"""
Tests for the Receivables app (receivables.py).

    python -m unittest tests.test_receivables -v

Runs against a throwaway database. Microsoft 365 and Jobber are fakes that record
what they were asked; Claude is off, so replies are read by the plain rules.
All names, numbers and addresses are made up.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix='receivables_test_')
os.environ.update(SECRET_KEY='test-secret-key-0123456789abcdef-ar', DATA_DIR=TMP, PUMPS_AUTO_SCAN='false',
                  WORKORDERS_AUTO_RUN='false', AR_AUTO_RUN='false', WEBSITE_URL='https://office.example.com')
os.environ.pop('ANTHROPIC_API_KEY', None)

import app as A  # noqa: E402
import receivables as R  # noqa: E402

A.app.config['TESTING'] = True
A.app.config['WTF_CSRF_ENABLED'] = False

TODAY = R._today()


def ago(days):
    return (TODAY - timedelta(days=days)).strftime('%m/%d/%Y')


def aging_detail_xlsx(rows):
    """A QuickBooks Online A/R Aging Detail export: title rows, header, aging sections, totals."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(['Example Irrigation Co'])
    ws.append(['A/R Aging Detail Report'])
    ws.append(['As of today'])
    ws.append([])
    ws.append(['', 'Date', 'Transaction Type', 'Num', 'Customer', 'Due Date', 'Amount', 'Open Balance'])
    ws.append(['31 - 60 days past due'])
    for r in rows:
        ws.append([''] + list(r))
    ws.append(['Total for 31 - 60 days past due', '', '', '', '', '', '', 999])
    ws.append(['TOTAL', '', '', '', '', '', '', 999])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


class FakeGraph:
    def __init__(self, inbox=None):
        self.calls = []
        self.inbox = inbox or []
        self.n = 0

    def __call__(self, method, path, **kw):
        self.calls.append((method, path, kw))
        if method == 'POST' and path.endswith('/messages'):
            self.n += 1
            return {'id': f'msg{self.n}', 'conversationId': f'conv{self.n}'}
        if method == 'GET' and '/mailFolders/inbox/messages' in path:
            return {'value': self.inbox}
        return {}

    def sent(self):
        return [c for c in self.calls if c[0] == 'POST' and c[1].endswith('/send')]

    def attachments(self):
        return [c[2]['json']['name'] for c in self.calls if c[0] == 'POST' and c[1].endswith('/attachments')]


class Base(unittest.TestCase):
    def setUp(self):
        conn = R._conn()
        for t in ('ar_invoices', 'ar_customers', 'ar_jobs', 'ar_notes', 'ar_documents', 'ar_emails', 'ar_replies',
                  'ar_uploads', 'ar_activity'):
            conn.execute(f'DELETE FROM {t}')
        conn.commit()
        conn.close()
        A.set_setting('receivables_settings', '{}')
        A.set_setting('receivables_last_reply_scan', '')
        self.graph = FakeGraph()
        R._graph = self.graph
        R._cfg['graph_enabled'] = True
        R._cfg['jobber_connected'] = lambda: False
        R._in_send_window = lambda s: True
        self.client = A.app.test_client()

    def login(self, role='office', username='simon'):
        with self.client.session_transaction() as s:
            s['username'] = username
            s['role'] = role
            s['full_name'] = 'Simon Test'

    def upload(self, rows):
        parsed, info = R.parse_ar_table(R._read_table(aging_detail_xlsx(rows), 'ar.xlsx'))
        return R.apply_upload(parsed, 'ar.xlsx', 'test'), parsed, info

    def inv(self, number):
        conn = R._conn()
        r = conn.execute("SELECT * FROM ar_invoices WHERE number=?", (number,)).fetchone()
        conn.close()
        return dict(r) if r else None


