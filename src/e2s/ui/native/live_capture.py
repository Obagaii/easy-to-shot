from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPaintEvent, QPen, QScreen
from PySide6.QtWidgets import QWidget

from e2s.capture.geometry import SelectionRect
from e2s.platform.windows.window_capture import exclude_capture_window


def grab_region(screen: QScreen, selection: SelectionRect) -> QImage:
    image = screen.grabWindow(0).toImage()
    image.setDevicePixelRatio(1)
    region = QRect(selection.left, selection.top, selection.width_px, selection.height_px)
    if not image.rect().contains(region):
        return QImage()
    return image.copy(region)


class LiveSelectionOutline(QWidget):
    def __init__(self, color: str) -> None:
        flags = (
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput
        )
        super().__init__(None, flags)
        self._color = QColor(color)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    def show_around(self, screen: QScreen, region: QRect) -> None:
        self.winId()
        self.windowHandle().setScreen(screen)
        exclude_capture_window(int(self.winId()))
        self.place_around(region)
        self.show()

    def place_around(self, region: QRect) -> None:
        self.setGeometry(region.adjusted(-3, -3, 3, 3))

    def paintEvent(self, event: QPaintEvent) -> None:
        with QPainter(self) as painter:
            painter.setPen(QPen(self._color, 2))
            painter.drawRect(self.rect().adjusted(1, 1, -2, -2))
