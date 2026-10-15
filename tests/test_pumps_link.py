"""
The sign-in ticket and the one-off data move between the Office App and the
Pumps service (pumps_link.py).

    python -m unittest tests.test_pumps_link -v
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pumps_link as L  # noqa: E402


def office_data(folder):
    """An Office App volume: Office tables, Pumps tables, Pumps files."""
    db = os.path.join(folder, 'po_requests.db')
    conn = sqlite3.connect(db)
    conn.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password TEXT)')
    conn.execute("INSERT INTO users (username, password) VALUES ('office1', 'hash')")
    conn.execute('CREATE TABLE po_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, job_name TEXT)')
    conn.execute("INSERT INTO po_requests (job_name) VALUES ('Lakes HOA')")
    conn.execute('CREATE TABLE pump_cases (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT)')
    conn.executemany('INSERT INTO pump_cases (title) VALUES (?)', [('Pump #1',), ('Pump #2',), ('Diver',)])
    conn.execute('CREATE INDEX ix_cases_title ON pump_cases (title)')
    conn.execute('CREATE TABLE pump_state (key TEXT PRIMARY KEY, value TEXT)')
    conn.execute("INSERT INTO pump_state VALUES ('jobber_tokens', '{}')")
    conn.commit()
    conn.close()
    os.makedirs(os.path.join(folder, 'pump_files', '2026', '10'))
    with open(os.path.join(folder, 'pump_files', '2026', '10', 'report.pdf'), 'wb') as f:
        f.write(b'%PDF-1.4 report' * 100)
    with open(os.path.join(folder, 'pump_files', 'quote.docx'), 'wb') as f:
        f.write(b'docx bytes')
    return db


class FakeResponse:
    def __init__(self, path, status=200):
        self.path, self.status_code, self.text = path, status, 'nope'

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_content(self, size):
        with open(self.path, 'rb') as f:
            while True:
                chunk = f.read(size)
                if not chunk:
                    return
                yield chunk


class TicketTest(unittest.TestCase):
    def test_round_trip(self):
        t = L.make_ticket('s3cret', 'office1', 'office', 'Jo Smith|Jr')
        self.assertEqual(L.read_ticket('s3cret', t), {'username': 'office1', 'role': 'office', 'full_name': 'Jo Smith|Jr'})

    def test_refused(self):
        t = L.make_ticket('s3cret', 'office1', 'office')
        self.assertIsNone(L.read_ticket('other', t))
        self.assertIsNone(L.read_ticket('', t))
        self.assertIsNone(L.read_ticket('s3cret', 'x' + t))
        self.assertIsNone(L.read_ticket('s3cret', L.make_ticket('s3cret', 'office1', 'office', ttl_seconds=-1)))

    def test_secret_ok(self):
        self.assertTrue(L.secret_ok('abc', 'abc'))
        self.assertFalse(L.secret_ok('abc', 'abd'))
        self.assertFalse(L.secret_ok('', ''))


class MoveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='pumps_link_test_')
        self.office = os.path.join(self.tmp, 'office')
        self.pumps = os.path.join(self.tmp, 'pumps')
        os.makedirs(self.office)
        self.office_db = office_data(self.office)
        self.zip = os.path.join(self.tmp, 'bundle.zip')
        self.pumps_db = os.path.join(self.pumps, 'pumps.db')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_import(self, zip_path=None, status=200):
        with mock.patch.object(L.http_requests, 'get', lambda *a, **kw: FakeResponse(zip_path or self.zip, status)):
            return L.import_bundle('http://web.railway.internal:8080/internal/pumps-export', 's', self.pumps_db,
                                   self.pumps)

    def test_export_holds_pumps_data_only(self):
        manifest = L.export_bundle(self.office_db, self.office, self.zip)
        self.assertEqual(manifest['tables'], {'pump_cases': 3, 'pump_state': 1})
        self.assertEqual(set(manifest['files']), {'2026/10/report.pdf', 'quote.docx'})
        with zipfile.ZipFile(self.zip) as z:
            z.extract('pumps.db', self.tmp)
        conn = sqlite3.connect(os.path.join(self.tmp, 'pumps.db'))
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        self.assertNotIn('users', tables)
        self.assertNotIn('po_requests', tables)

    def test_export_leaves_the_office_copy_alone(self):
        L.export_bundle(self.office_db, self.office, self.zip)
        conn = sqlite3.connect(self.office_db)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM pump_cases').fetchone()[0], 3)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM users').fetchone()[0], 1)
        conn.close()
        self.assertTrue(os.path.isfile(os.path.join(self.office, 'pump_files', 'quote.docx')))

    def test_import_puts_everything_in_place_once(self):
        L.export_bundle(self.office_db, self.office, self.zip)
        manifest = self.run_import()
        self.assertEqual(manifest['tables'], {'pump_cases': 3, 'pump_state': 1})
        conn = sqlite3.connect(self.pumps_db)
        self.assertEqual([r[0] for r in conn.execute('SELECT title FROM pump_cases ORDER BY id')],
                         ['Pump #1', 'Pump #2', 'Diver'])
        conn.close()
        with open(os.path.join(self.pumps, 'pump_files', '2026', '10', 'report.pdf'), 'rb') as f:
            self.assertEqual(f.read(), b'%PDF-1.4 report' * 100)
        self.assertFalse(os.path.exists(os.path.join(self.pumps, '.pumps_import')))
        # A restart doesn't import again (or touch what's there).
        self.assertIsNone(self.run_import(zip_path='/does/not/exist'))

    def test_anything_already_there_is_kept_aside(self):
        os.makedirs(os.path.join(self.pumps, 'pump_files'))
        conn = sqlite3.connect(self.pumps_db)
        conn.execute('CREATE TABLE pump_cases (id INTEGER PRIMARY KEY, title TEXT)')
        conn.execute("INSERT INTO pump_cases (title) VALUES ('made before the import')")
        conn.commit()
        conn.close()
        L.export_bundle(self.office_db, self.office, self.zip)
        self.run_import()
        aside = [n for n in os.listdir(self.pumps) if '.before-import-' in n]
        self.assertEqual(len(aside), 2, aside)
        old = sqlite3.connect(os.path.join(self.pumps, [n for n in aside if n.startswith('pumps.db')][0]))
        self.assertEqual(old.execute('SELECT title FROM pump_cases').fetchone()[0], 'made before the import')
        old.close()

    def test_a_bad_bundle_puts_nothing_in_place(self):
        L.export_bundle(self.office_db, self.office, self.zip)
        bad = os.path.join(self.tmp, 'bad.zip')
        with zipfile.ZipFile(self.zip) as src, zipfile.ZipFile(bad, 'w') as dst:
            for item in src.infolist():
                data = src.read(item)
                if item.filename == 'manifest.json':
                    m = json.loads(data)
                    m['tables']['pump_cases'] = 4
                    data = json.dumps(m).encode()
                dst.writestr(item, data)
        with self.assertRaises(RuntimeError):
            self.run_import(zip_path=bad)
        self.assertFalse(os.path.exists(self.pumps_db))
        self.assertFalse(os.path.exists(os.path.join(self.pumps, '.pumps_imported')))

    def test_office_refusal_stops_the_start(self):
        L.export_bundle(self.office_db, self.office, self.zip)
        with self.assertRaises(RuntimeError):
            self.run_import(status=409)
        self.assertFalse(os.path.exists(self.pumps_db))


if __name__ == '__main__':
    unittest.main(verbosity=2)
