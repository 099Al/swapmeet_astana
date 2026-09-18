from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class Ad:
    id: int
    user_id: int
    ad_type: str
    category: str
    description: str
    price: str | None
    address: str | None
    status: str
    created_at: str
    deleted_at: str | None
    reserved_by: int | None


@dataclass(frozen=True)
class AdMessage:
    ad_id: int
    chat_id: int
    message_id: int
    message_kind: str
    photo_index: int


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        parent = Path(path).expanduser().parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS market (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    ad_type TEXT NOT NULL CHECK(ad_type IN ('buy', 'sell')),
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    price TEXT,
                    address TEXT,
                    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'deleted')),
                    created_at TEXT NOT NULL,
                    deleted_at TEXT,
                    remove_reason TEXT,
                    reserved_by INTEGER,
                    reserved_at TEXT
                );

                CREATE TABLE IF NOT EXISTS market_photos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ad_id INTEGER NOT NULL REFERENCES market(id),
                    file_id TEXT NOT NULL,
                    file_unique_id TEXT NOT NULL,
                    image_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS hist_market (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ad_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    ad_type TEXT NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    price TEXT,
                    address TEXT,
                    created_at TEXT NOT NULL,
                    removed_at TEXT NOT NULL,
                    remove_reason TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ad_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ad_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    message_kind TEXT NOT NULL CHECK(message_kind IN ('photo', 'text')),
                    photo_index INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    UNIQUE(ad_id, chat_id, message_id)
                );

                CREATE TABLE IF NOT EXISTS admins (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_market_active_created
                    ON market(status, created_at);
                CREATE INDEX IF NOT EXISTS idx_market_user_created
                    ON market(user_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_market_photos_ad
                    ON market_photos(ad_id);
                CREATE INDEX IF NOT EXISTS idx_ad_messages_ad
                    ON ad_messages(ad_id);
                CREATE INDEX IF NOT EXISTS idx_ad_messages_chat
                    ON ad_messages(chat_id);
                """
            )

    def cleanup_old_ads(self, retention_days: int) -> None:
        cutoff = _start_of_day(datetime.now()) - timedelta(days=retention_days)
        removed_at = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            old_active = conn.execute(
                "SELECT * FROM market WHERE status = 'active' AND created_at < ?",
                (cutoff.isoformat(),),
            ).fetchall()
            for row in old_active:
                conn.execute(
                    """
                    INSERT INTO hist_market (
                        ad_id, user_id, username, ad_type, category, description, price, address,
                        created_at, removed_at, remove_reason
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"],
                        row["user_id"],
                        row["username"],
                        row["ad_type"],
                        row["category"],
                        row["description"],
                        row["price"],
                        row["address"],
                        row["created_at"],
                        removed_at,
                        "Истек срок показа",
                    ),
                )
            conn.execute("DELETE FROM market_photos WHERE ad_id IN (SELECT id FROM market WHERE created_at < ?)", (cutoff.isoformat(),))
            conn.execute("DELETE FROM ad_messages WHERE ad_id IN (SELECT id FROM market WHERE created_at < ?)", (cutoff.isoformat(),))
            conn.execute("DELETE FROM market WHERE created_at < ?", (cutoff.isoformat(),))

    def active_ads(self, retention_days: int, category: str | None = None) -> list[Ad]:
        cutoff = _start_of_day(datetime.now()) - timedelta(days=retention_days)
        sql = "SELECT * FROM market WHERE status = 'active' AND created_at >= ?"
        params: list[object] = [cutoff.isoformat()]
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY created_at DESC, id DESC"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_ad_from_row(row) for row in rows]

    def get_ad(self, ad_id: int) -> Ad | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM market WHERE id = ?", (ad_id,)).fetchone()
        return _ad_from_row(row) if row else None

    def get_ad_by_public_number(self, public_number: int) -> Ad | None:
        ad_id = public_number - 99999
        if ad_id < 1:
            return None
        return self.get_ad(ad_id)

    def ad_photos(self, ad_id: int) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT file_id FROM market_photos WHERE ad_id = ? ORDER BY id", (ad_id,)).fetchall()
        return [row["file_id"] for row in rows]

    def save_ad_message(
        self,
        *,
        ad_id: int,
        chat_id: int,
        message_id: int,
        message_kind: str,
        photo_index: int = 0,
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO ad_messages (
                    ad_id, chat_id, message_id, message_kind, photo_index, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (ad_id, chat_id, message_id, message_kind, photo_index, now),
            )

    def ad_messages(self, ad_id: int) -> list[AdMessage]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT ad_id, chat_id, message_id, message_kind, photo_index
                FROM ad_messages
                WHERE ad_id = ?
                ORDER BY id
                """,
                (ad_id,),
            ).fetchall()
        return [_ad_message_from_row(row) for row in rows]

    def ad_messages_for_chat(self, chat_id: int) -> list[AdMessage]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT ad_id, chat_id, message_id, message_kind, photo_index
                FROM ad_messages
                WHERE chat_id = ?
                ORDER BY id
                """,
                (chat_id,),
            ).fetchall()
        return [_ad_message_from_row(row) for row in rows]

    def ad_message_by_message_id(self, chat_id: int, message_id: int) -> AdMessage | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT ad_id, chat_id, message_id, message_kind, photo_index
                FROM ad_messages
                WHERE chat_id = ? AND message_id = ?
                """,
                (chat_id, message_id),
            ).fetchone()
        return _ad_message_from_row(row) if row else None

    def update_ad_message_photo_index(self, ad_id: int, chat_id: int, message_id: int, photo_index: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE ad_messages
                SET photo_index = ?
                WHERE ad_id = ? AND chat_id = ? AND message_id = ?
                """,
                (photo_index, ad_id, chat_id, message_id),
            )

    def delete_ad_messages_for_ad(self, ad_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM ad_messages WHERE ad_id = ?", (ad_id,))

    def delete_ad_messages_for_chat(self, chat_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM ad_messages WHERE chat_id = ?", (chat_id,))

    def upsert_admin(self, user_id: int, username: str | None = None) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO admins (user_id, username, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET username = excluded.username
                """,
                (user_id, username, now),
            )

    def is_admin(self, user_id: int) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,)).fetchone()
        return row is not None

    def count_user_ads_today(self, user_id: int, ad_type: str | None = None) -> int:
        start = _start_of_day(datetime.now()).isoformat()
        sql = "SELECT COUNT(*) FROM market WHERE user_id = ? AND created_at >= ?"
        params: list[object] = [user_id, start]
        if ad_type:
            sql += " AND ad_type = ?"
            params.append(ad_type)
        with self.connect() as conn:
            return int(conn.execute(sql, params).fetchone()[0])

    def find_duplicate_hash(
        self,
        user_id: int,
        hashes: list[str],
        duplicate_days: int,
        max_distance: int = 8,
    ) -> int | None:
        if not hashes:
            return None
        cutoff = _start_of_day(datetime.now()) - timedelta(days=duplicate_days)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT mp.ad_id, mp.image_hash
                FROM market_photos mp
                JOIN market m ON m.id = mp.ad_id
                WHERE m.user_id = ? AND m.ad_type = 'sell' AND m.created_at >= ?
                """,
                (user_id, cutoff.isoformat()),
            ).fetchall()
        for row in rows:
            existing = row["image_hash"]
            if any(_hamming_distance(existing, candidate) <= max_distance for candidate in hashes):
                return int(row["ad_id"])
        return None

    def create_ad(
        self,
        *,
        user_id: int,
        username: str | None,
        ad_type: str,
        category: str,
        description: str,
        price: str | None = None,
        address: str | None = None,
        photos: list[tuple[str, str, str]] | None = None,
    ) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO market (user_id, username, ad_type, category, description, price, address, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, username, ad_type, category, description, price, address, now),
            )
            ad_id = int(cursor.lastrowid)
            for file_id, file_unique_id, image_hash in photos or []:
                conn.execute(
                    """
                    INSERT INTO market_photos (ad_id, file_id, file_unique_id, image_hash, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (ad_id, file_id, file_unique_id, image_hash, now),
                )
        return ad_id

    def mark_deleted(self, ad_id: int, reason: str) -> None:
        removed_at = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM market WHERE id = ?", (ad_id,)).fetchone()
            if row is None or row["status"] == "deleted":
                return
            conn.execute(
                """
                UPDATE market
                SET status = 'deleted', deleted_at = ?, remove_reason = ?, reserved_by = NULL, reserved_at = NULL
                WHERE id = ?
                """,
                (removed_at, reason, ad_id),
            )
            conn.execute(
                """
                INSERT INTO hist_market (
                    ad_id, user_id, username, ad_type, category, description, price, address,
                    created_at, removed_at, remove_reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["user_id"],
                    row["username"],
                    row["ad_type"],
                    row["category"],
                    row["description"],
                    row["price"],
                    row["address"],
                    row["created_at"],
                    removed_at,
                    reason,
                ),
            )

    def reserve(self, ad_id: int, user_id: int) -> bool:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE market
                SET reserved_by = ?, reserved_at = ?
                WHERE id = ? AND status = 'active' AND reserved_by IS NULL
                """,
                (user_id, now, ad_id),
            )
            return cursor.rowcount == 1

    def release_reserve(self, ad_id: int, requester_id: int) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE market
                SET reserved_by = NULL, reserved_at = NULL
                WHERE id = ? AND status = 'active' AND (user_id = ? OR reserved_by = ?)
                """,
                (ad_id, requester_id, requester_id),
            )
            return cursor.rowcount == 1


def _start_of_day(value: datetime) -> datetime:
    return datetime.combine(value.date(), time.min)


def _ad_from_row(row: sqlite3.Row) -> Ad:
    return Ad(
        id=int(row["id"]),
        user_id=int(row["user_id"]),
        ad_type=str(row["ad_type"]),
        category=str(row["category"]),
        description=str(row["description"]),
        price=row["price"],
        address=row["address"],
        status=str(row["status"]),
        created_at=str(row["created_at"]),
        deleted_at=row["deleted_at"],
        reserved_by=row["reserved_by"],
    )


def _ad_message_from_row(row: sqlite3.Row) -> AdMessage:
    return AdMessage(
        ad_id=int(row["ad_id"]),
        chat_id=int(row["chat_id"]),
        message_id=int(row["message_id"]),
        message_kind=str(row["message_kind"]),
        photo_index=int(row["photo_index"]),
    )


def _hamming_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()
