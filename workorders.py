"""
Work Orders: community work orders from the inbox to Jobber to the community manager.

Office logins only. Every cycle (every 15 minutes, or "Run now"):

  1. Scan the inbox (simon@stahlman-england.com by default) for new work orders
     from a set-up community, save each one here and forward the email to the
     techs on the Settings tab (Regino and Fredy).
  2. Log each new work order as a note on that community's work order job in Jobber.
  3. Read new notes on that job from the tech (Regino by default), match each to
     its work order, fix the grammar, and save them as the technician's notes.
     A note that says a quote is needed marks the work order "Quote being
     prepared" and drafts a Jobber quote with the technician's notes on it.
  4. Draft an update email to the community manager (Erwin for Verona Walk) with
     the new technician's notes. It is sent from the Emails tab, or on its own
     when "Send manager emails automatically" is on.

Email goes through the Microsoft 365 connection the PO app already uses (Graph,
needs Mail.Read and Mail.Send). Jobber goes through the Jobber app already
connected for Pumps (the Cash Flow one is read-only). Grammar and matching use
Claude (ANTHROPIC_API_KEY).

Hooked into app.py with init_workorders(...).
"""
import html
import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests as http_requests
from flask import Blueprint, jsonify, redirect, render_template_string, request, session, url_for

try:
    import fcntl
except ImportError:  # Windows dev machines
    fcntl = None

TZ = ZoneInfo('America/New_York')
GRAPH = 'https://graph.microsoft.com/v1.0'
CLAUDE_MODEL = 'claude-opus-5-5'
# Our own Jobber notes start with this so the tech-note scan never reads them back.
NOTE_MARK = '[Office App]'
STATUSES = ('open', 'quote', 'closed')
# Optional: exactly these usernames get access (e.g. "simon,beatriz"). Unset = every office login.
WORKORDERS_USERS = {u.strip().lower() for u in os.environ.get('WORKORDERS_USERS', '').split(',') if u.strip()}

DEFAULT_SETTINGS = {
    'inbox': 'simon@stahlman-england.com',
    'forward_to': '',            # Regino's and Fredy's emails, comma separated
    'tech_name': 'Regino',       # whose Jobber notes count as technician's notes
    'keywords': 'work order, workorder, work-order, w/o',
    'auto_send': False,          # send manager emails without review
    'enabled': True,             # run the cycle on the schedule
}

bp = Blueprint('workorders', __name__)
_cfg = {}
_run_lock = threading.Lock()


# ── Plumbing ─────────────────────────────────────────────────────────────────

def _now():
    return datetime.now(TZ)


def _stamp():
    return _now().strftime('%Y-%m-%d %H:%M:%S')


