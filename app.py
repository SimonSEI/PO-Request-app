from flask import Flask, render_template_string, request, redirect, url_for, session, flash, jsonify, send_from_directory
from datetime import datetime, timedelta
import uuid
import sqlite3
import os
import re
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Claude API for intelligent invoice matching
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    print("⚠ anthropic package not installed - Claude API matching disabled")

# Claude API configuration
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
USE_CLAUDE_MATCHING = os.environ.get('USE_CLAUDE_MATCHING', 'true').lower() == 'true'

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'irrigation-po-system-secret-key-2024')
APP_VERSION = "1.2.0"  # Added API verify endpoint
# Multi-session support
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)
active_sessions = {}

def create_session_id():
    return str(uuid.uuid4())

def save_user_session(session_id, user_data):
    active_sessions[session_id] = {
        'username': user_data['username'],
        'role': user_data['role'],
        'email': user_data.get('email'),
        'full_name': user_data.get('full_name'),
        'created_at': datetime.now(),
        'last_activity': datetime.now()
    }

def cleanup_expired_sessions():
    now = datetime.now()
    expired = [sid for sid, data in active_sessions.items()
               if (now - data['last_activity']).total_seconds() > 86400]
    for session_id in expired:
        del active_sessions[session_id]

@app.before_request
def before_request():
    cleanup_expired_sessions()
    session.permanent = True

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Use persistent data directory from environment variable (for Railway volumes)
# This prevents data loss on app updates/redeployments
DATA_DIR = os.environ.get('DATA_DIR', BASE_DIR)
print(f"✓ Using data directory: {DATA_DIR}")

app.config['UPLOAD_FOLDER'] = os.path.join(DATA_DIR, 'invoice_uploads')
app.config['BULK_UPLOAD_FOLDER'] = os.path.join(DATA_DIR, 'bulk_uploads')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB for bulk uploads

try:
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, mode=0o755)
        print(f"✓ Created data directory: {DATA_DIR}")
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'], mode=0o755)
        print(f"✓ Created folder: {app.config['UPLOAD_FOLDER']}")
    if not os.path.exists(app.config['BULK_UPLOAD_FOLDER']):
        os.makedirs(app.config['BULK_UPLOAD_FOLDER'], mode=0o755)
        print(f"✓ Created folder: {app.config['BULK_UPLOAD_FOLDER']}")
except Exception as e:
    print(f"✗ ERROR with folder: {e}")

# Database path - use persistent data directory to prevent data loss
DB_PATH = os.path.join(DATA_DIR, 'po_requests.db')
print(f"✓ Database path: {DB_PATH}")

# Check if PDF libraries are available
try:
    import PyPDF2
    import pdfplumber
    PDF_SUPPORT = True
    print("✓ PDF processing libraries available")
except ImportError:
    PDF_SUPPORT = False
    print("⚠ PDF processing not available - install with: pip3 install --user PyPDF2 pdfplumber")

# Check if OCR libraries are available (for scanned PDFs)
try:
    import pytesseract
    from pdf2image import convert_from_path
    from PIL import Image
    OCR_SUPPORT = True
    print("✓ OCR libraries available (can process scanned PDFs)")
except ImportError:
    OCR_SUPPORT = False
    print("⚠ OCR not available - scanned PDFs won't be processed")

def extract_text_with_ocr(pdf_path, page_num):
    """Extract text from a scanned PDF page using OCR"""
    if not OCR_SUPPORT:
        return ''
    try:
        # Convert specific page to image (page_num is 1-indexed)
        images = convert_from_path(pdf_path, first_page=page_num, last_page=page_num, dpi=300)
        if images:
            # Use Tesseract to extract text
            text = pytesseract.image_to_string(images[0])
            print(f"  📷 OCR extracted {len(text)} chars from page {page_num}")
            return text
    except Exception as e:
        print(f"  ⚠ OCR failed for page {page_num}: {e}")
    return ''

# Telegram Configuration
TELEGRAM_ENABLED = True
TELEGRAM_BOT_TOKEN = '8311194615:AAFoTZmMtjZMIeIWoY8JPUs6ofC9PCbAzQM'
TELEGRAM_CHAT_ID = '8085851472'

# Email Configuration for Password Reset
EMAIL_ENABLED = False
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
EMAIL_ADDRESS = 'YOUR_EMAIL@gmail.com'
EMAIL_PASSWORD = 'YOUR_APP_PASSWORD'
WEBSITE_URL = os.environ.get('WEBSITE_URL', 'http://localhost:5000')

# ... rest of your code continues ...

def send_telegram_notification(po_id, tech_name, job_name, cost):
    """Send Telegram message when new PO is submitted"""
    if not TELEGRAM_ENABLED:
        return

    try:
        import requests

        message = f"""🔔 NEW PO REQUEST

PO #{po_id:04d}
Tech: {tech_name}
Job: {job_name}
Est Cost: ${cost:.2f}

View at: simonweardon3.pythonanywhere.com"""

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        }

        response = requests.post(url, data=data)
        if response.status_code == 200:
            print(f"✓ Telegram notification sent for PO #{po_id}")
        else:
            print(f"✗ Telegram notification failed: {response.text}")

    except Exception as e:
        print(f"✗ Telegram error: {e}")

