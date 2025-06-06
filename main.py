import os
import time
import telebot
import requests
import io
from fpdf import FPDF
from keep_alive import keep_alive
import openai

# Переменные окружения
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
        file_url = f"https://api.telegram.org/file/bot{bot_token}/{file_info.file_path}"
        bot.reply_to(message, "⏳ Загружаю файл...")

        # Скачиваем аудио
        audio_data = requests.get(file_url).content

        # Загрузка в AssemblyAI
        upload_resp = requests.post(
            "https://api.assemblyai.com/v2/upload",
            headers={"authorization": assembly_key},
            data=audio_data
        )
        upload_json = upload_resp.json()
        if "upload_url" not in upload_json:
            bot.reply_to(message, f"❌ Ошибка загрузки: {upload_json}")
            return

        audio_url = upload_json["upload_url"]

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
            bot.reply_to(message, "❌ Ошибка создания транскрипта.")
            return

        bot.reply_to(message, "🔁 Обрабатываю...")

        # Ожидание завершения транскрипции
        polling_url = f"https://api.assemblyai.com/v2/transcript/{transcript_id}"
        start_time = time.time()
        while True:
            poll = requests.get(polling_url, headers={"authorization": assembly_key}).json()

            if poll["status"] == "completed":
                utterances = poll.get("utterances", [])
                if not utterances:
                    text = poll.get("text", "⚠️ Нет распознанного текста.")
                    send_report_pdf(message.chat.id, text, "Не удалось определить роли", "Анализ невозможен.")
                    return

                # Определяем роли участников
                speaker_roles = {}
                for utt in utterances:
                    if any(word in utt["text"].lower() for word in ["коннект", "интернет", "видеонаблюден"]):
                        speaker_roles[utt["speaker"]] = "👨 Менеджер"
                    elif utt["speaker"] not in speaker_roles:
                        speaker_roles[utt["speaker"]] = "👤 Клиент"

                # Сборка диалога
                dialogue = ""
                for utt in utterances:
                    who = speaker_roles.get(utt["speaker"], f"🗣 Спикер {utt['speaker']}")
                    dialogue += f"{who}: {utt['text']}\n"

                # Анализ с OpenAI
                gpt_response = openai.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {
                            "role": "system",
                            "content": "Ты анализируешь телефонный звонок менеджера по продажам. Выдели сильные и слабые стороны, и предложи краткие рекомендации, как улучшить разговор."
                        },
                        {
                            "role": "user",
                            "content": dialogue
                        }
                    ]
                )
                analysis = gpt_response.choices[0].message.content.strip()

                # Генерация и отправка PDF
                send_report_pdf(message.chat.id, dialogue, "Автоопределение ролей", analysis)
                break

            elif poll["status"] == "error":
                bot.reply_to(message, f"❌ Ошибка транскрипции: {poll.get('error')}")
                break

            elif time.time() - start_time > 60:
                bot.reply_to(message, "⏰ Превышено время ожидания.")
                break

            time.sleep(5)

    except Exception as e:
        bot.reply_to(message, f"🚨 Внутренняя ошибка:\n\n{e}")

# Генерация PDF отчета
def send_report_pdf(chat_id, dialogue, roles_info, analysis):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_font("Arial", "", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", uni=True)
    pdf.set_font("Arial", size=12)

    pdf.multi_cell(0, 10, f"📋 Транскрипция звонка:\n\n{dialogue}\n\n")
    pdf.multi_cell(0, 10, f"🔎 Роли: {roles_info}\n\n")
    pdf.multi_cell(0, 10, f"📊 Анализ разговора:\n{analysis}")

    pdf_output = io.BytesIO()
    pdf.output(pdf_output)
    pdf_output.seek(0)

    bot.send_document(chat_id, ("report.pdf", pdf_output))

bot.polling(none_stop=True)
