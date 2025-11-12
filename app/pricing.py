# -*- coding: utf-8 -*-
def price(duration_sec: int, sound_flag: int) -> int:
    """
    duration_sec: 5 или 10
    sound_flag: 0 = без озвучки, 1 = с озвучкой
    Тарифы:
      - 5с без звука = 55₽
      - 10с без звука = 110₽
      - 5с со звуком = 75₽
      - 10с со звуком = 150₽
    """
    dur = 10 if int(duration_sec) == 10 else 5
    snd = 1 if int(sound_flag) == 1 else 0
    if dur == 5 and snd == 0:
        return 55
    if dur == 10 and snd == 0:
        return 110
    if dur == 5 and snd == 1:
        return 75
    if dur == 10 and snd == 1:
        return 150
    return 110 if dur == 10 else 55
