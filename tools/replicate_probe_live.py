#!/usr/bin/env python3
# /opt/content_factory/tools/replicate_probe_live.py
# Проверка доступности моделей на Replicate через POST /models/{slug}/predictions с немедленной отменой.
# Идея: если 201 (created) или даже 400 (validation error) -> endpoint живой и slug корректный.
# Если 404/401 -> нет модели/нет доступа.

import os, sys, json, urllib.request, urllib.error, time

API = "https://api.replicate.com/v1"
TOKEN = os.getenv("REPLICATE_API_TOKEN", "").strip()
TEST_IMAGE_URL = os.getenv("REPLICATE_TEST_IMAGE_URL", "https://picsum.photos/seed/persobi/512/512")

CANDIDATES = [
    # t2v / i2v WAN (fast): обычно доступны без явной версии
    "tencent/hunyuan-video",
    "wan-video/wan-2.2-i2v-fast",
    # если есть 2.5 — проверим тоже
    "wan-video/wan-2.5-i2v-fast",
    # Kling (если жив)
    "kwaivgi/kling-v2.1",
]

if not TOKEN:
    print("ERROR: env REPLICATE_API_TOKEN is empty", file=sys.stderr)
    sys.exit(2)

def req(method, path, payload=None, timeout=20):
    url = f"{API}{path}"
    headers = {
        "Authorization": f"Token {TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "replicate-probe-live/1.0",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    r = urllib.request.Request(url, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.getcode(), body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        return e.code, body
    except Exception as e:
        return 0, str(e)

def create_prediction(slug, kind):
    """
    kind = 't2v' или 'i2v' — подставляем минимально валидный input.
    Задача — получить 201 или 400 (оба означают "endpoint жив").
    """
    if kind == "i2v":
        payload = {
            "input": {
                # у разных WAN/Kling поля чуть отличаются, но цель — прогнать handshake
                "prompt": "test",
                "image": TEST_IMAGE_URL,
                "duration": 2,
            }
        }
    else:
        payload = {
            "input": {
                "prompt": "test",
                "duration": 2,
            }
        }
    return req("POST", f"/models/{slug}/predictions", payload)

def cancel_prediction(pred_id):
    return req("DELETE", f"/predictions/{pred_id}")

def main():
    print("Slug".ljust(32), "Kind".ljust(5), "HTTP".ljust(4), "Verdict".ljust(10), "PredictionID/Note")
    print("-"*100)
    for slug in CANDIDATES:
        kind = "i2v" if "i2v" in slug else "t2v"
        code, body = create_prediction(slug, kind)
        verdict = "unknown"
        note = "-"
        pred_id = None
        try:
            data = json.loads(body) if body else {}
        except Exception:
            data = {}
        if code == 201:
            verdict = "alive"
            pred_id = data.get("id")
            note = pred_id or "-"
        elif code == 400:
            # Валидация не прошла (ок) — endpoint живой, просто нужны точные поля
            verdict = "alive(400)"
            note = (data.get("error") or {}).get("message", "-") or "-"
        elif code in (401, 403):
            verdict = "unauth"
            note = "token/permission"
        elif code == 404:
            verdict = "notfound"
            note = "no such model"
        else:
            verdict = "err"
            note = f"HTTP {code}"

        print(slug.ljust(32), kind.ljust(5), str(code).ljust(4), verdict.ljust(10), note)

        # Если реально создали — отменим немедленно (не тратим GPU-время)
        if pred_id:
            cancel_prediction(pred_id)
            time.sleep(0.2)

    print("\nHint: 201/400 = можно внедрять; 404/401 = исключаем из списка.")

if __name__ == "__main__":
    main()
