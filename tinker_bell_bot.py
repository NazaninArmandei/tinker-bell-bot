import sqlite3
import random
import os
import time

from threading import Thread
from flask import Flask

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

TOKEN = os.environ["BOT_TOKEN"]
DB = "tinker_bell.db"

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

FAIRIES = {
    "Tinker Bell": {
        "talent": "Tinker",
        "emoji": "🔧",
        "price": 500
    },
    "Silvermist": {
        "talent": "Water",
        "emoji": "💧",
        "price": 5000
    },
    "Rosetta": {
        "talent": "Garden",
        "emoji": "🌹",
        "price": 25000
    },
    "Iridessa": {
        "talent": "Light",
        "emoji": "✨",
        "price": 100000
    },
    "Fawn": {
        "talent": "Animal",
        "emoji": "🐾",
        "price": 350000
    },
    "Vidia": {
        "talent": "Fast-Flying",
        "emoji": "🌪️",
        "price": 1000000
    },
    "Periwinkle": {
        "talent": "Frost",
        "emoji": "❄️",
        "price": 3000000
    },
    "Zarina": {
        "talent": "Dust-Keeper",
        "emoji": "✨",
        "price": 8000000
    },
    "Nyx": {
        "talent": "Scout",
        "emoji": "🛡️",
        "price": 20000000
    }
}

PRODUCTION = {
    1: 2,
    2: 3,
    3: 4,
    4: 5,
    5: 6,
    6: 7,
    7: 8,
    8: 9,
    9: 10,
    10: 11,
    11: 12,
    12: 13,
    13: 14,
    14: 15,
    15: 16,
    16: 17,
    17: 18,
    18: 19,
    19: 20,
    20: 22,
    21: 24,
    22: 26,
    23: 29,
    24: 32,
    25: 36
}

MAX_FAIRY_LEVEL = 25
MAX_OFFLINE_SECONDS = 24 * 60 * 60

health_app = Flask(__name__)

@health_app.route("/")
def health():
    return "Tinker Bell Bot is running!"

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    health_app.run(
        host="0.0.0.0",
        port=port
    )

def get_level(tinkies):
    return (tinkies // 25) + 1

def get_production(level):
    return PRODUCTION.get(
        level,
        PRODUCTION[MAX_FAIRY_LEVEL]
    )

def get_capacity(level):
    return 10000 * level

def get_upgrade_cost(level):
    return 100 * (level ** 2)

def setup_database():
    connection = sqlite3.connect(DB)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            tinkies INTEGER DEFAULT 0,
            points INTEGER DEFAULT 0
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS user_fairies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            fairy_name TEXT NOT NULL,
            level INTEGER DEFAULT 1,
            last_collect INTEGER DEFAULT 0,
            UNIQUE(user_id, fairy_name)
        )
    """)

    columns = connection.execute(
        "PRAGMA table_info(user_fairies)"
    ).fetchall()

    column_names = [column[1] for column in columns]

    if "last_collect" not in column_names:
        connection.execute(
            """
            ALTER TABLE user_fairies
            ADD COLUMN last_collect INTEGER DEFAULT 0
            """
        )

    connection.commit()
    connection.close()

def get_user(user_id, name):
    connection = sqlite3.connect(DB)

    user = connection.execute(
        """
        SELECT tinkies, points
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()

    if user is None:
        connection.execute(
            """
            INSERT INTO users
            (user_id, name, tinkies, points)
            VALUES (?, ?, 0, 0)
            """,
            (user_id, name)
        )

        connection.commit()
        user = (0, 0)

    connection.close()

    return user

def save_user(
    user_id,
    name,
    tinkies,
    points
):
    connection = sqlite3.connect(DB)

    connection.execute(
        """
        INSERT INTO users
        (user_id, name, tinkies, points)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET
            name = excluded.name,
            tinkies = excluded.tinkies,
            points = excluded.points
        """,
        (
            user_id,
            name,
            tinkies,
            points
        )
    )

    connection.commit()
    connection.close()

def get_user_fairies(user_id):
    connection = sqlite3.connect(DB)

    fairies = connection.execute(
        """
        SELECT fairy_name, level, last_collect
        FROM user_fairies
        WHERE user_id = ?
        ORDER BY id
        """,
        (user_id,)
    ).fetchall()

    connection.close()

    return fairies

def has_fairy(user_id, fairy_name):
    connection = sqlite3.connect(DB)

    result = connection.execute(
        """
        SELECT id
        FROM user_fairies
        WHERE user_id = ?
        AND fairy_name = ?
        """,
        (
            user_id,
            fairy_name
        )
    ).fetchone()

    connection.close()

    return result is not None

