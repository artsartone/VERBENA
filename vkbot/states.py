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

    START = "START"

    CATEGORY = "CATEGORY"

    SERVICE = "SERVICE"

    MASTER = "MASTER"

    DATE = "DATE"

    TIME = "TIME"

    NAME = "NAME"

    PHONE = "PHONE"

    COMMENT = "COMMENT"

    CONFIRM = "CONFIRM"

    CAREER_NAME = "CAREER_NAME"

    CAREER_PHONE = "CAREER_PHONE"

    CAREER_EXPERIENCE = "CAREER_EXPERIENCE"

    CAREER_RESUME = "CAREER_RESUME"

    CAREER_LETTER = "CAREER_LETTER"
