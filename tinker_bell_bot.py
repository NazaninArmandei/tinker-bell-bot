import os
import time
import random
import psycopg2
from psycopg2.extras import RealDictCursor

from flask import Flask
from threading import Thread

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
Application,
CommandHandler,
MessageHandler,
CallbackQueryHandler,
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
return psycopg2.connect(DATABASE_URL)

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
"✨ بگو «تینک» تا شروع کنیم! ✨",
reply_markup=main_menu()
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
    f"💚 امتیاز تینکی: {format_number(points)}",  
    reply_markup=main_menu()  
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
        "🎉 همه پری‌ها رو آزاد کردی!",  
        reply_markup=main_menu()  
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

await update.message.reply_text(  
    "🧚‍♀️✨ فروشگاه پری‌ها ✨🧚‍♀️\n\n"  
    "پری‌ها به ترتیب باز می‌شن! 🌸\n\n"  
    "🔓 هر پری جدید فقط وقتی قابل خرید می‌شه که "  
    "پری قبلی به سطح ۲۵ رسیده باشه.\n\n"  
    "💚 با امتیازهای تینکی می‌تونی پری‌هات رو بخری و ارتقا بدی.\n\n"  
    "⚡ هر پری در هر ثانیه امتیاز تولید می‌کنه.\n"  
    "📦 هر پری ظرفیت مشخصی برای ذخیره امتیاز داره.\n\n"  
    f"🧚‍♀️ {fairy['name']}\n"  
    f"🌿 استعداد: {fairy['talent']}\n\n"  
    f"💰 قیمت: {format_number(fairy['price'])} امتیاز\n"  
    f"⚡ تولید اولیه: {format_number(fairy['production'])} در ثانیه\n"  
    f"📦 ظرفیت اولیه: {format_number(fairy['capacity'])}\n\n"  
    f"💚 موجودی شما: {format_number(points)} امتیاز",  
    reply_markup=InlineKeyboardMarkup(keyboard)  
)

async def my_fairies(update: Update):
user = update.effective_user

owned = get_owned_fairies(user.id)  

if not owned:  
    await update.message.reply_text(  
        "🧚‍♀️✨ پری‌های من ✨🧚‍♀️\n\n"  
        "هنوز پری‌ای نداری! 🌸\n\n"  
        "💚 از فروشگاه اولین پریت رو بخر.",  
        reply_markup=main_menu()  
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

await update.message.reply_text(  
    message,  
    reply_markup=main_menu()  
)

async def collect(update: Update):
user = update.effective_user

owned = get_owned_fairies(user.id)  

if not owned:  
    await update.message.reply_text(  
        "💚 هنوز امتیازی از پری‌ها برای جمع کردن نداری.",  
        reply_markup=main_menu()  
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

cursor.close()  
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
    f"💚 +{format_number(total)} امتیاز تینکی\n\n"  
    f"💰 موجودی: {format_number(new_points)}",  
    reply_markup=main_menu()  
)

async def upgrade_menu(update: Update):
user = update.effective_user

owned = get_owned_fairies(user.id)  

if not owned:  
    await update.message.reply_text(  
        "🧚‍♀️ هنوز پری‌ای نداری که ارتقاش بدی!",  
        reply_markup=main_menu()  
    )  
    return  

buttons = []  

for fairy_index, level, stored, last_collection in owned:  
    fairy = FAIRIES[fairy_index]  

    buttons.append([  
        InlineKeyboardButton(  
            f"📈 {fairy['name']} — {level}/25",  
            callback_data=f"upgrade_{fairy_index}"  
        )  
    ])  

buttons.append([  
    InlineKeyboardButton(  
        "🔙 منوی اصلی",  
        callback_data="menu"  
    )  
])  

await update.message.reply_text(  
    "🧚‍♀️✨ انتخاب پری برای ارتقا ✨🧚‍♀️\n\n"  
    "پری موردنظرت رو انتخاب کن:",  
    reply_markup=InlineKeyboardMarkup(buttons)  
)

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
        "🎉✨ MAX LEVEL! ✨🎉\n\n"  
        f"🧚‍♀️ {fairy['name']}\n"  
        "🌟 سطح: 25/25"  
    )  
    return  

_, points, _ = get_user(  
    user.id,  
    user.first_name or "Fairy"  
)  

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

