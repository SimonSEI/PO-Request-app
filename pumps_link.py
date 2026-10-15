"""
How the Office App and the Pumps service (pumps_server.py) talk once Pumps runs
on its own. Both sides share PUMPS_SHARED_SECRET.

- Sign-in: people still log in to the Office App. Its /pumps sends them on to
  the Pumps service with a short-lived signed ticket carrying who they are, so
  Pumps never asks for a password of its own (like the Snowbirds hand-off).
  Ticket: base64url(JSON {"u", "r", "n", "exp"}) + "." + HMAC-SHA256 hex.
- Jobber: Receivables (in the Office App) reads Jobber through the connection
  made in Pumps, so it asks the Pumps service for an access token over
  Railway's private network (POST /internal/jobber-token, the secret in the
  X-Pumps-Secret header).
- Data: moved once at the switch-over (export_bundle / import_bundle below).
"""
import base64
import hmac
import json
import os
import sqlite3
import time
import zipfile

import requests as http_requests

TICKET_TTL_SECONDS = 120  # long enough to follow the redirect, useless if copied later


def _sign(secret, payload):
    return hmac.new(secret.encode(), payload.encode(), 'sha256').hexdigest()


def make_ticket(secret, username, role, full_name='', ttl_seconds=TICKET_TTL_SECONDS):
    body = json.dumps({'u': username, 'r': role, 'n': full_name or '', 'exp': int(time.time()) + ttl_seconds},
                      separators=(',', ':'))
    encoded = base64.urlsafe_b64encode(body.encode()).decode().rstrip('=')
    return f'{encoded}.{_sign(secret, encoded)}'


def read_ticket(secret, ticket):
    """{'username', 'role', 'full_name'} for a valid, unexpired ticket, else None."""
    if not secret or not ticket or '.' not in ticket:
        return None
    encoded, sig = ticket.rsplit('.', 1)
    if not hmac.compare_digest(_sign(secret, encoded), sig):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not data.get('u') or int(data.get('exp') or 0) < time.time():
        return None
    return {'username': str(data['u']), 'role': str(data.get('r') or ''), 'full_name': str(data.get('n') or '')}


def secret_ok(secret, given):
    return bool(secret) and hmac.compare_digest(secret, given or '')


class JobberLink:
    """The Office App's side of the Jobber hand-off: what Receivables is given
    as jobber_token / jobber_connected when Pumps runs as its own service."""

    def __init__(self, internal_url, secret):
        self.url = internal_url.rstrip('/') + '/internal/jobber-token'
        self.secret = secret

    def _ask(self, force=False, status_only=False):
        r = http_requests.post(self.url, json={'force': bool(force), 'status_only': status_only},
                               headers={'X-Pumps-Secret': self.secret}, timeout=45)
        try:
            out = r.json()
        except ValueError:
            out = {}
        if r.status_code >= 400:
            raise RuntimeError(out.get('error') or f'The Pumps service answered HTTP {r.status_code}')
        return out

    def token(self, force=False):
        out = self._ask(force)
        if not out.get('token'):
            raise RuntimeError(out.get('error') or 'Jobber is not connected to Pumps yet')
        return out['token']

    def connected(self):
        try:
            return bool(self._ask(status_only=True).get('connected'))
        except Exception:
            return False


# ── Moving Pumps' data to its own service (once, at the switch-over) ─────────
# The Office App packs its pump_* tables and pump_files/ into a zip
# (GET /internal/pumps-export, private network + secret, only once PUMPS_URL is
# set so it has stopped writing them). The Pumps service fetches it on start-up
# when PUMPS_IMPORT_FROM_OFFICE is on, checks every table's row count and every
# file's size against the zip's manifest, and only then puts it in place.
# Nothing is deleted on either side: the Office App keeps its copy, and
# anything already on the Pumps volume is renamed aside, not overwritten.

def _is_pump_table(name):
    return name.startswith('pump_')


