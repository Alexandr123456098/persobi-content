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

# --- billing auto-init ---
try:
    from app.billing import init_billing
    init_billing()
    print("✅ Billing initialized at startup.")
except Exception as e:
    print(f"⚠️ Billing init failed: {e}")
# --------------------------

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

# Консоль (для journalctl)
_console = logging.StreamHandler()
_console.setFormatter(_formatter)
_console.setLevel(LOG_LEVEL)
root_logger.addHandler(_console)

# Файл с ротацией
_file = RotatingFileHandler(str(LOG_FILE), maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
_file.setFormatter(_formatter)
_file.setLevel(LOG_LEVEL)
root_logger.addHandler(_file)

log = logging.getLogger("bot")
log.info("Logging configured: level=%s, file=%s", LOG_LEVEL, LOG_FILE)
# ---------- /ЛОГИ ----------

# ---------- ГЛОБАЛЬНОЕ СОСТОЯНИЕ (DICT) ----------
# bot_ui_patch._ensure_state сам создаст недостающие ключи,
# достаточно передавать общий dict между хендлерами.
BOT_STATE: Dict[str, Dict[int, str]] = {
    "last_prompt": {},
    "last_image": {},
    "last_video": {},
}

class StateMiddleware(BaseMiddleware):
    """Прокидывает dict bot_state во все хендлеры (aiogram 2.x BaseMiddleware)."""
    def __init__(self, state_obj: Dict[str, Dict[int, str]]):
        super().__init__()
        self.state_obj = state_obj

    async def on_pre_process_message(self, message: types.Message, data: Dict[str, Any]):
        data["bot_state"] = self.state_obj

    async def on_pre_process_callback_query(self, query: types.CallbackQuery, data: Dict[str, Any]):
        data["bot_state"] = self.state_obj

def build_dp() -> Dispatcher:
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN env is empty")

    bot = Bot(token=token, parse_mode=types.ParseMode.HTML)
    storage = MemoryStorage()
    dp = Dispatcher(bot, storage=storage)

    # Прокидываем dict-состояние через корректный BaseMiddleware
    dp.middleware.setup(StateMiddleware(BOT_STATE))

    # Регистрируем хендлеры
    setup_handlers(dp)
    return dp

dp = build_dp()

async def on_startup(dispatcher: Dispatcher):
    try:
        me = await dispatcher.bot.get_me()
        log.info("Bot: %s [@%s]", me.first_name, me.username)
    except Exception as e:
        log.warning("get_me failed: %s", e)

if __name__ == "__main__":
    log.info("Polling…")
    # skip_updates=True, чтобы не утонуть в старых апдейтах
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
