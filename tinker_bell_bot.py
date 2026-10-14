import os
import time
import random
import logging
from threading import Thread

import psycopg2
from psycopg2.extras import RealDictCursor

from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
COOLDOWN = 240

FAIRIES = [
    {"name": "تینکر بل", "talent": "اختراع", "price": 500, "production": 0.10, "capacity": 1000, "max_level": 5},
    {"name": "سیلورمیست", "talent": "آب", "price": 5000, "production": 0.20, "capacity": 5000, "max_level": 10},
    {"name": "روزتا", "talent": "باغبانی", "price": 25000, "production": 0.40, "capacity": 15000, "max_level": 15},
    {"name": "فان", "talent": "حیوانات", "price": 100000, "production": 0.80, "capacity": 40000, "max_level": 20},
    {"name": "ایریدسا", "talent": "نور", "price": 400000, "production": 1.50, "capacity": 100000, "max_level": 25},
    {"name": "ویدیا", "talent": "پرواز سریع", "price": 1500000, "production": 3.00, "capacity": 250000, "max_level": 30},
    {"name": "پری‌وینکل", "talent": "یخ", "price": 5000000, "production": 6.00, "capacity": 600000, "max_level": 35},
    {"name": "زارینا", "talent": "استعداد ویژه", "price": 15000000, "production": 12.00, "capacity": 1500000, "max_level": 40},
]

PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def get_db():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def init_db():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    name TEXT,
                    tinkies INTEGER DEFAULT 0,
                    points BIGINT DEFAULT 0,
                    last_tinky DOUBLE PRECISION DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS fairies (
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    fairy_index INTEGER,
                    level INTEGER DEFAULT 1,
                    stored_points DOUBLE PRECISION DEFAULT 0,
                    last_collection DOUBLE PRECISION DEFAULT 0,
                    PRIMARY KEY (user_id, fairy_index)
                )
            """)
        conn.commit()
    finally:
        conn.close()


def format_number(number):
    number = float(number)
    if number >= 1_000_000_000:
        result = f"{number / 1_000_000_000:.1f}B"
    elif number >= 1_000_000:
        result = f"{number / 1_000_000:.1f}M"
    elif number >= 1_000:
        result = f"{number / 1_000:.1f}K"
    elif number.is_integer():
        result = str(int(number))
    else:
        result = f"{number:.2f}".rstrip("0").rstrip(".")
    return result.translate(PERSIAN_DIGITS)


def format_decimal(number):
    return f"{number:.2f}".translate(PERSIAN_DIGITS)


def get_level(tinkies):
    return min((tinkies // 25) + 1, 25)


def get_production(fairy_index, level):
    return FAIRIES[fairy_index]["production"] * (1 + (level - 1) * 0.35)


def get_capacity(fairy_index, level):
    return int(FAIRIES[fairy_index]["capacity"] * (1 + (level - 1) * 0.30))


def get_upgrade_cost(fairy_index, level):
    return int(FAIRIES[fairy_index]["price"] * (level ** 1.7))


def ensure_user(user):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (user_id, name)
                VALUES (%s, %s)
                ON CONFLICT (user_id)
                DO UPDATE SET name = EXCLUDED.name
                """,
                (user.id, user.first_name or "بازیکن"),
            )
        conn.commit()
    finally:
        conn.close()


def get_user(user_id):
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            return cur.fetchone()
    finally:
        conn.close()


def get_owned_fairies(user_id):
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM fairies WHERE user_id = %s ORDER BY fairy_index",
                (user_id,),
            )
            return cur.fetchall()
    finally:
        conn.close()


def get_fairy(user_id, fairy_index):
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM fairies WHERE user_id = %s AND fairy_index = %s",
                (user_id, fairy_index),
            )
            return cur.fetchone()
    finally:
        conn.close()


def update_user_points(user_id, amount):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET points = points + %s WHERE user_id = %s",
                (amount, user_id),
            )
        conn.commit()
    finally:
        conn.close()


