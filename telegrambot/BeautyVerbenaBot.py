#!/usr/bin/env python3
"""BeautyVerbenaBot — Telegram-бот для записи в студию красоты VERBENA.

Для работы через прокси задайте переменную BOT_PROXY:
  export BOT_PROXY="http://user:pass@host:3128"
"""
import asyncio
import logging
import os
import re
from datetime import date, timedelta, datetime
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / "backend" / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    raise FileNotFoundError(f"Файл .env не найден: {ENV_PATH}")

import requests
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
from telegram.request import HTTPXRequest

# ─── Конфигурация ───

TOKEN = os.environ.get("BOT_TOKEN", "")
API_BASE = os.environ.get("API_BASE",
                          "http://localhost:5000")  # URL Flask-бэкенда

# ─── Прокси для Telegram API (из переменной окружения) ───
BOT_PROXY = os.environ.get("BOT_PROXY", "")

# ─── Состояния ConversationHandler ───

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

# Категории: ключи без эмодзи для callback_data (эмодзи только для отображения)
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

    ПРИМЕЧАНИЕ: для случая с известным service_id этот живой запрос теперь
    НЕ используется в основном сценарии бота (см. yc_staff_for_service) —
    у каждой услуги в _YC_SERVICES_CACHE уже есть свой встроенный список
    "staff", тем же способом, каким backend извлекает мастеров в
    yclients_api.extract_active_staff(). Функция оставлена для fallback-
    сценария (услуга не из YClients) и на случай, если понадобится
    полный, не привязанный к кэшу запрос."""
    try:
        params = {"service_id": service_id} if service_id else {}
        resp = requests.get(f"{API_BASE}/api/yclients/staff",
                            params=params,
                            timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.warning(f"YClients staff load failed: {e}")
    return []


def yc_staff_for_service(yc_service: dict):
    """Мастера конкретной услуги YClients БЕЗ живого запроса к API.

    Раньше service_selected() на КАЖДЫЙ выбор услуги любым пользователем
    делал отдельный живой запрос /api/yclients/staff?service_id=... —
    на backend это /book_staff/{company_id}?service_ids[]=... (см.
    yclients_api.get_staff_for_booking), ручка с историей 422 на
    "плохих" id и бисекцией для обхода (см. yclients_api._book_staff_bisect).
    Между тем сама услуга уже пришла из /company/{id}/services/ (см.
    _YC_SERVICES_CACHE / load_yc_services) — а YClients отдаёт эту ручку
    с встроенным списком "staff": [...] для каждой услуги, тем же полем,
    которым backend уже пользуется в yclients_api.extract_active_staff()
    для расчёта свободных окон. Значит мастеров для уже выбранной услуги
    можно взять прямо из уже загруженного (и обновляемого раз в
    _YC_CACHE_TTL секунд, см. refresh_yc_cache) кэша услуг — без единого
    дополнительного обращения к YClients на каждое нажатие кнопки."""
    return yc_service.get("staff", []) or []


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


# Cache for YClients data with TTL (60 seconds)
_YC_STAFF_CACHE = []
_YC_SERVICES_CACHE = []
_YC_CATEGORIES_CACHE = []
_YC_CACHE_TIMESTAMP = datetime.min  # время последнего обновления кэша
_YC_CACHE_TTL = 60  # секунд, в течение которых кэш считается свежим
_YC_CACHE_LOCK = asyncio.Lock(
)  # блокировка для предотвращения одновременных refresh


def _is_cache_fresh() -> bool:
    """Проверить, не устарел ли кэш YClients."""
    global _YC_CACHE_TIMESTAMP
    return (datetime.now() -
            _YC_CACHE_TIMESTAMP).total_seconds() < _YC_CACHE_TTL


def refresh_yc_cache():
    """Refresh YClients data cache (categories, services, staff)."""
    global _YC_STAFF_CACHE, _YC_SERVICES_CACHE, _YC_CATEGORIES_CACHE, _YC_CACHE_TIMESTAMP
    _YC_CATEGORIES_CACHE = load_yc_categories()
    _YC_SERVICES_CACHE = load_yc_services()
    _YC_STAFF_CACHE = load_yc_staff()
    _YC_CACHE_TIMESTAMP = datetime.now()


async def refresh_yc_cache_async():
    """Асинхронное обновление кэша YClients в фоне без блокировки."""
    async with _YC_CACHE_LOCK:
        if _is_cache_fresh():
            return  # кэш ещё свежий, ничего не делаем
        # Запускаем синхронные HTTP-запросы в executor, чтобы не блокировать event loop
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, refresh_yc_cache)


async def _show_loading(query, text: str = "⏳ Секунду, загружаю...") -> None:
    """Показать заглушку на время запроса к бэкенду/YClients.

    Используется перед потенциально небыстрыми сетевыми запросами
    (доступные даты/время, создание записи), чтобы пользователь видел,
    что бот работает, а не завис — сообщение сразу же будет заменено
    результатом запроса.
    """
    try:
        await query.edit_message_text(text)
    except Exception as e:
        if "not modified" not in str(e).lower():
            logger.debug(f"Не удалось показать индикатор загрузки: {e}")


async def _show_typing(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать статус «печатает…» в чате на время фонового запроса.

    В отличие от _show_loading (для callback-кнопок с редактируемым
    сообщением), используется там, где ответ идёт обычным текстовым
    сообщением (например, отправка заявки на трудоустройство).
    """
    chat = update.effective_chat
    if not chat:
        return
    try:
        await context.bot.send_chat_action(chat_id=chat.id, action="typing")
    except Exception as e:
        logger.debug(f"Не удалось показать статус 'печатает': {e}")


def yc_service_category_id(svc: dict):
    """Достать category_id из услуги YClients (как в modal.js: svc.category_id || svc.category.id)."""
    return svc.get("category_id") or (svc.get("category") or {}).get("id")


