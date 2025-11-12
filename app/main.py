import asyncio, logging, uvloop
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from .config import settings
from .prompting import build_director_prompt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
bot = Bot(token=settings.bot_token)
dp = Dispatcher()

HELLO = (
"Привет! Я соберу режиссёрский промпт под твою идею и предложу 1/2/3 видео.\n"
"Напиши мысль (например: «хочу видео с бабушкой на веранде летом»). "
"Также можешь отправить фото + подпись — учту детали из текста."
)

@dp.message(CommandStart())
async def on_start(m: Message):
    await m.answer(HELLO)

@dp.message(Command("cancel"))
async def on_cancel(m: Message):
    await m.answer("Сбросил. Готов к новой идее.")

@dp.message(F.photo)
async def on_photo(m: Message):
    caption = (m.caption or "").strip()
    if not caption:
        await m.answer("Добавь подпись к фото — текст задаёт замысел.")
        return
    await _handle_idea(m, caption)

@dp.message(F.text & ~F.via_bot)
async def on_text(m: Message):
    text = m.text.strip()
    # комманда выбора количества видео — простая заглушка
    if text in ("1", "2", "3"):
        await m.answer(f"Окей, генерирую {text} видео (заглушка). Дальше подключим провайдер видео.")
        return
    await _handle_idea(m, text)

async def _handle_idea(m: Message, idea: str):
    await m.answer("Думаю над режиссёрским промптом…")
    prompt = await build_director_prompt(idea)
    reply = (
        "Вот твой режиссёрский промпт (копируй куда хочешь):\n\n"
        f"{prompt}\n\n"
        "Сколько видео сделать: *1*, *2* или *3*?"
    )
    await m.answer(reply, parse_mode="Markdown")

def main():
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    asyncio.run(dp.start_polling(bot, allowed_updates=["message", "edited_message"]))

if __name__ == "__main__":
    main()
