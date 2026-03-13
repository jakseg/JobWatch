"""Per-user scheduled job checking via APScheduler + async Playwright."""

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from playwright.async_api import BrowserContext as AsyncBrowserContext
from playwright.async_api import async_playwright
from telegram import Bot

from src import database
from src.differ import check_diff
from src.notifier import send_notification
from src.scraper import DYNAMIC_PATTERNS, MAX_LINE_LENGTH, MIN_LINE_LENGTH

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
PAGE_TIMEOUT = 30_000
SETTLE_TIMEOUT = 2_000

scheduler = AsyncIOScheduler()

_playwright = None
_browser = None
_bot: Bot | None = None


# --- Browser lifecycle ---

async def init_browser() -> None:
    global _playwright, _browser
    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(headless=True)
    logger.info("Playwright browser launched.")


async def shutdown_browser() -> None:
    global _playwright, _browser
    if _browser:
        await _browser.close()
    if _playwright:
        await _playwright.stop()
    logger.info("Playwright browser closed.")


# --- Async scraper (mirrors src/scraper.py logic) ---

async def _async_scrape(context: AsyncBrowserContext, url: str) -> set[str] | None:
    import re
    page = await context.new_page()
    try:
        try:
            await page.goto(url, wait_until="networkidle", timeout=PAGE_TIMEOUT)
        except Exception:
            logger.warning("networkidle timed out for %s, falling back.", url)
            await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)

        await page.wait_for_timeout(SETTLE_TIMEOUT)
        raw_text = await page.inner_text("body")
    except Exception as e:
        logger.error("Failed to scrape %s: %s", url, e)
        return None
    finally:
        await page.close()

    lines: set[str] = set()
    for raw_line in raw_text.splitlines():
        cleaned = raw_line
        for pattern in DYNAMIC_PATTERNS:
            cleaned = pattern.sub("", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if MIN_LINE_LENGTH <= len(cleaned) <= MAX_LINE_LENGTH:
            lines.add(cleaned)

    logger.info("Extracted %d lines from %s", len(lines), url)
    return lines


# --- Keyword filter (from old main.py) ---

def _filter_by_keywords(lines: set[str], keywords: list[str]) -> set[str]:
    if not keywords:
        return lines
    return {
        line for line in lines
        if any(kw.lower() in line.lower() for kw in keywords)
    }


# --- Check pipeline for one user ---

async def check_user(chat_id: int, bot: Bot) -> None:
    """Run the scrape-diff-notify pipeline for all active companies of a user."""
    companies = database.get_companies_for_check(chat_id)
    if not companies:
        logger.info("No active companies for user %d.", chat_id)
        return

    context = await _browser.new_context(user_agent=USER_AGENT, locale="de-DE")
    changes: list[dict] = []

    try:
        for company in companies:
            name = company["name"]
            url = company["url"]
            keywords_str = company["keywords"]
            keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]

            logger.info("Checking %s for user %d...", name, chat_id)

            current_lines = await _async_scrape(context, url)
            if current_lines is None:
                logger.warning("Skipping %s due to scrape failure.", name)
                continue

            filtered = _filter_by_keywords(current_lines, keywords)
            stored = database.get_stored_lines(company["id"])
            result = check_diff(name, url, filtered, stored)

            database.save_lines(company["id"], filtered)

            if result["new_lines"]:
                changes.append(result)
    finally:
        await context.close()

    if changes:
        check_time = datetime.now(ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%d um %H:%M (Berlin)")
        await send_notification(bot, chat_id, changes, check_time)
        logger.info("Sent %d change(s) to user %d.", len(changes), chat_id)
    else:
        logger.info("No changes for user %d.", chat_id)


# --- Schedule management ---

def schedule_user(chat_id: int, hour: int, minute: int) -> None:
    job_id = f"check_{chat_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    scheduler.add_job(
        check_user,
        trigger=CronTrigger(hour=hour, minute=minute),
        id=job_id,
        args=[chat_id, _bot],
        replace_existing=True,
    )
    logger.info("Scheduled user %d at %02d:%02d UTC (stored).", chat_id, hour, minute)


def reschedule_user(chat_id: int, hour: int, minute: int) -> None:
    schedule_user(chat_id, hour, minute)


def load_all_schedules(bot: Bot) -> None:
    global _bot
    _bot = bot
    users = database.get_all_active_users()
    for user in users:
        schedule_user(user["chat_id"], user["notify_hour"], user["notify_minute"])
    logger.info("Loaded schedules for %d user(s).", len(users))