def export_bundle(db_path, data_dir, out_path):
    """Write the zip to out_path; returns the manifest."""
    tmp_db = out_path + '.db'
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(tmp_db)
    try:
        src.backup(dst)
    finally:
        src.close()
    try:
        tables = [r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for t in tables:
            if not _is_pump_table(t) and not t.startswith('sqlite_'):
                dst.execute(f'DROP TABLE "{t}"')
        dst.commit()
        counts = {t: dst.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables if _is_pump_table(t)}
        dst.execute('VACUUM')
    finally:
        dst.close()
    files_dir = os.path.join(data_dir, 'pump_files')
    files = {}
    for root, _dirs, names in os.walk(files_dir):
        for n in names:
            full = os.path.join(root, n)
            files[os.path.relpath(full, files_dir).replace(os.sep, '/')] = os.path.getsize(full)
    manifest = {'tables': counts, 'files': files, 'made_at': time.strftime('%Y-%m-%d %H:%M:%S')}
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_STORED, allowZip64=True) as z:
        z.write(tmp_db, 'pumps.db', compress_type=zipfile.ZIP_DEFLATED)
        for rel in files:
            z.write(os.path.join(files_dir, rel), 'pump_files/' + rel)
        z.writestr('manifest.json', json.dumps(manifest, indent=1))
    os.remove(tmp_db)
    return manifest


def _check_bundle(folder):
    with open(os.path.join(folder, 'manifest.json')) as f:
        manifest = json.load(f)
    conn = sqlite3.connect(os.path.join(folder, 'pumps.db'))
    try:
        for t, n in manifest['tables'].items():
            got = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            if got != n:
                raise RuntimeError(f'Pumps import: {t} has {got} rows, the Office App sent {n}')
    finally:
        conn.close()
    for rel, size in manifest['files'].items():
        p = os.path.join(folder, 'pump_files', *rel.split('/'))
        if not os.path.isfile(p) or os.path.getsize(p) != size:
            raise RuntimeError(f'Pumps import: file {rel} is missing or the wrong size')
    return manifest


def import_bundle(source_url, secret, db_path, data_dir):
    """Fetch, check and put the Office App's Pumps data in place, once.
    Returns the manifest, or None when it was already imported."""
    import fcntl
    import shutil
    os.makedirs(data_dir, exist_ok=True)
    marker = os.path.join(data_dir, '.pumps_imported')
    with open(os.path.join(data_dir, '.pumps_import.lock'), 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # gunicorn's workers start together; one imports
        if os.path.exists(marker):
            return None
        stage = os.path.join(data_dir, '.pumps_import')
        shutil.rmtree(stage, ignore_errors=True)
        os.makedirs(stage)
        zpath = os.path.join(stage, 'bundle.zip')
        with http_requests.get(source_url, headers={'X-Pumps-Secret': secret}, stream=True, timeout=600) as r:
            if r.status_code != 200:
                raise RuntimeError(f'Pumps import: the Office App answered HTTP {r.status_code}: {r.text[:300]}')
            with open(zpath, 'wb') as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        with zipfile.ZipFile(zpath) as z:
            for name in z.namelist():
                if name.startswith('/') or '..' in name.split('/'):
                    raise RuntimeError(f'Pumps import: unexpected path in the zip: {name}')
            z.extractall(stage)
        os.remove(zpath)
        manifest = _check_bundle(stage)
        stamp = time.strftime('%Y%m%d-%H%M%S')
        files_dir = os.path.join(data_dir, 'pump_files')
        for p in (db_path, db_path + '-wal', db_path + '-shm', files_dir):
            if os.path.exists(p):
                os.rename(p, f'{p}.before-import-{stamp}')
        os.rename(os.path.join(stage, 'pumps.db'), db_path)
        staged_files = os.path.join(stage, 'pump_files')
        if os.path.isdir(staged_files):
            os.rename(staged_files, files_dir)
        else:
            os.makedirs(files_dir)
        with open(marker, 'w') as f:
            json.dump({'imported_at': stamp, 'tables': manifest['tables'], 'files': len(manifest['files'])}, f)
        shutil.rmtree(stage, ignore_errors=True)
        print(f"✓ Pumps import: {sum(manifest['tables'].values())} rows in {len(manifest['tables'])} tables, "
              f"{len(manifest['files'])} files - all checked")
        return manifest
