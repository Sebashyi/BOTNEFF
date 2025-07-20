import os
import json
import logging
import base64
import re
from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler, CallbackContext
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# === Logging ===
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# === Bot Token and Admin ===
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID", "1364549026"))

# === Load Users ===
USERS_FILE = "users.json"
if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, "w") as f:
        json.dump({"pending": [], "approved": []}, f)

def load_users():
    with open(USERS_FILE, "r") as f:
        return json.load(f)

def save_users(data):
    with open(USERS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def is_approved(chat_id):
    return chat_id in load_users().get("approved", [])

# === Gmail Auth ===
if not os.path.exists("/etc/secrets/GMAIL_CREDENTIALS"):
    raise Exception("Missing GMAIL_CREDENTIALS secret.")

with open("/etc/secrets/GMAIL_CREDENTIALS", "r") as f:
    creds_dict = json.load(f)

creds = Credentials.from_authorized_user_info(creds_dict)
service = build("gmail", "v1", credentials=creds)

# === Gmail Helpers ===
def extract_reset_link_and_code(msg_body):
    links = re.findall(r'https://www\.netflix\.com/[^\s"<]+', msg_body)
    codes = re.findall(r'(?<!\d)(\d{4})(?!\d)', msg_body)  # Netflix now uses 4-digit codes
    return links[0] if links else "No reset link found", codes[0] if codes else "No code found"

def fetch_latest_email(query):
    result = service.users().messages().list(userId='me', q=query, maxResults=1).execute()
    messages = result.get('messages', [])
    if not messages:
        return "No email found.", "N/A"
    msg = service.users().messages().get(userId='me', id=messages[0]['id'], format='full').execute()
    parts = msg['payload'].get('parts', [])
    body = ""
    for part in parts:
        if part['mimeType'] == 'text/plain':
            body = base64.urlsafe_b64decode(part['body']['data']).decode()
            break
    return extract_reset_link_and_code(body)

# === Flask + Telegram Webhook Setup ===
bot = Bot(TOKEN)
app = Flask(__name__)
dispatcher = Dispatcher(bot, None, use_context=True)

# === Handlers ===
def start(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    users = load_users()
    if chat_id in users["approved"]:
        update.message.reply_text("✅ You are already approved. Use /get_code or /get_reset")
    elif chat_id in users["pending"]:
        update.message.reply_text("⏳ You have already requested access. Please wait.")
    else:
        users["pending"].append(chat_id)
        save_users(users)
        update.message.reply_text("✅ Request received. Waiting for admin approval.")
        context.bot.send_message(chat_id=ADMIN_ID, text=f"👤 New user requested access:\nID: {chat_id}")

def approve(update: Update, context: CallbackContext):
    if update.effective_chat.id != ADMIN_ID:
        return
    args = context.args
    if not args:
        update.message.reply_text("Usage: /approve <chat_id>")
        return
    chat_id = int(args[0])
    users = load_users()
    if chat_id in users["pending"]:
        users["pending"].remove(chat_id)
        users["approved"].append(chat_id)
        save_users(users)
        update.message.reply_text("✅ User approved.")
        context.bot.send_message(chat_id=chat_id, text="✅ You have been approved. You can now use /get_code or /get_reset")
    else:
        update.message.reply_text("❌ User not found in pending list.")

def revoke(update: Update, context: CallbackContext):
    if update.effective_chat.id != ADMIN_ID:
        return
    args = context.args
    if not args:
        update.message.reply_text("Usage: /revoke <chat_id>")
        return
    chat_id = int(args[0])
    users = load_users()
    if chat_id in users["approved"]:
        users["approved"].remove(chat_id)
        save_users(users)
        update.message.reply_text(f"✅ User {chat_id} has been revoked.")
        context.bot.send_message(chat_id=chat_id, text="❌ Your access has been revoked by the admin.")
    else:
        update.message.reply_text("❌ This user is not in the approved list.")

def get_code(update: Update, context: CallbackContext):
    if not is_approved(update.effective_chat.id):
        update.message.reply_text("❌ Not approved.")
        return
    update.message.reply_text("⏳ Fetching latest Netflix login code...")
    link, code = fetch_latest_email("subject:'Netflix sign-in code' OR from:info@mailer.netflix.com")
    update.message.reply_text(f"🔐 Sign-in code: {code}\n🔗 Reset link (if any): {link}")

def get_reset(update: Update, context: CallbackContext):
    if not is_approved(update.effective_chat.id):
        update.message.reply_text("❌ Not approved.")
        return
    update.message.reply_text("⏳ Fetching latest Netflix password reset email...")
    link, code = fetch_latest_email("subject:'Netflix password reset' OR from:info@mailer.netflix.com")
    update.message.reply_text(f"🔗 Reset link: {link}\n🔐 Code (if any): {code}")

# === Register Handlers ===
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("approve", approve))
dispatcher.add_handler(CommandHandler("revoke", revoke))
dispatcher.add_handler(CommandHandler("get_code", get_code))
dispatcher.add_handler(CommandHandler("get_reset", get_reset))

# === Flask Webhook Routes ===
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "ok"

@app.route("/", methods=["GET"])
def index():
    return "Bot is running with webhook"

if __name__ == "__main__":
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    if not WEBHOOK_URL:
        raise Exception("Missing WEBHOOK_URL")
    bot.set_webhook(f"{WEBHOOK_URL}/{TOKEN}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

