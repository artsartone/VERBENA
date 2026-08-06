"""
Общий модуль кэширования данных YClients.

Используется как Telegram, так и VK ботами для хранения:
- категорий услуг
- услуг
- мастеров

Кэш обновляется асинхронно с TTL 60 секунд.
"""
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
import requests


class YClientsCache:
    """Кэш данных YClients с TTL."""

    def __init__(self, api_base: str = "http://localhost:5000", ttl: int = 60):
        self.api_base = api_base
        self.ttl = ttl  # секунд

        self._categories_cache: List[Dict] = []
        self._services_cache: List[Dict] = []
        self._staff_cache: List[Dict] = []
        self._cache_timestamp: datetime = datetime.min
        self._lock = asyncio.Lock()

    def _is_cache_fresh(self) -> bool:
        """Проверить, не устарел ли кэш."""
        return (datetime.now() -
                self._cache_timestamp).total_seconds() < self.ttl

    def refresh_cache(self):
        """Обновить кэш данных YClients."""
        try:

            resp = requests.get(f"{self.api_base}/api/yclients/categories",
                                timeout=10)
            if resp.status_code == 200:
                self._categories_cache = resp.json()

            resp = requests.get(f"{self.api_base}/api/yclients/services",
                                timeout=10)
            if resp.status_code == 200:
                self._services_cache = resp.json()

            resp = requests.get(f"{self.api_base}/api/yclients/staff",
                                timeout=10)
            if resp.status_code == 200:
                self._staff_cache = resp.json()

            self._cache_timestamp = datetime.now()
        except Exception as e:
            print(f"Ошибка обновления кэша YClients: {e}")

    async def refresh_cache_async(self):
        """Асинхронное обновление кэша без блокировки event loop."""
        async with self._lock:
            if self._is_cache_fresh():
                return

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self.refresh_cache)

    @property
    def categories(self) -> List[Dict]:
        """Получить категории из кэша."""
        return self._categories_cache

    @property
    def services(self) -> List[Dict]:
        """Получить услуги из кэша."""
        return self._services_cache

    @property
    def staff(self) -> List[Dict]:
        """Получить мастеров из кэша."""
        return self._staff_cache

    def get_services_for_category(self, category_id: Any) -> List[Dict]:
        """Получить услуги для конкретной категории."""
        cat_id_str = str(category_id)
        result = []
        for svc in self._services_cache:
            svc_cat_id = svc.get("category_id") or (svc.get("category")
                                                    or {}).get("id")
            if str(svc_cat_id or "") == cat_id_str:
                result.append(svc)
        return result

    def get_staff_for_service(self,
                              service_id: Optional[str] = None) -> List[Dict]:
        """Получить мастеров для услуги (через API)."""
        try:
            params = {"service_id": service_id} if service_id else {}
            resp = requests.get(f"{self.api_base}/api/yclients/staff",
                                params=params,
                                timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            print(f"Ошибка получения мастеров: {e}")
        return []


_cache_instance: Optional[YClientsCache] = None


def get_cache(api_base: str = "http://localhost:5000",
              ttl: int = 60) -> YClientsCache:
    """Получить или создать экземпляр кэша."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = YClientsCache(api_base=api_base, ttl=ttl)
    return _cache_instance
