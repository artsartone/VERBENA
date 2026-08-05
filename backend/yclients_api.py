import os
import time
import logging
import threading
import calendar
import collections
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

# ─── Constants ───
YCLIENTS_API_BASE = "https://api.yclients.com/api/v1"
YCLIENTS_PARTNER_TOKEN = os.environ.get("YCLIENTS_PARTNER_TOKEN")
YCLIENTS_USER_TOKEN = os.environ.get("YCLIENTS_USER_TOKEN")
YCLIENTS_COMPANY_ID = os.environ.get("YCLIENTS_COMPANY_ID")

# For backward compatibility
YCLIENTS_TOKEN = YCLIENTS_PARTNER_TOKEN

# ─── Общий ограничитель скорости запросов к YClients ───
# YClients документирует жёсткий лимит: не более 5 запросов в секунду на IP
# (https://yclientsen.docs.apiary.io/). Раньше параллелизм ограничивался
# только локально, внутри одного расчёта (_YC_MAX_WORKERS в app.py) — но
# это не защищает от превышения лимита, когда одновременно работают
# НЕСКОЛЬКО независимых источников запросов: фоновый прогрев кэша,
# реальные посетители страницы расписания, форма записи, админка и т.д.
# Каждый по отдельности укладывался в свой локальный лимит, а суммарно —
# нет. На проде (больше услуг/мастеров в реальном аккаунте + реальный
# трафик поверх фонового прогрева) это легко превышает 5 req/sec, отсюда
# и медленные/ошибочные ответы, которых нет в локальном тесте с маленьким
# тестовым аккаунтом и без параллельного трафика.
#
# Это единственная точка, через которую идут вообще все запросы модуля
# (_request_with_retry), поэтому лимит соблюдается глобально для всего
# процесса, а не только внутри одной функции.
_RATE_LIMIT_PER_SEC = 3  # было 4 — судя по логам, и этого оказалось мало
_rate_lock = threading.Lock()
_rate_window = collections.deque()  # timestamps последних запросов


def _rate_limit_wait():
    """Блокирует вызывающий поток, пока в скользящем окне последней
    секунды не освободится место — не более _RATE_LIMIT_PER_SEC
    запросов в секунду суммарно от всего процесса."""
    while True:
        with _rate_lock:
            now = time.monotonic()
            while _rate_window and now - _rate_window[0] > 1.0:
                _rate_window.popleft()
            if len(_rate_window) < _RATE_LIMIT_PER_SEC:
                _rate_window.append(now)
                return
            sleep_for = 1.0 - (now - _rate_window[0])
        time.sleep(max(sleep_for, 0.01))


def _request_with_retry(method,
                        url,
                        retries=2,
                        backoff=0.4,
                        timeout=15,
                        **kwargs):

    last_resp = None
    for attempt in range(retries + 1):
        _rate_limit_wait()
        try:
            resp = requests.request(method, url, timeout=timeout, **kwargs)
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError) as e:
            last_resp = None
            if attempt < retries:
                logger.warning(
                    f"YClients {method.upper()} {url} — попытка {attempt + 1} "
                    f"не удалась ({e}), повтор через {backoff * (attempt + 1)}с..."
                )
                time.sleep(backoff * (attempt + 1))
                continue
            logger.error(
                f"YClients {method.upper()} {url} — все попытки истощены: {e}")
            return None

        if resp.status_code == 429 or resp.status_code >= 500:
            last_resp = resp
            if attempt < retries:
                logger.warning(
                    f"YClients {method.upper()} {url} — HTTP {resp.status_code}, "
                    f"попытка {attempt + 1}, повтор через {backoff * (attempt + 1)}с..."
                )
                time.sleep(backoff * (attempt + 1))
                continue
            return resp

        return resp

    return last_resp


def _headers():

    return {
        "Authorization":
        f"Bearer {YCLIENTS_PARTNER_TOKEN}, User {YCLIENTS_USER_TOKEN}",
        "Accept": "application/vnd.api.v2+json",
        "User-Agent": "BeautyVerbena/1.0",
    }


