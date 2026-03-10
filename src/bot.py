"""JobWatch Telegram Bot — entry point."""

import logging
import os

from telegram.ext import (
    Application,
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
    add_keywords,
    add_cancel,
)
from src.scheduler import init_browser, shutdown_browser, load_all_schedules, scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set")

    init_db()

    app = Application.builder().token(token).build()

    # Simple command handlers
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("remove", remove_cmd))
    app.add_handler(CommandHandler("check", check_cmd))
    app.add_handler(CommandHandler("time", time_cmd))
    app.add_handler(CommandHandler("pause", pause_cmd))
    app.add_handler(CommandHandler("resume", resume_cmd))
    app.add_handler(CommandHandler("keywords", keywords_cmd))

    # Multi-step /add conversation
    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_url)],
            KEYWORDS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_keywords),
                CommandHandler("skip", add_keywords),
            ],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
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