def update_fairy_storage(user_id, fairy_index):
    fairy_data = get_fairy(user_id, fairy_index)
    if not fairy_data:
        return None

    now = time.time()
    last_collection = fairy_data["last_collection"] or now
    elapsed = max(0, now - last_collection)

    production = get_production(fairy_index, fairy_data["level"])
    capacity = get_capacity(fairy_index, fairy_data["level"])
    stored = min(capacity, fairy_data["stored_points"] + elapsed * production)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE fairies
                SET stored_points = %s, last_collection = %s
                WHERE user_id = %s AND fairy_index = %s
                """,
                (stored, now, user_id, fairy_index),
            )
        conn.commit()
    finally:
        conn.close()

    fairy_data["stored_points"] = stored
    fairy_data["last_collection"] = now
    return fairy_data


def update_all_fairies(user_id):
    for fairy in get_owned_fairies(user_id):
        update_fairy_storage(user_id, fairy["fairy_index"])


def main_menu():
    keyboard = [
        [InlineKeyboardButton("🧚🏻‍♀️ پری‌های من", callback_data="my_fairies")],
        [
            InlineKeyboardButton("👤 پروفایل من", callback_data="profile"),
            InlineKeyboardButton("🏆 لیدربرد", callback_data="leaderboard"),
        ],
        [
            InlineKeyboardButton("✨ پری‌های سرزمین", callback_data="fairies"),
            InlineKeyboardButton("💫 درباره‌ی ربات", callback_data="about"),
        ],
        [InlineKeyboardButton("📜 راهنمای بازی", callback_data="guide")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def send_main_menu(message):
    text = (
        "🧚🏻‍♀️✨ منوی اصلی پیکسی هالو ✨🧚🏻‍♀️\n\n"
        "🌸 به سرزمین پری‌ها خوش اومدی!\n\n"
        "🍃 از کجا می‌خوای ماجراجوییت رو ادامه بدی؟\n\n"
        "━━━━━━━━━━━━━━"
    )
    await message.reply_text(text, reply_markup=main_menu())


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)

    text = (
        "🧚🏻‍♀️✨ به پیکسی هالو خوش اومدی! ✨🧚🏻‍♀️\n\n"
        "🌸 به سرزمین اسرارآمیز پری‌ها خوش اومدی!\n\n"
        "جایی که گرد جادویی در هوا می‌درخشه، هر پری استعداد خاص خودش رو داره و ماجراجویی تو تازه شروع شده! 🪄💫\n\n"
        "🧚🏻‍♀️ اینجا می‌تونی:\n\n"
        "୨ৎ پری‌های محبوبت رو جمع‌آوری کنی\n"
        "୨ৎ پری‌های جدید رو آزاد کنی\n"
        "୨ৎ پری‌هات رو ارتقا بدی\n"
        "୨ৎ تینکی‌پوینت جمع کنی و به ثروتمندترین پری‌دار سرزمین تبدیل بشی\n"
        "୨ৎ با بقیه‌ی بازیکن‌ها رقابت کنی و به صدر جدول برسی!\n\n"
        "🍃 هر پری داستان خودش رو داره...\n"
        "✨ و این تویی که قراره داستان خودت رو بسازی!\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "💌 آماده‌ای جادوی خودت رو شروع کنی؟\n\n"
        "🪄 کافیه بگی «تینک» تا جادوی پیکسی هالو برات شروع بشه! ✨🍃\n\n"
        "🦋 بذار جادو آغاز بشه... 🦋"
    )
    await update.message.reply_text(text)


async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)

    data = get_user(user.id)
    owned = get_owned_fairies(user.id)

    text = (
        "🧚🏻‍♀️✨ شناسنامه‌ی پری‌زاد تو ✨🧚🏻‍♀️\n\n"
        "━━━━━━━━━━━━━━\n\n"
        f"👤 نام ماجراجو: {data['name'] or 'بازیکن'}\n"
        f"🌟 سطح جادویی: {format_number(get_level(data['tinkies']))}\n"
        f"🧚🏻‍♀️ پری‌های همراه: {format_number(len(owned))}\n"
        f"💎 کل تینکی‌پوینت‌ها: {format_number(data['points'])}\n"
        f"🪄 تعداد دفعات تینک: {format_number(data['tinkies'])}\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "🍃 هر روز یه قدم به دنیای جادو نزدیک‌تر می‌شی! ✨💚"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text)
    else:
        await update.message.reply_text(text)


def next_fairy_unlocked(user_id, index):
    if index == 0:
        return True

    previous = get_fairy(user_id, index - 1)
    if not previous:
        return False

    return previous["level"] >= FAIRIES[index - 1]["max_level"]


async def show_fairies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)

    owned_indices = {
        fairy["fairy_index"]
        for fairy in get_owned_fairies(user.id)
    }

    lines = [
        "🧚🏻‍♀️ پری‌های پیکسی هالو",
        "",
        "✨ پری موردعلاقه‌ات رو انتخاب کن و به جمع پری‌هات اضافه کن!",
        "",
        "━━━━━━━━━━━━━━",
        "",
    ]
    keyboard = []

    for index, fairy in enumerate(FAIRIES):
        lines.extend([
            f"🧚🏻‍♀️ {fairy['name']}",
            f"🌿 استعداد: {fairy['talent']}",
            f"💰 قیمت: {format_number(fairy['price'])} تینکی‌پوینت",
            f"⚡ تولید: {format_decimal(fairy['production'])} امتیاز در ثانیه",
            "",
            "━━━━━━━━━━━━━━",
            "",
        ])

        if index in owned_indices:
            label = f"✅ {fairy['name']} — خریداری شده"
            callback = f"owned_{index}"
        else:
            label = f"🛒 خرید {fairy['name']}"
            callback = f"buy_{index}"

        keyboard.append([
            InlineKeyboardButton(label, callback_data=callback)
        ])

    lines.append("🍃 با خرید هر پری، قدرت جمع‌آوری تینکی‌پوینت‌هات رو بیشتر کن! 💎")
    keyboard.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu")])

    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_buy_confirmation(update, context, index):
    user = update.effective_user

    if index < 0 or index >= len(FAIRIES):
        await update.callback_query.answer("این پری وجود نداره!", show_alert=True)
        return

    if get_fairy(user.id, index):
        await update.callback_query.answer("این پری رو قبلاً خریدی!", show_alert=True)
        return

    if not next_fairy_unlocked(user.id, index):
        await update.callback_query.answer(
            "برای آزاد کردن این پری، اول پری قبلی رو به حداکثر سطح برسون!",
            show_alert=True,
        )
        return

    fairy = FAIRIES[index]
    user_data = get_user(user.id)

    text = (
        "🧚🏻‍♀️ خرید پری\n\n"
        f"✨ پری انتخاب‌شده: {fairy['name']}\n"
        f"💰 قیمت: {format_number(fairy['price'])} تینکی‌پوینت\n"
        f"💎 موجودی تو: {format_number(user_data['points'])}\n\n"
        "🪄 می‌خوای این پری رو به جمع پری‌هات اضافه کنی؟"
    )

    keyboard = [[
        InlineKeyboardButton("✅ بله", callback_data=f"yes_buy_{index}"),
        InlineKeyboardButton("❌ خیر", callback_data=f"no_buy_{index}"),
    ]]

    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def confirm_buy_fairy(update, context, index):
    user = update.effective_user
    ensure_user(user)

    if index < 0 or index >= len(FAIRIES):
        await update.callback_query.answer("این پری وجود نداره!", show_alert=True)
        return

    fairy = FAIRIES[index]
    conn = get_db()

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT points FROM users WHERE user_id = %s FOR UPDATE",
                (user.id,),
            )
            row = cur.fetchone()

            if not row or row[0] < fairy["price"]:
                conn.rollback()
                await update.callback_query.answer(
                    "تینکی‌پوینت کافی نداری!",
                    show_alert=True,
                )
                return

            cur.execute(
                "SELECT 1 FROM fairies WHERE user_id = %s AND fairy_index = %s",
                (user.id, index),
            )
            if cur.fetchone():
                conn.rollback()
                await update.callback_query.answer(
                    "این پری رو قبلاً خریدی!",
                    show_alert=True,
                )
                return

            if not next_fairy_unlocked(user.id, index):
                conn.rollback()
                await update.callback_query.answer(
                    "این پری هنوز آزاد نشده!",
                    show_alert=True,
                )
                return

            cur.execute(
                "UPDATE users SET points = points - %s WHERE user_id = %s",
                (fairy["price"], user.id),
            )
            cur.execute(
                """
                INSERT INTO fairies
                    (user_id, fairy_index, level, stored_points, last_collection)
                VALUES (%s, %s, 1, 0, %s)
                """,
                (user.id, index, time.time()),
            )

        conn.commit()
    finally:
        conn.close()

    remaining = get_user(user.id)["points"]

    text = (
        "🎉🧚🏻‍♀️ پری جدید به جمع تو پیوست!\n\n"
        f"✨ {fairy['name']} حالا یکی از پری‌های توئه!\n\n"
        f"⚡ تولید: {format_decimal(fairy['production'])} امتیاز در ثانیه\n"
        f"💎 موجودی باقی‌مانده: {format_number(remaining)} تینکی‌پوینت\n\n"
        "🍃 ماجراجویی‌تون تازه شروع شده! 💚"
    )

    await update.callback_query.answer("پری به جمع تو پیوست! 🧚🏻‍♀️")
    await update.callback_query.message.reply_text(text)


async def cancel_buy_fairy(update, context):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "🍃 خرید پری لغو شد!\n\n"
        "🧚🏻‍♀️ اشکالی نداره! هر وقت خواستی می‌تونی برگردی و پری موردعلاقه‌ات رو انتخاب کنی. 💚✨"
    )


async def show_my_fairies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)

    update_all_fairies(user.id)
    owned = get_owned_fairies(user.id)

    if not owned:
        text = (
            "🧚🏻‍♀️ پری‌های من\n\n"
            "━━━━━━━━━━━━━━\n\n"
            "🍃 هنوز هیچ پری‌ای همراهت نیست!\n\n"
            "✨ به بخش «🧚 پری‌ها» سر بزن و اولین پریت رو به سرزمین جادویی خودت بیار! 💚\n\n"
            "━━━━━━━━━━━━━━"
        )

        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(text)
        else:
            await update.message.reply_text(text)
        return

    lines = ["🧚🏻‍♀️ پری‌های من", "", "━━━━━━━━━━━━━━", ""]

    for fairy in owned:
        index = fairy["fairy_index"]
        data = FAIRIES[index]

        lines.extend([
            f"✨ {data['name']}",
            f"🌟 سطح: {format_number(fairy['level'])}/{format_number(data['max_level'])}",
            f"⚡ تولید امتیاز: {format_decimal(get_production(index, fairy['level']))} در ثانیه",
            f"📦 امتیاز ذخیره‌شده: {format_number(fairy['stored_points'])}/{format_number(get_capacity(index, fairy['level']))}",
            "",
            "━━━━━━━━━━━━━━",
            "",
        ])

    lines.append("🍃 پری‌هات رو ارتقا بده تا امتیاز بیشتری برات جمع کنن! 💎")

    keyboard = [[
        InlineKeyboardButton("⬆️ آپگرید", callback_data="upgrade_menu"),
        InlineKeyboardButton("💎 جمع کردن", callback_data="collect"),
    ]]

    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text("\n".join(lines), reply_markup=markup)
    else:
        await update.message.reply_text("\n".join(lines), reply_markup=markup)


async def collect_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)

    update_all_fairies(user.id)
    owned = get_owned_fairies(user.id)

    if not owned:
        text = "🍃 هنوز پری‌ای نداری که برات تینکی‌پوینت جمع کنه!"
    else:
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT points FROM users WHERE user_id = %s FOR UPDATE",
                    (user.id,),
                )

                total = 0.0

                for fairy in owned:
                    cur.execute(
                        """
                        SELECT stored_points
                        FROM fairies
                        WHERE user_id = %s AND fairy_index = %s
                        FOR UPDATE
                        """,
                        (user.id, fairy["fairy_index"]),
                    )
                    row = cur.fetchone()
                    amount = row[0] if row else 0.0
                    total += amount

                whole_total = int(total)

                for fairy in owned:
                    cur.execute(
                        """
                        UPDATE fairies
                        SET stored_points = 0, last_collection = %s
                        WHERE user_id = %s AND fairy_index = %s
                        """,
                        (time.time(), user.id, fairy["fairy_index"]),
                    )

                cur.execute(
                    "UPDATE users SET points = points + %s WHERE user_id = %s",
                    (whole_total, user.id),
                )

            conn.commit()
        finally:
            conn.close()

        if whole_total > 0:
            text = (
                "💎✨ جمع‌آوری تینکی‌پوینت انجام شد!\n\n"
                f"🍃 امتیاز جمع‌آوری‌شده: +{format_number(whole_total)} تینکی‌پوینت"
            )
        else:
            text = (
                "🍃 فعلاً امتیازی برای جمع‌آوری نداری!\n\n"
                "کمی صبر کن تا پری‌هات برات تینکی‌پوینت تولید کنن. 💚"
            )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text)
    else:
        await update.message.reply_text(text)


async def show_upgrade_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    owned = get_owned_fairies(user.id)
    keyboard = []

    if not owned:
        text = "⬆️ هنوز هیچ پری‌ای نداری که ارتقاش بدی!"
    else:
        text = "⬆️✨ پری‌ای رو که می‌خوای ارتقا بدی انتخاب کن:"

        for fairy in owned:
            index = fairy["fairy_index"]
            data = FAIRIES[index]

            if fairy["level"] < data["max_level"]:
                keyboard.append([
                    InlineKeyboardButton(
                        f"🧚🏻‍♀️ {data['name']} — سطح {fairy['level']}",
                        callback_data=f"upgrade_{index}",
                    )
                ])

        if not keyboard:
            text = "✨ همه‌ی پری‌هات به حداکثر سطح خودشون رسیدن!"

    keyboard.append([
        InlineKeyboardButton("🔙 بازگشت به پری‌های من", callback_data="my_fairies")
    ])

    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_upgrade(update, context, index):
    user = update.effective_user
    fairy = get_fairy(user.id, index)

    if not fairy:
        await update.callback_query.answer("این پری رو نداری!", show_alert=True)
        return

    data = FAIRIES[index]
    current_level = fairy["level"]

    if current_level >= data["max_level"]:
        await update.callback_query.answer("این پری به حداکثر سطح رسیده!", show_alert=True)
        return

    next_level = current_level + 1
    cost = get_upgrade_cost(index, current_level)

    text = (
        "⬆️✨ ارتقای پری\n\n"
        f"🧚🏻‍♀️ می‌خوای پری {data['name']} رو ارتقا بدی؟\n\n"
        "━━━━━━━━━━━━━━\n\n"
        f"💎 هزینه: {format_number(cost)} تینکی‌پوینت\n"
        f"⚡ تولید جدید: {format_decimal(get_production(index, next_level))} امتیاز در ثانیه\n"
        f"📦 ظرفیت جدید: {format_number(get_capacity(index, next_level))} تینکی‌پوینت\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "🌟 با این ارتقا، پریت قوی‌تر می‌شه و می‌تونه امتیاز بیشتری برات جمع کنه! 🍃"
    )

    keyboard = [
        [InlineKeyboardButton("✅ تأیید ارتقا", callback_data=f"confirm_upgrade_{index}")],
        [InlineKeyboardButton("🔙 بازگشت به پری‌های من", callback_data="my_fairies")],
    ]

    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def confirm_upgrade(update, context, index):
    user = update.effective_user
    conn = get_db()

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT points FROM users WHERE user_id = %s FOR UPDATE",
                (user.id,),
            )
            row = cur.fetchone()

            cur.execute(
                """
                SELECT level
                FROM fairies
                WHERE user_id = %s AND fairy_index = %s
                FOR UPDATE
                """,
                (user.id, index),
            )
            fairy_row = cur.fetchone()

            if not fairy_row:
                conn.rollback()
                await update.callback_query.answer("این پری رو نداری!", show_alert=True)
                return

            current_level = fairy_row[0]
            data = FAIRIES[index]

            if current_level >= data["max_level"]:
                conn.rollback()
                await update.callback_query.answer("این پری به حداکثر سطح رسیده!", show_alert=True)
                return

            cost = get_upgrade_cost(index, current_level)

            if not row or row[0] < cost:
                conn.rollback()
                await update.callback_query.answer("تینکی‌پوینت کافی نداری!", show_alert=True)
                return

            cur.execute(
                """
                SELECT stored_points, last_collection
                FROM fairies
                WHERE user_id = %s AND fairy_index = %s
                """,
                (user.id, index),
            )
            stored_row = cur.fetchone()

            now = time.time()
            last_collection = stored_row[1] or now
            elapsed = max(0, now - last_collection)
            generated = elapsed * get_production(index, current_level)
            stored = min(
                get_capacity(index, current_level),
                (stored_row[0] or 0) + generated,
            )

            cur.execute(
                "UPDATE users SET points = points - %s WHERE user_id = %s",
                (cost, user.id),
            )

            cur.execute(
                """
                UPDATE fairies
                SET level = level + 1,
                    stored_points = %s,
                    last_collection = %s
                WHERE user_id = %s AND fairy_index = %s
                """,
                (stored, now, user.id, index),
            )

        conn.commit()
    finally:
        conn.close()

    new_level = current_level + 1

    text = (
        "🎉✨ ارتقای پری با موفقیت انجام شد!\n\n"
        f"🧚🏻‍♀️ پری: {data['name']}\n"
        f"🌟 سطح: {format_number(current_level)} ← {format_number(new_level)}\n"
        f"💎 هزینه: {format_number(cost)} تینکی‌پوینت\n"
        f"⚡ تولید جدید: {format_decimal(get_production(index, new_level))} امتیاز در ثانیه\n"
        f"📦 ظرفیت جدید: {format_number(get_capacity(index, new_level))} تینکی‌پوینت"
    )

    await update.callback_query.answer("ارتقا انجام شد! ✨")
    await update.callback_query.message.reply_text(text)


async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)

    conn = get_db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT user_id, name, points
                FROM users
                ORDER BY points DESC, user_id ASC
                LIMIT 3
                """
            )
            top_users = cur.fetchall()

            cur.execute(
                """
                SELECT COUNT(*) + 1 AS rank
                FROM users
                WHERE points > (
                    SELECT points FROM users WHERE user_id = %s
                )
                """,
                (user.id,),
            )
            rank_data = cur.fetchone()
    finally:
        conn.close()

    medals = ["🥇 رتبه‌ی اول", "🥈 رتبه‌ی دوم", "🥉 رتبه‌ی سوم"]
    top_lines = []

    for position, medal in enumerate(medals):
        if position < len(top_users):
            player = top_users[position]
            top_lines.append(f"{medal}: {player['name'] or 'بازیکن'}")
        else:
            top_lines.append(f"{medal}: هنوز بازیکنی نیست")

    user_data = get_user(user.id)
    user_rank = rank_data["rank"] if rank_data else "؟"

    text = (
        "🏆✨ برترین پری‌داران پیکسی هالو ✨🏆\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "🌟 اینجا جایگاه برترین بازیکن‌های سرزمین پری‌هاست!\n\n"
        "🧚🏻‍♀️ هرکسی که تینکی‌پوینت بیشتری جمع کنه، به صدر جدول نزدیک‌تر می‌شه!\n\n"
        + "\n".join(top_lines)
        + "\n\n━━━━━━━━━━━━━━\n\n"
        f"💎 رتبه‌ی تو: {format_number(user_rank)}\n"
        f"✨ تینکی‌پوینت تو: {format_number(user_data['points'])}\n\n"
        "🍃 تلاش کن تا اسم تو هم بین برترین‌های پیکسی هالو بدرخشه! 🪄"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text)
    else:
        await update.message.reply_text(text)