class ParseTests(Base):
    def test_aging_detail_layout(self):
        _, parsed, info = self.upload([
            (ago(50), 'Invoice', 36006, 'Sample Builders:Tide Cleaners', ago(40), 2000, 200),
            (ago(45), 'Payment', '', 'Sample Builders', '', -100, -100),
            (ago(45), 'Credit Memo', 'CM1', 'Pat Example', '', -50, -50),
            (ago(40), 'Invoice', 36484, 'PAT EXAMPLE', ago(35), 150, 150),
        ])
        self.assertEqual([p['number'] for p in parsed], ['36006', '36484'])
        self.assertEqual(parsed[0]['customer'], 'Sample Builders')
        self.assertEqual(parsed[0]['qb_job'], 'Tide Cleaners')
        self.assertEqual(parsed[0]['amount'], 2000)
        self.assertEqual(parsed[0]['open_balance'], 200)
        self.assertEqual(info['skipped_types'], 1)

    def test_open_invoices_layout_with_customer_sections(self):
        rows = [['Open Invoices'], [], ['Date', 'Transaction Type', 'Num', 'Terms', 'Due Date', 'Open Balance'],
                ['Jamie Sample'], [ago(20), 'Invoice', '1001', 'Net 15', ago(5), '$1,250.00'],
                ['Total for Jamie Sample', '', '', '', '', '1,250.00'],
                ['31 - 60 days past due'],
                ['Lake Example HOA'], [ago(70), 'Invoice', '1002', 'Net 30', ago(40), '(0.00)'],
                [ago(60), 'Invoice', '1003', 'Net 30', ago(30), 300]]
        parsed, _ = R.parse_ar_table(rows)
        self.assertEqual([(p['number'], p['customer'], p['open_balance']) for p in parsed],
                         [('1001', 'Jamie Sample', 1250.0), ('1003', 'Lake Example HOA', 300.0)])

    def test_no_header(self):
        with self.assertRaises(ValueError):
            R.parse_ar_table([['hello'], ['world']])


class ClassifyTests(Base):
    def test_retainage_and_install_and_job(self):
        self.upload([
            (ago(50), 'Invoice', 36006, 'Sample Builders:Tide Cleaners', ago(40), 2000, 200),
            (ago(50), 'Invoice', 36007, 'Sample Builders:Tide Cleaners', ago(40), 4000, 200),
            (ago(40), 'Invoice', 36484, 'Pat Example', ago(35), 150, 150),
            (ago(40), 'Invoice', 36485, 'Pat Example', ago(35), 1000, 500),
        ])
        a, b, c, d = (self.inv(n) for n in ('36006', '36007', '36484', '36485'))
        self.assertEqual((a['retainage'], a['retainage_pct'], a['kind']), (1, 10.0, 'install'))
        self.assertEqual((b['retainage'], b['retainage_pct']), (1, 5.0))
        self.assertEqual(a['job_key'], b['job_key'])
        self.assertTrue(a['job_key'].startswith('qb:'))
        self.assertEqual((c['retainage'], c['kind'], c['job_key']), (0, 'service', ''))
        self.assertEqual(d['retainage'], 0)  # half paid is not retainage

    def test_jobber_project_code_groups_pay_apps(self):
        self.upload([(ago(50), 'Invoice', 36006, 'Sample Builders', ago(40), 2000, 2000)])
        inv = self.inv('36006')
        R._apply_jobber(inv, {'id': 'J1', 'invoiceStatus': 'past_due', 'subject': 'PAY APP 1 - TIDE CLEANERS',
                              'clientHubUri': 'https://hub.example/1', 'amounts': {'total': 2000, 'invoiceBalance': 2000},
                              'client': {'id': 'C1', 'name': 'Sample Builders',
                                         'emails': [{'address': 'ap@builders.example', 'primary': True}]},
                              'lineItems': {'nodes': [{'name': 'Installation Irrigation',
                                                       'description': '26106 - TIDE CLEANERS\n1 Example Rd'}]}})
        R.classify_all()
        inv = self.inv('36006')
        self.assertEqual(inv['kind'], 'install')
        self.assertEqual(inv['job_key'], 'proj:26106')
        self.assertEqual(R._job('proj:26106')['name'], '26106 - TIDE CLEANERS')
        conn = R._conn()
        cust = dict(conn.execute("SELECT * FROM ar_customers WHERE key=?", (inv['customer_key'],)).fetchone())
        conn.close()
        self.assertEqual(cust['jobber_emails'], 'ap@builders.example')

    def test_jobber_paid_closes(self):
        self.upload([(ago(50), 'Invoice', 5, 'Pat Example', ago(40), 100, 100)])
        R._apply_jobber(self.inv('5'), {'id': 'J5', 'invoiceStatus': 'paid', 'amounts': {'total': 100}, 'client': {}})
        self.assertEqual(self.inv('5')['status'], 'paid')


