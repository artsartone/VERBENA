"""
Конфигурация VK бота.

Переменные окружения:
- VK_GROUP_ID: ID сообщества VK
- BOT_TOKEN_VK: Токен бота VK
- VK_CONFIRMATION_TOKEN: Токен подтверждения для Callback API
"""
import os
from dotenv import load_dotenv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / "backend" / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)

VK_GROUP_ID = os.environ.get("VK_GROUP_ID", "")
BOT_TOKEN_VK = os.environ.get("BOT_TOKEN_VK", "")
VK_CONFIRMATION_TOKEN = os.environ.get("VK_CONFIRMATION_TOKEN", "")

API_BASE = os.environ.get("API_BASE", "http://localhost:5000")


def check_config() -> bool:
    """Проверить, что все необходимые переменные настроены."""
    if not VK_GROUP_ID:
        print("❌ VK_GROUP_ID не задан!")
        return False
    if not BOT_TOKEN_VK:
        print("❌ BOT_TOKEN_VK не задан!")
        return False
    if not VK_CONFIRMATION_TOKEN:
        print("❌ VK_CONFIRMATION_TOKEN не задан!")
        return False
    return True
