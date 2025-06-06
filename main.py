import os
import time
import requests
import telebot
from io import BytesIO
from keep_alive import keep_alive
import openai
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.units import cm

# Подключаем переменные окружения
bot_token = os.getenv("TELEGRAM_TOKEN")
assembly_key = os.getenv("ASSEMBLYAI_API_KEY")
openai.api_key = os.getenv("OPENAI_API_KEY")

if not bot_token or not assembly_key or not openai.api_key:
    raise ValueError("Один или несколько API ключей не заданы")

bot = telebot.TeleBot(bot_token)
keep_alive()

def generate_pdf(dialog_text, analysis_text):
    buffer = BytesIO()

    # Используем встроенный шрифт для поддержки Юникода
    pdfmetrics.registerFont(UnicodeCIDFont('HeiseiKakuGo-W5'))

    c = canvas.Canvas(buffer, pagesize=A4)
    c.setFont('HeiseiKakuGo-W5', 12)
    width, height = A4
    x, y = 2 * cm, height - 2 * cm

    def draw_text_block(title, text):
        nonlocal y
        c.setFont('HeiseiKakuGo-W5', 14)
        c.drawString(x, y, title)
        y -= 20
        c.setFont('HeiseiKakuGo-W5', 12)
        for line in text.split("\n"):
            if y < 2 * cm:
                c.showPage()
                y = height - 2 * cm
                c.setFont('HeiseiKakuGo-W5', 12)
            c.drawString(x, y, line)
            y -= 15
        y -= 10

    draw_text_block("Диалог", dialog_text)
    draw_text_block("Анализ", analysis_text)

    c.save()
    buffer.seek(0)
    return buffer

def analyze_dialog(dialog_text):
    prompt = (
        "Ты эксперт по продажам. Проанализируй диалог менеджера и клиента:\n"
        "1. Сильные стороны менеджера\n"
        "2. Слабые места\n"
        "3. Рекомендации по улучшению\n\n"
        f"Диалог:\n{dialog_text}"
    )

    try:
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Ты эксперт по оценке звонков в продажах."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"⚠️ Ошибка анализа: {e}"

@bot.message_handler(content_types=['audio', 'voice'])
def handle_audio(message):
    try:
        file_id = message.audio.file_id if message.audio else message.voice.file_id
        file_info = bot.get_file(file_id)
        file_url = f"https://api.telegram.org/file/bot{bot_token}/{file_info.file_path}"

        bot.reply_to(message, "⏳ Загружаю файл...")

        audio_data = requests.get(file_url).content

        upload_resp = requests.post(
            "https://api.assemblyai.com/v2/upload",
            headers={"authorization": assembly_key},
            data=audio_data
        )
        if upload_resp.status_code != 200:
            bot.reply_to(message, f"❌ Ошибка загрузки: {upload_resp.text}")
            return

        audio_url = upload_resp.json()["upload_url"]

        transcript_req = requests.post(
            "https://api.assemblyai.com/v2/transcript",
            headers={"authorization": assembly_key},
            json={
                "audio_url": audio_url,
                "language_code": "ru",
                "speaker_labels": True
            }
        )

        transcript_id = transcript_req.json().get("id")
        if not transcript_id:
            bot.reply_to(message, f"❌ Ошибка создания транскрипта: {transcript_req.text}")
            return

        bot.reply_to(message, "🔁 Распознаю речь...")

        polling_url = f"https://api.assemblyai.com/v2/transcript/{transcript_id}"
        start_time = time.time()

        while True:
            poll = requests.get(polling_url, headers={"authorization": assembly_key}).json()

            if poll["status"] == "completed":
                utterances = poll.get("utterances", [])
                if utterances:
                    speaker_a = utterances[0]["speaker"]
                    speaker_b = next((u["speaker"] for u in utterances if u["speaker"] != speaker_a), None)
                    speaker_map = {
                        speaker_a: "Менеджер",
                        speaker_b: "Клиент"
                    }
                    dialog_text = ""
                    for utt in utterances:
                        speaker = speaker_map.get(utt["speaker"], f"Спикер {utt['speaker']}")
                        dialog_text += f"{speaker}: {utt['text']}\n"
                else:
                    dialog_text = poll.get("text", "⚠️ Нет распознанного текста.")

                bot.reply_to(message, "📊 Анализирую разговор...")
                analysis = analyze_dialog(dialog_text)

                bot.reply_to(message, "📄 Формирую отчет...")
                pdf_buffer = generate_pdf(dialog_text, analysis)

                bot.send_document(message.chat.id, ("report.pdf", pdf_buffer))
                break

            elif poll["status"] == "error":
                bot.reply_to(message, f"❌ Ошибка AssemblyAI: {poll['error']}")
                break

            elif time.time() - start_time > 60:
                bot.reply_to(message, "⏰ Тайм-аут: файл обрабатывается слишком долго.")
                break

            time.sleep(5)

    except Exception as e:
        bot.reply_to(message, f"🚨 Внутренняя ошибка:\n{e}")

bot.polling(none_stop=True)
