# -*- coding: utf-8 -*-
import os, random
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
from app.billing import ensure_user, get_balance, register_preview_and_charge  # тарификация превью
from app.pricing import price as price_fn

log = logging.getLogger("ui")

OUT_DIR = os.environ.get("OUT_DIR", "/opt/content_factory/out")
Path(OUT_DIR).mkdir(parents=True, exist_ok=True)

FEATURE_DURATION_SOUND_MENU = int(os.environ.get("FEATURE_DURATION_SOUND_MENU", "1"))

# Длительность храним как float: 5.0 или 7.5
DEFAULT_DUR = float(os.environ.get("DEFAULT_DURATION", "5"))
if DEFAULT_DUR not in (5.0, 7.5):
    DEFAULT_DUR = 5.0

# Фича-флаг аплоада
ENABLE_UPLOAD = str(os.environ.get("ENABLE_UPLOAD", "false")).lower() in ("1", "true", "yes", "on")

_replicate: Optional[ReplicateClient] = None
_offline: Optional[OfflineClient] = None

def _ensure_clients():
    global _replicate, _offline
    if _replicate is None:
        _replicate = ReplicateClient()
    if _offline is None:
        _offline = OfflineClient(OUT_DIR)

# ---------- helpers: system ----------

def _run(cmd: list[str]) -> bool:
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

def _ack_cb_sync(query: types.CallbackQuery):
    try:
        return asyncio.create_task(query.answer(cache_time=0))
    except InvalidQueryID:
        return None

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
    _get_box(bot_state, "last_seed")   # chat_id -> int
    _get_box(bot_state, "prefs")       # chat_id -> {"dur": float(5|7.5), "sound": "on"/"off"}

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

def _get_last_seed(state, chat_id: int) -> Optional[int]:
    v = _get_box(state, "last_seed").get(chat_id)
    try:
        return int(v) if v is not None else None
    except Exception:
        return None

def _set_last_seed(state, chat_id: int, seed: int):
    _get_box(state, "last_seed")[chat_id] = int(seed)

def _get_prefs(state, chat_id: int) -> dict:
    prefs = _get_box(state, "prefs").get(chat_id)
    if not isinstance(prefs, dict):
        prefs = {"dur": DEFAULT_DUR, "sound": "off"}
        _get_box(state, "prefs")[chat_id] = prefs
    # нормализация
    try:
        prefs["dur"] = float(prefs.get("dur", DEFAULT_DUR))
    except Exception:
        prefs["dur"] = 5.0
    if prefs["dur"] not in (5.0, 7.5):
        prefs["dur"] = 5.0
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
        kb.row(InlineKeyboardButton("⏱ 7.5 секунд", callback_data="dur_set75"))
        kb.row(
            InlineKeyboardButton("🎙 Со звуком", callback_data="sound_on"),
            InlineKeyboardButton("🔇 Без звука", callback_data="sound_off"),
        )
        kb.row(InlineKeyboardButton("💵 Посчитать цену", callback_data="calc_price"))
    return kb

# ---------- media helpers ----------

def _cinema_prompt(user_text: str) -> str:
    raw = (user_text or "").strip()
    return raw if raw else "Short daylight scene."

def _reencode_to_jpeg(src_path: str) -> str:
    dst = str(Path(src_path).with_suffix(".jpg"))
    ok = (
        _run(["ffmpeg", "-y", "-i", src_path, "-vf", "format=rgb24", "-q:v", "3", dst])
        or any([
            _run(["magick", src_path, "-auto-orient", "-quality", "92", dst]),
            _run(["convert", src_path, "-auto-orient", "-quality", "92", dst]),
        ])
    )
    try:
        shutil.copy2(dst if ok else src_path, Path(OUT_DIR) / "last_upload.jpg")
    except Exception:
        pass
    return dst if ok else src_path

