import os
import re
import asyncio
from datetime import datetime, timezone, timedelta, date
from typing import List, Dict, Tuple, Optional
from pathlib import Path

from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Header, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from telethon import TelegramClient
from telethon.sessions import StringSession

from db import (
    init_db,
    get_user_by_email,
    get_user_by_id,
    get_session,
    delete_session,
    reset_daily_runs_if_needed,
    update_daily_runs,
    create_user,
    set_access_until,
)
from auth import generate_salt, hash_password, verify_password, create_session_token

CHANNEL_RE = re.compile(
    r"(?:https?://t\.me/(?:s/)?|@)?(?P<user>[A-Za-z0-9_]{4,})", re.IGNORECASE
)
LINK_RE = re.compile(r"https?://t\.me/([^/]+)/(\d+)")

MAX_CHANNELS = 30
MAX_KEYWORDS = 7
MAX_DAYS_WINDOW = 60
MAX_DAILY_RUNS = 5
THROTTLE_SECONDS = 0.05

API_ID = os.getenv("TG_API_ID", "").strip()
API_HASH = os.getenv("TG_API_HASH", "").strip()
SESSION_NAME = os.getenv("TG_SESSION_NAME", "tg_service_session")
TG_STRING_SESSION = os.getenv("TG_STRING_SESSION", "").strip()
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()

load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

app = FastAPI(title="TG Video Parser API")

