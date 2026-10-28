"""
Off-site backups: the whole database every few minutes and every uploaded file,
copied to S3-compatible storage outside the app's volume.

Primary storage is a Railway bucket (BACKUP_S3_*). A second copy can go to any
other S3-compatible store - Cloudflare R2, Backblaze B2, AWS - with the same
settings under BACKUP_OFFSITE_S3_*, so the backups outlive Railway itself.

What lands in the bucket:
    db/20261013T185500Z.db.gz              a consistent copy of po_requests.db
    db/20261013T190000Z-before-restore...  the database as it was just before a restore
    files/<path under DATA_DIR>            invoices, photos, receipts, pump reports...
    files-manifest.json                    which files are in files/ (size, mtime)

Kept: every database copy from the last 2 days, then the last one of each day
for 90 days, then the last one of each month. Files are never deleted.

Getting it back:
  - New server or empty volume: the app restores the newest copy by itself on
    start (BACKUP_RESTORE_ON_EMPTY=false turns that off), then pulls the files.
  - Running app: /backups lists every copy; restore one, or upload a file.
  - Anywhere else: python backups.py list | restore [KEY] [--files] [--force]

Hooked into app.py with restore_if_empty(DB_PATH, DATA_DIR) before the database
is opened and init_backups(app, csrf, DB_PATH, ...) after; see BACKUPS_README.md.
"""
import gzip
import json
import os
import shutil
import signal
import sqlite3
import sys
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests as http_requests
from flask import Blueprint, jsonify, redirect, render_template_string, request, session

try:
    import fcntl
except ImportError:  # Windows dev machines: fall back to in-process locks
    fcntl = None

