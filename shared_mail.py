"""
The PO mailbox helpers the Office App (app.py) and the Pumps app (pumps.py) share:
signing in to Microsoft 365, listing new emails for a scanner, and reading their
attachments. Kept out of app.py so Pumps can run as its own Railway service
without loading the whole Office App.

Settings come from the same environment variables app.py has always read
(PO_EMAIL_ADDRESS, PO_EMAIL_PASSWORD, PO_EMAIL_PROVIDER, PO_EMAIL_IMAP_SERVER,
MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET).
"""
import base64
import email
import email.utils
import imaplib
import os
import sqlite3
from datetime import datetime
from email.header import decode_header

import requests as http_requests

try:
    import msal
    MSAL_AVAILABLE = True
except ImportError:
    MSAL_AVAILABLE = False

PO_EMAIL_ADDRESS = os.environ.get('PO_EMAIL_ADDRESS', '')
PO_EMAIL_PASSWORD = os.environ.get('PO_EMAIL_PASSWORD', '')
PO_EMAIL_PROVIDER = os.environ.get('PO_EMAIL_PROVIDER', 'outlook')  # 'outlook' or 'gmail'

PO_EMAIL_IMAP_SERVER = os.environ.get('PO_EMAIL_IMAP_SERVER', '')
if not PO_EMAIL_IMAP_SERVER:
    PO_EMAIL_IMAP_SERVER = 'imap.gmail.com' if PO_EMAIL_PROVIDER.lower() == 'gmail' else 'outlook.office365.com'
PO_EMAIL_IMAP_PORT = 993

MS_TENANT_ID = os.environ.get('MS_TENANT_ID', '')
MS_CLIENT_ID = os.environ.get('MS_CLIENT_ID', '')
MS_CLIENT_SECRET = os.environ.get('MS_CLIENT_SECRET', '')
MS_GRAPH_ENABLED = bool(MS_TENANT_ID and MS_CLIENT_ID and MS_CLIENT_SECRET and MSAL_AVAILABLE)

MONITORING_ENABLED = bool(PO_EMAIL_ADDRESS and PO_EMAIL_PASSWORD) or (MS_GRAPH_ENABLED and bool(PO_EMAIL_ADDRESS))

SCAN_LOG_TABLES = ('vendor_invoice_email_log', 'pump_email_scan_log', 'vib_email_log')


