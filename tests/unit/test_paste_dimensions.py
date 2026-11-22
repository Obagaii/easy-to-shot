"""B1 粘贴尺寸与像素一致性验证。

真实两个外部桌面程序的粘贴验收依赖 A4，留待 PR-03 的第 ③ 次联调提交；
本文件用模拟剪贴板验证写入像素与合成快照、保存基准三者一致。
"""

import sys
import unittest
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from e2s.output.mock import MockClipboardWriter  # noqa: E402
from e2s.output.ports import TaskState  # noqa: E402
from e2s.output.service import OutputService  # noqa: E402
from samples import CHANNELS, build_snapshot, make_pixels  # noqa: E402

DIMENSION_CASES = [
    ("edge-1x1", 1, 1),
    ("small-2x2", 2, 2),
    ("odd-17x9", 17, 9),
    ("full-hd-1920x1080", 1920, 1080),
    ("mixed-dpi-2560x1440", 2560, 1440),
]


class PasteDimensionsTest(unittest.TestCase):
    def test_written_pixels_match_snapshot_for_each_dimension(self) -> None:
        for name, width, height in DIMENSION_CASES:
            with self.subTest(case=name):
                writer = MockClipboardWriter()
                service = OutputService(writer)
                snapshot = build_snapshot(
                    f"op-{name}", width_px=width, height_px=height
                )
                result = service.copy_image_to_clipboard(snapshot)

                self.assertEqual(result.state, TaskState.SUCCEEDED)
                self.assertIsNone(result.error_code)
                self.assertEqual(len(writer.written), 1)
                written = writer.written[0]
                self.assertEqual((written.width_px, written.height_px), (width, height))
                self.assertEqual(len(written.pixels), width * height * CHANNELS)
                self.assertEqual(written.pixels, make_pixels(width, height))
                self.assertEqual(written.pixels, snapshot.pixels)

    def test_written_pixels_match_save_baseline(self) -> None:
        """复制与保存共用同一份合成像素；以快照字节作为保存基准。"""

        writer = MockClipboardWriter()
        service = OutputService(writer)
        snapshot = build_snapshot("op-baseline", width_px=17, height_px=9, seed=7)
        save_baseline = snapshot.pixels

        result = service.copy_image_to_clipboard(snapshot)

        self.assertEqual(result.state, TaskState.SUCCEEDED)
        self.assertEqual(writer.written[0].pixels, save_baseline)
        self.assertEqual(len(save_baseline), 17 * 9 * CHANNELS)
        self.assertNotEqual(save_baseline[0], save_baseline[1])

    def test_seed_changes_pixels_but_not_dimensions(self) -> None:
        first = build_snapshot("op-seed-a", width_px=9, height_px=5, seed=1)
        second = build_snapshot("op-seed-b", width_px=9, height_px=5, seed=2)
        self.assertNotEqual(first.pixels, second.pixels)
        self.assertEqual(len(first.pixels), len(second.pixels))
        self.assertEqual(
            (first.width_px, first.height_px),
            (second.width_px, second.height_px),
        )


if __name__ == "__main__":
    unittest.main()
