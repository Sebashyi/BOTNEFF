import os
import logging
import base64
import re
import html
from email import message_from_bytes
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from dotenv import load_dotenv

load_dotenv()  # Optional: only needed for local .env testing

# Get environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID"))
CLIENT_ID = os.environ.get("CLIENT_ID")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
REFRESH_TOKEN = os.environ.get("REFRESH_TOKEN")

logging.basicConfig(level=logging.INFO)

approved_users = set()
pending_users = set()

def get_gmail_service():
    creds = Credentials(
        None,
        refresh_token=REFRESH_TOKEN,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("gmail", "v1", credentials=creds)

def is_approved(chat_id):
    return chat_id in approved_users or chat_id == ADMIN_CHAT_ID

def extract_reset_link(body):
    links = re.findall(r'href=[\'"]?([^\'" >]+)', body)
    for link in links:
        if "netflix.com/password" in link:
            return link
    match = re.search(r'https://www\.netflix\.com/[^\s<"]+', body)
    return match.group(0) if match else None

def extract_signin_code(body):
    code_match = re.search(r'(\d{6})', body)
    return code_match.group(1) if code_match else None

def get_latest_email_content(email, search_type):
    payload = email["payload"]
    parts = payload.get("parts", [])
    body = ""

    if "data" in payload.get("body", {}):
        body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")
    else:
        for part in parts:
            if "text/html" in part.get("mimeType", ""):
                body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="ignore")
                break

    body = html.unescape(body)

    if search_type == "reset":
        return extract_reset_link(body) or "❌ No reset link found."
    else:
        return extract_signin_code(body) or "❌ No sign-in code found."

def fetch_email(update: Update, context: CallbackContext, search_type: str):
    chat_id = update.effective_chat.id
    if not is_approved(chat_id):
        pending_users.add(chat_id)
        update.message.reply_text("⏳ Your access request has been sent to the admin.")
        return

    args = context.args
    if not args:
        update.message.reply_text("Please provide an email address.")
        return

    user_email = args[0]
    service = get_gmail_service()
    query = f"from:info@mailer.netflix.com to:{user_email} {'reset' if search_type == 'reset' else 'code'}"

    results = service.users().messages().list(userId="me", q=query, maxResults=1).execute()
    messages = results.get("messages", [])

    if not messages:
        update.message.reply_text("❌ No matching emails found.")
        return

    msg = service.users().messages().get(userId="me", id=messages[0]["id"], format="full").execute()
    content = get_latest_email_content(msg, search_type)
    update.message.reply_text(f"✅ Latest Netflix {'Reset Link' if search_type == 'reset' else 'Code'}:\n\n{content}")

def start(update: Update, context: CallbackContext):
    update.message.reply_text("👋 Welcome! Use /get_code <email> or /get_reset <email> to begin.")

def get_code(update: Update, context: CallbackContext):
    fetch_email(update, context, search_type="code")

def get_reset(update: Update, context: CallbackContext):
    fetch_email(update, context, search_type="reset")

def approve_user(update: Update, context: CallbackContext):
    if update.effective_chat.id != ADMIN_CHAT_ID:
        return

    args = context.args
    if not args:
        update.message.reply_text("Usage: /approve <chat_id>")
        return

    try:
        chat_id = int(args[0])
        approved_users.add(chat_id)
        pending_users.discard(chat_id)
        update.message.reply_text(f"✅ Approved user {chat_id}")
    except ValueError:
        update.message.reply_text("❌ Invalid chat_id.")

def list_pending(update: Update, context: CallbackContext):
    if update.effective_chat.id == ADMIN_CHAT_ID:
        update.message.reply_text(f"⏳ Pending Users:\n{list(pending_users)}")

def list_approved(update: Update, context: CallbackContext):
    if update.effective_chat.id == ADMIN_CHAT_ID:
        update.message.reply_text(f"✅ Approved Users:\n{list(approved_users)}")

def revoke_user(update: Update, context: CallbackContext):
    if update.effective_chat.id != ADMIN_CHAT_ID:
        return

    args = context.args
    if not args:
        update.message.reply_text("Usage: /revoke <chat_id>")
        return

    try:
        chat_id = int(args[0])
        approved_users.discard(chat_id)
        update.message.reply_text(f"🚫 Revoked access for user {chat_id}")
    except ValueError:
        update.message.reply_text("❌ Invalid chat_id.")

def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("get_code", get_code))
    dp.add_handler(CommandHandler("get_reset", get_reset))
    dp.add_handler(CommandHandler("approve", approve_user))
    dp.add_handler(CommandHandler("pending", list_pending))
    dp.add_handler(CommandHandler("approved", list_approved))
    dp.add_handler(CommandHandler("revoke", revoke_user))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
