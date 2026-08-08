"""
🚀 ULTIMATE ENTERPRISE TASK & PRODUCTIVITY SYSTEM — نسخه نهایی جامع
تمام ۱۸ قابلیت: تکرار واقعی، برنامه صبحگاهی، گزارش شبانه، هشدار ۱۰ دقیقه‌ای، Snooze،
تنظیمات شخصی، مدال‌های واقعی، چالش روزانه، زنجیره روزهای موفق، گزارش هفتگی، جستجو،
ویرایش از تلگرام، ۳ کار مهم روز، فوروارد=یادداشت، راهنما، بکاپ خودکار، پیام همگانی، گزارش خطا
"""
import asyncio
import csv
import io
import logging
import os
import re
import time as _time
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import aiosqlite
from aiohttp import web
import aiohttp_cors
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import (
    Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update,
    ReplyKeyboardMarkup, KeyboardButton, InputFile, WebAppInfo, MenuButtonWebApp
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)

# ═══ CONFIG ═══
ADMIN_ID = 7681488759
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8322904493:AAFMyY-sB__S8s3f5DiTfaq6jm5lbrydH34")
DB_PATH = "ultimate_productivity.db"
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://bot-kqte.onrender.com")
POMO_SECONDS = int(os.environ.get("POMO_SECONDS", str(25 * 60)))
CHALLENGE_TARGET = 3
TZ = ZoneInfo("Asia/Tehran")
WEEKDAYS_FA = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

def now_local() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None)

ACHIEVEMENTS = [
    ("first_task", "🥇 قدم اول", "اولین کار را انجام بده"),
    ("ten_tasks", "💎 شکارچی کارها", "۱۰ کار انجام بده"),
    ("fifty_tasks", "🏆 حرفه‌ای", "۵۰ کار انجام بده"),
    ("first_pomo", "🍅 اولین تمرکز", "اولین پومودورو را کامل کن"),
    ("ten_pomo", "🔥 استاد تمرکز", "۱۰ پومودورو کامل کن"),
    ("habit3", "🌱 عادت‌ساز", "۳ روز زنجیره روی یک عادت"),
    ("habit7", "🌳 درخت استمرار", "۷ روز زنجیره روی یک عادت"),
    ("streak3", "⚡ روزهای فعال", "۳ روز پشت‌سرهم با کار انجام‌شده"),
    ("level5", "👑 سطح پنج", "به سطح ۵ برس"),
    ("notes5", "📝 نویسنده", "۵ یادداشت ثبت کن"),
]

# ═══ UTILS ═══
def fa_to_en_digits(text: str) -> str:
    return text.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789'))

def parse_quick_add(text: str) -> dict:
    clean_text = fa_to_en_digits(text).replace("：", ":")
    category, priority, is_urgent, is_important, due_date = "Personal", "Medium", 0, 1, None
    cat_match = re.search(r'#(\w+)', clean_text)
    if cat_match:
        tag = cat_match.group(1).lower()
        if tag in ["کاری", "work", "کار", "شغلی"]: category = "Work"
        elif tag in ["تحصیلی", "study", "درس", "دانشگاه", "مدرسه"]: category = "Study"
        elif tag in ["شخصی", "personal", "خودم"]: category = "Personal"
        clean_text = re.sub(r'#\w+', '', clean_text)
    pri_match = re.search(r'!(\w+)', clean_text)
    if pri_match:
        p_str = pri_match.group(1).lower()
        if p_str in ["ضروری", "فوری", "بالا", "high", "مهم"]:
            priority, is_urgent, is_important = "High", 1, 1
        elif p_str in ["کم", "پایین", "low"]:
            priority, is_urgent, is_important = "Low", 0, 0
        clean_text = re.sub(r'!\w+', '', clean_text)
    time_match = re.search(r'@(\d{1,2}:\d{2})', clean_text)
    now = now_local()
    if time_match:
        try:
            h, m = map(int, time_match.group(1).split(":"))
            if 0 <= h <= 23 and 0 <= m <= 59:
                target = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if target <= now: target += timedelta(days=1)
                due_date = target.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass
        clean_text = re.sub(r'@\d{1,2}:\d{2}', '', clean_text)
    title = clean_text.strip()
    return {"title": title if title else text, "category": category, "priority": priority,
            "is_urgent": is_urgent, "is_important": is_important, "due_date": due_date}

# ═══ DATABASE ═══
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, title TEXT NOT NULL,
            description TEXT DEFAULT '', category TEXT DEFAULT 'Personal', priority TEXT DEFAULT 'Medium',
            is_urgent INTEGER DEFAULT 0, is_important INTEGER DEFAULT 1, due_date TEXT,
            recurrence TEXT DEFAULT 'None', status TEXT DEFAULT 'pending', pomodoros INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')), done_at TEXT, snoozed_until TEXT)""")
        try:
            await db.execute("ALTER TABLE tasks ADD COLUMN snoozed_until TEXT")
        except Exception:
            pass
        await db.execute("""CREATE TABLE IF NOT EXISTS subtasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL, title TEXT NOT NULL, is_done INTEGER DEFAULT 0)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, title TEXT NOT NULL,
            streak INTEGER DEFAULT 0, last_done TEXT)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, first_name TEXT, username TEXT, xp INTEGER DEFAULT 0, level INTEGER DEFAULT 1)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, content TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS settings (
            user_id INTEGER PRIMARY KEY, morning_hour TEXT DEFAULT '08:00', evening_hour TEXT DEFAULT '21:00',
            last_morning_date TEXT DEFAULT '', last_evening_date TEXT DEFAULT '', last_weekly TEXT DEFAULT '')""")
        await db.execute("""CREATE TABLE IF NOT EXISTS daily_stats (
            user_id INTEGER NOT NULL, date TEXT NOT NULL, done_count INTEGER DEFAULT 0,
            xp_gained INTEGER DEFAULT 0, pomo_count INTEGER DEFAULT 0, challenge_claimed INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, date))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS achievements (
            user_id INTEGER NOT NULL, key TEXT NOT NULL, unlocked_at TEXT, PRIMARY KEY (user_id, key))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS mit (
            user_id INTEGER NOT NULL, task_id INTEGER NOT NULL, date TEXT NOT NULL, PRIMARY KEY (user_id, task_id, date))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)""")
        await db.commit()

async def kv_get(key):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM kv WHERE key=?", (key,)) as c:
            r = await c.fetchone()
            return r[0] if r else None

async def kv_set(key, value):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        await db.commit()

async def db_add_note(user_id, content):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO notes (user_id, content) VALUES (?, ?)", (user_id, content))
        await db.commit()

