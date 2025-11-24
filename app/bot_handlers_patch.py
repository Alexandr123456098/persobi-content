# -*- coding: utf-8 -*-
import logging
from aiogram import types, Dispatcher

from app.bot_ui_patch import (
    handle_text,
    handle_photo,
    handle_video,
    handle_callback,
)

log = logging.getLogger("handlers")


def setup_handlers(dp: Dispatcher):

    @dp.message_handler(content_types=["text"])
    async def _text(message: types.Message, bot_state):
        try:
            await handle_text(message, bot_state)
        except Exception as e:
            log.error("text handler: %s", e)
            await message.answer("Ошибка обработки текста.")

    @dp.message_handler(content_types=["photo"])
    async def _photo(message: types.Message, bot_state):
        try:
            await handle_photo(message, bot_state)
        except Exception as e:
            log.error("photo handler: %s", e)
            await message.answer("Ошибка обработки фото.")

    @dp.message_handler(content_types=["video"])
    async def _video(message: types.Message, bot_state):
        try:
            await handle_video(message, bot_state)
        except Exception as e:
            log.error("video handler: %s", e)
            await message.answer("Ошибка обработки видео.")

    @dp.callback_query_handler()
    async def _cb(query: types.CallbackQuery, bot_state):
        try:
            await handle_callback(query, bot_state)
        except Exception as e:
            log.error("callback handler: %s", e)
            try:
                await query.message.answer("Ошибка обработки кнопки.")
            except:
                pass
