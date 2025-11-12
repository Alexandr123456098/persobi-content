#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

# проверка .env
if [ ! -f .env ]; then
  echo "Файл .env не найден. Заполни .env (см. fill_env.sh)"
  exit 1
fi

# поднимаем контейнеры
docker compose up -d

# ждём пока n8n станет доступен (простая проверка контейнера)
echo "Ждём 6 секунд для инициализации n8n..."
sleep 6

# если есть content.json — копируем внутрь и импортируем
WFHOST_PATH="./content.json"
if [ -f "$WFHOST_PATH" ]; then
  CID=$(docker compose ps -q n8n)
  if [ -z "$CID" ]; then
    echo "Не найден контейнер n8n. Проверь docker compose ps"
    exit 1
  fi
  docker cp "$WFHOST_PATH" "$CID":/home/node/.n8n/backups/content.json
  docker compose exec -T n8n sh -lc "n8n import:workflow --input='/home/node/.n8n/backups/content.json' || true"
  echo "Импорт попытался выполниться. Проверь лог n8n для деталей."
else
  echo "Файл content.json не найден — положи экспорт воркфлоу в ./content.json и запусти этот скрипт снова."
fi
echo "Готово. tail логов: docker compose logs -f --tail=100 n8n"