async def db_get_notes(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM notes WHERE user_id=? ORDER BY id DESC LIMIT 20", (user_id,)) as c:
            return [dict(r) for r in await c.fetchall()]

async def db_delete_note(note_id, user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM notes WHERE id=? AND user_id=?", (note_id, user_id))
        await db.commit()

async def db_upsert_user(user_id, first_name, username):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""INSERT INTO users (user_id, first_name, username) VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET first_name=excluded.first_name, username=excluded.username""",
            (user_id, first_name, username))
        await db.commit()

async def db_add_task(user_id, title, description="", category="Personal", priority="Medium",
                      due_date=None, recurrence="None", is_urgent=0, is_important=1):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""INSERT INTO tasks
            (user_id, title, description, category, priority, due_date, recurrence, is_urgent, is_important)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (user_id, title, description, category, priority, due_date, recurrence, is_urgent, is_important))
        await db.commit()
        return cur.lastrowid

async def db_update_task(task_id, title, description="", category="Personal", priority="Medium",
                         due_date=None, is_urgent=0, is_important=1):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""UPDATE tasks SET title=?, description=?, category=?, priority=?, due_date=?,
            is_urgent=?, is_important=? WHERE id=?""",
            (title, description, category, priority, due_date, is_urgent, is_important, task_id))
        await db.commit()

async def db_get_tasks(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE user_id=? AND status IN ('pending','doing') ORDER BY due_date ASC NULLS LAST, id DESC", (user_id,)) as c:
            return [dict(r) for r in await c.fetchall()]

async def db_get_done_tasks(user_id, limit=20):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE user_id=? AND status='done' ORDER BY done_at DESC LIMIT ?", (user_id, limit)) as c:
            return [dict(r) for r in await c.fetchall()]

async def db_get_task(task_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)) as c:
            row = await c.fetchone()
            return dict(row) if row else None

async def db_mark_done(task_id):
    now = now_local().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tasks SET status='done', done_at=? WHERE id=?", (now, task_id))
        await db.commit()

async def db_delete_task(task_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        await db.execute("DELETE FROM subtasks WHERE task_id=?", (task_id,))
        await db.commit()

async def db_increment_pomo(task_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tasks SET pomodoros = pomodoros + 1 WHERE id=?", (task_id,))
        await db.commit()

async def db_get_due_tasks():
    now = now_local().strftime("%Y-%m-%d %H:%M")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE status='pending' AND due_date IS NOT NULL AND due_date<=? AND (snoozed_until IS NULL OR snoozed_until<=?)", (now, now)) as c:
            return [dict(r) for r in await c.fetchall()]

async def db_get_pre_due_tasks():
    now = now_local()
    a = now.strftime("%Y-%m-%d %H:%M")
    b = (now + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE status='pending' AND due_date>? AND due_date<=? AND (snoozed_until IS NULL OR snoozed_until<=?)", (a, b, a)) as c:
            return [dict(r) for r in await c.fetchall()]

async def db_snooze(task_id, minutes=10):
    until = (now_local() + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tasks SET snoozed_until=? WHERE id=?", (until, task_id))
        await db.commit()

async def db_add_subtask(task_id, title):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO subtasks (task_id, title) VALUES (?, ?)", (task_id, title))
        await db.commit()

async def db_get_subtasks(task_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM subtasks WHERE task_id=?", (task_id,)) as c:
            return [dict(r) for r in await c.fetchall()]

async def db_toggle_subtask(subtask_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE subtasks SET is_done = 1 - is_done WHERE id=?", (subtask_id,))
        await db.commit()

async def db_add_habit(user_id, title):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO habits (user_id, title) VALUES (?, ?)", (user_id, title))
        await db.commit()

async def db_get_habits(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM habits WHERE user_id=?", (user_id,)) as c:
            return [dict(r) for r in await c.fetchall()]

async def db_checkin_habit(habit_id):
    today = now_local().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE habits SET streak = streak + 1, last_done=? WHERE id=?", (today, habit_id))
        await db.commit()

async def db_delete_habit(habit_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM habits WHERE id=?", (habit_id,))
        await db.commit()

# --- SETTINGS / DAILY STATS / MIT ---
async def db_get_setting(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM settings WHERE user_id=?", (uid,)) as c:
            row = await c.fetchone()
        if not row:
            await db.execute("INSERT INTO settings(user_id) VALUES(?)", (uid,))
            await db.commit()
            return {"user_id": uid, "morning_hour": "08:00", "evening_hour": "21:00",
                    "last_morning_date": "", "last_evening_date": "", "last_weekly": ""}
        return dict(row)

async def db_set_setting(uid, **kw):
    sets = ", ".join(f"{k}=?" for k in kw)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE settings SET {sets} WHERE user_id=?", (*kw.values(), uid))
        await db.commit()

async def db_bump_daily(uid, field, amount=1):
    today = now_local().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO daily_stats(user_id,date) VALUES(?,?) ON CONFLICT(user_id,date) DO NOTHING", (uid, today))
        await db.execute(f"UPDATE daily_stats SET {field}={field}+? WHERE user_id=? AND date=?", (amount, uid, today))
        await db.commit()

async def db_get_daily(uid, date):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM daily_stats WHERE user_id=? AND date=?", (uid, date)) as c:
            row = await c.fetchone()
            return dict(row) if row else None

async def db_toggle_mit(uid, task_id):
    today = now_local().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM mit WHERE user_id=? AND task_id=? AND date=?", (uid, task_id, today)) as c:
            if await c.fetchone():
                await db.execute("DELETE FROM mit WHERE user_id=? AND task_id=? AND date=?", (uid, task_id, today))
                await db.commit()
                return "removed"
        async with db.execute("SELECT COUNT(*) FROM mit WHERE user_id=? AND date=?", (uid, today)) as c:
            if (await c.fetchone())[0] >= 3:
                return "full"
        await db.execute("INSERT INTO mit(user_id,task_id,date) VALUES(?,?,?)", (uid, task_id, today))
        await db.commit()
        return "added"

async def db_get_mit(uid, date):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT t.* FROM mit m JOIN tasks t ON t.id=m.task_id WHERE m.user_id=? AND m.date=? AND t.status='pending'", (uid, date)) as c:
            return [dict(r) for r in await c.fetchall()]

async def calc_day_streak(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT date FROM daily_stats WHERE user_id=? AND done_count>0", (uid,)) as c:
            dates = {r[0] for r in await c.fetchall()}
    if not dates:
        return 0
    d = now_local().date()
    if d.isoformat() not in dates:
        d -= timedelta(days=1)
    n = 0
    while d.isoformat() in dates:
        n += 1
        d -= timedelta(days=1)
    return n

# --- GAMIFICATION ---
async def db_add_xp(user_id, amount):
    await db_bump_daily(user_id, "xp_gained", amount)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT xp, level FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            await db.execute("INSERT INTO users (user_id, xp, level) VALUES (?, ?, ?)", (user_id, amount, 1))
            await db.commit()
            return {"xp": amount, "level": 1, "leveled_up": False}
        current_xp = row[0] + amount
        new_lvl = (current_xp // 100) + 1
        leveled_up = new_lvl > row[1]
        await db.execute("UPDATE users SET xp=?, level=? WHERE user_id=?", (current_xp, new_lvl, user_id))
        await db.commit()
        return {"xp": current_xp, "level": new_lvl, "leveled_up": leveled_up}

async def check_challenge(uid):
    today = now_local().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT done_count, challenge_claimed FROM daily_stats WHERE user_id=? AND date=?", (uid, today)) as c:
            row = await c.fetchone()
        if row and row[0] >= CHALLENGE_TARGET and not row[1]:
            await db.execute("UPDATE daily_stats SET challenge_claimed=1 WHERE user_id=? AND date=?", (uid, today))
            await db.commit()
    if row and row[0] >= CHALLENGE_TARGET and not row[1]:
        await db_add_xp(uid, 50)
        return "🎯 <b>چالش روزانه کامل شد! (+50 XP جایزه)</b>"
    return None

async def check_achievements(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM tasks WHERE user_id=? AND status='done'", (uid,)) as c: done = (await c.fetchone())[0]
        async with db.execute("SELECT COALESCE(SUM(pomodoros),0) FROM tasks WHERE user_id=?", (uid,)) as c: pomo = (await c.fetchone())[0]
        async with db.execute("SELECT COALESCE(MAX(streak),0) FROM habits WHERE user_id=?", (uid,)) as c: hmax = (await c.fetchone())[0]
        async with db.execute("SELECT level FROM users WHERE user_id=?", (uid,)) as c:
            r = await c.fetchone(); lvl = r[0] if r else 1
        async with db.execute("SELECT COUNT(*) FROM notes WHERE user_id=?", (uid,)) as c: ncount = (await c.fetchone())[0]
        async with db.execute("SELECT key FROM achievements WHERE user_id=?", (uid,)) as c: have = {r[0] for r in await c.fetchall()}
    st = await calc_day_streak(uid)
    cond = {"first_task": done >= 1, "ten_tasks": done >= 10, "fifty_tasks": done >= 50,
            "first_pomo": pomo >= 1, "ten_pomo": pomo >= 10, "habit3": hmax >= 3, "habit7": hmax >= 7,
            "streak3": st >= 3, "level5": lvl >= 5, "notes5": ncount >= 5}
    msgs = []
    for key, title, desc in ACHIEVEMENTS:
        if cond.get(key) and key not in have:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("INSERT OR IGNORE INTO achievements(user_id,key,unlocked_at) VALUES(?,?,?)",
                                 (uid, key, now_local().strftime("%Y-%m-%d %H:%M")))
                await db.commit()
            msgs.append(f"🏅 <b>مدال جدید باز شد:</b> {title} — <i>{desc}</i>")
    return msgs

async def complete_task(tid, uid):
    task = await db_get_task(tid)
    if not task or task["status"] == "done":
        return None
    await db_mark_done(tid)
    res = await db_add_xp(uid, 20)
    await db_bump_daily(uid, "done_count")
    extra = []
    ch = await check_challenge(uid)
    if ch:
        extra.append(ch)
    if task.get("recurrence") == "Daily":
        nd = None
        if task.get("due_date"):
            try:
                nd = (datetime.strptime(task["due_date"], "%Y-%m-%d %H:%M") + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
            except Exception:
                nd = None
        await db_add_task(uid, task["title"], task.get("description", ""), task.get("category", "Personal"),
                          task.get("priority", "Medium"), nd, "Daily", task.get("is_urgent", 0), task.get("is_important", 1))
        extra.append("🔁 <b>نمونه فردای این کار به‌صورت خودکار ساخته شد.</b>")
    extra.extend(await check_achievements(uid))
    return {"res": res, "extra": extra}

# --- ADMIN / EXPORT ---
async def db_get_admin_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c: total_users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM tasks") as c: total_tasks = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM tasks WHERE status='done'") as c: done_tasks = (await c.fetchone())[0]
    return {"total_users": total_users, "total_tasks": total_tasks, "done_tasks": done_tasks}

async def db_get_users_list(page=1, per_page=5):
    offset = (page - 1) * per_page
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, first_name, username, level, xp FROM users LIMIT ? OFFSET ?", (per_page, offset)) as c:
            users = await c.fetchall()
        async with db.execute("SELECT COUNT(*) FROM users") as c: total = (await c.fetchone())[0]
    return users, total

async def db_get_user_full_details(target_user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id=?", (target_user_id,)) as c: user = await c.fetchone()
        async with db.execute("SELECT title, status, category FROM tasks WHERE user_id=? ORDER BY id DESC LIMIT 10", (target_user_id,)) as c:
            tasks = await c.fetchall()
    return user, tasks

async def db_get_user_profile(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT xp, level FROM users WHERE user_id=?", (user_id,)) as c: row = await c.fetchone()
    if not row:
        return {"xp": 0, "level": 1, "badge": "🌱 تازه کار"}
    xp, lvl = row[0], row[1]
    badges = {1: "🌱 تازه کار", 2: "⚡ فعال و باانگیزه", 3: "🔥 استاد تمرکز", 4: "🏆 قهرمان برنامه‌ریزی", 5: "👑 اسطوره استمرار و بازدهی"}
    return {"xp": xp, "level": lvl, "badge": badges.get(lvl, "👑 اسطوره استمرار")}

async def db_export_csv(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE user_id=?", (user_id,)) as c: rows = await c.fetchall()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["ID", "Title", "Description", "Category", "Priority", "Urgent", "Important", "DueDate", "Status", "Pomodoros", "CreatedAt", "DoneAt"])
    for r in rows:
        w.writerow([r["id"], r["title"], r["description"], r["category"], r["priority"], r["is_urgent"],
                    r["is_important"], r["due_date"], r["status"], r["pomodoros"], r["created_at"], r["done_at"]])
    return out.getvalue()

# ═══ KEYBOARDS & UI ═══
def main_reply_keyboard(user_id=None):
    url = f"{WEBAPP_URL}?user_id={user_id}" if user_id else WEBAPP_URL
    kb = [
        [KeyboardButton("➕ افزودن کار جدید"), KeyboardButton("⚡ ثبت سریع کار")],
        [KeyboardButton("📋 کارهای فعال من"), KeyboardButton("🌐 وب‌اپ کارهای من", web_app=WebAppInfo(url=url))],
        [KeyboardButton("🍅 پومودورو تمرکز"), KeyboardButton("🌱 ردیاب عادت‌ها")],
        [KeyboardButton("📐 ماتریس آیزنهاور"), KeyboardButton("📝 دفترچه یادداشت Notion")],
        [KeyboardButton("🏆 پروفایل & مدال‌ها"), KeyboardButton("📊 گزارش CSV")],
        [KeyboardButton("✅ کارهای انجام‌شده"), KeyboardButton("🔍 جستجو")],
        [KeyboardButton("📌 ۳ کار مهم امروز"), KeyboardButton("⚙️ تنظیمات")],
        [KeyboardButton("❓ راهنما و آموزش")]
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def step_back_kb(back_target=None):
    row = []
    if back_target:
        row.append(InlineKeyboardButton("🔙 مرحله قبل", callback_data=f"goto:{back_target}"))
    row.append(InlineKeyboardButton("❌ انصراف", callback_data="cancel_flow"))
    return InlineKeyboardMarkup([row])

def fmt_task_advanced(t, subtasks=None):
    subtasks = subtasks or []
    pri_map = {"High": "🚨 ضروری (بالا)", "Medium": "🟡 معمولی", "Low": "🟢 کم اهمیت"}
    cat_map = {"Personal": "👤 شخصی", "Work": "💼 کاری", "Study": "📚 تحصیلی"}
    text = f"💎 <b>{t['title']}</b>\n───────────────────────\n"
    if t.get("description"):
        text += f"💬 <i>{t['description']}</i>\n\n"
    text += f"🏷 <b>دسته‌بندی:</b> {cat_map.get(t.get('category'), 'عمومی')}\n"
    text += f"🎯 <b>اولویت:</b> {pri_map.get(t.get('priority'), 'معمولی')}\n"
    u, i = t.get("is_urgent", 0), t.get("is_important", 1)
    if u and i: text += "📐 <b>آیزنهاور:</b> 🔥 فوری و مهم\n"
    elif not u and i: text += "📐 <b>آیزنهاور:</b> 📅 غیرفوری ولی مهم\n"
    elif u and not i: text += "📐 <b>آیزنهاور:</b> ⚡ فوری ولی کم‌اهمیت\n"
    else: text += "📐 <b>آیزنهاور:</b> 🟢 کم‌اهمیت و غیرفوری\n"
    if t.get("recurrence") == "Daily":
        text += "🔁 <b>تکرار:</b> روزانه\n"
    text += f"🍅 <b>پومودوروها:</b> <code>{t.get('pomodoros', 0)}</code>\n"
    if t.get("due_date"):
        text += f"⏰ <b>یادآوری:</b> <code>{t['due_date']}</code>\n"
    if subtasks:
        text += "\n<b>☑️ زیرکارها:</b>\n"
        for st in subtasks:
            text += f"{'✅' if st['is_done'] else '▫️'} {st['title']}\n"
    return text

def task_action_kb(task_id, subtasks=None):
    subtasks = subtasks or []
    buttons = [
        [InlineKeyboardButton("✅ انجام شد (+20 XP)", callback_data=f"done:{task_id}"),
         InlineKeyboardButton("🍅 پومودورو", callback_data=f"pomo_start:{task_id}")],
        [InlineKeyboardButton("➕ زیرکار", callback_data=f"add_sub:{task_id}"),
         InlineKeyboardButton("✏️ ویرایش", callback_data=f"edit:{task_id}"),
         InlineKeyboardButton("🗑 حذف", callback_data=f"del_task:{task_id}")],
        [InlineKeyboardButton("😴 ۱۰ دقیقه بعد", callback_data=f"snooze:{task_id}")]
    ]
    for st in subtasks:
        buttons.append([InlineKeyboardButton(f"{'✅' if st['is_done'] else '▫️'} {st['title']}", callback_data=f"toggle_sub:{st['id']}:{task_id}")])
    return InlineKeyboardMarkup(buttons)

# ═══ SCHEDULER ═══
scheduler = AsyncIOScheduler(timezone="Asia/Tehran")
_bot: Optional[Bot] = None
_notified, _pre_notified = set(), set()

async def check_due_notifications():
    if not _bot:
        return
    for t in await db_get_pre_due_tasks():
        if t["id"] in _pre_notified:
            continue
        _pre_notified.add(t["id"])
        try:
            await _bot.send_message(t["user_id"], f"⏳ <b>یادآوری:</b> تا «{t['title']}» کمتر از ۱۰ دقیقه مانده!", parse_mode="HTML")
        except Exception as e:
            log.error(e)
    for t in await db_get_due_tasks():
        if t["id"] in _notified:
            continue
        _notified.add(t["id"])
        try:
            subs = await db_get_subtasks(t["id"])
            await _bot.send_message(t["user_id"], "🔔 <b>زمان انجام این کار فرا رسید!</b>\n\n" + fmt_task_advanced(t, subs),
                                    parse_mode="HTML", reply_markup=task_action_kb(t["id"], subs))
        except Exception as e:
            log.error(e)

async def build_morning(uid):
    now = now_local()
    today = now.strftime("%Y-%m-%d")
    tasks = await db_get_tasks(uid)
    due_today = [t for t in tasks if (t["due_date"] or "").startswith(today)]
    mits = await db_get_mit(uid, today)
    st = await calc_day_streak(uid)
    text = f"🌅 <b>صبح بخیر! {WEEKDAYS_FA[now.weekday()]} {today}</b>\n───────────────────────\n"
    text += f"📋 کارهای فعال: <code>{len(tasks)}</code>"
    if due_today:
        text += f" | ⏰ سررسید امروز: <code>{len(due_today)}</code>"
    text += "\n"
    if mits:
        text += "\n📌 <b>۳ کار مهم امروز تو:</b>\n" + "\n".join(f"• {m['title']}" for m in mits) + "\n"
    else:
        text += "\n💡 <i>با دکمه «📌  کار مهم امروز» اولویت‌هایت را انتخاب کن.</i>\n"
    text += f"\n🎯 چالش امروز: {CHALLENGE_TARGET} کار انجام بده (+50 XP)\n"
    if st:
        text += f"🔥 زنجیره روزهای موفق: <code>{st}</code>\n"
    return text + "\nروزت پرانرژی! 💪"

async def build_evening(uid):
    today = now_local().strftime("%Y-%m-%d")
    d = await db_get_daily(uid, today) or {"done_count": 0, "xp_gained": 0, "pomo_count": 0}
    tasks = await db_get_tasks(uid)
    st = await calc_day_streak(uid)
    return (f"🌙 <b>گزارش شبانه — {today}</b>\n───────────────────────\n"
            f"✅ انجام‌شده امروز: <code>{d['done_count']}</code>\n📋 باقی‌مانده: <code>{len(tasks)}</code>\n"
            f"⚡ XP امروز: <code>{d['xp_gained']}</code>\n🍅 پومودورو امروز: <code>{d['pomo_count']}</code>\n"
            f"🔥 زنجیره: <code>{st}</code> روز\n\nخسته نباشی! فردا روز تازه‌ای است. 🌟")

async def build_weekly(uid):
    start = (now_local() - timedelta(days=6)).strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT date, done_count, xp_gained, pomo_count FROM daily_stats WHERE user_id=? AND date>=?", (uid, start)) as c:
            rows = [dict(r) for r in await c.fetchall()]
    td = sum(r["done_count"] for r in rows)
    tx = sum(r["xp_gained"] for r in rows)
    tp = sum(r["pomo_count"] for r in rows)
    best = max(rows, key=lambda r: r["done_count"])["date"] if rows and max(r["done_count"] for r in rows) > 0 else None
    return (f"📊 <b>گزارش هفتگی تو</b>\n───────────────────────\n"
            f"✅ کارهای انجام‌شده: <code>{td}</code>\n⚡ XP کسب‌شده: <code>{tx}</code>\n🍅 پومودورو: <code>{tp}</code>\n"
            f"🏆 بهترین روز: <code>{best or '—'}</code>\n\nهفته بعدی را قوی‌تر شروع کن! 🚀")

async def daily_jobs():
    if not _bot:
        return
    now = now_local()
    today = now.strftime("%Y-%m-%d")
    hhmm = now.strftime("%H:%M")
    if now.hour >= 2 and await kv_get("last_backup") != today:
        await kv_set("last_backup", today)
        try:
            with open(DB_PATH, "rb") as f:
                await _bot.send_document(ADMIN_ID, InputFile(f), caption="📦 بکاپ خودکار روزانه دیتابیس")
        except Exception as e:
            log.error(e)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM settings") as c:
            rows = [dict(r) for r in await c.fetchall()]
    for s in rows:
        uid = s["user_id"]
        try:
            if hhmm >= s["morning_hour"] and s["last_morning_date"] != today:
                await db_set_setting(uid, last_morning_date=today)
                await _bot.send_message(uid, await build_morning(uid), parse_mode="HTML", reply_markup=main_reply_keyboard(uid))
            if hhmm >= s["evening_hour"] and s["last_evening_date"] != today:
                await db_set_setting(uid, last_evening_date=today)
                await _bot.send_message(uid, await build_evening(uid), parse_mode="HTML", reply_markup=main_reply_keyboard(uid))
            wk = f"{now.isocalendar()[0]}-{now.isocalendar()[1]}"
            if now.weekday() == 4 and hhmm >= "18:00" and s["last_weekly"] != wk:
                await db_set_setting(uid, last_weekly=wk)
                await _bot.send_message(uid, await build_weekly(uid), parse_mode="HTML", reply_markup=main_reply_keyboard(uid))
        except Exception as e:
            log.error(f"Daily msg error: {e}")

def start_scheduler(bot):
    global _bot
    _bot = bot
    scheduler.add_job(check_due_notifications, "interval", seconds=15, id="_check_due", replace_existing=True)
    scheduler.add_job(daily_jobs, "interval", seconds=30, id="_daily_jobs", replace_existing=True)
    if not scheduler.running:
        scheduler.start()

# ═══ STATES ═══
ADD_TITLE, ADD_DESC, ADD_CAT, ADD_PRI, ADD_EISENHOWER, ADD_DUE, ADD_REC = range(7)
QUICK_ADD_STATE, ADD_SUBTASK_STATE, ADD_HABIT_STATE, ADD_NOTE_STATE = 7, 8, 9, 10
EDIT_TITLE, EDIT_DESC, EDIT_DUE, SET_MORNING, SET_EVENING, SEARCH_STATE, ADMIN_BROADCAST = range(11, 18)

# ═══ ADD TASK CONVERSATION ═══
async def _send_step(update, text, kb):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)

async def ask_title(update, ctx):
    await _send_step(update, "📝 <b>افزودن کار (۱/۶)</b> — عنوان کار را وارد کن:", step_back_kb(None))
    return ADD_TITLE

async def ask_desc(update, ctx):
    await _send_step(update, f"✅ عنوان: {ctx.user_data.get('title', '')}\n\n💬 <b>(۲/۶)</b> توضیحات را وارد کن یا /skip:", step_back_kb("title"))
    return ADD_DESC

async def ask_cat(update, ctx):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 شخصی", callback_data="cat:Personal"), InlineKeyboardButton("💼 کاری", callback_data="cat:Work")],
        [InlineKeyboardButton("📚 تحصیلی", callback_data="cat:Study")],
        [InlineKeyboardButton("🔙 مرحله قبل", callback_data="goto:desc"), InlineKeyboardButton("❌ انصراف", callback_data="cancel_flow")]])
    await _send_step(update, "🏷 <b>(۳/۶)</b> دسته‌بندی:", kb)
    return ADD_CAT

async def ask_pri(update, ctx):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚨 ضروری", callback_data="pri:High"), InlineKeyboardButton("🟡 معمولی", callback_data="pri:Medium")],
        [InlineKeyboardButton("🟢 کم اهمیت", callback_data="pri:Low")],
        [InlineKeyboardButton("🔙 مرحله قبل", callback_data="goto:cat"), InlineKeyboardButton("❌ انصراف", callback_data="cancel_flow")]])
    await _send_step(update, "🎯 <b>(۴/۶)</b> اولویت:", kb)
    return ADD_PRI

async def ask_eisen(update, ctx):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 فوری و مهم", callback_data="eisen:1:1"), InlineKeyboardButton("📅 غیرفوری ولی مهم", callback_data="eisen:0:1")],
        [InlineKeyboardButton("⚡ فوری کم‌اهمیت", callback_data="eisen:1:0"), InlineKeyboardButton("🟢 کم‌اهمیت غیرفوری", callback_data="eisen:0:0")],
        [InlineKeyboardButton("🔙 مرحله قبل", callback_data="goto:pri"), InlineKeyboardButton("❌ انصراف", callback_data="cancel_flow")]])
    await _send_step(update, "📐 <b>(۵/۶)</b> ماتریس آیزنهاور:", kb)
    return ADD_EISENHOWER

async def ask_due(update, ctx):
    await _send_step(update, "⏰ <b>(۶/۶)</b> ساعت یادآوری مثل <code>18:30</code> یا /skip:", step_back_kb("eisen"))
    return ADD_DUE

async def ask_rec(update, ctx):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 بدون تکرار", callback_data="rec:None"), InlineKeyboardButton("📅 روزانه (تکرار خودکار)", callback_data="rec:Daily")],
        [InlineKeyboardButton("🔙 مرحله قبل", callback_data="goto:due"), InlineKeyboardButton("❌ انصراف", callback_data="cancel_flow")]])
    await _send_step(update, "🔁 آیا این کار <b>تکرار خودکار</b> دارد؟", kb)
    return ADD_REC

async def add_start(update, ctx):
    ctx.user_data.clear()
    return await ask_title(update, ctx)

async def add_got_title(update, ctx):
    if update.message:
        ctx.user_data["title"] = update.message.text.strip()
    return await ask_desc(update, ctx)

async def add_got_desc(update, ctx):
    if update.message:
        ctx.user_data["description"] = "" if update.message.text.startswith("/skip") else update.message.text.strip()
    return await ask_cat(update, ctx)

async def add_got_cat(update, ctx):
    await update.callback_query.answer()
    ctx.user_data["category"] = update.callback_query.data.split(":")[1]
    return await ask_pri(update, ctx)

async def add_got_pri(update, ctx):
    await update.callback_query.answer()
    ctx.user_data["priority"] = update.callback_query.data.split(":")[1]
    return await ask_eisen(update, ctx)

async def add_got_eisenhower(update, ctx):
    await update.callback_query.answer()
    p = update.callback_query.data.split(":")
    ctx.user_data["is_urgent"], ctx.user_data["is_important"] = int(p[1]), int(p[2])
    return await ask_due(update, ctx)

async def add_got_due(update, ctx):
    if update.message:
        if not update.message.text.startswith("/skip"):
            raw = fa_to_en_digits(update.message.text.strip())
            try:
                h, m = map(int, raw.split(":"))
                if not (0 <= h <= 23 and 0 <= m <= 59):
                    raise ValueError
                now = now_local()
                target = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if target <= now:
                    target += timedelta(days=1)
                ctx.user_data["due_date"] = target.strftime("%Y-%m-%d %H:%M")
            except Exception:
                await update.message.reply_text("❌ فرمت ساعت اشتباه است! مثال: <code>18:30</code>", parse_mode="HTML", reply_markup=step_back_kb("eisen"))
                return ADD_DUE
        else:
            ctx.user_data["due_date"] = None
    return await ask_rec(update, ctx)

async def add_got_rec(update, ctx):
    q = update.callback_query
    await q.answer()
    rec = q.data.split(":")[1]
    uid = update.effective_user.id
    d = ctx.user_data
    tid = await db_add_task(uid, d["title"], d.get("description", ""), d.get("category", "Personal"),
                            d.get("priority", "Medium"), d.get("due_date"), rec, d.get("is_urgent", 0), d.get("is_important", 1))
    ctx.user_data.clear()
    task = await db_get_task(tid)
    await q.edit_message_text("🎉 <b>کار ثبت شد!</b>\n\n" + fmt_task_advanced(task), parse_mode="HTML")
    await check_achievements_notify(uid)
    await cmd_list(update, ctx)
    return ConversationHandler.END

async def check_achievements_notify(uid):
    if not _bot:
        return
    for m in await check_achievements(uid):
        try:
            await _bot.send_message(uid, m, parse_mode="HTML")
        except Exception:
            pass

# ═══ GENERAL COMMANDS ═══
async def cmd_start(update, _):
    user = update.effective_user
    await db_upsert_user(user.id, user.first_name, user.username)
    await db_get_setting(user.id)
    await update.message.reply_text(
        "🚀 <b>به دستیار شخصی پیشرفته خوش آمدی!</b>\n───────────────────────\n"
        "مدیریت کارها، عادت‌ها، پومودورو، آیزنهاور، یادداشت‌ها، مدال‌ها و چالش‌ها — همه در یک ربات.\n"
        "💡 <i>هر پیامی را فوروارد کنی، در یادداشت‌هایت ذخیره می‌شود!</i>",
        parse_mode="HTML", reply_markup=main_reply_keyboard(user.id))

async def cmd_cancel(update, ctx):
    ctx.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ عملیات لغو شد.")
    else:
        await update.message.reply_text("❌ عملیات لغو شد.", reply_markup=main_reply_keyboard())
    return ConversationHandler.END

async def cmd_help(update, _):
    await update.message.reply_text(
        "❓ <b>راهنمای کامل ربات</b>\n───────────────────────\n"
        "➕ افزودن کار جدید: ثبت ۶ مرحله‌ای با امکان بازگشت\n"
        "⚡ ثبت سریع: <code>تکمیل پروژه #کاری !ضروری @19:30</code>\n"
        "📋 کارهای فعال: لیست + دکمه‌های انجام/پومودورو/ویرایش/حذف\n"
        "😴 ۱۰ دقیقه بعد: به تعویق انداختن یادآوری\n"
        "📌 ۳ کار مهم امروز: انتخاب اولویت‌های روز\n"
        "🌱 عادت‌ها: ثبت روزانه و زنجیره استمرار\n"
        "🍅 پومودورو: ۲۵ دقیقه تمرکز واقعی با پیام پایان\n"
        "🏆 پروفایل: XP، سطح و مدال‌های واقعی\n"
        "🎯 چالش روزانه: ۳ کار = ۵۰ XP جایزه\n"
        "🌅 برنامه صبحگاهی / 🌙 گزارش شبانه / 📊 گزارش هفتگی (خودکار)\n"
        "⚙️ تنظیمات: تغییر ساعت پیام‌های خودکار\n"
        "🔍 جستجو: بین کارها و یادداشت‌ها\n"
        "📎 فوروارد هر پیام/عکس = ذخیره در یادداشت‌ها\n"
        "🔁 کارهای روزانه پس از انجام، فردا خودکار تکرار می‌شوند\n",
        parse_mode="HTML", reply_markup=main_reply_keyboard())

async def cmd_profile(update, _):
    uid = update.effective_user.id
    prof = await db_get_user_profile(uid)
    st = await calc_day_streak(uid)
    today = now_local().strftime("%Y-%m-%d")
    d = await db_get_daily(uid, today) or {"done_count": 0}
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT key FROM achievements WHERE user_id=?", (uid,)) as c:
            have = {r[0] for r in await c.fetchall()}
    text = (f"🏆 <b>پروفایل تو</b>\n───────────────────────\n"
            f"👤 سطح: <code>{prof['level']}</code> | 🎖 {prof['badge']}\n⚡ XP: <code>{prof['xp']}</code>\n"
            f"🔥 زنجیره روزهای موفق: <code>{st}</code>\n"
            f"🎯 چالش امروز: {d['done_count']}/{CHALLENGE_TARGET}\n\n<b>مدال‌ها:</b>\n")
    for key, title, desc in ACHIEVEMENTS:
        text += f"{'✅' if key in have else '🔒'} {title} — <i>{desc}</i>\n"
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_reply_keyboard())

async def cmd_export(update, _):
    uid = update.effective_user.id
    bio = io.BytesIO((await db_export_csv(uid)).encode('utf-8'))
    bio.name = f"tasks_export_{now_local().strftime('%Y%m%d')}.csv"
    await update.message.reply_document(InputFile(bio), caption="📄 فایل پشتیبان کارها آماده شد.", reply_markup=main_reply_keyboard())

async def cmd_list(update, ctx):
    uid = update.effective_user.id
    tasks = await db_get_tasks(uid)
    target = update.message if update.message else update.callback_query.message
    if not tasks:
        await target.reply_text("🎉 <b>هیچ کار فعالی نداری!</b>", parse_mode="HTML",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🌐 وب‌اپ", web_app=WebAppInfo(url=f"{WEBAPP_URL}?user_id={uid}"))]]))
        return
    await target.reply_text("📋 <b>کارهای فعال تو:</b>", parse_mode="HTML")
    for t in tasks:
        subs = await db_get_subtasks(t["id"])
        await target.reply_text(fmt_task_advanced(t, subs), parse_mode="HTML", reply_markup=task_action_kb(t["id"], subs))

async def cmd_done_list(update, _):
    done = await db_get_done_tasks(update.effective_user.id)
    if not done:
        await update.message.reply_text("📂 هنوز کاری تمام نشده.", reply_markup=main_reply_keyboard())
        return
    text = "✅ <b>انجام‌شده‌ها:</b>\n"
    for t in done:
        text += f"• <s>{t['title']}</s> <code>{(t['done_at'] or '')[:10]}</code>\n"
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_reply_keyboard())

# ═══ QUICK ADD / POMODORO / HABITS / EISENHOWER / NOTES / SUBTASKS ═══
async def quick_add_start(update, ctx):
    await update.message.reply_text("⚡ <b>ثبت سریع:</b> یک خط بنویس:\n<code>تکمیل پروژه #کاری !ضروری @19:30</code>", parse_mode="HTML", reply_markup=step_back_kb(None))
    return QUICK_ADD_STATE

async def quick_add_process(update, ctx):
    parsed = parse_quick_add(update.message.text)
    uid = update.effective_user.id
    tid = await db_add_task(uid, parsed["title"], category=parsed["category"], priority=parsed["priority"],
                            due_date=parsed["due_date"], is_urgent=parsed["is_urgent"], is_important=parsed["is_important"])
    await db_add_xp(uid, 10)
    task = await db_get_task(tid)
    await update.message.reply_text("🎉 <b>ثبت شد! (+10 XP)</b>\n\n" + fmt_task_advanced(task), parse_mode="HTML", reply_markup=main_reply_keyboard())
    for m in await check_achievements(uid):
        await update.message.reply_text(m, parse_mode="HTML")
    return ConversationHandler.END

async def cmd_pomo_info(update, _):
    await update.message.reply_text("🍅 <b>پومودورو:</b> از دکمه «🍅 پومودورو» زیر هر کار استفاده کن. جلسه ۲۵ دقیقه‌ای واقعی است و پایانش خودم خبرت می‌کنم!", parse_mode="HTML", reply_markup=main_reply_keyboard())

async def _pomo_finish(uid, tid):
    try:
        await asyncio.sleep(POMO_SECONDS)
        await db_increment_pomo(tid)
        await db_bump_daily(uid, "pomo_count")
        await db_add_xp(uid, 25)
        if _bot:
            await _bot.send_message(uid, "🎉 <b>جلسه پومودورو تمام شد! (+25 XP)</b> ☕ ۵ دقیقه استراحت کن.", parse_mode="HTML", reply_markup=main_reply_keyboard())
            for m in await check_achievements(uid):
                await _bot.send_message(uid, m, parse_mode="HTML")
    except Exception as e:
        log.error(e)

async def cb_pomo_start(update, _):
    q = update.callback_query
    await q.answer("🍅 شروع شد!")
    tid = int(q.data.split(":")[1])
    await q.edit_message_text(q.message.text + f"\n\n🍅 <b>تمرکز {POMO_SECONDS // 60} دقیقه‌ای شروع شد؛ پایان خبرت می‌دهم.</b>", parse_mode="HTML")
    asyncio.create_task(_pomo_finish(update.effective_user.id, tid))

async def cb_snooze(update, _):
    q = update.callback_query
    tid = int(q.data.split(":")[1])
    await db_snooze(tid, 10)
    _notified.discard(tid)
    await q.answer("😴 باش! ۱۰ دقیقه دیگر یادآوری می‌کنم.")
    await q.edit_message_text(q.message.text + "\n\n😴 <b>به ۱۰ دقیقه بعد موکول شد.</b>", parse_mode="HTML")

async def cmd_habits(update, _):
    uid = update.effective_user.id
    habits = await db_get_habits(uid)
    if not habits:
        await update.message.reply_text("🌱 <b>ردیاب عادت‌ها</b>\nعادتی نداری.", parse_mode="HTML",
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ تعریف عادت", callback_data="add_habit_btn")]]))
        return
    text = "🌱 <b>عادت‌های تو:</b>\n"
    kb = []
    for h in habits:
        text += f"• <b>{h['title']}</b> ➔ 🔥 <code>{h['streak']}</code> روز\n"
        kb.append([InlineKeyboardButton(f"✅ ثبت امروز: {h['title']}", callback_data=f"checkin_habit:{h['id']}"), InlineKeyboardButton("🗑", callback_data=f"del_habit:{h['id']}")])
    kb.append([InlineKeyboardButton("➕ تعریف عادت", callback_data="add_habit_btn")])
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def cb_add_habit_start(update, ctx):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("🌱 عنوان عادت جدید:")
    return ADD_HABIT_STATE

async def add_habit_process(update, ctx):
    await db_add_habit(update.effective_user.id, update.message.text.strip())
    await update.message.reply_text("🎉 عادت اضافه شد!", reply_markup=main_reply_keyboard())
    return ConversationHandler.END

async def cb_checkin_habit(update, _):
    q = update.callback_query
    uid = update.effective_user.id
    await db_checkin_habit(int(q.data.split(":")[1]))
    await db_add_xp(uid, 15)
    await q.answer("🔥 +15 XP")
    await q.edit_message_text(q.message.text + "\n\n✅ <b>استمرار ثبت شد!</b>", parse_mode="HTML")
    for m in await check_achievements(uid):
        await q.message.reply_text(m, parse_mode="HTML")

async def cb_del_habit(update, _):
    q = update.callback_query
    await db_delete_habit(int(q.data.split(":")[1]))
    await q.answer("🗑 حذف شد.")
    await q.delete_message()

async def cmd_eisenhower(update, _):
    tasks = await db_get_tasks(update.effective_user.id)
    q1 = [t['title'] for t in tasks if t['is_urgent'] and t['is_important']]
    q2 = [t['title'] for t in tasks if not t['is_urgent'] and t['is_important']]
    q3 = [t['title'] for t in tasks if t['is_urgent'] and not t['is_important']]
    q4 = [t['title'] for t in tasks if not t['is_urgent'] and not t['is_important']]
    def blk(a, t): return f"<b>{t}</b>\n" + ("\n".join(f"• {x}" for x in a) if a else "<i>خالی</i>") + "\n\n"
    await update.message.reply_text("📐 <b>ماتریس آیزنهاور</b>\n───────────────────────\n" +
        blk(q1, "🔥 ۱. فوری و مهم:") + blk(q2, "📅 . مهم غیرفوری:") + blk(q3, "⚡ ۳. فوری کم‌اهمیت:") + blk(q4, "🟢 ۴. غیرفوری کم‌اهمیت:"),
        parse_mode="HTML", reply_markup=main_reply_keyboard())

async def cmd_notes(update, _):
    uid = update.effective_user.id
    notes = await db_get_notes(uid)
    if not notes:
        await update.message.reply_text("📝 <b>یادداشت‌ها خالی است.</b>", parse_mode="HTML",
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ یادداشت جدید", callback_data="add_note_btn")]]))
        return
    text, kb = "📝 <b>یادداشت‌های تو:</b>\n", []
    for n in notes:
        text += f"▫️ {n['content']} <code>({n['created_at'][:10]})</code>\n"
        kb.append([InlineKeyboardButton(f"🗑 {n['content'][:20]}", callback_data=f"del_note:{n['id']}")])
    kb.append([InlineKeyboardButton("➕ یادداشت جدید", callback_data="add_note_btn")])
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def cb_add_note_start(update, ctx):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("📝 متن یادداشت:")
    return ADD_NOTE_STATE

async def add_note_process(update, ctx):
    await db_add_note(update.effective_user.id, update.message.text.strip())
    await update.message.reply_text("✅ ذخیره شد!", reply_markup=main_reply_keyboard())
    for m in await check_achievements(update.effective_user.id):
        await update.message.reply_text(m, parse_mode="HTML")
    return ConversationHandler.END

async def cb_del_note(update, _):
    q = update.callback_query
    await db_delete_note(int(q.data.split(":")[1]), q.from_user.id)
    await q.answer("🗑 حذف شد.")
    await q.delete_message()

async def save_forward(update, _):
    m = update.message
    content = m.text or m.caption or ("📷 عکس" if m.photo else "📎 فایل")
    await db_add_note(update.effective_user.id, f"📨 فوروارد: {content}")
    await m.reply_text("✅ در یادداشت‌هایت ذخیره شد!", reply_markup=main_reply_keyboard())

async def catch_all(update, _):
    m = update.message
    fwd = getattr(m, "forward_origin", None) is not None or getattr(m, "forward_date", None) is not None
    if fwd:
        await save_forward(update, _)
    else:
        await m.reply_text("🤔 متوجه نشدم! از دکمه‌های کیبورد استفاده کن یا /help را ببین.", reply_markup=main_reply_keyboard())

async def cb_add_subtask_start(update, ctx):
    q = update.callback_query
    await q.answer()
    ctx.user_data["target_task_id"] = int(q.data.split(":")[1])
    await q.message.reply_text("☑️ عنوان زیرکار:")
    return ADD_SUBTASK_STATE

async def add_subtask_process(update, ctx):
    await db_add_subtask(ctx.user_data.get("target_task_id"), update.message.text.strip())
    await update.message.reply_text("✅ زیرکار اضافه شد!", reply_markup=main_reply_keyboard())
    return ConversationHandler.END

async def cb_toggle_subtask(update, _):
    q = update.callback_query
    p = q.data.split(":")
    await db_toggle_subtask(int(p[1]))
    await q.answer("✔️")
    task = await db_get_task(int(p[2]))
    subs = await db_get_subtasks(int(p[2]))
    await q.edit_message_text(fmt_task_advanced(task, subs), parse_mode="HTML", reply_markup=task_action_kb(int(p[2]), subs))

async def cb_done_task(update, ctx):
    q = update.callback_query
    tid = int(q.data.split(":")[1])
    uid = update.effective_user.id
    out = await complete_task(tid, uid)
    if not out:
        await q.answer("قبلاً انجام شده.", show_alert=True)
        return
    msg = "✅ <b>انجام شد (+20 XP)!</b>"
    if out["res"].get("leveled_up"):
        msg += f"\n🎉 <b>ارتقاء به سطح {out['res']['level']}!</b>"
    if out["extra"]:
        msg += "\n" + "\n".join(out["extra"])
    await q.answer("✅")
    await q.edit_message_text(q.message.text + f"\n\n{msg}", parse_mode="HTML")

async def cb_del_task(update, _):
    q = update.callback_query
    await db_delete_task(int(q.data.split(":")[1]))
    await q.answer("🗑 حذف شد.")
    await q.delete_message()

# ═══ EDIT TASK ═══
async def cb_edit_menu(update, _):
    q = update.callback_query
    tid = int(q.data.split(":")[1])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 عنوان", callback_data=f"edit_f:title:{tid}"), InlineKeyboardButton("💬 توضیح", callback_data=f"edit_f:desc:{tid}")],
        [InlineKeyboardButton("🏷 دسته: شخصی", callback_data=f"edit_cat:{tid}:Personal"), InlineKeyboardButton("کاری", callback_data=f"edit_cat:{tid}:Work"), InlineKeyboardButton("تحصیلی", callback_data=f"edit_cat:{tid}:Study")],
        [InlineKeyboardButton("🎯 ضروری", callback_data=f"edit_pri:{tid}:High"), InlineKeyboardButton("معمولی", callback_data=f"edit_pri:{tid}:Medium"), InlineKeyboardButton("کم", callback_data=f"edit_pri:{tid}:Low")],
        [InlineKeyboardButton("⏰ ساعت یادآوری", callback_data=f"edit_f:due:{tid}")],
        [InlineKeyboardButton("🔙 بازگشت به کار", callback_data=f"edit_back:{tid}")]])
    await q.answer()
    await q.edit_message_text("✏️ <b>چه چیزی را ویرایش کنم؟</b>", parse_mode="HTML", reply_markup=kb)

async def cb_edit_back(update, _):
    q = update.callback_query
    tid = int(q.data.split(":")[1])
    task = await db_get_task(tid)
    subs = await db_get_subtasks(tid)
    await q.edit_message_text(fmt_task_advanced(task, subs), parse_mode="HTML", reply_markup=task_action_kb(tid, subs))

async def cb_edit_field(update, ctx):
    q = update.callback_query
    p = q.data.split(":")
    field, tid = p[1], int(p[2])
    ctx.user_data["edit_id"] = tid
    prompts = {"title": "📝 عنوان جدید را بفرست:", "desc": "💬 توضیح جدید را بفرست:", "due": "⏰ ساعت جدید مثل <code>18:30</code> بفرست:"}
    await q.answer()
    await q.message.reply_text(prompts[field], parse_mode="HTML")
    return {"title": EDIT_TITLE, "desc": EDIT_DESC, "due": EDIT_DUE}[field]

async def _apply_edit(update, ctx, field, value):
    tid = ctx.user_data.get("edit_id")
    t = await db_get_task(tid)
    if not t:
        return ConversationHandler.END
    if field == "title": t["title"] = value
    elif field == "desc": t["description"] = value
    elif field == "due": t["due_date"] = value
    await db_update_task(tid, t["title"], t.get("description", ""), t.get("category", "Personal"),
                         t.get("priority", "Medium"), t.get("due_date"), t.get("is_urgent", 0), t.get("is_important", 1))
    task = await db_get_task(tid)
    subs = await db_get_subtasks(tid)
    await update.message.reply_text("✅ <b>ویرایش شد:</b>\n\n" + fmt_task_advanced(task, subs), parse_mode="HTML", reply_markup=task_action_kb(tid, subs))
    return ConversationHandler.END

async def got_edit_title(update, ctx):
    return await _apply_edit(update, ctx, "title", update.message.text.strip())

async def got_edit_desc(update, ctx):
    return await _apply_edit(update, ctx, "desc", update.message.text.strip())

async def got_edit_due(update, ctx):
    raw = fa_to_en_digits(update.message.text.strip())
    try:
        h, m = map(int, raw.split(":"))
        now = now_local()
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return await _apply_edit(update, ctx, "due", target.strftime("%Y-%m-%d %H:%M"))
    except Exception:
        await update.message.reply_text("❌ فرمت ساعت اشتباه است؛ مثال: <code>18:30</code>", parse_mode="HTML")
        return EDIT_DUE

async def cb_edit_cat(update, _):
    q = update.callback_query
    p = q.data.split(":")
    t = await db_get_task(int(p[1]))
    await db_update_task(int(p[1]), t["title"], t.get("description", ""), p[2], t.get("priority", "Medium"),
                         t.get("due_date"), t.get("is_urgent", 0), t.get("is_important", 1))
    await q.answer("🏷 دسته‌بندی تغییر کرد.")
    await cb_edit_back(update, _)

async def cb_edit_pri(update, _):
    q = update.callback_query
    p = q.data.split(":")
    t = await db_get_task(int(p[1]))
    await db_update_task(int(p[1]), t["title"], t.get("description", ""), t.get("category", "Personal"), p[2],
                         t.get("due_date"), t.get("is_urgent", 0), t.get("is_important", 1))
    await q.answer("🎯 اولویت تغییر کرد.")
    await cb_edit_back(update, _)

# ═══ SEARCH / MIT / SETTINGS ═══
async def search_start(update, ctx):
    await update.message.reply_text("🔍 <b>عبارت جستجو را بنویس:</b>", parse_mode="HTML", reply_markup=step_back_kb(None))
    return SEARCH_STATE

async def search_process(update, ctx):
    q = update.message.text.strip()
    uid = update.effective_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE user_id=? AND (title LIKE ? OR description LIKE ?) LIMIT 10", (uid, f"%{q}%", f"%{q}%")) as c:
            tasks = [dict(r) for r in await c.fetchall()]
        async with db.execute("SELECT * FROM notes WHERE user_id=? AND content LIKE ? LIMIT 5", (uid, f"%{q}%")) as c:
            notes = [dict(r) for r in await c.fetchall()]
    if not tasks and not notes:
        await update.message.reply_text("🔎 چیزی پیدا نشد.", reply_markup=main_reply_keyboard())
        return ConversationHandler.END
    text = f"🔍 <b>نتایج برای «{q}»:</b>\n"
    for t in tasks:
        text += f"{'✅' if t['status'] == 'done' else '⏳'} {t['title']}\n"
    for n in notes:
        text += f"📝 {n['content'][:60]}\n"
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_reply_keyboard())
    return ConversationHandler.END

async def cmd_mit(update, _):
    await render_mit(update)

async def render_mit(update):
    uid = update.effective_user.id
    today = now_local().strftime("%Y-%m-%d")
    tasks = (await db_get_tasks(uid))[:8]
    mits = {m["id"] for m in await db_get_mit(uid, today)}
    if not tasks:
        await update.message.reply_text("📌 کار فعالی نداری که انتخاب کنی!", reply_markup=main_reply_keyboard())
        return
    text = "📌 <b>۳ کار مهم امروز (MIT)</b>\nحداکثر ۳ مورد را انتخاب کن:\n"
    kb = [[InlineKeyboardButton(f"{'✅' if t['id'] in mits else '▫️'} {t['title'][:30]}", callback_data=f"mit_t:{t['id']}")] for t in tasks]
    kb.append([InlineKeyboardButton("✅ ثبت نهایی و نمایش", callback_data="mit_done")])
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def cb_mit_toggle(update, _):
    q = update.callback_query
    uid = update.effective_user.id
    res = await db_toggle_mit(uid, int(q.data.split(":")[1]))
    if res == "full":
        await q.answer("⚠️ فقط ۳ کار!", show_alert=True)
        return
    await q.answer("✔️")
    today = now_local().strftime("%Y-%m-%d")
    tasks = (await db_get_tasks(uid))[:8]
    mits = {m["id"] for m in await db_get_mit(uid, today)}
    text = "📌 <b>۳ کار مهم امروز (MIT)</b>\nحداکثر ۳ مورد:\n"
    kb = [[InlineKeyboardButton(f"{'✅' if t['id'] in mits else '▫️'} {t['title'][:30]}", callback_data=f"mit_t:{t['id']}")] for t in tasks]
    kb.append([InlineKeyboardButton("✅ ثبت نهایی و نمایش", callback_data="mit_done")])
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def cb_mit_done(update, _):
    q = update.callback_query
    mits = await db_get_mit(update.effective_user.id, now_local().strftime("%Y-%m-%d"))
    if not mits:
        await q.answer("اول چند کار را انتخاب کن!", show_alert=True)
        return
    await q.answer("✔️ ثبت شد")
    await q.edit_message_text("📌 <b>۳ کار مهم امروز تو:</b>\n" + "\n".join(f"⭐ {m['title']}" for m in mits) + "\n\n💪 اول روی همین‌ها تمرکز کن!", parse_mode="HTML")

async def cmd_settings(update, _):
    await render_settings(update)

async def render_settings(update):
    s = await db_get_setting(update.effective_user.id)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"🌅 صبح: {s['morning_hour']}", callback_data="set_m"),
        InlineKeyboardButton(f"🌙 شب: {s['evening_hour']}", callback_data="set_e")]])
    msg = ("⚙️ <b>تنظیمات پیام‌های خودکار</b>\n───────────────────────\n"
           f"🌅 برنامه صبحگاهی: ساعت <code>{s['morning_hour']}</code>\n🌙 گزارش شبانه: ساعت <code>{s['evening_hour']}</code>\n"
           "📊 گزارش هفتگی: جمعه‌ها ساعت ۱۸:۰۰\n بکاپ خودکار: هر شب ساعت ۲ بامداد\n\nروی ساعت‌ها بزن تا عوض شوند:")
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode="HTML", reply_markup=kb)
    else:
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)

