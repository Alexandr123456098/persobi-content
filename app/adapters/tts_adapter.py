import subprocess, tempfile
from gtts import gTTS

def tts_to_mp3(text: str) -> str:
    mp3 = tempfile.NamedTemporaryFile(prefix="tts_", suffix=".mp3", delete=False)
    gTTS(text=text, lang="ru").save(mp3.name)
    return mp3.name

def voiceover_video(video_path: str, text: str) -> str:
    mp3 = tts_to_mp3(text)
    out = video_path.rsplit(".", 1)[0] + "_vo.mp4"
    cmd = ["ffmpeg","-y","-i",video_path,"-i",mp3,"-c:v","copy","-c:a","aac","-b:a","192k","-shortest",out]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out
