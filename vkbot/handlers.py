"""
Обработчики сообщений VK бота.

Содержит всю логику обработки:
- главное меню
- процесс записи (категория → услуга → мастер → дата → время → имя → телефон → комментарий → подтверждение)
- вакансии
"""
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

import requests
from vkbottle import BaseStateGroup, Keyboard
from vkbottle.bot import Blueprint, Message
from vkbottle.dispatch.rules import OrRule
from vkbottle.dispatch.rules.base import CommandRule, StateRule, TextRule

from .config import API_BASE, VK_GROUP_ID, VK_TOKEN, BOT_TOKEN, BOT_PROXY
from .states import BookingState
from .keyboards import (
    get_menu_button_keyboard,
    get_main_menu_keyboard,
    get_categories_keyboard,
    get_services_keyboard,
    get_staff_keyboard,
    get_dates_keyboard,
    get_times_keyboard,
    get_skip_comment_keyboard,
    get_confirm_keyboard,
    get_back_to_menu_keyboard,
    get_career_keyboard,
)
from .cache import get_cache
from .booking import get_booking_service
from .validators import validate_name, validate_phone, validate_comment

logger = logging.getLogger("vk_bot")

bp = Blueprint("VK Booking Handlers")


async def _get_ctx(message: Message) -> dict:
    """Получить накопленный контекст FSM (payload состояния)."""
    if message.state_peer and message.state_peer.payload:
        return dict(message.state_peer.payload)
    return {}


async def _set_state(message: Message, state: BaseStateGroup,
                     **payload) -> None:
    """Переключить состояние и сохранить контекст FSM."""
    ctx = await _get_ctx(message)
    ctx.update({k: v for k, v in payload.items() if v is not None})
    await bp.state_dispenser.set(message.peer_id, state, **ctx)
    message.state_peer = await bp.state_dispenser.cast(message.peer_id)


async def _clear_state(message: Message) -> None:
    """Очистить состояние FSM."""
    await bp.state_dispenser.delete(message.peer_id)
    message.state_peer = None


async def _typing(message: Message) -> None:
    """Показать статус «печатает…» в диалоге VK на время запроса к бэкенду.

    VK-клиенты показывают этот статус несколько секунд — этого достаточно,
    чтобы пользователь видел, что бот не завис, пока идёт запрос к
    YClients/бэкенду (загрузка дат, времени, создание записи и т.п.).
    Ошибки игнорируются — это не критичный для работы бота индикатор.
    """
    try:
        await message.ctx_api.messages.set_activity(peer_id=message.peer_id,
                                                    type="typing")
    except Exception as e:
        logger.debug(f"Не удалось показать статус 'печатает': {e}")


async def _show_loader(
        message: Message,
        text: str = "⏳ Секунду, гружу данные…") -> Optional[int]:
    """Отправить сообщение-лоадер и вернуть его message_id.

    Возвращает None, если отправить не удалось — тогда _finish_loader
    просто пришлёт обычное новое сообщение с финальным ответом.
    """
    try:
        return await message.answer(text)
    except Exception as e:
        logger.debug(f"Не удалось отправить сообщение-лоадер: {e}")
        return None


async def _finish_loader(message: Message,
                         loader_id: Optional[int],
                         text: str,
                         keyboard: Optional[str] = None) -> None:
    """Заменить сообщение-лоадер финальным текстом/клавиатурой.

    Если лоадер не отправился (loader_id is None) или отредактировать
    его не удалось (например, VK отклонил messages.edit) — отправляет
    обычное новое сообщение, чтобы пользователь в любом случае получил
    ответ.
    """
    if loader_id is None:
        await message.answer(text, keyboard=keyboard)
        return

    try:
        kwargs = {
            "peer_id": message.peer_id,
            "message_id": loader_id,
            "message": text,
        }
        if keyboard is not None:
            kwargs["keyboard"] = keyboard
        await message.ctx_api.messages.edit(**kwargs)
    except Exception as e:
        logger.debug(f"Не удалось отредактировать сообщение-лоадер: {e}")
        await message.answer(text, keyboard=keyboard)


def _kb(keyboard: Keyboard) -> str:
    """Сконвертировать Keyboard в JSON-строку для Message.answer().

    VK запрещает поле one_time для inline-клавиатур (ошибка 911),
    поэтому для inline удаляем one_time из JSON.
    """
    data = json.loads(keyboard.get_json())
    if data.get("inline"):
        data.pop("one_time", None)
    return json.dumps(data, ensure_ascii=False)


MAIN_MENU_TEXT = (
    "🌸 Добро пожаловать в VERBENA — студию красоты!\n\n"
    "Здесь вы можете записаться на услуги, посмотреть свои записи "
    "и узнать больше о нашей студии.\n\n"
    "📍 г. Строитель, ул. Октябрьская, 15\n"
    "🕐 Ежедневно 10:00–20:00\n"
    "📞 +7 (915) 526-50-56\n"
    "🌐 https://beauty-verbena.ru\n\n"
    "Выберите действие:")


