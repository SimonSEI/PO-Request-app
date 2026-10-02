"""
FileMaker: a working, independent recreation of a FileMaker Pro-style
relational database builder, opened from the Features Coming Soon folder.

Not affiliated with, endorsed by or sponsored by Claris International Inc.
"FileMaker" is a trademark of Claris International Inc.; it is used here only
to describe what this prototype imitates.

  Browser     the FileMaker work: the calculation language, relationships and
              portals, scripts and the Script Workspace, layouts and the Layout
              mode designer, Browse/Find/Layout/Preview modes, reports, charts,
              import/export. Code: filemaker_assets/*.js.
  Host        this module. It stores each database file (its schema as JSON,
              its records, its accounts), enforces the file's privilege sets on
              every read and write, locks a record while someone edits it, and
              feeds each change to everyone else who has the file open.

Files, accounts and records live in the app's SQLite database in the fm_*
tables. Container data (files dropped into container fields) is stored on
disk under DATA_DIR/filemaker_files/<file id>/.

Opening a file signs in to one of the file's own accounts (like FileMaker's
"Open file" dialog). The browser then sends "X-FM-Session: <token>" with every
call; the token is tied to the app login that opened the file.

Hooked into app.py with init_filemaker(app, csrf, DB_PATH, data_dir=DATA_DIR).
See FILEMAKER_README.md.
"""
import hashlib
import io
import ipaddress
import json
import os
import re
import secrets
import socket
import sqlite3
import threading
import time
from datetime import date, datetime, time as dtime
from urllib.parse import urljoin, urlparse

import requests as http_requests
from flask import Blueprint, Response, jsonify, redirect, render_template_string, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

bp = Blueprint('filemaker', __name__, static_folder='filemaker_assets', static_url_path='/filemaker/static')

# ── who may use it ───────────────────────────────────────────────────────────
FILEMAKER_ROLES = ('office',)
NEVER_ROLES = ('technician', 'property_manager')
# Optional: exactly these usernames (comma-separated), whatever their role.
FILEMAKER_USERS = {u.strip().lower() for u in os.environ.get('FILEMAKER_USERS', '').split(',') if u.strip()}

# ── limits ───────────────────────────────────────────────────────────────────
MAX_SCHEMA_BYTES = 8 * 1024 * 1024
MAX_RECORD_BYTES = 1024 * 1024
MAX_BATCH_OPS = 20000
MAX_CONTAINER_BYTES = 25 * 1024 * 1024
MAX_FETCH_BYTES = 5 * 1024 * 1024
SESSION_TTL = 90          # seconds without a poll before a session counts as gone
LOCK_TTL = 60             # a lock whose holder has not polled for this long is free
FAILED_LOGIN_LIMIT = 5
FAILED_LOGIN_WINDOW = 300

FIELD_TYPES = ('text', 'number', 'date', 'time', 'timestamp', 'container', 'calculation', 'summary')
FULL, ENTRY, READONLY = 'PS_FULL', 'PS_ENTRY', 'PS_READ'
EXTENDED_PRIVILEGES = [
    {'key': 'fmapp', 'name': 'Access via FileMaker Network'},
    {'key': 'fmwebdirect', 'name': 'Access via FileMaker WebDirect (planned)'},
    {'key': 'fmrest', 'name': 'Access via FileMaker Data API (planned)'},
    {'key': 'fmxdbc', 'name': 'Access via ODBC/JDBC (planned)'},
    {'key': 'fmxml', 'name': 'Access via XML Web Publishing (planned)'},
    {'key': 'fmurlscript', 'name': 'Allow URLs to run FileMaker scripts'},
    {'key': 'fmreauthenticate10', 'name': 'Re-authenticate after sleep (10 minutes)'},
]


def _builtin_sets():
    def base(pid, name, desc, records, layouts, scripts, menus, ext):
        return {'id': pid, 'name': name, 'description': desc, 'builtin': True,
                'records': {'mode': records, 'tables': {}},
                'layouts': {'mode': layouts, 'items': {}, 'allowNew': layouts == 'all_modify'},
                'valueLists': {'mode': layouts, 'items': {}, 'allowNew': layouts == 'all_modify'},
                'scripts': {'mode': scripts, 'items': {}, 'allowNew': scripts == 'all_modify'},
                'extended': ext, 'printing': True, 'exporting': True, 'manageExtended': pid == FULL,
                'overrideValidation': pid == FULL, 'idleDisconnect': pid != FULL,
                'modifyOwnPassword': True, 'menus': menus}
    return [
        base(FULL, '[Full Access]', 'access to everything', 'all_ced', 'all_modify', 'all_modify', 'all',
             ['fmapp']),
        base(ENTRY, '[Data Entry Only]', 'write access to all records, no design access', 'all_ced', 'all_view',
             'all_exec', 'editing', ['fmapp']),
        base(READONLY, '[Read-Only Access]', 'read access to all records', 'all_view', 'all_view', 'all_exec',
             'editing', ['fmapp']),
    ]


_db_path = None
_data_dir = None
_log_activity = None
_schema_cache = {}
_schema_lock = threading.Lock()
_failed_logins = {}
_last_cleanup = [0.0]


# ═════════════════════════════════════════════════════════════════════════════
# basics
# ═════════════════════════════════════════════════════════════════════════════

