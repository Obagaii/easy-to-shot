from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, Qt, Signal, SignalInstance
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
from e2s.ui.native.canvas import AnnotationCanvas
from e2s.ui.native.resize_handles import handle_positions, resize_cursor

_CAPTURE_ACCENT = QColor("#58dcfa")
_CAPTURE_OUTLINE = QColor("#172b3d")
_ARROW_STEPS = {
    Qt.Key.Key_Left: (-1, 0),
    Qt.Key.Key_Right: (1, 0),
    Qt.Key.Key_Up: (0, -1),
    Qt.Key.Key_Down: (0, 1),
}
_HANDLE_HIT_DIP = 12
_BORDER_HIT_DIP = 4


class CaptureOverlay(QWidget):
    cancelled = Signal()
    copy_requested = Signal(object)
    save_requested = Signal(object)
    pin_requested = Signal(object)

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
        self._canvas: AnnotationCanvas | None = None
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

    def selection_origin(self, selection: SelectionRect) -> QPoint:
        """Return the global Qt desktop position of the selection's top-left pixel."""
        return self.mapToGlobal(self._selection_on_screen(selection).topLeft().toPoint())

    def reactivate(self) -> None:
        self.raise_()
        self.activateWindow()
        if self._canvas is None:
            self.setFocus()
        else:
            self._canvas.focus_input()

    def set_output_feedback(self, message: str, *, is_pending: bool = False) -> None:
        if self._canvas is not None:
            self._canvas.set_output_pending(is_pending)
            self._canvas.set_feedback(message)
            if not is_pending:
                self._canvas.focus_input()

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
        if self._canvas is None:
            self._paint_selection_frame(painter)
            if self._drag is None:
                message = self._feedback or "拖动框选 · Esc 取消"
                width = painter.fontMetrics().horizontalAdvance(message) + 20
                self._draw_label(painter, message, (self.width() - width) / 2, 36)

    def _paint_selection_frame(self, painter: QPainter) -> None:
        selection = self._preview_selection if self._drag is not None else self._session.selection
        if selection is None:
            return
        rect = self._selection_on_screen(selection)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_CAPTURE_OUTLINE, 2.5))
        painter.drawRect(rect)
        painter.setPen(QPen(_CAPTURE_ACCENT, 1))
        painter.drawRect(rect)
        self._paint_resize_handles(painter, rect)
        painter.restore()
        dimensions = f"{selection.width_px} × {selection.height_px} px"
        bottom = rect.top() - 8 if rect.top() >= 40 else rect.bottom() + 32
        self._draw_label(painter, dimensions, rect.left(), bottom)

    def _paint_resize_handles(self, painter: QPainter, rect: QRectF) -> None:
        active = self._drag.resize_handle if self._drag is not None else None
        length = min(12, rect.width() / 4, rect.height() / 4)
        viewport = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        for handle, center in handle_positions(rect):
            horizontal, vertical = handle.value
            # Keep the handles visible when the crop reaches an edge of the display.
            point = QPointF(
                min(viewport.right(), max(viewport.left(), center.x())),
                min(viewport.bottom(), max(viewport.top(), center.y())),
            )
            color = QColor("#ffffff") if handle is active else _CAPTURE_ACCENT
            if horizontal and vertical:
                corner = QPainterPath(point + QPointF(-horizontal * length, 0))
                corner.lineTo(point)
                corner.lineTo(point + QPointF(0, -vertical * length))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                for stroke, width in ((_CAPTURE_OUTLINE, 6), (color, 3)):
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
                painter.setPen(QPen(_CAPTURE_OUTLINE, 1.5))
                painter.setBrush(color)
                painter.drawRoundedRect(grip, 3, 3)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is not self._canvas or not isinstance(event, QMouseEvent):
            return super().eventFilter(watched, event)

        kind = event.type()
        if kind == QEvent.Type.MouseMove:
            if self._drag is not None:
                self._update_drag(event.position())
                return True
            drag = self._selection_drag_at(event.position())
            if drag is not None:
                self._canvas.setCursor(self._drag_cursor(drag))
                return True
        elif kind == QEvent.Type.MouseButtonRelease and self._drag is not None:
            self.mouseReleaseEvent(event)
            return True
        elif kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            if event.button() == Qt.MouseButton.LeftButton:
                drag = self._selection_drag_at(event.position())
                if drag is not None:
                    self._start_drag(drag, event.position())
                    return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            drag = self._selection_drag_at(event.position())
            if drag is not None:
                self._start_drag(drag, event.position())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag is not None:
            self._update_drag(event.position())
        else:
            self._update_cursor(event.position())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._drag is None:
            return
        self._update_drag(event.position())
        selection = self._preview_selection
        self._preview_selection = None
        self._drag = None
        if selection is not None:
            self._set_selection(selection)
        if self._canvas is not None:
            self._canvas.preview_selection(None)
            self._canvas.focus_input()
        self._update_cursor(event.position())
        self.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
        elif self._drag is not None:
            event.accept()
        elif (
            key in _ARROW_STEPS
            and self._session.selection is not None
            and (self._canvas is None or self._canvas.can_adjust_selection)
        ):
            step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            dx, dy = _ARROW_STEPS[key]
            self._set_selection(
                move_selection(
                    self._session.selection, dx * step, dy * step,
                    self._frame.width_px, self._frame.height_px,
                )
            )
        else:
            super().keyPressEvent(event)

    def _set_selection(self, selection: SelectionRect) -> None:
        previous = self._session.selection
        try:
            self._session.set_selection(selection)
            if self._canvas is None:
                self._show_annotation_canvas(selection)
            elif selection != previous:
                self._canvas.set_selection_target(self._selection_on_screen(selection))
        except (CaptureError, MemoryError) as error:
            message = str(error) if isinstance(error, CaptureError) else "内存不足，请缩小选区。"
            self._feedback = message
            if self._canvas is not None:
                self._canvas.set_feedback(message)
        self.update()

    def _show_annotation_canvas(self, selection: SelectionRect) -> None:
        canvas = AnnotationCanvas(
            self._session.begin_annotation(),
            self._selection_on_screen(selection),
            self,
            draw_selection_frame=self._paint_selection_frame,
        )
        self._canvas = canvas
        canvas.installEventFilter(self)
        canvas.cancelled.connect(self.close)
        canvas.copy_requested.connect(lambda: self._request_output(self.copy_requested))
        canvas.save_requested.connect(lambda: self._request_output(self.save_requested))
        canvas.pin_requested.connect(lambda: self._request_output(self.pin_requested))
        canvas.setGeometry(self.rect())
        canvas.show()

    def _request_output(self, requested: SignalInstance) -> None:
        if self._drag is not None:
            return
        try:
            snapshot = self._session.create_snapshot()
        except (CaptureError, MemoryError) as error:
            self.set_output_feedback(
                str(error) if isinstance(error, CaptureError) else "内存不足，无法生成截图。"
            )
            return
        requested.emit(snapshot)

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

    def _selection_drag_at(self, position: QPointF) -> SelectionDrag | None:
        canvas = self._canvas
        if canvas is not None and not canvas.can_adjust_selection:
            return None
        selection, handle = self._hit_selection(position)
        if canvas is not None and selection is not None and handle is None:
            if canvas.has_resize_handle_at(position):
                return None
            rect = self._selection_on_screen(selection)
            margin = min(_BORDER_HIT_DIP, rect.width() / 4, rect.height() / 4)
            interior = rect.adjusted(margin, margin, -margin, -margin)
            if interior.contains(position) and not canvas.can_move_selection_at(position):
                return None
        return SelectionDrag(self._source_position(position), selection, handle)

    def _start_drag(self, drag: SelectionDrag, position: QPointF) -> None:
        self._drag = drag
        self._feedback = ""
        if self._canvas is not None:
            self._canvas.set_feedback("")
            self._canvas.setCursor(self._drag_cursor(drag))
        self._update_drag(position)

    def _update_drag(self, position: QPointF) -> None:
        self._preview_selection = self._drag.update(
            self._source_position(position), self._frame.width_px, self._frame.height_px
        )
        if self._canvas is not None:
            selection = self._preview_selection
            target = self._selection_on_screen(selection) if selection is not None else QRectF()
            self._canvas.preview_selection(target)
        self.update()

    def _update_cursor(self, position: QPointF) -> None:
        drag = self._selection_drag_at(position)
        if drag is not None:
            (self._canvas or self).setCursor(self._drag_cursor(drag))
        elif self._canvas is not None:
            self._canvas.update_pointer_cursor(position)

    @staticmethod
    def _drag_cursor(drag: SelectionDrag) -> Qt.CursorShape:
        if drag.resize_handle is not None:
            return resize_cursor(drag.resize_handle)
        if drag.selection is not None:
            return Qt.CursorShape.SizeAllCursor
        return Qt.CursorShape.CrossCursor

    def _selection_on_screen(self, selection: SelectionRect) -> QRectF:
        to_dip = self._coordinates.to_local_dip
        return QRectF(
            QPointF(*to_dip(selection.left, selection.top)),
            QPointF(*to_dip(selection.right, selection.bottom)),
        )


    def _hit_selection(self, position: QPointF) -> tuple[SelectionRect | None, ResizeHandle | None]:
        selection = self._session.selection
        if selection is None:
            return None, None
        rect = self._selection_on_screen(selection)

        def distance(handle: tuple[ResizeHandle, QPointF]) -> float:
            delta = handle[1] - position
            return delta.x() ** 2 + delta.y() ** 2

        nearest = min(handle_positions(rect), key=distance)
        is_inside = rect.contains(position)
        hit_radius = _HANDLE_HIT_DIP
        if is_inside:
            hit_radius = min(hit_radius, rect.width() / 3, rect.height() / 3)
        if distance(nearest) <= hit_radius ** 2:
            return selection, nearest[0]
        margin = _BORDER_HIT_DIP
        if rect.adjusted(-margin, -margin, margin, margin).contains(position):
            return selection, None
        return None, None

    def _draw_label(self, painter: QPainter, text: str, left: float, bottom: float) -> None:
        width = painter.fontMetrics().horizontalAdvance(text) + 20
        x = max(0, min(left, self.width() - width))
        y = max(0, min(bottom - 24, self.height() - 24))
        rect = QRectF(x, y, width, 24)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#425d74"), 1))
        painter.setBrush(QColor(18, 28, 39, 240))
        painter.drawRoundedRect(rect, 6, 6)
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()
