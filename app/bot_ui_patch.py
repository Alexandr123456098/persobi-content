# -*- coding: utf-8 -*-
import os
import asyncio
import logging
import tempfile
import subprocess
import shutil
from pathlib import Path
from typing import Optional

from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.exceptions import InvalidQueryID

from app.adapters.replicate_adapter import ReplicateClient
from app.adapters.offline_adapter import OfflineClient
from app.billing import ensure_user, get_balance  # для calc_price

log = logging.getLogger("ui")

OUT_DIR = os.environ.get("OUT_DIR", "/opt/content_factory/out")
Path(OUT_DIR).mkdir(parents=True, exist_ok=True)

FEATURE_DURATION_SOUND_MENU = int(os.environ.get("FEATURE_DURATION_SOUND_MENU", "1"))
DEFAULT_DUR = int(os.environ.get("DEFAULT_DURATION", "5"))

# Фича-флаг для скрытия аплоада (transfer.sh шум резали на уровне UI)
ENABLE_UPLOAD = str(os.environ.get("ENABLE_UPLOAD", "false")).lower() in ("1", "true", "yes", "on")

_replicate: Optional[ReplicateClient] = None
_offline: Optional[OfflineClient] = None


def _ensure_clients():
    global _replicate, _offline
    if _replicate is None:
        _replicate = ReplicateClient()
    if _offline is None:
        _offline = OfflineClient(OUT_DIR)


# ---------- state helpers ----------

def _is_mapping(obj) -> bool:
    try:
        return hasattr(obj, "items") and callable(getattr(obj, "items"))
    except Exception:
        return False


def _get_box(state, name: str) -> dict:
    if _is_mapping(state):
        box = state.get(name)
        if not isinstance(box, dict):
            box = {}
            state[name] = box
        return box
    # fallback для простых объектов с атрибутами
    if not hasattr(state, name) or not isinstance(getattr(state, name), dict):
        try:
            setattr(state, name, {})
        except Exception:
            return {}
    return getattr(state, name)


def _ensure_state(bot_state):
    _get_box(bot_state, "last_prompt")
    _get_box(bot_state, "last_image")
    _get_box(bot_state, "last_video")
    _get_box(bot_state, "last_preview")
    _get_box(bot_state, "prefs")  # chat_id -> {"dur": int(5|10), "sound": "on"/"off"}


def _get_last_prompt(state, chat_id: int, default: str = "") -> str:
    return _get_box(state, "last_prompt").get(chat_id, default)


def _set_last_prompt(state, chat_id: int, prompt: str):
    if prompt:
        _get_box(state, "last_prompt")[chat_id] = prompt.strip()


def _get_last_image(state, chat_id: int) -> Optional[str]:
    return _get_box(state, "last_image").get(chat_id)


def _set_last_image(state, chat_id: int, path: Optional[str]):
    if path and os.path.exists(path):
        _get_box(state, "last_image")[chat_id] = path


def _get_last_video(state, chat_id: int) -> Optional[str]:
    return _get_box(state, "last_video").get(chat_id)


def _set_last_video(state, chat_id: int, path: Optional[str]):
    if path and os.path.exists(path):
        _get_box(state, "last_video")[chat_id] = path


def _get_last_preview(state, chat_id: int) -> Optional[str]:
    return _get_box(state, "last_preview").get(chat_id)


def _set_last_preview(state, chat_id: int, path: Optional[str]):
    if path and os.path.exists(path):
        _get_box(state, "last_preview")[chat_id] = path


def _get_prefs(state, chat_id: int) -> dict:
    prefs = _get_box(state, "prefs").get(chat_id)
    if not isinstance(prefs, dict):
        prefs = {"dur": DEFAULT_DUR, "sound": "off"}
        _get_box(state, "prefs")[chat_id] = prefs
    # нормализация
    prefs["dur"] = int(prefs.get("dur", DEFAULT_DUR))
    if prefs["dur"] not in (5, 10):
        prefs["dur"] = 5
    s = str(prefs.get("sound", "off")).lower()
    prefs["sound"] = "on" if s in ("on", "1", "true", "yes") else "off"
    _get_box(state, "prefs")[chat_id] = prefs
    return prefs


def _set_pref(state, chat_id: int, key: str, value):
    prefs = _get_prefs(state, chat_id)
    prefs[key] = value
    _get_box(state, "prefs")[chat_id] = prefs


