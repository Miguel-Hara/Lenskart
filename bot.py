from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
import os, uuid, psycopg2
import pyrogram.utils

pyrogram.utils.MIN_CHANNEL_ID = -1009147483647

# ================= ENV =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
DATABASE_URL = os.getenv("DATABASE_URL")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))

# ================= BUSINESS =================
MIN_MRP = 3000
DISCOUNT_PERCENT = 75

# ================= IMAGES =================
START_IMAGE = "https://files.catbox.moe/5t348b.jpg"
MRP_HELP_IMAGE = "https://files.catbox.moe/orp6r5.jpg"

# ================= BOT =================
app = Client(
    "lenskart_order_bot",
    bot_token=BOT_TOKEN,
    api_id=API_ID,
    api_hash=API_HASH,
    parse_mode=ParseMode.HTML
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

cur.execute("""
SELECT column_name FROM information_schema.columns
WHERE table_name='orders' AND column_name='lens_type'
""")
if not cur.fetchone():
    cur.execute("ALTER TABLE orders ADD COLUMN lens_type TEXT")

conn.commit()

# ================= STATES =================
support_waiting = set()
order_state = {}

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
        await msg.reply("👑 <b>Admin mode active</b>\n<i>Use admin commands only</i>")
        return

    cur.execute(
        "INSERT INTO users (telegram_id, username) VALUES (%s,%s) ON CONFLICT DO NOTHING",
        (msg.from_user.id, msg.from_user.username)
    )
    conn.commit()

    await msg.reply_photo(
        START_IMAGE,
        caption=(
            "🕶️ <b>Lenskart Order Bot</b>\n\n"
            "💥 <b>Flat 75% OFF + ₹1 extra</b>\n"
            "<i>75% discount + ₹1 aur kam</i>\n\n"
            "💸 <b>No advance payment</b>\n"
            "<i>Koi advance payment nahi</i>\n\n"
            "👇 <b>Choose an option below</b>\n"
            "<i>Neeche option select karein</i>"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 New Order", callback_data="buy")],
            [InlineKeyboardButton("🆘 Support", callback_data="support")]
        ])
    )

# ================= HELP =================
@app.on_message(filters.command("help"))
async def help_cmd(client, msg):
    if msg.from_user.id == ADMIN_ID:
        return

    await msg.reply(
        "🆘 <b>HELP & GUIDE</b>\n\n"
        "🛒 <b>How to place an order</b>\n"
        "• Send Lenskart product link\n"
        "• Send original MRP (₹3000+)\n"
        "• Type lens type\n"
        "• Send power image (or any image)\n\n"
        "📦 <b>Order tracking</b>\n"
        "Use <code>/track ORDER_ID</code>\n\n"
        "🆘 <b>Support</b>\n"
        "Use <code>/support</code> and send your issue\n\n"
        "👨‍💼 <b>Admin</b>\n"
        "Admin will confirm, update & contact you\n\n"
        "<i>Simple • Fast • Trusted</i>"
    )

# ================= SUPPORT =================
@app.on_message(filters.command("support"))
async def support(client, msg):
    if msg.from_user.id == ADMIN_ID:
        return

    support_waiting.add(msg.from_user.id)
    await msg.reply(
        "🆘 <b>Support</b>\n\n"
        "Send your issue in ONE message.\n"
        "<i>Apni problem ek hi message mein bhejein</i>"
    )

# ================= TRACK =================
@app.on_message(filters.command("track"))
async def track(client, msg):
    if msg.from_user.id == ADMIN_ID:
        return

    if len(msg.command) != 2:
        await msg.reply("Usage: <code>/track ORDER_ID</code>")
        return

    oid = msg.command[1]
    cur.execute(
        "SELECT status FROM orders WHERE order_id=%s AND telegram_id=%s",
        (oid, msg.from_user.id)
    )
    row = cur.fetchone()

    if not row:
        await msg.reply("❌ <b>Order not found</b>")
        return

    await msg.reply(
        f"📦 <b>Order ID:</b> <code>{oid}</code>\n"
        f"📍 <b>Status:</b> {row[0]}"
    )

# ================= ADMIN REPLY =================
@app.on_message(filters.command("reply") & filters.user(ADMIN_ID))
async def admin_reply(client, msg):
    parts = msg.text.split(maxsplit=2)
    if len(parts) < 3:
        await msg.reply("Usage: /reply USER_ID message")
        return

    await client.send_message(int(parts[1]), parts[2])
    await msg.reply("✅ Reply sent")

