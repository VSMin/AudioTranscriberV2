import os
import time
import telebot
import requests
import openai
from keep_alive import keep_alive

# Получаем токены из переменных окружения
bot_token = os.getenv("TELEGRAM_TOKEN")
assembly_key = os.getenv("ASSEMBLYAI_API_KEY")
openai.api_key = os.getenv("OPENAI_API_KEY")

# Проверка, что ключи заданы
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

        polling_url = f"https://api.assemblyai.com/v2/transcript/{transcript_id}"
        start_time = time.time()

        while True:
            poll = requests.get(polling_url, headers={"authorization": assembly_key}).json()
            if poll["status"] == "completed":
                utterances = poll.get("utterances", [])
                first_speaker = utterances[0]["speaker"] if utterances else 0
                second_speaker = next((u["speaker"] for u in utterances if u["speaker"] != first_speaker), first_speaker + 1)

                speaker_map = {
                    first_speaker: "👨 Менеджер",
                    second_speaker: "👤 Клиент"
                }

                result = ""
                for utt in utterances:
                    who = speaker_map.get(utt["speaker"], f"🗣 Спикер {utt['speaker']}")
                    result += f"{who}: {utt['text']}\n"

                # Генерация анализа GPT
                bot.reply_to(message, "📊 Анализирую разговор...")

                prompt = f"""
Ты — ассистент по обучению продажам. Проанализируй следующий диалог и:
1. Выдели сильные стороны менеджера.
2. Найди слабые стороны или ошибки.
3. Дай рекомендации, как улучшить разговор.

Диалог:
{result}
"""

                completion = openai.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": "Ты опытный тренер по продажам, специализирующийся на оценке телефонных звонков."},
                        {"role": "user", "content": prompt}
                    ]
                )

                analysis = completion.choices[0].message.content

                bot.reply_to(message, f"📝 Текст разговора:\n\n{result}\n\n💡 Анализ:\n{analysis}")
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
