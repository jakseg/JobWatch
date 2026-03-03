"""Send Telegram notifications via the Bot API."""

import logging
import os

import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


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


def send_notification(changes: list[dict], check_time: str) -> None:
    """Send a single summary message listing all changed career pages.

    Args:
        changes: List of DiffResult dicts where changed=True.
        check_time: Formatted timestamp string for the message footer.
    """
    if not changes:
        return

    token, chat_id = _get_credentials()

    lines = ["\U0001f514 *JobWatch — Neue Änderungen*\n"]
    for change in changes:
        name = _escape_markdown(change["company_name"])
        url = change["url"]
        lines.append(f"*{name}* — Karriereseite hat sich geändert")
        lines.append(f"[\u2192 Zur Seite]({url})\n")

    lines.append(f"_Geprüft am {_escape_markdown(check_time)}_")
    message = "\n".join(lines)

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
        logger.info("Telegram notification sent successfully.")
    except requests.RequestException as e:
        logger.error("Failed to send Telegram notification: %s", e)


def _escape_markdown(text: str) -> str:
    """Escape special Markdown characters for Telegram.

    Args:
        text: Raw text string.

    Returns:
        Escaped string safe for Telegram Markdown.
    """
    for char in ("_", "*", "`", "["):
        text = text.replace(char, f"\\{char}")
    return text
