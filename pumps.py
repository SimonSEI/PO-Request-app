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
import difflib
import hashlib
import hmac
import io
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests as http_requests
from flask import (Blueprint, Response, jsonify, redirect, render_template_string, request, send_file,
                   session, url_for)

import pump_reports
from pumps_page import PUMPS_PAGE

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
# A vendor quote that is read cleanly and filed is drafted as our client
# quote in Jobber straight away (a draft - the office still sends it).
AUTO_DRAFT_QUOTES = os.environ.get('PUMPS_AUTO_DRAFT_QUOTES', 'true').lower() in ('1', 'true', 'yes', 'on')
# A rebranded service report is put on the site's pump job in Jobber as a
# note ("October Pump Maintenance" + the PDF) as soon as it arrives, when the
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
                               'requestCreateNote', 'quoteCreateNote',
                               # An approved quote made a job, and a service-call visit on a job (Oct 2026).
                               'jobCreate', 'visitCreate', 'jobAddVisit', 'jobCreateVisit', 'jobVisitCreate'})

# What counts as pump work when searching Jobber, by category.
JOBBER_TERMS = {
    'pump': ['pump', 'fountain', 'wettech', 'wttech', 'wetech', 'lift station', 'vfd'],
    'diver': ['diver'],
    'filter': ['filter'],
    'scada': ['scada'],
}
TITLE_PATTERNS = {
    'scada': re.compile(r'\bscada\b', re.I),
    'diver': re.compile(r'\bdivers?\b', re.I),
    'filter': re.compile(r'\bfilters?\b', re.I),
    'pump': re.compile(r'\bpumps?\b|\bfountains?\b|\bwe?t+e?ch\b|\bwet\*|\blift\s+station\b|\bvfd\b|\bwell\s+pump\b', re.I),
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
    return conn


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


def similarity(a, b):
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    contain = inter / len(ta)
    jacc = inter / len(ta | tb)
    return round(0.7 * contain + 0.3 * jacc, 3)


def _vendor_display(text):
    v = pump_reports.vendor_for(text)
    return v.get('display') if v else ''


def _vendor_profile(name):
    for v in pump_reports.load_vendors():
        if (name or '').lower() in [v.get('display', '').lower(), v.get('key', '').lower()]:
            return v
    return pump_reports.vendor_for(name or '') or {}


def _vendor_email(vendor_name):
    v = _vendor_profile(vendor_name)
    return v.get('contact_email') or os.environ.get('PUMPS_VENDOR_EMAIL', 'office@wettec.biz')


# ═════════════════════════════════════════════════════════════════════════════
# database
# ═════════════════════════════════════════════════════════════════════════════

# What the office told us (Oct 2026) about one account's names.
SEED_SITE_ALIASES = [
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
    for a in SEED_SITE_ALIASES:
        # A seed fills in a name the office saved without its property.
        c.execute("UPDATE pump_site_aliases SET property_id=?, property_label=? WHERE place=? AND area=? AND "
                  "client_id=? AND COALESCE(property_id, '')='' AND ?!=''",
                  (a['property_id'], a['property_label'], a['place'], a['area'], a['client_id'], a['property_id']))
        if a.get('job_id'):
            c.execute("UPDATE pump_site_aliases SET job_id=?, job_label=? WHERE place=? AND area=? AND "
                      "COALESCE(job_id, '')=''", (a['job_id'], a['job_label'], a['place'], a['area']))
    # When the vendor's bill was paid, and who said so (added after launch).
    for col in ('vendor_paid_on', 'vendor_paid_by', 'closed_by_hand'):
        try:
            c.execute(f"ALTER TABLE pump_cases ADD COLUMN {col} TEXT DEFAULT ''")
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
    conn.commit()
    _migrate_old_sheet(conn)
    _backfill_visit_step(conn)
    _remove_own_email_service_calls(conn)
    _dedupe_startup_events(conn)
    conn.close()


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
    steps = _with_optional(steps)
    for k in STEP_KEYS:
        s = steps.get(k) or {}
        if not s.get('at') and not s.get('na'):
            return k
    return 'done'


def _case_dict(row, conn=None):
    d = dict(row)
    for k in ('jobber', 'steps'):
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
    if conn is not None:
        d['open_issues'] = [dict(r) for r in conn.execute(
            'SELECT * FROM pump_issues WHERE case_id=? AND resolved_at IS NULL ORDER BY id', (d['id'],))]
    return d


def vendor_pay_state(case):
    """Whether the vendor's bill is paid. 'due' once the client has paid our
    Jobber invoice and the vendor has not been paid yet."""
    has_bill = (case.get('vendor_bill_amount') is not None or case.get('vendor_bill_total') is not None
                or bool(((case.get('steps') or {}).get('vendor_bill') or {}).get('at')))
    client_status = (((case.get('jobber') or {}).get('invoice') or {}).get('status') or '').lower()
    if case.get('vendor_paid_on'):
        state = 'paid'
    elif not has_bill:
        state = ''
    elif client_status == 'paid':
        state = 'due'
    else:
        state = 'unpaid'
    return {'state': state, 'paid_on': case.get('vendor_paid_on') or '', 'paid_by': case.get('vendor_paid_by') or '',
            'client_invoice_status': client_status}


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
    row = conn.execute('SELECT steps, status, COALESCE(closed_by_hand, \'\') AS by_hand FROM pump_cases WHERE id=?',
                       (case_id,)).fetchone()
    if not row:
        return
    if row['status'] == 'closed' and row['by_hand']:
        return   # marked done by the office: stays done until reopened
    try:
        steps = json.loads(row['steps'] or '{}')
    except (TypeError, ValueError):
        steps = {}
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
    return {'name': name, 'notes': '\n'.join(dict.fromkeys(n.strip() for n in notes if n.strip()))}


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


def _regex_extract(text, sender='', subject=''):
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
    out['tax_included'] = bool(re.search(r'\b(?:price|cost)s?\s+includes?\s+(?:the\s+)?sales\s+tax', text, re.I))
    if out['line_items'] or out['total'] is None:
        return
    m = re.search(r'following\s+(?:services|work|items?)[^\n]*\n(.+?)\n\s*(?:your|total)\s+(?:cost|price)', text,
                  re.I | re.S)
    work = re.sub(r'\s+', ' ', m.group(1)).strip() if m else ''
    if work:
        out['description'] = work[:300]
    out['line_items'] = [{'name': short_name(work) or 'Pump service', 'description': work, 'quantity': 1.0,
                          'unit_price': out['total'], 'amount': out['total'],
                          'taxable': not out['tax_included'], 'is_tax': False}]


def short_name(text, limit=60):
    """First clause of a line item, cut on a word boundary."""
    first = re.split(r'[,.;]\s', (text or '').strip() + ' ')[0].strip()
    if len(first) <= limit:
        return first
    cut = first[:limit].rsplit(' ', 1)[0]
    return cut.rstrip(' -,') or first[:limit]


def _clean_extraction(x):
    x = dict(x or {})
    x['kind'] = x.get('kind') if x.get('kind') in ('quote', 'bill', 'report', 'other') else 'other'
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
        if x['total'] is None and len(items) == 1 and items[0].get('amount') is not None:
            x['total'] = items[0]['amount']
        if x['subtotal'] is not None and x['tax'] is None and x['total'] is None:
            x['total'], x['subtotal'] = x['subtotal'], None
        if x['tax'] is None:
            x['subtotal'] = None
        if 'includes sales tax' not in (x.get('notes') or '').lower():
            x['notes'] = ((x.get('notes') or '') + ' Price includes sales tax.').strip()
    elif x['subtotal'] is None:
        priced = [i['amount'] for i in items if not i['is_tax'] and i.get('amount') is not None]
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

def _find_case_for(conn, doc):
    """Best open item for a document, with how it was matched; (None, '') if none."""
    po = po_key(doc.get('po_number'))
    rows = [dict(r) for r in conn.execute("SELECT * FROM pump_cases WHERE status='open'")]
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
    best, best_score = None, 0.0
    for r in rows:
        score = max(similarity(name, r.get('client_name') or r.get('title') or ''),
                    similarity(name, r.get('title') or ''))
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
        if score > best_score:
            best, best_score = r, score
    if best and best_score >= 0.85:
        return best['id'], f"client name ({best.get('client_name') or best.get('title')})"
    return None, ''


def file_document(conn, doc_id, actor='system'):
    """Put a document on its item (finding or creating one) and do what that
    kind of document means for the item. Returns the item id."""
    doc = dict(conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone())
    kind = doc['kind']
    if kind == 'other' or doc['status'] == 'dismissed':
        return None
    case_id, how = (doc['case_id'], 'already linked') if doc['case_id'] else _find_case_for(conn, doc)
    if not case_id:
        title = doc.get('description') or ''
        if kind == 'report':
            rf = json.loads(doc.get('report_fields') or '{}')
            title = f"{(rf.get('title') or 'Pump report').title()} - {doc.get('client_name') or ''}".strip(' -')
        if kind != 'report' and doc.get('client_name') and title:
            title = f"{doc['client_name']} - {title.splitlines()[0]}"
        fields = {
            'title': (title or f"{doc.get('client_name') or 'Pump work'}")[:160],
            'category': ('maintenance' if kind == 'report' else doc.get('category') or 'repair'),
            'client_name': doc.get('client_name') or '',
            'site': doc.get('site') or '',
            'po_number': doc.get('po_number') or '',
            'vendor': doc.get('vendor') or '',
            'description': doc.get('description') or '',
            'approved_by': doc.get('ordered_by') or '',
            'wo_number': doc.get('wo_number') or '',
            'opened_on': doc.get('doc_date') or _today().isoformat(),
        }
        case_id = create_case(conn, fields, actor, source=doc.get('source') or 'email')
        how = 'new item'
    conn.execute("UPDATE pump_docs SET case_id=?, status=CASE WHEN status='new' THEN 'filed' ELSE status END, "
                 "updated_at=? WHERE id=?", (case_id, _now_text(), doc_id))
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
        _set_step(conn, case_id, 'vendor_bill', at=date_, by=actor)
        steps = json.loads(conn.execute('SELECT steps FROM pump_cases WHERE id=?', (case_id,)).fetchone()[0])
        if not (steps.get('work_done') or {}).get('at') and not (steps.get('work_done') or {}).get('na'):
            _set_step(conn, case_id, 'work_done', at=date_, by=actor)
        _check_bill(conn, case_id, actor)
    elif kind == 'report':
        _apply(conn, case_id, fill)
        steps = json.loads(conn.execute('SELECT steps FROM pump_cases WHERE id=?', (case_id,)).fetchone()[0])
        if not (steps.get('work_done') or {}).get('at'):
            _set_step(conn, case_id, 'work_done', at=date_, by=actor)
        if (steps.get('report_logged') or {}).get('na'):
            _set_step(conn, case_id, 'report_logged', by=actor, na=False)
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
    if res.get('kind') == 'quote' and res.get('case_id') and not res.get('review'):
        res['auto_quote'] = auto_draft_quote(res['doc_id'])
    if res.get('kind') == 'report' and res.get('doc_id') and not res.get('review'):
        res['auto_note'] = auto_log_report(res['doc_id'])
    if res.get('kind') == 'bill' and res.get('case_id') and not res.get('review'):
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
            return {'skipped': 'already have this file', 'doc_id': dup['id'], 'case_id': dup['case_id']}
        text = extract_text(filename, data)
        sender, subject = email.get('from', ''), email.get('subject', '')
        # A forwarded email is from one of us; the vendor shows in the
        # forwarded header at the top of the body, or on the document.
        vendor = _vendor_display(f"{sender}\n{subject}\n{email.get('preview', '')}\n{text[:3000]}")
        if source == 'email' and not vendor and not STRONG_TERMS.search(f'{subject}\n{filename}\n{text[:5000]}'):
            return {'skipped': 'not pump related'}
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
        elif low.endswith('.doc'):
            rec['kind'] = kind_hint or 'report'
            review = 'Old .doc Word file - open it, save as .docx and upload it again to rebrand it.'
            extracted_by = 'none'
        elif text.strip():
            x = _claude_extract(text, sender, subject, filename)
            if x:
                extracted_by = 'claude'
            else:
                x = _regex_extract(text, sender, subject)
                extracted_by = 'regex'
                if USE_CLAUDE:
                    # Claude is meant to read it but failed: read again later.
                    review = 'Read without Claude - check the amounts and line items.'
                elif not (x.get('client_name') or x.get('po_number') or x.get('wo_number')):
                    review = 'Could not find the client, PO or work order - enter it by hand.'
            x = _clean_extraction(x)
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
        now = _now_text()
        conn.execute('''INSERT INTO pump_docs (kind, status, vendor, doc_number, doc_date, po_number, wo_number,
                          quote_ref, ordered_by, client_name, site, category, description, line_items, subtotal,
                          tax, total, file_name, file_path, file_sha, branded_path, branded_info, report_fields,
                          text_excerpt, source, email_uid, email_from, email_subject, email_date, case_id,
                          extracted_by, review_reason, created_at, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                     (rec['kind'], 'review' if review else 'new', rec['vendor'], rec['doc_number'] or '',
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
        x = _clean_extraction(x)
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


def _pdf_name(filename):
    """"10-26  Spanish Wells.docx" -> "10-26 Spanish Wells.pdf", as the office names them."""
    return re.sub(r'\s+', ' ', os.path.splitext(_safe_name(filename))[0]).strip() + '.pdf'


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
                    if res.get('doc_id') and not res.get('skipped'):
                        found += 1
                        summary['documents_added'] += 1
                        summary['added'].append({'doc_id': res['doc_id'], 'kind': res.get('kind'), 'file': filename})
                    else:
                        summary['skipped'] += 1
                if not found and not any((f or '').lower().endswith(('.pdf', '.docx', '.doc')) for f, _ in attachments):
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
        _state_set('scan_status', {'state': 'done', **summary})
        return summary


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


def _tokens():
    raw = _state_get('jobber_tokens_enc')
    if not raw:
        return {}
    try:
        return json.loads(_fernet().decrypt(raw.encode()).decode())
    except Exception:
        return {}


def _save_tokens(tok):
    _state_set('jobber_tokens_enc', _fernet().encrypt(json.dumps(tok).encode()).decode() if tok else '')


def jobber_status():
    tok = _tokens()
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
        if force or time.time() - float(tok.get('obtained_at') or 0) > 55 * 60:
            new = _token_request({'grant_type': 'refresh_token', 'refresh_token': tok['refresh_token']})
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
    fields = _mutation_fields(query)
    bad = [f for f in fields if f not in ALLOWED_MUTATIONS]
    if not fields or bad:
            raise JobberError(f"Blocked Jobber mutation {bad or '(unreadable)'}: "
                          'Pumps only creates draft quotes, draft invoices, notes, jobs from approved quotes '
                          'and visits.')


def jobber_gql(query, variables=None):
    check_mutation_allowed(query)
    force = False
    for _ in range(5):
        token = _access_token(force)
        r = http_requests.post(JOBBER_GQL, timeout=60, json={'query': query, 'variables': variables or {}},
                               headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json',
                                        'X-JOBBER-GRAPHQL-VERSION': JOBBER_API_VERSION})
        if r.status_code == 401 and _tokens().get('refresh_token'):
            force = True
            continue
        if r.status_code == 429:
            time.sleep(20)
            continue
        if r.status_code >= 400:
            raise JobberError(f'Jobber API HTTP {r.status_code}')
        out = r.json()
        errors = out.get('errors') or []
        if errors:
            if any((e.get('extensions') or {}).get('code') == 'THROTTLED' for e in errors):
                time.sleep(15)
                continue
            raise JobberError(' | '.join(e.get('message', '?') for e in errors))
        return out.get('data') or {}
    raise JobberError('Jobber kept refusing the request (signed out or rate limited)')


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


def _sync_jobber(full=False, actor='system'):
    """Pull pump, diver, filter and SCADA requests, quotes, jobs and invoices
    from Jobber, then rebuild the SCADA list and link items by PO number."""
    with _FileLock('jobber_sync', blocking=False) as got:
        if not got:
            return {'skipped': 'a Jobber sync is already running'}
        status = {'state': 'running', 'started_at': _now_text(), 'counts': {}, 'errors': []}
        _state_set('jobber_sync', status)
        seen = {}
        terms = sorted({t for ts in JOBBER_TERMS.values() for t in ts})
        for conn_name, (spec, status_field) in SYNC_SPECS.items():
            kind = conn_name[:-1]
            for term in terms:
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
                        status['errors'].append(f'{conn_name} "{term}": {e}')
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
            status['counts'][conn_name] = sum(1 for v in seen.values() if v['kind'] == kind)
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
            approved = _follow_quotes(conn)
            rebuild_scada(conn)
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
        status.update(state='done', finished_at=_now_text(), items=len(seen), linked=linked)
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


def _refresh_linked_records(conn):
    """Update pump_jobber_items for every quote, invoice and job an item is
    linked to that isn't finished yet - open items, and closed ones still
    waiting on the client to pay. Returns errors."""
    errors, want = [], {}
    for c in conn.execute("SELECT id, status, jobber FROM pump_cases WHERE status != 'cancelled' "
                          "AND jobber LIKE '%\"id\"%'").fetchall():
        j = json.loads(c['jobber'] or '{}')
        for kind, (_, _, _, _, final) in _LINKED_QUERIES.items():
            rec = j.get(kind) or {}
            if not rec.get('id') or (rec.get('status') or '') in final:
                continue
            if c['status'] != 'open' and kind != 'invoice':
                continue
            want[rec['id']] = (kind, c['id'])
    for jid, (kind, case_id) in want.items():
        field, num, st, total, _ = _LINKED_QUERIES[kind]
        try:
            data = jobber_gql(f'query($id: EncodedId!) {{ {field}(id: $id) {{ id {num} {st} {total} '
                              f'jobberWebUri updatedAt }} }}', {'id': jid})
        except JobberError as e:
            errors.append(f'{kind} {jid}: {e}')
            continue
        n = data.get(field)
        if not n:
            continue
        amount = _money(n.get('total') if n.get('total') is not None else (n.get('amounts') or {}).get('total'))
        conn.execute('''INSERT INTO pump_jobber_items (jobber_id, kind, number, status, total, updated_at, web_uri,
                          case_id, synced_at) VALUES (?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(jobber_id) DO UPDATE SET status=excluded.status, total=excluded.total,
                          updated_at=excluded.updated_at, number=excluded.number, synced_at=excluded.synced_at,
                          case_id=COALESCE(pump_jobber_items.case_id, excluded.case_id)''',
                     (jid, kind, str(n.get(num) or ''), (n.get(st) or '').lower(), amount, n.get('updatedAt') or '',
                      n.get('jobberWebUri') or '', case_id, _now_text()))
        time.sleep(0.1)
    return errors


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


def _follow_quotes(conn):
    """Keep each item's Jobber quote status current, and tick "Quote sent to
    client" / "Client approved" once the office has sent it and the client
    has approved it in Jobber. Returns the items just approved."""
    approved = []
    for c in conn.execute("SELECT id, jobber, steps FROM pump_cases WHERE status='open' "
                          "AND jobber LIKE '%quote%'").fetchall():
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
        if it['status'] == q.get('status'):
            continue
        q['status'] = it['status']
        j['quote'] = q
        conn.execute('UPDATE pump_cases SET jobber=? WHERE id=?', (json.dumps(j), c['id']))
        _event(conn, 'jobber sync', 'quote status', f"Jobber quote #{q.get('number')} is now {it['status']}",
               case_id=c['id'])
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
        if extra:
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
            return out
    alias = match_site_alias(doc, case)
    if alias and (not item_client or item_client == alias['client_id']):
        out.update(client_id=alias['client_id'], client_name=alias['client_name'],
                   how=f'site name "{alias["place"]}{" " + alias["area"] if alias["area"] else ""}"')
        if alias['property_id']:
            out.update(property_id=alias['property_id'], property_label=alias['property_label'])
            return out
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
        props = client_jobs(out['client_id'])['properties']
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
            if len(fits) == 1:
                pick = fits[0]
        if pick:
            out.update(property_id=pick['id'], property_label=pick['label'])
    return out


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
    every later quote, bill and report with that name goes there by itself."""
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
    def score(j):
        s = 0
        t = (j['title'] or '').lower()
        if TITLE_PATTERNS['pump'].search(t):
            s += 3
        if loc and any(w in t for w in re.findall(r'[a-z0-9#]+', loc) if len(w) > 2):
            s += 2
        if j.get('property_id') in prop_ids:
            s += 2
        if j.get('type') == 'recurring' and j.get('status') not in ('archived',):
            s += 2
        if j.get('status') in ('active', 'upcoming', 'today', 'late'):
            s += 1
        return (s, j.get('created') or '')
    ranked = sorted(jobs, key=score, reverse=True)
    return ranked[0] if ranked and score(ranked[0])[0] >= 3 else None


def one_line_items(doc, markup_pct):
    """Our quotes and invoices are always one "Service Proposal Amount" line:
    the vendor's work described (without their name), priced at their total
    before tax plus the markup. A price that already includes the vendor's
    sales tax stays not taxable."""
    lines = [it for it in (doc.get('line_items') or []) if not it.get('is_tax')]
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
    return [{'name': 'Service Proposal Amount', 'description': '\n'.join(descs)[:2000], 'quantity': 1,
             'unit_price': round(base * (1 + (markup_pct or 0) / 100), 2), 'taxable': bool(taxable)}]


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


def suggest_invoice(doc, case=None):
    """Our invoice for a vendor bill when there is no client quote to copy:
    one Service Proposal Amount line, the bill before tax plus the quote
    markup (30%). Jobber adds the client's tax itself."""
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
                      'saveToProductsAndServices': False})
    if not items:
        raise ValueError(f'No line items to put on the {what}')
    return items


def suggest_quote(doc, case=None):
    """Our quote to the client, the way the office writes them (Jobber quote
    9136): the vendor's price plus QUOTE_MARKUP_PCT, no vendor name or sales
    tax line, a single-price quote as one "Service Proposal Amount" line
    carrying the vendor's description of the work, titled "Proposal to ...".
    A price that already includes the vendor's tax stays not taxable."""
    items = one_line_items(doc, QUOTE_MARKUP_PCT)
    words = ' '.join([doc.get('description') or ''] + [f"{i.get('name') or ''} {i.get('description') or ''}"
                                                       for i in doc.get('line_items') or []])
    markup = QUOTE_MARKUP_PCT
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
    title = (doc.get('proposal_title') or '').strip() or _proposal_title(
        items[0]['description'] if items else (doc.get('description') or ''))
    return {'title': title[:255], 'line_items': items, 'markup_pct': markup}


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
    lines.append(f'Our price: ${total:,.2f} ({QUOTE_MARKUP_PCT:g}% markup). Drafted by the Pumps app.')
    base = (CFG.get('website_url') or '').rstrip('/')
    if base and 'localhost' not in base:
        lines.append(f"File: {base}/pumps#doc-{doc['id']}")
    return '\n'.join(lines)


def note_vendor_file(doc, target_type, target_id, text, version='original', file_name=None, content_type=None):
    """A note on a Jobber record with the vendor's own document attached (or
    linked, when Jobber will not take the attachment)."""
    mutation, id_arg, input_type, field = NOTE_MUTATION[target_type]
    q = (f'mutation PumpsVendorNote($id: EncodedId!, $input: {input_type}!) {{ {mutation}({id_arg}: $id, '
         f'input: $input) {{ {field} {{ id }} userErrors {{ message path }} }} }}')
    url = _signed_file_url(doc['id'], version, days=7)
    ctype = content_type or ('application/pdf' if (doc.get('file_name') or '').lower().endswith('.pdf') else
                             'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    if url:
        try:
            data = jobber_gql(q, {'id': target_id, 'input': {'message': text, 'attachments': [
                {'url': url, 'fileName': file_name or doc.get('file_name'), 'contentType': ctype}]}})
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
    reason = ''
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
    except (JobberError, ValueError) as e:
        reason = f'Could not draft it automatically: {e}'
    conn = _conn()
    try:
        j = {**(doc.get('jobber') or {}), 'quote_pending': {'reason': reason, 'at': _now_text()}}
        conn.execute('UPDATE pump_docs SET jobber=? WHERE id=?', (json.dumps(j), doc_id))
        _event(conn, actor, 'client quote not drafted', reason, case_id=case['id'], doc_id=doc_id)
        conn.commit()
    finally:
        conn.close()
    return {'pending': reason}


def fetch_quote_lines(quote_id):
    """Our client quote's lines from Jobber, as the invoice should repeat them."""
    for lines_spec in ('lineItems { nodes { name description quantity unitPrice taxable } }',
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
                  'taxable': bool(li.get('taxable'))} for li in raw if li.get('unitPrice') is not None]
        return {'number': str(q.get('quoteNumber') or ''), 'line_items': lines}
    return None


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


def invoice_suggestion(doc, case=None):
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
    if jobber_status()['connected'] and not (json.loads(case.get('jobber') or '{}').get('job') or {}).get('id'):
        try:
            client_id = invoice_client(doc, case)
            job = find_matching_job(doc, client_id) if client_id else None
        except JobberError:
            job = None
        if job and job['line_items']:
            sugg.update(bill_lines=sugg['line_items'], line_items=job['line_items'], client_id=client_id,
                        job={k: job[k] for k in ('id', 'number', 'title', 'uri', 'total', 'status')})
    return sugg


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
            field = m.group(1) if m else next((f for f in ('saveToProductsAndServices', 'taxable')
                                               if f in str(e) and f not in dropped), None)
            if not field or field in dropped or field in ('name', 'quantity', 'unitPrice'):
                raise
            dropped.append(field)
            variables[key]['lineItems'] = [{k: v for k, v in li.items() if k != field}
                                           for li in variables[key]['lineItems']]
    return jobber_gql(query, variables)


QUOTE_CREATE = '''mutation PumpsDraftQuote($attributes: QuoteCreateAttributes!) {
  quoteCreate(attributes: $attributes) {
    quote { id quoteNumber quoteStatus jobberWebUri }
    userErrors { message path }
  }
}'''


def create_draft_quote(doc_id, client_id, property_id, line_items, title='', message='', actor='system'):
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
               'quote_drafted_by': actor, 'quote_drafted_at': _now_text()}
        conn.execute('UPDATE pump_docs SET jobber=?, updated_at=? WHERE id=?',
                     (json.dumps({**(doc.get('jobber') or {}), **ref}), _now_text(), doc_id))
        total = round(sum(i['quantity'] * i['unitPrice'] for i in items), 2)
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


def create_draft_invoice(doc_id, client_id, line_items, subject='', job_id='', actor='system'):
    """Create the invoice in Jobber as a DRAFT. Nothing is sent: the only
    mutation used is invoiceCreate, and check_mutation_allowed() refuses any
    other. If Jobber ever hands back a status other than draft, an issue is
    raised so someone looks at it."""
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM pump_docs WHERE id=?', (doc_id,)).fetchone()
        if not row:
            raise ValueError('No such document')
        doc = _doc_dict(row)
        if doc['kind'] != 'bill':
            raise ValueError('Only a bill can be turned into an invoice')
        if (doc.get('jobber') or {}).get('invoice_id'):
            raise ValueError(f"Already drafted as Jobber invoice #{doc['jobber'].get('invoice_number')}")
        if not client_id:
            raise ValueError('Choose the Jobber client first')
        items = _jobber_lines(line_items, 'invoice')
        due = invoice_due_details()
        inp = {'clientId': client_id, 'subject': (subject or 'Pump service')[:255], 'dueDetails': due,
               'tax': {'taxCalculationMethod': 'EXCLUSIVE'}, 'lineItems': items}
        if job_id:
            inp['jobId'] = job_id
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
        conn.execute('UPDATE pump_docs SET jobber=?, status=?, updated_at=? WHERE id=?',
                     (json.dumps({**(doc.get('jobber') or {}), **ref}), 'done', _now_text(), doc_id))
        total = round(sum(i['quantity'] * i['unitPrice'] for i in items), 2)
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
        return {**ref, 'total': total}
    finally:
        conn.close()


def _signed_file_url(doc_id, version='branded', days=2):
    base = (CFG.get('website_url') or '').rstrip('/')
    if not base or 'localhost' in base or '127.0.0.1' in base:
        return ''
    exp = int(time.time()) + days * 86400
    sig = hmac.new((CFG.get('secret_key') or '').encode(), f'{doc_id}:{version}:{exp}'.encode(),
                   'sha256').hexdigest()[:32]
    return f'{base}/pumps/f/{doc_id}/{version}/{exp}/{sig}'


def _check_signed(doc_id, version, exp, sig):
    if int(exp) < time.time():
        return False
    good = hmac.new((CFG.get('secret_key') or '').encode(), f'{doc_id}:{version}:{exp}'.encode(),
                    'sha256').hexdigest()[:32]
    return hmac.compare_digest(good, sig)


def report_note_text(doc):
    rf = doc.get('report_fields') or {}
    # Only ever the rebranded report's lines - never the sub's original.
    raw = rf.get('lines') if rf.get('from_branded') else []
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
}


def report_note_title(doc):
    """"October Pump Maintenance": the month of the visit, as the office titles them."""
    rf = doc.get('report_fields') or {}
    when = _iso_date(rf.get('date')) or doc.get('doc_date') or _today().isoformat()
    try:
        month = datetime.strptime(when[:10], '%Y-%m-%d').strftime('%B')
    except ValueError:
        month = _today().strftime('%B')
    what = 'Fountain Maintenance' if re.search(r'fountain', rf.get('title') or '', re.I) else 'Pump Maintenance'
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
    if not doc or doc['kind'] != 'report' or not doc['has_branded'] or doc['status'] in ('review', 'dismissed') \
            or (doc.get('jobber') or {}).get('note_id'):
        return None
    try:
        t = resolve_report_target(doc, case)
        if t.get('id'):
            return {**log_report_to_jobber(doc_id, t['type'], t['id'], actor), 'target': t['label'], 'how': t['how']}
        reason = t['needs']
    except (JobberError, ValueError) as e:
        reason = f'Could not log it automatically: {e}'
    conn = _conn()
    try:
        j = {**(doc.get('jobber') or {}), 'note_pending': {'reason': reason, 'at': _now_text()}}
        conn.execute('UPDATE pump_docs SET jobber=? WHERE id=?', (json.dumps(j), doc_id))
        _event(conn, actor, 'report not logged in Jobber', reason, case_id=doc.get('case_id'), doc_id=doc_id)
        conn.commit()
    finally:
        conn.close()
    return {'pending': reason}


def log_report_to_jobber(doc_id, target_type, target_id, actor='system', message=None):
    """Add the report as a note on the pump's job (or the client). Tries to
    attach the rebranded file; if Jobber will not take the attachment, the note
    is saved with a link to the file in this app instead."""
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
        text = message or report_note_title(doc)
        q = (f'mutation PumpsReportNote($id: EncodedId!, $input: {input_type}!) {{ {mutation}({id_arg}: $id, '
             f'input: $input) {{ {field} {{ id }} userErrors {{ message path }} }} }}')
        # The PDF, as the office attaches them; the Word file when there is no PDF.
        has_pdf = bool(row['branded_path']) and (os.path.exists(_branded_pdf_path(row['branded_path'])) or
                                                  bool(_make_branded_pdf(row['branded_path'])))
        version = 'branded_pdf' if has_pdf else ('branded' if doc['has_branded'] else 'original')
        url = _signed_file_url(doc_id, version, days=7)
        attached = False
        data = None
        if url:
            fname = _pdf_name(doc['file_name']) if has_pdf else \
                (_branded_name(doc['file_name']) if doc['has_branded'] else doc['file_name'])
            ctype = 'application/pdf' if has_pdf else \
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            try:
                data = jobber_gql(q, {'id': target_id, 'input': {'message': text, 'attachments': [{
                    'url': url, 'fileName': fname, 'contentType': ctype}]}})
                attached = not ((data.get(mutation) or {}).get('userErrors'))
            except JobberError as e:
                print(f'  ⚠ Pumps: Jobber would not take the attachment ({e}); saving the note without it')
                data = None
        if not attached:
            # No file on the note: put the (rebranded) report's text and a link in it.
            data = jobber_gql(q, {'id': target_id, 'input': {'message': f'{text}\n\n{report_note_text(doc)}'
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
        conn.execute('UPDATE pump_docs SET jobber=?, status=?, updated_at=? WHERE id=?',
                     (json.dumps({**j, **ref}), 'done', _now_text(), doc_id))
        if doc.get('case_id'):
            _set_step(conn, doc['case_id'], 'report_logged', at=_today().isoformat(), by=actor)
            if target_type == 'job':
                case = conn.execute('SELECT jobber FROM pump_cases WHERE id=?', (doc['case_id'],)).fetchone()
                j = json.loads(case['jobber'] or '{}')
                j.setdefault('job', {'id': target_id})
                conn.execute('UPDATE pump_cases SET jobber=? WHERE id=?', (json.dumps(j), doc['case_id']))
            _event(conn, actor, 'report logged in Jobber',
                   f"note on {target_type}" + (' with the file attached' if attached else ' (file linked, not attached)'),
                   case_id=doc['case_id'], doc_id=doc_id)
        conn.commit()
        return ref
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════════════════════
# what needs doing
# ═════════════════════════════════════════════════════════════════════════════

def work_queue(conn):
    cases = list_cases(conn, 'open')
    issues = [dict(r) for r in conn.execute('''SELECT i.*, c.title, c.client_name FROM pump_issues i
                                               LEFT JOIN pump_cases c ON c.id = i.case_id
                                               WHERE i.resolved_at IS NULL ORDER BY i.id''')]
    by_stage = {}
    for c in cases:
        by_stage.setdefault(c['stage'], []).append(c)
    review_docs = [_doc_dict(r) for r in conn.execute(
        "SELECT * FROM pump_docs WHERE status IN ('review','new') OR (case_id IS NULL AND status != 'dismissed') "
        "ORDER BY id DESC")]
    bills_to_draft = [_doc_dict(r) for r in conn.execute(
        "SELECT d.* FROM pump_docs d JOIN pump_cases c ON c.id = d.case_id WHERE d.kind='bill' "
        "AND d.status != 'dismissed' AND (d.jobber IS NULL OR d.jobber NOT LIKE '%invoice_id%') "
        "AND c.status='open' ORDER BY d.id")]
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
    new_requests = untracked_jobber_items(conn)
    stale = [c for c in cases if c['idle_days'] >= STALE_DAYS]
    return {
        'issues': issues,
        'needs_scheduling': by_stage.get('scheduled', []),
        'waiting_assessment': by_stage.get('assessment', []),
        'waiting_vendor_quote': by_stage.get('vendor_quote', []),
        'to_quote_client': by_stage.get('client_quote', []),
        'waiting_approval': by_stage.get('client_approved', []),
        'waiting_work': by_stage.get('work_done', []),
        'waiting_bill': by_stage.get('vendor_bill', []),
        'bills_to_check': by_stage.get('bill_checked', []),
        'bills_to_draft': bills_to_draft,
        'todos': [_todo_dict(r) for r in conn.execute("SELECT * FROM pump_todos WHERE done_at IS NULL "
                                                      "ORDER BY COALESCE(NULLIF(due_on, ''), created_at), id")],
        'quotes_to_draft': quotes_to_draft,
        'vendor_bills_to_pay': vendor_bills_to_pay,
        'reports_to_log': reports_to_log,
        'ready_to_close': by_stage.get('closed', []),
        'review_docs': review_docs,
        'scada_attention': scada,
        'new_jobber_requests': new_requests,
        'stale': stale,
        'open_count': len(cases),
    }


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
            return _call(fn, actor, kw)

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
    try:
        out = fn(actor, **kw)
    except (ValueError, KeyError) as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except JobberError as e:
        return jsonify({'success': False, 'error': str(e)}), 502
    if isinstance(out, tuple):
        body, code = out
        return jsonify(body), code
    if isinstance(out, Response):
        return out
    return jsonify({'success': True, **(out or {})})


def _json():
    return request.get_json(silent=True) or {}


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
        q = work_queue(conn)
        return {'queue': q, 'counts': {k: len(v) for k, v in q.items() if isinstance(v, list)},
                'scan': _state_get('scan_status') or {}, 'jobber': {**jobber_status(),
                                                                     'sync': jobber_sync_state()},
                'claude': USE_CLAUDE, 'email': bool(CFG.get('email_enabled'))}
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
             f"The client has paid our Jobber invoice{' #' + our_no if our_no else ''}.", '',
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
        conn.commit()
    finally:
        conn.close()
    return rec


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
        if d['kind'] == 'quote':
            d['quote_suggestion'] = suggest_quote(d, case)
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
    if version == 'branded_pdf':
        path = _branded_pdf_path(row['branded_path'])
        if row['branded_path'] and not os.path.exists(path):
            path = _make_branded_pdf(row['branded_path'])
        if not path or not os.path.exists(path):
            return {'success': False, 'error': 'No PDF of this report on this server - download the Word file.'}, 404
        return send_file(path, mimetype='application/pdf', as_attachment=request.args.get('download') == '1',
                         download_name=_pdf_name(row['file_name']))
    if version == 'approved':
        path = (json.loads(row['jobber'] or '{}')).get('approved_path')
        if not path or not os.path.exists(path):
            return {'success': False, 'error': 'No approved copy of this quote yet'}, 404
        return send_file(path, mimetype='application/pdf', as_attachment=request.args.get('download') == '1',
                         download_name=_approved_name(row['file_name']))
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
        mine = {**mine, 'score': 1.0, 'remembered': f'You matched "{a["place"]}" to {a["client_name"]} before'}
        cands = [mine] + [c for c in cands if c['id'] != a['client_id']]
        return {'candidates': cands, 'pick': mine}
    return {'candidates': cands, 'pick': pick_client(cands)}


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
    sugg = invoice_suggestion(doc, case)
    job_id = data.get('job_id')
    if job_id is None:
        job_id = (json.loads(case.get('jobber') or '{}').get('job') or {}).get('id') or \
            ((sugg.get('job') or {}).get('id') if (sugg.get('client_id') in (None, client_id)) else '') or ''
    res = create_draft_invoice(doc_id, client_id, data.get('line_items') or sugg['line_items'],
                               data.get('subject') or sugg['subject'], job_id or '', actor)
    if sugg.get('job') and job_id == sugg['job']['id']:
        invoiced_on_job(doc, case, sugg['job'], actor)
    return {'invoice': res}


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
        _set_step(conn, case['id'], 'bill_checked', at=_today().isoformat(), by=actor)
        _event(conn, actor, 'invoiced on matching job', f"Jobber job #{job.get('number')} {job.get('title')}",
               case_id=case['id'], doc_id=doc.get('id'))
        base = doc.get('subtotal') if doc.get('subtotal') is not None else doc.get('total')
        if base is not None and job.get('total') is not None and \
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


@api('/docs/<int:doc_id>/reread', methods=('POST',))
def h_doc_reread(actor, doc_id):
    """Read a document again with Claude, and file it if it now reads cleanly."""
    return reread_doc(doc_id, actor)


@api('/docs/<int:doc_id>/quote', methods=('POST',))
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
    res = create_draft_quote(doc_id, client_id, property_id, data.get('line_items') or sugg['line_items'],
                             data.get('title') or sugg['title'], data.get('message') or '', actor)
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


@api('/docs/<int:doc_id>/report_note', methods=('POST',))
def h_doc_report_note(actor, doc_id):
    """Log a report as a note in Jobber. Body: {"target_type": "job"|"client",
    "target_id", "message"}. Without a target, the pump's job is found from the
    report's customer and location when there is one clear answer."""
    data = _json()
    ttype, tid = data.get('target_type'), data.get('target_id')
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
    return {'note': log_report_to_jobber(doc_id, ttype, tid, actor, data.get('message'))}


@api('/issues/<int:issue_id>/bill-anyway', methods=('POST',))
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
    return {'status': _state_get('scan_status') or {}}


@api('/jobber/sync', methods=('POST',))
def h_jobber_sync(actor):
    if not jobber_status()['connected']:
        raise ValueError('Connect Jobber first')
    return {'started': start_jobber_sync(bool(_json().get('full')), actor), 'status': jobber_sync_state()}


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
            cat = {'scada': 'scada', 'diver': 'diver', 'filter': 'filter'}.get(it['category'], 'repair')
            if it['kind'] == 'job' and re.search(r'maint|quarter|monthly|annual', it['title'] or '', re.I):
                cat = 'maintenance'
            cid = create_case(conn, {'title': it['title'] or it['client_name'], 'category': cat,
                                     'client_name': it['client_name'], 'site': it['property_label'],
                                     'po_number': it['po_number'], 'jobber_client_id': it['client_id'],
                                     'jobber_property_id': it['property_id'],
                                     'vendor': 'Wettech' if cat in ('repair', 'maintenance')
                                               or re.search(r'we?t+e?ch|\bwet\b', it['title'] or '', re.I) else '',
                                     'opened_on': (it['created_at'] or '')[:10],
                                     'jobber_request_made': _jobber_ref_text(it)},
                              actor, source='jobber')
            _link_item(conn, jobber_id, cid, actor)
            if it['kind'] == 'quote' and it['status'] in ('awaiting_response', 'changes_requested'):
                _set_step(conn, cid, 'client_quote', at=(it['created_at'] or '')[:10] or None, by=actor)
            if it['kind'] == 'quote' and it['status'] == 'approved':
                _set_step(conn, cid, 'client_quote', at=(it['created_at'] or '')[:10] or None, by=actor)
                _set_step(conn, cid, 'client_approved', at=(it['updated_at'] or '')[:10] or None, by=actor)
            if it['kind'] == 'job' and (it['completed_at'] or it['status'] == 'requires_invoicing'):
                _set_step(conn, cid, 'client_approved', at=(it['created_at'] or '')[:10] or None, by=actor)
                _set_step(conn, cid, 'work_done', at=(it['completed_at'] or it['updated_at'] or '')[:10] or None,
                          by=actor)
            elif it['kind'] == 'job' and cat == 'maintenance':
                _set_step(conn, cid, 'client_approved', at=(it['created_at'] or '')[:10] or None, by=actor)
            elif it['kind'] in ('job', 'request'):
                # Made in Jobber before any quote: the vendor goes out to look first.
                _set_assessment(conn, cid, (it['start_at'] or '')[:10],
                                done=it['kind'] == 'request' and it['status'] == 'assessment_completed', by=actor)
        else:
            raise ValueError('action must be track, link, ignore or unignore')
        conn.commit()
        return {'case_id': cid}
    finally:
        conn.close()


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
               'jobber_client_id', 'kind', 'joined', 'diver_cost', 'our_bill', 'naples_electric')


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
    rf = d.get('report_fields') or {}
    return _iso_date(rf.get('date')) or d.get('doc_date') or (d.get('created_at') or '')[:10]


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
     '$1,125.00', 'SiteOne, not Tommy', 1),
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
    ('Wild Blue', 'Pump', '2026-03-17', '1 Pump 1 Lake', None, Q, '$250.00', '', '', None, 1, 1),
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
    for col, decl in (('kind', "TEXT DEFAULT 'Lake'"), ('joined', "TEXT DEFAULT ''"), ('diver_cost', "TEXT DEFAULT ''"),
                      ('our_bill', "TEXT DEFAULT ''"), ('naples_electric', "TEXT DEFAULT ''"),
                      ('active', 'INTEGER DEFAULT 1')):
        try:
            c.execute(f'ALTER TABLE pump_dive_sites ADD COLUMN {col} {decl}')
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
    lines = 'lineItems { nodes { name description } }'
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
                'notes')


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
        conn.commit()
        return {'accounts': maint_accounts(conn)}
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
AUTO_DRAFT_INVOICES = os.environ.get('PUMPS_AUTO_DRAFT_INVOICES', 'true').lower() in ('1', 'true', 'yes', 'on')
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


def _vendor_contact(vendor):
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


def make_approved_pdf(doc, when=None):
    """Stamp the vendor's quote file (a Word quote is turned into a PDF first)."""
    with open(doc['file_path'], 'rb') as f:
        data = f.read()
    if not (doc.get('file_name') or '').lower().endswith('.pdf'):
        data = pump_reports.docx_to_pdf(data)
        if not data:
            raise ValueError('The quote is a Word file and PDF conversion is not available on this server')
    when = when or _today()
    stamped = stamp_approved(data, f'{APPROVER}', when.strftime('%B %d, %Y').replace(' 0', ' '))
    path, _ = _store_file(stamped, _approved_name(doc.get('file_name')))
    return path


def on_quote_approved(case_id, actor='Jobber sync'):
    """The client approved our Jobber quote: stamp the vendor's quote APPROVED
    by Simon Weardon, keep it on the item and on the Jobber quote, make the
    quote a job, and add the to-do to send it back to the vendor."""
    conn = _conn()
    try:
        case = conn.execute('SELECT * FROM pump_cases WHERE id=?', (case_id,)).fetchone()
        if not case:
            return None
        case = dict(case)
        row = conn.execute("SELECT * FROM pump_docs WHERE case_id=? AND kind='quote' AND status != 'dismissed' "
                           "ORDER BY id DESC", (case_id,)).fetchone()
        doc = {**_doc_dict(row), 'file_path': row['file_path']} if row else None
    finally:
        conn.close()
    j = json.loads(case.get('jobber') or '{}')
    q = j.get('quote') or {}
    out = {'case_id': case_id}
    name, email = _vendor_contact(case.get('vendor'))
    who = case.get('client_name') or case.get('title') or f'item {case_id}'
    if doc and not (doc.get('jobber') or {}).get('approved_path'):
        try:
            path = make_approved_pdf(doc)
            conn = _conn()
            try:
                dj = {**(doc.get('jobber') or {}), 'approved_path': path, 'approved_at': _now_text(),
                      'approved_by': APPROVER}
                conn.execute('UPDATE pump_docs SET jobber=? WHERE id=?', (json.dumps(dj), doc['id']))
                _event(conn, actor, 'quote stamped approved', f'{APPROVER} - {_approved_name(doc["file_name"])}',
                       case_id=case_id, doc_id=doc['id'])
                conn.commit()
            finally:
                conn.close()
            doc['jobber'] = dj
            out['stamped'] = True
        except Exception as e:
            out['stamp_error'] = str(e)
    if doc and (doc.get('jobber') or {}).get('approved_path') and q.get('id') and jobber_status()['connected'] \
            and not (doc.get('jobber') or {}).get('approved_note_id'):
        try:
            note = note_vendor_file(doc, 'quote', q['id'], f"Approved - {doc.get('vendor') or 'vendor'} quote "
                                    f"{('#' + doc['doc_number']) if doc.get('doc_number') else ''} signed by "
                                    f"{APPROVER} on {_today().strftime('%m/%d/%Y')}.", version='approved',
                                    file_name=_approved_name(doc['file_name']), content_type='application/pdf')
            conn = _conn()
            try:
                dj = {**(doc.get('jobber') or {}), 'approved_note_id': note['note_id']}
                conn.execute('UPDATE pump_docs SET jobber=? WHERE id=?', (json.dumps(dj), doc['id']))
                conn.commit()
            finally:
                conn.close()
        except JobberError as e:
            out['note_error'] = str(e)
    conn = _conn()
    try:
        if doc:
            add_todo(conn, f"approved-quote:{doc['id']}", f'Send the approved quote back to {name} ({email})',
                     f"{who} - {doc.get('vendor') or 'vendor'} quote {('#' + doc['doc_number']) if doc.get('doc_number') else ''}"
                     f" is stamped APPROVED by {APPROVER}. Download it, reply to {name} with it attached, then tick this.",
                     {'case_id': case_id, 'doc_id': doc['id'], 'to': email,
                      'subject': f"Approved - {who} {('quote #' + doc['doc_number']) if doc.get('doc_number') else ''}".strip()},
                     kind='approved_quote')
        conn.commit()
    finally:
        conn.close()
    if q.get('id') and not (j.get('job') or {}).get('id'):
        out['job'] = make_job_from_quote(case_id)
    return out


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
            add_todo(conn, f'quote-to-job:{case_id}', f"Convert Jobber quote #{q.get('number') or ''} to a job",
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
    j = json.loads(case.get('jobber') or '{}')
    q = j.get('quote') or {}
    if (j.get('invoice') or {}).get('id'):
        return None
    if not q.get('id'):
        # No quote of ours on the item: invoice the client's Jobber job this bill matches, at the job's price.
        try:
            sugg = invoice_suggestion(doc, case)
            if not sugg.get('job'):
                return None
            res = create_draft_invoice(doc_id, sugg['client_id'], sugg['line_items'], sugg['subject'],
                                       sugg['job']['id'], actor)
            invoiced_on_job(doc, case, sugg['job'], actor)
            return {**res, 'job': sugg['job']}
        except (JobberError, ValueError) as e:
            return {'pending': str(e)}
    try:
        lines = fetch_quote_lines(q['id'])
        if not lines or not lines['line_items']:
            return {'pending': 'Could not read our quote from Jobber'}
        client_id = (j.get('client') or {}).get('id') or case.get('jobber_client_id')
        where = case.get('client_name') or ''
        subject = (doc.get('proposal_title') or case.get('title') or f'Pump service - {where}')[:255]
        return create_draft_invoice(doc_id, client_id, lines['line_items'], subject,
                                    (j.get('job') or {}).get('id') or '', actor)
    except (JobberError, ValueError) as e:
        return {'pending': str(e)}


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


def match_account(text, conn=None):
    """The account a service-call email is about: the longest name it mentions."""
    own = conn is None
    conn = conn or _conn()
    try:
        best = None
        for n in _account_names(conn):
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
                          r'approved\s*-\s)', re.I)


def from_this_app(sender, subject):
    own = {a.lower() for a in (CFG.get('mail_from'), dive_settings().get('from')) if a}
    addr = (re.search(r'[\w.+-]+@[\w.-]+', sender or '') or [None])[0]
    return bool(OWN_SUBJECTS.search(subject or '')) or bool(addr and addr.lower() in own)


def _remove_own_email_service_calls(conn):
    """Undo service calls opened from the app's own daily email ("Pumps today -
    N to do") before such emails were ignored. Once."""
    conn.row_factory = sqlite3.Row
    if not _claim_once(conn, 'own_email_calls_removed'):
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
    """30 days before a SCADA renewal: draft the client's quote in Jobber at
    their price from the SCADA sheet (a to-do says to send it), or, for a
    complimentary one, just a reminder."""
    conn = _conn()
    try:
        rows = [r for r in scada_rows(conn) if r['active'] and r['state'] in ('due_soon', 'overdue')]
    finally:
        conn.close()
    done = []
    for r in rows:
        year = (r['next_due_on'] or '')[:4]
        key = f"scada:{r['id']}:{year}"
        conn = _conn()
        try:
            if r.get('complimentary'):
                add_todo(conn, key, f"SCADA renewal due - {r['client']} (complimentary)",
                         f"Due {r['next_due_on']}. Wettech renews it; no client quote. {r.get('notes') or ''}".strip(),
                         {'scada_id': r['id']}, due_on=r['next_due_on'])
                conn.commit()
                continue
            quote = json.loads(r.get('quote') or '{}') if isinstance(r.get('quote'), str) else (r.get('quote') or {})
            if quote.get('year') == year:
                continue
        finally:
            conn.close()
        price = _money(r.get('our_bill'))
        err = ''
        if not price:
            err = 'no price on the SCADA tab'
        elif not jobber_status()['connected']:
            err = 'Jobber is not connected'
        made = None
        if not err:
            try:
                client = _scada_client(r)
                props = client_jobs(client['id'])['properties'] if client else []
                prop = props[0] if len(props) == 1 else next(
                    (p for p in props if place_score(_core_name(r['client']), p['label']) >= 0.99), None)
                if not client:
                    err = f"can't tell which Jobber client {r['client']} is - set its Name in Jobber"
                elif not prop:
                    err = f"{client['name']} has {len(props)} properties - choose one"
                else:
                    y = int(year)
                    items = _jobber_lines([{'name': 'Service Proposal Amount', 'description':
                                            SCADA_QUOTE_TEXT.format(y1=y, y2=y + 1), 'quantity': 1,
                                            'unit_price': price, 'taxable': False}], 'quote')
                    data = gql_with_lines(QUOTE_CREATE, {'attributes': {
                        'clientId': client['id'], 'propertyId': prop['id'],
                        'title': 'Proposal to renew the SCADA annual cellular subscription', 'lineItems': items}}, 'attributes')
                    payload = data.get('quoteCreate') or {}
                    if payload.get('userErrors'):
                        raise JobberError('; '.join(e.get('message', '?') for e in payload['userErrors']))
                    made = payload.get('quote') or {}
            except (JobberError, ValueError, TypeError) as e:
                err = str(e)
        conn = _conn()
        try:
            if made:
                ref = {'year': year, 'id': made.get('id'), 'number': str(made.get('quoteNumber') or ''),
                       'uri': made.get('jobberWebUri'), 'at': _now_text()}
                conn.execute('UPDATE pump_scada_accounts SET quote=? WHERE id=?', (json.dumps(ref), r['id']))
                _event(conn, 'Pumps', 'SCADA quote drafted', f"{r['client']} {year}: Jobber quote #{ref['number']} "
                       f"${price:,.2f}")
                add_todo(conn, f"scada-send:{r['id']}:{year}", f"Send the SCADA renewal quote #{ref['number']} - {r['client']}",
                         f"Drafted in Jobber at ${price:,.2f}. Renewal due {r['next_due_on']}.",
                         {'scada_id': r['id'], 'uri': ref['uri'] or ''}, due_on=r['next_due_on'])
                done.append(r['client'])
            else:
                add_todo(conn, key, f"Quote the SCADA renewal - {r['client']}",
                         f"Due {r['next_due_on']} at {r.get('our_bill') or 'their price'}. The app couldn't draft it: {err}.",
                         {'scada_id': r['id']}, due_on=r['next_due_on'])
            conn.commit()
        finally:
            conn.close()
    return done


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
    sec('SCADA renewals', [f"{e(s['client_name'])} - {'overdue since' if s['state'] == 'overdue' else 'due'} "
                           f"{e(s['next_due_on'])}" for s in q['scada_attention']])
    sec('Quotes to send / waiting on the client', [e(c['title'] or c['client_name']) for c in
                                                   q['to_quote_client'] + q['waiting_approval']])
    sec('Waiting on the vendor', [e(c['title'] or c['client_name']) for c in
                                  q['waiting_vendor_quote'] + q['needs_scheduling'] + q['waiting_work'] + q['waiting_bill']])
    sec('Ready to invoice / close', [e(c['title'] or c['client_name']) for c in q['ready_to_close']])
    sec('Documents that need a look', [e(d.get('client_name') or d.get('file_name')) + f" - {e(d.get('review_reason'))}"
                                       for d in q['review_docs'][:15]])
    day = _today().strftime('%A %B %d').replace(' 0', ' ')
    body = ''.join(sections) or '<p style="font:14px Arial">Nothing needs doing today.</p>'
    html = (f'<div style="font:14px Arial;color:#111"><p>Pumps - {e(day)}. {q["open_count"]} open jobs.'
            + (f' <a href="{link}">Open Pumps</a>' if link else '') + f'</p>{body}</div>')
    n = len(q['todos']) + len(q['vendor_bills_to_pay']) + len(q['issues'])
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


def _scheduled_hourly():
    """Every hour: the month's diver to-do / email, SCADA renewals coming due,
    and the weekday 8am email."""
    _scheduled_dive_email()
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
    out.sort(key=lambda a: a['name'].lower())
    return out


@api('/accounts')
def h_accounts(actor):
    conn = _conn()
    try:
        rows = accounts(conn)
        month = _today().month
        for a in rows:
            for k in ('pump', 'lake'):
                x = a[k]
                if x:
                    ms = _month_list(x.get('months'))
                    x['due_this_month'] = bool(x.get('active', 1)) and (bool(x.get('monthly')) or
                                                                         (month in ms if ms else k == 'lake'))
        return {'accounts': rows, 'month': _today().strftime('%B')}
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
                                  flash_msg=request.args.get('msg', ''))


@bp.route('/pumps/f/<int:doc_id>/<version>/<int:exp>/<sig>')
def signed_file(doc_id, version, exp, sig):
    """Short-lived link Jobber uses to fetch a report it is attaching to a note."""
    if version not in ('branded', 'branded_pdf', 'original', 'approved') or not _check_signed(doc_id, version, exp, sig):
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
            sched.add_job(_safe(_scheduled_hourly), 'interval', hours=1, id='pumps_hourly',
                          next_run_time=datetime.now() + timedelta(minutes=3))
            sched.start()
            print(f'✓ Pumps: mailbox scan every {SCAN_EVERY_MIN} min' if email_enabled else
                  'ℹ Pumps: mailbox not configured - no automatic scan')
        except Exception as e:
            print(f'⚠ Pumps scheduler did not start: {e}')


def _scheduled_jobber_sync():
    if jobber_status()['connected']:
        sync_jobber(False, 'schedule')
