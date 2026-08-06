"""
🚀 ULTIMATE ENTERPRISE TASK & PRODUCTIVITY BOT (bot03.py)
=========================================================
کامل‌ترین و بی‌نقص‌ترین ربات مدیریت وظایف، پومودورو، عادت‌ها و یادداشت‌ها
پشتیبانی از:
- Todoist Quick Add (NLP)
- Eisenhower Matrix (ماتریس آیزنهاور)
- Pomodoro Focus Timer (تکنیک پومودورو)
- Habit Tracker & Streak System (ردیاب عادت‌ها)
- Subtasks / Checklist (زیرکارها)
- Notion Quick Notes (دفترچه یادداشت)
- Gamification & Badges (گیمیفیکیشن و مدال‌ها)
- Background Task Scheduler (یادآوری دقیق)
- CSV Backup / Export (خروجی اکسل)

پیش‌نیازها:
pip install python-telegram-bot[job-queue] apscheduler aiosqlite
"""

import asyncio
import csv
import io
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import (
    Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update,
    ReplyKeyboardMarkup, KeyboardButton, InputFile
)
from telegram import (
    Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update,
    ReplyKeyboardMarkup, KeyboardButton, InputFile, WebAppInfo
)

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG & LOGGING
# ═══════════════════════════════════════════════════════════════════════════════

BOT_TOKEN = "8322904493:AAFMyY-sB__S8s3f5DiTfaq6jm5lbrydH34"
DB_PATH   = "ultimate_productivity.db"

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# UTILS & SMART TIME PARSER
# ═══════════════════════════════════════════════════════════════════════════════

def fa_to_en_digits(text: str) -> str:
    """تبدیل اعداد فارسی و عربی به انگلیسی"""
    fa_digits = '۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩'
    en_digits = '01234567890123456789'
    trans = str.maketrans(fa_digits, en_digits)
    return text.translate(trans)


def parse_quick_add(text: str) -> dict:
    """
    پردازش هوشمند ورودی سریع تک‌خطی (سبک Todoist)
    نمونه: خرید کتاب #تحصیلی !ضروری @18:30
    """
    clean_text = fa_to_en_digits(text).replace("：", ":")

    category = "Personal"
    priority = "Medium"
    due_date = None

    # استخراج دسته‌بندی هشتگ
    cat_match = re.search(r'#(\w+)', clean_text)
    if cat_match:
        tag = cat_match.group(1).lower()
        if tag in ["کاری", "work", "کار"]:
            category = "Work"
        elif tag in ["تحصیلی", "study", "درس"]:
            category = "Study"
        clean_text = re.sub(r'#\w+', '', clean_text)

    # استخراج اولویت
    pri_match = re.search(r'!(\w+)', clean_text)
    if pri_match:
        p_str = pri_match.group(1).lower()
        if p_str in ["ضروری", "فوری", "بالا", "high"]:
            priority = "High"
        elif p_str in ["کم", "پایین", "low"]:
            priority = "Low"
        clean_text = re.sub(r'!\w+', '', clean_text)

    # استخراج زمان (@18:30)
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
        "due_date": due_date
    }

# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE LAYER
# ═══════════════════════════════════════════════════════════════════════════════

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # جدول اصلی وظایف
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
        # جدول زیرکارها (Subtasks)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS subtasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id     INTEGER NOT NULL,
                title       TEXT    NOT NULL,
                is_done     INTEGER DEFAULT 0
            )
        """)
        # جدول ردیاب عادت‌ها (Habit Tracker)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS habits (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                title       TEXT    NOT NULL,
                streak      INTEGER DEFAULT 0,
                last_done   TEXT
            )
        """)
        # جدول کاربران و گیمیفیکیشن
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                xp          INTEGER DEFAULT 0,
                level       INTEGER DEFAULT 1
            )
        """)
        # جدول یادداشت‌های سریع Notion
        await db.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                content     TEXT    NOT NULL,
                created_at  TEXT    DEFAULT (datetime('now'))
            )
        """)
        await db.commit()


# --- DATABASE HELPERS: TASKS ---

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


