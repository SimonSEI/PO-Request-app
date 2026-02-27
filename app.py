from flask import Flask, render_template_string, request, redirect, url_for, session, flash, jsonify, send_from_directory, send_file
from datetime import datetime, timedelta
import uuid
import sqlite3
import os
import re
import secrets
import json
import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from markupsafe import Markup

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
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

# Email Configuration for Password Reset
EMAIL_ENABLED = False
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
EMAIL_ADDRESS = 'YOUR_EMAIL@gmail.com'
EMAIL_PASSWORD = 'YOUR_APP_PASSWORD'
WEBSITE_URL = os.environ.get('WEBSITE_URL', 'http://localhost:5000')

# ... rest of your code continues ...

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

    # Users table with email and tech_type
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY,
                  username TEXT UNIQUE,
                  password TEXT,
                  role TEXT,
                  email TEXT,
                  full_name TEXT,
                  created_date TEXT,
                  last_login TEXT,
                  tech_type TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS po_requests
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  tech_username TEXT, tech_name TEXT, job_name TEXT, store_name TEXT,
                  estimated_cost REAL, description TEXT, status TEXT DEFAULT 'pending',
                  request_date TEXT, approval_date TEXT, approval_notes TEXT,
                  approved_by TEXT, invoice_filename TEXT, invoice_number TEXT,
                  invoice_cost TEXT, invoice_date TEXT, invoice_upload_date TEXT,
                  po_type TEXT)''')

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

    # Techs table - managed by office, used for tech name dropdown
    c.execute('''CREATE TABLE IF NOT EXISTS techs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT UNIQUE,
                  created_date TEXT)''')

    # Add match_method column to po_requests if it doesn't exist
    try:
        c.execute("ALTER TABLE po_requests ADD COLUMN match_method TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Add delivery_notes column to po_requests if it doesn't exist
    try:
        c.execute("ALTER TABLE po_requests ADD COLUMN delivery_notes TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Add budget (Cost of Materials) column to jobs if it doesn't exist
    try:
        c.execute("ALTER TABLE jobs ADD COLUMN budget REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Add department column to jobs if it doesn't exist
    try:
        c.execute("ALTER TABLE jobs ADD COLUMN department TEXT DEFAULT 'service'")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Add jobber_invoice_number column to po_requests if it doesn't exist
    try:
        c.execute("ALTER TABLE po_requests ADD COLUMN jobber_invoice_number TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Add manual_review_flag column to po_requests if it doesn't exist
    try:
        c.execute("ALTER TABLE po_requests ADD COLUMN manual_review_flag TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Add client_name column to po_requests if it doesn't exist (for Service PO details)
    try:
        c.execute("ALTER TABLE po_requests ADD COLUMN client_name TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Add job_code column to jobs if it doesn't exist
    try:
        c.execute("ALTER TABLE jobs ADD COLUMN job_code TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Add tech_type column to users if it doesn't exist (for tech classification)
    try:
        c.execute("ALTER TABLE users ADD COLUMN tech_type TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Add po_type column to po_requests if it doesn't exist (install or service)
    try:
        c.execute("ALTER TABLE po_requests ADD COLUMN po_type TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Migration: Fix any existing jobs with NULL active field to active=1
    try:
        c.execute("UPDATE jobs SET active=1 WHERE active IS NULL")
    except sqlite3.OperationalError:
        pass  # Column might not exist yet

    # Migration: Ensure budget column has proper values
    try:
        c.execute("UPDATE jobs SET budget=0 WHERE budget IS NULL")
    except sqlite3.OperationalError:
        pass  # Column might not exist yet

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

    # Default users - REMOVED all technician defaults, office manages them now
    # Users will be added through manage_techs interface
    users = []

    for user_data in users:
        try:
            c.execute("INSERT INTO users VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?)", user_data)
        except sqlite3.IntegrityError:
            pass

    # Clear the techs table to start fresh (as per refactoring requirement)
    try:
        c.execute("DELETE FROM techs")
    except sqlite3.OperationalError:
        pass  # techs table might not exist yet

    # Add default jobs if empty
    c.execute("SELECT COUNT(*) FROM jobs")
    if c.fetchone()[0] == 0:
        default_jobs = [
            ('Chase Bank', 2024),
            ('Seven Lakes', 2025),
            ('Downtown Plaza', 2025),
            ('Herons Glen', 2025),
        ]
        for job_name, year in default_jobs:
            c.execute("INSERT INTO jobs (job_name, year, created_date, active) VALUES (?, ?, ?, 1)",
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

        # Add budget (Cost of Materials) column to jobs if it doesn't exist
        try:
            c.execute("ALTER TABLE jobs ADD COLUMN budget REAL DEFAULT 0")
            print("✓ Added budget column to jobs")
        except sqlite3.OperationalError:
            print("Budget column already exists")

        conn.commit()
        conn.close()

        return "Database updated successfully! You can now <a href='/'>login</a>. (You can delete this route now)"
    except Exception as e:
        return f"Error: {str(e)}"

def format_po_number(po_id, job_name, job_code=None):
    """Format PO number with job code if available, otherwise use S prefix for Service jobs"""
    if job_code:
        return f"{job_code}-{po_id}"
    if job_name and job_name.lower() == 'service':
        return f"S{po_id}"
    return f"{po_id}"

def format_po_display(po_id, job_name, client_name=None, job_code=None):
    """Format PO display with client name for Service jobs"""
    po_number = format_po_number(po_id, job_name, job_code)
    if job_name and job_name.lower() == 'service' and client_name:
        return f"{po_number} {client_name}"
    return po_number

def get_next_po_number_with_prefix(tech_type, db_path=DB_PATH):
    """Get the next PO number for a technician type with S or I prefix

    Args:
        tech_type: 'service' (prefix S) or 'install' (prefix I)
        db_path: path to database

    Returns:
        tuple: (next_po_id, formatted_po_string, prefix)
        Example: (1, 'S0001', 'S') or (1, 'I0001', 'I')
    """
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Map tech_type to prefix
    prefix = 'S' if tech_type == 'service' else 'I'

    # Find the max ID for this tech type
    c.execute("SELECT MAX(id) FROM po_requests WHERE po_type = ?", (tech_type,))
    result = c.fetchone()
    max_id = result[0] if result and result[0] else 0

    conn.close()

    next_id = max_id + 1
    formatted_po = f"{prefix}{next_id:04d}"

    return next_id, formatted_po, prefix

# Make these available to templates
app.jinja_env.globals.update(format_po_number=format_po_number)
app.jinja_env.globals.update(format_po_display=format_po_display)


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


def detect_packing_slip(text):
    """
    Detect if a document is a packing slip rather than an invoice.
    Returns True if the document appears to be a packing slip.
    """
    if not text:
        return False
    text_upper = text.upper()
    packing_indicators = [
        'PACKING SLIP', 'PACKING LIST', 'PACK SLIP', 'PACKSLIP',
        'SHIPPING SLIP', 'DELIVERY SLIP', 'DELIVERY NOTE',
        'BILL OF LADING', 'SHIP NOTICE', 'SHIPPING NOTICE',
        'SHIPMENT NOTICE', 'SHIPMENT CONFIRMATION',
    ]
    for indicator in packing_indicators:
        if indicator in text_upper:
            return True
    return False


def match_packing_slip_to_po(text, po_map):
    """
    Try to match a packing slip to an approved PO.
    Uses the same PO number and job name detection as invoice matching,
    but also tries Claude AI for intelligent matching.

    Returns: (po_id, order_number, vendor) or (None, None, None)
    """
    if not text or not po_map:
        return (None, None, None)

    text_upper = text.upper()

    # Try to extract an order/reference number from the packing slip
    order_number = None
    order_patterns = [
        r'Order\s*#\s*:?\s*([A-Z0-9\-]+)',
        r'Order\s*(?:NO|NUM|NUMBER)\s*:?\s*([A-Z0-9\-]+)',
        r'Sales\s*Order\s*#?\s*:?\s*([A-Z0-9\-]+)',
        r'Shipment\s*#?\s*:?\s*([A-Z0-9\-]+)',
        r'Tracking\s*#?\s*:?\s*([A-Z0-9\-]+)',
    ]
    for pattern in order_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            order_number = match.group(1).strip()
            break

    # Try to extract vendor name (usually near the top of the document)
    vendor = None
    lines = text.strip().split('\n')
    for line in lines[:10]:
        line_stripped = line.strip()
        if line_stripped and len(line_stripped) > 3 and not re.match(r'^[\d\s\-/]+$', line_stripped):
            # Skip common headers
            if not any(skip in line_stripped.upper() for skip in ['PACKING', 'BILL TO', 'SHIP TO', 'DATE', 'ORDER', 'PAGE']):
                vendor = line_stripped
                break

    # Method 1: Look for PO number directly in text
    po_patterns = [
        r'PO\s*Number[:\s]+(\d{3,})',
        r'PO\s*#?\s*[:\s]*(\d{3,})',
        r'Customer\s*PO\s*#?\s*[:\s]*(\d{3,})',
        r'Purchase\s*Order[:\s]+(\d{3,})',
    ]
    for pattern in po_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                candidate = int(match.group(1))
                if candidate in po_map:
                    print(f"  Packing slip matched to PO {candidate} via pattern")
                    return (candidate, order_number, vendor)
            except ValueError:
                continue

    # Method 2: Look for job names in the text
    for po_id, po_info in po_map.items():
        job_name = po_info.get('job_name', '')
        if not job_name:
            continue
        found, _, _, score = find_job_name_in_text(text, job_name, threshold=0.75)
        if found:
            print(f"  Packing slip matched to PO {po_id} via job name '{job_name}' (score: {score:.2f})")
            return (po_id, order_number, vendor)

    # Method 3: Use Claude AI for matching
    if is_claude_matching_enabled():
        active_jobs = get_active_job_names()
        claude_po, claude_job, confidence = match_invoice_with_claude(text, active_jobs, po_map)
        if claude_po and confidence >= 0.6:
            print(f"  Packing slip matched to PO {claude_po} via Claude AI (confidence: {confidence:.0%})")
            return (claude_po, order_number, vendor)

    return (None, order_number, vendor)


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
            model="claude-sonnet-4-6",
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


@app.route('/fuzzy_match_job', methods=['POST'])
def fuzzy_match_job():
    """Find the closest matching active job name using fuzzy matching.
    Used for auto-correcting misspelled job names typed by technicians."""
    if 'username' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'})

    try:
        data = request.get_json()
        query = data.get('query', '').strip()

        if not query or len(query) < 2:
            return jsonify({'success': False, 'matches': []})

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT job_name, year FROM jobs WHERE active=1")
        jobs = c.fetchall()
        conn.close()

        # First check for exact case-insensitive match
        for job_name, year in jobs:
            if job_name.lower() == query.lower():
                return jsonify({
                    'success': True,
                    'exact': True,
                    'matches': [{'name': job_name, 'year': year, 'score': 1.0}]
                })

        # Fuzzy match against all active jobs
        scored_matches = []
        for job_name, year in jobs:
            score = fuzzy_match_score(query, job_name)
            if score >= 0.55:  # Lower threshold to catch more typos
                scored_matches.append({
                    'name': job_name,
                    'year': year,
                    'score': round(score, 3)
                })

        # Sort by score descending
        scored_matches.sort(key=lambda x: x['score'], reverse=True)

        # Also include substring matches that fuzzy might miss
        query_lower = query.lower()
        for job_name, year in jobs:
            if query_lower in job_name.lower() or job_name.lower() in query_lower:
                already_included = any(m['name'] == job_name for m in scored_matches)
                if not already_included:
                    scored_matches.append({
                        'name': job_name,
                        'year': year,
                        'score': 0.6
                    })

        # Return top 5 matches
        return jsonify({
            'success': True,
            'exact': False,
            'matches': scored_matches[:5]
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'matches': []})

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
                'full_name': user[5] if len(user) > 5 else actual_username,
                'tech_type': user[8] if len(user) > 8 else None
            }
            save_user_session(session_id, user_data)
            session['session_id'] = session_id
            session['username'] = actual_username
            session['role'] = user[3]
            session['email'] = user[4] if len(user) > 4 else None
            session['full_name'] = user[5] if len(user) > 5 else actual_username
            session['tech_type'] = user[8] if len(user) > 8 else None

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

    # Show this tech's own POs (all statuses)
    tech_type = session.get('tech_type', 'install')
    c.execute("SELECT * FROM po_requests WHERE tech_username=? ORDER BY id DESC", (session['username'],))
    requests = c.fetchall()

    # Get column indices
    c.execute("PRAGMA table_info(po_requests)")
    columns = {col[1]: col[0] for col in c.fetchall()}

    # Get full name for display
    c.execute("SELECT full_name FROM users WHERE username=?", (session['username'],))
    user_info = c.fetchone()
    full_name = user_info[0] if user_info else session['username']

    conn.close()

    inv_filename_idx = columns.get('invoice_filename', 12)
    inv_number_idx = columns.get('invoice_number', 13)
    inv_cost_idx = columns.get('invoice_cost', 14)
    inv_upload_idx = columns.get('invoice_upload_date', 16)

    return render_template_string(TECH_DASHBOARD_TEMPLATE,
                                username=session['username'],
                                full_name=full_name,
                                tech_type=tech_type,
                                requests=requests,
                                inv_filename_idx=inv_filename_idx,
                                inv_number_idx=inv_number_idx,
                                inv_cost_idx=inv_cost_idx,
                                inv_upload_idx=inv_upload_idx)

@app.route('/office_dashboard')
def office_dashboard():
    """Unified department dashboard - Service & Install tabs with jobs and POs"""
    if 'username' not in session or session['role'] != 'office':
        return redirect(url_for('login'))

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Get all jobs with their stats
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
                COUNT(p.id) as po_count,
                COALESCE(j.budget, 0) as budget,
                COALESCE(j.department, 'service') as department,
                j.job_code
            FROM jobs j
            LEFT JOIN po_requests p ON j.job_name = p.job_name
            GROUP BY j.id, j.job_name, j.year, j.created_date, j.active, j.budget, j.department, j.job_code
            ORDER BY j.active DESC, j.year DESC, j.job_name ASC
        """)
        all_jobs = c.fetchall()

        # Get service and install POs for each job (ALL POs, not just active)
        job_pos = {}
        job_all_pos = {}
        for job in all_jobs:
            job_name = job[1]
            # Get active POs for this job (for display on card)
            c.execute("""
                SELECT id, po_type, tech_username, status, estimated_cost, invoice_cost, request_date
                FROM po_requests
                WHERE job_name=? AND status IN ('approved', 'awaiting_invoice')
                ORDER BY id DESC
            """, (job_name,))
            job_pos[job[0]] = c.fetchall()

            # Get ALL POs for this job (for complete history)
            c.execute("""
                SELECT id, po_type, tech_username, status, estimated_cost, invoice_cost, request_date, description
                FROM po_requests
                WHERE job_name=?
                ORDER BY id DESC
            """, (job_name,))
            job_all_pos[job[0]] = c.fetchall()

        # Get tech info for POs
        c.execute("SELECT id, username, full_name, tech_type FROM users WHERE role='technician'")
        techs = {row[1]: {'id': row[0], 'name': row[2], 'type': row[3]} for row in c.fetchall()}

        conn.close()

        # Separate jobs by stored department
        service_jobs = []
        install_jobs = []

        for job in all_jobs:
            job_id = job[0]
            stored_department = job[10]  # Department from database (11th column, index 10)

            # Add job to its assigned department
            if stored_department == 'install':
                install_jobs.append(job)
            else:
                # Default to service for new jobs or jobs without a department
                service_jobs.append(job)

        return render_template_string(UNIFIED_DEPARTMENT_DASHBOARD_TEMPLATE,
                                      username=session['username'],
                                      service_jobs=service_jobs,
                                      install_jobs=install_jobs,
                                      job_pos=job_pos,
                                      job_all_pos=job_all_pos,
                                      techs=techs)

    except Exception as e:
        return f"<h2>Error loading dashboard</h2><p>{str(e)}</p><p><a href='/office_dashboard'>Reload</a></p>"

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

    # Get tech_type from session - should be 'service' or 'install'
    tech_type = session.get('tech_type', 'install')

    tech_name = request.form['tech_name']
    custom_po_number = request.form.get('custom_po_number', '').strip()
    job_name = request.form['job_name'].strip()
    store_name = request.form['store_name']
    estimated_cost = 0  # Estimated cost removed from form
    description = request.form['description']
    client_name = request.form.get('client_name', '').strip()  # Optional - for Service POs

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # VALIDATE JOB NAME EXISTS AND IS ACTIVE (also get job_code)
    c.execute("SELECT job_name, job_code FROM jobs WHERE LOWER(job_name) = LOWER(?) AND active=1", (job_name,))
    valid_job = c.fetchone()

    if not valid_job:
        # Try fuzzy matching to auto-correct misspelled job names
        c.execute("SELECT job_name, job_code FROM jobs WHERE active=1")
        all_active_jobs = [row[0] for row in c.fetchall()]
        best_match = None
        best_score = 0.0
        for active_job in all_active_jobs:
            score = fuzzy_match_score(job_name, active_job)
            if score > best_score:
                best_score = score
                best_match = active_job

        if best_match and best_score >= 0.70:
            # Auto-correct to the closest matching job
            c.execute("SELECT job_name, job_code FROM jobs WHERE job_name=? AND active=1", (best_match,))
            valid_job = c.fetchone()
            flash(f'Auto-corrected job name from "{job_name}" to "{best_match}"')
        else:
            conn.close()
            flash('❌ ERROR: This job does not exist, is deactivated, or is spelled incorrectly. Please check the job list and try again.')
            return redirect(url_for('tech_dashboard'))

    # Use the correct spelling from database
    job_name = valid_job[0]
    job_code = valid_job[1] if len(valid_job) > 1 else None

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
            
            # Insert with EXPLICIT ID - set to awaiting_invoice
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            c.execute("""INSERT INTO po_requests
                         (id, tech_username, tech_name, job_name, store_name, estimated_cost,
                          description, status, request_date, client_name, po_type)
                         VALUES (?, ?, ?, ?, ?, ?, ?, 'awaiting_invoice', ?, ?, ?)""",
                     (po_id, session['username'], tech_name, job_name, store_name,
                      estimated_cost, description, now_str, client_name if client_name else None, tech_type))

            conn.commit()
            conn.close()

            po_display = format_po_display(po_id, job_name, client_name, job_code)
            flash(f'PO#{po_display}|{job_name}')
            return redirect(url_for('tech_dashboard'))

        except ValueError:
            conn.close()
            flash('❌ ERROR: Invalid PO number format')
            return redirect(url_for('tech_dashboard'))
        except Exception as e:
            conn.close()
            flash(f'❌ ERROR creating custom PO: {str(e)}')
            return redirect(url_for('tech_dashboard'))

    # AUTO-INCREMENT PO NUMBER (normal flow) - with tech type prefix
    else:
        conn.close()  # Close existing connection

        # Get next PO number with correct prefix
        next_id, formatted_po, prefix = get_next_po_number_with_prefix(tech_type)

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Create PO with awaiting_invoice status and po_type
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute("""INSERT INTO po_requests
                     (tech_username, tech_name, job_name, store_name, estimated_cost,
                      description, status, request_date, client_name, po_type)
                     VALUES (?, ?, ?, ?, ?, ?, 'awaiting_invoice', ?, ?, ?)""",
                 (session['username'], tech_name, job_name, store_name,
                  estimated_cost, description, now_str, client_name if client_name else None, tech_type))

        new_id = c.lastrowid
        conn.commit()
        conn.close()

        po_display = f"{formatted_po} {client_name}" if tech_type == 'service' and client_name else formatted_po
        flash(f'PO#{po_display}|{job_name}')
        return redirect(url_for('tech_dashboard'))

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

        c.execute("SELECT status, job_name, client_name FROM po_requests WHERE id=?", (po_id,))
        po = c.fetchone()

        if not po:
            conn.close()
            return jsonify({'success': False, 'error': 'PO request not found'})

        if po[0] != 'awaiting_invoice':
            conn.close()
            return jsonify({'success': False, 'error': 'PO request must be awaiting an invoice'})

        formatted_cost = f"{cost_float:.2f}"

        # ✅ NEW: Update BOTH invoice fields AND estimated_cost
        po_number_formatted = format_po_number(po_id, po[1])
        auto_categorized = False
        manual_review_flag = None
        new_job_name = None

        if po_number_formatted.upper().startswith('S'):
            # Service PO - try to extract year and match to Service YYYY job
            invoice_year = None

            # Try to extract year from uploaded file if PDF
            if invoice_filename and invoice_filename != 'MANUAL_ENTRY' and invoice_filename.lower().endswith('.pdf'):
                try:
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], invoice_filename)
                    if os.path.exists(file_path):
                        import pdfplumber
                        with pdfplumber.open(file_path) as pdf:
                            for page in pdf.pages[:2]:  # Check first 2 pages
                                text = page.extract_text() or ''
                                invoice_year = extract_invoice_year(text)
                                if invoice_year:
                                    break
                except:
                    pass  # If PDF extraction fails, continue without year

            if invoice_year:
                # Check if Service YYYY job exists
                service_job, error = get_service_job_for_year(invoice_year)
                if service_job:
                    new_job_name = service_job
                    auto_categorized = True
                    print(f"✅ Service PO matched to {service_job} based on invoice year {invoice_year}")
                else:
                    conn.close()
                    return jsonify({'success': False, 'error': error})
            else:
                # No year found - flag for manual review
                new_job_name = 'Service'
                manual_review_flag = f"Service PO (ID {po_id}) needs manual review - invoice year could not be extracted. Please assign to appropriate Service job."
                print(f"⚠ Service PO flagged for manual review - unable to extract invoice year")

            c.execute("""UPDATE po_requests
                         SET invoice_filename=?, invoice_number=?, invoice_cost=?,
                             invoice_date=?, invoice_upload_date=?, job_name=?, estimated_cost=?, status=?, manual_review_flag=?
                         WHERE id=?""",
                     (invoice_filename, invoice_number, formatted_cost, 'N/A',
                      datetime.now().strftime('%Y-%m-%d %H:%M:%S'), new_job_name, cost_float, 'matched', manual_review_flag, po_id))
        else:
            # Normal update - replace estimated_cost with actual invoice cost
            c.execute("""UPDATE po_requests
                         SET invoice_filename=?, invoice_number=?, invoice_cost=?,
                             invoice_date=?, invoice_upload_date=?, estimated_cost=?, status=?
                         WHERE id=?""",
                     (invoice_filename, invoice_number, formatted_cost, 'N/A',
                      datetime.now().strftime('%Y-%m-%d %H:%M:%S'), cost_float, 'matched', po_id))

        conn.commit()
        conn.close()

        # Build message with formatted PO display
        job_name = po[1]
        client_name_str = po[2] if po and po[2] else None
        po_display = format_po_display(po_id, job_name, client_name_str)
        message = f'Invoice saved successfully for PO {po_display}'
        if auto_categorized:
            message += f' - Auto-matched to {new_job_name}'
        if manual_review_flag:
            message += ' ⚠️ - Flagged for manual job assignment'

        return jsonify({
            'success': True,
            'message': message,
            'saved_data': {
                'invoice_number': invoice_number,
                'invoice_cost': formatted_cost,
                'auto_categorized': auto_categorized,
                'manual_review_flag': manual_review_flag,
                'client_name': client_name_str
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

        # If user is a technician, only show jobs matching their department
        if session.get('role') == 'technician':
            tech_type = session.get('tech_type', 'install')
            c.execute("""SELECT job_name, year FROM jobs
                        WHERE active=1 AND (department=? OR department IS NULL OR department='')
                        ORDER BY year DESC, job_name ASC""", (tech_type,))
        else:
            # Office manager sees all active jobs
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

@app.route('/api/get_jobs', methods=['GET'])
def api_get_jobs():
    """API endpoint to get jobs data as JSON"""
    if 'username' not in session or session['role'] != 'office':
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Get jobs with invoice totals, budget, and job_code
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
                COUNT(p.id) as po_count,
                COALESCE(j.budget, 0) as budget,
                j.job_code
            FROM jobs j
            LEFT JOIN po_requests p ON j.job_name = p.job_name
            GROUP BY j.id, j.job_name, j.year, j.created_date, j.active, j.budget, j.job_code
            ORDER BY j.active DESC, j.year DESC, j.job_name ASC
        """)
        jobs = c.fetchall()
        conn.close()

        # Convert to list of lists for JSON serialization
        jobs_list = [list(job) for job in jobs]
        return jsonify(jobs_list)

    except Exception as e:
        print(f"[api_get_jobs] Error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/debug_jobs')
def debug_jobs():
    """Debug endpoint to check jobs data being passed to template"""
    if 'username' not in session or session['role'] != 'office':
        return jsonify({'error': 'Unauthorized'})
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("""
            SELECT
                j.id, j.job_name, j.year, j.created_date, j.active,
                COALESCE(SUM(CASE WHEN p.invoice_cost IS NOT NULL THEN CAST(p.invoice_cost AS REAL) ELSE 0 END), 0) as total_invoiced,
                COUNT(CASE WHEN p.invoice_filename IS NOT NULL THEN 1 END) as invoice_count,
                COALESCE(SUM(p.estimated_cost), 0) as total_estimated,
                COUNT(p.id) as po_count,
                COALESCE(j.budget, 0) as budget,
                j.job_code
            FROM jobs j
            LEFT JOIN po_requests p ON j.job_name = p.job_name
            GROUP BY j.id, j.job_name, j.year, j.created_date, j.active, j.budget, j.job_code
            ORDER BY j.active DESC, j.year DESC, j.job_name ASC
        """)
        jobs = c.fetchall()
        conn.close()

        jobs_json = json.dumps(jobs)

        return jsonify({
            'raw_jobs': jobs,
            'json_jobs': jobs_json,
            'job_count': len(jobs),
            'is_valid_json': True
        })
    except Exception as e:
        return jsonify({'error': str(e), 'is_valid_json': False})


@app.route('/restore_jobs_from_history', methods=['POST'])
def restore_jobs_from_history():
    """Restore the jobs table from unique job names found in PO history"""
    if 'username' not in session or session['role'] != 'office':
        return jsonify({'success': False, 'error': 'Unauthorized'})
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # Get all unique job names from po_requests
        c.execute("""
            SELECT DISTINCT job_name, MAX(request_date) as last_used
            FROM po_requests
            WHERE job_name IS NOT NULL AND job_name != ''
            GROUP BY job_name
        """)
        rows = c.fetchall()
        restored = 0
        for row in rows:
            job_name = row[0]
            # Try to extract year from last_used date, default to current year
            try:
                year = int(row[1][:4]) if row[1] else datetime.now().year
            except:
                year = datetime.now().year
            try:
                c.execute("INSERT OR IGNORE INTO jobs (job_name, year, created_date, active) VALUES (?, ?, ?, 1)",
                          (job_name, year, datetime.now().strftime('%Y-%m-%d')))
                if c.rowcount > 0:
                    restored += 1
            except:
                pass
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': f'Restored {restored} job(s) from PO history', 'count': restored})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/get_job_details/<int:job_id>')
def get_job_details(job_id):
    """Get detailed invoice list for a specific job"""
    if 'username' not in session or session['role'] != 'office':
        return jsonify({'success': False, 'error': 'Unauthorized'})

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Get job name, budget, and job_code
        c.execute("SELECT job_name, COALESCE(budget, 0), job_code FROM jobs WHERE id=?", (job_id,))
        job = c.fetchone()
        if not job:
            return jsonify({'success': False, 'error': 'Job not found'})

        job_name = job[0]
        job_budget = float(job[1])
        job_code = job[2] if len(job) > 2 else None

        # Get all POs with invoices for this job
        c.execute("""
            SELECT id, tech_name, estimated_cost, invoice_number, invoice_cost,
                   invoice_upload_date, invoice_filename, status, jobber_invoice_number
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
                'status': row[7],
                'jobber_invoice_number': row[8] if len(row) > 8 else None
            })

        conn.close()

        total_invoiced = sum(inv['invoice_cost'] for inv in invoices)
        budget_pct = round((total_invoiced / job_budget) * 100, 1) if job_budget > 0 else None

        return jsonify({
            'success': True,
            'job_name': job_name,
            'job_code': job_code,
            'budget': job_budget,
            'total_invoiced': total_invoiced,
            'budget_pct': budget_pct,
            'invoices': invoices
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/update_jobber_invoice/<int:po_id>', methods=['POST'])
def update_jobber_invoice(po_id):
    """Update the Jobber invoice number for a PO"""
    if 'username' not in session or session['role'] != 'office':
        return jsonify({'success': False, 'error': 'Unauthorized'})
    try:
        data = request.get_json()
        jobber_number = data.get('jobber_invoice_number', '').strip()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE po_requests SET jobber_invoice_number=? WHERE id=?", (jobber_number or None, po_id))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Jobber invoice number updated'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/manage_techs')
def manage_techs():
    """Unified technician management - office only - shows both service and install techs in columns"""
    if 'username' not in session or session['role'] != 'office':
        return redirect(url_for('login'))

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Get all service technicians - include password
        c.execute("""SELECT id, username, full_name, email, created_date, last_login, password
                     FROM users WHERE role='technician' AND tech_type='service'
                     ORDER BY full_name ASC""")
        service_techs = c.fetchall()

        # Get all install technicians - include password
        c.execute("""SELECT id, username, full_name, email, created_date, last_login, password
                     FROM users WHERE role='technician' AND tech_type='install'
                     ORDER BY full_name ASC""")
        install_techs = c.fetchall()

        # Get ALL POs for each tech (no filtering by tech type, show all their POs)
        tech_pos = {}
        for tech in service_techs:
            c.execute("""SELECT id, po_type, job_name, status, request_date, invoice_cost
                         FROM po_requests WHERE tech_username=?
                         ORDER BY id DESC""", (tech[1],))
            tech_pos[tech[0]] = c.fetchall()

        for tech in install_techs:
            c.execute("""SELECT id, po_type, job_name, status, request_date, invoice_cost
                         FROM po_requests WHERE tech_username=?
                         ORDER BY id DESC""", (tech[1],))
            tech_pos[tech[0]] = c.fetchall()

        conn.close()
        return render_template_string(MANAGE_TECHS_UNIFIED_TEMPLATE,
                                      username=session['username'],
                                      service_techs=service_techs,
                                      install_techs=install_techs,
                                      tech_pos=tech_pos)
    except Exception as e:
        return f"<h2>Error loading Manage Techs page</h2><p>{str(e)}</p><p><a href='/office_dashboard'>Back to Dashboard</a></p>"

@app.route('/manage_service_techs')
def manage_service_techs():
    """Manage Service technicians - office only"""
    if 'username' not in session or session['role'] != 'office':
        return redirect(url_for('login'))

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Get all service technicians (users with tech_type='service') - include password
        c.execute("""SELECT id, username, full_name, email, created_date, last_login, password
                     FROM users WHERE role='technician' AND tech_type='service'
                     ORDER BY full_name ASC""")
        service_techs = c.fetchall()

        # For each tech, get their PO count
        tech_pos = {}
        for tech in service_techs:
            c.execute("""SELECT id, po_type, job_name, status, request_date
                         FROM po_requests WHERE tech_username=? AND po_type='service'
                         ORDER BY id DESC LIMIT 50""", (tech[1],))
            tech_pos[tech[0]] = c.fetchall()

        conn.close()
        return render_template_string(MANAGE_SERVICE_TECHS_TEMPLATE,
                                      username=session['username'],
                                      techs=service_techs,
                                      tech_pos=tech_pos)
    except Exception as e:
        return f"<h2>Error loading Service Techs page</h2><p>{str(e)}</p><p><a href='/office_dashboard'>Back to Dashboard</a></p>"

@app.route('/manage_install_techs')
def manage_install_techs():
    """Manage Install technicians - office only"""
    if 'username' not in session or session['role'] != 'office':
        return redirect(url_for('login'))

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Get all install technicians (users with tech_type='install') - include password
        c.execute("""SELECT id, username, full_name, email, created_date, last_login, password
                     FROM users WHERE role='technician' AND tech_type='install'
                     ORDER BY full_name ASC""")
        install_techs = c.fetchall()

        # For each tech, get their PO count
        tech_pos = {}
        for tech in install_techs:
            c.execute("""SELECT id, po_type, job_name, status, request_date
                         FROM po_requests WHERE tech_username=? AND po_type='install'
                         ORDER BY id DESC LIMIT 50""", (tech[1],))
            tech_pos[tech[0]] = c.fetchall()

        conn.close()
        return render_template_string(MANAGE_INSTALL_TECHS_TEMPLATE,
                                      username=session['username'],
                                      techs=install_techs,
                                      tech_pos=tech_pos)
    except Exception as e:
        return f"<h2>Error loading Install Techs page</h2><p>{str(e)}</p><p><a href='/office_dashboard'>Back to Dashboard</a></p>"

@app.route('/add_tech', methods=['POST'])
def add_tech():
    """Add a technician user account with specified type (service or install)"""
    if 'username' not in session or session['role'] != 'office':
        return jsonify({'success': False, 'error': 'Unauthorized'})
    try:
        data = request.get_json()
        username = data.get('username', '').strip().lower()
        password = data.get('password', '').strip()
        full_name = data.get('full_name', '').strip()
        email = data.get('email', '').strip()
        tech_type = data.get('tech_type', 'install').strip()  # 'service' or 'install'

        if not username or not password or not full_name:
            return jsonify({'success': False, 'error': 'Username, password, and name are required'})

        if tech_type not in ['service', 'install']:
            return jsonify({'success': False, 'error': 'Tech type must be "service" or "install"'})

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Check if username already exists
        c.execute("SELECT id FROM users WHERE LOWER(username)=?", (username,))
        if c.fetchone():
            return jsonify({'success': False, 'error': 'Username already exists'})

        # Create user account with tech_type
        now = datetime.now().strftime('%Y-%m-%d')
        c.execute("""INSERT INTO users (username, password, role, email, full_name, created_date, tech_type)
                     VALUES (?, ?, 'technician', ?, ?, ?, ?)""",
                  (username, password, email if email else None, full_name, now, tech_type))
        conn.commit()
        conn.close()

        return jsonify({'success': True, 'message': f'{"Service" if tech_type == "service" else "Install"} tech "{full_name}" created successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/delete_tech', methods=['POST'])
def delete_tech():
    """Delete a technician user account"""
    if 'username' not in session or session['role'] != 'office':
        return jsonify({'success': False, 'error': 'Unauthorized'})
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Get user details before deleting
        c.execute("SELECT username, full_name FROM users WHERE id=?", (user_id,))
        user_info = c.fetchone()

        if not user_info:
            return jsonify({'success': False, 'error': 'Technician not found'})

        # Delete the user account (POs will remain for historical reference)
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
        conn.close()

        return jsonify({'success': True, 'message': f'Technician "{user_info[1]}" deleted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/get_techs')
def get_techs():
    """Get list of technician names for dropdown"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name FROM techs ORDER BY name ASC")
    techs = [row[0] for row in c.fetchall()]
    conn.close()
    return jsonify({'success': True, 'techs': techs})

@app.route('/test_template')
def test_template():
    try:
        return f"Template exists: {type(JOB_MANAGEMENT_TEMPLATE)}"
    except NameError:
        return "ERROR: JOB_MANAGEMENT_TEMPLATE is not defined!"


@app.route('/add_job', methods=['POST'])
def add_job():
    """Add a new job - supports both AJAX (JSON response) and regular form submission (redirect)"""
    if 'username' not in session or session['role'] != 'office':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.best == 'application/json':
            return jsonify({'success': False, 'error': 'Unauthorized'})
        return redirect(url_for('login'))

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.best == 'application/json'

    job_name = request.form.get('job_name', '').strip()
    year = request.form.get('year', '').strip()
    budget = request.form.get('budget', '0').strip()
    department = request.form.get('department', 'service').strip()
    job_code = request.form.get('job_code', '').strip()

    print(f"[add_job] Adding job: name='{job_name}', year={year}, budget={budget}, dept='{department}', code='{job_code}', ajax={is_ajax}")

    if not job_name or not year:
        if is_ajax:
            return jsonify({'success': False, 'error': 'Job name and year required'})
        flash('Error: Job name and year are required')
        return redirect(url_for('office_dashboard'))

    try:
        year = int(year)
    except ValueError:
        if is_ajax:
            return jsonify({'success': False, 'error': 'Invalid year'})
        flash('Error: Invalid year')
        return redirect(url_for('office_dashboard'))

    try:
        budget = float(budget) if budget else 0
    except ValueError:
        budget = 0

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO jobs (job_name, year, created_date, budget, department, job_code, active) VALUES (?, ?, ?, ?, ?, ?, 1)",
                 (job_name, year, datetime.now().strftime('%Y-%m-%d'), budget, department, job_code or None))
        conn.commit()
        conn.close()
        print(f"[add_job] Successfully added job: '{job_name}' to {department} department")
        if is_ajax:
            return jsonify({'success': True, 'message': f'Job "{job_name}" added successfully'})
        flash(f'Job "{job_name}" added successfully!')

        # Redirect back to the appropriate department tab
        return redirect(url_for('office_dashboard', tab=department))
    except sqlite3.IntegrityError:
        if conn:
            conn.close()
        if is_ajax:
            return jsonify({'success': False, 'error': 'Job name already exists'})
        flash('Error: Job name already exists')
        return redirect(url_for('office_dashboard'))
    except Exception as e:
        if conn:
            conn.close()
        if is_ajax:
            return jsonify({'success': False, 'error': f'Database error: {str(e)}'})
        flash(f'Error: {str(e)}')
        return redirect(url_for('office_dashboard'))


@app.route('/edit_job', methods=['POST'])
def edit_job():
    """Edit existing job"""
    if 'username' not in session or session['role'] != 'office':
        return jsonify({'success': False, 'error': 'Unauthorized'})

    data = request.get_json()
    job_id = data.get('job_id')
    job_name = data.get('job_name', '').strip()
    year = data.get('year')
    budget = data.get('budget')
    job_code = data.get('job_code', '').strip()

    if not job_id or not job_name or not year:
        return jsonify({'success': False, 'error': 'All fields required'})

    try:
        budget = float(budget) if budget is not None else 0
    except (ValueError, TypeError):
        budget = 0

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE jobs SET job_name=?, year=?, budget=?, job_code=? WHERE id=?", (job_name, year, budget, job_code or None, job_id))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Job updated successfully'})


@app.route('/update_job_budget', methods=['POST'])
def update_job_budget():
    """Update budget (Cost of Materials) for a job"""
    if 'username' not in session or session['role'] != 'office':
        return jsonify({'success': False, 'error': 'Unauthorized'})

    data = request.get_json()
    job_id = data.get('job_id')
    budget = data.get('budget')

    if not job_id:
        return jsonify({'success': False, 'error': 'Job ID required'})

    try:
        budget = float(budget) if budget is not None else 0
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Invalid budget amount'})

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE jobs SET budget=? WHERE id=?", (budget, job_id))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Budget updated successfully'})


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
    """Delete a job - jobs can be deleted even if they have POs"""
    if 'username' not in session or session['role'] != 'office':
        return jsonify({'success': False, 'error': 'Unauthorized'})

    data = request.get_json()
    job_id = data.get('job_id')

    if not job_id:
        return jsonify({'success': False, 'error': 'Job ID required'})

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Job deleted successfully'})

@app.route('/backup_database', methods=['POST'])
def backup_database():
    """Create a timestamped backup of the database"""
    if 'username' not in session or session['role'] != 'office':
        return jsonify({'success': False, 'error': 'Unauthorized'})

    try:
        import shutil
        from datetime import datetime

        backup_dir = os.path.join(os.path.dirname(__file__), 'backups')
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f'po_app_backup_{timestamp}.db'
        backup_path = os.path.join(backup_dir, backup_filename)

        # Create backup copy
        shutil.copy2(DB_PATH, backup_path)

        # Also create a timestamped archive
        backup_zip = os.path.join(backup_dir, f'po_app_backup_{timestamp}.zip')

        import zipfile
        with zipfile.ZipFile(backup_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(DB_PATH, arcname='po_app.db')

        return jsonify({
            'success': True,
            'message': f'Backup created: {backup_filename}',
            'backup_file': backup_filename,
            'timestamp': timestamp
        })
    except Exception as e:
        return jsonify({'success': False, 'error': f'Backup failed: {str(e)}'})

@app.route('/list_backups', methods=['GET'])
def list_backups():
    """List all available backups"""
    if 'username' not in session or session['role'] != 'office':
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        backup_dir = os.path.join(os.path.dirname(__file__), 'backups')
        backups = []

        if os.path.exists(backup_dir):
            for filename in sorted(os.listdir(backup_dir), reverse=True):
                if filename.endswith(('.db', '.zip')) and filename.startswith('po_app_backup'):
                    filepath = os.path.join(backup_dir, filename)
                    size = os.path.getsize(filepath)
                    mtime = os.path.getmtime(filepath)
                    backups.append({
                        'filename': filename,
                        'size': size,
                        'size_mb': round(size / (1024*1024), 2),
                        'mtime': mtime,
                        'mtime_str': datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
                    })

        return jsonify(backups)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download_backup/<filename>', methods=['GET'])
def download_backup(filename):
    """Download a backup file"""
    if 'username' not in session or session['role'] != 'office':
        return 'Unauthorized', 401

    try:
        backup_dir = os.path.join(os.path.dirname(__file__), 'backups')
        filepath = os.path.join(backup_dir, filename)

        # Security: ensure the file is in the backups directory
        if not os.path.abspath(filepath).startswith(os.path.abspath(backup_dir)):
            return 'Invalid file path', 403

        if not os.path.exists(filepath):
            return 'File not found', 404

        return send_file(filepath, as_attachment=True, download_name=filename)
    except Exception as e:
        return f'Error: {str(e)}', 500

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

        # ✅ FIXED: Get POs awaiting invoices (without invoices)
        # Include both 'awaiting_invoice' and 'approved' statuses in case of state mismatch
        c.execute("""SELECT id, tech_name, job_name, estimated_cost, client_name
                     FROM po_requests
                     WHERE (status='awaiting_invoice' OR status='approved')
                     AND (invoice_filename IS NULL OR invoice_filename = '')""")
        po_map = {}
        for row in c.fetchall():
            po_map[row[0]] = {
                'id': row[0],
                'tech_name': row[1],
                'job_name': row[2],
                'estimated_cost': row[3],
                'client_name': row[4]
            }  # ← Fixed closing brace

        print(f"\n📋 Found {len(po_map)} approved POs without invoices: {sorted(po_map.keys())}")

        # Debug: Show all POs for troubleshooting
        c.execute("SELECT id, status, invoice_filename FROM po_requests ORDER BY id DESC LIMIT 10")
        all_pos = c.fetchall()
        if all_pos:
            print(f"   DEBUG: Recent POs in database:")
            for po_id, status, inv_file in all_pos:
                print(f"     PO {po_id}: status={status}, invoice_filename={'set' if inv_file else 'empty'}")
        else:
            print(f"   DEBUG: No POs found in database!")

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

                # Check if this is a packing slip BEFORE trying invoice matching
                if detect_packing_slip(text):
                    print(f"  📦 PACKING SLIP detected on page {page_num}")
                    po_id, order_number, vendor = match_packing_slip_to_po(text, po_map)

                    if po_id:
                        # Save packing slip PDF
                        slip_filename = f"PO{po_id:04d}_{timestamp}_PACKSLIP_page{page_num}.pdf"
                        slip_path = os.path.join(app.config['UPLOAD_FOLDER'], slip_filename)
                        pdf_writer = PyPDF2.PdfWriter()
                        pdf_writer.add_page(pdf_reader.pages[page_num - 1])
                        with open(slip_path, 'wb') as f:
                            pdf_writer.write(f)

                        # Build delivery note
                        note_parts = [f"Packing slip received {datetime.now().strftime('%Y-%m-%d %H:%M')}"]
                        if vendor:
                            note_parts.append(f"Vendor: {vendor}")
                        if order_number:
                            note_parts.append(f"Order #: {order_number}")
                        note_parts.append("Package delivered - awaiting invoice.")
                        delivery_note = " | ".join(note_parts)

                        # Update PO with delivery note (append if existing notes)
                        c.execute("SELECT delivery_notes FROM po_requests WHERE id=?", (po_id,))
                        existing = c.fetchone()
                        if existing and existing[0]:
                            delivery_note = existing[0] + "\n" + delivery_note
                        c.execute("UPDATE po_requests SET delivery_notes=? WHERE id=?",
                                  (delivery_note, po_id))
                        conn.commit()

                        po_info = po_map.get(po_id, {})
                        print(f"  ✅ Packing slip matched to PO {po_id} ({po_info.get('job_name', 'Unknown')})")

                        if 'packing_slips' not in results:
                            results['packing_slips'] = []
                        results['packing_slips'].append({
                            'page': page_num,
                            'po_number': po_id,
                            'job_name': po_info.get('job_name', 'Unknown'),
                            'client_name': po_info.get('client_name'),
                            'order_number': order_number,
                            'vendor': vendor,
                            'filename': slip_filename
                        })
                    else:
                        print(f"  ⚠ Packing slip detected but could not match to any PO")
                        unmatched_filename = f"UNMATCHED_PACKSLIP_{timestamp}_page{page_num}.pdf"
                        unmatched_path = os.path.join(app.config['UPLOAD_FOLDER'], unmatched_filename)
                        pdf_writer = PyPDF2.PdfWriter()
                        pdf_writer.add_page(pdf_reader.pages[page_num - 1])
                        with open(unmatched_path, 'wb') as f:
                            pdf_writer.write(f)
                        results['unmatched'].append({
                            'page': page_num,
                            'text_preview': f"[PACKING SLIP] {text[:150]}",
                            'filename': unmatched_filename
                        })
                    continue  # Skip regular invoice processing for packing slips

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

            # Check if this is a Service PO (S-prefix) and needs job mapping
            po_info = po_map.get(po_id, {})
            job_name = po_info.get('job_name', 'Unknown')
            estimated_cost = po_info.get('estimated_cost', 0.00)

            # Format PO number to check if it starts with S
            po_number_formatted = format_po_number(po_id, job_name)
            new_job_name = None
            manual_review_flag = None

            if po_number_formatted.upper().startswith('S'):
                # Service PO - try to use extracted year from invoice
                invoice_year = invoice_data.get('invoice_year')

                if invoice_year:
                    # Check if Service YYYY job exists
                    service_job, error = get_service_job_for_year(invoice_year)
                    if service_job:
                        new_job_name = service_job
                        print(f"  ✅ Service PO {po_id} matched to {service_job} based on invoice year {invoice_year}")
                    else:
                        # Service job doesn't exist - return error, don't save this match
                        print(f"  ❌ {error}")
                        results['errors'].append({
                            'page': f"{group['pages'][0] + 1}",
                            'invoice_number': inv_num,
                            'cost': invoice_data['cost'],
                            'error': 'SERVICE JOB NOT FOUND',
                            'message': error,
                            'text_preview': f"Service PO {po_id} - Year {invoice_year}"
                        })
                        # Skip saving this match
                        continue
                else:
                    # No year found - flag for manual review
                    new_job_name = 'Service'
                    manual_review_flag = f"Service PO (ID {po_id}) needs manual review - invoice year could not be extracted. Please assign to appropriate Service job."
                    print(f"  ⚠ Service PO {po_id} flagged for manual review - no invoice year found")

            # Update database
            if new_job_name:
                # Service PO with job mapping
                c.execute("""UPDATE po_requests
                             SET invoice_filename=?, invoice_number=?, invoice_cost=?,
                                 invoice_date=?, invoice_upload_date=?, estimated_cost=?,
                                 match_method=?, status=?, job_name=?, manual_review_flag=?
                             WHERE id=?""",
                         (filename, inv_num, invoice_data['cost'], 'N/A',
                          datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                          float(invoice_data['cost']),
                          invoice_data.get('match_method', 'Unknown'), 'matched', new_job_name, manual_review_flag, po_id))
                job_name = new_job_name  # Update job_name for results
            else:
                # Normal PO - no job name change
                c.execute("""UPDATE po_requests
                             SET invoice_filename=?, invoice_number=?, invoice_cost=?,
                                 invoice_date=?, invoice_upload_date=?, estimated_cost=?,
                                 match_method=?, status=?
                             WHERE id=?""",
                         (filename, inv_num, invoice_data['cost'], 'N/A',
                          datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                          float(invoice_data['cost']),
                          invoice_data.get('match_method', 'Unknown'), 'matched', po_id))

            results['matched'] += 1

            client_name = po_info.get('client_name', '')
            results['details'].append({
                'page': f"{group['pages'][0] + 1}" + (f"-{group['pages'][-1] + 1}" if len(group['pages']) > 1 else ""),
                'po_number': po_id,
                'job_name': job_name,
                'client_name': client_name,
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
        packing_slip_count = len(results.get('packing_slips', []))
        msg_parts = [f'Processed {results["processed"]} pages.']
        if results['matched'] > 0:
            msg_parts.append(f'Matched {results["matched"]} invoice(s).')
        if packing_slip_count > 0:
            slip_details = []
            for slip in results.get('packing_slips', []):
                po_display = format_po_display(slip['po_number'], slip['job_name'], slip.get('client_name'))
                slip_details.append(f"PO {po_display} ({slip['job_name']})")
            msg_parts.append(f'Detected {packing_slip_count} packing slip(s) - delivery noted on: {", ".join(slip_details)}.')
        if error_count > 0:
            msg_parts.append(f'{error_count} invoice(s) found but NO MATCHING PO!')
        icon = '✅' if error_count == 0 else '⚠'
        results['message'] = f'{icon} {" ".join(msg_parts)}'

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


def extract_invoice_year(text):
    """
    Extract year from invoice text.
    Looks for common date patterns: "2026", "02/26/2026", "2/26/2026", etc.
    Returns year as integer (e.g., 2026) or None if not found.
    """
    if not text:
        return None

    # Patterns for year extraction (prioritized)
    year_patterns = [
        r'\b(20\d{2})\b',  # Any 4-digit year starting with 20
    ]

    for pattern in year_patterns:
        matches = re.findall(pattern, text)
        # Get the most recent year (highest number)
        if matches:
            years = [int(y) for y in matches]
            # Filter out unreasonable years (before 2000 or after current year + 5)
            valid_years = [y for y in years if 2000 <= y <= 2030]
            if valid_years:
                return max(valid_years)  # Return the latest year found

    return None


def get_service_job_for_year(year):
    """
    Check if a Service job exists for the given year. Auto-create if missing.
    Returns (job_name, error_message) tuple:
    - If found or created: ("Service YYYY", None)
    - If error: (None, error message)
    """
    if year is None:
        return None, "Cannot determine invoice year for Service job mapping"

    service_job_name = f"Service {year}"

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT job_name FROM jobs WHERE job_name=? AND active=1", (service_job_name,))
        result = c.fetchone()

        if result:
            conn.close()
            return service_job_name, None
        else:
            # Auto-create the Service job if it doesn't exist
            try:
                c.execute("""INSERT INTO jobs (job_name, active, created_date)
                            VALUES (?, 1, ?)""",
                         (service_job_name, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                conn.commit()
                print(f"   ✅ Auto-created Service job: {service_job_name}")
                conn.close()
                return service_job_name, None
            except Exception as create_err:
                conn.close()
                print(f"   ⚠ Failed to auto-create Service job: {create_err}")
                return None, f"Service {year} job could not be created: {str(create_err)}"
    except Exception as e:
        return None, f"Error checking for Service job: {str(e)}"


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
        r'CUSTOMER\s*#\s*INVOICE\s*#[\s\S]*?(\d{4,}[A-Z0-9\-]*)',  # SiteOne table format (4+ digits)
        r'INVOICE\s*#[\s:]*(\d{4,}[A-Z0-9\-]*)',  # Simple Invoice # format (4+ digits)
    ]

    for pattern in customer_invoice_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            if len(candidate) >= 4:  # Allow 4+ character invoice numbers
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
                # Allow 4+ character invoice numbers to catch more formats
                if candidate.lower() not in ['date', 'time', 'page'] and len(candidate) >= 4:
                    invoice_number = candidate
                    print(f"  ✅ Found Invoice Number ({desc}): {invoice_number}")
                    break
                else:
                    print(f"    Skipped '{candidate}' (too short or false positive)")

    if not invoice_number:
        # Last resort fallback: if page contains invoice-related keywords, try to find ANY 4-5 digit number
        if any(keyword in text.upper() for keyword in ['INVOICE', 'BILL', 'INVOICE AMOUNT', 'TOTAL AMOUNT', 'AMOUNT DUE']):
            print("  🔍 Invoice keywords detected but no number matched, trying fallback...")
            # Find first 4-5 digit number after an invoice keyword
            match = re.search(r'(?:INVOICE|BILL)[^\d]*(\d{4,5})', text, re.IGNORECASE)
            if match:
                candidate = match.group(1).strip()
                invoice_number = candidate
                print(f"  ✅ Found Invoice Number (fallback): {invoice_number}")
            else:
                print("  ❌ No invoice number found even with fallback")
                return None
        else:
            print("  ❌ No invoice number found and no invoice keywords detected")
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

                # Also check up to 5 lines to handle multi-row tables
                for i in range(2, min(5, len(lines))):
                    lines_to_check.append(lines[i])

                for line_idx, values_line in enumerate(lines_to_check):
                    if po_number:
                        break
                    print(f"    → Checking line {line_idx}: {values_line[:80]}")

                    # Extract ALL sequences that could be PO numbers
                    number_patterns = [
                        r'S\s*-?\s*(\d{4,})',    # S 6133, S-6133, S - 6133, or S6133 format (handle flexible spacing/dashes)
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
            (r'PO\s*#?\s*[:\s]*S\s*-?\s*(\d{4,})', 'PO: S formats with flexible spacing', 0),
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

    # METHOD 3: Direct search for S-prefixed PO numbers (Service jobs)
    if not po_number and po_map:
        print("\n  Method 3: Direct search for S-prefixed PO numbers")
        # Look for S followed by 4+ digits anywhere in the text
        s_po_matches = re.findall(r'S\s*-?\s*(\d{4,})', text, re.IGNORECASE)
        print(f"    Found S-format numbers: {s_po_matches}")

        for num_str in s_po_matches:
            try:
                candidate = int(num_str)
                print(f"    Testing S-format number: {candidate}")
                if candidate in po_map:
                    po_number = candidate
                    match_method = "S-format Direct Search"
                    print(f"      ✅ MATCHED! PO {po_number}")
                    break
                else:
                    print(f"      ⚠ {candidate} not in approved list")
            except ValueError:
                continue

    # METHOD 4: Direct search for known PO IDs from po_map
    if not po_number and po_map:
        print("\n  Method 4: Direct search for known PO IDs")
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

    # METHOD 5: Scan for any 4-digit numbers that match PO IDs in database
    if not po_number and po_map:
        print("\n  Method 5: Scan all 4-digit numbers for PO matches")
        # Find all 4-digit numbers in the text
        all_numbers = re.findall(r'\b(\d{4,5})\b', text)
        print(f"    Found numbers: {all_numbers}")

        for num_str in all_numbers:
            try:
                candidate = int(num_str)
                if candidate in po_map:
                    print(f"    ✓ Found matching PO: {candidate}")
                    po_number = candidate
                    match_method = "Number Scan"
                    print(f"      ✅ MATCHED! PO {po_number}")
                    break
            except ValueError:
                continue

    # METHOD 6: Fuzzy job name scanning - find job names in text and extract nearby PO numbers
    if not po_number and po_map:
        print("\n  Method 6: Fuzzy job name scanning")
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
        if po_map:
            print(f"   Available POs (without invoices): {sorted(po_map.keys())}")
        else:
            print(f"   ⚠ ERROR: No POs available! Check database for POs with status='awaiting_invoice' or 'approved'")
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

    # Extract invoice year for Service job mapping
    invoice_year = extract_invoice_year(text)
    if invoice_year:
        print(f"   Invoice Year: {invoice_year}")

    return {
        'po_id': po_number,
        'po_number': po_number,
        'invoice_number': invoice_number,
        'cost': cost,
        'match_method': match_method,
        'invoice_year': invoice_year
    }

MANAGE_TECHS_UNIFIED_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Manage Technicians</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px; }
        .header {
            background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1); display: flex;
            justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;
        }
        h1 { color: #333; font-size: 28px; }
        .btn {
            padding: 10px 20px; border-radius: 5px; text-decoration: none;
            font-weight: bold; border: none; cursor: pointer; font-size: 14px;
        }
        .btn-secondary { background: #6c757d; color: white; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-success { background: #28a745; color: white; }
        .columns-container {
            display: grid; grid-template-columns: 1fr 1fr; gap: 30px; margin-bottom: 20px;
        }
        .column {
            background: white; padding: 20px; border-radius: 10px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        .column h2 {
            padding-bottom: 15px; border-bottom: 3px solid;
            margin-bottom: 20px; font-size: 22px;
        }
        .service-column h2 { color: #007bff; border-color: #007bff; }
        .install-column h2 { color: #28a745; border-color: #28a745; }
        .add-form { display: flex; flex-direction: column; gap: 10px; margin-bottom: 25px; padding-bottom: 25px; border-bottom: 2px solid #eee; }
        .form-group { display: flex; flex-direction: column; gap: 5px; }
        .form-group label { font-weight: bold; color: #555; font-size: 13px; }
        .form-group input { padding: 10px; border: 2px solid #ddd; border-radius: 5px; font-size: 14px; }
        .form-group input:focus { outline: none; border-color: #007bff; }
        .add-form .btn { align-self: flex-start; }
        .tech-account {
            background: #f9f9f9; padding: 15px; border-radius: 8px; margin-bottom: 15px;
            border-left: 4px solid; cursor: pointer; transition: all 0.3s;
        }
        .service-column .tech-account { border-left-color: #007bff; }
        .install-column .tech-account { border-left-color: #28a745; }
        .tech-account:hover { background: #f0f7ff; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
        .tech-account h4 { font-size: 16px; margin-bottom: 8px; color: #333; }
        .tech-info {
            font-size: 12px; color: #666; margin-bottom: 5px; display: flex;
            justify-content: space-between; align-items: center;
        }
        .tech-creds {
            background: white; padding: 10px; border-radius: 4px; margin-top: 8px;
            font-size: 12px; font-family: monospace;
        }
        .tech-creds p { margin: 4px 0; }
        .code { background: #f0f0f0; padding: 2px 6px; border-radius: 3px; }
        .tech-buttons { display: flex; gap: 8px; margin-top: 10px; }
        .btn-view { background: #667eea; color: white; padding: 6px 12px; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; flex: 1; }
        .btn-delete { background: #dc3545; color: white; padding: 6px 12px; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; flex: 1; }
        .modal {
            display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0,0,0,0.5); z-index: 1000; overflow-y: auto;
        }
        .modal.open { display: block; }
        .modal-content {
            background: white; margin: 40px auto; padding: 30px; border-radius: 10px;
            max-width: 900px; max-height: 80vh; overflow-y: auto;
        }
        .modal-header {
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 20px; padding-bottom: 15px; border-bottom: 2px solid #ddd;
        }
        .modal-header h2 { color: #333; }
        .close-btn { background: #dc3545; color: white; border: none; padding: 8px 15px; border-radius: 5px; cursor: pointer; font-weight: bold; }
        .po-list { display: flex; flex-direction: column; gap: 15px; }
        .po-item {
            background: #f9f9f9; padding: 15px; border-radius: 8px; border-left: 4px solid #667eea;
        }
        .po-item h4 { color: #333; margin-bottom: 8px; }
        .po-meta { font-size: 12px; color: #666; }
        .no-pos { text-align: center; color: #999; padding: 40px 20px; font-style: italic; }
        @media (max-width: 1024px) {
            .columns-container { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>👷 Manage Technicians</h1>
        <div style="display: flex; gap: 8px;">
            <a href="{{ url_for('office_dashboard') }}" class="btn btn-secondary">← Dashboard</a>
            <a href="{{ url_for('logout') }}" class="btn btn-danger">Logout</a>
        </div>
    </div>

    <div class="columns-container">
        {# SERVICE TECHNICIANS COLUMN #}
        <div class="column service-column">
            <h2>📱 Service Technicians</h2>

            <div class="add-form">
                <div class="form-group">
                    <label>Full Name</label>
                    <input type="text" id="service-name" placeholder="e.g., John Smith">
                </div>
                <div class="form-group">
                    <label>Username</label>
                    <input type="text" id="service-username" placeholder="e.g., jsmith">
                </div>
                <div class="form-group">
                    <label>Password</label>
                    <input type="password" id="service-password" placeholder="Password">
                </div>
                <div class="form-group">
                    <label>Email (Optional)</label>
                    <input type="email" id="service-email" placeholder="email@example.com">
                </div>
                <button onclick="addTech('service')" class="btn btn-success">+ Add Service Tech</button>
            </div>

            <div>
                {% if service_techs %}
                    {% for tech in service_techs %}
                        <div class="tech-account" onclick="viewTechPOs({{ tech[0] }}, '{{ tech[2]|replace("'", "\\'") }}')">
                            <h4>{{ tech[2] }}</h4>
                            <div class="tech-info">
                                <span>📊 {{ tech_pos[tech[0]]|length }} PO(s)</span>
                                <span style="color: #999;">Added: {{ tech[4][:10] }}</span>
                            </div>
                            <div class="tech-creds">
                                <p><strong>User:</strong> <span class="code">{{ tech[1] }}</span></p>
                                <p><strong>Pass:</strong> <span class="code">{{ tech[6] }}</span></p>
                                {% if tech[3] %}<p><strong>Email:</strong> {{ tech[3] }}</p>{% endif %}
                            </div>
                            <div class="tech-buttons">
                                <button class="btn-view" onclick="event.stopPropagation(); viewTechPOs({{ tech[0] }}, '{{ tech[2]|replace("'", "\\'") }}')">📋 View POs</button>
                                <button class="btn-delete" onclick="event.stopPropagation(); deleteTech({{ tech[0] }}, '{{ tech[2]|replace("'", "\\'") }}')">🗑️ Delete</button>
                            </div>
                        </div>
                    {% endfor %}
                {% else %}
                    <p style="color: #999; text-align: center; padding: 40px;">No service technicians added yet</p>
                {% endif %}
            </div>
        </div>

        {# INSTALL TECHNICIANS COLUMN #}
        <div class="column install-column">
            <h2>🔧 Install Technicians</h2>

            <div class="add-form">
                <div class="form-group">
                    <label>Full Name</label>
                    <input type="text" id="install-name" placeholder="e.g., Jane Doe">
                </div>
                <div class="form-group">
                    <label>Username</label>
                    <input type="text" id="install-username" placeholder="e.g., jdoe">
                </div>
                <div class="form-group">
                    <label>Password</label>
                    <input type="password" id="install-password" placeholder="Password">
                </div>
                <div class="form-group">
                    <label>Email (Optional)</label>
                    <input type="email" id="install-email" placeholder="email@example.com">
                </div>
                <button onclick="addTech('install')" class="btn btn-success">+ Add Install Tech</button>
            </div>

            <div>
                {% if install_techs %}
                    {% for tech in install_techs %}
                        <div class="tech-account" onclick="viewTechPOs({{ tech[0] }}, '{{ tech[2]|replace("'", "\\'") }}')">
                            <h4>{{ tech[2] }}</h4>
                            <div class="tech-info">
                                <span>📊 {{ tech_pos[tech[0]]|length }} PO(s)</span>
                                <span style="color: #999;">Added: {{ tech[4][:10] }}</span>
                            </div>
                            <div class="tech-creds">
                                <p><strong>User:</strong> <span class="code">{{ tech[1] }}</span></p>
                                <p><strong>Pass:</strong> <span class="code">{{ tech[6] }}</span></p>
                                {% if tech[3] %}<p><strong>Email:</strong> {{ tech[3] }}</p>{% endif %}
                            </div>
                            <div class="tech-buttons">
                                <button class="btn-view" onclick="event.stopPropagation(); viewTechPOs({{ tech[0] }}, '{{ tech[2]|replace("'", "\\'") }}')">📋 View POs</button>
                                <button class="btn-delete" onclick="event.stopPropagation(); deleteTech({{ tech[0] }}, '{{ tech[2]|replace("'", "\\'") }}')">🗑️ Delete</button>
                            </div>
                        </div>
                    {% endfor %}
                {% else %}
                    <p style="color: #999; text-align: center; padding: 40px;">No install technicians added yet</p>
                {% endif %}
            </div>
        </div>
    </div>

    {# PO MODAL #}
    <div id="po-modal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h2 id="modal-title">PO History</h2>
                <button class="close-btn" onclick="closeTechPOs()">✕ Close</button>
            </div>
            <div id="po-list" class="po-list"></div>
        </div>
    </div>

    <script>
        // Store all techs data for modal display
        const allTechPos = {
            {% for tech_id, pos in tech_pos.items() %}
                {{ tech_id }}: {{ pos | tojson }},
            {% endfor %}
        };

        function addTech(techType) {
            const nameInput = document.getElementById(techType + '-name');
            const usernameInput = document.getElementById(techType + '-username');
            const passwordInput = document.getElementById(techType + '-password');
            const emailInput = document.getElementById(techType + '-email');

            const name = nameInput.value.trim();
            const username = usernameInput.value.trim();
            const password = passwordInput.value.trim();
            const email = emailInput.value.trim();

            if (!name || !username || !password) {
                alert('Please enter: Full Name, Username, and Password');
                return;
            }

            fetch('/add_tech', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    full_name: name,
                    username: username,
                    password: password,
                    email: email,
                    tech_type: techType
                })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    alert(data.message);
                    location.reload();
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }

        function deleteTech(userId, techName) {
            if (!confirm('Delete technician "' + techName + '"? Their PO history will not be deleted.')) return;
            fetch('/delete_tech', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: userId })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    location.reload();
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }

        function viewTechPOs(techId, techName) {
            const modal = document.getElementById('po-modal');
            const title = document.getElementById('modal-title');
            const listContainer = document.getElementById('po-list');

            title.textContent = 'PO History: ' + techName;

            const pos = allTechPos[techId] || [];
            if (pos.length === 0) {
                listContainer.innerHTML = '<p class="no-pos">No POs submitted yet by this technician</p>';
            } else {
                let html = '';
                pos.forEach(po => {
                    const poType = po[1] || 'legacy';
                    const prefix = poType === 'service' ? 'S' : (poType === 'install' ? 'I' : '');
                    const poNum = prefix ? prefix + String(po[0]).padStart(4, '0') : po[0];

                    let statusColor = '#856404';
                    if (po[3] === 'approved') statusColor = '#28a745';
                    else if (po[3] === 'denied') statusColor = '#dc3545';

                    html += `
                        <div class="po-item">
                            <h4>PO #${poNum} - ${po[2]}</h4>
                            <div class="po-meta">
                                <p><strong>Status:</strong> <span style="color: ${statusColor}; font-weight: bold;">${po[3]}</span></p>
                                <p><strong>Date:</strong> ${po[4] ? po[4].substring(0, 10) : 'N/A'}</p>
                                <p><strong>Type:</strong> ${poType.charAt(0).toUpperCase() + poType.slice(1)}</p>
                                ${po[5] ? '<p><strong>Cost:</strong> $' + parseFloat(po[5]).toFixed(2) + '</p>' : ''}
                            </div>
                        </div>
                    `;
                });
                listContainer.innerHTML = html;
            }

            modal.classList.add('open');
        }

        function closeTechPOs() {
            document.getElementById('po-modal').classList.remove('open');
        }

        // Close modal when clicking outside
        window.onclick = function(event) {
            const modal = document.getElementById('po-modal');
            if (event.target === modal) {
                modal.classList.remove('open');
            }
        };
    </script>
</body>
</html>
'''

