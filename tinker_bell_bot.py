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
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)

logger = logging.getLogger("TinkerBellBot")

TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing.")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is missing.")

COOLDOWN = 4 * 60
MAX_LEVEL = 25

FAIRIES = [
    {
        "name": "Tinker Bell",
        "talent": "Tinker",
        "price": 500,
        "production": 1,
        "capacity": 1000
    },
    {
        "name": "Silvermist",
        "talent": "Water",
        "price": 5000,
        "production": 2,
        "capacity": 5000
    },
    {
        "name": "Rosetta",
        "talent": "Garden",
        "price": 25000,
        "production": 4,
        "capacity": 15000
    },
    {
        "name": "Fawn",
        "talent": "Animal",
        "price": 100000,
        "production": 8,
        "capacity": 40000
    },
    {
        "name": "Iridessa",
        "talent": "Light",
        "price": 400000,
        "production": 15,
        "capacity": 100000
    },
    {
        "name": "Vidia",
        "talent": "Fast Flying",
        "price": 1500000,
        "production": 30,
        "capacity": 250000
    },
    {
        "name": "Periwinkle",
        "talent": "Frost",
        "price": 5000000,
        "production": 60,
        "capacity": 600000
    },
    {
        "name": "Zarina",
        "talent": "Pixie Dust",
        "price": 15000000,
        "production": 120,
        "capacity": 1500000
    }
]


def db():
    return psycopg2.connect(
        DATABASE_URL,
        connect_timeout=10
    )


def setup_database():
    for attempt in range(1, 6):
        connection = None
        cursor = None

        try:
            logger.info(
                "Connecting to PostgreSQL... attempt %s/5",
                attempt
            )

            connection = db()
            cursor = connection.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    name TEXT,
                    tinkies INTEGER DEFAULT 0,
                    points BIGINT DEFAULT 0,
                    last_tinky DOUBLE PRECISION DEFAULT 0
                );
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS fairies (
                    user_id BIGINT REFERENCES users(user_id)
                    ON DELETE CASCADE,
                    fairy_index INTEGER,
                    level INTEGER DEFAULT 1,
                    stored_points DOUBLE PRECISION DEFAULT 0,
                    last_collection DOUBLE PRECISION DEFAULT 0,
                    PRIMARY KEY (user_id, fairy_index)
                );
            """)

            connection.commit()

            logger.info("PostgreSQL database is ready.")
            return

        except Exception:
            logger.exception("Database setup failed.")

            if attempt < 5:
                time.sleep(5)

        finally:
            if cursor:
                cursor.close()

            if connection:
                connection.close()

    raise RuntimeError(
        "Could not initialize PostgreSQL database."
    )


def format_number(number):
    return f"{int(number):,}"


def get_user(user_id, name):
    connection = db()
    cursor = connection.cursor(
        cursor_factory=RealDictCursor
    )

    try:
        cursor.execute(
            """
            INSERT INTO users
            (
                user_id,
                name,
                tinkies,
                points,
                last_tinky
            )
            VALUES (%s, %s, 0, 0, 0)
            ON CONFLICT (user_id)
            DO UPDATE SET name = EXCLUDED.name
            RETURNING tinkies, points, last_tinky
            """,
            (
                user_id,
                name
            )
        )

        user = cursor.fetchone()

        connection.commit()

        return (
            user["tinkies"],
            user["points"],
            user["last_tinky"]
        )

    finally:
        cursor.close()
        connection.close()


def save_user(
    user_id,
    name,
    tinkies,
    points,
    last_tinky
):
    connection = db()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            UPDATE users
            SET
                name = %s,
                tinkies = %s,
                points = %s,
                last_tinky = %s
            WHERE user_id = %s
            """,
            (
                name,
                tinkies,
                points,
                last_tinky,
                user_id
            )
        )

        connection.commit()

    finally:
        cursor.close()
        connection.close()


