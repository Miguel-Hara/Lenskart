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
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "-1003583093312"))

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

# ================= PRICE SLABS =================
def get_percentage(mrp):
    slabs = [
        (1900,3100,57.5),(3200,4100,59),(4200,5400,62),
        (5500,6400,64.5),(6500,7400,65.5),(7500,8400,66),
        (8500,9400,68),(9400,10300,69),(10400,11300,70),
        (11400,12800,71)
    ]
    for low, high, p in slabs:
        if low <= mrp <= high:
            return p
    return None

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
        await msg.reply("👑 Admin mode active.\nUse /orders to view orders.")
        return

    cur.execute(
        "INSERT INTO users VALUES (%s,%s) ON CONFLICT DO NOTHING",
        (msg.from_user.id, msg.from_user.username)
    )
    conn.commit()

    await msg.reply_photo(
        START_IMAGE,
        caption="👓 *Lenskart Order Bot*\nOrder Lenskart frames at discounted prices.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 New Order", callback_data="buy")],
            [InlineKeyboardButton("🆘 Support", callback_data="support")]
        ])
    )

# ================= HELP =================
@app.on_message(filters.command("help"))
async def help_cmd(client, msg):
    await msg.reply(
        "ℹ️ *How to use the bot*\n\n"
        "1️⃣ Send Lenskart product link\n"
        "2️⃣ Enter original MRP\n"
        "3️⃣ Pay discounted amount\n"
        "4️⃣ Get order updates automatically\n\n"
        "Commands:\n"
        "/myorders – view your orders"
    )

# ================= USER ORDERS =================
@app.on_message(filters.command("myorders"))
async def my_orders(client, msg):
    uid = msg.from_user.id
    cur.execute(
        "SELECT order_id, status FROM orders WHERE telegram_id=%s ORDER BY order_id DESC LIMIT 5",
        (uid,)
    )
    rows = cur.fetchall()
    if not rows:
        await msg.reply("❌ No orders found")
        return

    text = "📦 *Your Orders*\n\n"
    for oid, status in rows:
        text += f"• `{oid}` — {status}\n"

    await msg.reply(text)

# ================= ADMIN ORDERS =================
@app.on_message(filters.command("orders") & filters.user(ADMIN_ID))
async def admin_orders(client, msg):
    cur.execute(
        "SELECT order_id, telegram_id, status FROM orders ORDER BY order_id DESC LIMIT 10"
    )
    rows = cur.fetchall()
    if not rows:
        await msg.reply("No orders yet")
        return

    text = "📋 *Last 10 Orders*\n\n"
    for oid, uid, status in rows:
        text += f"🆔 `{oid}` | User `{uid}` | {status}\n"

    await msg.reply(text)

# ================= BROADCAST =================
@app.on_message(filters.command("broadcast") & filters.user(ADMIN_ID))
async def broadcast_cmd(client, msg):
    global broadcast_waiting
    broadcast_waiting = True
    await msg.reply("📢 Send the message to broadcast")

# ================= CALLBACKS =================
@app.on_callback_query()
async def callbacks(client, cb):
    uid = cb.from_user.id
    data = cb.data

    # ---------- STATUS UPDATE ----------
    if uid == ADMIN_ID and data.startswith("status:"):
        _, status, oid = data.split(":")
        cur.execute("UPDATE orders SET status=%s WHERE order_id=%s",(status,oid))
        conn.commit()

        cur.execute("SELECT telegram_id FROM orders WHERE order_id=%s",(oid,))
        user_id = cur.fetchone()[0]

        msg_map = {
            "PACKED":"📦 Your order is packed",
            "ON_THE_WAY":"🚚 Your order is on the way",
            "DELIVERED":"📬 Your order has been delivered"
        }

        await client.send_message(user_id, msg_map[status])

        try:
            await client.send_message(LOG_CHANNEL_ID, f"Order {oid} → {status}")
        except:
            pass

        await cb.answer("Status updated")
        return

    # ---------- CONFIRM ----------
    if uid == ADMIN_ID and data.startswith("admin_confirm"):
        oid = data.split(":")[1]
        cur.execute("UPDATE orders SET status='CONFIRMED' WHERE order_id=%s",(oid,))
        conn.commit()

        cur.execute("SELECT telegram_id FROM orders WHERE order_id=%s",(oid,))
        user_id = cur.fetchone()[0]

        await client.send_message(user_id,"✅ Your order is confirmed")
        await cb.message.edit_reply_markup(status_buttons(oid))
        return

    # ---------- USER ----------
    if data == "buy":
        await cb.message.reply("🔗 Send Lenskart product link")
    elif data == "support":
        support_waiting.add(uid)
        await cb.message.reply("✉️ Send your issue in one message")

# ================= TEXT =================
@app.on_message(filters.text & filters.private)
async def text_handler(client, msg):
    global broadcast_waiting
    uid = msg.from_user.id
    text = msg.text.strip()

    # ---------- BROADCAST ----------
    if uid == ADMIN_ID and broadcast_waiting:
        broadcast_waiting = False
        cur.execute("SELECT telegram_id FROM users")
        users = cur.fetchall()
        sent = 0
        for (u,) in users:
            try:
                await client.send_message(u, text)
                sent += 1
            except:
                pass
        await msg.reply(f"📢 Broadcast sent to {sent} users")
        return

    # ---------- SUPPORT ----------
    if uid in support_waiting:
        support_waiting.discard(uid)
        await client.send_message(ADMIN_ID, f"📩 SUPPORT\nUser {uid}\n{text}")
        await msg.reply("✅ Support sent")
        return

    # ---------- PRODUCT LINK ----------
    if "lenskart.com" in text:
        mrp_waiting[uid] = text
        await msg.reply_photo(MRP_HELP_IMAGE, caption="Send ONLY original MRP")
        return

    # ---------- MRP ----------
    if uid in mrp_waiting and text.isdigit():
        mrp = int(text)
        link = mrp_waiting.pop(uid)
        price = int(mrp * get_percentage(mrp) / 100)
        oid = str(uuid.uuid4())[:8]

        cur.execute(
            "INSERT INTO orders VALUES (%s,%s,%s,%s,%s,%s)",
            (oid, uid, link, mrp, price, "PAYMENT_WAITING")
        )
        conn.commit()

        await msg.reply_photo(QR_IMAGE, caption=f"🆔 `{oid}`\nPay ₹{price}")
        return

# ================= PAYMENT =================
@app.on_message(filters.photo & filters.private)
async def payment(client, msg):
    uid = msg.from_user.id
    cur.execute(
        "SELECT order_id FROM orders WHERE telegram_id=%s AND status='PAYMENT_WAITING'",
        (uid,)
    )
    row = cur.fetchone()
    if not row:
        return

    oid = row[0]
    await msg.forward(ADMIN_ID)
    await client.send_message(
        ADMIN_ID,
        f"💰 Payment received\nOrder ID: {oid}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm Order", callback_data=f"admin_confirm:{oid}")]
        ])
    )

# ================= RUN =================
app.run()
