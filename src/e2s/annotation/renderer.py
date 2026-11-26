from collections.abc import Iterable
from itertools import pairwise
from math import ceil, floor, hypot, sin

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
    QPolygonF,
    QTransform,
)

from e2s.annotation.elements import (
    MASK_TOOLS,
    Annotation,
    Element,
    ImagePatch,
    Point,
    Stroke,
    Text,
    TextStyle,
    Tool,
)

_LINE_STYLES = {"solid": Qt.PenStyle.SolidLine, "dash": Qt.PenStyle.DashLine,
                "dot": Qt.PenStyle.DotLine}


def render_annotations(
    source: QImage, elements: Iterable[Annotation], origin_px: tuple[int, int] = (0, 0)
) -> QImage:
    """Paint frame-relative annotations on a crop at its original pixel density."""
    image = source.convertToFormat(QImage.Format.Format_RGBA8888)
    if image.isNull():
        return image
    bounds = QRectF(*origin_px, image.width(), image.height())
    watermark = None
    with QPainter(image) as painter:
        if not painter.isActive():
            raise MemoryError("Unable to allocate the annotation image")
        painter.translate(-bounds.x(), -bounds.y())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        for element in elements:
            if isinstance(element, Stroke) and element.tool in MASK_TOOLS:
                painter.save()
                painter.setClipPath(stroke_area(element))
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                painter.drawImage(bounds.topLeft(), source)
                painter.restore()
            elif isinstance(element, ImagePatch):
                painter.drawImage(QPointF(*element.origin), element.image)
            elif element.tool is Tool.WATERMARK:
                watermark = element
            elif element.opacity:
                _draw_element(painter, element, bounds)
        if watermark is not None:
            _draw_watermark(painter, watermark, bounds)
    return image


def _draw_element(painter: QPainter, element: Element, crop: QRectF) -> None:
    draw = _draw_stroke if isinstance(element, Stroke) else _draw_text
    if element.opacity == 100:
        draw(painter, element)
        return

    # Composite the finished element as one layer so its fill and outline share the same opacity.
    padding = 4 + (element.style.outline_width if isinstance(element, Text) else 0)
    extent = element_bounds(element).adjusted(-padding, -padding, padding, padding)
    area = extent.intersected(crop).toAlignedRect()
    if area.isEmpty():
        return
    layer = QImage(area.size(), QImage.Format.Format_ARGB32_Premultiplied)
    if layer.isNull():
        raise MemoryError("Unable to allocate the annotation layer")
    layer.fill(Qt.GlobalColor.transparent)
    with QPainter(layer) as layer_painter:
        layer_painter.translate(-area.x(), -area.y())
        layer_painter.setRenderHints(painter.renderHints())
        draw(layer_painter, element)
    painter.save()
    painter.setOpacity(element.opacity / 100)
    painter.drawImage(area.topLeft(), layer)
    painter.restore()


def hit_test(elements: tuple[Annotation, ...], point: Point, tolerance_px: float) -> int | None:
    position = QPointF(*point)
    for index in range(len(elements) - 1, -1, -1):
        element = elements[index]
        if isinstance(element, Stroke):
            is_mask = element.tool in MASK_TOOLS
            if stroke_area(element, 0 if is_mask else tolerance_px).contains(position):
                return None if is_mask else index
        elif isinstance(element, Text) and element.tool is Tool.TEXT:
            bounds = element_bounds(element)
            if bounds.adjusted(-tolerance_px, -tolerance_px, tolerance_px, tolerance_px).contains(
                position
            ):
                return index
    return None


def intersecting_elements(elements: tuple[Annotation, ...], area: QPainterPath) -> set[int]:
    """Find editable elements intersecting a selection or an element eraser."""
    found = set()
    for index, element in enumerate(elements):
        if isinstance(element, Stroke):
            if element.tool not in MASK_TOOLS and area.intersects(stroke_area(element)):
                found.add(index)
        elif (
            isinstance(element, Text) and element.tool is Tool.TEXT
            and area.intersects(element_bounds(element))
        ):
            found.add(index)
    return found


def element_bounds(element: Element) -> QRectF:
    if isinstance(element, Stroke):
        return stroke_area(element).boundingRect()
    return _text_geometry(element)[1]


def annotation_font(font_size_px: int, style: TextStyle | None = None) -> QFont:
    style = style or TextStyle()
    font = QFont(style.family) if style.family else QFont()
    font.setPixelSize(font_size_px)
    font.setBold(style.bold)
    font.setItalic(style.italic)
    font.setUnderline(style.underline)
    font.setStrikeOut(style.strikethrough)
    return font


