import os, asyncio, logging, httpx, pathlib, time, random, string
log = logging.getLogger("luma")

def _rid(n=8): 
    import string, random
    return ''.join(random.choices(string.ascii_lowercase+string.digits,k=n))

class LumaClient:
    def __init__(self, base_url, start_path, status_tmpl, api_key, key_header):
        self.base = base_url.rstrip("/")
        self.start = start_path
        self.status_tmpl = status_tmpl
        self.headers = {key_header: api_key, "Content-Type":"application/json"}

    @classmethod
    def from_env(cls):
        api_key = os.getenv("LUMA_API_KEY")
        base    = os.getenv("LUMA_BASE_URL")           # напр. https://api.lumalabs.ai
        start   = os.getenv("LUMA_START_PATH")         # напр. /v1/videos
        status  = os.getenv("LUMA_STATUS_PATH")        # напр. /v1/videos/{task_id}
        keyhdr  = os.getenv("LUMA_KEY_HEADER","Authorization")
        if not (api_key and base and start and status):
            raise RuntimeError("LUMA: env incomplete (LUMA_API_KEY, LUMA_BASE_URL, LUMA_START_PATH, LUMA_STATUS_PATH)")
        # Если хедер стандартный — добавим "Bearer " автоматически (можно выключить LUMA_BEARER=0)
        if keyhdr.lower()=="authorization" and os.getenv("LUMA_BEARER","1")=="1" and not api_key.lower().startswith("bearer "):
            api_key = f"Bearer {api_key}"
        return cls(base, start, status, api_key, keyhdr)

    async def generate(self, prompt: str, n: int, out_dir: str):
        # Минимальный контракт: POST -> {task_id}, потом GET/STATUS пока state=done, поле url/mp4_url
        timeout = int(os.getenv("LUMA_TIMEOUT","300"))
        poll_iv = float(os.getenv("LUMA_POLL_SEC","2.0"))
        payload = {
            "prompt": prompt,
            "num_videos": n,
            "duration": int(os.getenv("LUMA_DURATION","6")),
            "resolution": os.getenv("LUMA_RESOLUTION","1280x720"),
            "fps": int(os.getenv("LUMA_FPS","24")),
        }
        async with httpx.AsyncClient(timeout=timeout) as cli:
            url = f"{self.base}{self.start}"
            r = await cli.post(url, headers=self.headers, json=payload)
            r.raise_for_status()
            data = r.json()
            task_id = data.get("task_id") or data.get("id")
            if not task_id:
                raise RuntimeError(f"LUMA: no task id in {data}")
            # poll
            start_ts = time.time()
            while True:
                st = await cli.get(f"{self.base}{self.status_tmpl.format(task_id=task_id)}", headers=self.headers)
                if st.status_code>=400: 
                    st.raise_for_status()
                sj = st.json()
                state = (sj.get("state") or sj.get("status") or "").lower()
                if state in ("succeeded","done","completed","ready"):
                    break
                if state in ("failed","error"):
                    raise RuntimeError(f"LUMA: failed state {sj}")
                if time.time()-start_ts > timeout:
                    raise TimeoutError("LUMA: timeout waiting result")
                await asyncio.sleep(poll_iv)
            # берём url(ы)
            media = sj.get("result") or sj
            urls = []
            for key in ("mp4_url","url","video_url"):
                v = media.get(key) if isinstance(media, dict) else None
                if v: urls.append(v)
            if not urls and isinstance(media, dict):
                # иногда приходят массивы результатов
                arr = media.get("videos") or media.get("items") or []
                for it in arr:
                    v = it.get("mp4_url") or it.get("url") or it.get("video_url")
                    if v: urls.append(v)
            if not urls:
                raise RuntimeError(f"LUMA: no video urls in {sj}")
            # скачиваем n штук (или первую)
            out = []
            pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
            for i, u in enumerate(urls[:n]):
                fn = pathlib.Path(out_dir) / f"cf_luma_{_rid()}.mp4"
                async with cli.stream("GET", u) as resp:
                    resp.raise_for_status()
                    with open(fn, "wb") as f:
                        async for chunk in resp.aiter_bytes():
                            f.write(chunk)
                out.append(str(fn))
            return out
