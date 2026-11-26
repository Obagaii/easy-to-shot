"""输出快照与复制服务。

后台任务只接收确认输出时生成的不可变快照，不读取活动画布或窗口。
"""

from dataclasses import dataclass, field
from typing import Callable, Mapping

from e2s.capture.history_payload import HistoryPayload

from .ports import ClipboardWriteError, ClipboardWriter, TaskResult, TaskState


@dataclass(frozen=True)
class OutputSnapshot:
    """确认输出时生成的不可变快照。

    pixels 为合成像素的独立副本；parameters 只由界面层构造，服务不修改其内容。
    """

    operation_id: str
    session_id: str
    revision: int
    width_px: int
    height_px: int
    pixels: bytes
    parameters: Mapping[str, object] = field(default_factory=dict)
    history_data: HistoryPayload | None = None

    def __post_init__(self) -> None:
        if self.width_px <= 0 or self.height_px <= 0:
            raise ValueError("快照像素尺寸必须为正数")
        if not self.pixels:
            raise ValueError("快照像素不能为空")


class OutputService:
    """调度输出快照到剪贴板，并把结果封装为稳定的状态值与错误码。"""

    def __init__(
        self,
        writer: ClipboardWriter,
        *,
        is_queue_full: Callable[[], bool] | None = None,
    ) -> None:
        self._writer = writer
        self._is_queue_full = is_queue_full or (lambda: False)

    def copy_image_to_clipboard(
        self,
        snapshot: OutputSnapshot,
        *,
        is_cancelled: bool = False,
    ) -> TaskResult:
        """复制合成像素；失败时保留快照，允许按同一 operation_id 重试。"""

        operation_id = snapshot.operation_id
        if is_cancelled:
            return TaskResult(operation_id, TaskState.CANCELLED)
        if self._is_queue_full():
            return TaskResult(operation_id, TaskState.BUSY, "queue_full")
        try:
            self._writer.write_image(snapshot)
        except ClipboardWriteError:
            return TaskResult(operation_id, TaskState.FAILED, "clipboard_write_failed")
        return TaskResult(operation_id, TaskState.SUCCEEDED)
