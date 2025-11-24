# -*- coding: utf-8 -*-
import os, json, shlex, time, subprocess, uuid, random
from pathlib import Path
from typing import Dict, Any, Optional

API_BASE = "https://api.replicate.com/v1"
T2V_MODEL = os.environ.get("REPLICATE_MODEL_T2V", "wan-video/wan-2.2-t2v-fast")

ROOT = Path("/opt/content_factory")
OUT_DIR = ROOT / "out"
PRED_DIR = OUT_DIR / "predictions"
OUT_DIR.mkdir(parents=True, exist_ok=True)
PRED_DIR.mkdir(parents=True, exist_ok=True)

ENV_PATH = ROOT / ".env"
DEFAULT_SECONDS = float(os.environ.get("DEFAULT_DURATION", "5"))
DEFAULT_FPS = int(os.environ.get("REPLICATE_FPS", "24"))
MAX_FRAMES_HARD = 120

FIXED_SEED = int(os.environ.get("REPLICATE_FIXED_SEED", "123456789"))

PROMPT_PRIMER = (
    "Start directly with a fully photorealistic frame. "
    "No fade-in, no painterly approximations. "
    "Stable exposure, realistic skin, no burned highlights. "
)

NEG = (
    "glitch, lowres, artifacts, deformed face, deformed body, "
    "mutated face, mutated body, weird colors, overexposed, "
    "fairy lights, garlands, bokeh, glowing bulbs, neon, lens flare"
)


class ReplicateError(RuntimeError):
    pass


def _run(cmd: str, check=True):
    p = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode != 0:
        raise RuntimeError(f"CMD FAIL ({p.returncode}): {p.stderr.decode()}")
    return p


def _parse_dotenv_token(path: Path) -> str:
    if not path.exists():
        return ""
    for line in path.read_text().splitlines():
        if line.strip().startswith("REPLICATE_API_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _ensure_token() -> str:
    tok = os.environ.get("REPLICATE_API_TOKEN", "").strip()
    if not tok:
        tok = _parse_dotenv_token(ENV_PATH).strip()
    if not tok or len(tok) < 10:
        raise ReplicateError("Invalid REPLICATE_API_TOKEN")
    return tok


def _json_post(url: str, data: Dict[str, Any], tok: str):
    cmd = (
        f"curl -fsS -X POST "
        f"-H 'Authorization: Token {tok}' "
        f"-H 'Content-Type: application/json' "
        f"-d {shlex.quote(json.dumps(data))} "
        f"{shlex.quote(url)}"
    )
    p = _run(cmd)
    return json.loads(p.stdout.decode())


def _json_get(url: str, tok: str):
    cmd = (
        f"curl -fsS -X GET "
        f"-H 'Authorization: Token {tok}' "
        f"{shlex.quote(url)}"
    )
    p = _run(cmd)
    return json.loads(p.stdout.decode())


def _download(url: str, dst: Path):
    cmd = f"curl -fsSL --retry 3 -o {shlex.quote(str(dst))} {shlex.quote(url)}"
    _run(cmd)


def _calc_frames(seconds: float, fps: int) -> int:
    n = int(round(seconds * fps))
    return max(1, min(n, MAX_FRAMES_HARD))


def _seed(seed: Optional[int]):
    if seed:
        return int(seed)
    base = int(time.time() * 1000) ^ random.randint(0, 2_147_483_647)
    s = base % 2_147_483_647
    return s or FIXED_SEED


def _ffmpeg_norm(path: Path, fps: int) -> Path:
    out = path.with_suffix(".final.mp4")
    cmd = (
        f"ffmpeg -y -i {shlex.quote(str(path))} "
        f"-vf scale=-2:720:flags=lanczos "
        f"-r {int(fps)} "
        f"-c:v libx264 -preset veryfast -movflags +faststart "
        f"{shlex.quote(str(out))}"
    )
    _run(cmd)
    return out


def _poll_prediction(url: str, tok: str) -> str:
    for _ in range(300):
        time.sleep(1.3)
        js = _json_get(url, tok)
        st = js.get("status")
        if st == "succeeded":
            out = js.get("output")
            if isinstance(out, list) and out:
                return out[-1]
            if isinstance(out, str):
                return out
            raise ReplicateError("No output url")
        if st == "failed":
            raise ReplicateError(f"Prediction failed: {js}")
    raise ReplicateError("Prediction timeout")


class ReplicateClient:
    def __init__(self, token: Optional[str] = None):
        self.token = token or _ensure_token()

    def _finalize(self, downloaded_path: Path, fps: int):
        norm = _ffmpeg_norm(downloaded_path, fps)
        final = OUT_DIR / f"wan22_{int(time.time())}.mp4"
        norm.rename(final)
        return final

    def generate_from_text(self, prompt: str, seconds=DEFAULT_SECONDS, fps=DEFAULT_FPS, seed=None):
        if not prompt.strip():
            raise ReplicateError("Prompt empty")

        fps = max(5, min(int(fps), 24))
        frames = _calc_frames(seconds, fps)
        sd = _seed(seed)

        payload = {
            "input": {
                "prompt": f"{PROMPT_PRIMER}{prompt}",
                "negative_prompt": NEG,
                "num_frames": frames,
                "frames_per_second": fps,
                "seed": sd,
            }
        }

        js = _json_post(f"{API_BASE}/models/{T2V_MODEL}/predictions", payload, self.token)
        get_url = js["urls"]["get"]

        url = _poll_prediction(get_url, self.token)
        tmp = OUT_DIR / f"tmp_{uuid.uuid4().hex[:10]}.mp4"
        _download(url, tmp)
        final = self._finalize(tmp, fps)
        return str(final)

    def text(self, p: str):
        return self.generate_from_text(p)
