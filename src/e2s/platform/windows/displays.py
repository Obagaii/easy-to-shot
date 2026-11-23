import ctypes
import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QScreen


def screen_at_cursor(app: QGuiApplication) -> QScreen | None:
    """Resolve the cursor in Qt's per-screen logical desktop coordinates."""
    return app.screenAt(QCursor.pos())


def wait_for_desktop_composition() -> None:
    if sys.platform == "win32":
        ctypes.windll.dwmapi.DwmFlush()


class DisplayWatcher(QObject):
    changed = Signal()

    def __init__(self, app: QGuiApplication, parent: QObject) -> None:
        super().__init__(parent)
        for screen in app.screens():
            self._watch_screen(screen)
        app.screenAdded.connect(self._on_screen_added)
        app.screenRemoved.connect(self._on_screen_removed)

    def _watch_screen(self, screen: QScreen) -> None:
        screen.geometryChanged.connect(self.changed)
        screen.logicalDotsPerInchChanged.connect(self.changed)
        screen.physicalDotsPerInchChanged.connect(self.changed)
        screen.virtualGeometryChanged.connect(self.changed)

    def _on_screen_added(self, screen: QScreen) -> None:
        self._watch_screen(screen)
        self.changed.emit()

    def _on_screen_removed(self, screen: QScreen) -> None:
        self.changed.emit()
