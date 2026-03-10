"""One-time migration from config.yaml + state.json to SQLite."""

import json
import sys
from pathlib import Path

from src.config_loader import load_config
from src.database import add_company, get_or_create_user, init_db, save_lines

STATE_FILE = Path("data/state.json")


def _load_old_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    with open(STATE_FILE, encoding="utf-8") as f:
        return json.load(f)


def migrate(chat_id: int, username: str = "migrated_user") -> None:
    init_db()
    get_or_create_user(chat_id, username)

    companies = load_config()
    old_state = _load_old_state()

    migrated = 0
    for company in companies:
        try:
            company_id = add_company(
                chat_id=chat_id,
                name=company["name"],
                url=company["url"],
                keywords=company["keywords"],
            )
        except Exception as e:
            print(f"  Skipping {company['name']}: {e}")
            continue

        if company["url"] in old_state:
            lines = set(old_state[company["url"]].get("lines", []))
            save_lines(company_id, lines)

        migrated += 1
        print(f"  Migrated: {company['name']}")

    print(f"\nDone. {migrated}/{len(companies)} companies migrated for chat_id {chat_id}.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.migrate <telegram_chat_id>")
        sys.exit(1)
    migrate(int(sys.argv[1]))