class UploadTests(Base):
    def test_dropped_invoices_close_and_big_drop_asks(self):
        rows = [(ago(50), 'Invoice', 100 + n, f'Customer {n}', ago(40), 100, 100) for n in range(12)]
        self.upload(rows)
        summary, _, _ = self.upload(rows[:3])
        self.assertTrue(summary.get('needs_confirm'))
        self.assertEqual(self.inv('111')['status'], 'open')
        summary, _, _ = self.upload(rows[:11])
        self.assertEqual(summary['closed'], 1)
        self.assertEqual(self.inv('111')['status'], 'paid')
        summary, _, _ = self.upload(rows)
        self.assertEqual(self.inv('111')['status'], 'open')

    def test_partial_payment_noted(self):
        self.upload([(ago(50), 'Invoice', 7, 'Pat Example', ago(40), 1000, 1000)])
        self.upload([(ago(50), 'Invoice', 7, 'Pat Example', ago(40), 1000, 100)])
        inv = self.inv('7')
        self.assertEqual(inv['retainage'], 1)
        conn = R._conn()
        notes = [r['text'] for r in conn.execute("SELECT text FROM ar_notes WHERE invoice_id=?", (inv['id'],))]
        conn.close()
        self.assertTrue(any('payment or credit of $900.00' in n for n in notes))


class PlanTests(Base):
    def test_stages_and_cadence(self):
        s = R.settings()
        base = {'status': 'open', 'open_balance': 100, 'retainage': 0, 'snooze_until': '', 'last_followup_at': None,
                'due_date': (TODAY - timedelta(days=45)).isoformat(), 'txn_date': ''}
        p = R.plan(dict(base), None, None, s)
        self.assertTrue(p['due_now'])
        self.assertEqual(p['stage'], 'past_due')
        p = R.plan(dict(base, last_followup_at=(TODAY - timedelta(days=3)).isoformat()), None, None, s)
        self.assertFalse(p['due_now'])
        p = R.plan(dict(base, due_date=TODAY.isoformat()), None, None, s)
        self.assertEqual(p['reason'], 'Not past due yet')
        p = R.plan(dict(base, retainage=1), {'complete': None, 'jobber_completed_at': ''}, None, s)
        self.assertIn('held until the job is complete', p['reason'])
        p = R.plan(dict(base, retainage=1), {'complete': 1}, None, s)
        self.assertTrue(p['due_now'])
        self.assertEqual(p['stage'], 'retainage')

    def test_lien_info(self):
        s = R.settings()
        job = {'kind': 'install', 'last_furnished': (TODAY - timedelta(days=70)).isoformat(), 'nonp_status': ''}
        invs = [{'status': 'open', 'open_balance': 500, 'txn_date': '', 'due_date': (TODAY - timedelta(days=40)).isoformat()}]
        li = R.lien_info(job, invs, s)
        self.assertEqual(li['days_left'], 20)
        self.assertTrue(li['nonp_due'])
        self.assertFalse(R.lien_info(dict(job, kind='service'), invs, s)['applies'])


