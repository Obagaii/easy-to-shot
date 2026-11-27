from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QWidget
from qfluentwidgets import LineEdit, MessageBoxBase, PushButton

from e2s.capture.translation import DEEPSEEK_MODEL
from e2s.platform.windows.credentials import (
    CredentialError, delete_deepseek_key, get_deepseek_key, save_deepseek_key,
)


class DeepSeekSettingsDialog(MessageBoxBase):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI 翻译设置")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.widget.setMinimumWidth(420)
        self._key = LineEdit()
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        self._key.setAccessibleName("DeepSeek API Key")
        self._key.setPlaceholderText("输入自己的 DeepSeek API Key")
        self._status = QLabel(wordWrap=True)
        self._remove = PushButton("移除已保存的 Key")
        self._remove.clicked.connect(self._remove_key)
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")
        self.yesButton.setEnabled(False)
        self._key.textChanged.connect(lambda text: self.yesButton.setEnabled(bool(text.strip())))
        form = QFormLayout()
        form.addRow("服务商", QLabel("DeepSeek"))
        form.addRow("翻译模型", QLabel(DEEPSEEK_MODEL))
        form.addRow("API Key", self._key)
        self.viewLayout.addLayout(form)
        self.viewLayout.addWidget(self._status)
        self.viewLayout.addWidget(self._remove)
        try:
            is_configured = bool(get_deepseek_key())
        except CredentialError as error:
            self._status.setText(str(error))
            self._remove.setEnabled(True)
        else:
            self._remove.setEnabled(is_configured)
            self._status.setText(
                "已保存到 Windows 凭据管理器。输入新 Key 可替换。"
                if is_configured else "尚未配置。API Key 将保存到 Windows 凭据管理器。"
            )
        self._key.setFocus()

    def validate(self) -> bool:
        try:
            save_deepseek_key(self._key.text())
        except (CredentialError, ValueError) as error:
            self._status.setText(str(error))
            return False
        self._key.clear()
        return True

    def _remove_key(self) -> None:
        try:
            delete_deepseek_key()
        except CredentialError as error:
            self._status.setText(str(error))
        else:
            self._key.clear()
            self._remove.setEnabled(False)
            self._status.setText("已移除。")
