"""
The Office App with Pumps running as its own service (PUMPS_URL set).

    python -m unittest tests.test_office_pumps_split -v

Run it in its own process: it starts app.py with different settings from
test_pumps / test_receivables.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import zipfile
import io
import json
from unittest import mock
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp(prefix='office_split_test_')
os.environ.update(SECRET_KEY='test-secret-key-0123456789abcdef-split', DATA_DIR=TMP, PUMPS_AUTO_SCAN='false',
                  SESSION_COOKIE_SECURE='false', PUMPS_URL='https://pumps.example.com/',
                  PUMPS_INTERNAL_URL='http://pumps.railway.internal:8080', PUMPS_SHARED_SECRET='shared-secret-for-tests')
os.environ.pop('ANTHROPIC_API_KEY', None)
os.environ.pop('JOBBER_API_TOKEN', None)

import app as A  # noqa: E402
import pumps_link as L  # noqa: E402
import receivables as R  # noqa: E402

A.app.config['TESTING'] = True


class OfficePumpsSplitTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        self.c = A.app.test_client()

    def login(self, role='office', username='office1'):
        with self.c.session_transaction() as s:
            s['username'], s['role'], s['full_name'] = username, role, 'Office Tester'

    def test_pumps_does_not_run_here(self):
        conn = sqlite3.connect(A.DB_PATH)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        self.assertNotIn('pump_docs', tables)
        rules = {r.rule for r in A.app.url_map.iter_rules()}
        self.assertNotIn('/pumps/api/cases', rules)
        self.assertNotIn('/api/openclaw/pumps', rules)

    def test_pumps_tile_sends_people_to_the_pumps_service_signed_in(self):
        self.login()
        r = self.c.get('/pumps')
        self.assertEqual(r.status_code, 302)
        loc = urlparse(r.headers['Location'])
        self.assertEqual((loc.scheme, loc.netloc, loc.path), ('https', 'pumps.example.com', '/pumps/sso'))
        q = parse_qs(loc.query)
        self.assertEqual(q['next'], ['/pumps'])
        self.assertEqual(L.read_ticket('shared-secret-for-tests', q['t'][0]),
                         {'username': 'office1', 'role': 'office', 'full_name': 'Office Tester'})

    def test_deep_links_keep_their_page(self):
        self.login()
        r = self.c.get('/pumps/jobber/connect')
        self.assertEqual(parse_qs(urlparse(r.headers['Location']).query)['next'], ['/pumps/jobber/connect'])

    def test_no_ticket_for_people_without_pumps(self):
        r = self.c.get('/pumps')
        self.assertTrue(r.headers['Location'].endswith('/login'))
        self.login(role='technician', username='tech1')
        r = self.c.get('/pumps')
        self.assertNotIn('pumps.example.com', r.headers['Location'])

    def test_dashboard_link_to_pumps_still_builds(self):
        with A.app.test_request_context():
            self.assertEqual(A.url_for('pumps.page'), '/pumps')

    def test_receivables_gets_jobber_from_the_pumps_service(self):
        calls = []

        class Resp:
            def __init__(self, status, body):
                self.status_code, self._body = status, body

            def json(self):
                return self._body

        def fake_post(url, json=None, headers=None, timeout=None):
            calls.append((url, json, headers))
            if json.get('status_only'):
                return Resp(200, {'connected': True})
            return Resp(200, {'connected': True, 'token': 'tok-from-pumps'})

        with mock.patch.object(L.http_requests, 'post', fake_post):
            self.assertTrue(R.jobber_ready())
            self.assertEqual(R._cfg['jobber_token'](True), 'tok-from-pumps')
        self.assertEqual(calls[0][0], 'http://pumps.railway.internal:8080/internal/jobber-token')
        self.assertEqual(calls[0][2], {'X-Pumps-Secret': 'shared-secret-for-tests'})
        self.assertEqual(calls[1][1], {'force': True, 'status_only': False})

    def test_receivables_says_not_connected_when_pumps_is_unreachable(self):
        def down(*a, **kw):
            raise ConnectionError('down')
        with mock.patch.object(L.http_requests, 'post', down):
            self.assertFalse(R.jobber_ready())
            with self.assertRaises(ConnectionError):
                R._cfg['jobber_token'](False)

    def test_export_for_the_pumps_service(self):
        internal = 'http://web.railway.internal:8080'
        hdr = {'X-Pumps-Secret': 'shared-secret-for-tests'}
        conn = sqlite3.connect(A.DB_PATH)
        conn.execute('CREATE TABLE IF NOT EXISTS pump_cases (id INTEGER PRIMARY KEY, title TEXT)')
        conn.execute("INSERT INTO pump_cases (title) VALUES ('Pump #1')")
        conn.commit()
        conn.close()
        self.assertEqual(self.c.get('/internal/pumps-export', headers=hdr).status_code, 404)  # public address
        self.assertEqual(self.c.get('/internal/pumps-export', base_url=internal,
                                    headers={'X-Pumps-Secret': 'x'}).status_code, 401)
        r = self.c.get('/internal/pumps-export', base_url=internal, headers=hdr)
        self.assertEqual(r.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(r.data)) as z:
            manifest = json.loads(z.read('manifest.json'))
        self.assertEqual(manifest['tables']['pump_cases'], 1)
        self.assertNotIn('users', manifest['tables'])
        r.close()
        # The Office App keeps its copy.
        conn = sqlite3.connect(A.DB_PATH)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM pump_cases').fetchone()[0], 1)
        conn.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