@bp.on.message(
    OrRule(
        CommandRule("start"),
        CommandRule("menu"),
        TextRule(["Начать", "Start", "Меню", "📋 Меню"], ignore_case=True),
    ))
async def start_handler(message: Message):
    """Приветствие и главное меню."""

    await bp.state_dispenser.delete(message.peer_id)
    await bp.state_dispenser.set(message.peer_id, BookingState.START)

    await message.answer(MAIN_MENU_TEXT,
                         keyboard=_kb(get_main_menu_keyboard()))

    await message.answer(
        "Кнопка «📋 Меню» всегда доступна под полем ввода — "
        "нажмите её, чтобы вернуться в главное меню.",
        keyboard=_kb(get_menu_button_keyboard()),
    )


@bp.on.message(StateRule(BookingState.START))
async def main_menu_handler(message: Message):
    """Обработка кнопок главного меню."""
    payload = message.get_payload_json() or {}
    cmd = payload.get("cmd")

    if cmd == "book":
        await show_categories(message)
    elif cmd == "services":
        await show_services_list(message)
    elif cmd == "contacts":
        await show_contacts(message)
    elif cmd == "career":
        await show_career(message)
    elif cmd == "back_to_menu":
        await bp.state_dispenser.delete(message.peer_id)
        await bp.state_dispenser.set(message.peer_id, BookingState.START)
        await message.answer(MAIN_MENU_TEXT,
                             keyboard=_kb(get_main_menu_keyboard()))


async def show_categories(message: Message):
    """Показать категории услуг."""
    await _set_state(message, BookingState.CATEGORY)

    await _typing(message)
    loader_id = await _show_loader(message)
    cache = get_cache(API_BASE)
    await cache.refresh_cache_async()

    categories = []
    if cache.categories and cache.services:
        for cat in cache.categories:
            cat_id = cat.get("id")
            title = cat.get("title") or "Услуги"
            if cat_id is not None and cache.get_services_for_category(cat_id):
                categories.append((cat_id, title))

    if not categories:
        categories = [
            ("manicure", "💅 Маникюр"),
            ("brows", "✏️ Брови"),
            ("hair", "💇‍♀️ Парикмахерские"),
        ]

    await _finish_loader(message,
                         loader_id,
                         "Выберите категорию услуги:",
                         keyboard=_kb(get_categories_keyboard(categories)))


@bp.on.message(StateRule(BookingState.CATEGORY))
async def category_handler(message: Message):
    """Обработка выбора категории."""
    payload = message.get_payload_json() or {}
    cmd = payload.get("cmd")

    if cmd == "category":
        cat_id = payload.get("cat_id")
        await show_services_for_category(message, cat_id)
        await _set_state(message, BookingState.SERVICE)
    elif cmd == "back_to_menu":
        await bp.state_dispenser.set(message.peer_id, BookingState.START)
        await message.answer(MAIN_MENU_TEXT,
                             keyboard=_kb(get_main_menu_keyboard()))
    elif cmd == "back_to_categories":
        await show_categories(message)


async def show_services_for_category(message: Message, category_id: str):
    """Показать услуги категории."""
    cache = get_cache(API_BASE)

    yc_category = None
    if cache.categories:
        for cat in cache.categories:
            if str(cat.get("id")) == str(category_id):
                yc_category = cat
                break

    services = []
    display_name = "Услуги"

    if yc_category:
        display_name = yc_category.get("title") or "Услуги"
        real_services = cache.get_services_for_category(category_id)
        for svc in real_services:
            svc_id = svc.get("id")
            title = svc.get("title", "Услуга")
            pmin = svc.get("price_min")
            pmax = svc.get("price_max")
            if pmin and pmax and pmin != pmax:
                price = f"{int(pmin)}–{int(pmax)} ₽"
            elif pmin:
                price = f"{int(pmin)} ₽"
            else:
                price = ""
            services.append((svc_id, title, price))
    else:
        display_name = category_id
        services = []

    if not services:
        await message.answer("❌ Ошибка: категория не найдена")
        return

    await _set_state(message,
                     BookingState.SERVICE,
                     available_services=services)
    await message.answer(f"{display_name}\n\nВыберите услугу:",
                         keyboard=_kb(get_services_keyboard(services)))


@bp.on.message(StateRule(BookingState.SERVICE))
async def service_handler(message: Message):
    """Обработка выбора услуги."""
    payload = message.get_payload_json() or {}
    cmd = payload.get("cmd")

    if cmd == "service":
        svc_id = payload.get("svc_id")
        await handle_service_selected(message, svc_id)
    elif cmd == "services_page":
        ctx = await _get_ctx(message)
        services = ctx.get("available_services") or []
        page = int(payload.get("page", 0))
        display_name = payload.get("title", "Услуги")
        await message.answer(f"{display_name}\n\nВыберите услугу:",
                             keyboard=_kb(
                                 get_services_keyboard(services, page=page)))
    elif cmd == "back_to_categories":
        await _set_state(message, BookingState.CATEGORY)
        await show_categories(message)


