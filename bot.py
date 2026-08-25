"""Telegram-бот для клієнтів."""
import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, Update, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

import config
import repo

logging.basicConfig(level=logging.INFO)

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

TS_FMT = "%Y-%m-%d %H:%M:%S"


class BookingStates(StatesGroup):
    choosing_slot = State()
    confirming = State()


def fmt_dt(ts):
    d = datetime.strptime(ts, TS_FMT)
    weekday_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
    return f"{d.strftime('%d.%m')} ({weekday_names[d.weekday()]}) о {d.strftime('%H:%M')}"


def main_menu():
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Записатися")],
            [KeyboardButton(text="📋 Мої записи")],
        ],
        resize_keyboard=True,
    )
    return kb


@router.message(CommandStart())
async def cmd_start(message: Message):
    uid = message.from_user.id
    uname = message.from_user.username or ""
    with open("user_ids.log", "a") as f:
        f.write(f"{uid} @{uname}\n")
    await message.answer(
        "Привіт! 👋 Я допоможу записатися на нарощування вій.\n"
        "Оберіть дію:",
        reply_markup=main_menu(),
    )


@router.message(F.text == "📋 Мої записи")
async def my_bookings(message: Message):
    bookings = await repo.client_bookings(message.from_user.id)
    if not bookings:
        await message.answer("У вас немає активних записів.")
        return
    status_map = {
        "pending": "🟡 Очікує підтвердження",
        "confirmed": "✅ Підтверджено",
        "cancelled": "❌ Скасовано",
    }
    for b in bookings:
        txt = (f"👁️ Нарощування вій\n"
               f"🕐 {fmt_dt(b['start_ts'])}\n"
               f"Статус: {status_map.get(b['status'], b['status'])}\n"
               f"📞 {config.MASTER_USERNAME or '@kh_sveta_lash'}")
        buttons = []
        if b["status"] == "pending":
            buttons.append(InlineKeyboardButton(text="✅ Підтвердити",
                                                callback_data=f"confirm_{b['id']}"))
        buttons.append(InlineKeyboardButton(text="❌ Скасувати",
                                            callback_data=f"client_cancel_{b['id']}"))
        kb = InlineKeyboardMarkup(inline_keyboard=[buttons])
        await message.answer(txt, reply_markup=kb)


@router.message(F.text == "📅 Записатися")
async def start_booking(message: Message, state: FSMContext):
    slots = await repo.all_free_slots()
    if not slots:
        await message.answer("Наразі немає вільних слотів. Спробуйте пізніше.")
        return
    await state.set_state(BookingStates.choosing_slot)
    await message.answer("🗓 Оберіть зручний день:")

    weekday_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
    by_day = {}
    for s in slots:
        d = datetime.strptime(s["start_ts"], TS_FMT)
        key = d.date()
        by_day.setdefault(key, []).append(s)

    for day, day_slots in by_day.items():
        header = f"📅 {day.strftime('%d.%m')} · {weekday_names[day.weekday()]}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=s["start_ts"][11:16],
                                 callback_data=f"slot_{s['id']}")] for s in day_slots])
        await message.answer(header, reply_markup=kb)


@router.callback_query(BookingStates.choosing_slot, F.data.startswith("slot_"))
async def choose_slot(cb: CallbackQuery, state: FSMContext):
    slot_id = int(cb.data.split("_")[1])
    slot = await repo.get_slot(slot_id)
    if not slot or slot["status"] != "free":
        await cb.answer("Цей слот щойно зайняли. Оберіть інший.", show_alert=True)
        return
    service = await repo.get_service(slot["service_id"])
    user = cb.from_user
    client_name = f"@{user.username}" if user.username else (user.first_name or "Клієнт")
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Підтвердити", callback_data="final_confirm"),
        InlineKeyboardButton(text="❌ Скасувати", callback_data="final_cancel"),
    ]])
    await state.update_data(slot_id=slot_id, service=service, slot=slot,
                            client_name=client_name, client_phone="")
    await state.set_state(BookingStates.confirming)
    await cb.message.edit_text(
        f"📋 Перевірте запис:\n"
        f"🕐 Час: {fmt_dt(slot['start_ts'])}\n"
        f"👤 Майстер: {config.MASTER_USERNAME or '@kh_sveta_lash'}",
        reply_markup=kb,
    )


