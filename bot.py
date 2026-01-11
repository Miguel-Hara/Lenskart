from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import os
import uuid
import psycopg2

# ==================================================
# ENV VARIABLES
# ==================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
DATABASE_URL = os.getenv("DATABASE_URL")

START_IMAGE = "https://files.catbox.moe/5t348b.jpg"
QR_IMAGE = "https://files.catbox.moe/r0ldyf.jpg"
MRP_HELP_IMAGE = "https://files.catbox.moe/orp6r5.jpg"

# ==================================================
# BOT INIT
# ==================================================
app = Client(
    "lenskart_order_bot",
    bot_token=BOT_TOKEN,
    api_id=API_ID,
    api_hash=API_HASH
)

# ==================================================
# DATABASE
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
# STATES
# ==================================================
support_waiting = set()
price_waiting = set()
order_waiting = set()
mrp_waiting = {}      # user_id -> product_link
support_map = {}      # admin_msg_id -> user_id

# ==================================================
# PRICE SLABS
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
    for low, high, p in slabs:
        if low <= mrp <= high:
            return p
    return None

# ==================================================
# START
# ==================================================
@app.on_message(filters.command("start"))
async def start_handler(client, msg):
    if msg.from_user.id == ADMIN_ID:
        await msg.reply("👑 Admin panel active.")
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
            "Order original Lenskart frames at discounted prices.\n"
            "Choose an option below 👇"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Price Check", callback_data="price")],
            [InlineKeyboardButton("🛒 Buy New Item", callback_data="buy")],
            [InlineKeyboardButton("🆘 Support", callback_data="support")]
        ])
    )

# ==================================================
# CALLBACK HANDLER (USER + ADMIN)
# ==================================================
@app.on_callback_query()
async def callback_handler(client, cb):
    uid = cb.from_user.id

    # ---------- ADMIN CONFIRM / REJECT ----------
    if uid == ADMIN_ID and cb.data.startswith("admin_"):
        action, oid = cb.data.split(":")
        status = "CONFIRMED" if action == "admin_confirm" else "REJECTED"

        cur.execute(
            "UPDATE orders SET status=%s WHERE order_id=%s",
            (status, oid)
        )
        conn.commit()

        cur.execute("""
            SELECT 
                orders.telegram_id,
                orders.product_link,
                orders.mrp,
                orders.final_price,
                users.username
            FROM orders
            LEFT JOIN users ON users.telegram_id = orders.telegram_id
            WHERE orders.order_id = %s
        """, (oid,))
        data = cur.fetchone()

        if not data:
            await cb.answer("Order not found", show_alert=True)
            return

        user_id, link, mrp, final_price, username = data
        username = f"@{username}" if username else "Not set"

        # Notify user
        if status == "CONFIRMED":
            await client.send_message(
                user_id,
                f"✅ *Order Confirmed*\n\nYour order `{oid}` has been confirmed 🎉"
            )
        else:
            await client.send_message(
                user_id,
                "❌ *Order Rejected*\n\n"
                "You will receive a refund on your original payment method."
            )

        # Admin summary
        await client.send_message(
            ADMIN_ID,
            f"✅ *ORDER {status}*\n\n"
            f"🆔 Order ID: `{oid}`\n\n"
            f"👤 *User Details*\n"
            f"• Username: {username}\n"
            f"• User ID: `{user_id}`\n\n"
            f"🛒 *Product Details*\n"
            f"• Link: {link}\n"
            f"• MRP: ₹{mrp}\n"
            f"• Discounted Price: ₹{final_price}\n\n"
            f"📌 Status: {status}"
        )

        await cb.message.edit_reply_markup(None)
        await cb.answer("Action completed ✅", show_alert=True)
        return

    # ---------- BLOCK ADMIN FROM USER FLOW ----------
    if uid == ADMIN_ID:
        await cb.answer("Admin cannot place orders", show_alert=True)
        return

    # ---------- USER FLOW ----------
    support_waiting.discard(uid)
    price_waiting.discard(uid)
    order_waiting.discard(uid)
    mrp_waiting.pop(uid, None)

    if cb.data == "support":
        support_waiting.add(uid)
        await cb.message.reply("✉️ Please explain your problem in one single message.")

    elif cb.data == "price":
        price_waiting.add(uid)
        await cb.message.reply("🔗 Send Lenskart product link")

    elif cb.data == "buy":
        order_waiting.add(uid)
        await cb.message.reply("🔗 Send product link to place order")

