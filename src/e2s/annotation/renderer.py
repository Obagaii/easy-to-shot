from collections.abc import Iterable
from math import hypot
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
)

from e2s.annotation.elements import Element, Point, Stroke, Text, Tool


def render_annotations(
    source: QImage, elements: Iterable[Element], origin_px: tuple[int, int] = (0, 0)
) -> QImage:
    """Composite elements in frame coordinates onto a crop at its original pixel density."""
    left_px, top_px = origin_px
    image = source.convertToFormat(QImage.Format.Format_RGBA8888)
    painter = QPainter()
    try:
        for element in elements:
            if image.isNull():
                break
            if not painter.isActive():
                if not painter.begin(image):
                    raise MemoryError("Unable to allocate the annotation image")
                painter.translate(-left_px, -top_px)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            if isinstance(element, Text):
                _draw_text(painter, element)
            else:
                path, is_filled = _stroke_path(element)
                color = QColor(element.color)
                if is_filled:
                    painter.fillPath(path, color)
                else:
                    painter.strokePath(path, _pen(color, element.width_px))
    finally:
        if painter.isActive():
            painter.end()
    return image


def hit_test(elements: tuple[Element, ...], point: Point, tolerance_px: float) -> int | None:
    position = QPointF(*point)
    for index in range(len(elements) - 1, -1, -1):
        element = elements[index]
        if isinstance(element, Stroke):
            path, is_filled = _stroke_path(element)
            if is_filled and path.contains(position):
                return index
            width = 0 if is_filled else element.width_px
            if _stroked(path, width + 2 * tolerance_px).contains(position):
                return index
        else:
            bounds = element_bounds(element)
            if bounds.adjusted(-tolerance_px, -tolerance_px, tolerance_px, tolerance_px).contains(
                position
            ):
                return index
    return None


def element_bounds(element: Element) -> QRectF:
    if isinstance(element, Text):
        return _text_bounds(element)
    path, is_filled = _stroke_path(element)
    return path.boundingRect() if is_filled else _stroked(path, element.width_px).boundingRect()


def annotation_font(font_size_px: int) -> QFont:
    font = QFont()
    font.setPixelSize(font_size_px)
    return font


def _text_bounds(element: Text) -> QRectF:
    metrics = QFontMetricsF(annotation_font(element.font_size_px))
    x, y = element.origin
    lines = element.value.split("\n")
    bounds = QRectF(x, y, 0, metrics.height() + (len(lines) - 1) * metrics.lineSpacing())
    for index, line in enumerate(lines):
        baseline = y + metrics.ascent() + index * metrics.lineSpacing()
        layout = QRectF(x, y, metrics.horizontalAdvance(line), bounds.height())
        bounds = bounds.united(layout)
        bounds = bounds.united(metrics.boundingRect(line).translated(x, baseline))
    return bounds


def _draw_text(painter: QPainter, element: Text) -> None:
    font = annotation_font(element.font_size_px)
    painter.setFont(font)
    painter.setPen(QColor(element.color))
    metrics = QFontMetricsF(font)
    x, y = element.origin
    for index, line in enumerate(element.value.split("\n")):
        painter.drawText(QPointF(x, y + metrics.ascent() + index * metrics.lineSpacing()), line)


def _pen(color: QColor, width_px: int) -> QPen:
    pen = QPen(color)
    pen.setWidthF(width_px)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _stroked(path: QPainterPath, width_px: float) -> QPainterPath:
    stroker = QPainterPathStroker()
    stroker.setWidth(max(width_px, 0.01))
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return stroker.createStroke(path)


def _stroke_path(stroke: Stroke) -> tuple[QPainterPath, bool]:
    start = QPointF(*stroke.points[0])
    end = QPointF(*stroke.points[-1])
    path = QPainterPath()
    if stroke.tool in (Tool.RECTANGLE, Tool.ELLIPSE):
        rect = QRectF(start, end).normalized()
        if stroke.tool is Tool.RECTANGLE:
            path.addRect(rect)
        else:
            path.addEllipse(rect)
        return path, stroke.is_filled
    if stroke.tool is Tool.PEN:
        if len(stroke.points) == 1:
            radius = stroke.width_px / 2
            path.addEllipse(start, radius, radius)
            return path, True
        path.moveTo(start)
        for point in stroke.points[1:]:
            path.lineTo(QPointF(*point))
        return path, False
    path.moveTo(start)
    path.lineTo(end)
    if stroke.tool is Tool.ARROW:
        delta = end - start
        length_px = hypot(delta.x(), delta.y())
        if length_px:
            direction = delta / length_px
            head_length_px = min(length_px * 0.45, max(8, stroke.width_px * 3))
            wing = QPointF(-direction.y(), direction.x()) * (head_length_px * 0.5)
            base = end - direction * head_length_px
            path.moveTo(base + wing)
            path.lineTo(end)
            path.lineTo(base - wing)
    return path, False
