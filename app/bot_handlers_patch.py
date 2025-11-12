# -*- coding: utf-8 -*-
import logging
from aiogram import types, Dispatcher

from app.bot_ui_patch import (
    handle_text,
    handle_callback,
    handle_photo,
    handle_video,
)

log = logging.getLogger("handlers")

# --- Команды/сообщения ---

async def start_cmd(message: types.Message, bot_state):
    # Только приветствие. Никаких автогенераций.
    await message.answer(
        "👋 Добро пожаловать в Persobi Content!\n"
        "Опиши идею, пришли фото или короткое видео — сделаю ролик.\n"
        "Для тонких настроек нажми «⏱ Длительность / 🔊 Звук»."
    )

async def any_text(message: types.Message, bot_state):
    # Игнорируем команды вида /xxx, чтобы /start и прочие не улетали в генерацию
    if (message.text or "").strip().startswith("/"):
        return
    await handle_text(message, bot_state)

async def any_photo(message: types.Message, bot_state):
    await handle_photo(message, bot_state)

async def any_video(message: types.Message, bot_state):
    await handle_video(message, bot_state)

# --- Кнопки ---

async def any_callback(query: types.CallbackQuery, bot_state):
    await handle_callback(query, bot_state)

# --- Регистрация всех хендлеров в Dispatcher ---

def setup_handlers(dp: Dispatcher):
    dp.register_message_handler(start_cmd, commands=["start"], state="*")

    dp.register_message_handler(any_photo,
                               content_types=["photo", "document"],
                               state="*")

    dp.register_message_handler(any_video,
                               content_types=["video"],
                               state="*")

    dp.register_message_handler(any_text,
                               content_types=["text"],
                               state="*")

    dp.register_callback_query_handler(any_callback, lambda c: True, state="*")
