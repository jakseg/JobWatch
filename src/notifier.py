"""Send Telegram notifications via python-telegram-bot."""

import logging

from telegram import Bot

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 4096
MAX_LINES_PER_COMPANY = 10
MAX_LINE_DISPLAY_LENGTH = 80


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
    new_lines = change["new_lines"]

    block_lines = [f"*{name}*"]

    display_lines = new_lines[:MAX_LINES_PER_COMPANY]
    for line in display_lines:
        truncated = _escape_markdown(_truncate_line(line))
        block_lines.append(f"  \u2022 {truncated}")

    remaining = len(new_lines) - MAX_LINES_PER_COMPANY
    if remaining > 0:
        block_lines.append(f"  _\\+{remaining} more_")

    block_lines.append(f"[\u2192 View page]({url})")

    return "\n".join(block_lines)


async def send_notification(bot: Bot, chat_id: int, changes: list[dict], check_time: str) -> None:
    """Send a summary message listing new job lines per company.

    Splits into multiple messages if exceeding the 4096 char Telegram limit.
    """
    if not changes:
        return

    header = "\U0001f514 *JobWatch \u2014 New Job Postings*\n"
    footer = f"\n_Checked at {_escape_markdown(check_time)}_"

    company_blocks = [_format_company_block(c) for c in changes]

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
            await bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
            logger.info("Notification %d/%d sent to %d.", i + 1, len(messages), chat_id)
        except Exception as e:
            logger.error("Failed to send notification %d/%d to %d: %s", i + 1, len(messages), chat_id, e)