# ─── Service Categories ───


def get_service_categories(error_flag=None):

    if not YCLIENTS_PARTNER_TOKEN or not YCLIENTS_USER_TOKEN:
        logger.error(
            "YCLIENTS_PARTNER_TOKEN or YCLIENTS_USER_TOKEN not configured")
        if error_flag is not None:
            error_flag.append(True)
        return []

    url = f"{YCLIENTS_API_BASE}/company/{YCLIENTS_COMPANY_ID}/service_categories/"
    try:
        resp = _request_with_retry("get", url, headers=_headers())
        if resp is not None and resp.status_code == 200:
            data = resp.json()
            return data.get("data", [])
        else:
            status = resp.status_code if resp is not None else "no response"
            body = resp.text[:200] if resp is not None else ""
            logger.error(
                f"YClients service_categories error: HTTP {status} - {body}")
            if error_flag is not None:
                error_flag.append(True)
            return []
    except Exception as e:
        logger.error(f"YClients service_categories exception: {e}")
        if error_flag is not None:
            error_flag.append(True)
        return []


# ─── Services ───


def get_services(category_id=None, error_flag=None):

    if not YCLIENTS_PARTNER_TOKEN or not YCLIENTS_USER_TOKEN:
        logger.error(
            "YCLIENTS_PARTNER_TOKEN or YCLIENTS_USER_TOKEN not configured")
        if error_flag is not None:
            error_flag.append(True)
        return []

    url = f"{YCLIENTS_API_BASE}/company/{YCLIENTS_COMPANY_ID}/services/"
    params = {}
    if category_id:
        params["category_id"] = category_id
    try:
        resp = _request_with_retry("get",
                                   url,
                                   headers=_headers(),
                                   params=params)
        if resp is not None and resp.status_code == 200:
            data = resp.json()
            return data.get("data", [])
        else:
            status = resp.status_code if resp is not None else "no response"
            body = resp.text[:200] if resp is not None else ""
            logger.error(f"YClients services error: HTTP {status} - {body}")
            if error_flag is not None:
                error_flag.append(True)
            return []
    except Exception as e:
        logger.error(f"YClients services exception: {e}")
        if error_flag is not None:
            error_flag.append(True)
        return []


def get_bookable_services(error_flag=None):
    """Получает услуги, пригодные для онлайн-записи."""
    if not YCLIENTS_PARTNER_TOKEN or not YCLIENTS_USER_TOKEN:
        logger.error("Tokens not configured")
        if error_flag is not None: error_flag.append(True)
        return []

    # ВАЖНО: /services/{company_id} — устаревшая (deprecated) ручка каталога
    # услуг из CRM-группы API. Для списка услуг, доступных именно для
    # онлайн-записи, YClients предоставляет отдельную ручку виджета
    # book_services/{company_id} — её и нужно использовать здесь.
    url = f"{YCLIENTS_API_BASE}/book_services/{YCLIENTS_COMPANY_ID}"
    try:
        resp = _request_with_retry("get", url, headers=_headers())
        if resp and resp.status_code == 200:
            data = resp.json()
            payload = data.get("data", []) if isinstance(data, dict) else data

            # book_services может вернуть либо плоский список услуг, либо
            # список категорий с вложенным services[] — поддержим оба формата.
            services = []
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict) and "services" in item:
                        services.extend(item.get("services") or [])
                    elif isinstance(item, dict):
                        services.append(item)

            # Фильтруем только активные (если поле active вообще присутствует)
            active_services = [
                s for s in services
                if s.get("active") in (1, True, "1", "true", "True")
            ]

            # Если активных нет (например, поля active нет в этом формате
            # ответа), возвращаем все, чтобы не сломать логику
            if not active_services:
                return services

            return active_services
        else:
            status = resp.status_code if resp else "no response"
            body = resp.text[:200] if resp else ""
            logger.error(f"YClients book_services error: HTTP {status} - {body}")
            if error_flag: error_flag.append(True)
            return []
    except Exception as e:
        logger.error(f"YClients book_services exception: {e}")
        if error_flag: error_flag.append(True)
        return []


