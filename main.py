import os
import time
import requests
from telegram import Update, Bot
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

ASSEMBLY_KEY = "ad65dc7849144c6c9832ab85649d6554"
TELEGRAM_TOKEN = "ВАШ_ТЕЛЕГРАМ_ТОКЕН"

HEADERS = {"authorization": ASSEMBLY_KEY}

def start(update: Update, context: CallbackContext):
    update.message.reply_text("Привет! Отправь мне аудиофайл (mp3/wav), и я расшифрую его текст.")

def transcribe_file(file_path):
    with open(file_path, 'rb') as f:
        upload_resp = requests.post(
            "https://api.assemblyai.com/v2/upload",
            headers=HEADERS,
            files={'file': f}
        )
    audio_url = upload_resp.json()["upload_url"]

    transcript_resp = requests.post(
        "https://api.assemblyai.com/v2/transcript",
        headers=HEADERS,
        json={"audio_url": audio_url, "language_code": "ru"}
    )
    transcript_id = transcript_resp.json()["id"]

    # Polling
    while True:
        poll = requests.get(f"https://api.assemblyai.com/v2/transcript/{transcript_id}", headers=HEADERS)
        status = poll.json()["status"]
        if status == "completed":
            return poll.json()["text"]
        elif status == "error":
            return f"Ошибка: {poll.json()['error']}"
        time.sleep(5)

def handle_audio(update: Update, context: CallbackContext):
    file = update.message.audio or update.message.voice or update.message.document
    if not file:
        update.message.reply_text("Пожалуйста, отправь mp3/wav файл.")
        return

    file_path = f"{file.file_id}.mp3"
    file.get_file().download(file_path)

    update.message.reply_text("Обрабатываю... ⏳")

    text = transcribe_file(file_path)
    os.remove(file_path)

    if text:
        update.message.reply_text("📝 Текст звонка:\n\n" + text[:4000])  # Telegram ограничение
    else:
        update.message.reply_text("Ошибка при транскрибации.")

def main():
    updater = Updater(TELEGRAM_TOKEN)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.audio | Filters.voice | Filters.document, handle_audio))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
