from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import os, uuid, psycopg2

# ================= ENV =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
DATABASE_URL = os.getenv("DATABASE_URL")

QR_IMAGE = "https://files.catbox.moe/r0ldyf.jpg"

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
price_waiting = set()
order_waiting = set()
mrp_waiting = {}          # uid -> product_link
support_map = {}          # admin_msg_id -> user_id

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

# ================= START =================
@app.on_message(filters.command("start"))
async def start(client, msg):
    cur.execute(
        "INSERT INTO users VALUES (%s,%s) ON CONFLICT DO NOTHING",
        (msg.from_user.id, msg.from_user.username)
    )
    conn.commit()

    await msg.reply(
        "👓 *Lenskart Order Bot*\nChoose an option:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Price Check", callback_data="price")],
            [InlineKeyboardButton("🛒 Buy New Item", callback_data="buy")],
            [InlineKeyboardButton("🆘 Support", callback_data="support")]
        ])
    )

# ================= COMMANDS =================
@app.on_message(filters.command(["support","pricecheckup","neworder"]))
async def block_admin_commands(client, msg):
    if msg.from_user.id == ADMIN_ID:
        await msg.reply("⚠️ Admin cannot use customer commands.")
        return

@app.on_message(filters.command("support"))
async def support_cmd(client, msg):
    support_waiting.add(msg.from_user.id)
    await msg.reply("✉️ Please explain your problem in one single message.")

@app.on_message(filters.command("pricecheckup"))
async def price_cmd(client, msg):
    price_waiting.add(msg.from_user.id)
    await msg.reply("🔗 Send Lenskart product link")

@app.on_message(filters.command("neworder"))
async def order_cmd(client, msg):
    order_waiting.add(msg.from_user.id)
    await msg.reply("🔗 Send product link to place order")

# ================= CALLBACKS =================
@app.on_callback_query()
async def callbacks(client, cb):
    uid = cb.from_user.id

    if uid == ADMIN_ID:
        await cb.message.reply("⚠️ Admin cannot use customer options.")
        return

    if cb.data == "support":
        support_waiting.add(uid)
        await cb.message.reply("✉️ Please explain your problem in one single message.")

    elif cb.data == "price":
        price_waiting.add(uid)
        await cb.message.reply("🔗 Send Lenskart product link")

    elif cb.data == "buy":
        order_waiting.add(uid)
        await cb.message.reply("🔗 Send product link to place order")

# ================= TEXT HANDLER =================
@app.on_message(filters.text & filters.private)
async def text_handler(client, msg):
    uid = msg.from_user.id
    text = msg.text.strip()

    # ---------- SUPPORT ----------
    if uid in support_waiting:
        support_waiting.discard(uid)

        sent = await client.send_message(
            ADMIN_ID,
            f"📩 SUPPORT MESSAGE\n\nUser ID: {uid}\n\n{text}"
        )

        support_map[sent.id] = uid
        await msg.reply("✅ Your message has been sent to admin")
        return

    # ---------- MANUAL MRP ----------
    if uid in mrp_waiting and text.isdigit():
        mrp = int(text)
        product_link = mrp_waiting.pop(uid)

        percent = get_percentage(mrp)
        if not percent:
            await msg.reply("❌ Price slab not supported")
            return

        final_price = int(mrp * percent / 100)
        oid = str(uuid.uuid4())[:8]

        cur.execute(
            "INSERT INTO orders VALUES (%s,%s,%s,%s,%s,%s)",
            (oid, uid, product_link, mrp, final_price, "PAYMENT_WAITING")
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
    if "lenskart.com" in text and (uid in price_waiting or uid in order_waiting):
        price_waiting.discard(uid)
        order_waiting.discard(uid)

        mrp_waiting[uid] = text
        await msg.reply(
            "⚠️ Unable to auto-fetch MRP.\n\n"
            "Please type ONLY the original *MRP* shown on Lenskart.\n"
            "❌ Do NOT send discounted price.\n"
            "Example: 1900"
        )
        return

    # ---------- RANDOM ----------
    await msg.reply(
        "⚠️ Please choose an option first.\n"
        "Use buttons or /support /pricecheckup /neworder"
    )

# ================= PAYMENT SCREENSHOT =================
@app.on_message(filters.photo & filters.private)
async def payment(client, msg):
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
    cur.execute("UPDATE orders SET status='PAYMENT_SENT' WHERE order_id=%s",(oid,))
    conn.commit()

    fwd = await msg.forward(ADMIN_ID)
    await client.send_message(
        ADMIN_ID,
        f"💰 PAYMENT RECEIVED\n\nOrder ID: {oid}\nPaid: ₹{price}\n\n"
        f"/confirm {oid}\n/reject {oid}"
    )

    await msg.reply("✅ Payment received. Waiting for confirmation.")

# ================= ADMIN CONFIRM / REJECT =================
@app.on_message(filters.command(["confirm","reject"]) & filters.user(ADMIN_ID))
async def admin_actions(client, msg):
    cmd, oid = msg.text.split()

    status = "CONFIRMED" if cmd == "/confirm" else "REJECTED"
    cur.execute("UPDATE orders SET status=%s WHERE order_id=%s",(status,oid))
    conn.commit()

    cur.execute("SELECT telegram_id FROM orders WHERE order_id=%s",(oid,))
    user = cur.fetchone()
    if user:
        if status == "CONFIRMED":
            await client.send_message(user[0], f"✅ Order `{oid}` confirmed 🎉")
        else:
            await client.send_message(
                user[0],
                "❌ *Order Rejected*\n\nYou will receive a refund on your original payment method."
            )

    await msg.reply(f"Order {status.lower()}")

# ================= ADMIN SUPPORT REPLY =================
@app.on_message(filters.reply & filters.user(ADMIN_ID))
async def admin_reply_support(client, msg):
    replied = msg.reply_to_message
    if replied and replied.id in support_map:
        user_id = support_map.pop(replied.id)
        await client.send_message(user_id, f"💬 *Admin Reply*\n\n{msg.text}")
        await msg.reply("✅ Reply sent to user")

# ================= RUN =================
app.run()
