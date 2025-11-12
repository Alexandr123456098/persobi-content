# Persobi (личный ассистент / контент) — NANO эталон

## Пути и состав
- Проект: /root/projects/persobi-content
- .env: /root/projects/persobi-content/.env
- Главный сервис: /etc/systemd/system/persobi.service
- Логи: journalctl -u persobi.service -f -n 100

## systemd юнит (эталон)
/etc/systemd/system/persobi.service
-----------------------------------
[Unit]
Description=Persobi Assistant
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/root/projects/persobi-content
EnvironmentFile=/root/projects/persobi-content/.env
ExecStart=/usr/bin/python3 /root/projects/persobi-content/main.py
Restart=on-failure
RestartSec=5s
TimeoutStartSec=60s
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target

## .env (шаблон; заполняется реальными значениями)
/root/projects/persobi-content/.env
-----------------------------------
TELEGRAM_BOT_TOKEN=8357463401:AAGf0CuUQ1jLLjqzFmZeP-sSEBj7IEbOtkI
OPENAI_API_KEY=__FILL__
ADMIN_ID=1079011202
DB_PATH=/root/projects/persobi-content/persobi.db
PYTHONUNBUFFERED=1

## Команды проверки
systemctl daemon-reload
systemctl enable --now persobi.service
systemctl status persobi.service --no-pager
journalctl -u persobi.service -n 200 --no-pager
journalctl -u persobi.service -f -n 100

## Дениска / NANO
curl -u alex:FL21010808 -fsS http://127.0.0.1:8081/ping && echo
curl -u alex:FL21010808 -fsS http://127.0.0.1:8081/nano_index | jq -c '.projects|map({p:.project,c:(.items|length)})'

## Снапшот
bash /root/bin/deniska-snapshot.sh

## Чёрный список «граблей»
- Пустой OPENAI_API_KEY → запуск запрещать (проверка в юните).
- Несогласованность токенов между .env и кодом → одно место истины: .env.

## Быстрый чек-лист
1) Заполни .env (минимум TELEGRAM_BOT_TOKEN и OPENAI_API_KEY)
2) daemon-reload + restart
3) Журнал без ошибок AUTH/OPENAI
4) Снапшот
