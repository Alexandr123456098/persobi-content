# -*- coding: utf-8 -*-
"""
WAN 2.2 i2v adapter через Replicate (новый API).
Загружает локальный файл на tmpfiles.org → подставляет публичный URL в "image".
"""

import os
import json
import time
import logging
import requests
from typing import Dict

log = logging.getLogger("wan_adapter")
log.setLevel(logging.INFO)

REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN", "").strip()
WAN_I2V_MODEL_VERSION = os.getenv("WAN_I2V_MODEL_VERSION", "").strip()

POLL_SEC = float(os.getenv("WAN_POLL_SECONDS", "3"))
POLL_MAX = int(os.getenv("WAN_POLL_MAX_LOOPS", "400"))

class WanError(RuntimeError):
    pass

def _auth_headers() -> Dict[str,str]:
    if not REPLICATE_API_TOKEN:
        raise WanError("Нет REPLICATE_API_TOKEN")
    return {"Authorization": f"Token {REPLICATE_API_TOKEN}", "Content-Type": "application/json"}

def _upload_tmp(path: str) -> str:
    """Загрузка файла на tmpfiles.org для получения временного URL."""
    with open(path, "rb") as f:
        r = requests.post("https://tmpfiles.org/api/v1/upload", files={"file": f})
    if r.status_code != 200:
        raise WanError(f"Upload FAIL {r.status_code}: {r.text[:200]}")
    data = r.json()
    url = data.get("data", {}).get("url")
    if not url:
        raise WanError(f"Upload response без url: {r.text[:200]}")
    # ссылка tmpfiles идёт как https://tmpfiles.org/XXXX → превращаем в download URL
    return url.replace("https://tmpfiles.org/", "https://tmpfiles.org/dl/")

def run_wan_i2v(image_path: str, prompt: str) -> str:
    if not WAN_I2V_MODEL_VERSION:
        raise WanError("Нет WAN_I2V_MODEL_VERSION")
    if not os.path.isfile(image_path):
        raise WanError(f"Нет файла: {image_path}")

    image_url = _upload_tmp(image_path)
    payload = {
        "version": WAN_I2V_MODEL_VERSION,
        "input": {
            "image": image_url,
            "prompt": prompt,
            "width": 1280,
            "height": 720,
            "seconds": 6,
            "fps": 24
        }
    }

    log.info("POST /v1/predictions (WAN i2v)...")
    r = requests.post("https://api.replicate.com/v1/predictions",
                      headers=_auth_headers(),
                      data=json.dumps(payload),
                      timeout=180)
    if r.status_code not in (200,201):
        raise WanError(f"Prediction start FAIL {r.status_code}: {r.text[:500]}")

    data = r.json()
    pid = data.get("id")
    if not pid:
        raise WanError("Нет prediction id")
    return _poll_prediction(pid)

def _poll_prediction(pred_id: str) -> str:
    for i in range(POLL_MAX):
        time.sleep(POLL_SEC)
        r = requests.get(f"https://api.replicate.com/v1/predictions/{pred_id}",
                         headers=_auth_headers())
        if r.status_code != 200:
            raise WanError(f"Poll {r.status_code}: {r.text[:300]}")
        data = r.json()
        st = data.get("status")
        if st in ("succeeded","failed","canceled"):
            out = data.get("output")
            if st == "succeeded" and out:
                if isinstance(out, list):
                    out = out[0]
                return out
            raise WanError(f"WAN завершился без результата: {st}")
    raise WanError("Timeout ожидания WAN")
