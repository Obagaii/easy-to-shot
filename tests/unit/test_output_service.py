"""B1 复制服务的单元测试。

以 unittest.TestCase 编写：当前环境未安装 pytest，用标准库即可运行；
pytest 安装后可直接收集同一批用例，无需改写。
"""

import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from e2s.output.mock import MockClipboardWriter  # noqa: E402
from e2s.output.ports import TaskState  # noqa: E402
from e2s.output.service import OutputService, OutputSnapshot  # noqa: E402


def build_snapshot() -> OutputSnapshot:
    """构造 2×2 合成色块，不含真实截图数据。"""

    return OutputSnapshot(
        operation_id="op-001",
        session_id="s-001",
        revision=1,
        width_px=2,
        height_px=2,
        pixels=b"\x01\x02\x03\x04",
        parameters={"format": "png"},
    )


class OutputServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.writer = MockClipboardWriter()
        self.service = OutputService(self.writer)
        self.snapshot = build_snapshot()

    def test_copy_writes_snapshot_and_returns_succeeded(self) -> None:
        result = self.service.copy_image_to_clipboard(self.snapshot)
        self.assertEqual(result.operation_id, "op-001")
        self.assertEqual(result.state, TaskState.SUCCEEDED)
        self.assertIsNone(result.error_code)
        self.assertEqual(self.writer.written, [self.snapshot])
        self.assertEqual(self.writer.written[0].pixels, self.snapshot.pixels)
        self.assertEqual(
            (self.writer.written[0].width_px, self.writer.written[0].height_px),
            (2, 2),
        )

    def test_failed_write_keeps_snapshot_for_retry(self) -> None:
        self.writer.fail_next_write = True
        failed = self.service.copy_image_to_clipboard(self.snapshot)
        self.assertEqual(failed.state, TaskState.FAILED)
        self.assertEqual(failed.error_code, "clipboard_write_failed")
        self.assertEqual(self.writer.written, [])

        retried = self.service.copy_image_to_clipboard(self.snapshot)
        self.assertEqual(retried.state, TaskState.SUCCEEDED)
        self.assertEqual(retried.operation_id, failed.operation_id)
        self.assertEqual(self.writer.written, [self.snapshot])

    def test_cancelled_does_not_write(self) -> None:
        result = self.service.copy_image_to_clipboard(self.snapshot, is_cancelled=True)
        self.assertEqual(result.state, TaskState.CANCELLED)
        self.assertIsNone(result.error_code)
        self.assertEqual(self.writer.written, [])

    def test_queue_full_returns_busy_before_write(self) -> None:
        service = OutputService(self.writer, is_queue_full=lambda: True)
        result = service.copy_image_to_clipboard(self.snapshot)
        self.assertEqual(result.state, TaskState.BUSY)
        self.assertEqual(result.error_code, "queue_full")
        self.assertEqual(self.writer.written, [])

    def test_snapshot_is_immutable(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            self.snapshot.width_px = 4

    def test_invalid_snapshot_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            OutputSnapshot(
                operation_id="op-002",
                session_id="s-001",
                revision=1,
                width_px=0,
                height_px=2,
                pixels=b"\x01",
            )
        with self.assertRaises(ValueError):
            OutputSnapshot(
                operation_id="op-003",
                session_id="s-001",
                revision=1,
                width_px=2,
                height_px=2,
                pixels=b"",
            )

    def test_task_states_match_frontend_contract(self) -> None:
        expected = {"pending", "succeeded", "failed", "cancelled", "busy"}
        self.assertEqual({state.value for state in TaskState}, expected)


if __name__ == "__main__":
    unittest.main()
