import subprocess, tempfile

def ensure_audio(video_path: str) -> str:
    out = tempfile.NamedTemporaryFile(prefix="aud_", suffix=".mp4", delete=False).name
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-f", "lavfi", "-t", "600", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        out
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out
