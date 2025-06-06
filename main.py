import os
import time
import telebot
import requests
import openai
from fpdf import FPDF
from keep_alive import keep_alive

bot_token = os.getenv("TELEGRAM_TOKEN")
assembly_key = os.getenv("ASSEMBLYAI_API_KEY")
openai.api_key = os.getenv("OPENAI_API_KEY")

if not bot_token or not assembly_key or not openai.api_key:
    raise ValueError("Один или несколько API ключей не заданы")

bot = telebot.TeleBot(bot_token)
keep_alive()

def определить_роли(utterances):
    менеджер_фразы = [
        "я звоню", "компания", "предлагаем", "интернет", "видеонаблюдение", "руководство",
        "установка", "оборудование", "провайдер", "договор"
    ]
    частота = {}
    for u in utterances:
        speaker = u["speaker"]
        if speaker not in частота:
            частота[speaker] = 0
        if any(ключ in u["text"].lower() for ключ in менеджер_фразы):
            частота[speaker] += 1
    if not частота:
        return {0: "👨 Менеджер", 1: "👤 Клиент"}
    менеджер = max(частота, key=частота.get)
    клиент = 1 - менеджер
    return {менеджер: "👨 Менеджер", клиент: "👤 Клиент"}

def создать_pdf_отчет(текст, аналитика):
    pdf = FPDF()
    pdf.add_page()
    pdf.add_font('DejaVu', '', 'DejaVuSans.ttf', uni=True)
    pdf.set_font('DejaVu', '', 12)
    pdf.multi_cell(0, 10, текст)
    pdf.ln(10)
    pdf.set_font('DejaVu', '', 11)
    pdf.multi_cell(0, 10, "\n--- Анализ разговора ---\n" + аналитика)
    путь = "/app/report.pdf"
    pdf.output(путь)
    return путь

@bot.message_handler(content_types=['audio', 'voice'])
def handle_audio(message):
    try:
        file_id = message.audio.file_id if message.audio else message.voice.file_id
        file_info = bot.get_file(file_id)
        file_path = file_info.file_path
        file_url = f'https://api.telegram.org/file/bot{bot_token}/{file_path}'

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

        bot.reply_to(message, "🔁 Обрабатываю...")
        polling_url = f"https://api.assemblyai.com/v2/transcript/{transcript_id}"
        start_time = time.time()

        while True:
            poll = requests.get(polling_url, headers={"authorization": assembly_key}).json()
            if poll["status"] == "completed":
                if "utterances" in poll:
                    utterances = poll["utterances"]
                    speaker_map = определить_роли(utterances)
                    result = ""
                    for utt in utterances:
                        who = speaker_map.get(utt["speaker"], f"🗣 Спикер {utt['speaker']}")
                        result += f"{who}: {utt['text']}\n"
                else:
                    result = poll["text"] or "⚠️ Нет распознанного текста."

                # Анализируем текст
                gpt_response = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "Ты опытный тренер по продажам. Проанализируй диалог менеджера с клиентом и укажи сильные стороны, слабые стороны и рекомендации по улучшению."},
                        {"role": "user", "content": result}
                    ]
                )
                анализ = gpt_response.choices[0].message.content.strip()

                # Отправляем текст и анализ
                bot.reply_to(message, f"📝 Готово:\n\n{result}\n\n📊 Анализ:\n{анализ}")

                # PDF
                try:
                    путь = создать_pdf_отчет(result, анализ)
                    with open(путь, "rb") as f:
                        bot.send_document(message.chat.id, f, caption="📎 PDF-отчет")
                except Exception as e:
                    bot.reply_to(message, f"⚠️ Не удалось создать PDF: {e}")
                break

            elif poll["status"] == "error":
                bot.reply_to(message, f"❌ Ошибка AssemblyAI: {poll['error']}")
                break

            elif time.time() - start_time > 60:
                bot.reply_to(message, "⏰ Timeout: файл обрабатывается слишком долго.")
                break

            time.sleep(5)

    except Exception as e:
        bot.reply_to(message, f"🚨 Внутренняя ошибка:\n\n{e}")

bot.polling(none_stop=True)
