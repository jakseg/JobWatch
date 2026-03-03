"""Fetch career pages and extract clean text content."""

import logging
import re

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Patterns that indicate dynamic content which changes on every page load
DYNAMIC_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"csrf[_-]?token\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"session[_-]?id\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"nonce\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\b[0-9a-f]{32,}\b"),  # long hex strings (tokens, hashes)
    re.compile(r"\d{10,13}"),  # Unix timestamps (seconds or milliseconds)
]

# HTML tags that typically contain dynamic / non-content data
REMOVE_TAGS = ["script", "style", "noscript", "iframe", "svg", "nav", "footer", "header"]


def fetch_page(url: str) -> str | None:
    """Fetch a URL and return the raw HTML, or None on error.

    Args:
        url: The URL to fetch.

    Returns:
        Raw HTML string or None if the request failed.
    """
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        logger.error("Failed to fetch %s: %s", url, e)
        return None


def extract_text(html: str) -> str:
    """Extract and clean text content from raw HTML.

    Removes scripts, styles, navigation, and other non-content elements.
    Strips dynamic tokens that change on every page load.

    Args:
        html: Raw HTML string.

    Returns:
        Cleaned text content suitable for hashing.
    """
    soup = BeautifulSoup(html, "html.parser")

    for tag_name in REMOVE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    text = soup.get_text(separator=" ", strip=True)

    for pattern in DYNAMIC_PATTERNS:
        text = pattern.sub("", text)

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text


def scrape(url: str) -> str | None:
    """Fetch a URL and return its cleaned text content.

    Args:
        url: The URL to scrape.

    Returns:
        Cleaned text content or None if fetching failed.
    """
    html = fetch_page(url)
    if html is None:
        return None
    return extract_text(html)
