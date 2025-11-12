#!/usr/bin/env python3
import os, sys, subprocess, tempfile, uuid, shutil
from pathlib import Path
from typing import Optional
from PIL import Image

OUT_DIR = Path(os.environ.get("OUT_DIR", "/opt/content_factory/out"))
ASSETS_MUSIC = Path("/opt/content_factory/assets/music")
ASSETS_OVER = Path("/opt/content_factory/assets/overlays")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(cmd)}\n{p.stdout}")

def ensure_image_1080p(src_path: str) -> str:
    """Подготовка кадра под 16:9, 1080p. Делаем letterbox без растяжения."""
    im = Image.open(src_path).convert("RGB")
    W, H = 1920, 1080
    # вписываем по меньшей стороне
    im_ratio = im.width / im.height
    frame_ratio = W / H

    if im_ratio > frame_ratio:
        # ширина ограничивает
        new_w = W
        new_h = int(W / im_ratio)
    else:
        new_h = H
        new_w = int(H * im_ratio)

    im_resized = im.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGB", (W, H), (0, 0, 0))
    canvas.paste(im_resized, ((W - new_w)//2, (H - new_h)//2))
    tmp = Path(tempfile.gettempdir()) / f"pex_{uuid.uuid4().hex}_base.jpg"
    canvas.save(tmp, quality=95)
    return str(tmp)

def build_zoompan_shot(img_path: str, out_mp4: str, duration: int, mode: str) -> None:
    """
    Три простых «кинодвижения» без depth:
      - mode=a: лёгкий dolly-in
      - mode=b: pan вправо
      - mode=c: pan влево + micro-zoom
    """
    fps = 30
    n = duration * fps
    if mode == "a":
        # плавный наезд
        # zoom от 1.00 до 1.08
        expr = "zoom=1+0.000266*on, x=(iw-iw/zoom)/2, y=(ih-ih/zoom)/2"
    elif mode == "b":
        # панорама вправо
        expr = "zoom=1.03, x=on*0.25, y=(ih-ih/zoom)/2"
    else:
        # панорама влево + микро-zoom
        expr = "zoom=1.04, x=(iw-iw/zoom)-on*0.25, y=(ih-ih/zoom)/2"

    # лёгкая «кинокоррекция»: виньетка + мягкий контраст
    vf = (
        f"zoompan={expr}:d=1:fps={fps},"
        f"eq=contrast=1.06:gamma=1.02:saturation=1.05,"
        f"vignette=PI/7"
    )

    run([
        "ffmpeg", "-y",
        "-loop", "1", "-t", str(duration),
        "-i", img_path,
        "-vf", vf,
        "-r", str(fps),
        "-pix_fmt", "yuv420p",
        "-an", out_mp4
    ])

def concat_with_xfade(mp4_list: list[str], out_mp4: str) -> None:
    """
    Склеиваем три шота через xfade (smooth), чтобы смотрелось как режиссура.
    """
    assert len(mp4_list) >= 2
    # Приведём все к одинаковому аудиотракту (пустой), чтобы xfade не ругался.
    fixed = []
    for p in mp4_list:
        q = p.replace(".mp4", "_fix.mp4")
        run(["ffmpeg", "-y", "-i", p, "-c:v", "copy", "-f", "lavfi", "-t", "0.1", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
             "-shortest", "-c:a", "aac", q])
        fixed.append(q)

    # первый переход
    mid1 = fixed[0].replace(".mp4", "_xf1.mp4")
    run([
        "ffmpeg", "-y",
        "-i", fixed[0], "-i", fixed[1],
        "-filter_complex", "xfade=transition=smooth:duration=0.6:offset=4.4",
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
        "-c:a", "aac", mid1
    ])

    final_src = mid1
    if len(fixed) >= 3:
        # второй переход
        mid2 = fixed[2]
        out2 = fixed[0].replace(".mp4", "_xf2.mp4")
        run([
            "ffmpeg", "-y",
            "-i", final_src, "-i", mid2,
            "-filter_complex", "xfade=transition=smooth:duration=0.6:offset=8.8",
            "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
            "-c:a", "aac", out2
        ])
        final_src = out2

    shutil.move(final_src, out_mp4)

def add_audio_mix(src_mp4: str, tts_wav: Optional[str], out_mp4: str) -> None:
    """
    Микс звука: TTS (если есть) + фоновая музыка (если есть).
    Громкость музыки тише, чтобы не перебивала голос.
    """
    music = None
    for cand in ["bg1.mp3", "bg.mp3", "music.mp3"]:
        p = ASSETS_MUSIC / cand
        if p.exists():
            music = str(p); break

    # Без звука — просто копия
    if not tts_wav and not music:
        shutil.copy(src_mp4, out_mp4)
        return

    # Собираем filter_complex под разные случаи
    inputs = ["-i", src_mp4]
    fc_parts = []
    amix_label = ""
    maps = ["-map", "0:v:0"]
    idx = 1

    if tts_wav:
        inputs += ["-i", tts_wav]
        fc_parts.append(f"[{idx}:a]volume=1.0[a1]")
        idx += 1
        amix_label += "[a1]"
    if music:
        inputs += ["-i", music]
        fc_parts.append(f"[{idx}:a]volume=0.25,aloop=loop=-1:size=2e+09[a2]")
        idx += 1
        amix_label += "[a2]"

    if amix_label:
        fc_parts.append(f"{amix_label}amix=inputs={len(amix_label)//4}:duration=first,aresample=48000[aout]")  # каждая пометка вида [aX] = 4 символа
        maps += ["-map", "[aout]"]

    filter_complex = ";".join(fc_parts) if fc_parts else None
    cmd = ["ffmpeg", "-y"] + inputs
    if filter_complex:
        cmd += ["-filter_complex", filter_complex]
    cmd += ["-c:v", "copy", "-c:a", "aac", "-shortest", out_mp4]
    run(cmd)

def maybe_build_tts(tts_text: Optional[str]) -> Optional[str]:
    """
    Если установлен piper — озвучим. Иначе вернём None.
    piper ставится отдельно: бинарь piper + модель ru.
    """
    if not tts_text:
        return None
    piper = shutil.which("piper")
    model = os.environ.get("PIPER_MODEL")  # напр. /opt/piper/ru_RU-dmitry-medium.onnx
    if not piper or not model or not Path(model).exists():
        return None
    out = Path(tempfile.gettempdir()) / f"pex_{uuid.uuid4().hex}_tts.wav"
    run([piper, "-m", model, "-f", str(out), "-q", "--text", tts_text])
    return str(out)

def main():
    if len(sys.argv) < 3:
        print("usage: product_exact.py <image_path> <duration_sec> [tts_text]")
        sys.exit(2)
    img_in = sys.argv[1]
    duration = int(sys.argv[2])  # 5/10/15
    tts = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else None

    base = ensure_image_1080p(img_in)
    # делим 15 сек на три по 5; для 5/10 — корректируем:
    if duration <= 5:
        parts = [duration]
    elif duration <= 10:
        parts = [5, duration - 5]
    else:
        parts = [5, 5, duration - 10]

    tmpdir = Path(tempfile.mkdtemp(prefix="pex_"))
    shots = []
    modes = ["a", "b", "c"]
    for i, d in enumerate(parts):
        out = tmpdir / f"shot{i}.mp4"
        build_zoompan_shot(base, str(out), d, modes[i % len(modes)])
        shots.append(str(out))

    merged = tmpdir / "merged.mp4"
    if len(shots) == 1:
        shutil.copy(shots[0], merged)
    else:
        concat_with_xfade(shots, str(merged))

    tts_wav = maybe_build_tts(tts)
    out_path = OUT_DIR / f"product_exact_{uuid.uuid4().hex}_{duration}s.mp4"
    add_audio_mix(str(merged), tts_wav, str(out_path))
    print(str(out_path))

if __name__ == "__main__":
    main()