async def handle_service_selected(message: Message, service_id: str):
    """Услуга выбрана — показываем мастеров или дату."""
    cache = get_cache(API_BASE)

    yc_service = None
    for svc in cache.services:
        if str(svc.get("id")) == str(service_id):
            yc_service = svc
            break

    if yc_service:
        service_name = yc_service.get("title", "Услуга")
        staff = cache.get_staff_for_service(service_id=yc_service["id"])
        await _set_state(
            message,
            BookingState.SERVICE,
            service=service_name,
            yclients_service_id=str(yc_service["id"]),
        )
    else:
        service_name = "Услуга"
        await _set_state(message, BookingState.SERVICE, service=service_name)
        staff = cache.staff

    if staff:
        await _set_state(message, BookingState.MASTER, available_staff=staff)
        await message.answer(f"💇‍♀️ Услуга: {service_name}\n\n",
                             keyboard=_kb(get_staff_keyboard(staff)))
    else:
        await _set_state(message, BookingState.MASTER)
        await show_date_selection(message, service_name)


@bp.on.message(StateRule(BookingState.MASTER))
async def master_handler(message: Message):
    """Обработка выбора мастера."""
    payload = message.get_payload_json() or {}
    cmd = payload.get("cmd")

    if cmd == "staff":
        staff_id = payload.get("staff_id")
        await handle_staff_selected(message, staff_id)
    elif cmd == "staff_page":
        ctx = await _get_ctx(message)
        staff = ctx.get("available_staff") or []
        page = int(payload.get("page", 0))
        service_name = ctx.get("service", "Услуга")
        await message.answer(f"💇‍♀️ Услуга: {service_name}\n\n",
                             keyboard=_kb(get_staff_keyboard(staff,
                                                             page=page)))
    elif cmd == "back_to_categories":
        await _set_state(message, BookingState.CATEGORY)
        await show_categories(message)


async def handle_staff_selected(message: Message, staff_id: str):
    """Мастер выбран — показываем даты."""
    cache = get_cache(API_BASE)

    if staff_id and staff_id != "0":
        assigned_employee_name = ""
        for s in cache.staff:
            if str(s["id"]) == str(staff_id):
                assigned_employee_name = s.get("name", "Мастер")
                break
        await _set_state(
            message,
            BookingState.MASTER,
            yclients_staff_id=staff_id,
            assigned_employee_name=assigned_employee_name,
        )
    else:
        await _set_state(
            message,
            BookingState.MASTER,
            yclients_staff_id="",
            assigned_employee_name="",
        )

    ctx = await _get_ctx(message)
    service_name = ctx.get("service", "Услуга")
    await show_date_selection(message, service_name)


DATE_WINDOW_DAYS = 60

MAX_BOOKING_DAYS = 365

_NAV_CACHE_TTL = 60  # секунд


def _get_cached_available_dates(booking_service,
                                service_id,
                                staff_id,
                                ctx: dict,
                                days: int = DATE_WINDOW_DAYS):
    """Доступные даты (ДД.ММ.ГГГГ) в пределах ближайших `days` дней.

    Получение и HTTP-запросы к /api/yclients/available-dates делегированы
    в booking_service.load_available_dates (общий модуль booking.py,
    используемый и Telegram-, и VK-ботом) — она сама учитывает, что окно
    может захватывать несколько календарных месяцев.

    Результат кэшируется в ctx (payload состояния FSM) на
    _NAV_CACHE_TTL секунд, чтобы при листании страниц/возврате назад не
    дёргать YClients повторно на каждый клик — вызывающий код должен сам
    сохранить обновлённый ctx через _set_state, чтобы кэш пережил
    следующий клик. Возвращает None, если получить данные не удалось
    (сигнал не фильтровать даты)."""
    cache = ctx.get("_dates_cache")
    cache_key = f"{service_id}:{staff_id}:{days}"

    if cache and cache.get("key") == cache_key:
        age = datetime.now().timestamp() - cache.get("ts", 0)
        if age < _NAV_CACHE_TTL:
            return cache["data"]

    dates = booking_service.load_available_dates(service_id,
                                                 staff_id,
                                                 days=days)

    if dates is None:
        return None

    ctx["_dates_cache"] = {
        "key": cache_key,
        "ts": datetime.now().timestamp(),
        "data": dates,
    }

    return dates


