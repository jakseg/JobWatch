"""Telegram command handlers for JobWatch."""

import ipaddress
import logging
import os
import socket
from urllib.parse import urlparse

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from src import database
from src.career_search import is_search_available, search_career_pages
from src.scheduler import check_user, reschedule_user, schedule_user

logger = logging.getLogger(__name__)

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _is_safe_url(url: str) -> bool:
    try:
        hostname = urlparse(url).hostname
        if not hostname:
            return False
        for addr_info in socket.getaddrinfo(hostname, None):
            ip = ipaddress.ip_address(addr_info[4][0])
            if any(ip in net for net in _BLOCKED_NETWORKS):
                return False
    except (socket.gaierror, ValueError):
        return False
    return True


def _escape_md(text: str) -> str:
    for char in ("_", "*", "`", "["):
        text = text.replace(char, f"\\{char}")
    return text

# Conversation states for /add
NAME, URL, KEYWORDS, LOCATION, URL_SELECT = range(5)


def _main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\u2795 Add", callback_data="cmd_add"),
            InlineKeyboardButton("\u2796 Remove", callback_data="cmd_remove"),
        ],
        [
            InlineKeyboardButton("\U0001f4cb List", callback_data="cmd_list"),
            InlineKeyboardButton("\U0001f50d Check now", callback_data="cmd_check"),
        ],
        [
            InlineKeyboardButton("\U0001f4bc All Jobs", callback_data="cmd_jobs"),
        ],
        [
            InlineKeyboardButton("\u23f0 Time", callback_data="cmd_time"),
            InlineKeyboardButton("\u23f8 Pause", callback_data="cmd_pause"),
        ],
        [
            InlineKeyboardButton("\u25b6\ufe0f Resume", callback_data="cmd_resume"),
            InlineKeyboardButton("\U0001f511 Keywords", callback_data="cmd_keywords"),
        ],
    ])


# --- /start ---

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    username = update.effective_user.username

    # Check if this is a new user
    is_new = database.get_user(chat_id) is None
    user = database.get_or_create_user(chat_id, username)

    schedule_user(chat_id, user["notify_hour"], user["notify_minute"])

    if is_new:
        await update.message.reply_text(
            "\U0001f514 *Welcome to JobWatch\!*\n\n"
            "I monitor company career pages and notify you when new job postings appear\\.\n\n"
            "*How it works:*\n"
            "1\\. Add companies you're interested in\n"
            "2\\. I'll check their career pages daily\n"
            "3\\. You get notified about new postings\n\n"
            "*Buttons explained:*\n"
            "\u2795 *Add* — Track a new company\n"
            "\u2796 *Remove* — Stop tracking a company\n"
            "\U0001f4cb *List* — Show all tracked companies\n"
            "\U0001f50d *Check now* — Run an immediate check\n"
            "\u23f0 *Time* — Change your daily notification time\n"
            "\u23f8 *Pause* / \u25b6\ufe0f *Resume* — Pause or resume tracking\n"
            "\U0001f511 *Keywords* — Filter postings by keywords\n\n"
            "Let's get started\! Tap *Add* to track your first company\\.",
            parse_mode="MarkdownV2",
            reply_markup=_main_keyboard(),
        )
    else:
        await update.message.reply_text(
            "\U0001f514 *JobWatch*\n\n"
            "What would you like to do?",
            parse_mode="Markdown",
            reply_markup=_main_keyboard(),
        )


# --- /help ---

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "What would you like to do?",
        reply_markup=_main_keyboard(),
    )


