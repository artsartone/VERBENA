import os
import time
import logging
import threading
import collections
from datetime import datetime

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
    """GET /book_services/{company_id} — каталог услуг ГЛАЗАМИ виджета
    онлайн-записи, а не CRM (в отличие от get_services(), которая ходит
    в /company/{id}/services/ и отдаёт ВСЕ услуги каталога, включая
    архивные/скрытые/не включённые в онлайн-запись).

    Нужна там, где id услуг потом передаются в другую виджетную ручку —
    например, book_staff (см. get_staff_for_booking) — которая валидирует
    весь переданный service_ids[] и при наличии среди них хотя бы одного
    id, не годного для онлайн-записи, отвечает 422 на ВЕСЬ запрос целиком
    (без указания, какой именно id был плохим). get_services() в паре с
    book_staff регулярно ловит это на аккаунтах, где каталог шире
    online-bookable подмножества (см. историю бага: 28 услуг в каталоге,
    book_staff → HTTP 422 Unprocessable Content)."""

    if not YCLIENTS_PARTNER_TOKEN or not YCLIENTS_USER_TOKEN:
        logger.error(
            "YCLIENTS_PARTNER_TOKEN or YCLIENTS_USER_TOKEN not configured")
        if error_flag is not None:
            error_flag.append(True)
        return []

    url = f"{YCLIENTS_API_BASE}/book_services/{YCLIENTS_COMPANY_ID}"
    try:
        resp = _request_with_retry("get", url, headers=_headers())
        if resp is not None and resp.status_code == 200:
            data = resp.json().get("data", [])
            # На некоторых версиях API это плоский список услуг, на других —
            # объект вида {"services": [...], "categories": [...]}. Приводим
            # к списку в обоих случаях, ничего не предполагая заранее.
            if isinstance(data, dict):
                data = data.get("services", [])
            return data or []
        else:
            status = resp.status_code if resp is not None else "no response"
            body = resp.text[:200] if resp is not None else ""
            logger.error(
                f"YClients book_services error: HTTP {status} - {body}")
            if error_flag is not None:
                error_flag.append(True)
            return []
    except Exception as e:
        logger.error(f"YClients book_services exception: {e}")
        if error_flag is not None:
            error_flag.append(True)
        return []


def get_all_staff_from_services():

    services = get_services()
    staff_map = {}
    for svc in services:
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


