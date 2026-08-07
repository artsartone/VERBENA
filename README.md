# 🌸 VERBENA

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Flask-3.0-green?logo=flask&logoColor=white" alt="Flask">
  <img src="https://img.shields.io/badge/JavaScript-Vanilla-yellow?logo=javascript&logoColor=black" alt="JavaScript">
  <img src="https://img.shields.io/badge/Status-Active-success" alt="Status">
  <img src="https://img.shields.io/badge/License-Personal-blueviolet" alt="License">
  <img src="https://img.shields.io/github/last-commit/artsartone/VERBENA" alt="Last Commit">
</p>

<p align="center">
  <em>Цифровая экосистема салона красоты: сайт, API и мультиплатформенные боты</em>
</p>

---

> ⚠️ **Дисклеймер**
> 
> Это **некоммерческий pet-проект**, созданный на безвозмездной основе для оттачивания навыков full-stack разработки. Проект внедрён в реальный салон красоты **Verbena** и на сегодняшний день находится в продакшене. Разработку, поддержку и администрирование веду в единственном лице.

---

## 📑 Содержание

- [📖 О проекте](#-о-проекте)
- [✨ Возможности](#-возможности)
- [🛠 Стек технологий](#-стек-технологий)
- [📁 Структура проекта](#-структура-проекта)
- [🚀 Локальная разработка](#-локальная-разработка)
- [🔐 Переменные окружения](#-переменные-окружения)
- [📦 Деплой в продакшен](#-деплой-в-продакшен)
- [🔄 Roadmap](#-roadmap)
- [👤 Автор](#-автор)

---

## 📖 О проекте

**VERBENA** — это комплексное веб-решение для автоматизации клиентского сервиса современного салона красоты. Проект объединяет в себе:

- 🌐 **Сайт-визитку** с адаптивной вёрсткой и формами заявок
- ⚙️ **Backend на Flask** с REST API и базой данных
- 🤖 **Экосистему ботов** для Telegram, ВКонтакте и MAX
- 📊 **Интеграцию с YCLIENTS** — популярной CRM для салонов красоты

### 🎯 Цели проекта

- Отработать архитектуру full-stack приложения (Python + Vanilla JS)
- Научиться работать с REST API сторонних CRM-систем
- Получить опыт деплоя и администрирования production-окружения
- Реализовать полезный инструмент для реального бизнеса

---

## ✨ Возможности

### 🌐 Веб-сайт

- Адаптивная верстка с использованием Google Fonts (`Cormorant Garamond`, `Poppins`)
- Модальные окна, toast-уведомления, слайдеры
- Валидируемые формы записи на услуги и отклика на вакансии
- SEO-оптимизация (Schema.org микроразметка)
- Асинхронные запросы к API через `fetch`

### ⚙️ Backend & API

- REST API для обработки клиентских и HR-заявок
- Работа с локальной базой данных (SQLite)
- Система уведомлений администраторов о новых записях.
- WSGI-совместимая точка входа (`wsgi.py`)

### 🤖 Мультиплатформенные боты

| Платформа | Статус | Описание |
|-----------|--------|----------|
| **Telegram** | ✅ Active | Канал коммуникации и онлайн-записи |
| **ВКонтакте** | ✅ Active | Интеграция с сообществом салона |
| **MAX** | ❌ В проработке | Бот для мессенджера MAX |

### 📊 Интеграции

- Полная синхронизация с **YCLIENTS** (расписание, клиенты, услуги)
- Работа с Partner API и User Token

---

## 🛠 Стек технологий

| Слой | Технологии |
|------|------------|
| **Frontend** | HTML5, CSS3, Vanilla JavaScript |
| **Backend** | Python 3, Flask |
| **База данных** | SQLite |
| **WSGI-сервер** | Gunicorn |
| **Веб-сервер** | Nginx (reverse proxy) |
| **ОС** | Linux (Ubuntu/Debian) |
| **API** | YCLIENTS Partner API |

---

## 📁 Структура проекта

```
VERBENA/
├── index.html              # Главная страница
├── assets/                 # Статические ресурсы
├── css/                    # Стили
├── js/                     # Клиентская логика (модальные окна, тосты, формы)
├── img/                    # Изображения
│
├── backend/                # Серверная логика Flask
│   ├── notifications/      # Система уведомлений
│   └── requirements.txt
├── wsgi.py                 # Точка входа для Gunicorn
│
├── telegrambot/            # Telegram-бот
├── vkbot/                  # VK-бот
├── maxbot/                 # MAX-бот
│
├── deploy.sh               # Скрипт автоматического деплоя
├── local_requirements.txt
└── .gitignore
```

---

## 🚀 Локальная разработка

```bash
# 1. Клонируем репозиторий
git clone https://github.com/artsartone/VERBENA.git
cd VERBENA

# 2. Создаём виртуальное окружение
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows

# 3. Устанавливаем зависимости
pip install -r local_requirements.txt

# 4. Настраиваем переменные окружения (см. раздел ниже)

# 5. Запускаем локальный сервер
python wsgi.py
```

Сайт будет доступен по адресу **http://localhost:5000**

---

## 🔐 Переменные окружения

В production используется файл `/etc/verbena.env`. Для локальной разработки создайте `.env` в корне проекта со следующими ключами:

```env
# ==================================
# Flask
# ==================================
SECRET_KEY=your_secret_key_here
FLASK_DEBUG=1
FORCE_HTTPS=0
API_BASE=http://localhost:5000

# ==================================
# Боты
# ==================================
TG_BOT_TOKEN=
MAX_BOT_TOKEN=
VK_BOT_TOKEN=
VK_GROUP_ID=

# Если Телеграм заблокирован на сервере
BOT_PROXY=

# ==================================
# YCLIENTS
# ==================================
YCLIENTS_PARTNER_TOKEN=
YCLIENTS_USER_TOKEN=
YCLIENTS_COMPANY_ID=

# ==================================
# База данных
# ==================================
DATABASE_URL=./beauty.db
```

> ⚠️ **Важно:** Токены YCLIENTS и ботов являются конфиденциальной информацией и **не хранятся** в репозитории. Добавьте `.env` в `.gitignore`!

---

## 📦 Деплой в продакшен

В репозитории есть готовый bash-скрипт `deploy.sh`, который автоматически:

1. ✅ Устанавливает системные пакеты (`git`, `python3`, `nginx`, `gunicorn`)
2. ✅ Клонирует репозиторий в `/var/www/VERBENA`
3. ✅ Создаёт виртуальное окружение Python
4. ✅ Настраивает systemd-сервисы для Flask-приложения и Telegram-бота
5. ✅ Конфигурирует Nginx как reverse proxy

### Запуск

```bash
sudo bash deploy.sh
```

### После установки

1. Отредактируйте `/etc/verbena.env` и заполните реальные токены
2. Перезапустите сервисы:

```bash
sudo systemctl restart verbena
sudo systemctl restart verbena-bot
sudo systemctl restart nginx
```

### Системные сервисы

| Сервис | Описание |
|--------|----------|
| `verbena` | Основное Flask-приложение через Gunicorn (4 воркера, порт 5000) |
| `verbena-bot` | Постоянно запущенный процесс Telegram-бота |

---

## 🔄 Roadmap

Поддержка проекта продолжается. В планах:

- [ ] Внедрение бота MAX 
- [ ] Добавление пользовательких уведомлений с напоминанием о предстоящих сеансах

---

## 👤 Автор

**Artem** — [artsartone](https://github.com/artsartone)

Разрабатываю, поддерживаю и администрирую проект в единственном лице.

---

<p align="center">
  <sub>Made with 💜 by artsartone</sub>
</p>
