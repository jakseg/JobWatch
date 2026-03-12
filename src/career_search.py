"""Search for company career pages using Google Custom Search API."""

import asyncio
import json
import logging
import os
import urllib.request
import urllib.parse

logger = logging.getLogger(__name__)

GOOGLE_CSE_API_KEY = os.environ.get("GOOGLE_CSE_API_KEY", "")
GOOGLE_CSE_CX = os.environ.get("GOOGLE_CSE_CX", "")

CSE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"


def is_search_available() -> bool:
    return bool(GOOGLE_CSE_API_KEY and GOOGLE_CSE_CX)


def _search_sync(query: str) -> list[dict]:
    params = urllib.parse.urlencode({
        "key": GOOGLE_CSE_API_KEY,
        "cx": GOOGLE_CSE_CX,
        "q": query,
        "num": 5,
    })
    url = f"{CSE_ENDPOINT}?{params}"

    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())

    results = []
    for item in data.get("items", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": item.get("snippet", ""),
        })
    return results


async def search_career_pages(company: str, location: str | None = None) -> list[dict]:
    if not is_search_available():
        return []

    parts = [f'"{company}"', "careers", "jobs"]
    if location:
        parts.append(location)
    query = " ".join(parts)

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _search_sync, query)
    except Exception:
        logger.exception("Career page search failed for query: %s", query)
        return []
