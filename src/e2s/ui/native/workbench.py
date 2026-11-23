from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMainWindow, QWidget


class Workbench(QMainWindow):
    capture_requested = Signal()
    settings_requested = Signal()

    def __init__(self, icon: QIcon) -> None:
        super().__init__()
        self.setWindowTitle("Easy to Shot")
        self.setWindowIcon(icon)
        self.resize(520, 300)
        self.setCentralWidget(QWidget(self))

    def activate(self) -> None:
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()
