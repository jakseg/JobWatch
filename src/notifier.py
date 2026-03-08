"""Send Telegram notifications via the Bot API."""

import logging
import os

import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
MAX_MESSAGE_LENGTH = 4096
MAX_LINES_PER_COMPANY = 10
MAX_LINE_DISPLAY_LENGTH = 80


def _get_credentials() -> tuple[str, str]:
    """Read Telegram credentials from environment variables.

    Returns:
        Tuple of (bot_token, chat_id).

    Raises:
        SystemExit: If credentials are missing.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        logger.error(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID environment variables."
        )
        raise SystemExit(1)

    return token, chat_id


def _escape_markdown(text: str) -> str:
    """Escape special Markdown characters for Telegram."""
    for char in ("_", "*", "`", "["):
        text = text.replace(char, f"\\{char}")
    return text


def _truncate_line(line: str, max_length: int = MAX_LINE_DISPLAY_LENGTH) -> str:
    """Truncate a line to max_length, appending ellipsis if needed."""
    if len(line) <= max_length:
        return line
    return line[: max_length - 1] + "\u2026"


def _format_company_block(change: dict) -> str:
    """Format a single company's new lines as a message block."""
    name = _escape_markdown(change["company_name"])
    url = change["url"]
    new_lines = change["new_lines"]

    block_lines = [f"*{name}*"]

    display_lines = new_lines[:MAX_LINES_PER_COMPANY]
    for line in display_lines:
        truncated = _escape_markdown(_truncate_line(line))
        block_lines.append(f"  \u2022 {truncated}")

    remaining = len(new_lines) - MAX_LINES_PER_COMPANY
    if remaining > 0:
        block_lines.append(f"  _\\+{remaining} weitere_")

    block_lines.append(f"[\u2192 Zur Seite]({url})")

    return "\n".join(block_lines)


def send_notification(changes: list[dict], check_time: str) -> None:
    """Send a summary message listing new job lines per company.

    Splits into multiple Telegram messages if exceeding the 4096 char limit.

    Args:
        changes: List of DiffResult dicts with non-empty new_lines.
        check_time: Formatted timestamp string for the message footer.
    """
    if not changes:
        return

    token, chat_id = _get_credentials()

    header = "\U0001f514 *JobWatch \u2014 Neue Stellenangebote*\n"
    footer = f"\n_Gepr\u00fcft am {_escape_markdown(check_time)}_"

    company_blocks = [_format_company_block(c) for c in changes]

    # Assemble messages respecting the 4096 char limit
    messages: list[str] = []
    current_message = header

    for block in company_blocks:
        test_message = current_message + "\n" + block + footer
        if len(test_message) > MAX_MESSAGE_LENGTH and current_message != header:
            messages.append(current_message + footer)
            current_message = header + "\n" + block
        else:
            current_message += "\n" + block

    messages.append(current_message + footer)

    for i, message in enumerate(messages):
        try:
            response = requests.post(
                TELEGRAM_API.format(token=token),
                json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            response.raise_for_status()
            logger.info(
                "Telegram notification %d/%d sent successfully.", i + 1, len(messages)
            )
        except requests.RequestException as e:
            logger.error(
                "Failed to send Telegram notification %d/%d: %s",
                i + 1,
                len(messages),
                e,
            )
