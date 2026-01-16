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
DISCOUNT_PERCENT = 75  # Flat 75% OFF

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
        await msg.reply("👑 Admin mode active")
        return

    cur.execute(
        "INSERT INTO users VALUES (%s,%s) ON CONFLICT DO NOTHING",
        (msg.from_user.id, msg.from_user.username)
    )
    conn.commit()

    await msg.reply_photo(
        START_IMAGE,
        caption=(
            "👓 *Lenskart Order Bot*\n\n"
            "🔥 Flat 75% OFF\n"
            "❌ No Buy 1 Get 1\n"
            "✅ Minimum MRP ₹3000\n\n"
            "Use /help to know steps"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 New Order", callback_data="buy")],
            [InlineKeyboardButton("🆘 Support", callback_data="support")]
        ])
    )

# ================= HELP =================
@app.on_message(filters.command("help"))
async def help_cmd(client, msg):
    await msg.reply(
        "📘 *How to use this bot*\n\n"
        "1️⃣ Send Lenskart product link\n"
        "2️⃣ Send original MRP (₹3000 min)\n"
        "3️⃣ Flat 75% OFF applied\n"
        "4️⃣ Pay via QR\n"
        "5️⃣ Send payment screenshot\n\n"
        "📦 Track order: `/track ORDER_ID`\n"
        "🆘 Support: /support"
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
        await msg.reply("❌ Order not found")
        return

    await msg.reply(f"📦 Order `{oid}`\nStatus: *{row[0]}*")

# ================= ORDERS (ADMIN) =================
@app.on_message(filters.command("orders") & filters.user(ADMIN_ID))
async def orders_cmd(client, msg):
    cur.execute(
        "SELECT order_id, telegram_id, status FROM orders ORDER BY order_id DESC LIMIT 20"
    )
    rows = cur.fetchall()

    if not rows:
        await msg.reply("No orders found.")
        return

    text = "📦 *Recent Orders*\n\n"
    for oid, uid, status in rows:
        text += f"• `{oid}` | `{uid}` | *{status}*\n"

    await msg.reply(text)

# ================= BROADCAST (ADMIN) =================
@app.on_message(filters.command("broadcast") & filters.user(ADMIN_ID))
async def broadcast_start(client, msg):
    global broadcast_waiting
    broadcast_waiting = True
    await msg.reply("📢 Send the message you want to broadcast")

# ================= ADMIN SUPPORT REPLY =================
@app.on_message(filters.command("reply") & filters.user(ADMIN_ID))
async def admin_reply(client, msg):
    parts = msg.text.split(maxsplit=2)
    if len(parts) < 3:
        await msg.reply("Usage:\n/reply <user_id> <message>")
        return

    user_id = int(parts[1])
    text = parts[2]

    await client.send_message(user_id, f"📩 *Support Reply*\n\n{text}")
    await msg.reply("✅ Reply sent")

# ================= CALLBACKS =================
@app.on_callback_query()
async def callbacks(client, cb):
    uid = cb.from_user.id
    data = cb.data

    if data == "buy":
        await cb.message.reply("🔗 Send Lenskart product link")
        return

    if data == "support":
        support_waiting.add(uid)
        await cb.message.reply("🆘 Send your issue in ONE message")
        return

    if uid == ADMIN_ID and data.startswith("admin_confirm"):
        oid = data.split(":")[1]

        cur.execute("UPDATE orders SET status='CONFIRMED' WHERE order_id=%s",(oid,))
        conn.commit()

        cur.execute("""
            SELECT u.username, o.telegram_id, o.product_link, o.mrp, o.final_price
            FROM orders o
            JOIN users u ON u.telegram_id=o.telegram_id
            WHERE o.order_id=%s
        """, (oid,))
        username, user_id, link, mrp, price = cur.fetchone()

        summary = (
            "💰 *PAYMENT RECEIVED*\n\n"
            f"🆔 Order ID: `{oid}`\n"
            f"👤 User: @{username if username else 'NoUsername'}\n"
            f"🆔 User ID: `{user_id}`\n\n"
            f"💸 MRP: ₹{mrp}\n"
            f"🔥 Discount: 75% OFF\n"
            f"✅ Pay Amount: ₹{price}\n\n"
            f"🔗 Product:\n{link}"
        )

        await client.send_message(user_id, summary)
        await cb.message.edit_reply_markup(status_buttons(oid))
        return

    if uid == ADMIN_ID and data.startswith("admin_reject"):
        oid = data.split(":")[1]
        cur.execute("UPDATE orders SET status='REJECTED' WHERE order_id=%s",(oid,))
        conn.commit()

        cur.execute("SELECT telegram_id FROM orders WHERE order_id=%s",(oid,))
        user_id = cur.fetchone()[0]

        await client.send_message(
            user_id,
            "❌ Order rejected.\nRefund soon."
        )
        await cb.message.edit_reply_markup(None)
        return

    if uid == ADMIN_ID and data.startswith("status:"):
        _, status, oid = data.split(":")
        cur.execute("UPDATE orders SET status=%s WHERE order_id=%s",(status,oid))
        conn.commit()

        cur.execute("SELECT telegram_id FROM orders WHERE order_id=%s",(oid,))
        user_id = cur.fetchone()[0]

        messages = {
            "PACKED":"📦 Packed",
            "ON_THE_WAY":"🚚 On the way",
            "DELIVERED":"📬 Delivered"
        }
        await client.send_message(user_id, messages[status])
        return

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
        await msg.reply("❌ No pending order")
        return

    oid, link, mrp, price, username = row

    summary = (
        "💰 *PAYMENT RECEIVED*\n\n"
        f"🆔 Order ID: `{oid}`\n"
        f"👤 User: @{username if username else 'NoUsername'}\n"
        f"🆔 User ID: `{uid}`\n\n"
        f"💸 MRP: ₹{mrp}\n"
        f"🔥 Discount: 75% OFF\n"
        f"✅ Pay Amount: ₹{price}\n\n"
        f"🔗 Product:\n{link}"
    )

    await msg.forward(ADMIN_ID)
    await client.send_message(
        ADMIN_ID,
        summary,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Confirm Order", callback_data=f"admin_confirm:{oid}"),
                InlineKeyboardButton("❌ Reject Order", callback_data=f"admin_reject:{oid}")
            ]
        ])
    )

    await client.send_message(LOG_CHANNEL_ID, summary)
    await msg.reply("✅ Payment received. Please wait ⏳")

