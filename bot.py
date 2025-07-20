import os
import json
import base64
import logging
import re
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext, MessageHandler, Filters
from bs4 import BeautifulSoup

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Admin ID (replace with your Telegram ID)
ADMIN_ID = 1364549026

# Load credentials from environment secret (base64-encoded JSON)
credentials_json = os.getenv("GMAIL_CREDENTIALS")
if not credentials_json:
    raise Exception("Missing GMAIL_CREDENTIALS secret.")

info = json.loads(credentials_json)
creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/gmail.readonly"])

# Gmail API service
service = build("gmail", "v1", credentials=creds)

# Telegram Bot Token
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("Missing BOT_TOKEN environment variable.")

# User storage file
USERS_FILE = "users.json"

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            data = json.load(f)
            return data.get("approved", []), data.get("pending", [])
    else:
        return [], []

def save_users(approved_users, pending_users):
    data = {"approved": approved_users, "pending": pending_users}
    with open(USERS_FILE, "w") as f:
        json.dump(data, f)

approved_users, pending_users = load_users()

def is_approved(chat_id):
    return chat_id in approved_users

def get_latest_email(user_email, query):
    try:
        results = service.users().messages().list(userId=user_email, q=query, maxResults=1).execute()
        messages = results.get("messages", [])
        if not messages:
            return "No matching email found."

        msg = service.users().messages().get(userId=user_email, id=messages[0]["id"]).execute()
        payload = msg.get("payload", {})
        parts = payload.get("parts", [])

        for part in parts:
            if part.get("mimeType") == "text/html":
                data = part["body"]["data"]
                decoded = base64.urlsafe_b64decode(data).decode("utf-8")
                soup = BeautifulSoup(decoded, "html.parser")

                if "password" in query:
                    for link in soup.find_all("a", href=True):
                        if "netflix.com/password" in link["href"]:
                            return link["href"]
                else:
                    match = re.search(r">(\d{6})<", decoded)
                    if match:
                        return f"Netflix Sign-In Code: {match.group(1)}"
        return "Matching email found but no data extracted."

    except Exception as e:
        logger.error(f"Error fetching email: {e}")
        return "Error fetching email."

def start(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user = update.effective_user

    if chat_id in approved_users:
        update.message.reply_text("✅ You are already approved.")
    elif chat_id in pending_users:
        update.message.reply_text("⏳ Your request is pending admin approval.")
    else:
        pending_users.append(chat_id)
        save_users(approved_users, pending_users)
        update.message.reply_text("👋 Welcome! Request sent for approval. Please wait.")
        context.bot.send_message(chat_id=ADMIN_ID, text=f"New user requested access: {chat_id} (@{user.username})")

def approve(update: Update, context: CallbackContext):
    if update.effective_chat.id != ADMIN_ID:
        return

    if not context.args:
        update.message.reply_text("Usage: /approve <chat_id>")
        return

    try:
        chat_id = int(context.args[0])
        if chat_id not in approved_users:
            approved_users.append(chat_id)
        if chat_id in pending_users:
            pending_users.remove(chat_id)
        save_users(approved_users, pending_users)
        context.bot.send_message(chat_id=chat_id, text="✅ You are approved to use the bot!")
        update.message.reply_text("User approved.")
    except ValueError:
        update.message.reply_text("Invalid chat_id.")

def revoke(update: Update, context: CallbackContext):
    if update.effective_chat.id != ADMIN_ID:
        return

    if not context.args:
        update.message.reply_text("Usage: /revoke <chat_id>")
        return

    try:
        chat_id = int(context.args[0])
        if chat_id in approved_users:
            approved_users.remove(chat_id)
        save_users(approved_users, pending_users)
        context.bot.send_message(chat_id=chat_id, text="🚫 Access revoked by admin.")
        update.message.reply_text("User revoked.")
    except ValueError:
        update.message.reply_text("Invalid chat_id.")

def fetch(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if not is_approved(chat_id):
        update.message.reply_text("❌ You are not approved to use this bot.")
        return

    if not context.args:
        update.message.reply_text("Usage: /fetch <email>")
        return

    email = context.args[0]
    code = get_latest_email(email, "Netflix login code")
    update.message.reply_text(code)

def reset(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if not is_approved(chat_id):
        update.message.reply_text("❌ You are not approved to use this bot.")
        return

    if not context.args:
        update.message.reply_text("Usage: /reset <email>")
        return

    email = context.args[0]
    link = get_latest_email(email, "Netflix password reset")
    update.message.reply_text(link)

def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("approve", approve))
    dp.add_handler(CommandHandler("revoke", revoke))
    dp.add_handler(CommandHandler("fetch", fetch))
    dp.add_handler(CommandHandler("reset", reset))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
