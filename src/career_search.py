"""Search for company career pages using DuckDuckGo."""

import asyncio
import json
import logging
import urllib.request
import urllib.parse

logger = logging.getLogger(__name__)

DDG_ENDPOINT = "https://html.duckduckgo.com/html/"


def is_search_available() -> bool:
    return True


def _search_sync(query: str) -> list[dict]:
    data = urllib.parse.urlencode({"q": query}).encode()
    req = urllib.request.Request(
        DDG_ENDPOINT,
        data=data,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        html = resp.read().decode()

    results = []
    # Parse result links from DuckDuckGo HTML response
    # Each result is in a <a class="result__a" href="...">title</a>
    import re
    for match in re.finditer(
        r'<a\s+rel="nofollow"\s+class="result__a"\s+href="([^"]+)"[^>]*>(.*?)</a>',
        html,
    ):
        raw_url = match.group(1)
        title = re.sub(r"<[^>]+>", "", match.group(2)).strip()

        # DuckDuckGo wraps URLs in a redirect; extract the actual URL
        url_match = re.search(r"uddg=([^&]+)", raw_url)
        url = urllib.parse.unquote(url_match.group(1)) if url_match else raw_url

        results.append({"title": title, "url": url, "snippet": ""})
        if len(results) >= 5:
            break

    return results


async def search_career_pages(company: str, location: str | None = None) -> list[dict]:
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
