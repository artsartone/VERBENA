"""
Общий модуль валидации данных.

Используется как Telegram, так и VK ботами для проверки:
- имени
- телефона
- комментария
"""
import re
from typing import Tuple, Optional


def validate_name(name: str) -> Tuple[bool, str]:
    """
    Проверить корректность имени.

    Args:
        name: Имя для проверки

    Returns:
        (True, "") если имя валидно
        (False, "сообщение об ошибке") если невалидно
    """
    if not name or len(name.strip()) < 2:
        return False, "Имя должно содержать минимум 2 символа"

    if not re.match(r"^[a-zA-Zа-яА-ЯёЁ\s\-']+$", name.strip()):
        return False, "Имя должно содержать только буквы"

    return True, ""


def validate_phone(phone: str) -> Tuple[bool, str]:
    """
    Проверить корректность номера телефона.

    Args:
        phone: Номер телефона для проверки

    Returns:
        (True, очищенный номер) если телефон валиден
        (False, "сообщение об ошибке") если невалидно
    """
    if not phone:
        return False, "Введите номер телефона"

    phone_clean = re.sub(r"[^\d+]", "", phone)

    digits_only = re.sub(r"\D", "", phone_clean)
    if len(digits_only) < 10:
        return False, "Неверный формат телефона (минимум 10 цифр)"

    return True, phone_clean


def validate_comment(comment: str) -> Tuple[bool, str]:
    """
    Проверить комментарий (опциональное поле).

    Args:
        comment: Текст комментария

    Returns:
        (True, текст) - комментарий всегда валиден (может быть пустым)
    """
    return True, comment.strip() if comment else ""


def format_phone_display(phone: str) -> str:
    """
    Отформатировать номер телефона для отображения.

    Пример: +79155265056 → +7 (915) 526-50-56
    """
    digits = re.sub(r"\D", "", phone)

    if len(digits) == 11 and digits.startswith("7"):
        return f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
    elif len(digits) >= 10:
        return f"+{digits[0]} ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"

    return phone
