from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt, Slot
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

from e2s.capture.ocr import OcrLine
from e2s.capture.service import CaptureError
from e2s.capture.translation import DeepSeekTranslator
from e2s.platform.windows.credentials import CredentialError, get_deepseek_key
from e2s.ui.native.deepseek_settings import DeepSeekSettingsDialog
from e2s.ui.native.workbench import LANGUAGES

_TRANSLATION_HINT = "点击「翻译」后会将原文发送给 DeepSeek。"
_COVER_HINT = "覆盖到截图需要保留识别时的分行。"


class RecognitionResults(QDialog):
    def __init__(
        self, lines: tuple[OcrLine, ...], cover_text: Callable[[tuple[str, ...]], None],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("截图文字识别")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(740, 420)
        self._line_count = len(lines)
        self._cover_text = cover_text
        self._translated_lines: tuple[str, ...] = ()
        self._translator = DeepSeekTranslator(self)
        self._translator.translated.connect(self._show_translation)
        self._translator.failed.connect(self._show_error)
        self.finished.connect(self._translator.cancel)

        self._source = QPlainTextEdit("\n".join(line.text for line in lines), self)
        self._source.setObjectName("recognizedText")
        self._source.setAccessibleName("识别原文")
        self._result = QPlainTextEdit(self, readOnly=True)
        self._result.setObjectName("translatedText")
        self._result.setAccessibleName("译文")
        self._result.setPlaceholderText("译文将在此显示")

        self._source_cover = QPushButton("覆盖到截图", self, autoDefault=False)
        self._source_cover.setAccessibleName("将识别原文覆盖到截图")
        self._source_cover.clicked.connect(lambda: self._apply_cover(self._source_lines()))
        self._result_cover = QPushButton("覆盖到截图", self, autoDefault=False)
        self._result_cover.setAccessibleName("将译文覆盖到截图")
        self._result_cover.clicked.connect(lambda: self._apply_cover(self._translated_lines))

        panels = QSplitter(Qt.Orientation.Horizontal, self)
        panels.setChildrenCollapsible(False)
        panels.addWidget(self._text_panel("识别原文", self._source, self._source_cover))
        panels.addWidget(self._text_panel("译文", self._result, self._result_cover))
        panels.setSizes([1, 1])

        self._target = QComboBox(self)
        self._target.setAccessibleName("目标语言")
        for name, language in LANGUAGES:
            self._target.addItem(name, language)
        root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
        settings = QSettings(str(Path(root) / "workbench.ini"), QSettings.Format.IniFormat)
        index = self._target.findData(settings.value("translation/language", "Simplified Chinese"))
        self._target.setCurrentIndex(max(index, 0))

        self._translate = QPushButton("翻译", self, autoDefault=False)
        self._translate.clicked.connect(self._translate_source)
        self._settings = QPushButton("配置 API Key", self, autoDefault=False)
        self._settings.clicked.connect(self._open_settings)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("目标语言", self))
        controls.addWidget(self._target)
        controls.addWidget(self._translate)
        controls.addStretch()
        controls.addWidget(self._settings)

        self._status = QLabel(_TRANSLATION_HINT, self, wordWrap=True)
        close = QPushButton("关闭", self, autoDefault=False)
        close.clicked.connect(self.reject)
        footer = QHBoxLayout()
        footer.addWidget(self._status, 1)
        footer.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(panels, 1)
        layout.addLayout(footer)

        self._target.currentIndexChanged.connect(self._clear_result)
        self._source.textChanged.connect(self._clear_result)
        self._set_translating(False)
        self._source.setFocus()

    def _text_panel(
        self, title: str, editor: QPlainTextEdit, cover_button: QPushButton
    ) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(QLabel(title, panel), 1)
        copy = QPushButton("复制" + title, panel, autoDefault=False)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(editor.toPlainText()))
        copy.setEnabled(not editor.document().isEmpty())
        editor.textChanged.connect(lambda: copy.setEnabled(not editor.document().isEmpty()))
        header.addWidget(copy)
        header.addWidget(cover_button)
        layout.addLayout(header)
        layout.addWidget(editor)
        return panel

    @Slot()
    def _open_settings(self) -> None:
        DeepSeekSettingsDialog(self).open()

    def _source_lines(self) -> tuple[str, ...]:
        lines = tuple(line.strip() for line in self._source.toPlainText().split("\n"))
        return lines if len(lines) == self._line_count and all(lines) else ()

    @Slot()
    def _clear_result(self) -> None:
        self._translated_lines = ()
        self._result.clear()
        self._status.setText(_TRANSLATION_HINT)
        self._set_translating(False)

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
        self._translated_lines = ()
        self._result.clear()
        self._status.setText("DeepSeek 正在翻译…")
        self._set_translating(True)
        self._translator.translate(text, self._target.currentData(), key, lines=self._source_lines())

    def _set_translating(self, is_translating: bool) -> None:
        self._source.setReadOnly(is_translating)
        self._target.setEnabled(not is_translating)
        self._translate.setEnabled(not is_translating and bool(self._source.toPlainText().strip()))
        self._settings.setEnabled(not is_translating)
        source_lines = self._source_lines()
        self._source_cover.setEnabled(not is_translating and bool(source_lines))
        self._source_cover.setToolTip("覆盖识别原文" if source_lines else _COVER_HINT)
        self._result_cover.setEnabled(not is_translating and bool(self._translated_lines))
        self._result_cover.setToolTip("覆盖译文" if source_lines else _COVER_HINT)

    def _apply_cover(self, lines: tuple[str, ...]) -> None:
        if not lines:
            return
        try:
            self._cover_text(lines)
        except CaptureError as error:
            self._status.setText(str(error))
        except MemoryError:
            self._status.setText("内存不足，无法覆盖文字。")
        else:
            self.accept()

    @Slot(str, object)
    def _show_translation(self, text: str, lines: tuple[str, ...]) -> None:
        self._translated_lines = lines
        self._result.setPlainText(text)
        self._status.setText("翻译完成。" if lines else f"翻译完成。{_COVER_HINT}")
        self._set_translating(False)

    @Slot(str)
    def _show_error(self, message: str) -> None:
        self._status.setText(message)
        self._set_translating(False)

