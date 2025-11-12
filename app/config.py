from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()

class Settings(BaseModel):
    bot_token: str = os.getenv("BOT_TOKEN", "")
    openai_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    prompt_style: str = os.getenv("PROMPT_STYLE", "cinematic-v1")

    def validate(self):
        miss = []
        if not self.bot_token: miss.append("BOT_TOKEN")
        if not self.openai_key: miss.append("OPENAI_API_KEY")
        if miss:
            raise SystemExit(f"Отсутствуют переменные: {', '.join(miss)}")
        return self

settings = Settings().validate()
