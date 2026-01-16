from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import os, uuid, psycopg2
import pyrogram.utils

# ================= FIX CHANNEL RANGE =================
pyrogram.utils.MIN_CHANNEL_ID = -1009147483647

# ================= ENV =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
DATABASE_URL = os.getenv("DATABASE_URL")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))

# ================= BUSINESS RULE =================
MIN_MRP = 3000
DISCOUNT_PERCENT = 75

# ================= IMAGES =================
START_IMAGE = "https://files.catbox.moe/5t348b.jpg"
QR_IMAGE = "https://files.catbox.moe/r0ldyf.jpg"
MRP_HELP_IMAGE = "https://files.catbox.moe/orp6r5.jpg"

# ================= BOT =================
app = Client(
    "lenskart_order_bot",
    bot_token=BOT_TOKEN,
    api_id=API_ID,
    api_hash=API_HASH
)

# ================= DATABASE =================
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

# ================= STATE =================
support_waiting = set()
mrp_waiting = {}
broadcast_waiting = False

# ================= STATUS BUTTONS =================
def status_buttons(oid):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📦 Packed", callback_data=f"status:PACKED:{oid}"),
            InlineKeyboardButton("🚚 On The Way", callback_data=f"status:ON_THE_WAY:{oid}")
        ],
        [
            InlineKeyboardButton("📬 Delivered", callback_data=f"status:DELIVERED:{oid}")
        ]
    ])

# ================= START =================
@app.on_message(filters.command("start"))
async def start(client, msg):
    if msg.from_user.id == ADMIN_ID:
        await msg.reply("Admin mode active")
        return

    cur.execute(
        "INSERT INTO users VALUES (%s,%s) ON CONFLICT DO NOTHING",
        (msg.from_user.id, msg.from_user.username)
    )
    conn.commit()

    await msg.reply_photo(
        START_IMAGE,
        caption=(
            "Lenskart Order Bot\n\n"
            "Simple ordering • Tracking • Support\n\n"
            "Use /help to know steps"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("New Order", callback_data="buy")],
            [InlineKeyboardButton("Support", callback_data="support")]
        ])
    )

# ================= HELP =================
@app.on_message(filters.command("help"))
async def help_cmd(client, msg):
    await msg.reply(
        "How to use:\n\n"
        "1. Send Lenskart product link\n"
        "2. Send original MRP\n"
        "3. Pay via QR\n"
        "4. Send payment screenshot\n\n"
        "Track: /track ORDER_ID\n"
        "Support: /support"
    )

# ================= TRACK =================
@app.on_message(filters.command("track"))
async def track(client, msg):
    if len(msg.command) != 2:
        await msg.reply("Usage: /track ORDER_ID")
        return

    oid = msg.command[1]
    cur.execute(
        "SELECT status FROM orders WHERE order_id=%s AND telegram_id=%s",
        (oid, msg.from_user.id)
    )
    row = cur.fetchone()

    if not row:
        await msg.reply("Order not found")
        return

    await msg.reply(f"Order {oid}\nStatus: {row[0]}")

# ================= ORDERS (ADMIN) =================
@app.on_message(filters.command("orders") & filters.user(ADMIN_ID))
async def orders_cmd(client, msg):
    cur.execute("SELECT order_id, telegram_id, status FROM orders ORDER BY order_id DESC LIMIT 20")
    rows = cur.fetchall()

    if not rows:
        await msg.reply("No orders found")
        return

    text = "Recent Orders:\n\n"
    for oid, uid, status in rows:
        text += f"{oid} | {uid} | {status}\n"

    await msg.reply(text)

# ================= BROADCAST (ADMIN) =================
@app.on_message(filters.command("broadcast") & filters.user(ADMIN_ID))
async def broadcast_start(client, msg):
    global broadcast_waiting
    broadcast_waiting = True
    await msg.reply("Send the message to broadcast")

# ================= ADMIN REPLY =================
@app.on_message(filters.command("reply") & filters.user(ADMIN_ID))
async def admin_reply(client, msg):
    parts = msg.text.split(maxsplit=2)
    if len(parts) < 3:
        await msg.reply("Usage: /reply user_id message")
        return

    await client.send_message(int(parts[1]), parts[2])
    await msg.reply("Reply sent")

# ================= CALLBACKS =================
@app.on_callback_query()
async def callbacks(client, cb):
    uid = cb.from_user.id
    data = cb.data

    if data == "buy":
        await cb.message.reply("Send Lenskart product link")
        return

    if data == "support":
        support_waiting.add(uid)
        await cb.message.reply("Send your issue in one message")
        return

# ================= SUPPORT HANDLER (FIXED) =================
@app.on_message(filters.private & filters.text)
async def support_handler(client, msg):
    uid = msg.from_user.id

    if uid not in support_waiting:
        return

    support_waiting.discard(uid)

    await msg.forward(ADMIN_ID)

    await client.send_message(
        ADMIN_ID,
        f"SUPPORT MESSAGE RECEIVED\n\n"
        f"User ID: {uid}\n"
        f"Username: @{msg.from_user.username if msg.from_user.username else 'NoUsername'}\n\n"
        f"Reply using:\n"
        f"/reply {uid} your message"
    )

    await msg.reply("Support message sent to admin")

# ================= PAYMENT =================
@app.on_message(filters.photo & filters.private)
async def payment(client, msg):
    uid = msg.from_user.id

    cur.execute("""
        SELECT o.order_id, o.product_link, o.mrp, o.final_price, u.username
        FROM orders o
        JOIN users u ON u.telegram_id=o.telegram_id
        WHERE o.telegram_id=%s AND o.status='PAYMENT_WAITING'
    """, (uid,))
    row = cur.fetchone()

    if not row:
        await msg.reply("No pending order")
        return

    oid, link, mrp, price, username = row

    summary = (
        f"PAYMENT RECEIVED\n\n"
        f"Order ID: {oid}\n"
        f"User: @{username if username else 'NoUsername'}\n"
        f"User ID: {uid}\n\n"
        f"MRP: ₹{mrp}\n"
        f"Pay Amount: ₹{price}\n\n"
        f"Product:\n{link}"
    )

    await msg.forward(ADMIN_ID)
    await client.send_message(
        ADMIN_ID,
        summary,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Confirm", callback_data=f"admin_confirm:{oid}"),
                InlineKeyboardButton("Reject", callback_data=f"admin_reject:{oid}")
            ]
        ])
    )

    await client.send_message(LOG_CHANNEL_ID, summary)
    await msg.reply("Payment received. Please wait.")

# ================= RUN =================
app.run()
