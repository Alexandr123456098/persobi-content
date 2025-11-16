# -*- coding: utf-8 -*-
def price(duration_sec, sound_flag: int) -> int:
    """
    duration_sec: логически 5 или 10 (секунд).
    sound_flag: 0 = без озвучки, 1 = с озвучкой

    Тарифы:
      - 5с без звука  =  55₽
      - 5с со звуком  =  75₽
      - 10с без звука = 110₽
      - 10с со звуком = 150₽

    Внутри:
      - всё, что < 6 секунд, считаем как «короткий» (5с-тариф),
      - всё, что ≥ 6 секунд, считаем как «длинный» (10с-тариф).
    """
    try:
        dur = float(duration_sec)
    except Exception:
        dur = 5.0
    snd = 1 if int(sound_flag) == 1 else 0

    if dur < 6.0:  # трактуем как 5с
        return 75 if snd else 55
    else:          # трактуем как 10с (старший тариф)
        return 150 if snd else 110
