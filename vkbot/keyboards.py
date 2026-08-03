"""
Клавиатуры для VK бота.

Использует inline callback-кнопки VK (Text с payload).
Все меню аналогичны Telegram боту.

Ограничение VK: inline-клавиатура содержит максимум 6 строк (рядов)
и максимум 10 кнопок.
"""
from vkbottle import Keyboard, KeyboardButtonColor, Text

MAX_INLINE_ROWS = 6  # лимит VK для inline-клавиатур
TIMES_PER_PAGE = 6  # слотов времени на одну страницу
DATES_PER_PAGE = 6  # дат на одну страницу
STAFF_PER_PAGE = 4  # мастеров на одну страницу
SERVICES_PER_PAGE = 4  # услуг на одну страницу


def get_menu_button_keyboard() -> Keyboard:
    """
    Постоянная (не inline) клавиатура с кнопкой «Меню».

    Всегда видна под полем ввода, не исчезает после нажатия.
    Отправляет текст «📋 Меню», который возвращает пользователя
    в главное меню (аналог кнопки «Начать»).
    """
    keyboard = Keyboard()
    keyboard.add(Text("📋 Меню"))
    return keyboard


def get_main_menu_keyboard() -> Keyboard:
    """
    Главное меню VK бота.

    🌿 Beauty Verbena

    📅 Записаться
    💅 Услуги
    📍 Контакты
    💼 Хочу работать
    """
    keyboard = Keyboard(inline=True)

    keyboard.add(Text("📅 Записаться", payload={"cmd": "book"}),
                 KeyboardButtonColor.PRIMARY)
    keyboard.row()
    keyboard.add(Text("💅 Услуги и цены", payload={"cmd": "services"}),
                 KeyboardButtonColor.PRIMARY)
    keyboard.row()
    keyboard.add(Text("📍 Контакты", payload={"cmd": "contacts"}),
                 KeyboardButtonColor.PRIMARY)
    keyboard.row()
    keyboard.add(Text("💼 Хочу работать", payload={"cmd": "career"}),
                 KeyboardButtonColor.PRIMARY)

    return keyboard


def get_categories_keyboard(categories: list) -> Keyboard:
    """
    Клавиатура с категориями услуг.

    Args:
        categories: Список категорий [(id, title), ...]
    """
    keyboard = Keyboard(inline=True)

    # Оставляем максимум 5 категорий (5 рядов + ряд «Назад» = 6)
    for cat_id, title in categories[:5]:
        keyboard.add(
            Text(title, payload={
                "cmd": "category",
                "cat_id": str(cat_id)
            }),
            KeyboardButtonColor.PRIMARY,
        )
        keyboard.row()

    keyboard.add(
        Text("️ Назад", payload={"cmd": "back_to_menu"}),
        KeyboardButtonColor.SECONDARY,
    )

    return keyboard