async def set_morning_start(update, ctx):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("🌅 ساعت جدید برنامه صبحگاهی را مثل <code>07:30</code> بفرست:", parse_mode="HTML")
    return SET_MORNING

async def set_evening_start(update, ctx):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("🌙 ساعت جدید گزارش شبانه را مثل <code>22:00</code> بفرست:", parse_mode="HTML")
    return SET_EVENING

async def _parse_hhmm(text):
    h, m = map(int, fa_to_en_digits(text.strip()).split(":"))
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError
    return f"{h:02d}:{m:02d}"

async def got_set_morning(update, ctx):
    try:
        v = await _parse_hhmm(update.message.text)
    except Exception:
        await update.message.reply_text("❌ مثال: <code>07:30</code>", parse_mode="HTML")
        return SET_MORNING
    await db_set_setting(update.effective_user.id, morning_hour=v, last_morning_date="")
    await update.message.reply_text(f"✅ برنامه صبحگاهی روی <code>{v}</code> تنظیم شد.", parse_mode="HTML", reply_markup=main_reply_keyboard())
    return ConversationHandler.END

async def got_set_evening(update, ctx):
    try:
        v = await _parse_hhmm(update.message.text)
    except Exception:
        await update.message.reply_text("❌ مثال: <code>22:00</code>", parse_mode="HTML")
        return SET_EVENING
    await db_set_setting(update.effective_user.id, evening_hour=v, last_evening_date="")
    await update.message.reply_text(f"✅ گزارش شبانه روی <code>{v}</code> تنظیم شد.", parse_mode="HTML", reply_markup=main_reply_keyboard())
    return ConversationHandler.END

