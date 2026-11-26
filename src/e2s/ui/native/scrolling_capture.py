from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image
from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QImage,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QScreen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
)

from qfluentwidgets import SpinBox

from e2s.capture.scrolling import ScrollResult, ScrollStitcher
from e2s.platform.windows.displays import wait_for_desktop_composition
from e2s.platform.windows.window_capture import exclude_capture_window
from e2s.ui.native.annotation_controls import CAPTURE_CONTROLS_STYLE, describe_control
from e2s.ui.native.annotation_toolbar import Command, describe_button
from e2s.ui.native.live_capture import LiveSelectionOutline
from e2s.ui.native.toolbar_icons import toolbar_icon

_FLAGS = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
_GAP = 8
_CROSS = 128
_ACCENT = QColor("#1677ff")


@dataclass(slots=True)
class ThumbnailStrip:
    start: int
    length: int
    image: QImage


class ScrollThumbnail(QAbstractScrollArea):
    """Show only visible strips of the stitched image and allow trimming either end."""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(_FLAGS)
        self.setObjectName("scrollThumbnail")
        self.setAccessibleName("长截图实时预览")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setStyleSheet("""
            QAbstractScrollArea { background: #ffffff; border: 1px solid #d9d9d9; }
            QScrollBar:vertical { background: #f5f5f5; width: 8px; margin: 0; }
            QScrollBar:horizontal { background: #f5f5f5; height: 8px; margin: 0; }
            QScrollBar::handle { background: #bfbfbf; border-radius: 3px; min-height: 12px; }
            QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
        """)
        self._strips: deque[ThumbnailStrip] = deque()
        self._horizontal = False
        self._drag_trim: str | None = None
        self._trim_start = self._trim_end = 0
        self._first = self._last = 0
        self._source_cross = 1
        self._cross = _CROSS
        self._scroll_limit = 1
        self._area = QRect()
        self._region = QRect()
        self._available = QRect()

    @property
    def source_extent(self) -> int:
        return self._last - self._first

    @property
    def trim(self) -> tuple[int, int]:
        return self._trim_start, self.source_extent - self._trim_end

    @property
    def _bar(self):
        return self.horizontalScrollBar() if self._horizontal else self.verticalScrollBar()

    @property
    def _scale(self) -> float:
        return self._cross / self._source_cross

    def configure(self, area: QRect, region: QRect, available: QRect, horizontal: bool) -> None:
        self.hide()
        self._horizontal = horizontal
        self._strips.clear()
        self._first = self._last = self._trim_start = self._trim_end = 0
        self._drag_trim = None
        self.horizontalScrollBar().setValue(0)
        self.verticalScrollBar().setValue(0)
        self.reanchor(area, region, available)
        as_needed = Qt.ScrollBarPolicy.ScrollBarAsNeeded
        off = Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        self.setHorizontalScrollBarPolicy(as_needed if horizontal else off)
        self.setVerticalScrollBarPolicy(off if horizontal else as_needed)

    def reanchor(self, area: QRect, region: QRect, available: QRect) -> None:
        self._area, self._region, self._available = area, region, available
        if self._horizontal:
            above = region.top() - available.top() - _GAP
            below = available.bottom() - region.bottom() - _GAP
            max_cross = max(above, below)
            self._scroll_limit = min(region.width(), available.width())
        else:
            left = region.left() - available.left() - _GAP
            right = available.right() - region.right() - _GAP
            max_cross = max(left, right)
            self._scroll_limit = min(region.height(), available.height())
        self._cross = min(_CROSS, max_cross - 10) if max_cross >= 82 else _CROSS
        if self.source_extent:
            self._place()

    def append(self, tile: Image.Image, source_size: tuple[int, int], is_prepend: bool) -> None:
        width, height = tile.size
        length = width if self._horizontal else height
        self._source_cross = source_size[1 if self._horizontal else 0]
        if is_prepend:
            self._first -= length
            start = self._first
        else:
            start = self._last
            self._last += length
        scaled_length = max(1, round(length * self._scale))
        scaled_size = (scaled_length, self._cross) if self._horizontal else (self._cross, scaled_length)
        image = tile.resize(scaled_size, Image.Resampling.BILINEAR)
        buffer = image.tobytes()
        preview = QImage(
            buffer, *scaled_size, scaled_size[0] * 4, QImage.Format.Format_RGBA8888
        ).copy()
        strip = ThumbnailStrip(start, length, preview)
        if is_prepend:
            self._strips.appendleft(strip)
        else:
            self._strips.append(strip)
        self._place()
        self._bar.setValue(0 if is_prepend else self._bar.maximum())
        if self.isHidden():
            self.show()
        self.viewport().update()

    def _place(self) -> None:
        extent = max(1, min(self._scroll_limit - 2, round(self.source_extent * self._scale)))
        needs_bar = extent < round(self.source_extent * self._scale)
        cross = self._cross + 2 + (8 if needs_bar else 0)
        if self._horizontal:
            width, height = extent + 2, cross
            x = self._region.x()
            y = self._region.top() - height - _GAP
            if y < self._available.top():
                y = self._region.bottom() + 1 + _GAP
        else:
            width, height = cross, extent + 2
            x = self._region.right() + 1 + _GAP
            if x + width > self._available.right() + 1:
                x = self._region.left() - width - _GAP
            y = self._region.y()
        x = max(self._area.left(), min(x, self._area.right() + 1 - width))
        y = max(self._area.top(), min(y, self._area.bottom() + 1 - height))
        self.setGeometry(x, y, width, height)
        self._bar.setRange(0, max(0, round(self.source_extent * self._scale) - extent))
        self._bar.setPageStep(extent)
        self._bar.setSingleStep(24)

    def paintEvent(self, event) -> None:
        with QPainter(self.viewport()) as painter:
            painter.fillRect(event.rect(), QColor("#f5f5f5"))
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            offset = self._bar.value()
            visible_length = self.viewport().width() if self._horizontal else self.viewport().height()
            for strip in self._strips:
                start = (strip.start - self._first) * self._scale - offset
                length = strip.length * self._scale
                if start > visible_length:
                    break
                if start + length >= 0:
                    rect = self._orient(start, length)
                    painter.drawImage(rect, strip.image)
            self._paint_trim(painter, offset, visible_length)

    def _orient(self, start: float, span: float) -> QRectF:
        if self._horizontal:
            return QRectF(start, 0, span, self._cross)
        return QRectF(0, start, self._cross, span)

    def _paint_trim(self, painter: QPainter, offset: int, visible: int) -> None:
        first, last = [origin * self._scale - offset for origin in self.trim]
        tint = QColor(0, 0, 0, 110)
        painter.fillRect(self._orient(0, max(0, first)), tint)
        painter.fillRect(self._orient(last, max(0, visible - last)), tint)
        for edge in (first, last):
            if -1 <= edge <= visible + 1:
                painter.fillRect(self._orient(max(0, min(visible - 3, edge - 1)), 3), _ACCENT)

    def _pointer(self, event) -> float:
        return event.position().x() if self._horizontal else event.position().y()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._strips:
            return
        position = self._pointer(event) + self._bar.value()
        first, last = (end * self._scale for end in self.trim)
        if abs(position - first) <= 7:
            self._drag_trim = "start"
        elif abs(position - last) <= 7:
            self._drag_trim = "end"

    def mouseMoveEvent(self, event) -> None:
        pointer = self._pointer(event) + self._bar.value()
        if self._drag_trim is None:
            near_edge = any(abs(pointer - end * self._scale) <= 7 for end in self.trim)
            if near_edge:
                self.viewport().setCursor(Qt.SizeHorCursor if self._horizontal else Qt.SizeVerCursor)
            else:
                self.viewport().unsetCursor()
            return
        position = round(pointer / self._scale)
        first, last = self.trim
        if self._drag_trim == "start":
            self._trim_start = max(0, min(position, last - 1))
        else:
            self._trim_end = max(0, min(self.source_extent - position, self.source_extent - first - 1))
        self.viewport().update()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_trim = None

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y() or event.angleDelta().x()
        pixels = event.pixelDelta().y() or event.pixelDelta().x()
        steps = pixels or round(delta * 36 / 120)
        if steps:
            self._bar.setValue(self._bar.value() - steps)
            event.accept()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        self.viewport().update()


