from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    database_path: str = "data/bot.db"
    fsm_storage: str = "memory"
    redis_url: str = "redis://localhost:6379/0"
    publication_chat_id: str | int = "@swapmeet_astana"
    communication_topic_id: int | None = None
    sell_topic_id: int | None = None
    find_topic_id: int | None = None
    communication_daily_message_limit: int = 20
    buy_daily_limit: int = 2
    user_daily_ad_limit: int = 10
    user_hourly_ad_limit: int = 5
    duplicate_photo_days: int = 7
    retention_period_days: int = 7
    retention_archive_period: int = 30
    repost_limit: int = 5
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
    database_path = str(_resolve_data_dir(os.getenv("DATA_DIR", "data"), env_path) / "bot.db")
    fsm_storage = os.getenv("FSM_STORAGE", "memory").strip().lower()
    if fsm_storage not in {"memory", "redis"}:
        raise RuntimeError("FSM_STORAGE must be either 'memory' or 'redis'.")

    return Settings(
        bot_token=token,
        database_path=database_path,
        fsm_storage=fsm_storage,
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0").strip(),
        publication_chat_id=_get_chat_id(os.getenv("PUBLICATION_CHAT_ID", "@swapmeet_astana")),
        communication_topic_id=_get_optional_int("COMMUNICATION_TOPIC_ID"),
        sell_topic_id=_get_optional_int("TOPIC_SELL_ID"),
        find_topic_id=_get_optional_int("TOPIC_FIND_ID"),
        communication_daily_message_limit=_get_int("COMMUNICATION_DAILY_MESSAGE_LIMIT", 20),
        buy_daily_limit=_get_int("BUY_DAILY_LIMIT", 2),
        user_daily_ad_limit=_get_int("USER_DAILY_AD_LIMIT", 10),
        user_hourly_ad_limit=_get_int("USER_HOURLY_AD_LIMIT", 5),
        duplicate_photo_days=_get_int("DUPLICATE_PHOTO_DAYS", 7),
        retention_period_days=_get_int("RETENTION_PERIOD_DAYS", 7),
        retention_archive_period=_get_int("RETENTION_ARCHIVE_PERIOD", 30),
        repost_limit=_get_int("REPOST_LIMIT", 5),
        admin_ids=_get_int_list("ADMIN_IDS"),
    )


def _resolve_data_dir(value: str, env_path: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    base_dir = Path(env_path).parent if env_path else Path.cwd()
    return base_dir / path


def _get_int_list(name: str) -> tuple[int, ...]:
    value = os.getenv(name, "").strip()
    if not value:
        return ()
    return tuple(int(item.strip()) for item in value.split(",") if item.strip())


def _get_optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    return int(value)


def _get_chat_id(value: str) -> str | int:
    value = value.strip()
    if value.lstrip("-").isdigit():
        return int(value)
    return value
