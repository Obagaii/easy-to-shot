"""B1 失败恢复与状态边界验证。"""

import sys
import unittest
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from e2s.output.mock import MockClipboardWriter  # noqa: E402
from e2s.output.ports import TaskState  # noqa: E402
from e2s.output.service import OutputService  # noqa: E402
from samples import build_snapshot  # noqa: E402


class FailureRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.writer = MockClipboardWriter()
        self.service = OutputService(self.writer)
        self.snapshot = build_snapshot("op-recovery", width_px=9, height_px=5)

    def test_consecutive_failures_then_retry_with_same_operation_id(self) -> None:
        results = []
        for _ in range(2):
            self.writer.fail_next_write = True
            results.append(self.service.copy_image_to_clipboard(self.snapshot))

        self.assertEqual([r.state for r in results], [TaskState.FAILED] * 2)
        self.assertEqual([r.error_code for r in results], ["clipboard_write_failed"] * 2)
        self.assertEqual(len({r.operation_id for r in results}), 1)
        self.assertEqual(self.writer.written, [])

        recovered = self.service.copy_image_to_clipboard(self.snapshot)
        self.assertEqual(recovered.state, TaskState.SUCCEEDED)
        self.assertIsNone(recovered.error_code)
        self.assertEqual(recovered.operation_id, results[0].operation_id)
        self.assertEqual(self.writer.written, [self.snapshot])

    def test_failed_copy_does_not_mutate_snapshot(self) -> None:
        before = (
            self.snapshot.pixels,
            self.snapshot.width_px,
            self.snapshot.height_px,
            self.snapshot.operation_id,
            self.snapshot.session_id,
            self.snapshot.revision,
        )
        self.writer.fail_next_write = True
        self.service.copy_image_to_clipboard(self.snapshot)
        after = (
            self.snapshot.pixels,
            self.snapshot.width_px,
            self.snapshot.height_px,
            self.snapshot.operation_id,
            self.snapshot.session_id,
            self.snapshot.revision,
        )
        self.assertEqual(after, before)

    def test_cancel_takes_precedence_over_queue_full(self) -> None:
        service = OutputService(self.writer, is_queue_full=lambda: True)
        result = service.copy_image_to_clipboard(self.snapshot, is_cancelled=True)
        self.assertEqual(result.state, TaskState.CANCELLED)
        self.assertIsNone(result.error_code)
        self.assertEqual(self.writer.written, [])

    def test_busy_result_does_not_carry_failure_code(self) -> None:
        service = OutputService(self.writer, is_queue_full=lambda: True)
        result = service.copy_image_to_clipboard(self.snapshot)
        self.assertEqual(result.state, TaskState.BUSY)
        self.assertEqual(result.error_code, "queue_full")
        self.assertEqual(self.writer.written, [])

    def test_retry_after_cancel_is_allowed(self) -> None:
        cancelled = self.service.copy_image_to_clipboard(self.snapshot, is_cancelled=True)
        self.assertEqual(cancelled.state, TaskState.CANCELLED)
        retried = self.service.copy_image_to_clipboard(self.snapshot)
        self.assertEqual(retried.state, TaskState.SUCCEEDED)
        self.assertEqual(self.writer.written, [self.snapshot])


if __name__ == "__main__":
    unittest.main()
