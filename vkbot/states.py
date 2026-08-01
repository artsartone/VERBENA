"""
Состояния FSM для VK бота.

Полностью соответствуют состояниям Telegram бота:
- START
- CATEGORY
- SERVICE
- MASTER
- DATE
- TIME
- NAME
- PHONE
- COMMENT
- CONFIRM
"""
from vkbottle import BaseStateGroup


class BookingState(BaseStateGroup):
    """Состояния для процесса записи."""

    # Главное меню (начало)
    START = "START"

    # Выбор категории услуги
    CATEGORY = "CATEGORY"

    # Выбор услуги
    SERVICE = "SERVICE"

    # Выбор мастера
    MASTER = "MASTER"

    # Выбор даты
    DATE = "DATE"

    # Выбор времени
    TIME = "TIME"

    # Ввод имени
    NAME = "NAME"

    # Ввод телефона
    PHONE = "PHONE"

    # Ввод комментария
    COMMENT = "COMMENT"

    # Подтверждение записи
    CONFIRM = "CONFIRM"

    # ─── Вакансии (трудоустройство) ───

    # Ввод имени
    CAREER_NAME = "CAREER_NAME"

    # Ввод телефона
    CAREER_PHONE = "CAREER_PHONE"

    # Опыт работы
    CAREER_EXPERIENCE = "CAREER_EXPERIENCE"

    # Резюме/портфолио
    CAREER_RESUME = "CAREER_RESUME"

    # Сопроводительное письмо
    CAREER_LETTER = "CAREER_LETTER"
