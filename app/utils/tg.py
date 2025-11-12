from aiogram.utils.exceptions import MessageCantBeEdited, MessageToEditNotFound

async def safe_edit_text(msg, text: str, **kwargs):
    """
    Пробует msg.edit_text(...). Если нельзя редактировать — шлёт новое msg.answer(...).
    Возвращает актуальный объект Message (либо отредактированный, либо новый).
    """
    try:
        return await msg.edit_text(text, **kwargs)
    except (MessageCantBeEdited, MessageToEditNotFound):
        return await msg.answer(text, **kwargs)
