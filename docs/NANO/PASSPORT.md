# PASSPORT — Persobi Content (Content Factory)

## Сервис
- systemd unit: content-factory.service
- Старт: /usr/bin/flock -n /var/run/content-factory.lock /opt/content_factory/run.sh
- Рабочая директория: /opt/content_factory

## Файлы
- Приложение: app/main.py
- Бот: app/bot.py
- UI/клавиатура/колбэки: app/bot_ui_patch.py, app/bot_handlers_patch.py
- Адаптеры: app/adapters/*
- Окружение: .env (корень проекта)
- Рендеры/выходы: /opt/content_factory/out

## Кнопки (актуально)
- «🔁 Ещё раз» — callback_data="again"
- «🧩 SORA 2» — callback_data="sora2_go" (AGAIN-LIKE)
- «📷 По фото» — callback_data="photo_help"
- «📽 По видео» — callback_data="video_help"

## Поведение SORA 2
- Статус: «🧩 Генерирую SORA 2…»
- Генерация: как «Ещё раз»: есть last_image → I2V, иначе T2V.

## Проверки
- Кнопки/генерация:
  journalctl -u content-factory.service -n 120 --no-pager | grep -E "\[CALLBACK\]|\[ui\]"
- Старт поллинга:
  journalctl -u content-factory.service -n 50 --no-pager | grep "Start polling"

## Контроль версий и снапшоты
- Git: /opt/content_factory/.git (main)
- NANO-архивы: docs/NANO/
- Снапшоты tar: /root/snapshots/content_factory_YYYYMMDD_HHMMSS.tgz