# ================= CALLBACKS =================
@app.on_callback_query()
async def callbacks(client, cb):
    uid = cb.from_user.id
    data = cb.data

    if uid == ADMIN_ID and not data.startswith(("admin_", "status:")):
        await cb.answer("Admin mode", show_alert=True)
        return

    if data == "buy":
        await cb.message.reply("🔗 Send Lenskart product link")
        return

    if data == "support":
        support_waiting.add(uid)
        await cb.message.reply("🆘 Send your issue in ONE message")
        return

    if data == "no_power":
        await send_to_admin(client, cb.from_user, uid, power_provided=False)
        await cb.message.reply(
            "✅ Order details sent.\n"
            "<i>Admin will contact you soon</i>"
        )
        return

    if uid == ADMIN_ID and data.startswith("admin_confirm:"):
        oid = data.split(":")[1]
        cur.execute("UPDATE orders SET status='CONFIRMED' WHERE order_id=%s", (oid,))
        conn.commit()

        cur.execute("SELECT telegram_id FROM orders WHERE order_id=%s", (oid,))
        user_id = cur.fetchone()[0]

        await client.send_message(user_id, "✅ <b>Order confirmed by admin</b>")
        await cb.message.edit_reply_markup(status_buttons(oid))
        return

    if uid == ADMIN_ID and data.startswith("admin_reject:"):
        oid = data.split(":")[1]
        cur.execute("UPDATE orders SET status='REJECTED' WHERE order_id=%s", (oid,))
        conn.commit()

        cur.execute("SELECT telegram_id FROM orders WHERE order_id=%s", (oid,))
        user_id = cur.fetchone()[0]

        await client.send_message(user_id, "❌ <b>Order rejected</b>")
        await cb.message.edit_reply_markup(None)
        return

    if uid == ADMIN_ID and data.startswith("status:"):
        _, status, oid = data.split(":")
        cur.execute("UPDATE orders SET status=%s WHERE order_id=%s", (status, oid))
        conn.commit()

        cur.execute("SELECT telegram_id FROM orders WHERE order_id=%s", (oid,))
        user_id = cur.fetchone()[0]

        await client.send_message(
            user_id,
            {
                "PACKED": "📦 <b>Order packed</b>",
                "ON_THE_WAY": "🚚 <b>Order on the way</b>",
                "DELIVERED": "📬 <b>Order delivered</b>"
            }[status]
        )

# ================= POWER PHOTO =================
@app.on_message(filters.photo & filters.private)
async def power_photo(client, msg):
    uid = msg.from_user.id
    if uid == ADMIN_ID:
        return

    if uid in order_state and "lens" in order_state[uid]:
        await msg.forward(ADMIN_ID)
        await send_to_admin(client, msg.from_user, uid, power_provided=True)
        await msg.reply(
            "✅ <b>Image received</b>\n"
            "<i>Admin will contact you soon</i>"
        )

# ================= PRIVATE TEXT =================
@app.on_message(filters.private & filters.text)
async def private_text(client, msg):
    uid = msg.from_user.id
    text = msg.text.strip()

    if uid == ADMIN_ID:
        return

    if uid in support_waiting:
        support_waiting.discard(uid)

        await msg.forward(ADMIN_ID)
        await client.send_message(
            ADMIN_ID,
            f"📨 <b>SUPPORT MESSAGE RECEIVED</b>\n\n"
            f"User ID: <code>{uid}</code>\n"
            f"Username: @{msg.from_user.username or 'NoUsername'}\n\n"
            f"Reply using:\n"
            f"<code>/reply {uid} your message</code>"
        )

        await msg.reply("✅ <b>Support message sent</b>")
        return

    if "lenskart.com" in text:
        order_state[uid] = {"link": text}
        await msg.reply_photo(
            MRP_HELP_IMAGE,
            caption=(
                "📌 <b>Send ORIGINAL MRP</b>\n\n"
                "• Type only number (example: 3999)\n"
                "• Minimum ₹3000"
            )
        )
        return

    if uid in order_state and "mrp" not in order_state[uid] and text.isdigit():
        mrp = int(text)
        if mrp < MIN_MRP:
            await msg.reply("❌ <b>Minimum MRP ₹3000</b>")
            return

        price = max(1, int(mrp * (100 - DISCOUNT_PERCENT) / 100) - 1)
        order_state[uid].update({"mrp": mrp, "price": price})

        await msg.reply(
            "✍️ <b>Type your Lens Type</b>\n\n"
            "Example:\n• Single Vision\n• Blue Cut\n• Progressive"
        )
        return

    if uid in order_state and "mrp" in order_state[uid] and "lens" not in order_state[uid]:
        order_state[uid]["lens"] = text
        await msg.reply(
            "📄 <b>Send power screenshot</b>\n"
            "<i>If not available, send any image</i>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ I don’t have a power", callback_data="no_power")]
            ])
        )

# ================= SEND TO ADMIN =================
async def send_to_admin(client, user, uid, power_provided: bool):
    info = order_state.pop(uid)
    oid = str(uuid.uuid4())[:8]

    cur.execute(
        """
        INSERT INTO orders
        (order_id, telegram_id, product_link, lens_type, mrp, final_price, status)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        """,
        (oid, uid, info["link"], info["lens"], info["mrp"], info["price"], "PENDING_ADMIN")
    )
    conn.commit()

    power_text = "Provided" if power_provided else "Not provided"

    admin_msg = (
        "💰 <b>PAYMENT RECEIVED</b>\n\n"
        f"Order ID: {oid}\n"
        f"User: @{user.username or 'NoUsername'}\n"
        f"User ID: {uid}\n\n"
        f"Lens Type: {info['lens']}\n"
        f"Power: {power_text}\n"
        f"MRP: ₹{info['mrp']}\n"
        f"Pay Amount: ₹{info['price']}\n\n"
        f"Product:\n{info['link']}"
    )

    await client.send_message(
        ADMIN_ID,
        admin_msg,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Confirm", callback_data=f"admin_confirm:{oid}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"admin_reject:{oid}")
            ]
        ])
    )

    await client.send_message(LOG_CHANNEL_ID, admin_msg)

# ================= RUN =================
app.run()
