from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter

from e2s.capture.geometry import SelectionRect
from e2s.capture.ocr import OcrLine
from e2s.capture.ocr_overlay import render_text_cover
from e2s.capture.service import CaptureFrame
from e2s.capture.session import CaptureSession, CaptureSource


def test_text_cover_follows_the_ocr_quad_in_an_offset_crop(app) -> None:
    origin_x, origin_y = 25, 20
    frame = QImage(160, 110, QImage.Format.Format_RGBA8888)
    frame.fill(QColor("white"))
    with QPainter(frame) as painter:
        painter.fillRect(QRect(origin_x + 40, origin_y + 43, 9, 5), QColor("magenta"))
    frame.setPixelColor(origin_x + 15, origin_y + 23, QColor("green"))

    session = CaptureSession(CaptureFrame("test", frame.rect(), frame), CaptureSource.HOTKEY)
    session.set_selection(SelectionRect(origin_x, origin_y, 150, 105))
    snapshot = session.create_snapshot()
    line = OcrLine("原文", ((15, 33), (100, 18), (105, 48), (20, 63)))
    cover = render_text_cover(snapshot, (line,), ("New text",))
    assert cover.origin == (origin_x + 15, origin_y + 18)
    assert cover.image.pixelColor(0, 0).alpha() == 0

    document = session.begin_annotation()
    document.add(cover)
    result = session.create_snapshot().to_image()
    assert result.pixelColor(15, 23) == QColor("green")
    assert result.pixelColor(44, 45) != QColor("magenta")
    assert any(
        result.pixelColor(x, y).value() < 80 for x in range(45, 95) for y in range(25, 52)
    )
