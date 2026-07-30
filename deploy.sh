#!/bin/bash
set -e

echo "================================="
echo "       DEPLOY VERBENA"
echo "================================="

REPO_URL="https://github.com/artsartone/verbena.git"
APP_DIR="/var/www/VERBENA"
ENV_FILE="/etc/verbena.env"


echo "=== Установка системных пакетов ==="

apt update

apt install -y \
git \
python3 \
python3-pip \
python3-venv \
nginx


echo "=== Подготовка директории ==="

mkdir -p /var/www


if [ -d "$APP_DIR" ]; then
    echo "Удаление старой версии $APP_DIR"
    rm -rf "$APP_DIR"
fi


echo "=== Клонирование VERBENA ==="

git clone "$REPO_URL" "$APP_DIR"


cd "$APP_DIR"


echo "=== Создание Python окружения ==="

python3 -m venv venv

source venv/bin/activate


pip install --upgrade pip

pip install -r backend/requirements.txt

pip install gunicorn


deactivate


echo "=== Настройка переменных окружения ==="


if [ ! -f "$ENV_FILE" ]; then

cat > "$ENV_FILE" <<EOF
SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')

FLASK_DEBUG=0
FORCE_HTTPS=0

API_BASE=http://localhost:5000

TG_BOT_TOKEN=CHANGE_ME
MAX_BOT_TOKEN=CHANGE_ME

YCLIENTS_PARTNER_TOKEN=CHANGE_ME
YCLIENTS_USER_TOKEN=CHANGE_ME
YCLIENTS_COMPANY_ID=CHANGE_ME

DATABASE_URL=$APP_DIR/beauty.db
EOF


chmod 600 "$ENV_FILE"

echo "Создан $ENV_FILE"

else

echo "$ENV_FILE уже существует"

fi



echo "=== Создание Flask сервиса ==="


cat > /etc/systemd/system/verbena.service <<EOF

[Unit]
Description=VERBENA Flask App
After=network.target


[Service]

User=root

WorkingDirectory=$APP_DIR

EnvironmentFile=$ENV_FILE


ExecStart=$APP_DIR/venv/bin/gunicorn \
-w 4 \
-b 127.0.0.1:5000 \
wsgi:app


Restart=always
RestartSec=5

Environment=PYTHONUNBUFFERED=1


[Install]

WantedBy=multi-user.target

EOF




echo "=== Создание Telegram Bot сервиса ==="


cat > /etc/systemd/system/verbena-bot.service <<EOF

[Unit]

Description=VERBENA Telegram Bot

After=network.target


[Service]

User=root

WorkingDirectory=$APP_DIR

EnvironmentFile=$ENV_FILE


ExecStart=$APP_DIR/venv/bin/python \
$APP_DIR/telegrambot/BeautyVerbenaBot.py


Restart=always

RestartSec=5


Environment=PYTHONUNBUFFERED=1


[Install]

WantedBy=multi-user.target

EOF




echo "=== Настройка nginx ==="


cat > /etc/nginx/sites-available/VERBENA <<EOF

server {

listen 80;

server_name _;


client_max_body_size 10M;


location / {

proxy_pass http://127.0.0.1:5000;


proxy_set_header Host \$host;

proxy_set_header X-Real-IP \$remote_addr;

proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;

proxy_set_header X-Forwarded-Proto \$scheme;


}

}

EOF



rm -f /etc/nginx/sites-enabled/default


ln -sf \
/etc/nginx/sites-available/VERBENA \
/etc/nginx/sites-enabled/VERBENA



echo "=== Запуск сервисов ==="


systemctl daemon-reload


systemctl enable verbena
systemctl restart verbena


systemctl enable verbena-bot
systemctl restart verbena-bot


nginx -t

systemctl restart nginx



echo ""
echo "================================="
echo "       VERBENA DEPLOY DONE"
echo "================================="

echo ""
echo "Flask:"
echo "systemctl status verbena"

echo ""

echo "Bot:"
echo "systemctl status verbena-bot"

echo ""

echo "Logs:"
echo "journalctl -u verbena -f"