async def show_date_selection(message: Message,
                              service_name: str,
                              page: int = 0):
    """Показать выбор даты (с пагинацией).

    Показываются только даты, на которые есть хотя бы один свободный
    слот — проверяется через booking_service.load_available_dates
    (та же логика, что и в Telegram-боте). Если услуга не привязана к
    YClients или API недоступен, показываются ближайшие дни без
    фильтрации.
    """
    ctx = await _get_ctx(message)

    service_id = ctx.get("yclients_service_id", "")
    staff_id = ctx.get("yclients_staff_id", "")

    dates = None
    loader_id = None

    if service_id:

        cache_key = f"{service_id}:{staff_id}:{DATE_WINDOW_DAYS}"
        dates_cache = ctx.get("_dates_cache")
        cache_fresh = (dates_cache and dates_cache.get("key") == cache_key
                       and (datetime.now().timestamp() -
                            dates_cache.get("ts", 0)) < _NAV_CACHE_TTL)
        if not cache_fresh:
            await _typing(message)
            loader_id = await _show_loader(message, "⏳ Ищу свободные даты…")

        booking_service = get_booking_service(API_BASE)
        dates = _get_cached_available_dates(booking_service,
                                            service_id,
                                            staff_id,
                                            ctx,
                                            days=DATE_WINDOW_DAYS)

    if dates is None:

        today = datetime.now().date()
        dates = [(today + timedelta(days=i)).strftime("%d.%m.%Y")
                 for i in range(MAX_BOOKING_DAYS)]

    ctx["available_dates"] = dates
    await _set_state(message, BookingState.DATE, **ctx)

    if not dates:
        await _finish_loader(
            message,
            loader_id, f"💇‍♀️ Услуга: {service_name}\n\n"
            "😔 На ближайшие даты нет свободных записей. "
            "Попробуйте выбрать другого мастера или загляните позже.",
            keyboard=_kb(get_dates_keyboard(dates, page=page)))
        return

    await _finish_loader(message,
                         loader_id, f"💇‍♀️ Услуга: {service_name}\n\n"
                         "📅 Выберите удобную дату:",
                         keyboard=_kb(get_dates_keyboard(dates, page=page)))


@bp.on.message(StateRule(BookingState.DATE))
async def date_handler(message: Message):
    """Обработка выбора даты."""
    payload = message.get_payload_json() or {}
    cmd = payload.get("cmd")

    if cmd == "date":
        date_str = payload.get("date")
        await handle_date_selected(message, date_str)
    elif cmd == "dates_page":
        ctx = await _get_ctx(message)
        page = int(payload.get("page", 0))
        await show_date_selection(message,
                                  ctx.get("service", "Услуга"),
                                  page=page)
    elif cmd == "back_to_date":
        ctx = await _get_ctx(message)
        await show_date_selection(message, ctx.get("service", "Услуга"))
    elif cmd == "back_to_categories":
        await _set_state(message, BookingState.CATEGORY)
        await show_categories(message)


async def handle_date_selected(message: Message, date_str: str):
    """Дата выбрана — загружаем время."""
    ctx = await _get_ctx(message)
    ctx["date"] = date_str

    service_id = ctx.get("yclients_service_id", "")
    staff_id = ctx.get("yclients_staff_id", "")

    booking_service = get_booking_service(API_BASE)

    if not staff_id and service_id:
        staff = booking_service.load_staff(service_id=service_id)
        if staff:
            staff_id = str(staff[0]["id"])
            ctx["yclients_staff_id"] = staff_id

    available_times = []
    loader_id = None
    if service_id and staff_id:
        await _typing(message)
        loader_id = await _show_loader(message, "⏳ Смотрю свободное время…")
        available_times = booking_service.load_available_times(
            service_id=service_id, staff_id=staff_id, date_str=date_str)

    await _set_state(message, BookingState.DATE, **ctx)

    if not available_times:
        await _finish_loader(
            message,
            loader_id, "😔 На эту дату нет свободного времени. "
            "Пожалуйста, выберите другую дату.",
            keyboard=_kb(get_dates_keyboard(ctx.get("available_dates") or [])))
        return

    service_name = ctx.get("service", "Услуга")

    ctx["available_times"] = available_times
    await _set_state(message, BookingState.TIME, **ctx)
    await _finish_loader(
        message,
        loader_id,
        f"💇‍♀️ Услуга: {service_name}\n"
        f"📅 Дата: {date_str}\n"
        "⏰ Выберите время:",
        keyboard=_kb(get_times_keyboard(available_times)),
    )


@bp.on.message(StateRule(BookingState.TIME))
async def time_handler(message: Message):
    """Обработка выбора времени."""
    payload = message.get_payload_json() or {}
    cmd = payload.get("cmd")

    if cmd == "time":
        time_str = payload.get("time")
        await handle_time_selected(message, time_str)
    elif cmd == "times_page":
        ctx = await _get_ctx(message)
        times = ctx.get("available_times") or []
        page = int(payload.get("page", 0))
        service_name = ctx.get("service", "Услуга")
        date_str = ctx.get("date", "")
        await message.answer(
            f"💇‍♀️ Услуга: {service_name}\n"
            f"📅 Дата: {date_str}\n"
            "⏰ Выберите время:",
            keyboard=_kb(get_times_keyboard(times, page=page)),
        )
    elif cmd == "back_to_date":
        ctx = await _get_ctx(message)
        service_name = ctx.get("service", "Услуга")
        await show_date_selection(message, service_name)


