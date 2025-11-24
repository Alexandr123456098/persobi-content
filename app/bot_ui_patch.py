# -*- coding: utf-8 -*-
import os
import asyncio
import logging
import tempfile
import subprocess
from pathlib import Path

from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.exceptions import InvalidQueryID

from app.adapters.replicate_adapter import ReplicateClient
from app.billing import ensure_user, plan_preview, commit_preview_charge

log = logging.getLogger("ui")

OUT_DIR = os.environ.get("OUT_DIR", "/opt/content_factory/out")
Path(OUT_DIR).mkdir(parents=True, exist_ok=True)

DEFAULT_DURATION = int(os.environ.get("DEFAULT_DURATION", "5"))
FPS_FINAL = 24
CUT_START = 0.20

_replicate = None


def _ensure_clients():
    """Гарантируем создание клиента Replicate один раз."""
    global _replicate
    if _replicate is None:
        _replicate = ReplicateClient()


def _postprocess(path: str) -> str:
    """Обрезаем первые кадры + нормализуем до 24fps + 720p."""
    src = Path(path)
    final = src.with_suffix(".fx.mp4")

    cmd = (
        f"ffmpeg -y -i \"{src}\" "
        f"-ss {CUT_START} "
        f"-vf scale=-2:720:flags=lanczos "
        f"-r {FPS_FINAL} "
        f"-c:v libx264 -preset veryfast -movflags +faststart "
        f"\"{final}\""
    )

    try:
        subprocess.run(cmd, shell=True, check=True)
    except Exception as e:
        log.error("postprocess: %s", e)
        return str(src)

    return str(final)


async def _generate(prompt: str, seconds: int, image: str | None):
    """WAN 2.2 генерация через Replicate."""
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

    return _postprocess(out)


def _menu():
    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("⏱ 5 сек", callback_data="dur5"),
        InlineKeyboardButton("⏱ 10 сек", callback_data="dur10"),
    )
    kb.add(
        InlineKeyboardButton("🔊 звук выкл", callback_data="sound_off"),
        InlineKeyboardButton("🔊 звук вкл", callback_data="sound_on"),
    )
    kb.add(InlineKeyboardButton("🧩 SORA 2", callback_data="sora2_go"))
    kb.add(InlineKeyboardButton("🔁 Ещё раз", callback_data="again"))
    return kb


async def _preview(user_id: int, prompt: str, seconds: int, sound: int):
    """Абсолютно стабильный предпросмотр — чёрный фон без drawtext."""
    ok, cost, is_free, need = plan_preview(user_id, seconds, sound)
    if not ok:
        return f"❌ Не хватает средств. Нужно {cost} ₽, нехватает {need} ₽."

    tmp = Path(tempfile.mkdtemp()) / "preview.mp4"

    cmd = (
        f"ffmpeg -y -f lavfi -i color=c=black:s=720x720:d={seconds} "
        f"-c:v libx264 -pix_fmt yuv420p \"{tmp}\""
    )

    try:
        subprocess.run(cmd, shell=True, check=True)
    except Exception as e:
        log.error("preview fail: %s", e)
        return "Ошибка предпросмотра."

    if not commit_preview_charge(user_id, cost, is_free):
        return "❌ Ошибка списания."

    return str(tmp)


async def _send_preview(message: types.Message, path: str):
    """Отправка предпросмотра пользователю."""
    try:
        await message.answer_video(open(path, "rb"), caption="🎬 Предпросмотр.")
    except Exception as e:
        log.error("send_preview: %s", e)
        await message.answer("Ошибка отправки.")


async def handle_text(message: types.Message, bot_state):
    """Пользователь отправил текст — генерируем превью."""
    user = message.from_user.id
    ensure_user(user)

    prompt = message.text.strip()
    bot_state["last_prompt"][user] = prompt

    await message.answer("🟡 Готовлю предпросмотр…", reply_markup=_menu())

    prev = await _preview(user, prompt, DEFAULT_DURATION, 0)

    if prev.endswith(".mp4"):
        await _send_preview(message, prev)
    else:
        await message.answer(prev)


async def handle_photo(message: types.Message, bot_state):
    """Фотография для image-to-video."""
    user = message.from_user.id
    ensure_user(user)

    ph = message.photo[-1]
    tmp = Path(tempfile.mkdtemp()) / "img.jpg"
    await ph.download(tmp)

    bot_state["last_image"][user] = str(tmp)

    await message.answer("🟡 Фото получено. Введи описание сцены.", reply_markup=_menu())


async def _sora2(message: types.Message, bot_state):
    """Усиленный режим SORA 2."""
    user = message.from_user.id
    ensure_user(user)

    prompt = bot_state["last_prompt"].get(user)
    if not prompt:
        await message.answer("Сначала текст.")
        return

    img = bot_state["last_image"].get(user)
    await message.answer("🧩 Генерирую SORA 2…")

    try:
        out = await _generate(prompt, DEFAULT_DURATION, img)
        await _send_preview(message, out)
    except Exception as e:
        log.error("sora2: %s", e)
        await message.answer("Ошибка генерации.")


async def handle_callback(query: types.CallbackQuery, bot_state):
    """Кнопки бота."""
    user = query.from_user.id
    ensure_user(user)

    data = query.data or ""

    try:
        if data == "again":
            await query.answer()

            prompt = bot_state["last_prompt"].get(user)
            img = bot_state["last_image"].get(user)

            if not prompt:
                await query.message.answer("Сначала текст.")
                return

            await query.message.answer("🔁 Генерирую…")

            out = await _generate(prompt, DEFAULT_DURATION, img)
            await _send_preview(query.message, out)
            return

        if data == "sora2_go":
            await query.answer()
            await _sora2(query.message, bot_state)
            return

        if data.startswith("dur"):
            await query.answer("⏱ длительность выбрана")
            bot_state.setdefault("last_dur", {})[user] = data
            return

        if data.startswith("sound_"):
            await query.answer("🔊 звук переключён")
            bot_state.setdefault("last_sound", {})[user] = data
            return

    except InvalidQueryID:
        pass
    except Exception as e:
        log.error("callback: %s", e)
        try:
            await query.message.answer("Ошибка кнопки.")
        except:
            pass