# ---------- keyboards ----------

def kb_ready():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(
        InlineKeyboardButton("🔁 Ещё раз", callback_data="again"),
        InlineKeyboardButton("🧩 SORA 2", callback_data="sora2_go"),
    )
    if ENABLE_UPLOAD:
        kb.row(
            InlineKeyboardButton("📷 По фото", callback_data="photo_help"),
            InlineKeyboardButton("🎬 По видео", callback_data="video_help"),
        )
    kb.row(InlineKeyboardButton("⚙️ Настройки", callback_data="menu_config"))
    return kb


def kb_menu_config(state, chat_id: int):
    kb = InlineKeyboardMarkup(row_width=2)
    if FEATURE_DURATION_SOUND_MENU:
        kb.row(InlineKeyboardButton("⏱ 10 секунд", callback_data="dur_set10"))
        kb.row(
            InlineKeyboardButton("🎙 Со звуком", callback_data="sound_on"),
            InlineKeyboardButton("🔇 Без звука", callback_data="sound_off"),
        )
        kb.row(InlineKeyboardButton("💵 Посчитать цену", callback_data="calc_price"))
    return kb


# ---------- helpers ----------

def _cinema_prompt(user_text: str) -> str:
    raw = (user_text or "").strip()
    return raw if raw else "Short daylight scene."


def _run(cmd: list[str]) -> bool:
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def _try_ffmpeg_frame(src_video: str, dst_jpg: str) -> bool:
    return (
        _run(["ffmpeg", "-y", "-ss", "1", "-i", src_video, "-frames:v", "1", "-q:v", "3", dst_jpg])
        or _run(["ffmpeg", "-y", "-i", src_video, "-frames:v", "1", "-q:v", "3", dst_jpg])
    ) and os.path.exists(dst_jpg) and os.stat(dst_jpg).st_size > 0


def _try_ffmpeg(src: str, dst: str) -> bool:
    return (
        _run(["ffmpeg", "-y", "-i", src, "-vf", "format=rgb24", "-q:v", "3", dst])
        and os.path.exists(dst) and os.stat(dst).st_size > 0
    )


def _try_imagemagick(src: str, dst: str) -> bool:
    for cmd in (["magick", src, "-auto-orient", "-quality", "92", dst],
                ["convert", src, "-auto-orient", "-quality", "92", dst]):
        if _run(cmd) and os.path.exists(dst) and os.stat(dst).st_size > 0:
            return True
    return False


def _try_pillow(src: str, dst: str) -> bool:
    try:
        from PIL import Image
        Image.open(src).convert("RGB").save(dst, "JPEG", quality=92, optimize=True)
        return os.path.exists(dst) and os.stat(dst).st_size > 0
    except Exception:
        return False


def _reencode_to_jpeg(src_path: str) -> str:
    dst = str(Path(src_path).with_suffix(".jpg"))
    ok = _try_ffmpeg(src_path, dst) or _try_imagemagick(src_path, dst) or _try_pillow(src_path, dst)
    try:
        shutil.copy2(dst if ok else src_path, Path(OUT_DIR) / "last_upload.jpg")
    except Exception:
        pass
    return dst if ok else src_path


async def _ack_cb(query: types.CallbackQuery):
    try:
        await query.answer(cache_time=0)
    except InvalidQueryID:
        pass


def _store_preview_and_reply_path(bot_state, chat_id: int, path: str):
    _set_last_preview(bot_state, chat_id, path)


def _maybe_add_audio(video_in: str, seconds: int, sound: str) -> str:
    """
    Пост-обработка без изменения длительности:
    - Если sound == 'on' — подмешиваем мягкий SFX и возвращаем -shortest.
    - Если 'off' — возвращаем исходник как есть.
    """
    want_audio = (str(sound).lower() == "on")
    if not want_audio:
        return video_in

    out = str(Path(OUT_DIR) / f"cf_audio_{Path(video_in).stem}.mp4")
    sfx = str(Path(OUT_DIR) / f"sfx_{seconds}s.wav")
    if not _run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anoisesrc=a=0.001:color=pink:r=48000",
                 "-t", str(seconds), "-af", "lowpass=f=900,volume=0.18", sfx]):
        return video_in
    ok = _run(["ffmpeg", "-y", "-i", video_in, "-i", sfx,
               "-c:v", "copy", "-c:a", "aac", "-shortest", out])
    try:
        os.remove(sfx)
    except Exception:
        pass
    return out if ok and os.path.exists(out) and os.stat(out).st_size > 0 else video_in