# --- Inline keyboard callback ---

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    cmd = query.data
    chat_id = query.message.chat_id

    if cmd == "cmd_list":
        # Reuse list logic
        companies = database.list_companies(chat_id)
        if not companies:
            await query.message.reply_text("No companies yet. Use /add to add one.")
        else:
            lines = []
            for i, c in enumerate(companies, 1):
                status = "\u23f8" if c["is_paused"] else "\u2705"
                keywords = c["keywords"] if c["keywords"] else "all"
                lines.append(f"{i}. {status} *{_escape_md(c['name'])}*\n   Keywords: _{_escape_md(keywords)}_")
            await query.message.reply_text("\n".join(lines), parse_mode="Markdown")
    elif cmd == "cmd_check":
        await query.message.reply_text("\u23f3 Running check...")
        await check_user(chat_id, context.bot)
        await query.message.reply_text(
            "\u2705 Check complete.",
            reply_markup=_main_keyboard(),
        )
    elif cmd == "cmd_jobs":
        await _show_jobs_picker(chat_id, query.message.reply_text)
    elif cmd.startswith("jobs_"):
        try:
            idx = int(cmd.replace("jobs_", ""))
        except ValueError:
            await query.message.reply_text("Invalid selection.")
            return
        await _send_company_jobs(chat_id, idx, query.message.reply_text)
    elif cmd == "cmd_remove":
        companies = database.list_companies(chat_id)
        if not companies:
            await query.message.reply_text("No companies found.")
        else:
            lines = [f"{i}. {c['name']}" for i, c in enumerate(companies, 1)]
            await query.message.reply_text(
                "Which company to remove?\n" + "\n".join(lines) + "\n\nReply: /remove <number>"
            )
    elif cmd == "cmd_time":
        user = database.get_or_create_user(chat_id)
        await query.message.reply_text(
            f"Current time: {user['notify_hour']:02d}:{user['notify_minute']:02d} UTC\n"
            "Change: /time HH:MM"
        )
    elif cmd == "cmd_pause":
        companies = database.list_companies(chat_id)
        active = [c for c in companies if not c["is_paused"]]
        if not active:
            await query.message.reply_text("No active companies to pause.")
        else:
            lines = [f"{i}. {c['name']}" for i, c in enumerate(active, 1)]
            await query.message.reply_text(
                "Which company to pause?\n" + "\n".join(lines) + "\n\nReply: /pause <number>"
            )
    elif cmd == "cmd_resume":
        companies = database.list_companies(chat_id)
        paused = [c for c in companies if c["is_paused"]]
        if not paused:
            await query.message.reply_text("No paused companies.")
        else:
            lines = [f"{i}. {c['name']}" for i, c in enumerate(paused, 1)]
            await query.message.reply_text(
                "Which company to resume?\n" + "\n".join(lines) + "\n\nReply: /resume <number>"
            )
    elif cmd == "cmd_keywords":
        companies = database.list_companies(chat_id)
        if not companies:
            await query.message.reply_text("No companies found.")
        else:
            lines = [f"{i}. {_escape_md(c['name'])} — _{_escape_md(c['keywords'] or 'all')}_" for i, c in enumerate(companies, 1)]
            await query.message.reply_text(
                "Change keywords:\n" + "\n".join(lines) + "\n\nReply: /keywords <number> <keywords>",
                parse_mode="Markdown",
            )


# --- /list ---

async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    companies = database.list_companies(chat_id)

    if not companies:
        await update.message.reply_text("No companies yet. Use /add to add one.")
        return

    lines = []
    for i, c in enumerate(companies, 1):
        status = "\u23f8" if c["is_paused"] else "\u2705"
        keywords = c["keywords"] if c["keywords"] else "all"
        lines.append(f"{i}. {status} *{_escape_md(c['name'])}*\n   Keywords: _{_escape_md(keywords)}_")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# --- /add (conversation: NAME → URL → KEYWORDS) ---

async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("What's the company name?")
    return NAME


async def add_start_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("What's the company name?")
    return NAME


async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_name"] = update.message.text.strip()
    if is_search_available():
        await update.message.reply_text(
            "\u26a0\ufe0f _Auto-search is in beta — results may not always be accurate._\n\n"
            "Location? (e.g. Berlin, Munich)\n"
            "Or /skip to search without location filter.",
            parse_mode="Markdown",
        )
        return LOCATION
    await update.message.reply_text("Send me the career page URL.")
    return URL


async def add_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    url = update.message.text.strip()
    if not url.startswith(("http://", "https://")):
        await update.message.reply_text("That doesn't look like a URL. Please start with http:// or https://")
        return URL
    if not _is_safe_url(url):
        await update.message.reply_text("This URL points to a private/internal address and is not allowed.")
        return URL

    context.user_data["new_url"] = url
    await update.message.reply_text(
        "Optional: Send keywords separated by commas (e.g. Werkstudent, Working Student).\n"
        "Or /skip to track all changes."
    )
    return KEYWORDS


