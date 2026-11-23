"""B2 ②：另存、覆盖确认与错误恢复的单元测试。"""

import io
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from PIL import Image  # noqa: E402

from e2s.output.files import OutputFileService  # noqa: E402
from e2s.output.ports import TaskState  # noqa: E402
from samples import build_snapshot  # noqa: E402

FIXED_TIME = datetime(2026, 11, 23, 13, 28, 0)


class SaveRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.directory = Path(self._temp_dir.name)
        self.snapshot = build_snapshot("op-save-as", width_px=9, height_px=5)
        self.service = OutputFileService(self.directory, clock=lambda: FIXED_TIME)

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def test_save_as_to_new_path_succeeds(self) -> None:
        target = self.directory / "custom.png"
        result = self.service.save_as(self.snapshot, target)
        self.assertEqual(result.state, TaskState.SUCCEEDED)
        self.assertEqual(result.path, target)
        with Image.open(target) as image:
            self.assertEqual(image.size, (9, 5))

    def test_save_as_existing_without_confirm_is_cancelled(self) -> None:
        target = self.directory / "custom.png"
        target.write_bytes(b"original")
        result = self.service.save_as(self.snapshot, target)
        self.assertEqual(result.state, TaskState.CANCELLED)
        self.assertEqual(result.error_code, "overwrite_not_confirmed")
        self.assertIsNone(result.path)
        self.assertEqual(target.read_bytes(), b"original")
        self.assertEqual(list(self.directory.glob("*.tmp")), [])

    def test_save_as_existing_with_confirm_replaces(self) -> None:
        target = self.directory / "custom.png"
        target.write_bytes(b"original")
        result = self.service.save_as(
            self.snapshot, target, is_overwrite_confirmed=True
        )
        self.assertEqual(result.state, TaskState.SUCCEEDED)
        with Image.open(io.BytesIO(target.read_bytes())) as image:
            self.assertEqual(image.size, (9, 5))
            self.assertEqual(image.tobytes(), self.snapshot.pixels)
        self.assertEqual(list(self.directory.glob("*.tmp")), [])

    def test_save_as_cancelled_does_not_write(self) -> None:
        target = self.directory / "custom.png"
        result = self.service.save_as(self.snapshot, target, is_cancelled=True)
        self.assertEqual(result.state, TaskState.CANCELLED)
        self.assertIsNone(result.error_code)
        self.assertFalse(target.exists())
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_save_as_missing_parent_returns_failed(self) -> None:
        target = self.directory / "missing" / "custom.png"
        result = self.service.save_as(self.snapshot, target)
        self.assertEqual(result.state, TaskState.FAILED)
        self.assertEqual(result.error_code, "directory_not_writable")
        self.assertIsNone(result.path)

    def test_write_failure_keeps_existing_file(self) -> None:
        target = self.directory / "custom.png"
        target.write_bytes(b"original")
        with patch.object(
            OutputFileService, "_write_temp", side_effect=OSError("disk full")
        ):
            result = self.service.save_as(
                self.snapshot, target, is_overwrite_confirmed=True
            )
        self.assertEqual(result.state, TaskState.FAILED)
        self.assertEqual(result.error_code, "write_failed")
        self.assertEqual(target.read_bytes(), b"original")
        self.assertEqual(list(self.directory.glob("*.tmp")), [])

    def test_write_failure_on_new_target_leaves_no_file(self) -> None:
        target = self.directory / "custom.png"
        with patch.object(
            OutputFileService, "_write_temp", side_effect=OSError("disk full")
        ):
            result = self.service.quick_save(self.snapshot)
        self.assertEqual(result.state, TaskState.FAILED)
        self.assertEqual(result.error_code, "write_failed")
        self.assertFalse(target.exists())
        self.assertEqual([p for p in self.directory.iterdir() if p.suffix == ".png"], [])

    def test_quick_save_cancelled_does_not_write(self) -> None:
        result = self.service.quick_save(self.snapshot, is_cancelled=True)
        self.assertEqual(result.state, TaskState.CANCELLED)
        self.assertIsNone(result.path)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_retry_after_failure_succeeds_with_same_operation_id(self) -> None:
        with patch.object(
            OutputFileService, "_write_temp", side_effect=OSError("disk full")
        ):
            failed = self.service.quick_save(self.snapshot)
        recovered = self.service.quick_save(self.snapshot)
        self.assertEqual(failed.state, TaskState.FAILED)
        self.assertEqual(recovered.state, TaskState.SUCCEEDED)
        self.assertEqual(recovered.operation_id, failed.operation_id)
        self.assertEqual(recovered.path.name, "E2S_20261123_132800.png")

    def test_cancel_takes_precedence_over_overwrite_confirmation(self) -> None:
        target = self.directory / "custom.png"
        target.write_bytes(b"original")
        result = self.service.save_as(
            self.snapshot,
            target,
            is_cancelled=True,
            is_overwrite_confirmed=True,
        )
        self.assertEqual(result.state, TaskState.CANCELLED)
        self.assertIsNone(result.error_code)
        self.assertEqual(target.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
