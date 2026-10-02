"""
Tests for the FileMaker host (filemaker.py): hosted files, accounts and
privilege sets, record locking, the change feed, schema saves, serial
numbers and record-level access calculations.

    python -m unittest tests.test_filemaker -v

Runs against a throwaway database. The browser-side engine (calculations,
scripts, layouts) is tested with node: tests/filemaker_calc_test.js.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix='filemaker_test_')
os.environ.setdefault('SECRET_KEY', 'test-secret-key-0123456789abcdef-filemaker')
os.environ.setdefault('DATA_DIR', TMP)
os.environ.setdefault('PUMPS_AUTO_SCAN', 'false')
os.environ.pop('ANTHROPIC_API_KEY', None)

import app as A  # noqa: E402
import filemaker as FMH  # noqa: E402

A.app.config['TESTING'] = True


def schema_with(tables, **extra):
    s = FMH.blank_schema()
    s['tables'] = tables
    s['tableOccurrences'] = [{'id': 'O_' + t['id'], 'name': t['name'], 'table': t['id']} for t in tables]
    s.update(extra)
    return s


CONTACTS = {'id': 'T1', 'name': 'Contacts', 'fields': [
    {'id': 'F1', 'name': 'ID', 'type': 'number', 'options': {'autoEnter': {'serial': {'on': True, 'next': '100', 'increment': 1}}}},
    {'id': 'F2', 'name': 'Name', 'type': 'text'},
    {'id': 'F3', 'name': 'Owner', 'type': 'text'},
    {'id': 'F4', 'name': 'Salary', 'type': 'number'},
    {'id': 'F5', 'name': 'Full', 'type': 'calculation', 'options': {'calc': {'formula': 'Name', 'resultType': 'text'}}},
]}


class FileMakerHostTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    def client(self, user='office1', role='office', name='Office Tester'):
        c = A.app.test_client()
        A.app.config['WTF_CSRF_ENABLED'] = False
        with c.session_transaction() as s:
            s['username'], s['role'], s['full_name'] = user, role, name
        return c

    def setUp(self):
        self.c = self.client()

    def make_file(self, name='Test', password='', records=None, schema=None):
        r = self.c.post('/filemaker/api/files', json={'name': name, 'schema': schema or schema_with([json.loads(json.dumps(CONTACTS))]),
                                                      'adminPassword': password, 'records': records or {}})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return r.get_json()['id']

    def open(self, fid, c=None, **body):
        c = c or self.c
        r = c.post(f'/filemaker/api/files/{fid}/open', json=body or {'auto': True})
        return r

    def call(self, method, path, token, body=None, c=None):
        c = c or self.c
        return c.open(path, method=method, json=body, headers={'X-FM-Session': token})

    # ── access ──────────────────────────────────────────────────────────────
    def test_only_office_logins(self):
        tech = self.client('tech1', 'technician')
        self.assertEqual(tech.get('/filemaker/api/files').status_code, 401)
        self.assertEqual(tech.get('/filemaker').status_code, 302)
        pm = self.client('pm1', 'property_manager')
        self.assertEqual(pm.get('/filemaker/api/files').status_code, 401)
        page = self.c.get('/filemaker')
        self.assertEqual(page.status_code, 200)
        self.assertIn("frame-src 'self' https: data: blob:", page.headers['Content-Security-Policy'])
        self.assertIn('Not affiliated', open(os.path.join(ROOT, 'filemaker_assets', 'fm-dialogs.js')).read())

    def test_dashboard_tile_in_coming_soon(self):
        html = self.c.get('/dashboard').get_data(as_text=True)
        folder = html.split('Features Coming Soon', 1)[1]
        self.assertIn('href="/filemaker"', folder)
        tech = self.client('tech1', 'technician').get('/dashboard').get_data(as_text=True)
        self.assertNotIn('/filemaker"', tech)

    def test_other_pages_keep_default_policy(self):
        r = self.c.get('/dashboard')
        self.assertIn("connect-src 'self'", r.headers['Content-Security-Policy'])
        self.assertNotIn('frame-src', r.headers['Content-Security-Policy'])

    # ── files and accounts ─────────────────────────────────────────────────
    def test_create_open_and_auto_login(self):
        fid = self.make_file('Auto')
        r = self.open(fid)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        d = r.get_json()
        self.assertEqual(d['account']['name'], 'Admin')
        self.assertEqual(d['account']['privilegeSet'], 'PS_FULL')
        self.assertEqual([p['id'] for p in d['schema']['privilegeSets'][:3]], ['PS_FULL', 'PS_ENTRY', 'PS_READ'])

    def test_password_required(self):
        fid = self.make_file('Locked', password='s3cret')
        self.assertTrue(self.open(fid).get_json().get('needLogin'))
        self.assertEqual(self.open(fid, account='Admin', password='nope').status_code, 401)
        self.assertEqual(self.open(fid, account='admin', password='s3cret').status_code, 200)

    def test_failed_logins_are_limited(self):
        fid = self.make_file('Brute', password='right')
        c = self.client('bruteuser')
        for _ in range(FMH.FAILED_LOGIN_LIMIT):
            self.assertEqual(self.open(fid, c, account='Admin', password='wrong').status_code, 401)
        r = self.open(fid, c, account='Admin', password='right')
        self.assertEqual(r.status_code, 401)
        self.assertIn('Too many', r.get_json()['error'])
        FMH._failed_logins.clear()

    def test_session_token_tied_to_app_login(self):
        fid = self.make_file('Mine')
        tok = self.open(fid).get_json()['token']
        other = self.client('office2')
        self.assertEqual(self.call('GET', f'/filemaker/api/files/{fid}/changes', tok, c=other).status_code, 401)

    def test_unique_names_and_copy(self):
        a = self.make_file('Same')
        b = self.make_file('Same')
        names = {f['id']: f['name'] for f in self.c.get('/filemaker/api/files').get_json()['files']}
        self.assertEqual(names[a], 'Same')
        self.assertEqual(names[b], 'Same 2')
        tok = self.open(a).get_json()['token']
        self.call('POST', f'/filemaker/api/files/{a}/records', tok, {'ops': [{'op': 'create', 'table': 'T1', 'data': {'F2': 'x'}}]})
        r = self.call('POST', f'/filemaker/api/files/{a}/copy', tok, {'name': 'Clone', 'mode': 'clone'})
        clone = r.get_json()['id']
        self.assertEqual(self.open(clone).get_json()['records']['T1'], [])

    def test_delete_needs_full_access_password_and_name(self):
        fid = self.make_file('Doomed', password='pw')
        self.assertEqual(self.c.post(f'/filemaker/api/files/{fid}/delete', json={'account': 'Admin', 'password': 'pw', 'confirm': 'nope'}).status_code, 400)
        self.assertEqual(self.c.post(f'/filemaker/api/files/{fid}/delete', json={'account': 'Admin', 'password': 'x', 'confirm': 'Doomed'}).status_code, 401)
        FMH._failed_logins.clear()
        self.assertEqual(self.c.post(f'/filemaker/api/files/{fid}/delete', json={'account': 'Admin', 'password': 'pw', 'confirm': 'Doomed'}).status_code, 200)
        self.assertFalse(any(f['id'] == fid for f in self.c.get('/filemaker/api/files').get_json()['files']))

    # ── records ─────────────────────────────────────────────────────────────
    def test_serials_pending_records_and_commit(self):
        fid = self.make_file('Serial')
        tok = self.open(fid).get_json()['token']
        r = self.call('POST', f'/filemaker/api/files/{fid}/records', tok, {'ops': [{'op': 'create', 'table': 'T1', 'data': {}, 'pending': True}]})
        rec = r.get_json()['results'][0]['record']
        self.assertEqual(rec['d']['F1'], '100')
        self.assertTrue(rec['pending'])
        # nobody else sees an uncommitted record
        other = self.client('office2')
        tok2 = self.open(fid, other).get_json()['token']
        self.assertEqual(self.open(fid, other).get_json()['records']['T1'], [])
        self.call('POST', f'/filemaker/api/files/{fid}/records', tok, {'ops': [{'op': 'update', 'id': rec['id'], 'data': {'F2': 'Ada'}}]})
        ch = self.call('GET', f'/filemaker/api/files/{fid}/changes?since=0', tok2, c=other).get_json()
        self.assertEqual([x['d']['F2'] for x in ch['records']], ['Ada'])
        # calculations are never stored by the host
        self.call('POST', f'/filemaker/api/files/{fid}/records', tok, {'ops': [{'op': 'create', 'table': 'T1', 'data': {'F2': 'B', 'F5': 'hack'}}]})
        recs = self.open(fid).get_json()['records']['T1']
        self.assertTrue(all('F5' not in r['d'] for r in recs))
        self.assertEqual(sorted(r['d']['F1'] for r in recs), ['100', '101'])

    def test_record_locking_and_stale_writes(self):
        fid = self.make_file('Locks')
        tok = self.open(fid).get_json()['token']
        rid = self.call('POST', f'/filemaker/api/files/{fid}/records', tok, {'ops': [{'op': 'create', 'table': 'T1', 'data': {'F2': 'a'}}]}).get_json()['results'][0]['id']
        other = self.client('office2', name='Other Person')
        tok2 = self.open(fid, other).get_json()['token']
        self.assertTrue(self.call('POST', f'/filemaker/api/files/{fid}/lock', tok, {'key': f'rec:{rid}'}).get_json()['success'])
        r = self.call('POST', f'/filemaker/api/files/{fid}/lock', tok2, {'key': f'rec:{rid}'}, c=other).get_json()
        self.assertFalse(r['success'])
        self.assertIn('Admin', r['holder'])
        r = self.call('POST', f'/filemaker/api/files/{fid}/records', tok2, {'ops': [{'op': 'update', 'id': rid, 'data': {'F2': 'b'}}]}, c=other)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()['fmError'], 301)
        r = self.call('POST', f'/filemaker/api/files/{fid}/records', tok2, {'ops': [{'op': 'delete', 'id': rid}]}, c=other)
        self.assertEqual(r.status_code, 409)
        # commit releases the lock; an out-of-date modification count is refused
        self.call('POST', f'/filemaker/api/files/{fid}/records', tok, {'ops': [{'op': 'update', 'id': rid, 'data': {'F2': 'c'}, 'mc': 0}]})
        r = self.call('POST', f'/filemaker/api/files/{fid}/records', tok2, {'ops': [{'op': 'update', 'id': rid, 'data': {'F2': 'd'}, 'mc': 0}]}, c=other)
        self.assertEqual(r.get_json()['fmError'], 306)
        self.assertEqual(self.call('POST', f'/filemaker/api/files/{fid}/records', tok2, {'ops': [{'op': 'update', 'id': rid, 'data': {'F2': 'd'}, 'mc': 1}]}, c=other).status_code, 200)

    def test_batch_is_all_or_nothing(self):
        fid = self.make_file('Atomic')
        tok = self.open(fid).get_json()['token']
        r = self.call('POST', f'/filemaker/api/files/{fid}/records', tok, {'ops': [{'op': 'create', 'table': 'T1', 'data': {'F2': 'ok'}}, {'op': 'update', 'id': 999999, 'data': {}}]})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()['index'], 1)
        self.assertEqual(self.open(fid).get_json()['records']['T1'], [])

    def test_disconnect_and_messages(self):
        fid = self.make_file('Hosted')
        tok = self.open(fid).get_json()['token']
        other = self.client('office2')
        tok2 = self.open(fid, other).get_json()['token']
        users = self.call('GET', f'/filemaker/api/files/{fid}/users', tok).get_json()
        them = [u for u in users['users'] if u['id'] != users['me']][0]
        self.call('POST', f'/filemaker/api/files/{fid}/users/{them["id"]}/message', tok, {'text': 'Please close the file'})
        msgs = self.call('GET', f'/filemaker/api/files/{fid}/changes?since=0', tok2, c=other).get_json()['messages']
        self.assertEqual(msgs[0]['text'], 'Please close the file')
        self.call('POST', f'/filemaker/api/files/{fid}/users/{them["id"]}/disconnect', tok, {'text': 'Maintenance'})
        r = self.call('GET', f'/filemaker/api/files/{fid}/changes?since=0', tok2, c=other)
        self.assertEqual(r.status_code, 401)
        self.assertTrue(r.get_json()['kicked'])
        self.assertEqual(r.get_json()['error'], 'Maintenance')

    # ── privileges ─────────────────────────────────────────────────────────
    def add_account(self, fid, tok, name, pw, pset):
        r = self.call('POST', f'/filemaker/api/files/{fid}/accounts', tok, {'ops': [{'op': 'add', 'name': name, 'password': pw, 'privilegeSet': pset}]})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

    def test_read_only_and_schema_rights(self):
        fid = self.make_file('Rights')
        tok = self.open(fid).get_json()['token']
        self.add_account(fid, tok, 'viewer', 'v', 'PS_READ')
        other = self.client('office2')
        vt = self.open(fid, other, account='viewer', password='v').get_json()['token']
        r = self.call('POST', f'/filemaker/api/files/{fid}/records', vt, {'ops': [{'op': 'create', 'table': 'T1', 'data': {}}]}, c=other)
        self.assertEqual(r.status_code, 403)
        schema = self.call('GET', f'/filemaker/api/files/{fid}/schema', vt, c=other).get_json()['schema']
        r = self.call('POST', f'/filemaker/api/files/{fid}/schema', vt, {'ops': [{'op': 'section', 'name': 'database', 'value': {k: schema[k] for k in ('tables', 'tableOccurrences', 'relationships')}}]}, c=other)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.call('GET', f'/filemaker/api/files/{fid}/accounts', vt, c=other).status_code, 403)

    def test_last_full_access_account_is_kept(self):
        fid = self.make_file('Keep')
        tok = self.open(fid).get_json()['token']
        accts = self.call('GET', f'/filemaker/api/files/{fid}/accounts', tok).get_json()['accounts']
        r = self.call('POST', f'/filemaker/api/files/{fid}/accounts', tok, {'ops': [{'op': 'update', 'id': accts[0]['id'], 'privilegeSet': 'PS_ENTRY'}]})
        self.assertEqual(r.status_code, 400)
        r = self.call('POST', f'/filemaker/api/files/{fid}/accounts', tok, {'ops': [{'op': 'delete', 'id': accts[0]['id']}]})
        self.assertEqual(r.status_code, 400)

    def test_record_level_and_field_privileges(self):
        fid = self.make_file('RLA')
        tok = self.open(fid).get_json()['token']
        schema = self.call('GET', f'/filemaker/api/files/{fid}/schema', tok).get_json()['schema']
        own = {'id': 'P_own', 'name': 'Own Records', 'records': {'mode': 'custom', 'tables': {'T1': {
            'view': 'limited', 'viewCalc': 'Owner = Get ( AccountName ) or IsEmpty ( Owner )', 'edit': 'limited',
            'editCalc': 'Owner = Get ( AccountName )', 'create': 'yes', 'delete': 'no',
            'fields': {'F4': 'none', 'F2': 'view'}}}},
            'layouts': {'mode': 'all_view'}, 'valueLists': {'mode': 'all_view'}, 'scripts': {'mode': 'all_exec'}, 'extended': ['fmapp']}
        r = self.call('POST', f'/filemaker/api/files/{fid}/schema', tok, {'ops': [{'op': 'section', 'name': 'privilegeSets', 'value': schema['privilegeSets'] + [own]}]})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.add_account(fid, tok, 'sam', 'pw', 'P_own')
        self.call('POST', f'/filemaker/api/files/{fid}/records', tok, {'ops': [
            {'op': 'create', 'table': 'T1', 'data': {'F2': 'mine', 'F3': 'sam', 'F4': '100'}},
            {'op': 'create', 'table': 'T1', 'data': {'F2': 'theirs', 'F3': 'pat', 'F4': '200'}},
            {'op': 'create', 'table': 'T1', 'data': {'F2': 'unowned', 'F4': '300'}}]})
        other = self.client('office2')
        st = self.open(fid, other, account='sam', password='pw').get_json()
        recs = {r['d'].get('F2', '?') if not r.get('noaccess') else 'NOACCESS': r for r in st['records']['T1']}
        self.assertIn('NOACCESS', recs)
        self.assertNotIn('F4', recs['mine']['d'], 'salary is hidden')
        self.assertTrue(recs['mine']['canEdit'])
        self.assertFalse(recs['unowned']['canEdit'])
        tok2 = st['token']
        # may not touch the view-only Name field, may not edit someone else's record
        r = self.call('POST', f'/filemaker/api/files/{fid}/records', tok2, {'ops': [{'op': 'update', 'id': recs['mine']['id'], 'data': {'F2': 'x'}}]}, c=other)
        self.assertEqual(r.status_code, 403)
        r = self.call('POST', f'/filemaker/api/files/{fid}/records', tok2, {'ops': [{'op': 'update', 'id': recs['unowned']['id'], 'data': {'F3': 'sam'}}]}, c=other)
        self.assertEqual(r.status_code, 403)
        r = self.call('POST', f'/filemaker/api/files/{fid}/records', tok2, {'ops': [{'op': 'update', 'id': recs['mine']['id'], 'data': {'F3': 'pat'}}]}, c=other)
        self.assertEqual(r.status_code, 403, 'an edit may not move a record out of reach')
        self.assertEqual(self.call('POST', f'/filemaker/api/files/{fid}/records', tok2, {'ops': [{'op': 'delete', 'id': recs['mine']['id']}]}, c=other).status_code, 403)

    def test_unsupported_record_calc_is_refused(self):
        fid = self.make_file('BadCalc')
        tok = self.open(fid).get_json()['token']
        schema = self.call('GET', f'/filemaker/api/files/{fid}/schema', tok).get_json()['schema']
        bad = {'id': 'P_bad', 'name': 'Bad', 'records': {'mode': 'custom', 'tables': {'T1': {'view': 'limited', 'viewCalc': 'Full = "x"'}}}}
        r = self.call('POST', f'/filemaker/api/files/{fid}/schema', tok, {'ops': [{'op': 'section', 'name': 'privilegeSets', 'value': schema['privilegeSets'] + [bad]}]})
        self.assertEqual(r.status_code, 400)
        self.assertIn('cannot check', r.get_json()['error'])

    def test_record_calc_evaluator(self):
        table = CONTACTS
        rc = FMH.RecordCalc('Lower ( Owner ) = "sam" and Salary > 50 and not IsEmpty ( Name )', table, schema_with([table]))
        self.assertTrue(rc.evaluate({'F3': 'Sam', 'F4': '60', 'F2': 'x'}, {}))
        self.assertFalse(rc.evaluate({'F3': 'Sam', 'F4': '40', 'F2': 'x'}, {}))
        rc = FMH.RecordCalc('Case ( Owner = Get ( AccountName ) ; 1 ; PatternCount ( Name ; "public" ) )', table, schema_with([table]))
        self.assertTrue(rc.evaluate({'F3': 'ann'}, {'account': 'Ann'}))
        self.assertTrue(rc.evaluate({'F2': 'a public note'}, {'account': 'x'}))
        self.assertFalse(rc.evaluate({'F2': 'private'}, {'account': 'x'}))

    # ── schema ─────────────────────────────────────────────────────────────
    def test_schema_lock_and_field_cleanup(self):
        fid = self.make_file('Schema')
        tok = self.open(fid).get_json()['token']
        rid = self.call('POST', f'/filemaker/api/files/{fid}/records', tok, {'ops': [{'op': 'create', 'table': 'T1', 'data': {'F2': 'a', 'F4': '5'}}]}).get_json()['results'][0]['id']
        other = self.client('office2')
        tok2 = self.open(fid, other).get_json()['token']
        self.assertTrue(self.call('POST', f'/filemaker/api/files/{fid}/lock', tok, {'key': 'schema'}).get_json()['success'])
        schema = self.call('GET', f'/filemaker/api/files/{fid}/schema', tok).get_json()['schema']
        db = {k: schema[k] for k in ('tables', 'tableOccurrences', 'relationships')}
        r = self.call('POST', f'/filemaker/api/files/{fid}/schema', tok2, {'ops': [{'op': 'section', 'name': 'database', 'value': db}]}, c=other)
        self.assertEqual(r.status_code, 409)
        db['tables'][0]['fields'] = [f for f in db['tables'][0]['fields'] if f['id'] != 'F4']
        r = self.call('POST', f'/filemaker/api/files/{fid}/schema', tok, {'ops': [{'op': 'section', 'name': 'database', 'value': db}]})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        rec = [x for x in self.open(fid).get_json()['records']['T1'] if x['id'] == rid][0]
        self.assertNotIn('F4', rec['d'])
        ch = self.call('GET', f'/filemaker/api/files/{fid}/changes?since=0', tok2, c=other).get_json()
        self.assertIsNotNone(ch['schemaVersion'])

    def test_schema_validation(self):
        for bad in ({'tables': [{'id': 'A', 'name': 'X', 'fields': []}, {'id': 'B', 'name': 'x', 'fields': []}]},
                    {'tables': [{'id': 'A', 'name': 'X', 'fields': [{'id': 'f', 'name': 'a', 'type': 'blob'}]}]},
                    {'tableOccurrences': [{'id': 'O', 'name': 'O', 'table': 'missing'}]}):
            with self.assertRaises(ValueError):
                FMH.clean_schema(dict(FMH.blank_schema(), **bad))
        s = FMH.clean_schema(dict(FMH.blank_schema(), privilegeSets=[{'id': 'PS_FULL', 'name': 'hacked', 'builtin': True, 'records': {'mode': 'none'}, 'extended': ['fmrest']}]))
        full = s['privilegeSets'][0]
        self.assertEqual(full['name'], '[Full Access]')
        self.assertEqual(full['records']['mode'], 'all_ced')
        self.assertEqual(set(full['extended']), {'fmapp', 'fmrest'})

    def test_layout_rights_and_layout_lock(self):
        fid = self.make_file('Layouts')
        tok = self.open(fid).get_json()['token']
        lay = {'id': 'L1', 'name': 'L', 'to': 'O_T1', 'parts': [], 'objects': []}
        self.assertEqual(self.call('POST', f'/filemaker/api/files/{fid}/schema', tok, {'ops': [{'op': 'upsert', 'coll': 'layouts', 'item': lay}]}).status_code, 200)
        self.add_account(fid, tok, 'clerk', 'c', 'PS_ENTRY')
        other = self.client('office2')
        ct = self.open(fid, other, account='clerk', password='c').get_json()['token']
        r = self.call('POST', f'/filemaker/api/files/{fid}/schema', ct, {'ops': [{'op': 'upsert', 'coll': 'layouts', 'item': dict(lay, name='changed')}]}, c=other)
        self.assertEqual(r.status_code, 403)
        self.call('POST', f'/filemaker/api/files/{fid}/lock', tok, {'key': 'layout:L1'})
        third = self.client('office3')
        t3 = self.open(fid, third).get_json()['token']
        r = self.call('POST', f'/filemaker/api/files/{fid}/schema', t3, {'ops': [{'op': 'upsert', 'coll': 'layouts', 'item': dict(lay, name='x')}]}, c=third)
        self.assertEqual(r.status_code, 409)

    def test_starter_serials_continue_after_sample_data(self):
        recs = {'T1': [{'F1': '100', 'F2': 'a'}, {'F1': '107', 'F2': 'b'}]}
        fid = self.make_file('Starter', records=recs)
        d = self.open(fid).get_json()
        self.assertEqual(sorted(r['d']['F1'] for r in d['records']['T1']), ['100', '107'])
        self.assertEqual(d['serials']['F1'], '108')

    def test_serial_increment(self):
        self.assertEqual(FMH.serial_increment('INV0099'), 'INV0100')
        self.assertEqual(FMH.serial_increment('99'), '100')
        self.assertEqual(FMH.serial_increment('A-7-B'), 'A-8-B')
        self.assertEqual(FMH.serial_increment('abc'), 'abc1')

    # ── containers, Excel, Insert From URL ─────────────────────────────────
    def test_containers(self):
        fid = self.make_file('Cont')
        tok = self.open(fid).get_json()['token']
        r = self.c.post(f'/filemaker/api/files/{fid}/containers', data={'file': (io.BytesIO(b'hello'), 'note.txt')},
                        headers={'X-FM-Session': tok}, content_type='multipart/form-data')
        v = r.get_json()['value']
        self.assertEqual(v['name'], 'note.txt')
        got = self.c.get(f'/filemaker/api/files/{fid}/containers/{v["c"]}')
        self.assertEqual(got.data, b'hello')
        self.assertEqual(self.client('office9').get(f'/filemaker/api/files/{fid}/containers/{v["c"]}').status_code, 401)

    def test_excel_round_trip(self):
        r = self.c.post('/filemaker/api/xlsx/build', json={'filename': 'x', 'header': True, 'rows': [['Name', 'Amount', 'When'], ['a', '1.5', '2026-01-02']], 'types': ['text', 'number', 'date']})
        self.assertEqual(r.data[:2], b'PK')
        p = self.c.post('/filemaker/api/xlsx/parse', data={'file': (io.BytesIO(r.data), 'x.xlsx')}, content_type='multipart/form-data').get_json()
        self.assertEqual(p['sheets'][0]['rows'], [['Name', 'Amount', 'When'], ['a', '1.5', '2026-01-02']])

    def test_fetch_refuses_private_addresses(self):
        fid = self.make_file('Fetch')
        tok = self.open(fid).get_json()['token']
        for url in ('http://127.0.0.1:5000/', 'http://localhost/', 'http://169.254.169.254/latest/meta-data', 'file:///etc/passwd', 'http://10.0.0.1/'):
            r = self.call('POST', f'/filemaker/api/files/{fid}/fetch', tok, {'url': url})
            self.assertEqual(r.status_code, 400, url)
            self.assertEqual(r.get_json()['fmError'], 1631 if url.startswith('http') else 1631)


if __name__ == '__main__':
    unittest.main()
