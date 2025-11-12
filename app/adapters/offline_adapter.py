import subprocess, tempfile, time, textwrap, shlex, asyncio
from pathlib import Path

def _run(args):
    if isinstance(args, str):
        import shlex as _sh
        args = _sh.split(args)
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def _has(prompt: str, keywords: list[str]) -> bool:
    p = (prompt or "").lower()
    return any(k in p for k in keywords)

def _make_sfx(prompt: str, duration: int, out_wav: Path):
    prof = "base"
    if _has(prompt, ["море", "волна", "волны", "прибой", "пляж", "sea", "ocean"]):
        prof = "sea"
    elif _has(prompt, ["ветер", "сквозняк", "буря", "wind", "storm"]):
        prof = "wind"
    elif _has(prompt, ["камин", "огонь", " fireplace", "fire"]):
        prof = "fire"

    if prof == "sea":
        af = "lowpass=f=900, tremolo=f=5:d=0.6, volume=0.28"
    elif prof == "wind":
        af = "bandpass=f=1000:w=800, volume=0.30"
    elif prof == "fire":
        af = "highpass=f=1200, tremolo=f=2:d=0.8, volume=0.24"
    else:
        af = "volume=0.18"

    _run([
        "ffmpeg","-y",
        "-f","lavfi","-i","anoisesrc=a=0.002:color=pink:r=48000",
        "-t",str(duration),
        "-af",af,
        str(out_wav)
    ])

class OfflineClient:
    """
    Офлайн-предпросмотр:
    — фон 1280×720 с текстом,
    — TTS (espeak-ng, если установлен) + SFX,
    — mp4 (x264 + AAC).
    """
    def __init__(self, out_dir: str):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, prompt: str, duration: int = 5, size: str = "1280x720") -> str:
        tmp = Path(tempfile.mkdtemp(prefix="offline_"))
        out_path = self.out_dir / f"offline_{int(time.time())}.mp4"
        tts = tmp / "tts.wav"
        sfx = tmp / "sfx.wav"
        mix = tmp / "mix.wav"
        bg  = tmp / "bg.mp4"

        safe_text = textwrap.fill((prompt or "")[:180], width=38).replace("'", r"\'")
        draw = (
            "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:"
            f"text='{safe_text}':fontcolor=white:fontsize=30:x=(w-text_w)/2:y=(h-text_h)/2"
        )

        _run([
            "ffmpeg","-y",
            "-f","lavfi","-i",f"color=c=#202428:size={size}:rate=30",
            "-t",str(duration),
            "-vf", draw,
            "-c:v","libx264","-pix_fmt","yuv420p","-preset","veryfast","-crf","23",
            str(bg)
        ])

        try:
            _run(f"espeak-ng -v {shlex.quote('ru')} -s 145 -w {tts} {shlex.quote(prompt or 'Предпросмотр сцены')}")
        except Exception:
            _run(["ffmpeg","-y","-f","lavfi","-i","anullsrc=r=48000:cl=mono","-t",str(duration),str(tts)])

        _make_sfx(prompt or "", duration, sfx)

        _run([
            "ffmpeg","-y",
            "-i",str(tts), "-i",str(sfx),
            "-filter_complex","[0:a]volume=1.0[a0];[1:a]volume=1.0[a1];[a0][a1]amix=inputs=2:normalize=0",
            "-t",str(duration),
            str(mix)
        ])

        _run(["ffmpeg","-y","-i",str(bg),"-i",str(mix), "-c:v","copy","-c:a","aac","-shortest", str(out_path)])
        return str(out_path)

    async def generate_video(self, prompt: str, seconds: int = 5, size: str = "1280x720"):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.generate, prompt, seconds, size)
