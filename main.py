import time
import requests
import telebot
from io import BytesIO
from fpdf import FPDF
from io import BytesIO
from keep_alive import keep_alive
from openai import OpenAI
import openai

# API ключи
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# Получение токенов из переменных окружения
bot_token = os.getenv("TELEGRAM_TOKEN")
assembly_key = os.getenv("ASSEMBLYAI_API_KEY")
openai_key = os.getenv("OPENAI_API_KEY")

if not all([TELEGRAM_TOKEN, ASSEMBLYAI_API_KEY, OPENAI_API_KEY]):
# Проверка токенов
if not bot_token or not assembly_key or not openai_key:
    raise ValueError("Один или несколько API ключей не заданы")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
keep_alive()

def analyze_call(text):
    prompt = f"""
Ты — эксперт по продажам. Проанализируй следующий диалог:

{text}
# Настройка OpenAI
openai.api_key = openai_key

1. Укажи сильные стороны менеджера.
2. Укажи слабые стороны.
3. Дай рекомендации.
4. Оцени по 10-балльной шкале.
# Инициализация бота
bot = telebot.TeleBot(bot_token)
keep_alive()

Отвечай кратко, по-деловому, на русском.
"""
    response = openai_client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    return response.choices[0].message.content.strip()

def generate_pdf(dialog_text, analysis_text):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)

    pdf.multi_cell(0, 10, "Отчет по звонку", align="C")
    # Используем встроенный шрифт, поддерживающий кириллицу, и избегаем emoji
    pdf.set_font("Arial", size=12)

    pdf.set_font("Arial", style='B', size=14)
    pdf.cell(0, 10, "Отчет по звонку", ln=True, align="C")
    pdf.ln(5)

    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 8, "Диалог:\n", align="L")
    pdf.set_font("Helvetica", size=10)
    pdf.multi_cell(0, 7, dialog_text)
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, "Диалог:", ln=True)
    pdf.set_font("Arial", size=11)
    pdf.multi_cell(0, 8, dialog_text)
    pdf.ln(5)

    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 8, "Анализ разговора:\n", align="L")
    pdf.set_font("Helvetica", size=10)
    pdf.multi_cell(0, 7, analysis_text)
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, "Анализ:", ln=True)
    pdf.set_font("Arial", size=11)
    pdf.multi_cell(0, 8, analysis_text)

    output = BytesIO()
    pdf.output(output)
    output.seek(0)
    return output


def analyze_dialog(dialog_text):
    prompt = (
        "Ты эксперт по продажам. Проанализируй диалог менеджера и клиента.\n"
        "1. Выдели сильные стороны менеджера\n"
        "2. Отметь слабые места и недочёты\n"
        "3. Дай рекомендации по улучшению разговора\n\n"
        f"Диалог:\n{dialog_text}"
    )

    try:
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Ты помощник по оценке продаж."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"⚠️ Ошибка анализа: {e}"


@bot.message_handler(content_types=['audio', 'voice'])
def handle_audio(message):
    try:
        file_id = message.audio.file_id if message.audio else message.voice.file_id
        file_info = bot.get_file(file_id)
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"
        file_path = file_info.file_path
        file_url = f'https://api.telegram.org/file/bot{bot_token}/{file_path}'

        bot.reply_to(message, "Загружаю и обрабатываю файл...")
        bot.reply_to(message, "⏳ Загружаю файл...")

        # Скачиваем файл
        audio_data = requests.get(file_url).content

        # Загрузка в AssemblyAI
        upload_resp = requests.post(
            "https://api.assemblyai.com/v2/upload",
            headers={"authorization": ASSEMBLYAI_API_KEY},
            headers={"authorization": assembly_key},
            data=audio_data
        ).json()
        )

        audio_url = upload_resp.get("upload_url")
        if not audio_url:
            bot.reply_to(message, "Ошибка загрузки в AssemblyAI.")
        if upload_resp.status_code != 200:
            bot.reply_to(message, f"❌ Ошибка загрузки: {upload_resp.text}")
            return

        audio_url = upload_resp.json()["upload_url"]

        # Запрос транскрипции
        transcript_req = requests.post(
            "https://api.assemblyai.com/v2/transcript",
            headers={"authorization": ASSEMBLYAI_API_KEY},
            headers={"authorization": assembly_key},
            json={
                "audio_url": audio_url,
                "language_code": "ru",
                "speaker_labels": True
            }
        ).json()
        )

        transcript_id = transcript_req.get("id")
        transcript_id = transcript_req.json().get("id")
        if not transcript_id:
            bot.reply_to(message, "Ошибка инициализации транскрипции.")
            bot.reply_to(message, f"❌ Ошибка создания транскрипта: {transcript_req.text}")
            return

        bot.reply_to(message, "🔁 Распознаю речь...")

        # Ожидание завершения транскрипции
        polling_url = f"https://api.assemblyai.com/v2/transcript/{transcript_id}"
        start_time = time.time()

        while True:
            poll = requests.get(polling_url, headers={"authorization": assembly_key}).json()

        for _ in range(60):
            time.sleep(5)
            poll = requests.get(polling_url, headers={"authorization": ASSEMBLYAI_API_KEY}).json()
            if poll["status"] == "completed":
                utterances = poll.get("utterances", [])
                first = utterances[0]["speaker"]
                second = next((u["speaker"] for u in utterances if u["speaker"] != first), None)
                speaker_map = {
                    first: "Менеджер",
                    second: "Клиент"
                }
                dialogue = ""
                for utt in utterances:
                    who = speaker_map.get(utt["speaker"], f"Спикер {utt['speaker']}")
                    dialogue += f"{who}: {utt['text']}\n"

                analysis = analyze_call(dialogue)
                pdf_file = generate_pdf(dialogue, analysis)
                bot.send_document(message.chat.id, pdf_file, visible_file_name="otchet_po_zvonku.pdf")
                return
                if utterances:
                    speaker_a = utterances[0]["speaker"]
                    speaker_b = next((u["speaker"] for u in utterances if u["speaker"] != speaker_a), None)
                    speaker_map = {
                        speaker_a: "Менеджер",
                        speaker_b: "Клиент"
                    }
                    dialog_text = ""
                    for utt in utterances:
                        speaker_label = speaker_map.get(utt["speaker"], f"Спикер {utt['speaker']}")
                        dialog_text += f"{speaker_label}: {utt['text']}\n"
                else:
                    dialog_text = poll.get("text", "⚠️ Нет распознанного текста.")

                # Генерация анализа
                bot.reply_to(message, "📊 Анализирую разговор...")
                analysis = analyze_dialog(dialog_text)

                # Генерация PDF
                bot.reply_to(message, "📄 Формирую отчет...")
                pdf_file = generate_pdf(dialog_text, analysis)
                bot.send_document(message.chat.id, ("report.pdf", pdf_file))

                break

            elif poll["status"] == "error":
                bot.reply_to(message, f"Ошибка транскрипции: {poll['error']}")
                return
                bot.reply_to(message, f"❌ Ошибка AssemblyAI: {poll.get('error')}")
                break

            elif time.time() - start_time > 60:
                bot.reply_to(message, "⏰ Тайм-аут: файл обрабатывается слишком долго.")
                break

            time.sleep(5)

        bot.reply_to(message, "Превышено время ожидания.")
    except Exception as e:Add commentMore actions
        bot.reply_to(message, f"Внутренняя ошибка:\n{e}")
        bot.reply_to(message, f"🚨 Внутренняя ошибка:\n{e}")


bot.polling(none_stop=True)
