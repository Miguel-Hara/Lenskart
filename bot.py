from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
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
    cur.execute(
        "INSERT INTO users VALUES (%s,%s) ON CONFLICT DO NOTHING",
        (msg.from_user.id, msg.from_user.username)
    )
    conn.commit()

    await msg.reply_photo(
        START_IMAGE,
        caption=(
            "🕶️ <b>Lenskart Order Bot</b>\n\n"
            "💥 <b>Flat 75% OFF + ₹1 extra</b>\n"
            "<i>75% discount milega + ₹1 aur kam</i>\n\n"
            "💸 <b>No advance payment required</b>\n"
            "<i>Koi advance payment nahi deni hogi</i>\n\n"
            "👇 <b>Please choose an option below</b>\n"
            "<i>Neeche option select karein</i>"
        ),
        parse_mode="html",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 New Order", callback_data="buy")],
            [InlineKeyboardButton("🆘 Support", callback_data="support")]
        ])
    )

# ================= SUPPORT =================
@app.on_message(filters.command("support"))
async def support(client, msg):
    support_waiting.add(msg.from_user.id)
    await msg.reply(
        "🆘 <b>Support</b>\n\n"
        "Please send your issue in ONE message.\n"
        "<i>Apni problem ek hi message mein bhejein.</i>",
        parse_mode="html"
    )

# ================= TRACK =================
@app.on_message(filters.command("track"))
async def track(client, msg):
    if len(msg.command) != 2:
        await msg.reply(
            "Usage: <code>/track ORDER_ID</code>\n"
            "<i>Istemaal: /track ORDER_ID</i>",
            parse_mode="html"
        )
        return

    oid = msg.command[1]
    cur.execute(
        "SELECT status FROM orders WHERE order_id=%s AND telegram_id=%s",
        (oid, msg.from_user.id)
    )
    row = cur.fetchone()

    if not row:
        await msg.reply(
            "❌ <b>Order not found</b>\n"
            "<i>Order nahi mila</i>",
            parse_mode="html"
        )
        return

    await msg.reply(
        f"📦 <b>Order ID:</b> <code>{oid}</code>\n"
        f"📍 <b>Status:</b> {row[0]}",
        parse_mode="html"
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

    if data == "buy":
        await cb.message.reply(
            "🔗 <b>Please send the Lenskart product link</b>\n"
            "<i>Lenskart ka product link bhejein</i>",
            parse_mode="html"
        )
        return

    if data == "support":
        support_waiting.add(uid)
        await cb.message.reply(
            "🆘 Send your issue in one message\n"
            "<i>Apni problem ek message mein likhein</i>",
            parse_mode="html"
        )
        return

    if uid == ADMIN_ID and data.startswith("admin_confirm:"):
        oid = data.split(":")[1]
        cur.execute("UPDATE orders SET status='CONFIRMED' WHERE order_id=%s", (oid,))
        conn.commit()

        cur.execute("SELECT telegram_id FROM orders WHERE order_id=%s", (oid,))
        user_id = cur.fetchone()[0]

        await client.send_message(
            user_id,
            "✅ <b>Your order has been confirmed</b>\n"
            "<i>Aapka order confirm ho gaya hai</i>",
            parse_mode="html"
        )
        await cb.message.edit_reply_markup(status_buttons(oid))
        return

    if uid == ADMIN_ID and data.startswith("admin_reject:"):
        oid = data.split(":")[1]
        cur.execute("UPDATE orders SET status='REJECTED' WHERE order_id=%s", (oid,))
        conn.commit()

        cur.execute("SELECT telegram_id FROM orders WHERE order_id=%s", (oid,))
        user_id = cur.fetchone()[0]

        await client.send_message(
            user_id,
            "❌ <b>Your order was rejected</b>\n"
            "<i>Aapka order reject kar diya gaya hai</i>",
            parse_mode="html"
        )
        await cb.message.edit_reply_markup(None)
        return

# ================= POWER PHOTO =================
@app.on_message(filters.photo & filters.private)
async def power_photo(client, msg):
    uid = msg.from_user.id
    if uid in order_state and "lens" in order_state[uid]:
        await msg.forward(ADMIN_ID)
        await send_to_admin(client, msg.from_user, uid)
        await msg.reply(
            "✅ <b>Image received successfully</b>\n"
            "<i>Image mil gayi hai</i>\n\n"
            "📞 Admin will contact you soon\n"
            "<i>Admin aapse jaldi contact karega</i>",
            parse_mode="html"
        )

# ================= PRIVATE TEXT =================
@app.on_message(filters.private & filters.text)
async def private_text(client, msg):
    uid = msg.from_user.id
    text = msg.text.strip()

    if uid in support_waiting:
        support_waiting.discard(uid)
        await msg.forward(ADMIN_ID)
        await msg.reply(
            "✅ Support message sent\n"
            "<i>Support message bhej diya gaya hai</i>",
            parse_mode="html"
        )
        return

    if "lenskart.com" in text:
        order_state[uid] = {"link": text}
        await msg.reply_photo(
            MRP_HELP_IMAGE,
            caption=(
                "📌 <b>Send the ORIGINAL MRP</b>\n"
                "<i>Original MRP bhejein</i>\n\n"
                "• Type only numbers (example: <code>3999</code>)\n"
                "<i>Sirf number likhein</i>\n"
                "• Minimum ₹3000 required\n"
                "<i>Minimum ₹3000 hona chahiye</i>"
            ),
            parse_mode="html"
        )
        return

    if uid in order_state and "mrp" not in order_state[uid] and text.isdigit():
        mrp = int(text)
        if mrp < MIN_MRP:
            await msg.reply(
                "❌ <b>Minimum MRP must be ₹3000</b>\n"
                "<i>Minimum MRP ₹3000 hona chahiye</i>",
                parse_mode="html"
            )
            return

        price = max(1, int(mrp * (100 - DISCOUNT_PERCENT) / 100) - 1)
        order_state[uid].update({"mrp": mrp, "price": price})

        await msg.reply(
            "✍️ <b>Please type your Lens Type</b>\n"
            "<i>Apna lens type likhein</i>\n\n"
            "Example:\n• Single Vision\n• Blue Cut\n• Progressive",
            parse_mode="html"
        )
        return

    if uid in order_state and "mrp" in order_state[uid] and "lens" not in order_state[uid]:
        order_state[uid]["lens"] = text
        await msg.reply(
            "📄 <b>Please send your power screenshot</b>\n"
            "<i>Agar power nahi hai to koi bhi image bhej sakte hain</i>",
            parse_mode="html"
        )

# ================= SEND TO ADMIN =================
async def send_to_admin(client, user, uid):
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

    admin_msg = (
        "💰 <b>ORDER RECEIVED</b>\n\n"
        f"<b>Order ID:</b> {oid}\n"
        f"<b>User:</b> @{user.username or 'NoUsername'}\n"
        f"<b>User ID:</b> {uid}\n\n"
        f"<b>Lens Type:</b> {info['lens']}\n"
        f"<b>MRP:</b> ₹{info['mrp']}\n"
        f"<b>Pay Amount:</b> ₹{info['price']}\n\n"
        f"<b>Product Link:</b>\n{info['link']}"
    )

    await client.send_message(
        ADMIN_ID,
        admin_msg,
        parse_mode="html",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Confirm", callback_data=f"admin_confirm:{oid}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"admin_reject:{oid}")
            ]
        ])
    )

    await client.send_message(LOG_CHANNEL_ID, admin_msg, parse_mode="html")

# ================= RUN =================
app.run()