def get_all_staff_from_services():

    services = get_services()
    return extract_active_staff(services, active_only=False)


def extract_active_staff(services, active_only=True):
    """Собирает уникальных мастеров из уже полученного списка услуг
    (см. get_services() — GET /company/{id}/services/, полный CRM-каталог,
    у каждой услуги есть поле "staff": [...] с мастерами, её оказывающими).

    В отличие от book_staff (см. get_staff_for_booking), здесь НЕТ
    отдельной валидации service_ids[] и, соответственно, не может быть
    422 на "плохой" id: это чистый разбор JSON, который уже пришёл одним
    запросом. Если active_only=True (по умолчанию), учитываются только
    мастера из услуг с active == 1 — это отражает реальную доступность
    услуги в самом YClients, а не отдельный флаг online-booking каталога
    (см. get_bookable_services(), который смотрит на другой, более узкий
    список)."""
    staff_map = {}
    for svc in services or []:
        if active_only and svc.get("active") != 1:
            continue
        for s in svc.get("staff", []):
            sid = s.get("id")
            if sid and sid not in staff_map:
                staff_map[sid] = {
                    "id": sid,
                    "name": s.get("name", "Мастер"),
                    "specialization": s.get("specialization", ""),
                }
    return list(staff_map.values())


# ─── Staff (legacy, kept for compatibility) ───


def get_staff():

    return get_all_staff_from_services()


def _book_staff_request(ids, error_flag=None):
    """Один сырой запрос GET /book_staff/{company_id}?service_ids[]=...
    Возвращает (status_code, data_or_None). Не ретраит 422 (это ответ о
    валидации, не транзиентная ошибка — retries тут не помогут, см.
    _request_with_retry, который и так ретраит только 429/5xx)."""
    url = f"{YCLIENTS_API_BASE}/book_staff/{YCLIENTS_COMPANY_ID}"
    params = [("service_ids[]", sid) for sid in ids]
    try:
        resp = _request_with_retry("get",
                                   url,
                                   headers=_headers(),
                                   params=params)
        if resp is not None and resp.status_code == 200:
            return 200, resp.json().get("data", [])
        status = resp.status_code if resp is not None else None
        body = resp.text[:200] if resp is not None else ""
        logger.warning(
            f"YClients book_staff HTTP {status} для {len(ids)} service_ids "
            f"(ids={ids}) - {body}")
        if error_flag is not None and status != 422:
            # 422 обрабатывается вызывающей стороной через бисекцию, это
            # не "настоящая" ошибка запроса — не поднимаем error_flag здесь.
            error_flag.append(True)
        return status, None
    except Exception as e:
        logger.error(f"YClients book_staff exception: {e}")
        if error_flag is not None:
            error_flag.append(True)
        return None, None


def _book_staff_bisect(ids, error_flag=None, _depth=0):
    """Пытается получить мастеров для ids одним запросом; если YClients
    отвечает 422 (валидация service_ids[] целиком, без указания, какой
    именно id виноват — см. get_bookable_services()), делит ids пополам
    и повторяет рекурсивно, пока не останутся рабочие подмножества или
    единичные id. Единичный id, который сам по себе даёт 422, логируется
    как "плохой" и пропускается (не должен ронять весь расчёт мастеров).

    Так решение не завязано на угаданное магическое число (батчи по 5 и
    т.п.): если реальная причина — конкретный непригодный id, бисекция
    сразу его находит и выкидывает; если причина — лимит на количество
    service_ids[] в одном запросе, бисекция сама сходится к рабочему
    размеру пачки."""
    if not ids:
        return []

    status, data = _book_staff_request(ids, error_flag=error_flag)
    if status == 200:
        return data or []

    if status != 422:
        # Не про валидацию (429 после исчерпания ретраев, 5xx, сеть) —
        # дальше бисектить бессмысленно, ошибка уже учтена в error_flag.
        return []

    if len(ids) == 1:
        logger.error(
            f"YClients book_staff: service_id={ids[0]} сам по себе даёт "
            f"422 — исключаю его из расчёта мастеров (проверьте, доступна "
            f"ли эта услуга для онлайн-записи в кабинете YClients).")
        return []

    mid = len(ids) // 2
    left = _book_staff_bisect(ids[:mid],
                              error_flag=error_flag,
                              _depth=_depth + 1)
    right = _book_staff_bisect(ids[mid:],
                               error_flag=error_flag,
                               _depth=_depth + 1)

    merged = {}
    for staff in left + right:
        sid = staff.get("id")
        if sid is not None and sid not in merged:
            merged[sid] = staff
    return list(merged.values())


