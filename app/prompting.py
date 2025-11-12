import httpx
from .config import settings

SYSTEM_CINEMATIC = (
    "You are a film director. Turn a short idea into a vivid, grounded, realistic video prompt. "
    "Structure the output with: [Scene], [Setting], [Subjects], [Action], [Camera], [Lighting], [Mood], [Details]. "
    "Keep it compact but concrete; avoid brand names unless given."
)

async def build_director_prompt(user_text: str) -> str:
    # Можно расширить стилями через settings.prompt_style
    return await _llm_complete(user_text, SYSTEM_CINEMATIC, settings.openai_model)

async def _llm_complete(user_text: str, system_prompt: str, model: str) -> str:
    # Минимальный вызов Chat Completions (без сторонних SDK)
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openai_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text.strip()},
        ],
        "temperature": 0.8,
        "max_tokens": 600,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        try:
            return data["choices"][0]["message"]["content"].strip()
        except Exception:
            return "Не смог построить промпт: проверь OPENAI_API_KEY/квоты/модель."