async def show_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🧚🏻‍♀️✨ درباره‌ی پیکسی هالو ✨🧚🏻‍♀️\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "🌸 به دنیای جادویی پری‌ها خوش اومدی!\n\n"
        "🪄 پیکسی هالو یه بازی سرگرم‌کننده با حال‌وهوای دنیای پری‌هاست؛ جایی که می‌تونی پری‌های مختلف رو جمع‌آوری کنی، قدرتشون رو افزایش بدی و برای رسیدن به بالاترین رتبه با بقیه‌ی بازیکن‌ها رقابت کنی!\n\n"
        "🍃 ماجراجویی تو از اینجا شروع می‌شه:\n\n"
        "🧚🏻‍♀️ جمع‌آوری پری‌های دوست‌داشتنی\n"
        "💎 به‌دست‌آوردن تینکی‌پوینت\n"
        "⬆️ ارتقای پری‌ها و افزایش توانایی‌هاشون\n"
        "🏆 رقابت با بازیکن‌های دیگه\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "💚 آماده‌ای جای خودت رو در پیکسی هالو پیدا کنی؟\n\n"
        "✨ جادوی ماجراجویی تو تازه شروع شده! 🦋"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text)
    else:
        await update.message.reply_text(text)


async def show_guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📜🧚🏻‍♀️ راهنمای بازی پیکسی هالو\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "🌱 ۱. شروع ماجراجویی\n\n"
        "🪄 کلمه‌ی «تینک» رو بفرست تا تینکی‌پوینت به دست بیاری!\n\n"
        "⏳ بین هر بار استفاده از «تینک» باید مدت مشخصی صبر کنی.\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "🧚🏻‍♀️ ۲. خرید پری\n\n"
        "✨ وارد بخش «پری‌های سرزمین» شو و پری موردعلاقه‌ات رو انتخاب کن.\n\n"
        "💎 برای خرید هر پری به مقدار مشخصی تینکی‌پوینت نیاز داری.\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "💰 ۳. جمع‌آوری تینکی‌پوینت\n\n"
        "🍃 پری‌هات به‌مرور برات امتیاز تولید می‌کنن.\n\n"
        "📦 برای دریافت امتیازهای ذخیره‌شده، وارد بخش «پری‌های من» شو و روی دکمه‌ی «جمع‌آوری تینکی‌پوینت» بزن.\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "⬆️ ۴. ارتقای پری‌ها\n\n"
        "🌟 با ارتقای پری‌هات می‌تونی سرعت تولید و ظرفیت ذخیره‌ی امتیازشون رو افزایش بدی.\n\n"
        "💎 هزینه‌ی ارتقا به پری و سطح فعلیش بستگی داره.\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "🏆 ۵. لیدربرد\n\n"
        "🥇 از بخش «لیدربرد» رتبه‌ی بازیکن‌ها رو ببین و تلاش کن به جمع برترین پری‌داران پیکسی هالو برسی!\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "💚 حالا وقتشه ماجراجوییت رو شروع کنی!\n\n"
        "🧚🏻‍♀️✨ کلمه‌ی «تینک» رو بفرست و وارد دنیای پری‌ها شو!"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text)
    else:
        await update.message.reply_text(text)


