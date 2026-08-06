"""notification_service.py — единая точка входа для всех уведомлений.

Правило из ТЗ (раздел 5): "Все уведомления должны проходить только через
notification_service.py" — ни backend/app.py, ни BeautyVerbenaBot.py, ни
BeautyVerbenaBot_MAX.py не должны напрямую импортировать telegram_notifications
или max_notifications.

Использование (из любого из трёх мест: сайт, Telegram-бот, MAX-бот):

    from notification_service import notify_client
    notify_client(db, client_id=42, event="booking_confirmed", booking=booking_dict)

Логика независима от того, где создана запись — вызывающий код просто передаёт
client_id и данные записи.
"""

import logging

from max_notifications import send_max_notification
from telegram_notifications import send_telegram_notification

logger = logging.getLogger(__name__)


def _fmt_date(iso_date: str) -> str:
    parts = (iso_date or "").split("-")
    return f"{parts[2]}.{parts[1]}.{parts[0]}" if len(parts) == 3 else (
        iso_date or "")


def _tpl_booking_confirmed(b: dict) -> str:
    return (
        "✅ <b>Запись подтверждена</b>\n\n"
        f"💇‍♀️ {b.get('service', '')}\n"
        f"📅 {_fmt_date(b.get('booking_date', ''))} в {b.get('booking_time', '')}\n"
        + (f"👩‍🎨 Мастер: {b['assigned_employee_name']}\n"
           if b.get("assigned_employee_name") else "") +
        "\nЖдём вас в студии красоты VERBENA! 🌸")


def _tpl_booking_rescheduled(b: dict) -> str:
    return (
        "🔄 <b>Запись перенесена</b>\n\n"
        f"💇‍♀️ {b.get('service', '')}\n"
        f"📅 Новая дата: {_fmt_date(b.get('booking_date', ''))} в {b.get('booking_time', '')}"
    )


def _tpl_booking_cancelled(b: dict) -> str:
    return (
        "❌ <b>Запись отменена</b>\n\n"
        f"💇‍♀️ {b.get('service', '')}\n"
        f"📅 {_fmt_date(b.get('booking_date', ''))} в {b.get('booking_time', '')}\n\n"
        "Будем рады видеть вас снова 🌸")


def _tpl_booking_reminder(b: dict) -> str:
    return ("⏰ <b>Напоминание о записи</b>\n\n"
            f"💇‍♀️ {b.get('service', '')}\n"
            f"📅 Сегодня в {b.get('booking_time', '')}\n\n"
            "Ждём вас в студии красоты VERBENA! 🌸")


NOTIFICATION_TEMPLATES = {
    "booking_confirmed": _tpl_booking_confirmed,
    "booking_rescheduled": _tpl_booking_rescheduled,
    "booking_cancelled": _tpl_booking_cancelled,
    "booking_reminder": _tpl_booking_reminder,
}


def notify_client(db, client_id: int, event: str, booking: dict) -> dict:
    """Отправить уведомление клиенту во все привязанные им каналы.

    db — соединение с БД (см. notification_link.py про интерфейс).
    event — один из ключей NOTIFICATION_TEMPLATES.
    booking — словарь с полями записи (service, booking_date, booking_time,
              assigned_employee_name — опционально).

    Возвращает {"telegram": bool, "max": bool} только для тех провайдеров,
    что были реально привязаны у клиента (есть в notification_links). Если
    у клиента нет ни одной привязки — вернёт {} (не ошибка, п.3 ТЗ:
    "есть Telegram → отправить, есть MAX → отправить, есть оба → отправить
    в оба" — а если нет ни одного, просто ничего не делаем).
    """
    template = NOTIFICATION_TEMPLATES.get(event)
    if template is None:
        raise ValueError(f"unknown notification event: {event!r}. "
                         f"Известные: {list(NOTIFICATION_TEMPLATES)}")

    text = template(booking)

    links = db.execute(
        "SELECT provider, provider_user_id FROM notification_links WHERE client_id = ?",
        (client_id, ),
    ).fetchall()

    if not links:
        logger.info(
            f"У клиента {client_id} нет привязанных каналов уведомлений")
        return {}

    results = {}
    for provider, provider_user_id in links:
        if provider == "telegram":
            results["telegram"] = send_telegram_notification(
                provider_user_id, text)
        elif provider == "max":
            results["max"] = send_max_notification(provider_user_id, text)
        else:
            logger.warning(
                f"Неизвестный провайдер в notification_links: {provider}")

    failed = [p for p, ok in results.items() if not ok]
    if failed:
        logger.error(
            f"Не удалось отправить уведомление ({event}) client_id={client_id} "
            f"через: {', '.join(failed)}")

    return results