def send_reset_email(email, reset_token):
    """Send password reset email"""
    if not EMAIL_ENABLED:
        return False

    try:
        reset_link = f"{WEBSITE_URL}/reset_password/{reset_token}"

        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Password Reset - Irrigation PO System'
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = email

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <div style="max-width: 600px; margin: 0 auto; background: #f9f9f9; padding: 30px; border-radius: 10px;">
                <h2 style="color: #667eea;">🔐 Password Reset Request</h2>
                <p>You requested a password reset for your Irrigation PO System account.</p>
                <p>Click the button below to reset your password:</p>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{reset_link}"
                       style="background: #667eea; color: white; padding: 15px 30px;
                              text-decoration: none; border-radius: 5px; font-weight: bold;
                              display: inline-block;">
                        Reset Password
                    </a>
                </div>
                <p style="color: #666; font-size: 14px;">Or copy this link:</p>
                <p style="background: #fff; padding: 10px; border-radius: 5px; word-break: break-all;">
                    {reset_link}
                </p>
                <p style="color: #999; font-size: 12px; margin-top: 30px;">
                    This link will expire in 1 hour.<br>
                    If you didn't request this, please ignore this email.
                </p>
            </div>
        </body>
        </html>
        """

        part = MIMEText(html, 'html')
        msg.attach(part)

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.send_message(msg)

        print(f"✓ Password reset email sent to {email}")
        return True
    except Exception as e:
        print(f"✗ Email error: {e}")
        return False

def log_activity(username, action, target_type, target_id, details=''):
    """Log user activity for audit trail"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Get user email
        c.execute("SELECT email FROM users WHERE username=?", (username,))
        user = c.fetchone()
        user_email = user[0] if user and user[0] else 'N/A'

        c.execute("""INSERT INTO activity_log
                     (username, user_email, action, target_type, target_id, details, timestamp)
                     VALUES (?, ?, ?, ?, ?, ?, ?)""",
                 (username, user_email, action, target_type, target_id, details,
                  datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        conn.close()
        print(f"✓ Logged: {username} - {action}")
    except Exception as e:
        print(f"✗ Activity log error: {e}")

def init_db():
    """Initialize database with tables and default users"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Users table with email
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY,
                  username TEXT UNIQUE,
                  password TEXT,
                  role TEXT,
                  email TEXT,
                  full_name TEXT,
                  created_date TEXT,
                  last_login TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS po_requests
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  tech_username TEXT, tech_name TEXT, job_name TEXT, store_name TEXT,
                  estimated_cost REAL, description TEXT, status TEXT DEFAULT 'pending',
                  request_date TEXT, approval_date TEXT, approval_notes TEXT,
                  approved_by TEXT, invoice_filename TEXT, invoice_number TEXT,
                  invoice_cost TEXT, invoice_date TEXT, invoice_upload_date TEXT)''')

    # Jobs table
    c.execute('''CREATE TABLE IF NOT EXISTS jobs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  job_name TEXT UNIQUE,
                  year INTEGER,
                  created_date TEXT,
                  active INTEGER DEFAULT 1)''')

    # Activity log table - THIS WAS MISSING!
    c.execute('''CREATE TABLE IF NOT EXISTS activity_log
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT,
                  user_email TEXT,
                  action TEXT,
                  target_type TEXT,
                  target_id INTEGER,
                  details TEXT,
                  timestamp TEXT)''')

    # Password reset tokens table
    c.execute('''CREATE TABLE IF NOT EXISTS password_reset_tokens
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  token TEXT UNIQUE,
                  created_at TEXT,
                  expires_at TEXT,
                  used INTEGER DEFAULT 0)''')

    # App settings table
    c.execute('''CREATE TABLE IF NOT EXISTS app_settings
                 (key TEXT PRIMARY KEY,
                  value TEXT,
                  updated_at TEXT)''')

    # Claude API usage log
    c.execute('''CREATE TABLE IF NOT EXISTS claude_api_log
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  timestamp TEXT,
                  invoice_text_preview TEXT,
                  matched_po INTEGER,
                  matched_job TEXT,
                  confidence REAL,
                  input_tokens INTEGER,
                  output_tokens INTEGER,
                  cost_estimate REAL,
                  success INTEGER)''')

    # Add match_method column to po_requests if it doesn't exist
    try:
        c.execute("ALTER TABLE po_requests ADD COLUMN match_method TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Default settings
    default_settings = [
        ('claude_matching_enabled', 'true', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
    ]
    for key, value, updated_at in default_settings:
        try:
            c.execute("INSERT OR IGNORE INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)",
                     (key, value, updated_at))
        except:
            pass

    # Default users (techs only - office users register themselves)
    users = [
        ('tech1', 'tech123', 'technician', None, 'Tech One', datetime.now().strftime('%Y-%m-%d'), None),
        ('tech2', 'tech123', 'technician', None, 'Tech Two', datetime.now().strftime('%Y-%m-%d'), None),
        ('tech3', 'tech123', 'technician', None, 'Tech Three', datetime.now().strftime('%Y-%m-%d'), None),
        ('tech4', 'tech123', 'technician', None, 'Tech Four', datetime.now().strftime('%Y-%m-%d'), None),
        ('tech5', 'tech123', 'technician', None, 'Tech Five', datetime.now().strftime('%Y-%m-%d'), None),
    ]

    for user_data in users:
        try:
            c.execute("INSERT INTO users VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)", user_data)
        except sqlite3.IntegrityError:
            pass

    # Add default jobs if empty
    c.execute("SELECT COUNT(*) FROM jobs")
    if c.fetchone()[0] == 0:
        default_jobs = [
            ('Chase Bank', 2024),
            ('Seven Lakes', 2025),
            ('Downtown Plaza', 2025),
        ]
        for job_name, year in default_jobs:
            c.execute("INSERT INTO jobs (job_name, year, created_date) VALUES (?, ?, ?)",
                     (job_name, year, datetime.now().strftime('%Y-%m-%d')))

    conn.commit()
    conn.close()
    print("✓ Database initialized successfully")

@app.route('/update_database_schema')
def update_database_schema():
    """One-time database update to add new columns"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Add new columns to users table if they don't exist
        try:
            c.execute("ALTER TABLE users ADD COLUMN email TEXT")
            print("✓ Added email column")
        except sqlite3.OperationalError:
            print("Email column already exists")

        try:
            c.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
            print("✓ Added full_name column")
        except sqlite3.OperationalError:
            print("Full_name column already exists")

        try:
            c.execute("ALTER TABLE users ADD COLUMN created_date TEXT")
            print("✓ Added created_date column")
        except sqlite3.OperationalError:
            print("Created_date column already exists")

        try:
            c.execute("ALTER TABLE users ADD COLUMN last_login TEXT")
            print("✓ Added last_login column")
        except sqlite3.OperationalError:
            print("Last_login column already exists")

        # Create activity_log table if it doesn't exist
        c.execute('''CREATE TABLE IF NOT EXISTS activity_log
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      username TEXT,
                      user_email TEXT,
                      action TEXT,
                      target_type TEXT,
                      target_id INTEGER,
                      details TEXT,
                      timestamp TEXT)''')
        print("✓ Activity log table created")

        conn.commit()
        conn.close()

        return "Database updated successfully! You can now <a href='/'>login</a>. (You can delete this route now)"
    except Exception as e:
        return f"Error: {str(e)}"

def format_po_number(po_id, job_name):
    """Format PO number with S prefix for Service jobs"""
    if job_name and job_name.lower() == 'service':
        return f"S{po_id:04d}"
    return f"{po_id:04d}"

# Make this available to templates
app.jinja_env.globals.update(format_po_number=format_po_number)


def normalize_text_for_matching(text):
    """
    Normalize text for fuzzy matching:
    - Convert to uppercase
    - Remove extra spaces
    - Remove common punctuation
    """
    if not text:
        return ""
    # Convert to uppercase
    text = text.upper()
    # Replace multiple spaces with single space
    text = re.sub(r'\s+', ' ', text)
    # Remove common punctuation but keep alphanumeric and spaces
    text = re.sub(r'[^\w\s]', '', text)
    return text.strip()


def fuzzy_match_score(text1, text2):
    """
    Calculate a similarity score between two strings.
    Returns a score from 0 to 1, where 1 is an exact match.
    Uses character-based matching that tolerates:
    - Extra/missing spaces
    - Minor misspellings
    - Character transpositions
    """
    if not text1 or not text2:
        return 0.0

    # Normalize both texts
    t1 = normalize_text_for_matching(text1)
    t2 = normalize_text_for_matching(text2)

    if not t1 or not t2:
        return 0.0

    # Exact match after normalization
    if t1 == t2:
        return 1.0

    # Also try without any spaces (handles "HERONS GLEN" vs "HERONSGLEN")
    t1_no_space = t1.replace(' ', '')
    t2_no_space = t2.replace(' ', '')

    if t1_no_space == t2_no_space:
        return 0.98  # Very high score for space-only differences

    # Calculate Levenshtein-like similarity
    # Use the longer string as the reference
    longer = t1_no_space if len(t1_no_space) >= len(t2_no_space) else t2_no_space
    shorter = t2_no_space if len(t1_no_space) >= len(t2_no_space) else t1_no_space

    if len(longer) == 0:
        return 0.0

    # Simple edit distance calculation
    distance = levenshtein_distance(shorter, longer)

    # Convert to similarity score (0 to 1)
    max_len = len(longer)
    similarity = 1.0 - (distance / max_len)

    return max(0.0, similarity)


def levenshtein_distance(s1, s2):
    """
    Calculate the Levenshtein distance between two strings.
    This is the minimum number of single-character edits needed
    to transform one string into the other.
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)

    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            # Cost is 0 if characters match, 1 otherwise
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def find_job_name_in_text(text, job_name, threshold=0.75):
    """
    Search for a job name in text using fuzzy matching.
    Returns (found, position, matched_text, score) tuple.

    Handles:
    - Misspellings (e.g., "HERONS GELN" for "HERONS GLEN")
    - Extra spaces (e.g., "HERONS  GLEN" or "HER ONS GLEN")
    - Missing spaces (e.g., "HERONSGLEN" for "HERONS GLEN")
    """
    if not text or not job_name:
        return (False, -1, None, 0.0)

    text_upper = text.upper()
    job_upper = job_name.upper().strip()
    job_no_spaces = job_upper.replace(' ', '').replace('-', '').replace('_', '')

    # First, try exact match (with normalization)
    job_normalized = normalize_text_for_matching(job_name)

    # Try exact substring match
    if job_normalized in normalize_text_for_matching(text):
        pos = text_upper.find(job_upper)
        if pos == -1:
            # Try without spaces
            pos = text_upper.replace(' ', '').find(job_no_spaces)
        return (True, pos if pos >= 0 else 0, job_normalized, 1.0)

    # Try finding job name without spaces in text without spaces
    text_no_spaces = text_upper.replace(' ', '')
    if job_no_spaces in text_no_spaces:
        # Find approximate position in original text
        pos = text_no_spaces.find(job_no_spaces)
        return (True, pos, job_no_spaces, 0.98)

    # Sliding window fuzzy match
    # Use window sizes based on job name length
    job_len = len(job_no_spaces)
    best_score = 0.0
    best_pos = -1
    best_match = None

    # Create a version of text without spaces for matching
    # but keep track of positions
    words = text_upper.split()

    # Try matching against consecutive word groups
    for window_size in range(1, min(5, len(words) + 1)):
        for i in range(len(words) - window_size + 1):
            window_words = words[i:i + window_size]
            window_text = ''.join(window_words)  # No spaces for comparison

            # Only consider windows of similar length
            if abs(len(window_text) - job_len) > max(3, job_len * 0.3):
                continue

            score = fuzzy_match_score(window_text, job_no_spaces)

            if score > best_score and score >= threshold:
                best_score = score
                best_match = ' '.join(window_words)
                # Find position in original text
                try:
                    best_pos = text_upper.find(window_words[0])
                except:
                    best_pos = 0

    if best_score >= threshold:
        return (True, best_pos, best_match, best_score)

    return (False, -1, None, best_score)


def get_active_job_names():
    """Get all active job names from the database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT job_name FROM jobs WHERE active=1")
        jobs = [row[0] for row in c.fetchall()]
        conn.close()
        return jobs
    except Exception as e:
        print(f"Error getting active jobs: {e}")
        return []


def get_setting(key, default=None):
    """Get an app setting from the database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT value FROM app_settings WHERE key=?", (key,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else default
    except Exception as e:
        print(f"Error getting setting {key}: {e}")
        return default


def set_setting(key, value):
    """Set an app setting in the database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""INSERT OR REPLACE INTO app_settings (key, value, updated_at)
                     VALUES (?, ?, ?)""",
                 (key, value, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error setting {key}: {e}")
        return False


def is_claude_matching_enabled():
    """Check if Claude API matching is enabled"""
    if not ANTHROPIC_AVAILABLE or not ANTHROPIC_API_KEY:
        return False
    setting = get_setting('claude_matching_enabled', 'true')
    return setting.lower() == 'true'


def log_claude_api_usage(invoice_text, matched_po, matched_job, confidence, input_tokens, output_tokens, success):
    """Log Claude API usage for tracking costs"""
    try:
        # Estimate cost (Claude Sonnet pricing: $3/M input, $15/M output)
        cost_estimate = (input_tokens * 3 / 1_000_000) + (output_tokens * 15 / 1_000_000)

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""INSERT INTO claude_api_log
                     (timestamp, invoice_text_preview, matched_po, matched_job, confidence,
                      input_tokens, output_tokens, cost_estimate, success)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                 (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                  invoice_text[:200] if invoice_text else '',
                  matched_po,
                  matched_job,
                  confidence,
                  input_tokens,
                  output_tokens,
                  cost_estimate,
                  1 if success else 0))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error logging Claude API usage: {e}")


def match_invoice_with_claude(invoice_text, active_jobs, po_map):
    """
    Use Claude API to intelligently match invoice text to a job name and PO number.

    This handles:
    - Misspellings (e.g., "HERONS GELN" -> "Herons Glen")
    - OCR errors (e.g., "Her0ns Glen" -> "Herons Glen")
    - Spacing issues (e.g., "HERONSGLEN" or "HER ONS GLEN")
    - Abbreviations and variations

    Returns: (po_number, job_name, confidence) or (None, None, 0) if no match
    """
    # Check if Claude matching is enabled (checks both env vars and DB setting)
    if not is_claude_matching_enabled():
        print("  ⚠ Claude API matching not available or disabled")
        return (None, None, 0)

    if not active_jobs or not po_map:
        return (None, None, 0)

    # Build context about available POs
    po_info_list = []
    for po_id, info in po_map.items():
        po_info_list.append(f"PO #{po_id}: Job '{info.get('job_name', 'Unknown')}'")

    po_context = "\n".join(po_info_list)
    jobs_list = ", ".join(active_jobs)

    # Limit invoice text to avoid token limits
    invoice_excerpt = invoice_text[:3000] if len(invoice_text) > 3000 else invoice_text

    prompt = f"""Analyze this invoice text and find which job it belongs to.

ACTIVE JOB NAMES IN SYSTEM:
{jobs_list}

APPROVED PO NUMBERS WAITING FOR INVOICES:
{po_context}

INVOICE TEXT:
{invoice_excerpt}

TASK:
1. Find any job name from the active jobs list that appears in the invoice (even if misspelled, has OCR errors, spacing issues, or is abbreviated)
2. Find the PO number associated with that job in the invoice
3. Match it to one of the approved PO numbers listed above

IMPORTANT:
- Job names may be misspelled (e.g., "HERONS GELN" instead of "Herons Glen")
- Job names may have spacing issues (e.g., "HERONSGLEN" or "HER ONS GLEN")
- Job names may have OCR errors (e.g., "Her0ns G1en" with zeros instead of O's)
- The PO number is usually a 3-5 digit number near the job name
- Only match to PO numbers from the approved list above

Respond in EXACTLY this format (nothing else):
MATCHED: [yes/no]
JOB_NAME: [the job name from the active list, or "none"]
PO_NUMBER: [the PO number from approved list, or "none"]
CONFIDENCE: [high/medium/low]
REASONING: [brief explanation of how you matched it]"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        response_text = message.content[0].text
        print(f"  🤖 Claude response:\n{response_text}")

        # Get token usage for logging
        input_tokens = message.usage.input_tokens if hasattr(message, 'usage') else 0
        output_tokens = message.usage.output_tokens if hasattr(message, 'usage') else 0

        # Parse the response
        lines = response_text.strip().split('\n')
        result = {}
        for line in lines:
            if ':' in line:
                key, value = line.split(':', 1)
                result[key.strip().upper()] = value.strip()

        matched = result.get('MATCHED', 'no').lower() == 'yes'
        job_name = result.get('JOB_NAME', 'none')
        po_number_str = result.get('PO_NUMBER', 'none')
        confidence = result.get('CONFIDENCE', 'low')
        reasoning = result.get('REASONING', '')

        if not matched or job_name.lower() == 'none' or po_number_str.lower() == 'none':
            print(f"  ⚠ Claude found no match. Reasoning: {reasoning}")
            # Log unsuccessful attempt
            log_claude_api_usage(invoice_text, None, None, 0, input_tokens, output_tokens, False)
            return (None, None, 0)

        # Convert PO number to int and verify it exists
        try:
            po_number = int(po_number_str)
            if po_number not in po_map:
                print(f"  ⚠ Claude suggested PO {po_number} but it's not in approved list")
                log_claude_api_usage(invoice_text, po_number, job_name, 0, input_tokens, output_tokens, False)
                return (None, None, 0)
        except ValueError:
            print(f"  ⚠ Claude returned invalid PO number: {po_number_str}")
            log_claude_api_usage(invoice_text, None, job_name, 0, input_tokens, output_tokens, False)
            return (None, None, 0)

        confidence_score = {'high': 0.95, 'medium': 0.80, 'low': 0.60}.get(confidence.lower(), 0.5)

        print(f"  ✅ Claude matched: PO {po_number}, Job '{job_name}', Confidence: {confidence}")
        print(f"     Reasoning: {reasoning}")

        # Log successful match
        log_claude_api_usage(invoice_text, po_number, job_name, confidence_score, input_tokens, output_tokens, True)

        return (po_number, job_name, confidence_score)

    except anthropic.APIError as e:
        print(f"  ❌ Claude API error: {e}")
        log_claude_api_usage(invoice_text, None, None, 0, 0, 0, False)
        return (None, None, 0)
    except Exception as e:
        print(f"  ❌ Error calling Claude API: {e}")
        log_claude_api_usage(invoice_text, None, None, 0, 0, 0, False)
        return (None, None, 0)


@app.route('/register', methods=['GET', 'POST'])
def register():
    """Office manager self-registration"""
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        email = request.form['email'].strip()
        full_name = request.form['full_name'].strip()

        # Validation
        if not username or not password or not email or not full_name:
            flash('All fields are required')
            return render_template_string(REGISTER_TEMPLATE)

        if password != confirm_password:
            flash('Passwords do not match')
            return render_template_string(REGISTER_TEMPLATE)

        if len(password) < 6:
            flash('Password must be at least 6 characters')
            return render_template_string(REGISTER_TEMPLATE)

        # Email validation
        if '@' not in email or '.' not in email:
            flash('Invalid email address')
            return render_template_string(REGISTER_TEMPLATE)

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Check if username exists
        c.execute("SELECT * FROM users WHERE username=?", (username,))
        if c.fetchone():
            flash('Username already exists')
            conn.close()
            return render_template_string(REGISTER_TEMPLATE)

        # Check if email exists
        c.execute("SELECT * FROM users WHERE email=?", (email,))
        if c.fetchone():
            flash('Email already registered')
            conn.close()
            return render_template_string(REGISTER_TEMPLATE)

        # Create office user account
        try:
            c.execute("""INSERT INTO users
                         (username, password, role, email, full_name, created_date, last_login)
                         VALUES (?, ?, 'office', ?, ?, ?, NULL)""",
                     (username, password, email, full_name, datetime.now().strftime('%Y-%m-%d')))
            conn.commit()

            # Log activity
            log_activity(username, 'REGISTERED', 'user', None, f'New office account created: {email}')

            flash(f'Account created successfully! Please log in.')
            conn.close()
            return redirect(url_for('login'))
        except Exception as e:
            conn.close()
            flash(f'Error creating account: {str(e)}')
            return render_template_string(REGISTER_TEMPLATE)

    return render_template_string(REGISTER_TEMPLATE)

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # CREATE THE TABLE IF IT DOESN'T EXIST (Safety check)
        c.execute('''CREATE TABLE IF NOT EXISTS password_reset_tokens
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      token TEXT UNIQUE,
                      created_at TEXT,
                      expires_at TEXT,
                      used INTEGER DEFAULT 0)''')
        conn.commit()

        # Find user by email
        c.execute("SELECT id, username FROM users WHERE LOWER(email)=?", (email,))
        user = c.fetchone()

        if user:
            user_id, username = user

            # Generate secure reset token
            reset_token = secrets.token_urlsafe(32)

            # Token expires in 1 hour
            created_at = datetime.now()
            expires_at = created_at.replace(hour=created_at.hour + 1)

            c.execute("""INSERT INTO password_reset_tokens
                        (user_id, token, created_at, expires_at)
                        VALUES (?, ?, ?, ?)""",
                     (user_id, reset_token,
                      created_at.strftime('%Y-%m-%d %H:%M:%S'),
                      expires_at.strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit()

            # Send email
            if send_reset_email(email, reset_token):
                flash('✓ Password reset link sent to your email!')
            else:
                flash('⚠ Email not configured. Contact administrator.')
        else:
            # Don't reveal if email exists (security best practice)
            flash('✓ If that email exists, a reset link has been sent.')

        conn.close()
        return redirect(url_for('forgot_password'))

    return render_template_string(FORGOT_PASSWORD_TEMPLATE)

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """Password reset form"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Check if token is valid
    c.execute("""SELECT rt.id, rt.user_id, rt.expires_at, rt.used, u.username, u.email
                 FROM password_reset_tokens rt
                 JOIN users u ON rt.user_id = u.id
                 WHERE rt.token=?""", (token,))
    result = c.fetchone()

    if not result:
        conn.close()
        flash('❌ Invalid or expired reset link')
        return redirect(url_for('login'))

    token_id, user_id, expires_at, used, username, email = result

    # Check if token is expired
    expires_datetime = datetime.strptime(expires_at, '%Y-%m-%d %H:%M:%S')
    if datetime.now() > expires_datetime or used == 1:
        conn.close()
        flash('❌ This reset link has expired')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        new_password = request.form['password']
        confirm_password = request.form['confirm_password']

        if len(new_password) < 6:
            flash('❌ Password must be at least 6 characters')
            return render_template_string(RESET_PASSWORD_TEMPLATE, token=token, email=email)

        if new_password != confirm_password:
            flash('❌ Passwords do not match')
            return render_template_string(RESET_PASSWORD_TEMPLATE, token=token, email=email)

        # Update password
        c.execute("UPDATE users SET password=? WHERE id=?", (new_password, user_id))

        # Mark token as used
        c.execute("UPDATE password_reset_tokens SET used=1 WHERE id=?", (token_id,))

        conn.commit()
        conn.close()

        # Log the password reset
        log_activity(username, 'PASSWORD_RESET', 'user', user_id, 'Password reset via email')

        flash('✓ Password reset successful! Please login with your new password.')
        return redirect(url_for('login'))

    conn.close()
    return render_template_string(RESET_PASSWORD_TEMPLATE, token=token, email=email)

@app.route('/generate_reset_link')
def generate_reset_link():
    """Temporary test route"""
    # Get first office user
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, email FROM users WHERE role='office' LIMIT 1")
    user = c.fetchone()

    if not user:
        return "No office users found"

    user_id, username, email = user
    reset_token = secrets.token_urlsafe(32)

    from datetime import timedelta
    created_at = datetime.now()
    expires_at = created_at + timedelta(hours=1)

    c.execute("""INSERT INTO password_reset_tokens
                 (user_id, token, created_at, expires_at, used)
                 VALUES (?, ?, ?, ?, 0)""",
             (user_id, reset_token,
              created_at.strftime('%Y-%m-%d %H:%M:%S'),
              expires_at.strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()

    reset_link = f"{WEBSITE_URL}/reset_password/{reset_token}"
    return f"<h2>Test Reset Link Generated</h2><p>User: {username} ({email})</p><p><a href='{reset_link}'>{reset_link}</a></p>"

# ADD THIS NEW ROUTE to validate job names
@app.route('/validate_job', methods=['POST'])
def validate_job():
    """Validate if a job name exists in the database"""
    if 'username' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'})

    try:
        data = request.get_json()
        job_name = data.get('job_name', '').strip()

        if not job_name:
            return jsonify({'valid': False})

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Check if job exists (case-insensitive for better UX)
        c.execute("SELECT job_name FROM jobs WHERE LOWER(job_name) = LOWER(?) AND active=1", (job_name,))
        result = c.fetchone()
        conn.close()

        if result:
            # Return the correct spelling from database
            return jsonify({'valid': True, 'correct_name': result[0]})
        else:
            return jsonify({'valid': False})

    except Exception as e:
        return jsonify({'valid': False, 'error': str(e)})

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].lower()
        password = request.form['password']

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE LOWER(username)=? AND password=?", (username, password))
        user = c.fetchone()

        if user:
            actual_username = user[1]

            # Update last login
            c.execute("UPDATE users SET last_login=? WHERE username=?",
                     (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), actual_username))
            conn.commit()


            session_id = create_session_id()
            user_data = {
                'username': actual_username,
                'role': user[3],
                'email': user[4] if len(user) > 4 else None,
                'full_name': user[5] if len(user) > 5 else actual_username
            }
            save_user_session(session_id, user_data)
            session['session_id'] = session_id
            session['username'] = actual_username
            session['role'] = user[3]
            session['email'] = user[4] if len(user) > 4 else None
            session['full_name'] = user[5] if len(user) > 5 else actual_username

            log_activity(actual_username, 'LOGIN', 'session', None, 'User logged in')

            conn.close()

            if user[3] == 'technician':
                return redirect(url_for('tech_dashboard'))
            elif user[3] == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('office_dashboard'))
        else:
            conn.close()
            flash('Invalid credentials')
    return render_template_string(LOGIN_TEMPLATE)

@app.route('/tech_dashboard')
def tech_dashboard():
    if 'username' not in session or session['role'] != 'technician':
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM po_requests WHERE status='pending' ORDER BY id DESC")
    requests = c.fetchall()

    # Get column indices
    c.execute("PRAGMA table_info(po_requests)")
    columns = {col[1]: col[0] for col in c.fetchall()}
    conn.close()

    inv_filename_idx = columns.get('invoice_filename', 12)
    inv_number_idx = columns.get('invoice_number', 13)
    inv_cost_idx = columns.get('invoice_cost', 14)
    inv_upload_idx = columns.get('invoice_upload_date', 16)

    return render_template_string(TECH_DASHBOARD_TEMPLATE,
                                username=session['username'],
                                requests=requests,
                                inv_filename_idx=inv_filename_idx,
                                inv_number_idx=inv_number_idx,
                                inv_cost_idx=inv_cost_idx,
                                inv_upload_idx=inv_upload_idx)

@app.route('/office_dashboard')
def office_dashboard():
    if 'username' not in session or session['role'] != 'office':
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Get column info to determine correct indices
    c.execute("PRAGMA table_info(po_requests)")
    columns = {col[1]: col[0] for col in c.fetchall()}

    # Determine column indices
    inv_filename_idx = columns.get('invoice_filename', 12)
    inv_number_idx = columns.get('invoice_number', 13)
    inv_cost_idx = columns.get('invoice_cost', 14)
    inv_upload_idx = columns.get('invoice_upload_date', 16)
    approved_by_idx = columns.get('approved_by', 11)

    c.execute("SELECT * FROM po_requests WHERE status='pending' ORDER BY id DESC")
    pending = c.fetchall()

    c.execute("SELECT * FROM po_requests WHERE status='approved' ORDER BY id DESC")
    all_approved = c.fetchall()

    # Split approved requests into those with and without invoices
    approved = []
    invoiced = []
    for req in all_approved:
        if len(req) > inv_filename_idx and req[inv_filename_idx]:
            invoiced.append(req)
        else:
            approved.append(req)

    c.execute("SELECT * FROM po_requests WHERE status='denied' ORDER BY id DESC")
    denied = c.fetchall()

    c.execute("SELECT COUNT(*), SUM(estimated_cost) FROM po_requests WHERE status='pending'")
    pending_stats = c.fetchone()

    c.execute("SELECT COUNT(*) FROM po_requests WHERE status='approved'")
    approved_count = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM po_requests WHERE status='denied'")
    denied_count = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM po_requests WHERE invoice_filename IS NOT NULL")
    invoice_count = c.fetchone()[0]

    conn.close()

    stats = {
        'pending': pending_stats[0], 'approved': approved_count,
        'denied': denied_count, 'with_invoice': invoice_count,
        'total_value': pending_stats[1] if pending_stats[1] else 0
    }

    return render_template_string(OFFICE_DASHBOARD_TEMPLATE,
                                username=session['username'],
                                pending_requests=pending,
                                approved_requests=approved,
                                invoiced_requests=invoiced,
                                denied_requests=denied,
                                stats=stats,
                                inv_filename_idx=inv_filename_idx,
                                inv_number_idx=inv_number_idx,
                                inv_cost_idx=inv_cost_idx,
                                inv_upload_idx=inv_upload_idx,
                                approved_by_idx=approved_by_idx)

@app.route('/activity_log')
def activity_log():
    """View activity log - office only"""
    if 'username' not in session or session['role'] != 'office':
        return redirect(url_for('login'))

    # Get filter parameters
    filter_user = request.args.get('filter_user', '')
    filter_action = request.args.get('filter_action', '')

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Build query
    query = "SELECT * FROM activity_log WHERE 1=1"
    params = []

    if filter_user:
        query += " AND username LIKE ?"
        params.append(f'%{filter_user}%')

    if filter_action:
        query += " AND action=?"
        params.append(filter_action)

    query += " ORDER BY timestamp DESC LIMIT 500"

    c.execute(query, params)
    logs = c.fetchall()

    # Get unique actions for filter
    c.execute("SELECT DISTINCT action FROM activity_log ORDER BY action")
    actions = [row[0] for row in c.fetchall()]

    # Get unique users for filter
    c.execute("SELECT DISTINCT username FROM activity_log ORDER BY username")
    users = [row[0] for row in c.fetchall()]

    conn.close()

    return render_template_string(ACTIVITY_LOG_TEMPLATE,
                                 logs=logs,
                                 actions=actions,
                                 users=users,
                                 filter_user=filter_user,
                                 filter_action=filter_action,
                                 username=session['username'])

@app.route('/submit_request', methods=['POST'])
def submit_request():
    if 'username' not in session or session['role'] != 'technician':
        return redirect(url_for('login'))

    tech_name = request.form['tech_name']
    custom_po_number = request.form.get('custom_po_number', '').strip()
    job_name = request.form['job_name'].strip()
    store_name = request.form['store_name']
    estimated_cost = float(request.form['estimated_cost'])
    description = request.form['description']

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # VALIDATE JOB NAME EXISTS AND IS ACTIVE
    c.execute("SELECT job_name FROM jobs WHERE LOWER(job_name) = LOWER(?) AND active=1", (job_name,))
    valid_job = c.fetchone()

    if not valid_job:
        conn.close()
        flash('❌ ERROR: This job does not exist, is deactivated, or is spelled incorrectly. Please check the job list and try again.')
        return redirect(url_for('tech_dashboard'))

    # Use the correct spelling from database
    job_name = valid_job[0]

    # HANDLE CUSTOM PO NUMBER
    if custom_po_number:
        try:
            po_id = int(custom_po_number)
    
            # Check how many times this number has been used
            c.execute("SELECT COUNT(*) FROM po_requests WHERE id=?", (po_id,))
            count = c.fetchone()[0]
            
            if count > 0:
                # Add a suffix to track duplicates
                suffix = chr(65 + count)  # A, B, C, etc.
                flash(f'⚠️ PO #{po_id:04d} already exists. Creating as #{po_id:04d}-{suffix}')
            
            # Insert with EXPLICIT ID (database still uses same number)
            c.execute("""INSERT INTO po_requests
                         (id, tech_username, tech_name, job_name, store_name, estimated_cost,
                          description, status, request_date)
                         VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                     (po_id, session['username'], tech_name, job_name, store_name,
                      estimated_cost, description, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

            conn.commit()
            conn.close()

            # Send Telegram notification
            send_telegram_notification(po_id, tech_name, job_name, estimated_cost)

            flash(f'✅ PO Request #{po_id:04d} (CUSTOM) submitted successfully!')
            return redirect(url_for('tech_dashboard'))

        except ValueError:
            conn.close()
            flash('❌ ERROR: Invalid PO number format')
            return redirect(url_for('tech_dashboard'))
        except Exception as e:
            conn.close()
            flash(f'❌ ERROR creating custom PO: {str(e)}')
            return redirect(url_for('tech_dashboard'))

    # AUTO-INCREMENT PO NUMBER (normal flow)
    # AUTO-INCREMENT PO NUMBER (normal flow)
    else:
        c.execute("SELECT MAX(id) FROM po_requests")
        last_id = c.fetchone()[0]

        # Start counting from 1 instead of 0
        if last_id is None or last_id < 1:
            next_po_number = 1
        else:
            next_po_number = last_id + 1

        c.execute("""INSERT INTO po_requests
                     (tech_username, tech_name, job_name, store_name, estimated_cost,
                      description, status, request_date)
                     VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
                 (session['username'], tech_name, job_name, store_name,
                  estimated_cost, description, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

        conn.commit()
        conn.close()

        # Send Telegram notification
        send_telegram_notification(next_po_number, tech_name, job_name, estimated_cost)

        flash(f'✅ PO Request #{next_po_number:04d} submitted successfully!')
        return redirect(url_for('tech_dashboard'))

@app.route('/process_request/<int:request_id>', methods=['POST'])
def process_request(request_id):
    if 'username' not in session or session['role'] != 'office':
        return redirect(url_for('login'))

    action = request.form['action']
    notes = request.form.get('notes', '')

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Get PO details for logging
    c.execute("SELECT tech_name, job_name, estimated_cost FROM po_requests WHERE id=?", (request_id,))
    po_data = c.fetchone()

    # FIX: Set the correct status - 'approved' or 'denied'
    if action == 'approve':
        status = 'approved'
    elif action == 'deny':
        status = 'denied'
    else:
        status = action + 'd'  # fallback

    c.execute("""UPDATE po_requests
                 SET status=?, approval_date=?, approval_notes=?, approved_by=?
                 WHERE id=?""",
             (status, datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
              notes, session['username'], request_id))
    conn.commit()
    conn.close()

    # Log the approval/denial
    if po_data:
        details = f"PO #{request_id:04d} - {po_data[1]} - ${po_data[2]:.2f} - Tech: {po_data[0]}"
        if notes:
            details += f" - Notes: {notes}"
        log_activity(session['username'], status.upper(), 'po_request', request_id, details)

    flash(f'Request {status} successfully!')
    return redirect(url_for('office_dashboard'))

@app.route('/bulk_process_pos', methods=['POST'])
def bulk_process_pos():
    """Process multiple PO requests at once"""
    if 'username' not in session or session['role'] != 'office':
        return jsonify({'success': False, 'error': 'Unauthorized'})

    try:
        data = request.get_json()
        po_ids = data.get('po_ids', [])
        action = data.get('action')  # 'approve' or 'deny'
        notes = data.get('notes', '')

        if not po_ids:
            return jsonify({'success': False, 'error': 'No POs selected'})

        if action not in ['approve', 'deny']:
            return jsonify({'success': False, 'error': 'Invalid action'})

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        processed = 0
        for po_id in po_ids:
            c.execute("""UPDATE po_requests
                         SET status=?, approval_date=?, approval_notes=?, approved_by=?
                         WHERE id=? AND status='pending'""",
                     (action + 'd', datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                      notes, session['username'], po_id))
            if c.rowcount > 0:
                processed += 1

        conn.commit()
        conn.close()

        # Log bulk action
        details = f"Bulk {action}d {processed} PO(s): {po_ids}"
        if notes:
            details += f" - Notes: {notes}"
        log_activity(session['username'], f'BULK_{action.upper()}D', 'po_request', None, details)

        return jsonify({
            'success': True,
            'processed': processed,
            'message': f'{processed} PO(s) {action}d successfully'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/upload_invoice/<int:po_id>', methods=['POST'])
def upload_invoice(po_id):
    if 'username' not in session or session['role'] != 'office':
        return jsonify({'success': False, 'error': 'Unauthorized'})

    try:
        invoice_number = request.form.get('invoice_number', '').strip()
        invoice_cost = request.form.get('invoice_cost', '0.00').strip()

        if not invoice_number:
            return jsonify({'success': False, 'error': 'Invoice number is required'})

        if not invoice_cost or invoice_cost == '':
            return jsonify({'success': False, 'error': 'Invoice cost is required'})

        try:
            cost_float = float(invoice_cost)
            if cost_float < 0:
                return jsonify({'success': False, 'error': 'Invoice cost cannot be negative'})
        except ValueError:
            return jsonify({'success': False, 'error': f'Invalid invoice cost format: {invoice_cost}'})

        invoice_filename = None
        if 'invoice' in request.files:
            file = request.files['invoice']
            if file.filename != '':
                allowed_extensions = {'.pdf', '.jpg', '.jpeg', '.png'}
                file_ext = os.path.splitext(file.filename)[1].lower()
                if file_ext not in allowed_extensions:
                    return jsonify({'success': False, 'error': f'Invalid file type. Allowed: PDF, JPG, PNG'})

                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                safe_filename = f"PO{po_id:04d}_{timestamp}_{file.filename.replace(' ', '_')}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], safe_filename)
                file.save(file_path)
                invoice_filename = safe_filename

        if not invoice_filename:
            invoice_filename = 'MANUAL_ENTRY'

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("SELECT status, job_name FROM po_requests WHERE id=?", (po_id,))
        po = c.fetchone()

        if not po:
            conn.close()
            return jsonify({'success': False, 'error': 'PO request not found'})

        if po[0] != 'approved':
            conn.close()
            return jsonify({'success': False, 'error': 'PO request must be approved first'})

        formatted_cost = f"{cost_float:.2f}"

        # ✅ NEW: Update BOTH invoice fields AND estimated_cost
        po_number_formatted = format_po_number(po_id, po[1])
        auto_categorized = False

        if po_number_formatted.upper().startswith('S'):
            # Auto-categorize as Service
            c.execute("""UPDATE po_requests
                         SET invoice_filename=?, invoice_number=?, invoice_cost=?,
                             invoice_date=?, invoice_upload_date=?, job_name=?, estimated_cost=?
                         WHERE id=?""",
                     (invoice_filename, invoice_number, formatted_cost, 'N/A',
                      datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'Service', cost_float, po_id))
            auto_categorized = True
        else:
            # Normal update - replace estimated_cost with actual invoice cost
            c.execute("""UPDATE po_requests
                         SET invoice_filename=?, invoice_number=?, invoice_cost=?,
                             invoice_date=?, invoice_upload_date=?, estimated_cost=?
                         WHERE id=?""",
                     (invoice_filename, invoice_number, formatted_cost, 'N/A',
                      datetime.now().strftime('%Y-%m-%d %H:%M:%S'), cost_float, po_id))

        conn.commit()
        conn.close()

        message = f'Invoice saved successfully for PO #{po_id:04d}'
        if auto_categorized:
            message += ' - Auto-categorized as Service'

        return jsonify({
            'success': True,
            'message': message,
            'saved_data': {
                'invoice_number': invoice_number,
                'invoice_cost': formatted_cost,
                'auto_categorized': auto_categorized
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'error': f'Server error: {str(e)}'})

@app.route('/delete_request', methods=['POST'])
def delete_request():
    if 'username' not in session or session['role'] != 'office':
        return jsonify({'success': False, 'error': 'Unauthorized'})

    data = request.get_json()
    request_id = data.get('request_id')

    if not request_id:
        return jsonify({'success': False, 'error': 'No request ID provided'})

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT invoice_filename FROM po_requests WHERE id=?", (request_id,))
    result = c.fetchone()

    if result and result[0] and result[0] != 'MANUAL_ENTRY':
        invoice_path = os.path.join(app.config['UPLOAD_FOLDER'], result[0])
        if os.path.exists(invoice_path):
            try:
                os.remove(invoice_path)
            except:
                pass

    c.execute("DELETE FROM po_requests WHERE id=?", (request_id,))
    conn.commit()
    conn.close()

    return jsonify({'success': True})

@app.route('/delete_invoice', methods=['POST'])
def delete_invoice():
    """Delete invoice and move PO back to approved (without invoice)"""
    if 'username' not in session or session['role'] != 'office':
        return jsonify({'success': False, 'error': 'Unauthorized'})

    try:
        data = request.get_json()
        request_id = data.get('request_id')

        if not request_id:
            return jsonify({'success': False, 'error': 'No request ID provided'})

        print(f"DEBUG: Attempting to delete invoice for PO ID: {request_id}")

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Get the invoice filename to delete the file
        c.execute("SELECT invoice_filename FROM po_requests WHERE id=?", (request_id,))
        result = c.fetchone()

        if result and result[0] and result[0] != 'MANUAL_ENTRY':
            invoice_path = os.path.join(app.config['UPLOAD_FOLDER'], result[0])
            if os.path.exists(invoice_path):
                try:
                    os.remove(invoice_path)
                    print(f"DEBUG: Deleted invoice file: {result[0]}")
                except Exception as e:
                    print(f"WARNING: Could not delete invoice file: {e}")

        # Clear invoice data but keep PO as approved
        c.execute("""UPDATE po_requests
                     SET invoice_filename=NULL, invoice_number=NULL,
                         invoice_cost=NULL, invoice_date=NULL, invoice_upload_date=NULL
                     WHERE id=?""", (request_id,))
        conn.commit()
        conn.close()

        print(f"DEBUG: Successfully deleted invoice for PO {request_id}")
        return jsonify({'success': True, 'message': 'Invoice deleted, PO moved back to Approved'})

    except Exception as e:
        print(f"ERROR in delete_invoice: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Server error: {str(e)}'})

@app.route('/undo_approval', methods=['POST'])
def undo_approval():
    """Undo approval and move PO back to pending"""
    if 'username' not in session or session['role'] != 'office':
        return jsonify({'success': False, 'error': 'Unauthorized'})

    try:
        data = request.get_json()
        request_id = data.get('request_id')

        if not request_id:
            return jsonify({'success': False, 'error': 'No request ID provided'})

        print(f"DEBUG: Attempting to undo approval for PO ID: {request_id}")

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Check if PO exists
        c.execute("SELECT id, status, invoice_filename FROM po_requests WHERE id=?", (request_id,))
        result = c.fetchone()

        if not result:
            conn.close()
            return jsonify({'success': False, 'error': 'PO request not found'})

        print(f"DEBUG: PO found - Status: {result[1]}, Invoice: {result[2]}")

        if result[2]:
            conn.close()
            return jsonify({'success': False, 'error': 'Cannot undo approval - PO has invoice attached. Delete invoice first.'})

        # Move back to pending
        c.execute("""UPDATE po_requests
                     SET status='pending', approval_date=NULL,
                         approval_notes=NULL, approved_by=NULL
                     WHERE id=?""", (request_id,))
        conn.commit()
        conn.close()

        print(f"DEBUG: Successfully moved PO {request_id} back to pending")
        return jsonify({'success': True, 'message': 'PO moved back to Pending'})

    except Exception as e:
        print(f"ERROR in undo_approval: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Server error: {str(e)}'})

@app.route('/view_invoice/<filename>')
def view_invoice(filename):
    """View uploaded invoice file"""
    if 'username' not in session or session['role'] != 'office':
        return redirect(url_for('login'))

    if filename == 'MANUAL_ENTRY':
        flash('No file attached - this was a manual entry')
        return redirect(url_for('office_dashboard'))

    try:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if not os.path.exists(file_path):
            flash(f'Invoice file not found: {filename}')
            return redirect(url_for('office_dashboard'))

        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
    except Exception as e:
        flash(f'Error viewing invoice: {str(e)}')
        return redirect(url_for('office_dashboard'))

@app.route('/logout')
def logout():
    if 'session_id' in session:
        if session['session_id'] in active_sessions:
            del active_sessions[session['session_id']]
    session.clear()
    return redirect(url_for('login'))

# NEW JOB MANAGEMENT ROUTES
@app.route('/get_jobs', methods=['GET'])
def get_jobs():
    """API endpoint to get all active jobs for dropdown"""
    if 'username' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'})

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # ONLY return active jobs (active=1)
        c.execute("SELECT job_name, year FROM jobs WHERE active=1 ORDER BY year DESC, job_name ASC")
        jobs = [{'name': row[0], 'year': row[1], 'display': f"{row[0]} ({row[1]})"} for row in c.fetchall()]
        conn.close()
        return jsonify({'success': True, 'jobs': jobs})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/login_with_token/<token>')
def login_with_token(token):
    """Login using a session token from URL"""
    if token in active_sessions:
        user_data = active_sessions[token]
        session['session_id'] = token
        session['username'] = user_data['username']
        session['role'] = user_data['role']
        session['email'] = user_data.get('email')
        session['full_name'] = user_data.get('full_name')

        if user_data['role'] == 'technician':
            return redirect(url_for('tech_dashboard'))
        elif user_data['role'] == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('office_dashboard'))
    else:
        flash('Invalid or expired session')
        return redirect(url_for('login'))

@app.route('/manage_jobs')
def manage_jobs():
    """Job management page for office with invoice totals"""
    if 'username' not in session or session['role'] != 'office':
        return redirect(url_for('login'))

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Check if table exists
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'")
        if not c.fetchone():
            conn.close()
            return "Error: Jobs table does not exist. Please restart the app to initialize the database."

        # Get jobs with invoice totals
        c.execute("""
            SELECT
                j.id,
                j.job_name,
                j.year,
                j.created_date,
                j.active,
                COALESCE(SUM(CASE WHEN p.invoice_cost IS NOT NULL THEN CAST(p.invoice_cost AS REAL) ELSE 0 END), 0) as total_invoiced,
                COUNT(CASE WHEN p.invoice_filename IS NOT NULL THEN 1 END) as invoice_count,
                COALESCE(SUM(p.estimated_cost), 0) as total_estimated,
                COUNT(p.id) as po_count
            FROM jobs j
            LEFT JOIN po_requests p ON j.job_name = p.job_name
            GROUP BY j.id, j.job_name, j.year, j.created_date, j.active
            ORDER BY j.active DESC, j.year DESC, j.job_name ASC
        """)
        jobs = c.fetchall()
        conn.close()

        return render_template_string(JOB_MANAGEMENT_TEMPLATE, username=session['username'], jobs=jobs)

    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/get_job_details/<int:job_id>')
def get_job_details(job_id):
    """Get detailed invoice list for a specific job"""
    if 'username' not in session or session['role'] != 'office':
        return jsonify({'success': False, 'error': 'Unauthorized'})

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Get job name
        c.execute("SELECT job_name FROM jobs WHERE id=?", (job_id,))
        job = c.fetchone()
        if not job:
            return jsonify({'success': False, 'error': 'Job not found'})

        job_name = job[0]

        # Get all POs with invoices for this job
        c.execute("""
            SELECT id, tech_name, estimated_cost, invoice_number, invoice_cost,
                   invoice_upload_date, invoice_filename, status
            FROM po_requests
            WHERE job_name = ? AND invoice_filename IS NOT NULL
            ORDER BY invoice_upload_date DESC
        """, (job_name,))

        invoices = []
        for row in c.fetchall():
            invoices.append({
                'po_id': row[0],
                'tech_name': row[1],
                'estimated': float(row[2]) if row[2] else 0,
                'invoice_number': row[3],
                'invoice_cost': float(row[4]) if row[4] else 0,
                'date': row[5],
                'filename': row[6],
                'status': row[7]
            })

        conn.close()

        return jsonify({
            'success': True,
            'job_name': job_name,
            'invoices': invoices
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/test_template')
def test_template():
    try:
        return f"Template exists: {type(JOB_MANAGEMENT_TEMPLATE)}"
    except NameError:
        return "ERROR: JOB_MANAGEMENT_TEMPLATE is not defined!"

@app.route('/add_job', methods=['POST'])
def add_job():
    """Add a new job"""
    if 'username' not in session or session['role'] != 'office':
        return jsonify({'success': False, 'error': 'Unauthorized'})

    job_name = request.form.get('job_name', '').strip()
    year = request.form.get('year', '').strip()

    if not job_name or not year:
        return jsonify({'success': False, 'error': 'Job name and year required'})

    try:
        year = int(year)
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid year'})

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    try:
        c.execute("INSERT INTO jobs (job_name, year, created_date) VALUES (?, ?, ?)",
                 (job_name, year, datetime.now().strftime('%Y-%m-%d')))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': f'Job "{job_name}" added successfully'})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'success': False, 'error': 'Job name already exists'})


@app.route('/edit_job', methods=['POST'])
def edit_job():
    """Edit existing job"""
    if 'username' not in session or session['role'] != 'office':
        return jsonify({'success': False, 'error': 'Unauthorized'})

    data = request.get_json()
    job_id = data.get('job_id')
    job_name = data.get('job_name', '').strip()
    year = data.get('year')

    if not job_id or not job_name or not year:
        return jsonify({'success': False, 'error': 'All fields required'})

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE jobs SET job_name=?, year=? WHERE id=?", (job_name, year, job_id))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Job updated successfully'})


@app.route('/toggle_job', methods=['POST'])
def toggle_job():
    """Activate/deactivate a job"""
    if 'username' not in session or session['role'] != 'office':
        return jsonify({'success': False, 'error': 'Unauthorized'})

    data = request.get_json()
    job_id = data.get('job_id')

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT active FROM jobs WHERE id=?", (job_id,))
    current = c.fetchone()[0]
    new_status = 0 if current == 1 else 1
    c.execute("UPDATE jobs SET active=? WHERE id=?", (new_status, job_id))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'status': 'active' if new_status == 1 else 'inactive'})

@app.route('/delete_job', methods=['POST'])
def delete_job():
    """Delete a job"""
    if 'username' not in session or session['role'] != 'office':
        return jsonify({'success': False, 'error': 'Unauthorized'})

    data = request.get_json()
    job_id = data.get('job_id')

    if not job_id:
        return jsonify({'success': False, 'error': 'Job ID required'})

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Check if any PO requests use this job
    c.execute("SELECT job_name FROM jobs WHERE id=?", (job_id,))
    job = c.fetchone()

    if job:
        job_name = job[0]
        c.execute("SELECT COUNT(*) FROM po_requests WHERE job_name=?", (job_name,))
        count = c.fetchone()[0]

        if count > 0:
            conn.close()
            return jsonify({
                'success': False,
                'error': f'Cannot delete: {count} PO request(s) are using this job'
            })

    c.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Job deleted successfully'})

@app.route('/bulk_upload_invoices', methods=['POST'])
def bulk_upload_invoices():
    """Process bulk PDF upload with multiple invoices"""
    if 'username' not in session or session['role'] != 'office':
        return jsonify({'success': False, 'error': 'Unauthorized'})

    if not PDF_SUPPORT:
        return jsonify({
            'success': False,
            'error': 'PDF libraries not installed. Run: pip3 install --user PyPDF2 pdfplumber'
        })

    try:
        if 'bulk_pdf' not in request.files:
            return jsonify({'success': False, 'error': 'No PDF file uploaded'})

        file = request.files['bulk_pdf']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'})

        if not file.filename.lower().endswith('.pdf'):
            return jsonify({'success': False, 'error': 'Only PDF files allowed'})

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        temp_pdf_path = os.path.join(app.config['BULK_UPLOAD_FOLDER'], f'bulk_{timestamp}.pdf')
        file.save(temp_pdf_path)

        results = process_bulk_pdf(temp_pdf_path, timestamp)

        try:
            os.remove(temp_pdf_path)
        except:
            pass

        return jsonify(results)

    except Exception as e:
        import traceback
        return jsonify({'success': False, 'error': str(e), 'trace': traceback.format_exc()})


def process_bulk_pdf(pdf_path, timestamp):
    """
    Improved PDF processing with better error handling and reporting
    """
    results = {
        'success': True,
        'processed': 0,
        'matched': 0,
        'unmatched': [],
        'errors': [],
        'details': []
    }

    try:
        import PyPDF2
        import pdfplumber

        pdf_reader = PyPDF2.PdfReader(pdf_path)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # ✅ FIXED: Only get approved POs WITHOUT invoices
        c.execute("""SELECT id, tech_name, job_name, estimated_cost
                     FROM po_requests
                     WHERE status='approved'
                     AND (invoice_filename IS NULL OR invoice_filename = '')""")
        po_map = {}
        for row in c.fetchall():
            po_map[row[0]] = {
                'id': row[0],
                'tech_name': row[1],
                'job_name': row[2],
                'estimated_cost': row[3]
            }  # ← Fixed closing brace

        print(f"\n📋 Found {len(po_map)} approved POs without invoices: {sorted(po_map.keys())}")

        # Group pages by invoice number
        invoice_groups = {}

        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                results['processed'] += 1
                text = page.extract_text() or ''

                print(f"\n{'='*60}")
                print(f"📄 PAGE {page_num}")
                print(f"{'='*60}")

                # If no text extracted, try OCR (for scanned PDFs)
                if not text.strip() and OCR_SUPPORT:
                    print(f"  📷 No embedded text, trying OCR...")
                    text = extract_text_with_ocr(pdf_path, page_num)

                # Extract invoice data from this page
                invoice_data = extract_invoice_data(text, po_map)

                if invoice_data and not invoice_data.get('error'):
                    # Valid invoice with PO match
                    inv_num = invoice_data['invoice_number']

                    if inv_num not in invoice_groups:
                        invoice_groups[inv_num] = {
                            'pages': [],
                            'texts': [],
                            'data': invoice_data
                        }

                    invoice_groups[inv_num]['pages'].append(page_num - 1)
                    invoice_groups[inv_num]['texts'].append(text)

                elif invoice_data and invoice_data.get('error'):
                    # Invoice found but no PO match
                    results['errors'].append({
                        'page': page_num,
                        'invoice_number': invoice_data['invoice_number'],
                        'cost': invoice_data.get('cost', 'Unknown'),
                        'error': 'NO MATCHING PO FOUND',
                        'message': invoice_data.get('message', ''),
                        'text_preview': text[:300]
                    })

                    # Save as unmatched page
                    unmatched_filename = f"ERROR_NO_PO_{timestamp}_page{page_num}_{invoice_data['invoice_number']}.pdf"
                    unmatched_path = os.path.join(app.config['UPLOAD_FOLDER'], unmatched_filename)
                    pdf_writer = PyPDF2.PdfWriter()
                    pdf_writer.add_page(pdf_reader.pages[page_num - 1])
                    with open(unmatched_path, 'wb') as f:
                        pdf_writer.write(f)

                else:
                    # No invoice number found
                    print(f"✗ No invoice number found on page {page_num}")
                    unmatched_filename = f"UNMATCHED_{timestamp}_page{page_num}.pdf"
                    unmatched_path = os.path.join(app.config['UPLOAD_FOLDER'], unmatched_filename)
                    pdf_writer = PyPDF2.PdfWriter()
                    pdf_writer.add_page(pdf_reader.pages[page_num - 1])
                    with open(unmatched_path, 'wb') as f:
                        pdf_writer.write(f)

                    results['unmatched'].append({
                        'page': page_num,
                        'text_preview': text[:200],
                        'filename': unmatched_filename
                    })

        # Save successfully matched invoices
        print(f"\n💾 Saving {len(invoice_groups)} invoice groups...")
        for inv_num, group in invoice_groups.items():
            invoice_data = group['data']
            po_id = invoice_data['po_id']

            # Create multi-page PDF
            pdf_writer = PyPDF2.PdfWriter()
            for page_idx in group['pages']:
                pdf_writer.add_page(pdf_reader.pages[page_idx])

            filename = f"PO{po_id:04d}_{timestamp}_INV{inv_num}.pdf"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

            with open(file_path, 'wb') as output_file:
                pdf_writer.write(output_file)

            # Update database
            c.execute("""UPDATE po_requests
                         SET invoice_filename=?, invoice_number=?, invoice_cost=?,
                             invoice_date=?, invoice_upload_date=?, estimated_cost=?,
                             match_method=?
                         WHERE id=?""",
                     (filename, inv_num, invoice_data['cost'], 'N/A',
                      datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                      float(invoice_data['cost']),
                      invoice_data.get('match_method', 'Unknown'), po_id))

            results['matched'] += 1

            po_info = po_map.get(po_id, {})
            job_name = po_info.get('job_name', 'Unknown')
            estimated_cost = po_info.get('estimated_cost', 0.00)

            results['details'].append({
                'page': f"{group['pages'][0] + 1}" + (f"-{group['pages'][-1] + 1}" if len(group['pages']) > 1 else ""),
                'po_number': po_id,
                'job_name': job_name,
                'estimated_cost': estimated_cost,
                'invoice_number': inv_num,
                'cost': invoice_data['cost'],
                'status': 'matched',
                'pages': len(group['pages'])
            })

        conn.commit()
        conn.close()

        # Build result message
        error_count = len(results['errors'])
        if error_count > 0:
            results['message'] = f'⚠ Processed {results["processed"]} pages. Matched {results["matched"]} invoices. {error_count} invoice(s) found but NO MATCHING PO!'
        else:
            results['message'] = f'✅ Processed {results["processed"]} pages. Successfully matched {results["matched"]} invoices.'

    except Exception as e:
        import traceback
        results['success'] = False
        results['error'] = str(e)
        results['trace'] = traceback.format_exc()
        print(f"❌ ERROR: {traceback.format_exc()}")

    return results


def save_invoice_pages(pdf_reader, invoice_data, page_indices, timestamp, cursor, results):
    """Save multi-page invoice as single PDF"""
    po_id = invoice_data['po_id']
    invoice_number = invoice_data['invoice_number']
    invoice_cost = invoice_data['cost']
    match_method = invoice_data.get('match_method', 'Unknown')

    # Get job name and estimated cost for display
    cursor.execute("SELECT job_name, estimated_cost FROM po_requests WHERE id=?", (po_id,))
    job_result = cursor.fetchone()
    job_name = job_result[0] if job_result else "Unknown Job"
    estimated_cost = job_result[1] if job_result else 0.00

    pdf_writer = PyPDF2.PdfWriter()
    for page_idx in page_indices:
        pdf_writer.add_page(pdf_reader.pages[page_idx])

    page_filename = f"PO{po_id:04d}_{timestamp}_INV{invoice_number}.pdf"
    page_path = os.path.join(app.config['UPLOAD_FOLDER'], page_filename)

    with open(page_path, 'wb') as output_file:
        pdf_writer.write(output_file)

    # ✅ NEW: Update BOTH invoice fields AND estimated_cost
    cursor.execute("""UPDATE po_requests
                     SET invoice_filename=?, invoice_number=?, invoice_cost=?,
                         invoice_date=?, invoice_upload_date=?, estimated_cost=?,
                         match_method=?
                     WHERE id=?""",
                 (page_filename, invoice_number, invoice_cost, 'N/A',
                  datetime.now().strftime('%Y-%m-%d %H:%M:%S'), float(invoice_cost),
                  match_method, po_id))

    # Check if PO NUMBER starts with "S" (not invoice number)
    po_number_formatted = format_po_number(po_id, job_name)

    # Only auto-categorize as Service if the PO number itself starts with S
    if po_id >= 9000:
        cursor.execute("SELECT job_name FROM jobs WHERE LOWER(job_name) = LOWER('service') AND active=1")
        service_job_exists = cursor.fetchone()

        if service_job_exists and po_number_formatted.upper().startswith('S'):
            cursor.execute("UPDATE po_requests SET job_name=? WHERE id=?", ('Service', po_id))
            print(f"  ✓ Auto-categorized PO #{po_id} as Service (PO number starts with S)")
        else:
            print(f"  ℹ PO #{po_id} NOT auto-categorized (PO number doesn't start with S)")
    else:
        print(f"  ℹ PO #{po_id} is not in Service range (9000+)")

    results['matched'] += 1
    results['details'].append({
        'page': f"{page_indices[0] + 1}" + (f"-{page_indices[-1] + 1}" if len(page_indices) > 1 else ""),
        'po_number': po_id,
        'job_name': job_name,
        'estimated_cost': estimated_cost,
        'invoice_number': invoice_number,
        'cost': invoice_cost,
        'status': 'matched',
        'pages': len(page_indices)
    })

def extract_invoice_data(text, po_map):
    """
    Enhanced invoice data extraction with table column handling
    """
    if not text:
        print("  ❌ No text provided")
        return None

    print(f"\n{'='*60}")
    print(f"📄 ANALYZING TEXT ({len(text)} chars)")
    print(f"{'='*60}")
    print("\n📝 TEXT PREVIEW:")
    print("-" * 60)
    print(text[:1500])
    print("-" * 60)

    # === STEP 1: Find Invoice Number - FIXED TO AVOID CUSTOMER NUMBER ===
    print("\n🔍 STEP 1: Looking for Invoice Number...")
    invoice_number = None

    # Pattern specifically for "CUSTOMER # INVOICE #" format (SiteOne) - handles table headers
    # This pattern handles both same-line and multiline formats
    customer_invoice_patterns = [
        r'CUSTOMER\s*#\s*INVOICE\s*#[\s\S]*?(\d{5,}[A-Z0-9\-]*)',  # SiteOne table format
        r'INVOICE\s*#[\s:]*(\d{5,}[A-Z0-9\-]*)',  # Simple Invoice # format
    ]

    for pattern in customer_invoice_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            if len(candidate) >= 5:
                invoice_number = candidate
                print(f"  ✅ Found Invoice Number (primary pattern): {invoice_number}")
                break

    if not invoice_number:
        # Fallback patterns - handle various invoice/order number formats
        order_patterns = [
            # Invoice patterns
            (r'INVOICE\s*#\s*:?\s*([A-Z0-9\-]+)', 'Invoice #'),
            (r'INVOICE\s*(?:NO|NUM|NUMBER)\s*[:\s]*([A-Z0-9\-]+)', 'Invoice No/Num'),
            (r'Invoice\s+No\s*[:\s]*([A-Z0-9\-]+)', 'Invoice No'),  # Davis: "Invoice No: FM10979-3"
            # Order patterns
            (r'Order\s*#\s*:?\s*([A-Z0-9\-]+)', 'Order #'),
            (r'Order\s*(?:NO|NUM|NUMBER)\s*:?\s*([A-Z0-9\-]+)', 'Order No/Num'),
            (r'Sales\s*Order\s*#?\s*:?\s*([A-Z0-9\-]+)', 'Sales Order'),
            (r'Work\s*Order\s*#?\s*:?\s*([A-Z0-9\-]+)', 'Work Order'),
            # Reference/Ticket/Transaction patterns
            (r'Reference\s*#?\s*:?\s*([A-Z0-9\-]+)', 'Reference #'),
            (r'Ticket\s*#?\s*:?\s*([A-Z0-9\-]+)', 'Ticket #'),
            (r'Document\s*#?\s*:?\s*([A-Z0-9\-]+)', 'Document #'),
            (r'Receipt\s*#?\s*:?\s*([A-Z0-9\-]+)', 'Receipt #'),
            (r'Confirmation\s*#?\s*:?\s*([A-Z0-9\-]+)', 'Confirmation #'),
            (r'Transaction\s*(?:ID|#)?\s*[:\s]*([A-Z0-9\-]+)', 'Transaction ID'),  # Davis: "Transaction ID: 81429863207"
        ]

        for pattern, desc in order_patterns:
            print(f"  Trying pattern: {desc}")
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                candidate = match.group(1).strip()
                # Skip short numbers (likely customer number) and common false positives
                if candidate.lower() not in ['date', 'time', 'page'] and len(candidate) >= 5:
                    invoice_number = candidate
                    print(f"  ✅ Found Invoice Number ({desc}): {invoice_number}")
                    break
                else:
                    print(f"    Skipped '{candidate}' (too short or false positive)")

    if not invoice_number:
        print("  ❌ No invoice number found")
        return None

    # === STEP 2: Find PO Number - IMPROVED VERSION ===
    print(f"\n🔍 STEP 2: Looking for PO Number...")
    print(f"  Available approved POs (without invoices): {sorted(po_map.keys())}")

    po_number = None
    match_method = None  # Track which method successfully matched

    # PRIMARY METHOD: Claude AI (when enabled) - Most accurate, handles misspellings/OCR errors
    if po_map and is_claude_matching_enabled():
        print("\n  🤖 PRIMARY: Claude AI intelligent matching")
        active_jobs = get_active_job_names()

        claude_po, claude_job, confidence = match_invoice_with_claude(text, active_jobs, po_map)

        if claude_po and confidence >= 0.6:
            po_number = claude_po
            match_method = "Claude AI"
            print(f"    ✅ Claude matched PO {po_number} for job '{claude_job}' (confidence: {confidence:.0%})")
        elif claude_po:
            print(f"    ⚠ Claude suggested PO {claude_po} but confidence too low ({confidence:.0%}), trying other methods...")
        else:
            print(f"    ⚠ Claude couldn't find a match, trying fallback methods...")

    # FALLBACK METHOD 1: Look for table headers with PO information
    if not po_number:
        print("\n  Method 1: Table column approach")

    # Try multiple header patterns
    header_patterns = [
        (r'(ORDER\s*#\s*)(PO\s*#)', 'ORDER # / PO #'),
        (r'(Purchase\s+Order[/\s]*Job\s+Name)', 'Purchase Order/Job Name'),
        (r'(PO\s*Number)', 'PO Number'),
        (r'(PO\s*#)', 'PO #'),
        (r'(Customer\s*PO)', 'Customer PO'),
        (r'(Job\s*#)', 'Job #'),
        (r'(Job\s*Name)', 'Job Name'),
        (r'(Job\s*Number)', 'Job Number'),
        (r'(Work\s*Order)', 'Work Order'),
        (r'(Project\s*#)', 'Project #'),
        (r'(Reference)', 'Reference'),
    ]

    for header_pattern, header_desc in header_patterns:
        if po_number:
            break

        po_header_match = re.search(header_pattern, text, re.IGNORECASE)

        if po_header_match:
            print(f"    ✓ Found '{header_desc}' header at position {po_header_match.start()}")
            po_column_start = po_header_match.start()
            text_after = text[po_column_start:]
            lines = text_after.split('\n')

            print(f"    Lines after header:")
            for i, line in enumerate(lines[:3]):
                print(f"      Line {i}: {line[:80]}")

            # Check line 0 (same line) and line 1 (next line) for values
            lines_to_check = [lines[0]] if lines else []
            if len(lines) > 1:
                lines_to_check.append(lines[1])

            for line_idx, values_line in enumerate(lines_to_check):
                if po_number:
                    break
                print(f"    → Checking line {line_idx}: {values_line[:80]}")

                # Extract ALL sequences that could be PO numbers
                number_patterns = [
                    r'S-(\d{4,})',           # S-4016 format
                    r'\b(\d{4,})[A-Za-z]+',  # 9860HERONSGLEN format (case insensitive)
                    r':\s*(\d{4,})\s+[A-Za-z]', # PO Number: 1012 SOMERVILLE format
                    r'\b(\d{4,})\s+[A-Za-z]{3,}', # 1012 SOMERVILLE format (space between)
                    r'\b(\d{4,})\b'          # Plain 4016 format
                ]

                for pattern in number_patterns:
                    if po_number:
                        break
                    matches = re.finditer(pattern, values_line, re.IGNORECASE)
                    for match in matches:
                        num_str = match.group(1)
                        try:
                            candidate = int(num_str)
                            print(f"      Testing: {candidate}")
                            if candidate in po_map:
                                po_number = candidate
                                match_method = "Table Column"
                                print(f"      ✅ MATCHED! PO {po_number}")
                                break
                            else:
                                print(f"      ⚠ {candidate} not in approved list (may already have invoice)")
                        except ValueError:
                            continue

    # METHOD 2: Pattern matching (fallback)
    if not po_number:
        print("\n  Method 2: Pattern matching (fallback)")
        po_patterns = [
            # PO # formats
            (r'PO\s*#?\s*[:\s]*S-(\d{4,})', 'PO: S-XXXX', 0),
            (r'PO\s*#?\s*[:\s]*(\d{4,})[A-Za-z]+', 'PO: XXXXABC', 0),
            (r'PO\s*#?\s*[:\s]*(\d{4,})\s+[A-Za-z]', 'PO: XXXX JOBNAME', 0),
            (r'PO\s*#?\s*[:\s]*(\d{4,})', 'PO: XXXX', 0),
            # Customer PO formats
            (r'Customer\s*PO\s*#?\s*[:\s]*(\d{4,})', 'Customer PO', 0),
            # Job # formats
            (r'Job\s*#\s*[:\s]*(\d{4,})', 'Job #', 0),
            (r'Job\s*(?:Name|Number)\s*[:\s]*(\d{4,})', 'Job Name/Number', 0),
            # Project/Work Order formats
            (r'Project\s*#?\s*[:\s]*(\d{4,})', 'Project #', 0),
            (r'Work\s*Order\s*#?\s*[:\s]*(\d{4,})', 'Work Order', 0),
            # Home Depot format: "Purchase Order/Job Name" with "9860HERONSGLEN" (handles newlines)
            (r'Purchase\s+Order[/\s]+Job\s+Name[\s\S]*?(\d{4,})[A-Za-z]+', 'Purchase Order/Job Name: XXXXJOBNAME', 0),
            # Shine On format: "PO Number: 1012 SOMERVILLE" (number followed by space then text)
            (r'PO\s*Number[:\s]+(\d{4,})\s+[A-Za-z]', 'PO Number: XXXX JOBNAME', 0),
            (r'PO\s*Number[:\s]+(\d{4,})', 'PO Number: XXXX', 0),
            # Generic: any 4+ digit number followed by job name text (letters)
            (r'\b(\d{4,})[A-Za-z]{3,}', 'XXXXJOBNAME pattern', 0),
            # Number with space then job name (like "1012 SOMERVILLE")
            (r'\b(\d{4,})\s+(?:SOMERVILLE|HERONS?\s*GLEN|SERVICE)', 'XXXX known job name', 0),
        ]

        for pattern, desc, flags in po_patterns:
            print(f"    Trying pattern: {desc}")
            matches = re.finditer(pattern, text, re.IGNORECASE | flags)

            for match in matches:
                try:
                    candidate = int(match.group(1))
                    print(f"      → Found: {candidate}")

                    if candidate in po_map:
                        po_number = candidate
                        match_method = "Pattern Match"
                        print(f"      ✅ MATCHED! PO {po_number}")
                        break
                    else:
                        print(f"      ⚠ {candidate} not in approved list")
                except ValueError:
                    continue

            if po_number:
                break

    # METHOD 3: Direct search for known PO IDs from po_map
    if not po_number and po_map:
        print("\n  Method 3: Direct search for known PO IDs")
        text_upper = text.upper()

        for po_id, po_info in po_map.items():
            po_str = str(po_id)
            job_name = po_info.get('job_name', '').upper()
            job_name_no_spaces = job_name.replace(' ', '').replace('-', '').replace('_', '')

            print(f"    Checking PO {po_id} (job: {job_name})")

            # Look for the PO number in the text
            if po_str in text:
                print(f"      Found PO ID {po_id} in text")

                # Check for concatenated format like "9860HERONSGLEN"
                concat_pattern = rf'{po_str}\s*{job_name_no_spaces}'
                if re.search(concat_pattern, text_upper):
                    po_number = po_id
                    match_method = "Direct Search"
                    print(f"      ✅ MATCHED! PO {po_number} (concatenated format)")
                    break

                # Verify by checking if job name (or parts of it) also appears
                job_parts = job_name.replace('-', ' ').replace('_', ' ').split()
                job_found = False
                for part in job_parts:
                    if len(part) >= 3 and part in text_upper:
                        job_found = True
                        print(f"      ✓ Job name part '{part}' also found in text")
                        break

                if job_found:
                    po_number = po_id
                    match_method = "Direct Search"
                    print(f"      ✅ MATCHED! PO {po_number} (verified with job name)")
                    break
                else:
                    # Even without job name match, check if PO is in context of PO/Order fields
                    po_context_pattern = rf'(?:PO|Purchase\s*Order|Order|Job)[^0-9]*{po_str}'
                    if re.search(po_context_pattern, text, re.IGNORECASE):
                        po_number = po_id
                        match_method = "Direct Search"
                        print(f"      ✅ MATCHED! PO {po_number} (found in PO context)")
                        break

    # METHOD 4: Fuzzy job name scanning - find job names in text and extract nearby PO numbers
    if not po_number and po_map:
        print("\n  Method 4: Fuzzy job name scanning")
        active_jobs = get_active_job_names()
        print(f"    Active jobs to search for: {active_jobs}")

        text_upper = text.upper()

        for job_name in active_jobs:
            if po_number:
                break

            # Use fuzzy matching to find job name in text
            found, pos, matched_text, score = find_job_name_in_text(text, job_name, threshold=0.75)

            if found:
                print(f"    ✓ Found job '{job_name}' in text (matched: '{matched_text}', score: {score:.2f})")

                # Look for numbers near the matched job name
                # Search in a window around the match position
                search_start = max(0, pos - 100)
                search_end = min(len(text), pos + len(job_name) + 100)
                context = text[search_start:search_end]

                print(f"      Context around match: {context[:150]}...")

                # Find all 3-5 digit numbers in the context
                number_matches = re.findall(r'\b(\d{3,5})\b', context)
                print(f"      Numbers found near job name: {number_matches}")

                for num_str in number_matches:
                    try:
                        candidate = int(num_str)
                        # Check if this number is a PO for this job
                        if candidate in po_map:
                            po_info = po_map[candidate]
                            po_job = po_info.get('job_name', '').upper()

                            # Verify the PO's job name matches (using fuzzy matching)
                            job_match_score = fuzzy_match_score(po_job, job_name)

                            if job_match_score >= 0.75:
                                po_number = candidate
                                match_method = "Fuzzy Match"
                                print(f"      ✅ MATCHED! PO {po_number} (fuzzy job match, score: {job_match_score:.2f})")
                                break
                            else:
                                print(f"      ⚠ PO {candidate} exists but job '{po_job}' doesn't match '{job_name}' (score: {job_match_score:.2f})")
                        else:
                            print(f"      ⚠ {candidate} not in approved PO list")
                    except ValueError:
                        continue

        # If still no match, try a broader approach: scan entire text for any active job name
        # and then look for PO numbers anywhere that match POs with that job
        if not po_number:
            print("\n    Method 4b: Broader fuzzy scan - checking if any job name appears anywhere")
            for job_name in active_jobs:
                if po_number:
                    break

                found, pos, matched_text, score = find_job_name_in_text(text, job_name, threshold=0.70)

                if found:
                    print(f"    ✓ Found job '{job_name}' (matched: '{matched_text}', score: {score:.2f})")

                    # Find all POs in po_map that have this job name
                    matching_pos = []
                    for po_id, po_info in po_map.items():
                        po_job = po_info.get('job_name', '')
                        if fuzzy_match_score(po_job, job_name) >= 0.75:
                            matching_pos.append(po_id)

                    print(f"      POs with this job: {matching_pos}")

                    # Look for these specific PO numbers in the text
                    for po_id in matching_pos:
                        po_str = str(po_id)
                        if po_str in text:
                            po_number = po_id
                            match_method = "Fuzzy Match"
                            print(f"      ✅ MATCHED! PO {po_number} (found in text with matching job name)")
                            break

    # === STEP 3: Find Total Cost ===
    print(f"\n🔍 STEP 3: Looking for Total Cost...")
    cost = "0.00"

    cost_patterns = [
        (r'TOTAL[:\s]*\$?\s*([0-9,]+\.\d{2})', 'Total:'),
        (r'Amount\s+Due[:\s]*\$?\s*([0-9,]+\.\d{2})', 'Amount Due:'),
        (r'Grand\s+Total[:\s]*\$?\s*([0-9,]+\.\d{2})', 'Grand Total:'),
    ]

    for pattern, desc in cost_patterns:
        print(f"  Trying pattern: {desc}")
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        if matches:
            last_match = matches[-1]
            cost_str = last_match.group(1).replace(',', '')
            try:
                cost = f"{float(cost_str):.2f}"
                print(f"  ✅ Found cost: ${cost}")
                break
            except:
                pass

    # === FINAL RESULT ===
    print(f"\n{'='*60}")
    if not po_number:
        print(f"❌ FINAL RESULT: NO PO MATCH")
        print(f"   Invoice Number: {invoice_number}")
        print(f"   Total Cost: ${cost}")
        print(f"   Available POs (without invoices): {sorted(po_map.keys())}")
        print(f"{'='*60}\n")
        return {
            'error': True,
            'invoice_number': invoice_number,
            'cost': cost,
            'message': f'Invoice {invoice_number} - PO already has invoice or not approved'
        }

    print(f"✅ FINAL RESULT: SUCCESS!")
    print(f"   Invoice Number: {invoice_number}")
    print(f"   Matched PO: {po_number}")
    print(f"   Total Cost: ${cost}")
    print(f"   Match Method: {match_method or 'Unknown'}")
    print(f"{'='*60}\n")

    return {
        'po_id': po_number,
        'po_number': po_number,
        'invoice_number': invoice_number,
        'cost': cost,
        'match_method': match_method
    }


JOB_MANAGEMENT_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Manage Jobs</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px; }
        .header {
            background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1); display: flex;
            justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;
        }
        h1 { color: #333; font-size: 24px; }
        .btn {
            padding: 10px 20px; border-radius: 5px; text-decoration: none;
            font-weight: bold; border: none; cursor: pointer; font-size: 14px;
        }
        .btn-primary { background: #667eea; color: white; }
        .btn-secondary { background: #6c757d; color: white; }
        .btn-success { background: #28a745; color: white; }
        .btn-danger { background: #dc3545; color: white; }
        .card {
            background: white; padding: 20px; border-radius: 10px;
            margin-bottom: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        .filter-controls {
            background: #f0f4ff; padding: 20px; border-radius: 5px;
            margin-bottom: 20px; display: flex; gap: 15px; align-items: flex-end;
            flex-wrap: wrap;
        }
        .filter-group {
            flex: 1;
            min-width: 200px;
        }
        .filter-group label {
            display: block;
            font-weight: bold;
            color: #667eea;
            margin-bottom: 5px;
        }
        .filter-group input, .filter-group select {
            width: 100%;
            padding: 10px;
            border: 2px solid #667eea;
            border-radius: 5px;
            font-size: 16px;
        }
        .filter-stats {
            background: #e7f3ff;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
        }
        .stat-item {
            flex: 1;
            min-width: 150px;
        }
        .stat-number {
            font-size: 24px;
            font-weight: bold;
            color: #667eea;
        }
        .stat-label {
            color: #666;
            font-size: 14px;
        }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background: #667eea; color: white; font-weight: bold; }
        tr:hover { background: #f5f5f5; cursor: pointer; }
        .form-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 5px; font-weight: bold; color: #555; }
        input {
            width: 100%; padding: 10px; border: 2px solid #ddd;
            border-radius: 5px; font-size: 16px;
        }
        .status-badge {
            padding: 5px 10px; border-radius: 20px; font-size: 12px;
            font-weight: bold; display: inline-block;
        }
        .status-active { background: #28a745; color: white; }
        .status-inactive { background: #dc3545; color: white; }
        .expandable-row {
            display: none;
            background: #f9f9f9;
        }
        .expandable-row.show {
            display: table-row;
        }
        .invoice-details {
            padding: 20px;
            background: white;
            border-radius: 5px;
        }
        .invoice-item {
            padding: 15px;
            background: #e7f3ff;
            margin: 10px 0;
            border-radius: 5px;
            border-left: 4px solid #667eea;
        }
        .expand-icon {
            transition: transform 0.3s;
            display: inline-block;
        }
        .expand-icon.rotated {
            transform: rotate(90deg);
        }
        .money-positive { color: #28a745; font-weight: bold; }
        .money-negative { color: #dc3545; font-weight: bold; }
        .no-results {
            text-align: center;
            padding: 40px;
            color: #999;
            font-size: 16px;
        }
    </style>
    <script>
        let jobsData = {{ jobs|tojson }};
        let filteredYear = '';
        let filteredStatus = 'all';

        function addJob() {
            const jobName = document.getElementById('job_name').value.trim();
            const year = document.getElementById('year').value.trim();

            if (!jobName || !year) {
                alert('Please enter both job name and year');
                return;
            }

            const formData = new FormData();
            formData.append('job_name', jobName);
            formData.append('year', year);

            fetch('/add_job', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert(data.message);
                    location.reload();
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }

        function editJob(id, currentName, currentYear, event) {
            event.stopPropagation();
            const newName = prompt('Edit job name:', currentName);
            if (!newName) return;

            const newYear = prompt('Edit year:', currentYear);
            if (!newYear) return;

            fetch('/edit_job', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_id: id,
                    job_name: newName,
                    year: parseInt(newYear)
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert(data.message);
                    location.reload();
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }

        function toggleJob(id, event) {
            event.stopPropagation();
            if (!confirm('Toggle active status for this job?')) return;

            fetch('/toggle_job', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ job_id: id })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    location.reload();
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }

        function deleteJob(id, jobName, event) {
            event.stopPropagation();
            if (!confirm('Are you sure you want to DELETE "' + jobName + '"? This cannot be undone!')) return;

            fetch('/delete_job', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ job_id: id })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert(data.message);
                    location.reload();
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }

        function toggleJobDetails(jobId) {
            const detailsRow = document.getElementById('details-' + jobId);
            const icon = document.getElementById('icon-' + jobId);

            if (detailsRow.classList.contains('show')) {
                detailsRow.classList.remove('show');
                icon.classList.remove('rotated');
            } else {
                // Hide all other expanded rows
                document.querySelectorAll('.expandable-row').forEach(row => row.classList.remove('show'));
                document.querySelectorAll('.expand-icon').forEach(ic => ic.classList.remove('rotated'));

                // Show this row
                detailsRow.classList.add('show');
                icon.classList.add('rotated');

                // Load invoice details
                loadJobInvoices(jobId);
            }
        }

        function loadJobInvoices(jobId) {
            const container = document.getElementById('invoice-container-' + jobId);
            container.innerHTML = '<p style="text-align: center; color: #666;">Loading invoices...</p>';

            fetch('/get_job_details/' + jobId)
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    if (data.invoices.length === 0) {
                        container.innerHTML = '<p style="text-align: center; color: #999;">No invoices for this job yet.</p>';
                        return;
                    }

                    let html = '<h3 style="color: #667eea; margin-bottom: 15px;">Invoices for ' + data.job_name + '</h3>';

                    data.invoices.forEach(inv => {
                        const diff = inv.invoice_cost - inv.estimated;
                        const diffClass = diff > 0 ? 'money-negative' : 'money-positive';
                        const diffSign = diff > 0 ? '+' : '';

                        html += '<div class="invoice-item">';
                        html += '<strong>PO #' + inv.po_id.toString().padStart(4, '0') + '</strong> - ' + inv.tech_name + '<br>';
                        html += 'Invoice: ' + inv.invoice_number + '<br>';
                        html += 'Estimated: $' + inv.estimated.toFixed(2) + ' | ';
                        html += 'Actual: $' + inv.invoice_cost.toFixed(2) + ' | ';
                        html += 'Difference: <span class="' + diffClass + '">' + diffSign + '$' + diff.toFixed(2) + '</span><br>';
                        html += 'Date: ' + inv.date;
                        if (inv.filename && inv.filename !== 'MANUAL_ENTRY') {
                            html += ' | <a href="/view_invoice/' + inv.filename + '" target="_blank" style="color: #667eea;">View Invoice</a>';
                        }
                        html += '</div>';
                    });

                    container.innerHTML = html;
                } else {
                    container.innerHTML = '<p style="color: #dc3545;">Error loading invoices: ' + data.error + '</p>';
                }
            })
            .catch(error => {
                container.innerHTML = '<p style="color: #dc3545;">Error: ' + error + '</p>';
            });
        }

        function applyFilters() {
            filteredYear = document.getElementById('year-filter').value.trim();
            filteredStatus = document.getElementById('status-filter').value;
            renderTable();
        }

        function clearFilters() {
            document.getElementById('year-filter').value = '';
            document.getElementById('status-filter').value = 'all';
            filteredYear = '';
            filteredStatus = 'all';
            renderTable();
        }

        function renderTable() {
            const tbody = document.getElementById('jobs-tbody');
            const statsDiv = document.getElementById('filter-stats');

            // Filter data
            let filtered = jobsData;

            // Filter by year
            if (filteredYear) {
                filtered = filtered.filter(job => job[2].toString() === filteredYear);
            }

            // Filter by status
            if (filteredStatus === 'active') {
                filtered = filtered.filter(job => job[4] === 1);
            } else if (filteredStatus === 'inactive') {
                filtered = filtered.filter(job => job[4] === 0);
            }

            // Sort alphabetically (A-Z) by job name
            filtered.sort((a, b) => {
                return a[1].toLowerCase().localeCompare(b[1].toLowerCase());
            });

            // Calculate stats
            const totalJobs = filtered.length;
            const activeJobs = filtered.filter(j => j[4] === 1).length;
            const totalInvoiced = filtered.reduce((sum, j) => sum + j[5], 0);
            const totalEstimated = filtered.reduce((sum, j) => sum + j[7], 0);

            // Update stats
            statsDiv.innerHTML = `
                <div class="stat-item">
                    <div class="stat-number">${totalJobs}</div>
                    <div class="stat-label">Total Jobs</div>
                </div>
                <div class="stat-item">
                    <div class="stat-number">${activeJobs}</div>
                    <div class="stat-label">Active Jobs</div>
                </div>
                <div class="stat-item">
                    <div class="stat-number">$${totalEstimated.toFixed(2)}</div>
                    <div class="stat-label">Total Estimated</div>
                </div>
                <div class="stat-item">
                    <div class="stat-number">$${totalInvoiced.toFixed(2)}</div>
                    <div class="stat-label">Total Invoiced</div>
                </div>
            `;

            // Build table HTML
            if (filtered.length === 0) {
                tbody.innerHTML = '<tr><td colspan="9" class="no-results">No jobs found matching filters. Try adjusting your search.</td></tr>';
                return;
            }

            let html = '';
            filtered.forEach(job => {
                const diff = job[5] - job[7];
                const diffClass = diff > 0 ? 'money-negative' : 'money-positive';
                const diffSign = diff > 0 ? '+' : '';

                html += `<tr onclick="toggleJobDetails(${job[0]})">
                    <td><span class="expand-icon" id="icon-${job[0]}">▶</span></td>
                    <td><strong>${job[1]}</strong></td>
                    <td>${job[2]}</td>
                    <td>${job[8]} POs (${job[6]} invoiced)</td>
                    <td>$${job[7].toFixed(2)}</td>
                    <td>$${job[5].toFixed(2)}</td>
                    <td><span class="${diffClass}">${diffSign}$${diff.toFixed(2)}</span></td>
                    <td><span class="status-badge ${job[4] === 1 ? 'status-active' : 'status-inactive'}">
                        ${job[4] === 1 ? 'Active' : 'Inactive'}
                    </span></td>
                    <td>
                        <button onclick="editJob(${job[0]}, '${job[1]}', ${job[2]}, event)" class="btn btn-primary" style="padding: 5px 10px; margin-right: 5px;">Edit</button>
                        <button onclick="toggleJob(${job[0]}, event)" class="btn btn-secondary" style="padding: 5px 10px; margin-right: 5px;">
                            ${job[4] === 1 ? 'Deactivate' : 'Activate'}
                        </button>
                        <button onclick="deleteJob(${job[0]}, '${job[1]}', event)" class="btn btn-danger" style="padding: 5px 10px;">Delete</button>
                    </td>
                </tr>
                <tr class="expandable-row" id="details-${job[0]}">
                    <td colspan="9">
                        <div class="invoice-details" id="invoice-container-${job[0]}">
                            <!-- Invoice details loaded here -->
                        </div>
                    </td>
                </tr>`;
            });

            tbody.innerHTML = html;
        }

        // Initialize on page load
        window.addEventListener('DOMContentLoaded', function() {
            renderTable();
        });
    </script>
</head>
<body>
    <div class="header">
        <h1>📋 Manage Jobs</h1>
        <div>
            <a href="{{ url_for('office_dashboard') }}" class="btn btn-secondary">← Back to Dashboard</a>
            <a href="{{ url_for('logout') }}" class="btn btn-danger">Logout</a>
        </div>
    </div>

    <div class="card">
        <h2 style="color: #667eea; margin-bottom: 20px;">Add New Job</h2>
        <div class="form-group">
            <label>Job Name</label>
            <input type="text" id="job_name" placeholder="e.g., Chase Bank, Seven Lakes">
        </div>
        <div class="form-group">
            <label>Year</label>
            <input type="number" id="year" placeholder="e.g., 2025" value="2025">
        </div>
        <button onclick="addJob()" class="btn btn-success">Add Job</button>
    </div>

    <div class="card">
        <h2 style="color: #667eea; margin-bottom: 20px;">Filter Jobs</h2>

        <!-- Filter Controls -->
        <div class="filter-controls">
            <div class="filter-group">
                <label>Filter by Year</label>
                <input type="number" id="year-filter" placeholder="e.g., 2025" min="2000" max="2100">
            </div>
            <div class="filter-group">
                <label>Filter by Status</label>
                <select id="status-filter">
                    <option value="all">All Jobs</option>
                    <option value="active">Active Only</option>
                    <option value="inactive">Inactive Only</option>
                </select>
            </div>
            <div class="filter-group">
                <label>&nbsp;</label>
                <button onclick="applyFilters()" class="btn btn-primary" style="width: 100%;">Apply Filters</button>
            </div>
            <div class="filter-group">
                <label>&nbsp;</label>
                <button onclick="clearFilters()" class="btn btn-secondary" style="width: 100%;">Clear Filters</button>
            </div>
        </div>

        <!-- Stats -->
        <div class="filter-stats" id="filter-stats">
            <!-- Stats populated by JavaScript -->
        </div>

        <h3 style="color: #667eea; margin-bottom: 15px;">Jobs (Sorted A-Z) - Click to Expand</h3>
        <table>
            <thead>
                <tr>
                    <th width="30"></th>
                    <th>Job Name</th>
                    <th>Year</th>
                    <th>POs</th>
                    <th>Total Estimated</th>
                    <th>Total Invoiced</th>
                    <th>Difference</th>
                    <th>Status</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody id="jobs-tbody">
                <!-- Jobs rendered by JavaScript -->
            </tbody>
        </table>
    </div>
</body>
</html>
'''
LOGIN_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>PO Request System - Login</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .container {
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            width: 100%;
            max-width: 400px;
        }
        h1 { color: #333; margin-bottom: 10px; font-size: 28px; }
        .subtitle { color: #666; margin-bottom: 30px; font-size: 14px; }
        .form-group { margin-bottom: 20px; }
        label { display: block; margin-bottom: 5px; color: #555; font-weight: bold; }
        input {
            width: 100%;
            padding: 12px;
            border: 2px solid #ddd;
            border-radius: 5px;
            font-size: 16px;
        }
        input:focus { outline: none; border-color: #667eea; }
        button {
            width: 100%;
            padding: 12px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 5px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
        }
        button:hover { background: #5568d3; }
        .error {
            background: #fee;
            color: #c33;
            padding: 10px;
            border-radius: 5px;
            margin-bottom: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🌱 Irrigation PO System</h1>
        <p class="subtitle">Purchase Order Request System</p>
        {% with messages = get_flashed_messages() %}
            {% if messages %}
                {% for message in messages %}
                    <div class="error">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        <form method="POST">
            <div class="form-group">
                <label>Username</label>
                <input type="text" name="username" required autofocus>
            </div>
            <div class="form-group">
                <label>Password</label>
                <input type="password" name="password" required>
            </div>
            <button type="submit">Login</button>
        </form>
    <div style="text-align: center; margin-top: 20px; color: #666;">
            Office Manager? <a href="{{ url_for('register') }}" style="color: #667eea; text-decoration: none; font-weight: bold;">Create Account</a>
        </div>
        <div style="text-align: center; margin-top: 15px;">
            <a href="{{ url_for('forgot_password') }}" style="color: #667eea; text-decoration: none; font-size: 14px;">Forgot your password?</a>
        </div>
    </div>
</body>
</html>
'''

# COMPLETE TECH_DASHBOARD_TEMPLATE - Replace your existing one with this

TECH_DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Technician Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px; }
        .header {
            background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1); display: flex;
            justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;
        }
        h1 { color: #333; font-size: 24px; }
        .logout-btn {
            background: #dc3545; color: white; padding: 10px 20px;
            text-decoration: none; border-radius: 5px; font-size: 14px;
        }
        .card {
            background: white; padding: 20px; border-radius: 10px;
            margin-bottom: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        h2 { color: #667eea; margin-bottom: 20px; font-size: 20px; }
        .form-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 5px; color: #555; font-weight: bold; }
        input, textarea, select {
            width: 100%; padding: 10px; border: 2px solid #ddd;
            border-radius: 5px; font-size: 16px;
        }
        textarea { min-height: 100px; resize: vertical; }
        button {
            background: #667eea; color: white; padding: 12px 30px;
            border: none; border-radius: 5px; font-size: 16px;
            cursor: pointer; font-weight: bold;
        }
        button:hover { background: #5568d3; }
        .request-item {
            background: #f9f9f9; padding: 15px; border-left: 4px solid #667eea;
            margin-bottom: 15px; border-radius: 5px; position: relative;
        }
        .request-item.approved { border-left-color: #28a745; }
        .request-item.denied { border-left-color: #dc3545; }
        .status {
            display: inline-block; padding: 5px 15px; border-radius: 20px;
            font-size: 12px; font-weight: bold; margin-bottom: 10px;
        }
        .status.pending { background: #ffc107; color: #000; }
        .status.approved { background: #28a745; color: white; }
        .status.denied { background: #dc3545; color: white; }
        .success {
            background: #d4edda; color: #155724; padding: 15px;
            border-radius: 5px; margin-bottom: 20px;
        }
        .invoice-data {
            background: #e7f3ff; padding: 15px; border-radius: 5px;
            margin-top: 15px; border-left: 4px solid #0066cc;
        }
        .invoice-data h4 { color: #0066cc; margin-bottom: 10px; }
        #job_suggestions {
            position: relative;
            background: white;
            border: 2px solid #667eea;
            border-radius: 5px;
            max-height: 300px;
            overflow-y: auto;
            margin-top: 5px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            z-index: 1000;
        }
        .job-suggestion-item {
            padding: 15px;
            border-bottom: 1px solid #eee;
            font-size: 16px;
            cursor: pointer;
            transition: background 0.2s;
        }
        .job-suggestion-item:hover {
            background: #f0f4ff;
        }
        .job-suggestion-item:last-child {
            border-bottom: none;
        }
        .error-message {
            background: #f8d7da;
            color: #721c24;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
            border-left: 4px solid #dc3545;
            font-weight: bold;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>👷 Technician Dashboard - {{ username }}</h1>
        <a href="{{ url_for('logout') }}" class="logout-btn">Logout</a>
    </div>

    {% with messages = get_flashed_messages() %}
        {% if messages %}
            {% for message in messages %}
                {% if 'ERROR' in message or '❌' in message %}
                    <div class="error-message">{{ message }}</div>
                {% else %}
                    <div class="success">{{ message }}</div>
                {% endif %}
            {% endfor %}
        {% endif %}
    {% endwith %}

    <div class="card">
        <h2>📝 Submit New PO Request</h2>
        <form method="POST" action="{{ url_for('submit_request') }}">
            <div class="form-group">
                <label>Your Full Name</label>
                <input type="text" name="tech_name" required placeholder="e.g., John Smith">
            </div>

            <div class="form-group">
                <label style="display: flex; align-items: center; gap: 10px; cursor: pointer;">
                    <input type="checkbox" id="use-custom-po" style="width: auto; margin: 0; cursor: pointer;"
                           onclick="var f=document.getElementById('custom-po-field'); var i=document.getElementById('custom_po_number'); if(this.checked){f.style.display='block';i.required=true;}else{f.style.display='none';i.required=false;i.value='';}">
                    Use Custom PO Number
                </label>
            </div>

            <div class="form-group" id="custom-po-field" style="display: none;">
                <label>Custom PO Number</label>
                <input type="number" id="custom_po_number" name="custom_po_number" placeholder="e.g., 9810" min="1">
                <small style="color: #666;">Enter specific PO number (must be 9000 or higher)</small>
            </div>
            
            <div class="form-group">
                <label>Job/Project Name <span style="color: red;">*</span></label>
                <div style="position: relative;">
                    <input type="text" id="job_search" name="job_name" placeholder="Start typing job name..." autocomplete="off" required style="padding-right: 40px;">
                    <button type="button" id="clear-job" onclick="clearJobName()" style="position: absolute; right: 10px; top: 50%; transform: translateY(-50%); background: #dc3545; color: white; border: none; border-radius: 3px; padding: 5px 10px; cursor: pointer; display: none; font-size: 14px; font-weight: bold;">✕</button>
                </div>
                <div id="job_suggestions" style="display: none;"></div>
                <small id="job_hint" style="color: #666; display: block; margin-top: 5px;">💡 Type to search active jobs - auto-fills as you type</small>
            </div>

            <div class="form-group">
                <label>Store Name</label>
                <input type="text" name="store_name" required placeholder="e.g., Home Depot, Lowes">
            </div>

            <div class="form-group">
                <label>Estimated Cost ($)</label>
                <input type="number" step="0.01" name="estimated_cost" required placeholder="0.00" min="0">
            </div>

            <div class="form-group">
                <label>Description / Items Needed</label>
                <textarea name="description" required placeholder="List what you need to purchase..."></textarea>
            </div>

            <button type="submit">Submit Request</button>
        </form>
    </div>

<script>
    // Global variables
    let allJobs = [];
    let validJobSelected = false;

    window.addEventListener('DOMContentLoaded', function() {
        console.log('Page loaded, initializing...');

        const searchInput = document.getElementById('job_search');
        const suggestionsDiv = document.getElementById('job_suggestions');
        const clearBtn = document.getElementById('clear-job');
        const hintText = document.getElementById('job_hint');

        // Fetch jobs from server
        fetch('/get_jobs')
            .then(response => response.json())
            .then(data => {
                console.log('Jobs loaded:', data);
                if (data.success && data.jobs) {
                    allJobs = data.jobs;
                    console.log('✓ Available jobs:', allJobs.length);
                    if (hintText && allJobs.length > 0) {
                        hintText.innerHTML = `💡 ${allJobs.length} active jobs available - start typing to search`;
                    }
                } else {
                    console.error('Failed to load jobs:', data);
                    if (hintText) {
                        hintText.innerHTML = '⚠️ Could not load jobs - please refresh the page';
                        hintText.style.color = '#dc3545';
                    }
                }
            })
            .catch(error => {
                console.error('Error loading jobs:', error);
                if (hintText) {
                    hintText.innerHTML = '⚠️ Error loading jobs - please refresh the page';
                    hintText.style.color = '#dc3545';
                }
            });

        // Show suggestions as user types
searchInput.addEventListener('input', function(e) {
    const query = this.value.trim();
    console.log('→ User typed:', query);

    // Show/hide clear button
    if (clearBtn) {
        clearBtn.style.display = query.length > 0 ? 'block' : 'none';
    }

    // Hide suggestions if empty
    if (query.length < 1) {
        suggestionsDiv.style.display = 'none';
        this.style.borderColor = '#ddd';
        return;
    }

    // Find matching jobs
    const queryLower = query.toLowerCase();
    const matches = allJobs.filter(job =>
        job.name.toLowerCase().includes(queryLower)
    );

    console.log('→ Found matches:', matches.length);

    // No matches
    if (matches.length === 0) {
        suggestionsDiv.innerHTML = '<div class="job-suggestion-item" style="color: #dc3545;">❌ No jobs match "' + query + '"</div>';
        suggestionsDiv.style.display = 'block';
        this.style.borderColor = '#dc3545';
        return;
    }

    // AUTO-FILL: If exact match found, fill it automatically
    const exactMatch = matches.find(job => 
        job.name.toLowerCase() === queryLower
    );

    if (exactMatch) {
        console.log('✓ Exact match found - auto-filling:', exactMatch.name);
        this.value = exactMatch.name;
        this.style.borderColor = '#28a745'; // Green
        suggestionsDiv.style.display = 'none';
        if (hintText) {
            hintText.innerHTML = `✓ Selected: ${exactMatch.name} (${exactMatch.year})`;
            hintText.style.color = '#28a745';
        }
        return;
    }

    // Show matches in dropdown
    let html = '';
    matches.forEach(job => {
        // Highlight the matching part
        const jobNameLower = job.name.toLowerCase();
        const matchIndex = jobNameLower.indexOf(queryLower);
        let displayName = job.name;

        if (matchIndex >= 0) {
            const before = job.name.substring(0, matchIndex);
            const matchText = job.name.substring(matchIndex, matchIndex + query.length);
            const after = job.name.substring(matchIndex + query.length);
            displayName = before + '<span style="background: #ffeb3b; font-weight: bold;">' + matchText + '</span>' + after;
        }

        html += `<div class="job-suggestion-item" onclick="selectJob('${job.name.replace(/'/g, "\\'")}')">`;
        html += `${displayName} <span style="color: #999;">(${job.year})</span>`;
        html += '</div>';
    });

    suggestionsDiv.innerHTML = html;
    suggestionsDiv.style.display = 'block';
    this.style.borderColor = '#667eea';

    if (hintText) {
        hintText.innerHTML = `💡 ${matches.length} job${matches.length > 1 ? 's' : ''} match - type full name or click to select`;
        hintText.style.color = '#667eea';
    }
});    

                // Multiple matches or exact match handling
                if (matches.length === 1) {
                    const match = matches[0];
                    const queryLower = query.toLowerCase();
                    const matchLower = match.name.toLowerCase();
                    
                    // Only auto-fill if it's an EXACT match (not just a partial match)
                    if (matchLower === queryLower) {
                        console.log('🎯 Auto-filling exact match:', match.name);
                        this.value = match.name;
                        this.style.borderColor = '#28a745'; // Green border
                        validJobSelected = true;
                        suggestionsDiv.style.display = 'none';
                        if (hintText) {
                            hintText.innerHTML = `✓ Selected: ${match.name} (${match.year})`;
                            hintText.style.color = '#28a745';
                        }
                        return;
                    }
                    
                    // If not exact match, show it in dropdown instead of auto-filling
                    console.log('Showing single match in dropdown (not exact)');
                }
                
                // Show dropdown for all non-exact matches
                if (matches.length > 0) {
                        const before = job.name.substring(0, matchIndex);
                        const matchText = job.name.substring(matchIndex, matchIndex + query.length);
                        const after = job.name.substring(matchIndex + query.length);
                        displayName = before + '<span style="background: #ffeb3b; font-weight: bold;">' + matchText + '</span>' + after;
                    }

                    html += `<div class="job-suggestion-item" onclick="selectJob('${job.name.replace(/'/g, "\\'")}')">`;
                    html += `${displayName} <span style="color: #999; font-size: 13px;">(${job.year})</span>`;
                    html += '</div>';
                });

                if (matches.length > 10) {
                    html += '<div style="padding: 8px; text-align: center; color: #999; font-size: 12px;">...and ' + (matches.length - 10) + ' more. Keep typing to narrow down.</div>';
                }

                suggestionsDiv.innerHTML = html;
                suggestionsDiv.style.display = 'block';

                if (hintText) {
                    hintText.innerHTML = `💡 ${matches.length} job${matches.length > 1 ? 's' : ''} match "${query}" - keep typing or click to select`;
                    hintText.style.color = '#667eea';
                }
            });

            // Close suggestions when clicking outside
            document.addEventListener('click', function(e) {
                if (!searchInput.contains(e.target) && !suggestionsDiv.contains(e.target)) {
                    suggestionsDiv.style.display = 'none';
                }
            });

            // Handle keyboard navigation (Enter key)
            searchInput.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') {
                    const currentValue = this.value.trim();
                    const exactMatch = allJobs.find(job =>
                        job.name.toLowerCase() === currentValue.toLowerCase()
                    );

                    if (exactMatch) {
                        selectJob(exactMatch.name);
                        e.preventDefault(); // Prevent form submission
                    }
                }
            });
        }
    });

    function selectJob(jobName) {
        const searchInput = document.getElementById('job_search');
        const suggestionsDiv = document.getElementById('job_suggestions');
        const clearBtn = document.getElementById('clear-job');
        const hintText = document.getElementById('job_hint');

        if (searchInput) {
            searchInput.value = jobName;
            searchInput.style.borderColor = '#28a745'; // Green
            validJobSelected = true;
        }
        if (suggestionsDiv) {
            suggestionsDiv.style.display = 'none';
        }
        if (clearBtn) {
            clearBtn.style.display = 'block';
        }

        const selectedJob = allJobs.find(job => job.name === jobName);
        if (hintText && selectedJob) {
            hintText.innerHTML = `✓ Selected: ${selectedJob.name} (${selectedJob.year})`;
            hintText.style.color = '#28a745';
        }

        console.log('✓ Selected:', jobName);
    }

    function clearJobName() {
        const searchInput = document.getElementById('job_search');
        const clearBtn = document.getElementById('clear-job');
        const hintText = document.getElementById('job_hint');

        searchInput.value = '';
        searchInput.style.borderColor = '#ddd';
        validJobSelected = false;
        if (clearBtn) clearBtn.style.display = 'none';
        if (hintText) {
            hintText.innerHTML = `💡 ${allJobs.length} active jobs available - start typing to search`;
            hintText.style.color = '#666';
        }
        searchInput.focus();
    }

    // STRICT form validation - prevents submission with invalid job names
    document.addEventListener('DOMContentLoaded', function() {
        const form = document.querySelector('form[action="{{ url_for(\'submit_request\') }}"]');
        if (form) {
            form.addEventListener('submit', function(e) {
                const jobInput = document.getElementById('job_search');
                const jobName = jobInput.value.trim();

                if (!jobName) {
                    e.preventDefault();
                    alert('❌ ERROR: Please enter a job name');
                    jobInput.focus();
                    return false;
                }

                // Verify job exists EXACTLY in active jobs list
                const exactMatch = allJobs.find(job =>
                    job.name.toLowerCase() === jobName.toLowerCase()
                );

                if (!exactMatch) {
                    e.preventDefault();

                    // Find similar jobs to suggest
                    const similar = allJobs.filter(job =>
                        job.name.toLowerCase().includes(jobName.toLowerCase())
                    ).slice(0, 3);

                    let msg = '❌ INVALID JOB NAME\\n\\n';
                    msg += 'The job "' + jobName + '" is not an active job in the system.\\n\\n';

                    if (similar.length > 0) {
                        msg += 'Did you mean one of these?\\n';
                        similar.forEach(job => {
                            msg += '  • ' + job.name + ' (' + job.year + ')\\n';
                        });
                        msg += '\\nPlease select a job from the dropdown list.';
                    } else {
                        msg += 'Please type a job name and select from the dropdown list.\\n';
                        msg += 'Only active jobs can be used for PO requests.';
                    }

                    alert(msg);
                    jobInput.focus();
                    jobInput.select();
                    jobInput.style.borderColor = '#dc3545';

                    const hintText = document.getElementById('job_hint');
                    if (hintText) {
                        hintText.innerHTML = '❌ Invalid job - must select from active jobs list';
                        hintText.style.color = '#dc3545';
                    }

                    return false;
                }

                console.log('✅ Form submitted with valid job:', exactMatch.name);
                return true;
            });
        }
    });
</script>

    <div class="card">
        <h2>📋 My PO Requests</h2>
        {% if requests %}
            {% for req in requests %}
                <div class="request-item {{ req[7] }}">
                    <span class="status {{ req[7] }}">{{ req[7]|upper }}</span>
                    <h3>PO #{{ format_po_number(req[0], req[3]) }} - {{ req[4] }}</h3>
                    <p><strong>Technician:</strong> {{ req[2] }}</p>
                    <p><strong>Job:</strong> {{ req[3] }}</p>
                    <p><strong>Estimated Amount:</strong> ${{ "%.2f"|format(req[5]) }}</p>
                    <p><strong>Description:</strong> {{ req[6] }}</p>
                    <p><strong>Requested:</strong> {{ req[8] }}</p>

                    {% if req[7] == 'approved' or req[7] == 'denied' %}
                        <p><strong>Decision Date:</strong> {{ req[9] }}</p>
                        {% if req[10] %}
                            <p><strong>Notes:</strong> {{ req[10] }}</p>
                        {% endif %}
                        <p><strong>Decided by:</strong> {{ req[11] if req|length > 11 else 'N/A' }}</p>
                    {% endif %}

                    {% if req[7] == 'approved' %}
                        {% if req|length > inv_filename_idx and req[inv_filename_idx] and req[inv_filename_idx] != '' %}
                            <div class="invoice-data">
                                <h4>📄 Invoice Entered by Office</h4>
                                <p><strong>Invoice Number:</strong> {{ req[inv_number_idx] if req|length > inv_number_idx else 'N/A' }}</p>
                                <p><strong>Total Cost:</strong> ${{ req[inv_cost_idx] if req|length > inv_cost_idx else '0.00' }}</p>
                                <p><strong>Entered:</strong> {{ req[inv_upload_idx] if req|length > inv_upload_idx else 'N/A' }}</p>
                            </div>
                        {% else %}
                            <p style="color: orange; margin-top: 10px;">⏳ Waiting for office to enter invoice details</p>
                        {% endif %}
                    {% endif %}
                </div>
            {% endfor %}
        {% else %}
            <p style="color: #999;">No requests yet. Submit your first PO request above!</p>
        {% endif %}
    </div>
</body>
</html>
'''

OFFICE_DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Office Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px; }
        .header {
            background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1); display: flex;
            justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;
        }
        h1 { color: #333; font-size: 24px; }
        .logout-btn {
            background: #dc3545; color: white; padding: 10px 20px;
            text-decoration: none; border-radius: 5px; font-size: 14px;
        }
        .search-card {
            background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        .search-form { display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; }
        .search-form input, .search-form select {
            flex: 1; min-width: 200px; padding: 12px; border: 2px solid #ddd;
            border-radius: 5px; font-size: 16px;
        }
        .search-btn {
            background: #667eea; color: white; padding: 12px 30px; border: none;
            border-radius: 5px; font-size: 16px; cursor: pointer; font-weight: bold;
        }
        .stats {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 20px; margin-bottom: 20px;
        }
        .stat-card {
            background: white; padding: 20px; border-radius: 10px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1); text-align: center;
        }
        .stat-number { font-size: 36px; font-weight: bold; color: #667eea; }
        .stat-label { color: #666; margin-top: 5px; }
        .tabs {
            background: white; padding: 0; border-radius: 10px 10px 0 0;
            display: flex; overflow-x: auto;
        }
        .tab {
            flex: 1; min-width: 150px; padding: 15px; background: #f9f9f9;
            border: none; cursor: pointer; font-size: 16px; font-weight: bold;
            color: #666; white-space: nowrap;
        }
        .tab.active {
            background: white; color: #667eea; border-bottom: 3px solid #667eea;
        }
        .tab-content {
            background: white; padding: 20px; border-radius: 0 0 10px 10px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1); display: none;
        }
        .tab-content.active { display: block; }
        .request-item {
            background: #f9f9f9; padding: 20px; border-left: 4px solid #667eea;
            margin-bottom: 15px; border-radius: 5px; position: relative;
        }
        .request-item h3 { color: #333; margin-bottom: 10px; }
        .action-form {
            margin-top: 15px; padding-top: 15px; border-top: 2px solid #ddd;
        }
        .action-form textarea {
            width: 100%; padding: 10px; border: 2px solid #ddd; border-radius: 5px;
            margin-bottom: 10px; min-height: 60px;
        }
        .action-buttons { display: flex; gap: 10px; flex-wrap: wrap; }
        .approve-btn {
            flex: 1; min-width: 120px; background: #28a745; color: white;
            padding: 10px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold;
        }
        .deny-btn {
            flex: 1; min-width: 120px; background: #dc3545; color: white;
            padding: 10px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold;
        }
        .delete-btn {
            position: absolute; top: 20px; right: 20px; background: #dc3545;
            color: white; padding: 6px 12px; border: none; border-radius: 5px;
            cursor: pointer; font-size: 12px; font-weight: bold;
        }
        .delete-btn:hover { background: #c82333; }

        /* Mobile-friendly delete buttons */
        @media (max-width: 768px) {
            .delete-btn {
                position: static;
                margin-top: 10px;
                display: inline-block;
                font-size: 11px;
                padding: 5px 10px;
            }
        }
        .status {
            display: inline-block; padding: 5px 15px; border-radius: 20px;
            font-size: 12px; font-weight: bold; margin-bottom: 10px;
        }
        .status.approved { background: #28a745; color: white; }
        .status.denied { background: #dc3545; color: white; }
        .invoice-data {
            background: #e7f3ff; padding: 15px; border-radius: 5px;
            margin-top: 15px; border-left: 4px solid #0066cc;
        }
        .invoice-data h4 { color: #0066cc; margin-bottom: 10px; }
        .search-results {
            background: #fff3cd; padding: 20px; border-radius: 10px;
            margin-bottom: 20px; border-left: 4px solid #ffc107;
        }
        .search-results h3 { color: #856404; margin-bottom: 15px; }
        .success-message {
            background: #d4edda; color: #155724; padding: 15px;
            border-radius: 5px; margin-bottom: 20px; border-left: 4px solid #28a745;
        }
        .invoice-upload-section {
            background: #f0f8ff; padding: 15px; border-radius: 5px;
            margin-top: 15px; border: 2px dashed #667eea;
        }
        .invoice-upload-section h4 { color: #667eea; margin-bottom: 10px; }
        .invoice-form { display: grid; gap: 10px; }
        .invoice-form input[type="text"], .invoice-form input[type="number"] {
            width: 100%; padding: 10px; border: 2px solid #ddd;
            border-radius: 5px; font-size: 14px;
        }
        .dropzone {
            border: 2px dashed #ccc; border-radius: 5px; padding: 20px;
            text-align: center; background: #fafafa; cursor: pointer;
            transition: all 0.3s; margin-bottom: 10px;
        }
        .dropzone:hover, .dropzone.dragover {
            background: #e7f0ff; border-color: #667eea;
        }
        .dropzone p { color: #666; font-size: 14px; margin: 0; }
        .upload-invoice-btn {
            background: #667eea; color: white; padding: 10px 20px;
            border: none; border-radius: 5px; cursor: pointer;
            font-weight: bold; width: 100%; font-size: 14px;
        }
        .upload-invoice-btn:hover { background: #5568d3; }
        .upload-invoice-btn:disabled { background: #ccc; cursor: not-allowed; }
        .error-message {
            background: #f8d7da;
            color: #721c24;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
            border-left: 4px solid #dc3545;
            font-weight: bold;
        }
        .po-checkbox {
    width: 20px;
    height: 20px;
    cursor: pointer;
    margin-right: 10px;
}

#bulk-actions {
    position: fixed;
    bottom: 20px;
    right: 20px;
    background: white;
    padding: 20px;
    border-radius: 10px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    z-index: 1000;
    display: none;
}

#bulk-actions h3 {
    margin: 0 0 15px 0;
    color: #667eea;
}

.bulk-btn {
    padding: 10px 20px;
    margin: 5px;
    border: none;
    border-radius: 5px;
    font-weight: bold;
    cursor: pointer;
    font-size: 14px;
}

.bulk-approve-btn {
    background: #28a745;
    color: white;
}

.bulk-deny-btn {
    background: #dc3545;
    color: white;
}

.bulk-cancel-btn {
    background: #6c757d;
    color: white;
}

.select-all-container {
    background: #f0f4ff;
    padding: 15px;
    border-radius: 5px;
    margin-bottom: 15px;
    display: flex;
    align-items: center;
    gap: 10px;
}
.po-checkbox {
            width: 20px;
            height: 20px;
            cursor: pointer;
            margin-right: 10px;
        }

        #bulk-actions {
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            z-index: 1000;
            display: none;
        }

        #bulk-actions h3 {
            margin: 0 0 15px 0;
            color: #667eea;
        }

        .bulk-btn {
            padding: 10px 20px;
            margin: 5px;
            border: none;
            border-radius: 5px;
            font-weight: bold;
            cursor: pointer;
            font-size: 14px;
        }

        .bulk-approve-btn {
            background: #28a745;
            color: white;
        }

        .bulk-deny-btn {
            background: #dc3545;
            color: white;
        }

        .bulk-cancel-btn {
            background: #6c757d;
            color: white;
        }

        .select-all-container {
            background: #f0f4ff;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
    </style>
    <script>
        function showTab(tabName) {
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.getElementById(tabName).classList.add('active');
            event.target.classList.add('active');
        }

        function initDropzone(poId) {
            const dropzone = document.getElementById('dropzone-' + poId);
            const fileInput = document.getElementById('file-' + poId);
            if (!dropzone || !fileInput) return;
            ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
                dropzone.addEventListener(eventName, preventDefaults, false);
            });
            function preventDefaults(e) {
                e.preventDefault();
                e.stopPropagation();
            }
            ['dragenter', 'dragover'].forEach(eventName => {
                dropzone.addEventListener(eventName, () => {
                    dropzone.classList.add('dragover');
                }, false);
            });
            ['dragleave', 'drop'].forEach(eventName => {
                dropzone.addEventListener(eventName, () => {
                    dropzone.classList.remove('dragover');
                }, false);
            });
            dropzone.addEventListener('drop', (e) => {
                const dt = e.dataTransfer;
                const files = dt.files;
                fileInput.files = files;
                handleFiles(files, poId);
            }, false);
            dropzone.addEventListener('click', () => {
                fileInput.click();
            });
            fileInput.addEventListener('change', (e) => {
                handleFiles(e.target.files, poId);
            });
        }

        function handleFiles(files, poId) {
            if (files.length > 0) {
                const file = files[0];
                const dropzone = document.getElementById('dropzone-' + poId);
                dropzone.innerHTML = '<p style="color: #28a745; font-weight: bold;">✓ File selected: ' + file.name + '</p>';
            }
        }

        function uploadInvoice(poId) {
            const form = document.getElementById('invoice-form-' + poId);
            if (!form) {
                alert('ERROR: Form not found for PO ' + poId);
                return;
            }
            const formData = new FormData(form);
            const invoiceNumber = formData.get('invoice_number');
            const invoiceCost = formData.get('invoice_cost');
            if (!invoiceNumber || !invoiceCost) {
                alert('Please enter both invoice number and total cost');
                return;
            }
            const btn = event.target;
            btn.disabled = true;
            btn.textContent = 'Saving...';
            fetch('/upload_invoice/' + poId, {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('✓ ' + data.message);
                    location.reload();
                } else {
                    alert('Error: ' + data.error);
                    btn.disabled = false;
                    btn.textContent = '💾 Save Invoice Details';
                }
            })
            .catch(error => {
                alert('Error uploading: ' + error);
                btn.disabled = false;
                btn.textContent = '💾 Save Invoice Details';
            });
        }

        function deleteRequest(requestId) {
            if (confirm('Are you sure you want to delete this PO request? This action cannot be undone.')) {
                fetch('/delete_request', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({request_id: requestId})
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert('PO request deleted successfully');
                        location.reload();
                    } else {
                        alert('Error: ' + data.error);
                    }
                })
                .catch(error => {
                    alert('Error deleting request');
                });
            }
        }

        function deleteInvoice(requestId) {
    if (confirm('Delete this invoice and move PO back to Approved tab?')) {
        fetch('/delete_invoice', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({request_id: requestId})
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                alert('✓ ' + data.message);
                location.reload();
            } else {
                alert('Error: ' + data.error);
            }
        })
        .catch(error => {
            alert('Error deleting invoice');
        });
    }
}

function undoApproval(requestId) {
    if (confirm('Move this PO back to Pending? This will undo the approval.')) {
        fetch('/undo_approval', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({request_id: requestId})
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                alert('✓ ' + data.message);
                location.reload();
            } else {
                alert('Error: ' + data.error);
            }
        })
        .catch(error => {
            console.error('Full error:', error);
            alert('Error undoing approval: ' + error);
        });
    }
}

        function uploadBulkPDF() {
            const fileInput = document.getElementById('bulk-pdf-input');
            const statusDiv = document.getElementById('bulk-upload-status');
            const btn = document.getElementById('bulk-upload-btn');

            console.log('uploadBulkPDF called');

            if (!fileInput.files || fileInput.files.length === 0) {
                alert('Please select a PDF file');
                return;
            }

            const file = fileInput.files[0];
            console.log('File selected:', file.name, 'Size:', file.size);

            if (!file.name.toLowerCase().endsWith('.pdf')) {
                alert('Please select a PDF file');
                return;
            }

            btn.disabled = true;
            btn.textContent = '⏳ Processing...';
            statusDiv.style.display = 'block';
            statusDiv.innerHTML = '<p style="color: white;">Processing PDF, please wait...</p>';

            const formData = new FormData();
            formData.append('bulk_pdf', file);

            console.log('Sending request to /bulk_upload_invoices');

            fetch('/bulk_upload_invoices', {
                method: 'POST',
                body: formData
            })
            .then(response => {
                console.log('Response status:', response.status);
                return response.json();
            })
            .then(data => {
                console.log('Response data:', data);
                btn.disabled = false;
                btn.textContent = '📤 Process PDF';

                if (data.success) {
                    let html = '<div style="background: white; color: #333; padding: 15px; border-radius: 5px;">';
                    html += '<h3 style="color: #28a745; margin-bottom: 10px;">✅ ' + data.message + '</h3>';

                    if (data.details && data.details.length > 0) {
                        html += '<h4 style="margin-top: 15px;">Matched Invoices:</h4><ul style="list-style: none; padding: 0;">';
                        data.details.forEach(detail => {
                            html += '<li style="padding: 8px; background: #e7f3ff; margin: 5px 0; border-radius: 3px;">';
                            html += '📄 Page ' + detail.page + ' → <strong>PO #' + detail.po_number + ' - ' + detail.job_name;
                            if (detail.estimated_cost !== undefined) {
                                  html += ' - Est. $' + Number(detail.estimated_cost).toFixed(2);
                            }
                            html += '</strong><br>';
                            html += '&nbsp;&nbsp;&nbsp;&nbsp;Invoice: ' + detail.invoice_number + ' | Actual Cost: $' + detail.cost + '</li>';
                        });
                        html += '</ul>';
                    }

                    if (data.errors && data.errors.length > 0) {
                        html += '<h4 style="margin-top: 15px; color: #dc3545;">❌ ERRORS: ' + data.errors.length + '</h4>';
                        html += '<p style="font-size: 14px;">These invoices were found but have NO associated PO:</p>';
                        html += '<ul style="list-style: none; padding: 0;">';
                        data.errors.forEach(error => {
                            html += '<li style="padding: 8px; background: #f8d7da; margin: 5px 0; border-radius: 3px; font-size: 12px; border-left: 3px solid #dc3545;">';
                            html += '<strong>Page ' + error.page + ':</strong> Invoice #' + error.invoice_number + ' | Cost: $' + error.cost + '<br>';
                            html += '<span style="color: #dc3545; font-weight: bold;">ERROR: ' + error.error + '</span>';
                            html += '</li>';
                        });
                        html += '</ul>';
                    }

                    if (data.unmatched && data.unmatched.length > 0) {
                        html += '<h4 style="margin-top: 15px; color: #856404;">⚠️ Unmatched Pages: ' + data.unmatched.length + '</h4>';
                        html += '<p style="font-size: 14px;">These pages could not be matched automatically:</p>';
                        html += '<ul style="list-style: none; padding: 0;">';
                        data.unmatched.forEach(page => {
                            html += '<li style="padding: 8px; background: #fff3cd; margin: 5px 0; border-radius: 3px; font-size: 12px;">';
                            html += '📄 Page ' + page.page;
                            if (page.filename) {
                                 html += ' - <a href="/view_invoice/' + page.filename + '" target="_blank" style="color: #667eea; text-decoration: underline;">View PDF</a>';
                            }
                            html += '</li>';
                        });
                        html += '</ul>';
                    }

                    html += '<button onclick="location.reload()" style="margin-top: 15px; padding: 10px 20px; background: #667eea; color: white; border: none; border-radius: 5px; cursor: pointer; font-weight: bold;">Refresh to See Updates</button>';
                    html += '</div>';
                    statusDiv.innerHTML = html;
                } else {
                    statusDiv.innerHTML = '<div style="background: #f8d7da; color: #721c24; padding: 15px; border-radius: 5px;"><strong>Error:</strong> ' + data.error + '</div>';
                }
            })
            .catch(error => {
                console.error('Fetch error:', error);
                btn.disabled = false;
                btn.textContent = '📤 Process PDF';
                statusDiv.innerHTML = '<div style="background: #f8d7da; color: #721c24; padding: 15px; border-radius: 5px;"><strong>Error:</strong> ' + error + '<br><br>Check browser console (F12) for details.</div>';
            });
        }

        window.addEventListener('load', function() {
            document.querySelectorAll('.request-item[data-po-id]').forEach(item => {
                const poId = item.getAttribute('data-po-id');
                initDropzone(poId);
            });
        });
        // Bulk selection functionality
let selectedPOs = new Set();

function togglePOSelection(poId, checkbox) {
    if (checkbox.checked) {
        selectedPOs.add(poId);
    } else {
        selectedPOs.delete(poId);
    }
    updateBulkActionsButton();
}

function selectAllPending() {
    const checkboxes = document.querySelectorAll('.po-checkbox');
    const selectAllCheckbox = document.getElementById('select-all-pending');

    checkboxes.forEach(checkbox => {
        checkbox.checked = selectAllCheckbox.checked;
        const poId = parseInt(checkbox.dataset.poId);
        if (selectAllCheckbox.checked) {
            selectedPOs.add(poId);
        } else {
            selectedPOs.delete(poId);
        }
    });
    updateBulkActionsButton();
}

function updateBulkActionsButton() {
    const bulkActions = document.getElementById('bulk-actions');
    const countSpan = document.getElementById('selected-count');

    if (selectedPOs.size > 0) {
        bulkActions.style.display = 'block';
        countSpan.textContent = selectedPOs.size;
    } else {
        bulkActions.style.display = 'none';
    }
}

function bulkApprove() {
    if (selectedPOs.size === 0) {
        alert('Please select at least one PO');
        return;
    }

    const notes = prompt(`Add notes for ${selectedPOs.size} PO(s) (optional):`);

    if (notes === null) return; // User cancelled

    bulkProcessPOs('approve', notes);
}

function bulkDeny() {
    if (selectedPOs.size === 0) {
        alert('Please select at least one PO');
        return;
    }

    const notes = prompt(`Reason for denying ${selectedPOs.size} PO(s):`);

    if (!notes) {
        alert('Please provide a reason for denial');
        return;
    }

    bulkProcessPOs('deny', notes);
}

function bulkProcessPOs(action, notes) {
    const poIds = Array.from(selectedPOs);

    fetch('/bulk_process_pos', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            po_ids: poIds,
            action: action,
            notes: notes || ''
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert(`✓ Successfully ${action}d ${data.processed} PO(s)`);
            location.reload();
        } else {
            alert('Error: ' + data.error);
        }
    })
    .catch(error => {
        alert('Error processing POs: ' + error);
    });
}
function searchInTab(tabId, searchInputId) {
    const searchQuery = document.getElementById(searchInputId).value.toLowerCase().trim();
    const tabContent = document.getElementById(tabId);
    const requestItems = tabContent.querySelectorAll('.request-item');
    let visibleCount = 0;

    requestItems.forEach(item => {
        const itemText = item.textContent.toLowerCase();

        if (!searchQuery || itemText.includes(searchQuery)) {
            item.style.display = 'block';
            visibleCount++;
        } else {
            item.style.display = 'none';
        }
    });

    // Update result count
    const resultCount = tabContent.querySelector('.search-result-count');
    if (resultCount) {
        if (searchQuery) {
            resultCount.textContent = `Showing ${visibleCount} of ${requestItems.length} results`;
            resultCount.style.display = 'block';
        } else {
            resultCount.style.display = 'none';
        }
    }
}
    </script>
</head>
<body>
    <div class="header">
        <h1>🏢 Office Dashboard - {{ username }}</h1>
        <div>
            <a href="{{ url_for('manage_jobs') }}" style="background: #17a2b8; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; margin-right: 10px; font-size: 14px;">📋 Manage Jobs</a>
            <a href="{{ url_for('settings_page') }}" style="background: #6c757d; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; margin-right: 10px; font-size: 14px;">⚙️ Settings</a>
            <a href="{{ url_for('logout') }}" class="logout-btn">Logout</a>
        </div>
    </div>

    {% with messages = get_flashed_messages() %}
        {% if messages %}
            {% for message in messages %}
                {% if 'ERROR' in message or '❌' in message %}
                    <div class="error-message">{{ message }}</div>
                {% else %}
                    <div class="success">{{ message }}</div>
                {% endif %}
            {% endfor %}
        {% endif %}
    {% endwith %}

    <div class="search-card" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;">
        <h2 style="color: white; margin-bottom: 15px;">📦 Bulk Invoice Upload (Auto-Process)</h2>
        <p style="margin-bottom: 15px; opacity: 0.95;">Upload a multi-page PDF with multiple invoices. System will extract invoice numbers, costs, match to POs, and split the PDF automatically.</p>
        <form id="bulk-upload-form" style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
            <input type="file" id="bulk-pdf-input" accept=".pdf" style="flex: 1; min-width: 200px; padding: 12px; border: 2px solid white; border-radius: 5px; background: white; color: #333;">
            <button type="button" onclick="uploadBulkPDF()" id="bulk-upload-btn" style="background: #28a745; color: white; padding: 12px 30px; border: none; border-radius: 5px; font-size: 16px; cursor: pointer; font-weight: bold;">📤 Process PDF</button>
        </form>
        <div id="bulk-upload-status" style="margin-top: 15px; display: none;"></div>
    </div>

    <div class="stats">
        <div class="stat-card">
            <div class="stat-number">{{ stats.pending }}</div>
            <div class="stat-label">Pending Requests</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{{ stats.approved }}</div>
            <div class="stat-label">Approved</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{{ stats.denied }}</div>
            <div class="stat-label">Denied</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{{ stats.with_invoice }}</div>
            <div class="stat-label">With Invoices</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">${{ "%.2f"|format(stats.total_value) }}</div>
            <div class="stat-label">Total Pending Value</div>
        </div>
    </div>

    <div class="tabs">
        <button class="tab active" onclick="showTab('pending')">Pending ({{ stats.pending }})</button>
        <button class="tab" onclick="showTab('approved')">Approved ({{ stats.approved - stats.with_invoice }})</button>
        <button class="tab" onclick="showTab('with_invoice')">With Invoice ({{ stats.with_invoice }})</button>
        <button class="tab" onclick="showTab('denied')">Denied ({{ stats.denied }})</button>
    </div>

    <div id="pending" class="tab-content active">
    <div style="background: #f0f4ff; padding: 15px; border-radius: 5px; margin-bottom: 15px;">
        <input type="text"
               id="search-pending"
               placeholder="🔍 Search pending POs (PO#, tech, job, description, store)..."
               onkeyup="searchInTab('pending', 'search-pending')"
               style="width: 100%; padding: 10px; border: 2px solid #667eea; border-radius: 5px; font-size: 14px;">
        <div class="search-result-count" style="margin-top: 8px; color: #667eea; font-size: 13px; display: none;"></div>
    </div>

    {% if pending_requests %}
        <!-- Select All Checkbox -->
        <div class="select-all-container">
            <input type="checkbox" id="select-all-pending" onclick="selectAllPending()" style="width: 20px; height: 20px; cursor: pointer;">
            <label for="select-all-pending" style="cursor: pointer; font-weight: bold; margin: 0;">Select All Pending POs</label>
        </div>

        {% for req in pending_requests %}
            <div class="request-item">
                <input type="checkbox" class="po-checkbox" data-po-id="{{ req[0] }}"
                       onchange="togglePOSelection({{ req[0] }}, this)">
                <button onclick="deleteRequest({{ req[0] }})" class="delete-btn">🗑️ Delete</button>
                <h3>PO #{{ format_po_number(req[0], req[3]) }} - {{ req[3] }} - ${{ "%.2f"|format(req[5]) }}</h3>
                <p><strong>Technician:</strong> {{ req[2] }} ({{ req[1] }})</p>
                <p><strong>Job:</strong> {{ req[3] }}</p>
                <p><strong>Description:</strong> {{ req[6] }}</p>
                <p><strong>Requested:</strong> {{ req[8] }}</p>
                <form method="POST" action="{{ url_for('process_request', request_id=req[0]) }}" class="action-form">
                    <textarea name="notes" placeholder="Add notes (optional)..."></textarea>
                    <div class="action-buttons">
                        <button type="submit" name="action" value="approve" class="approve-btn">✓ Approve</button>
                        <button type="submit" name="action" value="deny" class="deny-btn">✗ Deny</button>
                    </div>
                </form>
            </div>
        {% endfor %}

        <!-- Floating Bulk Actions Panel -->
        <div id="bulk-actions">
            <h3>📋 <span id="selected-count">0</span> PO(s) Selected</h3>
            <button onclick="bulkApprove()" class="bulk-btn bulk-approve-btn">✓ Approve All</button>
            <button onclick="bulkDeny()" class="bulk-btn bulk-deny-btn">✗ Deny All</button>
            <button onclick="selectedPOs.clear(); updateBulkActionsButton(); document.querySelectorAll('.po-checkbox').forEach(cb => cb.checked = false); document.getElementById('select-all-pending').checked = false;"
                    class="bulk-btn bulk-cancel-btn">Cancel</button>
        </div>
    {% else %}
        <p style="color: #999; text-align: center; padding: 40px;">No pending requests</p>
    {% endif %}
</div>

    <div id="approved" class="tab-content">
        {% if approved_requests %}
            {% for req in approved_requests %}
                <div class="request-item" data-po-id="{{ req[0] }}">
                    <button onclick="deleteRequest({{ req[0] }})" class="delete-btn">🗑️ Delete</button>
                    <button onclick="deleteRequest({{ req[0] }})" class="delete-btn">🗑️ Delete</button>
                    <button onclick="undoApproval({{ req[0] }})" class="delete-btn" style="right: 120px; background: #ffc107;">↩️ Undo</button>
                    <span class="status approved">APPROVED</span>
                    <h3>PO #{{ format_po_number(req[0], req[3]) }} - {{ req[3] }} - ${{ "%.2f"|format(req[5]) }}</h3>
                    <p><strong>Technician:</strong> {{ req[2] }} ({{ req[1] }})</p>
                    <p><strong>Job:</strong> {{ req[3] }}</p>
                    <p><strong>Description:</strong> {{ req[6] }}</p>
                    <p><strong>Requested:</strong> {{ req[8] }}</p>
                    <p><strong>Approved:</strong> {{ req[9] }} by {{ req[approved_by_idx] if req|length > approved_by_idx else 'N/A' }}</p>
                    {% if req[10] %}
                        <p><strong>Notes:</strong> {{ req[10] }}</p>
                    {% endif %}
                    <div class="invoice-upload-section">
                        <h4>📄 Add Invoice Details</h4>
                        <form id="invoice-form-{{ req[0] }}" class="invoice-form">
                            <input type="text" name="invoice_number" placeholder="Invoice Number (Required)" required>
                            <input type="number" step="0.01" name="invoice_cost" placeholder="Total Cost (Required)" required>
                            <div id="dropzone-{{ req[0] }}" class="dropzone">
                                <p>📎 Optional: Drag & drop invoice file or click to browse</p>
                            </div>
                            <input type="file" id="file-{{ req[0] }}" name="invoice" accept=".pdf,.jpg,.jpeg,.png" style="display: none;">
                            <button type="button" onclick="uploadInvoice({{ req[0] }})" class="upload-invoice-btn">💾 Save Invoice Details</button>
                        </form>
                    </div>
                </div>
            {% endfor %}
        {% else %}
            <p style="color: #999; text-align: center; padding: 40px;">No approved requests waiting for invoices</p>
        {% endif %}
    </div>

<div id="with_invoice" class="tab-content">
    {% if invoiced_requests %}
        {% for req in invoiced_requests %}
            <div class="request-item" data-po-id="{{ req[0] }}">
                <button onclick="deleteRequest({{ req[0] }})" class="delete-btn">🗑️ Delete</button>
                <button onclick="deleteInvoice({{ req[0] }})" class="delete-btn" style="right: 120px; background: #ff9800;">🗑️ Remove Invoice</button>
                <span class="status approved">APPROVED WITH INVOICE</span>
                <h3>PO #{{ format_po_number(req[0], req[3]) }} - {{ req[3] }} - ${{ "%.2f"|format(req[5]) }}</h3>
                <p><strong>Technician:</strong> {{ req[2] }} ({{ req[1] }})</p>
                <p><strong>Job:</strong> {{ req[3] }}</p>
                <p><strong>Description:</strong> {{ req[6] }}</p>
                <p><strong>Requested:</strong> {{ req[8] }}</p>
                <p><strong>Approved:</strong> {{ req[9] }} by {{ req[approved_by_idx] if req|length > approved_by_idx else 'N/A' }}</p>
                {% if req[10] %}
                    <p><strong>Notes:</strong> {{ req[10] }}</p>
                {% endif %}
                <div class="invoice-data">
                    <h4>📄 Invoice Details</h4>
                    <p><strong>Invoice Number:</strong> {{ req[inv_number_idx] if req|length > inv_number_idx else 'Not entered' }}</p>

                    {# FIXED: Only show message if job is actually "Service" #}
                    {% if req[3] and req[3].lower() == 'service' %}
                        <p style="background: #fff3cd; padding: 8px; border-radius: 5px; margin: 10px 0;">
                            <strong>🔧 Auto-categorized as Service</strong> (PO number starts with "S")
                        </p>
                    {% endif %}

                    <p><strong>Total Cost:</strong> ${{ req[inv_cost_idx] if req|length > inv_cost_idx else '0.00' }}</p>
                    <p><strong>Entered:</strong> {{ req[inv_upload_idx] if req|length > inv_upload_idx else 'N/A' }}</p>
                    {% if req[inv_filename_idx] and req[inv_filename_idx] != 'MANUAL_ENTRY' %}
                        <p><strong>File:</strong> <a href="{{ url_for('view_invoice', filename=req[inv_filename_idx]) }}" target="_blank" style="color: #667eea; text-decoration: underline;">📄 View Invoice PDF</a></p>
                    {% else %}
                        <p><strong>File:</strong> <span style="color: #666;">No file attached (manual entry)</span></p>
                    {% endif %}
                </div>
                <div class="invoice-upload-section" style="margin-top: 15px;">
                    <h4>✏️ Edit Invoice Details</h4>
                    <form id="invoice-form-{{ req[0] }}" class="invoice-form">
                        <input type="text" name="invoice_number" placeholder="Invoice Number" value="{{ req[inv_number_idx] if req|length > inv_number_idx else '' }}" required>
                        <input type="number" step="0.01" name="invoice_cost" placeholder="Total Cost" value="{{ req[inv_cost_idx] if req|length > inv_cost_idx else '' }}" required>
                        <div id="dropzone-{{ req[0] }}" class="dropzone">
                            <p>📎 Replace invoice file (optional)</p>
                        </div>
                        <input type="file" id="file-{{ req[0] }}" name="invoice" accept=".pdf,.jpg,.jpeg,.png" style="display: none;">
                        <button type="button" onclick="uploadInvoice({{ req[0] }})" class="upload-invoice-btn">💾 Update Invoice Details</button>
                    </form>
                </div>
            </div>
        {% endfor %}
    {% else %}
        <p style="color: #999; text-align: center; padding: 40px;">No approved requests with invoices</p>
    {% endif %}
</div>

    <div id="denied" class="tab-content">
        {% if denied_requests %}
            {% for req in denied_requests %}
                <div class="request-item">
                    <button onclick="deleteRequest({{ req[0] }})" class="delete-btn">🗑️ Delete</button>
                    <span class="status denied">DENIED</span>
                    <h3>PO #{{ format_po_number(req[0], req[3]) }} - {{ req[3] }} - ${{ "%.2f"|format(req[5]) }}</h3>
                    <p><strong>Technician:</strong> {{ req[2] }} ({{ req[1] }})</p>
                    <p><strong>Job:</strong> {{ req[3] }}</p>
                    <p><strong>Description:</strong> {{ req[6] }}</p>
                    <p><strong>Requested:</strong> {{ req[8] }}</p>
                    <p><strong>Denied:</strong> {{ req[9] }} by {{ req[approved_by_idx] if req|length > approved_by_idx else 'N/A' }}</p>
                    {% if req[10] %}
                        <p><strong>Reason:</strong> {{ req[10] }}</p>
                    {% endif %}
                </div>
            {% endfor %}
        {% else %}
            <p style="color: #999; text-align: center; padding: 40px;">No denied requests</p>
        {% endif %}
    </div>
</body>
</html>
'''
REGISTER_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Register - Office Manager</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .container {
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            width: 100%;
            max-width: 450px;
        }
        h1 { color: #333; margin-bottom: 10px; font-size: 28px; }
        .subtitle { color: #666; margin-bottom: 30px; font-size: 14px; }
        .form-group { margin-bottom: 20px; }
        label { display: block; margin-bottom: 5px; color: #555; font-weight: bold; }
        input {
            width: 100%;
            padding: 12px;
            border: 2px solid #ddd;
            border-radius: 5px;
            font-size: 16px;
        }
        input:focus { outline: none; border-color: #667eea; }
        button {
            width: 100%;
            padding: 12px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 5px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
        }
        button:hover { background: #5568d3; }
        .error {
            background: #fee;
            color: #c33;
            padding: 10px;
            border-radius: 5px;
            margin-bottom: 20px;
        }
        .success {
            background: #efe;
            color: #3c3;
            padding: 10px;
            border-radius: 5px;
            margin-bottom: 20px;
        }
        .login-link {
            text-align: center;
            margin-top: 20px;
            color: #666;
        }
        .login-link a {
            color: #667eea;
            text-decoration: none;
            font-weight: bold;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🏢 Office Manager Registration</h1>
        <p class="subtitle">Create your account to manage PO requests</p>
        {% with messages = get_flashed_messages() %}
            {% if messages %}
                {% for message in messages %}
                    <div class="{% if 'success' in message.lower() %}success{% else %}error{% endif %}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        <form method="POST">
            <div class="form-group">
                <label>Full Name</label>
                <input type="text" name="full_name" required placeholder="e.g., Sarah Johnson">
            </div>
            <div class="form-group">
                <label>Email Address</label>
                <input type="email" name="email" required placeholder="your.email@company.com">
            </div>
            <div class="form-group">
                <label>Username</label>
                <input type="text" name="username" required placeholder="Choose a username">
            </div>
            <div class="form-group">
                <label>Password</label>
                <input type="password" name="password" required minlength="6" placeholder="At least 6 characters">
            </div>
            <div class="form-group">
                <label>Confirm Password</label>
                <input type="password" name="confirm_password" required placeholder="Re-enter password">
            </div>
            <button type="submit">Create Account</button>
        </form>
        <div class="login-link">
            Already have an account? <a href="{{ url_for('login') }}">Login here</a>
        </div>
    </div>
</body>
</html>
'''

ACTIVITY_LOG_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Activity Log</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px; }
        .header {
            background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1); display: flex;
            justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;
        }
        h1 { color: #333; font-size: 24px; }
        .btn {
            padding: 10px 20px; border-radius: 5px; text-decoration: none;
            font-weight: bold; font-size: 14px; border: none; cursor: pointer;
        }
        .btn-secondary { background: #6c757d; color: white; }
        .btn-danger { background: #dc3545; color: white; }
        .card {
            background: white; padding: 20px; border-radius: 10px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1); margin-bottom: 20px;
        }
        .filter-controls {
            background: #f0f4ff; padding: 15px; border-radius: 5px;
            margin-bottom: 20px; display: flex; gap: 10px; flex-wrap: wrap;
        }
        .filter-controls input, .filter-controls select {
            padding: 8px; border: 2px solid #667eea; border-radius: 5px;
            font-size: 14px;
        }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background: #667eea; color: white; font-weight: bold; }
        tr:hover { background: #f5f5f5; }
        .action-badge {
            padding: 5px 10px; border-radius: 20px; font-size: 12px;
            font-weight: bold; display: inline-block;
        }
        .action-approved { background: #28a745; color: white; }
        .action-denied { background: #dc3545; color: white; }
        .action-login { background: #17a2b8; color: white; }
        .action-registered { background: #667eea; color: white; }
        .action-bulk { background: #ffc107; color: #000; }
    </style>
</head>
<body>
    <div class="header">
        <h1>📋 Activity Log</h1>
        <div>
            <a href="{{ url_for('office_dashboard') }}" class="btn btn-secondary">← Back to Dashboard</a>
            <a href="{{ url_for('logout') }}" class="btn btn-danger">Logout</a>
        </div>
    </div>

    <div class="card">
        <h2 style="color: #667eea; margin-bottom: 15px;">Filter Activity</h2>
        <form method="GET" class="filter-controls">
            <input type="text" name="filter_user" placeholder="Filter by user..." value="{{ filter_user }}">
            <select name="filter_action">
                <option value="">All Actions</option>
                {% for action in actions %}
                    <option value="{{ action }}" {% if action == filter_action %}selected{% endif %}>{{ action }}</option>
                {% endfor %}
            </select>
            <button type="submit" class="btn btn-secondary">Apply Filters</button>
            <a href="{{ url_for('activity_log') }}" class="btn btn-secondary">Clear</a>
        </form>
    </div>

    <div class="card">
        <h2 style="color: #667eea; margin-bottom: 20px;">Recent Activity (Last 500 entries)</h2>
        <table>
            <thead>
                <tr>
                    <th>Timestamp</th>
                    <th>User</th>
                    <th>Email</th>
                    <th>Action</th>
                    <th>Details</th>
                </tr>
            </thead>
            <tbody>
                {% for log in logs %}
                <tr>
                    <td>{{ log[7] }}</td>
                    <td><strong>{{ log[1] }}</strong></td>
                    <td>{{ log[2] }}</td>
                    <td>
                        <span class="action-badge action-{{ log[3].lower().replace('_', '-') }}">
                            {{ log[3] }}
                        </span>
                    </td>
                    <td>{{ log[6] }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</body>
</html>
'''
FORGOT_PASSWORD_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Forgot Password</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .container {
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            width: 100%;
            max-width: 450px;
        }
        h1 { color: #333; margin-bottom: 10px; font-size: 28px; }
        .subtitle { color: #666; margin-bottom: 30px; font-size: 14px; }
        .form-group { margin-bottom: 20px; }
        label { display: block; margin-bottom: 5px; color: #555; font-weight: bold; }
        input {
            width: 100%;
            padding: 12px;
            border: 2px solid #ddd;
            border-radius: 5px;
            font-size: 16px;
        }
        input:focus { outline: none; border-color: #667eea; }
        button {
            width: 100%;
            padding: 12px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 5px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
        }
        button:hover { background: #5568d3; }
        .success {
            background: #d4edda;
            color: #155724;
            padding: 12px;
            border-radius: 5px;
            margin-bottom: 20px;
            border: 1px solid #c3e6cb;
        }
        .error {
            background: #f8d7da;
            color: #721c24;
            padding: 12px;
            border-radius: 5px;
            margin-bottom: 20px;
            border: 1px solid #f5c6cb;
        }
        .back-link {
            text-align: center;
            margin-top: 20px;
            color: #666;
        }
        .back-link a {
            color: #667eea;
            text-decoration: none;
            font-weight: bold;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔐 Forgot Password</h1>
        <p class="subtitle">Enter your email to receive a password reset link</p>
        {% with messages = get_flashed_messages() %}
            {% if messages %}
                {% for message in messages %}
                    <div class="{% if '✓' in message %}success{% else %}error{% endif %}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        <form method="POST">
            <div class="form-group">
                <label>Email Address</label>
                <input type="email" name="email" required placeholder="your.email@company.com" autofocus>
            </div>
            <button type="submit">Send Reset Link</button>
        </form>
        <div class="back-link">
            <a href="{{ url_for('login') }}">← Back to Login</a>
        </div>
    </div>
</body>
</html>
'''

RESET_PASSWORD_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Reset Password</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .container {
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            width: 100%;
            max-width: 450px;
        }
        h1 { color: #333; margin-bottom: 10px; font-size: 28px; }
        .subtitle { color: #666; margin-bottom: 30px; font-size: 14px; }
        .form-group { margin-bottom: 20px; }
        label { display: block; margin-bottom: 5px; color: #555; font-weight: bold; }
        input {
            width: 100%;
            padding: 12px;
            border: 2px solid #ddd;
            border-radius: 5px;
            font-size: 16px;
        }
        input:focus { outline: none; border-color: #667eea; }
        button {
            width: 100%;
            padding: 12px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 5px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
        }
        button:hover { background: #5568d3; }
        .error {
            background: #f8d7da;
            color: #721c24;
            padding: 12px;
            border-radius: 5px;
            margin-bottom: 20px;
            border: 1px solid #f5c6cb;
        }
        .email-display {
            background: #e7f3ff;
            padding: 10px;
            border-radius: 5px;
            margin-bottom: 20px;
            color: #0066cc;
            text-align: center;
            font-weight: bold;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔑 Reset Your Password</h1>
        <p class="subtitle">Enter your new password below</p>
        <div class="email-display">{{ email }}</div>
        {% with messages = get_flashed_messages() %}
            {% if messages %}
                {% for message in messages %}
                    <div class="error">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        <form method="POST">
            <div class="form-group">
                <label>New Password</label>
                <input type="password" name="password" required minlength="6" placeholder="At least 6 characters" autofocus>
            </div>
            <div class="form-group">
                <label>Confirm New Password</label>
                <input type="password" name="confirm_password" required minlength="6" placeholder="Re-enter password">
            </div>
            <button type="submit">Reset Password</button>
        </form>
    </div>
</body>
</html>
'''


# ============================================================================
# TEMPLATES - Add these at the end of your file with your other templates
# ============================================================================

ADMIN_USERS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>User Management - Admin</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .header {
            background: white;
            padding: 20px 30px;
            border-radius: 10px;
            margin-bottom: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 15px;
        }
        h1 {
            color: #333;
            font-size: 28px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .header-buttons {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        .btn {
            padding: 10px 20px;
            border-radius: 5px;
            text-decoration: none;
            font-weight: bold;
            cursor: pointer;
            border: none;
            font-size: 14px;
            transition: all 0.3s;
        }
        .btn-primary {
            background: #667eea;
            color: white;
        }
        .btn-primary:hover { background: #5568d3; }
        .btn-secondary {
            background: #6c757d;
            color: white;
        }
        .btn-secondary:hover { background: #5a6268; }
        .btn-danger {
            background: #dc3545;
            color: white;
        }
        .btn-danger:hover { background: #c82333; }
        .btn-success {
            background: #28a745;
            color: white;
        }
        .btn-success:hover { background: #218838; }
        .container {
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 20px rgba(0,0,0,0.1);
            max-width: 1200px;
            margin: 0 auto;
        }
        .success, .error {
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }
        .success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        .error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }
        th {
            background: #667eea;
            color: white;
            padding: 15px;
            text-align: left;
            font-weight: bold;
        }
        td {
            padding: 15px;
            border-bottom: 1px solid #ddd;
        }
        tr:hover { background: #f8f9fa; }
        .role-badge {
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: bold;
            display: inline-block;
        }
        .role-admin { background: #dc3545; color: white; }
        .role-office { background: #28a745; color: white; }
        .role-technician { background: #007bff; color: white; }
        .action-buttons {
            display: flex;
            gap: 10px;
        }
        .user-count {
            background: #e7f3ff;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
            color: #0066cc;
            font-weight: bold;
        }
        .delete-form {
            display: inline;
        }
        @media (max-width: 768px) {
            table { font-size: 14px; }
            th, td { padding: 10px; }
            .action-buttons { flex-direction: column; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>👥 User Management</h1>
        <div class="header-buttons">
            <a href="{{ url_for('admin_create_user') }}" class="btn btn-success">+ Create New User</a>
            <a href="{{ url_for('admin_dashboard') }}" class="btn btn-secondary">← Back to Dashboard</a>
        </div>
    </div>

    <div class="container">
        {% with messages = get_flashed_messages() %}
            {% if messages %}
                {% for message in messages %}
                    <div class="{% if '✓' in message %}success{% else %}error{% endif %}">
                        {{ message }}
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        <div class="user-count">
            📊 Total Users: {{ users|length }}
        </div>

        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Username</th>
                    <th>Full Name</th>
                    <th>Email</th>
                    <th>Role</th>
                    <th>Created</th>
                    <th>Last Login</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for user in users %}
                <tr>
                    <td><strong>#{{ user[0] }}</strong></td>
                    <td>{{ user[1] }}</td>
                    <td>{{ user[4] or 'N/A' }}</td>
                    <td>{{ user[3] or 'N/A' }}</td>
                    <td>
                        <span class="role-badge role-{{ user[2] }}">
                            {{ user[2].upper() }}
                        </span>
                    </td>
                    <td>{{ user[5] }}</td>
                    <td>{{ user[6] or 'Never' }}</td>
                    <td>
                        <div class="action-buttons">
                            <a href="{{ url_for('admin_edit_user', user_id=user[0]) }}"
                               class="btn btn-primary">✏️ Edit</a>
                            {% if user[1] != session['username'] %}
                            <form method="POST" action="{{ url_for('admin_delete_user', user_id=user[0]) }}"
                                  class="delete-form"
                                  onsubmit="return confirm('Are you sure you want to delete user {{ user[1] }}?');">
                                <button type="submit" class="btn btn-danger">🗑️ Delete</button>
                            </form>
                            {% endif %}
                        </div>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</body>
</html>
'''

ADMIN_EDIT_USER_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Edit User - Admin</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .container {
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            width: 100%;
            max-width: 500px;
        }
        h1 {
            color: #333;
            margin-bottom: 10px;
            font-size: 28px;
        }
        .subtitle {
            color: #666;
            margin-bottom: 30px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 5px;
            color: #555;
            font-weight: bold;
        }
        input, select {
            width: 100%;
            padding: 12px;
            border: 2px solid #ddd;
            border-radius: 5px;
            font-size: 16px;
        }
        input:focus, select:focus {
            outline: none;
            border-color: #667eea;
        }
        .btn {
            padding: 12px 24px;
            border-radius: 5px;
            font-weight: bold;
            cursor: pointer;
            border: none;
            font-size: 16px;
            text-decoration: none;
            display: inline-block;
            transition: all 0.3s;
        }
        .btn-primary {
            background: #667eea;
            color: white;
            width: 100%;
        }
        .btn-primary:hover { background: #5568d3; }
        .btn-secondary {
            background: #6c757d;
            color: white;
            margin-top: 10px;
            text-align: center;
            width: 100%;
        }
        .btn-secondary:hover { background: #5a6268; }
        .error {
            background: #f8d7da;
            color: #721c24;
            padding: 12px;
            border-radius: 5px;
            margin-bottom: 20px;
            border: 1px solid #f5c6cb;
        }
        .note {
            background: #fff3cd;
            color: #856404;
            padding: 10px;
            border-radius: 5px;
            font-size: 14px;
            margin-top: 5px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>✏️ Edit User</h1>
        <p class="subtitle">Update user information</p>

        {% with messages = get_flashed_messages() %}
            {% if messages %}
                {% for message in messages %}
                    <div class="error">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        <form method="POST">
            <div class="form-group">
                <label>Username</label>
                <input type="text" name="username" value="{{ user[1] }}" required>
            </div>

            <div class="form-group">
                <label>Password</label>
                <input type="password" name="password" placeholder="Leave blank to keep current">
                <div class="note">⚠️ Only enter a password if you want to change it</div>
            </div>

            <div class="form-group">
                <label>Role</label>
                <select name="role" required>
                    <option value="admin" {% if user[2] == 'admin' %}selected{% endif %}>Admin</option>
                    <option value="office" {% if user[2] == 'office' %}selected{% endif %}>Office Staff</option>
                    <option value="technician" {% if user[2] == 'technician' %}selected{% endif %}>Technician</option>
                </select>
            </div>

            <div class="form-group">
                <label>Email</label>
                <input type="email" name="email" value="{{ user[3] or '' }}">
            </div>

            <div class="form-group">
                <label>Full Name</label>
                <input type="text" name="full_name" value="{{ user[4] or '' }}" required>
            </div>

            <button type="submit" class="btn btn-primary">💾 Save Changes</button>
            <a href="{{ url_for('admin_users') }}" class="btn btn-secondary">Cancel</a>
        </form>
    </div>
</body>
</html>
'''

ADMIN_CREATE_USER_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Create User - Admin</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .container {
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            width: 100%;
            max-width: 500px;
        }
        h1 {
            color: #333;
            margin-bottom: 10px;
            font-size: 28px;
        }
        .subtitle {
            color: #666;
            margin-bottom: 30px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 5px;
            color: #555;
            font-weight: bold;
        }
        input, select {
            width: 100%;
            padding: 12px;
            border: 2px solid #ddd;
            border-radius: 5px;
            font-size: 16px;
        }
        input:focus, select:focus {
            outline: none;
            border-color: #667eea;
        }
        .btn {
            padding: 12px 24px;
            border-radius: 5px;
            font-weight: bold;
            cursor: pointer;
            border: none;
            font-size: 16px;
            text-decoration: none;
            display: inline-block;
            transition: all 0.3s;
        }
        .btn-success {
            background: #28a745;
            color: white;
            width: 100%;
        }
        .btn-success:hover { background: #218838; }
        .btn-secondary {
            background: #6c757d;
            color: white;
            margin-top: 10px;
            text-align: center;
            width: 100%;
        }
        .btn-secondary:hover { background: #5a6268; }
        .error {
            background: #f8d7da;
            color: #721c24;
            padding: 12px;
            border-radius: 5px;
            margin-bottom: 20px;
            border: 1px solid #f5c6cb;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>➕ Create New User</h1>
        <p class="subtitle">Add a new user to the system</p>

        {% with messages = get_flashed_messages() %}
            {% if messages %}
                {% for message in messages %}
                    <div class="error">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        <form method="POST">
            <div class="form-group">
                <label>Username *</label>
                <input type="text" name="username" required autofocus>
            </div>

            <div class="form-group">
                <label>Password *</label>
                <input type="password" name="password" required minlength="6">
            </div>

            <div class="form-group">
                <label>Role *</label>
                <select name="role" required>
                    <option value="technician">Technician</option>
                    <option value="office">Office Staff</option>
                    <option value="admin">Admin</option>
                </select>
            </div>

            <div class="form-group">
                <label>Email</label>
                <input type="email" name="email">
            </div>

            <div class="form-group">
                <label>Full Name *</label>
                <input type="text" name="full_name" required>
            </div>

            <button type="submit" class="btn btn-success">✓ Create User</button>
            <a href="{{ url_for('admin_users') }}" class="btn btn-secondary">Cancel</a>
        </form>
    </div>
</body>
</html>
'''
# ============================================================================
# ADD THESE ROUTES AFTER YOUR office_dashboard ROUTE (around line 688)
# ============================================================================

@app.route('/admin_dashboard')
def admin_dashboard():
    """Admin dashboard - Shows all system stats and admin tools"""
    if 'username' not in session or session['role'] != 'admin':
        flash('⛔ Admin access required')
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Get system statistics
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM users WHERE role='technician'")
    tech_count = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM users WHERE role='office'")
    office_count = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM users WHERE role='admin'")
    admin_count = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM po_requests")
    total_pos = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM po_requests WHERE status='pending'")
    pending_pos = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM po_requests WHERE status='approved'")
    approved_pos = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM jobs WHERE active=1")
    active_jobs = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM activity_log")
    total_logs = c.fetchone()[0]

    # Recent activity
    c.execute("""SELECT username, action, target_type, details, timestamp
                 FROM activity_log
                 ORDER BY id DESC LIMIT 10""")
    recent_activity = c.fetchall()

    conn.close()

    stats = {
        'total_users': total_users,
        'tech_count': tech_count,
        'office_count': office_count,
        'admin_count': admin_count,
        'total_pos': total_pos,
        'pending_pos': pending_pos,
        'approved_pos': approved_pos,
        'active_jobs': active_jobs,
        'total_logs': total_logs
    }

    return render_template_string(ADMIN_DASHBOARD_TEMPLATE,
                                stats=stats,
                                recent_activity=recent_activity)

@app.route('/admin/users')
def admin_users():
    """Admin page to view all users"""
    if 'username' not in session or session.get('role') != 'admin':
        flash('⛔ Admin access required')
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Get all users with their details
    c.execute("""SELECT id, username, role, email, full_name, created_date, last_login
                 FROM users ORDER BY created_date DESC""")
    users = c.fetchall()
    conn.close()

    return render_template_string(ADMIN_USERS_TEMPLATE, users=users)

@app.route('/admin/users/edit/<int:user_id>', methods=['GET', 'POST'])
def admin_edit_user(user_id):
    """Edit user details"""
    if 'username' not in session or session.get('role') != 'admin':
        flash('⛔ Admin access required')
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        role = request.form['role']
        email = request.form['email'].strip()
        full_name = request.form['full_name'].strip()

        try:
            # Update user (only update password if provided)
            if password:
                c.execute("""UPDATE users
                           SET username=?, password=?, role=?, email=?, full_name=?
                           WHERE id=?""",
                         (username, password, role, email, full_name, user_id))
            else:
                c.execute("""UPDATE users
                           SET username=?, role=?, email=?, full_name=?
                           WHERE id=?""",
                         (username, role, email, full_name, user_id))

            conn.commit()
            log_activity(session['username'], 'user_updated', 'user', user_id,
                        f'Updated user: {username}')
            flash(f'✓ User {username} updated successfully!')
            conn.close()
            return redirect(url_for('admin_users'))
        except sqlite3.IntegrityError:
            flash('✗ Username already exists')
            conn.close()
            return redirect(url_for('admin_edit_user', user_id=user_id))

    # GET request - show edit form
    c.execute("SELECT id, username, role, email, full_name FROM users WHERE id=?", (user_id,))
    user = c.fetchone()
    conn.close()

    if not user:
        flash('✗ User not found')
        return redirect(url_for('admin_users'))

    return render_template_string(ADMIN_EDIT_USER_TEMPLATE, user=user)

@app.route('/admin/users/delete/<int:user_id>', methods=['POST'])
def admin_delete_user(user_id):
    """Delete a user"""
    if 'username' not in session or session.get('role') != 'admin':
        flash('⛔ Admin access required')
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Get user info before deleting
    c.execute("SELECT username FROM users WHERE id=?", (user_id,))
    user = c.fetchone()

    if user:
        username = user[0]

        # Prevent deleting yourself
        if username == session['username']:
            flash('⚠ You cannot delete your own account!')
            conn.close()
            return redirect(url_for('admin_users'))

        c.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
        log_activity(session['username'], 'user_deleted', 'user', user_id,
                    f'Deleted user: {username}')
        flash(f'✓ User {username} deleted successfully!')
    else:
        flash('✗ User not found')

    conn.close()
    return redirect(url_for('admin_users'))

@app.route('/admin/users/create', methods=['GET', 'POST'])
def admin_create_user():
    """Create a new user"""
    if 'username' not in session or session.get('role') != 'admin':
        flash('⛔ Admin access required')
        return redirect(url_for('login'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        role = request.form['role']
        email = request.form['email'].strip()
        full_name = request.form['full_name'].strip()

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        try:
            c.execute("""INSERT INTO users (username, password, role, email, full_name, created_date)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                     (username, password, role, email, full_name,
                      datetime.now().strftime('%Y-%m-%d')))
            conn.commit()
            user_id = c.lastrowid
            log_activity(session['username'], 'user_created', 'user', user_id,
                        f'Created user: {username}')
            flash(f'✓ User {username} created successfully!')
            conn.close()
            return redirect(url_for('admin_users'))
        except sqlite3.IntegrityError:
            flash('✗ Username already exists')
            conn.close()

    return render_template_string(ADMIN_CREATE_USER_TEMPLATE)


# ============================================================================
# ADD THESE TEMPLATES AT THE END OF YOUR FILE (before if __name__ == '__main__':)
# ============================================================================

ADMIN_DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Admin Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .header {
            background: white;
            padding: 20px 30px;
            border-radius: 10px;
            margin-bottom: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
        }
        h1 {
            color: #333;
            font-size: 28px;
        }
        .user-info {
            color: #666;
            font-size: 14px;
        }
        .logout-btn {
            background: #dc3545;
            color: white;
            padding: 10px 20px;
            border-radius: 5px;
            text-decoration: none;
            font-weight: bold;
        }
        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: white;
            padding: 25px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            text-align: center;
        }
        .stat-icon {
            font-size: 48px;
            margin-bottom: 10px;
        }
        .stat-value {
            font-size: 36px;
            font-weight: bold;
            color: #667eea;
            margin-bottom: 5px;
        }
        .stat-label {
            color: #666;
            font-size: 14px;
        }
        .action-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .action-card {
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            text-align: center;
            text-decoration: none;
            color: #333;
            transition: transform 0.3s, box-shadow 0.3s;
        }
        .action-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 5px 20px rgba(0,0,0,0.2);
        }
        .action-icon {
            font-size: 64px;
            margin-bottom: 15px;
        }
        .action-card h3 {
            color: #667eea;
            margin-bottom: 10px;
        }
        .recent-activity {
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .activity-item {
            padding: 15px;
            border-bottom: 1px solid #eee;
        }
        .activity-item:last-child {
            border-bottom: none;
        }
        .activity-time {
            color: #999;
            font-size: 12px;
        }
        .activity-action {
            font-weight: bold;
            color: #667eea;
        }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>🔐 Admin Dashboard</h1>
            <div class="user-info">Logged in as: <strong>{{ session['username'] }}</strong></div>
        </div>
        <a href="{{ url_for('logout') }}" class="logout-btn">Logout</a>
    </div>

    <div class="dashboard-grid">
        <div class="stat-card">
            <div class="stat-icon">👥</div>
            <div class="stat-value">{{ stats['total_users'] }}</div>
            <div class="stat-label">Total Users</div>
        </div>
        <div class="stat-card">
            <div class="stat-icon">📋</div>
            <div class="stat-value">{{ stats['total_pos'] }}</div>
            <div class="stat-label">Total PO Requests</div>
        </div>
        <div class="stat-card">
            <div class="stat-icon">⏳</div>
            <div class="stat-value">{{ stats['pending_pos'] }}</div>
            <div class="stat-label">Pending POs</div>
        </div>
        <div class="stat-card">
            <div class="stat-icon">💼</div>
            <div class="stat-value">{{ stats['active_jobs'] }}</div>
            <div class="stat-label">Active Jobs</div>
        </div>
    </div>

    <div class="action-grid">
        <a href="{{ url_for('admin_users') }}" class="action-card">
            <div class="action-icon">👥</div>
            <h3>User Management</h3>
            <p>View, edit, create, and delete user accounts</p>
            <p style="margin-top:10px; color:#999;">{{ stats['tech_count'] }} Techs | {{ stats['office_count'] }} Office | {{ stats['admin_count'] }} Admins</p>
        </a>

        <a href="{{ url_for('office_dashboard') }}" class="action-card">
            <div class="action-icon">📋</div>
            <h3>PO Requests</h3>
            <p>View and manage all purchase orders</p>
            <p style="margin-top:10px; color:#999;">{{ stats['approved_pos'] }} Approved</p>
        </a>

        <a href="{{ url_for('activity_log') }}" class="action-card">
            <div class="action-icon">📊</div>
            <h3>Activity Log</h3>
            <p>View system activity and audit trail</p>
            <p style="margin-top:10px; color:#999;">{{ stats['total_logs'] }} Log Entries</p>
        </a>
    </div>

    <div class="recent-activity">
        <h2 style="margin-bottom: 20px; color: #333;">📈 Recent Activity</h2>
        {% for activity in recent_activity %}
        <div class="activity-item">
            <div class="activity-action">{{ activity[1] }}</div>
            <div>{{ activity[0] }} - {{ activity[3] }}</div>
            <div class="activity-time">{{ activity[4] }}</div>
        </div>
        {% endfor %}
    </div>
</body>
</html>
'''

ADMIN_USERS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>User Management - Admin</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .header {
            background: white;
            padding: 20px 30px;
            border-radius: 10px;
            margin-bottom: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 15px;
        }
        h1 {
            color: #333;
            font-size: 28px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .header-buttons {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        .btn {
            padding: 10px 20px;
            border-radius: 5px;
            text-decoration: none;
            font-weight: bold;
            cursor: pointer;
            border: none;
            font-size: 14px;
            transition: all 0.3s;
        }
        .btn-primary {
            background: #667eea;
            color: white;
        }
        .btn-primary:hover { background: #5568d3; }
        .btn-secondary {
            background: #6c757d;
            color: white;
        }
        .btn-secondary:hover { background: #5a6268; }
        .btn-danger {
            background: #dc3545;
            color: white;
        }
        .btn-danger:hover { background: #c82333; }
        .btn-success {
            background: #28a745;
            color: white;
        }
        .btn-success:hover { background: #218838; }
        .container {
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 20px rgba(0,0,0,0.1);
            max-width: 1200px;
            margin: 0 auto;
        }
        .success, .error {
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }
        .success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        .error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }
        th {
            background: #667eea;
            color: white;
            padding: 15px;
            text-align: left;
            font-weight: bold;
        }
        td {
            padding: 15px;
            border-bottom: 1px solid #ddd;
        }
        tr:hover { background: #f8f9fa; }
        .role-badge {
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: bold;
            display: inline-block;
        }
        .role-admin { background: #dc3545; color: white; }
        .role-office { background: #28a745; color: white; }
        .role-technician { background: #007bff; color: white; }
        .action-buttons {
            display: flex;
            gap: 10px;
        }
        .user-count {
            background: #e7f3ff;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
            color: #0066cc;
            font-weight: bold;
        }
        .delete-form {
            display: inline;
        }
        @media (max-width: 768px) {
            table { font-size: 14px; }
            th, td { padding: 10px; }
            .action-buttons { flex-direction: column; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>👥 User Management</h1>
        <div class="header-buttons">
            <a href="{{ url_for('admin_create_user') }}" class="btn btn-success">+ Create New User</a>
            <a href="{{ url_for('admin_dashboard') }}" class="btn btn-secondary">← Back to Dashboard</a>
        </div>
    </div>

    <div class="container">
        {% with messages = get_flashed_messages() %}
            {% if messages %}
                {% for message in messages %}
                    <div class="{% if '✓' in message %}success{% else %}error{% endif %}">
                        {{ message }}
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        <div class="user-count">
            📊 Total Users: {{ users|length }}
        </div>

        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Username</th>
                    <th>Full Name</th>
                    <th>Email</th>
                    <th>Role</th>
                    <th>Created</th>
                    <th>Last Login</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for user in users %}
                <tr>
                    <td><strong>#{{ user[0] }}</strong></td>
                    <td>{{ user[1] }}</td>
                    <td>{{ user[4] or 'N/A' }}</td>
                    <td>{{ user[3] or 'N/A' }}</td>
                    <td>
                        <span class="role-badge role-{{ user[2] }}">
                            {{ user[2].upper() }}
                        </span>
                    </td>
                    <td>{{ user[5] }}</td>
                    <td>{{ user[6] or 'Never' }}</td>
                    <td>
                        <div class="action-buttons">
                            <a href="{{ url_for('admin_edit_user', user_id=user[0]) }}"
                               class="btn btn-primary">✏️ Edit</a>
                            {% if user[1] != session['username'] %}
                            <form method="POST" action="{{ url_for('admin_delete_user', user_id=user[0]) }}"
                                  class="delete-form"
                                  onsubmit="return confirm('Are you sure you want to delete user {{ user[1] }}?');">
                                <button type="submit" class="btn btn-danger">🗑️ Delete</button>
                            </form>
                            {% endif %}
                        </div>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</body>
</html>
'''

ADMIN_EDIT_USER_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Edit User - Admin</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .container {
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            width: 100%;
            max-width: 500px;
        }
        h1 {
            color: #333;
            margin-bottom: 10px;
            font-size: 28px;
        }
        .subtitle {
            color: #666;
            margin-bottom: 30px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 5px;
            color: #555;
            font-weight: bold;
        }
        input, select {
            width: 100%;
            padding: 12px;
            border: 2px solid #ddd;
            border-radius: 5px;
            font-size: 16px;
        }
        input:focus, select:focus {
            outline: none;
            border-color: #667eea;
        }
        .btn {
            padding: 12px 24px;
            border-radius: 5px;
            font-weight: bold;
            cursor: pointer;
            border: none;
            font-size: 16px;
            text-decoration: none;
            display: inline-block;
            transition: all 0.3s;
        }
        .btn-primary {
            background: #667eea;
            color: white;
            width: 100%;
        }
        .btn-primary:hover { background: #5568d3; }
        .btn-secondary {
            background: #6c757d;
            color: white;
            margin-top: 10px;
            text-align: center;
            width: 100%;
        }
        .btn-secondary:hover { background: #5a6268; }
        .error {
            background: #f8d7da;
            color: #721c24;
            padding: 12px;
            border-radius: 5px;
            margin-bottom: 20px;
            border: 1px solid #f5c6cb;
        }
        .note {
            background: #fff3cd;
            color: #856404;
            padding: 10px;
            border-radius: 5px;
            font-size: 14px;
            margin-top: 5px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>✏️ Edit User</h1>
        <p class="subtitle">Update user information</p>

        {% with messages = get_flashed_messages() %}
            {% if messages %}
                {% for message in messages %}
                    <div class="error">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        <form method="POST">
            <div class="form-group">
                <label>Username</label>
                <input type="text" name="username" value="{{ user[1] }}" required>
            </div>

            <div class="form-group">
                <label>Password</label>
                <input type="password" name="password" placeholder="Leave blank to keep current">
                <div class="note">⚠️ Only enter a password if you want to change it</div>
            </div>

            <div class="form-group">
                <label>Role</label>
                <select name="role" required>
                    <option value="admin" {% if user[2] == 'admin' %}selected{% endif %}>Admin</option>
                    <option value="office" {% if user[2] == 'office' %}selected{% endif %}>Office Staff</option>
                    <option value="technician" {% if user[2] == 'technician' %}selected{% endif %}>Technician</option>
                </select>
            </div>

            <div class="form-group">
                <label>Email</label>
                <input type="email" name="email" value="{{ user[3] or '' }}">
            </div>

            <div class="form-group">
                <label>Full Name</label>
                <input type="text" name="full_name" value="{{ user[4] or '' }}" required>
            </div>

            <button type="submit" class="btn btn-primary">💾 Save Changes</button>
            <a href="{{ url_for('admin_users') }}" class="btn btn-secondary">Cancel</a>
        </form>
    </div>
</body>
</html>
'''

ADMIN_CREATE_USER_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Create User - Admin</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .container {
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            width: 100%;
            max-width: 500px;
        }
        h1 {
            color: #333;
            margin-bottom: 10px;
            font-size: 28px;
        }
        .subtitle {
            color: #666;
            margin-bottom: 30px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 5px;
            color: #555;
            font-weight: bold;
        }
        input, select {
            width: 100%;
            padding: 12px;
            border: 2px solid #ddd;
            border-radius: 5px;
            font-size: 16px;
        }
        input:focus, select:focus {
            outline: none;
            border-color: #667eea;
        }
        .btn {
            padding: 12px 24px;
            border-radius: 5px;
            font-weight: bold;
            cursor: pointer;
            border: none;
            font-size: 16px;
            text-decoration: none;
            display: inline-block;
            transition: all 0.3s;
        }
        .btn-success {
            background: #28a745;
            color: white;
            width: 100%;
        }
        .btn-success:hover { background: #218838; }
        .btn-secondary {
            background: #6c757d;
            color: white;
            margin-top: 10px;
            text-align: center;
            width: 100%;
        }
        .btn-secondary:hover { background: #5a6268; }
        .error {
            background: #f8d7da;
            color: #721c24;
            padding: 12px;
            border-radius: 5px;
            margin-bottom: 20px;
            border: 1px solid #f5c6cb;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>➕ Create New User</h1>
        <p class="subtitle">Add a new user to the system</p>

        {% with messages = get_flashed_messages() %}
            {% if messages %}
                {% for message in messages %}
                    <div class="error">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        <form method="POST">
            <div class="form-group">
                <label>Username *</label>
                <input type="text" name="username" required autofocus>
            </div>

            <div class="form-group">
                <label>Password *</label>
                <input type="password" name="password" required minlength="6">
            </div>

            <div class="form-group">
                <label>Role *</label>
                <select name="role" required>
                    <option value="technician">Technician</option>
                    <option value="office">Office Staff</option>
                    <option value="admin">Admin</option>
                </select>
            </div>

            <div class="form-group">
                <label>Email</label>
                <input type="email" name="email">
            </div>

            <div class="form-group">
                <label>Full Name *</label>
                <input type="text" name="full_name" required>
            </div>

            <button type="submit" class="btn btn-success">✓ Create User</button>
            <a href="{{ url_for('admin_users') }}" class="btn btn-secondary">Cancel</a>
        </form>
    </div>
</body>
</html>
'''

@app.route('/debug_check_po')
def debug_check_po():
    """Debug: Check if PO 9864 exists and is approved"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Check PO 9864
    c.execute("SELECT id, tech_name, job_name, status, estimated_cost FROM po_requests WHERE id=9864")
    po = c.fetchone()

    # Get all approved POs
    c.execute("SELECT id, job_name, status FROM po_requests WHERE status='approved' ORDER BY id")
    all_approved = c.fetchall()

    conn.close()

    html = "<h2>🔍 Debug: PO 9864 Status</h2>"

    if po:
        html += f"<div style='background: #d4edda; padding: 20px; border-radius: 5px;'>"
        html += f"<h3>✅ PO 9864 Found!</h3>"
        html += f"<p><strong>ID:</strong> {po[0]}</p>"
        html += f"<p><strong>Tech:</strong> {po[1]}</p>"
        html += f"<p><strong>Job:</strong> {po[2]}</p>"
        html += f"<p><strong>Status:</strong> {po[3]}</p>"
        html += f"<p><strong>Estimated Cost:</strong> ${po[4]:.2f}</p>"
        html += f"</div>"
    else:
        html += f"<div style='background: #f8d7da; padding: 20px; border-radius: 5px;'>"
        html += f"<h3>❌ PO 9864 NOT FOUND!</h3>"
        html += f"<p>This PO does not exist in the database.</p>"
        html += f"</div>"

    html += "<br><h3>All Approved POs:</h3><ul>"
    for approved_po in all_approved:
        html += f"<li>PO #{approved_po[0]:04d} - {approved_po[1]} - Status: {approved_po[2]}</li>"
    html += "</ul>"

    return html

@app.route('/debug_pdf_text')
def debug_pdf_text():
    """Debug: Show what text is extracted from the uploaded PDF"""
    try:
        import pdfplumber

        # Point to your uploaded PDF
        pdf_path = '/home/simonweardon3/bulk_uploads'

        # Find the most recent PDF
        import glob
        pdf_files = glob.glob(f"{pdf_path}/*.pdf")
        if not pdf_files:
            return "No PDF files found in bulk_uploads folder"

        latest_pdf = max(pdf_files, key=os.path.getctime)

        html = f"<h2>📄 PDF Text Extraction Debug</h2>"
        html += f"<p><strong>File:</strong> {os.path.basename(latest_pdf)}</p><hr>"

        with pdfplumber.open(latest_pdf) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ''
                html += f"<h3>Page {page_num}</h3>"
                html += f"<pre style='background: #f5f5f5; padding: 15px; border: 1px solid #ddd; white-space: pre-wrap;'>{text}</pre>"
                html += "<hr>"

        return html
    except Exception as e:
        import traceback
        return f"<h2>Error:</h2><pre>{str(e)}\n\n{traceback.format_exc()}</pre>"

# ============================================================================
# SETTINGS ROUTES
# ============================================================================

SETTINGS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Settings - PO Request System</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px; }
        .header {
            background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1); display: flex;
            justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;
        }
        h1 { color: #333; font-size: 24px; }
        h2 { color: #667eea; font-size: 18px; margin-bottom: 15px; }
        .btn {
            padding: 10px 20px; border-radius: 5px; text-decoration: none;
            font-weight: bold; border: none; cursor: pointer; font-size: 14px;
        }
        .btn-primary { background: #667eea; color: white; }
        .btn-secondary { background: #6c757d; color: white; }
        .btn-success { background: #28a745; color: white; }
        .btn-danger { background: #dc3545; color: white; }
        .card {
            background: white; padding: 20px; border-radius: 10px;
            margin-bottom: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        .setting-row {
            display: flex; justify-content: space-between; align-items: center;
            padding: 15px 0; border-bottom: 1px solid #eee;
        }
        .setting-row:last-child { border-bottom: none; }
        .setting-info { flex: 1; }
        .setting-name { font-weight: bold; color: #333; }
        .setting-desc { color: #666; font-size: 13px; margin-top: 5px; }
        .toggle-switch {
            position: relative; width: 60px; height: 30px;
        }
        .toggle-switch input { opacity: 0; width: 0; height: 0; }
        .slider {
            position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0;
            background-color: #ccc; transition: .3s; border-radius: 30px;
        }
        .slider:before {
            position: absolute; content: ""; height: 22px; width: 22px; left: 4px; bottom: 4px;
            background-color: white; transition: .3s; border-radius: 50%;
        }
        input:checked + .slider { background-color: #28a745; }
        input:checked + .slider:before { transform: translateX(30px); }
        .stats-grid {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px;
        }
        .stat-box {
            background: #f8f9fa; padding: 15px; border-radius: 8px; text-align: center;
        }
        .stat-value { font-size: 24px; font-weight: bold; color: #667eea; }
        .stat-label { color: #666; font-size: 12px; margin-top: 5px; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #eee; }
        th { background: #f8f9fa; font-weight: bold; color: #333; }
        .success { color: #28a745; }
        .error { color: #dc3545; }
        .badge {
            display: inline-block; padding: 3px 8px; border-radius: 12px;
            font-size: 11px; font-weight: bold;
        }
        .badge-success { background: #d4edda; color: #155724; }
        .badge-danger { background: #f8d7da; color: #721c24; }
        .badge-info { background: #cce5ff; color: #004085; }
        .api-status {
            display: inline-flex; align-items: center; gap: 8px;
            padding: 8px 15px; border-radius: 20px; font-weight: bold;
        }
        .api-status.available { background: #d4edda; color: #155724; }
        .api-status.unavailable { background: #f8d7da; color: #721c24; }
    </style>
</head>
<body>
    <div class="header">
        <h1>⚙️ Settings</h1>
        <a href="{{ url_for('office_dashboard') }}" class="btn btn-secondary">← Back to Dashboard</a>
    </div>

    <div class="card">
        <h2>🤖 Claude AI Matching</h2>

        <div class="api-status {{ 'available' if api_available else 'unavailable' }}">
            {% if api_available %}
                ✅ Claude API Connected
            {% else %}
                ❌ Claude API Not Configured
            {% endif %}
        </div>

        {% if not api_available %}
        <p style="margin-top: 15px; color: #666;">
            To enable Claude AI matching, set the <code>ANTHROPIC_API_KEY</code> environment variable.
        </p>
        {% endif %}

        <div class="setting-row">
            <div class="setting-info">
                <div class="setting-name">Enable Claude AI Matching</div>
                <div class="setting-desc">
                    Use Claude AI as a fallback when other matching methods fail.
                    Handles misspellings, OCR errors, and spacing issues intelligently.
                </div>
            </div>
            <label class="toggle-switch">
                <input type="checkbox" id="claudeEnabled" {{ 'checked' if claude_enabled else '' }}
                       onchange="toggleClaude(this.checked)" {{ 'disabled' if not api_available else '' }}>
                <span class="slider"></span>
            </label>
        </div>
    </div>

    <div class="card">
        <h2>📊 Claude API Usage Statistics</h2>

        <div class="stats-grid">
            <div class="stat-box">
                <div class="stat-value">{{ usage_stats.total_calls }}</div>
                <div class="stat-label">Total API Calls</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">{{ usage_stats.successful }}</div>
                <div class="stat-label">Successful Matches</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">{{ "%.0f"|format(usage_stats.success_rate) }}%</div>
                <div class="stat-label">Success Rate</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">${{ "%.4f"|format(usage_stats.total_cost) }}</div>
                <div class="stat-label">Estimated Cost</div>
            </div>
        </div>

        {% if recent_logs %}
        <h3 style="margin-top: 20px; margin-bottom: 10px;">Recent API Calls</h3>
        <table>
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Result</th>
                    <th>PO</th>
                    <th>Job</th>
                    <th>Confidence</th>
                    <th>Cost</th>
                </tr>
            </thead>
            <tbody>
                {% for log in recent_logs %}
                <tr>
                    <td>{{ log.timestamp }}</td>
                    <td>
                        {% if log.success %}
                            <span class="badge badge-success">✓ Matched</span>
                        {% else %}
                            <span class="badge badge-danger">✗ No Match</span>
                        {% endif %}
                    </td>
                    <td>{{ log.matched_po or '-' }}</td>
                    <td>{{ log.matched_job or '-' }}</td>
                    <td>{{ "%.0f"|format(log.confidence * 100) if log.confidence else '-' }}%</td>
                    <td>${{ "%.4f"|format(log.cost_estimate) }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <p style="color: #666; margin-top: 15px;">No API calls recorded yet.</p>
        {% endif %}
    </div>

    <div class="card">
        <h2>📈 Invoice Match Methods</h2>
        <p style="color: #666; margin-bottom: 15px;">
            Shows which methods have been used to match invoices to POs.
        </p>

        <div class="stats-grid">
            {% for method, count in match_method_stats.items() %}
            <div class="stat-box">
                <div class="stat-value">{{ count }}</div>
                <div class="stat-label">{{ method }}</div>
            </div>
            {% endfor %}
        </div>
    </div>

    <script>
        function toggleClaude(enabled) {
            fetch('/settings/toggle_claude', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: enabled })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    // Visual feedback
                    const status = document.querySelector('.api-status');
                    if (status) {
                        status.innerHTML = enabled ? '✅ Claude AI Enabled' : '⏸️ Claude AI Disabled';
                    }
                } else {
                    alert('Failed to update setting: ' + (data.error || 'Unknown error'));
                    // Revert checkbox
                    document.getElementById('claudeEnabled').checked = !enabled;
                }
            })
            .catch(error => {
                alert('Error: ' + error);
                document.getElementById('claudeEnabled').checked = !enabled;
            });
        }
    </script>
</body>
</html>
'''


@app.route('/settings')
def settings_page():
    """Settings page for configuring Claude AI matching and viewing usage stats"""
    if 'user' not in session or session.get('role') != 'office':
        flash('Access denied')
        return redirect(url_for('login'))

    # Check API availability
    api_available = ANTHROPIC_AVAILABLE and bool(ANTHROPIC_API_KEY)
    claude_enabled = is_claude_matching_enabled()

    # Get usage statistics
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Claude API usage stats
    c.execute("""SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                    SUM(cost_estimate) as total_cost
                 FROM claude_api_log""")
    row = c.fetchone()
    usage_stats = {
        'total_calls': row[0] or 0,
        'successful': row[1] or 0,
        'total_cost': row[2] or 0,
        'success_rate': (row[1] / row[0] * 100) if row[0] and row[0] > 0 else 0
    }

    # Recent API logs
    c.execute("""SELECT timestamp, matched_po, matched_job, confidence, cost_estimate, success
                 FROM claude_api_log
                 ORDER BY timestamp DESC
                 LIMIT 20""")
    recent_logs = []
    for row in c.fetchall():
        recent_logs.append({
            'timestamp': row[0],
            'matched_po': row[1],
            'matched_job': row[2],
            'confidence': row[3] or 0,
            'cost_estimate': row[4] or 0,
            'success': row[5]
        })

    # Match method stats
    c.execute("""SELECT match_method, COUNT(*) as count
                 FROM po_requests
                 WHERE match_method IS NOT NULL
                 GROUP BY match_method
                 ORDER BY count DESC""")
    match_method_stats = {}
    for row in c.fetchall():
        match_method_stats[row[0] or 'Unknown'] = row[1]

    conn.close()

    return render_template_string(SETTINGS_TEMPLATE,
                                  api_available=api_available,
                                  claude_enabled=claude_enabled,
                                  usage_stats=usage_stats,
                                  recent_logs=recent_logs,
                                  match_method_stats=match_method_stats)


@app.route('/settings/toggle_claude', methods=['POST'])
def toggle_claude_setting():
    """Toggle Claude AI matching on/off"""
    if 'user' not in session or session.get('role') != 'office':
        return jsonify({'success': False, 'error': 'Access denied'})

    try:
        data = request.get_json()
        enabled = data.get('enabled', False)
        set_setting('claude_matching_enabled', 'true' if enabled else 'false')
        return jsonify({'success': True, 'enabled': enabled})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ============================================================================
# API VERIFICATION ENDPOINT
# ============================================================================

@app.route('/api/verify')
def verify_api_setup():
    """Public endpoint to verify API and environment configuration.
    Visit /api/verify to check if everything is set up correctly."""
    results = {}

    # 1. Check Anthropic package
    results['anthropic_package_installed'] = ANTHROPIC_AVAILABLE

    # 2. Check API key is set (don't reveal the key)
    api_key_set = bool(ANTHROPIC_API_KEY)
    results['anthropic_api_key_set'] = api_key_set
    if api_key_set:
        results['anthropic_api_key_preview'] = ANTHROPIC_API_KEY[:7] + '...'

    # 3. Check Claude matching enabled
    results['claude_matching_enabled'] = is_claude_matching_enabled()

    # 4. Test actual API connectivity
    results['anthropic_api_connected'] = False
    if ANTHROPIC_AVAILABLE and api_key_set:
        try:
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=10,
                messages=[{"role": "user", "content": "Reply with OK"}]
            )
            results['anthropic_api_connected'] = True
            results['anthropic_api_response'] = message.content[0].text.strip()
        except Exception as e:
            results['anthropic_api_error'] = str(e)

    # 5. Check other environment variables
    results['secret_key_set'] = bool(os.environ.get('SECRET_KEY'))
    results['data_dir_set'] = bool(os.environ.get('DATA_DIR'))
    results['website_url'] = os.environ.get('WEBSITE_URL', 'not set')
    results['telegram_bot_configured'] = bool(os.environ.get('TELEGRAM_BOT_TOKEN'))
    results['telegram_chat_configured'] = bool(os.environ.get('TELEGRAM_CHAT_ID'))

    # 6. Check database
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        user_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM jobs")
        job_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM po_requests")
        po_count = c.fetchone()[0]
        conn.close()
        results['database_connected'] = True
        results['database_counts'] = {
            'users': user_count,
            'jobs': job_count,
            'po_requests': po_count
        }
    except Exception as e:
        results['database_connected'] = False
        results['database_error'] = str(e)

    # Overall status
    all_good = (
        results['anthropic_package_installed']
        and results['anthropic_api_key_set']
        and results['anthropic_api_connected']
        and results['database_connected']
        and results['secret_key_set']
    )
    results['overall_status'] = 'ALL SYSTEMS GO' if all_good else 'ISSUES DETECTED'

    return jsonify(results)

@app.route('/api/debug_matching')
def debug_matching():
    """Debug endpoint to check matching status and logs"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Get all PO requests with their status
    c.execute("""SELECT id, tech_name, job_name, status, estimated_cost,
                        invoice_filename, invoice_number, match_method
                 FROM po_requests ORDER BY id DESC""")
    pos = []
    for row in c.fetchall():
        pos.append({
            'id': row[0], 'tech': row[1], 'job': row[2], 'status': row[3],
            'cost': row[4], 'invoice_file': row[5], 'invoice_num': row[6],
            'match_method': row[7]
        })

    # Get approved POs without invoices (what bulk upload would see)
    c.execute("""SELECT id, job_name FROM po_requests
                 WHERE status='approved'
                 AND (invoice_filename IS NULL OR invoice_filename = '')""")
    available_for_matching = [{'id': r[0], 'job': r[1]} for r in c.fetchall()]

    # Get active jobs
    c.execute("SELECT job_name FROM jobs WHERE active=1")
    active_jobs = [r[0] for r in c.fetchall()]

    # Get recent Claude API logs
    c.execute("""SELECT timestamp, invoice_text_preview, matched_po, matched_job,
                        confidence, cost_estimate, success
                 FROM claude_api_log ORDER BY timestamp DESC LIMIT 10""")
    api_logs = []
    for row in c.fetchall():
        api_logs.append({
            'timestamp': row[0], 'text_preview': row[1], 'matched_po': row[2],
            'matched_job': row[3], 'confidence': row[4], 'cost': row[5],
            'success': row[6]
        })

    # Check Claude status
    claude_status = {
        'anthropic_available': ANTHROPIC_AVAILABLE,
        'api_key_set': bool(ANTHROPIC_API_KEY),
        'matching_enabled': is_claude_matching_enabled()
    }

    conn.close()
    return jsonify({
        'all_pos': pos,
        'available_for_matching': available_for_matching,
        'active_jobs': active_jobs,
        'claude_status': claude_status,
        'recent_api_logs': api_logs
    })

# ============================================================================
# END DEBUG ROUTES
# ============================================================================

# Force close any unclosed strings
ADMIN_DASHBOARD_TEMPLATE = ADMIN_DASHBOARD_TEMPLATE if 'ADMIN_DASHBOARD_TEMPLATE' in dir() else ''
ADMIN_USERS_TEMPLATE = ADMIN_USERS_TEMPLATE if 'ADMIN_USERS_TEMPLATE' in dir() else ''
ADMIN_EDIT_USER_TEMPLATE = ADMIN_EDIT_USER_TEMPLATE if 'ADMIN_EDIT_USER_TEMPLATE' in dir() else ''
ADMIN_CREATE_USER_TEMPLATE = ADMIN_CREATE_USER_TEMPLATE if 'ADMIN_CREATE_USER_TEMPLATE' in dir() else ''

init_db()
print("✓ Database initialized on startup")

if __name__ == '__main__':
       app.run(debug=False)  # Change to False for production
