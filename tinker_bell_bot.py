import sqlite3
import random
import os
import time
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

from flask import Flask
from threading import Thread


TOKEN = os.environ["BOT_TOKEN"]
DB = "tinker_bell.db"

COOLDOWN = 4 * 60

POINT_RANGES = {
    1: (5, 15),
    2: (10, 25),
    3: (15, 35),
    4: (20, 45),
    5: (25, 55),
    6: (30, 65),
    7: (35, 75),
    8: (40, 85),
    9: (50, 100),
    10: (60, 120)
}

LEVEL_BONUSES = {
    2: 100,
    3: 200,
    4: 300,
    5: 500,
    6: 700,
    7: 1000,
    8: 1500,
    9: 2000,
    10: 3000
}

FAIRIES = [
    {
        "name": "Tinker Bell",
        "talent": "Tinker",
        "price": 500,
        "production": 5,
        "capacity": 500
    },
    {
        "name": "Silvermist",
        "talent": "Water",
        "price": 5000,
        "production": 20,
        "capacity": 2500
    },
    {
        "name": "Rosetta",
        "talent": "Garden",
        "price": 25000,
        "production": 70,
        "capacity": 10000
    },
    {
        "name": "Fawn",
        "talent": "Animal",
        "price": 100000,
        "production": 250,
        "capacity": 40000
    },
    {
        "name": "Iridessa",
        "talent": "Light",
        "price": 400000,
        "production": 800,
        "capacity": 120000
    },
    {
        "name": "Vidia",
        "talent": "Fast Flying",
        "price": 1500000,
        "production": 2500,
        "capacity": 350000
    },
    {
        "name": "Periwinkle",
        "talent": "Frost",
        "price": 5000000,
        "production": 7000,
        "capacity": 900000
    },
    {
        "name": "Zarina",
        "talent": "Pixie Dust",
        "price": 15000000,
        "production": 18000,
        "capacity": 2000000
    }
]


def setup_database():
    connection = sqlite3.connect(DB)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            tinkies INTEGER DEFAULT 0,
            points INTEGER DEFAULT 0,
            last_tinky REAL DEFAULT 0
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS fairies (
            user_id INTEGER,
            fairy_index INTEGER,
            level INTEGER DEFAULT 1,
            stored_points REAL DEFAULT 0,
            last_collection REAL DEFAULT 0,
            PRIMARY KEY (user_id, fairy_index)
        )
    """)

    try:
        connection.execute(
            "ALTER TABLE users ADD COLUMN last_tinky REAL DEFAULT 0"
        )
    except sqlite3.OperationalError:
        pass

    connection.commit()
    connection.close()


def get_level(tinkies):
    return min((tinkies // 25) + 1, 25)


def get_user(user_id, name):
    connection = sqlite3.connect(DB)

    user = connection.execute(
        """
        SELECT tinkies, points, last_tinky
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()

    if user is None:
        connection.execute(
            """
            INSERT INTO users
            (user_id, name, tinkies, points, last_tinky)
            VALUES (?, ?, 0, 0, 0)
            """,
            (user_id, name)
        )

        connection.commit()
        user = (0, 0, 0)

    connection.close()

    return user


def save_user(
    user_id,
    name,
    tinkies,
    points,
    last_tinky
):
    connection = sqlite3.connect(DB)

    connection.execute(
        """
        INSERT INTO users
        (user_id, name, tinkies, points, last_tinky)
        VALUES (?, ?, ?, ?, ?)

        ON CONFLICT(user_id)
        DO UPDATE SET
            name = excluded.name,
            tinkies = excluded.tinkies,
            points = excluded.points,
            last_tinky = excluded.last_tinky
        """,
        (
            user_id,
            name,
            tinkies,
            points,
            last_tinky
        )
    )

    connection.commit()
    connection.close()


def get_fairy(user_id, fairy_index):
    connection = sqlite3.connect(DB)

    fairy = connection.execute(
        """
        SELECT level, stored_points, last_collection
        FROM fairies
        WHERE user_id = ? AND fairy_index = ?
        """,
        (user_id, fairy_index)
    ).fetchone()

    connection.close()

    return fairy


