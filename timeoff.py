"""
Time-Off Log: technician time-off requests and sick call-outs.

Used by Beatriz (the approver) and office admins in the app, and by OpenClaw
(the AI scheduling assistant) through /api/time-off with a bearer token.
Technicians and property managers can never see it.

Privacy rule: a request records who, which dates and the decision - never why.
Fields such as "reason" or "notes" are dropped on the way in and never stored.

Everything is America/New_York. Dates are 'YYYY-MM-DD', times 'HH:MM' (24h),
timestamps ISO 8601 with the New York offset.

Hooked into app.py with init_timeoff(app, csrf, DB_PATH); see TIMEOFF_README.md.
"""
import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests as http_requests
from flask import Blueprint, jsonify, render_template_string, request, session, redirect, url_for
from flask_wtf.csrf import CSRFError

TZ = ZoneInfo('America/New_York')

# Who may use it. Technicians and property managers never, whatever is set below.
TIMEOFF_ROLES = ('office',)
TIMEOFF_NEVER_ROLES = ('technician', 'property_manager')
# Optional: exactly these usernames get access (e.g. "simon,beatriz"), whatever
# their role. Unset = every office login.
TIMEOFF_USERS = {u.strip().lower() for u in os.environ.get('TIMEOFF_USERS', '').split(',') if u.strip()}
# OpenClaw authenticates to /api/time-off with "Authorization: Bearer <token>".
TIMEOFF_API_TOKEN = os.environ.get('TIMEOFF_API_TOKEN', '')
# Where status changes made in the app are POSTed so OpenClaw can update Jobber and tell the tech.
OPENCLAW_WEBHOOK_URL = os.environ.get('OPENCLAW_WEBHOOK_URL', '')
# Optional: sent as a bearer token and used to sign the webhook body.
OPENCLAW_WEBHOOK_SECRET = os.environ.get('OPENCLAW_WEBHOOK_SECRET', '')

TYPES = ('TIME_OFF', 'CALL_OUT')
STATUSES = ('PENDING', 'APPROVED', 'DENIED', 'CANCELLED')
MAX_SPAN_DAYS = 366
# Anything that smells like a reason or medical detail is refused at the door.
PRIVATE_FIELDS = ('reason', 'reasons', 'note', 'notes', 'details', 'detail', 'description', 'comment',
                  'comments', 'message', 'medical', 'illness', 'symptoms', 'diagnosis', 'why', 'explanation')
COLUMNS = ('id', 'tech_name', 'jobber_user_id', 'slack_user_id', 'type', 'start_date', 'end_date',
           'start_time', 'end_time', 'days_count', 'requested_at', 'requested_via', 'status', 'decided_by',
           'decided_at', 'affected_visits_count', 'reported_by', 'unconfirmed', 'reminder_sent_at',
           'webhook_status', 'webhook_at', 'created_at', 'updated_at')

bp = Blueprint('timeoff', __name__)
_db_path = None


# ---------------------------------------------------------------- basics

def _now():
    return datetime.now(TZ).replace(microsecond=0)


def _now_text():
    return _now().isoformat()


def _today():
    return _now().date()


