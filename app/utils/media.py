import os,ffmpeg
def upscale_4k(src_path,out_dir,crf=22,preset="veryfast",audio_bitrate="128k"):
    if not os.path.isfile(src_path):
        raise FileNotFoundError("Source not found: "+str(src_path))
    os.makedirs(out_dir,exist_ok=True)
    base = os.path.splitext(os.path.basename(src_path))[0]
    dst = os.path.join(out_dir,base+"_4k.mp4")
    vf = "scale=w=3840:h=2160:flags=lanczos"
    inp = ffmpeg.input(src_path)
    (ffmpeg
      .output(inp.video, inp.audio if audio_bitrate else None, dst, vf=vf,
              vcodec="libx264",crf=crf,preset=preset,
              acodec="aac" if audio_bitrate else None,
              audio_bitrate=audio_bitrate if audio_bitrate else None,
              movflags="+faststart")
      .overwrite_output()
      .run(quiet=True))
    return dst
