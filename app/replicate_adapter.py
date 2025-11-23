# -*- coding: utf-8 -*-
import os, sys, json, shlex, time, subprocess, uuid, random
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
DEFAULT_FPS = int(os.environ.get("REPLICATE_FPS", "24"))
MAX_FRAMES_HARD = 100  # Wan 2.2: безопасный верх

WARMUP_SEC = float(os.environ.get("REPLICATE_WARMUP_SEC", "0.5"))
FIXED_SEED = int(os.environ.get("REPLICATE_FIXED_SEED", "123456789"))

PROMPT_PRIMER = (
    "Start immediately with a sharp, fully resolved photorealistic frame from the very first frame. "
    "No fade-in, no drawing animation, no painterly brushstrokes, no plastic placeholder. "
    "Cinematic, stable exposure, no glitches. "
    "Single continuous forward motion from beginning to end. No looping, no ping-pong, no backwards motion, no mirrored repetition. "
)

NEGATIVE_PROMPT = (
    "fairy lights, Christmas lights, garlands, bokeh lights, glowing decorations, "
    "twinkling bulbs, New Year lights, festive lights, tinsel, confetti, fireworks, sparkles, "
    "ёлочные гирлянды, новогодние гирлянды, мигающие огоньки, "
    "reverse, ping-pong, backwards motion, looped segment, mirrored loop, forwards-then-backwards movement, "
    "реверс, обратное движение, зацикленный отрывок, движение туда-сюда, "
    "different person, changed identity, different face, changed clothes, costume, fantasy outfit, "
    "low quality, glitch, distortion, warped face, deformed body"
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
        f"curl -k -fsS -F 'reqtype=fileupload' -F 'fileToUpload=@{shlex.quote(str(local_path))}' https://catbox.moe/user/api.php",
        check=True,
    ).stdout.decode().strip()
    if not out.startswith("http"):
        raise ReplicateError(f"catbox upload failed: {out}")
    return out


def _quantize_frames(n: int) -> int:
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


def _make_seed(seed: Optional[int]) -> int:
    if seed is not None:
        return int(seed)
    base = int(time.time() * 1000) ^ random.randint(0, 2_147_483_647)
    return base % 2_147_483_647 or FIXED_SEED


def _predict_with_sla(model: str, base_payload: Dict[str, Any], tok: str) -> str:
    """
    Упрощённый предикт без лестниц fps/кадров.
    Делаем до 3 сетевых попыток с теми же параметрами.
    """
    attempts: List[Dict[str, Any]] = []
    payload = dict(base_payload)

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
                            "url": url,
                            "ts": time.time(),
                        }
                    )
                    return url
                if st == "failed":
                    attempts.append({"net_try": net_try, "status": "failed"})
                    break
                time.sleep(1.5)
        except Exception as e:
            if net_try < 3:
                _log_json({"retry": True, "error": str(e), "ts": time.time()})
                time.sleep(0.8)
                continue
            if _is_422(e) or "validation" in str(e).lower():
                attempts.append({"net_try": net_try, "status": "422", "error": str(e)})
                break
            attempts.append({"net_try": net_try, "status": "error", "error": str(e)})
            break

    _log_json({"ok": False, "model": model, "base_payload": base_payload, "attempts": attempts, "ts": time.time()})
    raise ReplicateError("provider overloaded or unavailable")


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

    def _finalize(self, downloaded_path: Path, prefix: str, fps: int) -> Path:
        normalized = _ffmpeg_norm(downloaded_path, fps=fps)
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

        # Честные длительности:
        #   5 секунд  => 100 кадров @ 20 fps
        #   10 секунд => 100 кадров @ 10 fps
        if float(seconds) >= 9.0:
            fps = 10
            total_frames = 100
        else:
            fps = 20
            total_frames = 100

        fps = int(fps)
        fps = max(5, min(fps, 24))

        use_seed = _make_seed(seed)

        payload = {
            "prompt": f"{PROMPT_PRIMER}{prompt}",
            "negative_prompt": NEGATIVE_PROMPT,
            "num_frames": int(total_frames),
            "frames_per_second": int(fps),
            "seed": int(use_seed),
        }

        tok = self.token
        url = _predict_with_sla(T2V_MODEL, payload, tok)
        tmp = OUT_DIR / f"replicate_t2v_{int(time.time())}.dl.tmp.mp4"
        _download(url, tmp)
        final_path = self._finalize(tmp, "replicate_wanA_t2v", fps=fps)
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
        # Те же правила длительности, что и для текста:
        #   5 секунд  => 100 кадров @ 20 fps
        #   10 секунд => 100 кадров @ 10 fps
        if float(seconds) >= 9.0:
            fps = 10
            total_frames = 100
        else:
            fps = 20
            total_frames = 100

        fps = int(fps)
        fps = max(5, min(fps, 24))

        use_seed = _make_seed(seed)

        if image.lower().startswith("http://") or image.lower().startswith("https://"):
            img_url = image
        else:
            p = Path(image)
            if not p.exists():
                raise ReplicateError(f"Image not found: {image}")
            img_url = _upload_catbox(p)

        full_prompt = (
            f"{PROMPT_PRIMER}{prompt}".strip()
            + " Use the input image as the strict reference and base. Keep exactly the same main person, face, body, outfit, background and lighting as in the input image. "
            + "The resulting video must clearly show that it is the same person and the same jacket or clothing from the input image, only modified exactly as described in the prompt (for example, the jacket removed from the body and visible nearby). "
            + "Do not change the outfit style or color unless explicitly requested, do not change the background, do not add any lights, garlands, decorations or extra people. "
            + "Only do what is explicitly described in the prompt (pose, action, removal of the jacket) while preserving identity and scene."
        )

        payload = {
            "prompt": full_prompt,
            "image": img_url,
            "negative_prompt": NEGATIVE_PROMPT,
            "num_frames": int(total_frames),
            "frames_per_second": int(fps),
            "seed": int(use_seed),
        }

        tok = self.token
        url = _predict_with_sla(I2V_MODEL, payload, tok)
        tmp = OUT_DIR / f"replicate_t2v_{int(time.time())}.dl.tmp.mp4"
        _download(url, tmp)
        final_path = self._finalize(tmp, "replicate_wanA_t2v", fps=fps)
        return str(final_path)

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
