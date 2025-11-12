import os, asyncio, logging, httpx, time, pathlib, json, random, string

log = logging.getLogger("kie")

BASE_URL   = os.getenv("KIE_BASE_URL", "https://api.kie.ai").rstrip("/")
API_KEY    = os.getenv("KIEAI_API_KEY") or os.getenv("KIE_API_KEY")
TIMEOUT_S  = int(os.getenv("KIE_TIMEOUT", "300"))
DURATION   = int(os.getenv("KIE_DURATION", "6"))
RES        = os.getenv("KIE_RESOLUTION", "1280x720")
FPS        = int(os.getenv("KIE_FPS", "24"))

ENV_START  = os.getenv("KIE_START_PATH")   # e.g. /api/v1/video/generate
ENV_STATUS = os.getenv("KIE_STATUS_PATH")  # e.g. /api/v1/video/tasks/{task_id}

START_CANDIDATES = [ENV_START] if ENV_START else [
    "/api/v1/video/generate",
    "/v1/video/generate",
    "/api/v1/video/text-to-video",
    "/v1/video/text-to-video",
    "/api/v1/video/create",
    "/v1/video/create",
    "/v1/tasks/video/generate",
    "/api/v1/tasks/video/generate",
]

STATUS_CANDIDATES = [ENV_STATUS] if ENV_STATUS else [
    "/api/v1/video/tasks/{task_id}",
    "/v1/video/tasks/{task_id}",
    "/api/v1/tasks/{task_id}",
    "/v1/tasks/{task_id}",
]

def _rid(n=9):
    return ''.join(random.choices(string.ascii_lowercase+string.digits, k=n))

class KIEClient:
    def __init__(self):
        if not API_KEY:
            raise RuntimeError("KIE: API key is empty")
        self.header_sets = [
            {"Authorization": f"Bearer {API_KEY}", "Content-Type":"application/json"},
            {"X-API-Key": API_KEY, "Content-Type":"application/json"},
            {"Authorization": API_KEY, "Content-Type":"application/json"},
        ]

    async def _try_start(self, prompt: str, cli: httpx.AsyncClient):
        payload = {"prompt": prompt, "num_videos": 1, "duration": DURATION, "resolution": RES, "fps": FPS}
        last_err = None
        for path in START_CANDIDATES:
            if not path: 
                continue
            url = f"{BASE_URL}{path}"
            for headers in self.header_sets:
                log.info("KIE START %s payload={num_videos:%s,duration:%s,resolution:%s,fps:%s}",
                         url, payload["num_videos"], payload["duration"], payload["resolution"], payload["fps"])
                try:
                    r = await cli.post(url, headers=headers, json=payload)
                    log.info("HTTP POST %s %s", url, r.status_code)
                    if r.status_code >= 400:
                        # логируем до 1К символов тела — там часто подсказка про путь/поля
                        body = (r.text or "")[:1000].replace("\n"," ")
                        log.info("KIE START error body=%s", body)
                        r.raise_for_status()
                    ct = r.headers.get("Content-Type","")
                    if ct.startswith("video/") or ct == "application/octet-stream":
                        return {"mode":"immediate", "response": r, "headers": headers}
                    data = r.json()
                    task_id = data.get("task_id") or data.get("id")
                    if task_id:
                        return {"mode":"task", "task_id": str(task_id), "headers": headers}
                    dl = data.get("download_url") or data.get("url")
                    if dl:
                        return {"mode":"url", "download_url": dl, "headers": headers}
                    log.info("KIE START unknown JSON=%s", json.dumps(data)[:1000])
                except Exception as e:
                    last_err = e
        raise last_err or RuntimeError("KIE: could not start task")

    async def _poll_and_download(self, task_id: str, cli: httpx.AsyncClient, headers):
        t0 = time.time()
        while time.time() - t0 < TIMEOUT_S:
            for fmt in STATUS_CANDIDATES:
                if not fmt:
                    continue
                url = f"{BASE_URL}{fmt.format(task_id=task_id)}"
                try:
                    r = await cli.get(url, headers=headers)
                    if r.status_code >= 400:
                        log.info("KIE STATUS %s %s body=%s", url, r.status_code, (r.text or "")[:600].replace("\n"," "))
                        r.raise_for_status()
                    data = r.json()
                    status = (data.get("status") or data.get("state") or "").lower()
                    if status in {"done","completed","success","succeeded","ready"}:
                        durl = data.get("download_url") or data.get("url")
                        if not durl:
                            raise RuntimeError("KIE: completed but no download url")
                        return durl
                    if status in {"queued","pending","processing","running","in_progress"}:
                        await asyncio.sleep(2); break
                    if status in {"failed","error"}:
                        raise RuntimeError(f"KIE: task failed: {data}")
                except Exception:
                    await asyncio.sleep(2)
            await asyncio.sleep(2)
        raise TimeoutError("KIE: task timeout")

    async def generate(self, prompt: str, n: int, out_dir: str):
        pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
        out = []
        async with httpx.AsyncClient(timeout=60) as cli:
            start = await self._try_start(prompt, cli)
            if start["mode"] == "immediate":
                fname = pathlib.Path(out_dir, f"kie_{_rid()}.mp4")
                with open(fname, "wb") as f:
                    async for chunk in start["response"].aiter_bytes():
                        f.write(chunk)
                out.append(str(fname)); return out
            if start["mode"] == "url":
                r = await cli.get(start["download_url"]); r.raise_for_status()
                fname = pathlib.Path(out_dir, f"kie_{_rid()}.mp4"); open(fname,"wb").write(r.content)
                out.append(str(fname)); return out
            durl = await self._poll_and_download(start["task_id"], cli, start["headers"])
            r = await cli.get(durl); r.raise_for_status()
            fname = pathlib.Path(out_dir, f"kie_{_rid()}.mp4"); open(fname,"wb").write(r.content)
            out.append(str(fname)); return out
