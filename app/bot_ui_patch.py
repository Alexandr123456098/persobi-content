# -*- coding: utf-8 -*-
import os
import asyncio
import logging
import tempfile
import subprocess
import shutil
from pathlib import Path

from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.exceptions import InvalidQueryID

from app.adapters.replicate_adapter import ReplicateClient
from app.adapters.offline_adapter import OfflineClient
from app.billing import ensure_user, plan_preview, commit_preview_charge

log = logging.getLogger("ui")

OUT_DIR = os.environ.get("OUT_DIR", "/opt/content_factory/out")
Path(OUT_DIR).mkdir(parents=True, exist_ok=True)

FEATURE_DURATION_SOUND_MENU = int(os.environ.get("FEATURE_DURATION_SOUND_MENU", "1"))
DEFAULT_DUR = int(os.environ.get("DEFAULT_DURATION", "5"))

_replicate = None
_offline = None

I2V_STRICT = True


def _ensure_clients():
    global _replicate, _offline
    if _replicate is None:
        _replicate = ReplicateClient()
    if _offline is None:
        _offline = OfflineClient(OUT_DIR)


def _apply_postprocess(path: str) -> str:
    """
    Главный фикс пережжённого старта:
    — отрезаем первые ~0.2 секунды (5 кадров при 24 fps),
    — приводим к 720p,
    — приводим к fps=24.
    """
    src = Path(path)
    final = src.with_suffix(".clean.mp4")
    cmd = (
        f"ffmpeg -y -i {src} "
        f"-ss 0.20 "
        f"-vf scale=-2:720:flags=lanczos "
        f"-r 24 "
        f"-c:v libx264 -preset veryfast -movflags +faststart "
        f"{final}"
    )
    try:
        subprocess.run(cmd, shell=True, check=True)
    except Exception as e:
        log.error("postprocess failed: %s", e)
        return path
    return str(final)


def _dur_to_seconds(btn: str) -> int:
    if btn == "dur5":
        return 5
    if btn == "dur10":
        return 10
    return DEFAULT_DUR


def _sound_flag(btn: str) -> int:
    return 1 if btn == "sound_on" else 0


def _menu_kb():
    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("⏱ 5 сек", callback_data="dur5"),
        InlineKeyboardButton("⏱ 10 сек", callback_data="dur10"),
    )
    kb.add(
        InlineKeyboardButton("🔊 Звук: выкл", callback_data="sound_off"),
        InlineKeyboardButton("🔊 Звук: вкл", callback_data="sound_on"),
    )
    kb.add(InlineKeyboardButton("🧩 SORA 2", callback_data="sora2_go"))
    kb.add(InlineKeyboardButton("🔁 Ещё раз", callback_data="again"))
    return kb


async def _send_preview(message: types.Message, path: str):
    try:
        await message.answer_video(
            open(path, "rb"),
            caption="🎬 Предпросмотр готов.",
        )
    except Exception as e:
        log.error("send_preview: %s", e)
        await message.answer("Ошибка отправки файла.")


async def _make_preview(user_id: int, prompt: str, seconds: int, sound: int) -> str:
    _ensure_clients()

    ok, cost, is_free, need = plan_preview(user_id, seconds, sound)
    if not ok:
        return f"❌ Недостаточно средств. Нужно {cost} ₽, не хватает {need} ₽."

    # Offline: текстовый фон + шум
    path = await _offline.generate_video(prompt, seconds)

    if not commit_preview_charge(user_id, cost, is_free):
        return "❌ Ошибка списания."

    return path


async def _gen_full(prompt: str, seconds: int, image: str | None = None):
    _ensure_clients()

    if image:
        out = _replicate.generate_from_image(
            image=image,
            prompt=prompt,
            seconds=seconds,
        )
    else:
        out = _replicate.generate_from_text(
            prompt=prompt,
            seconds=seconds,
        )

    out = _apply_postprocess(out)
    return out


async def handle_text(message: types.Message, bot_state):
    user_id = message.from_user.id
    ensure_user(user_id)

    prompt = message.text.strip()
    bot_state["last_prompt"][user_id] = prompt

    await message.answer("🟡 Готовлю предпросмотр…", reply_markup=_menu_kb())

    path = await _make_preview(user_id, prompt, seconds=DEFAULT_DUR, sound=0)
    if path.endswith(".mp4"):
        await _send_preview(message, path)
    else:
        await message.answer(path)


async def handle_photo(message: types.Message, bot_state):
    user_id = message.from_user.id
    ensure_user(user_id)

    if not message.photo:
        await message.answer("Нужна фотография.")
        return

    ph = message.photo[-1]
    tmp = Path(tempfile.mkdtemp()) / "img.jpg"
    await ph.download(tmp)

    bot_state["last_image"][user_id] = str(tmp)
    await message.answer("🟡 Получил фото. Введи описание сцены.", reply_markup=_menu_kb())


async def handle_video(message: types.Message, bot_state):
    await message.answer("📹 Видео как вход пока не обрабатываю.")


async def _run_sora2(message: types.Message, bot_state):
    user_id = message.from_user.id
    ensure_user(user_id)

    prompt = bot_state["last_prompt"].get(user_id)
    if not prompt:
        await message.answer("Сначала отправь текст.")
        return

    img = bot_state["last_image"].get(user_id)

    await message.answer("🧩 Генерирую SORA 2…")

    out = await _gen_full(prompt, seconds=DEFAULT_DUR, image=img)
    await _send_preview(message, out)


async def handle_callback(query: types.CallbackQuery, bot_state):
    user_id = query.from_user.id
    ensure_user(user_id)

    data = query.data or ""

    try:
        if data == "again":
            await query.answer()
            msg = query.message
            prompt = bot_state["last_prompt"].get(user_id)
            img = bot_state["last_image"].get(user_id)
            if not prompt:
                await msg.answer("Сначала напиши текст.")
                return
            await msg.answer("🔁 Генерирую снова…")
            out = await _gen_full(prompt, DEFAULT_DUR, image=img)
            await _send_preview(msg, out)
            return

        if data == "sora2_go":
            await query.answer()
            await _run_sora2(query.message, bot_state)
            return

        if data.startswith("dur"):
            await query.answer("⏱ Выбрана длительность")
            bot_state["last_dur"] = data
            return

        if data.startswith("sound_"):
            await query.answer("🔊 Звук переключён")
            bot_state["last_sound"] = data
            return

    except InvalidQueryID:
        pass
    except Exception as e:
        log.error("callback error: %s", e)
        try:
            await query.message.answer("Ошибка обработки кнопки.")
        except Exception:
            pass
