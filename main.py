import os
import time
import telebot
import requests
from fpdf import FPDF
from datetime import datetime
from keep_alive import keep_alive
import openai
import tempfile

# Инициализация токенов
bot_token = os.getenv("TELEGRAM_TOKEN")
assembly_key = os.getenv("ASSEMBLYAI_API_KEY")
openai.api_key = os.getenv("OPENAI_API_KEY")
MANAGER_CHAT_ID = int(os.getenv("MANAGER_CHAT_ID", "0"))

if not bot_token or not assembly_key or not openai.api_key:
    raise ValueError("Один или несколько API ключей не заданы")

bot = telebot.TeleBot(bot_token)
keep_alive()

def generate_pdf_report(dialog_text, analysis_text):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    pdf.cell(200, 10, txt=f"Отчет о звонке – {now}", ln=True, align='C')
    pdf.ln(10)

    pdf.set_font("Arial", style='B', size=12)
    pdf.cell(200, 10, txt="Диалог:", ln=True)
    pdf.set_font("Arial", size=11)
    for line in dialog_text.split("\n"):
        pdf.multi_cell(0, 8, line)

    pdf.ln(5)
    pdf.set_font("Arial", style='B', size=12)
    pdf.cell(200, 10, txt="Анализ:", ln=True)
    pdf.set_font("Arial", size=11)
    for line in analysis_text.split("\n"):
        pdf.multi_cell(0, 8, line)

    temp_path = tempfile.mktemp(suffix=".pdf")
    pdf.output(temp_path)
    return temp_path

@bot.message_handler(content_types=['audio', 'voice'])
def handle_audio(message):
    try:
        file_id = message.audio.file_id if message.audio else message.voice.file_id
        file_info = bot.get_file(file_id)
        file_path = file_info.file_path
        file_url = f'https://api.telegram.org/file/bot{bot_token}/{file_path}'

        bot.reply_to(message, "⏳ Загружаю файл...")
        audio_data = requests.get(file_url).content

        # Upload to AssemblyAI
        upload_resp = requests.post("https://api.assemblyai.com/v2/upload",
            headers={"authorization": assembly_key}, data=audio_data)
        if upload_resp.status_code != 200:
            bot.reply_to(message, f"❌ Ошибка загрузки: {upload_resp.text}")
            return

        audio_url = upload_resp.json()["upload_url"]

        transcript_req = requests.post("https://api.assemblyai.com/v2/transcript",
            headers={"authorization": assembly_key},
            json={"audio_url": audio_url, "language_code": "ru", "speaker_labels": True})

        transcript_id = transcript_req.json().get("id")
        if not transcript_id:
            bot.reply_to(message, f"❌ Ошибка создания транскрипта: {transcript_req.text}")
            return

        bot.reply_to(message, "🔁 Обрабатываю...")

        polling_url = f"https://api.assemblyai.com/v2/transcript/{transcript_id}"
        start_time = time.time()

        while True:
            poll = requests.get(polling_url, headers={"authorization": assembly_key}).json()
            if poll["status"] == "completed":
                utterances = poll.get("utterances", [])
                first_speaker = utterances[0]["speaker"] if utterances else 0
                second_speaker = next((u["speaker"] for u in utterances if u["speaker"] != first_speaker), None)
                speaker_map = {
                    first_speaker: "👨 Менеджер",
                    second_speaker: "👤 Клиент"
                }

                dialog_text = ""
                for utt in utterances:
                    who = speaker_map.get(utt["speaker"], f"🗣 Спикер {utt['speaker']}")
                    dialog_text += f"{who}: {utt['text']}\n"

                # Анализ GPT
                prompt = f"""
Проанализируй следующий диалог между менеджером и клиентом.
Укажи:
- Сильные стороны менеджера
- Слабые стороны
- Оценка разговора по 10-балльной шкале
- Рекомендации по улучшению

Диалог:
{dialog_text}
"""
                gpt_resp = openai.ChatCompletion.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": "Ты помощник, оценивающий звонки менеджеров."},
                        {"role": "user", "content": prompt}
                    ]
                )
                feedback = gpt_resp.choices[0].message.content

                # Отправка текста и PDF
                bot.reply_to(message, f"📝 Готово:\n\n{dialog_text[:3500]}")
                bot.reply_to(message, f"🧠 Анализ:\n\n{feedback[:3500]}")

                pdf_path = generate_pdf_report(dialog_text, feedback)
                bot.send_document(MANAGER_CHAT_ID, open(pdf_path, 'rb'), caption="📄 Новый отчет о звонке")
                break

            elif poll["status"] == "error":
                bot.reply_to(message, f"❌ Ошибка AssemblyAI: {poll['error']}")
                break

            elif time.time() - start_time > 60:
                bot.reply_to(message, "⏰ Timeout: файл обрабатывается слишком долго.")
                break

            time.sleep(5)

    except Exception as e:
        bot.reply_to(message, f"🚨 Внутренняя ошибка:\n{e}")

bot.polling(none_stop=True)