def add_fairy(user_id, fairy_index):
    connection = sqlite3.connect(DB)

    connection.execute(
        """
        INSERT INTO fairies
        (user_id, fairy_index, level, stored_points, last_collection)
        VALUES (?, ?, 1, 0, ?)
        """,
        (user_id, fairy_index, time.time())
    )

    connection.commit()
    connection.close()


def get_owned_fairies(user_id):
    connection = sqlite3.connect(DB)

    fairies = connection.execute(
        """
        SELECT fairy_index, level, stored_points, last_collection
        FROM fairies
        WHERE user_id = ?
        ORDER BY fairy_index
        """,
        (user_id,)
    ).fetchall()

    connection.close()

    return fairies


def get_production(fairy_index, level):
    base = FAIRIES[fairy_index]["production"]

    return int(base * (1 + ((level - 1) * 0.35)))


def get_capacity(fairy_index, level):
    base = FAIRIES[fairy_index]["capacity"]

    return int(base * (1 + ((level - 1) * 0.30)))


def update_fairy_storage(user_id, fairy_index):
    fairy = get_fairy(user_id, fairy_index)

    if fairy is None:
        return

    level, stored, last_collection = fairy

    now = time.time()

    elapsed = max(0, now - last_collection)

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

    connection = sqlite3.connect(DB)

    connection.execute(
        """
        UPDATE fairies
        SET stored_points = ?,
            last_collection = ?
        WHERE user_id = ?
        AND fairy_index = ?
        """,
        (
            stored,
            now,
            user_id,
            fairy_index
        )
    )

    connection.commit()
    connection.close()


def update_all_fairies(user_id):
    fairies = get_owned_fairies(user_id)

    for fairy in fairies:
        fairy_index = fairy[0]
        update_fairy_storage(
            user_id,
            fairy_index
        )


def format_number(number):
    return f"{int(number):,}"


async def send_profile(update: Update):
    user = update.effective_user

    tinkies, points, last_tinky = get_user(
        user.id,
        user.first_name or "Fairy"
    )

    level = get_level(tinkies)

    if level >= 25:
        remaining = 0
    else:
        remaining = 25 - (tinkies % 25)

    low, high = POINT_RANGES.get(
        level,
        POINT_RANGES[10]
    )

    await update.message.reply_text(
        "🧚‍♀️✨ پروفایل تینکی ✨🧚‍♀️\n\n"
        f"🌟 سطح: {level}\n"
        f"🔔 تینکی‌ها: {tinkies}\n"
        f"💚 امتیاز تینکی: {format_number(points)}\n\n"
        f"🎲 امتیاز هر تینکی: {low}–{high}\n"
        f"✨ تا سطح بعدی: {remaining} تینکی"
    )


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
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
        "📋 امکانات:\n\n"
        "👤 پروفایل\n"
        "🧚‍♀️ فروشگاه پری‌ها\n"
        "💚 جمع کردن امتیازها\n"
        "🧚‍♀️ پری‌های من\n\n"
        "🌸 آماده‌ای وارد سرزمین پری‌ها بشی؟\n\n"
        "✨ بگو «تینک» تا شروع کنیم! ✨"
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
        await update.message.reply_text(
            "🧚‍♀️✨ فروشگاه پری‌ها ✨🧚‍♀️\n\n"
            "🎉 همه پری‌ها رو آزاد کردی!\n\n"
            "👑 تو به بالاترین مرحله فروشگاه رسیدی!"
        )
        return

    await update.message.reply_text(
        "🧚‍♀️✨ فروشگاه پری‌ها ✨🧚‍♀️\n\n"
        "پری‌ها به ترتیب باز می‌شن! 🌸\n\n"
        "🔓 هر پری جدید فقط وقتی قابل خرید می‌شه "
        "که پری قبلی به سطح ۲۵ رسیده باشه.\n\n"
        "💚 با امتیازهای تینکی می‌تونی پری‌هات رو "
        "بخری و ارتقا بدی.\n\n"
        "⚡ هر پری در هر ثانیه امتیاز تولید می‌کنه.\n"
        "📦 هر پری ظرفیت مشخصی برای ذخیره امتیاز داره.\n\n"
        "🌟 پری‌هات رو ارتقا بده، قوی‌ترشون کن "
        "و پری بعدی رو آزاد کن! ✨\n\n"
        "━━━━━━━━━━━━━━\n\n"
        f"🧚‍♀️ {FAIRIES[next_index]['name']}\n"
        f"🌿 استعداد: {FAIRIES[next_index]['talent']}\n\n"
        f"💰 قیمت: {format_number(FAIRIES[next_index]['price'])} امتیاز\n"
        f"⚡ تولید اولیه: {FAIRIES[next_index]['production']} در ثانیه\n"
        f"📦 ظرفیت اولیه: {format_number(FAIRIES[next_index]['capacity'])}\n\n"
        f"💚 موجودی شما: {format_number(points)} امتیاز"
    )


