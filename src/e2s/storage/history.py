"""历史索引、应用自有 PNG 与结果去重。

历史记录位于应用数据目录，不触碰用户另存文件；任何写入失败都返回稳定状态，
不影响已经完成的复制、保存或贴图结果。
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from e2s.output.files import encode_png

if TYPE_CHECKING:
    from e2s.output.service import OutputSnapshot

DEFAULT_HISTORY_LIMIT = 100

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history_items (
    history_item_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    result_revision INTEGER NOT NULL,
    created_at_utc TEXT NOT NULL,
    source TEXT NOT NULL,
    width_px INTEGER NOT NULL,
    height_px INTEGER NOT NULL,
    byte_count INTEGER NOT NULL,
    image_key TEXT NOT NULL,
    UNIQUE (session_id, result_revision)
);
CREATE INDEX IF NOT EXISTS idx_history_items_created
    ON history_items (created_at_utc DESC);
"""

_INSERT = """
INSERT INTO history_items (
    history_item_id, session_id, result_revision, created_at_utc,
    source, width_px, height_px, byte_count, image_key
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SELECT_FIELDS = """
SELECT history_item_id, session_id, result_revision, created_at_utc,
       source, width_px, height_px, byte_count, image_key
FROM history_items
"""


class HistoryStatus(StrEnum):
    """历史写入与查询的稳定状态值。"""

    RECORDED = "recorded"
    DUPLICATE = "duplicate"
    DISABLED = "disabled"
    SKIPPED = "skipped"
    WRITE_FAILED = "write_failed"
    DATABASE_FAILED = "database_failed"
    NOT_FOUND = "not_found"
    DELETED = "deleted"


@dataclass(frozen=True)
class HistoryItem:
    """一条历史索引，字段与 SQLite 的 snake_case 列一一对应。"""

    history_item_id: str
    session_id: str
    result_revision: int
    created_at_utc: str
    source: str
    width_px: int
    height_px: int
    byte_count: int
    image_key: str


@dataclass(frozen=True)
class HistoryResult:
    """历史写入结果；失败时 error_code 供界面提示。"""

    status: HistoryStatus
    item: HistoryItem | None = None
    error_code: str = ""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_item(row: tuple[object, ...]) -> HistoryItem:
    return HistoryItem(*row)  # type: ignore[arg-type]


def _item_params(item: HistoryItem) -> tuple[object, ...]:
    return (
        item.history_item_id,
        item.session_id,
        item.result_revision,
        item.created_at_utc,
        item.source,
        item.width_px,
        item.height_px,
        item.byte_count,
        item.image_key,
    )


class HistoryStore:
    """SQLite 索引 + 应用自有 PNG 的原子写入，按会话与结果修订去重。"""

    def __init__(
        self,
        root: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._root = Path(root)
        self._history_dir = self._root / "history"
        self._images_dir = self._history_dir / "images"
        self._db_path = self._history_dir / "index.sqlite3"
        self._clock = clock or _utc_now

    @property
    def db_path(self) -> Path:
        return self._db_path

    def image_path(self, item: HistoryItem) -> Path:
        """返回应用自有图像路径，与用户另存目录隔离。"""
        return self._images_dir / item.image_key

    def is_available(self, item: HistoryItem) -> bool:
        return self.image_path(item).is_file()

    def record(
        self,
        snapshot: "OutputSnapshot",
        source: str,
        *,
        is_enabled: bool = True,
    ) -> HistoryResult:
        if not is_enabled:
            return HistoryResult(HistoryStatus.DISABLED)
        try:
            self._ensure_schema()
            existing = self._find_duplicate(snapshot.session_id, snapshot.revision)
        except (sqlite3.Error, OSError):
            return HistoryResult(
                HistoryStatus.DATABASE_FAILED, error_code="database_unavailable"
            )
        if existing is not None:
            return HistoryResult(HistoryStatus.DUPLICATE, item=existing)
        try:
            payload = encode_png(snapshot)
        except (ValueError, OSError):
            return HistoryResult(HistoryStatus.WRITE_FAILED, error_code="encode_failed")

        item_id = str(uuid.uuid4())
        image_key = f"{item_id}.png"
        if not self._write_image(image_key, payload):
            return HistoryResult(HistoryStatus.WRITE_FAILED, error_code="image_write_failed")
        item = HistoryItem(
            history_item_id=item_id,
            session_id=snapshot.session_id,
            result_revision=snapshot.revision,
            created_at_utc=self._clock().astimezone(timezone.utc).isoformat(),
            source=source,
            width_px=snapshot.width_px,
            height_px=snapshot.height_px,
            byte_count=len(payload),
            image_key=image_key,
        )
        if not self._insert_item(item):
            self._remove_image(image_key)
            concurrent = self._find_duplicate_safe(item.session_id, item.result_revision)
            if concurrent is not None:
                return HistoryResult(HistoryStatus.DUPLICATE, item=concurrent)
            return HistoryResult(
                HistoryStatus.DATABASE_FAILED, error_code="database_write_failed"
            )
        return HistoryResult(HistoryStatus.RECORDED, item=item)

    def list_recent(
        self, limit: int = DEFAULT_HISTORY_LIMIT, offset: int = 0
    ) -> tuple[HistoryItem, ...]:
        try:
            self._ensure_schema()
            with closing(sqlite3.connect(self._db_path)) as conn:
                rows = conn.execute(
                    _SELECT_FIELDS + " ORDER BY created_at_utc DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
            return tuple(_row_to_item(row) for row in rows)
        except (sqlite3.Error, OSError):
            return ()

    def count(self) -> int:
        try:
            self._ensure_schema()
            with closing(sqlite3.connect(self._db_path)) as conn:
                return int(conn.execute("SELECT COUNT(*) FROM history_items").fetchone()[0])
        except (sqlite3.Error, OSError):
            return 0

    def _ensure_schema(self) -> None:
        self._images_dir.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._db_path)) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def _find_duplicate(self, session_id: str, revision: int) -> HistoryItem | None:
        with closing(sqlite3.connect(self._db_path)) as conn:
            row = conn.execute(
                _SELECT_FIELDS + " WHERE session_id = ? AND result_revision = ?",
                (session_id, revision),
            ).fetchone()
        return _row_to_item(row) if row else None

    def _find_duplicate_safe(self, session_id: str, revision: int) -> HistoryItem | None:
        try:
            return self._find_duplicate(session_id, revision)
        except (sqlite3.Error, OSError):
            return None

    def _insert_item(self, item: HistoryItem) -> bool:
        try:
            with closing(sqlite3.connect(self._db_path)) as conn:
                conn.execute(_INSERT, _item_params(item))
                conn.commit()
            return True
        except sqlite3.Error:
            return False

    def _write_image(self, image_key: str, payload: bytes) -> bool:
        temp_path: Path | None = None
        try:
            descriptor, name = tempfile.mkstemp(
                prefix=".history-", suffix=".tmp", dir=self._images_dir
            )
            temp_path = Path(name)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self._images_dir / image_key)
            return True
        except OSError:
            return False
        finally:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def _remove_image(self, image_key: str) -> None:
        try:
            (self._images_dir / image_key).unlink(missing_ok=True)
        except OSError:
            pass
