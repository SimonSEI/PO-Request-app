"""
Pumps on its own: a small Flask app that runs pumps.py without the Office App,
so a Pumps update only redeploys Pumps (and an Office App update leaves Pumps
alone). Run it as its own Railway service:

    gunicorn --workers=2 --threads=4 --timeout=60 --bind=0.0.0.0:$PORT pumps_server:app

Pumps runs here only once the Office App has PUMPS_URL set (see
PUMPS_SERVICE.md); until then it runs inside the Office App (app.py).

People log in to the Office App, which sends them here with a signed ticket
(pumps_link.py). Receivables asks this service for the Jobber token.

Variables (full list in PUMPS_SERVICE.md): SECRET_KEY - the SAME value as the
Office App's, because Pumps' saved Jobber sign-in is encrypted with it;
PUMPS_SHARED_SECRET (also on the Office App); DATA_DIR (this service's own
volume); OFFICE_APP_URL; WEBSITE_URL (this service's own address); and the
PO_EMAIL_* / MS_* / PUMPS_* / ANTHROPIC_API_KEY variables the Office App has.
"""
import os
from datetime import timedelta

from flask import Flask, jsonify, redirect, request, session
from flask_wtf.csrf import CSRFProtect, generate_csrf

import pumps
import pumps_link
import shared_mail

try:
    import apscheduler  # noqa: F401
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False

app = Flask(__name__)
_secret_key = os.environ.get('SECRET_KEY')
if not _secret_key:
    raise RuntimeError("SECRET_KEY environment variable must be set to a strong random value")
app.secret_key = _secret_key
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', 'true').lower() != 'false'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)
app.config['WTF_CSRF_TIME_LIMIT'] = 43200  # 12 hour token lifetime
app.config['WTF_CSRF_HEADERS'] = ['X-CSRFToken', 'X-CSRF-Token']
csrf = CSRFProtect(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get('DATA_DIR', BASE_DIR)
DB_PATH = os.path.join(DATA_DIR, 'pumps.db')
OFFICE_APP_URL = os.environ.get('OFFICE_APP_URL', '').rstrip('/')
WEBSITE_URL = os.environ.get('WEBSITE_URL', 'http://localhost:5000')
SHARED_SECRET = os.environ.get('PUMPS_SHARED_SECRET', '')
# The switch-over: fetch the Office App's Pumps data once, on start-up (pumps_link.import_bundle).
OFFICE_INTERNAL_URL = os.environ.get('OFFICE_INTERNAL_URL', '').rstrip('/')
IMPORT_FROM_OFFICE = os.environ.get('PUMPS_IMPORT_FROM_OFFICE', '').lower() in ('1', 'true', 'yes')
print(f"✓ Pumps database: {DB_PATH}")


@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
        "font-src 'self' data:; connect-src 'self'"
    )
    # The Pumps page reads the CSRF token from this cookie, as in the Office App.
    response.set_cookie('csrf_token', generate_csrf(), samesite='Lax',
                        secure=app.config.get('SESSION_COOKIE_SECURE', True), httponly=False)
    return response


# pumps.py links to 'login' and 'dashboard'; both live in the Office App. Its
# /pumps sends a signed-in person straight back here with a fresh ticket.
@app.route('/login')
def login():
    if not OFFICE_APP_URL:
        return 'Open Pumps from the Office App dashboard (OFFICE_APP_URL is not set here).', 401
    return redirect(f'{OFFICE_APP_URL}/pumps')


@app.route('/')
def dashboard():
    return redirect(f'{OFFICE_APP_URL}/dashboard' if OFFICE_APP_URL else '/pumps')


@app.route('/health')
def health():
    return {'ok': True}


@app.route('/pumps/sso')
def sso():
    """The Office App's hand-off: a valid ticket signs this person in here."""
    who = pumps_link.read_ticket(SHARED_SECRET, request.args.get('t', ''))
    if not who:
        return redirect(f'{OFFICE_APP_URL}/login') if OFFICE_APP_URL else ('That sign-in link has expired.', 401)
    session.clear()
    session.permanent = True
    session['username'] = who['username']
    session['role'] = who['role']
    session['full_name'] = who['full_name'] or who['username']
    nxt = request.args.get('next', '')
    # Only ever on to a Pumps page here, never off-site.
    if not (nxt.startswith('/pumps') and '//' not in nxt and '\\' not in nxt):
        nxt = '/pumps'
    return redirect(nxt)


@app.route('/internal/jobber-token', methods=['POST'])
@csrf.exempt
def jobber_token():
    """Receivables' Jobber access, over the private network only."""
    if not request.host.split(':')[0].endswith('.railway.internal'):
        return jsonify({'error': 'Not found'}), 404
    if not pumps_link.secret_ok(SHARED_SECRET, request.headers.get('X-Pumps-Secret')):
        return jsonify({'error': 'Unauthorized'}), 401
    body = request.get_json(silent=True) or {}
    connected = bool(pumps.jobber_status()['connected'])
    if body.get('status_only') or not connected:
        return jsonify({'connected': connected})
    try:
        return jsonify({'connected': True, 'token': pumps._access_token(bool(body.get('force')))})
    except Exception as e:
        return jsonify({'connected': True, 'error': str(e)}), 502


if IMPORT_FROM_OFFICE:
    if not (OFFICE_INTERNAL_URL and SHARED_SECRET):
        raise RuntimeError('PUMPS_IMPORT_FROM_OFFICE needs OFFICE_INTERNAL_URL and PUMPS_SHARED_SECRET')
    # Fails loudly (the service doesn't start) rather than run on partial data.
    pumps_link.import_bundle(OFFICE_INTERNAL_URL + '/internal/pumps-export', SHARED_SECRET, DB_PATH, DATA_DIR)

pumps.init_pumps(app, csrf, DB_PATH, data_dir=DATA_DIR, secret_key=app.secret_key, website_url=WEBSITE_URL,
                 email_enabled=shared_mail.MONITORING_ENABLED,
                 fetch_emails=lambda **kw: shared_mail.fetch_scan_emails(DB_PATH, **kw),
                 graph_attachments=shared_mail.graph_attachments, email_attachments=shared_mail.email_attachments,
                 scheduler_available=SCHEDULER_AVAILABLE,
                 graph_token=shared_mail.graph_access_token if shared_mail.MS_GRAPH_ENABLED else None,
                 mail_from=shared_mail.PO_EMAIL_ADDRESS)
