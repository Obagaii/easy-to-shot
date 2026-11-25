from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from e2s.capture.geometry import ResizeHandle

CORNERS = (
    ResizeHandle.TOP_LEFT, ResizeHandle.TOP_RIGHT, ResizeHandle.BOTTOM_RIGHT, ResizeHandle.BOTTOM_LEFT
)
_CURSORS = {
    ResizeHandle.TOP_LEFT: Qt.CursorShape.SizeFDiagCursor,
    ResizeHandle.TOP: Qt.CursorShape.SizeVerCursor,
    ResizeHandle.TOP_RIGHT: Qt.CursorShape.SizeBDiagCursor,
    ResizeHandle.RIGHT: Qt.CursorShape.SizeHorCursor,
    ResizeHandle.BOTTOM_RIGHT: Qt.CursorShape.SizeFDiagCursor,
    ResizeHandle.BOTTOM: Qt.CursorShape.SizeVerCursor,
    ResizeHandle.BOTTOM_LEFT: Qt.CursorShape.SizeBDiagCursor,
    ResizeHandle.LEFT: Qt.CursorShape.SizeHorCursor,
}
_SELECTION_HANDLES = tuple(ResizeHandle)
_FRAME_ACCENT = QColor("#58dcfa")
_FRAME_OUTLINE = QColor("#172b3d")
_ACTIVE_GRIP = QColor("#ffffff")
_VIEWPORT_INSET_DIP = 4


def handle_positions(
    rect: QRectF, handles: tuple[ResizeHandle, ...] = _SELECTION_HANDLES
) -> tuple[tuple[ResizeHandle, QPointF], ...]:
    center = rect.center()
    xs = {-1: rect.left(), 0: center.x(), 1: rect.right()}
    ys = {-1: rect.top(), 0: center.y(), 1: rect.bottom()}
    return tuple((handle, QPointF(xs[handle.value[0]], ys[handle.value[1]])) for handle in handles)


def frame_handle_positions(
    rect: QRectF, viewport: QRectF
) -> tuple[tuple[ResizeHandle, QPointF], ...]:
    """Keep grip centers inside the viewport when the frame reaches a window edge."""
    inset_x = min(_VIEWPORT_INSET_DIP, viewport.width() / 4)
    inset_y = min(_VIEWPORT_INSET_DIP, viewport.height() / 4)
    inner = viewport.adjusted(inset_x, inset_y, -inset_x, -inset_y)
    return tuple(
        (
            handle,
            QPointF(
                min(inner.right(), max(inner.left(), center.x())),
                min(inner.bottom(), max(inner.top(), center.y())),
            ),
        )
        for handle, center in handle_positions(rect)
    )


def draw_resize_frame(
    painter: QPainter, rect: QRectF, viewport: QRectF, active: ResizeHandle | None = None
) -> None:
    """Paint the capture and pin frame in logical widget coordinates."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(_FRAME_OUTLINE, 2.5))
    painter.drawRect(rect)
    painter.setPen(QPen(_FRAME_ACCENT, 1))
    painter.drawRect(rect)

    length = min(12, rect.width() / 4, rect.height() / 4)
    for handle, point in frame_handle_positions(rect, viewport):
        horizontal, vertical = handle.value
        color = _ACTIVE_GRIP if handle is active else _FRAME_ACCENT
        if horizontal and vertical:
            corner = QPainterPath(point + QPointF(-horizontal * length, 0))
            corner.lineTo(point)
            corner.lineTo(point + QPointF(0, -vertical * length))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for stroke, width in ((_FRAME_OUTLINE, 6), (color, 3)):
                pen = QPen(
                    stroke, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
                painter.setPen(pen)
                painter.drawPath(corner)
        else:
            span = min(18, (rect.height() if horizontal else rect.width()) / 3)
            width, height = (6, span) if horizontal else (span, 6)
            grip = QRectF(point.x() - width / 2, point.y() - height / 2, width, height)
            painter.setPen(QPen(_FRAME_OUTLINE, 1.5))
            painter.setBrush(color)
            painter.drawRoundedRect(grip, 3, 3)
    painter.restore()


def resize_cursor(handle: ResizeHandle) -> Qt.CursorShape:
    return _CURSORS[handle]
