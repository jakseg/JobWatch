"""Send Telegram notifications via python-telegram-bot."""

import logging
import re

from telegram import Bot

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 4096
MAX_LINES_PER_COMPANY = 10
MAX_LINE_DISPLAY_LENGTH = 80

# Lines that are likely noise (nav elements, counters, locations-only)
_NOISE_PATTERNS = [
    re.compile(r"^\d+\s*/\s*\d+\s*(Jobs?|Stellen?|Results?)", re.IGNORECASE),  # "27 / 461 Jobs"
    re.compile(r"^(Show more|Load more|Mehr anzeigen|Weitere)", re.IGNORECASE),
    re.compile(r"^(Cookie|Accept|Decline|Privacy|Datenschutz)", re.IGNORECASE),
    re.compile(r"^(Home|Menu|Navigation|Footer|Header|Breadcrumb)", re.IGNORECASE),
    re.compile(r"^\d+$"),  # Just a number
]


def _is_noise(line: str) -> bool:
    return any(p.search(line) for p in _NOISE_PATTERNS)


def _escape_markdown(text: str) -> str:
    for char in ("_", "*", "`", "["):
        text = text.replace(char, f"\\{char}")
    return text


def _truncate_line(line: str, max_length: int = MAX_LINE_DISPLAY_LENGTH) -> str:
    if len(line) <= max_length:
        return line
    return line[: max_length - 1] + "\u2026"


def _format_company_block(change: dict) -> str:
    name = _escape_markdown(change["company_name"])
    url = change["url"]
    new_lines = [l for l in change["new_lines"] if not _is_noise(l)]

    if not new_lines:
        new_lines = change["new_lines"]

    count = len(new_lines)
    block_lines = [f"\U0001f3e2 *{name}* — {count} new"]

    display_lines = new_lines[:MAX_LINES_PER_COMPANY]
    for line in display_lines:
        truncated = _escape_markdown(_truncate_line(line))
        block_lines.append(f"  \u2022 {truncated}")

    remaining = len(new_lines) - MAX_LINES_PER_COMPANY
    if remaining > 0:
        block_lines.append(f"  _\\+{remaining} more_")

    block_lines.append(f"  [\u2192 View page]({url})")

    return "\n".join(block_lines)


async def send_notification(bot: Bot, chat_id: int, changes: list[dict], check_time: str) -> None:
    """Send a summary message listing new job lines per company.

    Splits into multiple messages if exceeding the 4096 char Telegram limit.
    """
    if not changes:
        return

    total_new = sum(len(c["new_lines"]) for c in changes)
    company_count = len(changes)

    header = (
        f"\U0001f514 *JobWatch — New Job Postings*\n"
        f"_{company_count} {'company' if company_count == 1 else 'companies'}, "
        f"{total_new} new {'posting' if total_new == 1 else 'postings'}_\n"
    )
    footer = f"\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n_Checked {_escape_markdown(check_time)}_"

    separator = "\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
    company_blocks = [_format_company_block(c) for c in changes]

    messages: list[str] = []
    current_message = header

    for i, block in enumerate(company_blocks):
        prefix = separator if i > 0 else "\n"
        test_message = current_message + prefix + block + footer
        if len(test_message) > MAX_MESSAGE_LENGTH and current_message != header:
            messages.append(current_message + footer)
            current_message = header + "\n" + block
        else:
            current_message += prefix + block

    messages.append(current_message + footer)

    for i, message in enumerate(messages):
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
            logger.info("Notification %d/%d sent to %d.", i + 1, len(messages), chat_id)
        except Exception as e:
            logger.error("Failed to send notification %d/%d to %d: %s", i + 1, len(messages), chat_id, e)
