import os
import random
import json
import asyncio
import nest_asyncio
import requests
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

SECRET_PHRASE = "NewMexicoMouse"
DATA_FILE = "data.json"
user_states = {}
pending_withdrawal = {}
pending_inject = {}


def load_data():
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except:
        return {"users": {}, "admins": []}


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)


data = load_data()


def is_admin(user_id):
    return int(user_id) in data.get("admins", [])


def get_balance(user_id):
    return data["users"].get(str(user_id), {}).get("balance", 0.0)


def set_balance(user_id, amount):
    uid = str(user_id)
    data["users"].setdefault(uid, {})["balance"] = amount
    save_data(data)


def get_state(user_id):
    return data["users"].get(str(user_id), {}).get("state", {"running": False, "strategy": None})


def set_state(user_id, state):
    uid = str(user_id)
    data["users"].setdefault(uid, {})["state"] = state
    save_data(data)


def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("\uD83D\uDCB0 Balance", callback_data='balance')],
        [
            InlineKeyboardButton("\uD83D\uDCE4 Withdrawal", callback_data='withdrawal'),
            InlineKeyboardButton("\uD83D\uDCE5 Deposit", callback_data='deposit'),
        ],
        [
            InlineKeyboardButton("\u25B6\uFE0F Run", callback_data='run'),
            InlineKeyboardButton("⏹ Stop", callback_data='stop'),
        ],
        [
            InlineKeyboardButton("\uD83D\uDCCA Monitor", callback_data='monitor'),
            InlineKeyboardButton("\uD83E\uDEB0 Strategy", callback_data='strategy'),
        ],
        [InlineKeyboardButton("\uD83D\uDEAA Exit", callback_data='exit')]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_strategy_menu():
    keyboard = [
        [
            InlineKeyboardButton("\uD83D\uDCC8 Momentum", callback_data='strategy_momentum'),
            InlineKeyboardButton("\uD83D\uDCC9 Mean Reversion", callback_data='strategy_mean'),
            InlineKeyboardButton("⚙️ Grid Trading", callback_data='strategy_grid'),
        ],
        [InlineKeyboardButton("\uD83D\uDD19 Back", callback_data='back_to_main')]
    ]
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    set_balance(user_id, get_balance(user_id))
    set_state(user_id, get_state(user_id))

    try:
        with open("header.jpg", "rb") as img:
            await update.message.reply_photo(photo=InputFile(img))
    except:
        pass

    await update.message.reply_text("Choose an option:", reply_markup=get_main_menu())


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data
    user_id = query.from_user.id

    balance = get_balance(user_id)
    state = get_state(user_id)

    if action == "exit":
        await query.edit_message_text("\uD83D\uDEAA Session ended. Goodbye!")
        return

    if action == "deposit":
        await query.edit_message_text("\uD83D\uDCB8 Deposit BTC to: `bc1qexamplebtcaddress`", parse_mode="Markdown", reply_markup=get_main_menu())
        return

    if action == "balance":
        await query.edit_message_text(f"\uD83D\uDCB0 Balance: {balance:.8f} BTC", reply_markup=get_main_menu())
        return

    if action == "withdrawal":
        if not is_admin(user_id):
            await query.edit_message_text("❌ Transaction failed. You are not authorized to withdraw.", reply_markup=get_main_menu())
            return
        if balance <= 0:
            await query.edit_message_text("❌ You can’t withdraw with a 0.00000000 BTC balance.", reply_markup=get_main_menu())
        else:
            pending_withdrawal[user_id] = {'step': 1}
            await query.edit_message_text("\uD83D\uDCB8 Enter the Bitcoin address you want to withdraw to:")
        return

    if action == "run":
        if balance <= 0:
            await query.edit_message_text("⚠️ You have no balance. Please deposit BTC to start trading.", reply_markup=get_main_menu())
        else:
            state["running"] = True
            set_state(user_id, state)
            await query.edit_message_text(f"✅ Bot started using {balance:.8f} BTC.", reply_markup=get_main_menu())
        return

    if action == "stop":
        state["running"] = False
        set_state(user_id, state)
        await query.edit_message_text("⏹ Bot has been stopped.", reply_markup=get_main_menu())
        return

    if action == "monitor":
        try:
            btc_price = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd").json()["bitcoin"]["usd"]
        except:
            btc_price = "Unknown"
        msg = f"\uD83D\uDCCA *Monitor*\n\nStrategy: {state.get('strategy') or 'None'}\nStatus: {'Running' if state.get('running') else 'Stopped'}\nBalance: {balance:.8f} BTC\nBTC Price: ${btc_price}\nProfit: $0.00"
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=get_main_menu())
        return

    if action == "strategy":
        await query.edit_message_text("\uD83D\uDD0E Choose a strategy:", reply_markup=get_strategy_menu())
        return

    if action.startswith("strategy_"):
        strategy_map = {
            "strategy_momentum": "Momentum",
            "strategy_mean": "Mean Reversion",
            "strategy_grid": "Grid Trading"
        }
        state["strategy"] = strategy_map.get(action)
        set_state(user_id, state)
        await query.edit_message_text(f"Strategy set to: {strategy_map.get(action)}", reply_markup=get_strategy_menu())
        return

    if action == "back_to_main":
        await query.edit_message_text("Choose an option:", reply_markup=get_main_menu())
        return

    if action == "withdraw_confirm":
        if not is_admin(user_id):
            await query.edit_message_text("❌ Transaction failed. You are not authorized.", reply_markup=get_main_menu())
            return
        wd = pending_withdrawal.get(user_id)
        if not wd or wd.get("step") != 2:
            await query.answer("No withdrawal in progress.", show_alert=True)
            return
        fee = balance * 0.05
        net = balance - fee
        set_balance(user_id, 0.0)
        pending_withdrawal.pop(user_id)
        await query.edit_message_text(f"✅ Sent {net:.8f} BTC after 5% fee.", reply_markup=get_main_menu())
        return

    if action == "withdraw_cancel":
        pending_withdrawal.pop(user_id, None)
        await query.edit_message_text("❌ Withdrawal cancelled.", reply_markup=get_main_menu())
        return


