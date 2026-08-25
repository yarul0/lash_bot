"""Функції роботи з БД."""
from datetime import datetime, timedelta
from db import get_db, init_db, seed_schedule_days

DOW_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]

TS_FMT = "%Y-%m-%d %H:%M:%S"


def now_str():
    return datetime.now().strftime(TS_FMT)


# ---------- services ----------
async def list_services():
    db = await get_db()
    cur = await db.execute("SELECT * FROM services WHERE active=1 ORDER BY id")
    rows = await cur.fetchall()
    await db.close()
    return rows


async def create_service(name, duration_min, price):
    db = await get_db()
    await db.execute(
        "INSERT INTO services (name, duration_min, price) VALUES (?, ?, ?)",
        (name, duration_min, price),
    )
    await db.commit()
    await db.close()


async def toggle_service(service_id, active):
    db = await get_db()
    await db.execute("UPDATE services SET active=? WHERE id=?", (active, service_id))
    await db.commit()
    await db.close()


# ---------- slots ----------
async def free_slots_for_service(service_id):
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM slots WHERE service_id=? AND status='free' "
        "AND start_ts >= ? ORDER BY start_ts",
        (service_id, now_str()),
    )
    rows = await cur.fetchall()
    await db.close()
    return rows


async def all_free_slots():
    db = await get_db()
    cur = await db.execute(
        "SELECT s.*, sv.name AS service_name, sv.price AS price "
        "FROM slots s JOIN services sv ON sv.id = s.service_id "
        "WHERE s.status='free' AND s.start_ts >= ? ORDER BY s.start_ts",
        (now_str(),),
    )
    rows = await cur.fetchall()
    await db.close()
    return rows


async def get_service(service_id):
    db = await get_db()
    cur = await db.execute("SELECT * FROM services WHERE id=?", (service_id,))
    row = await cur.fetchone()
    await db.close()
    return row


async def add_slots(service_id, start_ts, duration_min, count):
    if len(start_ts) == 16:
        start_ts += ":00"
    db = await get_db()
    start = datetime.strptime(start_ts, TS_FMT)
    step = timedelta(minutes=duration_min)
    created = 0
    for i in range(count):
        s = start + i * step
        e = s + step
        cur = await db.execute(
            "INSERT OR IGNORE INTO slots (service_id, start_ts, end_ts) VALUES (?, ?, ?)",
            (service_id, s.strftime(TS_FMT), e.strftime(TS_FMT)),
        )
        created += cur.rowcount
    await db.commit()
    await db.close()
    return created


async def get_slot(slot_id):
    db = await get_db()
    cur = await db.execute("SELECT * FROM slots WHERE id=?", (slot_id,))
    row = await cur.fetchone()
    await db.close()
    return row


async def cancel_slot(slot_id):
    db = await get_db()
    await db.execute("UPDATE slots SET status='free' WHERE id=?", (slot_id,))
    await db.commit()
    await db.close()


# ---------- schedule_days ----------
async def list_schedule_days():
    db = await get_db()
    cur = await db.execute("SELECT * FROM schedule_days ORDER BY dow")
    rows = await cur.fetchall()
    await db.close()
    return rows


async def update_schedule_day(dow, active, times):
    db = await get_db()
    await db.execute(
        "UPDATE schedule_days SET active=?, times=? WHERE dow=?",
        (active, times, dow),
    )
    await db.commit()
    await db.close()


async def generate_week(service_id):
    """Створює слоти на наступні 7 днів згідно з розкладом."""
    days = await list_schedule_days()
    svc = None
    for s in await list_services():
        if s["id"] == service_id:
            svc = s
            break
    if not svc:
        return 0

    today = datetime.now()
    monday = (today.replace(hour=0, minute=0, second=0, microsecond=0)
              - timedelta(days=today.weekday()))
    start_week = monday + timedelta(days=7)  # наступний тиждень
    created = 0
    for d in days:
        if not d["active"] or not d["times"]:
            continue
        for t in d["times"].split(","):
            t = t.strip()
            if not t:
                continue
            hh, mm = t.split(":")
            slot_start = start_week + timedelta(days=d["dow"], hours=int(hh), minutes=int(mm))
            created += await add_slots(service_id, slot_start.strftime(TS_FMT), svc["duration_min"], 1)
    return created


# ---------- bookings ----------
async def create_booking(slot, service, client_id, client_name, client_phone):
    db = await get_db()
    await db.execute(
        "UPDATE slots SET status='booked' WHERE id=? AND status='free'",
        (slot["id"],),
    )
    cur = await db.execute(
        "SELECT changes() AS changed"
    )
    row = await cur.fetchone()
    changed = row["changed"] if row else 0
    if not changed:
        await db.close()
        return None
    await db.execute(
        "INSERT INTO bookings (slot_id, client_id, client_name, client_phone, "
        "service_name, price, start_ts, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (slot["id"], client_id, client_name, client_phone, service["name"],
         service["price"], slot["start_ts"], now_str()),
    )
    await db.commit()
    await db.close()
    return True


async def get_booking(booking_id):
    db = await get_db()
    cur = await db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,))
    row = await cur.fetchone()
    await db.close()
    return row


async def set_booking_status(booking_id, status):
    db = await get_db()
    await db.execute("UPDATE bookings SET status=? WHERE id=?", (status, booking_id))
    await db.commit()
    await db.close()


async def client_bookings(client_id, statuses=("pending", "confirmed")):
    db = await get_db()
    q = ",".join("?" * len(statuses))
    cur = await db.execute(
        f"SELECT * FROM bookings WHERE client_id=? AND status IN ({q}) "
        "AND start_ts >= ? ORDER BY start_ts",
        (client_id, *statuses, now_str()),
    )
    rows = await cur.fetchall()
    await db.close()
    return rows


async def booking_id_by_slot(slot_id):
    db = await get_db()
    cur = await db.execute("SELECT id FROM bookings WHERE slot_id=?", (slot_id,))
    row = await cur.fetchone()
    await db.close()
    return row["id"] if row else None


async def pending_reminders():
    """Повертає підтверджені/очікуючі записи, які ще не нагадували."""
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM bookings WHERE reminded=0 AND status IN ('pending','confirmed')"
    )
    rows = await cur.fetchall()
    await db.close()
    return rows


async def mark_reminded(booking_id):
    db = await get_db()
    await db.execute("UPDATE bookings SET reminded=1 WHERE id=?", (booking_id,))
    await db.commit()
    await db.close()


async def upcoming_admin_bookings():
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM bookings WHERE status IN ('pending','confirmed') "
        "AND start_ts >= ? ORDER BY start_ts",
        (now_str(),),
    )
    rows = await cur.fetchall()
    await db.close()
    return rows


async def all_admin_bookings():
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM bookings ORDER BY start_ts DESC LIMIT 200"
    )
    rows = await cur.fetchall()
    await db.close()
    return rows