def _try_ffmpeg_frame(src_video: str, dst_jpg: str) -> bool:
    return (
        _run(["ffmpeg", "-y", "-ss", "0.5", "-i", src_video, "-frames:v", "1", "-q:v", "3", dst_jpg])
        or _run(["ffmpeg", "-y", "-i", src_video, "-frames:v", "1", "-q:v", "3", dst_jpg])
    ) and os.path.exists(dst_jpg) and os.stat(dst_jpg).st_size > 0

def _quick_preview_from_image(img_path: str, seconds: float) -> str:
    """Быстрый Ken Burns из того же изображения (10–15 сек SLA)."""
    out = str(Path(OUT_DIR) / f"kb_{Path(img_path).stem}_{int(seconds*1000)}.mp4")
    # лёгкий зум-пан
    vf = f"zoompan=z='min(zoom+0.0008,1.2)':d={int(16*seconds)}:s=720x720"
    _run(["ffmpeg", "-y", "-loop", "1", "-i", img_path, "-vf", vf, "-t", f"{float(seconds):.2f}",
          "-an", "-c:v", "libx264", "-preset", "veryfast", out])
    return out if os.path.exists(out) and os.stat(out).st_size > 0 else img_path

def _quick_preview_from_video(video_path: str, seconds: float) -> str:
    """Быстрый обрез из того же видео."""
    out = str(Path(OUT_DIR) / f"trim_{Path(video_path).stem}_{int(seconds*1000)}.mp4")
    _run(["ffmpeg", "-y", "-i", video_path, "-ss", "0", "-t", f"{float(seconds):.2f}",
          "-an", "-c:v", "libx264", "-preset", "veryfast", out])
    return out if os.path.exists(out) and os.stat(out).st_size > 0 else video_path

def _maybe_add_audio(video_in: str, seconds: float, sound: str) -> str:
    want_audio = (str(sound).lower() == "on")
    if not want_audio:
        return video_in
    out = str(Path(OUT_DIR) / f"cf_audio_{Path(video_in).stem}.mp4")
    sfx = str(Path(OUT_DIR) / f"sfx_{int(seconds*10)}.wav")
    if not _run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anoisesrc=a=0.001:color=pink:r=48000",
                 "-t", f"{float(seconds):.2f}", "-af", "lowpass=f=900,volume=0.18", sfx]):
        return video_in
    ok = _run(["ffmpeg", "-y", "-i", video_in, "-i", sfx, "-c:v", "copy", "-c:a", "aac", "-shortest", out])
    try: os.remove(sfx)
    except Exception: pass
    return out if ok and os.path.exists(out) and os.stat(out).st_size > 0 else video_in

def _apply_postprocess(path: str, seconds: float, sound: str) -> str:
    try:
        return _maybe_add_audio(path, seconds, sound)
    except Exception as e:
        log.warning("postprocess failed (%s); return original %s", e, path)
        return path

# ---------- generators ----------

async def _gen_from_text(prompt: str, seconds: float, seed: Optional[int]) -> str:
    loop = asyncio.get_event_loop()
    try:
        path = await loop.run_in_executor(None, _replicate.generate_from_text, prompt, seconds, None, seed)
        log.info("[ui] replicate(text) OK: %s (seed=%s)", path, seed)
        return path
    except Exception as e:
        log.warning("[ui] replicate(text) failed: %s; fallback offline(text)", e)
        return await loop.run_in_executor(None, _offline.generate, prompt, int(seconds))

async def _gen_from_image(img_path: str, prompt: str, seconds: float, seed: Optional[int]) -> str:
    loop = asyncio.get_event_loop()
    try:
        path = await loop.run_in_executor(None, _replicate.generate_from_image, img_path, prompt, seconds, None, seed)
        log.info("[ui] replicate(image) OK: %s (seed=%s)", path, seed)
        return path
    except Exception as e:
        log.warning("[ui] replicate(image) failed: %s; QUICK PREVIEW from same image", e)
        return _quick_preview_from_image(img_path, seconds)

