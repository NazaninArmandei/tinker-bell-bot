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
    filters
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

COOLDOWN = 4 * 60

FAIRIES = [
    {
        "name": "تینکر بل",
        "talent": "تینکر",
        "price": 500,
        "production": 0.10,
        "capacity": 1000,
        "max_level": 5
    },
    {
        "name": "سیلورمیست",
        "talent": "آب",
        "price": 5000,
        "production": 0.20,
        "capacity": 5000,
        "max_level": 10
    },
    {
        "name": "روزتا",
        "talent": "باغبانی",
        "price": 25000,
        "production": 0.40,
        "capacity": 15000,
        "max_level": 15
    },
    {
        "name": "فان",
        "talent": "حیوانات",
        "price": 100000,
        "production": 0.80,
        "capacity": 40000,
        "max_level": 20
    },
    {
        "name": "ایریدسا",
        "talent": "نور",
        "price": 400000,
        "production": 1.50,
        "capacity": 100000,
        "max_level": 25
    },
    {
        "name": "ویدیا",
        "talent": "پرواز سریع",
        "price": 1500000,
        "production": 3.00,
        "capacity": 250000,
        "max_level": 30
    },
    {
        "name": "پری‌وینکل",
        "talent": "یخ",
        "price": 5000000,
        "production": 6.00,
        "capacity": 600000,
        "max_level": 35
    },
    {
        "name": "زارینا",
        "talent": "گرد جادویی",
        "price": 15000000,
        "production": 12.00,
        "capacity": 1500000,
        "max_level": 40
    }
]


def get_db():
    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require"
    )


def init_db():
    conn = get_db()
    cur = conn.cursor()

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
    cur.close()
    conn.close()


def format_number(number):
    number = float(number)

    if number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.1f}B"

    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"

    if number >= 1_000:
        return f"{number / 1_000:.1f}K"

    if number.is_integer():
        return str(int(number))

    return f"{number:.1f}"