async def handle_time_selected(message: Message, time_str: str):
    """Время выбрано — запрашиваем имя."""
    ctx = await _get_ctx(message)
    ctx["time"] = time_str
    await _set_state(message, BookingState.NAME, **ctx)

    service_name = ctx.get("service", "Услуга")
    date_str = ctx.get("date", "")

    await message.answer(f"💇‍♀️ Услуга: {service_name}\n"
                         f"📅 Дата: {date_str}\n"
                         f"⏰ Время: {time_str}\n\n"
                         "👤 Введите ваше имя:")


@bp.on.message(StateRule(BookingState.NAME))
async def name_handler(message: Message):
    """Обработка ввода имени."""
    name = message.text.strip()

    valid, error = validate_name(name)
    if not valid:
        await message.answer(f"❌ {error}. Попробуйте снова:")
        return

    ctx = await _get_ctx(message)
    ctx["name"] = name
    await _set_state(message, BookingState.PHONE, **ctx)

    await message.answer(f"👤 Имя: {name}\n\n"
                         "📞 Введите ваш номер телефона для связи.\n"
                         "Например: +79155265056")


@bp.on.message(StateRule(BookingState.PHONE))
async def phone_handler(message: Message):
    """Обработка ввода телефона."""
    phone = message.text.strip()

    valid, result = validate_phone(phone)
    if not valid:
        await message.answer(f"❌ {result}\n"
                             "Например: +79155265056")
        return

    ctx = await _get_ctx(message)
    ctx["phone"] = result
    await _set_state(message, BookingState.COMMENT, **ctx)

    await message.answer(
        f"👤 Имя: {ctx.get('name')}\n"
        f"📞 Телефон: {result}\n\n"
        "💬 Если хотите, оставьте комментарий к записи\n"
        "(или нажмите «Пропустить»):",
        keyboard=_kb(get_skip_comment_keyboard()))


@bp.on.message(StateRule(BookingState.COMMENT))
async def comment_handler(message: Message):
    """Обработка ввода комментария."""
    payload = message.get_payload_json() or {}
    if payload.get("cmd") == "skip_comment":
        ctx = await _get_ctx(message)
        ctx["comment"] = ""
        await _set_state(message, BookingState.CONFIRM, **ctx)
        await show_confirmation(message)
        return

    comment = message.text.strip()
    valid, result = validate_comment(comment)
    ctx = await _get_ctx(message)
    ctx["comment"] = result
    await _set_state(message, BookingState.CONFIRM, **ctx)

    await show_confirmation(message)


async def show_confirmation(message: Message):
    """Показать подтверждение записи."""
    ctx = await _get_ctx(message)
    phone = ctx.get("phone", "")
    comment = ctx.get("comment", "")
    master = ctx.get("assigned_employee_name", "")

    summary = ("📋 Проверьте данные записи:\n\n"
               f"💇‍♀️ Услуга: {ctx.get('service')}\n"
               f"📅 Дата: {ctx.get('date')}\n"
               f"⏰ Время: {ctx.get('time')}\n"
               f"👤 Имя: {ctx.get('name')}\n"
               f"📞 Телефон: {phone}\n")

    if master:
        summary += f"👩‍🎨 Мастер: {master}\n"

    if comment:
        summary += f"💬 Комментарий: {comment}\n"

    summary += "\nВсё верно?"

    await message.answer(summary, keyboard=_kb(get_confirm_keyboard()))


@bp.on.message(StateRule(BookingState.CONFIRM))
async def confirm_handler(message: Message):
    """Подтверждение/отмена записи."""
    payload = message.get_payload_json() or {}
    cmd = payload.get("cmd")

    if cmd == "confirm_no":
        await message.answer(
            "❌ Запись отменена.\nЕсли захотите записаться — напишите /start",
            keyboard=_kb(get_back_to_menu_keyboard()))
        await _clear_state(message)
        return

    if cmd == "confirm_yes":
        await create_booking(message)


