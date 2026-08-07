"""
🚀 ULTIMATE ENTERPRISE TASK & PRODUCTIVITY SYSTEM (bot03.py)
===================================================================
نسخه جامع بدون هیچ‌گونه خلاصه‌سازی یا حذفیات.
پشتیبانی کامل از:
- ثبت ۶ مرحله‌ای با دکمه بازگشت به مرحله قبل (Back Navigation)
- وب‌سرور REST API دوطرفه (Full CORS + WebApp Sync)
- پردازشگر هوشمند زبان طبیعی (Natural Language Quick Add)
- ردیاب عادت‌ها، ماتریس آیزنهاور، پومودورو، زیرکارها، گیمیفیکیشن و CSV
"""

import asyncio
import csv
import io
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

import aiosqlite
from aiohttp import web
import aiohttp_cors
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import (
    Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update,
    ReplyKeyboardMarkup, KeyboardButton, InputFile, WebAppInfo,
    MenuButtonWebApp
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG & LOGGING
# ═══════════════════════════════════════════════════════════════════════════════

# شناسه عددی تلگرام مدیر اصلی ربات
ADMIN_ID = 7681488759  # آیدی عددی خود را جایگزین کنید
BOT_TOKEN  = os.environ.get("BOT_TOKEN", "8322904493:AAFMyY-sB__S8s3f5DiTfaq6jm5lbrydH34")
DB_PATH    = "ultimate_productivity.db"
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://bot-kqte.onrender.com")

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# UTILS & SMART TIME PARSER
# ═══════════════════════════════════════════════════════════════════════════════

def fa_to_en_digits(text: str) -> str:
    """تبدیل تمام اعداد فارسی و عربی به انگلیسی"""
    fa_digits = '۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩'
    en_digits = '01234567890123456789'
    trans = str.maketrans(fa_digits, en_digits)
    return text.translate(trans)


def parse_quick_add(text: str) -> dict:
    """پردازشگر هوشمند متون تک‌خطی برای ثبت سریع کارها"""
    clean_text = fa_to_en_digits(text).replace("：", ":")

    category = "Personal"
    priority = "Medium"
    is_urgent = 0
    is_important = 1
    due_date = None

    # استخراج دسته‌بندی
    cat_match = re.search(r'#(\w+)', clean_text)
    if cat_match:
        tag = cat_match.group(1).lower()
        if tag in ["کاری", "work", "کار", "شغلی"]:
            category = "Work"
        elif tag in ["تحصیلی", "study", "درس", "دانشگاه", "مدرسه"]:
            category = "Study"
        elif tag in ["شخصی", "personal", "خودم"]:
            category = "Personal"
        clean_text = re.sub(r'#\w+', '', clean_text)

    # استخراج اولویت و ماتریس آیزنهاور
    pri_match = re.search(r'!(\w+)', clean_text)
    if pri_match:
        p_str = pri_match.group(1).lower()
        if p_str in ["ضروری", "فوری", "بالا", "high", "مهم"]:
            priority = "High"
            is_urgent = 1
            is_important = 1
        elif p_str in ["کم", "پایین", "low"]:
            priority = "Low"
            is_urgent = 0
            is_important = 0
        clean_text = re.sub(r'!\w+', '', clean_text)

    # استخراج زمان
    time_match = re.search(r'@(\d{1,2}:\d{2})', clean_text)
    now = datetime.now()
    if time_match:
        try:
            h, m = map(int, time_match.group(1).split(":"))
            if 0 <= h <= 23 and 0 <= m <= 59:
                target = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if target <= now:
                    target += timedelta(days=1)
                due_date = target.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass
        clean_text = re.sub(r'@\d{1,2}:\d{2}', '', clean_text)

    title = clean_text.strip()
    return {
        "title": title if title else text,
        "category": category,
        "priority": priority,
        "is_urgent": is_urgent,
        "is_important": is_important,
        "due_date": due_date
    }

# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE LAYER (COMPLETE AGGREGATED SCHEMA)
# ═══════════════════════════════════════════════════════════════════════════════

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER NOT NULL,
                title        TEXT    NOT NULL,
                description  TEXT    DEFAULT '',
                category     TEXT    DEFAULT 'Personal',
                priority     TEXT    DEFAULT 'Medium',
                is_urgent    INTEGER DEFAULT 0,
                is_important INTEGER DEFAULT 1,
                due_date     TEXT,
                recurrence   TEXT    DEFAULT 'None',
                status       TEXT    DEFAULT 'pending',
                pomodoros    INTEGER DEFAULT 0,
                created_at   TEXT    DEFAULT (datetime('now')),
                done_at      TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS subtasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id     INTEGER NOT NULL,
                title       TEXT    NOT NULL,
                is_done     INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS habits (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                title       TEXT    NOT NULL,
                streak      INTEGER DEFAULT 0,
                last_done   TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                first_name  TEXT,
                username    TEXT,
                xp          INTEGER DEFAULT 0,
                level       INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                content     TEXT    NOT NULL,
                created_at  TEXT    DEFAULT (datetime('now'))
            )
        """)
        await db.commit()

# --- DB HELPERS: NOTES ---

async def db_add_note(user_id: int, content: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO notes (user_id, content) VALUES (?, ?)",
            (user_id, content)
        )
        await db.commit()

async def db_get_notes(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM notes WHERE user_id = ? ORDER BY id DESC", (user_id,)) as cur:
            return await cur.fetchall()

async def db_delete_note(note_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM notes WHERE id = ? AND user_id = ?", (note_id, user_id))
        await db.commit()

# --- DB HELPERS: TASKS ---

async def db_add_task(user_id: int, title: str, description: str = "",
                      category: str = "Personal", priority: str = "Medium",
                      due_date: Optional[str] = None, recurrence: str = "None",
                      is_urgent: int = 0, is_important: int = 1) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO tasks
               (user_id, title, description, category, priority, due_date, recurrence, is_urgent, is_important)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, title, description, category, priority, due_date, recurrence, is_urgent, is_important)
        )
        await db.commit()
        return cursor.lastrowid

async def db_update_task(task_id: int, title: str, description: str = "",
                         category: str = "Personal", priority: str = "Medium",
                         due_date: Optional[str] = None, is_urgent: int = 0, is_important: int = 1):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE tasks SET title=?, description=?, category=?, priority=?, due_date=?, is_urgent=?, is_important=? WHERE id=?""",
            (title, description, category, priority, due_date, is_urgent, is_important, task_id)
        )
        await db.commit()

