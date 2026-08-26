import os
import time
import random
import asyncio
import threading

import psycopg2
from psycopg2.extras import RealDictCursor

from flask import Flask, request

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)


TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]

COOLDOWN = 4 * 60


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


def db():
    return psycopg2.connect(
        DATABASE_URL,
        connect_timeout=10
    )


def setup_database():
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
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            fairy_index INTEGER,
            level INTEGER DEFAULT 1,
            stored_points DOUBLE PRECISION DEFAULT 0,
            last_collection DOUBLE PRECISION DEFAULT 0,
            PRIMARY KEY (user_id, fairy_index)
        );
    """)

    connection.commit()
    cursor.close()
    connection.close()


def format_number(number):
    return f"{int(number):,}"


def get_user(user_id, name):
    connection = db()
    cursor = connection.cursor(cursor_factory=RealDictCursor)

    cursor.execute(
        """
        INSERT INTO users
        (user_id, name, tinkies, points, last_tinky)
        VALUES (%s, %s, 0, 0, 0)
        ON CONFLICT (user_id)
        DO UPDATE SET name = EXCLUDED.name
        RETURNING tinkies, points, last_tinky
        """,
        (user_id, name)
    )

    user = cursor.fetchone()

    connection.commit()
    cursor.close()
    connection.close()

    return (
        user["tinkies"],
        user["points"],
        user["last_tinky"]
    )


def save_user(user_id, name, tinkies, points, last_tinky):
    connection = db()
    cursor = connection.cursor()

    cursor.execute(
        """
        UPDATE users
        SET name = %s,
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
    cursor.close()
    connection.close()


def get_owned_fairies(user_id):
    connection = db()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT fairy_index, level, stored_points, last_collection
        FROM fairies
        WHERE user_id = %s
        ORDER BY fairy_index
        """,
        (user_id,)
    )

    fairies = cursor.fetchall()

    cursor.close()
    connection.close()

    return fairies


def get_fairy(user_id, fairy_index):
    connection = db()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT level, stored_points, last_collection
        FROM fairies
        WHERE user_id = %s
        AND fairy_index = %s
        """,
        (user_id, fairy_index)
    )

    fairy = cursor.fetchone()

    cursor.close()
    connection.close()

    return fairy


