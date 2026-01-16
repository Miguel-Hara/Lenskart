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
support_map = {}      # forwarded_msg_id -> user_id
mrp_waiting = {}

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
        await msg.reply("👑 Admin panel active.\nOrders & support yahin aayenge.")
        return

    cur.execute(
        "INSERT INTO users VALUES (%s,%s) ON CONFLICT DO NOTHING",
        (msg.from_user.id, msg.from_user.username)
    )
    conn.commit()

    await msg.reply_photo(
        START_IMAGE,
        caption=(
            "👓 *Welcome to Lenskart Order Bot*\n\n"
            "Yahan aap original Lenskart frames discounted price par order kar sakte ho 💸\n\n"
            "*Steps samjho:*\n"
            "1️⃣ Product link bhejo\n"
            "2️⃣ Original MRP likho\n"
            "3️⃣ Discounted payment karo\n"
            "4️⃣ Order updates pao 📦\n\n"
            "Neeche option select karo 👇"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 New Order", callback_data="buy")],
            [InlineKeyboardButton("🆘 Support", callback_data="support")]
        ])
    )

# ================= TRACK COMMAND =================
@app.on_message(filters.command("track"))
async def track(client, msg):
    if len(msg.command) != 2:
        await msg.reply("❌ Usage:\n`/track ORDER_ID`\nExample: `/track 8f3a91cd`")
        return

    oid = msg.command[1]
    cur.execute(
        "SELECT status FROM orders WHERE order_id=%s AND telegram_id=%s",
        (oid, msg.from_user.id)
    )
    row = cur.fetchone()
    if not row:
        await msg.reply("❌ Aisa koi order nahi mila.")
        return

    await msg.reply(
        f"📦 *Order Status*\n\n"
        f"🆔 Order ID: `{oid}`\n"
        f"📌 Status: *{row[0]}*"
    )

# ================= CALLBACKS =================
@app.on_callback_query()
async def callbacks(client, cb):
    uid = cb.from_user.id
    data = cb.data

    # ---------- ADMIN STATUS UPDATE ----------
    if uid == ADMIN_ID and data.startswith("status:"):
        _, status, oid = data.split(":")
        cur.execute("UPDATE orders SET status=%s WHERE order_id=%s",(status,oid))
        conn.commit()

        cur.execute("SELECT telegram_id FROM orders WHERE order_id=%s",(oid,))
        user_id = cur.fetchone()[0]

        msgs = {
            "PACKED":"📦 Aapka order pack ho chuka hai",
            "ON_THE_WAY":"🚚 Aapka order raste mein hai",
            "DELIVERED":"📬 Aapka order deliver ho gaya 🎉"
        }

        await client.send_message(user_id, msgs[status])

        try:
            await client.send_message(LOG_CHANNEL_ID, f"Order {oid} → {status}")
        except:
            pass

        await cb.answer("Status updated")
        return

    # ---------- ADMIN CONFIRM ----------
    if uid == ADMIN_ID and data.startswith("admin_confirm"):
        oid = data.split(":")[1]
        cur.execute("UPDATE orders SET status='CONFIRMED' WHERE order_id=%s",(oid,))
        conn.commit()

        cur.execute("SELECT telegram_id FROM orders WHERE order_id=%s",(oid,))
        user_id = cur.fetchone()[0]

        await client.send_message(
            user_id,
            "✅ *Order Confirmed*\n\nPayment verify ho gaya hai 👍"
        )

        await cb.message.edit_reply_markup(status_buttons(oid))
        return

    # ---------- USER FLOW ----------
    if data == "buy":
        await cb.message.reply(
            "🔗 *Step 1*\nLenskart product ka link bhejo"
        )

    elif data == "support":
        support_waiting.add(uid)
        await cb.message.reply(
            "🆘 *Support*\n\n"
            "Apni problem ek hi message me bhejo.\n"
            "Text, photo, sticker – sab chalega 👍"
        )

# ================= ALL PRIVATE MSG HANDLER =================
@app.on_message(filters.private)
async def all_private(client, msg):
    uid = msg.from_user.id

    # ---------- SUPPORT ----------
    if uid in support_waiting:
        support_waiting.discard(uid)
        fwd = await msg.forward(ADMIN_ID)
        support_map[fwd.id] = uid
        await msg.reply("✅ Aapka message support team ko bhej diya gaya hai.")
        return

    # ---------- PRODUCT LINK ----------
    if msg.text and "lenskart.com" in msg.text:
        mrp_waiting[uid] = msg.text
        await msg.reply_photo(
            MRP_HELP_IMAGE,
            caption=(
                "🧾 *Step 2 – MRP*\n\n"
                "Sirf *original MRP* likho (discounted nahi)\n"
                "Example:\nMRP ₹3900 → Discount ₹3100\n"
                "Send: *3900*"
            )
        )
        return

    # ---------- MRP ----------
    if uid in mrp_waiting and msg.text and msg.text.isdigit():
        mrp = int(msg.text)
        link = mrp_waiting.pop(uid)

        percent = get_percentage(mrp)
        if not percent:
            await msg.reply("❌ Is MRP par discount available nahi hai.")
            return

        price = int(mrp * percent / 100)
        oid = str(uuid.uuid4())[:8]

        cur.execute(
            "INSERT INTO orders VALUES (%s,%s,%s,%s,%s,%s)",
            (oid, uid, link, mrp, price, "PAYMENT_WAITING")
        )
        conn.commit()

        await msg.reply_photo(
            QR_IMAGE,
            caption=(
                f"💳 *Step 3 – Payment*\n\n"
                f"🆔 Order ID: `{oid}`\n"
                f"💰 Pay Amount: ₹{price}\n\n"
                "QR scan karke payment karo.\n"
                "Payment ke baad screenshot yahin bhejo 📸\n\n"
                "⏳ Uske baad bas wait karo —\n"
                "aapka order *confirm ya reject* hone ka message yahin mil jaayega."
            )
        )
        return

# ================= PAYMENT SCREENSHOT =================
@app.on_message(filters.photo & filters.private)
async def payment(client, msg):
    uid = msg.from_user.id
    cur.execute(
        "SELECT order_id FROM orders WHERE telegram_id=%s AND status='PAYMENT_WAITING'",
        (uid,)
    )
    row = cur.fetchone()
    if not row:
        await msg.reply("❌ Koi pending payment nahi mila.")
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

    await msg.reply(
        "✅ Payment submit ho gaya hai.\n"
        "Please wait, confirmation ya rejection ka message yahin aayega ⏳"
    )

# ================= ADMIN SUPPORT REPLY =================
@app.on_message(filters.reply & filters.user(ADMIN_ID))
async def admin_reply(client, msg):
    replied = msg.reply_to_message
    if replied and replied.id in support_map:
        user_id = support_map.pop(replied.id)
        await msg.copy(user_id)

# ================= RUN =================
app.run()
