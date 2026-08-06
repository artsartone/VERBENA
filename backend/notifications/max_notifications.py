"""max_notifications.py — отправка уведомлений в MAX.

Симметрично telegram_notifications.py: только отправка, вызывается исключительно
из notification_service.py. Отдельный HTTP-клиент (а не импорт из
BeautyVerbenaBot_MAX.py), чтобы backend/app.py не тянул за собой весь polling-бот
как зависимость.
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

MAX_BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
MAX_API_BASE = os.environ.get("MAX_API_BASE", "https://platform-api2.max.ru")


def send_max_notification(user_id: str, text: str) -> bool:
    """Отправить одно текстовое уведомление. Возвращает True/False (не бросает)."""
    if not MAX_BOT_TOKEN:
        logger.error("BOT_TOKEN не задан — уведомление в MAX не отправлено")
        return False
    try:
        resp = requests.post(
            f"{MAX_API_BASE}/messages",
            params={"user_id": user_id},
            headers={"Authorization": MAX_BOT_TOKEN},
            json={
                "text": text,
                "format": "html"
            },
            timeout=10,
        )
        if resp.status_code != 200:
            logger.error(f"MAX POST /messages -> HTTP {resp.status_code}: "
                         f"{resp.text[:300]}")
            return False
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка отправки в MAX: {e}")
        return False
