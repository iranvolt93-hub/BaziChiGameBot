import os
import sqlite3
import logging
import asyncio
from contextlib import closing
from datetime import datetime, timezone

from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove,
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters,
)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
DB_PATH = os.getenv("DB_PATH", "chat2chat.db")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("chat2chat")


def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with closing(db()) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT NOT NULL,
            gender TEXT,
            preference TEXT,
            age INTEGER,
            city TEXT,
            about TEXT,
            photo_file_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS sessions (
            user_id INTEGER PRIMARY KEY,
            partner_id INTEGER,
            mode TEXT NOT NULL DEFAULT 'idle'
        );

        CREATE TABLE IF NOT EXISTS likes (
            from_id INTEGER NOT NULL,
            to_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(from_id, to_id)
        );

        CREATE TABLE IF NOT EXISTS blocks (
            blocker_id INTEGER NOT NULL,
            blocked_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(blocker_id, blocked_id)
        );

        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER NOT NULL,
            reported_id INTEGER NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL
        );
        """)
        c.commit()


def now():
    return datetime.now(timezone.utc).isoformat()


def get_user(uid):
    with closing(db()) as c:
        return c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()


def ensure_user(tg_user):
    u = get_user(tg_user.id)
    if not u:
        with closing(db()) as c:
            c.execute(
                """INSERT INTO users
                (user_id,username,first_name,created_at,updated_at)
                VALUES (?,?,?,?,?)""",
                (tg_user.id, tg_user.username or "", tg_user.first_name or "کاربر", now(), now()),
            )
            c.commit()
    else:
        with closing(db()) as c:
            c.execute(
                "UPDATE users SET username=?, first_name=?, updated_at=? WHERE user_id=?",
                (tg_user.username or "", tg_user.first_name or "کاربر", now(), tg_user.id),
            )
            c.commit()


def menu():
    return ReplyKeyboardMarkup(
        [
            ["🔎 پیدا کردن نفر", "💬 چت تصادفی"],
            ["❤️ علاقه‌مندی‌ها", "👤 پروفایل من"],
            ["✏️ ویرایش پروفایل", "🚫 قطع چت"],
            ["⚠️ گزارش / بلاک", "ℹ️ راهنما"],
        ],
        resize_keyboard=True,
    )


def profile_text(u):
    gender = {"male":"مرد", "female":"زن"}.get(u["gender"], "ثبت نشده")
    pref = {"male":"مرد", "female":"زن", "both":"هر دو"}.get(u["preference"], "ثبت نشده")
    return (
        f"👤 پروفایل\n\n"
        f"نام: {u['first_name']}\n"
        f"جنسیت: {gender}\n"
        f"ترجیح: {pref}\n"
        f"سن: {u['age'] or 'ثبت نشده'}\n"
        f"شهر: {u['city'] or 'ثبت نشده'}\n"
        f"درباره من: {u['about'] or 'ثبت نشده'}"
    )


def set_session(uid, partner, mode):
    with closing(db()) as c:
        c.execute(
            "INSERT INTO sessions(user_id,partner_id,mode) VALUES(?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET partner_id=excluded.partner_id,mode=excluded.mode",
            (uid, partner, mode),
        )
        c.commit()


def get_session(uid):
    with closing(db()) as c:
        return c.execute("SELECT * FROM sessions WHERE user_id=?", (uid,)).fetchone()


def clear_session(uid):
    s = get_session(uid)
    with closing(db()) as c:
        c.execute("UPDATE sessions SET partner_id=NULL, mode='idle' WHERE user_id=?", (uid,))
        if s and s["partner_id"]:
            c.execute("UPDATE sessions SET partner_id=NULL, mode='idle' WHERE user_id=?", (s["partner_id"],))
        c.commit()


def blocked(a, b):
    with closing(db()) as c:
        x = c.execute(
            "SELECT 1 FROM blocks WHERE (blocker_id=? AND blocked_id=?) OR (blocker_id=? AND blocked_id=?)",
            (a,b,b,a)
        ).fetchone()
        return bool(x)


def find_candidate(uid):
    u = get_user(uid)
    if not u or not u["gender"] or not u["preference"]:
        return None

    with closing(db()) as c:
        rows = c.execute("""
            SELECT * FROM users
            WHERE user_id != ?
              AND is_active=1
              AND gender IS NOT NULL
              AND age IS NOT NULL
              AND (
                preference = 'both' OR preference = ?
              )
              AND (
                ? = 'both' OR gender = ?
              )
              AND user_id NOT IN (
                  SELECT blocked_id FROM blocks WHERE blocker_id=?
              )
              AND user_id NOT IN (
                  SELECT blocker_id FROM blocks WHERE blocked_id=?
              )
              AND user_id NOT IN (
                  SELECT partner_id FROM sessions WHERE partner_id IS NOT NULL
              )
            ORDER BY RANDOM()
            LIMIT 1
        """, (uid, u["gender"], u["preference"], u["gender"], uid, uid)).fetchone()
        return rows


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)
    context.user_data.clear()
    u = get_user(update.effective_user.id)
    if not u["gender"] or not u["age"] or not u["preference"]:
        context.user_data["setup"] = "gender"
        await update.message.reply_text(
            "👋 به ربات آشنایی و چت دونفره خوش آمدی.\n\n"
            "برای شروع، جنسیتت را انتخاب کن:",
            reply_markup=ReplyKeyboardMarkup([["👨 مرد", "👩 زن"]], resize_keyboard=True),
        )
    else:
        await update.message.reply_text("خوش آمدی 🌹\nاز منوی زیر استفاده کن.", reply_markup=menu())


async def setup_flow(update, context):
    uid = update.effective_user.id
    text = update.message.text.strip()
    step = context.user_data.get("setup")
    if not step:
        return False

    if step == "gender":
        if text not in ("👨 مرد", "👩 زن"):
            await update.message.reply_text("یکی از دو گزینه را انتخاب کن.")
            return True
        gender = "male" if "مرد" in text else "female"
        with closing(db()) as c:
            c.execute("UPDATE users SET gender=?, updated_at=? WHERE user_id=?", (gender,now(),uid)); c.commit()
        context.user_data["setup"] = "preference"
        await update.message.reply_text(
            "دنبال چه کسی هستی؟",
            reply_markup=ReplyKeyboardMarkup([["👨 مرد", "👩 زن"], ["👨‍👩 هر دو"]], resize_keyboard=True),
        )
        return True

    if step == "preference":
        if text not in ("👨 مرد", "👩 زن", "👨‍👩 هر دو"):
            await update.message.reply_text("یکی از گزینه‌ها را انتخاب کن.")
            return True
        pref = "male" if text == "👨 مرد" else ("female" if text == "👩 زن" else "both")
        with closing(db()) as c:
            c.execute("UPDATE users SET preference=?, updated_at=? WHERE user_id=?", (pref,now(),uid)); c.commit()
        context.user_data["setup"] = "age"
        await update.message.reply_text("سن خودت را فقط به عدد بفرست (مثلاً 41).")
        return True

    if step == "age":
        try:
            age = int(text)
            if age < 18 or age > 100:
                raise ValueError
        except ValueError:
            await update.message.reply_text("سن باید عددی بین ۱۸ تا ۱۰۰ باشد.")
            return True
        with closing(db()) as c:
            c.execute("UPDATE users SET age=?, updated_at=? WHERE user_id=?", (age,now(),uid)); c.commit()
        context.user_data["setup"] = "city"
        await update.message.reply_text("شهرت را بنویس.")
        return True

    if step == "city":
        with closing(db()) as c:
            c.execute("UPDATE users SET city=?, updated_at=? WHERE user_id=?", (text[:80],now(),uid)); c.commit()
        context.user_data["setup"] = "about"
        await update.message.reply_text("یک معرفی کوتاه از خودت بنویس (اختیاری؛ می‌توانی «رد» بفرستی).")
        return True

    if step == "about":
        about = "" if text == "رد" else text[:500]
        with closing(db()) as c:
            c.execute("UPDATE users SET about=?, updated_at=? WHERE user_id=?", (about,now(),uid)); c.commit()
        context.user_data.clear()
        await update.message.reply_text("✅ پروفایلت آماده شد.", reply_markup=menu())
        return True

    return False


async def send_candidate(update, candidate):
    if not candidate:
        await update.message.reply_text(
            "فعلاً فرد مناسبی برایت پیدا نشد.\nبعداً دوباره امتحان کن.",
            reply_markup=menu(),
        )
        return
    u = candidate
    gender = "👨" if u["gender"] == "male" else "👩"
    text = f"{gender} {u['first_name']} | {u['age']} ساله\n📍 {u['city'] or 'نامشخص'}\n\n{u['about'] or 'توضیحی ثبت نشده.'}"
    kb = ReplyKeyboardMarkup(
        [["❤️ پسندیدم", "➡️ نفر بعد"], ["🚫 بلاک", "🔙 منوی اصلی"]],
        resize_keyboard=True,
    )
    if u["photo_file_id"]:
        try:
            await update.message.reply_photo(u["photo_file_id"], caption=text, reply_markup=kb)
            return
        except Exception:
            pass
    await update.message.reply_text(text, reply_markup=kb)


async def handle_find(update, context):
    uid = update.effective_user.id
    s = get_session(uid)
    if s and s["partner_id"]:
        await update.message.reply_text("ابتدا چت فعلی را با «🚫 قطع چت» تمام کن.")
        return
    candidate = find_candidate(uid)
    if candidate:
        context.user_data["candidate"] = candidate["user_id"]
    await send_candidate(update, candidate)


async def start_random_chat(update, context):
    uid = update.effective_user.id
    s = get_session(uid)
    if s and s["partner_id"]:
        await update.message.reply_text("در حال حاضر با یک نفر در چت هستی.")
        return
    candidate = find_candidate(uid)
    if not candidate:
        await update.message.reply_text("فعلاً کسی مطابق ترجیحت آنلاین نیست.")
        return
    set_session(uid, candidate["user_id"], "chat")
    set_session(candidate["user_id"], uid, "chat")
    await update.message.reply_text("💬 وصل شدی! هر پیامی بفرستی برای طرف مقابل ارسال می‌شود.", reply_markup=ReplyKeyboardMarkup([["🚫 قطع چت", "⚠️ گزارش / بلاک"]], resize_keyboard=True))
    await context.bot.send_message(candidate["user_id"], "💬 یک نفر برای چت به تو وصل شد! می‌توانید گفتگو را شروع کنید.", reply_markup=ReplyKeyboardMarkup([["🚫 قطع چت", "⚠️ گزارش / بلاک"]], resize_keyboard=True))


async def action(update, context):
    text = update.message.text.strip()
    uid = update.effective_user.id

    if await setup_flow(update, context):
        return

    if text == "👤 پروفایل من":
        await update.message.reply_text(profile_text(get_user(uid)), reply_markup=menu())
        return

    if text in ("🔎 پیدا کردن نفر", "➡️ نفر بعد"):
        await handle_find(update, context)
        return

    if text == "💬 چت تصادفی":
        await start_random_chat(update, context)
        return

    if text == "🚫 قطع چت":
        s = get_session(uid)
        if not s or not s["partner_id"]:
            await update.message.reply_text("چت فعالی نداری.", reply_markup=menu())
        else:
            partner = s["partner_id"]
            clear_session(uid)
            await update.message.reply_text("چت پایان یافت.", reply_markup=menu())
            try:
                await context.bot.send_message(partner, "طرف مقابل چت را پایان داد.", reply_markup=menu())
            except Exception:
                pass
        return

    if text == "❤️ پسندیدم":
        target = context.user_data.get("candidate")
        if not target:
            await update.message.reply_text("ابتدا یک نفر پیدا کن.")
            return
        with closing(db()) as c:
            c.execute("INSERT OR IGNORE INTO likes VALUES(?,?,?)", (uid,target,now()))
            mutual = c.execute("SELECT 1 FROM likes WHERE from_id=? AND to_id=?", (target,uid)).fetchone()
            c.commit()
        if mutual:
            set_session(uid,target,"chat"); set_session(target,uid,"chat")
            await update.message.reply_text("❤️ علاقه دوطرفه شد! چت شروع شد.", reply_markup=ReplyKeyboardMarkup([["🚫 قطع چت","⚠️ گزارش / بلاک"]], resize_keyboard=True))
            await context.bot.send_message(target, "❤️ علاقه دوطرفه شد! چت شروع شد.", reply_markup=ReplyKeyboardMarkup([["🚫 قطع چت","⚠️ گزارش / بلاک"]], resize_keyboard=True))
        else:
            await update.message.reply_text("❤️ ثبت شد. اگر او هم تو را پسندیده باشد، Match می‌شوید.")
        return

    if text == "🚫 بلاک":
        target = context.user_data.get("candidate")
        if target:
            with closing(db()) as c:
                c.execute("INSERT OR IGNORE INTO blocks VALUES(?,?,?)", (uid,target,now())); c.commit()
            await update.message.reply_text("کاربر بلاک شد.", reply_markup=menu())
        return

    if text == "⚠️ گزارش / بلاک":
        context.user_data["report_mode"] = True
        await update.message.reply_text("شناسه/نام طرف مقابل را برای گزارش بفرست یا «لغو» بنویس.")
        return

    if context.user_data.get("report_mode"):
        if text == "لغو":
            context.user_data.pop("report_mode", None)
            await update.message.reply_text("لغو شد.", reply_markup=menu())
            return
        s = get_session(uid)
        target = s["partner_id"] if s and s["partner_id"] else context.user_data.get("candidate")
        if target:
            with closing(db()) as c:
                c.execute("INSERT INTO reports(reporter_id,reported_id,reason,created_at) VALUES(?,?,?,?)", (uid,target,text[:500],now()))
                c.execute("INSERT OR IGNORE INTO blocks VALUES(?,?,?)", (uid,target,now()))
                c.commit()
            context.user_data.pop("report_mode", None)
            await update.message.reply_text("گزارش ثبت و کاربر بلاک شد.", reply_markup=menu())
        return

    if text == "✏️ ویرایش پروفایل":
        context.user_data["setup"] = "gender"
        await update.message.reply_text("از ابتدا اطلاعات پروفایل را وارد کن.")
        return

    if text == "ℹ️ راهنما":
        await update.message.reply_text(
            "ℹ️ راهنما\n\n"
            "🔎 پیدا کردن نفر: نمایش یک پروفایل مناسب\n"
            "💬 چت تصادفی: اتصال مستقیم به یک نفر\n"
            "❤️ پسندیدم: ثبت علاقه؛ در صورت علاقه دوطرفه Match می‌شوید\n"
            "🚫 قطع چت: پایان گفتگو\n"
            "⚠️ گزارش / بلاک: گزارش و جلوگیری از تماس مجدد\n\n"
            "این نسخه برای افراد ۱۸ سال به بالا طراحی شده است.",
            reply_markup=menu(),
        )
        return

    # Forward ordinary chat messages to active partner.
    s = get_session(uid)
    if s and s["partner_id"] and s["mode"] == "chat":
        partner = s["partner_id"]
        try:
            await context.bot.send_chat_action(partner, ChatAction.TYPING)
            await context.bot.send_message(partner, f"💬 {update.effective_user.first_name}: {update.message.text}")
        except Exception:
            await update.message.reply_text("ارسال پیام ناموفق بود.")
        return

    await update.message.reply_text("از منوی ربات استفاده کن.", reply_markup=menu())


async def photo(update, context):
    uid = update.effective_user.id
    if context.user_data.get("setup") and context.user_data["setup"] == "about":
        await update.message.reply_text("فعلاً متن معرفی را بفرست. در نسخه بعدی عکس پروفایل را هم از همین بخش فعال می‌کنیم.")
        return
    s = get_session(uid)
    if s and s["partner_id"]:
        try:
            await update.message.forward(s["partner_id"])
        except Exception:
            await update.message.reply_text("ارسال عکس ناموفق بود.")


async def error_handler(update, context):
    log.exception("Unhandled exception", exc_info=context.error)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, action))
    app.add_error_handler(error_handler)
    log.info("Chat2Chat bot starting")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