def get_staff_for_booking(service_id=None, error_flag=None):
    """service_id может быть одним id (как раньше) ИЛИ списком/кортежем/
    множеством id — тогда сначала пробуем ОДИН запрос со всеми
    service_ids[] сразу (дёшево по rate-limit, см. _calculate_free_slots
    в app.py). Если YClients отвечает 422 на весь список сразу, разбиваем
    его бисекцией (см. _book_staff_bisect) вместо того, чтобы резать на
    заранее угаданные пачки фиксированного размера — так находим ровно
    те id, что реально ломают запрос, а не гадаем с magic number."""

    if not YCLIENTS_PARTNER_TOKEN or not YCLIENTS_USER_TOKEN:
        logger.error(
            "YCLIENTS_PARTNER_TOKEN or YCLIENTS_USER_TOKEN not configured")
        if error_flag is not None:
            error_flag.append(True)
        return []

    if not service_id:
        status, data = _book_staff_request([], error_flag=error_flag)
        return data or [] if status == 200 else []

    ids = list(service_id if isinstance(service_id, (list, tuple,
                                                     set)) else [service_id])

    return _book_staff_bisect(ids, error_flag=error_flag)


# ─── Staff Timetable (расписание мастера на дату) ───


def get_staff_timetable(staff_id, date_str, error_flag=None):
    """GET /timetable/seances/{company_id}/{staff_id}/{date}.

    В отличие от book_dates/book_times, эта ручка требует ТОЛЬКО staff_id
    и дату — без service_id. Она относится к "журнальной"/CRM-группе
    API (тот же расчёт прав, что и просмотр журнала записи в кабинете),
    а не к виджету онлайн-записи, поэтому не участвует в комбинаторике
    "услуга × мастер", из-за которой раньше _calculate_free_slots делал
    десятки запросов на одну дату.

    Возвращает список вида [{"time": "10:00", "is_free": true}, ...] —
    сырую занятость мастера по сетке (обычно 5 минут), БЕЗ учёта
    длительности конкретной услуги. Для страницы "какие вообще есть
    свободные окна" (без выбора услуги) этого достаточно — ровно так
    сейчас используется /api/public/free-slots. Если где-то потребуется
    проверить, влезает ли услуга нужной длины, слоты нужно предварительно
    схлопнуть в непрерывные интервалы (см. _calculate_free_slots).
    """
    if not YCLIENTS_PARTNER_TOKEN or not YCLIENTS_USER_TOKEN:
        logger.error("Tokens not configured")
        if error_flag is not None:
            error_flag.append(True)
        return []

    url = f"{YCLIENTS_API_BASE}/timetable/seances/{YCLIENTS_COMPANY_ID}/{staff_id}/{date_str}"
    try:
        resp = _request_with_retry("get", url, headers=_headers())
        if resp is not None and resp.status_code == 200:
            data = resp.json()
            return data.get("data", [])
        else:
            status = resp.status_code if resp is not None else "no response"
            body = resp.text[:200] if resp is not None else ""
            if status == 404:
                # Мастер без графика на эту дату / нет журнала — не
                # инфраструктурная ошибка, не поднимаем error_flag.
                logger.info(
                    f"YClients timetable: мастер {staff_id} без графика "
                    f"на {date_str} — HTTP 404")
                return []
            logger.error(
                f"YClients timetable/seances error: HTTP {status} - {body}")
            if error_flag is not None:
                error_flag.append(True)
            return []
    except Exception as e:
        logger.error(f"YClients timetable/seances exception: {e}")
        if error_flag is not None:
            error_flag.append(True)
        return []


