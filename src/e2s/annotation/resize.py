from dataclasses import dataclass, replace
from enum import Enum
from math import hypot

from PySide6.QtCore import QPointF, QRectF

from e2s.annotation.elements import (
    MAX_STROKE_WIDTH_PX,
    Element,
    Point,
    Stroke,
)
from e2s.annotation.renderer import element_bounds
from e2s.capture.geometry import ResizeHandle


class Endpoint(Enum):
    START = 0
    END = -1


def resize_bounds(element: Element) -> QRectF:
    if len(element.points) == 1:
        return element_bounds(element)
    points = element.points
    xs, ys = zip(*points)
    rect = QRectF(QPointF(min(xs), min(ys)), QPointF(max(xs), max(ys)))
    if rect.width() == 0:
        rect.adjust(-0.5, 0, 0.5, 0)
    if rect.height() == 0:
        rect.adjust(0, -0.5, 0, 0.5)
    return rect


@dataclass(frozen=True, slots=True)
class ElementResize:
    element: Element
    handle: ResizeHandle | Endpoint
    bounds: QRectF

    def update(self, dx_px: float, dy_px: float) -> Element:
        element = self.element
        if not dx_px and not dy_px:
            return element
        if isinstance(self.handle, Endpoint):
            return self._move_endpoint(dx_px, dy_px)

        horizontal, vertical = self.handle.value
        left, top = self.bounds.left(), self.bounds.top()
        width, height = self.bounds.width(), self.bounds.height()
        if len(element.points) == 1:
            anchor = (left + width if horizontal < 0 else left, top + height if vertical < 0 else top)
            diagonal_x, diagonal_y = horizontal * width, vertical * height
            scale = 1 + (dx_px * diagonal_x + dy_px * diagonal_y) / (width**2 + height**2)
            old_size = element.width_px
            size = max(1, min(MAX_STROKE_WIDTH_PX, round(old_size * scale)))
            center = _scale_from(element.points[0], anchor, size / old_size)
            return replace(element, points=(center,), width_px=size)

        new_width = max(min(2, width), width + horizontal * dx_px)
        new_height = max(min(2, height), height + vertical * dy_px)
        if horizontal < 0:
            left += width - new_width
        if vertical < 0:
            top += height - new_height
        origin_x, origin_y = self.bounds.left(), self.bounds.top()

        def map_point(point: Point) -> Point:
            return (
                left + (point[0] - origin_x) * new_width / width,
                top + (point[1] - origin_y) * new_height / height,
            )

        return replace(element, points=tuple(map_point(point) for point in element.points))

    def _move_endpoint(self, dx_px: float, dy_px: float) -> Element:
        element, handle = self.element, self.handle
        if not isinstance(element, Stroke) or not isinstance(handle, Endpoint):
            return element
        start, end = element.points
        if handle is Endpoint.START:
            start = start[0] + dx_px, start[1] + dy_px
        else:
            end = end[0] + dx_px, end[1] + dy_px
        if hypot(end[0] - start[0], end[1] - start[1]) < 1:
            return element
        return replace(element, points=(start, end))


def _scale_from(point: Point, anchor: Point, scale: float) -> Point:
    return (
        anchor[0] + (point[0] - anchor[0]) * scale,
        anchor[1] + (point[1] - anchor[1]) * scale,
    )
