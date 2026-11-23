"""B2 ①：PNG 编码与无覆盖快速保存的单元测试。"""

import io
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from PIL import Image  # noqa: E402

from e2s.output.files import OutputFileService, build_filename, encode_png  # noqa: E402
from e2s.output.ports import TaskState  # noqa: E402
from samples import build_snapshot  # noqa: E402

FIXED_TIME = datetime(2026, 11, 23, 13, 28, 0)


class SaveFilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.directory = Path(self._temp_dir.name)
        self.snapshot = build_snapshot("op-save", width_px=9, height_px=5)
        self.service = OutputFileService(self.directory, clock=lambda: FIXED_TIME)

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def test_build_filename_format(self) -> None:
        self.assertEqual(build_filename(FIXED_TIME), "E2S_20261123_132800.png")
        self.assertEqual(build_filename(FIXED_TIME, 1), "E2S_20261123_132800_01.png")
        self.assertEqual(build_filename(FIXED_TIME, 12), "E2S_20261123_132800_12.png")

    def test_encode_png_can_be_read_back(self) -> None:
        payload = encode_png(self.snapshot)
        self.assertTrue(payload.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(io.BytesIO(payload)) as image:
            self.assertEqual(image.size, (9, 5))
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.tobytes(), self.snapshot.pixels)

    def test_quick_save_creates_png(self) -> None:
        result = self.service.quick_save(self.snapshot)
        self.assertEqual(result.state, TaskState.SUCCEEDED)
        self.assertIsNone(result.error_code)
        self.assertEqual(result.path.name, "E2S_20261123_132800.png")
        with Image.open(result.path) as image:
            self.assertEqual(image.size, (9, 5))

    def test_two_saves_in_same_second_get_distinct_files(self) -> None:
        first = self.service.quick_save(self.snapshot)
        second = self.service.quick_save(self.snapshot)
        self.assertEqual(first.state, TaskState.SUCCEEDED)
        self.assertEqual(second.state, TaskState.SUCCEEDED)
        self.assertNotEqual(first.path, second.path)
        self.assertEqual(second.path.name, "E2S_20261123_132800_01.png")
        self.assertTrue(first.path.exists())
        self.assertTrue(second.path.exists())

    def test_existing_file_is_not_overwritten(self) -> None:
        existing = self.directory / "E2S_20261123_132800.png"
        existing.write_bytes(b"original")
        result = self.service.quick_save(self.snapshot)
        self.assertEqual(result.state, TaskState.SUCCEEDED)
        self.assertEqual(existing.read_bytes(), b"original")
        self.assertEqual(result.path.name, "E2S_20261123_132800_01.png")

    def test_missing_directory_returns_failed(self) -> None:
        service = OutputFileService(
            self.directory / "missing", clock=lambda: FIXED_TIME
        )
        result = service.quick_save(self.snapshot)
        self.assertEqual(result.state, TaskState.FAILED)
        self.assertEqual(result.error_code, "directory_not_writable")
        self.assertIsNone(result.path)

    def test_no_temp_files_remain(self) -> None:
        self.service.quick_save(self.snapshot)
        self.assertEqual(list(self.directory.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
