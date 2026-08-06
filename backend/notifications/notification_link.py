"""notification_link.py — одноразовые токены привязки уведомлений.

Используется в трёх местах:
  * backend/app.py       — при создании токена (после успешной записи на сайте)
  * BeautyVerbenaBot.py  — при получении "/start <token>" (Telegram)
  * BeautyVerbenaBot_MAX.py — при получении bot_started с payload=<token> (MAX)

Ничего не знает про телефон — только про client_id, который приходит извне.
Хранилище — sqlite3.Connection (или совместимый DB-API объект с execute/commit);
если в app.py используется SQLAlchemy, замените запросы на ORM-эквиваленты —
интерфейс функций (сигнатуры) можно оставить прежним.

⚠️ Это черновой модуль, написанный без доступа к вашей реальной схеме БД
(backend/app.py не был предоставлен на момент написания) — до интеграции
проверьте соответствие типов client_id, имя столбца и т.п.
"""

import logging
import secrets
import time

logger = logging.getLogger(__name__)

TOKEN_TTL_SECONDS = 15 * 60

TELEGRAM_BOT_USERNAME = "BeautyVerbenaBot"
MAX_BOT_USERNAME = "BeautyVerbenaBot"

PROVIDERS = ("telegram", "max")


def link_directly(db,
                  client_id: int,
                  provider: str,
                  provider_user_id: str,
                  provider_username: str = None) -> None:
    """Привязать провайдера к client_id напрямую, без одноразового токена.

    Используется только внутри самого бота (Telegram/MAX), когда пользователь
    нажимает "Получать уведомления" сразу после записи — в этот момент бот
    и так уже аутентифицировал отправителя как provider_user_id силами самой
    платформы (Telegram/MAX), так что токен как способ доказать "это тот же
    человек" здесь избыточен. Токен (create_token/redeem_token выше) остаётся
    нужен только для перехода сайт → бот, где такого прямого знания нет.
    """
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    db.execute(
        "INSERT INTO notification_links (client_id, provider, provider_user_id, provider_username) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(client_id, provider) DO UPDATE SET "
        "  provider_user_id = excluded.provider_user_id, "
        "  provider_username = excluded.provider_username, "
        "  updated_at = CURRENT_TIMESTAMP",
        (client_id, provider, provider_user_id, provider_username),
    )
    db.commit()
    logger.info(
        f"Уведомления {provider} напрямую привязаны к client_id={client_id}")


def create_token(db, client_id: int, provider: str) -> str:
    """Сгенерировать одноразовый токен для клиента и провайдера.
    Вызывается сайтом (после записи) перед показом кнопок Telegram/MAX."""
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")

    token = secrets.token_urlsafe(24)
    expires_at = time.time() + TOKEN_TTL_SECONDS
    db.execute(
        "INSERT INTO notification_tokens (client_id, provider, token, expires_at) "
        "VALUES (?, ?, ?, datetime(?, 'unixepoch'))",
        (client_id, provider, token, expires_at),
    )
    db.commit()
    return token


def build_deeplink(provider: str, token: str) -> str:
    """Собрать диплинк для кнопки на сайте."""
    if provider == "telegram":
        return f"https://t.me/{TELEGRAM_BOT_USERNAME}?start={token}"
    if provider == "max":
        return f"https://max.ru/{MAX_BOT_USERNAME}?start={token}"
    raise ValueError(f"unknown provider: {provider}")


def redeem_token(db,
                 token: str,
                 provider: str,
                 provider_user_id: str,
                 provider_username: str = None):
    """Погасить токен и создать/обновить запись в notification_links.

    Возвращает (client_id, None) при успехе, либо (None, причина_отказа):
    "not_found" | "already_used" | "expired" | "provider_mismatch".

    Вызывается из хендлера "/start <token>" (Telegram) или bot_started с
    payload=<token> (MAX) — см. TODO-заглушки в обоих файлах ботов.
    """
    row = db.execute(
        "SELECT client_id, provider, expires_at, used_at "
        "FROM notification_tokens WHERE token = ?",
        (token, ),
    ).fetchone()

    if row is None:
        logger.warning(f"Токен не найден: {token[:8]}...")
        return None, "not_found"

    client_id, token_provider, expires_at, used_at = row

    if token_provider != provider:
        logger.warning(f"Токен {token[:8]}... выписан для {token_provider}, "
                       f"а погашается через {provider}")
        return None, "provider_mismatch"

    if used_at is not None:
        return None, "already_used"

    cur = db.execute(
        "UPDATE notification_tokens SET used_at = CURRENT_TIMESTAMP "
        "WHERE token = ? AND used_at IS NULL AND expires_at > CURRENT_TIMESTAMP",
        (token, ),
    )
    if cur.rowcount == 0:
        db.commit()
        return None, "expired"

    db.execute(
        "INSERT INTO notification_links (client_id, provider, provider_user_id, provider_username) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(client_id, provider) DO UPDATE SET "
        "  provider_user_id = excluded.provider_user_id, "
        "  provider_username = excluded.provider_username, "
        "  updated_at = CURRENT_TIMESTAMP",
        (client_id, provider, provider_user_id, provider_username),
    )
    db.commit()
    logger.info(f"Уведомления {provider} привязаны к client_id={client_id}")
    return client_id, None


def is_linked(db, client_id: int, provider: str) -> bool:
    """Проверить, привязан ли уже этот провайдер у клиента (чтобы, как
    просили в ТЗ, не показывать повторно кнопку 'Подключить Telegram/MAX')."""
    row = db.execute(
        "SELECT 1 FROM notification_links WHERE client_id = ? AND provider = ?",
        (client_id, provider),
    ).fetchone()
    return row is not None


def unlink(db, client_id: int, provider: str) -> None:
    """Удалить привязку — после этого клиент может подключить провайдера заново."""
    db.execute(
        "DELETE FROM notification_links WHERE client_id = ? AND provider = ?",
        (client_id, provider),
    )
    db.commit()
