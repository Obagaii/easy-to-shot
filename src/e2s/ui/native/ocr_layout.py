from collections import Counter
from dataclasses import dataclass
from statistics import median

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPolygonF, QTransform

from e2s.capture.ocr import OcrLine
from e2s.capture.ocr_overlay import _sample_background


@dataclass(frozen=True, slots=True)
class TextRow:
    line: OcrLine
    text: str
    bounds: QRectF
    foreground: QColor
    background: QColor
    font_px: int
    vertical: bool


def _text_color(image: QImage, bounds: QRectF, background: QColor) -> QColor:
    rect = bounds.toAlignedRect().intersected(image.rect())
    colors: Counter[tuple[int, int, int]] = Counter()
    step = max(1, min(rect.width(), rect.height()) // 24)
    for y in range(rect.top(), rect.bottom() + 1, step):
        for x in range(rect.left(), rect.right() + 1, step):
            color = image.pixelColor(x, y)
            distance = sum((a - b) ** 2 for a, b in zip(
                (color.red(), color.green(), color.blue()),
                (background.red(), background.green(), background.blue()), strict=True,
            ))
            if distance >= 45 ** 2:
                colors[(color.red() // 24, color.green() // 24, color.blue() // 24)] += 1
    if colors:
        color, _ = colors.most_common(1)[0]
        return QColor(*(min(255, channel * 24 + 12) for channel in color))
    return QColor('#111111' if background.lightness() > 128 else '#ffffff')


def prepare_text_rows(image: QImage, lines: tuple[OcrLine, ...],
                      scale_x: float, scale_y: float) -> list[TextRow]:
    entries = []
    for line in lines:
        quad = QPolygonF([QPointF(x, y) for x, y in line.corners])
        bounds = quad.boundingRect().intersected(QRectF(image.rect()))
        if bounds.width() < 1 or bounds.height() < 1:
            continue
        transform = QTransform()
        box = QRectF(0, 0, bounds.width(), bounds.height())
        target = QPolygonF([bounds.topLeft(), bounds.topRight(),
                            bounds.bottomRight(), bounds.bottomLeft()])
        source = QPolygonF([box.topLeft(), box.topRight(), box.bottomRight(), box.bottomLeft()])
        QTransform.quadToQuad(source, target, transform)
        background = _sample_background(image, box, transform)
        entries.append((line, bounds, background, _text_color(image, bounds, background)))
    heights = [min(entry[1].height() * scale_y, entry[1].width() * scale_x)
               if entry[1].height() > entry[1].width() * 1.5 else entry[1].height() * scale_y
               for entry in entries]
    typical = median(heights) if heights else 0
    rows = []
    for line, bounds, background, foreground in entries:
        width, height = bounds.width() * scale_x, bounds.height() * scale_y
        vertical = height > width * 1.5
        thickness = width if vertical else height
        if len(heights) >= 3 and thickness > typical * 2.5:
            thickness = typical * 2
        font_px = max(1, round(thickness * 0.85))
        font = QFont('Microsoft YaHei UI')
        font.setPixelSize(font_px)
        advance = QFontMetricsF(font).horizontalAdvance(line.text)
        if not vertical and advance > width and advance > 0:
            font_px = max(1, round(font_px * width / advance))
        rows.append(TextRow(line, line.text, QRectF(bounds.x() * scale_x, bounds.y() * scale_y,
                                            width, bounds.height() * scale_y),
                            foreground, background, font_px, vertical))
    return rows