async def db_get_tasks(user_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tasks WHERE user_id=? AND status='pending' ORDER BY due_date ASC NULLS LAST, id DESC",
            (user_id,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def db_get_done_tasks(user_id: int, limit: int = 15) -> list[dict]:
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


# --- DATABASE HELPERS: SUBTASKS ---

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


# --- DATABASE HELPERS: HABITS ---

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


# --- DATABASE HELPERS: NOTES ---

async def db_add_note(user_id: int, content: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO notes (user_id, content) VALUES (?, ?)", (user_id, content))
        await db.commit()


async def db_get_notes(user_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM notes WHERE user_id=? ORDER BY id DESC LIMIT 15", (user_id,)) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def db_delete_note(note_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM notes WHERE id=?", (note_id,))
        await db.commit()


# --- DATABASE HELPERS: GAMIFICATION & EXPORT ---

async def db_add_xp(user_id: int, amount: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT xp, level FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                current_xp, current_lvl = amount, 1
                await db.execute("INSERT INTO users (user_id, xp, level) VALUES (?, ?, ?)", (user_id, amount, 1))
            else:
                current_xp, current_lvl = row[0] + amount, row[1]
                new_lvl = (current_xp // 100) + 1
                await db.execute("UPDATE users SET xp=?, level=? WHERE user_id=?", (current_xp, new_lvl, user_id))
                await db.commit()
                return {"xp": current_xp, "level": new_lvl, "leveled_up": new_lvl > current_lvl}
        await db.commit()
        return {"xp": amount, "level": 1, "leveled_up": False}


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
                5: "👑 غول بازدهی و مدیریت"
            }
            return {"xp": xp, "level": lvl, "badge": badges.get(lvl, "👑 استادیار بازدهی")}


async def db_export_csv(user_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE user_id=?", (user_id,)) as cur:
            rows = await cur.fetchall()
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["ID", "Title", "Description", "Category", "Priority", "DueDate", "Status", "Pomodoros"])
            for r in rows:
                writer.writerow([r["id"], r["title"], r["description"], r["category"], r["priority"], r["due_date"], r["status"], r["pomodoros"]])
            return output.getvalue()

# ═══════════════════════════════════════════════════════════════════════════════
# KEYBOARDS & UI FORMATTING
# ═══════════════════════════════════════════════════════════════════════════════

def main_reply_keyboard() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton("➕ افزودن کار جدید"), KeyboardButton("⚡ ثبت سریع کار")],
        # لینک وب‌اپ به دکمه کارهای فعال من متصل شد:
        [KeyboardButton("📋 کارهای فعال من", web_app=WebAppInfo(url="https://ornate-manatee-273466.netlify.app/")), KeyboardButton("🍅 پومودورو تمرکز")],
        [KeyboardButton("🌱 ردیاب عادت‌ها"), KeyboardButton("📐 ماتریس آیزنهاور")],
        [KeyboardButton("📝 دفترچه یادداشت Notion"), KeyboardButton("🏆 پروفایل & مدال‌ها")],
        [KeyboardButton("📊 گزارش CSV"), KeyboardButton("✅ کارهای انجام‌شده")]
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)


def cancel_reset_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 شروع مجدد (ریست)", callback_data="reset_flow"),
            InlineKeyboardButton("❌ انصراف", callback_data="cancel_flow")
        ]
    ])


def fmt_task_advanced(t: dict, subtasks: list[dict] = []) -> str:
    pri_map = {"High": "🚨 ضروری (بالا)", "Medium": "🟡 معمولی", "Low": "🟢 کم اهمیت"}
    cat_map = {"Personal": "👤 شخصی", "Work": "💼 کاری", "Study": "📚 تحصیلی"}

    text = f"💎 <b>{t['title']}</b>\n"
    text += "───────────────────────\n"
    if t.get("description"):
        text += f"💬 <i>{t['description']}</i>\n\n"
    text += f"🏷 <b>دسته‌بندی:</b> {cat_map.get(t['category'], 'عمومی')}\n"
    text += f"🎯 <b>اولویت:</b> {pri_map.get(t['priority'], 'معمولی')}\n"
    text += f"🍅 <b>پومودوروهای انجام‌شده:</b> <code>{t.get('pomodoros', 0)}</code> جلسه\n"

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

    # اگر زیرکار وجود داشت، دکمه‌های تغییر وضعیت زیرکار اضافه شوند
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