# ---------- UI flows ----------

def _seed_new_variant(last_seed: Optional[int]) -> int:
    # лёгкий jitter вокруг предыдущего, чтобы «похоже, но не копипаста»
    base = last_seed if isinstance(last_seed, int) else random.randint(1, 2_000_000_000)
    jitter = random.randint(-9999, 9999)
    return max(1, (base + jitter) % 2_147_483_647)

async def _preview_paygate(chat_id: int, dur: float, sound: str, message_obj):
    """3 превью бесплатно; дальше — автосписание. Если не хватает — просим пополнить и возвращаем False."""
    snd = 1 if str(sound).lower() == "on" else 0
    ok, cost = register_preview_and_charge(chat_id, dur, snd)
    if ok:
        return True
    # недост. средств
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("💳 Пополнить баланс", callback_data="add_money"))
    await message_obj.answer(f"💰 Баланс недостаточен для превью ({cost} ₽).", reply_markup=kb)
    return False

# ---------- MESSAGE HANDLERS ----------

async def handle_text(message: types.Message, bot_state):
    _ensure_clients()
    _ensure_state(bot_state)

    prompt = (message.text or "").strip()
    if not prompt:
        return await message.answer("Напиши описание сцены.")

    chat_id = message.chat.id
    ensure_user(chat_id)
    _set_last_prompt(bot_state, chat_id, prompt)
    _get_box(bot_state, "last_image").pop(chat_id, None)

    p = _get_prefs(bot_state, chat_id)
    seconds = float(p["dur"])
    sound = p["sound"]

    if not await _preview_paygate(chat_id, seconds, sound, message):
        return

    await message.answer("🛠 Генерирую превью…")
    seed = _seed_new_variant(_get_last_seed(bot_state, chat_id))
    path = await _gen_from_text(prompt, seconds, seed)
    path = _apply_postprocess(path, seconds, sound)

    _set_last_seed(bot_state, chat_id, seed)
    _set_last_preview(bot_state, chat_id, path)
    with open(path, "rb") as f:
        await message.answer_video(f, caption="✅ Готово. Предпросмотр:", reply_markup=kb_ready())

async def handle_photo(message: types.Message, bot_state):
    _ensure_clients()
    _ensure_state(bot_state)

    if not ENABLE_UPLOAD:
        return await message.answer("Загрузка по фото временно отключена.", reply_markup=kb_ready())

    caption = _cinema_prompt(message.caption or "")
    chat_id = message.chat.id
    ensure_user(chat_id)
    _set_last_prompt(bot_state, chat_id, caption or "сделай видео по фото")

    p = _get_prefs(bot_state, chat_id)
    seconds = float(p["dur"])
    sound = p["sound"]

    if not await _preview_paygate(chat_id, seconds, sound, message):
        return

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
        seed = _seed_new_variant(_get_last_seed(bot_state, chat_id))
        path = await _gen_from_image(jpath, caption or "", seconds, seed)
        _set_last_seed(bot_state, chat_id, seed)
        _set_last_image(bot_state, chat_id, jpath)
    except Exception as e:
        log.warning("[ui] photo flow failed hard: %s — QUICK PREVIEW from same photo if possible", e)
        if jpath:
            path = _quick_preview_from_image(jpath, seconds)
        else:
            path = _quick_preview_from_image(tmp_path, seconds) if tmp_path else None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except Exception: pass

    if not path:
        return await message.answer("Не удалось обработать фото.")
    path = _apply_postprocess(path, seconds, sound)
    _set_last_preview(bot_state, chat_id, path)
    with open(path, "rb") as f:
        await message.answer_video(f, caption="✅ Готово. Предпросмотр:", reply_markup=kb_ready())

