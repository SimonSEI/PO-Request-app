"""
Pumps on its own: a small Flask app that runs pumps.py without the Office App,
so a Pumps update only redeploys Pumps (and an Office App update leaves Pumps
alone). Run it as its own Railway service:

    gunicorn --workers=2 --threads=4 --timeout=60 --bind=0.0.0.0:$PORT pumps_server:app

Not live yet: Pumps still runs inside the Office App (app.py) until the
switch-over. Until then this is for trying Pumps on its own locally.

Variables: SECRET_KEY (required), DATA_DIR (the service's own volume, e.g. /data),
OFFICE_APP_URL (where people log in), and the same PO_EMAIL_* / MS_* /
PUMPS_* / OPENCLAW_* / ANTHROPIC_API_KEY variables the Office App has for Pumps.
"""
import os
from datetime import timedelta

from flask import Flask, redirect
from flask_wtf.csrf import CSRFProtect, generate_csrf

import shared_mail
from pumps import init_pumps

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


# pumps.py links to 'login' and 'dashboard'; both live in the Office App.
@app.route('/login')
def login():
    return redirect(f'{OFFICE_APP_URL}/login' if OFFICE_APP_URL else '/pumps')


@app.route('/')
def dashboard():
    return redirect(f'{OFFICE_APP_URL}/dashboard' if OFFICE_APP_URL else '/pumps')


@app.route('/health')
def health():
    return {'ok': True}


init_pumps(app, csrf, DB_PATH, data_dir=DATA_DIR, secret_key=app.secret_key, website_url=WEBSITE_URL,
           email_enabled=shared_mail.MONITORING_ENABLED,
           fetch_emails=lambda **kw: shared_mail.fetch_scan_emails(DB_PATH, **kw),
           graph_attachments=shared_mail.graph_attachments, email_attachments=shared_mail.email_attachments,
           scheduler_available=SCHEDULER_AVAILABLE,
           graph_token=shared_mail.graph_access_token if shared_mail.MS_GRAPH_ENABLED else None,
           mail_from=shared_mail.PO_EMAIL_ADDRESS)