# ═══ ADMIN ═══
async def cmd_admin(update, _):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ دسترسی ندارید.")
        return
    stats = await db_get_admin_stats()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 لیست کاربران", callback_data="admin_users_list_1")],
        [InlineKeyboardButton("📦 بکاپ دستی", callback_data="admin_backup")],
        [InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast")]])
    await update.message.reply_text(
        f"👑 <b>پنل مدیریت</b>\n───────────────────────\n👥 کاربران: <code>{stats['total_users']}</code>\n📋 کارها: <code>{stats['total_tasks']}</code>\n✅ انجام‌شده: <code>{stats['done_tasks']}</code>",
        parse_mode="HTML", reply_markup=kb)

async def cb_admin_backup(update, _):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        await q.answer("⛔", show_alert=True)
        return
    await q.answer("📦 در حال ارسال...")
    with open(DB_PATH, "rb") as f:
        await q.message.reply_document(InputFile(f), caption="📦 بکاپ دیتابیس")

async def cb_admin_broadcast_start(update, ctx):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        await q.answer("⛔", show_alert=True)
        return ConversationHandler.END
    await q.answer()
    await q.message.reply_text("📢 <b>متن پیام همگانی را بفرست:</b>", parse_mode="HTML")
    return ADMIN_BROADCAST

async def admin_broadcast_got(update, ctx):
    text = update.message.text
    users, total = await db_get_users_list(1, 1000)
    sent = 0
    for u in users:
        try:
            await _bot.send_message(u[0], f"📢 <b>پیام مدیر:</b>\n{text}", parse_mode="HTML")
            sent += 1
        except Exception:
            pass
    await update.message.reply_text(f"✅ پیام به {sent} کاربر ارسال شد.", reply_markup=main_reply_keyboard())
    return ConversationHandler.END

async def cb_admin_users_list(update, _):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        await q.answer("⛔", show_alert=True)
        return
    page = int(q.data.split("_")[-1])
    users, total = await db_get_users_list(page)
    text = f"👥 <b>کاربران (صفحه {page}):</b> کل: {total}\n"
    buttons = []
    for u in users:
        name = u[1] or u[2] or f"کاربر {u[0]}"
        text += f"👤 {name} | Lvl {u[3]} | <code>{u[0]}</code>\n"
        buttons.append([InlineKeyboardButton(f"🔍 {name}", callback_data=f"admin_uinfo_{u[0]}")])
    nav = []
    if page > 1: nav.append(InlineKeyboardButton("◀️", callback_data=f"admin_users_list_{page-1}"))
    if total > page * 5: nav.append(InlineKeyboardButton("▶️", callback_data=f"admin_users_list_{page+1}"))
    if nav: buttons.append(nav)
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

async def cb_admin_user_info(update, _):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        await q.answer("⛔", show_alert=True)
        return
    user, tasks = await db_get_user_full_details(int(q.data.split("_")[-1]))
    if not user:
        await q.answer("یافت نشد", show_alert=True)
        return
    text = (f"👤 <b>{user['first_name'] or '—'}</b> | @{user['username'] or '—'}\nID: <code>{user['user_id']}</code>\n"
            f"سطح: {user['level']} | XP: {user['xp']}\n<b>آخرین کارها:</b>\n")
    text += "\n".join(f"{'✅' if t['status'] == 'done' else '⏳'} {t['title']}" for t in tasks) if tasks else "خالی"
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="admin_users_list_1")]]))

