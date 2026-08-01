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

    # ─── Загрузка данных ───

    def load_categories(self) -> List[Dict]:
        """Загрузить категории услуг из YClients."""
        try:
            resp = requests.get(f"{self.api_base}/api/yclients/categories", timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.warning(f"Ошибка загрузки категорий: {e}")
        return []

    def load_services(self, category_id: Optional[str] = None) -> List[Dict]:
        """Загрузить услуги из YClients (опционально по категории)."""
        try:
            params = {"category_id": category_id} if category_id else {}
            resp = requests.get(f"{self.api_base}/api/yclients/services", params=params, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.warning(f"Ошибка загрузки услуг: {e}")
        return []

    def load_staff(self, service_id: Optional[str] = None) -> List[Dict]:
        """Загрузить мастеров из YClients (опционально для услуги)."""
        try:
            params = {"service_id": service_id} if service_id else {}
            resp = requests.get(f"{self.api_base}/api/yclients/staff", params=params, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.warning(f"Ошибка загрузки мастеров: {e}")
        return []

    def load_available_dates(
        self,
        service_id: str,
        staff_id: str,
        days: int = 14
    ) -> List[str]:
        """
        Получить список доступных дат.

        Args:
            service_id: ID услуги YClients
            staff_id: ID мастера YClients
            days: количество дней вперед (по умолчанию 14)

        Returns:
            Список дат в формате ДД.ММ.ГГГГ
        """
        dates = []
        today = date.today()
        for i in range(days):
            d = today + timedelta(days=i)
            dates.append(d.strftime("%d.%m.%Y"))
        return dates

    def load_available_times(
        self,
        service_id: str,
        staff_id: str,
        date_str: str
    ) -> List[str]:
        """
        Получить доступное время для записи.

        Args:
            service_id: ID услуги YClients
            staff_id: ID мастера YClients
            date_str: Дата в формате ДД.ММ.ГГГГ

        Returns:
            Список временных слотов (например ["10:00", "10:15", ...])
        """
        # Конвертируем ДД.ММ.ГГГГ → ГГГГ-ММ-ДД
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
                timeout=10
            )

            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    if len(data) > 0 and isinstance(data[0], dict):
                        # Фильтруем только доступные слоты
                        return [s["time"] for s in data if s.get("available", True)]
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
        source: str = "bot"
    ) -> Tuple[bool, Optional[int], Optional[str]]:
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
        # Конвертируем дату в ISO формат
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

        # Не дублируем уведомления — они идут только по подписке
        payload["no_notify"] = True

        try:
            resp = requests.post(
                f"{self.api_base}/api/bookings",
                json=payload,
                timeout=15
            )

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


# Глобальный экземпляр сервиса
_booking_service_instance: Optional[BookingService] = None


def get_booking_service(api_base: str = "http://localhost:5000") -> BookingService:
    """Получить или создать экземпляр сервиса записей."""
    global _booking_service_instance
    if _booking_service_instance is None:
        _booking_service_instance = BookingService(api_base=api_base)
    return _booking_service_instance