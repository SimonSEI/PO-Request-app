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
import socket
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix='filemaker_test_')
os.environ.setdefault('SECRET_KEY', 'test-secret-key-0123456789abcdef-filemaker')
os.environ.setdefault('DATA_DIR', TMP)
os.environ.setdefault('PUMPS_AUTO_SCAN', 'false')
os.environ.pop('ANTHROPIC_API_KEY', None)

A = FMH = None


def setUpModule():
    # The app is imported here, not at the top: when this module is loaded together with
    # tests.test_pumps, that module sets its environment and imports the app first, and
    # both then run against that one app (it is configured once, when first imported).
    global A, FMH
    import app as A
    import filemaker as FMH
    A.app.config['TESTING'] = True


def schema_with(tables, **extra):
    s = FMH.blank_schema()
    s['tables'] = tables
    s['tableOccurrences'] = [{'id': 'O_' + t['id'], 'name': t['name'], 'table': t['id']} for t in tables]
    s.update(extra)
    return s


def custom_set(pid, tables, **extra):
    return dict({'id': pid, 'name': pid, 'records': {'mode': 'custom', 'tables': tables}, 'layouts': {'mode': 'all_view'},
                 'valueLists': {'mode': 'all_view'}, 'scripts': {'mode': 'all_exec'}, 'extended': ['fmapp']}, **extra)


ALL = {'view': 'yes', 'edit': 'yes', 'create': 'yes', 'delete': 'yes'}


def serve(reply, tls=None):
    """A tiny HTTP server on 127.0.0.1 for the Insert From URL tests (https with a
    tls_context()). Returns (port, requests seen); each request is answered by reply(conn)."""
    srv = socket.socket()
    srv.bind(('127.0.0.1', 0))
    srv.listen(5)
    seen = []

    def loop():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            c.settimeout(5)
            if tls:
                try:
                    c = tls.wrap_socket(c, server_side=True)
                except OSError:
                    continue
            with c:
                req = b''
                while b'\r\n\r\n' not in req:
                    chunk = c.recv(4096)
                    if not chunk:
                        break
                    req += chunk
                seen.append(req.decode('latin-1'))
                try:
                    reply(c)
                except OSError:
                    pass
    threading.Thread(target=loop, daemon=True).start()
    return srv, seen


def ok_reply(c):
    c.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 6\r\nConnection: close\r\n\r\nSECRET')


