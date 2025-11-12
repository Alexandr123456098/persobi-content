import os, re, time, asyncio, ffmpeg

class OfflineClient:
    def __init__(self, out_dir=None):
        self.out_dir = out_dir or os.getenv("OUT_DIR", "/opt/content_factory/out")
        os.makedirs(self.out_dir, exist_ok=True)

    async def generate_video(self, prompt, seconds=5, width=1280, height=720, fps=30):
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(prompt)).strip("_")[:40] or "clip"
        dst = os.path.join(self.out_dir, "offline_%d_%s.mp4" % (int(time.time()), safe))

        def _run():
            color = "color=black:s=%dx%d:d=%d" % (width, height, seconds)
            v = ffmpeg.input(color, f="lavfi", r=fps)
            a = ffmpeg.input("anullsrc=r=48000:cl=stereo", f="lavfi")
            (ffmpeg
                .output(
                    v, a, dst,
                    vcodec="libx264", preset="veryfast", crf=23, pix_fmt="yuv420p",
                    acodec="aac", audio_bitrate="128k", movflags="+faststart"
                )
                .overwrite_output()
                .run(quiet=True))
            return dst

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _run)
