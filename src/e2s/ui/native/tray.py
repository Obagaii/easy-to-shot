from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


_ICON_PATH = Path(__file__).parent / "assets" / "e2s.png"


def create_app_icon() -> QIcon:
    source = QPixmap(str(_ICON_PATH))
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(source.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    return icon


class Tray(QSystemTrayIcon):
    workbench_requested = Signal()
    capture_requested = Signal()
    settings_requested = Signal()
    quit_requested = Signal()

    def __init__(self, icon: QIcon) -> None:
        super().__init__(icon)
        self.setToolTip("Easy to Shot")
        self._menu = QMenu()
        self.setContextMenu(self._menu)
        self._menu.addAction('新建截图', self.capture_requested.emit)
        self._menu.addAction("打开主菜单", self.workbench_requested.emit)
        self._menu.addAction("截图热键", self.settings_requested.emit)
        self._menu.addSeparator()
        self._menu.addAction("退出", self.quit_requested.emit)
        self.activated.connect(self._on_activated)

    def dismiss_menu(self) -> None:
        self._menu.hide()

    def notify(self, message: str) -> None:
        self.showMessage('Easy to Shot', message)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == self.ActivationReason.DoubleClick:
            self.workbench_requested.emit()

