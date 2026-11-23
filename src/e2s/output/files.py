"""输出文件命名、PNG 编码、无覆盖保存与另存。"""

import io
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from PIL import Image

from .ports import TaskState

if TYPE_CHECKING:
    from .service import OutputSnapshot

FILENAME_PREFIX = "E2S"
MAX_SEQUENCE = 999


@dataclass(frozen=True)
class SaveResult:
    """保存任务结果；path 仅在成功时有值。"""

    operation_id: str
    state: TaskState
    path: Path | None = None
    error_code: str | None = None


def build_filename(timestamp: datetime, sequence: int = 0) -> str:
    """生成 E2S_yyyyMMdd_HHmmss.png；同秒冲突时追加 _01、_02…"""

    base = f"{FILENAME_PREFIX}_{timestamp:%Y%m%d_%H%M%S}"
    suffix = f"_{sequence:02d}" if sequence > 0 else ""
    return f"{base}{suffix}.png"


def encode_png(snapshot: "OutputSnapshot") -> bytes:
    """把合成 RGBA 像素编码为 PNG；不重新渲染活动画布。"""

    image = Image.frombytes(
        "RGBA", (snapshot.width_px, snapshot.height_px), snapshot.pixels
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class OutputFileService:
    """快速保存与另存：同目录临时文件 + 原子发布，失败不破坏已有文件。"""

    def __init__(
        self,
        output_directory: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._output_directory = output_directory
        self._clock = clock or datetime.now

    def quick_save(
        self,
        snapshot: "OutputSnapshot",
        *,
        is_cancelled: bool = False,
    ) -> SaveResult:
        """按时间戳生成唯一文件名；同秒同名自动加序号，绝不覆盖。"""

        operation_id = snapshot.operation_id
        if is_cancelled:
            return SaveResult(operation_id, TaskState.CANCELLED)
        if not self._output_directory.is_dir():
            return SaveResult(
                operation_id, TaskState.FAILED, error_code="directory_not_writable"
            )
        payload, error_code = self._encode_payload(snapshot)
        if payload is None:
            return SaveResult(operation_id, TaskState.FAILED, error_code=error_code)

        timestamp = self._clock()
        for sequence in range(MAX_SEQUENCE + 1):
            target = self._output_directory / build_filename(timestamp, sequence)
            try:
                self._publish_without_overwrite(payload, target)
            except FileExistsError:
                continue
            except PermissionError:
                return SaveResult(
                    operation_id, TaskState.FAILED, error_code="directory_not_writable"
                )
            except OSError:
                return SaveResult(
                    operation_id, TaskState.FAILED, error_code="write_failed"
                )
            return SaveResult(operation_id, TaskState.SUCCEEDED, path=target)
        return SaveResult(
            operation_id, TaskState.FAILED, error_code="too_many_collisions"
        )

    def save_as(
        self,
        snapshot: "OutputSnapshot",
        target: Path,
        *,
        is_overwrite_confirmed: bool = False,
        is_cancelled: bool = False,
    ) -> SaveResult:
        """另存到用户确认的路径；取消或未确认覆盖时绝不改动目标文件。"""

        operation_id = snapshot.operation_id
        if is_cancelled:
            return SaveResult(operation_id, TaskState.CANCELLED)
        if not target.parent.is_dir():
            return SaveResult(
                operation_id, TaskState.FAILED, error_code="directory_not_writable"
            )
        if target.exists() and not is_overwrite_confirmed:
            return SaveResult(
                operation_id, TaskState.CANCELLED, error_code="overwrite_not_confirmed"
            )
        payload, error_code = self._encode_payload(snapshot)
        if payload is None:
            return SaveResult(operation_id, TaskState.FAILED, error_code=error_code)
        try:
            if is_overwrite_confirmed:
                self._publish_with_overwrite(payload, target)
            else:
                self._publish_without_overwrite(payload, target)
        except FileExistsError:
            return SaveResult(
                operation_id, TaskState.CANCELLED, error_code="overwrite_not_confirmed"
            )
        except PermissionError:
            return SaveResult(
                operation_id, TaskState.FAILED, error_code="directory_not_writable"
            )
        except OSError:
            return SaveResult(operation_id, TaskState.FAILED, error_code="write_failed")
        return SaveResult(operation_id, TaskState.SUCCEEDED, path=target)

    @staticmethod
    def _encode_payload(snapshot: "OutputSnapshot") -> tuple[bytes | None, str | None]:
        try:
            return encode_png(snapshot), None
        except (ValueError, OSError):
            return None, "encode_failed"

    @staticmethod
    def _write_temp(payload: bytes, directory: Path) -> Path:
        """把完整内容写入同目录临时文件，失败时清理。"""

        descriptor, name = tempfile.mkstemp(prefix=".e2s-", suffix=".tmp", dir=directory)
        temp_path = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
        except OSError:
            temp_path.unlink(missing_ok=True)
            raise
        return temp_path

    @classmethod
    def _publish_without_overwrite(cls, payload: bytes, target: Path) -> None:
        """os.link 原子发布；目标已存在时抛 FileExistsError，由调用方换序号。"""

        temp_path = cls._write_temp(payload, target.parent)
        try:
            os.link(temp_path, target)
        finally:
            temp_path.unlink(missing_ok=True)

    @classmethod
    def _publish_with_overwrite(cls, payload: bytes, target: Path) -> None:
        """确认覆盖后用 os.replace 原子发布；临时文件由 replace 消费。"""

        temp_path = cls._write_temp(payload, target.parent)
        try:
            os.replace(temp_path, target)
        finally:
            temp_path.unlink(missing_ok=True)
