import os, asyncio, logging, httpx, pathlib, time, random, string
log = logging.getLogger("runway")

def _rid(n=8): 
    import string, random
    return ''.join(random.choices(string.ascii_lowercase+string.digits,k=n))

class RunwayClient:
    def __init__(self, base_url, start_path, status_tmpl, api_key, key_header):
        self.base = base_url.rstrip("/")
        self.start = start_path
        self.status_tmpl = status_tmpl
        self.headers = {key_header: api_key, "Content-Type":"application/json"}

    @classmethod
    def from_env(cls):
        api_key = os.getenv("RUNWAY_API_KEY")
        base    = os.getenv("RUNWAY_BASE_URL")
        start   = os.getenv("RUNWAY_START_PATH")
        status  = os.getenv("RUNWAY_STATUS_PATH")
        keyhdr  = os.getenv("RUNWAY_KEY_HEADER","Authorization")
        if not (api_key and base and start and status):
            raise RuntimeError("RUNWAY: env incomplete (RUNWAY_* vars)")
        if keyhdr.lower()=="authorization" and os.getenv("RUNWAY_BEARER","1")=="1" and not api_key.lower().startswith("bearer "):
            api_key = f"Bearer {api_key}"
        return cls(base, start, status, api_key, keyhdr)

    async def generate(self, prompt: str, n: int, out_dir: str):
        timeout = int(os.getenv("RUNWAY_TIMEOUT","300"))
        poll_iv = float(os.getenv("RUNWAY_POLL_SEC","2.0"))
        payload = {
            "prompt": prompt,
            "num_videos": n,
            "duration": int(os.getenv("RUNWAY_DURATION","6")),
            "resolution": os.getenv("RUNWAY_RESOLUTION","1280x720"),
            "fps": int(os.getenv("RUNWAY_FPS","24")),
        }
        async with httpx.AsyncClient(timeout=timeout) as cli:
            r = await cli.post(f"{self.base}{self.start}", headers=self.headers, json=payload)
            r.raise_for_status()
            data = r.json()
            task_id = data.get("task_id") or data.get("id")
            if not task_id:
                raise RuntimeError(f"RUNWAY: no task id in {data}")
            start_ts = time.time()
            while True:
                st = await cli.get(f"{self.base}{self.status_tmpl.format(task_id=task_id)}", headers=self.headers)
                if st.status_code>=400: st.raise_for_status()
                sj = st.json()
                state = (sj.get("state") or sj.get("status") or "").lower()
                if state in ("succeeded","done","completed","ready"): break
                if state in ("failed","error"): raise RuntimeError(f"RUNWAY: failed state {sj}")
                if time.time()-start_ts > timeout: raise TimeoutError("RUNWAY: timeout waiting result")
                await asyncio.sleep(poll_iv)
            media = sj.get("result") or sj
            urls = []
            if isinstance(media, dict):
                for key in ("mp4_url","url","video_url"): 
                    v = media.get(key); 
                    if v: urls.append(v)
                for it in (media.get("videos") or media.get("items") or []):
                    v = it.get("mp4_url") or it.get("url") or it.get("video_url")
                    if v: urls.append(v)
            if not urls: raise RuntimeError(f"RUNWAY: no video urls in {sj}")
            out = []
            pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
            for u in urls[:n]:
                fn = pathlib.Path(out_dir)/f"cf_runway_{_rid()}.mp4"
                async with cli.stream("GET", u) as resp:
                    resp.raise_for_status()
                    with open(fn,"wb") as f:
                        async for chunk in resp.aiter_bytes():
                            f.write(chunk)
                out.append(str(fn))
            return out
