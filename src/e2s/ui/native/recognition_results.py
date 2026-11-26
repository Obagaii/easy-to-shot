from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from e2s.capture.translation import DeepSeekTranslator
from e2s.platform.windows.credentials import CredentialError, get_deepseek_key
from e2s.ui.native.deepseek_settings import DeepSeekSettingsDialog

_TARGET_LANGUAGES = (
    ("简体中文", "Simplified Chinese"),
    ("繁体中文", "Traditional Chinese"),
    ("英语", "English"),
    ("日语", "Japanese"),
    ("韩语", "Korean"),
    ("法语", "French"),
    ("德语", "German"),
    ("西班牙语", "Spanish"),
    ("俄语", "Russian"),
)


class RecognitionResults(QDialog):
    def __init__(self, text: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("截图文字识别")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(710, 420)
        self._translator = DeepSeekTranslator(self)
        self._translator.translated.connect(self._show_translation)
        self._translator.failed.connect(self._show_error)
        self.finished.connect(self._translator.cancel)

        self._source = QPlainTextEdit(text, self)
        self._source.setObjectName("recognizedText")
        self._source.setAccessibleName("识别原文")
        self._result = QPlainTextEdit(self, readOnly=True)
        self._result.setObjectName("translatedText")
        self._result.setAccessibleName("译文")
        self._result.setPlaceholderText("译文将在此显示")

        panels = QSplitter(Qt.Orientation.Horizontal, self)
        panels.setChildrenCollapsible(False)
        panels.addWidget(self._text_panel("识别原文", self._source))
        panels.addWidget(self._text_panel("译文", self._result))
        panels.setSizes([1, 1])

        self._target = QComboBox(self)
        self._target.setAccessibleName("目标语言")
        for name, language in _TARGET_LANGUAGES:
            self._target.addItem(name, language)
        self._target.currentIndexChanged.connect(self._clear_result)
        self._source.textChanged.connect(self._clear_result)

        self._translate = QPushButton("翻译", self)
        self._translate.setAutoDefault(False)
        self._translate.clicked.connect(self._translate_source)
        self._settings = QPushButton("配置 API Key", self)
        self._settings.setAutoDefault(False)
        self._settings.clicked.connect(self._open_settings)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("目标语言", self))
        controls.addWidget(self._target)
        controls.addWidget(self._translate)
        controls.addStretch()
        controls.addWidget(self._settings)

        self._status = QLabel(self, wordWrap=True)
        self._status.setText("点击「翻译」后会将原文发送给 DeepSeek。")
        close = QPushButton("关闭", self)
        close.setAutoDefault(False)
        close.clicked.connect(self.reject)
        footer = QHBoxLayout()
        footer.addWidget(self._status, 1)
        footer.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(panels, 1)
        layout.addLayout(footer)
        self._source.setFocus()

    def _text_panel(self, title: str, editor: QPlainTextEdit) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(QLabel(title, panel), 1)
        copy = QPushButton("复制" + title, panel)
        copy.setAutoDefault(False)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(editor.toPlainText()))
        copy.setEnabled(not editor.document().isEmpty())
        editor.textChanged.connect(lambda: copy.setEnabled(not editor.document().isEmpty()))
        header.addWidget(copy)
        layout.addLayout(header)
        layout.addWidget(editor)
        return panel

    @Slot()
    def _open_settings(self) -> None:
        dialog = DeepSeekSettingsDialog(self)
        dialog.accepted.connect(self._clear_result)
        dialog.open()

    @Slot()
    def _clear_result(self) -> None:
        self._result.clear()
        self._status.setText("点击「翻译」后会将原文发送给 DeepSeek。")
        self._translate.setEnabled(bool(self._source.toPlainText().strip()))

    @Slot()
    def _translate_source(self) -> None:
        text = self._source.toPlainText().strip()
        if not text:
            return
        try:
            key = get_deepseek_key()
        except CredentialError as error:
            self._status.setText(str(error))
            return
        if not key:
            self._status.setText("请先配置 DeepSeek API Key。")
            self._open_settings()
            return
        self._result.clear()
        self._status.setText("DeepSeek 正在翻译…")
        self._set_translating(True)
        self._translator.translate(text, self._target.currentData(), key)

    def _set_translating(self, is_translating: bool) -> None:
        self._source.setReadOnly(is_translating)
        self._target.setEnabled(not is_translating)
        self._translate.setEnabled(not is_translating)
        self._settings.setEnabled(not is_translating)

    @Slot(str)
    def _show_translation(self, text: str) -> None:
        self._result.setPlainText(text)
        self._status.setText("翻译完成。")
        self._set_translating(False)

    @Slot(str)
    def _show_error(self, message: str) -> None:
        self._status.setText(message)
        self._set_translating(False)