def get_services_keyboard(services: list, page: int = 0) -> Keyboard:
    """
    Клавиатура с услугами категории (с пагинацией).

    Args:
        services: Список услуг [(id, name, price), ...]
        page: Номер страницы (0-based). Показывается по SERVICES_PER_PAGE услуг.

    Если услуг больше SERVICES_PER_PAGE, добавляются кнопки
    «◀️ Назад» / «Вперёд ▶️» для перелистывания, а внизу —
    «◀️ Назад к категориям».
    """
    total_pages = max(1, (len(services) + SERVICES_PER_PAGE - 1) //
                      SERVICES_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * SERVICES_PER_PAGE
    page_services = services[start:start + SERVICES_PER_PAGE]

    keyboard = Keyboard(inline=True)

    MAX_LABEL = 40

    for svc_id, name, price in page_services:
        label = f"{name} — {price}" if price else name

        if len(label) > MAX_LABEL:
            label = label[:MAX_LABEL - 3] + "..."

        keyboard.add(
            Text(label, payload={
                "cmd": "service",
                "svc_id": str(svc_id)
            }),
            KeyboardButtonColor.PRIMARY,
        )
        keyboard.row()

    has_prev = page > 0
    has_next = page < total_pages - 1
    if has_prev or has_next:
        if has_prev:
            keyboard.add(
                Text("◀️ Назад",
                     payload={
                         "cmd": "services_page",
                         "page": page - 1
                     }),
                KeyboardButtonColor.SECONDARY,
            )
        if has_next:
            keyboard.add(
                Text("Вперёд ▶️",
                     payload={
                         "cmd": "services_page",
                         "page": page + 1
                     }),
                KeyboardButtonColor.SECONDARY,
            )
        keyboard.row()

    keyboard.add(
        Text("◀️ Назад к категориям", payload={"cmd": "back_to_categories"}),
        KeyboardButtonColor.SECONDARY,
    )

    return keyboard


def get_staff_keyboard(staff: list, page: int = 0) -> Keyboard:
    """
    Клавиатура с мастерами (с пагинацией).

    Args:
        staff: Список мастеров [{"id": ..., "name": ..., "specialization": ...}, ...]
        page: Номер страницы (0-based). Показывается по STAFF_PER_PAGE мастеров.

    Если мастеров больше STAFF_PER_PAGE, добавляются кнопки
    «◀️ Назад» / «Вперёд ▶️» для перелистывания, а внизу —
    «◀️ Назад» к категориям.
    """
    total_pages = max(1, (len(staff) + STAFF_PER_PAGE - 1) // STAFF_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * STAFF_PER_PAGE
    page_staff = staff[start:start + STAFF_PER_PAGE]

    keyboard = Keyboard(inline=True)

    for s in page_staff:
        name = s.get("name", "Мастер")
        spec = s.get("specialization", "")
        label = f"{name}" + (f" ({spec})" if spec else "")
        keyboard.add(
            Text(label, payload={
                "cmd": "staff",
                "staff_id": str(s["id"])
            }),
            KeyboardButtonColor.PRIMARY,
        )
        keyboard.row()

    has_prev = page > 0
    has_next = page < total_pages - 1
    if has_prev or has_next:
        if has_prev:
            keyboard.add(
                Text("◀️ Назад",
                     payload={
                         "cmd": "staff_page",
                         "page": page - 1
                     }),
                KeyboardButtonColor.SECONDARY,
            )
        if has_next:
            keyboard.add(
                Text("Вперёд ▶️",
                     payload={
                         "cmd": "staff_page",
                         "page": page + 1
                     }),
                KeyboardButtonColor.SECONDARY,
            )
        keyboard.row()

    keyboard.add(
        Text("◀️ Назад", payload={"cmd": "back_to_categories"}),
        KeyboardButtonColor.SECONDARY,
    )

    return keyboard


def get_dates_keyboard(dates: list, page: int = 0) -> Keyboard:
    """
    Клавиатура с датами (с пагинацией).

    Args:
        dates: Список дат в формате ДД.ММ.ГГГГ
        page: Номер страницы (0-based). Показывается по DATES_PER_PAGE дат.

    Если дат больше DATES_PER_PAGE, добавляются кнопки
    «◀️ Назад» / «Вперёд ▶️» для перелистывания, а внизу —
    «◀️ Назад к категориям».
    """
    total_pages = max(1, (len(dates) + DATES_PER_PAGE - 1) // DATES_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * DATES_PER_PAGE
    page_dates = dates[start:start + DATES_PER_PAGE]

    keyboard = Keyboard(inline=True)

    row_count = 0
    for date_str in page_dates:
        # Форматируем: ДД.ММ → ДД.ММ (ДНЬ)
        parts = date_str.split(".")
        if len(parts) == 3:
            day, month, year = parts
            from datetime import datetime
            try:
                d = datetime.strptime(date_str, "%d.%m.%Y")
                day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб",
                            "Вс"][d.weekday()]
                btn_text = f"{day}.{month} ({day_name})"
            except Exception:
                btn_text = f"{day}.{month}"
        else:
            btn_text = date_str

        keyboard.add(
            Text(btn_text, payload={
                "cmd": "date",
                "date": date_str
            }),
            KeyboardButtonColor.PRIMARY,
        )

        row_count += 1
        if row_count % 2 == 0:
            keyboard.row()

    if row_count % 2 != 0:
        keyboard.row()

    has_prev = page > 0
    has_next = page < total_pages - 1
    if has_prev or has_next:
        if has_prev:
            keyboard.add(
                Text("◀️ Назад",
                     payload={
                         "cmd": "dates_page",
                         "page": page - 1
                     }),
                KeyboardButtonColor.SECONDARY,
            )
        if has_next:
            keyboard.add(
                Text("Вперёд ▶️",
                     payload={
                         "cmd": "dates_page",
                         "page": page + 1
                     }),
                KeyboardButtonColor.SECONDARY,
            )
        keyboard.row()

    keyboard.add(
        Text("◀️ Назад", payload={"cmd": "back_to_categories"}),
        KeyboardButtonColor.SECONDARY,
    )

    return keyboard


def get_times_keyboard(times: list, page: int = 0) -> Keyboard:
    """
    Клавиатура со временем (с пагинацией).

    Args:
        times: Список временных слотов ["10:00", "10:15", ...]
        page: Номер страницы (0-based). Показывается по TIMES_PER_PAGE слотов.

    Если слотов больше TIMES_PER_PAGE, добавляются кнопки
    «◀️ Назад» / «Вперёд ▶️» для перелистывания, а внизу —
    «◀️ Назад к дате».
    """
    total_pages = max(1, (len(times) + TIMES_PER_PAGE - 1) // TIMES_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * TIMES_PER_PAGE
    page_times = times[start:start + TIMES_PER_PAGE]

    keyboard = Keyboard(inline=True)

    row_count = 0
    for time_slot in page_times:
        keyboard.add(
            Text(time_slot, payload={
                "cmd": "time",
                "time": time_slot
            }),
            KeyboardButtonColor.PRIMARY,
        )
        row_count += 1
        if row_count % 4 == 0:
            keyboard.row()

    if row_count % 4 != 0:
        keyboard.row()

    has_prev = page > 0
    has_next = page < total_pages - 1
    if has_prev or has_next:
        if has_prev:
            keyboard.add(
                Text("◀️ Назад",
                     payload={
                         "cmd": "times_page",
                         "page": page - 1
                     }),
                KeyboardButtonColor.SECONDARY,
            )
        if has_next:
            keyboard.add(
                Text("Вперёд ▶️",
                     payload={
                         "cmd": "times_page",
                         "page": page + 1
                     }),
                KeyboardButtonColor.SECONDARY,
            )
        keyboard.row()

    keyboard.add(
        Text("◀️ Назад к дате", payload={"cmd": "back_to_date"}),
        KeyboardButtonColor.SECONDARY,
    )

    return keyboard


def get_skip_comment_keyboard() -> Keyboard:
    """Клавиатура с кнопкой пропуска комментария."""
    keyboard = Keyboard(inline=True)
    keyboard.add(
        Text("⏭️ Пропустить", payload={"cmd": "skip_comment"}),
        KeyboardButtonColor.SECONDARY,
    )
    return keyboard


def get_confirm_keyboard() -> Keyboard:
    """Клавиатура подтверждения/отмены записи."""
    keyboard = Keyboard(inline=True)
    keyboard.add(Text("✅ Подтвердить", payload={"cmd": "confirm_yes"}),
                 KeyboardButtonColor.POSITIVE)
    keyboard.row()
    keyboard.add(Text("❌ Отменить", payload={"cmd": "confirm_no"}),
                 KeyboardButtonColor.NEGATIVE)
    return keyboard


def get_back_to_menu_keyboard() -> Keyboard:
    """Клавиатура с кнопкой возврата в меню."""
    keyboard = Keyboard(inline=True)
    keyboard.add(
        Text("◀️ В меню", payload={"cmd": "back_to_menu"}),
        KeyboardButtonColor.SECONDARY,
    )
    return keyboard


def get_career_keyboard() -> Keyboard:
    """Клавиатура для раздела вакансий."""
    keyboard = Keyboard(inline=True)
    keyboard.add(
        Text("📝 Оставить заявку", payload={"cmd": "career_form"}),
        KeyboardButtonColor.PRIMARY,
    )
    keyboard.row()
    keyboard.add(
        Text("◀️ В меню", payload={"cmd": "back_to_menu"}),
        KeyboardButtonColor.SECONDARY,
    )
    return keyboard