async def my_fairies(update: Update):
    user = update.effective_user

    owned = get_owned_fairies(user.id)

    if not owned:
        await update.message.reply_text(
            "🧚‍♀️✨ پری‌های من ✨🧚‍♀️\n\n"
            "هنوز پری‌ای نداری! 🌸\n\n"
            "💚 از فروشگاه اولین پریت رو بخر."
        )
        return

    update_all_fairies(user.id)

    owned = get_owned_fairies(user.id)

    message = "🧚‍♀️✨ پری‌های من ✨🧚‍♀️\n\n"

    for fairy_index, level, stored, last_collection in owned:
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
            f"🌟 سطح: {level}/25\n"
            f"⚡ تولید: {format_number(production)} در ثانیه\n"
            f"📦 ظرفیت: {format_number(capacity)}\n"
            f"💚 ذخیره: {format_number(stored)}\n\n"
        )

    await update.message.reply_text(message)


async def collect(update: Update):
    user = update.effective_user

    owned = get_owned_fairies(user.id)

    if not owned:
        await update.message.reply_text(
            "💚 هنوز امتیازی از پری‌ها برای جمع کردن نداری."
        )
        return

    update_all_fairies(user.id)

    owned = get_owned_fairies(user.id)

    total = 0

    connection = sqlite3.connect(DB)

    for fairy_index, level, stored, last_collection in owned:
        amount = int(stored)

        total += amount

        connection.execute(
            """
            UPDATE fairies
            SET stored_points = stored_points - ?
            WHERE user_id = ?
            AND fairy_index = ?
            """,
            (
                amount,
                user.id,
                fairy_index
            )
        )

    connection.commit()
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

    await update.message.reply_text(
        "💚✨ امتیازها جمع شدند! ✨💚\n\n"
        f"💚 +{format_number(total)} امتیاز تینکی\n"
        f"💰 موجودی: {format_number(new_points)}"
    )


async def upgrade(update: Update):
    user = update.effective_user

    owned = get_owned_fairies(user.id)

    if not owned:
        await update.message.reply_text(
            "🧚‍♀️ هنوز پری‌ای نداری که ارتقاش بدی!"
        )
        return

    update_all_fairies(user.id)

    owned = get_owned_fairies(user.id)

    message = "🧚‍♀️✨ ارتقای پری ✨🧚‍♀️\n\n"

    for fairy_index, level, stored, last_collection in owned:
        fairy = FAIRIES[fairy_index]

        if level >= 25:
            message += (
                f"👑 {fairy['name']}\n"
                "🌟 سطح: 25/25\n"
                "✨ MAX LEVEL!\n\n"
            )
            continue

        upgrade_cost = int(
            fairy["price"] * (level ** 1.7)
        )

        production = get_production(
            fairy_index,
            level
        )

        capacity = get_capacity(
            fairy_index,
            level
        )

        message += (
            f"🔧 {fairy['name']}\n\n"
            f"🌟 سطح فعلی: {level}/25\n\n"
            f"⚡ تولید فعلی:\n"
            f"{format_number(production)} امتیاز در ثانیه\n\n"
            f"📦 ظرفیت فعلی:\n"
            f"{format_number(capacity)} امتیاز\n\n"
            f"💰 هزینه ارتقا:\n"
            f"{format_number(upgrade_cost)} امتیاز\n\n"
            f"💚 موجودی شما:\n"
            f"{format_number(get_user(user.id, user.first_name or 'Fairy')[1])} امتیاز\n\n"
        )

    await update.message.reply_text(message)


