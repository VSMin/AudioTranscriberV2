import os
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from services.transcriber import transcribe_audio
from services.analyzer import analyze_transcript
from dotenv import load_dotenv
import tempfile

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.audio.get_file() if update.message.audio else await update.message.voice.get_file()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
        await file.download_to_drive(tmp.name)
        await update.message.reply_text("⏳ Обрабатываю аудио...")

        transcript = transcribe_audio(tmp.name)
        if not transcript:
            await update.message.reply_text("❌ Ошибка при транскрибации.")
            return

        analysis = analyze_transcript(transcript)
        await update.message.reply_text(analysis)

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.AUDIO | filters.VOICE, handle_audio))
    print("🤖 Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()
