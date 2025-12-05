
import os
import json
import base64
import re

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from bs4 import BeautifulSoup

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']


def get_service():
    """
    Create a Gmail API service.

    Priority:
    1. Use /etc/secrets/GMAIL_CREDENTIALS (for Render – JSON with credentials)
    2. Fallback to local token.json (for local testing)
    """
    creds = None

    # 1) Render / server secret
    if os.path.exists("/etc/secrets/GMAIL_CREDENTIALS"):
        with open("/etc/secrets/GMAIL_CREDENTIALS", "r") as f:
            creds_dict = json.load(f)
        creds = Credentials.from_authorized_user_info(creds_dict, SCOPES)

    # 2) Local token.json (for development)
    elif os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise Exception(
                "No valid Gmail credentials found. "
                "Ensure /etc/secrets/GMAIL_CREDENTIALS or token.json exists."
            )

    return build("gmail", "v1", credentials=creds)


def _extract_netflix_content_from_body(msg_body: str, digits: int = 4):
    """
    Extract Netflix-related link + code from plain text body.
    digits = expected code length (4 or 6).
    """
    links = re.findall(r'https://www\.netflix\.com/[^\s"<]+', msg_body)
    codes = re.findall(rf'(?<!\d)(\d{{{digits}}})(?!\d)', msg_body)

    link = links[0] if links else "No reset link found"
    code = codes[0] if codes else "No code found"
    return link, code


def fetch_latest_email(email: str, query: str, digits: int = 4):
    """
    Generic helper:
    - email: the target email address (Netflix account email)
    - query: Gmail search query (e.g. 'Netflix', 'Netflix password reset')
    - digits: code length to look for (4 or 6)

    Returns:
      (link, code) -> both strings
    """
    service = get_service()

    full_query = f'to:{email} {query}'
    result = service.users().messages().list(
        userId='me',
        q=full_query,
        maxResults=1
    ).execute()

    messages = result.get('messages', [])
    if not messages:
        return "No email found", "N/A"

    msg = service.users().messages().get(
        userId='me',
        id=messages[0]['id'],
        format='full'
    ).execute()
    payload = msg.get('payload', {})

    body = ""

    # Try text/plain first
    if 'parts' in payload:
        for part in payload['parts']:
            mime = part.get('mimeType', '')
            data = part.get('body', {}).get('data')
            if mime == 'text/plain' and data:
                body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                break

        # If still empty, try HTML → text
        if not body:
            for part in payload['parts']:
                mime = part.get('mimeType', '')
                data = part.get('body', {}).get('data')
                if mime == 'text/html' and data:
                    html = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                    soup = BeautifulSoup(html, 'html.parser')
                    body = soup.get_text(separator=' ', strip=True)
                    break

    # Fallback: single-part
    if not body and 'body' in payload and 'data' in payload['body']:
        data = payload['body']['data']
        body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')

    if not body:
        return "No body found", "N/A"

    return _extract_netflix_content_from_body(body, digits=digits)


def fetch_latest_netflix_code(email: str):
    """
    Use the generic fetcher to get latest Netflix login code for a given email.
    """
    link, code = fetch_latest_email(email, query='Netflix', digits=4)
    if code == "No code found":
        return "Netflix Login Code: Code not found."
    return f"Netflix Login Code: {code}"


def fetch_latest_reset_link(email: str):
    """
    Use HTML parsing to get latest Netflix password reset link for a given email.
    """
    service = get_service()
    full_query = f'to:{email} from:info@account.netflix.com subject:"reset your password"'
    result = service.users().messages().list(
        userId='me',
        q=full_query,
        maxResults=1
    ).execute()

    messages = result.get('messages', [])
    if not messages:
        return "No password reset email found."

    msg = service.users().messages().get(
        userId='me',
        id=messages[0]['id'],
        format='full'
    ).execute()
    payload = msg.get('payload', {})

    parts = payload.get('parts', [])
    html_part = None
    for p in parts:
        if p.get('mimeType') == 'text/html' and 'data' in p.get('body', {}):
            html_part = p
            break

    if not html_part and 'body' in payload and 'data' in payload['body']:
        html_data = payload['body']['data']
    elif html_part:
        html_data = html_part['body']['data']
    else:
        return "No HTML part found."

    html = base64.urlsafe_b64decode(html_data).decode('utf-8', errors='ignore')
    soup = BeautifulSoup(html, 'html.parser')

    link_tag = soup.find('a', href=re.compile(r'netflix\.com/password'))
    if not link_tag:
        link_tag = soup.find('a', href=re.compile(r'netflix\.com'))

    if link_tag:
        return f"Reset Link: {link_tag['href']}"

    return "Reset link not found."
