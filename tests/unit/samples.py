"""B1 的可复现合成样本：色块、边缘像素与混合 DPI 尺寸。

不含真实截图数据；样本按尺寸命名，便于定位边界场景。
"""

import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from e2s.output.service import OutputSnapshot  # noqa: E402

CHANNELS = 4  # RGBA：源图像素每像素 4 字节


def make_pixels(width_px: int, height_px: int, seed: int = 0) -> bytes:
    """生成确定性的 RGBA 合成色块，并在首尾像素留下可校验特征。"""

    base = bytes((channel + seed) % 256 for channel in range(CHANNELS))
    data = bytearray(base * (width_px * height_px))
    if data:
        data[0] = (data[0] + 17) % 256
        data[-1] = (data[-1] + 31) % 256
    return bytes(data)


def build_snapshot(
    operation_id: str,
    *,
    width_px: int = 2,
    height_px: int = 2,
    seed: int = 0,
    session_id: str = "s-001",
    revision: int = 1,
) -> OutputSnapshot:
    """构造指定尺寸的合成快照，供粘贴尺寸与像素一致性测试使用。"""

    return OutputSnapshot(
        operation_id=operation_id,
        session_id=session_id,
        revision=revision,
        width_px=width_px,
        height_px=height_px,
        pixels=make_pixels(width_px, height_px, seed),
        parameters={"format": "png", "channels": CHANNELS},
    )
