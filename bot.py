import os
import json
import logging
from datetime import datetime

from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler, CallbackContext

from gmail_utils import fetch_latest_email  # 👈 import Gmail helper

# === Logging ===
logging.basicConfig(level=logging.INFO)

# === Bot Token and Admin ID ===
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID", "1364549026"))

# === Users File ===
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

# === Activity Log File ===
LOG_FILE = "activity_logs.json"
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, "w") as f:
        json.dump([], f)

def log_activity(chat_id, username, command, target_email, link, code, status="success", error=None):
    """Save every request in activity_logs.json."""
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "chat_id": chat_id,
        "username": username,
        "command": command,
        "target_email": target_email,
        "link": link,
        "code": code,
        "status": status,
        "error": error,
    }

    try:
        with open(LOG_FILE, "r") as f:
            data = json.load(f)
    except Exception:
        data = []

    data.append(entry)

    with open(LOG_FILE, "w") as f:
        json.dump(data, f, indent=2)

# === Flask + Telegram Setup ===
bot = Bot(TOKEN)
app = Flask(__name__)
dispatcher = Dispatcher(bot, None, use_context=True)

# === Telegram Handlers ===
def start(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    users = load_users()

    if chat_id in users["approved"]:
        update.message.reply_text("✅ You are already approved. Use /get_code or /get_reset <email>")
    elif chat_id in users["pending"]:
        update.message.reply_text("⏳ You have already requested access. Please wait.")
    else:
        users["pending"].append(chat_id)
        save_users(users)
        update.message.reply_text("✅ Request received. Waiting for admin approval.")
        context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"👤 New user requested access:\nID: {chat_id}"
        )

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
        context.bot.send_message(
            chat_id=chat_id,
            text="✅ You have been approved. Use /get_code or /get_reset <email>"
        )
    else:
        update.message.reply_text("❌ User not found in pending list.")

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
        update.message.reply_text("✅ User revoked.")
        try:
            context.bot.send_message(
                chat_id=chat_id,
                text="🚫 Your access has been revoked."
            )
        except Exception:
            pass
    else:
        update.message.reply_text("❌ User not found in approved list.")

def get_code(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user = update.effective_user
    username = user.username or user.first_name or str(chat_id)

    if not is_approved(chat_id):
        update.message.reply_text("❌ Not approved.")
        return

    if not context.args:
        update.message.reply_text("Usage: /get_code <email>")
        return

    email = context.args[0]

    try:
        # digits=4 for login code
        link, code = fetch_latest_email(email, "Netflix", digits=4)

        update.message.reply_text(f"🔐 Sign-in code: {code}\n🔗 Reset link (if any): {link}")

        # Log to file
        log_activity(
            chat_id=chat_id,
            username=username,
            command="/get_code",
            target_email=email,
            link=link,
            code=code,
            status="success"
        )

        # Send log to admin
        try:
            context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "📒 LOG ENTRY\n"
                    f"👤 User: {username} (ID: {chat_id})\n"
                    f"📩 Command: /get_code\n"
                    f"🎯 Email: {email}\n"
                    f"🔐 Code: {code}\n"
                    f"🔗 Link: {link}"
                )
            )
        except Exception as e:
            logging.warning(f"Failed to send admin log: {e}")

    except Exception as e:
        err = str(e)
        update.message.reply_text(f"⚠️ Error: {err}")

        log_activity(
            chat_id=chat_id,
            username=username,
            command="/get_code",
            target_email=email,
            link="N/A",
            code="N/A",
            status="error",
            error=err
        )

        try:
            context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "❌ ERROR LOG\n"
                    f"👤 User: {username} (ID: {chat_id})\n"
                    f"📩 Command: /get_code\n"
                    f"🎯 Email: {email}\n"
                    f"⚠️ Error: {err}"
                )
            )
        except Exception:
            pass

def get_reset(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user = update.effective_user
    username = user.username or user.first_name or str(chat_id)

    if not is_approved(chat_id):
        update.message.reply_text("❌ Not approved.")
        return

    if not context.args:
        update.message.reply_text("Usage: /get_reset <email>")
        return

    email = context.args[0]

    try:
        # For reset, use different Gmail query; still reuse generic fetcher
        link, code = fetch_latest_email(email, "Netflix password reset", digits=6)

        update.message.reply_text(f"🔗 Reset link: {link}\n🔐 Code (if any): {code}")

        log_activity(
            chat_id=chat_id,
            username=username,
            command="/get_reset",
            target_email=email,
            link=link,
            code=code,
            status="success"
        )

        try:
            context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "📒 LOG ENTRY\n"
                    f"👤 User: {username} (ID: {chat_id})\n"
                    f"📩 Command: /get_reset\n"
                    f"🎯 Email: {email}\n"
                    f"🔐 Code: {code}\n"
                    f"🔗 Link: {link}"
                )
            )
        except Exception as e:
            logging.warning(f"Failed to send admin log: {e}")

    except Exception as e:
        err = str(e)
        update.message.reply_text(f"⚠️ Error: {err}")

        log_activity(
            chat_id=chat_id,
            username=username,
            command="/get_reset",
            target_email=email,
            link="N/A",
            code="N/A",
            status="error",
            error=err
        )

        try:
            context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "❌ ERROR LOG\n"
                    f"👤 User: {username} (ID: {chat_id})\n"
                    f"📩 Command: /get_reset\n"
                    f"🎯 Email: {email}\n"
                    f"⚠️ Error: {err}"
                )
            )
        except Exception:
            pass

# === Register Telegram Handlers ===
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("approve", approve))
dispatcher.add_handler(CommandHandler("revoke", revoke))
dispatcher.add_handler(CommandHandler("get_code", get_code))
dispatcher.add_handler(CommandHandler("get_reset", get_reset))

# === Flask Routes ===
@app.route("/", methods=["GET"])
def index():
    return "Bot is running."

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "ok"

# === Start Server + Webhook ===
if __name__ == "__main__":
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    if not WEBHOOK_URL:
        raise Exception("Missing WEBHOOK_URL")

    full_url = f"{WEBHOOK_URL.rstrip('/')}/{TOKEN}"
    bot.set_webhook(full_url)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
