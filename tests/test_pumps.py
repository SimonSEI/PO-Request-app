"""
Tests for the Pumps app (pumps.py, pump_reports.py).

    python -m unittest tests.test_pumps -v

Runs against a throwaway database. Jobber and Claude are never called: Jobber
is replaced by a fake that records every request, and documents are "read"
from canned text. All names below are made up.
"""
import atexit
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

    def __init__(self, invoice_status='draft', quote_status='draft', properties=None, clients=None, quote_lines=None):
        self.calls = []
        self.clients = clients
        self.quote_lines = quote_lines or []
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
        if 'quote(id' in query:
            return {'quote': {'quoteNumber': 812, 'lineItems': {'nodes': self.quote_lines}}}
        if 'quoteCreateNote' in query:
            return {'quoteCreateNote': {'quoteNote': {'id': 'QN1'}, 'userErrors': []}}
        if 'client(id' in query:
            return {'client': {'id': variables['id'], 'name': 'Lakeside Pines HOA',
                               'properties': self.properties, 'jobs': {'nodes': []}}}
        if 'jobCreateNote' in query:
            if 'attachments' in json.dumps(variables):
                raise P.JobberError("Argument 'attachments' is invalid")
            return {'jobCreateNote': {'jobNote': {'id': 'NOTE1'}, 'userErrors': []}}
        if 'clients(' in query and self.clients is not None:
            return {'clients': {'nodes': self.clients}}
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
        # OpenClaw is switched off for the office (PUMPS_OPENCLAW); these tests still cover what it could do.
        cls._openclaw = P.OPENCLAW_ENABLED
        P.OPENCLAW_ENABLED = True

    @classmethod
    def tearDownClass(cls):
        P.extract_text, P._claude_extract, P.jobber_gql = cls._orig
        P.OPENCLAW_ENABLED = cls._openclaw
        # Removed when the whole run ends: other test files share the same app (and this folder).
        atexit.register(shutil.rmtree, TMP, True)

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

    def test_multi_page_report_like_spanish_wells(self):
        """Wettech's Spanish Wells report (Oct 2026): one page per pump, each with Wettech's letterhead,
        "CUSTOMER: Stahlman England", an empty comments box and the technician - rebranded on every page, then
        put on The Lake Club's "Quarterly Pump- 850" job as "October Pump Maintenance"."""
        from docx import Document
        d = Document()
        for pump in ('Pump #1', 'Pump #2', 'Pump #3', 'Pump #5'):
            for t in ('Water Equipment Technologies of Southwest Florida LLC',
                      'State of Florida Certified Plumbing Contractor #CFC1429137',
                      '451 Interstate Court - Sarasota, FL  34240',
                      'Phone 941-232-4629   FAX 941-371-5151      EMAIL wettec@verizon.net', '',
                      '                   IRRIGATION PUMP SYSTEM REPORT'):
                d.add_paragraph(t)
            t = d.add_table(rows=2, cols=4)
            t.rows[0].cells[2].text, t.rows[0].cells[3].text = 'DATE', '10-1-2026'
            for cell, text in zip(t.rows[1].cells, ('CUSTOMER', 'Stahlman England', 'LOCATION', pump)):
                cell.text = text
            t = d.add_table(rows=1, cols=2)
            t.rows[0].cells[0].text, t.rows[0].cells[1].text = '√', 'GREASE MOTOR BEARINGS'
            d.add_paragraph('COMMENTS:')
            d.add_table(rows=1, cols=1)
            t = d.add_table(rows=1, cols=2)
            t.rows[0].cells[0].text, t.rows[0].cells[1].text = 'SERVICE TECHNICIAN', 'Justin Burnett'
            d.add_paragraph('')
        buf = io.BytesIO()
        d.save(buf)
        out, info = R.rebrand_report(buf.getvalue())
        self.assertEqual(info['pages_rebranded'], 4)
        self.assertEqual(info['technicians_removed'], ['Justin Burnett'])
        self.assertEqual(info['leftovers'], [])
        doc = Document(io.BytesIO(out))
        text = '\n'.join(p.text for p in doc.paragraphs) + '\n'.join(
            c.text for t in doc.tables for r in t.rows for c in r.cells)
        for gone in ('Water Equipment', 'wettec', '941-', 'Sarasota', 'CFC1429137', 'Justin', 'Burnett',
                     'Stahlman England', 'CUSTOMER', 'TECHNICIAN', 'COMMENTS'):
            self.assertNotIn(gone.lower(), text.lower(), gone)
        self.assertEqual(text.count('STAHLMAN – ENGLAND, INC.'), 4, 'our letterhead on every page')
        self.assertEqual(sum(1 for p in doc.paragraphs if p.paragraph_format.page_break_before), 3)
        for pump in ('Pump #1', 'Pump #2', 'Pump #3', 'Pump #5'):
            self.assertIn(pump, text)
        self.assertNotIn('   IRRIGATION', '\n'.join(p.text for p in doc.paragraphs))
        # Into the app and onto The Lake Club's job, with no one choosing anything.
        fake = FakeJobber()
        P.jobber_gql = fake
        P.JOBBER_STATIC_TOKEN, saved = 'test-token', P.JOBBER_STATIC_TOKEN
        try:
            res = P.ingest_document('10-26  Spanish Wells.docx', buf.getvalue(), source='email', actor='email scan',
                                    email={'uid': 'sw-1', 'from': 'simon@stahlman-england.com',
                                           'subject': 'FW: Inv 29099', 'preview': ''})
        finally:
            P.JOBBER_STATIC_TOKEN = saved
        self.assertEqual((res['kind'], res['review']), ('report', ''), res)
        got = self.c.get(f"/pumps/api/docs/{res['doc_id']}").get_json()['doc']
        self.assertEqual(got['client_name'], 'Spanish Wells')
        notes = [v for q, v in fake.calls if 'jobCreateNote' in q]
        self.assertTrue(notes, res)
        self.assertEqual(notes[0]['id'], 'Z2lkOi8vSm9iYmVyL0pvYi80MTQyMDAxOA==', 'job #1609 Quarterly Pump- 850')
        self.assertEqual(notes[0]['input']['message'], 'October Pump Maintenance')
        att = notes[0]['input'].get('attachments') or []
        # The PDF where the server can make one (LibreOffice), else the Word file.
        if self.c.get(f"/pumps/api/docs/{res['doc_id']}/file?version=branded_pdf").status_code == 200:
            self.assertEqual((att[0]['fileName'], att[0]['contentType']), ('10-26 Spanish Wells.pdf', 'application/pdf'))
        else:
            self.assertTrue(att[0]['fileName'].endswith('.docx'))
        self.assertEqual(res['auto_note']['target'], 'The Lake Club #1609 Quarterly Pump- 850')
        # Kept in the app by year.
        lib = self.c.get('/pumps/api/reports?year=2026').get_json()
        row = [r for r in lib['reports'] if r['id'] == res['doc_id']][0]
        self.assertEqual((row['date'], row['site'], row['jobber']['logged'], row['jobber']['title']),
                         ('2026-10-01', 'Spanish Wells', True, 'October Pump Maintenance'))
        self.assertIn('2026', lib['years'])

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

    def test_bill_over_quote_is_a_todo_to_check_with_the_vendor(self):
        """The client is invoiced what they approved; a bill that differs from
        Wettech's quote is a to-do to check with Tommy, not a hold."""
        self.extracts['q-0400.pdf'] = extraction('quote', 'Q-80', po='PO400', client='Heron Bay', subtotal=2000)
        self.extracts['b-0400.pdf'] = extraction('bill', '29200', po='PO 400', client='Heron Bay', subtotal=2250)
        self.upload('q-0400.pdf')
        b = self.upload('b-0400.pdf')
        case = self.case(b['case_id'])
        self.assertEqual(case['compare']['state'], 'over')
        self.assertEqual([i for i in case['issues'] if not i['resolved_at']], [])
        self.assertTrue({s['key']: s for s in case['step_list']}['bill_checked'].get('at'))
        todos = self.c.get('/pumps/api/summary').get_json()['queue']['todos']
        t = [t for t in todos if t['link'].get('case_id') == b['case_id']]
        self.assertEqual(len(t), 1)
        self.assertIn('Check with Tommy', t[0]['title'])
        self.assertIn('$250.00 more than their quote $2,000.00', t[0]['detail'])
        self.assertIn('tomm@wettec.biz', t[0]['detail'])

    def test_sheet_bill_amount_is_checked(self):
        cid = self.c.post('/pumps/api/sheet/save', json={'month': 'October 2026', 'client_name': 'Egret Run',
                                                          'vendor_quote_amount': '700',
                                                          'vendor_bill_amount': '760'}).get_json()['id']
        case = self.case(cid)
        self.assertEqual(case['compare']['state'], 'over')
        todos = self.c.get('/pumps/api/summary').get_json()['queue']['todos']
        self.assertTrue(any(t['link'].get('case_id') == cid and 'Check with' in t['title'] for t in todos))

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
        # Claude is switched on but down: the basic reader marks both for review and leaves them in the Inbox.
        P.USE_CLAUDE, use = True, P.USE_CLAUDE
        self.addCleanup(setattr, P, 'USE_CLAUDE', use)
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
        done = P.reread_pending('test')
        self.assertIn(b['doc_id'], [d['doc_id'] for d in done])
        self.assertTrue(self.c.get(f"/pumps/api/docs/{b['doc_id']}").get_json()['doc']['case_id'])

    def test_wettech_letter_quote(self):
        """Wettech quotes are Word letters: "RE: The Carlise", one "Your Cost" price that includes sales tax."""
        from docx import Document
        d = Document()
        for t in ('of Southwest Florida LLC', 'State of Florida Certified Plumbing Contractor', '#CFC1429137',
                  'Phone 941-232-4629   FAX 941-371-5151', 'Email: wettec@verizon.net', 'October 5, 2026',
                  'Stahlman England', 'Attn: Andrea',
                  'RE: The Carlise', 'We are pleased to quote you on the following services',
                  'Field service to check out pump station, found pipe had melted at the fitting going into the pump '
                  'suction.  Field service to pull and inspect suction line, clean screen and reinstall.',
                  'Your Cost --------------- $ 1158.99', 'Price includes Sales tax and in freight',
                  'Terms: Net 10 days', 'Thank You', 'H. H. (Tom) Morgan III'):
            d.add_paragraph(t)
        buf = io.BytesIO()
        d.save(buf)
        res = self.upload('Carslie Back Station .docx', data=buf.getvalue())
        self.assertEqual(res['kind'], 'quote', 'a quote letter, not a pump report')
        doc = self.c.get(f"/pumps/api/docs/{res['doc_id']}").get_json()['doc']
        self.assertEqual((doc['vendor'], doc['client_name'], doc['doc_date']), ('Wettech', 'The Carlise', '2026-10-05'))
        self.assertEqual((doc['subtotal'], doc['total']), (None, 1158.99))
        self.assertEqual(len(doc['line_items']), 1)
        line = doc['quote_suggestion']['line_items'][0]
        self.assertEqual(line['unit_price'], 1506.69, 'Simon quoted $1,506.69 in Jobber quote 9136')
        self.assertEqual(line['name'], 'Service Proposal Amount')
        self.assertFalse(line['taxable'], 'tax is already in the price - Jobber must not add it again')
        # Claude's reading of the same letter is cleaned up the same way.
        x = P._clean_extraction(extraction('quote', '', client='The Carlise', subtotal=1158.99, tax=0, items=[
            {'name': 'Suction line repair', 'description': 'Field service...', 'quantity': 1, 'unit_price': 1158.99,
             'amount': 1158.99, 'taxable': True, 'is_tax': False}]) | {'tax': None, 'subtotal': None, 'total': None,
                                                                       'tax_included': True})
        self.assertEqual((x['subtotal'], x['total'], x['line_items'][0]['taxable']), (None, 1158.99, False))

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
        # No Jobber quote to copy: one line, the bill before tax plus 30%.
        self.assertEqual((inp['lineItems'][0]['name'], inp['lineItems'][0]['unitPrice']), ('Service Proposal Amount', 2344.95))
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

    def test_draft_invoice_is_net_30(self):
        self.extracts['b-0630.pdf'] = extraction('bill', '29730', po='PO630', client='Sunset Cove', subtotal=400)
        b = self.upload('b-0630.pdf')

        class Net30Jobber(FakeJobber):
            reject_terms = False

            def __call__(self, query, variables=None):
                if '__type' in query:
                    n = variables['n']
                    if n == 'InvoiceCreateAttributes':
                        return {'__type': {'inputFields': [{'name': 'dueDetails', 'type': {
                            'kind': 'NON_NULL', 'ofType': {'kind': 'INPUT_OBJECT', 'name': 'InvoiceDueDetailsAttributes'}}}]}}
                    if n == 'InvoiceDueDetailsAttributes':
                        return {'__type': {'inputFields': [{'name': 'netTerms', 'type': {
                            'kind': 'ENUM', 'name': 'InvoiceNetTermsEnum'}}]}}
                    if n == 'InvoiceNetTermsEnum':
                        return {'__type': {'kind': 'ENUM', 'enumValues': [
                            {'name': 'DUE_ON_RECEIPT'}, {'name': 'NET_15'}, {'name': 'NET_30'}, {'name': 'NET_45'}]}}
                    return {'__type': {}}
                if 'invoiceCreate' in query and self.reject_terms and variables['input']['dueDetails']:
                    raise P.JobberError('Variable $input dueDetails is invalid')
                return super().__call__(query, variables)

        P._SCHEMA_CACHE.clear()
        fake = P.jobber_gql = Net30Jobber()
        try:
            body = self.c.post(f"/pumps/api/docs/{b['doc_id']}/invoice", json={'client_id': 'C9'}).get_json()
            self.assertTrue(body['success'], body)
            sent = [v for q, v in fake.calls if 'invoiceCreate' in q][-1]['input']
            self.assertEqual(sent['dueDetails'], {'netTerms': 'NET_30'})
            # The invoice's amount in Jobber (with the client's tax) shows on the item once synced.
            inv_id = self.case(b['case_id'])['jobber']['invoice']['id']
            conn = P._conn()
            try:
                conn.execute("INSERT INTO pump_jobber_items (jobber_id, kind, number, status, total) "
                             "VALUES (?, 'invoice', '5001', 'draft', 556.4)", (inv_id,))
                P._follow_invoices(conn)
                conn.commit()
            finally:
                conn.close()
            self.assertEqual(self.case(b['case_id'])['jobber']['invoice']['total'], 556.4)
            # If Jobber won't take the terms, the draft is still made with its defaults.
            self.extracts['b-0631.pdf'] = extraction('bill', '29731', po='PO631', client='Sunset Cove', subtotal=400)
            b2 = self.upload('b-0631.pdf')
            fake.reject_terms = True
            body = self.c.post(f"/pumps/api/docs/{b2['doc_id']}/invoice", json={'client_id': 'C9'}).get_json()
            self.assertTrue(body['success'], body)
        finally:
            P._SCHEMA_CACHE.clear()

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
        self.assertEqual(attrs['lineItems'][0]['unitPrice'], 3185.0, "Wettech's price plus 30%")
        self.assertEqual(attrs['lineItems'][0]['name'], 'Service Proposal Amount')
        self.assertNotIn('quotation', attrs['lineItems'][0]['description'].lower())
        self.assertTrue(attrs['title'].startswith('Proposal'))
        notes = [v for qq, v in fake.calls if 'quoteCreateNote' in qq]
        self.assertEqual(notes[0]['id'], 'Q1', "Wettech's quote is saved as a note on our quote")
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

    def test_job_tracked_before_the_visit_step_waits_on_the_visit(self):
        """Homewood Suites was tracked from Jobber before the visit step existed:
        marked approved and scheduled, no vendor. Once, at start-up, it becomes
        'waiting on Wettech to assess' with the Jobber visit date."""
        conn = P._conn()
        try:
            conn.execute("INSERT INTO pump_jobber_items (jobber_id, kind, number, title, status, job_type, created_at, "
                         "start_at, category) VALUES ('J323', 'job', '14542', 'Homewood Suites - PO 323 Pump Service', "
                         "'upcoming', 'one_off', '2026-10-05T12:00:00Z', '2026-10-13T08:00:00Z', 'pump')")
            cid = P.create_case(conn, {'title': 'Homewood Suites - PO 323 Pump Service', 'client_name': 'Homewood Suites',
                                       'scheduled_for': '2026-10-13'}, 'test', source='jobber')
            conn.execute("UPDATE pump_cases SET jobber=? WHERE id=?", (json.dumps({'job': {'id': 'J323'}}), cid))
            P._set_step(conn, cid, 'client_approved', at='2026-10-05')
            P._set_step(conn, cid, 'scheduled', at='2026-10-05')
            conn.execute("DELETE FROM pump_state WHERE key='visit_step_backfill'")
            conn.commit()
            P._backfill_visit_step(conn)
        finally:
            conn.close()
        case = self.case(cid)
        self.assertEqual(case['stage'], 'assessment')
        self.assertEqual(case['vendor'], 'Wettech')
        steps = {s['key']: s for s in case['step_list']}
        self.assertEqual(steps['assessment'].get('due'), '2026-10-13')
        self.assertFalse(steps['scheduled'].get('at'))
        self.assertFalse(steps['client_approved'].get('at'))
        # And by hand: "Wettech needs to visit first" on a job waiting on a quote.
        other = P._conn()
        try:
            oid = P.create_case(other, {'title': 'Pump Service call - PO322', 'client_name': 'Greenscapes',
                                        'vendor': 'Wettech'}, 'test')
            other.commit()
        finally:
            other.close()
        self.assertEqual(self.case(oid)['stage'], 'vendor_quote')
        r = self.c.patch(f'/pumps/api/cases/{oid}', json={'steps': {'assessment': None}, 'assessment_due': '10/20/2026'})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        case = self.case(oid)
        self.assertEqual(case['stage'], 'assessment')
        self.assertEqual({s['key']: s for s in case['step_list']}['assessment'].get('due'), '2026-10-20')

    def test_one_time_fixups_run_once_with_two_workers(self):
        conn = P._conn()
        try:
            conn.execute("DELETE FROM pump_state WHERE key='claim-test'")
            conn.commit()
            self.assertTrue(P._claim_once(conn, 'claim-test'))
            self.assertFalse(P._claim_once(conn, 'claim-test'), 'the second worker must not run it again')
            cid = P.create_case(conn, {'title': 'Twice noted', 'client_name': 'X'}, 'test')
            for _ in range(2):
                P._event(conn, 'Pumps', 'waiting on the vendor visit', 'Made in Jobber before any quote', case_id=cid)
            P._event(conn, 'Pumps', 'waiting on the vendor visit', 'A different note', case_id=cid)
            conn.execute("DELETE FROM pump_state WHERE key='startup_events_deduped'")
            conn.commit()
            P._dedupe_startup_events(conn)
            rows = conn.execute("SELECT detail FROM pump_events WHERE case_id=? AND action='waiting on the vendor visit'",
                                (cid,)).fetchall()
            self.assertEqual(sorted(r[0] for r in rows), ['A different note', 'Made in Jobber before any quote'])
        finally:
            conn.close()

    def test_the_apps_own_emails_are_not_service_calls(self):
        """The daily email ("Pumps today - 1 to do") names accounts and says
        "pump"; read back from the PO mailbox it must not open a service call."""
        for subject in ('Pumps today - 1 to do', 'FW: Pumps today - nothing urgent', 'Please pay Wettech invoice #29110',
                        'Diver schedule - October 2026 - Stahlman-England'):
            self.assertTrue(P.from_this_app('someone@example.com', subject), subject)
        self.assertFalse(P.from_this_app('manager@example.com', 'Pump at the front lake is down'))
        P.CFG['mail_from'], old = 'po@example.com', P.CFG.get('mail_from')
        try:
            self.assertTrue(P.from_this_app('PO <po@example.com>', 'anything'))
            self.assertIsNone(P.handle_service_call_email('u-own-1', 'po@example.com', 'Pumps today - 2 to do',
                                                          'Barrington Cove pump station - waiting on quote'))
        finally:
            P.CFG['mail_from'] = old
        # Ones opened before this was fixed are cancelled once, with their to-do.
        conn = P._conn()
        try:
            bad = P.create_case(conn, {'title': 'Service call - Pumps today - 1 to do', 'client_name': 'Barrington Cove'},
                                'email scan', source='service_call')
            real = P.create_case(conn, {'title': 'Service call - Front lake pump down', 'client_name': 'Barrington Cove'},
                                 'email scan', source='service_call')
            P.add_todo(conn, f'service-visit:{bad}', 'Add a "Service call - Pumps today - 1 to do" visit')
            conn.execute("DELETE FROM pump_state WHERE key='own_email_calls_removed'")
            conn.commit()
            P._remove_own_email_service_calls(conn)
            self.assertEqual(conn.execute('SELECT status FROM pump_cases WHERE id=?', (bad,)).fetchone()[0], 'cancelled')
            self.assertEqual(conn.execute('SELECT status FROM pump_cases WHERE id=?', (real,)).fetchone()[0], 'open')
            self.assertIsNotNone(conn.execute('SELECT done_at FROM pump_todos WHERE key=?', (f'service-visit:{bad}',)).fetchone()[0])
        finally:
            conn.close()

    def test_find_a_job_by_any_quote_or_invoice_number(self):
        conn = P._conn()
        try:
            cid = P.create_case(conn, {'title': 'Lift station repair', 'client_name': 'Quail Run', 'vendor': 'Wettech',
                                       'vendor_quote_number': 'Q-7731', 'vendor_bill_number': '30455',
                                       'sei_invoice_number': '36999'}, 'test')
            conn.execute("UPDATE pump_cases SET jobber=? WHERE id=?",
                         (json.dumps({'quote': {'id': 'Z1', 'number': '9188', 'total': 1235.0}}), cid))
            conn.execute("INSERT INTO pump_docs (kind, status, vendor, doc_number, case_id) "
                         "VALUES ('report', 'filed', 'Wettech', 'WO-5512', ?)", (cid,))
            conn.commit()
        finally:
            conn.close()
        for q in ('Q-7731', '#30455', '36999', '9188', 'WO-5512'):
            ids = [c['id'] for c in self.c.get('/pumps/api/cases?status=all&q=' + q.replace('#', '%23')).get_json()['cases']]
            self.assertIn(cid, ids, q)
        ids = [c['id'] for c in self.c.get('/pumps/api/cases?status=all&q=Z1').get_json()['cases']]
        self.assertNotIn(cid, ids, "Jobber's internal ids don't match")
        self.assertEqual(self.case(cid)['jobber']['quote']['total'], 1235.0)

    def test_sync_left_running_by_a_restart_reads_as_interrupted(self):
        P._state_set('jobber_sync', {'state': 'running', 'started_at': P._now_text(), 'errors': []})
        st = self.c.get('/pumps/api/jobber/items').get_json()['sync']
        self.assertEqual(st['state'], 'interrupted')
        self.assertTrue(st['errors'])
        # While a sync really holds the lock, it still reads as running.
        P._state_set('jobber_sync', {'state': 'running', 'started_at': P._now_text(), 'errors': []})
        with P._FileLock('jobber_sync', blocking=False):
            self.assertEqual(P.jobber_sync_state()['state'], 'running')

    def test_failed_sync_does_not_stay_running(self):
        real = P._sync_jobber
        def boom(full=False, actor='system'):
            P._state_set('jobber_sync', {'state': 'running', 'started_at': P._now_text(), 'errors': []})
            raise RuntimeError('database is locked')
        P._sync_jobber = boom
        try:
            with self.assertRaises(RuntimeError):
                P.sync_jobber()
        finally:
            P._sync_jobber = real
        st = P._state_get('jobber_sync')
        self.assertEqual(st['state'], 'failed')
        self.assertIn('database is locked', st['errors'][-1])

    def test_job_made_in_jobber_shows_up_to_track(self):
        """A pump job made straight in Jobber (no request) is listed to track, and
        tracking it makes an item that is already scheduled."""
        conn = P._conn()
        try:
            conn.execute("INSERT INTO pump_jobber_items (jobber_id, kind, number, title, status, job_type, client_id, "
                         "client_name, property_id, created_at, start_at, category, po_number) VALUES "
                         "('J14542', 'job', '14542', 'Homewood Suites - PO 9323 Pump Service', 'upcoming', 'one_off', "
                         "'CHW', 'Homewood Suites', 'PHW', '2026-10-05T12:00:00Z', '2026-10-13T08:00:00Z', 'pump', '9323')")
            conn.commit()
        finally:
            conn.close()
        queue = self.c.get('/pumps/api/summary').get_json()['queue']
        self.assertIn('J14542', [i['jobber_id'] for i in queue['new_jobber_requests']])
        body = self.c.get('/pumps/api/jobber/items?open=1&kind=request,quote,job').get_json()
        items = body['items']
        self.assertIn('J14542', [i['jobber_id'] for i in items])
        cid = self.c.post('/pumps/api/jobber/items/J14542', json={'action': 'track'}).get_json()['case_id']
        case = self.case(cid)
        self.assertEqual(case['jobber']['job']['number'], '14542')
        # It waits on Wettech's visit to assess (Oct 13), not on a quote or a schedule.
        self.assertEqual(case['stage'], 'assessment')
        steps = {s['key']: s for s in case['step_list']}
        self.assertEqual(steps['assessment'].get('due'), '2026-10-13')
        self.assertFalse(steps['scheduled'].get('at'))
        self.assertFalse(steps['client_approved'].get('at'))
        queue = self.c.get('/pumps/api/summary').get_json()['queue']
        self.assertIn(cid, [c['id'] for c in queue['waiting_assessment']])
        # Wettech's quote coming in means the visit happened.
        self.c.patch(f'/pumps/api/cases/{cid}', json={'steps': {'vendor_quote': '2026-10-14'}})
        case = self.case(cid)
        self.assertEqual(case['stage'], 'client_quote')
        self.assertTrue({s['key']: s for s in case['step_list']}['assessment'].get('at'))
        # Items that never had the visit step don't get it.
        other = self.c.post('/pumps/api/cases', json={'title': 'Plain repair', 'client_name': 'X'}).get_json()
        self.assertEqual(self.case(other.get('case_id') or other['case']['id'])['stage'], 'vendor_quote')
        queue = self.c.get('/pumps/api/summary').get_json()['queue']
        self.assertNotIn('J14542', [i['jobber_id'] for i in queue['new_jobber_requests']])
        # A quote Jobber makes later for the same client and property joins that item by itself.
        conn = P._conn()
        try:
            conn.execute("UPDATE pump_cases SET jobber_property_id='PHW' WHERE id=?", (cid,))
            conn.execute("INSERT INTO pump_jobber_items (jobber_id, kind, number, title, status, client_id, "
                         "property_id, created_at, category, po_number) VALUES ('Q14600', 'quote', '14600', "
                         "'Extra pump work', 'awaiting_response', 'CHW', 'PHW', '2026-10-07T12:00:00Z', 'pump', '')")
            P._link_jobber_items(conn)
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(self.case(cid)['jobber']['quote']['number'], '14600')
        # A quote sent from Jobber and still out with the client isn't listed; once approved it is.
        conn = P._conn()
        try:
            conn.execute("INSERT INTO pump_jobber_items (jobber_id, kind, number, title, status, client_id, "
                         "created_at, category, po_number) VALUES ('Q14700', 'quote', '14700', 'Pump repair', "
                         "'awaiting_response', 'COTHER', '2026-10-07T12:00:00Z', 'pump', '')")
            conn.commit()
            self.assertNotIn('Q14700', [i['jobber_id'] for i in P.untracked_jobber_items(conn)])
            conn.execute("UPDATE pump_jobber_items SET status='approved' WHERE jobber_id='Q14700'")
            conn.commit()
            self.assertIn('Q14700', [i['jobber_id'] for i in P.untracked_jobber_items(conn)])
        finally:
            conn.close()

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

    def test_quote_drafted_on_its_own_like_jobber_quote_9136(self):
        """Tom's Carlise quote (Oct 5 2026), as Simon then entered it by hand: Greenscapes, the Carlisle Pump #1
        exit ("back station"), "Proposal to inspect suction line", one Service Proposal Amount line of
        $1,506.69 (Wettech's $1,158.99 tax included, plus 30%), not taxable."""
        work = ('Field service to check out pump station, found pipe had melted at the fitting going into the pump '
                'suction. Field service to pull and inspect suction line, clean screen and reinstall, furnish ans '
                'install PVC parts needed to repair suction line, prime and test.')
        name = 'Carslie Back Station .docx'
        self.extracts[name] = extraction('quote', '', client='The Carlise', items=[
            {'name': 'Pump station repair', 'description': work, 'quantity': 1, 'unit_price': 1158.99,
             'amount': 1158.99, 'taxable': False, 'is_tax': False}]) | {
            'subtotal': None, 'tax': None, 'total': 1158.99, 'tax_included': True,
            'proposal_title': 'Proposal to inspect suction line', 'doc_date': '2026-10-05'}
        fake = FakeJobber(quote_lines=[{'name': 'Service Proposal Amount', 'description': work, 'quantity': 1,
                                         'unitPrice': 1506.69, 'taxable': False}])
        P.jobber_gql = fake
        P.JOBBER_STATIC_TOKEN, saved = 'test-token', P.JOBBER_STATIC_TOKEN
        try:
            res = self.upload(name, data=b'docx bytes')
            self.assertEqual(res['auto_quote']['quote_number'], '812', res)
            attrs = [v for q, v in fake.calls if 'quoteCreate(' in q][0]['attributes']
            self.assertEqual(attrs['clientId'], 'Z2lkOi8vSm9iYmVyL0NsaWVudC80OTAwNzI1OA==', '"Carlisle" is the Greenscapes account')
            self.assertEqual(attrs['propertyId'], 'Z2lkOi8vSm9iYmVyL1Byb3BlcnR5LzUyOTc4MjYw', '"back station" is the Pump #1 exit')
            self.assertEqual(attrs['title'], 'Proposal to inspect suction line')
            self.assertEqual(len(attrs['lineItems']), 1)
            li = attrs['lineItems'][0]
            self.assertEqual((li['name'], li['unitPrice'], li['quantity'], li['taxable']),
                             ('Service Proposal Amount', 1506.69, 1.0, False))
            self.assertEqual(li['description'], work)
            note = [v for q, v in fake.calls if 'quoteCreateNote' in q][0]
            self.assertEqual(note['id'], 'Q1')
            self.assertIn('Wettech quote', note['input']['message'])
            self.assertIn('$1,158.99 (includes sales tax)', note['input']['message'])
            self.assertIn('$1,506.69 (30% markup)', note['input']['message'])
            self.assertFalse(any(w in q for q, _ in fake.calls for w in ('Send', 'MarkAsSent')))
            queue = self.c.get('/pumps/api/summary').get_json()['queue']
            self.assertNotIn(res['doc_id'], [d['id'] for d in queue['quotes_to_draft']])
            # Wettech's bill matches its quote: the client is invoiced what they were quoted.
            self.extracts['b-carlise.pdf'] = extraction('bill', '29150', client='The Carlise', subtotal=1088.25,
                                                        tax=70.74)
            b = self.upload('b-carlise.pdf')
            self.assertEqual(b['case_id'], res['case_id'])
            sugg = self.c.get(f"/pumps/api/docs/{b['doc_id']}").get_json()['doc']['invoice_suggestion']
            self.assertEqual(sugg['from_quote'], '812')
            self.assertEqual([(l['name'], l['unit_price']) for l in sugg['line_items']],
                             [('Service Proposal Amount', 1506.69)])
        finally:
            P.JOBBER_STATIC_TOKEN = saved

    def test_carlise_quote_without_claude(self):
        """No Anthropic key: the built-in reader alone turns Tom's emailed Word quote into the 9136 draft."""
        self.assertFalse(P.USE_CLAUDE)
        from docx import Document
        d = Document()
        for t in ('of Southwest Florida LLC', 'Email: wettec@verizon.net', 'October 5, 2026', 'Stahlman England',
                  'Attn: Andrea', 'RE: The Carlise', 'We are pleased to quote you on the following services',
                  'Field service to check out pump station, found pipe had melted at the fitting going into the pump '
                  'suction.  Field service to pull and inspect suction line, clean screen and reinstall, furnish ans '
                  'install PVC parts needed to repair suction line, prime and test.',
                  'Your Cost --------------- $ 1158.99', 'Price includes Sales tax and in freight', 'Thank You'):
            d.add_paragraph(t)
        buf = io.BytesIO()
        d.save(buf)
        fake = FakeJobber()
        P.jobber_gql = fake
        P.JOBBER_STATIC_TOKEN, saved = 'test-token', P.JOBBER_STATIC_TOKEN
        try:
            form = {'file': (io.BytesIO(buf.getvalue()), 'Carslie Back Station .docx')}
            res = self.c.post('/pumps/api/docs', data=form, content_type='multipart/form-data').get_json()['results'][0]
        finally:
            P.JOBBER_STATIC_TOKEN = saved
        self.assertEqual(res['review'], '', 'a Wettech quote read cleanly is trusted')
        self.assertTrue(res['case_id'])
        self.assertEqual(res['auto_quote']['quote_number'], '812', res)
        attrs = [v for q, v in fake.calls if 'quoteCreate(' in q][0]['attributes']
        self.assertEqual((attrs['clientId'], attrs['propertyId']), ('Z2lkOi8vSm9iYmVyL0NsaWVudC80OTAwNzI1OA==', 'Z2lkOi8vSm9iYmVyL1Byb3BlcnR5LzUyOTc4MjYw'))
        self.assertEqual(attrs['title'], 'Proposal to pull and inspect suction line')
        li = attrs['lineItems'][0]
        self.assertEqual((li['name'], li['unitPrice'], li['taxable']), ('Service Proposal Amount', 1506.69, False))
        self.assertTrue([v for q, v in fake.calls if 'quoteCreateNote' in q])
        self.c.post(f"/pumps/api/cases/{res['case_id']}/delete", json={'reason': 'test done'})

    def test_forwarded_quote_with_letterhead_in_page_header(self):
        """Simon forwards Tom's quote to PO@: the sender is one of us and Wettech's details are only in the
        Word page header - it must still be read as a Wettech quote."""
        from docx import Document
        d = Document()
        hdr = d.sections[0].header.paragraphs[0]
        hdr.text = 'Water Equipment Technologies of Southwest Florida LLC - Email: wettec@verizon.net'
        for t in ('October 6, 2026', 'Stahlman England', 'RE: Egret Landing',
                  'We are pleased to quote you on the following services',
                  'Field service to replace check valve on pump #1, prime and test.',
                  'Your Cost --------------- $ 840.00', 'Price includes Sales tax and in freight'):
            d.add_paragraph(t)
        buf = io.BytesIO()
        d.save(buf)
        text = P.extract_text('Egret.docx', buf.getvalue())
        self.assertIn('wettec@verizon.net', text)
        res = P.ingest_document('Egret Landing pump.docx', buf.getvalue(), source='email', actor='email scan',
                                email={'uid': 'fw-1', 'from': 'simon@stahlman-england.com',
                                       'subject': 'FW: Egret Landing', 'preview': ''})
        self.assertEqual((res['kind'], res['review']), ('quote', ''), res)
        doc = self.c.get(f"/pumps/api/docs/{res['doc_id']}").get_json()['doc']
        self.assertEqual((doc['vendor'], doc['client_name'], doc['total']), ('Wettech', 'Egret Landing', 840.0))
        # A PDF forward whose only Wettech mark is the forwarded header in the email body.
        self.texts['fw-invoice.pdf'] = 'INVOICE\nBill To Stahlman-England\nRE: Egret Landing\nTotal $840.00'
        res = P.ingest_document('fw-invoice.pdf', b'%PDF fw', source='email', actor='email scan',
                                email={'uid': 'fw-2', 'from': 'simon@stahlman-england.com', 'subject': 'FW: Invoice',
                                       'preview': 'From: Tom Morgan <tomm@wettec.biz> Sent: Monday'})
        doc = self.c.get(f"/pumps/api/docs/{res['doc_id']}").get_json()['doc']
        self.assertEqual(doc['vendor'], 'Wettech')

    def test_client_found_through_its_property_despite_typos(self):
        props = [{'id': 'PX1', 'address': {'street1': '1 Osprey Ct', 'street2': 'Osprey Point - Pump #1', 'city': 'Naples'}},
                 {'id': 'PX2', 'address': {'street1': '2 Osprey Ct', 'street2': 'Osprey Point - Pump #2', 'city': 'Naples'}}]
        fake = FakeJobber(properties=props, clients=[
            {'id': 'LS1', 'name': 'Sunrise Landscaping', 'isLead': False, 'isArchived': False, 'properties': props},
            {'id': 'XX', 'name': 'Bayview Towers', 'isLead': False, 'isArchived': False, 'properties': []}])
        P.jobber_gql = fake
        cands = P.search_clients('The Ospray Pointe')
        self.assertEqual(cands[0]['id'], 'LS1', 'the community is a property of the landscape company')
        self.assertEqual(len(cands[0]['matching_properties']), 2)
        t = P.resolve_quote_target({'client_name': 'Ospray Pointe', 'site': 'Pump #2', 'file_name': 'q.pdf'})
        self.assertEqual((t['client_id'], t['property_id']), ('LS1', 'PX2'))
        t = P.resolve_quote_target({'client_name': 'Ospray Pointe', 'file_name': 'q.pdf'})
        self.assertEqual((t['client_id'], t['property_id']), ('LS1', None), 'two pumps, no hint: a person picks')

    def test_auto_draft_waits_for_a_person_when_unsure(self):
        self.extracts['q-unsure.pdf'] = extraction('quote', 'Q-140', client='Nowhere Isles', subtotal=700)
        fake = FakeJobber(clients=[])
        P.jobber_gql = fake
        P.JOBBER_STATIC_TOKEN, saved = 'test-token', P.JOBBER_STATIC_TOKEN
        try:
            res = self.upload('q-unsure.pdf')
        finally:
            P.JOBBER_STATIC_TOKEN = saved
        self.assertIn('Choose the Jobber client', res['auto_quote']['pending'])
        self.assertEqual([q for q, _ in fake.calls if 'quoteCreate(' in q], [])
        queue = self.c.get('/pumps/api/summary').get_json()['queue']
        d = [d for d in queue['quotes_to_draft'] if d['id'] == res['doc_id']][0]
        self.assertIn('Choose the Jobber client', d['jobber']['quote_pending']['reason'])

    def test_miramar_is_miromar(self):
        a = P.match_site_alias({'client_name': 'Miramar Lakes', 'file_name': 'Inv_29100.pdf'})
        self.assertEqual((a['client_name'], a['property_id']),
                         ('MIROMAR LAKES', 'Z2lkOi8vSm9iYmVyL1Byb3BlcnR5LzM4MTYzODEy'))
        self.assertEqual(P.match_site_alias({'client_name': 'Miromar Lakes', 'file_name': 'x.pdf'})['client_name'],
                         'MIROMAR LAKES')
        for other in ('Miramar Lakes Beach and Gulf Club', 'Miramar Lakes CDD', 'Miramar Lakes Golf & Country Club'):
            self.assertIsNone(P.match_site_alias({'client_name': other, 'file_name': 'x.pdf'}), other)
        # The Carlisle names still apply ("The Carlise" adds nothing of its own).
        self.assertEqual(P.match_site_alias({'client_name': 'The Carlise', 'file_name': 'Carslie Back Station .docx'})
                         ['area'], 'back station')

    def test_site_names(self):
        names = self.c.get('/pumps/api/site-names').get_json()['site_names']
        self.assertIn(('Carlisle', 'back station', 'Z2lkOi8vSm9iYmVyL1Byb3BlcnR5LzUyOTc4MjYw'), [(n['place'], n['area'], n['property_id']) for n in names])
        r = self.c.post('/pumps/api/site-names', json={'place': 'Heron Bay', 'area': 'front pump', 'client_id': 'C7',
                                                       'client_name': 'Heron Bay HOA', 'property_id': 'P7'})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        a = P.match_site_alias({'client_name': 'Heron Bay', 'file_name': 'Heron Bay front pump quote.pdf'})
        self.assertEqual(a['property_id'], 'P7')
        self.assertIsNone(P.match_site_alias({'client_name': 'Heron Glen', 'file_name': 'x.pdf'}))
        aid = [n['id'] for n in r.get_json()['site_names'] if n['place'] == 'Heron Bay'][0]
        bot = A.app.test_client()
        h = {'Authorization': 'Bearer test-openclaw-key'}
        self.assertEqual(bot.post('/api/pumps/site-names', json={'place': 'X', 'client_id': 'Y'}, headers=h).status_code, 403)
        self.assertEqual(bot.post(f'/api/pumps/site-names/{aid}/delete', json={}, headers=h).status_code, 403)
        self.c.post(f'/pumps/api/site-names/{aid}/delete', json={})
        self.assertIsNone(P.match_site_alias({'client_name': 'Heron Bay', 'file_name': 'Heron Bay front pump.pdf'}))

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
        # A ready-to-paste email asks Christian to pay it.
        conn = P._conn()
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('christian_email', 'christian@example.com')")
            conn.commit()
        finally:
            conn.close()
        mail = self.c.get(f'/pumps/api/cases/{cid}/pay_email').get_json()['email']
        self.assertEqual(mail['to'], 'christian@example.com')
        self.assertIn('Wettech invoice #30100', mail['subject'])
        self.assertIn('Please pay Wettech invoice #30100 for $', mail['body'])
        self.assertIn('Jobber invoice #5001', mail['body'])
        self.assertEqual(mail['bill_doc_id'], b['doc_id'])
        # Clicking Send emails it from the PO mailbox with the bill attached - only when clicked.
        sent, real_send = [], P.graph_send
        P.graph_send = lambda to, subject, html, attachments=None, sender=None: sent.append((to, subject, html, attachments))
        try:
            self.assertEqual(sent, [], 'nothing goes out on its own')
            r = self.c.post(f'/pumps/api/cases/{cid}/pay_email/send', json={'body': 'Hi Christian,\nPlease pay it.'})
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0][0], 'christian@example.com')
            self.assertIn('Please pay it.', sent[0][2])
            self.assertEqual(len(sent[0][3]), 1)
            q = self.c.get('/pumps/api/summary').get_json()['queue']['vendor_bills_to_pay']
            self.assertTrue(next(c for c in q if c['id'] == cid)['pay_email']['sent'])

            def refuse(*a, **k):
                raise RuntimeError('Microsoft 365 said HTTP 403: Access is denied.')
            P.graph_send = refuse
            r = self.c.post(f'/pumps/api/cases/{cid}/pay_email/send', json={})
            self.assertEqual(r.status_code, 502)
            self.assertIn('Access is denied', r.get_json()['error'])
        finally:
            P.graph_send = real_send
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

    # ── the diver ───────────────────────────────────────────────────────────
    def test_diver_sites_and_monthly_email(self):
        j = self.c.get('/pumps/api/dives').get_json()
        names = {x['name']: x for x in j['sites']}
        self.assertTrue({"Anna's Place", 'Spanish Wells Lake Club', 'Clubside', 'Riviera Golf Estates 2'} <= set(names))
        # From the lake sheet: quarterly, January only, April/October; former accounts kept but off the lists.
        self.assertEqual(names["Anna's Place"]['months'], '1,4,7,10')
        self.assertEqual((names["Anna's Place"]['diver_cost'], names["Anna's Place"]['our_bill']), ('$125.00', '$400.00'))
        self.assertEqual(names['Evergreen (Bradenton)']['months'], '1')
        self.assertEqual(names['Riviera Golf Estates 2']['months'], '4,10')
        self.assertEqual(names['Bentley Village']['active'], 0)
        self.assertEqual(names['Warm Springs Comm. Assoc.']['needs_dive'], 0, 'Naples Electric does it')
        self.assertEqual(names['Spanish Wells Lake Club']['status'], 'meet')
        self.assertEqual(names['Sopra Luxury Living']['status'], 'hold')
        self.assertEqual(j['settings']['to'], 'Gulfshoreyachts@gmail.com')
        # A site that doesn't need diving, one only in some months, and a one-time note.
        r = self.c.post('/pumps/api/dives/sites', json={'name': 'Lely Pump Station', 'equipment': '1 Pump',
                                                         'needs_dive': False})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.c.post('/pumps/api/dives/sites', json={'id': names['Morton Grove']['id'], 'months': '4,7,10'})
        self.c.post('/pumps/api/dives/sites', json={'id': names['Caymas']['id'],
                                                     'month_note': 'Gate is being replaced - call the office.'})
        self.assertEqual(self.c.get('/pumps/api/dives/preview?month=2026-11-01').get_json()['sites'], 0,
                         'nobody is due in November')
        p = self.c.get('/pumps/api/dives/preview?month=2027-01-01').get_json()
        self.assertEqual(p['subject'], 'Diver schedule - January 2027 - Stahlman-England')
        t = p['text']
        self.assertTrue(t.startswith('Hi Jordan!'))
        for name in ("Anna's Place", 'Clubside', 'Evergreen (Bradenton)', 'The Reserve @ Estero'):
            self.assertIn(name, t)
        for name in ('Riviera Golf Estates 2', 'Bentley Village', 'Warm Springs', 'Morton Grove'):
            self.assertNotIn(name, t)
        self.assertIn('Please see the attached list for January. Please note that Spanish Wells Lake Club has '
                      'requested to meet with you onsite.', t)
        self.assertIn('HOLD OFF - Called client to set up visit - waiting on approval. - Sopra Luxury Living', t)
        self.assertIn('Diver to check the rope that holds the float and filter.', t)
        self.assertIn('Gate code #0422', t)
        self.assertIn('Gate is being replaced', t)
        self.assertNotIn('Lely', t)
        self.assertIn('Andrea Mitchell', t)
        self.assertIn('<b>Anna&#x27;s Place</b>' if '&#x27;' in p['html'] else "<b>Anna's Place</b>", p['html'])
        october = self.c.get('/pumps/api/dives/preview?month=2026-10-01').get_json()['text']
        self.assertIn('Morton Grove', october)
        self.assertIn('Riviera Golf Estates 2', october)

        # Sending: once a month, from the PO mailbox, copied to Andrea, Word list attached.
        sent = []

        class Resp:
            status_code, content = 202, b''

        real_post = P.http_requests.post
        P.http_requests.post = lambda url, **kw: (sent.append((url, kw['json'])), Resp())[1]
        P.CFG['graph_token'], P.CFG['mail_from'] = (lambda: 'tok'), 'PO@stahlman-england.com'
        try:
            res = P.send_dive_email(P.datetime(2027, 1, 1).date())
            self.assertTrue(res['sent'])
            url, body = sent[0]
            self.assertIn('/users/PO@stahlman-england.com/sendMail', url)
            m = body['message']
            self.assertEqual([r['emailAddress']['address'] for r in m['toRecipients']], ['Gulfshoreyachts@gmail.com'])
            self.assertEqual([r['emailAddress']['address'] for r in m['ccRecipients']], ['Andrea@stahlman-england.com'])
            self.assertEqual([r['emailAddress']['address'] for r in m['replyTo']], ['Andrea@stahlman-england.com'])
            self.assertEqual(m['attachments'][0]['name'], 'Diver schedule January 2027.docx')
            self.assertGreater(len(m['attachments'][0]['contentBytes']), 1000)
            # The one-time note was for that email only; the month is not sent twice.
            caymas = [x for x in self.c.get('/pumps/api/dives').get_json()['sites'] if x['name'] == 'Caymas'][0]
            self.assertEqual(caymas['month_note'], '')
            self.assertEqual(P.send_dive_email(P.datetime(2027, 1, 1).date()), {'skipped': 'already sent this month'})
            self.assertEqual(len(sent), 1)
            # Switched off, the 1st only adds the to-do.
            P._now, real_now = (lambda: P.datetime(2027, 4, 1, 8, 5, tzinfo=P.TZ)), P._now
            try:
                self.c.post('/pumps/api/dives/settings', json={'auto': False})
                P._scheduled_dive_email()
                self.assertEqual(len(sent), 1)
                # Switched on (the default), the hourly check sends the month once; mid-month it does nothing.
                self.c.post('/pumps/api/dives/settings', json={'auto': True})
                P._scheduled_dive_email()
                P._scheduled_dive_email()
                self.assertEqual(len(sent), 2)
                self.assertIn('April 2027', sent[1][1]['message']['subject'])
                P._now = lambda: P.datetime(2027, 4, 15, 8, 5, tzinfo=P.TZ)
                P._scheduled_dive_email()
                self.assertEqual(len(sent), 2)
            finally:
                P._now = real_now
                self.c.post('/pumps/api/dives/settings', json={'auto': False})
            # A failed send is logged and tried again later.
            class Bad:
                status_code, content, text = 403, b'x', 'Access denied'

                def json(self):
                    return {'error': {'message': 'Access is denied'}}
            P.http_requests.post = lambda url, **kw: Bad()
            with self.assertRaises(RuntimeError):
                P.send_dive_email(P.datetime(2027, 7, 1).date())
            self.assertIsNone(P._state_get('dive_email:2027-07'))
            log = self.c.get('/pumps/api/dives').get_json()['sent']
            self.assertIn('Access is denied', log[0]['error'])
        finally:
            P.http_requests.post = real_post
            P.CFG['graph_token'] = None
        # OpenClaw can't change the list or email the diver.
        bot = A.app.test_client()
        h = {'Authorization': 'Bearer test-openclaw-key'}
        self.assertEqual(bot.post('/api/pumps/dives/send', json={}, headers=h).status_code, 403)
        self.assertEqual(bot.post('/api/pumps/dives/sites', json={'name': 'X'}, headers=h).status_code, 403)

    def test_todo_list_and_diver_email_todo(self):
        P.ensure_monthly_todos(P.datetime(2026, 11, 1).date())
        self.assertFalse([t for t in self.c.get('/pumps/api/todos').get_json()['todos']
                          if t['key'] == 'diver-email:2026-11'], 'no sites due in November - no to-do')
        P.ensure_monthly_todos(P.datetime(2027, 1, 1).date())
        P.ensure_monthly_todos(P.datetime(2027, 1, 1).date())
        todos = self.c.get('/pumps/api/summary').get_json()['queue']['todos']
        nov = [t for t in todos if t['key'] == 'diver-email:2027-01']
        self.assertEqual(len(nov), 1, 'one per month')
        self.assertEqual(nov[0]['title'], 'Email Jordan the January diver list')
        self.assertIn('Gulfshoreyachts@gmail.com', nov[0]['detail'])
        # The list is ready to attach.
        r = self.c.get('/pumps/api/dives/docx?month=2027-01-01')
        self.assertEqual(r.status_code, 200)
        self.assertIn('Diver schedule January 2027.docx', r.headers['Content-Disposition'])
        # Ticked off, and back again.
        j = self.c.post(f"/pumps/api/todos/{nov[0]['id']}/done", json={'done': True}).get_json()
        self.assertTrue([t for t in j['todos'] if t['id'] == nov[0]['id']][0]['done_at'])
        self.assertNotIn(nov[0]['id'], [t['id'] for t in self.c.get('/pumps/api/summary').get_json()['queue']['todos']])
        self.c.post(f"/pumps/api/todos/{nov[0]['id']}/done", json={'done': False})
        self.assertIn(nov[0]['id'], [t['id'] for t in self.c.get('/pumps/api/summary').get_json()['queue']['todos']])
        # The office's own to-dos.
        j = self.c.post('/pumps/api/todos', json={'title': 'Call Spanish Wells HOA about the dive'}).get_json()
        mine = [t for t in j['todos'] if t['title'] == 'Call Spanish Wells HOA about the dive'][0]
        self.assertEqual(self.c.post('/pumps/api/todos', json={'title': ' '}).status_code, 400)
        self.c.post(f"/pumps/api/todos/{mine['id']}/delete", json={})
        self.assertNotIn(mine['id'], [t['id'] for t in self.c.get('/pumps/api/todos').get_json()['todos']])

    def test_pipeline_dashboard(self):
        sample = self.c.get('/pumps/api/pipeline?sample=1').get_json()
        self.assertTrue(sample['sample'])
        self.assertEqual([st['key'] for st in sample['stages']],
                         ['quote', 'approval', 'scheduling', 'work', 'billing', 'payment'])
        self.assertEqual(sum(st['count'] for st in sample['stages']), sample['kpis']['open'])
        self.assertEqual(len(sample['weeks']), 8)
        # Live: a real item lands in its stage, with what's next.
        self.extracts['q-pl.pdf'] = extraction('quote', 'Q-150', po='PO990', client='Pipeline Pines', subtotal=700)
        q = self.upload('q-pl.pdf')
        live = self.c.get('/pumps/api/pipeline').get_json()
        self.assertFalse(live['sample'])
        quote = [st for st in live['stages'] if st['key'] == 'quote'][0]
        mine = [j for j in quote['jobs'] if j['id'] == q['case_id']][0]
        self.assertEqual(mine['next'], 'Quote sent to client')
        self.assertEqual(mine['jobber_uri'], '', 'not linked to Jobber yet')
        # Once linked, the job opens its Jobber record - the quote while quoting.
        self.c.patch(f"/pumps/api/cases/{q['case_id']}", json={'jobber': {
            'quote': {'id': 'QX', 'number': '9136', 'uri': 'https://secure.getjobber.com/quotes/66752875'},
            'job': {'id': 'JX', 'number': '1609', 'uri': 'https://secure.getjobber.com/work_orders/41420018'}}})
        live = self.c.get('/pumps/api/pipeline').get_json()
        mine = [j for st in live['stages'] for j in st['jobs'] if j['id'] == q['case_id']][0]
        self.assertEqual((mine['jobber_uri'], mine['jobber_label']),
                         ('https://secure.getjobber.com/quotes/66752875', 'quote #9136'))
        self.assertTrue(any(j['jobber_uri'] for st in sample['stages'] for j in st['jobs']))
        # Scheduled work shows up in the weeks ahead.
        when = (P._today() + P.timedelta(days=3)).isoformat()
        self.c.patch(f"/pumps/api/cases/{q['case_id']}", json={'scheduled_for': when})
        live = self.c.get('/pumps/api/pipeline').get_json()
        self.assertIn(when, [e['date'] for w in live['weeks'] for e in w['events']])
        ev = [e for w in live['weeks'] for e in w['events'] if e['date'] == when][0]
        self.assertEqual(ev['jobber_uri'], 'https://secure.getjobber.com/work_orders/41420018', 'the job, for a visit')

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
        # The job panel's script uses these; a page without them can't open a job.
        page = self.c.get('/pumps').get_data(as_text=True)
        for name in ('MONEY', 'CATS', 'STEPS'):
            self.assertRegex(page, rf'\bconst {name}\s*=', name)
        self.assertIn('function journeyHtml', page)

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

    def test_openclaw_is_off_unless_switched_on(self):
        """The office uses Pumps on its own: the bot door answers only with PUMPS_OPENCLAW on."""
        bot = A.app.test_client()
        h = {'Authorization': 'Bearer test-openclaw-key'}
        self.assertEqual(bot.get('/api/pumps/summary', headers=h).status_code, 200)
        P.OPENCLAW_ENABLED = False
        try:
            self.assertEqual(bot.get('/api/pumps/summary', headers=h).status_code, 401)
        finally:
            P.OPENCLAW_ENABLED = True

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

    def test_scada_sheet(self):
        """The office's SCADA sheet: renewal date = when it's next due; a year's cell holds the invoice # or a note."""
        today = P._today
        P._today = lambda: P.datetime(2026, 10, 5).date()
        try:
            j = self.c.get('/pumps/api/scada').get_json()
            rows = {r['client']: r for r in j['scada']}
            self.assertEqual(len(rows), 19)  # the sheet's 16 + 3 found in Jobber
            self.assertEqual(j['years'], ['2023', '2024', '2025', '2026'])
            allure = rows['ALLURE']
            self.assertEqual((allure['vendor_cost'], allure['our_bill'], allure['years']['2025']), (428.0, '$482.00', '29448'))
            # The sheet stopped at 2025; Jobber's invoices fill 2026.
            self.assertEqual((allure['years']['2026'], allure['next_due_on'], allure['state']), ('35944', '2027-08-28', 'current'))
            self.assertEqual(rows['LELY']['years'], {'2024': '19236', '2025': '25555', '2026': '32638'})
            self.assertEqual((rows['LELY']['next_due_on'], rows['LELY']['state']), ('2027-01-09', 'current'))
            self.assertEqual(rows['Heritage Stations']['years']['2026'], '33405')
            self.assertEqual(rows['OLD COLLIER']['next_due_on'], '2025-10-04')
            self.assertEqual(rows['AUTUMN WOODS']['years']['2024'], 'SEI pays for SCADA')
            self.assertEqual(rows['Tuscany Point']['vendor_cost'], 855.99)
            states = [r['state'] for r in j['scada']]
            # Old Collier and Camas Willows are off SCADA; Autumn Woods and Reserve are complimentary.
            self.assertEqual((states.count('overdue'), states.count('due_soon'), states.count('inactive')), (2, 0, 2))
            self.assertEqual((rows['AUTUMN WOODS']['complimentary'], rows['RESERVE AT ESTERO']['complimentary']), (1, 1))
            self.assertEqual(rows['CORSA (formerly Estero Crossing)']['state'], 'current')  # 46 days out
            # Renewed: the invoice goes in the year it was due, and the date moves on a year.
            sid = rows['CORSA (formerly Estero Crossing)']['id']
            j = self.c.post(f'/pumps/api/scada/{sid}', json={'action': 'renewed', 'value': '36800'}).get_json()
            corsa = [r for r in j['scada'] if r['id'] == sid][0]
            self.assertEqual((corsa['years']['2026'], corsa['next_due_on'], corsa['state']),
                             ('36800', '2027-11-20', 'current'))
            # A Jobber sync finds next year's renewal invoices by themselves.
            P.jobber_gql = lambda q, v=None: {'invoices': {'nodes': [
                {'invoiceNumber': 40001, 'invoiceStatus': 'paid', 'issuedDate': '2027-01-20T00:00:00Z',
                 'client': {'name': 'LELY CDD'}, 'lineItems': {'nodes': [{'name': 'PUMP SERVICE', 'description':
                 '2027 Renewal Annual Cellular and cloud subscription for SCADA system on irrigation pump station'}]}},
                {'invoiceNumber': 40002, 'invoiceStatus': 'awaiting_payment', 'issuedDate': '2027-03-02T00:00:00Z',
                 'client': {'name': 'MEDALLION HOME'}, 'lineItems': {'nodes': [{'name': 'PUMP SERVICE', 'description':
                 'Renewal of Annual Cellular and cloud subscription for SCADA system on irrigation pump station for '
                 'Cross Creek completed. 2027-2028'}]}},
                {'invoiceNumber': 40003, 'invoiceStatus': 'draft', 'issuedDate': '2027-03-02T00:00:00Z',
                 'client': {'name': 'CLUB CARE'}, 'lineItems': {'nodes': [{'description': 'SCADA subscription renewal'}]}},
                {'invoiceNumber': 40004, 'invoiceStatus': 'paid', 'issuedDate': '2027-02-02T00:00:00Z',
                 'client': {'name': 'Pebblebrook HOA'}, 'amounts': {'total': 600}, 'lineItems': {'nodes': [
                     {'description': 'Renewal of Annual Cellular and cloud subscription for SCADA system'}]}},
                {'invoiceNumber': 40005, 'invoiceStatus': 'paid', 'issuedDate': '2027-02-02T00:00:00Z',
                 'client': {'name': 'Barrington Cove'}, 'lineItems': {'nodes': [{'description': 'Pump Maintenance Complete'}]}},
            ], 'pageInfo': {'hasNextPage': False}}}
            conn = P._conn()
            self.assertEqual(P.scan_scada_invoices(conn), {'added': 1, 'recorded': 2})
            self.assertEqual(P.scan_scada_invoices(conn), {'added': 0, 'recorded': 0})  # once only
            conn.commit(); conn.close()
            rows = {r['client']: r for r in self.c.get('/pumps/api/scada').get_json()['scada']}
            self.assertEqual(rows['LELY']['years']['2027'], '40001')
            self.assertEqual(rows['CROSS CREEK']['years']['2027'], '40002')
            self.assertNotIn('2027', rows['CLUBCARE']['years'])  # drafts don't count
            self.assertEqual((rows['Pebblebrook HOA']['years'], rows['Pebblebrook HOA']['our_bill']), ({'2027': '40004'}, '$600.00'))
            # Edit and switch off.
            self.c.patch(f"/pumps/api/scada/{rows['CLUBCARE']['id']}", json={'active': False, 'notes': 'Left'})
            j = self.c.get('/pumps/api/scada').get_json()
            self.assertEqual([r for r in j['scada'] if r['client'] == 'CLUBCARE'][0]['state'], 'inactive')
            # A renewal item, one at a time.
            oc = rows['AUTUMN WOODS']['id']
            cid = self.c.post(f'/pumps/api/scada/{oc}', json={'action': 'renewal_item'}).get_json()['case_id']
            self.assertEqual(self.case(cid)['category'], 'scada')
            self.assertEqual(cid, self.c.post(f'/pumps/api/scada/{oc}', json={'action': 'renewal_item'}).get_json()['case_id'])
            self.assertIn('AUTUMN WOODS', [s['client_name'] for s in self.c.get('/pumps/api/summary').get_json()['queue']['scada_attention']])
        finally:
            P._today = today
            P.jobber_gql = self._orig[2]

    # ── the office's flow (Oct 2026) ────────────────────────────────────────
    def _pdf(self):
        from PyPDF2 import PdfWriter
        w, out = PdfWriter(), io.BytesIO()
        w.add_blank_page(width=612, height=792)
        w.write(out)
        return out.getvalue()

    def test_approved_quote_is_stamped_sent_back_and_invoiced_at_the_quoted_price(self):
        self.extracts['q-0950.pdf'] = extraction('quote', 'Q-950', po='PO951', client='Lakeside Pines', subtotal=1000)
        self.extracts['b-0950.pdf'] = extraction('bill', '30950', po='PO951', client='Lakeside Pines', subtotal=1100)
        fake = FakeJobber(quote_lines=[{'name': 'Service Proposal Amount', 'description': 'Replace check valve',
                                        'quantity': 1, 'unitPrice': 1300, 'taxable': False}])
        P.jobber_gql = fake
        P.JOBBER_STATIC_TOKEN, saved = 'test-token', P.JOBBER_STATIC_TOKEN
        try:
            q = self.upload('q-0950.pdf', data=self._pdf())
            self.assertEqual(q['auto_quote']['quote_number'], '812')
            cid = q['case_id']
            # The client approves quote #812 in Jobber (the sync calls the same thing).
            r = self.c.post(f'/pumps/api/cases/{cid}/approved', json={}).get_json()
            self.assertTrue(r['approval']['stamped'], r)
            doc = self.c.get(f"/pumps/api/docs/{q['doc_id']}").get_json()['doc']
            self.assertEqual(doc['jobber']['approved_by'], 'Simon Weardon')
            pdf = self.c.get(f"/pumps/api/docs/{q['doc_id']}/file?version=approved")
            self.assertEqual(pdf.status_code, 200)
            import pdfplumber
            with pdfplumber.open(io.BytesIO(pdf.data)) as f:
                text = f.pages[0].extract_text()
            self.assertIn('APPROVED', text)
            self.assertIn('Simon Weardon', text)
            notes = [v for qq, v in fake.calls if 'quoteCreateNote' in qq]
            self.assertTrue(any('APPROVED.pdf' in json.dumps(v) for v in notes), 'stamped copy on the Jobber quote')
            todos = {t['kind']: t for t in self.c.get('/pumps/api/summary').get_json()['queue']['todos']
                     if t['link'].get('case_id') == cid}
            self.assertEqual(todos['approved_quote']['title'], 'Send the approved quote back to Tommy (tomm@wettec.biz)')
            self.assertEqual(todos['approved_quote']['link']['to'], 'tomm@wettec.biz')
            # This Jobber has no way to make a job from a quote: a to-do instead.
            self.assertIn('Convert Jobber quote #812 to a job', [t['title'] for t in todos.values()])
            # Wettech bills $1,100 against a $1,000 quote: the client is invoiced the quoted $1,300.
            b = self.upload('b-0950.pdf')
            self.assertEqual(b['case_id'], cid)
            inv = [v for qq, v in fake.calls if 'invoiceCreate' in qq][0]['input']
            self.assertEqual([(l['name'], l['unitPrice']) for l in inv['lineItems']], [('Service Proposal Amount', 1300)])
            todos = self.c.get('/pumps/api/summary').get_json()['queue']['todos']
            self.assertTrue(any(t['link'].get('case_id') == cid and t['title'].startswith('Check with Tommy') for t in todos))
        finally:
            P.JOBBER_STATIC_TOKEN = saved

    def test_job_from_quote_and_service_visit_when_jobber_has_them(self):
        T = lambda name, kind='INPUT_OBJECT': {'kind': kind, 'name': name, 'ofType': None}
        NN = lambda t: {'kind': 'NON_NULL', 'name': None, 'ofType': t}

        class Fake(FakeJobber):
            def __call__(self, query, variables=None):
                if '__schema' in query:
                    return {'__schema': {'mutationType': {'fields': [
                        {'name': 'jobCreate', 'type': T('JobCreatePayload', 'OBJECT'),
                         'args': [{'name': 'input', 'type': NN(T('JobCreateAttributes'))}]},
                        {'name': 'visitCreate', 'type': T('VisitCreatePayload', 'OBJECT'),
                         'args': [{'name': 'jobId', 'type': NN(T('EncodedId', 'SCALAR'))},
                                  {'name': 'input', 'type': NN(T('VisitCreateAttributes'))}]}]}}}
                if '__type' in query:
                    n = variables['n']
                    return {'__type': {
                        'JobCreateAttributes': {'inputFields': [{'name': 'quoteId', 'type': NN(T('EncodedId', 'SCALAR'))},
                                                                {'name': 'title', 'type': T('String', 'SCALAR')}]},
                        'VisitCreateAttributes': {'inputFields': [{'name': 'title', 'type': NN(T('String', 'SCALAR'))},
                                                                  {'name': 'instructions', 'type': T('String', 'SCALAR')}]},
                        'JobCreatePayload': {'fields': [{'name': 'job'}, {'name': 'userErrors'}]},
                        'VisitCreatePayload': {'fields': [{'name': 'visit'}, {'name': 'userErrors'}]},
                        'EncodedId': {}}.get(n, {})}
                if 'jobCreate(' in query:
                    self.calls.append((query, variables))
                    return {'jobCreate': {'job': {'id': 'J9', 'jobNumber': 14500, 'jobberWebUri': 'https://secure.getjobber.com/work_orders/9'},
                                          'userErrors': []}}
                if 'visitCreate(' in query:
                    self.calls.append((query, variables))
                    return {'visitCreate': {'visit': {'id': 'V1'}, 'userErrors': []}}
                if 'client(id' in query:
                    return {'client': {'id': variables['id'], 'name': 'Banyan Bay', 'properties': self.properties,
                                       'jobs(first: 40)': {'nodes': [
                                           {'id': 'JM', 'jobNumber': 13196, 'title': 'Quarterly Pump Maintenance',
                                            'jobStatus': 'active', 'jobType': 'RECURRING', 'property': {'id': 'P1'}}]}}}
                return super().__call__(query, variables)
        P._SCHEMA_CACHE.clear()
        fake = Fake()
        P.jobber_gql = fake
        P.JOBBER_STATIC_TOKEN, saved = 'test-token', P.JOBBER_STATIC_TOKEN
        try:
            self.extracts['q-0910.pdf'] = extraction('quote', 'Q-910', po='PO910', client='Lakeside Pines', subtotal=500)
            q = self.upload('q-0910.pdf', data=self._pdf())
            self.c.post(f"/pumps/api/cases/{q['case_id']}/approved", json={})
            self.assertEqual(self.case(q['case_id'])['jobber']['job']['number'], '14500')
            made = [v for qq, v in fake.calls if 'jobCreate(' in qq][0]
            self.assertEqual(made['input']['quoteId'], 'Q1')
            # A plain email about a pump at one of our accounts: an item and a visit on its maintenance job.
            fake.clients = [{'id': 'CB', 'name': 'Banyan Bay C/O SAK & Associated Mgmt, Inc', 'isLead': False,
                             'isArchived': False}]
            res = P.handle_service_call_email('m-1', 'manager@banyanbay.org', 'RE: Pump not running at Banyan Bay',
                                              'The pump by the clubhouse tripped again this morning.')
            self.assertEqual(res['account'], 'Banyan Bay')
            self.assertTrue(res['visit'])
            v = [v for qq, v in fake.calls if 'visitCreate(' in qq][0]
            self.assertEqual((v['jobId'], v['input']['title']), ('JM', 'Service call - Pump not running at Banyan Bay'))
            self.assertEqual(self.case(res['case_id'])['title'], 'Service call - Pump not running at Banyan Bay')
            self.assertIsNone(P.handle_service_call_email('m-1', 'manager@banyanbay.org', 'RE: Pump not running at Banyan Bay', ''))
        finally:
            P.JOBBER_STATIC_TOKEN = saved
            P._SCHEMA_CACHE.clear()

    def test_service_call_emails(self):
        # Not connected to Jobber: the visit becomes a to-do.
        res = P.handle_service_call_email('m-2', 'board@caymas.com', 'Caymas lake fountain is off', 'Please send someone.')
        self.assertEqual((res['account'], res['visit']), ('Caymas', False))
        todos = self.c.get('/pumps/api/summary').get_json()['queue']['todos']
        self.assertIn("Add a \"Service call - Caymas lake fountain is off\" visit to Caymas's maintenance job",
                      [t['title'] for t in todos])
        self.assertEqual(self.case(res['case_id'])['vendor'], 'Gulfshore')
        # Not ours to act on: a vendor, nothing about pumps, or no account named.
        self.assertIsNone(P.handle_service_call_email('m-3', 'tomm@wettec.biz', 'Pump at Caymas', ''))
        self.assertIsNone(P.handle_service_call_email('m-4', 'a@b.com', 'Caymas invoice question', 'When is it due?'))
        self.assertIsNone(P.handle_service_call_email('m-5', 'a@b.com', 'Pump order for the shop', 'PO 5512'))

    def test_scada_coming_due_is_quoted_at_their_price(self):
        today = P._today
        P._today = lambda: P.datetime(2026, 12, 20).date()
        fake = FakeJobber(clients=[{'id': 'CL', 'name': 'LELY CDD', 'isLead': False, 'isArchived': False}])
        P.jobber_gql = fake
        P.JOBBER_STATIC_TOKEN, saved = 'test-token', P.JOBBER_STATIC_TOKEN
        try:
            done = P.scada_due_actions()
            self.assertIn('LELY', done)
            q = [v for qq, v in fake.calls if 'quoteCreate(' in qq and v['attributes']['clientId'] == 'CL'][0]['attributes']
            line = q['lineItems'][0]
            self.assertEqual((line['name'], line['unitPrice'], line['taxable']), ('Service Proposal Amount', 600.0, False))
            self.assertIn('for 2027-2028', line['description'])
            n = len([1 for qq, _ in fake.calls if 'quoteCreate(' in qq])
            P.scada_due_actions()
            self.assertEqual(len([1 for qq, _ in fake.calls if 'quoteCreate(' in qq]), n, 'once per renewal')
            todos = [t['title'] for t in self.c.get('/pumps/api/summary').get_json()['queue']['todos']]
            self.assertIn('Send the SCADA renewal quote #812 - LELY', todos)
            self.assertIn('SCADA renewal due - AUTUMN WOODS (complimentary)', todos)
            self.assertFalse(any('Quote the SCADA renewal - AUTUMN' in t for t in todos))
        finally:
            P.JOBBER_STATIC_TOKEN = saved
            P._today = today

    def test_scada_vendor_quote_is_not_marked_up(self):
        doc = {'description': 'Renewal of Annual Cellular and cloud subscription for SCADA system', 'client_name': 'Banyan Bay',
               'line_items': [{'name': 'SCADA', 'description': 'Annual subscription - SCADA', 'unit_price': 428.0,
                               'quantity': 1}]}
        s = P.suggest_quote(doc)
        self.assertEqual((s['line_items'][0]['unit_price'], s['markup_pct']), (600.0, 0))
        doc['description'] = 'Replace pressure switch'
        doc['line_items'][0].update(name='Pressure switch', description='Replace pressure switch')
        self.assertEqual(P.suggest_quote(doc)['line_items'][0]['unit_price'], 556.4)

    def test_daily_email(self):
        sent = []

        class Resp:
            status_code, content = 202, b''
        real_post = P.http_requests.post
        P.http_requests.post = lambda url, **kw: (sent.append((url, kw['json'])), Resp())[1]
        P.CFG['graph_token'], P.CFG['mail_from'] = (lambda: 'tok'), 'PO@stahlman-england.com'
        try:
            self.c.post('/pumps/api/todos', json={'title': 'Call the Caymas board'})
            r = self.c.post('/pumps/api/digest/send', json={}).get_json()
            self.assertTrue(r['sent'], r)
            m = sent[-1][1]['message']
            self.assertEqual(m['toRecipients'][0]['emailAddress']['address'], 'simon@stahlman-england.com')
            self.assertIn('Call the Caymas board', m['body']['content'])
            self.assertTrue(m['subject'].startswith('Pumps today'))
            # The 8am send happens once a weekday.
            P._now, real_now = (lambda: P.datetime(2026, 10, 6, 8, 2, tzinfo=P.TZ)), P._now
            P._today, real_today = (lambda: P.datetime(2026, 10, 6).date()), P._today
            try:
                n = len(sent)
                P._scheduled_hourly()
                P._scheduled_hourly()
                self.assertEqual(len([u for u, _ in sent[n:] if 'sendMail' in u and 'Pumps today' in str(_)]), 1)
            finally:
                P._now, P._today = real_now, real_today
        finally:
            P.http_requests.post = real_post
            P.CFG['graph_token'] = None

    def test_accounts_in_one_list(self):
        rows = {a['name']: a for a in self.c.get('/pumps/api/accounts').get_json()['accounts']}
        bb = rows['Banyan Bay']
        self.assertTrue(bb['pump'] and bb['lake'] and bb['scada'])
        self.assertEqual(bb['scada']['client'], 'BANYAN BAY')
        car = rows['Carlisle (The Carlisle)']
        self.assertTrue(car['pump'] and car['lake'])
        self.assertFalse(any(r['pump'] is None and r['name'] == 'Carlisle (The Carlisle)' for r in rows.values()))

    def test_quotes_and_invoices_are_one_service_proposal_line(self):
        doc = {'subtotal': 600.0, 'total': 639.0, 'description': 'Pump repair', 'line_items': [
            {'name': 'After making repairs to get pump running', 'description': 'After making repairs to get pump running, replace the contactor.',
             'quantity': 1, 'unit_price': 450.0, 'amount': 450.0, 'taxable': True},
            {'name': 'Labor', 'description': 'Labor 2 hours', 'quantity': 2, 'unit_price': 75.0, 'amount': 150.0, 'taxable': True},
            {'name': 'Sales Tax', 'description': 'Sales Tax 6.5%', 'amount': 39.0, 'is_tax': True}]}
        for sugg in (P.suggest_quote(doc), P.suggest_invoice(doc)):
            self.assertEqual(len(sugg['line_items']), 1)
            line = sugg['line_items'][0]
            self.assertEqual((line['name'], line['quantity'], line['unit_price']), ('Service Proposal Amount', 1, 780.0))
            self.assertIn('replace the contactor', line['description'])
            self.assertIn('Labor 2 hours', line['description'])
            self.assertNotIn('Sales Tax', line['description'])

    def test_bill_without_quote_can_be_billed_plus_30(self):
        self.extracts['b-noq2.pdf'] = extraction('bill', '30990', client='Coral Isles', subtotal=500)
        b = self.upload('b-noq2.pdf')
        issue = [i for i in self.case(b['case_id'])['issues'] if i['kind'] == 'no_quote' and not i['resolved_at']][0]
        r = self.c.post(f"/pumps/api/issues/{issue['id']}/bill-anyway", json={}).get_json()
        self.assertEqual(r['doc_id'], b['doc_id'])
        case = self.case(b['case_id'])
        self.assertEqual([i for i in case['issues'] if not i['resolved_at']], [])
        self.assertTrue({s['key']: s for s in case['step_list']}['bill_checked'].get('at'))
        doc = self.c.get(f"/pumps/api/docs/{b['doc_id']}").get_json()['doc']
        self.assertEqual(doc['invoice_suggestion']['line_items'][0]['unit_price'], 650.0)

    def test_picking_a_client_is_remembered_for_the_vendors_name(self):
        """Wettech still writes "Lee Memorial"; the office picks Hodges Funeral Home once."""
        hodges = [{'id': 'CH', 'name': 'Hodges Funeral Home', 'isLead': False, 'isArchived': False}]
        fake = FakeJobber(clients=hodges)
        P.jobber_gql = fake
        self.extracts['b-lee1.pdf'] = extraction('bill', '31001', client='Lee Memorial', subtotal=200)
        b = self.upload('b-lee1.pdf')
        r = self.c.post(f"/pumps/api/docs/{b['doc_id']}/invoice",
                        json={'client_id': 'CH', 'client_name': 'Hodges Funeral Home'}).get_json()
        self.assertTrue(r['success'], r)
        names = {n['place']: n for n in self.c.get('/pumps/api/site-names').get_json()['site_names']}
        self.assertEqual(names['Lee Memorial']['client_name'], 'Hodges Funeral Home')
        # Searching the name now offers Hodges first, already chosen.
        j = self.c.get('/pumps/api/jobber/clients?q=Lee%20Memorial').get_json()
        self.assertEqual((j['pick']['id'], j['candidates'][0]['remembered'] != ''), ('CH', True))
        # The next Lee Memorial bill goes to Hodges without asking.
        fake.clients = []
        self.extracts['b-lee2.pdf'] = extraction('bill', '31002', client='Lee Memorial', subtotal=300)
        b2 = self.upload('b-lee2.pdf')
        r = self.c.post(f"/pumps/api/docs/{b2['doc_id']}/invoice", json={}).get_json()
        self.assertTrue(r['success'], r)
        self.assertEqual([v for q, v in fake.calls if 'invoiceCreate' in q][-1]['input']['clientId'], 'CH')
        # A client picked under its own name teaches nothing.
        self.assertIsNone(P.remember_choice({'client_name': 'Hodges Funeral Home'}, 'CH', 'Hodges Funeral Home'))

    def test_invoice_retries_without_fields_jobber_refuses(self):
        """Jobber's invoice lines don't take saveToProductsAndServices (quote lines do)."""
        class Picky(FakeJobber):
            def __call__(self, query, variables=None):
                if 'invoiceCreate' in query and 'saveToProductsAndServices' in json.dumps(variables):
                    self.calls.append((query, variables))
                    raise P.JobberError('Variable $input of type InvoiceCreateInput! was provided invalid value for '
                                        'lineItems.0.saveToProductsAndServices (Field is not defined on '
                                        'InvoiceCreationLineItemInput)')
                return super().__call__(query, variables)
        fake = Picky()
        P.jobber_gql = fake
        self.extracts['b-picky.pdf'] = extraction('bill', '31100', client='Lakeside Pines', subtotal=600)
        b = self.upload('b-picky.pdf')
        r = self.c.post(f"/pumps/api/docs/{b['doc_id']}/invoice", json={'client_id': 'C1'}).get_json()
        self.assertTrue(r['success'], r)
        sent = [v for q, v in fake.calls if 'invoiceCreate' in q][-1]['input']['lineItems'][0]
        self.assertNotIn('saveToProductsAndServices', sent)
        self.assertEqual((sent['name'], sent['unitPrice'], sent['taxable']), ('Service Proposal Amount', 780.0, True))

    def test_bill_is_invoiced_on_the_matching_jobber_job(self):
        """Wettech bills "Lee Memorial"; Hodges' job #14511 "Replace broken drop pipe" needs invoicing."""
        HODGES = 'Z2lkOi8vSm9iYmVyL0NsaWVudC8zODg2MDA3MQ=='

        class Fake(FakeJobber):
            def __call__(self, query, variables=None):
                if 'job(id:' in query:
                    self.calls.append((query, variables))
                    jobs = {
                        'J14511': {'id': 'J14511', 'jobNumber': 14511, 'title': 'Replace broken drop pipe',
                                   'instructions': 'Lee Memorial Well 6\n\nAfter making repairs to get pump running, '
                                                   'we found the pipe is broke below the well seal.',
                                   'jobStatus': 'requires_invoicing', 'jobType': 'ONE_OFF', 'total': 3471.43,
                                   'jobberWebUri': 'https://secure.getjobber.com/work_orders/158570173',
                                   'property': {'id': 'P9', 'address': {'street1': '12777 Florida 82', 'city': 'Lehigh Acres'}},
                                   'lineItems': {'nodes': [{'name': 'PROPOSAL AMOUNT SERVICE', 'description': 'Lee Memorial Well 6 ...',
                                                            'quantity': 1, 'unitPrice': 3471.43, 'taxable': False}]}},
                        'J200': {'id': 'J200', 'jobNumber': 14400, 'title': 'Install new zones at the mausoleum',
                                 'instructions': 'Four new zones', 'jobStatus': 'active', 'jobType': 'ONE_OFF', 'total': 16795,
                                 'lineItems': {'nodes': [{'name': 'Zones', 'description': 'Four zones', 'quantity': 1,
                                                          'unitPrice': 16795, 'taxable': True}]}}}
                    return {'job': jobs[variables['id']]}
                if 'client(id' in query:
                    return {'client': {'id': variables['id'], 'name': 'Hodges Funeral Home', 'properties': [],
                                       'jobs(first: 40)': {'nodes': [
                                           {'id': 'J14511', 'jobNumber': 14511, 'title': 'Replace broken drop pipe',
                                            'jobStatus': 'requires_invoicing', 'jobType': 'ONE_OFF'},
                                           {'id': 'J200', 'jobNumber': 14400, 'title': 'Install new zones at the mausoleum',
                                            'jobStatus': 'active', 'jobType': 'ONE_OFF'},
                                           {'id': 'JR', 'jobNumber': 2069, 'title': 'Quarterly 2500', 'jobStatus': 'upcoming',
                                            'jobType': 'RECURRING'}]}}}
                return super().__call__(query, variables)
        fake = Fake(clients=[])
        P.jobber_gql = fake
        P.JOBBER_STATIC_TOKEN, saved = 'test-token', P.JOBBER_STATIC_TOKEN
        try:
            items = [{'name': 'After making repairs to get pump running', 'description': 'Lee Memorial Well 6. After making '
                      'repairs to get pump running, found pump stuck in well, customer will need to call well driller.',
                      'quantity': 1, 'unit_price': 600, 'amount': 600, 'taxable': True, 'is_tax': False}]
            self.extracts['b-leemem.pdf'] = extraction('bill', '31500', client='Lee Memorial', subtotal=600, items=items)
            b = self.upload('b-leemem.pdf')
            inv = b['auto_invoice']
            self.assertEqual(inv['job']['number'], '14511', inv)
            sent = [v for q, v in fake.calls if 'invoiceCreate' in q][-1]['input']
            self.assertEqual((sent['clientId'], sent['jobId']), (HODGES, 'J14511'))
            self.assertEqual([(l['name'], l['unitPrice']) for l in sent['lineItems']], [('PROPOSAL AMOUNT SERVICE', 3471.43)])
            case = self.case(b['case_id'])
            self.assertEqual(case['jobber']['job']['number'], '14511')
            self.assertEqual([i for i in case['issues'] if not i['resolved_at']], [])
            todos = [t['title'] for t in self.c.get('/pumps/api/summary').get_json()['queue']['todos']]
            self.assertIn("Check with Tommy - Wettech bill doesn't line up with job #14511", todos)
        finally:
            P.JOBBER_STATIC_TOKEN = saved

    def test_mark_done_remove_and_reopen(self):
        self.extracts['b-done.pdf'] = extraction('bill', '31700', client='Coral Isles', subtotal=500)
        b = self.upload('b-done.pdf')
        cid = b['case_id']
        self.assertTrue([i for i in self.case(cid)['issues'] if not i['resolved_at']])
        self.assertTrue(self.c.post(f'/pumps/api/cases/{cid}/done', json={'note': 'Handled by phone'}).get_json()['success'])
        case = self.case(cid)
        self.assertEqual((case['status'], [i for i in case['issues'] if not i['resolved_at']]), ('closed', []))
        # Step changes later don't reopen a job marked done by hand.
        self.c.patch(f'/pumps/api/cases/{cid}', json={'notes': 'x'})
        self.assertEqual(self.case(cid)['status'], 'closed')
        self.assertNotIn(cid, [c['id'] for c in self.c.get('/pumps/api/cases?status=open').get_json()['cases']])
        self.c.post(f'/pumps/api/cases/{cid}/done', json={'reopen': True})
        self.assertEqual(self.case(cid)['status'], 'open')
        self.c.post(f'/pumps/api/cases/{cid}/delete', json={'reason': 'Removed'})
        self.assertEqual(self.case(cid)['status'], 'cancelled')

    def test_maintenance_accounts(self):
        today = P._today
        P._today = lambda: P.datetime(2026, 10, 5).date()
        try:
            j = self.c.get('/pumps/api/maint').get_json()
        finally:
            P._today = today
        acc = {a['name']: a for a in j['accounts']}
        self.assertEqual(sum(1 for a in j['accounts'] if a['active']), 39)
        self.assertEqual(sum(1 for a in j['accounts'] if not a['active']), 13)
        lc = acc['Lake Club (Spanish Wells)']
        self.assertEqual((lc['months'], lc['vendor_cost'], lc['due_this_month']), ('1,4,7,10', '$200.00', True))
        self.assertTrue(acc['Quail Run']['monthly'])
        self.assertFalse(acc['Forum c/o LandQwest Commercial Property']['due_this_month'], 'January/July only')
        self.assertEqual(acc['Warm Springs Comm. Assoc.']['naples_electric'], '$250.00')
        self.assertFalse(acc['Sapphire Lakes']['active'])
        r = self.c.post('/pumps/api/maint', json={'id': acc['Wilshire']['id'], 'active': True, 'months': 'jan apr'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.c.post('/api/pumps/maint', json={'name': 'X'},
                                     headers={'Authorization': 'Bearer test-openclaw-key'}).status_code, 403)

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
