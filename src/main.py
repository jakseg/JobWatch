"""JobWatch — Entry point that orchestrates the full check pipeline."""

import logging
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

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


def _filter_by_keywords(lines: set[str], keywords: list[str]) -> set[str]:
    """Keep only lines containing at least one keyword (case-insensitive).

    If keywords is empty, return all lines unchanged.
    """
    if not keywords:
        return lines
    return {
        line
        for line in lines
        if any(kw.lower() in line.lower() for kw in keywords)
    }


def main() -> None:
    """Run the full JobWatch pipeline: load -> scrape -> diff -> notify -> save."""
    logger.info("JobWatch starting...")

    companies = load_config()
    state = load_state()
    changes: list[dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="de-DE",
        )
        for company in companies:
            name = company["name"]
            url = company["url"]
            keywords = company["keywords"]

            logger.info("Checking %s (%s)...", name, url)

            all_lines = scrape(context, url)

            if all_lines is None:
                logger.warning("Skipping %s due to page load error.", name)
                continue

            filtered_lines = _filter_by_keywords(all_lines, keywords)

            result = check_diff(name, url, filtered_lines, state)

            if result["new_lines"]:
                changes.append(result)

        browser.close()

    check_time = datetime.now(timezone.utc).strftime("%Y-%m-%d um %H:%M UTC")

    if changes:
        logger.info("%d company/companies with new lines. Sending notification...", len(changes))
        send_notification(changes, check_time)
    else:
        logger.info("No new lines detected. No notification sent.")

    save_state(state)
    logger.info("JobWatch finished.")


if __name__ == "__main__":
    main()
