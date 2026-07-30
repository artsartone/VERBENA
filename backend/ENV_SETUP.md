# README: Настройка переменных окружения

## .env файл

Этот проект использует переменные окружения для хранения чувствительных данных (API ключи, токены, секреты).

### Создание .env файла

1. Скопируйте `.env.example` в `.env`:
   ```bash
   cp backend/.env.example backend/.env
   ```

2. Отредактируйте `.env` и замените значения на свои:
   - `YCLIENTS_PARTNER_TOKEN` — токен партнёра YClients
   - `YCLIENTS_USER_TOKEN` — пользовательский токен YClients
   - `YCLIENTS_COMPANY_ID` — ID вашей компании в YClients
   - `SECRET_KEY` — случайная строка для сессий Flask (сгенерируйте через `python -c "import secrets; print(secrets.token_hex(32))"`)
   - `TG_BOT_TOKEN` — токен Telegram бота (опционально)
   - `MAX_BOT_TOKEN` — токен MAX бота (опционально)

### Переменные окружения

| Переменная | Описание | Обязательно | Пример |
|------------|----------|-------------|--------|
| `YCLIENTS_PARTNER_TOKEN` | Токен партнёра YClients API | Да | `your_partner_token` |
| `YCLIENTS_USER_TOKEN` | Пользовательский токен YClients API | Да | `your_user_token` |
| `YCLIENTS_COMPANY_ID` | ID компании в YClients | Да | `your_company_id` |
| `SECRET_KEY` | Секретный ключ Flask для сессий | Да | `a1b2c3d4...` (64 символа) |
| `FORCE_HTTPS` | Включить HTTPS для cookie (1/0) | Нет | `0` |
| `DATABASE_URL` | Путь к SQLite базе данных | Нет | `/path/to/beauty.db` |
| `LOG_LEVEL` | Уровень логирования | Нет | `INFO` |
| `TG_BOT_TOKEN` | Токен Telegram бота | Нет | `123456:ABC-DEF...` |
| `MAX_BOT_TOKEN` | Токен MAX бота | Нет | `...` |

### Безопасность

⚠️ **Никогда не коммитьте `.env` файл в Git!**

Файл `.env` уже добавлен в `.gitignore`. Используйте `.env.example` как шаблон для документации.

### Локальная разработка

Для локальной разработки создайте `.env` с тестовыми данными:

```bash
cd backend
cp .env.example .env
# Отредактируйте .env и установите свои токены
```

### Production

В production среде используйте менеджеры секретов:
- Docker Secrets
- AWS Secrets Manager
- HashiCorp Vault
- Или настройте переменные окружения напрямую в вашем хостинге

## Установка зависимостей

```bash
cd backend
pip install -r requirements.txt
```

## Запуск приложения

```bash
cd backend
python app.py
```

Или через gunicorn для production:

```bash
gunicorn --bind 0.0.0.0:8000 --workers 4 app:app
```