def get_staff_for_booking(service_id=None, error_flag=None):
    """service_id может быть одним id (как раньше) ИЛИ списком/кортежем/
    множеством id — тогда все они уйдут ОДНИМ запросом как несколько
    service_ids[] в query (YClients принимает этот параметр массивом).
    Раньше коду, которому нужны мастера сразу по НЕСКОЛЬКИМ услугам,
    приходилось делать отдельный запрос на каждую — это и было основным
    источником лишних запросов в _calculate_free_slots (см. app.py)."""

    if not YCLIENTS_PARTNER_TOKEN or not YCLIENTS_USER_TOKEN:
        logger.error(
            "YCLIENTS_PARTNER_TOKEN or YCLIENTS_USER_TOKEN not configured")
        if error_flag is not None:
            error_flag.append(True)
        return []

    url = f"{YCLIENTS_API_BASE}/book_staff/{YCLIENTS_COMPANY_ID}"
    params = []
    if service_id:
        ids = (service_id if isinstance(service_id, (list, tuple, set))
               else [service_id])
        params.extend(("service_ids[]", sid) for sid in ids)
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
            logger.error(f"YClients book_staff error: HTTP {status} - {body}")
            if error_flag is not None:
                error_flag.append(True)
            return []
    except Exception as e:
        logger.error(f"YClients book_staff exception: {e}")
        if error_flag is not None:
            error_flag.append(True)
        return []


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
    """service_id: id услуги, список id услуг, или None/пусто.

    Если service_id не задан — book_times вернёт времена БЕЗ фильтра по
    конкретной услуге, но с той же квантовкой (шагом записи), что и с
    услугой: это ровно те тайминги, которые реально можно указать в
    datetime при создании записи, а не сырая 5-минутная занятость
    сотрудника. Именно поэтому для публичного превью свободных окон
    (без выбора услуги) нужно звать эту ручку, а не собирать времена
    из timetable/seances — там 5-минутные тики не гарантированно
    являются валидными стартами записи (см. настройку "доступное время
    для онлайн-записи" в YClients — время может быть ограничено шагом,
    например только 9:00, 10:00, 11:00... для часовой услуги)."""

    if not YCLIENTS_PARTNER_TOKEN or not YCLIENTS_USER_TOKEN:
        logger.error("Tokens not configured")
        if error_flag is not None:
            error_flag.append(True)
        return []

    url = (f"{YCLIENTS_API_BASE}/book_times/{YCLIENTS_COMPANY_ID}"
           f"/{staff_id}/{date_str}")
    params = []
    if service_id:
        ids = (service_id if isinstance(service_id, (list, tuple, set))
               else [service_id])
        params.extend(("service_ids[]", sid) for sid in ids)
    try:
        resp = _request_with_retry("get",
                                   url,
                                   headers=_headers(),
                                   params=params)
        if resp is not None and resp.status_code == 200:
            data = resp.json()
            times_data = data.get("data", [])
            # /book_times/ returns [{time: "10:00", ...}, ...]
            if isinstance(times_data, list) and len(times_data) > 0:
                if isinstance(times_data[0], dict) and "time" in times_data[0]:
                    return [item["time"] for item in times_data]
                return times_data
            if isinstance(times_data, dict) and "times" in times_data:
                return times_data["times"]
            return []
        else:
            status = resp.status_code if resp is not None else "no response"
            body = resp.text[:200] if resp is not None else ""
            if status == 404:
                # Легитимный ответ YClients: этот мастер не бронируется на
                # эту услугу через онлайн-запись — не инфраструктурная
                # ошибка. Не поднимаем error_flag из-за неё, иначе она
                # ложно портит эвристику had_errors и заставляет кэш дня
                # пересчитываться заново без реальной причины.
                logger.info(
                    f"YClients available times: мастер {staff_id} недоступен "
                    f"для услуги {service_id} ({date_str}) — HTTP 404")
                return []
            logger.error(
                f"YClients available times error: HTTP {status} - {body}")
            if error_flag is not None:
                error_flag.append(True)
            return []
    except Exception as e:
        logger.error(f"YClients available times exception: {e}")
        if error_flag is not None:
            error_flag.append(True)
        return []


def get_available_dates(service_id,
                        staff_id,
                        month=None,
                        year=None,
                        error_flag=None):

    if not YCLIENTS_PARTNER_TOKEN or not YCLIENTS_USER_TOKEN:
        logger.error("Tokens not configured")
        if error_flag is not None:
            error_flag.append(True)
        return []

    now = datetime.now()
    month = month or now.month
    year = year or now.year

    url = f"{YCLIENTS_API_BASE}/book_dates/{YCLIENTS_COMPANY_ID}"
    params = {
        "service_ids[]": [service_id],
        "staff_id": staff_id,
        # У book_dates фильтр по месяцу задаётся одним параметром date
        # (любой день внутри нужного месяца), а не month/year.
        "date": f"{year:04d}-{month:02d}-01",
    }
    try:
        resp = _request_with_retry("get",
                                   url,
                                   headers=_headers(),
                                   params=params)
        if resp is not None and resp.status_code == 200:
            data = resp.json()
            dates_data = data.get("data", [])
            return dates_data
        else:
            status = resp.status_code if resp is not None else "no response"
            body = resp.text[:200] if resp is not None else ""
            if status == 404:
                logger.info(
                    f"YClients available dates: мастер {staff_id} недоступен "
                    f"для услуги {service_id} — HTTP 404")
                return []
            logger.error(
                f"YClients available dates error: HTTP {status} - {body}")
            if error_flag is not None:
                error_flag.append(True)
            return []
    except Exception as e:
        logger.error(f"YClients available dates exception: {e}")
        if error_flag is not None:
            error_flag.append(True)
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