def _apply_postprocess(path: str, seconds: int, sound: str) -> str:
    try:
        return _maybe_add_audio(path, seconds, sound)
    except Exception as e:
        log.warning("postprocess failed (%s); return original %s", e, path)
        return path


# ---------- GENERATORS (с ретраями) ----------

async def _gen_from_text(prompt: str, seconds: int) -> str:
    loop = asyncio.get_event_loop()
    # до 2 попыток Replicate, затем оффлайн
    for attempt in range(1, 3):
        try:
            path = await loop.run_in_executor(None, _replicate.generate_from_text, prompt, seconds)
            if path and os.path.exists(path) and os.stat(path).st_size > 0:
                log.info("[ui] replicate(text) OK: %s", path)
                return path
            raise RuntimeError("replicate(text) returned empty path")
        except Exception as e:
            log.warning("[ui] replicate(text) attempt %d failed: %s", attempt, e)
    return await loop.run_in_executor(None, _offline.generate, prompt, seconds)


async def _gen_from_image(img_path: str, prompt: str, seconds: int) -> str:
    loop = asyncio.get_event_loop()
    # до 2 попыток Replicate, затем оффлайн
    for attempt in range(1, 3):
        try:
            path = await loop.run_in_executor(None, _replicate.generate_from_image, img_path, prompt, seconds)
            if path and os.path.exists(path) and os.stat(path).st_size > 0:
                log.info("[ui] replicate(image) OK: %s", path)
                return path
            raise RuntimeError("replicate(image) returned empty path")
        except Exception as e:
            log.warning("[ui] replicate(image) attempt %d failed: %s", attempt, e)
    return await loop.run_in_executor(None, _offline.generate, prompt, seconds)


# ---------- MESSAGE HANDLERS ----------

async def handle_text(message: types.Message, bot_state):
    _ensure_clients()
    _ensure_state(bot_state)

    prompt = (message.text or "").strip()
    if not prompt:
        return await message.answer("Напиши описание сцены.")

    chat_id = message.chat.id
    _set_last_prompt(bot_state, chat_id, prompt)
    _get_box(bot_state, "last_image").pop(chat_id, None)

    p = _get_prefs(bot_state, chat_id)
    seconds = int(p["dur"])
    sound = p["sound"]

    await message.answer("🛠 Генерирую превью…")
    path = await _gen_from_text(prompt, seconds)
    path = _apply_postprocess(path, seconds, sound)

    _store_preview_and_reply_path(bot_state, chat_id, path)
    with open(path, "rb") as f:
        await message.answer_video(f, caption="✅ Готово. Предпросмотр:", reply_markup=kb_ready())


async def handle_photo(message: types.Message, bot_state):
    _ensure_clients()
    _ensure_state(bot_state)

    if not ENABLE_UPLOAD:
        return await message.answer("Загрузка по фото временно отключена.", reply_markup=kb_ready())

    caption = _cinema_prompt(message.caption or "")
    chat_id = message.chat.id
    _set_last_prompt(bot_state, chat_id, caption or "сделай видео по фото")

    p = _get_prefs(bot_state, chat_id)
    seconds = int(p["dur"])
    sound = p["sound"]

    await message.answer("🛠 Генерирую превью по фото…")
    loop = asyncio.get_event_loop()
    tmp_path = None
    jpath = None
    try:
        fd, tmp_path = tempfile.mkstemp(prefix="cf_photo_", suffix=".img", dir=OUT_DIR)
        os.close(fd)
        if getattr(message, "photo", None):
            await message.photo[-1].download(destination_file=tmp_path)
        elif getattr(message, "document", None):
            await message.document.download(destination_file=tmp_path)
        else:
            raise RuntimeError("no photo/document in message")

        jpath = _reencode_to_jpeg(tmp_path)
        path = await _gen_from_image(jpath, caption or "", seconds)
    except Exception as e:
        log.warning("[ui] photo flow failed: %s — fallback offline", e)
        path = await loop.run_in_executor(None, _offline.generate, caption, seconds)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    path = _apply_postprocess(path, seconds, sound)
    if jpath:
        _set_last_image(bot_state, chat_id, jpath)
    _store_preview_and_reply_path(bot_state, chat_id, path)
    with open(path, "rb") as f:
        await message.answer_video(f, caption="✅ Готово. Предпросмотр:", reply_markup=kb_ready())


