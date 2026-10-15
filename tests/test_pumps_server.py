"""
Pumps running on its own (pumps_server.py), without the Office App.

    python -m unittest tests.test_pumps_server -v

Run it in its own process: pumps.py keeps its settings at module level, so it
can't be started both inside the Office App (test_pumps) and on its own at once.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp(prefix='pumps_server_test_')
os.environ.update(SECRET_KEY='test-secret-key-0123456789abcdef-pumps', DATA_DIR=TMP, PUMPS_AUTO_SCAN='false',
                  OFFICE_APP_URL='https://office.example.com', SESSION_COOKIE_SECURE='false')
for k in ('ANTHROPIC_API_KEY', 'JOBBER_API_TOKEN', 'PO_EMAIL_ADDRESS', 'PO_EMAIL_PASSWORD',
          'MS_TENANT_ID', 'MS_CLIENT_ID', 'MS_CLIENT_SECRET'):
    os.environ.pop(k, None)

import pumps_server as S  # noqa: E402

S.app.config['TESTING'] = True


class PumpsServerTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        self.client = S.app.test_client()

    def login(self, role='office'):
        with self.client.session_transaction() as s:
            s['username'] = 'tester'
            s['role'] = role
            s['full_name'] = 'Test User'

    def test_does_not_load_the_office_app(self):
        self.assertNotIn('app', sys.modules)

    def test_own_database_has_pump_tables_only(self):
        conn = sqlite3.connect(os.path.join(TMP, 'pumps.db'))
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        self.assertIn('pump_cases', tables)
        self.assertIn('pump_email_scan_log', tables)
        self.assertNotIn('po_requests', tables)
        self.assertNotIn('users', tables)

    def test_health(self):
        r = self.client.get('/health')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {'ok': True})

    def test_signed_out_goes_to_office_app_login(self):
        r = self.client.get('/pumps')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers['Location'].endswith('/login'))
        r = self.client.get('/login')
        self.assertEqual(r.headers['Location'], 'https://office.example.com/login')

    def test_page_and_api_work_when_signed_in(self):
        self.login()
        r = self.client.get('/pumps')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'csrf-token', r.data)
        self.assertIn('csrf_token', r.headers.get('Set-Cookie', ''))
        r = self.client.get('/')
        self.assertEqual(r.headers['Location'], 'https://office.example.com/dashboard')

    def test_mailbox_not_configured_scans_nothing(self):
        self.assertFalse(S.shared_mail.MONITORING_ENABLED)
        out = S.shared_mail.fetch_scan_emails(S.DB_PATH, log_table='pump_email_scan_log')
        self.assertEqual(out['emails'], [])
        with self.assertRaises(ValueError):
            S.shared_mail.fetch_scan_emails(S.DB_PATH, log_table='users')


if __name__ == '__main__':
    unittest.main(verbosity=2)
