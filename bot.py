# -*- coding: utf-8 -*-
"""
فقط برای تو ♡ — Telegram Bot + Mini App Backend
یک فایل یکپارچه شامل: ربات تلگرام، API بک‌اند، زمان‌بندی، دیتابیس
"""

import os, sys, json, hmac, hashlib, time, asyncio, logging, secrets, re, mimetypes, io
from datetime import datetime, timedelta, time as dtime, date
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import parse_qsl, quote
from functools import wraps

import aiosqlite
from aiohttp import web, ClientSession, FormData
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    WebAppInfo, FSInputFile, BufferedInputFile, ReplyKeyboardRemove,
)
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode, ChatAction
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import jdatetime

try:
    from hijri_converter import Hijri
    HAS_HIJRI = True
except ImportError:
    HAS_HIJRI = False
    Hijri = None

try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False
    genai = None


# ============================================================
# CONFIG
# ============================================================
BOT_TOKEN = os.getenv("8881702653:AAHTHhxezuWTdaHAZSmDyxFB4LkoQJ5yrnc", "").strip()
ADMIN_ID = int(os.getenv("8826879439", "0") or "0")
ALLOWED_USER_ID = int(os.getenv("7499319085", "0") or "0")
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash").strip()
DB_PATH = os.getenv("DB_PATH", "/app/data/app.db")
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/app/data/uploads"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Tehran")
PORT = int(os.getenv("PORT", "8080") or "8080")
HOST = os.getenv("HOST", "0.0.0.0")

BASE_DIR = Path(__file__).parent
WEBAPP_DIR = BASE_DIR / "webapp"

Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
(UPLOAD_DIR / "photos").mkdir(exist_ok=True)
(UPLOAD_DIR / "voices").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("love-bot")

ALLOWED_USERS = {ADMIN_ID, ALLOWED_USER_ID}
if 0 in ALLOWED_USERS:
    ALLOWED_USERS.discard(0)


# ============================================================
# DATABASE SCHEMA
# ============================================================
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_user_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    first_name TEXT,
    privacy_accepted INTEGER DEFAULT 0,
    is_admin INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS relationship_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    start_date TEXT NOT NULL,
    girl_day_date TEXT,
    morning_msg_enabled INTEGER DEFAULT 1,
    evening_msg_enabled INTEGER DEFAULT 1,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    text TEXT,
    photo_file_id TEXT,
    photo_path TEXT,
    voice_file_id TEXT,
    voice_path TEXT,
    voice_duration INTEGER,
    memory_date TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    file_id TEXT,
    file_path TEXT NOT NULL,
    title TEXT,
    description TEXT,
    memory_id INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS voices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    file_id TEXT,
    file_path TEXT NOT NULL,
    title TEXT,
    duration INTEGER,
    memory_id INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS letters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_user_id INTEGER NOT NULL,
    to_user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    is_read INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    date_shamsi TEXT NOT NULL,
    is_annual INTEGER DEFAULT 0,
    description TEXT,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS scheduled_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_type TEXT NOT NULL,
    sent_date TEXT NOT NULL,
    status TEXT DEFAULT 'sent',
    created_at TEXT NOT NULL,
    UNIQUE(msg_type, sent_date)
);

CREATE TABLE IF NOT EXISTS error_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    error_type TEXT,
    message TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id);
