from PySide6.QtCore import QPoint, QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import QImage, QKeySequence, QMouseEvent, QPainter, QPixmap, QPolygonF, QRegion, QShortcut, QTextCursor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QWidget
from qfluentwidgets import ComboBox

from e2s.capture.ocr import OcrLine
from e2s.capture.session import OutputSnapshot
from e2s.capture.stream_translation import StreamingTranslator
from e2s.platform.windows.credentials import CredentialError, get_deepseek_key
from e2s.ui.native.annotation_controls import CAPTURE_CONTROLS_STYLE, PanelPosition, describe_control
from e2s.ui.native.ocr_layout import prepare_text_rows
from e2s.ui.native.ocr_text_layer import OcrTextLayer
from e2s.ui.native.toolbar_icons import toolbar_icon
from e2s.ui.native.workbench import LANGUAGES


class OriginalImage(QLabel):
    moved = Signal()

    def __init__(self, image, parent: QWidget) -> None:
        super().__init__(parent)
        self._image = QPixmap.fromImage(image)
        self._anchor: QPoint | None = None
        self.setScaledContents(True)
        self.setPixmap(self._image)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("拖动原图")
        self.setAccessibleName("识别原图")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._anchor = event.globalPosition().toPoint() - self.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._anchor is not None:
            self.move(event.globalPosition().toPoint() - self._anchor)
            self.moved.emit()
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._anchor = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        event.accept()


