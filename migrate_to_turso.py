"""Міграція даних з локальної SQLite-БД у Turso.

Використання:
  1. Створіть Turso-базу та токен, вкажіть TURSO_URL/TURSO_AUTH_TOKEN у .env
  2. Запустіть:  .venv/bin/python migrate_to_turso.py
"""
import asyncio

import aiosqlite
import libsql

import config
import db

TABLES = ["services", "slots", "schedule_days", "bookings"]


async def main():
    if not config.TURSO_URL:
        print("TURSO_URL не задано у .env — міграцію скасовано.")
        return

    src = await aiosqlite.connect("lash_bot.db")
    src.row_factory = aiosqlite.Row
    dst = libsql.connect(database=config.TURSO_URL,
                         auth_token=config.TURSO_AUTH_TOKEN or None)

    for stmt in db.SCHEMA:
        dst.execute(stmt)
    dst.commit()
    print("Схему створено")
    for dow in range(6):
        dst.execute(
            "INSERT OR IGNORE INTO schedule_days (dow, active, times) VALUES (?, 1, ?)",
            (dow, db.DEFAULT_TIMES),
        )
    dst.commit()

    for table in TABLES:
        cur = await src.execute(f"SELECT * FROM {table}")
        rows = await cur.fetchall()
        cols = [d[0] for d in cur.description]
        placeholders = ",".join("?" * len(cols))
        names = ",".join(cols)
        inserted = 0
        for row in rows:
            dst.execute(
                f"INSERT OR IGNORE INTO {table} ({names}) VALUES ({placeholders})",
                tuple(row),
            )
            inserted += 1
        dst.commit()
        print(f"{table}: {inserted} рядків")

    dst.close()
    await src.close()
    print("Готово!")


if __name__ == "__main__":
    asyncio.run(main())