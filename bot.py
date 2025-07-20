import os
import json
from telegram.ext import Updater, CommandHandler, CallbackContext
from telegram import Update
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
TOKEN = os.getenv('TELEGRAM_TOKEN')
ADMIN_ID = 123456789  # Replace with your Telegram user ID (int)
PENDING_FILE = 'pending_users.json'
APPROVED_FILE = 'approved_users.json'
CREDENTIALS_FILE = 'credentials.json'
TOKEN_FILE = 'token.json'

def load_json(filename):
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return json.load(f)
    return {}

def save_json(data, filename):
    with open(filename, 'w') as f:
        json.dump(data, f)

def gmail_authenticate():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    else:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    return build('gmail', 'v1', credentials=creds)

def search_gmail(service, email_address, keyword=None):
    query = f'from:info@account.netflix.com "{email_address}"'
    if keyword:
        query += f' subject:{keyword}'
    results = service.users().messages().list(userId='me', q=query, maxResults=5).execute()
    messages = results.get('messages', [])
    return messages

def get_message_snippet(service, message_id):
    msg = service.users().messages().get(userId='me', id=message_id, format='full').execute()
    snippet = msg.get('snippet', '')
    headers = msg.get('payload', {}).get('headers', [])
    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '(No Subject)')
    return subject, snippet

def register(update: Update, context: CallbackContext):
    chat_id = str(update.effective_chat.id)
    if len(context.args) != 1:
        update.message.reply_text("Usage: /register your_email@domain.com")
        return
    email = context.args[0].lower()

    pending = load_json(PENDING_FILE)
    approved = load_json(APPROVED_FILE)

    if email in approved:
        update.message.reply_text("You are already approved and registered.")
        return
    if email in pending:
        update.message.reply_text("Your registration is pending approval. Please wait.")
        return

    pending[email] = chat_id
    save_json(pending, PENDING_FILE)
    update.message.reply_text("Registration received. Please wait for admin approval.")

    # Notify admin
    context.bot.send_message(chat_id=ADMIN_ID,
        text=f"New registration request:\nEmail: {email}\nChat ID: {chat_id}\nApprove with /approve {email}")

def approve(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        update.message.reply_text("You are not authorized to approve users.")
        return
    if len(context.args) != 1:
        update.message.reply_text("Usage: /approve user_email@domain.com")
        return
    email = context.args[0].lower()

    pending = load_json(PENDING_FILE)
    approved = load_json(APPROVED_FILE)

    if email not in pending:
        update.message.reply_text("No pending registration found for that email.")
        return

    approved[email] = pending[email]
    del pending[email]
    save_json(pending, PENDING_FILE)
    save_json(approved, APPROVED_FILE)
    update.message.reply_text(f"User {email} approved successfully.")

    # Optionally notify the user
    context.bot.send_message(chat_id=approved[email],
        text="Your registration is approved! You can now use /get_code and /get_reset.")

def is_approved(chat_id):
    approved = load_json(APPROVED_FILE)
    return chat_id in approved.values()

def get_user_email(chat_id):
    approved = load_json(APPROVED_FILE)
    for email, cid in approved.items():
        if cid == chat_id:
            return email
    return None

def get_code(update: Update, context: CallbackContext):
    chat_id = str(update.effective_chat.id)
    if not is_approved(chat_id):
        update.message.reply_text("You are not approved yet. Please register and wait for admin approval.")
        return
    user_email = get_user_email(chat_id)
    service = gmail_authenticate()
    messages = search_gmail(service, user_email, keyword="code")
    if not messages:
        update.message.reply_text("No Netflix login code emails found for your registered email.")
        return
    message_id = messages[0]['id']
    subject, snippet = get_message_snippet(service, message_id)
    update.message.reply_text(f"*{subject}*\n\n{snippet}", parse_mode='Markdown')

def get_reset(update: Update, context: CallbackContext):
    chat_id = str(update.effective_chat.id)
    if not is_approved(chat_id):
        update.message.reply_text("You are not approved yet. Please register and wait for admin approval.")
        return
    user_email = get_user_email(chat_id)
    service = gmail_authenticate()
    messages = search_gmail(service, user_email, keyword="password reset")
    if not messages:
        update.message.reply_text("No Netflix password reset emails found for your registered email.")
        return
    message_id = messages[0]['id']
    subject, snippet = get_message_snippet(service, message_id)
    update.message.reply_text(f"*{subject}*\n\n{snippet}", parse_mode='Markdown')

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("register", register))
    dp.add_handler(CommandHandler("approve", approve))
    dp.add_handler(CommandHandler("get_code", get_code))
    dp.add_handler(CommandHandler("get_reset", get_reset))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