def get_pending_for_fairy(
    fairy_name,
    level,
    last_collect
):
    now = int(time.time())

    elapsed = max(
        0,
        now - last_collect
    )

    elapsed = min(
        elapsed,
        MAX_OFFLINE_SECONDS
    )

    production = get_production(level)
    capacity = get_capacity(level)

    earned = min(
        int(elapsed * production),
        capacity
    )

    return earned

def get_total_production(user_id):
    fairies = get_user_fairies(user_id)

    total = 0

    for fairy_name, level, last_collect in fairies:
        total += get_production(level)

    return total

def collect_pending(user_id):
    fairies = get_user_fairies(user_id)

    if not fairies:
        return 0, []

    now = int(time.time())
    total_earned = 0
    results = []

    connection = sqlite3.connect(DB)

    for fairy_name, level, last_collect in fairies:
        earned = get_pending_for_fairy(
            fairy_name,
            level,
            last_collect
        )

        total_earned += earned

        results.append(
            (
                fairy_name,
                level,
                earned
            )
        )

        connection.execute(
            """
            UPDATE user_fairies
            SET last_collect = ?
            WHERE user_id = ?
            AND fairy_name = ?
            """,
            (
                now,
                user_id,
                fairy_name
            )
        )

    connection.commit()
    connection.close()

    return total_earned, results

async def collect(update: Update):
    user = update.effective_user

    tinkies, points = get_user(
        user.id,
        user.first_name or "Fairy"
    )

    user_fairies = get_user_fairies(user.id)

    if not user_fairies:
        await update.message.reply_text(
            "🧚‍♀️✨ هنوز هیچ پری‌ای نداری!\n\n"
            "اول یک Fairy بخر تا شروع به تولید Tinky Points کنه."
        )
        return

    earned, results = collect_pending(user.id)

    new_points = points + earned

    save_user(
        user.id,
        user.first_name or "Fairy",
        tinkies,
        new_points
    )

    message = "🧚‍♀️✨ FAIRY COLLECTION ✨🧚‍♀️\n\n"

    for fairy_name, level, amount in results:
        data = FAIRIES[fairy_name]
        capacity = get_capacity(level)

        message += (
            f"{data['emoji']} {fairy_name} Lv.{level}\n"
            f"💚 +{amount:,} TP\n"
            f"📦 Capacity: {capacity:,} TP\n\n"
        )

    message += (
        f"💚 Total Collected: +{earned:,} TP\n"
        f"💰 Balance: {new_points:,} TP"
    )

    await update.message.reply_text(message)

async def fairies(update: Update):
    user = update.effective_user

    owned = {
        fairy_name: level
        for fairy_name, level, last_collect
        in get_user_fairies(user.id)
    }

    message = "🧚‍♀️✨ FAIRY SHOP ✨🧚‍♀️\n\n"

    for index, (fairy_name, data) in enumerate(
        FAIRIES.items(),
        start=1
    ):
        if fairy_name in owned:
            level = owned[fairy_name]

            message += (
                f"{index}. {data['emoji']} {fairy_name}\n"
                f"🌿 Talent: {data['talent']}\n"
                f"🌟 Level: {level}/25\n"
                f"💚 Production: {get_production(level)} TP/sec\n"
                f"📦 Capacity: {get_capacity(level):,} TP\n\n"
            )
        else:
            message += (
                f"{index}. {data['emoji']} {fairy_name}\n"
                f"🌿 Talent: {data['talent']}\n"
                f"💰 Price: {data['price']:,} TP\n\n"
            )

    await update.message.reply_text(message)

async def buy_fairy(
    update: Update,
    fairy_name
):
    user = update.effective_user

    if fairy_name not in FAIRIES:
        await update.message.reply_text(
            "❌ این Fairy وجود نداره."
        )
        return

    tinkies, points = get_user(
        user.id,
        user.first_name or "Fairy"
    )

    if has_fairy(
        user.id,
        fairy_name
    ):
        await update.message.reply_text(
            f"🧚‍♀️ تو قبلاً {fairy_name} رو داری!\n\n"
            "📈 برای ارتقاش از «ارتقا» استفاده کن."
        )
        return

    owned = get_user_fairies(user.id)

    if owned:
        last_fairy_name, last_level, last_collect = owned[-1]

        if last_level < MAX_FAIRY_LEVEL:
            await update.message.reply_text(
                "🔒 Fairy بعدی هنوز باز نشده!\n\n"
                f"🧚 {last_fairy_name}\n"
                f"🌟 Level: {last_level}/25\n\n"
                f"✨ اول باید {last_fairy_name} رو به Level 25 برسونی."
            )
            return

    data = FAIRIES[fairy_name]
    price = data["price"]

    if points < price:
        await update.message.reply_text(
            "💚 Tinky Points کافی نداری!\n\n"
            f"🧚 Fairy: {fairy_name}\n"
            f"💰 Price: {price:,} TP\n"
            f"💚 Your Points: {points:,} TP\n"
            f"❌ Need: {price - points:,} TP"
        )
        return

    now = int(time.time())

    connection = sqlite3.connect(DB)

    connection.execute(
        """
        INSERT INTO user_fairies
        (user_id, fairy_name, level, last_collect)
        VALUES (?, ?, 1, ?)
        """,
        (
            user.id,
            fairy_name,
            now
        )
    )

    connection.commit()
    connection.close()

    new_points = points - price

    save_user(
        user.id,
        user.first_name or "Fairy",
        tinkies,
        new_points
    )

    await update.message.reply_text(
        "🧚‍♀️✨ NEW FAIRY! ✨🧚‍♀️\n\n"
        f"{data['emoji']} {fairy_name}\n"
        f"🌿 Talent: {data['talent']}\n"
        f"🌟 Level: 1/25\n"
        f"💚 Production: {get_production(1)} TP/sec\n"
        f"📦 Capacity: {get_capacity(1):,} TP\n\n"
        f"💰 Paid: {price:,} TP\n"
        f"💚 Remaining: {new_points:,} TP"
    )