async def handle_video(message: types.Message, bot_state):
    _ensure_clients()
    _ensure_state(bot_state)

    if not ENABLE_UPLOAD:
        return await message.answer("Загрузка по видео временно отключена.", reply_markup=kb_ready())

    caption = _cinema_prompt(message.caption or "")
    chat_id = message.chat.id
    _set_last_prompt(bot_state, chat_id, caption)
    await message.answer("🛠 Обрабатываю видео…")

    p = _get_prefs(bot_state, chat_id)
    seconds = int(p["dur"])
    sound = p["sound"]

    loop = asyncio.get_event_loop()
    tmp_video = None
    frame_jpg = None
    try:
        fdv, tmp_video = tempfile.mkstemp(prefix="cf_video_", suffix=".mp4", dir=OUT_DIR)
        os.close(fdv)
        await message.video.download(destination_file=tmp_video)
        _set_last_video(bot_state, chat_id, tmp_video)

        frame_jpg = str(Path(tmp_video).with_suffix(".jpg"))
        if not _try_ffmpeg_frame(tmp_video, frame_jpg):
            raise RuntimeError("ffmpeg frame extract failed")

        jpath = _reencode_to_jpeg(frame_jpg)
        path = await _gen_from_image(jpath, caption or "", seconds)

    except Exception as e:
        log.warning("[ui] video flow failed: %s — fallback offline", e)
        path = await loop.run_in_executor(None, _offline.generate, caption, seconds)
    finally:
        if frame_jpg and os.path.exists(frame_jpg):
            try:
                os.remove(frame_jpg)
            except Exception:
                pass

    path = _apply_postprocess(path, seconds, sound)
    _store_preview_and_reply_path(bot_state, chat_id, path)
    with open(path, "rb") as f:
        await message.answer_video(f, caption="✅ Готово. Предпросмотр:", reply_markup=kb_ready())


# ---------- CALLBACKS ----------

