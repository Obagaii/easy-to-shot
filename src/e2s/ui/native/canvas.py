from collections.abc import Callable
from dataclasses import dataclass, field, replace
from math import copysign

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QImage,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QShortcut,
    QTabletEvent,
)
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QWidget

from e2s.annotation.document import AnnotationDocument
from e2s.annotation.elements import (
    SHAPE_TOOLS,
    Element,
    ImagePatch,
    Point,
    Stroke,
    Text,
    Tool,
)
from e2s.annotation.renderer import (
    annotation_font,
    arrow_control,
    element_bounds,
    hit_test,
    intersecting_elements,
    render_annotations,
)
from e2s.annotation.resize import ElementResize, Endpoint, resize_bounds
from e2s.capture.geometry import ResizeHandle
from e2s.ui.native.annotation_style import AnnotationStylePanel
from e2s.ui.native.annotation_text import AnnotationTextEditor
from e2s.ui.native.annotation_toolbar import AnnotationToolbar
from e2s.ui.native.resize_handles import CORNERS, handle_positions, resize_cursor

_TOOLBAR_GAP_DIP = 8
_ELEMENT_HANDLE_HIT_DIP = 7
_ELEMENT_ACCENT = QColor("#b3a5ff")
_IDLE_TOOLS = (Tool.SELECT, Tool.MOVE)
_DRAG_SHAPES = (*SHAPE_TOOLS, Tool.RECT_HIGHLIGHT, Tool.RECT_ERASER)
_FREEHAND = (Tool.PEN, Tool.HIGHLIGHT, Tool.BRUSH_ERASER)


@dataclass(slots=True)
class Gesture:
    start: Point
    index: int | None = None
    resize: ElementResize | None = None
    draft: Element | None = None
    pen_points: list[Point] = field(default_factory=list)
    pressures: list[float] = field(default_factory=list)
    box: QRectF | None = None
    erased: set[int] = field(default_factory=set)
    group: dict[int, Element] = field(default_factory=dict)
    group_offset: Point = (0, 0)
    eraser_target: int | None = None


