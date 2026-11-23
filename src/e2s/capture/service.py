from dataclasses import dataclass

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage, QScreen

from e2s.platform.windows.displays import wait_for_desktop_composition


class CaptureError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CaptureFrame:
    screen_id: str
    geometry_dip: QRect
    _image: QImage

    @property
    def image(self) -> QImage:
        """Return a copy-on-write view of the frozen source pixels."""
        return QImage(self._image)

    @property
    def width_px(self) -> int:
        return self._image.width()

    @property
    def height_px(self) -> int:
        return self._image.height()


def capture_frame(screen: QScreen) -> CaptureFrame:
    """Grab the selected screen on the GUI thread before showing any overlay."""
    geometry_dip = screen.geometry()
    wait_for_desktop_composition()
    image = screen.grabWindow(0).toImage()
    if image.isNull() or geometry_dip.isEmpty():
        raise CaptureError("无法抓取当前屏幕，请重试。")

    # Keep the captured physical size even when Qt rounds the logical bounds.
    image.setDevicePixelRatio(1)
    return CaptureFrame(screen.name(), geometry_dip, image)
