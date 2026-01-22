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
DISCOUNT_PERCENT = 75  # 75% OFF + ₹1 extra

# ================= IMAGES =================
START_IMAGE = "https://files.catbox.moe/5t348b.jpg"
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

# USERS
cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    telegram_id BIGINT PRIMARY KEY,
    username TEXT
)
""")

# ORDERS (explicit columns – safe)
cur.execute("""
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    telegram_id BIGINT,
    product_link TEXT,
    lens_type TEXT,
    mrp INTEGER,
    final_price INTEGER,
    status TEXT
)
""")
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
    cur.execute(
        "INSERT INTO users (telegram_id, username) VALUES (%s,%s) ON CONFLICT DO NOTHING",
        (msg.from_user.id, msg.from_user.username)
    )
    conn.commit()

    await msg.reply_photo(
        START_IMAGE,
        caption=(
            "🕶️ *Lenskart Order Bot*\n\n"
            "• Flat 75% OFF + ₹1 extra\n"
            "• No advance payment\n"
            "• Admin assisted ordering\n\n"
            "Choose an option ⬇️"
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
        "How to order:\n\n"
        "1. Send Lenskart product link\n"
        "2. Send ORIGINAL MRP (₹3000+)\n"
        "3. Type lens type\n"
        "4. Send power screenshot or skip\n\n"
        "Track: /track ORDER_ID\n"
        "Support: /support"
    )

# ================= SUPPORT =================
@app.on_message(filters.command("support"))
async def support_cmd(client, msg):
    support_waiting.add(msg.from_user.id)
    await msg.reply("🆘 Send your issue in ONE message")

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

    await msg.reply(f"📦 Order ID: `{oid}`\n📍 Status: {row[0]}")

# ================= ADMIN REPLY (RESTORED) =================
@app.on_message(filters.command("reply") & filters.user(ADMIN_ID))
async def admin_reply(client, msg):
    parts = msg.text.split(maxsplit=2)
    if len(parts) < 3:
        await msg.reply("Usage: /reply USER_ID message")
        return

    user_id = int(parts[1])
    text = parts[2]

    await client.send_message(user_id, text)
    await msg.reply("✅ Reply sent")

# ================= CALLBACKS =================
@app.on_callback_query()
async def callbacks(client, cb):
    uid = cb.from_user.id
    data = cb.data

    # USER
    if data == "buy":
        await cb.message.reply("🔗 Send Lenskart product link")
        return

    if data == "support":
        support_waiting.add(uid)
        await cb.message.reply("🆘 Send your issue in ONE message")
        return

    # NO POWER
    if data == "no_power":
        await send_to_admin(client, cb.from_user, uid, power_provided=False)
        await cb.message.reply(
            "✅ Order details sent.\n\n"
            "Admin will contact you soon,\n"
            "be ready with your money Hehehe..."
        )
        return

    # ADMIN CONFIRM
    if uid == ADMIN_ID and data.startswith("admin_confirm:"):
        oid = data.split(":")[1]
        cur.execute("UPDATE orders SET status='CONFIRMED' WHERE order_id=%s", (oid,))
        conn.commit()

        cur.execute("SELECT telegram_id FROM orders WHERE order_id=%s", (oid,))
        user_id = cur.fetchone()[0]

        await client.send_message(user_id, "✅ Order confirmed by admin.")
        await cb.message.edit_reply_markup(status_buttons(oid))
        return

    # ADMIN REJECT
    if uid == ADMIN_ID and data.startswith("admin_reject:"):
        oid = data.split(":")[1]
        cur.execute("UPDATE orders SET status='REJECTED' WHERE order_id=%s", (oid,))
        conn.commit()

        cur.execute("SELECT telegram_id FROM orders WHERE order_id=%s", (oid,))
        user_id = cur.fetchone()[0]

        await client.send_message(user_id, "❌ Order rejected. Admin will contact you.")
        await cb.message.edit_reply_markup(None)
        return

    # STATUS UPDATE
    if uid == ADMIN_ID and data.startswith("status:"):
        _, status, oid = data.split(":")
        cur.execute("UPDATE orders SET status=%s WHERE order_id=%s", (status, oid))
        conn.commit()

        cur.execute("SELECT telegram_id FROM orders WHERE order_id=%s", (oid,))
        user_id = cur.fetchone()[0]

        await client.send_message(
            user_id,
            {
                "PACKED": "📦 Your order has been packed",
                "ON_THE_WAY": "🚚 Your order is on the way",
                "DELIVERED": "📬 Your order has been delivered"
            }[status]
        )
        return

# ================= POWER PHOTO =================
@app.on_message(filters.photo & filters.private)
async def power_photo(client, msg):
    uid = msg.from_user.id

    if uid in order_state and order_state[uid].get("lens"):
        await msg.forward(ADMIN_ID)
        await send_to_admin(client, msg.from_user, uid, power_provided=True)

        await msg.reply(
            "✅ Power received successfully.\n\n"
            "Admin will contact you soon,\n"
            "be ready with your money Hehehe..."
        )

# ================= PRIVATE TEXT =================
@app.on_message(filters.private & filters.text)
async def private_text(client, msg):
    uid = msg.from_user.id
    text = msg.text.strip()

    # Support
    if uid in support_waiting:
        support_waiting.discard(uid)
        await msg.forward(ADMIN_ID)
        await msg.reply("✅ Support message sent")
        return

    # Product link
    if "lenskart.com" in text:
        order_state[uid] = {"link": text}
        await msg.reply_photo(
            MRP_HELP_IMAGE,
            caption=(
                "📌 *Send ORIGINAL MRP*\n\n"
                "• Check product page\n"
                "• Type only number (example: 3999)\n"
                "• Minimum ₹3000"
            )
        )
        return

    # MRP
    if uid in order_state and "mrp" not in order_state[uid] and text.isdigit():
        mrp = int(text)
        if mrp < MIN_MRP:
            await msg.reply("❌ Minimum MRP ₹3000")
            return

        price = max(1, int(mrp * (100 - DISCOUNT_PERCENT) / 100) - 1)
        order_state[uid].update({"mrp": mrp, "price": price})

        await msg.reply(
            "✍️ *Type your Lens Type*\n\n"
            "Example:\n"
            "• Single Vision\n"
            "• Blue Cut\n"
            "• Progressive"
        )
        return

    # Lens type
    if uid in order_state and "mrp" in order_state[uid] and "lens" not in order_state[uid]:
        order_state[uid]["lens"] = text

        await msg.reply(
            "📄 *Send the screenshot of your POWER*\n\n"
            "If you don’t have power, click below.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ I don’t have a power", callback_data="no_power")]
            ])
        )
        return

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

    power_text = "Provided (see image above)" if power_provided else "Not provided"

    admin_msg = (
        "PAYMENT RECEIVED\n\n"
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
