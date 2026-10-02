"""
Tests for the Pumps app (pumps.py, pump_reports.py).

    python -m unittest tests.test_pumps -v

Runs against a throwaway database. Jobber and Claude are never called: Jobber
is replaced by a fake that records every request, and documents are "read"
from canned text. All names below are made up.
"""
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix='pumps_test_')
os.environ.update(SECRET_KEY='test-secret-key-0123456789abcdef-pumps', DATA_DIR=TMP, PUMPS_AUTO_SCAN='false',
                  OPENCLAW_API_KEY='test-openclaw-key', WEBSITE_URL='https://office.example.com')
os.environ.pop('ANTHROPIC_API_KEY', None)
os.environ.pop('JOBBER_API_TOKEN', None)

# The preview's sheet rows, to check they become items when the app starts.
_db = sqlite3.connect(os.path.join(TMP, 'po_requests.db'))
_db.execute('''CREATE TABLE IF NOT EXISTS pump_invoices (id INTEGER PRIMARY KEY AUTOINCREMENT, po_number TEXT,
               entry_date TEXT, vendor TEXT, job_name TEXT, description TEXT, approved_by TEXT,
               jobber_request_made TEXT, vendor_quote_amount REAL, vendor_invoice_amount REAL,
               vendor_invoice_number TEXT, sei_invoice_number TEXT, amount REAL, notes TEXT, month_tab TEXT,
               source TEXT, email_uid TEXT, created_at TEXT, updated_at TEXT)''')
_db.execute('''INSERT INTO pump_invoices (po_number, entry_date, vendor, job_name, description, vendor_quote_amount,
               vendor_invoice_amount, vendor_invoice_number) VALUES ('0290', '2026-06-03', 'Wettech',
               'Old Sheet Lakes HOA', 'Replace transducer', 900, 900, '28001')''')
_db.commit()
_db.close()

import app as A  # noqa: E402
import pumps as P  # noqa: E402
import pump_reports as R  # noqa: E402
from docx import Document  # noqa: E402

P.ANTHROPIC_API_KEY = ''
A.app.config['TESTING'] = True


