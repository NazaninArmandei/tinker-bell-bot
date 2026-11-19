import os
import time
import random
import logging
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from threading import Thread

import psycopg2
from psycopg2.extras import RealDictCursor

from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
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
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
COOLDOWN = 240
TEHRAN = ZoneInfo("Asia/Tehran")

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

TALENTS = {
    "اختراع": {"unlock": "ارتقای موفق ۵ پری", "target": 5, "stat": "upgrades", "weekly": "ارتقای موفق ۵ پری", "weekly_stat": "upgrades", "weekly_target": 5},
    "آب": {"unlock": "۱۰ بار جمع‌آوری موفق", "target": 10, "stat": "collections", "weekly": "۱۰ بار جمع‌آوری", "weekly_stat": "collections", "weekly_target": 10},
    "باغبانی": {"unlock": "۵ بار تینک موفق", "target": 5, "stat": "tinky", "weekly": "۵ بار تینک موفق", "weekly_stat": "tinky", "weekly_target": 5},
    "حیوانات": {"unlock": "فعالیت موفق در ۵ روز متفاوت", "target": 5, "stat": "activity_days", "weekly": "فعالیت در ۵ روز متفاوت", "weekly_stat": "activity_days", "weekly_target": 5},
    "نور": {"unlock": "تکمیل و دریافت پاداش ۱۰ مأموریت", "target": 10, "stat": "missions", "weekly": "تکمیل و دریافت ۱۰ مأموریت", "weekly_stat": "missions", "weekly_target": 10},
    "پرواز سریع": {"unlock": "۱۵ فعالیت موفق", "target": 15, "stat": "activities", "weekly": "۱۵ فعالیت موفق", "weekly_stat": "activities", "weekly_target": 15},
    "یخ": {"unlock": "تکمیل و دریافت پاداش ۵ مأموریت هفتگی", "target": 5, "stat": "weekly_missions", "weekly": "تکمیل ۵ مأموریت هفتگی", "weekly_stat": "weekly_missions", "weekly_target": 5},
}

DAILY_QUESTS = {
    "daily_login": ("ورود روزانه", 1, 500, "login"),
    "daily_tinky": ("تینک روزانه", 3, 1200, "tinky"),
    "daily_collect": ("جمع‌آوری", 2, 1000, "collections"),
    "daily_upgrade": ("مراقبت از پریان", 1, 1500, "upgrades"),
    "daily_points": ("پیشرفت", 500, 2000, "points"),
}

WEEKLY_QUESTS = {
    "weekly_tinky": ("پری پرتلاش", 20, 6000, "tinky"),
    "weekly_collect": ("جمع‌آورنده", 10, 5000, "collections"),
    "weekly_upgrade": ("استاد ارتقا", 3, 7000, "upgrades"),
    "weekly_buy": ("کلکسیونر", 2, 6000, "buys"),
    "weekly_points": ("پیشرفت بزرگ", 3000, 9000, "points"),
}

MILESTONE_REWARDS = {
    2: 2000, 3: 3500, 4: 5000, 5: 8000, 6: 10000,
    7: 12000, 8: 15000, 9: 18000, 10: 25000,
    15: 35000, 20: 50000, 25: 70000, 30: 100000,
    35: 130000, 40: 170000, 45: 220000, 50: 300000,
}

app = Flask(__name__)


def now_tehran():
    return datetime.now(TEHRAN)


def today_key():
    return now_tehran().date().isoformat()


def week_key():
    today = now_tehran().date()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat()