class FollowupTests(Base):
    def setUp(self):
        super().setUp()
        self.upload([
            (ago(50), 'Invoice', 36484, 'PAT EXAMPLE', ago(45), 150, 150),
            (ago(50), 'Invoice', 36490, 'PAT EXAMPLE', ago(45), 300, 300),
            (ago(100), 'Invoice', 36006, 'Sample Builders:Tide Cleaners', ago(95), 2000, 2000),
            (ago(100), 'Invoice', 36007, 'Sample Builders:Tide Cleaners', ago(95), 2000, 200),
        ])
        conn = R._conn()
        conn.execute("UPDATE ar_customers SET emails='pat@example.com' WHERE key='patexample'")
        conn.execute("UPDATE ar_customers SET emails='ap@builders.example' WHERE key='samplebuilders'")
        conn.commit()
        conn.close()

    def drafts(self):
        conn = R._conn()
        rows = [dict(r) for r in conn.execute("SELECT * FROM ar_emails WHERE status='draft' ORDER BY id")]
        conn.close()
        return rows

    def test_drafts_grouped_and_toned(self):
        R.plan_followups()
        d = self.drafts()
        self.assertEqual(len(d), 2)
        service = next(e for e in d if e['group_key'] == 'cust:patexample')
        install = next(e for e in d if e['group_key'].startswith('job:'))
        self.assertEqual(len(json.loads(service['invoice_ids'])), 2)
        self.assertEqual(service['stage'], 'past_due')
        self.assertIn('Hello Pat Example', service['body'])
        self.assertEqual(install['stage'], 'final')
        self.assertIn('FINAL NOTICE', install['subject'])
        self.assertIn('Notice of Nonpayment', install['body'])
        self.assertIn('retainage of $200.00 is also held', install['body'])
        self.assertEqual(len(json.loads(install['invoice_ids'])), 1)  # retainage waits for completion

    def test_send_attaches_invoices_and_job_documents(self):
        R.plan_followups()
        install = next(e for e in self.drafts() if e['group_key'].startswith('job:'))
        conn = R._conn()
        stored = 'test_asbuilt.pdf'
        with open(os.path.join(R._files_dir(), stored), 'wb') as fh:
            fh.write(b'%PDF-1.4 as built')
        conn.execute("INSERT INTO ar_documents (scope, scope_key, filename, stored_name, content_type, size) "
                     "VALUES ('job', ?, 'As-built.pdf', ?, 'application/pdf', 17)", (install['job_key'], stored))
        conn.commit()
        conn.close()
        ok, err = R.send_email(install['id'], by='test')
        self.assertTrue(ok, err)
        self.assertEqual(len(self.graph.sent()), 1)
        self.assertEqual(self.graph.attachments(), ['Invoice-36006.pdf', 'As-built.pdf'])
        inv = self.inv('36006')
        self.assertEqual(inv['followup_count'], 1)
        self.assertEqual(inv['last_stage'], 'final')
        conn = R._conn()
        e = dict(conn.execute("SELECT * FROM ar_emails WHERE id=?", (install['id'],)).fetchone())
        conn.close()
        self.assertEqual(e['conversation_id'], 'conv1')
        # Not due again right away
        R.plan_followups()
        self.assertFalse(any(x['group_key'] == install['group_key'] for x in self.drafts()))

    def test_service_email_has_only_invoices(self):
        R.plan_followups()
        service = next(e for e in self.drafts() if e['group_key'] == 'cust:patexample')
        R.send_email(service['id'])
        self.assertEqual(sorted(self.graph.attachments()), ['Invoice-36484.pdf', 'Invoice-36490.pdf'])

    def test_auto_send(self):
        s = R.settings()
        s['auto_send'] = True
        R._save_settings(s)
        R.plan_followups()
        self.assertEqual(len(self.graph.sent()), 2)

    def test_reply_promise_holds_until_very_past_due(self):
        R.plan_followups()
        service = next(e for e in self.drafts() if e['group_key'] == 'cust:patexample')
        R.send_email(service['id'])
        self.graph.inbox = [{'id': 'r1', 'conversationId': 'conv1', 'subject': 'RE: Second notice',
                             'from': {'emailAddress': {'address': 'pat@example.com'}},
                             'receivedDateTime': '2026-10-08T12:00:00Z',
                             'uniqueBody': {'contentType': 'text', 'content': 'Sorry! The check will be mailed Friday.'}}]
        R.scan_replies()
        inv = self.inv('36484')
        self.assertEqual(inv['status'], 'promised')
        # Invoice is 45 days late; very past due starts at 61 days, so held 16 more days.
        self.assertEqual(inv['snooze_until'], (TODAY + timedelta(days=16)).isoformat())
        p = R.plan(inv, None, None, R.settings())
        self.assertFalse(p['due_now'])
        self.assertIn('Payment promised', p['reason'])
        # Reading the inbox again does not double up.
        R.scan_replies()
        conn = R._conn()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM ar_replies").fetchone()[0], 1)
        conn.close()

    def test_reply_dispute_needs_person_and_unrelated_mail_ignored(self):
        self.graph.inbox = [
            {'id': 'r2', 'conversationId': 'x', 'subject': 'Invoice 36490',
             'from': {'emailAddress': {'address': 'pat@example.com'}}, 'receivedDateTime': '2026-10-08T12:00:00Z',
             'body': {'contentType': 'text', 'content': 'This charge is incorrect, we never ordered this.'}},
            {'id': 'r3', 'conversationId': 'y', 'subject': 'Lunch?',
             'from': {'emailAddress': {'address': 'friend@example.org'}}, 'receivedDateTime': '2026-10-08T12:00:00Z',
             'body': {'contentType': 'text', 'content': 'Want to get lunch?'}}]
        R.scan_replies()
        self.assertEqual(self.inv('36490')['status'], 'needs_person')
        self.assertEqual(self.inv('36484')['status'], 'open')  # the reply named 36490 only
        conn = R._conn()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM ar_replies").fetchone()[0], 1)
        conn.close()

    def test_promise_lapses(self):
        conn = R._conn()
        conn.execute("UPDATE ar_invoices SET status='promised', snooze_until=?, promised_on=? WHERE number='36484'",
                     ((TODAY - timedelta(days=1)).isoformat(), (TODAY - timedelta(days=20)).isoformat()))
        conn.commit()
        conn.close()
        R.plan_followups()
        self.assertEqual(self.inv('36484')['status'], 'open')
        service = next(e for e in self.drafts() if e['group_key'] == 'cust:patexample')
        self.assertIn("you let us know payment", service['body'])

    def test_nonp(self):
        key = self.inv('36006')['job_key']
        conn = R._conn()
        conn.execute("UPDATE ar_jobs SET owner_name='Owner Example', owner_email='owner@example.com', "
                     "last_furnished=? WHERE key=?", ((TODAY - timedelta(days=75)).isoformat(), key))
        conn.commit()
        conn.close()
        R.check_liens()
        job = R._job(key)
        self.assertEqual(job['nonp_status'], 'prepared')
        conn = R._conn()
        e = dict(conn.execute("SELECT * FROM ar_emails WHERE kind='nonp'").fetchone())
        conn.close()
        self.assertEqual(e['to_email'], 'owner@example.com')
        self.assertEqual(e['cc'], 'ap@builders.example')
        self.assertIn('claim of lien', e['body'])
        ok, err = R.send_email(e['id'])
        self.assertTrue(ok, err)
        self.assertEqual(R._job(key)['nonp_status'], 'sent')
        self.assertTrue(self.graph.attachments()[0].startswith('Notice-of-Nonpayment'))
        R.check_liens()  # not prepared twice
        conn = R._conn()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM ar_emails WHERE kind='nonp'").fetchone()[0], 1)
        conn.close()

    def test_nonp_needs_owner_for_contractor(self):
        key = self.inv('36006')['job_key']
        ok, msg = R.prepare_nonp(key)
        self.assertFalse(ok)
        self.assertIn('owner', msg)


