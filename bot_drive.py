import os
import pickle
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# =========================
# CONFIG
# =========================

TELEGRAM_TOKEN = "8403023355:AAGPj8Qe0Etumr8d9alVGUbndlTHdP_zo_U"

SCOPES = ['https://www.googleapis.com/auth/drive.file']

FOLDERS = {
    "Alquiler": "ID_CARPETA_ALQUILER",
    "Luz": "ID_CARPETA_LUZ",
    "Otros": "ID_CARPETA_OTROS"
}

# =========================
# GOOGLE DRIVE AUTH
# =========================

def get_drive_service():
    creds = None

    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)

        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    return build('drive', 'v3', credentials=creds)

drive_service = get_drive_service()

# =========================
# LOGICA
# =========================

def get_categoria(texto):
    if not texto:
        return "Otros"

    texto = texto.lower()

    if "alquiler" in texto:
        return "Alquiler"
    elif "luz" in texto:
        return "Luz"
    else:
        return "Otros"


def upload_file(file_path, file_name, folder_id):
    file_metadata = {
        'name': file_name,
        'parents': [folder_id]
    }

    media = MediaFileUpload(file_path)

    file = drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id'
    ).execute()

    return file.get('id')

# =========================
# HANDLER
# =========================

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message

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
        await message.reply_text("❌ Enviá una imagen o PDF con texto")
        return

    if not text:
        await message.reply_text("❌ Agregá un texto (ej: Alquiler Marzo 2026)")
        return

    file_name = f"{text}{ext}"
    categoria = get_categoria(text)
    folder_id = FOLDERS.get(categoria, FOLDERS["Otros"])

    temp_path = f"temp{ext}"
    await file.download_to_drive(temp_path)

    try:
        upload_file(temp_path, file_name, folder_id)

        await message.reply_text(
            f"✅ Guardado en {categoria} como:\n{file_name}"
        )

    except Exception as e:
        await message.reply_text(f"❌ Error: {str(e)}")

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

# =========================
# MAIN
# =========================

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(
        MessageHandler(filters.Document.ALL | filters.PHOTO, handle_file)
    )

    print("Bot corriendo...")
    app.run_polling()

if __name__ == "__main__":
    main()