CREATE INDEX IF NOT EXISTS idx_photos_user ON photos(user_id);
CREATE INDEX IF NOT EXISTS idx_voices_user ON voices(user_id);
CREATE INDEX IF NOT EXISTS idx_letters_to ON letters(to_user_id);
CREATE INDEX IF NOT EXISTS idx_sched_msg ON scheduled_messages(msg_type, sent_date);
"""


# ============================================================
# DATABASE HELPERS
# ============================================================
async def db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    return conn


async def init_db():
    async with aiosqlite.connect(DB_PATH) as c:
        await c.executescript(SCHEMA)
        cur = await c.execute("SELECT COUNT(*) FROM relationship_settings")
        if (await cur.fetchone())[0] == 0:
            today = jdatetime.date.today().isoformat()
            await c.execute(
                "INSERT INTO relationship_settings (id, start_date, girl_day_date, updated_at) VALUES (1, ?, ?, ?)",
                (today, "", datetime.now().isoformat())
            )
        # Default events
        cur = await c.execute("SELECT COUNT(*) FROM events")
        if (await cur.fetchone())[0] == 0:
            defaults = [
                ("سالگرد رابطه", "", 1, "سالگرد شروع رابطه", 1),
                ("روز دختر", "", 1, "۵ جمادی‌الثانی - ولادت حضرت معصومه (س)", 1),
            ]
            for ev in defaults:
                await c.execute(
                    "INSERT INTO events (title, date_shamsi, is_annual, description, is_active) VALUES (?,?,?,?,?)",
                    ev
                )
        await c.commit()
    logger.info("Database initialized at %s", DB_PATH)


async def log_error(error_type: str, message: str):
    try:
        async with aiosqlite.connect(DB_PATH) as c:
            await c.execute(
                "INSERT INTO error_logs (error_type, message, created_at) VALUES (?,?,?)",
                (error_type, message, datetime.now().isoformat())
            )
            await c.commit()
    except Exception as e:
        logger.error("Failed to log error: %s", e)


async def get_settings() -> Dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT * FROM relationship_settings WHERE id=1")
        row = await cur.fetchone()
        return dict(row) if row else {}


async def update_settings(**kwargs):
    kwargs["updated_at"] = datetime.now().isoformat()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [1]
    async with aiosqlite.connect(DB_PATH) as c:
        await c.execute(f"UPDATE relationship_settings SET {sets} WHERE id=?", vals)
        await c.commit()


async def ensure_user(tg_user_id: int, username: str = None, first_name: str = None):
    async with aiosqlite.connect(DB_PATH) as c:
        cur = await c.execute("SELECT tg_user_id FROM users WHERE tg_user_id=?", (tg_user_id,))
        if not await cur.fetchone():
            await c.execute(
                "INSERT INTO users (tg_user_id, username, first_name, is_admin, created_at) VALUES (?,?,?,?,?)",
                (tg_user_id, username, first_name, 1 if tg_user_id == ADMIN_ID else 0, datetime.now().isoformat())
            )
            await c.commit()


# ============================================================
# JALALI / HIJRI HELPERS
# ============================================================
def format_jalali(d: jdatetime.date) -> str:
    months = ["فروردین","اردیبهشت","خرداد","تیر","مرداد","شهریور",
              "مهر","آبان","آذر","دی","بهمن","اسفند"]
    weekdays = ["دوشنبه","سه‌شنبه","چهارشنبه","پنج‌شنبه","جمعه","شنبه","یکشنبه"]
    try:
        wd = weekdays[d.weekday()]
    except Exception:
        wd = ""
    return f"{wd} {d.day} {months[d.month-1]} {d.year}"


def calculate_relationship(start_date_str: str) -> Dict[str, Any]:
    try:
        start = jdatetime.date.fromisoformat(start_date_str)
    except Exception:
        return {"error": "تاریخ شروع نامعتبر"}
    today = jdatetime.date.today()
    delta = today - start
    days = delta.days
    years = days // 365
    remainder = days - years * 365
    months = remainder // 30
    rem_days = remainder - months * 30
    # Next anniversary
    try:
        next_ann = start.replace(year=today.year)
    except ValueError:
        # leap handling: 30 Esfand -> 29
        next_ann = jdatetime.date(today.year, start.month, min(start.day, 29))
    if next_ann <= today:
        try:
            next_ann = start.replace(year=today.year + 1)
        except ValueError:
            next_ann = jdatetime.date(today.year + 1, start.month, min(start.day, 29))
    days_to_ann = (next_ann - today).days
    return {
        "start_date": start_date_str,
        "start_date_fa": format_jalali(start),
        "today_fa": format_jalali(today),
        "total_days": max(days, 0),
        "years": years,
        "months": months,
        "remaining_days": rem_days,
        "next_anniversary": next_ann.isoformat(),
        "next_anniversary_fa": format_jalali(next_ann),
        "days_to_anniversary": days_to_ann,
    }


def get_girls_day_for_shamsi_year(year: int) -> Optional[jdatetime.date]:
    """۵ جمادی‌الثانی (ماه ۶ قمری) را در سال شمسی داده‌شده پیدا می‌کند."""
    if not HAS_HIJRI:
        return None
    try:
        start_j = jdatetime.date(year, 1, 1)
        start_g = start_j.togregorian()
        for i in range(400):
            g = start_g + timedelta(days=i)
            try:
                h = Hijri(g.year, g.month, g.day)
            except (ValueError, IndexError):
                continue
            if h.month == 6 and h.day == 5:
                result = jdatetime.date.fromgregorian(date=g)
                if result.year == year:
                    return result
        return None
    except Exception as e:
        logger.error("girls day calc error: %s", e)
        return None


async def get_upcoming_events(limit: int = 5) -> List[Dict[str, Any]]:
    today = jdatetime.date.today()
    results = []
    settings = await get_settings()
    rel = calculate_relationship(settings.get("start_date", today.isoformat()))

    # Anniversary
    if rel.get("days_to_anniversary") is not None:
        results.append({
            "title": "سالگرد رابطه",
            "date": rel["next_anniversary"],
            "date_fa": rel["next_anniversary_fa"],
            "days_left": rel["days_to_anniversary"],
            "type": "anniversary",
        })

    # Girls day (computed dynamically for current and next year)
    gd_this = get_girls_day_for_shamsi_year(today.year)
    gd_next = get_girls_day_for_shamsi_year(today.year + 1)
    for gd in [gd_this, gd_next]:
        if gd and gd >= today:
            results.append({
                "title": "روز دختر",
                "date": gd.isoformat(),
                "date_fa": format_jalali(gd),
                "days_left": (gd - today).days,
                "type": "girls_day",
            })
            break

    # Custom events from DB
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT * FROM events WHERE is_active=1 AND title NOT IN ('سالگرد رابطه','روز دختر')")
        rows = await cur.fetchall()
        for r in rows:
            r = dict(r)
            try:
                d = jdatetime.date.fromisoformat(r["date_shamsi"])
                if d < today:
                    if r["is_annual"]:
                        d = d.replace(year=today.year)
                        if d < today:
                            d = d.replace(year=today.year + 1)
                    else:
                        continue
                results.append({
                    "title": r["title"],
                    "date": d.isoformat(),
                    "date_fa": format_jalali(d),
                    "days_left": (d - today).days,
                    "type": "custom",
                })
            except Exception:
                continue

    results.sort(key=lambda x: x["days_left"])
    return results[:limit]


# ============================================================
# LOCAL LOVE MESSAGES (fallback when Gemini unavailable)
# ============================================================
MORNING_MESSAGES = [
    "صبح بخیر عشقم ☀️ دلم برای صدات تنگ شده...",
    "چشمات رو که باز کنی، خورشید من طلوع می‌کنه 🌅",
    "سلام قشنگ‌ترین بهانه‌ی بیداری من ♡ صبحت بخیر",
    "امروز هم مثل هر روز، اولین فکرِ من تویی 💗",
    "صبح بخیر زندگی من، کاش الان کنارت بودم 🌷",
    "یه روز دیگه که با یاد تو شروع می‌شه... صبحت بخیر عشقم",
    "هر صبح که بیدار می‌شم، خوشحال‌ترین آدم دنیام چون تو رو دارم ♡",
    "صبح بخیر عزیز دلم، امروز بیشتر از دیروز دوستت دارم",
    "سلام مهربون‌ترین ♡ روزت پر از اتفاقای قشنگ",
    "بیدار شو عشقم، دنیا منتظر لبخندته 🌸",
]

EVENING_MESSAGES = [
    "شب بخیر ماه من 🌙 کاش الان کنارت بودم",
    "امشب هم با یاد تو می‌خوابم... شب بخیر عشقم ♡",
    "ستاره‌ها رو می‌شمرم تا تو رو پیدا کنم 🌟 شب بخیر",
    "آرامشِ شب من، صدای توئه... شب بخیر زندگیم",
    "خوابای قشنگ ببینی عزیزم، فردا باز هم دوستت دارم 💗",
    "شب بخیر قشنگ‌ترین اتفاق زندگیم 🌙",
    "امشب هم دلم پیش توئه... بخوابی آروم عشقم",
    "ماه امشب به یاد تو می‌درخشه 🌙 شب بخیر همه زندگیم",
    "چشماتو ببند و بخواب، فردا یه روز دیگه با عشق توئه ♡",
    "شب آرومی داشته باشی مهربون‌ترین 🌷",
]


def get_random_local_message(theme: str = "morning") -> str:
    import random
    pool = MORNING_MESSAGES if theme == "morning" else EVENING_MESSAGES
    return random.choice(pool)


async def generate_love_message(theme: str = "morning") -> str:
    if not HAS_GEMINI or not GEMINI_API_KEY:
        return get_random_local_message(theme)
    try:
        def _sync():
            genai.configure(api_key=GEMINI_API_KEY)
            model = genai.GenerativeModel(GEMINI_MODEL)
            label = "صبح‌بخیر" if theme == "morning" else "شب‌بخیر"
            prompt = (
                f"یک پیام {label} فارسی عاشقانه، کوتاه (حداکثر دو جمله)، "
                f"احساسی و مناسب رابطه لانگ‌دیستنس بنویس. "
                f"از ایموجی به اندازه کم استفاده کن. فقط متن پیام، بدون توضیح یا نقل‌قول."
            )
            resp = model.generate_content(prompt)
            return (resp.text or "").strip()
        text = await asyncio.to_thread(_sync)
        if text and len(text) < 500:
            return text
        return get_random_local_message(theme)
    except Exception as e:
        logger.error("Gemini error: %s", e)
        await log_error("gemini", str(e))
        return get_random_local_message(theme)


# ============================================================
# TELEGRAM INIT DATA VALIDATOR (official method)
# ============================================================
def validate_init_data(init_data: str, bot_token: str) -> Optional[Dict[str, Any]]:
    if not init_data:
        return None
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None
    received_hash = parsed.get("hash")
    if not received_hash:
        return None
    data_check = []
    for k, v in parsed.items():
        if k != "hash":
            data_check.append(f"{k}={v}")
    data_check.sort()
    data_check_string = "\n".join(data_check)
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        return None
    auth_date = int(parsed.get("auth_date", "0") or "0")
    if auth_date <= 0 or time.time() - auth_date > 86400:
        return None
    user_json = parsed.get("user")
    if not user_json:
        return None
    try:
        user = json.loads(user_json)
    except Exception:
        return None
    return user


def require_auth(handler):
    @wraps(handler)
    async def wrapper(request):
        init_data = request.headers.get("X-Telegram-Init-Data", "")
        user = validate_init_data(init_data, BOT_TOKEN)
        if not user:
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        tg_id = int(user.get("id", 0))
        if tg_id not in ALLOWED_USERS:
            return web.json_response({"ok": False, "error": "forbidden"}, status=403)
        request["tg_user"] = user
        request["tg_user_id"] = tg_id
        await ensure_user(tg_id, user.get("username"), user.get("first_name"))
        return await handler(request)
    return wrapper


def require_admin(handler):
    @wraps(handler)
    async def wrapper(request):
        init_data = request.headers.get("X-Telegram-Init-Data", "")
        user = validate_init_data(init_data, BOT_TOKEN)
        if not user:
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        tg_id = int(user.get("id", 0))
        if tg_id != ADMIN_ID:
            return web.json_response({"ok": False, "error": "admin only"}, status=403)
        request["tg_user"] = user
        request["tg_user_id"] = tg_id
        return await handler(request)
    return wrapper


# ============================================================
# FILE HELPERS
# ============================================================
MAX_PHOTO_SIZE = 10 * 1024 * 1024
MAX_VOICE_SIZE = 20 * 1024 * 1024
ALLOWED_PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_VOICE_TYPES = {"audio/ogg", "audio/mpeg", "audio/mp4", "audio/wav", "audio/webm", "audio/m4a"}


def safe_filename(ext: str) -> str:
    return f"{secrets.token_urlsafe(16)}{(ext or '').lower()}"


def is_safe_path(path: Path) -> bool:
    try:
        path.resolve().relative_to(UPLOAD_DIR.resolve())
        return True
    except ValueError:
        return False


async def download_tg_file(bot: Bot, file_id: str, dest_dir: Path, ext: str) -> Optional[Path]:
    try:
        file = await bot.get_file(file_id)
        if not file.file_path:
            return None
        bio = io.BytesIO()
        await bot.download_file(file.file_path, destination=bio)
        data = bio.getvalue()
        name = safe_filename(ext)
        out = dest_dir / name
        out.write_bytes(data)
        return out
    except Exception as e:
        logger.error("download tg file error: %s", e)
        await log_error("download", str(e))
        return None


# ============================================================
# FSM STATES
# ============================================================
class MemoryForm(StatesGroup):
    waiting_title = State()
    waiting_text = State()
    waiting_photo = State()
    waiting_voice = State()
    confirm = State()


class AdminLetterForm(StatesGroup):
    waiting_title = State()
    waiting_text = State()
    confirm = State()


class SettingsForm(StatesGroup):
    waiting_start_date = State()
    waiting_girl_day_date = State()
    waiting_event_title = State()
    waiting_event_date = State()


# ============================================================
# BOT SETUP
# ============================================================
router = Router()


def is_allowed(user_id: int) -> bool:
    return user_id in ALLOWED_USERS


def main_menu_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="💗 روزشمار رابطه", callback_data="menu:counter")],
        [InlineKeyboardButton(text="📖 دفتر خاطرات", callback_data="menu:memories")],
        [InlineKeyboardButton(text="🎙 صدای تو", callback_data="menu:voices")],
        [InlineKeyboardButton(text="🖼 گالری عکس‌ها", callback_data="menu:gallery")],
        [InlineKeyboardButton(text="💌 نامه‌های عاشقانه", callback_data="menu:letters")],
        [InlineKeyboardButton(text="🌷 مناسبت‌ها", callback_data="menu:events")],
        [InlineKeyboardButton(text="✨ پیام‌های ویژه", callback_data="menu:special")],
    ]
    if WEBAPP_URL:
        rows.append([InlineKeyboardButton(
            text="🖥 باز کردن مینی‌اپ",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )])
    rows.append([InlineKeyboardButton(text="⚙️ تنظیمات", callback_data="menu:settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_main_menu(message: Message):
    await message.answer(
        "💗 <b>فقط برای تو ♡</b>\n\n"
        "از منوی زیر انتخاب کن:",
        reply_markup=main_menu_kb(),
        parse_mode=ParseMode.HTML,
    )


# ---------- Start / Help ----------
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    if not is_allowed(message.from_user.id):
        await message.answer("⛔️ دسترسی محدود.")
        return
    await ensure_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    async with aiosqlite.connect(DB_PATH) as c:
        cur = await c.execute("SELECT privacy_accepted FROM users WHERE tg_user_id=?", (message.from_user.id,))
        row = await cur.fetchone()
        accepted = row and row[0]
    if not accepted:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ می‌پذیرم و ادامه می‌دهم", callback_data="privacy:accept")],
            [InlineKeyboardButton(text="❌ انصراف", callback_data="privacy:decline")],
        ])
        await message.answer(
            "🌷 <b>سلام عزیزم ♡</b>\n\n"
            "این فضا فقط برای دونفره‌ی ماست.\n\n"
            "🔐 <b>حریم خصوصی:</b>\n"
            "• خاطرات، عکس‌ها و ویس‌های ثبت‌شده در یک فضای خصوصی ذخیره می‌شوند.\n"
            "• مدیر پروژه (شریک عاطفی تو) می‌تواند محتوای ذخیره‌شده را مشاهده کند.\n"
            "• هیچ اطلاعاتی برای شخص ثالثی ارسال نمی‌شود.\n"
            "• هر زمان می‌توانی ثبت خاطره را متوقف یا درخواست حذف دهی.\n\n"
            "با ادامه، این شرایط را می‌پذیری.",
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )
        return
    await send_main_menu(message)


@router.callback_query(F.data == "privacy:accept")
async def cb_privacy_accept(call: CallbackQuery):
    if not is_allowed(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    async with aiosqlite.connect(DB_PATH) as c:
        await c.execute("UPDATE users SET privacy_accepted=1 WHERE tg_user_id=?", (call.from_user.id,))
        await c.commit()
    await call.message.edit_text("🌷 پذیرفته شد. خوش اومدی عزیزم ♡")
    await send_main_menu(call.message)
    await call.answer()


@router.callback_query(F.data == "privacy:decline")
async def cb_privacy_decline(call: CallbackQuery):
    await call.message.edit_text("هر وقت آماده بودی، دوباره /start بزن 🌷")
    await call.answer()


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    if not is_allowed(message.from_user.id): return
    await send_main_menu(message)


# ---------- Counter ----------
@router.callback_query(F.data == "menu:counter")
async def cb_counter(call: CallbackQuery):
    if not is_allowed(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    settings = await get_settings()
    rel = calculate_relationship(settings.get("start_date", jdatetime.date.today().isoformat()))
    text = (
        f"💗 <b>روزشمار رابطه‌ی ما</b>\n\n"
        f"🗓 شروع: {rel.get('start_date_fa','-')}\n"
        f"✨ امروز: {rel.get('today_fa','-')}\n\n"
        f"⏳ <b>{rel.get('total_days',0)}</b> روز عاشقی\n"
        f"📅 {rel.get('years',0)} سال و {rel.get('months',0)} ماه و {rel.get('remaining_days',0)} روز\n\n"
        f"🎂 سالگرد بعدی: {rel.get('next_anniversary_fa','-')}\n"
        f"🔖 {rel.get('days_to_anniversary','-')} روز مونده ♡"
    )
    await call.message.answer(text, parse_mode=ParseMode.HTML)
    await call.answer()


# ---------- Memories ----------
@router.callback_query(F.data == "menu:memories")
async def cb_memories(call: CallbackQuery):
    if not is_allowed(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute(
            "SELECT id, title, memory_date, created_at FROM memories WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
            (call.from_user.id,)
        )
        rows = await cur.fetchall()
    kb = []
    for r in rows:
        kb.append([InlineKeyboardButton(text=f"• {r['title'][:30]}", callback_data=f"mem:view:{r['id']}")])
    kb.append([InlineKeyboardButton(text="➕ ثبت خاطره جدید", callback_data="mem:new")])
    kb.append([InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="menu:main")])
    text = "📖 <b>دفتر خاطرات</b>\n\nیک خاطره انتخاب کن یا خاطره‌ی جدید ثبت کن:"
    if call.message.text:
        await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    else:
        await call.message.answer(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    await call.answer()


@router.callback_query(F.data == "menu:main")
async def cb_main(call: CallbackQuery):
    if not is_allowed(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    if call.message.text:
        await call.message.edit_text("💗 <b>فقط برای تو ♡</b>\n\nاز منوی زیر انتخاب کن:",
                                     reply_markup=main_menu_kb(), parse_mode=ParseMode.HTML)
    else:
        await call.message.answer("💗 <b>فقط برای تو ♡</b>\n\nاز منوی زیر انتخاب کن:",
                                  reply_markup=main_menu_kb(), parse_mode=ParseMode.HTML)
    await call.answer()


@router.callback_query(F.data == "mem:new")
async def cb_mem_new(call: CallbackQuery, state: FSMContext):
    if not is_allowed(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    async with aiosqlite.connect(DB_PATH) as c:
        cur = await c.execute("SELECT privacy_accepted FROM users WHERE tg_user_id=?", (call.from_user.id,))
        row = await cur.fetchone()
        if not row or not row[0]:
            await call.message.answer("⛔️ ابتدا باید شرایط حریم خصوصی را بپذیری. /start بزن.")
            await call.answer(); return
    await state.set_state(MemoryForm.waiting_title)
    await state.update_data(user_id=call.from_user.id, photo=None, voice=None)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ لغو", callback_data="mem:cancel")]
    ])
    await call.message.answer("📝 <b>عنوان خاطره</b> را بفرست:", reply_markup=kb, parse_mode=ParseMode.HTML)
    await call.answer()


@router.callback_query(F.data == "mem:cancel")
async def cb_mem_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer("لغو شد.")
    await call.answer()


@router.message(MemoryForm.waiting_title)
async def mem_title(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id): return
    title = (message.text or "").strip()
    if not title or len(title) < 2:
        await message.answer("عنوان خیلی کوتاهه. دوباره بفرست:"); return
    await state.update_data(title=title)
    await state.set_state(MemoryForm.waiting_text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ بدون متن", callback_data="mem:skip_text")],
        [InlineKeyboardButton(text="❌ لغو", callback_data="mem:cancel")],
    ])
    await message.answer("✍️ <b>متن خاطره</b> را بفرست:", reply_markup=kb, parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "mem:skip_text")
async def mem_skip_text(call: CallbackQuery, state: FSMContext):
    await state.update_data(text="")
    await state.set_state(MemoryForm.waiting_photo)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ بدون عکس", callback_data="mem:skip_photo")],
        [InlineKeyboardButton(text="❌ لغو", callback_data="mem:cancel")],
    ])
    await call.message.answer("🖼 حالا یک <b>عکس</b> بفرست (یا رد کن):", reply_markup=kb, parse_mode=ParseMode.HTML)
    await call.answer()


@router.message(MemoryForm.waiting_text)
async def mem_text(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id): return
    await state.update_data(text=message.text or "")
    await state.set_state(MemoryForm.waiting_photo)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ بدون عکس", callback_data="mem:skip_photo")],
        [InlineKeyboardButton(text="❌ لغو", callback_data="mem:cancel")],
    ])
    await message.answer("🖼 حالا یک <b>عکس</b> بفرست (یا رد کن):", reply_markup=kb, parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "mem:skip_photo")
async def mem_skip_photo(call: CallbackQuery, state: FSMContext):
    await state.update_data(photo_id=None, photo_path=None)
    await state.set_state(MemoryForm.waiting_voice)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ بدون ویس", callback_data="mem:skip_voice")],
        [InlineKeyboardButton(text="❌ لغو", callback_data="mem:cancel")],
    ])
    await call.message.answer("🎙 حالا یک <b>ویس</b> بفرست (یا رد کن):", reply_markup=kb, parse_mode=ParseMode.HTML)
    await call.answer()


@router.message(MemoryForm.waiting_photo, F.photo)
async def mem_photo(message: Message, state: FSMContext, bot: Bot):
    if not is_allowed(message.from_user.id): return
    photo = message.photo[-1]
    path = await download_tg_file(bot, photo.file_id, UPLOAD_DIR / "photos", ".jpg")
    if not path:
        await message.answer("❌ خطا در دریافت عکس. دوباره تلاش کن."); return
    await state.update_data(photo_id=photo.file_id, photo_path=str(path))
    await state.set_state(MemoryForm.waiting_voice)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ بدون ویس", callback_data="mem:skip_voice")],
        [InlineKeyboardButton(text="❌ لغو", callback_data="mem:cancel")],
    ])
    await message.answer("✅ عکس ذخیره شد.\n🎙 حالا یک <b>ویس</b> بفرست (یا رد کن):",
                         reply_markup=kb, parse_mode=ParseMode.HTML)


@router.message(MemoryForm.waiting_photo, F.text)
async def mem_photo_invalid(message: Message):
    await message.answer("لطفاً یک عکس بفرست یا دکمه «بدون عکس» را بزن.")


@router.callback_query(F.data == "mem:skip_voice")
async def mem_skip_voice(call: CallbackQuery, state: FSMContext):
    await state.update_data(voice_id=None, voice_path=None, voice_duration=None)
    await _mem_show_confirm(call.message, state)
    await call.answer()


@router.message(MemoryForm.waiting_voice, F.voice)
async def mem_voice(message: Message, state: FSMContext, bot: Bot):
    if not is_allowed(message.from_user.id): return
    v = message.voice
    ext = ".ogg"
    path = await download_tg_file(bot, v.file_id, UPLOAD_DIR / "voices", ext)
    if not path:
        await message.answer("❌ خطا در دریافت ویس."); return
    await state.update_data(voice_id=v.file_id, voice_path=str(path), voice_duration=v.duration)
    await _mem_show_confirm(message, state)


@router.message(MemoryForm.waiting_voice, F.audio)
async def mem_voice_audio(message: Message, state: FSMContext, bot: Bot):
    if not is_allowed(message.from_user.id): return
    a = message.audio
    ext = Path(a.file_name or "audio.m4a").suffix or ".m4a"
    path = await download_tg_file(bot, a.file_id, UPLOAD_DIR / "voices", ext)
    if not path:
        await message.answer("❌ خطا در دریافت فایل صوتی."); return
    await state.update_data(voice_id=a.file_id, voice_path=str(path), voice_duration=a.duration)
    await _mem_show_confirm(message, state)


@router.message(MemoryForm.waiting_voice, F.text)
async def mem_voice_invalid(message: Message):
    await message.answer("لطفاً یک ویس بفرست یا دکمه «بدون ویس» را بزن.")


async def _mem_show_confirm(message_or_call, state: FSMContext):
    data = await state.get_data()
    text = (
        f"📝 <b>پیش‌نمایش خاطره</b>\n\n"
        f"<b>عنوان:</b> {data.get('title','-')}\n"
        f"<b>متن:</b> {(data.get('text') or '-')[:300]}\n"
        f"<b>عکس:</b> {'دارد 🖼' if data.get('photo_path') else 'ندارد'}\n"
        f"<b>ویس:</b> {'دارد 🎙' if data.get('voice_path') else 'ندارد'}\n\n"
        f"تأیید می‌کنی؟"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تأیید و ذخیره", callback_data="mem:confirm")],
        [InlineKeyboardButton(text="❌ لغو", callback_data="mem:cancel")],
    ])
    if isinstance(message_or_call, CallbackQuery):
        await message_or_call.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await message_or_call.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await state.set_state(MemoryForm.confirm)


@router.callback_query(F.data == "mem:confirm", StateFilter(MemoryForm.confirm))
async def mem_confirm(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("user_id") or call.from_user.id
    now = datetime.now().isoformat()
    today_fa = format_jalali(jdatetime.date.today())
    async with aiosqlite.connect(DB_PATH) as c:
        cur = await c.execute(
            """INSERT INTO memories
               (user_id, title, text, photo_file_id, photo_path, voice_file_id, voice_path, voice_duration, memory_date, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (user_id, data.get("title",""), data.get("text",""),
             data.get("photo_id"), data.get("photo_path"),
             data.get("voice_id"), data.get("voice_path"), data.get("voice_duration"),
             today_fa, now, now)
        )
        mem_id = cur.lastrowid
        await c.commit()
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 دفتر خاطرات", callback_data="menu:memories")],
        [InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="menu:main")],
    ])
    await call.message.answer("✅ خاطره با موفقیت ذخیره شد ♡", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("mem:view:"))
