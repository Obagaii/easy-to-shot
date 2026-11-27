from PySide6.QtGui import QAction
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget
from qfluentwidgets import ComboBox, DropDownPushButton, FluentIcon, MessageBoxBase, TransparentToolButton
from qfluentwidgets.components.widgets.menu import CheckableMenu

from e2s.storage.quick_capture import QuickCaptureBinding


MOUSE_BUTTONS = (
    ("左键拖动", "left"), ("右键拖动", "right"),
    ("中键拖动", "middle"), ("侧键拖动", "side"),
)
MODIFIERS = (("win", "Win"), ("alt", "Alt"), ("ctrl", "Ctrl"))


def binding_label(binding: QuickCaptureBinding) -> str:
    if not binding.enabled or not binding.modifiers:
        return "未设置"
    keys = [label for key, label in MODIFIERS if key in binding.modifiers]
    button = next((label for label, value in MOUSE_BUTTONS if value == binding.button), "左键拖动")
    return " + ".join((*keys, button))


class QuickCaptureDialog(MessageBoxBase):
    def __init__(self, binding: QuickCaptureBinding, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("截图复制到剪贴板的按键配置")
        self.widget.setMinimumWidth(520)
        layout = self.viewLayout
        layout.setSpacing(16)
        header = QHBoxLayout()
        heading = QLabel("“截图复制到剪贴板”的鼠标配置")
        heading.setStyleSheet("font-size: 20px; font-weight: 600;")
        header.addWidget(heading, 1)
        close = TransparentToolButton(FluentIcon.CLOSE)
        close.setAccessibleName("关闭")
        close.clicked.connect(self.reject)
        header.addWidget(close)
        layout.addLayout(header)
        layout.addWidget(QLabel("激活按键"))
        self._modifier_button = DropDownPushButton()
        self._modifier_button.setMinimumHeight(40)
        self._modifier_button.setStyleSheet("text-align: left; padding-left: 12px;")
        menu = CheckableMenu(parent=self._modifier_button)
        self._keys = {}
        for key, label in MODIFIERS:
            action = QAction("Windows" if key == "win" else label, menu)
            action.setCheckable(True)
            action.setChecked(binding.enabled and key in binding.modifiers)
            action.toggled.connect(self._refresh_modifiers)
            menu.addAction(action)
            self._keys[key] = action
        self._modifier_button.setMenu(menu)
        self._refresh_modifiers()
        layout.addWidget(self._modifier_button)
        layout.addSpacing(8)
        layout.addWidget(QLabel("鼠标按键"))
        self._button = ComboBox()
        self._button.setMinimumHeight(40)
        for label, value in MOUSE_BUTTONS:
            self._button.addItem(label, userData=value)
        self._button.setCurrentIndex(self._button.findData(binding.button))
        layout.addWidget(self._button)
        self.cancelButton.setText("取消")
        self.yesButton.setText("确定")
        self.buttonLayout.removeWidget(self.yesButton)
        self.buttonLayout.removeWidget(self.cancelButton)
        self.buttonLayout.addStretch()
        self.buttonLayout.addWidget(self.cancelButton)
        self.buttonLayout.addWidget(self.yesButton)
    def _refresh_modifiers(self, *_args) -> None:
        labels = ["Windows" if key == "win" else label for key, label in MODIFIERS
                  if self._keys[key].isChecked()]
        self._modifier_button.setText("  +  ".join(labels) if labels else "请选择激活按键")

    def binding(self) -> QuickCaptureBinding:
        modifiers = frozenset(key for key, action in self._keys.items() if action.isChecked())
        return QuickCaptureBinding(str(self._button.currentData()), modifiers, bool(modifiers))

    def _confirm(self) -> None:
        self.accept()