class ScrollingCapture(QDialog):
    captured = Signal(str, object)
    failed = Signal(str)
    _frame_processed = Signal(object, object)

    def __init__(
        self, grab: Callable[[QPoint], QImage], scroll_step: Callable[[bool, QPoint], bool]
    ) -> None:
        super().__init__(None, _FLAGS)
        self.setWindowTitle("滚动截图")
        self.setObjectName("scrollingToolbar")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._grab = grab
        self._scroll_step = scroll_step
        self._can_overlay = False
        self._toolbar_excluded = False
        self._thumbnail = ScrollThumbnail()
        self._outline = LiveSelectionOutline("#1677ff")
        self._horizontal = False
        self._stitcher = ScrollStitcher()
        self._is_pending = False
        self._ready = False
        self._is_full = False
        self._processing = False
        self._is_closed = False
        self._requested_export: str | None = None
        self._frame_processed.connect(self._show_frame, Qt.ConnectionType.QueuedConnection)
        self._timer = QTimer(self, interval=120)
        self._timer.timeout.connect(self._collect)
        self._auto_timer = QTimer(self, interval=200)
        self._auto_timer.timeout.connect(self._advance)
        self._screen: QScreen | None = None
        self._region = QRect()
        self._region_origin = QPoint()
        self._drag: tuple[QPoint, QRect] | None = None
        self._toolbar_drag_anchor: QPoint | None = None
        self._toolbar_moved = False
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(CAPTURE_CONTROLS_STYLE + """
            QLabel { color: #595959; background: transparent; }
            QToolButton[scrollToggle="true"]:checked { background: #bae0ff; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        surface = QFrame(self)
        surface.setProperty("toolbarSurface", True)
        layout.addWidget(surface)
        self._buttons = QHBoxLayout(surface)
        self._buttons.setContentsMargins(7, 5, 7, 5)
        self._buttons.setSpacing(4)
        self._actions = self._buttons
        self._drag_handle = QToolButton(self)
        self._drag_handle.setIcon(toolbar_icon("drag_handle"))
        self._drag_handle.setIconSize(QSize(18, 22))
        self._drag_handle.setFixedSize(17, 38)
        describe_control(self._drag_handle, "拖动滚动截图工具栏")
        self._drag_handle.setCursor(Qt.CursorShape.SizeAllCursor)
        self._drag_handle.installEventFilter(self)
        self._buttons.addWidget(self._drag_handle)
        self._status = QLabel(self)
        self._status.setFixedWidth(160)
        self._status.setWordWrap(True)
        self._set_status("请在原窗口滚动")
        self._buttons.addWidget(self._status)

        self._auto = self._add_button("auto_scroll", "自动滚动", ("Alt+A",), self._toggle_auto)
        self._auto.setCheckable(True)
        self._auto.setProperty("scrollToggle", True)
        interval_icon = QLabel(self)
        interval_icon.setPixmap(toolbar_icon("interval").pixmap(16, 16))
        self._buttons.addWidget(interval_icon)
        interval = SpinBox(self)
        self._interval = interval
        interval.setRange(128, 1000)
        interval.setSingleStep(25)
        interval.setValue(self._auto_timer.interval())
        interval.setSymbolVisible(False)
        interval.setFixedSize(90, 32)
        interval.setSuffix(" ms")
        interval.setToolTip("自动滚动间隔（滚轮调整）")
        interval.valueChanged.connect(self._auto_timer.setInterval)
        self._buttons.addWidget(interval)
        self._buttons.addSpacing(4)
        self._vertical = self._add_button(
            "scroll_vertical", "垂直滚动", ("Alt+V",), lambda: self._change_direction(False)
        )
        self._sideways = self._add_button(
            "scroll_horizontal", "水平滚动", ("Alt+H",), lambda: self._change_direction(True)
        )
        for button in (self._vertical, self._sideways):
            button.setCheckable(True)
            button.setProperty("scrollToggle", True)
        self._vertical.setChecked(True)
        self._buttons.addSpacing(4)
        self._move_buttons = (
            self._add_button(
                "move_horizontal", "横向移动选区（按住拖动）", ("Ctrl+Left", "Ctrl+Right"),
                lambda: None,
            ),
            self._add_button(
                "move_vertical", "纵向移动选区（按住拖动）", ("Ctrl+Up", "Ctrl+Down"),
                lambda: None,
            ),
        )
        for button, cursor in zip(self._move_buttons, (Qt.SizeHorCursor, Qt.SizeVerCursor)):
            button.setCursor(cursor)
            button.installEventFilter(self)
        for key, dx, dy in (
            ("Ctrl+Left", -1, 0), ("Ctrl+Right", 1, 0),
            ("Ctrl+Up", 0, -1), ("Ctrl+Down", 0, 1),
        ):
            QShortcut(QKeySequence(key), self, lambda x=dx, y=dy: self._nudge(x, y))
        self._results = [
            self._add_button(
                icon, label, keys, lambda name=icon: self._export(name), layout=self._actions
            )
            for icon, label, keys in (
                ("pin", "固定到屏幕", ("Ctrl+F",)),
                ("save", "保存为文件", ("Ctrl+S",)),
                ("copy", "复制到剪贴板", ("Ctrl+C", "Return", "Enter")),
            )
        ]
        self._results[-1].setObjectName("scrollCopy")
        self._add_button(
            "cancel", "取消滚动截图", ("Esc", "L"), self.reject, layout=self._actions
        )
        self._update_enabled()

    def _set_status(self, message: str) -> None:
        self._status.setText(message)
        self._status.setToolTip(message)

    def _add_button(
        self, icon: str, label: str, keys: tuple[str, ...], action: Callable[[], None], *,
        layout: QHBoxLayout | None = None,
    ) -> QToolButton:
        button = QToolButton(self)
        button.setIcon(toolbar_icon(icon))
        button.setFixedSize(38, 38)
        button.setIconSize(QSize(22, 22))
        describe_button(button, Command(label, keys))
        button.clicked.connect(lambda _checked=False: action())
        if not icon.startswith("move_"):
            shortcut = QShortcut(self)
            shortcut.setKeys([QKeySequence(key) for key in keys])
            shortcut.setAutoRepeat(False)
            shortcut.activated.connect(button.click)
        (layout or self._buttons).addWidget(button)
        return button

    def present(self, screen: QScreen, region: QRect) -> bool:
        self._screen, self._region = screen, region
        self._region_origin = region.topLeft()
        self.adjustSize()
        self.winId()
        self.windowHandle().setScreen(screen)
        self._thumbnail.winId()
        self._thumbnail.windowHandle().setScreen(screen)
        self._can_overlay = exclude_capture_window(int(self._thumbnail.winId()))
        toolbar_excluded = exclude_capture_window(int(self.winId()))

        if not self._place_toolbar(region, toolbar_excluded):
            return False
        self._toolbar_excluded = toolbar_excluded
        self._outline.show_around(screen, region)
        self.show()
        self._configure_thumbnail()
        return True

    @property
    def selection_origin(self) -> QPoint:
        return self._region.topLeft()

    def _place_toolbar(self, region: QRect, toolbar_excluded: bool) -> bool:
        if self._screen is None:
            return False
        area = self._screen.availableGeometry()
        width, height = self.width(), self.height()
        x = max(area.left(), min(region.right() + 1 - width, area.right() + 1 - width))
        y = region.bottom() + _GAP
        if y + height > area.bottom():
            y = region.top() - height - _GAP
        fallback = QRect(x, max(area.top(), min(y, area.bottom() - height + 1)), width, height)
        slots = (
            QRect(x, y, width, height),
            QRect(region.right() + 1 + _GAP, region.top(), width, height),
            QRect(region.left() - width - _GAP, region.top(), width, height),
        )
        control = next(
            (slot for slot in slots if area.contains(slot) and not region.intersects(slot)),
            fallback,
        )
        if control.intersects(region) and not toolbar_excluded:
            return False
        self.setGeometry(control)
        return True

    def start(self) -> None:
        if not self.isVisible():
            return
        wait_for_desktop_composition()
        self._timer.start()
        self._collect()

    def _configure_thumbnail(self, *, reset: bool = True) -> None:
        if self._screen is None:
            return
        area = self._screen.availableGeometry().adjusted(_GAP, _GAP, -_GAP, -_GAP)
        available = QRect(area)
        toolbar = self.geometry()
        if toolbar.top() >= self._region.bottom() and toolbar.top() < area.bottom():
            available.setBottom(toolbar.top() - _GAP)
        elif toolbar.bottom() <= self._region.top() and toolbar.bottom() > area.top():
            available.setTop(toolbar.bottom() + _GAP)
        if reset:
            self._thumbnail.configure(area, self._region, available, self._horizontal)
        else:
            self._thumbnail.reanchor(area, self._region, available)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._drag_handle and isinstance(event, QMouseEvent):
            if (event.type() == QEvent.Type.MouseButtonPress
                    and event.button() == Qt.MouseButton.LeftButton):
                self._toolbar_drag_anchor = event.globalPosition().toPoint() - self.pos()
                self._drag_handle.grabMouse()
                return True
            if self._toolbar_drag_anchor is not None and event.type() == QEvent.Type.MouseMove:
                point = event.globalPosition().toPoint() - self._toolbar_drag_anchor
                screen = QApplication.screenAt(event.globalPosition().toPoint()) or self._screen
                if screen is not None:
                    area = screen.availableGeometry()
                    point.setX(max(area.left(), min(point.x(), area.right() + 1 - self.width())))
                    point.setY(max(area.top(), min(point.y(), area.bottom() + 1 - self.height())))
                if self._toolbar_excluded or not QRect(point, self.size()).intersects(self._region):
                    self.move(point)
                    self._toolbar_moved = True
                    self._configure_thumbnail(reset=False)
                return True
            if (self._toolbar_drag_anchor is not None
                    and event.type() == QEvent.Type.MouseButtonRelease):
                self._toolbar_drag_anchor = None
                self._drag_handle.releaseMouse()
                return True
        if watched is self._drag_handle:
            if event.type() == QEvent.Type.UngrabMouse:
                self._toolbar_drag_anchor = None
            return super().eventFilter(watched, event)
        if watched not in self._move_buttons:
            return super().eventFilter(watched, event)
        if (
            isinstance(event, QMouseEvent)
            and event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._drag = event.globalPosition().toPoint(), QRect(self._region)
            self._timer.stop()
            self._auto_timer.stop()
            watched.setDown(True)
            watched.grabMouse()
            return True
        if self._drag is None:
            return super().eventFilter(watched, event)
        if isinstance(event, QMouseEvent) and event.type() == QEvent.Type.MouseMove:
            start, region = self._drag
            delta = event.globalPosition().toPoint() - start
            self._move_region(region, delta.x(), delta.y())
            return True
        if event.type() in (QEvent.Type.MouseButtonRelease, QEvent.Type.UngrabMouse):
            self._drag = None
            watched.setDown(False)
            watched.releaseMouse()
            self._position_controls()
            if not self._is_full:
                self._timer.start()
            if self._auto.isChecked():
                self._auto_timer.start()
            return True
        return super().eventFilter(watched, event)

    def _nudge(self, dx: int, dy: int) -> None:
        if self._ready and not self._is_pending:
            self._move_region(self._region, dx, dy)
            self._position_controls()

    def _position_controls(self) -> None:
        if not self._toolbar_moved:
            self._place_toolbar(self._region, self._toolbar_excluded)
        self._configure_thumbnail(reset=False)

    def _move_region(self, start: QRect, dx: int, dy: int) -> None:
        if self._screen is None:
            return
        bounds = self._screen.geometry()
        region = QRect(start)
        if self._horizontal:
            x = max(bounds.left(), min(region.x() + dx, bounds.right() + 1 - region.width()))
            region.moveLeft(x)
        else:
            y = max(bounds.top(), min(region.y() + dy, bounds.bottom() + 1 - region.height()))
            region.moveTop(y)
        if region.intersects(self.geometry()) and not self._toolbar_excluded:
            return
        self._region = region
        self._outline.place_around(region)
        self._configure_thumbnail(reset=False)


    def _change_direction(self, horizontal: bool) -> None:
        self._vertical.setChecked(not horizontal)
        self._sideways.setChecked(horizontal)
        if self._horizontal == horizontal:
            return
        self._horizontal = horizontal
        self._stitcher = ScrollStitcher(horizontal=horizontal)
        self._ready = False
        self._is_full = False
        self._configure_thumbnail()
        self._update_enabled()
        wait_for_desktop_composition()
        self._collect()
        if not self._is_pending and self.isVisible():
            self._timer.start()

    def _toggle_auto(self) -> None:
        if self._auto.isChecked():
            self._advance()
            if self._auto.isChecked():
                self._auto_timer.start()
        else:
            self._auto_timer.stop()

    def _advance(self) -> None:
        offset = self.selection_origin - self._region_origin
        if not self._scroll_step(self._horizontal, offset):
            self._auto.setChecked(False)
            self._auto_timer.stop()
            self._set_status("无法自动滚动，请在原窗口手动滚动。")

    def _collect(self) -> None:
        if self._processing or self._is_pending or self._is_closed or self._drag is not None:
            return
        offset = self.selection_origin - self._region_origin
        image = self._grab(offset).convertToFormat(QImage.Format.Format_RGBA8888)
        if image.isNull():
            self.failed.emit("无法读取滚动区域，请重新框选。")
            return
        stitcher = self._stitcher
        self._processing = True
        QThreadPool.globalInstance().start(lambda: self._stitch_frame(stitcher, image))

    def _stitch_frame(self, stitcher: ScrollStitcher, image: QImage) -> None:
        try:
            size = image.width(), image.height()
            view = Image.frombytes("RGBA", size, image.constBits())
            result = stitcher.add(view)
        except MemoryError:
            result = None
        try:
            self._frame_processed.emit(stitcher, result)
        except RuntimeError:
            # A closed panel can be deleted while the worker owns its final frame.
            pass

    def _show_frame(self, stitcher: ScrollStitcher, result: ScrollResult | None) -> None:
        self._processing = False
        if self._is_closed:
            return
        if self._stitcher is not stitcher:
            self._collect()
            return
        if result is None:
            self.failed.emit("内存不足，无法继续拼接长截图。")
            return
        width, height = stitcher.size
        if result is ScrollResult.ADDED:
            part = stitcher.added_part
            assert part is not None
            self._thumbnail.append(part, (width, height), stitcher.is_prepend)
            if not self._can_overlay and self._thumbnail.geometry().intersects(self._region):
                self.failed.emit("当前选区没有空间显示长截图预览，请缩小选区。")
                return
            self._ready = True
            self._set_status(f"{width} × {height} px")
        elif result is ScrollResult.NO_OVERLAP:
            self._set_status("未找到重叠内容，请退回少许再慢慢滚动。")
        elif result is ScrollResult.FULL:
            self._set_status(f"{width} × {height} px · 已达到尺寸上限")
            self._is_full = True
            self._stop()
        self._update_enabled()
        if self._requested_export is not None:
            name, self._requested_export = self._requested_export, None
            self._write_result(name)

    def _export(self, name: str) -> None:
        if not self._ready or self._is_pending:
            return
        self._requested_export = name
        if not self._processing and not self._is_full:
            self._collect()
        if self._is_closed:
            return
        self.set_output_feedback("", is_pending=True)
        if not self._processing:
            self._requested_export = None
            self._write_result(name)

    def _write_result(self, name: str) -> None:
        try:
            image = self._stitcher.image()
            first, last = self._thumbnail.trim
            if (first, last) != (0, self._thumbnail.source_extent):
                if self._horizontal:
                    image = image.crop((first, 0, last, image.height))
                else:
                    image = image.crop((0, first, image.width, last))
        except MemoryError:
            self.set_output_feedback("内存不足，无法生成长截图。")
        else:
            self.captured.emit(name, image)


    def set_output_feedback(self, message: str, *, is_pending: bool = False) -> None:
        self._is_pending = is_pending
        if is_pending:
            self._stop()
        elif not self._is_full and self.isVisible():
            self._timer.start()
            # A modal file dialog can cover the selection until the next composition.
            wait_for_desktop_composition()
        if message:
            self._set_status(message)
        self._update_enabled()

    def _update_enabled(self) -> None:
        for button in self._results:
            button.setEnabled(self._ready and not self._is_pending)
        for button in (self._vertical, self._sideways):
            button.setEnabled(not self._is_pending)
        self._auto.setEnabled(self._ready and not self._is_pending and not self._is_full)
        for button, horizontal in zip(self._move_buttons, (True, False)):
            button.setEnabled(self._ready and not self._is_pending and horizontal == self._horizontal)

    def _stop(self) -> None:
        self._timer.stop()
        self._auto_timer.stop()
        self._auto.setChecked(False)

    def done(self, result: int) -> None:
        if self._is_closed:
            return
        self._is_closed = True
        self._stop()
        self._thumbnail.close()
        self._outline.close()
        self._thumbnail.deleteLater()
        self._outline.deleteLater()
        super().done(result)
