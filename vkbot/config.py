"""
Конфигурация VK бота.

Переменные окружения:
- VK_GROUP_ID: ID сообщества VK
- VK_TOKEN: Токен бота VK
- VK_CONFIRMATION_TOKEN: Токен подтверждения для Callback API
"""
import os
from dotenv import load_dotenv
from pathlib import Path

# Загружаем .env из backend/.env (как в Telegram боте)
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / "backend" / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)

# ─── Конфигурация VK ───
VK_GROUP_ID = os.environ.get("VK_GROUP_ID", "")
VK_TOKEN = os.environ.get("BOT_TOKEN_VK", "")
VK_CONFIRMATION_TOKEN = os.environ.get("VK_CONFIRMATION_TOKEN", "")

# ─── API Base ───
API_BASE = os.environ.get("API_BASE", "http://localhost:5000")

# ─── Токен Telegram-бота для уведомлений подписанным сотрудникам ───
# (сотрудники подписываются в admin.html → «Уведомления» → Telegram ID)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# ─── Прокси для Telegram API (если api.telegram.org недоступен напрямую) ───
BOT_PROXY = os.environ.get("BOT_PROXY", "")

# ─── Проверка конфигурации ───
def check_config() -> bool:
    """Проверить, что все необходимые переменные настроены."""
    if not VK_GROUP_ID:
        print("❌ VK_GROUP_ID не задан!")
        return False
    if not VK_TOKEN:
        print("❌ VK_TOKEN не задан!")
        return False
    if not VK_CONFIRMATION_TOKEN:
        print("❌ VK_CONFIRMATION_TOKEN не задан!")
        return False
    return True