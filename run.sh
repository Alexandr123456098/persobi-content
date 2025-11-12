#!/usr/bin/env bash
set -euo pipefail
cd /opt/content_factory

# Виртуальное окружение
if [ -d .venv ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# Окружение приложения
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

mkdir -p "${OUT_DIR:-/opt/content_factory/out}"
exec python -u -m app.main