# ─── Available Times ───


def get_available_times(service_id, staff_id, date_str, error_flag=None):
    """
    ШАГ 2: Получает доступное время для записи на конкретную дату к выбранному мастеру.
    Запрос: GET /book_times/{company_id}/{staff_id}/{date}?service_ids[]=...
    Ответ: [{"time": "10:30", "seance_length": 9000, ...}, ...]
    """
    if not YCLIENTS_PARTNER_TOKEN or not YCLIENTS_USER_TOKEN:
        logger.error("Tokens not configured")
        if error_flag is not None: error_flag.append(True)
        return []

    # Гарантируем формат YYYY-MM-DD для URL
    if "." in date_str:
        parts = date_str.split(".")
        date_str = f"{parts[2]}-{parts[1]}-{parts[0]}"

    url = f"{YCLIENTS_API_BASE}/book_times/{YCLIENTS_COMPANY_ID}/{staff_id}/{date_str}"

    # --- Правильная обработка списка или одиночного ID ---
    params = []
    if service_id:
        ids = service_id if isinstance(service_id,
                                       (list, tuple, set)) else [service_id]
        params.extend(("service_ids[]", sid) for sid in ids)
    # -----------------------------------------------------

    try:
        resp = _request_with_retry("get",
                                   url,
                                   headers=_headers(),
                                   params=params)
        if resp is not None and resp.status_code == 200:
            data = resp.json().get("data", [])
            times = []
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "time" in item:
                        times.append(item["time"])
            return times

        elif resp is not None and resp.status_code == 404:
            # 404 — мастер не работает в этот день или нет слотов под эту услугу
            return []

        else:
            status = resp.status_code if resp is not None else "no response"
            body = resp.text[:200] if resp is not None else ""
            logger.error(
                f"YClients available times error: HTTP {status} - {body}")
            if error_flag is not None: error_flag.append(True)
            return []
    except Exception as e:
        logger.error(f"YClients available times exception: {e}")
        if error_flag is not None: error_flag.append(True)
        return []


def get_staff_schedule(start_date, end_date, staff_ids=None, error_flag=None):
    """
    Получает расписание (графики и занятость) мастеров за период.
    GET /company/{id}/staff/schedule
    """
    if not YCLIENTS_PARTNER_TOKEN or not YCLIENTS_USER_TOKEN:
        logger.error("Tokens not configured")
        if error_flag is not None: error_flag.append(True)
        return {}

    url = f"{YCLIENTS_API_BASE}/company/{YCLIENTS_COMPANY_ID}/staff/schedule"
    params = {
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
    }
    if staff_ids:
        # staff_ids может быть строкой, int, или списком
        ids = staff_ids if isinstance(staff_ids,
                                      (list, tuple, set)) else [staff_ids]
        params["staff_ids[]"] = ids

    try:
        resp = _request_with_retry("get",
                                   url,
                                   headers=_headers(),
                                   params=params)
        if resp is not None and resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict) and "data" in data:
                return data["data"]
            else:
                logger.warning("YClients schedule: unexpected response format")
                return {}
        elif resp is not None and resp.status_code == 404:
            # 404 может значить, что мастеров нет или они не работают в этот период
            return {}
        else:
            status = resp.status_code if resp is not None else "no response"
            body = resp.text[:200] if resp is not None else ""
            logger.error(
                f"YClients staff schedule error: HTTP {status} - {body}")
            if error_flag is not None: error_flag.append(True)
            return {}
    except Exception as e:
        logger.error(f"YClients staff schedule exception: {e}")
        if error_flag is not None: error_flag.append(True)
        return {}


