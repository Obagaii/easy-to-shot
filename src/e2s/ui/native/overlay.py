from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QCloseEvent, QKeyEvent, QPaintEvent, QPainter, QScreen
from PySide6.QtWidgets import QWidget

from e2s.capture.service import CaptureFrame


class CaptureOverlay(QWidget):
    cancelled = Signal()

    def __init__(self, frame: CaptureFrame) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._frame = frame
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
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
        painter.drawImage(QRectF(self.rect()), self._frame.image)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.cancelled.emit()
        event.accept()