async def upgrade_fairy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not context.args:
        await upgrade(update)
        return

    try:
        fairy_index = int(context.args[0]) - 1
    except ValueError:
        await update.message.reply_text(
            "❌ شماره پری درست نیست."
        )
        return

    owned = get_owned_fairies(user.id)

    owned_indexes = [
        fairy[0]
        for fairy in owned
    ]

    if fairy_index not in owned_indexes:
        await update.message.reply_text(
            "❌ این پری رو نداری."
        )
        return

    update_all_fairies(user.id)

    fairy_data = get_fairy(
        user.id,
        fairy_index
    )

    level, stored, last_collection = fairy_data

    if level >= 25:
        await update.message.reply_text(
            "🎉✨ این پری به MAX LEVEL رسیده! ✨🎉"
        )
        return

    fairy = FAIRIES[fairy_index]

    upgrade_cost = int(
        fairy["price"] * (level ** 1.7)
    )

    tinkies, points, last_tinky = get_user(
        user.id,
        user.first_name or "Fairy"
    )

    if points < upgrade_cost:
        await update.message.reply_text(
            "❌ امتیاز کافی نداری!\n\n"
            f"💰 هزینه ارتقا: {format_number(upgrade_cost)}\n"
            f"💚 موجودی شما: {format_number(points)}"
        )
        return

    new_level = level + 1

    connection = sqlite3.connect(DB)

    connection.execute(
        """
        UPDATE fairies
        SET level = ?
        WHERE user_id = ?
        AND fairy_index = ?
        """,
        (
            new_level,
            user.id,
            fairy_index
        )
    )

    connection.commit()
    connection.close()

    new_points = points - upgrade_cost

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
        f"🌟 سطح جدید: {new_level}/25\n\n"
        f"⚡ تولید: {format_number(production)} امتیاز در ثانیه\n"
        f"📦 ظرفیت: {format_number(capacity)} امتیاز\n\n"
        f"💚 هزینه پرداخت‌شده:\n"
        f"{format_number(upgrade_cost)} امتیاز\n\n"
        f"💰 موجودی شما:\n"
        f"{format_number(new_points)} امتیاز\n\n"
        "🌸 پری شما قوی‌تر شد!"
    )

    if new_level == 25:
        next_fairy = fairy_index + 1

        message += (
            "\n\n"
            "🎉✨ MAX LEVEL! ✨🎉\n\n"
        )

        if next_fairy < len(FAIRIES):
            message += (
                "🔓 پری بعدی برای خرید آزاد شد!\n"
                f"🧚‍♀️ {FAIRIES[next_fairy]['name']}"
            )
        else:
            message += (
                "👑 همه پری‌ها رو آزاد کردی!"
            )

    await update.message.reply_text(message)