def get_owned_fairies(user_id):
    connection = db()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT
                fairy_index,
                level,
                stored_points,
                last_collection
            FROM fairies
            WHERE user_id = %s
            ORDER BY fairy_index
            """,
            (user_id,)
        )

        return cursor.fetchall()

    finally:
        cursor.close()
        connection.close()


def get_fairy(user_id, fairy_index):
    connection = db()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT
                level,
                stored_points,
                last_collection
            FROM fairies
            WHERE user_id = %s
            AND fairy_index = %s
            """,
            (
                user_id,
                fairy_index
            )
        )

        return cursor.fetchone()

    finally:
        cursor.close()
        connection.close()


def add_fairy(user_id, fairy_index):
    connection = db()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO fairies
            (
                user_id,
                fairy_index,
                level,
                stored_points,
                last_collection
            )
            VALUES (%s, %s, 1, 0, %s)
            """,
            (
                user_id,
                fairy_index,
                time.time()
            )
        )

        connection.commit()

    finally:
        cursor.close()
        connection.close()


def get_production(fairy_index, level):
    base = FAIRIES[fairy_index]["production"]

    return int(
        base * (
            1 + (level - 1) * 0.35
        )
    )


def get_capacity(fairy_index, level):
    base = FAIRIES[fairy_index]["capacity"]

    return int(
        base * (
            1 + (level - 1) * 0.30
        )
    )


def update_fairy_storage(user_id, fairy_index):
    fairy = get_fairy(
        user_id,
        fairy_index
    )

    if fairy is None:
        return

    level, stored, last_collection = fairy

    now = time.time()

    elapsed = max(
        0,
        now - last_collection
    )

    production = get_production(
        fairy_index,
        level
    )

    capacity = get_capacity(
        fairy_index,
        level
    )

    generated = elapsed * production

    stored = min(
        capacity,
        stored + generated
    )

    connection = db()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            UPDATE fairies
            SET
                stored_points = %s,
                last_collection = %s
            WHERE user_id = %s
            AND fairy_index = %s
            """,
            (
                stored,
                now,
                user_id,
                fairy_index
            )
        )

        connection.commit()

    finally:
        cursor.close()
        connection.close()


def update_all_fairies(user_id):
    fairies = get_owned_fairies(user_id)

    for fairy in fairies:
        update_fairy_storage(
            user_id,
            fairy[0]
        )


