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
            "🔥 *Flat 75% OFF*\n"
            "❌ No Buy 1 Get 1\n"
            "✅ Minimum MRP ₹3000\n\n"
            "1️⃣ Send product link\n"
            "2️⃣ Send original MRP\n"
            "3️⃣ Pay discounted amount\n"
            "4️⃣ Get updates 📦"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 New Order", callback_data="buy")],
            [InlineKeyboardButton("🆘 Support", callback_data="support")]
        ])
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

# ================= ADMIN SUPPORT REPLY =================
@app.on_message(filters.command("reply") & filters.user(ADMIN_ID))
async def admin_reply(client, msg):
    parts = msg.text.split(maxsplit=2)
    if len(parts) < 3:
        await msg.reply("Usage:\n/reply <user_id> <message>")
        return

    user_id = int(parts[1])
    text = parts[2]

    await client.send_message(
        user_id,
        f"📩 *Support Reply*\n\n{text}"
    )
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

    # ---------- CONFIRM ----------
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

        # send same summary to user
        await client.send_message(user_id, summary)

        # keep buttons for admin
        await cb.message.edit_reply_markup(status_buttons(oid))
        await cb.answer("Order confirmed")
        return

    # ---------- REJECT ----------
    if uid == ADMIN_ID and data.startswith("admin_reject"):
        oid = data.split(":")[1]

        cur.execute("UPDATE orders SET status='REJECTED' WHERE order_id=%s",(oid,))
        conn.commit()

        cur.execute("SELECT telegram_id FROM orders WHERE order_id=%s",(oid,))
        user_id = cur.fetchone()[0]

        await client.send_message(
            user_id,
            "❌ Order rejected.\n💸 Refund original payment method par soon aa jaayega."
        )
        await cb.message.edit_reply_markup(None)
        return

    # ---------- STATUS ----------
    if uid == ADMIN_ID and data.startswith("status:"):
        _, status, oid = data.split(":")
        cur.execute("UPDATE orders SET status=%s WHERE order_id=%s",(status,oid))
        conn.commit()

        cur.execute("SELECT telegram_id FROM orders WHERE order_id=%s",(oid,))
        user_id = cur.fetchone()[0]

        messages = {
            "PACKED":"📦 Order packed",
            "ON_THE_WAY":"🚚 Order on the way",
            "DELIVERED":"📬 Order delivered 🎉"
        }
        await client.send_message(user_id, messages[status])
        return

# ================= PAYMENT SCREENSHOT =================
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
        await msg.reply("❌ No pending order found")
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

    await msg.reply(
        "✅ Payment mil gaya hai.\n"
        "⏳ Verification ke baad update yahin milega."
    )

# ================= PRIVATE TEXT =================
@app.on_message(filters.private & ~filters.photo)
async def private_all(client, msg):
    uid = msg.from_user.id

    if uid in support_waiting:
        support_waiting.discard(uid)

        await msg.forward(ADMIN_ID)
        await client.send_message(
            ADMIN_ID,
            f"🆘 *SUPPORT MESSAGE RECEIVED*\n\n"
            f"👤 User ID: `{uid}`\n"
            f"📌 Username: @{msg.from_user.username if msg.from_user.username else 'NoUsername'}\n\n"
            "Reply using:\n"
            f"`/reply {uid} <your message>`"
        )

        await msg.reply("✅ Support message sent to admin")
        return

    if msg.text and "lenskart.com" in msg.text:
        mrp_waiting[uid] = msg.text
        await msg.reply_photo(
            MRP_HELP_IMAGE,
            caption=(
                "🧾 Send ONLY original MRP\n\n"
                "❌ Discounted price mat bhejo\n"
                "✅ Minimum MRP ₹3000"
            )
        )
        return

    if uid in mrp_waiting and msg.text.isdigit():
        mrp = int(msg.text)
        link = mrp_waiting.pop(uid)

        if mrp < MIN_MRP:
            await msg.reply(
                "❌ *Order not accepted*\n\n"
                "Minimum product MRP ₹3000 hona chahiye."
            )
            return

        final_price = int(mrp * (100 - DISCOUNT_PERCENT) / 100)
        oid = str(uuid.uuid4())[:8]

        cur.execute(
            "INSERT INTO orders VALUES (%s,%s,%s,%s,%s,%s)",
            (oid, uid, link, mrp, final_price, "PAYMENT_WAITING")
        )
        conn.commit()

        await msg.reply_photo(
            QR_IMAGE,
            caption=(
                f"💳 *Payment Details*\n\n"
                f"🆔 Order ID: `{oid}`\n"
                f"💸 MRP: ₹{mrp}\n"
                f"🔥 Discount: 75% OFF\n"
                f"✅ Pay Amount: ₹{final_price}\n\n"
                "QR scan karke payment karo.\n"
                "Screenshot bhejo 📸"
            )
        )

# ================= RUN =================
app.run()
