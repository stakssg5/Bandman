import os
import logging
from typing import Optional

from telegram import LabeledPrice, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

# --- Configuration ---
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
PROVIDER_TOKEN = os.environ.get("PROVIDER_TOKEN", "")  # Provided by your PSP (e.g., Stripe via Telegram)
DEFAULT_TITLE = os.environ.get("ITEM_TITLE", "Sample purchase")
DEFAULT_DESCRIPTION = os.environ.get("ITEM_DESCRIPTION", "Example via Telegram Payments")
DEFAULT_PRICE_CENTS = int(os.environ.get("ITEM_PRICE_CENTS", "500"))  # default $5.00
DEFAULT_CURRENCY = os.environ.get("ITEM_CURRENCY", "USD")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Welcome! This bot uses Telegram Payments so your card details never touch this bot.\n\n"
        "Commands:\n"
        "- /buy — send an invoice for the default item.\n"
        "  Optional: /buy <price_cents> <currency> (e.g., /buy 799 USD)\n"
        "- /help — show this help.\n\n"
        "Set BOT_TOKEN and PROVIDER_TOKEN as environment variables to run."
    )
    await update.message.reply_text(text)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


def parse_buy_args(args: list[str]) -> tuple[int, str]:
    if not args:
        return DEFAULT_PRICE_CENTS, DEFAULT_CURRENCY
    try:
        price = int(args[0])
    except ValueError:
        price = DEFAULT_PRICE_CENTS
    currency = args[1].upper() if len(args) > 1 else DEFAULT_CURRENCY
    return price, currency


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    price_cents, currency = parse_buy_args(context.args)
    prices = [LabeledPrice(DEFAULT_TITLE, price_cents)]

    await context.bot.send_invoice(
        chat_id=update.effective_chat.id,
        title=DEFAULT_TITLE,
        description=DEFAULT_DESCRIPTION,
        payload="invoice-payload-001",
        provider_token=PROVIDER_TOKEN,
        currency=currency,
        prices=prices,
        start_parameter="pay",
        need_name=False,
        need_phone_number=False,
        need_email=False,
        need_shipping_address=False,
        is_flexible=False,
    )


async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Approve the checkout. You could perform validation here (e.g., stock check).
    await update.pre_checkout_query.answer(ok=True)


async def successful(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message and update.message.successful_payment:
        total = update.message.successful_payment.total_amount
        currency = update.message.successful_payment.currency
        await update.message.reply_text(
            f"Payment received: {total/100:.2f} {currency}. Thank you!"
        )


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Unknown command. Use /help.")


def _require_env(name: str) -> Optional[str]:
    value = os.environ.get(name)
    if not value:
        logger.error("Missing required environment variable: %s", name)
    return value


def main() -> None:
    if not _require_env("BOT_TOKEN") or not _require_env("PROVIDER_TOKEN"):
        logger.error("Please set BOT_TOKEN and PROVIDER_TOKEN before running.")
        raise SystemExit(2)

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    logger.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=["message", "pre_checkout_query"])


if __name__ == "__main__":
    main()
