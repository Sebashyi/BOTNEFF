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
    1. Railway ENV var: GMAIL_CREDENTIALS (JSON string)
    2. Local token.json (for local testing only)
    """
    creds = None

    # ✅ 1) Railway / env-based credentials
    env_creds = os.getenv("GMAIL_CREDENTIALS")
    if env_creds:
        try:
            creds_dict = json.loads(env_creds)
            creds = Credentials.from_authorized_user_info(creds_dict, SCOPES)
        except Exception as e:
            raise Exception(f"Invalid GMAIL_CREDENTIALS JSON: {e}")

    # ✅ 2) Local development fallback
    elif os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds:
        raise Exception("No Gmail credentials found (env or token.json missing)")

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise Exception("Gmail credentials expired and cannot be refreshed")

    return build("gmail", "v1", credentials=creds)


def _extract_netflix_content_from_body(msg_body: str, digits: int = 4):
    links = re.findall(r'https://www\.netflix\.com/[^\s"<]+', msg_body)
    codes = re.findall(rf'(?<!\d)(\d{{{digits}}})(?!\d)', msg_body)

    link = links[0] if links else "No reset link found"
    code = codes[0] if codes else "No code found"
    return link, code


def fetch_latest_email(email: str, query: str, digits: int = 4):
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

    if 'parts' in payload:
        for part in payload['parts']:
            if part.get('mimeType') == 'text/plain' and 'data' in part.get('body', {}):
                body = base64.urlsafe_b64decode(
                    part['body']['data']
                ).decode('utf-8', errors='ignore')
                break

        if not body:
            for part in payload['parts']:
                if part.get('mimeType') == 'text/html' and 'data' in part.get('body', {}):
                    html = base64.urlsafe_b64decode(
                        part['body']['data']
                    ).decode('utf-8', errors='ignore')
                    soup = BeautifulSoup(html, 'html.parser')
                    body = soup.get_text(separator=' ', strip=True)
                    break

    if not body and 'body' in payload and 'data' in payload['body']:
        body = base64.urlsafe_b64decode(
            payload['body']['data']
        ).decode('utf-8', errors='ignore')

    if not body:
        return "No body found", "N/A"

    return _extract_netflix_content_from_body(body, digits)


def fetch_latest_netflix_code(email: str):
    link, code = fetch_latest_email(email, "Netflix", digits=4)
    return f"Netflix Login Code: {code}"


def fetch_latest_reset_link(email: str):
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

    for part in payload.get('parts', []):
        if part.get('mimeType') == 'text/html' and 'data' in part.get('body', {}):
            html = base64.urlsafe_b64decode(
                part['body']['data']
            ).decode('utf-8', errors='ignore')
            soup = BeautifulSoup(html, 'html.parser')

            link_tag = soup.find('a', href=re.compile(r'netflix\.com/password'))
            if not link_tag:
                link_tag = soup.find('a', href=re.compile(r'netflix\.com'))

            if link_tag:
                return f"Reset Link: {link_tag['href']}"

    return "Reset link not found."