async def create_booking(message: Message):
    """Создать запись через API."""
    await _typing(message)
    loader_id = await _show_loader(message, "⏳ Создаю запись…")
    booking_service = get_booking_service(API_BASE)
    ctx = await _get_ctx(message)

    success, booking_id, error = booking_service.create_booking(
        client_name=ctx.get("name", ""),
        client_phone=ctx.get("phone", ""),
        service=ctx.get("service", ""),
        booking_date=ctx.get("date", ""),
        booking_time=ctx.get("time", ""),
        comment=ctx.get("comment", ""),
        yclients_service_id=ctx.get("yclients_service_id"),
        yclients_staff_id=ctx.get("yclients_staff_id"),
        assigned_employee_name=ctx.get("assigned_employee_name"),
        vk_id=str(message.from_id),
        source="vk")

    if success:

        await _finish_loader(message,
                             loader_id, "✅ Запись успешно создана! 🌸\n"
                             f"💇‍♀️ Услуга: {ctx.get('service')}\n"
                             f"📅 Дата: {ctx.get('date')}\n"
                             f"⏰ Время: {ctx.get('time')}\n"
                             "Ждём вас в студии красоты VERBENA! 💅\n",
                             keyboard=_kb(get_back_to_menu_keyboard()))
    else:
        if error == "Это время уже занято":
            await _finish_loader(
                message,
                loader_id, "❌ К сожалению, это время уже занято.\n"
                "Пожалуйста, попробуйте выбрать другое время или дату.",
                keyboard=_kb(get_back_to_menu_keyboard()))
        else:
            await _finish_loader(
                message,
                loader_id, f"❌ Ошибка при создании записи: {error}\n"
                "Пожалуйста, попробуйте позже или запишитесь по телефону +7 (915) 526-50-56",
                keyboard=_kb(get_back_to_menu_keyboard()))

    await _clear_state(message)


def send_telegram_notifications(booking_data: dict):
    """Отправить уведомления о новой записи всем подписанным сотрудникам.

    Унаследовано из telegrambot/BeautyVerbenaBot.py (send_notifications).
    Сотрудники подписываются в админке: admin.html → «Уведомления» → Telegram ID.
    """
    if not BOT_TOKEN:
        logger.warning(
            "BOT_TOKEN не задан — уведомления Telegram не отправлены")
        return

    try:
        import requests as _requests

        proxies = None
        if BOT_PROXY:
            proxies = {"https": BOT_PROXY, "http": BOT_PROXY}

        resp = _requests.get(f"{API_BASE}/api/telegram/notify-users",
                             timeout=15)
        if resp.status_code != 200:
            logger.info(f"notify-users вернул {resp.status_code}, пропускаем")
            return
        users = resp.json()
        if not users:
            logger.info("Нет пользователей с notify_enabled=1")
            return

        date_str = booking_data.get("date", "")
        parts = date_str.split(".")
        if len(parts) == 3 and len(parts[2]) == 4:
            date_display = f"{parts[2]}-{parts[1]}-{parts[0]}"
        else:
            date_display = date_str

        message = (
            "📢 <b>Новая запись!</b>\n\n"
            f"👤 Клиент: {booking_data.get('name', '')}\n"
            f"💇‍♀️ Услуга: {booking_data.get('service', '')}\n"
            f"📅 Дата: {date_display}\n"
            f"⏰ Время: {booking_data.get('time', '')}\n"
            f"📞 Телефон: {booking_data.get('phone', '')}\n\n"
            "🔗 <a href='https://yclients.com/dashboard_records/2101920'>Управлять записями Verbena</a>"
        )

        for user in users:
            tg_id = user.get("telegram_id", "").strip()
            if not tg_id or not tg_id.isdigit():
                continue
            try:
                r = _requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": int(tg_id),
                        "text": message,
                        "parse_mode": "HTML",
                    },
                    timeout=15,
                    proxies=proxies,
                )
                if r.status_code != 200:
                    logger.error(f"Ошибка отправки уведомления {tg_id}: "
                                 f"HTTP {r.status_code} — {r.text[:200]}")
                else:
                    logger.info(f"Уведомление отправлено пользователю {tg_id}")
            except Exception as e:
                logger.error(
                    f"Ошибка отправки уведомления пользователю {tg_id}: {e}")
    except Exception as e:
        logger.error(f"Ошибка получения списка уведомляемых: {e}")


