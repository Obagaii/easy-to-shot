import ctypes
from ctypes import wintypes

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from e2s.capture.geometry import SelectionRect


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                ("work", wintypes.RECT), ("flags", wintypes.DWORD),
                ("device", wintypes.WCHAR * 32)]


def screen_for_native_point(app, x: int, y: int):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.MonitorFromPoint.argtypes = (wintypes.POINT, wintypes.DWORD)
    user32.MonitorFromPoint.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_MonitorInfo))
    monitor = user32.MonitorFromPoint(wintypes.POINT(x, y), 2)
    info = _MonitorInfo()
    info.size = ctypes.sizeof(info)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None, None
    screen = next((item for item in app.screens() if item.name().lower() == info.device.lower()), None)
    rect = info.monitor
    return screen, (rect.left, rect.top, rect.right, rect.bottom)


def native_selection(start, end, bounds, width: int, height: int) -> SelectionRect | None:
    left, top, right, bottom = bounds
    if right <= left or bottom <= top:
        return None
    def convert(point):
        return (max(0, min(width, round((point[0] - left) * width / (right - left)))),
                max(0, min(height, round((point[1] - top) * height / (bottom - top)))))
    x1, y1 = convert(start)
    x2, y2 = convert(end)
    selection = SelectionRect(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
    return selection if selection.fits(width, height) else None


class QuickCaptureOverlay(QWidget):
    def __init__(self, screen, frame, bounds, start) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput)
        self._frame = frame
        self._bounds = bounds
        self._start = start
        self._end = start
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setGeometry(screen.geometry())

    def update_end(self, x: int, y: int) -> None:
        self._end = (x, y)
        self.update()

    def selection(self):
        return native_selection(self._start, self._end, self._bounds,
                                self._frame.width_px, self._frame.height_px)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.drawImage(self.rect(), self._frame.image)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        selection = self.selection()
        if selection is None:
            return
        source = QRect(selection.left, selection.top, selection.width_px, selection.height_px)
        rect = QRect(round(selection.left * self.width() / self._frame.width_px),
                     round(selection.top * self.height() / self._frame.height_px),
                     round(selection.width_px * self.width() / self._frame.width_px),
                     round(selection.height_px * self.height() / self._frame.height_px))
        painter.drawImage(rect, self._frame.image, source)
        painter.setPen(QPen(QColor("#00bfff"), 2))
        painter.drawRect(rect)