# ─── Available Dates ───
def get_available_dates(service_id=None,
                        staff_id=None,
                        month=None,
                        year=None,
                        error_flag=None):
    """
    ШАГ 1: Получает список дат в месяце, на которые есть свободные слоты.
    Запрос: GET /book_dates/{company_id}?date_from=YYYY-MM-01&date_to=YYYY-MM-DD[&service_ids[]=...]
    Ответ: ["2026-08-05", "2026-08-09", ...]

    ВАЖНО про service_ids[]: это НЕ "фильтр по любой из услуг", а фильтр
    "дата, на которую можно записаться на ВСЕ перечисленные услуги сразу"
    (как при выборе нескольких услуг в одной записи) — YClients считает
    пересечение доступности. Если передать туда id вообще всех активных
    услуг салона (десятки), пересечение почти всегда пустое — это и
    было причиной пустого календаря. Поэтому если конкретная услуга не
    выбрана явно (service_id не передан), НЕ подставляем сюда список
    услуг — просто не отправляем service_ids[] вообще, и YClients сам
    вернёт даты, на которые доступна хотя бы одна услуга (проверено
    вручную: тот же book_dates без service_ids[] отдаёт непустой
    booking_dates).
    """
    if not YCLIENTS_PARTNER_TOKEN or not YCLIENTS_USER_TOKEN:
        logger.error("Tokens not configured")
        if error_flag is not None: error_flag.append(True)
        return []

    now = datetime.now()
    month = month or now.month
    year = year or now.year

    # Поддерживаем и один ID, и список/множество ID. Если ничего не
    # передано — фильтр по услугам просто не отправляется (см. докстринг).
    ids = []
    if service_id:
        ids = list(service_id) if isinstance(
            service_id, (list, tuple, set)) else [service_id]

    url = f"{YCLIENTS_API_BASE}/book_dates/{YCLIENTS_COMPANY_ID}"

    # date_from/date_to на весь месяц — YClients реально возвращает данные
    # по этим параметрам (проверено вручную), а не по одиночному date=.
    last_day = calendar.monthrange(year, month)[1]
    date_from = f"{year:04d}-{month:02d}-01"
    date_to = f"{year:04d}-{month:02d}-{last_day:02d}"

    # ВАЖНО: используем список кортежей, а не словарь, для корректной отправки нескольких service_ids[]
    params = [("date_from", date_from), ("date_to", date_to)]
    for sid in ids:
        params.append(("service_ids[]", sid))

    if staff_id and str(staff_id) != "0":
        params.append(("staff_id", staff_id))

    try:
        resp = _request_with_retry("get",
                                   url,
                                   headers=_headers(),
                                   params=params)
        if resp is not None and resp.status_code == 200:
            payload = resp.json().get("data", {})
            raw_dates = []

            if isinstance(payload, dict):
                raw_dates = payload.get("booking_dates", [])
            elif isinstance(payload, list):
                raw_dates = payload

            dates_data = []
            for item in raw_dates:
                if isinstance(item, (int, float)):
                    # Если YClients вернул Unix-таймстемпы
                    dates_data.append(
                        datetime.fromtimestamp(
                            item, tz=timezone.utc).strftime("%Y-%m-%d"))
                else:
                    dates_data.append(str(item))
            return dates_data

        elif resp is not None and resp.status_code == 404:
            # 404 — легитимный ответ: в этом месяце нет свободных дат
            return []
        else:
            status = resp.status_code if resp is not None else "no response"
            body = resp.text[:200] if resp is not None else ""
            logger.error(
                f"YClients available dates error: HTTP {status} - {body}")
            if error_flag is not None: error_flag.append(True)
            return []
    except Exception as e:
        logger.error(f"YClients available dates exception: {e}")
        if error_flag is not None: error_flag.append(True)
        return []


# ─── Create Booking (Record) ───


