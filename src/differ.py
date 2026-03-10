"""Line-set-based change detection."""

import logging
from typing import TypedDict

logger = logging.getLogger(__name__)


class DiffResult(TypedDict):
    company_name: str
    url: str
    new_lines: list[str]
    is_new: bool


def check_diff(
    company_name: str,
    url: str,
    current_lines: set[str],
    stored_lines: set[str] | None,
) -> DiffResult:
    """Compare current lines against stored lines using set difference.

    stored_lines is None when the company is checked for the first time.
    """
    is_new = stored_lines is None

    if is_new:
        logger.info("[NEW] %s — storing baseline (%d lines).", company_name, len(current_lines))
        new_lines: list[str] = []
    else:
        new_lines = sorted(current_lines - stored_lines)
        if new_lines:
            logger.info("[CHANGED] %s — %d new line(s) detected.", company_name, len(new_lines))
        else:
            logger.info("[OK] %s — no new lines.", company_name)

    return DiffResult(
        company_name=company_name,
        url=url,
        new_lines=new_lines,
        is_new=is_new,
    )
