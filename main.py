import os
import time
import requests
import telebot
from fpdf import FPDF
from keep_alive import keep_alive
from openai import OpenAI

# Получаем ключи из переменных окружения
bot_token = os.getenv("TELEGRAM_TOKEN")
assembly_key = os.getenv("ASSEMBLYAI_API_KEY")
openai_key = os.getenv("OPENAI_API_KEY")

if not bot_token or not assembly_key or not openai_key:
    raise ValueError("Один или несколько API ключей не заданы")

bot = telebot.TeleBot(bot_token)
keep_alive()

client = OpenAI(api_key=openai_key)

class PDF(FPDF):
    def header(self):
        self.set_font("Arial", size=12)
        self.cell(0, 10, "Отчет по звонку", ln=True, align="C")

    def add_section(self, title, content):
        self.set_font("Arial", style='B', size=12)
        self.multi_cell(0, 10, title)
        self.set_font("Arial", size=11)
        self.multi_cell(0, 8, content)
        self.ln()

@bot.message_handler(content_types=['audio', 'voice'])
def handle_audio(message):
    try:
        file_id = message.audio.file_id if message.audio else message.voice.file_id
        file_info = bot.get_file(file_id)
        file_path = file_info.file_path
        file_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"

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
                if not utterances:
                    bot.reply_to(message, "⚠️ Текст не распознан.")
                    return

                first_speaker = utterances[0]["speaker"]
                second_speaker = next((u["speaker"] for u in utterances if u["speaker"] != first_speaker), None)
                speaker_map = {
                    first_speaker: "👨 Менеджер",
                    second_speaker: "👤 Клиент"
                }

                dialog_text = ""
                for utt in utterances:
                    who = speaker_map.get(utt["speaker"], f"🗣 Спикер {utt['speaker']}")
                    dialog_text += f"{who}: {utt['text']}\n"

                bot.reply_to(message, "📊 Анализирую разговор...")

                prompt = (
                    "Ты — ассистент по продажам. Проанализируй следующий диалог между менеджером и клиентом:\n\n"
                    f"{dialog_text}\n\n"
                    "Выдели:\n"
                    "- Сильные стороны менеджера\n"
                    "- Слабые стороны менеджера\n"
                    "- Общую оценку разговора по 5-балльной шкале\n"
                    "- Конкретные рекомендации по улучшению разговора\n\n"
                    "Ответ на русском языке."
                )

                completion = client.chat.completions.create(
                    model="gpt-4",
                    messages=[{"role": "user", "content": prompt}]
                )

                analysis = completion.choices[0].message.content

                bot.reply_to(message, "📄 Формирую отчет...")

                pdf = PDF()
                pdf.add_page()
                pdf.add_section("📄 Расшифровка диалога", dialog_text)
                pdf.add_section("📊 Анализ разговора", analysis)

                pdf_path = "/mnt/data/отчет_по_звонку.pdf"
                pdf.output(pdf_path)

                with open(pdf_path, "rb") as f:
                    bot.send_document(message.chat.id, f, caption="✅ Готовый PDF-отчет")

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
