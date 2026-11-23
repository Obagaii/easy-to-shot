from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QInputMethodEvent, QKeyEvent
from PySide6.QtWidgets import QPlainTextEdit


class AnnotationTextEditor(QPlainTextEdit):
    accepted = Signal()
    cancelled = Signal()

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.has_preedit = False
        self.setAccessibleName("截图标注文字")
        self.setPlaceholderText("输入文字，Ctrl+Enter 完成")
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

    def inputMethodEvent(self, event: QInputMethodEvent) -> None:
        self.has_preedit = bool(event.preeditString())
        super().inputMethodEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        is_cancel = event.key() == Qt.Key.Key_Escape
        is_accept = (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        )
        if is_cancel or is_accept:
            if self.has_preedit:
                super().keyPressEvent(event)
            elif is_cancel:
                self.cancelled.emit()
            else:
                self.accepted.emit()
            event.accept()
        else:
            super().keyPressEvent(event)
