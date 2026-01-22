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

# ================= STATES =================
support_waiting = set()
price_preview = {}

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
            "🕶️ *Lenskart Order Bot*\n\n"
            "• Flat 75% OFF + ₹1 extra discount\n"
            "• Order tracking\n"
            "• Direct support\n\n"
            "Choose an option below ⬇️"
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
        "📖 *How to Order*\n\n"
        "1️⃣ Send Lenskart product link\n"
        "2️⃣ Send ORIGINAL MRP (₹3000+)\n"
        "3️⃣ Check price & confirm\n"
        "4️⃣ Pay via QR (or skip)\n"
        "5️⃣ Send screenshot / any image\n\n"
        "📦 Track: /track ORDER_ID\n"
        "🆘 Support: /support"
    )

# ================= SUPPORT =================
@app.on_message(filters.command("support") & filters.private)
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

# ================= CALLBACKS =================
@app.on_callback_query()
async def callbacks(client, cb):
    uid = cb.from_user.id
    data = cb.data

    # ---------- USER ----------
    if data == "buy":
        await cb.message.reply("🔗 Send Lenskart product link")
        return

    if data == "support":
        support_waiting.add(uid)
        await cb.message.reply("🆘 Send your issue in ONE message")
        return

    # ---------- CONFIRM BUY ----------
    if data == "confirm_buy":
        if uid not in price_preview:
            await cb.answer("Session expired. Start again.", show_alert=True)
            return

        info = price_preview.pop(uid)
        oid = str(uuid.uuid4())[:8]

        cur.execute(
            "INSERT INTO orders VALUES (%s,%s,%s,%s,%s,%s)",
            (oid, uid, info["link"], info["mrp"], info["price"], "PAYMENT_WAITING")
        )
        conn.commit()

        await cb.message.reply_photo(
            QR_IMAGE,
            caption=(
                f"🧾 *Order Created*\n\n"
                f"Order ID: `{oid}`\n"
                f"Pay Amount: ₹{info['price']}\n\n"
                "📸 You can send payment screenshot\n"
                "OR send any image if you don’t want to pay now.\n\n"
                "📞 Admin will contact you once order details are received."
            )
        )
        return

    # ---------- CHECK ANOTHER ----------
    if data == "new_check":
        price_preview.pop(uid, None)
        await cb.message.reply("🔗 Send another Lenskart product link")
        return

    # ---------- ADMIN CONFIRM ----------
    if uid == ADMIN_ID and data.startswith("admin_confirm:"):
        oid = data.split(":")[1]

        cur.execute("UPDATE orders SET status='CONFIRMED' WHERE order_id=%s", (oid,))
        conn.commit()

        cur.execute("""
            SELECT o.telegram_id, o.product_link, o.mrp, o.final_price, u.username
            FROM orders o
            JOIN users u ON u.telegram_id=o.telegram_id
            WHERE o.order_id=%s
        """, (oid,))
        user_id, link, mrp, price, username = cur.fetchone()

        await client.send_message(
            user_id,
            f"✅ PAYMENT CONFIRMED\n\nOrder ID: {oid}\nMRP: ₹{mrp}\nPaid: ₹{price}\n\nYour order is being processed."
        )

        await cb.message.edit_reply_markup(status_buttons(oid))
        await cb.answer("Order confirmed")
        return

    # ---------- ADMIN REJECT ----------
    if uid == ADMIN_ID and data.startswith("admin_reject:"):
        oid = data.split(":")[1]

        cur.execute("UPDATE orders SET status='REJECTED' WHERE order_id=%s", (oid,))
        conn.commit()

        cur.execute("SELECT telegram_id FROM orders WHERE order_id=%s", (oid,))
        user_id = cur.fetchone()[0]

        await client.send_message(
            user_id,
            "❌ PAYMENT REJECTED\n\nAdmin will contact you shortly."
        )

        await cb.message.edit_reply_markup(None)
        await cb.answer("Order rejected")
        return

    # ---------- STATUS UPDATE ----------
    if uid == ADMIN_ID and data.startswith("status:"):
        _, status, oid = data.split(":")

        cur.execute("UPDATE orders SET status=%s WHERE order_id=%s", (status, oid))
        conn.commit()

        cur.execute("SELECT telegram_id FROM orders WHERE order_id=%s", (oid,))
        user_id = cur.fetchone()[0]

        messages = {
            "PACKED": "📦 Your order has been packed",
            "ON_THE_WAY": "🚚 Your order is on the way",
            "DELIVERED": "📬 Your order has been delivered"
        }

        await client.send_message(user_id, messages[status])
        await cb.answer("Status updated")
        return

# ================= PAYMENT / IMAGE =================
@app.on_message(filters.photo & filters.private)
async def payment(client, msg):
    cur.execute("""
        SELECT order_id, product_link, mrp, final_price
        FROM orders WHERE telegram_id=%s AND status='PAYMENT_WAITING'
    """, (msg.from_user.id,))
    row = cur.fetchone()

    if not row:
        await msg.reply("❌ No pending order")
        return

    oid, link, mrp, price = row

    summary = (
        "PAYMENT RECEIVED\n\n"
        f"Order ID: {oid}\n"
        f"User: @{msg.from_user.username or 'NoUsername'}\n"
        f"User ID: {msg.from_user.id}\n\n"
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
                InlineKeyboardButton("✅ Confirm", callback_data=f"admin_confirm:{oid}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"admin_reject:{oid}")
            ]
        ])
    )

    await client.send_message(LOG_CHANNEL_ID, summary)
    await msg.reply("⏳ Order details sent to admin. Please wait.")

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
        price_preview[uid] = {"link": text}
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

    # MRP input
    if uid in price_preview and text.isdigit():
        mrp = int(text)

        if mrp < MIN_MRP:
            await msg.reply("❌ Minimum MRP ₹3000")
            return

        price = max(1, int(mrp * (100 - DISCOUNT_PERCENT) / 100) - 1)

        price_preview[uid].update({"mrp": mrp, "price": price})

        await msg.reply(
            f"💰 *Price Calculated*\n\n"
            f"MRP: ₹{mrp}\n"
            f"Your Price: ₹{price}\n\n"
            "Choose an option:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 Buy this product", callback_data="confirm_buy")],
                [InlineKeyboardButton("🔁 Check another product", callback_data="new_check")]
            ])
        )
        return

    await msg.reply("ℹ️ Use buttons or /help")

# ================= RUN =================
app.run()
