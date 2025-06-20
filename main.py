import os
import json
import time
import threading
from datetime import datetime, timedelta
import requests
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# === ENV CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
GOFILE_API = "https://api.gofile.io/uploadFile"
DATA_FILE = "files.json"
PREMIUM_FILE = "premium.json"

# === JSON LOAD/SAVE ===
def load_json(file_path):
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_json(file_path, data):
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=2)

files_db = load_json(DATA_FILE)
premium_db = load_json(PREMIUM_FILE)

# === AUTO CLEANER ===
def clean_expired():
    while True:
        time.sleep(60)
        now = datetime.utcnow()
        to_delete = []
        for fid, data in list(files_db.items()):
            expiry = datetime.fromisoformat(data["expiry"])
            if data["views"] <= 0 or now > expiry:
                to_delete.append(fid)
        for fid in to_delete:
            del files_db[fid]
        save_json(DATA_FILE, files_db)

threading.Thread(target=clean_expired, daemon=True).start()

# === PREMIUM CHECK ===
def is_premium(user_id):
    if str(user_id) in premium_db:
        expiry = datetime.fromisoformat(premium_db[str(user_id)]["expires"])
        return datetime.utcnow() < expiry
    return False

# === COMMANDS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👻 Welcome to GraveBoxBot!\n"
        "Send a file or text, and I'll store it anonymously.\n"
        "Use /upload to start.\n"
        "Free users can upload files up to 10MB with 1-hour expiry."
    )

async def upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📤 Now send a file or a text message. I’ll ask about expiry after that.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    text = update.message.text
    fid = str(int(time.time()))
    files_db[fid] = {
        "uploader": user.id,
        "text": text,
        "views": 1,
        "expiry": (datetime.utcnow() + timedelta(hours=1)).isoformat()
    }
    save_json(DATA_FILE, files_db)
    await update.message.reply_text(f"✅ Text saved.\nUse /get {fid} to retrieve it.")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    file = update.message.document or update.message.video or update.message.audio or update.message.photo[-1]

    if not is_premium(user.id) and file.file_size > 10_000_000:
        await update.message.reply_text("❌ File too large. Free users are limited to 10MB.")
        return

    tg_file = await file.get_file()
    local_path = await tg_file.download_to_drive()

    with open(local_path, 'rb') as f:
        response = requests.post(GOFILE_API, files={"file": f})
        file_url = response.json()["data"]["downloadPage"]

    fid = str(int(time.time()))
    files_db[fid] = {
        "uploader": user.id,
        "url": file_url,
        "views": 1,
        "expiry": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        "filename": getattr(file, 'file_name', 'Uploaded File')
    }

    save_json(DATA_FILE, files_db)
    os.remove(local_path)
    await update.message.reply_text(f"✅ File uploaded.\nUse /get {fid} to access it.")

async def get_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /get <file_id>")
        return

    fid = args[0]
    data = files_db.get(fid)
    if not data:
        await update.message.reply_text("⚠️ File not found or expired.")
        return

    if "text" in data:
        await update.message.reply_text(data["text"])
    else:
        await update.message.reply_text(f"📎 File: {data['url']}")

    data["views"] -= 1
    if data["views"] <= 0:
        del files_db[fid]
    save_json(DATA_FILE, files_db)

async def myfiles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_files = [
        f"ID: {fid}, Views Left: {data['views']}, Expires: {data['expiry'][:16]}"
        for fid, data in files_db.items() if data["uploader"] == user_id
    ]
    await update.message.reply_text("\n".join(user_files) if user_files else "📭 No active files found.")

async def addpremium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ You're not authorized.")
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Usage: /addpremium <user_id> <days>")
        return
    uid = int(args[0])
    days = int(args[1])
    expires = (datetime.utcnow() + timedelta(days=days)).isoformat()
    premium_db[str(uid)] = {"expires": expires}
    save_json(PREMIUM_FILE, premium_db)
    await update.message.reply_text(f"✅ User {uid} upgraded to premium for {days} days.")

# === RUN BOT ===
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("upload", upload))
app.add_handler(CommandHandler("get", get_file))
app.add_handler(CommandHandler("myfiles", myfiles))
app.add_handler(CommandHandler("addpremium", addpremium))
app.add_handler(MessageHandler(filters.Document.ALL | filters.Video.ALL | filters.Audio.ALL | filters.PHOTO, handle_file))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
app.run_polling()
