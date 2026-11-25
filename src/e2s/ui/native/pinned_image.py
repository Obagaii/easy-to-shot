from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QContextMenuEvent,
    QEnterEvent,
    QGuiApplication,
    QImage,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QScreen,
    QWheelEvent,
)
from PySide6.QtWidgets import QMenu, QWidget

from e2s.capture.geometry import ResizeHandle
from e2s.ui.native.resize_handles import draw_resize_frame, frame_handle_positions, resize_cursor

_MIN_VISIBLE_DIP = 24
_MAX_SCALE = 4.0
_WHEEL_STEP = 1.2
_HANDLE_HIT_DIP = 15
_FRAME_INSET_DIP = 1.5


@dataclass(frozen=True, slots=True)
class _ResizeDrag:
    handle: ResizeHandle
    pointer_origin: QPointF
    geometry: QRect
    scale: float
    min_scale: float
    bounds: QRect


class PinnedImage(QWidget):
    """Show an owned copy-on-write view of the original image on the GUI thread."""

    copy_requested = Signal()
    save_requested = Signal()
    closed = Signal()

    def __init__(self, image: QImage) -> None:
        if image.isNull():
            raise ValueError("A pinned image must have pixels")
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._image = QImage(image)
        self._scale = 1.0
        self._drag_offset: QPointF | None = None
        self._resize_drag: _ResizeDrag | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setWindowTitle("截图贴图")
        self.setToolTip("拖动图片移动 · 拖动手柄或滚轮缩放 · 右键打开菜单")
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        self._menu = QMenu(self)
        copy_action = self._menu.addAction("复制", self.copy_requested.emit)
        copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        self._save_action = self._menu.addAction("另存", self.save_requested.emit)
        self._save_action.setShortcuts(
            [QKeySequence.StandardKey.Save, QKeySequence.StandardKey.SaveAs]
        )
        self._menu.addSeparator()
        close_action = self._menu.addAction("关闭", self.close)
        close_action.setShortcuts(
            [QKeySequence(Qt.Key.Key_Escape), QKeySequence.StandardKey.Close]
        )

    def show_at(self, screen: QScreen, origin_dip: QPoint) -> None:
        """Place the preview at the capture location in Qt desktop coordinates."""
        self.winId()
        self.windowHandle().setScreen(screen)
        self._place(origin_dip, 1.0 / screen.devicePixelRatio(), screen.availableGeometry())
        self.show()

    def set_save_pending(self, is_pending: bool) -> None:
        self._save_action.setEnabled(not is_pending)

    def restore_visibility(self, available_areas: Sequence[QRect]) -> None:
        """Move the preview to an available screen if it no longer has a usable drag area."""
        geometry = self.geometry()
        for area in available_areas:
            visible = geometry.intersected(area)
            if (
                visible.width() >= min(geometry.width(), _MIN_VISIBLE_DIP)
                and visible.height() >= min(geometry.height(), _MIN_VISIBLE_DIP)
            ):
                return
        if available_areas:
            area = available_areas[0]
            size = self._size_at_scale(min(self._scale, self._max_scale(area)))
            origin = area.center() - QPoint(size.width() // 2, size.height() // 2)
            self._place(origin, self._scale, area)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor("#172b3d"))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(self.rect(), self._image)
        active = self._resize_drag.handle if self._resize_drag is not None else None
        draw_resize_frame(painter, self._frame_rect(), QRectF(self.rect()), active)

    def enterEvent(self, event: QEnterEvent) -> None:
        if not self._is_dragging:
            self._update_cursor(event.position())
        super().enterEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        self._resize_drag = None
        self._drag_offset = None
        position = event.globalPosition()
        handle = self._handle_at(event.position())
        screen = self._screen_at(position.toPoint()) if handle is not None else None
        if handle is not None and screen is not None:
            geometry = self.geometry()
            self._resize_drag = _ResizeDrag(
                handle, position, geometry, self._scale, self._min_scale(screen),
                screen.availableGeometry().united(geometry),
            )
            self.setCursor(resize_cursor(handle))
        else:
            self._drag_offset = position - QPointF(self.pos())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.update()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._is_dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self._update_drag(event.globalPosition())
            event.accept()
        else:
            if self._resize_drag is not None:
                self.update()
            self._resize_drag = None
            self._drag_offset = None
            self._update_cursor(event.position())
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._is_dragging:
            self._update_drag(event.globalPosition())
            self._drag_offset = None
            self._resize_drag = None
            self.restore_visibility(
                [screen.availableGeometry() for screen in QGuiApplication.screens()]
            )
            self._update_cursor(self.mapFromGlobal(event.globalPosition()))
            self.update()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if not delta or self._is_dragging:
            return
        screen = self._screen_at(event.globalPosition().toPoint())
        if screen is None:
            return
        bounds = screen.availableGeometry()
        scale = self._scale * _WHEEL_STEP ** (delta / 120)
        scale = min(max(scale, self._min_scale(screen)), self._max_scale(bounds))
        size = self._size_at_scale(scale)
        position = event.position()
        offset = QPointF(
            position.x() * size.width() / self.width(),
            position.y() * size.height() / self.height(),
        )
        self._place((event.globalPosition() - offset).toPoint(), scale, bounds)
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_requested.emit()
        elif (
            event.matches(QKeySequence.StandardKey.Save)
            or event.matches(QKeySequence.StandardKey.SaveAs)
        ):
            self._save_action.trigger()
        elif event.key() == Qt.Key.Key_Escape or event.matches(QKeySequence.StandardKey.Close):
            self.close()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        self._menu.popup(event.globalPos())
        event.accept()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._menu.hide()
        self.closed.emit()
        super().closeEvent(event)

    @property
    def _is_dragging(self) -> bool:
        return self._drag_offset is not None or self._resize_drag is not None

    @staticmethod
    def _screen_at(position: QPoint) -> QScreen | None:
        # QWidget.screen() can parent the PySide screen wrapper to this disposable window.
        return QGuiApplication.screenAt(position) or QGuiApplication.primaryScreen()

    def _frame_rect(self) -> QRectF:
        inset = min(_FRAME_INSET_DIP, self.width() / 4, self.height() / 4)
        return QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)

    def _handle_at(self, position: QPointF) -> ResizeHandle | None:
        def distance_squared(item: tuple[ResizeHandle, QPointF]) -> float:
            delta = position - item[1]
            return QPointF.dotProduct(delta, delta)

        grips = frame_handle_positions(self._frame_rect(), QRectF(self.rect()))
        nearest = min(grips, key=distance_squared)
        hit_radius = min(_HANDLE_HIT_DIP, self.width() / 3, self.height() / 3)
        return nearest[0] if distance_squared(nearest) <= hit_radius ** 2 else None

    def _update_cursor(self, position: QPointF) -> None:
        handle = self._handle_at(position)
        cursor = resize_cursor(handle) if handle is not None else Qt.CursorShape.OpenHandCursor
        self.setCursor(cursor)

    def _update_drag(self, position: QPointF) -> None:
        if self._resize_drag is not None:
            self._resize_from_drag(self._resize_drag, position)
        elif self._drag_offset is not None:
            self.move((position - self._drag_offset).toPoint())

    def _resize_from_drag(self, drag: _ResizeDrag, position: QPointF) -> None:
        horizontal, vertical = drag.handle.value
        original = drag.geometry
        direction = QPointF(horizontal * original.width(), vertical * original.height())
        delta = position - drag.pointer_origin
        factor = 1 + QPointF.dotProduct(delta, direction) / QPointF.dotProduct(direction, direction)

        # Side handles anchor the opposite edge's midpoint. Corners anchor the opposite corner.
        anchor_x = (1 - horizontal) / 2
        anchor_y = (1 - vertical) / 2
        anchor = QPointF(
            original.x() + anchor_x * original.width(),
            original.y() + anchor_y * original.height(),
        )
        bounds = drag.bounds
        width_px, height_px = self._image.width(), self._image.height()
        anchor_limits = (
            (anchor.x() - bounds.left(), anchor_x * width_px),
            (bounds.right() + 1 - anchor.x(), (1 - anchor_x) * width_px),
            (anchor.y() - bounds.top(), anchor_y * height_px),
            (bounds.bottom() + 1 - anchor.y(), (1 - anchor_y) * height_px),
        )
        max_scale = min(distance / pixels for distance, pixels in anchor_limits if pixels)
        # Retain the initial geometry when its rounded dimensions already meet the bound.
        max_scale = min(_MAX_SCALE, max(max_scale, drag.scale))
        scale = min(max(drag.scale * factor, drag.min_scale), max_scale)
        size = self._size_at_scale(scale)
        origin = anchor - QPointF(anchor_x * size.width(), anchor_y * size.height())
        self._place(origin.toPoint(), scale, bounds)

    def _min_scale(self, screen: QScreen) -> float:
        return min(
            1.0 / screen.devicePixelRatio(),
            _MIN_VISIBLE_DIP / max(self._image.width(), self._image.height()),
        )

    def _max_scale(self, bounds: QRect) -> float:
        return min(
            _MAX_SCALE,
            bounds.width() / self._image.width(),
            bounds.height() / self._image.height(),
        )

    def _size_at_scale(self, scale: float) -> QSize:
        return QSize(
            max(1, round(self._image.width() * scale)),
            max(1, round(self._image.height() * scale)),
        )

    def _place(self, origin: QPoint, scale: float, bounds: QRect) -> None:
        self._scale = min(scale, self._max_scale(bounds))
        size = self._size_at_scale(self._scale)
        x = max(bounds.left(), min(origin.x(), bounds.right() - size.width() + 1))
        y = max(bounds.top(), min(origin.y(), bounds.bottom() - size.height() + 1))
        self.setGeometry(QRect(QPoint(x, y), size))
