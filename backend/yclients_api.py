"""
YClients API integration module.

Provides functions to interact with YClients API for:
- Fetching service categories
- Fetching services (with embedded staff info)
- Fetching available time slots
- Creating bookings

Requires environment variables:
- YCLIENTS_PARTNER_TOKEN: partner token (from YClients app)
- YCLIENTS_USER_TOKEN: user token (from YClients app)
- YCLIENTS_COMPANY_ID: your company ID (2101920)
"""

import os
import logging
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

# ─── Constants ───
YCLIENTS_API_BASE = "https://api.yclients.com/api/v1"
YCLIENTS_PARTNER_TOKEN = os.environ.get("YCLIENTS_PARTNER_TOKEN",
                                        "dyx8KA6DiXHjYV4ZU9o7")
YCLIENTS_USER_TOKEN = os.environ.get("YCLIENTS_USER_TOKEN",
                                     "634fa473bd2937298aeed3fe640387ee")
YCLIENTS_COMPANY_ID = os.environ.get("YCLIENTS_COMPANY_ID", "2101920")

# For backward compatibility
YCLIENTS_TOKEN = YCLIENTS_PARTNER_TOKEN


def _headers():
    """
    YClients v1 API requires:
    - Authorization: Bearer {partner_token}, User {user_token}
    - Accept: application/vnd.api.v2+json
    """
    return {
        "Authorization":
        f"Bearer {YCLIENTS_PARTNER_TOKEN}, User {YCLIENTS_USER_TOKEN}",
        "Accept": "application/vnd.api.v2+json",
        "User-Agent": "BeautyVerbena/1.0",
    }


# ─── Service Categories ───


def get_service_categories():
    """
    Fetch all service categories from YClients.
    Uses /service_categories/ endpoint (not /categories).

    Returns list of dicts with keys: id, title, category_id, etc.
    """
    if not YCLIENTS_PARTNER_TOKEN or not YCLIENTS_USER_TOKEN:
        logger.error(
            "YCLIENTS_PARTNER_TOKEN or YCLIENTS_USER_TOKEN not configured")
        return []

    url = f"{YCLIENTS_API_BASE}/company/{YCLIENTS_COMPANY_ID}/service_categories/"
    try:
        resp = requests.get(url, headers=_headers(), timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("data", [])
        else:
            logger.error(
                f"YClients service_categories error: HTTP {resp.status_code} - {resp.text[:200]}"
            )
            return []
    except Exception as e:
        logger.error(f"YClients service_categories exception: {e}")
        return []


# ─── Services ───


def get_services(category_id=None):
    """
    Fetch services from YClients.
    
    Each service includes staff info in the 'staff' field.

    Args:
        category_id: optional category ID to filter by.

    Returns list of service dicts with keys: id, title, category_id, price_min,
    price_max, duration, staff (list), etc.
    """
    if not YCLIENTS_PARTNER_TOKEN or not YCLIENTS_USER_TOKEN:
        logger.error(
            "YCLIENTS_PARTNER_TOKEN or YCLIENTS_USER_TOKEN not configured")
        return []

    url = f"{YCLIENTS_API_BASE}/company/{YCLIENTS_COMPANY_ID}/services/"
    params = {}
    if category_id:
        params["category_id"] = category_id
    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("data", [])
        else:
            logger.error(
                f"YClients services error: HTTP {resp.status_code} - {resp.text[:200]}"
            )
            return []
    except Exception as e:
        logger.error(f"YClients services exception: {e}")
        return []


def get_all_staff_from_services():
    """
    Extract unique staff from all services.
    Each service has 'staff' field with [{id, name, ...}].
    
    Returns list of unique staff dicts: {id, name, specialization?}.
    """
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
    """
    Fetch all staff from YClients via services.
    YClients services endpoint includes staff data, so no separate staff endpoint needed.
    """
    return get_all_staff_from_services()


def get_staff_for_booking(service_id=None):
    """
    Fetch staff available for booking, optionally filtered by service.

    Uses the /book_staff/{company_id} endpoint — the same one YClients' own
    booking widget uses to show "which master performs this service". This is
    the reliable way to filter staff by service: the plain /services/ endpoint's
    embedded 'staff' field isn't populated for every company/service.

    Args:
        service_id: optional YClients service ID to filter staff by. If omitted,
        returns all staff bookable online.

    Returns:
        List of staff dicts (id, name, specialization, avatar, etc.).
    """
    if not YCLIENTS_PARTNER_TOKEN or not YCLIENTS_USER_TOKEN:
        logger.error(
            "YCLIENTS_PARTNER_TOKEN or YCLIENTS_USER_TOKEN not configured")
        return []

    url = f"{YCLIENTS_API_BASE}/book_staff/{YCLIENTS_COMPANY_ID}"
    params = []
    if service_id:
        params.append(("service_ids[]", service_id))
    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("data", [])
        else:
            logger.error(
                f"YClients book_staff error: HTTP {resp.status_code} - {resp.text[:200]}"
            )
            return []
    except Exception as e:
        logger.error(f"YClients book_staff exception: {e}")
        return []


# ─── Available Times ───


def get_available_times(service_id, staff_id, date_str):
    """
    Fetch available time slots for a given service, staff, and date.
    Uses /book_times/{company_id}/{staff_id}/{date} endpoint.

    Args:
        service_id: YClients service ID.
        staff_id: YClients staff ID.
        date_str: date in YYYY-MM-DD format.

    Returns:
        List of time strings (e.g. ["10:00", "10:15", ...]).
    """
    if not YCLIENTS_PARTNER_TOKEN or not YCLIENTS_USER_TOKEN:
        logger.error("Tokens not configured")
        return []

    url = (f"{YCLIENTS_API_BASE}/book_times/{YCLIENTS_COMPANY_ID}"
           f"/{staff_id}/{date_str}")
    params = [
        ("service_ids[]", service_id),
    ]
    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=15)
        if resp.status_code == 200:
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
            logger.error(
                f"YClients available times error: HTTP {resp.status_code} - {resp.text[:200]}"
            )
            return []
    except Exception as e:
        logger.error(f"YClients available times exception: {e}")
        return []