# ==================================================
# TEXT HANDLER (USERS)
# ==================================================
@app.on_message(filters.text & filters.private)
async def text_handler(client, msg):
    uid = msg.from_user.id
    text = msg.text.strip()

    if uid == ADMIN_ID:
        return

    # ---------- SUPPORT ----------
    if uid in support_waiting:
        support_waiting.discard(uid)
        sent = await client.send_message(
            ADMIN_ID,
            f"📩 *SUPPORT MESSAGE*\n\nUser ID: `{uid}`\n\n{text}"
        )
        support_map[sent.id] = uid
        await msg.reply("✅ Your message has been sent to admin")
        return

    # ---------- MANUAL MRP ----------
    if uid in mrp_waiting and text.isdigit():
        mrp = int(text)
        link = mrp_waiting.pop(uid)

        percent = get_percentage(mrp)
        if not percent:
            await msg.reply("❌ MRP not supported in pricing slabs")
            return

        final_price = int(mrp * percent / 100)
        oid = str(uuid.uuid4())[:8]

        cur.execute(
            "INSERT INTO orders VALUES (%s,%s,%s,%s,%s,%s)",
            (oid, uid, link, mrp, final_price, "PAYMENT_WAITING")
        )
        conn.commit()

        await msg.reply_photo(
            QR_IMAGE,
            caption=(
                f"🆔 Order ID: `{oid}`\n"
                f"🧾 MRP: ₹{mrp}\n"
                f"💰 Pay: ₹{final_price}\n\n"
                f"After payment, send screenshot here"
            )
        )
        return

    # ---------- PRODUCT LINK ----------
    if "lenskart.com" in text:
        mrp_waiting[uid] = text
        await msg.reply_photo(
            MRP_HELP_IMAGE,
            caption=(
                "⚠️ Unable to auto-fetch MRP.\n\n"
                "Please type ONLY the original *MRP* shown on Lenskart.\n"
                "❌ Do NOT send discounted price.\n\n"
                "Example:\n"
                "Original MRP = ₹3900\n"
                "Discounted Price = ₹3100\n\n"
                "You must send: 3900"
            )
        )
        return

    await msg.reply("⚠️ Please choose an option first.")

# ==================================================
# PAYMENT SCREENSHOT
# ==================================================
@app.on_message(filters.photo & filters.private)
async def payment_handler(client, msg):
    uid = msg.from_user.id

    cur.execute(
        "SELECT order_id, product_link, mrp, final_price FROM orders "
        "WHERE telegram_id=%s AND status='PAYMENT_WAITING'",
        (uid,)
    )
    order = cur.fetchone()

    if not order:
        await msg.reply("❌ No pending order found")
        return

    oid, link, mrp, price = order
    cur.execute(
        "UPDATE orders SET status='PAYMENT_SENT' WHERE order_id=%s",
        (oid,)
    )
    conn.commit()

    await msg.forward(ADMIN_ID)
    await client.send_message(
        ADMIN_ID,
        f"💰 *PAYMENT RECEIVED*\n\n"
        f"🆔 Order ID: `{oid}`\n"
        f"MRP: ₹{mrp}\n"
        f"Paid: ₹{price}",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Confirm Order", callback_data=f"admin_confirm:{oid}"),
                InlineKeyboardButton("❌ Reject Order", callback_data=f"admin_reject:{oid}")
            ]
        ])
    )

    await msg.reply("✅ Payment received. Waiting for confirmation.")

# ==================================================
# ADMIN SUPPORT REPLY
# ==================================================
@app.on_message(filters.reply & filters.user(ADMIN_ID))
async def admin_reply(client, msg):
    if msg.text and msg.text.startswith("/"):
        return

    replied = msg.reply_to_message
    if replied and replied.id in support_map:
        user_id = support_map.pop(replied.id)
        await client.send_message(
            user_id,
            f"💬 *Admin Reply*\n\n{msg.text}"
        )
        await msg.reply("✅ Reply sent to user")

# ==================================================
# RUN
# ==================================================
app.run()