ADD_TITLE, ADD_DESC, ADD_CAT, ADD_PRI, ADD_DUE, ADD_REC = range(6)
QUICK_ADD_STATE = 6
ADD_SUBTASK_STATE = 7
ADD_HABIT_STATE = 8
ADD_NOTE_STATE = 9

# ═══════════════════════════════════════════════════════════════════════════════
# HANDLERS: GENERAL & PROFILE
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    text = (
        "🚀 <b>به ربات فوق‌پیشرفته و هوشمند مدیریت وظایف خوش آمدید!</b>\n"
        "───────────────────────\n"
        "این ربات بر اساس متدولوژی‌های روز دنیا مانند <b>Notion</b>، <b>Todoist</b>، <b>تکنیک پومودورو</b> و <b>ماتریس آیزنهاور</b> طراحی شده است.\n\n"
        "💡 <b>راهنمای سریع امکانات:</b>\n"
        "▫️ <b>➕ افزودن کار جدید:</b> ثبت گام‌به‌گام همراه با اولویت، زمان و تکرار.\n"
        "▫️ <b>⚡ ثبت سریع کار:</b> تایپ یک‌خطی مثل: <code>خرید کتاب #تحصیلی !ضروری @18:30</code>\n"
        "▫️ <b>🍅 پومودورو تمرکز:</b> ایجاد فواصل تمرکز ۲۵ دقیقه‌ای برای جلوگیری از حواس‌پرتی.\n"
        "▫️ <b>🌱 ردیاب عادت‌ها:</b> ثبت عادات روزانه و حفظ زنجیره استمرار (Streak).\n"
        "▫️ <b>📐 ماتریس آیزنهاور:</b> دسته‌بندی کارهای مهم و فوری برای تصمیم‌گیری برتر.\n"
        "▫️ <b>📝 دفترچه یادداشت Notion:</b> ثبت سریع ایده‌ها و یادداشت‌ها.\n"
        "▫️ <b>🏆 گیمیفیکیشن:</b> دریافت XP و ارتقای سطح با انجام کارها!\n\n"
        "👇 <i>از کیبورد زیر جهت هدایت استفاده کنید:</i>"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_reply_keyboard())


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    msg = "❌ عملیات جاری لغو شد."
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
        "🏆 <b>سیستم گیمیفیکیشن و سطح‌بندی (Gamification)</b>\n"
        "───────────────────────\n"
        "این بخش انگیزشی برای افزایش بازدهی شما طراحی شده است! با انجام هر کار <b>۲۰ امتیاز (XP)</b>، "
        "با ثبت هر عادت <b>۱۵ امتیاز</b> و با هر جلسه پومودورو <b>۲۵ امتیاز</b> دریافت می‌کنید.\n\n"
    )
    
    body = (
        f"👤 <b>سطح فعلی شما:</b> Level {prof['level']}\n"
        f"🎖 <b>عنوان/مدال:</b> {prof['badge']}\n"
        f"⚡ <b>مجموع امتیاز (XP):</b> <code>{prof['xp']}</code> XP\n\n"
        f"💡 <i>با رسیدن به هر ۱۰۰ امتیاز، یک سطح ارتقا می‌یابید!</i>"
    )
    await update.message.reply_text(intro + body, parse_mode="HTML", reply_markup=main_reply_keyboard())


