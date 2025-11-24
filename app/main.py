# -*- coding: utf-8 -*-
import logging
import asyncio

from aiogram import Dispatcher, executor
from app.bot import dp  # dp уже включает bot, middleware, handlers

log = logging.getLogger("main")


async def on_startup(dispatcher: Dispatcher):
    try:
        me = await dispatcher.bot.get_me()
        log.info("Bot launched: %s (@%s)", me.first_name, me.username)
    except Exception as e:
        log.error("Startup get_me failed: %s", e)


if __name__ == "__main__":
    log.info("Starting polling…")
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
