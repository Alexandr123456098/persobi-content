#!/usr/bin/env bash
set -e
WF="/root/wf.json"   # временный файл для экспорта
WID="$1"
if [ -z "$WID" ]; then
  echo "Usage: $0 <workflowId>"
  exit 2
fi
mkdir -p /tmp/cf
docker compose exec -T n8n sh -lc "n8n export:workflow --id $WID --pretty" > /tmp/cf/wf.export.json
jq '([.[0].nodes, .nodes] | map(select(.!=null)) | .[0]) |=
    (map(if (.type|test("telegramTrigger";"i")) then
        .parameters.updateMode="polling" |
        .parameters.useWebhook=false |
        .parameters.updates=["message","editedMessage","callbackQuery"] |
        (.parameters |= .)
     else . end))' /tmp/cf/wf.export.json > /tmp/cf/wf.patched.json
docker cp /tmp/cf/wf.patched.json $(docker compose ps -q n8n):/home/node/.n8n/backups/wf.patched.json
docker compose exec -T n8n sh -lc "n8n import:workflow --input='/home/node/.n8n/backups/wf.patched.json' || true"
echo "Попытка импортировать патч. Проверь лог n8n."
