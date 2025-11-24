# -*- coding: utf-8 -*-
import asyncio
import logging
import uvloop
from pathlib import Path
from aiogram import Dispatcher
from aiogram.contrib.fsm_storage.memory import MemoryStorage

# Берём dp и bot из bot_ui_patch (главная логика здесь)
from app.bot_ui_patch import dp, bot

LOG_DIR = Path("/opt/content_factory/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "main.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8")
    ],
)

log = logging.getLogger("main")
log.info("main.py loaded")


async def on_startup(dispatcher: Dispatcher):
    try:
        me = await dispatcher.bot.get_me()
        log.info("Bot started: %s @%s", me.first_name, me.username)
    except Exception as e:
        log.warning("get_me failed: %s", e)


def main():
    uvloop.install()
    log.info("Polling start")
    from aiogram import executor
    executor.start_polling(
        dp,
        skip_updates=True,
        on_startup=on_startup,
        allowed_updates=[
            "message",
            "edited_message",
            "callback_query",
            "inline_query"
        ]
    )


if __name__ == "__main__":
    main()