def _text_geometry(element: Text) -> tuple[QPainterPath, QRectF, QFontMetricsF]:
    font = annotation_font(element.font_size_px, element.style)
    metrics = QFontMetricsF(font)
    lines = element.value.split("\n")
    widths = [metrics.horizontalAdvance(line) for line in lines]
    width = max(widths)
    x, y = element.origin
    path = QPainterPath()
    for index, (line, line_width) in enumerate(zip(lines, widths)):
        offset = {"left": 0, "center": (width - line_width) / 2, "right": width - line_width}
        baseline = y + metrics.ascent() + index * metrics.lineSpacing()
        left = x + offset[element.style.alignment]
        path.addText(QPointF(left, baseline), font, line)
        thickness = max(1, metrics.lineWidth())
        if element.style.underline:
            path.addRect(left, baseline + metrics.underlinePos(), line_width, thickness)
        if element.style.strikethrough:
            path.addRect(left, baseline - metrics.strikeOutPos(), line_width, thickness)
    height = metrics.height() + (len(lines) - 1) * metrics.lineSpacing()
    bounds = QRectF(x, y, width, height).united(path.boundingRect())
    if element.style.background:
        bounds.adjust(-4, -2, 4, 2)
    return path, bounds, metrics


def _draw_text(painter: QPainter, element: Text) -> None:
    path, bounds, _ = _text_geometry(element)
    style = element.style
    if style.background:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(style.background))
        painter.drawRoundedRect(bounds, style.corner_radius_px, style.corner_radius_px)
    if style.outline and style.outline_width:
        painter.strokePath(path, _pen(QColor(style.outline), style.outline_width))
    painter.fillPath(path, QColor(element.color))


def _draw_watermark(painter: QPainter, element: Text, bounds: QRectF) -> None:
    settings = element.watermark
    if not settings.value.strip() or not settings.opacity:
        return
    font = annotation_font(element.font_size_px, element.style)
    metrics = QFontMetricsF(font)
    lines = settings.value.splitlines()
    x_step = max(12, max(metrics.horizontalAdvance(line) for line in lines) + settings.gap_px)
    y_step = max(12, len(lines) * metrics.lineSpacing() + settings.gap_px)
    inverse = QTransform().rotate(-settings.angle)
    extent = inverse.mapRect(bounds.translated(-bounds.center()))
    color = QColor(element.color)
    color.setAlphaF(color.alphaF() * settings.opacity / 100)
    painter.save()
    painter.setClipRect(bounds)
    painter.translate(bounds.center())
    painter.rotate(settings.angle)
    painter.setPen(color)
    painter.setFont(font)
    for row in range(floor(extent.top() / y_step) - 1, ceil(extent.bottom() / y_step) + 1):
        stagger = (row % 2) * x_step / 2
        for col in range(floor((extent.left() - stagger) / x_step) - 1,
                         ceil((extent.right() - stagger) / x_step) + 1):
            for index, line in enumerate(lines):
                painter.drawText(
                    QPointF(col * x_step + stagger, row * y_step + index * metrics.lineSpacing()),
                    line,
                )
    painter.restore()


def _pen(color: QColor, width_px: float, style: str = "solid") -> QPen:
    pen = QPen(color)
    pen.setWidthF(width_px)
    pen.setStyle(_LINE_STYLES.get(style, Qt.PenStyle.SolidLine))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _stroked(path: QPainterPath, width_px: float) -> QPainterPath:
    stroker = QPainterPathStroker()
    stroker.setWidth(max(width_px, 0.1))
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return stroker.createStroke(path)


def _path(stroke: Stroke) -> QPainterPath:
    points = [QPointF(*point) for point in stroke.points]
    first, last = points[0], points[-1]
    tool, style = stroke.tool, stroke.style
    path = QPainterPath()
    if tool in (Tool.RECTANGLE, Tool.ELLIPSE, Tool.RECT_HIGHLIGHT, Tool.RECT_ERASER):
        rect = QRectF(first, last).normalized()
        if tool is Tool.ELLIPSE:
            path.addEllipse(rect)
        else:
            radius = min(style.corner_radius_px, rect.width() / 2, rect.height() / 2)
            path.addRoundedRect(rect, radius, radius)
        return path

    path.moveTo(first)
    if tool is Tool.ARROW and style.arrow_type == "curve":
        path.quadTo(QPointF(*arrow_control(stroke)), last)
    elif tool is Tool.ARROW and style.arrow_type == "elbow":
        middle, _ = arrow_control(stroke)
        path.lineTo(middle, first.y())
        path.lineTo(middle, last.y())
        path.lineTo(last)
    elif len(points) == 1:
        path.lineTo(first + QPointF(.01, 0))
    else:
        for point in points[1:]:
            path.lineTo(point)
    return path


