# -*- coding: utf-8 -*-
"""BaziChiGameBot - independent Persian Telegram game bot.
Python 3.11+, python-telegram-bot 21.x/22.x, SQLite.
"""
import os
import json
import time
import random
import asyncio
import logging
import sqlite3
from contextlib import contextmanager
from typing import Optional

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
)
from telegram.constants import ChatType
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
except ValueError:
    ADMIN_ID = 0
DB_PATH = os.getenv("DB_PATH", "/data/bazichi.db").strip() or "/data/bazichi.db"
ROUND_SECONDS = 25
TOTAL_ROUNDS = 5
MAX_GROUP_SIZE = 10
TASKS: dict[int, asyncio.Task] = {}

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("bazichi")

GAMES = {
    "quiz": "🧠 اطلاعات عمومی",
    "word": "🔤 حدس کلمه",
    "riddle": "❓ معما و چیستان",
    "truth": "🎭 جرئت یا حقیقت",
    "number": "🔢 حدس عدد",
    "speed": "⚡ چالش سرعت",
}
GAME_BUTTONS = [
    [InlineKeyboardButton(GAMES[k], callback_data=f"game:{k}")]
    for k in GAMES
]
MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("👤 بازی انفرادی"), KeyboardButton("👥 بازی دونفره")],
        [KeyboardButton("👨‍👩‍👧 بازی چندنفره")],
        [KeyboardButton("👤 پروفایل من"), KeyboardButton("🏆 جدول رتبه‌بندی")],
        [KeyboardButton("📜 تاریخچه بازی‌ها"), KeyboardButton("📖 راهنما")],
    ], resize_keyboard=True,
)

SEED_QUESTIONS = [
    ("quiz", "عمومی", "آسان", "پایتخت ایران کدام شهر است؟", ["تهران", "اصفهان", "شیراز", "تبریز"], 0),
    ("quiz", "علوم", "آسان", "کدام سیاره به سیاره سرخ معروف است؟", ["زهره", "مریخ", "مشتری", "عطارد"], 1),
    ("quiz", "علوم", "متوسط", "نماد شیمیایی طلا چیست؟", ["Ag", "Fe", "Au", "O"], 2),
    ("quiz", "جغرافیا", "آسان", "بزرگ‌ترین اقیانوس جهان کدام است؟", ["اطلس", "هند", "منجمد شمالی", "آرام"], 3),
    ("quiz", "دانش", "متوسط", "یک ساعت چند دقیقه است؟", ["۳۰", "۴۵", "۶۰", "۹۰"], 2),
    ("word", "واژگان", "آسان", "کدام گزینه واژه درستِ حروف «ب، ا، ت، ک» است؟", ["کتاب", "باتک", "کباب", "تابک"], 0),
    ("word", "واژگان", "آسان", "کدام واژه با «آ» شروع می‌شود؟", ["آسمان", "باران", "دریا", "زمین"], 0),
    ("word", "واژگان", "متوسط", "مخالف واژه «روشن» کدام است؟", ["شفاف", "تاریک", "درخشان", "نورانی"], 1),
    ("riddle", "چیستان", "آسان", "آن چیست که هرچه از آن برداری بزرگ‌تر می‌شود؟", ["گودال", "آب", "آتش", "سایه"], 0),
    ("riddle", "چیستان", "آسان", "چه چیزی دندان دارد اما غذا نمی‌خورد؟", ["شانه", "چنگال", "اره", "زیپ"], 0),
    ("riddle", "چیستان", "متوسط", "چه چیزی همیشه بالا می‌رود اما پایین نمی‌آید؟", ["سن", "بادکنک", "دود", "پرنده"], 0),
    ("speed", "محاسبات", "آسان", "حاصل ۷ × ۸ چند است؟", ["۵۴", "۵۶", "۶۴", "۴۸"], 1),
    ("speed", "محاسبات", "آسان", "حاصل ۹ + ۶ چند است؟", ["۱۴", "۱۵", "۱۶", "۱۳"], 1),
    ("speed", "عمومی", "آسان", "کدام عدد زوج است؟", ["۱۳", "۱۷", "۲۲", "۳۱"], 2),
]
TRUTHS = [
    "یک خاطره خنده‌دار از مدرسه تعریف کن.",
    "اگر می‌توانستی یک مهارت را فوری یاد بگیری، چه مهارتی بود؟",
    "سه ویژگی خوب خودت را بگو.",
    "آخرین چیزی که باعث خنده‌ات شد چه بود؟",
    "بهترین سفری که رفته‌ای کجا بوده است؟",
]
DARES = [
    "یک جمله انگیزشی بنویس.",
    "اسم پنج میوه را در یک پیام بنویس.",
    "با سه ایموجی حال امروزت را توصیف کن.",
    "یک تعریف محترمانه از بازیکن دیگر بنویس.",
    "یک جمله بامزه بساز که کلمه بازی‌چی در آن باشد.",
]


