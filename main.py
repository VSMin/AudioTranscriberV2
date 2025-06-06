import os
import time
import telebot
import requests
from fpdf import FPDF
import openai
from keep_alive import keep_alive

# Получаем переменные окружения
bot_token = os.getenv("TELEGRAM_TOKEN")
assembly_key = os.getenv("ASSEMBLYAI_API_KEY")
openai.api_key = os.getenv("OPENAI_API_KEY")

if not bot_token or not assembly_key or not openai.api_key:
    raise ValueError("Один или несколько API ключей не заданы")

bot = telebot.TeleBot(bot_token)
keep_alive()  # Запускает Flask-сервер на Railway, чтобы бот не засыпал

# Обработчик входящих аудиосообщений
@bot.message_handler(content_types=['audio', 'voice'])
def handle_audio(message):
    try:
        file_id = message.audio.file_id if message.audio else message.voice.file_id
        file_info = bot.get_file(file_id)
        file_url = f'https://api.telegram.org/file/bot{bot_token}/{file_info.file_path}'
        bot.reply_to(message, "⏳ Загружаю файл...")

        audio_data = requests.get(file_url).content

        # Загрузка в AssemblyAI
        upload_resp = requests.post(
            "https://api.assemblyai.com/v2/upload",
            headers={"authorization": assembly_key},
            data=audio_data
        )
        if upload_resp.status_code != 200:
            bot.reply_to(message, f"❌ Ошибка загрузки: {upload_resp.text}")
            return

        audio_url = upload_resp.json()["upload_url"]

        # Запрос транскрипции
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

        # Ожидание результата
        polling_url = f"https://api.assemblyai.com/v2/transcript/{transcript_id}"
        start_time = time.time()
        while True:
            poll = requests.get(polling_url, headers={"authorization": assembly_key}).json()
            if poll["status"] == "completed":
                utterances = poll.get("utterances", [])
                if not utterances:
                    result_text = poll.get("text", "⚠️ Нет распознанного текста.")
                else:
                    # Распределение по ролям
                    speaker0 = utterances[0]["speaker"]
                    speaker1 = next((u["speaker"] for u in utterances if u["speaker"] != speaker0), speaker0)
                    speaker_map = {
                        speaker0: "👨 Менеджер",
                        speaker1: "👤 Клиент"
                    }
                    result_text = ""
                    for utt in utterances:
                        who = speaker_map.get(utt["speaker"], f"🗣 Спикер {utt['speaker']}")
                        result_text += f"{who}: {utt['text']}\n"
                break
            elif poll["status"] == "error":
                bot.reply_to(message, f"❌ Ошибка AssemblyAI: {poll['error']}")
                return
            elif time.time() - start_time > 120:
                bot.reply_to(message, "⏰ Timeout: обработка слишком долгая.")
                return
            time.sleep(5)

        # Отправка текста в OpenAI на анализ
        bot.reply_to(message, "🧠 Анализирую диалог...")

        prompt = f"""Проанализируй разговор менеджера и клиента. Укажи:
1. Сильные стороны менеджера
2. Слабые стороны или ошибки
3. Общую оценку беседы
4. Рекомендации по улучшению

Диалог:
{result_text}
"""
        completion = openai.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        analysis_text = completion.choices[0].message.content.strip()

        # Создание PDF-отчета
        class PDF(FPDF):
            def header(self):
                self.set_font("Arial", "B", 14)
                self.cell(0, 10, "Отчёт по разговору", ln=True, align="C")
                self.ln(5)

            def footer(self):
                self.set_y(-15)
                self.set_font("Arial", "I", 8)
                self.cell(0, 10, f"Страница {self.page_no()}", align="C")

        pdf = PDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        pdf.multi_cell(0, 10, "📋 Диалог:\n\n" + result_text)
        pdf.ln(5)
        pdf.set_font("Arial", style="B", size=12)
        pdf.cell(0, 10, "📊 Анализ:", ln=True)
        pdf.set_font("Arial", size=12)
        pdf.multi_cell(0, 10, analysis_text)

        pdf_path = f"/tmp/report_{file_id}.pdf"
        pdf.output(pdf_path)

        with open(pdf_path, "rb") as pdf_file:
            bot.send_document(message.chat.id, pdf_file, caption="📎 Отчёт по разговору")

    except Exception as e:
        bot.reply_to(message, f"🚨 Внутренняя ошибка:\n{e}")

bot.polling(none_stop=True)