def arrow_control(stroke: Stroke) -> Point:
    start, end = stroke.points
    if stroke.control is not None:
        return stroke.control
    dx, dy = end[0] - start[0], end[1] - start[1]
    if stroke.style.arrow_type == "elbow":
        return start[0] + dx / 2, start[1] + dy / 2
    return start[0] + dx * .55 + dy * .23, start[1] + dy * .55 - dx * .23


def _arrowhead(tip: QPointF, nearby: QPointF, size: float, kind: str) -> QPainterPath:
    head = QPainterPath()
    delta = tip - nearby
    length = hypot(delta.x(), delta.y())
    if not length or kind == "none":
        return head
    if kind in ("dot", "circle", "circle_outline"):
        radius = size * (.18 if kind == "dot" else .3)
        head.addEllipse(tip - delta / length * radius, radius, radius)
        return head

    direction = delta / length
    side = QPointF(direction.y(), -direction.x()) * (size * .42)
    back = tip - direction * size
    if kind in ("bar", "crowfoot_one", "crowfoot_one_or_many"):
        center = tip if kind == "bar" else back
        head.moveTo(center + side)
        head.lineTo(center - side)
        if kind != "crowfoot_one_or_many":
            return head
    if kind in ("crowfoot_many", "crowfoot_one_or_many"):
        head.moveTo(tip + side)
        head.lineTo(back)
        head.lineTo(tip - side)
        return head
    head.moveTo(back + side)
    head.lineTo(tip)
    head.lineTo(back - side)
    if kind.startswith("diamond"):
        head.lineTo(tip - direction * (size * 1.55))
    elif kind == "indented_triangle":
        head.lineTo(tip - direction * (size * .72))
    if kind != "open":
        head.closeSubpath()
    return head


def _arrowheads(stroke: Stroke, path: QPainterPath) -> tuple[tuple[str, QPainterPath], ...]:
    style = stroke.style
    length = path.length()
    size = min(length * .48, max(stroke.width_px * 2, length * style.arrow_ratio / 250))
    return (
        (style.start_head, _arrowhead(path.pointAtPercent(0), path.pointAtPercent(.06),
                                      size, style.start_head)),
        (style.end_head, _arrowhead(path.pointAtPercent(1), path.pointAtPercent(.94),
                                    size, style.end_head)),
    )


def stroke_area(stroke: Stroke, tolerance: float = 0) -> QPainterPath:
    path = _path(stroke)
    return _stroke_area(stroke, path, tolerance)


def _stroke_area(stroke: Stroke, path: QPainterPath, tolerance: float) -> QPainterPath:
    width = stroke.width_px + 2 * tolerance
    area = _stroked(path, width)
    if stroke.tool in (Tool.RECT_ERASER, Tool.RECT_HIGHLIGHT):
        border = stroke.style.highlight_border if stroke.style.highlight_outline else 0
        edge = 2 * tolerance + border
        return path.united(_stroked(path, edge)) if edge else path
    if stroke.is_filled or stroke.style.fill_color:
        area = area.united(path)
    if stroke.tool is Tool.ARROW:
        width += stroke.style.arrow_outline_width * 2
        area = _stroked(path, width)
        for kind, head in _arrowheads(stroke, path):
            if kind != "none":
                area = area.united(head).united(_stroked(head, width))
    return area


def _draw_stroke(painter: QPainter, stroke: Stroke) -> None:
    path = _path(stroke)
    color = QColor(stroke.color)
    style = stroke.style
    if stroke.tool is Tool.RECT_HIGHLIGHT:
        painter.fillPath(path, color)
        if style.highlight_border and style.highlight_outline:
            painter.strokePath(path, _pen(QColor(style.highlight_outline), style.highlight_border))
        return
    if stroke.tool is Tool.HIGHLIGHT:
        painter.fillPath(_stroked(path, stroke.width_px), color)
        return

    if style.fill_color or stroke.is_filled:
        painter.fillPath(path, QColor(style.fill_color or stroke.color))
    if stroke.tool is Tool.ARROW:
        _draw_arrow(painter, stroke, path, color)
    elif stroke.tool is Tool.PEN and style.brush_mode == "pressure" and stroke.pressures:
        _draw_pressure_stroke(painter, stroke, color)
    elif style.line_effect == "precise":
        painter.strokePath(path, _pen(color, stroke.width_px, style.line_style))
    else:
        pen = _pen(color, stroke.width_px, style.line_style)
        artist = style.line_effect == "artist"
        amplitude = min(2.5, max(.6, stroke.width_px * .29))
        painter.strokePath(_sketched_path(path, amplitude, 0), pen)
        if artist:
            pen.setWidthF(max(.8, stroke.width_px * .36))
            painter.strokePath(_sketched_path(path, amplitude * 1.45, 1.8), pen)


