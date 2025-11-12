import os, subprocess, tempfile, random, string, shlex, textwrap

def _rand(n=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def _sanitize_text(t: str, limit=450):
    t = ' '.join(t.split())
    t = t.replace(":", "\\:").replace(",", "\\,")
    if len(t) > limit:
        t = t[:limit-3] + "..."
    return t

def render_many(prompt: str, count: int = 1, out_dir: str | None = None,
                fps: int = 24, duration: int = 6, size: str = "1280x720") -> list[str]:
    """
    Генерит count mp4-заглушек с текстом prompt.
    out_dir — папка сохранения (по умолчанию $OUT_DIR или /opt/content_factory/out)
    """
    if out_dir is None:
        out_dir = os.getenv("OUT_DIR", "/opt/content_factory/out")
    os.makedirs(out_dir, exist_ok=True)

    txt = _sanitize_text(prompt)
    paths: list[str] = []
    for _ in range(int(count)):
        fname = f"cf_{_rand(9)}.mp4"
        path = os.path.join(out_dir, fname)
        # drawtext требует установленный шрифт dejavu; у нас он стоит
        draw = (
            "drawbox=x=0:y=0:w=iw:h=ih:color=black@1:t=fill,"
            f"drawtext=font='DejaVu Sans':text='{txt}':"
            "fontcolor=white:fontsize=36:x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.0"
        )
        cmd = [
            "ffmpeg","-y",
            "-f","lavfi","-i",f"color=c=black:s={size}:d={duration}",
            "-vf", draw, "-r", str(fps), "-pix_fmt","yuv420p", path
        ]
        # запустим и не упадём, даже если ffmpeg что-то ворчит на stderr
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        paths.append(path)
    return paths