async def buy_fairy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    tinkies, points, last_tinky = get_user(
        user.id,
        user.first_name or "Fairy"
    )

    owned = get_owned_fairies(user.id)

    next_index = len(owned)

    if next_index >= len(FAIRIES):
        await update.message.reply_text(
            "🎉 همه پری‌ها رو داری!"
        )
        return

    if owned:
        last_index = owned[-1][0]
        last_level = owned[-1][1]

        if last_level < 25:
            await update.message.reply_text(
                "🔒 پری بعدی هنوز قفل است!\n\n"
                f"🧚‍♀️ {FAIRIES[last_index]['name']}\n"
                f"🌟 سطح فعلی: {last_level}/25\n\n"
                "✨ اول این پری رو به سطح ۲۵ برسون."
            )
            return

    fairy = FAIRIES[next_index]

    if points < fairy["price"]:
        await update.message.reply_text(
            "❌ امتیاز کافی نداری!\n\n"
            f"🧚‍♀️ {fairy['name']}\n"
            f"💰 قیمت: {format_number(fairy['price'])}\n"
            f"💚 موجودی: {format_number(points)}"
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

    await update.message.reply_text(
        "🧚‍♀️✨ پری جدید خریداری شد! ✨🧚‍♀️\n\n"
        f"🌸 {fairy['name']}\n"
        f"🌿 استعداد: {fairy['talent']}\n\n"
        f"🌟 سطح: 1/25\n"
        f"⚡ تولید: {format_number(fairy['production'])} در ثانیه\n"
        f"📦 ظرفیت: {format_number(fairy['capacity'])}\n\n"
        f"💚 هزینه پرداخت‌شده:\n"
        f"{format_number(fairy['price'])} امتیاز\n\n"
        f"💰 موجودی شما:\n"
        f"{format_number(new_points)} امتیاز"
    )


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not update.message:
        return

    if not update.message.text:
        return

    text = update.message.text.casefold().strip()

    if text in ["پروفایل", "تینکیم"]:
        await send_profile(update)
        return

    if text in ["پری ها", "پری‌ها", "پری", "fairies"]:
        await fairies(update)
        return

    if text in ["پری های من", "پری‌های من", "myfairies"]:
        await my_fairies(update)
        return

    if text in ["جمع کردن", "جمع", "collect"]:
        await collect(update)
        return

    if "تینک" not in text:
        return

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
        minutes = int(remaining // 60)
        seconds = int(remaining % 60)

        await update.message.reply_text(
            "⏳ هنوز نمی‌تونی تینکی بگی!\n\n"
            "🧚‍♀️ تینکی بعدی:\n"
            f"{minutes} دقیقه و {seconds} ثانیه دیگه"
        )

        return

    old_level = get_level(tinkies)

    new_tinkies = tinkies + 1

    new_level = get_level(new_tinkies)

    low, high = POINT_RANGES.get(
        old_level,
        POINT_RANGES[10]
    )

    earned_points = random.randint(
        low,
        high
    )

    new_points = old_points + earned_points

    bonus = 0

    if new_level > old_level:
        for level in range(
            old_level + 1,
            new_level + 1
        ):
            bonus += LEVEL_BONUSES.get(
                level,
                3000
            )

        new_points += bonus

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
            f"💚 +{format_number(earned_points)} امتیاز تینکی\n"
            f"🎁 +{format_number(bonus)} جایزه ارتقای سطح\n\n"
            "🌟 LEVEL UP!\n"
            f"✨ سطح جدید: {new_level}\n\n"
            f"💰 موجودی: {format_number(new_points)} امتیاز\n\n"
            "⏳ تینکی بعدی: ۴ دقیقه دیگه"
        )

    else:
        message = (
            "🧚‍♀️✨ TINK TINK! ✨🧚‍♀️\n\n"
            f"💚 +{format_number(earned_points)} امتیاز تینکی\n\n"
            f"💰 موجودی: {format_number(new_points)} امتیاز\n\n"
            "⏳ تینکی بعدی: ۴ دقیقه دیگه"
        )

    await update.message.reply_text(message)


app_server = Flask(__name__)


@app_server.route("/")
def home():
    return "Tinker Bell Bot is running!"


def run_server():
    port = int(os.environ.get("PORT", 10000))
    app_server.run(
        host="0.0.0.0",
        port=port
    )


def main():
    setup_database()

    Thread(
        target=run_server,
        daemon=True
    ).start()

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "profile",
            send_profile
        )
    )

    app.add_handler(
        CommandHandler(
            "fairies",
            fairies
        )
    )

    app.add_handler(
        CommandHandler(
            "myfairies",
            my_fairies
        )
    )

    app.add_handler(
        CommandHandler(
            "collect",
            collect
        )
    )

    app.add_handler(
        CommandHandler(
            "buy",
            buy_fairy
        )
    )

    app.add_handler(
        CommandHandler(
            "upgrade",
            upgrade_fairy
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print(
        "🧚‍♀️ Tinker Bell Bot is running!"
    )

    app.run_polling()


if __name__ == "__main__":
    main()
