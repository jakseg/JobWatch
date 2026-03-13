"""JobWatch Telegram Bot — entry point."""

import logging
import os

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from src.database import init_db
from src.handlers import (
    NAME,
    URL,
    KEYWORDS,
    LOCATION,
    URL_SELECT,
    start_cmd,
    help_cmd,
    list_cmd,
    remove_cmd,
    check_cmd,
    time_cmd,
    pause_cmd,
    resume_cmd,
    keywords_cmd,
    add_start,
    add_name,
    add_url,
    add_location,
    add_url_select,
    add_url_select_callback,
    add_keywords,
    add_cancel,
    button_callback,
)
from src.scheduler import init_browser, shutdown_browser, load_all_schedules, scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _parse_allowed_ids() -> set[int]:
    raw = os.environ.get("ALLOWED_CHAT_IDS", "").strip()
    if not raw:
        return set()
    return {int(x.strip()) for x in raw.split(",") if x.strip()}


ALLOWED_CHAT_IDS = _parse_allowed_ids()


class _AuthFilter(filters.MessageFilter):
    def filter(self, message) -> bool:
        if not ALLOWED_CHAT_IDS:
            return True
        return message.chat_id in ALLOWED_CHAT_IDS


auth_filter = _AuthFilter()


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set")

    init_db()

    app = Application.builder().token(token).build()

    af = auth_filter

    # Simple command handlers
    app.add_handler(CommandHandler("start", start_cmd, filters=af))
    app.add_handler(CommandHandler("help", help_cmd, filters=af))
    app.add_handler(CommandHandler("list", list_cmd, filters=af))
    app.add_handler(CommandHandler("remove", remove_cmd, filters=af))
    app.add_handler(CommandHandler("check", check_cmd, filters=af))
    app.add_handler(CommandHandler("time", time_cmd, filters=af))
    app.add_handler(CommandHandler("pause", pause_cmd, filters=af))
    app.add_handler(CommandHandler("resume", resume_cmd, filters=af))
    app.add_handler(CommandHandler("keywords", keywords_cmd, filters=af))
    app.add_handler(CallbackQueryHandler(button_callback))

    # Multi-step /add conversation
    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_start, filters=af)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND & af, add_name)],
            LOCATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & af, add_location),
                CommandHandler("skip", add_location, filters=af),
            ],
            URL: [MessageHandler(filters.TEXT & ~filters.COMMAND & af, add_url)],
            URL_SELECT: [
                CallbackQueryHandler(add_url_select_callback, pattern=r"^select_url_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND & af, add_url_select),
            ],
            KEYWORDS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & af, add_keywords),
                CommandHandler("skip", add_keywords, filters=af),
            ],
        },
        fallbacks=[CommandHandler("cancel", add_cancel, filters=af)],
    )
    app.add_handler(add_conv)

    # Lifecycle hooks
    async def post_init(application: Application) -> None:
        await init_browser()
        load_all_schedules(application.bot)
        scheduler.start()

    async def post_shutdown(application: Application) -> None:
        if scheduler.running:
            scheduler.shutdown()
        await shutdown_browser()

    app.post_init = post_init
    app.post_shutdown = post_shutdown

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
