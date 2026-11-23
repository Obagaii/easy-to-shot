from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QKeyEvent,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPainterPath,
    QPen,
    QScreen,
)
from PySide6.QtWidgets import QWidget

from e2s.capture.geometry import (
    ResizeHandle,
    ScreenCoordinates,
    SelectionDrag,
    SelectionRect,
    move_selection,
)
from e2s.capture.service import CaptureError
from e2s.capture.session import CaptureSession

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
_ARROW_STEPS = {
    Qt.Key.Key_Left: (-1, 0),
    Qt.Key.Key_Right: (1, 0),
    Qt.Key.Key_Up: (0, -1),
    Qt.Key.Key_Down: (0, 1),
}
_HANDLE_HIT_DIP = 9


class CaptureOverlay(QWidget):
    cancelled = Signal()
    snapshot_confirmed = Signal(object)

    def __init__(self, session: CaptureSession) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._session = session
        self._frame = session.frame
        rect = self._frame.geometry_dip
        self._coordinates = ScreenCoordinates(
            rect.x(), rect.y(), rect.width(), rect.height(),
            self._frame.width_px, self._frame.height_px,
        )
        self._drag: SelectionDrag | None = None
        self._preview_selection: SelectionRect | None = None
        self._feedback = ""
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

    def show_on_screen(self, screen: QScreen) -> None:
        self.winId()
        self.windowHandle().setScreen(screen)
        self.setGeometry(self._frame.geometry_dip)
        self.showFullScreen()
        self.reactivate()

    def reactivate(self) -> None:
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        viewport = QRectF(self.rect())
        painter.drawImage(viewport, self._frame.image)

        selection = self._preview_selection if self._drag is not None else self._session.selection
        shade = QPainterPath()
        shade.addRect(viewport)
        if selection is not None:
            rect = self._selection_on_screen(selection)
            shade.addRect(rect)
        painter.fillPath(shade, QColor(0, 0, 0, 150))
        if selection is not None:
            painter.setPen(QPen(Qt.GlobalColor.white, 1))
            painter.drawRect(rect)
            for _, point in self._resize_handles(rect):
                painter.fillRect(QRectF(point.x() - 3, point.y() - 3, 6, 6), Qt.GlobalColor.white)
            dimensions = f"{selection.width_px} × {selection.height_px} px"
            bottom = rect.top() - 8 if rect.top() >= 40 else rect.bottom() + 32
            self._draw_label(painter, dimensions, rect.left(), bottom)

        if self._drag is None:
            message = self._feedback or (
                "拖动框选 · Esc 取消"
                if selection is None
                else "拖动选区或缩放手柄 · 方向键微调 · Enter 确认选区 · Esc 取消"
            )
            label_width = painter.fontMetrics().horizontalAdvance(message) + 20
            self._draw_label(painter, message, (self.width() - label_width) / 2, 36)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        position = event.position()
        selection, handle = self._hit_selection(position)
        self._drag = SelectionDrag(self._source_position(position), selection, handle)
        self._feedback = ""
        self._update_drag(position)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag is not None:
            self._update_drag(event.position())
        else:
            self._update_cursor(event.position())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._drag is None:
            return
        self._update_drag(event.position())
        self._session.set_selection(self._preview_selection)
        self._preview_selection = None
        self._drag = None
        self._update_cursor(event.position())

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
        elif self._drag is not None:
            event.accept()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not event.isAutoRepeat():
                try:
                    snapshot = self._session.create_snapshot()
                except (CaptureError, MemoryError) as error:
                    self._feedback = (
                        str(error) if isinstance(error, CaptureError) else "内存不足，请缩小选区。"
                    )
                    self.update()
                    return
                self.snapshot_confirmed.emit(snapshot)
        elif key in _ARROW_STEPS and self._session.selection is not None:
            step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            dx, dy = _ARROW_STEPS[key]
            self._session.set_selection(
                move_selection(
                    self._session.selection, dx * step, dy * step,
                    self._frame.width_px, self._frame.height_px,
                )
            )
            self._feedback = ""
            self.update()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.cancelled.emit()
        event.accept()

    def _source_position(self, point: QPointF) -> tuple[float, float]:
        coordinates = self._coordinates
        # The cursor reaches the last displayed DIP, not the outer half-open edge.
        x_dip = coordinates.width_dip if point.x() >= coordinates.width_dip - 1 else point.x()
        y_dip = coordinates.height_dip if point.y() >= coordinates.height_dip - 1 else point.y()
        return coordinates.to_source(
            coordinates.origin_x_dip + x_dip, coordinates.origin_y_dip + y_dip
        )

    def _update_drag(self, position: QPointF) -> None:
        self._preview_selection = self._drag.update(
            self._source_position(position), self._frame.width_px, self._frame.height_px
        )
        self.update()

    def _update_cursor(self, position: QPointF) -> None:
        selection, handle = self._hit_selection(position)
        if handle is not None:
            self.setCursor(_CURSORS[handle])
        elif selection is not None:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    def _selection_on_screen(self, selection: SelectionRect) -> QRectF:
        to_dip = self._coordinates.to_local_dip
        return QRectF(
            QPointF(*to_dip(selection.left, selection.top)),
            QPointF(*to_dip(selection.right, selection.bottom)),
        )

    @staticmethod
    def _resize_handles(rect: QRectF) -> tuple[tuple[ResizeHandle, QPointF], ...]:
        center = rect.center()
        return (
            (ResizeHandle.TOP_LEFT, rect.topLeft()),
            (ResizeHandle.TOP, QPointF(center.x(), rect.top())),
            (ResizeHandle.TOP_RIGHT, rect.topRight()),
            (ResizeHandle.RIGHT, QPointF(rect.right(), center.y())),
            (ResizeHandle.BOTTOM_RIGHT, rect.bottomRight()),
            (ResizeHandle.BOTTOM, QPointF(center.x(), rect.bottom())),
            (ResizeHandle.BOTTOM_LEFT, rect.bottomLeft()),
            (ResizeHandle.LEFT, QPointF(rect.left(), center.y())),
        )

    def _hit_selection(self, position: QPointF) -> tuple[SelectionRect | None, ResizeHandle | None]:
        selection = self._session.selection
        if selection is None:
            return None, None
        rect = self._selection_on_screen(selection)

        def distance(handle: tuple[ResizeHandle, QPointF]) -> float:
            delta = handle[1] - position
            return delta.x() ** 2 + delta.y() ** 2

        nearest = min(self._resize_handles(rect), key=distance)
        is_inside = rect.contains(position)
        hit_radius = _HANDLE_HIT_DIP
        if is_inside:
            hit_radius = min(hit_radius, rect.width() / 3, rect.height() / 3)
        if distance(nearest) <= hit_radius ** 2:
            return selection, nearest[0]
        if is_inside:
            return selection, None
        return None, None

    def _draw_label(self, painter: QPainter, text: str, left: float, bottom: float) -> None:
        width = painter.fontMetrics().horizontalAdvance(text) + 20
        x = max(0, min(left, self.width() - width))
        y = max(0, min(bottom - 24, self.height() - 24))
        rect = QRectF(x, y, width, 24)
        painter.fillRect(rect, QColor(18, 28, 39, 235))
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
