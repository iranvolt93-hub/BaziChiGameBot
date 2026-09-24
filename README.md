# Chat2Chat Telegram Bot

ربات آشنایی و چت دونفره داخل تلگرام.

## امکانات نسخه 1
- ثبت پروفایل
- جنسیت و ترجیح طرف مقابل
- سن و شهر
- معرفی کوتاه
- پیدا کردن کاربر مناسب
- چت دونفره
- علاقه‌مندی و Match
- بلاک و گزارش
- SQLite با WAL
- آماده اجرا روی Railway

## متغیرهای Railway
TELEGRAM_BOT_TOKEN = توکن BotFather
DB_PATH = /data/chat2chat.db
ADMIN_ID = آیدی عددی مدیر (اختیاری)

برای حفظ دیتابیس روی Railway، یک Volume بساز و آن را روی `/data` mount کن.

## اجرا
python main.py
