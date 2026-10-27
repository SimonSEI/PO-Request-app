"""
Tests for off-site backups (backups.py).

    python -m unittest tests.test_backups -v

Storage is a fake S3 (moto); the database and files are throwaway copies.
"""
import gzip
import io
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix='backups_test_')
os.environ.update(SECRET_KEY='test-secret-key-0123456789abcdef-bk', DATA_DIR=TMP, PUMPS_AUTO_SCAN='false',
                  WORKORDERS_AUTO_RUN='false', AR_AUTO_RUN='false', WEBSITE_URL='https://office.example.com')
os.environ.pop('ANTHROPIC_API_KEY', None)
for _k in [k for k in os.environ if k.startswith(('BACKUP_S3_', 'BACKUP_OFFSITE_S3_', 'TELEGRAM_'))]:
    os.environ.pop(_k)

from moto import mock_aws  # noqa: E402

import app as A  # noqa: E402
import backups as B  # noqa: E402

A.app.config['TESTING'] = True
A.app.config['WTF_CSRF_ENABLED'] = False

STORAGE = {'BACKUP_S3_BUCKET': 'office-backups', 'BACKUP_S3_REGION': 'us-east-1',
           'BACKUP_S3_ACCESS_KEY_ID': 'test', 'BACKUP_S3_SECRET_ACCESS_KEY': 'test'}