def tls_context():
    """A server TLS context for 127.0.0.1, and the path of its self-signed certificate
    (the test CA a client must trust)."""
    import ipaddress
    import ssl
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'filemaker test')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = os.path.join(TMP, 'tls-cert.pem'), os.path.join(TMP, 'tls-key.pem')
    with open(cert_path, 'wb') as fh:
        fh.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(key_path, 'wb') as fh:
        fh.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                   serialization.NoEncryption()))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_path, key_path)
    return ctx, cert_path


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

    def sql(self, query, args=()):
        conn = FMH._conn()
        try:
            rows = conn.execute(query, args).fetchall()
            conn.commit()
            return rows
        finally:
            conn.close()

    def clear_failed_logins(self):
        self.sql("DELETE FROM fm_login_failures")

    def add_pset(self, fid, tok, pset):
        schema = self.call('GET', f'/filemaker/api/files/{fid}/schema', tok).get_json()['schema']
        r = self.call('POST', f'/filemaker/api/files/{fid}/schema', tok, {'ops': [{'op': 'section', 'name': 'privilegeSets', 'value': schema['privilegeSets'] + [pset]}]})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

    def upload(self, fid, tok, data, c=None):
        r = (c or self.c).post(f'/filemaker/api/files/{fid}/containers', data={'file': (io.BytesIO(data), 'x.png')},
                               headers={'X-FM-Session': tok}, content_type='multipart/form-data')
        return r

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
        self.clear_failed_logins()

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
        self.clear_failed_logins()
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

    # ── security fixes ─────────────────────────────────────────────────────
    def test_failed_logins_are_counted_per_account_in_the_database(self):
        fid = self.make_file('HR', password='right')
        tok = self.open(fid, account='Admin', password='right').get_json()['token']
        self.add_account(fid, tok, 'low', 'lowpw', 'PS_READ')
        c = self.client('attacker')
        # signing in to another account does not clear the failures against Admin
        for _ in range(2):
            for _ in range(2):
                self.assertEqual(self.open(fid, c, account='Admin', password='wrong').status_code, 401)
            self.assertEqual(self.open(fid, c, account='low', password='lowpw').status_code, 200)
        self.assertEqual(self.open(fid, c, account='Admin', password='wrong').status_code, 401)
        r = self.open(fid, c, account='Admin', password='right')
        self.assertIn('Too many', r.get_json()['error'])
        # kept in the database (so every worker process counts them), not in memory
        self.assertEqual(self.sql("SELECT COUNT(*) FROM fm_login_failures WHERE file_id=?", (fid,))[0][0], 5)
        # nobody else is locked out
        self.assertEqual(self.open(fid, self.client('bystander'), account='Admin', password='right').status_code, 200)
        # an attempt already counts while its password is checked, so guesses sent at once
        # (to any worker) cannot all get in under the limit
        seen = []
        real = FMH.check_password_hash

        def checking(h, pw):
            seen.append(self.sql("SELECT COUNT(*) FROM fm_login_failures WHERE app_user='bystander'")[0][0])
            return real(h, pw)
        with mock.patch.object(FMH, 'check_password_hash', checking):
            self.assertEqual(self.open(fid, self.client('bystander'), account='Admin', password='wrong').status_code, 401)
        self.assertEqual(seen, [1])
        self.clear_failed_logins()

    def test_limited_view_also_limits_edit_delete_and_lock(self):
        fid = self.make_file('Hidden')
        tok = self.open(fid).get_json()['token']
        self.add_pset(fid, tok, custom_set('P_own', {'T1': dict(ALL, view='limited', viewCalc='Owner = Get ( AccountName )')}))
        self.add_account(fid, tok, 'sam', 'pw', 'P_own')
        rid = self.call('POST', f'/filemaker/api/files/{fid}/records', tok, {'ops': [{'op': 'create', 'table': 'T1', 'data': {'F2': 'pat only', 'F3': 'pat'}}]}).get_json()['results'][0]['id']
        other = self.client('office2')
        st = self.open(fid, other, account='sam', password='pw').get_json()
        self.assertTrue(st['records']['T1'][0]['noaccess'])
        r = self.call('POST', f'/filemaker/api/files/{fid}/records', st['token'], {'ops': [{'op': 'update', 'id': rid, 'data': {'F2': 'overwritten by sam'}}]}, c=other)
        self.assertEqual(r.status_code, 403)
        r = self.call('POST', f'/filemaker/api/files/{fid}/lock', st['token'], {'key': f'rec:{rid}'}, c=other)
        self.assertEqual(r.get_json()['fmError'], 200)
        r = self.call('POST', f'/filemaker/api/files/{fid}/records', st['token'], {'ops': [{'op': 'delete', 'id': rid}]}, c=other)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.open(fid).get_json()['records']['T1'][0]['d']['F2'], 'pat only')

    def test_view_only_fields_are_never_taken_from_the_client(self):
        table = json.loads(json.dumps(CONTACTS))
        table['fields'] += [{'id': 'F6', 'name': 'Created By', 'type': 'text', 'options': {'autoEnter': {'creation': 'account'}}},
                            {'id': 'F7', 'name': 'Approved', 'type': 'text'},
                            {'id': 'F8', 'name': 'Modified By', 'type': 'text', 'options': {'autoEnter': {'modification': 'account'}}},
                            {'id': 'F9', 'name': 'Created', 'type': 'timestamp', 'options': {'autoEnter': {'creation': 'timestamp'}}}]
        fid = self.make_file('Audit', schema=schema_with([table]))
        tok = self.open(fid).get_json()['token']
        self.add_pset(fid, tok, custom_set('P_clerk', {'T1': dict(ALL, fields={'F6': 'view', 'F7': 'view', 'F8': 'view', 'F9': 'view'})}))
        self.add_account(fid, tok, 'sam', 'pw', 'P_clerk')
        other = self.client('office2')
        st = self.open(fid, other, account='sam', password='pw').get_json()['token']
        url = f'/filemaker/api/files/{fid}/records'
        forged = {'F6': 'Admin', 'F7': 'APPROVED', 'F8': 'Admin', 'F9': '2000-01-01 00:00:00'}
        # (its dates and times are in the users' time zone, FILEMAKER_TZ, as the browser's are, not the server's)
        tz = ZoneInfo('Pacific/Kiritimati')
        with mock.patch.object(FMH, 'FILEMAKER_TZ', tz):
            r = self.call('POST', url, st, {'ops': [{'op': 'create', 'table': 'T1', 'data': dict(forged, F2='x')}]}, c=other)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        d = r.get_json()['results'][0]['record']['d']
        self.assertEqual((d['F2'], d['F6'], d.get('F7'), d['F8']), ('x', 'sam', None, 'sam'), 'the host enters auto-enter values itself')
        created = datetime.strptime(d['F9'], '%Y-%m-%d %H:%M:%S')
        self.assertLess(abs((created - datetime.now(tz).replace(tzinfo=None)).total_seconds()), 120)
        # a pending (New Record) record committed later
        rid = self.call('POST', url, st, {'ops': [{'op': 'create', 'table': 'T1', 'data': {}, 'pending': True}]}, c=other).get_json()['results'][0]['id']
        r = self.call('POST', url, st, {'ops': [{'op': 'update', 'id': rid, 'data': dict(forged, F2='y'), 'commit': True}]}, c=other)
        d = r.get_json()['results'][0]['record']['d']
        self.assertEqual((d['F2'], d['F6'], d.get('F7'), d['F8']), ('y', 'sam', None, 'sam'))
        # a committed record: a view-only field is refused, its modification auto-enter is the host's
        self.assertEqual(self.call('POST', url, st, {'ops': [{'op': 'update', 'id': rid, 'data': {'F7': 'APPROVED'}}]}, c=other).status_code, 403)
        r = self.call('POST', url, st, {'ops': [{'op': 'update', 'id': rid, 'data': {'F2': 'z', 'F8': 'forged'}}]}, c=other)
        self.assertEqual(r.get_json()['results'][0]['record']['d']['F8'], 'sam')

    def test_new_records_keep_view_only_values_the_engine_works_out(self):
        invoices = {'id': 'T1', 'name': 'Invoices', 'fields': [
            {'id': 'F1', 'name': 'id', 'type': 'text', 'options': {'autoEnter': {'calc': 'Get ( UUID )'}}},
            {'id': 'F2', 'name': 'Customer', 'type': 'text'}, {'id': 'F3', 'name': 'Approved', 'type': 'text'}]}
        lines = {'id': 'T2', 'name': 'Lines', 'fields': [
            {'id': 'G1', 'name': 'invoice_id', 'type': 'text'}, {'id': 'G2', 'name': 'Item', 'type': 'text'},
            {'id': 'G3', 'name': 'customer_key', 'type': 'text'}]}
        rels = [{'id': 'R1', 'left': 'O_T1', 'right': 'O_T2', 'predicates': [{'leftField': 'F1', 'op': '=', 'rightField': 'G1'}],
                 'rightOpts': {'create': True}},
                # matches on a view-only field too, but creates no records there
                {'id': 'R2', 'left': 'O_T1', 'right': 'O_T2', 'predicates': [{'leftField': 'F2', 'op': '=', 'rightField': 'G3'}]}]
        fid = self.make_file('Portal', schema=schema_with([invoices, lines], relationships=rels))
        tok = self.open(fid).get_json()['token']
        self.add_pset(fid, tok, custom_set('P_clerk', {'T1': dict(ALL, fields={'F1': 'view', 'F3': 'view'}),
                                                       'T2': dict(ALL, fields={'G1': 'view', 'G3': 'view'})}))
        self.add_account(fid, tok, 'clerk', 'pw', 'P_clerk')
        other = self.client('office2')
        st = self.open(fid, other, account='clerk', password='pw').get_json()['token']
        url = f'/filemaker/api/files/{fid}/records'

        def new_record(table, data):
            # as the engine does it: a pending record, committed with its values
            rid = self.call('POST', url, st, {'ops': [{'op': 'create', 'table': table, 'data': {}, 'pending': True}]}, c=other).get_json()['results'][0]['id']
            r = self.call('POST', url, st, {'ops': [{'op': 'update', 'id': rid, 'data': data, 'commit': True}]}, c=other)
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
            return rid, r.get_json()['results'][0]['record']['d']
        inv, d = new_record('T1', {'F1': 'uuid-1', 'F2': 'ACME', 'F3': 'APPROVED'})
        self.assertEqual(d, {'F1': 'uuid-1', 'F2': 'ACME'}, 'the auto-enter calculation is kept, a typed value is not')
        _, d = new_record('T2', {'G1': 'uuid-1', 'G2': 'Widget', 'G3': 'ACME'})
        self.assertEqual(d, {'G1': 'uuid-1', 'G2': 'Widget'}, 'the portal match field is kept')
        # once the record exists, the field is the account's to view only
        r = self.call('POST', url, st, {'ops': [{'op': 'update', 'id': inv, 'data': {'F1': 'other'}}]}, c=other)
        self.assertEqual(r.status_code, 403)

    def test_concurrent_schema_saves_keep_both_changes(self):
        fid = self.make_file('Race')
        tok = self.open(fid).get_json()['token']
        real_ctx, fired = FMH._ctx, []

        def racing(conn, file_id):
            out = real_ctx(conn, file_id)
            if not fired:
                # another user's save lands after this request read the design
                fired.append(1)
                row = self.sql("SELECT schema, schema_version FROM fm_files WHERE id=?", (fid,))[0]
                s = json.loads(row['schema'])
                s['layouts'].append({'id': 'LA', 'name': 'Alice', 'to': 'O_T1', 'parts': [], 'objects': []})
                self.sql("UPDATE fm_files SET schema=?, schema_version=? WHERE id=?", (json.dumps(s), row['schema_version'] + 1, fid))
            return out
        with mock.patch.object(FMH, '_ctx', racing):
            r = self.call('POST', f'/filemaker/api/files/{fid}/schema', tok, {'ops': [{'op': 'upsert', 'coll': 'scripts', 'item': {'id': 'S1', 'name': 'Bob script', 'steps': []}}]})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        d = r.get_json()
        self.assertEqual(d['version'], 3)
        self.assertEqual([x['id'] for x in d['schema']['layouts']], ['LA'])
        self.assertEqual([x['id'] for x in d['schema']['scripts']], ['S1'])

    def test_design_locks_need_design_rights(self):
        fid = self.make_file('DesignLocks')
        tok = self.open(fid).get_json()['token']
        lay = {'id': 'L1', 'name': 'L', 'to': 'O_T1', 'parts': [], 'objects': []}
        self.call('POST', f'/filemaker/api/files/{fid}/schema', tok, {'ops': [{'op': 'upsert', 'coll': 'layouts', 'item': lay}]})
        self.add_account(fid, tok, 'ro', 'r', 'PS_READ')
        other = self.client('office2')
        rt = self.open(fid, other, account='ro', password='r').get_json()['token']
        for key in ('schema', 'security', 'layout:L1', 'script:S1', 'valueList:V1'):
            r = self.call('POST', f'/filemaker/api/files/{fid}/lock', rt, {'key': key}, c=other)
            self.assertEqual(r.status_code, 403, key)
        schema = self.call('GET', f'/filemaker/api/files/{fid}/schema', tok).get_json()['schema']
        r = self.call('POST', f'/filemaker/api/files/{fid}/schema', tok, {'ops': [{'op': 'section', 'name': 'database', 'value': {k: schema[k] for k in ('tables', 'tableOccurrences', 'relationships')}}]})
        self.assertEqual(r.status_code, 200)

    def test_password_rules_hold_on_open_and_relogin(self):
        fid = self.make_file('PwRules')
        tok = self.open(fid).get_json()['token']
        self.add_pset(fid, tok, custom_set('P_fixed', {'T1': ALL}, modifyOwnPassword=False))
        self.add_account(fid, tok, 'sam', 'pw', 'P_fixed')
        self.add_account(fid, tok, 'ro', 'r', 'PS_READ')
        self.call('POST', f'/filemaker/api/files/{fid}/accounts', tok, {'ops': [{'op': 'add', 'name': 'temp', 'password': 'Welcome1', 'privilegeSet': 'PS_READ', 'mustChange': True}]})
        other = self.client('office2')
        self.assertEqual(self.open(fid, other, account='sam', password='pw', newPassword='hijacked').status_code, 403)
        self.assertEqual(self.open(fid, other, account='sam', password='pw').status_code, 200)
        rt = self.open(fid, other, account='ro', password='r').get_json()['token']
        r = self.call('POST', f'/filemaker/api/files/{fid}/relogin', rt, {'account': 'temp', 'password': 'Welcome1'}, c=other)
        self.assertEqual(r.status_code, 403)
        self.assertTrue(r.get_json()['mustChange'])
        # a must-change account may still set its new password when it opens the file
        self.assertEqual(self.open(fid, other, account='temp', password='Welcome1', newPassword='Mine2').status_code, 200)
        self.clear_failed_logins()

    def test_change_feed_skips_tables_the_account_cannot_view(self):
        payroll = {'id': 'T2', 'name': 'Payroll', 'fields': [{'id': 'G1', 'name': 'Amount', 'type': 'number'}]}
        fid = self.make_file('Feed', schema=schema_with([json.loads(json.dumps(CONTACTS)), payroll]))
        tok = self.open(fid).get_json()['token']
        self.add_pset(fid, tok, custom_set('P_t1', {'T1': ALL, 'T2': {'view': 'no'}}))
        self.add_account(fid, tok, 'sam', 'pw', 'P_t1')
        other = self.client('office2')
        st = self.open(fid, other, account='sam', password='pw').get_json()
        url = f'/filemaker/api/files/{fid}/records'
        rid = self.call('POST', url, tok, {'ops': [{'op': 'create', 'table': 'T2', 'data': {'G1': '9000'}}, {'op': 'create', 'table': 'T1', 'data': {'F2': 'seen'}}]}).get_json()['results'][0]['id']
        self.call('POST', url, tok, {'ops': [{'op': 'update', 'id': rid, 'data': {'G1': '9500'}}]})
        self.call('POST', url, tok, {'ops': [{'op': 'delete', 'id': rid}]})
        ch = self.call('GET', f'/filemaker/api/files/{fid}/changes?since={st["seq"]}', st['token'], c=other).get_json()
        self.assertEqual(ch['deleted'], [])
        self.assertEqual([r['t'] for r in ch['records']], ['T1'])

    def test_open_never_misses_a_change_made_while_it_reads(self):
        fid = self.make_file('Snapshot')
        tok = self.open(fid).get_json()['token']
        rid = self.call('POST', f'/filemaker/api/files/{fid}/records', tok, {'ops': [{'op': 'create', 'table': 'T1', 'data': {'F2': 'v1'}}]}).get_json()['results'][0]['id']
        real, fired = FMH._all_records, []

        def racing(ctx):
            out = real(ctx)
            if not fired:
                # another user's edit is committed just after the records were read
                fired.append(1)
                conn = FMH._conn()
                conn.execute("UPDATE fm_records SET data=?, mod_count=mod_count+1 WHERE id=?", (json.dumps({'F1': '100', 'F2': 'v2'}), rid))
                FMH._change(conn, fid, 'rec', 'another-session', 'Admin', 'T1', rid)
                conn.commit()
                conn.close()
            return out
        other = self.client('office2')
        with mock.patch.object(FMH, '_all_records', racing):
            st = self.open(fid, other).get_json()
        self.assertEqual(st['records']['T1'][0]['d']['F2'], 'v1')
        ch = self.call('GET', f'/filemaker/api/files/{fid}/changes?since={st["seq"]}', st['token'], c=other).get_json()
        self.assertEqual([r['d']['F2'] for r in ch['records']], ['v2'])

    def test_malformed_bodies_are_refused_not_crashing(self):
        fid = self.make_file('Junk')
        tok = self.open(fid).get_json()['token']
        rid = self.call('POST', f'/filemaker/api/files/{fid}/records', tok, {'ops': [{'op': 'create', 'table': 'T1', 'data': {'F2': 'a'}}]}).get_json()['results'][0]['id']
        for path, body in (('records', [1]), ('records', {'ops': ['x']}), ('records', {'ops': [{'op': 'create', 'table': [1]}]}),
                           ('records', {'ops': [{'op': 'update', 'id': rid, 'data': {}, 'mc': [1]}]}), ('records', {'ops': [{'op': 'delete', 'id': [1]}]}),
                           ('schema', {'ops': ['x']}), ('schema', {'ops': [{'op': 'upsert', 'coll': ['layouts'], 'item': {}}]}),
                           ('schema', {'ops': [{'op': 'upsert', 'coll': 'layouts', 'item': [1]}]}),
                           ('schema', {'ops': [{'op': 'section', 'name': 'database', 'value': [1]}]}), ('schema', {'ops': [], 'serials': [1]}),
                           ('accounts', {'ops': ['x']}), ('accounts', {'ops': [{'op': 'add', 'name': 'x', 'privilegeSet': ['PS_READ']}]}),
                           ('fetch', {'url': 'https://example.com/', 'headers': [1]}),
                           # numbers SQLite cannot hold (JSON Infinity, or beyond 64 bits)
                           ('records', {'ops': [{'op': 'update', 'id': float('inf'), 'data': {}}]}),
                           ('records', {'ops': [{'op': 'update', 'id': 10 ** 23, 'data': {}}]}), ('records', {'ops': [{'op': 'delete', 'id': 10 ** 23}]}),
                           ('records', {'ops': [{'op': 'update', 'id': rid, 'data': {}, 'mc': -10 ** 23}]}),
                           ('lock', {'key': 'rec:99999999999999999999999'}), ('accounts', {'ops': [{'op': 'update', 'id': 10 ** 23, 'name': 'x'}]})):
            r = self.call('POST', f'/filemaker/api/files/{fid}/{path}', tok, body)
            self.assertIn(r.status_code, (400, 404), (path, body))
        self.assertEqual(self.call('GET', f'/filemaker/api/files/{fid}/changes?since=99999999999999999999999', tok).status_code, 200)
        self.assertEqual(self.call('POST', f'/filemaker/api/files/{fid}/unlock', tok, {'keys': 5}).status_code, 200)
        r = self.c.post('/filemaker/api/xlsx/build', json={'rows': [['2024-99-99', '1' * 5000, 'a\x01b']], 'types': ['date', 'number', 'text']})
        self.assertEqual(r.status_code, 200)

    # ── containers ─────────────────────────────────────────────────────────
    def container_file(self, name):
        contacts = json.loads(json.dumps(CONTACTS))
        contacts['fields'] += [{'id': 'F6', 'name': 'Photo', 'type': 'container'}, {'id': 'F7', 'name': 'Attachment', 'type': 'container'}]
        secret = {'id': 'T2', 'name': 'Secret', 'fields': [{'id': 'G1', 'name': 'Scan', 'type': 'container'}]}
        return self.make_file(name, schema=schema_with([contacts, secret]))

    def test_container_downloads_follow_record_privileges(self):
        fid = self.container_file('Pics')
        tok = self.open(fid).get_json()['token']
        own = {'view': 'limited', 'viewCalc': 'Owner = Get ( AccountName )', 'edit': 'limited', 'editCalc': 'Owner = Get ( AccountName )', 'create': 'yes', 'delete': 'no'}
        self.add_pset(fid, tok, custom_set('P_own', {'T1': own, 'T2': {'view': 'no'}}))
        self.add_pset(fid, tok, custom_set('P_nophoto', {'T1': dict(ALL, fields={'F6': 'none'}), 'T2': {'view': 'no'}}))
        self.add_account(fid, tok, 'sam', 'pw', 'P_own')
        self.add_account(fid, tok, 'nopic', 'pw', 'P_nophoto')
        secret, theirs, mine = (self.upload(fid, tok, data).get_json()['value'] for data in (b'TOP SECRET SCAN', b'pat photo', b'sam photo'))
        url = f'/filemaker/api/files/{fid}/records'
        r = self.call('POST', url, tok, {'ops': [{'op': 'create', 'table': 'T2', 'data': {'G1': secret}},
                                                 {'op': 'create', 'table': 'T1', 'data': {'F2': 'p', 'F3': 'pat', 'F6': theirs}},
                                                 {'op': 'create', 'table': 'T1', 'data': {'F2': 's', 'F3': 'sam', 'F6': mine}}]})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        sams = r.get_json()['results'][2]['id']
        other = self.client('office2')
        st = self.open(fid, other, account='sam', password='pw').get_json()['token']

        def get(c, v):
            return c.get(f'/filemaker/api/files/{fid}/containers/{v["c"]}')
        got = get(other, mine)
        self.assertEqual(got.data, b'sam photo')
        self.assertEqual(got.headers['Cache-Control'], 'private, no-cache')
        self.assertEqual(get(other, secret).status_code, 403)
        self.assertEqual(get(other, theirs).status_code, 403)
        # an upload is seen by the session that made it until a record holds it
        draft = self.upload(fid, st, b'draft', c=other).get_json()['value']
        self.assertEqual(get(other, draft).data, b'draft')
        self.assertEqual(get(self.c, draft).status_code, 403)
        # a guessed id cannot be put into a record of one's own to read it through that
        r = self.call('POST', url, st, {'ops': [{'op': 'create', 'table': 'T1', 'data': {'F2': 'x', 'F3': 'sam', 'F6': secret}}]}, c=other)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(get(other, secret).status_code, 403)
        # a "no access" field hides the file even in a record the account can view
        third = self.client('office3')
        nt = self.open(fid, third, account='nopic', password='pw').get_json()['token']
        self.assertEqual(get(third, mine).status_code, 403)
        # nor can it be copied from that field into one the account may modify, in the same record
        r = self.call('POST', url, nt, {'ops': [{'op': 'update', 'id': sams, 'data': {'F7': mine}}]}, c=third)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(get(third, mine).status_code, 403)
        # a field keeps the id it already holds
        r = self.call('POST', url, nt, {'ops': [{'op': 'update', 'id': sams, 'data': {'F2': 'renamed'}}]}, c=third)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

    def test_container_uploads_need_a_field_to_put_them_in_and_orphans_are_removed(self):
        fid = self.container_file('Uploads')
        tok = self.open(fid).get_json()['token']
        self.add_account(fid, tok, 'ro', 'r', 'PS_READ')
        other = self.client('office2')
        rt = self.open(fid, other, account='ro', password='r').get_json()['token']
        self.assertEqual(self.upload(fid, rt, b'junk', c=other).status_code, 403)
        kept, orphan = (self.upload(fid, tok, data).get_json()['value'] for data in (b'kept', b'orphan'))
        self.call('POST', f'/filemaker/api/files/{fid}/records', tok, {'ops': [{'op': 'create', 'table': 'T1', 'data': {'F6': kept}}]})
        self.sql("UPDATE fm_containers SET created_at='2000-01-01 00:00:00' WHERE file_id=?", (fid,))
        conn = FMH._conn()
        FMH._cleanup(conn, force=True)
        conn.close()
        self.assertEqual([r['id'] for r in self.sql("SELECT id FROM fm_containers WHERE file_id=?", (fid,))], [kept['c']])
        folder = os.path.join(FMH._data_dir, 'filemaker_files', str(fid))
        self.assertEqual(sorted(os.listdir(folder)), [str(kept['c'])])

    # ── Excel ──────────────────────────────────────────────────────────────
    def xlsx_with_sheet(self, sheet_xml):
        r = self.c.post('/filemaker/api/xlsx/build', json={'rows': [['a']]})
        src, out = zipfile.ZipFile(io.BytesIO(r.data)), io.BytesIO()
        with zipfile.ZipFile(out, 'w') as z:
            for item in src.infolist():
                z.writestr(item, sheet_xml if item.filename == 'xl/worksheets/sheet1.xml' else src.read(item.filename))
        return out.getvalue()

    def test_xlsx_declared_size_is_not_trusted(self):
        ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        # says it is 16,384 columns by 300 rows, but holds two cells
        tiny = self.xlsx_with_sheet(f'<worksheet {ns}><dimension ref="A1:XFD300"/><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>x</t></is></c></row>'
                                    f'<row r="300"><c r="A300" t="inlineStr"><is><t>y</t></is></c></row></sheetData></worksheet>')
        started = time.time()
        p = self.c.post('/filemaker/api/xlsx/parse', data={'file': (io.BytesIO(tiny), 'x.xlsx')}, content_type='multipart/form-data').get_json()
        rows = p['sheets'][0]['rows']
        self.assertEqual((len(rows), max(len(r) for r in rows), rows[0], rows[-1]), (300, 1, ['x'], ['y']))
        self.assertLess(time.time() - started, 5)
        # a cell in the last column of many rows is refused, not padded out
        wide = ''.join(f'<row r="{i}"><c r="XFD{i}" t="inlineStr"><is><t>z</t></is></c></row>' for i in range(1, 201))
        r = self.c.post('/filemaker/api/xlsx/parse', data={'file': (io.BytesIO(self.xlsx_with_sheet(f'<worksheet {ns}><sheetData>{wide}</sheetData></worksheet>')), 'x.xlsx')},
                        content_type='multipart/form-data')
        self.assertEqual(r.status_code, 400)
        self.assertIn('too large', r.get_json()['error'])

    def test_xlsx_bytes_are_limited_not_only_cells(self):
        ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'

        def parse(cells):
            sheet = f'<worksheet {ns}><sheetData><row r="1">' + ''.join(
                f'<c r="{chr(65 + i)}1" t="inlineStr"><is><t>{t}</t></is></c>' for i, t in enumerate(cells)) + '</row></sheetData></worksheet>'
            return self.c.post('/filemaker/api/xlsx/parse', data={'file': (io.BytesIO(self.xlsx_with_sheet(sheet)), 'x.xlsx')},
                               content_type='multipart/form-data')
        # a megabyte of one letter zips to about a kilobyte: what it unpacks to is what counts
        with mock.patch.object(FMH, 'MAX_XLSX_UNZIPPED', 512 * 1024):
            r = parse(['A' * 1024 * 1024])
        self.assertEqual(r.status_code, 400)
        self.assertIn('too large', r.get_json()['error'])
        # and the text of all the cells together (a shared string may be in every cell)
        with mock.patch.object(FMH, 'MAX_XLSX_TEXT', 1000):
            self.assertEqual(parse(['b' * 400] * 2).status_code, 200)
            r = parse(['b' * 400] * 3)
        self.assertEqual(r.status_code, 400)
        self.assertIn('too large', r.get_json()['error'])

    # ── Insert From URL ─────────────────────────────────────────────────────
    def fetch(self, fid, tok, url):
        return self.call('POST', f'/filemaker/api/files/{fid}/fetch', tok, {'url': url})

    def test_fetch_url_parser_tricks_are_refused(self):
        fid = self.make_file('FetchTricks')
        tok = self.open(fid).get_json()['token']
        srv, seen = serve(ok_reply)
        self.addCleanup(srv.close)
        port = srv.getsockname()[1]
        real = socket.getaddrinfo
        # example.com resolves to a public address here, so only the URL check can stop these
        with mock.patch('socket.getaddrinfo', lambda host, *a, **k: real('93.184.216.34' if host == 'example.com' else host, *a, **k)):
            for url in (f'http://127.0.0.1:{port}\\@example.com/', f'http://127.0.0.1:{port}\t@example.com/',
                        f'http://127.0.0.1:{port} @example.com/', f'http://[::ffff:127.0.0.1]:{port}/'):
                r = self.fetch(fid, tok, url)
                self.assertEqual(r.status_code, 400, url)
        self.assertEqual(seen, [])
        # every redirect is checked again: the first server counts as public here, the address it sends to does not
        with mock.patch.object(FMH, '_public_ip', lambda a: a == '127.0.0.1'):
            for target in (f'http://127.0.0.1:{port}\\@example.com/', 'http://127.0.0.2/'):
                red, red_seen = serve(lambda c, t=target: c.sendall(f'HTTP/1.1 302 Found\r\nLocation: {t}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'.encode()))
                self.addCleanup(red.close)
                r = self.fetch(fid, tok, f'http://127.0.0.1:{red.getsockname()[1]}/')
                self.assertEqual(r.status_code, 400, target)
                self.assertEqual(len(red_seen), 1)
        self.assertEqual(seen, [])
        # IPv6 forms that carry an IPv4 address are judged by that address
        self.assertEqual([FMH._public_ip(a) for a in ('::ffff:127.0.0.1', '::127.0.0.1', '64:ff9b::7f00:1', '64:ff9b::5db8:d822')],
                         [False, False, False, True])

    def test_fetch_connects_to_the_address_it_checked(self):
        fid = self.make_file('FetchPin')
        tok = self.open(fid).get_json()['token']
        srv, seen = serve(ok_reply)
        self.addCleanup(srv.close)
        port = srv.getsockname()[1]
        checked, real = [], socket.getaddrinfo

        def public_host(host, port=None):
            checked.append(host)
            return ['127.0.0.1']        # what the check approved

        def resolver(host, *a, **k):
            # a second lookup (DNS rebinding) would give another answer; it must not be made
            if host == 'rebind.test':
                raise socket.gaierror('second lookup')
            return real(host, *a, **k)
        with mock.patch.object(FMH, '_public_host', public_host), mock.patch('socket.getaddrinfo', resolver):
            r = self.fetch(fid, tok, f'http://rebind.test:{port}/x')
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json()['text'], 'SECRET')
        self.assertEqual(checked, ['rebind.test'])
        self.assertIn(f'Host: rebind.test:{port}', seen[0])
        # and a name that resolves to a private address is refused at the connection
        with mock.patch('socket.getaddrinfo', lambda host, *a, **k: real('127.0.0.1' if host == 'internal.test' else host, *a, **k)):
            self.assertEqual(self.fetch(fid, tok, f'http://internal.test:{port}/').status_code, 400)
        self.assertEqual(len(seen), 1)

    def test_fetch_has_an_overall_deadline(self):
        fid = self.make_file('FetchSlow')
        tok = self.open(fid).get_json()['token']

        def trickle(c):
            c.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 10\r\n\r\n')
            for _ in range(10):
                c.sendall(b'a')
                time.sleep(0.4)
        tls, ca = tls_context()

        class TrustingSession(FMH.http_requests.Session):
            def __init__(self):
                super().__init__()
                self.verify = ca      # the test CA
        # https too: the socket it reads through is a wrapped copy of the one connected
        for scheme in ('http', 'https'):
            srv, seen = serve(trickle, tls if scheme == 'https' else None)
            self.addCleanup(srv.close)
            started = time.time()
            with mock.patch.object(FMH, '_public_ip', lambda a: a == '127.0.0.1'), mock.patch.object(FMH, 'FETCH_DEADLINE', 1), \
                    mock.patch.object(FMH.http_requests, 'Session', TrustingSession):
                r = self.fetch(fid, tok, f'{scheme}://127.0.0.1:{srv.getsockname()[1]}/')
            self.assertEqual(r.status_code, 400, scheme)
            self.assertIn('too long', r.get_json()['error'])
            self.assertEqual(len(seen), 1, scheme)
            self.assertLess(time.time() - started, 3, scheme)

    def test_fetch_sends_spaces_encoded_and_international_names(self):
        fid = self.make_file('FetchSpace')
        tok = self.open(fid).get_json()['token']
        srv, seen = serve(ok_reply)
        self.addCleanup(srv.close)
        # "...?q=" & City with City "New York": FileMaker encodes the address itself
        with mock.patch.object(FMH, '_public_ip', lambda a: a == '127.0.0.1'):
            r = self.fetch(fid, tok, f'http://127.0.0.1:{srv.getsockname()[1]}/search?q=New York')
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertTrue(seen[0].startswith('GET /search?q=New%20York HTTP/1.1'), seen[0])
        # a space before an @ is then part of the user name, for urllib3 as for urlparse
        self.assertEqual(FMH.urlparse(FMH._check_fetch_url('http://127.0.0.1:80 @example.com/')).hostname, 'example.com')
        # names are compared after IDNA encoding the way urllib3 does it (ß is not "ss")
        for url in ('https://straße.de/', 'https://faß.de/x', 'https://bücher.de/'):
            self.assertEqual(FMH._check_fetch_url(url), url)

    def test_fetch_with_an_unknown_charset_is_read_as_utf8(self):
        fid = self.make_file('FetchCharset')
        tok = self.open(fid).get_json()['token']
        srv, seen = serve(lambda c: c.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=nonsense\r\n'
                                              b'Content-Length: 2\r\nConnection: close\r\n\r\nok'))
        self.addCleanup(srv.close)
        with mock.patch.object(FMH, '_public_ip', lambda a: a == '127.0.0.1'):
            r = self.fetch(fid, tok, f'http://127.0.0.1:{srv.getsockname()[1]}/')
        self.assertEqual((r.status_code, r.get_json()['text']), (200, 'ok'))


if __name__ == '__main__':
    unittest.main()