class OcrWorkspace(QWidget):
    closed = Signal()

    def __init__(self, snapshot: OutputSnapshot, lines: tuple[OcrLine, ...],
                 region: QRect, parent: QWidget, *, language: str) -> None:
        super().__init__(parent)
        self.setGeometry(parent.rect())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.close)
        self._region = QRect(region)
        self._snapshot = snapshot
        self._source_text = "\n".join(line.text for line in lines)
        self._is_original = False
        self._translator = StreamingTranslator(self)
        self._translator.updated.connect(self._show_stream)
        self._translator.finished.connect(self._translation_finished)
        self._translator.failed.connect(self._translation_failed)
        self._original = OriginalImage(snapshot.to_image(), self)
        self._original.moved.connect(self._on_original_moved)
        self._original.resize(region.size())
        self._original_position = self._adjacent_position(region)
        self._original.move(self._original_position)
        self._original.show()

        image = snapshot.to_image()
        self._rows = prepare_text_rows(image, lines, region.width() / image.width(),
                                       region.height() / image.height())
        cleaned = image.copy()
        with QPainter(cleaned) as painter:
            for row in self._rows:
                polygon = QPolygonF([QPointF(x, y) for x, y in row.line.corners])
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(row.background)
                painter.drawPolygon(polygon)
        self._background = QLabel(self)
        self._background.setGeometry(region)
        self._background.setScaledContents(True)
        self._background.setPixmap(QPixmap.fromImage(cleaned))
        self._background.show()
        self._editor = OcrTextLayer(self._rows, self)
        self._editor.setObjectName("ocrTextLayer")
        self._editor.setAccessibleName("识别文字")
        self._editor.setGeometry(region)
        self._editor.setReadOnly(True)
        self._editor.document().setDocumentMargin(0)
        self._editor.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._normal_style = (
            "QPlainTextEdit { background: transparent; color: #111111; "
            "border: none; padding: 0; selection-background-color: #1677ff; }"
        )
        self._editor.setStyleSheet(self._normal_style)
        self._apply_text_layout(self._source_text)
        self._editor.show()

        self._toolbar = QFrame(self)
        self._toolbar.setProperty("toolbarSurface", True)
        self._toolbar.setStyleSheet(CAPTURE_CONTROLS_STYLE)
        row = QHBoxLayout(self._toolbar)
        row.setContentsMargins(7, 5, 7, 5)
        row.setSpacing(4)
        handle = QToolButton(self._toolbar)
        handle.setIcon(toolbar_icon("drag_handle"))
        handle.setFixedSize(17, 38)
        describe_control(handle, "拖动识别工具栏")
        self._position = PanelPosition(self._toolbar, handle)
        self._position.moved.connect(self._update_mask)
        row.addWidget(handle)
        self._show_original = self._button(row, "显示原文", "view_original", self._toggle_original)
        self._edit = self._button(row, "编辑文字", "edit_text", self._toggle_edit)
        self._edit.setCheckable(True)
        self._translate = self._button(row, "翻译", "translate_text", self.start_translation)
        self._language = ComboBox(self._toolbar)
        for label, language_code in LANGUAGES:
            self._language.addItem(label, userData=language_code)
        self._language.setCurrentIndex(max(0, self._language.findData(language)))
        row.addWidget(self._language)
        self._model = ComboBox(self._toolbar)
        self._model.addItem("免费翻译", userData="free")
        self._model.addItem("DeepSeek", userData="deepseek")
        row.addWidget(self._model)
        self._button(row, "关闭文字识别", "cancel", self.close)
        self._toolbar.adjustSize()
        x = min(max(0, region.right() + 1 - self._toolbar.width()),
                max(0, self.width() - self._toolbar.width()))
        y = region.bottom() + 56
        if y + self._toolbar.height() > self.height():
            y = max(0, region.top() - self._toolbar.height() - 5)
        self._position.place(QPoint(x, y))
        self._toolbar.show()
        self._status = QLabel(self)
        self._status.setStyleSheet("background: #ffffff; color: #d4380d; padding: 4px;")
        self._status.move(self._toolbar.x(), max(0, self._toolbar.y() - 28))
        self._status.hide()
        self._toolbar.raise_()
        self._editor.setFocus()
        self._update_mask()

    def _apply_text_layout(self, text: str) -> None:
        self._editor.setPlainText(text)

    def _on_original_moved(self) -> None:
        if not self._is_original:
            self._original_position = self._original.pos()
        self._update_mask()

    def _update_mask(self) -> None:
        region = QRegion(self._original.geometry()).united(QRegion(self._toolbar.geometry()))
        if not self._editor.isHidden():
            region = region.united(QRegion(self._editor.geometry()))
        if not self._status.isHidden():
            region = region.united(QRegion(self._status.geometry()))
        self.setMask(region)

    def _button(self, row: QHBoxLayout, name: str, icon: str, callback) -> QToolButton:
        button = QToolButton(self._toolbar)
        button.setIcon(toolbar_icon(icon))
        button.setIconSize(QSize(22, 22))
        button.setFixedSize(38, 38)
        button.setProperty("toolButton", True)
        describe_control(button, name)
        button.clicked.connect(callback)
        row.addWidget(button)
        return button

    def _adjacent_position(self, region: QRect) -> QPoint:
        x = region.left() - region.width() - 8
        if x < 0:
            x = min(self.width() - region.width(), region.right() + 9)
        return QPoint(max(0, x), max(0, min(region.top(), self.height() - region.height())))

    def _toggle_original(self) -> None:
        self._is_original = not self._is_original
        self._editor.setVisible(not self._is_original)
        self._background.setVisible(not self._is_original)
        self._original.move(self._region.topLeft() if self._is_original else self._original_position)
        self._original.raise_()
        self._toolbar.raise_()
        self._update_mask()

    def _toggle_edit(self, checked: bool) -> None:
        if checked and self._is_original:
            self._toggle_original()
        self._editor.setReadOnly(not checked)
        self._background.setVisible(not checked and not self._is_original)
        self._editor.setStyleSheet(
            "QPlainTextEdit { background: white; color: black; border: none; padding: 4px; }"
            if checked else self._normal_style
        )
        if checked:
            self._editor.setFocus()
        else:
            self._source_text = self._editor.toPlainText()
            self._apply_text_layout(self._source_text)

    def start_translation(self) -> None:
        text = self._editor.toPlainText().strip()
        if not text:
            return
        self._source_text = text
        if self._is_original:
            self._toggle_original()
        model = self._model.currentData()
        key = ""
        if model == "deepseek":
            try:
                key = get_deepseek_key() or ""
            except CredentialError:
                key = ""
            if not key:
                self._translation_failed("请在主菜单的 AI 模型中配置 DeepSeek API Key。")
                return
        self._status.hide()
        self._edit.setChecked(False)
        self._toggle_edit(False)
        self._translate.setEnabled(False)
        self._translator.translate(text, self._language.currentData(), model, key)

    def _show_stream(self, text: str) -> None:
        self._apply_text_layout(text)

    def _translation_finished(self, text: str) -> None:
        self._apply_text_layout(text)
        self._translate.setEnabled(True)

    def _translation_failed(self, message: str) -> None:
        self._apply_text_layout(self._source_text)
        self._translate.setEnabled(True)
        self._status.setText(message)
        self._status.adjustSize()
        self._status.show()
        self._status.raise_()
        self._update_mask()

    def output_image(self) -> QImage:
        if self._is_original:
            return self._snapshot.to_image()
        image = self._snapshot.to_image()
        cursor = self._editor.textCursor()
        selection = QTextCursor(cursor)
        cursor.clearSelection()
        self._editor.setTextCursor(cursor)
        try:
            with QPainter(image) as painter:
                painter.drawPixmap(image.rect(), self._background.pixmap(),
                                   self._background.pixmap().rect())
                painter.scale(image.width() / self._editor.width(),
                              image.height() / self._editor.height())
                self._editor.render(painter, QPoint())
        finally:
            self._editor.setTextCursor(selection)
        return image.convertToFormat(QImage.Format.Format_RGBA8888)

    def closeEvent(self, event) -> None:
        self._translator.cancel()
        self.closed.emit()
        super().closeEvent(event)
