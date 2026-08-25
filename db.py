"""Шар доступу до БД: локальний SQLite (aiosqlite) або Turso (хмарний libSQL).

Якщо в .env задано TURSO_URL — використовується Turso, інакше локальний файл.
"""
import aiosqlite
import libsql

import config

DB_PATH = "lash_bot.db"
DEFAULT_TIMES = "09:00,11:00,13:30,16:00"


class Result:
    """Обгортка курсора: повертає рядки як dict (за іменем колонки)."""

    def __init__(self, cursor, async_backend=False):
        self._cursor = cursor
        self._async_backend = async_backend
        self.rowcount = getattr(cursor, "rowcount", 0)
        self.lastrowid = getattr(cursor, "lastrowid", None)

    async def _rows(self):
        rows = self._cursor.fetchall()
        if self._async_backend:
            rows = await rows
        cols = [c[0] for c in (self._cursor.description or [])]
        return [dict(zip(cols, r)) for r in rows]

    async def fetchall(self):
        return await self._rows()

    async def fetchone(self):
        rows = await self._rows()
        return rows[0] if rows else None


class AsyncDB:
    """Єдиний async-інтерфейс для aiosqlite та libsql."""

    def __init__(self, conn):
        self._conn = conn
        self._async_backend = isinstance(conn, aiosqlite.Connection)

    async def execute(self, sql, params=()):
        if self._async_backend:
            cur = await self._conn.execute(sql, params)
        else:
            cur = self._conn.execute(sql, params)
        return Result(cur, async_backend=self._async_backend)

    async def commit(self):
        if isinstance(self._conn, aiosqlite.Connection):
            await self._conn.commit()
        else:
            self._conn.commit()

    async def close(self):
        if isinstance(self._conn, aiosqlite.Connection):
            await self._conn.close()
        else:
            self._conn.close()


def _use_turso():
    return bool(config.TURSO_URL)


async def get_db():
    if _use_turso():
        kwargs = {"database": config.TURSO_URL}
        if config.TURSO_AUTH_TOKEN:
            kwargs["auth_token"] = config.TURSO_AUTH_TOKEN
        return AsyncDB(libsql.connect(**kwargs))
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    return AsyncDB(conn)


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS services (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        duration_min INTEGER NOT NULL,
        price INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS slots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service_id INTEGER NOT NULL REFERENCES services(id),
        start_ts TEXT NOT NULL UNIQUE,
        end_ts TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'free'  -- free | booked | cancelled
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_slots_start ON slots(start_ts)
    """,
    """
    CREATE TABLE IF NOT EXISTS schedule_days (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dow INTEGER NOT NULL UNIQUE,          -- 0=Пн ... 6=Нд
        active INTEGER NOT NULL DEFAULT 1,
        times TEXT NOT NULL DEFAULT ''        -- "09:00,11:00,13:30,16:00"
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slot_id INTEGER NOT NULL REFERENCES slots(id),
        client_id INTEGER NOT NULL,
        client_name TEXT NOT NULL,
        client_phone TEXT DEFAULT '',
        service_name TEXT NOT NULL,
        price INTEGER NOT NULL DEFAULT 0,
        start_ts TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',  -- pending | confirmed | cancelled
        created_at TEXT NOT NULL,
        reminded INTEGER NOT NULL DEFAULT 0
    )
    """,
]


async def init_db():
    db = await get_db()
    for stmt in SCHEMA:
        await db.execute(stmt)
    await db.commit()
    await db.close()


async def seed_schedule_days():
    """Заповнює дні Пн-Сб (0..5) стандартними часами, якщо ще немає."""
    db = await get_db()
    for dow in range(6):
        await db.execute(
            "INSERT OR IGNORE INTO schedule_days (dow, active, times) VALUES (?, 1, ?)",
            (dow, DEFAULT_TIMES),
        )
    await db.commit()
    await db.close()