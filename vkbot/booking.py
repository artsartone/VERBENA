"""
Общий модуль бизнес-логики для записи в YClients.

Используется как Telegram, так и VK ботами.
Содержит функции для:
- загрузки категорий, услуг, мастеров
- получения доступных дат и времени
- создания записи
"""
import logging
from datetime import date, timedelta
from typing import List, Dict, Any, Optional, Tuple
import requests

logger = logging.getLogger(__name__)


class BookingService:
    """Сервис для работы с записями через YClients API."""

    def __init__(self, api_base: str = "http://localhost:5000"):
        self.api_base = api_base

    def load_categories(self) -> List[Dict]:
        """Загрузить категории услуг из YClients."""
        try:
            resp = requests.get(f"{self.api_base}/api/yclients/categories",
                                timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.warning(f"Ошибка загрузки категорий: {e}")
        return []

    def load_services(self, category_id: Optional[str] = None) -> List[Dict]:
        """Загрузить услуги из YClients (опционально по категории)."""
        try:
            params = {"category_id": category_id} if category_id else {}
            resp = requests.get(f"{self.api_base}/api/yclients/services",
                                params=params,
                                timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.warning(f"Ошибка загрузки услуг: {e}")
        return []

    def load_staff(self, service_id: Optional[str] = None) -> List[Dict]:
        """Загрузить мастеров из YClients (опционально для услуги)."""
        try:
            params = {"service_id": service_id} if service_id else {}
            resp = requests.get(f"{self.api_base}/api/yclients/staff",
                                params=params,
                                timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.warning(f"Ошибка загрузки мастеров: {e}")
        return []

    def _fetch_available_dates_for_month(self, service_id: str,
                                         staff_id: Optional[str], year: int,
                                         month: int) -> Optional[set]:
        """Один вызов /api/yclients/available-dates за конкретный месяц.

        Возвращает set ISO-дат ("YYYY-MM-DD") со свободными слотами,
        либо None, если запрос не удался — этим None (в отличие от
        пустого set) вызывающий код должен трактовать как «фильтровать
        нельзя», чтобы случайно не скрыть рабочие дни из-за сбоя API.
        """
        params = {"service_id": service_id, "month": month, "year": year}
        if staff_id and str(staff_id) != "0":
            params["staff_id"] = staff_id
        try:
            resp = requests.get(
                f"{self.api_base}/api/yclients/available-dates",
                params=params,
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return {str(d) for d in data}
            logger.warning(
                f"available-dates: HTTP {resp.status_code} - {resp.text[:200]}"
            )
        except Exception as e:
            logger.error(f"Ошибка при получении доступных дат: {e}")
        return None

    def load_available_dates(self,
                             service_id: str,
                             staff_id: Optional[str] = None,
                             days: int = 14) -> Optional[List[str]]:
        """
        Получить список доступных дат — только тех, на которые есть хотя
        бы один свободный слот (через /api/yclients/available-dates,
        та же логика, что и в Telegram-боте).

        Args:
            service_id: ID услуги YClients
            staff_id: ID мастера YClients (можно не передавать — тогда
                учитываются слоты по всем мастерам услуги)
            days: количество дней вперед (по умолчанию 14)

        Returns:
            Список дат в формате ДД.ММ.ГГГГ, отфильтрованный по
            занятости, либо None, если получить данные хотя бы за один
            месяц из диапазона не удалось (сигнал вызывающему коду не
            фильтровать и показать даты как раньше).
        """
        today = date.today()
        end = today + timedelta(days=days - 1)

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
            result = self._fetch_available_dates_for_month(
                service_id, staff_id, y, m)

            if result is None:
                return None

            all_dates |= result

        dates = []
        for i in range(days):
            d = today + timedelta(days=i)
            if d.isoformat() in all_dates:
                dates.append(d.strftime("%d.%m.%Y"))

        return dates

    def load_available_times(self, service_id: str, staff_id: str,
                             date_str: str) -> List[str]:
        """
        Получить доступное время для записи.

        Args:
            service_id: ID услуги YClients
            staff_id: ID мастера YClients
            date_str: Дата в формате ДД.ММ.ГГГГ

        Returns:
            Список временных слотов (например ["10:00", "10:15", ...])
        """

        parts = date_str.split(".")
        if len(parts) == 3 and len(parts[2]) == 4:
            iso_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
        else:
            iso_date = date_str

        try:
            params = {
                "service_id": service_id,
                "staff_id": staff_id,
                "date": iso_date
            }
            resp = requests.get(
                f"{self.api_base}/api/yclients/available-times",
                params=params,
                timeout=10)

            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    if len(data) > 0 and isinstance(data[0], dict):

                        return [
                            s["time"] for s in data
                            if s.get("available", True)
                        ]
                    return data
        except Exception as e:
            logger.error(f"Ошибка получения времени: {e}")

        return []

    def create_booking(
            self,
            client_name: str,
            client_phone: str,
            service: str,
            booking_date: str,  # ДД.ММ.ГГГГ
            booking_time: str,
            comment: str = "",
            yclients_service_id: Optional[str] = None,
            yclients_staff_id: Optional[str] = None,
            assigned_employee_name: Optional[str] = None,
            telegram_id: Optional[str] = None,
            vk_id: Optional[str] = None,
            source: str = "bot") -> Tuple[bool, Optional[int], Optional[str]]:
        """
        Создать запись через API бэкенда.

        Args:
            client_name: Имя клиента
            client_phone: Телефон клиента
            service: Название услуги
            booking_date: Дата в формате ДД.ММ.ГГГГ
            booking_time: Время
            comment: Комментарий к записи
            yclients_service_id: ID услуги в YClients
            yclients_staff_id: ID мастера в YClients
            assigned_employee_name: Имя мастера
            telegram_id: ID пользователя Telegram (если есть)
            vk_id: ID пользователя VK (если есть)
            source: Источник записи ("telegram", "vk", "site")

        Returns:
            (success, booking_id, error_message)
        """

        parts = booking_date.split(".")
        if len(parts) == 3 and len(parts[2]) == 4:
            iso_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
        else:
            iso_date = booking_date

        payload = {
            "client_name": client_name,
            "client_phone": client_phone,
            "service": service,
            "booking_date": iso_date,
            "booking_time": booking_time,
            "comment": comment,
            "source": source,
        }

        if yclients_service_id:
            payload["yclients_service_id"] = yclients_service_id
        if yclients_staff_id:
            payload["yclients_staff_id"] = yclients_staff_id
        if assigned_employee_name:
            payload["assigned_employee_name"] = assigned_employee_name
        if telegram_id:
            payload["telegram_id"] = telegram_id
        if vk_id:
            payload["vk_id"] = vk_id

        payload["no_notify"] = True

        try:
            resp = requests.post(f"{self.api_base}/api/bookings",
                                 json=payload,
                                 timeout=15)

            if resp.status_code == 201:
                resp_json = resp.json()
                booking_id = resp_json.get("id")
                return True, booking_id, None
            elif resp.status_code == 409:
                return False, None, "Это время уже занято"
            else:
                error = resp.json().get("error", "Неизвестная ошибка")
                return False, None, error

        except Exception as e:
            logger.error(f"Ошибка создания записи: {e}")
            return False, None, "Ошибка соединения с сервером"


_booking_service_instance: Optional[BookingService] = None


def get_booking_service(
        api_base: str = "http://localhost:5000") -> BookingService:
    """Получить или создать экземпляр сервиса записей."""
    global _booking_service_instance
    if _booking_service_instance is None:
        _booking_service_instance = BookingService(api_base=api_base)
    return _booking_service_instance
