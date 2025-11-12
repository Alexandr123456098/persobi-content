# HANDOFF

## Проверка
1) `systemctl status <service> && journalctl -u <service> -n 50 --no-pager`
2) Обновить .env из vault:
   `/root/secrets/bin/secret-export <project> /root/projects/<project>/.env`
   Убедиться, что обязательные ключи на месте (см. ниже).
3) Установить зависимости именно из lock:
   `python3 -m pip install -r requirements.lock`

## Обязательные ключи
- Deniska: BOT_TOKEN (если шлёт уведомления), любые API-ключи, нужные дашборду.
- Persobi: BOT_TOKEN, OPENAI_API_KEY (или ключи используемых провайдеров), и др.

## Правила
- Не апдейтить либы «на глаз» — только через PR и перегенерацию `requirements.lock`.
- Перед рестартом делать снапшот: `/root/bin/deniska-snapshot.sh` или `/root/bin/persobi-snapshot.sh`.