async def handle_video(message: types.Message, bot_state):
    _ensure_clients()
    _ensure_state(bot_state)

    if not ENABLE_UPLOAD:
        return await message.answer("Загрузка по видео временно отключена.", reply_markup=kb_ready())

    caption = _cinema_prompt(message.caption or "")
    chat_id = message.chat.id
    ensure_user(chat_id)
    _set_last_prompt(bot_state, chat_id, caption)
    await message.answer("🛠 Обрабатываю видео…")

    p = _get_prefs(bot_state, chat_id)
    seconds = float(p["dur"])
    sound = p["sound"]

    if not await _preview_paygate(chat_id, seconds, sound, message):
        return

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
        seed = _seed_new_variant(_get_last_seed(bot_state, chat_id))
        path = await _gen_from_image(jpath, caption or "", seconds, seed)
        _set_last_seed(bot_state, chat_id, seed)
    except Exception as e:
        log.warning("[ui] video flow failed: %s — QUICK PREVIEW from same video", e)
        path = _quick_preview_from_video(tmp_video, seconds) if tmp_video else None
    finally:
        if frame_jpg and os.path.exists(frame_jpg):
            try: os.remove(frame_jpg)
            except Exception: pass

    if not path:
        return await message.answer("Не удалось обработать видео.")
    path = _apply_postprocess(path, seconds, sound)
    _set_last_preview(bot_state, chat_id, path)
    with open(path, "rb") as f:
        await message.answer_video(f, caption="✅ Готово. Предпросмотр:", reply_markup=kb_ready())

# ---------- CALLBACKS ----------

