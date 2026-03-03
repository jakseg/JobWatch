"""JobWatch — Entry point that orchestrates the full check pipeline."""

import logging
from datetime import datetime, timezone

from src.config_loader import load_config
from src.differ import check_diff, load_state, save_state
from src.notifier import send_notification
from src.scraper import scrape

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Run the full JobWatch pipeline: load → scrape → diff → notify → save."""
    logger.info("JobWatch starting...")

    companies = load_config()
    state = load_state()
    changes: list[dict] = []

    for company in companies:
        name = company["name"]
        url = company["url"]

        logger.info("Checking %s (%s)...", name, url)
        content = scrape(url)

        if content is None:
            logger.warning("Skipping %s due to fetch error.", name)
            continue

        result = check_diff(name, url, content, state)

        if result["changed"]:
            changes.append(result)

    check_time = datetime.now(timezone.utc).strftime("%Y-%m-%d um %H:%M UTC")

    if changes:
        logger.info("%d change(s) detected. Sending notification...", len(changes))
        send_notification(changes, check_time)
    else:
        logger.info("No changes detected. No notification sent.")

    save_state(state)
    logger.info("JobWatch finished.")


if __name__ == "__main__":
    main()
