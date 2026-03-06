#!/usr/bin/env python3
"""
Test script to send a notification email
"""
import os
import sys
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

# Email configuration
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
EMAIL_ADDRESS = os.environ.get('EMAIL_ADDRESS', '')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', '')
WEBSITE_URL = os.environ.get('WEBSITE_URL', 'http://localhost:5000')

def send_test_notification_email():
    """Send a test notification email"""

    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        print("❌ Error: EMAIL_ADDRESS and EMAIL_PASSWORD environment variables not set")
        print("\nTo use this test script, set:")
        print("  export EMAIL_ADDRESS='your-email@gmail.com'")
        print("  export EMAIL_PASSWORD='your-app-password'")
        print("  export WEBSITE_URL='https://your-app.railway.app'")
        return False

    try:
        recipient_email = 'simon@stahlman-england.com'
        invoice_number = 'TEST-12345'
        invoice_cost = 150.00
        email_sender = 'test@example.com'
        email_subject = '[TEST] Invoice Notification'
        invoice_filename = 'TEST_INVOICE.pdf'
        text_preview = 'This is a test invoice notification to verify email functionality is working correctly.'

        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'⚠️ Unmatched Invoice Alert - #{invoice_number}'
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = recipient_email

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <div style="max-width: 600px; margin: 0 auto; background: #fff3cd; padding: 30px; border-radius: 10px; border-left: 5px solid #ff9800;">
                <h2 style="color: #ff9800;">⚠️ Unmatched Invoice Detected (TEST)</h2>
                <p><strong>Invoice Number:</strong> {invoice_number}</p>
                <p><strong>Invoice Cost:</strong> £{invoice_cost:.2f}</p>
                <p><strong>Email From:</strong> {email_sender}</p>
                <p><strong>Email Subject:</strong> {email_subject}</p>
                <p><strong>Filename:</strong> {invoice_filename}</p>
                <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                <p style="color: #666; font-size: 14px;"><strong>Document Preview:</strong></p>
                <p style="background: #f5f5f5; padding: 15px; border-radius: 5px; color: #333; font-size: 13px; max-height: 200px; overflow: hidden;">
                    {text_preview}
                </p>
                <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                <div style="text-align: center; margin: 20px 0;">
                    <p style="color: #666;">This is a TEST email to verify notification system is working.</p>
                    <p style="color: #666;">Please log in to the system to manage invoice notifications.</p>
                </div>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{WEBSITE_URL}/office_dashboard"
                       style="background: #667eea; color: white; padding: 15px 30px;
                              text-decoration: none; border-radius: 5px; font-weight: bold;
                              display: inline-block;">
                        View in System
                    </a>
                </div>
                <p style="color: #999; font-size: 12px; margin-top: 30px;">
                    This is an automated TEST notification from the PO Request System.
                </p>
            </div>
        </body>
        </html>
        """

        part = MIMEText(html, 'html')
        msg.attach(part)

        print(f"📧 Sending test email to {recipient_email}...")
        print(f"   From: {EMAIL_ADDRESS}")
        print(f"   Server: {SMTP_SERVER}:{SMTP_PORT}")

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.send_message(msg)

        print(f"✅ Test email sent successfully to {recipient_email}")
        return True

    except smtplib.SMTPAuthenticationError:
        print("❌ Authentication failed. Check EMAIL_ADDRESS and EMAIL_PASSWORD")
        return False
    except Exception as e:
        print(f"❌ Error sending email: {e}")
        return False

if __name__ == '__main__':
    success = send_test_notification_email()
    sys.exit(0 if success else 1)