async def handle_callback(query: types.CallbackQuery, bot_state):
    from app.pricing import price

    _ensure_clients()
    _ensure_state(bot_state)
    data = (query.data or "").strip()
    chat_id = query.message.chat.id if query.message else None

    await _ack_cb(query)
    ensure_user(chat_id)

    # Меню настроек
    if data == "menu_config":
        kb = kb_menu_config(bot_state, chat_id)
        await query.message.answer("⚙️ Настройки генерации:", reply_markup=kb)
        return

    # Применение 10 секунд — без автогенерации
    if data == "dur_set10":
        _set_pref(bot_state, chat_id, "dur", 10)
        await query.message.answer("⏱ 10 секунд применено.")
        return

    # Звук вкл/выкл — без автогенерации
    if data == "sound_on":
        _set_pref(bot_state, chat_id, "sound", "on")
        await query.message.answer("🎙 Озвучка включена.")
        return

    if data == "sound_off":
        _set_pref(bot_state, chat_id, "sound", "off")
        await query.message.answer("🔇 Озвучка отключена.")
        return

    # Подсчёт цены и подтверждение
    if data == "calc_price":
        p = _get_prefs(bot_state, chat_id)
        dur = int(p["dur"])
        snd = 1 if p["sound"] == "on" else 0
        cost = price(dur, snd)
        bal = get_balance(chat_id)

        sel = f"Выбрано: {dur} сек, " + ("со звуком" if snd else "без звука")
        kb = InlineKeyboardMarkup()
        if bal >= cost:
            kb.add(InlineKeyboardButton("✅ Согласен, генерировать", callback_data="confirm_pay"))
        else:
            kb.add(InlineKeyboardButton("💳 Пополнить баланс", callback_data="add_money"))

        await query.message.answer(f"{sel}\n💵 Стоимость: {cost} ₽\n💰 Баланс: {bal} ₽", reply_markup=kb)
        return

    if data == "add_money":
        from app.billing import add_balance
        add_balance(chat_id, 200, "Пополнение через кнопку")
        # повторный расчёт
        fake = types.CallbackQuery(id=query.id, from_user=query.from_user,
                                   message=query.message, data="calc_price")
        await handle_callback(fake, bot_state)
        return

    if data == "confirm_pay":
        from app.billing import charge
        p = _get_prefs(bot_state, chat_id)
        dur = int(p["dur"])
        snd = 1 if p["sound"] == "on" else 0
        cost = price(dur, snd)
        bal = get_balance(chat_id)
        if bal < cost:
            await query.message.answer("❌ Недостаточно средств.")
            return
        charge(chat_id, 0, cost)
        await query.message.answer(f"✅ Оплачено {cost} ₽. Генерация…")
        # запускаем основную генерацию
        fake = types.CallbackQuery(id=query.id, from_user=query.from_user,
                                   message=query.message, data="sora2_go")
        await handle_callback(fake, bot_state)
        return

    # Генерации
    if data == "again":
        await query.message.answer("🛠 Генерирую превью…")
        last_img = _get_last_image(bot_state, chat_id)
        prompt = _get_last_prompt(bot_state, chat_id, default="Short daylight scene.")
        p = _get_prefs(bot_state, chat_id)
        seconds = int(p["dur"])
        sound = p["sound"]
        loop = asyncio.get_event_loop()
        try:
            if last_img and os.path.exists(last_img):
                jpath = _reencode_to_jpeg(last_img)
                path = await _gen_from_image(jpath, prompt, seconds)
                log.info("[ui] again(photo) OK: %s", path)
            else:
                path = await _gen_from_text(prompt, seconds)
                log.info("[ui] again(text) OK: %s", path)
        except Exception as e:
            log.warning("[ui] again failed: %s — fallback offline", e)
            path = await loop.run_in_executor(None, _offline.generate, prompt, seconds)

        path = _apply_postprocess(path, seconds, sound)
        _store_preview_and_reply_path(bot_state, chat_id, path)
        with open(path, "rb") as f:
            await query.message.answer_video(f, caption="✅ Готово. Предпросмотр:", reply_markup=kb_ready())
        return

    if data == "sora2_go":
        await query.message.answer("🧩 Генерирую SORA 2…")
        loop = asyncio.get_event_loop()
        p = _get_prefs(bot_state, chat_id)
        seconds = int(p["dur"])
        sound = p["sound"]
        prompt = _get_last_prompt(bot_state, chat_id, default="Short daylight scene.")

        last_video = _get_last_video(bot_state, chat_id)
        last_img = _get_last_image(bot_state, chat_id)
        last_prev = _get_last_preview(bot_state, chat_id)

        try:
            if last_video and os.path.exists(last_video):
                frame = str(Path(last_video).with_suffix(".jpg"))
                if not _try_ffmpeg_frame(last_video, frame):
                    raise RuntimeError("sora2: frame from last_video failed")
                jpath = _reencode_to_jpeg(frame)
                path = await _gen_from_image(jpath, prompt, seconds)
                log.info("[ui] sora2(video->frame) OK: %s", path)
            elif last_img and os.path.exists(last_img):
                jpath = _reencode_to_jpeg(last_img)
                path = await _gen_from_image(jpath, prompt, seconds)
                log.info("[ui] sora2(photo) OK: %s", path)
            elif last_prev and os.path.exists(last_prev):
                frame = str(Path(last_prev).with_suffix(".jpg"))
                if not _try_ffmpeg_frame(last_prev, frame):
                    raise RuntimeError("sora2: frame from last_preview failed")
                jpath = _reencode_to_jpeg(frame)
                path = await _gen_from_image(jpath, prompt, seconds)
                log.info("[ui] sora2(prev->frame) OK: %s", path)
            else:
                path = await _gen_from_text(prompt, seconds)
                log.info("[ui] sora2(text) OK: %s", path)
        except Exception as e:
            log.warning("[ui] sora2 failed: %s — fallback offline", e)
            path = await loop.run_in_executor(None, _offline.generate, prompt, seconds)

        path = _apply_postprocess(path, seconds, sound)
        _store_preview_and_reply_path(bot_state, chat_id, path)
        with open(path, "rb") as f:
            await query.message.answer_video(f, caption="✅ Готово. Предпросмотр:", reply_markup=kb_ready())
        return

    if data == "photo_help":
        await query.message.answer("Пришли фото и описание — сделаю ролик.")
        return

    if data == "video_help":
        await query.message.answer("Пришли короткое видео и описание — сделаю ролик.")
        return
