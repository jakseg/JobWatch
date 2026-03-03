"""Load and validate the JobWatch configuration from config.yaml."""

import logging
import sys
from pathlib import Path
from typing import TypedDict

import yaml

logger = logging.getLogger(__name__)


class CompanyConfig(TypedDict):
    name: str
    url: str
    keywords: list[str]


def load_config(path: Path = Path("config.yaml")) -> list[CompanyConfig]:
    """Load the watchlist from config.yaml and validate entries.

    Args:
        path: Path to the YAML config file.

    Returns:
        List of validated company configurations.
    """
    if not path.exists():
        logger.error("Config file not found: %s", path)
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict) or "companies" not in raw:
        logger.error("Config must contain a top-level 'companies' key.")
        sys.exit(1)

    companies: list[CompanyConfig] = []
    for i, entry in enumerate(raw["companies"]):
        if not isinstance(entry, dict):
            logger.error("Entry %d is not a valid mapping.", i)
            sys.exit(1)

        if "name" not in entry or "url" not in entry:
            logger.error(
                "Entry %d is missing required field 'name' or 'url'. Got: %s",
                i,
                entry,
            )
            sys.exit(1)

        companies.append(
            CompanyConfig(
                name=entry["name"],
                url=entry["url"],
                keywords=entry.get("keywords", []),
            )
        )

    logger.info("Loaded %d companies from config.", len(companies))
    return companies
