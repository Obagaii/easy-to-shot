"""输出层的端口定义与任务结果类型。

剪贴板写入由 A 的平台适配模块实现；输出服务只依赖本模块声明的协议，
不持有窗口对象，也不直接调用 Qt API。
"""

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .service import OutputSnapshot


class TaskState(str, Enum):
    """输出任务的互斥状态。"""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BUSY = "busy"


@dataclass(frozen=True)
class TaskResult:
    """按 operation_id 关联的任务结果；错误码单独传递。"""

    operation_id: str
    state: TaskState
    error_code: str | None = None


class ClipboardWriteError(Exception):
    """剪贴板写入失败；输出服务转换为 failed 结果，由界面层提示。"""


class ClipboardWriter(Protocol):
    """A 在 platform/windows/clipboard.py 提供的 GUI 线程写入接口。"""

    def write_image(self, snapshot: "OutputSnapshot") -> None:
        """写入合成像素；失败时抛 ClipboardWriteError。"""

