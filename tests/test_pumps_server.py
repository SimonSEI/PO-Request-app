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
                  OFFICE_APP_URL='https://office.example.com', SESSION_COOKIE_SECURE='false',
                  PUMPS_SHARED_SECRET='shared-secret-for-tests')
for k in ('ANTHROPIC_API_KEY', 'JOBBER_API_TOKEN', 'PO_EMAIL_ADDRESS', 'PO_EMAIL_PASSWORD',
          'MS_TENANT_ID', 'MS_CLIENT_ID', 'MS_CLIENT_SECRET'):
    os.environ.pop(k, None)

import pumps_link as L  # noqa: E402
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

    def test_signed_out_goes_to_office_app(self):
        r = self.client.get('/pumps')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers['Location'].endswith('/login'))
        # The Office App's /pumps re-checks who they are and sends them back with a ticket.
        r = self.client.get('/login')
        self.assertEqual(r.headers['Location'], 'https://office.example.com/pumps')

    def test_office_ticket_signs_in(self):
        t = L.make_ticket('shared-secret-for-tests', 'office1', 'office', 'Office Tester')
        r = self.client.get('/pumps/sso', query_string={'t': t, 'next': '/pumps'})
        self.assertEqual(r.headers['Location'], '/pumps')
        with self.client.session_transaction() as s:
            self.assertEqual((s['username'], s['role'], s['full_name']), ('office1', 'office', 'Office Tester'))
        self.assertEqual(self.client.get('/pumps').status_code, 200)

    def test_bad_tickets_are_refused(self):
        good = L.make_ticket('shared-secret-for-tests', 'office1', 'office')
        for t in ('', 'nonsense', good[:-1] + ('0' if good[-1] != '0' else '1'),
                  L.make_ticket('another-secret', 'office1', 'office'),
                  L.make_ticket('shared-secret-for-tests', 'office1', 'office', ttl_seconds=-5)):
            r = self.client.get('/pumps/sso', query_string={'t': t})
            self.assertEqual(r.headers['Location'], 'https://office.example.com/login', t)
            with self.client.session_transaction() as s:
                self.assertNotIn('username', s)

    def test_ticket_only_leads_to_pumps_pages(self):
        t = L.make_ticket('shared-secret-for-tests', 'office1', 'office')
        for nxt in ('https://evil.example.com/', '//evil.example.com/pumps', '/pumps//evil', '/dashboard'):
            r = self.client.get('/pumps/sso', query_string={'t': t, 'next': nxt})
            self.assertEqual(r.headers['Location'], '/pumps', nxt)

    def test_technicians_still_cannot_open_pumps(self):
        t = L.make_ticket('shared-secret-for-tests', 'tech1', 'technician')
        self.client.get('/pumps/sso', query_string={'t': t})
        self.assertEqual(self.client.get('/pumps').status_code, 302)

    def test_jobber_token_only_on_private_network_with_secret(self):
        internal = 'http://pumps.railway.internal:8080'
        r = self.client.post('/internal/jobber-token', json={}, headers={'X-Pumps-Secret': 'shared-secret-for-tests'})
        self.assertEqual(r.status_code, 404)  # public address
        r = self.client.post('/internal/jobber-token', json={}, base_url=internal,
                             headers={'X-Pumps-Secret': 'wrong'})
        self.assertEqual(r.status_code, 401)
        r = self.client.post('/internal/jobber-token', json={}, base_url=internal,
                             headers={'X-Pumps-Secret': 'shared-secret-for-tests'})
        self.assertEqual(r.get_json(), {'connected': False})
        old = S.pumps.JOBBER_STATIC_TOKEN
        S.pumps.JOBBER_STATIC_TOKEN = 'static-jobber-token'
        try:
            r = self.client.post('/internal/jobber-token', json={}, base_url=internal,
                                 headers={'X-Pumps-Secret': 'shared-secret-for-tests'})
            self.assertEqual(r.get_json(), {'connected': True, 'token': 'static-jobber-token'})
            r = self.client.post('/internal/jobber-token', json={'status_only': True}, base_url=internal,
                                 headers={'X-Pumps-Secret': 'shared-secret-for-tests'})
            self.assertEqual(r.get_json(), {'connected': True})
        finally:
            S.pumps.JOBBER_STATIC_TOKEN = old

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
