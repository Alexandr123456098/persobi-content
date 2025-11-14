# -*- coding: utf-8 -*-
import os, sys, json, shlex, time, subprocess, uuid
from pathlib import Path
from typing import Dict, Any, Optional, List

API_BASE = "https://api.replicate.com/v1"
T2V_MODEL = os.environ.get("REPLICATE_MODEL_T2V", "wan-video/wan-2.2-t2v-fast")
I2V_MODEL = os.environ.get("REPLICATE_MODEL_I2V", "wan-video/wan-2.2-i2v-fast")

ROOT = Path("/opt/content_factory")
OUT_DIR = Path(os.environ.get("OUT_DIR", str(ROOT / "out")))
PRED_DIR = OUT_DIR / "predictions"
OUT_DIR.mkdir(parents=True, exist_ok=True)
PRED_DIR.mkdir(parents=True, exist_ok=True)

ENV_PATH = ROOT / ".env"
DEFAULT_SECONDS = float(os.environ.get("DEFAULT_DURATION", "5"))
DEFAULT_FPS = int(os.environ.get("REPLICATE_FPS", "16"))
MAX_FRAMES_HARD = 100  # Wan 2.2: num_frames 81–100

WARMUP_SEC = float(os.environ.get("REPLICATE_WARMUP_SEC", "0.5"))
FIXED_SEED = int(os.environ.get("REPLICATE_FIXED_SEED", "123456789"))

PROMPT_PRIMER = (
    "Start immediately with a sharp, fully resolved photorealistic frame. "
    "No painterly intro or plastic placeholder. Cinematic, stable exposure, no glitches. "
)


class ReplicateError(RuntimeError):
    pass


def _run(cmd: str, stdin: Optional[bytes] = None, check=True) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, input=stdin, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode != 0:
        raise RuntimeError(f"Command failed [{p.returncode}]: {cmd}\nSTDERR:\n{p.stderr.decode(errors='ignore')}")
    return p