def add_fairy(user_id, fairy_index):
    connection = db()
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO fairies
        (user_id, fairy_index, level, stored_points, last_collection)
        VALUES (%s, %s, 1, 0, %s)
        """,
        (
            user_id,
            fairy_index,
            time.time()
        )
    )

    connection.commit()
    cursor.close()
    connection.close()


def get_production(fairy_index, level):
    base = FAIRIES[fairy_index]["production"]
    return int(base * (1 + (level - 1) * 0.35))


def get_capacity(fairy_index, level):
    base = FAIRIES[fairy_index]["capacity"]
    return int(base * (1 + (level - 1) * 0.30))


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

    connection = db()
    cursor = connection.cursor()

    cursor.execute(
        """
        UPDATE fairies
        SET stored_points = %s,
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
    return min((tinkies // 25) + 1, 25)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🧚‍♀️✨ تینکر بل ✨🧚‍♀️\n\n"
        "سلام پری کوچولو! 🌸\n"
        "به سرزمین پری‌ها خوش اومدی! 🧚‍♀️🌿\n\n"
        "🔔 با گفتن «تینک» می‌تونی تینکی و امتیاز تینکی بگیری.\n\n"
        "💚 امکانات:\n\n"
        "👤 پروفایل\n"
        "🧚‍♀️ فروشگاه پری‌ها\n"
        "🧚‍♀️ پری‌های من\n"
        "💚 جمع کردن امتیاز\n"
        "📈 ارتقای پری‌ها\n\n"
        "✨ هر پری امتیاز تولید می‌کنه و ظرفیت مشخصی داره.\n\n"
        "🌸 برای شروع بگو «تینک»!"
    )


async def profile(update: Update):
    user = update.effective_user

    tinkies, points, last_tinky = get_user(
        user.id,
        user.first_name or "Fairy"
    )

    level = get_level(tinkies)

    await update.message.reply_text(
        "🧚‍♀️✨ پروفایل تینکی ✨🧚‍♀️\n\n"
        f"🌟 سطح: {level}\n"
        f"🔔 تینکی‌ها: {tinkies}\n"
        f"💚 امتیاز تینکی: {format_number(points)}"
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
            "🎉 همه پری‌ها رو آزاد کردی!"
        )
        return

    fairy = FAIRIES[next_index]

    if next_index > 0 and owned[-1][1] < 25:
        await update.message.reply_text(
            "🔒 پری بعدی هنوز قفل است!\n\n"
            "🧚‍♀️ اول پری قبلی رو به سطح ۲۵ برسون."
        )
        return

    await update.message.reply_text(
        "🧚‍♀️✨ فروشگاه پری‌ها ✨🧚‍♀️\n\n"
        f"🧚‍♀️ {fairy['name']}\n"
        f"🌿 استعداد: {fairy['talent']}\n\n"
        f"💰 قیمت: {format_number(fairy['price'])} امتیاز\n"
        f"⚡ تولید اولیه: {format_number(fairy['production'])} در ثانیه\n"
        f"📦 ظرفیت اولیه: {format_number(fairy['capacity'])}\n\n"
        f"💚 موجودی شما: {format_number(points)} امتیاز\n\n"
        f"برای خرید این پری بنویس:\n"
        f"خرید {fairy['name']}"
    )


async def buy_fairy(update: Update):
    user = update.effective_user

    tinkies, points, last_tinky = get_user(
        user.id,
        user.first_name or "Fairy"
    )

    owned = get_owned_fairies(user.id)

    next_index = len(owned)

    if next_index >= len(FAIRIES):
        await update.message.reply_text(
            "🎉 همه پری‌ها رو خریدی!"
        )
        return

    if next_index > 0 and owned[-1][1] < 25:
        await update.message.reply_text(
            "🔒 پری بعدی هنوز قفل است!\n\n"
            "🧚‍♀️ پری قبلی باید به سطح ۲۵ برسه."
        )
        return

    fairy = FAIRIES[next_index]

    if points < fairy["price"]:
        await update.message.reply_text(
            "❌ امتیاز کافی نداری!\n\n"
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
        "🌟 سطح: 1/25\n"
        f"⚡ تولید: {format_number(fairy['production'])} در ثانیه\n"
        f"📦 ظرفیت: {format_number(fairy['capacity'])}\n\n"
        f"💚 موجودی جدید: {format_number(new_points)}"
    )


async def my_fairies(update: Update):
    user = update.effective_user

    owned = get_owned_fairies(user.id)

    if not owned:
        await update.message.reply_text(
            "🧚‍♀️ هنوز پری‌ای نداری!\n\n"
            "برای دیدن اولین پری بنویس «پری»."
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
            "💚 هنوز پری‌ای نداری."
        )
        return

    update_all_fairies(user.id)

    owned = get_owned_fairies(user.id)

    total = 0

    connection = db()
    cursor = connection.cursor()

    for fairy_index, level, stored, last_collection in owned:
        amount = int(stored)

        total += amount

        cursor.execute(
            """
            UPDATE fairies
            SET stored_points = 0
            WHERE user_id = %s
            AND fairy_index = %s
            """,
            (
                user.id,
                fairy_index
            )
        )

    connection.commit()
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

    await update.message.reply_text(
        "💚✨ امتیازها جمع شدند! ✨💚\n\n"
        f"💚 +{format_number(total)} امتیاز\n\n"
        f"💰 موجودی: {format_number(new_points)}"
    )


async def upgrade_menu(update: Update):
    user = update.effective_user

    owned = get_owned_fairies(user.id)

    if not owned:
        await update.message.reply_text(
            "🧚‍♀️ هنوز پری‌ای نداری که ارتقاش بدی."
        )
        return

    message = "🧚‍♀️✨ ارتقای پری ✨🧚‍♀️\n\n"

    for fairy_index, level, stored, last_collection in owned:
        fairy = FAIRIES[fairy_index]

        if level >= 25:
            message += (
                f"🧚‍♀️ {fairy['name']}\n"
                "🌟 سطح: 25/25 — MAX\n\n"
            )
            continue

        cost = int(
            fairy["price"] * (level ** 1.7)
        )

        message += (
            f"🧚‍♀️ {fairy['name']}\n"
            f"🌟 سطح: {level}/25\n"
            f"💰 هزینه ارتقا: {format_number(cost)}\n"
            f"✏️ برای ارتقا بنویس:\n"
            f"ارتقا {fairy['name']}\n\n"
        )

    await update.message.reply_text(message)


async def upgrade_fairy(update: Update, fairy_index):
    user = update.effective_user

    fairy_data = get_fairy(
        user.id,
        fairy_index
    )

    if fairy_data is None:
        await update.message.reply_text(
            "❌ این پری رو نداری."
        )
        return

    level, stored, last_collection = fairy_data
    fairy = FAIRIES[fairy_index]

    if level >= 25:
        await update.message.reply_text(
            "🎉✨ این پری به MAX LEVEL رسیده! ✨🎉\n\n"
            f"🧚‍♀️ {fairy['name']}\n"
            "🌟 سطح: 25/25"
        )
        return

    tinkies, points, last_tinky = get_user(
        user.id,
        user.first_name or "Fairy"
    )

    upgrade_cost = int(
        fairy["price"] * (level ** 1.7)
    )

    if points < upgrade_cost:
        await update.message.reply_text(
            "❌ امتیاز کافی نداری!\n\n"
            f"💰 هزینه: {format_number(upgrade_cost)}\n"
            f"💚 موجودی: {format_number(points)}"
        )
        return

    new_level = level + 1
    new_points = points - upgrade_cost

    connection = db()
    cursor = connection.cursor()

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
        f"🧚‍♀️ {fairy['name']}\n"
        f"🌟 سطح جدید: {new_level}/25\n\n"
        f"⚡ تولید: {format_number(production)} در ثانیه\n"
        f"📦 ظرفیت: {format_number(capacity)}\n\n"
        f"💰 هزینه: {format_number(upgrade_cost)}\n"
        f"💚 موجودی: {format_number(new_points)}"
    )

    if new_level == 25 and fairy_index + 1 < len(FAIRIES):
        message += (
            "\n\n🎉✨ MAX LEVEL! ✨🎉\n"
            f"🔓 {FAIRIES[fairy_index + 1]['name']} آزاد شد!"
        )

    await update.message.reply_text(message)


