from collections.abc import Callable

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)
from qfluentwidgets import IndeterminateProgressRing, MessageBoxBase, PushButton


class ShortcutDialog(MessageBoxBase):
    def __init__(
        self, title: str, values: tuple[str, ...], validate: Callable[[tuple[str, ...]], str],
        parent: QWidget, *, single: bool = False,
    ) -> None:
        self._recording: int | None = None
        super().__init__(parent)
        self.setWindowTitle(f"{title}的按键配置")
        self.widget.setMinimumWidth(520)
        self._validate = validate
        self._single = single
        self._rows: list[QWidget] = []
        self._buttons: list[PushButton] = []
        self._values: list[str] = []
        self._candidate = ""
        layout = self.viewLayout
        layout.setSpacing(14)
        heading = QLabel(f"“{title}”的按键配置")
        heading.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(heading)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(90)
        scroll.setMaximumHeight(230)
        container = QWidget()
        self._entries = QVBoxLayout(container)
        self._entries.setContentsMargins(0, 0, 0, 0)
        self._entries.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)
        self._add = PushButton("＋  添加按键配置")
        self._add.clicked.connect(self._start_new)
        layout.addWidget(self._add)
        self._error = QLabel(wordWrap=True)
        self._error.setStyleSheet("color: #c42b1c;")
        layout.addWidget(self._error)
        self.cancelButton.setText("取消")
        self._confirm_button = self.yesButton
        self._confirm_button.setText("确定")
        self.buttonLayout.removeWidget(self.yesButton)
        self.buttonLayout.removeWidget(self.cancelButton)
        self.buttonLayout.addStretch()
        self.buttonLayout.addWidget(self.cancelButton)
        self.buttonLayout.addWidget(self.yesButton)
        for value in values:
            self._add_entry(value)
        self._update_add()

    def _add_entry(self, value: str) -> None:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        button = PushButton(value or "请按下按键")
        button.setAccessibleName("录制快捷键")
        button.clicked.connect(lambda: self._start_recording(row))
        action = PushButton("删除")
        action.clicked.connect(lambda: self._row_action(row))
        ring = IndeterminateProgressRing(button, start=False)
        ring.setFixedSize(24, 24)
        ring.setStrokeWidth(3)
        ring.hide()
        ring.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        waiting = QLabel("请按下按键", button)
        waiting.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        waiting.hide()
        indicator = QHBoxLayout(button)
        indicator.setContentsMargins(12, 4, 12, 4)
        indicator.setSpacing(8)
        indicator.addWidget(ring)
        indicator.addWidget(waiting)
        row.ring = ring
        row.waiting = waiting
        layout.addWidget(button)
        layout.addStretch()
        layout.addWidget(action)
        row.action = action
        self._rows.append(row)
        self._buttons.append(button)
        self._values.append(value)
        self._entries.insertWidget(self._entries.count() - 1, row)
        self._update_add()

    def _start_new(self) -> None:
        self._add_entry("")
        self._start_recording(self._rows[-1])

    def _start_recording(self, row: QWidget) -> None:
        if self._recording is not None:
            return
        self._recording = self._rows.index(row)
        self._candidate = ""
        self._buttons[self._recording].setText("")
        row.waiting.show()
        row.ring.show()
        row.ring.start()
        row.action.setText("✓")
        row.action.setEnabled(False)
        self._confirm_button.setEnabled(False)
        self._error.clear()
        self._update_add()
        QApplication.instance().installEventFilter(self)
        self.setFocus()

    def eventFilter(self, watched, event) -> bool:
        if self._recording is None or not isinstance(watched, QWidget):
            return super().eventFilter(watched, event)
        if watched is not self and not self.isAncestorOf(watched):
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if event.isAutoRepeat() or key in (
                Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
                Qt.Key.Key_AltGr, Qt.Key.Key_unknown,
            ):
                return True
            self._candidate = QKeySequence(event.keyCombination()).toString(
                QKeySequence.SequenceFormat.PortableText
            )
            self._buttons[self._recording].setText(self._candidate)
            self._rows[self._recording].ring.stop()
            self._rows[self._recording].ring.hide()
            self._rows[self._recording].waiting.hide()
            self._rows[self._recording].action.setEnabled(bool(self._candidate))
            event.accept()
            return True
        if event.type() == QEvent.Type.KeyRelease:
            return True
        return super().eventFilter(watched, event)

    def _row_action(self, row: QWidget) -> None:
        index = self._rows.index(row)
        if self._recording == index:
            if not self._candidate:
                return
            self._values[index] = self._candidate
            self._end_recording()
        elif self._recording is None:
            self._remove_entry(row, self._buttons[index])

    def _end_recording(self) -> None:
        if self._recording is None:
            return
        index = self._recording
        QApplication.instance().removeEventFilter(self)
        self._recording = None
        self._rows[index].ring.stop()
        self._rows[index].ring.hide()
        self._rows[index].waiting.hide()
        self._buttons[index].setText(self._values[index] or "未设置")
        self._rows[index].action.setText("删除")
        self._rows[index].action.setEnabled(True)
        self._confirm_button.setEnabled(True)
        self._update_add()

    def _remove_entry(self, row: QWidget, button: PushButton) -> None:
        index = self._rows.index(row)
        self._rows.pop(index)
        self._buttons.pop(index)
        self._values.pop(index)
        row.hide()
        row.deleteLater()
        self._update_add()

    def _update_add(self) -> None:
        self._add.setEnabled(self._recording is None and (not self._single or not self._rows))

    def validate(self) -> bool:
        if self._recording is not None:
            return False
        if any(not value for value in self._values):
            self._error.setText("请设置按键，或删除空的按键配置。")
            return False
        error = self._validate(tuple(self._values))
        if error:
            self._error.setText(error)
            return False
        return True

    def _confirm(self) -> None:
        if self.validate():
            self.accept()
    def done(self, result: int) -> None:
        if self._recording is not None:
            QApplication.instance().removeEventFilter(self)
            self._rows[self._recording].ring.stop()
            self._recording = None
        super().done(result)
