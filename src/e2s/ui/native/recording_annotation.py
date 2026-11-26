from collections.abc import Callable

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QScreen
from PySide6.QtWidgets import QWidget

from e2s.annotation.document import AnnotationDocument
from e2s.platform.windows.window_capture import exclude_capture_window
from e2s.ui.native.canvas import AnnotationCanvas

_OVERLAY_FLAGS = (
    Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
)


class RecordingAnnotation(QWidget):
    """Display the live annotation layer and composite it separately from the controls."""

    editing_cancelled = Signal()

    def __init__(
        self, screen: QScreen, region: QRect, size: QSize, grab: Callable[[], QImage]
    ) -> None:
        super().__init__(None, _OVERLAY_FLAGS)
        self._screen = screen
        self._grab = grab
        self._region = region.translated(-screen.geometry().topLeft())
        self._editing = False
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        source = QImage(size, QImage.Format.Format_RGBA8888)
        if source.isNull():
            raise MemoryError("Could not allocate the recording annotation layer")
        source.fill(Qt.GlobalColor.transparent)
        self._canvas = AnnotationCanvas(
            AnnotationDocument(source), QRectF(self._region), self,
            recording=True, sample_screen_color=self._sample_color,
        )
        self._canvas.cancelled.connect(self.editing_cancelled)

    def set_editing(self, editing: bool) -> bool:
        self._canvas.set_recording_editing(editing)
        if not editing and not self.isVisible():
            return True
        self.hide()
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, not editing)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, not editing)
        self.winId()
        self.windowHandle().setScreen(self._screen)
        self.setGeometry(self._screen.geometry())
        self._canvas.setGeometry(self.rect())
        self.show()
        if not exclude_capture_window(int(self.winId())):
            self.hide()
            self._editing = False
            return False
        self._editing = editing
        if editing:
            self.activateWindow()
            self._canvas.focus_input()
        return True

    def capture_frame(self, frame: QImage) -> QImage:
        if frame.isNull():
            return frame
        if self._editing or self._canvas.has_annotations:
            with QPainter(frame) as painter:
                painter.drawImage(0, 0, self._canvas.recording_layer())
        return frame

    def _sample_color(self, position: QPointF) -> QColor | None:
        region = QRectF(self._region)
        if not region.contains(position):
            return None
        image = self._grab()
        if image.isNull():
            return None
        x = int((position.x() - region.left()) * image.width() / region.width())
        y = int((position.y() - region.top()) * image.height() / region.height())
        return image.pixelColor(min(image.width() - 1, x), min(image.height() - 1, y))
