from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    database_path: str = "swapmeet_astana.sqlite3"
    publication_chat_id: str | int = "@swapmeet_astana"
    buy_daily_limit: int = 2
    user_daily_ad_limit: int = 10
    user_hourly_ad_limit: int = 5
    duplicate_photo_days: int = 7
    retention_period_days: int = 7
    admin_ids: tuple[int, ...] = ()


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def load_settings() -> Settings:
    env_path = find_dotenv(usecwd=True)
    load_dotenv(env_path)
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is required. Put it into .env or environment variables.")
    database_path = _resolve_database_path(os.getenv("DATABASE_PATH", "swapmeet_astana.sqlite3"), env_path)

    return Settings(
        bot_token=token,
        database_path=database_path,
        publication_chat_id=_get_chat_id(os.getenv("PUBLICATION_CHAT_ID", "@swapmeet_astana")),
        buy_daily_limit=_get_int("BUY_DAILY_LIMIT", 2),
        user_daily_ad_limit=_get_int("USER_DAILY_AD_LIMIT", 10),
        user_hourly_ad_limit=_get_int("USER_HOURLY_AD_LIMIT", 5),
        duplicate_photo_days=_get_int("DUPLICATE_PHOTO_DAYS", 7),
        retention_period_days=_get_int("RETENTION_PERIOD_DAYS", 7),
        admin_ids=_get_int_list("ADMIN_IDS"),
    )


def _resolve_database_path(value: str, env_path: str) -> str:
    path = Path(value).expanduser()
    if path.is_absolute():
        return str(path)
    base_dir = Path(env_path).parent if env_path else Path.cwd()
    return str(base_dir / path)


def _get_int_list(name: str) -> tuple[int, ...]:
    value = os.getenv(name, "").strip()
    if not value:
        return ()
    return tuple(int(item.strip()) for item in value.split(",") if item.strip())


def _get_chat_id(value: str) -> str | int:
    value = value.strip()
    if value.lstrip("-").isdigit():
        return int(value)
    return value
