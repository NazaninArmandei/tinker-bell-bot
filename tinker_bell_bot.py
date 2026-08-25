import sqlite3
import random
import os

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
    connection.commit()
    connection.close()

def get_level(tinkies):
    return (tinkies // 25) + 1

def get_user(user_id, name):
    connection = sqlite3.connect(DB)
    user = connection.execute(
        "SELECT tinkies, points FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    if user is None:
        connection.execute(
            """
            INSERT INTO users (user_id, name, tinkies, points)
            VALUES (?, ?, 0, 0)
            """,
            (user_id, name)
        )
        connection.commit()
        user = (0, 0)

    connection.close()
    return user

def save_user(user_id, name, tinkies, points):
    connection = sqlite3.connect(DB)
    connection.execute(
        """
        INSERT INTO users (user_id, name, tinkies, points)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET
            name = excluded.name,
            tinkies = excluded.tinkies,
            points = excluded.points
        """,
        (user_id, name, tinkies, points)
    )
    connection.commit()
    connection.close()

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

    await update.message.reply_text(
        "🧚‍♀️✨ TINKY PROFILE ✨🧚‍♀️\n\n"
        f"🌟 Level: {level}\n"
        f"🔔 Tinkies: {tinkies}\n"
        f"💚 Tinky Points: {points}\n\n"
        f"🎲 Points per Tinky: {low}–{high}\n"
        f"✨ تا Level بعدی: {remaining} Tinky"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🧚‍♀️✨ سلام! من Tinker Bell هستم!\n\n"
        "هر وقت بگی «تینک» یا «تینکی»:\n\n"
        "🔔 یک Tinky می‌گیری.\n"
        "💚 Tinky Points رندوم می‌گیری.\n\n"
        "🌟 هر 25 Tinky = یک Level Up\n"
        "📈 با بالا رفتن Level، Points بیشتری می‌گیری.\n"
        "🎁 Level Up هم جایزه جداگانه داره!\n\n"
        "👤 برای دیدن پروفایل:\n"
        "«پروفایل» یا «تینکیم» رو بگو."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.casefold().strip()

    if text in ["پروفایل", "تینکیم"]:
        await send_profile(update)
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

    earned_points = random.randint(low, high)
    new_points = old_points + earned_points

    message = (
        "🧚‍♀️✨ TINK TINK!\n\n"
        f"💚 +{earned_points} Tinky Points\n"
        f"💰 Total Points: {new_points}"
    )

    if new_level > old_level:
        bonus = 0

        for level in range(old_level + 1, new_level + 1):
            bonus += LEVEL_BONUSES.get(level, 3000)

        new_points += bonus

        message = (
            "🧚‍♀️✨ TINK TINK!\n\n"
            f"💚 +{earned_points} Tinky Points\n"
            f"🎁 +{bonus} Level Up Bonus\n\n"
            f"💰 Total Points: {new_points}\n\n"
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

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", send_profile))

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