class ReplyRuleTests(unittest.TestCase):
    def test_rules(self):
        inv = [{'number': '36484', 'open_balance': 100, 'due_date': ''}]
        today = date(2026, 10, 8)  # a Thursday
        got = R.classify_reply('RE: invoice', 'Payment will be sent next week', inv, today)
        self.assertEqual((got['intent'], got['promised_date']), ('promise', '2026-10-15'))
        got = R.classify_reply('RE: invoice', 'We are processing it, should go out 10/20', inv, today)
        self.assertEqual((got['intent'], got['promised_date']), ('promise', '2026-10-20'))
        self.assertEqual(R.classify_reply('RE', 'We mailed the check on Monday.', inv, today)['intent'], 'paid')
        self.assertEqual(R.classify_reply('Automatic reply: out of office', 'I am away', inv, today)['intent'], 'auto_reply')
        self.assertEqual(R.classify_reply('RE', 'Can you send a W-9?', inv, today)['intent'], 'question')


class AccessTests(Base):
    def test_office_only(self):
        self.assertEqual(self.client.get('/receivables').status_code, 302)
        self.login(role='technician', username='tech')
        self.assertEqual(self.client.get('/receivables').status_code, 302)
        self.assertEqual(self.client.get('/receivables/api/data').status_code, 403)
        self.login()
        self.assertEqual(self.client.get('/receivables').status_code, 200)
        j = self.client.get('/receivables/api/data').get_json()
        self.assertTrue(j['success'])

    def test_upload_route_and_pdf(self):
        self.login()
        f = aging_detail_xlsx([(ago(50), 'Invoice', 36484, 'Pat Example', ago(45), 150, 150)])
        R.run_cycle = lambda manual=False: True
        r = self.client.post('/receivables/api/upload', data={'file': (f, 'ar.xlsx')}, content_type='multipart/form-data')
        self.assertTrue(r.get_json()['success'], r.get_json())
        inv = self.inv('36484')
        r = self.client.get(f"/receivables/invoice/{inv['id']}.pdf")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data.startswith(b'%PDF'))
        j = self.client.get(f"/receivables/api/invoice/{inv['id']}").get_json()
        self.assertTrue(j['success'])
        self.assertEqual(j['plan']['stage'], 'past_due')

    def test_dashboard_tile(self):
        self.login()
        self.assertIn(b'Open Receivables', self.client.get('/dashboard').data)
        self.login(role='technician', username='tech')
        self.assertNotIn(b'Open Receivables', self.client.get('/dashboard').data)