def _conn():
    conn = sqlite3.connect(_cfg['db_path'], timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS wo_inbox_communities (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  keywords TEXT DEFAULT '',
                  manager_name TEXT DEFAULT '',
                  manager_email TEXT DEFAULT '',
                  jobber_job TEXT DEFAULT '',
                  jobber_job_id TEXT DEFAULT '',
                  jobber_client_id TEXT DEFAULT '',
                  jobber_property_id TEXT DEFAULT '',
                  active INTEGER DEFAULT 1,
                  created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS wo_inbox_orders (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  message_id TEXT UNIQUE,
                  community_id INTEGER,
                  subject TEXT DEFAULT '',
                  sender TEXT DEFAULT '',
                  received_at TEXT,
                  body TEXT DEFAULT '',
                  wo_number TEXT DEFAULT '',
                  address TEXT DEFAULT '',
                  description TEXT DEFAULT '',
                  status TEXT DEFAULT 'open',
                  forwarded_at TEXT,
                  forward_error TEXT DEFAULT '',
                  jobber_logged_at TEXT,
                  jobber_error TEXT DEFAULT '',
                  tech_notes TEXT DEFAULT '',
                  notes_updated_at TEXT,
                  quote_status TEXT DEFAULT '',
                  jobber_quote_id TEXT DEFAULT '',
                  jobber_quote_number TEXT DEFAULT '',
                  jobber_quote_url TEXT DEFAULT '',
                  quote_error TEXT DEFAULT '',
                  emailed_at TEXT,
                  created_at TEXT,
                  updated_at TEXT)''')
    # Every tech note read from Jobber, matched or not. jobber_note_id doubles as the "seen" list.
    c.execute('''CREATE TABLE IF NOT EXISTS wo_inbox_tech_notes (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  jobber_note_id TEXT UNIQUE,
                  community_id INTEGER,
                  order_id INTEGER,
                  author TEXT DEFAULT '',
                  noted_at TEXT,
                  raw TEXT DEFAULT '',
                  cleaned TEXT DEFAULT '',
                  needs_quote INTEGER DEFAULT 0,
                  created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS wo_inbox_emails (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  community_id INTEGER,
                  to_email TEXT DEFAULT '',
                  subject TEXT DEFAULT '',
                  body TEXT DEFAULT '',
                  order_ids TEXT DEFAULT '[]',
                  status TEXT DEFAULT 'draft',
                  error TEXT DEFAULT '',
                  created_at TEXT,
                  sent_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS wo_inbox_activity (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  at TEXT,
                  kind TEXT,
                  message TEXT)''')
    conn.commit()
    conn.close()


def settings():
    s = dict(DEFAULT_SETTINGS)
    try:
        s.update(json.loads(_cfg['get_setting']('workorders_settings') or '{}'))
    except (TypeError, ValueError):
        pass
    return s


def _save_settings(s):
    _cfg['set_setting']('workorders_settings', json.dumps(s))


def _state(key, default=''):
    return _cfg['get_setting'](f'workorders_{key}') or default


def _set_state(key, value):
    _cfg['set_setting'](f'workorders_{key}', value)


def _log(kind, message):
    print(f"  🛠️ Work orders [{kind}]: {message}")
    try:
        conn = _conn()
        conn.execute("INSERT INTO wo_inbox_activity (at, kind, message) VALUES (?,?,?)", (_stamp(), kind, message[:2000]))
        conn.execute("DELETE FROM wo_inbox_activity WHERE id NOT IN (SELECT id FROM wo_inbox_activity ORDER BY id DESC LIMIT 500)")
        conn.commit()
        conn.close()
    except Exception:
        pass


def _emails(text):
    return [e.strip() for e in re.split(r'[,;\s]+', text or '') if '@' in e]


def _keywords(text):
    return [k.strip().lower() for k in (text or '').split(',') if k.strip()]


def _html_to_text(body):
    text = re.sub(r'(?is)<(script|style).*?</\1>', ' ', body or '')
    text = re.sub(r'(?i)<br\s*/?>|</p>|</div>|</tr>|</li>', '\n', text)
    text = html.unescape(re.sub(r'<[^>]+>', ' ', text))
    text = re.sub(r'[ \t\r\f\v]+', ' ', text)
    return re.sub(r'\n\s*\n+', '\n\n', text).strip()


def workorders_allowed():
    """Office logins only (optionally narrowed by WORKORDERS_USERS)."""
    if 'username' not in session or session.get('role') != 'office':
        return False
    if WORKORDERS_USERS:
        return session['username'].lower() in WORKORDERS_USERS
    return True


# ── Connections ──────────────────────────────────────────────────────────────

def graph_ready():
    return bool(_cfg.get('graph_enabled'))


def jobber_ready():
    try:
        return bool(_cfg['jobber_connected']())
    except Exception:
        return False


def claude_ready():
    return _cfg.get('anthropic_client') is not None


def _graph(method, path, **kw):
    token = _cfg['graph_token']()
    r = http_requests.request(method, GRAPH + path, timeout=60,
                              headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}, **kw)
    if r.status_code >= 400:
        try:
            detail = (r.json().get('error') or {}).get('message') or r.text[:300]
        except ValueError:
            detail = r.text[:300]
        raise RuntimeError(f'Microsoft 365 said HTTP {r.status_code}: {detail}')
    return r.json() if r.content else {}


# The only Jobber changes Work Orders may make: notes on the work order job and
# draft quotes. Nothing is sent to a client from Jobber by this app.
ALLOWED_MUTATIONS = ('jobCreateNote', 'quoteCreate')
JOBBER_GQL = 'https://api.getjobber.com/api/graphql'


def _jobber(query, variables=None):
    if re.match(r'\s*mutation\b', query):
        called = re.findall(r'\{\s*(\w+)\s*\(', query)[:1]
        if not called or called[0] not in ALLOWED_MUTATIONS:
            raise RuntimeError(f'Blocked Jobber change {called}: Work Orders only adds job notes and draft quotes.')
    force = False
    for _ in range(4):
        token = _cfg['jobber_token'](force)
        r = http_requests.post(JOBBER_GQL, timeout=60, json={'query': query, 'variables': variables or {}},
                               headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json',
                                        'X-JOBBER-GRAPHQL-VERSION': _cfg['jobber_version']})
        if r.status_code == 401 and not force:
            force = True
            continue
        if r.status_code == 429:
            threading.Event().wait(20)
            continue
        if r.status_code >= 400:
            raise RuntimeError(f'Jobber API HTTP {r.status_code}')
        out = r.json()
        errors = out.get('errors') or []
        if errors:
            if any((e.get('extensions') or {}).get('code') == 'THROTTLED' for e in errors):
                threading.Event().wait(15)
                continue
            raise RuntimeError(' | '.join(e.get('message', '?') for e in errors))
        return out.get('data') or {}
    raise RuntimeError('Jobber kept refusing the request (signed out or rate limited)')


def _claude_json(system, prompt, schema):
    """One Claude call that returns JSON matching schema, or None if Claude is unavailable or declines."""
    client = _cfg.get('anthropic_client')
    if client is None:
        return None
    resp = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=4000, system=system,
        messages=[{'role': 'user', 'content': prompt}],
        extra_body={'output_config': {'effort': 'low', 'format': {'type': 'json_schema', 'schema': schema}}})
    if resp.stop_reason == 'refusal':
        return None
    text = ''.join(b.text for b in resp.content if b.type == 'text')
    try:
        return json.loads(text)
    except ValueError:
        return None


# ── 1. Inbox scan + forward ──────────────────────────────────────────────────

_EXTRACT_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['is_work_order', 'wo_number', 'address', 'description'],
    'properties': {
        'is_work_order': {'type': 'boolean'},
        'wo_number': {'type': 'string'},
        'address': {'type': 'string'},
        'description': {'type': 'string'},
    },
}


def _extract_order(subject, text, community):
    got = _claude_json(
        'You read emails sent to an irrigation and landscape company. Decide whether the email is a NEW work '
        'order request from a community (not a reply about an existing one, not an invoice, not marketing). '
        'Pull out the work order number if there is one (else ""), the street address or unit/lot (else ""), and '
        'a one or two sentence description of the work asked for, in plain English.',
        f'Community: {community}\nSubject: {subject}\n\nEmail:\n{text[:12000]}',
        _EXTRACT_SCHEMA)
    if got is not None:
        return got
    # No Claude: trust the keyword match and keep the email as-is.
    m = re.search(r'(?i)work\s*-?\s*order\s*(?:#|no\.?|number)?\s*:?\s*([A-Z0-9][A-Z0-9\-]{2,})', subject + '\n' + text)
    return {'is_work_order': True, 'wo_number': m.group(1) if m else '', 'address': '',
            'description': (text[:400] + '…') if len(text) > 400 else text}


def _match_community(communities, text):
    low = text.lower()
    for com in communities:
        keys = _keywords(com['keywords']) or [com['name'].lower()]
        if any(k in low for k in keys):
            return com
    return None


def scan_inbox():
    s = settings()
    if not graph_ready():
        return _log('inbox', 'Skipped: Microsoft 365 is not connected (MS_TENANT_ID / MS_CLIENT_ID / MS_CLIENT_SECRET).')
    inbox = s['inbox'].strip()
    conn = _conn()
    communities = [dict(r) for r in conn.execute("SELECT * FROM wo_inbox_communities WHERE active=1")]
    conn.close()
    if not communities:
        return _log('inbox', 'Skipped: no communities set up yet.')

    since = _state('last_scan') or (datetime.now(timezone.utc) - timedelta(days=3)).strftime('%Y-%m-%dT%H:%M:%SZ')
    # Overlap the next scan by 15 minutes for mail that lands late; message ids stop doubles.
    scan_started = (datetime.now(timezone.utc) - timedelta(minutes=15)).strftime('%Y-%m-%dT%H:%M:%SZ')
    path = f'/users/{inbox}/mailFolders/inbox/messages'
    params = {'$filter': f'receivedDateTime ge {since}', '$orderby': 'receivedDateTime asc', '$top': 50,
              '$select': 'id,subject,from,receivedDateTime,body'}
    messages = []
    data = _graph('GET', path, params=params)
    messages.extend(data.get('value', []))
    while data.get('@odata.nextLink') and len(messages) < 500:
        token = _cfg['graph_token']()
        r = http_requests.get(data['@odata.nextLink'], headers={'Authorization': f'Bearer {token}'}, timeout=60)
        r.raise_for_status()
        data = r.json()
        messages.extend(data.get('value', []))

    ignore_from = {e.lower() for e in _emails(s['forward_to'])} | {inbox.lower()}
    wo_keys = _keywords(s['keywords'])
    new = 0
    for m in messages:
        sender = ((m.get('from') or {}).get('emailAddress') or {}).get('address', '').lower()
        subject = m.get('subject') or ''
        if sender in ignore_from or re.match(r'(?i)^\s*re\s*:', subject):
            continue
        conn = _conn()
        seen = conn.execute("SELECT 1 FROM wo_inbox_orders WHERE message_id=?", (m['id'],)).fetchone()
        conn.close()
        if seen:
            continue
        body = m.get('body') or {}
        text = _html_to_text(body.get('content', '')) if body.get('contentType') == 'html' else (body.get('content') or '')
        haystack = f'{subject}\n{text}'
        if not any(k in haystack.lower() for k in wo_keys):
            continue
        com = _match_community(communities, haystack)
        if not com:
            continue
        info = _extract_order(subject, text, com['name'])
        if not info.get('is_work_order'):
            continue
        now = _stamp()
        conn = _conn()
        cur = conn.execute('''INSERT OR IGNORE INTO wo_inbox_orders (message_id, community_id, subject, sender, received_at, body,
                               wo_number, address, description, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                           (m['id'], com['id'], subject, sender, m.get('receivedDateTime', ''), text[:20000],
                            info.get('wo_number', ''), info.get('address', ''), info.get('description', ''), now, now))
        order_id = cur.lastrowid if cur.rowcount else None
        conn.commit()
        conn.close()
        if not order_id:
            continue
        new += 1
        _log('inbox', f"New work order #{order_id} for {com['name']}: {subject}")
        _forward(order_id, m['id'], com, s)
    _set_state('last_scan', scan_started)
    _log('inbox', f'Scanned {len(messages)} email(s) in {inbox}; {new} new work order(s).')


def _forward(order_id, message_id, com, s):
    to = _emails(s['forward_to'])
    if not to:
        _set_order(order_id, forward_error='No tech emails on the Settings tab')
        return _log('forward', f'Work order #{order_id} not forwarded: add Regino\'s and Fredy\'s emails on the Settings tab.')
    try:
        _graph('POST', f"/users/{s['inbox'].strip()}/messages/{message_id}/forward", json={
            'comment': f"New work order for {com['name']}. It is logged in the Office App and on the Jobber work order job.",
            'toRecipients': [{'emailAddress': {'address': a}} for a in to]})
        _set_order(order_id, forwarded_at=_stamp(), forward_error='')
        _log('forward', f"Work order #{order_id} forwarded to {', '.join(to)}.")
    except Exception as e:
        _set_order(order_id, forward_error=str(e)[:500])
        _log('forward', f'Work order #{order_id} forward failed: {e}')


def _set_order(order_id, **fields):
    fields['updated_at'] = _stamp()
    conn = _conn()
    conn.execute(f"UPDATE wo_inbox_orders SET {', '.join(k + '=?' for k in fields)} WHERE id=?",
                 list(fields.values()) + [order_id])
    conn.commit()
    conn.close()


def retry_forward(order_id):
    conn = _conn()
    row = conn.execute('''SELECT o.message_id, c.* FROM wo_inbox_orders o JOIN wo_inbox_communities c ON c.id=o.community_id
                          WHERE o.id=?''', (order_id,)).fetchone()
    conn.close()
    if row:
        _forward(order_id, row['message_id'], dict(row), settings())


# ── 2. Jobber: the community's work order job ────────────────────────────────

def _resolve_job(com):
    """Turn the job number typed on the Communities tab into Jobber's ids (cached on the row)."""
    if com.get('jobber_job_id'):
        return com
    ref = (com.get('jobber_job') or '').strip().lstrip('#')
    if not ref:
        raise RuntimeError(f"No Jobber work order job set for {com['name']}")
    if ref.isdigit():
        data = _jobber('''query($q: String!) { jobs(searchTerm: $q, first: 10) {
                              nodes { id jobNumber title client { id } property { id } } } }''', {'q': ref})
        nodes = ((data.get('jobs') or {}).get('nodes')) or []
        job = next((n for n in nodes if str(n.get('jobNumber')) == ref), None)
    else:
        data = _jobber('query($id: EncodedId!) { job(id: $id) { id jobNumber title client { id } property { id } } }', {'id': ref})
        job = data.get('job')
    if not job:
        raise RuntimeError(f'Jobber has no job #{ref}')
    com['jobber_job_id'] = job['id']
    com['jobber_client_id'] = (job.get('client') or {}).get('id', '')
    com['jobber_property_id'] = (job.get('property') or {}).get('id', '')
    conn = _conn()
    conn.execute("UPDATE wo_inbox_communities SET jobber_job_id=?, jobber_client_id=?, jobber_property_id=? WHERE id=?",
                 (com['jobber_job_id'], com['jobber_client_id'], com['jobber_property_id'], com['id']))
    conn.commit()
    conn.close()
    return com


def _job_note(job_id, message):
    data = _jobber('''mutation($jobId: EncodedId!, $input: JobCreateNoteInput!) {
                          jobCreateNote(jobId: $jobId, input: $input) { userErrors { message } } }''',
                   {'jobId': job_id, 'input': {'message': f'{NOTE_MARK} {message}'}})
    errs = ((data.get('jobCreateNote') or {}).get('userErrors')) or []
    if errs:
        raise RuntimeError('; '.join(e.get('message', '?') for e in errs))


def log_to_jobber():
    if not jobber_ready():
        return _log('jobber', 'Skipped: Jobber is not connected (connect it in the Pumps app).')
    conn = _conn()
    rows = [dict(r) for r in conn.execute('''SELECT o.id, o.wo_number, o.address, o.description, o.received_at, o.community_id
                                             FROM wo_inbox_orders o WHERE o.jobber_logged_at IS NULL AND o.status != 'closed' ''')]
    coms = {r['id']: dict(r) for r in conn.execute("SELECT * FROM wo_inbox_communities")}
    conn.close()
    for o in rows:
        com = coms.get(o['community_id'])
        if not com or not (com.get('jobber_job') or com.get('jobber_job_id')):
            continue
        try:
            com = _resolve_job(com)
            label = f"Work order {o['wo_number']}" if o['wo_number'] else f"Work order (Office App #{o['id']})"
            where = f" at {o['address']}" if o['address'] else ''
            _job_note(com['jobber_job_id'], f"OUTSTANDING - {label}{where}, received {(o['received_at'] or '')[:10]}: {o['description']}")
            _set_order(o['id'], jobber_logged_at=_stamp(), jobber_error='')
            _log('jobber', f"Work order #{o['id']} logged on the {com['name']} work order job.")
        except Exception as e:
            _set_order(o['id'], jobber_error=str(e)[:500])
            _log('jobber', f"Work order #{o['id']} not logged in Jobber: {e}")


# ── 3. Tech notes from Jobber ────────────────────────────────────────────────

_NOTES_Q = '''query($id: EncodedId!) { job(id: $id) { notes(first: 50) { nodes {
                ... on JobNote { id message createdAt %s } } } } }'''
_NOTES_AUTHOR = 'createdBy { ... on User { name { full } } }'

_MATCH_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['work_order_id', 'cleaned_notes', 'needs_quote', 'quote_scope'],
    'properties': {
        'work_order_id': {'type': 'integer', 'description': 'id of the matching open work order, or 0 if none fits'},
        'cleaned_notes': {'type': 'string'},
        'needs_quote': {'type': 'boolean'},
        'quote_scope': {'type': 'string'},
    },
}


def _job_notes(job_id):
    try:
        data = _jobber(_NOTES_Q % _NOTES_AUTHOR, {'id': job_id})
        with_author = True
    except Exception:
        # Older API versions shape createdBy differently; fall back to every note that is not ours.
        data = _jobber(_NOTES_Q % '', {'id': job_id})
        with_author = False
    nodes = ((((data.get('job') or {}).get('notes')) or {}).get('nodes')) or []
    out = []
    for n in nodes:
        if not n or not n.get('id') or not n.get('message'):
            continue
        author = (((n.get('createdBy') or {}).get('name')) or {}).get('full', '') if with_author else ''
        out.append({'id': n['id'], 'message': n['message'], 'created_at': n.get('createdAt', ''),
                    'author': author, 'author_known': with_author})
    return out


def _clean_and_match(note, orders, tech):
    listing = '\n'.join(f"- id {o['id']}: WO {o['wo_number'] or '(no number)'}, {o['address'] or '(no address)'}: {o['description']}"
                        for o in orders) or '(none)'
    got = _claude_json(
        'You help an irrigation company office. A technician wrote a note on a Jobber job after a site visit. '
        '1) Pick which open work order the note is about (by work order number, address, or the problem '
        'described); use 0 if none clearly fits. 2) Rewrite the note with correct spelling, grammar and '
        'punctuation so it can go to the community manager. Keep every fact, part, quantity and location; do '
        'not add anything; keep it in the technician\'s voice, short and plain. 3) needs_quote is true only if '
        'the note says more work must be quoted or approved before it can be done; quote_scope then says '
        'what needs quoting in one sentence, else "".',
        f'Technician: {tech}\n\nOpen work orders:\n{listing}\n\nNote:\n{note}',
        _MATCH_SCHEMA)
    if got is None:
        only = orders[0]['id'] if len(orders) == 1 else 0
        return {'work_order_id': only, 'cleaned_notes': note.strip(), 'needs_quote': False, 'quote_scope': ''}
    return got


def scan_tech_notes():
    if not jobber_ready():
        return _log('notes', 'Skipped: Jobber is not connected.')
    s = settings()
    tech = s['tech_name'].strip()
    conn = _conn()
    coms = [dict(r) for r in conn.execute("SELECT * FROM wo_inbox_communities WHERE active=1 AND (jobber_job != '' OR jobber_job_id != '')")]
    conn.close()
    for com in coms:
        try:
            com = _resolve_job(com)
            notes = _job_notes(com['jobber_job_id'])
        except Exception as e:
            _log('notes', f"Could not read notes on the {com['name']} job: {e}")
            continue
        conn = _conn()
        seen = {r[0] for r in conn.execute("SELECT jobber_note_id FROM wo_inbox_tech_notes WHERE community_id=?", (com['id'],))}
        orders = [dict(r) for r in conn.execute('''SELECT id, wo_number, address, description, created_at FROM wo_inbox_orders
                                                   WHERE community_id=? AND status != 'closed' ORDER BY id''', (com['id'],))]
        conn.close()
        first_scan = not seen
        for n in notes:
            if n['id'] in seen or n['message'].startswith(NOTE_MARK):
                continue
            if n['author_known'] and tech and tech.lower() not in n['author'].lower():
                continue
            if first_scan and orders and n['created_at'] and n['created_at'][:10] < min(o['created_at'] for o in orders)[:10]:
                # Older than every work order here: history, not a new visit.
                _store_note(n, com, None, '', False)
                continue
            if not orders:
                _store_note(n, com, None, '', False)
                continue
            try:
                got = _clean_and_match(n['message'], orders, tech)
            except Exception as e:
                _log('notes', f'Claude could not read a note on the {com["name"]} job: {e}')
                continue
            oid = got.get('work_order_id') or None
            if oid not in {o['id'] for o in orders}:
                oid = None
            _store_note(n, com, oid, got.get('cleaned_notes', ''), bool(got.get('needs_quote')))
            if oid:
                _apply_note(oid)
                _log('notes', f"{tech}'s note added to work order #{oid}.")
                if got.get('needs_quote'):
                    start_quote(oid, got.get('quote_scope', ''))
            else:
                _log('notes', f"A note from {n['author'] or tech} on the {com['name']} job did not match a work order; assign it on the Work Orders tab.")


def _store_note(n, com, order_id, cleaned, needs_quote):
    conn = _conn()
    conn.execute('''INSERT OR IGNORE INTO wo_inbox_tech_notes (jobber_note_id, community_id, order_id, author, noted_at, raw,
                    cleaned, needs_quote, created_at) VALUES (?,?,?,?,?,?,?,?,?)''',
                 (n['id'], com['id'], order_id, n.get('author', ''), n.get('created_at', ''), n['message'],
                  cleaned, 1 if needs_quote else 0, _stamp()))
    conn.commit()
    conn.close()


def _apply_note(order_id):
    """Rebuild the work order's technician's notes from every note assigned to it."""
    conn = _conn()
    rows = conn.execute('''SELECT noted_at, cleaned, raw FROM wo_inbox_tech_notes WHERE order_id=? ORDER BY noted_at, id''',
                        (order_id,)).fetchall()
    conn.close()
    parts = []
    for r in rows:
        when = (r['noted_at'] or '')[:10]
        parts.append(f"{when}: {r['cleaned'] or r['raw']}" if when else (r['cleaned'] or r['raw']))
    _set_order(order_id, tech_notes='\n\n'.join(parts), notes_updated_at=_stamp())


def assign_note(note_id, order_id):
    conn = _conn()
    note = conn.execute("SELECT * FROM wo_inbox_tech_notes WHERE id=?", (note_id,)).fetchone()
    conn.close()
    if not note:
        return
    cleaned = note['cleaned'] or note['raw']
    conn = _conn()
    conn.execute("UPDATE wo_inbox_tech_notes SET order_id=?, cleaned=? WHERE id=?", (order_id, cleaned, note_id))
    conn.commit()
    conn.close()
    _apply_note(order_id)
    if note['needs_quote']:
        start_quote(order_id)


# ── 3b. Quotes ───────────────────────────────────────────────────────────────

def start_quote(order_id, scope=''):
    """Mark the work order "Quote being prepared" and draft a Jobber quote with the technician's notes."""
    conn = _conn()
    o = conn.execute('''SELECT o.*, c.name AS community_name, c.jobber_job, c.jobber_job_id, c.jobber_client_id, c.jobber_property_id
                        FROM wo_inbox_orders o JOIN wo_inbox_communities c ON c.id=o.community_id WHERE o.id=?''', (order_id,)).fetchone()
    com = conn.execute("SELECT * FROM wo_inbox_communities WHERE id=?", (o['community_id'],)).fetchone() if o else None
    conn.close()
    if not o:
        return
    o = dict(o)
    if o['jobber_quote_id']:
        return
    _set_order(order_id, status='quote', quote_status='Quote being prepared', quote_error='', notes_updated_at=_stamp())
    _log('quote', f'Work order #{order_id}: quote being prepared.')
    if not jobber_ready():
        return _set_order(order_id, quote_error='Jobber is not connected')
    try:
        c = _resolve_job(dict(com))
        if not c.get('jobber_client_id'):
            raise RuntimeError('the work order job has no client in Jobber')
        label = f"Work order {o['wo_number']}" if o['wo_number'] else f"Work order #{o['id']}"
        title = f"{o['community_name']} - {label}" + (f" - {o['address']}" if o['address'] else '')
        message = "Technician's notes:\n" + (o['tech_notes'] or '(none yet)')
        attrs = {'clientId': c['jobber_client_id'], 'title': title[:250], 'message': message[:5000],
                 'lineItems': [{'name': (scope or o['description'] or label)[:250],
                                'description': "Technician's notes:\n" + (o['tech_notes'] or '')[:4000],
                                'quantity': 1, 'unitPrice': 0, 'saveToProductsAndServices': False}]}
        if c.get('jobber_property_id'):
            attrs['propertyId'] = c['jobber_property_id']
        data = _jobber('''mutation($attributes: QuoteCreateAttributes!) { quoteCreate(attributes: $attributes) {
                              quote { id quoteNumber jobberWebUri } userErrors { message } } }''', {'attributes': attrs})
        res = data.get('quoteCreate') or {}
        errs = res.get('userErrors') or []
        if errs:
            raise RuntimeError('; '.join(e.get('message', '?') for e in errs))
        q = res.get('quote') or {}
        _set_order(order_id, jobber_quote_id=q.get('id', ''), jobber_quote_number=str(q.get('quoteNumber') or ''),
                   jobber_quote_url=q.get('jobberWebUri') or '', quote_status='Quote being prepared')
        _log('quote', f"Work order #{order_id}: draft quote #{q.get('quoteNumber')} made in Jobber with the technician's notes. Add prices before sending it.")
        try:
            _job_note(c['jobber_job_id'], f"Quote being prepared for {label} (draft quote #{q.get('quoteNumber')}).")
        except Exception:
            pass
    except Exception as e:
        _set_order(order_id, quote_error=str(e)[:500])
        _log('quote', f'Work order #{order_id}: Jobber quote not drafted: {e}')


# ── 4. Email to the community manager ────────────────────────────────────────

def _first_name(name):
    return (name or '').strip().split(' ')[0] or 'there'


def _compose(com, orders):
    lines = [f"Hi {_first_name(com['manager_name'])},", '',
             f"Here is an update on the {com['name']} work orders from our technician's latest visit:", '']
    for o in orders:
        label = f"Work order {o['wo_number']}" if o['wo_number'] else 'Work order'
        head = label + (f" - {o['address']}" if o['address'] else '')
        lines.append(head)
        if o['description']:
            lines.append(f"Request: {o['description']}")
        lines.append("Technician's notes:")
        lines.append(o['tech_notes'] or '')
        if o['status'] == 'quote':
            lines.append('A quote is being prepared for this work order and will follow shortly.')
        elif o['status'] == 'closed':
            lines.append('This work order is complete.')
        lines.append('')
    lines += ['Please let us know if you have any questions.', '', 'Thank you,', 'Stahlman-England Irrigation']
    return '\n'.join(lines)


def draft_manager_emails():
    s = settings()
    conn = _conn()
    coms = [dict(r) for r in conn.execute("SELECT * FROM wo_inbox_communities WHERE active=1")]
    conn.close()
    for com in coms:
        conn = _conn()
        orders = [dict(r) for r in conn.execute('''SELECT * FROM wo_inbox_orders WHERE community_id=? AND tech_notes != ''
                                                   AND (emailed_at IS NULL OR notes_updated_at > emailed_at) ORDER BY id''', (com['id'],))]
        draft = conn.execute("SELECT * FROM wo_inbox_emails WHERE community_id=? AND status='draft' ORDER BY id DESC LIMIT 1",
                             (com['id'],)).fetchone()
        conn.close()
        if not orders:
            continue
        ids = [o['id'] for o in orders]
        newest = max(o['notes_updated_at'] or '' for o in orders)
        if draft and json.loads(draft['order_ids'] or '[]') == ids and (draft['created_at'] or '') >= newest:
            continue  # nothing new since this draft was written (keeps any edits made to it)
        subject = f"{com['name']} work order update - {_now().strftime('%b %d, %Y').replace(' 0', ' ')}"
        body = _compose(com, orders)
        conn = _conn()
        if draft:
            conn.execute("UPDATE wo_inbox_emails SET to_email=?, subject=?, body=?, order_ids=?, created_at=? WHERE id=?",
                         (com['manager_email'], subject, body, json.dumps(ids), _stamp(), draft['id']))
            email_id = draft['id']
        else:
            email_id = conn.execute('''INSERT INTO wo_inbox_emails (community_id, to_email, subject, body, order_ids, status, created_at)
                                       VALUES (?,?,?,?,?, 'draft', ?)''',
                                    (com['id'], com['manager_email'], subject, body, json.dumps(ids), _stamp())).lastrowid
        conn.commit()
        conn.close()
        _log('email', f"Email to {com['manager_name'] or com['manager_email']} ({com['name']}) drafted with {len(ids)} work order(s).")
        if s.get('auto_send') and com['manager_email']:
            send_email(email_id)


def send_email(email_id):
    s = settings()
    conn = _conn()
    e = conn.execute("SELECT * FROM wo_inbox_emails WHERE id=?", (email_id,)).fetchone()
    conn.close()
    if not e or e['status'] == 'sent':
        return False, 'Already sent'
    to = _emails(e['to_email'])
    if not to:
        return False, 'No manager email address on this community'
    if not graph_ready():
        return False, 'Microsoft 365 is not connected'
    try:
        _graph('POST', f"/users/{s['inbox'].strip()}/sendMail", json={
            'message': {'subject': e['subject'], 'body': {'contentType': 'Text', 'content': e['body']},
                        'toRecipients': [{'emailAddress': {'address': a}} for a in to]},
            'saveToSentItems': True})
    except Exception as ex:
        conn = _conn()
        conn.execute("UPDATE wo_inbox_emails SET error=? WHERE id=?", (str(ex)[:500], email_id))
        conn.commit()
        conn.close()
        _log('email', f'Email #{email_id} not sent: {ex}')
        return False, str(ex)
    now = _stamp()
    conn = _conn()
    conn.execute("UPDATE wo_inbox_emails SET status='sent', sent_at=?, error='' WHERE id=?", (now, email_id))
    ids = json.loads(e['order_ids'] or '[]')
    if ids:
        conn.execute(f"UPDATE wo_inbox_orders SET emailed_at=? WHERE id IN ({','.join('?' * len(ids))})", [now] + ids)
    conn.commit()
    conn.close()
    _log('email', f"Email sent to {', '.join(to)}: {e['subject']}")
    return True, ''


# ── The cycle ────────────────────────────────────────────────────────────────

class _FileLock:
    """Only one gunicorn worker runs the cycle at a time."""

    def __init__(self):
        self.fh = None

    def __enter__(self):
        if not _run_lock.acquire(blocking=False):
            return False
        if fcntl:
            self.fh = open(os.path.join(_cfg['data_dir'], '.workorders_cycle.lock'), 'w')
            try:
                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.fh.close()
                self.fh = None
                _run_lock.release()
                return False
        return True

    def __exit__(self, *exc):
        if self.fh:
            fcntl.flock(self.fh, fcntl.LOCK_UN)
            self.fh.close()
            self.fh = None
        if _run_lock.locked():
            _run_lock.release()
        return False


def run_cycle(manual=False):
    if not manual and not settings().get('enabled'):
        return False
    with _FileLock() as got:
        if not got:
            return False
        for step in (scan_inbox, log_to_jobber, scan_tech_notes, draft_manager_emails):
            try:
                step()
            except Exception as e:
                _log(step.__name__, f'Failed: {e}')
        _set_state('last_run', _stamp())
    return True


# ── Pages and API ────────────────────────────────────────────────────────────

def _deny():
    if 'username' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))


@bp.route('/workorders')
def page():
    if not workorders_allowed():
        return _deny()
    return render_template_string(PAGE_TEMPLATE, full_name=session.get('full_name') or session.get('username'))


@bp.route('/workorders/api/data')
def api_data():
    if not workorders_allowed():
        return jsonify({'success': False, 'error': 'Office only'}), 403
    conn = _conn()
    orders = [dict(r) for r in conn.execute('''SELECT o.*, c.name AS community_name FROM wo_inbox_orders o
                                               LEFT JOIN wo_inbox_communities c ON c.id=o.community_id
                                               ORDER BY CASE o.status WHEN 'open' THEN 0 WHEN 'quote' THEN 1 ELSE 2 END, o.id DESC''')]
    for o in orders:
        o.pop('body', None)
    coms = [dict(r) for r in conn.execute("SELECT * FROM wo_inbox_communities ORDER BY name")]
    emails = [dict(r) for r in conn.execute('''SELECT e.*, c.name AS community_name, c.manager_name FROM wo_inbox_emails e
                                               LEFT JOIN wo_inbox_communities c ON c.id=e.community_id ORDER BY e.id DESC LIMIT 50''')]
    unmatched = [dict(r) for r in conn.execute('''SELECT n.id, n.raw, n.author, n.noted_at, n.community_id, c.name AS community_name
                                                  FROM wo_inbox_tech_notes n LEFT JOIN wo_inbox_communities c ON c.id=n.community_id
                                                  WHERE n.order_id IS NULL AND n.cleaned != '' ORDER BY n.id DESC LIMIT 50''')]
    activity = [dict(r) for r in conn.execute("SELECT at, kind, message FROM wo_inbox_activity ORDER BY id DESC LIMIT 100")]
    conn.close()
    return jsonify({'success': True, 'orders': orders, 'communities': coms, 'emails': emails, 'unmatched': unmatched,
                    'activity': activity, 'settings': settings(),
                    'status': {'graph': graph_ready(), 'jobber': jobber_ready(), 'claude': claude_ready(),
                               'last_run': _state('last_run'), 'last_scan': _state('last_scan')}})


@bp.route('/workorders/api/run', methods=['POST'])
def api_run():
    if not workorders_allowed():
        return jsonify({'success': False, 'error': 'Office only'}), 403
    threading.Thread(target=run_cycle, kwargs={'manual': True}, daemon=True).start()
    return jsonify({'success': True})


@bp.route('/workorders/api/settings', methods=['POST'])
def api_settings():
    if not workorders_allowed():
        return jsonify({'success': False, 'error': 'Office only'}), 403
    d = request.get_json(silent=True) or {}
    s = settings()
    for k in ('inbox', 'forward_to', 'tech_name', 'keywords'):
        if k in d:
            s[k] = str(d[k]).strip()[:1000]
    for k in ('auto_send', 'enabled'):
        if k in d:
            s[k] = bool(d[k])
    if '@' not in s['inbox']:
        return jsonify({'success': False, 'error': 'The inbox must be an email address'}), 400
    _save_settings(s)
    return jsonify({'success': True})


@bp.route('/workorders/api/community', methods=['POST'])
def api_community():
    if not workorders_allowed():
        return jsonify({'success': False, 'error': 'Office only'}), 403
    d = request.get_json(silent=True) or {}
    name = (d.get('name') or '').strip()
    conn = _conn()
    if d.get('delete') and d.get('id'):
        conn.execute("DELETE FROM wo_inbox_communities WHERE id=?", (d['id'],))
    else:
        if not name:
            conn.close()
            return jsonify({'success': False, 'error': 'Name is required'}), 400
        vals = (name, (d.get('keywords') or '').strip(), (d.get('manager_name') or '').strip(),
                (d.get('manager_email') or '').strip(), (d.get('jobber_job') or '').strip(), 1 if d.get('active', True) else 0)
        if d.get('id'):
            old = conn.execute("SELECT jobber_job FROM wo_inbox_communities WHERE id=?", (d['id'],)).fetchone()
            conn.execute('''UPDATE wo_inbox_communities SET name=?, keywords=?, manager_name=?, manager_email=?, jobber_job=?, active=?
                            WHERE id=?''', vals + (d['id'],))
            if old and old['jobber_job'] != vals[4]:
                conn.execute("UPDATE wo_inbox_communities SET jobber_job_id='', jobber_client_id='', jobber_property_id='' WHERE id=?", (d['id'],))
        else:
            conn.execute('''INSERT INTO wo_inbox_communities (name, keywords, manager_name, manager_email, jobber_job, active, created_at)
                            VALUES (?,?,?,?,?,?,?)''', vals + (_stamp(),))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@bp.route('/workorders/api/order', methods=['POST'])
def api_order():
    if not workorders_allowed():
        return jsonify({'success': False, 'error': 'Office only'}), 403
    d = request.get_json(silent=True) or {}
    oid = d.get('id')
    conn = _conn()
    o = conn.execute("SELECT id FROM wo_inbox_orders WHERE id=?", (oid,)).fetchone()
    conn.close()
    if not o:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    fields = {}
    for k in ('wo_number', 'address', 'description', 'tech_notes'):
        if k in d:
            fields[k] = str(d[k])[:10000]
    if 'tech_notes' in d:
        fields['notes_updated_at'] = _stamp()
    if d.get('status') in STATUSES:
        fields['status'] = d['status']
    if fields:
        _set_order(oid, **fields)
    action = d.get('action')
    if action == 'quote':
        threading.Thread(target=start_quote, args=(oid,), daemon=True).start()
    elif action == 'forward':
        threading.Thread(target=retry_forward, args=(oid,), daemon=True).start()
    elif action == 'relog':
        _set_order(oid, jobber_logged_at=None, jobber_error='')
        threading.Thread(target=log_to_jobber, daemon=True).start()
    return jsonify({'success': True})


@bp.route('/workorders/api/note/assign', methods=['POST'])
def api_assign_note():
    if not workorders_allowed():
        return jsonify({'success': False, 'error': 'Office only'}), 403
    d = request.get_json(silent=True) or {}
    if not d.get('note_id') or not d.get('order_id'):
        return jsonify({'success': False, 'error': 'Pick a work order'}), 400
    assign_note(int(d['note_id']), int(d['order_id']))
    return jsonify({'success': True})


@bp.route('/workorders/api/email', methods=['POST'])
def api_email():
    if not workorders_allowed():
        return jsonify({'success': False, 'error': 'Office only'}), 403
    d = request.get_json(silent=True) or {}
    eid = d.get('id')
    conn = _conn()
    e = conn.execute("SELECT status FROM wo_inbox_emails WHERE id=?", (eid,)).fetchone()
    if not e or e['status'] == 'sent':
        conn.close()
        return jsonify({'success': False, 'error': 'Not found or already sent'}), 400
    if d.get('discard'):
        conn.execute("UPDATE wo_inbox_emails SET status='discarded' WHERE id=?", (eid,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    conn.execute("UPDATE wo_inbox_emails SET to_email=?, subject=?, body=? WHERE id=?",
                 (str(d.get('to_email', '')).strip(), str(d.get('subject', ''))[:300], str(d.get('body', ''))[:20000], eid))
    conn.commit()
    conn.close()
    if d.get('send'):
        ok, err = send_email(eid)
        if not ok:
            return jsonify({'success': False, 'error': err}), 400
    return jsonify({'success': True})


def init_workorders(app, db_path, *, data_dir, get_setting, set_setting, graph_token, graph_enabled,
                    jobber_token, jobber_connected, jobber_version, anthropic_client=None, scheduler_cls=None):
    """Create the tables, register the routes and schedule the cycle every 15 minutes.
    jobber_token(force_refresh) hands over an access token from the Jobber app already
    connected for Pumps, so no new Jobber app is needed."""
    _cfg.update(db_path=db_path, data_dir=data_dir, get_setting=get_setting, set_setting=set_setting,
                graph_token=graph_token, graph_enabled=graph_enabled, jobber_token=jobber_token,
                jobber_connected=jobber_connected, jobber_version=jobber_version, anthropic_client=anthropic_client)
    init_db()
    app.register_blueprint(bp)
    if scheduler_cls and os.environ.get('WORKORDERS_AUTO_RUN', 'true').lower() not in ('0', 'false', 'no', 'off'):
        try:
            sched = scheduler_cls()
            sched.add_job(run_cycle, 'interval', minutes=15, id='workorders_cycle',
                          next_run_time=datetime.now() + timedelta(minutes=2))
            sched.start()
            print("✓ Work orders: inbox, Jobber and email cycle scheduled every 15 minutes")
        except Exception as e:
            print(f"⚠ Could not start the work orders scheduler: {e}")


PAGE_TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Work Orders — Stahlman-England</title>
<meta name="csrf-token" content="{{ csrf_token() }}">
<style>
  :root { --brand:#059669; --brand-dark:#047857; --brand-light:#ECFDF5; --ink:#0F172A; --ink2:#475569; --ink3:#94A3B8;
          --bg:#F8FAFC; --card:#FFF; --line:#E2E8F0; --warn:#B45309; --warn-bg:#FFFBEB; --bad:#DC2626; --bad-bg:#FEF2F2;
          --blue:#2563EB; --blue-bg:#EFF6FF; --shadow:0 1px 3px rgba(15,23,42,.06); }
  *,*::before,*::after { box-sizing:border-box; }
  body { margin:0; font-family:Inter,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; background:var(--bg); color:var(--ink); font-size:14px; line-height:1.45; }
  header { background:var(--card); border-bottom:1px solid var(--line); padding:12px 20px; display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
  header .brand { font-weight:700; font-size:17px; }
  header .pill { background:var(--brand-light); color:var(--brand-dark); border-radius:999px; padding:2px 10px; font-size:12px; font-weight:600; }
  header .spacer { flex:1; }
  a.back { color:var(--ink2); text-decoration:none; }
  main { max-width:1200px; margin:0 auto; padding:18px 16px 60px; }
  .status { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; }
  .chip { border-radius:999px; padding:3px 10px; font-size:12px; font-weight:600; border:1px solid var(--line); background:var(--card); }
  .chip.ok { color:var(--brand-dark); background:var(--brand-light); border-color:#A7F3D0; }
  .chip.no { color:var(--bad); background:var(--bad-bg); border-color:#FECACA; }
  .tabs { display:flex; gap:4px; border-bottom:1px solid var(--line); margin-bottom:14px; overflow-x:auto; }
  .tab { padding:8px 14px; cursor:pointer; color:var(--ink2); font-weight:600; border-bottom:2px solid transparent; white-space:nowrap; }
  .tab.active { color:var(--brand-dark); border-color:var(--brand); }
  .panel { display:none; } .panel.active { display:block; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; box-shadow:var(--shadow); padding:14px; margin-bottom:12px; }
  .row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  .muted { color:var(--ink2); } .small { font-size:12px; }
  button { font:inherit; border:1px solid var(--line); background:var(--card); border-radius:8px; padding:6px 12px; cursor:pointer; }
  button.primary { background:var(--brand); color:#fff; border-color:var(--brand); }
  button.danger { color:var(--bad); }
  input, textarea, select { font:inherit; border:1px solid var(--line); border-radius:8px; padding:7px 9px; width:100%; background:#fff; color:var(--ink); }
  textarea { min-height:90px; }
  label { display:block; font-weight:600; font-size:12px; color:var(--ink2); margin:8px 0 4px; }
  .grid2 { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:10px; }
  .badge { display:inline-block; border-radius:999px; padding:1px 8px; font-size:11px; font-weight:700; }
  .b-open { background:var(--blue-bg); color:var(--blue); } .b-quote { background:var(--warn-bg); color:var(--warn); } .b-closed { background:#F1F5F9; color:var(--ink2); }
  .wo h3 { margin:0; font-size:15px; }
  .steps { display:flex; gap:6px; flex-wrap:wrap; margin:8px 0; }
  .step { font-size:12px; padding:2px 8px; border-radius:6px; background:#F1F5F9; color:var(--ink2); }
  .step.done { background:var(--brand-light); color:var(--brand-dark); } .step.err { background:var(--bad-bg); color:var(--bad); }
  .notes { white-space:pre-wrap; background:#F8FAFC; border:1px solid var(--line); border-radius:8px; padding:8px 10px; margin-top:6px; }
  .empty { color:var(--ink3); text-align:center; padding:30px; }
  .filters { display:flex; gap:6px; margin-bottom:10px; flex-wrap:wrap; }
  .filters button.on { background:var(--ink); color:#fff; border-color:var(--ink); }
  table { width:100%; border-collapse:collapse; } td { padding:6px; border-bottom:1px solid var(--line); vertical-align:top; }
  .toast { position:fixed; bottom:16px; left:50%; transform:translateX(-50%); background:var(--ink); color:#fff; padding:8px 14px; border-radius:8px; display:none; }
</style>
</head>
<body>
<header>
  <a class="back" href="{{ url_for('dashboard') }}">← Home</a>
  <span class="brand">🛠️ Work Orders</span><span class="pill">Office</span>
  <span class="spacer"></span>
  <span class="muted small" id="lastRun"></span>
  <button class="primary" onclick="runNow()">Run now</button>
</header>
<main>
  <div class="status" id="status"></div>
  <div class="tabs">
    <div class="tab active" data-tab="orders">Work Orders</div>
    <div class="tab" data-tab="emails">Emails to Managers</div>
    <div class="tab" data-tab="communities">Communities</div>
    <div class="tab" data-tab="settings">Settings</div>
    <div class="tab" data-tab="activity">Activity</div>
  </div>

  <section class="panel active" id="p-orders">
    <div class="filters" id="filters"></div>
    <div id="unmatched"></div>
    <div id="orders"></div>
  </section>
  <section class="panel" id="p-emails"><div id="emails"></div></section>
  <section class="panel" id="p-communities">
    <div class="card">
      <strong>Add or edit a community</strong>
      <p class="muted small">Emails mentioning the community name or one of its keywords, plus a work order keyword, are picked up. The work order job is the Jobber job number where outstanding work orders get logged and where the tech leaves visit notes.</p>
      <input type="hidden" id="c-id">
      <div class="grid2">
        <div><label>Community</label><input id="c-name" placeholder="Verona Walk"></div>
        <div><label>Keywords (comma separated)</label><input id="c-keywords" placeholder="verona walk, verona"></div>
        <div><label>Manager name</label><input id="c-manager" placeholder="Erwin"></div>
        <div><label>Manager email</label><input id="c-email" placeholder="erwin@…"></div>
        <div><label>Jobber work order job number</label><input id="c-job" placeholder="e.g. 1234"></div>
      </div>
      <div class="row" style="margin-top:10px"><button class="primary" onclick="saveCommunity()">Save community</button><button onclick="clearCommunity()">Clear</button></div>
    </div>
    <div id="communities"></div>
  </section>
  <section class="panel" id="p-settings">
    <div class="card">
      <div class="grid2">
        <div><label>Inbox to scan</label><input id="s-inbox"></div>
        <div><label>Forward new work orders to (Regino, Fredy)</label><input id="s-forward" placeholder="regino@…, fredy@…"></div>
        <div><label>Technician whose Jobber notes are read</label><input id="s-tech"></div>
        <div><label>Work order keywords</label><input id="s-keywords"></div>
      </div>
      <label><input type="checkbox" id="s-enabled" style="width:auto"> Run automatically every 15 minutes</label>
      <label><input type="checkbox" id="s-auto" style="width:auto"> Send manager emails automatically (otherwise they wait on the Emails tab for you to send)</label>
      <div class="row" style="margin-top:10px"><button class="primary" onclick="saveSettings()">Save settings</button></div>
    </div>
    <div class="card small muted" id="setupHelp"></div>
  </section>
  <section class="panel" id="p-activity"><div class="card"><table id="activity"></table></div></section>
</main>
<div class="toast" id="toast"></div>
<script>
var D = null, FILTER = 'open';
var CSRF = document.querySelector('meta[name="csrf-token"]').content;
function esc(s){ return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
function toast(m){ var t=document.getElementById('toast'); t.textContent=m; t.style.display='block'; setTimeout(function(){ t.style.display='none'; }, 3000); }
function post(url, body){
  return fetch(url, {method:'POST', headers:{'Content-Type':'application/json','X-CSRFToken':CSRF}, body:JSON.stringify(body||{})})
    .then(function(r){ return r.json(); }).then(function(j){ if(!j.success){ toast(j.error || 'Something went wrong'); throw j; } return j; });
}
document.querySelectorAll('.tab').forEach(function(t){ t.onclick = function(){
  document.querySelectorAll('.tab').forEach(function(x){ x.classList.remove('active'); });
  document.querySelectorAll('.panel').forEach(function(x){ x.classList.remove('active'); });
  t.classList.add('active'); document.getElementById('p-'+t.dataset.tab).classList.add('active'); }; });

function load(){ fetch('/workorders/api/data').then(function(r){ return r.json(); }).then(function(j){ D=j; render(); }); }
function chip(ok, label){ return '<span class="chip '+(ok?'ok':'no')+'">'+(ok?'✓ ':'✗ ')+label+'</span>'; }
function render(){
  var st = D.status;
  document.getElementById('status').innerHTML = chip(st.graph,'Email (Microsoft 365)') + chip(st.jobber,'Jobber') + chip(st.claude,'Claude (grammar)');
  document.getElementById('lastRun').textContent = st.last_run ? 'Last run '+st.last_run : 'Not run yet';
  renderOrders(); renderEmails(); renderCommunities(); renderSettings(); renderActivity();
}
function renderOrders(){
  var counts = {open:0, quote:0, closed:0, all:D.orders.length};
  D.orders.forEach(function(o){ counts[o.status] = (counts[o.status]||0)+1; });
  var names = {open:'Outstanding', quote:'Quote being prepared', closed:'Closed', all:'All'};
  document.getElementById('filters').innerHTML = ['open','quote','closed','all'].map(function(k){
    return '<button class="'+(FILTER==k?'on':'')+'" onclick="FILTER=\''+k+'\';renderOrders()">'+names[k]+' ('+(counts[k]||0)+')</button>'; }).join('');
  var um = D.unmatched.filter(function(n){ return true; });
  document.getElementById('unmatched').innerHTML = um.length ? '<div class="card"><strong>Tech notes that did not match a work order</strong>' + um.map(function(n){
    var opts = D.orders.filter(function(o){ return o.community_id==n.community_id && o.status!='closed'; }).map(function(o){
      return '<option value="'+o.id+'">#'+o.id+' '+esc(o.wo_number||'')+' '+esc(o.address||o.description.slice(0,40))+'</option>'; }).join('');
    return '<div style="margin-top:8px"><div class="small muted">'+esc(n.community_name)+' · '+esc(n.author)+' · '+esc((n.noted_at||'').slice(0,10))+'</div><div class="notes">'+esc(n.raw)+'</div>'+
      '<div class="row" style="margin-top:6px"><select id="as-'+n.id+'" style="max-width:360px"><option value="">Pick a work order…</option>'+opts+'</select><button onclick="assignNote('+n.id+')">Add to work order</button></div></div>'; }).join('') + '</div>' : '';
  var list = D.orders.filter(function(o){ return FILTER=='all' || o.status==FILTER; });
  if(!list.length){ document.getElementById('orders').innerHTML = '<div class="empty">No work orders here.</div>'; return; }
  document.getElementById('orders').innerHTML = list.map(function(o){
    var stepF = o.forwarded_at ? '<span class="step done">✓ Forwarded to techs</span>' : (o.forward_error ? '<span class="step err" title="'+esc(o.forward_error)+'">✗ Not forwarded</span>' : '<span class="step">Forward pending</span>');
    var stepJ = o.jobber_logged_at ? '<span class="step done">✓ Logged in Jobber</span>' : (o.jobber_error ? '<span class="step err" title="'+esc(o.jobber_error)+'">✗ Not in Jobber</span>' : '<span class="step">Jobber pending</span>');
    var stepN = o.tech_notes ? '<span class="step done">✓ Tech notes</span>' : '<span class="step">Waiting on tech notes</span>';
    var stepQ = o.status=='quote' ? (o.jobber_quote_number ? '<span class="step done">✓ Draft quote #'+esc(o.jobber_quote_number)+'</span>' : (o.quote_error ? '<span class="step err" title="'+esc(o.quote_error)+'">✗ Quote not drafted</span>' : '<span class="step">Quote being prepared</span>')) : '';
    var stepE = o.emailed_at ? '<span class="step done">✓ Emailed manager</span>' : '';
    var errs = [o.forward_error, o.jobber_error, o.quote_error].filter(Boolean).map(function(e){ return '<div class="small" style="color:var(--bad)">'+esc(e)+'</div>'; }).join('');
    return '<div class="card wo"><div class="row"><h3>#'+o.id+' · '+esc(o.community_name||'')+(o.wo_number?' · WO '+esc(o.wo_number):'')+'</h3>'+
      '<span class="badge b-'+o.status+'">'+(o.status=='quote'?'Quote being prepared':o.status=='open'?'Outstanding':'Closed')+'</span>'+
      '<span class="spacer" style="flex:1"></span><span class="small muted">'+esc((o.received_at||'').slice(0,10))+' · '+esc(o.sender)+'</span></div>'+
      '<div class="small muted">'+esc(o.subject)+'</div>'+
      '<div class="steps">'+stepF+stepJ+stepN+stepQ+stepE+'</div>'+errs+
      '<div class="grid2"><div><label>WO number</label><input id="wn-'+o.id+'" value="'+esc(o.wo_number)+'"></div><div><label>Address</label><input id="wa-'+o.id+'" value="'+esc(o.address)+'"></div></div>'+
      '<label>Request</label><textarea id="wd-'+o.id+'" style="min-height:60px">'+esc(o.description)+'</textarea>'+
      '<label>Technician\'s notes</label><textarea id="wt-'+o.id+'">'+esc(o.tech_notes)+'</textarea>'+
      (o.jobber_quote_url ? '<div class="small" style="margin-top:6px"><a href="'+esc(o.jobber_quote_url)+'" target="_blank" rel="noopener">Open draft quote in Jobber →</a></div>' : '')+
      '<div class="row" style="margin-top:8px"><button class="primary" onclick="saveOrder('+o.id+')">Save</button>'+
      (o.status!='quote' ? '<button onclick="orderAction('+o.id+',\'quote\')">Needs a quote</button>' : '')+
      (!o.forwarded_at ? '<button onclick="orderAction('+o.id+',\'forward\')">Forward to techs</button>' : '')+
      (!o.jobber_logged_at ? '<button onclick="orderAction('+o.id+',\'relog\')">Log in Jobber</button>' : '')+
      (o.status!='closed' ? '<button onclick="setStatus('+o.id+',\'closed\')">Close</button>' : '<button onclick="setStatus('+o.id+',\'open\')">Reopen</button>')+'</div></div>';
  }).join('');
}
function saveOrder(id){ post('/workorders/api/order', {id:id, wo_number:val('wn-'+id), address:val('wa-'+id), description:val('wd-'+id), tech_notes:val('wt-'+id)}).then(function(){ toast('Saved'); load(); }); }
function orderAction(id, a){ post('/workorders/api/order', {id:id, action:a}).then(function(){ toast(a=='quote'?'Quote being prepared — drafting in Jobber':'Working on it'); setTimeout(load, 2500); }); }
function setStatus(id, s){ post('/workorders/api/order', {id:id, status:s}).then(load); }
function assignNote(nid){ var oid = val('as-'+nid); if(!oid){ toast('Pick a work order'); return; } post('/workorders/api/note/assign', {note_id:nid, order_id:oid}).then(function(){ toast('Note added'); load(); }); }
function val(id){ return document.getElementById(id).value; }

function renderEmails(){
  var list = D.emails.filter(function(e){ return e.status!='discarded'; });
  if(!list.length){ document.getElementById('emails').innerHTML = '<div class="empty">No manager emails yet. One is drafted when the tech adds notes to a work order.</div>'; return; }
  document.getElementById('emails').innerHTML = list.map(function(e){
    var sent = e.status=='sent';
    return '<div class="card"><div class="row"><strong>'+esc(e.community_name||'')+' → '+esc(e.manager_name||e.to_email)+'</strong><span class="badge '+(sent?'b-closed':'b-quote')+'">'+(sent?'Sent '+esc(e.sent_at):'Draft')+'</span></div>'+
      (e.error ? '<div class="small" style="color:var(--bad)">'+esc(e.error)+'</div>' : '')+
      '<label>To</label><input id="et-'+e.id+'" value="'+esc(e.to_email)+'"'+(sent?' disabled':'')+'>'+
      '<label>Subject</label><input id="es-'+e.id+'" value="'+esc(e.subject)+'"'+(sent?' disabled':'')+'>'+
      '<label>Message</label><textarea id="eb-'+e.id+'" style="min-height:220px"'+(sent?' disabled':'')+'>'+esc(e.body)+'</textarea>'+
      (sent ? '' : '<div class="row" style="margin-top:8px"><button class="primary" onclick="emailAct('+e.id+',true)">Send</button><button onclick="emailAct('+e.id+',false)">Save draft</button><button class="danger" onclick="discard('+e.id+')">Discard</button></div>')+'</div>';
  }).join('');
}
function emailAct(id, send){ post('/workorders/api/email', {id:id, to_email:val('et-'+id), subject:val('es-'+id), body:val('eb-'+id), send:send}).then(function(){ toast(send?'Sent':'Saved'); load(); }); }
function discard(id){ if(confirm('Discard this draft?')) post('/workorders/api/email', {id:id, discard:true}).then(load); }

function renderCommunities(){
  if(!D.communities.length){ document.getElementById('communities').innerHTML = '<div class="empty">No communities yet. Add Verona Walk above.</div>'; return; }
  document.getElementById('communities').innerHTML = '<div class="card"><table>' + D.communities.map(function(c){
    return '<tr><td><strong>'+esc(c.name)+'</strong><div class="small muted">'+esc(c.keywords)+'</div></td><td>'+esc(c.manager_name)+'<div class="small muted">'+esc(c.manager_email)+'</div></td>'+
      '<td>Job '+esc(c.jobber_job||'—')+(c.jobber_job_id?' <span class="small muted">✓ found in Jobber</span>':'')+'</td>'+
      '<td style="text-align:right"><button onclick="editCommunity('+c.id+')">Edit</button> <button class="danger" onclick="deleteCommunity('+c.id+')">Delete</button></td></tr>'; }).join('') + '</table></div>';
}
function editCommunity(id){ var c = D.communities.find(function(x){ return x.id==id; });
  document.getElementById('c-id').value=c.id; document.getElementById('c-name').value=c.name; document.getElementById('c-keywords').value=c.keywords;
  document.getElementById('c-manager').value=c.manager_name; document.getElementById('c-email').value=c.manager_email; document.getElementById('c-job').value=c.jobber_job; }
function clearCommunity(){ ['c-id','c-name','c-keywords','c-manager','c-email','c-job'].forEach(function(i){ document.getElementById(i).value=''; }); }
function saveCommunity(){ post('/workorders/api/community', {id:val('c-id')||null, name:val('c-name'), keywords:val('c-keywords'), manager_name:val('c-manager'), manager_email:val('c-email'), jobber_job:val('c-job')}).then(function(){ toast('Saved'); clearCommunity(); load(); }); }
function deleteCommunity(id){ if(confirm('Delete this community? Its work orders stay.')) post('/workorders/api/community', {id:id, delete:true}).then(load); }

function renderSettings(){
  var s = D.settings;
  document.getElementById('s-inbox').value=s.inbox; document.getElementById('s-forward').value=s.forward_to; document.getElementById('s-tech').value=s.tech_name;
  document.getElementById('s-keywords').value=s.keywords; document.getElementById('s-enabled').checked=!!s.enabled; document.getElementById('s-auto').checked=!!s.auto_send;
  var st = D.status, h = [];
  if(!st.graph) h.push('<b>Email:</b> set MS_TENANT_ID, MS_CLIENT_ID and MS_CLIENT_SECRET on the service (the same Microsoft 365 app the PO inbox uses). The app needs the Mail.Read and Mail.Send application permissions with admin consent so it can read '+esc(s.inbox)+' and send from it.');
  if(!st.jobber) h.push('<b>Jobber:</b> this uses the Jobber app already connected for Pumps. Connect Jobber in the Pumps app. Drafting quotes needs write access to quotes on that Jobber app; if quotes fail with a permission error, add that scope in Jobber\'s Developer Center and reconnect.');
  if(!st.claude) h.push('<b>Grammar:</b> set ANTHROPIC_API_KEY so tech notes are cleaned up and matched to work orders. Without it notes are copied as written.');
  document.getElementById('setupHelp').innerHTML = h.length ? h.join('<br><br>') : 'Email, Jobber and Claude are all connected.';
}
function saveSettings(){ post('/workorders/api/settings', {inbox:val('s-inbox'), forward_to:val('s-forward'), tech_name:val('s-tech'), keywords:val('s-keywords'),
  enabled:document.getElementById('s-enabled').checked, auto_send:document.getElementById('s-auto').checked}).then(function(){ toast('Settings saved'); load(); }); }
function renderActivity(){
  document.getElementById('activity').innerHTML = D.activity.length ? D.activity.map(function(a){
    return '<tr><td class="small muted" style="white-space:nowrap">'+esc(a.at)+'</td><td class="small"><b>'+esc(a.kind)+'</b></td><td>'+esc(a.message)+'</td></tr>'; }).join('') : '<tr><td class="empty">Nothing yet.</td></tr>';
}
function runNow(){ post('/workorders/api/run').then(function(){ toast('Running — this takes a minute'); setTimeout(load, 15000); setTimeout(load, 45000); }); }
load();
</script>
</body>
</html>'''
