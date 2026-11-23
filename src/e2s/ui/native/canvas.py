from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QImage,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPen,
    QResizeEvent,
)
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from e2s.annotation.document import AnnotationDocument
from e2s.annotation.elements import Element, Mosaic, Point, Stroke, Text, Tool
from e2s.annotation.renderer import annotation_font, element_bounds, hit_test, render_annotations
from e2s.annotation.resize import ElementResize, Endpoint, resize_bounds
from e2s.capture.geometry import ResizeHandle
from e2s.ui.native.annotation_text import AnnotationTextEditor
from e2s.ui.native.annotation_toolbar import AnnotationToolbar
from e2s.ui.native.resize_handles import CORNERS, handle_positions, resize_cursor

_TOOLBAR_GAP_DIP = 8
_ELEMENT_HANDLE_HIT_DIP = 7
_ELEMENT_ACCENT = QColor("#b3a5ff")
_ENDPOINT_TOOLS = (Tool.LINE, Tool.ARROW)


@dataclass(slots=True)
class Gesture:
    start: Point
    index: int | None = None
    resize: ElementResize | None = None
    draft: Element | None = None
    pen_points: list[Point] = field(default_factory=list)


class AnnotationCanvas(QWidget):
    cancelled = Signal()
    copy_requested = Signal()
    save_requested = Signal()

    def __init__(
        self,
        document: AnnotationDocument,
        target: QRectF,
        parent: QWidget,
        *,
        draw_selection_frame: Callable[[QPainter], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._document = document
        self._target = QRectF(target)
        self._selection_preview: QRectF | None = None
        self._draw_selection_frame = draw_selection_frame
        source = document.source
        self._width_px, self._height_px = source.width(), source.height()
        self._tool = Tool.SELECT
        self._selection: int | None = None
        self._gesture: Gesture | None = None
        self._preview = QImage()
        self._preview_revision = -1
        self._editor: AnnotationTextEditor | None = None
        self._text_origin: Point | None = None
        self._text_index: int | None = None
        self._is_output_pending = False

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self._toolbar = AnnotationToolbar(self)
        self._toolbar.tool_changed.connect(self._set_tool)
        self._toolbar.undo_requested.connect(self._undo)
        self._toolbar.redo_requested.connect(self._redo)
        self._toolbar.delete_requested.connect(self._delete_selected)
        self._toolbar.copy_requested.connect(self._request_copy)
        self._toolbar.save_requested.connect(self._request_save)
        self._toolbar.text_accepted.connect(self._accept_text)
        self._toolbar.text_cancelled.connect(self._cancel_text)
        self._toolbar.text_style_changed.connect(self._update_text_style)
        self._feedback = QLabel(self)
        self._feedback.setWordWrap(True)
        self._feedback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._feedback.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._feedback.setStyleSheet(
            "color: white; background: #243449; border-radius: 4px; padding: 5px;"
        )
        self._feedback.hide()

    @property
    def can_adjust_selection(self) -> bool:
        return self._editor is None and self._gesture is None and not self._is_output_pending

    def can_move_selection_at(self, position: QPointF) -> bool:
        return self._tool is Tool.SELECT and self._element_at(self._source_point(position)) is None

    def has_resize_handle_at(self, position: QPointF) -> bool:
        return self._resize_handle_at(position) is not None

    def set_selection_target(self, target: QRectF) -> None:
        self._target = QRectF(target)
        source = self._document.source
        self._width_px, self._height_px = source.width(), source.height()
        self._preview_revision = -1
        self._place_controls()
        self.update()

    def preview_selection(self, target: QRectF | None) -> None:
        self._selection_preview = target
        self._toolbar.setVisible(target is None)
        self.update()

    def focus_input(self) -> None:
        (self._editor or self).setFocus()

    def set_feedback(self, message: str) -> None:
        self._feedback.setText(message)
        self._feedback.setVisible(bool(message))
        if message:
            self._place_feedback()

    def set_output_pending(self, is_pending: bool) -> None:
        self._is_output_pending = is_pending
        self._toolbar.setEnabled(not is_pending)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._place_controls()

    def paintEvent(self, event: QPaintEvent) -> None:
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            if self._selection_preview is None:
                painter.drawImage(self._target, self._preview_image())
                if self._selection is not None and self._editor is None:
                    self._draw_selection(painter)
            else:
                # Keep existing marks aligned to the frozen frame throughout the drag.
                painter.save()
                painter.setClipRect(self._selection_preview)
                painter.drawImage(self._target, self._preview_image())
                painter.restore()
            if self._draw_selection_frame is not None:
                self._draw_selection_frame(painter)
            else:
                painter.setPen(QPen(QColor("#ffffff"), 1))
                painter.drawRect(self._target)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() != Qt.MouseButton.LeftButton
            or self._is_output_pending
            or self._editor is not None
        ):
            return
        self.setFocus()
        self.set_feedback("")
        position = event.position()
        if not self._target.contains(position):
            self._selection = None
            self._refresh()
            return

        point = self._source_point(position)
        handle = self._resize_handle_at(position)
        if handle is not None and self._selection is not None:
            element = self._document.elements[self._selection]
            self._gesture = Gesture(
                point, self._selection, resize=ElementResize(element, handle, resize_bounds(element))
            )
            self.setCursor(self._element_resize_cursor(handle))
            return

        if self._tool is Tool.TEXT:
            index = self._hit(point)
            if index is not None and isinstance(self._document.elements[index], Text):
                self._selection = index
                self._refresh()
            else:
                self._start_text(point)
            return

        index = self._element_at(point) if self._tool is Tool.SELECT else None
        self._selection = index
        if self._tool is not Tool.SELECT or index is not None:
            self._gesture = Gesture(point, index)
            self._update_gesture(point)
        self._refresh()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._tool in (Tool.SELECT, Tool.TEXT)
            and not self._is_output_pending
            and self._editor is None
            and self._target.contains(event.position())
        ):
            point = self._source_point(event.position())
            index = self._hit(point)
            if index is not None:
                element = self._document.elements[index]
                if isinstance(element, Text):
                    self._gesture = None
                    self._start_text(element.origin, index, element)
        else:
            super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._gesture is not None:
            self._update_gesture(self._source_point(event.position()))
            self.update()
        else:
            self.update_pointer_cursor(event.position())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._gesture is None:
            return
        self._update_gesture(self._source_point(event.position()))
        gesture, self._gesture = self._gesture, None
        if gesture.draft is not None:
            if gesture.index is None:
                self._document.add(gesture.draft)
            else:
                self._document.replace(gesture.index, gesture.draft)
        self.update_pointer_cursor(event.position())
        self._refresh()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._selection_preview is not None:
            super().keyPressEvent(event)
        elif event.key() == Qt.Key.Key_Escape:
            if self._editor is not None:
                self._cancel_text()
            elif self._gesture is not None:
                self._gesture = None
                self._refresh()
            else:
                self.cancelled.emit()
        elif self._editor is not None or self._is_output_pending or self._gesture is not None:
            super().keyPressEvent(event)
        elif event.matches(QKeySequence.StandardKey.Undo):
            self._undo()
        elif (
            event.matches(QKeySequence.StandardKey.Redo)
            or (
                event.key() == Qt.Key.Key_Z
                and event.modifiers()
                == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
            )
        ):
            self._redo()
        elif event.matches(QKeySequence.StandardKey.Copy):
            self._request_copy()
        elif (
            event.matches(QKeySequence.StandardKey.Save)
            or event.matches(QKeySequence.StandardKey.SaveAs)
        ):
            self._request_save()
        elif event.key() == Qt.Key.Key_Delete:
            self._delete_selected()
        else:
            super().keyPressEvent(event)

    def _set_tool(self, tool: Tool) -> None:
        self._tool = tool
        self._selection = None
        self._toolbar.set_tool(tool)
        self._place_controls()
        self.setFocus()
        self.setCursor(
            Qt.CursorShape.ArrowCursor if tool is Tool.SELECT else Qt.CursorShape.CrossCursor
        )
        self._refresh()

    def _update_gesture(self, point: Point) -> None:
        gesture = self._gesture
        if gesture is None:
            return
        dx, dy = point[0] - gesture.start[0], point[1] - gesture.start[1]
        if gesture.resize is not None:
            gesture.draft = gesture.resize.update(dx, dy)
        elif gesture.index is not None:
            element = self._document.elements[gesture.index]
            gesture.draft = element.translated(dx, dy) if dx or dy else None
        elif self._tool is Tool.MOSAIC:
            if abs(dx) >= 1 and abs(dy) >= 1:
                gesture.draft = Mosaic(gesture.start, point, self._toolbar.block_size_px)
            else:
                gesture.draft = None
        elif self._tool is Tool.PEN:
            if not gesture.pen_points or gesture.pen_points[-1] != point:
                gesture.pen_points.append(point)
            gesture.draft = self._make_stroke(tuple(gesture.pen_points))
        elif self._tool in (Tool.RECTANGLE, Tool.ELLIPSE):
            gesture.draft = (
                self._make_stroke((gesture.start, point)) if abs(dx) >= 1 and abs(dy) >= 1 else None
            )
        else:
            gesture.draft = self._make_stroke((gesture.start, point)) if dx or dy else None

    def _make_stroke(self, points: tuple[Point, ...]) -> Stroke:
        return Stroke(
            self._tool, points, self._toolbar.color, self._toolbar.width_px, self._toolbar.is_filled
        )

    def _source_point(self, position: QPointF) -> Point:
        x_dip, y_dip = position.x(), position.y()
        if self._tool not in (Tool.SELECT, Tool.TEXT):
            # A fullscreen crop must also reach the last source pixel at fractional DPI.
            if x_dip >= self.width() - 1 and self._target.right() >= self.width() - 1:
                x_dip = self.width()
            if y_dip >= self.height() - 1 and self._target.bottom() >= self.height() - 1:
                y_dip = self.height()
        x = (x_dip - self._target.left()) / self._target.width() * self._width_px
        y = (y_dip - self._target.top()) / self._target.height() * self._height_px
        left, top = self._document.origin_px
        return left + max(0, min(self._width_px, x)), top + max(0, min(self._height_px, y))

    def _display_point(self, point: Point) -> QPointF:
        x, y = point
        left, top = self._document.origin_px
        return QPointF(
            self._target.left() + (x - left) / self._width_px * self._target.width(),
            self._target.top() + (y - top) / self._height_px * self._target.height(),
        )

    def _hit(self, point: Point) -> int | None:
        tolerance_px = 4 * max(
            self._width_px / self._target.width(), self._height_px / self._target.height()
        )
        return hit_test(self._document.elements, point, tolerance_px)

    def _element_at(self, point: Point) -> int | None:
        index = self._hit(point)
        if index is not None or self._selection is None:
            return index
        element = self._document.elements[self._selection]
        if resize_bounds(element).contains(QPointF(*point)):
            return self._selection
        return None

    def _resize_handle_at(self, position: QPointF) -> ResizeHandle | Endpoint | None:
        if self._selection is None or not self._target.contains(position) or self._editor is not None:
            return None
        element = self._document.elements[self._selection]
        handles = self._element_handles(element)
        nearest, distance = None, _ELEMENT_HANDLE_HIT_DIP ** 2
        for handle, point in handles:
            delta = point - position
            squared = QPointF.dotProduct(delta, delta)
            if squared <= distance:
                nearest, distance = handle, squared
        return nearest

    def _element_handles(
        self, element: Element
    ) -> tuple[tuple[ResizeHandle | Endpoint, QPointF], ...]:
        if isinstance(element, Stroke) and element.tool in _ENDPOINT_TOOLS:
            return (
                (Endpoint.START, self._display_point(element.points[0])),
                (Endpoint.END, self._display_point(element.points[-1])),
            )
        return handle_positions(self._display_rect(resize_bounds(element)), CORNERS)

    @staticmethod
    def _element_resize_cursor(handle: ResizeHandle | Endpoint) -> Qt.CursorShape:
        return Qt.CursorShape.SizeAllCursor if isinstance(handle, Endpoint) else resize_cursor(handle)

    def update_pointer_cursor(self, position: QPointF) -> None:
        cursor = Qt.CursorShape.ArrowCursor
        if self._target.contains(position):
            handle = self._resize_handle_at(position)
            if handle is not None:
                cursor = self._element_resize_cursor(handle)
            elif self._tool is Tool.SELECT:
                if self._element_at(self._source_point(position)) is not None:
                    cursor = Qt.CursorShape.SizeAllCursor
            elif self._tool is Tool.TEXT:
                cursor = Qt.CursorShape.IBeamCursor
            else:
                cursor = Qt.CursorShape.CrossCursor
        self.setCursor(cursor)

    def _preview_image(self) -> QImage:
        gesture = self._gesture
        elements = self._document.elements
        origin_px = self._document.origin_px
        if self._text_index is not None:
            index = self._text_index
            return render_annotations(
                self._document.source, elements[:index] + elements[index + 1:], origin_px
            )
        if gesture is not None and gesture.draft is not None and gesture.index is not None:
            index = gesture.index
            return render_annotations(
                self._document.source,
                elements[:index] + (gesture.draft,) + elements[index + 1:],
                origin_px,
            )
        if self._preview_revision != self._document.revision:
            self._preview = render_annotations(self._document.source, elements, origin_px)
            self._preview_revision = self._document.revision
        if gesture is not None and gesture.draft is not None:
            return render_annotations(self._preview, (gesture.draft,), origin_px)
        return self._preview

    def _draw_selection(self, painter: QPainter) -> None:
        element = self._document.elements[self._selection]
        if self._gesture is not None and self._gesture.draft is not None:
            element = self._gesture.draft
        rect = self._display_rect(element_bounds(element)).adjusted(-3, -3, 3, 3)
        painter.save()
        painter.setClipRect(self._target)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#18132c"), 2))
        painter.drawRoundedRect(rect, 2, 2)
        painter.setPen(QPen(_ELEMENT_ACCENT, 1, Qt.PenStyle.DashLine))
        painter.drawRoundedRect(rect, 2, 2)
        painter.setPen(QPen(QColor("#241a4b"), 1.5))
        painter.setBrush(_ELEMENT_ACCENT)
        for _, point in self._element_handles(element):
            painter.drawEllipse(point, 4, 4)
        painter.restore()

    def _display_rect(self, bounds: QRectF) -> QRectF:
        return QRectF(
            self._display_point((bounds.left(), bounds.top())),
            self._display_point((bounds.right(), bounds.bottom())),
        )

    def _start_text(
        self, point: Point, index: int | None = None, existing: Text | None = None
    ) -> None:
        self._set_tool(Tool.TEXT)
        self._text_origin = point
        self._text_index = index
        self._selection = index
        if existing is not None:
            self._toolbar.set_text_style(existing.color, existing.font_size_px)
        editor = AnnotationTextEditor(self)
        self._editor = editor
        editor.accepted.connect(self._accept_text)
        editor.cancelled.connect(self._cancel_text)
        editor.setPlainText(existing.value if existing is not None else "")
        self._toolbar.set_text_editing(True)
        self._update_text_style()
        self._place_controls()
        editor.show()
        editor.setFocus()
        self._refresh()

    def _update_text_style(self) -> None:
        if self._editor is None:
            return
        scale = self._target.height() / self._height_px
        self._editor.setFont(annotation_font(max(8, round(self._toolbar.font_size_px * scale))))
        color = QColor(self._toolbar.color)
        background = "#242b35" if color.lightness() > 150 else "#ffffff"
        self._editor.setStyleSheet(
            f"QPlainTextEdit {{color: {color.name()}; background: {background};"
            " border: 2px solid #72a4ed;}"
        )

    def _accept_text(self) -> None:
        editor = self._editor
        origin = self._text_origin
        if editor is None or origin is None:
            return
        if editor.has_preedit:
            QApplication.inputMethod().commit()
            if editor.has_preedit:
                editor.setFocus()
                return
        value = editor.toPlainText()
        if value.strip():
            element = Text(origin, value, self._toolbar.color, self._toolbar.font_size_px)
            if self._text_index is None:
                self._selection = self._document.add(element)
            else:
                self._document.replace(self._text_index, element)
        elif self._text_index is not None:
            self._document.delete(self._text_index)
            self._selection = None
        self._close_editor()

    def _cancel_text(self) -> None:
        if self._editor is not None:
            self._close_editor()

    def _close_editor(self) -> None:
        editor, self._editor = self._editor, None
        self._text_origin = None
        self._text_index = None
        editor.hide()
        editor.deleteLater()
        self._toolbar.set_text_editing(False)
        self._place_controls()
        self.setFocus()
        self._refresh()

    def _undo(self) -> None:
        self._document.undo()
        self._selection = None
        self.setFocus()
        self._refresh()

    def _redo(self) -> None:
        self._document.redo()
        self._selection = None
        self.setFocus()
        self._refresh()

    def _delete_selected(self) -> None:
        if self._selection is None or not self.can_adjust_selection:
            return
        self._document.delete(self._selection)
        self._selection = None
        self.setFocus()
        self._refresh()

    def _request_copy(self) -> None:
        if self._gesture is None:
            self.copy_requested.emit()

    def _request_save(self) -> None:
        if self._gesture is None:
            self.save_requested.emit()

    def _refresh(self) -> None:
        can_edit = self._editor is None
        self._toolbar.set_element_selected(can_edit and self._selection is not None)
        self._toolbar.set_history(
            can_edit and self._document.can_undo, can_edit and self._document.can_redo
        )
        self.update()

    def _place_controls(self) -> None:
        self._toolbar.adjustSize()
        gap = _TOOLBAR_GAP_DIP
        toolbar_width, toolbar_height = self._toolbar.width(), self._toolbar.height()
        x = round(self._target.right()) - toolbar_width
        top = round(self._target.top()) - toolbar_height - gap
        bottom = round(self._target.bottom()) + gap
        y = bottom if bottom + toolbar_height + gap <= self.height() or top < gap else top
        self._toolbar.move(
            max(0, min(x, self.width() - toolbar_width - gap)),
            max(0, min(y, self.height() - toolbar_height - gap)),
        )

        if self._editor is not None and self._text_origin is not None:
            origin = self._display_point(self._text_origin)
            width = min(340, max(1, self.width() - 2 * gap))
            height = min(132, max(1, self.height() - 2 * gap))
            x = max(0, min(round(origin.x()), self.width() - width - gap))
            y = max(0, min(round(origin.y()), self.height() - height - gap))
            editor_rect = QRectF(x, y, width, height)
            if editor_rect.intersects(QRectF(self._toolbar.geometry())):
                below = self._toolbar.y() + toolbar_height + gap
                above = self._toolbar.y() - height - gap
                y = below if below + height + gap <= self.height() else max(0, above)
            self._editor.setGeometry(x, y, width, height)
            self._toolbar.raise_()
        if not self._feedback.isHidden():
            self._place_feedback()

    def _place_feedback(self) -> None:
        width = max(1, min(460, self.width() - 2 * _TOOLBAR_GAP_DIP))
        self._feedback.setFixedWidth(width)
        self._feedback.setFixedHeight(self._feedback.heightForWidth(width))
        self._feedback.move((self.width() - width) // 2, _TOOLBAR_GAP_DIP)
        self._feedback.raise_()
