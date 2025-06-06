import os
import time
import telebot
import requests
import openai
from keep_alive import keep_alive

# Ключи
bot_token = os.getenv("TELEGRAM_TOKEN")
assembly_key = os.getenv("ASSEMBLYAI_API_KEY")
openai.api_key = os.getenv("OPENAI_API_KEY")

# Проверка ключей
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

        # Загружаем в AssemblyAI
        upload_resp = requests.post(
            "https://api.assemblyai.com/v2/upload",
            headers={"authorization": assembly_key},
            data=audio_data
        )
        if upload_resp.status_code != 200:
            bot.reply_to(message, f"❌ Ошибка загрузки: {upload_resp.text}")
            return

        audio_url = upload_resp.json()["upload_url"]

        # Запрашиваем транскрипцию
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

        # Polling
        polling_url = f"https://api.assemblyai.com/v2/transcript/{transcript_id}"
        start_time = time.time()

        while True:
            poll = requests.get(polling_url, headers={"authorization": assembly_key}).json()
            if poll["status"] == "completed":
                utterances = poll.get("utterances", [])
                if not utterances:
                    text = poll.get("text", "")
                    if not text:
                        bot.reply_to(message, "⚠️ Нет распознанного текста.")
                        return
                    result_text = text
                else:
                    first_speaker = utterances[0]["speaker"]
                    second_speaker = next((u["speaker"] for u in utterances if u["speaker"] != first_speaker), first_speaker + 1)
                    speaker_map = {
                        first_speaker: "👨 Менеджер",
                        second_speaker: "👤 Клиент"
                    }
                    result_text = ""
                    for u in utterances:
                        who = speaker_map.get(u["speaker"], f"🗣 Спикер {str(u['speaker'])}")
                        result_text += f"{who}: {u['text']}\n"

                bot.reply_to(message, f"📄 Транскрипция завершена:\n\n{result_text[:3000]}")  # обрезаем для Telegram

                bot.reply_to(message, "📊 Анализирую разговор...")

                # Анализ текста
                prompt = (
                    "Проанализируй следующий диалог между менеджером и клиентом. "
                    "Выдели сильные и слабые стороны менеджера, оцени беседу по 10-балльной шкале и предложи, "
                    "что можно улучшить в его ответах.\n\n"
                    f"{result_text}"
                )

                chat_resp = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "Ты эксперт по продажам и анализу звонков."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7
                )

                analysis = chat_resp["choices"][0]["message"]["content"]
                bot.reply_to(message, f"📋 Отчет:\n\n{analysis[:3000]}")  # тоже ограничиваем
                break

            elif poll["status"] == "error":
                bot.reply_to(message, f"❌ Ошибка AssemblyAI: {poll['error']}")
                break

            elif time.time() - start_time > 90:
                bot.reply_to(message, "⏰ Timeout: обработка слишком долгая.")
                break

            time.sleep(5)

    except Exception as e:
        bot.reply_to(message, f"🚨 Внутренняя ошибка:\n{e}")

bot.polling(none_stop=True)