def create_booking(
    client_name,
    client_phone,
    service_id,
    staff_id,
    date_str,
    time_str,
    comment="",
    client_email="noreply@verbena-studio.ru",
):

    if not YCLIENTS_PARTNER_TOKEN or not YCLIENTS_USER_TOKEN:
        logger.error("Tokens not configured")
        return {"success": False, "error": "YClients tokens not configured"}

    url = f"{YCLIENTS_API_BASE}/book_record/{YCLIENTS_COMPANY_ID}"

    # Формируем payload строго по структуре YClients
    payload = {
        "phone":
        client_phone,
        "fullname":
        client_name,
        "email":
        client_email,
        "appointments": [{
            "id": 1,  # Временный ID для связки услуг
            "services": [int(service_id)],
            "staff_id": int(staff_id),
            "datetime": f"{date_str}T{time_str}:00",
            "seance_length": 3600,  # Длительность по умолчанию, можно уточнять
        }],
    }
    if comment and comment.strip():
        payload["comment"] = comment.strip()

    logger.info(f"YClients create booking payload: {payload}")

    try:
        _rate_limit_wait()
        resp = requests.post(url, headers=_headers(), json=payload, timeout=15)

        # ... внутри функции create_booking, блок обработки успеха ...
        if resp.status_code in (200, 201):
            data = resp.json()
            if not data.get("success", False):
                error_text = resp.text[:500]
                logger.error(f"YClients booking failed logic: {error_text}")
                return {
                    "success": False,
                    "error": f"YClients rejected: {error_text}"
                }

            record_data = data.get("data", {})

            # Корректное извлечение ID и HASH (учитывая структуру ответа YClients)
            record_id = None
            record_hash = None

            if isinstance(record_data, list) and len(record_data) > 0:
                first_record = record_data[0]
                record_id = first_record.get("record_id") or first_record.get(
                    "id")
                record_hash = first_record.get("record_hash")
            else:
                record_id = record_data.get("record_id") or record_data.get(
                    "id")
                record_hash = record_data.get("record_hash")

            logger.info(
                f"YClients booking created: id={record_id}, hash={record_hash}"
            )

            # ВАЖНО: Возвращаем ОБА значения
            return {
                "success": True,
                "record_id": str(record_id) if record_id else None,
                "hash": record_hash,
                "error": None
            }
        else:
            error_text = resp.text[:500]
            logger.error(
                f"YClients create booking HTTP error: {resp.status_code} - {error_text}"
            )
            return {
                "success": False,
                "error":
                f"YClients HTTP error: {resp.status_code} - {error_text}",
            }
    except Exception as e:
        logger.error(f"YClients create booking exception: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


# ─── Health check ───


def check_connection():

    if not YCLIENTS_PARTNER_TOKEN or not YCLIENTS_USER_TOKEN:
        return {
            "connected": False,
            "company_name": None,
            "error": "YClients tokens not configured",
        }

    url = f"{YCLIENTS_API_BASE}/company/{YCLIENTS_COMPANY_ID}"
    try:
        _rate_limit_wait()
        resp = requests.get(url, headers=_headers(), timeout=15)
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            return {
                "connected": True,
                "company_name": data.get("title"),
                "error": None,
            }
        else:
            return {
                "connected": False,
                "company_name": None,
                "error": f"HTTP {resp.status_code}",
            }
    except Exception as e:
        return {"connected": False, "company_name": None, "error": str(e)}


def get_record_by_hash(record_hash):

    if not record_hash:
        return None

    url = f"{YCLIENTS_API_BASE}/user/records/{record_hash}"

    try:
        _rate_limit_wait()
        resp = requests.get(url, headers=_headers(), timeout=10)
        if resp.status_code == 200:
            return resp.json().get("data")
        else:
            logger.error(
                f"YClients get_record_by_hash error: {resp.status_code}")
            return None
    except Exception as e:
        logger.error(f"YClients get_record_by_hash exception: {e}")
        return None