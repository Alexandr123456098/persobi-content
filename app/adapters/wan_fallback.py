# -*- coding: utf-8 -*-
"""
WAN 2.x fallback через HuggingFace Inference API.
"""
import os, time, requests, logging
log = logging.getLogger("wan_fallback")

HF_TOKEN = os.getenv("HF_TOKEN", "").strip()
MODEL_URL = "https://api-inference.huggingface.co/models/cjwbw/wan-2.1-turbo"

def run_wan(prompt: str, out_path="/opt/content_factory/out/wan_fallback.mp4"):
    if not HF_TOKEN:
        raise RuntimeError("HF_TOKEN не задан в .env")
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    payload = {"inputs": prompt, "parameters": {"num_frames": 48, "fps": 8}}
    log.info(f"WAN fallback → {MODEL_URL}")
    for _ in range(120):
        r = requests.post(MODEL_URL, headers=headers, json=payload, timeout=600)
        ct = r.headers.get("content-type", "")
        if r.status_code == 200 and ("video" in ct or "octet-stream" in ct):
            with open(out_path, "wb") as f: f.write(r.content)
            log.info(f"WAN fallback saved → {out_path}")
            return out_path
        if r.status_code in (202, 503):
            time.sleep(3)
            continue
        raise RuntimeError(f"WAN fallback failed {r.status_code}: {r.text[:400]}")
    raise RuntimeError("WAN fallback timeout — модель не прогрелась")
