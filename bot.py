import os
import json
import base64
import logging
import re
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

# Logging
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# ENV variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

# Gmail credentials
with open("credentials.json", "r") as f:
    creds_dict = json.load(f)

creds = Credentials.from_service_account_info(
    creds_dict,
    scopes=["https://www.googleapis.com/auth/gmail.readonly"]
)

gmail_service = build('gmail', 'v1', credentials=creds)


# Helper: extract reset link
def extract_reset_link_from_html(html):
    matches = re.findall(r'https://www\.netflix\.com/[^\s">]+password[^\s">]+', html)
    return matches[0] if matches else None

# Helper: extract Netflix sign-in code
def extract_signin_code(text):
    match = re.search(r'(?i)Netflix.*?code.*?(\d{6})', text)
    return match.group(1) if match else None


# Fetch Netflix reset link
def get_latest_reset_link():
    try:
        results = gmail_service.users().messages().list(
            userId='me',
            q="subject:reset netflix newer_than:2d",
            maxResults=5
        ).execute()

        messages = results.get('messages', [])

        for msg in messages:
            msg_data = gmail_service.users().messages().get(
                userId='me',
                id=msg['id'],
                format='full'
            ).execute()

            payload = msg_data.get('payload', {})
            parts = payload.get('parts', [])
            data = ""

            for part in parts:
                if part['mimeType'] == 'text/html':
                    data = part['body'].get('data')
                    break
                elif part['mimeType'] == 'text/plain' and not data:
                    data = part['body'].get('data')

            if data:
                decoded = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                link = extract_reset_link_from_html(decoded)
                if link:
                    return link
        return None
    except Exception as e:
        logging.error(f"Error fetching reset email: {e}")
        return None


# Fetch Netflix login code
def get_latest_signin_code():
    try:
        results = gmail_service.users().messages().list(
            userId='me',
            q="subject:code netflix newer_than:2d",
            maxResults=5
        ).execute()

        messages = results.get('messages', [])

        for msg in messages:
            msg_data = gmail_service.users().messages().get(
                userId='me',
                id=msg['id'],
                format='full'
            ).execute()

            payload = msg_data.get('payload', {})
            parts = payload.get('parts', [])
            data = ""

            for part in parts:
                if part['mimeType'] == 'text/plain':
                    data = part['body'].get('data')
                    break
                elif part['mimeType'] == 'text/html' and not data:
                    data = part['body'].get('data')

            if data:
                decoded = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                code = extract_signin_code(decoded)
                if code:
                    return code
        return None
    except Exception as e:
        logging.error(f"Error fetching code email: {e}")
        return None


# Commands
def start(update: Update, context: CallbackContext):
    user = update.effective_user
    chat_id = update.effective_chat.id
    name = user.full_name
    update.message.reply_text(f"👋 Welcome {name}!\n\nUse /reset to get a Netflix reset link or /code for sign-in code.")

    if ADMIN_ID:
        try:
            context.bot.send_message(chat_id=int(ADMIN_ID), text=f"🟢 New user:\n👤 {name}\n🆔 {chat_id}")
        except Exception as e:
            logging.error(f"Admin notification failed: {e}")


def reset(update: Update, context: CallbackContext):
    update.message.reply_text("🔍 Searching for Netflix reset email...")
    link = get_latest_reset_link()
    if link:
        update.message.reply_text(f"🔗 Netflix Reset Link:\n{link}")
    else:
        update.message.reply_text("❌ No recent Netflix reset link found.")


def code(update: Update, context: CallbackContext):
    update.message.reply_text("📩 Checking for latest Netflix sign-in code...")
    code = get_latest_signin_code()
    if code:
        update.message.reply_text(f"✅ Your Netflix code is: `{code}`", parse_mode="Markdown")
    else:
        update.message.reply_text("❌ No Netflix code found in recent emails.")


# Main entry
def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN not found in environment.")

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("reset", reset))
    dp.add_handler(CommandHandler("code", code))

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