async def upgrade_fairy(
    update: Update,
    fairy_name
):
    user = update.effective_user

    connection = sqlite3.connect(DB)

    result = connection.execute(
        """
        SELECT level
        FROM user_fairies
        WHERE user_id = ?
        AND fairy_name = ?
        """,
        (
            user.id,
            fairy_name
        )
    ).fetchone()

    connection.close()

    if result is None:
        await update.message.reply_text(
            "❌ این Fairy رو نداری."
        )
        return

    level = result[0]

    if level >= MAX_FAIRY_LEVEL:
        await update.message.reply_text(
            f"🌟 {fairy_name} همین الان MAX LEVEL هست!\n\n"
            "✨ Level 25/25"
        )
        return

    cost = get_upgrade_cost(level)

    tinkies, points = get_user(
        user.id,
        user.first_name or "Fairy"
    )

    if points < cost:
        await update.message.reply_text(
            "❌ Tinky Points کافی نداری!\n\n"
            f"🧚 {fairy_name}\n"
            f"🌟 Current Level: {level}/25\n"
            f"📈 Next Level: {level + 1}\n"
            f"💰 Upgrade Cost: {cost:,} TP\n"
            f"💚 Your Points: {points:,} TP\n"
            f"❌ Need: {cost - points:,} TP"
        )
        return

    new_level = level + 1

    connection = sqlite3.connect(DB)

    connection.execute(
        """
        UPDATE user_fairies
        SET level = ?
        WHERE user_id = ?
        AND fairy_name = ?
        """,
        (
            new_level,
            user.id,
            fairy_name
        )
    )

    connection.commit()
    connection.close()

    new_points = points - cost

    save_user(
        user.id,
        user.first_name or "Fairy",
        tinkies,
        new_points
    )

    production = get_production(new_level)
    capacity = get_capacity(new_level)

    message = (
        "🧚‍♀️✨ FAIRY UPGRADED! ✨🧚‍♀️\n\n"
        f"🧚 {fairy_name}\n"
        f"🌟 Level: {new_level}/25\n"
        f"💚 Production: {production} TP/sec\n"
        f"📦 Capacity: {capacity:,} TP\n\n"
        f"💰 Upgrade Cost: {cost:,} TP\n"
        f"💚 Remaining: {new_points:,} TP"
    )

    if new_level == MAX_FAIRY_LEVEL:
        message += (
            "\n\n🎉🎉 MAX LEVEL! 🎉🎉\n\n"
            "🔓 Fairy بعدی باز شد!"
        )

    await update.message.reply_text(message)

async def send_profile(update: Update):
    user = update.effective_user

    tinkies, points = get_user(
        user.id,
        user.first_name or "Fairy"
    )

    level = get_level(tinkies)
    remaining = 25 - (tinkies % 25)

    low, high = POINT_RANGES.get(
        level,
        POINT_RANGES[10]
    )

    total_production = get_total_production(user.id)
    user_fairies = get_user_fairies(user.id)

    message = (
        "🧚‍♀️✨ TINKY PROFILE ✨🧚‍♀️\n\n"
        f"🌟 Level: {level}\n"
        f"🔔 Tinkies: {tinkies}\n"
        f"💚 Tinky Points: {points:,}\n\n"
        f"🎲 Points per Tinky: {low}–{high}\n"
        f"✨ تا Level بعدی: {remaining} Tinky\n\n"
        f"⚡ Total Production: {total_production:g} TP/sec\n"
        f"🧚‍♀️ Fairies: {len(user_fairies)}\n"
    )

    if user_fairies:
        message += "\n"

        for fairy_name, fairy_level, last_collect in user_fairies:
            data = FAIRIES[fairy_name]

            message += (
                f"{data['emoji']} {fairy_name}\n"
                f"🌿 {data['talent']}\n"
                f"🌟 Lv.{fairy_level}/25\n"
                f"💚 {get_production(fairy_level)} TP/sec\n"
                f"📦 {get_capacity(fairy_level):,} TP\n\n"
            )
    else:
        message += (
            "\n🧚‍♀️ هنوز Fairy نداری.\n"
            "از /fairies برای خرید استفاده کن."
        )

    await update.message.reply_text(message)

