from PySide6.QtWidgets import QDialog, QLabel, QWidget
from qfluentwidgets import Dialog, LineEdit, MessageBox, MessageBoxBase


def _dialog(parent: QWidget | None, title: str, text: str):
    window = parent.window() if parent is not None else None
    if window is not None and window.isVisible() and window.width() >= 400 and window.height() >= 250:
        dialog = MessageBox(title, text, window)
    else:
        dialog = Dialog(title, text, window)
    dialog.yesButton.setText("确定")
    dialog.cancelButton.setText("取消")
    return dialog


def show_warning(parent: QWidget | None, title: str, text: str) -> None:
    dialog = _dialog(parent, title, text)
    dialog.hideCancelButton()
    dialog.exec()


def confirm_action(parent: QWidget | None, title: str, text: str) -> bool:
    dialog = _dialog(parent, title, text)
    dialog.cancelButton.setFocus()
    return dialog.exec() == QDialog.DialogCode.Accepted


class TextPrompt(MessageBoxBase):
    def __init__(self, parent: QWidget, title: str, label: str) -> None:
        super().__init__(parent.window())
        self.widget.setMinimumWidth(360)
        self.viewLayout.addWidget(QLabel(title))
        self.viewLayout.addWidget(QLabel(label))
        self.input = LineEdit()
        self.viewLayout.addWidget(self.input)
        self.yesButton.setText("确定")
        self.cancelButton.setText("取消")
        self.input.setFocus()


def prompt_text(parent: QWidget, title: str, label: str) -> tuple[str, bool]:
    dialog = TextPrompt(parent, title, label)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    return dialog.input.text(), accepted