class AnnotationCanvas(QWidget):
    cancelled = Signal()
    copy_requested = Signal()
    save_requested = Signal()
    pin_requested = Signal()
    output_requested = Signal(str)

    def __init__(
        self,
        document: AnnotationDocument,
        target: QRectF,
        parent: QWidget,
        *,
        draw_selection_frame: Callable[[QPainter], None] | None = None,
        sample_screen_color: Callable[[QPointF], QColor] | None = None,
        recording: bool = False,
    ) -> None:
        super().__init__(parent)
        self._document = document
        self._target = QRectF(target)
        self._selection_preview: QRectF | None = None
        self._draw_selection_frame = draw_selection_frame
        self._sample_screen_color = sample_screen_color
        self._is_sampling_color = False
        source = document.source
        self._width_px, self._height_px = source.width(), source.height()
        self._recording = recording
        self._controls_visible = True
        self._tool = Tool.SELECT if recording else Tool.MOVE
        self._selection: int | None = None
        self._multi_selection: set[int] = set()
        self._watermark_preview: Text | None = None
        self._color_preview: Element | None = None
        self._opacity_preview: int | None = None
        self._gesture: Gesture | None = None
        self._preview = QImage()
        self._preview_revision = -1
        self._editor: AnnotationTextEditor | None = None
        self._text_origin: Point | None = None
        self._text_index: int | None = None
        self._is_output_pending = False
        self._shortcuts: dict[QKeySequence, tuple[QShortcut, Callable[[], None]]] = {}

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self._toolbar = AnnotationToolbar(self, recording=recording)
        self._toolbar.tool_changed.connect(self._set_tool)
        self._toolbar.action_requested.connect(self._dispatch_action)
        self._styles = AnnotationStylePanel(self)
        self._styles.variant_changed.connect(self._set_tool)
        self._styles.style_changed.connect(self._apply_style)
        self._styles.watermark_preview_changed.connect(self._preview_watermark)
        self._styles.color_preview_changed.connect(self._preview_color)
        self._styles.color_sampling_requested.connect(self._start_color_sampling)
        self._styles.opacity_preview_changed.connect(self._preview_opacity)
        self._styles.selection_requested.connect(self._apply_selection_action)
        self._styles.selection_opacity_requested.connect(self._apply_selection_opacity)
        self._styles.alignment_requested.connect(self._align_selection)
        self._styles.layer_requested.connect(self._move_layers)
        for keys, action in self._toolbar.shortcuts():
            self._register_shortcut(keys, action)
        self._register_shortcut(("Delete",), self._delete_selected)
        self._register_shortcut(("Alt+C",), self._styles.focus_color)
        self._register_shortcut(("[",), lambda: self._styles.step_size(False))
        self._register_shortcut(("]",), lambda: self._styles.step_size(True))
        self._feedback = QLabel(self)
        self._feedback.setWordWrap(True)
        self._feedback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._feedback.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._feedback.setStyleSheet(
            "color: white; background: #243449; border-radius: 4px; padding: 5px;"
        )
        self._feedback.hide()
        self._refresh()

    @property
    def can_adjust_selection(self) -> bool:
        return (
            self._editor is None and self._gesture is None and not self._is_output_pending
            and not self._is_sampling_color
        )

    @property
    def is_sampling_color(self) -> bool:
        return self._is_sampling_color

    def can_move_selection_at(self, position: QPointF) -> bool:
        return self._tool is Tool.MOVE

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
        self._refresh()

    def focus_input(self) -> None:
        (self._editor or self).setFocus()

    def set_recording_editing(self, editing: bool) -> None:
        if not editing:
            self._accept_text()
            self._gesture = None
            self._color_preview = None
            self._opacity_preview = None
            self._selection = None
            self._multi_selection.clear()
            self._styles.close_color_picker()
            if self._is_sampling_color:
                self._finish_color_sampling(None)
        self._controls_visible = editing
        self._refresh()

    @property
    def has_annotations(self) -> bool:
        return bool(self._document.elements)

    def add_image_patch(self, patch: ImagePatch) -> None:
        self._document.add(patch)
        self._set_selected_indexes(set())
        self._refresh()

    def recording_layer(self) -> QImage:
        return self._preview_image()

    def set_feedback(self, message: str) -> None:
        self._feedback.setText(message)
        self._feedback.setVisible(bool(message))
        if message:
            self._place_feedback()

    def set_output_pending(self, is_pending: bool) -> None:
        self._is_output_pending = is_pending
        if is_pending:
            self._styles.close_color_picker()
            if self._is_sampling_color:
                self._finish_color_sampling(None)
        self._toolbar.setEnabled(not is_pending)
        self._styles.setEnabled(not is_pending)
        self._refresh()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._place_controls()

    def paintEvent(self, event: QPaintEvent) -> None:
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            if self._recording and self._controls_visible:
                # Windows passes clicks through pixels with zero alpha in layered windows.
                painter.fillRect(self._target, QColor(0, 0, 0, 1))
            if self._selection_preview is None:
                painter.drawImage(self._target, self._preview_image())
                if self._selection is not None and self._editor is None:
                    self._draw_selection(painter)
                self._draw_marquee(painter)
            else:
                # Keep existing marks aligned to the frozen frame throughout the drag.
                painter.save()
                painter.setClipRect(self._selection_preview)
                painter.drawImage(self._target, self._preview_image())
                painter.restore()
            if self._draw_selection_frame is not None:
                self._draw_selection_frame(painter)
            elif not self._recording:
                painter.setPen(QPen(QColor("#ffffff"), 1))
                painter.drawRect(self._target)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._is_sampling_color and event.button() == Qt.MouseButton.RightButton:
            self._finish_color_sampling(None)
        elif event.button() == Qt.MouseButton.LeftButton:
            self._begin_at(event.position())

    def _begin_at(self, position: QPointF, pressure: float = 1.0) -> None:
        if self._is_output_pending:
            return
        if self._is_sampling_color:
            self._finish_color_sampling(self._sample_color_at(position))
            return
        if self._editor is not None:
            self._accept_text()
            if self._editor is not None:
                return
        self.setFocus()
        self.set_feedback("")
        if not self._target.contains(position):
            self._selection = None
            self._multi_selection.clear()
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
        elif self._tool is Tool.TEXT:
            index = self._hit(point)
            if index is not None and isinstance(self._document.elements[index], Text):
                self._selection = index
            else:
                self._start_text(point)
        elif self._tool is Tool.SELECT:
            index = self._element_at(point)
            self._gesture = Gesture(point)
            if index in self._multi_selection:
                self._gesture.group = {
                    i: self._document.elements[i] for i in self._multi_selection
                }
            else:
                self._selection = index
                self._multi_selection.clear()
                self._gesture.index = index
        elif self._tool not in (Tool.MOVE, Tool.WATERMARK):
            self._selection = None
            self._multi_selection.clear()
            self._gesture = Gesture(point)
            if self._tool is Tool.ERASER:
                self._gesture.eraser_target = self._hit(point)
            self._update_gesture(point, pressure=pressure)
        self._refresh()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._tool in (Tool.SELECT, Tool.TEXT)
            and not self._is_output_pending
            and self._editor is None
            and self._target.contains(event.position())
        ):
            index = self._hit(self._source_point(event.position()))
            if index is not None:
                element = self._document.elements[index]
                if isinstance(element, Text):
                    self._gesture = None
                    self._start_text(element.origin, index, element)
        else:
            super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._gesture is not None:
            self._update_gesture(
                self._source_point(event.position()),
                is_constrained=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier),
            )
            self.update()
        else:
            self.update_pointer_cursor(event.position())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._finish_gesture(event.position(), event.modifiers())

    def tabletEvent(self, event: QTabletEvent) -> None:
        value = self._styles.value
        if self._tool is not Tool.PEN or not isinstance(value, Stroke) or value.style.brush_mode != "pressure":
            event.ignore()
            return
        if event.type() == event.Type.TabletPress:
            self._begin_at(event.position(), event.pressure())
        elif event.type() == event.Type.TabletMove and self._gesture is not None:
            self._update_gesture(self._source_point(event.position()), pressure=event.pressure())
            self.update()
        elif event.type() == event.Type.TabletRelease:
            self._finish_gesture(event.position(), event.modifiers(), event.pressure())
        event.accept()

    def _finish_gesture(
        self, position: QPointF, modifiers: Qt.KeyboardModifier, pressure: float = 1.0
    ) -> None:
        if self._gesture is None:
            return
        self._update_gesture(
            self._source_point(position),
            is_constrained=bool(modifiers & Qt.KeyboardModifier.ShiftModifier),
            pressure=pressure,
        )
        gesture, self._gesture = self._gesture, None
        if self._tool is Tool.ERASER:
            self._document.delete_many(gesture.erased)
        elif gesture.group:
            dx, dy = gesture.group_offset
            self._document.replace_many({
                index: element.translated(dx, dy) for index, element in gesture.group.items()
            })
        elif gesture.box is not None:
            area = QPainterPath()
            area.addRect(gesture.box)
            selection = intersecting_elements(self._document.elements, area)
            self._selection = next(iter(selection)) if len(selection) == 1 else None
            self._multi_selection = selection if len(selection) > 1 else set()
        elif gesture.draft is not None:
            if gesture.index is None:
                self._document.add(gesture.draft)
            else:
                self._document.replace(gesture.index, gesture.draft)
        self.update_pointer_cursor(position)
        self._refresh()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            if self._is_sampling_color:
                self._finish_color_sampling(None)
            elif self._editor is not None:
                self._cancel_text()
            else:
                self._cancel()
            event.accept()
            return
        if self._can_use_shortcuts() and not event.isAutoRepeat():
            binding = self._shortcuts.get(QKeySequence(event.keyCombination()))
            if binding is not None:
                self._activate_shortcut(binding[1])
                event.accept()
                return
        super().keyPressEvent(event)

    def _register_shortcut(self, keys: tuple[str, ...], action: Callable[[], None]) -> None:
        for key in keys:
            sequence = QKeySequence(key)
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.setAutoRepeat(False)
            shortcut.activated.connect(lambda action=action: self._activate_shortcut(action))
            self._shortcuts[sequence] = shortcut, action
            if key == "Enter":
                aliases = [sequence, QKeySequence("Return"), QKeySequence("Num+Enter")]
                shortcut.setKeys(aliases)
                for alias in aliases[1:]:
                    self._shortcuts[alias] = shortcut, action

    def _can_use_shortcuts(self) -> bool:
        return self._controls_visible and self.can_adjust_selection and self._selection_preview is None

    def _activate_shortcut(self, action: Callable[[], None]) -> None:
        focused = QApplication.focusWidget()
        if isinstance(focused, QLineEdit) and self.isAncestorOf(focused):
            return
        if self._can_use_shortcuts():
            action()

    def _cancel(self) -> None:
        if self._gesture is not None:
            self._gesture = None
            self._refresh()
        else:
            self.cancelled.emit()

    def _set_tool(self, tool: Tool) -> None:
        self._styles.close_color_picker()
        if self._is_sampling_color:
            self._finish_color_sampling(None)
        if self._editor is not None:
            self._accept_text()
            if self._editor is not None:
                self._toolbar.set_tool(self._tool)
                return
        self._tool = tool
        self._watermark_preview = None
        self._opacity_preview = None
        self._gesture = None
        self._selection = None
        self._multi_selection.clear()
        self.set_feedback("")
        self._toolbar.set_tool(tool)
        self.setFocus()
        cursor = Qt.CursorShape.ArrowCursor if tool in (*_IDLE_TOOLS, Tool.WATERMARK) else Qt.CursorShape.CrossCursor
        self.setCursor(cursor)
        self._refresh()

    def _update_gesture(
        self, point: Point, *, is_constrained: bool = False, pressure: float = 1.0
    ) -> None:
        gesture = self._gesture
        if gesture is None:
            return
        dx, dy = point[0] - gesture.start[0], point[1] - gesture.start[1]
        if gesture.resize is not None:
            gesture.draft = gesture.resize.update(dx, dy)
        elif gesture.index is not None:
            element = self._document.elements[gesture.index]
            gesture.draft = element.translated(dx, dy) if dx or dy else None
        elif gesture.group:
            gesture.group_offset = dx, dy
        elif self._tool in (Tool.SELECT, Tool.ERASER):
            if abs(dx) >= 1 or abs(dy) >= 1:
                end = QPointF(point[0] if dx else point[0] + 1, point[1] if dy else point[1] + 1)
                gesture.box = QRectF(QPointF(*gesture.start), end).normalized()
            else:
                gesture.box = None
            if self._tool is Tool.ERASER:
                if gesture.box is None:
                    hit = gesture.eraser_target
                    gesture.erased = {hit} if hit is not None else set()
                elif gesture.eraser_target is not None:
                    gesture.erased = {gesture.eraser_target}
                else:
                    area = QPainterPath()
                    area.addRect(gesture.box)
                    gesture.erased = intersecting_elements(self._document.elements, area)
        elif self._tool in _FREEHAND:
            if not gesture.pen_points or gesture.pen_points[-1] != point:
                gesture.pen_points.append(point)
                gesture.pressures.append(max(.08, pressure))
            gesture.draft = self._make_stroke(tuple(gesture.pen_points), tuple(gesture.pressures))
        elif self._tool in _DRAG_SHAPES:
            if is_constrained and self._tool in SHAPE_TOOLS:
                side = min(abs(dx), abs(dy))
                point = (gesture.start[0] + copysign(side, dx), gesture.start[1] + copysign(side, dy))
            gesture.draft = (
                self._make_stroke((gesture.start, point)) if abs(dx) >= 1 and abs(dy) >= 1 else None
            )
        elif self._tool is Tool.ARROW:
            if is_constrained:
                point = (point[0], gesture.start[1]) if abs(dx) >= abs(dy) else (gesture.start[0], point[1])
            gesture.draft = self._make_stroke((gesture.start, point)) if dx or dy else None

    def _make_stroke(
        self, points: tuple[Point, ...], pressures: tuple[float, ...] = ()
    ) -> Stroke:
        preset = self._styles.value
        assert isinstance(preset, Stroke)
        return replace(preset, points=points, pressures=pressures)

    def _source_point(self, position: QPointF) -> Point:
        x_dip, y_dip = position.x(), position.y()
        if self._tool not in (*_IDLE_TOOLS, Tool.TEXT, Tool.WATERMARK):
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
        if isinstance(element, Stroke) and element.tool is Tool.ARROW:
            handles = (
                (Endpoint.START, self._display_point(element.points[0])),
                (Endpoint.END, self._display_point(element.points[-1])),
            )
            if element.style.arrow_type != "straight":
                handles += ((Endpoint.CONTROL, self._display_point(arrow_control(element))),)
            return handles
        return handle_positions(self._display_rect(resize_bounds(element)), CORNERS)

    @staticmethod
    def _element_resize_cursor(handle: ResizeHandle | Endpoint) -> Qt.CursorShape:
        return Qt.CursorShape.SizeAllCursor if isinstance(handle, Endpoint) else resize_cursor(handle)

    def update_pointer_cursor(self, position: QPointF) -> None:
        if self._is_sampling_color:
            self.setCursor(Qt.CursorShape.CrossCursor)
            return
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
            elif self._tool not in (Tool.MOVE, Tool.WATERMARK):
                cursor = Qt.CursorShape.CrossCursor
        self.setCursor(cursor)

    def _preview_image(self) -> QImage:
        gesture = self._gesture
        elements = self._document.elements
        origin_px = self._document.origin_px
        color_preview = self._color_preview
        watermark = self._watermark_preview
        if isinstance(color_preview, Text) and color_preview.tool is Tool.WATERMARK:
            watermark = color_preview if watermark is None else replace(
                color_preview, watermark=watermark.watermark
            )
        if watermark is not None:
            elements = tuple(e for e in elements if e.tool is not Tool.WATERMARK)
            return render_annotations(self._document.source, (*elements, watermark), origin_px)
        if self._text_index is not None:
            index = self._text_index
            return render_annotations(
                self._document.source, elements[:index] + elements[index + 1:], origin_px
            )
        if gesture is not None:
            if gesture.group:
                dx, dy = gesture.group_offset
                moved = tuple(
                    e.translated(dx, dy) if i in gesture.group else e for i, e in enumerate(elements)
                )
                return render_annotations(self._document.source, moved, origin_px)
            if gesture.erased:
                remaining = tuple(e for i, e in enumerate(elements) if i not in gesture.erased)
                return render_annotations(self._document.source, remaining, origin_px)
            if gesture.draft is not None:
                index = gesture.index
                updated = (
                    (*elements, gesture.draft) if index is None
                    else (*elements[:index], gesture.draft, *elements[index + 1:])
                )
                return render_annotations(self._document.source, updated, origin_px)
        if color_preview is not None and self._selection is not None:
            index = self._selection
            return render_annotations(
                self._document.source, (*elements[:index], color_preview, *elements[index + 1:]),
                origin_px,
            )
        if self._opacity_preview is not None:
            indexes = self._selected_indexes()
            return render_annotations(self._document.source, (
                replace(element, opacity=self._opacity_preview) if i in indexes else element
                for i, element in enumerate(elements)
            ), origin_px)
        if self._preview_revision != self._document.revision:
            self._preview = render_annotations(self._document.source, elements, origin_px)
            self._preview_revision = self._document.revision
        return self._preview

    def _draw_marquee(self, painter: QPainter) -> None:
        painter.save()
        painter.setClipRect(self._target)
        painter.setPen(QPen(_ELEMENT_ACCENT, 1, Qt.PenStyle.DashLine))
        if self._gesture is not None and self._gesture.box is not None:
            painter.drawRect(self._display_rect(self._gesture.box))
        offset = self._gesture.group_offset if self._gesture is not None else (0, 0)
        for index in self._multi_selection:
            bounds = element_bounds(self._document.elements[index]).translated(*offset)
            painter.drawRect(self._display_rect(bounds))
        painter.restore()

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
        tool = existing.tool if existing is not None else self._tool
        self._set_tool(tool)
        self._text_origin = point
        self._text_index = index
        self._selection = index
        self._styles.show_style(tool, existing)
        editor = AnnotationTextEditor(self)
        self._editor = editor
        editor.accepted.connect(self._accept_text)
        editor.cancelled.connect(self._cancel_text)
        editor.setPlainText(existing.value if existing is not None else "")
        self._update_text_style()
        self._place_controls()
        editor.show()
        editor.setFocus()
        self._refresh()

    def _update_text_style(self) -> None:
        if self._editor is None:
            return
        scale = self._target.height() / self._height_px
        value = self._color_preview or self._styles.value
        if not isinstance(value, Text):
            return
        self._editor.setFont(annotation_font(max(8, round(value.font_size_px * scale)), value.style))
        color = QColor(value.color)
        option = self._editor.document().defaultTextOption()
        option.setAlignment({
            "left": Qt.AlignmentFlag.AlignLeft, "center": Qt.AlignmentFlag.AlignHCenter,
            "right": Qt.AlignmentFlag.AlignRight,
        }[value.style.alignment])
        self._editor.document().setDefaultTextOption(option)
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
            element = self._styles.update_element(Text(origin, value, "#ff4d4f", 24))
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
        self._place_controls()
        self.setFocus()
        self._refresh()

    def _dispatch_action(self, name: str) -> None:
        if self._editor is not None:
            self._accept_text()
        if not self._can_use_shortcuts():
            return
        action = {
            "undo": self._document.undo, "redo": self._document.redo,
            "copy": self.copy_requested.emit, "save": self.save_requested.emit,
            "pin": self.pin_requested.emit, "cancel": self._cancel,
        }.get(name)
        if action is None:
            self.output_requested.emit(name)
        elif name in ("undo", "redo"):
            action()
            self._selection = None
            self._multi_selection.clear()
            self.set_feedback("")
            self.setFocus()
            self._refresh()
        else:
            action()

    def _delete_selected(self) -> None:
        if not self._can_use_shortcuts():
            return
        indexes = self._multi_selection if self._selection is None else {self._selection}
        self._document.delete_many(indexes)
        self._selection = None
        self._multi_selection.clear()
        self.setFocus()
        self._refresh()

    def _watermark_index(self) -> int | None:
        return next(
            (i for i, element in enumerate(self._document.elements) if element.tool is Tool.WATERMARK),
            None,
        )

    def _selected_indexes(self) -> set[int]:
        return {self._selection} if self._selection is not None else self._multi_selection

    def _set_selected_indexes(self, indexes: set[int]) -> None:
        self._selection = next(iter(indexes)) if len(indexes) == 1 else None
        self._multi_selection = indexes if len(indexes) > 1 else set()

    def _apply_selection_action(self, action: str) -> None:
        if action == "delete":
            self._delete_selected()
        elif self._can_use_shortcuts():
            elements = self._document.elements
            offset_x = 12 * self._width_px / self._target.width()
            offset_y = 12 * self._height_px / self._target.height()
            duplicates = tuple(
                elements[index].translated(offset_x, offset_y)
                for index in sorted(self._selected_indexes())
            )
            self._set_selected_indexes(set(self._document.add_many(duplicates)))
            self.setFocus()
            self._refresh()

    def _apply_selection_opacity(self, opacity: int) -> None:
        if self._can_use_shortcuts():
            self._opacity_preview = None
            elements = self._document.elements
            self._document.replace_many({
                index: replace(elements[index], opacity=opacity) for index in self._multi_selection
            })
            self._refresh()

    def _align_selection(self, action: str) -> None:
        if len(self._multi_selection) < 2 or not self._can_use_shortcuts():
            return
        elements = self._document.elements
        horizontal = action in ("left", "center_x", "right", "distribute_x")
        edges = {}
        for index in self._multi_selection:
            bounds = element_bounds(elements[index])
            edges[index] = (bounds.left(), bounds.right()) if horizontal else (
                bounds.top(), bounds.bottom()
            )
        start = min(low for low, high in edges.values())
        end = max(high for low, high in edges.values())
        offsets = {}
        if action.startswith("distribute"):
            if len(edges) < 3:
                return
            span = sum(high - low for low, high in edges.values())
            gap = (end - start - span) / (len(edges) - 1)
            cursor = start
            for index in sorted(edges, key=lambda index: (sum(edges[index]), index)):
                low, high = edges[index]
                offsets[index] = cursor - low
                cursor += high - low + gap
        else:
            for index, (low, high) in edges.items():
                offsets[index] = {
                    "left": start - low, "top": start - low,
                    "center_x": (start + end - low - high) / 2,
                    "center_y": (start + end - low - high) / 2,
                    "right": end - high, "bottom": end - high,
                }[action]
        self._document.replace_many({
            index: elements[index].translated(offset, 0) if horizontal
            else elements[index].translated(0, offset)
            for index, offset in offsets.items()
        })
        self.setFocus()
        self._refresh()

    def _move_layers(self, action: str) -> None:
        if not self._can_use_shortcuts():
            return
        moved = self._document.move_layers(self._selected_indexes(), action)
        self._set_selected_indexes(moved)
        self.setFocus()
        self._refresh()

    def _apply_style(self, value: Element) -> None:
        self._opacity_preview = None
        self._color_preview = None
        if self._editor is not None:
            self._update_text_style()
            return
        index = self._selection
        if value.tool is Tool.WATERMARK:
            self._watermark_preview = None
            index = self._watermark_index()
            if index is not None:
                self._document.replace(index, value)
            elif isinstance(value, Text) and value.watermark.value:
                self._document.add(value)
        elif index is not None:
            element = self._document.elements[index]
            self._document.replace(index, self._styles.update_element(element))
        self._refresh()

    def _preview_color(self, value: Element | None) -> None:
        self._color_preview = value
        if self._editor is not None:
            self._update_text_style()
        self.update()

    def _start_color_sampling(self) -> None:
        self._is_sampling_color = True
        self.setFocus()
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._refresh()

    def _sample_color_at(self, position: QPointF) -> QColor | None:
        if self._recording and self._sample_screen_color is not None:
            return self._sample_screen_color(position)
        if self._target.contains(position):
            x, y = self._source_point(position)
            left, top = self._document.origin_px
            image = self._preview_image()
            return image.pixelColor(
                max(0, min(image.width() - 1, int(x - left))),
                max(0, min(image.height() - 1, int(y - top))),
            )
        if self._sample_screen_color is not None:
            return self._sample_screen_color(position)
        return None

    def _finish_color_sampling(self, color: QColor | None) -> None:
        self._is_sampling_color = False
        self._styles.finish_color_sampling(color)
        self.focus_input()
        self.update_pointer_cursor(QPointF(self.mapFromGlobal(QCursor.pos())))
        self._refresh()

    def _preview_opacity(self, opacity: int | None) -> None:
        self._opacity_preview = opacity
        self.update()

    def _preview_watermark(self, draft: Text | None) -> None:
        current = self._styles.value
        self._watermark_preview = None if current == draft else draft
        self.update()

    def _refresh(self) -> None:
        can_edit = self._can_use_shortcuts()
        if self._editor is None:
            index = self._watermark_index() if self._tool is Tool.WATERMARK else self._selection
            elements = self._document.elements
            selected = None if index is None else elements[index]
            opacities = tuple(elements[i].opacity for i in self._multi_selection)
            self._styles.show_style(self._tool, selected, selected_opacities=opacities)
        for shortcut, _ in self._shortcuts.values():
            shortcut.setEnabled(can_edit)
        self._toolbar.set_history(
            can_edit and self._document.can_undo, can_edit and self._document.can_redo
        )
        self._place_controls()
        self.update()

    def _place_controls(self) -> None:
        gap = _TOOLBAR_GAP_DIP
        bounds = self.rect().adjusted(gap, gap, -gap, -gap)
        if not bounds.isValid():
            return
        rail = QRect(bounds)
        self._toolbar.setVisible(self._controls_visible and self._selection_preview is None)
        show_styles = self._toolbar.isVisibleTo(self) and self._styles.has_controls
        self._styles.setVisible(show_styles)
        side_x = bounds.x()
        horizontal_room = False
        if show_styles:
            self._styles.fit_to_viewport(bounds.size())
            side_width = self._styles.width()
            right = round(self._target.right()) + 4
            left = round(self._target.left()) - side_width - 4
            use_left = right + side_width > bounds.right() + 1 and left >= bounds.x()
            side_x = left if use_left else min(right, bounds.right() + 1 - side_width)
            horizontal_room = bounds.width() >= side_width + 345
            if horizontal_room:
                if use_left:
                    rail.setLeft(side_x + side_width + 4)
                else:
                    rail.setRight(side_x - 5)
                if rail.width() < 345:
                    rail = QRect(bounds)
                    side_x = bounds.right() + 1 - side_width
                    rail.setRight(side_x - 5)

        self._toolbar.fit_to_width(rail.width())
        toolbar_height = self._toolbar.height()
        toolbar_x = round(self._target.right()) - self._toolbar.width()
        above = round(self._target.top()) - toolbar_height - 4
        below = round(self._target.bottom()) + 4
        top = below + toolbar_height > rail.bottom() + 1 and above >= rail.top()
        toolbar_y = above if top else below
        if show_styles and not horizontal_room:
            toolbar_y = rail.top() if top else rail.bottom() + 1 - toolbar_height
        self._toolbar.position.place(QPoint(toolbar_x, toolbar_y), rail)
        if show_styles:
            side_y = self._toolbar.y() if top else (
                self._toolbar.geometry().bottom() + 1 - self._styles.height()
            )
            if not horizontal_room:
                self._styles.fit_to_viewport(
                    QSize(bounds.width(), max(1, bounds.height() - toolbar_height - 4))
                )
                side_y = bounds.bottom() + 1 - self._styles.height() if top else bounds.top()
            self._styles.position.place(QPoint(side_x, side_y), bounds)
            self._styles.raise_()
        if self._editor is not None and self._text_origin is not None:
            self._place_editor()
        self._styles.place_color_picker()
        if not self._feedback.isHidden():
            self._place_feedback()

    def _place_editor(self) -> None:
        gap = _TOOLBAR_GAP_DIP
        origin = self._display_point(self._text_origin)
        width = min(340, max(1, self.width() - 2 * gap))
        height = min(132, max(1, self.height() - 2 * gap))
        x = max(0, min(round(origin.x()), self.width() - width - gap))
        y = max(0, min(round(origin.y()), self.height() - height - gap))
        if not self._styles.isHidden() and QRectF(x, y, width, height).intersects(
            QRectF(self._styles.geometry())
        ):
            left = self._styles.x() - gap
            right = self._styles.geometry().right() + gap
            if left >= self.width() - right:
                width = min(width, max(1, left))
                x = min(x, left - width)
            else:
                width = min(width, self.width() - right)
                x = right
        if QRectF(x, y, width, height).intersects(QRectF(self._toolbar.geometry())):
            below = self._toolbar.geometry().bottom() + gap
            above = self._toolbar.y() - height - gap
            y = below if below + height + gap <= self.height() else max(0, above)
        self._editor.setGeometry(x, y, width, height)
        self._toolbar.raise_()

    def _place_feedback(self) -> None:
        width = max(1, min(460, self.width() - 2 * _TOOLBAR_GAP_DIP))
        self._feedback.setFixedWidth(width)
        self._feedback.setFixedHeight(self._feedback.heightForWidth(width))
        self._feedback.move((self.width() - width) // 2, _TOOLBAR_GAP_DIP)
        self._feedback.raise_()