TZ = ZoneInfo('America/New_York')
INTERVAL_MINUTES = max(1, int(os.environ.get('BACKUP_INTERVAL_MINUTES', '5') or 5))
RESTORE_ON_EMPTY = os.environ.get('BACKUP_RESTORE_ON_EMPTY', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
KEEP_ALL_DAYS = 2
KEEP_DAILY_DAYS = 90
# Back up the database at least this often even when nothing changed, so a quiet
# weekend still shows a fresh copy and the status page never looks stale.
HEARTBEAT = timedelta(hours=24)
# Tell Telegram once backups have failed for this long.
ALERT_AFTER = timedelta(minutes=30)
# Each service backing up to the same bucket keeps to its own folder: the Office
# App uses the top level (as it always has), the Pumps service BACKUP_PREFIX=pumps.
PREFIX = (os.environ.get('BACKUP_PREFIX', '').strip().strip('/') + '/').lstrip('/')
DB_PREFIX = PREFIX + 'db/'
FILES_PREFIX = PREFIX + 'files/'
MANIFEST_KEY = PREFIX + 'files-manifest.json'
# Who the Telegram alerts are about.
LABEL = os.environ.get('BACKUP_LABEL', '').strip() or 'Office App'

bp = Blueprint('backups', __name__)
_cfg = {'db_path': None, 'data_dir': None, 'allowed': None}
_thread_locks = {}


# ---------------------------------------------------------------- where backups go

def _dest_from_env(name, prefix):
    bucket = os.environ.get(prefix + 'BUCKET', '').strip()
    if not bucket:
        return None
    return {
        'name': name,
        'bucket': bucket,
        'endpoint': os.environ.get(prefix + 'ENDPOINT', '').strip() or None,
        'region': os.environ.get(prefix + 'REGION', '').strip() or 'auto',
        'key_id': os.environ.get(prefix + 'ACCESS_KEY_ID', '').strip(),
        'secret': os.environ.get(prefix + 'SECRET_ACCESS_KEY', '').strip(),
        'url_style': os.environ.get(prefix + 'URL_STYLE', '').strip().lower(),
    }


def destinations():
    """Configured storage, primary first."""
    return [d for d in (_dest_from_env('primary', 'BACKUP_S3_'), _dest_from_env('offsite', 'BACKUP_OFFSITE_S3_')) if d]


def configured():
    return bool(destinations())


def _dest(name=None):
    dests = destinations()
    if not dests:
        raise RuntimeError('No backup storage configured (BACKUP_S3_BUCKET is not set)')
    if not name:
        return dests[0]
    for d in dests:
        if d['name'] == name:
            return d
    raise RuntimeError(f'No backup storage called {name!r}')


_clients = {}


def _s3(dest):
    key = (dest['name'], dest['bucket'], dest['endpoint'], dest['key_id'])
    if key not in _clients:
        import boto3
        from botocore.config import Config
        style = 'path' if dest['url_style'] == 'path' else 'virtual' if dest['url_style'].startswith('virtual') else 'auto'
        _clients[key] = boto3.client(
            's3', endpoint_url=dest['endpoint'], region_name=dest['region'],
            aws_access_key_id=dest['key_id'] or None, aws_secret_access_key=dest['secret'] or None,
            config=Config(signature_version='s3v4', s3={'addressing_style': style}, retries={'max_attempts': 5},
                          # Newer boto3 adds checksums that R2, B2 and Railway buckets can refuse.
                          request_checksum_calculation='when_required',
                          response_checksum_validation='when_required'))
    return _clients[key]


def _list_keys(dest, prefix):
    out = []
    for page in _s3(dest).get_paginator('list_objects_v2').paginate(Bucket=dest['bucket'], Prefix=prefix):
        out.extend(page.get('Contents', []))
    return out


# ---------------------------------------------------------------- local state

def _data_path(*parts):
    return os.path.join(_cfg['data_dir'], *parts)


def _status_path():
    return _data_path('.backup_status.json')


def _load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save_json(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f)
    os.replace(tmp, path)


def load_status():
    return _load_json(_status_path(), {})


def _now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(dt):
    return dt.isoformat() if dt else None


def _parse_iso(s):
    try:
        return datetime.fromisoformat(s) if s else None
    except ValueError:
        return None


class _FileLock:
    """A lock every gunicorn worker respects - a flock on a file beside the database."""

    def __init__(self, name, blocking=True):
        self.path = _data_path(f'.backup_{name}.lock')
        self.tlock = _thread_locks.setdefault(name, threading.Lock())
        self.blocking = blocking
        self.fh = None
        self.held = False

    def __enter__(self):
        if not self.tlock.acquire(blocking=self.blocking):
            return False
        if fcntl:
            self.fh = open(self.path, 'w')
            try:
                fcntl.flock(self.fh, fcntl.LOCK_EX | (0 if self.blocking else fcntl.LOCK_NB))
            except OSError:
                self.fh.close()
                self.fh = None
                self.tlock.release()
                return False
        self.held = True
        return True

    def __exit__(self, *exc):
        if self.held:
            if self.fh:
                fcntl.flock(self.fh, fcntl.LOCK_UN)
                self.fh.close()
            self.tlock.release()
        return False


# ---------------------------------------------------------------- database copies

def _db_fingerprint():
    """Changes whenever the database file does."""
    parts = []
    for suffix in ('', '-journal', '-wal'):
        try:
            st = os.stat(_cfg['db_path'] + suffix)
            parts.append(f'{st.st_mtime_ns}:{st.st_size}')
        except OSError:
            parts.append('-')
    return '|'.join(parts)


def _snapshot_key(when, label=''):
    return f"{DB_PREFIX}{when.strftime('%Y%m%dT%H%M%SZ')}{('-' + label) if label else ''}.db.gz"


def _key_time(key):
    """When a database copy was taken, from its name."""
    try:
        return datetime.strptime(key[len(DB_PREFIX):len(DB_PREFIX) + 16], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _copy_db(src_path, dst_path):
    """A consistent copy of a live SQLite database (other workers may be writing).
    One step: it holds the read lock for well under a second even for a few
    hundred MB, and the app's connections wait 5-30 s for a lock, so a save made
    during a backup just waits a moment. (A copy in small steps would let SQLite
    start it over on every save and might never finish on a busy day.)"""
    src = sqlite3.connect(src_path, timeout=30)
    dst = sqlite3.connect(dst_path)
    t0 = time.time()
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    took = time.time() - t0
    if took > 2:
        print(f'⚠ Backups: copying the database took {took:.1f}s - saves wait that long while it runs')


def check_db_file(path):
    """Raise ValueError unless path is a readable, healthy SQLite database with tables in it."""
    with open(path, 'rb') as f:
        if f.read(16) != b'SQLite format 3\x00':
            raise ValueError('That is not a SQLite database file')
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        result = conn.execute('PRAGMA quick_check').fetchone()[0]
        if result != 'ok':
            raise ValueError(f'The database is damaged: {result}')
        tables = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        if not tables:
            raise ValueError('The database is empty (no tables)')
    finally:
        conn.close()


def _gzip(src, dst):
    with open(src, 'rb') as fin, gzip.open(dst, 'wb', compresslevel=6) as fout:
        shutil.copyfileobj(fin, fout, 1024 * 1024)


def _gunzip(src, dst):
    with gzip.open(src, 'rb') as fin, open(dst, 'wb') as fout:
        shutil.copyfileobj(fin, fout, 1024 * 1024)


def _make_snapshot(workdir):
    """Copy, check and compress the live database. Returns the .gz path."""
    raw = os.path.join(workdir, 'snapshot.db')
    _copy_db(_cfg['db_path'], raw)
    check_db_file(raw)
    gz = raw + '.gz'
    _gzip(raw, gz)
    os.remove(raw)
    return gz


def _upload_snapshot(dest, gz_path, key, meta=None):
    _s3(dest).upload_file(gz_path, dest['bucket'], key,
                          ExtraArgs={'ContentType': 'application/gzip', 'Metadata': meta or {}})


def list_snapshots(dest_name=None, limit=None):
    """Database copies in storage, newest first: [{key, size, when}]."""
    dest = _dest(dest_name)
    rows = []
    for obj in _list_keys(dest, DB_PREFIX):
        when = _key_time(obj['Key'])
        if when and obj['Key'].endswith('.db.gz'):
            rows.append({'key': obj['Key'], 'size': obj['Size'], 'when': when,
                         'before_restore': '-before-restore' in obj['Key']})
    rows.sort(key=lambda r: r['key'], reverse=True)
    return rows[:limit] if limit else rows


def download_snapshot(key, dst_path, dest_name=None):
    """Fetch one database copy, unzip it to dst_path and check it."""
    dest = _dest(dest_name)
    if not key.startswith(DB_PREFIX) or '..' in key:
        raise ValueError('Not a database backup')
    fd, gz = tempfile.mkstemp(suffix='.db.gz', dir=os.path.dirname(dst_path) or None)
    os.close(fd)
    try:
        _s3(dest).download_file(dest['bucket'], key, gz)
        _gunzip(gz, dst_path)
    finally:
        os.remove(gz)
    check_db_file(dst_path)


def prune_snapshots(dest, now=None):
    """Thin out old copies. Returns how many were deleted."""
    now = now or _now_utc()
    snaps = [s for s in list_snapshots(dest['name'])]
    keep, seen_days, seen_months = set(), set(), set()
    for s in snaps:  # newest first, so the first of each day/month seen is that day's last
        age = now - s['when']
        day, month = s['when'].strftime('%Y-%m-%d'), s['when'].strftime('%Y-%m')
        if age < timedelta(days=KEEP_ALL_DAYS):
            keep.add(s['key'])
        elif age < timedelta(days=KEEP_DAILY_DAYS):
            if day not in seen_days:
                keep.add(s['key'])
        elif month not in seen_months:
            keep.add(s['key'])
        seen_days.add(day)
        seen_months.add(month)
    doomed = [s['key'] for s in snaps if s['key'] not in keep]
    if snaps and len(doomed) == len(snaps):  # never leave nothing behind
        doomed = doomed[1:]
    for i in range(0, len(doomed), 1000):
        _s3(dest).delete_objects(Bucket=dest['bucket'],
                                 Delete={'Objects': [{'Key': k} for k in doomed[i:i + 1000]], 'Quiet': True})
    return len(doomed)


# ---------------------------------------------------------------- uploaded files

def _skip_name(name):
    return (name.startswith('.') or name.endswith(('.tmp', '.lock', '.restoring'))
            or '.before-restore-' in name or name == '__pycache__')


def scan_files():
    """Every file under DATA_DIR worth keeping: {relative path: [size, mtime]}.
    Leaves out the database itself (copied separately), lock and temp files, and
    the old local backups folder."""
    root = _cfg['data_dir']
    db = os.path.abspath(_cfg['db_path'])
    db_family = {db, db + '-journal', db + '-wal', db + '-shm'}
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        dirnames[:] = [d for d in dirnames
                       if not _skip_name(d) and not (rel_dir == '.' and d in ('backups', 'lost+found'))]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            if _skip_name(fn) or os.path.abspath(full) in db_family or not os.path.isfile(full):
                continue
            st = os.stat(full)
            out[os.path.relpath(full, root).replace(os.sep, '/')] = [st.st_size, int(st.st_mtime)]
    return out


def _manifest_path(dest):
    return _data_path(f".backup_manifest_{dest['name']}.json")


def _remote_manifest(dest):
    try:
        body = _s3(dest).get_object(Bucket=dest['bucket'], Key=MANIFEST_KEY)['Body'].read()
        return json.loads(body)
    except Exception as e:
        code = getattr(e, 'response', {}).get('Error', {}).get('Code')
        if code in ('NoSuchKey', '404', 'NotFound'):
            return {}
        raise


def sync_files(dest):
    """Upload new and changed files. Returns how many went up."""
    path = _manifest_path(dest)
    manifest = _load_json(path, None)
    if manifest is None:  # first run on this volume: start from what storage already has
        manifest = _remote_manifest(dest)
    current = scan_files()
    sent = 0
    for rel, sig in sorted(current.items()):
        if manifest.get(rel) == sig:
            continue
        _s3(dest).upload_file(os.path.join(_cfg['data_dir'], rel), dest['bucket'], FILES_PREFIX + rel)
        manifest[rel] = sig
        sent += 1
        if sent % 50 == 0:  # a big first upload survives a restart part-way
            _save_json(path, manifest)
    if sent or not os.path.exists(path):
        _s3(dest).put_object(Bucket=dest['bucket'], Key=MANIFEST_KEY, Body=json.dumps(manifest).encode(),
                             ContentType='application/json')
        _save_json(path, manifest)
    return sent


def restore_files(dest_name=None, overwrite=False, log=print):
    """Download backed-up files that are missing here (or differ, with overwrite).
    Returns how many came down."""
    dest = _dest(dest_name)
    manifest = _remote_manifest(dest)
    root = os.path.abspath(_cfg['data_dir'])
    got = 0
    for rel, (size, mtime) in sorted(manifest.items()):
        target = os.path.abspath(os.path.join(root, rel))
        if not target.startswith(root + os.sep):
            continue
        if os.path.exists(target) and (not overwrite or os.path.getsize(target) == size):
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = target + '.tmp'
        _s3(dest).download_file(dest['bucket'], FILES_PREFIX + rel, tmp)
        os.replace(tmp, target)
        os.utime(target, (mtime, mtime))
        got += 1
        if got % 100 == 0:
            log(f'  … {got} files restored')
    # What is on disk now matches storage, so nothing needs re-uploading.
    _save_json(_manifest_path(dest), manifest)
    return got


# ---------------------------------------------------------------- the job

def _telegram(text):
    token, chat = os.environ.get('TELEGRAM_BOT_TOKEN', ''), os.environ.get('TELEGRAM_CHAT_ID', '')
    if not (token and chat):
        return
    try:
        http_requests.post(f'https://api.telegram.org/bot{token}/sendMessage',
                           json={'chat_id': chat, 'text': text}, timeout=15)
    except Exception as e:
        print(f'⚠ Backups: could not send Telegram alert: {e}')


def run_backup(force=False):
    """Copy the database (if it changed) and any new files to every destination.
    Safe to call from every worker: only one runs at a time, the rest skip.
    Returns the status dict, or None if another worker was already running it."""
    dests = destinations()
    if not dests:
        return None
    with _FileLock('run', blocking=False) as held:
        if not held:
            return None
        status = load_status()
        now = _now_utc()
        fingerprint = _db_fingerprint()
        workdir = tempfile.mkdtemp(prefix='.backup_tmp_', dir=_cfg['data_dir'])
        gz = None
        try:
            for dest in dests:
                st = status.setdefault(dest['name'], {})
                st['bucket'] = dest['bucket']
                try:
                    last_ok = _parse_iso(st.get('last_snapshot_at'))
                    if force or st.get('fingerprint') != fingerprint or not last_ok or now - last_ok > HEARTBEAT:
                        if gz is None:
                            gz = _make_snapshot(workdir)
                        key = _snapshot_key(now)
                        _upload_snapshot(dest, gz, key)
                        st.update(fingerprint=fingerprint, last_snapshot_at=_iso(now), last_snapshot_key=key,
                                  last_snapshot_size=os.path.getsize(gz))
                    sent = sync_files(dest)
                    st['files_sent_last_run'] = sent
                    st['files_total'] = len(_load_json(_manifest_path(dest), {}))
                    last_prune = _parse_iso(st.get('last_prune_at'))
                    if not last_prune or now - last_prune > timedelta(hours=6):
                        st['pruned_last'] = prune_snapshots(dest, now)
                        st['last_prune_at'] = _iso(now)
                    if st.get('alerted'):
                        _telegram(f"✅ {LABEL} backups to {dest['name']} storage are working again.")
                    st.update(last_ok_at=_iso(now), last_error=None, failing_since=None, alerted=False)
                except Exception as e:
                    print(f"✗ Backup to {dest['name']} storage failed: {e}")
                    st['last_error'] = str(e)[:500]
                    st['last_error_at'] = _iso(now)
                    st['failing_since'] = st.get('failing_since') or _iso(now)
                    since = _parse_iso(st['failing_since'])
                    if not st.get('alerted') and since and now - since >= ALERT_AFTER:
                        _telegram(f"⚠️ {LABEL} backups to {dest['name']} storage have been failing since "
                                  f"{since.astimezone(TZ):%b %-d %-I:%M %p}: {st['last_error']}")
                        st['alerted'] = True
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            _save_json(_status_path(), status)
        return status


def _in_background(fn):
    threading.Thread(target=fn, daemon=True).start()


def _scheduled():
    try:
        run_backup()
    except Exception as e:
        print(f'✗ Backup job crashed: {e}')


# ---------------------------------------------------------------- restoring

def _reload_workers_soon():
    """After a restore, have gunicorn restart its workers so every cache and
    migration starts from the restored database."""
    if 'gunicorn' not in os.path.basename(sys.argv[0] or ''):
        return

    def _hup():
        time.sleep(2)
        try:
            os.kill(os.getppid(), signal.SIGHUP)
        except OSError as e:
            print(f'⚠ Backups: could not reload workers: {e}')
    threading.Thread(target=_hup, daemon=True).start()


def _save_current_aside(workdir, who):
    """Keep the database as it is right now - locally and in storage - before
    anything overwrites it. Returns the storage key, or None."""
    if not os.path.exists(_cfg['db_path']):
        return None
    gz = _make_snapshot(workdir)
    local_dir = _data_path('backups')
    os.makedirs(local_dir, exist_ok=True)
    stamp = _now_utc()
    shutil.copy2(gz, os.path.join(local_dir, f"po_app_backup_{stamp.strftime('%Y%m%d_%H%M%S')}_before_restore.db.gz"))
    key = None
    for dest in destinations():
        try:
            key = _snapshot_key(stamp, 'before-restore')
            _upload_snapshot(dest, gz, key, meta={'by': who or ''})
        except Exception as e:
            print(f"⚠ Backups: could not store pre-restore copy in {dest['name']}: {e}")
    return key


def restore_db_from_file(path, who=''):
    """Replace the live database with the one at path (already unzipped and checked).
    The current database is saved first. Returns the key of that saved copy."""
    check_db_file(path)
    workdir = tempfile.mkdtemp(prefix='.backup_tmp_', dir=_cfg['data_dir'])
    try:
        with _FileLock('run'):
            saved = _save_current_aside(workdir, who)
            # Page-by-page copy into the open database, so other workers' connections
            # see the restored data rather than a file swapped out underneath them.
            src = sqlite3.connect(path)
            dst = sqlite3.connect(_cfg['db_path'], timeout=60)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
        print(f"✓ Database restored by {who or 'unknown'}; previous copy kept as {saved}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    _in_background(_scheduled)
    _reload_workers_soon()
    return saved


def unpack_upload(src_path, workdir):
    """Turn an uploaded backup (.db, .db.gz, or a .zip from the old Backup button)
    into a plain database file. Returns its path."""
    out = os.path.join(workdir, 'uploaded.db')
    with open(src_path, 'rb') as f:
        head = f.read(4)
    if head[:2] == b'\x1f\x8b':
        _gunzip(src_path, out)
    elif head == b'PK\x03\x04':
        with zipfile.ZipFile(src_path) as zf:
            names = [n for n in zf.namelist() if n.endswith(('.db', '.sqlite', '.sqlite3'))]
            if not names:
                raise ValueError('That zip has no database file in it')
            with zf.open(names[0]) as fin, open(out, 'wb') as fout:
                shutil.copyfileobj(fin, fout, 1024 * 1024)
    else:
        shutil.copyfile(src_path, out)
    check_db_file(out)
    return out


def restore_if_empty(db_path, data_dir):
    """On a new server or an empty volume, bring back the newest database copy
    before the app creates a blank one, then pull the files in the background.
    Does nothing when the database already exists or no storage is configured."""
    _cfg.update(db_path=db_path, data_dir=data_dir)
    if not RESTORE_ON_EMPTY or not configured() or os.path.exists(db_path):
        return False
    os.makedirs(data_dir, exist_ok=True)
    with _FileLock('restore'):
        if os.path.exists(db_path):  # another worker got there first
            return False
        try:
            snaps = list_snapshots()
        except Exception as e:
            print(f'⚠ Backups: no database here and storage could not be read ({e}); starting blank')
            return False
        snaps = [s for s in snaps if not s['before_restore']] or snaps
        if not snaps:
            print('ℹ Backups: no database here and none in storage yet; starting blank')
            return False
        tmp = db_path + '.restoring'
        try:
            download_snapshot(snaps[0]['key'], tmp)
            os.replace(tmp, db_path)
        except Exception as e:
            print(f"✗ Backups: could not restore {snaps[0]['key']}: {e}; starting blank")
            if os.path.exists(tmp):
                os.remove(tmp)
            return False
        print(f"✓ Backups: empty volume - restored database from {snaps[0]['key']}")

    def _files():
        with _FileLock('restore_files', blocking=False) as held:
            if held:
                try:
                    n = restore_files()
                    print(f'✓ Backups: restored {n} files from storage')
                except Exception as e:
                    print(f'✗ Backups: file restore failed: {e} (retry from the Backups page)')
    _in_background(_files)
    return True


# ---------------------------------------------------------------- pages

def _allowed():
    return 'username' in session and bool(_cfg['allowed'] and _cfg['allowed']())


def _who():
    return session.get('username', '')


def _fmt_time(dt):
    return dt.astimezone(TZ).strftime('%a %b %-d, %Y %-I:%M %p') if dt else '—'


def _fmt_size(n):
    if n is None:
        return '—'
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024


@bp.route('/backups')
def backups_page():
    if not _allowed():
        return redirect('/')
    dests = destinations()
    status = load_status()
    rows, list_error = [], None
    view = []
    for d in dests:
        st = status.get(d['name'], {})
        view.append({
            'name': d['name'], 'bucket': d['bucket'], 'endpoint': d['endpoint'] or 'AWS',
            'last_ok': _fmt_time(_parse_iso(st.get('last_ok_at'))),
            'last_snapshot': _fmt_time(_parse_iso(st.get('last_snapshot_at'))),
            'last_snapshot_size': _fmt_size(st.get('last_snapshot_size')),
            'files_total': st.get('files_total'),
            'error': st.get('last_error'), 'error_at': _fmt_time(_parse_iso(st.get('last_error_at'))),
            'stale': not st.get('last_ok_at') or (_now_utc() - _parse_iso(st['last_ok_at'])
                                                  > timedelta(minutes=INTERVAL_MINUTES * 3 + 5)),
        })
    if dests:
        try:
            rows = [dict(r, when_text=_fmt_time(r['when']), size_text=_fmt_size(r['size']))
                    for r in list_snapshots(limit=300)]
        except Exception as e:
            list_error = str(e)
    return render_template_string(PAGE_TEMPLATE, dests=view, rows=rows, list_error=list_error,
                                   interval=INTERVAL_MINUTES, keep_all=KEEP_ALL_DAYS, keep_daily=KEEP_DAILY_DAYS)


@bp.route('/backups/run', methods=['POST'])
def backups_run():
    if not _allowed():
        return jsonify({'ok': False, 'error': 'Not allowed'}), 403
    if not configured():
        return jsonify({'ok': False, 'error': 'Backup storage is not set up'}), 400
    status = run_backup(force=True)
    if status is None:
        return jsonify({'ok': False, 'error': 'A backup is already running - try again in a minute'}), 409
    errors = [f"{n}: {s['last_error']}" for n, s in status.items() if isinstance(s, dict) and s.get('last_error')]
    if errors:
        return jsonify({'ok': False, 'error': '; '.join(errors)}), 502
    return jsonify({'ok': True})


@bp.route('/backups/download')
def backups_download():
    if not _allowed():
        return 'Not allowed', 403
    key = request.args.get('key', '')
    if not key.startswith(DB_PREFIX) or '..' in key:
        return 'Not a database backup', 400
    dest = _dest()
    url = _s3(dest).generate_presigned_url(
        'get_object', ExpiresIn=300,
        Params={'Bucket': dest['bucket'], 'Key': key,
                'ResponseContentDisposition': f'attachment; filename="po_requests_{key[len(DB_PREFIX):]}"'})
    return redirect(url)


@bp.route('/backups/restore', methods=['POST'])
def backups_restore():
    if not _allowed():
        return jsonify({'ok': False, 'error': 'Not allowed'}), 403
    if (request.form.get('confirm') or '').strip().upper() != 'RESTORE':
        return jsonify({'ok': False, 'error': 'Type RESTORE to confirm'}), 400
    workdir = tempfile.mkdtemp(prefix='.backup_tmp_', dir=_cfg['data_dir'])
    try:
        upload = request.files.get('file')
        if upload and upload.filename:
            raw = os.path.join(workdir, 'upload.bin')
            upload.save(raw)
            path = unpack_upload(raw, workdir)
            source = upload.filename
        else:
            key = request.form.get('key', '')
            if not configured():
                return jsonify({'ok': False, 'error': 'Backup storage is not set up'}), 400
            path = os.path.join(workdir, 'snapshot.db')
            download_snapshot(key, path)
            source = key
        saved = restore_db_from_file(path, who=_who())
        print(f'✓ Restore source: {source}')
        return jsonify({'ok': True, 'saved': saved, 'source': source})
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Restore failed: {e}'}), 500
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@bp.route('/backups/restore-files', methods=['POST'])
def backups_restore_files():
    if not _allowed():
        return jsonify({'ok': False, 'error': 'Not allowed'}), 403
    if not configured():
        return jsonify({'ok': False, 'error': 'Backup storage is not set up'}), 400

    def _go():
        with _FileLock('restore_files', blocking=False) as held:
            if held:
                try:
                    print(f'✓ Backups: restored {restore_files()} missing files')
                except Exception as e:
                    print(f'✗ Backups: file restore failed: {e}')
    _in_background(_go)
    return jsonify({'ok': True})


def init_backups(app, csrf, db_path, *, data_dir, allowed, scheduler_cls=None):
    """Register the Backups page and start the job. allowed() says whether the
    signed-in user may see and restore backups."""
    _cfg.update(db_path=db_path, data_dir=data_dir, allowed=allowed)
    app.register_blueprint(bp)
    dests = destinations()
    if not dests:
        print('⚠ Backups: BACKUP_S3_BUCKET not set - the database is NOT being backed up off the volume')
        return
    for d in dests:
        print(f"✓ Backups: every {INTERVAL_MINUTES} min to {d['name']} storage ({d['bucket']})")
    if scheduler_cls:
        # Every worker schedules it; the job's file lock lets only one run at a time.
        sched = scheduler_cls()
        sched.add_job(_scheduled, 'interval', minutes=INTERVAL_MINUTES, id='offsite_backup',
                      next_run_time=datetime.now() + timedelta(seconds=45), max_instances=1, coalesce=True)
        sched.start()


PAGE_TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Backups — Stahlman-England</title>
<meta name="csrf-token" content="{{ csrf_token() }}">
<style>
  :root { --brand:#2563EB; --ink:#0F172A; --ink2:#475569; --ink3:#94A3B8; --bg:#F8FAFC; --card:#fff;
          --line:#E2E8F0; --good:#059669; --good-bg:#ECFDF5; --warn:#B45309; --warn-bg:#FFFBEB; --bad:#DC2626; --bad-bg:#FEF2F2; }
  *,*::before,*::after { box-sizing:border-box; }
  body { margin:0; font-family:Inter,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; background:var(--bg); color:var(--ink); font-size:14px; line-height:1.45; }
  a { color:var(--brand); text-decoration:none; }
  .top { background:#fff; border-bottom:1px solid var(--line); }
  .top-in { max-width:1100px; margin:0 auto; padding:0 20px; height:58px; display:flex; align-items:center; gap:14px; }
  .top-in h1 { font-size:17px; margin:0; }
  .wrap { max-width:1100px; margin:0 auto; padding:20px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:18px 20px; margin-bottom:18px; }
  .card h2 { font-size:15px; margin:0 0 10px; }
  .muted { color:var(--ink2); }
  .pill { display:inline-block; padding:2px 9px; border-radius:99px; font-size:12px; font-weight:600; }
  .ok { background:var(--good-bg); color:var(--good); } .warn { background:var(--warn-bg); color:var(--warn); } .bad { background:var(--bad-bg); color:var(--bad); }
  .alert { padding:12px 14px; border-radius:8px; margin-bottom:18px; }
  table { width:100%; border-collapse:collapse; }
  th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); }
  th { font-size:12px; color:var(--ink2); font-weight:600; }
  .btn { display:inline-block; border:1px solid var(--line); background:#fff; color:var(--ink); padding:6px 12px; border-radius:7px; font-size:13px; cursor:pointer; }
  .btn.primary { background:var(--brand); border-color:var(--brand); color:#fff; }
  .btn.danger { color:var(--bad); border-color:#FECACA; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:10px 24px; }
  .scroll { max-height:520px; overflow:auto; }
  #msg { display:none; }
  code { background:#F1F5F9; padding:1px 5px; border-radius:4px; font-size:12px; }
</style>
</head>
<body>
<div class="top"><div class="top-in"><a href="/">← Office App</a><h1>Backups</h1></div></div>
<div class="wrap">
  <div id="msg" class="alert"></div>

  {% if not dests %}
  <div class="alert bad"><b>Backups are not set up.</b> The database only lives on the app's volume.
    Set <code>BACKUP_S3_BUCKET</code>, <code>BACKUP_S3_ENDPOINT</code>, <code>BACKUP_S3_ACCESS_KEY_ID</code> and
    <code>BACKUP_S3_SECRET_ACCESS_KEY</code> on the service (see BACKUPS_README.md).</div>
  {% endif %}

  {% for d in dests %}
  <div class="card">
    <h2>{{ 'Main' if d.name == 'primary' else 'Off-site' }} storage
      {% if d.error %}<span class="pill bad">Failing</span>{% elif d.stale %}<span class="pill warn">Not run yet / late</span>{% else %}<span class="pill ok">Working</span>{% endif %}</h2>
    <div class="grid">
      <div><span class="muted">Last successful run</span><br>{{ d.last_ok }}</div>
      <div><span class="muted">Newest database copy</span><br>{{ d.last_snapshot }} · {{ d.last_snapshot_size }}</div>
      <div><span class="muted">Files backed up</span><br>{{ d.files_total if d.files_total is not none else '—' }}</div>
      <div><span class="muted">Bucket</span><br><code>{{ d.bucket }}</code></div>
    </div>
    {% if d.error %}<p class="alert bad" style="margin:12px 0 0">Last error ({{ d.error_at }}): {{ d.error }}</p>{% endif %}
  </div>
  {% endfor %}

  {% if dests %}
  <div class="card">
    <h2>How it works</h2>
    <p class="muted" style="margin:0 0 10px">Every {{ interval }} minutes the database is copied to storage if anything changed, along with any
      new uploaded files (invoices, photos, receipts, reports). Every copy from the last {{ keep_all }} days is kept, then one a day
      for {{ keep_daily }} days, then one a month. A new server with an empty volume restores the newest copy by itself.</p>
    <button class="btn primary" onclick="runNow(this)">Back up now</button>
    <button class="btn" onclick="restoreFiles(this)">Restore missing files</button>
  </div>

  <div class="card">
    <h2>Database copies</h2>
    {% if list_error %}<p class="alert bad">Could not read storage: {{ list_error }}</p>{% endif %}
    <div class="scroll"><table>
      <thead><tr><th>Taken</th><th>Size</th><th></th><th></th></tr></thead>
      <tbody>
      {% for r in rows %}
        <tr><td>{{ r.when_text }}{% if r.before_restore %} <span class="pill warn">saved before a restore</span>{% endif %}</td>
          <td>{{ r.size_text }}</td>
          <td><a class="btn" href="{{ url_for('backups.backups_download', key=r.key) }}">Download</a></td>
          <td><button class="btn danger" data-key="{{ r.key }}" data-when="{{ r.when_text }}" onclick="restoreKey(this)">Restore</button></td></tr>
      {% else %}
        <tr><td colspan="4" class="muted">No copies yet - the first one runs within a minute of the app starting.</td></tr>
      {% endfor %}
      </tbody>
    </table></div>
  </div>
  {% endif %}

  <div class="card">
    <h2>Restore from a file</h2>
    <p class="muted" style="margin:0 0 10px">Upload a downloaded copy (<code>.db.gz</code>), a plain <code>.db</code>, or a <code>.zip</code> from the old Backup button.
      The current database is saved first, so a restore can always be undone.</p>
    <input type="file" id="file" accept=".db,.gz,.zip,.sqlite,.sqlite3">
    <button class="btn danger" onclick="restoreUpload(this)">Restore this file</button>
  </div>
</div>
<script>
var CSRF = document.querySelector('meta[name="csrf-token"]').content;
function show(text, kind) { var m = document.getElementById('msg'); m.className = 'alert ' + kind; m.textContent = text; m.style.display = 'block'; window.scrollTo(0, 0); }
function post(url, body, btn, done) {
  btn.disabled = true;
  fetch(url, { method:'POST', headers:{ 'X-CSRFToken': CSRF }, body: body })
    .then(function (r) { return r.json(); })
    .then(function (d) { btn.disabled = false; if (d.ok) done(d); else show(d.error || 'Something went wrong', 'bad'); })
    .catch(function (e) { btn.disabled = false; show(String(e), 'bad'); });
}
function confirmRestore(what) {
  return (prompt('This replaces ALL current data with ' + what + '.\nThe current database is saved first.\n\nType RESTORE to continue:') || '').trim().toUpperCase() === 'RESTORE';
}
function runNow(btn) { show('Backing up…', 'warn'); post('{{ url_for("backups.backups_run") }}', new FormData(), btn, function () { location.reload(); }); }
function restoreFiles(btn) { post('{{ url_for("backups.backups_restore_files") }}', new FormData(), btn, function () { show('Restoring missing files in the background - refresh in a few minutes.', 'ok'); }); }
function afterRestore(d) { show('Restored from ' + d.source + '. The previous data was saved' + (d.saved ? ' as ' + d.saved : '') + '. The app is reloading…', 'ok'); setTimeout(function () { location.reload(); }, 6000); }
function restoreKey(btn) {
  if (!confirmRestore('the copy from ' + btn.dataset.when)) return;
  var f = new FormData(); f.append('key', btn.dataset.key); f.append('confirm', 'RESTORE');
  show('Restoring…', 'warn'); post('{{ url_for("backups.backups_restore") }}', f, btn, afterRestore);
}
function restoreUpload(btn) {
  var input = document.getElementById('file');
  if (!input.files.length) { show('Choose a backup file first', 'bad'); return; }
  if (!confirmRestore(input.files[0].name)) return;
  var f = new FormData(); f.append('file', input.files[0]); f.append('confirm', 'RESTORE');
  show('Uploading and restoring…', 'warn'); post('{{ url_for("backups.backups_restore") }}', f, btn, afterRestore);
}
</script>
</body>
</html>
'''


# ---------------------------------------------------------------- command line

def _main(argv):
    """python backups.py list | restore [KEY] [--files] [--force] [--offsite]
    Uses DATA_DIR (default: this folder) and the same BACKUP_* settings as the app."""
    import argparse
    p = argparse.ArgumentParser(description='Office App backups')
    p.add_argument('command', choices=('list', 'restore', 'backup'))
    p.add_argument('key', nargs='?', help='database copy to restore (default: newest)')
    p.add_argument('--files', action='store_true', help='also download the uploaded files')
    p.add_argument('--force', action='store_true', help='replace an existing database (it is saved aside first)')
    p.add_argument('--offsite', action='store_true', help='use the off-site storage instead of the main one')
    a = p.parse_args(argv)
    data_dir = os.environ.get('DATA_DIR', os.path.dirname(os.path.abspath(__file__)))
    _cfg.update(data_dir=data_dir, db_path=os.path.join(data_dir, 'po_requests.db'))
    dest = 'offsite' if a.offsite else None
    if a.command == 'list':
        for s in list_snapshots(dest):
            print(f"{s['key']}  {_fmt_size(s['size']):>9}  {_fmt_time(s['when'])}")
        return 0
    if a.command == 'backup':
        print(json.dumps(run_backup(force=True), indent=2, default=str))
        return 0
    os.makedirs(data_dir, exist_ok=True)
    key = a.key or next((s['key'] for s in list_snapshots(dest) if not s['before_restore']), None)
    if not key:
        print('No database copies in storage')
        return 1
    db = _cfg['db_path']
    if os.path.exists(db):
        if not a.force:
            print(f'{db} already exists - add --force to replace it (it is kept as a .before-restore copy)')
            return 1
        aside = f"{db}.before-restore-{_now_utc().strftime('%Y%m%dT%H%M%SZ')}"
        _copy_db(db, aside)
        print(f'Saved the current database as {aside}')
    tmp = db + '.restoring'
    download_snapshot(key, tmp, dest)
    if os.path.exists(db):
        src, dst = sqlite3.connect(tmp), sqlite3.connect(db, timeout=60)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        os.remove(tmp)
    else:
        os.replace(tmp, db)
    print(f'✓ Restored {db} from {key}')
    if a.files:
        print(f'✓ Restored {restore_files(dest)} files into {data_dir}')
    return 0


if __name__ == '__main__':
    sys.exit(_main(sys.argv[1:]))
