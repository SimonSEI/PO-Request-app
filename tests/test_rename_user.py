"""
Office admins changing a technician's or office admin's username.

    python -m unittest tests.test_rename_user -v
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp(prefix='rename_user_test_')
os.environ.update(SECRET_KEY='test-secret-key-0123456789abcdef-rename', DATA_DIR=TMP, PUMPS_AUTO_SCAN='false',
                  SESSION_COOKIE_SECURE='false', PUMPS_USERS='oldtech,simon')
os.environ.pop('ANTHROPIC_API_KEY', None)
os.environ.pop('JOBBER_API_TOKEN', None)

import app as A  # noqa: E402

A.app.config['TESTING'] = True
A.app.config['WTF_CSRF_ENABLED'] = False


class RenameUserTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        self.c = A.app.test_client()
        conn = sqlite3.connect(A.DB_PATH)
        conn.execute("DELETE FROM users")
        conn.execute("DELETE FROM po_requests")
        rows = [(1, 'oldtech', 'technician', 'Old Tech'), (2, 'office1', 'office', 'Office One'),
                (3, 'taken', 'technician', 'Taken'), (4, 'pm1', 'property_manager', 'PM One')]
        conn.executemany("INSERT INTO users (id, username, password, role, full_name) VALUES (?, ?, 'x', ?, ?)", rows)
        conn.execute("INSERT INTO po_requests (tech_username, tech_name, job_name) VALUES ('oldtech', 'Old Tech', 'Service')")
        conn.commit()
        conn.close()

    def login(self, role='office', username='office1'):
        with self.c.session_transaction() as s:
            s['username'], s['role'], s['full_name'] = username, role, 'Office One'

    def rename(self, user_id, username):
        return self.c.post('/office_admin/rename_user', json={'user_id': user_id, 'username': username})

    def query(self, sql, *args):
        conn = sqlite3.connect(A.DB_PATH)
        try:
            return conn.execute(sql, args).fetchall()
        finally:
            conn.close()

    def test_rename_moves_the_techs_pos_and_flags_access_lists(self):
        self.login()
        j = self.rename(1, 'newtech').get_json()
        self.assertTrue(j['success'], j)
        self.assertIn('Pumps', j['message'])
        self.assertEqual(self.query("SELECT username FROM users WHERE id=1"), [('newtech',)])
        self.assertEqual(self.query("SELECT tech_username FROM po_requests"), [('newtech',)])

    def test_only_office_admins_can_rename(self):
        self.login(role='technician', username='oldtech')
        self.assertEqual(self.rename(1, 'newtech').status_code, 401)
        self.assertEqual(self.query("SELECT username FROM users WHERE id=1"), [('oldtech',)])

    def test_taken_names_any_case_and_bad_names_are_refused(self):
        self.login()
        self.assertFalse(self.rename(1, 'TAKEN').get_json()['success'])
        self.assertFalse(self.rename(1, 'has space').get_json()['success'])
        self.assertFalse(self.rename(1, '').get_json()['success'])
        self.assertEqual(self.query("SELECT username FROM users WHERE id=1"), [('oldtech',)])

    def test_property_managers_are_not_renamed_here(self):
        self.login()
        self.assertFalse(self.rename(4, 'pm2').get_json()['success'])

    def test_renaming_yourself_keeps_you_signed_in(self):
        self.login()
        self.assertTrue(self.rename(2, 'office2').get_json()['success'])
        with self.c.session_transaction() as s:
            self.assertEqual(s['username'], 'office2')


if __name__ == '__main__':
    unittest.main()
