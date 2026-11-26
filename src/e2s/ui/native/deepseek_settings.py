from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QWidget,
)

from e2s.capture.translation import DEEPSEEK_MODEL
from e2s.platform.windows.credentials import (
    CredentialError,
    delete_deepseek_key,
    get_deepseek_key,
    save_deepseek_key,
)


class DeepSeekSettingsDialog(QDialog):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI 翻译设置")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(420, 170)

        self._key = QLineEdit(self, echoMode=QLineEdit.EchoMode.Password)
        self._key.setAccessibleName("DeepSeek API Key")
        self._key.setPlaceholderText("输入自己的 DeepSeek API Key")
        self._status = QLabel(self, wordWrap=True)

        buttons = QDialogButtonBox(self)
        save = buttons.addButton("保存", QDialogButtonBox.ButtonRole.AcceptRole)
        self._remove = buttons.addButton("移除已保存的 Key", QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        save.clicked.connect(self._save_key)
        self._remove.clicked.connect(self._remove_key)
        buttons.rejected.connect(self.reject)
        save.setEnabled(False)
        self._key.textChanged.connect(lambda text: save.setEnabled(bool(text.strip())))

        form = QFormLayout(self)
        form.addRow("服务商", QLabel("DeepSeek", self))
        form.addRow("翻译模型", QLabel(DEEPSEEK_MODEL, self))
        form.addRow("API Key", self._key)
        form.addRow(self._status)
        form.addRow(buttons)

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

    def _save_key(self) -> None:
        try:
            save_deepseek_key(self._key.text())
        except (CredentialError, ValueError) as error:
            self._status.setText(str(error))
        else:
            self._key.clear()
            self.accept()

    def _remove_key(self) -> None:
        try:
            delete_deepseek_key()
        except CredentialError as error:
            self._status.setText(str(error))
        else:
            self._key.clear()
            self._remove.setEnabled(False)
            self._status.setText("已移除。")