async def handle_callback(query: types.CallbackQuery, bot_state):
    _ensure_clients()
    _ensure_state(bot_state)
    data = (query.data or "").strip()
    chat_id = query.message.chat.id if query.message else None

    _ack_cb_sync(query)
    ensure_user(chat_id)

    # Меню настроек
    if data == "menu_config":
        kb = kb_menu_config(bot_state, chat_id)
        await query.message.answer("⚙️ Настройки генерации:", reply_markup=kb)
        return

    # Длительность 7.5
    if data == "dur_set75":
        _set_pref(bot_state, chat_id, "dur", 7.5)
        await query.message.answer("⏱ 7.5 секунд применено.")
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

    # Подсчёт цены
    if data == "calc_price":
        p = _get_prefs(bot_state, chat_id)
        dur = float(p["dur"])
        snd = 1 if p["sound"] == "on" else 0
        cost = price_fn(dur, snd)
        from app.billing import get_balance
        bal = get_balance(chat_id)
        sel = f"Выбрано: {('7.5' if dur>=7.5 else '5')} сек, " + ("со звуком" if snd else "без звука")
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("💳 Пополнить баланс", callback_data="add_money"))
        await query.message.answer(f"{sel}\n💵 Стоимость: {cost} ₽\n💰 Баланс: {bal} ₽", reply_markup=kb)
        return

    if data == "add_money":
        from app.billing import add_balance
        add_balance(chat_id, 200, "Пополнение через кнопку")
        await query.message.answer("✅ Баланс +200 ₽.")
        return

    # Генерации
    if data == "again":
        p = _get_prefs(bot_state, chat_id)
        seconds = float(p["dur"])
        sound = p["sound"]
        if not await _preview_paygate(chat_id, seconds, sound, query.message):
            return

        await query.message.answer("🛠 Генерирую превью…")
        last_img = _get_last_image(bot_state, chat_id)
        prompt = _get_last_prompt(bot_state, chat_id, default="Short daylight scene.")
        seed = _seed_new_variant(_get_last_seed(bot_state, chat_id))
        loop = asyncio.get_event_loop()
        try:
            if last_img and os.path.exists(last_img):
                jpath = _reencode_to_jpeg(last_img)
                path = await _gen_from_image(jpath, prompt, seconds, seed)
                log.info("[ui] again(photo) OK: %s (seed=%s)", path, seed)
            else:
                path = await _gen_from_text(prompt, seconds, seed)
                log.info("[ui] again(text) OK: %s (seed=%s)", path, seed)
        except Exception as e:
            log.warning("[ui] again failed: %s — QUICK PREVIEW", e)
            path = _quick_preview_from_image(last_img, seconds) if last_img else None

        if not path:
            return
        _set_last_seed(bot_state, chat_id, seed)
        path = _apply_postprocess(path, seconds, sound)
        _set_last_preview(bot_state, chat_id, path)
        with open(path, "rb") as f:
            await query.message.answer_video(f, caption="✅ Готово. Предпросмотр:", reply_markup=kb_ready())
        return

    if data == "sora2_go":
        await query.message.answer("🧩 Генерирую SORA 2…")
        p = _get_prefs(bot_state, chat_id)
        seconds = float(p["dur"])
        sound = p["sound"]
        prompt = _get_last_prompt(bot_state, chat_id, default="Short daylight scene.")
        seed = _get_last_seed(bot_state, chat_id) or 123456

        last_video = _get_last_video(bot_state, chat_id)
        last_img = _get_last_image(bot_state, chat_id)
        last_prev = _get_last_preview(bot_state, chat_id)

        try:
            if last_video and os.path.exists(last_video):
                frame = str(Path(last_video).with_suffix(".jpg"))
                if not _try_ffmpeg_frame(last_video, frame):
                    raise RuntimeError("sora2: frame from last_video failed")
                jpath = _reencode_to_jpeg(frame)
                path = await _gen_from_image(jpath, prompt, seconds, seed)
                log.info("[ui] sora2(video->frame) OK: %s (seed=%s)", path, seed)
            elif last_img and os.path.exists(last_img):
                jpath = _reencode_to_jpeg(last_img)
                path = await _gen_from_image(jpath, prompt, seconds, seed)
                log.info("[ui] sora2(photo) OK: %s (seed=%s)", path, seed)
            elif last_prev and os.path.exists(last_prev):
                frame = str(Path(last_prev).with_suffix(".jpg"))
                if not _try_ffmpeg_frame(last_prev, frame):
                    raise RuntimeError("sora2: frame from last_preview failed")
                jpath = _reencode_to_jpeg(frame)
                path = await _gen_from_image(jpath, prompt, seconds, seed)
                log.info("[ui] sora2(prev->frame) OK: %s (seed=%s)", path, seed)
            else:
                # если совсем нечего зафиксировать — рендерим текст по последнему prompt, но с фиксированным seed
                path = await _gen_from_text(prompt, seconds, seed)
                log.info("[ui] sora2(text) OK: %s (seed=%s)", path, seed)
        except Exception as e:
            log.warning("[ui] sora2 failed: %s — фиксированный QUICK PREVIEW", e)
            if last_img and os.path.exists(last_img):
                path = _quick_preview_from_image(last_img, seconds)
            elif last_prev and os.path.exists(last_prev):
                path = _quick_preview_from_video(last_prev, seconds)
            elif last_video and os.path.exists(last_video):
                path = _quick_preview_from_video(last_video, seconds)
            else:
                # до последнего — текст offline
                loop = asyncio.get_event_loop()
                path = await loop.run_in_executor(None, _offline.generate, prompt, int(seconds))

        path = _apply_postprocess(path, seconds, sound)
        _set_last_seed(bot_state, chat_id, seed)  # фиксируем seed SORA2
        _set_last_preview(bot_state, chat_id, path)
        with open(path, "rb") as f:
            await query.message.answer_video(f, caption="✅ Готово. Предпросмотр:", reply_markup=kb_ready())
        return

    if data == "photo_help":
        await query.message.answer("Пришли фото (или документ с картинкой) и подпись — сделаю ролик.")
        return

    if data == "video_help":
        await query.message.answer("Пришли короткое видео и подпись — сделаю ролик.")
        return
