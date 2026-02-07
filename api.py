import os
import re
import asyncio
import uuid
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Callable

from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from telethon import TelegramClient
from telethon.sessions import StringSession

from db import (
    init_db,
    get_user_by_email,
    reset_daily_runs_if_needed,
    update_daily_runs,
    create_user,
)
from auth import generate_salt, hash_password

CHANNEL_RE = re.compile(
    r"(?:https?://t\.me/(?:s/)?|@)?(?P<user>[A-Za-z0-9_]{4,})", re.IGNORECASE
)
LINK_RE = re.compile(r"https?://t\.me/([^/]+)/(\d+)")

MAX_CHANNELS = 100
MAX_KEYWORDS = 7
MAX_DAYS_WINDOW = 60
MAX_DAILY_RUNS = 20
THROTTLE_SECONDS = 0.05

load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

API_ID = os.getenv("TG_API_ID", "").strip()
API_HASH = os.getenv("TG_API_HASH", "").strip()
SESSION_NAME = os.getenv("TG_SESSION_NAME", "tg_service_session")
TG_STRING_SESSION = os.getenv("TG_STRING_SESSION", "").strip()
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")

GUEST_EMAIL = "guest@vestigator.local"

app = FastAPI(title="TG Video Parser API")

APP_VERSION = "2026-02-06-free-access"

JOBS: Dict[str, Dict[str, object]] = {}
JOB_TTL_SECONDS = 60 * 30
JOB_MAX_ITEMS = 200

origins = ["*"] if CORS_ORIGINS.strip() == "*" else [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



class SearchRequest(BaseModel):
    channels: List[str]
    keywords: List[str]
    start_date: str  # YYYY-MM-DD
    end_date: str    # YYYY-MM-DD
    videos_only: bool = True


class SearchResponse(BaseModel):
    links: List[str]
    rows: List[Tuple[str, str]]


class StartSearchResponse(BaseModel):
    job_id: str


class SearchStatusResponse(BaseModel):
    job_id: str
    done: bool
    progress: float
    log: Optional[str]
    error: Optional[str]
    links: Optional[List[str]] = None
    rows: Optional[List[Tuple[str, str]]] = None




@app.on_event("startup")
def on_startup():
    if not API_ID or not API_HASH:
        raise RuntimeError("TG_API_ID/TG_API_HASH are required")
    init_db()
    _ensure_guest_user()
    asyncio.create_task(_jobs_gc_loop())


async def _jobs_gc_loop():
    while True:
        _cleanup_jobs()
        await asyncio.sleep(60)


def _cleanup_jobs():
    now = datetime.now(timezone.utc).timestamp()
    expired = []
    for job_id, job in JOBS.items():
        created = float(job.get("created_at", now))
        if now - created > JOB_TTL_SECONDS:
            expired.append(job_id)
    for job_id in expired:
        JOBS.pop(job_id, None)

    if len(JOBS) > JOB_MAX_ITEMS:
        sorted_jobs = sorted(
            JOBS.items(),
            key=lambda kv: float(kv[1].get("created_at", now)),
        )
        for job_id, _ in sorted_jobs[: max(0, len(JOBS) - JOB_MAX_ITEMS)]:
            JOBS.pop(job_id, None)


def _ensure_guest_user():
    user = get_user_by_email(GUEST_EMAIL)
    if user:
        return
    salt = generate_salt()
    password_hash = hash_password("guest", salt)
    create_user(GUEST_EMAIL, password_hash, salt)


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
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> Tuple[List[str], List[Tuple[str, str]]]:
    found: Dict[str, Tuple[datetime, str, str, str]] = {}
    end_inclusive = end + timedelta(seconds=1)

    session = StringSession(TG_STRING_SESSION) if TG_STRING_SESSION else SESSION_NAME

    async with TelegramClient(session, int(API_ID), API_HASH) as client:
        total_steps = max(1, len(channels) * max(1, len(keywords)))
        done_steps = 0
        for ch in channels:
            try:
                entity = await client.get_entity(ch)
            except Exception:
                continue

            for kw in keywords:
                if progress_cb:
                    progress_cb(min(0.9, done_steps / total_steps * 0.9), f"@{ch} — «{kw}»")
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
                done_steps += 1
                if progress_cb:
                    progress_cb(min(0.9, done_steps / total_steps * 0.9), f"@{ch} — «{kw}»")

    final = sorted(found.values(), key=lambda x: x[0])
    links_only = [link for _, _, _, link in final]

    rows: List[Tuple[str, str]] = []
    session = StringSession(TG_STRING_SESSION) if TG_STRING_SESSION else SESSION_NAME

    async with TelegramClient(session, int(API_ID), API_HASH) as client:
        total_links = max(1, len(links_only))
        for i, link in enumerate(links_only, start=1):
            try:
                text = await _fetch_text_by_link(client, link)
            except Exception:
                text = ""
            rows.append((link, text))
            if progress_cb:
                pct = 0.9 + (i / total_links) * 0.1
                progress_cb(min(1.0, pct), f"Тексты: {i}/{len(links_only)}")
            if throttle > 0:
                await asyncio.sleep(throttle)

    return links_only, rows


def _get_user_from_token(auth_header: Optional[str]):
    guest = get_user_by_email(GUEST_EMAIL)
    if guest:
        return guest
    _ensure_guest_user()
    guest = get_user_by_email(GUEST_EMAIL)
    if guest:
        return guest
    raise HTTPException(status_code=500, detail="Guest user not available")




@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest):
    user = _get_user_from_token(None)

    # Access gating temporarily disabled by request.

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

    if links_only:
        update_daily_runs(int(user["id"]), today_str, daily_count + 1)

    return SearchResponse(links=links_only, rows=rows)