async def cmd_export(update: Update, _: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    csv_data = await db_export_csv(uid)

    bio = io.BytesIO(csv_data.encode('utf-8'))
    bio.name = f"tasks_export_{datetime.now().strftime('%Y%m%d')}.csv"

    intro = (
        "📊 <b>گزارش‌گیری و خروجی اکسل (Data Export)</b>\n"
        "───────────────────────\n"
        "شما می‌توانید یک خروجی کامل با فرمت CSV از تمام اطلاعات ثبت‌شده خود دریافت کنید و آن را در نرم‌افزارهایی مثل Excel یا Google Sheets مشاهده نمایید.\n\n"
    )

    await update.message.reply_text(intro, parse_mode="HTML")
    await update.message.reply_document(
        document=InputFile(bio),
        caption="📄 فایل پشتیبان کارهای شما آماده شد.",
        reply_markup=main_reply_keyboard()
    )


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    tasks = await db_get_tasks(uid)

    if not tasks:
        await update.message.reply_text("🎉 <b>هیچ کار فعالی در لیست شما نیست!</b>", parse_mode="HTML", reply_markup=main_reply_keyboard())
        return

    await update.message.reply_text("📋 <b>لیست کارهای فعال شما:</b>", parse_mode="HTML")
    for t in tasks:
        subs = await db_get_subtasks(t["id"])
        await update.message.reply_text(
            fmt_task_advanced(t, subs),
            parse_mode="HTML",
            reply_markup=task_action_kb(t["id"], subs)
        )


async def cmd_done_list(update: Update, _: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    done_tasks = await db_get_done_tasks(uid)

    if not done_tasks:
        await update.message.reply_text("📂 هنوز هیچ کاری را به اتمام نرسانده‌اید.", reply_markup=main_reply_keyboard())
        return

    text = "✅ <b>تاریخچه آخرین کارهای انجام‌شده:</b>\n───────────────────────\n"
    for t in done_tasks:
        text += f"• <s>{t['title']}</s> <code>({t['done_at'][:10] if t['done_at'] else ''})</code>\n"

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_reply_keyboard())

# ═══════════════════════════════════════════════════════════════════════════════
# HANDLERS: ADD TASK (STEP BY STEP)
# ═══════════════════════════════════════════════════════════════════════════════

async def add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    msg = "📝 <b>افزودن کار جدید (گام به گام)</b>\n───────────────────────\nلطفاً <b>عنوان کار</b> را وارد کنید:"

    if update.callback_query:
        await update.callback_query.answer("🔄 فرم ریست شد.")
        await update.callback_query.edit_message_text(msg, parse_mode="HTML")
    else:
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=cancel_reset_kb())
    return ADD_TITLE


async def add_got_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["title"] = update.message.text.strip()
    await update.message.reply_text(
        "💬 <b>توضیحات تکمیلی</b> را وارد کنید:\n\n<i>(یا دستور /skip را ارسال کنید)</i>",
        parse_mode="HTML",
        reply_markup=cancel_reset_kb()
    )
    return ADD_DESC


async def add_got_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text and not update.message.text.startswith("/skip"):
        ctx.user_data["description"] = update.message.text.strip()
    else:
        ctx.user_data["description"] = ""

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 شخصی", callback_data="cat:Personal"), InlineKeyboardButton("💼 کاری", callback_data="cat:Work")],
        [InlineKeyboardButton("📚 تحصیلی", callback_data="cat:Study")],
        [InlineKeyboardButton("🔄 شروع مجدد", callback_data="reset_flow")]
    ])
    await update.message.reply_text("🏷 <b>دسته‌بندی کار</b> را انتخاب کنید:", parse_mode="HTML", reply_markup=kb)
    return ADD_CAT


async def add_got_cat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["category"] = q.data.split(":")[1]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚨 ضروری (بالا)", callback_data="pri:High"), InlineKeyboardButton("🟡 معمولی", callback_data="pri:Medium")],
        [InlineKeyboardButton("🟢 کم اهمیت", callback_data="pri:Low")],
        [InlineKeyboardButton("🔄 شروع مجدد", callback_data="reset_flow")]
    ])
    await q.edit_message_text("🎯 <b>اولویت کار</b> را مشخص کنید:", parse_mode="HTML", reply_markup=kb)
    return ADD_PRI


