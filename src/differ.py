"""Line-set-based change detection and state persistence."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)

STATE_FILE = Path("data/state.json")
STATE_VERSION = 2  # v1 = hash-based (old), v2 = line-set-based (new)


class StateEntry(TypedDict):
    lines: list[str]
    last_checked: str
    version: int


class DiffResult(TypedDict):
    company_name: str
    url: str
    new_lines: list[str]
    is_new: bool


def load_state() -> dict[str, StateEntry]:
    """Load the persisted state from data/state.json."""
    if not STATE_FILE.exists():
        return {}
    with open(STATE_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict[str, StateEntry]) -> None:
    """Save the current state to data/state.json."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    logger.info("State saved to %s.", STATE_FILE)


def _is_v1_entry(entry: dict) -> bool:
    """Check if a state entry uses the old hash-based format."""
    return "hash" in entry and "lines" not in entry


def check_diff(
    company_name: str,
    url: str,
    current_lines: set[str],
    state: dict,
) -> DiffResult:
    """Compare current lines against stored state using set difference.

    Updates the state dict in-place with the new line set.

    Args:
        company_name: Display name of the company.
        url: The URL that was scraped.
        current_lines: Set of cleaned text lines from the page.
        state: The mutable state dictionary.

    Returns:
        DiffResult with new_lines populated (empty list = no changes).
    """
    now = datetime.now(timezone.utc).isoformat()
    is_new = url not in state

    if is_new:
        logger.info("[NEW] %s — storing baseline (%d lines).", company_name, len(current_lines))
        new_lines: list[str] = []
    elif _is_v1_entry(state[url]):
        logger.info("[MIGRATE] %s — upgrading from v1 to v2. Storing baseline.", company_name)
        new_lines = []
    else:
        stored_lines = set(state[url]["lines"])
        new_lines = sorted(current_lines - stored_lines)
        if new_lines:
            logger.info("[CHANGED] %s — %d new line(s) detected.", company_name, len(new_lines))
        else:
            logger.info("[OK] %s — no new lines.", company_name)

    state[url] = StateEntry(
        lines=sorted(current_lines),
        last_checked=now,
        version=STATE_VERSION,
    )

    return DiffResult(
        company_name=company_name,
        url=url,
        new_lines=new_lines,
        is_new=is_new,
    )