def get_available_dates(service_id, staff_id, month=None, year=None):
    """
    Fetch available dates (days with free slots) for a given service and staff.

    Args:
        service_id: YClients service ID.
        staff_id: YClients staff ID.
        month: month number (1-12), defaults to current.
        year: year, defaults to current.

    Returns:
        List of date strings (e.g. ["2026-08-01", "2026-08-03", ...]).
    """
    if not YCLIENTS_PARTNER_TOKEN or not YCLIENTS_USER_TOKEN:
        logger.error("Tokens not configured")
        return []

    now = datetime.now()
    month = month or now.month
    year = year or now.year

    url = (f"{YCLIENTS_API_BASE}/records/{YCLIENTS_COMPANY_ID}"
           f"/book_dates/dates")
    params = {
        "service_ids[]": [service_id],
        "staff_id": staff_id,
        "month": month,
        "year": year,
    }
    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            dates_data = data.get("data", [])
            return dates_data
        else:
            logger.error(
                f"YClients available dates error: HTTP {resp.status_code} - {resp.text[:200]}"
            )
            return []
    except Exception as e:
        logger.error(f"YClients available dates exception: {e}")
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
    """
    Create a booking (record) in YClients.
    Returns dict with keys: success, record_id, hash, error.
    """
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
    """
    Check if YClients API is reachable with current credentials.

    Returns:
        dict with keys: connected (bool), company_name (str or None), error (str or None).
    """
    if not YCLIENTS_PARTNER_TOKEN or not YCLIENTS_USER_TOKEN:
        return {
            "connected": False,
            "company_name": None,
            "error": "YClients tokens not configured",
        }

    url = f"{YCLIENTS_API_BASE}/company/{YCLIENTS_COMPANY_ID}"
    try:
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
    """
    Get record details by its public hash.
    Uses /user/records/{hash} endpoint.
    """
    if not record_hash:
        return None

    # Для этого эндпоинта иногда достаточно только User token,
    # но лучше использовать стандартные заголовки
    url = f"{YCLIENTS_API_BASE}/user/records/{record_hash}"

    try:
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