def send_vk_notifications(booking_data: dict):
    """Отправить уведомления о новой записи через VK API.

    Рассылается тем сотрудникам админки, которые указали VK ID
    (admin.html → «Уведомления» → VK ID) и включили уведомления.
    Текст использует VK-разметку (**жирный**, _курсив_).
    """
    if not VK_TOKEN:
        logger.warning("VK_TOKEN не задан — VK-уведомления не отправлены")
        return

    try:
        import requests as _requests

        resp = _requests.get(f"{API_BASE}/api/vk/notify-users", timeout=15)
        if resp.status_code == 404:
            logger.error(
                "GET %s/api/vk/notify-users вернул 404 — вероятно, backend не перезапущен "
                "после добавления эндпоинта, либо API_BASE указывает не на тот сервер. "
                "Проверьте: curl -s %s/api/vk/notify-users и перезапустите backend.",
                API_BASE,
                API_BASE,
            )
            return
        if resp.status_code != 200:
            logger.info(
                f"vk/notify-users вернул {resp.status_code}, пропускаем")
            return
        users = resp.json()
        if not users:
            logger.info("Нет пользователей с VK-уведомлениями")
            return

        date_str = booking_data.get("date", "")
        parts = date_str.split(".")
        if len(parts) == 3 and len(parts[2]) == 4:
            date_display = f"{parts[2]}-{parts[1]}-{parts[0]}"
        else:
            date_display = date_str

        message = (
            "📢 Новая запись!\n\n"
            f"👤 Клиент: {booking_data.get('name', '')}\n"
            f"💇‍♀️ Услуга: {booking_data.get('service', '')}\n"
            f"📅 Дата: {date_display}\n"
            f"⏰ Время: {booking_data.get('time', '')}\n"
            f"📞 Телефон: {booking_data.get('phone', '')}\n\n"
            "🔗 Управлять записями Verbena: https://yclients.com/dashboard_records/2101920"
        )

        for user in users:
            vk_id = user.get("vk_id", "").strip()
            if not vk_id or not vk_id.lstrip("-").isdigit():
                continue
            try:
                r = _requests.post(
                    "https://api.vk.com/method/messages.send",
                    data={
                        "access_token": VK_TOKEN,
                        "v": "5.199",
                        "user_id": int(vk_id),
                        "message": message,
                        "random_id": 0,
                    },
                    timeout=15,
                )
                data = r.json()
                if r.status_code != 200 or data.get("error"):
                    logger.error(
                        f"Ошибка отправки VK-уведомления {vk_id}: {data}")
                else:
                    logger.info(
                        f"VK-уведомление отправлено пользователю {vk_id}")
            except Exception as e:
                logger.error(
                    f"Ошибка отправки VK-уведомления пользователю {vk_id}: {e}"
                )
    except Exception as e:
        logger.error(f"Ошибка получения списка VK-уведомляемых: {e}")


async def show_services_list(message: Message):
    """Показать все услуги с ценами."""
    await _typing(message)
    loader_id = await _show_loader(message, "⏳ Загружаю услуги и цены…")
    cache = get_cache(API_BASE)
    await cache.refresh_cache_async()

    text = "💇‍♀️ Наши услуги и цены\n\n"

    if cache.categories and cache.services:
        for cat in cache.categories:
            cat_id = cat.get("id")
            title = cat.get("title") or "Услуги"
            text += f"{title}\n"
            for svc in cache.get_services_for_category(cat_id):
                pmin = svc.get("price_min")
                pmax = svc.get("price_max")
                if pmin and pmax and pmin != pmax:
                    price = f"{int(pmin)}–{int(pmax)} ₽"
                elif pmin:
                    price = f"{int(pmin)} ₽"
                else:
                    price = ""
                text += f"  • {svc.get('title', 'Услуга')}" + (
                    f" — {price}" if price else "") + "\n"
            text += "\n"

    text += "\nЧтобы записаться, нажмите «Записаться» в меню."

    await _finish_loader(message,
                         loader_id,
                         text,
                         keyboard=_kb(get_back_to_menu_keyboard()))


async def show_contacts(message: Message):
    """Показать контактную информацию."""
    text = (
        "📍 Студия красоты VERBENA\n"
        "🏠 Адрес: г. Строитель, ул. Октябрьская, 15\n"
        "🕐 Режим работы: Ежедневно 10:00–20:00\n"
        "📞 Телефон: +7 (915) 526-50-56\n"
        "🔗 Сайт: https://beauty-verbena.ru\n\n"
        "🌐 Мы в соцсетях:\n"
        "• ВКонтакте: https://vk.ru/verbena.studio31\n"
        "• Telegram: https://t.me/verbenastudio31\n"
        "• MAX: https://max.ru/join/pa9K0R9aGl3Q02_N0A6pvklfZfixDfIVIFgJFKz25Lg\n"
        "• Instagram: https://www.instagram.com/verbena_studio31")

    await message.answer(text, keyboard=_kb(get_back_to_menu_keyboard()))


async def show_career(message: Message):
    """Показать информацию о вакансиях."""
    text = ("🤝 Хотите присоединиться к команде VERBENA?\n\n"
            "Мы создаём пространство, где красота встречается с "
            "профессионализмом, заботой и вдохновением.\n\n"
            "Если ты любишь своё дело, стремишься развиваться и хочешь "
            "работать в атмосфере уважения и поддержки — "
            "мы будем рады познакомиться с тобой.\n\n"
            "Напишите нам:\n"
            "• Ваше имя\n"
            "• Телефон\n"
            "• Опыт работы\n"
            "• Ссылка на портфолио/резюме (необязательно)\n"
            "• Сопроводительное письмо (необязательно)\n\n"
            "Мы обязательно рассмотрим вашу заявку!")

    await message.answer(text, keyboard=_kb(get_career_keyboard()))