def _conn():
    conn = sqlite3.connect(_db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = sqlite3.connect(_db_path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS timeoff_requests (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  tech_name TEXT NOT NULL,
                  jobber_user_id TEXT,
                  slack_user_id TEXT,
                  type TEXT NOT NULL,
                  start_date TEXT NOT NULL,
                  end_date TEXT NOT NULL,
                  start_time TEXT,
                  end_time TEXT,
                  days_count INTEGER NOT NULL DEFAULT 0,
                  requested_at TEXT NOT NULL,
                  requested_via TEXT,
                  status TEXT NOT NULL,
                  decided_by TEXT,
                  decided_at TEXT,
                  affected_visits_count INTEGER,
                  reported_by TEXT,
                  unconfirmed INTEGER NOT NULL DEFAULT 0,
                  reminder_sent_at TEXT,
                  webhook_status TEXT,
                  webhook_at TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL)''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_timeoff_dates ON timeoff_requests(start_date, end_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_timeoff_status ON timeoff_requests(status)")
    # Every status change: who, when, from, to, and whether it came from the app or the API.
    c.execute('''CREATE TABLE IF NOT EXISTS timeoff_audit (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  request_id INTEGER NOT NULL,
                  changed_at TEXT NOT NULL,
                  changed_by TEXT,
                  from_status TEXT,
                  to_status TEXT NOT NULL,
                  source TEXT NOT NULL)''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_timeoff_audit_req ON timeoff_audit(request_id)")
    conn.commit()
    conn.close()


def weekdays_between(start, end):
    """Mon-Fri days from start to end, both inclusive."""
    if end < start:
        return 0
    n = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def _add_business_days(d, n):
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def _parse_date(value, field, errors):
    s = str(value or '').strip()
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', s):
        errors.append(f'{field} must be a date written YYYY-MM-DD')
        return None
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except ValueError:
        errors.append(f'{field} is not a real date ({s})')
        return None


def _parse_time(value, field, errors):
    if value in (None, ''):
        return None
    s = str(value).strip().upper().replace('.', '')
    for fmt in ('%H:%M', '%H:%M:%S', '%I:%M %p', '%I:%M%p', '%I %p', '%I%p'):
        try:
            return datetime.strptime(s, fmt).strftime('%H:%M')
        except ValueError:
            continue
    errors.append(f'{field} must be a time like 13:30')
    return None


def _parse_stamp(value, field, errors):
    """ISO timestamp -> New York ISO text. A time with no offset is taken as New York time."""
    s = str(value or '').strip()
    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        errors.append(f'{field} must be an ISO 8601 timestamp')
        return None
    dt = dt.replace(tzinfo=TZ) if dt.tzinfo is None else dt.astimezone(TZ)
    return dt.replace(microsecond=0).isoformat()


def _clean_text(value, limit=120):
    s = str(value).strip() if value is not None else ''
    return s[:limit] or None


def _row_dict(row):
    d = {k: row[k] for k in COLUMNS}
    d['unconfirmed'] = bool(d['unconfirmed'])
    d['reminder_due'] = _reminder_due(d)
    return d


def _reminder_due(d):
    """OpenClaw reminds Beatriz once, after one business day without a decision."""
    if d['status'] != 'PENDING' or d['reminder_sent_at']:
        return False
    try:
        req = datetime.fromisoformat(d['requested_at']).astimezone(TZ)
    except (TypeError, ValueError):
        return False
    due = datetime.combine(_add_business_days(req.date(), 1), req.timetz())
    return _now() >= due


def _audit(c, request_id, by, from_status, to_status, source):
    c.execute("""INSERT INTO timeoff_audit (request_id, changed_at, changed_by, from_status, to_status, source)
                 VALUES (?,?,?,?,?,?)""", (request_id, _now_text(), by, from_status, to_status, source))


def _same_tech_sql():
    return ("(LOWER(TRIM(tech_name)) = LOWER(TRIM(?))"
            " OR (jobber_user_id IS NOT NULL AND jobber_user_id != '' AND jobber_user_id = ?)"
            " OR (slack_user_id IS NOT NULL AND slack_user_id != '' AND slack_user_id = ?))")


def _tech_filter_sql(tech):
    """?tech= matches a full name, a first or last name, a Jobber id or a Slack id."""
    t = tech.strip().lower()
    return ("(LOWER(tech_name) = ? OR LOWER(tech_name) LIKE ? OR LOWER(tech_name) LIKE ?"
            " OR jobber_user_id = ? OR slack_user_id = ?)",
            [t, t + ' %', '% ' + t, tech.strip(), tech.strip()])


# ---------------------------------------------------------------- access

def timeoff_allowed():
    """May the signed-in user open the Time-Off Log?"""
    if 'username' not in session:
        return False
    role = session.get('role')
    if role in TIMEOFF_NEVER_ROLES:
        return False
    if TIMEOFF_USERS:
        return session['username'].lower() in TIMEOFF_USERS
    return role in TIMEOFF_ROLES


def _bearer_ok():
    if not TIMEOFF_API_TOKEN:
        return False
    auth = request.headers.get('Authorization', '')
    return hmac.compare_digest(auth.encode(), f'Bearer {TIMEOFF_API_TOKEN}'.encode())


def _caller():
    """('api', 'OpenClaw') for the token, ('app', <full name>) for an allowed login, else None.

    An app login writing through the API must also carry the CSRF token, since the
    blueprint is exempt from the global check so OpenClaw can call it."""
    if request.headers.get('Authorization'):
        return ('api', 'OpenClaw') if _bearer_ok() else None
    if timeoff_allowed():
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            _csrf.protect()
        return ('app', session.get('full_name') or session.get('username'))
    return None


def _deny():
    if request.headers.get('Authorization') and not TIMEOFF_API_TOKEN:
        return jsonify({'success': False, 'error': 'TIMEOFF_API_TOKEN is not set on this service'}), 503
    return jsonify({'success': False, 'error': 'Unauthorized'}), 401


def _bad(errors, code=400, **extra):
    return jsonify({'success': False, 'errors': errors, 'error': '; '.join(errors), **extra}), code


# ---------------------------------------------------------------- webhook

def _send_webhook(request_id, payload):
    body = json.dumps(payload, separators=(',', ':')).encode()
    headers = {'Content-Type': 'application/json', 'User-Agent': 'OfficeApp-TimeOff/1'}
    if OPENCLAW_WEBHOOK_SECRET:
        headers['Authorization'] = f'Bearer {OPENCLAW_WEBHOOK_SECRET}'
        headers['X-TimeOff-Signature'] = 'sha256=' + hmac.new(
            OPENCLAW_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    result = 'failed'
    for wait in (0, 2, 6):
        time.sleep(wait)
        try:
            r = http_requests.post(OPENCLAW_WEBHOOK_URL, data=body, headers=headers, timeout=10)
            if 200 <= r.status_code < 300:
                result = 'sent'
                break
            result = f'failed: HTTP {r.status_code}'
            if 400 <= r.status_code < 500 and r.status_code not in (408, 429):
                break
        except http_requests.RequestException as e:
            result = f'failed: {type(e).__name__}'
    try:
        conn = _conn()
        conn.execute("UPDATE timeoff_requests SET webhook_status=?, webhook_at=? WHERE id=?",
                     (result, _now_text(), request_id))
        conn.commit()
        conn.close()
    except sqlite3.Error:
        pass
    if result != 'sent':
        print(f"⚠ Time-off webhook for request {request_id} {result}")


def notify_openclaw(record, change):
    """POST the updated record to OPENCLAW_WEBHOOK_URL in the background."""
    conn = _conn()
    if not OPENCLAW_WEBHOOK_URL:
        conn.execute("UPDATE timeoff_requests SET webhook_status=?, webhook_at=? WHERE id=?",
                     ('not configured', _now_text(), record['id']))
        conn.commit()
        conn.close()
        return
    conn.execute("UPDATE timeoff_requests SET webhook_status=?, webhook_at=? WHERE id=?",
                 ('sending', _now_text(), record['id']))
    conn.commit()
    conn.close()
    payload = {'event': 'time_off.status_changed', **change, 'record': record}
    threading.Thread(target=_send_webhook, args=(record['id'], payload), daemon=True).start()


# ---------------------------------------------------------------- reads

def _get(conn, request_id):
    row = conn.execute("SELECT * FROM timeoff_requests WHERE id=?", (request_id,)).fetchone()
    return _row_dict(row) if row else None


def _history(conn, request_id):
    rows = conn.execute("""SELECT changed_at, changed_by, from_status, to_status, source FROM timeoff_audit
                           WHERE request_id=? ORDER BY id""", (request_id,)).fetchall()
    return [dict(r) for r in rows]


def list_requests(status=None, tech=None, date_from=None, date_to=None, type_=None):
    where, args = [], []
    if status:
        where.append('status IN (%s)' % ','.join('?' * len(status)))
        args += status
    if type_:
        where.append('type = ?')
        args.append(type_)
    if tech:
        sql, a = _tech_filter_sql(tech)
        where.append(sql)
        args += a
    if date_from:
        where.append('end_date >= ?')
        args.append(date_from.isoformat())
    if date_to:
        where.append('start_date <= ?')
        args.append(date_to.isoformat())
    sql = 'SELECT * FROM timeoff_requests'
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY start_date DESC, id DESC'
    conn = _conn()
    rows = [_row_dict(r) for r in conn.execute(sql, args).fetchall()]
    conn.close()
    return rows


def whos_off(day):
    conn = _conn()
    rows = conn.execute("""SELECT * FROM timeoff_requests WHERE start_date <= ? AND end_date >= ?
                           AND status IN ('APPROVED','PENDING') ORDER BY tech_name""",
                        (day.isoformat(), day.isoformat())).fetchall()
    conn.close()
    recs = [_row_dict(r) for r in rows]

    def brief(r):
        return {k: r[k] for k in ('id', 'tech_name', 'jobber_user_id', 'slack_user_id', 'type', 'status',
                                  'start_date', 'end_date', 'start_time', 'end_time', 'unconfirmed',
                                  'reported_by')}
    return {'date': day.isoformat(), 'weekday': day.strftime('%A'),
            'off': [brief(r) for r in recs if r['status'] == 'APPROVED'],
            'pending': [brief(r) for r in recs if r['status'] == 'PENDING']}


def tech_summary(year, tech=None):
    """Per tech: weekdays taken so far this year (approved time off + call-outs) and upcoming approved time off."""
    today = _today()
    jan1, dec31 = date(year, 1, 1), date(year, 12, 31)
    status_rows = list_requests(status=['APPROVED'], tech=tech)
    techs = {}
    for r in status_rows:
        key = r['tech_name'].strip().lower()
        t = techs.setdefault(key, {'tech_name': r['tech_name'], 'jobber_user_id': r['jobber_user_id'],
                                   'slack_user_id': r['slack_user_id'], 'days_taken': 0, 'time_off_days': 0,
                                   'call_out_days': 0, 'call_outs': 0, 'days_booked': 0, 'upcoming': []})
        t['jobber_user_id'] = t['jobber_user_id'] or r['jobber_user_id']
        t['slack_user_id'] = t['slack_user_id'] or r['slack_user_id']
        s, e = date.fromisoformat(r['start_date']), date.fromisoformat(r['end_date'])
        in_year = weekdays_between(max(s, jan1), min(e, dec31))
        taken = weekdays_between(max(s, jan1), min(e, dec31, today))
        t['days_booked'] += in_year
        t['days_taken'] += taken
        if r['type'] == 'CALL_OUT':
            t['call_out_days'] += taken
            if jan1 <= s <= min(dec31, today):
                t['call_outs'] += 1
        else:
            t['time_off_days'] += taken
        if r['type'] == 'TIME_OFF' and e >= today:
            t['upcoming'].append({k: r[k] for k in ('id', 'start_date', 'end_date', 'start_time', 'end_time',
                                                    'days_count', 'unconfirmed', 'reported_by')})
    out = sorted(techs.values(), key=lambda t: (-t['days_taken'], t['tech_name'].lower()))
    for t in out:
        t['upcoming'].sort(key=lambda u: u['start_date'])
    return {'year': year, 'as_of': today.isoformat(), 'techs': out}


# ---------------------------------------------------------------- writes

def create_request(data, source, actor):
    """Validate and insert. Returns (record, None) or (None, (errors, http_code, extra))."""
    errors = []
    data = dict(data or {})
    ignored = sorted(k for k in data if k.lower() in PRIVATE_FIELDS)
    for k in ignored:
        data.pop(k)

    tech_name = _clean_text(data.get('tech_name') or data.get('tech'))
    if not tech_name:
        errors.append('tech_name is required')
    type_ = str(data.get('type') or '').strip().upper().replace('-', '_').replace(' ', '_')
    if type_ not in TYPES:
        errors.append('type must be TIME_OFF or CALL_OUT')
    start = _parse_date(data.get('start_date'), 'start_date', errors)
    end = _parse_date(data.get('end_date') or data.get('start_date'), 'end_date', errors)
    start_time = _parse_time(data.get('start_time'), 'start_time', errors)
    end_time = _parse_time(data.get('end_time'), 'end_time', errors)
    if start and end:
        if end < start:
            errors.append('end_date must be on or after start_date')
        elif (end - start).days >= MAX_SPAN_DAYS:
            errors.append(f'a request can cover at most {MAX_SPAN_DAYS} days')
        elif start == end and start_time and end_time and end_time <= start_time:
            errors.append('end_time must be after start_time')
    visits = data.get('affected_visits_count')
    if visits in (None, ''):
        visits = None
    else:
        try:
            visits = int(visits)
            if visits < 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append('affected_visits_count must be a whole number, 0 or more')
    requested_at = _parse_stamp(data['requested_at'], 'requested_at', errors) if data.get('requested_at') else _now_text()
    reported_by = _clean_text(data.get('reported_by'))
    if reported_by and tech_name and reported_by.strip().lower() == tech_name.strip().lower():
        reported_by = None  # reporting your own time off is not a third-party report
    unconfirmed = bool(reported_by) or str(data.get('unconfirmed')).lower() in ('1', 'true', 'yes')
    if errors:
        return None, (errors, 400, {'ignored_fields': ignored})

    jobber_id = _clean_text(data.get('jobber_user_id'))
    slack_id = _clean_text(data.get('slack_user_id'))
    now = _now_text()
    is_callout = type_ == 'CALL_OUT'
    status = 'APPROVED' if is_callout else 'PENDING'

    conn = _conn()
    try:
        conn.execute('BEGIN IMMEDIATE')  # the overlap check and the insert are one step across workers
        if status == 'PENDING':
            clash = conn.execute(
                "SELECT id, tech_name, start_date, end_date FROM timeoff_requests WHERE status='PENDING'"
                " AND start_date <= ? AND end_date >= ? AND " + _same_tech_sql(),
                (end.isoformat(), start.isoformat(), tech_name, jobber_id or '', slack_id or '')).fetchone()
            if clash:
                conn.rollback()
                return None, ([f"{clash['tech_name']} already has a pending request (#{clash['id']}, "
                               f"{clash['start_date']} to {clash['end_date']}) overlapping these dates"],
                              409, {'existing_id': clash['id'], 'ignored_fields': ignored})
        cur = conn.execute(
            """INSERT INTO timeoff_requests (tech_name, jobber_user_id, slack_user_id, type, start_date, end_date,
                   start_time, end_time, days_count, requested_at, requested_via, status, decided_by, decided_at,
                   affected_visits_count, reported_by, unconfirmed, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (tech_name, jobber_id, slack_id, type_, start.isoformat(), end.isoformat(), start_time, end_time,
             weekdays_between(start, end), requested_at, _clean_text(data.get('requested_via'), 40) or
             ('App' if source == 'app' else 'API'), status,
             'Auto-approved (call-out)' if is_callout else None, now if is_callout else None,
             visits, reported_by, 1 if unconfirmed else 0, now, now))
        new_id = cur.lastrowid
        _audit(conn, new_id, actor, None, status, source)
        conn.commit()
        rec = _get(conn, new_id)
    finally:
        conn.close()
    rec['ignored_fields'] = ignored
    return rec, None


def update_request(request_id, data, source, actor):
    """Status changes, reminder_sent_at, confirmation and visit counts. Returns (record, change, error)."""
    data = dict(data or {})
    errors = []
    fields = {}
    new_status = None
    if 'status' in data:
        new_status = str(data.get('status') or '').strip().upper()
        if new_status not in ('APPROVED', 'DENIED', 'CANCELLED'):
            errors.append('status must be APPROVED, DENIED or CANCELLED')
    decided_by = _clean_text(data.get('decided_by'))
    if source == 'app':
        decided_by = actor  # the signed-in person, never whatever the browser claims
    elif new_status in ('APPROVED', 'DENIED') and not decided_by:
        errors.append('decided_by is required to approve or deny')
    if 'reminder_sent_at' in data:
        v = data.get('reminder_sent_at')
        if v in (True, 'now', 'NOW'):
            fields['reminder_sent_at'] = _now_text()
        elif v in (None, '', False):
            fields['reminder_sent_at'] = None
        else:
            fields['reminder_sent_at'] = _parse_stamp(v, 'reminder_sent_at', errors)
    if 'unconfirmed' in data:
        fields['unconfirmed'] = 1 if str(data.get('unconfirmed')).lower() in ('1', 'true', 'yes') else 0
    if 'affected_visits_count' in data:
        try:
            v = data.get('affected_visits_count')
            fields['affected_visits_count'] = None if v in (None, '') else int(v)
            if fields['affected_visits_count'] is not None and fields['affected_visits_count'] < 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append('affected_visits_count must be a whole number, 0 or more')
    if not errors and new_status is None and not fields:
        errors.append('nothing to change: send status, reminder_sent_at, unconfirmed or affected_visits_count')
    if errors:
        return None, None, (errors, 400)

    conn = _conn()
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute("SELECT * FROM timeoff_requests WHERE id=?", (request_id,)).fetchone()
        if not row:
            conn.rollback()
            return None, None, ([f'no time-off request #{request_id}'], 404)
        old_status = row['status']
        change = None
        now = _now_text()
        if new_status and new_status != old_status:
            if old_status == 'CANCELLED':
                conn.rollback()
                return None, None, ([f'request #{request_id} was cancelled and can no longer change'], 409)
            fields.update(status=new_status, decided_by=decided_by or actor, decided_at=now)
            _audit(conn, request_id, decided_by or actor, old_status, new_status, source)
            change = {'from_status': old_status, 'to_status': new_status, 'changed_by': decided_by or actor,
                      'changed_at': now, 'source': source}
        if fields:
            fields['updated_at'] = now
            conn.execute("UPDATE timeoff_requests SET %s WHERE id=?" % ', '.join(f'{k}=?' for k in fields),
                         (*fields.values(), request_id))
        conn.commit()
        rec = _get(conn, request_id)
    finally:
        conn.close()
    # A decision made in the app is news to OpenClaw; one OpenClaw sent itself is not echoed back.
    if change and source == 'app':
        notify_openclaw(rec, change)
        rec['webhook_status'] = 'sending' if OPENCLAW_WEBHOOK_URL else 'not configured'
    return rec, change, None


# ---------------------------------------------------------------- API routes

def _args_dates(errors):
    a = request.args
    d_from = _parse_date(a['from'], 'from', errors) if a.get('from') else None
    d_to = _parse_date(a['to'], 'to', errors) if a.get('to') else None
    if d_from and d_to and d_to < d_from:
        errors.append('to must be on or after from')
    return d_from, d_to


@bp.route('/api/time-off', methods=['GET', 'POST'])
def api_collection():
    who = _caller()
    if not who:
        return _deny()
    source, actor = who
    if request.method == 'POST':
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return _bad(['send a JSON object'])
        rec, err = create_request(data, source, actor)
        if err:
            errors, code, extra = err
            return _bad(errors, code, **extra)
        return jsonify({'success': True, 'request': rec}), 201

    errors = []
    status = [s.strip().upper() for s in request.args.get('status', '').split(',') if s.strip()]
    bad = [s for s in status if s not in STATUSES]
    if bad:
        errors.append(f"status must be one of {', '.join(STATUSES)}")
    type_ = request.args.get('type', '').strip().upper() or None
    if type_ and type_ not in TYPES:
        errors.append('type must be TIME_OFF or CALL_OUT')
    d_from, d_to = _args_dates(errors)
    if errors:
        return _bad(errors)
    rows = list_requests(status or None, request.args.get('tech') or None, d_from, d_to, type_)
    return jsonify({'success': True, 'count': len(rows), 'requests': rows})


@bp.route('/api/time-off/<int:request_id>', methods=['GET', 'PATCH'])
def api_item(request_id):
    who = _caller()
    if not who:
        return _deny()
    source, actor = who
    if request.method == 'PATCH':
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return _bad(['send a JSON object'])
        rec, change, err = update_request(request_id, data, source, actor)
        if err:
            return _bad(*err)
        return jsonify({'success': True, 'request': rec, 'status_changed': bool(change)})
    conn = _conn()
    rec = _get(conn, request_id)
    if rec:
        rec['history'] = _history(conn, request_id)
    conn.close()
    if not rec:
        return _bad([f'no time-off request #{request_id}'], 404)
    return jsonify({'success': True, 'request': rec})


@bp.route('/api/time-off/whos-off')
def api_whos_off():
    if not _caller():
        return _deny()
    errors = []
    day = _parse_date(request.args['date'], 'date', errors) if request.args.get('date') else _today()
    if errors:
        return _bad(errors)
    return jsonify({'success': True, **whos_off(day)})


@bp.route('/api/time-off/summary')
def api_summary():
    if not _caller():
        return _deny()
    year = request.args.get('year') or str(_today().year)
    if not re.fullmatch(r'\d{4}', year) or not 2000 <= int(year) <= 2100:
        return _bad(['year must be a four-digit year'])
    return jsonify({'success': True, **tech_summary(int(year), request.args.get('tech') or None)})


@bp.route('/api/time-off/<int:request_id>/notify', methods=['POST'])
def api_renotify(request_id):
    """App only: resend the latest status change to OpenClaw after a failed webhook."""
    if request.headers.get('Authorization') or not timeoff_allowed():
        return _deny()
    _csrf.protect()
    conn = _conn()
    rec = _get(conn, request_id)
    hist = _history(conn, request_id) if rec else []
    conn.close()
    if not rec:
        return _bad([f'no time-off request #{request_id}'], 404)
    last = hist[-1] if hist else {}
    notify_openclaw(rec, {'from_status': last.get('from_status'), 'to_status': rec['status'],
                          'changed_by': last.get('changed_by'), 'changed_at': last.get('changed_at'),
                          'source': 'app', 'resent': True})
    return jsonify({'success': True, 'webhook_status': 'sending' if OPENCLAW_WEBHOOK_URL else 'not configured'})


@bp.errorhandler(CSRFError)
def _csrf_failed(e):
    return jsonify({'success': False, 'error': 'Your session expired. Reload the page and try again.'}), 400


# ---------------------------------------------------------------- page

@bp.route('/timeoff')
def page():
    if not timeoff_allowed():
        return redirect(url_for('login'))
    conn = _conn()
    techs = [r[0] for r in conn.execute(
        "SELECT tech_name FROM timeoff_requests GROUP BY LOWER(TRIM(tech_name)) ORDER BY LOWER(tech_name)")]
    conn.close()
    boot = {'today': _today().isoformat(), 'techs': techs,
            'webhook_configured': bool(OPENCLAW_WEBHOOK_URL), 'api_configured': bool(TIMEOFF_API_TOKEN)}
    return render_template_string(TIMEOFF_TEMPLATE, boot=boot,
                                  full_name=session.get('full_name') or session.get('username'))


_csrf = None


def init_timeoff(app, csrf, db_path):
    """Create the tables and register the routes. OpenClaw has no CSRF token, so the blueprint
    is exempt from the global check and app logins are checked by hand in _caller()."""
    global _db_path, _csrf
    _db_path, _csrf = db_path, csrf
    init_db()
    csrf.exempt(bp)
    app.register_blueprint(bp)
    if not TIMEOFF_API_TOKEN:
        print("ℹ Time-Off API: TIMEOFF_API_TOKEN not set - OpenClaw cannot call /api/time-off yet")
    if not OPENCLAW_WEBHOOK_URL:
        print("ℹ Time-Off webhook: OPENCLAW_WEBHOOK_URL not set - app decisions will not reach OpenClaw")


TIMEOFF_TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Time-Off Log — Stahlman-England</title>
<meta name="csrf-token" content="{{ csrf_token() }}">
<style>
  :root {
    --brand:#2563EB; --brand-dark:#1D4ED8; --brand-light:#EFF6FF;
    --ink:#0F172A; --ink2:#475569; --ink3:#94A3B8;
    --bg:#F8FAFC; --card:#FFFFFF; --line:#E2E8F0; --line2:#F1F5F9;
    --good:#059669; --good-bg:#ECFDF5; --warn:#B45309; --warn-bg:#FFFBEB; --bad:#DC2626; --bad-bg:#FEF2F2;
    --shadow:0 1px 3px rgba(15,23,42,.06),0 1px 2px rgba(15,23,42,.04);
  }
  *,*::before,*::after { box-sizing:border-box; }
  body { margin:0; font-family:Inter,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; background:var(--bg); color:var(--ink); font-size:14px; line-height:1.45; }
  a { color:var(--brand); text-decoration:none; }
  a:hover { text-decoration:underline; }
  .n { font-variant-numeric:tabular-nums; text-align:right; white-space:nowrap; }

  .top { background:#fff; border-bottom:1px solid var(--line); position:sticky; top:0; z-index:50; }
  .top-in { max-width:1320px; margin:0 auto; padding:0 20px; height:58px; display:flex; align-items:center; gap:14px; }
  .top-in .back { color:var(--ink2); font-size:13px; font-weight:500; }
  .top-in .sep { width:1px; height:24px; background:var(--line); }
  .top-in h1 { font-size:17px; margin:0; letter-spacing:-.01em; }
  .top-in .me { margin-left:auto; font-size:12px; color:var(--ink2); }
  .tabs { max-width:1320px; margin:0 auto; padding:0 20px; display:flex; gap:2px; overflow-x:auto; }
  .tabs a { padding:11px 14px 10px; font-size:14px; font-weight:600; color:var(--ink2); border-bottom:2px solid transparent; white-space:nowrap; }
  .tabs a:hover { color:var(--ink); text-decoration:none; }
  .tabs a.on { color:var(--brand); border-bottom-color:var(--brand); }
  .tabs .badge { display:inline-block; min-width:18px; padding:0 5px; margin-left:5px; border-radius:9px; background:var(--warn); color:#fff; font-size:11px; line-height:18px; text-align:center; }

  main { max-width:1320px; margin:0 auto; padding:20px 20px 60px; }
  section[data-tab] { display:none; }
  section[data-tab].on { display:block; }
  .setup { background:var(--warn-bg); border:1px solid #FDE68A; color:#78350F; padding:10px 14px; border-radius:10px; margin-bottom:16px; font-size:13px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:14px; box-shadow:var(--shadow); padding:18px 20px; margin-bottom:18px; }
  .card h2 { font-size:15px; margin:0 0 4px; letter-spacing:-.01em; }
  .card .sub { color:var(--ink2); font-size:13px; margin:0 0 14px; }
  .card.pending { border-color:#FDE68A; }

  .btn { display:inline-flex; align-items:center; gap:6px; padding:8px 14px; border-radius:8px; border:1px solid var(--line); background:#fff; color:var(--ink); font:inherit; font-size:13px; font-weight:600; cursor:pointer; white-space:nowrap; }
  .btn:hover { background:var(--bg); text-decoration:none; }
  .btn.approve { background:var(--good); border-color:var(--good); color:#fff; }
  .btn.approve:hover { background:#047857; }
  .btn.deny { color:var(--bad); border-color:#FECACA; }
  .btn.deny:hover { background:var(--bad-bg); }
  .btn.sm { padding:4px 9px; font-size:12px; border-radius:6px; }
  .btn:disabled { opacity:.5; cursor:default; }
  .row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  .filters { display:flex; gap:10px; flex-wrap:wrap; align-items:flex-end; margin-bottom:12px; }
  label.f { display:block; font-size:12px; font-weight:600; color:var(--ink2); margin:0 0 4px; }
  input[type=month], select { font:inherit; font-size:14px; padding:7px 10px; border:1px solid #CBD5E1; border-radius:8px; background:#fff; color:var(--ink); }
  input:focus, select:focus { outline:2px solid #BFDBFE; border-color:var(--brand); }

  .tw { overflow-x:auto; -webkit-overflow-scrolling:touch; }
  table.t { width:100%; border-collapse:collapse; font-size:13px; }
  table.t th { text-align:left; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.04em; color:var(--ink2); padding:8px 10px; border-bottom:1px solid var(--line); white-space:nowrap; }
  table.t th.n { text-align:right; }
  table.t td { padding:9px 10px; border-bottom:1px solid var(--line2); vertical-align:top; }
  table.t tr.hist td { background:var(--bg); font-size:12px; color:var(--ink2); }
  .muted { color:var(--ink3); }
  .small { font-size:12px; }
  .pill { display:inline-block; padding:1px 8px; border-radius:100px; font-size:11px; font-weight:700; white-space:nowrap; }
  .pill.PENDING { background:#FEF3C7; color:#92400E; }
  .pill.APPROVED { background:var(--good-bg); color:var(--good); }
  .pill.DENIED { background:var(--line2); color:var(--ink2); }
  .pill.CANCELLED { background:var(--line2); color:var(--ink3); text-decoration:line-through; }
  .pill.CALL_OUT { background:var(--bad-bg); color:var(--bad); }
  .pill.TIME_OFF { background:var(--brand-light); color:var(--brand); }
  .pill.unconf { background:#FFF7ED; color:#9A3412; border:1px dashed #FDBA74; }
  .pill.due { background:var(--warn-bg); color:var(--warn); }
  .pill.wh { background:var(--bad-bg); color:var(--bad); cursor:pointer; }
  .empty { padding:22px 10px; text-align:center; color:var(--ink2); }

  .cal-h { display:flex; align-items:center; gap:10px; margin-bottom:12px; flex-wrap:wrap; }
  .cal-h h2 { margin:0; min-width:150px; }
  .legend { margin-left:auto; display:flex; gap:12px; font-size:12px; color:var(--ink2); }
  .sw { display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:5px; vertical-align:-1px; }
  .cal { display:grid; grid-template-columns:repeat(7,minmax(0,1fr)); border-top:1px solid var(--line); border-left:1px solid var(--line); }
  .cal .dow { font-size:11px; font-weight:700; text-transform:uppercase; color:var(--ink2); padding:6px 8px; border-right:1px solid var(--line); border-bottom:1px solid var(--line); background:var(--bg); }
  .cal .d { min-height:96px; padding:5px 6px; border-right:1px solid var(--line); border-bottom:1px solid var(--line); background:#fff; }
  .cal .d.out { background:var(--bg); }
  .cal .d.out .num { color:var(--ink3); }
  .cal .d.we { background:#FBFCFE; }
  .cal .d.today .num { background:var(--brand); color:#fff; border-radius:100px; padding:0 6px; }
  .cal .num { font-size:12px; font-weight:700; color:var(--ink2); display:inline-block; margin-bottom:3px; }
  .ev { display:block; font-size:11.5px; font-weight:600; border-radius:5px; padding:2px 6px; margin-bottom:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .ev.PENDING, .sw.PENDING { background:#FEF3C7; color:#92400E; }
  .ev.APPROVED, .sw.APPROVED { background:#D1FAE5; color:#065F46; }
  .ev.CALL_OUT, .sw.CALL_OUT { background:#FEE2E2; color:#991B1B; }
  .ev.unconf { border:1px dashed currentColor; }

  .yr { display:flex; gap:8px; align-items:center; margin-bottom:12px; }
  .big { font-size:20px; font-weight:750; font-variant-numeric:tabular-nums; }
  .up { list-style:none; margin:0; padding:0; }
  .up li { padding:1px 0; }
  @media(max-width:700px){ .cal .d { min-height:70px; padding:3px; } .ev { font-size:10px; padding:1px 3px; } .legend { margin-left:0; } }
</style>
</head>
<body>
<header class="top">
  <div class="top-in">
    <a class="back" href="/dashboard">← Office App</a><span class="sep"></span>
    <h1>Time-Off Log</h1>
    <span class="me">{{ full_name }}</span>
  </div>
  <nav class="tabs">
    <a href="#requests" data-go="requests">Requests<span class="badge" id="pendingBadge" hidden></span></a>
    <a href="#calendar" data-go="calendar">Calendar</a>
    <a href="#summary" data-go="summary">Tech summary</a>
  </nav>
</header>
<main>
  <div class="setup" id="setupNote" hidden></div>

  <section data-tab="requests">
    <div class="card pending">
      <h2>Pending</h2>
      <p class="sub">Approving or denying here is the same as replying in Slack: the record updates and OpenClaw is told, so it can update Jobber and let the tech know.</p>
      <div class="tw" id="pendingBox"></div>
    </div>
    <div class="card">
      <h2>All requests</h2>
      <div class="filters">
        <div><label class="f" for="fTech">Tech</label><select id="fTech"><option value="">All techs</option></select></div>
        <div><label class="f" for="fMonth">Month</label><input type="month" id="fMonth"></div>
        <div><label class="f" for="fStatus">Status</label>
          <select id="fStatus"><option value="">Any status</option><option>PENDING</option><option>APPROVED</option><option>DENIED</option><option>CANCELLED</option></select></div>
        <button class="btn sm" id="fClear" type="button">Clear</button>
      </div>
      <div class="tw" id="allBox"></div>
    </div>
  </section>

  <section data-tab="calendar">
    <div class="card">
      <div class="cal-h">
        <button class="btn sm" id="calPrev" type="button" aria-label="Previous month">‹</button>
        <h2 id="calTitle"></h2>
        <button class="btn sm" id="calNext" type="button" aria-label="Next month">›</button>
        <button class="btn sm" id="calToday" type="button">Today</button>
        <div class="legend"><span><span class="sw PENDING"></span>Pending</span><span><span class="sw APPROVED"></span>Approved</span><span><span class="sw CALL_OUT"></span>Call-out</span></div>
      </div>
      <div class="cal" id="cal"></div>
    </div>
  </section>

  <section data-tab="summary">
    <div class="card">
      <div class="yr"><h2 style="margin:0">Days taken in</h2><select id="sYear"></select></div>
      <p class="sub">Weekdays already taken this calendar year: approved time off plus call-outs. Upcoming approved time off is listed beside each tech.</p>
      <div class="tw" id="sumBox"></div>
    </div>
  </section>
</main>

<script>
(function(){
  var BOOT = {{ boot|tojson }};
  var CSRF = document.querySelector('meta[name=csrf-token]').content;
  var DOW = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
  var MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  var MONTH_LONG = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  var TODAY = BOOT.today;
  var THIS_YEAR = +TODAY.slice(0,4);
  var $ = function(id){ return document.getElementById(id); };

  function esc(s){ return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  function d(iso){ var p = iso.split('-'); return new Date(+p[0], +p[1]-1, +p[2]); }
  function iso(dt){ return dt.getFullYear()+'-'+String(dt.getMonth()+1).padStart(2,'0')+'-'+String(dt.getDate()).padStart(2,'0'); }
  function dayLabel(s){ var x = d(s); return DOW[x.getDay()]+' '+MON[x.getMonth()]+' '+x.getDate()+(x.getFullYear() !== THIS_YEAR ? ', '+x.getFullYear() : ''); }
  function t12(t){ if(!t) return ''; var h = +t.slice(0,2), m = t.slice(3); return (h % 12 || 12)+(m === '00' ? '' : ':'+m)+(h < 12 ? 'a' : 'p'); }
  function dates(r){
    var s = dayLabel(r.start_date);
    if (r.end_date !== r.start_date) s += ' – '+dayLabel(r.end_date);
    if (r.start_time || r.end_time) s += ' <span class="muted">('+esc(t12(r.start_time) || '…')+'–'+esc(t12(r.end_time) || '…')+')</span>';
    return s;
  }
  var NY = new Intl.DateTimeFormat('en-US', {timeZone:'America/New_York', month:'short', day:'numeric', hour:'numeric', minute:'2-digit'});
  function stamp(s){ if(!s) return ''; var x = new Date(s); return isNaN(x) ? esc(s) : esc(NY.format(x)); }
  function typePill(r){ return r.type === 'CALL_OUT' ? '<span class="pill CALL_OUT">Call-out</span>' : '<span class="pill TIME_OFF">Time off</span>'; }
  function statusPill(r){ return '<span class="pill '+r.status+'">'+r.status.charAt(0)+r.status.slice(1).toLowerCase()+'</span>'; }
  function techCell(r){
    var s = '<b>'+esc(r.tech_name)+'</b>';
    if (r.unconfirmed) s += '<br><span class="pill unconf">Unconfirmed'+(r.reported_by ? ' – reported by '+esc(r.reported_by) : '')+'</span>';
    return s;
  }
  function whPill(r){
    if (r.webhook_status && r.webhook_status.indexOf('failed') === 0)
      return ' <span class="pill wh" data-renotify="'+r.id+'" title="'+esc(r.webhook_status)+' – click to resend">OpenClaw not notified ↻</span>';
    return '';
  }

  function api(url, opts){
    opts = opts || {};
    opts.headers = Object.assign({'Content-Type':'application/json', 'X-CSRFToken':CSRF}, opts.headers || {});
    opts.credentials = 'same-origin';
    return fetch(url, opts).then(function(r){
      return r.json().catch(function(){ return {success:false, error:'HTTP '+r.status}; }).then(function(j){
        if (!r.ok || j.success === false) throw new Error(j.error || ('HTTP '+r.status));
        return j;
      });
    });
  }

  // --- setup hints
  var notes = [];
  if (!BOOT.webhook_configured) notes.push('<b>OPENCLAW_WEBHOOK_URL</b> is not set, so decisions made here are saved but OpenClaw is not told.');
  if (!BOOT.api_configured) notes.push('<b>TIMEOFF_API_TOKEN</b> is not set, so OpenClaw cannot add or read requests yet.');
  if (notes.length) { $('setupNote').innerHTML = notes.join('<br>'); $('setupNote').hidden = false; }

  // --- tabs
  function showTab(name){
    if (['requests','calendar','summary'].indexOf(name) < 0) name = 'requests';
    document.querySelectorAll('section[data-tab]').forEach(function(s){ s.classList.toggle('on', s.dataset.tab === name); });
    document.querySelectorAll('.tabs a').forEach(function(a){ a.classList.toggle('on', a.dataset.go === name); });
    if (name === 'calendar') loadCal();
    if (name === 'summary') loadSummary();
  }
  window.addEventListener('hashchange', function(){ showTab(location.hash.slice(1)); });

  // --- requests
  function pendingRow(r){
    var extra = [];
    if (r.affected_visits_count != null) extra.push(r.affected_visits_count+' Jobber visit'+(r.affected_visits_count === 1 ? '' : 's')+' affected');
    if (r.reminder_due) extra.push('<span class="pill due">Waiting over 1 business day</span>');
    return '<tr><td>'+techCell(r)+'</td><td>'+typePill(r)+'</td><td>'+dates(r)+(extra.length ? '<div class="small muted">'+extra.join(' · ')+'</div>' : '')+'</td>'
      +'<td class="n">'+r.days_count+'</td><td class="small">'+stamp(r.requested_at)+(r.requested_via ? '<br><span class="muted">via '+esc(r.requested_via)+'</span>' : '')+'</td>'
      +'<td><div class="row"><button class="btn sm approve" data-act="APPROVED" data-id="'+r.id+'">Approve</button>'
      +'<button class="btn sm deny" data-act="DENIED" data-id="'+r.id+'">Deny</button></div></td></tr>';
  }
  function loadPending(){
    return api('/api/time-off?status=PENDING').then(function(j){
      var rows = j.requests.slice().sort(function(a,b){ return a.start_date < b.start_date ? -1 : a.start_date > b.start_date ? 1 : a.id - b.id; });
      $('pendingBadge').hidden = !rows.length; $('pendingBadge').textContent = rows.length;
      $('pendingBox').innerHTML = rows.length
        ? '<table class="t"><thead><tr><th>Tech</th><th>Type</th><th>Dates</th><th class="n">Days</th><th>Requested</th><th></th></tr></thead><tbody>'+rows.map(pendingRow).join('')+'</tbody></table>'
        : '<div class="empty">Nothing waiting for a decision.</div>';
    }).catch(function(e){ $('pendingBox').innerHTML = '<div class="empty">Could not load: '+esc(e.message)+'</div>'; });
  }
  function allRow(r){
    return '<tr><td>'+techCell(r)+'</td><td>'+typePill(r)+'</td><td>'+dates(r)+'</td><td class="n">'+r.days_count+'</td>'
      +'<td class="small">'+stamp(r.requested_at)+(r.requested_via ? '<br><span class="muted">via '+esc(r.requested_via)+'</span>' : '')+'</td>'
      +'<td>'+statusPill(r)+whPill(r)+'</td><td class="small">'+(r.decided_by ? esc(r.decided_by)+'<br><span class="muted">'+stamp(r.decided_at)+'</span>' : '<span class="muted">—</span>')+'</td>'
      +'<td><a href="#" class="small" data-hist="'+r.id+'">History</a></td></tr>';
  }
  function loadAll(){
    var q = [], tech = $('fTech').value, month = $('fMonth').value, status = $('fStatus').value;
    if (tech) q.push('tech='+encodeURIComponent(tech));
    if (status) q.push('status='+status);
    if (month) {
      var y = +month.slice(0,4), m = +month.slice(5,7);
      q.push('from='+month+'-01', 'to='+iso(new Date(y, m, 0)));
    }
    return api('/api/time-off'+(q.length ? '?'+q.join('&') : '')).then(function(j){
      $('allBox').innerHTML = j.requests.length
        ? '<table class="t"><thead><tr><th>Tech</th><th>Type</th><th>Dates</th><th class="n">Days</th><th>Requested</th><th>Status</th><th>Decided by</th><th></th></tr></thead><tbody>'+j.requests.map(allRow).join('')+'</tbody></table>'
        : '<div class="empty">No requests match these filters.</div>';
    }).catch(function(e){ $('allBox').innerHTML = '<div class="empty">Could not load: '+esc(e.message)+'</div>'; });
  }
  function refresh(){ loadPending(); loadAll(); }

  BOOT.techs.forEach(function(t){ var o = document.createElement('option'); o.value = o.textContent = t; $('fTech').appendChild(o); });
  ['fTech','fMonth','fStatus'].forEach(function(id){ $(id).addEventListener('change', loadAll); });
  $('fClear').addEventListener('click', function(){ $('fTech').value = ''; $('fMonth').value = ''; $('fStatus').value = ''; loadAll(); });

  document.addEventListener('click', function(ev){
    var b = ev.target.closest('[data-act]');
    if (b) {
      var row = b.closest('tr');
      row.querySelectorAll('button').forEach(function(x){ x.disabled = true; });
      api('/api/time-off/'+b.dataset.id, {method:'PATCH', body:JSON.stringify({status:b.dataset.act})})
        .then(refresh)
        .catch(function(e){ alert('Could not save: '+e.message); row.querySelectorAll('button').forEach(function(x){ x.disabled = false; }); });
      return;
    }
    var h = ev.target.closest('[data-hist]');
    if (h) {
      ev.preventDefault();
      var tr = h.closest('tr'), next = tr.nextElementSibling;
      if (next && next.classList.contains('hist')) { next.remove(); return; }
      api('/api/time-off/'+h.dataset.hist).then(function(j){
        var r = j.request, lines = r.history.map(function(x){
          return stamp(x.changed_at)+' — '+(x.from_status ? esc(x.from_status)+' → ' : 'created as ')+'<b>'+esc(x.to_status)+'</b> by '+esc(x.changed_by || '?')+' <span class="muted">('+esc(x.source)+')</span>';
        });
        if (r.reminder_sent_at) lines.push('Reminder sent to approver '+stamp(r.reminder_sent_at));
        if (r.affected_visits_count != null) lines.push(r.affected_visits_count+' Jobber visits in this period');
        var x = document.createElement('tr'); x.className = 'hist';
        x.innerHTML = '<td colspan="8">'+lines.join('<br>')+'</td>';
        tr.after(x);
      }).catch(function(e){ alert(e.message); });
      return;
    }
    var w = ev.target.closest('[data-renotify]');
    if (w) {
      w.textContent = 'Resending…';
      api('/api/time-off/'+w.dataset.renotify+'/notify', {method:'POST', body:'{}'})
        .then(function(){ setTimeout(loadAll, 4000); }).catch(function(e){ alert(e.message); });
    }
  });

  // --- calendar
  var calMonth = d(TODAY.slice(0,8)+'01');
  function loadCal(){
    var y = calMonth.getFullYear(), m = calMonth.getMonth();
    var first = new Date(y, m, 1), last = new Date(y, m+1, 0);
    var gridStart = new Date(y, m, 1 - first.getDay()), gridEnd = new Date(y, m+1, 6 - last.getDay());
    $('calTitle').textContent = MONTH_LONG[m]+' '+y;
    api('/api/time-off?status=PENDING,APPROVED&from='+iso(gridStart)+'&to='+iso(gridEnd)).then(function(j){
      var reqs = j.requests.slice().sort(function(a,b){ return a.tech_name.localeCompare(b.tech_name); });
      var html = DOW.map(function(x){ return '<div class="dow">'+x+'</div>'; }).join('');
      for (var x = new Date(gridStart); x <= gridEnd; x.setDate(x.getDate()+1)) {
        var s = iso(x), cls = 'd' + (x.getMonth() !== m ? ' out' : '') + (x.getDay() % 6 === 0 ? ' we' : '') + (s === TODAY ? ' today' : '');
        var evs = reqs.filter(function(r){ return r.start_date <= s && r.end_date >= s; }).map(function(r){
          var c = r.status === 'PENDING' ? 'PENDING' : r.type === 'CALL_OUT' ? 'CALL_OUT' : 'APPROVED';
          var tip = r.tech_name+' – '+(r.type === 'CALL_OUT' ? 'call-out' : r.status.toLowerCase())+(r.start_time || r.end_time ? ' ('+t12(r.start_time)+'–'+t12(r.end_time)+')' : '')+(r.unconfirmed ? ' – unconfirmed' : '');
          return '<span class="ev '+c+(r.unconfirmed ? ' unconf' : '')+'" title="'+esc(tip)+'">'+esc(r.tech_name)+(r.start_time || r.end_time ? ' ½' : '')+'</span>';
        }).join('');
        html += '<div class="'+cls+'"><span class="num">'+x.getDate()+'</span>'+evs+'</div>';
      }
      $('cal').innerHTML = html;
    }).catch(function(e){ $('cal').innerHTML = '<div class="empty">Could not load: '+esc(e.message)+'</div>'; });
  }
  $('calPrev').addEventListener('click', function(){ calMonth = new Date(calMonth.getFullYear(), calMonth.getMonth()-1, 1); loadCal(); });
  $('calNext').addEventListener('click', function(){ calMonth = new Date(calMonth.getFullYear(), calMonth.getMonth()+1, 1); loadCal(); });
  $('calToday').addEventListener('click', function(){ calMonth = d(TODAY.slice(0,8)+'01'); loadCal(); });

  // --- tech summary
  for (var yy = THIS_YEAR + 1; yy >= THIS_YEAR - 3; yy--) { var o = document.createElement('option'); o.value = o.textContent = yy; if (yy === THIS_YEAR) o.selected = true; $('sYear').appendChild(o); }
  $('sYear').addEventListener('change', loadSummary);
  function loadSummary(){
    api('/api/time-off/summary?year='+$('sYear').value).then(function(j){
      $('sumBox').innerHTML = j.techs.length
        ? '<table class="t"><thead><tr><th>Tech</th><th class="n">Days taken</th><th class="n">Time off</th><th class="n">Call-outs</th><th class="n">Booked for the year</th><th>Upcoming approved time off</th></tr></thead><tbody>'
          + j.techs.map(function(t){
              return '<tr><td><b>'+esc(t.tech_name)+'</b></td><td class="n big">'+t.days_taken+'</td><td class="n">'+t.time_off_days+'</td>'
                + '<td class="n">'+t.call_out_days+' <span class="muted small">('+t.call_outs+'×)</span></td><td class="n">'+t.days_booked+'</td><td>'
                + (t.upcoming.length ? '<ul class="up">'+t.upcoming.map(function(u){ return '<li>'+dates(u)+' <span class="muted small">· '+u.days_count+' day'+(u.days_count === 1 ? '' : 's')+'</span></li>'; }).join('')+'</ul>' : '<span class="muted">—</span>')
                + '</td></tr>';
            }).join('') + '</tbody></table>'
        : '<div class="empty">No approved time off or call-outs in '+j.year+'.</div>';
    }).catch(function(e){ $('sumBox').innerHTML = '<div class="empty">Could not load: '+esc(e.message)+'</div>'; });
  }

  refresh();
  showTab(location.hash.slice(1));
  setInterval(loadPending, 60000);
})();
</script>
</body>
</html>
'''
