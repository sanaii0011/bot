"""
🚀 ULTIMATE ENTERPRISE TASK & PRODUCTIVITY BOT + WEB API (bot03.py)
===================================================================
"""

import asyncio
import csv
import io
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Optional

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

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8322904493:AAFMyY-sB__S8s3f5DiTfaq6jm5lbrydH34")
DB_PATH   = "ultimate_productivity.db"
WEBAPP_URL = "https://ornate-manatee-273466.netlify.app/"

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# UTILS & DATABASE
# ═══════════════════════════════════════════════════════════════════════════════

def fa_to_en_digits(text: str) -> str:
    fa_digits = '۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩'
    en_digits = '01234567890123456789'
    trans = str.maketrans(fa_digits, en_digits)
    return text.translate(trans)

# --- DATABASE HELPERS ---
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
        await db.execute("CREATE TABLE IF NOT EXISTS subtasks (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL, title TEXT NOT NULL, is_done INTEGER DEFAULT 0)")
        await db.execute("CREATE TABLE IF NOT EXISTS habits (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, title TEXT NOT NULL, streak INTEGER DEFAULT 0, last_done TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, xp INTEGER DEFAULT 0, level INTEGER DEFAULT 1)")
        await db.execute("CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, content TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')))")
        await db.commit()

async def db_add_task(user_id: int, title: str, description: str = "", category: str = "Personal", priority: str = "Medium", due_date: Optional[str] = None, recurrence: str = "None") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("INSERT INTO tasks (user_id, title, description, category, priority, due_date, recurrence) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, title, description, category, priority, due_date, recurrence))
        await db.commit()
        return cursor.lastrowid

async def db_update_task(task_id: int, title: str, description: str, category: str, priority: str, due_date: Optional[str]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tasks SET title=?, description=?, category=?, priority=?, due_date=? WHERE id=?", 
                         (title, description, category, priority, due_date, task_id))
        await db.commit()

async def db_get_tasks(user_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE user_id=? AND status='pending' ORDER BY due_date ASC NULLS LAST, id DESC", (user_id,)) as cur:
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

# ═══════════════════════════════════════════════════════════════════════════════
# KEYBOARDS & UI FORMATTING
# ═══════════════════════════════════════════════════════════════════════════════

def main_reply_keyboard() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton("➕ افزودن کار جدید"), KeyboardButton("📋 کارهای فعال من")],
        [KeyboardButton("🌐 مدیریت حرفه‌ای در وب‌اپ", web_app=WebAppInfo(url=WEBAPP_URL))],
        [KeyboardButton("🍅 پومودورو تمرکز"), KeyboardButton("🌱 ردیاب عادت‌ها")],
        [KeyboardButton("✅ کارهای انجام‌شده")]
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def step_kb(back_callback: str = None) -> InlineKeyboardMarkup:
    btns = []
    if back_callback:
        btns.append(InlineKeyboardButton("🔙 مرحله قبل", callback_data=back_callback))
    btns.append(InlineKeyboardButton("❌ انصراف", callback_data="cancel_flow"))
    return InlineKeyboardMarkup([btns])

def fmt_task_advanced(t: dict) -> str:
    pri_map = {"High": "🚨 ضروری", "Medium": "🟡 معمولی", "Low": "🟢 کم اهمیت"}
    cat_map = {"Personal": "👤 شخصی", "Work": "💼 کاری", "Study": "📚 تحصیلی"}
    text = f"💎 <b>{t['title']}</b>\n───────────────────────\n"
    if t.get("description"): text += f"💬 <i>{t['description']}</i>\n\n"
    text += f"🏷 <b>دسته‌بندی:</b> {cat_map.get(t.get('category'), 'عمومی')}\n"
    text += f"🎯 <b>اولویت:</b> {pri_map.get(t.get('priority'), 'معمولی')}\n"
    if t.get("due_date"): text += f"⏰ <b>زمان:</b> <code>{t['due_date']}</code>\n"
    return text

def task_action_kb(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ انجام شد", callback_data=f"done:{task_id}"), InlineKeyboardButton("🍅 پومودورو", callback_data=f"pomo_start:{task_id}")],
        [InlineKeyboardButton("✏️ ویرایش وب‌اپ", web_app=WebAppInfo(url=WEBAPP_URL)), InlineKeyboardButton("🗑 حذف", callback_data=f"del_task:{task_id}")]
    ])