async def handle_tinky(update: Update):
    user = update.effective_user
    ensure_user(user)

    data = get_user(user.id)
    now = time.time()
    elapsed = now - (data["last_tinky"] or 0)

    if elapsed < COOLDOWN:
        remaining = int(COOLDOWN - elapsed)
        minutes, seconds = divmod(remaining, 60)

        if minutes > 0 and seconds > 0:
            remaining_text = f"{format_number(minutes)} دقیقه و {format_number(seconds)} ثانیه"
        elif minutes > 0:
            remaining_text = f"{format_number(minutes)} دقیقه"
        else:
            remaining_text = f"{format_number(seconds)} ثانیه"

        await update.message.reply_text(
            "🍃 هنوز وقت استراحته! 🧚🏻‍♀️\n\n"
            f"🕐 {remaining_text} دیگه می‌تونی دوباره بگی «تینک»! 💚✨"
        )
        return

    old_level = get_level(data["tinkies"])
    reward = random.randint(5, 15) + (old_level - 1) * 2
    new_tinkies = data["tinkies"] + 1
    new_level = get_level(new_tinkies)
    bonus = new_level * 100 if new_level > old_level else 0
    total_reward = reward + bonus

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET tinkies = tinkies + 1,
                    points = points + %s,
                    last_tinky = %s
                WHERE user_id = %s
                """,
                (total_reward, now, user.id),
            )
        conn.commit()
    finally:
        conn.close()

    updated = get_user(user.id)

    if bonus > 0:
        text = (
            "🎉✨ ارتقای سطح! ✨🎉\n\n"
            f"🌟 سطح {format_number(old_level)} ← {format_number(new_level)}\n\n"
            f"💎 امتیاز دریافتی: +{format_number(reward)}\n"
            f"🎁 جایزه‌ی ارتقای سطح: +{format_number(bonus)}"
        )
    else:
        text = (
            "🧚🏻‍♀️✨ تینک! جادوی تو بیدار شد! ✨🪄\n\n"
            f"💎 امتیاز این بار: +{format_number(reward)} تینکی‌پوینت\n"
            f"💰 کل تینکی‌پوینت‌های تو: {format_number(updated['points'])}"
        )

    await update.message.reply_text(text)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if text == "تینک":
        await handle_tinky(update)
    elif text in ["پروفایل", "پروفایل من", "تینکیم"]:
        await show_profile(update, context)
    elif text in ["پری", "پری ها", "پری‌ها", "پری‌های سرزمین", "پری های سرزمین"]:
        await send_main_menu(update.message)
    elif text in ["پری های من", "پری‌های من"]:
        await show_my_fairies(update, context)
    elif text in ["جمع", "جمع کردن", "جمع‌آوری", "جمع آوری", "جمع‌آوری تینکی‌پوینت"]:
        await collect_points(update, context)
    elif text in ["ارتقا", "آپگرید", "اپگرید"]:
        await show_my_fairies(update, context)
    elif text in ["منو", "منوی اصلی", "menu"]:
        await send_main_menu(update.message)
    elif text in ["/top", "لیدربرد", "رتبه", "برترین"]:
        await show_leaderboard(update, context)
    elif text in ["درباره", "درباره‌ی ربات", "درباره ربات"]:
        await show_about(update, context)
    elif text in ["راهنما", "راهنمای بازی"]:
        await show_guide(update, context)


async def send_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_main_menu(update.message)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""

    if data == "menu":
        await query.answer()
        await send_main_menu(query.message)
    elif data == "profile":
        await show_profile(update, context)
    elif data == "fairies":
        await show_fairies(update, context)
    elif data == "my_fairies":
        await show_my_fairies(update, context)
    elif data == "collect":
        await collect_points(update, context)
    elif data == "upgrade_menu":
        await show_upgrade_menu(update, context)
    elif data == "leaderboard":
        await show_leaderboard(update, context)
    elif data == "about":
        await show_about(update, context)
    elif data == "guide":
        await show_guide(update, context)
    elif data.startswith("yes_buy_"):
        try:
            index = int(data.rsplit("_", 1)[1])
        except (ValueError, IndexError):
            await query.answer("خطا!", show_alert=True)
            return
        await confirm_buy_fairy(update, context, index)
    elif data.startswith("no_buy_"):
        await cancel_buy_fairy(update, context)
    elif data.startswith("buy_"):
        try:
            index = int(data.split("_", 1)[1])
        except (ValueError, IndexError):
            await query.answer("خطا!", show_alert=True)
            return
        await show_buy_confirmation(update, context, index)
    elif data.startswith("confirm_upgrade_"):
        try:
            index = int(data.rsplit("_", 1)[1])
        except (ValueError, IndexError):
            await query.answer("خطا!", show_alert=True)
            return
        await confirm_upgrade(update, context, index)
    elif data.startswith("upgrade_"):
        try:
            index = int(data.split("_", 1)[1])
        except (ValueError, IndexError):
            await query.answer("خطا!", show_alert=True)
            return
        await show_upgrade(update, context, index)
    elif data.startswith("owned_"):
        await query.answer("این پری رو قبلاً خریدی! 🧚🏻‍♀️", show_alert=True)
    else:
        await query.answer()


app = Flask(__name__)


@app.route("/")
def home():
    return "Pixie Hollow Bot is running! 🧚🏻‍♀️"


@app.route("/health")
def health():
    return "OK"


def run_flask():
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


async def post_init(application):
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
        bot_info = await application.bot.get_me()
        logging.info("Bot started: @%s", bot_info.username)
    except Exception as e:
        logging.error("Post init error: %s", e)


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not set")

    if not DATABASE_URL:
        raise ValueError("DATABASE_URL is not set")

    init_db()

    Thread(target=run_flask, daemon=True).start()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("top", show_leaderboard))
    application.add_handler(CommandHandler("menu", send_menu_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler)
    )

    logging.info("Pixie Hollow Bot is starting...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
