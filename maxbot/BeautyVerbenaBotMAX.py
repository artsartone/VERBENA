#!/usr/bin/env python3
"""BeautyVerbenaBot (MAX) — бот студии красоты VERBENA для мессенджера MAX.

Порт с python-telegram-bot на чистый requests + MAX Bot API
(https://dev.max.ru/docs-api), long polling (GET /updates).

⚠️ Согласно документации MAX, long polling не предназначен для продакшена
   (ограничен по скорости и сроку хранения событий) — для прода нужно
   переходить на Webhook (POST /subscriptions). Сейчас оставлено на polling,
   т.к. так проще сравнивать с текущей структурой файла и деплоить так же.

MAX доступен из РФ напрямую — прокси по умолчанию не используется. Если он
всё же нужен (например, из-за сети хостинга), задайте MAX_API_PROXY:
  export MAX_API_PROXY="http://user:pass@host:3128"

Если requests падает с SSL-ошибкой на platform-api2.max.ru — скорее всего,
не хватает корневого сертификата Минцифры в доверенных. Либо установите его
в систему (см. https://github.com/BushlanovDev/max-bot-api-client-php#установка-сертификата),
либо укажите путь к .pem-бандлу через MAX_CA_BUNDLE.
"""

import json
import logging
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / "backend" / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    raise FileNotFoundError(f"Файл .env не найден: {ENV_PATH}")

import requests

# ─── Конфигурация ───

TOKEN = os.environ.get("BOT_TOKEN", "")
API_BASE = os.environ.get("API_BASE",
                          "http://localhost:5000")  # URL Flask-бэкенда

MAX_API_BASE = os.environ.get("MAX_API_BASE", "https://platform-api2.max.ru")

# ─── Прокси / TLS ───
# ВАЖНО: MAX — российский сервис, platform-api2.max.ru открыт напрямую из РФ.
# BOT_PROXY НЕ применяется к запросам в MAX API (в отличие от старой
# telegram-версии, где прокси был нужен именно из-за блокировки Telegram).
# Если он вам всё же нужен для MAX (например, из-за сети хостинга) —
# задайте отдельно MAX_API_PROXY. Backend (Flask, обычно localhost) прокси
# также не использует.
BOT_PROXY = os.environ.get("BOT_PROXY", "")  # зарезервировано, сейчас нигде не применяется
MAX_API_PROXY = os.environ.get("MAX_API_PROXY", "")  # опционально, обычно не нужен
MAX_CA_BUNDLE = os.environ.get("MAX_CA_BUNDLE", "")  # путь к .pem, опционально

# ─── Состояния "диалога" (используются вручную, без ConversationHandler) ───

(
    SELECT_SERVICE,
    SELECT_STAFF,
    SELECT_DATE,
    SELECT_TIME,
    ENTER_NAME,
    ENTER_PHONE,
    ENTER_COMMENT,
    CONFIRM_BOOKING,
) = range(8)

# ─── Время (статическое, если YClients не даст слоты) ───
TIME_SLOTS = [
    f"{h:02d}:{m:02d}" for h in range(10, 20) for m in range(0, 60, 15)
]

# ─── Услуги (статические, из index.html) ───
# Сначала пробуем загрузить из YClients, если не получается — используем эти.
SERVICES = [
    ("Маникюр с покрытием гель-лак", "1700–2700 ₽", "manicure"),
    ("Педикюр с покрытием гель-лак (только пальчики)", "1600–2100 ₽",
     "manicure"),
    ("Полный педикюр с покрытием гель-лак", "2500–3200 ₽", "manicure"),
    ("Полный педикюр с покрытием лаком", "2100–3200 ₽", "manicure"),
    ("Наращивание ногтей", "2700–3400 ₽", "manicure"),
    ("Маникюр (гигиена)", "1100–1500 ₽", "manicure"),
    ("Педикюр (гигиена стопы и ногтей без покрытия)", "2000–2600 ₽",
     "manicure"),
    ("Маникюр с покрытием гель-лак + укрепление", "1900 ₽", "manicure"),
    ("Маникюр с покрытием DIP-система", "1900–2200 ₽", "manicure"),
    ("Коррекция бровей (воск/пинцет)", "700 ₽", "brows"),
    ("Окрашивание + коррекция (хна/краска)", "1100 ₽", "brows"),
    ("Долговременная укладка бровей", "1600 ₽", "brows"),
    ("Удаление волос (1 зона)", "150 ₽", "brows"),
    ("Укладка (на брашинг)", "600–1200 ₽", "hair"),
    ("Тонирование волос", "4500–6000 ₽", "hair"),
    ("Окрашивание волос", "3700–6000 ₽", "hair"),
    ("Окрашивание корней", "2200–3500 ₽", "hair"),
    ("Вуаль (осветление по контуру)", "3500–6000 ₽", "hair"),
    ('Уход "Жизненная сила" от Lebel', "3000–4000 ₽", "hair"),
    ("Стрижка", "500–1000 ₽", "hair"),
]

# Категории: ключи без эмодзи для payload кнопок (эмодзи только для отображения)
CATEGORY_LABELS = [
    ("manicure", "💅 Маникюр"),
    ("brows", "✏️ Брови"),
    ("hair", "💇‍♀️ Парикмахерские"),
]


def services_in_category(cat_key: str):
    """Список (индекс в SERVICES, имя, цена) для заданной категории."""
    return [(i, name, price) for i, (name, price, cat) in enumerate(SERVICES)
            if cat == cat_key]


