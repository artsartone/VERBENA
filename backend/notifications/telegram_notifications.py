"""telegram_notifications.py — отправка уведомлений в Telegram.

Только отправка, никакой бизнес-логики и никакого чтения БД — это делает
notification_service.py. Не импортировать напрямую из app.py/бота записи,
только через notification_service.

Использует тот же BOT_TOKEN, что и BeautyVerbenaBot.py, но обращается к
Telegram Bot API напрямую (sendMessage), а не через сам процесс бота —
это позволяет слать уведомления из backend/app.py без межпроцессного вызова.
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
TELEGRAM_API_BASE = "https://api.telegram.org"


def send_telegram_notification(chat_id: str, text: str) -> bool:
    """Отправить одно текстовое уведомление. Возвращает True/False (не бросает)."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("BOT_TOKEN не задан — уведомление в Telegram не отправлено")
        return False
    try:
        resp = requests.post(
            f"{TELEGRAM_API_BASE}/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.error(f"Telegram sendMessage -> HTTP {resp.status_code}: "
                         f"{resp.text[:300]}")
            return False
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка отправки в Telegram: {e}")
        return False