def get_level(tinkies):
    return min((tinkies // 25) + 1, 25)


def get_production(fairy_index, level):
    fairy = FAIRIES[fairy_index]

    return fairy["production"] * (
        1 + (level - 1) * 0.35
    )


def get_capacity(fairy_index, level):
    fairy = FAIRIES[fairy_index]

    return int(
        fairy["capacity"] * (
            1 + (level - 1) * 0.30
        )
    )


def get_upgrade_cost(fairy_index, level):
    fairy = FAIRIES[fairy_index]

    return int(
        fairy["price"] * (level ** 1.7)
    )


def ensure_user(user):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO users (user_id, name)
        VALUES (%s, %s)
        ON CONFLICT (user_id)
        DO UPDATE SET name = EXCLUDED.name
        """,
        (
            user.id,
            user.first_name or "بازیکن"
        )
    )

    conn.commit()
    cur.close()
    conn.close()


def get_user(user_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute(
        "SELECT * FROM users WHERE user_id = %s",
        (user_id,)
    )

    result = cur.fetchone()

    cur.close()
    conn.close()

    return result


def update_user_points(user_id, amount):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE users
        SET points = points + %s
        WHERE user_id = %s
        """,
        (amount, user_id)
    )

    conn.commit()
    cur.close()
    conn.close()


def get_owned_fairies(user_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute(
        """
        SELECT *
        FROM fairies
        WHERE user_id = %s
        ORDER BY fairy_index
        """,
        (user_id,)
    )

    result = cur.fetchall()

    cur.close()
    conn.close()

    return result


def get_fairy(user_id, fairy_index):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute(
        """
        SELECT *
        FROM fairies
        WHERE user_id = %s AND fairy_index = %s
        """,
        (user_id, fairy_index)
    )

    result = cur.fetchone()

    cur.close()
    conn.close()

    return result


def update_fairy_storage(user_id, fairy_index):
    fairy_data = get_fairy(user_id, fairy_index)

    if not fairy_data:
        return None

    now = time.time()

    last_collection = fairy_data["last_collection"]

    if not last_collection:
        last_collection = now

    elapsed = max(0, now - last_collection)

    production = get_production(
        fairy_index,
        fairy_data["level"]
    )

    capacity = get_capacity(
        fairy_index,
        fairy_data["level"]
    )

    generated = elapsed * production

    stored = min(
        capacity,
        fairy_data["stored_points"] + generated
    )

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE fairies
        SET stored_points = %s,
            last_collection = %s
        WHERE user_id = %s AND fairy_index = %s
        """,
        (
            stored,
            now,
            user_id,
            fairy_index
        )
    )

    conn.commit()
    cur.close()
    conn.close()

    fairy_data["stored_points"] = stored
    fairy_data["last_collection"] = now

    return fairy_data


def update_all_fairies(user_id):
    fairies = get_owned_fairies(user_id)

    for fairy in fairies:
        update_fairy_storage(
            user_id,
            fairy["fairy_index"]
        )


def main_menu():
    keyboard = [
        [
            InlineKeyboardButton(
                "👤 پروفایل",
                callback_data="profile"
            ),
            InlineKeyboardButton(
                "🧚 پری‌ها",
                callback_data="fairies"
            )
        ],
        [
            InlineKeyboardButton(
                "✨ پری‌های من",
                callback_data="my_fairies"
            ),
            InlineKeyboardButton(
                "💰 جمع‌آوری",
                callback_data="collect"
            )
        ],
        [
            InlineKeyboardButton(
                "⬆️ ارتقا",
                callback_data="upgrade_menu"
            ),
            InlineKeyboardButton(
                "🏆 لیدربرد",
                callback_data="leaderboard"
            )
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    ensure_user(user)

    text = (
        "🧚‍♀️✨ به سرزمین جادویی تینکر بل خوش اومدی!\n\n"
        "با گفتن «تینک» تینکی‌پوینت بگیر، "
        "پری‌ها رو بخر، ارتقا بده و تبدیل به قدرتمندترین پری‌دار شو! 💫\n\n"
        "از منوی زیر شروع کن 👇"
    )

    await update.message.reply_text(
        text,
        reply_markup=main_menu()
    )


async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    ensure_user(user)

    data = get_user(user.id)

    update_all_fairies(user.id)

    owned = get_owned_fairies(user.id)

    level = get_level(data["tinkies"])

    text = (
        "👤 **پروفایل شما**\n\n"
        f"✨ نام: {data['name']}\n"
        f"🌟 Level: {level}\n"
        f"🧚 تعداد پری‌ها: {len(owned)}\n"
        f"💎 تینکی‌پوینت: {format_number(data['points'])}\n"
        f"🔮 تعداد تینک‌ها: {data['tinkies']}"
    )

    if update.callback_query:
        await update.callback_query.answer()

        await update.callback_query.message.reply_text(
            text,
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode="Markdown"
        )


async def show_fairies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    ensure_user(user)

    owned = get_owned_fairies(user.id)

    next_index = len(owned)

    if next_index >= len(FAIRIES):
        text = (
            "👑✨ همه‌ی پری‌ها رو داری!\n\n"
            "تو به آخرین مرحله‌ی سرزمین پریان رسیدی 🧚‍♀️"
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "🏠 منوی اصلی",
                    callback_data="menu"
                )
            ]
        ]

        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if next_index > 0:
        previous = owned[-1]

        previous_index = previous["fairy_index"]

        previous_data = FAIRIES[previous_index]

        if previous["level"] < previous_data["max_level"]:
            text = (
                "🔒 این پری هنوز باز نشده!\n\n"
                f"برای باز شدن {FAIRIES[next_index]['name']}،\n"
                f"باید {previous_data['name']} رو به Level "
                f"{previous_data['max_level']} برسونی."
            )

            keyboard = [
                [
                    InlineKeyboardButton(
                        "🏠 منوی اصلی",
                        callback_data="menu"
                    )
                ]
            ]

            await update.callback_query.answer()
            await update.callback_query.message.reply_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

    fairy = FAIRIES[next_index]

    text = (
        "🧚‍♀️ **پری جدید**\n\n"
        f"✨ {fairy['name']}\n"
        f"🌟 استعداد: {fairy['talent']}\n\n"
        f"💰 قیمت: {format_number(fairy['price'])}\n"
        f"⚡ تولید پایه: {fairy['production']}/ثانیه\n"
        f"📦 ظرفیت پایه: {format_number(fairy['capacity'])}\n"
        f"🔝 حداکثر Level: {fairy['max_level']}"
    )

    keyboard = [
        [
            InlineKeyboardButton(
                f"🛒 خرید {fairy['name']}",
                callback_data=f"buy_{next_index}"
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="menu"
            )
        ]
    ]

    await update.callback_query.answer()

    await update.callback_query.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_my_fairies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    ensure_user(user)

    update_all_fairies(user.id)

    owned = get_owned_fairies(user.id)

    if not owned:
        text = (
            "🧚‍♀️ هنوز هیچ پری‌ای نداری!\n\n"
            "از بخش «🧚 پری‌ها» اولین پریت رو بخر."
        )

    else:
        lines = ["🧚‍♀️ **پری‌های من**\n"]

        for fairy in owned:
            index = fairy["fairy_index"]
            data = FAIRIES[index]

            production = get_production(
                index,
                fairy["level"]
            )

            capacity = get_capacity(
                index,
                fairy["level"]
            )

            lines.append(
                f"✨ **{data['name']}**\n"
                f"🌟 Level: {fairy['level']}/{data['max_level']}\n"
                f"⚡ تولید: {production:.2f}/ثانیه\n"
                f"📦 ذخیره: "
                f"{format_number(fairy['stored_points'])}/"
                f"{format_number(capacity)}\n"
            )

        text = "\n".join(lines)

    if update.callback_query:
        await update.callback_query.answer()

        await update.callback_query.message.reply_text(
            text,
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode="Markdown"
        )


async def collect_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    ensure_user(user)

    update_all_fairies(user.id)

    owned = get_owned_fairies(user.id)

    if not owned:
        text = (
            "🧚‍♀️ هنوز پری‌ای نداری که ازش "
            "تینکی‌پوینت جمع کنی!"
        )

    else:
        total = 0

        for fairy in owned:
            fairy_data = get_fairy(
                user.id,
                fairy["fairy_index"]
            )

            if fairy_data:
                amount = fairy_data["stored_points"]

                if amount > 0:
                    total += amount

                    conn = get_db()
                    cur = conn.cursor()

                    cur.execute(
                        """
                        UPDATE fairies
                        SET stored_points = 0,
                            last_collection = %s
                        WHERE user_id = %s
                        AND fairy_index = %s
                        """,
                        (
                            time.time(),
                            user.id,
                            fairy["fairy_index"]
                        )
                    )

                    conn.commit()
                    cur.close()
                    conn.close()

        if total > 0:
            update_user_points(
                user.id,
                int(total)
            )

            text = (
                "💰✨ جمع‌آوری انجام شد!\n\n"
                f"💎 +{format_number(total)} تینکی‌پوینت"
            )
        else:
            text = (
                "💨 فعلاً چیزی برای جمع‌آوری نداری!\n\n"
                "چند دقیقه صبر کن تا پری‌هات دوباره تولید کنن 🧚‍♀️"
            )

    if update.callback_query:
        await update.callback_query.answer()

        await update.callback_query.message.reply_text(
            text
        )
    else:
        await update.message.reply_text(
            text
        )


async def show_upgrade_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    ensure_user(user)

    update_all_fairies(user.id)

    owned = get_owned_fairies(user.id)

    if not owned:
        text = (
            "⬆️ هنوز پری‌ای نداری که ارتقاش بدی!"
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "🏠 منوی اصلی",
                    callback_data="menu"
                )
            ]
        ]

    else:
        text = "⬆️ **کدوم پری رو می‌خوای ارتقا بدی؟**"

        keyboard = []

        for fairy in owned:
            index = fairy["fairy_index"]
            data = FAIRIES[index]

            if fairy["level"] < data["max_level"]:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"✨ {data['name']} — Lv.{fairy['level']}",
                            callback_data=f"upgrade_{index}"
                        )
                    ]
                )

        keyboard.append(
            [
                InlineKeyboardButton(
                    "🏠 منوی اصلی",
                    callback_data="menu"
                )
            ]
        )

    await update.callback_query.answer()

    await update.callback_query.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE, index):
    user = update.effective_user

    fairy = get_fairy(
        user.id,
        index
    )

    if not fairy:
        await update.callback_query.answer(
            "این پری رو نداری!",
            show_alert=True
        )
        return

    data = FAIRIES[index]

    if fairy["level"] >= data["max_level"]:
        await update.callback_query.answer(
            "این پری به حداکثر Level رسیده!",
            show_alert=True
        )
        return

    current_level = fairy["level"]

    next_level = current_level + 1

    cost = get_upgrade_cost(
        index,
        current_level
    )

    current_production = get_production(
        index,
        current_level
    )

    next_production = get_production(
        index,
        next_level
    )

    current_capacity = get_capacity(
        index,
        current_level
    )

    next_capacity = get_capacity(
        index,
        next_level
    )

    text = (
        f"⬆️ **ارتقای {data['name']}**\n\n"
        f"🌟 Level فعلی: {current_level}\n"
        f"✨ Level بعدی: {next_level}\n\n"
        f"⚡ تولید: {current_production:.2f} → "
        f"{next_production:.2f}/ثانیه\n"
        f"📦 ظرفیت: {format_number(current_capacity)} → "
        f"{format_number(next_capacity)}\n\n"
        f"💰 هزینه ارتقا: {format_number(cost)}"
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "⬆️ ارتقا",
                callback_data=f"confirm_upgrade_{index}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 برگشت",
                callback_data="upgrade_menu"
            )
        ]
    ]

    await update.callback_query.answer()

    await update.callback_query.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def confirm_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE, index):
    user = update.effective_user

    fairy = get_fairy(
        user.id,
        index
    )

    if not fairy:
        await update.callback_query.answer(
            "این پری رو نداری!",
            show_alert=True
        )
        return

    data = FAIRIES[index]

    current_level = fairy["level"]

    if current_level >= data["max_level"]:
        await update.callback_query.answer(
            "این پری در بالاترین Level است!",
            show_alert=True
        )
        return

    cost = get_upgrade_cost(
        index,
        current_level
    )

    user_data = get_user(user.id)

    if user_data["points"] < cost:
        await update.callback_query.answer(
            "تینکی‌پوینت کافی نداری!",
            show_alert=True
        )
        return

    update_fairy_storage(
        user.id,
        index
    )

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE users
        SET points = points - %s
        WHERE user_id = %s
        """,
        (
            cost,
            user.id
        )
    )

    cur.execute(
        """
        UPDATE fairies
        SET level = level + 1
        WHERE user_id = %s
        AND fairy_index = %s
        """,
        (
            user.id,
            index
        )
    )

    conn.commit()
    cur.close()
    conn.close()

    new_level = current_level + 1

    text = (
        "🎉✨ ارتقا با موفقیت انجام شد!\n\n"
        f"🧚‍♀️ {data['name']}\n"
        f"🌟 Level {current_level} → {new_level}\n\n"
        f"💰 هزینه: {format_number(cost)}"
    )

    keyboard = []

    if new_level < data["max_level"]:
        keyboard.append(
            [
                InlineKeyboardButton(
                    "✨ ارتقای بیشتر",
                    callback_data=f"upgrade_{index}"
                )
            ]
        )
    else:
        if index + 1 < len(FAIRIES):
            keyboard.append(
                [
                    InlineKeyboardButton(
                        "🔓 پری بعدی",
                        callback_data="fairies"
                    )
                ]
            )

    keyboard.append(
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="menu"
            )
        ]
    )

    await update.callback_query.answer(
        "ارتقا انجام شد! ✨"
    )

    await update.callback_query.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def buy_fairy(update: Update, context: ContextTypes.DEFAULT_TYPE, index):
    user = update.effective_user

    ensure_user(user)

    owned = get_owned_fairies(user.id)

    expected_index = len(owned)

    if index != expected_index:
        await update.callback_query.answer(
            "این پری هنوز قابل خرید نیست!",
            show_alert=True
        )
        return

    if index >= len(FAIRIES):
        await update.callback_query.answer(
            "همه‌ی پری‌ها رو داری!",
            show_alert=True
        )
        return

    if index > 0:
        previous = owned[-1]

        previous_data = FAIRIES[
            previous["fairy_index"]
        ]

        if previous["level"] < previous_data["max_level"]:
            await update.callback_query.answer(
                "اول پری قبلی رو به Level نهایی برسون!",
                show_alert=True
            )
            return

    fairy = FAIRIES[index]

    user_data = get_user(user.id)

    if user_data["points"] < fairy["price"]:
        await update.callback_query.answer(
            "تینکی‌پوینت کافی نداری!",
            show_alert=True
        )
        return

    now = time.time()

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE users
        SET points = points - %s
        WHERE user_id = %s
        """,
        (
            fairy["price"],
            user.id
        )
    )

    cur.execute(
        """
        INSERT INTO fairies (
            user_id,
            fairy_index,
            level,
            stored_points,
            last_collection
        )
        VALUES (%s, %s, 1, 0, %s)
        """,
        (
            user.id,
            index,
            now
        )
    )

    conn.commit()
    cur.close()
    conn.close()

    text = (
        "🎉🧚‍♀️ **پری جدید به دستت رسید!**\n\n"
        f"✨ {fairy['name']}\n"
        f"🌟 استعداد: {fairy['talent']}\n\n"
        f"💰 هزینه: {format_number(fairy['price'])}\n\n"
        "از این به بعد این پری برات تینکی‌پوینت تولید می‌کنه! 💎"
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="menu"
            )
        ]
    ]

    await update.callback_query.answer(
        "پری خریداری شد! 🧚‍♀️"
    )

    await update.callback_query.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    ensure_user(user)

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute(
        """
        SELECT
            user_id,
            name,
            points
        FROM users
        ORDER BY points DESC, user_id ASC
        LIMIT 10
        """
    )

    top_users = cur.fetchall()

    cur.execute(
        """
        SELECT COUNT(*) + 1 AS rank
        FROM users
        WHERE points > (
            SELECT points
            FROM users
            WHERE user_id = %s
        )
        """,
        (user.id,)
    )

    rank_data = cur.fetchone()

    cur.close()
    conn.close()

    user_rank = rank_data["rank"] if rank_data else "?"

    lines = [
        "🏆 **لیدربرد برترین پری‌داران**\n"
    ]

    medals = ["🥇", "🥈", "🥉"]

    if not top_users:
        lines.append("هنوز کسی وارد لیدربرد نشده!")
    else:
        for position, player in enumerate(top_users, start=1):
            medal = (
                medals[position - 1]
                if position <= 3
                else f"{position}."
            )

            name = player["name"] or "بازیکن"

            if len(name) > 18:
                name = name[:18] + "…"

            lines.append(
                f"{medal} {name} — "
                f"💎 {format_number(player['points'])}"
            )

    user_data = get_user(user.id)

    lines.append(
        "\n━━━━━━━━━━━━━━\n"
        f"👤 رتبه شما: **#{user_rank}**\n"
        f"💎 امتیاز شما: **{format_number(user_data['points'])}**"
    )

    text = "\n".join(lines)

    keyboard = [
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="menu"
            )
        ]
    ]

    if update.callback_query:
        await update.callback_query.answer()

        await update.callback_query.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def handle_tinky(update: Update):
    user = update.effective_user

    ensure_user(user)

    data = get_user(user.id)

    now = time.time()

    elapsed = now - data["last_tinky"]

    if elapsed < COOLDOWN:
        remaining = int(COOLDOWN - elapsed)

        minutes = remaining // 60
        seconds = remaining % 60

        if minutes > 0:
            text = (
                f"⏳ هنوز زوده!\n\n"
                f"🕐 {minutes} دقیقه و {seconds} ثانیه دیگه دوباره بگو «تینک»."
            )
        else:
            text = (
                f"⏳ هنوز زوده!\n\n"
                f"🕐 {seconds} ثانیه دیگه دوباره بگو «تینک»."
            )

        await update.message.reply_text(text)
        return

    current_level = get_level(
        data["tinkies"]
    )

    reward = random.randint(5, 15)

    reward += (current_level - 1) * 2

    old_level = current_level

    new_tinkies = data["tinkies"] + 1

    new_level = get_level(
        new_tinkies
    )

    bonus = 0

    if new_level > old_level:
        bonus = new_level * 100

    total_reward = reward + bonus

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE users
        SET tinkies = tinkies + 1,
            points = points + %s,
            last_tinky = %s
        WHERE user_id = %s
        """,
        (
            total_reward,
            now,
            user.id
        )
    )

    conn.commit()
    cur.close()
    conn.close()

    if bonus > 0:
        text = (
            "🎉✨ **LEVEL UP!** ✨🎉\n\n"
            f"🌟 Level {old_level} → {new_level}\n\n"
            f"💎 پاداش تینک: +{reward}\n"
            f"🎁 جایزه Level Up: +{bonus}\n\n"
            f"💰 مجموع: **+{total_reward}**"
        )
    else:
        text = (
            "✨ تینک! 🧚‍♀️\n\n"
            f"💎 +{total_reward} تینکی‌پوینت\n"
            f"🌟 Level: {new_level}"
        )

    await update.message.reply_text(text)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if text == "تینک":
        await handle_tinky(update)
        return

    if text in ["پروفایل", "تینکیم"]:
        await show_profile(update, context)
        return

    if text in ["پری", "پری ها", "پری‌ها"]:
        await update.message.reply_text(
            "🧚‍♀️ بخش پری‌ها رو از منوی اصلی باز کن."
        )
        return

    if text in ["پری های من", "پری‌های من"]:
        await show_my_fairies(update, context)
        return

    if text in ["جمع", "جمع کردن"]:
        await collect_points(update, context)
        return

    if text in ["ارتقا", "آپگرید", "اپگرید"]:
        await update.message.reply_text(
            "⬆️ بخش ارتقا رو از منوی اصلی باز کن."
        )
        return

    if text in ["/top", "لیدربرد", "رتبه", "برترین"]:
        await show_leaderboard(update, context)
        return


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    data = query.data

    if data == "menu":
        await query.answer()

        await query.message.reply_text(
            "🏡 **منوی اصلی**",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )
        return

    if data == "profile":
        await show_profile(update, context)
        return

    if data == "fairies":
        await show_fairies(update, context)
        return

    if data == "my_fairies":
        await show_my_fairies(update, context)
        return

    if data == "collect":
        await collect_points(update, context)
        return

    if data == "upgrade_menu":
        await show_upgrade_menu(update, context)
        return

    if data == "leaderboard":
        await show_leaderboard(update, context)
        return

    if data.startswith("buy_"):
        try:
            index = int(data.split("_")[1])
        except (ValueError, IndexError):
            await query.answer(
                "خطا!",
                show_alert=True
            )
            return

        await buy_fairy(
            update,
            context,
            index
        )
        return

    if data.startswith("confirm_upgrade_"):
        try:
            index = int(
                data.split("_")[2]
            )
        except (ValueError, IndexError):
            await query.answer(
                "خطا!",
                show_alert=True
            )
            return

        await confirm_upgrade(
            update,
            context,
            index
        )
        return

    if data.startswith("upgrade_"):
        try:
            index = int(
                data.split("_")[1]
            )
        except (ValueError, IndexError):
            await query.answer(
                "خطا!",
                show_alert=True
            )
            return

        await show_upgrade(
            update,
            context,
            index
        )
        return

    await query.answer()


