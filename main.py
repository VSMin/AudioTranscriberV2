import os
import time
import telebot
import requests
from fpdf import FPDF
from keep_alive import keep_alive
from openai import OpenAI

# Инициализация API ключей
bot_token = os.getenv("TELEGRAM_TOKEN")
assembly_key = os.getenv("ASSEMBLYAI_API_KEY")
openai_key = os.getenv("OPENAI_API_KEY")

if not bot_token or not assembly_key or not openai_key:
    raise ValueError("Один или несколько API ключей не заданы")

# Telegram бот
bot = telebot.TeleBot(bot_token)
client = OpenAI(api_key=openai_key)
keep_alive()

@bot.message_handler(content_types=['audio', 'voice'])
def handle_audio(message):
    try:
        file_id = message.audio.file_id if message.audio else message.voice.file_id
        file_info = bot.get_file(file_id)
        file_path = file_info.file_path
        file_url = f'https://api.telegram.org/file/bot{bot_token}/{file_path}'

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

        bot.reply_to(message, "🔁 Обрабатываю...")
        polling_url = f"https://api.assemblyai.com/v2/transcript/{transcript_id}"
        start_time = time.time()

        while True:
            poll = requests.get(polling_url, headers={"authorization": assembly_key}).json()
            if poll["status"] == "completed":
                if "utterances" in poll:
                    utterances = poll["utterances"]
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
                else:
                    dialogue = poll["text"] or "⚠️ Нет распознанного текста."

                # Генерация анализа GPT
                response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "Ты анализируешь телефонный звонок менеджера по продажам. Выдели сильные и слабые стороны, и предложи краткие рекомендации, как улучшить разговор."},
                        {"role": "user", "content": dialogue}
                    ]
                )
                analysis = response.choices[0].message.content.strip()

                # PDF генерация
                pdf = FPDF()
                pdf.add_page()
                pdf.set_font("Arial", size=12)
                pdf.multi_cell(0, 10, "Транскрипция звонка:\n\n" + dialogue)
                pdf.ln(5)
                pdf.set_font("Arial", style='B', size=12)
                pdf.cell(0, 10, "Анализ звонка:", ln=True)
                pdf.set_font("Arial", size=12)
                pdf.multi_cell(0, 10, analysis)

                pdf_output = f"report_{transcript_id}.pdf"
                pdf.output(pdf_output)

                with open(pdf_output, "rb") as f:
                    bot.send_document(message.chat.id, f, caption="📄 Отчёт готов")

                os.remove(pdf_output)
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
