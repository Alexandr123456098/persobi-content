#!/usr/bin/env bash
set -e
TEMPLATE=".env.template"
TARGET=".env"

if [ ! -f "$TEMPLATE" ]; then
  echo "Нет $TEMPLATE. Сначала создайте шаблон."
  exit 1
fi

# Usage: BOT_TOKEN="xxx" OPENAI_API_KEY="yyy" ./fill_env.sh
env | grep -E '^(BOT_TOKEN|OPENAI_API_KEY|KIEAI_API_KEY|SUPABASE_URL|SUPABASE_KEY|PAYMENT_PROVIDER_APIKEY|N8N_BASIC_AUTH_USER|N8N_BASIC_AUTH_PASSWORD|WEBHOOK_URL)=' > /tmp/env_fill.$$ || true

# create .env by taking template and replacing vars from environment
cp "$TEMPLATE" "$TARGET"
while read -r line; do
  key=$(echo "$line" | cut -d= -f1)
  val=$(echo "$line" | cut -d= -f2-)
  # replace exact key line in .env (preserve quoting)
  sed -i "s|^${key}=.*|${key}=${val}|" "$TARGET" || echo "${key}=${val}" >> "$TARGET"
done < /tmp/env_fill.$$
rm -f /tmp/env_fill.$$

chmod 600 "$TARGET"
echo ".env создан (permissions 600)."
echo "Запустите: docker compose up -d"