@contextmanager
def db():
    folder = os.path.dirname(DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def add_column(conn, table: str, name: str, declaration: str):
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if name not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT NOT NULL,
            total_points INTEGER NOT NULL DEFAULT 0, games INTEGER NOT NULL DEFAULT 0,
            wins INTEGER NOT NULL DEFAULT 0, losses INTEGER NOT NULL DEFAULT 0,
            level INTEGER NOT NULL DEFAULT 1, blocked INTEGER NOT NULL DEFAULT 0,
            joined_at TEXT DEFAULT CURRENT_TIMESTAMP, last_seen TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS matches(
            id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT DEFAULT 'game',
            host_id INTEGER, status TEXT NOT NULL DEFAULT 'running', game_type TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, started_at TEXT, ended_at TEXT
        );
        CREATE TABLE IF NOT EXISTS players(
            match_id INTEGER NOT NULL, user_id INTEGER NOT NULL, score INTEGER NOT NULL DEFAULT 0,
            joined_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(match_id,user_id),
            FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS questions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, game_type TEXT NOT NULL,
            category TEXT DEFAULT 'عمومی', difficulty TEXT DEFAULT 'آسان', prompt TEXT NOT NULL,
            options TEXT NOT NULL, answer INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS rounds(
            id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER NOT NULL, round_no INTEGER NOT NULL,
            game_type TEXT NOT NULL, prompt TEXT NOT NULL, options TEXT, answer INTEGER,
            extra TEXT, deadline REAL NOT NULL, status TEXT NOT NULL DEFAULT 'open',
            UNIQUE(match_id,round_no), FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS answers(
            round_id INTEGER NOT NULL, user_id INTEGER NOT NULL, answer TEXT NOT NULL,
            correct INTEGER NOT NULL DEFAULT 0, points INTEGER NOT NULL DEFAULT 0,
            answered_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(round_id,user_id),
            FOREIGN KEY(round_id) REFERENCES rounds(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS queue_entries(
            user_id INTEGER PRIMARY KEY, game_type TEXT NOT NULL, group_size INTEGER NOT NULL,
            joined_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS truth_choices(
            round_id INTEGER NOT NULL, user_id INTEGER NOT NULL, choice TEXT NOT NULL,
            prompt TEXT NOT NULL, PRIMARY KEY(round_id,user_id)
        );
        CREATE TABLE IF NOT EXISTS reports(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            match_id INTEGER, reason TEXT NOT NULL, status TEXT DEFAULT 'new',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY AUTOINCREMENT, level TEXT, message TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);
        CREATE INDEX IF NOT EXISTS idx_players_user ON players(user_id);
        CREATE INDEX IF NOT EXISTS idx_queue_game ON queue_entries(game_type,group_size,joined_at);
        CREATE INDEX IF NOT EXISTS idx_rounds_match_status ON rounds(match_id,status);
        """)
        # Safe migrations for databases created by earlier BaziChi builds.
        add_column(c, "matches", "mode", "TEXT DEFAULT 'multi'")
        add_column(c, "matches", "target_size", "INTEGER DEFAULT 2")
        add_column(c, "matches", "round_no", "INTEGER DEFAULT 0")
        # Seed each supported question-based game independently. This also repairs
        # databases where an older release populated only some game categories.
        for game_key in ("quiz", "word", "riddle", "speed"):
            count = c.execute("SELECT COUNT(*) n FROM questions WHERE game_type=?", (game_key,)).fetchone()["n"]
            if count == 0:
                rows = [item for item in SEED_QUESTIONS if item[0] == game_key]
                c.executemany(
                    "INSERT INTO questions(game_type,category,difficulty,prompt,options,answer) VALUES(?,?,?,?,?,?)",
                    [(g, cat, diff, prompt, json.dumps(opts, ensure_ascii=False), ans)
                     for g, cat, diff, prompt, opts, ans in rows],
                )


def log_event(level: str, message: str):
    getattr(log, level.lower(), log.info)(message)
    try:
        with db() as c:
            c.execute("INSERT INTO events(level,message) VALUES(?,?)", (level, message[:1000]))
    except Exception:
        log.exception("Could not persist event")


def register_user(user) -> bool:
    full_name = " ".join(x for x in [user.first_name, user.last_name] if x) or "بازیکن"
    with db() as c:
        c.execute("""INSERT INTO users(user_id,username,full_name) VALUES(?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,
            full_name=excluded.full_name,last_seen=CURRENT_TIMESTAMP""",
            (user.id, user.username, full_name))
        row = c.execute("SELECT blocked FROM users WHERE user_id=?", (user.id,)).fetchone()
        return bool(row["blocked"])


def is_registered(uid: int) -> bool:
    with db() as c:
        row = c.execute("SELECT blocked FROM users WHERE user_id=?", (uid,)).fetchone()
        return bool(row and not row["blocked"])


def active_match(uid: int):
    with db() as c:
        row = c.execute("""SELECT m.* FROM matches m JOIN players p ON p.match_id=m.id
            WHERE p.user_id=? AND m.status IN ('running','waiting') ORDER BY m.id DESC LIMIT 1""", (uid,)).fetchone()
        return dict(row) if row else None


def active_match_in_connection(conn, uid: int):
    """Same check inside an existing transaction (prevents queue/match races)."""
    return conn.execute("""SELECT m.id FROM matches m JOIN players p ON p.match_id=m.id
        WHERE p.user_id=? AND m.status IN ('running','waiting') LIMIT 1""", (uid,)).fetchone()


def get_players(mid: int):
    with db() as c:
        return [dict(r) for r in c.execute("""SELECT u.user_id,u.full_name,u.username,p.score
            FROM players p JOIN users u ON u.user_id=p.user_id
            WHERE p.match_id=? ORDER BY p.joined_at,p.user_id""", (mid,))]


async def safe_send(ctx, uid: int, text: str, **kwargs):
    try:
        return await ctx.bot.send_message(chat_id=uid, text=text, **kwargs)
    except Exception as exc:
        log_event("warning", f"ارسال پیام به {uid} ناموفق بود: {exc}")
        return None


async def announce(ctx, mid: int, text: str, **kwargs):
    for player in get_players(mid):
        await safe_send(ctx, player["user_id"], text, **kwargs)


def main_menu_text(text: str) -> bool:
    return text in {
        "👤 بازی انفرادی", "👥 بازی دونفره", "👨‍👩‍👧 بازی چندنفره",
        "👤 پروفایل من", "🏆 جدول رتبه‌بندی", "📜 تاریخچه بازی‌ها", "📖 راهنما",
    }


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        await update.message.reply_text("برای بازی، ابتدا در گفت‌وگوی خصوصی ربات دستور /start را اجرا کنید.")
        return
    if register_user(update.effective_user):
        await update.message.reply_text("⛔ دسترسی شما به ربات مسدود شده است.")
        return
    await update.message.reply_text(
        f"سلام {update.effective_user.first_name or 'دوست من'}! 🎉\n"
        "به بازی‌چی خوش آمدی! بازی‌ها کاملاً رایگان هستند.\n\n"
        "👤 انفرادی: خودت بازی کن و امتیاز بگیر.\n"
        "👥 دونفره: ربات یک بازیکن دیگر را برایت پیدا می‌کند.\n"
        "👨‍👩‍👧 چندنفره: ظرفیت ۳ تا ۱۰ نفر را انتخاب کن تا ربات بازیکنان را خودکار جمع کند.",
        reply_markup=MENU,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 راهنمای بازی‌چی\n\n"
        "👤 بازی انفرادی: یکی از شش بازی را انتخاب کن و به‌تنهایی امتیاز بگیر.\n"
        "👥 بازی دونفره: حالت پیش‌فرض رقابتی؛ ربات یک عضو دیگر را که همان بازی را انتخاب کرده پیدا می‌کند.\n"
        "👨‍👩‍👧 بازی چندنفره: در صورت تمایل ظرفیت ۳ تا ۱۰ نفر را انتخاب کن؛ تشکیل مسابقه خودکار است.\n\n"
        "همه بازیکنان باید یک‌بار /start را در ربات اجرا کرده باشند. برای دونفره، دو نفر باید همان بازی را انتخاب کنند؛ "
        "برای چندنفره، همه باید همان بازی و همان ظرفیت را انتخاب کنند. پاسخ هر دور فقط یک‌بار ثبت می‌شود.\n\n"
        "امتیازها برای پروفایل و رتبه‌بندی هستند؛ هیچ پرداخت یا جایزه نقدی وجود ندارد. "
        "برای دیدن وضعیت بازی یا صف از /status و برای خروج از /leave استفاده کن.",
        reply_markup=MENU,
    )


async def choose_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str):
    context.user_data.pop("admin_action", None)
    context.user_data.pop("truth_wait", None)
    context.user_data["pending_mode"] = mode
    title = {"solo": "انفرادی", "duo": "دونفره", "group": "چندنفره"}[mode]
    await update.message.reply_text(
        f"{title} انتخاب شد. حالا بازی موردنظرت را انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(GAME_BUTTONS),
    )


async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    # A fresh main-menu action invalidates any old inline selection or admin prompt.
    context.user_data.pop("pending_mode", None)
    context.user_data.pop("pending_group_game", None)
    context.user_data.pop("admin_action", None)
    if text == "👤 بازی انفرادی":
        await choose_mode(update, context, "solo")
    elif text == "👥 بازی دونفره":
        await choose_mode(update, context, "duo")
    elif text == "👨‍👩‍👧 بازی چندنفره":
        await choose_mode(update, context, "group")
    elif text == "👤 پروفایل من":
        await show_profile(update, context)
    elif text == "🏆 جدول رتبه‌بندی":
        await show_leaderboard(update, context)
    elif text == "📜 تاریخچه بازی‌ها":
        await show_history(update, context)
    elif text == "📖 راهنما":
        await help_command(update, context)


async def start_solo(ctx, uid: int, game: str):
    if game not in GAMES:
        await safe_send(ctx, uid, "این بازی در دسترس نیست.")
        return
    already_playing = False
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        if active_match_in_connection(c, uid):
            already_playing = True
        else:
            # Choosing solo explicitly cancels an earlier matchmaking request.
            c.execute("DELETE FROM queue_entries WHERE user_id=?", (uid,))
            mid = c.execute(
                "INSERT INTO matches(kind,host_id,status,game_type,mode,target_size,started_at) "
                "VALUES('game',?,'running',?,'solo',1,CURRENT_TIMESTAMP)",
                (uid, game),
            ).lastrowid
            c.execute("INSERT INTO players(match_id,user_id) VALUES(?,?)", (mid, uid))
    if already_playing:
        await safe_send(ctx, uid, "ابتدا بازی فعال فعلی را تمام کن یا با /leave از آن خارج شو.")
        return
    await safe_send(ctx, uid, f"🎮 بازی انفرادی شروع شد: {GAMES[game]}\n۵ دور برای کسب امتیاز در پیش داری.")
    await new_round(ctx, mid, 1)


async def join_queue(ctx, uid: int, game: str, group_size: int):
    if game not in GAMES or group_size not in range(2, MAX_GROUP_SIZE + 1):
        await safe_send(ctx, uid, "انتخاب بازی یا تعداد بازیکنان معتبر نیست.")
        return

    matched_mid: Optional[int] = None
    matched_users: list[int] = []
    waiting = 0
    already_playing = False
    with db() as c:
        # One writer at a time: queue selection and match creation are atomic.
        c.execute("BEGIN IMMEDIATE")
        if active_match_in_connection(c, uid):
            already_playing = True
        else:
            existing = c.execute(
                "SELECT game_type,group_size FROM queue_entries WHERE user_id=?", (uid,)
            ).fetchone()
            if existing and (existing["game_type"] != game or existing["group_size"] != group_size):
                c.execute("DELETE FROM queue_entries WHERE user_id=?", (uid,))
            c.execute(
                "INSERT OR IGNORE INTO queue_entries(user_id,game_type,group_size) VALUES(?,?,?)",
                (uid, game, group_size),
            )
            # Remove stale queue entries whose owners are already in another match.
            c.execute("""DELETE FROM queue_entries
                WHERE EXISTS (
                    SELECT 1 FROM players p JOIN matches m ON m.id=p.match_id
                    WHERE p.user_id=queue_entries.user_id AND m.status IN ('running','waiting')
                )""")
            rows = c.execute("""SELECT q.user_id FROM queue_entries q
                JOIN users u ON u.user_id=q.user_id
                WHERE q.game_type=? AND q.group_size=? AND u.blocked=0
                AND NOT EXISTS (
                    SELECT 1 FROM players p JOIN matches m ON m.id=p.match_id
                    WHERE p.user_id=q.user_id AND m.status IN ('running','waiting')
                )
                ORDER BY q.joined_at,q.user_id LIMIT ?""", (game, group_size, group_size)).fetchall()
            if len(rows) >= group_size:
                matched_users = [r["user_id"] for r in rows]
                host_id = matched_users[0]
                mode = "duo" if group_size == 2 else "group"
                matched_mid = c.execute(
                    "INSERT INTO matches(kind,host_id,status,game_type,mode,target_size,started_at) "
                    "VALUES('game',?,'running',?,?,?,CURRENT_TIMESTAMP)",
                    (host_id, game, mode, group_size),
                ).lastrowid
                c.executemany(
                    "INSERT INTO players(match_id,user_id) VALUES(?,?)",
                    [(matched_mid, x) for x in matched_users],
                )
                c.executemany("DELETE FROM queue_entries WHERE user_id=?", [(x,) for x in matched_users])
            else:
                waiting = len(rows)

    if already_playing:
        await safe_send(ctx, uid, "ابتدا بازی فعال فعلی را تمام کن یا با /leave از آن خارج شو.")
        return
    if matched_mid:
        label = "دونفره" if group_size == 2 else f"چندنفره ({group_size} نفر)"
        for player_id in matched_users:
            await safe_send(
                ctx, player_id,
                f"🎉 بازیکنان کامل شدند!\n{label} — {GAMES[game]}\nمسابقه #{matched_mid} شروع شد.\nبرای پاسخ به سؤال‌ها از دکمه‌ها استفاده کن.",
            )
        await new_round(ctx, matched_mid, 1)
    else:
        await safe_send(
            ctx, uid,
            f"⏳ وارد صف {GAMES[game]} شدی.\nبازیکنان حاضر: {waiting}/{group_size}\n"
            "به محض تکمیل ظرفیت، بازی خودکار شروع می‌شود.\nبرای لغو انتظار دکمه زیر را بزن.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو انتظار", callback_data="queue:cancel")]]),
        )


async def game_selected(q, context, uid: int, game: str):
    mode = context.user_data.get("pending_mode")
    if game not in GAMES or mode not in ("solo", "duo", "group"):
        await q.answer("ابتدا از منوی اصلی نوع بازی را انتخاب کن.", show_alert=True)
        return
    context.user_data.pop("pending_mode", None)
    await q.answer()
    if mode == "solo":
        await start_solo(context, uid, game)
    elif mode == "duo":
        await join_queue(context, uid, game, 2)
    else:
        context.user_data["pending_group_game"] = game
        buttons = [[InlineKeyboardButton(f"{n} نفر", callback_data=f"size:{game}:{n}") for n in (3, 4, 5)]]
        buttons += [[InlineKeyboardButton(f"{n} نفر", callback_data=f"size:{game}:{n}") for n in (6, 7, 8)]]
        buttons += [[InlineKeyboardButton(f"{n} نفر", callback_data=f"size:{game}:{n}") for n in (9, 10)]]
        await q.message.reply_text("ظرفیت مسابقه را انتخاب کن:", reply_markup=InlineKeyboardMarkup(buttons))


async def new_round(ctx, mid: int, round_no: int):
    if round_no > TOTAL_ROUNDS:
        await finish_match(ctx, mid)
        return
    with db() as c:
        match = c.execute("SELECT * FROM matches WHERE id=? AND status='running'", (mid,)).fetchone()
        if not match:
            return
        game = match["game_type"]
        deadline = time.time() + ROUND_SECONDS
        if game == "truth":
            prompt = "برای دریافت چالش خود، حقیقت یا جرئت را انتخاب کن:"
            options = None
            answer = None
            extra = json.dumps({"truth": random.choice(TRUTHS), "dare": random.choice(DARES)}, ensure_ascii=False)
        elif game == "number":
            secret = random.randint(1, 30)
            prompt = "یک عدد بین ۱ تا ۳۰ حدس بزن. هر بازیکن فقط یک فرصت دارد."
            options = None
            answer = None
            extra = json.dumps({"secret": secret}, ensure_ascii=False)
        else:
            row = c.execute("SELECT * FROM questions WHERE game_type=? AND active=1 ORDER BY RANDOM() LIMIT 1", (game,)).fetchone()
            if not row:
                row = c.execute("SELECT * FROM questions WHERE game_type='quiz' AND active=1 ORDER BY RANDOM() LIMIT 1").fetchone()
            if not row:
                log_event("error", f"بانک سؤال برای {game} خالی است")
                await finish_match(ctx, mid)
                return
            prompt, options, answer = row["prompt"], row["options"], row["answer"]
            extra = None
        rid = c.execute("INSERT INTO rounds(match_id,round_no,game_type,prompt,options,answer,extra,deadline,status) VALUES(?,?,?,?,?,?,?,?, 'open')",
                        (mid, round_no, game, prompt, options, answer, extra, deadline)).lastrowid
        c.execute("UPDATE matches SET round_no=? WHERE id=?", (round_no, mid))
    if game == "truth":
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("💬 حقیقت", callback_data=f"truth:{rid}:truth"),
                                        InlineKeyboardButton("🔥 جرئت", callback_data=f"truth:{rid}:dare")]])
        await announce(ctx, mid, f"🎭 دور {round_no}/{TOTAL_ROUNDS}\n{prompt}\n⏱ {ROUND_SECONDS} ثانیه", reply_markup=markup)
    elif game == "number":
        await announce(ctx, mid, f"🔢 دور {round_no}/{TOTAL_ROUNDS}\n{prompt}\n⏱ {ROUND_SECONDS} ثانیه")
    else:
        opts = json.loads(options)
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(f"{i+1}. {v}", callback_data=f"answer:{rid}:{i}")]
                                       for i, v in enumerate(opts)])
        await announce(ctx, mid, f"🎯 دور {round_no}/{TOTAL_ROUNDS}\n{prompt}\n⏱ {ROUND_SECONDS} ثانیه", reply_markup=markup)
    old = TASKS.pop(rid, None)
    if old and not old.done():
        old.cancel()
    TASKS[rid] = asyncio.create_task(round_timeout(ctx, mid, rid, round_no, ROUND_SECONDS + 1))


async def answer_callback(q, ctx, uid: int, rid: int, value: str):
    with db() as c:
        r = c.execute("SELECT * FROM rounds WHERE id=?", (rid,)).fetchone()
        if not r or r["status"] != "open" or time.time() > r["deadline"]:
            await q.answer("زمان پاسخ تمام شده است.", show_alert=True)
            return
        if not c.execute("SELECT 1 FROM players WHERE match_id=? AND user_id=?", (r["match_id"], uid)).fetchone():
            await q.answer("شما عضو این مسابقه نیستید.", show_alert=True)
            return
        if c.execute("SELECT 1 FROM answers WHERE round_id=? AND user_id=?", (rid, uid)).fetchone():
            await q.answer("پاسخ شما قبلاً ثبت شده است.", show_alert=True)
            return
        try:
            selected = int(value)
        except ValueError:
            await q.answer("پاسخ نامعتبر است.", show_alert=True)
            return
        if selected < 0 or selected >= len(json.loads(r["options"] or "[]")):
            await q.answer("گزینه نامعتبر است.", show_alert=True)
            return
        correct = int(selected == r["answer"])
        points = 0
        if correct:
            points = 10
            if r["game_type"] == "speed":
                elapsed = max(0.0, ROUND_SECONDS - (float(r["deadline"]) - time.time()))
                points += max(0, 5 - int(elapsed // 5))
        c.execute("INSERT INTO answers(round_id,user_id,answer,correct,points) VALUES(?,?,?,?,?)", (rid, uid, value, correct, points))
        c.execute("UPDATE players SET score=score+? WHERE match_id=? AND user_id=?", (points, r["match_id"], uid))
        answered = c.execute("SELECT COUNT(*) n FROM answers WHERE round_id=?", (rid,)).fetchone()["n"]
        total = c.execute("SELECT COUNT(*) n FROM players WHERE match_id=?", (r["match_id"],)).fetchone()["n"]
        mid, no = r["match_id"], r["round_no"]
    if correct and r["game_type"] == "speed":
        feedback = f"⚡ پاسخ درست و سریع! {points} امتیاز گرفتی."
    elif correct:
        feedback = f"آفرین! پاسخ درست بود؛ {points} امتیاز گرفتی."
    else:
        feedback = "پاسخت ثبت شد؛ این بار امتیازی نگرفتی."
    await q.answer(feedback, show_alert=True)
    if answered >= total:
        await close_round(ctx, mid, rid, no)


async def truth_choice(q, ctx, uid: int, rid: int, choice: str):
    with db() as c:
        r = c.execute("SELECT * FROM rounds WHERE id=? AND status='open'", (rid,)).fetchone()
        if not r or time.time() > r["deadline"]:
            await q.answer("زمان این دور تمام شده است.", show_alert=True)
            return
        if not c.execute("SELECT 1 FROM players WHERE match_id=? AND user_id=?", (r["match_id"], uid)).fetchone():
            await q.answer("عضو این مسابقه نیستی.", show_alert=True)
            return
        if c.execute("SELECT 1 FROM truth_choices WHERE round_id=? AND user_id=?", (rid, uid)).fetchone():
            await q.answer("انتخابت قبلاً ثبت شده است.", show_alert=True)
            return
        data = json.loads(r["extra"] or "{}")
        prompt = data.get(choice)
        if not prompt:
            await q.answer("انتخاب نامعتبر است.", show_alert=True)
            return
        c.execute("INSERT INTO truth_choices(round_id,user_id,choice,prompt) VALUES(?,?,?,?)", (rid, uid, choice, prompt))
    await q.answer("انتخاب ثبت شد.")
    await safe_send(ctx, uid, f"{'💬 حقیقت' if choice == 'truth' else '🔥 جرئت'}\n{prompt}\n\nپاسخت را در همین گفت‌وگو بنویس. با ارسال پاسخ ۵ امتیاز می‌گیری.")


async def close_round(ctx, mid: int, rid: int, round_no: int):
    with db() as c:
        r = c.execute("SELECT * FROM rounds WHERE id=?", (rid,)).fetchone()
        if not r or r["status"] != "open":
            return
        c.execute("UPDATE rounds SET status='closed' WHERE id=?", (rid,))
        match = c.execute("SELECT status FROM matches WHERE id=?", (mid,)).fetchone()
        if not match or match["status"] != "running":
            return
        total = c.execute("SELECT COUNT(*) n FROM players WHERE match_id=?", (mid,)).fetchone()["n"]
        answered = c.execute("SELECT COUNT(*) n FROM answers WHERE round_id=?", (rid,)).fetchone()["n"]
        game = r["game_type"]
    task = TASKS.pop(rid, None)
    if task and task is not asyncio.current_task() and not task.done():
        task.cancel()
    if game == "number":
        with db() as c:
            secret = json.loads(r["extra"] or "{}").get("secret", 0)
            rows = c.execute("SELECT user_id,answer FROM answers WHERE round_id=?", (rid,)).fetchall()
            for row in rows:
                try:
                    diff = abs(int(row["answer"]) - secret)
                except ValueError:
                    diff = 30
                pts = 15 if diff == 0 else 10 if diff <= 2 else 5 if diff <= 5 else 0
                c.execute("UPDATE answers SET points=?,correct=? WHERE round_id=? AND user_id=?", (pts, int(diff == 0), rid, row["user_id"]))
                c.execute("UPDATE players SET score=score+? WHERE match_id=? AND user_id=?", (pts, mid, row["user_id"]))
        await announce(ctx, mid, f"🔢 عدد درست {secret} بود. پاسخ‌های ثبت‌شده: {answered}/{total}")
    elif game == "truth":
        await announce(ctx, mid, f"🎭 دور {round_no} تمام شد. پاسخ ثبت‌شده: {answered}/{total}")
    else:
        options = json.loads(r["options"] or "[]")
        correct_text = options[r["answer"]] if options and r["answer"] is not None and 0 <= r["answer"] < len(options) else "نامشخص"
        await announce(ctx, mid, f"⌛ دور {round_no} تمام شد.\nپاسخ درست: {correct_text}\nپاسخ ثبت‌شده: {answered}/{total}")
    if round_no >= TOTAL_ROUNDS:
        await finish_match(ctx, mid)
    else:
        await new_round(ctx, mid, round_no + 1)


async def round_timeout(ctx, mid: int, rid: int, no: int, delay: float):
    try:
        await asyncio.sleep(max(0, delay))
        await close_round(ctx, mid, rid, no)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log_event("error", f"خطای زمان‌سنج دور {rid}: {exc}")


async def finish_match(ctx, mid: int, cancelled: bool = False):
    with db() as c:
        match = c.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone()
        if not match or match["status"] in ("finished", "cancelled"):
            return
        rows = c.execute("""SELECT p.user_id,p.score,u.full_name FROM players p
            JOIN users u ON u.user_id=p.user_id WHERE p.match_id=? ORDER BY p.score DESC,p.joined_at""", (mid,)).fetchall()
        best = max((r["score"] for r in rows), default=0)
        new_status = "cancelled" if cancelled else "finished"
        c.execute("UPDATE matches SET status=?,ended_at=CURRENT_TIMESTAMP WHERE id=?", (new_status, mid))
        if not cancelled:
            for row in rows:
                win = int(row["score"] == best and best > 0)
                loss = int(not win)
                c.execute("""UPDATE users SET total_points=total_points+?,games=games+1,
                    wins=wins+?,losses=losses+?,level=1+CAST((total_points+?)/100 AS INTEGER)
                    WHERE user_id=?""", (row["score"], win, loss, row["score"], row["user_id"]))
    for rid, task in list(TASKS.items()):
        # Cancel only timers belonging to this match.
        with db() as c:
            belongs = c.execute("SELECT 1 FROM rounds WHERE id=? AND match_id=?", (rid, mid)).fetchone()
        if belongs:
            TASKS.pop(rid, None)
            if task is not asyncio.current_task() and not task.done():
                task.cancel()
    if cancelled:
        await announce(ctx, mid, "مسابقه لغو شد.", reply_markup=MENU)
        return
    lines = ["🏁 نتیجه نهایی بازی‌چی"]
    for i, row in enumerate(rows, 1):
        lines.append(f"{i}. {row['full_name']} — {row['score']} امتیاز")
    if rows:
        lines.append(f"\n🏆 برنده: {rows[0]['full_name']}" if best > 0 else "\nاین دور برنده‌ای نداشت؛ دور بعدی تلاش کن!")
    for row in rows:
        await safe_send(ctx, row["user_id"], "\n".join(lines), reply_markup=MENU)


async def leave_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    context.user_data.pop("pending_mode", None)
    context.user_data.pop("pending_group_game", None)
    with db() as c:
        c.execute("DELETE FROM queue_entries WHERE user_id=?", (uid,))
        row = c.execute("SELECT m.id,m.status FROM matches m JOIN players p ON p.match_id=m.id WHERE p.user_id=? AND m.status='running' LIMIT 1", (uid,)).fetchone()
        if row:
            c.execute("DELETE FROM players WHERE match_id=? AND user_id=?", (row["id"], uid))
            remaining = c.execute("SELECT COUNT(*) n FROM players WHERE match_id=?", (row["id"],)).fetchone()["n"]
            if remaining == 0:
                c.execute("UPDATE matches SET status='cancelled',ended_at=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
    await update.message.reply_text("از صف انتظار یا بازی فعال خارج شدی.", reply_markup=MENU)


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return
    if update.effective_chat.type != ChatType.PRIVATE:
        await update.message.reply_text("بازی‌ها فقط در گفت‌وگوی خصوصی ربات اجرا می‌شوند.")
        return
    uid = update.effective_user.id
    with db() as c:
        user = c.execute("SELECT blocked FROM users WHERE user_id=?", (uid,)).fetchone()
        if user:
            c.execute("UPDATE users SET last_seen=CURRENT_TIMESTAMP WHERE user_id=?", (uid,))
    if not user:
        await update.message.reply_text("ابتدا /start را در گفت‌وگوی خصوصی ربات اجرا کن.")
        return
    if user["blocked"]:
        await update.message.reply_text("⛔ دسترسی شما مسدود است.")
        return
    text = update.message.text.strip()
    # Main-menu buttons always take priority over pending free-text answers.
    if main_menu_text(text):
        await menu_router(update, context)
        return
    if context.user_data.get("admin_action"):
        await admin_text(update, context)
        return
    match = active_match(uid)
    if match and match["status"] == "running" and match["game_type"] in ("number", "truth"):
        with db() as c:
            r = c.execute("SELECT * FROM rounds WHERE match_id=? AND status='open' ORDER BY id DESC LIMIT 1", (match["id"],)).fetchone()
            if not r or time.time() > r["deadline"]:
                await update.message.reply_text("زمان پاسخ این دور تمام شده است.")
                return
            if c.execute("SELECT 1 FROM answers WHERE round_id=? AND user_id=?", (r["id"], uid)).fetchone():
                await update.message.reply_text("پاسخ این دور قبلاً ثبت شده است.")
                return
            if match["game_type"] == "number":
                try:
                    guess = int(text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")).translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")))
                except ValueError:
                    await update.message.reply_text("لطفاً فقط یک عدد بین ۱ تا ۳۰ بفرست.")
                    return
                if not 1 <= guess <= 30:
                    await update.message.reply_text("عدد باید بین ۱ تا ۳۰ باشد.")
                    return
                c.execute("INSERT INTO answers(round_id,user_id,answer) VALUES(?,?,?)", (r["id"], uid, str(guess)))
                prompt = "حدس تو ثبت شد."
            else:
                choice = c.execute("SELECT choice FROM truth_choices WHERE round_id=? AND user_id=?", (r["id"], uid)).fetchone()
                if not choice:
                    await update.message.reply_text("ابتدا دکمه حقیقت یا جرئت را انتخاب کن.")
                    return
                c.execute("INSERT INTO answers(round_id,user_id,answer,correct,points) VALUES(?,?,?,1,5)", (r["id"], uid, text[:1000]))
                c.execute("UPDATE players SET score=score+5 WHERE match_id=? AND user_id=?", (match["id"], uid))
                prompt = "پاسخت ثبت شد؛ ۵ امتیاز گرفتی."
            answered = c.execute("SELECT COUNT(*) n FROM answers WHERE round_id=?", (r["id"],)).fetchone()["n"]
            total = c.execute("SELECT COUNT(*) n FROM players WHERE match_id=?", (match["id"],)).fetchone()["n"]
            rid, mid, no = r["id"], match["id"], r["round_no"]
        await update.message.reply_text(prompt)
        if answered >= total:
            await close_round(context, mid, rid, no)
        return
    await update.message.reply_text("از دکمه‌های منوی اصلی استفاده کن.", reply_markup=MENU)


async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with db() as c:
        u = c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        rank = c.execute("SELECT COUNT(*)+1 r FROM users WHERE blocked=0 AND total_points>(SELECT total_points FROM users WHERE user_id=?)", (uid,)).fetchone()["r"]
    await update.message.reply_text(
        f"👤 پروفایل بازی‌چی\nنام: {u['full_name']}\nشناسه تلگرام: {uid}\n"
        f"امتیاز کل: {u['total_points']}\nتعداد بازی: {u['games']}\nبرد: {u['wins']} | باخت: {u['losses']}\n"
        f"سطح: {u['level']}\nرتبه جهانی: {rank}", reply_markup=MENU)


async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as c:
        rows = c.execute("SELECT full_name,total_points,games,wins FROM users WHERE blocked=0 ORDER BY total_points DESC,wins DESC LIMIT 10").fetchall()
    text = "🏆 ۱۰ بازیکن برتر بازی‌چی\n\n" + ("\n".join(f"{i}. {r['full_name']} — {r['total_points']} امتیاز" for i, r in enumerate(rows, 1)) if rows else "هنوز امتیازی ثبت نشده است.")
    await update.message.reply_text(text, reply_markup=MENU)


async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as c:
        rows = c.execute("""SELECT m.id,m.game_type,m.mode,m.status,p.score,m.created_at
            FROM players p JOIN matches m ON m.id=p.match_id WHERE p.user_id=?
            ORDER BY m.id DESC LIMIT 10""", (update.effective_user.id,)).fetchall()
    if not rows:
        text = "📜 هنوز مسابقه‌ای در تاریخچه تو ثبت نشده است."
    else:
        text = "📜 ۱۰ بازی اخیر\n\n" + "\n".join(
            f"#{r['id']} | {GAMES.get(r['game_type'], 'بازی')} | {'انفرادی' if r['mode']=='solo' else 'دونفره' if r['mode']=='duo' else 'چندنفره'} | {r['score']} امتیاز | {r['status']}"
            for r in rows)
    await update.message.reply_text(text, reply_markup=MENU)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    match = active_match(uid)
    if match:
        players = get_players(match["id"])
        mode = "انفرادی" if match["mode"] == "solo" else "دونفره" if match["mode"] == "duo" else "چندنفره"
        await update.message.reply_text(
            f"🎮 بازی فعال داری\nشناسه: #{match['id']}\nبازی: {GAMES.get(match['game_type'], 'نامشخص')}\n"
            f"حالت: {mode}\nبازیکنان: {len(players)}/{match['target_size']}\nامتیاز تو: "
            f"{next((p['score'] for p in players if p['user_id'] == uid), 0)}",
            reply_markup=MENU,
        )
        return
    with db() as c:
        row = c.execute("SELECT game_type,group_size,joined_at FROM queue_entries WHERE user_id=?", (uid,)).fetchone()
        if row:
            count = c.execute("SELECT COUNT(*) n FROM queue_entries WHERE game_type=? AND group_size=?", (row['game_type'], row['group_size'])).fetchone()["n"]
    if row:
        await update.message.reply_text(
            f"⏳ در صف {GAMES.get(row['game_type'], 'بازی')} هستی.\nبازیکنان حاضر: {count}/{row['group_size']}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو انتظار", callback_data="queue:cancel")]]),
        )
    else:
        await update.message.reply_text("در حال حاضر بازی فعال یا انتظار در صف نداری.", reply_markup=MENU)


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = active_match(update.effective_user.id)
    reason = " ".join(context.args).strip() or "گزارش بدون توضیح"
    with db() as c:
        c.execute("INSERT INTO reports(user_id,match_id,reason) VALUES(?,?,?)", (update.effective_user.id, m["id"] if m else None, reason[:500]))
    await update.message.reply_text("گزارش شما برای مدیر ارسال شد. سپاسگزاریم.")


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID or ADMIN_ID == 0:
        await update.message.reply_text("⛔ دسترسی ندارید.")
        return
    with db() as c:
        users = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        active_users = c.execute("SELECT COUNT(*) n FROM users WHERE last_seen>=datetime('now','-1 day')").fetchone()["n"]
        matches = c.execute("SELECT COUNT(*) n FROM matches").fetchone()["n"]
        running = c.execute("SELECT COUNT(*) n FROM matches WHERE status='running'").fetchone()["n"]
        reports = c.execute("SELECT COUNT(*) n FROM reports WHERE status='new'").fetchone()["n"]
        errors = c.execute("SELECT COUNT(*) n FROM events WHERE level='error' AND created_at>=datetime('now','-1 day')").fetchone()["n"]
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 بازی‌های فعال", callback_data="admin:matches"), InlineKeyboardButton("🚨 گزارش‌ها", callback_data="admin:reports")],
        [InlineKeyboardButton("➕ افزودن سؤال", callback_data="admin:addq"), InlineKeyboardButton("📣 پیام همگانی", callback_data="admin:broadcast")],
    ])
    await update.message.reply_text(
        f"🛠 پنل مدیریت بازی‌چی\nکاربران کل: {users}\nفعال در ۲۴ ساعت: {active_users}\n"
        f"کل مسابقات: {matches}\nمسابقات در حال اجرا: {running}\nگزارش‌های جدید: {reports}\nخطاهای ۲۴ ساعت: {errors}",
        reply_markup=keyboard)


async def admin_callback(q, context, uid: int, action: str):
    if uid != ADMIN_ID or ADMIN_ID == 0:
        await q.answer("دسترسی ندارید.", show_alert=True)
        return
    await q.answer()
    if action == "matches":
        with db() as c:
            rows = c.execute("SELECT id,game_type,mode,status,target_size FROM matches WHERE status='running' ORDER BY id DESC LIMIT 15").fetchall()
        if not rows:
            await q.message.reply_text("مسابقه فعالی وجود ندارد.")
            return
        await q.message.reply_text("مسابقات فعال:\n" + "\n".join(f"#{r['id']} {GAMES.get(r['game_type'], '-') } | {r['mode']} | {r['target_size']} نفر" for r in rows),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"پایان #{r['id']}", callback_data=f"adminfinish:{r['id']}"), InlineKeyboardButton(f"لغو #{r['id']}", callback_data=f"admincancel:{r['id']}")] for r in rows]))
    elif action == "reports":
        with db() as c:
            rows = c.execute("SELECT id,user_id,match_id,reason FROM reports WHERE status='new' ORDER BY id DESC LIMIT 20").fetchall()
        await q.message.reply_text("\n".join(f"#{r['id']} | کاربر {r['user_id']} | مسابقه {r['match_id']} | {r['reason']}" for r in rows) or "گزارش جدیدی وجود ندارد.")
    elif action in ("addq", "broadcast"):
        context.user_data["admin_action"] = action
        message = ("قالب سؤال:\nنوع|دسته|سطح|متن سؤال|گزینه۱;گزینه۲;گزینه۳;گزینه۴|شماره پاسخ درست\n"
                   "نوع یکی از این موارد باشد: quiz, word, riddle, speed.\n"
                   "بازی حدس عدد و جرئت یا حقیقت بانک سؤال جداگانه دارند.") if action == "addq" else "متن پیام همگانی را ارسال کن:"
        await q.message.reply_text(message)


async def admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = context.user_data.pop("admin_action", None)
    if update.effective_user.id != ADMIN_ID or not action:
        return
    text = update.message.text.strip()
    if action == "broadcast":
        with db() as c:
            ids = [r["user_id"] for r in c.execute("SELECT user_id FROM users WHERE blocked=0")]
        sent = 0
        for uid in ids:
            if await safe_send(context, uid, "📣 پیام مدیریت بازی‌چی:\n\n" + text):
                sent += 1
        await update.message.reply_text(f"ارسال پیام پایان یافت: {sent}/{len(ids)}")
        return
    try:
        game, category, difficulty, prompt, raw_options, raw_answer = [x.strip() for x in text.split("|", 5)]
        options = [x.strip() for x in raw_options.split(";") if x.strip()]
        answer = int(raw_answer) - 1
        if game not in ("quiz", "word", "riddle", "speed") or len(options) < 2 or answer not in range(len(options)):
            raise ValueError
        with db() as c:
            c.execute("INSERT INTO questions(game_type,category,difficulty,prompt,options,answer) VALUES(?,?,?,?,?,?)",
                      (game, category, difficulty, prompt, json.dumps(options, ensure_ascii=False), answer))
        await update.message.reply_text("✅ سؤال با موفقیت به بانک سؤال اضافه شد.")
    except Exception:
        await update.message.reply_text("قالب نامعتبر است. نمونه:\nquiz|علوم|آسان|پایتخت ایران؟|تهران;شیراز;تبریز;قم|1")


async def block_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID or not context.args:
        await update.message.reply_text("استفاده: /block شناسه_کاربر")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("شناسه باید عددی باشد.")
        return
    with db() as c:
        c.execute("UPDATE users SET blocked=1 WHERE user_id=?", (uid,))
        c.execute("DELETE FROM queue_entries WHERE user_id=?", (uid,))
    await update.message.reply_text("کاربر مسدود شد.")


async def unblock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID or not context.args:
        await update.message.reply_text("استفاده: /unblock شناسه_کاربر")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("شناسه باید عددی باشد.")
        return
    with db() as c:
        c.execute("UPDATE users SET blocked=0 WHERE user_id=?", (uid,))
    await update.message.reply_text("مسدودی کاربر رفع شد.")


async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid, data = q.from_user.id, q.data or ""
    if not is_registered(uid):
        await q.answer("ابتدا /start را اجرا کن یا با مدیر ربات تماس بگیر.", show_alert=True)
        return
    try:
        if data.startswith("game:"):
            await game_selected(q, context, uid, data.split(":", 1)[1])
        elif data.startswith("size:"):
            _, game, raw_size = data.split(":")
            size = int(raw_size)
            if game not in GAMES or not 3 <= size <= MAX_GROUP_SIZE:
                await q.answer("انتخاب نامعتبر است.", show_alert=True)
                return
            if context.user_data.get("pending_group_game") != game:
                await q.answer("ابتدا از منوی چندنفره یک بازی را انتخاب کن.", show_alert=True)
                return
            context.user_data.pop("pending_group_game", None)
            await q.answer()
            await join_queue(context, uid, game, size)
        elif data == "queue:cancel":
            with db() as c:
                deleted = c.execute("DELETE FROM queue_entries WHERE user_id=?", (uid,)).rowcount
            await q.answer("از صف انتظار خارج شدی." if deleted else "در صف انتظاری نیستی.", show_alert=True)
            await q.message.reply_text("انتظار لغو شد. هر زمان خواستی بازی دیگری انتخاب کن.", reply_markup=MENU)
        elif data.startswith("answer:"):
            _, rid, val = data.split(":")
            await answer_callback(q, context, uid, int(rid), val)
        elif data.startswith("truth:"):
            _, rid, choice = data.split(":")
            await truth_choice(q, context, uid, int(rid), choice)
        elif data.startswith("admin:"):
            await admin_callback(q, context, uid, data.split(":", 1)[1])
        elif data.startswith("adminfinish:"):
            if uid != ADMIN_ID:
                await q.answer("دسترسی ندارید.", show_alert=True)
                return
            await q.answer()
            await finish_match(context, int(data.split(":")[1]))
        elif data.startswith("admincancel:"):
            if uid != ADMIN_ID:
                await q.answer("دسترسی ندارید.", show_alert=True)
                return
            await q.answer()
            await finish_match(context, int(data.split(":")[1]), cancelled=True)
        else:
            await q.answer("این دکمه معتبر نیست یا منقضی شده است.", show_alert=True)
    except Exception as exc:
        log_event("error", f"callback {data}: {exc}")
        try:
            await q.answer("خطا رخ داد؛ دوباره تلاش کن.", show_alert=True)
        except Exception:
            pass


async def finish_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    match = active_match(update.effective_user.id)
    if not match:
        await update.message.reply_text("بازی فعالی نداری.")
        return
    if match["mode"] != "solo" and match["host_id"] != update.effective_user.id and update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("فقط شروع‌کننده مسابقه یا مدیر می‌تواند آن را پایان دهد.")
        return
    await finish_match(context, match["id"])


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log_event("error", f"خطای کنترل‌نشده: {context.error}")


async def post_init(app: Application):
    init_db()
    # Resume active rounds after Railway restarts; expired rounds close immediately.
    with db() as c:
        running = c.execute("SELECT id FROM matches WHERE status='running'").fetchall()
        open_rounds = c.execute("SELECT id,match_id,round_no,deadline FROM rounds WHERE status='open'").fetchall()
    open_by_match = {r["match_id"]: r for r in open_rounds}
    for match_row in running:
        mid = match_row["id"]
        current = open_by_match.get(mid)
        if current:
            delay = max(0, current["deadline"] - time.time())
            TASKS[current["id"]] = asyncio.create_task(round_timeout(app, mid, current["id"], current["round_no"], delay))
            await announce(app, mid, "🔄 بازی پس از راه‌اندازی مجدد ادامه پیدا می‌کند.")
        else:
            with db() as c:
                last = c.execute("SELECT COALESCE(MAX(round_no),0) n FROM rounds WHERE match_id=?", (mid,)).fetchone()["n"]
            await new_round(app, mid, last + 1)
    # Keep queued players in the queue across restarts and inform them.
    with db() as c:
        queued = c.execute("SELECT user_id,game_type,group_size FROM queue_entries").fetchall()
    for row in queued:
        await safe_send(app, row["user_id"], f"🔄 صف انتظار حفظ شده است: {GAMES.get(row['game_type'], 'بازی')} — {row['group_size']} نفر.")
    me = await app.bot.get_me()
    log.info("BaziChi started as @%s; DB=%s", me.username, DB_PATH)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("متغیر BOT_TOKEN در Railway تنظیم نشده است.")
    init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("finish", finish_command))
    app.add_handler(CommandHandler("leave", leave_match))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("block", block_command))
    app.add_handler(CommandHandler("unblock", unblock_command))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    log.info("Starting polling")
    app.run_polling(close_loop=True, drop_pending_updates=False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Bot stopped")