def yc_services_in_category(category_id):
    """Реальные услуги YClients для данной категории (как populateServices() в modal.js).

    Отдаёт только услуги с active == 1 — как в extract_active_staff()
    (см. yclients_api.py): active == 1 отражает реальную доступность
    услуги в самом YClients (архивные/скрытые услуги отдаются тем же
    /company/{id}/services/ с active == 0, но показывать их в боте
    для записи нельзя)."""
    cat_id_str = str(category_id)
    return [
        s for s in _YC_SERVICES_CACHE
        if str(yc_service_category_id(s) or "") == cat_id_str
        and s.get("active") == 1
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


def get_telegram_id(update: Update) -> str:
    """Получить строковый telegram_id пользователя."""
    user = update.effective_user
    return str(user.id) if user else ""


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
    time = booking.get("booking_time", "")
    master = booking.get("assigned_employee_name", "")

    lines = [
        f"📋 <b>Запись #{booking['id']}</b>",
        f"{emoji} <b>{status_ru}</b>",
        f"💇‍♀️ {service}",
        f"📅 {date_display} в {time}",
    ]
    if master:
        lines.append(f"👩‍🎨 Мастер: {master}")
    # Телефон скрываем — пользователь знает свой номер
    return "\n".join(lines)


def get_proxy_config():
    """Вернуть словарь proxies для requests (если BOT_PROXY задан), иначе None."""
    if BOT_PROXY:
        return {"https": BOT_PROXY, "http": BOT_PROXY}
    return None


def send_notifications(booking_data: dict):
    """Отправить уведомления всем сотрудникам с notify_enabled=1.

    Использует синхронный httpx.Client (читает HTTPS_PROXY из env vars).
    В отличие от requests, httpx корректно работает через HTTP forward-прокси
    для HTTPS-запросов — без CONNECT-туннелирования.
    """
    import httpx

    try:
        with httpx.Client(timeout=15.0) as client:
            # Получаем список пользователей через API бэкенда (localhost)
            resp = client.get(f"{API_BASE}/api/telegram/notify-users")
            if resp.status_code != 200:
                logger.info(
                    f"notify-users вернул {resp.status_code}, пропускаем")
                return
            users = resp.json()
            if not users:
                logger.info("Нет пользователей с notify_enabled=1")
                return

            date_display = to_display_date(booking_data.get(
                "booking_date", ""))
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
                tg_id = user.get("telegram_id", "").strip()
                if not tg_id or not tg_id.isdigit():
                    continue
                try:
                    r = client.post(
                        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                        json={
                            "chat_id": int(tg_id),
                            "text": message,
                            "parse_mode": "HTML",
                        },
                    )
                    if r.status_code != 200:
                        logger.error(f"Ошибка отправки уведомления {tg_id}: "
                                     f"HTTP {r.status_code} — {r.text[:200]}")
                    else:
                        logger.info(
                            f"Уведомление отправлено пользователю {tg_id}")
                except Exception as e:
                    logger.error(
                        f"Ошибка отправки уведомления пользователю {tg_id}: {e}"
                    )
    except Exception as e:
        logger.error(f"Ошибка получения списка уведомляемых: {e}")


# ─── Команда /start ───

MAIN_MENU_TEXT = (
    "🌸 <b>Добро пожаловать в VERBENA — студию красоты!</b>\n\n"
    "Здесь вы можете записаться на услуги, посмотреть свои записи "
    "и узнать больше о нашей студии.\n\n"
    "📍 г. Строитель, ул. Октябрьская, 15\n"
    "🕐 Ежедневно 10:00–20:00\n"
    "📞 +7 (915) 526-50-56\n"
    "🌍 https://beauty-verbena.ru\n\n"
    "<i>Выберите действие:</i>")

MAIN_MENU_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("📅 Записаться на услугу", callback_data="book")],
    # [InlineKeyboardButton("📋 Мои записи", callback_data="my_bookings")],  # ← МОИ ЗАПИСИ (отключено)
    # [InlineKeyboardButton("🔔 Уведомления",
    #                       callback_data="notifications")],  # ← УВЕДОМЛЕНИЯ (клиентские, отключено)
    [InlineKeyboardButton("💇‍♀️ Услуги и цены", callback_data="services")],
    [InlineKeyboardButton("📍 Контакты", callback_data="contacts")],
    [
        InlineKeyboardButton("🤝 Хочу присоединиться к команде",
                             callback_data="career")
    ],
])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Приветствие и главное меню. Если передан токен (/start <token>) — погасить его."""
    if context.args:
        token = context.args[0]
        user = update.effective_user
        try:
            resp = requests.post(
                f"{API_BASE}/api/notifications/redeem-token",
                json={
                    "token": token,
                    "provider": "telegram",
                    "provider_user_id": str(user.id),
                    "provider_username": user.username or "",
                },
                timeout=10,
            )
            if resp.status_code == 200:
                await update.message.reply_text(
                    "🔔 Уведомления Telegram подключены!")
            else:
                err = resp.json().get("error", "")
                msg = {
                    "expired":
                    "⏳ Ссылка устарела, вернитесь на сайт и попробуйте снова.",
                    "already_used": "Эта ссылка уже была использована.",
                    "not_found": "Ссылка недействительна.",
                }.get(err, "Не удалось подключить уведомления.")
                await update.message.reply_text(f"⚠️ {msg}")
        except Exception as e:
            logger.error(f"Ошибка redeem-token: {e}")

    await update.message.reply_text(
        MAIN_MENU_TEXT,
        reply_markup=MAIN_MENU_KEYBOARD,
        parse_mode="HTML",
    )


# ─── Главное меню (обработчик кнопок) ───


async def show_main_menu(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать главное меню (из callback)."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        MAIN_MENU_TEXT,
        reply_markup=MAIN_MENU_KEYBOARD,
        parse_mode="HTML",
    )


async def main_menu_callback(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатий кнопок главного меню."""
    query = update.callback_query
    await query.answer()

    if query.data == "book":
        await show_categories(query, context)
    # elif query.data == "my_bookings":  # ← МОИ ЗАПИСИ (отключено)
    #     await show_my_bookings(update, context)
    elif query.data == "services":
        await show_services(query, context)
    elif query.data == "contacts":
        await show_contacts(query, context)
    elif query.data == "back_to_categories":
        await show_categories(query, context)
    elif query.data == "back_to_menu":
        await show_main_menu(update, context)
    # elif query.data == "notifications":  # ← УВЕДОМЛЕНИЯ (клиентские, отключено)
    #     await show_notifications_settings(update, context)
    elif query.data == "career":
        await show_career(update, context)


