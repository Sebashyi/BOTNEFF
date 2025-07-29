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
from datetime import datetime

# === Logging ===
logging.basicConfig(level=logging.INFO)

# === Config ===
TOKEN = os.getenv("BOT_TOKEN")  # No hardcoded token
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID", "1364549026"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
USERS_FILE = "users.json"
USAGE_LIMIT = 20  # daily code fetch limit

# === Setup user files ===
if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, "w") as f:
        json.dump({"pending": [], "approved": [], "usage": {}}, f)

def load_users():
    with open(USERS_FILE, "r") as f:
        return json.load(f)

def save_users(data):
    with open(USERS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def is_approved(chat_id):
    return chat_id in load_users().get("approved", [])

def can_use(chat_id):
    users = load_users()
    usage = users.get("usage", {})
    today = datetime.utcnow().strftime("%Y-%m-%d")
    user_data = usage.get(str(chat_id), {})
    if user_data.get("date") != today:
        usage[str(chat_id)] = {"count": 0, "date": today}
        save_users(users)
        return True
    return user_data.get("count", 0) < USAGE_LIMIT

def record_usage(chat_id):
    users = load_users()
    usage = users.get("usage", {})
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if str(chat_id) not in usage or usage[str(chat_id)].get("date") != today:
        usage[str(chat_id)] = {"count": 1, "date": today}
    else:
        usage[str(chat_id)]["count"] += 1
    users["usage"] = usage
    save_users(users)

# === Gmail Auth ===
if not os.path.exists("/etc/secrets/GMAIL_CREDENTIALS"):
    raise Exception("Missing GMAIL_CREDENTIALS secret.")

with open("/etc/secrets/GMAIL_CREDENTIALS", "r") as f:
    creds_dict = json.load(f)

creds = Credentials.from_authorized_user_info(creds_dict)
service = build("gmail", "v1", credentials=creds)

# === Gmail Extraction ===
def extract_netflix_content(msg_body, digits=4):
    links = re.findall(r'https://www\.netflix\.com/[^\s"<]+', msg_body)
    codes = re.findall(rf'(?<!\d)(\d{{{digits}}})(?!\d)', msg_body)
    return links[0] if links else "No reset link found", codes[0] if codes else "No code found"

def fetch_latest_email(email, query, digits=4):
    result = service.users().messages().list(userId='me', q=f'to:{email} {query}', maxResults=1).execute()
    messages = result.get('messages', [])
    if not messages:
        return "No email found", "N/A"
    msg = service.users().messages().get(userId='me', id=messages[0]['id'], format='full').execute()
    payload = msg['payload']
    body = ""

    if 'parts' in payload:
        for part in payload['parts']:
            if part.get('mimeType') == 'text/plain' and 'data' in part['body']:
                body = base64.urlsafe_b64decode(part['body']['data']).decode()
                break
    elif 'body' in payload and 'data' in payload['body']:
        body = base64.urlsafe_b64decode(payload['body']['data']).decode()

    return extract_netflix_content(body, digits)

# === Flask + Telegram Setup ===
bot = Bot(TOKEN)
app = Flask(__name__)
dispatcher = Dispatcher(bot, None, use_context=True)

# === Telegram Commands ===
def start(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    users = load_users()
    if chat_id in users["approved"]:
        update.message.reply_text("✅ Already approved. Use /get_code or /get_reset <email>")
    elif chat_id in users["pending"]:
        update.message.reply_text("⏳ Already requested access. Please wait.")
    else:
        users["pending"].append(chat_id)
        save_users(users)
        update.message.reply_text("📩 Request received. Wait for admin approval.")
        context.bot.send_message(chat_id=ADMIN_ID, text=f"🆕 New request:\nID: {chat_id}")

def approve(update: Update, context: CallbackContext):
    if update.effective_chat.id != ADMIN_ID:
        return
    if not context.args:
        update.message.reply_text("Usage: /approve <chat_id>")
        return
    chat_id = int(context.args[0])
    users = load_users()
    if chat_id in users["pending"]:
        users["pending"].remove(chat_id)
        users["approved"].append(chat_id)
        save_users(users)
        update.message.reply_text("✅ Approved.")
        context.bot.send_message(chat_id=chat_id, text="✅ You are approved. Use /get_code or /get_reset <email>")
    else:
        update.message.reply_text("❌ Not found in pending list.")

def revoke(update: Update, context: CallbackContext):
    if update.effective_chat.id != ADMIN_ID:
        return
    if not context.args:
        update.message.reply_text("Usage: /revoke <chat_id>")
        return
    chat_id = int(context.args[0])
    users = load_users()
    if chat_id in users["approved"]:
        users["approved"].remove(chat_id)
        save_users(users)
        context.bot.send_message(chat_id=chat_id, text="🚫 Your access is revoked.")
        update.message.reply_text("✅ Revoked.")
    else:
        update.message.reply_text("❌ Not in approved list.")

def get_code(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if not is_approved(chat_id):
        return update.message.reply_text("❌ Not approved.")
    if not can_use(chat_id):
        return update.message.reply_text("🚫 Daily limit reached (20 codes). Try tomorrow.")
    if not context.args:
        return update.message.reply_text("Usage: /get_code <email>")
    email = context.args[0]
    link, code = fetch_latest_email(email, "Netflix", digits=4)
    record_usage(chat_id)
    update.message.reply_text(f"🔐 Sign-in code: {code}\n🔗 Link: {link}")

def get_reset(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if not is_approved(chat_id):
        return update.message.reply_text("❌ Not approved.")
    if not can_use(chat_id):
        return update.message.reply_text("🚫 Daily limit reached (20 codes). Try tomorrow.")
    if not context.args:
        return update.message.reply_text("Usage: /get_reset <email>")
    email = context.args[0]
    link, code = fetch_latest_email(email, "Netflix password reset", digits=6)
    record_usage(chat_id)
    update.message.reply_text(f"🔗 Reset link: {link}\n🔐 Code: {code}")

# === Register Telegram Handlers ===
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("approve", approve))
dispatcher.add_handler(CommandHandler("revoke", revoke))
dispatcher.add_handler(CommandHandler("get_code", get_code))
dispatcher.add_handler(CommandHandler("get_reset", get_reset))

# === Flask Webhook Routes ===
@app.route("/", methods=["GET"])
def index():
    return "Bot is running."

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "ok"

# === Start Server ===
if __name__ == "__main__":
    if not WEBHOOK_URL:
        raise Exception("Missing WEBHOOK_URL env var")
    bot.set_webhook(f"{WEBHOOK_URL.rstrip('/')}/{TOKEN}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