app = Flask(__name__)


@app.route("/")
def home():
    return "Tinker Bell Bot is running! 🧚‍♀️"


@app.route("/health")
def health():
    return "OK"


def run_flask():
    port = int(
        os.getenv("PORT", 10000)
    )

    app.run(
        host="0.0.0.0",
        port=port
    )


async def post_init(application):
    try:
        await application.bot.delete_webhook(
            drop_pending_updates=True
        )

        bot_info = await application.bot.get_me()

        logging.info(
            f"Bot started: @{bot_info.username}"
        )

    except Exception as e:
        logging.error(
            f"Post init error: {e}"
        )


def main():
    if not BOT_TOKEN:
        raise ValueError(
            "BOT_TOKEN is not set"
        )

    if not DATABASE_URL:
        raise ValueError(
            "DATABASE_URL is not set"
        )

    init_db()

    Thread(
        target=run_flask,
        daemon=True
    ).start()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "top",
            show_leaderboard
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            message_handler
        )
    )

    logging.info(
        "Tinker Bell Bot is starting..."
    )

    while True:
        try:
            application.run_polling(
                drop_pending_updates=True
            )

        except Exception as e:
            logging.error(
                f"Bot crashed: {e}"
            )

            time.sleep(10)


if __name__ == "__main__":
    main()