async def _run_job(job_id: str, req: SearchRequest):
    def progress_cb(pct: float, msg: str):
        JOBS[job_id]["progress"] = pct * 100
        JOBS[job_id]["log"] = msg

    try:
        channels = _normalize_channels(req.channels)
        keywords = _normalize_keywords(req.keywords)
        start_d = _parse_date(req.start_date)
        end_d = _parse_date(req.end_date)
        start, end = _utc_window(start_d, end_d)

        links_only, rows = await _search_videos_and_texts(
            channels=channels,
            keywords=keywords,
            start=start,
            end=end,
            videos_only=req.videos_only,
            throttle=THROTTLE_SECONDS,
            progress_cb=progress_cb,
        )
        JOBS[job_id]["links"] = links_only
        JOBS[job_id]["rows"] = rows
        JOBS[job_id]["done"] = True
        JOBS[job_id]["progress"] = 100.0
        JOBS[job_id]["log"] = "Готово"
        if links_only:
            user_id = int(JOBS[job_id]["user_id"])
            today_str = str(JOBS[job_id]["today_str"])
            _, daily_count = reset_daily_runs_if_needed(user_id, today_str)
            update_daily_runs(user_id, today_str, daily_count + 1)
    except Exception as e:
        JOBS[job_id]["done"] = True
        JOBS[job_id]["error"] = str(e)


@app.post("/search/start", response_model=StartSearchResponse)
async def start_search(req: SearchRequest):
    user = _get_user_from_token(None)

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

    today_str = datetime.now(timezone.utc).date().isoformat()
    _, daily_count = reset_daily_runs_if_needed(int(user["id"]), today_str)
    if daily_count >= MAX_DAILY_RUNS:
        raise HTTPException(status_code=429, detail="Достигнут дневной лимит запусков")

    job_id = uuid.uuid4().hex
    JOBS[job_id] = {
        "done": False,
        "progress": 0.0,
        "log": "Старт",
        "error": None,
        "links": None,
        "rows": None,
        "user_id": int(user["id"]),
        "today_str": today_str,
        "created_at": datetime.now(timezone.utc).timestamp(),
    }
    asyncio.create_task(_run_job(job_id, req))
    return StartSearchResponse(job_id=job_id)


@app.get("/search/status/{job_id}", response_model=SearchStatusResponse)
def search_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return SearchStatusResponse(
        job_id=job_id,
        done=bool(job.get("done")),
        progress=float(job.get("progress") or 0.0),
        log=job.get("log"),
        error=job.get("error"),
        links=job.get("links"),
        rows=job.get("rows"),
    )




@app.get("/version")
def version():
    return {"version": APP_VERSION}
