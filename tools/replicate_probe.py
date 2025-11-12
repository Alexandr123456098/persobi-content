#!/usr/bin/env python3
# /opt/content_factory/tools/replicate_probe.py
import os, sys, json, urllib.request, urllib.error

API = "https://api.replicate.com/v1/models"
TOKEN = os.getenv("REPLICATE_API_TOKEN", "").strip()

# Отредактируй список под себя:
CANDIDATES = [
    "wan-video/wan-2.5-i2v-fast",
    "wan-video/wan-2.2-i2v-fast",
    "tencent/hunyuan-video",
    "kwaivgi/kling-v2.1",
]

if not TOKEN:
    print("ERROR: env REPLICATE_API_TOKEN is empty", file=sys.stderr)
    sys.exit(2)

def get(url):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Token {TOKEN}",
        "User-Agent": "replicate-probe/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.getcode(), r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8") if e.fp else ""
    except Exception as e:
        return 0, str(e)

def probe_model(slug):
    url = f"{API}/{slug}"
    code, body = get(url)
    if code != 200:
        return {"slug": slug, "status": code or "ERR", "ok": False, "latest_version": None, "note": "not found or no access"}
    try:
        data = json.loads(body)
        ver = (data.get("latest_version") or {}).get("id")
        visibility = data.get("visibility")
        owner = (data.get("owner") or {}).get("username") or ""
        return {"slug": slug, "status": 200, "ok": True, "latest_version": ver, "visibility": visibility, "owner": owner}
    except Exception as e:
        return {"slug": slug, "status": 200, "ok": False, "latest_version": None, "note": f"parse error: {e}"}

def main():
    print("Slug".ljust(32), "Status".ljust(8), "OK".ljust(3), "LatestVersionID")
    print("-"*80)
    results = []
    for slug in CANDIDATES:
        r = probe_model(slug)
        results.append(r)
        print(slug.ljust(32), str(r.get("status")).ljust(8), str(r.get("ok")).ljust(3), (r.get("latest_version") or "-"))
    # сохраним JSON на всякий
    out_path = "/opt/content_factory/tools/replicate_models.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print("\nSaved:", out_path)

if __name__ == "__main__":
    main()
