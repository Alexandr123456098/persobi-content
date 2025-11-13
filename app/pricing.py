# -*- coding: utf-8 -*-
def price(duration_sec, sound_flag: int) -> int:
    """
    duration_sec: 5 или 7.5 (float/int)
    sound_flag: 0 = без озвучки, 1 = с озвучкой
    Тарифы (по ТЗ):
      - 5с без звука = 55₽
      - 5с со звуком = 75₽
      - 7.5с без звука = 110₽
      - 7.5с со звуком = 150₽
    """
    try:
        dur = float(duration_sec)
    except Exception:
        dur = 5.0
    snd = 1 if int(sound_flag) == 1 else 0

    if dur < 6.0:  # трактуем как 5с
        return 75 if snd else 55
    else:          # трактуем как 7.5с
        return 150 if snd else 110