MANAGE_TECHS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Manage Technicians</title>
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
        .btn-secondary { background: #6c757d; color: white; }
        .btn-danger { background: #dc3545; color: white; }
        .card {
            background: white; padding: 20px; border-radius: 10px;
            margin-bottom: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        .tech-type-buttons {
            display: flex; gap: 20px; justify-content: center; flex-wrap: wrap; margin: 30px 0;
        }
        .tech-btn {
            padding: 30px 40px; border-radius: 10px; text-decoration: none;
            font-weight: bold; border: none; cursor: pointer; font-size: 18px;
            box-shadow: 0 4px 10px rgba(0,0,0,0.15); transition: transform 0.2s, box-shadow 0.2s;
        }
        .tech-btn:hover { transform: translateY(-2px); box-shadow: 0 6px 15px rgba(0,0,0,0.2); }
        .btn-service { background: #007bff; color: white; }
        .btn-install { background: #28a745; color: white; }
        .icon { font-size: 36px; margin-bottom: 10px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>👷 Manage Technicians</h1>
        <div style="display: flex; gap: 8px; flex-wrap: wrap;">
            <a href="{{ url_for('office_dashboard') }}" class="btn btn-secondary">← Back to Dashboard</a>
            <a href="{{ url_for('logout') }}" class="btn btn-danger">Logout</a>
        </div>
    </div>

    <div class="card">
        <h2 style="color: #333; margin-bottom: 10px; text-align: center;">Manage Technician Teams</h2>
        <p style="color: #666; text-align: center; margin-bottom: 20px; font-size: 14px;">Select a team to manage technicians and their POs</p>

        <div class="tech-type-buttons">
            <a href="{{ url_for('manage_service_techs') }}" class="tech-btn btn-service">
                <div class="icon">📱</div>
                <div>Service Technicians</div>
                <div style="font-size: 12px; margin-top: 5px;">Manage service techs (S-prefix POs)</div>
            </a>
            <a href="{{ url_for('manage_install_techs') }}" class="tech-btn btn-install">
                <div class="icon">🔧</div>
                <div>Install Technicians</div>
                <div style="font-size: 12px; margin-top: 5px;">Manage install techs (I-prefix POs)</div>
            </a>
        </div>
    </div>
</body>
</html>
'''

MANAGE_SERVICE_TECHS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Manage Service Technicians</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px; }
        .header {
            background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1); display: flex;
            justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;
        }
        h1 { color: #007bff; font-size: 24px; }
        .btn {
            padding: 10px 20px; border-radius: 5px; text-decoration: none;
            font-weight: bold; border: none; cursor: pointer; font-size: 14px;
        }
        .btn-secondary { background: #6c757d; color: white; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-success { background: #28a745; color: white; }
        .card {
            background: white; padding: 20px; border-radius: 10px;
            margin-bottom: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        .tech-card {
            background: white; border-radius: 10px; margin-bottom: 15px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1); overflow: hidden;
        }
        .tech-header {
            background: #007bff; color: white; padding: 15px 20px;
            display: flex; justify-content: space-between; align-items: center;
            cursor: pointer;
        }
        .tech-header h3 { margin: 0; font-size: 18px; }
        .tech-body { padding: 20px; display: none; }
        .tech-body.open { display: block; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background: #007bff; color: white; }
        tr:hover { background: #f0f7ff; }
        .add-form { display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end; }
        .form-group { display: flex; flex-direction: column; flex: 1; min-width: 200px; }
        .form-group label { font-size: 13px; color: #666; margin-bottom: 5px; }
        .form-group input { padding: 8px; border: 2px solid #007bff; border-radius: 5px; font-size: 14px; }
        .form-group input:focus { outline: none; border-color: #0056b3; }
        .no-pos { color: #999; font-style: italic; padding: 10px 0; }
        .tech-stats { font-size: 13px; color: rgba(255,255,255,0.85); }
    </style>
</head>
<body>
    <div class="header">
        <h1>📱 Manage Service Technicians</h1>
        <div style="display: flex; gap: 8px; flex-wrap: wrap;">
            <a href="{{ url_for('manage_techs') }}" class="btn btn-secondary">← Back to Tech Management</a>
            <a href="{{ url_for('office_dashboard') }}" class="btn btn-secondary">Dashboard</a>
            <a href="{{ url_for('logout') }}" class="btn btn-danger">Logout</a>
        </div>
    </div>

    <div class="card">
        <h2 style="color: #007bff; margin-bottom: 15px;">Add New Service Technician</h2>
        <div class="add-form">
            <div class="form-group" style="flex: 0 0 auto; width: auto;">
                <label for="new-tech-name">Full Name</label>
                <input type="text" id="new-tech-name" placeholder="e.g., John Smith" style="min-width: 150px;">
            </div>
            <div class="form-group" style="flex: 0 0 auto; width: auto;">
                <label for="new-tech-username">Username</label>
                <input type="text" id="new-tech-username" placeholder="e.g., jsmith" style="min-width: 150px;">
            </div>
            <div class="form-group" style="flex: 0 0 auto; width: auto;">
                <label for="new-tech-password">Password</label>
                <input type="password" id="new-tech-password" placeholder="Password" style="min-width: 150px;">
            </div>
            <div class="form-group" style="flex: 0 0 auto; width: auto;">
                <label for="new-tech-email">Email (Optional)</label>
                <input type="email" id="new-tech-email" placeholder="email@example.com" style="min-width: 150px;">
            </div>
            <button onclick="addTech('service')" class="btn btn-success">+ Add Service Tech</button>
        </div>
    </div>

    <div class="card">
        <h2 style="color: #007bff; margin-bottom: 5px;">Service Technicians ({{ techs|length }})</h2>
        <p style="color: #666; margin-bottom: 20px; font-size: 14px;">Click a technician to see their PO history.</p>

        {% if techs %}
            {% for tech in techs %}
                <div class="tech-card" id="tech-card-{{ tech[0] }}">
                    <div class="tech-header" onclick="toggleTech({{ tech[0] }})">
                        <div>
                            <h3>{{ tech[2] }}</h3>
                            <div class="tech-stats">{{ tech_pos[tech[0]]|length }} PO(s) &nbsp;|&nbsp; Username: {{ tech[1] }} &nbsp;|&nbsp; Added: {{ tech[4][:10] }}</div>
                        </div>
                        <div style="display: flex; gap: 8px; align-items: center;">
                            <span id="icon-{{ tech[0] }}">▼</span>
                            <button onclick="event.stopPropagation(); deleteTech({{ tech[0] }}, '{{ tech[2]|replace("'", "\\'") }}')"
                                    class="btn btn-danger" style="padding: 6px 14px; font-size: 13px;">Delete</button>
                        </div>
                    </div>
                    <div class="tech-body" id="body-{{ tech[0] }}">
                        <div style="background: #f0f7ff; padding: 12px; border-radius: 5px; margin-bottom: 15px; border-left: 4px solid #007bff;">
                            <p style="color: #666; margin-bottom: 8px;"><strong>Username:</strong> <code style="background: white; padding: 2px 6px; border-radius: 3px;">{{ tech[1] }}</code></p>
                            <p style="color: #666; margin-bottom: 8px;"><strong>Password:</strong> <code style="background: white; padding: 2px 6px; border-radius: 3px;">{{ tech[6] }}</code></p>
                            <p style="color: #666; margin-bottom: 0;"><strong>Email:</strong> {{ tech[3] if tech[3] else "N/A" }}</p>
                        </div>
                        {% if tech_pos[tech[0]] %}
                            <table>
                                <thead>
                                    <tr>
                                        <th>PO #</th>
                                        <th>Job</th>
                                        <th>Status</th>
                                        <th>Date</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {% for po in tech_pos[tech[0]] %}
                                    <tr>
                                        <td><strong>{{ po[0] }}</strong></td>
                                        <td>{{ po[2] }}</td>
                                        <td>
                                            {% if po[3] == 'approved' %}
                                                <span style="color: #28a745; font-weight: bold;">Approved</span>
                                            {% elif po[3] == 'denied' %}
                                                <span style="color: #dc3545; font-weight: bold;">Denied</span>
                                            {% else %}
                                                <span style="color: #856404;">{{ po[3]|title }}</span>
                                            {% endif %}
                                        </td>
                                        <td>{{ po[4][:10] if po[4] else 'N/A' }}</td>
                                    </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        {% else %}
                            <p class="no-pos">No POs submitted yet for this technician.</p>
                        {% endif %}
                    </div>
                </div>
            {% endfor %}
        {% else %}
            <p style="color: #999; text-align: center; padding: 40px;">No service technicians added yet. Add one above!</p>
        {% endif %}
    </div>

<script>
    function toggleTech(id) {
        const body = document.getElementById('body-' + id);
        const icon = document.getElementById('icon-' + id);
        if (body.classList.contains('open')) {
            body.classList.remove('open');
            icon.textContent = '▼';
        } else {
            body.classList.add('open');
            icon.textContent = '▲';
        }
    }

    function addTech(techType) {
        const name = document.getElementById('new-tech-name').value.trim();
        const username = document.getElementById('new-tech-username').value.trim();
        const password = document.getElementById('new-tech-password').value.trim();
        const email = document.getElementById('new-tech-email').value.trim();

        if (!name || !username || !password) {
            alert('Please enter: Full Name, Username, and Password');
            return;
        }

        fetch('/add_tech', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                full_name: name,
                username: username,
                password: password,
                email: email,
                tech_type: techType
            })
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                alert(data.message);
                location.reload();
            } else {
                alert('Error: ' + data.error);
            }
        });
    }

    function deleteTech(id, name) {
        if (!confirm('Delete technician "' + name + '"? Their PO history will not be deleted.')) return;
        fetch('/delete_tech', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: id })
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                location.reload();
            } else {
                alert('Error: ' + data.error);
            }
        });
    }
</script>
</body>
</html>
'''

MANAGE_INSTALL_TECHS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Manage Install Technicians</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px; }
        .header {
            background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1); display: flex;
            justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;
        }
        h1 { color: #28a745; font-size: 24px; }
        .btn {
            padding: 10px 20px; border-radius: 5px; text-decoration: none;
            font-weight: bold; border: none; cursor: pointer; font-size: 14px;
        }
        .btn-secondary { background: #6c757d; color: white; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-success { background: #28a745; color: white; }
        .card {
            background: white; padding: 20px; border-radius: 10px;
            margin-bottom: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        .tech-card {
            background: white; border-radius: 10px; margin-bottom: 15px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1); overflow: hidden;
        }
        .tech-header {
            background: #28a745; color: white; padding: 15px 20px;
            display: flex; justify-content: space-between; align-items: center;
            cursor: pointer;
        }
        .tech-header h3 { margin: 0; font-size: 18px; }
        .tech-body { padding: 20px; display: none; }
        .tech-body.open { display: block; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background: #28a745; color: white; }
        tr:hover { background: #f0fff4; }
        .add-form { display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end; }
        .form-group { display: flex; flex-direction: column; flex: 1; min-width: 200px; }
        .form-group label { font-size: 13px; color: #666; margin-bottom: 5px; }
        .form-group input { padding: 8px; border: 2px solid #28a745; border-radius: 5px; font-size: 14px; }
        .form-group input:focus { outline: none; border-color: #1e7e34; }
        .no-pos { color: #999; font-style: italic; padding: 10px 0; }
        .tech-stats { font-size: 13px; color: rgba(255,255,255,0.85); }
    </style>
</head>
<body>
    <div class="header">
        <h1>🔧 Manage Install Technicians</h1>
        <div style="display: flex; gap: 8px; flex-wrap: wrap;">
            <a href="{{ url_for('manage_techs') }}" class="btn btn-secondary">← Back to Tech Management</a>
            <a href="{{ url_for('office_dashboard') }}" class="btn btn-secondary">Dashboard</a>
            <a href="{{ url_for('logout') }}" class="btn btn-danger">Logout</a>
        </div>
    </div>

    <div class="card">
        <h2 style="color: #28a745; margin-bottom: 15px;">Add New Install Technician</h2>
        <div class="add-form">
            <div class="form-group" style="flex: 0 0 auto; width: auto;">
                <label for="new-tech-name">Full Name</label>
                <input type="text" id="new-tech-name" placeholder="e.g., Jane Doe" style="min-width: 150px;">
            </div>
            <div class="form-group" style="flex: 0 0 auto; width: auto;">
                <label for="new-tech-username">Username</label>
                <input type="text" id="new-tech-username" placeholder="e.g., jdoe" style="min-width: 150px;">
            </div>
            <div class="form-group" style="flex: 0 0 auto; width: auto;">
                <label for="new-tech-password">Password</label>
                <input type="password" id="new-tech-password" placeholder="Password" style="min-width: 150px;">
            </div>
            <div class="form-group" style="flex: 0 0 auto; width: auto;">
                <label for="new-tech-email">Email (Optional)</label>
                <input type="email" id="new-tech-email" placeholder="email@example.com" style="min-width: 150px;">
            </div>
            <button onclick="addTech('install')" class="btn btn-success">+ Add Install Tech</button>
        </div>
    </div>

    <div class="card">
        <h2 style="color: #28a745; margin-bottom: 5px;">Install Technicians ({{ techs|length }})</h2>
        <p style="color: #666; margin-bottom: 20px; font-size: 14px;">Click a technician to see their PO history.</p>

        {% if techs %}
            {% for tech in techs %}
                <div class="tech-card" id="tech-card-{{ tech[0] }}">
                    <div class="tech-header" onclick="toggleTech({{ tech[0] }})">
                        <div>
                            <h3>{{ tech[2] }}</h3>
                            <div class="tech-stats">{{ tech_pos[tech[0]]|length }} PO(s) &nbsp;|&nbsp; Username: {{ tech[1] }} &nbsp;|&nbsp; Added: {{ tech[4][:10] }}</div>
                        </div>
                        <div style="display: flex; gap: 8px; align-items: center;">
                            <span id="icon-{{ tech[0] }}">▼</span>
                            <button onclick="event.stopPropagation(); deleteTech({{ tech[0] }}, '{{ tech[2]|replace("'", "\\'") }}')"
                                    class="btn btn-danger" style="padding: 6px 14px; font-size: 13px;">Delete</button>
                        </div>
                    </div>
                    <div class="tech-body" id="body-{{ tech[0] }}">
                        <div style="background: #f0fff4; padding: 12px; border-radius: 5px; margin-bottom: 15px; border-left: 4px solid #28a745;">
                            <p style="color: #666; margin-bottom: 8px;"><strong>Username:</strong> <code style="background: white; padding: 2px 6px; border-radius: 3px;">{{ tech[1] }}</code></p>
                            <p style="color: #666; margin-bottom: 8px;"><strong>Password:</strong> <code style="background: white; padding: 2px 6px; border-radius: 3px;">{{ tech[6] }}</code></p>
                            <p style="color: #666; margin-bottom: 0;"><strong>Email:</strong> {{ tech[3] if tech[3] else "N/A" }}</p>
                        </div>
                        {% if tech_pos[tech[0]] %}
                            <table>
                                <thead>
                                    <tr>
                                        <th>PO #</th>
                                        <th>Job</th>
                                        <th>Status</th>
                                        <th>Date</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {% for po in tech_pos[tech[0]] %}
                                    <tr>
                                        <td><strong>{{ po[0] }}</strong></td>
                                        <td>{{ po[2] }}</td>
                                        <td>
                                            {% if po[3] == 'approved' %}
                                                <span style="color: #28a745; font-weight: bold;">Approved</span>
                                            {% elif po[3] == 'denied' %}
                                                <span style="color: #dc3545; font-weight: bold;">Denied</span>
                                            {% else %}
                                                <span style="color: #856404;">{{ po[3]|title }}</span>
                                            {% endif %}
                                        </td>
                                        <td>{{ po[4][:10] if po[4] else 'N/A' }}</td>
                                    </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        {% else %}
                            <p class="no-pos">No POs submitted yet for this technician.</p>
                        {% endif %}
                    </div>
                </div>
            {% endfor %}
        {% else %}
            <p style="color: #999; text-align: center; padding: 40px;">No install technicians added yet. Add one above!</p>
        {% endif %}
    </div>

<script>
    function toggleTech(id) {
        const body = document.getElementById('body-' + id);
        const icon = document.getElementById('icon-' + id);
        if (body.classList.contains('open')) {
            body.classList.remove('open');
            icon.textContent = '▼';
        } else {
            body.classList.add('open');
            icon.textContent = '▲';
        }
    }

    function addTech(techType) {
        const name = document.getElementById('new-tech-name').value.trim();
        const username = document.getElementById('new-tech-username').value.trim();
        const password = document.getElementById('new-tech-password').value.trim();
        const email = document.getElementById('new-tech-email').value.trim();

        if (!name || !username || !password) {
            alert('Please enter: Full Name, Username, and Password');
            return;
        }

        fetch('/add_tech', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                full_name: name,
                username: username,
                password: password,
                email: email,
                tech_type: techType
            })
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                alert(data.message);
                location.reload();
            } else {
                alert('Error: ' + data.error);
            }
        });
    }

    function deleteTech(id, name) {
        if (!confirm('Delete technician "' + name + '"? Their PO history will not be deleted.')) return;
        fetch('/delete_tech', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: id })
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                location.reload();
            } else {
                alert('Error: ' + data.error);
            }
        });
    }
</script>
</body>
</html>
'''

JOB_MANAGEMENT_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Manage Jobs</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px; }
        .header { background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
        h1 { color: #333; font-size: 24px; }
        .btn { padding: 10px 20px; border-radius: 5px; text-decoration: none; font-weight: bold; border: none; cursor: pointer; font-size: 14px; }
        .btn-primary { background: #667eea; color: white; }
        .btn-secondary { background: #6c757d; color: white; }
        .btn-success { background: #28a745; color: white; }
        .btn-danger { background: #dc3545; color: white; }
        .card { background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
        .form-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 5px; font-weight: bold; color: #555; }
        input, select { width: 100%; padding: 10px; border: 2px solid #ddd; border-radius: 5px; font-size: 16px; }
        .filter-controls { background: #f0f4ff; padding: 20px; border-radius: 5px; margin-bottom: 20px; display: flex; gap: 15px; align-items: flex-end; flex-wrap: wrap; }
        .filter-group { flex: 1; min-width: 200px; }
        .filter-group label { color: #667eea; margin-bottom: 5px; }
        .filter-group input, .filter-group select { border: 2px solid #667eea; }
        .filter-stats { background: #e7f3ff; padding: 15px; border-radius: 5px; margin-bottom: 20px; display: flex; gap: 20px; flex-wrap: wrap; }
        .stat-item { flex: 1; min-width: 150px; }
        .stat-number { font-size: 24px; font-weight: bold; color: #667eea; }
        .stat-label { color: #666; font-size: 14px; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background: #667eea; color: white; font-weight: bold; }
        tr:hover { background: #f5f5f5; }
        .status-badge { padding: 5px 10px; border-radius: 20px; font-size: 12px; font-weight: bold; display: inline-block; }
        .status-active { background: #28a745; color: white; }
        .status-inactive { background: #dc3545; color: white; }
        .expandable-row { display: none; background: #f9f9f9; }
        .expandable-row.show { display: table-row; }
        .invoice-details { padding: 20px; background: white; border-radius: 5px; }
        .invoice-item { padding: 15px; background: #e7f3ff; margin: 10px 0; border-radius: 5px; border-left: 4px solid #667eea; }
        .expand-icon { transition: transform 0.3s; display: inline-block; }
        .expand-icon.rotated { transform: rotate(90deg); }
        .money-positive { color: #28a745; font-weight: bold; }
        .money-negative { color: #dc3545; font-weight: bold; }
        .budget-bar-container { width: 100%; background: #e9ecef; border-radius: 10px; overflow: hidden; height: 22px; position: relative; }
        .budget-bar { height: 100%; border-radius: 10px; transition: width 0.3s ease; }
        .budget-bar-label { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-size: 11px; font-weight: bold; color: #333; white-space: nowrap; text-shadow: 0 0 3px rgba(255,255,255,0.8); }
        .budget-green { background: #28a745; }
        .budget-yellow { background: #ffc107; }
        .budget-orange { background: #fd7e14; }
        .budget-red { background: #dc3545; }
        .budget-not-set { color: #999; font-style: italic; font-size: 12px; }
        .no-results { text-align: center; padding: 40px; color: #999; font-size: 16px; }
    </style>
    <script>
        // Jobs data will be loaded via API
        let jobsData = [];
        let jobsMap = {};  // Map job ID to job data
        let filteredYear = '';
        let filteredStatus = 'all';

        function escapeHtml(text) {
            const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
            return text.replace(/[&<>"']/g, m => map[m]);
        }

        function editJob(id, currentName, currentYear, currentBudget, currentJobCode, event) {
            if (event) event.stopPropagation();
            const newName = prompt('Edit job name:', currentName);
            if (!newName) return;
            const newYear = prompt('Edit year:', currentYear);
            if (!newYear) return;
            const newBudget = prompt('Edit Budget for Materials ($):', currentBudget || 0);
            if (newBudget === null) return;
            const newJobCode = prompt('Edit Job Code (e.g., CHASE, SVC):', currentJobCode || '');

            fetch('/edit_job', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ job_id: id, job_name: newName, year: parseInt(newYear), budget: parseFloat(newBudget) || 0, job_code: newJobCode })
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

        function toggleJob(id, event) {
            if (event) event.stopPropagation();
            if (!confirm('Toggle active status for this job?')) return;
            fetch('/toggle_job', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ job_id: id })
            })
            .then(response => response.json())
            .then(data => { if (data.success) location.reload(); else alert('Error: ' + data.error); });
        }

        function deleteJob(id, jobName, event) {
            if (event) event.stopPropagation();
            if (!confirm('Are you sure you want to DELETE "' + jobName + '"? This cannot be undone!')) return;
            fetch('/delete_job', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ job_id: id })
            })
            .then(response => response.json())
            .then(data => { if (data.success) location.reload(); else alert('Error: ' + data.error); });
        }

        function toggleJobDetails(jobId) {
            const detailsRow = document.getElementById('details-' + jobId);
            const icon = document.getElementById('icon-' + jobId);
            if (detailsRow.classList.contains('show')) {
                detailsRow.classList.remove('show');
                icon.classList.remove('rotated');
            } else {
                document.querySelectorAll('.expandable-row').forEach(row => row.classList.remove('show'));
                document.querySelectorAll('.expand-icon').forEach(ic => ic.classList.remove('rotated'));
                detailsRow.classList.add('show');
                icon.classList.add('rotated');
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
                    let html = '<h3 style="color: #667eea; margin-bottom: 15px;">Invoices for ' + escapeHtml(data.job_name) + '</h3>';
                    if (data.budget && data.budget > 0) {
                        const pct = data.budget_pct || 0;
                        const remaining = data.budget - data.total_invoiced;
                        const barColor = pct <= 50 ? 'budget-green' : pct <= 75 ? 'budget-yellow' : pct <= 100 ? 'budget-orange' : 'budget-red';
                        html += '<div style="background: #f0f4ff; padding: 15px; border-radius: 8px; margin-bottom: 15px; border: 2px solid #667eea;">';
                        html += '<strong style="color: #667eea;">Budget Summary</strong><br>';
                        html += '<span>Budget: $' + data.budget.toFixed(2) + ' | Spent: $' + data.total_invoiced.toFixed(2) + ' | Remaining: <strong class="' + (remaining >= 0 ? 'money-positive' : 'money-negative') + '">$' + remaining.toFixed(2) + '</strong></span><br>';
                        html += '<div class="budget-bar-container" style="height: 26px; margin-top: 10px;"><div class="budget-bar ' + barColor + '" style="width: ' + Math.min(pct, 100) + '%"></div><span class="budget-bar-label">' + pct + '% used</span></div>';
                        html += '</div>';
                    }
                    data.invoices.forEach(inv => {
                        const diff = inv.invoice_cost - inv.estimated;
                        const jobberNum = inv.jobber_invoice_number || '';
                        const poDisplay = data.job_code ? data.job_code + '-' + inv.po_id : inv.po_id;
                        html += '<div class="invoice-item"><strong>PO #' + poDisplay + '</strong> - ' + escapeHtml(inv.tech_name) + '<br>';
                        html += 'Invoice: ' + escapeHtml(inv.invoice_number) + ' | Estimated: $' + inv.estimated.toFixed(2) + ' | Actual: $' + inv.invoice_cost.toFixed(2);
                        html += ' | Diff: <span class="' + (diff > 0 ? 'money-negative' : 'money-positive') + '">$' + diff.toFixed(2) + '</span><br>';
                        html += '<div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid #ddd;">';
                        html += '<label style="margin-bottom: 5px; font-size: 13px; font-weight: bold; color: #555;">Jobber Invoice #:</label> ';
                        html += '<input type="text" id="jobber-inv-' + inv.po_id + '" value="' + escapeHtml(jobberNum) + '" placeholder="Enter Jobber Invoice #" style="width: 150px; padding: 5px; border: 1px solid #ddd; border-radius: 3px; font-size: 13px;">';
                        html += ' <button class="btn btn-primary" style="padding: 5px 10px; font-size: 12px;" onclick="saveJobberInvoice(' + inv.po_id + ')">Save</button>';
                        html += '</div>';
                        if (inv.filename && inv.filename !== 'MANUAL_ENTRY') html += '<a href="/view_invoice/' + inv.filename + '" target="_blank" style="color: #667eea; display: inline-block; margin-top: 8px;">View Invoice</a>';
                        html += '</div>';
                    });
                    container.innerHTML = html;
                } else {
                    container.innerHTML = '<p style="color: #dc3545;">Error: ' + data.error + '</p>';
                }
            });
        }

        function saveJobberInvoice(poId) {
            const input = document.getElementById('jobber-inv-' + poId);
            const jobberNumber = input.value.trim();

            fetch('/update_jobber_invoice/' + poId, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ jobber_invoice_number: jobberNumber })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    input.style.borderColor = '#28a745';
                    setTimeout(() => { input.style.borderColor = '#ddd'; }, 2000);
                } else {
                    alert('Error: ' + data.error);
                }
            })
            .catch(err => alert('Error saving: ' + err));
        }

        function applyFilters() {
            filteredYear = document.getElementById('year-filter').value;
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

        function showAllJobsAZ() {
            // Show all jobs (active and inactive) sorted alphabetically
            document.getElementById('year-filter').value = '';
            document.getElementById('status-filter').value = 'all';
            filteredYear = '';
            filteredStatus = 'all';
            renderTable();
        }

        function renderBudgetBar(budget, invoiced) {
            if (!budget || budget <= 0) return '<span class="budget-not-set">No budget set</span>';
            const pct = Math.min((invoiced / budget) * 100, 100);
            const displayPct = (invoiced / budget * 100).toFixed(1);
            const barColor = displayPct <= 50 ? 'budget-green' : displayPct <= 75 ? 'budget-yellow' : displayPct <= 100 ? 'budget-orange' : 'budget-red';
            const label = invoiced > budget ? displayPct + '% - OVER by $' + (invoiced - budget).toFixed(2) : displayPct + '% used';
            return '<div class="budget-bar-container"><div class="budget-bar ' + barColor + '" style="width: ' + pct + '%"></div><span class="budget-bar-label">' + label + '</span></div><div style="font-size: 11px; color: #666; margin-top: 3px;">$' + invoiced.toFixed(2) + ' / $' + budget.toFixed(2) + '</div>';
        }

        function renderTable() {
            console.log('[DEBUG] renderTable called with jobsData:', jobsData);
            const tbody = document.getElementById('jobs-tbody');
            const statsDiv = document.getElementById('filter-stats');

            let filtered = jobsData;
            if (filteredYear) filtered = filtered.filter(job => job[2].toString() === filteredYear);
            if (filteredStatus === 'active') filtered = filtered.filter(job => job[4] == 1);
            else if (filteredStatus === 'inactive') filtered = filtered.filter(job => job[4] == 0);

            filtered.sort((a, b) => {
                const nameA = (a[1] || '').toLowerCase();
                const nameB = (b[1] || '').toLowerCase();
                return nameA.localeCompare(nameB);
            });

            const totalJobs = filtered.length;
            const activeJobs = filtered.filter(j => j[4] == 1).length;
            const totalInvoiced = filtered.reduce((sum, j) => sum + (parseFloat(j[5]) || 0), 0);
            const totalBudget = filtered.reduce((sum, j) => sum + (j[9] || 0), 0);
            const overallPct = totalBudget > 0 ? ((totalInvoiced / totalBudget) * 100).toFixed(1) : 'N/A';

            statsDiv.innerHTML = '<div class="stat-item"><div class="stat-number">' + totalJobs + '</div><div class="stat-label">Total Jobs</div></div>' +
                '<div class="stat-item"><div class="stat-number">' + activeJobs + '</div><div class="stat-label">Active Jobs</div></div>' +
                '<div class="stat-item"><div class="stat-number">$' + totalBudget.toFixed(2) + '</div><div class="stat-label">Total Budget</div></div>' +
                '<div class="stat-item"><div class="stat-number">$' + totalInvoiced.toFixed(2) + '</div><div class="stat-label">Total Invoiced</div></div>' +
                '<div class="stat-item"><div class="stat-number">' + overallPct + (overallPct !== 'N/A' ? '%' : '') + '</div><div class="stat-label">% Budget Used</div></div>';

            if (filtered.length === 0) {
                const hasFilter = filteredYear !== '' || filteredStatus !== 'all';
                tbody.innerHTML = '<tr><td colspan="9" class="no-results">' + (hasFilter ? 'No jobs match filters. <button onclick="clearFilters()" class="btn btn-primary" style="margin-left:10px;">Show All</button>' : 'No jobs yet. Use the form above.') + '</td></tr>';
                return;
            }

            // Rebuild jobsMap
            jobsMap = {};
            filtered.forEach(job => {
                jobsMap[job[0]] = job;
            });

            let html = '';
            filtered.forEach(job => {
                const id = job[0];
                const budget = parseFloat(job[9]) || 0;
                const invoiced = parseFloat(job[5]) || 0;
                const jobName = job[1] || '';
                const isActive = job[4] == 1;
                const htmlEscapedName = escapeHtml(jobName);

                html += '<tr class="job-row" data-job-id="' + id + '">';
                html += '<td><span class="expand-icon" id="icon-' + id + '">▶</span></td>';
                html += '<td><strong>' + htmlEscapedName + '</strong></td>';
                html += '<td>' + job[2] + '</td>';
                html += '<td>' + job[8] + ' POs (' + job[6] + ' invoiced)</td>';
                html += '<td>' + (budget > 0 ? '$' + budget.toFixed(2) : '<span class="budget-not-set">Not set</span>') + '</td>';
                html += '<td>$' + invoiced.toFixed(2) + '</td>';
                html += '<td style="min-width: 180px;">' + renderBudgetBar(budget, invoiced) + '</td>';
                html += '<td><span class="status-badge ' + (isActive ? 'status-active' : 'status-inactive') + '">' + (isActive ? 'Active' : 'Inactive') + '</span></td>';
                html += '<td><button class="edit-btn btn btn-primary" data-id="' + id + '">Edit</button>';
                html += '<button class="toggle-btn btn btn-secondary" data-id="' + id + '">' + (isActive ? 'Deactivate' : 'Activate') + '</button>';
                html += '<button class="delete-btn btn btn-danger" data-id="' + id + '">Delete</button></td></tr>';
                html += '<tr class="expandable-row" id="details-' + id + '"><td colspan="9"><div class="invoice-details" id="invoice-container-' + id + '"></div></td></tr>';
            });

            tbody.innerHTML = html;

            // Add event listeners
            document.querySelectorAll('.edit-btn').forEach(btn => {
                btn.addEventListener('click', function(e) {
                    e.stopPropagation();
                    const id = parseInt(this.dataset.id);
                    const job = jobsMap[id];
                    if (job) editJob(id, job[1], job[2], job[9], job[10], e);
                });
            });

            document.querySelectorAll('.toggle-btn').forEach(btn => {
                btn.addEventListener('click', function(e) {
                    e.stopPropagation();
                    const id = parseInt(this.dataset.id);
                    toggleJob(id, e);
                });
            });

            document.querySelectorAll('.delete-btn').forEach(btn => {
                btn.addEventListener('click', function(e) {
                    e.stopPropagation();
                    const id = parseInt(this.dataset.id);
                    const job = jobsMap[id];
                    if (job) deleteJob(id, job[1], e);
                });
            });

            document.querySelectorAll('.job-row').forEach(row => {
                row.addEventListener('click', function(e) {
                    if (!e.target.closest('button')) {
                        const id = parseInt(this.dataset.jobId);
                        toggleJobDetails(id);
                    }
                });
            });
        }

        function populateYearFilter() {
            const years = [...new Set(jobsData.map(j => j[2]))].sort((a, b) => b - a);
            const sel = document.getElementById('year-filter');
            sel.innerHTML = '<option value="">All Years</option>';
            years.forEach(yr => {
                const opt = document.createElement('option');
                opt.value = yr;
                opt.textContent = yr;
                sel.appendChild(opt);
            });
        }

        function initPage() {
            console.log('[DEBUG] initPage called - fetching jobs data from API');
            // Fetch jobs data from the API
            fetch('/api/get_jobs')
                .then(response => {
                    if (!response.ok) throw new Error('Failed to fetch jobs');
                    return response.json();
                })
                .then(data => {
                    jobsData = data;
                    console.log('[DEBUG] Jobs data loaded:', jobsData);
                    console.log('[DEBUG] jobsData length:', jobsData ? jobsData.length : 'undefined');
                    try {
                        populateYearFilter();
                        document.getElementById('year-filter').value = '';
                        document.getElementById('status-filter').value = 'all';
                        filteredYear = '';
                        filteredStatus = 'all';
                        renderTable();
                        console.log('[DEBUG] initPage completed successfully');
                    } catch (error) {
                        console.error('[DEBUG] Error initializing page:', error);
                    }
                })
                .catch(error => {
                    console.error('[DEBUG] Error fetching jobs:', error);
                    document.getElementById('jobs-tbody').innerHTML = '<tr><td colspan="9" style="text-align: center; color: #dc3545; padding: 40px;">Error loading jobs. Please refresh the page.</td></tr>';
                });
        }

        window.addEventListener('DOMContentLoaded', initPage);
        window.addEventListener('pageshow', initPage);
    </script>
</head>
<body>
    <div class="header">
        <h1>📋 Manage Jobs</h1>
        <div style="display: flex; gap: 8px; flex-wrap: wrap;">
            <a href="{{ url_for('office_dashboard') }}" class="btn btn-secondary">← Dashboard</a>
            <a href="{{ url_for('manage_techs') }}" style="background: #fd7e14; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; font-weight: bold;">👷 Manage Techs</a>
            <a href="{{ url_for('logout') }}" class="btn btn-danger">Logout</a>
        </div>
    </div>

    {% with messages = get_flashed_messages() %}
    {% if messages %}
        {% for message in messages %}
        <div style="padding: 15px 20px; border-radius: 8px; margin-bottom: 15px; font-weight: bold; font-size: 15px; {% if 'Error' in message or 'error' in message %}background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb;{% else %}background: #d4edda; color: #155724; border: 1px solid #c3e6cb;{% endif %}">
            {{ message }}
        </div>
        {% endfor %}
    {% endif %}
    {% endwith %}

    <div class="card">
        <h2 style="color: #667eea; margin-bottom: 20px;">Add New Job</h2>
        <p style="color: #888; font-size: 13px; margin-bottom: 15px;">Note: each job name must be unique.</p>
        <form method="POST" action="/add_job">
            <div class="form-group">
                <label>Job Name</label>
                <input type="text" name="job_name" placeholder="e.g., Chase Bank" required>
            </div>
            <div class="form-group">
                <label>Year</label>
                <input type="number" name="year" value="2026" required>
            </div>
            <div class="form-group">
                <label>Budget for Materials ($)</label>
                <input type="number" name="budget" placeholder="0" step="0.01" min="0" value="0">
            </div>
            <button type="submit" class="btn btn-success" style="font-size: 16px; padding: 12px 24px;">+ Add Job</button>
        </form>
    </div>

    <div class="card">
        <h2 style="color: #667eea; margin-bottom: 20px;">Jobs</h2>
        <div class="filter-controls">
            <div class="filter-group">
                <label>Filter by Year</label>
                <select id="year-filter" onchange="applyFilters()"><option value="">All Years</option></select>
            </div>
            <div class="filter-group">
                <label>Filter by Status</label>
                <select id="status-filter" onchange="applyFilters()">
                    <option value="all">All Jobs</option>
                    <option value="active">Active Only</option>
                    <option value="inactive">Inactive Only</option>
                </select>
            </div>
            <div class="filter-group"><label>&nbsp;</label><button onclick="clearFilters()" class="btn btn-secondary" style="width: 100%;">Show All</button></div>
            <div class="filter-group"><label>&nbsp;</label><button onclick="showAllJobsAZ()" class="btn btn-primary" style="width: 100%; background: #28a745;">📋 Show all jobs A-Z</button></div>
        </div>
        <div class="filter-stats" id="filter-stats"></div>
        <div style="overflow-x: auto;">
            <table>
                <thead>
                    <tr><th width="30"></th><th>Job Name</th><th>Year</th><th>POs</th><th>Budget</th><th>Invoiced</th><th>% Used</th><th>Status</th><th>Actions</th></tr>
                </thead>
                <tbody id="jobs-tbody"></tbody>
            </table>
        </div>
    </div>

    <div class="card" style="background: #f0f8ff; border-left: 4px solid #28a745;">
        <h2 style="color: #28a745; margin-bottom: 15px;">💾 Database Backups</h2>
        <p style="color: #666; margin-bottom: 15px;">Create and manage backups of your database.</p>
        <div style="display: flex; gap: 15px; flex-wrap: wrap; margin-bottom: 20px;">
            <button onclick="createBackup()" class="btn btn-success" style="background: #28a745;">💾 Create Backup Now</button>
            <button onclick="loadBackupsList()" class="btn btn-primary">📂 View Backups</button>
        </div>
        <div id="backups-container" style="display: none;">
            <h3 style="color: #333; margin-bottom: 10px;">Available Backups</h3>
            <div id="backups-list" style="background: white; padding: 15px; border-radius: 5px; max-height: 400px; overflow-y: auto;">
                <p style="text-align: center; color: #999;">Loading backups...</p>
            </div>
        </div>
        <div id="backup-status" style="margin-top: 15px; display: none; padding: 15px; border-radius: 5px; background: #d4edda; color: #155724; border: 1px solid #c3e6cb;"></div>
    </div>

    <script>
        function createBackup() {
            const statusDiv = document.getElementById('backup-status');
            statusDiv.textContent = 'Creating backup...';
            statusDiv.style.display = 'block';
            statusDiv.style.background = '#e7f3ff';
            statusDiv.style.color = '#004085';

            fetch('/backup_database', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    statusDiv.textContent = '✓ ' + data.message;
                    statusDiv.style.background = '#d4edda';
                    statusDiv.style.color = '#155724';
                    setTimeout(() => loadBackupsList(), 1000);
                } else {
                    statusDiv.textContent = '✗ Error: ' + data.error;
                    statusDiv.style.background = '#f8d7da';
                    statusDiv.style.color = '#721c24';
                }
            })
            .catch(err => {
                statusDiv.textContent = '✗ Error: ' + err;
                statusDiv.style.background = '#f8d7da';
                statusDiv.style.color = '#721c24';
            });
        }

        function loadBackupsList() {
            const container = document.getElementById('backups-container');
            const list = document.getElementById('backups-list');
            container.style.display = 'block';
            list.innerHTML = '<p style="text-align: center; color: #999;">Loading backups...</p>';

            fetch('/list_backups')
            .then(r => r.json())
            .then(backups => {
                if (backups.length === 0) {
                    list.innerHTML = '<p style="text-align: center; color: #999;">No backups yet. Create one using the button above.</p>';
                    return;
                }

                let html = '<table style="width: 100%; border-collapse: collapse;">';
                html += '<tr style="background: #f0f0f0; font-weight: bold;"><td style="padding: 8px; border-bottom: 1px solid #ddd;">Filename</td><td style="padding: 8px; border-bottom: 1px solid #ddd;">Size</td><td style="padding: 8px; border-bottom: 1px solid #ddd;">Created</td><td style="padding: 8px; border-bottom: 1px solid #ddd;">Action</td></tr>';

                backups.forEach(backup => {
                    html += '<tr style="border-bottom: 1px solid #ddd;"><td style="padding: 8px;"><code style="background: #f5f5f5; padding: 2px 6px; border-radius: 3px; font-size: 12px;">' + backup.filename + '</code></td>';
                    html += '<td style="padding: 8px;">' + backup.size_mb + ' MB</td>';
                    html += '<td style="padding: 8px; font-size: 12px;">' + backup.mtime_str + '</td>';
                    html += '<td style="padding: 8px;"><a href="/download_backup/' + backup.filename + '" class="btn btn-primary" style="padding: 5px 10px; font-size: 12px; text-decoration: none; display: inline-block;">⬇️ Download</a></td></tr>';
                });
                html += '</table>';
                list.innerHTML = html;
            })
            .catch(err => {
                list.innerHTML = '<p style="color: #dc3545;">Error loading backups: ' + err + '</p>';
            });
        }
    </script>
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
        {% if tech_type == 'service' %}
            <h1>📱 Service Technician Dashboard - {{ full_name }}</h1>
        {% else %}
            <h1>🔧 Install Technician Dashboard - {{ full_name }}</h1>
        {% endif %}
        <a href="{{ url_for('logout') }}" class="logout-btn">Logout</a>
    </div>

    {% with messages = get_flashed_messages() %}
        {% if messages %}
            {% for message in messages %}
                {% if message.startswith('PO#') and '|' in message %}
                    {% set parts = message.split('|') %}
                    {% set po_num = parts[0] %}
                    {% set job_nm = parts[1] %}
                    <div style="background: #28a745; color: white; padding: 25px; border-radius: 10px; margin-bottom: 20px; text-align: center; box-shadow: 0 4px 12px rgba(40,167,69,0.4);">
                        <div style="font-size: 28px; font-weight: bold; margin-bottom: 8px;">PO SUBMITTED!</div>
                        <div style="font-size: 42px; font-weight: bold; letter-spacing: 2px; margin: 10px 0;">{{ po_num }}</div>
                        <div style="font-size: 22px; margin-bottom: 12px;">Job: <strong>{{ job_nm }}</strong></div>
                        <div style="font-size: 18px; background: rgba(0,0,0,0.2); padding: 12px; border-radius: 8px; margin-top: 10px;">
                            Use <strong>{{ po_num }}</strong> when placing your order at the store
                        </div>
                    </div>
                {% elif 'ERROR' in message or '❌' in message %}
                    <div class="error-message">{{ message }}</div>
                {% else %}
                    <div class="success">{{ message }}</div>
                {% endif %}
            {% endfor %}
        {% endif %}
    {% endwith %}

    <div class="card">
        {% if tech_type == 'service' %}
            <h2>📝 Submit New Service PO Request <span style="background: #007bff; color: white; padding: 5px 12px; border-radius: 20px; font-size: 12px; font-weight: bold; margin-left: 10px;">PO Prefix: S</span></h2>
        {% else %}
            <h2>📝 Submit New Install PO Request <span style="background: #28a745; color: white; padding: 5px 12px; border-radius: 20px; font-size: 12px; font-weight: bold; margin-left: 10px;">PO Prefix: I</span></h2>
        {% endif %}
        <form method="POST" action="{{ url_for('submit_request') }}">
            {# Auto-populate tech_name from the logged-in user's full_name #}
            <input type="hidden" name="tech_name" value="{{ full_name }}">

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
                <small id="job_hint" style="color: #666; display: block; margin-top: 5px;">💡 Type to search active jobs - auto-corrects misspellings</small>
            </div>

            <div class="form-group" id="client_name_field" style="display: none;">
                <label>Client Name (if Service) <span style="color: red;">*</span></label>
                <input type="text" id="client_name" name="client_name" placeholder="e.g., Somerville, Heron's Glen, Reserve" style="display: none;">
                <small style="color: #666; display: block; margin-top: 5px;">📍 Enter the client/location name for this service (e.g., Somerville, Heron's Glen, etc.)</small>
            </div>

            <div class="form-group">
                <label>Store Name</label>
                <input type="text" name="store_name" required placeholder="e.g., Home Depot, Lowes">
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

    // No substring matches - try fuzzy matching for auto-correction
    if (matches.length === 0) {
        // Client-side fuzzy matching using Levenshtein distance
        const fuzzyMatches = allJobs.map(job => {
            const score = fuzzyMatchScore(query, job.name);
            return { ...job, score: score };
        }).filter(job => job.score >= 0.55)
          .sort((a, b) => b.score - a.score)
          .slice(0, 5);

        if (fuzzyMatches.length > 0) {
            const bestMatch = fuzzyMatches[0];

            // If very high confidence (>= 0.80), auto-correct immediately
            if (bestMatch.score >= 0.80) {
                console.log('🔧 Auto-correcting to:', bestMatch.name, '(score:', bestMatch.score, ')');
                this.value = bestMatch.name;
                this.style.borderColor = '#28a745';
                suggestionsDiv.style.display = 'none';
                validJobSelected = true;
                if (hintText) {
                    hintText.innerHTML = `🔧 Auto-corrected to: ${bestMatch.name} (${bestMatch.year})`;
                    hintText.style.color = '#28a745';
                }
                return;
            }

            // Otherwise show fuzzy suggestions with "Did you mean?" prompt
            let html = '<div style="padding: 8px 15px; color: #856404; background: #fff3cd; border-bottom: 1px solid #ffc107; font-size: 13px;">🔧 Did you mean one of these?</div>';
            fuzzyMatches.forEach(job => {
                const confidence = Math.round(job.score * 100);
                html += `<div class="job-suggestion-item" onclick="selectJob('${job.name.replace(/'/g, "\\'")}')">`;
                html += `${job.name} <span style="color: #999;">(${job.year})</span>`;
                html += `<span style="float: right; color: #28a745; font-size: 12px;">${confidence}% match</span>`;
                html += '</div>';
            });
            suggestionsDiv.innerHTML = html;
            suggestionsDiv.style.display = 'block';
            this.style.borderColor = '#ffc107'; // Yellow for "close match"
            if (hintText) {
                hintText.innerHTML = '🔧 No exact match - showing closest matches. Click to select.';
                hintText.style.color = '#856404';
            }
            return;
        }

        // Truly no matches at all
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

            // Close suggestions when clicking outside
            document.addEventListener('click', function(e) {
                if (!searchInput.contains(e.target) && !suggestionsDiv.contains(e.target)) {
                    suggestionsDiv.style.display = 'none';
                }
            });

            // Handle keyboard navigation (Enter key) with fuzzy auto-correct
            searchInput.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') {
                    const currentValue = this.value.trim();
                    if (!currentValue) return;

                    const exactMatch = allJobs.find(job =>
                        job.name.toLowerCase() === currentValue.toLowerCase()
                    );

                    if (exactMatch) {
                        selectJob(exactMatch.name);
                        e.preventDefault();
                    } else {
                        // Try fuzzy auto-correct on Enter
                        const fuzzyMatches = allJobs.map(job => ({
                            ...job,
                            score: fuzzyMatchScore(currentValue, job.name)
                        })).filter(job => job.score >= 0.70)
                          .sort((a, b) => b.score - a.score);

                        if (fuzzyMatches.length > 0) {
                            e.preventDefault();
                            selectJob(fuzzyMatches[0].name);
                            if (hintText) {
                                hintText.innerHTML = `🔧 Auto-corrected to: ${fuzzyMatches[0].name} (${fuzzyMatches[0].year})`;
                                hintText.style.color = '#28a745';
                            }
                        }
                    }
                }
            });

            // Auto-correct on blur (when user clicks away from the field)
            searchInput.addEventListener('blur', function() {
                const currentValue = this.value.trim();
                if (!currentValue) return;

                // Already a valid job? No action needed
                const exactMatch = allJobs.find(job =>
                    job.name.toLowerCase() === currentValue.toLowerCase()
                );
                if (exactMatch) {
                    this.value = exactMatch.name;
                    this.style.borderColor = '#28a745';
                    validJobSelected = true;
                    return;
                }

                // Try fuzzy auto-correct
                const fuzzyMatches = allJobs.map(job => ({
                    ...job,
                    score: fuzzyMatchScore(currentValue, job.name)
                })).filter(job => job.score >= 0.70)
                  .sort((a, b) => b.score - a.score);

                if (fuzzyMatches.length > 0) {
                    const bestMatch = fuzzyMatches[0];
                    console.log('🔧 Blur auto-correct:', currentValue, '->', bestMatch.name, '(score:', bestMatch.score, ')');
                    this.value = bestMatch.name;
                    this.style.borderColor = '#28a745';
                    validJobSelected = true;
                    suggestionsDiv.style.display = 'none';
                    if (hintText) {
                        hintText.innerHTML = `🔧 Auto-corrected to: ${bestMatch.name} (${bestMatch.year})`;
                        hintText.style.color = '#28a745';
                    }
                }
            });
    });

    // ---- Fuzzy matching functions (client-side Levenshtein) ----
    function levenshteinDistance(s1, s2) {
        if (s1.length < s2.length) return levenshteinDistance(s2, s1);
        if (s2.length === 0) return s1.length;

        let previousRow = Array.from({length: s2.length + 1}, (_, i) => i);
        for (let i = 0; i < s1.length; i++) {
            let currentRow = [i + 1];
            for (let j = 0; j < s2.length; j++) {
                const insertions = previousRow[j + 1] + 1;
                const deletions = currentRow[j] + 1;
                const substitutions = previousRow[j] + (s1[i] !== s2[j] ? 1 : 0);
                currentRow.push(Math.min(insertions, deletions, substitutions));
            }
            previousRow = currentRow;
        }
        return previousRow[previousRow.length - 1];
    }

    function fuzzyMatchScore(text1, text2) {
        if (!text1 || !text2) return 0;
        const t1 = text1.toUpperCase().replace(/[^\w\s]/g, '').replace(/\s+/g, ' ').trim();
        const t2 = text2.toUpperCase().replace(/[^\w\s]/g, '').replace(/\s+/g, ' ').trim();
        if (!t1 || !t2) return 0;
        if (t1 === t2) return 1.0;

        const t1NoSpace = t1.replace(/\s/g, '');
        const t2NoSpace = t2.replace(/\s/g, '');
        if (t1NoSpace === t2NoSpace) return 0.98;

        const longer = t1NoSpace.length >= t2NoSpace.length ? t1NoSpace : t2NoSpace;
        const shorter = t1NoSpace.length >= t2NoSpace.length ? t2NoSpace : t1NoSpace;
        if (longer.length === 0) return 0;

        const distance = levenshteinDistance(shorter, longer);
        return Math.max(0, 1.0 - (distance / longer.length));
    }

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

        // Show/hide client name field if Service job is selected
        const clientNameField = document.getElementById('client_name_field');
        const clientNameInput = document.getElementById('client_name');
        if (selectedJob && selectedJob.name.toLowerCase().includes('service')) {
            if (clientNameField) clientNameField.style.display = 'block';
            if (clientNameInput) {
                clientNameInput.style.display = 'block';
                clientNameInput.required = true;
            }
        } else {
            if (clientNameField) clientNameField.style.display = 'none';
            if (clientNameInput) {
                clientNameInput.style.display = 'none';
                clientNameInput.required = false;
                clientNameInput.value = '';
            }
        }

        console.log('✓ Selected:', jobName);
    }

    function clearJobName() {
        const searchInput = document.getElementById('job_search');
        const clearBtn = document.getElementById('clear-job');
        const hintText = document.getElementById('job_hint');
        const clientNameField = document.getElementById('client_name_field');
        const clientNameInput = document.getElementById('client_name');

        searchInput.value = '';
        searchInput.style.borderColor = '#ddd';
        validJobSelected = false;
        if (clearBtn) clearBtn.style.display = 'none';
        if (hintText) {
            hintText.innerHTML = `💡 ${allJobs.length} active jobs available - start typing to search`;
            hintText.style.color = '#666';
        }
        if (clientNameField) clientNameField.style.display = 'none';
        if (clientNameInput) {
            clientNameInput.value = '';
            clientNameInput.required = false;
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
                    // Try fuzzy auto-correction before rejecting
                    const fuzzyMatches = allJobs.map(job => ({
                        ...job,
                        score: fuzzyMatchScore(jobName, job.name)
                    })).filter(job => job.score >= 0.70)
                      .sort((a, b) => b.score - a.score);

                    if (fuzzyMatches.length > 0) {
                        // Auto-correct to the best fuzzy match
                        const bestMatch = fuzzyMatches[0];
                        console.log('🔧 Form submit: auto-correcting to', bestMatch.name, '(score:', bestMatch.score, ')');
                        jobInput.value = bestMatch.name;
                        jobInput.style.borderColor = '#28a745';
                        validJobSelected = true;

                        const hintText = document.getElementById('job_hint');
                        if (hintText) {
                            hintText.innerHTML = `🔧 Auto-corrected to: ${bestMatch.name} (${bestMatch.year})`;
                            hintText.style.color = '#28a745';
                        }
                        // Allow the form to submit with the corrected name
                        return true;
                    }

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
                    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 8px; flex-wrap: wrap;">
                        <div style="background: #28a745; color: white; padding: 6px 16px; border-radius: 20px; font-size: 18px; font-weight: bold; letter-spacing: 1px;">
                            PO #{{ format_po_number(req[0], req[3]) }}
                        </div>
                        <div style="font-size: 16px; color: #333; font-weight: bold;">{{ req[3] }}</div>
                    </div>
                    <p><strong>Store:</strong> {{ req[4] }}</p>
                    <p><strong>Estimated Amount:</strong> ${{ "%.2f"|format(req[5]) }}</p>
                    <p><strong>Description:</strong> {{ req[6] }}</p>
                    <p><strong>Submitted:</strong> {{ req[8] }}</p>

                    {% if req[7] == 'denied' %}
                        <span class="status denied">DENIED</span>
                        {% if req[10] %}
                            <p><strong>Reason:</strong> {{ req[10] }}</p>
                        {% endif %}
                    {% elif req[7] == 'approved' %}
                        {% if req|length > inv_filename_idx and req[inv_filename_idx] and req[inv_filename_idx] != '' %}
                            <div class="invoice-data">
                                <h4>📄 Invoice Entered by Office</h4>
                                <p><strong>Invoice Number:</strong> {{ req[inv_number_idx] if req|length > inv_number_idx else 'N/A' }}</p>
                                <p><strong>Total Cost:</strong> ${{ req[inv_cost_idx] if req|length > inv_cost_idx else '0.00' }}</p>
                                <p><strong>Entered:</strong> {{ req[inv_upload_idx] if req|length > inv_upload_idx else 'N/A' }}</p>
                            </div>
                        {% else %}
                            <p style="color: #666; margin-top: 10px; font-size: 14px;">⏳ Invoice not yet entered by office</p>
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

UNIFIED_DEPARTMENT_DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Department Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px; }
        .header {
            background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1); display: flex;
            justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;
        }
        h1 { color: #333; font-size: 28px; }
        .header-nav { display: flex; gap: 8px; flex-wrap: wrap; }
        .btn { padding: 10px 20px; border-radius: 5px; text-decoration: none; font-weight: bold; border: none; cursor: pointer; font-size: 14px; display: inline-block; }
        .btn-primary { background: #667eea; color: white; }
        .btn-secondary { background: #6c757d; color: white; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-success { background: #28a745; color: white; }

        .tabs-container { display: flex; gap: 10px; margin-bottom: 20px; }
        .tab-btn {
            padding: 12px 24px; background: white; border: 2px solid #ddd; border-radius: 5px;
            cursor: pointer; font-weight: bold; font-size: 16px; transition: all 0.3s;
        }
        .tab-btn:hover { background: #f5f5f5; }
        .tab-btn.active { background: #667eea; color: white; border-color: #667eea; }
        .tab-btn.service { color: #007bff; }
        .tab-btn.service.active { background: #007bff; color: white; }
        .tab-btn.install { color: #28a745; }
        .tab-btn.install.active { background: #28a745; color: white; }

        .tab-content { display: none; }
        .tab-content.active { display: block; }

        .year-filter {
            background: white; padding: 15px; border-radius: 5px; margin-bottom: 20px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1); display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
        }
        .year-filter select { padding: 8px 15px; border: 2px solid #ddd; border-radius: 5px; font-size: 14px; }
        .year-filter button { padding: 8px 15px; background: #667eea; color: white; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; }

        .stats-grid {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px;
        }
        .stat-card {
            background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            border-left: 4px solid #667eea;
        }
        .stat-number { font-size: 28px; font-weight: bold; color: #667eea; }
        .stat-label { color: #666; font-size: 13px; margin-top: 5px; }

        .jobs-container { display: flex; flex-direction: column; gap: 15px; }
        .job-card {
            background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            border-left: 4px solid #667eea;
        }
        .job-card.inactive { opacity: 0.7; border-left-color: #dc3545; }
        .job-header { display: flex; justify-content: space-between; align-items: start; margin-bottom: 15px; flex-wrap: wrap; gap: 10px; }
        .job-title { font-size: 18px; font-weight: bold; color: #333; }
        .job-meta { font-size: 13px; color: #666; display: flex; gap: 15px; flex-wrap: wrap; }
        .status-badge { padding: 5px 10px; border-radius: 20px; font-size: 12px; font-weight: bold; }
        .status-active { background: #28a745; color: white; }
        .status-inactive { background: #dc3545; color: white; }

        .job-stats {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; margin-bottom: 15px;
        }
        .job-stat-item { background: #f9f9f9; padding: 10px; border-radius: 5px; }
        .job-stat-value { font-weight: bold; color: #667eea; }
        .job-stat-label { font-size: 12px; color: #666; }

        .budget-bar {
            background: #e9ecef; border-radius: 10px; overflow: hidden; height: 20px; margin: 10px 0;
        }
        .budget-fill {
            height: 100%; border-radius: 10px; transition: width 0.3s; background: #28a745;
        }
        .budget-fill.yellow { background: #ffc107; }
        .budget-fill.red { background: #dc3545; }

        .pos-section {
            margin-top: 15px; padding-top: 15px; border-top: 1px solid #ddd;
        }
        .pos-title { font-weight: bold; color: #333; margin-bottom: 10px; }
        .po-item {
            background: #f5f7ff; padding: 12px; border-radius: 5px; margin-bottom: 8px;
            border-left: 3px solid #667eea; font-size: 13px;
        }
        .po-tech { font-weight: bold; color: #007bff; }
        .po-status { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 11px; margin-left: 8px; }
        .po-status.approved { background: #28a745; color: white; }
        .po-status.awaiting { background: #ffc107; color: #333; }

        .job-actions { display: flex; gap: 10px; margin-top: 15px; }
        .job-actions button { padding: 8px 16px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; font-size: 13px; }
        .toggle-job-btn { background: #6c757d; color: white; }
        .toggle-job-btn.active { background: #28a745; }

        .no-jobs { text-align: center; padding: 40px; color: #999; font-style: italic; }

        .add-job-card {
            background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1); border-left: 4px solid #667eea;
        }
        .add-job-card h2 { color: #667eea; margin-bottom: 15px; font-size: 18px; }
        .add-job-card p { color: #666; font-size: 13px; margin-bottom: 15px; }
        .form-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 15px; }
        .form-group { display: flex; flex-direction: column; }
        .form-group label { font-weight: bold; color: #555; margin-bottom: 5px; font-size: 13px; }
        .form-group input, .form-group select { padding: 10px; border: 2px solid #ddd; border-radius: 5px; font-size: 14px; }
        .form-group input:focus, .form-group select:focus { outline: none; border-color: #667eea; }
        .form-actions { display: flex; gap: 10px; }
        .form-actions button { padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; font-size: 14px; }

        .search-bar {
            background: white; padding: 15px; border-radius: 5px; margin-bottom: 20px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1); display: flex; gap: 10px; align-items: center;
        }
        .search-bar input { flex: 1; padding: 10px 15px; border: 2px solid #ddd; border-radius: 5px; font-size: 14px; }
        .search-bar input:focus { outline: none; border-color: #667eea; }
        .search-bar button { padding: 10px 20px; background: #667eea; color: white; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; }

        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; overflow-y: auto; }
        .modal.open { display: block; }
        .modal-content { background: white; margin: 30px auto; padding: 30px; border-radius: 10px; max-width: 900px; max-height: 80vh; overflow-y: auto; }
        .modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding-bottom: 15px; border-bottom: 2px solid #ddd; }
        .modal-header h2 { color: #333; }
        .modal-close { background: #dc3545; color: white; border: none; padding: 8px 15px; border-radius: 5px; cursor: pointer; font-weight: bold; }
        .all-pos-table { width: 100%; border-collapse: collapse; }
        .all-pos-table th, .all-pos-table td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        .all-pos-table th { background: #667eea; color: white; font-weight: bold; }
        .all-pos-table tr:hover { background: #f5f5f5; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🏢 Department Dashboard</h1>
        <div class="header-nav">
            <a href="{{ url_for('manage_techs') }}" style="background: #fd7e14; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; font-weight: bold;">👷 Manage Techs</a>
            <a href="{{ url_for('logout') }}" class="btn btn-danger">Logout</a>
        </div>
    </div>

    <div class="tabs-container">
        <button class="tab-btn service active" id="service-btn" onclick="switchTab('service', event)">📱 Service Department</button>
        <button class="tab-btn install" id="install-btn" onclick="switchTab('install', event)">🔧 Install Department</button>
        <button class="tab-btn" id="all-pos-btn" style="color: #9b59b6;" onclick="switchTab('all-pos', event)">📋 View All POs</button>
    </div>

    <div class="search-bar">
        <input type="text" id="search-input" placeholder="🔍 Search jobs by name..." onkeyup="performSearch()">
        <button onclick="clearSearch()">Clear</button>
    </div>

    {# PO HISTORY MODAL #}
    <div id="po-modal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h2>📋 All POs for <span id="modal-job-name"></span></h2>
                <button class="modal-close" onclick="closePoModal()">✕ Close</button>
            </div>
            <div id="modal-po-list"></div>
        </div>
    </div>

    {# SERVICE DEPARTMENT TAB #}
    <div id="service-tab" class="tab-content active">
        <div class="add-job-card">
            <h2>➕ Add New Service Job</h2>
            <p>Create a new service job. Job names must be unique.</p>
            <div style="display: flex; flex-direction: column; gap: 15px;">
                <div class="form-row">
                    <div class="form-group">
                        <label>Job Name *</label>
                        <input type="text" id="service-job-name" placeholder="e.g., Chase Bank Service" required>
                    </div>
                    <div class="form-group">
                        <label>Job Code</label>
                        <input type="text" id="service-job-code" placeholder="e.g., CB-Service">
                    </div>
                    <div class="form-group">
                        <label>Year *</label>
                        <input type="number" id="service-year" value="2026" required>
                    </div>
                    <div class="form-group">
                        <label>Budget for Materials ($)</label>
                        <input type="number" id="service-budget" placeholder="0" step="0.01" min="0" value="0">
                    </div>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-success" onclick="submitServiceJob()">✓ Create Job</button>
                </div>
            </div>
        </div>

        <div class="year-filter">
            <label>Filter by Year:</label>
            <select id="service-year-filter" onchange="filterServiceJobs()">
                <option value="">All Years</option>
            </select>
            <button onclick="filterServiceJobs()">Apply Filter</button>
            <button onclick="showAllServiceJobs()" style="background: #28a745;">Show All</button>
        </div>

        <div class="stats-grid" id="service-stats"></div>
        <div class="jobs-container" id="service-jobs-container"></div>
    </div>

    {# INSTALL DEPARTMENT TAB #}
    <div id="install-tab" class="tab-content">
        <div class="add-job-card">
            <h2>➕ Add New Install Job</h2>
            <p>Create a new install job. Job names must be unique.</p>
            <div style="display: flex; flex-direction: column; gap: 15px;">
                <div class="form-row">
                    <div class="form-group">
                        <label>Job Name *</label>
                        <input type="text" id="install-job-name" placeholder="e.g., Commercial Tower Install" required>
                    </div>
                    <div class="form-group">
                        <label>Job Code</label>
                        <input type="text" id="install-job-code" placeholder="e.g., Herons">
                    </div>
                    <div class="form-group">
                        <label>Year *</label>
                        <input type="number" id="install-year" value="2026" required>
                    </div>
                    <div class="form-group">
                        <label>Budget for Materials ($)</label>
                        <input type="number" id="install-budget" placeholder="0" step="0.01" min="0" value="0">
                    </div>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-success" onclick="submitInstallJob()">✓ Create Job</button>
                </div>
            </div>
        </div>

        <div class="year-filter">
            <label>Filter by Year:</label>
            <select id="install-year-filter" onchange="filterInstallJobs()">
                <option value="">All Years</option>
            </select>
            <button onclick="filterInstallJobs()">Apply Filter</button>
            <button onclick="showAllInstallJobs()" style="background: #28a745;">Show All</button>
        </div>

        <div class="stats-grid" id="install-stats"></div>
        <div class="jobs-container" id="install-jobs-container"></div>
    </div>

    <div id="all-pos-tab" class="tab-content">
        <div style="margin-bottom: 20px;">
            <h2>🔍 Search All POs</h2>
            <div style="display: flex; gap: 10px; margin-bottom: 15px;">
                <input type="text" id="po-search-input" placeholder="Search by description or tech name..." style="flex: 1; padding: 10px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px;">
                <button onclick="searchAllPOs()" style="background: #667eea; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer;">🔍 Search</button>
                <button onclick="clearPOSearch()" style="background: #999; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer;">Clear</button>
            </div>
        </div>
        <div id="all-pos-results" style="background: white; border-radius: 8px; padding: 20px;">
            <p style="text-align: center; color: #999;">Enter a search term to find POs by description or tech name</p>
        </div>
    </div>

    <script>
        // Data from server
        const serviceJobs = {{ service_jobs | tojson }};
        const installJobs = {{ install_jobs | tojson }};
        const jobPOs = {{ job_pos | tojson }};
        const jobAllPOs = {{ job_all_pos | tojson }};
        const techsMap = {{ techs | tojson }};

        let filteredServiceJobs = [...serviceJobs];
        let filteredInstallJobs = [...installJobs];
        let searchTerm = '';

        function switchTab(dept, evt) {
            // Hide all tabs
            document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));

            // Show selected tab
            document.getElementById(dept + '-tab').classList.add('active');

            // Set the button active if called from event (has evt parameter)
            if (evt && evt.target) {
                evt.target.classList.add('active');
            } else {
                // If called from initialization, find and activate the button by ID/matching criteria
                const buttons = document.querySelectorAll('.tab-btn');
                buttons.forEach(btn => {
                    if ((dept === 'install' && btn.id === 'install-btn') ||
                        (dept === 'service' && btn.id === 'service-btn') ||
                        (dept === 'all-pos' && btn.id === 'all-pos-btn')) {
                        btn.classList.add('active');
                    }
                });
            }
        }

        function getTechName(username) {
            return techsMap[username] ? techsMap[username].name : username;
        }

        function formatCurrency(value) {
            return '$' + parseFloat(value || 0).toFixed(2);
        }

        function searchAllPOs() {
            const searchTerm = document.getElementById('po-search-input').value.toLowerCase().trim();
            if (!searchTerm) {
                document.getElementById('all-pos-results').innerHTML = '<p style="text-align: center; color: #999;">Enter a search term to find POs by description or tech name</p>';
                return;
            }

            let html = '<table class="all-pos-table"><thead><tr><th>PO #</th><th>Job Name</th><th>Tech</th><th>Description</th><th>Status</th><th>Estimated</th><th>Date</th></tr></thead><tbody>';
            let found = 0;

            for (const [jobId, pos] of Object.entries(jobAllPOs)) {
                const job = [...serviceJobs, ...installJobs].find(j => j[0] === parseInt(jobId));
                if (!job) continue;

                pos.forEach(po => {
                    const techName = getTechName(po[2]);
                    const description = po[7] || '';
                    const status = po[3];

                    if (description.toLowerCase().includes(searchTerm) || techName.toLowerCase().includes(searchTerm)) {
                        const jobCode = job[11];
                        const poDisplay = jobCode ? `${jobCode}-${po[0]}` : po[0];
                        const estimated = po[4] || 0;
                        const date = po[6] ? po[6].substring(0, 10) : 'N/A';

                        html += `<tr>
                            <td><strong>#${poDisplay}</strong></td>
                            <td>${job[1]}</td>
                            <td>${techName}</td>
                            <td>${escapeHtml(description)}</td>
                            <td><span class="po-status ${status === 'approved' ? 'approved' : 'awaiting'}">${status}</span></td>
                            <td>${formatCurrency(estimated)}</td>
                            <td>${date}</td>
                        </tr>`;
                        found++;
                    }
                });
            }

            html += '</tbody></table>';
            if (found === 0) {
                html = '<p style="text-align: center; color: #999;">No POs found matching your search.</p>';
            } else {
                html = `<p style="margin-bottom: 15px;"><strong>Found ${found} PO(s)</strong></p>` + html;
            }
            document.getElementById('all-pos-results').innerHTML = html;
        }

        function clearPOSearch() {
            document.getElementById('po-search-input').value = '';
            document.getElementById('all-pos-results').innerHTML = '<p style="text-align: center; color: #999;">Enter a search term to find POs by description or tech name</p>';
        }

        function submitInstallJob() {
            const jobName = document.getElementById('install-job-name').value.trim();
            const jobCode = document.getElementById('install-job-code').value.trim();
            const year = document.getElementById('install-year').value.trim();
            const budget = document.getElementById('install-budget').value.trim();

            if (!jobName || !year) {
                alert('Please fill in Job Name and Year (required fields)');
                return;
            }

            const formData = new FormData();
            formData.append('job_name', jobName);
            formData.append('job_code', jobCode);
            formData.append('year', year);
            formData.append('budget', budget || '0');
            formData.append('department', 'install');

            fetch('/add_job', {
                method: 'POST',
                body: formData,
                redirect: 'follow'
            })
            .then(response => {
                console.log('Response status:', response.status);
                // Always redirect to install tab after submission
                window.location.href = '/office_dashboard?tab=install';
            })
            .catch(error => {
                console.error('Error:', error);
                alert('Error creating job: ' + error.message);
            });
        }

        function submitServiceJob() {
            const jobName = document.getElementById('service-job-name').value.trim();
            const jobCode = document.getElementById('service-job-code').value.trim();
            const year = document.getElementById('service-year').value.trim();
            const budget = document.getElementById('service-budget').value.trim();

            if (!jobName || !year) {
                alert('Please fill in Job Name and Year (required fields)');
                return;
            }

            const formData = new FormData();
            formData.append('job_name', jobName);
            formData.append('job_code', jobCode);
            formData.append('year', year);
            formData.append('budget', budget || '0');
            formData.append('department', 'service');

            fetch('/add_job', {
                method: 'POST',
                body: formData,
                redirect: 'follow'
            })
            .then(response => {
                console.log('Response status:', response.status);
                // Always redirect to service tab after submission
                window.location.href = '/office_dashboard?tab=service';
            })
            .catch(error => {
                console.error('Error:', error);
                alert('Error creating job: ' + error.message);
            });
        }

        function renderServiceJobs() {
            const container = document.getElementById('service-jobs-container');
            const statsDiv = document.getElementById('service-stats');

            if (filteredServiceJobs.length === 0) {
                container.innerHTML = '<div class="no-jobs">No service jobs to display</div>';
                statsDiv.innerHTML = '';
                return;
            }

            // Calculate stats
            let activeCount = 0, totalBudget = 0, totalInvoiced = 0, totalPOs = 0;
            filteredServiceJobs.forEach(job => {
                if (job[4]) activeCount++;
                totalBudget += job[9] || 0;
                totalInvoiced += job[5] || 0;
                totalPOs += job[8] || 0;
            });

            statsDiv.innerHTML = `
                <div class="stat-card"><div class="stat-number">${filteredServiceJobs.length}</div><div class="stat-label">Total Jobs</div></div>
                <div class="stat-card"><div class="stat-number">${activeCount}</div><div class="stat-label">Active Jobs</div></div>
                <div class="stat-card"><div class="stat-number">${formatCurrency(totalBudget)}</div><div class="stat-label">Total Budget</div></div>
                <div class="stat-card"><div class="stat-number">${formatCurrency(totalInvoiced)}</div><div class="stat-label">Total Invoiced</div></div>
            `;

            let html = '';
            filteredServiceJobs.forEach(job => {
                html += renderJobCard(job, 'service');
            });
            container.innerHTML = html;

            // Add event listeners
            addJobCardListeners();
        }

        function renderInstallJobs() {
            const container = document.getElementById('install-jobs-container');
            const statsDiv = document.getElementById('install-stats');

            if (filteredInstallJobs.length === 0) {
                container.innerHTML = '<div class="no-jobs">No install jobs to display</div>';
                statsDiv.innerHTML = '';
                return;
            }

            // Calculate stats
            let activeCount = 0, totalBudget = 0, totalInvoiced = 0, totalPOs = 0;
            filteredInstallJobs.forEach(job => {
                if (job[4]) activeCount++;
                totalBudget += job[9] || 0;
                totalInvoiced += job[5] || 0;
                totalPOs += job[8] || 0;
            });

            statsDiv.innerHTML = `
                <div class="stat-card"><div class="stat-number">${filteredInstallJobs.length}</div><div class="stat-label">Total Jobs</div></div>
                <div class="stat-card"><div class="stat-number">${activeCount}</div><div class="stat-label">Active Jobs</div></div>
                <div class="stat-card"><div class="stat-number">${formatCurrency(totalBudget)}</div><div class="stat-label">Total Budget</div></div>
                <div class="stat-card"><div class="stat-number">${formatCurrency(totalInvoiced)}</div><div class="stat-label">Total Invoiced</div></div>
            `;

            let html = '';
            filteredInstallJobs.forEach(job => {
                html += renderJobCard(job, 'install');
            });
            container.innerHTML = html;

            // Add event listeners
            addJobCardListeners();
        }

        function renderJobCard(job, dept) {
            const jobId = job[0];
            const jobName = job[1];
            const year = job[2];
            const isActive = job[4];
            const budget = job[9] || 0;
            const invoiced = job[5] || 0;
            const poCount = job[8] || 0;
            const jobCode = job[11];

            const budgetPct = budget > 0 ? (invoiced / budget * 100) : 0;
            const budgetColor = budgetPct <= 50 ? '' : budgetPct <= 75 ? 'yellow' : 'red';

            const pos = jobPOs[jobId] || [];
            const servicePOs = pos.filter(p => techsMap[p[2]] && techsMap[p[2]].type === dept.slice(0, 7)); // 'service' or 'install'

            let html = `
                <div class="job-card ${!isActive ? 'inactive' : ''}" id="job-${jobId}">
                    <div class="job-header">
                        <div>
                            <div class="job-title">${jobName}</div>
                            <div class="job-meta">
                                <span>Year: ${year}</span>
                                <span class="status-badge ${isActive ? 'status-active' : 'status-inactive'}">${isActive ? 'Active' : 'Inactive'}</span>
                            </div>
                        </div>
                    </div>

                    <div class="job-stats">
                        <div class="job-stat-item">
                            <div class="job-stat-value">${poCount}</div>
                            <div class="job-stat-label">Active POs</div>
                        </div>
                        <div class="job-stat-item">
                            <div class="job-stat-value">${formatCurrency(budget)}</div>
                            <div class="job-stat-label">Budget</div>
                        </div>
                        <div class="job-stat-item">
                            <div class="job-stat-value">${formatCurrency(invoiced)}</div>
                            <div class="job-stat-label">Invoiced</div>
                        </div>
                    </div>
            `;

            if (budget > 0) {
                html += `
                    <div class="budget-bar">
                        <div class="budget-fill ${budgetColor}" style="width: ${Math.min(budgetPct, 100)}%"></div>
                    </div>
                    <small style="color: #666;">${budgetPct.toFixed(1)}% of budget used</small>
                `;
            }

            if (servicePOs.length > 0) {
                html += '<div class="pos-section"><div class="pos-title">📋 Active POs:</div>';
                servicePOs.forEach(po => {
                    const poNum = po[0];
                    const poDisplay = jobCode ? `${jobCode}-${poNum}` : poNum;
                    const techName = getTechName(po[2]);
                    const status = po[3];
                    const estimated = po[4] || 0;
                    const invoiced_po = po[5] || 0;

                    html += `
                        <div class="po-item">
                            <strong>PO #${poDisplay}</strong> - <span class="po-tech">${techName}</span>
                            <span class="po-status ${status === 'approved' ? 'approved' : 'awaiting'}">${status}</span>
                            <br><small>Est: ${formatCurrency(estimated)} | Inv: ${formatCurrency(invoiced_po)}</small>
                        </div>
                    `;
                });
                html += '</div>';
            } else {
                html += '<div class="pos-section"><p style="color: #999; font-style: italic;">No active POs for this job</p></div>';
            }

            html += `
                <div class="job-actions">
                    <button class="toggle-job-btn ${isActive ? 'active' : ''}" data-id="${jobId}" onclick="toggleJobStatus(${jobId}, '${dept}')">
                        ${isActive ? '✓ Active - Click to Close' : '○ Inactive - Click to Reopen'}
                    </button>
                    <button style="background: #007bff; color: white;" onclick="showAllPOs(${jobId}, '${jobName.replace(/'/g, "\\'")}', '${jobCode ? jobCode.replace(/'/g, "\\'") : ''}')">
                        📋 View All POs (${jobAllPOs[jobId] ? jobAllPOs[jobId].length : 0})
                    </button>
                    <button class="delete-job-btn" onclick="deleteJob(${jobId}, '${jobName.replace(/'/g, "\\'")}')" style="background: #dc3545; color: white;">
                        🗑️ Delete
                    </button>
                </div>
            </div>
            `;

            return html;
        }

        function addJobCardListeners() {
            // Listeners are added via onclick attributes
        }

        function toggleJobStatus(jobId, dept) {
            if (!confirm('Toggle this job status? Inactive jobs are archived.')) return;

            fetch('/toggle_job', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ job_id: jobId })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    location.reload();
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }

        function deleteJob(jobId, jobName) {
            if (!confirm(`Are you sure you want to delete the job "${jobName}"? This action cannot be undone.`)) return;

            fetch('/delete_job', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ job_id: jobId })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    alert(data.message);
                    location.reload();
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }

        function filterServiceJobs() {
            const year = document.getElementById('service-year-filter').value;
            if (year) {
                filteredServiceJobs = serviceJobs.filter(job => job[2].toString() === year);
            } else {
                filteredServiceJobs = [...serviceJobs];
            }
            renderServiceJobs();
        }

        function filterInstallJobs() {
            const year = document.getElementById('install-year-filter').value;
            if (year) {
                filteredInstallJobs = installJobs.filter(job => job[2].toString() === year);
            } else {
                filteredInstallJobs = [...installJobs];
            }
            renderInstallJobs();
        }

        function showAllServiceJobs() {
            document.getElementById('service-year-filter').value = '';
            filterServiceJobs();
        }

        function showAllInstallJobs() {
            document.getElementById('install-year-filter').value = '';
            filterInstallJobs();
        }

        // Populate year filters
        function populateYearFilters() {
            const serviceYears = [...new Set(serviceJobs.map(j => j[2]))].sort((a, b) => b - a);
            const installYears = [...new Set(installJobs.map(j => j[2]))].sort((a, b) => b - a);

            const serviceSelect = document.getElementById('service-year-filter');
            const installSelect = document.getElementById('install-year-filter');

            serviceYears.forEach(year => {
                const opt = document.createElement('option');
                opt.value = year;
                opt.textContent = year;
                serviceSelect.appendChild(opt);
            });

            installYears.forEach(year => {
                const opt = document.createElement('option');
                opt.value = year;
                opt.textContent = year;
                installSelect.appendChild(opt);
            });
        }

        // Search functionality
        function performSearch() {
            searchTerm = document.getElementById('search-input').value.toLowerCase();
            filteredServiceJobs = serviceJobs.filter(job =>
                job[1].toLowerCase().includes(searchTerm)
            );
            filteredInstallJobs = installJobs.filter(job =>
                job[1].toLowerCase().includes(searchTerm)
            );
            renderServiceJobs();
            renderInstallJobs();
        }

        function clearSearch() {
            document.getElementById('search-input').value = '';
            searchTerm = '';
            filteredServiceJobs = [...serviceJobs];
            filteredInstallJobs = [...installJobs];
            renderServiceJobs();
            renderInstallJobs();
        }

        // Modal for viewing all POs
        function showAllPOs(jobId, jobName, jobCode) {
            const allPOs = jobAllPOs[jobId] || [];
            document.getElementById('modal-job-name').textContent = jobName;

            if (allPOs.length === 0) {
                document.getElementById('modal-po-list').innerHTML = '<p style="text-align: center; color: #999;">No POs found for this job.</p>';
            } else {
                let html = '<table class="all-pos-table"><thead><tr><th>PO #</th><th>Tech</th><th>Status</th><th>Estimated</th><th>Invoiced</th><th>Date</th></tr></thead><tbody>';

                allPOs.forEach(po => {
                    const poNum = po[0];
                    const poDisplay = jobCode ? `${jobCode}-${poNum}` : poNum;
                    const techName = getTechName(po[2]);
                    const status = po[3];
                    const estimated = po[4] || 0;
                    const invoiced = po[5] || 0;
                    const date = po[6] ? po[6].substring(0, 10) : 'N/A';

                    html += `<tr>
                        <td><strong>#${poDisplay}</strong></td>
                        <td>${techName}</td>
                        <td><span class="po-status ${status === 'approved' ? 'approved' : 'awaiting'}">${status}</span></td>
                        <td>${formatCurrency(estimated)}</td>
                        <td>${formatCurrency(invoiced)}</td>
                        <td>${date}</td>
                    </tr>`;
                });

                html += '</tbody></table>';
                document.getElementById('modal-po-list').innerHTML = html;
            }

            document.getElementById('po-modal').classList.add('open');
        }

        function closePoModal() {
            document.getElementById('po-modal').classList.remove('open');
        }

        window.onclick = function(event) {
            const modal = document.getElementById('po-modal');
            if (event.target === modal) {
                modal.classList.remove('open');
            }
        };

        // Initialize
        window.addEventListener('DOMContentLoaded', () => {
            populateYearFilters();
            renderServiceJobs();
            renderInstallJobs();

            // Check if we need to switch to a different tab based on URL parameter
            const urlParams = new URLSearchParams(window.location.search);
            const tab = urlParams.get('tab');
            if (tab && (tab === 'install' || tab === 'all-pos')) {
                switchTab(tab);
            }
        });
    </script>
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
        <div style="display: flex; gap: 8px; flex-wrap: wrap;">
            <a href="{{ url_for('manage_jobs') }}" style="background: #17a2b8; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; font-size: 14px;">📋 Manage Jobs</a>
            <a href="{{ url_for('manage_techs') }}" style="background: #fd7e14; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; font-size: 14px;">👷 Manage Techs</a>
            <a href="{{ url_for('settings_page') }}" style="background: #6c757d; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; font-size: 14px;">⚙️ Settings</a>
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
            <div class="stat-number">{{ stats.service_awaiting }}</div>
            <div class="stat-label">Service - Awaiting Invoice</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{{ stats.install_awaiting }}</div>
            <div class="stat-label">Install - Awaiting Invoice</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{{ stats.service_invoiced }}</div>
            <div class="stat-label">Service - With Invoices</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{{ stats.install_invoiced }}</div>
            <div class="stat-label">Install - With Invoices</div>
        </div>
    </div>

    <div class="tabs">
        <button class="tab active" onclick="showTab('service-awaiting')">📱 Service - Awaiting ({{ stats.service_awaiting }})</button>
        <button class="tab" onclick="showTab('service-invoiced')">📱 Service - Invoiced ({{ stats.service_invoiced }})</button>
        <button class="tab" onclick="showTab('install-awaiting')">🔧 Install - Awaiting ({{ stats.install_awaiting }})</button>
        <button class="tab" onclick="showTab('install-invoiced')">🔧 Install - Invoiced ({{ stats.install_invoiced }})</button>
        {% if stats.legacy_awaiting > 0 or stats.legacy_invoiced > 0 %}
            <button class="tab" onclick="showTab('legacy-awaiting')">📦 Legacy - Awaiting ({{ stats.legacy_awaiting }})</button>
            <button class="tab" onclick="showTab('legacy-invoiced')">📦 Legacy - Invoiced ({{ stats.legacy_invoiced }})</button>
        {% endif %}
    </div>

    {# SERVICE - AWAITING INVOICE #}
    <div id="service-awaiting" class="tab-content active">
    <div style="background: #f0f4ff; padding: 15px; border-radius: 5px; margin-bottom: 15px;">
        <input type="text"
               id="search-service-awaiting"
               placeholder="🔍 Search Service POs (PO#, tech, job, description, store)..."
               onkeyup="searchInTab('service-awaiting', 'search-service-awaiting')"
               style="width: 100%; padding: 10px; border: 2px solid #007bff; border-radius: 5px; font-size: 14px;">
        <div class="search-result-count" style="margin-top: 8px; color: #007bff; font-size: 13px; display: none;"></div>
    </div>

    {% if service_awaiting_requests %}
        {% for req in service_awaiting_requests %}
            <div class="request-item" data-po-id="{{ req[0] }}">
                <button onclick="deleteRequest({{ req[0] }})" class="delete-btn">🗑️ Delete</button>
                <h3>📱 PO #S{{ "%04d"|format(req[0]) }} - {{ req[3] }}</h3>
                <p><strong>Technician:</strong> {{ req[2] }} ({{ req[1] }})</p>
                <p><strong>Job:</strong> {{ req[3] }}</p>
                <p><strong>Store:</strong> {{ req[4] }}</p>
                <p><strong>Description:</strong> {{ req[6] }}</p>
                <p><strong>Requested:</strong> {{ req[8] }}</p>
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
        <p style="color: #999; text-align: center; padding: 40px;">No Service POs awaiting invoices</p>
    {% endif %}
</div>

    {# SERVICE - WITH INVOICE #}
    <div id="service-invoiced" class="tab-content">
    {% if service_invoiced_requests %}
        {% for req in service_invoiced_requests %}
            <div class="request-item" data-po-id="{{ req[0] }}">
                <button onclick="deleteRequest({{ req[0] }})" class="delete-btn">🗑️ Delete</button>
                <button onclick="deleteInvoice({{ req[0] }})" class="delete-btn" style="right: 120px; background: #ff9800;">🗑️ Remove Invoice</button>
                <h3>📱 PO #S{{ "%04d"|format(req[0]) }} - {{ req[3] }} - ${{ "%.2f"|format((req[inv_cost_idx]|float(0) if req[inv_cost_idx] else 0) if req|length > inv_cost_idx else 0) }}</h3>
                <p><strong>Technician:</strong> {{ req[2] }} ({{ req[1] }})</p>
                <p><strong>Job:</strong> {{ req[3] }}</p>
                <p><strong>Description:</strong> {{ req[6] }}</p>
                <p><strong>Requested:</strong> {{ req[8] }}</p>
                <div class="invoice-data">
                    <h4>📄 Invoice Details</h4>
                    <p><strong>Invoice Number:</strong> {{ req[inv_number_idx] if req|length > inv_number_idx else 'Not entered' }}</p>
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
        <p style="color: #999; text-align: center; padding: 40px;">No Service invoiced requests</p>
    {% endif %}
</div>

    {# INSTALL - AWAITING INVOICE #}
    <div id="install-awaiting" class="tab-content">
    <div style="background: #f0f4ff; padding: 15px; border-radius: 5px; margin-bottom: 15px;">
        <input type="text"
               id="search-install-awaiting"
               placeholder="🔍 Search Install POs (PO#, tech, job, description, store)..."
               onkeyup="searchInTab('install-awaiting', 'search-install-awaiting')"
               style="width: 100%; padding: 10px; border: 2px solid #28a745; border-radius: 5px; font-size: 14px;">
        <div class="search-result-count" style="margin-top: 8px; color: #28a745; font-size: 13px; display: none;"></div>
    </div>

    {% if install_awaiting_requests %}
        {% for req in install_awaiting_requests %}
            <div class="request-item" data-po-id="{{ req[0] }}">
                <button onclick="deleteRequest({{ req[0] }})" class="delete-btn">🗑️ Delete</button>
                <h3>🔧 PO #I{{ "%04d"|format(req[0]) }} - {{ req[3] }}</h3>
                <p><strong>Technician:</strong> {{ req[2] }} ({{ req[1] }})</p>
                <p><strong>Job:</strong> {{ req[3] }}</p>
                <p><strong>Store:</strong> {{ req[4] }}</p>
                <p><strong>Description:</strong> {{ req[6] }}</p>
                <p><strong>Requested:</strong> {{ req[8] }}</p>
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
        <p style="color: #999; text-align: center; padding: 40px;">No Install POs awaiting invoices</p>
    {% endif %}
</div>

    {# INSTALL - WITH INVOICE #}
    <div id="install-invoiced" class="tab-content">
    {% if install_invoiced_requests %}
        {% for req in install_invoiced_requests %}
            <div class="request-item" data-po-id="{{ req[0] }}">
                <button onclick="deleteRequest({{ req[0] }})" class="delete-btn">🗑️ Delete</button>
                <button onclick="deleteInvoice({{ req[0] }})" class="delete-btn" style="right: 120px; background: #ff9800;">🗑️ Remove Invoice</button>
                <h3>🔧 PO #I{{ "%04d"|format(req[0]) }} - {{ req[3] }} - ${{ "%.2f"|format((req[inv_cost_idx]|float(0) if req[inv_cost_idx] else 0) if req|length > inv_cost_idx else 0) }}</h3>
                <p><strong>Technician:</strong> {{ req[2] }} ({{ req[1] }})</p>
                <p><strong>Job:</strong> {{ req[3] }}</p>
                <p><strong>Description:</strong> {{ req[6] }}</p>
                <p><strong>Requested:</strong> {{ req[8] }}</p>
                <div class="invoice-data">
                    <h4>📄 Invoice Details</h4>
                    <p><strong>Invoice Number:</strong> {{ req[inv_number_idx] if req|length > inv_number_idx else 'Not entered' }}</p>
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
        <p style="color: #999; text-align: center; padding: 40px;">No Install invoiced requests</p>
    {% endif %}
</div>

    {# LEGACY - AWAITING INVOICE (for backwards compatibility) #}
    {% if stats.legacy_awaiting > 0 %}
    <div id="legacy-awaiting" class="tab-content">
    <div style="background: #f0f4ff; padding: 15px; border-radius: 5px; margin-bottom: 15px;">
        <input type="text"
               id="search-legacy-awaiting"
               placeholder="🔍 Search Legacy POs (PO#, tech, job, description, store)..."
               onkeyup="searchInTab('legacy-awaiting', 'search-legacy-awaiting')"
               style="width: 100%; padding: 10px; border: 2px solid #fd7e14; border-radius: 5px; font-size: 14px;">
        <div class="search-result-count" style="margin-top: 8px; color: #fd7e14; font-size: 13px; display: none;"></div>
    </div>

    {% if legacy_awaiting_requests %}
        {% for req in legacy_awaiting_requests %}
            <div class="request-item" data-po-id="{{ req[0] }}">
                <button onclick="deleteRequest({{ req[0] }})" class="delete-btn">🗑️ Delete</button>
                <h3>📦 PO #{{ "%04d"|format(req[0]) }} - {{ req[3] }}</h3>
                <p><strong>Technician:</strong> {{ req[2] }} ({{ req[1] }})</p>
                <p><strong>Job:</strong> {{ req[3] }}</p>
                <p><strong>Store:</strong> {{ req[4] }}</p>
                <p><strong>Description:</strong> {{ req[6] }}</p>
                <p><strong>Requested:</strong> {{ req[8] }}</p>
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
        <p style="color: #999; text-align: center; padding: 40px;">No Legacy POs awaiting invoices</p>
    {% endif %}
</div>
    {% endif %}

    {# LEGACY - WITH INVOICE (for backwards compatibility) #}
    {% if stats.legacy_invoiced > 0 %}
    <div id="legacy-invoiced" class="tab-content">
    {% if legacy_invoiced_requests %}
        {% for req in legacy_invoiced_requests %}
            <div class="request-item" data-po-id="{{ req[0] }}">
                <button onclick="deleteRequest({{ req[0] }})" class="delete-btn">🗑️ Delete</button>
                <button onclick="deleteInvoice({{ req[0] }})" class="delete-btn" style="right: 120px; background: #ff9800;">🗑️ Remove Invoice</button>
                <h3>📦 PO #{{ "%04d"|format(req[0]) }} - {{ req[3] }} - ${{ "%.2f"|format((req[inv_cost_idx]|float(0) if req[inv_cost_idx] else 0) if req|length > inv_cost_idx else 0) }}</h3>
                <p><strong>Technician:</strong> {{ req[2] }} ({{ req[1] }})</p>
                <p><strong>Job:</strong> {{ req[3] }}</p>
                <p><strong>Description:</strong> {{ req[6] }}</p>
                <p><strong>Requested:</strong> {{ req[8] }}</p>
                <div class="invoice-data">
                    <h4>📄 Invoice Details</h4>
                    <p><strong>Invoice Number:</strong> {{ req[inv_number_idx] if req|length > inv_number_idx else 'Not entered' }}</p>
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
        <p style="color: #999; text-align: center; padding: 40px;">No Legacy invoiced requests</p>
    {% endif %}
</div>
    {% endif %}
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

    c.execute("SELECT COUNT(*) FROM po_requests WHERE status='awaiting_invoice'")
    awaiting_pos = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM po_requests WHERE invoice_filename IS NOT NULL")
    invoiced_pos = c.fetchone()[0]

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
        'awaiting_pos': awaiting_pos,
        'invoiced_pos': invoiced_pos,
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

    # Get all awaiting_invoice POs
    c.execute("SELECT id, job_name, status FROM po_requests WHERE status='awaiting_invoice' ORDER BY id")
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

    # Get awaiting_invoice POs without invoices (what bulk upload would see)
    c.execute("""SELECT id, job_name FROM po_requests
                 WHERE status='awaiting_invoice'
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
