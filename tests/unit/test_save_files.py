import io
from datetime import datetime

from PIL import Image

from e2s.output.files import build_filename, encode_png
from samples import build_snapshot


def test_suggested_filename_contains_timestamp() -> None:
    assert build_filename(datetime(2026, 11, 23, 13, 28)) == "E2S_20261123_132800.png"


def test_encode_png_preserves_snapshot_pixels() -> None:
    snapshot = build_snapshot("op-save", width_px=9, height_px=5)
    with Image.open(io.BytesIO(encode_png(snapshot))) as image:
        assert image.size == (9, 5)
        assert image.mode == "RGBA"
        assert image.tobytes() == snapshot.pixels