async def add_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    location = None if text == "/skip" else text
    name = context.user_data["new_name"]

    await update.message.reply_text("\U0001f50d Searching career pages...")
    results = await search_career_pages(name, location)

    if not results:
        await update.message.reply_text(
            "No career pages found. Please send the URL manually."
        )
        return URL

    context.user_data["search_results"] = results
    buttons = []
    for i, r in enumerate(results):
        # Truncate URL for display
        display = r["url"]
        if len(display) > 60:
            display = display[:57] + "..."
        buttons.append([InlineKeyboardButton(display, callback_data=f"select_url_{i}")])
    buttons.append([InlineKeyboardButton("\u270f Enter URL manually", callback_data="select_url_manual")])

    await update.message.reply_text(
        "Select a career page:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return URL_SELECT


async def add_url_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle manual URL input in URL_SELECT state."""
    url = update.message.text.strip()
    if not url.startswith(("http://", "https://")):
        await update.message.reply_text("That doesn't look like a URL. Please start with http:// or https://")
        return URL_SELECT
    if not _is_safe_url(url):
        await update.message.reply_text("This URL points to a private/internal address and is not allowed.")
        return URL_SELECT

    context.user_data["new_url"] = url
    context.user_data.pop("search_results", None)
    await update.message.reply_text(
        "Optional: Send keywords separated by commas (e.g. Werkstudent, Working Student).\n"
        "Or /skip to track all changes."
    )
    return KEYWORDS


async def add_url_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle inline button selection for search results."""
    query = update.callback_query
    await query.answer()

    if query.data == "select_url_manual":
        await query.message.reply_text("Send me the career page URL.")
        return URL_SELECT

    try:
        idx = int(query.data.replace("select_url_", ""))
        results = context.user_data.get("search_results", [])
        result = results[idx]
    except (ValueError, IndexError):
        await query.message.reply_text("Invalid selection. Send me the URL manually.")
        return URL_SELECT

    context.user_data["new_url"] = result["url"]
    context.user_data.pop("search_results", None)
    await query.message.reply_text(
        f"Selected: {result['url']}\n\n"
        "Optional: Send keywords separated by commas (e.g. Werkstudent, Working Student).\n"
        "Or /skip to track all changes."
    )
    return KEYWORDS


async def add_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    keywords = [] if text == "/skip" else [k.strip() for k in text.split(",") if k.strip()]

    chat_id = update.effective_chat.id
    name = context.user_data.pop("new_name")
    url = context.user_data.pop("new_url")

    try:
        database.add_company(chat_id, name, url, keywords)
    except Exception:
        await update.message.reply_text("This URL is already in your list.")
        return ConversationHandler.END

    kw_display = ", ".join(keywords) if keywords else "all"
    await update.message.reply_text(
        f"\u2705 *{_escape_md(name)}* added.\nKeywords: _{_escape_md(kw_display)}_\n\n"
        "The first check will establish a baseline (no notification).",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("new_name", None)
    context.user_data.pop("new_url", None)
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# --- /remove ---

async def remove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    companies = database.list_companies(chat_id)

    if not companies:
        await update.message.reply_text("No companies found.")
        return

    if not context.args:
        lines = [f"{i}. {c['name']}" for i, c in enumerate(companies, 1)]
        await update.message.reply_text(
            "Which company to remove?\n" + "\n".join(lines) + "\n\nReply: /remove <number>"
        )
        return

    try:
        idx = int(context.args[0]) - 1
        company = companies[idx]
    except (ValueError, IndexError):
        await update.message.reply_text("Invalid number.")
        return

    database.remove_company(chat_id, company["id"])
    await update.message.reply_text(f"\u274c *{_escape_md(company['name'])}* removed.", parse_mode="Markdown")


# --- /check ---

async def check_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.message.reply_text("\u23f3 Running check...")
    await check_user(chat_id, context.bot)
    await update.message.reply_text(
        "\u2705 Check complete.",
        reply_markup=_main_keyboard(),
    )


# --- /time ---

async def time_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        user = database.get_or_create_user(update.effective_chat.id)
        await update.message.reply_text(
            f"Current time: {user['notify_hour']:02d}:{user['notify_minute']:02d} UTC\n"
            "Change: /time HH:MM"
        )
        return

    try:
        parts = context.args[0].split(":")
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except (ValueError, IndexError):
        await update.message.reply_text("Format: /time HH:MM (e.g. /time 09:30)")
        return

    chat_id = update.effective_chat.id
    database.update_notify_time(chat_id, hour, minute)
    reschedule_user(chat_id, hour, minute)
    await update.message.reply_text(f"\u2705 Notification time set to {hour:02d}:{minute:02d} UTC.")


# --- /pause ---

async def pause_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    companies = database.list_companies(chat_id)
    active = [c for c in companies if not c["is_paused"]]

    if not active:
        await update.message.reply_text("No active companies to pause.")
        return

    if not context.args:
        lines = [f"{i}. {c['name']}" for i, c in enumerate(active, 1)]
        await update.message.reply_text(
            "Which company to pause?\n" + "\n".join(lines) + "\n\nReply: /pause <number>"
        )
        return

    try:
        idx = int(context.args[0]) - 1
        company = active[idx]
    except (ValueError, IndexError):
        await update.message.reply_text("Invalid number.")
        return

    database.set_company_paused(company["id"], True)
    await update.message.reply_text(f"\u23f8 *{_escape_md(company['name'])}* paused.", parse_mode="Markdown")


# --- /resume ---

async def resume_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    companies = database.list_companies(chat_id)
    paused = [c for c in companies if c["is_paused"]]

    if not paused:
        await update.message.reply_text("No paused companies.")
        return

    if not context.args:
        lines = [f"{i}. {c['name']}" for i, c in enumerate(paused, 1)]
        await update.message.reply_text(
            "Which company to resume?\n" + "\n".join(lines) + "\n\nReply: /resume <number>"
        )
        return

    try:
        idx = int(context.args[0]) - 1
        company = paused[idx]
    except (ValueError, IndexError):
        await update.message.reply_text("Invalid number.")
        return

    database.set_company_paused(company["id"], False)
    await update.message.reply_text(f"\u25b6 *{_escape_md(company['name'])}* resumed.", parse_mode="Markdown")


# --- /keywords ---

async def keywords_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    companies = database.list_companies(chat_id)

    if not companies:
        await update.message.reply_text("No companies found.")
        return

    if not context.args:
        lines = [f"{i}. {_escape_md(c['name'])} — _{_escape_md(c['keywords'] or 'all')}_" for i, c in enumerate(companies, 1)]
        await update.message.reply_text(
            "Change keywords:\n" + "\n".join(lines) + "\n\nReply: /keywords <number> <keywords>",
            parse_mode="Markdown",
        )
        return

    try:
        idx = int(context.args[0]) - 1
        company = companies[idx]
    except (ValueError, IndexError):
        await update.message.reply_text("Invalid number.")
        return

    if len(context.args) < 2:
        kw = company["keywords"] or "all"
        await update.message.reply_text(
            f"*{_escape_md(company['name'])}*: _{_escape_md(kw)}_\n\n"
            f"Change: /keywords {idx + 1} Werkstudent, Working Student\n"
            f"Clear: /keywords {idx + 1} all",
            parse_mode="Markdown",
        )
        return

    raw = " ".join(context.args[1:])
    keywords = [] if raw.lower() == "all" else [k.strip() for k in raw.split(",") if k.strip()]

    database.update_keywords(company["id"], keywords)
    kw_display = ", ".join(keywords) if keywords else "all"
    await update.message.reply_text(
        f"\u2705 Keywords for *{_escape_md(company['name'])}*: _{_escape_md(kw_display)}_",
        parse_mode="Markdown",
    )


# --- /jobs ---

_JOBS_NOISE = [
    "Show more", "Load more", "Mehr anzeigen", "Weitere",
    "Cookie", "Accept", "Decline", "Privacy", "Datenschutz",
    "Home", "Menu", "Navigation", "Footer", "Header", "Breadcrumb",
]

MAX_JOBS_MESSAGE = 4096
MAX_LINES_PER_COMPANY = 15


def _filter_job_lines(lines: list[str], keywords: str) -> list[str]:
    """Filter out noise and optionally highlight keyword matches."""
    import re
    filtered = []
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped or len(line_stripped) < 10:
            continue
        if any(line_stripped.lower().startswith(n.lower()) for n in _JOBS_NOISE):
            continue
        if re.match(r"^\d+\s*/\s*\d+", line_stripped):
            continue
        if re.match(r"^\d+$", line_stripped):
            continue
        filtered.append(line_stripped)
    return filtered


async def _show_jobs_picker(chat_id: int, reply_func) -> None:
    """Show inline buttons to pick a company for job listing."""
    data = database.get_all_jobs(chat_id)

    if not data:
        await reply_func("No companies tracked yet. Use /add to get started.")
        return

    companies_with_data = [d for d in data if d["lines"]]
    if not companies_with_data:
        await reply_func(
            "No job data yet. Run /check first to scan your career pages.",
            reply_markup=_main_keyboard(),
        )
        return

    buttons = []
    for i, company in enumerate(companies_with_data):
        lines = _filter_job_lines(company["lines"], company["keywords"])
        count = len(lines)
        buttons.append([InlineKeyboardButton(
            f"\U0001f3e2 {company['name']} ({count})",
            callback_data=f"jobs_{i}",
        )])

    await reply_func(
        "\U0001f4bc *Which company's jobs do you want to see?*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _send_company_jobs(chat_id: int, company_index: int, reply_func) -> None:
    """Send all stored job lines for a specific company."""
    data = database.get_all_jobs(chat_id)
    companies_with_data = [d for d in data if d["lines"]]

    if company_index >= len(companies_with_data):
        await reply_func("Company not found.")
        return

    company = companies_with_data[company_index]
    name = _escape_md(company["name"])
    url = company["url"]
    lines = _filter_job_lines(company["lines"], company["keywords"])

    if not lines:
        await reply_func(f"No job postings found for *{name}*.", parse_mode="Markdown")
        return

    messages = []
    current = f"\U0001f3e2 *{name}* — {len(lines)} postings\n\n"

    for line in lines:
        truncated = line[:77] + "\u2026" if len(line) > 80 else line
        entry = f"\u2022 {_escape_md(truncated)}\n"

        if len(current) + len(entry) > MAX_JOBS_MESSAGE - 100:
            messages.append(current)
            current = f"\U0001f3e2 *{name}* (cont.)\n\n"

        current += entry

    current += f"\n[\u2192 View page]({url})"
    messages.append(current)

    for msg in messages:
        await reply_func(
            msg,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )


async def jobs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await _show_jobs_picker(chat_id, update.message.reply_text)


# --- /stats (admin only) ---

def _is_admin(chat_id: int) -> bool:
    admin_id = os.environ.get("ADMIN_CHAT_ID")
    return admin_id is not None and str(chat_id) == admin_id


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_chat.id):
        await update.message.reply_text("This command is only available to the bot admin.")
        return

    s = database.get_stats()

    top = "\n".join(
        f"   {i}. {_escape_md(c['name'])} ({c['c']} users)"
        for i, c in enumerate(s["top_companies"], 1)
    ) or "   No data yet"

    await update.message.reply_text(
        "\U0001f4ca *JobWatch Stats*\n\n"
        f"*Users:* {s['total_users']} total, {s['active_users']} active\n\n"
        f"*Companies:* {s['total_companies']} total\n"
        f"   \u2705 {s['active_companies']} active\n"
        f"   \u23f8 {s['paused_companies']} paused\n"
        f"   \U0001f511 {s['companies_with_keywords']} with keyword filters\n"
        f"   \U0001f50d {s['checked_companies']} checked at least once\n\n"
        f"*Avg companies per user:* {s['avg_companies_per_user']}\n\n"
        f"*Most tracked companies:*\n{top}",
        parse_mode="Markdown",
    )