def _parse_dotenv_token(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        for line in path.read_text().splitlines():
            if line.strip().startswith("REPLICATE_API_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        return ""
    return ""


def _looks_like_path(s: str) -> bool:
    s = s.strip()
    return s.startswith("/") or s.startswith("./") or s.startswith("../")


def _ensure_token() -> str:
    tok = os.environ.get("REPLICATE_API_TOKEN", "").strip()
    if not tok:
        tok = _parse_dotenv_token(ENV_PATH).strip()
    if (not tok) or _looks_like_path(tok) or len(tok) < 20:
        raise ReplicateError("REPLICATE_API_TOKEN invalid or missing")
    return tok


def _curl_json(method: str, url: str, headers: Dict[str, str], body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    hdr = " ".join([f"-H {shlex.quote(f'{k}: {v}')}" for k, v in headers.items()])
    data = f"-d {shlex.quote(json.dumps(body))}" if body else ""
    cmd = f"curl -fsS -X {method} {hdr} {data} {shlex.quote(url)}"
    p = _run(cmd, check=True)
    try:
        return json.loads(p.stdout.decode())
    except Exception as e:
        raise ReplicateError(f"Bad JSON from {url}: {e}\nRAW:\n{p.stdout.decode(errors='ignore')}")


def _post_json(url: str, js: Dict[str, Any], tok: str) -> Dict[str, Any]:
    return _curl_json("POST", url, {"Authorization": f"Token {tok}", "Content-Type": "application/json"}, js)


def _get_json(url: str, tok: str) -> Dict[str, Any]:
    return _curl_json("GET", url, {"Authorization": f"Token {tok}"})


def _download(url: str, dst: Path):
    _run(f"curl -fsSL --retry 3 -o {shlex.quote(str(dst))} {shlex.quote(url)}", check=True)


def _upload_catbox(local_path: Path) -> str:
    out = _run(
        f"curl -fsS -F 'reqtype=fileupload' -F 'fileToUpload=@{shlex.quote(str(local_path))}' https://catbox.moe/user/api.php",
        check=True,
    ).stdout.decode().strip()
    if not out.startswith("http"):
        raise ReplicateError(f"catbox upload failed: {out}")
    return out


def _quantize_frames(n: int) -> int:
    """
    Квантуем количество кадров в допустимый для Wan 2.2 диапазон.
    Wan 2.2: num_frames ∈ [81, 100].
    """
    safe = [100, 96, 92, 88, 84, 81]
    n = max(1, min(n, MAX_FRAMES_HARD))
    for s in safe:
        if s <= n:
            return s
    return 81


def _calc_frames(sec: float, fps: int) -> int:
    n = int(round(float(sec) * fps))
    n = max(1, min(n, MAX_FRAMES_HARD))
    return _quantize_frames(n)


def _log_json(js: Dict[str, Any]):
    try:
        fname = PRED_DIR / f"{uuid.uuid4().hex[:10]}.json"
        fname.write_text(json.dumps(js, ensure_ascii=False, indent=2))
    except Exception:
        pass


def _is_422(err: Exception) -> bool:
    s = str(err)
    return " 422" in s or "HTTP 422" in s or "error: 422" in s or "422\n" in s


def _predict_with_sla(model: str, base_payload: Dict[str, Any], tok: str) -> str:
    """
    SLA-логика: теперь перебираем только допустимые варианты Wan 2.2:
    num_frames ∈ [81, 100], fps ∈ [5, 24].
    """
    attempts: List[Dict[str, Any]] = []

    start_fps = int(base_payload.get("frames_per_second", DEFAULT_FPS))
    start_fps = max(5, min(start_fps, 24))

    start_nf = int(base_payload.get("num_frames", _calc_frames(DEFAULT_SECONDS, start_fps)))
    start_nf = max(81, min(start_nf, MAX_FRAMES_HARD))

    fps_order: List[int] = []
    for f in [start_fps, 24, 20, 16, 12, 8]:
        f = max(5, min(int(f), 24))
        if f not in fps_order:
            fps_order.append(f)

    frame_master = [100, 96, 92, 88, 84, 81]

    variants: List[Dict[str, int]] = []
    for i, fps in enumerate(fps_order):
        if i == 0:
            start_q = _quantize_frames(start_nf)
            ladder = [x for x in frame_master if x <= start_q]
            if start_q not in ladder:
                ladder = [start_q] + ladder
        else:
            ladder = [x for x in frame_master if x <= _calc_frames(DEFAULT_SECONDS, fps)]
        for nf in ladder:
            nf_clamped = max(81, min(int(nf), MAX_FRAMES_HARD))
            variants.append({"fps": int(fps), "nf": nf_clamped})

    for var in variants:
        payload = dict(base_payload)
        payload["frames_per_second"] = int(var["fps"])
        payload["num_frames"] = int(var["nf"])

        for net_try in range(1, 3 + 1):
            try:
                r = _post_json(f"{API_BASE}/models/{model}/predictions", {"input": payload}, tok)
                get_url = (r.get("urls") or {}).get("get", "")
                if not get_url:
                    raise RuntimeError("No urls.get in create response")

                while True:
                    s = _get_json(get_url, tok)
                    st = s.get("status")
                    if st == "succeeded":
                        out = s.get("output")
                        url = out[-1] if isinstance(out, list) and out else (out if isinstance(out, str) else "")
                        if not url:
                            raise RuntimeError("No output url")
                        _log_json(
                            {
                                "ok": True,
                                "model": model,
                                "payload": payload,
                                "variant": var,
                                "url": url,
                                "ts": time.time(),
                            }
                        )
                        return url
                    if st == "failed":
                        attempts.append({"variant": var, "net_try": net_try, "status": "failed"})
                        break
                    time.sleep(1.5)
            except Exception as e:
                if net_try < 3:
                    _log_json({"retry": True, "variant": var, "error": str(e), "ts": time.time()})
                    time.sleep(0.8)
                    continue
                if _is_422(e) or "validation" in str(e).lower():
                    attempts.append({"variant": var, "net_try": net_try, "status": "422"})
                    break
                attempts.append({"variant": var, "net_try": net_try, "status": "error", "error": str(e)})
                break

    _log_json({"ok": False, "model": model, "base_payload": base_payload, "attempts": attempts, "ts": time.time()})
    raise ReplicateError("SLA: exhausted variants")


def _ffmpeg_trim(src: Path, fps: int, seconds: float, warm_frames: int) -> Path:
    ss = warm_frames / max(1, fps)
    out = src.with_suffix(".trim.mp4")
    cmd = (
        f"ffmpeg -y -ss {ss:.2f} -i {shlex.quote(str(src))} "
        f"-t {float(seconds):.2f} -an -c:v libx264 -preset veryfast -crf 18 "
        f"-pix_fmt yuv420p -movflags +faststart {shlex.quote(str(out))}"
    )
    _run(cmd, check=True)
    return out


def _ffmpeg_norm(src: Path, fps: int) -> Path:
    out = src.with_suffix(".final.mp4")
    vf = "scale=-2:720:flags=lanczos"
    cmd = (
        f"ffmpeg -y -i {shlex.quote(str(src))} -vf {shlex.quote(vf)} -r {int(fps)} "
        f"-c:v libx264 -preset veryfast -movflags +faststart {shlex.quote(str(out))}"
    )
    _run(cmd, check=True)
    return out


class ReplicateClient:
    def __init__(self, token: Optional[str] = None):
        self.token = token or _ensure_token()

    def _finalize(self, downloaded_path: Path, prefix: str, fps: int, seconds: float, warm_frames: int) -> Path:
        trimmed = _ffmpeg_trim(downloaded_path, fps=fps, seconds=seconds, warm_frames=warm_frames)
        normalized = _ffmpeg_norm(trimmed, fps=fps)
        final = OUT_DIR / f"{prefix}_{int(time.time())}.mp4"
        normalized.rename(final)
        return final

    def generate_from_text(
        self,
        prompt: str,
        seconds: float = DEFAULT_SECONDS,
        fps: Optional[int] = None,
        seed: Optional[int] = None,
    ) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ReplicateError("prompt is required")
        fps = int(fps or DEFAULT_FPS)
        fps = max(5, min(fps, 24))

        warm_frames = max(1, round(WARMUP_SEC * fps))
        total_frames = min(MAX_FRAMES_HARD, _calc_frames(seconds, fps) + warm_frames)

        payload = {
            "prompt": f"{PROMPT_PRIMER}{prompt}",
            "num_frames": total_frames,
            "frames_per_second": fps,
            "seed": int(seed if seed is not None else FIXED_SEED),
        }

        url = _predict_with_sla(T2V_MODEL, payload, self.token)
        tmp = OUT_DIR / f"replicate_t2v_{int(time.time())}.dl.tmp.mp4"
        _download(url, tmp)
        final_path = self._finalize(tmp, "replicate_wanA_t2v", fps=fps, seconds=seconds, warm_frames=warm_frames)
        return str(final_path)

    def generate_from_image(
        self,
        image: str,
        prompt: str = "",
        seconds: float = DEFAULT_SECONDS,
        fps: Optional[int] = None,
        seed: Optional[int] = None,
        strength: Optional[float] = None,
        denoise: Optional[float] = None,
    ) -> str:
        fps = int(fps or DEFAULT_FPS)
        fps = max(5, min(fps, 24))

        warm_frames = max(1, round(WARMUP_SEC * fps))
        total_frames = min(MAX_FRAMES_HARD, _calc_frames(seconds, fps) + warm_frames)

        if image.lower().startswith("http://") or image.lower().startswith("https://"):
            img_url = image
        else:
            p = Path(image)
            if not p.exists():
                raise ReplicateError(f"Image not found: {image}")
            img_url = _upload_catbox(p)

        payload = {
            "image": img_url,
            "prompt": f"{PROMPT_PRIMER}{prompt}",
            "num_frames": total_frames,
            "frames_per_second": fps,
            "seed": int(seed if seed is not None else FIXED_SEED),
            "strength": float(strength if strength is not None else os.getenv("REPLICATE_I2V_STRENGTH", "0.55")),
            "denoise": float(denoise if denoise is not None else os.getenv("REPLICATE_I2V_DENOISE", "0.35")),
        }

        url = _predict_with_sla(I2V_MODEL, payload, self.token)
        tmp = OUT_DIR / f"replicate_i2v_{int(time.time())}.dl.tmp.mp4"
        _download(url, tmp)
        final_path = self._finalize(tmp, "replicate_wanA_i2v", fps=fps, seconds=seconds, warm_frames=warm_frames)
        return str(final_path)

    # back-compat
    def text(self, prompt: str) -> str:
        return self.generate_from_text(prompt)

    def image(self, image: str, prompt: str = "") -> str:
        return self.generate_from_image(image, prompt)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--mode", required=True, choices=["text", "image"])
    p.add_argument("--prompt", default="A cinematic shot, soft light")
    p.add_argument("--image", default="")
    p.add_argument("--seconds", type=float, default=DEFAULT_SECONDS)
    p.add_argument("--fps", type=int, default=DEFAULT_FPS)
    p.add_argument("--seed", type=int, default=None)
    a = p.parse_args()

    rc = ReplicateClient()
    try:
        if a.mode == "text":
            out_path = rc.generate_from_text(a.prompt, seconds=a.seconds, fps=a.fps, seed=a.seed)
        else:
            if not a.image:
                raise ReplicateError("--image required for mode=image")
            out_path = rc.generate_from_image(a.image, a.prompt or "", seconds=a.seconds, fps=a.fps, seed=a.seed)
        print(json.dumps({"path": out_path}, ensure_ascii=False))
    except Exception as e:
        sys.stderr.write(str(e) + "\n")
        sys.exit(1)