async def show_career(update: Update,
                      context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать информацию о вакансиях и форму заявки на трудоустройство."""
    query = update.callback_query
    await query.answer()
    text = ("🤝 <b>Хотите присоединиться к команде VERBENA?</b>\n\n"
            "Мы создаём пространство, где красота встречается с "
            "профессионализмом, заботой и вдохновением.\n\n"
            "Если ты любишь своё дело, стремишься развиваться и хочешь "
            "работать в атмосфере уважения и поддержки — "
            "мы будем рады познакомиться с тобой.\n\n"
            "Напишите нам в ответных сообщениях:\n"
            "• Ваше имя\n"
            "• Телефон\n"
            "• Опыт работы\n"
            "• Ссылка на портфолио/резюме (необязательно)\n"
            "• Сопроводительное письмо (необязательно)\n\n"
            "Мы обязательно рассмотрим вашу заявку!")
    keyboard = [[
        InlineKeyboardButton("📝 Оставить заявку", callback_data="career_form"),
        InlineKeyboardButton("◀️ В меню", callback_data="back_to_menu")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text,
                                  reply_markup=reply_markup,
                                  parse_mode="HTML")


async def career_form_handler(update: Update,
                              context: ContextTypes.DEFAULT_TYPE) -> None:
    """Начало диалога для заявки на трудоустройство."""
    query = update.callback_query
    await query.answer()
    context.user_data["career_step"] = "name"
    await query.edit_message_text(
        "📝 <b>Заявка на трудоустройство</b>\n\n"
        "Шаг 1 из 5\n\n"
        "Введите ваше имя:",
        parse_mode="HTML")


async def career_message_handler(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка сообщений для заявки на трудоустройство."""
    step = context.user_data.get("career_step")
    if not step:
        return
    text = update.message.text.strip()

    if step == "name":
        # ✅ Валидация имени
        if not re.match(r"^[a-zA-Zа-яА-ЯёЁ\s\-']{2,}$", text):
            await update.message.reply_text(
                "❌ Имя должно содержать только буквы (минимум 2 символа). Попробуйте снова:"
            )
            return
        context.user_data["career_name"] = text
        context.user_data["career_step"] = "phone"
        await update.message.reply_text(
            f"👤 Имя: {text}\nШаг 2 из 5\nВведите ваш номер телефона:")

    elif step == "phone":
        phone_clean = re.sub(r"[^\d+]", "", text)
        if len(phone_clean) < 10:
            await update.message.reply_text(
                "❌ Неверный формат телефона. Введите номер (например: +79155265056):"
            )
            return
        context.user_data["career_phone"] = phone_clean
        context.user_data["career_step"] = "experience"
        await update.message.reply_text(
            f"📞 Телефон: {phone_clean}\n\nШаг 3 из 5\n\nРасскажите о вашем опыте работы:"
        )

    elif step == "experience":
        if len(text) < 3:
            await update.message.reply_text(
                "❌ Пожалуйста, опишите ваш опыт работы подробнее:")
            return
        context.user_data["career_experience"] = text
        context.user_data["career_step"] = "resume"
        await update.message.reply_text(
            f"💼 Опыт: {text}\n\nШаг 4 из 5\n\nСсылка на резюме или портфолио (необязательно, отправьте «-» чтобы пропустить):"
        )

    elif step == "resume":
        context.user_data["career_resume"] = text if text != "-" else ""
        context.user_data["career_step"] = "cover_letter"
        await update.message.reply_text(
            "Шаг 5 из 5\n\nСопроводительное письмо (необязательно, отправьте «-» чтобы пропустить):"
        )

    elif step == "cover_letter":
        context.user_data["career_cover_letter"] = text if text != "-" else ""
        # Отправляем заявку
        await _submit_career_application(update, context)


async def _submit_career_application(
        update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправить заявку на трудоустройство в API."""
    telegram_id = str(
        update.effective_user.id) if update.effective_user else ""
    payload = {
        "client_name": context.user_data.get("career_name", ""),
        "client_phone": context.user_data.get("career_phone", ""),
        "experience": context.user_data.get("career_experience", ""),
        "resume": context.user_data.get("career_resume", ""),
        "cover_letter": context.user_data.get("career_cover_letter", ""),
        "source": "tg",
        "telegram_id": telegram_id,
    }

    await _show_typing(update, context)

    try:
        resp = requests.post(f"{API_BASE}/api/career/submit",
                             json=payload,
                             timeout=10)
        if resp.status_code in (200, 201):
            text = ("✅ <b>Заявка успешно отправлена!</b>\n"
                    "Мы свяжемся с вами в ближайшее время.\n"
                    "Спасибо за интерес к работе в VERBENA! 🌸")
        else:
            text = "✅ Ваша заявка принята! Мы свяжемся с вами."
    except Exception:
        text = "✅ Ваша заявка принята! Мы свяжемся с вами."

    # Очищаем данные
    for key in [
            "career_step", "career_name", "career_phone", "career_experience",
            "resume", "cover_letter"
    ]:
        context.user_data.pop(key, None)

    # ✅ ОДНО сообщение с кнопкой возврата в меню (вместо двух подряд)
    keyboard = [[
        InlineKeyboardButton("◀️ В меню", callback_data="back_to_menu")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        text,
        reply_markup=reply_markup,
        parse_mode="HTML",
    )


async def exit_booking_to_main_menu(update: Update,
                                    context: ContextTypes.DEFAULT_TYPE) -> int:
    """«В меню» из середины диалога записи — показываем меню и ЗАВЕРШАЕМ диалог.

    main_menu_callback ничего не возвращает (None), а ConversationHandler
    трактует None как «состояние не меняется». Если использовать
    main_menu_callback напрямую внутри состояния SELECT_SERVICE, диалог
    формально остаётся активным в состоянии SELECT_SERVICE, хотя пользователь
    уже видит главное меню — из-за этого дальнейшие нажатия (например, выбор
    категории после повторного «Записаться») в некоторых сценариях не
    долетают до нужного обработчика. Эта обёртка явно завершает диалог.
    """
    await main_menu_callback(update, context)
    context.user_data.clear()
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════
# [ЗАКОММЕНТИРОВАНО] Мои записи — show_my_bookings
# Функция показывает пользователю его записи — отключено.
# ═══════════════════════════════════════════════════════════════


async def show_categories(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать категории услуг."""
    # Асинхронное обновление кэша — не блокирует ответ
    asyncio.ensure_future(refresh_yc_cache_async())

    keyboard = []
    if _YC_CATEGORIES_CACHE and _YC_SERVICES_CACHE:
        for cat in _YC_CATEGORIES_CACHE:
            cat_id = cat.get("id")
            title = cat.get("title") or "Услуги"
            if cat_id is None or not yc_services_in_category(cat_id):
                continue
            keyboard.append(
                [InlineKeyboardButton(title, callback_data=f"cat_{cat_id}")])

    if not keyboard:
        for key, display_name in CATEGORY_LABELS:
            keyboard.append([
                InlineKeyboardButton(display_name, callback_data=f"cat_{key}")
            ])

    keyboard.append(
        [InlineKeyboardButton("️ Назад", callback_data="back_to_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    new_text = "Выберите категорию услуги:"

    # ✅ ПРОВЕРКА: Не редактируем, если контент идентичен
    try:
        current_msg = query.message
        if (current_msg.text == new_text and current_msg.reply_markup
                and current_msg.reply_markup.inline_keyboard
                == reply_markup.inline_keyboard):
            logger.debug("Message content unchanged, skipping edit.")
            return

        await query.edit_message_text(
            new_text,
            reply_markup=reply_markup,
        )
    except telegram.error.BadRequest as e:
        if "not modified" in str(e).lower():
            logger.debug("Telegram skipped edit: message not modified")
        else:
            raise


async def show_services(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать все услуги с ценами (загружается из YClients API)."""
    # Асинхронное обновление кэша — не блокирует ответ
    asyncio.ensure_future(refresh_yc_cache_async())

    text = "💇‍♀️ <b>Наши услуги и цены</b>\n\n"

    if _YC_CATEGORIES_CACHE and _YC_SERVICES_CACHE:
        # Показываем из YClients
        for cat in _YC_CATEGORIES_CACHE:
            cat_id = cat.get("id")
            title = cat.get("title") or "Услуги"
            if cat_id is None:
                continue
            text += f"<b>{title}</b>\n"
            for svc in yc_services_in_category(cat_id):
                price = yc_price_label(svc)
                svc_title = svc.get("title", "Услуга")
                text += f"  • {svc_title}" + (f" — <i>{price}</i>"
                                              if price else "") + "\n"
            text += "\n"
    else:
        # Fallback: статический список
        for key, display_name in CATEGORY_LABELS:
            text += f"<b>{display_name}</b>\n"
            for _, service_name, price in services_in_category(key):
                text += f"  • {service_name} — <i>{price}</i>\n"
            text += "\n"

    text += "\n<i>Чтобы записаться, нажмите «Записаться на услугу» в меню.</i>"
    keyboard = [[
        InlineKeyboardButton("◀️ В меню", callback_data="back_to_menu")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text,
                                  reply_markup=reply_markup,
                                  parse_mode="HTML")


async def show_contacts(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать контактную информацию."""
    text = (
        "📍 <b>Студия красоты VERBENA</b>\n"
        "🏠 <b>Адрес:</b> г. Строитель, ул. Октябрьская, 15\n"
        "🕐 <b>Режим работы:</b> Ежедневно 10:00–20:00\n"
        "📞 <b>Телефон:</b> +7 (915) 526-50-56\n\n"
        "🌐 <b>Мы в соцсетях:</b>\n"
        "• <a href='https://vk.ru/verbena.studio31'>ВКонтакте</a>\n"
        "• <a href='https://t.me/verbenastudio31'>Telegram</a>\n"
        "• <a href='https://max.ru/join/pa9K0R9aGl3Q02_N0A6pvklfZfixDfIVIFgJFKz25Lg'>MAX</a>\n"
        "• <a href='https://www.instagram.com/verbena_studio31'>Instagram</a>")
    keyboard = [[
        InlineKeyboardButton("◀️ В меню", callback_data="back_to_menu")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        text,
        reply_markup=reply_markup,
        parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════════════════
# [ЗАКОММЕНТИРОВАНО] Мои записи — cancel_booking_callback
# Отмена записи из раздела «Мои записи» — отключено.
# ═══════════════════════════════════════════════════════════════

# ─── Процесс записи на услугу ───


async def category_callback(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор услуги из категории."""
    query = update.callback_query
    await query.answer()

    cat_key = query.data.replace("cat_", "")

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
            label = f"{svc.get('title', 'Услуга')}" + (f" — {price}"
                                                       if price else "")
            # callback_data ограничен 64 байтами — используем реальный числовой
            # id услуги YClients, чтобы не терять связь с сервисом (как selectedService.id в modal.js)
            keyboard.append([
                InlineKeyboardButton(label, callback_data=f"svc_{svc['id']}")
            ])
    else:
        # ─── Fallback: статический список (старое поведение) ───
        display_name = dict(CATEGORY_LABELS).get(cat_key)
        services = services_in_category(cat_key)
        if display_name is None or not services:
            await query.edit_message_text("❌ Ошибка: категория не найдена")
            return SELECT_SERVICE
        for idx, service_name, price in services:
            label = f"{service_name} — {price}"
            # Индекс, а не текст: длинные названия услуг ломают клавиатуру целиком.
            keyboard.append(
                [InlineKeyboardButton(label, callback_data=f"svc_{idx}")])

    keyboard.append([
        InlineKeyboardButton("◀️ Назад к категориям",
                             callback_data="back_to_categories")
    ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"<b>{display_name}</b>\n\nВыберите услугу:",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    return SELECT_SERVICE


async def back_to_categories(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> int:
    """Вернуться к категориям."""
    query = update.callback_query
    await query.answer()
    await show_categories(query, context)
    # Явно возвращаем состояние: без этого ConversationHandler считает,
    # что состояние не изменилось (осталось прежним — например SELECT_DATE),
    # и следующий выбор категории (cat_...) просто не долетает до обработчика.
    return SELECT_SERVICE


async def service_selected(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> int:
    """Услуга выбрана — запрашиваем мастера (если есть в YClients), иначе дату."""
    query = update.callback_query
    await query.answer()

    raw = query.data.replace("svc_", "")

    # ─── Реальная услуга YClients (id совпадает с закэшированной) ───
    yc_service = None
    if _YC_SERVICES_CACHE:
        for svc in _YC_SERVICES_CACHE:
            # active == 1 — иначе можно словить нажатие на устаревшую кнопку
            # из старого сообщения (услугу деактивировали/сняли с онлайн-записи
            # после того, как меню было показано пользователю).
            if str(svc.get("id")) == raw and svc.get("active") == 1:
                yc_service = svc
                break

    if yc_service is not None:
        service_name = yc_service.get("title", "Услуга")
        context.user_data["service"] = service_name
        context.user_data["yclients_service_id"] = yc_service["id"]
        # Мастера этой услуги — из уже закэшированного списка услуг, без
        # живого запроса к YClients (см. yc_staff_for_service).
        staff = yc_staff_for_service(yc_service)
    else:
        # ─── Fallback: статический список услуг (старое поведение) ───
        try:
            service_name, price, _ = SERVICES[int(raw)]
        except (ValueError, IndexError):
            # Устаревшая/повреждённая кнопка (например, после перезапуска бота).
            await query.edit_message_text(
                "❌ Эта кнопка устарела. Пожалуйста, начните запись заново: /start"
            )
            context.user_data.clear()
            return ConversationHandler.END

        context.user_data["service"] = service_name
        context.user_data.pop("yclients_service_id", None)
        staff = _YC_STAFF_CACHE

    if staff:
        # Show staff selection first
        keyboard = []
        for s in staff:
            name = s.get("name", "Мастер")
            spec = s.get("specialization", "")
            label = f"{name}" + (f" ({spec})" if spec else "")
            keyboard.append([
                InlineKeyboardButton(label, callback_data=f"staff_{s['id']}")
            ])
        keyboard.append([
            InlineKeyboardButton("◀️ Назад",
                                 callback_data="back_to_categories")
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"💇‍♀️ <b>Услуга:</b> {service_name}\n\n"
            "👩‍🎨 Выберите мастера:",
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
        return SELECT_STAFF
    else:
        context.user_data["date_page"] = 0
        return await _show_date_selection(query, context, service_name)


DATE_RANGE_DAYS = 14
# ─── Пагинация дат ───
DATE_WINDOW_DAYS = 60  # на сколько дней вперёд ищем доступные даты
DATE_PAGE_SIZE = 14  # сколько дат показывать на одной странице

# TTL для локального (в рамках одного диалога) кэша доступных дат/времени.
# Нужен только для навигации "Назад" внутри уже начатой записи (см.
# back_to_date/back_to_time) — пока пользователь ходит между шагами
# туда-обратно, не меняя услугу/мастера/дату, нет смысла на каждый такой
# клик заново дёргать YClients: book_dates/book_times не кэшируются на
# backend (в отличие от /api/public/free-slots), поэтому без этого кэша
# каждое "Назад" — это живой запрос к YClients с тем же результатом.
# Хранится в context.user_data, то есть per-диалог, и живёт не дольше
# самого диалога — никакого риска отдать чужие/устаревшие данные другому
# пользователю.
_NAV_CACHE_TTL = 60  # секунд


def _fetch_available_dates_for_month(service_id, staff_id, year, month):
    """Один вызов /api/yclients/available-dates за конкретный месяц.

    Возвращает set ISO-дат ("YYYY-MM-DD") со свободными слотами, либо
    None, если запрос не удался — этим None (в отличие от пустого set)
    сигнализирует, что фильтровать календарь нельзя, и вызывающий код
    должен показать все даты, как раньше (не прятать даты из-за сбоя API)."""
    params = {"service_id": service_id, "month": month, "year": year}
    if staff_id and staff_id != "0":
        params["staff_id"] = staff_id
    try:
        resp = requests.get(
            f"{API_BASE}/api/yclients/available-dates",
            params=params,
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return {str(d) for d in data}
        logger.warning(
            f"available-dates: HTTP {resp.status_code} - {resp.text[:200]}")
    except Exception as e:
        logger.error(f"Ошибка при получении доступных дат: {e}")
    return None


def _get_available_dates_set(service_id,
                             staff_id,
                             context,
                             days=DATE_WINDOW_DAYS):
    """Доступные даты (ISO) в пределах ближайших `days` дней.

    Учитывает, что окно может захватывать несколько календарных месяцев.
    Результат кэшируется в context.user_data на _NAV_CACHE_TTL секунд.
    """
    cache = context.user_data.get("_dates_cache")
    cache_key = (str(service_id), str(staff_id), int(days))

    if cache and cache.get("key") == cache_key:
        age = datetime.now().timestamp() - cache["ts"]
        if age < _NAV_CACHE_TTL:
            return cache["data"]

    today = date.today()
    end = today + timedelta(days=days - 1)

    # Собираем все месяцы, которые попадают в диапазон
    months = []
    cur = today.replace(day=1)
    end_month = end.replace(day=1)

    while cur <= end_month:
        months.append((cur.year, cur.month))
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)

    all_dates = set()

    for (y, m) in months:
        result = _fetch_available_dates_for_month(service_id, staff_id, y, m)

        if result is None:
            # Если хотя бы один месяц не удалось получить —
            # не фильтруем даты, чтобы случайно не скрыть рабочие дни.
            return None

        all_dates |= result

    context.user_data["_dates_cache"] = {
        "key": cache_key,
        "ts": datetime.now().timestamp(),
        "data": all_dates,
    }

    return all_dates


async def _show_date_selection(query, context, service_name):
    """Показ выбора даты с пагинацией стрелками вперёд/назад."""
    today = date.today()

    yc_service_id = context.user_data.get("yclients_service_id", "")
    yc_staff_id = context.user_data.get("yclients_staff_id", "")

    available_dates = None

    if yc_service_id:
        # Показываем заглушку, только если данных ещё нет в кэше диалога —
        # иначе будет лишнее мигание сообщения при листании уже
        # закэшированных дат.
        dates_cache_key = (str(yc_service_id), str(yc_staff_id),
                          int(DATE_WINDOW_DAYS))
        dates_cache = context.user_data.get("_dates_cache")
        cache_fresh = (dates_cache and dates_cache.get("key") == dates_cache_key
                       and (datetime.now().timestamp() - dates_cache.get("ts", 0))
                       < _NAV_CACHE_TTL)
        if not cache_fresh:
            await _show_loading(query, "⏳ Ищу свободные даты...")

        available_dates = _get_available_dates_set(yc_service_id,
                                                   yc_staff_id,
                                                   context,
                                                   days=DATE_WINDOW_DAYS)

    if available_dates is not None:
        all_dates = []

        for i in range(DATE_WINDOW_DAYS):
            d = today + timedelta(days=i)
            iso_date = d.isoformat()

            if iso_date in available_dates:
                all_dates.append(iso_date)
    else:
        # Fallback: если услуга не из YClients или API недоступен,
        # показываем ближайшие DATE_RANGE_DAYS дней без фильтрации.
        all_dates = [(today + timedelta(days=i)).isoformat()
                     for i in range(DATE_RANGE_DAYS)]

    if not all_dates:
        keyboard = [[
            InlineKeyboardButton("◀️ Назад",
                                 callback_data="back_to_categories")
        ]]

        await query.edit_message_text(
            f"💇‍♀️ <b>Услуга:</b> {service_name}\n"
            "😔 На ближайшие даты нет свободных записей. "
            "Попробуйте выбрать другого мастера или загляните позже.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

        return SELECT_DATE

    page = int(context.user_data.get("date_page", 0) or 0)

    page_count = max(1,
                     (len(all_dates) + DATE_PAGE_SIZE - 1) // DATE_PAGE_SIZE)

    if page < 0:
        page = 0

    if page >= page_count:
        page = page_count - 1

    context.user_data["date_page"] = page

    start_idx = page * DATE_PAGE_SIZE
    page_dates = all_dates[start_idx:start_idx + DATE_PAGE_SIZE]

    keyboard = []
    row = []

    for iso_date in page_dates:
        d = date.fromisoformat(iso_date)

        label = d.strftime("%d.%m")
        day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d.weekday()]

        btn_text = f"{label} ({day_name})"
        callback = f"date_{d.strftime('%d.%m.%Y')}"

        row.append(InlineKeyboardButton(btn_text, callback_data=callback))

        if len(row) == 2:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    # ─── Стрелки вперёд / назад ───
    nav_row = []

    if page > 0:
        nav_row.append(
            InlineKeyboardButton("◀️ Предыдущие", callback_data="dates_prev"))

    if page < page_count - 1:
        nav_row.append(
            InlineKeyboardButton("Следующие ▶️", callback_data="dates_next"))

    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([
        InlineKeyboardButton("◀️ Назад к категориям",
                             callback_data="back_to_categories")
    ])

    if page_count > 1:
        title = f"📅 Выберите удобную дату (стр. {page + 1} из {page_count}):"
    else:
        title = "📅 Выберите удобную дату:"

    await query.edit_message_text(
        f"💇‍♀️ <b>Услуга:</b> {service_name}\n"
        f"{title}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )

    return SELECT_DATE


async def staff_selected(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> int:
    """Staff selected — go to date selection."""
    query = update.callback_query
    await query.answer()

    staff_id = query.data.replace("staff_", "")
    if staff_id and staff_id != "0":
        context.user_data["yclients_staff_id"] = staff_id
        for s in _YC_STAFF_CACHE:
            if str(s["id"]) == staff_id:
                context.user_data["assigned_employee_name"] = s.get(
                    "name", "Мастер")
                break
    else:
        context.user_data["yclients_staff_id"] = ""
        context.user_data["assigned_employee_name"] = ""

    context.user_data["date_page"] = 0
    service_name = context.user_data.get("service", "")
    return await _show_date_selection(query, context, service_name)


async def date_selected(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> int:
    """Дата выбрана — загружаем свободное время."""
    query = update.callback_query
    await query.answer()
    if "service" not in context.user_data:
        await query.edit_message_text(
            "❌ Эта кнопка устарела. Пожалуйста, начните запись заново: /start")
        context.user_data.clear()
        return ConversationHandler.END

    date_str = query.data.replace("date_", "")
    context.user_data["date"] = date_str
    return await _show_time_selection(query, context, date_str)


async def _show_time_selection(query, context, date_str: str) -> int:
    """Загрузить и показать доступное время для уже выбранной даты.

    Вынесено из date_selected в отдельную функцию, чтобы её мог
    использовать и back_to_time (возврат с шага ввода имени, если
    пользователь передумал)."""
    iso_date = to_iso_date(date_str)

    yc_staff_id = context.user_data.get("yclients_staff_id", "")
    yc_service_id = context.user_data.get("yclients_service_id", "")

    logger.info(
        f"📅 Запрос слотов: Date={iso_date}, Staff={yc_staff_id}, Service={yc_service_id}"
    )

    # Кэш в рамках диалога — см. _NAV_CACHE_TTL: на "Назад к дате" → "туда
    # же" (тот же service/staff/date) не шлём в YClients повторный
    # book_times, если с прошлого раза не прошло больше TTL.
    times_cache_key = (str(yc_service_id), str(yc_staff_id), iso_date)
    times_cache = context.user_data.get("_times_cache")
    cache_hit = (times_cache and times_cache["key"] == times_cache_key
                 and (datetime.now().timestamp() - times_cache["ts"])
                 < _NAV_CACHE_TTL)

    available_slots = []
    if cache_hit:
        available_slots = times_cache["data"]
    else:
        await _show_loading(query, "⏳ Ищу свободное время...")
        try:
            # Пытаемся получить слоты от YClients через бэкенд
            if yc_service_id:
                # Даже если мастера нет (staff_0), пробуем получить слоты по услуге
                params = {
                    "service_id": yc_service_id,
                    "date": iso_date,
                }
                if yc_staff_id and yc_staff_id != "0":
                    params["staff_id"] = yc_staff_id

                resp = requests.get(
                    f"{API_BASE}/api/yclients/available-times",
                    params=params,
                    timeout=10,
                )

                logger.info(
                    f"YClients API Status: {resp.status_code}, Body: {resp.text[:200]}"
                )

                if resp.status_code == 200:
                    slots = resp.json()
                    if isinstance(slots, list) and len(slots) > 0:
                        if isinstance(slots[0], str):
                            available_slots = slots
                        elif isinstance(slots[0], dict):
                            # Фильтруем только доступные слоты
                            available_slots = [
                                s["time"] for s in slots
                                if s.get("available", True)
                            ]
                    # Кэшируем даже пустой (но успешный) результат — пустой
                    # список тоже валиден и не должен провоцировать повторный
                    # запрос при следующем "Назад" в течение TTL.
                    context.user_data["_times_cache"] = {
                        "key": times_cache_key,
                        "ts": datetime.now().timestamp(),
                        "data": available_slots,
                    }

            # УБРАЛИ fallback на старую БД, так как она не синхронизирована с YClients

        except Exception as e:
            logger.error(f"Ошибка при получении слотов: {e}")

    # ЕСЛИ СЛОТОВ НЕТ — ЧЕСТНО ГОВОРИМ ОБ ЭТОМ, А НЕ ПОКАЗЫВАЕМ TIME_SLOTS
    if not available_slots:
        logger.warning(
            f"⚠️ Нет доступных слотов для {iso_date}. Используем заглушку.")
        keyboard = [
            [
                InlineKeyboardButton("◀️ Выбрать другую дату",
                                     callback_data="back_to_date")
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "😔 На эту дату нет свободного времени. "
            "Пожалуйста, выберите другую дату.",
            reply_markup=reply_markup,
        )
        return SELECT_DATE

    keyboard = []
    row = []
    for slot in available_slots:
        row.append(InlineKeyboardButton(slot, callback_data=f"time_{slot}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([
        InlineKeyboardButton("◀️ Назад к дате", callback_data="back_to_date")
    ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"💇‍♀️ <b>Услуга:</b> {context.user_data['service']}\n"
        f"📅 <b>Дата:</b> {date_str}\n"
        "⏰ Выберите время:",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    return SELECT_TIME


async def back_to_date(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> int:
    """Вернуться к выбору даты."""
    query = update.callback_query
    await query.answer()
    service_name = context.user_data.get("service", "")
    context.user_data.pop("date", None)
    return await _show_date_selection(query, context, service_name)


async def date_page_prev(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> int:
    """Листание дат назад."""
    query = update.callback_query
    await query.answer()

    page = int(context.user_data.get("date_page", 0) or 0)
    context.user_data["date_page"] = max(0, page - 1)

    service_name = context.user_data.get("service", "")

    return await _show_date_selection(query, context, service_name)


async def date_page_next(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> int:
    """Листание дат вперёд."""
    query = update.callback_query
    await query.answer()

    page = int(context.user_data.get("date_page", 0) or 0)
    context.user_data["date_page"] = page + 1

    service_name = context.user_data.get("service", "")

    return await _show_date_selection(query, context, service_name)


async def time_selected(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> int:
    """Время выбрано — запрашиваем имя."""
    query = update.callback_query
    await query.answer()

    if "service" not in context.user_data or "date" not in context.user_data:
        await query.edit_message_text(
            "❌ Эта кнопка устарела. Пожалуйста, начните запись заново: /start")
        context.user_data.clear()
        return ConversationHandler.END

    time_str = query.data.replace("time_", "")
    context.user_data["time"] = time_str

    keyboard = [[
        InlineKeyboardButton("◀️ Назад", callback_data="back_to_time")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"💇‍♀️ <b>Услуга:</b> {context.user_data['service']}\n"
        f"📅 <b>Дата:</b> {context.user_data['date']}\n"
        f"⏰ <b>Время:</b> {time_str}\n\n"
        "👤 Введите ваше имя:",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    return ENTER_NAME


async def back_to_time(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> int:
    """Вернуться к выбору времени с шага ввода имени (пользователь передумал)."""
    query = update.callback_query
    await query.answer()
    date_str = context.user_data.get("date")
    if not date_str:
        # На всякий случай, если дата почему-то потерялась — откатываемся дальше.
        return await back_to_date(update, context)
    context.user_data.pop("time", None)
    return await _show_time_selection(query, context, date_str)


async def name_received(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> int:
    """Имя получено — запрашиваем телефон."""
    name = update.message.text.strip()
    if not name or len(name) < 2:
        await update.message.reply_text(
            "❌ Пожалуйста, введите корректное имя (минимум 2 символа).")
        return ENTER_NAME

    context.user_data["name"] = name

    await update.message.reply_text(
        f"👤 <b>Имя:</b> {name}\n\n"
        "📞 Введите ваш номер телефона для связи.\n"
        "Например: <code>+79155265056</code>",
        parse_mode="HTML",
    )
    return ENTER_PHONE


async def phone_received(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> int:
    """Телефон получен — показываем подтверждение."""
    phone = update.message.text.strip()
    phone_clean = re.sub(r"[^\d+]", "", phone)
    if not phone_clean or len(phone_clean) < 10:
        await update.message.reply_text(
            "❌ Пожалуйста, введите корректный номер телефона.\n"
            "Например: <code>+79155265056</code>",
            parse_mode="HTML",
        )
        return ENTER_PHONE

    context.user_data["phone"] = phone_clean

    # Ask for optional comment
    keyboard = [[
        InlineKeyboardButton("⏭️ Пропустить", callback_data="skip_comment"),
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"👤 <b>Имя:</b> {context.user_data['name']}\n"
        f"📞 <b>Телефон:</b> {phone_clean}\n\n"
        "💬 Если хотите, оставьте комментарий к записи\n"
        "(или нажмите «Пропустить»):",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    return ENTER_COMMENT


async def comment_received(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> int:
    """Comment received — show confirmation."""
    comment = update.message.text.strip()
    context.user_data["comment"] = comment
    return await _show_confirmation(update, context)


async def skip_comment(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> int:
    """Skip comment — show confirmation."""
    query = update.callback_query
    await query.answer()
    context.user_data["comment"] = ""
    return await _show_confirmation_from_query(query, context)


async def _show_confirmation(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show booking confirmation (from message handler)."""
    phone = context.user_data.get("phone", "")
    comment = context.user_data.get("comment", "")

    summary = ("📋 <b>Проверьте данные записи:</b>\n\n"
               f"💇‍♀️ <b>Услуга:</b> {context.user_data['service']}\n"
               f"📅 <b>Дата:</b> {context.user_data['date']}\n"
               f"⏰ <b>Время:</b> {context.user_data['time']}\n"
               f"👤 <b>Имя:</b> {context.user_data['name']}\n"
               f"📞 <b>Телефон:</b> {phone}\n")

    master = context.user_data.get("assigned_employee_name", "")
    if master:
        summary += f"👩‍🎨 <b>Мастер:</b> {master}\n"

    if comment:
        summary += f"💬 <b>Комментарий:</b> {comment}\n"

    summary += "\nВсё верно?"

    keyboard = [[
        InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_yes"),
        InlineKeyboardButton("❌ Отменить", callback_data="confirm_no"),
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(summary,
                                    reply_markup=reply_markup,
                                    parse_mode="HTML")
    return CONFIRM_BOOKING


async def _show_confirmation_from_query(query, context):
    """Show booking confirmation (from callback query)."""
    phone = context.user_data.get("phone", "")
    comment = context.user_data.get("comment", "")

    summary = ("📋 <b>Проверьте данные записи:</b>\n\n"
               f"💇‍♀️ <b>Услуга:</b> {context.user_data['service']}\n"
               f"📅 <b>Дата:</b> {context.user_data['date']}\n"
               f"⏰ <b>Время:</b> {context.user_data['time']}\n"
               f"👤 <b>Имя:</b> {context.user_data['name']}\n"
               f"📞 <b>Телефон:</b> {phone}\n")

    master = context.user_data.get("assigned_employee_name", "")
    if master:
        summary += f"👩‍🎨 <b>Мастер:</b> {master}\n"

    if comment:
        summary += f"💬 <b>Комментарий:</b> {comment}\n"

    summary += "\nВсё верно?"

    keyboard = [[
        InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_yes"),
        InlineKeyboardButton("❌ Отменить", callback_data="confirm_no"),
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(summary,
                                  reply_markup=reply_markup,
                                  parse_mode="HTML")
    return CONFIRM_BOOKING


async def confirm_booking(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждение записи — отправка в API."""
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_no":
        await query.edit_message_text(
            "❌ Запись отменена.\nЕсли захотите записаться — нажмите /start",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("◀️ В меню",
                                         callback_data="back_to_menu")
                ],
            ]),
        )
        context.user_data.clear()
        return ConversationHandler.END

    iso_date = to_iso_date(context.user_data["date"])
    telegram_id = get_telegram_id(update)
    phone = context.user_data["phone"]
    comment = context.user_data.get("comment", "")
    staff_id = context.user_data.get("yclients_staff_id", "")
    master_name = context.user_data.get("assigned_employee_name", "")
    yc_service_id = context.user_data.get("yclients_service_id", "")

    payload = {
        "client_name": context.user_data["name"],
        "client_phone": phone,
        "service": context.user_data["service"],
        "booking_date": iso_date,
        "booking_time": context.user_data["time"],
        "comment": comment,
    }
    if yc_service_id:
        payload["yclients_service_id"] = yc_service_id
    if staff_id:
        payload["yclients_staff_id"] = staff_id
    if master_name:
        payload["assigned_employee_name"] = master_name

    # Не дублируем уведомления — они идут только по подписке
    payload["no_notify"] = True

    await _show_loading(query, "⏳ Создаю запись...")

    try:
        resp = requests.post(f"{API_BASE}/api/bookings",
                             json=payload,
                             timeout=15)

        if resp.status_code == 201:
            resp_json = resp.json()
            booking_id = resp_json.get("id", "—")
            client_id = resp_json.get("client_id")

            # ═══════════════════════════════════════════════════════════════
            # ТЕГ: Мои записи — привязка телефона к Telegram ID
            # ═══════════════════════════════════════════════════════════════
            if telegram_id:
                try:
                    requests.post(
                        f"{API_BASE}/api/telegram/link-phone",
                        json={
                            "telegram_id": telegram_id,
                            "phone": phone,
                            "client_name": context.user_data["name"],
                        },
                        timeout=10,
                    )
                except Exception as e:
                    logger.error(f"Ошибка привязки телефона: {e}")

            # ═══════════════════════════════════════════════════════════════
            # ТЕГ: Мои записи — кнопка перехода в раздел
            # ═══════════════════════════════════════════════════════════════
            keyboard = [
                #    [
                #        InlineKeyboardButton("📋 Мои записи",
                #                             callback_data="my_bookings")
                #    ],
                [
                    InlineKeyboardButton("◀️ В меню",
                                         callback_data="back_to_menu")
                ],
            ]

            # ═══════════════════════════════════════════════════════════════
            # ТЕГ: Уведомления (клиентские) — кнопки подписки/отписки
            # после успешного создания записи
            # ═══════════════════════════════════════════════════════════════
            # ═══════════════════════════════════════════════════════════════
            # [СКРЫТО] Кнопки управления уведомлениями
            # Чтобы вернуть их отображение, просто уберите символы # в начале строк ниже
            # ═══════════════════════════════════════════════════════════════
            # if client_id:
            #     try:
            #         status_resp = requests.get(
            #             f"{API_BASE}/api/notifications/status",
            #             params={"client_id": client_id, "provider": "telegram"},
            #             timeout=5,
            #         )
            #         already_linked = status_resp.ok and status_resp.json().get("linked")
            #     except Exception:
            #         already_linked = False
            #
            #     if already_linked:
            #         # Уже подписан → показываем кнопку ОТПИСКИ
            #         keyboard.insert(0, [
            #             InlineKeyboardButton(
            #                 "🔕 Отключить уведомления",
            #                 callback_data=f"unsubscribe_tg_{client_id}"
            #             )
            #         ])
            #     else:
            #         # Не подписан → показываем кнопку ПОДПИСКИ
            #         keyboard.insert(0, [
            #             InlineKeyboardButton(
            #                 "🔔 Получать уведомления о записи",
            #                 callback_data=f"notify_tg_{client_id}"
            #             )
            #         ])

            await query.edit_message_text(
                "✅ <b>Запись успешно создана!</b> 🌸\n"
                f"💇‍♀️ Услуга: {context.user_data['service']}\n"
                f"📅 Дата: {context.user_data['date']}\n"
                f"⏰ Время: {context.user_data['time']}\n"
                "Ждём вас в студии красоты VERBENA! 💅\n",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

        elif resp.status_code == 409:
            await query.edit_message_text(
                "❌ К сожалению, это время уже занято.\nПожалуйста, попробуйте выбрать другое время или дату.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("🔄 Выбрать другое время",
                                             callback_data="book")
                    ],
                    [
                        InlineKeyboardButton("◀️ В меню",
                                             callback_data="back_to_menu")
                    ],
                ]),
            )
        else:
            error_msg = resp.json().get("error", "Неизвестная ошибка")
            await query.edit_message_text(
                f"❌ Ошибка при создании записи: {error_msg}\nПожалуйста, попробуйте позже или запишитесь по телефону +7 (915) 526-50-56",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("◀️ В меню",
                                             callback_data="back_to_menu")
                    ],
                ]),
            )

    except Exception as e:
        logger.error(f"Ошибка создания записи: {e}")
        await query.edit_message_text(
            "❌ Ошибка соединения с сервером.\nПожалуйста, попробуйте позже или запишитесь по телефону:\n📞 +7 (915) 526-50-56",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("◀️ В меню",
                                         callback_data="back_to_menu")
                ],
            ]),
        )

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена диалога."""
    await update.message.reply_text(
        "❌ Диалог прерван. Чтобы начать заново, нажмите /start",
        reply_markup=ReplyKeyboardRemove(),
    )
    context.user_data.clear()
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════
# [ЗАКОММЕНТИРОВАНО] Уведомления (клиентские) — notification_phone_handler
# Обработчик ввода телефона для подписки на уведомления — отключено.
# ═══════════════════════════════════════════════════════════════

# ─── Обработчик обычных сообщений (не в диалоге) ───


async def handle_message(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ответ на любые сообщения вне диалога."""

    if "service" in context.user_data or "date" in context.user_data or "time" in context.user_data:
        return

    text = update.message.text.lower()

    if "запис" in text:
        await start(update, context)
    elif "услуг" in text or "цен" in text:
        await update.message.reply_text(
            "💇‍♀️ Чтобы посмотреть услуги и цены, нажмите /start и выберите "
            "«Услуги и цены».", )
    elif "контакт" in text or "адрес" in text:
        await update.message.reply_text(
            "📍 <b>Студия красоты VERBENA</b>\n"
            "🏠 г. Строитель, ул. Октябрьская, 15\n"
            "🕐 Ежедневно 10:00–20:00\n"
            "📞 +7 (915) 526-50-56",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            "🌸 Я бот студии красоты VERBENA.\n"
            "Используйте /start, чтобы открыть меню.", )


# ─── Главная функция ───


def main() -> None:
    """Запуск бота."""
    # ─── Проверка токена ───
    if not TOKEN:
        logger.critical(
            "BOT_TOKEN не задан! Установите переменную окружения BOT_TOKEN.\n"
            "  export BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11\n"
            "Или укажите токен в /etc/beautyverbena.env")
        raise SystemExit(1)

    logger.info(
        "╭─────────────────────────────────────────────╮\n"
        "│  BeautyVerbenaBot запускается               │\n"
        f"│  TOKEN: {TOKEN[:8]}...{TOKEN[-4:]:>10}  │\n"
        f"│  API_BASE: {API_BASE:<31} │\n"
        f"│  BOT_PROXY: {'задан' if BOT_PROXY else 'нет (прямое подключение)':<20} │\n"
        "╰─────────────────────────────────────────────╯")

    # ─── Настройка прокси для httpx ───
    # httpx (используется python-telegram-bot под капотом) уважает
    # переменные окружения HTTPS_PROXY/HTTP_PROXY. Это самый надёжный
    # способ задать прокси — без возни с httpx.Proxy объектами.
    # Requests для локального API идёт в обход (NO_PROXY).
    if BOT_PROXY:
        logger.info(f"Прокси для Telegram API: {BOT_PROXY}")
        os.environ["HTTPS_PROXY"] = BOT_PROXY
        os.environ["HTTP_PROXY"] = BOT_PROXY
        os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"
    else:
        # Убираем на случай если прокси задан системно
        os.environ.pop("HTTPS_PROXY", None)
        os.environ.pop("HTTP_PROXY", None)
        os.environ.pop("NO_PROXY", None)

    # ─── Создаём HTTPXRequest ───
    # connection_pool_size=1 — минимизируем проблемы с keep-alive
    # через HTTP-прокси (которые сбрасывают idle-соединения)
    # timeout=25 в run_polling — getUpdates завершается до того
    # как прокси оборвёт долгое соединение
    bot_request = HTTPXRequest(
        connection_pool_size=1,
        connect_timeout=90,
        read_timeout=90,
        write_timeout=90,
        pool_timeout=30,
    )

    # ─── Собираем приложение ───
    application = (
        Application.builder().token(TOKEN).request(bot_request).build())

    # ConversationHandler для записи на услугу
    booking_conv = ConversationHandler(
        per_message=False,
        entry_points=[
            CallbackQueryHandler(category_callback, pattern="^cat_"),
        ],
        states={
            SELECT_SERVICE: [
                CallbackQueryHandler(category_callback, pattern="^cat_"),
                CallbackQueryHandler(service_selected, pattern="^svc_"),
                CallbackQueryHandler(back_to_categories,
                                     pattern="^back_to_categories$"),
                CallbackQueryHandler(exit_booking_to_main_menu,
                                     pattern="^back_to_menu$"),
            ],
            SELECT_STAFF: [
                CallbackQueryHandler(staff_selected, pattern="^staff_"),
                CallbackQueryHandler(back_to_categories,
                                     pattern="^back_to_categories$"),
                CallbackQueryHandler(exit_booking_to_main_menu,
                                     pattern="^back_to_menu$"),
            ],
            SELECT_DATE: [
                CallbackQueryHandler(date_page_prev, pattern="^dates_prev$"),
                CallbackQueryHandler(date_page_next, pattern="^dates_next$"),
                CallbackQueryHandler(date_selected, pattern="^date_"),
                CallbackQueryHandler(back_to_date, pattern="^back_to_date$"),
                CallbackQueryHandler(back_to_categories,
                                     pattern="^back_to_categories$"),
            ],
            SELECT_TIME: [
                CallbackQueryHandler(time_selected, pattern="^time_"),
                CallbackQueryHandler(back_to_date, pattern="^back_to_date$"),
            ],
            ENTER_NAME: [
                CallbackQueryHandler(back_to_time, pattern="^back_to_time$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, name_received),
            ],
            ENTER_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               phone_received),
            ],
            ENTER_COMMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               comment_received),
                CallbackQueryHandler(skip_comment, pattern="^skip_comment$"),
            ],
            CONFIRM_BOOKING: [
                CallbackQueryHandler(confirm_booking,
                                     pattern="^(confirm_yes|confirm_no)$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
        ],
        name="booking_conversation",
        persistent=False,
    )

    # ═══════════════════════════════════════════════════════════════
    # [ЗАКОММЕНТИРОВАНО] Уведомления (клиентские) — регистрация обработчика телефона
    # ═══════════════════════════════════════════════════════════════
    # application.add_handler(
    #     MessageHandler(
    #         filters.TEXT & ~filters.COMMAND & filters.UpdateType.MESSAGE,
    #         notification_phone_handler,
    #     ))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(booking_conv)
    # ═══════════════════════════════════════════════════════════════
    # [ЗАКОММЕНТИРОВАНО] Уведомления (клиентские) — show_notifications_settings
    # ═══════════════════════════════════════════════════════════════
    # application.add_handler(
    #     CallbackQueryHandler(show_notifications_settings,
    #                          pattern="^notifications$"))
    # ═══════════════════════════════════════════════════════════════
    # [ЗАКОММЕНТИРОВАНО] Мои записи / Уведомления (клиентские) — main_menu_callback
    # включает паттерны my_bookings и notifications — убраны из regex
    # ═══════════════════════════════════════════════════════════════
    application.add_handler(
        CallbackQueryHandler(
            main_menu_callback,
            pattern=
            "^(book|services|contacts|career|back_to_menu|back_to_categories)$"
        ))
    # ═══════════════════════════════════════════════════════════════
    # Career — заявка на трудоустройство
    # ═══════════════════════════════════════════════════════════════
    application.add_handler(
        CallbackQueryHandler(career_form_handler, pattern="^career_form$"))
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.UpdateType.MESSAGE,
            career_message_handler,
        ))
    # ═══════════════════════════════════════════════════════════════
    # [ЗАКОММЕНТИРОВАНО] Мои записи — cancel_booking_callback
    # ═══════════════════════════════════════════════════════════════
    # application.add_handler(
    #     CallbackQueryHandler(cancel_booking_callback, pattern="^cancel_"))
    # ═══════════════════════════════════════════════════════════════
    # [ЗАКОММЕНТИРОВАНО] Уведомления (клиентские) — notify_link_callback / unsubscribe_callback
    # ═══════════════════════════════════════════════════════════════
    # application.add_handler(
    #     CallbackQueryHandler(notify_link_callback, pattern="^notify_tg_"))
    # application.add_handler(
    #     CallbackQueryHandler(unsubscribe_callback, pattern="^unsubscribe_tg_"))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # ═══════════════════════════════════════════════════════════════
    # Предзагрузка кэша YClients при старте
    # ═══════════════════════════════════════════════════════════════
    logger.info("Предзагрузка кэша YClients...")
    refresh_yc_cache()
    logger.info(
        f"Загружено: {len(_YC_CATEGORIES_CACHE)} категорий, "
        f"{len(_YC_SERVICES_CACHE)} услуг, {len(_YC_STAFF_CACHE)} сотрудников")

    logger.info("Обработчики зарегистрированы. Запускаю polling...")
    try:
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            poll_interval=0.5,
            timeout=25,
        )
    except Exception as e:
        logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА при запуске polling: {e}",
                        exc_info=True)
        raise


if __name__ == "__main__":
    main()