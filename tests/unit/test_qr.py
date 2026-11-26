from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image

from e2s.capture.geometry import SelectionRect
from e2s.capture.qr import scan_codes
from e2s.capture.session import CaptureSource, OutputSnapshot


PRIVATE_QR_IMAGE = (
    Path(__file__).resolve().parents[2]
    / "docs/private/647db43d-cb77-4f7c-876f-72b4e0d747d7.png"
)
EXPECTED_URL = "https://pan.baidu.com/s/16TvFrrVaAWUKifAKz2KEjA?pwd=MIKU"


def make_snapshot(image: Image.Image) -> OutputSnapshot:
    rgba = image.convert("RGBA")
    return OutputSnapshot(
        uuid4(), uuid4(), 1, CaptureSource.TRAY, "test",
        SelectionRect(0, 0, rgba.width, rgba.height), rgba.tobytes(),
    )


def test_scan_blank_selection_returns_no_detections() -> None:
    snapshot = make_snapshot(Image.new("RGBA", (64, 64), "white"))
    assert scan_codes(snapshot) == ()


def test_scan_provided_qr_image_decodes_url_and_location() -> None:
    if not PRIVATE_QR_IMAGE.is_file():
        pytest.skip("Optional private QR sample is not available")
    with Image.open(PRIVATE_QR_IMAGE) as image:
        snapshot = make_snapshot(image)
    (detection,) = scan_codes(snapshot)
    assert detection.text == EXPECTED_URL
    assert detection.center[0] == pytest.approx(0.5, abs=0.03)
    assert detection.center[1] == pytest.approx(0.5, abs=0.03)