def get_level(tinkies):
    return min(
        (tinkies // 25) + 1,
        MAX_LEVEL
    )


def get_tinky_reward(level):
    base_reward = random.randint(5, 15)
    level_bonus = (level - 1) * 2

    return base_reward + level_bonus


def get_upgrade_cost(fairy_index, level):
    return int(
        FAIRIES[fairy_index]["price"] *
        (level ** 1.7)
    )


def main_menu():
    keyboard = [
        [
            InlineKeyboardButton(
                "👤 پروفایل",
                callback_data="profile"
            ),
            InlineKeyboardButton(
                "🧚‍♀️ پری‌ها",
                callback_data="fairies"
            )
        ],
        [
            InlineKeyboardButton(
                "🧚‍♀️ پری‌های من",
                callback_data="my_fairies"
            ),
            InlineKeyboardButton(
                "💚 جمع کردن",
                callback_data="collect"
            )
        ],
        [
            InlineKeyboardButton(
                "📈 ارتقای پری",
                callback_data="upgrade_menu"
            )
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


async def send_reply(
    update,
    text,
    reply_markup=None
):
    if update.callback_query:
        await update.callback_query.message.reply_text(
            text,
            reply_markup=reply_markup
        )

    elif update.message:
        await update.message.reply_text(
            text,
            reply_markup=reply_markup
        )


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    logger.info(
        "START command from user %s",
        update.effective_user.id
    )

    get_user(
        update.effective_user.id,
        update.effective_user.first_name or "Fairy"
    )

    await send_reply(
        update,
        "🧚‍♀️✨ تینکر بل ✨🧚‍♀️\n\n"
        "سلام پری کوچولو! 🌸\n"
        "به سرزمین پری‌ها خوش اومدی! 🧚‍♀️🌿\n\n"
        "🔔 با گفتن «تینک» می‌تونی تینکی و امتیاز تینکی بگیری.\n\n"
        "💚 با امتیازهای تینکی می‌تونی:\n\n"
        "🧚‍♀️ پری بخری\n"
        "📈 پری‌هات رو تا سطح ۲۵ ارتقا بدی\n"
        "⚡ از پری‌هات امتیاز جمع کنی\n"
        "📦 ظرفیت پری‌هات رو افزایش بدی\n"
        "🔓 بعد از رسیدن اولین پری به سطح ۲۵، پری بعدی رو آزاد کنی\n\n"
        "✨ هر پری:\n"
        "🌿 یک استعداد مخصوص داره\n"
        "⚡ در هر ثانیه امتیاز تولید می‌کنه\n"
        "📦 ظرفیت مشخصی برای ذخیره امتیاز داره\n\n"
        "🌸 آماده‌ای وارد سرزمین پری‌ها بشی؟\n\n"
        "✨ بگو «تینک» تا شروع کنیم! ✨",
        main_menu()
    )


async def profile(update: Update):
    user = update.effective_user

    tinkies, points, last_tinky = get_user(
        user.id,
        user.first_name or "Fairy"
    )

    level = get_level(tinkies)

    await send_reply(
        update,
        "🧚‍♀️✨ پروفایل تینکی ✨🧚‍♀️\n\n"
        f"🌟 سطح: {level}\n"
        f"🔔 تینکی‌ها: {tinkies}\n"
        f"💚 امتیاز تینکی: "
        f"{format_number(points)}",
        main_menu()
    )


async def fairies(update: Update):
    user = update.effective_user

    tinkies, points, last_tinky = get_user(
        user.id,
        user.first_name or "Fairy"
    )

    owned = get_owned_fairies(user.id)

    next_index = len(owned)

    if next_index >= len(FAIRIES):
        await send_reply(
            update,
            "🧚‍♀️✨ فروشگاه پری‌ها ✨🧚‍♀️\n\n"
            "🎉 همه پری‌ها رو آزاد کردی!",
            main_menu()
        )
        return

    if next_index > 0:
        previous = owned[-1]

        if previous[1] < MAX_LEVEL:
            await send_reply(
                update,
                "🔒 پری بعدی هنوز قفل است!\n\n"
                f"🧚‍♀️ پری فعلی: "
                f"{FAIRIES[previous[0]]['name']}\n"
                f"🌟 سطح فعلی: "
                f"{previous[1]}/{MAX_LEVEL}\n\n"
                "برای باز شدن پری بعدی، "
                "پری فعلی را به سطح ۲۵ برسان.",
                main_menu()
            )
            return

    fairy = FAIRIES[next_index]

    keyboard = [
        [
            InlineKeyboardButton(
                f"🛒 خرید {fairy['name']}",
                callback_data=f"buy_{next_index}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 منوی اصلی",
                callback_data="menu"
            )
        ]
    ]

    await send_reply(
        update,
        "🧚‍♀️✨ فروشگاه پری‌ها ✨🧚‍♀️\n\n"
        f"🧚‍♀️ {fairy['name']}\n"
        f"🌿 استعداد: {fairy['talent']}\n\n"
        f"💰 قیمت: "
        f"{format_number(fairy['price'])} امتیاز\n"
        f"⚡ تولید اولیه: "
        f"{format_number(fairy['production'])} در ثانیه\n"
        f"📦 ظرفیت اولیه: "
        f"{format_number(fairy['capacity'])}\n\n"
        f"💚 موجودی شما: "
        f"{format_number(points)} امتیاز",
        InlineKeyboardMarkup(keyboard)
    )


async def my_fairies(update: Update):
    user = update.effective_user

    owned = get_owned_fairies(user.id)

    if not owned:
        await send_reply(
            update,
            "🧚‍♀️✨ پری‌های من ✨🧚‍♀️\n\n"
            "هنوز پری‌ای نداری! 🌸\n\n"
            "💚 از فروشگاه اولین پریت رو بخر.",
            main_menu()
        )
        return

    update_all_fairies(user.id)

    owned = get_owned_fairies(user.id)

    message = "🧚‍♀️✨ پری‌های من ✨🧚‍♀️\n\n"

    for (
        fairy_index,
        level,
        stored,
        last_collection
    ) in owned:

        fairy = FAIRIES[fairy_index]

        production = get_production(
            fairy_index,
            level
        )

        capacity = get_capacity(
            fairy_index,
            level
        )

        message += (
            f"🧚‍♀️ {fairy['name']}\n"
            f"🌿 استعداد: {fairy['talent']}\n"
            f"🌟 سطح: {level}/{MAX_LEVEL}\n"
            f"⚡ تولید: "
            f"{format_number(production)} در ثانیه\n"
            f"📦 ظرفیت: "
            f"{format_number(capacity)}\n"
            f"💚 ذخیره: "
            f"{format_number(stored)}\n\n"
        )

    await send_reply(
        update,
        message,
        main_menu()
    )


async def collect(update: Update):
    user = update.effective_user

    owned = get_owned_fairies(user.id)

    if not owned:
        await send_reply(
            update,
            "💚 هنوز پری‌ای نداری که ازش "
            "امتیاز جمع کنی.",
            main_menu()
        )
        return

    update_all_fairies(user.id)

    owned = get_owned_fairies(user.id)

    total = 0

    connection = db()
    cursor = connection.cursor()

    try:
        now = time.time()

        for (
            fairy_index,
            level,
            stored,
            last_collection
        ) in owned:

            amount = int(stored)

            total += amount

            cursor.execute(
                """
                UPDATE fairies
                SET
                    stored_points = 0,
                    last_collection = %s
                WHERE user_id = %s
                AND fairy_index = %s
                """,
                (
                    now,
                    user.id,
                    fairy_index
                )
            )

        connection.commit()

    finally:
        cursor.close()
        connection.close()

    tinkies, points, last_tinky = get_user(
        user.id,
        user.first_name or "Fairy"
    )

    new_points = points + total

    save_user(
        user.id,
        user.first_name or "Fairy",
        tinkies,
        new_points,
        last_tinky
    )

    if total <= 0:
        await send_reply(
            update,
            "💚 هنوز امتیازی برای جمع کردن "
            "ذخیره نشده.\n\n"
            "⚡ چند لحظه صبر کن تا پری‌هات "
            "امتیاز تولید کنن!",
            main_menu()
        )
        return

    await send_reply(
        update,
        "💚✨ امتیازها جمع شدند! ✨💚\n\n"
        f"💚 +{format_number(total)} "
        "امتیاز تینکی\n\n"
        f"💰 موجودی: "
        f"{format_number(new_points)}",
        main_menu()
    )


async def upgrade_menu(update: Update):
    user = update.effective_user

    owned = get_owned_fairies(user.id)

    if not owned:
        await send_reply(
            update,
            "🧚‍♀️ هنوز پری‌ای نداری که ارتقاش بدی!",
            main_menu()
        )
        return

    buttons = []

    for (
        fairy_index,
        level,
        stored,
        last_collection
    ) in owned:

        buttons.append([
            InlineKeyboardButton(
                f"📈 "
                f"{FAIRIES[fairy_index]['name']} "
                f"— {level}/{MAX_LEVEL}",
                callback_data=f"upgrade_{fairy_index}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔙 منوی اصلی",
            callback_data="menu"
        )
    ])

    await send_reply(
        update,
        "🧚‍♀️✨ انتخاب پری برای ارتقا ✨🧚‍♀️\n\n"
        "پری موردنظرت رو انتخاب کن:",
        InlineKeyboardMarkup(buttons)
    )


async def upgrade_fairy(
    update: Update,
    fairy_index
):
    user = update.effective_user

    if (
        fairy_index < 0
        or fairy_index >= len(FAIRIES)
    ):
        await send_reply(
            update,
            "❌ پری نامعتبر است."
        )
        return

    fairy_data = get_fairy(
        user.id,
        fairy_index
    )

    if fairy_data is None:
        await send_reply(
            update,
            "❌ این پری رو نداری."
        )
        return

    level, stored, last_collection = fairy_data

    fairy = FAIRIES[fairy_index]

    if level >= MAX_LEVEL:
        await send_reply(
            update,
            "🎉✨ MAX LEVEL! ✨🎉\n\n"
            f"🧚‍♀️ {fairy['name']}\n"
            f"🌟 سطح: {MAX_LEVEL}/{MAX_LEVEL}"
        )
        return

    _, points, _ = get_user(
        user.id,
        user.first_name or "Fairy"
    )

    upgrade_cost = get_upgrade_cost(
        fairy_index,
        level
    )

    production = get_production(
        fairy_index,
        level
    )

    next_production = get_production(
        fairy_index,
        level + 1
    )

    capacity = get_capacity(
        fairy_index,
        level
    )

    next_capacity = get_capacity(
        fairy_index,
        level + 1
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "⬆️ ارتقا",
                callback_data=f"confirm_upgrade_{fairy_index}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 بازگشت",
                callback_data="upgrade_menu"
            )
        ]
    ]

    await send_reply(
        update,
        "🧚‍♀️✨ ارتقای پری ✨🧚‍♀️\n\n"
        f"🔧 {fairy['name']}\n\n"
        f"🌟 سطح فعلی: {level}/{MAX_LEVEL}\n\n"
        f"⚡ تولید فعلی:\n"
        f"{format_number(production)} امتیاز در ثانیه\n"
        f"⬆️ تولید بعدی:\n"
        f"{format_number(next_production)} امتیاز در ثانیه\n\n"
        f"📦 ظرفیت فعلی:\n"
        f"{format_number(capacity)} امتیاز\n"
        f"⬆️ ظرفیت بعدی:\n"
        f"{format_number(next_capacity)} امتیاز\n\n"
        f"💰 هزینه ارتقا:\n"
        f"{format_number(upgrade_cost)} امتیاز\n\n"
        f"💚 موجودی شما:\n"
        f"{format_number(points)} امتیاز\n\n"
        "✨ می‌خوای این پری رو ارتقا بدی؟",
        InlineKeyboardMarkup(keyboard)
    )


async def confirm_upgrade(
    update: Update,
    fairy_index
):
    user = update.effective_user

    if (
        fairy_index < 0
        or fairy_index >= len(FAIRIES)
    ):
        await send_reply(
            update,
            "❌ پری نامعتبر است."
        )
        return

    fairy_data = get_fairy(
        user.id,
        fairy_index
    )

    if fairy_data is None:
        await send_reply(
            update,
            "❌ این پری رو نداری."
        )
        return

    level, stored, last_collection = fairy_data

    if level >= MAX_LEVEL:
        await send_reply(
            update,
            "🎉✨ این پری به MAX LEVEL رسیده! ✨🎉"
        )
        return

    fairy = FAIRIES[fairy_index]

    tinkies, points, last_tinky = get_user(
        user.id,
        user.first_name or "Fairy"
    )

    upgrade_cost = get_upgrade_cost(
        fairy_index,
        level
    )

    if points < upgrade_cost:
        await send_reply(
            update,
            "❌ امتیاز کافی نداری!\n\n"
            f"💰 هزینه ارتقا: "
            f"{format_number(upgrade_cost)}\n"
            f"💚 موجودی شما: "
            f"{format_number(points)}"
        )
        return

    update_fairy_storage(
        user.id,
        fairy_index
    )

    fairy_data = get_fairy(
        user.id,
        fairy_index
    )

    level, stored, last_collection = fairy_data

    new_level = level + 1
    new_points = points - upgrade_cost

    connection = db()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            UPDATE fairies
            SET level = %s
            WHERE user_id = %s
            AND fairy_index = %s
            """,
            (
                new_level,
                user.id,
                fairy_index
            )
        )

        connection.commit()

    finally:
        cursor.close()
        connection.close()

    save_user(
        user.id,
        user.first_name or "Fairy",
        tinkies,
        new_points,
        last_tinky
    )

    production = get_production(
        fairy_index,
        new_level
    )

    capacity = get_capacity(
        fairy_index,
        new_level
    )

    message = (
        "🧚‍♀️✨ ارتقا با موفقیت انجام شد! ✨🧚‍♀️\n\n"
        f"🔧 {fairy['name']}\n\n"
        f"🌟 سطح جدید: {new_level}/{MAX_LEVEL}\n\n"
        f"⚡ تولید: "
        f"{format_number(production)} امتیاز در ثانیه\n"
        f"📦 ظرفیت: "
        f"{format_number(capacity)} امتیاز\n\n"
        f"💚 هزینه پرداخت‌شده:\n"
        f"{format_number(upgrade_cost)} امتیاز\n\n"
        f"💰 موجودی شما:\n"
        f"{format_number(new_points)} امتیاز\n\n"
        "🌸 پری شما قوی‌تر شد!"
    )

    keyboard = []

    if new_level == MAX_LEVEL:
        next_index = fairy_index + 1

        message += "\n\n🎉✨ MAX LEVEL! ✨🎉"

        if next_index < len(FAIRIES):
            message += "\n\n🔓 پری بعدی برای خرید آزاد شد!"

            keyboard.append([
                InlineKeyboardButton(
                    f"🛒 خرید {FAIRIES[next_index]['name']}",
                    callback_data=f"buy_{next_index}"
                )
            ])

    keyboard.append([
        InlineKeyboardButton(
            "📈 ارتقای بیشتر",
            callback_data=f"upgrade_{fairy_index}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 منوی اصلی",
            callback_data="menu"
        )
    ])

    await send_reply(
        update,
        message,
        InlineKeyboardMarkup(keyboard)
    )


async def buy_fairy(
    update: Update,
    fairy_index
):
    user = update.effective_user

    if (
        fairy_index < 0
        or fairy_index >= len(FAIRIES)
    ):
        await send_reply(
            update,
            "❌ پری نامعتبر است."
        )
        return

    tinkies, points, last_tinky = get_user(
        user.id,
        user.first_name or "Fairy"
    )

    owned = get_owned_fairies(user.id)

    next_index = len(owned)

    if fairy_index != next_index:
        await send_reply(
            update,
            "🔒 این پری هنوز قابل خرید نیست."
        )
        return

    if next_index > 0:
        previous = owned[-1]

        if previous[1] < MAX_LEVEL:
            await send_reply(
                update,
                "🔒 پری بعدی هنوز قفل است!\n\n"
                f"🧚‍♀️ "
                f"{FAIRIES[previous[0]]['name']}\n"
                f"🌟 سطح: {previous[1]}/{MAX_LEVEL}"
            )
            return

    fairy = FAIRIES[next_index]

    if points < fairy["price"]:
        await send_reply(
            update,
            "❌ امتیاز کافی نداری!\n\n"
            f"💰 قیمت: "
            f"{format_number(fairy['price'])}\n"
            f"💚 موجودی: "
            f"{format_number(points)}"
        )
        return

    add_fairy(
        user.id,
        next_index
    )

    new_points = points - fairy["price"]

    save_user(
        user.id,
        user.first_name or "Fairy",
        tinkies,
        new_points,
        last_tinky
    )

    await send_reply(
        update,
        "🧚‍♀️✨ پری جدید خریداری شد! ✨🧚‍♀️\n\n"
        f"🌸 {fairy['name']}\n"
        f"🌿 استعداد: {fairy['talent']}\n\n"
        f"🌟 سطح: 1/{MAX_LEVEL}\n"
        f"⚡ تولید: "
        f"{format_number(fairy['production'])} در ثانیه\n"
        f"📦 ظرفیت: "
        f"{format_number(fairy['capacity'])}\n\n"
        f"💚 هزینه پرداخت‌شده:\n"
        f"{format_number(fairy['price'])} امتیاز\n\n"
        f"💰 موجودی شما:\n"
        f"{format_number(new_points)} امتیاز",
        main_menu()
    )


async def handle_tinky(update: Update):
    user = update.effective_user

    tinkies, old_points, last_tinky = get_user(
        user.id,
        user.first_name or "Fairy"
    )

    now = time.time()

    remaining = COOLDOWN - (
        now - last_tinky
    )

    if remaining > 0:
        minutes = int(
            remaining // 60
        )

        seconds = int(
            remaining % 60
        )

        await send_reply(
            update,
            "⏳ هنوز نمی‌تونی تینکی بگی!\n\n"
            "🧚‍♀️ تینکی بعدی:\n"
            f"{minutes} دقیقه و "
            f"{seconds} ثانیه دیگه"
        )
        return

    old_level = get_level(tinkies)

    new_tinkies = tinkies + 1

    new_level = get_level(new_tinkies)

    earned_points = get_tinky_reward(new_level)

    bonus = 0

    if new_level > old_level:
        bonus = new_level * 100

    new_points = (
        old_points
        + earned_points
        + bonus
    )

    save_user(
        user.id,
        user.first_name or "Fairy",
        new_tinkies,
        new_points,
        now
    )

    if new_level > old_level:
        message = (
            "🧚‍♀️✨ TINK TINK! ✨🧚‍♀️\n\n"
            f"💚 +{format_number(earned_points)} "
            "امتیاز تینکی\n"
            f"🎁 +{format_number(bonus)} "
            "جایزه ارتقای سطح\n\n"
            "🌟 LEVEL UP!\n"
            f"✨ سطح جدید: {new_level}\n\n"
            f"💰 موجودی: "
            f"{format_number(new_points)} امتیاز\n\n"
            "⏳ تینکی بعدی: ۴ دقیقه دیگه"
        )

    else:
        message = (
            "🧚‍♀️✨ TINK TINK! ✨🧚‍♀️\n\n"
            f"💚 +{format_number(earned_points)} "
            "امتیاز تینکی\n"
            f"🌟 سطح فعلی: {new_level}\n\n"
            f"💰 موجودی: "
            f"{format_number(new_points)} امتیاز\n\n"
            "⏳ تینکی بعدی: ۴ دقیقه دیگه"
        )

    await send_reply(
        update,
        message,
        main_menu()
    )


async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    try:
        await query.answer()

        user = query.from_user
        data = query.data

        logger.info(
            "Callback '%s' from user %s",
            data,
            user.id
        )

        if data == "menu":
            await query.message.reply_text(
                "🧚‍♀️✨ منوی اصلی ✨🧚‍♀️",
                reply_markup=main_menu()
            )
            return

        if data == "profile":
            await profile(update)
            return

        if data == "fairies":
            await fairies(update)
            return

        if data == "my_fairies":
            await my_fairies(update)
            return

        if data == "collect":
            await collect(update)
            return

        if data == "upgrade_menu":
            await upgrade_menu(update)
            return

        if data.startswith("buy_"):
            try:
                fairy_index = int(
                    data.split("_")[1]
                )
            except (
                ValueError,
                IndexError
            ):
                await query.message.reply_text(
                    "❌ خطا در انتخاب پری."
                )
                return

            await buy_fairy(
                update,
                fairy_index
            )
            return

        if data.startswith("confirm_upgrade_"):
            try:
                fairy_index = int(
                    data.split("_")[2]
                )
            except (
                ValueError,
                IndexError
            ):
                await query.message.reply_text(
                    "❌ خطا در انتخاب پری."
                )
                return

            await confirm_upgrade(
                update,
                fairy_index
            )
            return

        if data.startswith("upgrade_"):
            try:
                fairy_index = int(
                    data.split("_")[1]
                )
            except (
                ValueError,
                IndexError
            ):
                await query.message.reply_text(
                    "❌ خطا در انتخاب پری."
                )
                return

            await upgrade_fairy(
                update,
                fairy_index
            )
            return

    except Exception:
        logger.exception(
            "Error while processing callback."
        )

        try:
            await query.message.reply_text(
                "❌ یک خطای موقت رخ داد. "
                "لطفاً دوباره امتحان کن."
            )
        except Exception:
            pass


async def message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if (
        not update.message
        or not update.message.text
    ):
        return

    try:
        text = (
            update.message.text
            .casefold()
            .strip()
        )

        logger.info(
            "Message from user %s: %s",
            update.effective_user.id,
            text
        )

        if "تینک" in text:
            await handle_tinky(update)
            return

        if text in [
            "پروفایل",
            "تینکیم"
        ]:
            await profile(update)
            return

        if text in [
            "پری",
            "پری ها",
            "پری‌ها"
        ]:
            await fairies(update)
            return

        if text in [
            "پری های من",
            "پری‌های من"
        ]:
            await my_fairies(update)
            return

        if text in [
            "جمع",
            "جمع کردن"
        ]:
            await collect(update)
            return

        if text in [
            "ارتقا",
            "آپگرید",
            "اپگرید"
        ]:
            await upgrade_menu(update)
            return

    except Exception:
        logger.exception(
            "Error while processing message."
        )

        try:
            await update.message.reply_text(
                "❌ یک خطای موقت رخ داد. "
                "لطفاً دوباره امتحان کن."
            )
        except Exception:
            pass


async def telegram_error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):
    error = context.error

    logger.error(
        "Telegram handler error: %r",
        error,
        exc_info=(
            type(error),
            error,
            error.__traceback__
        ) if error else None
    )


async def post_init(application: Application):
    logger.info(
        "Initializing Telegram connection..."
    )

    try:
        await application.bot.delete_webhook(
            drop_pending_updates=False
        )

        logger.info(
            "Webhook cleared successfully."
        )

    except Exception:
        logger.exception(
            "Could not clear webhook."
        )

    try:
        me = await application.bot.get_me()

        logger.info(
            "Connected to Telegram as @%s (id=%s)",
            me.username,
            me.id
        )

    except Exception:
        logger.exception(
            "Telegram connection test failed."
        )


server = Flask(__name__)


@server.route("/")
def home():
    return "Tinker Bell Bot is running!"


@server.route("/health")
def health():
    return "OK"


def run_server():
    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    logger.info(
        "Starting Render web server on port %s",
        port
    )

    server.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )


def create_application():
    application = (
        Application
        .builder()
        .token(TOKEN)
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
        CallbackQueryHandler(
            callback_handler
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            message_handler
        )
    )

    application.add_error_handler(
        telegram_error_handler
    )

    return application


def main():
    logger.info(
        "================================"
    )

    logger.info(
        "Starting Tinker Bell Bot..."
    )

    logger.info(
        "================================"
    )

    setup_database()

    server_thread = Thread(
        target=run_server,
        daemon=True
    )

    server_thread.start()

    logger.info(
        "Render web server started."
    )

    application = create_application()

    logger.info(
        "Telegram application created."
    )

    logger.info(
        "Starting polling..."
    )

    while True:
        try:
            application.run_polling(
                poll_interval=1,
                timeout=30,
                bootstrap_retries=-1,
                drop_pending_updates=False
            )

            logger.warning(
                "Polling stopped unexpectedly."
            )

        except KeyboardInterrupt:
            logger.info(
                "Bot stopped by KeyboardInterrupt."
            )
            break

        except SystemExit:
            logger.info(
                "Bot stopped by SystemExit."
            )
            break

        except Exception:
            logger.exception(
                "MAIN POLLING LOOP CRASHED."
            )

        logger.info(
            "Restarting Telegram polling in 10 seconds..."
        )

        time.sleep(10)


if __name__ == "__main__":
    main()
