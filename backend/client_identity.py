"""client_identity.py — нормализация телефона и resolve/create client_id.

Единая точка входа для всех трёх поверхностей (сайт, Telegram, MAX):
  * get_or_create_client(conn, phone, display_name="") → client_id
  * normalize_phone(phone) → cleaned_phone (только цифры, без +, без лидирующей 7/8
    нормализации — храним как есть, но единообразно: только цифры, никаких
    +, -, пробелов, скобок).

Описанная в ТЗ "Идеальная архитектура": client_id — первичный ключ везде
(notification_links, notification_tokens, bookings.client_id), а phone —
внутренняя деталь resolve'а. Этот модуль — ровно та деталь.
"""

import re
import logging

logger = logging.getLogger(__name__)


def normalize_phone(phone: str) -> str:
    """Привести номер к цифровому виду: только digits, никаких +, -, скобок, пробелов.

    Примеры:
      "+7 (915) 526-50-56" → "79155265056"
      "8-915-526-50-56"    → "89155265056"
      "79155265056"        → "79155265056"
    """
    cleaned = re.sub(r"[^\d]", "", phone)
    if cleaned.startswith("7") or cleaned.startswith("8"):
        # Оставляем как есть — единообразно, без "лишней" 7/8 нормализации
        return cleaned
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    return cleaned


def get_or_create_client(conn, phone: str, display_name: str = "") -> int:
    """Найти client_id по нормализованному телефону, либо создать нового клиента.

    Возвращает client_id (int) — гарантированно существующую запись в таблице clients.
    """
    cleaned = normalize_phone(phone)
    if not cleaned.isdigit() or len(cleaned) < 10:
        raise ValueError(f"Некорректный номер телефона: {phone!r}")

    cur = conn.cursor()
    cur.execute("SELECT id FROM clients WHERE phone = ?", (cleaned,))
    row = cur.fetchone()
    if row is not None:
        client_id = row["id"] if hasattr(row, "__getitem__") else row[0]
        # Обновляем display_name, если передан непустой, а старый пустой
        if display_name:
            conn.execute(
                "UPDATE clients SET display_name = CASE "
                "  WHEN display_name = '' THEN ? ELSE display_name END, "
                "updated_at = datetime('now', '+3 hours') "
                "WHERE id = ?",
                (display_name, client_id),
            )
            conn.commit()
        return client_id

    # Создаём нового клиента
    cur.execute(
        "INSERT INTO clients (phone, display_name) VALUES (?, ?)",
        (cleaned, display_name or ""),
    )
    conn.commit()
    client_id = cur.lastrowid
    logger.info(f"Создан новый client_id={client_id} для телефона {cleaned}")
    return client_id