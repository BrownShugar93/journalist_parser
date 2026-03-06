import os
import math
import re
import asyncio
import uuid
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Callable
import difflib

from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError

from db import (
    init_db,
    get_user_by_email,
    reset_daily_runs_if_needed,
    update_daily_runs,
    create_user,
)
import hashlib
import secrets

CHANNEL_RE = re.compile(
    r"(?:https?://t\.me/(?:s/)?|@)?(?P<user>[A-Za-z0-9_]{4,})", re.IGNORECASE
)

MAX_CHANNELS = 100
MAX_DAYS_WINDOW = 0
MAX_DAILY_RUNS = 20
THROTTLE_SECONDS = 0.03
TEXT_DEDUP_RATIO = 0.95
MAX_PARALLEL_CHANNELS = 1
FUZZY_DEDUP_MAX_ROWS = 1500
MAX_FLOOD_WAIT_SECONDS = 180
MAX_FLOOD_RETRIES = 2

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
ENTITY_CACHE: Dict[str, object] = {}

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
    exclude_keywords: Optional[List[str]] = None
    start_date: str  # YYYY-MM-DD
    end_date: str    # YYYY-MM-DD
    videos_only: bool = True


class SearchResponse(BaseModel):
    links: List[str]
    rows: List[Tuple[str, str, str]]


class StartSearchResponse(BaseModel):
    job_id: str


class SearchStatusResponse(BaseModel):
    job_id: str
    done: bool
    progress: float
    log: Optional[str]
    error: Optional[str]
    links: Optional[List[str]] = None
    rows: Optional[List[Tuple[str, str, str]]] = None




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
        # Never delete running jobs.
        if not bool(job.get("done")):
            continue
        created = float(job.get("created_at", now))
        if now - created > JOB_TTL_SECONDS:
            expired.append(job_id)
    for job_id in expired:
        job = JOBS.get(job_id)
        if job:
            task = job.get("task")
            if task and hasattr(task, "done") and not task.done():
                task.cancel()
        JOBS.pop(job_id, None)

    if len(JOBS) > JOB_MAX_ITEMS:
        done_jobs = [(jid, job) for jid, job in JOBS.items() if bool(job.get("done"))]
        sorted_jobs = sorted(
            done_jobs,
            key=lambda kv: float(kv[1].get("created_at", now)),
        )
        for job_id, _ in sorted_jobs[: max(0, len(JOBS) - JOB_MAX_ITEMS)]:
            job = JOBS.get(job_id)
            if job:
                task = job.get("task")
                if task and hasattr(task, "done") and not task.done():
                    task.cancel()
            JOBS.pop(job_id, None)


def _ensure_guest_user():
    user = get_user_by_email(GUEST_EMAIL)
    if user:
        return
    salt = secrets.token_hex(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256", b"guest", salt.encode("utf-8"), 200_000
    ).hex()
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


