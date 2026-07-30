import sqlite3
import os
import sys
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

# ─── Настройка путей ───
# Добавляем директорию backend в путь поиска модулей, чтобы работали импорты
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# Загружаем переменные окружения из .env файла
load_dotenv(os.path.join(BASE_DIR, '.env'))

# Теперь импорты будут работать корректно
try:
    from notification_link import PROVIDERS
except ImportError:
    # Если модуль все еще не найден, создаем заглушку для константы
    PROVIDERS = ['telegram', 'max'] 

DB_PATH = os.path.join(BASE_DIR, "beauty.db")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
BOT_PROXY = os.environ.get("BOT_PROXY", "")

def send_reminder(tg_id, booking_info):
    """Отправляет напоминание конкретному пользователю."""
    if not tg_id or not BOT_TOKEN:
        return

    message = (
        f"🔔 <b>Напоминание о записи!</b>\n\n"
        f"💇‍♀️ Услуга: {booking_info['service']}\n"
        f"⏰ Время: {booking_info['booking_time']}\n"
        f"📅 Дата: {booking_info['booking_date']}\n\n"
        "Ждем вас в студии VERBENA! 🌸"
    )

    proxies = None
    if BOT_PROXY:
        proxies = {'http': BOT_PROXY, 'https': BOT_PROXY}

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": int(tg_id),
                "text": message,
                "parse_mode": "HTML"
            },
            proxies=proxies,
            timeout=10
        )
        if resp.status_code == 200:
            print(f"✅ Напоминание отправлено для {tg_id}")
        else:
            print(f"❌ Ошибка API для {tg_id}: {resp.text}")
    except Exception as e:
        print(f"❌ Исключение при отправке для {tg_id}: {e}")

def check_and_send_reminders():
    """Основная функция проверки записей."""
    if not os.path.exists(DB_PATH):
        print(f"❌ База данных не найдена по пути: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Вычисляем временное окно: от 59 до 61 минуты от текущего времени
    now = datetime.now()
    target_start = now + timedelta(minutes=59)
    target_end = now + timedelta(minutes=61)
    
    # Формат времени для SQL сравнения (HH:MM)
    time_start_str = target_start.strftime("%H:%M")
    time_end_str = target_end.strftime("%H:%M")
    date_str = now.strftime("%Y-%m-%d") # Проверяем только сегодняшние записи

    print(f"🔍 Поиск записей на сегодня ({date_str}) в интервале {time_start_str} - {time_end_str}")

    # Ищем активные записи, попадающие в интервал
    cur.execute("""
        SELECT b.id, b.client_name, b.service, b.booking_time, b.booking_date, nl.provider_user_id
        FROM bookings b
        JOIN notification_links nl ON b.client_id = nl.client_id
        WHERE b.status = 'active'
        AND b.booking_date = ?
        AND b.booking_time BETWEEN ? AND ?
        AND nl.provider = 'telegram'
    """, (date_str, time_start_str, time_end_str))

    rows = cur.fetchall()
    
    if rows:
        print(f"🚀 Найдено {len(rows)} записей для напоминания.")
        for row in rows:
            tg_id = row['provider_user_id']
            booking_info = {
                'service': row['service'],
                'booking_time': row['booking_time'],
                'booking_date': row['booking_date']
            }
            send_reminder(tg_id, booking_info)
    else:
        print("ℹ️ Записей для напоминания в ближайший час не найдено.")

    conn.close()

if __name__ == "__main__":
    check_and_send_reminders()