async def mem_view(call: CallbackQuery):
    if not is_allowed(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    mid = int(call.data.split(":")[-1])
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT * FROM memories WHERE id=?", (mid,))
        m = await cur.fetchone()
    if not m:
        await call.answer("پیدا نشد", show_alert=True); return
    m = dict(m)
    text = (
        f"📖 <b>{m['title']}</b>\n\n"
        f"🗓 {m.get('memory_date','-')}\n\n"
        f"{(m.get('text') or '-')[:1500]}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 حذف", callback_data=f"mem:del:{m['id']}")],
        [InlineKeyboardButton(text="🔙 فهرست", callback_data="menu:memories")],
    ])
    if m.get("photo_path") and is_safe_path(Path(m["photo_path"])):
        try:
            await call.message.answer_photo(
                FSInputFile(m["photo_path"]),
                caption=text, reply_markup=kb, parse_mode=ParseMode.HTML
            )
            await call.answer()
            return
        except Exception as e:
            logger.error("send photo error: %s", e)
    if m.get("voice_path") and is_safe_path(Path(m["voice_path"])):
        try:
            await call.message.answer_voice(
                FSInputFile(m["voice_path"]),
                caption=text, reply_markup=kb, parse_mode=ParseMode.HTML
            )
            await call.answer()
            return
        except Exception as e:
            logger.error("send voice error: %s", e)
    await call.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await call.answer()


