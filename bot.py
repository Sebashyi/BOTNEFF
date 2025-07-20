import os
import json
import logging
import pickle
import base64
import re

from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# ====== CONFIGURATION =======
ADMIN_CHAT_ID = 1364549026  # replace with your Telegram ID
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
CREDENTIALS_FILE = 'credentials.json'
TOKEN_FILE = 'token.pickle'
USERS_FILE = 'users.json'

BOT_TOKEN = os.environ.get('BOT_TOKEN')

# ============================

# ---- Gmail Auth ----
def get_gmail_credentials():
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)
    return creds

def get_gmail_service():
    creds = get_gmail_credentials()
    return build('gmail', 'v1', credentials=creds)

# ---- User Management ----
def load_users():
    if not os.path.exists(USERS_FILE):
        return {"approved": [], "pending": []}
    with open(USERS_FILE, "r") as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f)

def is_approved(chat_id):
    users = load_users()
    return chat_id in users["approved"]

def add_pending_user(chat_id):
    users = load_users()
    if chat_id not in users["pending"] and chat_id not in users["approved"]:
        users["pending"].append(chat_id)
        save_users(users)
        return True
    return False

def approve_user(chat_id):
    users = load_users()
    if chat_id in users["pending"]:
        users["pending"].remove(chat_id)
    if chat_id not in users["approved"]:
        users["approved"].append(chat_id)
    save_users(users)

def get_latest_email(service, user_id='me', query='from:info@mailer.netflix.com'):
    results = service.users().messages().list(userId=user_id, q=query, maxResults=1).execute()
    messages = results.get('messages', [])
    if not messages:
        return None

    msg = service.users().messages().get(userId=user_id, id=messages[0]['id'], format='full').execute()
    parts = msg['payload'].get('parts', [])
    body = ""

    for part in parts:
        if part['mimeType'] == 'text/html':
            body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
            break
    return body

def extract_reset_link(body):
    match = re.search(r'href="(https://www\.netflix\.com/[^\"]*password[^\"]*)"', body)
    return match.group(1) if match else "Reset link not found."

def extract_code(body):
    match = re.search(r'(\d{6})', body)
    return match.group(1) if match else "No code found."

# ---- Bot Handlers ----
def start(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_added = add_pending_user(chat_id)
    context.bot.send_message(chat_id, "👋 Welcome! Your ID has been sent to the admin for approval.")
    if user_added:
        context.bot.send_message(ADMIN_CHAT_ID, f"New user requested access:\nChat ID: {chat_id}")

def get_reset(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if not is_approved(chat_id):
        update.message.reply_text("⛔ You are not approved yet.")
        return

    try:
        service = get_gmail_service()
        body = get_latest_email(service)
        if not body:
            update.message.reply_text("No email found.")
            return

        link = extract_reset_link(body)
        update.message.reply_text(f"🔗 Reset link:\n{link}")
    except Exception as e:
        update.message.reply_text("Error fetching reset link.")
        logger.error(e)

def get_code(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if not is_approved(chat_id):
        update.message.reply_text("⛔ You are not approved yet.")
        return

    try:
        service = get_gmail_service()
        body = get_latest_email(service)
        if not body:
            update.message.reply_text("No email found.")
            return

        code = extract_code(body)
        update.message.reply_text(f"🔢 Login code: {code}")
    except Exception as e:
        update.message.reply_text("Error fetching code.")
        logger.error(e)

def approve(update: Update, context: CallbackContext):
    if update.effective_chat.id != ADMIN_CHAT_ID:
        update.message.reply_text("⛔ Unauthorized.")
        return
    try:
        chat_id = int(context.args[0])
        approve_user(chat_id)
        update.message.reply_text(f"✅ Approved user {chat_id}")
    except:
        update.message.reply_text("Usage: /approve <chat_id>")

def pending(update: Update, context: CallbackContext):
    if update.effective_chat.id != ADMIN_CHAT_ID:
        update.message.reply_text("⛔ Unauthorized.")
        return
    users = load_users()
    update.message.reply_text(f"📌 Pending Users:\n" + "\n".join(map(str, users["pending"])))

# ---- Main Entry ----
def main():
    if not BOT_TOKEN:
        raise Exception("Missing BOT_TOKEN environment variable.")
    if not os.path.exists(CREDENTIALS_FILE):
        raise Exception("Missing credentials.json file.")
    
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("getreset", get_reset))
    dp.add_handler(CommandHandler("getcode", get_code))
    dp.add_handler(CommandHandler("approve", approve, pass_args=True))
    dp.add_handler(CommandHandler("pending", pending))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()