origins = ["*"] if CORS_ORIGINS.strip() == "*" else [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_at: str
    access_until: Optional[str]


class RegisterRequest(BaseModel):
    email: str
    password: str


class SearchRequest(BaseModel):
    channels: List[str]
    keywords: List[str]
    start_date: str  # YYYY-MM-DD
    end_date: str    # YYYY-MM-DD
    videos_only: bool = True


class SearchResponse(BaseModel):
    links: List[str]
    rows: List[Tuple[str, str]]


class MeResponse(BaseModel):
    email: str
    access_until: Optional[str]
    daily_runs_remaining: int


class AdminCreateUserRequest(BaseModel):
    email: str
    password: str


class AdminGrantAccessRequest(BaseModel):
    email: str
    days: int = 1


@app.on_event("startup")
def on_startup():
    if not API_ID or not API_HASH:
        raise RuntimeError("TG_API_ID/TG_API_HASH are required")
    init_db()


def _parse_date(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(status_code=400, detail="Неверный формат даты (YYYY-MM-DD).")


def _utc_window(start_d: date, end_d: date) -> Tuple[datetime, datetime]:
    start = datetime(start_d.year, start_d.month, start_d.day, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(end_d.year, end_d.month, end_d.day, 23, 59, 59, tzinfo=timezone.utc)
    if end < start:
        raise HTTPException(status_code=400, detail="Конечная дата раньше начальной.")
    return start, end


def _normalize_channels(channels: List[str]) -> List[str]:
    out: List[str] = []
    for raw in channels:
        s = raw.strip()
        if not s:
            continue
        m = CHANNEL_RE.search(s)
        if not m:
            continue
        out.append(m.group("user"))
    seen = set()
    uniq = []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def _normalize_keywords(keywords: List[str]) -> List[str]:
    seen = set()
    uniq = []
    for w in keywords:
        s = w.strip()
        if not s:
            continue
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def _is_video(msg) -> bool:
    if getattr(msg, "video", None):
        return True
    doc = getattr(msg, "document", None)
    if doc and getattr(doc, "mime_type", "") and doc.mime_type.startswith("video/"):
        return True
    return False


def _video_fingerprint(msg) -> Optional[str]:
    doc = getattr(msg, "document", None)
    if doc and getattr(doc, "id", None):
        return f"doc:{doc.id}"
    return None


async def _fetch_text_by_link(client: TelegramClient, link: str) -> str:
    m = LINK_RE.search(link)
    if not m:
        return ""
    username, msg_id = m.group(1), int(m.group(2))
    entity = await client.get_entity(username)
    msg = await client.get_messages(entity, ids=msg_id)
    return (msg.message or "").strip() if msg else ""


async def _search_videos_and_texts(
    channels: List[str],
    keywords: List[str],
    start: datetime,
    end: datetime,
    videos_only: bool,
    throttle: float,
) -> Tuple[List[str], List[Tuple[str, str]]]:
    found: Dict[str, Tuple[datetime, str, str, str]] = {}
    end_inclusive = end + timedelta(seconds=1)

    session = StringSession(TG_STRING_SESSION) if TG_STRING_SESSION else SESSION_NAME

    async with TelegramClient(session, int(API_ID), API_HASH) as client:
        for ch in channels:
            try:
                entity = await client.get_entity(ch)
            except Exception:
                continue

            for kw in keywords:
                async for msg in client.iter_messages(entity, search=kw, offset_date=end_inclusive):
                    if not msg or not msg.date:
                        continue

                    msg_date = msg.date
                    if msg_date.tzinfo is None:
                        msg_date = msg_date.replace(tzinfo=timezone.utc)

                    if msg_date > end:
                        continue
                    if msg_date < start:
                        break

                    if videos_only and (not _is_video(msg)):
                        continue

                    link = f"https://t.me/{ch}/{msg.id}"
                    fp = _video_fingerprint(msg) or f"link:{link}"
                    if fp not in found:
                        found[fp] = (msg_date, ch, kw, link)

                    if throttle > 0:
                        await asyncio.sleep(throttle)

    final = sorted(found.values(), key=lambda x: x[0])
    links_only = [link for _, _, _, link in final]

    rows: List[Tuple[str, str]] = []
    session = StringSession(TG_STRING_SESSION) if TG_STRING_SESSION else SESSION_NAME

    async with TelegramClient(session, int(API_ID), API_HASH) as client:
        for link in links_only:
            try:
                text = await _fetch_text_by_link(client, link)
            except Exception:
                text = ""
            rows.append((link, text))
            if throttle > 0:
                await asyncio.sleep(throttle)

    return links_only, rows


def _get_user_from_token(auth_header: Optional[str]):
    if not auth_header:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Нужна авторизация")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный токен")
    token = auth_header.split(" ", 1)[1].strip()
    sess = get_session(token)
    if not sess:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Сессия не найдена")
    expires_at = datetime.fromisoformat(sess["expires_at"])
    if expires_at < datetime.now(timezone.utc):
        delete_session(token)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Сессия истекла")
    user = get_user_by_id(int(sess["user_id"]))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Пользователь не найден")
    return user


def _require_admin(token_header: Optional[str]):
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN не задан")
    if not token_header or token_header.strip() != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")


@app.post("/auth/login", response_model=LoginResponse)
def login(req: LoginRequest):
    user = get_user_by_email(req.email)
    if not user:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    if not verify_password(req.password, user["password_salt"], user["password_hash"]):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    token, expires_at = create_session_token(int(user["id"]))
    return LoginResponse(
        token=token,
        expires_at=expires_at.isoformat(),
        access_until=user["access_until"],
    )


@app.post("/auth/register", response_model=LoginResponse)
def register(req: RegisterRequest):
    if not req.email or not req.password:
        raise HTTPException(status_code=400, detail="Email и пароль обязательны")
    existing = get_user_by_email(req.email)
    if existing:
        raise HTTPException(status_code=400, detail="Пользователь уже существует")

    salt = generate_salt()
    password_hash = hash_password(req.password, salt)
    try:
        user_id = create_user(req.email, password_hash, salt)
    except Exception:
        raise HTTPException(status_code=400, detail="Пользователь уже существует")

    token, expires_at = create_session_token(int(user_id))
    return LoginResponse(
        token=token,
        expires_at=expires_at.isoformat(),
        access_until=None,
    )


@app.post("/auth/logout")
def logout(authorization: Optional[str] = Header(default=None)):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
        delete_session(token)
    return {"ok": True}


@app.get("/auth/me", response_model=MeResponse)
def me(authorization: Optional[str] = Header(default=None)):
    user = _get_user_from_token(authorization)
    today_str = datetime.now(timezone.utc).date().isoformat()
    _, daily_count = reset_daily_runs_if_needed(int(user["id"]), today_str)
    remaining = max(0, MAX_DAILY_RUNS - daily_count)
    return MeResponse(
        email=user["email"],
        access_until=user["access_until"],
        daily_runs_remaining=remaining,
    )


@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest, authorization: Optional[str] = Header(default=None)):
    user = _get_user_from_token(authorization)

    if not user["access_until"]:
        raise HTTPException(status_code=402, detail="Доступ не активирован")

    access_until = datetime.fromisoformat(user["access_until"])
    if access_until < datetime.now(timezone.utc):
        raise HTTPException(status_code=402, detail="Доступ истек")

    channels = _normalize_channels(req.channels)
    keywords = _normalize_keywords(req.keywords)

    if not channels:
        raise HTTPException(status_code=400, detail="Нет каналов")
    if not keywords:
        raise HTTPException(status_code=400, detail="Нет ключевых слов")

    if len(channels) > MAX_CHANNELS:
        raise HTTPException(status_code=400, detail=f"Слишком много каналов (макс {MAX_CHANNELS})")
    if len(keywords) > MAX_KEYWORDS:
        raise HTTPException(status_code=400, detail=f"Слишком много ключей (макс {MAX_KEYWORDS})")

    start_d = _parse_date(req.start_date)
    end_d = _parse_date(req.end_date)
    if (end_d - start_d).days > MAX_DAYS_WINDOW:
        raise HTTPException(status_code=400, detail=f"Слишком широкий период (макс {MAX_DAYS_WINDOW} дней)")

    start, end = _utc_window(start_d, end_d)

    today_str = datetime.now(timezone.utc).date().isoformat()
    _, daily_count = reset_daily_runs_if_needed(int(user["id"]), today_str)
    if daily_count >= MAX_DAILY_RUNS:
        raise HTTPException(status_code=429, detail="Достигнут дневной лимит запусков")

    links_only, rows = await _search_videos_and_texts(
        channels=channels,
        keywords=keywords,
        start=start,
        end=end,
        videos_only=req.videos_only,
        throttle=THROTTLE_SECONDS,
    )

    update_daily_runs(int(user["id"]), today_str, daily_count + 1)

    return SearchResponse(links=links_only, rows=rows)


@app.post("/admin/create_user")
def admin_create_user(
    req: AdminCreateUserRequest, x_admin_token: Optional[str] = Header(default=None)
):
    _require_admin(x_admin_token)
    salt = generate_salt()
    password_hash = hash_password(req.password, salt)
    try:
        user_id = create_user(req.email, password_hash, salt)
    except Exception:
        raise HTTPException(status_code=400, detail="Пользователь уже существует")
    return {"user_id": user_id}


@app.post("/admin/grant_access")
def admin_grant_access(
    req: AdminGrantAccessRequest, x_admin_token: Optional[str] = Header(default=None)
):
    _require_admin(x_admin_token)
    user = get_user_by_email(req.email)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    access_until = datetime.now(timezone.utc) + timedelta(days=req.days)
    set_access_until(int(user["id"]), access_until)
    return {"ok": True, "access_until": access_until.isoformat()}
