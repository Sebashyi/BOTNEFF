
import base64
import os
import re
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from bs4 import BeautifulSoup

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def get_service():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        raise Exception("Gmail token not found or invalid. Run auth script first.")
    return build('gmail', 'v1', credentials=creds)

def fetch_latest_netflix_code():
    service = get_service()
    results = service.users().messages().list(userId='me', q='from:info@account.netflix.com subject:"login code"', maxResults=1).execute()
    messages = results.get('messages', [])
    if not messages:
        return "No login code found."

    msg = service.users().messages().get(userId='me', id=messages[0]['id'], format='full').execute()
    data = msg['payload']['body'].get('data')
    if not data:
        for part in msg['payload'].get('parts', []):
            if part['mimeType'] == 'text/plain':
                data = part['body'].get('data')
                break
    if not data:
        return "Email format not recognized."
    text = base64.urlsafe_b64decode(data).decode('utf-8')
    match = re.search(r'(\d{6})', text)
    return f"Netflix Login Code: {match.group(1)}" if match else "Code not found."

def fetch_latest_reset_link():
    service = get_service()
    results = service.users().messages().list(userId='me', q='from:info@account.netflix.com subject:"reset your password"', maxResults=1).execute()
    messages = results.get('messages', [])
    if not messages:
        return "No password reset email found."

    msg = service.users().messages().get(userId='me', id=messages[0]['id'], format='full').execute()
    parts = msg['payload'].get('parts', [])
    html_part = next((p for p in parts if p['mimeType'] == 'text/html'), None)
    if not html_part:
        return "No HTML part found."

    data = html_part['body']['data']
    html = base64.urlsafe_b64decode(data).decode('utf-8')
    soup = BeautifulSoup(html, 'html.parser')
    link = soup.find('a', href=re.compile(r'netflix\.com/password'))
    return f"Reset Link: {link['href']}" if link else "Reset link not found."
