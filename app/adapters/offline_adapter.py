# -*- coding: utf-8 -*-
# Stub offline adapter — полностью заглушка.
# Все предпросмотры / генерации теперь идут через Replicate.

class OfflineClient:
    def __init__(self, out_dir):
        self.out_dir = out_dir

    async def generate_video(self, prompt: str, seconds: int):
        # Возвращаем текст, чтобы вызвать ошибку и не маскировать Replicate
        return "❌ Offline режим отключён. Используется только Replicate."
