"""
Run this in the Railway console to reset a user's password:
  python reset_password.py <username> <new_password>

It also lists all users so you can see what's in the database.
"""
import sys
import os
import sqlite3
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get('DATA_DIR', BASE_DIR)
DB_PATH = os.path.join(DATA_DIR, 'po_requests.db')

print(f"Database: {DB_PATH}")
print(f"Exists: {os.path.exists(DB_PATH)}")

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.execute("SELECT id, username, role, email, SUBSTR(password,1,20) FROM users")
users = c.fetchall()
print(f"\nUsers in database ({len(users)} total):")
for u in users:
    print(f"  id={u[0]}  username={u[1]}  role={u[2]}  email={u[3]}  password_preview={u[4]}")

if len(sys.argv) == 3:
    username = sys.argv[1]
    new_password = sys.argv[2]
    hashed = generate_password_hash(new_password)
    c.execute("UPDATE users SET password=? WHERE LOWER(username)=?", (hashed, username.lower()))
    if c.rowcount == 0:
        print(f"\nNo user found with username '{username}'")
    else:
        conn.commit()
        print(f"\nPassword reset for '{username}' — you can now log in.")
else:
    print("\nTo reset a password, run:")
    print("  python reset_password.py <username> <new_password>")

conn.close()