@router.callback_query(F.data.startswith("mem:del:"))
async def mem_del_ask(call: CallbackQuery):
    if not is_allowed(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    mid = int(call.data.split(":")[-1])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ بله، حذف شود", callback_data=f"mem:delok:{mid}")],
        [InlineKeyboardButton(text="❌ انصراف", callback_data=f"mem:view:{mid}")],
    ])
    await call.message.answer("⚠️ مطمئنی می‌خوای این خاطره حذف شود؟", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("mem:delok:"))
async def mem_del_ok(call: CallbackQuery):
    if not is_allowed(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    mid = int(call.data.split(":")[-1])
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT photo_path, voice_path FROM memories WHERE id=?", (mid,))
        m = await cur.fetchone()
        if m:
            for p in (m["photo_path"], m["voice_path"]):
                if p and is_safe_path(Path(p)):
                    try: Path(p).unlink(missing_ok=True)
                    except Exception: pass
            await c.execute("DELETE FROM memories WHERE id=?", (mid,))
            await c.commit()
    await call.message.edit_text("🗑 خاطره حذف شد.")
    await call.answer()


# ---------- Voices list ----------
@router.callback_query(F.data == "menu:voices")
async def cb_voices(call: CallbackQuery):
    if not is_allowed(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute(
            "SELECT id, title, duration, created_at FROM voices WHERE user_id=? ORDER BY created_at DESC LIMIT 30",
            (call.from_user.id,)
        )
        rows = await cur.fetchall()
    kb = []
    for r in rows:
        dur = f" ({r['duration']}ث)" if r['duration'] else ""
        kb.append([InlineKeyboardButton(text=f"🎙 {r['title'][:28]}{dur}", callback_data=f"voice:view:{r['id']}")])
    kb.append([InlineKeyboardButton(text="💡 برای ضبط ویس جدید از مینی‌اپ یا ارسال ویس به ربات استفاده کن", callback_data="noop")])
    kb.append([InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="menu:main")])
    text = "🎙 <b>صدای تو</b>\n\nویس‌های ثبت‌شده:"
    if call.message.text:
        await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    else:
        await call.message.answer(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    await call.answer()


@router.callback_query(F.data.startswith("voice:view:"))
async def voice_view(call: CallbackQuery):
    if not is_allowed(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    vid = int(call.data.split(":")[-1])
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT * FROM voices WHERE id=?", (vid,))
        v = await cur.fetchone()
    if not v or not v["voice_path"] or not is_safe_path(Path(v["voice_path"])):
        await call.answer("فایل موجود نیست", show_alert=True); return
    v = dict(v)
    try:
        await call.message.answer_voice(
            FSInputFile(v["voice_path"]),
            caption=f"🎙 {v.get('title') or '-'}"
        )
    except Exception as e:
        logger.error("send voice error: %s", e)
        await call.message.answer("❌ خطا در ارسال ویس")
    await call.answer()


# ---------- Gallery ----------
@router.callback_query(F.data == "menu:gallery")
async def cb_gallery(call: CallbackQuery):
    if not is_allowed(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute(
            "SELECT id, title, created_at FROM photos WHERE user_id=? ORDER BY created_at DESC LIMIT 30",
            (call.from_user.id,)
        )
        rows = await cur.fetchall()
    kb = []
    for r in rows:
        kb.append([InlineKeyboardButton(text=f"🖼 {r['title'][:28]}", callback_data=f"photo:view:{r['id']}")])
    kb.append([InlineKeyboardButton(text="💡 برای افزودن عکس از مینی‌اپ استفاده کن", callback_data="noop")])
    kb.append([InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="menu:main")])
    text = "🖼 <b>گالری عکس‌ها</b>"
    if call.message.text:
        await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    else:
        await call.message.answer(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    await call.answer()


@router.callback_query(F.data.startswith("photo:view:"))
async def photo_view(call: CallbackQuery):
    if not is_allowed(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    pid = int(call.data.split(":")[-1])
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT * FROM photos WHERE id=?", (pid,))
        p = await cur.fetchone()
    if not p or not p["file_path"] or not is_safe_path(Path(p["file_path"])):
        await call.answer("فایل موجود نیست", show_alert=True); return
    p = dict(p)
    try:
        await call.message.answer_photo(
            FSInputFile(p["file_path"]),
            caption=f"🖼 {p.get('title') or '-'}\n{(p.get('description') or '')[:300]}"
        )
    except Exception as e:
        logger.error("send photo error: %s", e)
        await call.message.answer("❌ خطا در ارسال عکس")
    await call.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    await call.answer()


# ---------- Letters ----------
@router.callback_query(F.data == "menu:letters")
async def cb_letters(call: CallbackQuery):
    if not is_allowed(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute(
            "SELECT id, title, is_read, created_at FROM letters WHERE to_user_id=? ORDER BY created_at DESC LIMIT 20",
            (call.from_user.id,)
        )
        rows = await cur.fetchall()
    kb = []
    for r in rows:
        mark = "📩" if not r["is_read"] else "✉️"
        kb.append([InlineKeyboardButton(text=f"{mark} {r['title'][:28]}", callback_data=f"letter:view:{r['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="menu:main")])
    text = "💌 <b>نامه‌های عاشقانه</b>\n\nنامه‌های دریافتی:"
    if call.message.text:
        await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    else:
        await call.message.answer(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    await call.answer()


@router.callback_query(F.data.startswith("letter:view:"))
async def letter_view(call: CallbackQuery):
    if not is_allowed(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    lid = int(call.data.split(":")[-1])
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT * FROM letters WHERE id=? AND to_user_id=?", (lid, call.from_user.id))
        l = await cur.fetchone()
        if not l:
            await call.answer("پیدا نشد", show_alert=True); return
        l = dict(l)
        await c.execute("UPDATE letters SET is_read=1 WHERE id=?", (lid,))
        await c.commit()
    text = (
        f"💌 <b>{l['title']}</b>\n\n"
        f"{l['text']}\n\n"
        f"🗓 {l['created_at'][:10]}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 فهرست نامه‌ها", callback_data="menu:letters")]
    ])
    await call.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await call.answer()


# ---------- Events ----------
@router.callback_query(F.data == "menu:events")
async def cb_events(call: CallbackQuery):
    if not is_allowed(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    events = await get_upcoming_events(10)
    lines = ["🌷 <b>مناسبت‌ها</b>\n"]
    for e in events:
        lines.append(f"• <b>{e['title']}</b>\n  🗓 {e['date_fa']}  —  🔖 {e['days_left']} روز مانده")
    if len(events) == 0:
        lines.append("مناسبتی ثبت نشده.")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="menu:main")]
    ])
    await call.message.answer("\n".join(lines), reply_markup=kb, parse_mode=ParseMode.HTML)
    await call.answer()


# ---------- Special messages ----------
@router.callback_query(F.data == "menu:special")
async def cb_special(call: CallbackQuery):
    if not is_allowed(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    msg = await generate_love_message("morning")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 یک پیام دیگر", callback_data="special:regen")],
        [InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="menu:main")],
    ])
    await call.message.answer(f"✨ <b>پیام ویژه</b>\n\n{msg}", reply_markup=kb, parse_mode=ParseMode.HTML)
    await call.answer()


@router.callback_query(F.data == "special:regen")
async def cb_special_regen(call: CallbackQuery):
    if not is_allowed(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    msg = await generate_love_message("evening")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 یک پیام دیگر", callback_data="special:regen")],
        [InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="menu:main")],
    ])
    await call.message.edit_text(f"✨ <b>پیام ویژه</b>\n\n{msg}", reply_markup=kb, parse_mode=ParseMode.HTML)
    await call.answer()


# ---------- Settings ----------
@router.callback_query(F.data == "menu:settings")
async def cb_settings(call: CallbackQuery):
    if not is_allowed(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    s = await get_settings()
    text = (
        f"⚙️ <b>تنظیمات</b>\n\n"
        f"🗓 تاریخ شروع رابطه: <code>{s.get('start_date','-')}</code>\n"
        f"🌷 تاریخ روز دختر: <code>{s.get('girl_day_date') or 'محاسبه خودکار'}</code>\n"
        f"🌅 پیام صبح: {'فعال ☀️' if s.get('morning_msg_enabled') else 'غیرفعال'}\n"
        f"🌙 پیام شب: {'فعال 🌙' if s.get('evening_msg_enabled') else 'غیرفعال'}\n"
    )
    kb = []
    if call.from_user.id == ADMIN_ID:
        kb.append([InlineKeyboardButton(text="🗓 تغییر تاریخ شروع", callback_data="set:start_date")])
        kb.append([InlineKeyboardButton(text="🌷 تنظیم دستی روز دختر", callback_data="set:girl_day")])
        kb.append([InlineKeyboardButton(text="🎁 افزودن مناسبت", callback_data="set:add_event")])
        kb.append([InlineKeyboardButton(text="👥 پنل مدیر", callback_data="admin:panel")])
    kb.append([InlineKeyboardButton(text="🔒 حریم خصوصی", callback_data="set:privacy")])
    kb.append([InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="menu:main")])
    await call.message.answer(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    await call.answer()


@router.callback_query(F.data == "set:privacy")
async def cb_privacy(call: CallbackQuery):
    text = (
        "🔒 <b>سیاست حریم خصوصی</b>\n\n"
        "• تمام داده‌ها در یک فضای خصوصی ذخیره می‌شوند.\n"
        "• مدیر پروژه به محتوا دسترسی دارد.\n"
        "• هیچ اطلاعاتی به شخص ثالث ارسال نمی‌شود.\n"
        "• برای توقف ثبت خاطره یا درخواست حذف، به مدیر پیام بده.\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu:settings")]
    ])
    await call.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await call.answer()


