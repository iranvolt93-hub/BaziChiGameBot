
import os
import re
import time
import random
import sqlite3
import logging
import asyncio
import secrets
from pathlib import Path

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.constants import ChatType
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# ---------------- CONFIG ----------------

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")
DB_PATH = os.getenv("DB_PATH", "bazichi.db")
GAME_TIMEOUT = 45

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("BaziChi")

active_games = {}
game_locks = {}

# ---------------- DATABASE ----------------

def connect_db():
    path = Path(DB_PATH)
    if str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db():
    con = connect_db()

    con.execute("""
        CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            points INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            games INTEGER DEFAULT 0,
            joined_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS groups_data (
            chat_id INTEGER PRIMARY KEY,
            title TEXT DEFAULT '',
            games INTEGER DEFAULT 0
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS game_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            user_id INTEGER,
            game_type TEXT,
            result TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.commit()
    con.close()


def register_player(user):
    con = connect_db()
    con.execute("""
        INSERT INTO players(user_id, username, first_name)
        VALUES(?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET
        username=excluded.username,
        first_name=excluded.first_name
    """, (user.id, user.username or "", user.first_name or "بازیکن"))
    con.commit()
    con.close()


def add_points(user, points, win=False):
    register_player(user)
    con = connect_db()
    con.execute("""
        UPDATE players
        SET points=points+?,
            wins=wins+?,
            games=games+1
        WHERE user_id=?
    """, (points, 1 if win else 0, user.id))
    con.commit()
    con.close()


def record_game(chat, user_id, game_type, result):
    con = connect_db()
    con.execute("""
        INSERT INTO game_history(chat_id,user_id,game_type,result)
        VALUES(?,?,?,?)
    """, (chat.id, user_id, game_type, result))

    con.execute("""
        INSERT INTO groups_data(chat_id,title,games)
        VALUES(?,?,1)
        ON CONFLICT(chat_id) DO UPDATE SET
        title=excluded.title,
        games=games+1
    """, (chat.id, chat.title or "گروه"))
    con.commit()
    con.close()


def get_player(user_id):
    con = connect_db()
    row = con.execute("""
        SELECT points,wins,games FROM players WHERE user_id=?
    """, (user_id,)).fetchone()
    con.close()
    return row or (0, 0, 0)


# ---------------- DATA ----------------

QUIZ = [
    ("پایتخت ژاپن کدام است؟", ["سئول", "توکیو", "پکن", "بانکوک"], 1),
    ("بزرگ‌ترین سیاره منظومه شمسی چیست؟", ["زمین", "مریخ", "مشتری", "زحل"], 2),
    ("نویسنده شاهنامه کیست؟", ["حافظ", "فردوسی", "سعدی", "مولانا"], 1),
    ("واحد شدت جریان برق چیست؟", ["ولت", "آمپر", "وات", "اهم"], 1),
    ("کدام حیوان سریع‌ترین دونده خشکی است؟", ["شیر", "اسب", "یوزپلنگ", "گرگ"], 2),
    ("آب در فشار معمولی در چند درجه می‌جوشد؟", ["۵۰", "۷۵", "۱۰۰", "۱۲۰"], 2),
    ("بزرگ‌ترین قاره جهان کدام است؟", ["آسیا", "اروپا", "آفریقا", "استرالیا"], 0),
    ("کدام سیاره به سیاره سرخ معروف است؟", ["زهره", "مریخ", "عطارد", "نپتون"], 1),
    ("ترکیب آبی و زرد چه رنگی می‌شود؟", ["بنفش", "سبز", "نارنجی", "قرمز"], 1),
    ("کدام فلز در دمای اتاق مایع است؟", ["آهن", "جیوه", "مس", "طلا"], 1),
    ("پایتخت ایران کدام شهر است؟", ["شیراز", "اصفهان", "تهران", "تبریز"], 2),
    ("چند ضلع در یک شش‌ضلعی وجود دارد؟", ["۵", "۶", "۷", "۸"], 1),
]

WORDS = [
    ("وسیله‌ای برای دیدن زمان", "ساعت"),
    ("با آن عکس می‌گیریم", "دوربین"),
    ("در زمستان خانه را گرم می‌کند", "بخاری"),
    ("وسیله‌ای برای باز کردن قفل", "کلید"),
    ("با آن می‌نویسیم", "مداد"),
    ("در آسمان شب می‌درخشد", "ستاره"),
    ("وسیله‌ای برای تماس گرفتن", "تلفن"),
    ("خانه پرنده", "لانه"),
    ("وسیله‌ای برای شستن لباس", "ماشین لباسشویی"),
]

RIDDLES = [
    ("آن چیست که هرچه از آن برداری بزرگ‌تر می‌شود؟", "چاله"),
    ("دندان دارد ولی غذا نمی‌خورد؟", "شانه"),
    ("پا ندارد ولی راه می‌رود؟", "ساعت"),
    ("هرچه خشک می‌کند خودش خیس‌تر می‌شود؟", "حوله"),
    ("کلید دارد ولی قفل باز نمی‌کند؟", "پیانو"),
    ("همیشه جلوی توست اما دیده نمی‌شود؟", "آینده"),
]

TRUTHS = [
    "خنده‌دارترین خاطره دوران مدرسه‌ات چیست؟",
    "اگر یک قدرت جادویی داشتی چه انتخاب می‌کردی؟",
    "یک عادت عجیب خودت را بگو.",
    "آخرین باری که از ته دل خندیدی چه زمانی بود؟",
    "اگر به گذشته برگردی چه چیزی را تغییر می‌دهی؟",
]

DARES = [
    "با سه ایموجی حالت امروزت را توضیح بده.",
    "یک جمله انگیزشی برای گروه بنویس.",
    "اسم یک آهنگ را فقط با ایموجی نشان بده.",
    "از نفر بعدی گروه یک سؤال جالب بپرس.",
    "یک جمله خنده‌دار بساز.",
]

SPEED_TASKS = [
    ("اولین نفری که بنویسد «بازی‌چی» برنده است!", "بازی‌چی"),
    ("اولین نفری که عدد ۷۷ را بفرستد برنده است!", "۷۷"),
    ("اولین نفری که بنویسد «من آماده‌ام» برنده است!", "من آماده‌ام"),
]


# ---------------- KEYBOARDS ----------------

def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🎮 شروع بازی"),
             KeyboardButton("🏆 جدول امتیازات")],
            [KeyboardButton("👤 امتیاز من"),
             KeyboardButton("📚 راهنما")],
        ],
        resize_keyboard=True
    )


def game_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🧠 اطلاعات عمومی", callback_data="game:quiz"),
            InlineKeyboardButton("🔤 حدس کلمه", callback_data="game:word")
        ],
        [
            InlineKeyboardButton("🧩 چیستان", callback_data="game:riddle"),
            InlineKeyboardButton("🎭 جرأت یا حقیقت", callback_data="game:truth")
        ],
        [
            InlineKeyboardButton("🔢 حدس عدد", callback_data="game:number"),
            InlineKeyboardButton("⚡ سرعت عمل", callback_data="game:speed")
        ],
        [
            InlineKeyboardButton("🏆 رتبه‌بندی", callback_data="scores")
        ]
    ])


# ---------------- HELPERS ----------------

def normalize(text):
    text = (text or "").strip().casefold()
    text = text.translate(str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
        "01234567890123456789"
    ))
    return re.sub(r"\s+", " ", text)


def get_lock(chat_id):
    if chat_id not in game_locks:
        game_locks[chat_id] = asyncio.Lock()
    return game_locks[chat_id]


def remove_game(chat_id, game_id):
    game = active_games.get(chat_id)
    if game and game["id"] == game_id:
        active_games.pop(chat_id, None)
        return True
    return False


# ---------------- COMMANDS ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "سلام! به بازی‌چی خوش آمدی 🎮\n\n"
        "اینجا می‌توانی با دوستانت بازی کنی، امتیاز بگیری "
        "و در جدول برترین‌ها قرار بگیری.\n\n"
        "برای شروع بازی گروهی، من را به گروه اضافه کن "
        "و دستور /game را بزن.",
        reply_markup=main_keyboard()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "📚 راهنمای بازی‌چی\n\n"
        "🎮 /game نمایش بازی‌ها\n"
        "🏆 /scores جدول امتیازات\n"
        "👤 /me امتیاز شخصی\n"
        "❌ /cancel لغو بازی جاری\n"
        "🛠 /admin پنل مدیر\n\n"
        "برای دریافت پاسخ اعضا در گروه، Privacy ربات را "
        "در BotFather روی Disable تنظیم کن."
    )


async def game_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.effective_message.reply_text(
            "🎮 بازی‌چی برای بازی گروهی طراحی شده است.\n"
            "ربات را به گروه اضافه کن و دستور /game را بزن."
        )
        return

    await update.effective_message.reply_text(
        "🎮 بازی مورد علاقه‌ات را انتخاب کن:",
        reply_markup=game_keyboard()
    )


async def cancel_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = active_games.pop(chat_id, None)

    if game:
        await update.effective_message.reply_text(
            "❌ بازی توسط کاربر لغو شد."
        )
    else:
        await update.effective_message.reply_text(
            "در حال حاضر بازی فعالی وجود ندارد."
        )


async def my_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    points, wins, games = get_player(user.id)

    await update.effective_message.reply_text(
        f"👤 آمار {user.first_name}\n\n"
        f"⭐ امتیاز: {points}\n"
        f"🏆 برد: {wins}\n"
        f"🎮 بازی ثبت‌شده: {games}"
    )


async def show_scores(message):
    con = connect_db()
    rows = con.execute("""
        SELECT first_name,username,points,wins
        FROM players
        ORDER BY points DESC,wins DESC
        LIMIT 10
    """).fetchall()
    con.close()

    if not rows:
        await message.reply_text("هنوز امتیازی ثبت نشده است. اولین بازی را شروع کنید!")
        return

    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 جدول ۱۰ نفر برتر بازی‌چی\n"]

    for i, row in enumerate(rows):
        name, username, points, wins = row
        display = "@" + username if username else name
        medal = medals[i] if i < 3 else f"{i+1}."
        lines.append(f"{medal} {display} | ⭐ {points} | 🏅 {wins} برد")

    await message.reply_text("\n".join(lines))


async def scores_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_scores(update.effective_message)


# ---------------- GAME ENGINE ----------------

async def timeout_game(app, chat_id, game_id):
    await asyncio.sleep(GAME_TIMEOUT)

    async with get_lock(chat_id):
        game = active_games.get(chat_id)
        if not game or game["id"] != game_id:
            return

        active_games.pop(chat_id, None)
        answer = game.get("answer", "")
        reveal = f"\nپاسخ درست: {answer}" if answer else ""

    try:
        await app.bot.send_message(
            chat_id,
            "⏰ زمان بازی تمام شد!" + reveal +
            "\nبرای بازی بعدی دستور /game را بزنید."
        )
    except Exception:
        logger.exception("Timeout message failed")


async def begin_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat = query.message.chat
    chat_id = chat.id

    if chat.type == ChatType.PRIVATE:
        await query.message.reply_text("این بازی فقط در گروه اجرا می‌شود.")
        return

    async with get_lock(chat_id):
        if chat_id in active_games:
            await query.message.reply_text(
                "⚠️ یک بازی در حال اجراست. ابتدا آن را تمام کنید یا /cancel بزنید."
            )
            return

        kind = query.data.split(":")[1]
        game_id = secrets.token_hex(8)

        game = {
            "id": game_id,
            "type": kind,
            "answer": None,
            "started": time.time(),
            "players": set()
        }

        if kind == "quiz":
            question, options, correct = random.choice(QUIZ)
            game["answer"] = str(correct)
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"{i+1}) {option}",
                    callback_data=f"qa:{game_id}:{i}"
                )]
                for i, option in enumerate(options)
            ])
            text = f"🧠 مسابقه اطلاعات عمومی\n\n{question}\n\n۴۵ ثانیه فرصت دارید!"

        elif kind == "word":
            clue, answer = random.choice(WORDS)
            game["answer"] = normalize(answer)
            text = f"🔤 حدس کلمه\n\nراهنما: {clue}\n\nاولین پاسخ درست برنده است!"

        elif kind == "riddle":
            question, answer = random.choice(RIDDLES)
            game["answer"] = normalize(answer)
            text = f"🧩 چیستان\n\n{question}\n\nپاسخ را در گروه بنویس!"

        elif kind == "number":
            number = random.randint(1, 20)
            game["answer"] = str(number)
            game["low"] = 1
            game["high"] = 20
            text = "🔢 یک عدد بین ۱ تا ۲۰ انتخاب کردم.\nحدس خود را بفرست!"

        elif kind == "speed":
            task, answer = random.choice(SPEED_TASKS)
            game["answer"] = normalize(answer)
            text = f"⚡ مسابقه سرعت\n\n{task}"

        elif kind == "truth":
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("💬 حقیقت", callback_data=f"td:{game_id}:truth"),
                InlineKeyboardButton("🔥 جرأت", callback_data=f"td:{game_id}:dare")
            ]])
            game["answer"] = None
            text = "🎭 جرأت یا حقیقت؟ یکی را انتخاب کن!"
        else:
            return

        active_games[chat_id] = game
        record_game(chat, query.from_user.id, kind, "started")

    if kind in ("quiz", "truth"):
        await query.message.reply_text(text, reply_markup=keyboard)
    else:
        await query.message.reply_text(text)

    context.application.create_task(
        timeout_game(context.application, chat_id, game_id)
    )


async def quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        _, game_id, choice = query.data.split(":")
    except ValueError:
        return

    chat_id = query.message.chat_id

    async with get_lock(chat_id):
        game = active_games.get(chat_id)

        if not game or game["id"] != game_id:
            await query.answer("این مسابقه تمام شده است.", show_alert=True)
            return

        if game["type"] != "quiz":
            return

        if game["answer"] != choice:
            await query.answer("پاسخ اشتباه است؛ دوباره تلاش کن.", show_alert=True)
            return

        active_games.pop(chat_id, None)
        add_points(query.from_user, 3, True)
        record_game(query.message.chat, query.from_user.id, "quiz", "won")

    await query.message.reply_text(
        f"🎉 آفرین {query.from_user.first_name}!\n"
        "پاسخ درست بود و ۳ امتیاز گرفتی."
    )


async def truth_dare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, game_id, choice = query.data.split(":")
    chat_id = query.message.chat_id

    async with get_lock(chat_id):
        game = active_games.get(chat_id)

        if not game or game["id"] != game_id or game["type"] != "truth":
            await query.message.reply_text("این نوبت تمام شده است.")
            return

        active_games.pop(chat_id, None)
        prompt = random.choice(TRUTHS if choice == "truth" else DARES)
        add_points(query.from_user, 1, False)
        record_game(query.message.chat, query.from_user.id, "truth", "played")

    title = "💬 حقیقت" if choice == "truth" else "🔥 جرأت"

    await query.message.reply_text(
        f"{title}\n\n{query.from_user.first_name}، نوبت توست:\n\n"
        f"{prompt}\n\n⭐ یک امتیاز مشارکت گرفتی."
    )


# ---------------- GROUP ANSWERS ----------------

async def group_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat_id = msg.chat_id
    user = update.effective_user

    if not user or user.is_bot or msg.chat.type == ChatType.PRIVATE:
        return

    text = normalize(msg.text)
    if not text:
        return

    if text == "🎮 شروع بازی":
        await game_menu(update, context)
        return

    if text == "🏆 جدول امتیازات":
        await show_scores(msg)
        return

    if text == "👤 امتیاز من":
        await my_score(update, context)
        return

    if text == "📚 راهنما":
        await help_command(update, context)
        return

    async with get_lock(chat_id):
        game = active_games.get(chat_id)
        if not game:
            return

        kind = game["type"]

        if kind == "number":
            if not text.isdigit():
                return

            guess = int(text)
            if not 1 <= guess <= 20:
                return

            answer = int(game["answer"])

            if guess == answer:
                active_games.pop(chat_id, None)
                add_points(user, 3, True)
                record_game(msg.chat, user.id, "number", "won")
                result = f"🎯 درست حدس زدی {user.first_name}!\nعدد {answer} بود؛ ۳ امتیاز گرفتی."
            else:
                result = "⬆️ بزرگ‌تره!" if guess < answer else "⬇️ کوچک‌تره!"

        elif kind in ("word", "riddle", "speed"):
            if text != game["answer"]:
                return

            active_games.pop(chat_id, None)
            add_points(user, 3, True)
            record_game(msg.chat, user.id, kind, "won")
            result = f"🏆 برنده شدی {user.first_name}!\n۳ امتیاز به حسابت اضافه شد."

        else:
            return

    await msg.reply_text(result)


# ---------------- ADMIN ----------------

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not ADMIN_ID or user.id != ADMIN_ID:
        await update.effective_message.reply_text(
            "⛔ دسترسی به پنل مدیریت ندارید."
        )
        return

    con = connect_db()
    players = con.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    points = con.execute("SELECT COALESCE(SUM(points),0) FROM players").fetchone()[0]
    games = con.execute("SELECT COALESCE(SUM(games),0) FROM groups_data").fetchone()[0]
    groups = con.execute("SELECT COUNT(*) FROM groups_data").fetchone()[0]
    con.close()

    await update.effective_message.reply_text(
        "🛠 پنل مدیریت بازی‌چی\n\n"
        f"👥 بازیکنان ثبت‌شده: {players}\n"
        f"👨‍👩‍👧‍👦 گروه‌های فعال: {groups}\n"
        f"🎮 مجموع بازی‌های شروع‌شده: {games}\n"
        f"⭐ مجموع امتیازها: {points}\n\n"
        "برای لغو بازی یک گروه از دستور /cancel در همان گروه استفاده کنید."
    )


async def bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            await update.message.reply_text(
                "سلام دوستان! 🎮\n"
                "من بازی‌چی هستم.\n"
                "برای شروع رقابت گروهی دستور /game را بزنید."
            )


# ---------------- STARTUP ----------------

async def post_init(app: Application):
    me = await app.bot.get_me()
    logger.info("BaziChi started: @%s", me.username)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("متغیر BOT_TOKEN تنظیم نشده است.")

    init_db()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("game", game_menu))
    app.add_handler(CommandHandler("scores", scores_command))
    app.add_handler(CommandHandler("me", my_score))
    app.add_handler(CommandHandler("cancel", cancel_game))
    app.add_handler(CommandHandler("admin", admin_panel))

    app.add_handler(CallbackQueryHandler(begin_game, pattern=r"^game:"))
    app.add_handler(CallbackQueryHandler(quiz_answer, pattern=r"^qa:"))
    app.add_handler(CallbackQueryHandler(truth_dare, pattern=r"^td:"))

    app.add_handler(
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, bot_added)
    )

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, group_text)
    )

    logger.info("Starting BaziChi...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
