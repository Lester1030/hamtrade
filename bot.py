import os
import random
import asyncio
from aiohttp import web

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputFile
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

user_balances = {}
user_states = {}

def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("💰 Balance", callback_data='balance')],
        [InlineKeyboardButton("🚪 Exit", callback_data='exit')],
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_balances.setdefault(user_id, 0.0)
    user_states.setdefault(user_id, {"running": False, "strategy": None})

    await update.message.reply_text("Welcome to AngryTrader! Choose an option:", reply_markup=get_main_menu())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    action = query.data

    if action == "balance":
        balance = user_balances.get(user_id, 0.0)
        await query.edit_message_text(f"Your balance is {balance:.8f} BTC", reply_markup=get_main_menu())
    elif action == "exit":
        await query.edit_message_text("Goodbye!")
    else:
        await query.edit_message_text("Unknown action.", reply_markup=get_main_menu())

async def profit_simulator_tick(context: ContextTypes.DEFAULT_TYPE):
    for user_id, state in user_states.items():
        if state.get("running"):
            profit = random.uniform(0.00001, 0.00005)
            user_balances[user_id] = user_balances.get(user_id, 0.0) + profit

async def handle_web(request):
    return web.Response(text="Bot is running!")

async def run_webserver():
    app = web.Application()
    app.router.add_get("/", handle_web)
    port = int(os.environ.get("PORT", "8000"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Webserver running on port {port}")

    # Keep running forever without exiting
    while True:
        await asyncio.sleep(3600)

async def main():
    # Build bot app
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    # Schedule profit simulator job
    app.job_queue.run_repeating(profit_simulator_tick, interval=5, first=5)

    # Run bot polling and webserver concurrently
    await asyncio.gather(
        app.run_polling(),
        run_webserver()
    )

if __name__ == "__main__":
    asyncio.run(main())