def db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            name TEXT,
            tinkies BIGINT DEFAULT 0,
            points BIGINT DEFAULT 0,
            last_tinky DOUBLE PRECISION DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS fairies (
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            fairy_index INTEGER,
            level INTEGER DEFAULT 1,
            stored_points BIGINT DEFAULT 0,
            last_collection DOUBLE PRECISION DEFAULT 0,
            PRIMARY KEY(user_id, fairy_index)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ph_stats (
            user_id BIGINT,
            stat_key TEXT,
            value BIGINT DEFAULT 0,
            PRIMARY KEY(user_id, stat_key)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ph_activity_days (
            user_id BIGINT,
            activity_date DATE,
            PRIMARY KEY(user_id, activity_date)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ph_talents (
            user_id BIGINT,
            talent_name TEXT,
            level INTEGER DEFAULT 1,
            xp INTEGER DEFAULT 0,
            unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id, talent_name)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ph_quest_progress (
            user_id BIGINT,
            period_type TEXT,
            period_key TEXT,
            quest_id TEXT,
            progress BIGINT DEFAULT 0,
            target BIGINT,
            claimed BOOLEAN DEFAULT FALSE,
            PRIMARY KEY(user_id, period_type, period_key, quest_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ph_quest_claims (
            user_id BIGINT,
            period_type TEXT,
            period_key TEXT,
            quest_id TEXT,
            reward BIGINT,
            claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id, period_type, period_key, quest_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ph_talent_milestone_claims (
            user_id BIGINT,
            talent_name TEXT,
            level INTEGER,
            reward BIGINT,
            PRIMARY KEY(user_id, talent_name, level)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ph_quest_bonus_claims (
            user_id BIGINT,
            period_type TEXT,
            period_key TEXT,
            reward BIGINT,
            PRIMARY KEY(user_id, period_type, period_key)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ph_streaks (
            user_id BIGINT PRIMARY KEY,
            current_streak INTEGER DEFAULT 0,
            last_completed_date DATE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ph_streak_rewards (
            user_id BIGINT,
            streak_count INTEGER,
            reward BIGINT,
            PRIMARY KEY(user_id, streak_count)
        )
    """)

    conn.commit()
    cur.close()
    conn.close()


def ensure_user(user_id, name):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users(user_id,name) VALUES(%s,%s) "
        "ON CONFLICT(user_id) DO UPDATE SET name=EXCLUDED.name",
        (user_id, name),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_user(user_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result


def get_stat(cur, user_id, key):
    cur.execute(
        "SELECT value FROM ph_stats WHERE user_id=%s AND stat_key=%s",
        (user_id, key),
    )
    row = cur.fetchone()
    return int(row["value"]) if row else 0


def add_stat(cur, user_id, key, amount=1):
    cur.execute("""
        INSERT INTO ph_stats(user_id,stat_key,value)
        VALUES(%s,%s,%s)
        ON CONFLICT(user_id,stat_key)
        DO UPDATE SET value=ph_stats.value+EXCLUDED.value
    """, (user_id, key, amount))


def mark_activity(cur, user_id):
    cur.execute(
        "INSERT INTO ph_activity_days(user_id,activity_date) VALUES(%s,%s) ON CONFLICT DO NOTHING",
        (user_id, now_tehran().date()),
    )


def get_activity_days(cur, user_id):
    cur.execute("SELECT COUNT(*) AS count FROM ph_activity_days WHERE user_id=%s", (user_id,))
    return int(cur.fetchone()["count"])


def get_period_progress(cur, user_id, period_type, period_key, quest_id, target):
    cur.execute("""
        INSERT INTO ph_quest_progress(user_id,period_type,period_key,quest_id,target)
        VALUES(%s,%s,%s,%s,%s)
        ON CONFLICT(user_id,period_type,period_key,quest_id) DO NOTHING
    """, (user_id, period_type, period_key, quest_id, target))
    cur.execute("""
        SELECT * FROM ph_quest_progress
        WHERE user_id=%s AND period_type=%s AND period_key=%s AND quest_id=%s
    """, (user_id, period_type, period_key, quest_id))
    return cur.fetchone()


def update_quest_progress(cur, user_id, period_type, quest_id, amount):
    period_key = today_key() if period_type == "daily" else week_key()
    quests = DAILY_QUESTS if period_type == "daily" else WEEKLY_QUESTS
    if quest_id not in quests:
        return
    target = quests[quest_id][1]
    get_period_progress(cur, user_id, period_type, period_key, quest_id, target)
    cur.execute("""
        UPDATE ph_quest_progress
        SET progress=LEAST(target,progress+%s)
        WHERE user_id=%s AND period_type=%s AND period_key=%s AND quest_id=%s
    """, (amount, user_id, period_type, period_key, quest_id))


def update_event_quests(cur, user_id, event, amount=1):
    daily_map = {
        "tinky": "daily_tinky",
        "collections": "daily_collect",
        "upgrades": "daily_upgrade",
        "points": "daily_points",
    }
    weekly_map = {
        "tinky": "weekly_tinky",
        "collections": "weekly_collect",
        "upgrades": "weekly_upgrade",
        "buys": "weekly_buy",
        "points": "weekly_points",
    }
    if event in daily_map:
        update_quest_progress(cur, user_id, "daily", daily_map[event], amount)
    if event in weekly_map:
        update_quest_progress(cur, user_id, "weekly", weekly_map[event], amount)


def record_activity(cur, user_id, event, points=0):
    mark_activity(cur, user_id)
    add_stat(cur, user_id, "activities")
    add_stat(cur, user_id, event)
    update_event_quests(cur, user_id, event)
    if points > 0:
        update_event_quests(cur, user_id, "points", points)


def refresh_talent_unlocks(cur, user_id):
    for talent, data in TALENTS.items():
        if talent == "حیوانات":
            progress = get_activity_days(cur, user_id)
        else:
            progress = get_stat(cur, user_id, data["stat"])

        cur.execute("""
            INSERT INTO ph_talent_unlock_progress(user_id,talent_name,progress,target)
            VALUES(%s,%s,%s,%s)
            ON CONFLICT(user_id,talent_name)
            DO UPDATE SET progress=EXCLUDED.progress,target=EXCLUDED.target
        """, (user_id, talent, progress, data["target"]))


def talent_xp_needed(level):
    return 500 + 250 * (level - 1)


def grant_talent_xp(cur, user_id, talent, xp):
    cur.execute(
        "SELECT * FROM ph_talents WHERE user_id=%s AND talent_name=%s FOR UPDATE",
        (user_id, talent),
    )
    row = cur.fetchone()
    if not row:
        return 0

    level = row["level"]
    current_xp = row["xp"] + xp
    earned_rewards = 0

    while level < 50 and current_xp >= talent_xp_needed(level):
        current_xp -= talent_xp_needed(level)
        level += 1
        reward = MILESTONE_REWARDS.get(level, 0)
        if reward:
            cur.execute("""
                INSERT INTO ph_talent_milestone_claims(user_id,talent_name,level,reward)
                VALUES(%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
                RETURNING reward
            """, (user_id, talent, level, reward))
            claimed = cur.fetchone()
            if claimed:
                earned_rewards += reward

    if level >= 50:
        current_xp = 0

    cur.execute("""
        UPDATE ph_talents SET level=%s,xp=%s
        WHERE user_id=%s AND talent_name=%s
    """, (level, current_xp, user_id, talent))

    if earned_rewards:
        cur.execute("UPDATE users SET points=points+%s WHERE user_id=%s", (earned_rewards, user_id))

    return earned_rewards


def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["🧚🏻‍♀️ پری‌های من"],
            ["👤 پروفایل من", "🏆 لیدربرد"],
            ["✨ پری‌های سرزمین", "💫 درباره‌ی ربات"],
            ["📜 راهنمای بازی"],
            ["📜 مأموریت‌ها", "✨ استعدادهای من"],
        ],
        resize_keyboard=True,
    )


def inline_back():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="menu")]])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.first_name or "پری")
    conn = db()
    cur = conn.cursor()

    period = today_key()
    get_period_progress(cur, user.id, "daily", period, "daily_login", 1)
    cur.execute("""
        UPDATE ph_quest_progress SET progress=1
        WHERE user_id=%s AND period_type='daily' AND period_key=%s
        AND quest_id='daily_login'
    """, (user.id, period))

    conn.commit()
    cur.close()
    conn.close()

    await update.message.reply_text(
        "🧚🏻‍♀️✨ به پیکسی هالو خوش اومدی! ✨🧚🏻‍♀️\n\n"
        "به سرزمین پری‌ها خوش اومدی!\n"
        "اینجا می‌تونی پری‌ها رو جمع‌آوری کنی، ارتقاشون بدی و مأموریت انجام بدی.",
        reply_markup=main_keyboard(),
    )


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user:
        return
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS count FROM fairies WHERE user_id=%s", (user["user_id"],))
    count = cur.fetchone()["count"]
    cur.close()
    conn.close()

    await update.message.reply_text(
        f"👤 شناسنامه‌ی {user['name']}\n\n"
        f"✨ تینکی‌ها: {user['tinkies']:,}\n"
        f"💎 امتیازها: {user['points']:,}\n"
        f"🧚🏻‍♀️ تعداد پری‌ها: {count}",
        reply_markup=inline_back(),
    )


async def handle_tinky(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=%s FOR UPDATE", (user_id,))
    user = cur.fetchone()

    if not user:
        conn.rollback()
        cur.close()
        conn.close()
        return

    remaining = COOLDOWN - (time.time() - user["last_tinky"])
    if remaining > 0:
        conn.rollback()
        cur.close()
        conn.close()
        await update.message.reply_text(
            f"⏳ هنوز آماده نیستی!\nزمان باقی‌مانده: {int(remaining)} ثانیه"
        )
        return

    reward = random.randint(10, 30)
    cur.execute("""
        UPDATE users SET tinkies=tinkies+1,points=points+%s,last_tinky=%s
        WHERE user_id=%s
    """, (reward, time.time(), user_id))

    record_activity(cur, user_id, "tinky", reward)
    refresh_talent_unlocks(cur, user_id)

    conn.commit()
    cur.close()
    conn.close()

    await update.message.reply_text(
        f"✨ تینک موفقیت‌آمیز بود!\n\n"
        f"💎 {reward:,} امتیاز دریافت کردی."
    )


async def show_fairies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM fairies WHERE user_id=%s ORDER BY fairy_index
    """, (user_id,))
    owned = cur.fetchall()
    cur.close()
    conn.close()

    if not owned:
        await update.message.reply_text("هنوز پری‌ای نداری! از بخش پری‌های سرزمین می‌تونی پری بخری.")
        return

    lines = ["🧚🏻‍♀️ پری‌های تو:\n"]
    for fairy in owned:
        info = FAIRIES[fairy["fairy_index"]]
        lines.append(
            f"✨ {info['name']}\n"
            f"سطح: {fairy['level']}\n"
            f"امتیاز ذخیره‌شده: {fairy['stored_points']:,}\n"
        )
    await update.message.reply_text("\n".join(lines), reply_markup=inline_back())


async def fairy_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT fairy_index FROM fairies WHERE user_id=%s", (user_id,))
    owned = {row["fairy_index"] for row in cur.fetchall()}
    cur.close()
    conn.close()

    buttons = []
    for index, fairy in enumerate(FAIRIES):
        if index not in owned:
            buttons.append([
                InlineKeyboardButton(
                    f"{fairy['name']} - {fairy['price']:,} امتیاز",
                    callback_data=f"buy:{index}",
                )
            ])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu")])

    await update.message.reply_text(
        "✨ پری‌های سرزمین\n\nپری موردنظرت رو انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def collect_fairy(query, user_id, fairy_index):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM fairies WHERE user_id=%s AND fairy_index=%s FOR UPDATE
    """, (user_id, fairy_index))
    fairy = cur.fetchone()

    if not fairy:
        conn.rollback()
        cur.close()
        conn.close()
        await query.edit_message_text("این پری رو نداری!")
        return

    info = FAIRIES[fairy_index]
    elapsed = max(0, time.time() - fairy["last_collection"])
    produced = int(elapsed * info["production"] * fairy["level"])
    available = max(0, info["capacity"] * fairy["level"] - fairy["stored_points"])
    amount = min(produced, available)

    if amount <= 0:
        conn.rollback()
        cur.close()
        conn.close()
        await query.edit_message_text("هنوز امتیازی برای جمع‌آوری آماده نشده!")
        return

    cur.execute("""
        UPDATE fairies
        SET stored_points=stored_points-%s,last_collection=%s
        WHERE user_id=%s AND fairy_index=%s
    """, (amount, time.time(), user_id, fairy_index))
    cur.execute("UPDATE users SET points=points+%s WHERE user_id=%s", (amount, user_id))

    record_activity(cur, user_id, "collections", amount)
    refresh_talent_unlocks(cur, user_id)

    conn.commit()
    cur.close()
    conn.close()

    await query.edit_message_text(f"💎 {amount:,} امتیاز از {info['name']} جمع‌آوری شد!")


async def upgrade_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM fairies WHERE user_id=%s ORDER BY fairy_index
    """, (update.effective_user.id,))
    owned = cur.fetchall()
    cur.close()
    conn.close()

    if not owned:
        await update.message.reply_text("هنوز پری‌ای برای ارتقا نداری!")
        return

    buttons = []
    for fairy in owned:
        info = FAIRIES[fairy["fairy_index"]]
        if fairy["level"] < info["max_level"]:
            cost = int(info["price"] * (fairy["level"] ** 1.5))
            buttons.append([
                InlineKeyboardButton(
                    f"{info['name']} - سطح {fairy['level']} | {cost:,}",
                    callback_data=f"upgrade:{fairy['fairy_index']}",
                )
            ])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu")])

    await update.message.reply_text(
        "⬆️ کدوم پری رو ارتقا می‌دی؟",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT name,points FROM users ORDER BY points DESC LIMIT 10")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    text = "🏆 لیدربرد پیکسی هالو\n\n"
    for index, row in enumerate(rows, 1):
        text += f"{index}. {row['name']} — {row['points']:,} امتیاز\n"
    await update.message.reply_text(text, reply_markup=inline_back())


async def show_quests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = db()
    cur = conn.cursor()

    sections = [
        ("daily", today_key(), DAILY_QUESTS, "☀️ مأموریت‌های روزانه"),
        ("weekly", week_key(), WEEKLY_QUESTS, "🌙 مأموریت‌های هفتگی"),
    ]

    text = "📜 مأموریت‌ها\n"
    buttons = []

    for period_type, period_key, quests, heading in sections:
        text += f"\n{heading}\n"
        for quest_id, (name, target, reward, stat) in quests.items():
            row = get_period_progress(cur, user_id, period_type, period_key, quest_id, target)
            progress = min(row["progress"], target)
            status = "✅ دریافت شد" if row["claimed"] else f"{progress}/{target}"
            text += f"\n• {name}: {status}\n  پاداش: {reward:,} امتیاز\n"

            if progress >= target and not row["claimed"]:
                buttons.append([
                    InlineKeyboardButton(
                        f"🎁 دریافت: {name}",
                        callback_data=f"claim:{period_type}:{quest_id}",
                    )
                ])

        cur.execute("""
            SELECT COUNT(*) AS count FROM ph_quest_progress
            WHERE user_id=%s AND period_type=%s AND period_key=%s AND claimed=TRUE
        """, (user_id, period_type, period_key))
        claimed_count = cur.fetchone()["count"]
        bonus = 3000 if period_type == "daily" else 10000
        if claimed_count == 5:
            cur.execute("""
                SELECT 1 FROM ph_quest_bonus_claims
                WHERE user_id=%s AND period_type=%s AND period_key=%s
            """, (user_id, period_type, period_key))
            if not cur.fetchone():
                buttons.append([
                    InlineKeyboardButton(
                        f"🎉 پاداش تکمیل {heading}: {bonus:,}",
                        callback_data=f"bonus:{period_type}",
                    )
                ])

    conn.commit()
    cur.close()
    conn.close()

    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu")])
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def show_talents(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = db()
    cur = conn.cursor()
    refresh_talent_unlocks(cur, user_id)

    text = "✨ استعدادهای تو\n"
    buttons = []

    for talent, data in TALENTS.items():
        cur.execute(
            "SELECT * FROM ph_talents WHERE user_id=%s AND talent_name=%s",
            (user_id, talent),
        )
        unlocked = cur.fetchone()

        cur.execute("""
            SELECT progress,target FROM ph_talent_unlock_progress
            WHERE user_id=%s AND talent_name=%s
        """, (user_id, talent))
        progress = cur.fetchone()

        if unlocked:
            needed = talent_xp_needed(unlocked["level"]) if unlocked["level"] < 50 else 0
            text += (
                f"\n✨ {talent}\n"
                f"سطح: {unlocked['level']}/50\n"
                f"تجربه: {unlocked['xp']}/{needed}\n"
                f"مأموریت هفتگی: {data['weekly']}\n"
            )
            buttons.append([
                InlineKeyboardButton(
                    f"📜 مأموریت هفتگی {talent}",
                    callback_data=f"talentquest:{talent}",
                )
            ])
        else:
            text += (
                f"\n🔒 {talent}\n"
                f"شرط آزادسازی: {data['unlock']}\n"
                f"پیشرفت: {progress['progress']}/{progress['target']}\n"
            )
            if progress["progress"] >= progress["target"]:
                buttons.append([
                    InlineKeyboardButton(
                        f"🎁 آزادسازی استعداد {talent}",
                        callback_data=f"unlock:{talent}",
                    )
                ])

    conn.commit()
    cur.close()
    conn.close()

    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu")])
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def show_talent_quests(query, user_id, talent):
    if talent not in TALENTS:
        await query.edit_message_text("استعداد موردنظر پیدا نشد.")
        return

    conn = db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM ph_talents WHERE user_id=%s AND talent_name=%s",
        (user_id, talent),
    )
    unlocked = cur.fetchone()

    if not unlocked:
        conn.rollback()
        cur.close()
        conn.close()
        await query.edit_message_text("این استعداد هنوز آزاد نشده است.")
        return

    data = TALENTS[talent]
    progress = (
        get_activity_days(cur, user_id)
        if data["weekly_stat"] == "activity_days"
        else get_stat(cur, user_id, data["weekly_stat"])
    )

    period = week_key()
    quest_id = f"talent_{talent}"
    target = data["weekly_target"]

    cur.execute("""
        INSERT INTO ph_quest_progress(user_id,period_type,period_key,quest_id,target)
        VALUES(%s,'talent',%s,%s,%s)
        ON CONFLICT DO NOTHING
    """, (user_id, period, quest_id, target))

    cur.execute("""
        SELECT * FROM ph_quest_progress
        WHERE user_id=%s AND period_type='talent' AND period_key=%s AND quest_id=%s
    """, (user_id, period, quest_id))
    row = cur.fetchone()

    if not row["claimed"]:
        cur.execute("""
            UPDATE ph_quest_progress SET progress=LEAST(%s,%s)
            WHERE user_id=%s AND period_type='talent' AND period_key=%s AND quest_id=%s
        """, (target, progress, user_id, period, quest_id))
        row["progress"] = min(progress, target)

    conn.commit()
    cur.close()
    conn.close()

    text = (
        f"✨ مأموریت هفتگی استعداد {talent}\n\n"
        f"{data['weekly']}\n"
        f"پیشرفت: {row['progress']}/{target}\n\n"
        "🎁 پاداش: ۵۰۰۰ امتیاز + ۵۰۰ تجربه استعداد"
    )

    buttons = []
    if row["progress"] >= target and not row["claimed"]:
        buttons.append([
            InlineKeyboardButton(
                "🎁 دریافت پاداش",
                callback_data=f"claimtalent:{talent}",
            )
        ])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="talents")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def claim_quest(query, user_id, period_type, quest_id):
    quests = DAILY_QUESTS if period_type == "daily" else WEEKLY_QUESTS
    if quest_id not in quests:
        await query.edit_message_text("مأموریت پیدا نشد.")
        return

    name, target, reward, _ = quests[quest_id]
    period = today_key() if period_type == "daily" else week_key()

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id=%s FOR UPDATE", (user_id,))
    cur.fetchone()

    row = get_period_progress(cur, user_id, period_type, period, quest_id, target)
    if row["claimed"] or row["progress"] < target:
        conn.rollback()
        cur.close()
        conn.close()
        await query.edit_message_text("این مأموریت هنوز کامل نشده یا پاداشش قبلاً دریافت شده است.")
        return

    cur.execute("""
        INSERT INTO ph_quest_claims(user_id,period_type,period_key,quest_id,reward)
        VALUES(%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING RETURNING reward
    """, (user_id, period_type, period, quest_id, reward))
    claimed = cur.fetchone()

    if not claimed:
        conn.rollback()
        cur.close()
        conn.close()
        await query.edit_message_text("پاداش این مأموریت قبلاً دریافت شده است.")
        return

    cur.execute("""
        UPDATE ph_quest_progress SET claimed=TRUE
        WHERE user_id=%s AND period_type=%s AND period_key=%s AND quest_id=%s
    """, (user_id, period_type, period, quest_id))
    cur.execute("UPDATE users SET points=points+%s WHERE user_id=%s", (reward, user_id))

    add_stat(cur, user_id, "missions")
    if period_type == "weekly":
        add_stat(cur, user_id, "weekly_missions")

    refresh_talent_unlocks(cur, user_id)
    conn.commit()
    cur.close()
    conn.close()

    await query.edit_message_text(f"🎉 مأموریت «{name}» تکمیل شد!\n💎 {reward:,} امتیاز دریافت کردی.")


async def claim_bonus(query, user_id, period_type):
    period = today_key() if period_type == "daily" else week_key()
    reward = 3000 if period_type == "daily" else 10000

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id=%s FOR UPDATE", (user_id,))
    cur.fetchone()

    cur.execute("""
        SELECT COUNT(*) AS count FROM ph_quest_progress
        WHERE user_id=%s AND period_type=%s AND period_key=%s AND claimed=TRUE
    """, (user_id, period_type, period))
    count = cur.fetchone()["count"]

    if count < 5:
        conn.rollback()
        cur.close()
        conn.close()
        await query.edit_message_text("هنوز همه مأموریت‌ها دریافت نشده‌اند.")
        return

    cur.execute("""
        INSERT INTO ph_quest_bonus_claims(user_id,period_type,period_key,reward)
        VALUES(%s,%s,%s,%s)
        ON CONFLICT DO NOTHING RETURNING reward
    """, (user_id, period_type, period, reward))
    claimed = cur.fetchone()

    if not claimed:
        conn.rollback()
        cur.close()
        conn.close()
        await query.edit_message_text("این پاداش قبلاً دریافت شده است.")
        return

    cur.execute("UPDATE users SET points=points+%s WHERE user_id=%s", (reward, user_id))

    if period_type == "daily":
        update_streak(cur, user_id)

    conn.commit()
    cur.close()
    conn.close()

    await query.edit_message_text(f"🎉 آفرین!\n💎 {reward:,} امتیاز پاداش تکمیل مأموریت‌ها دریافت کردی.")


def update_streak(cur, user_id):
    today = now_tehran().date()
    cur.execute("SELECT * FROM ph_streaks WHERE user_id=%s FOR UPDATE", (user_id,))
    row = cur.fetchone()

    if not row:
        streak = 1
        cur.execute("""
            INSERT INTO ph_streaks(user_id,current_streak,last_completed_date)
            VALUES(%s,1,%s)
        """, (user_id, today))
    elif row["last_completed_date"] == today:
        return
    elif row["last_completed_date"] == today - timedelta(days=1):
        streak = row["current_streak"] + 1
        cur.execute("""
            UPDATE ph_streaks SET current_streak=%s,last_completed_date=%s
            WHERE user_id=%s
        """, (streak, today, user_id))
    else:
        streak = 1
        cur.execute("""
            UPDATE ph_streaks SET current_streak=1,last_completed_date=%s
            WHERE user_id=%s
        """, (today, user_id))

    rewards = {3: 2000, 7: 7000, 14: 15000, 30: 40000}
    if streak > 30 and streak % 30 == 0:
        rewards[streak] = 40000

    reward = rewards.get(streak, 0)
    if reward:
        cur.execute("""
            INSERT INTO ph_streak_rewards(user_id,streak_count,reward)
            VALUES(%s,%s,%s)
            ON CONFLICT DO NOTHING RETURNING reward
        """, (user_id, streak, reward))
        result = cur.fetchone()
        if result:
            cur.execute("UPDATE users SET points=points+%s WHERE user_id=%s", (reward, user_id))


async def unlock_talent(query, user_id, talent):
    if talent not in TALENTS:
        await query.edit_message_text("استعداد موردنظر پیدا نشد.")
        return

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id=%s FOR UPDATE", (user_id,))
    cur.fetchone()

    refresh_talent_unlocks(cur, user_id)
    cur.execute("""
        SELECT progress,target FROM ph_talent_unlock_progress
        WHERE user_id=%s AND talent_name=%s
    """, (user_id, talent))
    progress = cur.fetchone()

    if not progress or progress["progress"] < progress["target"]:
        conn.rollback()
        cur.close()
        conn.close()
        await query.edit_message_text("شرط آزادسازی این استعداد هنوز کامل نشده است.")
        return

    cur.execute("""
        INSERT INTO ph_talents(user_id,talent_name,level,xp)
        VALUES(%s,%s,1,0)
        ON CONFLICT DO NOTHING RETURNING talent_name
    """, (user_id, talent))
    result = cur.fetchone()

    if not result:
        conn.rollback()
        cur.close()
        conn.close()
        await query.edit_message_text("این استعداد قبلاً آزاد شده است.")
        return

    conn.commit()
    cur.close()
    conn.close()

    await query.edit_message_text(f"🎉 استعداد «{talent}» آزاد شد!\nسطح اولیه: ۱")


async def claim_talent_quest(query, user_id, talent):
    if talent not in TALENTS:
        await query.edit_message_text("استعداد پیدا نشد.")
        return

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id=%s FOR UPDATE", (user_id,))
    cur.fetchone()

    cur.execute(
        "SELECT * FROM ph_talents WHERE user_id=%s AND talent_name=%s FOR UPDATE",
        (user_id, talent),
    )
    unlocked = cur.fetchone()

    if not unlocked:
        conn.rollback()
        cur.close()
        conn.close()
        await query.edit_message_text("این استعداد هنوز آزاد نشده است.")
        return

    period = week_key()
    quest_id = f"talent_{talent}"
    target = TALENTS[talent]["weekly_target"]

    cur.execute("""
        SELECT * FROM ph_quest_progress
        WHERE user_id=%s AND period_type='talent' AND period_key=%s AND quest_id=%s
        FOR UPDATE
    """, (user_id, period, quest_id))
    row = cur.fetchone()

    if not row or row["claimed"] or row["progress"] < target:
        conn.rollback()
        cur.close()
        conn.close()
        await query.edit_message_text("مأموریت هنوز کامل نشده یا پاداش آن دریافت شده است.")
        return

    cur.execute("""
        UPDATE ph_quest_progress SET claimed=TRUE
        WHERE user_id=%s AND period_type='talent' AND period_key=%s AND quest_id=%s
    """, (user_id, period, quest_id))

    cur.execute("UPDATE users SET points=points+5000 WHERE user_id=%s", (user_id,))
    milestone_reward = grant_talent_xp(cur, user_id, talent, 500)

    conn.commit()
    cur.close()
    conn.close()

    extra = f"\n🎖 پاداش ارتقای سطح: {milestone_reward:,} امتیاز" if milestone_reward else ""
    await query.edit_message_text(
        f"🎉 مأموریت هفتگی استعداد «{talent}» کامل شد!\n"
        f"💎 ۵۰۰۰ امتیاز\n"
        f"✨ ۵۰۰ تجربه استعداد{extra}"
    )


async def buy_fairy(query, user_id, fairy_index):
    if fairy_index < 0 or fairy_index >= len(FAIRIES):
        await query.edit_message_text("پری موردنظر پیدا نشد.")
        return

    info = FAIRIES[fairy_index]
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=%s FOR UPDATE", (user_id,))
    user = cur.fetchone()

    cur.execute(
        "SELECT 1 FROM fairies WHERE user_id=%s AND fairy_index=%s",
        (user_id, fairy_index),
    )
    if cur.fetchone():
        conn.rollback()
        cur.close()
        conn.close()
        await query.edit_message_text("این پری رو قبلاً خریدی!")
        return

    if user["points"] < info["price"]:
        conn.rollback()
        cur.close()
        conn.close()
        await query.edit_message_text("امتیاز کافی برای خرید این پری نداری.")
        return

    cur.execute("UPDATE users SET points=points-%s WHERE user_id=%s", (info["price"], user_id))
    cur.execute("""
        INSERT INTO fairies(user_id,fairy_index,level,stored_points,last_collection)
        VALUES(%s,%s,1,0,%s)
    """, (user_id, fairy_index, time.time()))

    record_activity(cur, user_id, "buys")
    refresh_talent_unlocks(cur, user_id)

    conn.commit()
    cur.close()
    conn.close()

    await query.edit_message_text(f"🎉 {info['name']} به مجموعه پری‌هات اضافه شد!")


async def upgrade_fairy(query, user_id, fairy_index):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=%s FOR UPDATE", (user_id,))
    user = cur.fetchone()

    cur.execute("""
        SELECT * FROM fairies WHERE user_id=%s AND fairy_index=%s FOR UPDATE
    """, (user_id, fairy_index))
    fairy = cur.fetchone()

    if not fairy:
        conn.rollback()
        cur.close()
        conn.close()
        await query.edit_message_text("این پری رو نداری.")
        return

    info = FAIRIES[fairy_index]
    if fairy["level"] >= info["max_level"]:
        conn.rollback()
        cur.close()
        conn.close()
        await query.edit_message_text("این پری به حداکثر سطح خودش رسیده!")
        return

    cost = int(info["price"] * (fairy["level"] ** 1.5))
    if user["points"] < cost:
        conn.rollback()
        cur.close()
        conn.close()
        await query.edit_message_text("امتیاز کافی برای ارتقای این پری نداری.")
        return

    cur.execute("UPDATE users SET points=points-%s WHERE user_id=%s", (cost, user_id))
    cur.execute("""
        UPDATE fairies SET level=level+1
        WHERE user_id=%s AND fairy_index=%s
    """, (user_id, fairy_index))

    record_activity(cur, user_id, "upgrades")
    refresh_talent_unlocks(cur, user_id)

    conn.commit()
    cur.close()
    conn.close()

    await query.edit_message_text(
        f"🎉 {info['name']} با موفقیت ارتقا پیدا کرد!\n"
        f"سطح جدید: {fairy['level'] + 1}"
    )


async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💫 درباره‌ی پیکسی هالو\n\n"
        "به دنیای جادویی پری‌ها خوش اومدی!\n"
        "پری جمع کن، امتیاز بگیر، مأموریت انجام بده و استعدادهای جدید آزاد کن.",
        reply_markup=inline_back(),
    )


async def guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📜 راهنمای بازی\n\n"
        "🧚🏻‍♀️ با دستور /tinky می‌تونی تینک انجام بدی.\n"
        "✨ از بخش پری‌های سرزمین پری جدید بخر.\n"
        "💎 امتیاز پری‌هات رو جمع‌آوری کن.\n"
        "⬆️ پری‌هات رو ارتقا بده.\n"
        "📜 مأموریت‌های روزانه و هفتگی رو انجام بده.\n"
        "🌟 با تکمیل شرط‌ها استعدادهای جدید آزاد کن.\n\n"
        "دستورها:\n"
        "/quests - مأموریت‌ها\n"
        "/daily - مأموریت‌های روزانه\n"
        "/weekly - مأموریت‌های هفتگی\n"
        "/talents - استعدادها\n"
        "/talentquests - مأموریت‌های استعدادها",
        reply_markup=inline_back(),
    )


async def menu_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "🧚🏻‍♀️ پری‌های من":
        await show_fairies(update, context)
    elif text == "👤 پروفایل من":
        await profile(update, context)
    elif text == "🏆 لیدربرد":
        await leaderboard(update, context)
    elif text == "✨ پری‌های سرزمین":
        await fairy_shop(update, context)
    elif text == "💫 درباره‌ی ربات":
        await about(update, context)
    elif text == "📜 راهنمای بازی":
        await guide(update, context)
    elif text == "📜 مأموریت‌ها":
        await show_quests(update, context)
    elif text == "✨ استعدادهای من":
        await show_talents(update, context)
    elif text == "⬆️ ارتقای پری‌ها":
        await upgrade_menu(update, context)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "menu":
        await query.message.reply_text("🧚🏻‍♀️ منوی اصلی", reply_markup=main_keyboard())
    elif data == "talents":
        await show_talents_callback(query, user_id)
    elif data.startswith("buy:"):
        await buy_fairy(query, user_id, int(data.split(":")[1]))
    elif data.startswith("upgrade:"):
        await upgrade_fairy(query, user_id, int(data.split(":")[1]))
    elif data.startswith("collect:"):
        await collect_fairy(query, user_id, int(data.split(":")[1]))
    elif data.startswith("claim:"):
        _, period_type, quest_id = data.split(":", 2)
        await claim_quest(query, user_id, period_type, quest_id)
    elif data.startswith("bonus:"):
        await claim_bonus(query, user_id, data.split(":")[1])
    elif data.startswith("unlock:"):
        await unlock_talent(query, user_id, data.split(":", 1)[1])
    elif data.startswith("talentquest:"):
        await show_talent_quests(query, user_id, data.split(":", 1)[1])
    elif data.startswith("claimtalent:"):
        await claim_talent_quest(query, user_id, data.split(":", 1)[1])


async def show_talents_callback(query, user_id):
    class FakeUser:
        id = user_id

    conn = db()
    cur = conn.cursor()
    refresh_talent_unlocks(cur, user_id)

    text = "✨ استعدادهای تو\n"
    buttons = []

    for talent, data in TALENTS.items():
        cur.execute(
            "SELECT * FROM ph_talents WHERE user_id=%s AND talent_name=%s",
            (user_id, talent),
        )
        unlocked = cur.fetchone()

        cur.execute("""
            SELECT progress,target FROM ph_talent_unlock_progress
            WHERE user_id=%s AND talent_name=%s
        """, (user_id, talent))
        progress = cur.fetchone()

        if unlocked:
            needed = talent_xp_needed(unlocked["level"]) if unlocked["level"] < 50 else 0
            text += f"\n✨ {talent}\nسطح: {unlocked['level']}/50\nتجربه: {unlocked['xp']}/{needed}\n"
            buttons.append([
                InlineKeyboardButton(
                    f"📜 مأموریت هفتگی {talent}",
                    callback_data=f"talentquest:{talent}",
                )
            ])
        else:
            text += (
                f"\n🔒 {talent}\n"
                f"شرط: {data['unlock']}\n"
                f"پیشرفت: {progress['progress']}/{progress['target']}\n"
            )
            if progress["progress"] >= progress["target"]:
                buttons.append([
                    InlineKeyboardButton(
                        f"🎁 آزادسازی {talent}",
                        callback_data=f"unlock:{talent}",
                    )
                ])

    conn.commit()
    cur.close()
    conn.close()

    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_quests(update, context)


async def weekly_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_quests(update, context)


async def talentquests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_talents(update, context)


async def talents_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_talents(update, context)


async def quests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_quests(update, context)


async def tink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_tinky(update, context)


async def collect_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM fairies WHERE user_id=%s ORDER BY fairy_index", (user_id,))
    fairies = cur.fetchall()
    cur.close()
    conn.close()

    if not fairies:
        await update.message.reply_text("هنوز پری‌ای نداری!")
        return

    buttons = []
    for fairy in fairies:
        info = FAIRIES[fairy["fairy_index"]]
        buttons.append([
            InlineKeyboardButton(
                f"💎 جمع‌آوری از {info['name']}",
                callback_data=f"collect:{fairy['fairy_index']}",
            )
        ])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu")])

    await update.message.reply_text(
        "از کدوم پری امتیاز جمع‌آوری می‌کنی؟",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def upgrade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await upgrade_menu(update, context)


@app.route("/")
def home():
    return "Pixie Hollow Bot is running!"


@app.route("/health")
def health():
    return {"status": "ok"}


def run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))


async def post_init(application: Application):
    init_db()
    logger.info("Pixie Hollow bot initialized.")


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is missing")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is missing")

    init_db()

    Thread(target=run_flask, daemon=True).start()

    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("tinky", tink_command))
    application.add_handler(CommandHandler("tink", tink_command))
    application.add_handler(CommandHandler("collect", collect_command))
    application.add_handler(CommandHandler("upgrade", upgrade_command))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("quests", quests_command))
    application.add_handler(CommandHandler("daily", daily_command))
    application.add_handler(CommandHandler("weekly", weekly_command))
    application.add_handler(CommandHandler("talents", talents_command))
    application.add_handler(CommandHandler("talentquests", talentquests_command))
    application.add_handler(CommandHandler("leaderboard", leaderboard))

    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, menu_message)
    )

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