def count_marks(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT count(*) FROM jobs WHERE job_name LIKE 'Backup test%'").fetchone()[0]
    finally:
        conn.close()


def add_mark(db_path, name):
    conn = sqlite3.connect(db_path)
    conn.execute('INSERT INTO jobs (job_name) VALUES (?)', (name,))
    conn.commit()
    conn.close()


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.aws = mock_aws()
        self.aws.start()
        self.env = mock.patch.dict(os.environ, STORAGE)
        self.env.start()
        B._clients.clear()
        B._cfg.update(db_path=A.DB_PATH, data_dir=TMP)
        self.s3 = B._s3(B._dest())
        self.s3.create_bucket(Bucket='office-backups')
        for f in os.listdir(TMP):
            if f.startswith('.backup_'):
                os.remove(os.path.join(TMP, f))
        conn = sqlite3.connect(A.DB_PATH)
        conn.execute("DELETE FROM jobs WHERE job_name LIKE 'Backup test%'")
        conn.commit()
        conn.close()
        os.makedirs(os.path.join(TMP, 'invoice_uploads'), exist_ok=True)
        with open(os.path.join(TMP, 'invoice_uploads', 'inv1.pdf'), 'wb') as f:
            f.write(b'%PDF-1.4 invoice one')
        self.client = A.app.test_client()
        # Restores kick off a background backup and a worker reload; keep tests synchronous.
        self.bg = mock.patch.object(B, '_scheduled', lambda: None)
        self.bg.start()

    def tearDown(self):
        self.bg.stop()
        self.env.stop()
        self.aws.stop()
        B._clients.clear()

    def login(self, role='office', username='simon'):
        with self.client.session_transaction() as s:
            s['username'] = username
            s['role'] = role
            s['full_name'] = 'Simon Test'

    def keys(self, prefix=''):
        return sorted(o['Key'] for o in self.s3.list_objects_v2(Bucket='office-backups', Prefix=prefix).get('Contents', []))

    # ------------------------------------------------------------ backing up

    def test_backs_up_database_and_files_and_skips_when_unchanged(self):
        add_mark(A.DB_PATH, 'Backup test 1')
        status = B.run_backup()
        self.assertIsNone(status['primary']['last_error'])
        snaps = self.keys('db/')
        self.assertEqual(len(snaps), 1)
        self.assertIn('files/invoice_uploads/inv1.pdf', self.keys('files/'))
        self.assertIn('files-manifest.json', self.keys())
        # The copy is a real, readable database with the data in it.
        out = os.path.join(TMP, 'check.db')
        B.download_snapshot(snaps[0], out)
        self.assertEqual(count_marks(out), 1)
        os.remove(out)
        # The database itself and lock files are not sent as "files".
        self.assertFalse([k for k in self.keys('files/') if 'po_requests.db' in k or '/.' in k])

        # Nothing changed: no new copy.
        with mock.patch.object(B, '_now_utc', return_value=B._now_utc() + timedelta(minutes=5)):
            B.run_backup()
        self.assertEqual(len(self.keys('db/')), 1)

        # A change: a new copy, and a new file goes up on its own.
        add_mark(A.DB_PATH, 'Backup test 2')
        with open(os.path.join(TMP, 'invoice_uploads', 'inv2.pdf'), 'wb') as f:
            f.write(b'%PDF-1.4 invoice two')
        with mock.patch.object(B, '_now_utc', return_value=B._now_utc() + timedelta(minutes=10)):
            status = B.run_backup()
        self.assertEqual(len(self.keys('db/')), 2)
        self.assertEqual(status['primary']['files_sent_last_run'], 1)

    def test_failure_is_recorded_and_alerted_once(self):
        sent = []
        with mock.patch.dict(os.environ, {'BACKUP_S3_BUCKET': 'no-such-bucket'}), \
                mock.patch.object(B, '_telegram', sent.append):
            B._clients.clear()
            start = B._now_utc()
            for minutes in (0, 10, 40, 50):
                with mock.patch.object(B, '_now_utc', return_value=start + timedelta(minutes=minutes)):
                    status = B.run_backup(force=True)
        self.assertTrue(status['primary']['last_error'])
        self.assertEqual(len(sent), 1)
        self.assertIn('failing', sent[0])
        # Working again: one all-clear.
        B._clients.clear()
        with mock.patch.object(B, '_telegram', sent.append):
            status = B.run_backup(force=True)
        self.assertIsNone(status['primary']['last_error'])
        self.assertEqual(len(sent), 2)

    def test_prune_keeps_recent_then_daily_then_monthly(self):
        now = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
        times = [now - timedelta(hours=h) for h in range(0, 30, 3)]           # last 2 days: all kept
        times += [now - timedelta(days=10, hours=h) for h in (1, 5, 9)]       # one day: keep newest
        times += [now - timedelta(days=200, hours=h) for h in (1, 30)]        # one month: keep newest
        for t in times:
            self.s3.put_object(Bucket='office-backups', Key=B._snapshot_key(t), Body=b'x')
        deleted = B.prune_snapshots(B._dest(), now)
        self.assertEqual(deleted, 3)
        left = self.keys('db/')
        self.assertEqual(len(left), 10 + 1 + 1)
        self.assertIn(B._snapshot_key(now - timedelta(days=10, hours=1)), left)
        self.assertIn(B._snapshot_key(now - timedelta(days=200, hours=1)), left)

    # ------------------------------------------------------------ restoring

    def test_new_server_restores_itself(self):
        add_mark(A.DB_PATH, 'Backup test 1')
        B.run_backup()
        fresh = tempfile.mkdtemp(prefix='backups_fresh_')
        try:
            db = os.path.join(fresh, 'po_requests.db')
            started = []
            with mock.patch.object(B, '_in_background', started.append):
                self.assertTrue(B.restore_if_empty(db, fresh))
            self.assertEqual(count_marks(db), 1)
            started[0]()  # the background file download
            with open(os.path.join(fresh, 'invoice_uploads', 'inv1.pdf'), 'rb') as f:
                self.assertEqual(f.read(), b'%PDF-1.4 invoice one')
            # Already has a database: left alone.
            self.assertFalse(B.restore_if_empty(db, fresh))
        finally:
            shutil.rmtree(fresh)
            B._cfg.update(db_path=A.DB_PATH, data_dir=TMP)

    def test_new_server_with_restore_off_starts_blank(self):
        B.run_backup()
        fresh = tempfile.mkdtemp(prefix='backups_fresh_')
        try:
            with mock.patch.object(B, 'RESTORE_ON_EMPTY', False):
                self.assertFalse(B.restore_if_empty(os.path.join(fresh, 'po_requests.db'), fresh))
            self.assertFalse(os.path.exists(os.path.join(fresh, 'po_requests.db')))
        finally:
            shutil.rmtree(fresh)
            B._cfg.update(db_path=A.DB_PATH, data_dir=TMP)

    def test_restore_a_copy_from_the_page_saves_current_first(self):
        add_mark(A.DB_PATH, 'Backup test 1')
        B.run_backup()
        key = self.keys('db/')[0]
        add_mark(A.DB_PATH, 'Backup test 2')
        self.assertEqual(count_marks(A.DB_PATH), 2)
        self.login()
        r = self.client.post('/backups/restore', data={'key': key, 'confirm': 'restore'})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(count_marks(A.DB_PATH), 1)
        saved = r.get_json()['saved']
        self.assertIn('before-restore', saved)
        out = os.path.join(TMP, 'check.db')
        B.download_snapshot(saved, out)
        self.assertEqual(count_marks(out), 2)  # the undo copy has what was there before
        os.remove(out)

    def test_restore_needs_typed_confirmation(self):
        B.run_backup()
        self.login()
        r = self.client.post('/backups/restore', data={'key': self.keys('db/')[0], 'confirm': 'yes'})
        self.assertEqual(r.status_code, 400)

    def test_restore_from_uploaded_files(self):
        add_mark(A.DB_PATH, 'Backup test 1')
        good = os.path.join(TMP, 'good.db')
        B._copy_db(A.DB_PATH, good)
        add_mark(A.DB_PATH, 'Backup test 2')
        with open(good, 'rb') as f:
            raw = f.read()
        os.remove(good)
        zbuf = io.BytesIO()
        with zipfile.ZipFile(zbuf, 'w') as zf:
            zf.writestr('po_app.db', raw)
        self.login()
        for name, body in (('copy.db.gz', gzip.compress(raw)), ('old.zip', zbuf.getvalue()), ('plain.db', raw)):
            add_mark(A.DB_PATH, 'Backup test extra')
            r = self.client.post('/backups/restore', content_type='multipart/form-data',
                                 data={'confirm': 'RESTORE', 'file': (io.BytesIO(body), name)})
            self.assertEqual(r.status_code, 200, (name, r.get_json()))
            self.assertEqual(count_marks(A.DB_PATH), 1, name)
        r = self.client.post('/backups/restore', content_type='multipart/form-data',
                             data={'confirm': 'RESTORE', 'file': (io.BytesIO(b'not a database'), 'x.db')})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(count_marks(A.DB_PATH), 1)

    def test_command_line_restore(self):
        add_mark(A.DB_PATH, 'Backup test 1')
        B.run_backup()
        fresh = tempfile.mkdtemp(prefix='backups_cli_')
        try:
            with mock.patch.dict(os.environ, {'DATA_DIR': fresh}):
                self.assertEqual(B._main(['restore', '--files']), 0)
                self.assertEqual(count_marks(os.path.join(fresh, 'po_requests.db')), 1)
                self.assertTrue(os.path.exists(os.path.join(fresh, 'invoice_uploads', 'inv1.pdf')))
                self.assertEqual(B._main(['restore']), 1)  # won't overwrite without --force
                self.assertEqual(B._main(['restore', '--force']), 0)
        finally:
            shutil.rmtree(fresh)
            B._cfg.update(db_path=A.DB_PATH, data_dir=TMP)

    # ------------------------------------------------------------ the page

    def test_page_access(self):
        B.run_backup()
        self.login(role='technician', username='tech')
        self.assertEqual(self.client.get('/backups').status_code, 302)
        self.assertEqual(self.client.post('/backups/run').status_code, 403)
        self.assertEqual(self.client.post('/backups/restore', data={'confirm': 'RESTORE'}).status_code, 403)
        self.login()
        r = self.client.get('/backups')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Working', r.data)
        self.assertIn(self.keys('db/')[0].encode(), r.data)
        with mock.patch.object(A, 'CASHFLOW_USERS', {'beatriz'}):
            self.assertEqual(self.client.get('/backups').status_code, 302)

    def test_page_says_when_not_set_up(self):
        self.login()
        with mock.patch.dict(os.environ, {'BACKUP_S3_BUCKET': ''}):
            r = self.client.get('/backups')
        self.assertIn(b'Backups are not set up', r.data)


if __name__ == '__main__':
    unittest.main()


class SafeCopyTests(unittest.TestCase):
    """The backup copy must never hold the database long enough to fail someone's save."""

    def test_saves_carry_on_while_a_backup_copies(self):
        import threading
        import time
        d = tempfile.mkdtemp(prefix='backup_lock_')
        try:
            db = os.path.join(d, 'live.db')
            conn = sqlite3.connect(db)
            conn.execute('CREATE TABLE t (id INTEGER PRIMARY KEY, v BLOB)')
            conn.executemany('INSERT INTO t (v) VALUES (?)', [(os.urandom(4000),) for _ in range(15000)])
            conn.commit()
            conn.close()
            failed, saved, done = [], [], threading.Event()

            def someone_saving():
                w = sqlite3.connect(db, timeout=5)  # the app's shortest wait for a lock
                while not done.is_set():
                    try:
                        w.execute('INSERT INTO t (v) VALUES (?)', (b'saved while backing up',))
                        w.commit()
                        saved.append(1)
                    except sqlite3.OperationalError as e:
                        failed.append(str(e))
                    time.sleep(0.005)
                w.close()

            t = threading.Thread(target=someone_saving)
            t.start()
            try:
                time.sleep(0.05)
                B._copy_db(db, os.path.join(d, 'copy.db'))
                time.sleep(0.05)
            finally:
                done.set()
                t.join()
            self.assertEqual(failed, [])
            self.assertTrue(saved)
            B.check_db_file(os.path.join(d, 'copy.db'))
        finally:
            shutil.rmtree(d, ignore_errors=True)


class PrefixTests(unittest.TestCase):
    """The Pumps service backs up to the same bucket under pumps/, apart from the Office App."""

    def setUp(self):
        import importlib
        self.importlib = importlib
        self.aws = mock_aws()
        self.aws.start()
        self.dir = tempfile.mkdtemp(prefix='backup_prefix_')
        self.db = os.path.join(self.dir, 'pumps.db')
        conn = sqlite3.connect(self.db)
        conn.execute('CREATE TABLE pump_cases (id INTEGER PRIMARY KEY, title TEXT)')
        conn.execute("INSERT INTO pump_cases (title) VALUES ('Pump #1')")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.aws.stop()
        shutil.rmtree(self.dir, ignore_errors=True)
        B._clients.clear()

    def _module(self, prefix):
        env = dict(STORAGE, BACKUP_PREFIX=prefix)
        with mock.patch.dict(os.environ, env):
            spec = self.importlib.util.spec_from_file_location(f'backups_{prefix or "office"}',
                                                              os.path.join(ROOT, 'backups.py'))
            mod = self.importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        return mod

    def test_pumps_copies_stay_in_their_own_folder(self):
        pumps_b = self._module('pumps')
        office_b = self._module('')
        with mock.patch.dict(os.environ, STORAGE):
            pumps_b._cfg.update(db_path=self.db, data_dir=self.dir)
            s3 = pumps_b._s3(pumps_b._dest())
            s3.create_bucket(Bucket='office-backups')
            s3.put_object(Bucket='office-backups', Key='db/20260101T000000Z.db.gz', Body=b'office copy')
            status = pumps_b.run_backup(force=True)
            self.assertIsNone(status['primary'].get('last_error'))
            keys = [o['Key'] for o in s3.list_objects_v2(Bucket='office-backups')['Contents']]
            self.assertTrue(any(k.startswith('pumps/db/') for k in keys), keys)
            self.assertIn('pumps/files-manifest.json', keys)
            self.assertIn('db/20260101T000000Z.db.gz', keys, 'the Office copy is untouched')
            self.assertEqual([s['key'] for s in office_b.list_snapshots()], ['db/20260101T000000Z.db.gz'])
            self.assertTrue(all(s['key'].startswith('pumps/db/') for s in pumps_b.list_snapshots()))
            # Pruning on the Pumps side never reaches the Office copies.
            pumps_b.prune_snapshots(pumps_b._dest(), now=datetime.now(timezone.utc) + timedelta(days=400))
            keys = [o['Key'] for o in s3.list_objects_v2(Bucket='office-backups')['Contents']]
            self.assertIn('db/20260101T000000Z.db.gz', keys)
