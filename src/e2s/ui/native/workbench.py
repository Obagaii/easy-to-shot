from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QKeySequence
from PySide6.QtWidgets import (
    QFormLayout,
    QKeySequenceEdit,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from e2s.platform.windows.hotkeys import DEFAULT_HOTKEY, HotkeyError, HotkeyState

_HOTKEY_MESSAGES = {
    HotkeyError.INVALID: "请输入包含 Ctrl、Shift 或 Alt 的单个组合键。",
    HotkeyError.RESERVED: "该组合键由系统保留，请换一个。",
    HotkeyError.CONFLICT: "该组合键已被占用，请换一个。",
    HotkeyError.UNAVAILABLE: "系统无法注册该组合键，仍可从托盘截图。",
}


class Workbench(QMainWindow):
    capture_requested = Signal()
    hotkey_requested = Signal(QKeySequence)

    def __init__(self, icon: QIcon) -> None:
        super().__init__()
        self.setWindowTitle("Easy to Shot")
        self.setWindowIcon(icon)
        self.resize(520, 300)

        self._shortcut = QKeySequenceEdit(QKeySequence(DEFAULT_HOTKEY))
        self._shortcut.setMaximumSequenceLength(1)
        self._shortcut.setClearButtonEnabled(True)
        self._hotkey_status = QLabel()
        self._hotkey_feedback = QLabel()
        self._hotkey_feedback.setWordWrap(True)
        apply_button = QPushButton("应用热键")
        apply_button.clicked.connect(
            lambda: self.hotkey_requested.emit(self._shortcut.keySequence())
        )

        content = QWidget(self)
        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(24, 24, 24, 24)
        hotkey_form = QFormLayout()
        hotkey_form.addRow("截图热键", self._shortcut)
        hotkey_form.addRow(self._hotkey_status)
        hotkey_form.addRow(self._hotkey_feedback)
        hotkey_form.addRow(apply_button)
        self._layout.addLayout(hotkey_form)
        self._layout.addStretch()
        self.setCentralWidget(content)

    def activate(self) -> None:
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def show_hotkey_settings(self) -> None:
        self.activate()
        self._shortcut.setFocus()

    def show_hotkey_state(self, state: HotkeyState) -> None:
        status = f"当前热键：{state.active}" if state.active else "当前未注册截图热键"
        self._hotkey_status.setText(status)
        self._hotkey_feedback.setText(_HOTKEY_MESSAGES.get(state.error, ""))