_last_err = [0.0]
async def on_error(update, context):
    log.error("Exception:", exc_info=context.error)
    if _time.time() - _last_err[0] > 60:
        _last_err[0] = _time.time()
        try:
            await context.bot.send_message(ADMIN_ID, f"🧯 <b>گزارش خطای سیستم:</b>\n<code>{str(context.error)[:3000]}</code>", parse_mode="HTML")
        except Exception:
            pass

# ═══ WEB SERVER ═══
async def handle_index(request):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    if os.path.exists(path):
        return web.FileResponse(path)
    return web.Response(text="✅ Bot is running")

async def handle_get_tasks(request):
    user_id = request.query.get("user_id")
    if not user_id: return web.json_response({"error": "user_id required"}, status=400)
    tasks = await db_get_tasks(int(user_id))
    for t in tasks: t["subtasks"] = await db_get_subtasks(t["id"])
    return web.json_response({"status": "success", "tasks": tasks})

async def handle_post_task(request):
    try:
        d = await request.json()
        tid = await db_add_task(int(d["user_id"]), d["title"], d.get("description", ""), d.get("category", "Personal"),
                                d.get("priority", "Medium"), d.get("due_date"), d.get("is_urgent", 0), d.get("is_important", 1))
        return web.json_response({"status": "success", "id": tid})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_put_task(request):
    try:
        d = await request.json()
        await db_update_task(int(d["task_id"]), d["title"], d.get("description", ""), d.get("category", "Personal"),
                             d.get("priority", "Medium"), d.get("due_date"), d.get("is_urgent", 0), d.get("is_important", 1))
        return web.json_response({"status": "success"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_delete_task(request):
    await db_delete_task(int(request.match_info.get("id")))
    return web.json_response({"status": "success"})

async def handle_mark_done(request):
    tid = int(request.match_info.get("id"))
    task = await db_get_task(tid)
    if not task: return web.json_response({"error": "not found"}, status=404)
    out = await complete_task(tid, task["user_id"])
    return web.json_response({"status": "success", "xp_gained": 20, "level": out["res"]["level"], "xp": out["res"]["xp"], "leveled_up": out["res"]["leveled_up"]})

async def handle_get_stats(request):
    user_id = request.query.get("user_id")
    if not user_id: return web.json_response({"error": "required"}, status=400)
    return web.json_response({"status": "success", "profile": await db_get_user_profile(int(user_id))})

async def handle_get_notes(request):
    user_id = request.query.get("user_id")
    if not user_id: return web.json_response({"error": "required"}, status=400)
    return web.json_response({"status": "success", "notes": await db_get_notes(int(user_id))})

async def handle_post_note(request):
    d = await request.json()
    await db_add_note(int(d["user_id"]), d["content"])
    return web.json_response({"status": "success"})

async def handle_delete_note(request):
    await db_delete_note(int(request.match_info.get("id")), int(request.query.get("user_id", 0)))
    return web.json_response({"status": "success"})

async def handle_admin_all_data(request):
    user_id = request.query.get("user_id")
    if not user_id or int(user_id) != ADMIN_ID:
        return web.json_response({"success": False, "message": "دسترسی غیرمجاز!"}, status=403)
    users, _ = await db_get_users_list(1, 100)
    data = []
    for u in users:
        data.append({"telegram_id": u[0], "name": u[1] or u[2] or f"کاربر {u[0]}",
                     "tasks": await db_get_tasks(u[0]), "notes": await db_get_notes(u[0])})
    return web.json_response({"success": True, "users": data})

# ═══ WEB API EXTRA (برای وب‌اپ حرفه‌ای) ═══
async def db_get_all_tasks(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE user_id=? ORDER BY id DESC LIMIT 200", (user_id,)) as c:
            return [dict(r) for r in await c.fetchall()]

async def db_get_insights(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        start = (now_local() - timedelta(days=90)).strftime("%Y-%m-%d")
        async with db.execute("SELECT date, done_count, xp_gained, pomo_count FROM daily_stats WHERE user_id=? AND date>=? ORDER BY date", (user_id, start)) as c:
            daily = [dict(r) for r in await c.fetchall()]
        async with db.execute("SELECT key FROM achievements WHERE user_id=?", (user_id,)) as c:
            ach = [r["key"] for r in await c.fetchall()]
        async with db.execute("SELECT * FROM habits WHERE user_id=?", (user_id,)) as c:
            habits = [dict(r) for r in await c.fetchall()]
        today = now_local().strftime("%Y-%m-%d")
        async with db.execute("SELECT done_count, challenge_claimed FROM daily_stats WHERE user_id=? AND date=?", (user_id, today)) as c:
            ch = await c.fetchone()
    return {"daily": daily, "achievements": ach, "habits": habits, "streak": await calc_day_streak(user_id),
            "challenge": {"target": CHALLENGE_TARGET, "progress": ch[0] if ch else 0, "claimed": ch[1] if ch else 0}}

async def handle_get_all_tasks(request):
    user_id = request.query.get("user_id")
    if not user_id: return web.json_response({"error": "required"}, status=400)
    tasks = await db_get_all_tasks(int(user_id))
    for t in tasks: t["subtasks"] = await db_get_subtasks(t["id"])
    return web.json_response({"status": "success", "tasks": tasks})

async def handle_insights(request):
    user_id = request.query.get("user_id")
    if not user_id: return web.json_response({"error": "required"}, status=400)
    return web.json_response({"status": "success", **await db_get_insights(int(user_id))})

async def handle_toggle_subtask(request):
    await db_toggle_subtask(int(request.match_info.get("id")))
    return web.json_response({"status": "success"})

async def handle_set_status(request):
    d = await request.json()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tasks SET status=? WHERE id=?", (d.get("status", "pending"), int(request.match_info.get("id"))))
        await db.commit()
    return web.json_response({"status": "success"})

async def handle_admin_broadcast(request):
    d = await request.json()
    if int(d.get("user_id", 0)) != ADMIN_ID:
        return web.json_response({"success": False}, status=403)
    users, _ = await db_get_users_list(1, 1000)
    sent = 0
    for u in users:
        try:
            await _bot.send_message(u[0], "📢 <b>پیام مدیر:</b>\n" + d.get("text", ""), parse_mode="HTML")
            sent += 1
        except Exception:
            pass
    return web.json_response({"success": True, "sent": sent})

async def start_web_server():
    app = web.Application()
    cors = aiohttp_cors.setup(app, defaults={"*": aiohttp_cors.ResourceOptions(allow_credentials=True, expose_headers="*", allow_headers="*", allow_methods="*")})
    app.router.add_get("/", handle_index)
    cors.add(app.router.add_get("/api/tasks", handle_get_tasks))
    cors.add(app.router.add_post("/api/tasks", handle_post_task))
    cors.add(app.router.add_put("/api/tasks", handle_put_task))
    cors.add(app.router.add_delete("/api/tasks/{id}", handle_delete_task))
    cors.add(app.router.add_post("/api/tasks/{id}/done", handle_mark_done))
    cors.add(app.router.add_get("/api/stats", handle_get_stats))
    cors.add(app.router.add_get("/api/admin/all-data", handle_admin_all_data))
    cors.add(app.router.add_get("/api/notes", handle_get_notes))
    cors.add(app.router.add_post("/api/notes", handle_post_note))
    cors.add(app.router.add_delete("/api/notes/{id}", handle_delete_note))
    cors.add(app.router.add_get("/api/tasks/all", handle_get_all_tasks))
    cors.add(app.router.add_get("/api/insights", handle_insights))
    cors.add(app.router.add_post("/api/subtasks/{id}/toggle", handle_toggle_subtask))
    cors.add(app.router.add_post("/api/tasks/{id}/status", handle_set_status))
    cors.add(app.router.add_post("/api/admin/broadcast", handle_admin_broadcast))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080))).start()
    log.info("Web Server Online 🌐")

# ═══ MAIN ══
async def post_init(application):
    await application.bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="todo-list", web_app=WebAppInfo(url=WEBAPP_URL)))
    start_scheduler(application.bot)