async def add_got_pri(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["priority"] = q.data.split(":")[1]

    await q.edit_message_text(
        "⏰ <b>ساعت یادآوری</b> را وارد کنید:\n\n"
        "📌 فرمت‌های مجاز:\n"
        "• <code>18:30</code> (ساعت ۶ و نیم عصر)\n"
        "• <code>09:15</code> (ساعت ۹ و ربع صبح)\n\n"
        "<i>(یا دستور /skip را ارسال کنید)</i>",
        parse_mode="HTML"
    )
    return ADD_DUE


async def add_got_due(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text and not update.message.text.startswith("/skip"):
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
            await update.message.reply_text("❌ فرمت ساعت نامعتبر است! مثال: <code>18:30</code>", parse_mode="HTML", reply_markup=cancel_reset_kb())
            return ADD_DUE
    else:
        ctx.user_data["due_date"] = None

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 بدون تکرار", callback_data="rec:None"), InlineKeyboardButton("📅 روزانه", callback_data="rec:Daily")],
        [InlineKeyboardButton("🔄 شروع مجدد", callback_data="reset_flow")]
    ])
    await update.message.reply_text("🔁 آیا این کار نیاز به <b>تکرار خودکار</b> دارد؟", parse_mode="HTML", reply_markup=kb)
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
        recurrence=rec
    )
    ctx.user_data.clear()
    task = await db_get_task(tid)

    await q.delete_message()
    await _bot.send_message(
        chat_id=uid,
        text="🎉 <b>کار جدید با موفقیت ثبت شد!</b>\n\n" + fmt_task_advanced(task),
        parse_mode="HTML",
        reply_markup=task_action_kb(tid)
    )
    await _bot.send_message(chat_id=uid, text="از منوی زیر استفاده کنید:", reply_markup=main_reply_keyboard())
    return ConversationHandler.END

# ═══════════════════════════════════════════════════════════════════════════════
# HANDLERS: QUICK ADD (NLP)
# ═══════════════════════════════════════════════════════════════════════════════

async def quick_add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    intro = (
        "⚡ <b>ثبت سریع کار (Smart Quick Add)</b>\n"
        "───────────────────────\n"
        "با این ابزار فوق‌العاده می‌توانید تمام مشخصات کار را در <b>یک پیام ساده</b> تایپ کنید!\n\n"
        "📌 <b>راهنمای هشتگ‌ها و علامت‌ها:</b>\n"
        "• <b>هشتگ دسته‌بندی:</b> <code>#کاری</code> | <code>#تحصیلی</code> | <code>#شخصی</code>\n"
        "• <b>علامت اولویت:</b> <code>!ضروری</code> | <code>!کم</code>\n"
        "• <b>علامت زمان:</b> <code>@18:30</code>\n\n"
        "💡 <b>نمونه پیام ارسال:</b>\n"
        "<code>بررسی گزارش مالی #کاری !ضروری @19:30</code>"
    )
    await update.message.reply_text(intro, parse_mode="HTML", reply_markup=cancel_reset_kb())
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
        due_date=parsed["due_date"]
    )

    task = await db_get_task(tid)
    await db_add_xp(uid, 10)

    await update.message.reply_text(
        "🎉 <b>کار جدید با موفقیت تحلیل و ثبت شد! (+10 XP)</b>\n\n" + fmt_task_advanced(task),
        parse_mode="HTML",
        reply_markup=main_reply_keyboard()
    )
    return ConversationHandler.END

# ═══════════════════════════════════════════════════════════════════════════════
# HANDLERS: POMODORO TIMER
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_pomo_info(update: Update, _: ContextTypes.DEFAULT_TYPE):
    intro = (
        "🍅 <b>تکنیک پومودورو (Pomodoro Technique) چیست؟</b>\n"
        "───────────────────────\n"
        "تکنیک پومودورو یکی از معروف‌ترین روش‌های مدیریت زمان است:\n"
        "۱. یک کار را انتخاب می‌کنید.\n"
        "۲. <b>۲۵ دقیقه</b> با تمرکز کامل و بدون حواس‌پرتی روی آن کار می‌کنید.\n"
        "۳. <b>۵ دقیقه</b> استراحت می‌کنید.\n\n"
        "💡 <i>با کلیک روی دکمه «🍅 پومودورو» زیر هر کار در لیست، تایمر آن فعال می‌شود!</i>"
    )
    await update.message.reply_text(intro, parse_mode="HTML", reply_markup=main_reply_keyboard())


