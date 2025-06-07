import os
import time
import telebot
import requests
import openai
from keep_alive import keep_alive

# Получение токенов из переменных окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Проверка на наличие всех ключей
if not TELEGRAM_TOKEN or not ASSEMBLYAI_API_KEY or not OPENAI_API_KEY:
    raise ValueError("Один или несколько API ключей не заданы")

# Инициализация OpenAI и Telegram
openai.api_key = OPENAI_API_KEY
bot = telebot.TeleBot(TELEGRAM_TOKEN)

keep_alive()  # Flask-сервер, чтобы Railway не засыпал

@bot.message_handler(content_types=['audio', 'voice'])
def handle_audio(message):
    try:
        file_id = message.audio.file_id if message.audio else message.voice.file_id
        file_info = bot.get_file(file_id)
        file_url = f'https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}'

        bot.reply_to(message, "⏳ Загружаю файл...")

        # Скачивание файла
        audio_data = requests.get(file_url).content

        # Загрузка в AssemblyAI
        upload_resp = requests.post(
            "https://api.assemblyai.com/v2/upload",
            headers={"authorization": ASSEMBLYAI_API_KEY},
            data=audio_data
        )
        upload_url = upload_resp.json().get("upload_url")
        if not upload_url:
            bot.reply_to(message, f"❌ Ошибка загрузки: {upload_resp.text}")
            return

        # Запрос транскрипции
        transcript_resp = requests.post(
            "https://api.assemblyai.com/v2/transcript",
            headers={"authorization": ASSEMBLYAI_API_KEY},
            json={
                "audio_url": upload_url,
                "language_code": "ru",
                "speaker_labels": True
            }
        )
        transcript_id = transcript_resp.json().get("id")
        if not transcript_id:
            bot.reply_to(message, f"❌ Ошибка создания транскрипта: {transcript_resp.text}")
            return

        bot.reply_to(message, "🔁 Распознаю речь...")

        # Ожидание результата
        polling_url = f"https://api.assemblyai.com/v2/transcript/{transcript_id}"
        start_time = time.time()
        while True:
            poll = requests.get(polling_url, headers={"authorization": ASSEMBLYAI_API_KEY}).json()
            if poll["status"] == "completed":
                utterances = poll.get("utterances", [])
                if not utterances:
                    bot.reply_to(message, "⚠️ Текст не распознан.")
                    return

                # Простейшее сопоставление спикеров — первый считается менеджером
                speaker_map = {}
                unique_speakers = list({u['speaker'] for u in utterances})
                if len(unique_speakers) >= 2:
                    speaker_map[unique_speakers[0]] = "👨 Менеджер"
                    speaker_map[unique_speakers[1]] = "👤 Клиент"
                else:
                    speaker_map[unique_speakers[0]] = "🗣 Спикер"

                # Сборка текста
                dialogue = ""
                for utt in utterances:
                    speaker = speaker_map.get(utt["speaker"], f"🗣 Спикер {utt['speaker']}")
                    dialogue += f"{speaker}: {utt['text']}\n"

                bot.reply_to(message, "📊 Анализирую разговор...")

                # Отправка текста в OpenAI для анализа
                prompt = f"""Вот стенограмма разговора:\n\n{dialogue}\n\n
Проанализируй, пожалуйста:
1. Какие сильные стороны были у менеджера?
2. Какие слабые стороны?
3. Как можно было улучшить разговор?
4. Итоговая оценка разговора по 5-балльной шкале.
Формат ответа: с пунктами и понятным текстом."""

                response = openai.ChatCompletion.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": "Ты эксперт по продажам и аудитор звонков."},
                        {"role": "user", "content": prompt}
                    ]
                )

                analysis = response.choices[0].message.content.strip()

                bot.reply_to(message, f"📄 Готово!\n\n🗣 Диалог:\n{dialogue}\n\n🔍 Анализ:\n{analysis}")
                break

            elif poll["status"] == "error":
                bot.reply_to(message, f"❌ Ошибка AssemblyAI: {poll['error']}")
                break

            elif time.time() - start_time > 120:
                bot.reply_to(message, "⏰ Timeout: файл обрабатывается слишком долго.")
                break

            time.sleep(5)

    except Exception as e:
        bot.reply_to(message, f"🚨 Внутренняя ошибка:\n{e}")

bot.polling(none_stop=True)
