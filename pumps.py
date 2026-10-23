"""
Pumps: every pump, diver, filter and SCADA need for a client, tracked from the
first request to the invoice so nothing is lost.

  Items       one row per client need (the old monthly pump sheet, one row per
              PO). Each item walks a checklist: quote from the vendor (Wettech)
              -> quote to the client -> approved -> scheduled with Wettech ->
              work done -> Wettech's bill -> bill checked against the quote ->
              draft invoice in Jobber -> report logged in Jobber -> closed.
              Once the client pays the Jobber invoice, the vendor's bill is
              flagged to be paid until someone marks it paid.
  Inbox       quotes, bills and pump reports read from the PO@ mailbox (or
              uploaded). Each is filed against its item by PO number, Wettech
              work-order number or client name.
  Bill check  a bill that differs from its quote, or arrives with no quote,
              raises an issue that stays open until someone resolves it.
  Reports     Wettech's Word reports are rebranded (our letterhead and name,
              no technician) by pump_reports.py, then logged as a note on the
              pump's job in Jobber.
  SCADA       every client on SCADA, when it was last renewed and when the
              next annual renewal is due, built from Jobber.
  Jobber      pump/diver/filter/SCADA requests, quotes, jobs and invoices.
              Writes are limited to creating DRAFT quotes, DRAFT invoices and
              notes: the client gets a quote or invoice only when someone in
              the office sends it from Jobber.

Office logins use /pumps. OpenClaw uses the same actions at /api/pumps/...
with "Authorization: Bearer <OPENCLAW_API_KEY>". See PUMPS_README.md and
PUMPS_OPENCLAW.md.

Hooked into app.py with init_pumps(app, csrf, DB_PATH, ...).
"""
import base64
import contextvars
import difflib
import hashlib
import hmac
import io
import math
import json
import os
import re
import sqlite3
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
import time
from datetime import date, datetime, timedelta
from urllib.parse import quote as url_quote
from zoneinfo import ZoneInfo

import requests as http_requests
from flask import (Blueprint, Response, jsonify, redirect, render_template_string, request, send_file,
                   session, url_for)

import pump_reports
from pumps_page import PUMPS_PAGE

# This deployment's version - the same in every worker. An open Pumps page
# compares it with the server's and reloads itself after a new deployment.
try:
    with open(__file__, 'rb') as _f:
        APP_VERSION = hashlib.sha1(_f.read() + PUMPS_PAGE.encode()).hexdigest()[:12]
except OSError:
    APP_VERSION = hashlib.sha1(PUMPS_PAGE.encode()).hexdigest()[:12]

TZ = ZoneInfo('America/New_York')
bp = Blueprint('pumps', __name__)

# Filled in by init_pumps(): the database, the PO mailbox helpers from app.py,
# and the app's secret (used to sign file links and encrypt Jobber sign-ins).
CFG = {}

# ── who may use it ───────────────────────────────────────────────────────────
PUMPS_ROLES = ('office',)
NEVER_ROLES = ('technician', 'property_manager')
# Optional: exactly these usernames (comma-separated), whatever their role.
PUMPS_USERS = {u.strip().lower() for u in os.environ.get('PUMPS_USERS', '').split(',') if u.strip()}
# OpenClaw's key, shared with the older /api/openclaw/pumps intake.
OPENCLAW_API_KEY = os.environ.get('OPENCLAW_API_KEY', '')
# Switched off (Oct 2026): Pumps is used by the office only.
OPENCLAW_ENABLED = os.environ.get('PUMPS_OPENCLAW', 'false').lower() in ('1', 'true', 'yes', 'on')

# ── settings ─────────────────────────────────────────────────────────────────
CLAUDE_MODEL = os.environ.get('PUMPS_CLAUDE_MODEL', 'claude-opus-5-5')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
# Pumps reads Wettech's quotes, bills and reports with its own reader. Claude
# is only used when this is switched on (the key is shared with the PO app).
USE_CLAUDE = os.environ.get('PUMPS_USE_CLAUDE', 'false').lower() in ('1', 'true', 'yes', 'on') \
    and bool(ANTHROPIC_API_KEY)
AUTO_SCAN = os.environ.get('PUMPS_AUTO_SCAN', 'true').lower() in ('1', 'true', 'yes', 'on')
SCAN_EVERY_MIN = max(10, int(os.environ.get('PUMPS_SCAN_EVERY_MINUTES', '30') or 30))
# How often Jobber is synced on its own, so nobody has to press Sync.
JOBBER_SYNC_EVERY_MIN = max(5, int(os.environ.get('PUMPS_JOBBER_SYNC_MINUTES', '15') or 15))
# The first scan only reads mail from this date on (default: 60 days back), so
# turning the app on does not run years of old mail through it.
SCAN_SINCE = os.environ.get('PUMPS_SCAN_SINCE', '')
MARKUP_PCT = float(os.environ.get('PUMPS_MARKUP_PCT', '0') or 0)
# Our quote to the client = the vendor's price plus this (Simon's Jobber quote
# 9136: Wettech $1,158.99 tax included -> $1,506.69, i.e. 30%).
QUOTE_MARKUP_PCT = float(os.environ.get('PUMPS_QUOTE_MARKUP_PCT', '30') or 0)
# Government clients (Sarasota County, Oct 2026) are billed their own way: the
# sub's cost plus 10%, one "PUMP SERVICE" line with their WO # and PO #, the
# work, and "Subcontractor Cost / Vendor 10% Markup / Total Cost"; no sales tax.
GOV_MARKUP_PCT = float(os.environ.get('PUMPS_GOV_MARKUP_PCT', '10') or 0)
GOV_CLIENTS = re.compile(os.environ.get('PUMPS_GOV_CLIENTS', r'\bsarasota\s+county\b'), re.I)
# Our client quote is drafted in Jobber only when someone clicks Draft quote -
# never on its own when a vendor quote arrives or is read again.
AUTO_DRAFT_QUOTES = False
# A rebranded service report is put on the site's pump job in Jobber as a
# note ("October Pump Report" + the PDF, named as the vendor sent it) as soon as it arrives, when the
# job is clear.
AUTO_LOG_REPORTS = os.environ.get('PUMPS_AUTO_LOG_REPORTS', 'true').lower() in ('1', 'true', 'yes', 'on')
MATCH_TOLERANCE = float(os.environ.get('PUMPS_MATCH_TOLERANCE', '0.50') or 0.5)
SCADA_DUE_SOON_DAYS = int(os.environ.get('PUMPS_SCADA_DUE_SOON_DAYS', '30') or 30)
STALE_DAYS = int(os.environ.get('PUMPS_STALE_DAYS', '7') or 7)
WEBHOOK_URL = os.environ.get('PUMPS_WEBHOOK_URL', '')

# ── Jobber ───────────────────────────────────────────────────────────────────
# Pumps has its own Jobber app connection (it needs write access to quotes,
# invoices and notes; the Cash Flow connection is read-only). JOBBER_API_TOKEN, if set,
# is used only when no connection has been made.
JOBBER_CLIENT_ID = os.environ.get('PUMPS_JOBBER_CLIENT_ID', '')
JOBBER_CLIENT_SECRET = os.environ.get('PUMPS_JOBBER_CLIENT_SECRET', '')
JOBBER_CALLBACK_URL = os.environ.get('PUMPS_JOBBER_CALLBACK_URL', '')
JOBBER_STATIC_TOKEN = os.environ.get('JOBBER_API_TOKEN', '')
JOBBER_API_VERSION = os.environ.get('JOBBER_API_VERSION', '2025-04-16')
TOKEN_KEY = os.environ.get('PUMPS_TOKEN_KEY', '')
JOBBER_GQL = 'https://api.getjobber.com/api/graphql'
JOBBER_AUTHORIZE = 'https://api.getjobber.com/api/oauth/authorize'
JOBBER_TOKEN = 'https://api.getjobber.com/api/oauth/token'

# The only Jobber mutations this app may ever run. Nothing here sends,
# emails, texts or marks anything as sent - quotes and invoices are created as
# drafts and stay drafts until someone in the office sends them from Jobber.
ALLOWED_MUTATIONS = frozenset({'quoteCreate', 'invoiceCreate', 'jobCreateNote', 'clientCreateNote',
                               'requestCreateNote', 'quoteCreateNote', 'invoiceCreateNote',
                               # An approved quote made a job, and a service-call visit on a job (Oct 2026).
                               'jobCreate', 'visitCreate', 'jobAddVisit', 'jobCreateVisit', 'jobVisitCreate',
                               # Closing a one-off pump job that's invoiced, when someone clicks Close job (Oct 2026).
                               # Only close_jobber_job() uses it.
                               'jobClose', 'closeJob',
                               # Redoing the lines of OUR OWN quote while it is still a draft, after the
                               # vendor's quote is read again (Oct 2026). update_draft_quote() checks the
                               # quote is a draft right before, and never touches a sent quote.
                               'quoteCreateLineItems', 'quoteDeleteLineItems',
                               # Marking the recurring maintenance job's visit for the bill's month complete,
                               # right before its draft invoice is made (Oct 2026). Only complete_visit_for_bill() uses it.
                               'visitComplete', 'visitMarkComplete', 'completeVisit'})

# What counts as pump work when searching Jobber, by category.
JOBBER_TERMS = {
    'pump': ['pump', 'fountain', 'wettech', 'wttech', 'wetech', 'lift station', 'vfd', 'well pump'],
    'diver': ['diver'],
    'filter': ['filter'],
    'scada': ['scada'],
}
TITLE_PATTERNS = {
    'scada': re.compile(r'\bscada\b', re.I),
    'diver': re.compile(r'\bdivers?\b', re.I),
    'filter': re.compile(r'\bfilters?\b', re.I),
    'pump': re.compile(r'\bpumps?\b|\bfountains?\b|\bwe?t+e?ch\b|\bwet\*|\blift\s+station\b|\bvfd\b|\bwell\s*(?:pumps?|#|no\.?\s*\d|\d|motors?|service|repairs?)\b|\b(?:deep|irrigation|potable)\s+wells?\b', re.I),
}
# Strong words for mail from someone who is not a known pump vendor.
STRONG_TERMS = re.compile(r'pump\s+station|pump\s+report|pump\s+maintenance|pump\s+service|\bscada\b|\bdivers?\b|'
                          r'wet\s+well|lift\s+station|submersible\s+pump|centrifugal\s+pump|fountain\s+maintenance|'
                          r'irrigation\s+pump|\bvfd\b', re.I)

CATEGORIES = ('repair', 'maintenance', 'install', 'diver', 'filter', 'scada', 'inspection', 'other')
STEPS = [
    ('assessment', '{vendor} visit to assess'),
    ('vendor_quote', 'Quote from {vendor}'),
    ('client_quote', 'Quote sent to client'),
    ('client_approved', 'Client approved'),
    ('scheduled', 'Scheduled with {vendor}'),
    ('work_done', 'Work done'),
    ('vendor_bill', 'Bill from {vendor}'),
    ('bill_checked', 'Bill checked against quote'),
    ('invoice_drafted', 'Draft invoice in Jobber'),
    ('report_logged', 'Report logged in Jobber'),
    ('closed', 'Invoice sent from Jobber - close out'),
]
STEP_KEYS = [k for k, _ in STEPS]
# Steps an item only has when switched on: the vendor's visit to look before
# quoting. Absent means not needed, so items made before it existed are unchanged.
OPTIONAL_STEPS = ('assessment',)


def _with_optional(steps):
    return {**{k: {'na': True} for k in OPTIONAL_STEPS if k not in steps}, **steps}


# A vendor bill for a maintenance visit ("Service to perform quarterly
# maintenance ... Maintenance Report Attached", Oct 2026) needs no quote - it
# is billed at the client's recurring job price - unless the bill names one.
_MAINT_WORDS = re.compile(r'\bmaint(?:enance|\.)?\b', re.I)
_QUOTE_WORDS = re.compile(r'\b(?:quote[sd]?|quotation|estimate|proposal)\b', re.I)
# "... maintenance ... OCTOBER 2026. As per quotation." (Rosewood, Oct 2026): the
# month's visit under the contract quote - Wettech's boilerplate, not quoted work.
_SERVICE_MONTH = re.compile(r'\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?,?\s+20\d\d\b', re.I)
_AS_PER_QUOTE = re.compile(r'\bas per (?:the |our |your )?(?:quote|quotation|proposal|contract)\b', re.I)


def _names_a_quote(text):
    """Whether a bill's text points at quoted work. "As per quotation" on a
    bill for a named month is the maintenance contract, not a quote."""
    if _SERVICE_MONTH.search(text or ''):
        text = _AS_PER_QUOTE.sub('', text)
    return bool(_QUOTE_WORDS.search(text or ''))


def maintenance_bill(doc):
    """True when a bill is for a maintenance visit and says nothing of a quote."""
    if (doc or {}).get('kind') != 'bill':
        return False
    items = doc.get('line_items')
    if isinstance(items, str):
        try:
            items = json.loads(items or '[]')
        except ValueError:
            items = []
    text = ' '.join([doc.get('description') or '', doc.get('proposal_title') or '', doc.get('quote_reference') or '',
                     doc.get('notes') or ''] + [f"{i.get('name') or ''} {i.get('description') or ''}"
                                                for i in items or [] if isinstance(i, dict)])
    return bool(_MAINT_WORDS.search(text)) and not _names_a_quote(text)


_NO_QUOTE_STEPS = ('vendor_quote', 'client_quote', 'client_approved', 'bill_checked')


# A bill that says more work needs a quote ("Bearings worn - quote to follow",
# "Recommend replacing the check valve, will send a quote") puts that work on
# the watchlist as its own item, waiting on the vendor's quote (Oct 2026).
# Only what the vendor says is coming or needed - "As per quotation" or
# "Quote #4512" on a bill is the quote already done.
_QUOTE_NOUN = r'(?:quote|quotation|estimate|proposal)'
_QUOTE_NEEDED = re.compile(
    rf'\b{_QUOTE_NOUN}s?\s+(?:to\s+follow|will\s+follow|(?:will\s+be|to\s+be|being)\s+'
    rf'(?:sent|provided|submitted|forwarded)|forthcoming|(?:is\s+)?(?:needed|required|necessary))\b'
    rf'|\b(?:need|needs|needed|require|requires|required|request|requesting)\s+(?:an?\s+)?'
    rf'(?:(?:new|separate|additional|another)\s+)?{_QUOTE_NOUN}\b'
    rf"|\b(?:will|to|we'?ll|shall)\s+(?:send|provide|submit|forward|prepare|follow\s+up\s+with|get)\s+"
    rf'(?:you\s+|over\s+)?(?:an?\s+|the\s+)?(?:(?:new|separate|additional)\s+)?{_QUOTE_NOUN}\b'
    rf'|\b(?:will|to)\s+(?:re-?)?quote\b'
    rf'|\brecommend\w*\b[^.\n]{{0,120}}\b{_QUOTE_NOUN}\b', re.I)


def _quote_needed_in(texts):
    """The first sentence of the texts that says a quote is coming or needed, or ''."""
    for text in texts:
        for part in re.split(r'(?<=[.!?])\s+|\n+', text or ''):
            part = ' '.join(part.split()).strip(' |')
            if _QUOTE_NEEDED.search(part):
                return part[:300]
    return ''


def sweep_quote_needed(days=60, actor='Pumps'):
    """Reports and bills of the last `days` days that say a quote is needed but never got their
    "quote needed" item (Wild Blue PS1, Oct 2026 - and ones filed before the check existed)."""
    since = (_today() - timedelta(days=days)).isoformat()
    conn = _conn()
    made = []
    try:
        for r in conn.execute("SELECT * FROM pump_docs d WHERE kind IN ('report', 'bill') AND status != 'dismissed' "
                              "AND COALESCE(created_at, '') >= ? AND NOT EXISTS "
                              "(SELECT 1 FROM pump_events e WHERE e.doc_id = d.id AND e.action='quote needed')",
                              (since,)).fetchall():
            doc = _doc_dict(r)
            if quote_needed_note(doc):
                new = _quote_needed_item(conn, doc, doc['case_id'], actor)
                made.append(new or doc['id'])
        conn.commit()
    finally:
        conn.close()
    return made


def quote_needed_note(doc):
    """The line of a vendor bill - or the comments of a pump report - that
    says a quote is needed, or ''."""
    if (doc or {}).get('kind') == 'report':
        rf = doc.get('report_fields')
        rf = json.loads(rf or '{}') if isinstance(rf, str) else (rf or {})
        return rf.get('quote_needed') or _quote_needed_in([doc.get('text_excerpt') or ''])
    if (doc or {}).get('kind') != 'bill':
        return ''
    items = doc.get('line_items')
    if isinstance(items, str):
        try:
            items = json.loads(items or '[]')
        except ValueError:
            items = []
    texts = [doc.get('description') or ''] + [f"{i.get('name') or ''} {i.get('description') or ''}"
                                              for i in items or [] if isinstance(i, dict)]
    texts.append(doc.get('text_excerpt') or '')
    for text in texts:
        for part in re.split(r'(?<=[.!?])\s+|\n+', text):
            part = ' '.join(part.split())
            if _QUOTE_NEEDED.search(part):
                return part[:300]
    return ''


def _quote_needed_item(conn, doc, case_id, actor):
    """Put the quote a bill asks for on the watchlist, once per bill. Returns the new item id or None."""
    note = quote_needed_note(doc)
    if not note or conn.execute("SELECT 1 FROM pump_events WHERE doc_id=? AND action='quote needed'",
                                (doc['id'],)).fetchone():
        return None
    where = beatrice_site(doc.get('client_name'), doc.get('site'))
    if where:
        # Wettech quotes those to Beatriz - nothing to track, but the office is told a quote is
        # coming, to send on when it does (Wild Blue PS1's lightning damage, Oct 2026).
        add_todo(conn, f"beatriz-quote:{doc['id']}", f"{where}: {doc.get('vendor') or 'Wettech'} quote to follow - "
                                                     f"send it to {BEATRICE} when it comes",
                 f"{note} (from the {'pump report' if doc.get('kind') == 'report' else 'bill'}"
                 f"{' of ' + doc['doc_date'] if doc.get('doc_date') else ''})", {'case_id': case_id, 'doc_id': doc['id']})
        _event(conn, actor, 'quote needed', f"{note} - goes to {BEATRICE}", case_id=case_id, doc_id=doc['id'])
        return None
    row = conn.execute('SELECT * FROM pump_cases WHERE id=?', (case_id,)).fetchone() if case_id else None
    case = dict(row) if row else {}
    client = doc.get('client_name') or case.get('client_name') or ''
    vendor = doc.get('vendor') or case.get('vendor') or ''
    num = f" #{doc['doc_number']}" if doc.get('doc_number') else ''
    what = f"{vendor or 'the vendor'}'s {'pump report' if doc.get('kind') == 'report' else 'bill' + num}"
    title = (f'{client} - {note}' if client else note)[:160]
    same = conn.execute("SELECT id FROM pump_cases WHERE status='open' AND title=?", (title,)).fetchone()
    if same:
        # The bill and the report in one email both said it: one item.
        _event(conn, actor, 'quote needed', f"{what[0].upper() + what[1:]} says it too: {note}",
               case_id=same['id'], doc_id=doc['id'])
        return None
    # No PO or W/O: those belong to the billed job, and a second item with them
    # would stop documents matching by PO.
    new_id = create_case(conn, {'title': title, 'category': 'repair',
                                'client_name': client, 'site': doc.get('site') or case.get('site') or '',
                                'vendor': vendor,
                                'description': f"{note}\n(From {what}.)",
                                # Waiting since we learned of it, not since the date on the vendor's
                                # paper (Anna's Place, Oct 2026: a day-old item read "8 days").
                                'opened_on': _today().isoformat()}, actor, source='bill')
    _event(conn, actor, 'quote needed', f"{what[0].upper() + what[1:]} says: {note}",
           case_id=new_id, doc_id=doc['id'])
    _event(conn, actor, 'quote needed', f'Put on the watchlist as job {new_id}: {note}', case_id=case_id)
    # Already quoted in Jobber and waiting on the client: not "waiting on a quote".
    it = pending_quote_for(conn, dict(conn.execute('SELECT * FROM pump_cases WHERE id=?', (new_id,)).fetchone()))
    if it:
        link_pending_quote(conn, new_id, it, actor)
    return new_id


def _maintenance_needs_no_quote(conn, case_id, actor):
    """A maintenance bill on an item still waiting on a quote: it's maintenance,
    and the quote steps don't apply (unless a vendor quote is on the item)."""
    case = conn.execute('SELECT category, steps FROM pump_cases WHERE id=?', (case_id,)).fetchone()
    if not case:
        return False
    steps = json.loads(case['steps'] or '{}')
    if (steps.get('vendor_quote') or {}).get('at') or conn.execute(
            "SELECT 1 FROM pump_docs WHERE case_id=? AND kind='quote' AND status != 'dismissed'", (case_id,)).fetchone():
        return False
    if case['category'] in ('maintenance', 'inspection') and \
            all((steps.get(k) or {}).get('na') or (steps.get(k) or {}).get('at') for k in _NO_QUOTE_STEPS):
        return False
    if case['category'] not in ('maintenance', 'inspection'):
        conn.execute("UPDATE pump_cases SET category='maintenance' WHERE id=?", (case_id,))
    for k in _NO_QUOTE_STEPS:
        if not (steps.get(k) or {}).get('at'):
            _set_step(conn, case_id, k, by=actor, na=True)
    resolve_issues(conn, case_id, 'no_quote', actor, 'Maintenance bill - no quote needed')
    _event(conn, actor, 'no quote needed', 'Maintenance bill - billed at the recurring job price', case_id=case_id)
    return True


def fix_terms_as_po(conn):
    """Items and documents whose PO was read from the payment terms."""
    for table in ('pump_cases', 'pump_docs'):
        for r in conn.execute(f"SELECT id, po_number FROM {table} WHERE po_number != ''").fetchall():
            if not clean_po(r['po_number']):
                conn.execute(f"UPDATE {table} SET po_number='' WHERE id=?", (r['id'],))


def fix_maintenance_bills(conn, actor='Pumps'):
    """Open items waiting on a quote that only have a maintenance bill."""
    n = 0
    for r in conn.execute("SELECT DISTINCT c.id FROM pump_cases c JOIN pump_docs d ON d.case_id=c.id "
                          "WHERE c.status='open' AND c.stage IN ('assessment', 'vendor_quote', 'client_quote', "
                          "'client_approved') AND d.kind='bill' AND d.status != 'dismissed'").fetchall():
        bills = [dict(d) for d in conn.execute("SELECT * FROM pump_docs WHERE case_id=? AND kind='bill' "
                                               "AND status != 'dismissed'", (r['id'],))]
        if bills and all(maintenance_bill(b) for b in bills):
            n += _maintenance_needs_no_quote(conn, r['id'], actor)
    return n
# Steps that do not apply by default, per kind of work. Any step can be
# switched on or off on the item.
NA_BY_CATEGORY = {
    'repair': ['report_logged'],
    'install': ['report_logged'],
    'diver': ['report_logged'],
    'filter': ['report_logged'],
    'maintenance': ['vendor_quote', 'client_quote', 'client_approved', 'bill_checked'],
    'inspection': ['vendor_quote', 'client_quote', 'client_approved', 'bill_checked'],
    'scada': ['vendor_quote', 'work_done', 'bill_checked', 'report_logged'],
    'other': ['report_logged'],
}
SHEET_COLUMNS = ['po_number', 'opened_on', 'vendor', 'client_name', 'description', 'approved_by',
                 'jobber_request_made', 'vendor_quote_amount', 'vendor_bill_amount', 'vendor_bill_number',
                 'sei_invoice_number', 'amount', 'notes']
CASE_TEXT_FIELDS = ('title', 'category', 'client_name', 'site', 'po_number', 'vendor', 'description',
                    'approved_by', 'jobber_request_made', 'vendor_quote_number', 'vendor_bill_number',
                    'wo_number', 'sei_invoice_number', 'notes', 'scheduled_for', 'jobber_client_id',
                    'jobber_property_id', 'opened_on')
CASE_MONEY_FIELDS = ('vendor_quote_amount', 'vendor_quote_total', 'vendor_bill_amount', 'vendor_bill_total',
                     'amount')


# ═════════════════════════════════════════════════════════════════════════════
# basics
# ═════════════════════════════════════════════════════════════════════════════

def _now():
    return datetime.now(TZ).replace(microsecond=0)


def _now_text():
    return _now().strftime('%Y-%m-%d %H:%M:%S')


def _today():
    return _now().date()


def _conn():
    conn = sqlite3.connect(CFG['db_path'], timeout=30)
    conn.row_factory = sqlite3.Row
    action = _UNDO_ACTION.get()
    if action:
        _watch_for_undo(conn, action)
    return conn


# ── undo ──────────────────────────────────────────────
# While an office click is being handled, every row it adds, changes or
# deletes in these tables is written down (pump_undo_rows) so the click can
# be undone. Temporary triggers on that request's connections only - the
# scan, the Jobber sync and other background work are never recorded.
UNDO_TABLES = ('pump_cases', 'pump_docs', 'pump_issues', 'pump_events', 'pump_scada', 'pump_client_contacts',
               'pump_jobber_items', 'pump_site_aliases', 'pump_todos', 'pump_dive_sites', 'pump_scada_accounts',
               'pump_maint_accounts', 'pump_todo_hidden', 'pump_maint_notices')
_UNDO_ACTION = contextvars.ContextVar('pump_undo_action', default=0)


def _watch_for_undo(conn, action):
    for t in UNDO_TABLES:
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info({t})')]
        if not cols:
            continue
        old = 'json_object(' + ', '.join(f"'{c}', OLD.{c}" for c in cols) + ')'
        for op, when, rid, row in (('I', 'INSERT', 'NEW.rowid', 'NULL'), ('U', 'UPDATE', 'OLD.rowid', old),
                                   ('D', 'DELETE', 'OLD.rowid', old)):
            conn.execute(f'CREATE TEMP TRIGGER IF NOT EXISTS undo_{t}_{op} AFTER {when} ON main.{t} BEGIN '
                         f'INSERT INTO pump_undo_rows (action_id, tbl, op, row_id, old) '
                         f"VALUES ({int(action)}, '{t}', '{op}', {rid}, {row}); END")


def _iso_date(value):
    """'9/30/2026', '2026-09-30', '3-25-2026', 'September 30, 2026' -> '2026-09-30' (or '')."""
    if not value:
        return ''
    s = str(value).strip()[:40]
    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y', '%m-%d-%Y', '%m-%d-%y', '%B %d, %Y', '%b %d, %Y'):
        try:
            return datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    m = re.match(r'(\d{4}-\d{2}-\d{2})', s)
    return m.group(1) if m else ''


def _money(v):
    if v is None or v == '':
        return None
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    s = re.sub(r'[^\d.\-]', '', str(v))
    try:
        return round(float(s), 2) if s not in ('', '-', '.') else None
    except ValueError:
        return None


def _month_tab(d):
    try:
        return datetime.strptime((d or '')[:10], '%Y-%m-%d').strftime('%B %Y')
    except ValueError:
        return _now().strftime('%B %Y')


def po_key(s):
    """'PO#0153', 'PO 153', '0153' -> '153'. Empty when there is no number."""
    m = re.search(r'(\d{2,7})', str(s or ''))
    return str(int(m.group(1))) if m else ''


def po_from_title(title):
    m = re.search(r'\bP\.?\s?O\.?\s*#?\s*(\d{2,6})\b', title or '', re.I)
    return str(int(m.group(1))) if m else ''


_STOP = {'the', 'at', 'of', 'and', 'hoa', 'inc', 'llc', 'association', 'assoc', 'assn', 'condo', 'condominium',
         'community', 'communities', 'master', 'property', 'properties', 'management', 'mgmt', 'homeowners',
         'homeowner', 'owners', 'poa', 'cdd', 'club', 'co', 'corp', 'company', 'a', 'an', 'in', 'on', 'for',
         'naples', 'fort', 'myers', 'estero', 'bonita', 'springs', 'fl', 'florida', 'work', 'orders', 'st',
         'stahlman', 'england', 'sei'}


def name_tokens(s):
    s = (s or '').lower()
    s = re.split(r'\bc/o\b|\bcare of\b', s)[0]
    s = re.sub(r'\s*[-–]\s*(lee|collier|charlotte|sarasota|hendry|manatee|glades)\s+county\b.*$', '', s)
    toks = re.findall(r'[a-z0-9]+', s)
    keep = [t for t in toks if t not in _STOP and len(t) > 1]
    # Keep place words when they are all there is ("Estero" alone).
    return set(keep) or set(t for t in toks if len(t) > 2 and t not in ('the', 'and', 'of', 'at'))


def _join_split_words(ta, b, tb):
    """tb with two neighbouring words written as one in ta joined up:
    Wettech's "Watercrest" is Jobber's "WATER CREST" (Oct 2026)."""
    order = [t for t in re.findall(r'[a-z0-9]+', re.split(r'\bc/o\b|\bcare of\b', (b or '').lower())[0]) if t in tb]
    for x, y in zip(order, order[1:]):
        if x + y in ta and x + y not in tb:
            tb = (tb - {x, y}) | {x + y}
    return tb


def similarity(a, b):
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0.0
    tb = _join_split_words(ta, b, tb)
    ta = _join_split_words(tb, a, ta)
    inter = len(ta & tb)
    contain = inter / len(ta)
    jacc = inter / len(ta | tb)
    return round(0.7 * contain + 0.3 * jacc, 3)


_SITEONE_STORE = re.compile(r'\s*siteone(?:us)?_\d', re.I)


def _dismiss_siteone_store(c, now):
    """Once (Oct 22 2026): SiteOne store invoices waiting on "Look at" - parts bought, not pump work."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pump_docs'").fetchone():
        return
    c.execute("INSERT OR IGNORE INTO pump_state (key, value) VALUES ('siteone_store_oct26', ?)", (json.dumps(now),))
    if c.rowcount != 1:
        return
    for did, fname in c.execute("SELECT id, file_name FROM pump_docs WHERE case_id IS NULL AND status IN ('new', 'review') "
                                "AND source='email'").fetchall():
        if _SITEONE_STORE.match(fname or ''):
            c.execute("UPDATE pump_docs SET status='dismissed', review_reason=?, updated_at=? WHERE id=?",
                      ('SiteOne store invoice - not pump work', _now_text(), did))


def _vendor_display(text):
    v = pump_reports.vendor_for(text)
    return v.get('display') if v else ''


def _vendor_profile(name):
    for v in pump_reports.load_vendors():
        if (name or '').lower() in [v.get('display', '').lower(), v.get('key', '').lower()]:
            return v
    return pump_reports.vendor_for(name or '') or {}


def _vendor_email(vendor_name):
    if vendor_name in REPAIR_COMPANIES:
        return REPAIR_COMPANIES[vendor_name][1]
    v = _vendor_profile(vendor_name)
    return v.get('contact_email') or os.environ.get('PUMPS_VENDOR_EMAIL', 'office@wettec.biz')


# ═════════════════════════════════════════════════════════════════════════════
# database
# ═════════════════════════════════════════════════════════════════════════════

# What the office told us (Oct 2026) about one account's names.
SEED_SITE_ALIASES = [
    # The office (Oct 2026): every Huntington quote - "Huntington #6", any
    # phase or "Residence Assoc." - is for the Lakes Master Association.
    # Its 41 properties are the pump locations, picked per quote as usual.
    {'place': 'Huntington', 'area': '', 'client_id': 'Z2lkOi8vSm9iYmVyL0NsaWVudC83NTE2ODg4Nw==',
     'client_name': 'HUNTINGTON LAKES MASTER ASSOCIATION C/O Moore PM Services', 'property_id': '',
     'property_label': '', 'any_name': 1, 'not_with': 'Legends',
     'note': 'All Huntington quotes ("Huntington #6", "Huntington Lakes Phase 3"...) go to the Master '
             'Association, not the phases. Huntington I/II at the Legends are other clients.'},
    {'place': 'Carlisle', 'area': '', 'client_id': 'Z2lkOi8vSm9iYmVyL0NsaWVudC80OTAwNzI1OA==',
     'client_name': 'Greenscapes', 'property_id': '', 'property_label': '',
     'note': 'The Carlisle (Naples) is on the Greenscapes account.'},
    {'place': 'Carlisle', 'area': 'back station', 'client_id': 'Z2lkOi8vSm9iYmVyL0NsaWVudC80OTAwNzI1OA==',
     'client_name': 'Greenscapes', 'property_id': 'Z2lkOi8vSm9iYmVyL1Byb3BlcnR5LzUyOTc4MjYw',
     'property_label': '6945 Carlisle Court, The Carlisle Naples- Pump #1 Exit',
     'note': '"Back station" at the Carlisle means the Pump #1 exit pump (this account only).'},
    {'place': 'Miramar Lakes', 'area': '', 'client_id': 'Z2lkOi8vSm9iYmVyL0NsaWVudC8zNTM3MDgwNw==',
     'client_name': 'MIROMAR LAKES', 'property_id': 'Z2lkOi8vSm9iYmVyL1Byb3BlcnR5LzM4MTYzODEy',
     'property_label': '17910 Ben Hill Griffin Pkwy, Miromar Lakes',
     'note': 'Wettech writes "Miramar Lakes" for Miromar Lakes (its pumps and fountains).'},
    {'place': 'Spanish Wells', 'area': '', 'client_id': 'Z2lkOi8vSm9iYmVyL0NsaWVudC8zNTM3MDUzOQ==',
     'client_name': 'The Lake Club', 'property_id': 'Z2lkOi8vSm9iYmVyL1Byb3BlcnR5LzM4MTYzNTQ0',
     'property_label': '28432 Highgate Drive, Bonita Springs',
     'job_id': 'Z2lkOi8vSm9iYmVyL0pvYi80MTQyMDAxOA==', 'job_label': '#1609 Quarterly Pump- 850',
     'note': 'Spanish Wells reports go on The Lake Club account, job #1609 "Quarterly Pump- 850".'},
    {'place': 'Lee Memorial', 'area': '', 'client_id': 'Z2lkOi8vSm9iYmVyL0NsaWVudC8zODg2MDA3MQ==',
     'client_name': 'Hodges Funeral Home at Naples Memorial Gardens (David Luginbuel)',
     'property_id': 'Z2lkOi8vSm9iYmVyL1Byb3BlcnR5LzU2Njc0MDU3', 'property_label': '12777 Florida 82, Lehigh Acres',
     'note': 'Wettech still writes "Lee Memorial" (Well 6, Lehigh Acres) - it is the Hodges Funeral Home account.'},
]


def init_db():
    conn = _conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS pump_cases (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  title TEXT DEFAULT '',
                  category TEXT DEFAULT 'repair',
                  client_name TEXT DEFAULT '',
                  site TEXT DEFAULT '',
                  jobber_client_id TEXT DEFAULT '',
                  jobber_property_id TEXT DEFAULT '',
                  po_number TEXT DEFAULT '',
                  vendor TEXT DEFAULT '',
                  description TEXT DEFAULT '',
                  approved_by TEXT DEFAULT '',
                  jobber_request_made TEXT DEFAULT '',
                  vendor_quote_number TEXT DEFAULT '',
                  vendor_quote_amount REAL,
                  vendor_quote_total REAL,
                  vendor_bill_number TEXT DEFAULT '',
                  vendor_bill_amount REAL,
                  vendor_bill_total REAL,
                  wo_number TEXT DEFAULT '',
                  sei_invoice_number TEXT DEFAULT '',
                  amount REAL,
                  notes TEXT DEFAULT '',
                  jobber TEXT DEFAULT '{}',
                  steps TEXT DEFAULT '{}',
                  stage TEXT DEFAULT '',
                  status TEXT DEFAULT 'open',
                  scheduled_for TEXT DEFAULT '',
                  opened_on TEXT DEFAULT '',
                  source TEXT DEFAULT 'manual',
                  legacy_invoice_id INTEGER,
                  created_by TEXT DEFAULT '',
                  created_at TEXT,
                  updated_at TEXT,
                  last_activity_at TEXT,
                  closed_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pump_docs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  kind TEXT DEFAULT 'other',
                  status TEXT DEFAULT 'new',
                  vendor TEXT DEFAULT '',
                  doc_number TEXT DEFAULT '',
                  doc_date TEXT DEFAULT '',
                  po_number TEXT DEFAULT '',
                  wo_number TEXT DEFAULT '',
                  quote_ref TEXT DEFAULT '',
                  ordered_by TEXT DEFAULT '',
                  client_name TEXT DEFAULT '',
                  site TEXT DEFAULT '',
                  category TEXT DEFAULT '',
                  description TEXT DEFAULT '',
                  line_items TEXT DEFAULT '[]',
                  subtotal REAL,
                  tax REAL,
                  total REAL,
                  file_name TEXT DEFAULT '',
                  file_path TEXT DEFAULT '',
                  file_sha TEXT DEFAULT '',
                  branded_path TEXT DEFAULT '',
                  branded_info TEXT DEFAULT '{}',
                  report_fields TEXT DEFAULT '{}',
                  text_excerpt TEXT DEFAULT '',
                  source TEXT DEFAULT 'email',
                  email_uid TEXT DEFAULT '',
                  email_from TEXT DEFAULT '',
                  email_subject TEXT DEFAULT '',
                  email_date TEXT DEFAULT '',
                  case_id INTEGER,
                  extracted_by TEXT DEFAULT '',
                  review_reason TEXT DEFAULT '',
                  jobber TEXT DEFAULT '{}',
                  created_at TEXT,
                  updated_at TEXT)''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_pump_docs_sha ON pump_docs(file_sha)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_pump_docs_case ON pump_docs(case_id)')
    c.execute('''CREATE TABLE IF NOT EXISTS pump_issues (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  case_id INTEGER,
                  doc_id INTEGER,
                  kind TEXT,
                  message TEXT,
                  opened_at TEXT,
                  resolved_at TEXT,
                  resolved_by TEXT,
                  resolution TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pump_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  case_id INTEGER,
                  doc_id INTEGER,
                  at TEXT,
                  actor TEXT,
                  action TEXT,
                  detail TEXT)''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_pump_events_case ON pump_events(case_id)')
    c.execute('''CREATE TABLE IF NOT EXISTS pump_scada (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  client_name TEXT DEFAULT '',
                  jobber_client_id TEXT DEFAULT '',
                  site TEXT DEFAULT '',
                  provider TEXT DEFAULT 'Wettech',
                  annual_amount REAL,
                  last_renewed_on TEXT DEFAULT '',
                  next_due_override TEXT DEFAULT '',
                  recurring INTEGER DEFAULT 0,
                  open_quote TEXT DEFAULT '',
                  history TEXT DEFAULT '[]',
                  active INTEGER DEFAULT 1,
                  notes TEXT DEFAULT '',
                  source TEXT DEFAULT 'jobber',
                  case_id INTEGER,
                  updated_at TEXT,
                  UNIQUE(jobber_client_id, site))''')
    # Each Jobber client's email addresses, refreshed by the Jobber sync, so the to-dos can say
    # who to follow up with (the AP/billing address when there is one).
    c.execute('''CREATE TABLE IF NOT EXISTS pump_client_contacts (
                  client_id TEXT PRIMARY KEY,
                  name TEXT DEFAULT '',
                  emails TEXT DEFAULT '[]',
                  fetched_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pump_jobber_items (
                  jobber_id TEXT PRIMARY KEY,
                  kind TEXT,
                  number TEXT,
                  title TEXT,
                  status TEXT,
                  job_type TEXT DEFAULT '',
                  client_id TEXT,
                  client_name TEXT,
                  property_id TEXT,
                  property_label TEXT,
                  total REAL,
                  created_at TEXT,
                  updated_at TEXT,
                  start_at TEXT,
                  completed_at TEXT,
                  approved_at TEXT,
                  web_uri TEXT,
                  category TEXT,
                  po_number TEXT,
                  case_id INTEGER,
                  ignored INTEGER DEFAULT 0,
                  synced_at TEXT)''')
    try:
        # 1 = the Jobber client is a company, 0 = a person, NULL = not known yet.
        c.execute('ALTER TABLE pump_jobber_items ADD COLUMN client_company INTEGER')
    except sqlite3.OperationalError:
        pass
    c.execute('''CREATE TABLE IF NOT EXISTS pump_state (key TEXT PRIMARY KEY, value TEXT)''')
    init_dive_tables(c)
    init_todo_table(c)
    init_account_tables(c)
    # Account-specific names on vendor paperwork: "Carlisle" is a Greenscapes
    # property, and its "back station" is the Pump #1 exit pump.
    c.execute('''CREATE TABLE IF NOT EXISTS pump_site_aliases (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  place TEXT NOT NULL,
                  area TEXT DEFAULT '',
                  client_id TEXT NOT NULL,
                  client_name TEXT DEFAULT '',
                  property_id TEXT DEFAULT '',
                  property_label TEXT DEFAULT '',
                  note TEXT DEFAULT '',
                  created_by TEXT DEFAULT '',
                  created_at TEXT,
                  UNIQUE(place, area))''')
    for a in SEED_SITE_ALIASES:
        c.execute('''INSERT OR IGNORE INTO pump_site_aliases (place, area, client_id, client_name, property_id,
                       property_label, note, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?)''',
                  (a['place'], a['area'], a['client_id'], a['client_name'], a['property_id'], a['property_label'],
                   a['note'], 'office', _now_text()))
    for table, col in (('pump_docs', 'proposal_title'), ('pump_site_aliases', 'job_id'),
                       ('pump_site_aliases', 'job_label')):
        try:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
    # any_name 1 = the name matches whatever else the vendor adds ("Huntington
    # #6", "Huntington Lakes Phase 3"), not just the name itself; not_with =
    # words that mean another client ("Legends").
    for col, decl in (('any_name', 'INTEGER DEFAULT 0'), ('not_with', "TEXT DEFAULT ''")):
        try:
            c.execute(f'ALTER TABLE pump_site_aliases ADD COLUMN {col} {decl}')
        except sqlite3.OperationalError:
            pass
    for a in SEED_SITE_ALIASES:
        if a.get('any_name'):
            c.execute('UPDATE pump_site_aliases SET any_name=1, not_with=? WHERE place=? AND area=? AND client_id=?',
                      (a.get('not_with', ''), a['place'], a['area'], a['client_id']))
    for a in SEED_SITE_ALIASES:
        # A seed fills in a name the office saved without its property.
        c.execute("UPDATE pump_site_aliases SET property_id=?, property_label=? WHERE place=? AND area=? AND "
                  "client_id=? AND COALESCE(property_id, '')='' AND ?!=''",
                  (a['property_id'], a['property_label'], a['place'], a['area'], a['client_id'], a['property_id']))
        if a.get('job_id'):
            c.execute("UPDATE pump_site_aliases SET job_id=?, job_label=? WHERE place=? AND area=? AND "
                      "COALESCE(job_id, '')=''", (a['job_id'], a['job_label'], a['place'], a['area']))
    # When the vendor's bill was paid, and who said so (added after launch).
    # vendor_follow: the last time we chased the vendor and what they said (JSON).
    # job_status: the latest status update on an approved job (JSON) - parts ordered, client told, scheduled...
    for col in ('vendor_paid_on', 'vendor_paid_by', 'closed_by_hand', 'vendor_follow', 'job_status', 'urgent'):
        try:
            c.execute(f"ALTER TABLE pump_cases ADD COLUMN {col} TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
    # orig_client_name: the name the vendor wrote, kept when the office renames it on the document -
    # a pick is remembered under both, so the vendor's next document fills in too (Oct 2026).
    try:
        c.execute("ALTER TABLE pump_docs ADD COLUMN orig_client_name TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    # parts_lead: how long the vendor said parts take ("2-3 weeks"); NULL = not looked yet, '' = none said.
    try:
        c.execute('ALTER TABLE pump_cases ADD COLUMN parts_lead TEXT')
    except sqlite3.OperationalError:
        pass
    c.execute('''CREATE TABLE IF NOT EXISTS pump_email_scan_log (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  email_uid TEXT UNIQUE,
                  email_sender TEXT,
                  email_subject TEXT,
                  email_date TEXT,
                  scanned_at TEXT,
                  invoices_found INTEGER DEFAULT 0,
                  results TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pump_undo_actions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT, path TEXT, label TEXT DEFAULT '',
                  external TEXT DEFAULT '', created_at TEXT, undone_at TEXT, undone_by TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pump_undo_rows (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, action_id INTEGER, tbl TEXT, op TEXT,
                  row_id INTEGER, old TEXT)''')
    c.execute('CREATE INDEX IF NOT EXISTS pump_undo_rows_action ON pump_undo_rows (action_id)')
    conn.commit()
    _migrate_old_sheet(conn)
    _backfill_visit_step(conn)
    _remove_own_email_service_calls(conn)
    _dedupe_startup_events(conn)
    _seed_homewood_follow_up(conn)
    _restage_quoted_jobs(conn)
    _file_quoted_docs(conn)
    conn.close()


def _file_quoted_docs(conn):
    """Vendor quotes our Jobber quote was drafted from while they were on no job
    (Homewood Suites, quote 9176): each goes on a job with that quote linked, so
    it's on the watchlist waiting on the client. Once."""
    if not _claim_once(conn, 'file_quoted_docs'):
        return
    conn.row_factory = sqlite3.Row
    for r in conn.execute("SELECT id, jobber FROM pump_docs WHERE kind='quote' AND case_id IS NULL "
                          "AND status != 'dismissed' AND jobber LIKE '%quote_id%'").fetchall():
        dj = json.loads(r['jobber'] or '{}')
        if not dj.get('quote_id'):
            continue
        cid = file_document(conn, r['id'], 'Pumps')
        cid = conn.execute('SELECT case_id FROM pump_docs WHERE id=?', (r['id'],)).fetchone()[0]
        if not cid:
            continue
        j = json.loads(conn.execute('SELECT jobber FROM pump_cases WHERE id=?', (cid,)).fetchone()[0] or '{}')
        if not (j.get('quote') or {}).get('id'):
            j['quote'] = {'id': dj['quote_id'], 'number': dj.get('quote_number') or '', 'uri': dj.get('quote_uri'),
                          'status': dj.get('quote_status') or 'draft'}
            if dj.get('client_id'):
                j.setdefault('client', {'id': dj['client_id']})
            conn.execute('UPDATE pump_cases SET jobber=?, jobber_client_id=COALESCE(NULLIF(jobber_client_id, \'\'), ?) '
                         'WHERE id=?', (json.dumps(j), dj.get('client_id') or '', cid))
            _event(conn, 'Pumps', 'linked Jobber', f"quote #{dj.get('quote_number') or ''} - drafted from this "
                                                   f"vendor quote before it was on a job", case_id=cid, doc_id=r['id'])
    conn.commit()


def _restage_quoted_jobs(conn):
    """Jobs whose client quote went out but whose vendor quote was never filed
    here showed "Waiting on quote" (Oct 2026): work out their stage again, once."""
    if not _claim_once(conn, 'restage_quoted_jobs'):
        return
    conn.row_factory = sqlite3.Row
    for r in conn.execute("SELECT id FROM pump_cases WHERE status='open'").fetchall():
        _refresh_case(conn, r['id'])
    conn.commit()


def _claim_once(conn, key):
    """True for exactly one caller per key, ever. The app runs two workers that
    start together; a one-time fix-up claims its key before doing anything, so
    only one of them runs it."""
    cur = conn.execute('INSERT OR IGNORE INTO pump_state (key, value) VALUES (?,?)', (key, json.dumps(_now_text())))
    conn.commit()
    return cur.rowcount == 1


def _dedupe_startup_events(conn):
    """Both workers ran the Oct 2026 fix-ups at once, so their history notes
    were written twice. Keep the first of each. Once."""
    if not _claim_once(conn, 'startup_events_deduped'):
        return
    conn.execute('''DELETE FROM pump_events WHERE actor='Pumps' AND action IN ('waiting on the vendor visit', 'cancelled')
                    AND id NOT IN (SELECT MIN(id) FROM pump_events WHERE actor='Pumps'
                                   AND action IN ('waiting on the vendor visit', 'cancelled')
                                   GROUP BY case_id, action, detail)''')
    conn.commit()


def _backfill_visit_step(conn):
    """Jobs tracked from a Jobber job before the 'vendor visit to assess' step
    existed (Oct 2026) were marked approved and scheduled. If nothing from the
    vendor has come in yet, they are really waiting on the vendor's visit:
    switch that step on with the Jobber visit date, once."""
    conn.row_factory = sqlite3.Row
    if not _claim_once(conn, 'visit_step_backfill'):
        return
    for c in conn.execute("SELECT * FROM pump_cases WHERE status='open' AND source='jobber'").fetchall():
        steps = json.loads(c['steps'] or '{}')
        job_id = ((json.loads(c['jobber'] or '{}').get('job')) or {}).get('id')
        if not job_id or 'assessment' in steps or (steps.get('vendor_quote') or {}).get('at') \
                or conn.execute("SELECT 1 FROM pump_docs WHERE case_id=? AND kind IN ('quote','bill') "
                                "AND status != 'dismissed'", (c['id'],)).fetchone():
            continue
        job = conn.execute('SELECT * FROM pump_jobber_items WHERE jobber_id=?', (job_id,)).fetchone()
        if not job or job['completed_at'] or job['status'] == 'requires_invoicing':
            continue
        due = (job['start_at'] or '')[:10]
        steps['assessment'] = {'due': due} if due else {}
        for k in ('client_approved', 'scheduled'):
            if (steps.get(k) or {}).get('at'):
                steps.pop(k)
        conn.execute("UPDATE pump_cases SET steps=?, vendor=CASE WHEN COALESCE(vendor,'')='' THEN 'Wettech' ELSE vendor END, "
                     "scheduled_for=CASE WHEN scheduled_for=? THEN '' ELSE scheduled_for END WHERE id=?",
                     (json.dumps(steps), due, c['id']))
        _event(conn, 'Pumps', 'waiting on the vendor visit',
               'Made in Jobber before any quote: waiting on Wettech to go out and assess' + (f' ({due})' if due else ''),
               case_id=c['id'])
        _refresh_case(conn, c['id'])
    conn.commit()


def _migrate_old_sheet(conn):
    """The preview's pump_invoices rows (the monthly sheet) become items, once.
    pump_invoices itself is left as it was."""
    if _state_get('sheet_migrated', conn=conn):
        return
    try:
        rows = conn.execute('SELECT * FROM pump_invoices ORDER BY id').fetchall()
    except sqlite3.OperationalError:
        rows = []
    now = _now_text()
    moved = 0
    for r in rows:
        r = dict(r)
        steps = {}
        opened = _iso_date(r.get('entry_date')) or (r.get('created_at') or now)[:10]
        if r.get('vendor_quote_amount') is not None:
            steps['vendor_quote'] = {'at': opened, 'by': 'sheet'}
        if r.get('vendor_invoice_amount') is not None:
            steps['vendor_bill'] = {'at': opened, 'by': 'sheet'}
        if (r.get('sei_invoice_number') or '').strip():
            steps['invoice_drafted'] = {'at': opened, 'by': 'sheet'}
        conn.execute('''INSERT INTO pump_cases (title, category, client_name, po_number, vendor, description,
                          approved_by, jobber_request_made, vendor_quote_amount, vendor_bill_amount,
                          vendor_bill_number, sei_invoice_number, amount, notes, steps, opened_on, source,
                          legacy_invoice_id, created_by, created_at, updated_at, last_activity_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                     ((r.get('job_name') or r.get('description') or 'Pump work')[:120], 'repair',
                      r.get('job_name') or '', r.get('po_number') or '', r.get('vendor') or '',
                      r.get('description') or '', r.get('approved_by') or '', r.get('jobber_request_made') or '',
                      r.get('vendor_quote_amount'), r.get('vendor_invoice_amount'),
                      r.get('vendor_invoice_number') or '', r.get('sei_invoice_number') or '', r.get('amount'),
                      r.get('notes') or '', json.dumps(steps), opened, 'sheet', r.get('id'), 'sheet',
                      r.get('created_at') or now, now, now))
        moved += 1
    _state_set('sheet_migrated', {'at': now, 'rows': moved}, conn=conn)
    conn.commit()
    if moved:
        print(f'✓ Pumps: moved {moved} rows from the old pump sheet into items')
    for (cid,) in conn.execute('SELECT id FROM pump_cases WHERE stage IS NULL OR stage = ""').fetchall():
        _refresh_case(conn, cid)
    conn.commit()


def _state_get(key, default=None, conn=None):
    own = conn is None
    conn = conn or _conn()
    try:
        row = conn.execute('SELECT value FROM pump_state WHERE key=?', (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row[0])
        except (TypeError, ValueError):
            return default
    finally:
        if own:
            conn.close()


def _state_set(key, value, conn=None):
    own = conn is None
    conn = conn or _conn()
    try:
        conn.execute('INSERT OR REPLACE INTO pump_state (key, value) VALUES (?, ?)', (key, json.dumps(value)))
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


def _event(conn, actor, action, detail='', case_id=None, doc_id=None):
    conn.execute('INSERT INTO pump_events (case_id, doc_id, at, actor, action, detail) VALUES (?,?,?,?,?,?)',
                 (case_id, doc_id, _now_text(), actor or 'system', action, (detail or '')[:2000]))
    if case_id:
        conn.execute('UPDATE pump_cases SET last_activity_at=? WHERE id=?', (_now_text(), case_id))


class _FileLock:
    """A lock every gunicorn worker respects (a flock beside the database)."""
    _thread_locks = {}

    def __init__(self, name, blocking=True):
        self.path = os.path.join(CFG.get('data_dir') or '.', f'.pumps_{name}.lock')
        self.tlock = self._thread_locks.setdefault(name, threading.Lock())
        self.blocking = blocking
        self.fh = None
        self.got = False

    def __enter__(self):
        if not self.tlock.acquire(blocking=self.blocking):
            return False
        try:
            import fcntl
            self.fh = open(self.path, 'w')
            try:
                fcntl.flock(self.fh, fcntl.LOCK_EX | (0 if self.blocking else fcntl.LOCK_NB))
            except OSError:
                self.fh.close()
                self.fh = None
                self.tlock.release()
                return False
        except ImportError:
            pass
        self.got = True
        return True

    def __exit__(self, *exc):
        if not self.got:
            return False
        if self.fh:
            import fcntl
            fcntl.flock(self.fh, fcntl.LOCK_UN)
            self.fh.close()
        self.tlock.release()
        return False


# ═════════════════════════════════════════════════════════════════════════════
# items (cases)
# ═════════════════════════════════════════════════════════════════════════════

def _steps_for(category):
    return {k: {'na': True} for k in NA_BY_CATEGORY.get(category, [])}


def _stage(steps, status='open'):
    if status == 'cancelled':
        return 'cancelled'
    steps = dict(_with_optional(steps))
    # Our quote went to the client (Carlisle, #9136): the vendor's visit and price
    # came before it, filed here or not - the job isn't waiting on their quote.
    for later, earlier in (('client_approved', ('assessment', 'vendor_quote', 'client_quote')),
                           ('client_quote', ('assessment', 'vendor_quote'))):
        if (steps.get(later) or {}).get('at'):
            for k in earlier:
                if not (steps.get(k) or {}).get('at') and not (steps.get(k) or {}).get('na'):
                    steps[k] = {'na': True}
    for k in STEP_KEYS:
        s = steps.get(k) or {}
        if not s.get('at') and not s.get('na'):
            return k
    return 'done'


_WORK_LEAD = re.compile(r'^(?:service\s+call\s*-\s*|proposal\s*(?:to|for|-)\s*|estimate\s*(?:to|for|-)\s*|'
                        r'quote\s*(?:to|for|-)\s*|field\s+service\s+to\s+)', re.I)
_TAIL_WORDS = {'a', 'an', 'the', 'and', 'or', 'of', 'to', 'at', 'in', 'on', 'for', 'with', 'is', 'are', 'was', 'not', 'from',
               '&', '+', '-', 'needs', 'need', 'by'}
_CLIENT_TAIL = re.compile(r'\s+(?:master\s+)?(?:association|assoc\.?|hoa|homeowners|condominium|condo|community|'
                          r'inc\.?|llc|property\s+owners)\b.*$', re.I)


def short_title(case):
    """"Client · work" in a few words, to skim the watchlist (Oct 2026):
    "Magnolia Cove Pressure Transducer - Furnish and install new 0-150 Pressure
    transducer, wire up, program and test" -> "Magnolia Cove · New 0-150 pressure transducer"."""
    client = _core_name(case.get('client_name') or '')
    client = re.split(r'\s+c/o\s+', client, flags=re.I)[0]
    client = _CLIENT_TAIL.sub('', client).strip() or client
    if client.isupper():
        client = client.title()
    work = (case.get('title') or '').strip()
    # The client's name at the front of the title is already said.
    for name in sorted({case.get('client_name') or '', client}, key=len, reverse=True):
        if name and work.lower().startswith(name.lower()):
            work = work[len(name):].lstrip(' -:·,')
            break
    else:
        # Spelled differently at the front ("Banayn Bay quote for ..." at Banyan Bay, Oct 2026).
        n = len(client.split())
        if n and difflib.SequenceMatcher(None, ' '.join(work.split()[:n]).lower(), client.lower()).ratio() >= 0.8:
            work = ' '.join(work.split()[n:]).lstrip(' -:·,')
    work = _WORK_LEAD.sub('', work)
    # "Fountian #1... Field service to furnish ..." - the part before the dots says what it is.
    first = re.split(r'\s*(?:\.{2,}|…)\s*', work)[0]
    if len(first.split()) >= 2:
        work = first
    if ' - ' in work and len(work.split(' - ')[0].split()) >= 2:
        work = work.split(' - ')[0]
    work = re.split(r'[,.;]\s|\s+(?:and\s+)?(?:wire\s+up|reinstall|program)\b', work)[0]
    work = re.sub(r'^furnish\s+(?:and|&)\s+install\s+(?:a\s+)?(?:new\s+)?', 'New ', work, flags=re.I)
    words = work.split()[:6]
    while len(words) > 1 and words[-1].lower() in _TAIL_WORDS:
        words.pop()   # not "... front lake is"
    work = ' '.join(words).strip(' -:,')
    # "Magnolia Cove Pressure Transducer" (the work read into the client's name): just "Magnolia Cove".
    cw = client.split()
    while len(cw) > 2 and cw[-1].lower() in work.lower():
        cw.pop()
    client = ' '.join(cw)
    work = (work[:1].upper() + work[1:]) if work else ''
    if work and client and client.lower() in work.lower():
        return work
    return ' · '.join(x for x in (client, work) if x) or case.get('title') or ''


def _case_dict(row, conn=None):
    d = dict(row)
    for k in ('jobber', 'steps', 'vendor_follow', 'job_status'):
        try:
            d[k] = json.loads(d.get(k) or '{}')
        except (TypeError, ValueError):
            d[k] = {}
    d['compare'] = compare_amounts(d)
    d['vendor_pay'] = vendor_pay_state(d)
    vendor = d.get('vendor') or 'vendor'
    d['step_list'] = [{'key': k, 'label': label.format(vendor=vendor), **(_with_optional(d['steps']).get(k) or {})}
                      for k, label in STEPS]
    last = d.get('last_activity_at') or d.get('updated_at') or d.get('created_at') or ''
    try:
        d['idle_days'] = (_now().replace(tzinfo=None) - datetime.strptime(last[:19], '%Y-%m-%d %H:%M:%S')).days
    except ValueError:
        d['idle_days'] = 0
    d['chase'] = vendor_chase(d)
    d['short_title'] = short_title(d)
    if conn is not None:
        d['open_issues'] = [dict(r) for r in conn.execute(
            'SELECT * FROM pump_issues WHERE case_id=? AND resolved_at IS NULL ORDER BY id', (d['id'],))]
        # The last thing done on the job, and how many days ago (Oct 2026).
        ev = conn.execute('SELECT at, actor, action, detail FROM pump_events WHERE case_id=? ORDER BY id DESC LIMIT 1',
                          (d['id'],)).fetchone()
        when = (ev['at'] if ev else last)[:10]
        try:
            days = (_today() - date.fromisoformat(when)).days
        except ValueError:
            days = None
        d['last_action'] = {'at': when, 'days': days, 'action': ev['action'] if ev else '',
                            'detail': (ev['detail'] or '')[:120] if ev else '', 'by': ev['actor'] if ev else ''}
    return d


def vendor_pay_state(case):
    """Whether the vendor's bill is paid. 'due' once the client has paid our
    Jobber invoice and the vendor has not been paid yet."""
    has_bill = (case.get('vendor_bill_amount') is not None or case.get('vendor_bill_total') is not None
                or bool(((case.get('steps') or {}).get('vendor_bill') or {}).get('at')))
    client_status = (((case.get('jobber') or {}).get('invoice') or {}).get('status') or '').lower()
    # A report-only account (Wild Blue...) gets no invoice from us: billed through
    # its monthly contract, so the bill is to pay once the next monthly job (the
    # account's recurring Jobber job's visit after the bill) is completed (the
    # office, Oct 19 2026 - it was the month's end). check_report_only_bills sets it.
    steps = case.get('steps') or {}
    monthly = (case.get('jobber') or {}).get('monthly_visit') or {}
    report_only = ((steps.get('invoice_drafted') or {}).get('by') == 'report only account')
    month_end = ''
    if report_only:
        came = _iso_date(((steps.get('vendor_bill') or {}).get('at') or '')[:10]) or (case.get('opened_on') or '')[:10]
        if came:
            d = date.fromisoformat(came)
            month_end = (date(d.year + d.month // 12, d.month % 12 + 1, 1) - timedelta(days=1)).isoformat()
    if case.get('vendor_paid_on'):
        state = 'paid'
    elif not has_bill:
        state = ''
    elif client_status == 'paid' or (report_only and monthly.get('completed_on')):
        state = 'due'
    else:
        state = 'unpaid'
    return {'state': state, 'paid_on': case.get('vendor_paid_on') or '', 'paid_by': case.get('vendor_paid_by') or '',
            'client_invoice_status': client_status, 'report_only': report_only, 'month_end': month_end,
            'monthly_visit': monthly}


def compare_amounts(case):
    """Quote vs bill, before tax where both sides have it."""
    qa, qt = case.get('vendor_quote_amount'), case.get('vendor_quote_total')
    ba, bt = case.get('vendor_bill_amount'), case.get('vendor_bill_total')
    if ba is None and bt is None:
        return {'state': 'no_bill'}
    if qa is None and qt is None:
        return {'state': 'no_quote'}
    pairs = []
    if qa is not None and ba is not None:
        pairs.append((qa, ba))
    if qt is not None and bt is not None:
        pairs.append((qt, bt))
    if not pairs:
        # One side has only a pre-tax figure and the other only a total.
        pairs = [(qa if qa is not None else qt, ba if ba is not None else bt)]
        if qa is not None and bt is not None:
            pairs.append((qa, bt))
    for q, b in pairs:
        if abs(b - q) <= MATCH_TOLERANCE:
            return {'state': 'match', 'quote': q, 'bill': b, 'diff': round(b - q, 2)}
    q, b = pairs[0]
    return {'state': 'over' if b > q else 'under', 'quote': q, 'bill': b, 'diff': round(b - q, 2)}


def _refresh_case(conn, case_id):
    row = conn.execute('SELECT steps, status, category, client_name, title, site, '
                       'COALESCE(closed_by_hand, \'\') AS by_hand FROM pump_cases WHERE id=?', (case_id,)).fetchone()
    if not row:
        return
    if row['status'] == 'closed' and row['by_hand']:
        return   # marked done by the office: stays done until reopened
    try:
        steps = json.loads(row['steps'] or '{}')
    except (TypeError, ValueError):
        steps = {}
    if not all((steps.get(k) or {}).get('na') or (steps.get(k) or {}).get('at') for k in ('invoice_drafted', 'closed')) \
            and report_only_account(conn, dict(row)):
        # The account gets its report, not an invoice: done once the report is logged.
        for k in ('invoice_drafted', 'closed'):
            if not (steps.get(k) or {}).get('at'):
                steps[k] = {'na': True, 'by': 'report only account'}
        conn.execute('UPDATE pump_cases SET steps=? WHERE id=?', (json.dumps(steps), case_id))
    stage = _stage(steps, row['status'])
    status = row['status']
    closed_at = None
    if stage == 'done' and status == 'open':
        status, closed_at = 'closed', _now_text()
    elif stage != 'done' and status == 'closed':
        status = 'open'
    conn.execute('UPDATE pump_cases SET stage=?, status=?, closed_at=COALESCE(?, closed_at) WHERE id=?',
                 (stage, status, closed_at, case_id))


# Steps that must have happened if a later one has: work that is done was
# scheduled, and a bill means the work is done. (Quotes and the bill check are
# never assumed - those gaps are the point of tracking.)
IMPLIED = {'vendor_quote': ['assessment'], 'client_quote': ['assessment'], 'work_done': ['scheduled'], 'vendor_bill': ['scheduled', 'work_done'],
           'report_logged': ['scheduled', 'work_done']}


def _set_step(conn, case_id, key, at=None, by='system', na=None):
    row = conn.execute('SELECT steps FROM pump_cases WHERE id=?', (case_id,)).fetchone()
    if not row or key not in STEP_KEYS:
        return
    steps = json.loads(row['steps'] or '{}')
    if na is True:
        steps[key] = {'na': True, 'by': by}
    elif at is None and na is False:
        if key in OPTIONAL_STEPS:
            steps[key] = {k: v for k, v in (steps.get(key) or {}).items() if k == 'due'}
        else:
            steps.pop(key, None)
    elif at is not None:
        when = at[:10] if at else _today().isoformat()
        steps[key] = {'at': when, 'by': by}
        for earlier in IMPLIED.get(key, []):
            if earlier in OPTIONAL_STEPS and earlier not in steps:
                continue
            cur = steps.get(earlier) or {}
            if not cur.get('at') and not cur.get('na'):
                steps[earlier] = {'at': when, 'by': f'{by} (implied)'}
    conn.execute('UPDATE pump_cases SET steps=?, updated_at=? WHERE id=?', (json.dumps(steps), _now_text(), case_id))
    _refresh_case(conn, case_id)


def create_case(conn, fields, actor='system', source='manual'):
    category = fields.get('category') if fields.get('category') in CATEGORIES else 'repair'
    steps = _steps_for(category)
    now = _now_text()
    opened = _iso_date(fields.get('opened_on')) or now[:10]
    title = (fields.get('title') or fields.get('description') or fields.get('client_name') or 'Pump work').strip()
    vals = {k: (fields.get(k) or '') for k in CASE_TEXT_FIELDS}
    vals.update({k: _money(fields.get(k)) for k in CASE_MONEY_FIELDS})
    vals.update(title=title[:160], category=category, opened_on=opened)
    # Repairs at an account someone else looks after (SiteOne, Naples Electric,
    # our own technician) go to them, unless the job came with its vendor - a
    # Wettech document is Wettech's. Lake and SCADA work keep their vendor.
    if category in ('repair', 'install', 'inspection', 'other') and \
            (not vals['vendor'] or (vals['vendor'] == 'Wettech' and source in ('jobber', 'service_call'))):
        by = account_repairs_by(conn, {**fields, 'title': title})
        if by:
            vals['vendor'] = by
            if by == IN_HOUSE:
                steps.update({k: {'na': True} for k in IN_HOUSE_NA})
    jobber = fields.get('jobber') if isinstance(fields.get('jobber'), dict) else {}
    cols = list(vals.keys()) + ['jobber', 'steps', 'source', 'created_by', 'created_at', 'updated_at',
                                'last_activity_at']
    conn.execute(f"INSERT INTO pump_cases ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                 (*vals.values(), json.dumps(jobber), json.dumps(steps), source, actor, now, now, now))
    case_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    _refresh_case(conn, case_id)
    _event(conn, actor, 'created', title, case_id=case_id)
    return case_id


def update_case(conn, case_id, data, actor):
    row = conn.execute('SELECT * FROM pump_cases WHERE id=?', (case_id,)).fetchone()
    if not row:
        return False
    sets, vals, changed = [], [], []
    for k in CASE_TEXT_FIELDS:
        if k in data and data[k] is not None and str(data[k]) != str(row[k] or ''):
            v = str(data[k]).strip()
            if k == 'category' and v not in CATEGORIES:
                continue
            if k == 'opened_on':
                v = _iso_date(v) or row['opened_on']
            sets.append(f'{k}=?')
            vals.append(v)
            changed.append(k)
    for k in CASE_MONEY_FIELDS:
        if k in data:
            v = _money(data[k])
            if v != row[k]:
                sets.append(f'{k}=?')
                vals.append(v)
                changed.append(k)
    if 'jobber' in data and isinstance(data['jobber'], dict):
        j = json.loads(row['jobber'] or '{}')
        for kind, ref in data['jobber'].items():
            if kind in ('request', 'quote', 'job', 'invoice', 'client', 'property'):
                if ref:
                    j[kind] = {**(j.get(kind) or {}), **ref}
                else:
                    j.pop(kind, None)
        sets.append('jobber=?')
        vals.append(json.dumps(j))
        changed.append('jobber')
    if 'vendor_paid_on' in data:
        v = _iso_date(data['vendor_paid_on']) if data['vendor_paid_on'] else ''
        if data['vendor_paid_on'] and not v:
            raise ValueError('vendor_paid_on must be a date (YYYY-MM-DD), or empty for not paid')
        if v != (row['vendor_paid_on'] or ''):
            sets += ['vendor_paid_on=?', 'vendor_paid_by=?']
            vals += [v, actor if v else '']
            changed.append('vendor paid' if v else 'vendor not paid')
    if 'status' in data and data['status'] in ('open', 'cancelled') and data['status'] != row['status']:
        sets.append('status=?')
        vals.append(data['status'])
        changed.append('status')
    if sets:
        conn.execute(f"UPDATE pump_cases SET {', '.join(sets)}, updated_at=? WHERE id=?", (*vals, _now_text(), case_id))
    # Steps: {"scheduled": "2026-10-05"} done that day, "na" not needed,
    # "" / null not done.
    for k, v in (data.get('steps') or {}).items():
        if k not in STEP_KEYS:
            continue
        if v == 'na':
            _set_step(conn, case_id, k, by=actor, na=True)
        elif v in (None, '', False):
            _set_step(conn, case_id, k, by=actor, na=False)
        else:
            _set_step(conn, case_id, k, at=_iso_date(v) or _today().isoformat(), by=actor)
        changed.append(f'step:{k}')
    if 'assessment_due' in data:
        _set_assessment(conn, case_id, _iso_date(data['assessment_due']) or '', by=actor)
        changed.append('step:assessment')
    if 'category' in changed and not data.get('steps'):
        # Re-apply the default not-needed steps for the new kind of work,
        # leaving anything already done alone.
        steps = json.loads(conn.execute('SELECT steps FROM pump_cases WHERE id=?', (case_id,)).fetchone()[0] or '{}')
        steps = {k: v for k, v in steps.items() if v.get('at')}
        for k in NA_BY_CATEGORY.get(data['category'], []):
            steps.setdefault(k, {'na': True})
        conn.execute('UPDATE pump_cases SET steps=? WHERE id=?', (json.dumps(steps), case_id))
    _refresh_case(conn, case_id)
    _steps_from_amounts(conn, case_id, actor)
    if any(k in changed for k in ('vendor_quote_amount', 'vendor_quote_total', 'vendor_bill_amount',
                                  'vendor_bill_total')):
        _check_bill(conn, case_id, actor)
    if changed:
        _event(conn, actor, 'updated', ', '.join(changed), case_id=case_id)
    if data.get('note'):
        _event(conn, actor, 'note', str(data['note'])[:2000], case_id=case_id)
    return True


def _steps_from_amounts(conn, case_id, actor):
    """An amount typed in for the vendor's quote or bill means that step happened."""
    row = conn.execute('SELECT vendor_quote_amount, vendor_quote_total, vendor_bill_amount, vendor_bill_total, '
                       'steps FROM pump_cases WHERE id=?', (case_id,)).fetchone()
    steps = json.loads(row['steps'] or '{}')
    for key, a, t in (('vendor_quote', 'vendor_quote_amount', 'vendor_quote_total'),
                      ('vendor_bill', 'vendor_bill_amount', 'vendor_bill_total')):
        if (row[a] is not None or row[t] is not None) and not (steps.get(key) or {}).get('at'):
            _set_step(conn, case_id, key, at=_today().isoformat(), by=actor)


def open_issue(conn, case_id, kind, message, doc_id=None):
    """One open issue per (item, kind): a repeat refreshes the message."""
    row = conn.execute('SELECT id FROM pump_issues WHERE case_id=? AND kind=? AND resolved_at IS NULL',
                       (case_id, kind)).fetchone()
    if row:
        conn.execute('UPDATE pump_issues SET message=?, doc_id=COALESCE(?, doc_id) WHERE id=?',
                     (message, doc_id, row['id']))
        return row['id']
    conn.execute('INSERT INTO pump_issues (case_id, doc_id, kind, message, opened_at) VALUES (?,?,?,?,?)',
                 (case_id, doc_id, kind, message, _now_text()))
    iid = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    _event(conn, 'system', 'issue', message, case_id=case_id, doc_id=doc_id)
    _notify('pump_issue', {'issue_id': iid, 'case_id': case_id, 'kind': kind, 'message': message})
    return iid


def resolve_issues(conn, case_id, kind, actor, resolution):
    conn.execute('''UPDATE pump_issues SET resolved_at=?, resolved_by=?, resolution=?
                    WHERE case_id=? AND kind=? AND resolved_at IS NULL''',
                 (_now_text(), actor, resolution, case_id, kind))


def _check_bill(conn, case_id, actor='system'):
    """Compare the bill with the quote; raise or clear the mismatch issue."""
    case = dict(conn.execute('SELECT * FROM pump_cases WHERE id=?', (case_id,)).fetchone())
    steps = json.loads(case['steps'] or '{}')
    cmp = compare_amounts(case)
    if cmp['state'] == 'no_bill':
        return cmp
    if cmp['state'] == 'match':
        resolve_issues(conn, case_id, 'amount_mismatch', 'system', 'Bill now matches the quote')
        resolve_issues(conn, case_id, 'no_quote', 'system', 'Quote now on file and matches')
        if not (steps.get('bill_checked') or {}).get('at'):
            _set_step(conn, case_id, 'bill_checked', at=_today().isoformat(), by='system')
            _event(conn, 'system', 'bill matches quote', f"${cmp['bill']:,.2f}", case_id=case_id)
    elif cmp['state'] in ('over', 'under'):
        # The client is invoiced what they approved; the difference is
        # between us and the vendor - a to-do, not a hold.
        word = 'more' if cmp['state'] == 'over' else 'less'
        name, email = _vendor_contact(case.get('vendor'))
        add_todo(conn, f"bill-check:{case_id}:{case.get('vendor_bill_number') or ''}",
                 f"Check with {name} - {case.get('vendor') or 'vendor'} bill doesn't match the quote "
                 f"({case.get('client_name') or case.get('title') or ''})",
                 f"Bill {('#' + case['vendor_bill_number'] + ' ') if case.get('vendor_bill_number') else ''}"
                 f"${cmp['bill']:,.2f} is ${abs(cmp['diff']):,.2f} {word} than their quote ${cmp['quote']:,.2f}. "
                 f"Our invoice is drafted at the quoted price. {email}", {'case_id': case_id})
        if not (steps.get('bill_checked') or {}).get('at'):
            _set_step(conn, case_id, 'bill_checked', at=_today().isoformat(), by='system (see the to-do)')
    elif cmp['state'] == 'no_quote' and not (steps.get('vendor_quote') or {}).get('na') \
            and not (steps.get('bill_checked') or {}).get('na'):
        open_issue(conn, case_id, 'no_quote',
                   f"{case.get('vendor') or 'The vendor'}'s invoice came before their quote - the quote usually "
                   'follows and is checked against the bill when it arrives. If no quote is coming (contract or '
                   'time-and-materials work), bill it +30% or mark the quote not needed.')
    return cmp


def list_cases(conn, status='open', month=None, q=''):
    sql, args = 'SELECT * FROM pump_cases WHERE 1=1', []
    if status in ('open', 'closed', 'cancelled'):
        sql += ' AND status=?'
        args.append(status)
    if month:
        sql += ' AND opened_on LIKE ?'
        try:
            args.append(datetime.strptime(month, '%B %Y').strftime('%Y-%m') + '%')
        except ValueError:
            args.append(month[:7] + '%')
    if q:
        # Names, PO, and every document number: the vendor's quote/bill/work
        # order, our Jobber quote/invoice, and any filed document's number.
        q = q.strip().lstrip('#')
        sql += (' AND (title LIKE ? OR client_name LIKE ? OR po_number LIKE ? OR site LIKE ? OR description LIKE ?'
                ' OR vendor_quote_number LIKE ? OR vendor_bill_number LIKE ? OR wo_number LIKE ?'
                ' OR sei_invoice_number LIKE ? OR jobber LIKE ?'
                ' OR id IN (SELECT case_id FROM pump_docs WHERE doc_number LIKE ? AND case_id IS NOT NULL))')
        args += [f'%{q}%'] * 9 + [f'%"number": "{q}%', f'%{q}%']
    sql += ' ORDER BY opened_on, id'
    return [_case_dict(r, conn) for r in conn.execute(sql, args).fetchall()]


def case_detail(conn, case_id):
    row = conn.execute('SELECT * FROM pump_cases WHERE id=?', (case_id,)).fetchone()
    if not row:
        return None
    d = _case_dict(row, conn)
    d['docs'] = [_doc_dict(r) for r in conn.execute('SELECT * FROM pump_docs WHERE case_id=? ORDER BY id', (case_id,))]
    d['issues'] = [dict(r) for r in conn.execute('SELECT * FROM pump_issues WHERE case_id=? ORDER BY id DESC', (case_id,))]
    d['events'] = [dict(r) for r in conn.execute(
        'SELECT * FROM pump_events WHERE case_id=? ORDER BY id DESC LIMIT 100', (case_id,))]
    d['jobber_items'] = [dict(r) for r in conn.execute(
        'SELECT * FROM pump_jobber_items WHERE case_id=? ORDER BY updated_at DESC', (case_id,))]
    d['schedule_email'] = _schedule_mailto(d)
    d['account'] = account_info(conn, d)
    return d


def account_info(conn, case):
    """The account a job is for and its notes from the account sheets
    (contacts, where invoices and quotes go), or None."""
    text = ' '.join(x for x in (case.get('client_name'), case.get('title'), case.get('site')) if x)
    name = match_account(text, conn)
    if not name:
        return None
    notes = [r[0] for r in conn.execute("SELECT notes FROM pump_maint_accounts WHERE name=? AND notes != ''", (name,))]
    notes += [r[0] for r in conn.execute("SELECT diver_notes FROM pump_dive_sites WHERE name=? AND diver_notes != ''",
                                         (name,))]
    by = conn.execute("SELECT repairs_by FROM pump_maint_accounts WHERE name=?", (name,)).fetchone()
    return {'name': name, 'notes': '\n'.join(dict.fromkeys(n.strip() for n in notes if n.strip())),
            'repairs_by': (by[0] or '') if by else ''}


def _schedule_mailto(case):
    """A ready-to-send email to the vendor asking them to schedule the work.
    It only opens in the user's mail program - nothing is sent from here."""
    from urllib.parse import quote
    vendor = case.get('vendor') or 'Wettech'
    subject = f"Please schedule: {case.get('client_name') or case.get('title')}" + \
              (f" - PO {case['po_number']}" if case.get('po_number') else '')
    body = '\n'.join(x for x in [
        f"Hi {vendor},", '',
        'Please schedule the following work and let us know the date:', '',
        f"Customer: {case.get('client_name') or ''}",
        f"Location: {case.get('site') or ''}" if case.get('site') else '',
        f"PO: {case.get('po_number')}" if case.get('po_number') else '',
        f"Your quote: #{case.get('vendor_quote_number')}" if case.get('vendor_quote_number') else '',
        f"Work: {case.get('description') or case.get('title') or ''}", '',
        'Thank you,', 'Stahlman-England Irrigation'] if x is not None)
    return f"mailto:{_vendor_email(vendor)}?subject={quote(subject)}&body={quote(body)}"


# ═════════════════════════════════════════════════════════════════════════════
# documents
# ═════════════════════════════════════════════════════════════════════════════

def _doc_dict(row):
    d = dict(row)
    for k in ('line_items', 'branded_info', 'report_fields', 'jobber'):
        try:
            d[k] = json.loads(d.get(k) or ('[]' if k == 'line_items' else '{}'))
        except (TypeError, ValueError):
            d[k] = [] if k == 'line_items' else {}
    d['has_branded'] = bool(d.get('branded_path'))
    d.pop('file_path', None)
    d.pop('branded_path', None)
    return d


def _files_dir():
    path = os.path.join(CFG['data_dir'], 'pump_files')
    os.makedirs(path, exist_ok=True)
    return path


def _safe_name(name):
    name = os.path.basename(name or 'file')
    return re.sub(r'[^\w.\- ]+', '_', name)[:120] or 'file'


def _store_file(data, filename):
    sha = hashlib.sha256(data).hexdigest()
    sub = os.path.join(_files_dir(), _now().strftime('%Y-%m'))
    os.makedirs(sub, exist_ok=True)
    path = os.path.join(sub, f'{sha[:16]}_{_safe_name(filename)}')
    if not os.path.exists(path):
        with open(path, 'wb') as f:
            f.write(data)
    return path, sha


def extract_text(filename, data):
    """Plain text from a PDF or Word file ('' when there is none)."""
    low = (filename or '').lower()
    try:
        if low.endswith('.pdf'):
            import pdfplumber
            out = []
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                for page in pdf.pages:
                    out.append(page.extract_text() or '')
            return '\n'.join(out)
        if low.endswith('.docx'):
            from docx import Document
            from docx.oxml.ns import qn
            doc = Document(io.BytesIO(data))
            # Letterheads live in page headers and text boxes (Wettech's
            # address and email are there): read those first.
            out = []
            for sec in doc.sections:
                parts = [sec.header] + ([sec.first_page_header] if sec.different_first_page_header_footer else [])
                for part in parts:
                    try:
                        lines = [p.text for p in part.paragraphs]
                        for t in part.tables:
                            lines += [' | '.join(dict.fromkeys(c.text for c in r.cells)) for r in t.rows]
                    except Exception:
                        continue
                    out += [l for l in lines if l.strip() and l not in out]
            for box in doc.element.body.iter(qn('w:txbxContent')):
                for p in box.iter(qn('w:p')):
                    line = ''.join(t.text or '' for t in p.iter(qn('w:t'))).strip()
                    if line and line not in out:
                        out.append(line)
            out += [p.text for p in doc.paragraphs]
            for t in doc.tables:
                for r in t.rows:
                    cells = []
                    for c in r.cells:
                        if c.text not in cells:
                            cells.append(c.text)
                    out.append(' | '.join(cells))
            return '\n'.join(out)
    except Exception as e:
        print(f'  ⚠ Pumps: could not read {filename}: {e}')
    return ''


def _is_report(filename, text):
    low = (filename or '').lower()
    head = (text or '')[:1500].upper()
    return bool(re.search(r'\b(MAINTENANCE|PUMP|SYSTEM|SERVICE|FOUNTAIN|INSPECTION|STATION)\s+(\w+\s+)?REPORT\b', head)) \
        or ('report' in low and low.endswith(('.docx', '.doc')))


# ── reading quotes and bills ─────────────────────────────────────────────────

_NUM = {'anyOf': [{'type': 'number'}, {'type': 'null'}]}
EXTRACT_SCHEMA = {
    'type': 'object',
    'properties': {
        'kind': {'type': 'string', 'enum': ['quote', 'bill', 'report', 'other']},
        'vendor': {'type': 'string'},
        'doc_number': {'type': 'string'},
        'doc_date': {'type': 'string'},
        'po_number': {'type': 'string'},
        'ordered_by': {'type': 'string'},
        'wo_number': {'type': 'string'},
        'quote_reference': {'type': 'string'},
        'client_name': {'type': 'string'},
        'site': {'type': 'string'},
        'category': {'type': 'string', 'enum': list(CATEGORIES)},
        'description': {'type': 'string'},
        'line_items': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'description': {'type': 'string'},
                'quantity': _NUM,
                'unit_price': _NUM,
                'amount': _NUM,
                'taxable': {'type': 'boolean'},
                'is_tax': {'type': 'boolean'},
            },
            'required': ['name', 'description', 'quantity', 'unit_price', 'amount', 'taxable', 'is_tax'],
            'additionalProperties': False}},
        'subtotal': _NUM,
        'tax': _NUM,
        'total': _NUM,
        'tax_included': {'type': 'boolean'},
        'proposal_title': {'type': 'string'},
        'notes': {'type': 'string'},
    },
    'required': ['kind', 'vendor', 'doc_number', 'doc_date', 'po_number', 'ordered_by', 'wo_number',
                 'quote_reference', 'client_name', 'site', 'category', 'description', 'line_items', 'subtotal',
                 'tax', 'total', 'tax_included', 'proposal_title', 'notes'],
    'additionalProperties': False,
}

EXTRACT_PROMPT = """You read documents that arrive in the purchasing mailbox of Stahlman-England Irrigation, a
landscape irrigation company in Naples, Florida. Pump work for our clients is subcontracted, mostly to
Wettech (Water Equipment Technologies of Southwest Florida). Stahlman-England is the customer on these
documents; the client community or property the work is for usually appears as the job, site or first
description line (e.g. "Reserve at Estero - Lee County").

Classify the document and pull out its fields:
- kind: "quote" for a quote/quotation/estimate/proposal, "bill" for an invoice/bill, "report" for a service or
  maintenance report, "other" otherwise.
- vendor: the company that issued it (short name, e.g. "Wettech").
- doc_number: the quote or invoice number.
- doc_date: YYYY-MM-DD, or "".
- po_number: our PO number only when the P.O. field holds a number or code (e.g. "PO322", "0322"). If the P.O.
  field holds a person's name, leave po_number "" and put the name in ordered_by.
  Payment terms (e.g. "1.5% Finance Chrg over 30 days", "Net 30") are never a PO number.
- wo_number: the vendor's work order (W/O) number, or "".
- quote_reference: the vendor quote number a bill refers to, or "".
- client_name: the client/community the work is for (not Stahlman-England) - on Wettech's letter-style quotes
  it is the "RE:" line (e.g. "RE: The Carlise" -> "The Carlise"). site: the pump, station or area
  if named separately (e.g. "Pump #2", "Fountain", "South pump station"), else "".
- category: repair, maintenance (routine/contract visit), install (new pump/equipment), diver, filter, scada,
  inspection, or other.
- description: one or two plain sentences on the work.
- line_items: every priced line, in order, as written. name is a short label (under 60 characters) and
  description the full text of the line. Set is_tax true for sales-tax lines and taxable true where the line
  is marked taxable (e.g. a trailing "T") or tax is charged on it. Use null for numbers that are not shown.
  A quote written as a letter with a single price (e.g. "Your Cost ------ $1158.99") is one line item: name a
  short label for the work, description the work paragraph, quantity 1, unit_price and amount the price.
  The descriptions go to our client, so correct obvious typing mistakes in them (e.g. "check out well nor
  pumping" -> "check out well not pumping", "teh" -> "the") - never change the meaning, sizes, models or numbers.
- subtotal (before tax), tax, total: as printed; null when not shown.
- tax_included: true when the document says its price already includes sales tax (e.g. "Price includes Sales
  tax and freight"). Then put that price in total, leave subtotal and tax null, and set taxable false on its
  lines. Otherwise false.
- proposal_title: for a quote, a short title for our proposal to the client, starting "Proposal to" and naming
  the main work (e.g. "Proposal to inspect suction line", "Proposal to replace pump motor"). "" otherwise.
- notes: anything a person checking this against a quote should know ("as per quotation", exclusions, etc).
Use "" for text you cannot find. Never invent numbers."""


def _claude_extract(text, sender='', subject='', filename=''):
    if not USE_CLAUDE:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    # Pump quotes and bills run one to a few pages; this cap only guards
    # against something enormous landing in the mailbox.
    body = text if len(text) <= 60000 else text[:60000]
    content = (f"EMAIL FROM: {sender}\nEMAIL SUBJECT: {subject}\nFILE: {filename}\n\n"
               f"DOCUMENT TEXT:\n{body}")
    try:
        resp = client.beta.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=16000,
            betas=['server-side-fallback-2026-07-01'],
            fallbacks='default',
            system=EXTRACT_PROMPT,
            output_config={'effort': 'medium', 'format': {'type': 'json_schema', 'schema': EXTRACT_SCHEMA}},
            messages=[{'role': 'user', 'content': content}],
        )
    except anthropic.BadRequestError as e:
        print(f'  ⚠ Pumps: Claude rejected the request: {e.message}')
        _note_claude(f'Claude refused: {e.message}' if 'credit' not in str(e.message).lower() else
                     'the Anthropic account is out of credits')
        return None
    except anthropic.APIStatusError as e:
        print(f'  ⚠ Pumps: Claude error {e.status_code}')
        _note_claude(f'Claude error {e.status_code}')
        return None
    except anthropic.APIConnectionError:
        print('  ⚠ Pumps: could not reach Claude')
        _note_claude('could not reach Claude')
        return None
    if resp.stop_reason in ('refusal', 'max_tokens'):
        print(f'  ⚠ Pumps: Claude stopped early ({resp.stop_reason})')
        return None
    raw = next((b.text for b in resp.content if b.type == 'text'), '')
    _note_claude('')
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _note_claude(problem):
    """Remember why Claude last failed ('' once it works), for the page header."""
    try:
        if problem or (_state_get('claude_problem') or {}).get('problem'):
            _state_set('claude_problem', {'problem': problem, 'at': _now_text()})
    except Exception:
        pass


def _regex_extract(text, sender='', subject='', filename=''):
    """A rough reading for when Claude is unavailable, tuned to Wettech's
    invoice layout. Anything read this way is marked for review."""
    head = (text or '')[:600].lower()
    kind = 'other'
    if re.search(r'\binvoice\b', head):
        kind = 'bill'
    elif re.search(r'\b(quot(e|ation)|estimate|proposal)\b', head):
        kind = 'quote'
    elif re.search(r'\breport\b', head):
        kind = 'report'
    out = {'kind': kind, 'vendor': _vendor_display(f'{sender}\n{text}'), 'doc_number': '', 'doc_date': '',
           'po_number': '', 'ordered_by': '', 'wo_number': '', 'quote_reference': '', 'client_name': '', 'site': '',
           'category': 'repair', 'description': '', 'line_items': [], 'subtotal': None, 'tax': None, 'total': None,
           'notes': ''}
    m = re.search(r'(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{3,})\b', text)
    if m:
        out['doc_date'], out['doc_number'] = _iso_date(m.group(1)), m.group(2)
    else:
        m = re.search(r'(?:invoice|quote|estimate|proposal)\s*(?:#|no\.?|number)\s*:?\s*([A-Z0-9\-]{3,})', text, re.I)
        if m:
            out['doc_number'] = m.group(1)
    m = re.search(r'\bTotal\b\s*\$?\s*([\d,]+\.\d{2})', text)
    if m:
        out['total'] = _money(m.group(1))
    m = re.search(r'W/?O\s*(?:No\.?|#)\s*:?\s*(\w+)', text, re.I)
    if m:
        out['wo_number'] = m.group(1)
    m = re.search(r'(?:\bP\.\s?O\.|\bPO\b)\s*(?:No\.?|#|Number)?[^\n]*\n\s*([^\n]+)', text)
    if m:
        val = m.group(1).strip().split('  ')[0].strip()
        if re.search(r'\d', val):
            out['po_number'] = val[:20]
        elif re.match(r'^[A-Za-z][A-Za-z .\'-]{1,30}$', val):
            out['ordered_by'] = val
    lines = text.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if re.search(r'description', l, re.I) and re.search(r'amount', l, re.I))
    except StopIteration:
        start = -1
    items, current = [], None
    for l in lines[start + 1:] if start >= 0 else []:
        s = l.strip()
        if not s:
            continue
        if re.match(r'^(total|w/?o|we accept|balance|payments)', s, re.I):
            break
        tax = re.match(r'^sales\s+tax.*?([\d,]+\.\d{2})\s*$', s, re.I)
        if tax:
            out['tax'] = _money(tax.group(1))
            current = None
            continue
        m = re.match(r'^(?:(\d+(?:\.\d+)?)\s+)?(.+?)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})(T?)\s*$', s)
        if m:
            current = {'name': '', 'description': m.group(2).strip(), 'quantity': float(m.group(1) or 1),
                       'unit_price': _money(m.group(3)), 'amount': _money(m.group(4)),
                       'taxable': bool(m.group(5)), 'is_tax': False}
            items.append(current)
        elif current is not None:
            current['description'] += ' ' + s
        elif not out['client_name'] and not re.search(r'\d+\.\d{2}', s):
            out['client_name'] = s
    for it in items:
        it['name'] = short_name(it['description'])
    out['line_items'] = items
    if items:
        out['subtotal'] = round(sum(i['amount'] or 0 for i in items), 2)
        out['description'] = items[0]['description'][:300]
    elif out['total'] is not None and out['tax'] is not None:
        out['subtotal'] = round(out['total'] - out['tax'], 2)
    if re.search(r'as per quot', text, re.I):
        out['notes'] = 'Bill says "as per quotation".'
    _letter_quote(text, out)
    # "Reserve at Estero - Lee County" names the county for tax: drop it.
    out['client_name'] = re.sub(r'\s*[-–]\s*(Lee|Collier|Charlotte|Sarasota|Hendry|Manatee)\s+County\s*$', '',
                                out['client_name'] or '', flags=re.I)
    if re.match(r'\s*gulf\s*shore', out['vendor'] or '', re.I):
        _gulfshore_fields(text, subject, filename, out)
    return out


def site_account(label, conn=None):
    """The account a site label means: one the label names in full, else the one
    account whose name holds the label ("Rosewood" -> "Rosewood HOA", "Magnolia
    Falls" -> "Magnolia Falls @ Falling Waters"). None when it's not one, or
    several could be."""
    own = conn is None
    conn = conn or _conn()
    try:
        names = _account_names(conn)
        names += [a['name'] for a in accounts(conn) if a['name'] not in names]
        hit = match_account(label, conn, names)
        if hit:
            return hit
        if len(label.strip()) < 4:
            return None
        cands = {n for n in names if fuzzy_has(label.strip(), _core_name(n))}
        if len({_core_name(n).lower() for n in cands}) == 1:
            return min(cands, key=len)
        return None
    finally:
        if own:
            conn.close()


_US_DATE = re.compile(r'\b(\d{1,2}/\d{1,2}/\d{2,4})\b')


def _gulfshore_fields(text, subject, filename, out, conn=None):
    """Jordan's QuickBooks invoices (Gulfshore Yacht Service), read by code: the
    number from the file name ("Invoice_2498_from_...") - it isn't in the
    text - the day of the cleaning on the line, the line itself, and the site:
    Jordan's "Rosewood." at the start of the description, the line above "Bill
    to" ("Caymas"), or the Bill to line when it isn't us ("Rosewood, Falling
    Waters" twice, Bill to and Ship to). Never the wrapped note ("condition and
    seems to be functioning", #2498, Oct 2026). The account it names when there
    is one; a site it can't find is left blank."""
    m = (re.search(r'invoice[_\s#:no.]*?(\d{3,})', filename or '', re.I)
         or re.search(r'invoice\s*(?:#|no\.?|number)\s*:?\s*(\d{3,})', f'{subject or ""}\n{text}', re.I))
    if m:
        out['doc_number'] = m.group(1)
    lines = [l.strip() for l in (text or '').splitlines()]
    rows = [re.match(r'^\d+\.\s+(?:(\d{1,2}/\d{1,2}/\d{2,4})\s+)?(.+?)\s+(\d+(?:\.\d+)?)\s+\$?([\d,]+\.\d{2})'
                     r'\s+\$?([\d,]+\.\d{2})\s*$', l) for l in lines]
    items, first = [], None
    for k, m in enumerate(rows):
        if not m:
            continue
        first = first or m
        desc = m.group(2)
        for n in range(k + 1, len(lines)):   # the note wraps onto the lines below
            l = lines[n]
            if not l or rows[n] or re.match(r'^(total|ways to pay|balance|amount due)\b', l, re.I):
                break
            desc += ' ' + l
        items.append({'name': short_name(desc), 'description': desc, 'quantity': float(m.group(3)),
                      'unit_price': _money(m.group(4)), 'amount': _money(m.group(5)), 'taxable': False, 'is_tax': False})
    if items:
        out['line_items'] = items
        out['description'] = items[0]['description'][:300]
    m = (first and first.group(1) and _US_DATE.search(first.group(1))) or \
        re.search(r'invoice\s+date\b\s*:?\s*' + _US_DATE.pattern, text, re.I) or _US_DATE.search(text)
    if m:
        out['doc_date'] = _iso_date(m.group(1)) or out.get('doc_date') or ''
    m = re.search(r'^\s*(?:total|balance\s+due|amount\s+due)\b\s*:?\s*\$?\s*([\d,]+\.\d{2})', text, re.I | re.M)
    if m:
        out['total'] = _money(m.group(1))
    if out.get('total') is not None:
        out['subtotal'] = out['total'] if not out.get('tax') else round(out['total'] - out['tax'], 2)
    # Where the site is named, Jordan's own label first.
    named = []
    if first and '.' in first.group(2):
        # "Filter cleaning Rosewood. Filter is ..." - his label ends with a full stop; with none
        # ("Filter cleaning Filter is in good ...", Ana's Place #2491) there's no label to take.
        lead = re.sub(r'^\s*(?:lake\s+)?filter\s+clean(?:ing|ed)?\s*', '', first.group(2).split('.')[0], flags=re.I).strip()
        if lead and len(lead.split()) <= 6 and not re.search(r'\bfilter\s+is\b|condition|functioning', lead, re.I):
            named.append(lead)
    k = next((n for n, l in enumerate(lines) if re.match(r'^bill\s+to\b', l, re.I)), None)
    if k is not None:
        above = lines[k - 1] if k else ''
        if above and not re.search(r'\d{5}|\S@\S|\.com\b|\(\d{3}\)|^invoice$', above, re.I):
            named.append(above)
        below = lines[k + 1] if k + 1 < len(lines) else ''
        half = below[:len(below) // 2].strip()
        if half and half == below[len(below) - len(half):].strip():
            below = half             # the Bill to and Ship to columns side by side
        if below and not re.search(r'stahlman', below, re.I):
            named.append(below)
    named = [n for n in named if len(n) >= 3]
    # As written, like Wettech's "RE:" line: which client it is, is the pump bills' matching (diver_client).
    out['client_name'] = (named[0] if named else '')[:120]
    out['site'] = next((n for n in named[1:] if n.lower() != out['client_name'].lower()), out.get('site') or '')[:120]
    return out


_MONTH_DATE = re.compile(r'\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},\s+\d{4})')


def _letter_quote(text, out):
    """Wettech's quotes are letters, not tables: "RE: The Carlise", a work
    paragraph after "We are pleased to quote you on the following services",
    one "Your Cost ---- $ 1158.99" and often "Price includes Sales tax"."""
    if out['total'] is None:
        m = re.search(r'(?:your|total)\s+(?:cost|price)\b[\s\-–—_.:]*\$\s*([\d,]+\.\d{2})', text, re.I)
        if m:
            out['total'] = _money(m.group(1))
    if not out['doc_date']:
        m = _MONTH_DATE.search(text[:2000])
        if m:
            out['doc_date'] = _iso_date(m.group(1).replace('.', '').replace('Sept ', 'Sep '))
    m = re.search(r'^\s*RE\s*:\s*(.+?)\s*$', text, re.I | re.M)
    if m:
        out['client_name'] = m.group(1)[:120]
    out['tax_included'] = bool(re.search(r'\b(?:price|cost)s?\s+(?:does\s+|do\s+)?includes?\s+(?:the\s+)?sales\s+tax', text, re.I))
    if out['line_items'] or out['total'] is None:
        return
    if _letter_options(text, out):
        return
    m = re.search(r'following\s+(?:services|work|items?)[^\n]*\n(.+?)\n\s*(?:your|total)\s+(?:cost|price)', text,
                  re.I | re.S)
    work = re.sub(r'\s+', ' ', m.group(1)).strip() if m else ''
    if work:
        out['description'] = work[:300]
    out['line_items'] = [{'name': short_name(work) or 'Pump service', 'description': work, 'quantity': 1.0,
                          'unit_price': out['total'], 'amount': out['total'],
                          'taxable': not out['tax_included'], 'is_tax': False}]


# "Your Cost ---- $ 5427.63", and an option's "Your Additional Cost ... $ 534.86"
# with its work on the same line (Homewood Suites, Oct 14 2026): group 1 is
# what's before the label, group 2 the price.
_COST_LINE = re.compile(r'^(.*?)\b(?:your|total)\s+(?:(?:additional|optional|extra|added)\s+)?(?:cost|price)\b'
                        r'[\s\-–—_.…:]*\$\s*([\d,]+\.\d{2}).*$', re.I | re.M)
_EXTRA_COST = re.compile(r'\b(?:additional|optional|extra|added)\s+(?:cost|price)\b', re.I)
_OPTIONAL_WORK = re.compile(r'^\s*(?:possibly|if\s+(?:still\s+)?needed|if\s+required|optional|option\b|alternate|'
                            r'alternative|additional(?:ly)?\s+if)', re.I)


def _letter_options(text, out):
    """A letter with several "Your Cost" lines (Huntington #6, Oct 2026): each
    is its own piece of work. One starting "Possibly needed", "If needed",
    "Option"... is optional - quoted, but not in the total. Returns True when
    it found more than one."""
    costs = list(_COST_LINE.finditer(text))
    if len(costs) < 2:
        return False
    start = re.search(r'following\s+(?:services|work|items?)[^\n]*\n', text, re.I)
    pos = start.end() if start else 0
    items = []
    for m in costs:
        work = re.sub(r'\s+', ' ', text[pos:m.start()] + ' ' + m.group(1)).strip()
        work = re.sub(r'\s*(?:[.…_\-–—]{2,}|…)\s*$', '', work)
        # "Item #1 ... Field service to ..." (Autumn Woods 2): the numbering is not the work.
        work = re.sub(r'^item\s*#?\s*\d+\s*[.…:\-–—]*\s*', '', work, flags=re.I)
        pos = m.end()
        amount = _money(m.group(2))
        if not work or amount is None:
            continue
        # "Optional ... replace all PVC pipe ... Your Additional Cost" - either says it.
        optional = bool(_OPTIONAL_WORK.match(work)) or bool(_EXTRA_COST.search(m.group(0)))
        if optional:
            work = re.sub(r'^(?:possibly|if\s+(?:still\s+)?needed|if\s+required|optional(?:ly)?|option\s*\d*)\s*'
                          r'(?:needed)?\s*[-–—:.…]+\s*', '', work, flags=re.I)
            work = work[:1].upper() + work[1:]
        items.append({'name': short_name(work) or 'Pump service', 'description': work, 'quantity': 1.0,
                      'unit_price': amount, 'amount': amount, 'taxable': not out['tax_included'], 'is_tax': False,
                      'own_price': True, **({'optional': True} if optional else {})})
    if len(items) < 2:
        return False
    required = [i for i in items if not i.get('optional')] or items[:1]
    for i in required:
        i.pop('optional', None)
    out['line_items'] = items
    out['total'] = round(sum(i['amount'] for i in required), 2)
    out['description'] = required[0]['description'][:300]
    opts = [i for i in items if i.get('optional')]
    if opts:
        out['notes'] = ((out.get('notes') or '') + ' ' + ' '.join(
            f"Optional (not in the total): {short_name(i['description'], 80)} - ${i['amount']:,.2f}." for i in opts)
        ).strip()
    return True


def _letter_prices(text, x):
    """After Claude (or anyone) read a vendor letter with several "Your Cost"
    lines (Lely, Huntington #6): one line per priced piece of work, the
    "possibly needed" ones optional - whatever the reader made of it."""
    if x.get('kind') not in ('quote', 'other') or len(_COST_LINE.findall(text or '')) < 2:
        return x
    out = {'tax_included': bool(x.get('tax_included')) or bool(re.search(
        r'\b(?:price|cost)s?\s+(?:does\s+|do\s+)?includes?\s+(?:the\s+)?sales\s+tax', text, re.I)), 'notes': ''}
    if not _letter_options(text, out):
        return x
    x = dict(x, line_items=out['line_items'], total=out['total'], description=out['description'])
    if out['tax_included']:
        x.update(tax_included=True, subtotal=None, tax=None)
    else:
        x.update(subtotal=out['total'], tax=None, total=None)
    notes = [n for n in re.split(r'(?<=\.)\s+', x.get('notes') or '') if not n.startswith('Optional (not in the total)')]
    x['notes'] = ' '.join(notes + ([out['notes']] if out['notes'] else [])).strip()
    return x


def _letter_parts(items):
    """The separately priced pieces of work on a vendor letter - "possibly
    needed" ones too: each is its own quote to the client (Oct 2026)."""
    return [i for i in items or [] if i.get('own_price') and not i.get('is_tax')]


def _letter_part(x, part):
    """One piece of work from a letter quoting several (Lely, Oct 2026): each
    is its own job and its own quote to the client - "possibly needed" work
    too (Huntington #6). x unchanged when the letter has only one price."""
    parts = _letter_parts(x.get('line_items'))
    if len(parts) < 2 or part >= len(parts):
        return x
    it = {k: v for k, v in parts[part].items() if k != 'optional'}
    if parts[part].get('optional'):
        it['description'] = 'If needed: ' + (it.get('description') or '')
    items = [it]
    tax_in = bool(x.get('tax_included')) or x.get('subtotal') is None
    return dict(x, line_items=items, description=(it.get('description') or '')[:300], tax=None,
                subtotal=None if tax_in else it['amount'], total=it['amount'] if tax_in else None)


def _merge_letter_copies(conn, doc, actor):
    """The letter doc split before Oct 9 2026 goes back to the whole letter:
    its "letter_parts" mark is dropped, and each copy made for another piece
    is dismissed with its job cancelled - unless something was made in Jobber
    from it, which the office sorts out. Returns a note for the summary."""
    dj = {k: v for k, v in (doc.get('jobber') or {}).items() if k != 'letter_parts'}
    conn.execute('UPDATE pump_docs SET jobber=? WHERE id=?', (json.dumps(dj), doc['id']))
    kept = []
    for r in conn.execute("SELECT * FROM pump_docs WHERE json_extract(jobber, '$.split_from')=? AND status != 'dismissed'",
                          (doc['id'],)).fetchall():
        cj = json.loads(r['jobber'] or '{}')
        case = conn.execute('SELECT * FROM pump_cases WHERE id=?', (r['case_id'],)).fetchone() if r['case_id'] else None
        kj = json.loads(case['jobber'] or '{}') if case else {}
        in_jobber = cj.get('quote_id') or any((kj.get(k) or {}).get('id') for k in ('job', 'quote', 'invoice'))
        if in_jobber:
            kept.append(f"job #{r['case_id']}" if r['case_id'] else f"document #{r['id']}")
            continue
        conn.execute("UPDATE pump_docs SET status='dismissed', updated_at=? WHERE id=?", (_now_text(), r['id']))
        if case and case['status'] != 'cancelled':
            conn.execute("UPDATE pump_cases SET status='cancelled', stage='cancelled', updated_at=? WHERE id=?",
                         (_now_text(), case['id']))
            conn.execute("UPDATE pump_issues SET resolved_at=?, resolved_by=?, resolution=? WHERE case_id=? AND "
                         "resolved_at IS NULL", (_now_text(), actor, 'Back on one quote', case['id']))
            _event(conn, actor, 'cancelled', f"{doc['file_name']} is one quote again - this work is a line on "
                                             f"job #{doc['case_id']}", case_id=case['id'])
    if kept:
        return (f"; the other work is still on {', '.join(kept)} (made in Jobber) - "
                f"cancel it there if this quote now covers it")
    return '; one quote again with a line for each piece of work'


# The office (Oct 9 2026): a letter quoting several pieces of work is ONE
# quote with a line for each piece; "possibly needed" work is an optional
# line on it (Autumn Woods 2: flow meter + surge arrestor, one quote).
# Splitting it into a job and quote per piece is off.
SPLIT_LETTERS = os.environ.get('PUMPS_SPLIT_LETTERS', 'false').lower() in ('1', 'true', 'yes', 'on')


def split_letter(doc_id, actor='system', full=None):
    """A vendor quote letter with several separately priced pieces of work
    becomes a job and a client quote for each: the document keeps the first,
    and each other piece gets its own copy of the document on a new job.
    Reading the letter again updates those copies instead of adding more.
    Returns the copies' doc ids. Off unless PUMPS_SPLIT_LETTERS is on."""
    if not SPLIT_LETTERS:
        return []
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
        if not row:
            return []
        doc = _doc_dict(row)
        j = doc.get('jobber') or {}
        if doc['kind'] != 'quote' or not doc.get('case_id') or j.get('split_from') or doc['status'] == 'dismissed':
            return []
        full = full or {k: doc.get(k) for k in ('line_items', 'subtotal', 'tax', 'total', 'description')}
        parts = _letter_parts(full.get('line_items'))
        if len(parts) < 2:
            return []
        first = _letter_part(full, 0)
        conn.execute('UPDATE pump_docs SET line_items=?, subtotal=?, tax=?, total=?, description=?, jobber=? WHERE id=?',
                     (json.dumps(first['line_items']), first['subtotal'], first['tax'], first['total'],
                      first['description'], json.dumps({**j, 'letter_parts': len(parts)}), doc_id))
        conn.execute('UPDATE pump_cases SET vendor_quote_amount=?, vendor_quote_total=? WHERE id=?',
                     (first['subtotal'], first['total'], doc['case_id']))
        cols = [r[1] for r in conn.execute('PRAGMA table_info(pump_docs)') if r[1] != 'id']
        ids = []
        for n in range(1, len(parts)):
            x = _letter_part(full, n)
            have = conn.execute("SELECT id FROM pump_docs WHERE json_extract(jobber, '$.split_from')=? "
                                "AND json_extract(jobber, '$.letter_part')=?", (doc_id, n)).fetchone()
            if have:
                conn.execute('UPDATE pump_docs SET line_items=?, subtotal=?, tax=?, total=?, description=?, '
                             'updated_at=? WHERE id=?', (json.dumps(x['line_items']), x['subtotal'], x['tax'],
                                                         x['total'], x['description'], _now_text(), have[0]))
                part_case = conn.execute('SELECT case_id FROM pump_docs WHERE id=?', (have[0],)).fetchone()[0]
                if not part_case or conn.execute("SELECT 1 FROM pump_cases WHERE id=? AND status='cancelled'",
                                                 (part_case,)).fetchone():
                    # Its item was cancelled (or it has none): a new item for this
                    # piece, without the cancelled item's Jobber quote.
                    pj = json.loads(conn.execute('SELECT jobber FROM pump_docs WHERE id=?', (have[0],)).fetchone()[0]
                                    or '{}')
                    pj = {k: v for k, v in pj.items() if not k.startswith('quote_')}
                    conn.execute("UPDATE pump_docs SET case_id=NULL, status='new', jobber=? WHERE id=?",
                                 (json.dumps(pj), have[0]))
                    pdoc = dict(conn.execute('SELECT * FROM pump_docs WHERE id=?', (have[0],)).fetchone())
                    part_case = _new_case_for(conn, pdoc, actor)
                    conn.execute("UPDATE pump_docs SET case_id=?, status='filed' WHERE id=?", (part_case, have[0]))
                    _file_on_case(conn, pdoc, part_case, 'split from a letter', actor)
                    _event(conn, actor, 'split', f"{doc['file_name']} also quotes other work at its own price - "
                                                 f"made job #{part_case} for it", case_id=doc['case_id'], doc_id=doc_id)
                if part_case:
                    conn.execute('UPDATE pump_cases SET vendor_quote_amount=?, vendor_quote_total=? WHERE id=?',
                                 (x['subtotal'], x['total'], part_case))
                _unhide_doc(conn, have[0])
                ids.append(have[0])
                continue
            new = {c: row[c] for c in cols}
            new.update(line_items=json.dumps(x['line_items']), subtotal=x['subtotal'], tax=x['tax'],
                       total=x['total'], description=x['description'], case_id=None, status='new',
                       file_sha=None, created_at=_now_text(), updated_at=_now_text(),
                       jobber=json.dumps({'split_from': doc_id, 'letter_part': n}))
            if new.get('doc_number'):
                new['doc_number'] = f"{new['doc_number']}-{n + 1}"
            new = {k: v for k, v in new.items() if k in cols}
            cur = conn.execute(f"INSERT INTO pump_docs ({', '.join(new)}) VALUES ({', '.join('?' for _ in new)})",
                               tuple(new.values()))
            pid = cur.lastrowid
            pdoc = dict(conn.execute('SELECT * FROM pump_docs WHERE id=?', (pid,)).fetchone())
            cid = _new_case_for(conn, pdoc, actor)
            conn.execute("UPDATE pump_docs SET case_id=?, status='filed' WHERE id=?", (cid, pid))
            _file_on_case(conn, pdoc, cid, 'split from a letter', actor)
            _event(conn, actor, 'split', f"Quote letter {doc['file_name']} prices {len(parts)} pieces of work "
                                         f"separately - this one is its own job and quote", case_id=cid, doc_id=pid)
            _event(conn, actor, 'split', f"{doc['file_name']} also quotes other work at its own price - "
                                         f"made job #{cid} for it", case_id=doc['case_id'], doc_id=doc_id)
            ids.append(pid)
        conn.commit()
        return ids
    finally:
        conn.close()


def _quote_each_part(doc_ids, actor):
    """Draft (or redo, while still a draft) the client quote for each copy."""
    out = []
    for pid in doc_ids:
        conn = _conn()
        try:
            r = conn.execute('SELECT jobber FROM pump_docs WHERE id=?', (pid,)).fetchone()
        finally:
            conn.close()
        j = json.loads((r and r[0]) or '{}')
        out.append(update_draft_quote(pid, actor) if j.get('quote_id') else auto_draft_quote(pid))
    return out


def short_name(text, limit=60):
    """First clause of a line item, cut on a word boundary."""
    first = re.split(r'[,.;]\s', (text or '').strip() + ' ')[0].strip()
    if len(first) <= limit:
        return first
    cut = first[:limit].rsplit(' ', 1)[0]
    return cut.rstrip(' -,') or first[:limit]


# Wettech's invoice puts its payment terms ("1.5% Finance Chrg over 30 days")
# next to the P.O. box (Oct 2026): that's not a PO number.
_NOT_A_PO = re.compile(r'%|finance|charge|chrg|\bterms?\b|\bnet\s*\d|\bdue\b|\bdays?\b|receipt|\binterest\b', re.I)


def clean_po(value):
    """The PO number, or '' when what was read is the payment terms or other text."""
    value = (value or '').strip()
    return '' if not value or _NOT_A_PO.search(value) else value


def _clean_extraction(x):
    x = dict(x or {})
    x['kind'] = x.get('kind') if x.get('kind') in ('quote', 'bill', 'report', 'other') else 'other'
    x['po_number'] = clean_po(x.get('po_number'))
    x['doc_date'] = _iso_date(x.get('doc_date'))
    for k in ('subtotal', 'tax', 'total'):
        x[k] = _money(x.get(k))
    items = []
    for it in x.get('line_items') or []:
        if not isinstance(it, dict):
            continue
        it = dict(it)
        for k in ('quantity', 'unit_price', 'amount'):
            it[k] = _money(it.get(k)) if k != 'quantity' else (float(it.get(k)) if it.get(k) not in (None, '') else None)
        desc = (it.get('description') or it.get('name') or '').strip()
        it['is_tax'] = bool(it.get('is_tax')) or bool(re.match(r'^\s*(sales\s+)?tax\b', desc, re.I))
        items.append(it)
    x['line_items'] = items
    if x.get('tax_included'):
        # The price already carries the vendor's sales tax: it is the total,
        # and our client quote/invoice must not add tax on top of it.
        for it in items:
            it['taxable'] = False
        if x['total'] is None and len([i for i in items if not i.get('optional')]) == 1 and \
                [i for i in items if not i.get('optional')][0].get('amount') is not None:
            x['total'] = [i for i in items if not i.get('optional')][0]['amount']
        if x['subtotal'] is not None and x['tax'] is None and x['total'] is None:
            x['total'], x['subtotal'] = x['subtotal'], None
        if x['tax'] is None:
            x['subtotal'] = None
        if 'includes sales tax' not in (x.get('notes') or '').lower():
            x['notes'] = ((x.get('notes') or '') + ' Price includes sales tax.').strip()
    elif x['subtotal'] is None:
        priced = [i['amount'] for i in items if not i['is_tax'] and not i.get('optional') and i.get('amount') is not None]
        if priced:
            x['subtotal'] = round(sum(priced), 2)
        elif x['total'] is not None and x['tax'] is not None:
            x['subtotal'] = round(x['total'] - x['tax'], 2)
    if x['tax'] is None:
        taxes = [i['amount'] for i in items if i['is_tax'] and i.get('amount') is not None]
        if taxes:
            x['tax'] = round(sum(taxes), 2)
    if x.get('client_name'):
        x['client_name'] = re.sub(r'\s*[-–]\s*(Lee|Collier|Charlotte|Sarasota|Hendry|Manatee)\s+County\s*$', '',
                                  x['client_name'], flags=re.I).strip()
    x['category'] = x.get('category') if x.get('category') in CATEGORIES else 'repair'
    return x


# ── filing a document against an item ────────────────────────────────────────

def _station_nums(text):
    """Pump station numbers in a text: "pump station #6", "#6 pump station", "Huntington #6" -> {'6'}."""
    return {m.group(1) or m.group(2) for m in re.finditer(
        r'#\s*(\d{1,2})\b|\b(?:pump|ps|station)\s*(?:station\s*)?(?:no\.?\s*|#\s*)?(\d{1,2})\b', text or '', re.I)}


def _bill_by_quote_or_station(doc, rows):
    """A vendor bill's item when its name alone doesn't say (Huntington Lakes #29218, Oct 2026:
    "Huntington Lakes" vs the item "Huntington #6 - Check out #6 pump station", with #3 and #5
    open too): one item at the same site, still waiting on its bill, whose vendor quote is the
    bill's amount - or, failing that, the one for the same pump station. (id, how) or None."""
    site = name_tokens(doc.get('client_name'))
    if not site:
        return None
    lines = doc.get('line_items') or []
    if isinstance(lines, str):
        try:
            lines = json.loads(lines)
        except ValueError:
            lines = []
    text = ' '.join(str(doc.get(k) or '') for k in ('client_name', 'description')) + ' ' + ' '.join(
        f"{i.get('name') or ''} {i.get('description') or ''}" for i in lines if isinstance(i, dict))
    cands = []
    for r in rows:
        steps = json.loads(r.get('steps') or '{}')
        if (steps.get('vendor_bill') or {}).get('at') or r.get('category') in ('maintenance', 'inspection', 'diver'):
            continue
        # The site's most telling word ("huntington", not "lakes") is the item's.
        if max(sorted(site), key=len) in name_tokens(f"{r.get('client_name') or ''} {r.get('title') or ''} {r.get('site') or ''}"):
            cands.append(r)
    amounts = [a for a in (doc.get('total'), doc.get('subtotal')) if a is not None]
    same = [r for r in cands if any(q is not None and abs(q - a) <= 1 for q in (r.get('vendor_quote_total'),
                                                                                  r.get('vendor_quote_amount'))
                                    for a in amounts)]
    if len(same) == 1:
        return same[0]['id'], f"its quote's amount ({same[0].get('title') or same[0].get('client_name')})"
    nums = _station_nums(text)
    if len(nums) == 1:
        same = [r for r in cands if _station_nums(f"{r.get('client_name') or ''} {r.get('title') or ''} "
                                                   f"{r.get('site') or ''}") == nums]
        if len(same) == 1:
            return same[0]['id'], f"pump station #{next(iter(nums))} ({same[0].get('title') or same[0].get('client_name')})"
    return None


def _recent_unbilled(conn, exclude=None):
    """Jobs closed or cancelled in the last REOPEN_DAYS days that never got their vendor bill."""
    since = (_today() - timedelta(days=REOPEN_DAYS)).isoformat()
    return [dict(r) for r in conn.execute("SELECT * FROM pump_cases WHERE status IN ('closed', 'cancelled') "
                                          "AND COALESCE(updated_at, '') >= ?", (since,))
            if r['id'] != exclude and not (json.loads(r['steps'] or '{}').get('vendor_bill') or {}).get('at')]


def merge_billed_duplicates(conn, actor='Pumps'):
    """A bill's own item, already invoiced from (Huntington #5, Oct 2026: #29219 on an item of its own, our
    invoice #36888 drafted from it, while "Huntington #5 - Check out #5 pump station" - quote #9149, job
    #14584 - sat on "Waiting on Wettech to do the work"): the bill, our invoice and the steps they ticked
    go onto that job, and the bill's item is cancelled as merged. Only when exactly one job fits."""
    merged = []
    since = (_today() - timedelta(days=REOPEN_DAYS)).isoformat()
    for dup in conn.execute("SELECT * FROM pump_cases WHERE status IN ('open', 'closed') AND COALESCE(updated_at, '') >= ? "
                            "AND source NOT IN ('manual', 'jobber', 'service_call')", (since,)).fetchall():
        dj = json.loads(dup['jobber'] or '{}')
        if not (dj.get('invoice') or {}).get('id') or any((dj.get(k) or {}).get('id') for k in ('quote', 'job')):
            continue
        bill = conn.execute("SELECT * FROM pump_docs WHERE case_id=? AND kind='bill' AND status != 'dismissed' "
                            "ORDER BY id DESC", (dup['id'],)).fetchone()
        if not bill:
            continue
        rows = [dict(r) for r in conn.execute("SELECT * FROM pump_cases WHERE status='open' AND id != ? "
                                              "AND source != 'bill'", (dup['id'],))
                if any((json.loads(r['jobber'] or '{}').get(k) or {}).get('id') for k in ('quote', 'job'))]
        hit = _bill_by_quote_or_station(_doc_dict(bill), rows)
        if not hit:
            continue
        job = hit[0]
        jrow = conn.execute('SELECT * FROM pump_cases WHERE id=?', (job,)).fetchone()
        jj = json.loads(jrow['jobber'] or '{}')
        jj['invoice'] = dj['invoice']
        if dj.get('client') and not jj.get('client'):
            jj['client'] = dj['client']
        conn.execute('''UPDATE pump_cases SET jobber=?, sei_invoice_number=COALESCE(NULLIF(?, ''), sei_invoice_number),
                          vendor_bill_number=?, vendor_bill_amount=?, vendor_bill_total=?,
                          vendor_paid_on=COALESCE(NULLIF(vendor_paid_on, ''), ?), updated_at=? WHERE id=?''',
                     (json.dumps(jj), dup['sei_invoice_number'] or '', dup['vendor_bill_number'] or '',
                      dup['vendor_bill_amount'], dup['vendor_bill_total'], dup['vendor_paid_on'] or '', _now_text(), job))
        conn.execute('UPDATE pump_docs SET case_id=?, updated_at=? WHERE case_id=? AND status != \'dismissed\'',
                     (job, _now_text(), dup['id']))
        conn.execute('UPDATE pump_jobber_items SET case_id=? WHERE case_id=?', (job, dup['id']))
        steps = json.loads(dup['steps'] or '{}')
        for k in ('work_done', 'vendor_bill', 'bill_checked', 'invoice_drafted', 'closed'):
            if (steps.get(k) or {}).get('at'):
                _set_step(conn, job, k, at=steps[k]['at'], by=actor)
        conn.execute("UPDATE pump_cases SET status='cancelled', stage='cancelled', updated_at=? WHERE id=?",
                     (_now_text(), dup['id']))
        conn.execute("UPDATE pump_issues SET resolved_at=?, resolved_by=?, resolution=? WHERE case_id=? "
                     "AND resolved_at IS NULL", (_now_text(), actor, f'Merged into item #{job}', dup['id']))
        conn.execute("UPDATE pump_todos SET done_at=?, done_by=? WHERE done_at IS NULL AND key LIKE ?",
                     (_now_text(), actor, f'%:{dup["id"]}'))
        num = (dj.get('invoice') or {}).get('number') or dup['sei_invoice_number'] or ''
        _event(conn, actor, 'merged', f"Bill #{bill['doc_number'] or '?'} and our invoice #{num} are item #{job}'s "
                                      f"({hit[1]}) - moved there", case_id=dup['id'])
        _event(conn, actor, 'merged', f"Bill #{bill['doc_number'] or '?'} and our invoice #{num} came from item "
                                      f"#{dup['id']} - moved here", case_id=job)
        merged.append((dup['id'], job))
    if merged:
        conn.commit()
    return merged


def move_early_bills(conn, actor='Pumps'):
    """A bill that made an item of its own as "came before its quote" when its job was open all
    along (Huntington #29218 -> "Huntington #6 - Check out #6 pump station", Oct 2026): moved to
    that job by its quote's amount or pump station, and the empty item cancelled."""
    moved = []
    for iss in conn.execute("SELECT DISTINCT case_id FROM pump_issues WHERE kind='no_quote' AND resolved_at IS NULL").fetchall():
        cid = iss[0]
        docs = conn.execute("SELECT * FROM pump_docs WHERE case_id=? AND status != 'dismissed'", (cid,)).fetchall()
        if len(docs) != 1 or docs[0]['kind'] != 'bill' or (_doc_dict(docs[0]).get('jobber') or {}).get('invoice_id'):
            continue
        case = conn.execute("SELECT * FROM pump_cases WHERE id=? AND status='open'", (cid,)).fetchone()
        if not case or json.loads(case['jobber'] or '{}').get('quote'):
            continue
        rows = [dict(r) for r in conn.execute("SELECT * FROM pump_cases WHERE status='open' AND id != ?", (cid,))]
        doc = _doc_dict(docs[0])
        if not _bill_by_quote_or_station(doc, rows) and not _bill_by_quote_or_station(doc, _recent_unbilled(conn, cid)):
            continue
        new = refile_document(conn, doc['id'], actor)
        if not conn.execute("SELECT 1 FROM pump_docs WHERE case_id=? AND status != 'dismissed'", (cid,)).fetchone():
            conn.execute("UPDATE pump_cases SET status='cancelled', stage='cancelled', updated_at=? WHERE id=?",
                         (_now_text(), cid))
            conn.execute("UPDATE pump_issues SET resolved_at=?, resolved_by=?, resolution=? WHERE case_id=? "
                         "AND resolved_at IS NULL", (_now_text(), actor, 'The bill went on its job', cid))
            _event(conn, actor, 'cancelled', "The bill was for a job already open - moved there", case_id=cid)
        moved.append((doc['id'], new))
    if moved:
        conn.commit()
    return moved


def _find_case_for(conn, doc, exclude=None):
    """Best open item for a document, with how it was matched; (None, '') if none."""
    po = po_key(doc.get('po_number'))
    rows = [dict(r) for r in conn.execute("SELECT * FROM pump_cases WHERE status='open'") if r['id'] != exclude]
    if po:
        hits = [r for r in rows if po_key(r.get('po_number')) == po]
        if len(hits) == 1:
            return hits[0]['id'], f'PO {po}'
    wo = (doc.get('wo_number') or '').strip()
    if wo:
        hits = [r for r in rows if (r.get('wo_number') or '').strip() == wo]
        if len(hits) == 1:
            return hits[0]['id'], f'W/O {wo}'
    qref = (doc.get('quote_ref') or '').strip()
    if qref:
        hits = [r for r in rows if (r.get('vendor_quote_number') or '').strip().lower() == qref.lower()]
        if len(hits) == 1:
            return hits[0]['id'], f'quote #{qref}'
    name = doc.get('client_name') or ''
    if not name:
        return None, ''
    kind = doc.get('kind')
    hit = _bill_by_quote_or_station(doc, rows) if kind == 'bill' and not maintenance_bill(doc) else None
    if hit:
        return hit
    if kind == 'bill' and not maintenance_bill(doc):
        # Closed or cancelled lately without its bill (Huntington #5, Oct 2026): reopened for it.
        hit = _bill_by_quote_or_station(doc, _recent_unbilled(conn, exclude))
        if hit:
            conn.execute("UPDATE pump_cases SET status='open', updated_at=? WHERE id=?", (_now_text(), hit[0]))
            _event(conn, 'Pumps', 'reopened', f"Its vendor bill came in ({doc.get('vendor') or 'vendor'} "
                                              f"#{doc.get('doc_number') or '?'})", case_id=hit[0])
            return hit[0], hit[1] + ' - reopened'
    # A maintenance visit's bill or report (Lely, Oct 2026: the quarterly bill
    # went on the 10" valve repair waiting on its quote) only goes on a
    # maintenance item by name - otherwise it gets its own.
    maint = kind == 'report' or (kind == 'bill' and maintenance_bill(doc))
    best, best_score = None, 0.0
    for r in rows:
        if maint and r.get('category') not in ('maintenance', 'inspection'):
            continue
        score = max(similarity(name, r.get('client_name') or r.get('title') or ''),
                    similarity(name, r.get('title') or ''))
        # "Magnolia Cove Pressure Transducer" (the work read into the name, Oct 2026)
        # is the job at "Magnolia Cove".
        cn = (r.get('client_name') or '').strip().lower()
        if len(cn) >= 6 and re.match(rf'{re.escape(cn)}\b', name.strip().lower()):
            score = max(score, 0.9)
        if score < 0.75:
            continue
        steps = json.loads(r.get('steps') or '{}')
        done = {k for k, v in steps.items() if v.get('at')}
        # Prefer the item at the right point in its checklist.
        if kind == 'quote' and 'vendor_quote' not in done:
            score += 0.2
        if kind == 'bill' and 'vendor_bill' not in done:
            score += 0.2 + (0.1 if 'vendor_quote' in done else 0)
        if kind == 'report' and 'report_logged' not in done and not (steps.get('report_logged') or {}).get('na'):
            score += 0.2
        if kind == 'bill' and 'vendor_bill' in done:
            score -= 0.5
        if kind == 'quote' and 'vendor_quote' in done:
            score -= 0.3
        if kind == 'quote' and (r.get('category') in ('maintenance', 'inspection') or 'work_done' in done):
            # Banyan Bay (Oct 2026): the quote for what the report found went on the report's own
            # maintenance visit (done, and the older item) instead of the item waiting on that quote.
            score -= 0.15
        if score > best_score:
            best, best_score = r, score
    if best and best_score >= 0.85:
        return best['id'], f"client name ({best.get('client_name') or best.get('title')})"
    return None, ''


# ── Gulfshore (Jordan, the diver): lake filter cleaning bills ────────────────
# Billed to the client with the pump service on the account's recurring job, so
# there's no quote and no invoice of their own: the bill is logged, and once our
# Jobber invoice to the client for that visit exists it's Christian's to pay. If
# it isn't billed out yet, the office is told (Magnolia Falls #2497, Oct 2026).

def is_diver_bill(doc):
    return (doc or {}).get('kind') == 'bill' and re.match(r'\s*gulf\s*shore', (doc or {}).get('vendor') or '', re.I) is not None


def diver_client(conn, doc):
    """(account, Jobber client id) for Jordan's site label, matched the way the pump
    bills are: the office's saved site names first ("Rosewood" -> the Rosewood
    HOA client), then the account the label names or is part of. The id is
    None when only the account is known; the invoice check looks the client up
    then, as for a pump bill."""
    names = _account_names(conn)
    names += [a['name'] for a in accounts(conn) if a['name'] not in names]
    alias = match_site_alias(doc, None, conn)
    if alias:
        acct = next((n for n in names if _same_account(n, alias['client_name'] or '')), None)
        return acct or alias['client_name'] or doc.get('client_name') or '', alias['client_id']
    # Jordan cleans lake filters: a lake account by his label first - "Falling Waters II", not the pump
    # account "Falling Waters II - Watercrest" (#2495, Oct 2026).
    lakes = [r[0] for r in conn.execute('SELECT name FROM pump_dive_sites')]
    norm = lambda x: ' '.join(re.findall(r'[a-z0-9]+', _core_name(x or '').lower()))
    for label in (doc.get('client_name'), doc.get('site')):
        hit = next((n for n in lakes if label and norm(n) == norm(label)), None)
        if hit:
            return hit, None
        # Spelled a letter off ("Ana's Place" for Anna's Place, #2491): the one lake that close.
        close = [n for n in lakes if label and difflib.SequenceMatcher(None, norm(n), norm(label)).ratio() >= 0.9]
        if len(close) == 1:
            return close[0], None
    for label in (doc.get('client_name'), doc.get('site')):
        acct = site_account(label, conn) if label else None
        if acct:
            return acct, None
    return doc.get('client_name') or '', None


def file_diver_bill(conn, doc, actor):
    """A Gulfshore bill on an item of its own: the visit done, nothing to quote or check."""
    client = doc.get('client_name') or ''
    acct, client_id = diver_client(conn, doc)
    num = f" #{doc['doc_number']}" if doc.get('doc_number') else ''
    when = doc.get('doc_date') or _today().isoformat()
    cid = create_case(conn, {'title': f"{acct or client or 'Lake'} - lake filter cleaning (Gulfshore{num})"[:160],
                             'category': 'diver', 'client_name': acct or client, 'site': doc.get('site') or '',
                             'vendor': 'Gulfshore', 'description': (doc.get('description') or '').strip()[:1000],
                             'opened_on': when}, actor, source='bill')
    if client_id:
        conn.execute('UPDATE pump_cases SET jobber_client_id=? WHERE id=?', (client_id, cid))
    conn.execute("UPDATE pump_docs SET case_id=?, status=CASE WHEN status='new' THEN 'filed' ELSE status END, "
                 "updated_at=? WHERE id=?", (cid, _now_text(), doc['id']))
    _apply(conn, cid, {'vendor_bill_number': doc.get('doc_number') or '', 'vendor_bill_amount': doc.get('subtotal'),
                       'vendor_bill_total': doc.get('total')})
    for k in ('assessment', 'vendor_quote', 'client_quote', 'client_approved', 'bill_checked', 'report_logged'):
        _set_step(conn, cid, k, by=actor, na=True)
    for k in ('scheduled', 'work_done', 'vendor_bill'):
        _set_step(conn, cid, k, at=when, by=actor)
    _event(conn, actor, 'bill filed', f"{doc.get('file_name')} - Gulfshore filter cleaning, billed with the pump service",
           case_id=cid, doc_id=doc['id'])
    return cid


def check_diver_billed(case_id, actor='Pumps'):
    """Has the client been invoiced for the Gulfshore visit? Our Jobber invoice to them
    from around the service date (the pump service, filter cleaning included):
    linked, and the bill is Christian's to pay. If not: a to-do saying it isn't billed out."""
    conn = _conn()
    try:
        case = conn.execute('SELECT * FROM pump_cases WHERE id=?', (case_id,)).fetchone()
        doc = conn.execute("SELECT * FROM pump_docs WHERE case_id=? AND kind='bill' AND status != 'dismissed' "
                           'ORDER BY id DESC', (case_id,)).fetchone()
        if not case or not doc:
            return None
        case, doc = dict(case), _doc_dict(doc)
        j = json.loads(case.get('jobber') or '{}')
        if (j.get('invoice') or {}).get('id'):
            return {'billed': True, 'invoice': j['invoice']}
        acct = next((a for a in accounts(conn) if a['name'] == case.get('client_name')), None) or {}
        client_id = case.get('jobber_client_id') or ((acct.get('pump') or {}).get('jobber_client_id'))
    finally:
        conn.close()
    found, err = None, ''
    if not (client_id or case.get('client_name') or doc.get('client_name')):
        pass                    # whose it is isn't known: the to-do asks
    elif jobber_status()['connected']:
        try:
            client_id = client_id or invoice_client(doc, case)
            if client_id:
                when = date.fromisoformat(_iso_date(doc.get('doc_date')) or _today().isoformat())
                lo, hi = (when - timedelta(days=10)).isoformat(), (when + timedelta(days=45)).isoformat()
                recs = [r for r in client_records(client_id, 'invoice') if r['status'] not in ('voided', 'bad_debt')
                        and lo <= (r['created'] or '') <= hi]
                if not recs:
                    recs = invoices_named(case.get('client_name') or doc.get('client_name') or '', lo, hi, client_id,
                                          labels=(doc.get('client_name'), doc.get('site')))
                found = sorted(recs, key=lambda r: abs((date.fromisoformat(r['created']) - when).days))[0] if recs else None
        except (JobberError, ValueError) as e:
            err = str(e)
    else:
        err = 'Jobber is not connected'
    num = f" #{doc['doc_number']}" if doc.get('doc_number') else ''
    key = f"gulfshore-unbilled:{doc['id']}"
    conn = _conn()
    try:
        if found:
            j['invoice'] = {'id': found['id'], 'number': found['number'], 'uri': found.get('uri') or '',
                            'status': found['status'], 'total': found.get('total')}
            if client_id:
                j.setdefault('client', {'id': client_id})
            conn.execute('UPDATE pump_cases SET jobber=?, sei_invoice_number=?, jobber_client_id=COALESCE(NULLIF('
                         "jobber_client_id, ''), ?) WHERE id=?", (json.dumps(j), found['number'], client_id or '', case_id))
            _set_step(conn, case_id, 'invoice_drafted', at=_today().isoformat(), by=actor)
            if found['status'] not in ('draft', 'voided', 'bad_debt'):
                # Already sent to the client (Rosewood #36816): nothing to send - only Jordan to pay.
                _set_step(conn, case_id, 'closed', at=_today().isoformat(), by=actor)
            conn.execute('UPDATE pump_todos SET done_at=?, done_by=? WHERE key=? AND done_at IS NULL',
                         (_now_text(), actor, key))
            _event(conn, actor, 'billed out', f"Gulfshore{num} is on our Jobber invoice #{found['number']} to the client - "
                                              "Christian can pay it", case_id=case_id, doc_id=doc['id'])
        else:
            amt = doc.get('total') if doc.get('total') is not None else doc.get('subtotal')
            who = case.get('client_name') or doc.get('client_name')
            if who:
                title = f"Gulfshore invoice{num} - {who}: not billed out yet"
                detail = (f"Jordan's {money_text(amt) if amt is not None else ''} filter cleaning on "
                          f"{doc.get('doc_date') or '?'} isn't on a Jobber invoice to the client yet"
                          f"{' (' + err + ')' if err else ''}. Bill it with the pump service - then it goes to "
                          "Christian to pay.")
            else:
                title = f"Gulfshore invoice{num}: which client is it for?"
                detail = ("The bill was read without Claude and the client couldn't be told from it. Open the job "
                          "and set the client - then it's checked against Jobber.")
            add_todo(conn, key, title, detail, {'case_id': case_id})
            conn.execute('UPDATE pump_todos SET title=?, detail=? WHERE key=? AND done_at IS NULL',
                         (title[:300], detail[:2000], key))
        conn.commit()
    finally:
        conn.close()
    if found and client_id and doc.get('client_name'):
        # The invoice confirms the client: Jordan's label is remembered like a pump bill's site name.
        try:
            remember_choice(doc, client_id, actor=actor)
        except (JobberError, ValueError):
            pass
    return {'billed': bool(found), 'invoice': found, 'error': err}


def _names_with(client_name, label):
    """The Jobber client's name starts with the site label, whole words: "FALLING WATERS II AT
    FALLING WATERS c/o GUARDIAN" for Jordan's "Falling Waters II" - not "Magnolia Falls @
    Falling Waters", nor "Falling Waters III"."""
    norm = lambda x: ' '.join(re.findall(r'[a-z0-9]+', (x or '').lower().replace('@', ' at ')))
    a, b = re.sub(r'^(?:inc|the)\s+', '', norm(client_name)), re.sub(r'^(?:inc|the)\s+', '', norm(label))
    return len(b) >= 4 and (a == b or a.startswith(b + ' '))


def _subject_site(subject):
    """The site our pump service invoice is for: "Pump service - Anna's Place - October 2026" -> "Anna's Place"."""
    m = re.match(r'\s*pump\s+(?:service|maintenance)\s*[-–:]\s*(.+?)(?:\s+[-–]\s+.*)?$', subject or '', re.I)
    return m.group(1).strip() if m else ''


def invoices_named(name, lo, hi, client_id=None, labels=()):
    """Jobber invoices found by searching the account's name (and the vendor's labels),
    created between lo and hi: the pump service invoice when the client's own list didn't
    have it (Magnolia Falls #36870, Oct 2026). The client's, when we know which client, or
    one whose name starts with a label (Falling Waters II #36834)."""
    labels = [l for l in labels if l] + [_core_name(name)]
    terms = []
    for t in labels:
        if len(t or '') >= 4 and t.lower() not in [x.lower() for x in terms]:
            terms.append(t)
    nodes = []
    for t in terms:
        data = jobber_gql('query($q: String) { invoices(first: 20, searchTerm: $q) { nodes { id invoiceNumber subject '
                          'invoiceStatus createdAt jobberWebUri amounts { total } client { id name } } } }', {'q': t})
        nodes += [n for n in ((data.get('invoices') or {}).get('nodes') or []) if n['id'] not in [m['id'] for m in nodes]]
    out = []
    for n in nodes:
        c = n.get('client') or {}
        site = _subject_site(n.get('subject'))
        named = _same_account(c.get('name') or '', name) or any(_names_with(c.get('name'), l) for l in labels) \
            or bool(site and any(_names_with(site, l) and _names_with(l, site) for l in labels))
        if not named and not (client_id and c.get('id') == client_id):
            continue
        created, status = (n.get('createdAt') or '')[:10], (n.get('invoiceStatus') or '').lower()
        if lo <= created <= hi and status not in ('voided', 'bad_debt'):
            out.append({'id': n['id'], 'number': str(n.get('invoiceNumber') or ''), 'status': status,
                        'total': _money((n.get('amounts') or {}).get('total')), 'created': created,
                        'uri': n.get('jobberWebUri')})
    return out


def reread_diver_bill(conn, case_id, actor='Pumps'):
    """A Gulfshore bill the basic reader got wrong (the client a line of Jordan's
    note, no number or date - Rosewood #2498, Oct 2026): read again from the
    stored file and the item put right. True when something changed."""
    case = dict(conn.execute('SELECT * FROM pump_cases WHERE id=?', (case_id,)).fetchone() or {})
    row = conn.execute("SELECT * FROM pump_docs WHERE case_id=? AND kind='bill' AND status != 'dismissed' "
                       "ORDER BY id DESC", (case_id,)).fetchone()
    if not case or not row or row['extracted_by'] != 'regex':
        return False
    # Once per bill: a client set by hand afterwards stays.
    conn.execute('INSERT OR IGNORE INTO pump_state (key, value) VALUES (?, ?)',
                 (f"diver_reread:{row['id']}", json.dumps(_now_text())))
    if conn.execute('SELECT changes()').fetchone()[0] != 1:
        return False
    try:
        with open(row['file_path'], 'rb') as f:
            text = extract_text(row['file_name'], f.read())
    except (OSError, TypeError):
        return False
    x = _gulfshore_fields(text, row['email_subject'] or '', row['file_name'], {
        'doc_number': row['doc_number'], 'doc_date': row['doc_date'], 'total': row['total'],
        'subtotal': row['subtotal'], 'tax': row['tax'], 'client_name': '', 'site': ''}, conn)
    acct, client_id = diver_client(conn, {**dict(row), **x})
    if (acct, x['doc_number'], x['doc_date']) == (case['client_name'], row['doc_number'], row['doc_date']):
        return False
    conn.execute('UPDATE pump_docs SET client_name=?, site=?, doc_number=?, doc_date=?, total=COALESCE(total, ?), '
                 'subtotal=COALESCE(subtotal, ?), updated_at=? WHERE id=?',
                 (x['client_name'], x['site'], x['doc_number'], x['doc_date'], x['total'], x['subtotal'], _now_text(),
                  row['id']))
    num = f" #{x['doc_number']}" if x['doc_number'] else ''
    conn.execute('UPDATE pump_cases SET client_name=?, title=?, vendor_bill_number=?, jobber_client_id=? WHERE id=?',
                 (acct, f"{acct or 'Lake'} - lake filter cleaning (Gulfshore{num})"[:160], x['doc_number'],
                  client_id or case.get('jobber_client_id') or '', case_id))
    for k in ('scheduled', 'work_done', 'vendor_bill'):
        if x['doc_date']:
            _set_step(conn, case_id, k, at=x['doc_date'], by=actor)
    _event(conn, actor, 'read again', f"Gulfshore{num}: {acct or 'client not found'}", case_id=case_id, doc_id=row['id'])
    return True


def check_report_only_bills(actor='Jobber sync'):
    """Bills for report-only accounts (The Reserve @ Estero, Autumn Woods, Wild Blue)
    waiting on the next monthly job: the account's recurring Jobber job's first visit
    on or after the bill's date - payable once it's completed."""
    conn = _conn()
    try:
        waiting = []
        for c in list_cases(conn, 'all'):
            pay = c['vendor_pay']
            if pay.get('report_only') and pay['state'] == 'unpaid' and c['status'] != 'cancelled':
                name = report_only_account(conn, c)
                row = conn.execute('SELECT jobber_job_id, jobber_job_label FROM pump_maint_accounts WHERE name=?',
                                   (name,)).fetchone() if name else None
                came = (((c.get('steps') or {}).get('vendor_bill') or {}).get('at') or c.get('opened_on') or '')[:10]
                waiting.append((c['id'], row['jobber_job_id'] if row else '', came))
    finally:
        conn.close()
    visits_of, done = {}, []
    for cid, job_id, came in waiting:
        note, mv = '', {}
        if not job_id:
            note = "the account's monthly job isn't linked to Jobber (Accounts tab)"
        else:
            try:
                if job_id not in visits_of:
                    visits_of[job_id] = job_visits(job_id)
                nxt = next((v for v in visits_of[job_id] if v['date'] >= came), None)
                if nxt:
                    mv = {'date': nxt['date'], 'visit_id': nxt['id']}
                    if nxt['completed']:
                        mv['completed_on'] = _today().isoformat()
                else:
                    note = 'no visit on the monthly job after the bill yet'
            except JobberError as e:
                note = f'Jobber: {e}'
        if note:
            mv['note'] = note
        conn = _conn()
        try:
            row = conn.execute('SELECT jobber FROM pump_cases WHERE id=?', (cid,)).fetchone()
            j = json.loads(row['jobber'] or '{}')
            if j.get('monthly_visit') != mv:
                j['monthly_visit'] = mv
                conn.execute('UPDATE pump_cases SET jobber=? WHERE id=?', (json.dumps(j), cid))
                if mv.get('completed_on'):
                    _event(conn, actor, 'pay vendor', f"The monthly job's visit of {mv['date']} is done - "
                                                      "the vendor's bill can be paid", case_id=cid)
                    done.append(cid)
                conn.commit()
        finally:
            conn.close()
    return done


def check_all_diver_bills(actor='Jobber sync'):
    """Every Gulfshore bill not billed out yet: looked for again (the invoice may be made later)."""
    conn = _conn()
    try:
        ids = [r[0] for r in conn.execute("SELECT id FROM pump_cases WHERE status='open' AND category='diver' "
                                          "AND vendor='Gulfshore' AND COALESCE(json_extract(jobber, '$.invoice.id'), '')=''")]
        for i in ids:
            reread_diver_bill(conn, i, actor)
        # Linked to an invoice already sent but left on "Send invoice" (before Oct 19 2026): closed.
        for r in conn.execute("SELECT id FROM pump_cases WHERE status='open' AND category='diver' AND vendor='Gulfshore' "
                              "AND COALESCE(json_extract(jobber, '$.invoice.status'), 'draft') "
                              "NOT IN ('draft', 'voided', 'bad_debt')").fetchall():
            _set_step(conn, r[0], 'closed', at=_today().isoformat(), by=actor)
        conn.commit()
    finally:
        conn.close()
    return [check_diver_billed(i, actor) for i in ids]


def _same_email_case(conn, doc):
    """The item a report's bill (or a bill's report) from the same email is on
    (Char Co McGuire Pk, Oct 2026: the report's name didn't match the bill's
    "Sunshine Lake Park" and made an item of its own). Only when the email's
    other documents are on one item."""
    other = {'report': 'bill', 'bill': 'report'}.get(doc.get('kind'))
    if not other or not (doc.get('email_uid') or '').strip():
        return None, ''
    ids = {r[0] for r in conn.execute(
        "SELECT d.case_id FROM pump_docs d JOIN pump_cases c ON c.id = d.case_id WHERE d.email_uid=? AND d.id != ? "
        "AND d.kind=? AND d.status != 'dismissed' AND c.status='open'", (doc['email_uid'], doc['id'], other))}
    return (ids.pop(), f'its {other} in the same email') if len(ids) == 1 else (None, '')


def merge_report_items(conn, job_id, actor='system'):
    """A report that made an item of its own, logged on the Jobber job of
    another open item still waiting on its report (Char Co McGuire Pk, Oct
    2026: the bill's item, Sunshine Lake Park, invoiced on job #541, sat on
    "Report logged"): the report moves onto that item, ticks its step, and
    the report's own item is closed as merged. Returns the item it went to."""
    if not job_id:
        return None
    owners = {r['id'] for r in conn.execute("SELECT id, jobber FROM pump_cases WHERE status='open' AND jobber LIKE ?",
                                            (f'%{job_id}%',))
              if (json.loads(r['jobber'] or '{}').get('job') or {}).get('id') == job_id}
    owners |= {r[0] for r in conn.execute(
        "SELECT d.case_id FROM pump_docs d JOIN pump_cases c ON c.id = d.case_id WHERE d.kind='bill' "
        "AND d.status != 'dismissed' AND c.status='open' AND json_extract(d.jobber, '$.job_id')=?", (job_id,))}
    report_only, arrived = {}, {}
    # (Its own item open, or already closed by hand - the report still counts for the bill's item.)
    for r in conn.execute("SELECT d.id, d.case_id, d.created_at FROM pump_docs d JOIN pump_cases c ON c.id = d.case_id "
                          "WHERE d.kind='report' AND d.status != 'dismissed' "
                          "AND json_extract(d.jobber, '$.note_target_id')=?", (job_id,)).fetchall():
        if not conn.execute("SELECT 1 FROM pump_docs WHERE case_id=? AND kind != 'report' AND status != 'dismissed'",
                            (r['case_id'],)).fetchone():
            report_only.setdefault(r['case_id'], []).append(r['id'])
            arrived[r['id']] = (r['created_at'] or '')[:10]

    def near(cid):
        # This visit's bill: arrived within 20 days of the report (not last month's on a monthly job).
        bills = [(b[0] or '')[:10] for b in conn.execute(
            "SELECT created_at FROM pump_docs WHERE case_id=? AND kind='bill' AND status != 'dismissed'", (cid,))]
        try:
            return any(abs((date.fromisoformat(b) - date.fromisoformat(a)).days) <= 20
                       for b in bills for a in arrived.values() if a and b)
        except ValueError:
            return False
    waiting = []
    for cid in owners - set(report_only):
        row = conn.execute('SELECT steps FROM pump_cases WHERE id=?', (cid,)).fetchone()
        st = json.loads(row['steps'] or '{}').get('report_logged') or {}
        has_report = conn.execute("SELECT 1 FROM pump_docs WHERE case_id=? AND kind='report' AND status != 'dismissed'",
                                  (cid,)).fetchone()
        if not st.get('at') and not st.get('na') and not has_report and near(cid):
            waiting.append(cid)
    if len(waiting) != 1 or not report_only:
        return None
    owner = waiting[0]
    for cid, doc_ids in report_only.items():
        for did in doc_ids:
            conn.execute('UPDATE pump_docs SET case_id=?, updated_at=? WHERE id=?', (owner, _now_text(), did))
        conn.execute("UPDATE pump_cases SET status='cancelled', stage='cancelled', updated_at=? WHERE id=? "
                     "AND status='open'", (_now_text(), cid))
        conn.execute("UPDATE pump_issues SET resolved_at=?, resolved_by=?, resolution=? WHERE case_id=? "
                     "AND resolved_at IS NULL", (_now_text(), actor, f'Merged into item #{owner}', cid))
        _event(conn, actor, 'merged', f'The report is for item #{owner} (same Jobber job) - moved there', case_id=cid)
        _event(conn, actor, 'merged', f"Item #{cid}'s report is this job's (same Jobber job) - moved here",
               case_id=owner)
    _set_step(conn, owner, 'report_logged', at=_today().isoformat(), by=actor)
    return owner


def merge_all_report_items(conn, actor='Pumps'):
    """merge_report_items for every report-only item's logged job."""
    jobs = {r[0] for r in conn.execute(
        "SELECT json_extract(d.jobber, '$.note_target_id') FROM pump_docs d JOIN pump_cases c ON c.id = d.case_id "
        "WHERE d.kind='report' AND d.status != 'dismissed' AND json_extract(d.jobber, '$.note_target')='job' "
        "AND d.updated_at >= ?", ((_today() - timedelta(days=60)).isoformat(),)) if r[0]}
    return [o for o in (merge_report_items(conn, j, actor) for j in sorted(jobs)) if o]


def file_document(conn, doc_id, actor='system'):
    """Put a document on its item (finding or creating one) and do what that
    kind of document means for the item. Returns the item id."""
    doc = dict(conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone())
    kind = doc['kind']
    if kind == 'other' or doc['status'] == 'dismissed':
        return None
    if kind == 'quote' and not doc['case_id'] and beatrice_site(doc.get('client_name'), doc.get('site')):
        return quote_to_beatrice(conn, doc, actor)
    if not doc['case_id'] and is_diver_bill(doc):
        return file_diver_bill(conn, doc, actor)
    case_id, how = (doc['case_id'], 'already linked') if doc['case_id'] else _same_email_case(conn, doc)
    if not case_id:
        case_id, how = _find_case_for(conn, doc)
    if not case_id:
        case_id = _new_case_for(conn, doc, actor)
        how = 'new item'
    conn.execute("UPDATE pump_docs SET case_id=?, status=CASE WHEN status='new' THEN 'filed' ELSE status END, "
                 "updated_at=? WHERE id=?", (case_id, _now_text(), doc_id))
    return _file_on_case(conn, doc, case_id, how, actor)


def refile_document(conn, doc_id, actor, target=None):
    """A document filed on the wrong item: off it - what it put there undone
    (its bill number and amounts, Bill from vendor / Work done when it ticked
    them) - and filed again on another open item or a new one."""
    row = conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
    if not row:
        return None
    doc, old = dict(row), row['case_id']
    if (_doc_dict(row).get('jobber') or {}).get('invoice_id') or (_doc_dict(row).get('jobber') or {}).get('quote_id'):
        raise ValueError("It's already drafted in Jobber from this item - delete that draft in Jobber first.")
    if old:
        case = conn.execute('SELECT * FROM pump_cases WHERE id=?', (old,)).fetchone()
        others = conn.execute("SELECT 1 FROM pump_docs WHERE case_id=? AND kind=? AND id != ? AND status != 'dismissed'",
                              (old, doc['kind'], doc_id)).fetchone()
        if case and not others:
            steps = json.loads(case['steps'] or '{}')
            when = doc.get('doc_date') or ''
            if doc['kind'] == 'bill':
                conn.execute("UPDATE pump_cases SET vendor_bill_number='', vendor_bill_amount=NULL, vendor_bill_total=NULL "
                             "WHERE id=?", (old,))
                for k in ('vendor_bill', 'bill_checked', 'work_done'):
                    if (steps.get(k) or {}).get('at') and (k != 'work_done' or steps[k]['at'] == when):
                        _set_step(conn, old, k, by=actor, na=False)
                conn.execute("UPDATE pump_issues SET resolved_at=?, resolved_by=? WHERE case_id=? AND doc_id=? "
                             "AND resolved_at IS NULL", (_now_text(), actor, old, doc_id))
            elif doc['kind'] == 'quote' and (steps.get('vendor_quote') or {}).get('at'):
                conn.execute("UPDATE pump_cases SET vendor_quote_number='', vendor_quote_amount=NULL, "
                             "vendor_quote_total=NULL WHERE id=?", (old,))
                _set_step(conn, old, 'vendor_quote', by=actor, na=False)
            _refresh_case(conn, old)
        _event(conn, actor, 'moved off', f"{doc.get('file_name')} wasn't for this item", case_id=old, doc_id=doc_id)
    conn.execute("UPDATE pump_docs SET case_id=NULL, status='new', updated_at=? WHERE id=?", (_now_text(), doc_id))
    if old:
        # An item the document made by itself, left with nothing: cancelled, not left on the lists.
        oc = conn.execute('SELECT * FROM pump_cases WHERE id=?', (old,)).fetchone()
        oj = json.loads((oc['jobber'] if oc else '') or '{}')
        if oc and oc['status'] == 'open' and oc['source'] not in ('manual', 'jobber', 'service_call') \
                and not any((oj.get(k) or {}).get('id') for k in ('quote', 'job', 'invoice')) \
                and not conn.execute("SELECT 1 FROM pump_docs WHERE case_id=? AND status != 'dismissed'", (old,)).fetchone():
            conn.execute("UPDATE pump_cases SET status='cancelled', stage='cancelled', updated_at=? WHERE id=?",
                         (_now_text(), old))
            conn.execute("UPDATE pump_issues SET resolved_at=?, resolved_by=?, resolution=? WHERE case_id=? "
                         "AND resolved_at IS NULL", (_now_text(), actor, 'Its document went on another job', old))
    if target:
        # The office picked the job (Huntington #5's bill, Oct 2026): that one, reopened if it was closed.
        if not conn.execute('SELECT 1 FROM pump_cases WHERE id=?', (target,)).fetchone():
            raise ValueError('No such job')
        conn.execute("UPDATE pump_cases SET status='open', updated_at=? WHERE id=? AND status != 'open'",
                     (_now_text(), target))
        case_id, how = target, 'picked by hand'
    else:
        case_id, how = _find_case_for(conn, dict(conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()),
                                      exclude=old)
    if not case_id:
        case_id = _new_case_for(conn, doc, actor)
        how = 'new item'
    conn.execute("UPDATE pump_docs SET case_id=?, status='filed', updated_at=? WHERE id=?", (case_id, _now_text(), doc_id))
    return _file_on_case(conn, doc, case_id, f'moved from item {old} - {how}', actor)


def _new_case_for(conn, doc, actor):
    """A new item for a document that belongs to none yet."""
    kind = doc['kind']
    title = doc.get('description') or ''
    if kind == 'report':
        rf = json.loads(doc.get('report_fields') or '{}')
        title = f"{(rf.get('title') or 'Pump report').title()} - {doc.get('client_name') or ''}".strip(' -')
    if kind != 'report' and doc.get('client_name') and title:
        title = f"{doc['client_name']} - {title.splitlines()[0]}"
    fields = {
        'title': (title or f"{doc.get('client_name') or 'Pump work'}")[:160],
        'category': ('maintenance' if kind == 'report' or maintenance_bill(doc) else doc.get('category') or 'repair'),
        'client_name': doc.get('client_name') or '',
        'site': doc.get('site') or '',
        'po_number': doc.get('po_number') or '',
        'vendor': doc.get('vendor') or '',
        'description': doc.get('description') or '',
        'approved_by': doc.get('ordered_by') or '',
        'wo_number': doc.get('wo_number') or '',
        'opened_on': doc.get('doc_date') or _today().isoformat(),
    }
    return create_case(conn, fields, actor, source=doc.get('source') or 'email')


def _file_on_case(conn, doc, case_id, how, actor):
    doc_id, kind = doc['id'], doc['kind']
    case = dict(conn.execute('SELECT * FROM pump_cases WHERE id=?', (case_id,)).fetchone())
    fill = {}
    for k_case, k_doc in (('client_name', 'client_name'), ('site', 'site'), ('vendor', 'vendor'),
                          ('po_number', 'po_number'), ('wo_number', 'wo_number'), ('description', 'description'),
                          ('approved_by', 'ordered_by')):
        if not (case.get(k_case) or '').strip() and (doc.get(k_doc) or '').strip():
            fill[k_case] = doc[k_doc]
    date_ = doc.get('doc_date') or _today().isoformat()
    if kind == 'quote':
        fill.update(vendor_quote_number=doc.get('doc_number') or '', vendor_quote_amount=doc.get('subtotal'),
                    vendor_quote_total=doc.get('total'))
        _apply(conn, case_id, fill)
        _set_step(conn, case_id, 'vendor_quote', at=date_, by=actor)
        lead = parts_lead_in(delivery_note(doc))
        if lead:
            conn.execute('UPDATE pump_cases SET parts_lead=? WHERE id=?', (lead, case_id))
    elif kind == 'bill':
        other_bill = conn.execute("SELECT 1 FROM pump_docs WHERE case_id=? AND kind='bill' AND id != ? "
                                  "AND status != 'dismissed'", (case_id, doc_id)).fetchone()
        if other_bill and (case.get('vendor_bill_number') or '').strip() and doc.get('doc_number') and \
                case['vendor_bill_number'].strip() != doc['doc_number'].strip():
            open_issue(conn, case_id, 'second_bill',
                       f"A second bill (#{doc['doc_number']}) arrived for this item, which already has bill "
                       f"#{case['vendor_bill_number']}. Check it is not a duplicate.", doc_id=doc_id)
        else:
            fill.update(vendor_bill_number=doc.get('doc_number') or '', vendor_bill_amount=doc.get('subtotal'),
                        vendor_bill_total=doc.get('total'))
            _apply(conn, case_id, fill)
        if maintenance_bill(doc):
            _maintenance_needs_no_quote(conn, case_id, actor)
        _set_step(conn, case_id, 'vendor_bill', at=date_, by=actor)
        steps = json.loads(conn.execute('SELECT steps FROM pump_cases WHERE id=?', (case_id,)).fetchone()[0])
        if not (steps.get('work_done') or {}).get('at') and not (steps.get('work_done') or {}).get('na'):
            _set_step(conn, case_id, 'work_done', at=date_, by=actor)
        _check_bill(conn, case_id, actor)
        _quote_needed_item(conn, doc, case_id, actor)
    elif kind == 'report':
        _apply(conn, case_id, fill)
        steps = json.loads(conn.execute('SELECT steps FROM pump_cases WHERE id=?', (case_id,)).fetchone()[0])
        if not (steps.get('work_done') or {}).get('at'):
            _set_step(conn, case_id, 'work_done', at=date_, by=actor)
        if (steps.get('report_logged') or {}).get('na'):
            _set_step(conn, case_id, 'report_logged', by=actor, na=False)
        _quote_needed_item(conn, doc, case_id, actor)
    _event(conn, actor, f'{kind} filed', f"{doc.get('file_name')} - matched by {how}", case_id=case_id, doc_id=doc_id)
    return case_id


def _apply(conn, case_id, fill):
    fill = {k: v for k, v in fill.items() if v not in (None, '')}
    if not fill:
        return
    cols = ', '.join(f'{k}=?' for k in fill)
    conn.execute(f'UPDATE pump_cases SET {cols}, updated_at=? WHERE id=?', (*fill.values(), _now_text(), case_id))


def ingest_document(filename, data, source='upload', email=None, kind_hint=None, actor='system', case_id=None):
    """Read, store and file one document, then draft our client quote in
    Jobber when it is a vendor quote that read cleanly."""
    res = _ingest_document(filename, data, source, email, kind_hint, actor, case_id)
    if res.get('read_again'):
        return res   # read_doc_again already drafted what was missing
    if res.get('kind') == 'quote' and res.get('case_id') and not res.get('review'):
        parts = split_letter(res['doc_id'], actor)
        res['auto_quote'] = auto_draft_quote(res['doc_id'])
        if parts:
            res['parts'] = parts
            _quote_each_part(parts, actor)
    if res.get('kind') == 'report' and res.get('doc_id') and not res.get('review'):
        # A report sent again (Lely, Oct 2026: the email forwarded to the mailbox
        # once more) that isn't in Jobber yet is tried again.
        res['auto_note'] = auto_log_report(res['doc_id'])
    if res.get('kind') == 'bill' and res.get('case_id') and not res.get('review'):
        conn = _conn()
        try:
            cat = conn.execute('SELECT category, vendor FROM pump_cases WHERE id=?', (res['case_id'],)).fetchone()
        finally:
            conn.close()
        if cat and cat['category'] == 'diver' and cat['vendor'] == 'Gulfshore':
            res['billed_out'] = check_diver_billed(res['case_id'])
        else:
            res['auto_invoice'] = auto_draft_invoice(res['doc_id'])
    return res


def _ingest_document(filename, data, source='upload', email=None, kind_hint=None, actor='system', case_id=None):
    """Read, store and file one document. Returns {'doc_id', 'case_id', ...}
    or {'skipped': reason}."""
    email = email or {}
    low = (filename or '').lower()
    if not low.endswith(('.pdf', '.docx', '.doc')):
        return {'skipped': 'not a PDF or Word file'}
    conn = _conn()
    try:
        sha = hashlib.sha256(data).hexdigest()
        dup = conn.execute('SELECT id, case_id FROM pump_docs WHERE file_sha=?', (sha,)).fetchone()
        if dup:
            prev = dict(conn.execute('SELECT kind, status, jobber, review_reason FROM pump_docs WHERE id=?',
                                     (dup['id'],)).fetchone())
            pj = json.loads(prev['jobber'] or '{}')
            if prev['status'] == 'dismissed' and prev['kind'] in ('quote', 'bill') and \
                    not (prev['review_reason'] or '').startswith('Duplicate'):
                # Dismissed by hand, then sent again: wanted after all - back on
                # its item (or filed again) and read with today's reader.
                prev['status'] = 'filed' if dup['case_id'] else 'new'
                conn.execute('UPDATE pump_docs SET status=?, updated_at=? WHERE id=?',
                             (prev['status'], _now_text(), dup['id']))
                _event(conn, actor, 'sent again', 'It was dismissed - back in use', case_id=dup['case_id'],
                       doc_id=dup['id'])
                conn.commit()
            # Edited by hand (a dismissal alone doesn't count): not read again over it.
            edited = conn.execute("SELECT 1 FROM pump_events WHERE doc_id=? AND action='document edited' "
                                  "AND COALESCE(detail, '') != 'status'", (dup['id'],)).fetchone()
            gone = dup['case_id'] and conn.execute("SELECT 1 FROM pump_cases WHERE id=? AND status='cancelled'",
                                                   (dup['case_id'],)).fetchone()
            if gone and prev['kind'] in ('quote', 'bill') and prev['status'] != 'dismissed':
                # Its item was cancelled: sent again, it starts over on an open
                # item - without the cancelled item's Jobber quote/invoice.
                pj = {k: v for k, v in pj.items() if not k.startswith(('quote_', 'invoice_'))}
                conn.execute("UPDATE pump_docs SET case_id=NULL, status='new', jobber=?, updated_at=? WHERE id=?",
                             (json.dumps(pj), _now_text(), dup['id']))
                _event(conn, actor, 'sent again', 'Its item was cancelled - filed again', case_id=dup['case_id'],
                       doc_id=dup['id'])
                dup = {'id': dup['id'], 'case_id': None}
                if edited:
                    # Corrected by hand: filed as it is, not read again.
                    dup['case_id'] = file_document(conn, dup['id'], actor)
                    conn.commit()
                    return {'doc_id': dup['id'], 'case_id': dup['case_id'], 'kind': prev['kind'], 'review': ''}
                conn.commit()
            on = conn.execute('SELECT category FROM pump_cases WHERE id=?', (dup['case_id'],)).fetchone() \
                if dup['case_id'] else None
            if prev['kind'] == 'bill' and on and on['category'] not in ('maintenance', 'inspection') and \
                    prev['status'] != 'dismissed' and not pj.get('invoice_id') and \
                    maintenance_bill(dict(conn.execute('SELECT * FROM pump_docs WHERE id=?', (dup['id'],)).fetchone())):
                # A maintenance bill sent again that sits on a repair (Lely, Oct 2026):
                # off it and filed on its own maintenance item, then invoiced as usual.
                case_id = refile_document(conn, dup['id'], actor)
                conn.commit()
                return {'doc_id': dup['id'], 'case_id': case_id, 'kind': 'bill', 'review': '', 'refiled': True}
            done_on = on and (json.loads(conn.execute('SELECT steps FROM pump_cases WHERE id=?', (dup['case_id'],))
                                         .fetchone()[0] or '{}').get('work_done') or {}).get('at')
            if prev['kind'] == 'quote' and on and (on['category'] in ('maintenance', 'inspection') or done_on) and \
                    prev['status'] != 'dismissed' and not pj.get('quote_id'):
                # A quote sent again that sits on the wrong item (Banyan Bay, Oct 2026: on the
                # report's maintenance visit, not the item waiting on it): moved where it fits now.
                best, _ = _find_case_for(conn, dict(conn.execute('SELECT * FROM pump_docs WHERE id=?',
                                                                  (dup['id'],)).fetchone()))
                if best and best != dup['case_id']:
                    case_id = refile_document(conn, dup['id'], actor)
                    conn.commit()
                    return {'doc_id': dup['id'], 'case_id': case_id, 'kind': 'quote', 'review': '', 'refiled': True}
            if prev['kind'] in ('quote', 'bill') and prev['status'] != 'dismissed' and not edited and \
                    not pj.get('invoice_id') and (prev['kind'] == 'quote' or not pj.get('quote_id')):
                # Sent again: read it again with today's reader (it may have
                # read it wrong the first time). Our Jobber quote is redone
                # if it's still a draft; an invoice in Jobber is left alone.
                try:
                    return {**read_doc_again(dup['id'], actor), 'read_again': True}
                except ValueError as e:
                    return {'skipped': f'already have this file ({e})', 'doc_id': dup['id'], 'case_id': dup['case_id']}
            return {'skipped': 'already have this file', 'doc_id': dup['id'], 'case_id': dup['case_id'],
                    'kind': prev['kind']}
        text = extract_text(filename, data)
        sender, subject = email.get('from', ''), email.get('subject', '')
        # A forwarded email is from one of us; the vendor shows in the
        # forwarded header at the top of the body, or on the document.
        vendor = _vendor_display(f"{sender}\n{subject}\n{email.get('preview', '')}\n{text[:3000]}")
        if source == 'email' and not vendor and not STRONG_TERMS.search(f'{subject}\n{filename}\n{text[:5000]}'):
            return {'skipped': 'not pump related'}
        if source == 'email' and _SITEONE_STORE.match(filename or ''):
            # SiteOne's store invoices (siteoneus_15664_...) are parts bought - the main app's Vendor
            # Invoices has them, not pump work to look at (Oct 2026).
            return {'skipped': 'SiteOne store invoice - not pump work'}
        path, sha = _store_file(data, filename)
        rec = {'kind': kind_hint or 'other', 'vendor': vendor, 'line_items': [], 'category': '',
               'doc_number': '', 'doc_date': '', 'po_number': '', 'wo_number': '', 'quote_reference': '',
               'ordered_by': '', 'client_name': '', 'site': '', 'description': '', 'subtotal': None, 'tax': None,
               'total': None, 'notes': '', 'proposal_title': ''}
        extracted_by, review, report_fields, branded_path, branded_info = '', '', {}, '', {}
        if low.endswith('.docx') and (kind_hint in (None, 'report')) and _is_report(filename, text):
            rec['kind'] = 'report'
            report_fields = pump_reports.read_report(data)
            rec.update(client_name=report_fields.get('customer') or _site_from_filename(filename),
                       site=report_fields.get('location') or '',
                       doc_date=_iso_date(report_fields.get('date')), description=report_fields.get('title') or '',
                       category='maintenance')
            extracted_by = 'report'
            try:
                vprof = pump_reports.vendor_for(f'{sender}\n{text}')
                branded, branded_info = pump_reports.rebrand_report(data, vendor=vprof)
                branded_path, _ = _store_file(branded, _branded_name(filename))
                _make_branded_pdf(branded_path, branded)
                # What goes into Jobber is read from OUR version: no technician,
                # no sub's name or contact details.
                report_fields = {**pump_reports.read_report(branded), 'from_branded': True}
                if branded_info.get('leftovers'):
                    review = 'Rebranded report still mentions: ' + ', '.join(branded_info['leftovers'])
            except Exception as e:
                review = f'Could not rebrand this report automatically: {e}'
                report_fields = {**report_fields, 'lines': []}
            # "Pump #4 check valve has a hole ... - quote to follow" in the comments (Lely, Oct 2026).
            note = _quote_needed_in([text])
            if note:
                report_fields = {**report_fields, 'quote_needed': note}
        elif low.endswith('.doc'):
            rec['kind'] = kind_hint or 'report'
            review = 'Old .doc Word file - open it, save as .docx and upload it again to rebrand it.'
            extracted_by = 'none'
        elif text.strip():
            x = _claude_extract(text, sender, subject, filename)
            if x:
                extracted_by = 'claude'
            else:
                x = _regex_extract(text, sender, subject, filename)
                extracted_by = 'regex'
                if USE_CLAUDE:
                    # Claude is meant to read it but failed: read again later.
                    review = 'Read without Claude - check the amounts and line items.'
                elif not (x.get('client_name') or x.get('po_number') or x.get('wo_number')):
                    review = 'Could not find the client, PO or work order - enter it by hand.'
            x = _letter_prices(text, _clean_extraction(x))
            if kind_hint:
                x['kind'] = kind_hint
            rec.update({k: v for k, v in x.items() if k in rec})
            rec['quote_ref'] = x.get('quote_reference') or ''
            if not rec['vendor']:
                rec['vendor'] = x.get('vendor') or vendor
            if x.get('notes'):
                rec['notes'] = x['notes']
            if rec['kind'] in ('quote', 'bill') and rec['total'] is None and rec['subtotal'] is None:
                review = 'No amount found - enter it by hand.'
        else:
            review = 'No text could be read (a scanned image?) - enter the details by hand.'
            extracted_by = 'none'
        if source == 'email' and not vendor and not review:
            review = 'Not from a known pump vendor - confirm it belongs here.'
        if rec['kind'] == 'other' and not review:
            review = 'Could not tell whether this is a quote, bill or report.'
        # The vendor sent this quote/bill before (a new scan, a forward, a
        # resend): the same number and amount is a duplicate - kept on file but
        # never used again; a different amount may be a revision - a person decides.
        dup_of = revised_of = None
        if rec['kind'] in ('quote', 'bill') and rec['doc_number'] and not case_id:
            prev = same_vendor_doc(conn, rec['vendor'], rec['kind'], rec['doc_number'])
            if prev:
                a = rec['total'] if rec['total'] is not None else rec['subtotal']
                b = prev['total'] if prev['total'] is not None else prev['subtotal']
                if a is None or b is None or abs(a - b) <= 0.5:
                    dup_of = prev
                    review = (f"Duplicate - {rec['vendor'] or 'the vendor'}'s {rec['kind']} #{rec['doc_number']} is "
                              f"already on file{' (job ' + str(prev['case_id']) + ')' if prev['case_id'] else ''}. "
                              'Not used again.')
                else:
                    revised_of = prev
                    word = 'quote' if rec['kind'] == 'quote' else 'invoice'
                    review = (f"{rec['vendor'] or 'The vendor'} sent {word} #{rec['doc_number']} again with a "
                              f"different amount (${b:,.2f} before, ${a:,.2f} now) - a revised {word}? Check which "
                              'is right before using it.')
        now = _now_text()
        conn.execute('''INSERT INTO pump_docs (kind, status, vendor, doc_number, doc_date, po_number, wo_number,
                          quote_ref, ordered_by, client_name, site, category, description, line_items, subtotal,
                          tax, total, file_name, file_path, file_sha, branded_path, branded_info, report_fields,
                          text_excerpt, source, email_uid, email_from, email_subject, email_date, case_id,
                          extracted_by, review_reason, created_at, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                     (rec['kind'], 'dismissed' if dup_of else ('review' if review else 'new'), rec['vendor'],
                      rec['doc_number'] or '',
                      rec['doc_date'] or '', rec['po_number'] or '', rec['wo_number'] or '', rec.get('quote_ref', ''),
                      rec['ordered_by'] or '', rec['client_name'] or '', rec['site'] or '', rec['category'] or '',
                      (rec['description'] or '') + (f"\n{rec['notes']}" if rec.get('notes') else ''),
                      json.dumps(rec['line_items']), rec['subtotal'], rec['tax'], rec['total'],
                      _safe_name(filename), path, sha, branded_path, json.dumps(branded_info),
                      json.dumps(report_fields), text[:4000], source, email.get('uid', ''), sender, subject,
                      email.get('date', ''), case_id, extracted_by, review, now, now))
        doc_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        if rec.get('proposal_title'):
            conn.execute('UPDATE pump_docs SET proposal_title=? WHERE id=?', (rec['proposal_title'][:200], doc_id))
        _event(conn, actor, 'document received', f'{rec["kind"]}: {filename} ({source})', doc_id=doc_id)
        if dup_of:
            conn.execute('UPDATE pump_docs SET case_id=? WHERE id=?', (dup_of['case_id'], doc_id))
            if dup_of['case_id']:
                _event(conn, actor, 'duplicate received', review, case_id=dup_of['case_id'], doc_id=doc_id)
            conn.commit()
            return {'skipped': review, 'doc_id': doc_id, 'case_id': dup_of['case_id'], 'duplicate_of': dup_of['id']}
        if revised_of and revised_of['case_id']:
            open_issue(conn, revised_of['case_id'], 'revised_doc', review, doc_id=doc_id)
        filed = None
        # Documents that need a person's eye wait in the inbox unfiled - except
        # reports and anything already pointed at an item.
        if not review or case_id or rec['kind'] == 'report':
            filed = file_document(conn, doc_id, actor)
        conn.commit()
        return {'doc_id': doc_id, 'case_id': filed, 'kind': rec['kind'], 'review': review}
    finally:
        conn.close()


def reread_doc(doc_id, actor='system'):
    """Read a document again with Claude - for one the basic reader handled
    while Claude was unavailable (e.g. the Anthropic account was out of
    credits). Only documents not yet on an item, so nothing the office has
    already worked on is overwritten. Files it when it now reads cleanly."""
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
        if not row:
            raise ValueError('No such document')
        doc = dict(row)
        if doc['case_id']:
            raise ValueError('This document is already on an item - correct it by hand there.')
        if doc['status'] == 'dismissed':
            raise ValueError('This document was dismissed.')
        if doc['kind'] == 'report' or (doc['file_name'] or '').lower().endswith(('.docx', '.doc')):
            raise ValueError('Reports are not read by Claude - use Rebrand again.')
        try:
            with open(doc['file_path'], 'rb') as f:
                data = f.read()
        except OSError:
            raise ValueError('The stored file is missing.')
        text = extract_text(doc['file_name'], data)
        if not text.strip():
            raise ValueError('No text could be read (a scanned image?) - enter the details by hand.')
        x = _claude_extract(text, doc['email_from'] or '', doc['email_subject'] or '', doc['file_name'])
        if not x:
            raise ValueError('Claude could not read it - check the Anthropic account has credits, then try again.')
        x = _letter_prices(text, _clean_extraction(x))
        known = _vendor_display(f"{doc['email_from'] or ''}\n{doc['email_subject'] or ''}\n{text[:3000]}")
        review = ''
        if x['kind'] in ('quote', 'bill') and x.get('total') is None and x.get('subtotal') is None:
            review = 'No amount found - enter it by hand.'
        elif doc['source'] == 'email' and not known:
            review = 'Not from a known pump vendor - confirm it belongs here.'
        elif x['kind'] == 'other':
            review = 'Could not tell whether this is a quote, bill or report.'
        desc = (x.get('description') or '') + (f"\n{x['notes']}" if x.get('notes') else '')
        conn.execute('''UPDATE pump_docs SET kind=?, status=?, vendor=?, doc_number=?, doc_date=?, po_number=?,
                          wo_number=?, quote_ref=?, ordered_by=?, client_name=?, site=?, category=?, description=?,
                          line_items=?, subtotal=?, tax=?, total=?, extracted_by='claude', review_reason=?,
                          proposal_title=?, updated_at=? WHERE id=?''',
                     (x['kind'], 'review' if review else 'new', known or x.get('vendor') or doc['vendor'] or '',
                      x.get('doc_number') or '', x.get('doc_date') or '', x.get('po_number') or '',
                      x.get('wo_number') or '', x.get('quote_reference') or '', x.get('ordered_by') or '',
                      x.get('client_name') or '', x.get('site') or '', x.get('category') or '', desc,
                      json.dumps(x['line_items']), x.get('subtotal'), x.get('tax'), x.get('total'), review,
                      (x.get('proposal_title') or '')[:200], _now_text(), doc_id))
        _event(conn, actor, 'read again', f"{x['kind']}: {doc['file_name']} (Claude)", doc_id=doc_id)
        filed = None if review else file_document(conn, doc_id, actor)
        conn.commit()
    finally:
        conn.close()
    out = {'doc_id': doc_id, 'case_id': filed, 'kind': x['kind'], 'review': review}
    if x['kind'] == 'quote' and filed:
        out['auto_quote'] = auto_draft_quote(doc_id)
    return out


def _unhide_doc(conn, doc_id):
    """A document sent or read again is wanted: its To do rows (and its
    item's) come back if they were deleted from the list."""
    row = conn.execute('SELECT case_id FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
    conn.execute('DELETE FROM pump_todo_hidden WHERE key=?', (f'doc:{doc_id}',))
    if row and row[0]:
        conn.execute('DELETE FROM pump_todo_hidden WHERE key LIKE ?', (f'case:{row[0]}:%',))


def read_doc_again(doc_id, actor='system'):
    """Read a quote or bill again with today's reader - e.g. a letter with two
    prices read as one before the reader knew better - and update it and its
    job. Our Jobber quote/invoice is drafted if there isn't one yet; one that
    exists is left alone (the office fixes it in Jobber)."""
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
        if not row:
            raise ValueError('No such document')
        doc = _doc_dict(row)
        if doc['kind'] not in ('quote', 'bill'):
            raise ValueError('Only quotes and bills are read again here.')
        _unhide_doc(conn, doc_id)
        if doc['status'] == 'dismissed':
            raise ValueError('This document was dismissed.')
        try:
            with open(row['file_path'], 'rb') as f:
                data = f.read()
        except (OSError, TypeError):
            raise ValueError('The stored file is missing.')
        text = extract_text(doc['file_name'], data)
        if not text.strip():
            raise ValueError('No text could be read (a scanned image?) - enter the details by hand.')
        x = _claude_extract(text, doc['email_from'] or '', doc['email_subject'] or '', doc['file_name'])
        how = 'claude' if x else 'regex'
        x = _clean_extraction(x or _regex_extract(text, doc['email_from'] or '', doc['email_subject'] or '',
                                                  doc['file_name']))
        x['kind'] = doc['kind']
        full = x = _letter_prices(text, x)
        dj = doc.get('jobber') or {}
        merged = ''
        if 'split_from' in dj or ('letter_parts' in dj and SPLIT_LETTERS):
            x = _letter_part(x, dj.get('letter_part') or 0)   # a piece of a letter split before Oct 9 2026
        elif 'letter_parts' in dj:
            # A letter split before Oct 9 2026 (Autumn Woods 2) is whole again:
            # one quote with a line for each piece of work.
            merged = _merge_letter_copies(conn, doc, actor)
        if x.get('total') is None and x.get('subtotal') is None:
            raise ValueError('No amount found reading it again - enter it by hand.')
        desc = (x.get('description') or doc['description'] or '') + (f"\n{x['notes']}" if x.get('notes') else '')
        conn.execute('''UPDATE pump_docs SET line_items=?, subtotal=?, tax=?, total=?, description=?,
                          doc_number=CASE WHEN doc_number='' THEN ? ELSE doc_number END, extracted_by=?,
                          updated_at=? WHERE id=?''',
                     (json.dumps(x['line_items']), x.get('subtotal'), x.get('tax'), x.get('total'), desc,
                      x.get('doc_number') or '', how, _now_text(), doc_id))
        opts = [i for i in x['line_items'] if i.get('optional')]
        summary = (f"{len(x['line_items'])} line(s), total ${x['total'] if x.get('total') is not None else x.get('subtotal'):,.2f}"
                   + (f", {len(opts)} optional" if opts else '') + merged)
        if doc['case_id']:
            fill = ({'vendor_quote_amount': x.get('subtotal'), 'vendor_quote_total': x.get('total')}
                    if doc['kind'] == 'quote' else
                    {'vendor_bill_amount': x.get('subtotal'), 'vendor_bill_total': x.get('total')})
            conn.execute(f"UPDATE pump_cases SET {', '.join(k + '=?' for k in fill)}, updated_at=? WHERE id=?",
                         (*fill.values(), _now_text(), doc['case_id']))
            if doc['kind'] == 'bill':
                _check_bill(conn, doc['case_id'], actor)
            _event(conn, actor, 'read again', f"{doc['kind']} {doc['file_name']}: {summary}",
                   case_id=doc['case_id'], doc_id=doc_id)
        filed = doc['case_id'] or (file_document(conn, doc_id, actor) if doc['status'] != 'review' else None)
        conn.commit()
    finally:
        conn.close()
    j = doc.get('jobber') or {}
    out = {'doc_id': doc_id, 'case_id': filed, 'kind': doc['kind'], 'summary': summary}
    parts = split_letter(doc_id, actor, full) if doc['kind'] == 'quote' and filed else []
    if parts:
        out['parts'] = parts
        out['part_quotes'] = _quote_each_part(parts, actor)
    if doc['kind'] == 'quote' and filed:
        if j.get('quote_id'):
            out.update(update_draft_quote(doc_id, actor))
        else:
            out['auto_quote'] = auto_draft_quote(doc_id)
    if doc['kind'] == 'bill' and filed:
        if j.get('invoice_id'):
            out['note'] = f"Our Jobber invoice #{j.get('invoice_number')} was made from the old reading - fix it in Jobber."
        else:
            out['auto_invoice'] = auto_draft_invoice(doc_id)
    return out


def reread_pending(actor='system', limit=25):
    """Documents the basic reader handled while Claude was unavailable, read
    again now that it is back. Stops at the first failure (Claude still down)."""
    if not USE_CLAUDE:
        return []
    conn = _conn()
    try:
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM pump_docs WHERE extracted_by='regex' AND case_id IS NULL AND status='review' "
            "AND kind != 'report' ORDER BY id LIMIT ?", (limit,))]
    finally:
        conn.close()
    done = []
    for i in ids:
        try:
            done.append(reread_doc(i, actor))
        except ValueError:
            break
    return done


def _branded_name(filename):
    base = os.path.splitext(_safe_name(filename))[0]
    return f'{base} - Stahlman-England.docx'


def _vendor_file_name(filename, ext):
    """The vendor's own file name with our file's extension: "10-26  Spanish Wells.docx" -> "10-26  Spanish Wells.pdf"."""
    return os.path.splitext(os.path.basename(filename or 'report'))[0] + ext


def _branded_pdf_path(branded_path):
    return os.path.splitext(branded_path)[0] + '.pdf' if branded_path else ''


def _make_branded_pdf(branded_path, docx_bytes=None):
    """The rebranded report as a PDF beside the Word file (needs LibreOffice)."""
    if not branded_path:
        return ''
    try:
        if docx_bytes is None:
            with open(branded_path, 'rb') as f:
                docx_bytes = f.read()
        pdf = pump_reports.docx_to_pdf(docx_bytes)
    except Exception as e:
        print(f'  ⚠ Pumps: no PDF of {os.path.basename(branded_path)}: {e}')
        pdf = None
    if not pdf:
        return ''
    path = _branded_pdf_path(branded_path)
    with open(path, 'wb') as f:
        f.write(pdf)
    return path


def _site_from_filename(filename):
    """"10-26  Spanish Wells.docx" -> "Spanish Wells" (the report's own customer
    box only holds our name)."""
    base = os.path.splitext(os.path.basename(filename or ''))[0]
    base = re.sub(r'^\s*\d{1,2}[-_./]\d{1,4}(?:[-_./]\d{2,4})?\s*', '', base)
    base = re.sub(r'\b(pump|fountain|maintenance|service|system|report|monthly|quarterly)s?\b', ' ', base, flags=re.I)
    return re.sub(r'[\s_\-]+', ' ', base).strip(' -')[:80]


# ═════════════════════════════════════════════════════════════════════════════
# PO@ mailbox scan
# ═════════════════════════════════════════════════════════════════════════════

def _scan_since():
    d = _iso_date(SCAN_SINCE)
    return d or (_today() - timedelta(days=60)).isoformat()


def _mail_preview(msg, limit=1000):
    """The start of an IMAP message's plain-text body."""
    try:
        for part in msg.walk():
            if part.get_content_type() == 'text/plain' and not part.get_filename():
                return (part.get_payload(decode=True) or b'').decode(part.get_content_charset() or 'utf-8',
                                                                    'replace')[:limit]
    except Exception:
        pass
    return ''


def scan_mailbox(actor='system'):
    """Read new mail in the PO@ inbox for pump quotes, bills and reports.
    Every email is looked at once (pump_email_scan_log)."""
    with _FileLock('scan', blocking=False) as got:
        if not got:
            return {'skipped': 'a scan is already running'}
        summary = {'emails_checked': 0, 'documents_added': 0, 'skipped': 0, 'errors': [], 'added': [],
                   'started_at': _now_text()}
        _state_set('scan_status', {'state': 'running', **summary})
        plain_since = max(_scan_since() or '', (_today() - timedelta(days=SERVICE_CALL_DAYS)).isoformat())
        try:
            try:
                fetched = CFG['fetch_emails'](log_table='pump_email_scan_log', extensions=('.pdf', '.docx', '.doc'),
                                              since=_scan_since(), plain_since=plain_since)
            except TypeError:
                fetched = CFG['fetch_emails'](log_table='pump_email_scan_log', extensions=('.pdf', '.docx', '.doc'),
                                              since=_scan_since())
        except Exception as e:
            summary['errors'].append(f'Mailbox: {e}')
            fetched = {'emails': []}
        diag = fetched.get('diagnostics') or {}
        if diag.get('error'):
            summary['errors'].append(diag['error'])
        source = fetched.get('source')
        recent = []
        for uid, msg in fetched.get('emails', []):
            summary['emails_checked'] += 1
            sender = subject = when = preview = ''
            found = 0
            try:
                if source == 'graph_api':
                    sender = ((msg.get('from') or {}).get('emailAddress') or {}).get('address', '')
                    subject = msg.get('subject', '')
                    preview = msg.get('bodyPreview', '')
                    when = msg.get('receivedDateTime', '')
                    attachments = CFG['graph_attachments'](uid) if msg.get('hasAttachments', True) else []
                else:
                    sender, subject, when = msg.get('From', ''), msg.get('Subject', ''), msg.get('Date', '')
                    preview = _mail_preview(msg)
                    attachments = CFG['email_attachments'](msg)
                for filename, data in attachments:
                    if not (filename or '').lower().endswith(('.pdf', '.docx', '.doc')) or not data:
                        continue
                    try:
                        res = ingest_document(filename, data, source='email', actor='email scan',
                                              email={'uid': str(uid), 'from': sender, 'subject': subject, 'date': when,
                                                     'preview': preview})
                    except Exception as e:
                        summary['errors'].append(f'{filename}: {e}')
                        continue
                    recent.append(_scan_result_line(filename, sender, res))
                    if res.get('doc_id') and not res.get('skipped'):
                        found += 1
                        summary['documents_added'] += 1
                        summary['added'].append({'doc_id': res['doc_id'], 'kind': res.get('kind'), 'file': filename})
                    else:
                        summary['skipped'] += 1
                        summary.setdefault('skipped_files', []).append(
                            {'file': filename, 'why': res.get('skipped') or '', 'case_id': res.get('case_id')})
                reply = handle_signed_quote_reply(str(uid), sender, subject, preview)
                if reply:
                    summary.setdefault('signed_quote_replies', []).append(reply)
                elif not found and not any((f or '').lower().endswith(('.pdf', '.docx', '.doc')) for f, _ in attachments):
                    call = handle_service_call_email(str(uid), sender, subject, preview)
                    if call:
                        summary.setdefault('service_calls', []).append(call)
            except Exception as e:
                summary['errors'].append(f'Email {uid}: {e}')
            conn = _conn()
            try:
                conn.execute('''INSERT OR IGNORE INTO pump_email_scan_log (email_uid, email_sender, email_subject,
                                  email_date, scanned_at, invoices_found, results) VALUES (?,?,?,?,?,?,?)''',
                             (str(uid), sender, subject, when, _now_text(), found, json.dumps({'documents': found})))
                conn.commit()
            finally:
                conn.close()
        try:
            reread = reread_pending('email scan')
        except Exception as e:
            reread = []
            summary['errors'].append(f'Reading again with Claude: {e}')
        summary['read_again'] = len(reread)
        summary['finished_at'] = _now_text()
        if recent:
            _state_set('scan_files', (recent[::-1] + (_state_get('scan_files') or []))[:60])
        _state_set('scan_status', {'state': 'done', **summary})
        return summary


def _scan_result_line(filename, sender, res):
    """What happened to one emailed file, for the "Recent files" list."""
    res = res or {}
    if res.get('skipped'):
        what = 'Not added - ' + res['skipped']
    elif res.get('read_again'):
        what = 'Read again' + (f" ({res['summary']})" if res.get('summary') else '') + \
               (f". {res['note']}" if res.get('note') else '')
    elif res.get('review'):
        what = f"Added as a {res.get('kind') or 'document'} - needs a look (To do: Look at)"
    else:
        what = f"Added as a {res.get('kind') or 'document'}"
    aq = res.get('auto_quote') or {}
    if aq.get('pending'):
        what += f" - quote not drafted: {aq['pending']}"
    elif aq.get('quote_number'):
        what += f" - draft quote #{aq['quote_number']} made in Jobber (To do: Send quote)"
    return {'at': _now_text(), 'file': filename, 'from': sender, 'what': what[:400],
            'case_id': res.get('case_id'), 'doc_id': res.get('doc_id')}


def start_scan(actor='system'):
    st = _state_get('scan_status') or {}
    if st.get('state') == 'running':
        try:
            started = datetime.strptime(st.get('started_at', '')[:19], '%Y-%m-%d %H:%M:%S')
            if (_now().replace(tzinfo=None) - started).total_seconds() < 1800:
                return False
        except ValueError:
            pass
    threading.Thread(target=_safe(scan_mailbox), args=(actor,), daemon=True).start()
    return True


def _safe(fn):
    def run(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as e:
            print(f'✗ Pumps background job {fn.__name__} failed: {e}')
    run.__name__ = fn.__name__
    return run


# ═════════════════════════════════════════════════════════════════════════════
# Jobber
# ═════════════════════════════════════════════════════════════════════════════

class JobberError(Exception):
    pass


def _fernet():
    from cryptography.fernet import Fernet
    secret = TOKEN_KEY or ('pumps-jobber:' + (CFG.get('secret_key') or ''))
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


# The newest Jobber tokens this process holds. Jobber's refresh token is good
# for one use: a new one that couldn't be saved (Oct 2026: the disk was full)
# is lost, and Jobber refuses the old one from then on. Kept here too, the app
# goes on working until the save succeeds.
_TOKEN_MEMO = {}


def _tokens():
    raw = _state_get('jobber_tokens_enc')
    saved = {}
    if raw:
        try:
            saved = json.loads(_fernet().decrypt(raw.encode()).decode())
        except Exception:
            saved = {}
    if _TOKEN_MEMO.get('refresh_token') and saved.get('refresh_token') and \
            float(_TOKEN_MEMO.get('obtained_at') or 0) > float(saved.get('obtained_at') or 0):
        return dict(_TOKEN_MEMO)
    return saved


def _save_tokens(tok):
    _TOKEN_MEMO.clear()
    _TOKEN_MEMO.update(tok or {})
    try:
        _state_set('jobber_tokens_enc', _fernet().encrypt(json.dumps(tok).encode()).decode() if tok else '')
    except Exception as e:
        print(f'  ❌ Pumps: could not save the Jobber sign-in ({e}) - kept in memory until it can be')


def jobber_status():
    tok = _tokens()
    if tok.get('broken'):
        # Jobber refused the saved sign-in: it has to be connected again.
        return {'connected': False, 'how': 'oauth', 'broken': tok['broken'], 'at': tok.get('broken_at'),
                'can_connect': bool(JOBBER_CLIENT_ID and JOBBER_CLIENT_SECRET)}
    if tok.get('refresh_token'):
        return {'connected': True, 'how': 'oauth', 'by': tok.get('connected_by'), 'at': tok.get('connected_at'),
                'can_connect': True}
    if JOBBER_STATIC_TOKEN:
        return {'connected': True, 'how': 'token', 'can_connect': bool(JOBBER_CLIENT_ID and JOBBER_CLIENT_SECRET)}
    return {'connected': False, 'how': '', 'can_connect': bool(JOBBER_CLIENT_ID and JOBBER_CLIENT_SECRET)}


def _token_request(fields):
    r = http_requests.post(JOBBER_TOKEN, timeout=30,
                           data=dict(fields, client_id=JOBBER_CLIENT_ID, client_secret=JOBBER_CLIENT_SECRET))
    try:
        out = r.json()
    except ValueError:
        out = {}
    if r.status_code >= 400 or not out.get('access_token'):
        raise JobberError(f"Jobber refused the sign-in (HTTP {r.status_code}): "
                          f"{out.get('error_description') or out.get('error') or 'no detail'}")
    return out


def _access_token(force=False):
    tok = _tokens()
    if not tok.get('refresh_token'):
        if JOBBER_STATIC_TOKEN:
            return JOBBER_STATIC_TOKEN
        raise JobberError('Jobber is not connected to Pumps yet')
    with _FileLock('jobber_token'):
        tok = _tokens()
        age = time.time() - float(tok.get('obtained_at') or 0)
        # force: Jobber said the token was refused - unless another thread
        # (the sync runs several calls at once) refreshed it a moment ago.
        if tok.get('broken'):
            raise JobberError('Jobber needs reconnecting - click Reconnect Jobber at the top of Pumps')
        if (force and age > 30) or age > 55 * 60:
            try:
                new = _token_request({'grant_type': 'refresh_token', 'refresh_token': tok['refresh_token']})
            except JobberError as e:
                if re.search(r'HTTP 40[01]\b', str(e)):
                    # The refresh token itself was refused: no retry will fix it - only reconnecting.
                    _save_tokens({**tok, 'broken': str(e), 'broken_at': _now_text()})
                raise
            tok.update(access_token=new['access_token'], obtained_at=time.time(),
                       refresh_token=new.get('refresh_token') or tok['refresh_token'])
            _save_tokens(tok)
        return tok['access_token']


def _mutation_fields(query):
    """Root fields of a GraphQL mutation document."""
    m = re.search(r'\bmutation\b[^{]*\{(.*)\}\s*$', query, re.S)
    if not m:
        return []
    body, depth, names, i = m.group(1), 0, [], 0
    while i < len(body):
        ch = body[i]
        if ch in '{(':
            depth += 1
        elif ch in '})':
            depth -= 1
        elif depth == 0:
            w = re.match(r'(\w+)\s*(?::\s*(\w+))?', body[i:])
            if w:
                names.append(w.group(2) or w.group(1))
                i += w.end()
                continue
        i += 1
    return names


def check_mutation_allowed(query):
    """Refuse anything but the draft-quote, draft-invoice and note mutations."""
    if not re.match(r'\s*mutation\b', query):
        return
    if not _human_clicked():
        raise JobberError('Not done by itself - the app only changes Jobber when you click its button')
    fields = _mutation_fields(query)
    bad = [f for f in fields if f not in ALLOWED_MUTATIONS]
    if not fields or bad:
            raise JobberError(f"Blocked Jobber mutation {bad or '(unreadable)'}: "
                          'Pumps only creates draft quotes, draft invoices, notes, jobs from approved quotes '
                          'and visits, and completes maintenance visits.')


def jobber_gql(query, variables=None):
    check_mutation_allowed(query)
    force, reason = False, 'signed out or rate limited'
    for _ in range(10):
        token = _access_token(force)
        r = http_requests.post(JOBBER_GQL, timeout=60, json={'query': query, 'variables': variables or {}},
                               headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json',
                                        'X-JOBBER-GRAPHQL-VERSION': JOBBER_API_VERSION})
        if r.status_code == 401 and _tokens().get('refresh_token'):
            force, reason = True, 'signed out'
            continue
        if r.status_code == 429:
            time.sleep(20)
            reason = 'rate limited'
            continue
        if r.status_code in (502, 503, 504):
            # Jobber's own server timed out (504 on the "pump" quote search, Oct 19 2026): a pause, then again.
            time.sleep(10)
            reason = f'Jobber API HTTP {r.status_code}'
            continue
        if r.status_code >= 400:
            raise JobberError(f'Jobber API HTTP {r.status_code}')
        out = r.json()
        errors = out.get('errors') or []
        if errors:
            if any((e.get('extensions') or {}).get('code') == 'THROTTLED' for e in errors):
                # Jobber's points bucket: wait as long as it takes to refill for this query. One
                # costing more than the whole bucket never runs (SCADA invoices, Oct 2026).
                cost = (out.get('extensions') or {}).get('cost') or {}
                need, ts = cost.get('requestedQueryCost') or 0, cost.get('throttleStatus') or {}
                if need and ts.get('maximumAvailable') and need > ts['maximumAvailable']:
                    raise JobberError(f"Jobber won't run a query this big ({need} points, "
                                      f"{ts['maximumAvailable']} allowed)")
                short = need - (ts.get('currentlyAvailable') or 0)
                time.sleep(min(30, max(2, short / (ts.get('restoreRate') or 500) + 1)) if need else 15)
                reason = 'rate limited'
                continue
            raise JobberError(' | '.join(e.get('message', '?') for e in errors))
        return out.get('data') or {}
    raise JobberError(f'Jobber kept refusing the request ({reason})')


def _render(spec):
    return ' '.join(f if isinstance(f, str) else f'{f[0]} {{ {_render(f[1])} }}' for f in spec)


def _drop(spec, field):
    out = []
    for f in spec:
        if isinstance(f, str):
            if f != field:
                out.append(f)
        elif f[0] != field:
            out.append((f[0], _drop(f[1], field)))
    return out


def _gql_tolerant(make_query, spec, variables, required=()):
    """Run a query, dropping fields this Jobber API version does not have."""
    for _ in range(8):
        try:
            return jobber_gql(make_query(_render(spec)), variables), spec
        except JobberError as e:
            m = re.search(r"Field '(\w+)' doesn't exist", str(e))
            if m and m.group(1) not in required and m.group(1) in _render(spec).split():
                spec = _drop(spec, m.group(1))
                continue
            raise
    raise JobberError('Too many unknown fields')


JOBBER_PARALLEL = 2   # Jobber calls at once during a sync (4 kept tripping its rate limit, Oct 2026)
_ADDR = ('address', ['street1', 'street2', 'city'])
SYNC_SPECS = {
    'requests': (['id', 'title', 'requestStatus', 'createdAt', 'updatedAt', 'jobberWebUri',
                  ('client', ['id', 'name', 'isCompany']), ('property', ['id', _ADDR])], 'requestStatus'),
    'quotes': (['id', 'quoteNumber', 'title', 'quoteStatus', 'createdAt', 'updatedAt', 'jobberWebUri',
                ('amounts', ['total']), ('client', ['id', 'name', 'isCompany']), ('property', ['id', _ADDR])], 'quoteStatus'),
    'jobs': (['id', 'jobNumber', 'title', 'jobStatus', 'jobType', 'createdAt', 'updatedAt', 'startAt',
              'completedAt', 'jobberWebUri', 'total', ('client', ['id', 'name', 'isCompany']), ('property', ['id', _ADDR])],
             'jobStatus'),
    'invoices': (['id', 'invoiceNumber', 'subject', 'invoiceStatus', 'createdAt', 'updatedAt', 'issuedDate',
                  'jobberWebUri', ('amounts', ['total']), ('client', ['id', 'name'])], 'invoiceStatus'),
}
OPEN_STATUSES = {
    'request': {'new', 'needs_approval', 'assessment_completed', 'overdue', 'today', 'upcoming', 'unscheduled'},
    'quote': {'draft', 'awaiting_response', 'changes_requested', 'approved'},
    'job': {'active', 'late', 'requires_invoicing', 'action_required', 'today', 'upcoming', 'unscheduled',
            'on_hold'},
    'invoice': {'draft'},
}


def _prop_label(p):
    a = (p or {}).get('address') or {}
    return ', '.join(x for x in [a.get('street1'), a.get('street2'), a.get('city')] if x)


def _category(title, prop_label=''):
    text = f'{title or ""} {prop_label or ""}'
    for cat in ('scada', 'diver', 'filter', 'pump'):
        if TITLE_PATTERNS[cat].search(title or '') or (cat == 'pump' and TITLE_PATTERNS['pump'].search(prop_label or '')):
            return cat
    return '' if not TITLE_PATTERNS['pump'].search(text) else 'pump'


def sync_jobber(full=False, actor='system'):
    """A Jobber sync that never leaves "running" behind when it fails."""
    try:
        return _sync_jobber(full, actor)
    except Exception as e:
        st = _state_get('jobber_sync') or {}
        if st.get('state') == 'running':
            st.update(state='failed', finished_at=_now_text(), errors=(st.get('errors') or []) + [str(e)])
            _state_set('jobber_sync', st)
        raise


def jobber_sync_state():
    """The last sync's status. "running" with nobody holding the sync lock means
    the sync died (a restart mid-sync), so it reads as interrupted."""
    st = _state_get('jobber_sync') or {}
    if st.get('state') == 'running':
        with _FileLock('jobber_sync', blocking=False) as got:
            if got:
                st.update(state='interrupted', finished_at=_now_text(),
                          errors=(st.get('errors') or []) + ['The sync stopped part way (the app restarted) - run it again.'])
                _state_set('jobber_sync', st)
    return st


def _sync_search(conn_name, spec, status_field, term, full):
    """One search term's pages of one kind of Jobber record:
    (spec as Jobber took it, {id: item}, errors)."""
    kind, seen, errors = conn_name[:-1], {}, []
    cursor, pages = None, 0
    while pages < (40 if full else 10):
        def make(fields):
            return (f'query($first: Int!, $after: String, $q: String) {{ {conn_name}(first: $first, '
                    f'after: $after, searchTerm: $q) {{ nodes {{ {fields} }} '
                    f'pageInfo {{ hasNextPage endCursor }} }} }}')
        try:
            data, spec = _gql_tolerant(make, spec, {'first': 50, 'after': cursor, 'q': term},
                                       required=('id', 'title', 'subject', 'client'))
        except JobberError as e:
            errors.append(f'{conn_name} "{term}": {e}')
            break
        page = data.get(conn_name) or {}
        for n in page.get('nodes') or []:
            title = n.get('title') or n.get('subject') or ''
            plabel = _prop_label(n.get('property'))
            cat = _category(title, plabel)
            if not cat:
                continue
            seen[n['id']] = {
                'jobber_id': n['id'], 'kind': kind,
                'number': str(n.get('quoteNumber') or n.get('jobNumber') or n.get('invoiceNumber') or ''),
                'title': title, 'status': (n.get(status_field) or '').lower(),
                'job_type': (n.get('jobType') or '').lower(),
                'client_id': (n.get('client') or {}).get('id', ''),
                'client_name': (n.get('client') or {}).get('name', ''),
                'client_company': (None if 'isCompany' not in (n.get('client') or {})
                                   else int(bool(n['client']['isCompany']))),
                'property_id': (n.get('property') or {}).get('id', ''),
                'property_label': plabel,
                'total': _money(n.get('total') if n.get('total') is not None else (n.get('amounts') or {}).get('total')),
                'created_at': n.get('createdAt') or '', 'updated_at': n.get('updatedAt') or '',
                'start_at': n.get('startAt') or n.get('issuedDate') or '',
                'completed_at': n.get('completedAt') or '', 'approved_at': '',
                'web_uri': n.get('jobberWebUri') or '', 'category': cat,
                'po_number': po_from_title(title)}
        info = page.get('pageInfo') or {}
        pages += 1
        if not info.get('hasNextPage'):
            break
        cursor = info.get('endCursor')
        time.sleep(0.2)
    return spec, seen, errors


RECENT_QUOTE_DAYS = 120


def _sync_recent_quotes(seen):
    """Quotes approved or out with the client lately whose TITLE doesn't say
    pump - the office's "Proposal to inspect suction line" (Greenscapes
    #9136) - which the keyword searches never return: kept when their lines
    say pump, well or Wettech, or the client is an account we follow. Added
    to seen (records already found are left as they are). Returns errors."""
    errors, kept = [], {}
    spec = ['id', 'quoteNumber', 'title', 'quoteStatus', 'createdAt', 'updatedAt', 'jobberWebUri',
            ('amounts', ['total']), ('client', ['id', 'name', 'isCompany']), ('property', ['id', _ADDR]),
            ('lineItems(first: 10)', [('nodes', ['name', 'description'])])]
    since = (_today() - timedelta(days=RECENT_QUOTE_DAYS)).isoformat()
    conn = _conn()
    try:
        def ours(n):
            text = ' '.join([n.get('title') or ''] + [f"{li.get('name') or ''} {li.get('description') or ''}"
                                                      for li in ((n.get('lineItems') or {}).get('nodes') or [])])
            if TITLE_PATTERNS['pump'].search(text) or _VENDOR_WORDS.search(text):
                return True
            # One of our accounts, and about pump equipment - not every quote they get: The Reserve @ Estero's
            # valve boxes and gate valve (#8443, Oct 2026) were irrigation work for Install.
            if not _PUMP_HINTS.search(text):
                return False
            c = n.get('client') or {}
            return _tracked_account(conn, {'client_id': c.get('id'), 'client_name': c.get('name'),
                                           'property_label': _prop_label(n.get('property'))})
        filter_failed = False
        for status in ('approved', 'awaiting_response', None):
            if status is None and not filter_failed:
                break          # both filtered passes worked: nothing more to read
            cursor, pages, filtered = None, 0, status is not None
            while pages < (3 if filtered else 6):
                flt = f', filter: {{ status: {status} }}' if filtered else ''
                def make(fields):
                    return (f'query($first: Int!, $after: String) {{ quotes(first: $first, after: $after{flt}) '
                            f'{{ nodes {{ {fields} }} pageInfo {{ hasNextPage endCursor }} }} }}')
                try:
                    data, spec = _gql_tolerant(make, spec, {'first': 50, 'after': cursor}, required=('id', 'title', 'client'))
                except JobberError as e:
                    if filtered:
                        filter_failed = True   # this Jobber can't filter by status: the unfiltered pass covers it
                        break
                    errors.append(f'recent quotes: {e}')
                    break
                page = data.get('quotes') or {}
                for n in page.get('nodes') or []:
                    st = (n.get('quoteStatus') or '').lower()
                    if n['id'] in seen or n['id'] in kept or st not in ('approved', 'awaiting_response', 'changes_requested'):
                        continue
                    if (n.get('updatedAt') or n.get('createdAt') or '')[:10] < since or not ours(n):
                        continue
                    title = n.get('title') or ''
                    kept[n['id']] = {
                        'jobber_id': n['id'], 'kind': 'quote', 'number': str(n.get('quoteNumber') or ''),
                        'title': title, 'status': st, 'job_type': '',
                        'client_id': (n.get('client') or {}).get('id', ''),
                        'client_name': (n.get('client') or {}).get('name', ''),
                        'client_company': (None if 'isCompany' not in (n.get('client') or {})
                                           else int(bool(n['client']['isCompany']))),
                        'property_id': (n.get('property') or {}).get('id', ''),
                        'property_label': _prop_label(n.get('property')),
                        'total': _money((n.get('amounts') or {}).get('total')),
                        'created_at': n.get('createdAt') or '', 'updated_at': n.get('updatedAt') or '',
                        'start_at': '', 'completed_at': '', 'approved_at': '',
                        'web_uri': n.get('jobberWebUri') or '', 'category': 'pump', 'po_number': po_from_title(title)}
                info = page.get('pageInfo') or {}
                pages += 1
                if not info.get('hasNextPage'):
                    break
                cursor = info.get('endCursor')
                time.sleep(0.2)
    finally:
        conn.close()
    seen.update(kept)
    return errors


def _sync_jobber(full=False, actor='system'):
    """Pull pump, diver, filter and SCADA requests, quotes, jobs and invoices
    from Jobber, then rebuild the SCADA list and link items by PO number."""
    with _FileLock('jobber_sync', blocking=False) as got:
        if not got:
            return {'skipped': 'a Jobber sync is already running'}
        status = {'state': 'running', 'started_at': _now_text(), 'counts': {}, 'errors': []}
        t0 = time.time()
        _state_set('jobber_sync', status)
        seen = {}
        terms = sorted({t for ts in JOBBER_TERMS.values() for t in ts})
        # Every kind of record x every search term (40 searches) - several at
        # a time. Each kind's first search runs alone first, so fields this
        # Jobber doesn't have are dropped once, not by every search.
        jobs, specs = [], {}
        for conn_name, (spec, status_field) in SYNC_SPECS.items():
            spec, found, errs = _sync_search(conn_name, spec, status_field, terms[0], full)
            specs[conn_name] = spec
            seen.update(found)
            status['errors'] += errs
            jobs += [(conn_name, status_field, t) for t in terms[1:]]
        with ThreadPoolExecutor(max_workers=JOBBER_PARALLEL) as pool:
            results = list(pool.map(lambda a: _sync_search(a[0], specs[a[0]], a[1], a[2], full), jobs))
        for _, found, errs in results:
            seen.update(found)
            status['errors'] += errs
        status['errors'] += _sync_recent_quotes(seen)
        for conn_name in SYNC_SPECS:
            status['counts'][conn_name] = sum(1 for v in seen.values() if v['kind'] == conn_name[:-1])
        conn = _conn()
        try:
            now = _now_text()
            for it in seen.values():
                conn.execute('''INSERT INTO pump_jobber_items (jobber_id, kind, number, title, status, job_type,
                                  client_id, client_name, property_id, property_label, total, created_at, updated_at,
                                  start_at, completed_at, approved_at, web_uri, category, po_number, synced_at,
                                  client_company)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                                ON CONFLICT(jobber_id) DO UPDATE SET kind=excluded.kind, number=excluded.number,
                                  title=excluded.title, status=excluded.status, job_type=excluded.job_type,
                                  client_id=excluded.client_id, client_name=excluded.client_name,
                                  property_id=excluded.property_id, property_label=excluded.property_label,
                                  total=excluded.total, updated_at=excluded.updated_at, start_at=excluded.start_at,
                                  completed_at=excluded.completed_at, web_uri=excluded.web_uri,
                                  category=excluded.category, po_number=excluded.po_number,
                                  synced_at=excluded.synced_at, client_company=excluded.client_company''',
                             (it['jobber_id'], it['kind'], it['number'], it['title'], it['status'], it['job_type'],
                              it['client_id'], it['client_name'], it['property_id'], it['property_label'],
                              it['total'], it['created_at'], it['updated_at'], it['start_at'], it['completed_at'],
                              it['approved_at'], it['web_uri'], it['category'], it['po_number'], now,
                              it['client_company']))
            linked = _link_jobber_items(conn)
            status['errors'] += _refresh_linked_records(conn)
            _follow_invoices(conn)
            duplicate_jobber_invoices(conn)
            reconcile_quote_waits(conn)
            approved = _follow_quotes(conn)
            approved += auto_track_approved(conn)
            close_stale_todos(conn)
            rebuild_scada(conn)
            conn.commit()
            try:
                check_all_irrigation()
            except Exception as e:
                status['errors'].append(f'Irrigation check: {e}')
            try:
                check_all_diver_bills()
            except Exception as e:
                status['errors'].append(f'Gulfshore bills: {e}')
            try:
                check_report_only_bills()
            except Exception as e:
                status['errors'].append(f'Report-only bills: {e}')
            try:
                refresh_scada_quotes()
            except Exception as e:
                status['errors'].append(f'SCADA quotes: {e}')
            try:
                jobs_to_close()
            except Exception as e:
                status['errors'].append(f'Jobs to close: {e}')
            try:
                sweep_quote_needed()
            except Exception as e:
                status['errors'].append(f'Quotes needed: {e}')
            status['errors'] += refresh_client_contacts(conn)
            conn.commit()
            try:
                status['scada_invoices'] = scan_scada_invoices(conn)
                conn.commit()
            except JobberError as e:
                status['errors'].append(f'SCADA invoices: {e}')
        finally:
            conn.close()
        for cid in approved:
            try:
                on_quote_approved(cid)
            except Exception as e:
                status['errors'].append(f'Approved quote (item {cid}): {e}')
        status.update(state='done', finished_at=_now_text(), items=len(seen), linked=linked,
                      seconds=round(time.time() - t0))
        for e in status['errors'][:20]:
            print(f'  ⚠ Pumps Jobber sync: {e}')
        _state_set('jobber_sync', status)
        return status


def on_account_sheets(conn, it, names=None):
    """Whether a Jobber record is work we follow: one of our accounts (the
    maintenance and lake sheets, site names, SCADA accounts), or any client
    Jobber has as a company (a hotel, an HOA not on the sheets yet). A
    homeowner's pump work - a Jobber client who is a person and not on the
    sheets - is done in Jobber but not followed here."""
    if it.get('category') == 'scada' or it.get('client_company') != 0:
        return True
    text = ' '.join(x for x in (it.get('client_name'), it.get('title'), it.get('property_label')) if x)
    for n in (names if names is not None else _account_names(conn)):
        core = _core_name(n)
        if len(core) >= 4 and fuzzy_has(core, text):
            return True
    return False


# Fetched by id: the Jobber records our items are linked to. Jobber's search
# doesn't look at quote titles, so a quote we drafted may never come up in
# the term search; asking for it by id keeps its status (sent, approved) and
# total current either way.
_LINKED_QUERIES = {
    'quote': ('quote', 'quoteNumber', 'quoteStatus', 'amounts { total }', {'approved', 'converted', 'archived'}),
    'invoice': ('invoice', 'invoiceNumber', 'invoiceStatus', 'amounts { total }', {'paid', 'voided', 'bad_debt'}),
    'job': ('job', 'jobNumber', 'jobStatus', 'total', {'archived'}),
}


def _refresh_linked_records(conn, kinds=None):
    """Update pump_jobber_items for every quote, invoice and job an item is
    linked to that isn't finished yet - open items, and closed ones still
    waiting on the client to pay. Returns errors."""
    errors, want = [], {}
    recent = (_today() - timedelta(days=REOPEN_DAYS)).isoformat()
    for c in conn.execute("SELECT id, status, jobber, updated_at FROM pump_cases "
                          "WHERE jobber LIKE '%\"id\"%'").fetchall():
        j = json.loads(c['jobber'] or '{}')
        for kind, (_, _, _, _, final) in _LINKED_QUERIES.items():
            if kinds and kind not in kinds:
                continue
            rec = j.get(kind) or {}
            if not rec.get('id') or (rec.get('status') or '') in final:
                continue
            # A quote still out on a job closed or cancelled lately: the client may
            # yet approve it (Huntington #5 and #6, Oct 2026).
            if c['status'] != 'open' and not (kind == 'invoice' and c['status'] != 'cancelled') and \
                    not (kind == 'quote' and (c['updated_at'] or '')[:10] >= recent):
                continue
            want[rec['id']] = (kind, c['id'])
    # Approved quotes no item follows yet show in To do as new work: checked
    # too, so one deleted in Jobber drops off.
    since = (_today() - timedelta(days=90)).isoformat()
    for r in conn.execute("SELECT jobber_id FROM pump_jobber_items WHERE kind='quote' AND case_id IS NULL "
                          "AND status='approved' AND COALESCE(created_at, updated_at, '') >= ?", (since,)).fetchall():
        want.setdefault(r[0], ('quote', None))
    def fetch(item):
        jid, (kind, _) = item
        field, num, st, total, _ = _LINKED_QUERIES[kind]
        try:
            return jobber_gql(f'query($id: EncodedId!) {{ {field}(id: $id) {{ id {num} {st} {total} '
                              f'jobberWebUri updatedAt }} }}', {'id': jid}), None
        except JobberError as e:
            return None, e
    # Fetched several at a time; the database is written here, one by one.
    with ThreadPoolExecutor(max_workers=JOBBER_PARALLEL) as pool:
        fetched = list(pool.map(fetch, want.items()))
    for (jid, (kind, case_id)), (data, err) in zip(want.items(), fetched):
        field, num, st, total, _ = _LINKED_QUERIES[kind]
        if err is not None:
            if _GONE.search(str(err)):
                jobber_record_gone(conn, kind, jid)
            else:
                errors.append(f'{kind} {jid}: {err}')
            continue
        n = data.get(field)
        if not n:
            jobber_record_gone(conn, kind, jid)
            continue
        amount = _money(n.get('total') if n.get('total') is not None else (n.get('amounts') or {}).get('total'))
        conn.execute('''INSERT INTO pump_jobber_items (jobber_id, kind, number, status, total, updated_at, web_uri,
                          case_id, synced_at) VALUES (?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(jobber_id) DO UPDATE SET status=excluded.status, total=excluded.total,
                          updated_at=excluded.updated_at, number=excluded.number, synced_at=excluded.synced_at,
                          case_id=COALESCE(pump_jobber_items.case_id, excluded.case_id)''',
                     (jid, kind, str(n.get(num) or ''), (n.get(st) or '').lower(), amount, n.get('updatedAt') or '',
                      n.get('jobberWebUri') or '', case_id, _now_text()))
    return errors


_GONE = re.compile(r'not\s+found|could\s*n.?t\s+(?:be\s+)?f(?:i|ou)nd|does\s*n.?o?t\s+exist|no\s+longer\s+exists|'
                   r'has\s+been\s+deleted', re.I)


def jobber_record_gone(conn, kind, jid):
    """A quote, invoice or job deleted in Jobber: forget it, and take it off
    any item and document it was on - the item goes back to needing one."""
    row = conn.execute('SELECT number FROM pump_jobber_items WHERE jobber_id=?', (jid,)).fetchone()
    num = row[0] if row else ''
    conn.execute('DELETE FROM pump_jobber_items WHERE jobber_id=?', (jid,))
    for c in conn.execute('SELECT id, jobber FROM pump_cases WHERE jobber LIKE ?', (f'%{jid}%',)).fetchall():
        j = json.loads(c['jobber'] or '{}')
        rec = j.get(kind) or {}
        if rec.get('id') != jid:
            continue
        num = num or rec.get('number') or ''
        j.pop(kind)
        conn.execute('UPDATE pump_cases SET jobber=?, updated_at=? WHERE id=?', (json.dumps(j), _now_text(), c['id']))
        _event(conn, 'jobber sync', f'{kind} deleted',
               f"Jobber {kind} #{num} was deleted in Jobber - taken off this job", case_id=c['id'])
    for d in conn.execute('SELECT id, jobber FROM pump_docs WHERE jobber LIKE ?', (f'%{jid}%',)).fetchall():
        j = json.loads(d['jobber'] or '{}')
        if j.get(f'{kind}_id') != jid:
            continue
        j = {k: v for k, v in j.items() if not k.startswith(f'{kind}_')}
        conn.execute('UPDATE pump_docs SET jobber=? WHERE id=?', (json.dumps(j), d['id']))
    return num


def untracked_jobber_items(conn, others=False):
    """Open pump requests, approved quotes and one-off jobs made in Jobber that
    no item here follows yet and nobody has ignored - for our accounts only
    (others=True: just the ones that aren't). A quote still out with the
    client needs nothing from us until it is approved."""
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM pump_jobber_items WHERE kind IN ('request','quote','job') AND case_id IS NULL "
        "AND ignored=0 ORDER BY created_at DESC")]
    rows = [r for r in rows if r['status'] in OPEN_STATUSES[r['kind']]
            and not (r['kind'] == 'job' and r['job_type'] == 'recurring')
            and not (r['kind'] == 'quote' and r['status'] != 'approved')]
    names = _account_names(conn)
    # Quotes for Beatriz's sites are never tracked here.
    rows = [r for r in rows if not (r['kind'] == 'quote' and
                                    beatrice_site(r.get('client_name'), r.get('property_label'), r.get('title')))]
    return [r for r in rows if on_account_sheets(conn, r, names) != others]


def _link_jobber_items(conn):
    """Attach Jobber records to items by PO number, and fill the item's Jobber links."""
    linked = 0
    cases = [dict(r) for r in conn.execute("SELECT id, po_number, jobber FROM pump_cases WHERE po_number != ''")]
    by_po = {}
    for c in cases:
        k = po_key(c['po_number'])
        if k:
            by_po.setdefault(k, []).append(c)
    for it in conn.execute("SELECT * FROM pump_jobber_items WHERE po_number != '' AND case_id IS NULL"):
        hits = by_po.get(it['po_number'], [])
        if len(hits) != 1:
            continue
        c = hits[0]
        conn.execute('UPDATE pump_jobber_items SET case_id=? WHERE jobber_id=?', (c['id'], it['jobber_id']))
        j = json.loads(c['jobber'] or '{}')
        j.setdefault(it['kind'], {'id': it['jobber_id'], 'number': it['number'], 'uri': it['web_uri'],
                                  'status': it['status'], 'total': it['total']})
        conn.execute("UPDATE pump_cases SET jobber=?, jobber_request_made=CASE WHEN COALESCE(jobber_request_made,'')='' "
                     "THEN ? ELSE jobber_request_made END WHERE id=?",
                     (json.dumps(j), _jobber_ref_text(it), c['id']))
        _event(conn, 'jobber sync', 'linked', f"{it['kind']} {it['number'] or ''} {it['title']}", case_id=c['id'])
        linked += 1
    # A quote or job made in Jobber from a request we already follow: same client
    # and property, and only one open item there that has no quote/job of that kind.
    open_cases = [dict(r) for r in conn.execute(
        "SELECT id, jobber, jobber_client_id, jobber_property_id, opened_on FROM pump_cases "
        "WHERE status='open' AND jobber_client_id != '' AND jobber_property_id != ''")]
    for it in conn.execute("SELECT * FROM pump_jobber_items WHERE kind IN ('quote','job') AND case_id IS NULL "
                           "AND ignored=0 AND client_id != '' AND property_id != ''").fetchall():
        hits = [c for c in open_cases if c['jobber_client_id'] == it['client_id']
                and c['jobber_property_id'] == it['property_id']
                and not json.loads(c['jobber'] or '{}').get(it['kind'])
                and (it['created_at'] or '')[:10] >= (c['opened_on'] or '')[:10]]
        if len(hits) != 1:
            continue
        _link_item(conn, it['jobber_id'], hits[0]['id'], 'jobber sync')
        hits[0]['jobber'] = json.dumps({**json.loads(hits[0]['jobber'] or '{}'), it['kind']: {'id': it['jobber_id']}})
        linked += 1
    return linked


def _with_invoice_link(conn, c):
    """A job waiting on its invoice to be sent, with the Jobber invoice's page
    to open - from the draft we made, else the synced invoice with its number."""
    inv = dict((c.get('jobber') or {}).get('invoice') or {})
    if not inv.get('uri'):
        num = str(inv.get('number') or c.get('sei_invoice_number') or '').lstrip('#').strip()
        row = conn.execute("SELECT jobber_id, web_uri FROM pump_jobber_items WHERE kind='invoice' AND "
                           "(jobber_id=? OR number=?) AND web_uri != '' LIMIT 1",
                           (inv.get('id') or '', num or '-')).fetchone()
        if row:
            inv.update(uri=row['web_uri'], number=inv.get('number') or num)
    return {**c, 'jobber': {**(c.get('jobber') or {}), 'invoice': inv}} if inv else c


def _with_quote_link(conn, c):
    """A job whose quote is to send, with our Jobber quote's page to open (Send quote)."""
    q = dict((c.get('jobber') or {}).get('quote') or {})
    if q.get('id') and not q.get('uri'):
        row = conn.execute("SELECT web_uri FROM pump_jobber_items WHERE jobber_id=? AND web_uri != ''",
                           (q['id'],)).fetchone()
        if row:
            q['uri'] = row['web_uri']
    return {**c, 'jobber': {**(c.get('jobber') or {}), 'quote': q}} if q else c


def _follow_invoices(conn):
    """Keep each item's Jobber invoice status current. Once the office has sent
    the invoice from Jobber and everything else on the item is done, the item
    closes itself. Closed items are followed too: when the client pays, the
    vendor's bill is flagged to be paid."""
    for c in conn.execute("SELECT id, status, jobber, steps, vendor_paid_on FROM pump_cases "
                          "WHERE status != 'cancelled' AND jobber LIKE '%invoice%'").fetchall():
        j = json.loads(c['jobber'] or '{}')
        inv = j.get('invoice') or {}
        if not inv.get('id'):
            continue
        it = conn.execute('SELECT status, total FROM pump_jobber_items WHERE jobber_id=?', (inv['id'],)).fetchone()
        if not it:
            continue
        if it['total'] is not None and it['total'] != inv.get('total'):
            inv['total'] = it['total']
            j['invoice'] = inv
            conn.execute('UPDATE pump_cases SET jobber=? WHERE id=?', (json.dumps(j), c['id']))
        if it['status'] == inv.get('status'):
            continue
        inv['status'] = it['status']
        j['invoice'] = inv
        conn.execute('UPDATE pump_cases SET jobber=? WHERE id=?', (json.dumps(j), c['id']))
        _event(conn, 'jobber sync', 'invoice status', f"Jobber invoice #{inv.get('number')} is now {it['status']}",
               case_id=c['id'])
        if it['status'] == 'paid' and not c['vendor_paid_on']:
            _event(conn, 'jobber sync', 'pay vendor', 'The client paid the Jobber invoice - the vendor\'s bill is due',
                   case_id=c['id'])
        if c['status'] == 'open' and it['status'] not in ('draft', 'voided', 'bad_debt') and \
                _stage(json.loads(c['steps'] or '{}')) == 'closed':
            _set_step(conn, c['id'], 'closed', at=_today().isoformat(), by='jobber sync')


# How far back a closed or cancelled job's quote is still watched for approval.
REOPEN_DAYS = 60
QUOTE_GONE_OUT = ('awaiting_response', 'changes_requested', 'approved', 'converted')


# Words that say nothing about which work a quote is for.
_WORK_STOP = {'estimate', 'needed', 'needs', 'recommend', 'recommended', 'recommends', 'replace', 'replacement',
              'install', 'installation', 'new', 'quote', 'please', 'provide', 'should', 'would', 'also', 'club',
              'house', 'clubhouse', 'station', 'irrigation', 'system', 'repair', 'repairs', 'report', 'comments'}
PENDING_QUOTE = ('draft', 'awaiting_response', 'changes_requested')


def _pump_nums(text):
    """Pump numbers named in a text: "Pump #2", "pump 2", "PS 1" -> {'2', '1'}."""
    return set(re.findall(r'\b(?:pump|ps|station)\s*#?\s*(\d{1,2})\b', (text or '').lower()))


def pending_quote_for(conn, case):
    """A quote already in Jobber for the work an item is waiting on a quote
    for (Autumn Woods, Oct 2026: the report asked for a surge protector and
    flow meters, and quotes #9181, #9161 and #9159 were already out to the
    client): the client's one draft or sent quote, not yet approved, whose
    title names the same work (and the same pump, when either names one).
    None unless exactly one fits."""
    j = case.get('jobber') if isinstance(case.get('jobber'), dict) else json.loads(case.get('jobber') or '{}')
    name = case.get('client_name') or ''
    cid_j = case.get('jobber_client_id') or (j.get('client') or {}).get('id') or ''
    work = f"{case.get('title') or ''} {case.get('description') or ''}"
    own = _match_words(name) | _match_words(case.get('site') or '')
    want = {w for w in _match_words(work) - own if w not in _WORK_STOP}
    if not want:
        return None
    nums = _pump_nums(work)
    best, ties = [], 0
    for it in conn.execute("SELECT * FROM pump_jobber_items WHERE kind='quote' AND COALESCE(ignored, 0)=0 "
                           f"AND status IN ({','.join('?' * len(PENDING_QUOTE))})", PENDING_QUOTE):
        it = dict(it)
        if it.get('case_id') and it['case_id'] != case.get('id') and conn.execute(
                "SELECT 1 FROM pump_cases WHERE id=? AND status != 'cancelled'", (it['case_id'],)).fetchone():
            continue   # another item has it
        same = (cid_j and it.get('client_id') == cid_j) or (
            name and max(similarity(name, it.get('client_name') or ''),
                         similarity(name, it.get('property_label') or '')) >= 0.85)
        if not same:
            continue
        theirs = nums and _pump_nums(it.get('title') or '')
        if theirs and not (theirs & nums):
            continue   # "Pump #1" is not the "Pump #2" quote
        shared = len(want & (_match_words(it.get('title') or '') - own))
        if not shared:
            continue
        score = shared + (1 if theirs else 0)
        if not best or score > best[0]:
            best, ties = [score, it], 0
        elif score == best[0]:
            ties += 1
    return best[1] if best and not ties else None


def link_pending_quote(conn, case_id, it, actor):
    """Put the quote already made on the item: no longer waiting on the vendor's
    quote - on sending ours (a draft) or on the client's answer."""
    _link_item(conn, it['jobber_id'], case_id, actor)
    steps = json.loads(conn.execute('SELECT steps FROM pump_cases WHERE id=?', (case_id,)).fetchone()[0] or '{}')
    for k in ('assessment', 'vendor_quote'):
        if not (steps.get(k) or {}).get('at'):
            _set_step(conn, case_id, k, by=actor, na=True)
    if it['status'] != 'draft' and not (steps.get('client_quote') or {}).get('at'):
        _set_step(conn, case_id, 'client_quote', at=(it.get('updated_at') or '')[:10] or _today().isoformat(), by=actor)
    _event(conn, actor, 'quote already made', f"Jobber quote #{it['number']} \"{it['title']}\" is for this work "
                                              f"({it['status'].replace('_', ' ')})", case_id=case_id)


def reconcile_quote_waits(conn, actor='Jobber sync'):
    """A job still "waiting on quote" whose client has since been sent a quote
    in Jobber (Magnolia Cove, Oct 2026: "Quote is needed" kept waiting after
    quote #9186 went out from another job). The one such quote, when it's on
    no job, is linked to this one; when it's on another job and this one is
    an empty placeholder (no documents, no Jobber quote or job), this one is
    merged into that job. Returns what was done."""
    done = []
    rows = [dict(r) for r in conn.execute("SELECT * FROM pump_cases WHERE status='open' "
                                          "AND stage IN ('assessment', 'vendor_quote')")]
    for c in rows:
        j = json.loads(c.get('jobber') or '{}')
        if any((j.get(k) or {}).get('id') for k in ('quote', 'job', 'invoice')):
            continue
        it = pending_quote_for(conn, c)
        if it:
            # The quote for this work is already made - it's waiting on the client, not on a quote.
            link_pending_quote(conn, c['id'], it, actor)
            done.append(('linked', c['id'], it['number']))
            continue
        name, cid_j = c.get('client_name') or '', c.get('jobber_client_id') or (j.get('client') or {}).get('id') or ''
        opened = c.get('opened_on') or (c.get('created_at') or '')[:10]
        cands = []
        for it in conn.execute("SELECT * FROM pump_jobber_items WHERE kind='quote' AND COALESCE(ignored, 0)=0 "
                               "AND COALESCE(case_id, 0) != ?", (c['id'],)):
            it = dict(it)
            if it['status'] not in QUOTE_GONE_OUT or (it.get('created_at') or '')[:10] < opened:
                continue
            same = (cid_j and it.get('client_id') == cid_j) or (
                name and max(similarity(name, it.get('client_name') or ''),
                             similarity(name, it.get('property_label') or '')) >= 0.85)
            if same:
                cands.append(it)
        if len(cands) != 1:
            continue   # none, or more than one: a person sorts it out
        it = cands[0]
        # The job it's on: marked on the Jobber record, or the quote our app drafted from a job.
        own = conn.execute("SELECT id FROM pump_cases WHERE id != ? AND json_extract(jobber, '$.quote.id')=? "
                           "ORDER BY id DESC", (c['id'], it['jobber_id'])).fetchone()
        other = it.get('case_id') or (own[0] if own else None)
        if other == c['id']:
            continue
        if other:
            o = conn.execute("SELECT status FROM pump_cases WHERE id=?", (other,)).fetchone()
            # Only a placeholder made BEFORE the job that quoted it (a lower job #):
            # one opened later at the same client is new work, not this quote.
            if not o or o['status'] == 'cancelled' or other < c['id']:
                continue
            if conn.execute("SELECT 1 FROM pump_docs WHERE case_id=? AND status != 'dismissed'",
                            (c['id'],)).fetchone():
                continue   # it has its own documents: not just a placeholder
            conn.execute("UPDATE pump_cases SET status='cancelled', stage='cancelled', updated_at=? WHERE id=?",
                         (_now_text(), c['id']))
            conn.execute("UPDATE pump_issues SET resolved_at=?, resolved_by=?, resolution=? WHERE case_id=? "
                         "AND resolved_at IS NULL", (_now_text(), actor, f"Covered by job #{other}", c['id']))
            for jt in conn.execute("SELECT jobber_id FROM pump_jobber_items WHERE case_id=?", (c['id'],)).fetchall():
                _link_item(conn, jt[0], other, actor)   # its Jobber request goes with it
            _event(conn, actor, 'merged', f"Quote #{it['number']} went to {it['client_name']} from job #{other} - "
                                          f"this job is the same work", case_id=c['id'])
            _event(conn, actor, 'merged', f"\"{c.get('title') or name}\" (job #{c['id']}) was waiting on this quote "
                                          f"- merged into this job", case_id=other)
            done.append(('merged', c['id'], other))
        elif not other:
            _link_item(conn, it['jobber_id'], c['id'], actor)
            done.append(('linked', c['id'], it['number']))
    return done


def _follow_quotes(conn):
    """Keep each item's Jobber quote status current, and tick "Quote sent to
    client" / "Client approved" once the office has sent it and the client
    has approved it in Jobber. Returns the items just approved."""
    approved = []
    recent = (_today() - timedelta(days=REOPEN_DAYS)).isoformat()
    for c in conn.execute("SELECT id, status, jobber, steps FROM pump_cases WHERE (status='open' OR updated_at >= ?) "
                          "AND jobber LIKE '%quote%'", (recent,)).fetchall():
        j = json.loads(c['jobber'] or '{}')
        q = j.get('quote') or {}
        if not q.get('id'):
            continue
        it = conn.execute('SELECT status, updated_at, total FROM pump_jobber_items WHERE jobber_id=?',
                          (q['id'],)).fetchone()
        if not it:
            continue
        if it['total'] is not None and it['total'] != q.get('total'):
            q['total'] = it['total']
            j['quote'] = q
            conn.execute('UPDATE pump_cases SET jobber=? WHERE id=?', (json.dumps(j), c['id']))
        steps = json.loads(c['steps'] or '{}')
        if c['status'] != 'open':
            # Closed or cancelled while the quote was still out, and now the client
            # approved it: the work is on again. Anything else stays as it is.
            # Or it was still a draft, and has now gone to the client (Homewood, 9176).
            # (Not when the quote now belongs to another job: this one was replaced.)
            approved_now = it['status'] == 'approved' and q.get('status') != 'approved' and \
                not (steps.get('client_approved') or {}).get('at')
            sent_now = it['status'] in QUOTE_GONE_OUT and (q.get('status') or 'draft') == 'draft' and \
                not (steps.get('client_quote') or {}).get('at')
            if not (approved_now or sent_now) or \
                    conn.execute("SELECT 1 FROM pump_cases WHERE id != ? AND status != 'cancelled' "
                                 "AND json_extract(jobber, '$.quote.id')=?", (c['id'], q['id'])).fetchone():
                if it['status'] != q.get('status'):
                    q['status'] = it['status']
                    j['quote'] = q
                    conn.execute('UPDATE pump_cases SET jobber=? WHERE id=?', (json.dumps(j), c['id']))
                continue
            conn.execute("UPDATE pump_cases SET status='open', closed_at=NULL, closed_by_hand='', updated_at=? "
                         "WHERE id=?", (_now_text(), c['id']))
            _event(conn, 'jobber sync', 'reopened', f"Jobber quote #{q.get('number')} "
                                                    f"{'was approved' if approved_now else 'went to the client'} - "
                                                    f"this job was {c['status']}, it's open again", case_id=c['id'])
        if it['status'] != q.get('status'):
            q['status'] = it['status']
            j['quote'] = q
            conn.execute('UPDATE pump_cases SET jobber=? WHERE id=?', (json.dumps(j), c['id']))
            _event(conn, 'jobber sync', 'quote status', f"Jobber quote #{q.get('number')} is now {it['status']}",
                   case_id=c['id'])
        # Checked every sync, not just when the status changes: a quote whose
        # status was noted earlier (linked, or before this check) still ticks
        # "Quote sent" - nobody has to tick it by hand.
        steps = json.loads(c['steps'] or '{}')
        when = (it['updated_at'] or '')[:10] or _today().isoformat()
        if it['status'] in ('awaiting_response', 'changes_requested', 'approved', 'converted') and \
                not (steps.get('client_quote') or {}).get('at'):
            _set_step(conn, c['id'], 'client_quote', at=when, by='jobber sync')
        if it['status'] in ('approved', 'converted') and not (steps.get('client_approved') or {}).get('at'):
            _set_step(conn, c['id'], 'client_approved', at=when, by='jobber sync')
            approved.append(c['id'])
    return approved


def _jobber_ref_text(it):
    """What goes in the sheet's "Jobber Request Made" column."""
    return f"Yes - {it['kind']}" + (f" #{it['number']}" if it['number'] else '')


def start_jobber_sync(full=False, actor='system'):
    if jobber_sync_state().get('state') == 'running':
        return False
    threading.Thread(target=_safe(sync_jobber), args=(full, actor), daemon=True).start()
    return True


# ── SCADA ────────────────────────────────────────────────────────────────────

def _scada_site(title):
    """'Estimate to Renew the SCADA system- Driving Range' -> 'Driving Range'."""
    m = re.search(r'scada[^-–]*?[-–]\s*(.+)$', title or '', re.I)
    if not m:
        return ''
    site = m.group(1).strip()
    if re.match(r'^(dec|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov)\w*\s+\d{4}', site, re.I) or \
            re.match(r'^annual', site, re.I):
        return ''
    return site[:60]


def rebuild_scada(conn):
    """One row per client (and named site) that has had SCADA work in Jobber.
    Rows people have edited keep their edits; dates only ever move forward."""
    items = [dict(r) for r in conn.execute("SELECT * FROM pump_jobber_items WHERE category='scada'")]
    groups = {}
    for it in items:
        key = (it['client_id'], _scada_site(it['title']))
        groups.setdefault(key, []).append(it)
    for (client_id, site), its in groups.items():
        renewals, open_quote, recurring, amount = [], '', 0, None
        for it in its:
            when = (it.get('completed_at') or it.get('start_at') or it.get('created_at') or '')[:10]
            if it['kind'] == 'job':
                if it['job_type'] == 'recurring' and it['status'] not in ('archived',):
                    recurring = 1
                renewals.append(when)
                amount = it['total'] if it['total'] else amount
            elif it['kind'] == 'invoice' and it['status'] not in ('voided', 'draft'):
                renewals.append(when)
            elif it['kind'] == 'quote':
                if it['status'] in ('approved', 'converted'):
                    renewals.append(when)
                elif it['status'] in ('awaiting_response', 'changes_requested', 'draft'):
                    open_quote = json.dumps({'number': it['number'], 'status': it['status'],
                                             'created': it['created_at'][:10], 'uri': it['web_uri']})
        renewals = sorted(d for d in renewals if d)
        last = renewals[-1] if renewals else ''
        history = [{'kind': it['kind'], 'number': it['number'], 'title': it['title'], 'status': it['status'],
                    'date': (it.get('completed_at') or it.get('created_at') or '')[:10], 'uri': it['web_uri'],
                    'total': it['total']} for it in sorted(its, key=lambda x: x.get('created_at') or '')]
        if open_quote and last and json.loads(open_quote)['created'] < last:
            open_quote = ''
        row = conn.execute('SELECT * FROM pump_scada WHERE jobber_client_id=? AND site=?', (client_id, site)).fetchone()
        now = _now_text()
        if row:
            keep_last = max(row['last_renewed_on'] or '', last)
            conn.execute('''UPDATE pump_scada SET client_name=?, last_renewed_on=?, recurring=?, open_quote=?,
                              history=?, annual_amount=COALESCE(annual_amount, ?), updated_at=? WHERE id=?''',
                         (its[0]['client_name'], keep_last, recurring, open_quote, json.dumps(history), amount, now,
                          row['id']))
        else:
            conn.execute('''INSERT INTO pump_scada (client_name, jobber_client_id, site, last_renewed_on, recurring,
                              open_quote, history, annual_amount, source, updated_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?)''',
                         (its[0]['client_name'], client_id, site, last, recurring, open_quote, json.dumps(history),
                          amount, 'jobber', now))


# ── draft invoices and notes ─────────────────────────────────────────────────

def _tok_match(a, b):
    """Two words that are the same name, allowing for typos ("Carlise",
    "Carslie" and "Carlisle")."""
    return a == b or (len(a) >= 4 and len(b) >= 4 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.8)


def _words(text):
    return re.findall(r'[a-z0-9#]+', (text or '').lower())


def fuzzy_has(phrase, text):
    """Every word of phrase (bar "the") shows up in text, typos allowed."""
    want = [t for t in _words(phrase) if t not in ('the', 'at', 'of')]
    have = _words(text)
    return bool(want) and all(any(_tok_match(w, h) for h in have) for w in want)


def place_score(name, label):
    """How much of a place name ("The Carlise") a property address covers."""
    want = list(name_tokens(name))
    have = _words(label)
    if not want or not have:
        return 0.0
    return round(sum(1 for w in want if any(_tok_match(w, h) for h in have)) / len(want), 2)


def search_clients(name, limit=8):
    """Jobber clients that could be the one on a document, best first. A
    vendor often names the community, which in Jobber is a property of a
    management or landscape company (The Carlisle is a Greenscapes property),
    so property addresses count as much as client names; matching_properties
    lists the client's properties that fit."""
    q_terms = [name]
    toks = sorted(name_tokens(name), key=len, reverse=True)
    if toks:
        q_terms.append(toks[0])
        if len(toks[0]) >= 6:
            q_terms.append(toks[0][:5])  # a misspelt name still finds "Carli..."
    found = {}
    spec = ['id', 'name', 'isLead', 'isArchived', 'jobberWebUri', ('billingAddress', ['street1', 'city']),
            ('properties', ['id', _ADDR])]
    for term in q_terms:
        if not term:
            continue
        def make(fields):
            return f'query($q: String!) {{ clients(searchTerm: $q, first: 15) {{ nodes {{ {fields} }} }} }}'
        try:
            data, spec = _gql_tolerant(make, spec, {'q': term}, required=('id', 'name'))
        except JobberError:
            if ('properties', ['id', _ADDR]) in spec:
                spec = [f for f in spec if f != ('properties', ['id', _ADDR])]
                try:
                    data, spec = _gql_tolerant(make, spec, {'q': term}, required=('id', 'name'))
                except JobberError:
                    if found:
                        break
                    raise
            elif found:
                break
            else:
                raise
        for n in (data.get('clients') or {}).get('nodes') or []:
            if n.get('isArchived'):
                continue
            props = n.get('properties') or []
            if isinstance(props, dict):
                props = props.get('nodes') or []
            plist = [{'id': p['id'], 'label': _prop_label(p), 'score': place_score(name, _prop_label(p))}
                     for p in props if p and p.get('id')]
            matching = [p for p in plist if p['score'] >= 0.99]
            # A lead is a prospect, not who we bill.
            score = max(similarity(name, n.get('name') or ''), 0.95 if matching else 0) \
                - (0.25 if n.get('isLead') else 0)
            if n['id'] not in found or found[n['id']]['score'] < score:
                found[n['id']] = {'id': n['id'], 'name': n.get('name'), 'is_lead': bool(n.get('isLead')),
                                  'uri': n.get('jobberWebUri'), 'score': round(score, 2),
                                  'matching_properties': matching,
                                  'address': ', '.join(x for x in [(n.get('billingAddress') or {}).get('street1'),
                                                                   (n.get('billingAddress') or {}).get('city')] if x)}
        if any(v['score'] >= 0.85 for v in found.values()):
            break
    return sorted(found.values(), key=lambda v: -v['score'])[:limit]


# ── account-specific site names ──────────────────────────────────────────────

def site_aliases(conn=None):
    own = conn is None
    conn = conn or _conn()
    try:
        return [dict(r) for r in conn.execute('SELECT * FROM pump_site_aliases ORDER BY place, area')]
    finally:
        if own:
            conn.close()


def _doc_hay(doc, case=None):
    """Everything on a document that can name the site: the RE: line, the
    file name ("Carslie Back Station.docx"), the email subject, the site."""
    case = case or {}
    return ' '.join(str(x or '') for x in (doc.get('client_name'), doc.get('file_name'), doc.get('email_subject'),
                                            doc.get('site'), case.get('client_name'), case.get('site')))


def match_site_alias(doc, case=None, conn=None):
    """The office's own name for a site that fits this document, most specific
    first ("Carlisle" + "back station" beats "Carlisle")."""
    hay = _doc_hay(doc, case)
    named = doc.get('client_name') or (case or {}).get('client_name') or ''
    best = None
    for a in site_aliases(conn):
        if not fuzzy_has(a['place'], hay):
            continue
        if a['area'] and not fuzzy_has(a['area'], hay):
            continue
        # "Miramar Lakes Beach Club" is a different client from "Miramar
        # Lakes": the name on the document may not add words of its own.
        mine = [w for w in _words(f"{a['place']} {a['area']}")]
        extra = [w for w in _words(named) if w not in ('the', 'at', 'of', 'and', 'a', '-', '@')
                 and not any(_tok_match(w, m) for m in mine)]
        if extra and not a.get('any_name'):
            continue
        if a.get('not_with') and any(fuzzy_has(w.strip(), hay) for w in a['not_with'].split(',') if w.strip()):
            continue
        rank = (1 if a['area'] else 0, 1 if a['property_id'] else 0)
        if best is None or rank > best[0]:
            best = (rank, a)
    return best[1] if best else None


def resolve_quote_target(doc, case=None):
    """Which Jobber client and property a vendor quote is for. Returns the ids
    found (either may be None when a person has to choose), how, and the
    choices."""
    case = case or {}
    out = {'client_id': None, 'client_name': '', 'property_id': None, 'property_label': '', 'how': '',
           'candidates': [], 'properties': []}
    j = case.get('jobber') if isinstance(case.get('jobber'), dict) else json.loads(case.get('jobber') or '{}')
    item_client = (j.get('client') or {}).get('id') or case.get('jobber_client_id')
    if item_client:
        out.update(client_id=item_client, how='the item')
        if case.get('jobber_property_id'):
            out.update(property_id=case['jobber_property_id'])
            # Still the maintenance job's property when the client has one
            # (an earlier quote may have gone on the billing address).
            return _prefer_maintenance_property(out, doc, case)
    alias = match_site_alias(doc, case)
    if alias and (not item_client or item_client == alias['client_id']):
        out.update(client_id=alias['client_id'], client_name=alias['client_name'],
                   how=f'site name "{alias["place"]}{" " + alias["area"] if alias["area"] else ""}"')
        if alias['property_id']:
            out.update(property_id=alias['property_id'], property_label=alias['property_label'])
            # A remembered property that isn't the maintenance job's (Autumn
            # Woods: a home picked by hand once) gives way to the job's.
            return _prefer_maintenance_property(out, doc, case)
    name = doc.get('client_name') or case.get('client_name') or ''
    matching = []
    if not out['client_id'] and name:
        cands = search_clients(name)
        out['candidates'] = cands
        pick = pick_client(cands)
        if pick:
            out.update(client_id=pick['id'], client_name=pick['name'], how=f'Jobber search for "{name}"')
            matching = pick.get('matching_properties') or []
    if out['client_id']:
        cj = client_jobs(out['client_id'])
        props = cj['properties']
        out['properties'] = props
        if not out['client_name']:
            out['client_name'] = next((c['name'] for c in out['candidates'] if c['id'] == out['client_id']), '')
        pick = None
        if len(props) == 1:
            pick = props[0]
        else:
            fits = [p for p in props if (matching and p['id'] in {m['id'] for m in matching})
                    or (name and place_score(name, p['label']) >= 0.99)] or props
            site = ' '.join(x for x in (doc.get('site'), case.get('site')) if x)
            if site:
                narrowed = [p for p in fits if fuzzy_has(site, p['label'])]
                fits = narrowed or fits
            by_pump = _pump_number_property(props, f"{_doc_hay(doc, case)} {doc.get('description') or ''}")
            if by_pump and len(fits) != 1:
                fits = [by_pump]
            # The office's rule (Oct 2026, Anna's Place): a pump quote goes on
            # the property of the client's recurring maintenance job ("Quarterly
            # 400") - not the billing address or another of their properties.
            # Several (Huntington: a job per pump) - the pump the vendor names,
            # else the first; the quote says which pump.
            maint = maintenance_properties(cj['jobs'] + recurring_jobs(out['client_id']), props)
            if maint and not (by_pump and by_pump['id'] in {p['id'] for p in maint}):
                fits = maint[:1]
                out['how'] = (out['how'] + '; ' if out['how'] else '') + 'the maintenance job\'s property'
            if len(fits) == 1:
                pick = fits[0]
        if pick:
            out.update(property_id=pick['id'], property_label=pick['label'])
    return out


def _prefer_maintenance_property(out, doc, case):
    """out with its property swapped for the client's recurring maintenance
    job's property when it isn't one (the pump the vendor names, else the
    first). out unchanged when the client has none or Jobber won't say."""
    try:
        cj = client_jobs(out['client_id'])
    except JobberError:
        return out
    maint = maintenance_properties(cj['jobs'] + recurring_jobs(out['client_id']), cj['properties'])
    if maint and out['property_id'] not in {p['id'] for p in maint}:
        pick = _pump_number_property(maint, f"{_doc_hay(doc, case)} {doc.get('description') or ''}") or maint[0]
        out.update(property_id=pick['id'], property_label=pick['label'], properties=cj['properties'],
                   how=f"{out['how']}; the maintenance job's property")
    return out


def recurring_jobs(client_id):
    """The client's recurring jobs, asked for as such: a big client (Autumn
    Woods HOA) has far more jobs than the first 40 client_jobs() sees, and
    their "Monthly 3605" may not be among them. [] when Jobber won't say."""
    for args in ('first: 50, filter: {jobType: RECURRING}', 'first: 100'):
        try:
            data = jobber_gql(f'query($id: EncodedId!) {{ client(id: $id) {{ id jobs({args}) {{ nodes {{ '
                              'id jobNumber title jobStatus jobType createdAt property { id address { street1 street2 city } } } } } }',
                              {'id': client_id})
        except JobberError:
            continue
        c = data.get('client') or {}
        nodes = (next((v for k, v in c.items() if k.startswith('jobs')), None) or {}).get('nodes') or []
        return [{'id': j['id'], 'number': j.get('jobNumber'), 'title': j.get('title') or '',
                 'status': (j.get('jobStatus') or '').lower(), 'type': (j.get('jobType') or '').lower(),
                 'property_id': (j.get('property') or {}).get('id'), 'created': (j.get('createdAt') or '')[:10],
                 'property_label': _prop_label(j.get('property'))}
                for j in nodes if (j.get('jobType') or '').lower() == 'recurring']
    return []


def maintenance_properties(jobs, props):
    """The properties of a client's live recurring maintenance jobs, pump
    ones ("Quarterly 400", "Quarterly Pump Maintenance") first."""
    live = [j for j in jobs if j.get('type') == 'recurring' and j.get('status') != 'archived' and j.get('property_id')]
    live.sort(key=lambda j: (not (TITLE_PATTERNS['pump'].search(j.get('title') or '') or
                                  re.search(r'quarterly|maint', j.get('title') or '', re.I)),
                             -(int(j.get('number') or 0))))
    by_id = {p['id']: p for p in props}
    out = []
    for j in live:
        # A big client's property list may leave out the job's property: the
        # job says what it is.
        p = by_id.get(j['property_id']) or ({'id': j['property_id'], 'label': j['property_label']}
                                             if j.get('property_label') else None)
        if p and p not in out:
            out.append(p)
    return out


def pump_named(doc):
    """The one pump the vendor's quote is about ("check valve on pump #4",
    "RE: Huntington #6"), or ''."""
    text = ' '.join([doc.get('client_name') or '', doc.get('site') or '', doc.get('description') or '']
                    + [f"{i.get('name') or ''} {i.get('description') or ''}" for i in doc.get('line_items') or []])
    nums = {m.group(1) or m.group(2) for m in re.finditer(
        r'(?<![\w/])#\s*(\d{1,2})\b|\bpump\s*(?:station\s*)?(?:no\.?\s*|#\s*)?(\d{1,2})\b', text, re.I)}
    return next(iter(nums)) if len(nums) == 1 else ''


def _pump_number_property(props, text):
    """The property labelled with the pump number the vendor names ("RE:
    Huntington #6", "#6 pump station") - "... Lane Pump #6" in Jobber."""
    nums = {m.group(1) or m.group(2) for m in re.finditer(
        r'#\s*(\d{1,2})\b|\bpump\s*(?:station\s*)?(?:no\.?\s*|#\s*)?(\d{1,2})\b', text or '', re.I)}
    hits = [p for p in props for n in nums
            if re.search(rf'\bpump\s*(?:station\s*)?(?:no\.?\s*|#\s*)?{n}\b', p.get('label') or '', re.I)]
    return hits[0] if len({p['id'] for p in hits}) == 1 else None


def save_site_alias(place, area, client_id, client_name, property_id, property_label, note, actor,
                    job_id='', job_label=''):
    place, area = (place or '').strip()[:80], (area or '').strip()[:80]
    if not place or not client_id:
        raise ValueError('A site name needs the name as written and the Jobber client')
    conn = _conn()
    try:
        conn.execute('''INSERT INTO pump_site_aliases (place, area, client_id, client_name, property_id,
                          property_label, note, created_by, created_at, job_id, job_label)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(place, area) DO UPDATE SET client_id=excluded.client_id,
                          client_name=excluded.client_name, property_id=excluded.property_id,
                          property_label=excluded.property_label, note=excluded.note,
                          created_by=excluded.created_by, created_at=excluded.created_at,
                          job_id=excluded.job_id, job_label=excluded.job_label''',
                     (place, area, client_id, client_name or '', property_id or '', property_label or '',
                      (note or '')[:300], actor, _now_text(), job_id or '', job_label or ''))
        said = f'{place} {area}'.strip()
        _event(conn, actor, 'site name saved', f'"{said}" -> {client_name} {property_label}'.strip())
        conn.commit()
    finally:
        conn.close()


def remember_choice(doc, client_id, client_name='', property_id='', property_label='', actor='system'):
    """The office picked this Jobber client for a vendor's name (Wettech still
    writes "Lee Memorial" for what is now Hodges Funeral Home): remember it, so
    every later quote, bill and report with that name goes there by itself.
    Renamed on the document: remembered under the vendor's name too."""
    orig = (doc.get('orig_client_name') or '').strip()
    if orig and orig != (doc.get('client_name') or '').strip():
        remember_choice({**doc, 'client_name': orig, 'orig_client_name': ''}, client_id, client_name, property_id,
                        property_label, actor)
    place = re.sub(r'\s+', ' ', (doc.get('client_name') or '').strip())[:80]
    if not place or not client_id:
        return None
    a = match_site_alias({'client_name': place})
    if a and a['client_id'] == client_id and (a['property_id'] or not property_id):
        return None
    if not client_name:
        try:
            client_name = (client_jobs(client_id).get('client') or {}).get('name') or ''
        except JobberError:
            client_name = ''
    if not a and client_name and similarity(place, client_name) >= 0.85:
        return None   # the vendor's name is the client's own name - nothing to learn
    save_site_alias(place, '', client_id, client_name, property_id or '', property_label or '',
                    f'Picked by {actor} on {_today().isoformat()}', actor)
    return place


def pick_client(candidates):
    """The one clear match, or None when a person has to choose."""
    if not candidates:
        return None
    top = candidates[0]
    second = candidates[1]['score'] if len(candidates) > 1 else 0
    return top if top['score'] >= 0.8 and top['score'] - second >= 0.1 - 1e-9 else None


def client_jobs(client_id):
    """The client's properties and recent jobs, for choosing where a report note goes."""
    def make(fields):
        return f'query($id: EncodedId!) {{ client(id: $id) {{ {fields} }} }}'
    jobs_spec = ('jobs(first: 40)', [('nodes', ['id', 'jobNumber', 'title', 'jobStatus', 'jobType', 'createdAt',
                                                'jobberWebUri', ('property', ['id'])])])
    # Client.properties is a plain list in the API versions we know of; the
    # other shapes are tried in case Jobber changes it.
    variants = [['id', 'name', ('properties', ['id', _ADDR]), jobs_spec],
                ['id', 'name', ('properties', [('nodes', ['id', _ADDR])]), jobs_spec],
                ['id', 'name', jobs_spec],
                ['id', 'name', ('properties', ['id', _ADDR])],
                ['id', 'name']]
    data, last_err = None, None
    for spec in variants:
        try:
            data, _ = _gql_tolerant(make, spec, {'id': client_id}, required=('id', 'name', 'properties', 'nodes'))
            break
        except JobberError as e:
            last_err = e
    if data is None:
        raise last_err or JobberError('Could not read the client from Jobber')
    c = data.get('client') or {}
    raw_props = c.get('properties') or []
    if isinstance(raw_props, dict):
        raw_props = raw_props.get('nodes') or []
    props = [{'id': p['id'], 'label': _prop_label(p)} for p in raw_props if p]
    jobs = [{'id': j['id'], 'number': j.get('jobNumber'), 'title': j.get('title') or '',
             'status': (j.get('jobStatus') or '').lower(), 'type': (j.get('jobType') or '').lower(),
             'property_id': (j.get('property') or {}).get('id'), 'uri': j.get('jobberWebUri'),
             'created': (j.get('createdAt') or '')[:10]}
            for j in ((c.get('jobs(first: 40)') or c.get('jobs') or {}).get('nodes') or [])]
    if not jobs:
        conn = _conn()
        try:
            jobs = [{'id': r['jobber_id'], 'number': r['number'], 'title': r['title'], 'status': r['status'],
                     'type': r['job_type'], 'property_id': r['property_id'], 'uri': r['web_uri'],
                     'created': (r['created_at'] or '')[:10]}
                    for r in conn.execute("SELECT * FROM pump_jobber_items WHERE kind='job' AND client_id=? "
                                          "ORDER BY created_at DESC LIMIT 40", (client_id,))]
        finally:
            conn.close()
    return {'client': {'id': c.get('id'), 'name': c.get('name')}, 'properties': props, 'jobs': jobs}


def best_job_for_report(jobs, properties, location, title):
    """The pump's job: a live pump job at the property named in the report
    (e.g. "Pump #2", "Fountain"), preferring the recurring maintenance job."""
    loc = (location or '').lower()
    prop_ids = {p['id'] for p in properties if loc and any(t in p['label'].lower() for t in re.findall(r'[a-z0-9#]+', loc) if len(t) > 2)}
    # A finished one-off job is never where this month's report goes (Cypress
    # Legends, Oct 2026: archived "Service Call - Wttech PO243" beat "Quarterly 500").
    jobs = [j for j in jobs if not (j.get('type') != 'recurring' and j.get('status') == 'archived')]

    def score(j):
        s = 0
        t = (j['title'] or '').lower()
        if TITLE_PATTERNS['pump'].search(t) or re.search(r'\b(?:quarterly|monthly|maint\w*|annual|semi-?annual)\b', t):
            s += 3
        if loc and any(w in t for w in re.findall(r'[a-z0-9#]+', loc) if len(w) > 2):
            s += 2
        if j.get('property_id') in prop_ids:
            s += 2
        if j.get('type') == 'recurring' and j.get('status') not in ('archived',):
            s += 3
        if j.get('status') in ('active', 'upcoming', 'today', 'late'):
            s += 1
        return (s, j.get('created') or '')
    ranked = sorted(jobs, key=score, reverse=True)
    if len(ranked) > 1 and score(ranked[0])[0] == score(ranked[1])[0]:
        return None   # two jobs fit as well (Honda: "Monthly 180" and "Quarterly 300") - a person picks
    return ranked[0] if ranked and score(ranked[0])[0] >= 3 else None


# Typing slips in vendor letters that would otherwise go to the client
# (Homewood Suites, Oct 2026: "check out well nor pumping").
_TYPOS = (
    (re.compile(r'\bnor(\s+(?:pumping|running|working|starting|holding|pulling|draining|operating|'
                r'responding|turning|coming|getting|keeping|building|making|reaching|cycling|shutting|'
                r'priming|charging|reading|communicating|functioning)\b)', re.I), r'not\1'),
    (re.compile(r'\bteh\b', re.I), 'the'),
    (re.compile(r'\b(the|a|an|and|to|of|on|in|with|for) \1\b', re.I), r'\1'),   # "the the"
    (re.compile(r'[ \t]{2,}'), ' '),
)


def fix_typos(text):
    """(text with the known typing slips corrected, [what was changed])."""
    changes = []
    for pat, good in _TYPOS:
        def sub(m, good=good):
            new = m.expand(good)
            if new != m.group(0) and new.strip():
                changes.append(f'"{m.group(0).strip()}" -> "{new.strip()}"')
            return new
        text = pat.sub(sub, text or '')
    return text, changes


def one_line_items(doc, markup_pct, whole=False):
    """Our quotes and invoices are always one "Service Proposal Amount" line:
    the vendor's work described (without their name), priced at their total
    before tax plus the markup. A price that already includes the vendor's
    sales tax stays not taxable. whole: marked-up prices in whole dollars, the
    cents dropped ($2,215.80 -> $2,215), as our client quotes go (Oct 2026)."""
    def up(a):
        v = a * (1 + (markup_pct or 0) / 100)
        return float(math.floor(v + 1e-9)) if whole and markup_pct else round(v, 2)
    every = [it for it in (doc.get('line_items') or []) if not it.get('is_tax')]
    lines = [it for it in every if not it.get('optional')]
    options = [it for it in every if it.get('optional')]
    descs = []
    for it in lines:
        d = _strip_vendor((it.get('description') or it.get('name') or '').strip())
        if d and d not in descs:
            descs.append(d)
    if not descs and doc.get('description'):
        descs = [_strip_vendor(doc['description'].split('\n')[0])]
    def amt(it):
        if it.get('amount') is not None:
            return it['amount']
        if it.get('unit_price') is not None:
            return it['unit_price'] * (it.get('quantity') or 1)
        return None
    known = [amt(it) for it in lines if amt(it) is not None]
    if doc.get('subtotal') is not None:
        base, taxable = doc['subtotal'], any(it.get('taxable', True) for it in lines) if lines else True
    elif known:
        base, taxable = sum(known), doc.get('total') is None and any(it.get('taxable', True) for it in lines)
    elif doc.get('total') is not None:
        base, taxable = doc['total'], False
    else:
        return []
    priced = [it for it in lines if it.get('own_price') and amt(it) is not None]
    if len(priced) >= 2 and len(priced) == len(lines):
        # A letter quoting several pieces of work, each at its own price
        # (Lely, Oct 2026): a line each, so the client sees what each costs.
        out = [{'name': 'Service Proposal Amount', 'description': _strip_vendor(it.get('description') or '')[:2000],
                'quantity': 1, 'unit_price': up(amt(it)),
                'taxable': bool(it.get('taxable', taxable))} for it in priced]
    else:
        out = [{'name': 'Service Proposal Amount', 'description': '\n'.join(descs)[:2000], 'quantity': 1,
                'unit_price': up(base), 'taxable': bool(taxable)}]
    # Work the vendor quoted as "possibly needed": its own optional line,
    # marked up the same, not in the quote's total.
    for it in options:
        a = amt(it)
        if a is None:
            continue
        out.append({'name': 'Optional', 'description': _strip_vendor(it.get('description') or '')[:2000],
                    'quantity': 1, 'unit_price': up(a),
                    'taxable': bool(it.get('taxable', taxable)), 'optional': True})
    return out


JOB_DETAIL_SPEC = ['id', 'jobNumber', 'title', 'instructions', 'jobStatus', 'jobType', 'jobberWebUri', 'total',
                   ('property', ['id', _ADDR]),
                   ('lineItems', [('nodes', ['name', 'description', 'quantity', 'unitPrice', 'taxable'])])]
_MATCH_STOP = {'with', 'will', 'need', 'needs', 'that', 'this', 'from', 'have', 'been', 'were', 'they', 'their',
               'pump', 'pumps', 'service', 'services', 'field', 'proposal', 'amount', 'quote', 'pleased', 'following',
               'customer', 'repair', 'repairs', 'call', 'labor', 'materials', 'work', 'completed', 'install', 'test'}


def job_detail(job_id):
    def make(fields):
        return f'query($id: EncodedId!) {{ job(id: $id) {{ {fields} }} }}'
    data, _ = _gql_tolerant(make, JOB_DETAIL_SPEC, {'id': job_id}, required=('id',))
    j = data.get('job') or {}
    lines = (j.get('lineItems') or {}).get('nodes') if isinstance(j.get('lineItems'), dict) else (j.get('lineItems') or [])
    return {'id': j.get('id'), 'number': str(j.get('jobNumber') or ''), 'title': j.get('title') or '',
            'instructions': j.get('instructions') or '', 'status': (j.get('jobStatus') or '').lower(),
            'type': (j.get('jobType') or '').lower(), 'uri': j.get('jobberWebUri') or '', 'total': j.get('total'),
            'property_label': _prop_label(j.get('property')),
            'line_items': [{'name': li.get('name') or '', 'description': li.get('description') or '',
                            'quantity': li.get('quantity') or 1, 'unit_price': li.get('unitPrice'),
                            'taxable': bool(li.get('taxable'))} for li in lines or [] if li.get('unitPrice') is not None]}


def _match_words(text):
    return {w for w in re.findall(r'[a-z]{4,}', (text or '').lower()) if w not in _MATCH_STOP}


def find_matching_job(doc, client_id):
    """The client's Jobber job this vendor bill is for: a one-off job that
    still needs invoicing (or is under way) whose title, instructions and
    lines share the bill's words - "Lee Memorial Well 6 ... after making
    repairs to get pump running" on both. None unless one job is clearly it."""
    if not client_id:
        return None
    jobs = [j for j in client_jobs(client_id)['jobs'] if j.get('type') != 'recurring' and
            j.get('status') in ('requires_invoicing', 'action_required', 'active', 'late', 'today', 'upcoming',
                                'unscheduled')]
    if not jobs:
        return None
    bill = ' '.join([doc.get('client_name') or '', doc.get('site') or '', doc.get('description') or ''] +
                    [f"{li.get('name') or ''} {li.get('description') or ''}" for li in doc.get('line_items') or []])
    want = _match_words(bill)
    scored = []
    for j in jobs[:12]:
        try:
            d = job_detail(j['id'])
        except JobberError:
            continue
        have = _match_words(' '.join([d['title'], d['instructions'], d['property_label']] +
                                     [f"{li['name']} {li['description']}" for li in d['line_items']]))
        common = len(want & have)
        score = common / max(4, min(len(want), 12)) + (0.25 if d['status'] == 'requires_invoicing' else 0)
        scored.append((round(score, 3), common, d))
    scored.sort(key=lambda x: -x[0])
    if not scored or scored[0][1] < 2 or scored[0][0] < 0.45:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.15:
        return None
    return {**scored[0][2], 'score': scored[0][0]}


def gov_client(doc=None, case=None):
    """The government client name this work is for (Sarasota County), or ''."""
    case = case or {}
    j = json.loads(case.get('jobber') or '{}') if isinstance(case.get('jobber'), str) else (case.get('jobber') or {})
    for name in ((j.get('client') or {}).get('name'), case.get('client_name'), (doc or {}).get('client_name'),
                 case.get('title')):
        if name and GOV_CLIENTS.search(name):
            return name
    return ''


def _ref(prefix, value):
    """'PO', '# 260904' -> 'PO260904' (a number already starting with PO keeps it once)."""
    value = re.sub(rf'^\s*{prefix}\s*#?\s*', '', (value or '').strip(), flags=re.I)
    return f'{prefix}{value}' if value else ''


def _usd(x):
    return f'${x:,.2f}'


def gov_line_items(doc, case=None):
    """Sarasota County's way (invoice 36176): one PUMP SERVICE line -
    "WO2135661  PO 260904", the work, then Subcontractor Cost / Vendor 10%
    Markup / Total Cost - not taxable."""
    case = case or {}
    plain = one_line_items(doc, 0)
    main = [it for it in plain if not it.get('optional')]
    if not main:
        return []
    cost = round(sum(it['unit_price'] for it in main), 2)
    mark = round(cost * GOV_MARKUP_PCT / 100, 2)
    pump = pump_named(doc)
    wo = (case.get('wo_number') or '').strip()
    po = (case.get('po_number') or doc.get('po_number') or '').strip()
    refs = '  '.join(x for x in (_ref('WO', wo), _ref('PO', po)) if x)
    work = '\n\n'.join(it['description'] for it in main if it.get('description'))
    desc = '\n'.join(x for x in (f'Pump #{pump}' if pump else '', refs) if x)
    desc = (desc + '\n\n' if desc else '') + work + (
        f"\n\nSubcontractor Cost: {_usd(cost)}\nVendor {GOV_MARKUP_PCT:g}% Markup: {_usd(mark)}\n"
        f"Total Cost: {_usd(cost + mark)}")
    out = [{'name': 'PUMP SERVICE', 'description': desc[:2000], 'quantity': 1, 'unit_price': round(cost + mark, 2),
            'taxable': False}]
    for it in plain:
        if it.get('optional'):
            out.append({**it, 'unit_price': round(it['unit_price'] * (1 + GOV_MARKUP_PCT / 100), 2), 'taxable': False})
    return out


def gov_missing_refs(case):
    """What the county needs on the invoice that this job doesn't have yet."""
    return [label for key, label in (('wo_number', 'WO #'), ('po_number', 'PO #'))
            if not ((case or {}).get(key) or '').strip()]


def _gov_refs_todo(case, who):
    missing = gov_missing_refs(case)
    if not missing or not case.get('id'):
        return
    conn = _conn()
    try:
        add_todo(conn, f"gov-refs:{case['id']}", f"Get {who}'s {' and '.join(missing)} for {case.get('title') or 'this job'}",
                 f"{who} needs its work order # and PO # on the invoice. Put them on the job (Details: PO #, W/O #) "
                 f"and on the Jobber invoice before it goes out.", {'case_id': case['id']})
        conn.commit()
    finally:
        conn.close()


def suggest_invoice(doc, case=None):
    """Our invoice for a vendor bill when there is no client quote to copy:
    one Service Proposal Amount line, the bill before tax plus the quote
    markup (30%). Jobber adds the client's tax itself."""
    gov = gov_client(doc, case)
    if gov:
        po = ((case or {}).get('po_number') or doc.get('po_number') or '').strip()
        _gov_refs_todo(case or {}, gov)
        return {'subject': ('Invoice-' + _ref('PO', po) if po else 'Invoice')[:255],
                'line_items': gov_line_items(doc, case), 'markup_pct': GOV_MARKUP_PCT, 'gov': gov}
    items = one_line_items(doc, QUOTE_MARKUP_PCT)
    where = (case or {}).get('client_name') or doc.get('client_name') or ''
    subject = f"Pump service - {where}" if where else 'Pump service'
    if (case or {}).get('po_number') or doc.get('po_number'):
        subject += f" (PO {(case or {}).get('po_number') or doc.get('po_number')})"
    return {'subject': subject[:255], 'line_items': items, 'markup_pct': QUOTE_MARKUP_PCT}


def _strip_vendor(text):
    """Our invoice should not name the sub."""
    for v in pump_reports.load_vendors():
        pat = pump_reports._phrase_pattern(v.get('names', []))
        if pat:
            text = pat.sub('', text)
    text = re.sub(r'\s*as per (?:the )?quot(?:e|ation)\.?', '', text, flags=re.I)
    return re.sub(r'\s{2,}', ' ', text).strip(' ,.-') + ('.' if text.strip().endswith('.') else '')


def _jobber_lines(line_items, what):
    """Line items as Jobber takes them. Nothing is saved to Products & Services."""
    items = []
    for it in line_items or []:
        name = (it.get('name') or '').strip()
        if not name:
            continue
        qty = float(it.get('quantity') or 1)
        price = _money(it.get('unit_price'))
        if price is None or qty <= 0:
            continue
        items.append({'name': name[:255], 'description': (it.get('description') or '')[:2000],
                      'quantity': qty, 'unitPrice': price, 'taxable': bool(it.get('taxable', True)),
                      'saveToProductsAndServices': False, **({'optional': True} if it.get('optional') else {})})
    if not items:
        raise ValueError(f'No line items to put on the {what}')
    return items


_LONG_LEAD = re.compile(r'\b(?:weeks?|wks?|months?)\b', re.I)
_DELIVERY = re.compile(r'\b(?:deliver(?:y|ed)?|lead\s*time|ship(?:s|ping|ped)?|arrive|in\s+stock)\b', re.I)


def delivery_note(doc):
    """The vendor's delivery time when it is weeks or months away (Lely, Oct
    2026: "Delivery: 2-3 weeks after receipt of order") - the client is told
    on our quote: "It will take 2-3 weeks to deliver after approval". A few days isn't worth saying. '' when there is none."""
    text = doc.get('text_excerpt') or ''
    if not text and doc.get('file_path'):
        try:
            with open(doc['file_path'], 'rb') as f:
                text = extract_text(doc.get('file_name') or '', f.read())[:4000]
        except (OSError, TypeError, ValueError):
            text = ''
    return _delivery_in(text)


def _delivery_in(text):
    for line in re.split(r'\n|(?<=\.)\s+', text):
        line = re.sub(r'\s+', ' ', line).strip()
        if _LONG_LEAD.search(line) and _DELIVERY.search(line) and len(line) <= 200:
            # Said the client's way: from their approval (our order to the vendor).
            m = re.search(r'(\d+\s*(?:-|–|to)\s*\d+|\d+|a\s+few|several)\s*(weeks?|wks?|months?)', line, re.I)
            if m:
                unit = {'wk': 'weeks', 'wks': 'weeks'}.get(m.group(2).lower(), m.group(2).lower())
                if m.group(1).strip() == '1' and unit.startswith(('week', 'month')):
                    unit = unit.rstrip('s')
                span = re.sub(r'\s*(?:-|–)\s*', '-', m.group(1).strip())
                return f'It will take {span} {unit} to deliver after approval.'
            return line if re.match(r'(?i)delivery\b', line) else f'Delivery: {line}'
    return ''


def parts_lead_in(text):
    """"2-3 weeks" when the text says delivery takes weeks or months, else ''."""
    m = re.search(r'(\d+\s*(?:-|–|to)\s*\d+|\d+|a\s+few|several)\s*(weeks?|wks?|months?)', _delivery_in(text or ''), re.I)
    if not m:
        return ''
    unit = {'wk': 'weeks', 'wks': 'weeks'}.get(m.group(2).lower(), m.group(2).lower())
    span = re.sub(r'\s*(?:-|–|to)\s*', '-', m.group(1).strip())
    if span == '1':
        unit = unit.rstrip('s')
    return f'{span} {unit}'


def suggest_quote(doc, case=None):
    """Our quote to the client, the way the office writes them (Jobber quote
    9136): the vendor's price plus QUOTE_MARKUP_PCT, no vendor name or sales
    tax line, a single-price quote as one "Service Proposal Amount" line
    carrying the vendor's description of the work, titled "Proposal to ...".
    A price that already includes the vendor's tax stays not taxable."""
    gov = gov_client(doc, case)
    items = gov_line_items(doc, case) if gov else one_line_items(doc, QUOTE_MARKUP_PCT, whole=True)
    words = ' '.join([doc.get('description') or ''] + [f"{i.get('name') or ''} {i.get('description') or ''}"
                                                       for i in doc.get('line_items') or []])
    markup = GOV_MARKUP_PCT if gov else QUOTE_MARKUP_PCT
    if is_scada_renewal(words):
        # SCADA is not marked up: each client pays their price from the SCADA tab.
        conn = _conn()
        try:
            rows = [dict(r) for r in conn.execute('SELECT * FROM pump_scada_accounts WHERE active=1')]
        finally:
            conn.close()
        row = _scada_match(rows, (case or {}).get('client_name') or doc.get('client_name') or '', words)
        price = _money(row.get('our_bill')) if row else None
        if price:
            desc = items[0]['description'] if items else ''
            items = [{'name': 'Service Proposal Amount', 'description': desc, 'quantity': 1, 'unit_price': price,
                      'taxable': False}]
            markup = 0
    # Typing slips in the vendor's letter don't go to the client.
    corrections = []
    for it in items:
        it['description'], ch = fix_typos(it.get('description') or '')
        corrections += [c for c in ch if c not in corrections]
    title = (doc.get('proposal_title') or '').strip() or _proposal_title(
        items[0]['description'] if items else (doc.get('description') or ''))
    title, ch = fix_typos(title)
    corrections += [c for c in ch if c not in corrections]
    pump = pump_named(doc)
    if pump and not re.search(rf'#\s*{pump}\b|pump\s*{pump}\b', title, re.I):
        # Which pump, on a property with several (the address alone doesn't say).
        title = f'{title} - Pump #{pump}'
    lead = delivery_note(doc)
    if lead:
        items = [{**it, 'description': f"{it['description']}\n\n{lead}".strip()[:2000]} for it in items]
    return {'title': title[:255], 'line_items': items, 'markup_pct': markup, 'delivery': lead,
            'corrections': corrections}


def _proposal_title(work):
    """"Field service to check out pump station ... Field service to pull and
    inspect suction line, clean screen ..." -> "Proposal to pull and inspect
    suction line": the last thing the vendor will do is the repair itself."""
    tasks = re.findall(r'\b(?:service|labor|work|crew)\s+to\s+([^,.;]+)', work or '', re.I)
    if tasks:
        words = tasks[-1].split()
        return 'Proposal to ' + ' '.join(words[:7]).rstrip(' -')
    first = short_name(work or '', 70)
    return f'Proposal - {first}' if first else 'Pump service proposal'


def _quote_note_text(doc, total):
    vendor = doc.get('vendor') or 'Vendor'
    price = doc.get('total') if doc.get('total') is not None else doc.get('subtotal')
    lines = [f"{vendor} quote{' #' + doc['doc_number'] if doc.get('doc_number') else ''}"
             f"{' dated ' + doc['doc_date'] if doc.get('doc_date') else ''}: {doc.get('file_name')}"]
    if price is not None:
        lines.append(f"{vendor} price: ${price:,.2f}" + (' (includes sales tax)' if doc.get('subtotal') is None and
                                                        doc.get('total') is not None else ''))
    base = doc.get('subtotal') if doc.get('subtotal') is not None else price
    pct = round((total / base - 1) * 100) if base else QUOTE_MARKUP_PCT
    lines.append(f'Our price: ${total:,.2f} ({pct:g}% markup). Drafted by the Pumps app.')
    base = (CFG.get('website_url') or '').rstrip('/')
    if base and 'localhost' not in base:
        lines.append(f"File: {base}/pumps#doc-{doc['id']}")
    return '\n'.join(lines)


def _note_attachment(url, file_name, content_type):
    """A note attachment with only the fields this Jobber takes (its
    NoteAttachmentAttributes has no fileName or contentType - Oct 2026)."""
    try:
        have = {f['name'] for f in (_type_fields('NoteAttachmentAttributes').get('inputFields') or [])}
    except JobberError:
        have = set()
    att = {'url': url}
    for keys, value in ((('fileName', 'name', 'filename'), file_name), (('contentType', 'mimeType'), content_type)):
        key = next((k for k in keys if k in have), None)
        if key and value:
            att[key] = value
    return att


def note_vendor_file(doc, target_type, target_id, text, version='original', file_name=None, content_type=None):
    """A note on a Jobber record with the vendor's own document attached (or
    linked, when Jobber will not take the attachment)."""
    mutation, id_arg, input_type, field = NOTE_MUTATION[target_type]
    q = (f'mutation PumpsVendorNote($id: EncodedId!, $input: {input_type}!) {{ {mutation}({id_arg}: $id, '
         f'input: $input) {{ {field} {{ id }} userErrors {{ message path }} }} }}')
    url = _signed_file_url(doc['id'], version, days=7, name=file_name or os.path.basename(doc.get('file_name') or ''))
    ctype = content_type or ('application/pdf' if (doc.get('file_name') or '').lower().endswith('.pdf') else
                             'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    if url:
        try:
            data = jobber_gql(q, {'id': target_id, 'input': {'message': text, 'attachments': [
                _note_attachment(url, file_name or doc.get('file_name'), ctype)]}})
            payload = data.get(mutation) or {}
            if not payload.get('userErrors'):
                return {'note_id': (payload.get(field) or {}).get('id'), 'attached': True}
        except JobberError as e:
            print(f'  ⚠ Pumps: Jobber would not take the attachment ({e}); saving the note without it')
    data = jobber_gql(q, {'id': target_id, 'input': {'message': text}})
    payload = data.get(mutation) or {}
    if payload.get('userErrors'):
        raise JobberError('Jobber: ' + '; '.join(e.get('message', '?') for e in payload['userErrors']))
    return {'note_id': (payload.get(field) or {}).get('id'), 'attached': False}


def auto_draft_quote(doc_id, actor='Pumps (automatic)'):
    """Draft our client quote in Jobber as soon as a vendor quote is filed,
    when the client and property are clear. Otherwise say on the document what
    a person has to choose. Never raises: the quote still waits in Today."""
    if not AUTO_DRAFT_QUOTES or not jobber_status()['connected']:
        return None
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
        doc = _doc_dict(row) if row else None
        case = dict(conn.execute('SELECT * FROM pump_cases WHERE id=?', (doc['case_id'],)).fetchone()) \
            if doc and doc.get('case_id') else None
    finally:
        conn.close()
    if not doc or not case or doc['kind'] != 'quote' or doc['status'] in ('review', 'dismissed') \
            or (doc.get('jobber') or {}).get('quote_id') \
            or (json.loads(case.get('jobber') or '{}').get('quote') or {}).get('id'):
        return None
    reason, dup = '', None
    try:
        t = resolve_quote_target(doc, case)
        if not t['client_id']:
            reason = f'Choose the Jobber client - no clear match for "{doc.get("client_name") or case.get("client_name")}".'
        elif not t['property_id']:
            reason = f"Choose which {t['client_name'] or 'client'} property this is for."
        else:
            sugg = suggest_quote(doc, case)
            res = create_draft_quote(doc_id, t['client_id'], t['property_id'], sugg['line_items'], sugg['title'],
                                     '', actor)
            return {**res, 'how': t['how']}
    except PossibleDuplicate as e:
        reason, dup = str(e), e.rec
    except (JobberError, ValueError) as e:
        reason = f'Could not draft it automatically: {e}'
    conn = _conn()
    try:
        j = {**(doc.get('jobber') or {}), 'quote_pending': {'reason': reason, 'at': _now_text(),
                                                            **({'possible_duplicate': dup} if dup else {})}}
        conn.execute('UPDATE pump_docs SET jobber=? WHERE id=?', (json.dumps(j), doc_id))
        _event(conn, actor, 'client quote not drafted', reason, case_id=case['id'], doc_id=doc_id)
        conn.commit()
    finally:
        conn.close()
    return {'pending': reason}


def fetch_quote_lines(quote_id):
    """Our client quote's lines from Jobber, as the invoice should repeat them."""
    for lines_spec in ('lineItems { nodes { name description quantity unitPrice taxable optional } } amounts { total }',
                       'lineItems { nodes { name description quantity unitPrice taxable } }',
                       'lineItems { name description quantity unitPrice taxable }'):
        try:
            data = jobber_gql(f'query($id: EncodedId!) {{ quote(id: $id) {{ quoteNumber {lines_spec} }} }}',
                              {'id': quote_id})
        except JobberError:
            continue
        q = data.get('quote') or {}
        raw = q.get('lineItems') or []
        if isinstance(raw, dict):
            raw = raw.get('nodes') or []
        lines = [{'name': li.get('name') or '', 'description': li.get('description') or '',
                  'quantity': li.get('quantity') or 1, 'unit_price': li.get('unitPrice'),
                  'taxable': bool(li.get('taxable')), 'optional': bool(li.get('optional'))}
                 for li in raw if li.get('unitPrice') is not None]
        # Optional work the client didn't take isn't invoiced (Huntington #6 #9160, Oct 2026: the $6,287.97
        # "Optional - if needed" motor went on the invoice). Kept only when the approved total needs it.
        total = _money((q.get('amounts') or {}).get('total'))
        cost = lambda ls: round(sum(float(li['unit_price']) * float(li['quantity'] or 1) for li in ls), 2)
        required = [li for li in lines if not li['optional']]
        if not (total is not None and abs(cost(required) - total) > 1 and abs(cost(lines) - total) <= 1):
            lines = required
        for li in lines:
            li.pop('optional', None)
        return {'number': str(q.get('quoteNumber') or ''), 'line_items': lines, 'total': total}
    return None


def _line_print(lines):
    """What a quote's lines are, to tell later whether someone changed it in
    Jobber: [[name, price], ...] sorted."""
    return sorted([str(li.get('name') or '').strip(), round(float(li.get('unitPrice') or 0), 2)] for li in lines or [])


QUOTE_ADD_LINES = ('quoteCreateLineItems',)
QUOTE_REMOVE_LINES = ('quoteDeleteLineItems',)


def _with_lines(candidates, values):
    """try_mutation, dropping line fields Jobber says it doesn't take."""
    for _ in range(4):
        try:
            return try_mutation(candidates, values, {'quote': 'id'})
        except JobberError as e:
            m = _LINE_FIELD_REFUSED.search(str(e))
            field = m.group(1) if m else next((f for f in ('saveToProductsAndServices', 'taxable', 'optional')
                                               if f in str(e)), None)
            if not field or field in ('name', 'quantity', 'unitPrice') or \
                    not any(field in li for li in values['lineItems']):
                raise
            values = {**values, 'lineItems': [{k: v for k, v in li.items() if k != field}
                                               for li in values['lineItems']]}
    return try_mutation(candidates, values, {'quote': 'id'})


def update_draft_quote(doc_id, actor='Pumps (automatic)'):
    """Our Jobber quote made from this vendor quote, redone from the vendor's
    quote as it reads now - only while it is still a draft. New lines are
    added before the old ones are taken off, so the quote is never empty.
    Returns {'updated': True, ...} or {'note': why it was left alone}."""
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
        doc = _doc_dict(row)
        case = dict(conn.execute('SELECT * FROM pump_cases WHERE id=?', (doc['case_id'],)).fetchone()) \
            if doc.get('case_id') else None
    finally:
        conn.close()
    j = doc.get('jobber') or {}
    qid, num = j.get('quote_id'), j.get('quote_number')
    left = f"Our Jobber quote #{num} was made from the old reading - fix it in Jobber."
    try:
        data = jobber_gql('query($id: EncodedId!) { quote(id: $id) { quoteNumber quoteStatus '
                          'lineItems { nodes { id name unitPrice } } } }', {'id': qid})
    except JobberError as e:
        if not _GONE.search(str(e)):
            return {'note': f'{left} (Jobber: {e})'}
        data = {}
    q = data.get('quote') or {}
    if not q:
        # Deleted in Jobber: forget it, so Draft quote can make a new one.
        conn = _conn()
        try:
            jobber_record_gone(conn, 'quote', qid)
            conn.commit()
        finally:
            conn.close()
        return {'note': f"Our Jobber quote #{num} was deleted in Jobber - click Draft quote to make a new one."}
    status = (q.get('quoteStatus') or '').lower()
    if status != 'draft':
        return {'note': f"Our Jobber quote #{num} is already {status.replace('_', ' ') or 'gone'} - "
                        "fix it in Jobber if the new reading changes it."}
    nodes = (q.get('lineItems') or {}).get('nodes') or []
    if not j.get('quote_lines') or _line_print(nodes) != j['quote_lines']:
        # Made or changed by a person in Jobber (or before the app kept track):
        # theirs - never overwritten.
        return {'note': f"Our Jobber quote #{num} was set up or changed by hand in Jobber, so it was left as it is"
                        " - change it there if the new reading should change it."}
    old_ids = [n['id'] for n in nodes if n.get('id')]
    sugg = suggest_quote(doc, case)
    lines = _jobber_lines(sugg['line_items'], 'quote')
    try:
        added = _with_lines(QUOTE_ADD_LINES, {'quoteId': qid, 'lineItems': lines})
        if added is None:
            return {'note': left}
        removed = _with_lines(QUOTE_REMOVE_LINES, {'quoteId': qid, 'lineItemIds': old_ids, 'lineItems': []}) \
            if old_ids else {}
    except JobberError as e:
        return {'note': f'{left} (Jobber: {e})'}
    total = sum(li['unitPrice'] * li['quantity'] for li in lines if not li.get('optional'))
    conn = _conn()
    try:
        dj = json.loads(conn.execute('SELECT jobber FROM pump_docs WHERE id=?', (doc_id,)).fetchone()[0] or '{}')
        dj['quote_lines'] = _line_print(lines) if removed is not None else None
        conn.execute('UPDATE pump_docs SET jobber=? WHERE id=?', (json.dumps(dj), doc_id))
        cj = json.loads(case.get('jobber') or '{}') if case else {}
        if (cj.get('quote') or {}).get('id') == qid:
            cj['quote']['total'] = round(total, 2)
            conn.execute('UPDATE pump_cases SET jobber=? WHERE id=?', (json.dumps(cj), case['id']))
        msg = (f"Draft quote #{num} in Jobber redone from the new reading: {len(lines)} line(s), "
               f"${total:,.2f}" + ('' if removed is not None else ' - take the old lines off in Jobber'))
        _event(conn, actor, 'quote updated', msg, case_id=doc.get('case_id'), doc_id=doc_id)
        conn.commit()
    finally:
        conn.close()
    return {'updated': True, 'note': msg}


def find_quote_by_number(number):
    """The Jobber quote with this number (e.g. 9136), or None."""
    number = str(number or '').strip().lstrip('#')
    if not number.isdigit():
        raise ValueError('Type the Jobber quote number, e.g. 9136')
    spec = ['id', 'quoteNumber', 'quoteStatus', 'title', 'jobberWebUri', ('amounts', ['total']),
            ('client', ['id', 'name']), ('property', ['id', _ADDR])]

    def make(fields):
        return f'query($q: String!) {{ quotes(searchTerm: $q, first: 20) {{ nodes {{ {fields} }} }} }}'
    data, _ = _gql_tolerant(make, spec, {'q': number}, required=('id', 'quoteNumber'))
    return next((n for n in (data.get('quotes') or {}).get('nodes') or []
                 if str(n.get('quoteNumber') or '') == number), None)


def find_invoice_by_number(number):
    """Our Jobber invoice with this number (e.g. 36806): from the sync, else Jobber."""
    number = str(number or '').strip().lstrip('#')
    if not number.isdigit():
        raise ValueError('Type the Jobber invoice number, e.g. 36806')
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM pump_jobber_items WHERE kind='invoice' AND number=?", (number,)).fetchone()
    finally:
        conn.close()
    if row:
        return {'id': row['jobber_id'], 'invoiceNumber': number, 'invoiceStatus': row['status'] or '',
                'jobberWebUri': row['web_uri'] or '', 'amounts': {'total': row['total']},
                'client': {'id': row['client_id'] or '', 'name': row['client_name'] or ''}}
    spec = ['id', 'invoiceNumber', 'invoiceStatus', 'subject', 'jobberWebUri', ('amounts', ['total']),
            ('client', ['id', 'name'])]

    def make(fields):
        return f'query($q: String!) {{ invoices(searchTerm: $q, first: 20) {{ nodes {{ {fields} }} }} }}'
    data, _ = _gql_tolerant(make, spec, {'q': number}, required=('id', 'invoiceNumber'))
    return next((n for n in (data.get('invoices') or {}).get('nodes') or []
                 if str(n.get('invoiceNumber') or '') == number), None)


def link_jobber_invoice(case_id, number, actor='system'):
    """The client was invoiced straight in Jobber (Enclave @ Palmira, Oct 2026):
    tie that invoice to the job - "Draft invoice" is done, the bill leaves the
    Draft invoice list and can be paid, and the invoice's status is followed."""
    inv = find_invoice_by_number(number)
    if not inv:
        raise ValueError(f'No Jobber invoice #{str(number).lstrip("#")} found')
    num = str(inv.get('invoiceNumber'))
    status = (inv.get('invoiceStatus') or '').lower()
    total = _money((inv.get('amounts') or {}).get('total'))
    client = inv.get('client') or {}
    conn = _conn()
    try:
        row = conn.execute('SELECT jobber FROM pump_cases WHERE id=?', (case_id,)).fetchone()
        if not row:
            raise ValueError('No such item')
        j = json.loads(row['jobber'] or '{}')
        j['invoice'] = {'id': inv['id'], 'number': num, 'uri': inv.get('jobberWebUri') or '', 'status': status,
                        'total': total}
        if client.get('id') and not (j.get('client') or {}).get('id'):
            j['client'] = {'id': client['id'], 'name': client.get('name') or ''}
        conn.execute('UPDATE pump_cases SET jobber=?, sei_invoice_number=?, updated_at=? WHERE id=?',
                     (json.dumps(j), num, _now_text(), case_id))
        for d in conn.execute("SELECT id, jobber FROM pump_docs WHERE case_id=? AND kind='bill' AND status != 'dismissed'",
                              (case_id,)).fetchall():
            dj = json.loads(d['jobber'] or '{}')
            if not dj.get('invoice_id'):
                dj.update(invoice_id=inv['id'], invoice_number=num, invoice_uri=inv.get('jobberWebUri') or '',
                          invoice_status=status, linked_by=actor)
                dj.pop('invoice_pending', None)
                conn.execute("UPDATE pump_docs SET jobber=?, status='done' WHERE id=?", (json.dumps(dj), d['id']))
        conn.execute("INSERT INTO pump_jobber_items (jobber_id, kind, number, status, client_id, client_name, total, "
                     "web_uri, case_id, category, synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                     "ON CONFLICT(jobber_id) DO UPDATE SET case_id=excluded.case_id",
                     (inv['id'], 'invoice', num, status, client.get('id') or '', client.get('name') or '', total,
                      inv.get('jobberWebUri') or '', case_id, 'pump', _now_text()))
        _set_step(conn, case_id, 'invoice_drafted', at=_today().isoformat(), by=actor)
        _event(conn, actor, 'linked Jobber invoice', f"Invoice #{num} ({status or 'status unknown'}"
               f"{', $' + format(total, ',.2f') if total is not None else ''})", case_id=case_id)
        conn.commit()
    finally:
        conn.close()
    return j['invoice']


def link_jobber_quote(case_id, number, actor='system'):
    """Point an item at the Jobber quote that is really ours for it - e.g. one
    the office made by hand - instead of the one the app drafted. The item's
    Jobber client and property follow the quote. The draft it replaces can't
    be deleted from here, so that becomes a to-do."""
    q = find_quote_by_number(number)
    if not q:
        raise ValueError(f'No Jobber quote #{number} found')
    conn = _conn()
    try:
        row = conn.execute('SELECT jobber FROM pump_cases WHERE id=?', (case_id,)).fetchone()
        if not row:
            raise ValueError('No such item')
        j = json.loads(row['jobber'] or '{}')
        old = j.get('quote') or {}
        status = (q.get('quoteStatus') or '').lower()
        client = q.get('client') or {}
        prop = q.get('property') or {}
        num = str(q.get('quoteNumber'))
        j['quote'] = {'id': q['id'], 'number': num, 'uri': q.get('jobberWebUri'),
                      'status': status, 'total': _money((q.get('amounts') or {}).get('total'))}
        if client.get('id'):
            j['client'] = {'id': client['id'], 'name': client.get('name', '')}
        conn.execute("UPDATE pump_cases SET jobber=?, jobber_client_id=COALESCE(NULLIF(?, ''), jobber_client_id), "
                     "jobber_property_id=COALESCE(NULLIF(?, ''), jobber_property_id), updated_at=? WHERE id=?",
                     (json.dumps(j), client.get('id') or '', prop.get('id') or '', _now_text(), case_id))
        # The vendor quote that was drafted into the old one now belongs to this one.
        for d in conn.execute("SELECT id, jobber FROM pump_docs WHERE case_id=? AND kind='quote'", (case_id,)).fetchall():
            dj = json.loads(d['jobber'] or '{}')
            if not dj.get('quote_id') or dj.get('quote_id') == old.get('id'):
                dj.update(quote_id=q['id'], quote_number=num, quote_uri=q.get('jobberWebUri'), quote_status=status,
                          client_id=client.get('id') or dj.get('client_id'))
                dj.pop('quote_pending', None)
                conn.execute('UPDATE pump_docs SET jobber=? WHERE id=?', (json.dumps(dj), d['id']))
        conn.execute("INSERT INTO pump_jobber_items (jobber_id, kind, number, title, status, client_id, client_name, "
                     "total, web_uri, case_id, category, synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
                     "ON CONFLICT(jobber_id) DO UPDATE SET status=excluded.status, total=excluded.total, "
                     "case_id=excluded.case_id",
                     (q['id'], 'quote', num, q.get('title') or '', status, client.get('id') or '',
                      client.get('name') or '', j['quote']['total'], q.get('jobberWebUri') or '', case_id, 'pump',
                      _now_text()))
        replaced = old.get('id') and old.get('id') != q['id']
        if replaced:
            conn.execute('UPDATE pump_jobber_items SET case_id=NULL, ignored=1 WHERE jobber_id=?', (old['id'],))
            add_todo(conn, f"delete-quote:{old['id']}", f"Delete the duplicate draft quote #{old.get('number')} in Jobber",
                     f"This job now follows quote #{num} ({client.get('name') or 'its client'}). "
                     f"#{old.get('number')} was drafted by the app and isn't needed.",
                     {'case_id': case_id, 'uri': old.get('uri') or ''})
        _event(conn, actor, 'linked Jobber quote',
               f"Quote #{num} ({client.get('name') or ''}, {status or 'status unknown'})"
               + (f" instead of #{old.get('number')}" if replaced else ''), case_id=case_id)
        if status in ('awaiting_response', 'changes_requested', 'approved', 'converted'):
            _set_step(conn, case_id, 'client_quote', at=_today().isoformat(), by=actor)
        if status in ('approved', 'converted'):
            _set_step(conn, case_id, 'client_approved', at=_today().isoformat(), by=actor)
        conn.commit()
        return j['quote']
    finally:
        conn.close()


def maint_word(doc, case=None):
    """"Fountain" for an account whose maintenance is fountains only (Miromar Lakes, Oct 2026:
    "October Fountain Maintenance"), else "Pump"."""
    text = ' '.join(str((src or {}).get(k) or '') for src in (case, doc) for k in ('client_name', 'title', 'site'))
    conn = _conn()
    try:
        name = match_account(text, conn)
        row = conn.execute('SELECT kind FROM pump_maint_accounts WHERE name=?', (name,)).fetchone() if name else None
    finally:
        conn.close()
    return 'Fountain' if row and (row['kind'] or '').strip().lower() == 'fountain' else 'Pump'


def _with_month_line(lines, y, m, word='Pump'):
    """A maintenance invoice's line says the month it's for, first: "October Pump Maintenance" over
    the job's own description (Caymas #36867, Oct 2026 - the office added it by hand). Left as
    it is when the line already names the month."""
    lines = [dict(li) for li in lines or []]
    month = date(y, m, 1).strftime('%B')
    first = next((li for li in lines if (li.get('unit_price') or 0) > 0), lines[0] if lines else None)
    if first is not None and month.lower() not in f"{first.get('name') or ''} {first.get('description') or ''}".lower():
        first['description'] = f"{month} {word} Maintenance\n{first.get('description') or ''}".strip()
    return lines


def whole_dollars(lines):
    """Our invoice prices rounded up to the dollar - no cents ($1,506.69 ->
    $1,507, Oct 2026)."""
    return [{**li, 'unit_price': float(math.ceil(float(li['unit_price']) - 1e-9))}
            if isinstance(li.get('unit_price'), (int, float)) else li for li in lines or []]


def invoice_suggestion(doc, case=None, client_id=None, job_id=None):
    """The invoice for a bill (see _invoice_suggestion), prices in whole
    dollars - except the county's, whose line shows its cost math in cents."""
    sugg = _invoice_suggestion(doc, case, client_id, job_id)
    if not sugg.get('gov'):
        for k in ('line_items', 'bill_lines'):
            if sugg.get(k):
                sugg[k] = whole_dollars(sugg[k])
    return sugg


def _invoice_suggestion(doc, case=None, client_id=None, job_id=None):
    """The invoice for a bill: when the bill matches the vendor's quote and
    the item has our client quote in Jobber, the client is invoiced what they
    were quoted (and approved). Otherwise the bill's lines plus any markup."""
    sugg = suggest_invoice(doc, case)
    case = case or {}
    qid = (json.loads(case.get('jobber') or '{}').get('quote') or {}).get('id') if case else None
    if qid and jobber_status()['connected']:
        try:
            q = fetch_quote_lines(qid)
        except Exception:
            q = None
        if q and q['line_items']:
            sugg.update(line_items=q['line_items'], from_quote=q['number'] or True)
            return sugg
    if jobber_status()['connected'] and (job_id or case.get('category') in ('maintenance', 'inspection') or
                                         maintenance_bill(doc) or maint_visit_bill(doc, case)):
        # A maintenance visit: the client pays their recurring job's price, not the bill plus markup.
        try:
            client_id = client_id or invoice_client(doc, case)
            job = recurring_job_price(doc, case, client_id, job_id) if (client_id or job_id) else None
        except JobberError:
            job = None
        if job:
            # The month the visit was for, as the office titles them: "October Pump Maintenance" (Oct 2026;
            # was "Pump service - Honda of Ft Myers - October 2026").
            y, m = bill_service_month(doc)
            month = date(y, m, 1).strftime('%B %Y')
            if FLOW_ON_INVOICE.search(job.get('instructions') or ''):
                # "TAKE MONTHLY READING OF PUMP FLOW METERS AND NOTE ON INVOICE" (Evergreen #1450).
                lines = _with_flow_readings(job['line_items'], case, doc, y, m)
                if lines:
                    job = {**job, 'line_items': lines, 'flow_readings': True}
            word = maint_word(doc, case)
            sugg['subject'] = f"{date(y, m, 1).strftime('%B')} {word} Maintenance"
            lines = job['line_items'] if job.get('flow_readings') else _with_bill_notes(job['line_items'], sugg['line_items'])
            sugg.update(bill_lines=sugg['line_items'], line_items=_with_month_line(lines, y, m, word),
                        client_id=client_id, markup_pct=0, recurring=True,
                        job={k: job[k] for k in ('id', 'number', 'title', 'uri', 'total', 'status', 'type')})
            return sugg
    if jobber_status()['connected'] and not (json.loads(case.get('jobber') or '{}').get('job') or {}).get('id'):
        try:
            client_id = client_id or invoice_client(doc, case)
            job = find_matching_job(doc, client_id) if client_id else None
        except JobberError:
            job = None
        if job and job['line_items']:
            sugg.update(bill_lines=sugg['line_items'], line_items=job['line_items'], client_id=client_id,
                        job={k: job[k] for k in ('id', 'number', 'title', 'uri', 'total', 'status')})
    return sugg


def bill_kind_note(doc, case=None):
    """What a vendor bill is for, said on its Draft invoice to-do (Caymas, Oct
    2026): "October maintenance · no quote", "Quoted work · quote #812", or
    "No quote on file"."""
    case = case or {}
    steps = json.loads(case.get('steps') or '{}') if isinstance(case.get('steps'), str) else case.get('steps') or {}
    quoted = bool((case.get('vendor_quote_number') or '').strip() or (steps.get('vendor_quote') or {}).get('at'))
    if not quoted and (maintenance_bill(doc) or case.get('category') in ('maintenance', 'inspection')
                       or maint_visit_bill(doc, case)):
        items = doc.get('line_items')
        if isinstance(items, str):
            try:
                items = json.loads(items or '[]')
            except ValueError:
                items = []
        text = ' '.join([doc.get('description') or ''] + [f"{i.get('name') or ''} {i.get('description') or ''}"
                                                          for i in items or [] if isinstance(i, dict)])
        m = _SERVICE_MONTH.search(text)
        try:
            month = datetime.strptime(m.group(0)[:3], '%b').strftime('%B') if m else \
                datetime.strptime((doc.get('doc_date') or '')[:10], '%Y-%m-%d').strftime('%B')
        except ValueError:
            month = ''
        return f"{month + ' ' if month else ''}maintenance · no quote".capitalize()
    if quoted:
        num = (case.get('vendor_quote_number') or '').strip()
        return f'Quoted work · quote #{num}' if num else 'Quoted work'
    return 'No quote on file'


_REPORT_ATTACHED = re.compile(r'\s*\(?\b(?:maintenance\s+)?report\s+attached\b[!.)]*', re.I)


FLOW_ON_INVOICE = re.compile(r'flow\s*meters?\b.{0,80}\binvoice|invoice.{0,80}flow\s*meters?', re.I | re.S)


def flow_readings(lines):
    """Flow meter readings in a pump report, by pump: [("North Pump", "229985393")].
    The report's rows: "LOCATION · North Pump" starts each pump's page, and
    "√ · CHECK & RECORD FLOW METER READINGS · 229985393" is its reading."""
    out, loc = [], ''
    for line in lines or []:
        m = re.search(r'\bLOCATION\b\s*[·:|]\s*([^·|]+)', line, re.I)
        if m:
            loc = m.group(1).strip()
        if re.search(r'FLOW\s*METER\s*READING', line, re.I):
            n = re.search(r'(\d[\d,]{3,})', re.split(r'FLOW\s*METER\s*READINGS?', line, flags=re.I)[-1])
            if n:
                out.append((loc or f'Pump {len(out) + 1}', n.group(1).replace(',', '')))
    return out


def _with_flow_readings(job_lines, case, doc, year, month):
    """The recurring job's line written the way the office invoices it (Evergreen,
    Sept 2026 #36362): the job's description, "SEPTEMBER PUMP MAINTENANCE", then
    each pump's flow meter reading in gallons, from that month's report. None
    when there is no report with readings yet."""
    conn = _conn()
    try:
        rows = [_doc_dict(r) for r in conn.execute(
            "SELECT * FROM pump_docs WHERE kind='report' AND status != 'dismissed' AND "
            "(case_id=? OR (client_name=? AND client_name != '')) ORDER BY id DESC",
            ((case or {}).get('id') or -1, (doc or {}).get('client_name') or ''))]
    finally:
        conn.close()
    ym = f'{year:04d}-{month:02d}'
    for r in sorted(rows, key=lambda r: ((r.get('doc_date') or '')[:7] != ym, -r['id'])):
        readings = flow_readings((r.get('report_fields') or {}).get('lines') or
                                 (r.get('text_excerpt') or '').replace(' | ', ' · ').split('\n'))
        if readings:
            break
    else:
        return None
    out = [dict(li) for li in job_lines or []]
    if not out:
        return None
    own = (out[0].get('description') or '').strip()
    body = f"{date(year, month, 1).strftime('%B').upper()} PUMP MAINTENANCE\n\n" + '\n'.join(
        f'{loc} - FLOW METER READINGS {n} GALLONS' for loc, n in readings)
    out[0]['description'] = (f'{own}\n\n{body}' if own else body)[:2000]
    return out


def _with_bill_notes(job_lines, bill_lines):
    """The recurring job's lines at its price, with the vendor's notes for the
    visit on the first one ("Service to perform maintenance on irrigation system
    and VFD for OCTOBER 2026." - Tuscany Point, Oct 2026), after the job's own
    description when it has one."""
    notes = ' '.join(dict.fromkeys(_REPORT_ATTACHED.sub('', (b.get('description') or '')).strip()
                                   for b in bill_lines or [])).strip()
    out = [dict(li) for li in job_lines or []]
    if out and notes and notes not in (out[0].get('description') or ''):
        own = (out[0].get('description') or '').strip()
        out[0]['description'] = (f'{own}\n{notes}' if own else notes)[:2000]
    return out


def maint_visit_bill(doc, case=None):
    """A bill from a maintenance account for the account's usual vendor cost
    (Evergreen, Oct 2026: Wettech's $100 visit, nothing saying maintenance) -
    the monthly visit, invoiced at the recurring job's price."""
    case = case or {}
    base = doc.get('subtotal') if doc.get('subtotal') is not None else doc.get('total')
    if doc.get('kind') != 'bill' or base is None:
        return False
    text = ' '.join(str(x or '') for x in (case.get('client_name'), case.get('title'), case.get('site'),
                                           doc.get('client_name'), doc.get('site')))
    conn = _conn()
    try:
        accts = {r['name']: r['vendor_cost'] for r in
                 conn.execute('SELECT name, vendor_cost FROM pump_maint_accounts WHERE active=1')}
        name = match_account(text, conn, list(accts))
    finally:
        conn.close()
    cost = _money(accts.get(name)) if name else None
    if cost is None or abs(float(base) - cost) > 1:
        return False
    items = doc.get('line_items')
    if isinstance(items, str):
        try:
            items = json.loads(items or '[]')
        except ValueError:
            items = []
    words = ' '.join([doc.get('description') or '', doc.get('proposal_title') or '', doc.get('quote_reference') or ''] +
                     [f"{i.get('name') or ''} {i.get('description') or ''}" for i in items or [] if isinstance(i, dict)])
    return not _names_a_quote(words)


def _job_priced(d):
    return sum(float(li.get('unit_price') or 0) * float(li.get('quantity') or 1) for li in d.get('line_items') or []) > 0


def recurring_job_price(doc, case, client_id, job_id=None):
    """The client's recurring maintenance job a maintenance bill is for, with
    its line items (the visit price): the item's own job when it is recurring,
    a remembered site's job, else the client's live recurring jobs - pump /
    maintenance ones first. None when it has no priced lines."""
    if job_id:
        # The office picked the job in the draft window (Caymas, Oct 2026).
        d = job_detail(job_id)
        return d if d.get('id') and d['line_items'] else None
    case = case or {}
    j = json.loads(case.get('jobber') or '{}') if isinstance(case.get('jobber'), str) else (case.get('jobber') or {})
    ids = [(j.get('job') or {}).get('id'), (match_site_alias(doc, case) or {}).get('job_id')]
    live = [x for x in recurring_jobs(client_id) if x.get('status') != 'archived']
    live.sort(key=lambda x: (not (TITLE_PATTERNS['pump'].search(x.get('title') or '') or
                                  re.search(r'quarterly|monthly|maint', x.get('title') or '', re.I)),
                             -(int(x.get('number') or 0))))
    ids += [x['id'] for x in live]
    seen, free = set(), None
    for jid in ids:
        if not jid or jid in seen:
            continue
        seen.add(jid)
        d = job_detail(jid)
        if d.get('type') == 'recurring' and d.get('status') != 'archived' and d['line_items']:
            # A $0 job ("Monthly Water Reading", Caymas #10912) only when none has a price.
            if _job_priced(d):
                return d
            free = free or d
    return free


def invoice_client(doc, case=None):
    """Who a bill is invoiced to: the job's client, a remembered site name,
    or the one clear Jobber match."""
    case = case or {}
    cid = (json.loads(case.get('jobber') or '{}').get('client') or {}).get('id') or case.get('jobber_client_id')
    if cid:
        return cid
    a = match_site_alias(doc, case)
    if a:
        return a['client_id']
    pick = pick_client(search_clients(case.get('client_name') or doc.get('client_name') or ''))
    return pick['id'] if pick else None


_LINE_FIELD_REFUSED = re.compile(r'lineItems\.\d+\.(\w+)[^.]*?(?:Field is not defined|is not defined|unknown|invalid)', re.I)


def gql_with_lines(query, variables, key):
    """Run a create mutation whose variables[key]['lineItems'] may carry line
    fields this Jobber API version doesn't take on that kind of record
    (invoice lines don't take saveToProductsAndServices): drop each field
    Jobber names and try again."""
    dropped = []
    for _ in range(4):
        try:
            return jobber_gql(query, variables)
        except JobberError as e:
            m = _LINE_FIELD_REFUSED.search(str(e))
            field = m.group(1) if m else next((f for f in ('saveToProductsAndServices', 'taxable', 'optional')
                                               if f in str(e) and f not in dropped), None)
            if not field or field in dropped or field in ('name', 'quantity', 'unitPrice'):
                raise
            dropped.append(field)
            lines = variables[key]['lineItems']
            if field == 'optional':
                # No optional lines in this Jobber: never let "possibly needed"
                # work count in the total - it goes in the main line's text.
                opts = [li for li in lines if li.get('optional')]
                lines = [li for li in lines if not li.get('optional')]
                if opts and lines:
                    lines[0] = {**lines[0], 'description': (lines[0].get('description', '') + ''.join(
                        f"\n\nOptional, if needed (not included): {o.get('description') or o['name']} - "
                        f"${o['unitPrice'] * o.get('quantity', 1):,.2f}" for o in opts))[:2000]}
            variables[key]['lineItems'] = [{k: v for k, v in li.items() if k != field} for li in lines]
    return jobber_gql(query, variables)


QUOTE_CREATE = '''mutation PumpsDraftQuote($attributes: QuoteCreateAttributes!) {
  quoteCreate(attributes: $attributes) {
    quote { id quoteNumber quoteStatus jobberWebUri }
    userErrors { message path }
  }
}'''


# ── duplicates ───────────────────────────────────────────────────────────────

DUPLICATE_DAYS = 60   # how far back a Jobber quote/invoice may be "this one"


class PossibleDuplicate(ValueError):
    """Jobber already has a quote/invoice for this client at this price."""
    def __init__(self, kind, rec):
        self.kind, self.rec = kind, rec
        super().__init__(f"Jobber {kind} #{rec.get('number')} for this client ({money_text(rec.get('total'))}, "
                         f"{(rec.get('status') or '').replace('_', ' ') or 'status unknown'}, {rec.get('created') or ''}) "
                         f"looks like this one - link it instead, or draft anyway.")


def money_text(v):
    return f'${v:,.2f}' if isinstance(v, (int, float)) else '?'


def client_records(client_id, kind):
    """The client's recent Jobber quotes or invoices: {id, number, status,
    total, created, uri}. Falls back to what the sync has seen."""
    field, num, st = ('quotes', 'quoteNumber', 'quoteStatus') if kind == 'quote' else \
        ('invoices', 'invoiceNumber', 'invoiceStatus')
    spec = [('id'), (f'{field}(first: 30)', [('nodes', ['id', num, st, 'createdAt', 'jobberWebUri',
                                                         ('amounts', ['total'])])])]

    def make(fields):
        return f'query($id: EncodedId!) {{ client(id: $id) {{ {fields} }} }}'
    try:
        data, _ = _gql_tolerant(make, spec, {'id': client_id}, required=('id', 'nodes', num))
        c = data.get('client') or {}
        nodes = (c.get(f'{field}(first: 30)') or c.get(field) or {}).get('nodes') or []
        return [{'id': n['id'], 'number': str(n.get(num) or ''), 'status': (n.get(st) or '').lower(),
                 'total': _money((n.get('amounts') or {}).get('total')), 'created': (n.get('createdAt') or '')[:10],
                 'uri': n.get('jobberWebUri')} for n in nodes]
    except JobberError:
        conn = _conn()
        try:
            return [{'id': r['jobber_id'], 'number': r['number'], 'status': r['status'], 'total': r['total'],
                     'created': (r['created_at'] or '')[:10], 'uri': r['web_uri']}
                    for r in conn.execute('SELECT * FROM pump_jobber_items WHERE kind=? AND client_id=?',
                                          (kind, client_id))]
        finally:
            conn.close()


def existing_jobber_record(kind, client_id, line_items, ignore_ids=()):
    """A recent Jobber quote/invoice for this client at the price we're about
    to draft (our lines, or the same plus the client's sales tax) - made by
    hand, or drafted before. None when there's none."""
    ours = round(sum(i['quantity'] * i['unitPrice'] for i in line_items if not i.get('optional')), 2)
    taxed = any(i.get('taxable') for i in line_items if not i.get('optional'))
    since = (_today() - timedelta(days=DUPLICATE_DAYS)).isoformat()
    for r in client_records(client_id, kind):
        if r['id'] in ignore_ids or r['total'] is None or (r['created'] and r['created'] < since):
            continue
        if r['status'] in ('archived', 'voided', 'bad_debt', 'rejected'):
            continue
        if abs(r['total'] - ours) <= 1 or (taxed and ours < r['total'] <= ours * 1.08 + 1):
            return r
    return None


def _vendor_doc_key(number):
    return re.sub(r'[^A-Z0-9]', '', (number or '').upper()).lstrip('0')


def same_vendor_doc(conn, vendor, kind, number):
    """A quote/bill already on file with this vendor's number."""
    key = _vendor_doc_key(number)
    if not key:
        return None
    for r in conn.execute("SELECT * FROM pump_docs WHERE kind=? AND status != 'dismissed' AND doc_number != '' "
                          "AND LOWER(vendor)=LOWER(?) ORDER BY id", (kind, vendor or '')):
        if _vendor_doc_key(r['doc_number']) == key:
            return dict(r)
    return None


def duplicate_jobber_invoices(conn, days=30):
    """Two Jobber invoices for the same client at the same amount within
    `days` of each other: a to-do each, once."""
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM pump_jobber_items WHERE kind='invoice' AND total IS NOT NULL AND client_id != '' "
        "AND status NOT IN ('voided', 'bad_debt') ORDER BY client_id, created_at")]
    # One bill's stations, each invoiced on its own job (The Carlisle's Entrance and Exit), are not duplicates.
    together = []
    for r in conn.execute("SELECT jobber FROM pump_docs WHERE kind='bill' AND jobber LIKE '%site_invoices%'"):
        dj = json.loads(r['jobber'] or '{}')
        together.append({x for x in [dj.get('invoice_id')] + [x.get('invoice_id') for x in dj.get('site_invoices') or []] if x})
    found = []
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if b['client_id'] != a['client_id'] or abs((a['total'] or 0) - (b['total'] or 0)) > 0.5:
                continue
            if any(a['jobber_id'] in t and b['jobber_id'] in t for t in together):
                continue
            try:
                gap = abs((datetime.strptime(b['created_at'][:10], '%Y-%m-%d') -
                           datetime.strptime(a['created_at'][:10], '%Y-%m-%d')).days)
            except (TypeError, ValueError):
                continue
            if gap > days:
                continue
            key = f"dup-invoice:{min(a['jobber_id'], b['jobber_id'])}:{max(a['jobber_id'], b['jobber_id'])}"
            link = {'uri': a['web_uri'] or b['web_uri'] or '',
                    'uris': [{'label': f"invoice #{r['number']}", 'uri': r['web_uri']} for r in (a, b) if r['web_uri']]}
            add_todo(conn, key, f"Possible duplicate invoices: #{a['number']} and #{b['number']} "
                                f"({a['client_name'] or 'same client'}, {money_text(a['total'])})",
                     f"Two Jobber invoices for the same client at the same amount, {gap} days apart "
                     f"({a['created_at'][:10]} and {b['created_at'][:10]}). Check one isn't billed twice.",
                     link)
            # Older to-dos only had one link: give them both.
            conn.execute('UPDATE pump_todos SET link=? WHERE key=?', (json.dumps(link), key))
            found.append(key)
    return found


def create_draft_quote(doc_id, client_id, property_id, line_items, title='', message='', actor='system', force=False):
    """Create our quote to the client in Jobber as a DRAFT, from the vendor's
    quote. Nothing is sent: the only mutation used is quoteCreate, which makes
    a draft, and check_mutation_allowed() refuses any other. The office
    reviews it and sends it from Jobber. If Jobber ever hands back a status
    other than draft, an issue is raised so someone looks at it."""
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
        if not row:
            raise ValueError('No such document')
        doc = _doc_dict(row)
        doc['jobber'] = {k: v for k, v in (doc.get('jobber') or {}).items() if k != 'quote_pending'}
        if doc['kind'] != 'quote':
            raise ValueError("Only a vendor's quote can be turned into a client quote")
        if (doc.get('jobber') or {}).get('quote_id'):
            raise ValueError(f"Already drafted as Jobber quote #{doc['jobber'].get('quote_number')}")
        if not client_id:
            raise ValueError('Choose the Jobber client first')
        if not property_id:
            raise ValueError("Choose the client's property first")
        items = _jobber_lines(line_items, 'quote')
        if not force:
            dup = existing_jobber_record('quote', client_id, items)
            if dup:
                raise PossibleDuplicate('quote', dup)
        attrs = {'clientId': client_id, 'propertyId': property_id, 'title': (title or 'Pump service')[:255],
                 'lineItems': items}
        if message:
            attrs['message'] = message[:4000]
        data = gql_with_lines(QUOTE_CREATE, {'attributes': attrs}, 'attributes')
        payload = data.get('quoteCreate') or {}
        errs = payload.get('userErrors') or []
        if errs:
            raise JobberError('Jobber: ' + '; '.join(e.get('message', '?') for e in errs))
        q = payload.get('quote') or {}
        status = (q.get('quoteStatus') or '').lower()
        ref = {'quote_id': q.get('id'), 'quote_number': str(q.get('quoteNumber') or ''), 'quote_status': status,
               'quote_uri': q.get('jobberWebUri'), 'client_id': client_id, 'property_id': property_id,
               'quote_drafted_by': actor, 'quote_drafted_at': _now_text(),
               'quote_lines': _line_print(attrs.get('lineItems') or items)}
        conn.execute('UPDATE pump_docs SET jobber=?, updated_at=? WHERE id=?',
                     (json.dumps({**(doc.get('jobber') or {}), **ref}), _now_text(), doc_id))
        total = round(sum(i['quantity'] * i['unitPrice'] for i in items if not i.get('optional')), 2)
        if not doc.get('case_id'):
            # A vendor quote not on a job yet (Homewood Suites, quote 9176, Oct 2026):
            # it goes on one, so our quote is followed on the watchlist.
            file_document(conn, doc_id, actor)
            doc['case_id'] = conn.execute('SELECT case_id FROM pump_docs WHERE id=?', (doc_id,)).fetchone()[0]
        if doc.get('case_id'):
            cid = doc['case_id']
            case = conn.execute('SELECT jobber FROM pump_cases WHERE id=?', (cid,)).fetchone()
            j = json.loads(case['jobber'] or '{}')
            j['quote'] = {'id': q.get('id'), 'number': ref['quote_number'], 'uri': ref['quote_uri'], 'status': status,
                          'total': total}
            j.setdefault('client', {'id': client_id})
            conn.execute('UPDATE pump_cases SET jobber=?, jobber_client_id=?, jobber_property_id=?, updated_at=? '
                         'WHERE id=?', (json.dumps(j), client_id, property_id, _now_text(), cid))
            _event(conn, actor, 'draft quote created',
                   f"Jobber quote #{ref['quote_number']} ({status or 'status unknown'}) - ${total:,.2f}. "
                   'Review it and send it from Jobber.', case_id=cid, doc_id=doc_id)
            if status and status != 'draft':
                open_issue(conn, cid, 'not_draft',
                           f"Jobber reports quote #{ref['quote_number']} as '{status}', not draft. "
                           'Open it in Jobber and check it has not gone to the client.', doc_id=doc_id)
        conn.commit()
        # The vendor's quote goes on our quote as a note, for whoever reviews it.
        if q.get('id'):
            try:
                note = note_vendor_file({**doc, 'id': doc_id}, 'quote', q['id'], _quote_note_text(doc, total))
                ref.update(quote_note_id=note['note_id'], quote_note_attached=note['attached'])
                conn.execute('UPDATE pump_docs SET jobber=? WHERE id=?',
                             (json.dumps({**(doc.get('jobber') or {}), **ref}), doc_id))
                if doc.get('case_id'):
                    _event(conn, actor, 'vendor quote saved on Jobber quote',
                           'attached' if note['attached'] else 'linked (Jobber would not take the file)',
                           case_id=doc['case_id'], doc_id=doc_id)
                conn.commit()
            except JobberError as e:
                if doc.get('case_id'):
                    _event(conn, actor, 'vendor quote not saved on Jobber quote', str(e), case_id=doc['case_id'],
                           doc_id=doc_id)
                    conn.commit()
        return {**ref, 'total': total}
    finally:
        conn.close()


INVOICE_CREATE = '''mutation PumpsDraftInvoice($input: InvoiceCreateInput!) {
  invoiceCreate(input: $input) {
    invoice { id invoiceNumber invoiceStatus jobberWebUri amounts { total } }
    userErrors { message path }
  }
}'''


INVOICE_NET_DAYS = 30


def invoice_due_details(days=INVOICE_NET_DAYS):
    """Jobber's dueDetails for Net 30, from whatever this API version names
    it: a payment-terms enum value like NET_30, or else a due date 30 days
    out. Empty (Jobber's default terms) when the schema can't be read."""
    try:
        top = _type_fields('InvoiceCreateAttributes').get('inputFields') or []
        f = next((x for x in top if x['name'] == 'dueDetails'), None)
        tname = _type_ref(f['type'])[2] if f else None
        fields = (_type_fields(tname).get('inputFields') or []) if tname else []
        for fld in fields:
            ename = _type_ref(fld['type'])[2]
            values = _enum_values(ename)
            pick = next((v for v in values if re.fullmatch(rf'(?i)net_?{days}(_days)?', v)), None) or \
                next((v for v in values if re.search(rf'(?<!\d){days}(?!\d)', v)), None)
            if pick:
                return {fld['name']: pick}
        for fld in fields:
            if re.search(r'(?i)due.*date|date.*due', fld['name']):
                return {fld['name']: (_today() + timedelta(days=days)).isoformat()}
    except (JobberError, KeyError, TypeError):
        pass
    return {}


def _enum_values(name):
    if not name:
        return []
    key = f'enum:{name}'
    if key not in _SCHEMA_CACHE:
        data = jobber_gql('query($n: String!) { __type(name: $n) { kind enumValues { name } } }', {'n': name})
        t = data.get('__type') or {}
        _SCHEMA_CACHE[key] = [v['name'] for v in t.get('enumValues') or []] if t.get('kind') == 'ENUM' else []
    return _SCHEMA_CACHE[key]


def _invoice_visit_field():
    """The InvoiceCreateInput field that ties an invoice to job visits, when
    this Jobber API has one ('' when not)."""
    try:
        have = {f['name'] for f in (_type_fields('InvoiceCreateInput').get('inputFields') or [])}
    except JobberError:
        return ''
    return next((k for k in ('visitIds', 'visitsIds', 'visits') if k in have), '')


def create_draft_invoice(doc_id, client_id, line_items, subject='', job_id='', actor='system', force=False,
                         visit_ids=None, extra=False, ignore_ids=(), site=''):
    """Create the invoice in Jobber as a DRAFT. Nothing is sent: the only
    mutation used is invoiceCreate, and check_mutation_allowed() refuses any
    other. If Jobber ever hands back a status other than draft, an issue is
    raised so someone looks at it. extra: another station's invoice for a bill
    already invoiced once (see draft_site_invoices) - kept beside the first."""
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
        if not row:
            raise ValueError('No such document')
        doc = _doc_dict(row)
        if doc['kind'] != 'bill':
            raise ValueError('Only a bill can be turned into an invoice')
        if (doc.get('jobber') or {}).get('invoice_id') and not extra:
            raise ValueError(f"Already drafted as Jobber invoice #{doc['jobber'].get('invoice_number')}")
        if not client_id:
            raise ValueError('Choose the Jobber client first')
        items = _jobber_lines(line_items, 'invoice')
        if not force:
            dup = existing_jobber_record('invoice', client_id, items, ignore_ids=tuple(ignore_ids))
            if dup:
                raise PossibleDuplicate('invoice', dup)
        due = invoice_due_details()
        inp = {'clientId': client_id, 'subject': (subject or 'Pump service')[:255], 'dueDetails': due,
               'tax': {'taxCalculationMethod': 'EXCLUSIVE'}, 'lineItems': items}
        if job_id:
            inp['jobId'] = job_id
            # A recurring job's visit, completed just before: the invoice is for it, so
            # Jobber counts the visit as invoiced (not "completed, not invoiced").
            vfield = _invoice_visit_field() if visit_ids else ''
            if vfield:
                inp[vfield] = list(visit_ids)
        try:
            data = gql_with_lines(INVOICE_CREATE, {'input': inp}, 'input')
        except JobberError as e:
            if not due or 'due' not in str(e).lower():
                raise
            print(f'  ⚠ Pumps: Jobber would not take Net {INVOICE_NET_DAYS} ({e}); drafting with its default terms')
            inp['dueDetails'] = {}
            data = gql_with_lines(INVOICE_CREATE, {'input': inp}, 'input')
        payload = data.get('invoiceCreate') or {}
        errs = payload.get('userErrors') or []
        if errs:
            raise JobberError('Jobber: ' + '; '.join(e.get('message', '?') for e in errs))
        inv = payload.get('invoice') or {}
        status = (inv.get('invoiceStatus') or '').lower()
        ref = {'invoice_id': inv.get('id'), 'invoice_number': str(inv.get('invoiceNumber') or ''),
               'invoice_status': status, 'invoice_uri': inv.get('jobberWebUri'), 'client_id': client_id,
               'job_id': job_id, 'drafted_by': actor, 'drafted_at': _now_text()}
        if site:
            ref['site'] = site
        dj = doc.get('jobber') or {}
        dj = {**dj, 'site_invoices': (dj.get('site_invoices') or []) + [ref]} if extra else {**dj, **ref}
        conn.execute('UPDATE pump_docs SET jobber=?, status=?, updated_at=? WHERE id=?',
                     (json.dumps(dj), 'done', _now_text(), doc_id))
        total = round(sum(i['quantity'] * i['unitPrice'] for i in items), 2)
        if doc.get('case_id') and extra:
            cid = doc['case_id']
            case = conn.execute('SELECT jobber, amount FROM pump_cases WHERE id=?', (cid,)).fetchone()
            j = json.loads(case['jobber'] or '{}')
            j['site_invoices'] = (j.get('site_invoices') or []) + [
                {'id': inv.get('id'), 'number': ref['invoice_number'], 'uri': ref['invoice_uri'], 'status': status,
                 'site': site, 'job_id': job_id}]
            conn.execute('UPDATE pump_cases SET jobber=?, amount=?, updated_at=? WHERE id=?',
                         (json.dumps(j), round((case['amount'] or 0) + total, 2), _now_text(), cid))
            _event(conn, actor, 'draft invoice created',
                   f"{site + ': ' if site else ''}Jobber invoice #{ref['invoice_number']} ({status or 'status unknown'}) - "
                   f"${total:,.2f}", case_id=cid, doc_id=doc_id)
            if status and status != 'draft':
                open_issue(conn, cid, 'not_draft',
                           f"Jobber reports invoice #{ref['invoice_number']} as '{status}', not draft. "
                           'Open it in Jobber and check it has not gone to the client.', doc_id=doc_id)
            conn.commit()
            return {**ref, 'total': total}
        if doc.get('case_id'):
            cid = doc['case_id']
            case = conn.execute('SELECT jobber, sei_invoice_number FROM pump_cases WHERE id=?', (cid,)).fetchone()
            j = json.loads(case['jobber'] or '{}')
            j['invoice'] = {'id': inv.get('id'), 'number': ref['invoice_number'], 'uri': ref['invoice_uri'],
                            'status': status, 'total': _money((inv.get('amounts') or {}).get('total'))}
            j.setdefault('client', {'id': client_id})
            conn.execute('UPDATE pump_cases SET jobber=?, sei_invoice_number=?, amount=?, jobber_client_id=?, '
                         'updated_at=? WHERE id=?',
                         (json.dumps(j), ref['invoice_number'], total, client_id, _now_text(), cid))
            _set_step(conn, cid, 'invoice_drafted', at=_today().isoformat(), by=actor)
            _event(conn, actor, 'draft invoice created',
                   f"Jobber invoice #{ref['invoice_number']} ({status or 'status unknown'}) - ${total:,.2f}",
                   case_id=cid, doc_id=doc_id)
            if status and status != 'draft':
                open_issue(conn, cid, 'not_draft',
                           f"Jobber reports invoice #{ref['invoice_number']} as '{status}', not draft. "
                           'Open it in Jobber and check it has not gone to the client.', doc_id=doc_id)
        conn.commit()
        if doc.get('case_id'):
            # The sub's quote on the invoice, for later. Never holds up the invoice.
            try:
                note = note_sub_quote_on_invoice(doc['case_id'], inv.get('id'), job_id, client_id,
                                                 ref['invoice_number'])
            except Exception as e:
                note, ref['sub_quote_note_error'] = None, str(e)
            if note:
                ref['sub_quote_note'] = note
                _event(conn, actor, 'sub quote on invoice',
                       f"{doc.get('vendor') or 'Vendor'} quote {'attached' if note.get('attached') else 'noted'} "
                       f"on the Jobber {note['on']}", case_id=doc['case_id'], doc_id=note['doc_id'])
                conn.commit()
        return {**ref, 'total': total}
    finally:
        conn.close()


def _signed_file_url(doc_id, version='branded', days=2, name=''):
    """A short-lived link to a document. Jobber names an attached file after
    the link's last part, so `name` ("10-26 Evergreen.pdf") goes on the end."""
    base = (CFG.get('website_url') or '').rstrip('/')
    if not base or 'localhost' in base or '127.0.0.1' in base:
        return ''
    exp = int(time.time()) + days * 86400
    sig = hmac.new((CFG.get('secret_key') or '').encode(), f'{doc_id}:{version}:{exp}'.encode(),
                   'sha256').hexdigest()[:32]
    return f'{base}/pumps/f/{doc_id}/{version}/{exp}/{sig}' + (f'/{url_quote(name)}' if name else '')


def _check_signed(doc_id, version, exp, sig):
    if int(exp) < time.time():
        return False
    good = hmac.new((CFG.get('secret_key') or '').encode(), f'{doc_id}:{version}:{exp}'.encode(),
                    'sha256').hexdigest()[:32]
    return hmac.compare_digest(good, sig)


def report_note_text(doc, section=None):
    rf = doc.get('report_fields') or {}
    # Only ever the rebranded report's lines - never the sub's original.
    raw = rf.get('lines') if rf.get('from_branded') else []
    if section is not None and raw:
        secs = report_sections(doc)
        if 0 <= section < len(secs):
            raw = secs[section]['lines']
            rf = {**rf, 'title': f"{rf.get('title') or 'Report'} - {secs[section]['location']}",
                  'date': secs[section]['date'] or rf.get('date')}
    lines = [l for l in (raw or []) if l and not re.match(r'^(STAHLMAN|Installation •|Landscape Drainage)', l)]
    head = f"Pump report - {rf.get('title') or 'Report'}" + (f" - {rf.get('date')}" if rf.get('date') else '')
    body = '\n'.join(lines[:60])
    base = (CFG.get('website_url') or '').rstrip('/')
    link = f"\n\nReport file: {base}/pumps#doc-{doc['id']}" if base and 'localhost' not in base else ''
    return (head + '\n' + body)[:6000] + link


NOTE_MUTATION = {
    'job': ('jobCreateNote', 'jobId', 'JobCreateNoteInput', 'jobNote'),
    'client': ('clientCreateNote', 'clientId', 'ClientCreateNoteInput', 'clientNote'),
    'request': ('requestCreateNote', 'requestId', 'RequestCreateNoteInput', 'requestNote'),
    'quote': ('quoteCreateNote', 'quoteId', 'QuoteCreateNoteInput', 'quoteNote'),
    'invoice': ('invoiceCreateNote', 'invoiceId', 'InvoiceCreateNoteInput', 'invoiceNote'),
}


def note_sub_quote_on_invoice(case_id, invoice_id, job_id='', client_id='', invoice_number=''):
    """The sub's quote for the work, attached to our Jobber invoice so it's at
    hand later (Oct 2026) - on the invoice when Jobber takes invoice notes,
    else on the job, else on the client. None when there is no sub quote."""
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM pump_docs WHERE case_id=? AND kind='quote' AND status != 'dismissed' "
                           "ORDER BY id DESC", (case_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    doc = _doc_dict(row)
    vendor = doc.get('vendor') or 'Vendor'
    price = doc.get('total') if doc.get('total') is not None else doc.get('subtotal')
    base = (CFG.get('website_url') or '').rstrip('/')
    text = '\n'.join(x for x in (
        f"{vendor} quote{' #' + doc['doc_number'] if doc.get('doc_number') else ''}"
        f"{' dated ' + doc['doc_date'] if doc.get('doc_date') else ''} for this work: {doc.get('file_name')}",
        f"{vendor} price: ${price:,.2f}" if price is not None else '',
        f"File: {base}/pumps#doc-{doc['id']}" if base and 'localhost' not in base else '') if x)
    targets = ([('invoice', invoice_id)] if invoice_id and 'invoiceCreateNote' in _mutation_schema() else []) + \
        [(t, i) for t, i in (('job', job_id), ('client', client_id)) if i]
    for target, tid in targets:
        try:
            msg = text if target == 'invoice' or not invoice_number else f"For invoice #{invoice_number} - {text}"
            return {**note_vendor_file(doc, target, tid, msg), 'on': target, 'doc_id': doc['id']}
        except JobberError as e:
            print(f'  ⚠ Pumps: could not put the sub quote on the {target} ({e})')
    return None


_FILE_MONTH = re.compile(r'^\s*(\d{1,2})\s*[-_.]\s*(\d{2})(?!\d)')


def report_month_date(doc):
    """The day a report is for. Wettech names each report by its month -
    "10-26 Sopra Luxury Living.docx" is October 2026 - and that wins over a
    date inside that disagrees (Sopra, Oct 2026: the form still said July, and
    the note went in as "July Pump Report")."""
    rf = doc.get('report_fields') or {}
    when = _iso_date(rf.get('date')) or doc.get('doc_date') or ''
    m = _FILE_MONTH.match(os.path.basename(doc.get('file_name') or ''))
    if m and 1 <= int(m.group(1)) <= 12:
        ym = f'20{m.group(2)}-{int(m.group(1)):02d}'
        if when[:7] != ym:
            return f'{ym}-01'
    return when


def report_note_title(doc):
    """"October Pump Report": the month of the visit, as the office titles them."""
    when = report_month_date(doc) or _today().isoformat()
    try:
        month = datetime.strptime(when[:10], '%Y-%m-%d').strftime('%B')
    except ValueError:
        month = _today().strftime('%B')
    what = 'Fountain Report' if re.search(r'fountain', (doc.get('report_fields') or {}).get('title') or '', re.I) \
        else 'Pump Report'
    return f'{month} {what}'


def resolve_report_target(doc, case=None):
    """Where a report's note goes: the job a site name points at, else the
    pump job of the item's (or the clear match's) client. Returns
    {'type','id','label','how'} or {'needs': reason, ...choices}."""
    case = case or {}
    alias = match_site_alias(doc, case)
    if alias and alias.get('job_id'):
        return {'type': 'job', 'id': alias['job_id'], 'label': f"{alias['client_name']} {alias['job_label']}".strip(),
                'how': f'site name "{alias["place"]}"'}
    j = case.get('jobber') if isinstance(case.get('jobber'), dict) else json.loads(case.get('jobber') or '{}')
    if case.get('category') in ('maintenance', 'inspection') and (j.get('job') or {}).get('id'):
        # The maintenance visit's own job - where its bill was invoiced.
        return {'type': 'job', 'id': j['job']['id'], 'label': f"#{j['job'].get('number') or ''}".strip(),
                'how': "the item's Jobber job"}
    client_id = (alias or {}).get('client_id') or (j.get('client') or {}).get('id') or case.get('jobber_client_id')
    how = f'site name "{alias["place"]}"' if alias else 'the item'
    cands = []
    if not client_id:
        name = doc.get('client_name') or case.get('client_name') or ''
        cands = search_clients(name) if name else []
        pick = pick_client(cands)
        client_id, how = (pick['id'], f'Jobber search for "{name}"') if pick else (None, '')
    if not client_id:
        return {'needs': 'Choose the Jobber client for this report.', 'candidates': cands}
    cj = client_jobs(client_id)
    props = cj['properties']
    if alias and alias.get('property_id'):
        props = [p for p in props if p['id'] == alias['property_id']] or props
    job = best_job_for_report(cj['jobs'], props, doc.get('site'), (doc.get('report_fields') or {}).get('title'))
    if not job:
        return {'needs': 'No clear pump job for this report - choose the job, or log it on the client.',
                'client_id': client_id, 'jobs': cj['jobs'], 'properties': cj['properties']}
    return {'type': 'job', 'id': job['id'], 'label': f"#{job.get('number')} {job.get('title')}", 'how': how}


def auto_log_report(doc_id, actor='Pumps (automatic)'):
    """Put a newly rebranded report on its pump job in Jobber, when the job is
    clear. Otherwise say on the report what a person has to choose."""
    if not AUTO_LOG_REPORTS or not jobber_status()['connected']:
        return None
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
        doc = _doc_dict(row) if row else None
        case = dict(conn.execute('SELECT * FROM pump_cases WHERE id=?', (doc['case_id'],)).fetchone()) \
            if doc and doc.get('case_id') else {}
    finally:
        conn.close()
    if not doc or doc['kind'] != 'report' or doc['status'] == 'dismissed' or (doc.get('jobber') or {}).get('note_id'):
        return None
    if doc['status'] == 'review':
        return _note_pending(doc, 'The report needs a look first (Look at) - then log it in Jobber.', actor)
    if not doc['has_branded']:
        return _note_pending(doc, "The report couldn't be rebranded, so it wasn't put in Jobber by itself.", actor)
    try:
        sites = section_targets(doc, case)
        if sites:
            return log_sections(doc, sites, actor)
        t = resolve_report_target(doc, case)
        if t.get('id'):
            return {**log_report_to_jobber(doc_id, t['type'], t['id'], actor), 'target': t['label'], 'how': t['how']}
        reason = t['needs']
    except (JobberError, ValueError) as e:
        reason = f'Could not log it automatically: {e}'
    return _note_pending(doc, reason, actor)


def _note_pending(doc, reason, actor):
    """Why a report wasn't put in Jobber by itself - kept on it and shown on its to-do."""
    conn = _conn()
    try:
        j = {**(doc.get('jobber') or {}), 'note_pending': {'reason': reason, 'at': _now_text()}}
        conn.execute('UPDATE pump_docs SET jobber=? WHERE id=?', (json.dumps(j), doc['id']))
        _event(conn, actor, 'report not logged in Jobber', reason, case_id=doc.get('case_id'), doc_id=doc['id'])
        conn.commit()
    finally:
        conn.close()
    return {'pending': reason}


# ── Two pump stations in one report ──────────────────────────────────────────
# The Carlisle (Greenscapes, Oct 2026): Wettech sends one report with a page
# for the Entrance pump and one for the Exit pump. Each station has its own
# recurring job in Jobber (#3249 Entrance, #3250 Exit), so each page is its own
# note on its own job, and the bill is invoiced once per job.

_LOC_ROW = re.compile(r'\bLOCATION\b\s*[·:|]\s*([^·|]+)', re.I)
_DATE_ROW = re.compile(r'\bDATE\b\s*[·:|]\s*(\d{1,4}[-/.]\d{1,2}[-/.]\d{2,4})', re.I)
_REPORT_HEAD = re.compile(r'^(STAHLMAN|Installation •|Landscape Drainage|Water Equipment Tech|.*\bREPORT\s*$)', re.I)
# Words that say nothing about which station ("North Pump", "Pump Station").
_STATION_WORDS = {'pump', 'pumps', 'station', 'the', 'and', 'site', 'irrigation', 'main', 'system'}


def report_sections(doc):
    """A report's pages, one per pump station: [{'location', 'date', 'lines'}],
    in order. [] when the report is for one station."""
    rf = doc.get('report_fields') or {}
    lines = rf.get('lines') or (doc.get('text_excerpt') or '').replace(' | ', ' · ').split('\n')
    secs, pre = [], []
    for line in lines or []:
        m = _LOC_ROW.search(line or '')
        if not (m and m.group(1).strip()):
            (secs[-1]['lines'] if secs else pre).append(line)
            continue
        if secs:
            # The next page's letterhead, title and date came before its LOCATION row.
            prev = secs[-1]['lines']
            k = next((i for i in range(len(prev) - 1, 0, -1) if re.search(r'\bREPORT\s*$', prev[i] or '', re.I)), None)
            if k is not None:
                while k > 1 and _REPORT_HEAD.match(prev[k - 1] or ''):
                    k -= 1
                pre, secs[-1]['lines'] = prev[k:], prev[:k]
        secs.append({'location': m.group(1).strip(), 'date': '', 'lines': pre + [line]})
        pre = []
    for sec in secs:
        d = next((_DATE_ROW.search(l or '') for l in sec['lines'] if _DATE_ROW.search(l or '')), None)
        sec['date'] = d.group(1) if d else ''
    if len({sec['location'].lower() for sec in secs}) < 2:
        return []
    return secs


def _section_pdf(branded_path, location):
    """The pages of the rebranded report's PDF for one station, as PDF bytes;
    None when the PDF can't be split by station."""
    path = _branded_pdf_path(branded_path)
    if not path or not os.path.exists(path):
        return None
    try:
        from PyPDF2 import PdfReader, PdfWriter
        reader = PdfReader(path)
        want = re.sub(r'\s+', ' ', location).strip().lower()
        keep, on = [], False
        for page in reader.pages:
            text = re.sub(r'\s+', ' ', page.extract_text() or '')
            m = re.search(r'\bLOCATION\b\s*:?\s*(.+)', text, re.I)
            if m:
                on = m.group(1).strip().lower().startswith(want)
            if on:
                keep.append(page)
        if not keep or len(keep) == len(reader.pages):
            return None
        writer = PdfWriter()
        for page in keep:
            writer.add_page(page)
        buf = io.BytesIO()
        writer.write(buf)
        return buf.getvalue()
    except Exception as e:
        print(f'  ⚠ Pumps: could not split {os.path.basename(path)} by station: {e}')
        return None


def station_job(jobs, site, location):
    """The live recurring job for one station of a site: its title or property
    names the station ("Entrance" -> "The Carlisle Naples- Pump #2 Entrance")
    and the site. None unless exactly one fits."""
    loc = [w for w in re.findall(r'[a-z0-9#]+', (location or '').lower()) if len(w) > 2 and w not in _STATION_WORDS]
    where = [w for w in re.findall(r'[a-z0-9]+', (site or '').lower()) if len(w) > 3 and w not in _STATION_WORDS]
    if not loc:
        return None
    live = [j for j in jobs if j.get('type') == 'recurring' and j.get('status') != 'archived']
    text = lambda j: f"{j.get('title') or ''} {j.get('property_label') or ''}".lower()
    at_site = [j for j in live if not where or any(w in text(j) for w in where)]
    hit = [j for j in at_site if any(re.search(rf'(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])', text(j)) for w in loc)]
    return hit[0] if len(hit) == 1 else None


def section_targets(doc, case=None):
    """For a report covering more than one station, each page's job:
    [{'section', 'location', 'job'}] (job None when no single job fits). None
    when the report is one station's, or its pages don't land on different jobs
    (Evergreen's North and South pumps are one job) - it's logged as one note."""
    secs = report_sections(doc)
    if not secs:
        return None
    case = case or {}
    j = case.get('jobber') if isinstance(case.get('jobber'), dict) else json.loads(case.get('jobber') or '{}')
    alias = match_site_alias(doc, case)
    client_id = (alias or {}).get('client_id') or (j.get('client') or {}).get('id') or case.get('jobber_client_id')
    if not client_id:
        pick = pick_client(search_clients(doc.get('client_name') or case.get('client_name') or ''))
        client_id = pick['id'] if pick else None
    if not client_id:
        return None
    jobs = recurring_jobs(client_id)
    site = (doc.get('report_fields') or {}).get('customer') or doc.get('client_name') or case.get('client_name') or ''
    out = [{'section': i, 'location': sec['location'], 'date': sec['date'], 'client_id': client_id,
            'job': station_job(jobs, site, sec['location'])} for i, sec in enumerate(secs)]
    if len({t['job']['id'] for t in out if t['job']}) < 2:
        return None
    return out


def log_sections(doc, sites, actor):
    """Each station's page as its own note on its own job. A page whose job
    isn't clear waits for a person, said on the report."""
    done = (doc.get('jobber') or {}).get('sections') or {}
    logged, waiting = [], []
    for t in sites:
        if str(t['section']) in done:
            continue
        if not t['job']:
            waiting.append(t['location'])
            continue
        ref = log_report_to_jobber(doc['id'], 'job', t['job']['id'], actor, section=t['section'])
        logged.append({**ref, 'target': f"#{t['job'].get('number')} {t['job'].get('title')}"})
    out = {'sections': logged}
    if waiting:
        conn = _conn()
        try:
            doc = _doc_dict(conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc['id'],)).fetchone())
        finally:
            conn.close()
        out.update(_note_pending(doc, f"No clear Jobber job for the {' and '.join(waiting)} page - choose it "
                                      '(Log in Jobber).', actor))
    if logged and doc.get('case_id'):
        # The bill came first: its other station's invoice now that the report says there are two.
        conn = _conn()
        try:
            bills = [r['id'] for r in conn.execute("SELECT id FROM pump_docs WHERE case_id=? AND kind='bill' AND "
                                                   "status != 'dismissed' AND jobber LIKE '%invoice_id%'",
                                                   (doc['case_id'],))]
        finally:
            conn.close()
        for bid in bills:
            if AUTO_DRAFT_INVOICES:
                try:
                    draft_site_invoices(bid, actor)
                except (JobberError, ValueError) as e:
                    print(f'  ⚠ Pumps: second station invoice for bill {bid} not drafted: {e}')
    return out


def _site_report(conn, doc, case):
    """The report that came with a bill: on its item, else the same site's report within 45 days."""
    rows = []
    if (case or {}).get('id'):
        rows = conn.execute("SELECT * FROM pump_docs WHERE case_id=? AND kind='report' AND status != 'dismissed' "
                            'ORDER BY id DESC', (case['id'],)).fetchall()
    if not rows and doc.get('client_name'):
        since = ((_iso_date(doc.get('doc_date')) and date.fromisoformat(_iso_date(doc.get('doc_date')))) or _today()) \
            - timedelta(days=45)
        rows = conn.execute("SELECT * FROM pump_docs WHERE kind='report' AND status != 'dismissed' AND client_name=? "
                            'AND created_at >= ? ORDER BY id DESC', (doc['client_name'], since.isoformat())).fetchall()
    for r in rows:
        d = _doc_dict(r)
        if report_sections(d):
            return d
    return None


def bill_sites(doc, case=None):
    """The stations a bill covers, each with its own recurring job:
    [{'location', 'job_id'}], from the report that came with it - the jobs its
    pages were logged on, else the ones found now. [] for one station."""
    conn = _conn()
    try:
        rep = _site_report(conn, doc, case)
    finally:
        conn.close()
    if not rep:
        return []
    done = (rep.get('jobber') or {}).get('sections') or {}
    secs = report_sections(rep)
    if len(done) == len(secs) and all(v.get('note_target') == 'job' for v in done.values()) and \
            len({v['note_target_id'] for v in done.values()}) >= 2:
        return [{'location': secs[int(k)]['location'], 'job_id': v['note_target_id']} for k, v in sorted(done.items())]
    sites = section_targets(rep, case) or []
    return [{'location': t['location'], 'job_id': t['job']['id']} for t in sites if t['job']]


def draft_site_invoices(doc_id, actor='system'):
    """One draft invoice per station's job for a bill covering two (The
    Carlisle: Entrance #3249 and Exit #3250), each at its job's price. Drafts
    only the ones not made yet - the first may already be there. None when the
    bill is for one station."""
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
        doc = _doc_dict(row) if row else None
        case = dict(conn.execute('SELECT * FROM pump_cases WHERE id=?', (doc['case_id'],)).fetchone()) \
            if doc and doc.get('case_id') else {}
    finally:
        conn.close()
    if not doc or doc['kind'] != 'bill':
        raise ValueError('Not a bill')
    sites = bill_sites(doc, case)
    if len(sites) < 2:
        return None
    J = doc.get('jobber') or {}
    have = {x['job_id'] for x in J.get('site_invoices') or []} | ({J.get('job_id')} if J.get('invoice_id') else set())
    made = [x for x in [J.get('invoice_id')] + [x['invoice_id'] for x in J.get('site_invoices') or []] if x]
    client_id = invoice_client(doc, case)
    if not client_id:
        raise ValueError('Choose the Jobber client first')
    y, m = bill_service_month(doc)
    month = date(y, m, 1).strftime('%B %Y')
    where = case.get('client_name') or doc.get('client_name') or ''
    bill_lines = suggest_invoice(doc, case).get('line_items') or []
    out = []
    for site in sites:
        if site['job_id'] in have:
            continue
        job = job_detail(site['job_id'])
        if not job.get('line_items'):
            out.append({'location': site['location'], 'pending': f"Job #{job.get('number')} has no price in Jobber"})
            continue
        lines = whole_dollars(_with_bill_notes(job['line_items'], bill_lines))
        subject = f"Pump service - {where} - {site['location']} - {month}"[:255]
        visit = complete_visit_for_bill(doc, case, job, actor)
        first = not (doc.get('jobber') or {}).get('invoice_id') and not out
        res = create_draft_invoice(doc_id, client_id, lines, subject, job['id'], actor, visit_ids=_visit_ids(visit),
                                   extra=not first, ignore_ids=tuple(made), site=site['location'])
        if first:
            invoiced_on_job(doc, case, {**job, 'type': 'recurring'}, actor)
            doc['jobber'] = {**(doc.get('jobber') or {}), 'invoice_id': res.get('invoice_id')}
        made.append(res.get('invoice_id'))
        have.add(job['id'])
        out.append({**res, 'location': site['location'], 'job': {k: job.get(k) for k in ('id', 'number', 'title', 'uri')}})
    return {'invoices': out}


def site_invoices_left(doc, case=None):
    """The stations of a bill already invoiced once that still need their own invoice."""
    J = doc.get('jobber') or {}
    if doc.get('kind') != 'bill' or not J.get('invoice_id'):
        return []
    try:
        sites = bill_sites(doc, case)
    except JobberError:
        return []
    have = {x['job_id'] for x in J.get('site_invoices') or []} | {J.get('job_id')}
    return [s for s in sites if s['job_id'] not in have] if len(sites) >= 2 else []


def log_report_to_jobber(doc_id, target_type, target_id, actor='system', message=None, section=None):
    """Add the report as a note on the pump's job (or the client). Tries to
    attach the rebranded file; if Jobber will not take the attachment, the note
    is saved with a link to the file in this app instead. section: one pump
    station's page of a report covering two (The Carlisle's Entrance and Exit) -
    its own note, with only its page, on its own job."""
    if target_type not in NOTE_MUTATION:
        raise ValueError('Note target must be job, client, request or quote')
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
        if not row:
            raise ValueError('No such document')
        doc = _doc_dict(row)
        if doc['kind'] != 'report':
            raise ValueError('Only a report can be logged as a note')
        mutation, id_arg, input_type, field = NOTE_MUTATION[target_type]
        sec = None
        if section is not None:
            secs = report_sections(doc)
            if not 0 <= section < len(secs):
                raise ValueError('This report has no such page')
            sec = secs[section]
            rf = doc.get('report_fields') or {}
            text = message or f"{report_note_title({**doc, 'report_fields': {**rf, 'date': sec['date'] or rf.get('date')}})}" \
                              f" - {sec['location']}"
        else:
            text = message or report_note_title(doc)
        q = (f'mutation PumpsReportNote($id: EncodedId!, $input: {input_type}!) {{ {mutation}({id_arg}: $id, '
             f'input: $input) {{ {field} {{ id }} userErrors {{ message path }} }} }}')
        # The PDF, as the office attaches them; the Word file when there is no PDF.
        has_pdf = bool(row['branded_path']) and (os.path.exists(_branded_pdf_path(row['branded_path'])) or
                                                  bool(_make_branded_pdf(row['branded_path'])))
        version = 'branded_pdf' if has_pdf else ('branded' if doc['has_branded'] else 'original')
        # Named as the vendor sent it ("10-26  Spanish Wells"), only the extension changes. Jobber
        # takes the name from the link, so it goes on the end of it.
        fname = _vendor_file_name(doc['file_name'], '.pdf' if has_pdf else '.docx')
        if sec and has_pdf and _section_pdf(row['branded_path'], sec['location']):
            # Only this station's page.
            version = f'section{section}'
            fname = _vendor_file_name(doc['file_name'], f" - {sec['location']}.pdf")
        url = _signed_file_url(doc_id, version, days=7, name=fname)
        attached = False
        data = None
        if url:
            ctype = 'application/pdf' if has_pdf else \
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            try:
                data = jobber_gql(q, {'id': target_id, 'input': {'message': text, 'attachments': [
                    _note_attachment(url, fname, ctype)]}})
                attached = not ((data.get(mutation) or {}).get('userErrors'))
            except JobberError as e:
                print(f'  ⚠ Pumps: Jobber would not take the attachment ({e}); saving the note without it')
                data = None
        if not attached:
            # No file on the note: put the (rebranded) report's text and a link in it.
            data = jobber_gql(q, {'id': target_id, 'input': {'message': f'{text}\n\n{report_note_text(doc, section)}'
                                                                        if not message else text}})
        payload = data.get(mutation) or {}
        errs = payload.get('userErrors') or []
        if errs:
            raise JobberError('Jobber: ' + '; '.join(e.get('message', '?') for e in errs))
        note_id = (payload.get(field) or {}).get('id')
        ref = {'note_id': note_id, 'note_target': target_type, 'note_target_id': target_id,
               'note_attached_file': attached, 'note_title': text, 'note_pdf': has_pdf, 'logged_by': actor,
               'logged_at': _now_text()}
        j = {k: v for k, v in (doc.get('jobber') or {}).items() if k != 'note_pending'}
        if sec:
            j['sections'] = {**(j.get('sections') or {}), str(section): {**ref, 'location': sec['location']}}
            if len(j['sections']) < len(report_sections(doc)):
                # The other station's note still to go.
                conn.execute('UPDATE pump_docs SET jobber=?, updated_at=? WHERE id=?', (json.dumps(j), _now_text(), doc_id))
                if doc.get('case_id'):
                    _event(conn, actor, 'report logged in Jobber', f"{sec['location']} page - note on {target_type}",
                           case_id=doc['case_id'], doc_id=doc_id)
                conn.commit()
                return {**ref, 'section': section, 'location': sec['location']}
            ref = {**ref, 'note_id': next(iter(j['sections'].values()))['note_id']}
        conn.execute('UPDATE pump_docs SET jobber=?, status=?, updated_at=? WHERE id=?',
                     (json.dumps({**j, **ref}), 'done', _now_text(), doc_id))
        if doc.get('case_id'):
            _set_step(conn, doc['case_id'], 'report_logged', at=_today().isoformat(), by=actor)
            if target_type == 'job' and not sec:
                case = conn.execute('SELECT jobber FROM pump_cases WHERE id=?', (doc['case_id'],)).fetchone()
                j = json.loads(case['jobber'] or '{}')
                j.setdefault('job', {'id': target_id})
                conn.execute('UPDATE pump_cases SET jobber=? WHERE id=?', (json.dumps(j), doc['case_id']))
            _event(conn, actor, 'report logged in Jobber',
                   (f"{sec['location']} page - " if sec else '') + f"note on {target_type}" +
                   (' with the file attached' if attached else ' (file linked, not attached)'),
                   case_id=doc['case_id'], doc_id=doc_id)
            if target_type == 'job' and not sec:
                merge_report_items(conn, target_id, actor)
        conn.commit()
        return {**ref, 'section': section, 'location': sec['location']} if sec else ref
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════════════════════
# what needs doing
# ═════════════════════════════════════════════════════════════════════════════

# ── Chasing the vendor ───────────────────────────────────────────────────────
# A job waiting on the vendor is either a quote (their visit to look, or their
# price) or a job (getting it on their calendar, then doing it). Each time the
# office calls or emails them, what they said and when they'll be out is kept
# on the job; the app then says whether someone still needs to follow up:
#   - they gave a date and it hasn't passed -> wait, check back the weekday after
#   - the date passed and it isn't done      -> follow up
#   - no date, and nobody has asked them in VENDOR_FOLLOW_DAYS -> follow up

CHASE_PHASES = {'assessment': 'quote', 'vendor_quote': 'quote', 'scheduled': 'job', 'work_done': 'job'}
CHASE_SKIP_CATEGORIES = ('maintenance', 'scada')   # followed by the account sheets / SCADA tab
VENDOR_FOLLOW_DAYS = max(1, int(os.environ.get('PUMPS_VENDOR_FOLLOW_DAYS', '3') or 3))
# A quote saying parts take weeks (Carlisle, Oct 2026: "2-3 weeks"): once the
# client approves, the job waits on the parts; ask the vendor about them this
# many days after the approval.
PARTS_FOLLOW_DAYS = max(1, int(os.environ.get('PUMPS_PARTS_FOLLOW_DAYS', '14') or 14))
FOLLOW_HOW = ('call', 'text', 'email', 'in person')


def _weekday_from(d):
    """d, or the Monday after when it falls on a weekend."""
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _workdays_after(d, n):
    for _ in range(n):
        d = _weekday_from(d + timedelta(days=1))
    return d


def _phase_since(case):
    """When the job started waiting on the vendor: its last step done, else when it was opened."""
    days = [s.get('at')[:10] for s in (case.get('steps') or {}).values() if isinstance(s, dict) and s.get('at')]
    days += [_iso_date(case.get('opened_on')) or (case.get('created_at') or '')[:10]]
    days = [x for x in days if _iso_date(x)]
    return date.fromisoformat(max(days)) if days else _today()


def vendor_chase(case, today=None):
    """Whether someone needs to follow up with the vendor on an open job, or None
    when the job isn't waiting on the vendor."""
    phase = CHASE_PHASES.get(case.get('stage'))
    if case.get('status') != 'open' or not phase or case.get('category') in CHASE_SKIP_CATEGORIES:
        return None
    today = today or _today()
    vendor = case.get('vendor') or 'Wettech'
    f = case.get('vendor_follow') or {}
    if f.get('off_stage') and f['off_stage'] == case.get('stage'):
        return None   # the office said no follow-up is needed at this step
    if f.get('phase') != phase:
        f = {}   # what they said was about the quote; the job has moved on
    expect = _iso_date(f.get('expect_by'))
    if not expect and phase == 'job':
        expect = _iso_date(case.get('scheduled_for'))
    if not expect and case.get('stage') == 'assessment':
        expect = _iso_date(((case.get('steps') or {}).get('assessment') or {}).get('due'))
    last = _iso_date((f.get('at') or '')[:10])
    since = date.fromisoformat(last) if last else _phase_since(case)
    # Approved: the vendor orders the parts, and gives a date once they are in -
    # the job waits on the parts, not on scheduling (Oct 2026).
    parts_wait = case['stage'] == 'scheduled' and vendor != IN_HOUSE
    parts = (case.get('parts_lead') or '') if parts_wait else ''
    approved = _iso_date(((case.get('steps') or {}).get('client_approved') or {}).get('at')) or since.isoformat()
    if _iso_date(f.get('check_on')):
        check = date.fromisoformat(f['check_on'])
    elif expect:
        check = _workdays_after(date.fromisoformat(expect), 1)
    elif parts_wait and not last:
        # Waiting on parts: ask about them PARTS_FOLLOW_DAYS after the approval.
        check = _weekday_from(date.fromisoformat(approved) + timedelta(days=PARTS_FOLLOW_DAYS))
    elif case['stage'] == 'scheduled' and not last:
        check = since   # approved: ask them for a date straight away
    else:
        check = _workdays_after(since, VENDOR_FOLLOW_DAYS)
    contact = _vendor_contact(vendor)[0]
    who = f.get('who') or contact
    what = {'assessment': 'visit to look', 'vendor_quote': 'quote', 'scheduled': 'date', 'work_done': 'work'}[case['stage']]
    if expect and date.fromisoformat(expect) < today:
        reason = f"{who} said by {expect} - the {what} isn't in yet"
    elif expect:
        reason = f"{who} said by {expect}"
    elif parts_wait and not last:
        reason = (f"approved {approved}; {'parts take ' + parts if parts else 'waiting on parts'} - ask {who} "
                  f"if the parts are in and when they can schedule it")
    elif last:
        reason = f"asked {who} {last}, no date given"
    else:
        reason = f"nobody has asked {vendor} yet"
    return {'phase': phase, 'state': 'follow_up' if today >= check else 'waiting', 'check_on': check.isoformat(),
            'expect_by': expect or '', 'last_at': last or '', 'said': f.get('said') or '', 'who': who,
            'how': f.get('how') or '', 'by': f.get('by') or '', 'days': (today - since).days, 'reason': reason,
            'contact': contact, 'parts': parts, 'parts_wait': parts_wait}


def log_vendor_follow(conn, case_id, actor, who='', how='call', said='', expect_by='', check_on='', today=None):
    """We chased the vendor: keep what they said and when they'll be out. A date
    for a job not yet scheduled schedules it for that day."""
    row = conn.execute('SELECT * FROM pump_cases WHERE id=?', (case_id,)).fetchone()
    if not row:
        return None
    c = _case_dict(row)
    phase = CHASE_PHASES.get(c['stage'])
    if not phase:
        raise ValueError('This job is not waiting on the vendor')
    today = today or _today()
    expect, check = _iso_date(expect_by) or '', _iso_date(check_on) or ''
    if expect_by and not expect:
        raise ValueError('The date they gave must be a date (YYYY-MM-DD)')
    how = how if how in FOLLOW_HOW else 'call'
    who = (who or '').strip()[:80] or _vendor_contact(c.get('vendor') or 'Wettech')[0]
    said = (said or '').strip()[:500]
    conn.execute('UPDATE pump_cases SET vendor_follow=?, last_activity_at=?, updated_at=? WHERE id=?',
                 (json.dumps({'phase': phase, 'at': _now_text(), 'by': actor, 'who': who, 'how': how, 'said': said,
                              'expect_by': expect, 'check_on': check}), _now_text(), _now_text(), case_id))
    if expect and c['stage'] == 'assessment':
        _set_assessment(conn, case_id, expect, by=actor)
    if expect and c['stage'] == 'scheduled':
        if not _iso_date(c.get('scheduled_for')):
            conn.execute('UPDATE pump_cases SET scheduled_for=? WHERE id=?', (expect, case_id))
        _set_step(conn, case_id, 'scheduled', at=today.isoformat(), by=actor)
    elif expect and c['stage'] == 'work_done' and not _iso_date(c.get('scheduled_for')):
        conn.execute('UPDATE pump_cases SET scheduled_for=? WHERE id=?', (expect, case_id))
    _event(conn, actor, 'followed up with the vendor',
           ' · '.join(x for x in (f'{how} with {who}', f'"{said}"' if said else '', f'by {expect}' if expect else '',
                                  f'check back {check}' if check else '') if x), case_id=case_id)
    return True


# Oct 9 2026: Simon followed up with Tom at Wettech about Homewood Suites -
# he'll be out later next week (by Fri Oct 16).
HOMEWOOD_FOLLOW = {'who': 'Tom', 'how': 'call', 'said': 'He will be out there later next week.',
                   'expect_by': '2026-10-16'}


def _seed_homewood_follow_up(conn):
    if not _claim_once(conn, 'homewood_follow_oct26'):
        return
    rows = [r for r in conn.execute("SELECT * FROM pump_cases WHERE status='open' AND (title LIKE '%homewood%' "
                                    "OR client_name LIKE '%homewood%' OR site LIKE '%homewood%') ORDER BY id")]
    rows = [r for r in rows if CHASE_PHASES.get(r['stage'])]
    for r in rows:
        log_vendor_follow(conn, r['id'], 'Simon', **HOMEWOOD_FOLLOW, today=date(2026, 10, 9))
    if not rows:
        add_todo(conn, 'homewood_follow_oct26', 'Homewood Suites: make sure Tom (Wettech) gets out there',
                 'Tom said on Oct 9 he will be out later next week. Homewood Suites is not a job in Pumps yet - '
                 'track it from the Jobber tab (or add it), then log the follow-up on it.', {'account': 'Homewood Suites'},
                 due_on='2026-10-19')
    conn.commit()


def _waiting_on_work(c):
    """An approved job nobody has to chase: the office said no follow-up is
    needed, or gave a status since the approval - parts ordered, waiting on the
    vendor, under way (Huntington #6, Oct 2026: "Parts ordered - should be
    done today" still showed as Schedule)."""
    if ((c.get('vendor_follow') or {}).get('off_stage') or '') == c.get('stage'):
        return True
    st = c.get('job_status') or {}
    approved = (((c.get('steps') or {}).get('client_approved') or {}).get('at') or '')[:10]
    return st.get('kind') in ('parts_ordered', 'waiting_vendor', 'scheduled', 'in_progress', 'on_hold') and \
        (st.get('at') or '')[:10] >= approved


def work_queue(conn):
    # A report on an item of its own that belongs to a bill's item: joined first, so neither is a to-do.
    merge_all_report_items(conn)
    move_early_bills(conn)
    merge_billed_duplicates(conn)
    cases = list_cases(conn, 'open')
    issues = [dict(r) for r in conn.execute('''SELECT i.*, c.title, c.client_name FROM pump_issues i
                                               LEFT JOIN pump_cases c ON c.id = i.case_id
                                               WHERE i.resolved_at IS NULL ORDER BY i.id''')]
    # Jobs where someone needs to chase the vendor come out of the waiting lists
    # into their own (To do); the rest wait, with what the vendor said.
    # (An approved job still to be scheduled stays a "Schedule" to-do until the
    # vendor has been asked, then waits.)
    by_stage, chase = {}, []
    for c in cases:
        state = (c.get('chase') or {}).get('state')
        if state == 'follow_up' and (c['stage'] != 'scheduled' or c['chase'].get('parts_wait')):
            chase.append(c)
        elif c['stage'] == 'scheduled' and (state == 'waiting' or (not c.get('chase') and _waiting_on_work(c))):
            by_stage.setdefault('scheduling_asked', []).append(c)
        else:
            by_stage.setdefault(c['stage'], []).append(c)
    chase.sort(key=lambda c: (c['chase']['check_on'], c['id']))
    # A drafted invoice not sent yet is always "Send invoice", whatever step the job is on (Sunshine Lake
    # Park, Oct 2026: its job sat on "Report logged", which has no list, so draft #36869 showed nowhere).
    for st in [k for k in by_stage if k not in ('closed', 'done')]:
        stay = []
        for c in by_stage[st]:
            inv = (c.get('jobber') or {}).get('invoice') or {}
            drafted = ((c.get('steps') or {}).get('invoice_drafted') or {}).get('at')
            sent = ((c.get('steps') or {}).get('closed') or {}).get('at')
            if (inv.get('id') or (drafted and c.get('sei_invoice_number'))) and (inv.get('status') or 'draft') == 'draft' \
                    and not sent:
                by_stage.setdefault('closed', []).append(c)
            else:
                stay.append(c)
        by_stage[st] = stay
    review_docs = [_doc_dict(r) for r in conn.execute(
        "SELECT * FROM pump_docs WHERE status IN ('review','new') OR (case_id IS NULL AND status != 'dismissed') "
        "ORDER BY id DESC")]
    bills_to_draft = [_doc_dict(r) for r in conn.execute(
        "SELECT d.* FROM pump_docs d JOIN pump_cases c ON c.id = d.case_id WHERE d.kind='bill' "
        "AND d.status != 'dismissed' AND (d.jobber IS NULL OR d.jobber NOT LIKE '%invoice_id%') "
        "AND c.status='open' AND COALESCE(json_extract(c.steps, '$.invoice_drafted.na'), 0) = 0 "
        "AND NOT (c.category='diver' AND c.vendor='Gulfshore') "
        "AND COALESCE(json_extract(c.steps, '$.invoice_drafted.at'), '') = '' ORDER BY d.id")]
    bill_cases = {r['id']: dict(r) for r in conn.execute(
        f"SELECT * FROM pump_cases WHERE id IN ({','.join('?' * len(bills_to_draft))})",
        [d['case_id'] for d in bills_to_draft])} if bills_to_draft else {}
    for d in bills_to_draft:
        d['bill_kind'] = bill_kind_note(d, bill_cases.get(d['case_id']))
    for d in bills_to_draft:
        # The account's notes where the invoice is made (Evergreen: attach the report in
        # Jobber but don't send it - only report the gallons used for the north and south pumps).
        crow = conn.execute('SELECT client_name, title, site FROM pump_cases WHERE id=?', (d['case_id'],)).fetchone()
        acct = account_info(conn, dict(crow)) if crow else None
        d['account_note'] = (acct or {}).get('notes') or ''
        d['account_name'] = (acct or {}).get('name') or ''
    to_quote_ids = {c['id'] for c in by_stage.get('client_quote', []) if not (c['jobber'].get('quote') or {}).get('id')}
    quotes_to_draft = [d for d in (_doc_dict(r) for r in conn.execute(
        "SELECT * FROM pump_docs WHERE kind='quote' AND status != 'dismissed' "
        "AND (jobber IS NULL OR jobber NOT LIKE '%quote_id%') ORDER BY id")) if d['case_id'] in to_quote_ids]
    vendor_bills_to_pay = [{**c, 'pay_email': _state_get(f"pay_email:{c['id']}", conn=conn) or {}}
                           for c in list_cases(conn, 'all') if c['status'] != 'cancelled'
                           and c['vendor_pay']['state'] == 'due']
    reports_to_log = [_doc_dict(r) for r in conn.execute(
        "SELECT * FROM pump_docs WHERE kind='report' AND status != 'dismissed' "
        "AND (jobber IS NULL OR jobber NOT LIKE '%note_id%') ORDER BY id")]
    scada = [s for s in scada_rows(conn) if s['state'] in ('overdue', 'due_soon')]
    for c in by_stage.get('client_quote', []) + by_stage.get('client_approved', []) + by_stage.get('closed', []):
        c['follow_up'] = follow_up_for(conn, c)
    for sc in scada:
        sc['follow_up'] = follow_up_for(conn, sc)
    new_requests = untracked_jobber_items(conn)
    stale = [c for c in cases if c['idle_days'] >= STALE_DAYS]

    follow_visits(conn)
    conn.commit()
    todos = [_todo_dict(r) for r in conn.execute("SELECT * FROM pump_todos WHERE done_at IS NULL AND kind != 'visit' "
                                                 "ORDER BY COALESCE(NULLIF(due_on, ''), created_at), id")]
    visits = [_todo_dict(r) for r in conn.execute("SELECT * FROM pump_todos WHERE done_at IS NULL AND kind='visit' "
                                                  "ORDER BY created_at, id")]
    # Each row's key for the ✕ (take it off the To do list); rows taken off are left out.
    hidden = {r[0] for r in conn.execute('SELECT key FROM pump_todo_hidden')}

    def keep(rows, key):
        out = []
        for r in rows:
            k = key(r)
            if k not in hidden:
                out.append({**r, 'todo_key': k})
        return out
    stage_key = lambda c: f"case:{c['id']}:{c['stage']}"
    doc_key = lambda d: f"doc:{d['id']}"
    issues = keep(issues, lambda i: f"issue:{i['id']}")
    by_stage = {st: keep(cs, stage_key) for st, cs in by_stage.items()}
    bills_to_draft, quotes_to_draft = keep(bills_to_draft, doc_key), keep(quotes_to_draft, doc_key)
    reports_to_log, review_docs = keep(reports_to_log, doc_key), keep(review_docs, doc_key)
    vendor_bills_to_pay = keep(vendor_bills_to_pay, lambda c: f"pay:{c['id']}")
    scada = keep(scada, lambda sc: f"scada:{sc['id']}:{sc.get('next_due_on') or ''}")
    new_requests = keep(new_requests, lambda it: f"jobber:{it['jobber_id']}")
    todos = keep(todos, lambda t: f"todo:{t['id']}")
    visits = keep(visits, lambda t: f"todo:{t['id']}")
    chase = keep(chase, lambda c: f"chase:{c['id']}:{c['chase']['check_on']}")
    return {
        'issues': issues,
        'vendor_follow_ups': chase,
        'needs_scheduling': by_stage.get('scheduled', []),
        'scheduling_asked': by_stage.get('scheduling_asked', []),
        'waiting_assessment': by_stage.get('assessment', []),
        'waiting_vendor_quote': by_stage.get('vendor_quote', []),
        'to_quote_client': [_with_quote_link(conn, c) for c in by_stage.get('client_quote', [])],
        'waiting_approval': by_stage.get('client_approved', []),
        'waiting_work': by_stage.get('work_done', []),
        'waiting_bill': by_stage.get('vendor_bill', []),
        'bills_to_check': by_stage.get('bill_checked', []),
        'bills_to_draft': bills_to_draft,
        'todos': todos,
        'waiting_visits': visits,
        'quotes_to_draft': quotes_to_draft,
        'vendor_bills_to_pay': vendor_bills_to_pay,
        'reports_to_log': reports_to_log,
        'ready_to_close': [_with_invoice_link(conn, c) for c in by_stage.get('closed', [])],
        'review_docs': review_docs,
        'scada_attention': scada,
        'new_jobber_requests': new_requests,
        'stale': stale,
        'open_count': len(cases),
    }


# ── Who to follow up with ────────────────────────────────────────────────────
# The account's contact from the office's master list when it has one; for the
# email, otherwise the client's AP/billing address in Jobber (Jobber labels every
# email "Main", so it is picked by the address), else the client's primary email.

_BILLING_EMAIL = re.compile(r'(?i)^(ap|a\.p|accountspayable|accounts[._-]?payable|payables?|invoices?|invoicing|'
                            r'billing|bills|accounting|accounts|finance)([._-][^@]*)?@')
_EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')
_PHONE_RE = re.compile(r'\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}')


def billing_emails(emails):
    """The address(es) to follow up with from a Jobber client's emails ([{address, primary}]):
    AP/billing ones first, else the primary, else the first."""
    seen, uniq, primary = set(), [], []
    for e in emails or []:
        addr = ((e or {}).get('address') or '').strip()
        if not addr or addr.lower() in seen:
            continue
        seen.add(addr.lower())
        uniq.append(addr)
        if e.get('primary'):
            primary.append(addr)
    ap = [a for a in uniq if _BILLING_EMAIL.match(a)]
    return ap or primary[:1] or uniq[:1]


def _client_id_for(conn, item):
    cid = item.get('jobber_client_id') or ''
    if cid:
        return cid
    want = _norm_name(item.get('jobber_name') or item.get('client_name') or item.get('client') or '')
    if not want:
        return ''
    for r in conn.execute("SELECT client_id, client_name FROM pump_jobber_items WHERE client_id != '' "
                          "ORDER BY updated_at DESC"):
        have = _norm_name(r['client_name'])
        if have and (have == want or (len(want) >= 6 and want in have)):
            return r['client_id']
    return ''


def _norm_name(text):
    return re.sub(r'[^a-z0-9]', '', (text or '').lower())


def refresh_client_contacts(conn, max_age_days=3):
    """Fetch the emails of the clients the to-dos are about (open jobs, SCADA coming due)
    when not fetched in the last few days. Returns any errors."""
    ids = {r[0] for r in conn.execute("SELECT DISTINCT jobber_client_id FROM pump_cases WHERE status='open' "
                                      "AND jobber_client_id != ''")}
    for sc in scada_rows(conn):
        if sc['state'] in ('overdue', 'due_soon'):
            cid = _client_id_for(conn, sc)
            if cid:
                ids.add(cid)
    cutoff = (datetime.now(TZ) - timedelta(days=max_age_days)).strftime('%Y-%m-%d %H:%M:%S')
    fresh = {r[0] for r in conn.execute("SELECT client_id FROM pump_client_contacts WHERE fetched_at >= ?", (cutoff,))}
    errors = []
    for cid in sorted(ids - fresh):
        try:
            data = jobber_gql('query($id: EncodedId!) { client(id: $id) { id name emails { address primary } } }',
                              {'id': cid})
        except JobberError as e:
            errors.append(f'Client emails: {e}')
            break
        cl = data.get('client') or {}
        conn.execute("INSERT OR REPLACE INTO pump_client_contacts (client_id, name, emails, fetched_at) VALUES (?,?,?,?)",
                     (cid, cl.get('name') or '', json.dumps(cl.get('emails') or []), _now_text()))
    return errors


def follow_up_for(conn, item):
    """{name, email, phone, source} of who to follow up with about a job or SCADA renewal."""
    out = {'name': '', 'email': '', 'phone': '', 'source': ''}
    acct = account_info(conn, item) if item.get('title') is not None or item.get('site') is not None else None
    if not acct:
        name = match_account(' '.join(x for x in (item.get('client_name'), item.get('client')) if x), conn)
        if name:
            notes = [r[0] for r in conn.execute("SELECT notes FROM pump_maint_accounts WHERE name=? AND notes != ''",
                                                (name,))]
            acct = {'name': name, 'notes': '\n'.join(notes)}
    m = re.search(r'(?im)account contact:\s*([^\n]+)', (acct or {}).get('notes') or '')
    if m:
        seg = m.group(1)
        first = seg.split(',')[0].strip().rstrip('.')
        if first and not _EMAIL_RE.search(first) and not _PHONE_RE.search(first):
            out['name'] = first
        em = _EMAIL_RE.search(seg)
        ph = _PHONE_RE.search(seg)
        out['email'] = em.group(0).rstrip('.') if em else ''
        out['phone'] = ph.group(0) if ph else ''
        out['source'] = 'account'
    if not out['email']:
        cid = _client_id_for(conn, item)
        row = conn.execute("SELECT emails FROM pump_client_contacts WHERE client_id=?", (cid,)).fetchone() if cid else None
        if row:
            picked = billing_emails(json.loads(row[0] or '[]'))
            if picked:
                out['email'] = ', '.join(picked)
                out['source'] = out['source'] or 'jobber'
                out['email_from'] = 'jobber_ap' if any(_BILLING_EMAIL.match(a) for a in picked) else 'jobber'
    return out


def _notify(event, payload):
    if not WEBHOOK_URL:
        return
    def go():
        try:
            body = json.dumps({'event': event, 'at': _now_text(), **payload})
            headers = {'Content-Type': 'application/json'}
            if OPENCLAW_API_KEY:
                headers['X-Pumps-Signature'] = hmac.new(OPENCLAW_API_KEY.encode(), body.encode(), 'sha256').hexdigest()
            http_requests.post(WEBHOOK_URL, data=body, headers=headers, timeout=10)
        except Exception as e:
            print(f'  ⚠ Pumps webhook failed: {e}')
    threading.Thread(target=go, daemon=True).start()


# ═════════════════════════════════════════════════════════════════════════════
# HTTP: one handler, two doors (office session at /pumps/api, OpenClaw at /api/pumps)
# ═════════════════════════════════════════════════════════════════════════════

def pumps_allowed():
    """May this login see Pumps (the dashboard tile and /pumps)?"""
    if 'username' not in session or session.get('role') in NEVER_ROLES:
        return False
    if PUMPS_USERS:
        return session['username'].lower() in PUMPS_USERS
    return session.get('role') in PUMPS_ROLES


def _bearer_ok():
    if not OPENCLAW_API_KEY or not OPENCLAW_ENABLED:
        return False
    return hmac.compare_digest(request.headers.get('Authorization', ''), f'Bearer {OPENCLAW_API_KEY}')


_ROUTES = []


# Jobber is only ever changed when a person clicks the button that does it (the office, Oct 22
# 2026: "human involved and confirm every move - 100% of the time"). Those handlers are marked
# @jobber_button; only a signed-in person's click on one may write to Jobber. Everything else -
# the mailbox scan, the Jobber sync, the schedule, uploads, the bot - is refused, and what it
# would have done is left on the to-do list with its button.
_HUMAN_JOBBER = contextvars.ContextVar('human_jobber', default=False)


def _human_clicked():
    """Is this a person's click on a Jobber button (see jobber_button)?"""
    return _HUMAN_JOBBER.get()


def jobber_button(fn):
    fn._jobber_button = True
    return fn


def api(path, methods=('GET',)):
    def deco(fn):
        _ROUTES.append((path, methods, fn))
        return fn
    return deco


def _register_routes(app, csrf):
    for path, methods, fn in _ROUTES:
        def office_view(fn=fn, **kw):
            if not pumps_allowed():
                return jsonify({'success': False, 'error': 'Not signed in to Pumps'}), 401
            actor = session.get('full_name') or session.get('username')
            human = _HUMAN_JOBBER.set(bool(getattr(fn, '_jobber_button', False)) and request.method != 'GET')
            try:
                return _call(fn, actor, kw)
            finally:
                _HUMAN_JOBBER.reset(human)

        def bot_view(fn=fn, **kw):
            if not _bearer_ok():
                return jsonify({'success': False, 'error': 'Unauthorized'}), 401
            return _call(fn, BOT, kw)

        name = fn.__name__
        office_view.__name__ = f'office_{name}'
        bot_view.__name__ = f'bot_{name}'
        bp.add_url_rule(f'/pumps/api{path}', f'office_{name}', office_view, methods=list(methods))
        bp.add_url_rule(f'/api/pumps{path}', f'bot_{name}', bot_view, methods=list(methods))
        # Bearer-token calls carry no browser cookie, so no CSRF token either.
        # (The office door keeps CSRF; the bot door ignores the session.)
        csrf.exempt(bot_view)


def _call(fn, actor, kw):
    action = _start_undo(actor) if request.method in ('POST', 'PATCH', 'PUT', 'DELETE') and \
        not re.search(UNDO_SKIP, request.path) else 0
    token = _UNDO_ACTION.set(action)
    try:
        out = fn(actor, **kw)
    except (ValueError, KeyError) as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except JobberError as e:
        return jsonify({'success': False, 'error': str(e)}), 502
    finally:
        _UNDO_ACTION.reset(token)
        if action:
            _finish_undo(action)
    if isinstance(out, tuple):
        body, code = out
        return jsonify(body), code
    if isinstance(out, Response):
        return out
    return jsonify({'success': True, **(out or {})})


def _json():
    return request.get_json(silent=True) or {}


UNDO_SKIP = r'/(undo(/\d+)?|scan|jobber/sync|todos/reword)$'  # clicks not put on the undo list
UNDO_HOURS = 24
# What a click was, for the Undo list: (path pattern, label). {0} = the number in the path.
UNDO_LABELS = (
    (r'/cases/(\d+)/jobber_quote$', 'Linked a Jobber quote to job #{0}'),
    (r'/cases/(\d+)/vendor_email/send$', 'Emailed the vendor about job #{0}'),
    (r'/cases/(\d+)/pay_email/send$', 'Emailed Christian to pay for job #{0}'),
    (r'/cases/(\d+)/done$', 'Marked a step on job #{0}'),
    (r'/cases/(\d+)/vendor_follow$', 'Logged a follow-up with the vendor on job #{0}'),
    (r'/cases/(\d+)/status$', 'Status update on job #{0}'),
    (r'/cases/(\d+)/delete$', 'Deleted job #{0}'),
    (r'/cases/(\d+)/approved$', 'Marked job #{0} approved'),
    (r'/cases/(\d+)$', 'Changed job #{0}'),
    (r'/cases$', 'Added a job'),
    (r'/sheet/save$', 'Saved the sheet'),
    (r'/docs/(\d+)/invoice$', 'Drafted an invoice from document #{0}'),
    (r'/docs/(\d+)/quote$', 'Drafted a quote from document #{0}'),
    (r'/docs/(\d+)/(read_again|reread)$', 'Read document #{0} again'),
    (r'/docs/(\d+)/rebrand$', 'Rebranded document #{0}'),
    (r'/docs/(\d+)/report_note$', 'Added a report note to document #{0}'),
    (r'/docs/(\d+)$', 'Changed document #{0}'),
    (r'/docs$', 'Uploaded a document'),
    (r'/site-names', 'Changed a site name'),
    (r'/issues/(\d+)/bill-anyway$', 'Billed anyway'),
    (r'/issues/(\d+)/resolve$', 'Resolved an issue'),
    (r'/jobber/items/', 'Changed a Jobber item'),
    (r'/dives/send$', 'Sent the dive email'),
    (r'/dives/', 'Changed a dive site'),
    (r'/todos/(\d+)/done$', 'Ticked a to-do'),
    (r'/todos/(\d+)/edit$', 'Edited a to-do'),
    (r'/todos/hide$', 'Took a row off the To do list'),
    (r'/accounts/ready$', 'Client ready for maintenance'),
    (r'/todos', 'Changed a to-do'),
    (r'/scada', 'Changed SCADA'),
    (r'/maint', 'Changed a maintenance account'),
    (r'/digest/send$', 'Sent the digest'),
)
# What undo can't take back: things that already left the app.
UNDO_OUTSIDE = (
    (r'/docs/\d+/quote$', "The draft quote in Jobber stays - delete it there if you don't want it."),
    (r'/docs/\d+/invoice$', "The draft invoice in Jobber stays - delete it there if you don't want it."),
    (r'/docs/\d+/(read_again|reread)$', "If it drafted in Jobber, that draft stays - delete it there if you don't want it."),
    (r'/(vendor_email|pay_email|dives|digest)/send$', 'The email was already sent.'),
)


def _start_undo(actor):
    conn = sqlite3.connect(CFG['db_path'], timeout=30)
    try:
        cur = conn.execute('INSERT INTO pump_undo_actions (actor, path, created_at) VALUES (?,?,?)',
                           (actor or '', request.path, _now_text()))
        conn.commit()
        return cur.lastrowid
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def _undo_label(path):
    path = path.split('/api', 1)[-1].replace('/pumps', '', 1) if '/api' in path else path
    label = next((lab.format(*m.groups()) for pat, lab in UNDO_LABELS for m in [re.search(pat, path)] if m), 'A change')
    outside = next((note for pat, note in UNDO_OUTSIDE if re.search(pat, path)), '')
    return label, outside


def _finish_undo(action):
    """Keep the record only if the click changed something; drop old ones."""
    conn = sqlite3.connect(CFG['db_path'], timeout=30)
    try:
        if not conn.execute('SELECT 1 FROM pump_undo_rows WHERE action_id=? LIMIT 1', (action,)).fetchone():
            conn.execute('DELETE FROM pump_undo_actions WHERE id=?', (action,))
        else:
            path = conn.execute('SELECT path FROM pump_undo_actions WHERE id=?', (action,)).fetchone()[0]
            label, outside = _undo_label(path)
            conn.execute('UPDATE pump_undo_actions SET label=?, external=? WHERE id=?', (label, outside, action))
        cutoff = (_now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
        old = [r[0] for r in conn.execute('SELECT id FROM pump_undo_actions WHERE created_at < ?', (cutoff,))]
        for i in old:
            conn.execute('DELETE FROM pump_undo_rows WHERE action_id=?', (i,))
            conn.execute('DELETE FROM pump_undo_actions WHERE id=?', (i,))
        conn.commit()
    finally:
        conn.close()


def recent_actions(limit=15):
    since = (_now() - timedelta(hours=UNDO_HOURS)).strftime('%Y-%m-%d %H:%M:%S')
    conn = _conn()
    try:
        return [dict(r) for r in conn.execute(
            'SELECT id, actor, label, external, created_at FROM pump_undo_actions WHERE undone_at IS NULL '
            "AND label != '' AND created_at >= ? ORDER BY id DESC LIMIT ?", (since, limit))]
    finally:
        conn.close()


class UndoBlocked(ValueError):
    """A later click changed the same rows: undo those too (cascade) or not at all."""
    def __init__(self, labels):
        self.labels = labels
        super().__init__(f'"{labels[0]}" changed the same thing afterwards - undo that too?')


def undo_action(action_id, actor, cascade=False):
    """Put back every row the click added, changed or deleted, newest first.
    When a later click changed the same rows, it is refused unless cascade -
    then those later clicks are undone first."""
    conn = _conn()
    try:
        a = conn.execute('SELECT * FROM pump_undo_actions WHERE id=?', (action_id,)).fetchone()
        if not a or not a['label']:
            raise ValueError('Nothing to undo there')
        if a['undone_at']:
            raise ValueError('Already undone')
        since = (_now() - timedelta(hours=UNDO_HOURS)).strftime('%Y-%m-%d %H:%M:%S')
        if a['created_at'] < since:
            raise ValueError(f'Only the last {UNDO_HOURS} hours can be undone')
        rows = conn.execute('SELECT * FROM pump_undo_rows WHERE action_id=? ORDER BY id DESC', (action_id,)).fetchall()
        later = conn.execute(
            'SELECT DISTINCT x.label FROM pump_undo_rows r JOIN pump_undo_actions x ON x.id = r.action_id '
            'WHERE r.action_id > ? AND x.undone_at IS NULL AND EXISTS (SELECT 1 FROM pump_undo_rows o '
            'WHERE o.action_id=? AND o.tbl=r.tbl AND o.row_id=r.row_id)', (action_id, action_id)).fetchall()
        if later and not cascade:
            raise UndoBlocked([r[0] for r in later])
        if later:
            # Undo the later clicks that changed the same rows first, newest first.
            ids = [r[0] for r in conn.execute(
                'SELECT DISTINCT r.action_id FROM pump_undo_rows r JOIN pump_undo_actions x ON x.id = r.action_id '
                'WHERE r.action_id > ? AND x.undone_at IS NULL AND EXISTS (SELECT 1 FROM pump_undo_rows o '
                'WHERE o.action_id=? AND o.tbl=r.tbl AND o.row_id=r.row_id) ORDER BY r.action_id DESC',
                (action_id, action_id))]
            conn.close()
            for i in ids:
                try:
                    undo_action(i, actor, cascade=True)
                except ValueError as e:
                    if 'Already undone' not in str(e):
                        raise
            conn = _conn()
        for r in rows:
            t = r['tbl']
            if t not in UNDO_TABLES:
                continue
            cols = {c[1] for c in conn.execute(f'PRAGMA table_info({t})')}
            if r['op'] == 'I':
                conn.execute(f'DELETE FROM {t} WHERE rowid=?', (r['row_id'],))
                continue
            old = {k: v for k, v in json.loads(r['old'] or '{}').items() if k in cols}
            if r['op'] == 'U':
                conn.execute(f"UPDATE {t} SET {', '.join(f'{k}=?' for k in old)} WHERE rowid=?",
                             (*old.values(), r['row_id']))
            else:
                conn.execute(f"INSERT OR REPLACE INTO {t} (rowid, {', '.join(old)}) VALUES "
                             f"(?, {', '.join('?' for _ in old)})", (r['row_id'], *old.values()))
        conn.execute('UPDATE pump_undo_actions SET undone_at=?, undone_by=? WHERE id=?',
                     (_now_text(), actor or '', action_id))
        conn.commit()
        return {'label': a['label'], 'outside': a['external'] or ''}
    finally:
        conn.close()


BOT = 'OpenClaw'
# Decisions that stay with the office: OpenClaw may not tick these steps.
OFFICE_ONLY_STEPS = ('bill_checked', 'closed')


def _office_only(actor, what):
    if actor == BOT:
        return {'success': False, 'error': f'{what} is for the office, not OpenClaw.'}, 403
    return None


# ── reading ──────────────────────────────────────────────────────────────────

@api('/summary')
def h_summary(actor):
    ensure_monthly_todos()
    conn = _conn()
    try:
        close_stale_todos(conn)
        fix_terms_as_po(conn)
        fix_maintenance_bills(conn)
        conn.commit()
        q = work_queue(conn)
        # Bills Christian can pay that he hasn't been sent yet - the Bills to pay tab's badge.
        q['bills_to_pay_count'] = sum(1 for g in bills_to_pay(conn) for b in g['bills']
                                      if b['payable'] and not b['asked_at'])
        return {'queue': q, 'counts': {k: len(v) for k, v in q.items() if isinstance(v, list)},
                'scan': _state_get('scan_status') or {}, 'jobber': {**jobber_status(),
                                                                     'sync': jobber_sync_state()},
                'claude': USE_CLAUDE, 'email': bool(CFG.get('email_enabled')), 'version': APP_VERSION}
    finally:
        conn.close()


@api('/cases')
def h_cases(actor):
    conn = _conn()
    try:
        return {'cases': list_cases(conn, request.args.get('status', 'open'), request.args.get('month') or None,
                                    request.args.get('q', '').strip())}
    finally:
        conn.close()


@api('/cases/<int:case_id>')
def h_case(actor, case_id):
    conn = _conn()
    try:
        d = case_detail(conn, case_id)
        return ({'success': False, 'error': 'Not found'}, 404) if not d else {'case': d}
    finally:
        conn.close()


def _app_setting(conn, key, default=''):
    try:
        row = conn.execute('SELECT value FROM app_settings WHERE key=?', (key,)).fetchone()
        return (row[0] if row else '') or default
    except sqlite3.Error:
        return default


def vendor_pay_email(conn, case_id, signer=''):
    """A ready-to-paste email asking Christian to pay the vendor's bill, once
    the client has paid our Jobber invoice."""
    row = conn.execute('SELECT * FROM pump_cases WHERE id=?', (case_id,)).fetchone()
    if not row:
        return None
    c = _case_dict(row)
    bill = conn.execute("SELECT id, doc_number, total, file_name FROM pump_docs WHERE case_id=? AND kind='bill' "
                        "AND status != 'dismissed' ORDER BY id DESC", (case_id,)).fetchone()
    vendor = c.get('vendor') or 'Wettech'
    number = c.get('vendor_bill_number') or (bill['doc_number'] if bill else '') or ''
    amount = next((v for v in (c.get('vendor_bill_total'), c.get('vendor_bill_amount'), bill['total'] if bill else None)
                   if v is not None), None)
    inv = (c.get('jobber') or {}).get('invoice') or {}
    our_no = inv.get('number') or c.get('sei_invoice_number') or ''
    title = short_name(c.get('title') or '', 90)
    client = c.get('client_name') or ''
    job = title if client and title.lower().startswith(client.lower()) else ' - '.join(x for x in [client, title] if x)
    lines = [f'Hi Christian,', '',
             f"Please pay {vendor} invoice{' #' + number if number else ''}"
             f"{f' for ${amount:,.2f}' if amount is not None else ''}.", '',
             f'Job: {job}' + (f" (PO {c['po_number']})" if c.get('po_number') else ''),
             (f"{client or 'The account'}'s next monthly job is completed (billed through its monthly contract) - no separate invoice from us."
              if c['vendor_pay'].get('report_only') else
              f"The client has paid our Jobber invoice{' #' + our_no if our_no else ''}."), '',
             *([f'{vendor}\'s invoice is attached.', ''] if bill else []), 'Thank you,', signer]
    body = '\n'.join(lines).rstrip()
    return {'to': _app_setting(conn, 'christian_email', os.environ.get('CHRISTIAN_EMAIL', '')),
            'subject': f"Please pay {vendor} invoice{' #' + number if number else ''}"
                       + (f' - {c["client_name"]}' if c.get('client_name') else ''),
            'body': body, 'bill_doc_id': bill['id'] if bill else None,
            'bill_file': bill['file_name'] if bill else ''}


def vendor_email(conn, case_id, signer=''):
    """An email to the vendor that asks for what the job is waiting on: the
    visit, the quote, a date, or the invoice."""
    row = conn.execute('SELECT * FROM pump_cases WHERE id=?', (case_id,)).fetchone()
    if not row:
        return None
    c = _case_dict(row)
    vendor = c.get('vendor') or 'Wettech'
    name, email = _vendor_contact(vendor)
    stage = c.get('stage') or _stage(c.get('steps') or {}, c.get('status'))
    has_bill = c.get('vendor_bill_amount') is not None or c.get('vendor_bill_total') is not None
    where = c.get('client_name') or c.get('title') or ''
    asks = {
        'assessment': ('Please assess', 'Please go out and assess the following and send us your quote for the work:'),
        'vendor_quote': (('Quote for your invoice' if has_bill else 'Please quote'),
                         ('We have your invoice for the job below. Please send us the quote that goes with it:'
                          if has_bill else 'Please send us your quote for the following:')),
        'scheduled': ('Please schedule', 'The client has approved this work. Please schedule it and let us know the date:'),
        'work_done': ('Work status', 'Please let us know when this work will be (or was) done:'),
        'vendor_bill': ('Please invoice', 'Please send us your invoice for the following work:'),
    }
    subj, ask = asks.get(stage, ('Re', 'About the following job:'))
    job = ((c.get('jobber') or {}).get('job') or {}).get('number')
    lines = [f'Hi {name},', '', ask, '',
             f"Customer: {c.get('client_name') or ''}",
             *([f"Location: {c['site']}"] if c.get('site') else []),
             *([f"PO: {c['po_number']}"] if c.get('po_number') else []),
             *([f"Your quote: #{c['vendor_quote_number']}"] if c.get('vendor_quote_number') else []),
             *([f"Your invoice: #{c['vendor_bill_number']}"] if c.get('vendor_bill_number') else []),
             *([f"Visit: {(c.get('steps') or {}).get('assessment', {}).get('due')}"]
               if stage == 'assessment' and (c.get('steps') or {}).get('assessment', {}).get('due') else []),
             f"Work: {c.get('description') or c.get('title') or ''}", '',
             'Thank you,', signer or 'Stahlman-England Irrigation']
    return {'to': email, 'vendor': vendor, 'stage': stage,
            'subject': f"{subj}: {where}" + (f" - PO {c['po_number']}" if c.get('po_number') else '')
                       + (f' (our job #{job})' if job else ''),
            'body': '\n'.join(lines)}


@api('/cases/<int:case_id>/jobber_quote', methods=('POST',))
def h_link_jobber_quote(actor, case_id):
    if not jobber_status()['connected']:
        raise ValueError('Connect Jobber first')
    return {'quote': link_jobber_quote(case_id, _json().get('number'), actor)}


def search_jobber_jobs(q, limit=25):
    """Recent Jobber jobs for a job number or a client name (Oct 2026: a service call is found by
    either, then picked from the list), newest first: [{number, title, client_name, status, date,
    uri, case_id}]. Jobber's own search, plus the jobs the sync already has."""
    q = (q or '').strip().lstrip('#')
    if len(q) < 2:
        return []
    found = {}
    conn = _conn()
    try:
        like = f'%{q}%'
        for r in conn.execute("SELECT * FROM pump_jobber_items WHERE kind='job' AND (number=? OR client_name LIKE ? "
                              "OR title LIKE ? OR property_label LIKE ?) ORDER BY COALESCE(start_at, created_at) DESC "
                              "LIMIT ?", (q, like, like, like, limit)):
            found[r['jobber_id']] = {'number': r['number'], 'title': r['title'] or '', 'client_name': r['client_name'] or '',
                                     'status': r['status'] or '', 'date': (r['start_at'] or r['created_at'] or '')[:10],
                                     'uri': r['web_uri'] or '', 'case_id': r['case_id']}
    finally:
        conn.close()
    if jobber_status()['connected']:
        def make(fields):
            return f'query($q: String!) {{ jobs(searchTerm: $q, first: {limit}) {{ nodes {{ {fields} }} }} }}'
        spec = ['id', 'jobNumber', 'title', 'jobStatus', 'createdAt', 'startAt', 'jobberWebUri', ('client', ['id', 'name'])]
        try:
            data, _ = _gql_tolerant(make, spec, {'q': q}, required=('id', 'jobNumber'))
            for n in (data.get('jobs') or {}).get('nodes') or []:
                found.setdefault(n['id'], {'number': str(n.get('jobNumber') or ''), 'title': n.get('title') or '',
                                           'client_name': (n.get('client') or {}).get('name') or '',
                                           'status': (n.get('jobStatus') or '').lower(),
                                           'date': (n.get('startAt') or n.get('createdAt') or '')[:10],
                                           'uri': n.get('jobberWebUri') or '', 'case_id': None})
        except JobberError:
            pass
    exact = [j for j in found.values() if j['number'] == q]
    rest = sorted((j for j in found.values() if j['number'] != q), key=lambda j: j['date'] or '', reverse=True)
    return (exact + rest)[:limit]


@api('/jobber/jobs')
def h_jobber_jobs(actor):
    """?q= a job number or client name - recent Jobber jobs to pick from."""
    return {'jobs': search_jobber_jobs(request.args.get('q') or '')}


@api('/service_call', methods=('POST',))
def h_service_call(actor):
    """Body: {"number": Jobber job #} - follow a service call booked in Jobber: an item
    that starts at the work (no quote), linked to the job."""
    if actor == BOT:
        return _office_only(actor, 'Adding a service call')
    it = find_job_by_number(_json().get('number'))
    if not it:
        raise ValueError("Jobber has no job with that number")
    conn = _conn()
    try:
        if it.get('case_id') and conn.execute("SELECT 1 FROM pump_cases WHERE id=? AND status != 'cancelled'",
                                              (it['case_id'],)).fetchone():
            return {'case_id': it['case_id'], 'already': True}
        cid = track_jobber_item(conn, it, actor, service_call=True)
        conn.commit()
        return {'case_id': cid}
    finally:
        conn.close()


@api('/cases/<int:case_id>/jobber_job', methods=('POST',))
def h_link_jobber_job(actor, case_id):
    """Body: {"number", "service_call": bool} - tie a Jobber job to this item; a service call
    is the start of the work (no quote)."""
    if actor == BOT:
        return _office_only(actor, 'Linking a Jobber job')
    d = _json()
    it = find_job_by_number(d.get('number'))
    if not it:
        raise ValueError("Jobber has no job with that number")
    conn = _conn()
    try:
        if not conn.execute('SELECT 1 FROM pump_cases WHERE id=?', (case_id,)).fetchone():
            return {'success': False, 'error': 'Not found'}, 404
        _link_item(conn, it['jobber_id'], case_id, actor)
        if d.get('service_call'):
            service_call_steps(conn, case_id, it, actor)
        conn.commit()
        return {'job': {'number': it['number'], 'title': it['title'], 'uri': it.get('web_uri') or ''}}
    finally:
        conn.close()


@api('/cases/<int:case_id>/jobber_invoice', methods=('POST',))
def h_link_jobber_invoice(actor, case_id):
    if actor == BOT:
        return _office_only(actor, 'Linking a Jobber invoice')
    inv = link_jobber_invoice(case_id, _json().get('number'), actor)
    diver_invoice_linked(case_id, inv, actor)
    return {'invoice': inv}


def diver_invoice_linked(case_id, inv, actor):
    """Linked by hand to a Gulfshore item (Anna's Place, Oct 2026 - the app didn't find it): the "not billed
    out" to-do done, closed when the invoice has gone out, and Jordan's label remembered for that client."""
    conn = _conn()
    try:
        case = conn.execute("SELECT * FROM pump_cases WHERE id=? AND category='diver' AND vendor='Gulfshore'",
                            (case_id,)).fetchone()
        if not case:
            return
        doc = conn.execute("SELECT * FROM pump_docs WHERE case_id=? AND kind='bill' AND status != 'dismissed' "
                           'ORDER BY id DESC', (case_id,)).fetchone()
        if doc:
            conn.execute('UPDATE pump_todos SET done_at=?, done_by=? WHERE key=? AND done_at IS NULL',
                         (_now_text(), actor, f"gulfshore-unbilled:{doc['id']}"))
        if (inv.get('status') or 'draft') not in ('draft', 'voided', 'bad_debt'):
            _set_step(conn, case_id, 'closed', at=_today().isoformat(), by=actor)
        # The invoice's own client - not one the item was wrongly tied to before (Water Crest for Falling Waters II).
        got = conn.execute("SELECT client_id, client_name FROM pump_jobber_items WHERE jobber_id=?", (inv.get('id'),)).fetchone()
        client_id = (got['client_id'] if got else '') or (json.loads(case['jobber'] or '{}').get('client') or {}).get('id')
        if got and got['client_id']:
            j = json.loads(case['jobber'] or '{}')
            j['client'] = {'id': got['client_id'], 'name': got['client_name'] or ''}
            conn.execute('UPDATE pump_cases SET jobber=?, jobber_client_id=? WHERE id=?',
                         (json.dumps(j), got['client_id'], case_id))
        conn.commit()
    finally:
        conn.close()
    if doc and client_id and doc['client_name']:
        try:
            remember_choice(_doc_dict(doc), client_id, actor=actor)
        except (JobberError, ValueError):
            pass


@api('/cases/<int:case_id>/vendor_email')
def h_vendor_email(actor, case_id):
    conn = _conn()
    try:
        e = vendor_email(conn, case_id, actor if actor != BOT else '')
        return ({'success': False, 'error': 'Not found'}, 404) if not e else {'email': e}
    finally:
        conn.close()


@api('/cases/<int:case_id>/vendor_email/send', methods=('POST',))
def h_vendor_email_send(actor, case_id):
    """Send it from the PO mailbox when someone clicks Send - so the vendor's
    reply lands in the mailbox the app reads."""
    import html as _html
    if actor == BOT:
        return {'success': False, 'error': 'Only the office can send this'}, 403
    data = _json()
    to, subject, body = (str(data.get(k) or '').strip() for k in ('to', 'subject', 'body'))
    if not (to and subject and body):
        return {'success': False, 'error': 'To, subject and message are all needed'}, 400
    try:
        graph_send(to, subject[:255], '<div style="font-family:Arial,sans-serif;font-size:14px">'
                   + '<br>'.join(_html.escape(x) for x in body[:20000].split('\n')) + '</div>')
    except Exception as e:
        return {'success': False, 'error': f'Not sent - {e}'}, 502
    conn = _conn()
    try:
        _event(conn, actor, f'emailed the vendor', f'To {to}: {subject}', case_id=case_id)
        row = conn.execute('SELECT * FROM pump_cases WHERE id=?', (case_id,)).fetchone()
        if row and (vendor_chase(_case_dict(row)) or {}).get('state'):
            # The email is the follow-up: check back in VENDOR_FOLLOW_DAYS if they don't answer.
            f = json.loads(row['vendor_follow'] or '{}')
            if f.get('phase') != CHASE_PHASES.get(row['stage']):
                f = {'phase': CHASE_PHASES.get(row['stage'])}
            f.update(at=_now_text(), by=actor, how='email', said='',
                     check_on=_workdays_after(_today(), VENDOR_FOLLOW_DAYS).isoformat())
            if f.get('expect_by') and f['expect_by'] >= _today().isoformat():
                f['check_on'] = ''   # a date they gave still stands
            conn.execute('UPDATE pump_cases SET vendor_follow=? WHERE id=?', (json.dumps(f), case_id))
        conn.commit()
    finally:
        conn.close()
    return {'sent': {'to': to, 'subject': subject}}


def send_vendor_pay_email(case_id, actor, body=None):
    """Send the pay-the-vendor email to Christian when someone in the office
    clicks Send, from the PO mailbox, with the vendor's bill attached."""
    import html as _html
    conn = _conn()
    try:
        e = vendor_pay_email(conn, case_id, actor)
        bill = conn.execute('SELECT file_name, file_path FROM pump_docs WHERE id=?',
                            (e['bill_doc_id'],)).fetchone() if e and e['bill_doc_id'] else None
    finally:
        conn.close()
    if not e:
        raise ValueError('No such item')
    if not e['to']:
        raise ValueError("No email address is saved for Christian - add it in the main app's Settings")
    html = ('<div style="font-family:Arial,sans-serif;font-size:14px">'
            + '<br>'.join(_html.escape(line) for line in ((body or '').strip() or e['body']).split('\n')) + '</div>')
    atts = []
    if bill and bill['file_path'] and os.path.exists(bill['file_path']):
        with open(bill['file_path'], 'rb') as f:
            atts.append({'@odata.type': '#microsoft.graph.fileAttachment', 'name': bill['file_name'] or 'invoice.pdf',
                         'contentType': 'application/pdf' if (bill['file_name'] or '').lower().endswith('.pdf')
                         else 'application/octet-stream', 'contentBytes': base64.b64encode(f.read()).decode()})
    error = ''
    try:
        graph_send(e['to'], e['subject'], html, atts or None)
    except Exception as ex:
        error = str(ex)
    rec = {'at': _now_text(), 'to': e['to'], 'by': actor, **({'error': error} if error else {'sent': True})}
    _state_set(f'pay_email:{case_id}', rec)
    conn = _conn()
    try:
        _event(conn, actor, 'could not email Christian' if error else 'emailed Christian to pay the vendor',
               error or f"To {e['to']}: {e['subject']}", case_id=case_id)
        if not error:
            update_case(conn, case_id, {'vendor_paid_on': _today().isoformat()}, actor)
        conn.commit()
    finally:
        conn.close()
    return rec


# ── bills to pay ─────────────────────────────────────────────────────────────

BIG_BILL = 1500.0   # a vendor bill over this waits for the client to pay our invoice


def bills_to_pay(conn):
    """Every vendor bill not paid yet, by vendor (Oct 2026). A bill can be paid
    once we've invoiced the client for it (our Jobber invoice exists - nearly
    always), or a report-only account's month is over. The rest wait."""
    groups = {}
    for c in list_cases(conn, 'all'):
        if c['status'] == 'cancelled' or c['vendor_paid_on']:
            continue
        pay = c['vendor_pay']
        if not pay['state']:
            continue   # no bill
        inv = (c.get('jobber') or {}).get('invoice') or {}
        invoiced = bool(inv.get('id') or (c.get('sei_invoice_number') or '').strip() or
                        ((c.get('steps') or {}).get('invoice_drafted') or {}).get('at'))
        bill = conn.execute("SELECT id, doc_number, doc_date, total, subtotal, file_name FROM pump_docs WHERE case_id=? "
                            "AND kind='bill' AND status != 'dismissed' ORDER BY id DESC", (c['id'],)).fetchone()
        number = c.get('vendor_bill_number') or (bill['doc_number'] if bill else '') or ''
        amount = next((v for v in (c.get('vendor_bill_total'), c.get('vendor_bill_amount'),
                                   bill['total'] if bill else None) if v is not None), None)
        if pay.get('report_only'):
            payable = pay['state'] == 'due'
            mv = pay.get('monthly_visit') or {}
            why = (f"report-only account - the monthly job's visit of {mv['date']} is done" if payable and mv.get('completed_on')
                   else 'report-only account - payable once the next monthly job is completed'
                   + (f" (visit {mv['date']})" if mv.get('date') else '')
                   + (f" - {mv['note']}" if mv.get('note') else ''))
        else:
            payable = invoiced or pay['state'] == 'due'
            num = inv.get('number') or c.get('sei_invoice_number') or ''
            why = (f"invoiced{' #' + num if num else ''}{' (' + inv['status'].replace('_', ' ') + ')' if inv.get('status') else ''}"
                   if invoiced else 'not invoiced yet')
            if amount is not None and amount > BIG_BILL and pay['client_invoice_status'] != 'paid':
                # Over $1,500 (the office, Oct 2026): paid only once the client has paid our invoice.
                payable = False
                why = (f"over {money_text(BIG_BILL)} - paid once the client pays our invoice"
                       f"{' #' + num if num else ''}{' (' + inv['status'].replace('_', ' ') + ')' if inv.get('status') else ''}"
                       if invoiced else f"over {money_text(BIG_BILL)} - not invoiced yet")
        ok = _state_get(f"pay_ok:{c['id']}", conn=conn) or {}
        if ok and not payable:
            # OK'd by hand (Wild Blue, Oct 2026: billed through the monthly irrigation contract - no invoice to link).
            payable = True
            why = f"OK'd to pay now by {ok.get('by') or 'the office'} ({(ok.get('at') or '')[:10]}) - {why}"
        hold = _state_get(f"pay_hold:{c['id']}", conn=conn) or {}
        if hold:
            # Held by hand (Homewood Suites, Oct 2026: invoiced, but not OK to pay the vendor yet).
            payable = False
            why = (f"held - not OK to pay, by {hold.get('by') or 'the office'} ({(hold.get('at') or '')[:10]})"
                   f"{': ' + hold['note'] if hold.get('note') else ''} - {why}")
        asked = _state_get(f'pay_email:{c["id"]}', conn=conn) or {}
        vendor = c.get('vendor') or 'Wettech'
        groups.setdefault(vendor, []).append({
            'case_id': c['id'], 'title': c.get('title') or '', 'client_name': c.get('client_name') or '',
            'bill_number': number, 'bill_date': (bill['doc_date'] if bill else '') or '', 'amount': amount,
            'bill_doc_id': bill['id'] if bill else None, 'payable': payable, 'why': why, 'pay_ok': bool(ok), 'held': bool(hold),
            'invoice_number': inv.get('number') or c.get('sei_invoice_number') or '',
            'asked_at': asked.get('at', '') if asked.get('sent') else ''})
    out = []
    for vendor in sorted(groups, key=lambda v: (v != 'Wettech', v.lower())):
        bills = sorted(groups[vendor], key=lambda b: (not b['payable'], b['bill_date'] or '', b['case_id']))
        out.append({'vendor': vendor, 'bills': bills,
                    'payable_total': round(sum(b['amount'] or 0 for b in bills if b['payable']), 2),
                    'waiting_total': round(sum(b['amount'] or 0 for b in bills if not b['payable']), 2)})
    return out


def bills_paid_recently(conn, days=60, q=''):
    """Vendor bills marked paid in the last `days` days, newest first - so one
    marked paid by mistake can be put back on the list. q: search every paid
    bill, any date, by site, job, vendor or invoice number."""
    q = (q or '').strip().lower().lstrip('#')
    since = '' if q else (_today() - timedelta(days=days)).isoformat()
    out = []
    for c in list_cases(conn, 'all'):
        paid = c.get('vendor_paid_on') or ''
        if not paid or paid < since or not c['vendor_pay']['state']:
            continue
        bill = conn.execute("SELECT id, doc_number, total FROM pump_docs WHERE case_id=? AND kind='bill' "
                            "AND status != 'dismissed' ORDER BY id DESC", (c['id'],)).fetchone()
        amount = next((v for v in (c.get('vendor_bill_total'), c.get('vendor_bill_amount'),
                                   bill['total'] if bill else None) if v is not None), None)
        row = {'case_id': c['id'], 'vendor': c.get('vendor') or 'Wettech',
               'client_name': c.get('client_name') or '', 'title': c.get('title') or '',
               'bill_number': c.get('vendor_bill_number') or (bill['doc_number'] if bill else '') or '',
               'bill_doc_id': bill['id'] if bill else None, 'amount': amount,
               'paid_on': paid, 'paid_by': c.get('vendor_paid_by') or '',
               'emailed_at': ((_state_get(f"pay_email:{c['id']}", conn=conn) or {}).get('at') or '')[:10]}
        if q and q not in ' '.join(str(row[k]) for k in ('vendor', 'client_name', 'title', 'bill_number')).lower() + \
                f" {c.get('sei_invoice_number') or ''} {c.get('site') or ''}".lower():
            continue
        out.append(row)
    return sorted(out, key=lambda b: (b['paid_on'], b['case_id']), reverse=True)


@api('/bills_to_pay')
def h_bills_to_pay(actor):
    conn = _conn()
    try:
        return {'vendors': bills_to_pay(conn), 'paid': bills_paid_recently(conn),
                'christian': _app_setting(conn, 'christian_email', os.environ.get('CHRISTIAN_EMAIL', ''))}
    finally:
        conn.close()


def bills_to_pay_email(conn, case_ids, signer=''):
    """One email to Christian: the bills he can pay, by vendor, with each bill attached."""
    picked = set(case_ids or [])
    lines, atts_ids, total, n = ['Hi Christian,', '', 'These vendor bills can be paid - we have invoiced the clients:', ''], [], 0.0, 0
    for g in bills_to_pay(conn):
        bills = [b for b in g['bills'] if b['payable'] and (not picked or b['case_id'] in picked)]
        if not bills:
            continue
        sub = round(sum(b['amount'] or 0 for b in bills), 2)
        lines.append(f"{g['vendor']} - {len(bills)} bill{'s' if len(bills) > 1 else ''}, ${sub:,.2f}")
        for b in bills:
            lines.append(f"  • Invoice #{b['bill_number'] or '?'}"
                         f"{' (' + b['bill_date'] + ')' if b['bill_date'] else ''} - "
                         f"{'$%s' % format(b['amount'], ',.2f') if b['amount'] is not None else 'amount ?'} - "
                         f"{b['client_name'] or b['title']}"
                         f"{' - our invoice #' + b['invoice_number'] if b['invoice_number'] else ''}")
            if b['bill_doc_id']:
                atts_ids.append(b['bill_doc_id'])
        lines.append('')
        total += sub
        n += len(bills)
    if not n:
        raise ValueError('No bills to pay are picked')
    lines += [f'Total: ${total:,.2f} ({n} bill{"s" if n > 1 else ""}). The bills are attached.', '', 'Thank you,',
              signer or 'Stahlman-England Irrigation']
    return {'to': _app_setting(conn, 'christian_email', os.environ.get('CHRISTIAN_EMAIL', '')),
            'subject': f'Vendor bills to pay - {n} bill{"s" if n > 1 else ""}, ${total:,.2f}',
            'body': '\n'.join(lines), 'doc_ids': atts_ids, 'count': n, 'total': round(total, 2)}


@api('/bills_to_pay/paid', methods=('POST',))
def h_bills_paid(actor):
    """Body: {"case_ids": [...], "paid_on": "YYYY-MM-DD"} - the vendor's bills on these jobs are paid."""
    if actor == BOT:
        return _office_only(actor, 'Marking vendor bills paid')
    data = _json()
    when = _iso_date(data.get('paid_on') or '') or _today().isoformat()
    ids = [int(x) for x in (data.get('case_ids') or []) if str(x).isdigit()]
    if not ids:
        raise ValueError('Tick the bills that are paid')
    conn = _conn()
    try:
        done = [cid for cid in ids if update_case(conn, cid, {'vendor_paid_on': when}, actor)]
        conn.commit()
    finally:
        conn.close()
    return {'marked': len(done), 'case_ids': done}


@api('/docs/<int:doc_id>/site_invoices', methods=('POST',))
@jobber_button
def h_doc_site_invoices(actor, doc_id):
    """Draft the invoice for each station of the bill that doesn't have one yet."""
    if actor == BOT:
        return _office_only(actor, 'Drafting invoices')
    res = draft_site_invoices(doc_id, actor)
    if not res:
        raise ValueError("This bill's report is for one pump station")
    return res


@api('/bills_to_pay/pay_ok', methods=('POST',))
def h_bills_pay_ok(actor):
    """Body: {"case_ids": [...], "undo": false} - these bills can be paid now, though nothing
    says so yet (billed through a monthly contract, so no invoice to link)."""
    if actor == BOT:
        return _office_only(actor, 'OKing vendor bills to pay')
    data = _json()
    ids = [int(x) for x in (data.get('case_ids') or []) if str(x).isdigit()]
    if not ids:
        raise ValueError('Pick the bills')
    conn = _conn()
    try:
        for cid in ids:
            if data.get('undo'):
                conn.execute('DELETE FROM pump_state WHERE key=?', (f'pay_ok:{cid}',))
            else:
                _state_set(f'pay_ok:{cid}', {'at': _now_text(), 'by': actor}, conn=conn)
            _event(conn, actor, 'vendor bill not OKd to pay' if data.get('undo') else 'vendor bill OKd to pay',
                   'put back to wait' if data.get('undo') else 'OK to pay now - no invoice to wait on', case_id=cid)
        conn.commit()
    finally:
        conn.close()
    return {'case_ids': ids}


@api('/bills_to_pay/hold', methods=('POST',))
def h_bills_hold(actor):
    """Body: {"case_ids": [...], "note": "", "undo": false} - these bills aren't OK to pay, whatever
    else says they are (a problem with the work, a dispute). Undo lets them be paid again."""
    if actor == BOT:
        return _office_only(actor, 'Holding vendor bills')
    data = _json()
    ids = [int(x) for x in (data.get('case_ids') or []) if str(x).isdigit()]
    if not ids:
        raise ValueError('Pick the bills')
    note = (data.get('note') or '').strip()
    conn = _conn()
    try:
        for cid in ids:
            if data.get('undo'):
                conn.execute('DELETE FROM pump_state WHERE key=?', (f'pay_hold:{cid}',))
            else:
                conn.execute('DELETE FROM pump_state WHERE key=?', (f'pay_ok:{cid}',))
                _state_set(f'pay_hold:{cid}', {'at': _now_text(), 'by': actor, 'note': note}, conn=conn)
            _event(conn, actor, 'vendor bill hold lifted' if data.get('undo') else 'vendor bill held - not OK to pay',
                   'can be paid again' if data.get('undo') else (note or 'not OK to pay'), case_id=cid)
        conn.commit()
    finally:
        conn.close()
    return {'case_ids': ids}


@api('/bills_to_pay/paid_list')
def h_bills_paid_list(actor):
    """?q= - paid bills to undo: the last 60 days, or every one matching q."""
    conn = _conn()
    try:
        return {'paid': bills_paid_recently(conn, q=request.args.get('q') or '')}
    finally:
        conn.close()


@api('/bills_to_pay/unpaid', methods=('POST',))
def h_bills_unpaid(actor):
    """Body: {"case_ids": [...]} - undo: these bills were marked paid by mistake, back on the list."""
    if actor == BOT:
        return _office_only(actor, 'Undoing vendor bills marked paid')
    ids = [int(x) for x in (_json().get('case_ids') or []) if str(x).isdigit()]
    if not ids:
        raise ValueError('Pick the bills to put back')
    conn = _conn()
    try:
        n = sum(1 for cid in ids if update_case(conn, cid, {'vendor_paid_on': ''}, actor))
        conn.commit()
    finally:
        conn.close()
    return {'unmarked': n}


@api('/bills_to_pay/email', methods=('POST',))
def h_bills_to_pay_email(actor):
    """Body: {"case_ids": [...], "send": true}. Without send, the email to look over."""
    import html as _html
    if actor == BOT:
        return _office_only(actor, 'Emailing Christian to pay vendor bills')
    data = _json()
    ids = [int(x) for x in (data.get('case_ids') or []) if str(x).isdigit()]
    conn = _conn()
    try:
        e = bills_to_pay_email(conn, ids, actor)
        files = [dict(r) for r in conn.execute(
            f"SELECT file_name, file_path FROM pump_docs WHERE id IN ({','.join('?' * len(e['doc_ids'])) or 'NULL'})",
            e['doc_ids'])]
        cases = [b['case_id'] for g in bills_to_pay(conn) for b in g['bills'] if b['payable'] and (not ids or b['case_id'] in ids)]
    finally:
        conn.close()
    if not data.get('send'):
        return {'email': {k: e[k] for k in ('to', 'subject', 'body', 'count', 'total')}}
    if not e['to']:
        raise ValueError("No email address is saved for Christian - add it in the main app's Settings")
    body = (data.get('body') or '').strip() or e['body']
    html = '<div style="font-family:Arial,sans-serif;font-size:14px">' + '<br>'.join(
        _html.escape(l).replace('  ', '&nbsp;&nbsp;') for l in body.split('\n')) + '</div>'
    atts = []
    for f in files:
        if f['file_path'] and os.path.exists(f['file_path']):
            with open(f['file_path'], 'rb') as fh:
                atts.append({'@odata.type': '#microsoft.graph.fileAttachment', 'name': f['file_name'] or 'invoice.pdf',
                             'contentType': 'application/pdf' if (f['file_name'] or '').lower().endswith('.pdf')
                             else 'application/octet-stream', 'contentBytes': base64.b64encode(fh.read()).decode()})
    graph_send(e['to'], e['subject'], html, atts or None)
    rec = {'at': _now_text(), 'to': e['to'], 'by': actor, 'sent': True, 'batch': True}
    conn = _conn()
    try:
        for cid in cases:
            _state_set(f'pay_email:{cid}', rec, conn=conn)
            _event(conn, actor, 'emailed Christian to pay the vendor', f"In the bills-to-pay email to {e['to']}",
                   case_id=cid)
            # Sent to Christian = paid as far as the office goes (Oct 2026): off the list, into Old vendor bills.
            update_case(conn, cid, {'vendor_paid_on': _today().isoformat()}, actor)
        conn.commit()
    finally:
        conn.close()
    return {'sent': e['count'], 'total': e['total'], 'to': e['to'], 'case_ids': cases}


@api('/cases/<int:case_id>/pay_email/send', methods=('POST',))
def h_pay_email_send(actor, case_id):
    if actor == BOT:
        return {'success': False, 'error': 'Only the office can send this'}, 403
    rec = send_vendor_pay_email(case_id, actor, str(_json().get('body') or '')[:20000])
    if rec.get('error'):
        return {'success': False, 'error': 'Not sent - ' + rec['error']}, 502
    return {'sent': rec}


@api('/cases/<int:case_id>/pay_email')
def h_pay_email(actor, case_id):
    conn = _conn()
    try:
        e = vendor_pay_email(conn, case_id, actor if actor != BOT else '')
        return ({'success': False, 'error': 'Not found'}, 404) if not e else {'email': e}
    finally:
        conn.close()


@api('/months')
def h_months(actor):
    conn = _conn()
    try:
        months = {_month_tab(r[0]) for r in conn.execute("SELECT DISTINCT substr(opened_on,1,7)||'-01' FROM pump_cases")}
        months.add(_now().strftime('%B %Y'))
        return {'months': sorted(months, key=lambda m: datetime.strptime(m, '%B %Y')),
                'current': _now().strftime('%B %Y')}
    finally:
        conn.close()


@api('/docs')
def h_docs(actor):
    conn = _conn()
    try:
        sql, args = 'SELECT * FROM pump_docs WHERE 1=1', []
        if request.args.get('kind'):
            sql += ' AND kind=?'
            args.append(request.args['kind'])
        if request.args.get('status'):
            sql += ' AND status=?'
            args.append(request.args['status'])
        if request.args.get('case_id'):
            sql += ' AND case_id=?'
            args.append(int(request.args['case_id']))
        sql += ' ORDER BY id DESC LIMIT ?'
        args.append(min(int(request.args.get('limit', 200)), 500))
        return {'docs': [_doc_dict(r) for r in conn.execute(sql, args)]}
    finally:
        conn.close()


@api('/docs/<int:doc_id>/refile', methods=('POST',))
def h_doc_refile(actor, doc_id):
    """Wrong item: take the document off it and file it again (on the item it
    fits, or a new one). A bill or report then carries on as when it came in."""
    if actor == BOT:
        return _office_only(actor, 'Moving a document to another item')
    conn = _conn()
    try:
        target = _json().get('case_id')
        case_id = refile_document(conn, doc_id, actor, int(target) if str(target or '').isdigit() else None)
        if case_id is None:
            return {'success': False, 'error': 'Not found'}, 404
        conn.commit()
        kind = conn.execute('SELECT kind FROM pump_docs WHERE id=?', (doc_id,)).fetchone()['kind']
    finally:
        conn.close()
    out = {'case_id': case_id}
    if kind == 'report':
        out['auto_note'] = auto_log_report(doc_id)
    elif kind == 'bill':
        out['auto_invoice'] = auto_draft_invoice(doc_id)
    return out


@api('/docs/<int:doc_id>/invoice_suggestion')
def h_doc_invoice_suggestion(actor, doc_id):
    """The invoice for a bill once the office has picked the Jobber client: a
    maintenance visit takes that client's recurring job price."""
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
        if not row:
            return {'success': False, 'error': 'Not found'}, 404
        d = _doc_dict(row)
        case = dict(conn.execute('SELECT * FROM pump_cases WHERE id=?', (d['case_id'],)).fetchone()) if d['case_id'] else None
    finally:
        conn.close()
    return {'suggestion': invoice_suggestion(d, case, request.args.get('client_id') or None,
                                             request.args.get('job_id') or None)}


@api('/jobber/recurring_jobs')
def h_recurring_jobs(actor):
    """?client_id= - the client's live recurring jobs with their price, to pick the one an invoice goes on."""
    out = []
    for x in recurring_jobs(request.args.get('client_id') or ''):
        if x.get('status') == 'archived':
            continue
        d = job_detail(x['id'])
        price = sum(float(li.get('unit_price') or 0) * float(li.get('quantity') or 1) for li in d['line_items'])
        out.append({'id': x['id'], 'number': str(x.get('number') or ''), 'title': x.get('title') or '',
                    'property_label': x.get('property_label') or '', 'price': round(price, 2), 'uri': d.get('uri') or ''})
    return {'jobs': out}


@api('/docs/<int:doc_id>')
def h_doc(actor, doc_id):
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
        if not row:
            return {'success': False, 'error': 'Not found'}, 404
        d = _doc_dict(row)
        case = dict(conn.execute('SELECT * FROM pump_cases WHERE id=?', (d['case_id'],)).fetchone()) if d['case_id'] else None
        if d['kind'] == 'bill':
            d['invoice_suggestion'] = invoice_suggestion(d, case)
            d['site_invoices_left'] = site_invoices_left(d, case) if jobber_status()['connected'] else []
            acct = account_info(conn, case) if case else None
            d['account_note'], d['account_name'] = (acct or {}).get('notes') or '', (acct or {}).get('name') or ''
        if d['kind'] == 'quote':
            d['quote_suggestion'] = suggest_quote(d, case)
        if d['kind'] == 'report':
            done = (d.get('jobber') or {}).get('sections') or {}
            d['sections'] = [{'section': i, 'location': x['location'], 'date': x['date'],
                              'logged': bool(done.get(str(i)))} for i, x in enumerate(report_sections(d))]
        if case:
            d['case_issues'] = [dict(r) for r in conn.execute(
                'SELECT id, kind, message FROM pump_issues WHERE case_id=? AND resolved_at IS NULL', (case['id'],))]
        return {'doc': d}
    finally:
        conn.close()


@api('/docs/<int:doc_id>/file')
def h_doc_file(actor, doc_id):
    version = request.args.get('version', 'original')
    return _send_doc_file(doc_id, version)


def _send_doc_file(doc_id, version):
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return {'success': False, 'error': 'Not found'}, 404
    m = re.fullmatch(r'section(\d{1,2})', version or '')
    if m:
        # One pump station's page of a two-station report.
        secs = report_sections(_doc_dict(row))
        i = int(m.group(1))
        pdf = _section_pdf(row['branded_path'], secs[i]['location']) if i < len(secs) else None
        if not pdf:
            return {'success': False, 'error': 'No such page'}, 404
        return send_file(io.BytesIO(pdf), mimetype='application/pdf', as_attachment=request.args.get('download') == '1',
                         download_name=_vendor_file_name(row['file_name'], f" - {secs[i]['location']}.pdf"))
    if version == 'branded_pdf':
        path = _branded_pdf_path(row['branded_path'])
        if row['branded_path'] and not os.path.exists(path):
            path = _make_branded_pdf(row['branded_path'])
        if not path or not os.path.exists(path):
            return {'success': False, 'error': 'No PDF of this report on this server - download the Word file.'}, 404
        return send_file(path, mimetype='application/pdf', as_attachment=request.args.get('download') == '1',
                         download_name=_vendor_file_name(row['file_name'], '.pdf'))
    if version == 'approved':
        dj = json.loads(row['jobber'] or '{}')
        path = dj.get('approved_path')
        if not path or not os.path.exists(path):
            return {'success': False, 'error': 'This quote is not signed yet'}, 404
        name = dj.get('approved_name') or _approved_name(row['file_name'])
        return send_file(path, mimetype='application/pdf' if name.lower().endswith('.pdf') else
                         'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                         as_attachment=request.args.get('download') == '1', download_name=name)
    path = row['branded_path'] if version == 'branded' else row['file_path']
    if not path or not os.path.exists(path):
        return {'success': False, 'error': 'File not available'}, 404
    name = _branded_name(row['file_name']) if version == 'branded' else row['file_name']
    if version == 'pdf':
        return {'success': False, 'error': 'Use version=branded_pdf'}, 400
    return send_file(path, as_attachment=request.args.get('download') == '1', download_name=name)


@api('/docs/<int:doc_id>/pdf')
def h_doc_pdf(actor, doc_id):
    """The rebranded report as a PDF (only where LibreOffice is installed)."""
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
    finally:
        conn.close()
    if not row or not row['branded_path']:
        return {'success': False, 'error': 'No rebranded report'}, 404
    with open(row['branded_path'], 'rb') as f:
        pdf = pump_reports.docx_to_pdf(f.read())
    if not pdf:
        return {'success': False, 'error': 'PDF conversion is not available on this server - download the Word file.'}, 501
    return send_file(io.BytesIO(pdf), mimetype='application/pdf', as_attachment=request.args.get('download') == '1',
                     download_name=os.path.splitext(_branded_name(row['file_name']))[0] + '.pdf')


@api('/jobber/items')
def h_jobber_items(actor):
    conn = _conn()
    try:
        sql, args = 'SELECT * FROM pump_jobber_items WHERE 1=1', []
        if request.args.get('category'):
            sql += ' AND category=?'
            args.append(request.args['category'])
        if request.args.get('kind'):
            kinds = [k for k in request.args['kind'].split(',') if k]
            sql += f" AND kind IN ({','.join('?' * len(kinds))})"
            args += kinds
        rows = [dict(r) for r in conn.execute(sql + ' ORDER BY updated_at DESC', args)]
        if request.args.get('open', '1') == '1':
            rows = [r for r in rows if r['status'] in OPEN_STATUSES.get(r['kind'], set())
                    and not (r['kind'] == 'job' and r['job_type'] == 'recurring')]
        if request.args.get('show_ignored') != '1':
            rows = [r for r in rows if not r['ignored']]
        rows = rows[:1000]
        names = _account_names(conn)
        for r in rows:
            if not r['case_id']:
                r['on_sheet'] = on_account_sheets(conn, r, names)
        return {'items': rows, 'sync': {**jobber_sync_state(), 'every_min': JOBBER_SYNC_EVERY_MIN},
                'jobber': jobber_status()}
    finally:
        conn.close()


@api('/jobber/contracts')
def h_jobber_contracts(actor):
    """Recurring pump maintenance jobs (the service contracts)."""
    conn = _conn()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM pump_jobber_items WHERE kind='job' AND job_type='recurring' AND status != 'archived' "
            "ORDER BY client_name")]
        return {'contracts': rows}
    finally:
        conn.close()


@api('/jobber/clients')
def h_jobber_clients(actor):
    name = request.args.get('q', '').strip()
    if not name:
        raise ValueError('q is required')
    cands = search_clients(name)
    a = match_site_alias({'client_name': name})
    if a:
        # A name the office has matched before: that client, first and chosen.
        mine = next((c for c in cands if c['id'] == a['client_id']), None) or \
            {'id': a['client_id'], 'name': a['client_name'], 'is_lead': False, 'uri': '', 'address': '',
             'matching_properties': []}
        mine = {**mine, 'score': 1.0, 'remembered': f'You matched "{a["place"]}" to {a["client_name"]} before',
                'job_id': a.get('job_id') or ''}
        cands = [mine] + [c for c in cands if c['id'] != a['client_id']]
        return {'candidates': cands, 'pick': mine}
    hidden = 0
    if request.args.get('pump') and not request.args.get('all'):
        # A pump report (Rosewood, Oct 2026): only clients we do pump work for -
        # not everyone whose address or contact has the word in it.
        pumped = pump_client_ids()
        keep = [c for c in cands if c['id'] in pumped]
        if keep:
            hidden, cands = len(cands) - len(keep), keep
    return {'candidates': cands, 'pick': pick_client(cands), 'hidden': hidden}


def pump_client_ids():
    """Jobber clients we do pump work for: pump jobs, quotes or invoices synced
    from Jobber, a pump account's client, or a client on one of our items."""
    conn = _conn()
    try:
        ids = {r[0] for r in conn.execute("SELECT DISTINCT client_id FROM pump_jobber_items WHERE client_id != '' "
                                          "AND COALESCE(ignored, 0)=0")}
        ids |= {r[0] for r in conn.execute("SELECT jobber_client_id FROM pump_maint_accounts "
                                           "WHERE COALESCE(jobber_client_id, '') != ''")}
        ids |= {r[0] for r in conn.execute("SELECT jobber_client_id FROM pump_cases "
                                           "WHERE COALESCE(jobber_client_id, '') != ''")}
        ids |= {r[0] for r in conn.execute("SELECT client_id FROM pump_site_aliases WHERE COALESCE(client_id, '') != ''")}
    finally:
        conn.close()
    return ids


@api('/jobber/clients/<path:client_id>/jobs')
def h_jobber_client_jobs(actor, client_id):
    return client_jobs(client_id)


# ── writing ──────────────────────────────────────────────────────────────────

@api('/cases', methods=('POST',))
def h_case_create(actor):
    data = _json()
    if not (data.get('title') or data.get('client_name') or data.get('description')):
        raise ValueError('Give the item a title, client or description')
    conn = _conn()
    try:
        cid = create_case(conn, data, actor, source='openclaw' if actor == BOT else 'manual')
        if data.get('steps') or data.get('note'):
            update_case(conn, cid, {'steps': data.get('steps') or {}, 'note': data.get('note')}, actor)
        if data.get('jobber_item_id'):
            _link_item(conn, data['jobber_item_id'], cid, actor)
        conn.commit()
        return {'case_id': cid, 'case': case_detail(conn, cid)}
    finally:
        conn.close()


def move_case_to(conn, case_id, stage, actor):
    """Bring a job that's out of step up to (or back to) a stage by hand
    (Carlisle, Oct 2026: Wettech said the work was done while it still read
    "send the quote to Tom"): every step before it is ticked done today, unless
    done or not needed already; moving back un-ticks it and the steps after."""
    if stage not in STEP_KEYS:
        raise ValueError('Pick the step the job is at')
    row = conn.execute('SELECT steps FROM pump_cases WHERE id=?', (case_id,)).fetchone()
    if not row:
        return False
    steps = _with_optional(json.loads(row['steps'] or '{}'))   # an optional step left off stays off
    at = STEP_KEYS.index(stage)
    today = _today().isoformat()
    for k in STEP_KEYS[:at]:
        if not (steps.get(k) or {}).get('at') and not (steps.get(k) or {}).get('na'):
            _set_step(conn, case_id, k, at=today, by=f'{actor} (moved up)')
    for k in STEP_KEYS[at:]:
        if (steps.get(k) or {}).get('at'):
            _set_step(conn, case_id, k, by=actor, na=False)
    _refresh_case(conn, case_id)
    label = dict(STEPS)[stage].format(vendor='the vendor')
    _event(conn, actor, 'moved', f'Moved by hand to: {label}', case_id=case_id)
    return True


@api('/cases/<int:case_id>/follow_up_off', methods=('POST',))
def h_follow_up_off(actor, case_id):
    """No follow-up with the vendor needed at the job's current step: off the
    list until the job moves to another step. {"on": true} undoes it."""
    conn = _conn()
    try:
        row = conn.execute('SELECT stage, vendor_follow FROM pump_cases WHERE id=?', (case_id,)).fetchone()
        if not row:
            return {'success': False, 'error': 'Not found'}, 404
        f = json.loads(row['vendor_follow'] or '{}')
        if _json().get('on'):
            f.pop('off_stage', None)
        else:
            f['off_stage'] = row['stage']
        conn.execute('UPDATE pump_cases SET vendor_follow=?, updated_at=? WHERE id=?',
                     (json.dumps(f), _now_text(), case_id))
        _event(conn, actor, 'follow-up turned back on' if _json().get('on') else 'no follow-up needed',
               f"At: {row['stage']}", case_id=case_id)
        conn.commit()
        return {}
    finally:
        conn.close()


@api('/cases/<int:case_id>/urgent', methods=('POST',))
def h_case_urgent(actor, case_id):
    """{"on": true|false} - a quote that's urgent sits with the jobs at the top of the watchlist;
    the rest wait under "Quotes - not urgent" at the bottom (Oct 2026)."""
    on = bool(_json().get('on'))
    conn = _conn()
    try:
        if not conn.execute('UPDATE pump_cases SET urgent=?, updated_at=? WHERE id=?',
                            ('1' if on else '', _now_text(), case_id)).rowcount:
            return {'success': False, 'error': 'Not found'}, 404
        _event(conn, actor, 'marked urgent' if on else 'marked not urgent', '', case_id=case_id)
        conn.commit()
        return {'urgent': on}
    finally:
        conn.close()


@api('/cases/<int:case_id>/follow_up_tomorrow', methods=('POST',))
def h_follow_up_tomorrow(actor, case_id):
    """Postpone the follow-up to the next working day (Oct 2026): off the list until then, what the
    vendor said kept."""
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_cases WHERE id=?', (case_id,)).fetchone()
        if not row:
            return {'success': False, 'error': 'Not found'}, 404
        c = _case_dict(row)
        phase = CHASE_PHASES.get(c['stage'])
        f = json.loads(row['vendor_follow'] or '{}')
        if f.get('phase') != phase:
            f = {'phase': phase}
        when = _workdays_after(_today(), 1).isoformat()
        f['check_on'] = when
        conn.execute('UPDATE pump_cases SET vendor_follow=?, updated_at=? WHERE id=?', (json.dumps(f), _now_text(), case_id))
        _event(conn, actor, 'follow-up postponed', f'To {when}', case_id=case_id)
        conn.commit()
        return {'check_on': when}
    finally:
        conn.close()


@api('/cases/<int:case_id>/move', methods=('POST',))
def h_case_move(actor, case_id):
    """Body: {"stage": step key} - the next step the job is waiting on."""
    if actor == BOT:
        return _office_only(actor, 'Moving a job to another step')
    conn = _conn()
    try:
        if not move_case_to(conn, case_id, (_json().get('stage') or '').strip(), actor):
            return {'success': False, 'error': 'Not found'}, 404
        conn.commit()
        return {'case': case_detail(conn, case_id)}
    finally:
        conn.close()


@api('/cases/<int:case_id>', methods=('PATCH', 'POST'))
def h_case_update(actor, case_id):
    data = _json()
    if actor == BOT and (any(k in OFFICE_ONLY_STEPS for k in (data.get('steps') or {})) or data.get('status')
                         or 'vendor_paid_on' in data):
        return _office_only(actor, 'Checking a bill, marking the vendor paid, closing or cancelling an item')
    conn = _conn()
    try:
        if not update_case(conn, case_id, data, actor):
            return {'success': False, 'error': 'Not found'}, 404
        conn.commit()
        return {'case': case_detail(conn, case_id)}
    finally:
        conn.close()


@api('/cases/<int:case_id>/vendor_follow', methods=('POST',))
def h_vendor_follow(actor, case_id):
    """We chased the vendor: {who, how, said, expect_by, check_on}."""
    d = _json()
    conn = _conn()
    try:
        if not log_vendor_follow(conn, case_id, actor, d.get('who'), d.get('how'), d.get('said'),
                                 d.get('expect_by'), d.get('check_on')):
            return {'success': False, 'error': 'Not found'}, 404
        conn.commit()
        return {'case': case_detail(conn, case_id)}
    finally:
        conn.close()


# Status updates on an approved job, newest kept on the job and every one in its log.
JOB_STATUSES = {
    'parts_ordered': 'Parts ordered',
    'waiting_vendor': 'Waiting on the vendor',
    'client_notified': 'Client notified',
    'scheduled': 'Scheduled',
    'in_progress': 'Work under way',
    'work_done': 'Work done',
    'on_hold': 'On hold',
    'note': 'Note',
}


def set_job_status(conn, case_id, actor, kind, text='', on=''):
    """A status update: {kind} with a note and a date - when the parts are due
    (parts ordered, waiting on the vendor) or the day it's booked (scheduled).
    A date for the work moves the job's follow-up to then; Scheduled sets the
    job's date and ticks Scheduled; Work done ticks Work done."""
    row = conn.execute('SELECT * FROM pump_cases WHERE id=?', (case_id,)).fetchone()
    if not row:
        return None
    if kind not in JOB_STATUSES:
        raise ValueError('Pick what the update is')
    text = (text or '').strip()[:1000]
    on = _iso_date(on) if on else ''
    if kind == 'note' and not text:
        raise ValueError('Write the note')
    if kind == 'scheduled' and not on:
        raise ValueError('Say what day it is scheduled for')
    c = _case_dict(row)
    today = _today().isoformat()
    rec = {'kind': kind, 'label': JOB_STATUSES[kind], 'text': text, 'on': on, 'at': _now_text(), 'by': actor or ''}
    conn.execute('UPDATE pump_cases SET job_status=?, last_activity_at=?, updated_at=? WHERE id=?',
                 (json.dumps(rec), _now_text(), _now_text(), case_id))
    if kind == 'scheduled':
        conn.execute('UPDATE pump_cases SET scheduled_for=? WHERE id=?', (on, case_id))
        if not (c['steps'].get('scheduled') or {}).get('at'):
            _set_step(conn, case_id, 'scheduled', at=today, by=actor)
    elif kind == 'work_done' and not (c['steps'].get('work_done') or {}).get('at'):
        _set_step(conn, case_id, 'work_done', at=on or today, by=actor)
    if kind in ('parts_ordered', 'waiting_vendor', 'scheduled') and CHASE_PHASES.get(c['stage']):
        # Nobody needs to chase the vendor before the date they gave - or, with no
        # date, for the usual few working days (then it's a follow-up again).
        conn.execute('UPDATE pump_cases SET vendor_follow=? WHERE id=?', (json.dumps(
            {'phase': CHASE_PHASES[c['stage']], 'at': _now_text(), 'by': actor or '',
             'who': _vendor_contact(c.get('vendor') or 'Wettech')[0], 'how': '',
             'said': f"{JOB_STATUSES[kind]}{': ' + text if text else ''}", 'expect_by': on,
             'check_on': '' if on else _workdays_after(_today(), VENDOR_FOLLOW_DAYS).isoformat()}), case_id))
    when = {'parts_ordered': 'parts due', 'waiting_vendor': 'expected', 'scheduled': 'for',
            'work_done': 'on'}.get(kind, 'on')
    _event(conn, actor, 'status', ' · '.join(x for x in (JOB_STATUSES[kind], text,
                                                        f'{when} {on}' if on else '') if x), case_id=case_id)
    return rec


@api('/cases/<int:case_id>/status/kind', methods=('POST',))
def h_case_status_kind(actor, case_id):
    """{"kind": ...} - the latest status update was picked as the wrong kind ("Parts ordered" for a
    follow-up with the client, Oct 2026): relabelled, its words and date kept."""
    kind = str(_json().get('kind') or '')
    if kind not in JOB_STATUSES:
        raise ValueError('Pick what the update is')
    conn = _conn()
    try:
        row = conn.execute('SELECT job_status FROM pump_cases WHERE id=?', (case_id,)).fetchone()
        if not row:
            return {'success': False, 'error': 'Not found'}, 404
        rec = json.loads(row['job_status'] or '{}')
        if not rec.get('kind'):
            raise ValueError('There is no status update to change')
        was = rec.get('label') or ''
        rec.update(kind=kind, label=JOB_STATUSES[kind])
        conn.execute('UPDATE pump_cases SET job_status=?, updated_at=? WHERE id=?', (json.dumps(rec), _now_text(), case_id))
        _event(conn, actor, 'status', f"{was} changed to {JOB_STATUSES[kind]}"
                                      f"{' · ' + rec['text'] if rec.get('text') else ''}", case_id=case_id)
        conn.commit()
        return {'case': case_detail(conn, case_id)}
    finally:
        conn.close()


@api('/cases/<int:case_id>/status', methods=('POST',))
def h_case_status(actor, case_id):
    """A status update on a job: {"kind": parts_ordered|waiting_vendor|client_notified|scheduled|
    in_progress|work_done|on_hold|note, "text": "...", "on": "YYYY-MM-DD"}."""
    d = _json()
    conn = _conn()
    try:
        if not set_job_status(conn, case_id, actor, str(d.get('kind') or ''), str(d.get('text') or ''),
                              str(d.get('on') or '')):
            return {'success': False, 'error': 'Not found'}, 404
        conn.commit()
        return {'case': case_detail(conn, case_id)}
    finally:
        conn.close()


@api('/cases/<int:case_id>/done', methods=('POST',))
def h_case_done(actor, case_id):
    """The office marks a job done by hand ({"note": "..."}): it leaves the
    lists and its open issues are cleared. {"reopen": true} undoes it."""
    d = _json()
    conn = _conn()
    try:
        if not conn.execute('SELECT 1 FROM pump_cases WHERE id=?', (case_id,)).fetchone():
            return {'success': False, 'error': 'Not found'}, 404
        if d.get('reopen'):
            conn.execute("UPDATE pump_cases SET status='open', closed_by_hand='', closed_at=NULL, updated_at=? WHERE id=?",
                         (_now_text(), case_id))
            _refresh_case(conn, case_id)
            _event(conn, actor, 'reopened', '', case_id=case_id)
        else:
            note = (d.get('note') or '').strip()
            conn.execute("UPDATE pump_cases SET status='closed', stage='done', closed_by_hand=?, closed_at=?, updated_at=? "
                         "WHERE id=?", (f'{actor}: {note}' if note else actor, _now_text(), _now_text(), case_id))
            conn.execute("UPDATE pump_issues SET resolved_at=?, resolved_by=?, resolution=? WHERE case_id=? AND "
                         "resolved_at IS NULL", (_now_text(), actor, 'Job marked done by hand', case_id))
            _event(conn, actor, 'marked done by hand', note, case_id=case_id)
        conn.commit()
        return {}
    finally:
        conn.close()


@api('/cases/<int:case_id>/delete', methods=('POST',))
def h_case_delete(actor, case_id):
    """Cancel (kept, with its history) - items are never hard-deleted."""
    if actor == BOT:
        return _office_only(actor, 'Cancelling an item')
    conn = _conn()
    try:
        conn.execute("UPDATE pump_cases SET status='cancelled', stage='cancelled', updated_at=? WHERE id=?",
                     (_now_text(), case_id))
        conn.execute("UPDATE pump_issues SET resolved_at=?, resolved_by=?, resolution=? WHERE case_id=? AND "
                     "resolved_at IS NULL", (_now_text(), actor, 'Job removed', case_id))
        _event(conn, actor, 'cancelled', _json().get('reason', ''), case_id=case_id)
        conn.commit()
        return {}
    finally:
        conn.close()


@api('/sheet/save', methods=('POST',))
def h_sheet_save(actor):
    """A row edited in the Tracker sheet: create or update the item."""
    data = _json()
    fields = {k: data.get(k) for k in SHEET_COLUMNS if k in data}
    conn = _conn()
    try:
        if data.get('id'):
            cid = int(data['id'])
            row = conn.execute('SELECT vendor_quote_amount, vendor_bill_amount FROM pump_cases WHERE id=?',
                               (cid,)).fetchone()
            # An amount typed over in the sheet replaces what was read from the
            # document, so the with-tax total read alongside it no longer applies.
            for amt, tot in (('vendor_quote_amount', 'vendor_quote_total'), ('vendor_bill_amount', 'vendor_bill_total')):
                if row and amt in fields and _money(fields[amt]) != row[amt]:
                    fields[tot] = None
            update_case(conn, cid, fields, actor)
        else:
            if data.get('month') and not fields.get('opened_on'):
                try:
                    m = datetime.strptime(data['month'], '%B %Y')
                    today = _today()
                    fields['opened_on'] = (today.isoformat() if (m.year, m.month) == (today.year, today.month)
                                           else m.strftime('%Y-%m-01'))
                except ValueError:
                    pass
            fields['title'] = fields.get('client_name') or fields.get('description') or 'Pump work'
            cid = create_case(conn, fields, actor, source='sheet')
            _steps_from_amounts(conn, cid, actor)
            _check_bill(conn, cid, actor)
        conn.commit()
        return {'id': cid}
    finally:
        conn.close()


@api('/docs', methods=('POST',))
def h_doc_upload(actor):
    """Upload a quote, bill or report. multipart 'file' (repeatable), or JSON
    {"filename", "content_base64", "kind", "case_id", "email_subject", "email_from"}."""
    results = []
    if request.files:
        kind = request.form.get('kind') or None
        case_id = request.form.get('case_id', type=int)
        for f in request.files.getlist('file'):
            results.append({'file': f.filename, **ingest_document(f.filename, f.read(), source='upload',
                                                                  kind_hint=kind, actor=actor, case_id=case_id)})
    else:
        data = _json()
        raw = base64.b64decode(data.get('content_base64') or '')
        if not raw:
            raise ValueError('content_base64 is empty')
        results.append({'file': data.get('filename'), **ingest_document(
            data.get('filename') or 'upload.pdf', raw, source='openclaw' if actor == BOT else 'upload',
            kind_hint=data.get('kind'), actor=actor, case_id=data.get('case_id'),
            email={'subject': data.get('email_subject', ''), 'from': data.get('email_from', ''),
                   'date': data.get('email_date', '')})})
    return {'results': results}


DOC_EDITABLE = ('kind', 'vendor', 'doc_number', 'doc_date', 'po_number', 'wo_number', 'quote_ref', 'ordered_by',
                'client_name', 'site', 'category', 'description')


@api('/docs/<int:doc_id>', methods=('PATCH', 'POST'))
def h_doc_update(actor, doc_id):
    """Correct what was read, link to an item, dismiss, or re-file."""
    data = _json()
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
        if not row:
            return {'success': False, 'error': 'Not found'}, 404
        sets, vals = [], []
        new_name = str(data.get('client_name') or '').strip()
        if new_name and new_name != (row['client_name'] or '').strip() and (row['client_name'] or '').strip() \
                and not (row['orig_client_name'] or '').strip():
            sets.append('orig_client_name=?')
            vals.append(row['client_name'].strip())
        for k in DOC_EDITABLE:
            if k in data and data[k] is not None:
                v = str(data[k]).strip()
                if k == 'kind' and v not in ('quote', 'bill', 'report', 'other'):
                    continue
                sets.append(f'{k}=?')
                vals.append(_iso_date(v) if k == 'doc_date' else v)
        for k in ('subtotal', 'tax', 'total'):
            if k in data:
                sets.append(f'{k}=?')
                vals.append(_money(data[k]))
        if isinstance(data.get('line_items'), list):
            sets.append('line_items=?')
            vals.append(json.dumps(_clean_extraction({'line_items': data['line_items']})['line_items']))
        if 'case_id' in data:
            sets.append('case_id=?')
            vals.append(int(data['case_id']) if data['case_id'] else None)
        if data.get('status') == 'dismissed' and actor == BOT:
            return _office_only(actor, 'Dismissing a document')
        if data.get('status') in ('dismissed', 'new', 'review', 'filed', 'done'):
            sets.append('status=?')
            vals.append(data['status'])
        elif sets:
            sets.append('review_reason=?')
            vals.append('')
            if row['status'] == 'review':
                sets.append("status='new'")
        if sets:
            conn.execute(f"UPDATE pump_docs SET {', '.join(sets)}, updated_at=? WHERE id=?", (*vals, _now_text(), doc_id))
            _event(conn, actor, 'document edited', ', '.join(s.split('=')[0] for s in sets), case_id=row['case_id'],
                   doc_id=doc_id)
        filed = None
        if data.get('file') or ('case_id' in data and data['case_id']) or (row['status'] == 'review' and sets
                                                                             and data.get('status') != 'dismissed'):
            filed = file_document(conn, doc_id, actor)
        conn.commit()
        return {'doc': _doc_dict(conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()),
                'case_id': filed}
    finally:
        conn.close()


@api('/docs/<int:doc_id>/rebrand', methods=('POST',))
def h_doc_rebrand(actor, doc_id):
    """(Re)build the Stahlman-England version of a Word report. Optional
    {"technician_names": [...]} names to remove as well."""
    data = _json()
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
        if not row or not row['file_name'].lower().endswith('.docx'):
            raise ValueError('Only a .docx report can be rebranded')
        with open(row['file_path'], 'rb') as f:
            src = f.read()
        out, info = pump_reports.rebrand_report(src, extra_tech_names=data.get('technician_names') or [])
        path, _ = _store_file(out, _branded_name(row['file_name']))
        _make_branded_pdf(path, out)
        rf = {**pump_reports.read_report(out), 'from_branded': True}
        conn.execute("UPDATE pump_docs SET branded_path=?, branded_info=?, report_fields=?, kind='report', "
                     "review_reason='', updated_at=? WHERE id=?",
                     (path, json.dumps(info), json.dumps(rf), _now_text(), doc_id))
        _event(conn, actor, 'report rebranded', json.dumps(info)[:500], case_id=row['case_id'], doc_id=doc_id)
        conn.commit()
        return {'info': info}
    finally:
        conn.close()


@api('/docs/<int:doc_id>/invoice', methods=('POST',))
@jobber_button
def h_doc_invoice(actor, doc_id):
    """Create the Jobber DRAFT invoice for a bill. Body: {"client_id",
    "line_items": [...], "subject", "job_id"}. Without client_id, the clear
    best client match is used, or the candidates are returned to choose from.
    Nothing is ever sent to the client."""
    data = _json()
    client_id = data.get('client_id')
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
        if not row:
            return {'success': False, 'error': 'Not found'}, 404
        doc = _doc_dict(row)
        case = dict(conn.execute('SELECT * FROM pump_cases WHERE id=?', (doc['case_id'],)).fetchone()) if doc['case_id'] else {}
    finally:
        conn.close()
    if actor == BOT and case:
        conn = _conn()
        try:
            open_n = conn.execute('SELECT COUNT(*) FROM pump_issues WHERE case_id=? AND resolved_at IS NULL',
                                  (case['id'],)).fetchone()[0]
        finally:
            conn.close()
        steps = json.loads(case.get('steps') or '{}')
        if open_n or not ((steps.get('bill_checked') or {}).get('at') or (steps.get('bill_checked') or {}).get('na')):
            return {'success': False, 'error': 'The bill has not been checked against the quote (or the item has '
                                               'open issues) - the office decides this one.'}, 409
    if client_id:
        remember_choice(doc, client_id, data.get('client_name') or '', actor=actor)
    if not client_id:
        client_id = (json.loads(case.get('jobber') or '{}').get('client') or {}).get('id') or case.get('jobber_client_id')
    if not client_id:
        alias = match_site_alias(doc, case)
        client_id = alias['client_id'] if alias else None
    if not client_id:
        cands = search_clients(case.get('client_name') or doc.get('client_name') or '')
        pick = pick_client(cands)
        if not pick:
            return {'success': False, 'needs_client': True, 'candidates': cands,
                    'error': 'More than one Jobber client could match - choose one.'}, 409
        client_id = pick['id']
    sugg = invoice_suggestion(doc, case, client_id)
    job_id = data.get('job_id')
    if job_id is None:
        job_id = (json.loads(case.get('jobber') or '{}').get('job') or {}).get('id') or \
            ((sugg.get('job') or {}).get('id') if (sugg.get('client_id') in (None, client_id)) else '') or ''
    on_job = bool(sugg.get('job') and job_id == sugg['job']['id'])
    # A monthly/quarterly: the visit is marked complete first, then invoiced, as a draft.
    visit = complete_visit_for_bill(doc, case, sugg['job'], actor) if on_job else None
    try:
        res = create_draft_invoice(doc_id, client_id, data.get('line_items') or sugg['line_items'],
                                   data.get('subject') or sugg['subject'], job_id or '', actor,
                                   force=bool(data.get('force')), visit_ids=_visit_ids(visit))
    except PossibleDuplicate as e:
        return {'success': False, 'possible_duplicate': e.rec, 'error': str(e)}, 409
    if on_job:
        invoiced_on_job(doc, case, sugg['job'], actor)
        res['visit'] = visit
    return {'invoice': res}


def _visit_ids(visit):
    """The completed visit's id from complete_visit_for_bill()'s answer."""
    v = (visit or {}).get('visit') or {}
    return [v['id']] if v.get('id') and ((visit or {}).get('completed') or (visit or {}).get('already_complete')) else []


def invoiced_on_job(doc, case, job, actor='system'):
    """A bill invoiced on the Jobber job it matched: the job goes on the item,
    the job stands in for the quote, and a bill that doesn't line up with the
    job's price is a to-do to check with the vendor."""
    if not case or not case.get('id'):
        return
    conn = _conn()
    try:
        jj = json.loads(conn.execute('SELECT jobber FROM pump_cases WHERE id=?', (case['id'],)).fetchone()[0] or '{}')
        jj['job'] = {'id': job['id'], 'number': job.get('number'), 'uri': job.get('uri')}
        conn.execute('UPDATE pump_cases SET jobber=? WHERE id=?', (json.dumps(jj), case['id']))
        resolve_issues(conn, case['id'], 'no_quote', actor, f"Invoiced on Jobber job #{job.get('number')}")
        merge_report_items(conn, job['id'], actor)
        _set_step(conn, case['id'], 'bill_checked', at=_today().isoformat(), by=actor)
        _event(conn, actor, 'invoiced on matching job', f"Jobber job #{job.get('number')} {job.get('title')}",
               case_id=case['id'], doc_id=doc.get('id'))
        base = doc.get('subtotal') if doc.get('subtotal') is not None else doc.get('total')
        # A recurring maintenance job has its own price; the bill isn't marked up to it.
        if job.get('type') != 'recurring' and base is not None and job.get('total') is not None and \
                abs(round(base * (1 + QUOTE_MARKUP_PCT / 100), 2) - float(job['total'])) > 1:
            name, email = _vendor_contact(case.get('vendor') or doc.get('vendor'))
            add_todo(conn, f"job-check:{case['id']}:{doc.get('doc_number') or doc.get('id')}",
                     f"Check with {name} - {doc.get('vendor') or 'vendor'} bill doesn't line up with job #{job.get('number')}",
                     f"Bill {('#' + doc['doc_number'] + ' ') if doc.get('doc_number') else ''}${base:,.2f} "
                     f"(${base * (1 + QUOTE_MARKUP_PCT / 100):,.2f} with {QUOTE_MARKUP_PCT:g}%) vs job #{job.get('number')} "
                     f"\"{job.get('title')}\" ${float(job['total']):,.2f}. The invoice is drafted at the job's price. {email}",
                     {'case_id': case['id'], 'uri': job.get('uri') or ''})
        conn.commit()
    finally:
        conn.close()


@api('/docs/<int:doc_id>/read_again', methods=('POST',))
def h_doc_read_again(actor, doc_id):
    """Read a quote or bill again with today's reader and update its job."""
    return read_doc_again(doc_id, actor)


@api('/docs/<int:doc_id>/reread', methods=('POST',))
def h_doc_reread(actor, doc_id):
    """Read a document again with Claude, and file it if it now reads cleanly."""
    return reread_doc(doc_id, actor)


@api('/docs/<int:doc_id>/quote', methods=('POST',))
@jobber_button
def h_doc_quote(actor, doc_id):
    """Create our DRAFT quote to the client in Jobber from a vendor's quote.
    Body: {"client_id", "property_id", "line_items": [...], "title", "message"}.
    Without client_id / property_id, the item's (or the one clear match) is
    used, or the choices are returned. Nothing is ever sent to the client.
    Office only: what we quote a client is the office's decision."""
    if actor == BOT:
        return _office_only(actor, 'Drafting a client quote')
    data = _json()
    client_id, property_id = data.get('client_id'), data.get('property_id')
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
        if not row:
            return {'success': False, 'error': 'Not found'}, 404
        doc = _doc_dict(row)
        case = dict(conn.execute('SELECT * FROM pump_cases WHERE id=?', (doc['case_id'],)).fetchone()) if doc['case_id'] else {}
    finally:
        conn.close()
    if not (client_id and property_id):
        t = resolve_quote_target(doc, case) if not client_id else \
            resolve_quote_target(doc, {**case, 'jobber': '{}', 'jobber_client_id': client_id,
                                       'jobber_property_id': ''})
        client_id = client_id or t['client_id']
        if not client_id:
            return {'success': False, 'needs_client': True, 'candidates': t['candidates'],
                    'error': 'More than one Jobber client could match - choose one.'}, 409
        property_id = property_id or (t['property_id'] if t['client_id'] == client_id else None)
        if not property_id:
            props = t['properties'] or client_jobs(client_id)['properties']
            return {'success': False, 'needs_property': True, 'properties': props, 'client_id': client_id,
                    'error': "Choose the client's property for the quote." if props else
                             'This client has no property in Jobber - add one in Jobber first.'}, 409
    sugg = suggest_quote(doc, case)
    try:
        res = create_draft_quote(doc_id, client_id, property_id, data.get('line_items') or sugg['line_items'],
                                 data.get('title') or sugg['title'], data.get('message') or '', actor,
                                 force=bool(data.get('force')))
    except PossibleDuplicate as e:
        return {'success': False, 'possible_duplicate': e.rec, 'error': str(e)}, 409
    rem = data.get('remember') or {}
    if rem.get('place'):
        save_site_alias(rem.get('place'), rem.get('area'), client_id, rem.get('client_name'), property_id,
                        rem.get('property_label'), rem.get('note'), actor)
    elif data.get('client_id'):
        remember_choice(doc, client_id, data.get('client_name') or '', property_id, data.get('property_label') or '',
                        actor)
    return {'quote': res}


@api('/docs/<int:doc_id>/quote_target')
def h_doc_quote_target(actor, doc_id):
    """Who the app thinks a vendor quote is for, to start the dialog from."""
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
        if not row:
            return {'success': False, 'error': 'Not found'}, 404
        doc = _doc_dict(row)
        case = dict(conn.execute('SELECT * FROM pump_cases WHERE id=?', (doc['case_id'],)).fetchone()) if doc['case_id'] else {}
    finally:
        conn.close()
    return {'target': resolve_quote_target(doc, case)}


@api('/site-names')
def h_site_names(actor):
    return {'site_names': site_aliases()}


@api('/site-names', methods=('POST',))
def h_site_name_save(actor):
    """{"place": "Carlisle", "area": "back station", "client_id", "client_name",
    "property_id", "property_label", "note"} - how one account names a site."""
    if actor == BOT:
        return _office_only(actor, 'Saving a site name')
    d = _json()
    save_site_alias(d.get('place'), d.get('area'), d.get('client_id'), d.get('client_name'), d.get('property_id'),
                    d.get('property_label'), d.get('note'), actor, d.get('job_id'), d.get('job_label'))
    return {'site_names': site_aliases()}


@api('/site-names/<int:alias_id>/delete', methods=('POST',))
def h_site_name_delete(actor, alias_id):
    if actor == BOT:
        return _office_only(actor, 'Removing a site name')
    conn = _conn()
    try:
        conn.execute('DELETE FROM pump_site_aliases WHERE id=?', (alias_id,))
        _event(conn, actor, 'site name removed', str(alias_id))
        conn.commit()
    finally:
        conn.close()
    return {'site_names': site_aliases()}


@api('/docs/<int:doc_id>/report_done', methods=('POST',))
def h_doc_report_done(actor, doc_id):
    """The report was put in Jobber by hand: off the Log report list, and
    "Report logged in Jobber" ticked on its job."""
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
        if not row or row['kind'] != 'report':
            return {'success': False, 'error': 'Not found'}, 404
        doc = _doc_dict(row)
        j = {k: v for k, v in (doc.get('jobber') or {}).items() if k != 'note_pending'}
        j.update(note_id='by hand', logged_by=actor, logged_at=_now_text())
        conn.execute("UPDATE pump_docs SET jobber=?, status='done', updated_at=? WHERE id=?",
                     (json.dumps(j), _now_text(), doc_id))
        if doc.get('case_id'):
            _set_step(conn, doc['case_id'], 'report_logged', at=_today().isoformat(), by=actor)
            _event(conn, actor, 'report logged by hand', doc.get('file_name') or '', case_id=doc['case_id'],
                   doc_id=doc_id)
        conn.commit()
        return {'case_id': doc.get('case_id')}
    finally:
        conn.close()


@api('/docs/<int:doc_id>/report_note', methods=('POST',))
@jobber_button
def h_doc_report_note(actor, doc_id):
    """Log a report as a note in Jobber. Body: {"target_type": "job"|"client",
    "target_id", "message"}. Without a target, the pump's job is found from the
    report's customer and location when there is one clear answer."""
    data = _json()
    ttype, tid = data.get('target_type'), data.get('target_id')
    section = data.get('section')
    section = int(section) if str(section).isdigit() else None
    if not (ttype and tid):
        conn = _conn()
        try:
            doc = _doc_dict(conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone())
            case = dict(conn.execute('SELECT * FROM pump_cases WHERE id=?', (doc['case_id'],)).fetchone()) if doc['case_id'] else {}
        finally:
            conn.close()
        t = resolve_report_target(doc, case)
        if not t.get('id'):
            return {'success': False, 'needs_target': True, 'error': t.pop('needs'), **t}, 409
        ttype, tid = t['type'], t['id']
    note = log_report_to_jobber(doc_id, ttype, tid, actor, data.get('message'), **({'section': section}
                                                                                 if section is not None else {}))
    if section is not None:
        # One station's page: the job isn't remembered for the whole site.
        tid, ttype = '', 'client'
    if data.get('client_id'):
        conn = _conn()
        try:
            doc = _doc_dict(conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone())
        finally:
            conn.close()
        remember_report_choice(doc, data['client_id'], data.get('client_name') or '',
                               tid if ttype == 'job' else '', data.get('job_label') or '', actor)
    return {'note': note}


def remember_report_choice(doc, client_id, client_name='', job_id='', job_label='', actor='system'):
    """The client (and pump job) the office logged a report on, kept under the
    vendor's name for the site: the next report with that name goes to the
    same place by itself, and the Log report window starts on it. Renamed on
    the document: remembered under the vendor's name too."""
    orig = (doc.get('orig_client_name') or '').strip()
    if orig and orig != (doc.get('client_name') or '').strip():
        remember_report_choice({**doc, 'client_name': orig, 'orig_client_name': ''}, client_id, client_name, job_id,
                               job_label, actor)
    place = re.sub(r'\s+', ' ', (doc.get('client_name') or '').strip())[:80]
    if not place or not client_id:
        return None
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM pump_site_aliases WHERE place=? AND area=''", (place,)).fetchone()
    finally:
        conn.close()
    a = dict(row) if row else None
    if a and a['client_id'] == client_id and (a.get('job_id') or '') == (job_id or ''):
        return None
    same = bool(a and a['client_id'] == client_id)
    save_site_alias(place, '', client_id, client_name or (a or {}).get('client_name') or '',
                    a['property_id'] if same else '', a['property_label'] if same else '',
                    f'Report logged by {actor} on {_today().isoformat()}', actor, job_id=job_id, job_label=job_label)
    return place


@api('/issues/<int:issue_id>/bill-anyway', methods=('POST',))
@jobber_button
def h_issue_bill_anyway(actor, issue_id):
    """The office's override for a bill with no quote: clear the alert and
    invoice the bill plus 30%. Returns the bill to draft."""
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_issues WHERE id=?', (issue_id,)).fetchone()
        if not row:
            return {'success': False, 'error': 'Not found'}, 404
        conn.execute('UPDATE pump_issues SET resolved_at=?, resolved_by=?, resolution=? WHERE id=?',
                     (_now_text(), actor, f'Billed at the vendor bill plus {QUOTE_MARKUP_PCT:g}%', issue_id))
        _event(conn, actor, 'issue resolved', f"{row['message']} -> billed plus {QUOTE_MARKUP_PCT:g}%",
               case_id=row['case_id'])
        doc_id = row['doc_id']
        if row['case_id']:
            _set_step(conn, row['case_id'], 'bill_checked', at=_today().isoformat(), by=actor)
            if not doc_id:
                d = conn.execute("SELECT id FROM pump_docs WHERE case_id=? AND kind='bill' AND status != 'dismissed' "
                                 "ORDER BY id DESC", (row['case_id'],)).fetchone()
                doc_id = d['id'] if d else None
        conn.commit()
        return {'doc_id': doc_id}
    finally:
        conn.close()


@api('/issues/<int:issue_id>/resolve', methods=('POST',))
def h_issue_resolve(actor, issue_id):
    if actor == BOT:
        return _office_only(actor, 'Resolving an issue')
    data = _json()
    if not (data.get('resolution') or '').strip():
        raise ValueError('Say how it was resolved')
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_issues WHERE id=?', (issue_id,)).fetchone()
        if not row:
            return {'success': False, 'error': 'Not found'}, 404
        conn.execute('UPDATE pump_issues SET resolved_at=?, resolved_by=?, resolution=? WHERE id=?',
                     (_now_text(), actor, data['resolution'].strip(), issue_id))
        _event(conn, actor, 'issue resolved', f"{row['message']} -> {data['resolution'].strip()}", case_id=row['case_id'])
        if row['kind'] in ('amount_mismatch', 'no_quote') and row['case_id']:
            _set_step(conn, row['case_id'], 'bill_checked', at=_today().isoformat(), by=actor)
        conn.commit()
        return {}
    finally:
        conn.close()


@api('/scan', methods=('POST',))
def h_scan(actor):
    if not CFG.get('email_enabled'):
        raise ValueError('The PO@ mailbox is not configured on this server')
    started = start_scan(actor)
    return {'started': started, 'status': _state_get('scan_status') or {}}


@api('/scan')
def h_scan_status(actor):
    return {'status': _state_get('scan_status') or {}, 'recent_files': _state_get('scan_files') or []}


@api('/jobber/sync', methods=('POST',))
def h_jobber_sync(actor):
    if not jobber_status()['connected']:
        raise ValueError('Connect Jobber first')
    return {'started': start_jobber_sync(bool(_json().get('full')), actor), 'status': jobber_sync_state()}


def account_for_jobber(conn, it):
    """Our account name for a Jobber record. Jobber has who we bill, the
    account sheets have the community: Greenscapes in Jobber is "Carlisle
    (The Carlisle)" here. From the account's own Jobber link, the site names,
    or the client/property names; '' when it isn't clear."""
    it = dict(it)
    cid, pid = it.get('client_id') or '', it.get('property_id') or ''
    if cid:
        rows = conn.execute("SELECT name, jobber_property_id FROM pump_maint_accounts WHERE jobber_client_id=? "
                            "AND active=1", (cid,)).fetchall()
        hit = [r['name'] for r in rows if pid and r['jobber_property_id'] == pid] or \
            ([rows[0]['name']] if len(rows) == 1 else [])
        if hit:
            return hit[0]
        aliases = conn.execute('SELECT place, property_id FROM pump_site_aliases WHERE client_id=?', (cid,)).fetchall()
        places = {a['place'] for a in aliases if pid and a['property_id'] == pid} or \
            ({a['place'] for a in aliases} if len({a['place'] for a in aliases}) == 1 else set())
        if len(places) == 1:
            place = places.pop()
            return match_account(place, conn) or place
    return match_account(' '.join(x for x in (it.get('property_label'), it.get('client_name')) if x), conn) or ''


_SERVICE_CALL = re.compile(r'\bservice\s*call\b', re.I)


def service_call_steps(conn, cid, it, actor):
    """A service call is the start of the work, not a quote (Woodmere #14592, Oct
    2026): no quote steps, approved when it was booked, scheduled for its day."""
    steps = json.loads(conn.execute('SELECT steps FROM pump_cases WHERE id=?', (cid,)).fetchone()[0] or '{}')
    for k in ('assessment', 'vendor_quote', 'client_quote'):
        if not (steps.get(k) or {}).get('at'):
            _set_step(conn, cid, k, by=actor, na=True)
    booked = (it.get('created_at') or '')[:10] or _today().isoformat()
    if not (steps.get('client_approved') or {}).get('at'):
        _set_step(conn, cid, 'client_approved', at=booked, by=actor)
    if not (steps.get('scheduled') or {}).get('at'):
        _set_step(conn, cid, 'scheduled', at=(it.get('start_at') or '')[:10] or booked, by=actor)
    if it.get('start_at'):
        conn.execute("UPDATE pump_cases SET scheduled_for=? WHERE id=? AND COALESCE(scheduled_for, '')=''",
                     (it['start_at'][:10], cid))
    _event(conn, actor, 'service call', f"Jobber job #{it.get('number') or ''} {it.get('title') or ''} - the start of "
                                        'the work, no quote', case_id=cid)


def find_job_by_number(number):
    """A Jobber job by its number (e.g. 14592): from the sync, else from Jobber (kept in the sync's list)."""
    number = str(number or '').strip().lstrip('#')
    if not number.isdigit():
        raise ValueError('Type the Jobber job number, e.g. 14592')
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM pump_jobber_items WHERE kind='job' AND number=?", (number,)).fetchone()
        if row:
            return dict(row)
        def make(fields):
            return f'query($q: String!) {{ jobs(searchTerm: $q, first: 20) {{ nodes {{ {fields} }} }} }}'
        spec = ['id', 'jobNumber', 'title', 'jobStatus', 'jobType', 'createdAt', 'startAt', 'completedAt', 'jobberWebUri',
                'total', ('client', ['id', 'name']), ('property', ['id', _ADDR])]
        data, _ = _gql_tolerant(make, spec, {'q': number}, required=('id', 'jobNumber'))
        n = next((x for x in (data.get('jobs') or {}).get('nodes') or [] if str(x.get('jobNumber') or '') == number), None)
        if not n:
            return None
        it = {'jobber_id': n['id'], 'kind': 'job', 'number': number, 'title': n.get('title') or '',
              'status': (n.get('jobStatus') or '').lower(), 'job_type': (n.get('jobType') or '').lower(),
              'client_id': (n.get('client') or {}).get('id') or '', 'client_name': (n.get('client') or {}).get('name') or '',
              'property_id': (n.get('property') or {}).get('id') or '', 'property_label': _prop_label(n.get('property')),
              'total': _money(n.get('total')), 'created_at': (n.get('createdAt') or '')[:19].replace('T', ' '),
              'updated_at': _now_text(), 'start_at': (n.get('startAt') or '')[:10], 'completed_at': (n.get('completedAt') or '')[:10],
              'web_uri': n.get('jobberWebUri') or '', 'category': 'pump', 'po_number': po_from_title(n.get('title') or '')}
        conn.execute('INSERT OR IGNORE INTO pump_jobber_items (jobber_id, kind, number, title, status, job_type, client_id, '
                     'client_name, property_id, property_label, total, created_at, updated_at, start_at, completed_at, '
                     'web_uri, category, po_number, synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                     (it['jobber_id'], 'job', number, it['title'], it['status'], it['job_type'], it['client_id'],
                      it['client_name'], it['property_id'], it['property_label'], it['total'], it['created_at'],
                      it['updated_at'], it['start_at'], it['completed_at'], it['web_uri'], 'pump', it['po_number'],
                      _now_text()))
        conn.commit()
        return dict(conn.execute('SELECT * FROM pump_jobber_items WHERE jobber_id=?', (it['jobber_id'],)).fetchone())
    finally:
        conn.close()


def track_jobber_item(conn, it, actor, service_call=None):
    """Make an item here from a Jobber record and link the record to it."""
    cat = {'scada': 'scada', 'diver': 'diver', 'filter': 'filter'}.get(it['category'], 'repair')
    if it['kind'] == 'job' and re.search(r'maint|quarter|monthly|annual', it['title'] or '', re.I):
        cat = 'maintenance'
    account = account_for_jobber(conn, it)
    cid = create_case(conn, {'title': it['title'] or it['client_name'], 'category': cat,
                             'client_name': account or it['client_name'], 'site': it['property_label'],
                             'po_number': it['po_number'], 'jobber_client_id': it['client_id'],
                             'jobber_property_id': it['property_id'],
                             'vendor': 'Wettech' if cat in ('repair', 'maintenance')
                                       or re.search(r'we?t+e?ch|\bwet\b', it['title'] or '', re.I) else '',
                             'opened_on': (it['created_at'] or '')[:10],
                             'jobber_request_made': _jobber_ref_text(it)},
                      actor, source='jobber')
    _link_item(conn, it['jobber_id'], cid, actor)
    if it['kind'] == 'quote' and it['status'] in ('awaiting_response', 'changes_requested'):
        _set_step(conn, cid, 'client_quote', at=(it['created_at'] or '')[:10] or None, by=actor)
    if it['kind'] == 'quote' and it['status'] == 'approved':
        _set_step(conn, cid, 'client_quote', at=(it['created_at'] or '')[:10] or None, by=actor)
        _set_step(conn, cid, 'client_approved', at=(it['updated_at'] or '')[:10] or None, by=actor)
    if it['kind'] == 'job' and (service_call or (service_call is None and _SERVICE_CALL.search(it['title'] or ''))):
        service_call_steps(conn, cid, dict(it), actor)
        if it['completed_at'] or it['status'] == 'requires_invoicing':
            _set_step(conn, cid, 'work_done', at=(it['completed_at'] or it['updated_at'] or '')[:10] or None, by=actor)
    elif it['kind'] == 'job' and (it['completed_at'] or it['status'] == 'requires_invoicing'):
        _set_step(conn, cid, 'client_approved', at=(it['created_at'] or '')[:10] or None, by=actor)
        _set_step(conn, cid, 'work_done', at=(it['completed_at'] or it['updated_at'] or '')[:10] or None,
                  by=actor)
    elif it['kind'] == 'job' and cat == 'maintenance':
        _set_step(conn, cid, 'client_approved', at=(it['created_at'] or '')[:10] or None, by=actor)
    elif it['kind'] in ('job', 'request'):
        # Made in Jobber before any quote: the vendor goes out to look first.
        _set_assessment(conn, cid, (it['start_at'] or '')[:10],
                        done=it['kind'] == 'request' and it['status'] == 'assessment_completed', by=actor)
    return cid


@api('/jobber/items/<path:jobber_id>', methods=('POST',))
def h_jobber_item(actor, jobber_id):
    """{"action": "track"} makes an item from a Jobber record, {"action":
    "link", "case_id"} links it to an existing one, {"action": "ignore"} hides it."""
    data = _json()
    conn = _conn()
    try:
        it = conn.execute('SELECT * FROM pump_jobber_items WHERE jobber_id=?', (jobber_id,)).fetchone()
        if not it:
            return {'success': False, 'error': 'Not found'}, 404
        action = data.get('action')
        if action == 'ignore':
            conn.execute('UPDATE pump_jobber_items SET ignored=1 WHERE jobber_id=?', (jobber_id,))
            cid = None
        elif action == 'unignore':
            conn.execute('UPDATE pump_jobber_items SET ignored=0 WHERE jobber_id=?', (jobber_id,))
            cid = None
        elif action == 'link':
            cid = int(data['case_id'])
            _link_item(conn, jobber_id, cid, actor)
        elif action == 'track':
            cid = track_jobber_item(conn, it, actor)
        else:
            raise ValueError('action must be track, link, ignore or unignore')
        conn.commit()
    finally:
        conn.close()
    if action == 'track' and it['kind'] == 'quote' and it['status'] == 'approved':
        on_quote_approved(cid, actor)
    return {'case_id': cid}


def _set_assessment(conn, case_id, due='', done=False, by='system'):
    """Switch on the vendor's visit to assess, with the visit date when known."""
    row = conn.execute('SELECT steps FROM pump_cases WHERE id=?', (case_id,)).fetchone()
    steps = json.loads(row['steps'] or '{}')
    a = {k: v for k, v in (steps.get('assessment') or {}).items() if k != 'na'}
    if due:
        a['due'] = due
    if done and not a.get('at'):
        a.update(at=_today().isoformat(), by=by)
    steps['assessment'] = a
    conn.execute('UPDATE pump_cases SET steps=?, updated_at=? WHERE id=?', (json.dumps(steps), _now_text(), case_id))
    _refresh_case(conn, case_id)


def _link_item(conn, jobber_id, case_id, actor):
    it = conn.execute('SELECT * FROM pump_jobber_items WHERE jobber_id=?', (jobber_id,)).fetchone()
    if not it:
        return
    conn.execute('UPDATE pump_jobber_items SET case_id=? WHERE jobber_id=?', (case_id, jobber_id))
    row = conn.execute('SELECT jobber, jobber_client_id FROM pump_cases WHERE id=?', (case_id,)).fetchone()
    j = json.loads(row['jobber'] or '{}')
    j[it['kind']] = {'id': it['jobber_id'], 'number': it['number'], 'uri': it['web_uri'], 'status': it['status'],
                     'total': it['total']}
    if it['client_id']:
        j.setdefault('client', {'id': it['client_id'], 'name': it['client_name']})
    conn.execute("UPDATE pump_cases SET jobber=?, jobber_client_id=COALESCE(NULLIF(jobber_client_id, ''), ?), "
                 "jobber_request_made=CASE WHEN COALESCE(jobber_request_made,'')='' THEN ? ELSE jobber_request_made END "
                 "WHERE id=?", (json.dumps(j), it['client_id'] or '', _jobber_ref_text(it), case_id))
    _event(conn, actor, 'linked Jobber', f"{it['kind']} #{it['number'] or ''} {it['title']}", case_id=case_id)




@api('/export.xlsx')
def h_export(actor):
    """The Tracker sheet for one month as an Excel file."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    month = request.args.get('month') or _now().strftime('%B %Y')
    conn = _conn()
    try:
        cases = list_cases(conn, 'all', month)
    finally:
        conn.close()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = month[:31]
    heads = ['PO#', 'Date', 'Vendor', 'Job Name /Address', 'Description of Work', 'Approved By',
             'Jobber Request Made', 'Vendor Quote Amount', 'Vendor Invoice Amount', 'Vendor Invoice#', 'Sei Invoice#',
             'Amount', 'Notes', 'Stage', 'Issue']
    ws.append(heads)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill('solid', fgColor='BDD7EE')
    for c in cases:
        ws.append([c['po_number'], c['opened_on'], c['vendor'], c['client_name'] or c['title'], c['description'],
                   c['approved_by'], c['jobber_request_made'], c['vendor_quote_amount'], c['vendor_bill_amount'],
                   c['vendor_bill_number'], c['sei_invoice_number'], c['amount'], c['notes'],
                   dict(STEPS).get(c['stage'], c['stage']).format(vendor=c['vendor'] or 'vendor'),
                   '; '.join(i['message'] for i in c.get('open_issues') or [])])
    for col, width in zip('ABCDEFGHIJKLMNO', (8, 11, 12, 30, 50, 14, 18, 14, 14, 12, 12, 12, 30, 22, 40)):
        ws.column_dimensions[col].width = width
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f'Pumps {month}.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ═════════════════════════════════════════════════════════════════════════════
# Diver schedule
# ═════════════════════════════════════════════════════════════════════════════
# Which pump sites need a diver (lake intakes, filters, fountains) and which
# do not, and the email the diver gets on the 1st of every month with that
# month's sites - the email Andrea used to write by hand.

DIVE_DEFAULTS = {
    'to': os.environ.get('PUMPS_DIVER_EMAIL', 'Gulfshoreyachts@gmail.com'),
    'diver_name': os.environ.get('PUMPS_DIVER_NAME', 'Jordan'),
    'cc': os.environ.get('PUMPS_DIVE_CC', 'Andrea@stahlman-england.com'),
    'from': os.environ.get('PUMPS_DIVE_FROM', ''),   # empty = the PO mailbox
    # Sent by itself on the 1st (Oct 2026); if it can't send, it stays a to-do.
    'auto': os.environ.get('PUMPS_DIVE_EMAIL_AUTO', 'true').lower() in ('1', 'true', 'yes', 'on'),
    'signature': os.environ.get('PUMPS_DIVE_SIGNATURE', 'Best Regards,\n\nAndrea Mitchell\nAssistant Client Service Manager\n'
                                'Andrea@stahlman-england.com\nO 239.514.1200\n\nStahlman-England\n'
                                '2063 Trade Center Way\nNaples, FL 34109'),
}
DIVE_STATUSES = ('active', 'meet', 'hold')
DIVE_SEND_HOUR = 7   # on the 1st, from 7am Naples time (a missed 1st is caught up on the 2nd or 3rd)

# Andrea's October 2026 list to the diver.
SEED_DIVE_SITES = [
    ("Anna's Place", '1 Lake 2 Filters', '5897 Ashford Ln', '', 'active', ''),
    ('Autumn Woods', '1 Lake 2 Filters', '6710 Goodlette Frank Rd.', '', 'active', ''),
    ('Banyan Bay', '1 Pump 1 Lake 1 Filter', '8125 Banyan Breeze Way #6107 (Clubhouse), Fort Myers, FL 33908',
     'Diver to check the rope that holds the float and filter. Replace if needed and bill us.', 'active', ''),
    ('Barrington Cove', '2 Pumps 2 Filters',
     'First pump station: west entrance of the parking area, next to 16164 Aberdeen. Second pump station: north side '
     'of the property (north entrance), across from 16420 Aberdeen.', '', 'active', ''),
    ('Carlisle (The Carlisle)', '2 Lakes 3 Filters', '6945 Carlisle Ct. - Pump #1; 6495 Carlisle Ct. - Pump #2', '',
     'active', ''),
    ('Caymas', '2 Pumps 2 Lakes', '5684 Barbuda Lane',
     '2nd pump is next to the roundabout at the front of the neighborhood, just past the guard gate.', 'active', ''),
    ('Cypress Legends (Behind Clubhouse)', '1 Pump 1 Lake Filter', '3427 Forum Blvd., Ft. Myers, FL', '', 'active', ''),
    ('Edgemont Office Park (Pine Air Lakes)', '1 Pump 1 Lake 1 Filter', '5695 Naples Blvd, Naples, FL', '', 'active', ''),
    ('Enclave @ Palmira', '2 Lakes 4 Filters', '28613 & 28653 San Lucas Lane, Bonita Springs', '', 'active', ''),
    ('Falling Waters II', '1 Lake 3 Filters', '2300 Hidden Lakes Dr., Naples', '', 'active', ''),
    ('Huntington Lakes Residence Assoc.', '10 Pumps 1 Lake 1 Filter', '6585 Huntington Lakes Circle, Naples, FL',
     'Gate code #0422', 'active', ''),
    ('Kurt Biggs', '1 Lake 1 Filter', '181 Eugenia Drive', 'Technician (Ramon) to be present for dive.', 'active', ''),
    ('Magnolia Cove at Falling Waters', '1 Pump 1 Lake Filter', '2344 Magnolia Lane', '', 'active', ''),
    ('Magnolia Falls at Falling Waters', '1 Pump 4 Filters', '2370 Magnolia Avenue, Naples, FL 34112',
     'Behind the Magnolia Falls sign.', 'active', ''),
    ('Miromar Outlets', '1 Lake Fountain (2 Filters)', '10801 Corkscrew Rd.', '', 'active', ''),
    ('Morton Grove', '1 Lake Fountain', '26801 Robinhood Lane, Bonita Springs 34135', '', 'active', ''),
    ('Pebblebrook HOA', '4 Pump Stations 9 Lake Fountains', '8610 Pebblebrook Drive', 'Gate code 22334', 'active', ''),
    ('Rosewood HOA', '1 Lake, 1 Lake', 'Left of 1655 Windy Pines Drive', '', 'active', ''),
    ('Sanctuary @ Blue Heron', '3 Lakes 9 Filters 3 Pump Stations', '706 Haven Drive, Naples, FL', '', 'active', ''),
    ('Spanish Wells Lake Club', '3 Lakes 6 Filters 3 Pump Stations (4 Pumps)', '28409 High Gate Dr, Bonita Springs, FL',
     '', 'meet', 'The HOA has asked to meet the diver onsite.'),
    ('Sopra Luxury Living', '1 Pump 1 Lake', '3280 Champion Ring Road, Fort Myers, Florida 33905', '', 'hold',
     'Called client to set up visit - waiting on approval.'),
    ('Tuscany Point Trail Association', '1 Lake', 'Tuscany Pointe Trl, Naples, FL 34120', 'Gate 2253', 'active', ''),
    ('University Square CDD', '1 Pump 1 Filter', '10801 Corkscrew Road, Estero, FL',
     'Second pump and lake filter not used.', 'active', ''),
    ('Watercrest @ Falling Waters', '1 Lake 1 Filter', '2326 Magnolia Lane, Naples', '', 'active', ''),
    ('Westminster HOA', '4 Lakes 9 Filters', '2001 Oxford Ridge Circle, Lehigh Acres', '', 'active', ''),
    ('Wild Blue', '1 Pump 1 Lake', '8396 Sea Glass Court, Sarasota, Florida 34240', '', 'active', ''),
]


def quote_to_job_title(client, number):
    """'Convert quote for Huntington #5 (#9149) to a job'."""
    who = f'quote for {client}' if client else 'Jobber quote'
    return f"Convert {who}{f' (#{number})' if number else ''} to a job"


def init_todo_table(c):
    c.execute('''CREATE TABLE IF NOT EXISTS pump_todos (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  kind TEXT DEFAULT 'manual',
                  key TEXT UNIQUE,
                  title TEXT NOT NULL,
                  detail TEXT DEFAULT '',
                  due_on TEXT DEFAULT '',
                  link TEXT DEFAULT '{}',
                  done_at TEXT,
                  done_by TEXT DEFAULT '',
                  created_by TEXT DEFAULT '',
                  created_at TEXT)''')
    # Rows taken off the To do list by hand (the ✕): the item itself is left
    # as it is. Keyed by what the row is about - an item's key includes its
    # step, so it comes back when the item moves on.
    c.execute('''CREATE TABLE IF NOT EXISTS pump_todo_hidden (
                  key TEXT PRIMARY KEY,
                  hidden_by TEXT DEFAULT '',
                  hidden_at TEXT)''')
    # Older quote-to-job to-dos led with the quote number; retitle open ones.
    for tid, title, detail in c.execute("SELECT id, title, detail FROM pump_todos WHERE key LIKE 'quote-to-job:%' "
                                        "AND done_at IS NULL AND title LIKE 'Convert Jobber quote #%'").fetchall():
        m = re.match(r'Convert Jobber quote #(\S*) to a job$', title)
        if m:
            client = (detail or '').split(' approved it.')[0] if ' approved it.' in (detail or '') else ''
            c.execute('UPDATE pump_todos SET title=? WHERE id=?', (quote_to_job_title(client.strip(), m.group(1)), tid))


def init_dive_tables(c):
    c.execute('''CREATE TABLE IF NOT EXISTS pump_dive_sites (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  equipment TEXT DEFAULT '',
                  address TEXT DEFAULT '',
                  diver_notes TEXT DEFAULT '',
                  needs_dive INTEGER DEFAULT 1,
                  months TEXT DEFAULT '',
                  status TEXT DEFAULT 'active',
                  status_note TEXT DEFAULT '',
                  month_note TEXT DEFAULT '',
                  jobber_client_id TEXT DEFAULT '',
                  updated_by TEXT DEFAULT '',
                  updated_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pump_dive_emails (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  month TEXT,
                  sent_at TEXT,
                  sent_by TEXT,
                  to_addr TEXT,
                  cc_addr TEXT,
                  subject TEXT,
                  body TEXT,
                  sites INTEGER,
                  error TEXT DEFAULT '')''')
    if not c.execute('SELECT 1 FROM pump_state WHERE key=?', ('dive_sites_seeded',)).fetchone():
        if not c.execute('SELECT 1 FROM pump_dive_sites').fetchone():
            now = _now_text()
            for name, equip, addr, notes, status, snote in SEED_DIVE_SITES:
                c.execute('''INSERT INTO pump_dive_sites (name, equipment, address, diver_notes, status, status_note,
                               updated_by, updated_at) VALUES (?,?,?,?,?,?,?,?)''',
                          (name, equip, addr, notes, status, snote, "Andrea's October list", now))
        c.execute('INSERT OR REPLACE INTO pump_state (key, value) VALUES (?,?)', ('dive_sites_seeded', '"yes"'))


def dive_settings():
    s = dict(DIVE_DEFAULTS)
    s.update({k: v for k, v in (_state_get('dive_settings') or {}).items() if k in DIVE_DEFAULTS})
    s['from'] = (s.get('from') or CFG.get('mail_from') or '').strip()
    return s


_MONTH_NAMES = {m: i for i, m in enumerate(('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct',
                                             'nov', 'dec'), 1)}


def _month_list(months):
    """"1,4,7,10" or "JAN, APR, JULY, OCT" -> [1, 4, 7, 10]."""
    out = []
    for tok in re.findall(r'\d+|[A-Za-z]+', months or ''):
        m = int(tok) if tok.isdigit() else _MONTH_NAMES.get(tok[:3].lower())
        if m and 1 <= m <= 12 and m not in out:
            out.append(m)
    return sorted(out)


def dive_sites(conn, include_all=True):
    rows = [dict(r) for r in conn.execute('SELECT * FROM pump_dive_sites ORDER BY name COLLATE NOCASE')]
    return rows if include_all else [r for r in rows if r['needs_dive']]


def sites_for_month(conn, month_date):
    """The sites the diver visits in a month: they need a diver and are on for
    that month (no months listed = every month)."""
    out = []
    for s in dive_sites(conn, include_all=False):
        if not s.get('active', 1):
            continue
        months = _month_list(s['months'])
        if not months or month_date.month in months:
            out.append(s)
    return out


def _site_lines(s):
    head = s['name']
    if s['status'] == 'hold':
        head = f"HOLD OFF - {s['status_note'] or 'waiting on the client'} - {s['name']}"
    elif s['status'] == 'meet':
        head = f"{s['name']} - the HOA wants to meet you onsite"
    lines = [head, s['equipment'], s['address']]
    for note in (s['diver_notes'], s['status_note'] if s['status'] == 'meet' else '', s['month_note']):
        if note:
            lines.append(note)
    return [l for l in lines if l]


def build_dive_email(conn, month_date):
    """Subject, plain text, HTML and a Word copy of the month's list."""
    st = dive_settings()
    sites = sites_for_month(conn, month_date)
    month = month_date.strftime('%B')
    meet = [s['name'] for s in sites if s['status'] == 'meet']
    intro = f"Please see the attached list for {month}."
    if meet:
        names = ', '.join(meet[:-1]) + (' and ' if len(meet) > 1 else '') + meet[-1]
        verb = 'have' if len(meet) > 1 else 'has'
        intro += (f" Please note that {names} {verb} requested to meet with you onsite. When you know what day you "
                  "are going to dive please let me know a couple of days ahead so I can coordinate with the HOA to "
                  "meet you there.")
    else:
        intro += ' When you know what days you are going to dive please let me know a couple of days ahead.'
    intro += ' Thanks!'
    hi = f"Hi {st['diver_name']}!" if st.get('diver_name') else 'Hi!'
    text = [hi, '', intro, '']
    for s in sites:
        text += _site_lines(s) + ['']
    text += [st['signature']]
    esc = lambda t: (t or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    html_sites = ''.join(
        '<p style="margin:0 0 12px">' + '<br>'.join(
            (f'<b>{esc(l)}</b>' if i == 0 else esc(l)) for i, l in enumerate(_site_lines(s))) + '</p>'
        for s in sites)
    para = '<p style="margin:0 0 12px">'
    html = (f'<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt">{para}{esc(hi)}</p>{para}{esc(intro)}</p>'
            f'{html_sites}{para}{"<br>".join(esc(l) for l in st["signature"].splitlines())}</p></div>')
    subject = f"Diver schedule - {month_date.strftime('%B %Y')} - Stahlman-England"
    return {'subject': subject, 'text': '\n'.join(text), 'html': html, 'sites': sites,
            'docx': _dive_docx(sites, month_date), 'docx_name': f"Diver schedule {month_date.strftime('%B %Y')}.docx",
            'to': st['to'], 'cc': st['cc'], 'from': st['from']}


def _dive_docx(sites, month_date):
    from docx import Document
    d = Document()
    d.add_heading(f"Stahlman-England - diver schedule - {month_date.strftime('%B %Y')}", level=1)
    t = d.add_table(rows=1, cols=4)
    t.style = 'Table Grid'
    for cell, head in zip(t.rows[0].cells, ('Site', 'Lakes / filters / pumps', 'Address', 'Notes')):
        cell.text = head
    for s in sites:
        lines = _site_lines(s)
        notes = '\n'.join(lines[3:]) if len(lines) > 3 else ''
        row = t.add_row().cells
        row[0].text, row[1].text, row[2].text, row[3].text = lines[0], s['equipment'], s['address'], notes
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _emails(text):
    return [a for a in re.split(r'[\s,;]+', text or '') if '@' in a]


def send_dive_email(month_date=None, actor='Pumps (1st of the month)', force=False):
    """Email the diver this month's list. Once per month unless forced (the
    office's "Send now"). Sent from the PO mailbox through Microsoft 365, with
    the office copied and replies going to them."""
    month_date = month_date or _today().replace(day=1)
    key = f"dive_email:{month_date.strftime('%Y-%m')}"
    st = dive_settings()
    to, cc = _emails(st['to']), _emails(st['cc'])
    if not to:
        raise ValueError("No diver email address - set it on the Divers tab")
    if not (CFG.get('graph_token') and st['from']):
        raise ValueError('Microsoft 365 is not connected for sending (MS_TENANT_ID / MS_CLIENT_ID / MS_CLIENT_SECRET)')
    conn = _conn()
    try:
        if not force:
            # Claim the month first, so two app workers never both send it.
            cur = conn.execute('INSERT OR IGNORE INTO pump_state (key, value) VALUES (?,?)', (key, json.dumps(_now_text())))
            conn.commit()
            if cur.rowcount == 0:
                return {'skipped': 'already sent this month'}
        mail = build_dive_email(conn, month_date)
    finally:
        conn.close()
    msg = {'subject': mail['subject'], 'body': {'contentType': 'HTML', 'content': mail['html']},
           'toRecipients': [{'emailAddress': {'address': a}} for a in to],
           'ccRecipients': [{'emailAddress': {'address': a}} for a in cc],
           'replyTo': [{'emailAddress': {'address': a}} for a in (cc or [st['from']])],
           'attachments': [{'@odata.type': '#microsoft.graph.fileAttachment', 'name': mail['docx_name'],
                            'contentType': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                            'contentBytes': base64.b64encode(mail['docx']).decode()}]}
    error = ''
    try:
        r = http_requests.post(f"https://graph.microsoft.com/v1.0/users/{st['from']}/sendMail", timeout=60,
                               headers={'Authorization': f"Bearer {CFG['graph_token']()}",
                                        'Content-Type': 'application/json'},
                               json={'message': msg, 'saveToSentItems': True})
        if r.status_code >= 400:
            try:
                error = (r.json().get('error') or {}).get('message') or r.text[:300]
            except ValueError:
                error = r.text[:300]
            error = f'Microsoft 365 said HTTP {r.status_code}: {error}'
    except Exception as e:
        error = f'Could not reach Microsoft 365: {e}'
    conn = _conn()
    try:
        conn.execute('''INSERT INTO pump_dive_emails (month, sent_at, sent_by, to_addr, cc_addr, subject, body, sites,
                          error) VALUES (?,?,?,?,?,?,?,?,?)''',
                     (month_date.strftime('%Y-%m'), _now_text(), actor, ', '.join(to), ', '.join(cc), mail['subject'],
                      mail['text'], len(mail['sites']), error))
        if error:
            if not force:
                conn.execute('DELETE FROM pump_state WHERE key=?', (key,))   # try again next hour
        else:
            conn.execute('INSERT OR REPLACE INTO pump_state (key, value) VALUES (?,?)', (key, json.dumps(_now_text())))
            # One-off notes were for this email only.
            conn.execute("UPDATE pump_todos SET done_at=?, done_by=? WHERE key=? AND done_at IS NULL",
                         (_now_text(), actor, f"diver-email:{month_date.strftime('%Y-%m')}"))
            ids = [s['id'] for s in mail['sites'] if s['month_note']]
            if ids:
                conn.execute(f"UPDATE pump_dive_sites SET month_note='' WHERE id IN ({','.join('?' * len(ids))})", ids)
        _event(conn, actor, 'diver schedule ' + ('NOT sent' if error else 'sent'),
               f"{mail['subject']} to {', '.join(to)}" + (f' - {error}' if error else ''))
        conn.commit()
    finally:
        conn.close()
    if error:
        raise RuntimeError(error)
    return {'sent': True, 'to': to, 'cc': cc, 'subject': mail['subject'], 'sites': len(mail['sites'])}


def _scheduled_dive_email():
    """Hourly: the month's to-do, and (if switched on) the email itself on the
    1st (or the 2nd/3rd if the app was down), from 7am."""
    ensure_monthly_todos()
    now = _now()
    if not dive_settings()['auto'] or now.day > 3 or now.hour < DIVE_SEND_HOUR:
        return
    if _state_get(f"dive_email:{now.strftime('%Y-%m')}"):
        return
    conn = _conn()
    try:
        if not sites_for_month(conn, now.date().replace(day=1)):
            return   # nobody to visit this month
    finally:
        conn.close()
    try:
        send_dive_email(now.date().replace(day=1))
    except (ValueError, RuntimeError) as e:
        print(f'  ⚠ Pumps: diver schedule not sent: {e}')


DIVE_FIELDS = ('name', 'equipment', 'address', 'diver_notes', 'months', 'status_note', 'month_note',
               'jobber_client_id', 'kind', 'joined', 'diver_cost', 'our_bill', 'naples_electric', 'follow_up')


@api('/dives')
def h_dives(actor):
    conn = _conn()
    try:
        month = _today().replace(day=1)
        if _today().day > 3:   # after the 1st, show next month's email
            month = (month + timedelta(days=32)).replace(day=1)
        sent = [dict(r) for r in conn.execute('SELECT id, month, sent_at, sent_by, to_addr, cc_addr, subject, sites, '
                                              'error FROM pump_dive_emails ORDER BY id DESC LIMIT 24')]
        return {'sites': dive_sites(conn), 'settings': dive_settings(), 'next_month': month.isoformat(),
                'next_count': len(sites_for_month(conn, month)), 'sent': sent,
                'can_send': bool(CFG.get('graph_token') and dive_settings()['from'])}
    finally:
        conn.close()


@api('/dives/preview')
def h_dives_preview(actor):
    month = _iso_date(request.args.get('month')) or _today().replace(day=1).isoformat()
    conn = _conn()
    try:
        m = build_dive_email(conn, datetime.strptime(month[:10], '%Y-%m-%d').date().replace(day=1))
    finally:
        conn.close()
    return {'subject': m['subject'], 'text': m['text'], 'html': m['html'], 'to': m['to'], 'cc': m['cc'],
            'from': m['from'], 'sites': len(m['sites'])}


@api('/dives/sites', methods=('POST',))
def h_dive_site_save(actor):
    """Add or change a site: {"id"?, "name", "equipment", "address", "diver_notes",
    "needs_dive", "months", "status", "status_note", "month_note"}."""
    if actor == BOT:
        return _office_only(actor, "Changing the diver's sites")
    d = _json()
    vals = {k: str(d.get(k) or '').strip()[:1000] for k in DIVE_FIELDS if k in d}
    for k in ('needs_dive', 'active'):
        if k in d:
            vals[k] = 1 if d[k] in (True, 1, '1', 'true', 'yes', 'on') else 0
    if 'status' in d:
        if d['status'] not in DIVE_STATUSES:
            raise ValueError('status must be active, meet or hold')
        vals['status'] = d['status']
    if 'months' in vals:
        vals['months'] = ','.join(str(m) for m in _month_list(vals['months']))
    conn = _conn()
    try:
        if d.get('id'):
            if 'name' in vals and not vals['name']:
                raise ValueError('A site needs a name')
            if vals:
                conn.execute(f"UPDATE pump_dive_sites SET {', '.join(k + '=?' for k in vals)}, updated_by=?, "
                             f"updated_at=? WHERE id=?", (*vals.values(), actor, _now_text(), int(d['id'])))
            sid = int(d['id'])
        else:
            if not vals.get('name'):
                raise ValueError('A site needs a name')
            cols = list(vals) + ['updated_by', 'updated_at']
            conn.execute(f"INSERT INTO pump_dive_sites ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                         (*vals.values(), actor, _now_text()))
            sid = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        _event(conn, actor, 'diver site saved', vals.get('name') or f'site {sid}')
        conn.commit()
        return {'sites': dive_sites(conn)}
    finally:
        conn.close()


@api('/dives/sites/<int:site_id>/delete', methods=('POST',))
def h_dive_site_delete(actor, site_id):
    if actor == BOT:
        return _office_only(actor, "Changing the diver's sites")
    conn = _conn()
    try:
        row = conn.execute('SELECT name FROM pump_dive_sites WHERE id=?', (site_id,)).fetchone()
        conn.execute('DELETE FROM pump_dive_sites WHERE id=?', (site_id,))
        _event(conn, actor, 'diver site removed', row['name'] if row else str(site_id))
        conn.commit()
        return {'sites': dive_sites(conn)}
    finally:
        conn.close()


@api('/dives/settings', methods=('POST',))
def h_dive_settings(actor):
    if actor == BOT:
        return _office_only(actor, "Changing the diver's email")
    d = _json()
    cur = _state_get('dive_settings') or {}
    for k in ('to', 'diver_name', 'cc', 'from', 'signature'):
        if k in d:
            cur[k] = str(d[k] or '').strip()[:2000]
    if 'auto' in d:
        cur['auto'] = bool(d['auto'])
    if 'to' in cur and cur['to'] and not _emails(cur['to']):
        raise ValueError("The diver's email address doesn't look right")
    _state_set('dive_settings', cur)
    return {'settings': dive_settings()}


@api('/dives/send', methods=('POST',))
def h_dive_send(actor):
    """Send this month's (or {"month": "YYYY-MM-01"}) list to the diver now."""
    if actor == BOT:
        return _office_only(actor, 'Emailing the diver')
    d = _json()
    month = _iso_date(d.get('month')) or _today().replace(day=1).isoformat()
    try:
        return send_dive_email(datetime.strptime(month[:10], '%Y-%m-%d').date().replace(day=1), actor, force=True)
    except RuntimeError as e:
        return {'success': False, 'error': str(e)}, 502



# ═════════════════════════════════════════════════════════════════════════════
# To-do list
# ═════════════════════════════════════════════════════════════════════════════
# Things the office has to do, ticked off when done. The app adds the
# recurring ones itself: on the 1st, "Email Jordan the <month> diver list",
# with the list ready to send.

def ensure_monthly_todos(today=None):
    today = today or _today()
    month = today.replace(day=1)
    st = dive_settings()
    conn = _conn()
    try:
        key = f"diver-email:{month.strftime('%Y-%m')}"
        n = len(sites_for_month(conn, month))
        if n and not conn.execute('SELECT 1 FROM pump_todos WHERE key=?', (key,)).fetchone():
            who = st.get('diver_name') or 'the diver'
            conn.execute('INSERT OR IGNORE INTO pump_todos (kind, key, title, detail, due_on, link, created_by, '
                         'created_at) VALUES (?,?,?,?,?,?,?,?)',
                         ('diver_email', key, f"Email {who} the {month.strftime('%B')} diver list",
                          f"{n} sites. The email and the Word list are ready: copy the email, attach the list and "
                          f"send it to {st['to']} (cc {st['cc']}).", month.isoformat(),
                          json.dumps({'month': month.isoformat()}), 'Pumps', _now_text()))
            conn.commit()
    finally:
        conn.close()


def _todo_dict(r):
    d = dict(r)
    try:
        d['link'] = json.loads(d.get('link') or '{}')
    except ValueError:
        d['link'] = {}
    return d


@api('/todos')
def h_todos(actor):
    ensure_monthly_todos()
    conn = _conn()
    try:
        rows = [_todo_dict(r) for r in conn.execute(
            'SELECT * FROM pump_todos WHERE done_at IS NULL OR done_at >= ? ORDER BY done_at IS NOT NULL, '
            'COALESCE(NULLIF(due_on, \'\'), created_at), id', ((_today() - timedelta(days=30)).isoformat(),))]
        return {'todos': rows}
    finally:
        conn.close()


@api('/todos', methods=('POST',))
def h_todo_add(actor):
    d = _json()
    title = (d.get('title') or '').strip()
    if not title:
        raise ValueError('Say what needs doing')
    conn = _conn()
    try:
        conn.execute('INSERT INTO pump_todos (kind, title, detail, due_on, created_by, created_at) VALUES (?,?,?,?,?,?)',
                     ('manual', title[:300], (d.get('detail') or '')[:2000], _iso_date(d.get('due_on')), actor,
                      _now_text()))
        conn.commit()
    finally:
        conn.close()
    return h_todos(actor)


# ── A to-do written from what someone explains ───────────────────────────────
# The office types what needs doing in their own words; the app shortens it to
# a to-do to check before it's saved: the first sentence, without "I need to",
# and a due date when one is said ("by Friday", "tomorrow", "10/16"). No AI.

_TODO_FILLER = re.compile(r'^\s*(?:(?:so|ok|okay|also|and|then)\b,?|(?:i|we)\s+(?:need|have|want|should|must)\s+to|'
                          r'(?:i|we)\s+(?:gotta|got\s+to)|(?:please\s+)?remind\s+me\s+to|remember\s+to|'
                          r'(?:can|could)\s+you|(?:i|we)\s*(?:\'ll|will)\s+need\s+to|need\s+to|have\s+to|please|'
                          r'(?:i|we)\s+(?:should|must|will|\'ll))\s+', re.I)
_WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
_DUE = re.compile(r'\b(?:(by|before|on|due|for|until)\s+)?(?:(today|tonight|tomorrow)|(this|next)\s+week|'
                  r'end\s+of\s+(?:the\s+)?(week|month)|(?:(this|next)\s+)?(' + '|'.join(_WEEKDAYS) +
                  r')|(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?)\b', re.I)


def due_from_text(text, today):
    """The date a to-do is due by when the text says one, else ''."""
    # A number date only after "by", "on", "due"...: "1/2 HP" is not January 2nd.
    m = next((m for m in _DUE.finditer(text or '') if not m.group(7) or m.group(1)), None)
    if not m:
        return ''
    day, week, end, which, wd, mo, dd, yy = m.groups()[1:]
    if day:
        return (today + timedelta(days=0 if day.lower() in ('today', 'tonight') else 1)).isoformat()
    friday = today + timedelta(days=(4 - today.weekday()) % 7)
    if week:
        return (friday + timedelta(days=7 if week.lower() == 'next' else 0)).isoformat()
    if end:
        if end.lower() == 'week':
            return friday.isoformat()
        nxt = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        return (nxt - timedelta(days=1)).isoformat()
    if wd:
        d = today + timedelta(days=(_WEEKDAYS.index(wd.lower()) - today.weekday()) % 7 or 7)
        if (which or '').lower() == 'next' and (d - today).days < 7 and today.weekday() < _WEEKDAYS.index(wd.lower()):
            d += timedelta(days=7)   # "next Friday" on a Monday = the Friday after this one
        return d.isoformat()
    try:
        y = int(yy) + (2000 if yy and len(yy) == 2 else 0) if yy else today.year
        d = date(y, int(mo), int(dd))
        if not yy and d < today - timedelta(days=60):
            d = d.replace(year=y + 1)   # "1/5" in October is next January
        return d.isoformat()
    except ValueError:
        return ''


def reword_todo(text, today=None):
    """A short to-do from someone's explanation: {title, detail, due_on}."""
    text = re.sub(r'\s+', ' ', text or '').strip()
    if not text:
        raise ValueError('Say what needs doing')
    today = today or _today()
    parts = re.split(r'(?<=[.!?])\s+', text, 1)
    first = parts[0].rstrip('.!? ')
    while _TODO_FILLER.match(first):
        first = _TODO_FILLER.sub('', first, 1)
    cut = len(first) > 80
    if cut:
        first = first[:80].rsplit(' ', 1)[0].rstrip(',;:-') + '…'
    title = (first[:1].upper() + first[1:]) or text[:80]
    # Details only when the title leaves something out.
    return {'title': title[:300], 'detail': (text if cut else (parts[1] if len(parts) > 1 else ''))[:2000],
            'due_on': due_from_text(text, today)}


@api('/todos/reword', methods=('POST',))
def h_todo_reword(actor):
    """{"text": what needs doing, in your own words} -> a to-do to check before saving."""
    return {'todo': reword_todo(str(_json().get('text') or '')[:4000])}


@api('/todos/<int:todo_id>/edit', methods=('POST',))
def h_todo_edit(actor, todo_id):
    """Change a to-do's wording or due date: {"title", "detail", "due_on"}."""
    d = _json()
    title = str(d.get('title') or '').strip()
    if not title:
        raise ValueError('Say what needs doing')
    conn = _conn()
    try:
        if not conn.execute('SELECT 1 FROM pump_todos WHERE id=?', (todo_id,)).fetchone():
            return {'success': False, 'error': 'Not found'}, 404
        conn.execute('UPDATE pump_todos SET title=?, detail=?, due_on=? WHERE id=?',
                     (title[:300], str(d.get('detail') or '')[:2000], _iso_date(d.get('due_on')) or '', todo_id))
        _event(conn, actor, 'to-do edited', title[:300])
        conn.commit()
    finally:
        conn.close()
    return {'id': todo_id}


@api('/todos/<int:todo_id>/done', methods=('POST',))
def h_todo_done(actor, todo_id):
    """{"done": true|false}"""
    done = _json().get('done', True)
    conn = _conn()
    try:
        row = conn.execute('SELECT title FROM pump_todos WHERE id=?', (todo_id,)).fetchone()
        if not row:
            return {'success': False, 'error': 'Not found'}, 404
        conn.execute('UPDATE pump_todos SET done_at=?, done_by=? WHERE id=?',
                     (_now_text() if done else None, actor if done else '', todo_id))
        _event(conn, actor, 'to-do done' if done else 'to-do reopened', row['title'])
        conn.commit()
    finally:
        conn.close()
    return h_todos(actor)


@api('/undo')
def h_undo_list(actor):
    return {'actions': recent_actions(), 'me': actor or ''}


@api('/undo/<int:action_id>', methods=('POST',))
def h_undo(actor, action_id):
    """{"also_later": true} also undoes later clicks that changed the same things."""
    try:
        return undo_action(action_id, actor, cascade=bool(_json().get('also_later')))
    except UndoBlocked as e:
        return {'success': False, 'error': str(e), 'blocked_by': e.labels}, 409


@api('/todos/hide', methods=('POST',))
def h_todo_hide(actor):
    """Take a row off the To do list (the ✕ - the item itself is left as it
    is). Body: {"key": the row's todo_key}. Undo brings it back."""
    key = str(_json().get('key') or '').strip()
    if not re.fullmatch(r'(?:case:\d+:[\w-]+|doc:\d+|issue:\d+|pay:\d+|scada:\d+:[\w-]*|jobber:[\w=+/-]+|todo:\d+)',
                        key):
        raise ValueError('Not a to-do row')
    conn = _conn()
    try:
        conn.execute('INSERT OR REPLACE INTO pump_todo_hidden (key, hidden_by, hidden_at) VALUES (?,?,?)',
                     (key, actor or '', _now_text()))
        conn.commit()
    finally:
        conn.close()
    return {}


@api('/todos/<int:todo_id>/delete', methods=('POST',))
def h_todo_delete(actor, todo_id):
    conn = _conn()
    try:
        conn.execute("DELETE FROM pump_todos WHERE id=? AND kind='manual'", (todo_id,))
        conn.commit()
    finally:
        conn.close()
    return h_todos(actor)


@api('/dives/docx')
def h_dives_docx(actor):
    """The month's list as a Word file, to attach to the email."""
    month = _iso_date(request.args.get('month')) or _today().replace(day=1).isoformat()
    conn = _conn()
    try:
        m = build_dive_email(conn, datetime.strptime(month[:10], '%Y-%m-%d').date().replace(day=1))
    finally:
        conn.close()
    return send_file(io.BytesIO(m['docx']), as_attachment=True, download_name=m['docx_name'],
                     mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')


# ═════════════════════════════════════════════════════════════════════════════
# Reports library
# ═════════════════════════════════════════════════════════════════════════════

def _report_date(d):
    return report_month_date(d) or (d.get('created_at') or '')[:10]


def reports_archive(fileobj):
    """Every pump report ever, in one zip (Oct 2026): our rebranded PDF (else the
    rebranded Word file, else the vendor's original under "not rebranded/"),
    in a folder per month, plus index.csv listing them all. Returns the count."""
    import csv
    conn = _conn()
    try:
        docs = [{**_doc_dict(r), 'file_path': r['file_path'], 'branded_path': r['branded_path']}   # paths kept
                for r in conn.execute("SELECT * FROM pump_docs WHERE kind='report' AND status != 'dismissed' ORDER BY id")]
    finally:
        conn.close()
    index, used, n = io.StringIO(), set(), 0
    w = csv.writer(index)
    w.writerow(['Date', 'Site', 'Location', 'Title', 'File in this zip', 'Logged in Jobber', 'Original file name'])
    with zipfile.ZipFile(fileobj, 'w', zipfile.ZIP_DEFLATED) as z:
        for d in sorted(docs, key=lambda d: (_report_date(d) or '', d['id'])):
            pdf = _branded_pdf_path(d.get('branded_path') or '')
            for path, ext, folder in ((pdf, '.pdf', ''), (d.get('branded_path'), '.docx', ''),
                                      (d.get('file_path'), os.path.splitext(d.get('file_name') or '')[1] or '.docx',
                                       'not rebranded/')):
                if path and os.path.exists(path):
                    break
            else:
                continue
            when = _report_date(d) or ''
            base = re.sub(r'[\\/:*?"<>|]+', '-', _vendor_file_name(d.get('file_name'), '')).strip() or f'report {d["id"]}'
            name = f"{folder}{when[:7] or 'undated'}/{base}{ext}"
            k = 2
            while name in used:
                name = f"{folder}{when[:7] or 'undated'}/{base} ({k}){ext}"
                k += 1
            used.add(name)
            z.write(path, name)
            n += 1
            w.writerow([when, d.get('client_name') or '', d.get('site') or '',
                        (d.get('report_fields') or {}).get('title') or 'Report', name,
                        'yes' if (d.get('jobber') or {}).get('note_id') else 'no', d.get('file_name') or ''])
        z.writestr('index.csv', index.getvalue())
    return n


@api('/reports/archive.zip')
def h_reports_archive(actor):
    """Download every pump report ever, in one zip."""
    import tempfile
    f = tempfile.TemporaryFile()
    reports_archive(f)
    f.seek(0)
    return send_file(f, mimetype='application/zip', as_attachment=True,
                     download_name=f'Pump reports - all - {_today().isoformat()}.zip')


def vendor_quotes(conn, show='open', q='', sort='az'):
    """Every vendor quote on file (Oct 2026: a Quotes tab for all of Wettech's
    quotes), newest first, with where it stands: our Jobber quote not made
    yet, a draft to send, out to the client, approved - or done/cancelled."""
    docs = [_doc_dict(r) for r in conn.execute(
        "SELECT * FROM pump_docs WHERE kind='quote' AND status != 'dismissed' ORDER BY id DESC")]
    ids = {d['case_id'] for d in docs if d.get('case_id')}
    cases = {r['id']: dict(r) for r in conn.execute(
        f"SELECT id, title, client_name, stage, status, jobber FROM pump_cases WHERE id IN ({','.join('?' * len(ids))})",
        list(ids))} if ids else {}
    q = (q or '').strip().lower()
    out, counts = [], {}
    for d in docs:
        c = cases.get(d.get('case_id')) or {}
        dj, cj = d.get('jobber') or {}, json.loads(c.get('jobber') or '{}')
        ours = cj.get('quote') or {}
        num = ours.get('number') or dj.get('quote_number') or ''
        st = (ours.get('status') or dj.get('quote_status') or '').lower()
        if not c and beatrice_site(d.get('client_name'), d.get('site')):
            state = 'beatrice'
        elif c.get('status') == 'cancelled':
            state = 'cancelled'
        elif st in ('approved', 'converted') or (c.get('stage') not in (None, '', 'assessment', 'vendor_quote',
                                                                         'client_quote', 'client_approved')
                                                  and c.get('status') == 'open'):
            state = 'approved'
        elif c.get('status') == 'closed':
            state = 'done'
        elif st in ('awaiting_response', 'changes_requested'):
            state = 'sent'
        elif num:
            state = 'draft'
        else:
            state = 'to_quote'
        counts[state] = counts.get(state, 0) + 1
        if show == 'open' and state not in ('to_quote', 'draft', 'sent', 'beatrice'):
            continue
        if show not in ('open', 'all') and state != show:
            continue
        hay = f"{d.get('vendor')} {d.get('client_name')} {d.get('site')} {d.get('doc_number')} #{d.get('doc_number')} " \
              f"{d.get('description')} {c.get('title')} {num} #{num}"
        if q and q not in hay.lower():
            continue
        out.append({'id': d['id'], 'date': d.get('doc_date') or (d.get('created_at') or '')[:10],
                    'vendor': d.get('vendor') or 'Wettech', 'number': d.get('doc_number') or '',
                    'client_name': d.get('client_name') or c.get('client_name') or '', 'site': d.get('site') or '',
                    'what': ((d.get('description') or '').strip().splitlines() or [''])[0][:200],
                    'subtotal': d.get('subtotal'), 'total': d.get('total'), 'file_name': d.get('file_name'),
                    'case_id': d.get('case_id'), 'case_title': c.get('title') or '', 'state': state,
                    'ours': {'number': num, 'status': st, 'uri': ours.get('uri') or dj.get('quote_uri') or ''}})
    _sort_docs(out, sort)
    return {'quotes': out, 'counts': counts}


def _sort_docs(rows, sort):
    """A-Z by site (the default), newest first, or by vendor."""
    if sort == 'new':
        rows.sort(key=lambda r: (r.get('date') or '', r['id']), reverse=True)
    elif sort == 'vendor':
        rows.sort(key=lambda r: ((r.get('vendor') or '').lower(), (r.get('client_name') or '').lower(), r.get('date') or ''))
    else:
        rows.sort(key=lambda r: ((r.get('client_name') or r.get('case_title') or '~').lower(), r.get('date') or ''))


def vendor_invoices(conn, show='all', q='', sort='az'):
    """Every vendor bill on file (Oct 2026: its own tab): the site, their
    invoice # and amount, our invoice to the client, and whether it's paid."""
    docs = [_doc_dict(r) for r in conn.execute(
        "SELECT * FROM pump_docs WHERE kind='bill' AND status != 'dismissed' ORDER BY id DESC")]
    ids = {d['case_id'] for d in docs if d.get('case_id')}
    cases = {r['id']: dict(r) for r in conn.execute(
        f"SELECT id, title, client_name, status, jobber, sei_invoice_number, vendor_paid_on, vendor_paid_by "
        f"FROM pump_cases WHERE id IN ({','.join('?' * len(ids))})", list(ids))} if ids else {}
    q = (q or '').strip().lower()
    out, counts = [], {}
    for d in docs:
        c = cases.get(d.get('case_id')) or {}
        dj, cj = d.get('jobber') or {}, json.loads(c.get('jobber') or '{}')
        inv = cj.get('invoice') or {}
        ours = inv.get('number') or dj.get('invoice_number') or c.get('sei_invoice_number') or ''
        if c.get('vendor_paid_on'):
            state = 'paid'
        elif c.get('status') == 'cancelled':
            state = 'cancelled'
        elif ours:
            state = 'invoiced'
        else:
            state = 'not_invoiced'
        counts[state] = counts.get(state, 0) + 1
        if show == 'unpaid' and state not in ('invoiced', 'not_invoiced'):
            continue
        if show not in ('all', 'unpaid') and state != show:
            continue
        hay = f"{d.get('vendor')} {d.get('client_name')} {d.get('site')} {d.get('doc_number')} #{d.get('doc_number')} " \
              f"{d.get('description')} {c.get('title')} {ours} #{ours}"
        if q and q not in hay.lower():
            continue
        out.append({'id': d['id'], 'date': d.get('doc_date') or (d.get('created_at') or '')[:10],
                    'vendor': d.get('vendor') or 'Wettech', 'number': d.get('doc_number') or '',
                    'client_name': d.get('client_name') or c.get('client_name') or '', 'site': d.get('site') or '',
                    'what': ((d.get('description') or '').strip().splitlines() or [''])[0][:200],
                    'subtotal': d.get('subtotal'), 'total': d.get('total'), 'case_id': d.get('case_id'),
                    'case_title': c.get('title') or '', 'state': state, 'paid_on': c.get('vendor_paid_on') or '',
                    'ours': {'number': ours, 'status': (inv.get('status') or dj.get('invoice_status') or '').lower(),
                             'uri': inv.get('uri') or dj.get('invoice_uri') or ''}})
    _sort_docs(out, sort)
    return {'invoices': out, 'counts': counts}


@api('/vendor_invoices')
def h_vendor_invoices(actor):
    """?show=all|unpaid|not_invoiced|invoiced|paid|cancelled&q=...&sort=az|new|vendor"""
    conn = _conn()
    try:
        return vendor_invoices(conn, request.args.get('show') or 'all', request.args.get('q') or '',
                               request.args.get('sort') or 'az')
    finally:
        conn.close()


@api('/vendor_quotes')
def h_vendor_quotes(actor):
    """?show=open|all|to_quote|draft|sent|approved|done|cancelled&q=..."""
    conn = _conn()
    try:
        return vendor_quotes(conn, request.args.get('show') or 'open', request.args.get('q') or '',
                             request.args.get('sort') or 'az')
    finally:
        conn.close()


@api('/reports')
def h_reports(actor):
    """Every service report, rebranded, by year: ?year=2026&q=..."""
    q = (request.args.get('q') or '').strip().lower()
    conn = _conn()
    try:
        docs = [_doc_dict(r) for r in conn.execute(
            "SELECT * FROM pump_docs WHERE kind='report' AND status != 'dismissed' ORDER BY id DESC")]
    finally:
        conn.close()
    years = sorted({_report_date(d)[:4] for d in docs if _report_date(d)}, reverse=True)
    year = request.args.get('year') or (years[0] if years else str(_today().year))
    out = []
    for d in docs:
        when = _report_date(d)
        if (when or '')[:4] != str(year):
            continue
        if q and q not in f"{d.get('client_name')} {d.get('site')} {d.get('file_name')}".lower():
            continue
        j = d.get('jobber') or {}
        out.append({'id': d['id'], 'date': when, 'site': d.get('client_name') or '', 'location': d.get('site') or '',
                    'title': (d.get('report_fields') or {}).get('title') or 'Report', 'file_name': d['file_name'],
                    'case_id': d.get('case_id'), 'has_branded': d['has_branded'],
                    'jobber': {'logged': bool(j.get('note_id')), 'title': j.get('note_title') or '',
                               'pending': (j.get('note_pending') or {}).get('reason', '')}})
    out.sort(key=lambda r: (r['date'] or '', r['site']), reverse=True)
    return {'year': str(year), 'years': years or [str(year)], 'reports': out}




# ═════════════════════════════════════════════════════════════════════════════
# Pipeline dashboard
# ═════════════════════════════════════════════════════════════════════════════
# Where every pump job is (quote -> approval -> scheduling -> work -> billing
# -> payment) and what's coming up week by week.

PIPELINE_STAGES = [
    ('quote', 'Quote', 'Wettech quoting, or our quote to send'),
    ('approval', 'Approval', 'Quote sent - waiting on the client'),
    ('scheduling', 'Scheduling', 'Approved - get it on Wettech\'s calendar'),
    ('work', 'Work', 'Scheduled - waiting for the work'),
    ('billing', 'Billing', "Wettech's bill, check it, draft our invoice, log the report"),
    ('payment', 'Payment', 'Invoice to send, client to pay, Wettech to pay'),
]
_STEP_TO_STAGE = {'vendor_quote': 'quote', 'client_quote': 'quote', 'client_approved': 'approval',
                  'scheduled': 'scheduling', 'work_done': 'work', 'vendor_bill': 'billing',
                  'bill_checked': 'billing', 'invoice_drafted': 'billing', 'report_logged': 'billing',
                  'closed': 'payment'}
# The Jobber record that fits each stage, best first.
_STAGE_JOBBER = {'quote': ('quote', 'request', 'job'), 'approval': ('quote', 'request', 'job'),
                 'scheduling': ('job', 'quote', 'request'), 'work': ('job', 'quote', 'request'),
                 'billing': ('invoice', 'job', 'quote'), 'payment': ('invoice', 'job', 'quote')}


def _jobber_link(case_jobber, stage):
    """(url, label) of the item's Jobber record for this stage, or ('', '')."""
    j = case_jobber if isinstance(case_jobber, dict) else {}
    for kind in _STAGE_JOBBER.get(stage, ('job', 'quote', 'invoice', 'request')):
        ref = j.get(kind) or {}
        if ref.get('uri'):
            return ref['uri'], f"{kind} #{ref['number']}" if ref.get('number') else kind
    return '', ''


UPCOMING_KINDS = [('maintenance', 'Maintenance'), ('repair', 'Repair / install'), ('scada', 'SCADA renewal'),
                  ('diver', 'Diver')]


def pipeline_data(conn, today=None):
    """The live pipeline: open items by stage, closed ones still waiting on
    money, and the next eight weeks of work."""
    today = today or _today()
    step_label = dict(STEPS)
    jobs = []
    for c in list_cases(conn, 'all'):
        if c['status'] == 'cancelled':
            continue
        pay = c['vendor_pay']
        if c['status'] == 'open':
            stage = _STEP_TO_STAGE.get(c['stage'])
            nxt = step_label.get(c['stage'], '').format(vendor=c.get('vendor') or 'Wettech')
        elif pay['state'] == 'due' or (pay['client_invoice_status'] and pay['client_invoice_status'] != 'paid'
                                       and pay['state'] == 'unpaid'):
            stage = 'payment'
            nxt = 'Pay Wettech' if pay['state'] == 'due' else 'Client to pay our invoice'
        else:
            continue
        if not stage:
            continue
        uri, label = _jobber_link(c['jobber'], stage)
        jobs.append({'id': c['id'], 'title': c['title'] or c['client_name'], 'client': c['client_name'],
                     'jobber_uri': uri, 'jobber_label': label,
                     'stage': stage, 'next': nxt, 'days': c['idle_days'], 'stuck': c['idle_days'] >= STALE_DAYS,
                     'amount': c.get('amount') or c.get('vendor_quote_amount') or c.get('vendor_quote_total') or 0,
                     'category': c['category']})
    end = today + timedelta(days=56)
    events = []
    for c in list_cases(conn, 'open'):
        when = _iso_date(c.get('scheduled_for'))
        if when and today.isoformat() <= when <= end.isoformat():
            events.append({'date': when, 'kind': 'maintenance' if c['category'] in ('maintenance', 'inspection')
                           else 'repair', 'title': c['title'] or c['client_name'], 'where': c.get('site') or '',
                           'jobber_uri': _jobber_link(c['jobber'], 'work')[0], 'case_id': c['id']})
    for s in scada_rows(conn):
        due = s.get('next_due_on') or ''
        if due and today.isoformat() <= due <= end.isoformat():
            events.append({'date': due, 'kind': 'scada', 'title': f"SCADA renewal - {s['client_name']}",
                           'where': s.get('site') or ''})
    m = today.replace(day=1)
    while m <= end:
        if m >= today.replace(day=1):
            n = len(sites_for_month(conn, m))
            if n:
                when = max(m, today)
                events.append({'date': when.isoformat(), 'kind': 'diver',
                               'title': f"Diver - {m.strftime('%B')} list ({n} sites)", 'where': ''})
        m = (m + timedelta(days=32)).replace(day=1)
    return _pipeline_shape(jobs, events, today, sample=False)


def _pipeline_shape(jobs, events, today, sample):
    stages = []
    for key, name, hint in PIPELINE_STAGES:
        js = sorted([j for j in jobs if j['stage'] == key], key=lambda j: -j['days'])
        stages.append({'key': key, 'name': name, 'hint': hint, 'count': len(js),
                       'stuck': sum(1 for j in js if j['stuck']), 'amount': round(sum(j['amount'] or 0 for j in js), 2),
                       'jobs': js})
    start = today - timedelta(days=today.weekday())
    weeks = []
    for w in range(8):
        a = start + timedelta(days=7 * w)
        b = a + timedelta(days=6)
        evs = sorted([e for e in events if a.isoformat() <= e['date'] <= b.isoformat()], key=lambda e: e['date'])
        weeks.append({'start': a.isoformat(), 'end': b.isoformat(), 'events': evs,
                      'counts': {k: sum(1 for e in evs if e['kind'] == k) for k, _ in UPCOMING_KINDS}})
    month_end = (today + timedelta(days=30)).isoformat()
    return {
        'sample': sample, 'today': today.isoformat(), 'stages': stages, 'weeks': weeks,
        'kinds': [{'key': k, 'name': n} for k, n in UPCOMING_KINDS],
        'kpis': {'open': len(jobs), 'stuck': sum(1 for j in jobs if j['stuck']),
                 'awaiting_approval': round(sum(j['amount'] or 0 for j in jobs if j['stage'] == 'approval'), 2),
                 'next_30_days': sum(1 for e in events if today.isoformat() <= e['date'] <= month_end)},
    }


def pipeline_sample(today=None):
    """MOCK DATA for judging the dashboard's layout - not real jobs.
    Delete this function and the "sample" switch once the office has seen it."""
    today = today or _today()
    d = lambda n: (today + timedelta(days=n)).isoformat()
    J = lambda i, t, c, st, nxt, days, amt, cat='repair', uri='', label='': {
        'id': -i, 'title': t, 'client': c, 'stage': st, 'next': nxt, 'days': days, 'stuck': days >= STALE_DAYS,
        'amount': amt, 'category': cat, 'jobber_uri': uri, 'jobber_label': label}
    jobs = [
        J(1, 'Replace check valve - Pump #2', 'Heron Bay', 'quote', 'Quote from Wettech', 3, 0),
        J(2, 'VFD fault - lift station', 'Lely CDD', 'quote', 'Quote sent to client', 9, 2480),
        J(3, 'Suction line repair', 'The Carlisle (Greenscapes)', 'approval', 'Client approved', 2, 1506.69,
          uri='https://secure.getjobber.com/quotes/66752875', label='quote #9136'),
        J(4, 'New float switch', 'Sanctuary at Blue Heron', 'approval', 'Client approved', 12, 640),
        J(5, 'Fountain motor', 'Morton Grove', 'approval', 'Client approved', 5, 3120),
        J(6, 'Pressure transducer', 'Pebblebrook HOA', 'scheduling', 'Scheduled with Wettech', 1, 890),
        J(7, 'Pump #1 rebuild', 'Spanish Wells (The Lake Club)', 'scheduling', 'Scheduled with Wettech', 8, 4650,
          uri='https://secure.getjobber.com/work_orders/41420018', label='job #1609'),
        J(8, 'Control panel replacement', 'Barrington Cove', 'work', 'Work done', 4, 5400),
        J(9, 'Quarterly maintenance', 'Tuscany Pointe Trail', 'work', 'Work done', 2, 550, 'maintenance'),
        J(10, 'Check valve install', 'Miromar Lakes', 'billing', "Bill from Wettech", 6, 1180),
        J(11, 'Butterfly valve', 'Sample Lakes', 'billing', 'Bill checked against quote', 10, 1921.06),
        J(12, 'Quarterly maintenance', 'Enclave at Palmira', 'billing', 'Report logged in Jobber', 1, 450,
          'maintenance'),
        J(13, 'Impeller replacement', 'Westminster HOA', 'payment', 'Client to pay our invoice', 15, 2760),
        J(14, 'Lift station repair', 'University Square CDD', 'payment', 'Pay Wettech', 3, 1340),
    ]
    events = [
        {'date': d(1), 'kind': 'maintenance', 'title': 'Quarterly pump - Spanish Wells (The Lake Club)', 'where': '4 pumps',
         'jobber_uri': 'https://secure.getjobber.com/work_orders/41420018'},
        {'date': d(2), 'kind': 'repair', 'title': 'Pressure transducer - Pebblebrook HOA', 'where': 'Station 2'},
        {'date': d(4), 'kind': 'maintenance', 'title': 'Quarterly pump - The Carlisle', 'where': 'Pump #1 exit'},
        {'date': d(6), 'kind': 'diver', 'title': 'Diver - 26 sites (Jordan)', 'where': ''},
        {'date': d(8), 'kind': 'maintenance', 'title': 'Quarterly pump - Barrington Cove', 'where': '2 stations'},
        {'date': d(9), 'kind': 'repair', 'title': 'Pump #1 rebuild - Spanish Wells', 'where': 'Pump #1'},
        {'date': d(11), 'kind': 'scada', 'title': 'SCADA renewal - Lely CDD', 'where': ''},
        {'date': d(13), 'kind': 'maintenance', 'title': 'Quarterly pump - Kurt Biggs', 'where': ''},
        {'date': d(15), 'kind': 'maintenance', 'title': 'Quarterly pump - Rosewood HOA', 'where': ''},
        {'date': d(16), 'kind': 'maintenance', 'title': 'Fountain quarterly - Miromar Lakes', 'where': ''},
        {'date': d(20), 'kind': 'repair', 'title': 'Control panel - Barrington Cove', 'where': 'North station'},
        {'date': d(22), 'kind': 'scada', 'title': 'SCADA renewal - Pebblebrook HOA', 'where': ''},
        {'date': d(24), 'kind': 'maintenance', 'title': 'Quarterly pump - Turn Leaf HOA', 'where': ''},
        {'date': d(27), 'kind': 'maintenance', 'title': 'Quarterly pump - Cypress Legends', 'where': ''},
        {'date': d(29), 'kind': 'maintenance', 'title': 'Quarterly pump - Pine Air Lakes', 'where': ''},
        {'date': d(33), 'kind': 'diver', 'title': 'Diver - next month (26 sites)', 'where': ''},
        {'date': d(35), 'kind': 'maintenance', 'title': 'Quarterly pump - Enclave at Palmira', 'where': ''},
        {'date': d(36), 'kind': 'maintenance', 'title': 'Quarterly pump - Water Crest', 'where': ''},
        {'date': d(41), 'kind': 'scada', 'title': 'SCADA renewal - Sapphire Lakes', 'where': ''},
        {'date': d(43), 'kind': 'repair', 'title': 'Float switch - Sanctuary at Blue Heron', 'where': ''},
        {'date': d(48), 'kind': 'maintenance', 'title': 'Quarterly pump - Escala at Quail West', 'where': ''},
        {'date': d(52), 'kind': 'maintenance', 'title': 'Quarterly pump - Diplomat RV', 'where': ''},
    ]
    return _pipeline_shape(jobs, events, today, sample=True)


@api('/pipeline')
def h_pipeline(actor):
    """?sample=1 for the mock example (until the office signs off on the layout)."""
    if request.args.get('sample') == '1':
        return pipeline_sample()
    conn = _conn()
    try:
        return pipeline_data(conn)
    finally:
        conn.close()




# ═════════════════════════════════════════════════════════════════════════════
# The office's account sheets: SCADA renewals, Wettech pump maintenance, and
# the lake/diver accounts (Oct 2026 versions loaded once; edited here after)
# ═════════════════════════════════════════════════════════════════════════════

Q = '1,4,7,10'   # JAN, APR, JULY, OCT

# SCADA: (client, renewal date, product, Wettech cost, our bill, vendor, {year: invoice # or note})
# "Renewal date" is when the next renewal is due (the office moves it on a
# year when they renew).
SEED_SCADA = [
    ('ALLURE', '2025-08-28', 'Annual Scada - Pump Station', 428.00, '$482.00', 'Wettech',
     {'2023': '16467', '2024': '22702', '2025': '29448'}),
    ('AUTUMN WOODS', '2026-03-13', 'Annual Inspection - SCADA', 428.00, '$600.00', 'Wettech',
     {'2023': 'SEI pays for SCADA', '2024': 'SEI pays for SCADA', '2025': 'SEI pays for SCADA'}),
    ('BANYAN BAY', '2026-03-08', 'Annual Inspection - SCADA', 428.00, '$600.00', 'Wettech',
     {'2023': '17360', '2024': '19716', '2025': '25695'}),
    ('Camas Willows 1', '2024-09-08', 'Annual Inspection - SCADA', 428.00, 'N/A - approved as part of our bid',
     'Wettech', {'2024': 'N/A - approved as part of our bid'}),
    ('CLUBCARE', '2024-03-15', 'Annual Inspection - SCADA', 428.00, '$600.00', 'Wettech',
     {'2023': '19732', '2024': '19732'}),
    ('COCONUT LANDING', '2023-04-30', 'Annual Inspection - SCADA', 428.00, '$600.00', 'Wettech',
     {'2023': 'n/a', '2024': '20122'}),
    ('COMMUNITY SCHOOL', '2023-12-01', 'Annual Scada - Pump Station', 428.00, '$600.00', 'Wettech',
     {'2023': '18014', '2024': '23773'}),
    ('CROSS CREEK', '2026-02-23', 'Annual Scada - Pump Station', 428.00, 'No charge', 'Wettech',
     {'2024': '19542', '2025': '26587'}),
    ('CORSA (formerly Estero Crossing)', '2023-11-20', 'Annual Scada - Pump Station', 428.00, '$600.00', 'Wettech',
     {'2024': '23788'}),
    ('FGCU-Athletics', '2023-07-03', 'Annual Subscription - SCADA', 428.00, '$500.00', 'Wettech',
     {'2023': '15283', '2024': '22704'}),
    ('FRUITVILLE COMMONS', '2026-02-28', 'Annual Subscription - SCADA', 428.00, '', 'Wettech',
     {'2024': '19617', '2025': '25844'}),
    ('LELY', '2023-01-09', 'Annual Subscription - SCADA', 428.00, '$600.00', 'Wettech', {'2024': '19236'}),
    ('OLD COLLIER', '2025-10-04', 'Annual Subscription - SCADA', 428.00, '$600.00', 'Wettech',
     {'2023': 'No charge', '2024': '23967'}),
    ('RESERVE AT ESTERO', '2026-03-13', 'Annual Inspection - SCADA', 428.00, '$600.00', 'Wettech',
     {'2023': 'Included in monthly'}),
    ('Tuscany Point', '2026-02-27', 'Annual Scada - Pump Station (2 pump stations)', 855.99, '$1,095.00', 'Wettech',
     {'2024': '20271', '2025': '26523'}),
    ('WildBlue', '2026-04-30', 'Annual Scada - Pump Station', 428.00, '$600.00', 'Wettech',
     {'2024': 'No charge - paid by us during ongoing project', '2025': 'No charge - paid by us during ongoing project'}),
]

# Wettech pump maintenance accounts:
# (name, kind, joined, equipment, location, months, Wettech $/visit, Naples Electric, our bill, notes, active)
SEED_MAINT = [
    ('Allura', 'Pump', '2022-04-01', '1 Pump, 1 Lake Filter', 'Veterans Memorial Blvd.', Q, '$125.00', '', '$320.00', '', 1),
    ("Anna's Place", 'Pump', '2016-11-01', '1 Lake 2 Filters', '5897 Ashford Ln', Q, '$75.00', '', 'N/A', '', 1),
    ('Autumn Woods', 'Pump', '2016-12-01', '2 Pumps', '6710 Goodlette Frank', Q, '$300.00', '', 'N/A', '', 1),
    ('Banyan Bay', 'Pump', '2025-04-24', '1 Pump, 1 Lake Filter',
     '8125 Banyan Breeze Way, Clubhouse, Fort Myers, FL 33908', Q, '$125.00', '', '$780.00', '', 1),
    ('Barrington Cove', 'Pump', '2024-08-19', '2 Pumps 2 Filters',
     'First pump station: west entrance of the parking area, next to 16164 Aberdeen. Second: north side of the '
     'property (north entrance), across from 16420 Aberdeen.', Q, '$250.00', '', '$600.00', '', 1),
    ('Carlisle (The Carlisle)', 'Pumps', '2022-04-23', '2 Pumps', '6945 Carlisle Ct. - Pump #1; 6495 Carlisle Ct. - Pump #2',
     Q, '$125.00', '', '$500.00', '', 1),
    ('Caymas', 'Both', '2024-09-24', '2 Pumps (lakes?)', '5684 Barbuda Lane', Q, '$250.00', '', '$3,706.25 for both', '', 1),
    ('Charlotte County - Sunshine Lake Park', 'Pump', '2017-01-01', '2 Pumps (1 inside, 1 outside)',
     '21125 McGuire Ave, Port Charlotte', '', '$150.00', '', '$300.00', 'Monthly', 1),
    ('Cypress Legends', 'Pump', '2019-10-01', '1 Pump, 1 Lake Filter', '3427 Forum Blvd., Ft. Myers, FL', Q, '$75.00', '',
     'N/A', '', 1),
    ('Diplomat', 'Both', '2025-04-11', '1 Pump, 1 Lake Filter', '2900 Diplomat Parkway E., Cape Coral, FL 33909', Q,
     '$150.00', '', '', '', 1),
    ('Pine Air Lakes - Edgemont Office Park', 'Pump', '2019-01-01', '1 Pump, 1 Lake 1 Filter', '5695 Naples Blvd, Naples, FL',
     Q, '$75.00', '', '$400.00', '', 1),
    ('Enclave @ Palmira', 'Pump', '2019-09-01', '2 Pumps, 2 Lakes 2 Filters', '28613 & 28653 San Lucas Lane, Bonita Springs',
     Q, '$100.00', '', 'N/A', '', 1),
    ('Escala @ Quail West', 'Pump', '2024-03-08', '1 Pump Station', '28892 Blaisdell Drive', Q, '$125.00', '', '$375.00', '', 1),
    ('Evergreen (Bradenton)', 'Pump', '2021-06-02', '1 Pump (monthly), 1 Lake (annually)',
     '3831 Turning Tides Terrace, Bradenton, FL 34201', '', '$100.00', '', 'N/A', 'Monthly', 1),
    ('FGCU - PGA Program', 'Pump', '2026-08-24', '1 Pump', '5820 Buckingham Road, Fort Myers, FL 33905', Q, '$150.00', '',
     '', '', 1),
    ('Falling Waters II - Watercrest', 'Pump', '2022-12-01', '1 Pump', '2300 Hidden Lakes Dr., Naples', Q, '$120.00', '',
     '$315.00', '', 1),
    ('Forum c/o LandQwest Commercial Property', 'Pump', '2024-06-17', '1 Pump',
     '3049 Forum Boulevard, NE side of Starbucks, Fort Myers, FL 33905', '1,7', '$125.00', '', '$475.00', '', 1),
    ('Hodges Funeral Home', 'Pump', '2021-10-01', 'Pump', '525 111th Avenue, Naples FL', '1,5,9', '$125.00', '',
     '$1,125.00', 'SiteOne, not Tom', 1),
    ('Honda Fort Myers', 'Pump', '2020-01-01', '1 Pump Station', '3550 Colonial Blvd, Fort Myers', Q, '$125.00', '', 'N/A',
     '', 1),
    ('Huntington Lakes Residence Assoc.', 'Pump', '2023-10-24', '10 Pumps, 1 Lake 1 Filter',
     '6585 Huntington Lakes Circle, Naples, FL', Q, '$1,000.00', '', '$3,500', '', 1),
    ('Lake Club (Spanish Wells)', 'Pumps', '2016-04-16', '3 Pump Stations (4 Pumps), 3 Lakes/6 Filters',
     '28409 High Gate Dr, Bonita Springs, FL', Q, '$200.00', '', '', '', 1),
    ('Lely CDD - Lely Pump Station', 'Pump', '2022-02-22', '1 Pump Station', '6815 Wildflower Way, Naples, FL 34113', Q,
     '$570.00', '', '$825.00', '', 1),
    ('Magnolia Cove at Falling Waters', 'Pump', '2022-07-12', '1 Pump', '2326 Magnolia Lane, Naples', Q, '$250.00', '',
     '$450.00', '', 1),
    ('Magnolia Falls at Falling Waters', 'Pump', '2023-02-01', '1 Pump, 4 Filters (behind the Magnolia Falls sign)',
     '2370 Magnolia Avenue, Naples, FL 34112', Q, '$150.00', '', '$450.00', '', 1),
    ('Miromar Lakes', 'Fountain', '2025-11-25', '3 Fountains', '17910 Ben Hill Griffin Pkwy, Miromar Lakes, FL 33913 (Chris Bevers)',
     Q, '$750.00', '', '', 'Dog: no', 1),
    ('Miromar Outlets', 'Pump', '2016-01-01', '1 Lake Fountain, 2 Pump Stations', '10801 Corkscrew Rd.', Q, '$75.00', '',
     'N/A', '', 1),
    ('Pebblebrook HOA', 'Both', '2023-11-17', '4 Pump Stations, 9 Lake Fountains', '8610 Pebblebrook Drive', Q,
     '$1,700.00', '', '$3,850 for both', '', 1),
    ('Quail Run', 'Pump', '2020-12-14', '1 Pump 60HP', '1 Forest Lakes Dr., Naples, FL 34105', '', '$100.00', '', '$135.00',
     'Monthly', 1),
    ('Rosewood HOA', 'Lake', '2026-07-13', '1 Lake', 'Left of 1655 Windy Pines Drive', Q, '$125.00', '', '$687.50', '', 1),
    ('Sanctuary @ Blue Heron', 'Pumps', '2016-01-01', '3 Lakes, 3 Pump Stations (Clubhouse, Sanctuary Dr., Sanctuary Circle)',
     '706 Haven Drive, Naples, FL', Q, '$100.00', '', '', '', 1),
    ('Sopra Luxury Living', 'Pump', '2025-04-01', '1 Pump 1 Lake', '3280 Champion Ring Road, Fort Myers, FL 33905', Q,
     '$125.00', '', '', 'Call the client to set up before each visit.', 1),
    ('St. Moritz HOA', 'Fountain', '2025-09-11', '1 Fountain', '10079 Saint Moritz Drive, Miromar Lakes, FL 33913', '2,9',
     '$400 twice a year', '', '', 'Semi-annual (September, February); sheet also says April/October.', 1),
    ('The Reserve @ Estero', 'Pumps', '2025-01-14', '1 Pump 1 Lake', '9350 La Bianco St, Estero, FL 33967', '1,7', '$350.00',
     '', '', '', 1),
    ('Turn Leaf', 'Pumps', '2026-06-30', '2 Pumps', '10600 Chevrolet Way suite 202, Estero, FL 33928', Q, '$500.00', '', '',
     '', 1),
    ('Tuscany Point Trail Association', 'Pump', '2022-04-29', '1 Lake, Pump', 'Tuscany Pointe Trl, Naples, FL 34120', Q,
     '$125.00', '', '$550.00', '', 1),
    ('University Square CDD', 'Pump', '2024-12-24', '3 Pumps and 2 Lakes', '10801 Corkscrew Road, Estero, FL', Q, '$350.00',
     '', '', '', 1),
    ('Warm Springs Comm. Assoc.', 'Pumps', '2023-08-23', '10 Pump Stations', '3813 Helsman Drive, Naples FL 34120', Q, '',
     '$250.00', '$475.00', 'Naples Electric does this.', 1),
    ('Watercrest @ Falling Waters', 'Pump', '2017-01-01', '2 Filters, pump at the rear of building 2300',
     '2326 Magnolia Lane, Naples', Q, '$75.00', '', '', '', 1),
    ('Wild Blue', 'Pump', '2026-03-17', '1 Pump', '8396 Sea Glass Court, Sarasota, FL 34240', Q, '$250.00', '', '', '', 1),
    # Former accounts (the sheet's bottom block; archived in Jobber)
    ('Bentley Village / Retreat at Bentley', 'Pump', '2018-01-01', '1 Lake 6 Filters, 1 Pump',
     'LR 602 Lake Louise Circle (The Retreat)', Q, '$100.00', '', 'N/A', '', 0),
    ('Carlton Lakes HOA III', 'Pumps', '2022-05-01', 'Pumps, 1 Lake, Filters',
     'Rear of 6104 Manchester Place, Naples, FL 34110 - gate code 2073', Q, '$125.00', '', '$320.00 for both', '', 0),
    ('Silverstone South @ Willow Hammock (Bradenton)', 'Pump', '2022-01-01', '2 Lakes, 1 Filter each lake',
     '4002 Willow Branch Place, Palmetto FL 34221', Q, '$200.00', '', '$525.00 quarterly', '', 0),
    ('Wilshire', 'Pump', '2016-12-01', '1 Pump', '9741 Wilshire Lake Blvd, Naples', Q, '$100.00', '', '', '', 0),
    ('Sapphire Lakes', 'Pumps', '2023-04-01', '8 Pump Stations', '8001 Radio Road, Naples, FL 34104', Q, '$600.00', '',
     '$1,200.00 (lake & pumps)', '', 0),
    ('Plantation Homes & Condos', 'Both', '2022-05-04', '1 Lake, 1 VFD Pump', '15077 Royal Fern Court, Naples, FL 34110', Q,
     '$125.00', '', '$550.00', '', 0),
    ('Boca Ciega', 'Pump', '2018-01-01', '1 Pump, 1 Lake 2 Filters', '2071-2099 Pine Isle Lane, Naples, FL', Q, '$100.00', '',
     'N/A', '', 0),
    ('Solera @ Lakewood Ranch', 'Pump', '2021-05-25', '2 Pump Stations (#1 & 2) monthly, lake annually',
     '16812 Harvest Moon Way, Lakewood Ranch, FL 34211', '', '$100.00', '', '$250.00 for both lake & filter', 'Monthly', 0),
    ('Horse Creek', 'Pump', '2016-12-01', '1 Pump', '331 Saddlebrook Lane, Naples, FL', Q, '$75.00', '', 'N/A', '', 0),
    ('Fruitville Commons', 'Pump', '2023-11-10', 'Pump', '3130 Fruitville Commons Boulevard, Sarasota FL', Q, '$125.00', '',
     '$595.00', '', 0),
    ('Abaco Bay', 'Pump', '2025-06-17', '1 Pump, 1 Lake 1 Filter', '14759 Kingfisher Loop (pump location: left)', Q,
     '$200.00', '', '$500.00', '', 0),
    ('Heritage Stations c/o Wilmington Land Company', 'Pump', '2024-10-02', '1 Pump',
     '15351 Burnt Store Road, Punta Gorda, FL 33955', Q, '$250.00', '', 'Included with irrigation maintenance', '', 0),
    ('Liberty Shores', 'Pump', '2025-04-16', '1 Pump Station', '904 Admiral Bull Halsey Avenue, LGI Homes, LaBelle, FL 33935',
     Q, '$250.00', '', '', '', 0),
]
MAINT_MONTHLY = {'Charlotte County - Sunshine Lake Park', 'Evergreen (Bradenton)', 'Quail Run', 'Solera @ Lakewood Ranch'}

# Lake / diver accounts (Gulfshore Yacht Service - Jordan):
# (name as on the diver list, kind, joined, equipment, location, months, diver $, our bill, Naples Electric,
#  diver notes, needs the diver, active)
SEED_LAKES = [
    ("Anna's Place", 'Lake', '2016-11-01', '1 Lake 2 Filters', '5897 Ashford Ln', Q, '$125.00', '$400.00', '', None, 1, 1),
    ('Autumn Woods', 'Lake', '2016-01-01', '1 Lake 2 Filters', '6710 Goodlette Frank Rd.', Q, '$125.00', 'N/A', '', None, 1, 1),
    ('Banyan Bay', 'Lake', '2025-05-01', '1 Pump 1 Lake 1 Filter', None, Q, '$125.00', '$780 for both', '', None, 1, 1),
    ('Barrington Cove', 'Both', '2024-08-19', '2 Pumps 2 Filters', None, Q, '$175.00', '$600.00', '', None, 1, 1),
    ('Carlisle (The Carlisle)', 'Both', '2022-04-23', '2 Lakes 3 Filters', None, Q, '$175.00', '$500.00', '', None, 1, 1),
    ('Caymas', 'Both', '2024-09-24', '2 Pumps 2 Lakes', None, Q, '$125.00', '$3,706.25 for both', '', None, 1, 1),
    ('Cypress Legends (Behind Clubhouse)', 'Lake', '2019-10-01', '1 Pump 1 Lake Filter', None, Q, '$125.00', '$500.00', '',
     None, 1, 1),
    ('Clubside', 'Lake', '', '5 Pumps 2 Lakes', '5862 3 Iron Drive', '1', '', '', '', 'January only.', 1, 1),
    ('Diplomat RV', 'Lake', '2025-05-01', '1 Pump 1 Lake Filter', '2900 Diplomat Parkway E., Cape Coral, FL 33909', Q,
     '$175.00', '', '', 'Sheet marks it "January".', 1, 1),
    ('Edgemont Office Park (Pine Air Lakes)', 'Lake', '2019-01-01', '1 Pump 1 Lake 1 Filter', None, Q, '$125.00', '$400.00', '',
     None, 1, 1),
    ('Enclave @ Palmira', 'Lake', '2019-09-01', '2 Lakes 4 Filters', None, Q, '$175.00', '$450.00', '', None, 1, 1),
    ('Evergreen (Bradenton)', 'Lake', '2021-06-02', '2 Pumps 2 Lakes', '3831 Turning Tides Terrace, Bradenton, FL 34201', '1',
     '$350.00', '$250.00 for lake & pump', '',
     'January only. North pump is in Evergreen Estates - the first pump on the left when you drive in.', 1, 1),
    ('Falling Waters II', 'Lake', '2016-12-01', '1 Lake 3 Filters', None, Q, '$125.00', '$315.00', '', None, 1, 1),
    ('Huntington Lakes Residence Assoc.', 'Lake', '2023-10-24', '10 Pumps 1 Lake 1 Filter', None, Q, '$575.00',
     '$3,500 with maintenance', '', None, 1, 1),
    ('Kurt Biggs', 'Lake', '2026-02-16', '1 Lake 1 Filter', None, Q, '', '', '', None, 1, 1),
    ('Magnolia Cove at Falling Waters', 'Lake', '2022-07-12', '1 Pump 1 Lake Filter', None, Q, '$125.00', '$450.00', '', None, 1, 1),
    ('Magnolia Falls at Falling Waters', 'Pump', '2023-02-01', '1 Pump 4 Filters', None, Q, '$125.00', '$450.00', '', None, 1, 1),
    ('Miromar Outlets', 'Lake', '2016-01-01', '1 Lake Fountain (2 Filters)', None, Q, '$200.00 (lake filter)',
     '$980.00 with maintenance', '', None, 1, 1),
    ('Morton Grove', 'Lake', '2026-08-05', '1 Lake Fountain', None, Q, '$125.00', '$250.00', '', None, 1, 1),
    ('Pebblebrook HOA', 'Both', '2023-11-17', '4 Pump Stations 9 Lake Fountains', None, Q, '$275.00', '$3,850 for both', '',
     None, 1, 1),
    ('Riviera Golf Estates 2', 'Lake', '2022-01-01', '1 Lake 1 Filter', '351 Charlemagne Blvd, Naples', '4,10', '$125.00',
     '$200.00', '', 'April and October.', 1, 1),
    ('Rosewood HOA', 'Lake', '2026-07-13', '1 Lake', None, Q, '$125.00', '$687.50', '', None, 1, 1),
    ('Sanctuary @ Blue Heron', 'Lake', '2016-01-01', '3 Lakes 9 Filters 3 Pump Stations', None, Q, '$225.00', '$490.00', '',
     None, 1, 1),
    ('Spanish Wells Lake Club', 'Lake', '2016-04-16', '3 Lakes 6 Filters 3 Pump Stations (4 Pumps)', None, Q, '$225.00',
     '$850.00', '', None, 1, 1),
    ('Sopra Luxury Living', 'Pump', '2025-04-01', '1 Pump 1 Lake', None, Q, '$125.00', '', '', None, 1, 1),
    ('The Reserve @ Estero', 'Both', '2025-01-14', '1 Pump 1 Lake', '9350 La Bianco St, Estero, FL 33967', '1,7', '$125.00',
     'Approx. $125.00', '', 'January and July.', 1, 1),
    ('Tuscany Point Trail Association', 'Both', '2022-04-29', '1 Lake', None, Q, '$125.00', '$550.00', '', None, 1, 1),
    ('University Square CDD', 'Both', '2024-12-06', '1 Pump 1 Filter', None, Q, '$125.00', '', '', None, 1, 1),
    ('Warm Springs Comm. Assoc.', 'Both', '2023-08-23', 'Lake', '3813 Helsman Drive, Naples FL 34120', '10', '', '$450.00',
     '$450.00', 'October only - Naples Electric does this, not the diver.', 0, 1),
    ('Watercrest @ Falling Waters', 'Both', '2017-01-01', '1 Lake 1 Filter', None, Q, '$125.00', '', '', None, 1, 1),
    ('Westminster HOA', 'Lake', '2016-12-01', '4 Lakes 9 Filters', None, Q, '$325.00', 'Included in m/m $780', '', None, 1, 1),
    ('Wild Blue', 'Pump', '2026-03-17', '1 Pump 1 Lake', None, Q, '', '', '', 'No diving - Wettech only (master list).', 0, 1),
    # Former accounts (yellow on the sheet)
    ('Bentley Village', 'Lake', '2018-01-01', '1 Lake 6 Filters', 'LR 602 Lake Louise Circle (The Retreat)', Q, '$145.00',
     '$500.00', '', '', 1, 0),
    ('Carlton Lakes HOA III', 'Both', '2022-05-01', 'Pumps, 1 Lake, Filters',
     'Rear of 6104 Manchester Place, Naples, FL 34110', Q, '$125.00', '$320.00', '', 'Gate code 2073', 1, 0),
    ('Silverstone South @ Willow Hammock (Bradenton)', 'Lake', '2022-01-01', '2 Lakes, 1 Filter each lake',
     '4002 Willow Branch Place, Palmetto FL 34221', '1', '$400.00', 'Combined with pump', '', 'January only.', 1, 0),
    ('Sapphire Lakes', 'Pumps', '2023-04-01', '4 Lakes 8 Filters', '8001 Radio Road, Naples, FL 34104', Q, '$475.00',
     '$1,200.00 (lake & pump)', '', '', 1, 0),
    ('Plantation Homes & Condos - Storrington', 'Lake', '2022-05-04', '1 Lake 3 Filters',
     '15077 Royal Fern Court, Naples, FL 34110', Q, '$375.00', 'Combined with pump', '', '', 1, 0),
    ('Boca Ciega', 'Lake', '2018-01-01', '1 Pump 1 Lake 2 Filters', '2071-2099 Pine Isle Lane, Naples, FL', Q, '$150.00',
     '$400.00', '', '', 1, 0),
    ('VeronaWalk HOA', 'Lake', '2022-04-13', '3 Fountains', '8090 Sorrento Lane, Suite 1, Naples, FL 34114', Q, '$300.00',
     '$1,440.00', '', '', 1, 0),
    ('Solera @ Lakewood Ranch', 'Lake', '2021-05-25', '1 Lake (alligator)', '16812 Harvest Moon Way, Lakewood Ranch, FL 34211',
     '4', '$100.00', '$250.00', '', 'April only.', 1, 0),
    ('Horse Creek', 'Lake', '2016-12-01', '1 Lake 2 Filters', '331 Saddlebrook Lane, Naples, FL', Q, '$125.00', '$525.00', '',
     '', 1, 0),
    ('Riviera Golf Estates 1', 'Lake', '2022-01-01', '1 Lake 1 Filter', '325 Charlemagne Blvd., Naples', '1,7', '$125.00',
     '$100.00', '', 'January and July.', 1, 0),
    ('Heritage Stations c/o Wilmington Land Company', 'Lake', '2024-10-02', '1 Pump 1 Lake Filter',
     '15351 Burnt Store Road, Punta Gorda, FL 33955', '1', '$175.00', 'Included with irrigation maintenance', '',
     'January only.', 1, 0),
    ('Liberty Shores', 'Lake', '2025-05-01', '1 Pump, lake filters?', '904 Admiral Bull Halsey Avenue, LGI Homes, LaBelle, FL 33935',
     Q, '$250.00?', '', '', '', 1, 0),
]


# Contacts and billing instructions from the office's master list (Oct 7
# 2026), by the account's name here. Pump accounts' notes; the lake-only ones
# go on the diver list.
MASTER_LIST_NOTES = [
    ('maint', 'Autumn Woods', 'After Wettech, the contact for any pump issues is Oscar.'),
    ('maint', 'Banyan Bay', 'Account contact: Stephanie Kolenut, sakmgmt@gmail.com.'),
    ('maint', 'Barrington Cove', 'Account contact: John Rodrigues, 239-354-7367. Invoices only to Paramount accounts '
                                 'payable (accountspayable@paramount...); quotes only to John Rodriguez. Billing: pump '
                                 '$600, recharge wells $325, fountains $650.'),
    ('maint', 'Carlisle (The Carlisle)', 'Account contact: Christine Keller, ckeller@greenscapesfl.com (Greenscapes).'),
    ('maint', 'Caymas', 'Account contact: Irene Blandon, (239) 529-9021. Add the pump report to the account; Beatriz '
                        'bills it with the water meter reading. SCADA is included in the quarterly invoice.'),
    ('maint', 'Charlotte County - Sunshine Lake Park', 'Account contact: Karen Bliss, 941-575-3642. Needs a new PO every '
                                                       'year, added to the job before billing (set for Sept 2026-2027).'),
    ('maint', 'Cypress Legends', 'Account contact: Bridget Wooten, 239-693-2700, bwooten@northland.com.'),
    ('maint', 'Diplomat', 'Account contact: Tim, 239-458-2200. Owner: Beverly, 239-292-2163.'),
    ('maint', 'Pine Air Lakes - Edgemont Office Park', 'Send all invoices to jpadilla@gmssf.com, jwasserman@gmscfl.com '
                                                       'and agill@gmssf.com. Quotes to jpadilla@gmssf.com.'),
    ('maint', 'Enclave @ Palmira', 'Account contact: brenna.mcdowell@fsresidential.com.'),
    ('maint', 'Evergreen (Bradenton)', "Attach the report in Jobber but don't send the pump report - only report the "
                                       'gallons used for the north and south pumps.'),
    ('maint', 'Hodges Funeral Home', 'SiteOne does the pump maintenance 3 times a year; ask PSochar@siteone.com (backup '
                                     'desposito@siteone.com) for the report.'),
    ('maint', 'Honda Fort Myers', 'Account contact: Mike Naegele, mnaegele@hondaoffortmyers.com, 215-783-5304.'),
    ('maint', 'Huntington Lakes Residence Assoc.', 'Account contact: Michael, 973-615-1427.'),
    ('maint', 'Magnolia Falls at Falling Waters', 'Always cc Carol Connolly on invoices and quotes: '
                                                  'carolconnolly48@gmail.com, 262-617-8255.'),
    ('maint', 'Miromar Outlets', 'Account contact: Jeff Staner, 239-287-1050. Let them know before making pump repairs '
                                 'over $500.'),
    ('maint', 'Pebblebrook HOA', 'Account contact: Nancy Phillips, contractors@newellpropertymanagement.com.'),
    ('maint', 'Rosewood HOA', 'Account contact: George Anderson, 708-514-2091, ganderson47@att.net.'),
    ('maint', 'Sopra Luxury Living', 'Email Lauren (lmleczek@davisdevelopment.com) before each quarterly visit for '
                                     'approval.'),
    ('maint', 'The Reserve @ Estero', 'Contact besides Wettech: Oscar.'),
    ('maint', 'Warm Springs Comm. Assoc.', 'Naples Electric: Paul Jukins, 777-0797, paul@nemwinc.com. Reports: '
                                           'jenna@nemwinc.com.'),
    ('dive', 'Kurt Biggs', 'Ramon to be there with the diver; Jordan calls to coordinate when he is going out.'),
    ('dive', 'Clubside', 'Jordan dives once a year, in January only. Our technicians Jimmie/Ramon keep an eye on the '
                         'pump.'),
]
# SCADA renewals on the master workbook (Oct 7 2026) that weren't on the first
# sheet. The two FGCU stations are marked "?" there with no invoice since 2023,
# so they come in switched off. (Its "Heritage Station - Charlotte County" is
# the Heritage Stations account already found from Jobber's invoices; the
# sheet only adds its 2023 and 2024 invoice numbers.)
MASTER_LIST_SCADA = [
    ('FGCU Intermural Pump Station', '2022-08-17', 'Annual Inspection - SCADA', 426.00, '$600.00', 'Wettech',
     {'2023': '15286'}, 0, 'Marked "?" on the Oct 2026 sheet - no invoice since 2023.'),
    ('FGCU Library - Broadcast - Athletics', '2022-05-02', 'Annual Inspection - SCADA', 428.00, '$500.00', 'Wettech',
     {'2023': '14107'}, 0, 'Marked "?" on the Oct 2026 sheet - no invoice since 2023.'),
]


def _apply_master_list(c, now):
    """Once: the master list's contacts onto the accounts, and its SCADA
    renewals the app didn't have. Claimed first so only one worker runs it."""
    c.execute("INSERT OR IGNORE INTO pump_state (key, value) VALUES ('master_list_oct7', ?)", (json.dumps(now),))
    if c.rowcount != 1:
        return
    for table, name, text in MASTER_LIST_NOTES:
        tbl, col = ('pump_maint_accounts', 'notes') if table == 'maint' else ('pump_dive_sites', 'diver_notes')
        row = c.execute(f'SELECT id, {col} FROM {tbl} WHERE name=?', (name,)).fetchone()
        if not row or text in (row[1] or ''):
            continue
        c.execute(f'UPDATE {tbl} SET {col}=?, updated_by=?, updated_at=? WHERE id=?',
                  (((row[1] or '').strip() + '\n' + text).strip(), 'Master list (Oct 7 2026)', now, row[0]))
    row = c.execute("SELECT id, years FROM pump_scada_accounts WHERE client='Heritage Stations'").fetchone()
    if row:
        years = json.loads(row[1] or '{}')
        for y, inv in (('2023', '18456'), ('2024', '23846')):
            if not str(years.get(y) or '').strip():
                years[y] = inv
        c.execute('UPDATE pump_scada_accounts SET years=? WHERE id=?', (json.dumps(years), row[0]))
    for client, due, product, cost, bill, vendor, years, active, notes in MASTER_LIST_SCADA:
        if c.execute('SELECT 1 FROM pump_scada_accounts WHERE client=?', (client,)).fetchone():
            continue
        c.execute('''INSERT INTO pump_scada_accounts (client, renewal_date, product, vendor_cost, our_bill, vendor,
                       years, active, notes, updated_by, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                  (client, due, product, cost, bill, vendor, json.dumps(years), active, notes,
                   'Master list (Oct 7 2026)', now))


def _apply_master_vendors(c, now):
    """Once (Oct 13 2026): the office's master list ("Gulfshore Yacht Service /
    Wet Tech") has Gulfshore N/A at Wild Blue - Wettech does the pump, no diver.
    It had been on the lake sheet with Wettech's $250, so Jordan was being asked."""
    c.execute("INSERT OR IGNORE INTO pump_state (key, value) VALUES ('master_vendors_oct26', ?)", (json.dumps(now),))
    if c.rowcount != 1:
        return
    c.execute("UPDATE pump_dive_sites SET needs_dive=0, diver_cost='', diver_notes=TRIM(COALESCE(diver_notes, '') || "
              "' No diving - Wettech only (master list).'), updated_by='Master list (Oct 13 2026)', updated_at=? "
              "WHERE name='Wild Blue'", (now,))


REPORT_ONLY_ACCOUNTS = ('Autumn Woods', 'The Reserve @ Estero', 'Wild Blue')
# Sites whose Wettech quotes go straight to Beatriz (the office, Oct 2026):
# never tracked here - no item, no Jobber quote, just "Send Wettech quote to Beatriz".
BEATRICE_SITES = ('Wild Blue', 'Autumn Woods')
BEATRICE = 'Beatriz'


def beatrice_site(*texts):
    """The Beatriz site a document or Jobber record is for, or ''."""
    hay = ' '.join(t or '' for t in texts)
    return next((s for s in BEATRICE_SITES if fuzzy_has(s, hay)), '')


def quote_to_beatrice(conn, doc, actor):
    """A vendor quote for a Beatriz site: a to-do to send it to her, and nothing tracked."""
    site = beatrice_site(doc.get('client_name'), doc.get('site'))
    num = f" #{doc['doc_number']}" if doc.get('doc_number') else ''
    price = doc.get('subtotal') if doc.get('subtotal') is not None else doc.get('total')
    add_todo(conn, f"beatrice:{doc['id']}",
             f"Send {doc.get('vendor') or 'Wettech'} quote{num} to {BEATRICE} - {doc.get('client_name') or site}",
             ' · '.join(x for x in (((doc.get('description') or '').strip().splitlines() or [''])[0][:300],
                                     money_text(price) if price is not None else '',
                                     f"{site} quotes go to {BEATRICE} - not tracked here") if x),
             {'uri': f"/pumps/api/docs/{doc['id']}/file", 'label': 'Open the quote'})
    conn.execute("UPDATE pump_docs SET status='done', updated_at=? WHERE id=?", (_now_text(), doc['id']))
    _event(conn, actor, 'quote for Beatriz', f"{doc.get('file_name')} - {site} quotes go to {BEATRICE}",
           doc_id=doc['id'])
    return None


# The 2026 Monthly Billing Checklist, as scanned (Oct 2026): account, line,
# monthly amount (None = TBD, billed as used), how often, status, months ticked.
CONTRACT_CHECKLIST_2026 = [
    ('Amberly Village', 'Monthly maintenance', 500.00, 'monthly', 'active', [1, 2, 3, 6]),
    ('Amberly Village', 'Parts', None, 'as used', 'active', []),
    ('Autumn Woods', 'Monthly maintenance', 3605.00, 'monthly', 'active', [1, 2, 3, 4, 6]),
    ('Autumn Woods', 'Parts', None, 'as used', 'active', [4, 6]),
    ('Barefoot Beach', 'Monthly maintenance', 1600.00, 'monthly', 'cancelled', []),
    ('Clubside at the Strand', 'Monthly maintenance', 850.00, 'monthly', 'active', [1, 2, 3, 6]),
    ('Center Links', 'Monthly maintenance', 495.00, 'monthly', 'active', [6]),
    ('Germain Toyota', 'Monthly maintenance', 500.00, 'monthly', 'active', [6]),
    ('Germain Lincoln', 'Monthly maintenance', 300.00, 'monthly', 'active', [6]),
    ('Green Tree', 'Monthly maintenance', 750.00, 'monthly', 'active', [1, 2, 3, 6]),
    ('Hemingway', 'Monthly maintenance', 1200.00, 'monthly', 'active', [1, 2, 3, 6]),
    ('Heritage Stations', 'Monthly maintenance', 1080.00, 'monthly', 'cancelled', []),
    ('Heron Glen', 'Bi-monthly maintenance', 510.00, 'bi-monthly', 'active', []),
    ('Hodges Funeral Home', 'Quarterly maintenance', 3252.00, 'quarterly', 'active', [1]),
    ('Huntington Lakes #3', 'Monthly maintenance', 400.00, 'monthly', 'active', [6]),
    ('Huntington Lakes #5', 'Monthly maintenance', 400.00, 'monthly', 'active', [4, 6]),
    ('Huntington Lakes Master', 'Monthly maintenance', 1850.00, 'monthly', 'active', [1, 2, 3, 6]),
    ('Isle Verde', 'Monthly maintenance', 680.00, 'monthly', 'active', [6]),
    ('Miromar Design', 'Monthly maintenance', 175.00, 'monthly', 'active', [1, 2, 3, 6]),
    ('Miromar Outlets', 'Monthly maintenance', 950.00, 'monthly', 'active', [6]),
    ('Miromar Outlets', 'Koi pond', 127.00, 'monthly', 'active', [1, 2, 3, 4, 6]),
    ('Morton Grove', 'Monthly maintenance ($575)', 575.00, 'monthly', 'active', [1, 2, 6]),
    ('Morton Grove', 'Monthly maintenance ($150)', 150.00, 'monthly', 'active', [1, 2, 3, 6]),
    ('Pine Air Lakes', 'Irrigation', 600.00, 'monthly', 'active', [1, 2, 3, 4, 6]),
    ('Pine Air Lakes', 'Landscape', 4708.33, 'monthly', 'active', [1, 2, 3, 4, 6]),
    ('Pine Air Lakes', 'Trash', 250.00, 'monthly', 'active', [1, 2, 3, 4, 6]),
    ('Pinnacle at the Strand', 'Monthly maintenance', 600.00, 'monthly', 'active', [6]),
    ('Raymond Lutgert', 'Monthly maintenance', 350.00, 'monthly', 'active', [4, 6]),
    ('The Lake Club', 'Monthly maintenance', 1950.00, 'monthly', 'active', [1, 2, 3, 4, 6]),
    ('The Lake Club', 'Parts', None, 'as used', 'active', [1, 2, 3, 4, 6]),
    ('The Reserve @ Estero', 'Monthly maintenance', 6920.83, 'monthly', 'active', [1, 2, 3, 4, 6]),
    ('The Reserve @ Estero', 'Parts', None, 'as used', 'active', [1, 2, 3, 4, 6]),
    ('Tuscany Point', 'Monthly maintenance', 2100.00, 'monthly', 'active', [1, 2, 3, 6]),
    ('Tuscany Point', 'Parts', None, 'as used', 'active', [1, 2, 3, 6]),
    ('University Village Shops, LLC', 'Monthly maintenance', 324.00, 'monthly', 'active', [4, 6]),
    ('Verona Walk', 'Common', 4560.00, 'monthly', 'active', [6]),
    ('Verona Walk', 'Residential', 6840.00, 'monthly', 'active', [6]),
    ('Westminster', 'Monthly maintenance', 980.00, 'monthly', 'active', [1, 2, 3, 6]),
]
# Contract lines that aren't the irrigation itself.
_NOT_IRRIGATION_LINE = re.compile(r'\b(?:parts|landscape|land|trash|koi)\b', re.I)


def _seed_contracts(c, now):
    """Once (Oct 19 2026): the 2026 Monthly Billing Checklist the office scanned."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pump_contracts'").fetchone():
        return
    c.execute("INSERT OR IGNORE INTO pump_state (key, value) VALUES ('contracts_checklist_2026', ?)", (json.dumps(now),))
    if c.rowcount != 1:
        return
    for account, line, amount, freq, status, months in CONTRACT_CHECKLIST_2026:
        c.execute('INSERT INTO pump_contracts (account, line, amount, frequency, status, billed, notes, updated_by, '
                  'updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
                  (account, line, amount, freq, status, json.dumps({'2026': months}),
                   'From the 2026 Monthly Billing Checklist (scanned Oct 2026)', 'Pumps', now))


def contract_dict(r, today=None):
    """A contract line with where its billing stands this year: the months billed
    and, for a monthly one, the months before this one that weren't."""
    today = today or _today()
    d = dict(r)
    billed = json.loads(d.get('billed') or '{}')
    year = str(today.year)
    d['year'] = year
    d['months'] = sorted(int(m) for m in billed.get(year, []))
    d['unbilled'] = [m for m in range(1, today.month) if m not in d['months']] \
        if d['status'] == 'active' and d['frequency'] == 'monthly' else []
    d['irrigation'] = not _NOT_IRRIGATION_LINE.search(d.get('line') or '')
    return d


def _spell_beatriz(c, now):
    """Once (Oct 19 2026): it's Beatriz, not Beatrice - the to-dos already made say so too."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pump_todos'").fetchone():
        return
    c.execute("INSERT OR IGNORE INTO pump_state (key, value) VALUES ('beatriz_spelling_oct26', ?)", (json.dumps(now),))
    if c.rowcount != 1:
        return
    c.execute("UPDATE pump_todos SET title=REPLACE(title, 'Beatrice', 'Beatriz'), "
              "detail=REPLACE(detail, 'Beatrice', 'Beatriz') WHERE key LIKE 'beatrice:%'")


def _paid_once_emailed(c, now):
    """Once (Oct 19 2026, the office): every bill already emailed to Christian is
    paid - dated the day it was emailed - and goes to Old vendor bills."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pump_cases'").fetchone():
        return
    c.execute("INSERT OR IGNORE INTO pump_state (key, value) VALUES ('paid_once_emailed_oct26', ?)", (json.dumps(now),))
    if c.rowcount != 1:
        return
    for key, value in c.execute("SELECT key, value FROM pump_state WHERE key LIKE 'pay_email:%'").fetchall():
        try:
            rec, cid = json.loads(value or '{}'), int(key.split(':', 1)[1])
        except (ValueError, TypeError):
            continue
        if not isinstance(rec, dict) or not rec.get('sent'):
            continue
        c.execute("UPDATE pump_cases SET vendor_paid_on=?, vendor_paid_by=?, updated_at=? "
                  "WHERE id=? AND COALESCE(vendor_paid_on, '')=''",
                  ((rec.get('at') or now)[:10], rec.get('by') or 'Pumps', _now_text(), cid))
        if c.rowcount:
            c.execute('INSERT INTO pump_events (case_id, doc_id, at, actor, action, detail) VALUES (?,?,?,?,?,?)',
                      (cid, None, _now_text(), 'Pumps', 'vendor paid',
                       f"Emailed to Christian {(rec.get('at') or '')[:10]} - marked paid"))


def _drop_irrigation_quotes(c, now):
    """Once (Oct 19 2026, the office): items the sync made from a Jobber quote that is
    irrigation field work, not pumps (The Reserve @ Estero #8443, valve boxes and
    a gate valve): cancelled, the quote ignored, its to-do done."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pump_jobber_items'").fetchone():
        return
    c.execute("INSERT OR IGNORE INTO pump_state (key, value) VALUES ('drop_irrigation_quotes_oct26', ?)", (json.dumps(now),))
    if c.rowcount != 1:
        return
    for jid, cid, title in c.execute(
            "SELECT i.jobber_id, i.case_id, COALESCE(i.title, '') FROM pump_jobber_items i "
            "JOIN pump_cases p ON p.id = i.case_id WHERE i.kind='quote' AND p.status='open' "
            "AND NOT EXISTS (SELECT 1 FROM pump_docs d WHERE d.case_id = p.id AND d.status != 'dismissed')").fetchall():
        if not _IRRIGATION_ONLY.search(title) or TITLE_PATTERNS['pump'].search(title) or _PUMP_HINTS.search(title) \
                or _VENDOR_WORDS.search(title):
            continue
        c.execute("UPDATE pump_cases SET status='cancelled', stage='cancelled', updated_at=? WHERE id=?", (_now_text(), cid))
        c.execute('UPDATE pump_jobber_items SET case_id=NULL, ignored=1 WHERE jobber_id=?', (jid,))
        c.execute("UPDATE pump_todos SET done_at=?, done_by='Pumps' WHERE key LIKE ? AND done_at IS NULL",
                  (_now_text(), f'%:{cid}'))
        c.execute('INSERT INTO pump_events (case_id, doc_id, at, actor, action, detail) VALUES (?,?,?,?,?,?)',
                  (cid, None, _now_text(), 'Pumps', 'cancelled', f'"{title}" is irrigation work, not pumps - not followed'))


def _stop_tracking_beatrice(c, now):
    """Once (Oct 16 2026): items already open for a Beatriz site that only wait
    on a quote are closed - those quotes go to Beatriz."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pump_cases'").fetchone():
        return
    c.execute("INSERT OR IGNORE INTO pump_state (key, value) VALUES ('beatrice_untrack_oct26', ?)", (json.dumps(now),))
    if c.rowcount != 1:
        return
    for cid, title, client, site in c.execute(
            "SELECT id, title, client_name, site FROM pump_cases WHERE status='open' "
            "AND stage IN ('assessment', 'vendor_quote', 'client_quote', 'client_approved')").fetchall():
        where = beatrice_site(client, site, title)
        if where:
            c.execute("UPDATE pump_cases SET status='cancelled', stage='cancelled', updated_at=? WHERE id=?",
                      (_now_text(), cid))
            c.execute('INSERT INTO pump_events (case_id, doc_id, at, actor, action, detail) VALUES (?,?,?,?,?,?)',
                      (cid, None, _now_text(), 'Pumps', 'cancelled', f'{where} quotes go to {BEATRICE} - not tracked'))


def _apply_report_only(c, now):
    """Once (Oct 15 2026, the office): Autumn Woods, The Reserve @ Estero and
    Wild Blue get no pump maintenance invoice - only the report logged in Jobber."""
    c.execute("INSERT OR IGNORE INTO pump_state (key, value) VALUES ('report_only_oct26', ?)", (json.dumps(now),))
    if c.rowcount != 1:
        return
    c.execute(f"UPDATE pump_maint_accounts SET report_only=1 WHERE name IN ({','.join('?' * len(REPORT_ONLY_ACCOUNTS))})",
              REPORT_ONLY_ACCOUNTS)


# Falling Waters II's client and pump job in Jobber.
_FW2_CLIENT, _FW2_JOB = 'Z2lkOi8vSm9iYmVyL0NsaWVudC8zNTM3MDA2Mg==', 'Z2lkOi8vSm9iYmVyL0pvYi80OTI1NjUzMA=='


def _undo_watercrest_mismatch(c, now):
    """Once (Oct 15 2026): Watercrest's October report was logged on Falling
    Waters II's job #2874 ("Watercrest" didn't match Jobber's "WATER CREST"),
    and that pick was remembered. Forget it, and put the report back on the
    Log report list so it can go on Water Crest's job."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pump_site_aliases'").fetchone():
        return   # a new database: nothing to undo yet
    c.execute("INSERT OR IGNORE INTO pump_state (key, value) VALUES ('watercrest_fw2_oct26', ?)", (json.dumps(now),))
    if c.rowcount != 1:
        return
    c.execute("DELETE FROM pump_site_aliases WHERE client_id=? AND LOWER(REPLACE(place, ' ', '')) LIKE '%watercrest%'",
              (_FW2_CLIENT,))
    for r in c.execute("SELECT id, jobber FROM pump_docs WHERE kind='report' AND jobber LIKE ?",
                       (f'%{_FW2_JOB}%',)).fetchall():
        j = json.loads(r[1] or '{}')
        if j.get('note_target_id') == _FW2_JOB and 'watercrest' in json.dumps(j).lower() + \
                (c.execute('SELECT client_name FROM pump_docs WHERE id=?', (r[0],)).fetchone()[0] or '').lower().replace(' ', ''):
            c.execute('UPDATE pump_docs SET jobber=? WHERE id=?', (json.dumps(
                {k: v for k, v in j.items() if not k.startswith('note_') and k not in ('logged_by', 'logged_at')}), r[0]))


def _fix_quote_needed_dates(c, now):
    """Once (Oct 16 2026): "quote needed" items made from a bill or report were
    dated from the vendor's paper; count them from the day they were made."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pump_cases'").fetchone():
        return
    c.execute("INSERT OR IGNORE INTO pump_state (key, value) VALUES ('quote_needed_dates_oct26', ?)", (json.dumps(now),))
    if c.rowcount != 1:
        return
    c.execute("UPDATE pump_cases SET opened_on=substr(created_at, 1, 10) WHERE source='bill' "
              "AND COALESCE(created_at, '') != '' AND opened_on < substr(created_at, 1, 10)")


def report_only_account(conn, case):
    """The account's name when a maintenance item is for an account that gets
    only its report logged - no invoice to draft or send. '' otherwise."""
    if (case or {}).get('category') not in ('maintenance', 'inspection'):
        return ''
    text = ' '.join(str(case.get(k) or '') for k in ('client_name', 'title', 'site'))
    name = match_account(text, conn)
    row = conn.execute('SELECT 1 FROM pump_maint_accounts WHERE name=? AND active=1 AND report_only=1',
                       (name,)).fetchone() if name else None
    return name if row else ''


def _apply_repairs_by(c, now):
    """Once (Oct 2026): who does the pump repairs where it isn't Wettech, from
    the office's sheets - SiteOne at Hodges, Naples Electric at Warm Springs,
    Oscar (our technician) at Autumn Woods and The Reserve, where Wettech does
    the maintenance. The office sets the rest on the Accounts tab."""
    c.execute("INSERT OR IGNORE INTO pump_state (key, value) VALUES ('repairs_by_oct26', ?)", (json.dumps(now),))
    if c.rowcount != 1:
        return
    for name, by in (('Hodges Funeral Home', 'SiteOne'), ('Warm Springs Comm. Assoc.', 'Naples Electric'),
                     ('Autumn Woods', IN_HOUSE), ('The Reserve @ Estero', IN_HOUSE)):
        c.execute("UPDATE pump_maint_accounts SET repairs_by=? WHERE name=? AND COALESCE(repairs_by, '')=''", (by, name))
    for name, old, new in (('Autumn Woods', 'the contact for any pump issues is Oscar.',
                            'pump issues go to Oscar (our technician).'),
                           ('The Reserve @ Estero', 'Contact besides Wettech: Oscar.',
                            'Besides Wettech, pump issues go to Oscar (our technician).')):
        c.execute('UPDATE pump_maint_accounts SET notes=REPLACE(notes, ?, ?) WHERE name=?', (old, new, name))


# Who to follow up with before an account's service, from the office's sheets
# (Oct 2026). Editable per account on the Accounts tab.
SEED_FOLLOW_UPS = [
    ('maint', 'Sopra Luxury Living', 'Email Lauren (lmleczek@davisdevelopment.com) to approve the visit before '
                                     'Wettech goes out.'),
    ('maint', 'Hodges Funeral Home', 'SiteOne does this service - ask PSochar@siteone.com (backup '
                                     'desposito@siteone.com) for their maintenance report.'),
    ('maint', 'Warm Springs Comm. Assoc.', 'Naples Electric does this service - get the report from '
                                           'jenna@nemwinc.com (Paul Jukins, paul@nemwinc.com).'),
    ('dive', 'Kurt Biggs', 'Make sure Ramon is there with Jordan (the diver) - Jordan calls to coordinate.'),
]
FOLLOW_UP_DAYS_AHEAD = 7


def _apply_follow_ups(c, now):
    c.execute("INSERT OR IGNORE INTO pump_state (key, value) VALUES ('follow_ups_oct26', ?)", (json.dumps(now),))
    if c.rowcount != 1:
        return
    for table, name, text in SEED_FOLLOW_UPS:
        tbl = 'pump_maint_accounts' if table == 'maint' else 'pump_dive_sites'
        c.execute(f"UPDATE {tbl} SET follow_up=? WHERE name=? AND COALESCE(follow_up, '')=''", (text, name))


def _service_month(months, monthly, today):
    """The service month (year, month) an account is due in now, or within
    FOLLOW_UP_DAYS_AHEAD days; None when it isn't. No months = every month."""
    for d in (today, today + timedelta(days=FOLLOW_UP_DAYS_AHEAD)):
        if monthly or not months or d.month in months:
            return d.year, d.month
    return None


def service_follow_ups(today=None):
    """A to-do, once per service, for each account with someone to follow up
    with before it: about a week ahead of the service month."""
    today = today or _today()
    conn = _conn()
    added = []
    try:
        rows = [('m', r['id'], r['name'], r['follow_up'], _month_list(r['months']), bool(r['monthly']))
                for r in conn.execute("SELECT * FROM pump_maint_accounts WHERE active=1 AND COALESCE(follow_up, '')!=''")]
        rows += [('d', r['id'], r['name'], r['follow_up'], _month_list(r['months']), False)
                 for r in conn.execute("SELECT * FROM pump_dive_sites WHERE COALESCE(active, 1)=1 "
                                       "AND COALESCE(needs_dive, 1)=1 AND COALESCE(follow_up, '')!=''")]
        for kind, rid, name, text, months, monthly in rows:
            when = _service_month(months, monthly, today)
            if not when:
                continue
            label = datetime(when[0], when[1], 1).strftime('%B')
            key = f'followup:{kind}:{rid}:{when[0]}-{when[1]:02d}'
            what = 'dive' if kind == 'd' else 'service'
            before = conn.total_changes
            add_todo(conn, key, f"Follow up before {name}'s {label} {what}", text, {'account': name},
                     due_on=f'{when[0]}-{when[1]:02d}-01')
            if conn.total_changes > before:
                added.append(key)
        conn.commit()
    finally:
        conn.close()
    return added


def init_account_tables(c):
    c.execute('''CREATE TABLE IF NOT EXISTS pump_scada_accounts (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  client TEXT NOT NULL,
                  renewal_date TEXT DEFAULT '',
                  product TEXT DEFAULT '',
                  vendor_cost REAL,
                  our_bill TEXT DEFAULT '',
                  vendor TEXT DEFAULT 'Wettech',
                  years TEXT DEFAULT '{}',
                  active INTEGER DEFAULT 1,
                  notes TEXT DEFAULT '',
                  case_id INTEGER,
                  updated_by TEXT DEFAULT '',
                  updated_at TEXT)''')
    # Maintenance contracts we bill each month (the office's 2026 Monthly Billing
    # Checklist): one row per line - "Autumn Woods M/M $3,605", "Autumn Woods
    # parts" - with the months billed ({"2026": [1, 2, 3]}).
    c.execute('''CREATE TABLE IF NOT EXISTS pump_contracts (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  account TEXT NOT NULL,
                  line TEXT DEFAULT '',
                  amount REAL,
                  frequency TEXT DEFAULT 'monthly',
                  status TEXT DEFAULT 'active',
                  billed TEXT DEFAULT '{}',
                  notes TEXT DEFAULT '',
                  updated_by TEXT DEFAULT '',
                  updated_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pump_maint_accounts (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  kind TEXT DEFAULT 'Pump',
                  joined TEXT DEFAULT '',
                  equipment TEXT DEFAULT '',
                  address TEXT DEFAULT '',
                  months TEXT DEFAULT '',
                  monthly INTEGER DEFAULT 0,
                  vendor_cost TEXT DEFAULT '',
                  naples_electric TEXT DEFAULT '',
                  our_bill TEXT DEFAULT '',
                  notes TEXT DEFAULT '',
                  active INTEGER DEFAULT 1,
                  updated_by TEXT DEFAULT '',
                  updated_at TEXT)''')
    # Whether the subcontractor (Wettech, Gulfshore) has been told about an
    # account's maintenance in a month - one row per account, vendor and month.
    c.execute('''CREATE TABLE IF NOT EXISTS pump_maint_notices (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  month TEXT NOT NULL,
                  account TEXT NOT NULL,
                  vendor TEXT NOT NULL,
                  how TEXT DEFAULT '',
                  note TEXT DEFAULT '',
                  notified_by TEXT DEFAULT '',
                  notified_at TEXT,
                  UNIQUE(month, account, vendor))''')
    for col, decl in (('kind', "TEXT DEFAULT 'Lake'"), ('joined', "TEXT DEFAULT ''"), ('diver_cost', "TEXT DEFAULT ''"),
                      ('our_bill', "TEXT DEFAULT ''"), ('naples_electric', "TEXT DEFAULT ''"),
                      ('active', 'INTEGER DEFAULT 1')):
        try:
            c.execute(f'ALTER TABLE pump_dive_sites ADD COLUMN {col} {decl}')
        except sqlite3.OperationalError:
            pass
    # jobber_*: the account's Jobber client, property and recurring maintenance job (set on the Accounts tab).
    for tbl, col in (('pump_maint_accounts', 'repairs_by'), ('pump_maint_accounts', 'follow_up'),
                     ('pump_dive_sites', 'follow_up'),
                     *(('pump_maint_accounts', f'jobber_{k}') for k in ('client_id', 'client_name', 'property_id',
                                                                        'property_label', 'job_id', 'job_label'))):
        try:
            c.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
    try:
        # report_only: the client gets the pump report logged in Jobber, never a maintenance invoice.
        c.execute('ALTER TABLE pump_maint_accounts ADD COLUMN report_only INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    for col, decl in (('jobber_names', "TEXT DEFAULT ''"), ('complimentary', 'INTEGER DEFAULT 0'),
                      ('quote', "TEXT DEFAULT '{}'")):
        try:
            c.execute(f'ALTER TABLE pump_scada_accounts ADD COLUMN {col} {decl}')
        except sqlite3.OperationalError:
            pass
    now = _now_text()
    seeded = lambda k: c.execute('SELECT 1 FROM pump_state WHERE key=?', (k,)).fetchone()
    mark = lambda k: c.execute('INSERT OR REPLACE INTO pump_state (key, value) VALUES (?,?)', (k, '"yes"'))
    if not seeded('scada_sheet_seeded'):
        for client, due, product, cost, bill, vendor, years in SEED_SCADA:
            c.execute('''INSERT INTO pump_scada_accounts (client, renewal_date, product, vendor_cost, our_bill, vendor,
                           years, updated_by, updated_at) VALUES (?,?,?,?,?,?,?,?,?)''',
                      (client, due, product, cost, bill, vendor, json.dumps(years), 'SCADA sheet (Oct 2026)', now))
        mark('scada_sheet_seeded')
    if not seeded('maint_sheet_seeded'):
        for (name, kind, joined, equip, addr, months, cost, ne, bill, notes, active) in SEED_MAINT:
            c.execute('''INSERT INTO pump_maint_accounts (name, kind, joined, equipment, address, months, monthly,
                           vendor_cost, naples_electric, our_bill, notes, active, updated_by, updated_at)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                      (name, kind, joined, equip, addr, months, 1 if name in MAINT_MONTHLY else 0, cost, ne, bill,
                       notes, active, 'Maintenance sheet (Oct 2026)', now))
        mark('maint_sheet_seeded')
    if not seeded('lake_sheet_seeded'):
        for (name, kind, joined, equip, addr, months, cost, bill, ne, notes, needs, active) in SEED_LAKES:
            row = c.execute('SELECT id, diver_notes FROM pump_dive_sites WHERE name=?', (name,)).fetchone()
            if row:
                sets = {'kind': kind, 'joined': joined, 'equipment': equip, 'months': months, 'diver_cost': cost,
                        'our_bill': bill, 'naples_electric': ne, 'needs_dive': needs, 'active': active}
                if addr is not None:
                    sets['address'] = addr
                if notes and not (row[1] or '').strip():
                    sets['diver_notes'] = notes
                c.execute(f"UPDATE pump_dive_sites SET {', '.join(k + '=?' for k in sets)}, updated_by=?, updated_at=? "
                          f"WHERE id=?", (*sets.values(), 'Lake sheet (Oct 2026)', now, row[0]))
            else:
                c.execute('''INSERT INTO pump_dive_sites (name, kind, joined, equipment, address, months, diver_cost,
                               our_bill, naples_electric, diver_notes, needs_dive, active, updated_by, updated_at)
                             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                          (name, kind, joined, equip, addr or '', months, cost, bill, ne, notes or '', needs, active,
                           'Lake sheet (Oct 2026)', now))
        mark('lake_sheet_seeded')
    _scada_jobber_migrate(c)
    _apply_master_list(c, now)
    _apply_repairs_by(c, now)
    _apply_master_vendors(c, now)
    _apply_report_only(c, now)
    _undo_watercrest_mismatch(c, now)
    _fix_quote_needed_dates(c, now)
    _apply_follow_ups(c, now)
    _stop_tracking_beatrice(c, now)
    _paid_once_emailed(c, now)
    _drop_irrigation_quotes(c, now)
    _unhook_wrong_client_quotes(c, now)
    _dismiss_siteone_store(c, now)
    _seed_contracts(c, now)
    _spell_beatriz(c, now)
    if not seeded('office_answers_oct26'):
        # What the office said (Oct 2026): Old Collier and Camas Willows are off
        # SCADA; Autumn Woods (we pay) and Reserve at Estero (in their monthly)
        # are complimentary - reminded, never quoted. The diver list goes by itself.
        c.execute("UPDATE pump_scada_accounts SET active=0, notes=TRIM(COALESCE(notes,'') || ' No longer on SCADA (Oct 2026).') "
                  "WHERE client IN ('OLD COLLIER', 'Camas Willows 1')")
        c.execute("UPDATE pump_scada_accounts SET complimentary=1, notes=TRIM(COALESCE(notes,'') || ' Complimentary - "
                  "our company pays for it.') WHERE client='AUTUMN WOODS'")
        c.execute("UPDATE pump_scada_accounts SET complimentary=1, notes=TRIM(COALESCE(notes,'') || ' Complimentary - "
                  "included with their monthly.') WHERE client='RESERVE AT ESTERO'")
        saved = c.execute("SELECT value FROM pump_state WHERE key='dive_settings'").fetchone()
        if saved:
            ds = json.loads(saved[0] or '{}')
            ds['auto'] = True
            c.execute("UPDATE pump_state SET value=? WHERE key='dive_settings'", (json.dumps(ds),))
        mark('office_answers_oct26')


def _anniversary(d, year):
    try:
        return d.replace(year=year)
    except ValueError:
        return d.replace(year=year, day=28)


def _scada_row(r, today):
    d = dict(r)
    try:
        d['years'] = json.loads(d.get('years') or '{}')
    except ValueError:
        d['years'] = {}
    due = None
    try:
        due = datetime.strptime((d['renewal_date'] or '')[:10], '%Y-%m-%d').date()
    except ValueError:
        pass
    filled = sorted(int(y) for y, v in d['years'].items() if str(v).strip() and y.isdigit())
    if due and filled and _anniversary(due, filled[-1] + 1) > due:
        # A later year was recorded than the sheet's date shows: due a year after it.
        due = _anniversary(due, filled[-1] + 1)
    d['next_due_on'] = due.isoformat() if due else ''
    # This renewal's quote in Jobber - its number, status and link (the SCADA tab, Oct 2026).
    try:
        q = json.loads(d.get('quote') or '{}') if isinstance(d.get('quote'), str) else (d.get('quote') or {})
    except ValueError:
        q = {}
    d['renewal_quote'] = q if q.get('number') and q.get('year') == d['next_due_on'][:4] else None
    d['client_name'], d['site'] = d['client'], ''
    if not d['active']:
        d['state'] = 'inactive'
    elif not due:
        d['state'] = 'unknown'
    else:
        days = (due - today).days
        d['days_left'] = days
        d['state'] = 'overdue' if days < 0 else ('due_soon' if days <= SCADA_DUE_SOON_DAYS else 'current')
    return d


def scada_rows(conn):
    today = _today()
    out = [_scada_row(r, today) for r in conn.execute('SELECT * FROM pump_scada_accounts')]
    order = {'overdue': 0, 'due_soon': 1, 'unknown': 2, 'current': 3, 'inactive': 4}
    out.sort(key=lambda d: (order.get(d['state'], 9), d.get('next_due_on') or '9999', d['client'].lower()))
    return out


def scada_years(rows):
    ys = {int(y) for r in rows for y in r['years'] if y.isdigit()} | {2023, _today().year}
    return [str(y) for y in range(min(ys), max(ys) + 1)]


# ── SCADA renewals seen in Jobber ────────────────────────────────────────────
# Our SCADA renewal invoices say "Renewal of Annual Cellular and cloud
# subscription for SCADA system on irrigation pump station". Each Jobber sync
# looks for them and writes the invoice # into the client's year, so the SCADA
# tab keeps up without anyone typing it in.

# What each row is called in Jobber: words of the client name, or a site named
# on the invoice ("... for Cross Creek" is billed to Medallion Home).
SCADA_JOBBER_NAMES = {
    'ALLURE': 'Allura', 'AUTUMN WOODS': 'Autumn Woods', 'BANYAN BAY': 'Banyan Bay',
    'Camas Willows 1': 'Camas Willows', 'CLUBCARE': 'Club Care', 'COCONUT LANDING': 'Coconut Landing',
    'COMMUNITY SCHOOL': 'Community School', 'CROSS CREEK': 'Cross Creek',
    'CORSA (formerly Estero Crossing)': 'Corsa; Estero Crossing', 'FGCU-Athletics': 'FGCU Athletics',
    'FRUITVILLE COMMONS': 'Fruitville', 'LELY': 'Lely', 'OLD COLLIER': 'Old Collier',
    'RESERVE AT ESTERO': 'Reserve Estero', 'Tuscany Point': 'Tuscany Pointe; Tuscany Point', 'WildBlue': 'Wild Blue',
}

# Checked against the paid SCADA renewal invoices in Jobber (Oct 2026); the
# sheet stopped at 2024/2025. Only empty years are filled.
SCADA_FROM_JOBBER_OCT26 = {
    'ALLURE': {'2026': '35944'},
    'BANYAN BAY': {'2026': '32863'},
    'CLUBCARE': {'2025': '27166', '2026': '32861'},
    'COCONUT LANDING': {'2025': '27840', '2026': '33254'},
    'COMMUNITY SCHOOL': {'2025': '31344'},
    'CROSS CREEK': {'2026': '33687'},
    'CORSA (formerly Estero Crossing)': {'2025': '28997'},
    'FGCU-Athletics': {'2025': '31939', '2026': '35279'},
    'FRUITVILLE COMMONS': {'2026': '32860'},
    'LELY': {'2025': '25555', '2026': '32638'},
    'Tuscany Point': {'2026': '32875'},
    'WildBlue': {'2026': '32858'},
}
# SCADA clients in Jobber that the sheet did not have.
SCADA_NEW_FROM_JOBBER = [
    ('Sopra Luxury Living @ The Forum', '2025-03-01', '$600.00', 'Sopra', {'2025': '26892', '2026': '32862'}),
    ('Heritage Stations', '2025-03-15', '$600.00', 'Heritage Stations', {'2025': '28165', '2026': '33405'}),
    ('FGCU - PGA program (Driving Range)', '2025-12-01', '$600.00', 'FGCU PGA; Driving Range',
     {'2025': '32130', '2026': '36707'}),
]


def _scada_jobber_migrate(c):
    if c.execute("SELECT 1 FROM pump_state WHERE key='scada_jobber_oct26'").fetchone():
        return
    now = _now_text()
    for r in c.execute('SELECT id, client, years, jobber_names FROM pump_scada_accounts').fetchall():
        years = json.loads(r[2] or '{}')
        for y, v in SCADA_FROM_JOBBER_OCT26.get(r[1], {}).items():
            if not str(years.get(y) or '').strip():
                years[y] = v
        names = r[3] or SCADA_JOBBER_NAMES.get(r[1], '')
        c.execute('UPDATE pump_scada_accounts SET years=?, jobber_names=? WHERE id=?', (json.dumps(years), names, r[0]))
    for client, due, bill, names, years in SCADA_NEW_FROM_JOBBER:
        if not c.execute('SELECT 1 FROM pump_scada_accounts WHERE client=?', (client,)).fetchone():
            c.execute('''INSERT INTO pump_scada_accounts (client, renewal_date, product, vendor_cost, our_bill, vendor,
                           years, jobber_names, notes, updated_by, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                      (client, due, 'Annual Subscription - SCADA', 428.00, bill, 'Wettech', json.dumps(years), names,
                       'Found in Jobber - not on the SCADA sheet', 'Jobber invoices (Oct 2026)', now))
    c.execute("INSERT OR REPLACE INTO pump_state (key, value) VALUES ('scada_jobber_oct26', '\"yes\"')")


def is_scada_renewal(text):
    t = (text or '').lower()
    return 'scada' in t and ('subscription' in t or 'renew' in t)


def scada_invoice_year(text, issued):
    """The year a renewal invoice counts for: "2025-2026 Renewal" is 2025 even
    when it went out in January 2026; otherwise the year it was issued."""
    m = re.search(r'\b(20\d\d)\s*[-–/]\s*(20\d\d)\b', text or '') or \
        re.search(r'\b(20\d\d)\s+renewal', text or '', re.I)
    return m.group(1) if m else (issued or '')[:4]


def _scada_match(rows, client_name, text):
    hits = []
    for r in rows:
        names = [n.strip() for n in re.split(r'[;,\n]', r['jobber_names'] or '') if n.strip()] or [r['client']]
        if any(fuzzy_has(n, client_name) for n in names):
            hits.append((0, r))
        elif any(fuzzy_has(n, text) for n in names):
            hits.append((1, r))
    best = [r for p, r in hits if p == min((p for p, _ in hits), default=0)]
    return best[0] if len(best) == 1 else None


def record_scada_invoice(conn, inv):
    """Put one Jobber SCADA renewal invoice on the SCADA tab: its number goes
    in the client's year if that year is empty. A client not on the tab is
    added. Returns what happened, or None."""
    number = str(inv.get('invoiceNumber') or '').strip()
    status = (inv.get('invoiceStatus') or '').lower()
    lines = (inv.get('lineItems') or {}).get('nodes') if isinstance(inv.get('lineItems'), dict) else inv.get('lineItems')
    text = ' '.join(f"{li.get('name') or ''} {li.get('description') or ''}" for li in lines or [])
    if not number or status in ('draft', 'voided', 'bad_debt') or not is_scada_renewal(text):
        return None
    rows = [dict(r) for r in conn.execute('SELECT * FROM pump_scada_accounts')]
    if any(number == str(v).strip() for r in rows for v in json.loads(r['years'] or '{}').values()):
        return None
    client = (inv.get('client') or {}).get('name') or ''
    issued = (inv.get('issuedDate') or inv.get('createdAt') or '')[:10]
    year = scada_invoice_year(text, issued)
    row = _scada_match(rows, client, text)
    now = _now_text()
    if row is None:
        if any(fuzzy_has(r['client'], client) for r in rows):
            return None  # the client has several sites on the tab and the invoice doesn't say which
        conn.execute('''INSERT INTO pump_scada_accounts (client, renewal_date, product, our_bill, vendor, years,
                          jobber_names, notes, updated_by, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)''',
                     (client[:120], issued, 'Annual Subscription - SCADA', _fmt_money(inv), 'Wettech',
                      json.dumps({year: number}), client[:120], f'Found in Jobber (invoice #{number})', 'jobber sync', now))
        _event(conn, 'jobber sync', 'SCADA client found', f'{client}: invoice #{number} ({year})')
        return 'added'
    years = json.loads(row['years'] or '{}')
    if str(years.get(year) or '').strip():
        return None
    years[year] = number
    conn.execute('UPDATE pump_scada_accounts SET years=?, updated_by=?, updated_at=? WHERE id=?',
                 (json.dumps(years), 'jobber sync', now, row['id']))
    _event(conn, 'jobber sync', 'SCADA renewed', f"{row['client']} {year}: invoice #{number}")
    return 'recorded'


def _fmt_money(inv):
    total = (inv.get('amounts') or {}).get('total')
    return f'${float(total):,.2f}' if isinstance(total, (int, float)) else ''


def scan_scada_invoices(conn, days=430):
    """Read the last ~14 months of Jobber invoices for SCADA renewals."""
    since = (_today() - timedelta(days=days)).isoformat()
    lines = 'lineItems(first: 10) { nodes { name description } }'   # all of them: past Jobber's points limit
    fields = (f'id invoiceNumber invoiceStatus issuedDate createdAt jobberWebUri amounts {{ total }} '
              f'client {{ id name }} {lines}')
    filt = '(first: 50, after: $after, filter: { issuedDate: { after: $since } })'
    done = {'added': 0, 'recorded': 0}
    cursor, pages = None, 0
    while pages < 30:
        q = (f'query($after: String, $since: ISO8601DateTime) {{ invoices{filt} {{ nodes {{ {fields} }} '
             f'pageInfo {{ hasNextPage endCursor }} }} }}')
        try:
            data = jobber_gql(q, {'after': cursor, 'since': since + 'T00:00:00Z'})
        except JobberError as e:
            if 'filter' in filt and re.search(r'filter|issuedDate|ISO8601DateTime', str(e)):
                filt = '(first: 50, after: $after)'  # older API: read pages until they are older than `since`
                fields = fields.replace('amounts { total } ', '')
                continue
            raise
        page = (data or {}).get('invoices') or {}
        nodes = page.get('nodes') or []
        for inv in nodes:
            what = record_scada_invoice(conn, inv)
            if what:
                done[what] += 1
        pages += 1
        info = page.get('pageInfo') or {}
        if not info.get('hasNextPage') or not nodes:
            break
        if 'filter' not in filt and all((n.get('createdAt') or '')[:10] < since for n in nodes):
            break
        cursor = info.get('endCursor')
        time.sleep(0.2)
    return done


@api('/scada')
def h_scada(actor):
    conn = _conn()
    try:
        rows = scada_rows(conn)
        return {'scada': rows, 'years': scada_years(rows)}
    finally:
        conn.close()


@api('/scada', methods=('POST',))
def h_scada_add(actor):
    d = _json()
    if not (d.get('client') or '').strip():
        raise ValueError('Give the client')
    conn = _conn()
    try:
        conn.execute('''INSERT INTO pump_scada_accounts (client, renewal_date, product, vendor_cost, our_bill, vendor,
                          years, notes, updated_by, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)''',
                     (d['client'].strip()[:120], _iso_date(d.get('renewal_date')), (d.get('product') or '')[:200],
                      _money(d.get('vendor_cost')), (d.get('our_bill') or '')[:120], (d.get('vendor') or 'Wettech')[:60],
                      '{}', (d.get('notes') or '')[:1000], actor, _now_text()))
        conn.commit()
        return {'scada': scada_rows(conn)}
    finally:
        conn.close()


@api('/scada/<int:sid>', methods=('PATCH', 'POST'))
def h_scada_update(actor, sid):
    """Edit a row; {"action": "renewed", "value": "29448"} records this
    renewal (invoice # or a note) in its year and moves the date on a year;
    {"action": "renewal_item"} opens an item to quote and order it."""
    d = _json()
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_scada_accounts WHERE id=?', (sid,)).fetchone()
        if not row:
            return {'success': False, 'error': 'Not found'}, 404
        cur = _scada_row(row, _today())
        if d.get('action') == 'renewal_item':
            if row['case_id']:
                c = conn.execute("SELECT status FROM pump_cases WHERE id=?", (row['case_id'],)).fetchone()
                if c and c['status'] == 'open':
                    return {'case_id': row['case_id']}
            cid = create_case(conn, {'title': f"SCADA annual renewal - {row['client']}", 'category': 'scada',
                                     'client_name': row['client'], 'vendor': row['vendor'] or 'Wettech',
                                     'description': f"{row['product'] or 'Annual SCADA'} - due {cur['next_due_on']}.",
                                     'vendor_quote_amount': row['vendor_cost']}, actor, source='scada')
            conn.execute('UPDATE pump_scada_accounts SET case_id=?, updated_at=? WHERE id=?', (cid, _now_text(), sid))
            conn.commit()
            return {'case_id': cid}
        if d.get('action') == 'renewed':
            value = str(d.get('value') or '').strip()
            if not value:
                raise ValueError('Give the invoice # (or a note such as "No charge")')
            due = datetime.strptime(cur['next_due_on'], '%Y-%m-%d').date() if cur['next_due_on'] else _today()
            years = cur['years']
            years[str(due.year)] = value[:120]
            conn.execute('UPDATE pump_scada_accounts SET years=?, renewal_date=?, updated_by=?, updated_at=? WHERE id=?',
                         (json.dumps(years), _anniversary(due, due.year + 1).isoformat(), actor, _now_text(), sid))
            _event(conn, actor, 'SCADA renewed', f"{row['client']} {due.year}: {value}")
            conn.commit()
            return {'scada': scada_rows(conn)}
        sets, vals = [], []
        for k in ('client', 'product', 'our_bill', 'vendor', 'notes', 'jobber_names'):
            if k in d:
                sets.append(f'{k}=?')
                vals.append(str(d[k] or '').strip()[:1000])
        if 'renewal_date' in d:
            sets.append('renewal_date=?')
            vals.append(_iso_date(d['renewal_date']))
        if 'vendor_cost' in d:
            sets.append('vendor_cost=?')
            vals.append(_money(d['vendor_cost']))
        if 'active' in d:
            sets.append('active=?')
            vals.append(1 if d['active'] else 0)
        if 'complimentary' in d:
            sets.append('complimentary=?')
            vals.append(1 if d['complimentary'] else 0)
        if isinstance(d.get('years'), dict):
            years = cur['years']
            for y, v in d['years'].items():
                if str(y).isdigit():
                    if str(v or '').strip():
                        years[str(y)] = str(v).strip()[:120]
                    else:
                        years.pop(str(y), None)
            sets.append('years=?')
            vals.append(json.dumps(years))
        if sets:
            conn.execute(f"UPDATE pump_scada_accounts SET {', '.join(sets)}, updated_by=?, updated_at=? WHERE id=?",
                         (*vals, actor, _now_text(), sid))
            conn.commit()
        return {'scada': scada_rows(conn)}
    finally:
        conn.close()


MAINT_FIELDS = ('name', 'kind', 'joined', 'equipment', 'address', 'months', 'vendor_cost', 'naples_electric', 'our_bill',
                'notes', 'repairs_by', 'follow_up', 'jobber_client_id', 'jobber_client_name', 'jobber_property_id',
                'jobber_property_label', 'jobber_job_id', 'jobber_job_label')


def maint_accounts(conn):
    rows = [dict(r) for r in conn.execute('SELECT * FROM pump_maint_accounts ORDER BY active DESC, name COLLATE NOCASE')]
    m = _today().month
    for r in rows:
        r['due_this_month'] = bool(r['active']) and (bool(r['monthly']) or m in _month_list(r['months']))
    return rows


@api('/maint')
def h_maint(actor):
    conn = _conn()
    try:
        return {'accounts': maint_accounts(conn), 'month': _today().month}
    finally:
        conn.close()


@api('/maint', methods=('POST',))
def h_maint_save(actor):
    if actor == BOT:
        return _office_only(actor, 'Changing the maintenance accounts')
    d = _json()
    vals = {k: str(d.get(k) or '').strip()[:1000] for k in MAINT_FIELDS if k in d}
    if 'joined' in vals:
        vals['joined'] = _iso_date(vals['joined']) or vals['joined']
    if 'months' in vals:
        vals['months'] = ','.join(str(x) for x in _month_list(vals['months']))
    for k in ('active', 'monthly'):
        if k in d:
            vals[k] = 1 if d[k] in (True, 1, '1', 'true', 'on') else 0
    conn = _conn()
    try:
        if d.get('id'):
            if 'name' in vals and not vals['name']:
                raise ValueError('An account needs a name')
            conn.execute(f"UPDATE pump_maint_accounts SET {', '.join(k + '=?' for k in vals)}, updated_by=?, "
                         f"updated_at=? WHERE id=?", (*vals.values(), actor, _now_text(), int(d['id'])))
        else:
            if not vals.get('name'):
                raise ValueError('An account needs a name')
            cols = list(vals) + ['updated_by', 'updated_at']
            conn.execute(f"INSERT INTO pump_maint_accounts ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                         (*vals.values(), actor, _now_text()))
        aid = int(d['id']) if d.get('id') else conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        acct = dict(conn.execute('SELECT * FROM pump_maint_accounts WHERE id=?', (aid,)).fetchone())
        conn.commit()
    finally:
        conn.close()
    if vals.get('jobber_client_id'):
        link_account_to_jobber(acct, actor)
    conn = _conn()
    try:
        return {'accounts': maint_accounts(conn)}
    finally:
        conn.close()


def schedule_text(acct):
    if acct.get('monthly'):
        return 'monthly'
    ms = _month_list(acct.get('months'))
    return ', '.join(date(2000, m, 1).strftime('%b') for m in ms) if ms else 'scheduled'


def recurring_job_for(acct):
    """The account's recurring maintenance job(s) in Jobber - from the last
    sync, or asked of Jobber - the one at its property first. None if there is none."""
    cid, pid = acct.get('jobber_client_id'), acct.get('jobber_property_id') or ''
    if not cid:
        return None
    conn = _conn()
    try:
        jobs = [{'id': r['jobber_id'], 'number': r['number'], 'title': r['title'] or '', 'property_id': r['property_id']}
                for r in conn.execute("SELECT * FROM pump_jobber_items WHERE kind='job' AND job_type='recurring' "
                                      "AND client_id=? AND status NOT IN ('archived')", (cid,))]
    finally:
        conn.close()
    if not jobs and jobber_status()['connected']:
        try:
            jobs = [j for j in client_jobs(cid).get('jobs') or [] if j.get('type') == 'recurring'
                    and j.get('status') != 'archived']
        except JobberError:
            jobs = []
    if not jobs:
        return None
    jobs.sort(key=lambda j: (not (pid and j.get('property_id') == pid),
                             not TITLE_PATTERNS['pump'].search(j.get('title') or '')))
    j = jobs[0]
    label = ', '.join(f"#{x['number']}" for x in jobs if x.get('number')) + (f" {j['title']}" if j.get('title') else '')
    return {'id': j['id'], 'label': label.strip()}


# To-dos the app adds about a job, that the job itself can show are done.
_JOB_TODOS = ('sign-quote', 'approved-quote', 'quote-to-job', 'service-visit', 'gov-refs', 'signed-reply',
              'date-to-jobber')


def close_stale_todos(conn):
    """Tick the app's own to-dos whose work is visibly done, so To do only has
    what still needs someone: the job is closed or cancelled; its Jobber job
    exists (convert the quote, add the visit); its WO # and PO # are in (the
    county); the quote is signed and sent; the account's maintenance job is in Jobber."""
    now = _now_text()
    for t in conn.execute("SELECT id, key, link FROM pump_todos WHERE done_at IS NULL AND kind != 'manual'").fetchall():
        prefix = (t['key'] or '').split(':')[0]
        if prefix not in _JOB_TODOS:
            continue
        try:
            cid = int((json.loads(t['link'] or '{}') or {}).get('case_id') or 0)
        except (TypeError, ValueError):
            cid = 0
        row = conn.execute('SELECT * FROM pump_cases WHERE id=?', (cid,)).fetchone() if cid else None
        if not row:
            continue
        c = dict(row)
        j = json.loads(c.get('jobber') or '{}')
        done = c['status'] != 'open'
        if prefix in ('quote-to-job', 'service-visit'):
            done = done or bool((j.get('job') or {}).get('id'))
        if prefix == 'quote-to-job' and not done:
            # Converted by hand in Jobber: the synced quote says so.
            q = j.get('quote') or {}
            it = conn.execute("SELECT status FROM pump_jobber_items WHERE jobber_id=?",
                              (q.get('id'),)).fetchone() if q.get('id') else None
            done = 'converted' in (q.get('status'), it and it['status'])
        elif prefix == 'gov-refs':
            done = done or not gov_missing_refs(c)
        elif prefix in ('sign-quote', 'approved-quote'):
            doc = _approved_quote_doc(conn, cid)
            done = done or bool(doc and (doc.get('jobber') or {}).get('signed_sent_at'))
        if done:
            conn.execute("UPDATE pump_todos SET done_at=?, done_by='Pumps' WHERE id=?", (now, t['id']))
    close_maint_job_todos(conn)


def close_maint_job_todos(conn):
    """"Set up X's pump maintenance job in Jobber" once Jobber has one (each sync)."""
    for t in conn.execute("SELECT id, key FROM pump_todos WHERE key LIKE 'maint-job:%' AND done_at IS NULL").fetchall():
        row = conn.execute('SELECT * FROM pump_maint_accounts WHERE id=?', (int(t['key'].split(':')[1]),)).fetchone()
        if not row:
            continue
        acct = dict(row)
        if not acct.get('active') or (acct.get('jobber_client_id') and conn.execute(
                "SELECT 1 FROM pump_jobber_items WHERE kind='job' AND job_type='recurring' AND client_id=? "
                "AND status NOT IN ('archived') LIMIT 1", (acct['jobber_client_id'],)).fetchone()):
            conn.execute("UPDATE pump_todos SET done_at=?, done_by='Pumps' WHERE id=?", (_now_text(), t['id']))


def link_account_to_jobber(acct, actor):
    """A pump account tied to its Jobber client: its name becomes a site name
    for that client, property and maintenance job, so Wettech's quotes and
    service reports for it go there, and its Jobber quotes are followed. With
    no recurring maintenance job in Jobber yet, a to-do to set one up."""
    save_site_alias(acct['name'], '', acct['jobber_client_id'], acct.get('jobber_client_name') or '',
                    acct.get('jobber_property_id') or '', acct.get('jobber_property_label') or '',
                    'Pump account (Accounts tab)', actor, acct.get('jobber_job_id') or '', acct.get('jobber_job_label') or '')
    if not acct.get('jobber_job_id'):
        job = recurring_job_for(acct)
        if job:
            # Already in Jobber (The Carlisle: #3249 and #3250, one per pump) - use it, no to-do.
            acct = {**acct, 'jobber_job_id': job['id'], 'jobber_job_label': job['label']}
            conn = _conn()
            try:
                conn.execute('UPDATE pump_maint_accounts SET jobber_job_id=?, jobber_job_label=? WHERE id=?',
                             (job['id'], job['label'], acct['id']))
                conn.commit()
            finally:
                conn.close()
    conn = _conn()
    try:
        key = f"maint-job:{acct['id']}"
        if acct.get('jobber_job_id'):
            conn.execute("UPDATE pump_todos SET done_at=?, done_by=? WHERE key=? AND done_at IS NULL",
                         (_now_text(), actor or '', key))
        elif acct.get('active', 1):
            add_todo(conn, key, f"Set up {acct['name']}'s pump maintenance job in Jobber",
                     f"{acct['name']} is a pump account now (Jobber client {acct.get('jobber_client_name') or ''}). Make "
                     f"its recurring maintenance job in Jobber ({schedule_text(acct)} visits, we bill "
                     f"{acct.get('our_bill') or 'the agreed price'}), then pick it on the account (Edit).",
                     {'account': acct['name']})
        conn.commit()
    finally:
        conn.close()


@api('/maint/<int:aid>/delete', methods=('POST',))
def h_maint_delete(actor, aid):
    if actor == BOT:
        return _office_only(actor, 'Changing the maintenance accounts')
    conn = _conn()
    try:
        conn.execute('DELETE FROM pump_maint_accounts WHERE id=?', (aid,))
        conn.commit()
        return {'accounts': maint_accounts(conn)}
    finally:
        conn.close()



# ═════════════════════════════════════════════════════════════════════════════
# The office's flow (Oct 2026): request -> vendor quote -> our Jobber quote ->
# approved (stamped, sent back, made a job) -> vendor bill -> our invoice at
# the quoted price -> client pays -> pay the vendor. Plus SCADA renewals, the
# daily email and the accounts list.
# ═════════════════════════════════════════════════════════════════════════════

APPROVER = os.environ.get('PUMPS_APPROVER', 'Simon Weardon')
AUTO_DRAFT_INVOICES = False   # never by itself: a bill waits on "Draft invoice" for a person (Oct 22 2026)
DIGEST_TO = os.environ.get('PUMPS_DIGEST_TO', 'simon@stahlman-england.com')
DIGEST_HOUR = int(os.environ.get('PUMPS_DIGEST_HOUR', '8') or 8)
SERVICE_CALL_DAYS = int(os.environ.get('PUMPS_SERVICE_CALL_DAYS', '14') or 14)
SERVICE_WORDS = re.compile(r'\b(pumps?|pump\s+station|scada|divers?|aerators?|fountains?|lake\s+filters?|'
                           r'filters?|lakes?)\b', re.I)


def add_todo(conn, key, title, detail='', link=None, kind='auto', due_on=''):
    """A to-do the app adds itself, once per key (a done one is not re-added)."""
    conn.execute('INSERT OR IGNORE INTO pump_todos (kind, key, title, detail, due_on, link, created_by, created_at) '
                 'VALUES (?,?,?,?,?,?,?,?)', (kind, key, title[:300], (detail or '')[:2000], due_on or '',
                                              json.dumps(link or {}), 'Pumps', _now_text()))


# Who does an account's pump repairs, when it isn't Wettech (set per account on
# the Accounts tab). Contacts for emails; '' email = type it in.
IN_HOUSE = 'Oscar (our technician)'
REPAIR_COMPANIES = {
    'SiteOne': ('SiteOne', 'PSochar@siteone.com'),
    'Naples Electric': ('Paul', 'paul@nemwinc.com'),
    IN_HOUSE: ('Oscar', ''),
}
# Steps a job skips when our own technician does the work: no vendor quote,
# bill or bill check - we quote and invoice the client ourselves.
IN_HOUSE_NA = ('vendor_quote', 'vendor_bill', 'bill_checked')


def account_repairs_by(conn, fields):
    """Who does pump repairs for the account a new job is for ('' = Wettech)."""
    text = ' '.join(str(fields.get(k) or '') for k in ('client_name', 'title', 'site'))
    name = match_account(text, conn)
    if not name:
        return ''
    row = conn.execute("SELECT repairs_by FROM pump_maint_accounts WHERE name=? AND active=1", (name,)).fetchone()
    return (row[0] or '') if row else ''


def _vendor_contact(vendor):
    if vendor in REPAIR_COMPANIES:
        return REPAIR_COMPANIES[vendor]
    v = _vendor_profile(vendor or 'Wettech')
    return (v.get('contact_name') or v.get('display') or vendor or 'the vendor',
            v.get('contact_email') or _vendor_email(vendor))


# ── Jobber actions that depend on what Jobber's API offers ───────────────────
# Adding a visit to a job and turning an approved quote into a job are not in
# every Jobber API version under the same name. The app asks Jobber's schema
# which exist and fills only what it knows; anything it cannot do becomes a
# to-do instead.

VISIT_MUTATIONS = ('visitCreate', 'jobAddVisit', 'jobCreateVisit', 'jobVisitCreate')
JOB_FROM_QUOTE_MUTATIONS = ('jobCreate',)
_SCHEMA_CACHE = {}


def _type_ref(t):
    """(NON_NULL?, LIST?, named type) of an introspected type."""
    nn = lst = False
    while t and t.get('kind') in ('NON_NULL', 'LIST'):
        if t['kind'] == 'NON_NULL':
            nn = True
        else:
            lst = True
        t = t.get('ofType')
    return nn, lst, (t or {}).get('name')


_TYPE_Q = 'kind name ofType { kind name ofType { kind name ofType { kind name } } }'


def _mutation_schema():
    if 'mutations' not in _SCHEMA_CACHE:
        data = jobber_gql('query { __schema { mutationType { fields { name type { ' + _TYPE_Q + ' } '
                          'args { name type { ' + _TYPE_Q + ' } } } } } }')
        _SCHEMA_CACHE['mutations'] = {f['name']: f for f in
                                      (((data.get('__schema') or {}).get('mutationType') or {}).get('fields') or [])}
    return _SCHEMA_CACHE['mutations']


def _type_fields(name):
    key = f'type:{name}'
    if key not in _SCHEMA_CACHE:
        data = jobber_gql('query($n: String!) { __type(name: $n) { name inputFields { name type { ' + _TYPE_Q +
                          ' } } fields { name type { ' + _TYPE_Q + ' } } } }', {'n': name})
        _SCHEMA_CACHE[key] = data.get('__type') or {}
    return _SCHEMA_CACHE[key]


def try_mutation(candidates, values, want=None):
    """Run the first of the candidate mutations Jobber has, filling its
    arguments (and its input object's fields) from values by name. Returns
    the payload, or None when none exists or a required field is unknown.
    Raises JobberError when Jobber refuses it."""
    values = {k: v for k, v in values.items() if v not in (None, '')}
    schema = _mutation_schema()
    for name in candidates:
        f = schema.get(name)
        if not f or name not in ALLOWED_MUTATIONS:
            continue
        args, decls, ok = {}, [], True
        for a in f.get('args') or []:
            nn, lst, tname = _type_ref(a['type'])
            if a['name'] in values:
                args[a['name']] = values[a['name']]
            else:
                inner = _type_fields(tname).get('inputFields') if tname else None
                if inner is None:
                    if nn:
                        ok = False
                    continue
                obj = {}
                for fld in inner:
                    fnn = _type_ref(fld['type'])[0]
                    if fld['name'] in values:
                        obj[fld['name']] = values[fld['name']]
                    elif fnn:
                        ok = False
                if not obj and not nn:
                    continue
                args[a['name']] = obj
            decl_t = tname + ('!' if nn else '')
            decls.append(f"${a['name']}: {'[' + decl_t + ']' if lst else decl_t}")
        if not ok:
            continue
        payload_t = _type_ref(f['type'])[2]
        pfields = {x['name'] for x in (_type_fields(payload_t).get('fields') or [])} if payload_t else set()
        sel = ['userErrors { message }'] if 'userErrors' in pfields else ['__typename']
        for obj, sub in (want or {}).items():
            if obj in pfields:
                sel.append(f'{obj} {{ {sub} }}')
        q = (f"mutation Pumps({', '.join(decls)}) {{ {name}("
             f"{', '.join(a + ': $' + a for a in args)}) {{ {' '.join(sel)} }} }}")
        data = jobber_gql(q, args)
        payload = data.get(name) or {}
        errs = payload.get('userErrors') or []
        if errs:
            raise JobberError('Jobber: ' + '; '.join(e.get('message', '?') for e in errs))
        return {'mutation': name, **payload}
    return None


# ── the maintenance visit a bill is for, marked complete ─────────────────────
# A maintenance bill invoiced on the client's recurring job also completes
# that job's visit for the month the bill is for, so Jobber shows the month
# done instead of a late visit. Anything that can't be done is a to-do.

COMPLETE_VISITS = os.environ.get('PUMPS_COMPLETE_VISITS', 'true').lower() in ('1', 'true', 'yes', 'on')
VISIT_COMPLETE_MUTATIONS = ('visitComplete', 'visitMarkComplete', 'completeVisit')
_MONTH_YEAR = re.compile(r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+(20\d\d)\b', re.I)
_MONTH_ABBR = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
VISIT_SPEC = ['id', 'title', 'startAt', 'completedAt', 'visitStatus']


def bill_service_month(doc):
    """(year, month) a maintenance bill is for: the month it names ("quarterly
    maintenance ... for OCTOBER 2026"), else the bill's date's month."""
    text = ' '.join([doc.get('description') or ''] +
                    [f"{li.get('name') or ''} {li.get('description') or ''}" for li in doc.get('line_items') or []])
    m = _MONTH_YEAR.search(text)
    if m:
        return int(m.group(2)), _MONTH_ABBR.index(m.group(1).lower()[:3]) + 1
    d = _iso_date(doc.get('doc_date')) or _today().isoformat()
    return int(d[:4]), int(d[5:7])


def job_visits(job_id, pages=6):
    """A Jobber job's visits: [{id, title, date, completed}], oldest first."""
    def make(fields):
        return ('query($id: EncodedId!, $after: String) { job(id: $id) { visits(first: 50, after: $after) '
                f'{{ nodes {{ {fields} }} pageInfo {{ hasNextPage endCursor }} }} }} }}')
    out, after, spec = [], None, VISIT_SPEC
    for _ in range(pages):
        data, spec = _gql_tolerant(make, spec, {'id': job_id, 'after': after}, required=('id', 'startAt'))
        page = (data.get('job') or {}).get('visits') or {}
        out += page.get('nodes') or []
        info = page.get('pageInfo') or {}
        if not info.get('hasNextPage') or not info.get('endCursor'):
            break
        after = info['endCursor']
    return sorted(({'id': v.get('id'), 'title': v.get('title') or '', 'date': (v.get('startAt') or '')[:10],
                    'completed': bool(v.get('completedAt')) or (v.get('visitStatus') or '').lower() == 'completed'}
                   for v in out if v.get('id')), key=lambda v: v['date'])


def complete_visit_for_bill(doc, case, job, actor='system'):
    """Mark the recurring job's visit for the bill's month complete in Jobber
    (the one nearest the bill's date when the month has more than one).
    Returns what happened; never raises - a visit that can't be completed is
    a to-do to do it in Jobber."""
    if not COMPLETE_VISITS or not job or not job.get('id') or job.get('type') != 'recurring':
        return None
    year, month = bill_service_month(doc)
    label = date(year, month, 1).strftime('%B %Y')
    num = job.get('number') or ''
    cid = (case or {}).get('id')

    def pending(why):
        conn = _conn()
        try:
            add_todo(conn, f"visit-complete:{job['id']}:{year}-{month:02d}",
                     f"Mark the {label} visit complete on Jobber job #{num}", why,
                     {'case_id': cid, 'uri': job.get('uri') or ''})
            if cid:
                _event(conn, actor, 'visit not marked complete', why, case_id=cid, doc_id=doc.get('id'))
            conn.commit()
        finally:
            conn.close()
        return {'pending': why, 'month': label}

    try:
        visits = job_visits(job['id'])
    except JobberError as e:
        return pending(f"Could not read job #{num}'s visits from Jobber ({e}).")
    in_month = [v for v in visits if v['date'][:7] == f'{year:04d}-{month:02d}']
    if not in_month:
        return pending(f"Jobber job #{num} has no {label} visit.")
    todo = [v for v in in_month if not v['completed']]
    if not todo:
        return {'already_complete': True, 'month': label, 'visit': in_month[0]}
    billed = _iso_date(doc.get('doc_date'))
    near = date.fromisoformat(billed) if billed[:7] == f'{year:04d}-{month:02d}' else date(year, month, 15)
    visit = min(todo, key=lambda v: abs((date.fromisoformat(v['date']) - near).days))
    try:
        res = try_mutation(VISIT_COMPLETE_MUTATIONS, {'visitId': visit['id'], 'id': visit['id']},
                           want={'visit': 'id'})
    except JobberError as e:
        return pending(f"Jobber would not mark the {visit['date']} visit complete ({e}).")
    if res is None:
        return pending("This Jobber API version doesn't let Pumps complete visits.")
    if cid:
        conn = _conn()
        try:
            _event(conn, actor, 'visit marked complete',
                   f"{label} visit ({visit['date']}) on Jobber job #{num} {job.get('title') or ''}".strip(),
                   case_id=cid, doc_id=doc.get('id'))
            conn.commit()
        finally:
            conn.close()
    return {'completed': True, 'month': label, 'visit': visit}


# ── approval: stamp the vendor's quote, send it back, make it a job ───────────

def _pdf_text(s):
    return s.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)').encode('latin-1', 'replace').decode('latin-1')


def stamp_approved(pdf_bytes, who, when):
    """The vendor's quote with a red APPROVED box (name, date) on its first page."""
    from PyPDF2 import PdfReader, PdfWriter, PageObject
    from PyPDF2.generic import DecodedStreamObject, DictionaryObject, NameObject
    reader, writer = PdfReader(io.BytesIO(pdf_bytes)), PdfWriter()
    for i, page in enumerate(reader.pages):
        if i == 0:
            w, h = float(page.mediabox.width), float(page.mediabox.height)
            bw, bh = 240, 78
            x, y = w - bw - 24, h - bh - 24
            stamp = PageObject.create_blank_page(width=w, height=h)
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                                     NameObject('/BaseFont'): NameObject('/Helvetica-Bold')})
            stamp[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject(
                {NameObject('/FS'): font})})
            ops = (f'q 1 1 1 rg {x} {y} {bw} {bh} re f 0.78 0.1 0.1 RG 2.5 w {x} {y} {bw} {bh} re S '
                   f'0.78 0.1 0.1 rg BT /FS 24 Tf {x + 12} {y + 48} Td (APPROVED) Tj ET '
                   f'BT /FS 11 Tf {x + 12} {y + 28} Td ({_pdf_text(who)}) Tj ET '
                   f'BT /FS 11 Tf {x + 12} {y + 12} Td ({_pdf_text(when)}) Tj ET Q')
            s = DecodedStreamObject()
            s.set_data(ops.encode('latin-1'))
            stamp[NameObject('/Contents')] = s
            page.merge_page(stamp)
        writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _approved_name(file_name):
    return os.path.splitext(file_name or 'quote')[0] + ' - APPROVED.pdf'


def on_quote_approved(case_id, actor='Jobber sync'):
    """The client approved our Jobber quote: make the quote a job and put
    "Sign the quote and send it to Tom" on To do. Clicking Sign quote there
    (sign_and_send_quote) signs the vendor's Word quote, saves it here and on
    the Jobber quote, and emails it to the vendor asking when it'll be done."""
    conn = _conn()
    try:
        case = conn.execute('SELECT * FROM pump_cases WHERE id=?', (case_id,)).fetchone()
        if not case:
            return None
        case = dict(case)
        doc = _approved_quote_doc(conn, case_id)
        j = json.loads(case.get('jobber') or '{}')
        q = j.get('quote') or {}
        out = {'case_id': case_id}
        if not (doc and (doc.get('jobber') or {}).get('signed_sent_at')):
            add_sign_todo(conn, case, doc)
            out['todo'] = True
        conn.commit()
    finally:
        conn.close()
    if out.get('todo'):
        # Said straight away, not only on the Pumps page (quote 9160, Oct 2026).
        try:
            out['emailed'] = email_quote_approved(case, doc)
        except Exception as e:
            print(f'  ⚠ Pumps: approved-quote email: {e}')
    if q.get('id') and not (j.get('job') or {}).get('id'):
        out['job'] = make_job_from_quote(case_id)
    return out


def email_quote_approved(case, doc=None):
    """Email the office once per job when the client approves our quote:
    send the approved quote to the vendor and ask when it'll be scheduled."""
    import html as _html
    key = f"approved_mail:{case['id']}"
    if _state_get(key):
        return False
    name = _vendor_contact(case.get('vendor') or 'Wettech')[0]
    q = (json.loads(case.get('jobber') or '{}').get('quote') or {})
    who = case.get('client_name') or case.get('title') or f"job #{case['id']}"
    num = f" #{q['number']}" if q.get('number') else ''
    base = (CFG.get('website_url') or '').rstrip('/')
    lines = [f"{who} approved our quote{num}" + (f" (${q['total']:,.2f})" if q.get('total') else '') + '.',
             f"Next: send the approved {(doc or {}).get('vendor') or case.get('vendor') or 'vendor'} quote to {name} "
             f"and ask when it can be scheduled - \"Sign quote & send\" on the Pumps page does both, or click "
             f"\"I already sent it\" there if you've emailed it yourself."]
    links = []
    if base and 'localhost' not in base:
        links.append(f'<a href="{base}/pumps#item-{case["id"]}">Open the job in Pumps</a>')
    if q.get('uri'):
        links.append(f'<a href="{_html.escape(q["uri"])}">Quote{num} in Jobber</a>')
    html = ('<div style="font-family:Arial,sans-serif;font-size:14px">'
            + ''.join(f'<p>{_html.escape(l)}</p>' for l in lines) + ('<p>' + ' · '.join(links) + '</p>' if links else '')
            + '</div>')
    graph_send(DIGEST_TO, f"Quote{num} approved - {who}: send it to {name}"[:255], html)
    _state_set(key, {'at': _now_text(), 'to': DIGEST_TO})
    return True


def _approved_quote_doc(conn, case_id):
    row = conn.execute("SELECT * FROM pump_docs WHERE case_id=? AND kind='quote' AND status != 'dismissed' "
                       "ORDER BY id DESC", (case_id,)).fetchone()
    return {**_doc_dict(row), 'file_path': row['file_path']} if row else None


def add_sign_todo(conn, case, doc=None):
    """The to-do to sign an approved quote and send it to the vendor - once per item."""
    name, email = _vendor_contact(case.get('vendor'))
    who = case.get('client_name') or case.get('title') or f"item {case['id']}"
    num = (doc or {}).get('doc_number') or ''
    jq = (json.loads(case.get('jobber') or '{}').get('quote') or {})
    detail = (f"{who} approved our Jobber quote{(' #' + str(jq['number'])) if jq.get('number') else ''}. "
              + (f"Sign quote types \"{APPROVER} {_today().strftime('%m/%d/%Y')}\" on "
                 f"{(doc or {}).get('vendor') or 'the vendor'}'s quote{(' #' + num) if num else ''}, saves it here and "
                 f"on the Jobber quote, and emails it to {name} asking when it'll be done."
                 if doc else f"{case.get('vendor') or 'The vendor'}'s quote isn't saved on this job yet - upload it "
                 f"(or it comes in by email), then click Sign quote."))
    add_todo(conn, f"sign-quote:{case['id']}", f'Sign the approved quote and send it to {name} - {who}', detail,
             {'case_id': case['id'], 'doc_id': (doc or {}).get('id'), 'to': email}, kind='approved_quote')


_THANKS_P = re.compile(r'<w:p[ >](?:(?!</w:p>).)*?Thank\s*You(?:(?!</w:p>).)*?</w:p>', re.S | re.I)
_PARA = re.compile(r'<w:p[ >].*?</w:p>|<w:p/>', re.S)


def sign_docx(data, text):
    """Type the signature line on a vendor's Word quote the way the office does
    by hand: "Simon Weardon 10/12/2026" at the start of the line under "Thank
    You" (the line with the vendor's own signature further along it)."""
    zin = zipfile.ZipFile(io.BytesIO(data))
    xml = zin.read('word/document.xml').decode('utf-8')
    esc = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    m = _THANKS_P.search(xml)
    nxt = _PARA.search(xml, m.end()) if m else None
    if nxt:
        p = nxt.group(0)
        rpr = re.search(r'<w:r[ >](?:(?!</w:r>).)*?(<w:rPr>.*?</w:rPr>)', p, re.S)
        run = f'<w:r>{rpr.group(1) if rpr else ""}<w:t xml:space="preserve">{esc}</w:t></w:r>'
        if p == '<w:p/>':
            p2 = f'<w:p>{run}</w:p>'
        else:
            ppr = re.search(r'</w:pPr>', p)
            at = ppr.end() if ppr else p.index('>') + 1
            p2 = p[:at] + run + p[at:]
        xml = xml[:nxt.start()] + p2 + xml[nxt.end():]
    else:
        # No "Thank You": a line of its own before the "By signing..." terms, or at the end.
        new = f'<w:p><w:r><w:t xml:space="preserve">{esc}</w:t></w:r></w:p>'
        by = re.search(r'<w:p[ >](?:(?!</w:p>).)*?By\s+signing', xml, re.S)
        at = by.start() if by else xml.rindex('<w:sectPr') if '<w:sectPr' in xml else xml.rindex('</w:body>')
        xml = xml[:at] + new + xml[at:]
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            zout.writestr(item, xml.encode('utf-8') if item.filename == 'word/document.xml' else zin.read(item.filename))
    return out.getvalue()


def _signed_name(file_name):
    base, ext = os.path.splitext(file_name or 'quote.docx')
    return f"{base} - SIGNED{ext if ext.lower() in ('.docx', '.pdf') else '.pdf'}"


def make_signed_copy(doc, when=None):
    """The vendor's quote signed: a Word quote gets the signature line typed
    on it, a PDF is stamped. Returns (path, file name)."""
    when = when or _today()
    with open(doc['file_path'], 'rb') as f:
        data = f.read()
    name = doc.get('file_name') or 'quote'
    if name.lower().endswith('.docx'):
        signed = sign_docx(data, f"{APPROVER} {when.strftime('%m/%d/%Y')}")
    else:
        if not name.lower().endswith('.pdf'):
            data = pump_reports.docx_to_pdf(data)
            if not data:
                raise ValueError('The quote is an old Word file and PDF conversion is not available on this server')
            name = os.path.splitext(name)[0] + '.pdf'
        signed = stamp_approved(data, f'{APPROVER}', when.strftime('%B %d, %Y').replace(' 0', ' '))
    file_name = _signed_name(name)
    path, _ = _store_file(signed, file_name)
    return path, file_name


SIGNED_TAG = re.compile(r'\[P(\d+)\]')


def signed_quote_email(case, doc):
    name, email = _vendor_contact(case.get('vendor'))
    who = case.get('client_name') or case.get('title') or f"item {case['id']}"
    num = doc.get('doc_number') or ''
    subject = f"Signed quote - {who}{(' #' + num) if num else ''} [P{case['id']}]"
    first = (name or '').split()[0] if name else ''
    body = (f"Hi {first or 'there'},\n\nAttached is your quote{(' #' + num) if num else ''} for {who}, signed - "
            f"the client approved it. Please go ahead.\n\nWhen can we expect it to be done?\n\n"
            f"Thank you,\n{APPROVER}\nStahlman-England Irrigation")
    return {'to': email, 'name': name, 'subject': subject, 'body': body}


def sign_and_send_quote(case_id, actor, body=None, send=True):
    """Sign the approved vendor quote, keep the signed copy on the item and on
    the Jobber quote, and email it to the vendor asking when it'll be done.
    The vendor's reply is read by the mailbox scan (handle_signed_quote_reply)."""
    import html as _html
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_cases WHERE id=?', (case_id,)).fetchone()
        if not row:
            raise ValueError('No such job')
        case = dict(row)
        doc = _approved_quote_doc(conn, case_id)
    finally:
        conn.close()
    if not doc:
        raise ValueError(f"{case.get('vendor') or 'The vendor'}'s quote isn't saved on this job yet - upload it first")
    if not doc.get('file_path') or not os.path.exists(doc['file_path']):
        raise ValueError("The vendor's quote file is not on this server any more - upload it again")
    out = {'case_id': case_id, 'doc_id': doc['id']}
    dj = doc.get('jobber') or {}
    path, file_name = make_signed_copy(doc)
    dj = {**dj, 'approved_path': path, 'approved_name': file_name, 'approved_at': _now_text(), 'approved_by': APPROVER}
    dj.pop('approved_note_id', None)
    conn = _conn()
    try:
        conn.execute('UPDATE pump_docs SET jobber=? WHERE id=?', (json.dumps(dj), doc['id']))
        _event(conn, actor, 'quote signed', f'{APPROVER} - {file_name}', case_id=case_id, doc_id=doc['id'])
        conn.commit()
    finally:
        conn.close()
    doc['jobber'] = dj
    out['signed'] = file_name
    # The signed quote on our Jobber quote, so Jobber shows what was approved.
    q = (json.loads(case.get('jobber') or '{}').get('quote') or {})
    ctype = 'application/pdf' if file_name.lower().endswith('.pdf') else \
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    if q.get('id') and jobber_status()['connected']:
        try:
            note = note_vendor_file(doc, 'quote', q['id'], f"Approved - {doc.get('vendor') or 'vendor'} quote "
                                    f"{('#' + doc['doc_number']) if doc.get('doc_number') else ''} signed by "
                                    f"{APPROVER} on {_today().strftime('%m/%d/%Y')}.", version='approved',
                                    file_name=file_name, content_type=ctype)
            dj['approved_note_id'] = note['note_id']
            out['jobber_note'] = True
        except JobberError as e:
            out['note_error'] = str(e)
    if not send:
        _save_doc_jobber(doc['id'], dj)
        return out
    mail = signed_quote_email(case, doc)
    if not mail['to']:
        _save_doc_jobber(doc['id'], dj)
        raise ValueError(f"No email address is saved for {mail['name']} - the quote is signed; download it and send it yourself")
    html = ('<div style="font-family:Arial,sans-serif;font-size:14px">'
            + '<br>'.join(_html.escape(line) for line in ((body or '').strip() or mail['body']).split('\n')) + '</div>')
    with open(path, 'rb') as f:
        att = {'@odata.type': '#microsoft.graph.fileAttachment', 'name': file_name, 'contentType': ctype,
               'contentBytes': base64.b64encode(f.read()).decode()}
    try:
        graph_send(mail['to'], mail['subject'], html, [att])
    except Exception as e:
        _save_doc_jobber(doc['id'], dj)
        raise RuntimeError(f'Signed, but the email to {mail["to"]} did not go: {e} - download the signed quote and send it yourself')
    dj.update(signed_sent_at=_now_text(), signed_sent_to=mail['to'], signed_sent_by=actor)
    _save_doc_jobber(doc['id'], dj)
    conn = _conn()
    try:
        _event(conn, actor, 'signed quote emailed', f"to {mail['name']} ({mail['to']}) - asked when it'll be done",
               case_id=case_id, doc_id=doc['id'])
        for key in (f'sign-quote:{case_id}', f"approved-quote:{doc['id']}"):
            conn.execute("UPDATE pump_todos SET done_at=?, done_by=? WHERE key=? AND done_at IS NULL",
                         (_now_text(), actor, key))
        try:
            log_vendor_follow(conn, case_id, actor, who=mail['name'], how='email',
                              said='Sent the signed quote - asked when it will be done',
                              check_on=_quote_sent_check_on(case))
        except ValueError:
            pass   # not waiting on the vendor (already scheduled or done)
        conn.commit()
    finally:
        conn.close()
    out['emailed'] = mail['to']
    return out


def _quote_sent_check_on(case):
    """When to ask again after the approved quote went to the vendor: two
    workdays, or PARTS_FOLLOW_DAYS after the approval when parts take weeks."""
    check = _workdays_after(_today(), 2)
    approved = _iso_date((json.loads(case.get('steps') or '{}') if isinstance(case.get('steps'), str)
                          else (case.get('steps') or {})).get('client_approved', {}).get('at'))
    if case.get('parts_lead') and approved:
        check = max(check, _weekday_from(date.fromisoformat(approved) + timedelta(days=PARTS_FOLLOW_DAYS)))
    return check.isoformat()


def mark_quote_sent(case_id, actor, who='', how='email'):
    """The office sent the approved quote to the vendor themselves (Huntington
    #6, quote 9160, Oct 2026): the job now waits on the vendor's reply about
    when it'll be scheduled, and the "send it to Tom" to-do is done."""
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_cases WHERE id=?', (case_id,)).fetchone()
        if not row:
            raise ValueError('No such job')
        case = dict(row)
        name = (who or '').strip()[:80] or _vendor_contact(case.get('vendor') or 'Wettech')[0]
        doc = _approved_quote_doc(conn, case_id)
        if doc:
            dj = {**(doc.get('jobber') or {}), 'signed_sent_at': _now_text(), 'signed_sent_to': name,
                  'signed_sent_by': actor, 'sent_by_hand': True}
            conn.execute('UPDATE pump_docs SET jobber=? WHERE id=?', (json.dumps(dj), doc['id']))
        for key in [f'sign-quote:{case_id}'] + ([f"approved-quote:{doc['id']}"] if doc else []):
            conn.execute("UPDATE pump_todos SET done_at=?, done_by=? WHERE key=? AND done_at IS NULL",
                         (_now_text(), actor, key))
        _event(conn, actor, 'approved quote sent', f"to {name} by {how or 'email'} (sent by hand) - "
                                                    f"waiting on when it'll be scheduled", case_id=case_id)
        try:
            log_vendor_follow(conn, case_id, actor, who=name, how=how,
                              said="Sent the approved quote - asked when it'll be scheduled",
                              check_on=_quote_sent_check_on(case))
        except ValueError:
            pass   # not waiting on the vendor (already scheduled or done)
        conn.commit()
        return {'case_id': case_id, 'to': name}
    finally:
        conn.close()


def _save_doc_jobber(doc_id, dj):
    conn = _conn()
    try:
        conn.execute('UPDATE pump_docs SET jobber=? WHERE id=?', (json.dumps(dj), doc_id))
        conn.commit()
    finally:
        conn.close()


_MONTHS = ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec')
_MONTH_DAY = re.compile(r'\b(' + '|'.join(_MONTHS) + r')[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b', re.I)
_NUM_DATE = re.compile(r'\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b')


def expected_date(text, today=None):
    """The date a vendor's reply says the work will be done by ("Oct 20th",
    "10/20", "next week", "Friday"), else ''."""
    today = today or _today()
    text = text or ''
    m = _MONTH_DAY.search(text)
    if m:
        mo, dd = _MONTHS.index(m.group(1).lower()[:3]) + 1, int(m.group(2))
        try:
            d = date(today.year, mo, dd)
            if (today - d).days > 60:
                d = date(today.year + 1, mo, dd)
            return d.isoformat()
        except ValueError:
            pass
    m = _NUM_DATE.search(text)
    if m:
        mo, dd, yy = int(m.group(1)), int(m.group(2)), m.group(3)
        try:
            y = (2000 + int(yy) if len(yy) == 2 else int(yy)) if yy else today.year
            d = date(y, mo, dd)
            if not yy and (today - d).days > 60:
                d = date(y + 1, mo, dd)
            return d.isoformat()
        except ValueError:
            pass
    return due_from_text(text, today)


def _reply_text(preview):
    """The vendor's own words, not the quoted email under them."""
    return re.split(r'\n\s*(?:-{2,}|_{4,}|From:|On .{0,80}wrote:|Sent from my)', preview or '', maxsplit=1)[0].strip()


def handle_signed_quote_reply(uid, sender, subject, preview, actor='email scan'):
    """The vendor answered our signed-quote email ("[P123]" in the subject):
    keep the date they gave on the item, put it in Jobber, and follow the job.
    No date in it: a to-do to read the reply."""
    m = SIGNED_TAG.search(subject or '')
    if not m or not re.match(r'^\s*(re|fw|fwd)\s*:', subject or '', re.I):
        return None
    own = {a.lower() for a in (CFG.get('mail_from'), dive_settings().get('from')) if a}
    addr = ((re.search(r'[\w.+-]+@[\w.-]+', sender or '') or [''])[0] or '').lower()
    if addr and addr in own:
        return None
    case_id = int(m.group(1))
    said = _reply_text(preview)[:500]
    when = expected_date(said)
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_cases WHERE id=?', (case_id,)).fetchone()
        if not row:
            return None
        case = _case_dict(row)
        if conn.execute("SELECT 1 FROM pump_events WHERE case_id=? AND action='vendor replied' AND detail LIKE ?",
                        (case_id, f'%[{uid}]%')).fetchone():
            return None
        who = _vendor_contact(case.get('vendor'))[0]
        _event(conn, actor, 'vendor replied', f'{who}: "{said[:300]}"' + (f' - done by {when}' if when else '')
               + f' [{uid}]', case_id=case_id)
        if when:
            try:
                log_vendor_follow(conn, case_id, actor, who=who, how='email', said=said, expect_by=when)
            except ValueError:
                pass
            if not _iso_date(case.get('scheduled_for')) or case.get('scheduled_for') != when:
                conn.execute('UPDATE pump_cases SET scheduled_for=? WHERE id=?', (when, case_id))
        else:
            add_todo(conn, f'signed-reply:{case_id}:{uid}', f'{who} replied about {case.get("client_name") or case.get("title")} - when will it be done?',
                     f'"{said[:300]}" - no date in it. Open the job and log the date (Follow up), or ask again.',
                     {'case_id': case_id})
        conn.commit()
    finally:
        conn.close()
    out = {'case_id': case_id, 'expect_by': when}
    if when:
        out['jobber'] = note_expected_date(case_id, who, when, said)
    return out


def note_expected_date(case_id, who, when, said=''):
    """Put the vendor's date on the Jobber job (or the quote, before there is a job)."""
    conn = _conn()
    try:
        c = dict(conn.execute('SELECT * FROM pump_cases WHERE id=?', (case_id,)).fetchone())
    finally:
        conn.close()
    j = json.loads(c.get('jobber') or '{}')
    target = ('job', (j.get('job') or {}).get('id')) if (j.get('job') or {}).get('id') else \
        ('quote', (j.get('quote') or {}).get('id'))
    text = (f"{c.get('vendor') or 'Vendor'} ({who}) expects it done by "
            f"{date.fromisoformat(when).strftime('%m/%d/%Y')}." + (f' They said: "{said[:300]}"' if said else ''))
    err = ''
    if target[1] and jobber_status()['connected']:
        mutation, id_arg, input_type, field = NOTE_MUTATION[target[0]]
        try:
            data = jobber_gql(f'mutation PumpsDateNote($id: EncodedId!, $input: {input_type}!) {{ {mutation}('
                              f'{id_arg}: $id, input: $input) {{ {field} {{ id }} userErrors {{ message }} }} }}',
                              {'id': target[1], 'input': {'message': text}})
            errs = (data.get(mutation) or {}).get('userErrors') or []
            if not errs:
                conn = _conn()
                try:
                    _event(conn, 'email scan', 'date noted in Jobber', f'{target[0]} - {text}', case_id=case_id)
                    conn.commit()
                finally:
                    conn.close()
                return True
            err = '; '.join(e.get('message', '?') for e in errs)
        except JobberError as e:
            err = str(e)
    conn = _conn()
    try:
        add_todo(conn, f'date-to-jobber:{case_id}:{when}', f"Put {who}'s date in Jobber - {c.get('client_name') or c.get('title')}",
                 text + (f' (Jobber: {err})' if err else " The app couldn't add it in Jobber itself."),
                 {'case_id': case_id, 'uri': (j.get('job') or j.get('quote') or {}).get('uri') or ''})
        conn.commit()
    finally:
        conn.close()
    return False


def auto_track_approved(conn, actor='Jobber sync'):
    """Approved quotes in Jobber (the sync only reads pump, Wettech, diver,
    filter and SCADA work) that no item follows yet: follow them, so they're on
    the Jobs list and get "Sign the quote and send it to Tom". A quote the
    office typed by hand from a vendor's quote already here (Greenscapes
    #9136: "Proposal to inspect suction line", Wettech's $1,158.99 + 30%)
    joins that vendor quote's job instead of starting a new one. Returns the items."""
    since = (_today() - timedelta(days=30)).isoformat()
    out = []
    for it in untracked_jobber_items(conn):
        if it['kind'] == 'quote' and it['status'] == 'approved' \
                and (it.get('updated_at') or it.get('created_at') or '') >= since:
            cid = job_for_quote_price(conn, it)
            if cid:
                _link_item(conn, it['jobber_id'], cid, actor)
                _set_step(conn, cid, 'client_quote', at=(it['created_at'] or '')[:10] or None, by=actor)
                _set_step(conn, cid, 'client_approved', at=(it['updated_at'] or '')[:10] or None, by=actor)
            elif it.get('category') in ('pump', 'diver', 'filter', 'scada') or _tracked_account(conn, it) \
                    or _quote_is_pump_work(it['jobber_id']):
                cid = track_jobber_item(conn, it, actor)
            else:
                continue
            out.append(cid)
    return out


# Pump equipment named without the word pump: "inspect suction line", "replace the float switch".
_PUMP_HINTS = re.compile(r'\bsuction\b|\bdischarge\b|\bimpeller|\bmotors?\b|\bfloat\b|\bintake\b|'
                         r'pressure\s+(?:tank|switch|transducer)|pump\s*station|\bstation\b|\bfilters?\b|'
                         r'\bscreens?\b|\bscada\b|\bdivers?\b|\bwet\s*well|\bstarter\b|\bvfd\b|\baerat', re.I)
# Irrigation field work - valve boxes, heads, sod - that isn't ours (#8443).
_IRRIGATION_ONLY = re.compile(r'valve\s+box|sprinkler|\bsod\b|spray\s+heads?|\brotors?\b|\bdrip\b|'
                              r'\bheads?\b|\bzones?\b|landscap', re.I)
_VENDOR_WORDS = re.compile(r'\bwe?t+e?ch\b|\bwater\s+equipment\s+tech|\bgulfshore\b', re.I)


def _tracked_account(conn, it):
    """The quote is for one of the accounts we follow: on the maintenance or
    lake sheets, SCADA, or a Jobber client a site name points to (Greenscapes
    for the Carlisle)."""
    if it.get('client_id') and (
            conn.execute('SELECT 1 FROM pump_site_aliases WHERE client_id=? LIMIT 1', (it['client_id'],)).fetchone()
            or conn.execute('SELECT 1 FROM pump_maint_accounts WHERE jobber_client_id=? AND active=1 LIMIT 1',
                            (it['client_id'],)).fetchone()):
        return True
    return bool(match_account(' '.join(x for x in (it.get('client_name'), it.get('property_label')) if x), conn))


def _quote_is_pump_work(quote_id):
    """A quote whose title doesn't say so, but whose lines or notes do: the
    vendor's description of the work ("Field service to check out pump
    station...") or the vendor's quote noted on it ("Wettech quote #...")."""
    if not jobber_status()['connected']:
        return False
    texts = []
    try:
        q = fetch_quote_lines(quote_id) or {}
        texts += [f"{li.get('name') or ''} {li.get('description') or ''}" for li in q.get('line_items') or []]
    except JobberError:
        pass
    for spec in ('notes { nodes { ... on QuoteNote { message } } }', 'notes(first: 20) { nodes { message } }',
                 'notes { nodes { message } }'):
        try:
            data = jobber_gql(f'query($id: EncodedId!) {{ quote(id: $id) {{ {spec} }} }}', {'id': quote_id})
        except JobberError:
            continue
        texts += [n.get('message') or '' for n in (((data.get('quote') or {}).get('notes') or {}).get('nodes') or [])]
        break
    text = ' '.join(texts)
    return bool(_VENDOR_WORDS.search(text) or TITLE_PATTERNS['pump'].search(text))


def job_for_quote_price(conn, it):
    """The one open job, with no Jobber quote yet, whose vendor quote marked up
    the way we quote (30%, or 10% for the county) comes to this quote's total."""
    total = it.get('total')
    if not total:
        return None
    hits = []
    for c in conn.execute("SELECT id, client_name, title, jobber, vendor_quote_amount, vendor_quote_total "
                          "FROM pump_cases WHERE status='open'"):
        if (json.loads(c['jobber'] or '{}').get('quote') or {}).get('id'):
            continue
        prices = {p for p in (c['vendor_quote_amount'], c['vendor_quote_total']) if p}
        for d in conn.execute("SELECT subtotal, total FROM pump_docs WHERE case_id=? AND kind='quote' "
                              "AND status != 'dismissed'", (c['id'],)):
            prices |= {p for p in (d['subtotal'], d['total']) if p}
        pcts = (GOV_MARKUP_PCT,) if gov_client(None, {'client_name': it.get('client_name')}) else (QUOTE_MARKUP_PCT,)
        if any(abs(p * (1 + m / 100) - total) <= 1.0 for p in prices for m in pcts) and _same_client(conn, c['id'], it):
            hits.append(c['id'])
    return hits[0] if len(hits) == 1 else None


def _same_client(conn, case_id, it, by_name=False):
    """Is a Jobber record for this item's client - its Jobber client, or the name (the client's,
    or the property's)? A price alone isn't enough: Maria Peralta's $556.40 quote #9175 went on
    CORSA's SCADA renewal ($428 + 30%) (Oct 2026)."""
    c = conn.execute('SELECT client_name, site, title, jobber_client_id, jobber FROM pump_cases WHERE id=?',
                     (case_id,)).fetchone()
    if not c:
        return False
    cid = c['jobber_client_id'] or (json.loads(c['jobber'] or '{}').get('client') or {}).get('id') or ''
    if cid and it.get('client_id') and not by_name:
        return cid == it['client_id']
    theirs = f"{it.get('client_name') or ''} {it.get('property_label') or ''}"
    for name in (c['client_name'], c['site']):
        if name and (similarity(name, it.get('client_name') or '') >= 0.85 or
                     similarity(name, it.get('property_label') or '') >= 0.85 or
                     (len(_core_name(name)) >= 4 and fuzzy_has(_core_name(name), theirs))):
            return True
    return False


def _unhook_wrong_client_quotes(c, now):
    """Once (Oct 21 2026): approved quotes the sync put on another client's item by price alone
    (#9175, Maria Peralta, on CORSA's SCADA renewal) - taken off, the item back to waiting, its
    Sign-quote and Convert-quote to-dos done, the quote free to go on its own client's."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pump_jobber_items'").fetchone():
        return
    c.execute("INSERT OR IGNORE INTO pump_state (key, value) VALUES ('unhook_wrong_client_oct26', ?)", (json.dumps(now),))
    if c.rowcount != 1:
        return
    conn = c.connection
    for r in c.execute("SELECT * FROM pump_cases WHERE status='open' AND jobber LIKE '%\"quote\"%'").fetchall():
        j = json.loads(r['jobber'] or '{}')
        qid = (j.get('quote') or {}).get('id')
        it = c.execute("SELECT * FROM pump_jobber_items WHERE jobber_id=?", (qid,)).fetchone() if qid else None
        if not it or not (it['client_name'] or it['client_id']):
            continue
        by_sync = c.execute("SELECT 1 FROM pump_events WHERE case_id=? AND actor='Jobber sync' "
                            "AND action IN ('linked', 'linked Jobber') AND detail LIKE ?",
                            (r['id'], f"%{it['number']}%")).fetchone()
        # By name: the wrong link may have set the item's Jobber client from that very quote.
        if not by_sync or _same_client(conn, r['id'], dict(it), by_name=True):
            continue
        j.pop('quote', None)
        if (j.get('client') or {}).get('id') == it['client_id']:
            j.pop('client', None)
            c.execute("UPDATE pump_cases SET jobber_client_id='' WHERE id=? AND jobber_client_id=?", (r['id'], it['client_id']))
        steps = json.loads(r['steps'] or '{}')
        for k in ('client_quote', 'client_approved'):
            if (steps.get(k) or {}).get('by') == 'Jobber sync':
                steps.pop(k, None)
        c.execute('UPDATE pump_cases SET jobber=?, steps=?, updated_at=? WHERE id=?',
                  (json.dumps(j), json.dumps(steps), _now_text(), r['id']))
        c.execute('UPDATE pump_jobber_items SET case_id=NULL WHERE jobber_id=?', (qid,))
        c.execute("UPDATE pump_todos SET done_at=?, done_by='Pumps' WHERE done_at IS NULL AND key IN (?, ?)",
                  (_now_text(), f"sign-quote:{r['id']}", f"quote-to-job:{r['id']}"))
        c.execute('INSERT INTO pump_events (case_id, doc_id, at, actor, action, detail) VALUES (?,?,?,?,?,?)',
                  (r['id'], None, _now_text(), 'Pumps', 'unlinked',
                   f"Jobber quote #{it['number']} is {it['client_name']}'s, not this client's - taken off"))


def make_job_from_quote(case_id, actor='Jobber sync'):
    conn = _conn()
    try:
        case = dict(conn.execute('SELECT * FROM pump_cases WHERE id=?', (case_id,)).fetchone())
    finally:
        conn.close()
    j = json.loads(case.get('jobber') or '{}')
    q = j.get('quote') or {}
    res, err = None, ''
    if jobber_status()['connected']:
        try:
            res = try_mutation(JOB_FROM_QUOTE_MUTATIONS,
                               {'quoteId': q['id'], 'clientId': (j.get('client') or {}).get('id') or case.get('jobber_client_id'),
                                'propertyId': case.get('jobber_property_id'), 'title': case.get('title')},
                               want={'job': 'id jobNumber jobberWebUri'})
        except JobberError as e:
            err = str(e)
    conn = _conn()
    try:
        job = (res or {}).get('job') or {}
        if job.get('id'):
            j['job'] = {'id': job['id'], 'number': str(job.get('jobNumber') or ''), 'uri': job.get('jobberWebUri')}
            conn.execute('UPDATE pump_cases SET jobber=? WHERE id=?', (json.dumps(j), case_id))
            _event(conn, actor, 'quote made a job', f"Jobber job #{j['job']['number']}", case_id=case_id)
        else:
            add_todo(conn, f'quote-to-job:{case_id}', quote_to_job_title(case.get('client_name'), q.get('number')),
                     f"{case.get('client_name') or ''} approved it. " + (f'(Jobber: {err})' if err else
                     "Jobber's API can't do this one by itself."),
                     {'case_id': case_id, 'uri': q.get('uri') or ''})
        conn.commit()
    finally:
        conn.close()
    return j.get('job')


# ── the vendor's bill: our invoice at the quoted price ───────────────────────

def auto_draft_invoice(doc_id, actor='Pumps (automatic)'):
    """When the vendor's bill comes in for work we quoted, draft our Jobber
    invoice on the job at the price the client approved. A bill that doesn't
    match the vendor's quote still gets the quoted price, and a to-do to
    check with the vendor."""
    if not AUTO_DRAFT_INVOICES or not jobber_status()['connected']:
        return None
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
        doc = _doc_dict(row) if row else None
        case = dict(conn.execute('SELECT * FROM pump_cases WHERE id=?', (doc['case_id'],)).fetchone()) \
            if doc and doc.get('case_id') else None
    finally:
        conn.close()
    if not doc or not case or doc['kind'] != 'bill' or (doc.get('jobber') or {}).get('invoice_id'):
        return None
    if is_diver_bill(doc):
        return None   # billed with the pump service - see check_diver_billed
    if ((json.loads(case.get('steps') or '{}').get('invoice_drafted')) or {}).get('na'):
        return None   # nothing to invoice (a report-only account, our own technician's job...)
    j = json.loads(case.get('jobber') or '{}')
    q = j.get('quote') or {}
    if (j.get('invoice') or {}).get('id'):
        return None
    if not q.get('id'):
        # No quote of ours on the item: invoice the client's Jobber job this bill matches, at the job's price.
        try:
            # Two stations, two recurring jobs (The Carlisle): an invoice on each.
            sites = draft_site_invoices(doc_id, actor)
            if sites:
                return sites
            sugg = invoice_suggestion(doc, case)
            if not sugg.get('job'):
                return None
            visit = complete_visit_for_bill(doc, case, sugg['job'], actor)
            res = create_draft_invoice(doc_id, sugg['client_id'], sugg['line_items'], sugg['subject'],
                                       sugg['job']['id'], actor, visit_ids=_visit_ids(visit))
            invoiced_on_job(doc, case, sugg['job'], actor)
            return {**res, 'job': sugg['job'], 'visit': visit}
        except (JobberError, ValueError) as e:
            return _invoice_pending(doc_id, e)
    try:
        lines = fetch_quote_lines(q['id'])
        if not lines or not lines['line_items']:
            return {'pending': 'Could not read our quote from Jobber'}
        client_id = (j.get('client') or {}).get('id') or case.get('jobber_client_id')
        where = case.get('client_name') or ''
        subject = (doc.get('proposal_title') or case.get('title') or f'Pump service - {where}')[:255]
        gov = gov_client(doc, case)
        if gov:
            # The county is invoiced what it approved, with its PO in the subject and nothing taxed.
            subject = suggest_invoice(doc, case)['subject']
            lines['line_items'] = [{**li, 'taxable': False} for li in lines['line_items']]
        return create_draft_invoice(doc_id, client_id, lines['line_items'] if gov else whole_dollars(lines['line_items']),
                                    subject, (j.get('job') or {}).get('id') or '', actor)
    except (JobberError, ValueError) as e:
        return _invoice_pending(doc_id, e)


def _invoice_pending(doc_id, err):
    """Why the bill's invoice wasn't drafted by itself - shown on the to-do."""
    out = {'pending': str(err)}
    if isinstance(err, PossibleDuplicate):
        conn = _conn()
        try:
            row = conn.execute('SELECT jobber, case_id FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
            j = {**json.loads(row['jobber'] or '{}'),
                 'invoice_pending': {'reason': str(err), 'at': _now_text(), 'possible_duplicate': err.rec}}
            conn.execute('UPDATE pump_docs SET jobber=? WHERE id=?', (json.dumps(j), doc_id))
            _event(conn, 'Pumps', 'invoice not drafted', str(err), case_id=row['case_id'], doc_id=doc_id)
            conn.commit()
        finally:
            conn.close()
        out['possible_duplicate'] = err.rec
    return out


# ── service-call emails: a visit on the client's maintenance job ─────────────

def _account_names(conn):
    """Every name an account goes by, the maintenance sheets' names first."""
    names = []
    for sql in ('SELECT name FROM pump_maint_accounts WHERE active=1',
                'SELECT name FROM pump_dive_sites WHERE COALESCE(active, 1)=1',
                'SELECT place FROM pump_site_aliases',
                'SELECT client FROM pump_scada_accounts WHERE active=1'):
        names += [r[0] for r in conn.execute(sql) if r[0] not in names]
    return names


def _core_name(name):
    """"Carlisle (The Carlisle)" -> "Carlisle"; "Spanish Wells Lake Club" stays."""
    return re.sub(r'\s*[\(\[].*?[\)\]]', '', name or '').split(' c/o ')[0].split(' - ')[0].strip()


def match_account(text, conn=None, names=None):
    """The account a service-call email is about: the longest name it mentions."""
    own = conn is None
    conn = conn or _conn()
    try:
        best = None
        for n in (names if names is not None else _account_names(conn)):
            core = _core_name(n)
            if len(core) < 4 or not fuzzy_has(core, text):
                continue
            if best is None or len(core) > len(_core_name(best)):
                best = n
        return best
    finally:
        if own:
            conn.close()


def service_call_summary(subject, preview=''):
    s = re.sub(r'^\s*((re|fw|fwd)\s*:\s*)+', '', subject or '', flags=re.I).strip()
    return short_name(s or (preview or '').strip().split('\n')[0], 70) or 'Service call'


# Subjects of the emails this app sends: the daily email, the diver list, the
# pay-the-vendor email and approved quotes. Read back from the mailbox they are
# never a service call.
OWN_SUBJECTS = re.compile(r'^\s*((re|fw|fwd)\s*:\s*)*(pumps today\b|diver schedule\b|please pay \w+ invoice\b|'
                          r'approved\s*-\s|signed\s+quote\s*-\s|'
                          # The approval email (Oct 2026): "Quote #9152 approved - Lely: send it to Tom".
                          r'quote\s*(#\s*\d+\s*)?approved\s*-\s)', re.I)


def from_this_app(sender, subject):
    own = {a.lower() for a in (CFG.get('mail_from'), dive_settings().get('from')) if a}
    addr = (re.search(r'[\w.+-]+@[\w.-]+', sender or '') or [None])[0]
    return bool(OWN_SUBJECTS.search(subject or '')) or bool(addr and addr.lower() in own)


def _remove_own_email_service_calls(conn):
    """Undo service calls opened from the app's own daily email ("Pumps today -
    N to do") before such emails were ignored. Once."""
    conn.row_factory = sqlite3.Row
    # Again for the approval emails, which the first pass didn't know (Oct 14 2026).
    if not _claim_once(conn, 'own_email_calls_removed_2'):
        return
    for c in conn.execute("SELECT id, title FROM pump_cases WHERE source='service_call' AND status='open'").fetchall():
        if not OWN_SUBJECTS.search(re.sub(r'^Service call - ', '', c['title'] or '')):
            continue
        conn.execute("UPDATE pump_cases SET status='cancelled', updated_at=? WHERE id=?", (_now_text(), c['id']))
        conn.execute("UPDATE pump_todos SET done_at=?, done_by='Pumps' WHERE key=? AND done_at IS NULL",
                     (_now_text(), f"service-visit:{c['id']}"))
        _event(conn, 'Pumps', 'cancelled', "Opened by mistake from the app's own daily email", case_id=c['id'])
    conn.commit()


def handle_service_call_email(uid, sender, subject, preview, actor='email scan'):
    """A plain email to PO@ about a pump, lake or SCADA at one of our accounts:
    open an item and put a "Service call" visit on the client's ongoing
    maintenance job (or a to-do to add it)."""
    text = f'{subject}\n{preview}'
    if pump_reports.vendor_for(sender) or not SERVICE_WORDS.search(text) or from_this_app(sender, subject):
        return None
    conn = _conn()
    try:
        account = match_account(text, conn)
        if not account:
            return None
        if conn.execute("SELECT 1 FROM pump_cases WHERE source='service_call' AND description LIKE ?",
                        (f'%[{uid}]%',)).fetchone():
            return None
        summary = service_call_summary(subject, preview)
        cid = create_case(conn, {'title': f'Service call - {summary}', 'category': 'repair', 'client_name': account,
                                 'vendor': 'Gulfshore' if re.search(r'\b(divers?|lakes?)\b', text, re.I) else 'Wettech',
                                 'description': f'{preview[:1500]}\n\nFrom {sender} [{uid}]',
                                 'opened_on': _today().isoformat()}, actor, source='service_call')
        conn.commit()
    finally:
        conn.close()
    visit = add_service_visit(cid, account, summary, preview)
    return {'case_id': cid, 'account': account, 'visit': visit}


def add_service_visit(case_id, account, summary, detail=''):
    title = f'Service call - {summary}'
    job, err, done = None, '', None
    if jobber_status()['connected']:
        try:
            pick = pick_client(search_clients(account))
            if pick:
                jobs = client_jobs(pick['id'])['jobs']
                live = [x for x in jobs if x.get('type') == 'recurring' and x.get('status') not in ('archived',)]
                job = best_job_for_report(live, [], '', '') or (live[0] if len(live) == 1 else None)
            if job:
                done = try_mutation(VISIT_MUTATIONS, {'jobId': job['id'], 'title': title,
                                                      'instructions': (detail or '')[:2000]},
                                    want={'visit': 'id'})
        except JobberError as e:
            err = str(e)
    conn = _conn()
    try:
        if done:
            jj = json.loads(conn.execute('SELECT jobber FROM pump_cases WHERE id=?', (case_id,)).fetchone()[0] or '{}')
            jj['job'] = {'id': job['id'], 'number': str(job.get('number') or ''), 'uri': job.get('uri')}
            conn.execute('UPDATE pump_cases SET jobber=? WHERE id=?', (json.dumps(jj), case_id))
            _event(conn, 'email scan', 'service visit added', f"{title} on job #{job.get('number')}", case_id=case_id)
        else:
            where = f"job #{job['number']} ({job['title']})" if job else f"{account}'s maintenance job"
            add_todo(conn, f'service-visit:{case_id}', f'Add a "{title}" visit to {where}',
                     f'{account}. ' + (f'(Jobber: {err})' if err else "The app couldn't add it in Jobber itself."),
                     {'case_id': case_id, 'uri': (job or {}).get('uri') or ''})
        conn.commit()
    finally:
        conn.close()
    return bool(done)


# ── SCADA renewals coming due ────────────────────────────────────────────────

SCADA_QUOTE_TEXT = ('Renewal of Annual Cellular and cloud subscription for SCADA system on irrigation pump station '
                    'for {y1}-{y2}.\n\nThe SCADA Flow Shield service provides remote access to the pump station via a '
                    'cellular device inside the unit. The annual service is basic cellular service. It allows you to:'
                    '\n\n•\tAccess the pump remotely\n•\tTurn the pump on and off\n•\tCheck status of pump\n'
                    '•\tSee Pressure\n•\tSee Flow rate\n•\tSee total flow on flow meter\n'
                    '•\tSends you important alerts regarding the pump system:\n•\tOver heating\n•\tLow voltage\n'
                    '•\tHigh voltage\n•\tHigh amperage')


def _scada_client(row):
    names = [n.strip() for n in re.split(r'[;,\n]', row.get('jobber_names') or '') if n.strip()] + [row['client']]
    for n in names:
        pick = pick_client(search_clients(n))
        if pick:
            return pick
    return None


def scada_due_actions(today=None):
    """30 days before a SCADA renewal: a to-do to draft the client's renewal quote,
    with a Draft quote button - the app never drafts it by itself (the office, Oct 21
    2026: two copies of #9203 were drafted for Stock Development); or, for a
    complimentary one, just a reminder."""
    conn = _conn()
    try:
        rows = [r for r in scada_rows(conn) if r['active'] and r['state'] in ('due_soon', 'overdue')]
    finally:
        conn.close()
    # Already quoted in Jobber lately (Coras, Oct 2026): that quote is this year's - no to-do.
    found = {}
    for r in rows:
        quote = json.loads(r.get('quote') or '{}') if isinstance(r.get('quote'), str) else (r.get('quote') or {})
        if not r.get('complimentary') and quote.get('year') != (r['next_due_on'] or '')[:4]:
            try:
                found[r['id']] = existing_scada_quote(r)
            except JobberError:
                pass
    conn = _conn()
    try:
        done = []
        for r in rows:
            year = (r['next_due_on'] or '')[:4]
            key = f"scada:{r['id']}:{year}"
            if found.get(r['id']):
                q = {**found[r['id']], 'year': year}
                conn.execute('UPDATE pump_scada_accounts SET quote=? WHERE id=?', (json.dumps(q), r['id']))
                conn.execute('UPDATE pump_todos SET done_at=?, done_by=? WHERE key=? AND done_at IS NULL',
                             (_now_text(), 'Pumps', key))
                _event(conn, 'Pumps', 'SCADA quote found', f"{r['client']} {year}: Jobber quote #{q['number']} "
                                                            f"({q['status'].replace('_', ' ')}) is the renewal's")
                if q['status'] == 'draft':
                    add_todo(conn, f"scada-send:{r['id']}:{year}", f"Send the SCADA renewal quote #{q['number']} - {r['client']}",
                             f"Drafted in Jobber already. Renewal due {r['next_due_on']}.",
                             {'scada_id': r['id'], 'uri': q.get('uri') or ''}, due_on=r['next_due_on'])
                continue
            if r.get('complimentary'):
                add_todo(conn, key, f"SCADA renewal due - {r['client']} (complimentary)",
                         f"Due {r['next_due_on']}. Wettech renews it; no client quote. {r.get('notes') or ''}".strip(),
                         {'scada_id': r['id']}, due_on=r['next_due_on'])
                continue
            quote = json.loads(r.get('quote') or '{}') if isinstance(r.get('quote'), str) else (r.get('quote') or {})
            if quote.get('year') == year:
                continue
            add_todo(conn, key, f"Quote the SCADA renewal - {r['client']}",
                     f"Due {r['next_due_on']} at {r.get('our_bill') or 'their price'}. Draft quote makes it in Jobber "
                     "(nothing is drafted until you click it).",
                     {'scada_id': r['id'], 'draft_scada': year}, due_on=r['next_due_on'])
            done.append(r['client'])
        conn.commit()
    finally:
        conn.close()
    return done


SCADA_QUOTE_DAYS = 180   # a SCADA renewal quote made this long before counts for the renewal


JOB_DONE_STATUSES = ('archived', 'closed')
INVOICE_OUT = ('awaiting_payment', 'sent_not_due', 'past_due', 'paid', 'bad_debt')


def jobs_to_close():
    """One-off pump jobs we linked that are invoiced but still open in Jobber (Oct 2026: they sat open):
    a to-do each to close it, with a Close job button; done once Jobber shows it closed."""
    since = (_today() - timedelta(days=120)).isoformat()
    conn = _conn()
    try:
        cases = [dict(r) for r in conn.execute("SELECT * FROM pump_cases WHERE status != 'cancelled' AND jobber LIKE '%\"job\"%' "
                                               "AND COALESCE(updated_at, '') >= ?", (since,))]
        open_todos = {r['key']: r for r in conn.execute("SELECT * FROM pump_todos WHERE key LIKE 'close-job:%' AND done_at IS NULL")}
    finally:
        conn.close()
    want = {}
    for c in cases:
        j = json.loads(c['jobber'] or '{}')
        job, inv = j.get('job') or {}, j.get('invoice') or {}
        if job.get('id') and (inv.get('status') or '') in INVOICE_OUT:
            want[job['id']] = (c, job, inv)
    for key, t in open_todos.items():
        jid = key.split(':', 1)[1]
        want.setdefault(jid, None)
    added = []
    for jid, it in want.items():
        try:
            n = (jobber_gql('query($id: EncodedId!) { job(id: $id) { jobNumber jobStatus jobType jobberWebUri } }',
                            {'id': jid}).get('job')) or {}
        except JobberError as e:
            if not _GONE.search(str(e)):
                continue
            n = {'jobStatus': 'archived'}
        st, kind = (n.get('jobStatus') or '').lower(), (n.get('jobType') or '').lower()
        conn = _conn()
        try:
            key = f'close-job:{jid}'
            if st in JOB_DONE_STATUSES or kind == 'recurring' or not it:
                conn.execute('UPDATE pump_todos SET done_at=?, done_by=? WHERE key=? AND done_at IS NULL',
                             (_now_text(), 'Jobber sync', key))
            else:
                c, job, inv = it
                add_todo(conn, key, f"Close Jobber job #{n.get('jobNumber') or job.get('number') or '?'} - "
                                    f"{c.get('client_name') or c.get('title')}",
                         f"Our invoice #{inv.get('number') or c.get('sei_invoice_number') or '?'} has gone out "
                         f"({inv.get('status', '').replace('_', ' ')}) - nothing left to do on the job, so close it "
                         "instead of leaving it open in Jobber.",
                         {'case_id': c['id'], 'close_job': jid, 'uri': n.get('jobberWebUri') or job.get('uri') or '',
                          'label': 'Open the job in Jobber'})
                added.append(jid)
            conn.commit()
        finally:
            conn.close()
    return added


def close_jobber_job(job_id, actor):
    """Close a job in Jobber - when someone clicks Close job on its to-do."""
    res = try_mutation(('jobClose', 'closeJob'), {'jobId': job_id, 'id': job_id}, want={'job': 'id jobNumber jobStatus'})
    if res is None:
        raise ValueError("Jobber's API won't close jobs from here - close it in Jobber (Open the job in Jobber)")
    conn = _conn()
    try:
        conn.execute("UPDATE pump_jobber_items SET status='archived', synced_at=? WHERE jobber_id=?", (_now_text(), job_id))
        conn.execute('UPDATE pump_todos SET done_at=?, done_by=? WHERE key=? AND done_at IS NULL',
                     (_now_text(), actor, f'close-job:{job_id}'))
        for r in conn.execute("SELECT id FROM pump_cases WHERE jobber LIKE ?", (f'%{job_id}%',)).fetchall():
            _event(conn, actor, 'jobber job closed', f"Job #{(res.get('job') or {}).get('jobNumber') or ''} closed in Jobber",
                   case_id=r[0])
        conn.commit()
    finally:
        conn.close()
    return res.get('job') or {}


@api('/jobber/jobs/close', methods=('POST',))
@jobber_button
def h_close_jobber_job(actor):
    """Body: {"job_id"} - close that Jobber job (the Close job button on its to-do)."""
    if actor == BOT:
        return _office_only(actor, 'Closing Jobber jobs')
    return {'job': close_jobber_job(str(_json().get('job_id') or ''), actor)}


def refresh_scada_quotes():
    """Each SCADA renewal quote's status from Jobber (draft, sent, approved...), for the SCADA tab."""
    conn = _conn()
    try:
        rows = [(r['id'], json.loads(r['quote'] or '{}')) for r in conn.execute(
            "SELECT id, quote FROM pump_scada_accounts WHERE COALESCE(quote, '') LIKE '%\"id\"%'")]
    finally:
        conn.close()
    for sid, q in rows:
        if not q.get('id') or q.get('status') in ('converted', 'archived', 'rejected'):
            continue
        try:
            n = (jobber_gql('query($id: EncodedId!) { quote(id: $id) { quoteNumber quoteStatus jobberWebUri } }',
                            {'id': q['id']}).get('quote')) or {}
        except JobberError as e:
            if _GONE.search(str(e)):
                n = {'quoteStatus': 'archived'}
            else:
                continue
        st = (n.get('quoteStatus') or '').lower()
        if st and st != q.get('status'):
            q.update(status=st, uri=n.get('jobberWebUri') or q.get('uri') or '')
            conn = _conn()
            try:
                conn.execute('UPDATE pump_scada_accounts SET quote=? WHERE id=?', (json.dumps(q), sid))
                conn.commit()
            finally:
                conn.close()


def existing_scada_quote(r):
    """A SCADA renewal quote the client already has in Jobber, made in the last SCADA_QUOTE_DAYS
    days and not archived or declined (Coras, Oct 2026: quoted already, yet a to-do to quote it):
    {id, number, status, uri} or None. What the sync has seen, else Jobber's search."""
    since = (_today() - timedelta(days=SCADA_QUOTE_DAYS)).isoformat()
    names = [n.strip() for n in re.split(r'[;,\n]', r.get('jobber_names') or '') if n.strip()] + [r['client']]
    ok = lambda title, status, created, client: (
        re.search(r'\bscada\b', title or '', re.I) and (status or '').lower() not in ('archived', 'rejected')
        and (created or '')[:10] >= since and any(_same_account(n, client or '') or fuzzy_has(_core_name(n), client or '')
                                                  for n in names))
    conn = _conn()
    try:
        for it in conn.execute("SELECT * FROM pump_jobber_items WHERE kind='quote' ORDER BY created_at DESC"):
            if ok(it['title'], it['status'], it['created_at'], it['client_name']):
                return {'id': it['jobber_id'], 'number': it['number'], 'status': (it['status'] or '').lower(),
                        'uri': it['web_uri'] or ''}
    finally:
        conn.close()
    if not jobber_status()['connected']:
        return None
    for n in names:
        core = _core_name(n)
        if len(core) < 3:
            continue
        data = jobber_gql('query($q: String) { quotes(first: 20, searchTerm: $q) { nodes { id quoteNumber title '
                          'quoteStatus createdAt jobberWebUri client { name } } } }', {'q': core})
        for q in (data.get('quotes') or {}).get('nodes') or []:
            if ok(q.get('title'), q.get('quoteStatus'), q.get('createdAt'), (q.get('client') or {}).get('name')):
                return {'id': q['id'], 'number': str(q.get('quoteNumber') or ''),
                        'status': (q.get('quoteStatus') or '').lower(), 'uri': q.get('jobberWebUri') or ''}
    return None


def draft_scada_quote(scada_id, actor):
    """The renewal quote, drafted in Jobber when someone clicks Draft quote - once a year:
    clicked again (or by two people) it returns the quote already drafted."""
    with _FileLock(f'scada_quote_{scada_id}', blocking=True):
        conn = _conn()
        try:
            r = next((x for x in scada_rows(conn) if x['id'] == scada_id), None)
        finally:
            conn.close()
        if not r:
            raise ValueError('No such SCADA account')
        year = (r['next_due_on'] or '')[:4]
        quote = json.loads(r.get('quote') or '{}') if isinstance(r.get('quote'), str) else (r.get('quote') or {})
        if quote.get('year') == year and quote.get('id'):
            return {**quote, 'already': True}
        price = _money(r.get('our_bill'))
        if not price:
            raise ValueError('No price on the SCADA tab - add it there first')
        if not jobber_status()['connected']:
            raise ValueError('Jobber is not connected')
        client = _scada_client(r)
        if not client:
            raise ValueError(f"Can't tell which Jobber client {r['client']} is - set its Name in Jobber on the SCADA tab")
        props = client_jobs(client['id'])['properties']
        prop = props[0] if len(props) == 1 else next(
            (p for p in props if place_score(_core_name(r['client']), p['label']) >= 0.99), None)
        if not prop:
            raise ValueError(f"{client['name']} has {len(props)} properties - choose one in Jobber")
        y = int(year)
        items = _jobber_lines([{'name': 'Service Proposal Amount', 'description': SCADA_QUOTE_TEXT.format(y1=y, y2=y + 1),
                                'quantity': 1, 'unit_price': price, 'taxable': False}], 'quote')
        data = gql_with_lines(QUOTE_CREATE, {'attributes': {
            'clientId': client['id'], 'propertyId': prop['id'],
            'title': 'Proposal to renew the SCADA annual cellular subscription', 'lineItems': items}}, 'attributes')
        payload = data.get('quoteCreate') or {}
        if payload.get('userErrors'):
            raise JobberError('; '.join(e.get('message', '?') for e in payload['userErrors']))
        made = payload.get('quote') or {}
        ref = {'year': year, 'id': made.get('id'), 'number': str(made.get('quoteNumber') or ''),
               'uri': made.get('jobberWebUri'), 'at': _now_text(), 'by': actor, 'status': 'draft'}
        conn = _conn()
        try:
            conn.execute('UPDATE pump_scada_accounts SET quote=? WHERE id=?', (json.dumps(ref), scada_id))
            _event(conn, actor, 'SCADA quote drafted', f"{r['client']} {year}: Jobber quote #{ref['number']} ${price:,.2f}")
            conn.execute('UPDATE pump_todos SET done_at=?, done_by=? WHERE key=? AND done_at IS NULL',
                         (_now_text(), actor, f"scada:{scada_id}:{year}"))
            add_todo(conn, f"scada-send:{scada_id}:{year}", f"Send the SCADA renewal quote #{ref['number']} - {r['client']}",
                     f"Drafted in Jobber at ${price:,.2f}. Renewal due {r['next_due_on']}.",
                     {'scada_id': scada_id, 'uri': ref['uri'] or ''}, due_on=r['next_due_on'])
            conn.commit()
        finally:
            conn.close()
        return ref


@api('/scada/<int:scada_id>/draft_quote', methods=('POST',))
@jobber_button
def h_scada_draft_quote(actor, scada_id):
    """Draft the SCADA renewal quote in Jobber - only when someone in the office clicks it."""
    if actor == BOT:
        return _office_only(actor, 'Drafting quotes')
    return {'quote': draft_scada_quote(scada_id, actor)}


# ── the daily email ──────────────────────────────────────────────────────────

def graph_send(to, subject, html, attachments=None, sender=None):
    sender = sender or dive_settings()['from']
    if not (CFG.get('graph_token') and sender):
        raise RuntimeError('Microsoft 365 is not set up to send from the PO mailbox')
    msg = {'subject': subject, 'body': {'contentType': 'HTML', 'content': html},
           'toRecipients': [{'emailAddress': {'address': a}} for a in _emails(to)]}
    if attachments:
        msg['attachments'] = attachments
    r = http_requests.post(f'https://graph.microsoft.com/v1.0/users/{sender}/sendMail', timeout=60,
                           headers={'Authorization': f"Bearer {CFG['graph_token']()}", 'Content-Type': 'application/json'},
                           json={'message': msg, 'saveToSentItems': True})
    if r.status_code >= 400:
        try:
            why = (r.json().get('error') or {}).get('message') or r.text[:300]
        except ValueError:
            why = r.text[:300]
        raise RuntimeError(f'Microsoft 365 said HTTP {r.status_code}: {why}')


def build_digest(conn=None):
    own = conn is None
    conn = conn or _conn()
    try:
        q = work_queue(conn)
    finally:
        if own:
            conn.close()
    base = (CFG.get('website_url') or '').rstrip('/')
    link = f'{base}/pumps' if base else ''
    e = lambda s: (str(s or '')).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    sections = []

    def sec(title, rows):
        if rows:
            sections.append(f'<h3 style="margin:16px 0 6px;font:600 15px Arial">{e(title)} ({len(rows)})</h3><ul '
                            f'style="margin:0;padding-left:18px;font:14px Arial">' +
                            ''.join(f'<li style="margin:3px 0">{r}</li>' for r in rows) + '</ul>')
    sec('To do', [e(t['title']) + (f" <span style='color:#666'>- {e(t['detail'][:140])}</span>" if t['detail'] else '')
                  for t in q['todos']])
    sec('Pay the vendor - the client has paid', [f"{e(c['title'] or c['client_name'])} - {e(c['vendor'])} bill "
                                                 f"#{e(c.get('vendor_bill_number'))}" for c in q['vendor_bills_to_pay']])
    sec('Problems', [f"{e(i.get('title') or i.get('client_name'))}: {e(i['message'])}" for i in q['issues']])
    sec('Follow up with the vendor', [f"{e(c['title'] or c['client_name'])} - {e(c['chase']['phase'])}: "
                                      f"{e(c['chase']['reason'])}" for c in q['needs_scheduling'] + q['vendor_follow_ups']
                                      if c.get('chase')])
    sec('SCADA renewals', [f"{e(s['client_name'])} - {'overdue since' if s['state'] == 'overdue' else 'due'} "
                           f"{e(s['next_due_on'])}" for s in q['scada_attention']])
    sec('Quotes to send / waiting on the client', [e(c['title'] or c['client_name']) for c in
                                                   q['to_quote_client'] + q['waiting_approval']])
    sec('Waiting on the vendor', [e(c['title'] or c['client_name'])
                                  + (f" <span style='color:#666'>- {e(c['chase']['reason'])}, check back "
                                     f"{e(c['chase']['check_on'])}</span>" if c.get('chase') else '') for c in
                                  q['waiting_assessment'] + q['waiting_vendor_quote'] + q['scheduling_asked']
                                  + q['waiting_work'] + q['waiting_bill']])
    sec('Ready to invoice / close', [e(c['title'] or c['client_name']) for c in q['ready_to_close']])
    sec('Documents that need a look', [e(d.get('client_name') or d.get('file_name')) + f" - {e(d.get('review_reason'))}"
                                       for d in q['review_docs'][:15]])
    day = _today().strftime('%A %B %d').replace(' 0', ' ')
    body = ''.join(sections) or '<p style="font:14px Arial">Nothing needs doing today.</p>'
    html = (f'<div style="font:14px Arial;color:#111"><p>Pumps - {e(day)}. {q["open_count"]} open jobs.'
            + (f' <a href="{link}">Open Pumps</a>' if link else '') + f'</p>{body}</div>')
    n = len(q['todos']) + len(q['vendor_bills_to_pay']) + len(q['issues']) + len(q['vendor_follow_ups']) \
        + len(q['needs_scheduling'])
    return {'subject': f'Pumps today - {n} to do' if n else 'Pumps today - nothing urgent', 'html': html}


def send_digest(force=False, actor='Pumps (8am)'):
    key = f"digest:{_today().isoformat()}"
    conn = _conn()
    try:
        if not force:
            cur = conn.execute('INSERT OR IGNORE INTO pump_state (key, value) VALUES (?,?)', (key, json.dumps(_now_text())))
            conn.commit()
            if cur.rowcount == 0:
                return {'skipped': 'already sent today'}
        mail = build_digest(conn)
    finally:
        conn.close()
    try:
        graph_send(DIGEST_TO, mail['subject'], mail['html'])
    except Exception as ex:
        _state_set('digest_status', {'at': _now_text(), 'error': str(ex)})
        if not force:
            conn = _conn()
            try:
                conn.execute('DELETE FROM pump_state WHERE key=?', (key,))
                conn.commit()
            finally:
                conn.close()
        raise RuntimeError(str(ex))
    _state_set('digest_status', {'at': _now_text(), 'to': DIGEST_TO, 'error': ''})
    return {'sent': True, 'to': DIGEST_TO, 'subject': mail['subject']}


def find_parts_leads():
    """Approved jobs not yet scheduled whose parts lead hasn't been looked for:
    the vendor's quote on file, else our Jobber quote's lines ("It will take 2-3
    weeks to deliver after approval"). Looked for once per job."""
    conn = _conn()
    try:
        rows = conn.execute("SELECT * FROM pump_cases WHERE status='open' AND stage='scheduled' "
                            "AND parts_lead IS NULL").fetchall()
        found, live = {}, bool(rows) and jobber_status()['connected']
        for r in rows:
            lead = ''
            for d in conn.execute("SELECT * FROM pump_docs WHERE case_id=? AND kind='quote' AND status != 'dismissed' "
                                  "ORDER BY id DESC", (r['id'],)):
                lead = parts_lead_in(delivery_note(dict(d)))
                if lead:
                    break
            qid = (json.loads(r['jobber'] or '{}').get('quote') or {}).get('id')
            if not lead and qid:
                if not live:
                    continue   # look again once Jobber is connected
                try:
                    q = fetch_quote_lines(qid) or {}
                except JobberError:
                    continue   # try again next hour
                lead = parts_lead_in('\n'.join(li.get('description') or '' for li in q.get('line_items') or []))
            conn.execute('UPDATE pump_cases SET parts_lead=? WHERE id=?', (lead, r['id']))
            if lead:
                found[r['id']] = lead
        conn.commit()
        return found
    finally:
        conn.close()


def _scheduled_hourly():
    """Every hour: the month's diver to-do / email, SCADA renewals coming due,
    parts lead times on approved jobs, and the weekday 8am email."""
    _scheduled_dive_email()
    try:
        find_parts_leads()
    except Exception as e:
        print(f'  ⚠ Pumps: parts lead times: {e}')
    try:
        service_follow_ups()
    except Exception as e:
        print(f'  ⚠ Pumps: service follow-ups: {e}')
    try:
        scada_due_actions()
    except Exception as e:
        print(f'  ⚠ Pumps: SCADA renewals: {e}')
    now = _now()
    if now.weekday() < 5 and now.hour >= DIGEST_HOUR:
        try:
            send_digest()
        except RuntimeError as e:
            print(f'  ⚠ Pumps: daily email not sent: {e}')


@api('/digest')
def h_digest(actor):
    mail = build_digest()
    return {**mail, 'to': DIGEST_TO, 'status': _state_get('digest_status') or {}}


@api('/digest/send', methods=('POST',))
def h_digest_send(actor):
    try:
        return send_digest(force=True, actor=actor)
    except RuntimeError as e:
        return {'success': False, 'error': str(e)}, 502


@api('/cases/<int:case_id>/approved', methods=('POST',))
def h_case_approved(actor, case_id):
    """Do the approval steps now (normally the Jobber sync does them when the
    client approves the quote)."""
    conn = _conn()
    try:
        steps = json.loads((conn.execute('SELECT steps FROM pump_cases WHERE id=?', (case_id,)).fetchone() or ['{}'])[0])
        if not (steps.get('client_approved') or {}).get('at'):
            _set_step(conn, case_id, 'client_approved', at=_today().isoformat(), by=actor)
            conn.commit()
    finally:
        conn.close()
    return {'approval': on_quote_approved(case_id, actor)}


@api('/cases/<int:case_id>/sign_quote', methods=('POST',))
@jobber_button
def h_case_sign_quote(actor, case_id):
    """Sign quote: sign the vendor's approved quote, save it here and on the
    Jobber quote, and email it to the vendor asking when it'll be done.
    {"send": false} only signs it."""
    data = _json()
    try:
        return sign_and_send_quote(case_id, actor, body=data.get('body'), send=data.get('send', True) is not False)
    except ValueError as e:
        return {'success': False, 'error': str(e)}, 400
    except RuntimeError as e:
        return {'success': False, 'error': str(e)}, 502


@api('/cases/<int:case_id>/quote_sent', methods=('POST',))
def h_case_quote_sent(actor, case_id):
    """{"who", "how"}: the approved quote went to the vendor outside the app."""
    d = _json()
    return mark_quote_sent(case_id, actor, d.get('who') or '', d.get('how') or 'email')


@api('/cases/<int:case_id>/sign_quote', methods=('GET',))
def h_case_sign_quote_preview(actor, case_id):
    """The email Sign quote will send, to show before sending."""
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_cases WHERE id=?', (case_id,)).fetchone()
        if not row:
            return {'success': False, 'error': 'No such job'}, 404
        doc = _approved_quote_doc(conn, case_id)
    finally:
        conn.close()
    if not doc:
        return {'success': False, 'error': "The vendor's quote isn't saved on this job yet - upload it first"}, 400
    return {'email': signed_quote_email(dict(row), doc), 'doc': {'id': doc['id'], 'file_name': doc['file_name'],
            'signed_as': f"{APPROVER} {_today().strftime('%m/%d/%Y')}",
            'sent_at': (doc.get('jobber') or {}).get('signed_sent_at') or ''}}


# ── accounts: Wettech pumps, Gulfshore lakes and SCADA in one list ───────────

def _same_account(a, b):
    ca, cb = _core_name(a).lower(), _core_name(b).lower()
    if not ca or not cb:
        return False
    return ca == cb or similarity(ca, cb) >= 0.8 or fuzzy_has(ca, cb) or fuzzy_has(cb, ca)


def accounts(conn):
    maint = maint_accounts(conn)
    lakes = [dict(r) for r in conn.execute('SELECT * FROM pump_dive_sites ORDER BY name')]
    scada = scada_rows(conn)
    out, used_l, used_s = [], set(), set()
    for m in maint:
        lake = next((l for l in lakes if l['id'] not in used_l and _same_account(m['name'], l['name'])), None)
        if lake:
            used_l.add(lake['id'])
        out.append({'name': m['name'], 'pump': m, 'lake': lake})
    for l in lakes:
        if l['id'] not in used_l:
            out.append({'name': l['name'], 'pump': None, 'lake': l})
    for a in out:
        s = next((s for s in scada if s['id'] not in used_s and _same_account(a['name'], s['client'])), None)
        if s:
            used_s.add(s['id'])
        a['scada'] = s
        a['active'] = bool((a['pump'] and a['pump'].get('active')) or (a['lake'] and (a['lake'].get('active') if
                                                                                       a['lake'].get('active') is not None else 1)))
    # The maintenance contracts we bill: on their account, or an account of their own.
    try:
        rows = [contract_dict(r) for r in conn.execute('SELECT * FROM pump_contracts ORDER BY account, id')]
    except sqlite3.OperationalError:
        rows = []
    for a in out:
        a['contracts'] = []
    known = list(out)
    for r in rows:
        # The same name, else an existing account that's clearly it - a name from the
        # checklist only ever joins itself ("Huntington Lakes #3" isn't "#5").
        a = next((x for x in out if x['name'] == r['account']), None) or \
            next((x for x in known if _same_account(x['name'], r['account']) and
                  not re.search(r'#\s*\d', r['account'] + x['name'])), None)
        if not a:
            a = {'name': r['account'], 'pump': None, 'lake': None, 'scada': None, 'active': False, 'contracts': []}
            out.append(a)
        a['contracts'].append(r)
    for a in out:
        if any(r['status'] == 'active' for r in a['contracts']):
            a['active'] = True
    out.sort(key=lambda a: a['name'].lower())
    return out


@api('/contracts/<int:cid>', methods=('POST',))
def h_contract_update(actor, cid):
    """Body: {"month": 1-12, "billed": true|false, "year"?} ticks a month billed, or
    {"status": "active"|"cancelled"}, {"amount"}, {"notes"}."""
    d = _json()
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_contracts WHERE id=?', (cid,)).fetchone()
        if not row:
            return {'success': False, 'error': 'Not found'}, 404
        sets, vals = [], []
        if 'month' in d:
            m = int(d['month'])
            if not 1 <= m <= 12:
                raise ValueError('Month 1-12')
            billed = json.loads(row['billed'] or '{}')
            year = str(d.get('year') or _today().year)
            ms = set(int(x) for x in billed.get(year, []))
            ms.add(m) if d.get('billed', True) else ms.discard(m)
            billed[year] = sorted(ms)
            sets.append('billed=?')
            vals.append(json.dumps(billed))
        if d.get('status') in ('active', 'cancelled'):
            sets.append('status=?')
            vals.append(d['status'])
        if 'amount' in d:
            sets.append('amount=?')
            vals.append(_money(d['amount']))
        if 'notes' in d:
            sets.append('notes=?')
            vals.append(str(d['notes'])[:1000])
        if not sets:
            raise ValueError('Nothing to change')
        conn.execute(f"UPDATE pump_contracts SET {', '.join(sets)}, updated_by=?, updated_at=? WHERE id=?",
                     (*vals, actor, _now_text(), cid))
        conn.commit()
        return {'contract': contract_dict(conn.execute('SELECT * FROM pump_contracts WHERE id=?', (cid,)).fetchone())}
    finally:
        conn.close()


def account_ready(conn, name, actor='system'):
    """The client called: ready for their maintenance (Sopra, Oct 2026). The
    lake comes off hold for the diver list, and a visit is followed under
    Waiting on others until each vendor's service report comes in."""
    a = next((x for x in accounts(conn) if x['name'] == name), None)
    if not a:
        raise ValueError('No such account')
    today = _today().isoformat()
    vendors, p, l = [], a['pump'], a['lake']
    if p and p.get('active'):
        vendors.append('Wettech')
    if l and (l.get('active') if l.get('active') is not None else 1) and (l.get('needs_dive') if
                                                                          l.get('needs_dive') is not None else 1):
        vendors.append('Gulfshore')
        if l.get('status') == 'hold':
            conn.execute("UPDATE pump_dive_sites SET status='active', status_note=? WHERE id=?",
                         (f"Client approved {today}", l['id']))
    if not vendors:
        raise ValueError(f'{name} has no active pump or diver service.')
    who = ' and '.join(vendors)
    conn.execute("UPDATE pump_todos SET done_at=?, done_by=? WHERE kind='visit' AND done_at IS NULL "
                 "AND json_extract(link, '$.account')=?", (_now_text(), actor or '', name))
    conn.execute('INSERT OR REPLACE INTO pump_todos (kind, key, title, detail, due_on, link, created_by, created_at) '
                 'VALUES (?,?,?,?,?,?,?,?)',
                 ('visit', f'visit:{name}:{today}', f'{name} - maintenance visit',
                  f'Client approved {today} - {who} going out. Clears itself when their service '
                  f"report{'s come' if len(vendors) > 1 else ' comes'} in.", '',
                  json.dumps({'account': name, 'vendors': vendors, 'since': today, 'reported': []}),
                  actor or '', _now_text()))
    return {'vendors': vendors, 'unheld': bool(l and l.get('status') == 'hold' and 'Gulfshore' in vendors)}


def follow_visits(conn):
    """A maintenance visit is done once each vendor's service report for the
    account has come in since the client approved it."""
    visits = [dict(r) for r in conn.execute("SELECT * FROM pump_todos WHERE kind='visit' AND done_at IS NULL")]
    if not visits:
        return
    reports = [dict(r) for r in conn.execute(
        "SELECT vendor, client_name, site, file_name, created_at FROM pump_docs WHERE kind='report' "
        "AND status != 'dismissed'")]
    for v in visits:
        link = json.loads(v['link'] or '{}')
        got = set(link.get('reported') or [])
        for r in reports:
            if (r['created_at'] or '')[:10] < link.get('since', '') or r['vendor'] not in link.get('vendors', []):
                continue
            if _same_account(link.get('account', ''), r['client_name'] or '') or \
                    fuzzy_has(_core_name(link.get('account', '')), f"{r['site']} {r['file_name']}"):
                got.add(r['vendor'])
        if got == set(link.get('reported') or []):
            continue
        link['reported'] = sorted(got)
        done = set(link.get('vendors') or []) <= got
        conn.execute('UPDATE pump_todos SET link=?, done_at=?, done_by=? WHERE id=?',
                     (json.dumps(link), _now_text() if done else None, 'service report' if done else '', v['id']))


@api('/accounts/ready', methods=('POST',))
def h_account_ready(actor):
    """Ready - client approved: {"name": the account's name}."""
    conn = _conn()
    try:
        out = account_ready(conn, str(_json().get('name') or ''), actor)
        conn.commit()
        return out
    finally:
        conn.close()


@api('/accounts')
def h_accounts(actor):
    conn = _conn()
    try:
        rows = accounts(conn)
        month = _today().month
        follow_visits(conn)
        conn.commit()
        visits = {json.loads(r['link'] or '{}').get('account'): _todo_dict(r) for r in conn.execute(
            "SELECT * FROM pump_todos WHERE kind='visit' AND done_at IS NULL")}
        for a in rows:
            a['visit'] = visits.get(a['name'])
            a['irrigation'] = irrigation_state(conn, a['name'])
            for k in ('pump', 'lake'):
                x = a[k]
                if x:
                    ms = _month_list(x.get('months'))
                    x['due_this_month'] = bool(x.get('active', 1)) and (bool(x.get('monthly')) or
                                                                         (month in ms if ms else k == 'lake'))
        return {'accounts': rows, 'month': _today().strftime('%B')}
    finally:
        conn.close()


# ── quoting an account for a service it doesn't have ────────────────────────
# Worded like the office's own Jobber quotes (Oct 2026): Turn Leaf #8746
# "Quarterly Pump Maintenance", Coconut Landing #9162 "SCADA Annual Cellular
# subscription", Morton Grove #8903 / #7026 "Quarterly Filter Cleaning".
PUMP_PROGRAM_TEXT = (
    'We are pleased to offer this proposal for the irrigation controls and VFD maintenance at your facility'
    '{stations}.\nThe following breakdown of work to be performed with each visit to ensure the equipment is '
    'operating properly.\n\n•\tCheck and record incoming voltage\n•\tCheck and record amperage of motors\n'
    '•\tCheck and record hour meter readings\n•\tCheck and record flow meter readings\n•\tCheck motor starter '
    'conditions\n•\tVisually inspect all wires for heat damage\n•\tCheck all control devices for proper operation\n'
    '•\tDrain and clean control lines\n•\tVisually inspect all switches & indicator lights for proper operation\n'
    '•\tCheck pipes and fittings for leaks\n•\tCheck motors for excessive heat\n•\tGrease motor bearings\n'
    '•\tCheck for excessive vibration\n•\tCheck mechanical seals for leaks\n•\tCheck control valves and clean wye '
    'strainers and tubing\n•\tCheck gauges and valves\n•\tManually flush any filters\n•\tCheck hydro-pneumatic '
    'tanks for proper air pressure')
IRRIGATION_PROGRAM_TEXT = (
    '1. Maintenance checklist:\n  •\tCheck all sprinklers and adjust if needed.\n  •\tClean any clogged nozzles as needed.\n'
    '  •\tSeasonal time clock adjustments. (city and county restrictions apply.)\n  •\tCheck, adjust and replace all '
    'valves, solenoids & controllers as needed.\n  •\tMoth balls are placed in all clocks as a preventative measure.\n'
    '  •\tDetailed summary of all findings. (ie: dry spots, dying plants, unhealthy landscape.)\n  •\tPosted sign in '
    'sheet- inside time clock initialed by technician each month.\n2. No charge for any additional service calls ($95.00) '
    'for monthly maintenance customers.\n3. Extra charge for major parts only.(valves, solenoids, sprinkler heads, elec. '
    'problems etc.)\n4. Customer may terminate contract at any time.')
FILTER_PROGRAM_TEXT = ('We are pleased to quote you the following quarterly filter cleaning services:\n\n'
                       'Quarterly certified diver to inspect and thoroughly clean out lake filter and remove any debris.')
SERVICE_QUOTES = {
    'pump': {'label': 'Pump maintenance', 'title': 'Quarterly Pump Maintenance', 'line': 'QUARTERLY PUMP PROGRAM'},
    'filter': {'label': 'Filter cleaning', 'title': 'Quarterly Filter Cleaning', 'line': 'PROPOSAL AMOUNT SERVICE'},
    'scada': {'label': 'SCADA', 'title': 'Estimate for SCADA Annual Cellular subscription', 'line': 'PUMP SERVICE',
              'price': 600.0},
    # Monthly Irrigation Maintenance Program (Jobber #6824).
    'irrigation': {'label': 'Irrigation maintenance', 'title': 'Monthly Irrigation Maintenance Program',
                   'line': 'MONTHLY IRRIGATION PROGRAM'},
}
# What we charge a month per irrigation zone (the office, Oct 2026).
IRRIGATION_PER_ZONE = float(os.environ.get('PUMPS_IRRIGATION_PER_ZONE', '15') or 15)
_ZONES = re.compile(r'(\d{1,3})\s*(?:irrigation\s+|sprinkler\s+)?zones?\b|\bzones?\s*(?:count)?\s*[:#=-]?\s*(\d{1,3})\b', re.I)


def account_zones(a):
    """The number of irrigation zones written anywhere in an account's notes, or None."""
    texts = []
    for k in ('pump', 'lake', 'scada'):
        x = a.get(k) or {}
        texts += [str(x.get(f) or '') for f in ('notes', 'equipment', 'size', 'address', 'location')]
    for t in texts:
        for m in _ZONES.finditer(t):
            # "Zone 9 & 11 renovation" names zones - a count reads "24 zones" or "zones: 24".
            n = int(m.group(1) or m.group(2))
            if m.group(2) and re.search(r'\bzone\s+\d', m.group(0), re.I) and not re.search(r'[:#=]', m.group(0)):
                continue
            if 0 < n < 1000:
                return n
    return None


# A recurring job in Jobber that's ours for the pumps, lake or SCADA - not the irrigation itself.
_NOT_IRRIGATION = re.compile(r'\b(?:pumps?|fountains?|filters?|lakes?|divers?|scada|wells?|vfd|aerat\w*)\b', re.I)


def irrigation_state(conn, name):
    """Whether we manage an account's irrigation: {'managed', 'job', 'how', 'checked_at'} or {} (not checked)."""
    return _state_get(f'irrigation:{name}', conn=conn) or {}


def check_irrigation(conn, a):
    """Look in Jobber: a live recurring job at the account's site that isn't a pump,
    lake or SCADA job ("Monthly 6920.83", "Monthly Irrigation Program") means we
    manage its irrigation. A choice the office made by hand is kept."""
    name = a['name']
    was = irrigation_state(conn, name)
    if was.get('how') == 'office':
        return was
    p = a.get('pump') or {}
    cid = p.get('jobber_client_id')
    if not cid:
        pick = pick_client(search_clients(name))
        cid = pick['id'] if pick else None
    if not cid:
        out = {'managed': False, 'job': '', 'how': 'no Jobber client found', 'checked_at': _now_text()}
    else:
        every = recurring_jobs(cid)
        jobs = [j for j in every if j.get('status') != 'archived' and not _NOT_IRRIGATION.search(j.get('title') or '')]
        labels = {j.get('property_label') or '' for j in every}
        if len(labels) > 1:
            # A big client (a management company): only the jobs at this account's site.
            core = _core_name(name)
            addr = (p.get('address') or (a.get('lake') or {}).get('address') or '').lower()
            num = re.match(r'\s*(\d+)', addr)
            jobs = [j for j in jobs if place_score(core, j.get('property_label') or '') >= 0.6 or
                    (num and num.group(1) in (j.get('property_label') or ''))]
        j = jobs[0] if jobs else None
        out = {'managed': bool(j), 'job': f"#{j.get('number')} {j.get('title')}".strip() if j else '',
               'how': 'Jobber', 'checked_at': _now_text()}
    _state_set(f'irrigation:{name}', out, conn=conn)
    return out


def check_all_irrigation(force=False):
    """Once a day (with the Jobber sync), or on asking: which accounts' irrigation we manage."""
    conn = _conn()
    try:
        last = _state_get('irrigation_checked_at', conn=conn) or ''
        if not force and last[:10] == _today().isoformat():
            return 0
        n = 0
        for a in accounts(conn):
            if not a.get('active'):
                continue
            try:
                check_irrigation(conn, a)
                n += 1
            except JobberError as e:
                print(f"  ⚠ Pumps: irrigation check for {a['name']}: {e}")
            conn.commit()
        _state_set('irrigation_checked_at', _now_text(), conn=conn)
        conn.commit()
        return n
    finally:
        conn.close()


def service_quote_draft(conn, name, kind):
    """What a quote for a service an account doesn't have would say, and the
    Jobber client and property it would go to (the account's, else the clear
    match by name)."""
    if kind not in SERVICE_QUOTES:
        raise ValueError('Pick pump, filter, SCADA or irrigation')
    a = next((x for x in accounts(conn) if x['name'] == name), None)
    if not a:
        raise ValueError('No such account')
    t = SERVICE_QUOTES[kind]
    p = a.get('pump') or {}
    n = len(re.findall(r'pump', p.get('equipment') or p.get('size') or '', re.I))
    m = re.search(r'(\d+)\s*pump', f"{p.get('equipment') or ''} {p.get('size') or ''}", re.I)
    count = int(m.group(1)) if m else n
    if kind == 'pump':
        desc = PUMP_PROGRAM_TEXT.format(stations=f' for ({count}) pump stations' if count > 1 else '')
    elif kind == 'filter':
        desc = FILTER_PROGRAM_TEXT
    elif kind == 'irrigation':
        zones = account_zones(a)
        desc = IRRIGATION_PROGRAM_TEXT + (
            f'\n\nNumber of zones: {zones} at ${IRRIGATION_PER_ZONE:,.2f} per zone per month.' if zones
            else '\n\nNumber of zones undetermined.')
    else:
        y = _today().year
        desc = SCADA_QUOTE_TEXT.format(y1=y, y2=y + 1).replace('Renewal of Annual', 'Annual')
    client = {'id': p.get('jobber_client_id'), 'name': p.get('jobber_client_name')} if p.get('jobber_client_id') else None
    if not client and jobber_status()['connected']:
        try:
            client = pick_client(search_clients(name))
        except JobberError:
            client = None
    props = []
    if client and client.get('id') and jobber_status()['connected']:
        try:
            props = client_jobs(client['id'])['properties']
        except JobberError:
            props = []
    prop = props[0] if len(props) == 1 else next(
        (x for x in props if place_score(_core_name(name), x['label']) >= 0.99), None)
    price = t.get('price')
    zones = account_zones(a) if kind == 'irrigation' else None
    if zones:
        price = round(zones * IRRIGATION_PER_ZONE, 2)
    return {'account': name, 'kind': kind, 'label': t['label'], 'title': t['title'],
            'zones': zones, 'per_zone': IRRIGATION_PER_ZONE if kind == 'irrigation' else None,
            'line_items': [{'name': t['line'], 'description': desc, 'quantity': 1,
                            'unit_price': price, 'taxable': False}],
            'client': client, 'properties': props, 'property_id': (prop or {}).get('id') or ''}


@api('/accounts/service_quote')
def h_service_quote_draft(actor):
    """?name=<account>&kind=pump|filter|scada - the quote to draft, to look over."""
    conn = _conn()
    try:
        return service_quote_draft(conn, request.args.get('name') or '', request.args.get('kind') or '')
    finally:
        conn.close()


@api('/accounts/service_quote', methods=('POST',))
@jobber_button
def h_service_quote_create(actor):
    """Body: {name, kind, client_id, property_id, title, line_items} - a DRAFT quote in Jobber
    for a service the account doesn't have, and a to-do to send it."""
    if actor == BOT:
        return _office_only(actor, 'Drafting quotes')
    d = _json()
    kind = d.get('kind')
    if kind not in SERVICE_QUOTES:
        raise ValueError('Pick pump, filter or SCADA')
    if not d.get('client_id'):
        raise ValueError('Choose the Jobber client first')
    if not d.get('property_id'):
        raise ValueError("Choose the client's property first")
    lines = [li for li in d.get('line_items') or [] if (li.get('name') or li.get('description'))]
    if not lines or any(_money(li.get('unit_price')) is None for li in lines):
        raise ValueError('Put a price on the quote')
    if not jobber_status()['connected']:
        raise ValueError('Connect Jobber first')
    items = _jobber_lines(lines, 'quote')
    data = gql_with_lines(QUOTE_CREATE, {'attributes': {
        'clientId': d['client_id'], 'propertyId': d['property_id'],
        'title': (d.get('title') or SERVICE_QUOTES[kind]['title'])[:255], 'lineItems': items}}, 'attributes')
    payload = data.get('quoteCreate') or {}
    if payload.get('userErrors'):
        raise JobberError('Jobber: ' + '; '.join(e.get('message', '?') for e in payload['userErrors']))
    q = payload.get('quote') or {}
    num, uri = str(q.get('quoteNumber') or ''), q.get('jobberWebUri') or ''
    total = round(sum(i['quantity'] * i['unitPrice'] for i in items), 2)
    conn = _conn()
    try:
        add_todo(conn, f"service-quote:{q.get('id')}",
                 f"Send the {SERVICE_QUOTES[kind]['label'] if kind == 'scada' else SERVICE_QUOTES[kind]['label'].lower()} "
                 f"quote #{num} - {d.get('name') or ''}",
                 f"Drafted in Jobber at ${total:,.2f} from the Accounts tab.", {'uri': uri, 'label': 'Open the quote in Jobber'})
        _event(conn, actor, 'service quote drafted', f"{d.get('name')}: {SERVICE_QUOTES[kind]['label']} quote #{num} ${total:,.2f}")
        conn.commit()
    finally:
        conn.close()
    return {'quote': {'id': q.get('id'), 'number': num, 'uri': uri, 'status': (q.get('quoteStatus') or '').lower(),
                      'total': total}}


@bp.route('/pumps/api/accounts/export.xlsx', methods=['POST'])
def accounts_export():
    """The Accounts list as a spreadsheet - just the accounts on screen, in that order.
    Body: {"names": [...], "title": "what was selected"}."""
    if not pumps_allowed():
        return jsonify({'success': False, 'error': 'Sign in'}), 401
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    d = request.get_json(silent=True) or {}
    names = [str(n) for n in d.get('names') or []]
    conn = _conn()
    try:
        by = {a['name']: a for a in accounts(conn)}
        irr = {n: irrigation_state(conn, n) for n in names}
    finally:
        conn.close()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Accounts'
    title = (d.get('title') or 'Accounts')[:200]
    ws.append([f'Accounts - {title} - {_today().strftime("%b %d, %Y")}'])
    ws['A1'].font = Font(bold=True, size=13)
    heads = ['Account', 'Pump', 'Filter', 'SCADA', 'Irrigation', 'Contract type', 'Contract $/mo', 'Schedule / next due',
             'Address', 'Jobber client', 'Notes']
    ws.append(heads)
    for cell in ws[2]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill('solid', fgColor='BDD7EE')
    yes = lambda v: 'Yes' if v else ''
    for n in names:
        a = by.get(n)
        if not a:
            continue
        p, l, sc = a.get('pump') or {}, a.get('lake') or {}, a.get('scada') or {}
        cons = [c for c in a.get('contracts') or [] if c['status'] == 'active']
        freq = {c['frequency'] for c in cons}
        ctype = ('Monthly' if 'monthly' in freq else 'Bi-monthly' if 'bi-monthly' in freq else 'Quarterly'
                 if 'quarterly' in freq else 'Parts / as used' if cons else
                 'Cancelled' if a.get('contracts') else '')
        has_irr = (irr.get(n) or {}).get('managed') or any(c.get('irrigation') for c in cons)
        sched = []
        if p.get('active'):
            sched.append('Pump: ' + ('monthly' if p.get('monthly') else (p.get('months') or '')))
        if l and (l.get('active') if l.get('active') is not None else 1):
            sched.append('Diver: ' + (l.get('months') or 'yearly'))
        if sc.get('active'):
            sched.append('SCADA: ' + ('complimentary' if sc.get('complimentary') else f"renews {sc.get('next_due_on') or '?'}"))
        ws.append([n, yes(p.get('active')), yes(l and (l.get('active') if l.get('active') is not None else 1)),
                   ('Yes (incl.)' if sc.get('complimentary') else 'Yes') if sc.get('active') else '',
                   'Yes' if has_irr else '', ctype,
                   round(sum(c['amount'] or 0 for c in cons if c['frequency'] == 'monthly'), 2) or None,
                   '; '.join(x for x in sched if x), p.get('address') or l.get('address') or '',
                   p.get('jobber_client_name') or '', ' | '.join(x for x in (p.get('notes'), l.get('notes')) if x)])
    for col, w in zip('ABCDEFGHIJK', (34, 7, 7, 12, 10, 16, 14, 40, 40, 30, 60)):
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=3):
        row[6].number_format = '$#,##0.00'
        for c in row:
            c.alignment = Alignment(vertical='top', wrap_text=c.column in (8, 9, 11))
    ws.freeze_panes = 'A3'
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    safe = re.sub(r'[^A-Za-z0-9 _-]+', '', title).strip().replace(' ', '_')[:60] or 'all'
    return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name=f'Accounts_{safe}_{_today().isoformat()}.xlsx')


@api('/accounts/irrigation', methods=('POST',))
def h_account_irrigation(actor):
    """Body: {"name", "managed": true|false} - the office says whether we manage the account's irrigation."""
    d = _json()
    if not d.get('name'):
        raise ValueError('Which account?')
    conn = _conn()
    try:
        out = {'managed': bool(d.get('managed')), 'job': '', 'how': 'office', 'by': actor, 'checked_at': _now_text()}
        _state_set(f"irrigation:{d['name']}", out, conn=conn)
        conn.commit()
        return {'irrigation': out}
    finally:
        conn.close()


@api('/accounts/irrigation/check', methods=('POST',))
def h_account_irrigation_check(actor):
    """Look in Jobber now for every account (in the background - it takes a minute)."""
    if not jobber_status()['connected']:
        raise ValueError('Connect Jobber first')
    threading.Thread(target=_safe(check_all_irrigation), args=(True,), daemon=True).start()
    return {'started': True}


# ── an account's history: every to-do and job the client has had ────────────

def _account_aliases(a):
    """Every name one row of the Accounts list goes by."""
    names = {a['name']}
    for k, f in (('pump', 'name'), ('lake', 'name'), ('scada', 'client')):
        if a.get(k) and a[k].get(f):
            names.add(a[k][f])
    names |= {n.strip() for n in re.split(r'[;,\n]', (a.get('scada') or {}).get('jobber_names') or '') if n.strip()}
    return names


def _is_account(names, name):
    return bool(name) and any(name == n or _same_account(name, n) for n in names)


def _jobber_client_uri(client_id):
    """Jobber's web page for a client, from its API id (gid://Jobber/Client/123)."""
    try:
        n = base64.b64decode(client_id + '=' * (-len(client_id) % 4)).decode().rsplit('/', 1)[-1]
        return f'https://secure.getjobber.com/clients/{int(n)}'
    except (ValueError, UnicodeDecodeError):
        return ''


def account_history(conn, name):
    """Every to-do (open and done, however old) and every job for an account,
    newest first, plus the months its subcontractors were told of a visit."""
    a = next((x for x in accounts(conn) if x['name'] == name), None)
    if not a:
        raise ValueError('No such account')
    names = _account_aliases(a)
    found = {}
    # A quick look first: text with none of the account's words (their first
    # three letters, so "Carslie" still counts) can't be about it, and only
    # accounts whose words are in the text can be the better match. Before
    # this the page took ~25 s with a year of to-dos and Jobber records.
    def stems(n):
        return {w[:3] for w in re.findall(r'[a-z0-9]+', _core_name(n).lower()) if len(w) >= 4}
    own_stems = set().union(*(stems(n) for n in names)) if names else set()
    others = [(n, stems(n)) for n in _account_names(conn)]

    def about(text):
        if text not in found:
            low = (text or '').lower()
            if not own_stems or not any(st in low for st in own_stems):
                found[text] = False
            else:
                cands = [n for n, st in others if st and any(x in low for x in st)]
                found[text] = _is_account(names, match_account(text, conn, cands))
        return found[text]

    jobs = []
    for r in conn.execute('SELECT * FROM pump_cases ORDER BY COALESCE(opened_on, created_at) DESC, id DESC'):
        c = dict(r)
        if about(' '.join(x for x in (c['client_name'], c['title'], c['site']) if x)):
            jobs.append(c)
    job_ids = {c['id'] for c in jobs}
    events = {}
    if job_ids:
        for e in conn.execute(f"SELECT * FROM pump_events WHERE case_id IN ({','.join('?' * len(job_ids))}) "
                              'ORDER BY id DESC', list(job_ids)):
            events.setdefault(e['case_id'], []).append(dict(e))
    scada_id = (a.get('scada') or {}).get('id')
    todos = []
    for r in conn.execute('SELECT * FROM pump_todos ORDER BY created_at DESC, id DESC'):
        t = _todo_dict(r)
        link = t['link'] if isinstance(t['link'], dict) else {}
        if link.get('account'):
            mine = _is_account(names, link['account'])
        elif link.get('case_id'):
            mine = link['case_id'] in job_ids
        elif link.get('scada_id'):
            mine = link['scada_id'] == scada_id
        else:
            mine = about(f"{t['title']} {t['detail']}")
        if mine:
            todos.append(t)
    notices = [dict(r) for r in conn.execute('SELECT * FROM pump_maint_notices ORDER BY month DESC, vendor')
               if _is_account(names, r['account'])]
    # Its paperwork: the vendors' service reports, and quotes and bills on its jobs.
    docs = []
    for r in conn.execute("SELECT * FROM pump_docs WHERE status != 'dismissed' ORDER BY COALESCE(doc_date, created_at) DESC, id DESC"):
        if r['case_id'] in job_ids or (r['kind'] == 'report' and about(' '.join(x for x in (r['client_name'], r['site']) if x))):
            d = _doc_dict(r)
            docs.append({k: d.get(k) for k in ('id', 'kind', 'vendor', 'doc_number', 'doc_date', 'total', 'file_name',
                                               'case_id', 'has_branded', 'created_at')}
                        | {'signed_at': (d['jobber'] or {}).get('approved_at') or '',
                           'signed_sent_at': (d['jobber'] or {}).get('signed_sent_at') or ''})
    # Every vendor invoice for it - on its jobs, or naming it (Oct 2026: the account page shows them all).
    vendor_bills = []
    case_info = {c['id']: c for c in jobs}
    for r in conn.execute("SELECT * FROM pump_docs WHERE kind='bill' AND status != 'dismissed' "
                          "ORDER BY COALESCE(doc_date, created_at) DESC, id DESC"):
        if r['case_id'] in job_ids or about(' '.join(x for x in (r['client_name'], r['site']) if x)):
            c = case_info.get(r['case_id']) or {}
            vendor_bills.append({'id': r['id'], 'vendor': r['vendor'] or '', 'number': r['doc_number'] or '',
                                 'date': r['doc_date'] or (r['created_at'] or '')[:10], 'total': r['total'],
                                 'subtotal': r['subtotal'], 'case_id': r['case_id'], 'title': c.get('title') or '',
                                 'our_invoice': c.get('sei_invoice_number') or '', 'paid_on': c.get('vendor_paid_on') or ''})
    # Where it is in Jobber: the client, and its recurring maintenance job(s).
    client, recurring = None, []
    for r in conn.execute("SELECT * FROM pump_jobber_items WHERE client_id != '' ORDER BY updated_at DESC"):
        if not about(r['client_name'] or ''):
            continue
        if not client:
            client = {'id': r['client_id'], 'name': r['client_name'], 'uri': _jobber_client_uri(r['client_id'])}
        if r['kind'] == 'job' and r['job_type'] == 'recurring' and r['status'] not in ('archived',):
            recurring.append({'id': r['jobber_id'], 'number': r['number'], 'title': r['title'], 'uri': r['web_uri'],
                              'status': r['status']})
    p = a.get('pump') or {}
    if p.get('jobber_client_id'):
        # Linked on the Accounts tab: that client and job come first.
        client = {'id': p['jobber_client_id'], 'name': p.get('jobber_client_name') or client and client['name'] or '',
                  'uri': _jobber_client_uri(p['jobber_client_id'])}
        if p.get('jobber_job_id') and not any(r.get('id') == p['jobber_job_id'] for r in recurring):
            row = conn.execute('SELECT number, title, web_uri, status FROM pump_jobber_items WHERE jobber_id=?',
                               (p['jobber_job_id'],)).fetchone()
            recurring.insert(0, {'id': p['jobber_job_id'], 'number': row['number'] if row else '',
                                 'title': (row['title'] if row else '') or p.get('jobber_job_label') or 'Maintenance job',
                                 'uri': row['web_uri'] if row else '', 'status': row['status'] if row else ''})
    return {
        'name': a['name'],
        'account': {k: a.get(k) for k in ('pump', 'lake', 'scada', 'active')},
        'docs': docs,
        'vendor_bills': vendor_bills,
        'jobber': {'client': client, 'recurring': recurring[:4],
                   'client_ids': [x for x in dict.fromkeys([(client or {}).get('id'), (a.get('lake') or {}).get('jobber_client_id')]) if x]},
        'todos': todos,
        'jobs': [{'id': c['id'], 'title': c['title'], 'client_name': c['client_name'], 'site': c['site'],
                  'vendor': c['vendor'], 'category': c['category'], 'stage': c['stage'], 'status': c['status'],
                  'opened_on': c['opened_on'], 'closed_at': c['closed_at'], 'po_number': c['po_number'],
                  'events': events.get(c['id'], [])} for c in jobs],
        'notices': notices,
        'open_todos': sum(1 for t in todos if not t['done_at']),
    }


def client_jobber_history(client_id):
    """Everything we've done for a Jobber client, newest first: its invoices, jobs and requests."""
    out = {}
    specs = {'invoices': ['id', 'invoiceNumber', 'subject', 'invoiceStatus', 'issuedDate', 'createdAt', 'jobberWebUri',
                          ('amounts', ['total'])],
             'jobs': ['id', 'jobNumber', 'title', 'jobStatus', 'jobType', 'startAt', 'createdAt', 'total', 'jobberWebUri'],
             'requests': ['id', 'title', 'requestStatus', 'createdAt', 'jobberWebUri']}
    for conn_name, spec in specs.items():
        def make(fields, conn_name=conn_name):
            return f'query($id: EncodedId!) {{ client(id: $id) {{ id {conn_name}(first: 100) {{ nodes {{ {fields} }} }} }} }}'
        try:
            data, _ = _gql_tolerant(make, spec, {'id': client_id}, required=('id',))
        except JobberError:
            out[conn_name] = []
            continue
        nodes = (((data.get('client') or {}).get(conn_name)) or {}).get('nodes') or []
        rows = []
        for n in nodes:
            if conn_name == 'invoices':
                rows.append({'number': str(n.get('invoiceNumber') or ''), 'title': n.get('subject') or '',
                             'status': (n.get('invoiceStatus') or '').lower(),
                             'date': (n.get('issuedDate') or n.get('createdAt') or '')[:10],
                             'total': _money((n.get('amounts') or {}).get('total')), 'uri': n.get('jobberWebUri') or ''})
            elif conn_name == 'jobs':
                rows.append({'number': str(n.get('jobNumber') or ''), 'title': n.get('title') or '',
                             'status': (n.get('jobStatus') or '').lower(), 'type': (n.get('jobType') or '').lower(),
                             'date': (n.get('startAt') or n.get('createdAt') or '')[:10], 'total': _money(n.get('total')),
                             'uri': n.get('jobberWebUri') or ''})
            else:
                rows.append({'number': '', 'title': n.get('title') or '', 'status': (n.get('requestStatus') or '').lower(),
                             'date': (n.get('createdAt') or '')[:10], 'total': None, 'uri': n.get('jobberWebUri') or ''})
        out[conn_name] = sorted(rows, key=lambda x: x['date'], reverse=True)
    return out


@api('/accounts/jobber_history')
def h_account_jobber_history(actor):
    """?client_id=...&client_id=... - every invoice, job and request in Jobber for the account's client(s)."""
    if not jobber_status()['connected']:
        raise ValueError('Jobber is not connected')
    out = {'invoices': [], 'jobs': [], 'requests': []}
    for cid in request.args.getlist('client_id')[:3]:
        for k, rows in client_jobber_history(cid).items():
            out[k] += rows
    for k in out:
        out[k].sort(key=lambda x: x['date'], reverse=True)
    return out


@api('/accounts/history')
def h_account_history(actor):
    """?name=<account> - every to-do and job the client has had."""
    conn = _conn()
    try:
        return account_history(conn, (request.args.get('name') or '').strip())
    finally:
        conn.close()


@api('/accounts/todo', methods=('POST',))
def h_account_todo(actor):
    """A to-do of your own about an account: {"name", "title", "detail", "due_on"}."""
    d = _json()
    name, title = str(d.get('name') or '').strip(), str(d.get('title') or '').strip()
    if not title:
        raise ValueError('Say what needs doing')
    conn = _conn()
    try:
        if not any(a['name'] == name for a in accounts(conn)):
            raise ValueError('No such account')
        conn.execute('INSERT INTO pump_todos (kind, title, detail, due_on, link, created_by, created_at) '
                     'VALUES (?,?,?,?,?,?,?)', ('manual', title[:300], str(d.get('detail') or '')[:2000],
                                                _iso_date(d.get('due_on')), json.dumps({'account': name}), actor,
                                                _now_text()))
        conn.commit()
        return account_history(conn, name)
    finally:
        conn.close()


# ── the month's maintenance and whether each subcontractor has been told ────
# Wettech does the pump maintenance, Gulfshore (the diver) the lakes. A lake on
# the month's diver list counts as told once that list's email has gone; a
# pump visit counts once someone marks it (or emails Tom from the Home tab).

def _month_arg(text, today=None):
    """"2026-11" (or a date) -> date(2026, 11, 1); else this month."""
    m = re.match(r'(\d{4})-(\d{2})', str(text or ''))
    if m and 1 <= int(m.group(2)) <= 12:
        return date(int(m.group(1)), int(m.group(2)), 1)
    return (today or _today()).replace(day=1)


def maint_schedule(conn, month_date):
    """Every maintenance visit due in a month, one row per account and vendor."""
    key = month_date.strftime('%Y-%m')
    nxt = (month_date + timedelta(days=32)).replace(day=1)
    notices = {(r['account'], r['vendor']): dict(r) for r in
               conn.execute('SELECT * FROM pump_maint_notices WHERE month=?', (key,))}
    dive_mail = conn.execute("SELECT sent_at, sent_by, to_addr FROM pump_dive_emails WHERE month=? AND "
                             "COALESCE(error, '')='' ORDER BY id LIMIT 1", (key,)).fetchone()
    visits = [json.loads(r['link'] or '{}') for r in conn.execute("SELECT link FROM pump_todos WHERE kind='visit'")]
    reports = [dict(r) for r in conn.execute(
        "SELECT vendor, client_name, site, file_name, created_at FROM pump_docs WHERE kind='report' "
        "AND status != 'dismissed' AND created_at >= ? AND created_at < ?", (key, nxt.isoformat()))]
    dive_ids = {s['id'] for s in sites_for_month(conn, month_date)}
    rows = []
    for a in accounts(conn):
        due = []
        p, l = a['pump'], a['lake']
        if p and p.get('active') and (p.get('monthly') or month_date.month in _month_list(p.get('months'))):
            due.append(('Wettech', p.get('equipment') or p.get('kind') or 'Pump', p.get('address') or '', ''))
        if l and l['id'] in dive_ids:
            due.append(('Gulfshore', l.get('equipment') or 'Lake', l.get('address') or '',
                        'on hold - ' + (l.get('status_note') or 'waiting on the client') if l.get('status') == 'hold'
                        else ''))
        names = _account_aliases(a)
        for vendor, what, where, hold in due:
            n = notices.get((a['name'], vendor))
            if not n and vendor == 'Gulfshore' and dive_mail:
                n = {'notified_at': dive_mail['sent_at'], 'notified_by': dive_mail['sent_by'],
                     'how': f"diver list emailed to {dive_mail['to_addr']}", 'note': '', 'auto': True}
            approved = next((v.get('since') for v in visits if vendor in (v.get('vendors') or [])
                             and key <= (v.get('since') or '') < nxt.isoformat()
                             and _is_account(names, v.get('account'))), '')
            report = next((r['created_at'][:10] for r in reports if r['vendor'] == vendor and (
                _is_account(names, r['client_name']) or
                fuzzy_has(_core_name(a['name']), f"{r['site']} {r['file_name']}"))), '')
            rows.append({'account': a['name'], 'vendor': vendor, 'what': what, 'where': where, 'hold': hold,
                         'notified': n, 'approved': approved, 'report': report})
    rows.sort(key=lambda r: (bool(r['notified']), r['vendor'], r['account'].lower()))
    return rows


def _notify_mailto(month_date, rows):
    """A ready email to Tom listing the month's pump visits he hasn't been told of."""
    from urllib.parse import quote
    todo = [r for r in rows if r['vendor'] == 'Wettech' and not r['notified']]
    if not todo:
        return ''
    label = month_date.strftime('%B %Y')
    body = '\n'.join(['Hi Tom,', '', f'These pump maintenance visits are due in {label}:', ''] +
                     [f"- {r['account']} ({r['what']})" + (f" - {r['where']}" if r['where'] else '') for r in todo] +
                     ['', 'Please put them on your schedule and send the service reports when done.', '', 'Thank you,',
                      'Stahlman-England Irrigation'])
    return f"mailto:{_vendor_email('Wettech')}?subject={quote(f'{label} pump maintenance')}&body={quote(body)}"


def _schedule_payload(conn, month_date):
    rows = maint_schedule(conn, month_date)
    return {'month': month_date.strftime('%Y-%m'), 'label': month_date.strftime('%B %Y'), 'rows': rows,
            'notified': sum(1 for r in rows if r['notified']), 'total': len(rows),
            'wettech_mailto': _notify_mailto(month_date, rows)}


@api('/maint/schedule')
def h_maint_schedule(actor):
    """?month=YYYY-MM (default this month): every maintenance visit due, and
    whether Wettech / Gulfshore has been told."""
    conn = _conn()
    try:
        return _schedule_payload(conn, _month_arg(request.args.get('month')))
    finally:
        conn.close()


@api('/maint/notified', methods=('POST',))
def h_maint_notified(actor):
    """{"month": "YYYY-MM", "vendor", "accounts": [names] (or "account"),
    "notified": true|false, "how": "email"/"phone"/..., "note"}."""
    d = _json()
    month_date = _month_arg(d.get('month'))
    vendor = str(d.get('vendor') or '').strip()
    if vendor not in ('Wettech', 'Gulfshore'):
        raise ValueError('Which subcontractor?')
    names = [str(n).strip() for n in (d.get('accounts') or [d.get('account')]) if str(n or '').strip()]
    if not names:
        raise ValueError('Which account?')
    key, on = month_date.strftime('%Y-%m'), d.get('notified', True) not in (False, 0, '0', 'false')
    conn = _conn()
    try:
        for n in names:
            if on:
                conn.execute('INSERT OR REPLACE INTO pump_maint_notices (month, account, vendor, how, note, '
                             'notified_by, notified_at) VALUES (?,?,?,?,?,?,?)',
                             (key, n, vendor, str(d.get('how') or '')[:100], str(d.get('note') or '')[:1000],
                              actor or '', _now_text()))
            else:
                conn.execute('DELETE FROM pump_maint_notices WHERE month=? AND account=? AND vendor=?',
                             (key, n, vendor))
        _event(conn, actor, f"{vendor} {'told' if on else 'not told'} of {month_date.strftime('%B')} maintenance",
               ', '.join(names))
        conn.commit()
        return _schedule_payload(conn, month_date)
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════════════════════
# pages and the Jobber sign-in
# ═════════════════════════════════════════════════════════════════════════════

@bp.route('/pumps')
def page():
    if not pumps_allowed():
        return redirect(url_for('login'))
    return render_template_string(PUMPS_PAGE,
                                  full_name=session.get('full_name', session.get('username', '')),
                                  steps=[{'key': k, 'label': l} for k, l in STEPS],
                                  categories=CATEGORIES,
                                  jobber=jobber_status(),
                                  claude=USE_CLAUDE,
                                  claude_problem=(_state_get('claude_problem') or {}).get('problem', ''),
                                  email=bool(CFG.get('email_enabled')),
                                  openclaw=bool(OPENCLAW_API_KEY),
                                  markup=MARKUP_PCT,
                                  scada_days=SCADA_DUE_SOON_DAYS, digest_to=DIGEST_TO, digest_hour=DIGEST_HOUR,
                                  flash_msg=request.args.get('msg', ''), app_version=APP_VERSION)


@bp.route('/pumps/f/<int:doc_id>/<version>/<int:exp>/<sig>')
@bp.route('/pumps/f/<int:doc_id>/<version>/<int:exp>/<sig>/<path:name>')
def signed_file(doc_id, version, exp, sig, name=''):
    """Short-lived link Jobber uses to fetch a report it is attaching to a note."""
    if not (version in ('branded', 'branded_pdf', 'original', 'approved') or re.fullmatch(r'section\d{1,2}', version)) \
            or not _check_signed(doc_id, version, exp, sig):
        return 'Link expired', 403
    out = _send_doc_file(doc_id, version)
    if isinstance(out, tuple):
        return 'Not found', 404
    return out


def _callback_url():
    if JOBBER_CALLBACK_URL:
        return JOBBER_CALLBACK_URL
    base = (CFG.get('website_url') or '').rstrip('/')
    if not base or 'localhost' in base:
        base = request.url_root.rstrip('/')
    return base + '/pumps/jobber/callback'


@bp.route('/pumps/jobber/connect')
def jobber_connect():
    if not pumps_allowed():
        return redirect(url_for('login'))
    if not (JOBBER_CLIENT_ID and JOBBER_CLIENT_SECRET):
        return redirect(url_for('pumps.page', msg='Set PUMPS_JOBBER_CLIENT_ID and PUMPS_JOBBER_CLIENT_SECRET first (see PUMPS_README.md).'))
    import secrets
    from urllib.parse import urlencode
    state = secrets.token_urlsafe(24)
    session['pumps_jobber_state'] = state
    return redirect(JOBBER_AUTHORIZE + '?' + urlencode({'response_type': 'code', 'client_id': JOBBER_CLIENT_ID,
                                                        'redirect_uri': _callback_url(), 'state': state}))


@bp.route('/pumps/jobber/callback')
def jobber_callback():
    if not pumps_allowed():
        return redirect(url_for('login'))
    expected = session.pop('pumps_jobber_state', None)
    if not expected or not hmac.compare_digest(expected, request.args.get('state', '')):
        return redirect(url_for('pumps.page', msg='The Jobber sign-in could not be verified - try Connect Jobber again.'))
    if request.args.get('error') or not request.args.get('code'):
        return redirect(url_for('pumps.page', msg=f"Jobber did not connect: {request.args.get('error_description') or request.args.get('error') or 'no code'}"))
    try:
        tok = _token_request({'grant_type': 'authorization_code', 'code': request.args['code'],
                              'redirect_uri': _callback_url()})
    except JobberError as e:
        return redirect(url_for('pumps.page', msg=str(e)))
    _save_tokens({'access_token': tok['access_token'], 'refresh_token': tok.get('refresh_token'),
                  'obtained_at': time.time(), 'connected_by': session.get('full_name') or session['username'],
                  'connected_at': _now_text()[:16]})
    if CFG.get('log_activity'):
        CFG['log_activity'](session['username'], 'PUMPS_JOBBER_CONNECT', 'pumps', None, 'Connected Jobber')
    start_jobber_sync(full=True, actor=session.get('username'))
    return redirect(url_for('pumps.page', msg='Jobber is connected. The first sync of pump work takes a few minutes.'))


@bp.route('/pumps/jobber/disconnect', methods=['POST'])
def jobber_disconnect():
    if not pumps_allowed():
        return jsonify({'success': False}), 401
    _save_tokens({})
    return jsonify({'success': True})


@bp.route('/api/openclaw/pumps', methods=['POST'])
def openclaw_intake():
    """The preview's free-text intake, kept for OpenClaw: {"request": "..."}
    becomes a tracked item. It no longer touches Jobber - drafting happens from
    a bill, through /api/pumps/docs/<id>/invoice."""
    if not _bearer_ok():
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    text = ((request.get_json(silent=True) or {}).get('request') or '').strip()
    if not text:
        return jsonify({'success': False, 'error': 'Missing "request"'}), 400
    x = _clean_extraction(_claude_extract(text, subject='Request from OpenClaw') or {'description': text})
    conn = _conn()
    try:
        cid = create_case(conn, {'title': (x.get('description') or text)[:160], 'category': x.get('category'),
                                 'client_name': x.get('client_name') or '', 'site': x.get('site') or '',
                                 'po_number': x.get('po_number') or '', 'vendor': x.get('vendor') or '',
                                 'description': text}, 'OpenClaw', source='openclaw')
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': True, 'case_id': cid})


# ═════════════════════════════════════════════════════════════════════════════
# wiring
# ═════════════════════════════════════════════════════════════════════════════

def init_pumps(app, csrf, db_path, *, data_dir, secret_key, website_url, email_enabled, fetch_emails,
               graph_attachments, email_attachments, log_activity=None, scheduler_available=True,
               graph_token=None, mail_from=''):
    CFG.update(db_path=db_path, data_dir=data_dir, secret_key=secret_key, website_url=website_url,
               email_enabled=email_enabled, fetch_emails=fetch_emails, graph_attachments=graph_attachments,
               email_attachments=email_attachments, log_activity=log_activity, graph_token=graph_token,
               mail_from=mail_from)
    init_db()
    _register_routes(app, csrf)
    csrf.exempt(openclaw_intake)
    app.register_blueprint(bp)
    if scheduler_available and AUTO_SCAN:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            sched = BackgroundScheduler()
            if email_enabled:
                sched.add_job(_safe(scan_mailbox), 'interval', minutes=SCAN_EVERY_MIN, id='pumps_mail_scan',
                              next_run_time=datetime.now() + timedelta(minutes=2))
            sched.add_job(_safe(_scheduled_jobber_sync), 'interval', minutes=JOBBER_SYNC_EVERY_MIN,
                          id='pumps_jobber_sync', next_run_time=datetime.now() + timedelta(minutes=2))
            sched.add_job(_safe(check_quote_approvals), 'interval', minutes=QUOTE_CHECK_EVERY_MIN,
                          id='pumps_quote_check', next_run_time=datetime.now() + timedelta(minutes=1))
            sched.add_job(_safe(_scheduled_hourly), 'interval', hours=1, id='pumps_hourly',
                          next_run_time=datetime.now() + timedelta(minutes=3))
            sched.start()
            print(f'✓ Pumps: mailbox scan every {SCAN_EVERY_MIN} min' if email_enabled else
                  'ℹ Pumps: mailbox not configured - no automatic scan')
        except Exception as e:
            print(f'⚠ Pumps scheduler did not start: {e}')


QUOTE_CHECK_EVERY_MIN = max(2, int(os.environ.get('PUMPS_QUOTE_CHECK_MINUTES', '5') or 5))


def check_quote_approvals(actor='Jobber sync'):
    """Our open quotes read straight from Jobber every few minutes, apart from
    the full sync (Huntington #5 and #6, quotes 9149 and 9160, Oct 2026: the
    full sync is long, and a restart part way never reached the approvals).
    Ticks sent / approved, and an approval gets its to-do and email. Returns
    the jobs just approved."""
    if not jobber_status()['connected']:
        return []
    with _FileLock('quote_check', blocking=False) as got:
        if not got:
            return []
        conn = _conn()
        try:
            errors = _refresh_linked_records(conn, kinds=('quote',))
            approved = _follow_quotes(conn)
            conn.commit()
        finally:
            conn.close()
        for e in errors:
            print(f'  ⚠ Pumps: quote check: {e}')
        for cid in approved:
            try:
                on_quote_approved(cid, actor)
            except Exception as e:
                print(f'  ⚠ Pumps: approved quote (item {cid}): {e}')
        return approved


def _scheduled_jobber_sync():
    if jobber_status()['connected']:
        sync_jobber(False, 'schedule')
