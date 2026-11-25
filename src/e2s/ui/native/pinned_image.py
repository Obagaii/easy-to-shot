from collections.abc import Sequence

from PySide6.QtCore import QPoint, QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QContextMenuEvent,
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

_MIN_VISIBLE_DIP = 24
_MAX_SCALE = 4.0
_WHEEL_STEP = 1.2


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
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setWindowTitle("截图贴图")
        self.setToolTip("拖动移动 · 滚轮缩放 · 右键打开菜单")
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

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition() - QPointF(self.pos())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move((event.globalPosition() - self._drag_offset).toPoint())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_offset is not None:
            self.move((event.globalPosition() - self._drag_offset).toPoint())
            self._drag_offset = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.restore_visibility(
                [screen.availableGeometry() for screen in QGuiApplication.screens()]
            )
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if not delta or self._drag_offset is not None:
            return
        # QWidget.screen() can parent the PySide screen wrapper to this disposable window.
        screen = (
            QGuiApplication.screenAt(event.globalPosition().toPoint())
            or QGuiApplication.primaryScreen()
        )
        if screen is None:
            return
        bounds = screen.availableGeometry()
        scale = self._scale * _WHEEL_STEP ** (delta / 120)
        min_scale = min(
            1.0 / screen.devicePixelRatio(),
            _MIN_VISIBLE_DIP / max(self._image.width(), self._image.height()),
        )
        scale = min(max(scale, min_scale), self._max_scale(bounds))
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