async def handle_tinky(update: Update):
    user = update.effective_user

    tinkies, old_points, last_tinky = get_user(
        user.id,
        user.first_name or "Fairy"
    )

    now = time.time()

    remaining = COOLDOWN - (now - last_tinky)

    if remaining > 0:
        minutes = int(remaining // 60)
        seconds = int(remaining % 60)

        await update.message.reply_text(
            "⏳ هنوز نمی‌تونی تینکی بگی!\n\n"
            f"🧚‍♀️ {minutes} دقیقه و {seconds} ثانیه دیگه"
        )
        return

    old_level = get_level(tinkies)

    new_tinkies = tinkies + 1
    new_level = get_level(new_tinkies)

    earned_points = random.randint(5, 15)

    bonus = 0

    if new_level > old_level:
        bonus = new_level * 100

    new_points = (
        old_points +
        earned_points +
        bonus
    )

    save_user(
        user.id,
        user.first_name or "Fairy",
        new_tinkies,
        new_points,
        now
    )

    if new_level > old_level:
        await update.message.reply_text(
            "🧚‍♀️✨ TINK TINK! ✨🧚‍♀️\n\n"
            f"💚 +{format_number(earned_points)} امتیاز\n"
            f"🎁 +{format_number(bonus)} جایزه سطح\n\n"
            "🌟 LEVEL UP!\n"
            f"✨ سطح جدید: {new_level}\n\n"
            f"💰 موجودی: {format_number(new_points)}\n\n"
            "⏳ تینکی بعدی: ۴ دقیقه دیگه"
        )
    else:
        await update.message.reply_text(
            "🧚‍♀️✨ TINK TINK! ✨🧚‍♀️\n\n"
            f"💚 +{format_number(earned_points)} امتیاز\n\n"
            f"💰 موجودی: {format_number(new_points)}\n\n"
            "⏳ تینکی بعدی: ۴ دقیقه دیگه"
        )


async def message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not update.message or not update.message.text:
        return

    text = update.message.text.casefold().strip()

    if text in ["تینک", "تینکی", "تینک تینک"] or "تینک" in text:
        await handle_tinky(update)
        return

    if text in ["پروفایل", "تینکیم"]:
        await profile(update)
        return

    if text in ["پری", "پری ها", "پری‌ها"]:
        await fairies(update)
        return

    if text in ["پری های من", "پری‌های من"]:
        await my_fairies(update)
        return

    if text in ["جمع", "جمع کردن"]:
        await collect(update)
        return

    if text in ["ارتقا", "آپگرید", "اپگرید"]:
        await upgrade_menu(update)
        return

    if text.startswith("خرید "):
        name = text[5:].strip()

        user = update.effective_user
        owned = get_owned_fairies(user.id)
        next_index = len(owned)

        if next_index < len(FAIRIES):
            fairy = FAIRIES[next_index]

            if name.casefold() == fairy["name"].casefold():
                await buy_fairy(update)
                return

    if text.startswith("ارتقا "):
        name = text[6:].strip()

        user = update.effective_user
        owned = get_owned_fairies(user.id)

        for fairy_index, level, stored, last_collection in owned:
            if FAIRIES[fairy_index]["name"].casefold() == name.casefold():
                await upgrade_fairy(
                    update,
                    fairy_index
                )
                return


server = Flask(__name__)


@server.route("/")
def home():
    return "Tinker Bell Bot is running!"


@server.route("/health")
def health():
    return "OK"


application = None
application_loop = None


@server.route("/telegram", methods=["POST"])
def telegram_webhook():
    global application_loop

    if application_loop is None:
        return "Bot is starting", 503

    try:
        data = request.get_json(force=True)
        update = Update.de_json(
            data,
            application.bot
        )

        future = asyncio.run_coroutine_threadsafe(
            application.update_queue.put(update),
            application_loop
        )

        future.result(timeout=10)

        return "OK", 200

    except Exception as error:
        print(
            f"Webhook error: {type(error).__name__}: {error}"
        )
        return "ERROR", 500


async def start_bot():
    global application_loop

    application_loop = asyncio.get_running_loop()

    await application.initialize()
    await application.start()

    webhook_url = os.environ.get("RENDER_EXTERNAL_URL")

    if not webhook_url:
        print(
            "ERROR: RENDER_EXTERNAL_URL is not available."
        )
        return

    webhook_url = webhook_url.rstrip("/") + "/telegram"

    await application.bot.delete_webhook(
        drop_pending_updates=False
    )

    await application.bot.set_webhook(
        url=webhook_url,
        drop_pending_updates=False,
        allowed_updates=Update.ALL_TYPES
    )

    print(
        "🧚‍♀️ Tinker Bell Bot is running with webhook!"
    )

    await asyncio.Event().wait()


def bot_thread():
    asyncio.run(start_bot())


def main():
    setup_database()

    thread = threading.Thread(
        target=bot_thread,
        daemon=True
    )

    thread.start()

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    print(
        f"🌐 Server running on port {port}"
    )

    server.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )


if __name__ == "__main__":
    main()