@bp.on.message(StateRule(BookingState.CAREER_NAME))
async def career_name_handler(message: Message):
    """Начало заявки на трудоустройство — ввод имени."""
    name = message.text.strip()
    valid, error = validate_name(name)

    if not valid:
        await message.answer(f"❌ {error}. Попробуйте снова:")
        return

    ctx = await _get_ctx(message)
    ctx["career_name"] = name
    await _set_state(message, BookingState.CAREER_PHONE, **ctx)
    await message.answer(
        f"👤 Имя: {name}\nШаг 2 из 5\nВведите ваш номер телефона:")


@bp.on.message(StateRule(BookingState.CAREER_PHONE))
async def career_phone_handler(message: Message):
    """Заявка на трудоустройство — ввод телефона."""
    phone = message.text.strip()
    valid, result = validate_phone(phone)

    if not valid:
        await message.answer(f"❌ {result}\nПопробуйте снова:")
        return

    ctx = await _get_ctx(message)
    ctx["career_phone"] = result
    await _set_state(message, BookingState.CAREER_EXPERIENCE, **ctx)
    await message.answer(
        f"📞 Телефон: {result}\n\nШаг 3 из 5\n\nРасскажите о вашем опыте работы:"
    )


@bp.on.message(StateRule(BookingState.CAREER_EXPERIENCE))
async def career_experience_handler(message: Message):
    """Заявка на трудоустройство — опыт работы."""
    experience = message.text.strip()

    if len(experience) < 3:
        await message.answer("❌ Пожалуйста, опишите ваш опыт работы подробнее:"
                             )
        return

    ctx = await _get_ctx(message)
    ctx["career_experience"] = experience
    await _set_state(message, BookingState.CAREER_RESUME, **ctx)
    await message.answer(
        f"💼 Опыт: {experience}\n\nШаг 4 из 5\n\n"
        "Ссылка на резюме или портфолио (необязательно, отправьте «-» чтобы пропустить):"
    )


@bp.on.message(StateRule(BookingState.CAREER_RESUME))
async def career_resume_handler(message: Message):
    """Заявка на трудоустройство — резюме."""
    resume = message.text.strip()

    ctx = await _get_ctx(message)
    ctx["career_resume"] = resume if resume != "-" else ""
    await _set_state(message, BookingState.CAREER_LETTER, **ctx)
    await message.answer(
        "Шаг 5 из 5\n\n"
        "Сопроводительное письмо (необязательно, отправьте «-» чтобы пропустить):"
    )


@bp.on.message(StateRule(BookingState.CAREER_LETTER))
async def career_letter_handler(message: Message):
    """Заявка на трудоустройство — сопроводительное письмо."""
    cover_letter = message.text.strip()

    ctx = await _get_ctx(message)
    ctx["career_cover_letter"] = cover_letter if cover_letter != "-" else ""
    await _set_state(message, BookingState.CAREER_LETTER, **ctx)

    await submit_career_application(message)


async def submit_career_application(message: Message):
    """Отправить заявку на трудоустройство."""
    import requests

    await _typing(message)
    loader_id = await _show_loader(message, "⏳ Отправляю заявку…")
    ctx = await _get_ctx(message)

    payload = {
        "client_name": ctx.get("career_name", ""),
        "client_phone": ctx.get("career_phone", ""),
        "experience": ctx.get("career_experience", ""),
        "resume": ctx.get("career_resume", ""),
        "cover_letter": ctx.get("career_cover_letter", ""),
        "source": "vk",
        "vk_id": str(message.from_id),
    }

    try:
        resp = requests.post(f"{API_BASE}/api/career/submit",
                             json=payload,
                             timeout=10)
        if resp.status_code in (200, 201):
            await _finish_loader(
                message, loader_id, "✅ Отклик отправлен!\n"
                "Мы свяжемся с вами в ближайшее время.\n"
                "Спасибо за интерес к работе в VERBENA! 🌸")
        else:
            await _finish_loader(message, loader_id,
                                 "✅ Ваша заявка принята! Мы свяжемся с вами.")
    except Exception:
        await _finish_loader(message, loader_id,
                             "✅ Ваша заявка принята! Мы свяжемся с вами.")

    await _clear_state(message)
    await message.answer(MAIN_MENU_TEXT,
                         keyboard=_kb(get_main_menu_keyboard()))


@bp.on.message()
async def fallback_handler(message: Message):
    """Возврат в главное меню при любом нераспознанном вводе.

    Срабатывает, когда состояние FSM потеряно (например, после
    перезапуска бота) или пользователь отправил произвольный текст.
    """
    await bp.state_dispenser.delete(message.peer_id)
    await bp.state_dispenser.set(message.peer_id, BookingState.START)

    await message.answer("🤖 Я вас не понял. Давайте вернёмся в главное меню:",
                         keyboard=_kb(get_main_menu_keyboard()))