await update.message.reply_text(  
    "🧚‍♀️✨ ارتقای پری ✨🧚‍♀️\n\n"  
    f"🔧 {fairy['name']}\n\n"  
    f"🌟 سطح فعلی: {level}/25\n\n"  
    f"⚡ تولید فعلی:\n"  
    f"{format_number(production)} امتیاز در ثانیه\n\n"  
    f"📦 ظرفیت فعلی:\n"  
    f"{format_number(capacity)} امتیاز\n\n"  
    f"💰 هزینه ارتقا:\n"  
    f"{format_number(upgrade_cost)} امتیاز\n\n"  
    f"💚 موجودی شما:\n"  
    f"{format_number(points)} امتیاز\n\n"  
    "✨ می‌خوای این پری رو ارتقا بدی؟",  
    reply_markup=InlineKeyboardMarkup(keyboard)  
)

async def confirm_upgrade(update: Update, fairy_index):
user = update.effective_user

fairy_data = get_fairy(  
    user.id,  
    fairy_index  
)  

if fairy_data is None:  
    return  

level, stored, last_collection = fairy_data  

if level >= 25:  
    await update.message.reply_text(  
        "🎉✨ این پری به MAX LEVEL رسیده! ✨🎉"  
    )  
    return  

fairy = FAIRIES[fairy_index]  

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
        f"💰 هزینه ارتقا: {format_number(upgrade_cost)}\n"  
        f"💚 موجودی شما: {format_number(points)}"  
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

keyboard = []  

if new_level == 25:  
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

await update.message.reply_text(  
    message,  
    reply_markup=InlineKeyboardMarkup(keyboard)  
)

async def buy_fairy(update: Update, fairy_index):
user = update.effective_user

tinkies, points, last_tinky = get_user(  
    user.id,  
    user.first_name or "Fairy"  
)  

owned = get_owned_fairies(user.id)  

next_index = len(owned)  

if fairy_index != next_index:  
    await update.message.reply_text(  
        "🔒 این پری هنوز قابل خرید نیست."  
    )  
    return  

if next_index > 0:  
    previous = owned[-1]  

    if previous[1] < 25:  
        await update.message.reply_text(  
            "🔒 پری بعدی هنوز قفل است!"  
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
    f"💚 هزینه پرداخت‌شده:\n"  
    f"{format_number(fairy['price'])} امتیاز\n\n"  
    f"💰 موجودی شما:\n"  
    f"{format_number(new_points)} امتیاز",  
    reply_markup=main_menu()  
)

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
        "🧚‍♀️ تینکی بعدی:\n"  
        f"{minutes} دقیقه و {seconds} ثانیه دیگه"  
    )  
    return  

old_level = get_level(tinkies)  

new_tinkies = tinkies + 1  
new_level = get_level(new_tinkies)  

earned_points = random.randint(5, 15)  

bonus = 0  

if new_level > old_level:  
    bonus = new_level * 100  

new_points = old_points + earned_points + bonus  

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

await update.message.reply_text(  
    message,  
    reply_markup=main_menu()  
)

async def callback_handler(
update: Update,
context: ContextTypes.DEFAULT_TYPE
):
query = update.callback_query

await query.answer()  

user = query.from_user  

if query.data == "menu":  
    await query.message.reply_text(  
        "🧚‍♀️✨ منوی اصلی ✨🧚‍♀️",  
        reply_markup=main_menu()  
    )  
    return  

if query.data == "profile":  
    tinkies, points, last_tinky = get_user(  
        user.id,  
        user.first_name or "Fairy"  
    )  

    level = get_level(tinkies)  

    await query.message.reply_text(  
        "🧚‍♀️✨ پروفایل تینکی ✨🧚‍♀️\n\n"  
        f"🌟 سطح: {level}\n"  
        f"🔔 تینکی‌ها: {tinkies}\n"  
        f"💚 امتیاز تینکی: {format_number(points)}",  
        reply_markup=main_menu()  
    )  

