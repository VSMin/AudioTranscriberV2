import os
import assemblyai as aai
import telebot
from telebot.types import Message
from keep_alive import keep_alive

bot_token = os.environ.get('BOT_TOKEN')

# Initialize the Telegram bot with your bot token
bot = telebot.TeleBot(bot_token)

# Dictionary to store user API keys
user_api_keys = {}


def get_api_key(chat_id):
  if chat_id not in user_api_keys:
    bot.send_message(chat_id, "Please enter your AssemblyAI API key:")
    return None
  return user_api_keys[chat_id]


def transcribe_and_show_text(api_key, audio_file_path):
  try:
    aai.settings.api_key = api_key
    transcriber = aai.Transcriber()
    transcript = transcriber.transcribe(audio_file_path)
    text = transcript.text
    return text
  except aai.exceptions.AuthError:
    print("Authentication failed. Please check your AssemblyAI API key.")
  except aai.exceptions.FileError:
    print("File error. Please check the audio file path.")
  except aai.exceptions.RequestError as e:
    print("Transcription request failed. Error:", e)
  except aai.exceptions.TranscriberError as e:
    print("Transcriber error. Error:", e)
  except Exception as e:
    print("An unexpected error occurred:", e)
  return None


# Start command handler
@bot.message_handler(commands=['start'])
def send_welcome(message: Message):
  welcome_message = (
    "👋 Hello! I'm AudioTranscriber Bot.\n\n"
    "Send me an audio file or a voice message in OGG or WAV format, "
    "and I'll transcribe it into text for you.\n\n"
    "Note: This bot is based on AssemblyAI API, and you need to have an API key for transcription.\n\n"
    "For getting an API key, visit AssemblyAI website: https://www.assemblyai.com/"
  )

  bot.send_message(message.chat.id, welcome_message)


# Transcribe command handler
@bot.message_handler(commands=['transcribe'])
def handle_audio(message: Message):
  chat_id = message.chat.id
  api_key = get_api_key(chat_id)

  if not api_key:
    return

  bot.reply_to(
    message,
    "Please send me the audio file or the voice message you want to transcribe."
  )


# Handle incoming audio files and voice messages from users
@bot.message_handler(content_types=['audio', 'voice'])
def handle_received_audio(message: Message):
  chat_id = message.chat.id
  api_key = get_api_key(chat_id)

  if not api_key:
    return

  try:
    # Inform the user that the file is being processed
    bot.reply_to(message, "Your file is being processed. Please wait...")

    # Get the file ID and download the audio/voice file
    file_id = None
    if message.content_type == 'audio':
      file_id = message.audio.file_id
    elif message.content_type == 'voice':
      file_id = message.voice.file_id

    file_info = bot.get_file(file_id)
    audio_file = bot.download_file(file_info.file_path)

    # Save the audio file to a temporary location
    audio_file_path = "temp_audio.ogg"  # Adjust the file extension if needed
    with open(audio_file_path, 'wb') as f:
      f.write(audio_file)

    # Transcribe the audio and get the text
    transcribed_text = transcribe_and_show_text(api_key, audio_file_path)

    # Respond to the user with the transcribed text
    if transcribed_text:
      bot.reply_to(message, "Transcription Result:\n" + transcribed_text)
    else:
      bot.reply_to(message, "Transcription failed. Please try again later.")

    # Clean up: Delete the temporary audio file
    os.remove(audio_file_path)

  except Exception as e:
    bot.reply_to(
      message,
      "An error occurred during transcription. Please try again later.")
    print("Transcription failed. Error:", e)


# Non-command text handler to capture API keys
@bot.message_handler(func=lambda message: True)
def get_user_api_key(message: Message):
  chat_id = message.chat.id
  if chat_id not in user_api_keys:
    user_api_keys[chat_id] = message.text.strip()
    bot.reply_to(
      message,
      "Thank you! Your API key has been recorded. You can now use the /transcribe command to transcribe audio or voice messages."
    )
  else:
    bot.reply_to(
      message,
      "Sorry, I'm already processing your API key. Please use the /transcribe command to transcribe audio or voice messages."
    )


# Run the flask server
keep_alive()

# Run the bot
bot.polling()
