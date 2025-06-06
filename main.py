import os
import time
import requests
import telebot
from io import BytesIO
from fpdf import FPDF
from keep_alive import keep_alive
from openai import OpenAI

# API ключи
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not all([TELEGRAM_TOKEN, ASSEMBLYAI_API_KEY, OPENAI_API_KEY]):
    raise ValueError("Один или несколько API ключей не заданы")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
keep_alive()

def analyze_call(text):
    prompt = f"""
Ты — эксперт по продажам. Проанализируй следующий диалог:

{text}

1. Укажи сильные стороны менеджера.
2. Укажи слабые стороны.
3. Дай рекомендации.
4. Оцени по 10-балльной шкале.

Отвечай кратко, по-деловому, на русском.
"""
    response = openai_client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    return response.choices[0].message.content.strip()

def generate_pdf(dialog_text, analysis_text):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)

    pdf.multi_cell(0, 10, "Отчет по звонку", align="C")
    pdf.ln(5)

    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 8, "Диалог:\n", align="L")
    pdf.set_font("Helvetica", size=10)
    pdf.multi_cell(0, 7, dialog_text)
    pdf.ln(5)

    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 8, "Анализ разговора:\n", align="L")
    pdf.set_font("Helvetica", size=10)
    pdf.multi_cell(0, 7, analysis_text)

    output = BytesIO()
    pdf.output(output)
    output.seek(0)
    return output

@bot.message_handler(content_types=['audio', 'voice'])
def handle_audio(message):
    try:
        file_id = message.audio.file_id if message.audio else message.voice.file_id
        file_info = bot.get_file(file_id)
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"

        bot.reply_to(message, "Загружаю и обрабатываю файл...")

        audio_data = requests.get(file_url).content

        upload_resp = requests.post(
            "https://api.assemblyai.com/v2/upload",
            headers={"authorization": ASSEMBLYAI_API_KEY},
            data=audio_data
        ).json()

        audio_url = upload_resp.get("upload_url")
        if not audio_url:
            bot.reply_to(message, "Ошибка загрузки в AssemblyAI.")
            return

        transcript_req = requests.post(
            "https://api.assemblyai.com/v2/transcript",
            headers={"authorization": ASSEMBLYAI_API_KEY},
            json={
                "audio_url": audio_url,
                "language_code": "ru",
                "speaker_labels": True
            }
        ).json()

        transcript_id = transcript_req.get("id")
        if not transcript_id:
            bot.reply_to(message, "Ошибка инициализации транскрипции.")
            return

        polling_url = f"https://api.assemblyai.com/v2/transcript/{transcript_id}"

        for _ in range(60):
            time.sleep(5)
            poll = requests.get(polling_url, headers={"authorization": ASSEMBLYAI_API_KEY}).json()
            if poll["status"] == "completed":
                utterances = poll.get("utterances", [])
                first = utterances[0]["speaker"]
                second = next((u["speaker"] for u in utterances if u["speaker"] != first), None)
                speaker_map = {
                    first: "Менеджер",
                    second: "Клиент"
                }
                dialogue = ""
                for utt in utterances:
                    who = speaker_map.get(utt["speaker"], f"Спикер {utt['speaker']}")
                    dialogue += f"{who}: {utt['text']}\n"

                analysis = analyze_call(dialogue)
                pdf_file = generate_pdf(dialogue, analysis)
                bot.send_document(message.chat.id, pdf_file, visible_file_name="otchet_po_zvonku.pdf")
                return

            elif poll["status"] == "error":
                bot.reply_to(message, f"Ошибка транскрипции: {poll['error']}")
                return

        bot.reply_to(message, "Превышено время ожидания.")
    except Exception as e:
        bot.reply_to(message, f"Внутренняя ошибка:\n{e}")

bot.polling(none_stop=True)