async def main_async():
    await init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("add", add_start), MessageHandler(filters.Regex("^➕ افزودن کار جدید$"), add_start)],
        states={
            ADD_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_title), CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")],
            ADD_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_desc), CommandHandler("skip", add_got_desc), CallbackQueryHandler(ask_title, pattern=r"^goto:title$"), CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")],
            ADD_CAT: [CallbackQueryHandler(add_got_cat, pattern=r"^cat:"), CallbackQueryHandler(ask_desc, pattern=r"^goto:desc$"), CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")],
            ADD_PRI: [CallbackQueryHandler(add_got_pri, pattern=r"^pri:"), CallbackQueryHandler(ask_cat, pattern=r"^goto:cat$"), CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")],
            ADD_EISENHOWER: [CallbackQueryHandler(add_got_eisenhower, pattern=r"^eisen:"), CallbackQueryHandler(ask_pri, pattern=r"^goto:pri$"), CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")],
            ADD_DUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_due), CommandHandler("skip", add_got_due), CallbackQueryHandler(ask_eisen, pattern=r"^goto:eisen$"), CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")],
            ADD_REC: [CallbackQueryHandler(add_got_rec, pattern=r"^rec:"), CallbackQueryHandler(ask_due, pattern=r"^goto:due$"), CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel), CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")], per_user=True))

    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^⚡ ثبت سریع کار$"), quick_add_start)],
        states={QUICK_ADD_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, quick_add_process), CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")]},
        fallbacks=[CommandHandler("cancel", cmd_cancel)], per_user=True))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_add_subtask_start, pattern=r"^add_sub:")],
        states={ADD_SUBTASK_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_subtask_process)]},
        fallbacks=[CommandHandler("cancel", cmd_cancel)], per_user=True))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_add_habit_start, pattern="^add_habit_btn$")],
        states={ADD_HABIT_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_habit_process)]},
        fallbacks=[CommandHandler("cancel", cmd_cancel)], per_user=True))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_add_note_start, pattern="^add_note_btn$")],
        states={ADD_NOTE_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_note_process)]},
        fallbacks=[CommandHandler("cancel", cmd_cancel)], per_user=True))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_edit_field, pattern=r"^edit_f:(title|desc|due):")],
        states={EDIT_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_edit_title)],
                EDIT_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_edit_desc)],
                EDIT_DUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_edit_due)]},
        fallbacks=[CommandHandler("cancel", cmd_cancel)], per_user=True))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(set_morning_start, pattern="^set_m$"), CallbackQueryHandler(set_evening_start, pattern="^set_e$")],
        states={SET_MORNING: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_set_morning)],
                SET_EVENING: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_set_evening)]},
        fallbacks=[CommandHandler("cancel", cmd_cancel)], per_user=True))

    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 جستجو$"), search_start)],
        states={SEARCH_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_process), CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")]},
        fallbacks=[CommandHandler("cancel", cmd_cancel)], per_user=True))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_admin_broadcast_start, pattern="^admin_broadcast$")],
        states={ADMIN_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_got)]},
        fallbacks=[CommandHandler("cancel", cmd_cancel)], per_user=True))

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(MessageHandler(filters.Regex("^➕ افزودن کار جدید$"), add_start))
    app.add_handler(MessageHandler(filters.Regex("^📋 کارهای فعال من$"), cmd_list))
    app.add_handler(MessageHandler(filters.Regex("^🍅 پومودورو تمرکز$"), cmd_pomo_info))
    app.add_handler(MessageHandler(filters.Regex("^🌱 ردیاب عادت‌ها$"), cmd_habits))
    app.add_handler(MessageHandler(filters.Regex("^📐 ماتریس آیزنهاور$"), cmd_eisenhower))
    app.add_handler(MessageHandler(filters.Regex("^📝 دفترچه یادداشت Notion$"), cmd_notes))
    app.add_handler(MessageHandler(filters.Regex("^🏆 پروفایل & مدال‌ها$"), cmd_profile))
    app.add_handler(MessageHandler(filters.Regex("^📊 گزارش CSV$"), cmd_export))
    app.add_handler(MessageHandler(filters.Regex("^✅ کارهای انجام‌شده$"), cmd_done_list))
    app.add_handler(MessageHandler(filters.Regex("^📌 ۳ کار مهم امروز$"), cmd_mit))
    app.add_handler(MessageHandler(filters.Regex("^⚙️ تنظیمات$"), cmd_settings))
    app.add_handler(MessageHandler(filters.Regex("^❓ راهنما و آموزش$"), cmd_help))
    app.add_handler(MessageHandler(filters.PHOTO, save_forward))
    app.add_handler(CallbackQueryHandler(cb_done_task, pattern=r"^done:"))
    app.add_handler(CallbackQueryHandler(cb_del_task, pattern=r"^del_task:"))
    app.add_handler(CallbackQueryHandler(cb_pomo_start, pattern=r"^pomo_start:"))
    app.add_handler(CallbackQueryHandler(cb_snooze, pattern=r"^snooze:"))
    app.add_handler(CallbackQueryHandler(cb_checkin_habit, pattern=r"^checkin_habit:"))
    app.add_handler(CallbackQueryHandler(cb_del_habit, pattern=r"^del_habit:"))
    app.add_handler(CallbackQueryHandler(cb_del_note, pattern=r"^del_note:"))
    app.add_handler(CallbackQueryHandler(cb_toggle_subtask, pattern=r"^toggle_sub:"))
    app.add_handler(CallbackQueryHandler(cb_edit_menu, pattern=r"^edit:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_edit_back, pattern=r"^edit_back:"))
    app.add_handler(CallbackQueryHandler(cb_edit_cat, pattern=r"^edit_cat:"))
    app.add_handler(CallbackQueryHandler(cb_edit_pri, pattern=r"^edit_pri:"))
    app.add_handler(CallbackQueryHandler(cb_mit_toggle, pattern=r"^mit_t:"))
    app.add_handler(CallbackQueryHandler(cb_mit_done, pattern="^mit_done$"))
    app.add_handler(CallbackQueryHandler(cb_admin_backup, pattern="^admin_backup$"))
    app.add_handler(CallbackQueryHandler(cb_admin_users_list, pattern="^admin_users_list_"))
    app.add_handler(CallbackQueryHandler(cb_admin_user_info, pattern="^admin_uinfo_"))
    app.add_handler(MessageHandler(filters.ALL, catch_all))
    app.add_error_handler(on_error)

    await start_web_server()
    async with app:
        await app.initialize()
        await app.start()
        log.info("System Ready & Running Smoothly 🚀")
        await app.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main_async())
