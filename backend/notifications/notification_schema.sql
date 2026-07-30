-- Схема "уведомления по идентификатору клиента", без привязки к телефону
-- (см. обсуждение в ТЗ — токен указывает прямо на client_id, поэтому
-- телефон в этих двух таблицах не нужен).
--
-- client_id — это ID из таблицы clients (backend/app.py, clients.py),
-- которая теперь создаётся в init_db(). Phone — внутренняя деталь resolve'а
-- (client_identity.py), а не часть схемы уведомлений.
--
-- notification_links.client_id и notification_tokens.client_id —
-- внешние ключи к clients.id (FK не объявлены явно, т.к. sqlite не форсирует
-- их на REFERENCE в текущей конфигурации, но логически они связаны).

CREATE TABLE IF NOT EXISTS notification_links (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id           INTEGER NOT NULL,
    provider            TEXT NOT NULL CHECK (provider IN ('telegram', 'max')),
    provider_user_id    TEXT NOT NULL,      -- telegram chat_id или MAX user_id
    provider_username   TEXT,               -- опционально, для отображения в админке
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (provider, provider_user_id),     -- один telegram/max-аккаунт -> один клиент
    UNIQUE (client_id, provider)             -- один клиент -> один аккаунт на провайдера
);

CREATE INDEX IF NOT EXISTS idx_notification_links_client
    ON notification_links (client_id);

CREATE TABLE IF NOT EXISTS notification_tokens (
    token       TEXT PRIMARY KEY,           -- secrets.token_urlsafe(24)
    client_id   INTEGER NOT NULL,
    provider    TEXT NOT NULL CHECK (provider IN ('telegram', 'max')),
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at  TIMESTAMP NOT NULL,          -- created_at + 15 минут
    used_at     TIMESTAMP                    -- NULL, пока не погашен
);

CREATE INDEX IF NOT EXISTS idx_notification_tokens_client
    ON notification_tokens (client_id);
