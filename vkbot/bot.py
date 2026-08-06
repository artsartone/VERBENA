"""
VK Bot для студии красоты VERBENA.

Использует vkbottle для работы с VK API.
Полностью повторяет функционал Telegram бота.
"""
import asyncio
import logging
from pathlib import Path

from vkbottle.bot import Bot, Message

from .config import VK_TOKEN, VK_GROUP_ID, check_config, API_BASE
from .states import BookingState
from .handlers import bp as booking_bp
from vkbottle_types.methods.messages import MessagesSendPeerIdsResponse
from vkbottle_types.objects import MessagesSendUserIdsResponseItem

MessagesSendPeerIdsResponse.model_rebuild()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("vk_bot")


def main():
    """Запуск VK бота."""

    if not check_config():
        logger.critical("Конфигурация VK не завершена!\n"
                        "Установите переменные окружения:\n"
                        "  export VK_GROUP_ID=...\n"
                        "  export BOT_TOKEN_VK=...\n"
                        "  export VK_CONFIRMATION_TOKEN=...")
        raise SystemExit(1)

    logger.info("╭─────────────────────────────────────────────╮\n"
                f"│  VK Bot запускается                         │\n"
                f"│  GROUP_ID: {VK_GROUP_ID:<27} │\n"
                f"│  TOKEN: {VK_TOKEN[:8]}...{VK_TOKEN[-4:]:>10}  │\n"
                f"│  API_BASE: {API_BASE:<31} │\n"
                "╰─────────────────────────────────────────────╯")

    bot = Bot(token=VK_TOKEN)

    state_dispenser = bot.state_dispenser

    booking_bp.load(bot)

    from .cache import get_cache
    cache = get_cache(API_BASE)
    logger.info("Предзагрузка кэша YClients...")
    cache.refresh_cache()
    logger.info(f"Загружено: {len(cache.categories)} категорий, "
                f"{len(cache.services)} услуг, {len(cache.staff)} сотрудников")

    logger.info("Обработчики зарегистрированы. Запускаю polling...")

    try:
        bot.run_forever()
    except Exception as e:
        logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА при запуске: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()