def load_yc_staff(service_id=None):
    """Load staff from YClients via backend proxy.

    If service_id is given, only staff assigned to that specific service are
    returned (backend must forward this to yclients_api.get_staff_for_booking()).
    """
    try:
        params = {"service_id": service_id} if service_id else {}
        resp = requests.get(f"{API_BASE}/api/yclients/staff",
                            params=params, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.warning(f"YClients staff load failed: {e}")
    return []


def load_yc_services():
    """Load services from YClients via backend proxy."""
    try:
        resp = requests.get(f"{API_BASE}/api/yclients/services", timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.warning(f"YClients services load failed: {e}")
    return []


def load_yc_categories():
    """Load service categories from YClients via backend proxy."""
    try:
        resp = requests.get(f"{API_BASE}/api/yclients/categories", timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.warning(f"YClients categories load failed: {e}")
    return []


# Cache for YClients data
_YC_STAFF_CACHE = []
_YC_SERVICES_CACHE = []
_YC_CATEGORIES_CACHE = []


def refresh_yc_cache():
    """Refresh YClients data cache (categories, services, staff)."""
    global _YC_STAFF_CACHE, _YC_SERVICES_CACHE, _YC_CATEGORIES_CACHE
    _YC_CATEGORIES_CACHE = load_yc_categories()
    _YC_SERVICES_CACHE = load_yc_services()
    _YC_STAFF_CACHE = load_yc_staff()


def yc_service_category_id(svc: dict):
    """Достать category_id из услуги YClients (как в modal.js: svc.category_id || svc.category.id)."""
    return svc.get("category_id") or (svc.get("category") or {}).get("id")


def yc_services_in_category(category_id):
    """Реальные услуги YClients для данной категории (как populateServices() в modal.js)."""
    cat_id_str = str(category_id)
    return [
        s for s in _YC_SERVICES_CACHE
        if str(yc_service_category_id(s) or "") == cat_id_str
    ]


def yc_price_label(svc: dict) -> str:
    """Строка цены вида '1700–2700 ₽' из price_min/price_max."""
    pmin = svc.get("price_min")
    pmax = svc.get("price_max")
    if pmin and pmax and pmin != pmax:
        return f"{int(pmin)}–{int(pmax)} ₽"
    if pmin:
        return f"{int(pmin)} ₽"
    return ""


# ─── Логирование ───

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Вспомогательные функции ───


def to_display_date(date_str: str) -> str:
    """ГГГГ-ММ-ДД → ДД.ММ.ГГГГ"""
    parts = date_str.split("-")
    if len(parts) == 3:
        return f"{parts[2]}.{parts[1]}.{parts[0]}"
    return date_str


def to_iso_date(date_str: str) -> str:
    """ДД.ММ.ГГГГ → ГГГГ-ММ-ДД"""
    parts = date_str.split(".")
    if len(parts) == 3 and len(parts[2]) == 4:
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return date_str


def get_max_user_id(update: dict) -> str:
    """Получить строковый user_id отправителя (сообщение или callback)."""
    if update.get("update_type") == "message_callback":
        return str(update.get("callback", {}).get("sender", {}).get("user_id", ""))
    message = update.get("message") or {}
    sender = message.get("sender") or update.get("user") or {}
    return str(sender.get("user_id", ""))


def format_booking(booking: dict) -> str:
    """Форматировать запись для отображения пользователю."""
    status_config = {
        "active": ("✅", "Подтверждена"),
        "pending": ("⏳", "Ожидает подтверждения"),
        "completed": ("✔️", "Завершена"),
        "cancelled": ("❌", "Отменена"),
    }
    status_raw = booking.get("status", "")
    emoji, status_ru = status_config.get(status_raw,
                                         ("❓", status_raw or "неизвестно"))
    date_display = to_display_date(booking.get("booking_date", ""))
    service = booking.get("service", "")
    time_ = booking.get("booking_time", "")
    master = booking.get("assigned_employee_name", "")

    lines = [
        f"📋 <b>Запись #{booking['id']}</b>",
        f"{emoji} <b>{status_ru}</b>",
        f"💇‍♀️ {service}",
        f"📅 {date_display} в {time_}",
    ]
    if master:
        lines.append(f"👩‍🎨 Мастер: {master}")
    # Телефон скрываем — пользователь знает свой номер
    return "\n".join(lines)


def get_max_proxy_config():
    """Вернуть словарь proxies для запросов к MAX API — только если явно
    задан MAX_API_PROXY. По умолчанию None (без прокси), т.к. MAX доступен
    из РФ напрямую."""
    if MAX_API_PROXY:
        return {"https": MAX_API_PROXY, "http": MAX_API_PROXY}
    return None


# ══════════════════════════════════════════════════════════════════════════
# ─── Слой MAX Bot API (замена python-telegram-bot) ───
# ══════════════════════════════════════════════════════════════════════════


def _max_verify():
    """Что передать в requests(verify=...) для сертификата Минцифры."""
    return MAX_CA_BUNDLE if MAX_CA_BUNDLE else True


def max_api_request(method: str, path: str, params=None, json_body=None,
                    timeout=15):
    """Низкоуровневый вызов MAX Bot API. Авторизация — заголовок Authorization
    БЕЗ префикса "Bearer" (важно: с ним запрос будет отклонён)."""
    headers = {"Authorization": TOKEN}
    url = f"{MAX_API_BASE}{path}"
    try:
        return requests.request(
            method,
            url,
            headers=headers,
            params=params,
            json=json_body,
            timeout=timeout,
            proxies=get_max_proxy_config(),
            verify=_max_verify(),
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка запроса к MAX API {method} {path}: {e}")
        return None


def btn(text: str, payload: str) -> dict:
    """Кнопка типа callback для inline_keyboard (аналог InlineKeyboardButton)."""
    return {"type": "callback", "text": text, "payload": payload}


def _build_attachments(keyboard):
    """keyboard — список рядов кнопок (список списков btn(...)), либо None."""
    if keyboard is None:
        return None
    return [{"type": "inline_keyboard", "payload": {"buttons": keyboard}}]


def send_message(user_id=None, chat_id=None, text="", keyboard=None,
                 fmt="html"):
    """POST /messages — отправить новое сообщение пользователю/в чат."""
    params = {}
    if user_id:
        params["user_id"] = user_id
    if chat_id:
        params["chat_id"] = chat_id
    body = {"text": text, "format": fmt}
    attachments = _build_attachments(keyboard)
    if attachments is not None:
        body["attachments"] = attachments
    resp = max_api_request("POST", "/messages", params=params, json_body=body)
    if resp is None or resp.status_code != 200:
        status = resp.status_code if resp is not None else "нет ответа"
        logger.error(f"send_message: HTTP {status} — "
                     f"{resp.text[:300] if resp is not None else ''}")
    return resp


def edit_message(message_id: str, text: str, keyboard=None, fmt="html"):
    """PUT /messages?message_id=... — отредактировать сообщение бота
    (кнопочные сообщения редактируются без ограничения по давности)."""
    body = {"text": text, "format": fmt}
    attachments = _build_attachments(keyboard)
    if attachments is not None:
        body["attachments"] = attachments
    resp = max_api_request("PUT", "/messages",
                           params={"message_id": message_id}, json_body=body)
    if resp is None or resp.status_code != 200:
        status = resp.status_code if resp is not None else "нет ответа"
        logger.error(f"edit_message: HTTP {status} — "
                     f"{resp.text[:300] if resp is not None else ''}")
    return resp


def answer_callback(callback_id: str, text: str = None, keyboard=None,
                    fmt="html", notification: str = None):
    """POST /answers?callback_id=... — ответ на нажатие кнопки.

    Если передан text, сообщение с кнопкой будет отредактировано ЭТИМ ЖЕ
    вызовом (отдельный edit_message не нужен — так и просили: без отдельного
    PUT). Если нужно одноразовое уведомление вместо/вместе с этим — notification.
    """
    body = {}
    if text is not None:
        msg = {"text": text, "format": fmt}
        attachments = _build_attachments(keyboard)
        if attachments is not None:
            msg["attachments"] = attachments
        body["message"] = msg
    if notification is not None:
        body["notification"] = notification
    resp = max_api_request("POST", "/answers",
                           params={"callback_id": callback_id}, json_body=body)
    if resp is None or resp.status_code != 200:
        status = resp.status_code if resp is not None else "нет ответа"
        logger.error(f"answer_callback: HTTP {status} — "
                     f"{resp.text[:300] if resp is not None else ''}")
    return resp


def get_updates(marker=None, timeout=25, limit=100):
    """GET /updates — long polling (только для разработки/тестов, см. шапку файла)."""
    params = {"timeout": timeout, "limit": limit}
    if marker is not None:
        params["marker"] = marker
    return max_api_request("GET", "/updates", params=params,
                           timeout=timeout + 15)


# ══════════════════════════════════════════════════════════════════════════
# ─── Хранилище состояния "диалога" (замена ConversationHandler) ───
# ══════════════════════════════════════════════════════════════════════════

# user_id (str) -> {"state": int, "data": {...}}  — простой in-memory стор.
# Как и в оригинале (persistent=False), при перезапуске бота сессии теряются —
# отсюда и оставлены все проверки "эта кнопка устарела" ниже.
SESSIONS: dict = {}


def get_session(user_id: str) -> dict:
    return SESSIONS.setdefault(user_id, {"state": None, "data": {}})


def set_state(user_id: str, state):
    get_session(user_id)["state"] = state


def get_state(user_id: str):
    return SESSIONS.get(user_id, {}).get("state")


def user_data(user_id: str) -> dict:
    return get_session(user_id)["data"]


def clear_session(user_id: str):
    SESSIONS.pop(user_id, None)


def send_notifications(booking_data: dict):
    """Отправить уведомления всем сотрудникам с notify_enabled=1.

    ⚠️ ПЕРЕНОС С TELEGRAM, ТРЕБУЕТ ВНИМАНИЯ БЭКЕНДА:
    Эндпоинт /api/telegram/notify-users исторически возвращает записи с полем
    "telegram_id". Ниже это поле используется как есть (т.е. как generic ID
    мессенджера) — если бэкенд физически хранит только Telegram ID, эти
    уведомления в MAX слать будет некому, пока бэкенд не начнёт сохранять
    также MAX user_id (например, в том же поле или в отдельном max_id).
    Как и в оригинале, сейчас эта функция никем не вызывается: бэкенд сам
    рассылает уведомления при создании записи (см. confirm_booking).
    """
    try:
        resp = requests.get(f"{API_BASE}/api/telegram/notify-users", timeout=15)
        if resp.status_code != 200:
            logger.info(f"notify-users вернул {resp.status_code}, пропускаем")
            return
        users = resp.json()
        if not users:
            logger.info("Нет пользователей с notify_enabled=1")
            return

        date_display = to_display_date(booking_data.get("booking_date", ""))
        message = (
            "📢 <b>Новая запись!</b>\n\n"
            f"👤 Клиент: {booking_data.get('client_name', '')}\n"
            f"💇‍♀️ Услуга: {booking_data.get('service', '')}\n"
            f"📅 Дата: {date_display}\n"
            f"⏰ Время: {booking_data.get('booking_time', '')}\n"
            f"📞 Телефон: {booking_data.get('client_phone', '')}\n\n"
            "🔗 <a href='https://beauty-verbena.ru/admin'>Управлять записями Verbena</a>"
        )

        for user in users:
            max_id = str(user.get("telegram_id", "")).strip()
            if not max_id or not max_id.isdigit():
                continue
            resp2 = send_message(user_id=int(max_id), text=message)
            if resp2 is None or resp2.status_code != 200:
                logger.error(f"Ошибка отправки уведомления {max_id}")
            else:
                logger.info(f"Уведомление отправлено пользователю {max_id}")
    except Exception as e:
        logger.error(f"Ошибка получения списка уведомляемых: {e}")


# ─── Команда /start ───

MAIN_MENU_TEXT = (
    "🌸 <b>Добро пожаловать в VERBENA — студию красоты!</b>\n\n"
    "Здесь вы можете записаться на услуги, посмотреть свои записи "
    "и узнать больше о нашей студии.\n\n"
    "📍 г. Строитель, ул. Октябрьская, 15\n"
    "🕐 Ежедневно 10:00–20:00\n"
    "📞 +7 (915) 526-50-56\n\n"
    "<i>Выберите действие:</i>")

MAIN_MENU_KEYBOARD = [
    [btn("📅 Записаться на услугу", "book")],
    [btn("📋 Мои записи", "my_bookings")],
    [btn("💇‍♀️ Услуги и цены", "services")],
    [btn("📍 Контакты", "contacts")],
]


def start(user_id: str) -> None:
    """Приветствие и главное меню (по /start или событию bot_started)."""
    clear_session(user_id)
    send_message(user_id=int(user_id), text=MAIN_MENU_TEXT,
                keyboard=MAIN_MENU_KEYBOARD)


# ─── Главное меню (обработчик кнопок) ───


def show_main_menu(callback_id: str) -> None:
    """Показать главное меню (из callback)."""
    answer_callback(callback_id, text=MAIN_MENU_TEXT,
                    keyboard=MAIN_MENU_KEYBOARD)


def main_menu_callback(user_id: str, callback_id: str, payload: str) -> None:
    """Обработчик нажатий кнопок главного меню."""
    if payload == "book":
        show_categories(user_id, callback_id)
    elif payload == "my_bookings":
        show_my_bookings(user_id, callback_id)
    elif payload == "services":
        show_services(callback_id)
    elif payload == "contacts":
        show_contacts(callback_id)
    elif payload == "back_to_categories":
        show_categories(user_id, callback_id)
    elif payload == "back_to_menu":
        exit_booking_to_main_menu(user_id, callback_id)


def exit_booking_to_main_menu(user_id: str, callback_id: str) -> None:
    """«В меню» — показываем меню и завершаем текущий сценарий записи."""
    show_main_menu(callback_id)
    clear_session(user_id)


def show_my_bookings(user_id: str, callback_id: str) -> None:
    """Показать записи, привязанные к user_id (в MAX — по тому же принципу,
    что telegram_id в оригинале — см. предупреждение в send_notifications)."""
    try:
        resp = requests.get(
            f"{API_BASE}/api/telegram/my-bookings",
            params={"telegram_id": user_id},
            timeout=10,
        )
        bookings = resp.json() if resp.status_code == 200 else []
    except Exception as e:
        logger.error(f"Ошибка получения записей по user_id: {e}")
        bookings = []

    if not bookings:
        text = ("😔 У вас нет активных записей.\n\n"
                "Возможные причины:\n"
                "• Вы ещё не записывались через этого бота\n"
                "• Все записи завершены или отменены\n\n"
                "<i>Записи показываются только по тем номерам телефона, "
                "которые вы указали при записи через этого бота.</i>")
        keyboard = [
            [btn("📅 Записаться", "book")],
            [btn("◀️ В меню", "back_to_menu")],
        ]
        answer_callback(callback_id, text=text, keyboard=keyboard)
    else:
        text = f"📋 <b>Ваши записи: {len(bookings)}</b>\n\n"
        cancel_buttons = []
        for b in bookings:
            text += f"{format_booking(b)}\n\n"
            if b.get("status") in ("active", "pending"):
                cancel_buttons.append([
                    btn(f"❌ Отменить запись #{b['id']}", f"cancel_{b['id']}")
                ])

        keyboard = cancel_buttons + [
            [btn("📅 Новая запись", "book")],
            [btn("◀️ В меню", "back_to_menu")],
        ]
        answer_callback(callback_id, text=text, keyboard=keyboard)


def show_categories(user_id: str, callback_id: str) -> None:
    """Показать категории услуг.

    Сначала пробуем реальные категории/услуги из YClients (как loadYClientsData()
    в modal.js на сайте). Если YClients недоступен или список пуст — используем
    статический CATEGORY_LABELS/SERVICES как раньше.
    """
    refresh_yc_cache()

    keyboard = []
    if _YC_CATEGORIES_CACHE and _YC_SERVICES_CACHE:
        for cat in _YC_CATEGORIES_CACHE:
            cat_id = cat.get("id")
            title = cat.get("title") or "Услуги"
            if cat_id is None or not yc_services_in_category(cat_id):
                continue
            keyboard.append([btn(title, f"cat_{cat_id}")])

    if not keyboard:
        # Fallback: статический список категорий
        for key, display_name in CATEGORY_LABELS:
            keyboard.append([btn(display_name, f"cat_{key}")])

    keyboard.append([btn("◀️ Назад", "back_to_menu")])
    set_state(user_id, SELECT_SERVICE)
    answer_callback(callback_id, text="Выберите категорию услуги:",
                    keyboard=keyboard)


def show_services(callback_id: str) -> None:
    """Показать все услуги с ценами."""
    text = "💇‍♀️ <b>Наши услуги и цены</b>\n\n"
    for key, display_name in CATEGORY_LABELS:
        text += f"<b>{display_name}</b>\n"
        for _, service_name, price in services_in_category(key):
            text += f"  • {service_name} — <i>{price}</i>\n"
        text += "\n"

    text += "\n<i>Чтобы записаться, нажмите «Записаться на услугу» в меню.</i>"
    keyboard = [[btn("◀️ В меню", "back_to_menu")]]
    answer_callback(callback_id, text=text, keyboard=keyboard)


def show_contacts(callback_id: str) -> None:
    """Показать контактную информацию."""
    text = ("📍 <b>Студия красоты VERBENA</b>\n\n"
            "🏠 <b>Адрес:</b> г. Строитель, ул. Октябрьская, 15\n"
            "🕐 <b>Режим работы:</b> Ежедневно 10:00–20:00\n"
            "📞 <b>Телефон:</b> +7 (915) 526-50-56\n\n"
            "🌐 <b>Мы в соцсетях:</b>\n"
            "• ВКонтакте: vk.ru/verbena.studio31\n"
            "• Telegram: @verbenastudio31")
    keyboard = [[btn("◀️ В меню", "back_to_menu")]]
    answer_callback(callback_id, text=text, keyboard=keyboard)


# ─── Отмена записи ───


def notify_max_callback(user_id: str, callback_id: str, payload: str) -> None:
    """Пользователь нажал «Получать уведомления» в MAX боте."""
    client_id = payload.replace("notify_max_", "")
    try:
        resp = requests.post(
            f"{API_BASE}/api/notifications/link-direct",
            json={
                "client_id": int(client_id),
                "provider": "max",
                "provider_user_id": user_id,
            },
            timeout=10,
        )
        ok = resp.status_code == 200
    except Exception as e:
        logger.error(f"Ошибка привязки уведомлений (max): {e}")
        ok = False

    text = "🔔 Уведомления подключены!" if ok else "⚠️ Не удалось подключить уведомления."
    answer_callback(callback_id, text=text,
                    keyboard=[[btn("◀️ В меню", "back_to_menu")]])


def cancel_booking_callback(callback_id: str, payload: str) -> None:
    """Отменить запись (через публичный эндпоинт)."""
    booking_id = payload.replace("cancel_", "")
    try:
        resp = requests.post(f"{API_BASE}/api/bookings/{booking_id}/cancel",
                             timeout=10)
        if resp.status_code == 200:
            answer_callback(
                callback_id,
                text=(f"✅ Запись #{booking_id} успешно отменена.\n\n"
                     "Если захотите записаться снова — мы будем рады! 🌸"),
                keyboard=[
                    [btn("📅 Записаться снова", "book")],
                    [btn("◀️ В меню", "back_to_menu")],
                ],
            )
        else:
            answer_callback(
                callback_id,
                text="❌ Не удалось отменить запись. Попробуйте позже.",
                keyboard=[[btn("◀️ В меню", "back_to_menu")]],
            )
    except Exception as e:
        logger.error(f"Ошибка отмены записи: {e}")
        answer_callback(callback_id, text="❌ Ошибка соединения. Попробуйте позже.")


# ─── Процесс записи на услугу ───


def category_callback(user_id: str, callback_id: str, payload: str) -> None:
    """Выбор услуги из категории."""
    cat_key = payload.replace("cat_", "")

    # ─── Реальная категория YClients (id совпадает с одной из закэшированных) ───
    yc_category = None
    if _YC_CATEGORIES_CACHE:
        for cat in _YC_CATEGORIES_CACHE:
            if str(cat.get("id")) == cat_key:
                yc_category = cat
                break

    keyboard = []
    if yc_category is not None:
        display_name = yc_category.get("title") or "Услуги"
        real_services = yc_services_in_category(yc_category["id"])
        for svc in real_services:
            price = yc_price_label(svc)
            label = f"{svc.get('title', 'Услуга')}" + (f" — {price}" if price else "")
            keyboard.append([btn(label, f"svc_{svc['id']}")])
    else:
        # ─── Fallback: статический список (старое поведение) ───
        display_name = dict(CATEGORY_LABELS).get(cat_key)
        services = services_in_category(cat_key)
        if display_name is None or not services:
            answer_callback(callback_id, text="❌ Ошибка: категория не найдена")
            return
        for idx, service_name, price in services:
            label = f"{service_name} — {price}"
            keyboard.append([btn(label, f"svc_{idx}")])

    keyboard.append([btn("◀️ Назад к категориям", "back_to_categories")])

    set_state(user_id, SELECT_SERVICE)
    answer_callback(callback_id, text=f"<b>{display_name}</b>\n\nВыберите услугу:",
                    keyboard=keyboard)


def back_to_categories(user_id: str, callback_id: str) -> None:
    """Вернуться к категориям."""
    show_categories(user_id, callback_id)


def service_selected(user_id: str, callback_id: str, payload: str) -> None:
    """Услуга выбрана — запрашиваем мастера (если есть в YClients), иначе дату."""
    raw = payload.replace("svc_", "")
    data = user_data(user_id)

    # ─── Реальная услуга YClients (id совпадает с закэшированной) ───
    yc_service = None
    if _YC_SERVICES_CACHE:
        for svc in _YC_SERVICES_CACHE:
            if str(svc.get("id")) == raw:
                yc_service = svc
                break

    if yc_service is not None:
        service_name = yc_service.get("title", "Услуга")
        data["service"] = service_name
        data["yclients_service_id"] = yc_service["id"]
        # Мастера, реально привязанные именно к этой услуге —
        # запрашиваем отдельно через /book_staff (свежий запрос, не кэш).
        staff = load_yc_staff(service_id=yc_service["id"])
    else:
        # ─── Fallback: статический список услуг (старое поведение) ───
        try:
            service_name, price, _ = SERVICES[int(raw)]
        except (ValueError, IndexError):
            # Устаревшая/повреждённая кнопка (например, после перезапуска бота).
            answer_callback(callback_id,
                            text="❌ Эта кнопка устарела. Пожалуйста, начните запись заново: /start")
            clear_session(user_id)
            return

        data["service"] = service_name
        data.pop("yclients_service_id", None)
        staff = _YC_STAFF_CACHE

    if staff:
        keyboard = []
        for s in staff:
            name = s.get("name", "Мастер")
            spec = s.get("specialization", "")
            label = f"{name}" + (f" ({spec})" if spec else "")
            keyboard.append([btn(label, f"staff_{s['id']}")])
        keyboard.append([btn("🤷 Любой мастер", "staff_0")])
        keyboard.append([btn("◀️ Назад", "back_to_categories")])

        set_state(user_id, SELECT_STAFF)
        answer_callback(
            callback_id,
            text=(f"💇‍♀️ <b>Услуга:</b> {service_name}\n\n"
                 "👩‍🎨 Выберите мастера (или «Любой мастер»):"),
            keyboard=keyboard,
        )
    else:
        # No YClients staff, go directly to date selection
        _show_date_selection(user_id, callback_id, service_name)


def _show_date_selection(user_id: str, callback_id: str, service_name: str) -> None:
    """Show date selection after service (and optionally staff) selected."""
    today = date.today()
    keyboard = []
    row = []
    for i in range(14):
        d = today + timedelta(days=i)
        label = d.strftime("%d.%m")
        day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d.weekday()]
        btn_text = f"{label} ({day_name})"
        payload = f"date_{d.strftime('%d.%m.%Y')}"
        row.append(btn(btn_text, payload))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([btn("◀️ Назад", "back_to_categories")])

    set_state(user_id, SELECT_DATE)
    answer_callback(
        callback_id,
        text=(f"💇‍♀️ <b>Услуга:</b> {service_name}\n\n"
             "📅 Выберите удобную дату:"),
        keyboard=keyboard,
    )


def staff_selected(user_id: str, callback_id: str, payload: str) -> None:
    """Staff selected — go to date selection."""
    data = user_data(user_id)
    staff_id = payload.replace("staff_", "")
    if staff_id and staff_id != "0":
        data["yclients_staff_id"] = staff_id
        for s in _YC_STAFF_CACHE:
            if str(s["id"]) == staff_id:
                data["assigned_employee_name"] = s.get("name", "Мастер")
                break
    else:
        data["yclients_staff_id"] = ""
        data["assigned_employee_name"] = ""

    service_name = data.get("service", "")
    _show_date_selection(user_id, callback_id, service_name)


def date_selected(user_id: str, callback_id: str, payload: str) -> None:
    """Дата выбрана — загружаем свободное время."""
    data = user_data(user_id)
    if "service" not in data:
        # Кнопка из старого/просроченного диалога (диалоги не persistent).
        answer_callback(callback_id,
                        text="❌ Эта кнопка устарела. Пожалуйста, начните запись заново: /start")
        clear_session(user_id)
        return

    date_str = payload.replace("date_", "")
    data["date"] = date_str

    iso_date = to_iso_date(date_str)
    yc_staff_id = data.get("yclients_staff_id", "")
    yc_service_id = data.get("yclients_service_id", "")
    available_slots = []
    try:
        if yc_staff_id and yc_service_id and _YC_SERVICES_CACHE:
            resp = requests.get(
                f"{API_BASE}/api/yclients/available-times",
                params={
                    "service_id": yc_service_id,
                    "staff_id": yc_staff_id,
                    "date": iso_date,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                slots = resp.json()
                if isinstance(slots, list) and len(slots) > 0:
                    if isinstance(slots[0], str):
                        available_slots = slots
                    elif isinstance(slots[0], dict):
                        available_slots = [s["time"] for s in slots if s.get("available", True)]
        else:
            resp = requests.get(
                f"{API_BASE}/api/available-times",
                params={"date": iso_date},
                timeout=10,
            )
            if resp.status_code == 200:
                slots = resp.json()
                available_slots = [s["time"] for s in slots if s["available"]]
    except Exception:
        available_slots = available_slots or []

    # If no slots from API, use static list (only as last resort)
    if not available_slots:
        available_slots = TIME_SLOTS

    if not available_slots:
        keyboard = [[btn("◀️ Выбрать другую дату", "back_to_date")]]
        answer_callback(
            callback_id,
            text=("😔 На эту дату нет свободного времени.\n"
                 "Пожалуйста, выберите другую дату."),
            keyboard=keyboard,
        )
        return

    keyboard = []
    row = []
    for slot in available_slots:
        row.append(btn(slot, f"time_{slot}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([btn("◀️ Назад к дате", "back_to_date")])

    set_state(user_id, SELECT_TIME)
    answer_callback(
        callback_id,
        text=(f"💇‍♀️ <b>Услуга:</b> {data['service']}\n"
             f"📅 <b>Дата:</b> {date_str}\n\n"
             "⏰ Выберите время:"),
        keyboard=keyboard,
    )


def back_to_date(user_id: str, callback_id: str) -> None:
    """Вернуться к выбору даты."""
    data = user_data(user_id)
    service_name = data.get("service", "")
    data.pop("date", None)

    today = date.today()
    keyboard = []
    row = []
    for i in range(14):
        d = today + timedelta(days=i)
        label = d.strftime("%d.%m")
        day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d.weekday()]
        btn_text = f"{label} ({day_name})"
        payload = f"date_{d.strftime('%d.%m.%Y')}"
        row.append(btn(btn_text, payload))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([btn("◀️ Назад", "back_to_categories")])

    set_state(user_id, SELECT_DATE)
    answer_callback(
        callback_id,
        text=(f"💇‍♀️ <b>Услуга:</b> {service_name}\n\n"
             "📅 Выберите удобную дату:"),
        keyboard=keyboard,
    )


def time_selected(user_id: str, callback_id: str, payload: str) -> None:
    """Время выбрано — запрашиваем имя."""
    data = user_data(user_id)
    if "service" not in data or "date" not in data:
        answer_callback(callback_id,
                        text="❌ Эта кнопка устарела. Пожалуйста, начните запись заново: /start")
        clear_session(user_id)
        return

    time_str = payload.replace("time_", "")
    data["time"] = time_str

    set_state(user_id, ENTER_NAME)
    answer_callback(
        callback_id,
        text=(f"💇‍♀️ <b>Услуга:</b> {data['service']}\n"
             f"📅 <b>Дата:</b> {data['date']}\n"
             f"⏰ <b>Время:</b> {time_str}\n\n"
             "👤 Введите ваше имя:"),
    )


def name_received(user_id: str, text: str) -> None:
    """Имя получено — запрашиваем телефон."""
    name = text.strip()
    if not name or len(name) < 2:
        send_message(user_id=int(user_id),
                    text="❌ Пожалуйста, введите корректное имя (минимум 2 символа).")
        return  # остаёмся в ENTER_NAME

    user_data(user_id)["name"] = name

    send_message(
        user_id=int(user_id),
        text=(f"👤 <b>Имя:</b> {name}\n\n"
             "📞 Введите ваш номер телефона для связи.\n"
             "Например: <code>+79155265056</code>"),
    )
    set_state(user_id, ENTER_PHONE)


def phone_received(user_id: str, text: str) -> None:
    """Телефон получен — показываем подтверждение."""
    phone = text.strip()
    phone_clean = re.sub(r"[^\d+]", "", phone)
    if not phone_clean or len(phone_clean) < 10:
        send_message(
            user_id=int(user_id),
            text=("❌ Пожалуйста, введите корректный номер телефона.\n"
                 "Например: <code>+79155265056</code>"),
        )
        return  # остаёмся в ENTER_PHONE

    data = user_data(user_id)
    data["phone"] = phone_clean

    keyboard = [[btn("⏭️ Пропустить", "skip_comment")]]
    send_message(
        user_id=int(user_id),
        text=(f"👤 <b>Имя:</b> {data['name']}\n"
             f"📞 <b>Телефон:</b> {phone_clean}\n\n"
             "💬 Если хотите, оставьте комментарий к записи\n"
             "(или нажмите «Пропустить»):"),
        keyboard=keyboard,
    )
    set_state(user_id, ENTER_COMMENT)


def comment_received(user_id: str, text: str) -> None:
    """Comment received (текстом) — show confirmation."""
    user_data(user_id)["comment"] = text.strip()
    _show_confirmation(user_id, via_callback_id=None)


def skip_comment(user_id: str, callback_id: str) -> None:
    """Skip comment (кнопкой) — show confirmation."""
    user_data(user_id)["comment"] = ""
    _show_confirmation(user_id, via_callback_id=callback_id)


def _confirmation_text(user_id: str) -> str:
    data = user_data(user_id)
    phone = data.get("phone", "")
    comment = data.get("comment", "")

    summary = ("📋 <b>Проверьте данные записи:</b>\n\n"
              f"💇‍♀️ <b>Услуга:</b> {data['service']}\n"
              f"📅 <b>Дата:</b> {data['date']}\n"
              f"⏰ <b>Время:</b> {data['time']}\n"
              f"👤 <b>Имя:</b> {data['name']}\n"
              f"📞 <b>Телефон:</b> {phone}\n")

    master = data.get("assigned_employee_name", "")
    if master:
        summary += f"👩‍🎨 <b>Мастер:</b> {master}\n"
    if comment:
        summary += f"💬 <b>Комментарий:</b> {comment}\n"
    summary += "\nВсё верно?"
    return summary


def _show_confirmation(user_id: str, via_callback_id: str = None) -> None:
    """Show booking confirmation — либо новым сообщением (после текста),
    либо редактированием (после кнопки «Пропустить»)."""
    keyboard = [[
        btn("✅ Подтвердить", "confirm_yes"),
        btn("❌ Отменить", "confirm_no"),
    ]]
    summary = _confirmation_text(user_id)
    set_state(user_id, CONFIRM_BOOKING)
    if via_callback_id:
        answer_callback(via_callback_id, text=summary, keyboard=keyboard)
    else:
        send_message(user_id=int(user_id), text=summary, keyboard=keyboard)


def confirm_booking(user_id: str, callback_id: str, payload: str) -> None:
    """Подтверждение записи — отправка в API."""
    if payload == "confirm_no":
        answer_callback(
            callback_id,
            text=("❌ Запись отменена.\n\n"
                 "Если захотите записаться — нажмите /start"),
            keyboard=[[btn("◀️ В меню", "back_to_menu")]],
        )
        clear_session(user_id)
        return

    data = user_data(user_id)
    iso_date = to_iso_date(data["date"])
    phone = data["phone"]
    comment = data.get("comment", "")
    staff_id = data.get("yclients_staff_id", "")
    master_name = data.get("assigned_employee_name", "")
    yc_service_id = data.get("yclients_service_id", "")

    payload_body = {
        "client_name": data["name"],
        "client_phone": phone,
        "service": data["service"],
        "booking_date": iso_date,
        "booking_time": data["time"],
        "comment": comment,
    }
    if yc_service_id:
        payload_body["yclients_service_id"] = yc_service_id
    if staff_id:
        payload_body["yclients_staff_id"] = staff_id
    if master_name:
        payload_body["assigned_employee_name"] = master_name
    # Бот уже сам отправляет сообщение клиенту — не дублируем через notify_client
    payload_body["no_notify"] = True

    try:
        resp = requests.post(f"{API_BASE}/api/bookings", json=payload_body,
                             timeout=15)

        if resp.status_code == 201:
            resp_json = resp.json()
            booking_id = resp_json.get("id", "—")
            client_id = resp_json.get("client_id")

            # Привязка телефона к user_id (см. предупреждение в send_notifications
            # про поле telegram_id — переносится "как есть")
            try:
                requests.post(
                    f"{API_BASE}/api/telegram/link-phone",
                    json={
                        "telegram_id": user_id,
                        "phone": phone,
                        "client_name": data["name"],
                    },
                    timeout=10,
                )
            except Exception as e:
                logger.error(f"Ошибка привязки телефона: {e}")

            # Бэкенд сам отправит уведомления при создании записи (status 201) —
            # ручную рассылку send_notifications() здесь не вызываем, чтобы
            # сотрудники не получили двойное сообщение.

            # Build keyboard with optional notification button
            keyboard = [
                [btn("📋 Мои записи", "my_bookings")],
                [btn("◀️ В меню", "back_to_menu")],
            ]
            if client_id:
                try:
                    status_resp = requests.get(
                        f"{API_BASE}/api/notifications/status",
                        params={"client_id": client_id, "provider": "max"},
                        timeout=5,
                    )
                    already_linked = status_resp.ok and status_resp.json().get("linked")
                except Exception:
                    already_linked = False
                if not already_linked:
                    keyboard.insert(0, [
                        btn("🔔 Получать уведомления о записи", f"notify_max_{client_id}")
                    ])

            answer_callback(
                callback_id,
                text=("✅ <b>Запись успешно создана!</b> 🌸\n\n"
                     f"📋 Номер записи: <b>#{booking_id}</b>\n"
                     f"💇‍♀️ Услуга: {data['service']}\n"
                     f"📅 Дата: {data['date']}\n"
                     f"⏰ Время: {data['time']}\n\n"
                     "Ждём вас в студии красоты VERBENA! 💅\n\n"
                     "<i>Вы можете посмотреть свои записи в любое время через "
                     "главное меню.</i>"),
                keyboard=keyboard,
            )
        elif resp.status_code == 409:
            answer_callback(
                callback_id,
                text=("❌ К сожалению, это время уже занято.\n\n"
                     "Пожалуйста, попробуйте выбрать другое время или дату."),
                keyboard=[
                    [btn("🔄 Выбрать другое время", "book")],
                    [btn("◀️ В меню", "back_to_menu")],
                ],
            )
        else:
            error_msg = resp.json().get("error", "Неизвестная ошибка")
            answer_callback(
                callback_id,
                text=(f"❌ Ошибка при создании записи: {error_msg}\n\n"
                     "Пожалуйста, попробуйте позже или запишитесь по телефону +7 (915) 526-50-56"),
                keyboard=[[btn("◀️ В меню", "back_to_menu")]],
            )
    except Exception as e:
        logger.error(f"Ошибка создания записи: {e}")
        answer_callback(
            callback_id,
            text=("❌ Ошибка соединения с сервером.\n\n"
                 "Пожалуйста, попробуйте позже или запишитесь по телефону:\n"
                 "📞 +7 (915) 526-50-56"),
            keyboard=[[btn("◀️ В меню", "back_to_menu")]],
        )

    clear_session(user_id)


def cancel_dialog(user_id: str) -> None:
    """Отмена диалога (команда /cancel)."""
    send_message(user_id=int(user_id),
                text="❌ Диалог прерван. Чтобы начать заново, нажмите /start")
    clear_session(user_id)


# ─── Обработчик обычных сообщений (не в диалоге) ───


def handle_free_text(user_id: str, text: str) -> None:
    """Ответ на любые сообщения вне диалога записи."""
    text_l = text.lower()

    if "запис" in text_l:
        start(user_id)
    elif "услуг" in text_l or "цен" in text_l:
        send_message(
            user_id=int(user_id),
            text=("💇‍♀️ Чтобы посмотреть услуги и цены, нажмите /start и выберите "
                 "«Услуги и цены»."),
        )
    elif "контакт" in text_l or "адрес" in text_l:
        send_message(
            user_id=int(user_id),
            text=("📍 <b>Студия красоты VERBENA</b>\n"
                 "🏠 г. Строитель, ул. Октябрьская, 15\n"
                 "🕐 Ежедневно 10:00–20:00\n"
                 "📞 +7 (915) 526-50-56"),
        )
    else:
        send_message(
            user_id=int(user_id),
            text=("🌸 Я бот студии красоты VERBENA.\n"
                 "Используйте /start, чтобы открыть меню."),
        )


# ══════════════════════════════════════════════════════════════════════════
# ─── Диспетчер обновлений ───
# ══════════════════════════════════════════════════════════════════════════

# payload -> обработчик, требующий (user_id, callback_id, payload)
_CALLBACK_PREFIX_ROUTES = (
    ("cat_", category_callback),
    ("svc_", service_selected),
    ("staff_", staff_selected),
    ("date_", date_selected),
    ("time_", time_selected),
)


def handle_callback(update: dict) -> None:
    """message_callback — пользователь нажал на кнопку."""
    callback = update.get("callback", {})
    callback_id = callback.get("callback_id")
    payload = callback.get("payload", "") or ""
    user_id = str(callback.get("sender", {}).get("user_id", ""))

    if not callback_id or not user_id:
        logger.warning(f"Некорректный message_callback: {update}")
        return

    try:
        if payload in ("book", "services", "contacts", "my_bookings",
                      "back_to_categories", "back_to_menu"):
            main_menu_callback(user_id, callback_id, payload)
        elif payload == "back_to_date":
            back_to_date(user_id, callback_id)
        elif payload == "skip_comment":
            skip_comment(user_id, callback_id)
        elif payload in ("confirm_yes", "confirm_no"):
            confirm_booking(user_id, callback_id, payload)
        elif payload.startswith("notify_max_"):
            notify_max_callback(user_id, callback_id, payload)
        elif payload.startswith("cancel_"):
            cancel_booking_callback(callback_id, payload)
        else:
            for prefix, handler in _CALLBACK_PREFIX_ROUTES:
                if payload.startswith(prefix):
                    handler(user_id, callback_id, payload)
                    return
            logger.warning(f"Неизвестный payload кнопки: {payload!r}")
            answer_callback(callback_id)  # тихо подтверждаем, чтобы не висело
    except Exception:
        logger.exception(f"Ошибка обработки callback (user={user_id}, payload={payload})")
        answer_callback(callback_id, text="❌ Произошла ошибка. Попробуйте /start")
        clear_session(user_id)


def handle_message(update: dict) -> None:
    """message_created — пользователь отправил текстовое сообщение."""
    message = update.get("message", {})
    sender = message.get("sender", {})
    user_id = str(sender.get("user_id", ""))
    text = (message.get("body", {}) or {}).get("text", "") or ""

    if not user_id:
        return

    try:
        stripped = text.strip()
        if stripped.startswith("/start"):
            start(user_id)
            return
        if stripped.startswith("/cancel"):
            cancel_dialog(user_id)
            return

        state = get_state(user_id)
        if state == ENTER_NAME:
            name_received(user_id, text)
        elif state == ENTER_PHONE:
            phone_received(user_id, text)
        elif state == ENTER_COMMENT:
            comment_received(user_id, text)
        else:
            handle_free_text(user_id, text)
    except Exception:
        logger.exception(f"Ошибка обработки сообщения (user={user_id})")
        send_message(user_id=int(user_id),
                    text="❌ Произошла ошибка. Попробуйте /start")
        clear_session(user_id)


def handle_bot_started(update: dict) -> None:
    """bot_started — пользователь впервые запустил бота (аналог первого /start),
    либо перешёл по диплинку https://max.ru/<bot>?start=<payload> — тогда
    payload лежит ПРЯМО в update (не внутри update["user"])."""
    user_id = str(update.get("user", {}).get("user_id", ""))
    payload = update.get("payload")  # None, если диплинк без параметра
    if not user_id:
        return
    if payload:
        # Погасить одноразовый токен привязки уведомлений,
        # отправленный сайтом через deeplink.
        try:
            resp = requests.post(
                f"{API_BASE}/api/notifications/redeem-token",
                json={
                    "token": payload,
                    "provider": "max",
                    "provider_user_id": user_id,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                send_message(user_id=int(user_id), text="🔔 Уведомления MAX подключены!")
            else:
                err = resp.json().get("error", "")
                msg = {
                    "expired": "⏳ Ссылка устарела, вернитесь на сайт и попробуйте снова.",
                    "already_used": "Эта ссылка уже была использована.",
                    "not_found": "Ссылка недействительна.",
                }.get(err, "Не удалось подключить уведомления.")
                send_message(user_id=int(user_id), text=f"⚠️ {msg}")
        except Exception as e:
            logger.error(f"Ошибка redeem-token (max): {e}")
    start(user_id)


def process_update(update: dict) -> None:
    utype = update.get("update_type")
    if utype == "message_callback":
        handle_callback(update)
    elif utype == "message_created":
        handle_message(update)
    elif utype == "bot_started":
        handle_bot_started(update)
    # остальные типы (bot_added/removed, dialog_*, user_*, ...) не используются
    # этим ботом — молча пропускаем.


# ─── Главная функция ───


def run_polling() -> None:
    """Long polling GET /updates. Только для разработки/тестов — см. шапку файла."""
    logger.info("Обработчики зарегистрированы. Запускаю polling...")
    marker = None
    consecutive_errors = 0

    while True:
        try:
            resp = get_updates(marker=marker, timeout=25, limit=100)
            if resp is None:
                raise requests.exceptions.RequestException("нет ответа от MAX API")

            if resp.status_code == 401:
                logger.critical("HTTP 401 при GET /updates — проверьте BOT_TOKEN")
                raise SystemExit(1)

            if resp.status_code != 200:
                logger.error(f"GET /updates -> HTTP {resp.status_code}: "
                             f"{resp.text[:300]}")
                consecutive_errors += 1
                time.sleep(min(30, 2 ** consecutive_errors))
                continue

            consecutive_errors = 0
            data = resp.json()
            for update in data.get("updates", []):
                process_update(update)
            marker = data.get("marker", marker)

        except KeyboardInterrupt:
            logger.info("Остановлено пользователем (Ctrl+C).")
            break
        except SystemExit:
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка сети при GET /updates: {e}")
            consecutive_errors += 1
            time.sleep(min(30, 2 ** consecutive_errors))
        except Exception:
            logger.exception("Непредвиденная ошибка в цикле polling")
            consecutive_errors += 1
            time.sleep(min(30, 2 ** consecutive_errors))


def main() -> None:
    """Запуск бота."""
    # ─── Проверка токена ───
    if not TOKEN:
        logger.critical(
            "BOT_TOKEN не задан! Установите переменную окружения BOT_TOKEN.\n"
            "  export BOT_TOKEN=<токен, выданный при создании бота в MAX>\n"
            "Или укажите токен в /etc/beautyverbena.env")
        raise SystemExit(1)

    logger.info(
        "╭─────────────────────────────────────────────╮\n"
        "│  BeautyVerbenaBot (MAX) запускается          │\n"
        f"│  TOKEN: {TOKEN[:8]}...{TOKEN[-4:]:>10}  │\n"
        f"│  API_BASE: {API_BASE:<31} │\n"
        f"│  MAX_API_BASE: {MAX_API_BASE:<27} │\n"
        f"│  MAX_API_PROXY: {'задан' if MAX_API_PROXY else 'нет (прямое подключение)':<20} │\n"
        "╰─────────────────────────────────────────────╯\n"
        "⚠️  Long polling — только для разработки/тестов. "
        "Для прода используйте Webhook (POST /subscriptions).")

    try:
        run_polling()
    except Exception as e:
        logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА при запуске polling: {e}",
                        exc_info=True)
        raise


if __name__ == "__main__":
    main()