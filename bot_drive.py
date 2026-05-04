import os
import re
import json
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account

# =========================
# CONFIG
# =========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
PARENT_FOLDER_ID = os.getenv("PARENT_FOLDER_ID")

SCOPES = ['https://www.googleapis.com/auth/drive.file']

# =========================
# GOOGLE DRIVE AUTH
# =========================

def get_drive_service():
    json_str = os.getenv("SERVICE_ACCOUNT_JSON")

    if not json_str:
        raise ValueError("❌ Falta SERVICE_ACCOUNT_JSON")

    creds_dict = json.loads(json_str)

    creds = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=SCOPES
    )

    return build('drive', 'v3', credentials=creds)

drive_service = get_drive_service()

# =========================
# DRIVE HELPERS
# =========================

def list_folders(service, parent_id):
    query = f"mimeType = 'application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed = false"

    results = service.files().list(
        q=query,
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()

    return results.get('files', [])


def find_folder(service, folder_name, parent_id):
    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed = false"

    results = service.files().list(
        q=query,
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()

    files = results.get('files', [])
    return files[0]['id'] if files else None


def create_folder(service, folder_name, parent_id):
    file_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_id]
    }

    folder = service.files().create(
        body=file_metadata,
        fields='id',
        supportsAllDrives=True
    ).execute()

    return folder.get('id')


def get_or_create_folder(service, folder_name, parent_id):
    folder_id = find_folder(service, folder_name, parent_id)
    if folder_id:
        return folder_id
    return create_folder(service, folder_name, parent_id)


def upload_file(file_path, file_name, folder_id):
    file_metadata = {
        'name': file_name,
        'parents': [folder_id]
    }

    media = MediaFileUpload(file_path)

    file = drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id',
        supportsAllDrives=True
    ).execute()

    return file.get('id')

# =========================
# HELPERS
# =========================

def extract_year(text):
    if not text:
        return str(datetime.now().year)

    match = re.search(r"(20\d{2})", text)
    if match:
        return match.group(1)

    return str(datetime.now().year)

# =========================
# STATE
# =========================

user_states = {}

# =========================
# HANDLERS
# =========================

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user_id = message.from_user.id

    text = message.caption or message.text

    file = None
    ext = ""

    if message.document:
        file = await message.document.get_file()
        ext = ".pdf"
    elif message.photo:
        file = await message.photo[-1].get_file()
        ext = ".jpg"

    if not file:
        await message.reply_text("❌ Enviá un archivo válido")
        return

    temp_path = f"temp_{user_id}{ext}"
    await file.download_to_drive(temp_path)

    user_states[user_id] = {
        "file_path": temp_path,
        "file_name": f"{text}{ext}" if text else f"archivo{ext}",
        "waiting_for_folder_name": False
    }

    folders = list_folders(drive_service, PARENT_FOLDER_ID)

    keyboard = [
        [InlineKeyboardButton(f["name"], callback_data=f"folder_{f['id']}")]
        for f in folders
    ]

    keyboard.append([InlineKeyboardButton("➕ Nueva carpeta", callback_data="new_folder")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await message.reply_text(
        "📁 ¿En qué carpeta querés guardarlo?",
        reply_markup=reply_markup
    )


async def handle_folder_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if user_id not in user_states:
        await query.edit_message_text("❌ No hay archivo pendiente")
        return

    data = query.data

    if data == "new_folder":
        user_states[user_id]["waiting_for_folder_name"] = True
        await query.edit_message_text("✏️ Escribí el nombre de la nueva carpeta:")
        return

    parent_folder_id = data.replace("folder_", "")
    state = user_states[user_id]

    year = extract_year(state["file_name"])
    year_folder_id = get_or_create_folder(drive_service, year, parent_folder_id)

    try:
        upload_file(state["file_path"], state["file_name"], year_folder_id)

        await query.edit_message_text(
            f"✅ Guardado en {year} como:\n{state['file_name']}"
        )

    except Exception as e:
        await query.edit_message_text(f"❌ Error: {str(e)}")

    finally:
        if os.path.exists(state["file_path"]):
            os.remove(state["file_path"])
        del user_states[user_id]


async def handle_new_folder_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if user_id not in user_states:
        return

    state = user_states[user_id]

    if not state.get("waiting_for_folder_name"):
        return

    folder_name = update.message.text

    try:
        main_folder_id = create_folder(drive_service, folder_name, PARENT_FOLDER_ID)

        year = extract_year(state["file_name"])
        year_folder_id = get_or_create_folder(drive_service, year, main_folder_id)

        upload_file(state["file_path"], state["file_name"], year_folder_id)

        await update.message.reply_text(
            f"✅ Carpeta '{folder_name}/{year}' creada y archivo guardado"
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

    finally:
        if os.path.exists(state["file_path"]):
            os.remove(state["file_path"])
        del user_states[user_id]

# =========================
# MAIN
# =========================

def main():
    if not TELEGRAM_TOKEN:
        raise ValueError("❌ Falta TELEGRAM_TOKEN")

    if not PARENT_FOLDER_ID:
        raise ValueError("❌ Falta PARENT_FOLDER_ID")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_file))
    app.add_handler(CallbackQueryHandler(handle_folder_selection))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_folder_name))

    print("Bot corriendo...")
    app.run_polling()


if __name__ == "__main__":
    main()
