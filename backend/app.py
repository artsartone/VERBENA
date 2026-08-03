import sys
import os
import re
import csv
import io
import time

# ─── Настройка путей (ОБЯЗАТЕЛЬНО ДО ОСТАЛЬНЫХ ИМПОРТОВ) ───
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'notifications'))

# Теперь можно импортировать локальные модули
from dotenv import load_dotenv

load_dotenv(os.path.join(BASE_DIR, '.env'))

import sqlite3
import json
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, redirect, request, jsonify, send_from_directory, session, Response, stream_with_context
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date

import yclients_api as yc
from client_identity import get_or_create_client
from notification_link import create_token, build_deeplink, link_directly, is_linked, redeem_token, PROVIDERS
from notification_service import notify_client
import logging
import subprocess, urllib.parse

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ─── Формат дат ───
def to_iso_date(dd_mm_yyyy):
    """ДД.ММ.ГГГГ → ГГГГ-ММ-ДД (для БД/SQL)."""
    if not dd_mm_yyyy or not isinstance(dd_mm_yyyy, str):
        return dd_mm_yyyy
    parts = dd_mm_yyyy.split(".")
    if len(parts) == 3 and len(parts[2]) == 4:
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return dd_mm_yyyy


def from_iso_date(yyyy_mm_dd):
    """ГГГГ-ММ-ДД → ДД.ММ.ГГГГ (для отображения)."""
    if not yyyy_mm_dd or not isinstance(yyyy_mm_dd, str):
        return yyyy_mm_dd
    parts = yyyy_mm_dd.split("-")
    if len(parts) == 3 and len(parts[0]) == 4:
        return f"{parts[2]}.{parts[1]}.{parts[0]}"
    return yyyy_mm_dd


def convert_booking_dates(booking_dict):
    """Преобразовать дату в booking_dict из ISO в ДД.ММ.ГГГГ для ответа клиенту."""
    if "booking_date" in booking_dict:
        booking_dict["booking_date"] = from_iso_date(
            booking_dict["booking_date"])
    if "completed_at" in booking_dict:
        booking_dict["completed_at"] = from_iso_date(
            booking_dict["completed_at"])
    return booking_dict


app = Flask(__name__,
            static_folder=None,
            template_folder=os.path.join(BASE_DIR, "templates"))

# ─── SECRET_KEY ───
_secret_key_env = os.environ.get("SECRET_KEY")
if _secret_key_env:
    app.secret_key = _secret_key_env
else:
    _secret_key_path = os.path.join(BASE_DIR, ".secret_key")
    if os.path.exists(_secret_key_path):
        with open(_secret_key_path, "r") as f:
            app.secret_key = f.read().strip()
    else:
        app.secret_key = os.urandom(24).hex()
        with open(_secret_key_path, "w") as f:
            f.write(app.secret_key)

app.permanent_session_lifetime = timedelta(hours=12)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FORCE_HTTPS") == "1",
)
CORS(app, supports_credentials=True)

DB_PATH = os.path.join(BASE_DIR, "beauty.db")