elif query.data == "fairies":  
    tinkies, points, last_tinky = get_user(  
        user.id,  
        user.first_name or "Fairy"  
    )  

    owned = get_owned_fairies(user.id)  

    next_index = len(owned)  

    if next_index >= len(FAIRIES):  
        await query.message.reply_text(  
            "🎉 همه پری‌ها رو آزاد کردی!",  
            reply_markup=main_menu()  
        )  
        return  

    fairy = FAIRIES[next_index]  

    keyboard = [[  
        InlineKeyboardButton(  
            f"🛒 خرید {fairy['name']}",  
            callback_data=f"buy_{next_index}"  
        )  
    ]]  

    await query.message.reply_text(  
        "🧚‍♀️✨ فروشگاه پری‌ها ✨🧚‍♀️\n\n"  
        f"🧚‍♀️ {fairy['name']}\n"  
        f"🌿 استعداد: {fairy['talent']}\n\n"  
        f"💰 قیمت: {format_number(fairy['price'])}\n"  
        f"⚡ تولید اولیه: {format_number(fairy['production'])}/ثانیه\n"  
        f"📦 ظرفیت اولیه: {format_number(fairy['capacity'])}\n\n"  
        f"💚 موجودی شما: {format_number(points)}",  
        reply_markup=InlineKeyboardMarkup(keyboard)  
    )  

elif query.data == "my_fairies":  
    owned = get_owned_fairies(user.id)  

    if not owned:  
        await query.message.reply_text(  
            "🧚‍♀️ هنوز پری‌ای نداری!",  
            reply_markup=main_menu()  
        )  
        return  

    update_all_fairies(user.id)  

    owned = get_owned_fairies(user.id)  

    message = "🧚‍♀️✨ پری‌های من ✨🧚‍♀️\n\n"  

    for fairy_index, level, stored, last_collection in owned:  
        fairy = FAIRIES[fairy_index]  

        message += (  
            f"🧚‍♀️ {fairy['name']}\n"  
            f"🌟 سطح: {level}/25\n"  
            f"⚡ تولید: {format_number(get_production(fairy_index, level))}/ثانیه\n"  
            f"📦 ظرفیت: {format_number(get_capacity(fairy_index, level))}\n"  
            f"💚 ذخیره: {format_number(stored)}\n\n"  
        )  

    await query.message.reply_text(  
        message,  
        reply_markup=main_menu()  
    )  

elif query.data == "collect":  
    await query.message.reply_text(  
        "💚 برای جمع کردن امتیاز، از دکمه جمع کردن استفاده کن.",  
        reply_markup=main_menu()  
    )  

elif query.data == "upgrade_menu":  
    owned = get_owned_fairies(user.id)  

    if not owned:  
        await query.message.reply_text(  
            "🧚‍♀️ هنوز پری‌ای نداری که ارتقا بدی!",  
            reply_markup=main_menu()  
        )  
        return  

    buttons = []  

    for fairy_index, level, stored, last_collection in owned:  
        buttons.append([  
            InlineKeyboardButton(  
                f"📈 {FAIRIES[fairy_index]['name']} — {level}/25",  
                callback_data=f"upgrade_{fairy_index}"  
            )  
        ])  

    await query.message.reply_text(  
        "🧚‍♀️✨ انتخاب پری برای ارتقا ✨🧚‍♀️",  
        reply_markup=InlineKeyboardMarkup(buttons)  
    )  

elif query.data.startswith("buy_"):  
    fairy_index = int(  
        query.data.split("_")[1]  
    )  

    await buy_fairy(  
        update,  
        fairy_index  
    )  

elif query.data.startswith("upgrade_"):  
    fairy_index = int(  
        query.data.split("_")[1]  
    )  

    await upgrade_fairy(  
        update,  
        fairy_index  
    )  

elif query.data.startswith("confirm_upgrade_"):  
    fairy_index = int(  
        query.data.split("_")[2]  
    )  

    await confirm_upgrade(  
        update,  
        fairy_index  
    )

async def message_handler(
update: Update,
context: ContextTypes.DEFAULT_TYPE
):
if not update.message or not update.message.text:
return

text = update.message.text.casefold().strip()  

if "تینک" in text:  
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

server = Flask(name)

@server.route("/")
def home():
return "Tinker Bell Bot is running!"

def run_server():
port = int(
os.environ.get(
"PORT",
10000
)
)

server.run(  
    host="0.0.0.0",  
    port=port  
)

def main():
setup_database()

Thread(  
    target=run_server,  
    daemon=True  
).start()  

application = (  
    Application  
    .builder()  
    .token(TOKEN)  
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

print("🧚‍♀️ Tinker Bell Bot is running!")  

application.run_polling()

if name == "main":
main() 