def aging_summary_xlsx(as_of, rows):
    """The office's A/R Aging Summary: one row per customer, notes typed into free cells."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(['EXAMPLE IRRIGATION INC.'])
    ws.append(['A/R Aging Summary Report'])
    ws.append([f"As of {as_of.strftime('%b %-d, %Y')}"])
    ws.append([])
    ws.append(['', 'CURRENT', '1 - 30', '31 - 60', '61 - 90', '91 AND OVER', 'Total'])
    for n, r in enumerate(rows, start=6):
        ws.append(list(r) + [None] * (6 - len(r)) + ([f'=B{n}+C{n}+D{n}+E{n}+F{n}'] if len(r) < 7 else []))
    ws.append(['TOTAL'])
    ws.append([' Tuesday, October 06, 2026 12:21 PM GMT-04:00'])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def jnode(num, client, total, balance, days_late, subject='Invoice'):
    issued = TODAY - timedelta(days=days_late + 30)
    due = TODAY - timedelta(days=days_late)
    return {'id': f'J{num}', 'invoiceNumber': num, 'subject': subject, 'invoiceStatus': 'past_due' if days_late > 0 else 'awaiting_payment',
            'issuedDate': issued.isoformat() + 'T12:00:00Z', 'dueDate': due.isoformat() + 'T04:00:00Z',
            'jobberWebUri': f'https://jobber.example/{num}', 'clientHubUri': f'https://hub.example/{num}',
            'amounts': {'total': total, 'invoiceBalance': balance, 'paymentsTotal': total - balance},
            'client': {'id': 'C' + client[:3], 'name': client, 'emails': [{'address': f'{_slug(client)}@example.com', 'primary': True}]},
            'lineItems': {'nodes': [{'name': 'Service', 'description': '', 'totalPrice': total}]}}


def _slug(name):
    return ''.join(ch for ch in name.lower() if ch.isalnum())[:12]


class FakeJobber:
    """Answers invoices(searchTerm) and invoice(id) like Jobber, from a list of invoice nodes."""

    def __init__(self, nodes):
        self.nodes = nodes
        self.searches = []

    def __call__(self, query, variables=None):
        variables = variables or {}
        if 'invoice(id:' in query:
            return {'invoice': next((n for n in self.nodes if n['id'] == variables['id']), None)}
        q = variables.get('q', '').lower()
        self.searches.append(q)
        words = [w for w in q.replace(',', ' ').split() if len(w) > 2]
        hits = [n for n in self.nodes if any(w in n['client']['name'].lower() for w in words) or q == str(n['invoiceNumber'])]
        return {'invoices': {'nodes': hits, 'pageInfo': {'hasNextPage': False, 'endCursor': None}}}


class SummaryTests(Base):
    def setUp(self):
        super().setUp()
        self.as_of = TODAY - timedelta(days=2)
        self.jobber = FakeJobber([
            jnode(501, 'Pat Example', 300, 300, 20),
            jnode(502, 'Lake Example HOA', 1200, 1200, 45),
            jnode(503, 'Lake Example HOA', 800, 800, -10),
            jnode(504, 'Board Example Condo', 900, 900, 40),
            jnode(505, 'Sample Builders', 100000, 5000, 120, 'PAY APP 3 - EXAMPLE PARK'),
            jnode(506, 'Sample Builders', 60000, 3000, 90, 'PAY APP 4 - EXAMPLE PARK'),
            jnode(507, 'Gc Example Construction', 2200, 2200, 20),
            jnode(508, 'Gc Example Construction', 40000, 4000, 70, 'PAY APP 1 - EXAMPLE PLAZA'),
            jnode(509, 'Pat Example Jr', 999, 999, 20),   # another client the search also finds
            jnode(510, 'Quiet Example', 400, 400, 10),
        ])
        R._jobber = self.jobber
        R._cfg['jobber_connected'] = lambda: True
        R._cfg['tier'] = 0

    def upload_summary(self, rows, as_of=None):
        rows_ = R._read_table(aging_summary_xlsx(as_of or self.as_of, rows), 'ar.xlsx')
        self.assertTrue(R.is_aging_summary(rows_))
        custs, as_of_text = R.parse_aging_summary(rows_)
        out = R.apply_summary(custs, 'Summary.xlsx', 'test', as_of_text)
        R.sync_summary_invoices()
        R.apply_sheet_notes()
        return out, custs

    ROWS = [
        ('Pat Example', None, 300, 'paid today'),
        ('Lake Example HOA', 800, 1200, 'Followed up no response yet'),
        ('Board Example Condo', None, None, 900, 'Board is disputing this. Working with Beatriz'),
        ('Sample Builders', None, None, None, 3000, 5000, 'All retainage. Said they will release it next month'),
        ('Gc Example Construction', None, 'followed up no response yet 2200', None, "all retainage ongoing can't collect", 4000),
        ('Quiet Example', None, 400),
        ('Credit Example', None, None, None, None, -105),
    ]

    def test_parse_notes_and_amounts(self):
        rows_ = R._read_table(aging_summary_xlsx(self.as_of, self.ROWS), 'ar.xlsx')
        custs, as_of = R.parse_aging_summary(rows_)
        self.assertEqual(as_of, self.as_of.isoformat())
        by = {c['name']: c for c in custs}
        self.assertEqual(by['Gc Example Construction']['total'], 6200)  # 2200 recovered from the note
        self.assertEqual(by['Gc Example Construction']['notes'][0], ('1-30', 'followed up no response yet 2200'))
        self.assertEqual(by['Sample Builders']['notes'], [('Total', 'All retainage. Said they will release it next month')])
        self.assertEqual(by['Credit Example']['total'], -105)
        self.assertNotIn('TOTAL', by)

    def test_upload_finds_invoices_and_acts_on_notes(self):
        out, _ = self.upload_summary(self.ROWS)
        self.assertEqual(out['owing'], 6)
        self.assertEqual(out['with_notes'], 5)
        self.assertIsNone(self.inv('509'))  # another client's invoice is not taken
        self.assertEqual(self.inv('501')['status'], 'reported_paid')
        lake = self.inv('502')
        self.assertEqual(lake['last_followup_at'], f'{self.as_of.isoformat()} 12:00:00')
        self.assertFalse(R.plan(lake, None, None, R.settings())['due_now'])
        self.assertEqual(self.inv('503')['last_followup_at'], None)  # not due yet, the note was not about it
        self.assertEqual(self.inv('504')['status'], 'needs_person')
        self.assertIn('disputing', self.inv('504')['needs_reason'])
        self.assertEqual((self.inv('505')['retainage'], self.inv('506')['retainage']), (1, 1))
        # "all retainage" typed in the 61-90 column: only that is retainage; the 1-30 invoice is still chased
        self.assertEqual(self.inv('507')['retainage'], 0)
        self.assertEqual(self.inv('508')['retainage'], 1)
        conn = R._conn()
        gc = dict(conn.execute("SELECT * FROM ar_customers WHERE key='gcexampleconstruction'").fetchone())
        conn.close()
        self.assertEqual(gc['retainage_hold'], 1)
        self.assertEqual(gc['qb_total'], 6200)
        p = R.plan(self.inv('508'), None, gc, R.settings())
        self.assertIn('still going', p['reason'])
        self.assertEqual(self.inv('510')['status'], 'open')

    def test_reupload_same_notes_is_quiet_and_dropped_customers_close(self):
        self.upload_summary(self.ROWS)
        conn = R._conn()
        conn.execute("UPDATE ar_invoices SET status='open', snooze_until='' WHERE number='501'")
        notes_before = conn.execute("SELECT COUNT(*) FROM ar_notes").fetchone()[0]
        conn.commit()
        conn.close()
        rows = [r for r in self.ROWS if r[0] != 'Quiet Example']
        self.upload_summary(rows)
        self.assertEqual(self.inv('501')['status'], 'open')   # same note: not acted on again
        self.assertEqual(self.inv('510')['status'], 'paid')   # no longer on the sheet
        conn = R._conn()
        added = conn.execute("SELECT COUNT(*) FROM ar_notes").fetchone()[0] - notes_before
        conn.close()
        self.assertEqual(added, 1)  # just the "paid" note on 510

    def test_changed_note_is_acted_on(self):
        self.upload_summary(self.ROWS)
        rows = list(self.ROWS)
        rows[2] = ('Board Example Condo', None, None, 900, 'Resolved with the board, check is in the mail')
        conn = R._conn()
        conn.execute("UPDATE ar_invoices SET status='open', needs_reason='' WHERE number='504'")
        conn.commit()
        conn.close()
        self.upload_summary(rows)
        self.assertEqual(self.inv('504')['status'], 'promised')

    def test_jobber_mismatch_flagged(self):
        self.upload_summary([('Quiet Example', None, 650, 'Followed up no response yet')])
        conn = R._conn()
        c = dict(conn.execute("SELECT * FROM ar_customers WHERE key='quietexample'").fetchone())
        conn.close()
        self.assertIn('Jobber shows $400.00', c['jobber_note'])

    def test_upload_route_detects_summary(self):
        self.login()
        R.run_cycle = lambda manual=False: True
        f = aging_summary_xlsx(self.as_of, self.ROWS)
        j = self.client.post('/receivables/api/upload', data={'file': (f, 'October.xlsx')},
                             content_type='multipart/form-data').get_json()
        self.assertTrue(j['success'], j)
        self.assertEqual(j['summary']['kind'], 'summary')


class SheetNoteRuleTests(unittest.TestCase):
    def test_rules(self):
        as_of = date(2026, 10, 6)
        r = R.interpret_sheet_note('1-30: Preparing a check. Will follow up again if not received by the 12th', as_of)
        self.assertEqual((r['intent'], r['follow_up_on']), ('promise', '2026-10-12'))
        r = R.interpret_sheet_note('31-60: still waiting on funding followed up again no response yet', as_of)
        self.assertEqual((r['intent'], r['followed_up']), ('waiting', True))
        r = R.interpret_sheet_note("Total: Retainage (still ongoing; can't collect)", as_of)
        self.assertEqual((r['intent'], r['retainage'], r['retainage_collectable']), ('retainage', 'some', False))
        self.assertEqual(R.interpret_sheet_note('31-60: charged card all paid now', as_of)['intent'], 'paid')
        self.assertEqual(R.interpret_sheet_note('31-60: they can pay by EOM', as_of)['promised_date'], '2026-10-31')


class JobberGuardTests(unittest.TestCase):
    def test_mutations_blocked(self):
        with self.assertRaises(RuntimeError):
            R._jobber('mutation { invoiceCreate(input: {}) { invoice { id } } }')


if __name__ == '__main__':
    unittest.main()