async def handle_secret_inject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text == SECRET_PHRASE and is_admin(user_id):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Inject to self", callback_data="admin_inject_self")],
            [InlineKeyboardButton("👑 Add Admin", callback_data="admin_add")],
            [InlineKeyboardButton("🗑️ Remove Admin", callback_data="admin_remove")]
        ])
        await update.message.reply_text("🛠️ Admin Panel:", reply_markup=keyboard)
        return

    if pending_withdrawal.get(user_id, {}).get("step") == 1:
        pending_withdrawal[user_id] = {"step": 2, "address": text}
        balance = get_balance(user_id)
        fee = balance * 0.05
        net = balance - fee
        confirm_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm", callback_data="withdraw_confirm"),
             InlineKeyboardButton("❌ Cancel", callback_data="withdraw_cancel")]
        ])
        await update.message.reply_text(
            f"Withdraw {net:.8f} BTC to `{text}`? Fee: {fee:.8f} BTC",
            reply_markup=confirm_kb, parse_mode="Markdown")
        return


async def profit_loop(context: ContextTypes.DEFAULT_TYPE):
    for uid in data.get("users", {}):
        uid_int = int(uid)
        state = get_state(uid_int)
        if state.get("running"):
            gain = random.uniform(0.00001, 0.00005)
            set_balance(uid_int, get_balance(uid_int) + gain)


async def handle(request):
    return web.Response(text="OK")


async def run_webserver():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", "8000")))
    await site.start()
    while True:
        await asyncio.sleep(3600)


async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_secret_inject))
    app.job_queue.run_repeating(profit_loop, interval=5, first=5)
    asyncio.create_task(run_webserver())
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