def _draw_arrow(painter: QPainter, stroke: Stroke, path: QPainterPath, color: QColor) -> None:
    style = stroke.style
    outline = QColor(style.arrow_outline)
    edge = style.arrow_outline_width if outline.isValid() else 0
    line = style.shaft if style.shaft in ("dash", "dot") else style.line_style
    shaft_path = path
    if style.line_effect != "precise":
        shaft_path = _sketched_path(path, min(2.5, max(.6, stroke.width_px * .29)), 0)
    if style.shaft == "tapered" and line == "solid":
        shaft = _tapered_shaft(shaft_path, stroke.width_px)
        if edge:
            painter.strokePath(shaft, _pen(outline, edge * 2))
        painter.fillPath(shaft, color)
    elif style.shaft != "none":
        if edge:
            painter.strokePath(shaft_path, _pen(outline, stroke.width_px + edge * 2, line))
        painter.strokePath(shaft_path, _pen(color, stroke.width_px, line))
        if style.line_effect == "artist":
            painter.strokePath(_sketched_path(path, 2, 1.8), _pen(color, 1, line))
    for kind, head in _arrowheads(stroke, path):
        if kind == "none":
            continue
        is_open = kind in ("open", "bar", "crowfoot_one", "crowfoot_many", "crowfoot_one_or_many")
        is_open = is_open or kind.endswith("_outline")
        if edge:
            painter.strokePath(head, _pen(outline, edge * 2 + (stroke.width_px if is_open else 0)))
        if is_open:
            painter.strokePath(head, _pen(color, stroke.width_px))
        else:
            painter.fillPath(head, color)


def _tapered_shaft(path: QPainterPath, width: float) -> QPainterPath:
    polygons = path.toSubpathPolygons()
    if not polygons:
        return QPainterPath()
    polygon = polygons[0]
    left_side, right_side = [], []
    for index, point in enumerate(polygon):
        direction = polygon[min(index + 1, len(polygon) - 1)] - polygon[max(0, index - 1)]
        length = hypot(direction.x(), direction.y())
        if length:
            radius = width * (.15 + .35 * index / (len(polygon) - 1))
            normal = QPointF(-direction.y(), direction.x()) * (radius / length)
            left_side.append(point + normal)
            right_side.append(point - normal)
    shaft = QPainterPath()
    shaft.addPolygon(QPolygonF(left_side + right_side[::-1]))
    shaft.closeSubpath()
    return shaft


def _sketched_path(path: QPainterPath, amplitude: float, phase: float) -> QPainterPath:
    sketch = QPainterPath()
    for polygon in path.toSubpathPolygons():
        sketch.moveTo(polygon[0])
        distance = 0.0
        for start, end in pairwise(polygon):
            step = end - start
            length = hypot(step.x(), step.y())
            if length == 0:
                continue
            count = max(1, ceil(length / 5))
            normal = QPointF(-step.y(), step.x()) / length
            for index in range(1, count):
                fraction = index / count
                wave = sin((distance + length * fraction) / 6 + phase)
                sketch.lineTo(start + step * fraction + normal * (wave * amplitude))
            sketch.lineTo(end)
            distance += length
    return sketch


def _draw_pressure_stroke(painter: QPainter, stroke: Stroke, color: QColor) -> None:
    if len(stroke.points) == 1:
        radius = max(.5, stroke.width_px * stroke.pressures[0] / 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(*stroke.points[0]), radius, radius)
        return
    for index, (start, end) in enumerate(zip(stroke.points, stroke.points[1:])):
        pressure = (stroke.pressures[index] + stroke.pressures[index + 1]) / 2
        painter.setPen(_pen(color, max(1, stroke.width_px * pressure)))
        painter.drawLine(QPointF(*start), QPointF(*end))