def _now_text():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _conn():
    conn = sqlite3.connect(_db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = sqlite3.connect(_db_path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS fm_files (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  schema TEXT NOT NULL,
                  schema_version INTEGER NOT NULL DEFAULT 1,
                  created_by TEXT,
                  created_at TEXT NOT NULL,
                  modified_at TEXT NOT NULL,
                  modified_by TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS fm_accounts (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  file_id INTEGER NOT NULL,
                  name TEXT NOT NULL,
                  password_hash TEXT NOT NULL DEFAULT '',
                  privilege_set TEXT NOT NULL,
                  active INTEGER NOT NULL DEFAULT 1,
                  must_change INTEGER NOT NULL DEFAULT 0,
                  description TEXT DEFAULT '',
                  created_at TEXT NOT NULL)''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_fm_accounts_file ON fm_accounts(file_id)")
    # pending_token: a record made with New Record that has not been committed
    # yet. Only the session that made it can see it; it is removed if that
    # session reverts it or goes away.
    c.execute('''CREATE TABLE IF NOT EXISTS fm_records (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  file_id INTEGER NOT NULL,
                  table_id TEXT NOT NULL,
                  data TEXT NOT NULL DEFAULT '{}',
                  created_at TEXT NOT NULL,
                  created_by TEXT,
                  modified_at TEXT NOT NULL,
                  modified_by TEXT,
                  mod_count INTEGER NOT NULL DEFAULT 0,
                  pending_token TEXT)''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_fm_records_table ON fm_records(file_id, table_id)")
    c.execute('''CREATE TABLE IF NOT EXISTS fm_serials (
                  file_id INTEGER NOT NULL,
                  field_id TEXT NOT NULL,
                  next_value TEXT NOT NULL,
                  PRIMARY KEY (file_id, field_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS fm_sessions (
                  token TEXT PRIMARY KEY,
                  file_id INTEGER NOT NULL,
                  account_id INTEGER NOT NULL,
                  account_name TEXT NOT NULL,
                  app_user TEXT NOT NULL,
                  app_name TEXT,
                  opened_at TEXT NOT NULL,
                  last_seen REAL NOT NULL,
                  closed INTEGER NOT NULL DEFAULT 0,
                  kicked INTEGER NOT NULL DEFAULT 0,
                  kick_message TEXT)''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_fm_sessions_file ON fm_sessions(file_id)")
    c.execute('''CREATE TABLE IF NOT EXISTS fm_locks (
                  file_id INTEGER NOT NULL,
                  lock_key TEXT NOT NULL,
                  token TEXT NOT NULL,
                  holder TEXT,
                  acquired_at TEXT NOT NULL,
                  PRIMARY KEY (file_id, lock_key))''')
    c.execute('''CREATE TABLE IF NOT EXISTS fm_changes (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT,
                  file_id INTEGER NOT NULL,
                  kind TEXT NOT NULL,
                  table_id TEXT,
                  record_id INTEGER,
                  token TEXT,
                  actor TEXT,
                  at REAL NOT NULL)''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_fm_changes_file ON fm_changes(file_id, seq)")
    c.execute('''CREATE TABLE IF NOT EXISTS fm_messages (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  file_id INTEGER NOT NULL,
                  to_token TEXT NOT NULL,
                  from_name TEXT,
                  text TEXT NOT NULL,
                  at TEXT NOT NULL,
                  delivered INTEGER NOT NULL DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS fm_containers (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  file_id INTEGER NOT NULL,
                  name TEXT NOT NULL,
                  mime TEXT,
                  size INTEGER NOT NULL DEFAULT 0,
                  sha1 TEXT,
                  created_at TEXT NOT NULL,
                  created_by TEXT)''')
    conn.commit()
    conn.close()


def filemaker_allowed():
    """May this login see FileMaker (the dashboard tile and /filemaker)?"""
    if 'username' not in session or session.get('role') in NEVER_ROLES:
        return False
    if FILEMAKER_USERS:
        return session['username'].lower() in FILEMAKER_USERS
    return session.get('role') in FILEMAKER_ROLES


def _app_user():
    return (session.get('username') or '').lower()


def _app_name():
    return session.get('full_name') or session.get('username') or ''


def _err(message, code=400, **extra):
    return jsonify({'success': False, 'error': message, **extra}), code


def _body():
    return request.get_json(silent=True) or {}


def _log(action, details, target_id=None):
    if _log_activity:
        try:
            _log_activity(session.get('username', ''), action, 'filemaker', target_id, details)
        except Exception:
            pass


def serial_increment(text, by=1):
    """FileMaker's SerialIncrement: 'INV0009' + 1 -> 'INV0010'; '99' + 1 -> '100'."""
    text = str(text or '')
    m = re.search(r'(\d+)(?!.*\d)', text)
    if not m:
        return text + str(by)
    digits = m.group(1)
    n = max(0, int(digits) + int(by))
    return text[:m.start(1)] + str(n).zfill(len(digits)) + text[m.end(1):]


# ═════════════════════════════════════════════════════════════════════════════
# schema: cleaning, caching, privileges
# ═════════════════════════════════════════════════════════════════════════════

def blank_schema():
    return {'format': 1, 'tables': [], 'tableOccurrences': [], 'relationships': [], 'layouts': [],
            'layoutOrder': [], 'scripts': [], 'scriptOrder': [], 'valueLists': [], 'customFunctions': [],
            'privilegeSets': _builtin_sets(), 'extendedPrivileges': EXTENDED_PRIVILEGES,
            'themes': [], 'fileOptions': {'autoLogin': {'enabled': True, 'account': 'Admin'}}}


def _ids(items, what):
    seen = set()
    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get('id'), str) or not it['id']:
            raise ValueError(f'Every {what} needs an id')
        if it['id'] in seen:
            raise ValueError(f'Two {what}s share the id {it["id"]}')
        seen.add(it['id'])
    return seen


def clean_schema(schema):
    """Check the shape the host relies on and put the built-in privilege sets back.
    Raises ValueError with a message for the person editing."""
    if not isinstance(schema, dict):
        raise ValueError('The schema must be an object')
    out = blank_schema()
    out.update({k: v for k, v in schema.items() if k in out or k in ('theme', 'meta')})
    for key in ('tables', 'tableOccurrences', 'relationships', 'layouts', 'layoutOrder', 'scripts', 'scriptOrder',
                'valueLists', 'customFunctions', 'privilegeSets', 'themes'):
        if not isinstance(out.get(key), list):
            raise ValueError(f'"{key}" must be a list')
    if not isinstance(out.get('fileOptions'), dict):
        raise ValueError('"fileOptions" must be an object')
    table_ids = _ids(out['tables'], 'table')
    names = set()
    for t in out['tables']:
        n = str(t.get('name') or '').strip()
        if not n:
            raise ValueError('Every table needs a name')
        if n.lower() in names:
            raise ValueError(f'There are two tables named "{n}"')
        names.add(n.lower())
        if not isinstance(t.get('fields'), list):
            raise ValueError(f'Table "{n}" has no field list')
        _ids(t['fields'], 'field')
        fnames = set()
        for f in t['fields']:
            fn = str(f.get('name') or '').strip()
            if not fn:
                raise ValueError(f'A field in "{n}" has no name')
            if fn.lower() in fnames:
                raise ValueError(f'Table "{n}" has two fields named "{fn}"')
            fnames.add(fn.lower())
            if f.get('type') not in FIELD_TYPES:
                raise ValueError(f'Field "{fn}" has an unknown type')
    to_ids = _ids(out['tableOccurrences'], 'table occurrence')
    tonames = set()
    for to in out['tableOccurrences']:
        if to.get('table') not in table_ids:
            raise ValueError(f'Table occurrence "{to.get("name")}" points at a table that does not exist')
        n = str(to.get('name') or '').strip().lower()
        if not n or n in tonames:
            raise ValueError(f'Table occurrence names must be unique ("{to.get("name")}")')
        tonames.add(n)
    _ids(out['relationships'], 'relationship')
    for r in out['relationships']:
        if r.get('left') not in to_ids or r.get('right') not in to_ids:
            raise ValueError('A relationship points at a table occurrence that does not exist')
    for lay in _ids_list(out['layouts'], 'layout'):
        if lay.get('to') and lay['to'] not in to_ids:
            raise ValueError(f'Layout "{lay.get("name")}" is based on a table occurrence that does not exist')
    _ids(out['scripts'], 'script')
    _ids(out['valueLists'], 'value list')
    _ids(out['customFunctions'], 'custom function')
    # Privilege sets: built-ins always present and unchangeable apart from
    # their extended privileges (as in FileMaker).
    sets = [p for p in out['privilegeSets'] if isinstance(p, dict) and not p.get('builtin')]
    _ids(sets, 'privilege set')
    given = {p.get('id'): p for p in out['privilegeSets'] if isinstance(p, dict)}
    builtins = []
    for b in _builtin_sets():
        if isinstance(given.get(b['id']), dict) and isinstance(given[b['id']].get('extended'), list):
            ext = [str(x) for x in given[b['id']]['extended']][:50]
            b['extended'] = sorted(set(ext) | ({'fmapp'} if b['id'] == FULL else set()))
        builtins.append(b)
    for p in sets:
        if p['id'] in (FULL, ENTRY, READONLY):
            raise ValueError('That privilege set id is reserved')
        _check_privilege_set(p, out)
    out['privilegeSets'] = builtins + sets
    out['extendedPrivileges'] = _clean_extended(out.get('extendedPrivileges'))
    raw = json.dumps(out, separators=(',', ':'))
    if len(raw) > MAX_SCHEMA_BYTES:
        raise ValueError('This file\'s design is too large to save (8 MB limit)')
    return out


def _ids_list(items, what):
    _ids(items, what)
    return items


def _clean_extended(ext):
    keys = {e['key'] for e in EXTENDED_PRIVILEGES}
    out = list(EXTENDED_PRIVILEGES)
    for e in ext or []:
        if isinstance(e, dict) and isinstance(e.get('key'), str) and e['key'] not in keys and \
                re.fullmatch(r'[A-Za-z0-9_]{1,40}', e['key']):
            out.append({'key': e['key'], 'name': str(e.get('name') or e['key'])[:120]})
            keys.add(e['key'])
    return out


def _check_privilege_set(p, schema):
    if not str(p.get('name') or '').strip():
        raise ValueError('Every privilege set needs a name')
    rec = p.get('records') if isinstance(p.get('records'), dict) else {}
    if rec.get('mode') not in ('all_ced', 'all_ce', 'all_view', 'none', 'custom'):
        raise ValueError(f'Privilege set "{p["name"]}": unknown record access')
    tables = {t['id']: t for t in schema['tables']}
    for tid, tp in (rec.get('tables') or {}).items():
        if tid not in tables or not isinstance(tp, dict):
            continue
        for key in ('view', 'edit', 'delete'):
            if tp.get(key) == 'limited':
                try:
                    RecordCalc(tp.get(key + 'Calc') or '', tables[tid], schema)
                except ValueError as e:
                    raise ValueError(f'Privilege set "{p["name"]}", table "{tables[tid]["name"]}", '
                                     f'{key} limited: {e}')


def _load_schema(conn, file_id):
    row = conn.execute("SELECT schema, schema_version FROM fm_files WHERE id=?", (file_id,)).fetchone()
    if not row:
        return None, 0
    with _schema_lock:
        hit = _schema_cache.get(file_id)
        if hit and hit[0] == row['schema_version']:
            return hit[1], hit[0]
    schema = json.loads(row['schema'])
    with _schema_lock:
        _schema_cache[file_id] = (row['schema_version'], schema)
    return schema, row['schema_version']


def _pset(schema, pid):
    for p in schema.get('privilegeSets') or []:
        if p.get('id') == pid:
            return p
    return None


def is_full(pset):
    return bool(pset) and pset.get('id') == FULL


def table_priv(pset, table):
    """{'view','edit','create','delete'} -> 'yes'/'no'/'limited', plus calcs and field access."""
    tid = table['id']
    if is_full(pset):
        return {'view': 'yes', 'edit': 'yes', 'create': 'yes', 'delete': 'yes', 'fields': 'all'}
    mode = ((pset or {}).get('records') or {}).get('mode', 'none')
    if mode == 'all_ced':
        return {'view': 'yes', 'edit': 'yes', 'create': 'yes', 'delete': 'yes', 'fields': 'all'}
    if mode == 'all_ce':
        return {'view': 'yes', 'edit': 'yes', 'create': 'yes', 'delete': 'no', 'fields': 'all'}
    if mode == 'all_view':
        return {'view': 'yes', 'edit': 'no', 'create': 'no', 'delete': 'no', 'fields': 'all'}
    if mode == 'custom':
        tp = ((pset.get('records') or {}).get('tables') or {}).get(tid) or \
            ((pset.get('records') or {}).get('tables') or {}).get('*new*')
        if isinstance(tp, dict):
            out = {k: (tp.get(k) if tp.get(k) in ('yes', 'no', 'limited') else 'no')
                   for k in ('view', 'edit', 'delete')}
            out['create'] = 'yes' if tp.get('create') == 'yes' else 'no'
            for k in ('view', 'edit', 'delete'):
                if out[k] == 'limited':
                    out[k + 'Calc'] = tp.get(k + 'Calc') or ''
            out['fields'] = tp.get('fields') if isinstance(tp.get('fields'), dict) else 'all'
            if out['view'] == 'no':
                out.update(edit='no', delete='no', create='no')
            return out
    return {'view': 'no', 'edit': 'no', 'create': 'no', 'delete': 'no', 'fields': 'all'}


def field_access(tp, field_id):
    f = tp.get('fields')
    if f == 'all' or not isinstance(f, dict):
        return 'modify'
    v = f.get(field_id) or f.get('*new*') or 'modify'
    return v if v in ('modify', 'view', 'none') else 'modify'


def _layout_modify_ok(pset, layout_id, is_new):
    if is_full(pset):
        return True
    lay = (pset or {}).get('layouts') or {}
    if lay.get('mode') == 'all_modify':
        return True
    if lay.get('mode') == 'custom':
        if is_new:
            return bool(lay.get('allowNew'))
        return ((lay.get('items') or {}).get(layout_id) or {}).get('layout') == 'modify'
    return False


def _script_modify_ok(pset, script_id, is_new):
    if is_full(pset):
        return True
    sc = (pset or {}).get('scripts') or {}
    if sc.get('mode') == 'all_modify':
        return True
    if sc.get('mode') == 'custom':
        if is_new:
            return bool(sc.get('allowNew'))
        return (sc.get('items') or {}).get(script_id) == 'modify'
    return False


def _valuelist_modify_ok(pset, vl_id, is_new):
    if is_full(pset):
        return True
    vl = (pset or {}).get('valueLists') or {}
    if vl.get('mode') == 'all_modify':
        return True
    if vl.get('mode') == 'custom':
        if is_new:
            return bool(vl.get('allowNew'))
        return (vl.get('items') or {}).get(vl_id) == 'modify'
    return False


# ── record-level access calculations ─────────────────────────────────────────
# FileMaker lets a privilege set limit which records it may view, edit or
# delete with a calculation. The host must check these itself, so it has its
# own small evaluator for the formulas such rules are written with: fields of
# the record, text and number literals, Get(AccountName),
# Get(AccountPrivilegeSetName), Get(UserName), IsEmpty, PatternCount, Lower,
# Upper, Trim, If, Case, comparison, &, and/or/xor/not. Anything else is
# refused when the privilege set is saved, so a rule is never half-enforced.

class RecordCalc:
    FUNCS = ('get', 'isempty', 'patterncount', 'lower', 'upper', 'trim', 'if', 'case', 'not')

    def __init__(self, formula, table, schema):
        self.table = table
        self.fields = sorted(((f['name'], f) for f in table['fields']), key=lambda x: -len(x[0]))
        self.tos = {to['name'].lower() for to in schema.get('tableOccurrences', []) if to.get('table') == table['id']}
        self.src = re.sub(r'//[^\n]*|/\*.*?\*/', ' ', str(formula or ''), flags=re.S)
        if not self.src.strip():
            raise ValueError('the calculation is empty')
        self.pos = 0
        self.tree = self._expr()
        self._skip()
        if self.pos < len(self.src):
            raise ValueError(f'unexpected "{self.src[self.pos:self.pos + 12]}"')

    # parsing
    def _skip(self):
        while self.pos < len(self.src) and self.src[self.pos].isspace():
            self.pos += 1

    def _peek_word(self, *words):
        self._skip()
        for w in words:
            seg = self.src[self.pos:self.pos + len(w)]
            after = self.src[self.pos + len(w):self.pos + len(w) + 1]
            if seg.lower() == w and (not after or not (after.isalnum() or after == '_')):
                return w
        return None

    def _eat(self, ch):
        self._skip()
        if self.src.startswith(ch, self.pos):
            self.pos += len(ch)
            return True
        return False

    def _expr(self):
        left = self._and()
        while True:
            w = self._peek_word('or', 'xor')
            if not w:
                return left
            self.pos += len(w)
            left = (w, left, self._and())

    def _and(self):
        left = self._not()
        while self._peek_word('and'):
            self.pos += 3
            left = ('and', left, self._not())
        return left

    def _not(self):
        if self._peek_word('not') and not self.src[self.pos + 3:].lstrip().startswith('('):
            self.pos += 3
            return ('not', self._not())
        return self._cmp()

    def _cmp(self):
        left = self._concat()
        self._skip()
        for op in ('<>', '≠', '<=', '≤', '>=', '≥', '=', '<', '>'):
            if self.src.startswith(op, self.pos):
                self.pos += len(op)
                return ('cmp', op, left, self._concat())
        return left

    def _concat(self):
        left = self._atom()
        while self._eat('&'):
            left = ('cat', left, self._atom())
        return left

    def _atom(self):
        self._skip()
        s = self.src
        if self.pos >= len(s):
            raise ValueError('the calculation ends too soon')
        ch = s[self.pos]
        if ch == '(':
            self.pos += 1
            inner = self._expr()
            if not self._eat(')'):
                raise ValueError('a ")" is missing')
            return inner
        if ch == '"':
            m = re.match(r'"((?:[^"\\]|\\.)*)"', s[self.pos:])
            if not m:
                raise ValueError('a text constant is not closed')
            self.pos += m.end()
            return ('lit', re.sub(r'\\(.)', r'\1', m.group(1)).replace('¶', '\n'))
        m = re.match(r'\d+(?:\.\d+)?|\.\d+', s[self.pos:])
        if m:
            self.pos += m.end()
            return ('lit', float(m.group(0)))
        for w in ('true', 'false'):
            if self._peek_word(w):
                self.pos += len(w)
                return ('lit', 1.0 if w == 'true' else 0.0)
        # a field: "Field Name" or "TO::Field Name", longest match wins
        rest = s[self.pos:]
        m = re.match(r'([^\s:();"=<>&]+(?: [^\s:();"=<>&]+)*?)\s*::', rest)
        prefix_len = 0
        if m and m.group(1).lower() in self.tos:
            prefix_len = m.end()
            rest = rest[prefix_len:].lstrip()
            prefix_len = len(s[self.pos:]) - len(rest)
        for name, f in self.fields:
            if rest[:len(name)].lower() == name.lower():
                nxt = rest[len(name):len(name) + 1]
                if not nxt or not (nxt.isalnum() or nxt == '_'):
                    self.pos += prefix_len + len(name)
                    if f['type'] in ('calculation', 'summary', 'container') or \
                            ((f.get('options') or {}).get('storage') or {}).get('global'):
                        raise ValueError(f'the host cannot check "{name}" (only stored text, number, date '
                                         'and time fields can be used here)')
                    return ('field', f['id'], f['type'])
        if prefix_len:
            raise ValueError('unknown field after "::"')
        m = re.match(r'[A-Za-z_][A-Za-z0-9_]*', rest)
        if not m:
            raise ValueError(f'unexpected "{rest[:12]}"')
        word = m.group(0)
        if word.lower() not in self.FUNCS:
            raise ValueError(f'"{word}" is not a field of this table or a function the host can check '
                             '(use fields, Get(AccountName), Get(AccountPrivilegeSetName), Get(UserName), '
                             'IsEmpty, PatternCount, Lower, Upper, Trim, If, Case)')
        self.pos += m.end()
        if not self._eat('('):
            raise ValueError(f'"{word}" needs "("')
        if word.lower() == 'get':
            self._skip()
            m = re.match(r'[A-Za-z]+', s[self.pos:])
            arg = (m.group(0) if m else '').lower()
            if arg not in ('accountname', 'accountprivilegesetname', 'username'):
                raise ValueError('only Get(AccountName), Get(AccountPrivilegeSetName) and Get(UserName) '
                                 'can be used here')
            self.pos += m.end()
            if not self._eat(')'):
                raise ValueError('a ")" is missing')
            return ('get', arg)
        args = [self._expr()]
        while self._eat(';') or self._eat(','):
            args.append(self._expr())
        if not self._eat(')'):
            raise ValueError('a ")" is missing')
        need = {'isempty': (1, 1), 'patterncount': (2, 2), 'lower': (1, 1), 'upper': (1, 1), 'trim': (1, 1),
                'if': (2, 3), 'case': (2, 99), 'not': (1, 1)}[word.lower()]
        if not need[0] <= len(args) <= need[1]:
            raise ValueError(f'{word} has the wrong number of parameters')
        return ('fn', word.lower(), args)

    # evaluating
    @staticmethod
    def _num(v):
        if isinstance(v, float):
            return v
        m = re.sub(r'[^0-9.\-]', '', str(v or ''))
        try:
            return float(m) if m not in ('', '-', '.', '-.') else 0.0
        except ValueError:
            return 0.0

    @classmethod
    def truth(cls, v):
        return cls._num(v) != 0

    @staticmethod
    def _text(v):
        if isinstance(v, float):
            return str(int(v)) if v.is_integer() else repr(v)
        return '' if v is None else str(v)

    def evaluate(self, data, ctx):
        return self.truth(self._ev(self.tree, data, ctx))

    def _ev(self, n, data, ctx):
        k = n[0]
        if k == 'lit':
            return n[1]
        if k == 'field':
            v = data.get(n[1], '')
            if isinstance(v, list):
                v = v[0] if v else ''
            if n[2] == 'number' and str(v).strip() != '':
                return self._num(v)
            return '' if v is None else str(v)
        if k == 'get':
            return {'accountname': ctx.get('account', ''), 'accountprivilegesetname': ctx.get('privset', ''),
                    'username': ctx.get('user', '')}[n[1]]
        if k == 'cat':
            return self._text(self._ev(n[1], data, ctx)) + self._text(self._ev(n[2], data, ctx))
        if k == 'not':
            return 0.0 if self.truth(self._ev(n[1], data, ctx)) else 1.0
        if k in ('and', 'or', 'xor'):
            a = self.truth(self._ev(n[1], data, ctx))
            if k == 'and' and not a:
                return 0.0
            if k == 'or' and a:
                return 1.0
            b = self.truth(self._ev(n[2], data, ctx))
            return 1.0 if (a and b if k == 'and' else a or b if k == 'or' else a != b) else 0.0
        if k == 'cmp':
            a, b = self._ev(n[2], data, ctx), self._ev(n[3], data, ctx)
            if isinstance(a, float) and isinstance(b, float):
                x, y = a, b
            elif isinstance(a, float) or isinstance(b, float):
                sa, sb = self._text(a), self._text(b)
                if sa == '' or sb == '':
                    x, y = sa, sb
                else:
                    x, y = self._num(a), self._num(b)
            else:
                x, y = self._text(a).lower(), self._text(b).lower()
            op = n[1]
            r = {'=': x == y, '<>': x != y, '≠': x != y, '<': x < y, '>': x > y,
                 '<=': x <= y, '≤': x <= y, '>=': x >= y, '≥': x >= y}[op]
            return 1.0 if r else 0.0
        if k == 'fn':
            name, args = n[1], n[2]
            if name == 'if':
                if self.truth(self._ev(args[0], data, ctx)):
                    return self._ev(args[1], data, ctx)
                return self._ev(args[2], data, ctx) if len(args) > 2 else ''
            if name == 'case':
                for i in range(0, len(args) - 1, 2):
                    if self.truth(self._ev(args[i], data, ctx)):
                        return self._ev(args[i + 1], data, ctx)
                return self._ev(args[-1], data, ctx) if len(args) % 2 else ''
            vals = [self._ev(a, data, ctx) for a in args]
            if name == 'isempty':
                return 1.0 if self._text(vals[0]) == '' else 0.0
            if name == 'not':
                return 0.0 if self.truth(vals[0]) else 1.0
            if name == 'patterncount':
                hay, needle = self._text(vals[0]).lower(), self._text(vals[1]).lower()
                return float(hay.count(needle)) if needle else 0.0
            if name == 'lower':
                return self._text(vals[0]).lower()
            if name == 'upper':
                return self._text(vals[0]).upper()
            if name == 'trim':
                return self._text(vals[0]).strip()
        raise ValueError('cannot evaluate')


# ═════════════════════════════════════════════════════════════════════════════
# sessions (an open file)
# ═════════════════════════════════════════════════════════════════════════════

class Ctx:
    """The caller's open file: session row, schema, account and privilege set."""

    def __init__(self, conn, file_id, srow, schema, version, pset):
        self.conn, self.file_id, self.s, self.schema, self.version, self.pset = \
            conn, file_id, srow, schema, version, pset
        self.token = srow['token']
        self.account = srow['account_name']
        self.tables = {t['id']: t for t in schema['tables']}
        self._calc = {}

    @property
    def full(self):
        return is_full(self.pset)

    @property
    def eval_ctx(self):
        return {'account': self.account, 'privset': (self.pset or {}).get('name', ''), 'user': _app_name()}

    def tp(self, table_id):
        t = self.tables.get(table_id)
        return table_priv(self.pset, t) if t else None

    def allowed(self, tp, what, data):
        """Is 'view'/'edit'/'delete' allowed for this record's stored data?"""
        v = tp.get(what)
        if v == 'yes':
            return True
        if v != 'limited':
            return False
        key = (what, tp.get(what + 'Calc', ''))
        rc = self._calc.get(key)
        if rc is None:
            try:
                rc = RecordCalc(tp.get(what + 'Calc', ''), self.tables[self._table_of(tp)], self.schema)
            except (ValueError, KeyError):
                rc = False
            self._calc[key] = rc
        if rc is False:
            return False
        try:
            return rc.evaluate(data, self.eval_ctx)
        except Exception:
            return False

    def _table_of(self, tp):
        return tp['_table']


def _ctx(conn, file_id):
    """The caller's session for this file, or an error response."""
    token = request.headers.get('X-FM-Session', '')
    if not token:
        return None, _err('This file is not open', 401, closed=True)
    srow = conn.execute("SELECT * FROM fm_sessions WHERE token=? AND file_id=?", (token, file_id)).fetchone()
    if not srow or srow['app_user'] != _app_user() or srow['closed']:
        return None, _err('This file is not open', 401, closed=True)
    if srow['kicked']:
        return None, _err(srow['kick_message'] or 'You were disconnected by the host', 401, closed=True,
                          kicked=True)
    acct = conn.execute("SELECT * FROM fm_accounts WHERE id=? AND file_id=?",
                        (srow['account_id'], file_id)).fetchone()
    if not acct or not acct['active']:
        return None, _err('Your account was disabled or deleted', 401, closed=True)
    schema, version = _load_schema(conn, file_id)
    if schema is None:
        return None, _err('That file no longer exists', 404, closed=True)
    pset = _pset(schema, acct['privilege_set'])
    if not pset:
        return None, _err('Your privilege set no longer exists', 401, closed=True)
    now = time.time()
    if now - srow['last_seen'] > 5:
        conn.execute("UPDATE fm_sessions SET last_seen=? WHERE token=?", (now, token))
        conn.commit()
    return Ctx(conn, file_id, srow, schema, version, pset), None


def _tp(ctx, table_id):
    tp = ctx.tp(table_id)
    if tp is not None:
        tp['_table'] = table_id
    return tp


def _cleanup(conn, force=False):
    """Close sessions that stopped polling; drop their uncommitted records and locks."""
    now = time.time()
    if not force and now - _last_cleanup[0] < 20:
        return
    _last_cleanup[0] = now
    stale = [r['token'] for r in conn.execute(
        "SELECT token FROM fm_sessions WHERE closed=0 AND last_seen<?", (now - SESSION_TTL,))]
    for tok in stale:
        _end_session(conn, tok)
    conn.execute("DELETE FROM fm_sessions WHERE closed=1 AND last_seen<?", (now - 7 * 86400,))
    conn.execute("DELETE FROM fm_changes WHERE at<?", (now - 2 * 86400,))
    conn.execute("DELETE FROM fm_messages WHERE delivered=1")
    conn.commit()


def _end_session(conn, token):
    conn.execute("DELETE FROM fm_records WHERE pending_token=?", (token,))
    conn.execute("DELETE FROM fm_locks WHERE token=?", (token,))
    conn.execute("UPDATE fm_sessions SET closed=1 WHERE token=?", (token,))


def _live_tokens(conn, file_id):
    return {r['token'] for r in conn.execute(
        "SELECT token FROM fm_sessions WHERE file_id=? AND closed=0 AND kicked=0 AND last_seen>=?",
        (file_id, time.time() - LOCK_TTL))}


def _change(conn, file_id, kind, token, actor, table_id=None, record_id=None):
    conn.execute("INSERT INTO fm_changes (file_id, kind, table_id, record_id, token, actor, at) VALUES (?,?,?,?,?,?,?)",
                 (file_id, kind, table_id, record_id, token, actor, time.time()))


def _seq(conn, file_id):
    return conn.execute("SELECT COALESCE(MAX(seq), 0) FROM fm_changes").fetchone()[0]


def _users(conn, file_id):
    rows = conn.execute("""SELECT token, account_name, app_name, app_user, opened_at, last_seen FROM fm_sessions
                           WHERE file_id=? AND closed=0 AND kicked=0 AND last_seen>=? ORDER BY opened_at""",
                        (file_id, time.time() - SESSION_TTL)).fetchall()
    return [{'id': hashlib.sha1(r['token'].encode()).hexdigest()[:12], 'account': r['account_name'],
             'user': r['app_name'] or r['app_user'], 'opened': r['opened_at'],
             'idle': int(time.time() - r['last_seen'])} for r in rows]


def _token_for_user_id(conn, file_id, uid):
    for r in conn.execute("SELECT token FROM fm_sessions WHERE file_id=? AND closed=0", (file_id,)):
        if hashlib.sha1(r['token'].encode()).hexdigest()[:12] == uid:
            return r['token']
    return None


# ═════════════════════════════════════════════════════════════════════════════
# records
# ═════════════════════════════════════════════════════════════════════════════

def _record_out(ctx, row, tp=None):
    tp = tp or _tp(ctx, row['table_id'])
    data = json.loads(row['data'] or '{}')
    out = {'id': row['id'], 't': row['table_id'], 'c': row['created_at'], 'cb': row['created_by'],
           'm': row['modified_at'], 'mb': row['modified_by'], 'mc': row['mod_count']}
    if row['pending_token']:
        out['pending'] = True
    if not ctx.allowed(tp, 'view', data):
        out['d'] = {}
        out['noaccess'] = True
        return out
    if tp.get('fields') != 'all':
        data = {k: v for k, v in data.items() if field_access(tp, k) != 'none'}
    out['d'] = data
    out['canEdit'] = ctx.allowed(tp, 'edit', data) if tp.get('edit') == 'limited' else tp.get('edit') == 'yes'
    out['canDelete'] = ctx.allowed(tp, 'delete', data) if tp.get('delete') == 'limited' else tp.get('delete') == 'yes'
    return out


def _clean_data(ctx, table, data, tp, creating):
    if not isinstance(data, dict):
        raise ValueError('Record data must be an object')
    fields = {f['id']: f for f in table['fields']}
    out = {}
    for k, v in data.items():
        f = fields.get(k)
        # calculations and summaries are worked out from the stored fields, never saved
        if not f or f['type'] in ('summary', 'calculation'):
            continue
        acc = field_access(tp, k)
        if acc == 'none' or (acc == 'view' and not creating):
            raise PermissionError(f'You do not have permission to modify "{f["name"]}"')
        if not (v is None or isinstance(v, (str, int, float, list, dict))):
            raise ValueError(f'"{f["name"]}" has a value of an unknown kind')
        out[k] = v
    if len(json.dumps(out)) > MAX_RECORD_BYTES:
        raise ValueError('That record is too large (1 MB limit)')
    return out


def _serial_fields(table, when):
    out = []
    for f in table['fields']:
        ser = ((f.get('options') or {}).get('autoEnter') or {}).get('serial')
        if isinstance(ser, dict) and ser.get('on') and (ser.get('generate') or 'create') == when:
            out.append((f, ser))
    return out


def _take_serials(conn, file_id, table, data, when):
    for f, ser in _serial_fields(table, when):
        row = conn.execute("SELECT next_value FROM fm_serials WHERE file_id=? AND field_id=?",
                           (file_id, f['id'])).fetchone()
        nxt = row['next_value'] if row else str(ser.get('next') or '1')
        data[f['id']] = nxt
        new = serial_increment(nxt, int(ser.get('increment') or 1))
        conn.execute("INSERT INTO fm_serials (file_id, field_id, next_value) VALUES (?,?,?) "
                     "ON CONFLICT(file_id, field_id) DO UPDATE SET next_value=excluded.next_value",
                     (file_id, f['id'], new))


def _lock_holder(conn, ctx, key):
    row = conn.execute("SELECT token, holder FROM fm_locks WHERE file_id=? AND lock_key=?",
                       (ctx.file_id, key)).fetchone()
    if not row or row['token'] == ctx.token:
        return None
    if row['token'] not in _live_tokens(conn, ctx.file_id):
        conn.execute("DELETE FROM fm_locks WHERE file_id=? AND lock_key=?", (ctx.file_id, key))
        return None
    return row['holder']


def _op_create(ctx, op):
    table = ctx.tables.get(op.get('table'))
    if not table:
        raise LookupError('That table does not exist')
    tp = _tp(ctx, table['id'])
    if tp['create'] != 'yes':
        raise PermissionError(f'You do not have permission to create records in "{table["name"]}"')
    data = _clean_data(ctx, table, op.get('data') or {}, tp, True)
    pending = bool(op.get('pending'))
    _take_serials(ctx.conn, ctx.file_id, table, data, 'create')
    if not pending:
        _take_serials(ctx.conn, ctx.file_id, table, data, 'commit')
    now = _now_text()
    cur = ctx.conn.execute("""INSERT INTO fm_records (file_id, table_id, data, created_at, created_by, modified_at,
                              modified_by, mod_count, pending_token) VALUES (?,?,?,?,?,?,?,0,?)""",
                           (ctx.file_id, table['id'], json.dumps(data), now, ctx.account, now, ctx.account,
                            ctx.token if pending else None))
    rid = cur.lastrowid
    if not pending:
        _change(ctx.conn, ctx.file_id, 'rec', ctx.token, ctx.account, table['id'], rid)
    return rid


def _op_update(ctx, op):
    rid = int(op.get('id') or 0)
    row = ctx.conn.execute("SELECT * FROM fm_records WHERE id=? AND file_id=?", (rid, ctx.file_id)).fetchone()
    if not row or (row['pending_token'] and row['pending_token'] != ctx.token):
        raise LookupError('That record no longer exists (it may have been deleted by another user)')
    table = ctx.tables.get(row['table_id'])
    if not table:
        raise LookupError('That table does not exist')
    tp = _tp(ctx, table['id'])
    old = json.loads(row['data'] or '{}')
    was_pending = bool(row['pending_token'])
    if not was_pending and not ctx.allowed(tp, 'edit', old):
        raise PermissionError(f'You do not have permission to modify this record in "{table["name"]}"')
    if was_pending and tp['create'] != 'yes':
        raise PermissionError(f'You do not have permission to create records in "{table["name"]}"')
    holder = _lock_holder(ctx.conn, ctx, f'rec:{rid}')
    if holder:
        raise BlockingIOError(f'This record is being modified by "{holder}"')
    if op.get('mc') is not None and int(op['mc']) != row['mod_count'] and not was_pending:
        raise InterruptedError('This record was changed by another user since you started editing it')
    changes = _clean_data(ctx, table, op.get('data') or {}, tp, was_pending)
    new = dict(old)
    new.update(changes)
    if not was_pending and tp.get('edit') == 'limited' and not ctx.allowed(tp, 'edit', new):
        raise PermissionError('You do not have permission to save the record with those values')
    commit = op.get('commit', True)
    if was_pending and commit:
        _take_serials(ctx.conn, ctx.file_id, table, new, 'commit')
    ctx.conn.execute("""UPDATE fm_records SET data=?, modified_at=?, modified_by=?, mod_count=mod_count+?,
                        pending_token=? WHERE id=?""",
                     (json.dumps(new), _now_text(), ctx.account, 0 if was_pending else 1,
                      ctx.token if (was_pending and not commit) else None, rid))
    if commit:
        ctx.conn.execute("DELETE FROM fm_locks WHERE file_id=? AND lock_key=? AND token=?",
                         (ctx.file_id, f'rec:{rid}', ctx.token))
        _change(ctx.conn, ctx.file_id, 'rec', ctx.token, ctx.account, table['id'], rid)
    return rid


def _op_delete(ctx, op):
    rid = int(op.get('id') or 0)
    row = ctx.conn.execute("SELECT * FROM fm_records WHERE id=? AND file_id=?", (rid, ctx.file_id)).fetchone()
    if not row or (row['pending_token'] and row['pending_token'] != ctx.token):
        return None
    tp = _tp(ctx, row['table_id'])
    if not row['pending_token']:
        table = ctx.tables.get(row['table_id']) or {'name': '?'}
        if not ctx.allowed(tp, 'delete', json.loads(row['data'] or '{}')):
            raise PermissionError(f'You do not have permission to delete this record in "{table["name"]}"')
        holder = _lock_holder(ctx.conn, ctx, f'rec:{rid}')
        if holder:
            raise BlockingIOError(f'This record is being modified by "{holder}" and cannot be deleted')
    ctx.conn.execute("DELETE FROM fm_records WHERE id=?", (rid,))
    ctx.conn.execute("DELETE FROM fm_locks WHERE file_id=? AND lock_key=?", (ctx.file_id, f'rec:{rid}'))
    if not row['pending_token']:
        _change(ctx.conn, ctx.file_id, 'del', ctx.token, ctx.account, row['table_id'], rid)
    return rid


def _run_ops(ctx, ops):
    """Apply record operations in one transaction. Raises on the first failure
    (the caller rolls back), naming which operation failed."""
    results = []
    for i, op in enumerate(ops):
        kind = op.get('op')
        try:
            if kind == 'create':
                rid = _op_create(ctx, op)
            elif kind == 'update':
                rid = _op_update(ctx, op)
            elif kind == 'delete':
                rid = _op_delete(ctx, op)
            else:
                raise ValueError(f'Unknown operation "{kind}"')
        except (ValueError, LookupError, PermissionError, BlockingIOError, InterruptedError) as e:
            e.index = i
            raise
        results.append({'op': kind, 'id': rid, 'ref': op.get('ref')})
    return results


_OP_ERRORS = ((PermissionError, 403, 200), (BlockingIOError, 409, 301), (InterruptedError, 409, 306),
              (LookupError, 404, 101), (ValueError, 400, 500))


def _op_error(e):
    for cls, http, fm in _OP_ERRORS:
        if isinstance(e, cls):
            return _err(str(e), http, fmError=fm, index=getattr(e, 'index', None))
    return _err(str(e), 400)


def _rows_out(ctx, ids):
    if not ids:
        return []
    out = []
    ids = list(ids)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        q = f"SELECT * FROM fm_records WHERE file_id=? AND id IN ({','.join('?' * len(chunk))})"
        for row in ctx.conn.execute(q, (ctx.file_id, *chunk)):
            if row['pending_token'] and row['pending_token'] != ctx.token:
                continue
            tp = _tp(ctx, row['table_id'])
            if tp and tp['view'] != 'no':
                out.append(_record_out(ctx, row, tp))
    return out


def _all_records(ctx):
    out = {}
    for t in ctx.schema['tables']:
        tp = _tp(ctx, t['id'])
        if tp['view'] == 'no':
            continue
        rows = ctx.conn.execute("""SELECT * FROM fm_records WHERE file_id=? AND table_id=?
                                   AND (pending_token IS NULL OR pending_token=?) ORDER BY id""",
                                (ctx.file_id, t['id'], ctx.token)).fetchall()
        out[t['id']] = [_record_out(ctx, r, tp) for r in rows]
    return out


def _serials(conn, file_id, schema):
    stored = {r['field_id']: r['next_value'] for r in conn.execute(
        "SELECT field_id, next_value FROM fm_serials WHERE file_id=?", (file_id,))}
    out = {}
    for t in schema['tables']:
        for f in t['fields']:
            ser = ((f.get('options') or {}).get('autoEnter') or {}).get('serial')
            if isinstance(ser, dict) and ser.get('on'):
                out[f['id']] = stored.get(f['id'], str(ser.get('next') or '1'))
    return out


# ═════════════════════════════════════════════════════════════════════════════
# HTTP: page
# ═════════════════════════════════════════════════════════════════════════════

def _asset_version():
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'filemaker_assets')
    h = hashlib.sha1()
    try:
        for name in sorted(os.listdir(folder)):
            h.update(f'{name}:{os.path.getmtime(os.path.join(folder, name))}'.encode())
    except OSError:
        pass
    return h.hexdigest()[:10]


@bp.route('/filemaker')
def page():
    if not filemaker_allowed():
        return redirect(url_for('login'))
    boot = {'user': _app_name(), 'username': session.get('username', ''),
            'dashboard': url_for('dashboard')}
    resp = Response(render_template_string(PAGE, boot=boot, v=_asset_version()))
    # The page needs a little more than the app's default policy: web viewers
    # (frames) and pictures from the web.
    resp.headers['Content-Security-Policy'] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https:; media-src 'self' blob: data:; font-src 'self' data:; "
        "frame-src 'self' https: data: blob:; connect-src 'self'")
    return resp


def _guard():
    if not filemaker_allowed():
        return _err('Not signed in to FileMaker', 401)
    return None


# ═════════════════════════════════════════════════════════════════════════════
# HTTP: hosted files
# ═════════════════════════════════════════════════════════════════════════════

@bp.route('/filemaker/api/files')
def list_files():
    if (g := _guard()):
        return g
    conn = _conn()
    try:
        _cleanup(conn)
        out = []
        for f in conn.execute("SELECT id, name, created_by, created_at, modified_at, schema FROM fm_files ORDER BY name COLLATE NOCASE"):
            n = conn.execute("SELECT COUNT(*) FROM fm_records WHERE file_id=? AND pending_token IS NULL",
                             (f['id'],)).fetchone()[0]
            users = conn.execute("SELECT COUNT(*) FROM fm_sessions WHERE file_id=? AND closed=0 AND kicked=0 "
                                 "AND last_seen>=?", (f['id'], time.time() - SESSION_TTL)).fetchone()[0]
            try:
                sch = json.loads(f['schema'])
                meta = {'tables': len(sch.get('tables', [])), 'layouts': len(sch.get('layouts', [])),
                        'scripts': len(sch.get('scripts', [])),
                        'color': (sch.get('fileOptions') or {}).get('color', '')}
            except ValueError:
                meta = {}
            out.append({'id': f['id'], 'name': f['name'], 'createdBy': f['created_by'], 'created': f['created_at'],
                        'modified': f['modified_at'], 'records': n, 'users': users, **meta})
        return jsonify({'success': True, 'files': out})
    finally:
        conn.close()


def _unique_name(conn, name, exclude=None):
    name = re.sub(r'[\\/:*?"<>|]', '', str(name or '')).strip()[:80] or 'Untitled'
    taken = {r[0].lower() for r in conn.execute("SELECT name FROM fm_files WHERE id IS NOT ?", (exclude,))}
    if name.lower() not in taken:
        return name
    i = 2
    while f'{name} {i}'.lower() in taken:
        i += 1
    return f'{name} {i}'


@bp.route('/filemaker/api/files', methods=['POST'])
def create_file():
    """{name, schema?, records?: {tableId: [data, ...]}, adminName?, adminPassword?}"""
    if (g := _guard()):
        return g
    body = _body()
    try:
        schema = clean_schema(body.get('schema') or blank_schema())
    except ValueError as e:
        return _err(str(e))
    admin = str(body.get('adminName') or 'Admin').strip()[:60] or 'Admin'
    pw = str(body.get('adminPassword') or '')
    if not pw:
        schema['fileOptions']['autoLogin'] = {'enabled': True, 'account': admin}
    else:
        schema['fileOptions']['autoLogin'] = {'enabled': False, 'account': admin}
    conn = _conn()
    try:
        name = _unique_name(conn, body.get('name'))
        now = _now_text()
        cur = conn.execute("""INSERT INTO fm_files (name, schema, schema_version, created_by, created_at, modified_at,
                              modified_by) VALUES (?,?,1,?,?,?,?)""",
                           (name, json.dumps(schema), _app_name(), now, now, _app_name()))
        fid = cur.lastrowid
        conn.execute("""INSERT INTO fm_accounts (file_id, name, password_hash, privilege_set, active, created_at)
                        VALUES (?,?,?,?,1,?)""", (fid, admin, generate_password_hash(pw) if pw else '', FULL, now))
        tables = {t['id']: t for t in schema['tables']}
        recs = body.get('records') or {}
        total = 0
        for tid, rows in (recs.items() if isinstance(recs, dict) else []):
            if tid not in tables or not isinstance(rows, list):
                continue
            serial_ids = {f['id'] for f, _ in _serial_fields(tables[tid], 'create') + _serial_fields(tables[tid], 'commit')}
            for data in rows[:MAX_BATCH_OPS]:
                if not isinstance(data, dict):
                    continue
                data = {k: v for k, v in data.items() if isinstance(v, (str, int, float, list, dict)) or v is None}
                # sample records may bring their own serial numbers (their related records use them)
                given = {k: data[k] for k in serial_ids if str(data.get(k) or '') != ''}
                _take_serials(conn, fid, tables[tid], data, 'create')
                _take_serials(conn, fid, tables[tid], data, 'commit')
                data.update(given)
                conn.execute("""INSERT INTO fm_records (file_id, table_id, data, created_at, created_by, modified_at,
                                modified_by) VALUES (?,?,?,?,?,?,?)""",
                             (fid, tid, json.dumps(data), now, admin, now, admin))
                total += 1
            for k in serial_ids:
                nums = [r for r in (rows or []) if isinstance(r, dict) and str(r.get(k) or '').strip()]
                if nums:
                    top = max((str(r[k]) for r in nums), key=lambda v: (len(v), v))
                    row = conn.execute("SELECT next_value FROM fm_serials WHERE file_id=? AND field_id=?",
                                       (fid, k)).fetchone()
                    nxt = serial_increment(top, 1)
                    if not row or (len(row['next_value']), row['next_value']) < (len(nxt), nxt):
                        conn.execute("INSERT INTO fm_serials (file_id, field_id, next_value) VALUES (?,?,?) "
                                     "ON CONFLICT(file_id, field_id) DO UPDATE SET next_value=excluded.next_value",
                                     (fid, k, nxt))
        conn.commit()
        _log('FILEMAKER_CREATE', f'Created FileMaker file "{name}" ({total} records)', fid)
        return jsonify({'success': True, 'id': fid, 'name': name})
    finally:
        conn.close()


def _check_login(conn, file_id, account, password):
    key = (_app_user(), file_id)
    now = time.time()
    fails = [t for t in _failed_logins.get(key, []) if now - t < FAILED_LOGIN_WINDOW]
    _failed_logins[key] = fails
    if len(fails) >= FAILED_LOGIN_LIMIT:
        raise PermissionError('Too many failed sign-ins. Wait five minutes and try again.')
    row = conn.execute("SELECT * FROM fm_accounts WHERE file_id=? AND name=? COLLATE NOCASE",
                       (file_id, str(account or '').strip())).fetchone()
    ok = bool(row) and row['active'] and (
        (row['password_hash'] == '' and password == '') or
        (row['password_hash'] != '' and check_password_hash(row['password_hash'], password or '')))
    if not ok:
        fails.append(now)
        raise PermissionError('The account name and password you entered cannot be used to access this file. '
                              'Please try again.')
    _failed_logins.pop(key, None)
    return row


@bp.route('/filemaker/api/files/<int:file_id>/open', methods=['POST'])
def open_file(file_id):
    """{account, password} or {auto: true} (the file's "Log in using" option)."""
    if (g := _guard()):
        return g
    body = _body()
    conn = _conn()
    try:
        _cleanup(conn)
        frow = conn.execute("SELECT * FROM fm_files WHERE id=?", (file_id,)).fetchone()
        if not frow:
            return _err('That file no longer exists', 404)
        schema, version = _load_schema(conn, file_id)
        if body.get('auto'):
            auto = (schema.get('fileOptions') or {}).get('autoLogin') or {}
            if not auto.get('enabled'):
                return _err('Sign in required', 401, needLogin=True)
            account, password = auto.get('account') or 'Admin', ''
        else:
            account, password = body.get('account'), str(body.get('password') or '')
        try:
            acct = _check_login(conn, file_id, account, password)
        except PermissionError as e:
            if body.get('auto'):
                return _err('Sign in required', 401, needLogin=True)
            return _err(str(e), 401)
        pset = _pset(schema, acct['privilege_set'])
        if not pset or 'fmapp' not in (pset.get('extended') or []):
            return _err('Your privilege set does not include the "Access via FileMaker Network" extended '
                        'privilege, so it cannot open this hosted file.', 403)
        if body.get('newPassword') is not None:
            npw = str(body['newPassword'])
            if len(npw) < 1:
                return _err('Enter a new password')
            conn.execute("UPDATE fm_accounts SET password_hash=?, must_change=0 WHERE id=?",
                         (generate_password_hash(npw), acct['id']))
            conn.commit()
        elif acct['must_change']:
            return _err('You must change your password before you open this file.', 403, mustChange=True)
        token = secrets.token_urlsafe(24)
        conn.execute("""INSERT INTO fm_sessions (token, file_id, account_id, account_name, app_user, app_name,
                        opened_at, last_seen) VALUES (?,?,?,?,?,?,?,?)""",
                     (token, file_id, acct['id'], acct['name'], _app_user(), _app_name(), _now_text(), time.time()))
        conn.commit()
        srow = conn.execute("SELECT * FROM fm_sessions WHERE token=?", (token,)).fetchone()
        ctx = Ctx(conn, file_id, srow, schema, version, pset)
        _log('FILEMAKER_OPEN', f'Opened "{frow["name"]}" as {acct["name"]}', file_id)
        return jsonify({'success': True, 'token': token, 'file': {'id': file_id, 'name': frow['name']},
                        'account': {'name': acct['name'], 'privilegeSet': pset['id']},
                        'schema': schema, 'version': version, 'serials': _serials(conn, file_id, schema),
                        'records': _all_records(ctx), 'seq': _seq(conn, file_id), 'users': _users(conn, file_id),
                        'hasPassword': acct['password_hash'] != ''})
    finally:
        conn.close()


@bp.route('/filemaker/api/files/<int:file_id>/relogin', methods=['POST'])
def relogin(file_id):
    """Re-Login: switch the open session to another account."""
    if (g := _guard()):
        return g
    body = _body()
    conn = _conn()
    try:
        ctx, err = _ctx(conn, file_id)
        if err:
            return err
        try:
            acct = _check_login(conn, file_id, body.get('account'), str(body.get('password') or ''))
        except PermissionError as e:
            return _err(str(e), 401, fmError=212)
        pset = _pset(ctx.schema, acct['privilege_set'])
        if not pset or 'fmapp' not in (pset.get('extended') or []):
            return _err('That account cannot open this hosted file.', 403, fmError=212)
        conn.execute("DELETE FROM fm_records WHERE pending_token=?", (ctx.token,))
        conn.execute("DELETE FROM fm_locks WHERE token=?", (ctx.token,))
        conn.execute("UPDATE fm_sessions SET account_id=?, account_name=? WHERE token=?",
                     (acct['id'], acct['name'], ctx.token))
        conn.commit()
        srow = conn.execute("SELECT * FROM fm_sessions WHERE token=?", (ctx.token,)).fetchone()
        nctx = Ctx(conn, file_id, srow, ctx.schema, ctx.version, pset)
        return jsonify({'success': True, 'account': {'name': acct['name'], 'privilegeSet': pset['id']},
                        'records': _all_records(nctx), 'seq': _seq(conn, file_id),
                        'hasPassword': acct['password_hash'] != ''})
    finally:
        conn.close()


@bp.route('/filemaker/api/files/<int:file_id>/close', methods=['POST'])
def close_file(file_id):
    if (g := _guard()):
        return g
    conn = _conn()
    try:
        token = request.headers.get('X-FM-Session', '')
        row = conn.execute("SELECT app_user FROM fm_sessions WHERE token=? AND file_id=?", (token, file_id)).fetchone()
        if row and row['app_user'] == _app_user():
            _end_session(conn, token)
            conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


@bp.route('/filemaker/api/files/<int:file_id>/rename', methods=['POST'])
def rename_file(file_id):
    if (g := _guard()):
        return g
    conn = _conn()
    try:
        ctx, err = _ctx(conn, file_id)
        if err:
            return err
        if not ctx.full:
            return _err('Only a [Full Access] account can rename the file', 403)
        name = _unique_name(conn, _body().get('name'), exclude=file_id)
        conn.execute("UPDATE fm_files SET name=?, modified_at=? WHERE id=?", (name, _now_text(), file_id))
        _change(conn, file_id, 'file', ctx.token, ctx.account)
        conn.commit()
        return jsonify({'success': True, 'name': name})
    finally:
        conn.close()


@bp.route('/filemaker/api/files/<int:file_id>/copy', methods=['POST'])
def copy_file(file_id):
    """Save a Copy As: {name, mode: 'copy' | 'clone'} (clone = no records)."""
    if (g := _guard()):
        return g
    body = _body()
    conn = _conn()
    try:
        ctx, err = _ctx(conn, file_id)
        if err:
            return err
        if not ctx.full:
            return _err('Only a [Full Access] account can save a copy of the file', 403)
        frow = conn.execute("SELECT * FROM fm_files WHERE id=?", (file_id,)).fetchone()
        name = _unique_name(conn, body.get('name') or f'{frow["name"]} Copy')
        now = _now_text()
        cur = conn.execute("""INSERT INTO fm_files (name, schema, schema_version, created_by, created_at, modified_at,
                              modified_by) VALUES (?,?,1,?,?,?,?)""",
                           (name, frow['schema'], _app_name(), now, now, _app_name()))
        nid = cur.lastrowid
        conn.execute("""INSERT INTO fm_accounts (file_id, name, password_hash, privilege_set, active, must_change,
                        description, created_at) SELECT ?, name, password_hash, privilege_set, active, must_change,
                        description, ? FROM fm_accounts WHERE file_id=?""", (nid, now, file_id))
        if body.get('mode') != 'clone':
            conn.execute("""INSERT INTO fm_records (file_id, table_id, data, created_at, created_by, modified_at,
                            modified_by, mod_count) SELECT ?, table_id, data, created_at, created_by, modified_at,
                            modified_by, mod_count FROM fm_records WHERE file_id=? AND pending_token IS NULL""",
                         (nid, file_id))
            conn.execute("""INSERT INTO fm_serials (file_id, field_id, next_value)
                            SELECT ?, field_id, next_value FROM fm_serials WHERE file_id=?""", (nid, file_id))
            src = os.path.join(_data_dir, 'filemaker_files', str(file_id))
            dst = os.path.join(_data_dir, 'filemaker_files', str(nid))
            idmap = {}
            for c in conn.execute("SELECT * FROM fm_containers WHERE file_id=?", (file_id,)).fetchall():
                cur = conn.execute("""INSERT INTO fm_containers (file_id, name, mime, size, sha1, created_at,
                                      created_by) VALUES (?,?,?,?,?,?,?)""",
                                   (nid, c['name'], c['mime'], c['size'], c['sha1'], c['created_at'], c['created_by']))
                idmap[c['id']] = cur.lastrowid
                try:
                    os.makedirs(dst, exist_ok=True)
                    with open(os.path.join(src, str(c['id'])), 'rb') as fh, \
                            open(os.path.join(dst, str(cur.lastrowid)), 'wb') as out:
                        out.write(fh.read())
                except OSError:
                    pass
            # container values in the copied records point at the copy's own containers
            for r in conn.execute("SELECT id, data FROM fm_records WHERE file_id=?", (nid,)).fetchall() if idmap else []:
                d = json.loads(r['data'] or '{}')
                changed = False
                for v in d.values():
                    for x in (v if isinstance(v, list) else [v]):
                        if isinstance(x, dict) and x.get('c') in idmap:
                            x['c'] = idmap[x['c']]
                            changed = True
                if changed:
                    conn.execute("UPDATE fm_records SET data=? WHERE id=?", (json.dumps(d), r['id']))
        conn.commit()
        _log('FILEMAKER_COPY', f'Saved a copy of "{frow["name"]}" as "{name}"', nid)
        return jsonify({'success': True, 'id': nid, 'name': name})
    finally:
        conn.close()


@bp.route('/filemaker/api/files/<int:file_id>/delete', methods=['POST'])
def delete_file(file_id):
    """Delete a hosted file. Needs a [Full Access] account name and password for it."""
    if (g := _guard()):
        return g
    body = _body()
    conn = _conn()
    try:
        frow = conn.execute("SELECT * FROM fm_files WHERE id=?", (file_id,)).fetchone()
        if not frow:
            return _err('That file no longer exists', 404)
        try:
            acct = _check_login(conn, file_id, body.get('account'), str(body.get('password') or ''))
        except PermissionError as e:
            return _err(str(e), 401)
        if acct['privilege_set'] != FULL:
            return _err('Only a [Full Access] account can delete the file', 403)
        if str(body.get('confirm') or '') != frow['name']:
            return _err('Type the file name to confirm')
        for tbl in ('fm_records', 'fm_accounts', 'fm_serials', 'fm_locks', 'fm_changes', 'fm_messages',
                    'fm_containers'):
            conn.execute(f"DELETE FROM {tbl} WHERE file_id=?", (file_id,))
        conn.execute("UPDATE fm_sessions SET closed=1 WHERE file_id=?", (file_id,))
        conn.execute("DELETE FROM fm_files WHERE id=?", (file_id,))
        conn.commit()
        folder = os.path.join(_data_dir, 'filemaker_files', str(file_id))
        if os.path.isdir(folder):
            for n in os.listdir(folder):
                try:
                    os.remove(os.path.join(folder, n))
                except OSError:
                    pass
            try:
                os.rmdir(folder)
            except OSError:
                pass
        with _schema_lock:
            _schema_cache.pop(file_id, None)
        _log('FILEMAKER_DELETE', f'Deleted FileMaker file "{frow["name"]}"', file_id)
        return jsonify({'success': True})
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════════════════════
# HTTP: schema (Manage Database, layouts, scripts, value lists, security)
# ═════════════════════════════════════════════════════════════════════════════

SECTIONS_FULL = ('database', 'customFunctions', 'privilegeSets', 'extendedPrivileges', 'fileOptions', 'themes',
                 'layoutOrder', 'scriptOrder')
COLLECTIONS = {'layouts': _layout_modify_ok, 'scripts': _script_modify_ok, 'valueLists': _valuelist_modify_ok}


@bp.route('/filemaker/api/files/<int:file_id>/schema')
def get_schema(file_id):
    if (g := _guard()):
        return g
    conn = _conn()
    try:
        ctx, err = _ctx(conn, file_id)
        if err:
            return err
        return jsonify({'success': True, 'schema': ctx.schema, 'version': ctx.version,
                        'serials': _serials(conn, file_id, ctx.schema)})
    finally:
        conn.close()


@bp.route('/filemaker/api/files/<int:file_id>/schema', methods=['POST'])
def save_schema(file_id):
    """{ops: [{op: 'section', name, value} | {op: 'upsert', coll, item} | {op: 'delete', coll, id}],
        serials?: {fieldId: next}}"""
    if (g := _guard()):
        return g
    body = _body()
    ops = body.get('ops') or []
    if not isinstance(ops, list) or not ops and not body.get('serials'):
        return _err('Nothing to save')
    conn = _conn()
    try:
        with _schema_lock:
            _schema_cache.pop(file_id, None)
        ctx, err = _ctx(conn, file_id)
        if err:
            return err
        conn.execute('BEGIN IMMEDIATE')
        schema = json.loads(json.dumps(ctx.schema))
        holder = None
        for op in ops:
            kind = op.get('op')
            if kind == 'section':
                name = op.get('name')
                if name not in SECTIONS_FULL and name not in ('valueLists',):
                    return _err(f'Unknown section "{name}"')
                if not ctx.full:
                    return _err('Only a [Full Access] account can change that', 403)
                if name == 'database':
                    holder = holder or _lock_holder(conn, ctx, 'schema')
                    if holder:
                        return _err(f'The database schema is being modified by "{holder}". Try again later.', 409)
                    val = op.get('value') or {}
                    for key in ('tables', 'tableOccurrences', 'relationships'):
                        if not isinstance(val.get(key), list):
                            return _err(f'"{key}" must be a list')
                        schema[key] = val[key]
                else:
                    schema[name] = op.get('value')
            elif kind in ('upsert', 'delete'):
                coll = op.get('coll')
                check = COLLECTIONS.get(coll)
                if not check:
                    return _err(f'Unknown collection "{coll}"')
                items = schema.setdefault(coll, [])
                item_id = (op.get('item') or {}).get('id') if kind == 'upsert' else op.get('id')
                if not isinstance(item_id, str) or not item_id:
                    return _err('Missing id')
                idx = next((i for i, it in enumerate(items) if it.get('id') == item_id), None)
                if not check(ctx.pset, item_id, idx is None):
                    return _err('Your privilege set does not allow that change', 403)
                lk = _lock_holder(conn, ctx, f'{coll[:-1]}:{item_id}')
                if lk:
                    return _err(f'That is being modified by "{lk}". Try again later.', 409)
                if kind == 'delete':
                    if idx is not None:
                        items.pop(idx)
                elif idx is None:
                    items.append(op['item'])
                else:
                    items[idx] = op['item']
            else:
                return _err(f'Unknown operation "{kind}"')
        try:
            schema = clean_schema(schema)
        except ValueError as e:
            conn.rollback()
            return _err(str(e))
        if not any(a['privilege_set'] == FULL and a['active'] for a in
                   conn.execute("SELECT privilege_set, active FROM fm_accounts WHERE file_id=?", (file_id,))):
            conn.rollback()
            return _err('At least one active [Full Access] account is required')
        # accounts must still point at a privilege set
        set_ids = {p['id'] for p in schema['privilegeSets']}
        for a in conn.execute("SELECT name, privilege_set FROM fm_accounts WHERE file_id=?", (file_id,)):
            if a['privilege_set'] not in set_ids:
                conn.rollback()
                return _err(f'The account "{a["name"]}" still uses that privilege set')
        # forget the data of deleted tables and fields
        old_tables = {t['id']: {f['id'] for f in t['fields']} for t in ctx.schema['tables']}
        new_tables = {t['id']: {f['id'] for f in t['fields']} for t in schema['tables']}
        for tid in set(old_tables) - set(new_tables):
            conn.execute("DELETE FROM fm_records WHERE file_id=? AND table_id=?", (file_id, tid))
        for tid, fids in new_tables.items():
            gone = old_tables.get(tid, set()) - fids
            if gone:
                for r in conn.execute("SELECT id, data FROM fm_records WHERE file_id=? AND table_id=?",
                                      (file_id, tid)).fetchall():
                    d = json.loads(r['data'] or '{}')
                    if gone & set(d):
                        conn.execute("UPDATE fm_records SET data=? WHERE id=?",
                                     (json.dumps({k: v for k, v in d.items() if k not in gone}), r['id']))
        for fid, nxt in (body.get('serials') or {}).items():
            if not ctx.full:
                return _err('Only a [Full Access] account can change serial numbers', 403)
            conn.execute("INSERT INTO fm_serials (file_id, field_id, next_value) VALUES (?,?,?) "
                         "ON CONFLICT(file_id, field_id) DO UPDATE SET next_value=excluded.next_value",
                         (file_id, str(fid)[:40], str(nxt)[:40]))
        version = ctx.version + 1
        conn.execute("UPDATE fm_files SET schema=?, schema_version=?, modified_at=?, modified_by=? WHERE id=?",
                     (json.dumps(schema, separators=(',', ':')), version, _now_text(), ctx.account, file_id))
        _change(conn, file_id, 'schema', ctx.token, ctx.account)
        conn.commit()
        with _schema_lock:
            _schema_cache[file_id] = (version, schema)
        return jsonify({'success': True, 'version': version, 'schema': schema,
                        'serials': _serials(conn, file_id, schema)})
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════════════════════
# HTTP: records, locks, changes
# ═════════════════════════════════════════════════════════════════════════════

@bp.route('/filemaker/api/files/<int:file_id>/records', methods=['POST'])
def records_batch(file_id):
    """{ops: [{op:'create', table, data, pending?, ref?} | {op:'update', id, data, mc?, commit?} |
              {op:'delete', id}]}  All or nothing."""
    if (g := _guard()):
        return g
    ops = _body().get('ops')
    if not isinstance(ops, list) or not ops:
        return _err('Nothing to do')
    if len(ops) > MAX_BATCH_OPS:
        return _err(f'Too many changes at once ({MAX_BATCH_OPS} at most)')
    conn = _conn()
    try:
        ctx, err = _ctx(conn, file_id)
        if err:
            return err
        conn.execute('BEGIN IMMEDIATE')
        try:
            results = _run_ops(ctx, ops)
        except Exception as e:
            conn.rollback()
            if hasattr(e, 'index'):
                return _op_error(e)
            raise
        conn.commit()
        ids = [r['id'] for r in results if r['id'] and r['op'] != 'delete']
        recs = {r['id']: r for r in _rows_out(ctx, ids)}
        for r in results:
            if r['op'] != 'delete':
                r['record'] = recs.get(r['id'])
        return jsonify({'success': True, 'results': results, 'seq': _seq(conn, file_id)})
    finally:
        conn.close()


@bp.route('/filemaker/api/files/<int:file_id>/lock', methods=['POST'])
def lock(file_id):
    """{key: 'rec:<id>' | 'schema' | 'layout:<id>' | 'script:<id>' | 'valueList:<id>'}"""
    if (g := _guard()):
        return g
    key = str(_body().get('key') or '')
    if not re.fullmatch(r'(rec:\d+|schema|security|layout:[\w-]+|script:[\w-]+|valueList:[\w-]+)', key):
        return _err('Unknown lock')
    conn = _conn()
    try:
        ctx, err = _ctx(conn, file_id)
        if err:
            return err
        conn.execute('BEGIN IMMEDIATE')
        holder = _lock_holder(conn, ctx, key)
        if holder:
            conn.rollback()
            return jsonify({'success': False, 'holder': holder, 'fmError': 301,
                            'error': f'This record is being modified by "{holder}"' if key.startswith('rec:')
                            else f'This is being modified by "{holder}"'})
        record = None
        if key.startswith('rec:'):
            rid = int(key[4:])
            row = conn.execute("SELECT * FROM fm_records WHERE id=? AND file_id=?", (rid, file_id)).fetchone()
            if not row or (row['pending_token'] and row['pending_token'] != ctx.token):
                conn.rollback()
                return jsonify({'success': False, 'fmError': 101, 'gone': True,
                                'error': 'This record was deleted by another user'})
            tp = _tp(ctx, row['table_id'])
            if not row['pending_token'] and not ctx.allowed(tp, 'edit', json.loads(row['data'] or '{}')):
                conn.rollback()
                return jsonify({'success': False, 'fmError': 200,
                                'error': 'You do not have permission to modify this record'})
            record = _record_out(ctx, row, tp)
        conn.execute("""INSERT INTO fm_locks (file_id, lock_key, token, holder, acquired_at) VALUES (?,?,?,?,?)
                        ON CONFLICT(file_id, lock_key) DO UPDATE SET token=excluded.token, holder=excluded.holder,
                        acquired_at=excluded.acquired_at""",
                     (file_id, key, ctx.token, f'{ctx.account} ({_app_name()})' if ctx.account.lower() !=
                      _app_name().lower() else ctx.account, _now_text()))
        conn.commit()
        return jsonify({'success': True, 'record': record})
    finally:
        conn.close()


@bp.route('/filemaker/api/files/<int:file_id>/unlock', methods=['POST'])
def unlock(file_id):
    if (g := _guard()):
        return g
    keys = _body().get('keys') or [_body().get('key')]
    conn = _conn()
    try:
        ctx, err = _ctx(conn, file_id)
        if err:
            return err
        for k in keys:
            conn.execute("DELETE FROM fm_locks WHERE file_id=? AND lock_key=? AND token=?",
                         (file_id, str(k or ''), ctx.token))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


@bp.route('/filemaker/api/files/<int:file_id>/changes')
def changes(file_id):
    """Everything that changed since ?since=<seq>, plus who is connected.
    Polled every couple of seconds; also keeps the session and its locks alive."""
    if (g := _guard()):
        return g
    try:
        since = int(request.args.get('since') or 0)
    except ValueError:
        since = 0
    conn = _conn()
    try:
        _cleanup(conn)
        ctx, err = _ctx(conn, file_id)
        if err:
            return err
        conn.execute("UPDATE fm_sessions SET last_seen=? WHERE token=?", (time.time(), ctx.token))
        rows = conn.execute("SELECT * FROM fm_changes WHERE file_id=? AND seq>? ORDER BY seq LIMIT 5000",
                            (file_id, since)).fetchall()
        seq = rows[-1]['seq'] if rows else max(since, 0)
        schema_changed = any(r['kind'] == 'schema' for r in rows if r['token'] != ctx.token)
        file_changed = any(r['kind'] in ('file', 'acct') for r in rows if r['token'] != ctx.token)
        rec_ids, deleted = [], []
        for r in rows:
            if r['token'] == ctx.token:
                continue
            if r['kind'] == 'rec':
                rec_ids.append(r['record_id'])
            elif r['kind'] == 'del':
                deleted.append({'id': r['record_id'], 't': r['table_id'], 'by': r['actor']})
        records = _rows_out(ctx, list(dict.fromkeys(rec_ids)))
        found = {r['id'] for r in records}
        # records that changed so this account may no longer see them
        for r in rows:
            if r['kind'] == 'rec' and r['token'] != ctx.token and r['record_id'] not in found:
                deleted.append({'id': r['record_id'], 't': r['table_id'], 'hidden': True})
        msgs = conn.execute("SELECT id, from_name, text, at FROM fm_messages WHERE to_token=? AND delivered=0",
                            (ctx.token,)).fetchall()
        if msgs:
            conn.execute(f"UPDATE fm_messages SET delivered=1 WHERE id IN ({','.join('?' * len(msgs))})",
                         [m['id'] for m in msgs])
        conn.commit()
        out = {'success': True, 'seq': seq, 'records': records, 'deleted': deleted,
               'schemaVersion': ctx.version if schema_changed else None,
               'fileChanged': file_changed, 'users': _users(conn, file_id),
               'messages': [{'from': m['from_name'], 'text': m['text'], 'at': m['at']} for m in msgs],
               'serverTime': _now_text()}
        if schema_changed:
            out['schema'] = ctx.schema
            out['serials'] = _serials(conn, file_id, ctx.schema)
        return jsonify(out)
    finally:
        conn.close()


@bp.route('/filemaker/api/files/<int:file_id>/serials', methods=['POST'])
def take_serials(file_id):
    """Set Next Serial Value: {field, next}."""
    if (g := _guard()):
        return g
    body = _body()
    conn = _conn()
    try:
        ctx, err = _ctx(conn, file_id)
        if err:
            return err
        fid = str(body.get('field') or '')
        if not any(f['id'] == fid for t in ctx.schema['tables'] for f in t['fields']):
            return _err('Unknown field', 404, fmError=102)
        if not ctx.full:
            return _err('Only a [Full Access] account can change serial numbers', 403, fmError=200)
        conn.execute("INSERT INTO fm_serials (file_id, field_id, next_value) VALUES (?,?,?) "
                     "ON CONFLICT(file_id, field_id) DO UPDATE SET next_value=excluded.next_value",
                     (file_id, fid, str(body.get('next') or '1')[:40]))
        conn.commit()
        return jsonify({'success': True, 'serials': _serials(conn, file_id, ctx.schema)})
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════════════════════
# HTTP: accounts, users connected
# ═════════════════════════════════════════════════════════════════════════════

def _account_out(a):
    return {'id': a['id'], 'name': a['name'], 'privilegeSet': a['privilege_set'], 'active': bool(a['active']),
            'mustChange': bool(a['must_change']), 'hasPassword': a['password_hash'] != '',
            'description': a['description'] or '', 'created': a['created_at']}


@bp.route('/filemaker/api/files/<int:file_id>/accounts')
def list_accounts(file_id):
    if (g := _guard()):
        return g
    conn = _conn()
    try:
        ctx, err = _ctx(conn, file_id)
        if err:
            return err
        if not ctx.full:
            return _err('Only a [Full Access] account can manage security', 403, fmError=200)
        rows = conn.execute("SELECT * FROM fm_accounts WHERE file_id=? ORDER BY name COLLATE NOCASE", (file_id,))
        return jsonify({'success': True, 'accounts': [_account_out(a) for a in rows]})
    finally:
        conn.close()


@bp.route('/filemaker/api/files/<int:file_id>/accounts', methods=['POST'])
def save_accounts(file_id):
    """{ops: [{op:'add', name, password, privilegeSet, active, mustChange, description} |
              {op:'update', id, ...same, password only when changing} | {op:'delete', id}]}
    Used by Manage Security and by the Add Account / Delete Account / Reset Account Password /
    Enable Account script steps (which may also name the account instead of its id)."""
    if (g := _guard()):
        return g
    ops = _body().get('ops') or []
    conn = _conn()
    try:
        ctx, err = _ctx(conn, file_id)
        if err:
            return err
        if not ctx.full:
            return _err('Only a [Full Access] account can manage accounts', 403, fmError=200)
        set_ids = {p['id'] for p in ctx.schema['privilegeSets']}
        conn.execute('BEGIN IMMEDIATE')
        now = _now_text()
        for op in ops:
            kind = op.get('op')
            aid = op.get('id')
            if not aid and op.get('match'):
                r = conn.execute("SELECT id FROM fm_accounts WHERE file_id=? AND name=? COLLATE NOCASE",
                                 (file_id, str(op['match']))).fetchone()
                if not r:
                    conn.rollback()
                    return _err(f'There is no account named "{op["match"]}"', 404, fmError=211)
                aid = r['id']
            name = str(op.get('name') or '').strip()[:60]
            if kind in ('add', 'update') and 'privilegeSet' in op and op['privilegeSet'] not in set_ids:
                conn.rollback()
                return _err('Choose a privilege set', 400)
            if kind == 'add':
                if not name:
                    conn.rollback()
                    return _err('Enter an account name')
                if conn.execute("SELECT 1 FROM fm_accounts WHERE file_id=? AND name=? COLLATE NOCASE",
                                (file_id, name)).fetchone():
                    conn.rollback()
                    return _err(f'An account named "{name}" already exists', 400, fmError=214)
                pw = str(op.get('password') or '')
                conn.execute("""INSERT INTO fm_accounts (file_id, name, password_hash, privilege_set, active,
                                must_change, description, created_at) VALUES (?,?,?,?,?,?,?,?)""",
                             (file_id, name, generate_password_hash(pw) if pw else '',
                              op.get('privilegeSet') or ENTRY, 1 if op.get('active', True) else 0,
                              1 if op.get('mustChange') else 0, str(op.get('description') or '')[:300], now))
            elif kind == 'update':
                row = conn.execute("SELECT * FROM fm_accounts WHERE id=? AND file_id=?", (aid, file_id)).fetchone()
                if not row:
                    conn.rollback()
                    return _err('That account no longer exists', 404, fmError=211)
                sets, vals = [], []
                if name and name.lower() != row['name'].lower():
                    if conn.execute("SELECT 1 FROM fm_accounts WHERE file_id=? AND name=? COLLATE NOCASE AND id<>?",
                                    (file_id, name, aid)).fetchone():
                        conn.rollback()
                        return _err(f'An account named "{name}" already exists', 400, fmError=214)
                if name:
                    sets.append('name=?')
                    vals.append(name)
                if 'password' in op and op['password'] is not None:
                    pw = str(op['password'])
                    sets.append('password_hash=?')
                    vals.append(generate_password_hash(pw) if pw else '')
                for key, col in (('privilegeSet', 'privilege_set'), ('description', 'description')):
                    if key in op:
                        sets.append(f'{col}=?')
                        vals.append(op[key])
                for key, col in (('active', 'active'), ('mustChange', 'must_change')):
                    if key in op:
                        sets.append(f'{col}=?')
                        vals.append(1 if op[key] else 0)
                if sets:
                    conn.execute(f"UPDATE fm_accounts SET {', '.join(sets)} WHERE id=?", (*vals, aid))
            elif kind == 'delete':
                row = conn.execute("SELECT * FROM fm_accounts WHERE id=? AND file_id=?", (aid, file_id)).fetchone()
                if row and row['id'] == ctx.s['account_id']:
                    conn.rollback()
                    return _err('You cannot delete the account you are signed in with', 400, fmError=200)
                conn.execute("DELETE FROM fm_accounts WHERE id=? AND file_id=?", (aid, file_id))
            else:
                conn.rollback()
                return _err(f'Unknown operation "{kind}"')
        if not conn.execute("SELECT 1 FROM fm_accounts WHERE file_id=? AND privilege_set=? AND active=1",
                            (file_id, FULL)).fetchone():
            conn.rollback()
            return _err('At least one active account must keep [Full Access]')
        _change(conn, file_id, 'acct', ctx.token, ctx.account)
        conn.commit()
        rows = conn.execute("SELECT * FROM fm_accounts WHERE file_id=? ORDER BY name COLLATE NOCASE", (file_id,))
        return jsonify({'success': True, 'accounts': [_account_out(a) for a in rows]})
    finally:
        conn.close()


@bp.route('/filemaker/api/files/<int:file_id>/password', methods=['POST'])
def change_password(file_id):
    """Change Password: {old, new} for the signed-in account."""
    if (g := _guard()):
        return g
    body = _body()
    conn = _conn()
    try:
        ctx, err = _ctx(conn, file_id)
        if err:
            return err
        if not (ctx.pset or {}).get('modifyOwnPassword', True):
            return _err('Your privilege set does not allow changing your password', 403, fmError=200)
        row = conn.execute("SELECT * FROM fm_accounts WHERE id=?", (ctx.s['account_id'],)).fetchone()
        old = str(body.get('old') or '')
        ok = (row['password_hash'] == '' and old == '') or \
            (row['password_hash'] and check_password_hash(row['password_hash'], old))
        if not ok:
            return _err('The old password is not correct', 401, fmError=213)
        new = str(body.get('new') or '')
        conn.execute("UPDATE fm_accounts SET password_hash=?, must_change=0 WHERE id=?",
                     (generate_password_hash(new) if new else '', row['id']))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


@bp.route('/filemaker/api/files/<int:file_id>/users')
def users(file_id):
    if (g := _guard()):
        return g
    conn = _conn()
    try:
        ctx, err = _ctx(conn, file_id)
        if err:
            return err
        return jsonify({'success': True, 'users': _users(conn, file_id),
                        'me': hashlib.sha1(ctx.token.encode()).hexdigest()[:12]})
    finally:
        conn.close()


@bp.route('/filemaker/api/files/<int:file_id>/users/<uid>/<action>', methods=['POST'])
def user_action(file_id, uid, action):
    """Send a message to a connected user, or disconnect them (Full Access only)."""
    if (g := _guard()):
        return g
    if action not in ('message', 'disconnect'):
        return _err('Unknown action', 404)
    text = str(_body().get('text') or '').strip()[:1000]
    conn = _conn()
    try:
        ctx, err = _ctx(conn, file_id)
        if err:
            return err
        if not ctx.full:
            return _err('Only a [Full Access] account can do that', 403)
        token = _token_for_user_id(conn, file_id, uid)
        if not token:
            return _err('That user is no longer connected', 404)
        if action == 'message':
            if not text:
                return _err('Type a message')
            conn.execute("INSERT INTO fm_messages (file_id, to_token, from_name, text, at) VALUES (?,?,?,?,?)",
                         (file_id, token, ctx.account, text, _now_text()))
        else:
            if token == ctx.token:
                return _err('Use Close to close your own copy of the file')
            _end_session(conn, token)
            conn.execute("UPDATE fm_sessions SET kicked=1, closed=0, kick_message=? WHERE token=?",
                         (text or f'You were disconnected from this file by {ctx.account}.', token))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════════════════════
# HTTP: containers, Excel, Insert From URL
# ═════════════════════════════════════════════════════════════════════════════

@bp.route('/filemaker/api/files/<int:file_id>/containers', methods=['POST'])
def upload_container(file_id):
    if (g := _guard()):
        return g
    up = request.files.get('file')
    if not up:
        return _err('Choose a file')
    data = up.read(MAX_CONTAINER_BYTES + 1)
    if len(data) > MAX_CONTAINER_BYTES:
        return _err('That file is too large (25 MB limit)')
    conn = _conn()
    try:
        ctx, err = _ctx(conn, file_id)
        if err:
            return err
        name = os.path.basename(up.filename or 'file')[:200] or 'file'
        mime = (up.mimetype or 'application/octet-stream')[:100]
        cur = conn.execute("""INSERT INTO fm_containers (file_id, name, mime, size, sha1, created_at, created_by)
                              VALUES (?,?,?,?,?,?,?)""",
                           (file_id, name, mime, len(data), hashlib.sha1(data).hexdigest(), _now_text(), ctx.account))
        cid = cur.lastrowid
        folder = os.path.join(_data_dir, 'filemaker_files', str(file_id))
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, str(cid)), 'wb') as fh:
            fh.write(data)
        conn.commit()
        return jsonify({'success': True, 'value': {'c': cid, 'name': name, 'mime': mime, 'size': len(data)}})
    finally:
        conn.close()


@bp.route('/filemaker/api/files/<int:file_id>/containers/<int:cid>')
def get_container(file_id, cid):
    """Served to anyone with this file open (images are loaded by <img>, so by
    cookie rather than the session header)."""
    if (g := _guard()):
        return g
    conn = _conn()
    try:
        live = conn.execute("""SELECT 1 FROM fm_sessions WHERE file_id=? AND app_user=? AND closed=0 AND kicked=0
                               AND last_seen>=?""", (file_id, _app_user(), time.time() - SESSION_TTL)).fetchone()
        if not live:
            return _err('Open the file first', 401)
        row = conn.execute("SELECT * FROM fm_containers WHERE id=? AND file_id=?", (cid, file_id)).fetchone()
        if not row:
            return _err('Not found', 404)
        path = os.path.join(_data_dir, 'filemaker_files', str(file_id), str(cid))
        if not os.path.exists(path):
            return _err('Not found', 404)
        mime = row['mime'] or 'application/octet-stream'
        inline = mime.startswith(('image/', 'audio/', 'video/')) and mime != 'image/svg+xml' or mime == 'application/pdf'
        resp = send_file(path, mimetype=mime, as_attachment=not inline or request.args.get('download') == '1',
                         download_name=row['name'], max_age=3600)
        resp.headers['Content-Security-Policy'] = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'"
        return resp
    finally:
        conn.close()


def _cell_text(v):
    if v is None:
        return ''
    if isinstance(v, bool):
        return '1' if v else '0'
    if isinstance(v, datetime):
        return v.strftime('%Y-%m-%d') if (v.hour, v.minute, v.second) == (0, 0, 0) else v.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(v, date):
        return v.strftime('%Y-%m-%d')
    if isinstance(v, dtime):
        return v.strftime('%H:%M:%S')
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    return str(v)


@bp.route('/filemaker/api/xlsx/parse', methods=['POST'])
def xlsx_parse():
    """Import from Excel: the sheets of an uploaded .xlsx as rows of text."""
    if (g := _guard()):
        return g
    up = request.files.get('file')
    if not up:
        return _err('Choose a file')
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(up.read(30 * 1024 * 1024)), read_only=True, data_only=True)
    except Exception:
        return _err('That file could not be read as an Excel workbook (.xlsx)')
    sheets = []
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows(values_only=True):
            rows.append([_cell_text(v) for v in row])
            if len(rows) >= 100000:
                break
        while rows and not any(rows[-1]):
            rows.pop()
        sheets.append({'name': ws.title, 'rows': rows})
    return jsonify({'success': True, 'sheets': sheets})


@bp.route('/filemaker/api/xlsx/build', methods=['POST'])
def xlsx_build():
    """Export Records / Save Records as Excel: {filename, sheet, rows: [[...]], types?: [...]}"""
    if (g := _guard()):
        return g
    body = _body()
    rows = body.get('rows') or []
    if not isinstance(rows, list) or len(rows) > 200000:
        return _err('Nothing to save')
    import openpyxl
    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet(re.sub(r'[\[\]:*?/\\]', '', str(body.get('sheet') or 'Sheet1'))[:31] or 'Sheet1')
    types = body.get('types') or []
    for i, row in enumerate(rows):
        out = []
        for j, v in enumerate(row if isinstance(row, list) else []):
            t = types[j] if j < len(types) else 'text'
            if i > 0 or not body.get('header'):
                if t == 'number' and isinstance(v, str) and re.fullmatch(r'-?\d+(\.\d+)?', v.strip()):
                    v = float(v) if '.' in v else int(v)
                elif t == 'date' and isinstance(v, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', v):
                    v = datetime.strptime(v, '%Y-%m-%d').date()
                elif t == 'timestamp' and isinstance(v, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', v):
                    v = datetime.strptime(v, '%Y-%m-%d %H:%M:%S')
            out.append(v if isinstance(v, (int, float, date)) else str(v if v is not None else '')[:32000])
        ws.append(out)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    name = re.sub(r'[^\w .()-]', '', str(body.get('filename') or 'Export'))[:80] or 'Export'
    if not name.lower().endswith('.xlsx'):
        name += '.xlsx'
    return send_file(buf, as_attachment=True, download_name=name,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


def _public_host(host):
    """Every address the host name resolves to is on the public internet."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise ValueError(f'Could not find the host "{host}"')
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split('%')[0])
        if not ip.is_global or ip.is_multicast:
            raise ValueError('Insert From URL can only reach public internet addresses')
    return True


@bp.route('/filemaker/api/files/<int:file_id>/fetch', methods=['POST'])
def fetch_url(file_id):
    """Insert From URL: {url, method, headers, body}. Public http(s) addresses only."""
    if (g := _guard()):
        return g
    body = _body()
    conn = _conn()
    try:
        ctx, err = _ctx(conn, file_id)
        if err:
            return err
    finally:
        conn.close()
    url = str(body.get('url') or '').strip()
    method = str(body.get('method') or 'GET').upper()
    if method not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD'):
        return _err('Unsupported method', 400, fmError=1630)
    headers = {str(k)[:100]: str(v)[:2000] for k, v in (body.get('headers') or {}).items()
               if str(k).lower() not in ('host', 'content-length', 'cookie')}
    data = body.get('body')
    try:
        for _ in range(5):
            u = urlparse(url)
            if u.scheme not in ('http', 'https') or not u.hostname:
                raise ValueError('Only http:// and https:// addresses are supported')
            _public_host(u.hostname)
            r = http_requests.request(method, url, headers=headers, data=data if method != 'GET' else None,
                                      timeout=20, allow_redirects=False, stream=True)
            if r.is_redirect and r.headers.get('Location'):
                url = urljoin(url, r.headers['Location'])
                if r.status_code in (301, 302, 303):
                    method, data = 'GET', None
                continue
            content = r.raw.read(MAX_FETCH_BYTES + 1, decode_content=True)
            if len(content) > MAX_FETCH_BYTES:
                raise ValueError('The response is larger than 5 MB')
            ctype = r.headers.get('Content-Type', '')
            out = {'success': True, 'status': r.status_code, 'contentType': ctype,
                   'headers': dict(list(r.headers.items())[:60]), 'url': url}
            if ctype.startswith(('text/', 'application/json', 'application/xml', 'application/javascript')) or \
                    '+json' in ctype or '+xml' in ctype or not ctype:
                out['text'] = content.decode(r.encoding or 'utf-8', errors='replace')
            else:
                import base64
                out['base64'] = base64.b64encode(content).decode()
            return jsonify(out)
        raise ValueError('Too many redirects')
    except ValueError as e:
        return _err(str(e), 400, fmError=1631)
    except http_requests.RequestException as e:
        return _err(f'The request failed: {e.__class__.__name__}', 502, fmError=1631)


# ═════════════════════════════════════════════════════════════════════════════
# wiring
# ═════════════════════════════════════════════════════════════════════════════

def init_filemaker(app, csrf, db_path, *, data_dir, log_activity=None):
    global _db_path, _data_dir, _log_activity
    _db_path, _data_dir, _log_activity = db_path, data_dir, log_activity
    init_db()
    app.register_blueprint(bp)


PAGE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>FileMaker — Stahlman-England</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="csrf-token" content="{{ csrf_token() }}">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%237A2BD8'/%3E%3Cpath d='M9 8h14v4H13v3h8v4h-8v6H9z' fill='white'/%3E%3C/svg%3E">
<link rel="stylesheet" href="{{ url_for('filemaker.static', filename='fm.css') }}?v={{ v }}">
</head>
<body>
<div id="fm-root"></div>
<noscript>FileMaker needs JavaScript.</noscript>
<script>window.FM_BOOT = {{ boot|tojson }};</script>
{% for js in ['fm-core.js', 'fm-calc.js', 'fm-data.js', 'fm-render.js', 'fm-script.js', 'fm-dialogs.js',
              'fm-design.js', 'fm-starters.js', 'fm-app.js'] %}
<script src="{{ url_for('filemaker.static', filename=js) }}?v={{ v }}"></script>
{% endfor %}
</body>
</html>
'''