async def my_fairies(update: Update):
    user = update.effective_user

    user_fairies = get_user_fairies(user.id)

    if not user_fairies:
        await update.message.reply_text(
            "🧚‍♀️ هنوز هیچ Fairy نداری!"
        )
        return

    message = "🧚‍♀️✨ MY FAIRIES ✨🧚‍♀️\n\n"

    for fairy_name, level, last_collect in user_fairies:
        data = FAIRIES[fairy_name]

        message += (
            f"{data['emoji']} {fairy_name}\n"
            f"🌿 Talent: {data['talent']}\n"
            f"🌟 Level: {level}/25\n"
            f"💚 Production: {get_production(level)} TP/sec\n"
            f"📦 Capacity: {get_capacity(level):,} TP\n"
        )

        if level < MAX_FAIRY_LEVEL:
            cost = get_upgrade_cost(level)
            message += f"📈 Upgrade: {cost:,} TP\n"

        message += "\n"

    await update.message.reply_text(message)

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "🧚‍♀️✨ سلام! من Tinker Bell هستم!\n\n"
        "🔔 با گفتن «تینک» Tinkies و Tinky Points بگیر.\n"
        "🧚‍♀️ Fairy بخر و تا Level 25 ارتقاش بده.\n"
        "💚 Fairyها در هر ثانیه Tinky Points تولید می‌کنن.\n"
        "📦 هر Fairy ظرفیت مخصوص خودش رو داره.\n"
        "💰 با /collect درآمدت رو جمع کن.\n\n"
        "📋 /profile\n"
        "🧚 /fairies\n"
        "💚 /collect\n"
        "🧚‍♀️ /myfairies\n\n"
        "✨ وقتی Fairy فعلیت به Level 25 برسه، "
        "Fairy بعدی باز می‌شه!"
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

    if text in [
        "پروفایل",
        "تینکیم"
    ]:
        await send_profile(update)
        return

    if text in [
        "پری ها",
        "پریها",
        "پری",
        "fairies"
    ]:
        await fairies(update)
        return

    if text in [
        "جمع کن",
        "collect",
        "جمع"
    ]:
        await collect(update)
        return

    if text in [
        "پری های من",
        "پریهام",
        "my fairies"
    ]:
        await my_fairies(update)
        return

    if text.startswith("خرید "):
        fairy_name = text[5:].strip()

        for name in FAIRIES:
            if name.casefold() == fairy_name:
                await buy_fairy(update, name)
                return

    if text.startswith("ارتقا "):
        fairy_name = text[5:].strip()

        for name in FAIRIES:
            if name.casefold() == fairy_name:
                await upgrade_fairy(update, name)
                return

    if "تینک" not in text:
        return

    user = update.effective_user

    old_tinkies, old_points = get_user(
        user.id,
        user.first_name or "Fairy"
    )

    old_level = get_level(old_tinkies)
    new_tinkies = old_tinkies + 1
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

    message = (
        "🧚‍♀️✨ TINK TINK!\n\n"
        f"💚 +{earned_points} Tinky Points\n"
        f"💰 Total Points: {new_points:,}"
    )

    if new_level > old_level:
        bonus = 0

        for current_level in range(
            old_level + 1,
            new_level + 1
        ):
            bonus += LEVEL_BONUSES.get(
                current_level,
                3000
            )

        new_points += bonus

        message = (
            "🧚‍♀️✨ TINK TINK!\n\n"
            f"💚 +{earned_points} Tinky Points\n"
            f"🎁 +{bonus:,} Level Up Bonus\n\n"
            f"💰 Total Points: {new_points:,}\n\n"
            "🎉🎉 LEVEL UP! 🎉🎉\n"
            f"🌟 Level {new_level}!"
        )

    save_user(
        user.id,
        user.first_name or "Fairy",
        new_tinkies,
        new_points
    )

    await update.message.reply_text(message)

def main():
    setup_database()

    health_thread = Thread(
        target=run_health_server,
        daemon=True
    )

    health_thread.start()

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
            "collect",
            collect
        )
    )

    app.add_handler(
        CommandHandler(
            "myfairies",
            my_fairies
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print("🧚‍♀️ Tinker Bell Bot is running!")

    app.run_polling()

if __name__ == "__main__":
    main()