# ================= PRIVATE TEXT =================
@app.on_message(filters.private & ~filters.photo)
async def private_all(client, msg):
    global broadcast_waiting
    uid = msg.from_user.id

    # Broadcast flow
    if broadcast_waiting and uid == ADMIN_ID:
        broadcast_waiting = False
        cur.execute("SELECT telegram_id FROM users")
        users = cur.fetchall()
        for (u,) in users:
            try:
                await client.send_message(u, msg.text)
            except:
                pass
        await msg.reply("📢 Broadcast sent")
        return

    # Support flow
    if uid in support_waiting:
        support_waiting.discard(uid)

        await msg.forward(ADMIN_ID)
        await client.send_message(
            ADMIN_ID,
            f"🆘 SUPPORT MESSAGE\nUser ID: `{uid}`\n"
            f"Reply using `/reply {uid} <msg>`"
        )
        await msg.reply("✅ Support message sent")
        return

    # Product link
    if msg.text and "lenskart.com" in msg.text:
        mrp_waiting[uid] = msg.text
        await msg.reply_photo(MRP_HELP_IMAGE, caption="Send original MRP (₹3000 min)")
        return

    # MRP
    if uid in mrp_waiting and msg.text.isdigit():
        mrp = int(msg.text)
        link = mrp_waiting.pop(uid)

        if mrp < MIN_MRP:
            await msg.reply("❌ Minimum MRP ₹3000 required")
            return

        price = int(mrp * (100 - DISCOUNT_PERCENT) / 100)
        oid = str(uuid.uuid4())[:8]

        cur.execute(
            "INSERT INTO orders VALUES (%s,%s,%s,%s,%s,%s)",
            (oid, uid, link, mrp, price, "PAYMENT_WAITING")
        )
        conn.commit()

        await msg.reply_photo(
            QR_IMAGE,
            caption=f"🆔 {oid}\nPay ₹{price}\nSend screenshot"
        )

# ================= RUN =================
app.run()