async def db_get_tasks(user_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tasks WHERE user_id=? AND status='pending' ORDER BY due_date ASC NULLS LAST, id DESC",
            (user_id,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

async def db_get_done_tasks(user_id: int, limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tasks WHERE user_id=? AND status='done' ORDER BY done_at DESC LIMIT ?",
            (user_id, limit)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

async def db_get_task(task_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def db_mark_done(task_id: int):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tasks SET status='done', done_at=? WHERE id=?", (now, task_id))
        await db.commit()

async def db_delete_task(task_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        await db.execute("DELETE FROM subtasks WHERE task_id=?", (task_id,))
        await db.commit()

async def db_increment_pomo(task_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tasks SET pomodoros = pomodoros + 1 WHERE id=?", (task_id,))
        await db.commit()

async def db_get_due_tasks() -> list[dict]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tasks WHERE status='pending' AND due_date IS NOT NULL AND due_date<=?",
            (now,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

# --- DB HELPERS: SUBTASKS ---

async def db_add_subtask(task_id: int, title: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO subtasks (task_id, title) VALUES (?, ?)", (task_id, title))
        await db.commit()

async def db_get_subtasks(task_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM subtasks WHERE task_id=?", (task_id,)) as cur:
            return [dict(r) for r in await cur.fetchall()]

async def db_toggle_subtask(subtask_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE subtasks SET is_done = 1 - is_done WHERE id=?", (subtask_id,))
        await db.commit()

# --- DB HELPERS: HABITS ---

async def db_add_habit(user_id: int, title: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO habits (user_id, title) VALUES (?, ?)", (user_id, title))
        await db.commit()

async def db_get_habits(user_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM habits WHERE user_id=?", (user_id,)) as cur:
            return [dict(r) for r in await cur.fetchall()]

async def db_checkin_habit(habit_id: int):
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE habits SET streak = streak + 1, last_done=? WHERE id=?", (today, habit_id))
        await db.commit()

async def db_delete_habit(habit_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM habits WHERE id=?", (habit_id,))
        await db.commit()

# --- DB HELPERS: NOTES ---

async def db_add_note(user_id: int, content: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO notes (user_id, content) VALUES (?, ?)", (user_id, content))
        await db.commit()

async def db_get_notes(user_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM notes WHERE user_id=? ORDER BY id DESC LIMIT 20", (user_id,)) as cur:
            return [dict(r) for r in await cur.fetchall()]

# --- DB HELPERS: GAMIFICATION & EXPORT ---

async def db_add_xp(user_id: int, amount: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT xp, level FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                current_xp, current_lvl = amount, 1
                await db.execute("INSERT INTO users (user_id, xp, level) VALUES (?, ?, ?)", (user_id, amount, 1))
            else:
                current_xp = row[0] + amount
                new_lvl = (current_xp // 100) + 1
                leveled_up = new_lvl > row[1]
                await db.execute("UPDATE users SET xp=?, level=? WHERE user_id=?", (current_xp, new_lvl, user_id))
                await db.commit()
                return {"xp": current_xp, "level": new_lvl, "leveled_up": leveled_up}
        await db.commit()
        return {"xp": amount, "level": 1, "leveled_up": False}

async def db_get_admin_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        # دریافت تعداد کل کاربران
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            total_users = (await cur.fetchone())[0]
        
        # دریافت تعداد کل کارهای ثبت‌شده
        async with db.execute("SELECT COUNT(*) FROM tasks") as cur:
            total_tasks = (await cur.fetchone())[0]
        
        # دریافت تعداد کارهای انجام‌شده
        async with db.execute("SELECT COUNT(*) FROM tasks WHERE status='done'") as cur:
            done_tasks = (await cur.fetchone())[0]
            
        return {
            "total_users": total_users,
            "total_tasks": total_tasks,
            "done_tasks": done_tasks
        }

async def db_get_users_list(page: int = 1, per_page: int = 5):
    offset = (page - 1) * per_page
    async with aiosqlite.connect(DB_PATH) as db:
        # دریافت ۵ کاربر برای صفحه جاری
        async with db.execute("SELECT user_id, first_name, username, level, xp FROM users LIMIT ? OFFSET ?", (per_page, offset)) as cur:
            users = await cur.fetchall()
        # دریافت تعداد کل کاربران
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            total = (await cur.fetchone())[0]
    return users, total

async def db_get_user_full_details(target_user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # دریافت اطلاعات پروفایل کاربر
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (target_user_id,)) as cur:
            user = await cur.fetchone()
        
        # دریافت ۱۰ کاری که این کاربر در ربات ثبت کرده است
        async with db.execute("SELECT title, status, category FROM tasks WHERE user_id = ? ORDER BY id DESC LIMIT 10", (target_user_id,)) as cur:
            tasks = await cur.fetchall()
            
        return user, tasks

async def db_get_user_profile(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT xp, level FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return {"xp": 0, "level": 1, "badge": "🌱 تازه کار"}
            xp, lvl = row[0], row[1]
            badges = {
                1: "🌱 تازه کار",
                2: "⚡ فعال و باانگیزه",
                3: "🔥 استاد تمرکز",
                4: "🏆 قهرمان برنامه‌ریزی",
                5: "👑 اسطوره استمرار و بازدهی"
            }
            return {"xp": xp, "level": lvl, "badge": badges.get(lvl, "👑 اسطوره استمرار")}

async def db_export_csv(user_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE user_id=?", (user_id,)) as cur:
            rows = await cur.fetchall()
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["ID", "Title", "Description", "Category", "Priority", "Urgent", "Important", "DueDate", "Status", "Pomodoros", "CreatedAt", "DoneAt"])
            for r in rows:
                writer.writerow([r["id"], r["title"], r["description"], r["category"], r["priority"], r["is_urgent"], r["is_important"], r["due_date"], r["status"], r["pomodoros"], r["created_at"], r["done_at"]])
            return output.getvalue()

# ═══════════════════════════════════════════════════════════════════════════════
# KEYBOARDS & UI FORMATTING
# ═══════════════════════════════════════════════════════════════════════════════

def main_reply_keyboard(user_id: Optional[int] = None) -> ReplyKeyboardMarkup:
    url = f"{WEBAPP_URL}?user_id={user_id}" if user_id else WEBAPP_URL
    kb = [
        [KeyboardButton("➕ افزودن کار جدید"), KeyboardButton("⚡ ثبت سریع کار")],
        [KeyboardButton("📋 کارهای فعال من"), KeyboardButton("🌐 وب‌اپ کارهای من", web_app=WebAppInfo(url=url))],
        [KeyboardButton("🍅 پومودورو تمرکز"), KeyboardButton("🌱 ردیاب عادت‌ها")],
        [KeyboardButton("📐 ماتریس آیزنهاور"), KeyboardButton("📝 دفترچه یادداشت Notion")],
        [KeyboardButton("🏆 پروفایل & مدال‌ها"), KeyboardButton("📊 گزارش CSV")],
        [KeyboardButton("✅ کارهای انجام‌شده")]
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def step_back_kb(back_target: Optional[str] = None) -> InlineKeyboardMarkup:
    row = []
    if back_target:
        row.append(InlineKeyboardButton("🔙 مرحله قبل", callback_data=f"goto:{back_target}"))
    row.append(InlineKeyboardButton("❌ انصراف", callback_data="cancel_flow"))
    return InlineKeyboardMarkup([row])

def fmt_task_advanced(t: dict, subtasks: list[dict] = []) -> str:
    pri_map = {"High": "🚨 ضروری (بالا)", "Medium": "🟡 معمولی", "Low": "🟢 کم اهمیت"}
    cat_map = {"Personal": "👤 شخصی", "Work": "💼 کاری", "Study": "📚 تحصیلی"}

    text = f"💎 <b>{t['title']}</b>\n"
    text += "───────────────────────\n"
    if t.get("description"):
        text += f"💬 <i>{t['description']}</i>\n\n"
    text += f"🏷 <b>دسته‌بندی:</b> {cat_map.get(t.get('category'), 'عمومی')}\n"
    text += f"🎯 <b>اولویت:</b> {pri_map.get(t.get('priority'), 'معمولی')}\n"
    
    # نمایش ربع آیزنهاور
    u, i = t.get("is_urgent", 0), t.get("is_important", 1)
    if u and i:
        text += "📐 <b>ماتریس آیزنهاور:</b> 🔥 فوری و مهم (انجام فوری)\n"
    elif not u and i:
        text += "📐 <b>ماتریس آیزنهاور:</b> 📅 غیرفوری ولی مهم (برنامه‌ریزی)\n"
    elif u and not i:
        text += "📐 <b>ماتریس آیزنهاور:</b> ⚡ فوری ولی کم‌اهمیت (واگذاری)\n"
    else:
        text += "📐 <b>ماتریس آیزنهاور:</b> 🟢 کم‌اهمیت و غیرفوری\n"

    text += f"🍅 <b>پومودوروها:</b> <code>{t.get('pomodoros', 0)}</code> جلسه\n"

    if t.get("due_date"):
        text += f"⏰ <b>زمان یادآوری:</b> <code>{t['due_date']}</code>\n"

    if subtasks:
        text += "\n<b>☑️ زیرکارها (چک‌لیست):</b>\n"
        for st in subtasks:
            icon = "✅" if st["is_done"] else "▫️"
            text += f"{icon} {st['title']}\n"

    return text

def task_action_kb(task_id: int, subtasks: list[dict] = []) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("✅ انجام شد (+20 XP)", callback_data=f"done:{task_id}"),
            InlineKeyboardButton("🍅 پومودورو", callback_data=f"pomo_start:{task_id}"),
        ],
        [
            InlineKeyboardButton("➕ افزودن زیرکار", callback_data=f"add_sub:{task_id}"),
            InlineKeyboardButton("🗑 حذف", callback_data=f"del_task:{task_id}")
        ]
    ]

    for st in subtasks:
        icon = "✅" if st["is_done"] else "▫️"
        buttons.append([InlineKeyboardButton(f"{icon} {st['title']}", callback_data=f"toggle_sub:{st['id']}:{task_id}")])

    return InlineKeyboardMarkup(buttons)

# ═══════════════════════════════════════════════════════════════════════════════
# SCHEDULER & NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════════════════

scheduler = AsyncIOScheduler(timezone="UTC")
_bot: Optional[Bot] = None
_notified: set[int] = set()

async def check_due_notifications():
    if not _bot:
        return
    tasks = await db_get_due_tasks()
    for t in tasks:
        tid = t["id"]
        if tid in _notified:
            continue
        _notified.add(tid)
        try:
            subs = await db_get_subtasks(tid)
            await _bot.send_message(
                chat_id=t["user_id"],
                text=f"🔔 <b>زمان انجام این کار فرا رسید!</b>\n\n" + fmt_task_advanced(t, subs),
                parse_mode="HTML",
                reply_markup=task_action_kb(tid, subs)
            )
        except Exception as e:
            log.error(f"Notification error: {e}")

def start_scheduler(bot: Bot):
    global _bot
    _bot = bot
    scheduler.add_job(check_due_notifications, "interval", seconds=15, id="_check_due", replace_existing=True)
    if not scheduler.running:
        scheduler.start()

# ═══════════════════════════════════════════════════════════════════════════════
# CONVERSATION STATES
# ═══════════════════════════════════════════════════════════════════════════════

ADD_TITLE, ADD_DESC, ADD_CAT, ADD_PRI, ADD_EISENHOWER, ADD_DUE, ADD_REC = range(7)
QUICK_ADD_STATE = 7
ADD_SUBTASK_STATE = 8
ADD_HABIT_STATE = 9
ADD_NOTE_STATE = 10

# ═══════════════════════════════════════════════════════════════════════════════
# HANDLERS: ADD TASK WITH FULL BACK NAVIGATION (مرحله به مرحله)
# ═══════════════════════════════════════════════════════════════════════════════

async def add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    msg = "📝 <b>افزودن کار جدید (مرحله ۱ از ۶)</b>\n───────────────────────\nلطفاً <b>عنوان کار</b> را وارد کنید:"
    kb = step_back_kb(None)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(msg, parse_mode="HTML", reply_markup=kb)
    else:
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
    return ADD_TITLE


async def add_got_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message:
        ctx.user_data["title"] = update.message.text.strip()

    msg = (
        f"✅ <b>عنوان کار:</b> {ctx.user_data.get('title')}\n\n"
        "💬 <b>توضیحات تکمیلی (مرحله ۲ از ۶)</b> را وارد کنید:\n"
        "<i>(یا دستور /skip را ارسال کنید)</i>"
    )
    kb = step_back_kb("title")

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(msg, parse_mode="HTML", reply_markup=kb)
    else:
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
    return ADD_DESC


async def add_got_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message:
        if update.message.text.startswith("/skip"):
            ctx.user_data["description"] = ""
        else:
            ctx.user_data["description"] = update.message.text.strip()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 شخصی", callback_data="cat:Personal"), InlineKeyboardButton("💼 کاری", callback_data="cat:Work")],
        [InlineKeyboardButton("📚 تحصیلی", callback_data="cat:Study")],
        [InlineKeyboardButton("🔙 مرحله قبل", callback_data="goto:desc"), InlineKeyboardButton("❌ انصراف", callback_data="cancel_flow")]
    ])
    msg = "🏷 <b>دسته‌بندی کار (مرحله ۳ از ۶)</b> را انتخاب کنید:"

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(msg, parse_mode="HTML", reply_markup=kb)
    else:
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
    return ADD_CAT


async def add_got_cat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data.startswith("cat:"):
        ctx.user_data["category"] = q.data.split(":")[1]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚨 ضروری (بالا)", callback_data="pri:High"), InlineKeyboardButton("🟡 معمولی", callback_data="pri:Medium")],
        [InlineKeyboardButton("🟢 کم اهمیت", callback_data="pri:Low")],
        [InlineKeyboardButton("🔙 مرحله قبل", callback_data="goto:cat"), InlineKeyboardButton("❌ انصراف", callback_data="cancel_flow")]
    ])
    await q.edit_message_text("🎯 <b>اولویت کار (مرحله ۴ از ۶)</b> را مشخص کنید:", parse_mode="HTML", reply_markup=kb)
    return ADD_PRI


async def add_got_pri(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data.startswith("pri:"):
        ctx.user_data["priority"] = q.data.split(":")[1]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 فوری و مهم", callback_data="eisen:1:1"), InlineKeyboardButton("📅 غیرفوری ولی مهم", callback_data="eisen:0:1")],
        [InlineKeyboardButton("⚡ فوری ولی کم‌اهمیت", callback_data="eisen:1:0"), InlineKeyboardButton("🟢 کم‌اهمیت و غیرفوری", callback_data="eisen:0:0")],
        [InlineKeyboardButton("🔙 مرحله قبل", callback_data="goto:pri"), InlineKeyboardButton("❌ انصراف", callback_data="cancel_flow")]
    ])
    await q.edit_message_text("📐 <b>دسته‌بندی در ماتریس آیزنهاور (مرحله ۵ از ۶):</b>", parse_mode="HTML", reply_markup=kb)
    return ADD_EISENHOWER


async def add_got_eisenhower(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data.startswith("eisen:"):
        parts = q.data.split(":")
        ctx.user_data["is_urgent"] = int(parts[1])
        ctx.user_data["is_important"] = int(parts[2])

    msg = (
        "⏰ <b>زمان یادآوری (مرحله ۶ از ۶)</b> را وارد کنید:\n\n"
        "📌 فرمت‌های مجاز:\n"
        "• <code>18:30</code> (ساعت ۶ و نیم عصر)\n"
        "• <code>09:15</code> (ساعت ۹ و ربع صبح)\n\n"
        "<i>(یا دستور /skip را ارسال کنید)</i>"
    )
    kb = step_back_kb("eisen")
    await q.edit_message_text(msg, parse_mode="HTML", reply_markup=kb)
    return ADD_DUE


async def add_got_due(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message:
        if not update.message.text.startswith("/skip"):
            raw = fa_to_en_digits(update.message.text.strip()).replace("：", ":")
            try:
                parts = raw.split(":")
                if len(parts) != 2:
                    raise ValueError
                h, m = int(parts[0]), int(parts[1])
                if not (0 <= h <= 23 and 0 <= m <= 59):
                    raise ValueError

                now = datetime.now()
                target_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if target_dt <= now:
                    target_dt += timedelta(days=1)

                ctx.user_data["due_date"] = target_dt.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                await update.message.reply_text("❌ فرمت ساعت نامعتبر است! مثال: <code>18:30</code>", parse_mode="HTML", reply_markup=step_back_kb("eisen"))
                return ADD_DUE
        else:
            ctx.user_data["due_date"] = None

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 بدون تکرار", callback_data="rec:None"), InlineKeyboardButton("📅 روزانه", callback_data="rec:Daily")],
        [InlineKeyboardButton("🔙 مرحله قبل", callback_data="goto:due"), InlineKeyboardButton("❌ انصراف", callback_data="cancel_flow")]
    ])
    msg = "🔁 آیا این کار نیاز به <b>تکرار خودکار</b> دارد؟"

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(msg, parse_mode="HTML", reply_markup=kb)
    else:
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
    return ADD_REC


async def add_got_rec(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    rec = q.data.split(":")[1]

    uid = update.effective_user.id
    d = ctx.user_data
    tid = await db_add_task(
        user_id=uid,
        title=d["title"],
        description=d.get("description", ""),
        category=d.get("category", "Personal"),
        priority=d.get("priority", "Medium"),
        due_date=d.get("due_date"),
        recurrence=rec,
        is_urgent=d.get("is_urgent", 0),
        is_important=d.get("is_important", 1)
    )
    ctx.user_data.clear()
    task = await db_get_task(tid)

    # ۱. ارسال پیام موفقیت ثبت کار
    await q.edit_message_text(
        "🎉 <b>کار جدید شما با موفقیت ثبت شد!</b>\n\n" + fmt_task_advanced(task),
        parse_mode="HTML"
    )

    # ۲. نمایش خودکار و آنلاین لیست کارهای فعال
    await cmd_list(update, ctx)
    return ConversationHandler.END

# ═══════════════════════════════════════════════════════════════════════════════
# HANDLERS: GENERAL COMMANDS, LISTS, PROFILE & CSV
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    text = (
        "🚀 <b>به سیستم مدیریت وظایف پیشرفته خوش آمدید!</b>\n"
        "───────────────────────\n"
        "طراحی‌شده بر اساس استانداردهای جهانی <b>Notion</b>، <b>Todoist</b>، <b>تکنیک پومودورو</b> و <b>ماتریس آیزنهاور</b>.\n\n"
        "👇 <i>از کیبورد زیر برای هدایت استفاده کنید:</i>"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_reply_keyboard(update.effective_user.id))


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    msg = "❌ عملیات لغو شد."
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg, reply_markup=main_reply_keyboard())
    return ConversationHandler.END


async def cmd_profile(update: Update, _: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    prof = await db_get_user_profile(uid)

    intro = (
        "🏆 <b>پروفایل کاربری و سیستم امتیازدهی (Gamification)</b>\n"
        "───────────────────────\n"
    )
    body = (
        f"👤 <b>سطح فعلی:</b> Level {prof['level']}\n"
        f"🎖 <b>مدال:</b> {prof['badge']}\n"
        f"⚡ <b>مجموع امتیاز (XP):</b> <code>{prof['xp']}</code> XP\n\n"
        f"💡 <i>با انجام کارها، جلسات پومودورو و عادت‌ها XP بگیرید و ارتقا یابید!</i>"
    )
    await update.message.reply_text(intro + body, parse_mode="HTML", reply_markup=main_reply_keyboard())


async def cmd_export(update: Update, _: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    csv_data = await db_export_csv(uid)
    bio = io.BytesIO(csv_data.encode('utf-8'))
    bio.name = f"tasks_export_{datetime.now().strftime('%Y%m%d')}.csv"

    await update.message.reply_text("📊 <b>در حال تولید فایل CSV...</b>", parse_mode="HTML")
    await update.message.reply_document(
        document=InputFile(bio),
        caption="📄 فایل کامل پشتیبان کارهای شما آماده گردید.",
        reply_markup=main_reply_keyboard()
    )


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.message else update.callback_query.from_user.id
    tasks = await db_get_tasks(uid)
    msg_target = update.message if update.message else update.callback_query.message

    if not tasks:
        no_task_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 باز کردن وب‌اپ تودولیست", web_app=WebAppInfo(url=WEBAPP_URL))]
        ])
        await msg_target.reply_text("🎉 <b>هیچ کار فعالی در لیست شما نیست!</b>", parse_mode="HTML", reply_markup=no_task_kb)
        return

    webapp_inline_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 مدیریت گرافیکی کارهام در وب‌اپ", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])
    await msg_target.reply_text("📋 <b>لیست کارهای فعال شما:</b>", parse_mode="HTML", reply_markup=webapp_inline_kb)

    for t in tasks:
        subs = await db_get_subtasks(t["id"])
        await msg_target.reply_text(
            fmt_task_advanced(t, subs),
            parse_mode="HTML",
            reply_markup=task_action_kb(t["id"], subs)
        )


async def cmd_done_list(update: Update, _: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    done_tasks = await db_get_done_tasks(uid)

    if not done_tasks:
        await update.message.reply_text("📂 هنوز هیچ کاری را تمام نکرده‌اید.", reply_markup=main_reply_keyboard())
        return

    text = "✅ <b>تاریخچه کارهای انجام‌شده:</b>\n───────────────────────\n"
    for t in done_tasks:
        text += f"• <s>{t['title']}</s> <code>({t['done_at'][:10] if t['done_at'] else ''})</code>\n"

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_reply_keyboard())

# ═══════════════════════════════════════════════════════════════════════════════
# HANDLERS: QUICK ADD, POMODORO, HABITS, EISENHOWER, NOTES & SUBTASKS
# ═══════════════════════════════════════════════════════════════════════════════

async def quick_add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    intro = (
        "⚡ <b>ثبت سریع کار (Smart Natural Language)</b>\n"
        "───────────────────────\n"
        "متن کار را در یک سطر وارد کنید:\n"
        "<code>تکمیل پروژه #کاری !ضروری @19:30</code>"
    )
    await update.message.reply_text(intro, parse_mode="HTML", reply_markup=step_back_kb(None))
    return QUICK_ADD_STATE


async def quick_add_process(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    parsed = parse_quick_add(text)
    uid = update.effective_user.id

    tid = await db_add_task(
        user_id=uid,
        title=parsed["title"],
        category=parsed["category"],
        priority=parsed["priority"],
        due_date=parsed["due_date"],
        is_urgent=parsed["is_urgent"],
        is_important=parsed["is_important"]
    )
    task = await db_get_task(tid)
    await db_add_xp(uid, 10)

    await update.message.reply_text(
        "🎉 <b>کار جدید تحلیل و ثبت شد! (+10 XP)</b>\n\n" + fmt_task_advanced(task),
        parse_mode="HTML",
        reply_markup=main_reply_keyboard()
    )
    await cmd_list(update, ctx)
    return ConversationHandler.END


async def cmd_pomo_info(update: Update, _: ContextTypes.DEFAULT_TYPE):
    intro = (
        "🍅 <b>تکنیک پومودورو (Pomodoro Technique)</b>\n"
        "───────────────────────\n"
        "۲۵ دقیقه تمرکز کاملاً عمیق + ۵ دقیقه استراحت.\n"
        "💡 <i>جهت شروع، روی دکمه «🍅 پومودورو» زیر هر کار در لیست کلیک کنید!</i>"
    )
    await update.message.reply_text(intro, parse_mode="HTML", reply_markup=main_reply_keyboard())


async def cb_pomo_start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("🍅 جلسه پومودورو شروع شد!")
    tid = int(q.data.split(":")[1])

    await q.edit_message_text(q.message.text + "\n\n🍅 <b>جلسه تمرکز در حال انجام است...</b>", parse_mode="HTML")
    await asyncio.sleep(2)
    await db_increment_pomo(tid)
    await db_add_xp(update.effective_user.id, 25)

    await _bot.send_message(
        chat_id=update.effective_user.id,
        text="🎉 <b>جلسه پومودورو به پایان رسید! (+25 XP)</b> ☕",
        parse_mode="HTML",
        reply_markup=main_reply_keyboard()
    )


async def cmd_habits(update: Update, _: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    habits = await db_get_habits(uid)
    intro = "🌱 <b>ردیاب عادت‌ها و زنجیره استمرار (Habits)</b>\n───────────────────────\n"

    if not habits:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ تعریف عادت جدید", callback_data="add_habit_btn")]])
        await update.message.reply_text(intro + "<i>هنوز عادتی ثبت نکرده‌اید.</i>", parse_mode="HTML", reply_markup=kb)
        return

    text = intro + "📋 <b>عادت‌های شما:</b>\n"
    kb_btns = []
    for h in habits:
        text += f"• <b>{h['title']}</b> ➔ 🔥 <code>{h['streak']}</code> روز استمرار\n"
        kb_btns.append([
            InlineKeyboardButton(f"✅ ثبت امروز: {h['title']}", callback_data=f"checkin_habit:{h['id']}"),
            InlineKeyboardButton("🗑", callback_data=f"del_habit:{h['id']}")
        ])
    kb_btns.append([InlineKeyboardButton("➕ تعریف عادت جدید", callback_data="add_habit_btn")])
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_btns))


async def cb_add_habit_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.message.reply_text("🌱 <b>عنوان عادت جدید را وارد کنید:</b>", parse_mode="HTML")
    return ADD_HABIT_STATE


async def add_habit_process(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()
    uid = update.effective_user.id
    await db_add_habit(uid, title)
    await update.message.reply_text(f"🎉 عادت «<b>{title}</b>» اضافه شد!", parse_mode="HTML", reply_markup=main_reply_keyboard())
    return ConversationHandler.END


async def cb_checkin_habit(update: Update, _: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    hid = int(q.data.split(":")[1])
    await db_checkin_habit(hid)
    await db_add_xp(update.effective_user.id, 15)
    await q.answer("🔥 ۱ روز به زنجیره اضافه شد (+15 XP)!")
    await q.edit_message_text(q.message.text + "\n\n✅ <b>استمرار ثبت شد!</b>", parse_mode="HTML")


async def cb_del_habit(update: Update, _: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    hid = int(q.data.split(":")[1])
    await db_delete_habit(hid)
    await q.answer("🗑 حذف شد.")
    await q.delete_message()


async def cmd_eisenhower(update: Update, _: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    tasks = await db_get_tasks(uid)
    intro = "📐 <b>ماتریس 4 گانه آیزنهاور (Eisenhower Matrix)</b>\n───────────────────────\n"

    q1 = [t['title'] for t in tasks if t['is_urgent'] and t['is_important']]
    q2 = [t['title'] for t in tasks if not t['is_urgent'] and t['is_important']]
    q3 = [t['title'] for t in tasks if t['is_urgent'] and not t['is_important']]
    q4 = [t['title'] for t in tasks if not t['is_urgent'] and not t['is_important']]

    matrix_text = (
        "🔥 <b>۱. فوری و مهم (انجام دهید):</b>\n" + ("\n".join([f"• {x}" for x in q1]) if q1 else "<i>خالی</i>") + "\n\n"
        "📅 <b>۲. غیرفوری ولی مهم (زمان‌بندی کنید):</b>\n" + ("\n".join([f"• {x}" for x in q2]) if q2 else "<i>خالی</i>") + "\n\n"
        "⚡ <b>۳. فوری ولی کم‌اهمیت (واگذار کنید):</b>\n" + ("\n".join([f"• {x}" for x in q3]) if q3 else "<i>خالی</i>") + "\n\n"
        "🟢 <b>۴. غیرفوری و کم‌اهمیت (حذف کنید):</b>\n" + ("\n".join([f"• {x}" for x in q4]) if q4 else "<i>خالی</i>")
    )
    await update.message.reply_text(intro + matrix_text, parse_mode="HTML", reply_markup=main_reply_keyboard())


async def cmd_notes(update: Update, _: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    notes = await db_get_notes(uid)
    intro = "📝 <b>دفترچه یادداشت سریع (Notion Style)</b>\n───────────────────────\n"

    if not notes:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ ثبت یادداشت جدید", callback_data="add_note_btn")]])
        await update.message.reply_text(intro + "<i>یادداشتی وجود ندارد.</i>", parse_mode="HTML", reply_markup=kb)
        return

    text = intro + "📋 <b>آخرین یادداشت‌های شما:</b>\n"
    kb_btns = []
    for n in notes:
        text += f"▫️ {n['content']} <code>({n['created_at'][:10]})</code>\n"
        kb_btns.append([InlineKeyboardButton(f"🗑 حذف: {n['content'][:20]}...", callback_data=f"del_note:{n['id']}")])
    kb_btns.append([InlineKeyboardButton("➕ ثبت یادداشت جدید", callback_data="add_note_btn")])
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_btns))


async def cb_add_note_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.message.reply_text("📝 <b>متن یادداشت را وارد کنید:</b>", parse_mode="HTML")
    return ADD_NOTE_STATE


async def add_note_process(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    content = update.message.text.strip()
    await db_add_note(update.effective_user.id, content)
    await update.message.reply_text("✅ یادداشت ذخیره گردید!", parse_mode="HTML", reply_markup=main_reply_keyboard())
    return ConversationHandler.END


async def cb_del_note(update: Update, _: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    nid = int(q.data.split(":")[1])
    await db_delete_note(nid)
    await q.answer("🗑 حذف شد.")
    await q.delete_message()


async def cb_add_subtask_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    tid = int(q.data.split(":")[1])
    ctx.user_data["target_task_id"] = tid
    await q.message.reply_text("☑️ <b>عنوان زیرکار (Subtask) را وارد کنید:</b>", parse_mode="HTML")
    return ADD_SUBTASK_STATE


async def add_subtask_process(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()
    tid = ctx.user_data.get("target_task_id")
    await db_add_subtask(tid, title)
    task = await db_get_task(tid)
    subs = await db_get_subtasks(tid)

    await update.message.reply_text("✅ <b>زیرکار اضافه شد:</b>\n\n" + fmt_task_advanced(task, subs), parse_mode="HTML", reply_markup=main_reply_keyboard())
    return ConversationHandler.END


async def cb_toggle_subtask(update: Update, _: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split(":")
    sub_id, task_id = int(parts[1]), int(parts[2])
    await db_toggle_subtask(sub_id)
    await q.answer("تغییر وضعیت ثبت شد.")
    task = await db_get_task(task_id)
    subs = await db_get_subtasks(task_id)
    await q.edit_message_text(fmt_task_advanced(task, subs), parse_mode="HTML", reply_markup=task_action_kb(task_id, subs))


async def cb_done_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    tid = int(q.data.split(":")[1])
    uid = update.effective_user.id
    await db_mark_done(tid)
    res = await db_add_xp(uid, 20)

    msg = "✅ <b>این کار انجام شد (+20 XP)!</b>"
    if res.get("leveled_up"):
        msg += f"\n🎉 <b>تبریک! ارتقاء به Level {res['level']}!</b>"

    await q.answer("✅ انجام شد!")
    await q.edit_message_text(q.message.text + f"\n\n{msg}", parse_mode="HTML")


async def cb_del_task(update: Update, _: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    tid = int(q.data.split(":")[1])
    await db_delete_task(tid)
    await q.answer("🗑 حذف شد.")
    await q.delete_message()

# ═══════════════════════════════════════════════════════════════════════════════
# WEB API SERVER (FULL REST API & CORS SUPPORT)
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_get_tasks(request):
    user_id = request.query.get("user_id")
    if not user_id:
        return web.json_response({"error": "user_id is required"}, status=400)
    tasks = await db_get_tasks(int(user_id))
    
    # همگام‌سازی زیرکارها برای وب‌اپ
    for t in tasks:
        t["subtasks"] = await db_get_subtasks(t["id"])
        
    return web.json_response({"status": "success", "tasks": tasks})

async def handle_post_task(request):
    try:
        data = await request.json()
        tid = await db_add_task(
            user_id=int(data["user_id"]),
            title=data["title"],
            description=data.get("description", ""),
            category=data.get("category", "Personal"),
            priority=data.get("priority", "Medium"),
            due_date=data.get("due_date"),
            is_urgent=data.get("is_urgent", 0),
            is_important=data.get("is_important", 1)
        )
        return web.json_response({"status": "success", "id": tid})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_put_task(request):
    try:
        data = await request.json()
        await db_update_task(
            task_id=int(data["task_id"]),
            title=data["title"],
            description=data.get("description", ""),
            category=data.get("category", "Personal"),
            priority=data.get("priority", "Medium"),
            due_date=data.get("due_date"),
            is_urgent=data.get("is_urgent", 0),
            is_important=data.get("is_important", 1)
        )
        return web.json_response({"status": "success"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_delete_task(request):
    try:
        task_id = request.match_info.get("id")
        await db_delete_task(int(task_id))
        return web.json_response({"status": "success"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_mark_done(request):
    try:
        task_id = int(request.match_info.get("id"))
        task = await db_get_task(task_id)
        if not task:
            return web.json_response({"error": "Task not found"}, status=404)

        await db_mark_done(task_id)
        xp_res = await db_add_xp(task["user_id"], 20)
        
        return web.json_response({
            "status": "success",
            "xp_gained": 20,
            "level": xp_res.get("level"),
            "xp": xp_res.get("xp"),
            "leveled_up": xp_res.get("leveled_up", False)
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_get_stats(request):
    user_id = request.query.get("user_id")
    if not user_id: return web.json_response({"error": "user_id required"}, status=400)
    prof = await db_get_user_profile(int(user_id))
    return web.json_response({"status": "success", "profile": prof})

async def handle_get_notes(request):
    user_id = request.query.get("user_id")
    if not user_id:
        return web.json_response({"error": "user_id is required"}, status=400)
    
    notes = await db_get_notes(int(user_id))
    notes_list = [{"id": n["id"], "content": n["content"], "created_at": n["created_at"]} for n in notes]
    return web.json_response({"status": "success", "notes": notes_list})

async def handle_post_note(request):
    try:
        data = await request.json()
        await db_add_note(
            user_id=int(data["user_id"]),
            content=data["content"]
        )
        return web.json_response({"status": "success"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_delete_note(request):
    try:
        note_id = request.match_info.get("id")
        user_id = request.query.get("user_id", 0)
        await db_delete_note(int(note_id), int(user_id))
        return web.json_response({"status": "success"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def start_web_server():
    app = web.Application()
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(allow_credentials=True, expose_headers="*", allow_headers="*", allow_methods="*")
    })

    cors.add(app.router.add_get("/api/tasks", handle_get_tasks))
    cors.add(app.router.add_post("/api/tasks", handle_post_task))
    cors.add(app.router.add_put("/api/tasks", handle_put_task))
    cors.add(app.router.add_delete("/api/tasks/{id}", handle_delete_task))
    cors.add(app.router.add_post("/api/tasks/{id}/done", handle_mark_done))
    cors.add(app.router.add_get("/api/stats", handle_get_stats))
    cors.add(app.router.add_get("/api/notes", handle_get_notes))
    cors.add(app.router.add_post("/api/notes", handle_post_note))
    cors.add(app.router.add_delete("/api/notes/{id}", handle_delete_note))

    port = int(os.environ.get("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info(f"Enterprise Web Server Online on Port {port} 🌐")

# ═══════════════════════════════════════════════════════════════════════════════
# ENGINE SETUP & MAIN RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

async def post_init(application: Application):
    await application.bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="todo-list", web_app=WebAppInfo(url=WEBAPP_URL))
    )
    start_scheduler(application.bot)

# --- TELEGRAM HANDLERS: NOTES ---

async def cmd_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    notes = await db_get_notes(user_id)
    
    if not notes:
        await update.message.reply_text("📝 دفترچه یادداشت شما خالی است.\nمی‌توانید از طریق وب‌اپ یادداشت جدید اضافه کنید.")
        return

    text = "📝 <b>دفترچه یادداشت‌های شما:</b>\n───────────────────────\n"
    buttons = []
    for n in notes:
        text += f"🔹 {n['content']}\n🕒 <i>{n['created_at']}</i>\n───────────────────────\n"
        buttons.append([InlineKeyboardButton(f"🗑 حذف: {n['content'][:20]}...", callback_data=f"del_note:{n['id']}")])

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

async def cb_del_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user_id = q.from_user.id
    note_id = int(q.data.split(":")[1])
    
    await db_delete_note(note_id, user_id)
    await q.answer("یادداشت با موفقیت حذف شد!", show_alert=True)
    
    # به‌روزرسانی لیست بعد از حذف
    notes = await db_get_notes(user_id)
    if not notes:
        await q.edit_message_text("📝 دفترچه یادداشت شما خالی است.")
        return
    
    text = "📝 <b>دفترچه یادداشت‌های شما:</b>\n───────────────────────\n"
    buttons = []
    for n in notes:
        text += f"🔹 {n['content']}\n🕒 <i>{n['created_at']}</i>\n───────────────────────\n"
        buttons.append([InlineKeyboardButton(f"🗑 حذف: {n['content'][:20]}...", callback_data=f"del_note:{n['id']}")])
    
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # بررسی دسترسی مدیر
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ شما دسترسی مدیریت این ربات را ندارید.")
        return

    stats = await db_get_admin_stats()
    
    text = (
        "👑 <b>پنل مدیریت و کنترل ربات</b>\n"
        "───────────────────────\n"
        f"👥 <b>تعداد کل کاربران:</b> <code>{stats['total_users']}</code> نفر\n"
        f"📋 <b>تعداد کل وظایف:</b> <code>{stats['total_tasks']}</code> عدد\n"
        f"✅ <b>وظایف انجام‌شده:</b> <code>{stats['done_tasks']}</code> عدد\n"
    )
    
    # دکمه لیست و نظارت بر کاربران اضافه شد
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 لیست و نظارت بر کاربران", callback_data="admin_users_list_1")],
        [InlineKeyboardButton("📦 دانلود فایل پشتیبان (Backup)", callback_data="admin_backup")]
    ])
    
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)

async def cb_admin_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    
    # ۱. بررسی مجدد دسترسی مدیر
    if q.from_user.id != ADMIN_ID:
        await q.answer("⛔ شما دسترسی مدیریت ندارید!", show_alert=True)
        return

    await q.answer("در حال آماده‌سازی و ارسال فایل دیتابیس...")
    
    # ۲. خواندن فایل دیتابیس و ارسال به عنوان سندی در تلگرام
    try:
        with open(DB_PATH, "rb") as db_file:
            await context.bot.send_document(
                chat_id=q.from_user.id,
                document=InputFile(db_file),
                caption="📦 <b>فایل پشتیبان دیتابیس ربات</b>",
                parse_mode="HTML"
            )
    except Exception as e:
        await q.message.reply_text(f"❌ خطا در ارسال بکاپ: {str(e)}")

async def cb_admin_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        await q.answer("⛔ عدم دسترسی!", show_alert=True)
        return

    page = int(q.data.split("_")[-1])
    users, total = await db_get_users_list(page=page)
    
    text = f"👥 <b>لیست کاربران ربات (صفحه {page}):</b>\n"
    text += f"تعداد کل: {total} نفر\n───────────────────────\n"
    
    buttons = []
    for u in users:
        u_id, f_name, u_name, lvl, xp = u
        display_name = f_name or u_name or f"کاربر {u_id}"
        text += f"👤 <b>{display_name}</b> | Lvl {lvl} | ID: <code>{u_id}</code>\n"
        buttons.append([InlineKeyboardButton(f"🔍 جزئیات: {display_name}", callback_data=f"admin_uinfo_{u_id}")])
    
    # دکمه‌های صفحه قبل و بعدی
    nav_btns = []
    if page > 1:
        nav_btns.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"admin_users_list_{page-1}"))
    if total > page * 5:
        nav_btns.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"admin_users_list_{page+1}"))
    
    if nav_btns:
        buttons.append(nav_btns)
        
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

async def cb_admin_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        await q.answer("⛔ عدم دسترسی!", show_alert=True)
        return

    target_id = int(q.data.split("_")[-1])
    user, tasks = await db_get_user_full_details(target_id)
    
    if not user:
        await q.answer("کاربر یافت نشد!", show_alert=True)
        return

    text = (
        f"👤 <b>جزئیات کامل کاربر:</b>\n"
        f"▪️ نام: {user['first_name'] or 'ثبت نشده'}\n"
        f"▪️ نام کاربری: @{user['username'] if user['username'] else 'ندارد'}\n"
        f"▪️ شناسه عددی: <code>{user['user_id']}</code>\n"
        f"▪️ سطح (Level): <code>{user['level']}</code> (XP: {user['xp']})\n"
        f"───────────────────────\n"
        f"📋 <b>آخرین کارهای ثبت‌شده توسط کاربر:</b>\n"
    )
    
    if tasks:
        for t in tasks:
            status_icon = "✅" if t['status'] == 'done' else "⏳"
            text += f"{status_icon} <b>{t['title']}</b> ({t['category']})\n"
    else:
        text += "هیچ کاری توسط این کاربر ثبت نشده است.\n"
        
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به لیست کاربران", callback_data="admin_users_list_1")]])
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)

async def main_async():
    await init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # 1. Conversation Handler کامل ثبت کار با قابلیت عقب رفتن
    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add", add_start),
            MessageHandler(filters.Regex("^➕ افزودن کار جدید$"), add_start)
        ],
        states={
            ADD_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_title),
                CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")
            ],
            ADD_DESC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_desc),
                CommandHandler("skip", add_got_desc),
                CallbackQueryHandler(add_start, pattern=r"^goto:title$"),
                CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")
            ],
            ADD_CAT: [
                CallbackQueryHandler(add_got_cat, pattern=r"^cat:"),
                CallbackQueryHandler(add_got_title, pattern=r"^goto:desc$"),
                CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")
            ],
            ADD_PRI: [
                CallbackQueryHandler(add_got_pri, pattern=r"^pri:"),
                CallbackQueryHandler(add_got_desc, pattern=r"^goto:cat$"),
                CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")
            ],
            ADD_EISENHOWER: [
                CallbackQueryHandler(add_got_eisenhower, pattern=r"^eisen:"),
                CallbackQueryHandler(add_got_cat, pattern=r"^goto:pri$"),
                CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")
            ],
            ADD_DUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_due),
                CommandHandler("skip", add_got_due),
                CallbackQueryHandler(add_got_pri, pattern=r"^goto:eisen$"),
                CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")
            ],
            ADD_REC: [
                CallbackQueryHandler(add_got_rec, pattern=r"^rec:"),
                CallbackQueryHandler(add_got_eisenhower, pattern=r"^goto:due$"),
                CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel), CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")],
        per_user=True,
    )

    # 2. Conversation Handler ثبت سریع تک‌خطی
    quick_add_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^⚡ ثبت سریع کار$"), quick_add_start)],
        states={
            QUICK_ADD_STATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, quick_add_process),
                CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")
            ]
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True,
    )

    # 3. Conversation Handler زیرکارها
    subtask_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_add_subtask_start, pattern=r"^add_sub:")],
        states={ADD_SUBTASK_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_subtask_process)]},
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True
    )

    # 4. Conversation Handler عادت‌ها
    habit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_add_habit_start, pattern="^add_habit_btn$")],
        states={ADD_HABIT_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_habit_process)]},
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True
    )

    # 5. Conversation Handler یادداشت‌ها
    note_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_add_note_start, pattern="^add_note_btn$")],
        states={ADD_NOTE_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_note_process)]},
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True
    )

    # ثبت هندلرها
    app.add_handler(add_conv)
    app.add_handler(quick_add_conv)
    app.add_handler(subtask_conv)
    app.add_handler(habit_conv)
    app.add_handler(note_conv)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(MessageHandler(filters.Regex("^📋 کارهای فعال من$"), cmd_list))
    app.add_handler(MessageHandler(filters.Regex("^🍅 پومودورو تمرکز$"), cmd_pomo_info))
    app.add_handler(MessageHandler(filters.Regex("^🌱 ردیاب عادت‌ها$"), cmd_habits))
    app.add_handler(MessageHandler(filters.Regex("^📐 ماتریس آیزنهاور$"), cmd_eisenhower))
    app.add_handler(MessageHandler(filters.Regex("^📝 دفترچه یادداشت Notion$"), cmd_notes))
    app.add_handler(MessageHandler(filters.Regex("^🏆 پروفایل & مدال‌ها$"), cmd_profile))
    app.add_handler(MessageHandler(filters.Regex("^📊 گزارش CSV$"), cmd_export))
    app.add_handler(MessageHandler(filters.Regex("^✅ کارهای انجام‌شده$"), cmd_done_list))

    app.add_handler(CallbackQueryHandler(cb_done_task, pattern=r"^done:"))
    app.add_handler(CallbackQueryHandler(cb_del_task, pattern=r"^del_task:"))
    app.add_handler(CallbackQueryHandler(cb_pomo_start, pattern=r"^pomo_start:"))
    app.add_handler(CallbackQueryHandler(cb_checkin_habit, pattern=r"^checkin_habit:"))
    app.add_handler(CallbackQueryHandler(cb_del_habit, pattern=r"^del_habit:"))
    app.add_handler(CallbackQueryHandler(cb_del_note, pattern=r"^del_note:"))
    app.add_handler(CallbackQueryHandler(cb_toggle_subtask, pattern=r"^toggle_sub:"))
    app.add_handler(CallbackQueryHandler(cb_admin_backup, pattern="^admin_backup$"))
    app.add_handler(CallbackQueryHandler(cb_admin_users_list, pattern="^admin_users_list_"))
    app.add_handler(CallbackQueryHandler(cb_admin_user_info, pattern="^admin_uinfo_"))

    await start_web_server()

    async with app:
        await app.initialize()
        await app.start()
        log.info("System Ready & Running Smoothly 🚀")
        await app.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main_async())
