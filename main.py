import os
import time
import telebot
import requests
import openai
from fpdf import FPDF
from keep_alive import keep_alive

# Токены
bot_token = os.getenv("TELEGRAM_TOKEN")
assembly_key = os.getenv("ASSEMBLYAI_API_KEY")
openai.api_key = os.getenv("OPENAI_API_KEY")

if not bot_token or not assembly_key or not openai.api_key:
    raise ValueError("Один или несколько API ключей не заданы")

bot = telebot.TeleBot(bot_token)
keep_alive()

@bot.message_handler(content_types=['audio', 'voice'])
def handle_audio(message):
    try:
        file_id = message.audio.file_id if message.audio else message.voice.file_id
        file_info = bot.get_file(file_id)
        file_path = file_info.file_path
        file_url = f'https://api.telegram.org/file/bot{bot_token}/{file_path}'

        bot.reply_to(message, "⏳ Загружаю файл...")

        # Скачиваем аудио
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
            bot.reply_to(message, f"❌ Ошибка транскрипции: {transcript_req.text}")
            return

        bot.reply_to(message, "🔁 Обрабатываю...")

        polling_url = f"https://api.assemblyai.com/v2/transcript/{transcript_id}"
        start_time = time.time()
        utterances = []

        while True:
            poll = requests.get(polling_url, headers={"authorization": assembly_key}).json()
            if poll["status"] == "completed":
                utterances = poll.get("utterances", [])
                break
            elif poll["status"] == "error":
                bot.reply_to(message, f"❌ Ошибка AssemblyAI: {poll['error']}")
                return
            elif time.time() - start_time > 90:
                bot.reply_to(message, "⏰ Время ожидания истекло.")
                return
            time.sleep(5)

        if not utterances:
            bot.reply_to(message, "⚠️ Не удалось разделить голоса.")
            return

        # Определение ролей
        first_speaker = utterances[0]["speaker"]
        second_speaker = next((u["speaker"] for u in utterances if u["speaker"] != first_speaker), None)
        speaker_map = {
            first_speaker: "👨 Менеджер",
            second_speaker: "👤 Клиент"
        }

        dialogue = ""
        for utt in utterances:
            who = speaker_map.get(utt["speaker"], f"🗣 Спикер {utt['speaker']}")
            dialogue += f"{who}: {utt['text']}\n"

        # Анализ через OpenAI
        analysis_prompt = f"""Ты — эксперт по продажам. Проанализируй разговор ниже. 
Определи сильные и слабые стороны менеджера, ошибки, и дай рекомендации по улучшению:

{dialogue}"""

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Ты — эксперт по продажам, помогаешь улучшить работу менеджеров."},
                {"role": "user", "content": analysis_prompt}
            ]
        )
        analysis = response["choices"][0]["message"]["content"]

        # Генерация PDF отчета
        pdf = FPDF()
        pdf.add_page()
        pdf.add_font('DejaVu', '', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', uni=True)
        pdf.set_font("DejaVu", size=12)

        pdf.multi_cell(0, 10, "📋 Транскрипция:\n" + dialogue)
        pdf.ln(5)
        pdf.set_font("DejaVu", style='B', size=12)
        pdf.cell(0, 10, "📈 Анализ разговора:", ln=True)
        pdf.set_font("DejaVu", size=12)
        pdf.multi_cell(0, 10, analysis)

        file_path = f"/tmp/report_{file_id}.pdf"
        pdf.output(file_path)

        # Отправляем PDF
        with open(file_path, "rb") as f:
            bot.send_document(message.chat.id, f)

    except Exception as e:
        bot.reply_to(message, f"🚨 Внутренняя ошибка:\n{e}")

bot.polling(none_stop=True)
