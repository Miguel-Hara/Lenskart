from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import os
import uuid
import requests
import psycopg2
from bs4 import BeautifulSoup

# ==================================================
# ENV CONFIGURATION (NO HARDCODE)
# ==================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")

DATABASE_URL = os.getenv("DATABASE_URL")

QR_IMAGE = "https://files.catbox.moe/r0ldyf.jpg"

# ==================================================
# BOT INITIALIZATION
# ==================================================
app = Client(
    "lenskart_order_bot",
    bot_token=BOT_TOKEN,
    api_id=API_ID,
    api_hash=API_HASH
)

# ==================================================
# DATABASE CONNECTION (HEROKU POSTGRES)
# ==================================================
conn = psycopg2.connect(DATABASE_URL, sslmode="require")
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    telegram_id BIGINT PRIMARY KEY,
    username TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    telegram_id BIGINT,
    product_link TEXT,
    mrp INTEGER,
    final_price INTEGER,
    status TEXT
)
""")
conn.commit()

# ==================================================
# USER STATE MANAGEMENT
# ==================================================
support_waiting = set()
price_waiting = set()
order_waiting = set()

# ==================================================
# PRICE SLAB LOGIC
# ==================================================
def get_percentage(mrp):
    slabs = [
        (1900, 3100, 57.5),
        (3200, 4100, 59),
        (4200, 5400, 62),
        (5500, 6400, 64.5),
        (6500, 7400, 65.5),
        (7500, 8400, 66),
        (8500, 9400, 68),
        (9400, 10300, 69),
        (10400, 11300, 70),
        (11400, 12800, 71)
    ]
    for low, high, percent in slabs:
        if low <= mrp <= high:
            return percent
    return None

# ==================================================
# LENSKART SCRAPER
# ==================================================
def get_mrp(url):
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        price_tag = soup.find("span", class_="price")
        if not price_tag:
            return None
        return int("".join(filter(str.isdigit, price_tag.text)))
    except:
        return None

# ==================================================
# /START COMMAND
# ==================================================
@app.on_message(filters.command("start"))
async def start_handler(client, message):
    cur.execute(
        "INSERT INTO users VALUES (%s,%s) ON CONFLICT DO NOTHING",
        (message.from_user.id, message.from_user.username)
    )
    conn.commit()

    await message.reply_text(
        "👓 *Lenskart Order Bot*\n\nChoose an option:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Price Check", callback_data="price")],
            [InlineKeyboardButton("🛒 Buy New Item", callback_data="buy")],
            [InlineKeyboardButton("🆘 Support", callback_data="support")]
        ])
    )

# ==================================================
# COMMANDS (ALTERNATIVE TO BUTTONS)
# ==================================================
@app.on_message(filters.command("support"))
async def support_command(client, message):
    uid = message.from_user.id
    support_waiting.add(uid)
    price_waiting.discard(uid)
    order_waiting.discard(uid)

    await message.reply(
        "✉️ Please explain your problem in *one single message*."
    )

@app.on_message(filters.command("pricecheckup"))
async def price_command(client, message):
    uid = message.from_user.id
    price_waiting.add(uid)
    support_waiting.discard(uid)
    order_waiting.discard(uid)

    await message.reply("🔗 Send Lenskart product link")

@app.on_message(filters.command("neworder"))
async def neworder_command(client, message):
    uid = message.from_user.id
    order_waiting.add(uid)
    support_waiting.discard(uid)
    price_waiting.discard(uid)

    await message.reply("🔗 Send product link to place order")

# ==================================================
# CALLBACK BUTTON HANDLER
# ==================================================
@app.on_callback_query()
async def callback_handler(client, callback):
    uid = callback.from_user.id

    support_waiting.discard(uid)
    price_waiting.discard(uid)
    order_waiting.discard(uid)

    if callback.data == "support":
        support_waiting.add(uid)
        await callback.message.reply(
            "✉️ Please explain your problem in *one single message*."
        )

    elif callback.data == "price":
        price_waiting.add(uid)
        await callback.message.reply("🔗 Send Lenskart product link")

    elif callback.data == "buy":
        order_waiting.add(uid)
        await callback.message.reply("🔗 Send product link to place order")

# ==================================================
# TEXT MESSAGE HANDLER
# ==================================================
@app.on_message(filters.text & filters.private)
async def text_handler(client, message):
    uid = message.from_user.id
    text = message.text

    # ---------------- SUPPORT FLOW ----------------
    if uid in support_waiting:
        support_waiting.discard(uid)

        await client.send_message(
            ADMIN_ID,
            f"📩 SUPPORT MESSAGE\n\nUser ID: {uid}\n\n{text}"
        )

        await message.reply("✅ Your message has been sent to admin")
        return

    # ---------------- PRICE / ORDER FLOW ----------------
    if "lenskart.com" in text and (uid in price_waiting or uid in order_waiting):
        price_waiting.discard(uid)
        order_waiting.discard(uid)

        mrp = get_mrp(text)
        if not mrp:
            await message.reply("❌ Could not fetch MRP")
            return

        percent = get_percentage(mrp)
        if not percent:
            await message.reply("❌ Price not supported")
            return

        final_price = int(mrp * percent / 100)
        order_id = str(uuid.uuid4())[:8]

        cur.execute(
            "INSERT INTO orders VALUES (%s,%s,%s,%s,%s,%s)",
            (order_id, uid, text, mrp, final_price, "PAYMENT_WAITING")
        )
        conn.commit()

        await message.reply_photo(
            QR_IMAGE,
            caption=(
                f"🆔 Order ID: `{order_id}`\n"
                f"🧾 MRP: ₹{mrp}\n"
                f"📉 Discount: {percent}%\n"
                f"💰 Pay: ₹{final_price}\n\n"
                f"After payment, send screenshot here"
            )
        )
        return

    # ---------------- RANDOM MESSAGE ALERT ----------------
    await message.reply(
        "⚠️ Please choose an option first.\n\n"
        "For support click 🆘 Support or use /support"
    )

# ==================================================
# PAYMENT SCREENSHOT HANDLER
# ==================================================
@app.on_message(filters.photo & filters.private)
async def payment_handler(client, message):
    uid = message.from_user.id

    cur.execute(
        "SELECT order_id, product_link, mrp, final_price FROM orders "
        "WHERE telegram_id=%s AND status='PAYMENT_WAITING'",
        (uid,)
    )
    order = cur.fetchone()

    if not order:
        await message.reply("❌ No pending order found")
        return

    order_id, link, mrp, price = order

    cur.execute(
        "UPDATE orders SET status='PAYMENT_SENT' WHERE order_id=%s",
        (order_id,)
    )
    conn.commit()

    await message.forward(ADMIN_ID)
    await client.send_message(
        ADMIN_ID,
        f"💰 PAYMENT RECEIVED\n\n"
        f"Order ID: {order_id}\n"
        f"User ID: {uid}\n"
        f"Product: {link}\n"
        f"MRP: ₹{mrp}\n"
        f"Paid: ₹{price}\n\n"
        f"/confirm {order_id}\n"
        f"/reject {order_id}"
    )

    await message.reply(
        "✅ Payment received\n⏳ Order waiting for confirmation"
    )

# ==================================================
# ADMIN CONFIRM ORDER
# ==================================================
@app.on_message(filters.command("confirm") & filters.user(ADMIN_ID))
async def confirm_handler(client, message):
    oid = message.text.split()[-1]

    cur.execute(
        "UPDATE orders SET status='CONFIRMED' WHERE order_id=%s",
        (oid,)
    )
    conn.commit()

    cur.execute(
        "SELECT telegram_id FROM orders WHERE order_id=%s",
        (oid,)
    )
    user = cur.fetchone()

    if user:
        await client.send_message(
            user[0],
            f"✅ Order `{oid}` confirmed 🎉"
        )

    await message.reply("Order confirmed")

# ==================================================
# ADMIN REJECT ORDER
# ==================================================
@app.on_message(filters.command("reject") & filters.user(ADMIN_ID))
async def reject_handler(client, message):
    oid = message.text.split()[-1]

    cur.execute(
        "UPDATE orders SET status='REJECTED' WHERE order_id=%s",
        (oid,)
    )
    conn.commit()

    cur.execute(
        "SELECT telegram_id FROM orders WHERE order_id=%s",
        (oid,)
    )
    user = cur.fetchone()

    if user:
        await client.send_message(
            user[0],
            "❌ *Order Rejected*\n\n"
            "You will receive a refund on your original payment method."
        )

    await message.reply("Order rejected & user notified")

# ==================================================
# RUN BOT
# ==================================================
app.run()
