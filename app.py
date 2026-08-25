"""Мінімальна веб-адмінка (FastAPI)."""
from pathlib import Path

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from urllib.parse import quote

import repo

app = FastAPI()
TEMPLATES = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES))


def flash(redirect: str, msg: str) -> Response:
    resp = RedirectResponse(redirect, status_code=303)
    resp.set_cookie("flash", quote(msg))
    return resp


@app.on_event("startup")
async def startup():
    await repo.init_db()
    await repo.seed_schedule_days()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    bookings = await repo.all_admin_bookings()
    resp = templates.TemplateResponse("index.html", {"request": request, "bookings": bookings})
    flash_cookie = request.cookies.get("flash")
    if flash_cookie:
        resp.set_cookie("flash", "", expires=0)
        resp = templates.TemplateResponse(
            "index.html",
            {"request": request, "bookings": bookings, "flash": __import__("urllib.parse", fromlist=["unquote"]).unquote(flash_cookie)},
        )
    return resp


@app.get("/schedule", response_class=HTMLResponse)
async def schedule(request: Request):
    services = await repo.list_services()
    free_slots = {}
    for s in services:
        free_slots[s["id"]] = await repo.free_slots_for_service(s["id"])
    days = await repo.list_schedule_days()
    return templates.TemplateResponse(
        "schedule.html",
        {"request": request, "services": services, "free_slots": free_slots,
         "days": days, "DOW_NAMES": repo.DOW_NAMES},
    )


@app.post("/schedule/days")
async def schedule_days(request: Request):
    form = await request.form()
    for dow in range(7):
        key = f"times_{dow}"
        times = form.get(key, "").strip()
        active = 1 if form.get(f"active_{dow}") else 0
        await repo.update_schedule_day(dow, active, times)
    return flash("/schedule", "Розклад збережено")


@app.post("/schedule/generate")
async def schedule_generate(service_id: int = Form(...)):
    created = await repo.generate_week(service_id)
    return flash("/schedule", f"Створено слотів: {created}")


@app.post("/schedule/add")
async def schedule_add(
    service_id: int = Form(...),
    start: str = Form(...),
    count: int = Form(5),
):
    start = start.replace("T", " ")
    svc = None
    for s in await repo.list_services():
        if s["id"] == service_id:
            svc = s
            break
    if svc:
        await repo.add_slots(service_id, start, svc["duration_min"], count)
    return flash("/schedule", "Слоти додано")


@app.get("/services", response_class=HTMLResponse)
async def services(request: Request):
    svcs = await repo.list_services()
    return templates.TemplateResponse("services.html", {"request": request, "services": svcs})


@app.post("/services/add")
async def services_add(
    name: str = Form(...),
    duration_min: int = Form(...),
    price: int = Form(...),
):
    await repo.create_service(name, duration_min, price)
    return flash("/services", "Послугу додано")


@app.post("/services/toggle")
async def services_toggle(service_id: int = Form(...)):
    svcs = await repo.list_services()
    active = 1
    for s in svcs:
        if s["id"] == service_id:
            active = 0 if s["active"] else 1
            break
    await repo.toggle_service(service_id, active)
    return flash("/services", "Статус змінено")
