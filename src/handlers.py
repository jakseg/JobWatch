"""Telegram command handlers for JobWatch."""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from src import database
from src.scheduler import check_user, reschedule_user, schedule_user

logger = logging.getLogger(__name__)

# Conversation states for /add
NAME, URL, KEYWORDS = range(3)


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
    user = database.get_or_create_user(chat_id, username)

    schedule_user(chat_id, user["notify_hour"], user["notify_minute"])

    await update.message.reply_text(
        "\U0001f514 *JobWatch*\n\n"
        "I monitor career pages and notify you about new job postings.\n\n"
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

    if cmd == "cmd_add":
        await query.message.reply_text("What's the company name?")
        # Store state so the conversation handler can pick it up
        context.user_data["_awaiting_add"] = True
    elif cmd == "cmd_list":
        # Reuse list logic
        companies = database.list_companies(chat_id)
        if not companies:
            await query.message.reply_text("No companies yet. Use /add to add one.")
        else:
            lines = []
            for i, c in enumerate(companies, 1):
                status = "\u23f8" if c["is_paused"] else "\u2705"
                keywords = c["keywords"] if c["keywords"] else "all"
                lines.append(f"{i}. {status} *{c['name']}*\n   Keywords: _{keywords}_")
            await query.message.reply_text("\n".join(lines), parse_mode="Markdown")
    elif cmd == "cmd_check":
        await query.message.reply_text("\u23f3 Running check...")
        await check_user(chat_id, context.bot)
        await query.message.reply_text("\u2705 Check complete.")
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
            lines = [f"{i}. {c['name']} — _{c['keywords'] or 'all'}_" for i, c in enumerate(companies, 1)]
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
        lines.append(f"{i}. {status} *{c['name']}*\n   Keywords: _{keywords}_")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# --- /add (conversation: NAME → URL → KEYWORDS) ---

async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("What's the company name?")
    return NAME


async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_name"] = update.message.text.strip()
    await update.message.reply_text("Send me the career page URL.")
    return URL


async def add_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    url = update.message.text.strip()
    if not url.startswith(("http://", "https://")):
        await update.message.reply_text("That doesn't look like a URL. Please start with http:// or https://")
        return URL

    context.user_data["new_url"] = url
    await update.message.reply_text(
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
        f"\u2705 *{name}* added.\nKeywords: _{kw_display}_\n\n"
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
    await update.message.reply_text(f"\u274c *{company['name']}* removed.", parse_mode="Markdown")


# --- /check ---

async def check_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.message.reply_text("\u23f3 Running check...")
    await check_user(chat_id, context.bot)
    await update.message.reply_text("\u2705 Check complete.")


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
    await update.message.reply_text(f"\u23f8 *{company['name']}* paused.", parse_mode="Markdown")


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
    await update.message.reply_text(f"\u25b6 *{company['name']}* resumed.", parse_mode="Markdown")


# --- /keywords ---

async def keywords_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    companies = database.list_companies(chat_id)

    if not companies:
        await update.message.reply_text("No companies found.")
        return

    if not context.args:
        lines = [f"{i}. {c['name']} — _{c['keywords'] or 'all'}_" for i, c in enumerate(companies, 1)]
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
            f"*{company['name']}*: _{kw}_\n\n"
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
        f"\u2705 Keywords for *{company['name']}*: _{kw_display}_",
        parse_mode="Markdown",
    )