def _sanitize_string_session(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    # Common copy/paste artifacts from terminal/docs.
    s = s.replace("\u200b", "").replace("\ufeff", "")
    s = s.strip("\"'`")
    # Keep only the first line that looks like a session token.
    parts = [p.strip() for p in re.split(r"[\r\n]+", s) if p.strip()]
    if parts:
        for p in parts:
            if p.startswith("1") and re.fullmatch(r"[A-Za-z0-9_\-=]+", p):
                return p
        s = parts[-1]
    # Remove spaces if any slipped in.
    s = re.sub(r"\s+", "", s)
    return s


async def _build_dialog_entity_index(client: TelegramClient) -> Dict[str, object]:
    """
    Build fast username -> entity map from local dialogs cache.
    This avoids mass username resolving requests that quickly trigger FloodWait.
    """
    idx: Dict[str, object] = {}
    async for d in client.iter_dialogs(limit=500):
        ent = getattr(d, "entity", None)
        username = (getattr(ent, "username", None) or "").strip()
        if username:
            idx[username.lower()] = ent
    return idx


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


def _normalize_exclude(keywords: Optional[List[str]]) -> List[str]:
    if not keywords:
        return []
    return _normalize_keywords(keywords)


def _text_has_excludes(text: str, excludes: List[str]) -> bool:
    if not excludes:
        return False
    hay = (text or "").lower()
    for w in excludes:
        if w.lower() in hay:
            return True
    return False


def _text_has_keyword(text: str, keywords: List[str]) -> bool:
    if not keywords:
        return False
    hay = (text or "").lower()
    # Fast path.
    for w in keywords:
        if w in hay:
            return True
    # Boundary-friendly path for punctuation/space separated words.
    for w in keywords:
        pattern = r"(?<!\w)" + re.escape(w) + r"(?!\w)"
        if re.search(pattern, hay):
            return True
    return False


def _normalize_text_for_dedup(text: str) -> str:
    t = (text or "").lower()
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _dedup_by_text(
    rows: List[Tuple[str, str, str]], progress_cb: Optional[Callable[[float, str], None]] = None
) -> List[Tuple[str, str, str]]:
    # Fast exact dedup first (linear).
    exact_seen: set[str] = set()
    exact_rows: List[Tuple[str, str, str, str]] = []
    for published_at, link, text in rows:
        norm = _normalize_text_for_dedup(text)
        if not norm:
            exact_rows.append((published_at, link, text, norm))
            continue
        if norm in exact_seen:
            continue
        exact_seen.add(norm)
        exact_rows.append((published_at, link, text, norm))

    # For large batches, skip expensive fuzzy pass to avoid long stalls.
    if len(exact_rows) > FUZZY_DEDUP_MAX_ROWS:
        if progress_cb:
            progress_cb(1.0, "Дедуп: быстрый режим (точные совпадения)")
        return [(published_at, link, text) for published_at, link, text, _ in exact_rows]

    # Fuzzy dedup with candidate bucketing to reduce comparisons.
    deduped: List[Tuple[str, str, str]] = []
    buckets: Dict[str, List[str]] = {}
    total = max(1, len(exact_rows))

    for i, (published_at, link, text, norm) in enumerate(exact_rows, start=1):
        if not norm:
            deduped.append((published_at, link, text))
            continue

        key = norm[:24]
        candidates = buckets.get(key, [])
        is_dup = False
        for prev in candidates:
            # Quick length gate before expensive ratio.
            max_len = max(len(prev), len(norm))
            if max_len == 0:
                continue
            if abs(len(prev) - len(norm)) / max_len > (1 - TEXT_DEDUP_RATIO):
                continue
            if difflib.SequenceMatcher(None, prev, norm).ratio() >= TEXT_DEDUP_RATIO:
                is_dup = True
                break

        if not is_dup:
            deduped.append((published_at, link, text))
            buckets.setdefault(key, []).append(norm)

        if progress_cb and i % 200 == 0:
            progress_cb(0.95 + (i / total) * 0.05, f"Дедуп: {i}/{total}")

    return deduped


def _is_video(msg) -> bool:
    # Prefer strict checks to avoid false positives in mixed/preview messages.
    if getattr(msg, "video_note", None):
        return True
    doc = getattr(msg, "document", None)
    if doc:
        mime_type = getattr(doc, "mime_type", "") or ""
        if mime_type.startswith("video/"):
            return True
        for attr in getattr(doc, "attributes", []) or []:
            if attr.__class__.__name__ == "DocumentAttributeVideo":
                return True
    return False


def _video_fingerprint(msg) -> Optional[str]:
    doc = getattr(msg, "document", None)
    if doc and getattr(doc, "id", None):
        return f"doc:{doc.id}"
    return None


async def _search_videos_and_texts(
    channels: List[str],
    keywords: List[str],
    exclude_keywords: List[str],
    start: datetime,
    end: datetime,
    videos_only: bool,
    throttle: float,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> Tuple[List[str], List[Tuple[str, str, str]]]:
    found: Dict[str, Tuple[datetime, str, str]] = {}
    end_inclusive = end + timedelta(seconds=1)
    string_session = _sanitize_string_session(TG_STRING_SESSION)
    if string_session:
        if not re.fullmatch(r"[A-Za-z0-9_\-=]+", string_session):
            raise RuntimeError("TG_STRING_SESSION содержит недопустимые символы. Вставьте только строку сессии.")
        session = StringSession(string_session)
    else:
        session = SESSION_NAME
    sem = asyncio.Semaphore(max(1, min(MAX_PARALLEL_CHANNELS, len(channels) or 1)))
    found_lock = asyncio.Lock()
    done_channels = 0
    total_channels = max(1, len(channels))
    keywords_lc = [k.lower() for k in keywords]
    excludes_lc = [k.lower() for k in exclude_keywords]
    matched_total = 0
    skipped_channels = 0
    flood_skipped = 0
    max_flood_wait_seconds = 0
    skipped_errors: List[str] = []
    dialog_entity_index: Dict[str, object] = {}

    async def process_channel(client: TelegramClient, ch: str):
        nonlocal done_channels, matched_total, skipped_channels, flood_skipped, max_flood_wait_seconds
        async with sem:
            entity = None
            ch_key = ch.lower()
            entity = ENTITY_CACHE.get(ch_key) or dialog_entity_index.get(ch_key)
            for attempt in range(MAX_FLOOD_RETRIES + 1):
                if entity is not None:
                    break
                try:
                    entity = await client.get_entity(ch)
                    ENTITY_CACHE[ch_key] = entity
                    break
                except FloodWaitError as e:
                    wait_s = int(getattr(e, "seconds", 0) or 0)
                    if wait_s > max_flood_wait_seconds:
                        max_flood_wait_seconds = wait_s
                    if wait_s <= 0 or wait_s > MAX_FLOOD_WAIT_SECONDS or attempt >= MAX_FLOOD_RETRIES:
                        skipped_channels += 1
                        flood_skipped += 1
                        if len(skipped_errors) < 5:
                            skipped_errors.append(f"@{ch}: FloodWaitError({wait_s}s)")
                        if progress_cb:
                            done_channels += 1
                            progress_cb(
                                min(0.95, (done_channels / total_channels) * 0.95),
                                f"@{ch} — flood wait {wait_s}s, пропуск",
                            )
                        return
                    if progress_cb:
                        progress_cb(
                            min(0.95, (done_channels / total_channels) * 0.95),
                            f"@{ch} — flood wait {wait_s}s, жду...",
                        )
                    await asyncio.sleep(wait_s + 1)
                except Exception as e:
                    skipped_channels += 1
                    if len(skipped_errors) < 5:
                        skipped_errors.append(f"@{ch}: {e.__class__.__name__}")
                    if progress_cb:
                        done_channels += 1
                        progress_cb(min(0.95, (done_channels / total_channels) * 0.95), f"@{ch} — пропуск")
                    return

            scanned = 0
            for attempt in range(MAX_FLOOD_RETRIES + 1):
                try:
                    async for msg in client.iter_messages(entity, offset_date=end_inclusive):
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

                        text = (msg.message or "").strip()
                        if keywords_lc and not _text_has_keyword(text, keywords_lc):
                            continue
                        if _text_has_excludes(text, excludes_lc):
                            continue

                        link = f"https://t.me/{ch}/{msg.id}"
                        fp = _video_fingerprint(msg) or f"link:{link}"
                        async with found_lock:
                            if fp not in found:
                                found[fp] = (msg_date, link, text)
                                matched_total += 1

                        scanned += 1
                        if progress_cb and scanned % 200 == 0:
                            progress_cb(
                                min(0.95, (done_channels / total_channels) * 0.95),
                                f"@{ch} — найдено: {scanned}",
                            )

                        if throttle > 0:
                            await asyncio.sleep(throttle)
                    break
                except FloodWaitError as e:
                    wait_s = int(getattr(e, "seconds", 0) or 0)
                    if wait_s > max_flood_wait_seconds:
                        max_flood_wait_seconds = wait_s
                    if wait_s <= 0 or wait_s > MAX_FLOOD_WAIT_SECONDS or attempt >= MAX_FLOOD_RETRIES:
                        skipped_channels += 1
                        if len(skipped_errors) < 5:
                            skipped_errors.append(f"@{ch}: FloodWaitError({wait_s}s)")
                        if progress_cb:
                            progress_cb(
                                min(0.95, (done_channels / total_channels) * 0.95),
                                f"@{ch} — flood wait {wait_s}s, пропуск",
                            )
                        break
                    if progress_cb:
                        progress_cb(
                            min(0.95, (done_channels / total_channels) * 0.95),
                            f"@{ch} — flood wait {wait_s}s, жду...",
                        )
                    await asyncio.sleep(wait_s + 1)

            done_channels += 1
            if progress_cb:
                progress_cb(min(0.95, (done_channels / total_channels) * 0.95), f"@{ch} — готово")

    async def fallback_channel_search(client: TelegramClient, ch: str):
        nonlocal max_flood_wait_seconds
        entity = None
        ch_key = ch.lower()
        entity = ENTITY_CACHE.get(ch_key) or dialog_entity_index.get(ch_key)
        for attempt in range(MAX_FLOOD_RETRIES + 1):
            if entity is not None:
                break
            try:
                entity = await client.get_entity(ch)
                ENTITY_CACHE[ch_key] = entity
                break
            except FloodWaitError as e:
                wait_s = int(getattr(e, "seconds", 0) or 0)
                if wait_s > max_flood_wait_seconds:
                    max_flood_wait_seconds = wait_s
                if wait_s <= 0 or wait_s > MAX_FLOOD_WAIT_SECONDS or attempt >= MAX_FLOOD_RETRIES:
                    return
                await asyncio.sleep(wait_s + 1)
            except Exception:
                return
        for kw in keywords_lc:
            for attempt in range(MAX_FLOOD_RETRIES + 1):
                try:
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

                        text = (msg.message or "").strip()
                        if _text_has_excludes(text, excludes_lc):
                            continue

                        link = f"https://t.me/{ch}/{msg.id}"
                        fp = _video_fingerprint(msg) or f"link:{link}"
                        async with found_lock:
                            if fp not in found:
                                found[fp] = (msg_date, link, text)
                        if throttle > 0:
                            await asyncio.sleep(throttle)
                    break
                except FloodWaitError as e:
                    wait_s = int(getattr(e, "seconds", 0) or 0)
                    if wait_s > max_flood_wait_seconds:
                        max_flood_wait_seconds = wait_s
                    if wait_s <= 0 or wait_s > MAX_FLOOD_WAIT_SECONDS or attempt >= MAX_FLOOD_RETRIES:
                        break
                    await asyncio.sleep(wait_s + 1)

    async with TelegramClient(session, int(API_ID), API_HASH) as client:
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram-сессия не авторизована. Обновите TG_STRING_SESSION или сессию.")
        dialog_entity_index = await _build_dialog_entity_index(client)
        await asyncio.gather(*(process_channel(client, ch) for ch in channels))
        if not found:
            if progress_cb:
                progress_cb(0.6, "Первый проход пустой, пробую fallback-поиск...")
            await asyncio.gather(*(fallback_channel_search(client, ch) for ch in channels))

    if skipped_channels >= total_channels:
        details = "; ".join(skipped_errors) if skipped_errors else "ошибки get_entity"
        raise RuntimeError(f"Не удалось открыть ни один канал ({skipped_channels}/{total_channels}): {details}")
    if not found and flood_skipped > 0:
        wait_minutes = max(1, math.ceil(max_flood_wait_seconds / 60)) if max_flood_wait_seconds > 0 else 10
        raise RuntimeError(
            f"Telegram временно ограничил доступ (FloodWait) по {flood_skipped} каналам. "
            f"Подождите примерно {wait_minutes} мин и повторите."
        )

    final = sorted(found.values(), key=lambda x: x[0], reverse=True)
    rows = [(dt.isoformat(), link, text) for dt, link, text in final]
    if progress_cb:
        progress_cb(
            0.95,
            f"Дедуп по тексту... найдено: {len(rows)}, совпадений: {matched_total}, пропусков каналов: {skipped_channels}",
        )
    rows = _dedup_by_text(rows, progress_cb=progress_cb)
    links_only = [link for _, link, _ in rows]
    if progress_cb:
        progress_cb(
            1.0,
            f"Готово. Каналов пропущено из-за FloodWait: {flood_skipped}",
        )
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
    excludes = _normalize_exclude(req.exclude_keywords)

    if not channels:
        raise HTTPException(status_code=400, detail="Нет каналов")
    if not keywords:
        raise HTTPException(status_code=400, detail="Нет ключевых слов")

    if len(channels) > MAX_CHANNELS:
        raise HTTPException(status_code=400, detail=f"Слишком много каналов (макс {MAX_CHANNELS})")
    # лимит по количеству ключевых слов отключен

    start_d = _parse_date(req.start_date)
    end_d = _parse_date(req.end_date)
    # временный лимит по периоду отключен

    start, end = _utc_window(start_d, end_d)

    today_str = datetime.now(timezone.utc).date().isoformat()
    _, daily_count = reset_daily_runs_if_needed(int(user["id"]), today_str)
    if daily_count >= MAX_DAILY_RUNS:
        raise HTTPException(status_code=429, detail="Достигнут дневной лимит запусков")

    links_only, rows = await _search_videos_and_texts(
        channels=channels,
        keywords=keywords,
        exclude_keywords=excludes,
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
        job = JOBS.get(job_id)
        if not job:
            return
        job["progress"] = pct * 100
        job["log"] = msg

    try:
        job = JOBS.get(job_id)
        if job:
            job["progress"] = 1.0
            job["log"] = "Инициализация..."
        channels = _normalize_channels(req.channels)
        keywords = _normalize_keywords(req.keywords)
        excludes = _normalize_exclude(req.exclude_keywords)
        start_d = _parse_date(req.start_date)
        end_d = _parse_date(req.end_date)
        start, end = _utc_window(start_d, end_d)

        links_only, rows = await _search_videos_and_texts(
            channels=channels,
            keywords=keywords,
            exclude_keywords=excludes,
            start=start,
            end=end,
            videos_only=req.videos_only,
            throttle=THROTTLE_SECONDS,
            progress_cb=progress_cb,
        )
        job = JOBS.get(job_id)
        if not job:
            return
        job["links"] = links_only
        job["rows"] = rows
        job["done"] = True
        job["progress"] = 100.0
        if not job.get("log"):
            job["log"] = "Готово"
        if links_only:
            user_id = int(job["user_id"])
            today_str = str(job["today_str"])
            _, daily_count = reset_daily_runs_if_needed(user_id, today_str)
            update_daily_runs(user_id, today_str, daily_count + 1)
    except Exception as e:
        job = JOBS.get(job_id)
        if job:
            job["done"] = True
            job["error"] = str(e)
    finally:
        job = JOBS.get(job_id)
        if job:
            job["task"] = None


@app.post("/search/start", response_model=StartSearchResponse)
async def start_search(req: SearchRequest):
    user = _get_user_from_token(None)

    channels = _normalize_channels(req.channels)
    keywords = _normalize_keywords(req.keywords)
    excludes = _normalize_exclude(req.exclude_keywords)
    if not channels:
        raise HTTPException(status_code=400, detail="Нет каналов")
    if not keywords:
        raise HTTPException(status_code=400, detail="Нет ключевых слов")
    if len(channels) > MAX_CHANNELS:
        raise HTTPException(status_code=400, detail=f"Слишком много каналов (макс {MAX_CHANNELS})")
    # лимит по количеству ключевых слов отключен
    start_d = _parse_date(req.start_date)
    end_d = _parse_date(req.end_date)
    # временный лимит по периоду отключен

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
        "task": None,
    }
    req.exclude_keywords = excludes
    task = asyncio.create_task(_run_job(job_id, req))
    JOBS[job_id]["task"] = task
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
