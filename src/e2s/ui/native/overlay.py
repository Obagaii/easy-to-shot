from dataclasses import replace
from collections.abc import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QCursor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QScreen,
    QWheelEvent,
)
from PySide6.QtWidgets import QApplication, QWidget

from e2s.capture.geometry import (
    ResizeHandle,
    ScreenCoordinates,
    SelectionDrag,
    SelectionRect,
    move_selection,
)
from e2s.capture.ocr import OcrLine
from e2s.capture.ocr_overlay import render_text_cover
from e2s.capture.qr import CodeDetection
from e2s.capture.service import CaptureError
from e2s.capture.session import CaptureSession, OutputSnapshot
from e2s.platform.windows.uia_selection import WindowsSelector
from e2s.platform.windows.window_capture import monitor_pixel_bounds
from e2s.ui.native.canvas import AnnotationCanvas
from e2s.ui.native.ocr_workspace import OcrWorkspace
from e2s.ui.native.qr_results import QrResults
from e2s.ui.native.resize_handles import (
    draw_resize_frame,
    handle_positions,
    resize_cursor,
)
from e2s.ui.native.smart_selection import SmartSelection

_ARROW_STEPS = {
    Qt.Key.Key_Left: (-1, 0),
    Qt.Key.Key_Right: (1, 0),
    Qt.Key.Key_Up: (0, -1),
    Qt.Key.Key_Down: (0, 1),
    Qt.Key.Key_A: (-1, 0),
    Qt.Key.Key_D: (1, 0),
    Qt.Key.Key_W: (0, -1),
    Qt.Key.Key_S: (0, 1),
}
_HANDLE_HIT_DIP = 12
_BORDER_HIT_DIP = 4
_SMART_PREVIEW_DURATION_MS = 120


