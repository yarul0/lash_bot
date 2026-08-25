# 🎀 Бот запису на вії

Telegram-бот для клієнтів + мінімальна веб-адмінка для майстра.

## Можливості
- **Клієнт (бот):** запис на процедуру, перегляд своїх записів, підтвердження/скасування, автонагадування перед візитом.
- **Майстер (веб-адмінка):** керування послугами, створення вільних слотів, перегляд усіх записів.

> **Дані:** за замовчуванням зберігаються в локальному файлі `lash_bot.db` (SQLite).
> Якщо в `.env` задано `TURSO_URL` — використовується хмарна база [Turso](https://turso.tech)
> (потрібна для деплою, щоб бот і локальна адмінка бачили одні й ті самі дані).

## Встановлення

```bash
cd lash_bot
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # заповнити BOT_TOKEN і ADMIN_ID
```

## Запуск
```bash
# термінал 1 — бот
python bot.py

# термінал 2 — адмінка (відкрити http://127.0.0.1:8000)
uvicorn app:app --port 8000
```

## Деплой на Render (безкоштовно, 24/7)

Потрібні: акаунт на [Render](https://render.com) і хмарна база [Turso](https://turso.tech).

### 1. Створити Turso-базу
```bash
npm install -g @libsql/client   # або скористайся turso CLI
curl -sSfL https://get.turso.tech/install.sh | bash   # turso CLI
turso auth login
turso db create lash_bot
turso db show lash_bot --url      # → TURSO_URL (libsql://...turso.io)
turso db tokens create lash_bot   # → TURSO_AUTH_TOKEN
```

### 2. Перенести поточні дані у хмару (один раз)
Впиши `TURSO_URL`/`TURSO_AUTH_TOKEN` у `.env` і запусти:
```bash
python migrate_to_turso.py
```

### 3. Завантажити код у git-репозиторій (GitHub)

### 4. У Render: New → Web Service
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `python bot.py`
- **Environment Variables** (у `Environment` сервісу):
  - `BOT_TOKEN`, `ADMIN_ID`, `REMINDER_MINUTES`, `MASTER_USERNAME`
  - `ADMIN_USERNAME`, `ADMIN_PASSWORD` — логін/пароль від веб-адмінки
  - `TURSO_URL`, `TURSO_AUTH_TOKEN`
  - `WEBHOOK_URL` — URL сервісу, напр. `https://lash-bot.onrender.com`
  - `WEBHOOK_SECRET` — будь-який випадковий рядок
  - `PORT` — залиш `10000` (Render підставляє свій `$PORT`, якщо не задано — береться `8080`)

> Бот сам реєструє webhook при старті. Локально (без `WEBHOOK_URL`) він працює в режимі polling.
>
> Адмінка живе в **тому ж сервісі** і доступна за тим самим доменом:
> `https://lash-bot.onrender.com/` → сторінка входу (логін/пароль з `ADMIN_USERNAME`/`ADMIN_PASSWORD`).
>
> Безкоштовний план Render «засинає» після 15 хв без трафіку.
> Щоб бот прокидався миттєво, налаштуй безкоштовний пінг
> на [cron-job.org](https://cron-job.org) — GET запит на `https://lash-bot.onrender.com/health` кожні 10 хвилин.
> Перші повідомлення клієнтів після сну можуть затриматися на ~30–60 с (Telegram сам повторює webhook).

### 5. Налаштування адмінки після деплою
Локальна адмінка (`uvicorn app:app`) має працювати з **тими самими** `TURSO_URL`/`TURSO_AUTH_TOKEN`
у `.env`, щоб бачити записи з хмарної бази. Тепер вона теж захищена логіном/паролем.

## Як отримати токен бота
1. Напиши [@BotFather](https://t.me/BotFather) → `/newbot` → отримай токен.
2. Дізнайся свій `ADMIN_ID` — надішли боту `/start` і подивись лог, або скористайся [@userinfobot](https://t.me/userinfobot).

## Структура
- `bot.py` — Telegram-бот + нагадування (+ webhook для Render)
- `app.py` — веб-адмінка
- `db.py` / `repo.py` — схема та запити (локальний SQLite або Turso)
- `migrate_to_turso.py` — перенесення даних у хмару
- `config.py` — налаштування з `.env`
- `templates/` — HTML сторінки адмінки
