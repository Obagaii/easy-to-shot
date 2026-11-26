from math import dist
from statistics import median

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QImage, QPainter, QPolygonF, QTransform

from e2s.annotation.elements import ImagePatch
from e2s.annotation.renderer import annotation_font
from e2s.capture.ocr import OcrLine
from e2s.capture.service import CaptureError
from e2s.capture.session import OutputSnapshot


def render_text_cover(
    snapshot: OutputSnapshot, lines: tuple[OcrLine, ...], replacements: tuple[str, ...]
) -> ImagePatch:
    """Render a crop-relative OCR replacement as a frame-relative image patch."""
    image = snapshot.to_image()
    if image.isNull():
        raise MemoryError("Unable to allocate the source image")
    crop = QRectF(image.rect())
    regions = []
    bounds = QRectF()
    for line, text in zip(lines, replacements, strict=True):
        quad = QPolygonF([QPointF(x, y) for x, y in line.corners])
        visible = quad.boundingRect().intersected(crop)
        if not visible.isEmpty():
            regions.append((quad, text))
            bounds = bounds.united(visible)
    extent = bounds.toAlignedRect()
    if extent.isEmpty():
        raise CaptureError("找不到可覆盖的文字位置。")

    layer = QImage(extent.size(), QImage.Format.Format_ARGB32_Premultiplied)
    if layer.isNull():
        raise MemoryError("Unable to allocate the text overlay")
    layer.fill(Qt.GlobalColor.transparent)
    with QPainter(layer) as painter:
        if not painter.isActive():
            raise MemoryError("Unable to paint the text overlay")
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.translate(-extent.left(), -extent.top())
        placed = False
        for quad, text in regions:
            placed = _paint_line(painter, image, quad, text) or placed

    if not placed:
        raise CaptureError("找不到可覆盖的文字位置。")
    return ImagePatch(
        (snapshot.selection.left + extent.left(), snapshot.selection.top + extent.top()),
        layer,
    )


def _paint_line(painter: QPainter, image: QImage, quad: QPolygonF, text: str) -> bool:
    top_left, top_right, bottom_right, bottom_left = [point.toTuple() for point in quad]
    width = (dist(top_left, top_right) + dist(bottom_left, bottom_right)) / 2
    height = (dist(top_left, bottom_left) + dist(top_right, bottom_right)) / 2
    if min(width, height) < 2:
        return False
    if height / width >= 1.5:
        # RapidOCR rotates tall crops before recognizing the text.
        quad = QPolygonF([quad[1], quad[2], quad[3], quad[0]])
        width, height = height, width
    box = QRectF(0, 0, width, height)
    transform = QTransform()
    corners = QPolygonF([box.topLeft(), box.topRight(), box.bottomRight(), box.bottomLeft()])
    if not QTransform.quadToQuad(corners, quad, transform):
        return False
    background = _sample_background(image, box, transform)
    brightness = (299 * background.red() + 587 * background.green() + 114 * background.blue())
    padding = min(2.0, width * 0.07, height * 0.07)
    available = box.adjusted(padding, padding, -padding, -padding)
    font = annotation_font(max(1, round(available.height())))
    word_bounds = QFontMetricsF(font).tightBoundingRect(text)
    if word_bounds.isEmpty():
        return False
    scale = min(1.0, available.width() / word_bounds.width(),
                available.height() / word_bounds.height())

    painter.save()
    painter.setWorldTransform(transform, True)
    painter.setClipRect(box)
    painter.fillRect(box, background)
    painter.setFont(font)
    painter.setPen(Qt.GlobalColor.black if brightness >= 145_000 else Qt.GlobalColor.white)
    painter.translate(available.left(), available.center().y())
    painter.scale(scale, scale)
    painter.drawText(QPointF(-word_bounds.left(), -word_bounds.center().y()), text)
    painter.restore()
    return True


def _sample_background(image: QImage, box: QRectF, transform: QTransform) -> QColor:
    """Estimate text background from pixels just outside the OCR quadrilateral."""
    offset = min(3.0, max(1.0, box.height() * 0.12))
    samples = []
    for index in range(1, 12):
        x = box.width() * index / 12
        y = box.height() * index / 12
        for point in (
            QPointF(x, -offset), QPointF(x, box.height() + offset),
            QPointF(-offset, y), QPointF(box.width() + offset, y),
        ):
            mapped = transform.map(point).toPoint()
            if image.rect().contains(mapped):
                samples.append(image.pixelColor(mapped))
    if not samples:
        visible = transform.mapRect(box).intersected(QRectF(image.rect()))
        center = visible.center().toPoint()
        return image.pixelColor(center) if image.rect().contains(center) else QColor("white")
    return QColor(
        round(median(color.red() for color in samples)),
        round(median(color.green() for color in samples)),
        round(median(color.blue() for color in samples)),
    )
