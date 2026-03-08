"""Fetch career pages via Playwright and extract text lines."""

import logging
import re

from playwright.sync_api import BrowserContext
from playwright.sync_api import TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

PAGE_TIMEOUT = 30_000  # 30 seconds for page load
SETTLE_TIMEOUT = 2_000  # 2 seconds extra for late JS rendering
MIN_LINE_LENGTH = 10
MAX_LINE_LENGTH = 300

# Patterns that indicate dynamic content which changes on every page load
DYNAMIC_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"csrf[_-]?token\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"session[_-]?id\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"nonce\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\b[0-9a-f]{32,}\b"),  # long hex strings (tokens, hashes)
    re.compile(r"\d{10,13}"),  # Unix timestamps (seconds or milliseconds)
]


def _clean_line(line: str) -> str:
    """Normalize whitespace and strip dynamic tokens from a single line."""
    for pattern in DYNAMIC_PATTERNS:
        line = pattern.sub("", line)
    return re.sub(r"\s+", " ", line).strip()


def scrape(context: BrowserContext, url: str) -> set[str] | None:
    """Open a new page, navigate to a URL, and extract cleaned text lines.

    Creates a fresh page per URL to avoid cross-contamination between sites.

    Args:
        context: An open Playwright BrowserContext.
        url: The career page URL to scrape.

    Returns:
        A set of cleaned, non-empty text lines (length 10-300),
        or None if navigation failed.
    """
    page = context.new_page()
    try:
        try:
            page.goto(url, wait_until="networkidle", timeout=PAGE_TIMEOUT)
        except PlaywrightTimeout:
            logger.warning("networkidle timed out for %s, falling back to domcontentloaded.", url)
            page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)

        # Give JS a moment to finish rendering dynamic content
        page.wait_for_timeout(SETTLE_TIMEOUT)

        raw_text = page.inner_text("body")
    except Exception as e:
        logger.error("Failed to scrape %s: %s", url, e)
        return None
    finally:
        page.close()

    lines: set[str] = set()
    for raw_line in raw_text.splitlines():
        cleaned = _clean_line(raw_line)
        if MIN_LINE_LENGTH <= len(cleaned) <= MAX_LINE_LENGTH:
            lines.add(cleaned)

    logger.info("Extracted %d lines from %s", len(lines), url)
    return lines
