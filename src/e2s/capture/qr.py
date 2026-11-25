from dataclasses import dataclass

from PIL import Image
from zxingcpp import read_barcodes

from e2s.capture.session import OutputSnapshot


@dataclass(frozen=True, slots=True)
class CodeDetection:
    text: str
    center: tuple[float, float]


def scan_codes(snapshot: OutputSnapshot) -> tuple[CodeDetection, ...]:
    """Decode each barcode and return its center in normalized crop coordinates."""
    image = Image.frombytes(
        "RGBA", (snapshot.width_px, snapshot.height_px), snapshot.rgba_pixels
    ).convert("RGB")
    result = []
    for code in read_barcodes(image):
        corners = (code.position.top_left, code.position.top_right,
                   code.position.bottom_right, code.position.bottom_left)
        x = sum(corner.x for corner in corners) / (4 * image.width)
        y = sum(corner.y for corner in corners) / (4 * image.height)
        if code.text:
            result.append(CodeDetection(code.text, (x, y)))
    return tuple(result)