# ═══════════════════════════════════════════════════════════════════════════════
# CONVERSATION: ADD TASK WITH BACK NAVIGATION
# ═══════════════════════════════════════════════════════════════════════════════
ADD_TITLE, ADD_DESC, ADD_CAT, ADD_PRI, ADD_DUE = range(5)

async def add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = "📝 <b>افزودن کار جدید</b>\n───────────────────────\nلطفاً <b>عنوان کار</b> را وارد کنید:"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(msg, parse_mode="HTML", reply_markup=step_kb())
    else:
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=step_kb())
    return ADD_TITLE

async def add_got_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message: ctx.user_data["title"] = update.message.text.strip()
    msg = f"عنوان ثبت شد: {ctx.user_data.get('title')}\n\n💬 <b>توضیحات تکمیلی</b> را وارد کنید:\n<i>(یا دستور /skip را ارسال کنید)</i>"
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode="HTML", reply_markup=step_kb("back_to_title"))
    else:
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=step_kb("back_to_title"))
    return ADD_DESC

async def add_got_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message:
        ctx.user_data["description"] = "" if update.message.text.startswith("/skip") else update.message.text.strip()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 شخصی", callback_data="cat:Personal"), InlineKeyboardButton("💼 کاری", callback_data="cat:Work")],
        [InlineKeyboardButton("📚 تحصیلی", callback_data="cat:Study")],
        [InlineKeyboardButton("🔙 مرحله قبل", callback_data="back_to_desc"), InlineKeyboardButton("❌ انصراف", callback_data="cancel_flow")]
    ])
    msg = "🏷 <b>دسته‌بندی کار</b> را انتخاب کنید:"
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode="HTML", reply_markup=kb)
    else:
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
    return ADD_CAT

async def add_got_cat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not q.data.startswith("back"): ctx.user_data["category"] = q.data.split(":")[1]
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚨 ضروری", callback_data="pri:High"), InlineKeyboardButton("🟡 معمولی", callback_data="pri:Medium")],
        [InlineKeyboardButton("🟢 کم اهمیت", callback_data="pri:Low")],
        [InlineKeyboardButton("🔙 مرحله قبل", callback_data="back_to_cat"), InlineKeyboardButton("❌ انصراف", callback_data="cancel_flow")]
    ])
    await q.edit_message_text("🎯 <b>اولویت کار</b> را مشخص کنید:", parse_mode="HTML", reply_markup=kb)
    return ADD_PRI

