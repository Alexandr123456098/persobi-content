# -*- coding: utf-8 -*-
import os
import logging
from typing import Any, Dict
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.middlewares import BaseMiddleware

from app.bot_handlers_patch import setup_handlers
from app.billing import init_billing

# ---------- ИНИЦИАЛИЗАЦИЯ BILLING ----------
try:
    init_billing()
    print("✅ Billing initialized.")
except Exception as e:
    print(f"⚠️ Billing init failed: {e}")

# ---------- ЛОГИ ----------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_DIR = Path("/opt/content_factory/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "bot.log"

_formatter = logging.Formatter(
    fmt="%(asctime)s %(levelname)s:%(name)s:%(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

root_logger = logging.getLogger()
root_logger.setLevel(LOG_LEVEL)

_console = logging.StreamHandler()
_console.setFormatter(_formatter)
_console.setLevel(LOG_LEVEL)
root_logger.addHandler(_console)

_file = RotatingFileHandler(
    str(LOG_FILE),
    maxBytes=5 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8"
)
_file.setFormatter(_formatter)
_file.setLevel(LOG_LEVEL)
root_logger.addHandler(_file)

log = logging.getLogger("bot")
log.info("Logging configured.")

# ---------- ГЛОБАЛЬНОЕ СОСТОЯНИЕ ----------
BOT_STATE: Dict[str, Dict[int, Any]] = {
    "last_prompt": {},
    "last_image": {},
    "last_dur": {},
    "last_sound": {},
}

# ---------- MIDDLEWARE ----------
class StateMiddleware(BaseMiddleware):
    def __init__(self, state_obj: Dict[str, Dict[int, Any]]):
        super().__init__()
        self.state_obj = state_obj

    async def on_pre_process_message(self, message: types.Message, data: Dict[str, Any]):
        data["bot_state"] = self.state_obj

    async def on_pre_process_callback_query(self, query: types.CallbackQuery, data: Dict[str, Any]):
        data["bot_state"] = self.state_obj

# ---------- DP / BOT ----------
def build_dp():
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN not set in environment")

    bot = Bot(token=token, parse_mode=types.ParseMode.HTML)
    storage = MemoryStorage()
    dp = Dispatcher(bot, storage=storage)

    dp.middleware.setup(StateMiddleware(BOT_STATE))
    setup_handlers(dp)

    return dp, bot

dp, bot = build_dp()

# ---------- STARTUP ----------
async def on_startup(dispatcher: Dispatcher):
    try:
        me = await dispatcher.bot.get_me()
        log.info("Bot started: %s @%s", me.first_name, me.username)
    except Exception as e:
        log.warning("get_me failed: %s", e)

# ---------- MAIN ----------
if __name__ == "__main__":
    log.info("Polling…")
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