def graph_access_token():
    """Get OAuth2 access token using Client Credentials flow via MSAL"""
    authority = f"https://login.microsoftonline.com/{MS_TENANT_ID}"
    app = msal.ConfidentialClientApplication(
        MS_CLIENT_ID,
        authority=authority,
        client_credential=MS_CLIENT_SECRET,
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" in result:
        return result["access_token"]
    raise Exception(f"Graph auth failed: {result.get('error_description', result.get('error', 'Unknown'))}")


def fetch_scan_emails(db_path, log_table='vendor_invoice_email_log', extensions=('.pdf',), since=None,
                      plain_since=None):
    """
    Fetch emails for a scanner that keeps its own log table, so it runs
    independently of the PO scanner. log_table is the scanner's history
    (vendor_invoice_email_log, pump_email_scan_log or vib_email_log) in the database at db_path.
    extensions: attachment types worth fetching the email for (Pumps also
    wants Word reports). since: 'YYYY-MM-DD' - skip mail received before it.
    plain_since: 'YYYY-MM-DD' - also return emails with no wanted attachment
    received since then (Pumps reads plain service-call emails).
    Returns {'emails': [(uid, msg), ...], 'diagnostics': {...}, 'source': '...'}
    """
    if log_table not in SCAN_LOG_TABLES:
        raise ValueError(f'Unsupported scan log table: {log_table}')
    if not PO_EMAIL_ADDRESS:
        return {'emails': [], 'diagnostics': {'error': 'PO_EMAIL_ADDRESS not configured'}, 'source': 'none'}

    # Load already-scanned UIDs from the scanner's own log
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(f"SELECT email_uid FROM {log_table}")
    scanned_uids = {r[0] for r in c.fetchall()}
    conn.close()

    emails_out = []
    diagnostics = {'scanned_uids': len(scanned_uids)}
    exts = tuple(e.lower() for e in extensions)
    wants_pdf_type = '.pdf' in exts

    def _wanted(name, ctype=''):
        return (name or '').lower().endswith(exts) or (wants_pdf_type and ctype == 'application/pdf')

    if MS_GRAPH_ENABLED:
        try:
            token = graph_access_token()
            headers = {'Authorization': f'Bearer {token}'}
            url = f'https://graph.microsoft.com/v1.0/users/{PO_EMAIL_ADDRESS}/messages'
            graph_filter = 'hasAttachments eq true'
            if since:
                # Graph wants the $orderby field (receivedDateTime) first in $filter.
                graph_filter = f'receivedDateTime ge {since}T00:00:00Z and hasAttachments eq true'
            params = {
                '$filter': graph_filter,
                '$top': 100,
                '$select': 'id,subject,from,receivedDateTime,hasAttachments,bodyPreview',
                '$expand': 'attachments($select=id,name,contentType,size)',
                '$orderby': 'receivedDateTime desc',
            }
            while url:
                resp = http_requests.get(url, headers=headers, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                for msg_data in data.get('value', []):
                    msg_id = msg_data['id']
                    if msg_id in scanned_uids:
                        continue
                    atts = msg_data.get('attachments', [])
                    if any(_wanted(a.get('name', ''), a.get('contentType', '')) for a in atts):
                        emails_out.append((msg_id, msg_data))
                url = data.get('@odata.nextLink')
                params = None
            if plain_since:
                seen = {m for m, _ in emails_out}
                url = f'https://graph.microsoft.com/v1.0/users/{PO_EMAIL_ADDRESS}/messages'
                params = {'$filter': f'receivedDateTime ge {plain_since}T00:00:00Z', '$top': 100,
                          '$select': 'id,subject,from,receivedDateTime,hasAttachments,bodyPreview',
                          '$orderby': 'receivedDateTime desc'}
                while url:
                    resp = http_requests.get(url, headers=headers, params=params, timeout=30)
                    resp.raise_for_status()
                    data = resp.json()
                    for msg_data in data.get('value', []):
                        if msg_data['id'] not in scanned_uids and msg_data['id'] not in seen:
                            emails_out.append((msg_data['id'], msg_data))
                    url = data.get('@odata.nextLink')
                    params = None
            diagnostics['source'] = 'graph_api'
            diagnostics['found'] = len(emails_out)
        except Exception as e:
            diagnostics['error'] = str(e)
            diagnostics['source'] = 'graph_api'
    elif PO_EMAIL_PASSWORD:
        try:
            mail = imaplib.IMAP4_SSL(PO_EMAIL_IMAP_SERVER, PO_EMAIL_IMAP_PORT)
            mail.login(PO_EMAIL_ADDRESS, PO_EMAIL_PASSWORD)
            mail.select('INBOX')
            if since:
                imap_since = datetime.strptime(since, '%Y-%m-%d').strftime('%d-%b-%Y')
                status, uid_data = mail.uid('search', None, 'SINCE', imap_since)
            else:
                status, uid_data = mail.uid('search', None, 'ALL')
            if status == 'OK':
                for uid in reversed(uid_data[0].split()):
                    uid_str = uid.decode()
                    if uid_str in scanned_uids:
                        continue
                    status2, msg_data = mail.uid('fetch', uid, '(RFC822)')
                    if status2 == 'OK':
                        msg = email.message_from_bytes(msg_data[0][1])
                        # Only bother with emails that have the attachments we want
                        has_pdf = any(
                            (p.get_content_disposition() == 'attachment' or
                             p.get_content_maintype() == 'application') and
                            _wanted(p.get_filename() or '')
                            for p in msg.walk()
                        )
                        if has_pdf:
                            emails_out.append((uid_str, msg))
                        elif plain_since:
                            try:
                                sent = email.utils.parsedate_to_datetime(msg.get('Date', '')).strftime('%Y-%m-%d')
                            except (TypeError, ValueError):
                                sent = ''
                            if sent >= plain_since:
                                emails_out.append((uid_str, msg))
            mail.close()
            mail.logout()
            diagnostics['source'] = 'imap'
            diagnostics['found'] = len(emails_out)
        except Exception as e:
            diagnostics['error'] = str(e)
            diagnostics['source'] = 'imap'
    else:
        diagnostics['error'] = 'No email credentials configured'
        diagnostics['source'] = 'none'

    return {'emails': emails_out, 'diagnostics': diagnostics, 'source': diagnostics.get('source', 'none')}


def graph_attachments(msg_id, token=None):
    """
    Download attachments from a Graph API message.
    Returns list of (filename, file_content_bytes) tuples - same format as email_attachments.
    """
    if token is None:
        token = graph_access_token()

    headers = {'Authorization': f'Bearer {token}'}
    url = f"https://graph.microsoft.com/v1.0/users/{PO_EMAIL_ADDRESS}/messages/{msg_id}/attachments"
    response = http_requests.get(url, headers=headers)
    response.raise_for_status()

    attachments = []
    for att in response.json().get('value', []):
        if att.get('@odata.type') == '#microsoft.graph.fileAttachment':
            filename = att.get('name', 'unnamed')
            content_bytes = base64.b64decode(att['contentBytes'])
            attachments.append((filename, content_bytes))
            print(f"    📎 Downloaded attachment: {filename} ({len(content_bytes)} bytes)")
        elif att.get('@odata.type') == '#microsoft.graph.itemAttachment':
            # Forwarded email attachment - check for nested file attachments
            item_att_url = f"{url}/{att['id']}?$expand=microsoft.graph.itemAttachment/item"
            item_resp = http_requests.get(item_att_url, headers=headers)
            if item_resp.ok:
                item_data = item_resp.json()
                nested_item = item_data.get('item', {})
                if nested_item.get('attachments'):
                    for nested_att in nested_item['attachments']:
                        if nested_att.get('@odata.type') == '#microsoft.graph.fileAttachment':
                            filename = nested_att.get('name', 'unnamed')
                            content_bytes = base64.b64decode(nested_att['contentBytes'])
                            attachments.append((filename, content_bytes))
                            print(f"    📎 Downloaded nested attachment: {filename} ({len(content_bytes)} bytes)")

    return attachments


def email_attachments(msg):
    """
    Extract attachments from an email message
    Returns list of (filename, file_content) tuples
    """
    attachments = []
    try:
        for part in msg.walk():
            if part.get_content_disposition() == 'attachment':
                filename = part.get_filename()
                if filename:
                    # Decode filename if needed
                    if isinstance(filename, str):
                        # Handle encoded-word format
                        try:
                            decoded_parts = decode_header(filename)
                            filename = ''.join([part.decode(enc or 'utf-8') if isinstance(part, bytes) else part
                                               for part, enc in decoded_parts])
                        except:
                            pass

                    file_content = part.get_payload(decode=True)
                    attachments.append((filename, file_content))
                    print(f"  📎 Extracted attachment: {filename}")

        return attachments
    except Exception as e:
        print(f"✗ Error extracting attachments: {e}")
        return []