async def add_got_pri(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not q.data.startswith("back"): ctx.user_data["priority"] = q.data.split(":")[1]
    
    msg = "⏰ <b>ساعت یادآوری</b> (مثال 18:30) را وارد کنید:\n<i>(یا دستور /skip را ارسال کنید)</i>"
    await q.edit_message_text(msg, parse_mode="HTML", reply_markup=step_kb("back_to_pri"))
    return ADD_DUE

async def add_finish(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message and not update.message.text.startswith("/skip"):
        ctx.user_data["due_date"] = update.message.text.strip() # Simplified for length
    else:
        ctx.user_data["due_date"] = None

    uid = update.effective_user.id
    d = ctx.user_data
    tid = await db_add_task(uid, d["title"], d.get("description", ""), d.get("category", "Personal"), d.get("priority", "Medium"), d.get("due_date"))
    task = await db_get_task(tid)
    ctx.user_data.clear()

    # پیام موفقیت ثبت تسک
    await update.message.reply_text(
        "🎉 <b>کار جدید با موفقیت ثبت شد!</b>\n\n" + fmt_task_advanced(task),
        parse_mode="HTML", reply_markup=main_reply_keyboard()
    )
    
    # نمایش خودکار لیست کارهای فعال بعد از افزودن
    await cmd_list(update, ctx)
    return ConversationHandler.END

async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    msg = "❌ عملیات لغو شد."
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg, reply_markup=main_reply_keyboard())
    return ConversationHandler.END

# ═══════════════════════════════════════════════════════════════════════════════
# HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════
async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 <b>به سیستم مدیریت کارهای پیشرفته خوش آمدید!</b>", parse_mode="HTML", reply_markup=main_reply_keyboard())

async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else update.callback_query.from_user.id
    tasks = await db_get_tasks(uid)
    msg_target = update.message if update.message else update.callback_query.message

    if not tasks:
        await msg_target.reply_text("🎉 <b>هیچ کار فعالی ندارید!</b>", parse_mode="HTML", reply_markup=main_reply_keyboard())
        return

    await msg_target.reply_text("📋 <b>لیست کارهای فعال شما:</b>\nبرای ویرایش پیشرفته، از وب‌اپ استفاده کنید.", parse_mode="HTML")
    for t in tasks:
        await msg_target.reply_text(fmt_task_advanced(t), parse_mode="HTML", reply_markup=task_action_kb(t["id"]))

async def cb_done_task(update: Update, _: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    tid = int(q.data.split(":")[1])
    await db_mark_done(tid)
    await q.answer("✅ انجام شد!")
    await q.edit_message_text(f"<s>{q.message.text}</s>\n\n✅ <b>به اتمام رسید!</b>", parse_mode="HTML")

async def cb_del_task(update: Update, _: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    tid = int(q.data.split(":")[1])
    await db_delete_task(tid)
    await q.answer("🗑 حذف شد.")
    await q.delete_message()

# ═══════════════════════════════════════════════════════════════════════════════
# WEB API (CORS & CRUD ENABLED)
# ═══════════════════════════════════════════════════════════════════════════════

async def api_get_tasks(request):
    user_id = request.query.get("user_id")
    if not user_id: return web.json_response({"error": "user_id required"}, status=400)
    tasks = await db_get_tasks(int(user_id))
    return web.json_response({"status": "success", "tasks": tasks})

async def api_add_task(request):
    data = await request.json()
    tid = await db_add_task(int(data['user_id']), data['title'], data.get('description',''), data.get('category','Personal'), data.get('priority','Medium'), data.get('due_date'))
    return web.json_response({"status": "success", "id": tid})

async def api_update_task(request):
    task_id = request.match_info.get('id')
    data = await request.json()
    await db_update_task(int(task_id), data['title'], data.get('description',''), data.get('category','Personal'), data.get('priority','Medium'), data.get('due_date'))
    return web.json_response({"status": "success"})

async def api_mark_done(request):
    task_id = request.match_info.get('id')
    await db_mark_done(int(task_id))
    return web.json_response({"status": "success"})

async def api_delete_task(request):
    task_id = request.match_info.get('id')
    await db_delete_task(int(task_id))
    return web.json_response({"status": "success"})

async def start_web_server():
    app = web.Application()
    cors = aiohttp_cors.setup(app, defaults={"*": aiohttp_cors.ResourceOptions(allow_credentials=True, expose_headers="*", allow_headers="*")})
    
    cors.add(app.router.add_get("/api/tasks", api_get_tasks))
    cors.add(app.router.add_post("/api/tasks", api_add_task))
    cors.add(app.router.add_put("/api/tasks/{id}", api_update_task))
    cors.add(app.router.add_post("/api/tasks/{id}/done", api_mark_done))
    cors.add(app.router.add_delete("/api/tasks/{id}", api_delete_task))

    port = int(os.environ.get("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info(f"Enterprise Web API Server on port {port} 🌐")

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN SETUP
# ═══════════════════════════════════════════════════════════════════════════════
async def main_async():
    await init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    add_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ افزودن کار جدید$"), add_start)],
        states={
            ADD_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_title), CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")],
            ADD_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_desc), CallbackQueryHandler(add_start, pattern="^back_to_title$"), CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")],
            ADD_CAT: [CallbackQueryHandler(add_got_cat, pattern=r"^cat:"), CallbackQueryHandler(add_got_title, pattern="^back_to_desc$"), CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")],
            ADD_PRI: [CallbackQueryHandler(add_got_pri, pattern=r"^pri:"), CallbackQueryHandler(add_got_desc, pattern="^back_to_cat$"), CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")],
            ADD_DUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_finish), CallbackQueryHandler(add_got_cat, pattern="^back_to_pri$"), CallbackQueryHandler(cmd_cancel, pattern="^cancel_flow$")],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
    )

    app.add_handler(add_conv)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.Regex("^📋 کارهای فعال من$"), cmd_list))
    app.add_handler(CallbackQueryHandler(cb_done_task, pattern=r"^done:"))
    app.add_handler(CallbackQueryHandler(cb_del_task, pattern=r"^del_task:"))

    await start_web_server()
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main_async())
