"""Hash-based change detection and state persistence."""

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)

STATE_FILE = Path("data/state.json")


class StateEntry(TypedDict):
    hash: str
    last_checked: str


class DiffResult(TypedDict):
    company_name: str
    url: str
    changed: bool
    is_new: bool


def compute_hash(content: str) -> str:
    """Compute SHA-256 hash of the given content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def load_state() -> dict[str, StateEntry]:
    """Load the persisted state from data/state.json.

    Returns:
        Dictionary mapping URLs to their state entries.
    """
    if not STATE_FILE.exists():
        return {}

    with open(STATE_FILE, encoding="utf-8") as f:
        data = json.load(f)

    return data


def save_state(state: dict[str, StateEntry]) -> None:
    """Save the current state to data/state.json.

    Args:
        state: Dictionary mapping URLs to their state entries.
    """
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    logger.info("State saved to %s.", STATE_FILE)


def check_diff(
    company_name: str,
    url: str,
    content: str,
    state: dict[str, StateEntry],
) -> DiffResult:
    """Compare the current content hash against the stored state.

    Updates the state dict in-place with the new hash and timestamp.

    Args:
        company_name: Display name of the company.
        url: The URL that was scraped.
        content: The cleaned text content from the page.
        state: The mutable state dictionary.

    Returns:
        A DiffResult indicating whether the page changed or is new.
    """
    current_hash = compute_hash(content)
    now = datetime.now(timezone.utc).isoformat()

    is_new = url not in state
    changed = False

    if is_new:
        logger.info("[NEW] %s — storing baseline hash.", company_name)
    elif state[url]["hash"] != current_hash:
        changed = True
        logger.info("[CHANGED] %s — content has changed.", company_name)
    else:
        logger.info("[OK] %s — no changes detected.", company_name)

    state[url] = StateEntry(hash=current_hash, last_checked=now)

    return DiffResult(
        company_name=company_name,
        url=url,
        changed=changed,
        is_new=is_new,
    )