class CaptureOverlay(QWidget):
    cancelled = Signal()
    copy_requested = Signal(object)
    save_requested = Signal(object)
    pin_requested = Signal(object)
    action_requested = Signal(str, object)

    def __init__(self, session: CaptureSession, selector: WindowsSelector) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._session = session
        self._selector = selector
        self._qr_results = QrResults(self)
        self._ocr_workspace: OcrWorkspace | None = None
        self._frame = session.frame
        rect = self._frame.geometry_dip
        self._coordinates = ScreenCoordinates(
            rect.x(), rect.y(), rect.width(), rect.height(),
            self._frame.width_px, self._frame.height_px,
        )
        self._drag: SelectionDrag | None = None
        self._preview_selection: SelectionRect | None = None
        self._smart_selection: SmartSelection | None = None
        self._smart_preview: SelectionRect | None = None
        self._smart_preview_animation = QVariantAnimation(
            self, duration=_SMART_PREVIEW_DURATION_MS, easingCurve=QEasingCurve.Type.OutQuad,
        )
        self._smart_preview_animation.valueChanged.connect(lambda _: self.update())
        self._press_position: QPointF | None = None
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
        if self._canvas is None and QApplication.platformName() == "windows":
            self._start_smart_selection()
        self.reactivate()

    def _start_smart_selection(self) -> None:
        window_id = int(self.winId())
        monitor = monitor_pixel_bounds(window_id)
        if monitor is None or not self._selector.available:
            self._on_selector_failed()
            return
        self._smart_selection = SmartSelection(
            self._selector, window_id, monitor, self,
        )
        self._smart_selection.changed.connect(self._update_smart_preview)
        self._smart_selection.failed.connect(self._on_selector_failed)
        self._update_hover(QPointF(self.mapFromGlobal(QCursor.pos())))

    def release_smart_selection(self) -> None:
        smart, self._smart_selection = self._smart_selection, None
        if smart is not None:
            smart.stop()
            smart.deleteLater()
            self._clear_smart_preview()

    def _update_smart_preview(self) -> None:
        selection = self._smart_selection.selection
        # Keep the last frame visible while the selector looks up the next target.
        if selection is not None and selection != self._smart_preview:
            animation = self._smart_preview_animation
            target = self._selection_on_screen(selection)
            start = animation.currentValue() if self._smart_preview is not None else target
            self._smart_preview = selection
            animation.stop()
            animation.setStartValue(start)
            animation.setEndValue(target)
            if start != target:
                animation.start()
            else:
                animation.setCurrentTime(animation.duration())
        self.update()

    def _clear_smart_preview(self) -> None:
        self._smart_preview = None
        self._smart_preview_animation.stop()
        self.update()

    def _on_selector_failed(self) -> None:
        self.release_smart_selection()
        self._feedback = "智能选区不可用 · 拖动框选 · Esc 取消"
        self.update()

    def selection_origin(self, selection: SelectionRect) -> QPoint:
        """Return the global Qt desktop position of the selection's top-left pixel."""
        return self.mapToGlobal(self._selection_on_screen(selection).topLeft().toPoint())

    def capture_size_px(self) -> tuple[int, int]:
        return self._frame.width_px, self._frame.height_px

    def selection_geometry(self, selection: SelectionRect) -> QRect:
        rect = self._selection_on_screen(selection).toAlignedRect()
        return QRect(self.mapToGlobal(rect.topLeft()), rect.size())

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

    def cover_text(
        self, snapshot: OutputSnapshot, lines: tuple[OcrLine, ...], text: tuple[str, ...]
    ) -> None:
        if self._canvas is None or self._session.selection != snapshot.selection:
            raise CaptureError("截图选区已变化，请重新识别文字。")
        patch = render_text_cover(snapshot, lines, text)
        self._canvas.add_image_patch(patch)
        self.set_output_feedback("已覆盖到截图，可按 Ctrl+Z 撤销。")

    def show_ocr_results(
        self, snapshot: OutputSnapshot, lines: tuple[OcrLine, ...], language: str
    ) -> None:
        if self._session.selection != snapshot.selection:
            self.set_output_feedback("截图选区已变化，请重新识别文字。")
            return
        self._dismiss_ocr_workspace()
        region = self._selection_on_screen(snapshot.selection).toAlignedRect()
        workspace = OcrWorkspace(snapshot, lines, region, self, language=language)
        self._ocr_workspace = workspace
        workspace.closed.connect(lambda: self._close_ocr_workspace(workspace))
        workspace.show()
        workspace.raise_()
        workspace._editor.setFocus()

    def _dismiss_ocr_workspace(self) -> None:
        if self._ocr_workspace is not None:
            self._ocr_workspace.close()

    def _close_ocr_workspace(self, workspace: OcrWorkspace) -> None:
        if self._ocr_workspace is workspace:
            self._ocr_workspace = None
            workspace.deleteLater()
            self.reactivate()

    def show_code_results(self, detections: tuple[CodeDetection, ...]) -> None:
        selection = self._session.selection
        if selection is not None:
            self._qr_results.show(detections, self._selection_on_screen(selection))

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        viewport = QRectF(self.rect())
        painter.drawImage(viewport, self._frame.image)

        selection, rect = self._painted_selection()
        shade = QPainterPath()
        shade.addRect(viewport)
        if selection is not None:
            shade.addRect(rect)
        if self._smart_preview is not None:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillPath(shade, QColor(0, 0, 0, 150))
        if self._canvas is None:
            self._paint_selection_frame(painter)
            if self._drag is None:
                message = self._feedback or "拖动框选 · Esc 取消"
                smart = self._smart_selection
                if not self._feedback and smart is not None and smart.selection is not None:
                    target = "窗口" if smart.window_only else "控件"
                    message = f"智能选区（{target}） · 单击确认 · Tab 切换 · " + message
                    if smart.has_levels:
                        message += " · 滚轮切换层级"
                width = painter.fontMetrics().horizontalAdvance(message) + 20
                self._draw_label(painter, message, (self.width() - width) / 2, 36)

    def _displayed_selection(self) -> SelectionRect | None:
        if self._drag is not None:
            return self._preview_selection
        if self._smart_selection is not None:
            return self._smart_selection.selection
        return self._session.selection

    def _painted_selection(self) -> tuple[SelectionRect | None, QRectF]:
        if self._smart_selection is not None and self._drag is None:
            if self._smart_preview is not None:
                return self._smart_preview, self._smart_preview_animation.currentValue()
            return None, QRectF()
        selection = self._displayed_selection()
        return selection, self._selection_on_screen(selection) if selection is not None else QRectF()

    def _paint_selection_frame(self, painter: QPainter) -> None:
        selection, rect = self._painted_selection()
        if selection is None:
            return
        active = self._drag.resize_handle if self._drag is not None else None
        is_smart_preview = self._smart_selection is not None and self._drag is None
        draw_resize_frame(
            painter, rect, QRectF(self.rect()), active, show_handles=not is_smart_preview,
        )
        dimensions = f"{selection.width_px} × {selection.height_px} px"
        bottom = rect.top() - 8
        if not is_smart_preview and rect.top() < 40:
            bottom = rect.bottom() + 32
        self._draw_label(painter, dimensions, rect.left(), bottom)

    def event(self, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent)
            and event.key() == Qt.Key.Key_Tab
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
            and self._drag is None and self._smart_selection is not None
            and (event.isAutoRepeat() or self._smart_selection.toggle_target())
        ):
            event.accept()
            return True
        return super().event(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._canvas and event.type() == QEvent.Type.MouseButtonPress:
            self._qr_results.clear()
        if (
            watched is not self._canvas or not isinstance(event, QMouseEvent)
            or self._canvas.is_sampling_color
        ):
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
            position = event.position()
            self._update_hover(position)
            smart = self._smart_selection
            if smart is not None and smart.selection is not None:
                self._press_position = position
                smart.pause()
                animation = self._smart_preview_animation
                animation.stop()
                animation.setCurrentTime(animation.duration())
                event.accept()
                return
            drag = self._selection_drag_at(position)
            if drag is not None:
                self._start_drag(drag, event.position())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        position = event.position()
        self._maybe_start_manual_drag(position)
        if self._drag is not None:
            self._update_drag(position)
        else:
            self._update_hover(position)
            self._update_cursor(position)

    def leaveEvent(self, event: QEvent) -> None:
        if self._press_position is None and self._smart_selection is not None:
            self._smart_selection.clear()
            self._clear_smart_preview()
        super().leaveEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        smart = self._smart_selection
        if self._press_position is None and smart is not None and delta:
            self._update_hover(event.position())
            if smart.step(1 if delta > 0 else -1):
                event.accept()
                return
        super().wheelEvent(event)

    def _update_hover(self, position: QPointF) -> None:
        smart = self._smart_selection
        if smart is None or self._press_position is not None:
            return
        if not QRectF(self.rect()).contains(position):
            smart.clear()
            self._clear_smart_preview()
            return
        x, y = self._coordinates.to_source(
            self._coordinates.origin_x_dip + position.x(),
            self._coordinates.origin_y_dip + position.y(),
        )
        smart.move((min(int(x), self._frame.width_px - 1), min(int(y), self._frame.height_px - 1)))

    def _maybe_start_manual_drag(self, position: QPointF) -> None:
        origin = self._press_position
        if origin is None:
            return
        delta = position - origin
        distance = QApplication.startDragDistance()
        if delta.x() ** 2 + delta.y() ** 2 >= distance ** 2:
            self._press_position = None
            if self._smart_selection is not None:
                self._smart_selection.clear()
            self._start_drag(SelectionDrag(self._source_position(origin)), origin)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        position = event.position()
        self._maybe_start_manual_drag(position)
        if self._press_position is not None:
            selection = self._displayed_selection()
            self._press_position = None
            if selection is not None and self._selection_on_screen(selection).contains(position):
                self._set_selection(selection)
            self._resume_smart_selection(position)
            event.accept()
            return
        if self._drag is None:
            return
        self._update_drag(position)
        selection = self._preview_selection
        self._preview_selection = None
        self._drag = None
        if selection is not None:
            self._set_selection(selection)
        if self._canvas is not None:
            self._canvas.preview_selection(None)
            self._canvas.focus_input()
        self._resume_smart_selection(position)
        self._update_cursor(position)
        self.update()

    def _resume_smart_selection(self, position: QPointF) -> None:
        if self._smart_selection is not None:
            self._smart_selection.resume()
            self._update_hover(position)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
        elif self._drag is not None:
            event.accept()
        elif (
            key in _ARROW_STEPS
            and event.modifiers() in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier)
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
        if previous != selection:
            self._dismiss_ocr_workspace()
            self._qr_results.clear()
        try:
            self._session.set_selection(selection)
            if self._canvas is None:
                self._show_annotation_canvas(selection)
                self.release_smart_selection()
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
            sample_screen_color=self._sample_screen_color,
        )
        self._canvas = canvas
        canvas.installEventFilter(self)
        canvas._toolbar.tool_changed.connect(lambda _tool: self._dismiss_ocr_workspace())
        canvas.cancelled.connect(self.close)
        canvas.copy_requested.connect(lambda: self._request_output(self.copy_requested.emit))
        canvas.save_requested.connect(lambda: self._request_output(self.save_requested.emit))
        canvas.pin_requested.connect(lambda: self._request_output(self.pin_requested.emit))
        canvas.output_requested.connect(self._request_capture_action)
        canvas.setGeometry(self.rect())
        canvas.show()

    def _sample_screen_color(self, position: QPointF) -> QColor:
        x, y = self._source_position(position)
        return self._frame.image.pixelColor(
            max(0, min(self._frame.width_px - 1, int(x))),
            max(0, min(self._frame.height_px - 1, int(y))),
        )

    def _request_capture_action(self, name: str) -> None:
        if name != "ocr":
            self._dismiss_ocr_workspace()
        self._request_output(
            lambda snapshot: self.action_requested.emit(name, snapshot),
            include_text_covers=name != "ocr",
        )

    def _request_output(
        self, requested: Callable[[OutputSnapshot], None], *, include_text_covers: bool = True
    ) -> None:
        if self._drag is not None:
            return
        try:
            snapshot = self._session.create_snapshot(include_text_covers=include_text_covers)
        except (CaptureError, MemoryError) as error:
            self.set_output_feedback(
                str(error) if isinstance(error, CaptureError) else "内存不足，无法生成截图。"
            )
            return
        if include_text_covers and self._ocr_workspace is not None:
            workspace = self._ocr_workspace
            if snapshot.selection == workspace._snapshot.selection:
                image = workspace.output_image()
                snapshot = replace(snapshot, rgba_pixels=bytes(image.constBits()))
        requested(snapshot)

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
        if self._smart_selection is not None:
            self._clear_smart_preview()
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
