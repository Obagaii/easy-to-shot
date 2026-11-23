from PySide6.QtCore import QPointF, QRectF, Qt

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


def handle_positions(
    rect: QRectF, handles: tuple[ResizeHandle, ...] = _SELECTION_HANDLES
) -> tuple[tuple[ResizeHandle, QPointF], ...]:
    center = rect.center()
    xs = {-1: rect.left(), 0: center.x(), 1: rect.right()}
    ys = {-1: rect.top(), 0: center.y(), 1: rect.bottom()}
    return tuple((handle, QPointF(xs[handle.value[0]], ys[handle.value[1]])) for handle in handles)


def resize_cursor(handle: ResizeHandle) -> Qt.CursorShape:
    return _CURSORS[handle]
