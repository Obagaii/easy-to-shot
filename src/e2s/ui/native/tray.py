from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def create_app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 32, size / 32)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#164e63"))
        painter.drawRoundedRect(QRectF(1, 1, 30, 30), 7, 7)
        pen = QPen(QColor('#ffffff'), 2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(9, 12), QPointF(9, 8))
        painter.drawLine(QPointF(9, 8), QPointF(13, 8))
        painter.drawLine(QPointF(19, 24), QPointF(23, 24))
        painter.drawLine(QPointF(23, 24), QPointF(23, 20))
        painter.drawLine(QPointF(12, 20), QPointF(20, 12))
        painter.end()
        icon.addPixmap(pixmap)
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
        self._menu.addAction("打开工作台", self.workbench_requested.emit)
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
