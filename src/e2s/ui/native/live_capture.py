import logging

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPaintEvent, QPen, QScreen
from PySide6.QtWidgets import QWidget

from e2s.capture.geometry import SelectionRect
from e2s.platform.windows.window_capture import exclude_capture_window


_LOG = logging.getLogger(__name__)
_camera = None
_camera_screen = ""


def release_live_capture() -> None:
    global _camera, _camera_screen
    camera, _camera = _camera, None
    _camera_screen = ""
    if camera is not None:
        camera.release()


def grab_region(screen: QScreen, selection: SelectionRect) -> QImage:
    """Capture physical screen pixels without disturbing the desktop cursor."""
    global _camera, _camera_screen
    try:
        if _camera is None or _camera_screen != screen.name():
            release_live_capture()
            import dxcam

            factory = dxcam.DXFactory()
            output = next(
                (device_index, output_index)
                for device_index, outputs in enumerate(factory.outputs)
                for output_index, item in enumerate(outputs)
                if item.devicename.casefold() == screen.name().casefold()
            )
            _camera = dxcam.create(device_idx=output[0], output_idx=output[1], output_color="RGB")
            _camera_screen = screen.name()
        frame = _camera.grab(new_frame_only=False)
        if frame is None:
            return QImage()
        height, width, _channels = frame.shape
        region = QRect(selection.left, selection.top, selection.width_px, selection.height_px)
        if not QRect(0, 0, width, height).contains(region):
            return QImage()
        image = QImage(frame.data, width, height, frame.strides[0], QImage.Format.Format_RGB888)
        return image.copy(region)
    except Exception:
        _LOG.exception("Unable to capture live screen")
        release_live_capture()
        return QImage()


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