@router.callback_query(F.data == "set:start_date")
async def cb_set_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔️", show_alert=True); return
    await state.set_state(SettingsForm.waiting_start_date)
    await call.message.answer("تاریخ شروع رابطه را به فرمت شمسی بفرست، مثلاً: <code>1402-06-15</code>",
                              parse_mode=ParseMode.HTML)
    await call.answer()


@router.message(SettingsForm.waiting_start_date)
async def set_start_date(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    txt = (message.text or "").strip()
    try:
        jdatetime.date.fromisoformat(txt)
    except Exception:
        await message.answer("فرمت اشتباه. مثال: 1402-06-15"); return
    await update_settings(start_date=txt)
    await state.clear()
    await message.answer(f"✅ تاریخ شروع ذخیره شد: {txt}")


@router.callback_query(F.data == "set:girl_day")
async def cb_set_girl(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔️", show_alert=True); return
    await state.set_state(SettingsForm.waiting_girl_day_date)
    await call.message.answer(
        "برای روز دختر، تاریخ شمسی دقیق (مثلاً <code>1405-12-09</code>) را بفرست.\n"
        "اگر خالی بگذاری، به‌صورت خودکار از ۵ جمادی‌الثانی محاسبه می‌شود.",
        parse_mode=ParseMode.HTML
    )
    await call.answer()


@router.message(SettingsForm.waiting_girl_day_date)
async def set_girl_day(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    txt = (message.text or "").strip()
    if txt:
        try:
            jdatetime.date.fromisoformat(txt)
        except Exception:
            await message.answer("فرمت اشتباه."); return
    await update_settings(girl_day_date=txt)
    await state.clear()
    await message.answer("✅ ذخیره شد.")


@router.callback_query(F.data == "set:add_event")
async def cb_add_event(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔️", show_alert=True); return
    await state.set_state(SettingsForm.waiting_event_title)
    await call.message.answer("عنوان مناسبت را بفرست:")
    await call.answer()


@router.message(SettingsForm.waiting_event_title)
async def set_event_title(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.update_data(title=message.text.strip())
    await state.set_state(SettingsForm.waiting_event_date)
    await message.answer("تاریخ شمسی (مثلاً 1405-03-20) و در پایان «سالانه» اگر هر سال تکرار می‌شود:")


@router.message(SettingsForm.waiting_event_date)
async def set_event_date(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    parts = (message.text or "").strip().split()
    date_str = parts[0]
    is_annual = 1 if any("سالانه" in p for p in parts) else 0
    try:
        jdatetime.date.fromisoformat(date_str)
    except Exception:
        await message.answer("فرمت تاریخ اشتباه."); return
    data = await state.get_data()
    async with aiosqlite.connect(DB_PATH) as c:
        await c.execute(
            "INSERT INTO events (title, date_shamsi, is_annual, is_active) VALUES (?,?,?,1)",
            (data["title"], date_str, is_annual)
        )
        await c.commit()
    await state.clear()
    await message.answer("✅ مناسبت افزوده شد.")


# ---------- Admin panel ----------
@router.callback_query(F.data == "admin:panel")
async def cb_admin(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔️", show_alert=True); return
    async with aiosqlite.connect(DB_PATH) as c:
        cm = await (await c.execute("SELECT COUNT(*) FROM memories")).fetchone()
        cp = await (await c.execute("SELECT COUNT(*) FROM photos")).fetchone()
        cv = await (await c.execute("SELECT COUNT(*) FROM voices")).fetchone()
        cl = await (await c.execute("SELECT COUNT(*) FROM letters WHERE is_read=0")).fetchone()
        cu = await (await c.execute("SELECT COUNT(*) FROM users")).fetchone()
    s = await get_settings()
    text = (
        f"👥 <b>پنل مدیر</b>\n\n"
        f"👤 کاربران: {cu[0]}\n"
        f"📖 خاطرات: {cm[0]}\n"
        f"🖼 عکس‌ها: {cp[0]}\n"
        f"🎙 ویس‌ها: {cv[0]}\n"
        f"💌 نامه‌های خوانده‌نشده: {cl[0]}\n\n"
        f"☀️ پیام صبح: {'فعال' if s.get('morning_msg_enabled') else 'غیرفعال'}\n"
        f"🌙 پیام شب: {'فعال' if s.get('evening_msg_enabled') else 'غیرفعال'}\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ ارسال نامه به کاربر", callback_data="admin:letter")],
        [InlineKeyboardButton(text="📖 همه خاطرات", callback_data="admin:memories")],
        [InlineKeyboardButton(text="🔄 تغییر وضعیت پیام صبح", callback_data="admin:tog_morning")],
        [InlineKeyboardButton(text="🔄 تغییر وضعیت پیام شب", callback_data="admin:tog_evening")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu:settings")],
    ])
    await call.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await call.answer()


@router.callback_query(F.data.startswith("admin:tog_"))
async def cb_admin_tog(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔️", show_alert=True); return
    s = await get_settings()
    if "morning" in call.data:
        await update_settings(morning_msg_enabled=0 if s.get("morning_msg_enabled") else 1)
    else:
        await update_settings(evening_msg_enabled=0 if s.get("evening_msg_enabled") else 1)
    await call.answer("✅ تغییر کرد")
    await cb_admin(call)


@router.callback_query(F.data == "admin:letter")
async def cb_admin_letter(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔️", show_alert=True); return
    await state.set_state(AdminLetterForm.waiting_title)
    await call.message.answer("عنوان نامه را بفرست:")
    await call.answer()


@router.message(AdminLetterForm.waiting_title)
async def admin_letter_title(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.update_data(title=message.text.strip(), to_user_id=ALLOWED_USER_ID)
    await state.set_state(AdminLetterForm.waiting_text)
    await message.answer("متن نامه را بفرست:")


@router.message(AdminLetterForm.waiting_text)
async def admin_letter_text(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    data = await state.get_data()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ارسال", callback_data="admin:letter:send")],
        [InlineKeyboardButton(text="❌ لغو", callback_data="admin:letter:cancel")],
    ])
    await state.update_data(text=message.text)
    await state.set_state(AdminLetterForm.confirm)
    await message.answer(
        f"📝 <b>{data['title']}</b>\n\n{message.text[:300]}\n\nارسال شود؟",
        reply_markup=kb, parse_mode=ParseMode.HTML
    )


@router.callback_query(F.data == "admin:letter:send", StateFilter(AdminLetterForm.confirm))
async def admin_letter_send(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔️", show_alert=True); return
    data = await state.get_data()
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as c:
        await c.execute(
            "INSERT INTO letters (from_user_id, to_user_id, title, text, created_at) VALUES (?,?,?,?,?)",
            (ADMIN_ID, data["to_user_id"], data["title"], data["text"], now)
        )
        await c.commit()
    await state.clear()
    await call.message.edit_text("✅ نامه ارسال شد ♡")
    await call.answer()


@router.callback_query(F.data == "admin:letter:cancel")
async def admin_letter_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("لغو شد.")
    await call.answer()


@router.callback_query(F.data == "admin:memories")
async def cb_admin_memories(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔️", show_alert=True); return
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT id, user_id, title, memory_date FROM memories ORDER BY created_at DESC LIMIT 30")
        rows = await cur.fetchall()
    kb = []
    for r in rows:
        kb.append([InlineKeyboardButton(text=f"• {r['title'][:30]}", callback_data=f"mem:view:{r['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin:panel")])
    await call.message.answer("📖 همه خاطرات:", reply_markup=InlineKeyboardMarkup(kb))
    await call.answer()


# ---------- Voice/Photo direct send to bot ----------
@router.message(F.voice | F.audio)
async def on_voice(message: Message, state: FSMContext, bot: Bot):
    if not is_allowed(message.from_user.id): return
    cur = await state.get_state()
    if cur: return  # handled by FSM
    v = message.voice or message.audio
    ext = ".ogg"
    if message.audio:
        ext = Path(message.audio.file_name or "audio.m4a").suffix or ".m4a"
    path = await download_tg_file(bot, v.file_id, UPLOAD_DIR / "voices", ext)
    if not path:
        await message.answer("❌ خطا در ذخیره ویس"); return
    title = f"ویس {format_jalali(jdatetime.date.today())}"
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as c:
        cur = await c.execute(
            "INSERT INTO voices (user_id, file_id, file_path, title, duration, created_at) VALUES (?,?,?,?,?,?)",
            (message.from_user.id, v.file_id, str(path), title, v.duration, now)
        )
        await c.commit()
    await message.answer("🎙 ویس ذخیره شد ♡")


@router.message(F.photo)
async def on_photo(message: Message, state: FSMContext, bot: Bot):
    if not is_allowed(message.from_user.id): return
    cur = await state.get_state()
    if cur: return
    photo = message.photo[-1]
    path = await download_tg_file(bot, photo.file_id, UPLOAD_DIR / "photos", ".jpg")
    if not path:
        await message.answer("❌ خطا در ذخیره عکس"); return
    title = f"عکس {format_jalali(jdatetime.date.today())}"
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as c:
        await c.execute(
            "INSERT INTO photos (user_id, file_id, file_path, title, created_at) VALUES (?,?,?,?,?)",
            (message.from_user.id, photo.file_id, str(path), title, now)
        )
        await c.commit()
    await message.answer("🖼 عکس ذخیره شد ♡")


# ============================================================
# SCHEDULER
# ============================================================
scheduler: Optional[AsyncIOScheduler] = None


async def send_scheduled(bot: Bot, msg_type: str, theme: str):
    today = jdatetime.date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as c:
        cur = await c.execute(
            "SELECT id FROM scheduled_messages WHERE msg_type=? AND sent_date=?",
            (msg_type, today)
        )
        if await cur.fetchone():
            logger.info("Already sent %s for %s", msg_type, today)
            return
    s = await get_settings()
    if msg_type == "morning" and not s.get("morning_msg_enabled"):
        return
    if msg_type == "evening" and not s.get("evening_msg_enabled"):
        return
    text = await generate_love_message(theme)
    targets = [u for u in ALLOWED_USERS if u != ADMIN_ID] or [ALLOWED_USER_ID]
    for uid in targets:
        try:
            await bot.send_message(uid, f"{'☀️' if msg_type=='morning' else '🌙'} {text}")
        except Exception as e:
            logger.error("send scheduled error to %s: %s", uid, e)
            await log_error("scheduled", f"{msg_type} -> {uid}: {e}")
    async with aiosqlite.connect(DB_PATH) as c:
        try:
            await c.execute(
                "INSERT INTO scheduled_messages (msg_type, sent_date, status, created_at) VALUES (?,?,?,?)",
                (msg_type, today, "sent", datetime.now().isoformat())
            )
            await c.commit()
        except aiosqlite.IntegrityError:
            pass


def setup_scheduler(bot: Bot):
    global scheduler
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        send_scheduled, CronTrigger(hour=6, minute=0),
        args=[bot, "morning", "morning"], id="morning_msg",
        replace_existing=True, misfire_grace_time=3600
    )
    scheduler.add_job(
        send_scheduled, CronTrigger(hour=0, minute=0),
        args=[bot, "evening", "evening"], id="evening_msg",
        replace_existing=True, misfire_grace_time=3600
    )
    scheduler.start()
    logger.info("Scheduler started (tz=%s)", TIMEZONE)


# ============================================================
# WEB API (for Mini App)
# ============================================================
async def api_auth(request):
    user = request["tg_user"]
    tg_id = request["tg_user_id"]
    await ensure_user(tg_id, user.get("username"), user.get("first_name"))
    return web.json_response({
        "ok": True,
        "user": {
            "id": tg_id,
            "username": user.get("username"),
            "first_name": user.get("first_name"),
            "is_admin": tg_id == ADMIN_ID,
        }
    })


async def api_counter(request):
    s = await get_settings()
    rel = calculate_relationship(s.get("start_date", jdatetime.date.today().isoformat()))
    async with aiosqlite.connect(DB_PATH) as c:
        cm = await (await c.execute("SELECT COUNT(*) FROM memories WHERE user_id=?", (request["tg_user_id"],))).fetchone()
        cp = await (await c.execute("SELECT COUNT(*) FROM photos WHERE user_id=?", (request["tg_user_id"],))).fetchone()
        cv = await (await c.execute("SELECT COUNT(*) FROM voices WHERE user_id=?", (request["tg_user_id"],))).fetchone()
    events = await get_upcoming_events(5)
    # Memory of the day: latest
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute(
            "SELECT id, title, text, memory_date FROM memories WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
            (request["tg_user_id"],)
        )
        mem = await cur.fetchone()
    return web.json_response({
        "ok": True,
        "counter": rel,
        "stats": {"memories": cm[0], "photos": cp[0], "voices": cv[0]},
        "events": events,
        "memory_of_day": dict(mem) if mem else None,
    })


async def api_memories(request):
    uid = request["tg_user_id"]
    q = request.rel_url.query.get("q", "").strip()
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        if q:
            cur = await c.execute(
                "SELECT id, title, text, memory_date, created_at FROM memories WHERE user_id=? AND (title LIKE ? OR text LIKE ?) ORDER BY created_at DESC",
                (uid, f"%{q}%", f"%{q}%")
            )
        else:
            cur = await c.execute(
                "SELECT id, title, text, memory_date, created_at FROM memories WHERE user_id=? ORDER BY created_at DESC",
                (uid,)
            )
        rows = await cur.fetchall()
    return web.json_response({"ok": True, "items": [dict(r) for r in rows]})


async def api_memory_get(request):
    uid = request["tg_user_id"]
    mid = int(request.match_info["id"])
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT * FROM memories WHERE id=? AND user_id=?", (mid, uid))
        m = await cur.fetchone()
    if not m:
        return web.json_response({"ok": False, "error": "not found"}, status=404)
    return web.json_response({"ok": True, "item": dict(m)})


async def api_memory_post(request):
    uid = request["tg_user_id"]
    data = await request.json()
    title = (data.get("title") or "").strip()
    text = (data.get("text") or "").strip()
    memory_date = data.get("memory_date") or format_jalali(jdatetime.date.today())
    if not title:
        return web.json_response({"ok": False, "error": "title required"}, status=400)
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as c:
        cur = await c.execute(
            """INSERT INTO memories (user_id, title, text, memory_date, created_at, updated_at)
               VALUES (?,?,?,?,?,?)""",
            (uid, title, text, memory_date, now, now)
        )
        mid = cur.lastrowid
        await c.commit()
    return web.json_response({"ok": True, "id": mid})


async def api_memory_put(request):
    uid = request["tg_user_id"]
    mid = int(request.match_info["id"])
    data = await request.json()
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT id FROM memories WHERE id=? AND user_id=?", (mid, uid))
        if not await cur.fetchone():
            return web.json_response({"ok": False, "error": "not found"}, status=404)
        sets, vals = [], []
        for k in ("title", "text", "memory_date"):
            if k in data:
                sets.append(f"{k}=?")
                vals.append(data[k])
        if not sets:
            return web.json_response({"ok": False, "error": "no fields"}, status=400)
        sets.append("updated_at=?")
        vals.append(datetime.now().isoformat())
        vals.append(mid)
        await c.execute(f"UPDATE memories SET {', '.join(sets)} WHERE id=?", vals)
        await c.commit()
    return web.json_response({"ok": True})


async def api_memory_delete(request):
    uid = request["tg_user_id"]
    mid = int(request.match_info["id"])
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT photo_path, voice_path FROM memories WHERE id=? AND user_id=?", (mid, uid))
        m = await cur.fetchone()
        if not m:
            return web.json_response({"ok": False, "error": "not found"}, status=404)
        for p in (m["photo_path"], m["voice_path"]):
            if p and is_safe_path(Path(p)):
                try: Path(p).unlink(missing_ok=True)
                except Exception: pass
        await c.execute("DELETE FROM memories WHERE id=?", (mid,))
        await c.commit()
    return web.json_response({"ok": True})


async def api_gallery(request):
    uid = request["tg_user_id"]
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute(
            "SELECT id, title, description, created_at FROM photos WHERE user_id=? ORDER BY created_at DESC",
            (uid,)
        )
        rows = await cur.fetchall()
    return web.json_response({"ok": True, "items": [dict(r) for r in rows]})


async def api_gallery_post(request):
    uid = request["tg_user_id"]
    reader = await request.multipart()
    title = description = ""
    photo_data = None
    filename = "photo.jpg"
    while True:
        part = await reader.next()
        if part is None: break
        if part.name == "photo":
            photo_data = await part.read(decode=False)
            filename = part.filename or "photo.jpg"
        elif part.name == "title":
            title = ((await part.read(decode=False)) or b"").decode("utf-8", "ignore").strip()
        elif part.name == "description":
            description = ((await part.read(decode=False)) or b"").decode("utf-8", "ignore").strip()
    if not photo_data:
        return web.json_response({"ok": False, "error": "no photo"}, status=400)
    if len(photo_data) > MAX_PHOTO_SIZE:
        return web.json_response({"ok": False, "error": "too large"}, status=400)
    ext = Path(filename).suffix or ".jpg"
    name = safe_filename(ext)
    out = UPLOAD_DIR / "photos" / name
    out.write_bytes(photo_data)
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as c:
        cur = await c.execute(
            "INSERT INTO photos (user_id, file_path, title, description, created_at) VALUES (?,?,?,?,?)",
            (uid, str(out), title or name, description, now)
        )
        pid = cur.lastrowid
        await c.commit()
    return web.json_response({"ok": True, "id": pid})


async def api_gallery_delete(request):
    uid = request["tg_user_id"]
    pid = int(request.match_info["id"])
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT file_path FROM photos WHERE id=? AND user_id=?", (pid, uid))
        p = await cur.fetchone()
        if not p:
            return web.json_response({"ok": False, "error": "not found"}, status=404)
        if p["file_path"] and is_safe_path(Path(p["file_path"])):
            try: Path(p["file_path"]).unlink(missing_ok=True)
            except Exception: pass
        await c.execute("DELETE FROM photos WHERE id=?", (pid,))
        await c.commit()
    return web.json_response({"ok": True})


async def api_file(request):
    """Serve uploaded files with auth check."""
    uid = request["tg_user_id"]
    kind = request.match_info["kind"]  # photos or voices
    fid = int(request.match_info["id"])
    table = "photos" if kind == "photos" else "voices"
    col = "file_path"
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute(f"SELECT {col}, user_id FROM {table} WHERE id=?", (fid,))
        row = await cur.fetchone()
    if not row or row["user_id"] != uid:
        # admin can view any
        if request["tg_user_id"] != ADMIN_ID:
            return web.json_response({"ok": False, "error": "forbidden"}, status=403)
    path = Path(row[col])
    if not is_safe_path(path) or not path.exists():
        return web.json_response({"ok": False, "error": "missing"}, status=404)
    ct = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return web.FileResponse(path, headers={"Content-Type": ct})


async def api_voices(request):
    uid = request["tg_user_id"]
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute(
            "SELECT id, title, duration, created_at FROM voices WHERE user_id=? ORDER BY created_at DESC",
            (uid,)
        )
        rows = await cur.fetchall()
    return web.json_response({"ok": True, "items": [dict(r) for r in rows]})


async def api_voices_post(request):
    uid = request["tg_user_id"]
    reader = await request.multipart()
    title = ""
    voice_data = None
    filename = "voice.ogg"
    duration = None
    while True:
        part = await reader.next()
        if part is None: break
        if part.name == "voice":
            voice_data = await part.read(decode=False)
            filename = part.filename or "voice.ogg"
        elif part.name == "title":
            title = ((await part.read(decode=False)) or b"").decode("utf-8", "ignore").strip()
        elif part.name == "duration":
            try: duration = int(((await part.read(decode=False)) or b"0").decode())
            except Exception: duration = None
    if not voice_data:
        return web.json_response({"ok": False, "error": "no voice"}, status=400)
    if len(voice_data) > MAX_VOICE_SIZE:
        return web.json_response({"ok": False, "error": "too large"}, status=400)
    ext = Path(filename).suffix or ".ogg"
    name = safe_filename(ext)
    out = UPLOAD_DIR / "voices" / name
    out.write_bytes(voice_data)
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as c:
        cur = await c.execute(
            "INSERT INTO voices (user_id, file_path, title, duration, created_at) VALUES (?,?,?,?,?)",
            (uid, str(out), title or name, duration, now)
        )
        vid = cur.lastrowid
        await c.commit()
    return web.json_response({"ok": True, "id": vid})


async def api_voices_delete(request):
    uid = request["tg_user_id"]
    vid = int(request.match_info["id"])
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT file_path FROM voices WHERE id=? AND user_id=?", (vid, uid))
        v = await cur.fetchone()
        if not v:
            return web.json_response({"ok": False, "error": "not found"}, status=404)
        if v["file_path"] and is_safe_path(Path(v["file_path"])):
            try: Path(v["file_path"]).unlink(missing_ok=True)
            except Exception: pass
        await c.execute("DELETE FROM voices WHERE id=?", (vid,))
        await c.commit()
    return web.json_response({"ok": True})


async def api_letters(request):
    uid = request["tg_user_id"]
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute(
            "SELECT id, title, text, is_read, created_at FROM letters WHERE to_user_id=? ORDER BY created_at DESC",
            (uid,)
        )
        rows = await cur.fetchall()
    return web.json_response({"ok": True, "items": [dict(r) for r in rows]})


async def api_letters_read(request):
    uid = request["tg_user_id"]
    lid = int(request.match_info["id"])
    async with aiosqlite.connect(DB_PATH) as c:
        await c.execute("UPDATE letters SET is_read=1 WHERE id=? AND to_user_id=?", (lid, uid))
        await c.commit()
    return web.json_response({"ok": True})


async def api_events(request):
    events = await get_upcoming_events(20)
    return web.json_response({"ok": True, "items": events})


async def api_settings(request):
    s = await get_settings()
    return web.json_response({"ok": True, "settings": s})


async def api_settings_put(request):
    if request["tg_user_id"] != ADMIN_ID:
        return web.json_response({"ok": False, "error": "admin only"}, status=403)
    data = await request.json()
    allowed = {"start_date", "girl_day_date", "morning_msg_enabled", "evening_msg_enabled"}
    upd = {k: data[k] for k in data if k in allowed}
    if upd:
        await update_settings(**upd)
    return web.json_response({"ok": True})


async def handle_index(request):
    index_path = WEBAPP_DIR / "index.html"
    if index_path.exists():
        return web.FileResponse(index_path)
    return web.Response(text="Mini App not found", status=404)


def setup_routes(app: web.Application):
    app.router.add_get("/", handle_index)
    # Static files from webapp dir (css/js/assets if any)
    if WEBAPP_DIR.exists():
        app.router.add_static("/static/", path=str(WEBAPP_DIR), show_index=False)

    api = web.Application(middlewares=[])
    # Auth-required endpoints
    api.router.add_post("/auth", api_auth)
    api.router.add_get("/counter", api_counter)
    api.router.add_get("/memories", api_memories)
    api.router.add_post("/memories", api_memory_post)
    api.router.add_get("/memories/{id}", api_memory_get)
    api.router.add_put("/memories/{id}", api_memory_put)
    api.router.add_delete("/memories/{id}", api_memory_delete)
    api.router.add_get("/gallery", api_gallery)
    api.router.add_post("/gallery", api_gallery_post)
    api.router.add_delete("/gallery/{id}", api_gallery_delete)
    api.router.add_get("/voices", api_voices)
    api.router.add_post("/voices", api_voices_post)
    api.router.add_delete("/voices/{id}", api_voices_delete)
    api.router.add_get("/files/{kind}/{id}", api_file)
    api.router.add_get("/letters", api_letters)
    api.router.add_post("/letters/{id}/read", api_letters_read)
    api.router.add_get("/events", api_events)
    api.router.add_get("/settings", api_settings)
    api.router.add_put("/settings", api_settings_put)

    # Wrap all /api/* with auth
    async def auth_middleware(app, handler):
        async def middleware(request):
            init_data = request.headers.get("X-Telegram-Init-Data", "")
            user = validate_init_data(init_data, BOT_TOKEN)
            if not user:
                return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
            tg_id = int(user.get("id", 0))
            if tg_id not in ALLOWED_USERS:
                return web.json_response({"ok": False, "error": "forbidden"}, status=403)
            request["tg_user"] = user
            request["tg_user_id"] = tg_id
            await ensure_user(tg_id, user.get("username"), user.get("first_name"))
            return await handler(request)
        return middleware

    api.middlewares.append(auth_middleware)
    app.add_subapp("/api", api)


# ============================================================
# MAIN
# ============================================================
async def on_startup(app: web.Application):
    await init_db()
    bot: Bot = app["bot"]
    try:
        me = await bot.get_me()
        logger.info("Bot started as @%s (%s)", me.username, me.id)
    except Exception as e:
        logger.error("Bot get_me error: %s", e)
    setup_scheduler(bot)


async def on_cleanup(app: web.Application):
    if scheduler:
        scheduler.shutdown(wait=False)
    await app["bot"].session.close()


async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not set")
        sys.exit(1)

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    app = web.Application()
    app["bot"] = bot
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    setup_routes(app)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HOST, PORT)
    await site.start()
    logger.info("Web server listening on %s:%s", HOST, PORT)

    # Start polling
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")