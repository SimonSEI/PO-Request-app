"""
Tests for the Vendor Invoices app (vendor_invoices.py).

    python -m unittest tests.test_vendor_invoices -v

Runs against a throwaway database that starts with the real workbook (vendor_invoices_seed.json).
The PO@ mailbox, Microsoft 365 and Jobber are fakes that record what they were asked.
Vendors and addresses in the made-up mail are invented.
"""
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix='vendor_invoices_test_')
os.environ.update(SECRET_KEY='test-secret-key-0123456789abcdef-vi', DATA_DIR=TMP, PUMPS_AUTO_SCAN='false',
                  WORKORDERS_AUTO_RUN='false', AR_AUTO_RUN='false', VI_AUTO_RUN='false',
                  WEBSITE_URL='https://office.example.com')
os.environ.pop('ANTHROPIC_API_KEY', None)

import app as A  # noqa: E402
import vendor_invoices as V  # noqa: E402

A.app.config['TESTING'] = True
A.app.config['WTF_CSRF_ENABLED'] = False


def q(sql, *args):
    conn = sqlite3.connect(A.DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return rows


def tab_id(label):
    return q("SELECT id FROM vib_tabs WHERE label=?", label)[0]['id']


class FakeMail:
    """PO@ (as Graph sees it) plus Microsoft 365 sending."""

    def __init__(self):
        self.inbox, self.sent, self.seen = [], [], set()

    def add(self, uid, sender, subject, filename, received='2026-10-14T13:05:00Z'):
        self.inbox.append((uid, {'from': {'emailAddress': {'address': sender}}, 'subject': subject,
                                 'receivedDateTime': received, 'hasAttachments': True}, filename))

    def fetch(self, log_table, extensions, since=None):
        logged = {r['email_uid'] for r in q(f"SELECT email_uid FROM {log_table}")}
        return {'source': 'graph_api', 'diagnostics': {},
                'emails': [(uid, msg) for uid, msg, _ in self.inbox if uid not in logged]}

    def attachments(self, uid):
        return [(f, b'%PDF-1.4 fake ' + uid.encode()) for u, _, f in self.inbox if u == uid]

    def send(self, to, subject, body):
        self.sent.append({'to': to, 'subject': subject, 'body': body})
        return True


class FakeJobber:
    def __init__(self):
        self.invoices = {}

    def add(self, jid, number, status='awaiting_payment', client='Example HOA', total=1000.0):
        self.invoices[jid] = {'id': jid, 'invoiceNumber': number, 'subject': 'Pay app 1', 'invoiceStatus': status,
                              'issuedDate': '2026-10-01', 'jobberWebUri': f'https://jobber.example/{jid}',
                              'amounts': {'total': total, 'invoiceBalance': 0 if status == 'paid' else total},
                              'client': {'name': client}}

    def __call__(self, query, variables=None):
        if 'invoices(searchTerm' in query:
            term = (variables or {}).get('q', '')
            return {'invoices': {'nodes': [i for i in self.invoices.values()
                                           if term in i['invoiceNumber'] or term.lower() in i['client']['name'].lower()]}}
        return {'invoice': self.invoices.get((variables or {}).get('id'))}


class VendorInvoicesTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        self.c = A.app.test_client()
        self.mail = FakeMail()
        self.jobber = FakeJobber()
        self._saved = dict(V._cfg)
        self._send, self._jobber_fn = V.send_mail, V._jobber
        V._cfg.update(fetch_emails=self.mail.fetch, graph_attachments=self.mail.attachments,
                      jobber_connected=lambda: True,
                      extract_fields=lambda text, sender: json.loads(text))
        V.send_mail = self.mail.send
        V._jobber = self.jobber
        self._pdf_text = V._pdf_text
        V._pdf_text = lambda data: json.dumps(self.fields.get(data.decode().split()[-1], {}))
        self.fields = {}
        A.set_setting('christian_email', 'christian@example.com')

    def tearDown(self):
        V._cfg.clear()
        V._cfg.update(self._saved)
        V.send_mail, V._jobber, V._pdf_text = self._send, self._jobber_fn, self._pdf_text
        conn = sqlite3.connect(A.DB_PATH)
        for t in ('vib_received', 'vib_email_log', 'vib_senders'):
            conn.execute(f"DELETE FROM {t}")
        conn.execute("DELETE FROM vib_rows WHERE source<>'workbook'")
        conn.execute("DELETE FROM vib_tabs WHERE source<>'workbook'")
        conn.commit()
        conn.close()

    def login(self, role='office', username='office1'):
        with self.c.session_transaction() as s:
            s['username'], s['role'], s['full_name'] = username, role, 'Office Tester'

    # ── the workbook ──

    def test_every_month_of_the_workbook_is_here_in_order(self):
        tabs = [t['label'] for t in V.tabs_summary()]
        self.assertEqual(len(tabs), 80)
        self.assertEqual(tabs[:3], ['OCTOBER 2026', 'SEPTEMBER 2026', 'AUGUST 2026'])
        self.assertEqual(tabs[-1], 'MARCH')
        self.assertNotIn('MASTER COPY BLANK', tabs)
        filled = q("SELECT COUNT(*) n FROM vib_rows WHERE " + ' OR '.join(f"{k}<>''" for k in V.KEYS))[0]['n']
        self.assertEqual(filled, 1786)

    def test_a_row_keeps_its_values_colors_and_dates(self):
        rows = V.tab_rows(tab_id('SEPTEMBER 2026'))
        first = rows[0]
        self.assertEqual((first['ok'], first['vendor'], first['inv_date'], first['inv_no'], first['inv_total']),
                         ('YES', 'PELICAN LAWN', '2026-09-17', '46077', '45495'))
        self.assertEqual(first['proposal'], '63966/63967')
        self.assertEqual(first['style']['ok']['bg'], '92D050')
        # Text typed into a date column stays as typed.
        aug = V.tab_rows(tab_id('AUGUST 2026'))
        self.assertIn('TBD SEPT 23', [r['date_billed'] for r in aug])
        self.assertEqual([r for r in aug if r['inv_no'] == '45984'][0]['style']['ok']['bg'], 'FF0000')

    def test_merged_cells_come_across(self):
        aug = V.tab_rows(tab_id('AUGUST 2026'))
        self.assertEqual(aug[2]['spans'].get('inv_date'), [2, 1])   # C4:C5
        self.assertEqual(aug[27]['spans'].get('proposal'), [1, 4])  # G29:J29

    def test_old_tabs_keep_their_own_headers(self):
        t = [t for t in V.tabs_summary() if t['label'] == 'JANUARY 2024'][0]
        self.assertEqual(t['headers']['to_christian'], 'INVOICE TO JOANNE')
        t = [t for t in V.tabs_summary() if t['label'] == 'MARCH'][0]
        self.assertEqual(t['headers']['inv_total'], 'COST')
        self.assertNotIn('ok', t['headers'])

    def test_download_and_upload_round_trip(self):
        self.login()
        r = self.c.get('/vendor-invoices/api/export')
        self.assertEqual(r.status_code, 200)
        tabs = V.parse_workbook(r.data)
        sep = [t for t in tabs if t['label'] == 'SEPTEMBER 2026'][0]
        here = V.tab_rows(tab_id('SEPTEMBER 2026'))
        self.assertEqual([(x['vendor'], x['inv_no'], x['inv_total'], x['date_billed']) for x in sep['rows']],
                         [(x['vendor'], x['inv_no'], x['inv_total'], x['date_billed']) for x in here])
        self.assertEqual(sep['rows'][0]['style']['ok']['bg'], '92D050')
        aug = [t for t in tabs if t['label'] == 'AUGUST 2026'][0]
        self.assertEqual(aug['rows'][2]['spans'].get('inv_date'), [2, 1])
        # Uploading it back adds nothing: every tab is already here.
        r = self.c.post('/vendor-invoices/api/import', data={'file': (io.BytesIO(r.data), 'book.xlsx')},
                        content_type='multipart/form-data')
        j = r.get_json()
        self.assertTrue(j['success'])
        self.assertEqual((j['rows'], len(j['added']), len(j['skipped'])), (0, 0, 80))

    # ── who can open it ──

    def test_office_only(self):
        self.login(role='technician', username='tech1')
        self.assertEqual(self.c.get('/vendor-invoices').status_code, 302)
        self.assertEqual(self.c.get('/vendor-invoices/api/state').status_code, 403)
        self.login()
        r = self.c.get('/vendor-invoices')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Vendor Invoices', r.data)

    def test_dashboard_shows_it_under_coming_soon(self):
        self.login()
        r = self.c.get('/dashboard')
        self.assertIn(b'Vendor Invoices <span class="soon-badge">Coming Soon</span>', r.data)
        self.login(role='technician', username='tech1')
        self.assertNotIn(b'Open Vendor Invoices', self.c.get('/dashboard').data)

    # ── editing ──

    def test_typing_in_cells(self):
        self.login()
        tid, _ = V.add_tab('NOVEMBER 2026')
        self.assertEqual(V.tabs_summary()[0]['label'], 'NOVEMBER 2026')
        row = self.c.post('/vendor-invoices/api/row/add', json={'tab_id': tid}).get_json()['row']
        r = self.c.post('/vendor-invoices/api/cell', json={'id': row['id'], 'key': 'inv_date', 'value': '9/17/26'})
        self.assertEqual(r.get_json()['row']['inv_date'], '2026-09-17')
        r = self.c.post('/vendor-invoices/api/cell', json={'id': row['id'], 'key': 'date_billed', 'value': 'TBD OCT 20'})
        self.assertEqual(r.get_json()['row']['date_billed'], 'TBD OCT 20')
        r = self.c.post('/vendor-invoices/api/cell', json={'id': row['id'], 'key': 'inv_total', 'value': '$1,234.50'})
        self.assertEqual(r.get_json()['row']['inv_total'], '1234.5')
        r = self.c.post('/vendor-invoices/api/cell', json={'id': row['id'], 'key': 'ok', 'value': 'no'})
        self.assertEqual(r.get_json()['row']['style']['ok']['bg'], 'FF0000')
        r = self.c.post('/vendor-invoices/api/style', json={'id': row['id'], 'keys': ['notes'], 'bg': '66FFFF', 'bold': True})
        self.assertEqual(r.get_json()['row']['style']['notes'], {'bg': '66FFFF', 'b': 1})
        self.assertEqual(self.c.post('/vendor-invoices/api/cell', json={'id': row['id'], 'key': 'style', 'value': 'x'})
                         .status_code, 400)

    def test_deleting_a_row_shortens_a_merge_over_it(self):
        tid, _ = V.add_tab('DECEMBER 2026')
        a = V.add_row(tid, values={'vendor': 'A'})
        b = V.add_row(tid, values={'vendor': 'B'})
        V.add_row(tid, values={'vendor': 'C'})
        conn = sqlite3.connect(A.DB_PATH)
        conn.execute("UPDATE vib_rows SET spans=? WHERE id=?", (json.dumps({'ok': [3, 1]}), a['id']))
        conn.commit()
        conn.close()
        V.delete_row(b['id'])
        rows = V.tab_rows(tid)
        self.assertEqual([r['vendor'] for r in rows], ['A', 'C'])
        self.assertEqual(rows[0]['spans'], {'ok': [2, 1]})

    def test_search_finds_rows_in_any_month(self):
        self.login()
        rows = self.c.get('/vendor-invoices/api/search?q=46077').get_json()['rows']
        self.assertEqual([(r['tab_label'], r['vendor']) for r in rows], [('SEPTEMBER 2026', 'PELICAN LAWN')])

    # ── the PO@ inbox ──

    def test_scan_sorts_vendor_pump_and_unknown_pdfs(self):
        self.mail.add('m1', 'billing@pelicanlawn.example', 'Invoice 46200', 'inv46200.pdf')
        self.mail.add('m2', 'office@wettec.biz', 'Invoice 9136', 'wet.pdf')
        self.mail.add('m3', 'ar@acme-rentals.example', 'Your statement', 'statement.pdf')
        self.fields = {'m1': {'sub_contractor': 'Pelican Lawn Services Inc', 'invoice_number': '46200',
                              'invoice_date': '2026-10-13', 'invoice_total': 1500, 'notes': 'Tide maintenance'},
                       'm3': {'sub_contractor': 'Acme Rentals', 'invoice_number': 'S-1', 'invoice_total': 80}}
        s = V.scan_inbox()
        self.assertEqual((s['emails_checked'], s['added'], s['other'], s['pump']), (3, 1, 1, 1))
        got = {x['inv_no']: x for x in V.inbox()}
        self.assertEqual(got['46200']['status'], 'received')
        self.assertEqual(got['46200']['vendor'], 'PELICAN LAWN')
        self.assertEqual(got['S-1']['status'], 'other')
        # Each email is read once.
        self.assertEqual(V.scan_inbox()['emails_checked'], 0)
        self.login()
        r = self.c.get(f"/vendor-invoices/api/inbox/{got['46200']['id']}/file")
        self.assertEqual(r.status_code, 200)
        r.close()

    def test_pump_vendor_named_only_inside_the_pdf_is_skipped(self):
        self.mail.add('m1', 'ap@somewhere.example', 'Invoice', 'x.pdf')
        self.fields = {'m1': {'sub_contractor': 'WET TEC Inc', 'invoice_number': '9001'}}
        self.assertEqual(V.scan_inbox()['pump'], 1)
        self.assertEqual(V.inbox(), [])

    def test_entering_an_invoice_from_the_inbox(self):
        self.mail.add('m1', 'billing@pelicanlawn.example', 'Invoice 46201', 'a.pdf')
        self.fields = {'m1': {'sub_contractor': 'Pelican Lawn', 'invoice_number': '46201', 'invoice_date': '2026-10-13',
                              'invoice_total': 900.5, 'sei_proposal_number': '67001', 'notes': 'Root barrier'}}
        V.scan_inbox()
        rec = V.inbox()[0]
        self.login()
        tid, _ = V.add_tab('NOVEMBER 2026')
        j = self.c.post(f"/vendor-invoices/api/inbox/{rec['id']}/enter", json={'tab_id': tid}).get_json()
        row = j['row']
        self.assertEqual((row['tab_id'], row['ok'], row['vendor'], row['inv_no'], row['inv_total'], row['inv_date'],
                          row['proposal']), (tid, 'YES', 'PELICAN LAWN', '46201', '900.5', '2026-10-13', '67001'))
        self.assertEqual(V.inbox()[0]['status'], 'inputted')

    def test_typing_the_invoice_on_the_sheet_counts_as_entered(self):
        self.mail.add('m1', 'office@sanchezsod.example', 'Inv 10500', 'a.pdf')
        self.fields = {'m1': {'sub_contractor': 'Sanchez Sod LLC', 'invoice_number': '010500'}}
        V.scan_inbox()
        self.assertEqual(V.inbox()[0]['status'], 'received')
        tid, _ = V.add_tab('NOVEMBER 2026')
        row = V.add_row(tid, values={'vendor': 'SANCHEZ SOD'})
        V.set_cell(row['id'], 'inv_no', '10500')
        x = V.inbox()[0]
        self.assertEqual((x['status'], x['row_id']), ('inputted', row['id']))

    def test_unknown_sender_marked_as_vendor_is_remembered(self):
        self.mail.add('m1', 'ap@newsub.example', 'Invoice 1', 'a.pdf')
        self.fields = {'m1': {'sub_contractor': 'Brand New Paving', 'invoice_number': '1'}}
        V.scan_inbox()
        rec = V.inbox()[0]
        self.assertEqual(rec['status'], 'other')
        V.decide_received(rec['id'], 'vendor')
        self.mail.add('m2', 'ap@newsub.example', 'Invoice 2', 'b.pdf')
        self.fields['m2'] = {'sub_contractor': 'Brand New Paving', 'invoice_number': '2'}
        V.scan_inbox()
        self.assertEqual({x['inv_no']: x['status'] for x in V.inbox()}, {'1': 'received', '2': 'received'})

    # ── emails to Christian ──

    def test_invoice_never_entered_emails_christian(self):
        old = (V._now() - timedelta(days=4)).strftime('%Y-%m-%dT%H:%M:%SZ')
        self.mail.add('m1', 'billing@pelicanlawn.example', 'Invoice 46300', 'a.pdf', received=old)
        self.mail.add('m2', 'billing@pelicanlawn.example', 'Invoice 46301', 'b.pdf')
        self.fields = {'m1': {'sub_contractor': 'Pelican Lawn', 'invoice_number': '46300', 'invoice_total': 300},
                       'm2': {'sub_contractor': 'Pelican Lawn', 'invoice_number': '46301', 'invoice_total': 301}}
        self.mail.inbox[1] = (self.mail.inbox[1][0], dict(self.mail.inbox[1][1],
                              receivedDateTime=V._now().strftime('%Y-%m-%dT%H:%M:%SZ')), 'b.pdf')
        V.scan_inbox()
        out = V.alert_not_inputted()
        self.assertEqual((out['sent'], out['count']), (True, 1))
        self.assertEqual(self.mail.sent[0]['to'], ['christian@example.com'])
        self.assertIn('46300', self.mail.sent[0]['body'])
        self.assertNotIn('46301', self.mail.sent[0]['body'])
        # Not again the next hour...
        self.assertFalse(V.alert_not_inputted()['sent'])
        # ...but again a week later if it's still not entered.
        conn = sqlite3.connect(A.DB_PATH)
        conn.execute("UPDATE vib_received SET alerted_at=?", ((V._now() - timedelta(days=8)).strftime('%Y-%m-%d %H:%M:%S'),))
        conn.commit()
        conn.close()
        self.assertTrue(V.alert_not_inputted()['sent'])
        self.assertEqual(len(self.mail.sent), 2)

    def test_jobber_paid_emails_christian_once(self):
        self.jobber.add('J1', '36437', status='awaiting_payment', total=56850)
        row = V.tab_rows(tab_id('SEPTEMBER 2026'))[0]
        self.assertEqual(V.suggest_jobber_number(row), '36437')
        self.login()
        found = self.c.get('/vendor-invoices/api/jobber/search?q=36437').get_json()['invoices']
        self.assertEqual(found[0]['number'], '36437')
        j = self.c.post('/vendor-invoices/api/jobber/link', json={'id': row['id'], 'jobber_id': 'J1'}).get_json()
        self.assertTrue(j['success'])
        self.assertFalse(j['already_paid'])
        self.assertEqual(V.check_jobber_paid()['paid'], 0)
        self.assertEqual(self.mail.sent, [])
        self.jobber.add('J1', '36437', status='paid', total=56850)
        out = V.check_jobber_paid()
        self.assertEqual((out['paid'], out['emailed']), (1, 1))
        self.assertIn('Paid in Jobber', self.mail.sent[0]['subject'])
        self.assertIn('46077', self.mail.sent[0]['subject'])
        self.assertEqual(V.check_jobber_paid()['checked'], 0)
        self.assertEqual(len(self.mail.sent), 1)
        linked = [r for r in V.tab_rows(tab_id('SEPTEMBER 2026')) if r['id'] == row['id']][0]['jobber']
        self.assertTrue(linked['paid_at'] and linked['paid_email_at'])
        V.unlink_jobber(row['id'])

    def test_linking_an_already_paid_invoice_asks_before_emailing(self):
        self.jobber.add('J2', '36550', status='paid')
        row = V.tab_rows(tab_id('OCTOBER 2026'))[0]
        out = V.link_jobber(row['id'], 'J2')
        self.assertTrue(out['already_paid'])
        self.assertEqual(self.mail.sent, [])
        V.unlink_jobber(row['id'])
        out = V.link_jobber(row['id'], 'J2', notify=True)
        self.assertEqual(len(self.mail.sent), 1)
        V.unlink_jobber(row['id'])

    def test_jobber_is_only_read(self):
        V._jobber = self._jobber_fn
        with self.assertRaises(RuntimeError):
            V._jobber('mutation { invoiceCreate { invoice { id } } }')


if __name__ == '__main__':
    unittest.main()