def make_report(customer='Stahlman-Lakeside Pines HOA', location='Pump #2', tech='Casey Rivera'):
    """A Wettech-style Word report, laid out like the real ones."""
    d = Document()
    for line in ('Water Equipment Technologies of Southwest Florida LLC',
                 'State of Florida Certified Plumbing Contractor #CFC1429137',
                 '451 interstate Court - Sarasota, FL  34240',
                 'Phone 941-232-4629   FAX 941-371-5151      EMAIL wettec@verizon.net', ''):
        d.add_paragraph(line)
    d.add_paragraph('IRRIGATION PUMP SYSTEM REPORT')
    t = d.add_table(rows=1, cols=4)
    for cell, text in zip(t.rows[0].cells, ('DATE', '9-12-2026', 'TIME', '0930')):
        cell.text = text
    t = d.add_table(rows=1, cols=4)
    for cell, text in zip(t.rows[0].cells, ('CUSTOMER', customer, 'LOCATION', location)):
        cell.text = text
    t = d.add_table(rows=2, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = '√', 'CHECK ALL ELECTRICAL CONNECTIONS'
    t.rows[1].cells[0].text, t.rows[1].cells[1].text = '√', 'CLEAN SCREENS'
    d.add_paragraph('COMMENTS:')
    c = d.add_table(rows=1, cols=1)
    p = c.rows[0].cells[0].paragraphs[0]
    p.add_run(f'{tech.split()[0]} found the intake screen clogged. ')
    p.add_run('Wettech recommends a new ')
    p.add_run('check valve. Call 941-232-4629.')
    sig = d.add_table(rows=1, cols=2)
    sig.rows[0].cells[0].text, sig.rows[0].cells[1].text = 'Service Technician Signature', tech
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def extraction(kind, number, po='', client='Lakeside Pines', subtotal=1000.0, tax=65.0, wo='', items=None):
    """What Claude hands back for a quote or bill."""
    items = items if items is not None else [
        {'name': 'Replace check valve', 'description': 'Furnish and install 6" check valve. As per quotation.',
         'quantity': 1, 'unit_price': subtotal, 'amount': subtotal, 'taxable': True, 'is_tax': False},
        {'name': 'Sales Tax 6.5%', 'description': 'Sales Tax 6.5%', 'quantity': None, 'unit_price': None,
         'amount': tax, 'taxable': False, 'is_tax': True}]
    return {'kind': kind, 'vendor': 'Wettech', 'doc_number': number, 'doc_date': '2026-09-20', 'po_number': po,
            'ordered_by': '', 'wo_number': wo, 'quote_reference': '', 'client_name': client, 'site': '',
            'category': 'repair', 'description': 'Replace check valve', 'line_items': items,
            'subtotal': subtotal, 'tax': tax, 'total': round(subtotal + tax, 2), 'notes': ''}


class FakeJobber:
    """Stands in for Jobber: records every query and answers the ones Pumps sends."""

    def __init__(self, invoice_status='draft', quote_status='draft', properties=None):
        self.calls = []
        self.invoice_status = invoice_status
        self.quote_status = quote_status
        self.properties = properties if properties is not None else [
            {'id': 'P1', 'address': {'street1': '100 Lakeside Dr', 'city': 'Naples'}}]

    def __call__(self, query, variables=None):
        P.check_mutation_allowed(query)  # the real guard still runs
        self.calls.append((query, variables))
        if 'invoiceCreate' in query:
            return {'invoiceCreate': {'invoice': {'id': 'INV1', 'invoiceNumber': 5001,
                                                  'invoiceStatus': self.invoice_status,
                                                  'jobberWebUri': 'https://secure.getjobber.com/invoices/1'},
                                      'userErrors': []}}
        if 'quoteCreate(' in query:
            return {'quoteCreate': {'quote': {'id': 'Q1', 'quoteNumber': 812, 'quoteStatus': self.quote_status,
                                              'jobberWebUri': 'https://secure.getjobber.com/quotes/1'},
                                    'userErrors': []}}
        if 'client(id' in query:
            return {'client': {'id': variables['id'], 'name': 'Lakeside Pines HOA',
                               'properties': self.properties, 'jobs': {'nodes': []}}}
        if 'jobCreateNote' in query:
            if 'attachments' in json.dumps(variables):
                raise P.JobberError("Argument 'attachments' is invalid")
            return {'jobCreateNote': {'jobNote': {'id': 'NOTE1'}, 'userErrors': []}}
        if 'clients(' in query:
            return {'clients': {'nodes': [
                {'id': 'C1', 'name': 'Lakeside Pines HOA c/o Example Management', 'isLead': False, 'isArchived': False},
                {'id': 'C2', 'name': 'Lakeside Pines - Work Orders', 'isLead': True, 'isArchived': False}]}}
        return {}


class PumpsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.texts = {}
        cls.extracts = {}
        cls._orig = (P.extract_text, P._claude_extract, P.jobber_gql)
        real_extract = P.extract_text

        def fake_extract(name, data):
            if name in cls.texts:
                return cls.texts[name]
            if name in cls.extracts:
                return f'Document text for {name}'
            return real_extract(name, data)
        P.extract_text = fake_extract
        P._claude_extract = lambda text, sender='', subject='', filename='': cls.extracts.get(filename)

    @classmethod
    def tearDownClass(cls):
        P.extract_text, P._claude_extract, P.jobber_gql = cls._orig
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        self.c = A.app.test_client()
        A.app.config['WTF_CSRF_ENABLED'] = False
        with self.c.session_transaction() as s:
            s['username'], s['role'], s['full_name'] = 'office1', 'office', 'Office Tester'

    def upload(self, name, data=b'%PDF-1.4 fake', kind=None, case_id=None):
        if not name.endswith('.docx'):
            data = data + name.encode()  # a distinct file per name
        form = {'file': (io.BytesIO(data), name)}
        if kind:
            form['kind'] = kind
        if case_id:
            form['case_id'] = str(case_id)
        r = self.c.post('/pumps/api/docs', data=form, content_type='multipart/form-data')
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return r.get_json()['results'][0]

    def case(self, cid):
        return self.c.get(f'/pumps/api/cases/{cid}').get_json()['case']

    # ── reports ─────────────────────────────────────────────────────────────
    def test_rebrand_report(self):
        out, info = R.rebrand_report(make_report())
        text = '\n'.join(R.read_report(out)['lines'])
        for gone in ('Water Equipment', 'Wettech', 'CFC1429137', '941-232-4629', 'wettec', 'Casey', 'Rivera',
                     'Stahlman-Lakeside', 'Technician Signature'):
            self.assertNotIn(gone.lower(), text.lower(), gone)
        self.assertIn('STAHLMAN – ENGLAND, INC.', text)
        self.assertIn('IRRIGATION PUMP SYSTEM REPORT', text)
        self.assertIn('Lakeside Pines HOA', text)
        self.assertIn('Our technician found the intake screen clogged', text)
        self.assertIn('Stahlman-England Irrigation recommends a new check valve', text)
        self.assertEqual(info['technicians_removed'], ['Casey Rivera'])
        self.assertEqual(info['leftovers'], [])
        # The letterhead's logo came along.
        self.assertTrue(any('image' in rel.reltype for rel in Document(io.BytesIO(out)).part.rels.values()))

    def test_read_report_fields(self):
        f = R.read_report(make_report())
        self.assertEqual((f['customer'], f['location'], f['date']), ('Lakeside Pines HOA', 'Pump #2', '9-12-2026'))

    def test_report_upload_files_item_and_logs_to_jobber(self):
        res = self.upload('9-12 Lakeside Pines.docx', make_report(customer='Stahlman-Bayview Palms HOA'))
        self.assertEqual(res['kind'], 'report')
        case = self.case(res['case_id'])
        self.assertEqual(case['category'], 'maintenance')
        self.assertEqual(case['client_name'], 'Bayview Palms HOA')
        steps = {s['key']: s for s in case['step_list']}
        self.assertTrue(steps['work_done'].get('at'))
        self.assertTrue(steps['scheduled'].get('at'), 'work done implies it was scheduled')
        self.assertEqual(case['stage'], 'vendor_bill')
        # Branded file downloads with our name on it.
        r = self.c.get(f"/pumps/api/docs/{res['doc_id']}/file?version=branded")
        self.assertEqual(r.status_code, 200)
        self.assertIn('Stahlman-England', r.headers['Content-Disposition'])
        # Log it on a job; Jobber refuses the attachment, so it falls back to a link.
        fake = FakeJobber()
        P.jobber_gql = fake
        r = self.c.post(f"/pumps/api/docs/{res['doc_id']}/report_note",
                        json={'target_type': 'job', 'target_id': 'JOB9'})
        body = r.get_json()
        self.assertTrue(body['success'], body)
        self.assertFalse(body['note']['note_attached_file'])
        note_calls = [v for q, v in fake.calls if 'jobCreateNote' in q]
        self.assertEqual(len(note_calls), 2)
        self.assertNotIn('attachments', note_calls[-1]['input'])
        self.assertIn('Pump report - IRRIGATION PUMP SYSTEM REPORT', note_calls[-1]['input']['message'])
        message = note_calls[-1]['input']['message']
        for gone in ('Casey', 'Rivera', 'Wettech', 'Water Equipment', '941-232-4629', 'wettec', 'Stahlman-Bayview'):
            self.assertNotIn(gone, message)
        self.assertIn('Bayview Palms HOA', message)
        self.assertIn('Our technician found the intake screen clogged', message)
        steps = {s['key']: s for s in self.case(res['case_id'])['step_list']}
        self.assertTrue(steps['report_logged'].get('at'))

    # ── quotes, bills, issues ───────────────────────────────────────────────
    def test_quote_then_matching_bill_checks_itself(self):
        self.extracts['q-0322.pdf'] = extraction('quote', 'Q-77', po='PO322', subtotal=1500)
        self.extracts['b-0322.pdf'] = extraction('bill', '29100', po='0322', subtotal=1500, tax=97.5)
        q = self.upload('q-0322.pdf')
        b = self.upload('b-0322.pdf')
        self.assertEqual(q['case_id'], b['case_id'], 'bill filed by PO number onto the quote\'s item')
        case = self.case(b['case_id'])
        self.assertEqual(case['compare']['state'], 'match')
        steps = {s['key']: s for s in case['step_list']}
        self.assertTrue(steps['bill_checked'].get('at'))
        self.assertEqual([i for i in case['issues'] if not i['resolved_at']], [])

    def test_bill_over_quote_raises_issue_until_resolved(self):
        self.extracts['q-0400.pdf'] = extraction('quote', 'Q-80', po='PO400', client='Heron Bay', subtotal=2000)
        self.extracts['b-0400.pdf'] = extraction('bill', '29200', po='PO 400', client='Heron Bay', subtotal=2250)
        self.upload('q-0400.pdf')
        b = self.upload('b-0400.pdf')
        case = self.case(b['case_id'])
        self.assertEqual(case['compare']['state'], 'over')
        open_issues = [i for i in case['issues'] if not i['resolved_at']]
        self.assertEqual(len(open_issues), 1)
        self.assertIn('$250.00 more than the quote', open_issues[0]['message'])
        summary = self.c.get('/pumps/api/summary').get_json()
        self.assertTrue(any(i['case_id'] == b['case_id'] for i in summary['queue']['issues']))
        r = self.c.post(f"/pumps/api/issues/{open_issues[0]['id']}/resolve", json={'resolution': ''})
        self.assertEqual(r.status_code, 400, 'a resolution has to say how')
        self.c.post(f"/pumps/api/issues/{open_issues[0]['id']}/resolve",
                    json={'resolution': 'Extra fittings approved by the manager'})
        case = self.case(b['case_id'])
        self.assertEqual([i for i in case['issues'] if not i['resolved_at']], [])
        self.assertTrue({s['key']: s for s in case['step_list']}['bill_checked'].get('at'))

    def test_sheet_bill_amount_is_checked(self):
        cid = self.c.post('/pumps/api/sheet/save', json={'month': 'October 2026', 'client_name': 'Egret Run',
                                                          'vendor_quote_amount': '700',
                                                          'vendor_bill_amount': '760'}).get_json()['id']
        case = self.case(cid)
        self.assertEqual(case['compare']['state'], 'over')
        self.assertTrue(any(i['kind'] == 'amount_mismatch' for i in case['issues']))

    def test_bill_without_quote_raises_issue(self):
        self.extracts['b-noquote.pdf'] = extraction('bill', '29300', client='Coral Isles', subtotal=500)
        b = self.upload('b-noquote.pdf')
        case = self.case(b['case_id'])
        self.assertEqual(case['compare']['state'], 'no_quote')
        self.assertTrue(any(i['kind'] == 'no_quote' and not i['resolved_at'] for i in case['issues']))

    def test_bill_matched_by_client_name(self):
        self.extracts['q-name.pdf'] = extraction('quote', 'Q-90', client='The Reserve at Glenwood', subtotal=800)
        self.extracts['b-name.pdf'] = extraction('bill', '29400', client='Reserve at Glenwood - Lee County',
                                                 subtotal=800)
        q = self.upload('q-name.pdf')
        b = self.upload('b-name.pdf')
        self.assertEqual(q['case_id'], b['case_id'])

    def test_unread_bill_waits_in_inbox_for_review(self):
        self.texts['scan.pdf'] = ''
        res = self.upload('scan.pdf', kind='bill')
        self.assertIsNone(res['case_id'])
        self.assertIn('enter the details by hand', res['review'])
        self.c.patch(f"/pumps/api/docs/{res['doc_id']}", json={'client_name': 'Palm Cove', 'subtotal': 300,
                                                                'total': 319.5, 'doc_number': '29500', 'file': True})
        doc = self.c.get(f"/pumps/api/docs/{res['doc_id']}").get_json()['doc']
        self.assertTrue(doc['case_id'])

    def test_read_again_once_claude_is_back(self):
        # Claude is down: the basic reader marks both for review and leaves them in the Inbox.
        for name in ('Inv_29041_from_Water_Equipment.pdf', 'Inv_29042_from_Water_Equipment.pdf'):
            self.texts[name] = 'INVOICE\nWater Equipment Technologies\nTotal $1,200.00'
        a = self.upload('Inv_29041_from_Water_Equipment.pdf')
        b = self.upload('Inv_29042_from_Water_Equipment.pdf')
        for res in (a, b):
            self.assertIsNone(res['case_id'])
            self.assertIn('without Claude', res['review'])
        # Claude is back.
        for name, num in (('Inv_29041_from_Water_Equipment.pdf', '29041'), ('Inv_29042_from_Water_Equipment.pdf', '29042')):
            self.extracts[name] = extraction('bill', num, po='PO950', client='Osprey Point', subtotal=1126.76)
            self.texts.pop(name)
        r = self.c.post(f"/pumps/api/docs/{a['doc_id']}/reread", json={})
        body = r.get_json()
        self.assertTrue(body['success'], body)
        self.assertEqual(body['kind'], 'bill')
        self.assertTrue(body['case_id'], 'filed onto an item once read cleanly')
        doc = self.c.get(f"/pumps/api/docs/{a['doc_id']}").get_json()['doc']
        self.assertEqual((doc['extracted_by'], doc['review_reason'], doc['doc_number']), ('claude', '', '29041'))
        self.assertEqual(self.case(body['case_id'])['vendor_bill_number'], '29041')
        # Already on an item: not read again over the office's work.
        self.assertEqual(self.c.post(f"/pumps/api/docs/{a['doc_id']}/reread", json={}).status_code, 400)
        # The next scan picks up the rest by itself.
        P.ANTHROPIC_API_KEY, key = 'test', P.ANTHROPIC_API_KEY
        try:
            done = P.reread_pending('test')
        finally:
            P.ANTHROPIC_API_KEY = key
        self.assertIn(b['doc_id'], [d['doc_id'] for d in done])
        self.assertTrue(self.c.get(f"/pumps/api/docs/{b['doc_id']}").get_json()['doc']['case_id'])

    def test_same_file_twice_is_skipped(self):
        self.extracts['dup.pdf'] = extraction('quote', 'Q-91', client='Dup Lakes', subtotal=100)
        self.upload('dup.pdf')
        self.assertIn('already have', self.upload('dup.pdf').get('skipped', ''))

    # ── Jobber: drafts only, never sent ──────────────────────────────────────
    def test_guard_blocks_everything_but_drafts_and_notes(self):
        for q in ('mutation { invoiceSend(invoiceId: "1") { invoice { id } } }',
                  'mutation M($id: EncodedId!) { invoiceMarkAsSent(id: $id) { invoice { id } } }',
                  'mutation { x: invoiceMarkAsSent(id: "1") { invoice { id } } }',
                  'mutation { invoiceCreate(input: {}) { invoice { id } } quoteSend(quoteId: "1") { quote { id } } }',
                  'mutation { clientDelete(clientId: "1") { userErrors { message } } }'):
            with self.assertRaises(P.JobberError, msg=q):
                P.check_mutation_allowed(q)
        P.check_mutation_allowed(P.INVOICE_CREATE)
        P.check_mutation_allowed(P.QUOTE_CREATE)
        P.check_mutation_allowed('query { clients(first: 1) { nodes { id } } }')
        for target in P.NOTE_MUTATION.values():
            P.check_mutation_allowed(f'mutation N($id: EncodedId!, $input: {target[2]}!) {{ {target[0]}({target[1]}: $id, '
                                     f'input: $input) {{ {target[3]} {{ id }} userErrors {{ message }} }} }}')

    def test_no_send_mutation_anywhere_in_the_code(self):
        for name in ('pumps.py', 'pump_reports.py', 'pumps_page.py'):
            with open(os.path.join(ROOT, name)) as f:
                src = f.read()
            for word in ('invoiceSend', 'quoteSend', 'sendInvoice'):
                self.assertNotIn(word, src, f'{word} in {name}')
            # invoiceMarkAsSent may only be named in comments, never in a query.
            self.assertNotRegex(src, r"['\"][^'\"]*invoiceMarkAsSent", name)

    def test_draft_invoice_from_bill(self):
        self.extracts['q-0500.pdf'] = extraction('quote', 'Q-95', po='PO500', client='Lakeside Pines', subtotal=1803.81)
        self.extracts['b-0500.pdf'] = extraction('bill', '29600', po='PO500', client='Lakeside Pines',
                                                 subtotal=1803.81, tax=117.25)
        self.upload('q-0500.pdf')
        b = self.upload('b-0500.pdf')
        fake = FakeJobber()
        P.jobber_gql = fake
        r = self.c.post(f"/pumps/api/docs/{b['doc_id']}/invoice", json={})
        body = r.get_json()
        self.assertTrue(body['success'], body)
        self.assertEqual(body['invoice']['invoice_status'], 'draft')
        creates = [v for q, v in fake.calls if 'invoiceCreate' in q]
        self.assertEqual(len(creates), 1)
        inp = creates[0]['input']
        self.assertEqual(inp['clientId'], 'C1', 'the clear best client, not the work-orders lead')
        self.assertEqual(len(inp['lineItems']), 1, 'sales tax line left off')
        self.assertEqual(inp['lineItems'][0]['unitPrice'], 1803.81)
        self.assertNotIn('quotation', inp['lineItems'][0]['description'].lower())
        self.assertEqual(inp['tax'], {'taxCalculationMethod': 'EXCLUSIVE'})
        self.assertFalse(any(word in q for q, _ in fake.calls for word in ('Send', 'MarkAsSent')))
        case = self.case(b['case_id'])
        self.assertEqual(case['sei_invoice_number'], '5001')
        self.assertTrue({s['key']: s for s in case['step_list']}['invoice_drafted'].get('at'))
        # A second draft for the same bill is refused.
        r = self.c.post(f"/pumps/api/docs/{b['doc_id']}/invoice", json={'client_id': 'C1'})
        self.assertEqual(r.status_code, 400)

    def test_non_draft_status_from_jobber_raises_issue(self):
        self.extracts['b-0600.pdf'] = extraction('bill', '29700', po='PO600', client='Sunset Cove', subtotal=400)
        b = self.upload('b-0600.pdf')
        P.jobber_gql = FakeJobber(invoice_status='awaiting_payment')
        body = self.c.post(f"/pumps/api/docs/{b['doc_id']}/invoice", json={'client_id': 'C9'}).get_json()
        self.assertTrue(body['success'], body)
        self.assertTrue(any(i['kind'] == 'not_draft' and not i['resolved_at'] for i in self.case(b['case_id'])['issues']))

    def test_ambiguous_client_asks_a_person(self):
        self.extracts['b-amb.pdf'] = extraction('bill', '29800', client='Twin Oaks', subtotal=100)
        b = self.upload('b-amb.pdf')

        def two_equal(query, variables=None):
            return {'clients': {'nodes': [{'id': 'X1', 'name': 'Twin Oaks North'}, {'id': 'X2', 'name': 'Twin Oaks South'}]}}
        P.jobber_gql = two_equal
        r = self.c.post(f"/pumps/api/docs/{b['doc_id']}/invoice", json={})
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.get_json()['needs_client'])

    def test_draft_quote_from_vendor_quote(self):
        self.extracts['q-0800.pdf'] = extraction('quote', 'Q-120', po='PO800', client='Lakeside Pines', subtotal=2450)
        q = self.upload('q-0800.pdf')
        cid = q['case_id']
        queue = self.c.get('/pumps/api/summary').get_json()['queue']
        self.assertIn(q['doc_id'], [d['id'] for d in queue['quotes_to_draft']])
        fake = FakeJobber()
        P.jobber_gql = fake
        body = self.c.post(f"/pumps/api/docs/{q['doc_id']}/quote", json={}).get_json()
        self.assertTrue(body['success'], body)
        self.assertEqual(body['quote']['quote_status'], 'draft')
        creates = [v for qq, v in fake.calls if 'quoteCreate(' in qq]
        self.assertEqual(len(creates), 1)
        attrs = creates[0]['attributes']
        self.assertEqual(attrs['clientId'], 'C1', 'the clear best client, not the work-orders lead')
        self.assertEqual(attrs['propertyId'], 'P1', "the client's only property")
        self.assertEqual(len(attrs['lineItems']), 1, 'sales tax line left off')
        self.assertEqual(attrs['lineItems'][0]['unitPrice'], 2450)
        self.assertNotIn('quotation', attrs['lineItems'][0]['description'].lower())
        self.assertIn('PO800', attrs['title'])
        self.assertFalse(any(word in qq for qq, _ in fake.calls for word in ('Send', 'MarkAsSent')))
        case = self.case(cid)
        self.assertEqual(case['jobber']['quote']['number'], '812')
        steps = {s['key']: s for s in case['step_list']}
        self.assertFalse(steps['client_quote'].get('at'), 'a draft is not "sent to client"')
        queue = self.c.get('/pumps/api/summary').get_json()['queue']
        self.assertNotIn(q['doc_id'], [d['id'] for d in queue['quotes_to_draft']])
        # A second draft for the same vendor quote is refused.
        r = self.c.post(f"/pumps/api/docs/{q['doc_id']}/quote", json={'client_id': 'C1', 'property_id': 'P1'})
        self.assertEqual(r.status_code, 400)
        # When the office sends it from Jobber, and the client approves, the steps tick themselves.
        conn = P._conn()
        try:
            conn.execute("INSERT INTO pump_jobber_items (jobber_id, kind, number, title, status, updated_at) "
                         "VALUES ('Q1', 'quote', '812', 'Pump service', 'awaiting_response', '2026-10-03T10:00:00Z')")
            P._follow_quotes(conn)
            conn.commit()
        finally:
            conn.close()
        steps = {s['key']: s for s in self.case(cid)['step_list']}
        self.assertEqual(steps['client_quote'].get('at'), '2026-10-03')
        self.assertFalse(steps['client_approved'].get('at'))
        conn = P._conn()
        try:
            conn.execute("UPDATE pump_jobber_items SET status='approved', updated_at='2026-10-06T09:00:00Z' "
                         "WHERE jobber_id='Q1'")
            P._follow_quotes(conn)
            conn.commit()
        finally:
            conn.close()
        steps = {s['key']: s for s in self.case(cid)['step_list']}
        self.assertEqual(steps['client_approved'].get('at'), '2026-10-06')

    def test_draft_quote_asks_which_property(self):
        self.extracts['q-0810.pdf'] = extraction('quote', 'Q-121', po='PO810', client='Lakeside Pines', subtotal=300)
        q = self.upload('q-0810.pdf')
        P.jobber_gql = FakeJobber(properties=[{'id': 'P1', 'address': {'street1': 'North gate'}},
                                              {'id': 'P2', 'address': {'street1': 'South gate'}}])
        r = self.c.post(f"/pumps/api/docs/{q['doc_id']}/quote", json={'client_id': 'C1'})
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.get_json()['needs_property'])
        self.assertEqual([p['id'] for p in r.get_json()['properties']], ['P1', 'P2'])
        r = self.c.post(f"/pumps/api/docs/{q['doc_id']}/quote", json={'client_id': 'C1', 'property_id': 'P2'})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

    def test_non_draft_quote_status_raises_issue(self):
        self.extracts['q-0820.pdf'] = extraction('quote', 'Q-122', po='PO820', client='Sunset Cove', subtotal=400)
        q = self.upload('q-0820.pdf')
        P.jobber_gql = FakeJobber(quote_status='awaiting_response')
        body = self.c.post(f"/pumps/api/docs/{q['doc_id']}/quote", json={'client_id': 'C9', 'property_id': 'P9'}).get_json()
        self.assertTrue(body['success'], body)
        self.assertTrue(any(i['kind'] == 'not_draft' and not i['resolved_at'] for i in self.case(q['case_id'])['issues']))

    def test_openclaw_cannot_draft_client_quotes(self):
        self.extracts['q-0830.pdf'] = extraction('quote', 'Q-123', po='PO830', client='Lakeside Pines', subtotal=500)
        q = self.upload('q-0830.pdf')
        fake = FakeJobber()
        P.jobber_gql = fake
        r = A.app.test_client().post(f"/api/pumps/docs/{q['doc_id']}/quote", json={'client_id': 'C1', 'property_id': 'P1'},
                                     headers={'Authorization': 'Bearer test-openclaw-key'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(fake.calls, [])

    def test_vendor_bill_due_once_client_pays(self):
        self.extracts['q-0900.pdf'] = extraction('quote', 'Q-130', po='PO900', client='Lakeside Pines', subtotal=900)
        self.extracts['b-0900.pdf'] = extraction('bill', '30100', po='PO900', client='Lakeside Pines', subtotal=900)
        self.upload('q-0900.pdf')
        b = self.upload('b-0900.pdf')
        cid = b['case_id']
        self.assertEqual(self.case(cid)['vendor_pay']['state'], 'unpaid')
        P.jobber_gql = FakeJobber()
        self.assertTrue(self.c.post(f"/pumps/api/docs/{b['doc_id']}/invoice", json={'client_id': 'C1'}).get_json()['success'])

        def jobber_says(status):
            conn = P._conn()
            try:
                conn.execute("INSERT INTO pump_jobber_items (jobber_id, kind, number, title, status) "
                             "VALUES ('INV1', 'invoice', '5001', 'Pump service', ?) "
                             "ON CONFLICT(jobber_id) DO UPDATE SET status=excluded.status", (status,))
                P._follow_invoices(conn)
                conn.commit()
            finally:
                conn.close()

        def to_pay():
            return [c['id'] for c in self.c.get('/pumps/api/summary').get_json()['queue']['vendor_bills_to_pay']]
        jobber_says('awaiting_payment')
        self.assertEqual(self.case(cid)['vendor_pay']['state'], 'unpaid', 'sent, not paid yet')
        self.assertNotIn(cid, to_pay())
        # The item closes before the client pays; the alert must still come.
        conn = P._conn()
        try:
            conn.execute("UPDATE pump_cases SET status='closed' WHERE id=?", (cid,))
            conn.commit()
        finally:
            conn.close()
        jobber_says('paid')
        case = self.case(cid)
        self.assertEqual(case['vendor_pay']['state'], 'due')
        self.assertIn(cid, to_pay())
        self.assertTrue(any(e['action'] == 'pay vendor' for e in case['events']))
        # OpenClaw may not say a vendor was paid.
        r = A.app.test_client().patch(f'/api/pumps/cases/{cid}', json={'vendor_paid_on': '2026-10-08'},
                                      headers={'Authorization': 'Bearer test-openclaw-key'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.c.patch(f'/pumps/api/cases/{cid}', json={'vendor_paid_on': 'soon'}).status_code, 400)
        r = self.c.patch(f'/pumps/api/cases/{cid}', json={'vendor_paid_on': '2026-10-08'})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        pay = r.get_json()['case']['vendor_pay']
        self.assertEqual((pay['state'], pay['paid_on'], pay['paid_by']), ('paid', '2026-10-08', 'Office Tester'))
        self.assertNotIn(cid, to_pay())
        # Undo.
        self.c.patch(f'/pumps/api/cases/{cid}', json={'vendor_paid_on': ''})
        self.assertIn(cid, to_pay())

    # ── who can get in ───────────────────────────────────────────────────────
    def test_access(self):
        anon = A.app.test_client()
        self.assertEqual(anon.get('/pumps/api/summary').status_code, 401)
        self.assertEqual(anon.get('/api/pumps/summary').status_code, 401)
        self.assertEqual(anon.get('/api/pumps/summary', headers={'Authorization': 'Bearer wrong'}).status_code, 401)
        self.assertEqual(anon.get('/api/pumps/summary',
                                  headers={'Authorization': 'Bearer test-openclaw-key'}).status_code, 200)
        tech = A.app.test_client()
        with tech.session_transaction() as s:
            s['username'], s['role'] = 'tech1', 'technician'
        self.assertEqual(tech.get('/pumps/api/summary').status_code, 401)
        self.assertEqual(tech.get('/pumps').status_code, 302)
        self.assertEqual(self.c.get('/pumps').status_code, 200)

    def test_office_writes_need_csrf_but_openclaw_does_not(self):
        A.app.config['WTF_CSRF_ENABLED'] = True
        try:
            r = self.c.post('/pumps/api/cases', json={'title': 'CSRF probe'})
            self.assertIn(r.status_code, (400, 302), 'refused (the app redirects on a bad CSRF token)')
            A.app.config['WTF_CSRF_ENABLED'] = False
            self.assertEqual(self.c.get('/pumps/api/cases?status=all&q=CSRF probe').get_json()['cases'], [])
            A.app.config['WTF_CSRF_ENABLED'] = True
            bot = A.app.test_client()
            r = bot.post('/api/pumps/cases', json={'title': 'Pump #3 tripping', 'client_name': 'Gulf Harbor'},
                         headers={'Authorization': 'Bearer test-openclaw-key'})
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
            self.assertEqual(r.get_json()['case']['source'], 'openclaw')
        finally:
            A.app.config['WTF_CSRF_ENABLED'] = False

    def test_openclaw_cannot_make_office_decisions(self):
        bot = A.app.test_client()
        h = {'Authorization': 'Bearer test-openclaw-key'}
        self.extracts['q-0700.pdf'] = extraction('quote', 'Q-97', po='PO700', client='Marsh Landing', subtotal=1000)
        self.extracts['b-0700.pdf'] = extraction('bill', '29900', po='PO700', client='Marsh Landing', subtotal=1100)
        self.upload('q-0700.pdf')
        b = self.upload('b-0700.pdf')
        cid = b['case_id']
        issue = [i for i in self.case(cid)['issues'] if not i['resolved_at']][0]
        fake = FakeJobber()
        P.jobber_gql = fake
        r = bot.post(f"/api/pumps/docs/{b['doc_id']}/invoice", json={'client_id': 'C1'}, headers=h)
        self.assertEqual(r.status_code, 409, 'no draft while the bill is over the quote')
        self.assertEqual(fake.calls, [])
        self.assertEqual(bot.post(f"/api/pumps/issues/{issue['id']}/resolve", json={'resolution': 'fine'},
                                  headers=h).status_code, 403)
        self.assertEqual(bot.patch(f'/api/pumps/cases/{cid}', json={'steps': {'bill_checked': '2026-10-02'}},
                                   headers=h).status_code, 403)
        self.assertEqual(bot.patch(f'/api/pumps/cases/{cid}', json={'steps': {'closed': '2026-10-02'}},
                                   headers=h).status_code, 403)
        self.assertEqual(bot.post(f'/api/pumps/cases/{cid}/delete', json={}, headers=h).status_code, 403)
        # Ordinary bookkeeping is fine.
        self.assertEqual(bot.patch(f'/api/pumps/cases/{cid}', json={'note': 'Asked Wettech about the extra $100'},
                                   headers=h).status_code, 200)
        # Once the office resolves it, OpenClaw may draft.
        self.c.post(f"/pumps/api/issues/{issue['id']}/resolve", json={'resolution': 'Extra part approved'})
        r = bot.post(f"/api/pumps/docs/{b['doc_id']}/invoice", json={'client_id': 'C1'}, headers=h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

    def test_dashboard_tile_is_live(self):
        html = self.c.get('/dashboard').get_data(as_text=True)
        self.assertIn('href="/pumps"', html)
        folder = html.split('Features Coming Soon', 1)[1] if 'Features Coming Soon' in html else ''
        self.assertNotIn('/pumps"', folder)

    # ── sheet, checklist, SCADA ──────────────────────────────────────────────
    def test_old_sheet_rows_became_items(self):
        cases = self.c.get('/pumps/api/cases?status=all&q=Old Sheet').get_json()['cases']
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]['po_number'], '0290')
        self.assertEqual(cases[0]['compare']['state'], 'match')

    def test_sheet_edit_and_steps(self):
        r = self.c.post('/pumps/api/sheet/save', json={'month': 'October 2026', 'po_number': '0333',
                                                       'client_name': 'Mangrove Bay', 'vendor': 'Wettech',
                                                       'vendor_quote_amount': '$1,200.00'})
        cid = r.get_json()['id']
        case = self.case(cid)
        self.assertEqual(case['vendor_quote_amount'], 1200.0)
        self.assertTrue({s['key']: s for s in case['step_list']}['vendor_quote'].get('at'),
                        'an amount in the sheet ticks the step')
        self.c.patch(f'/pumps/api/cases/{cid}', json={'steps': {'vendor_quote': '2026-10-01', 'client_quote': 'na',
                                                                'client_approved': '2026-10-02'}})
        case = self.case(cid)
        self.assertEqual(case['stage'], 'scheduled')
        self.assertIn('mailto:', case['schedule_email'])
        summary = self.c.get('/pumps/api/summary').get_json()
        self.assertTrue(any(c['id'] == cid for c in summary['queue']['needs_scheduling']))
        r = self.c.get('/pumps/api/export.xlsx?month=October 2026')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data[:2] == b'PK')

    def test_scada_due_dates(self):
        conn = P._conn()
        rows = [('S1', 'job', '101', 'Estimate to Renew the SCADA Annual Cellular subcription', 'archived', 'one_off',
                 'CL1', 'Overdue Club', '2025-07-10T14:00:00Z'),
                ('S2', 'job', '102', 'Estimate to Renew the SCADA system- Driving Range', 'archived', 'one_off',
                 'CL2', 'Current Golf', '2026-08-01T14:00:00Z'),
                ('S3', 'job', '103', 'Estimate to Renew the SCADA system', 'archived', 'one_off', 'CL3',
                 'Due Soon School', '2025-11-18T02:10:39Z')]
        for jid, kind, num, title, status, jt, cid, cname, created in rows:
            conn.execute('''INSERT OR REPLACE INTO pump_jobber_items (jobber_id, kind, number, title, status, job_type,
                              client_id, client_name, created_at, completed_at, category)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                         (jid, kind, num, title, status, jt, cid, cname, created, created, 'scada'))
        P.rebuild_scada(conn)
        conn.commit()
        conn.close()
        today = P._today
        P._today = lambda: __import__('datetime').date(2026, 10, 2)
        try:
            rows = {r['client_name']: r for r in self.c.get('/pumps/api/scada').get_json()['scada']}
        finally:
            P._today = today
        self.assertEqual(rows['Overdue Club']['state'], 'overdue')
        self.assertEqual(rows['Current Golf']['state'], 'current')
        self.assertEqual(rows['Current Golf']['site'], 'Driving Range')
        self.assertEqual(rows['Due Soon School']['state'], 'due_soon')
        sid = rows['Overdue Club']['id']
        cid = self.c.post(f'/pumps/api/scada/{sid}', json={'action': 'renewal_item'}).get_json()['case_id']
        self.assertEqual(self.case(cid)['category'], 'scada')
        again = self.c.post(f'/pumps/api/scada/{sid}', json={'action': 'renewal_item'}).get_json()['case_id']
        self.assertEqual(cid, again, 'one renewal item at a time')

    def test_matching_helpers(self):
        self.assertGreater(P.similarity('Reserve at Estero - Lee County',
                                        'THE RESERVE AT ESTERO c/o ALLIANT PROPERTY MANAGEMENT, LLC.'), 0.95)
        self.assertGreater(P.similarity('Moritz HOA', 'St. Moritz C/O Suitor Middleton Cox & Associates'), 0.8)
        self.assertLess(P.similarity('Moritz HOA', 'Pebblebrook HOA'), 0.3)
        self.assertEqual(P.po_key('PO#0153'), '153')
        self.assertEqual(P.po_from_title('Service Call - WET***SC PUMP PO#0153'), '153')
        self.assertEqual(P.po_from_title('Pump Service call - PO322 Wttech'), '322')
        self.assertEqual(P._scada_site('Estimate to Renew the SCADA system-Dec 2023-Dec 2024'), '')
        self.assertEqual(P._scada_site('Scada Annual Renewal -Athletic Field'), 'Athletic Field')
        self.assertEqual(P._category('Pump Service call - PO322 Wttech'), 'pump')
        self.assertEqual(P._category('Service call - Diver to clean filter'), 'diver')
        self.assertEqual(P._category('SC- IRRIGATION'), '')

    def test_wettech_invoice_layout_without_claude(self):
        text = '''Invoice
Date Invoice #
of Southwest Florida LLC 9/30/2026 29067
451 Interstate Court
Phone # 941-232-4629 Fax # 941-371-5151
License #CFC1429137 office@wettec.biz
Bill To
Stahlman-England Irrigation
P.O. No. Terms
Andrea
Quantity Description Rate Amount
Sample Lakes - Lee County
Field service to furnish and install new 6" victaulic butterfly 1,803.81 1,803.81T
valve and couplings, pressurized and tested system. As per
quotation.
Sales Tax 6.5% 6.50% 117.25
Total $1,921.06
W/O No. 41105'''
        x = P._clean_extraction(P._regex_extract(text, 'office@wettec.biz'))
        self.assertEqual((x['kind'], x['doc_number'], x['doc_date'], x['vendor']), ('bill', '29067', '2026-09-30', 'Wettech'))
        self.assertEqual((x['po_number'], x['ordered_by'], x['wo_number']), ('', 'Andrea', '41105'))
        self.assertEqual((x['subtotal'], x['tax'], x['total']), (1803.81, 117.25, 1921.06))
        self.assertEqual(x['client_name'], 'Sample Lakes')
        self.assertEqual(len(x['line_items']), 1)
        self.assertTrue(x['line_items'][0]['taxable'])
        self.assertIn('pressurized and tested system', x['line_items'][0]['description'])

    def test_mailbox_scan(self):
        report = make_report(customer='Stahlman-Osprey Point HOA')
        self.extracts['Inv_31000.pdf'] = extraction('bill', '31000', po='PO777', client='Osprey Point', subtotal=250)
        self.texts['Inv_31000.pdf'] = 'Invoice ... office@wettec.biz'
        self.texts['menu.pdf'] = 'Lunch menu for Friday'
        mail = [('m1', {'from': {'emailAddress': {'address': 'office@wettec.biz'}}, 'subject': 'Report and invoice',
                        'receivedDateTime': '2026-10-01T12:00:00Z'}),
                ('m2', {'from': {'emailAddress': {'address': 'someone@example.com'}}, 'subject': 'Lunch',
                        'receivedDateTime': '2026-10-01T12:00:00Z'})]
        atts = {'m1': [('9-30 Osprey Point.docx', report), ('Inv_31000.pdf', b'%PDF fake 31000')],
                'm2': [('menu.pdf', b'%PDF menu')]}
        seen = {}

        def fetch(log_table, extensions, since):
            seen.update(log_table=log_table, extensions=extensions, since=since)
            return {'emails': mail, 'source': 'graph_api', 'diagnostics': {}}
        P.CFG.update(fetch_emails=fetch, graph_attachments=lambda uid: atts[uid], email_enabled=True)
        out = P.scan_mailbox()
        self.assertEqual(out['documents_added'], 2, out)
        self.assertEqual(out['skipped'], 1)
        self.assertIn('.docx', seen['extensions'])
        self.assertEqual(seen['log_table'], 'pump_email_scan_log')
        conn = P._conn()
        logged = {r[0] for r in conn.execute('SELECT email_uid FROM pump_email_scan_log')}
        conn.close()
        self.assertTrue({'m1', 'm2'} <= logged, 'every email is only looked at once')


if __name__ == '__main__':
    unittest.main(verbosity=2)