@router.callback_query(BookingStates.confirming, F.data == "final_confirm")
async def final_confirm(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    slot = data["slot"]
    service = data["service"]
    created = await repo.create_booking(
        slot, service, cb.from_user.id,
        data["client_name"], data["client_phone"],
    )
    if not created:
        await cb.answer("Час зайнятий", show_alert=True)
        await cb.message.edit_text("На жаль, цей час щойно зайняли. Спробуйте ще раз.")
    else:
        await cb.answer("✅")
        await cb.message.edit_text("🎉 Запис створено! Чекаємо на вас.\n"
                                   "Нагадаємо ближче до візиту.")
        await notify_admin_new_booking(service["name"], slot["start_ts"], data["client_name"])
    await state.clear()


@router.callback_query(BookingStates.confirming, F.data == "final_cancel")
async def final_cancel(cb: CallbackQuery, state: FSMContext):
    await state.set_state(BookingStates.choosing_slot)
    await cb.answer()
    await cb.message.edit_text(
        "Запис скасовано. Оберіть інший час у списку вище 👆"
    )


@router.callback_query(F.data.startswith("confirm_"))
async def confirm_booking(cb: CallbackQuery):
    booking_id = int(cb.data.split("_")[1])
    booking = await repo.get_booking(booking_id)
    if booking and booking["client_id"] == cb.from_user.id:
        await repo.set_booking_status(booking_id, "confirmed")
        await cb.answer("✅ Запис підтверджено!", show_alert=True)
        await notify_admin_confirmation(booking, confirmed=True)
    await cb.message.delete()


@router.callback_query(F.data.startswith("client_cancel_"))
async def client_cancel(cb: CallbackQuery):
    booking_id = int(cb.data.split("_")[2])
    booking = await repo.get_booking(booking_id)
    if booking and booking["client_id"] == cb.from_user.id:
        await repo.set_booking_status(booking_id, "cancelled")
        await repo.cancel_slot(booking["slot_id"])
        await cb.answer("❌ Запис скасовано.", show_alert=True)
        await notify_admin_confirmation(booking, confirmed=False)
    await cb.message.delete()


async def notify_admin_new_booking(service_name, start_ts, client_name):
    try:
        await bot.send_message(
            config.ADMIN_ID,
            f"🆕 Новий запис!\n💇 {service_name}\n🕐 {fmt_dt(start_ts)}\n👤 {client_name}",
        )
    except Exception:
        pass


async def notify_admin_confirmation(booking, confirmed):
    action = "✅ підтвердив" if confirmed else "❌ скасував"
    try:
        await bot.send_message(
            config.ADMIN_ID,
            f"Клієнт {booking['client_name']} {action} запис на {fmt_dt(booking['start_ts'])}",
        )
    except Exception:
        pass


async def reminder_loop():
    """Щогвилини перевіряє записи, що потребують нагадування."""
    while True:
        try:
            now = datetime.now()
            for b in await repo.pending_reminders():
                start = datetime.strptime(b["start_ts"], TS_FMT)
                delta = start - now
                if 0 < delta.total_seconds() <= config.REMINDER_MINUTES * 60:
                    kb = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="✅ Підтверджую",
                                             callback_data=f"confirm_{b['id']}"),
                        InlineKeyboardButton(text="❌ Скасувати",
                                             callback_data=f"client_cancel_{b['id']}"),
                    ]])
                    try:
                        await bot.send_message(
                            b["client_id"],
                            f"⏰ Нагадування! Через {config.REMINDER_MINUTES // 60} год "
                            f"у вас візит на {fmt_dt(b['start_ts'])} ({b['service_name']}).\n"
                            f"Підтвердіть або скасуйте:",
                            reply_markup=kb,
                        )
                        await repo.mark_reminded(b["id"])
                    except Exception:
                        pass
        except Exception as e:
            logging.warning("reminder error: %s", e)
        await asyncio.sleep(60)


async def main():
    await repo.init_db()
    await repo.seed_schedule_days()
    asyncio.create_task(reminder_loop())
    if config.WEBHOOK_URL:
        await webhook_main()
    else:
        await dp.start_polling(bot)


async def webhook_main():
    """Режим для Render: приймає оновлення через webhook на $PORT."""
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse
    import uvicorn

    webhook_path = "/webhook"
    web_app = FastAPI()

    @web_app.get("/")
    async def health():
        html = (
            "<!doctype html><html lang='uk'><head><meta charset='utf-8'>"
            "<title>Lash-bot</title></head><body style='font-family:system-ui;"
            "text-align:center;padding-top:60px'>"
            "<h1>💅 Lash-bot</h1>"
            "<p>Бот працює.</p>"
            f"<p>Майстер: {config.MASTER_USERNAME or '—'}</p>"
            "</body></html>"
        )
        return HTMLResponse(html)

    @web_app.post(webhook_path)
    async def webhook(request: Request):
        if config.WEBHOOK_SECRET and \
                request.headers.get("X-Telegram-Bot-Api-Secret-Token") != config.WEBHOOK_SECRET:
            return {"ok": False}
        update = Update.model_validate(await request.json())
        await dp.feed_update(bot, update)
        return {"ok": True}

    await bot.set_webhook(
        url=config.WEBHOOK_URL + webhook_path,
        secret_token=config.WEBHOOK_SECRET or None,
        drop_pending_updates=True,
    )
    logging.info("Webhook встановлено: %s%s", config.WEBHOOK_URL, webhook_path)
    server = uvicorn.Server(uvicorn.Config(web_app, host="0.0.0.0", port=config.PORT))
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