# ─── Очистка записей старше 2 дней ───
def _cleanup_old_bookings():
    """Удаляет записи и историю старше 2 дней, вызывается при старте и раз в сутки."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM bookings WHERE booking_date < date('now', '-2 days')")
        deleted_bookings = cur.rowcount
        cur.execute(
            "DELETE FROM services_history WHERE completed_at < datetime('now', '-2 days', '+3 hours')"
        )
        deleted_history = cur.rowcount
        conn.commit()
        conn.close()
        if deleted_bookings > 0 or deleted_history > 0:
            logger.info(
                f"Очистка: удалено {deleted_bookings} записей, {deleted_history} историй"
            )
    except Exception as e:
        logger.error(f"Ошибка очистки: {e}")


def _run_daily_cleanup():
    """Запускает очистку раз в сутки."""
    while True:
        threading.Event().wait(86400)
        _cleanup_old_bookings()


# Инициализируем БД
# Очищаем при старте
_cleanup_old_bookings()
threading.Thread(target=_run_daily_cleanup, daemon=True).start()

# ─── SSE уведомления (поток событий) ───
# Каждый клиент SSE регистрирует свою очередь.
# При создании записи событие публикуется во все очереди.
_sse_clients = []
_sse_lock = threading.Lock()


def sse_broadcast(event_type, data):
    """Отправить событие всем подключённым SSE-клиентам."""
    with _sse_lock:
        for q in _sse_clients[:]:
            try:
                q.put((event_type, data))
            except Exception:
                if q in _sse_clients:
                    _sse_clients.remove(q)


# ──────────── БД ────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 1. Создаем основные таблицы
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'employee' CHECK(role IN ('admin','employee')),
        display_name TEXT NOT NULL DEFAULT '',
        position TEXT NOT NULL DEFAULT '',
        telegram_id TEXT NOT NULL DEFAULT '',
        vk_id TEXT NOT NULL DEFAULT '',
        notify_enabled INTEGER NOT NULL DEFAULT 0,
        vk_notify_enabled INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now', '+3 hours'))
    );
    CREATE TABLE IF NOT EXISTS clients (
         id INTEGER PRIMARY KEY AUTOINCREMENT,
         phone TEXT NOT NULL UNIQUE,
         display_name TEXT NOT NULL DEFAULT '',
         created_at TEXT NOT NULL DEFAULT (datetime('now', '+3 hours')),
         updated_at TEXT NOT NULL DEFAULT (datetime('now', '+3 hours'))
     );
     CREATE TABLE IF NOT EXISTS bookings (
         id INTEGER PRIMARY KEY AUTOINCREMENT,
         client_name TEXT NOT NULL,
         client_phone TEXT NOT NULL,
         service TEXT NOT NULL,
         booking_date TEXT NOT NULL,
         booking_time TEXT NOT NULL,
         status TEXT NOT NULL DEFAULT 'active',
         comment TEXT DEFAULT '',
         assigned_employee_id INTEGER DEFAULT NULL,
         assigned_employee_name TEXT DEFAULT '',
         yclients_staff_id TEXT DEFAULT NULL,
         client_id INTEGER DEFAULT NULL REFERENCES clients(id),
         created_at TEXT NOT NULL DEFAULT (datetime('now', '+3 hours')),
         FOREIGN KEY (assigned_employee_id) REFERENCES users(id)
     );
     CREATE TABLE IF NOT EXISTS services_history (
         id INTEGER PRIMARY KEY AUTOINCREMENT,
         booking_id INTEGER,
         client_name TEXT NOT NULL,
         client_phone TEXT NOT NULL,
         service TEXT NOT NULL,
         price TEXT DEFAULT '',
         status TEXT NOT NULL DEFAULT 'completed',
         completed_at TEXT NOT NULL DEFAULT (datetime('now', '+3 hours')),
         FOREIGN KEY (booking_id) REFERENCES bookings(id)
     );
     CREATE TABLE IF NOT EXISTS telegram_clients (
         id INTEGER PRIMARY KEY AUTOINCREMENT,
         telegram_id TEXT NOT NULL,
         phone TEXT NOT NULL,
         client_name TEXT NOT NULL DEFAULT '',
         created_at TEXT NOT NULL DEFAULT (datetime('now', '+3 hours')),
         UNIQUE(telegram_id, phone)
     );
     CREATE TABLE IF NOT EXISTS career_applications (
         id INTEGER PRIMARY KEY AUTOINCREMENT,
         client_name TEXT NOT NULL,
         client_phone TEXT NOT NULL,
         experience TEXT NOT NULL,
         resume TEXT DEFAULT '',
         cover_letter TEXT DEFAULT '',
         source TEXT DEFAULT 'site',
         telegram_id TEXT DEFAULT '',
         created_at TEXT NOT NULL DEFAULT (datetime('now', '+3 hours'))
     );
     CREATE TABLE IF NOT EXISTS notification_log (
         id INTEGER PRIMARY KEY AUTOINCREMENT,
         booking_id INTEGER NOT NULL,
         channel TEXT NOT NULL,
         created_at TEXT NOT NULL DEFAULT (datetime('now', '+3 hours')),
         UNIQUE(booking_id, channel)
     );
    """)
    conn.commit()

    # 2. Добавляем недостающие колонки (БЕЗОПАСНО через try/except)
    migrations = [
        "ALTER TABLE users ADD COLUMN position TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE bookings ADD COLUMN assigned_employee_id INTEGER DEFAULT NULL REFERENCES users(id)",
        "ALTER TABLE bookings ADD COLUMN assigned_employee_name TEXT DEFAULT ''",
        "ALTER TABLE services_history ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'",
        "ALTER TABLE services_history ADD COLUMN cancelled_at TEXT DEFAULT NULL",
        "ALTER TABLE services_history ADD COLUMN assigned_employee_name TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN telegram_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE users ADD COLUMN vk_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE users ADD COLUMN vk_notify_enabled INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN notify_enabled INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE bookings ADD COLUMN yclients_staff_id TEXT DEFAULT NULL",
        # ✅ ВАЖНО: Добавляем ОБЕ колонки для интеграции с YClients
        "ALTER TABLE bookings ADD COLUMN yclients_record_id TEXT DEFAULT NULL",
        "ALTER TABLE bookings ADD COLUMN yclients_record_hash TEXT DEFAULT NULL"
    ]

    for sql in migrations:
        try:
            cur.execute(sql)
        except sqlite3.OperationalError:
            pass  # Колонка уже существует

    conn.commit()

    # 3. Миграция дат (ДД.ММ.ГГГГ -> ГГГГ-ММ-ДД)
    # Делаем это ПОСЛЕ добавления всех колонок, чтобы избежать конфликтов
    for table, col in [("bookings", "booking_date"),
                       ("services_history", "completed_at")]:
        try:
            cur.execute(
                f"SELECT id, {col} FROM {table} WHERE {col} LIKE '__.__.____'")
            for row_id, old_date in cur.fetchall():
                iso = to_iso_date(old_date)
                if iso != old_date:
                    cur.execute(f"UPDATE {table} SET {col} = ? WHERE id = ?",
                                (iso, row_id))
        except sqlite3.OperationalError:
            pass

    conn.commit()

    # 4. Создание дефолтных пользователей
    defaults = [
        ("admin", "admin123", "admin", "Администратор", "Руководитель"),
        ("employee", "employee123", "employee", "Сотрудник", "Мастер"),
    ]
    for username, password, role, display_name, position in defaults:
        cur.execute("SELECT id FROM users WHERE username = ?", (username, ))
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO users (username, password_hash, role, display_name, position) VALUES (?, ?, ?, ?, ?)",
                (username, generate_password_hash(password), role,
                 display_name, position),
            )
    conn.commit()

    # 5. Инициализация схемы уведомлений
    notification_schema_path = os.path.join(BASE_DIR, "notifications",
                                            "notification_schema.sql")
    if os.path.exists(notification_schema_path):
        with open(notification_schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        try:
            cur.executescript(schema_sql)
            conn.commit()
        except sqlite3.OperationalError as e:
            logger.warning(f"Notification schema init warning: {e}")

    # ✅ ЗАКРЫВАЕМ СОЕДИНЕНИЕ ТОЛЬКО ЗДЕСЬ, ПОСЛЕ ВСЕХ ОПЕРАЦИЙ
    conn.close()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def login_required(f):

    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Не авторизован"}), 401
        return f(*args, **kwargs)

    return wrapper


def admin_required(f):

    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Не авторизован"}), 401
        if session.get("role") != "admin":
            return jsonify({"error": "Доступ запрещён"}), 403
        return f(*args, **kwargs)

    return wrapper


# ──────────── АВТОРИЗАЦИЯ ────────────
@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify({"error": "Введите логин и пароль"}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?", (username, ))
    user = cur.fetchone()
    conn.close()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Неверный логин или пароль"}), 401
    session.permanent = True
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["role"] = user["role"]
    session["display_name"] = user["display_name"]
    return jsonify({
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "display_name": user["display_name"],
        "position": user["position"],
        "telegram_id": user["telegram_id"],
        "vk_id": user["vk_id"],
        "notify_enabled": user["notify_enabled"],
        "vk_notify_enabled": user["vk_notify_enabled"],
    })


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    session.clear()
    return jsonify({"message": "Выход выполнен"})


@app.route("/api/auth/me", methods=["GET"])
@login_required
def auth_me():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, username, role, display_name, position, telegram_id, vk_id, notify_enabled, vk_notify_enabled FROM users WHERE id = ?",
        (session["user_id"], ))
    user = cur.fetchone()
    conn.close()
    if not user:
        return jsonify({"error": "Пользователь не найден"}), 404
    return jsonify({
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "display_name": user["display_name"],
        "position": user["position"],
        "telegram_id": user["telegram_id"],
        "vk_id": user["vk_id"],
        "notify_enabled": user["notify_enabled"],
        "vk_notify_enabled": user["vk_notify_enabled"],
    })


# ──────────── ЗАПИСИ ────────────
@app.route("/api/bookings", methods=["GET"])
@login_required
def get_bookings():
    status_filter = request.args.get("status", "all")
    service_filter = request.args.get("service", "")
    employee_filter = request.args.get("employee", "")
    date_from = to_iso_date(request.args.get("date_from", ""))
    date_to = to_iso_date(request.args.get("date_to", ""))
    conditions = []
    params = []
    if status_filter != "all":
        if "," in status_filter:
            parts = [s.strip() for s in status_filter.split(",") if s.strip()]
            placeholders = ",".join("?" for _ in parts)
            conditions.append(f"status IN ({placeholders})")
            params.extend(parts)
        else:
            conditions.append("status = ?")
            params.append(status_filter)
    if service_filter:
        conditions.append("service LIKE ?")
        params.append(f"%{service_filter}%")
    if employee_filter:
        conditions.append("assigned_employee_id = ?")
        params.append(employee_filter)
    if date_from:
        conditions.append("booking_date >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("booking_date <= ?")
        params.append(date_to)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        f"SELECT * FROM bookings {where} ORDER BY booking_date DESC, booking_time DESC",
        params,
    )
    rows = [convert_booking_dates(dict(r)) for r in cur.fetchall()]
    conn.close()
    return jsonify(rows)


@app.route("/api/bookings/next-id", methods=["GET"])
def get_next_booking_id():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM bookings")
    next_id = cur.fetchone()[0]
    conn.close()
    return jsonify({"next_id": next_id})


@app.route("/api/bookings", methods=["POST"])
def create_booking():
    """Публичное создание записи + SSE-уведомление."""
    data = request.get_json()
    required = [
        "client_name", "client_phone", "service", "booking_date",
        "booking_time"
    ]
    field_names = {
        "client_name": "Клиент",
        "client_phone": "Телефон",
        "service": "Услуга",
        "booking_date": "Дата",
        "booking_time": "Время",
    }
    for field in required:
        if not data.get(field):
            return jsonify({
                "error":
                f"Пожалуйста, заполните поле «{field_names.get(field, field)}»"
            }), 400
    data["booking_date"] = to_iso_date(data.get("booking_date", ""))
    conn = get_db()
    cur = conn.cursor()
    if data.get("booking_date"):
        local_emp_id = data.get("assigned_employee_id")
        yc_staff_id = data.get("yclients_staff_id")
        if local_emp_id:
            cur.execute(
                "SELECT id FROM bookings WHERE booking_date = ? AND booking_time = ? AND assigned_employee_id = ? AND status IN ('active','pending')",
                (data["booking_date"], data["booking_time"], local_emp_id),
            )
        elif yc_staff_id:
            cur.execute(
                "SELECT id FROM bookings WHERE booking_date = ? AND booking_time = ? AND yclients_staff_id = ? AND status IN ('active','pending')",
                (data["booking_date"], data["booking_time"], yc_staff_id),
            )
        else:
            cur.execute(
                "SELECT id FROM bookings WHERE booking_date = ? AND booking_time = ? AND status IN ('active','pending')",
                (data["booking_date"], data["booking_time"]),
            )
        if cur.fetchone():
            conn.close()
            return jsonify({"error": "Это время уже занято"}), 409
    phone = (data.get("client_phone") or "").strip()
    if phone != "—" and phone != "-":
        cleaned = phone.replace("+", "").replace(" ",
                                                 "").replace("-", "").replace(
                                                     "(", "").replace(")", "")
        if not cleaned.isdigit() or len(cleaned) < 10:
            return jsonify({
                "error":
                "Телефон должен быть в формате +71234567890 или «—»"
            }), 400
    # ─── Resolve/create client_id from phone (before local insert, before YClients) ───
    client_id = -1
    if phone not in ("—", "-") and len(phone) >= 10:
        try:
            client_id = get_or_create_client(conn,
                                             phone,
                                             display_name=data["client_name"])
        except ValueError as e:
            logger.warning(f"Не удалось создать клиента: {e}")
        except Exception as e:
            logger.error(f"Ошибка resolve клиента: {e}")
    # ─── Запись в локальную БД ───
    if session.get("user_id"):
        status = data.get("status") or "pending"
    else:
        status = "pending"
    cur.execute(
        """INSERT INTO bookings (client_name, client_phone, service, booking_date, booking_time, status, comment, assigned_employee_id, assigned_employee_name, yclients_staff_id, client_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (data["client_name"],
         data["client_phone"] if data["client_phone"] != "—" else "",
         data["service"], data["booking_date"], data["booking_time"], status,
         data.get("comment", ""), data.get("assigned_employee_id"),
         data.get("assigned_employee_name", ""),
         str(data.get("yclients_staff_id")) if data.get("yclients_staff_id")
         else None, client_id if client_id > 0 else None),
    )
    conn.commit()
    booking_id = cur.lastrowid

    # ─── Отправка в YClients (если настроено) ───
    yclients_service_id = data.get("yclients_service_id")
    yclients_staff_id = data.get("yclients_staff_id")
    if yclients_service_id and yclients_staff_id and yc.YCLIENTS_TOKEN:

        def _send_to_yclients():
            try:
                # ... (код нормализации телефона и даты остается прежним) ...
                clean_phone = phone.replace(" ", "").replace("-", "").replace(
                    "(", "").replace(")", "").replace("+", "")
                if not clean_phone.startswith(
                        "7") and not clean_phone.startswith("8"):
                    clean_phone = "7" + clean_phone

                yc_date = data["booking_date"]
                if "." in yc_date:
                    parts = yc_date.split(".")
                    yc_date = f"{parts[2]}-{parts[1]}-{parts[0]}"

                result = yc.create_booking(
                    client_name=data["client_name"],
                    client_phone=clean_phone,
                    service_id=yclients_service_id,
                    staff_id=yclients_staff_id,
                    date_str=yc_date,
                    time_str=data["booking_time"],
                    comment=data.get("comment", ""),
                )

                if result["success"]:
                    record_id = result.get('record_id')
                    record_hash = result.get('hash')

                    # Сохраняем ОБА значения в локальную БД
                    n_conn = get_db()
                    n_cur = n_conn.cursor()
                    n_cur.execute(
                        "UPDATE bookings SET yclients_record_id = ?, yclients_record_hash = ? WHERE id = ?",
                        (str(record_id), record_hash, booking_id))
                    n_conn.commit()
                    n_conn.close()

                    # Вычёркиваем занятое время у мастера из уже
                    # закэшированного /api/public/free-slots на эту дату —
                    # без этого пользователь увидит слот свободным ещё до
                    # 5 минут (TTL кэша), хотя запись только что ушла в YClients.
                    _remove_booked_slot_from_cache(yc_date, yclients_staff_id,
                                                   data["booking_time"])

                    logger.info(
                        f"YClients booking saved locally: id={record_id}, hash={record_hash}"
                    )
                else:
                    logger.error(f"YClients booking failed: {result['error']}")
            except Exception as e:
                logger.error(f"YClients booking exception: {e}", exc_info=True)

        threading.Thread(target=_send_to_yclients, daemon=True).start()

    def _send_telegram_notify():
        import os as _os
        import logging as _logging
        _logger = _logging.getLogger("telegram_notify")
        _logger.setLevel(_logging.INFO)
        if not _logger.handlers:
            _h = _logging.StreamHandler()
            _h.setFormatter(
                _logging.Formatter(
                    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
            _logger.addHandler(_h)
        token = _os.environ.get("BOT_TOKEN", "")
        proxy_conf = _os.environ.get("BOT_PROXY", "")
        if not token:
            _logger.warning("BOT_TOKEN не задан — уведомления не отправляются")
            return
        try:
            # Получаем список уведомляемых через сам API
            users_raw = subprocess.run([
                "curl", "-s", "--max-time", "5",
                "http://127.0.0.1:5000/api/telegram/notify-users"
            ],
                                       capture_output=True,
                                       text=True,
                                       timeout=10)
            if users_raw.returncode != 0:
                _logger.error(
                    f"Ошибка вызова notify-users: stderr={users_raw.stderr}")
                return
            users = json.loads(users_raw.stdout or "[]")
            if not users:
                _logger.info("Нет пользователей с notify_enabled=1")
                return
            # Дедупликация: не отправляем дважды для одной записи.
            # SQLite блокирует БД при параллельной записи, поэтому делаем retry;
            # при любой ошибке НЕ отправляем (чтобы избежать дубля).
            for attempt in range(10):
                try:
                    dup_conn = sqlite3.connect(DB_PATH, timeout=10)
                    dup_cur = dup_conn.cursor()
                    dup_cur.execute(
                        "INSERT OR IGNORE INTO notification_log (booking_id, channel) VALUES (?, 'tg')",
                        (booking_id, ))
                    dup_inserted = dup_cur.rowcount
                    dup_conn.commit()
                    dup_conn.close()
                    break
                except Exception as dup_e:
                    try:
                        dup_conn.close()
                    except Exception:
                        pass
                    _logger.warning(
                        f"TG дедуп retry {attempt + 1} для записи {booking_id}: {dup_e}"
                    )
                    dup_inserted = 0
                    import time as _time
                    _time.sleep(0.3)
            if dup_inserted == 0:
                _logger.info(
                    f"TG-уведомление уже отправлено для записи {booking_id}, пропускаем"
                )
                return
            _logger.info(
                f"Отправка уведомлений {len(users)} пользователям (proxy={'да' if proxy_conf else 'нет'})"
            )
            text = (
                "📢 <b>Новая запись в студию VERBENA!</b>\n\n"
                f"👤 Клиент: {data['client_name']}\n"
                f"💇‍♀️ Услуга: {data['service']}\n"
                f"📅 Дата: {data['booking_date']}\n"
                f"⏰ Время: {data['booking_time']}\n"
                f"📞 Телефон: {phone}\n\n"
                "🔗 <a href='https://yclients.com/dashboard_records/2101920'>Управлять записями Verbena</a>"
            )
            for u in users:
                tg_id = u.get("telegram_id", "").strip()
                if not tg_id or not tg_id.isdigit():
                    continue
                cmd = [
                    "curl",
                    "-s",
                    "--max-time",
                    "15",
                    "-X",
                    "POST",
                    "-H",
                    "Content-Type: application/json",
                    "-d",
                    json.dumps({
                        "chat_id": int(tg_id),
                        "text": text,
                        "parse_mode": "HTML",
                    }),
                    f"https://api.telegram.org/bot{token}/sendMessage",
                ]
                if proxy_conf:
                    cmd.insert(1, "-x")
                    cmd.insert(2, proxy_conf)
                result = subprocess.run(cmd,
                                        capture_output=True,
                                        text=True,
                                        timeout=20)
                if result.returncode != 0:
                    _logger.error(
                        f"Ошибка отправки пользователю {tg_id}: stderr={result.stderr}"
                    )
                else:
                    resp_data = json.loads(result.stdout or "{}")
                    if not resp_data.get("ok"):
                        _logger.error(
                            f"Telegram API ошибка для пользователя {tg_id}: {resp_data}"
                        )
                    else:
                        _logger.info(
                            f"Уведомление отправлено пользователю {tg_id}")
        except Exception as e:
            _logger.error(f"Исключение в _send_telegram_notify: {e}",
                          exc_info=True)

    def _send_vk_notify():
        """VK-уведомления о новой записи (для источников: сайт, ТГ, VK)."""
        import os as _os
        import logging as _logging
        _logger = _logging.getLogger("vk_notify")
        _logger.setLevel(_logging.INFO)
        if not _logger.handlers:
            _h = _logging.StreamHandler()
            _h.setFormatter(
                _logging.Formatter(
                    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
            _logger.addHandler(_h)
        vk_token = _os.environ.get("BOT_TOKEN_VK", "")
        if not vk_token:
            _logger.warning(
                "BOT_TOKEN_VK не задан — VK-уведомления не отправляются")
            return
        try:
            import requests as _requests
            # Получаем список уведомляемых через сам API
            users_raw = subprocess.run([
                "curl", "-s", "--max-time", "5",
                "http://127.0.0.1:5000/api/vk/notify-users"
            ],
                                       capture_output=True,
                                       text=True,
                                       timeout=10)
            if users_raw.returncode != 0:
                _logger.error(
                    f"Ошибка вызова vk/notify-users: stderr={users_raw.stderr}"
                )
                return
            users = json.loads(users_raw.stdout or "[]")
            if not users:
                _logger.info("Нет пользователей с vk_notify_enabled=1")
                return
            # Дедупликация: не отправляем дважды для одной записи.
            # SQLite блокирует БД при параллельной записи, поэтому делаем retry;
            # при любой ошибке НЕ отправляем (чтобы избежать дубля).
            for attempt in range(10):
                try:
                    dup_conn = sqlite3.connect(DB_PATH, timeout=10)
                    dup_cur = dup_conn.cursor()
                    dup_cur.execute(
                        "INSERT OR IGNORE INTO notification_log (booking_id, channel) VALUES (?, 'vk')",
                        (booking_id, ))
                    dup_inserted = dup_cur.rowcount
                    dup_conn.commit()
                    dup_conn.close()
                    break
                except Exception as dup_e:
                    try:
                        dup_conn.close()
                    except Exception:
                        pass
                    _logger.warning(
                        f"VK дедуп retry {attempt + 1} для записи {booking_id}: {dup_e}"
                    )
                    dup_inserted = 0
                    import time as _time
                    _time.sleep(0.3)
            if dup_inserted == 0:
                _logger.info(
                    f"VK-уведомление уже отправлено для записи {booking_id}, пропускаем"
                )
                return
            _logger.info(f"Отправка VK-уведомлений {len(users)} пользователям")
            text = (
                "📢 Новая запись в студию VERBENA!\n\n"
                f"👤 Клиент: {data['client_name']}\n"
                f"💇‍♀️ Услуга: {data['service']}\n"
                f"📅 Дата: {data['booking_date']}\n"
                f"⏰ Время: {data['booking_time']}\n"
                f"📞 Телефон: {phone}\n\n"
                "🔗 Управлять записями Verbena: https://yclients.com/dashboard_records/2101920"
            )
            for u in users:
                vk_id = u.get("vk_id", "").strip()
                if not vk_id or not vk_id.lstrip("-").isdigit():
                    continue
                try:
                    r = _requests.post(
                        "https://api.vk.com/method/messages.send",
                        data={
                            "access_token": vk_token,
                            "v": "5.199",
                            "user_id": int(vk_id),
                            "message": text,
                            "random_id": 0,
                        },
                        timeout=15,
                    )
                    resp_data = r.json()
                    if "error" in resp_data:
                        _logger.error(
                            f"VK API ошибка для пользователя {vk_id}: {resp_data['error']}"
                        )
                    else:
                        _logger.info(
                            f"VK-уведомление отправлено пользователю {vk_id}")
                except Exception as e:
                    _logger.error(
                        f"Ошибка отправки VK-уведомления {vk_id}: {e}")
        except Exception as e:
            _logger.error(f"Исключение в _send_vk_notify: {e}", exc_info=True)

    threading.Thread(target=_send_telegram_notify, daemon=True).start()
    threading.Thread(target=_send_vk_notify, daemon=True).start()
    return jsonify({
        "id": booking_id,
        "client_id": client_id,
        "message": "Запись создана"
    }), 201


@app.post("/api/admin/restart-bot/<bot_name>")
def restart_bot(bot_name):

    services = {
        "telegram": "verbena-bot.service",
        "vk": "beautyverbena-vk.service"
    }

    if bot_name not in services:
        return jsonify({"success": False, "error": "Unknown bot"}), 400

    service = services[bot_name]

    subprocess.run(["sudo", "systemctl", "restart", service], check=True)

    return jsonify({"success": True, "service": service})


@app.route("/api/bookings/<int:booking_id>", methods=["PUT"])
@login_required
def update_booking(booking_id):
    data = request.get_json()
    role = session.get("role")
    conn = get_db()
    cur = conn.cursor()
    if role == "employee":
        allowed = data.get("status") in ("active", "completed", "cancelled")
        if not allowed:
            conn.close()
            return jsonify({"error": "Доступ запрещён"}), 403
    updates = []
    params = []
    if "booking_date" in data:
        data["booking_date"] = to_iso_date(data["booking_date"])
    # ─── Читаем текущее состояние ДО любых изменений ───
    cur.execute("SELECT * FROM bookings WHERE id = ?", (booking_id, ))
    old_row = cur.fetchone()
    if not old_row:
        conn.close()
        return jsonify({"error": "Запись не найдена"}), 404
    old_booking = dict(old_row)
    if "booking_date" in data or "booking_time" in data or "assigned_employee_id" in data or "yclients_staff_id" in data:
        new_date = data.get("booking_date") or None
        new_time = data.get("booking_time") or None
        local_emp_id = data.get("assigned_employee_id") or None
        yc_staff_id = data.get("yclients_staff_id") or None
        if new_date and new_time and (local_emp_id is not None
                                      or yc_staff_id is not None):
            if local_emp_id is not None:
                cur.execute(
                    "SELECT id FROM bookings WHERE booking_date = ? AND booking_time = ? AND assigned_employee_id = ? AND status IN ('active','pending') AND id != ?",
                    (new_date, new_time, local_emp_id, booking_id),
                )
            else:
                cur.execute(
                    "SELECT id FROM bookings WHERE booking_date = ? AND booking_time = ? AND yclients_staff_id = ? AND status IN ('active','pending') AND id != ?",
                    (new_date, new_time, yc_staff_id, booking_id),
                )
            if cur.fetchone():
                conn.close()
                return jsonify({
                    "error":
                    f"На {new_date} в {new_time} у сотрудника уже есть запись"
                }), 409
    if "status" in data:
        updates.append("status = ?")
        params.append(data["status"])
        if data["status"] in ("completed", "cancelled"):
            cur.execute("SELECT * FROM bookings WHERE id = ?", (booking_id, ))
            b = cur.fetchone()
            if b:
                emp_name = b["assigned_employee_name"] if b[
                    "assigned_employee_name"] else data.get(
                        "assigned_employee_name", "")
                cur.execute(
                    """INSERT INTO services_history (booking_id, client_name, client_phone, service, price, status, assigned_employee_name)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (b[0], b[1], b[2], b[3], data.get(
                        "price", ""), data["status"], emp_name),
                )
    if "comment" in data:
        updates.append("comment = ?")
        params.append(data["comment"])
    if "client_name" in data:
        updates.append("client_name = ?")
        params.append(data["client_name"])
    if "client_phone" in data:
        updates.append("client_phone = ?")
        params.append(data["client_phone"])
    if "service" in data:
        updates.append("service = ?")
        params.append(data["service"])
    if "booking_date" in data:
        updates.append("booking_date = ?")
        params.append(data["booking_date"])
    if "booking_time" in data:
        updates.append("booking_time = ?")
        params.append(data["booking_time"])
    if "assigned_employee_id" in data:
        updates.append("assigned_employee_id = ?")
        params.append(data["assigned_employee_id"])
        updates.append("assigned_employee_name = ?")
        params.append(data.get("assigned_employee_name", ""))
    if "yclients_staff_id" in data:
        updates.append("yclients_staff_id = ?")
        params.append(data["yclients_staff_id"])
    if updates:
        params.append(booking_id)
        cur.execute(
            f"UPDATE bookings SET {', '.join(updates)} WHERE id = ?",
            params,
        )
    conn.commit()
    # ─── Детектируем реальное изменение даты/времени сравнением с old_booking ───
    reschedule_date = data.get("booking_date") or old_booking["booking_date"]
    reschedule_time = data.get("booking_time") or old_booking["booking_time"]
    date_changed = ("booking_date" in data
                    and data["booking_date"] != old_booking["booking_date"])
    time_changed = ("booking_time" in data
                    and data["booking_time"] != old_booking["booking_time"])
    conn.close()

    return jsonify({"message": "Обновлено"})  # <--- ВАЖНО: Вернуть ответ!


@app.route("/api/bookings/<int:booking_id>", methods=["DELETE"])
@admin_required
def delete_booking(booking_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM bookings WHERE id = ?", (booking_id, ))
    conn.commit()
    conn.close()
    return jsonify({"message": "Удалено"})


# @app.route("/api/bookings/<int:booking_id>/cancel", methods=["POST"])
# def cancel_booking_public(booking_id):
#     """Публичная отмена записи (для Telegram-бота)."""
#     conn = get_db()
#     cur = conn.cursor()
#     cur.execute("SELECT * FROM bookings WHERE id = ?", (booking_id, ))
#     booking = cur.fetchone()
#     if not booking:
#         conn.close()
#         return jsonify({"error": "Запись не найдена"}), 404
#     if booking["status"] not in ("active", "pending"):
#         conn.close()
#         return jsonify({"error": "Запись уже отменена или завершена"}), 409
#     cur.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?",
#                 (booking_id, ))
#     # Добавляем в историю
#     cur.execute(
#         """INSERT INTO services_history (booking_id, client_name, client_phone, service, price, status, assigned_employee_name)
# VALUES (?, ?, ?, ?, ?, 'cancelled', ?)""",
#         (booking["id"], booking["client_name"], booking["client_phone"],
#          booking["service"], "", booking["assigned_employee_name"] or ""),
#     )
#     conn.commit()
#     conn.close()


@app.route("/api/available-times", methods=["GET"])
def get_available_times():
    date = to_iso_date(request.args.get("date", ""))
    employee_id = request.args.get("employee_id", "")
    if not date:
        return jsonify({"error": "Укажите параметр date"}), 400
    all_slots = [
        f"{h:02d}:{m:02d}" for h in range(10, 20) for m in range(0, 60, 15)
    ]
    conn = get_db()
    cur = conn.cursor()
    if employee_id:
        cur.execute(
            "SELECT booking_time FROM bookings WHERE booking_date = ? AND status IN ('active', 'pending') AND assigned_employee_id = ?",
            (date, employee_id),
        )
    else:
        cur.execute(
            "SELECT booking_time FROM bookings WHERE booking_date = ? AND status IN ('active', 'pending')",
            (date, ),
        )
    booked = {r[0] for r in cur.fetchall()}
    conn.close()
    return jsonify([{
        "time": s,
        "available": s not in booked
    } for s in all_slots])


# ──────────── ИСТОРИЯ ────────────
@app.route("/api/history", methods=["GET"])
@login_required
def get_history():
    conn = get_db()
    cur = conn.cursor()
    status_filter = request.args.get("status", "all")
    date_from = to_iso_date(request.args.get("date_from", ""))
    date_to = to_iso_date(request.args.get("date_to", ""))
    filter_client = request.args.get("client", "").strip()
    filter_phone = request.args.get("phone", "").strip()
    filter_service = request.args.get("service", "").strip()
    filter_master = request.args.get("master", "").strip()
    filter_price = request.args.get("price", "").strip()
    conditions = []
    params = []
    if status_filter in ("completed", "cancelled"):
        conditions.append("status = ?")
        params.append(status_filter)
    if date_from:
        conditions.append("completed_at >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("completed_at <= ?")
        params.append(date_to)
    if filter_client:
        conditions.append("client_name LIKE ?")
        params.append(f"%{filter_client}%")
    if filter_phone:
        conditions.append("client_phone LIKE ?")
        params.append(f"%{filter_phone}%")
    if filter_service:
        conditions.append("service LIKE ?")
        params.append(f"%{filter_service}%")
    if filter_master:
        conditions.append("assigned_employee_name LIKE ?")
        params.append(f"%{filter_master}%")
    if filter_price:
        conditions.append("price LIKE ?")
        params.append(f"%{filter_price}%")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    cur.execute(
        f"SELECT * FROM services_history {where} ORDER BY completed_at DESC",
        params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(rows)


# ──────────── СТАТИСТИКА ────────────
@app.route("/api/stats", methods=["GET"])
@login_required
def get_stats():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as total FROM bookings")
    total_bookings = cur.fetchone()["total"]
    cur.execute(
        "SELECT COUNT(*) as total FROM bookings WHERE status IN ('active', 'pending')"
    )
    active_bookings = cur.fetchone()["total"]
    cur.execute(
        "SELECT COUNT(*) as total FROM bookings WHERE status = 'completed'")
    completed_bookings = cur.fetchone()["total"]
    cur.execute("SELECT COUNT(*) as total FROM services_history")
    total_services = cur.fetchone()["total"]
    cur.execute(
        "SELECT COUNT(DISTINCT assigned_employee_id) FROM bookings WHERE assigned_employee_id IS NOT NULL"
    )
    total_employees_active = cur.fetchone()[0] or 0
    result = {
        "total_bookings": total_bookings,
        "active_bookings": active_bookings,
        "completed_bookings": completed_bookings,
        "total_services": total_services,
        "total_employees_active": total_employees_active,
    }
    if session.get("role") == "admin":
        cur.execute(
            "SELECT SUM(CAST(REPLACE(REPLACE(price, ' ', ''), '₽', '') AS INTEGER)) "
            "FROM services_history WHERE price != '' AND price != '—'")
        row = cur.fetchone()
        result["total_sum"] = row[0] if row and row[0] else 0
    conn.close()
    return jsonify(result)


# ──────────── УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ ────────────
@app.route("/api/users", methods=["GET"])
@admin_required
def get_users():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, username, role, display_name, position, telegram_id, notify_enabled, created_at FROM users ORDER BY id"
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(rows)


@app.route("/api/users", methods=["POST"])
@admin_required
def create_user():
    data = request.get_json()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    display_name = (data.get("display_name") or "").strip()
    position = (data.get("position") or "").strip()
    role = data.get("role", "employee")
    telegram_id = (data.get("telegram_id") or "").strip()
    notify_enabled = 1 if data.get("notify_enabled") else 0
    if not username or not password:
        return jsonify({"error": "Логин и пароль обязательны"}), 400
    if role not in ("admin", "employee"):
        return jsonify({"error": "Недопустимая роль"}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = ?", (username, ))
    if cur.fetchone():
        conn.close()
        return jsonify(
            {"error": "Пользователь с таким логином уже существует"}), 409
    cur.execute(
        "INSERT INTO users (username, password_hash, role, display_name, position, telegram_id, notify_enabled) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (username, generate_password_hash(password), role, display_name,
         position, telegram_id, notify_enabled),
    )
    conn.commit()
    user_id = cur.lastrowid
    conn.close()
    return jsonify({"id": user_id, "message": "Пользователь создан"}), 201


@app.route("/api/users/<int:user_id>", methods=["PUT"])
@admin_required
def update_user(user_id):
    data = request.get_json()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id, ))
    if not cur.fetchone():
        conn.close()
        return jsonify({"error": "Пользователь не найден"}), 404
    updates = []
    params = []
    for field in ("display_name", "position", "role", "telegram_id"):
        if field in data:
            updates.append(f"{field} = ?")
            params.append(data[field])
    if "notify_enabled" in data:
        updates.append("notify_enabled = ?")
        params.append(1 if data["notify_enabled"] else 0)
    if "password" in data and data["password"]:
        updates.append("password_hash = ?")
        params.append(generate_password_hash(data["password"]))
    if "username" in data:
        updates.append("username = ?")
        params.append(data["username"])
    if updates:
        params.append(user_id)
        try:
            cur.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?",
                        params)
        except sqlite3.IntegrityError:
            conn.close()
            return jsonify(
                {"error": "Пользователь с таким логином уже существует"}), 409
    conn.commit()
    conn.close()
    return jsonify({"message": "Пользователь обновлён"})


@app.route("/api/users/<int:user_id>", methods=["DELETE"])
@admin_required
def delete_user(user_id):
    if user_id == session.get("user_id"):
        return jsonify({"error": "Нельзя удалить самого себя"}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id = ?", (user_id, ))
    conn.commit()
    conn.close()
    return jsonify({"message": "Пользователь удалён"})


# ──────────── TELEGRAM API ────────────
# [ЗАКОММЕНТИРОВАНО] Мои записи / клиентские уведомления — отключено
# @app.route("/api/telegram/link-phone", methods=["POST"])
# def telegram_link_phone():
#     data = request.get_json()
#     telegram_id = (data.get("telegram_id") or "").strip()
#     phone = (data.get("phone") or "").strip()
#     client_name = (data.get("client_name") or "").strip()
#     if not telegram_id or not phone:
#         return jsonify({"error": "telegram_id и phone обязательны"}), 400
#     phone_clean = phone.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
#     if not phone_clean.isdigit() or len(phone_clean) < 10:
#         return jsonify({"error": "Неверный формат телефона"}), 400
#     conn = get_db()
#     cur = conn.cursor()
#     cur.execute(
#         "INSERT OR REPLACE INTO telegram_clients (telegram_id, phone, client_name) VALUES (?, ?, ?)",
#         (telegram_id, phone, client_name),
#     )
#     conn.commit()
#     conn.close()
#     return jsonify({"message": "Телефон привязан"}), 200

# @app.route("/api/telegram/linked-phones", methods=["GET"])
# def telegram_linked_phones():
#     """Получить список телефонов, привязанных к telegram_id."""
#     telegram_id = request.args.get("telegram_id", "").strip()
#     if not telegram_id:
#         return jsonify({"error": "telegram_id обязателен"}), 400
#     conn = get_db()
#     cur = conn.cursor()
#     cur.execute("SELECT phone FROM telegram_clients WHERE telegram_id = ?", (telegram_id, ))
#     phones = [r[0] for r in cur.fetchall()]
#     conn.close()
#     return jsonify({"phones": phones}), 200

# def _phone_digits10(phone: str) -> str:
#     """Извлекает последние 10 цифр из телефона для устойчивого сравнения."""
#     digits = re.sub(r"\D", "", phone or "")
#     return digits[-10:] if len(digits) >= 10 else digits

# @app.route("/api/clients/by-phone", methods=["GET"])
# def client_by_phone():
#     """Найти client_id по номеру телефона (устойчиво к формату)."""
#     phone = request.args.get("phone", "").strip()
#     if not phone:
#         return jsonify({"error": "phone обязателен"}), 400
#     target = _phone_digits10(phone)
#     if not target:
#         return jsonify({"error": "Некорректный номер"}), 400
#     conn = get_db()
#     cur = conn.cursor()
#     cur.execute("SELECT id FROM clients WHERE substr(phone, -10) = ?", (target, ))
#     row = cur.fetchone()
#     conn.close()
#     if row:
#         return jsonify({"client_id": row["id"]}), 200
#     return jsonify({"error": "Клиент не найден"}), 404

# @app.route("/api/telegram/my-bookings", methods=["GET"])
# def telegram_my_bookings():
#     telegram_id = request.args.get("telegram_id", "").strip()
#     if not telegram_id:
#         return jsonify({"error": "telegram_id обязателен"}), 400
#     conn = get_db()
#     cur = conn.cursor()
#     cur.execute("SELECT phone FROM telegram_clients WHERE telegram_id = ?", (telegram_id, ))
#     phones = [r[0] for r in cur.fetchall()]
#     if not phones:
#         conn.close()
#         return jsonify([])
#     placeholders = ",".join("?" for _ in phones)
#     cur.execute(
#         f"SELECT * FROM bookings WHERE client_phone IN ({placeholders}) AND status IN ('active', 'pending') ORDER BY booking_date DESC, booking_time DESC",
#         phones,
#     )
#     rows = [convert_booking_dates(dict(r)) for r in cur.fetchall()]
#     conn.close()
#     return jsonify(rows)


@app.route("/api/auth/update-notify", methods=["PUT"])
@login_required
def auth_update_notify():
    data = request.get_json()

    # ✅ Безопасный парсер булевых значений
    def parse_bool(val):
        if isinstance(val, bool): return 1 if val else 0
        if isinstance(val, (int, float)): return 1 if val else 0
        if isinstance(val, str):
            return 1 if val.strip().lower() in ('1', 'true', 'yes',
                                                'on') else 0
        return 0

    telegram_id = (data.get("telegram_id") or "").strip()
    vk_id = (data.get("vk_id") or "").strip()

    # ✅ Используем парсер вместо прямого if/else
    notify_enabled = parse_bool(data.get("notify_enabled"))
    vk_notify_enabled = parse_bool(data.get("vk_notify_enabled"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET telegram_id = ?, vk_id = ?, notify_enabled = ?, vk_notify_enabled = ? WHERE id = ?",
        (telegram_id, vk_id, notify_enabled, vk_notify_enabled,
         session["user_id"]))
    conn.commit()
    conn.close()

    session["telegram_id"] = telegram_id
    session["vk_id"] = vk_id

    return jsonify({"message": "Настройки уведомлений обновлены"}), 200


@app.route("/api/telegram/notify-users", methods=["GET"])
def telegram_notify_users():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, display_name, telegram_id FROM users WHERE notify_enabled = 1 AND telegram_id != '' AND telegram_id IS NOT NULL"
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(rows)


@app.route("/api/vk/notify-users", methods=["GET"])
def vk_notify_users():
    """Список пользователей админки, подписавшихся на VK-уведомления о записях."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, display_name, vk_id FROM users WHERE vk_notify_enabled = 1 AND vk_id != '' AND vk_id IS NOT NULL"
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(rows)


# ──────────── SSE (браузерные уведомления) ────────────
@app.route("/api/events/stream")
@login_required
def sse_event_stream():
    """SSE endpoint: поток событий о новых записях."""

    def event_stream():
        q = queue.Queue()
        with _sse_lock:
            _sse_clients.append(q)
        try:
            # Отправляем keepalive каждые 25 секунд
            while True:
                try:
                    event_type, data = q.get(timeout=25)
                    yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            with _sse_lock:
                if q in _sse_clients:
                    _sse_clients.remove(q)

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ──────────── РАСПИСАНИЕ СОТРУДНИКОВ ────────────
@app.route("/api/employees/schedule", methods=["GET"])
@login_required
def get_employee_schedule():
    date = to_iso_date(request.args.get("date", ""))
    date_from = to_iso_date(request.args.get("date_from", ""))
    date_to = to_iso_date(request.args.get("date_to", ""))
    employee_id = request.args.get("employee_id", "")
    show_future = request.args.get("show_future", "")
    conn = get_db()
    cur = conn.cursor()
    conditions = ["status IN ('active', 'pending')"]
    params = []
    if date:
        conditions.append("booking_date = ?")
        params.append(date)
    elif date_from or date_to:
        if date_from:
            conditions.append("booking_date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("booking_date <= ?")
            params.append(date_to)
    else:
        conditions.append("booking_date >= date('now')")
    if employee_id:
        conditions.append("assigned_employee_id = ?")
        params.append(employee_id)
    where = " AND ".join(conditions)
    cur.execute(
        f"SELECT b.*, u.display_name as emp_name, u.position as emp_position "
        f"FROM bookings b LEFT JOIN users u ON b.assigned_employee_id = u.id "
        f"WHERE {where} ORDER BY booking_date, booking_time",
        params,
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(rows)


@app.route("/api/employees/list", methods=["GET"])
@login_required
def get_employees_list():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, display_name, position FROM users WHERE role IN ('admin','employee') ORDER BY display_name"
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(rows)


# ──────────── КЭШИРОВАНИЕ ────────────
# Простое in-memory кэширование для YClients API
_ycache = {}
_ycache_lock = threading.Lock()
_ycache_key_locks = {}
_ycache_key_locks_lock = threading.Lock()
_YCACHE_TTL = 300  # 5 минут

# Максимум одновременных запросов к YClients при расчёте free-slots.
# Раньше было 10 — на проде (больше услуг/мастеров, чем в тесте) такой
# всплеск параллельных запросов, судя по всему, приводил к мягкому
# rate-limit'у на стороне YClients: без HTTP-ошибки, просто пустой
# ответ. Понизили и развели по времени "раунды" запросов (см.
# _calculate_free_slots) — цена в скорости холодного расчёта, но
# именно холодные расчёты и не должны происходить синхронно на живом
# запросе пользователя (см. фоновый прогрев кэша ниже).
_YC_MAX_WORKERS = 6
_YC_ROUND_DELAY = 0.15  # секунд паузы между раундами запросов


def _get_key_lock(key):
    """Возвращает (создавая при необходимости) отдельный lock для ключа."""
    with _ycache_key_locks_lock:
        if key not in _ycache_key_locks:
            _ycache_key_locks[key] = threading.Lock()
        return _ycache_key_locks[key]


def get_cached(key, fetch_func, ttl=None):
    """Получить данные из кэша или вызвать fetch_func если кэш устарел.

    Использует lock по конкретному ключу: если несколько запросов
    одновременно просят один и тот же ещё не закэшированный ключ
    (например, повторный запрос с фронта после таймаута), выполняется
    только один вызов fetch_func — остальные дожидаются его завершения
    и берут готовый результат из кэша, а не запускают параллельно
    ещё один дорогой опрос YClients.
    """
    if ttl is None:
        ttl = _YCACHE_TTL

    def _read_if_fresh():
        with _ycache_lock:
            if key in _ycache:
                entry = _ycache[key]
                if datetime.now().timestamp() - entry['timestamp'] < ttl:
                    return entry['data'], True
        return None, False

    data, found = _read_if_fresh()
    if found:
        return data

    key_lock = _get_key_lock(key)
    with key_lock:
        # Пока ждали lock, кэш мог наполниться другим потоком — перечитываем
        data, found = _read_if_fresh()
        if found:
            return data

        # Кэш отсутствует или устарел — получаем свежие данные
        data = fetch_func()
        with _ycache_lock:
            _ycache[key] = {
                'data': data,
                'timestamp': datetime.now().timestamp()
            }
        return data


def clear_cache(pattern=None):
    """Очистить кэш полностью или по паттерну."""
    with _ycache_lock:
        if pattern:
            keys_to_delete = [k for k in _ycache.keys() if pattern in k]
            for k in keys_to_delete:
                del _ycache[k]
        else:
            _ycache.clear()


def get_cached_dynamic(key, fetch_func, ttl_success=None, ttl_error=20):
    """Как get_cached, но для случаев, когда сам расчёт может частично
    провалиться (например, YClients прижал rate-лимитом часть параллельных
    запросов при "холодном" кэше).

    fetch_func должна возвращать (data, had_errors). Если had_errors=True,
    результат кэшируется всего на ttl_error секунд, а не на полный TTL —
    иначе неудачный (например, ложно-пустой) ответ "залипал" бы в кэше
    на весь обычный срок, и все посетители до его истечения видели бы
    неверные данные, хотя на самом деле проблема была временной.

    Возвращает (data, had_errors) — в отличие от get_cached, всегда парой,
    чтобы вызывающий код мог распространить признак ошибки выше (например,
    в свой собственный errors-список), а не заглядывать во внутренности
    кэша. had_errors=True приходит и из свежего вычисления, и из уже
    закэшированной "ошибочной" записи (пока не истёк её короткий TTL).

    Хранит собственный TTL и признак ошибки прямо в записи кэша, поэтому
    использует свою пару ключей — с обычным get_cached их путать не нужно.
    """
    if ttl_success is None:
        ttl_success = _YCACHE_TTL

    def _read_if_fresh():
        with _ycache_lock:
            if key in _ycache:
                entry = _ycache[key]
                entry_ttl = entry.get('ttl', ttl_success)
                if datetime.now().timestamp() - entry['timestamp'] < entry_ttl:
                    return entry['data'], entry.get('had_errors', False), True
        return None, False, False

    data, had_errors, found = _read_if_fresh()
    if found:
        return data, had_errors

    key_lock = _get_key_lock(key)
    with key_lock:
        data, had_errors, found = _read_if_fresh()
        if found:
            return data, had_errors

        result, had_errors = fetch_func()
        ttl = ttl_error if had_errors else ttl_success
        if had_errors:
            logger.warning(
                f"get_cached_dynamic: расчёт для '{key}' прошёл с ошибками, "
                f"кэшируем результат всего на {ttl}с вместо {ttl_success}с")
        with _ycache_lock:
            _ycache[key] = {
                'data': result,
                'timestamp': datetime.now().timestamp(),
                'ttl': ttl,
                'had_errors': had_errors,
            }
        return result, had_errors


# ──────────── ПОСЛЕДНИЙ НАДЁЖНЫЙ РЕЗУЛЬТАТ FREE-SLOTS ────────────
# На проде (больше услуг/мастеров, чем в тестовом аккаунте) YClients
# иногда отдаёт под нагрузкой формально успешный (200 OK), но полностью
# пустой ответ — без единой HTTP-ошибки. Обычный error_flag/retry это
# не ловит. Поэтому храним отдельно последний результат, который прошёл
# без признаков сбоя (см. эвристики внутри _calculate_free_slots), и
# если новый расчёт выглядит подозрительно — отдаём пользователю его,
# а не свежую "пустоту", пока не подтвердится, что она настоящая.
_last_good_slots = {}  # date_str -> {'data': [...], 'timestamp': float}
_last_good_slots_lock = threading.Lock()
_LAST_GOOD_MAX_AGE = 6 * 3600  # не подставляем результат старше 6 часов


def _remove_booked_slot_from_cache(date_str, staff_id, time_str):
    """Вызывается сразу после того, как YClients подтвердил создание
    записи (см. create_booking → _send_to_yclients). Вычёркивает именно
    это время у именно этого мастера из уже закэшированного результата
    /api/public/free-slots на эту дату.

    Специально НЕ сбрасываем весь кэш на дату целиком: следующий
    посетитель страницы попал бы на холодный пересчёт со всплеском
    запросов к YClients — то есть вернул бы ровно ту проблему throttling,
    которую и чинили в _calculate_free_slots. Точечная правка кэша даёт
    актуальную картину немедленно, без единого лишнего запроса к API.

    Правим и основной кэш (_ycache), и last-good подстраховку
    (_last_good_slots) — иначе при следующем подозрительном
    (had_errors) расчёте эвристика в _get_free_slots_safe подставит
    старый fallback, где это время всё ещё "свободно"."""
    if not staff_id or not time_str:
        return
    staff_id = str(staff_id)
    cache_key = f"public_free_slots_{date_str}"

    def _strip(staff_list):
        if not staff_list:
            return
        for entry in staff_list:
            if str(entry.get("id")) != staff_id:
                continue
            entry["free_slots"] = [
                s for s in entry.get("free_slots", [])
                if (s.get("time") if isinstance(s, dict) else s) != time_str
            ]

    with _ycache_lock:
        entry = _ycache.get(cache_key)
        if entry:
            _strip(entry.get("data"))

    with _last_good_slots_lock:
        fallback = _last_good_slots.get(date_str)
        if fallback:
            _strip(fallback.get("data"))


def _get_free_slots_safe(date_str, target_date):
    """Считает free-slots на дату с защитой от "тихого" throttling
    YClients: если расчёт помечен как подозрительный (had_errors) —
    подменяем результат последним надёжным, если он не слишком старый,
    вместо показа ложного "всё занято". Возвращает (result, had_errors)
    как и _calculate_free_slots — had_errors=True сохраняется даже при
    подмене, чтобы кэш всё равно взял короткий TTL и попробовал снова
    в следующий раз.
    """
    result, had_errors = _calculate_free_slots(target_date)

    if not had_errors:
        # Надёжный результат (даже если пустой — значит, реально всё
        # занято/выходной) — запоминаем как последний известный хороший.
        with _last_good_slots_lock:
            _last_good_slots[date_str] = {
                'data': result,
                'timestamp': datetime.now().timestamp(),
            }
        return result, False

    # Расчёт подозрительный — пробуем подстраховаться прошлым хорошим
    with _last_good_slots_lock:
        fallback = _last_good_slots.get(date_str)
    if fallback is not None:
        age = datetime.now().timestamp() - fallback['timestamp']
        if age < _LAST_GOOD_MAX_AGE:
            logger.warning(
                f"_get_free_slots_safe: расчёт для {date_str} подозрительный, "
                f"подставляем последний надёжный результат ({int(age)}с назад) "
                f"вместо него")
            return fallback['data'], True

    # Подстраховки нет или она слишком старая — отдаём то, что есть
    logger.warning(
        f"_get_free_slots_safe: расчёт для {date_str} подозрительный, "
        f"надёжной подстраховки нет — отдаём как есть")
    return result, True


# ──────────── ФОНОВЫЙ ПРОГРЕВ КЭША FREE-SLOTS ────────────
# Раньше кэш заполнялся только "по требованию" — первый посетитель дня
# сам вызывал холодный расчёт и получал (или не получал) весь его риск
# на себя. Теперь фоновый поток сам поддерживает кэш тёплым для
# ближайших дней, обновляя его заметно чаще, чем истекает TTL, — так что
# обычные посетители почти всегда просто читают готовый кэш, а не
# запускают синхронный расчёт с всплеском запросов к YClients.
_SLOTS_PREWARM_WINDOW_DAYS = 5
_SLOTS_PREWARM_INTERVAL = 180  # секунд между прогревами


def _prewarm_free_slots():
    today = datetime.now().date()
    for offset in range(_SLOTS_PREWARM_WINDOW_DAYS):
        target_date = today + timedelta(days=offset)
        date_str = target_date.isoformat()
        cache_key = f"public_free_slots_{date_str}"
        try:
            get_cached_dynamic(
                cache_key,
                lambda d=date_str, t=target_date: _get_free_slots_safe(d, t),
                ttl_success=300,
                ttl_error=45)
        except Exception as e:
            logger.error(f"Прогрев free-slots для {date_str} не удался: {e}")
        # Пауза между датами — тот же принцип: не бить по YClients
        # запросами на несколько дней подряд одним всплеском.
        time.sleep(_YC_ROUND_DELAY * 2)


def _run_slots_prewarmer():
    # Небольшая начальная пауза, чтобы не стартовать прогрев одновременно
    # с остальной инициализацией приложения.
    threading.Event().wait(5)
    while True:
        try:
            _prewarm_free_slots()
        except Exception as e:
            logger.error(f"Ошибка фонового прогрева free-slots: {e}")
        threading.Event().wait(_SLOTS_PREWARM_INTERVAL)


threading.Thread(target=_run_slots_prewarmer, daemon=True).start()


# ──────────── СПИСОК УСЛУГ ────────────
@app.route("/api/services", methods=["GET"])
@login_required
def get_services_list():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT service FROM bookings ORDER BY service")
    rows = [r[0] for r in cur.fetchall()]
    cur.execute(
        "SELECT DISTINCT service FROM services_history WHERE service NOT IN (SELECT DISTINCT service FROM bookings)"
    )
    rows.extend(r[0] for r in cur.fetchall() if r[0] not in rows)
    conn.close()
    return jsonify(sorted(set(rows)))


# ──────────── YCLIENTS API ────────────
@app.route("/api/yclients/check", methods=["GET"])
def yclients_check():
    """Check YClients API connection."""
    result = yc.check_connection()
    return jsonify(result)


@app.route("/api/public/services", methods=["GET"])
def get_public_services():
    """Публичный endpoint для сайта — возвращает услуги из YClients."""
    try:
        category_id = request.args.get("category_id")
        cache_key = f'public_services_cat_{category_id}' if category_id else 'public_services_all'
        services = get_cached(cache_key,
                              lambda: yc.get_services(category_id=category_id))

        formatted = [{
            "id":
            svc.get("id"),
            "booking_title":
            svc.get("booking_title", svc.get("title", "Услуга")),
            "title":
            svc.get("title", svc.get("booking_title", "Услуга")),
            "comment":
            svc.get("comment", ""),
            "price_min":
            svc.get("price_min", 0),
            "price_max":
            svc.get("price_max", 0),
            "category_id":
            svc.get("category_id"),
            "duration":
            svc.get("duration"),
        } for svc in (services or [])]

        return jsonify({"success": True, "data": formatted})
    except Exception as e:
        logger.error(f"Ошибка при получении публичных услуг: {e}")
        return jsonify({
            "success": False,
            "error": "Не удалось загрузить услуги",
            "data": []
        }), 500


@app.route("/api/service_categories", methods=["GET"])
def get_service_categories_public():
    """Публичный endpoint для получения категорий услуг.
    Возвращает данные из YClients API для отображения на сайте.
    Использует кэширование для снижения нагрузки на API.
    """
    try:
        categories = get_cached('service_categories',
                                lambda: yc.get_service_categories())
        # Форматируем ответ для фронтенда
        formatted = [{
            "id": cat.get("id"),
            "title": cat.get("title", "Без названия"),
            "category_id": cat.get("category_id")
        } for cat in (categories or [])]
        return jsonify({"success": True, "data": formatted})
    except Exception as e:
        logger.error(f"Ошибка при получении категорий: {e}")
        return jsonify({
            "success": False,
            "error": "Не удалось загрузить категории",
            "data": []
        }), 500


@app.route("/api/yclients/categories", methods=["GET"])
def yclients_categories():
    """Fetch service categories from YClients (admin).
    Кэшируем под тем же ключом, что и /api/service_categories — это один
    и тот же вызов yc.get_service_categories(), не нужно дублировать."""
    categories = get_cached('service_categories',
                            lambda: yc.get_service_categories())
    return jsonify(categories)


@app.route("/api/yclients/services", methods=["GET"])
def yclients_services():
    """Fetch services from YClients (admin). Optional ?category_id= filter.
    Без category_id кэшируем под тем же ключом 'services_list', что и
    расчёт free-slots — раньше это был отдельный живой запрос к YClients
    при каждой загрузке страницы (и не один, а сразу из двух разных мест
    на фронте), конкурирующий за лимит запросов с расчётом на "сегодня"."""
    category_id = request.args.get("category_id")
    if category_id:
        services = yc.get_services(category_id=category_id)
    else:
        services = get_cached('services_list', lambda: yc.get_services())
    return jsonify(services)


@app.route("/api/yclients/staff", methods=["GET"])
def yclients_staff():
    """Fetch staff (employees) from YClients.
    Optional ?service_id= — when given, returns only staff assigned to that
    specific service (uses /book_staff/{company_id}?service_ids[]=...),
    same as YClients' own booking widget uses to filter masters per service.
    """
    service_id = request.args.get("service_id")
    staff = yc.get_staff_for_booking(service_id=service_id)
    return jsonify(staff)


@app.route("/api/yclients/available-times", methods=["GET"])
def yclients_available_times():
    """Fetch available times from YClients.
    Required: ?service_id=XXX &staff_id=XXX &date=DD.MM.YYYY or YYYY-MM-DD
    Uses /book_times/{company_id}/{staff_id}/{date} endpoint.
    """
    service_id = request.args.get("service_id")
    staff_id = request.args.get("staff_id")
    date = to_iso_date(request.args.get("date", ""))
    if not service_id or not staff_id or not date:
        return jsonify({"error": "service_id, staff_id, date required"}), 400
    times = yc.get_available_times(service_id, staff_id, date)
    return jsonify(times)


@app.route("/api/yclients/book-times", methods=["GET"])
def yclients_book_times():
    """Fetch book times from YClients.
    Required: ?staff_id=XXX &date=DD.MM.YYYY or YYYY-MM-DD &service_id=XXX
    """
    staff_id = request.args.get("staff_id")
    date = to_iso_date(request.args.get("date", ""))
    service_id = request.args.get("service_id")
    if not staff_id or not date:
        return jsonify({"error": "staff_id, date required"}), 400
    times = yc.get_available_times(service_id, staff_id, date)
    return jsonify(times)


@app.route("/api/yclients/available-dates", methods=["GET"])
def yclients_available_dates():
    """Fetch available dates from YClients.
    Required: ?service_id=XXX &staff_id=XXX
    Optional:  &month=8 &year=2026
    """
    service_id = request.args.get("service_id")
    staff_id = request.args.get("staff_id")
    month = request.args.get("month")
    year = request.args.get("year")
    if not service_id or not staff_id:
        return jsonify({"error": "service_id, staff_id required"}), 400
    dates = yc.get_available_dates(
        service_id,
        staff_id,
        month=int(month) if month else None,
        year=int(year) if year else None,
    )
    return jsonify(dates)


# ──────────── УВЕДОМЛЕНИЯ (API для привязки) ────────────
@app.route("/api/notifications/link-token", methods=["POST"])
def create_notification_link_token():
    """Создать одноразовый токен для перехода сайт→бот и вернуть диплинк."""
    data = request.get_json() or {}
    client_id = data.get("client_id")
    provider = data.get("provider")
    if not client_id or provider not in PROVIDERS:
        return jsonify(
            {"error": "client_id и provider (telegram/max) обязательны"}), 400
    conn = get_db()
    try:
        token = create_token(conn, client_id=int(client_id), provider=provider)
    finally:
        conn.close()
    return jsonify({"deeplink": build_deeplink(provider, token)}), 200


@app.route("/api/notifications/status", methods=["GET"])
def notifications_status():
    """Проверить, привязан ли уже провайдер для данного client_id."""
    client_id = request.args.get("client_id")
    provider = request.args.get("provider")
    if not client_id or provider not in PROVIDERS:
        return jsonify({"error": "client_id и provider обязательны"}), 400
    conn = get_db()
    try:
        linked = is_linked(conn, client_id=int(client_id), provider=provider)
    finally:
        conn.close()
    return jsonify({"linked": linked}), 200


@app.route("/api/notifications/redeem-token", methods=["POST"])
def notifications_redeem_token():
    """Погасить одноразовый токен (переход сайт→бот) и привязать провайдера."""
    data = request.get_json() or {}
    token = data.get("token")
    provider = data.get("provider")
    provider_user_id = data.get("provider_user_id")
    if not token or provider not in PROVIDERS or not provider_user_id:
        return jsonify(
            {"error": "token, provider, provider_user_id обязательны"}), 400
    conn = get_db()
    try:
        client_id, err = redeem_token(
            conn,
            token=token,
            provider=provider,
            provider_user_id=str(provider_user_id),
            provider_username=data.get("provider_username"))
    finally:
        conn.close()
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"client_id": client_id}), 200


@app.route("/api/notifications/link-direct", methods=["POST"])
def notifications_link_direct():
    """Привязать провайдера к client_id напрямую (без токена) — только для ботов."""
    data = request.get_json(silent=True) or {}
    client_id = data.get("client_id")
    provider = data.get("provider")
    provider_user_id = data.get("provider_user_id")
    if not client_id or provider not in PROVIDERS or not provider_user_id:
        return jsonify(
            {"error":
             "client_id, provider, provider_user_id обязательны"}), 400
    conn = get_db()
    try:
        # Пробуем привязать
        link_directly(conn,
                      client_id=int(client_id),
                      provider=provider,
                      provider_user_id=str(provider_user_id),
                      provider_username=data.get("provider_username"))
        conn.commit()
        return jsonify({"message": "Привязано", "linked": True}), 200
    except Exception as e:
        # Если произошла ошибка (например, дубликат), проверяем статус
        linked = is_linked(conn, client_id=int(client_id), provider=provider)
        if linked:
            # Если уже привязано — считаем это успехом
            return jsonify({"message": "Уже привязано", "linked": True}), 200
        else:
            logger.error(f"Ошибка при прямой привязке уведомлений: {e}")
            return jsonify({
                "error": "Не удалось подключить уведомления",
                "details": str(e)
            }), 500
    finally:
        conn.close()


@app.route("/api/notifications/unlink-direct", methods=["POST"])
def notifications_unlink_direct():
    """Отвязать провайдера от client_id напрямую (для кнопки 'Отписаться' в боте)."""
    data = request.get_json(silent=True) or {}
    client_id = data.get("client_id")
    provider = data.get("provider")

    if not client_id or provider not in PROVIDERS:
        return jsonify({"error": "client_id и provider обязательны"}), 400

    conn = get_db()
    try:
        cur = conn.cursor()
        # Удаляем запись о привязке
        cur.execute(
            "DELETE FROM notification_links WHERE client_id = ? AND provider = ?",
            (int(client_id), provider))
        conn.commit()

        # Возвращаем понятный ответ для бота
        if cur.rowcount > 0:
            return jsonify({
                "message": "Уведомления отключены",
                "linked": False
            }), 200
        else:
            # Даже если записи не было, считаем это успешным состоянием "не привязан"
            return jsonify({
                "message": "Подписка не найдена",
                "linked": False
            }), 200

    except Exception as e:
        logger.error(f"Ошибка при отвязке уведомлений: {e}")
        return jsonify({"error": "Не удалось отключить уведомления"}), 500
    finally:
        conn.close()


# ──────────── CAREER ────────────
@app.route("/api/career/submit", methods=["POST"])
def career_submit():
    """Публичная отправка заявки на трудоустройство (с сайта или из ТГ бота)."""
    data = request.get_json() or {}
    client_name = (data.get("client_name") or "").strip()
    client_phone = (data.get("client_phone") or "").strip()
    experience = (data.get("experience") or "").strip()

    # ✅ Валидация имени: только буквы, минимум 2 символа
    if len(client_name) < 2 or not re.match(r'^[a-zA-Zа-яА-ЯёЁ\s\-]+$',
                                            client_name):
        return jsonify(
            {"error":
             "Имя должно содержать только буквы (минимум 2 символа)"}), 400

    # ✅ Валидация телефона: минимум 10 цифр
    phone_clean = re.sub(r'\D', '', client_phone)
    if len(phone_clean) < 10:
        return jsonify(
            {"error":
             "Введите корректный номер телефона (минимум 10 цифр)"}), 400

    if not client_name or not client_phone or not experience:
        return jsonify({"error": "Имя, телефон и опыт обязательны"}), 400
    resume = (data.get("resume") or "").strip()
    cover_letter = (data.get("cover_letter") or "").strip()
    source = (data.get("source") or "site").strip()
    telegram_id = (data.get("telegram_id") or "").strip()

    # ✅ Если есть telegram_id, но source не указан или "site" — это отклик из Telegram
    if telegram_id and source == "site":
        source = "tg"

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO career_applications (client_name, client_phone, experience, resume, cover_letter, source, telegram_id)
VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (client_name, client_phone, experience, resume, cover_letter, source,
         telegram_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"message": "Заявка принята"}), 201


@app.route("/api/career/applications", methods=["GET"])
@login_required
def career_applications():
    """Получить список заявок на трудоустройство (только для авторизованных)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM career_applications ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(rows)


# ──────────── СТРАНИЦЫ ────────────
SITE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@app.route("/")
@app.route("/index.html")
def site_index():
    index_path = os.path.join(SITE_ROOT, "index.html")
    if os.path.exists(index_path):
        return send_from_directory(SITE_ROOT, "index.html")
    return jsonify({"error": "index.html не найден"}), 404


@app.route("/admin")
def admin_page():
    if "user_id" not in session:
        return redirect("/admin/login")
    admin_html = os.path.join(app.template_folder, "admin.html")
    if os.path.exists(admin_html):
        return send_from_directory(app.template_folder, "admin.html")
    return jsonify({"error": "admin.html не найден"}), 404


@app.route("/admin/login")
def admin_login_page():
    if "user_id" in session:
        return redirect("/admin")
    login_html = os.path.join(app.template_folder, "login.html")
    if os.path.exists(login_html):
        return send_from_directory(app.template_folder, "login.html")
    return jsonify({"error": "login.html не найден"}), 404


@app.errorhandler(401)
def unauthorized(e):
    if request.path.startswith('/api/'):
        return jsonify({"error": "Не авторизован"}), 401
    return redirect("/admin/login")


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/admin'):
        return send_from_directory(app.template_folder, "login.html")
    return jsonify({"error": "Страница не найдена"}), 404


ADMIN_STATIC_DIR = os.path.join(BASE_DIR, "static")


@app.route("/admin/<path:filename>")
def admin_static(filename):
    return send_from_directory(ADMIN_STATIC_DIR, filename)


SITE_STATIC_DIRS = [
    SITE_ROOT,
]
_BLOCKED_STATIC_NAMES = {
    "beauty.db", "app.py", "wsgi.py", "cookies.txt", ".env"
}
_BLOCKED_STATIC_EXTS = {".db", ".py", ".pyc", ".env"}


@app.route("/<path:filename>")
def serve_site_static(filename):
    if filename.startswith("admin/") or filename.startswith("api/"):
        return jsonify({"error": "Файл не найден"}), 404
    base_name = os.path.basename(filename)
    _, ext = os.path.splitext(base_name)
    if base_name in _BLOCKED_STATIC_NAMES or ext.lower(
    ) in _BLOCKED_STATIC_EXTS:
        return jsonify({"error": "Файл не найден"}), 404
    for directory in SITE_STATIC_DIRS:
        file_path = os.path.join(directory, filename)
        if os.path.exists(file_path) and not os.path.isdir(file_path):
            return send_from_directory(directory, filename)
    return jsonify({"error": "Файл не найден"}), 404


# ──────────── ЦЕНТР УПРАВЛЕНИЯ ДАННЫМИ ────────────


@app.route("/api/data/clients", methods=["GET"])
@admin_required
def get_all_clients():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT c.id, c.display_name, c.phone, c.created_at,
               GROUP_CONCAT(tc.telegram_id, ', ') as tg_ids
        FROM clients c
        LEFT JOIN telegram_clients tc ON c.phone = tc.phone
        GROUP BY c.id
        ORDER BY c.created_at DESC
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(rows)


@app.route("/api/data/clients/<int:client_id>", methods=["DELETE"])
@admin_required
def delete_client(client_id):
    """Удалить клиента."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM clients WHERE id = ?", (client_id, ))
    conn.commit()
    conn.close()
    return jsonify({"message": "Клиент удален"})


@app.route("/api/data/logs/notifications", methods=["GET"])
@admin_required
def get_notification_logs():
    """Посмотреть логи отправленных уведомлений (дедупликация)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT nl.id, nl.booking_id, nl.channel, nl.created_at,
        b.client_name, b.service
        FROM notification_log nl
        LEFT JOIN bookings b ON nl.booking_id = b.id
        ORDER BY nl.created_at DESC LIMIT 100
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(rows)


# ═══════════════════════════════════════════════════════════════
# УДАЛЕНИЕ ЛОГА УВЕДОМЛЕНИЯ
# ══════════════════════════════════════════════════════════════
@app.route("/api/data/logs/notifications/<int:log_id>", methods=["DELETE"])
@admin_required
def delete_notification_log(log_id):
    """Удалить одну запись из лога уведомлений."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM notification_log WHERE id = ?", (log_id, ))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    if deleted == 0:
        return jsonify({"error": "Лог не найден"}), 404
    return jsonify({"message": "Лог удалён"}), 200


@app.route("/api/data/logs/notifications", methods=["DELETE"])
@admin_required
def clear_notification_logs():
    """Очистить все логи уведомлений (опционально — кнопка «Очистить всё»)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM notification_log")
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return jsonify({"message": f"Удалено записей: {deleted}"}), 200


@app.route("/api/data/export/<table_type>", methods=["GET"])
@admin_required
def export_data(table_type):
    """Экспорт данных в CSV (для открытия в Excel)."""
    import csv
    import io

    conn = get_db()
    cur = conn.cursor()

    if table_type == "clients":
        cur.execute("SELECT id, display_name, phone, created_at FROM clients")
        headers = ["ID", "Имя", "Телефон", "Дата создания"]
    elif table_type == "bookings":
        cur.execute(
            "SELECT id, client_name, client_phone, service, booking_date, booking_time, status, assigned_employee_name FROM bookings"
        )
        headers = [
            "ID", "Клиент", "Телефон", "Услуга", "Дата", "Время", "Статус",
            "Мастер"
        ]
    elif table_type == "career":
        cur.execute(
            "SELECT id, client_name, client_phone, experience, source, created_at FROM career_applications"
        )
        headers = ["ID", "Имя", "Телефон", "Опыт", "Источник", "Дата"]
    else:
        conn.close()
        return jsonify({"error": "Неизвестный тип"}), 400

    rows = cur.fetchall()
    conn.close()

    # Генерируем CSV
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(headers)
    cw.writerows(rows)

    output = si.getvalue()
    # Добавляем BOM для корректного отображения кириллицы в Excel
    output = "\ufeff" + output

    return Response(output,
                    mimetype="text/csv",
                    headers={
                        "Content-Disposition":
                        f"attachment;filename={table_type}_export.csv"
                    })


@app.get("/api/admin/bots/status")
def bots_status():

    services = ["verbena-bot.service", "beautyverbena-vk.service"]

    result = {}

    for service in services:

        try:
            output = subprocess.check_output(
                ["systemctl", "is-active", service],
                stderr=subprocess.STDOUT).decode().strip()

        except FileNotFoundError:
            # Windows локально
            output = "local"

        except subprocess.CalledProcessError:
            # Linux, сервис выключен
            output = "inactive"

        except Exception as e:
            output = f"error: {e}"

        result[service] = output

    return jsonify(result)


# ──────────── ПОДПИСКИ И УДАЛЕНИЕ ОТКЛИКОВ ────────────


@app.route("/api/data/subscriptions", methods=["GET"])
@admin_required
def get_subscriptions():
    """Получить список пользователей с активными подписками на уведомления."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, display_name, username, telegram_id, notify_enabled, vk_id, vk_notify_enabled
        FROM users
        WHERE (telegram_id != '' AND notify_enabled = 1) OR (vk_id != '' AND vk_notify_enabled = 1)
        ORDER BY display_name
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(rows)


@app.route("/api/data/subscriptions/<int:user_id>/<channel>",
           methods=["DELETE"])
@admin_required
def delete_subscription(user_id, channel):
    """Отвязать ID и выключить уведомления для конкретного канала (tg или vk)."""
    conn = get_db()
    cur = conn.cursor()
    if channel == 'tg':
        cur.execute(
            "UPDATE users SET telegram_id = '', notify_enabled = 0 WHERE id = ?",
            (user_id, ))
    elif channel == 'vk':
        cur.execute(
            "UPDATE users SET vk_id = '', vk_notify_enabled = 0 WHERE id = ?",
            (user_id, ))
    else:
        conn.close()
        return jsonify({"error": "Неизвестный канал"}), 400
    conn.commit()
    conn.close()
    return jsonify({"message": "Подписка удалена"})


@app.route("/api/career/applications/<int:app_id>", methods=["DELETE"])
@admin_required
def delete_career_application(app_id):
    """Удалить отклик на вакансию."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM career_applications WHERE id = ?", (app_id, ))
    conn.commit()
    conn.close()
    return jsonify({"message": "Отклик удален"})


# ─── ПУБЛИЧНЫЙ ГРАФИК (СВОБОДНЫЕ ОКНА) ────────────


# ─── ПУБЛИЧНЫЙ ГРАФИК (СВОБОДНЫЕ ОКНА) ────────────
def _slots_to_intervals(slots):
    """
    Преобразует список времён ['10:00', '10:15', '10:30', '12:00']
    в интервалы [{'from': '10:00', 'to': '10:45'}, {'from': '12:00', 'to': '12:15'}]
    """
    if not slots:
        return []

    intervals = []
    current_start = slots[0]
    prev_time = slots[0]

    for i in range(1, len(slots)):
        curr_time = slots[i]
        prev_h, prev_m = map(int, prev_time.split(":"))
        curr_h, curr_m = map(int, curr_time.split(":"))
        prev_total = prev_h * 60 + prev_m
        curr_total = curr_h * 60 + curr_m

        if curr_total - prev_total <= 15:
            prev_time = curr_time
        else:
            end_h, end_m = map(int, prev_time.split(":"))
            end_total = end_h * 60 + end_m + 15
            end_time = f"{end_total // 60:02d}:{end_total % 60:02d}"
            intervals.append({"from": current_start, "to": end_time})
            current_start = curr_time
            prev_time = curr_time

    end_h, end_m = map(int, prev_time.split(":"))
    end_total = end_h * 60 + end_m + 15
    end_time = f"{end_total // 60:02d}:{end_total % 60:02d}"
    intervals.append({"from": current_start, "to": end_time})

    return intervals


def _calculate_free_slots(target_date):
    """
    Рассчитывает свободные слоты для всех мастеров на указанную дату.

    Возвращает (result, had_errors). had_errors=True означает, что хотя
    бы один из запросов к YClients не удался даже после ретраев — то есть
    пустой или неполный result может не отражать реальную картину, и
    кэшировать его как "точно всё занято" на обычный TTL не стоит
    (см. get_cached_dynamic).

    ИСТОРИЯ ИЗМЕНЕНИЙ (важно, чтобы не откатить обратно на старую схему):
    Раньше здесь были ТРИ раунда запросов к виджетным ручкам YClients
    (book_staff → book_dates → book_times), причём раунды 2 и 3 шли по
    ОТДЕЛЬНОМУ запросу на каждую пару (услуга, мастер) — при 10 услугах
    и 3-5 мастерах на услугу это 40-60+ запросов на расчёт ОДНОЙ даты.
    YClients документирует жёсткий лимит 3-5 запросов/сек на IP, и при
    таком всплеске он не всегда отвечает HTTP-ошибкой — вместо этого
    "тихо" отдаёт формально валидные (200 OK), но пустые ответы (мягкий
    throttling). Обычный error_flag/retry по статус-коду это не ловит,
    отсюда и ложные "нет свободных окон" на дату, при том что соседние
    (уже закэшированные) даты в порядке.

    Теперь вместо book_dates/book_times по каждой паре (услуга, мастер)
    используется GET /book_times/{company_id}/{staff_id}/{date} БЕЗ
    фильтра по услуге (service_ids[] необязателен) — один запрос на
    мастера вместо запроса на каждую пару. Это та же ручка, что и форма
    записи (см. /api/yclients/available-times), поэтому времена приходят
    уже корректно квантованными по шагу записи мастера — в отличие от
    сырой 5-минутной занятости, отдаваемой /timetable/seances, где не
    каждый "свободный" тик на самом деле является допустимым стартом
    записи (см. настройку "доступное время для онлайн-записи" в
    YClients). Список бронируемых мастеров (раньше — раунд с book_staff
    по каждой услуге отдельно) тоже получаем ОДНИМ запросом со всеми
    service_ids сразу и кэшируем отдельно от конкретной даты, т.к. он от
    даты не зависит и раньше пересчитывался заново на каждую из 5
    прогреваемых дат.
    """
    errors = []  # общий флаг ошибок на весь расчёт; list — чтобы можно
    # было передавать как error_flag в функции yclients_api и просто
    # append'ить из разных потоков (list.append атомарен под GIL)

    _t_start = time.time()

    # 1. Получаем ПОЛНЫЙ каталог услуг (GET /company/{id}/services/, та же
    # ручка, что и обычный "услуги" в CRM) — а НЕ мастеров через book_staff.
    # --- НАЧАЛО ИЗМЕНЕНИЯ (v2) ---
    # Раньше здесь получали bookable-услуги (book_services) и передавали их
    # id одним запросом в book_staff — это должно было устранить 422 (см.
    # историю ниже), но на практике book_staff ведёт себя непредсказуемо
    # даже с отфильтрованными id: на некоторых аккаунтах всё ещё 422 на
    # весь список сразу, а по отдельному СКРЫТОМУ id — наоборот, тихо
    # игнорирует фильтр и отдаёт ВСЕХ мастеров компании, как будто
    # service_ids[] не передан вовсе (т.е. книга book_staff в принципе не
    # надёжна как источник списка мастеров).
    #
    # Вместо этого мастеров берём напрямую из ответа /services/: у каждой
    # услуги там уже есть встроенный список "staff": [...]. Никакой
    # отдельной валидации id здесь нет — это просто разбор уже пришедшего
    # JSON, 422 здесь неоткуда взяться. Учитываем только услуги с
    # active == 1 (реальный признак доступности услуги в YClients), берём
    # уникальных мастеров по всем таким услугам (см. yc.extract_active_staff).
    #
    # СТАРАЯ ИСТОРИЯ (сохранено для контекста): раньше здесь был
    # get_services() без bookable-фильтра, и передача его id в book_staff
    # приводила к HTTP 422 "Unprocessable Content" — он валидирует ВЕСЬ
    # переданный service_ids[] и отклоняет целиком запрос при наличии
    # среди них хотя бы одного непригодного id, без указания, какой именно
    # (см. историю бага, 28 услуг в каталоге → 422). Промежуточный фикс —
    # переход на book_services (bookable-подмножество) — не полностью решил
    # проблему (см. выше), поэтому book_staff здесь больше не используется.
    # --- КОНЕЦ ИЗМЕНЕНИЯ (v2) ---
    def _fetch_services_for_slots():
        local_err = []
        data = yc.get_services(error_flag=local_err)
        return data, bool(local_err)

    try:
        all_services, services_had_err = get_cached_dynamic(
            'services_list_for_slots',
            _fetch_services_for_slots,
            ttl_success=600,
            ttl_error=45)
        if services_had_err:
            errors.append(True)
    except Exception as e:
        logger.error(f"Failed to get services from YClients: {e}")
        return [], True

    if not all_services:
        return [], bool(errors)

    active_staff = yc.extract_active_staff(all_services, active_only=True)

    # 2. Мастера, доступные хоть по одной активной услуге — уже посчитаны
    # выше из services без единого обращения к book_staff.
    booking_staff, staff_had_err = active_staff, False
    staff_map = {}  # staff_id -> {"name": ..., "slots": set()}
    for staff in booking_staff or []:
        staff_id = str(staff.get("id", ""))
        if staff_id and staff_id not in staff_map:
            staff_map[staff_id] = {
                "name": staff.get("name", "Мастер"),
                "slots": set(),
            }

    active_services_count = sum(1 for s in all_services
                                if s.get("active") == 1)
    logger.info(
        f"_calculate_free_slots({target_date}): подготовка ({active_services_count} "
        f"активных услуг → {len(staff_map)} мастеров) заняла "
        f"{time.time() - _t_start:.1f}с")

    if not staff_map:
        return [], bool(errors)

    # 3. Свободные времена каждого мастера на target_date — ОДИН запрос
    # на мастера через book_times БЕЗ фильтра по услуге (та же ручка, что
    # использует форма записи — см. /api/yclients/available-times). Не
    # нужна ни комбинаторика по услугам, ни отдельный раунд "доступные
    # даты в месяце": book_times сам возвращает пусто, если у мастера в
    # этот день нет графика/окон.
    def fetch_times(staff_id):
        local_err = []
        try:
            slots = yc.get_available_times(None,
                                           staff_id,
                                           target_date.isoformat(),
                                           error_flag=local_err)
        except Exception as e:
            logger.warning(
                f"Failed to get available times for staff {staff_id}: {e}")
            local_err.append(True)
            slots = []
        return staff_id, slots, bool(local_err)

    with ThreadPoolExecutor(max_workers=_YC_MAX_WORKERS) as executor:
        for staff_id, slots, had_err in executor.map(fetch_times,
                                                     staff_map.keys()):
            if had_err:
                errors.append(True)
                continue
            for item in slots or []:
                if isinstance(item, str):
                    staff_map[staff_id]["slots"].add(item)
                elif isinstance(item, dict) and item.get("available", True):
                    t = item.get("time")
                    if t:
                        staff_map[staff_id]["slots"].add(t)

    if staff_map and not errors and not any(data["slots"]
                                            for data in staff_map.values()):
        # Подозрительный сигнал БЕЗ единой HTTP-ошибки: у нас есть
        # бронируемые мастера, но ни у одного из них ни одного свободного
        # слота за весь день. Разово у одного мастера — нормально
        # (выходной), но одновременно у ВСЕХ мастеров салона — тот же
        # паттерн "мягкого" throttling, что был и в старой схеме.
        logger.warning(
            f"_calculate_free_slots: ни один из {len(staff_map)} мастеров "
            f"не показал ни одного свободного слота на {target_date} — "
            f"похоже на мягкий throttling YClients, а не на реальное "
            f"отсутствие доступности. Помечаем расчёт как подозрительный.")
        errors.append(True)

    # 4. Формируем результат — каждый реальный слот из YClients как есть.
    result = []
    for staff_id, data in staff_map.items():
        slots = sorted(data["slots"])
        if slots:
            result.append({
                "id": staff_id,
                "name": data["name"],
                "free_slots": [{
                    "time": t
                } for t in slots]
            })

    logger.info(
        f"_calculate_free_slots({target_date}): итого весь расчёт занял "
        f"{time.time() - _t_start:.1f}с, had_errors={bool(errors)}, "
        f"мастеров с окнами={len(result)}/{len(staff_map)}")

    return result, bool(errors)


@app.route("/schedule")
def public_schedule_page():
    """Публичная страница графика работы и свободных слотов."""
    schedule_html = os.path.join(app.template_folder, "schedule.html")
    if os.path.exists(schedule_html):
        return send_from_directory(app.template_folder, "schedule.html")
    return jsonify({"error": "schedule.html не найден"}), 404


@app.route("/api/public/free-slots", methods=["GET"])
def public_free_slots():
    """
    Публичный API. Возвращает ТОЛЬКО свободные окна мастеров.
    Использует РЕАЛЬНЫЕ данные из YClients (как форма записи).
    Кэширует результат на 5 минут.
    """
    date_str = request.args.get("date", datetime.now().date().isoformat())
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

    # Кэшируем на 5 минут для снижения нагрузки на YClients API.
    # _get_free_slots_safe уже прогрет фоновым потоком для ближайших
    # дней (см. _run_slots_prewarmer) — обычно этот вызов просто читает
    # готовый кэш. Если расчёт всё же подозрительный (см. эвристики и
    # error_flag внутри _calculate_free_slots) — подставляется последний
    # надёжный результат, а кэш всё равно берёт короткий TTL (45с), чтобы
    # скоро попробовать снова, а не залипнуть на все 5 минут.
    cache_key = f"public_free_slots_{date_str}"
    cached, had_errors = get_cached_dynamic(
        cache_key,
        lambda: _get_free_slots_safe(date_str, target_date),
        ttl_success=300,
        ttl_error=45)

    return jsonify({"staff": cached, "date": target_date.isoformat()})


if __name__ == "__main__":
    # Инициализируем БД (здесь функция уже точно определена)
    init_db()

    debug_mode = os.environ.get("FLASK_DEBUG") == "1"
    app.run(host="0.0.0.0", port=5000, debug=debug_mode, threaded=True)

# @app.route("/api/telegram/my-bookings-yc", methods=["GET"])
# def telegram_my_bookings_yc():
#     """Get user's active bookings checking status via YClients."""
#     telegram_id = request.args.get("telegram_id", "").strip()
#     if not telegram_id:
#         return jsonify({"error": "telegram_id required"}), 400
#
#     conn = get_db()
#     cur = conn.cursor()
#
#     # 1. Находим телефоны клиента
#     cur.execute("SELECT phone FROM telegram_clients WHERE telegram_id = ?",
#                 (telegram_id, ))
#     phones = [r[0] for r in cur.fetchall()]
#
#     if not phones:
#         conn.close()
#         return jsonify([])
#
#     # 2. Ищем ВСЕ активные записи (не только те, где есть хеш)
#     placeholders = ",".join("?" for _ in phones)
#     cur.execute(
#         f"""SELECT id, client_name, service, booking_date, booking_time,
#                    yclients_record_id, yclients_record_hash, status
#             FROM bookings
#             WHERE client_phone IN ({placeholders})
#             AND status IN ('active', 'pending')
#             ORDER BY booking_date DESC, booking_time DESC""", phones)
#     local_bookings = [dict(r) for r in cur.fetchall()]
#     conn.close()
#
#     active_bookings = []
#
#     for booking in local_bookings:
#         rec_id = booking.get('yclients_record_id')
#         rec_hash = booking.get('yclients_record_hash')
#
#         # Если есть и ID, и Хеш — проверяем в YC
#         if rec_id and rec_hash:
#             try:
#                 url = f"{yc.YCLIENTS_API_BASE}/user/records/{rec_id}/{rec_hash}"
#                 resp = requests.get(url, headers=yc._headers(), timeout=5)
#                 if resp.status_code == 200:
#                     yc_data = resp.json().get("data")
#                     if yc_data and not yc_data.get(
#                             'deleted', False) and yc_data.get('status') in [
#                                 1, 2
#                             ]:
#                         booking['booking_date'] = from_iso_date(
#                             booking['booking_date'])
#                         active_bookings.append(booking)
#                 continue
#             except Exception as e:
#                 logger.error(f"YC check failed for {rec_id}: {e}")
#
#         # ⚡ Fallback
#         booking['booking_date'] = from_iso_date(booking['booking_date'])
#         booking['status_pending_sync'] = True
#         active_bookings.append(booking)
#
#     return jsonify(active_bookings)