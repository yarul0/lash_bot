"""Мінімальна веб-адмінка (FastAPI) з авторизацією."""
import hashlib
import hmac
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

import config
import repo

app = FastAPI()
TEMPLATES = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES))

COOKIE_NAME = "lash_admin_session"


def make_token() -> str:
    return hmac.new(
        config.ADMIN_PASSWORD.encode(), b"lash-admin", hashlib.sha256
    ).hexdigest()


def is_authed(request: Request) -> bool:
    return hmac.compare_digest(request.cookies.get(COOKIE_NAME, ""), make_token())


def login_redirect() -> Response:
    resp = RedirectResponse("/login", status_code=303)
    return resp


def flash(redirect: str, msg: str) -> Response:
    resp = RedirectResponse(redirect, status_code=303)
    resp.set_cookie("flash", quote(msg))
    return resp


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    flash_cookie = request.cookies.get("flash")
    flash_msg = unquote(flash_cookie) if flash_cookie else ""
    resp = templates.TemplateResponse(
        "login.html", {"request": request, "flash": flash_msg}
    )
    if flash_cookie:
        resp.set_cookie("flash", "", expires=0)
    return resp


@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    if username == config.ADMIN_USERNAME and password == config.ADMIN_PASSWORD:
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(COOKIE_NAME, make_token(), httponly=True, samesite="lax")
        return resp
    return flash("/login", "Невірний логін або пароль")


@app.post("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


@app.on_event("startup")
async def startup():
    await repo.init_db()
    await repo.seed_schedule_days()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not is_authed(request):
        return login_redirect()
    bookings = await repo.all_admin_bookings()
    resp = templates.TemplateResponse("index.html", {"request": request, "bookings": bookings})
    flash_cookie = request.cookies.get("flash")
    if flash_cookie:
        resp.set_cookie("flash", "", expires=0)
        resp = templates.TemplateResponse(
            "index.html",
            {"request": request, "bookings": bookings, "flash": unquote(flash_cookie)},
        )
    return resp


@app.get("/schedule", response_class=HTMLResponse)
async def schedule(request: Request):
    if not is_authed(request):
        return login_redirect()
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
    if not is_authed(request):
        return login_redirect()
    form = await request.form()
    for dow in range(7):
        key = f"times_{dow}"
        times = form.get(key, "").strip()
        active = 1 if form.get(f"active_{dow}") else 0
        await repo.update_schedule_day(dow, active, times)
    return flash("/schedule", "Розклад збережено")


@app.post("/schedule/generate")
async def schedule_generate(request: Request, service_id: int = Form(...)):
    if not is_authed(request):
        return login_redirect()
    created = await repo.generate_week(service_id)
    return flash("/schedule", f"Створено слотів: {created}")


@app.post("/schedule/add")
async def schedule_add(
    request: Request,
    service_id: int = Form(...),
    start: str = Form(...),
    count: int = Form(5),
):
    if not is_authed(request):
        return login_redirect()
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
    if not is_authed(request):
        return login_redirect()
    svcs = await repo.list_services()
    return templates.TemplateResponse("services.html", {"request": request, "services": svcs})


@app.post("/services/add")
async def services_add(
    request: Request,
    name: str = Form(...),
    duration_min: int = Form(...),
    price: int = Form(...),
):
    if not is_authed(request):
        return login_redirect()
    await repo.create_service(name, duration_min, price)
    return flash("/services", "Послугу додано")


@app.post("/services/toggle")
async def services_toggle(request: Request, service_id: int = Form(...)):
    if not is_authed(request):
        return login_redirect()
    svcs = await repo.list_services()
    active = 1
    for s in svcs:
        if s["id"] == service_id:
            active = 0 if s["active"] else 1
            break
    await repo.toggle_service(service_id, active)
    return flash("/services", "Статус змінено")