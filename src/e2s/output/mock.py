"""开发期的剪贴板模拟实现，结构与真实 WebChannel / GUI 写入接口一致。"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .ports import ClipboardWriteError

if TYPE_CHECKING:
    from .service import OutputSnapshot


@dataclass
class MockClipboardWriter:
    """记录写入的快照；fail_next_write 用于复现失败分支。"""

    written: list["OutputSnapshot"] = field(default_factory=list)
    fail_next_write: bool = False

    def write_image(self, snapshot: "OutputSnapshot") -> None:
        if self.fail_next_write:
            self.fail_next_write = False
            raise ClipboardWriteError("模拟剪贴板写入失败")
        self.written.append(snapshot)
