import asyncio
import os
from openai import OpenAI
from deepgram import (
    DeepgramClient,
    PrerecordedOptions,
    FileSource,
)
from aiogram import Bot, Dispatcher, types
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.filters.command import Command
from aiogram import F
from aiogram.types import FSInputFile
from config import Config

session = AiohttpSession(
    api=TelegramAPIServer.from_base(Config.TELEGRAM_BASE_URL)
)
client = OpenAI(api_key=Config.OPENAI_API_KEY)
bot = Bot(token=Config.TELEGRAM_BOT_TOKEN, session=session)
dp = Dispatcher()

# Define a global constant for the message text
BOT_HI_MESSAGE = ("Бот для получения текста из аудио. Просто загрузите аудио файлом, или запишите голосом. "
                  "Пишите @wisemik обратную связь (что нравится, и чего не хватает или что не работает)")


@dp.message(Command("start"))
async def command_start(message: types.Message):
    await message.reply(BOT_HI_MESSAGE)


@dp.message(Command("id"))
async def command_id(message: types.Message):
    await message.reply(
        f"chat id: {message.chat.id}\n" f"user_id: {message.from_user.id}"
    )


@dp.message(Command("help"))
async def help_command(message: types.Message):
    await message.reply(BOT_HI_MESSAGE)


@dp.message(F.text)
async def get_text(message: types.Message):
    await message.reply(BOT_HI_MESSAGE)


def summarize_text(text: str) -> str:
    response = client.chat.completions.create(model="gpt-4o",
                                                  messages=[
                                                      {
                                                          "role": "system",
                                                          "content": f"""
You will be provided with a text.
This text is a transcript of an audio recording of a meeting,
or a transcript of an audio recording of someone's thoughts and reflections.

Your task is to create a summary of the text based on the following guidelines:

1. If the text is a transcript of an audio meeting (with at least two participants):
   - Identify the participants and the meeting date, if available
   - Summarize the main points discussed by each participant
   - Highlight any agreements reached and next steps decided

2. If the text is an audio recording of thoughts (with only one participant):
   - Identify the main points discussed
   - Outline the next action plan mentioned in the recording

Ensure the final summary is no longer than 4000 characters.
Provide the summary in Russian"""
                                                      },
                                                      {
                                                          "role": "user",
                                                          "content": f"Here is the dialogue text:\n\n{text}"
                                                      }
                                                  ])
    summary = response.choices[0].message.content.strip()
    return summary




def escape_markdown(text: str) -> str:
    escape_chars = r'_[]*()~`>#+-=|{}.!'
    return ''.join(f'\\{char}' if char in escape_chars else char for char in text)


async def send_long_message(message: types.Message, text: str):
    max_length = 4000
    escaped_text = escape_markdown(text)
    if len(escaped_text) > max_length:
        parts = [escaped_text[i:i + max_length] for i in range(0, len(escaped_text), max_length)]
        for part in parts:
            await message.reply(part, parse_mode="MarkdownV2")
    else:
        await message.reply(escaped_text, parse_mode="MarkdownV2")


def get_text_file_path(file_path: str) -> str:
    directory, filename = os.path.split(file_path)
    name, ext = os.path.splitext(filename)
    new_file_path = os.path.join(directory, f"{name}.txt")
    return new_file_path


def save_string_to_file(text: str, file_path: str) -> str:
    with open(file_path, "w") as file:
        file.write(text)
    return file_path


def transcribe_audio(file_path: str) -> str:
    try:
        # Create a Deepgram client using the API key
        deepgram = DeepgramClient(Config.DEEPGRAM_API_KEY)

        with open(file_path, "rb") as file:
            buffer_data = file.read()

        payload: FileSource = {
            "buffer": buffer_data,
        }

        options = PrerecordedOptions(
            smart_format=True,
            punctuate=True,
            paragraphs=True,
            language="ru",
            model="nova-2"
        )
        file_response = deepgram.listen.prerecorded.v("1").transcribe_file(payload, options)

        json_response = file_response.to_dict()

        results = json_response['results']
        alternatives = results['channels'][0]['alternatives']
        paragraphs = alternatives[0]['paragraphs']
        transcript = paragraphs['transcript']
        return transcript

    except Exception as e:
        return ""


@dp.message(F.voice)
@dp.message(F.audio)
async def get_audio(message: types.Message):
    mess = await message.reply("Скачиваем файл...")
    try:
        voice_object = message.voice or message.audio
        file_id = voice_object.file_id
        file = await bot.get_file(file_id)
        file_path = file.file_path
    except Exception as E:
        await message.reply(f"Ошибка: не получилось скачать файл.\n{E}")
        raise E
    finally:
        await mess.delete()

    mess = await message.reply("Преобразуем аудио в текст...")
    try:
        text = transcribe_audio(file_path)
        os.remove(file_path)

        if text == "":
            await message.reply(f"Аудио сообщение не содержит текста")
        else:
            text_file_path = save_string_to_file(text, get_text_file_path(file_path))
            text_file = FSInputFile(text_file_path, filename="summary.txt")
            await mess.reply_document(text_file)
            os.remove(text_file_path)
    except Exception as E:
        await message.reply(f"Ошибка: не получилось сделать summary.\n{E}")
        raise E
    finally:
        await mess.delete()

    mess = await message.reply("Собираем summary текста...")
    try:
        summary = summarize_text(text)
        await send_long_message(message, summary)
    except Exception as E:
        await message.reply(f"Ошибка: не получилось собрать summary.\n{E}")
        raise E
    finally:
        await mess.delete()


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