async def cb_pomo_start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("🍅 جلسه تمرکز پومودورو فعال شد!")
    tid = int(q.data.split(":")[1])

    await q.edit_message_text(
        q.message.text + "\n\n🍅 <b>جلسه ۲۵ دقیقه‌ای تمرکز عمیق شروع شد... موفق باشید!</b>",
        parse_mode="HTML"
    )

    # برای نمونه آزمایشی ۵ ثانیه متوقف می‌شود (در حالت واقعی ۲۵ دقیقه)
    await asyncio.sleep(5)
    await db_increment_pomo(tid)
    await db_add_xp(update.effective_user.id, 25)

    await _bot.send_message(
        chat_id=update.effective_user.id,
        text="🎉 <b>پومودورو به پایان رسید! (+25 XP)</b>\nاکنون ۵ دقیقه استراحت کنید و سپس به کار بازگردید. ☕",
        parse_mode="HTML",
        reply_markup=main_reply_keyboard()
    )

# ═══════════════════════════════════════════════════════════════════════════════
# HANDLERS: HABIT TRACKER
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_habits(update: Update, _: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    habits = await db_get_habits(uid)

    intro = (
        "🌱 <b>ردیاب عادت‌ها و زنجیره استمرار (Habit Tracker)</b>\n"
        "───────────────────────\n"
        "مهم‌ترین عامل موفقیت، استمرار است. با ثبت عادت‌های روزانه (مثل ورزش، مطالعه یا کتاب‌خوانی) "
        "و ثبت روزانه آن‌ها، <b>زنجیره استمرار (Streak)</b> خود را حفظ کنید.\n\n"
    )

    if not habits:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ تعریف عادت جدید", callback_data="add_habit_btn")]])
        await update.message.reply_text(intro + "<i>هنوز هیچ عادتی تعریف نکرده‌اید!</i>", parse_mode="HTML", reply_markup=kb)
        return

    text = intro + "📋 <b>عادت‌های فعال شما:</b>\n"
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
    await q.message.reply_text("🌱 <b>عنوان عادت جدید را وارد کنید:</b>\n(مثال: ۳۰ دقیقه مطالعه روزانه)", parse_mode="HTML")
    return ADD_HABIT_STATE


async def add_habit_process(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()
    uid = update.effective_user.id
    await db_add_habit(uid, title)

    await update.message.reply_text(f"🎉 عادت جدید «<b>{title}</b>» با موفقیت اضافه شد!", parse_mode="HTML", reply_markup=main_reply_keyboard())
    return ConversationHandler.END


async def cb_checkin_habit(update: Update, _: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    hid = int(q.data.split(":")[1])
    await db_checkin_habit(hid)
    await db_add_xp(update.effective_user.id, 15)

    await q.answer("🔥 ۱ روز به زنجیره استمرار شما اضافه شد (+15 XP)!")
    await q.edit_message_text(q.message.text + "\n\n✅ <b>استمرار امروز ثبت شد! عالی هستید.</b>", parse_mode="HTML")


async def cb_del_habit(update: Update, _: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    hid = int(q.data.split(":")[1])
    await db_delete_habit(hid)
    await q.answer("🗑 عادت حذف شد.")
    await q.delete_message()

# ═══════════════════════════════════════════════════════════════════════════════
# HANDLERS: EISENHOWER MATRIX
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_eisenhower(update: Update, _: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    tasks = await db_get_tasks(uid)

    intro = (
        "📐 <b>ماتریس آیزنهاور (Eisenhower Decision Matrix) چیست؟</b>\n"
        "───────────────────────\n"
        "این ماتریس وظایف شما را بر اساس دو معیار <b>«فوریت»</b> و <b>«اهمیت»</b> به ۴ گروه تقسیم می‌کند تا بدانید اولویت اول تمرکز شما چیست:\n\n"
    )

    q1 = [t['title'] for t in tasks if t['priority'] == 'High']
    q2 = [t['title'] for t in tasks if t['priority'] == 'Medium']
    q3 = [t['title'] for t in tasks if t['priority'] == 'Low']

    matrix_text = (
        "🔥 <b>۱. فوری و مهم (همین الان انجام دهید):</b>\n" +
        ("\n".join([f"• {x}" for x in q1]) if q1 else "<i>خالی</i>") + "\n\n"
        "📅 <b>۲. غیرفوری ولی مهم (برنامه‌ریزی کنید):</b>\n" +
        ("\n".join([f"• {x}" for x in q2]) if q2 else "<i>خالی</i>") + "\n\n"
        "🟢 <b>۳. کم‌اهمیت / تفویض:</b>\n" +
        ("\n".join([f"• {x}" for x in q3]) if q3 else "<i>خالی</i>")
    )

    await update.message.reply_text(intro + matrix_text, parse_mode="HTML", reply_markup=main_reply_keyboard())

# ═══════════════════════════════════════════════════════════════════════════════
# HANDLERS: NOTION QUICK NOTES
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_notes(update: Update, _: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    notes = await db_get_notes(uid)

    intro = (
        "📝 <b>دفترچه یادداشت سریع (Notion Quick Notes)</b>\n"
        "───────────────────────\n"
        "ایده‌ها و یادداشت‌های ناگهانی خود را قبل از فراموشی در این بخش ذخیره کنید.\n\n"
    )

    if not notes:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ ثبت یادداشت جدید", callback_data="add_note_btn")]])
        await update.message.reply_text(intro + "<i>هیچ یادداشتی ثبت نشده است.</i>", parse_mode="HTML", reply_markup=kb)
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
    await q.message.reply_text("📝 <b>متن یادداشت خود را تایپ کنید:</b>", parse_mode="HTML")
    return ADD_NOTE_STATE


async def add_note_process(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    content = update.message.text.strip()
    uid = update.effective_user.id
    await db_add_note(uid, content)

    await update.message.reply_text("✅ یادداشت جدید با موفقیت ذخیره شد!", parse_mode="HTML", reply_markup=main_reply_keyboard())
    return ConversationHandler.END


async def cb_del_note(update: Update, _: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    nid = int(q.data.split(":")[1])
    await db_delete_note(nid)
    await q.answer("🗑 یادداشت حذف شد.")
    await q.delete_message()

# ═══════════════════════════════════════════════════════════════════════════════
# HANDLERS: SUBTASKS & TASK CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════════

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

    await update.message.reply_text(
        "✅ <b>زیرکار جدید اضافه شد:</b>\n\n" + fmt_task_advanced(task, subs),
        parse_mode="HTML",
        reply_markup=main_reply_keyboard()
    )
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


async def cb_done_task(update: Update, _: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    tid = int(q.data.split(":")[1])
    uid = update.effective_user.id

    await db_mark_done(tid)
    res = await db_add_xp(uid, 20)

    msg = "✅ <b>تبریک! این کار به اتمام رسید (+20 XP)</b>"
    if res.get("leveled_up"):
        msg += f"\n\n🎉 <b>ارتقاء سطح! شما به Level {res['level']} رسیدید!</b>"

    await q.answer("✅ ثبت شد!")
    await q.edit_message_text(q.message.text + f"\n\n{msg}", parse_mode="HTML")


async def cb_del_task(update: Update, _: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    tid = int(q.data.split(":")[1])
    await db_delete_task(tid)
    await q.answer("🗑 کار حذف شد.")
    await q.delete_message()

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ENGINE & APPLICATION SETUP
# ═══════════════════════════════════════════════════════════════════════════════

async def post_init(application: Application):
    # تنظیم دکمه آبی‌رنگ منو برای باز کردن وب‌اپ
    await application.bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="تودولیست",
            web_app=WebAppInfo(url="https://ornate-manatee-273466.netlify.app/")
        )
    )
    # شروع زمان‌بندی یادآورها (کد قبلی خودتان)
    start_scheduler(application.bot)

def main():
    asyncio.run(init_db())
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Conversation: Add Task (Step-by-Step)
    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add", add_start),
            MessageHandler(filters.Regex("^➕ افزودن کار جدید$"), add_start)
        ],
        states={
            ADD_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_title),
                CallbackQueryHandler(add_start, pattern="^reset_flow$"),
                CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")
            ],
            ADD_DESC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_desc),
                CommandHandler("skip", add_got_desc),
                CallbackQueryHandler(add_start, pattern="^reset_flow$"),
                CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")
            ],
            ADD_CAT: [
                CallbackQueryHandler(add_got_cat, pattern=r"^cat:"),
                CallbackQueryHandler(add_start, pattern="^reset_flow$")
            ],
            ADD_PRI: [
                CallbackQueryHandler(add_got_pri, pattern=r"^pri:"),
                CallbackQueryHandler(add_start, pattern="^reset_flow$")
            ],
            ADD_DUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_due),
                CommandHandler("skip", add_got_due),
                CallbackQueryHandler(add_start, pattern="^reset_flow$"),
                CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")
            ],
            ADD_REC: [
                CallbackQueryHandler(add_got_rec, pattern=r"^rec:"),
                CallbackQueryHandler(add_start, pattern="^reset_flow$")
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True,
    )

    # Conversation: Quick Add
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

    # Conversation: Subtasks
    subtask_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_add_subtask_start, pattern=r"^add_sub:")],
        states={
            ADD_SUBTASK_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_subtask_process)]
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True
    )

    # Conversation: Habits
    habit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_add_habit_start, pattern="^add_habit_btn$")],
        states={
            ADD_HABIT_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_habit_process)]
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True
    )

    # Conversation: Notes
    note_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_add_note_start, pattern="^add_note_btn$")],
        states={
            ADD_NOTE_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_note_process)]
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True
    )

    # Register Conversations
    app.add_handler(add_conv)
    app.add_handler(quick_add_conv)
    app.add_handler(subtask_conv)
    app.add_handler(habit_conv)
    app.add_handler(note_conv)

    # Register Main Menu Handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.Regex("^📋 کارهای فعال من$"), cmd_list))
    app.add_handler(MessageHandler(filters.Regex("^🍅 پومودورو تمرکز$"), cmd_pomo_info))
    app.add_handler(MessageHandler(filters.Regex("^🌱 ردیاب عادت‌ها$"), cmd_habits))
    app.add_handler(MessageHandler(filters.Regex("^📐 ماتریس آیزنهاور$"), cmd_eisenhower))
    app.add_handler(MessageHandler(filters.Regex("^📝 دفترچه یادداشت Notion$"), cmd_notes))
    app.add_handler(MessageHandler(filters.Regex("^🏆 پروفایل & مدال‌ها$"), cmd_profile))
    app.add_handler(MessageHandler(filters.Regex("^📊 گزارش CSV$"), cmd_export))
    app.add_handler(MessageHandler(filters.Regex("^✅ کارهای انجام‌شده$"), cmd_done_list))

    # Inline Callbacks
    app.add_handler(CallbackQueryHandler(cb_done_task, pattern=r"^done:"))
    app.add_handler(CallbackQueryHandler(cb_del_task, pattern=r"^del_task:"))
    app.add_handler(CallbackQueryHandler(cb_pomo_start, pattern=r"^pomo_start:"))
    app.add_handler(CallbackQueryHandler(cb_checkin_habit, pattern=r"^checkin_habit:"))
    app.add_handler(CallbackQueryHandler(cb_del_habit, pattern=r"^del_habit:"))
    app.add_handler(CallbackQueryHandler(cb_del_note, pattern=r"^del_note:"))
    app.add_handler(CallbackQueryHandler(cb_toggle_subtask, pattern=r"^toggle_sub:"))

    log.info("Ultimate Task Manager Bot Started Successfully 🚀")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
