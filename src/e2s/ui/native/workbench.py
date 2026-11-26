from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, QStandardPaths, Qt, Signal
from PySide6.QtGui import QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QKeySequenceEdit, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from e2s.capture.translation import DEEPSEEK_MODEL
from e2s.platform.windows.credentials import (
    CredentialError, delete_deepseek_key, get_deepseek_key, save_deepseek_key,
)
from e2s.platform.windows.hotkeys import DEFAULT_HOTKEY, HotkeyError, HotkeyState
from e2s.storage.history import HistoryService, HistoryStatus, HistoryStore

_HOTKEY_MESSAGES = {
    HotkeyError.INVALID: "请输入包含 Ctrl、Shift 或 Alt 的单个组合键。",
    HotkeyError.RESERVED: "该组合键由系统保留，请换一个。",
    HotkeyError.CONFLICT: "该组合键已被占用，请换一个。",
    HotkeyError.UNAVAILABLE: "系统无法注册该组合键，仍可从托盘截图。",
}
LANGUAGES = (
    ("简体中文", "Simplified Chinese"), ("繁体中文", "Traditional Chinese"),
    ("英语", "English"), ("日语", "Japanese"), ("韩语", "Korean"),
    ("法语", "French"), ("德语", "German"), ("西班牙语", "Spanish"),
    ("俄语", "Russian"),
)
_STYLE = """
QMainWindow, QWidget#content { background: #f5f7fb; color: #202a3a; }
QFrame#sidebar { background: #edf1f8; border-right: 1px solid #dce3ed; }
QLabel#brand { font-size: 21px; font-weight: 700; color: #1b2a40; }
QLabel#title { font-size: 25px; font-weight: 700; }
QLabel#subtitle, QLabel#hint { color: #718096; }
QLabel#section { font-size: 16px; font-weight: 600; }
QFrame#card { background: white; border: 1px solid #e1e7f0; border-radius: 10px; }
QListWidget#navigation { background: transparent; border: 0; outline: 0; font-size: 14px; }
QListWidget#navigation::item { padding: 12px 14px; border-radius: 7px; margin: 2px 8px; }
QListWidget#navigation::item:selected { background: #dce9ff; color: #2563c5; }
QListWidget#navigation::item:hover:!selected { background: #e1e8f2; }
QPushButton { background: white; border: 1px solid #ccd7e6; border-radius: 6px; padding: 8px 15px; color: #27374d; }
QPushButton:hover { background: #eef4ff; border-color: #8aafe9; }
QPushButton#primary { background: #3978df; border-color: #3978df; color: white; }
QPushButton#primary:hover { background: #2e68c5; }
QLineEdit, QKeySequenceEdit, QComboBox, QListWidget#history { background: white; border: 1px solid #ccd7e6; border-radius: 6px; padding: 7px; }
QListWidget#history::item { padding: 10px; border-bottom: 1px solid #edf1f5; }
QListWidget#history::item:selected { background: #e4efff; color: #203859; }
"""


class Workbench(QMainWindow):
    capture_requested = Signal()
    hotkey_requested = Signal(QKeySequence)

    def __init__(self, icon: QIcon, data_root: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Easy to Shot - 主菜单")
        self.setWindowIcon(icon)
        self.resize(960, 650)
        self.setMinimumSize(760, 520)
        self.setStyleSheet(_STYLE)
        root = data_root or Path(QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation
        ))
        self.history = HistoryService(HistoryStore(root))
        self.settings = QSettings(str(root / "workbench.ini"), QSettings.Format.IniFormat)

        shell = QWidget(self, objectName="content")
        layout = QHBoxLayout(shell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QFrame(objectName="sidebar")
        sidebar.setFixedWidth(200)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 28, 12, 20)
        brand = QLabel("Easy to Shot", objectName="brand")
        side.addWidget(brand)
        tagline = QLabel("轻松捕捉，记录灵感", objectName="hint")
        side.addWidget(tagline)
        side.addSpacing(22)
        capture = QPushButton("＋  新建截图", objectName="primary")
        capture.clicked.connect(self.capture_requested.emit)
        side.addWidget(capture)
        side.addSpacing(18)
        self._navigation = QListWidget(objectName="navigation")
        self._navigation.addItems(["全局热键", "截图历史", "OCR 和翻译", "AI 模型", "关于"])
        side.addWidget(self._navigation, 1)
        self._pages = QStackedWidget()
        for page in (self._hotkey_page(), self._history_page(), self._ocr_page(),
                     self._model_page(), self._about_page()):
            self._pages.addWidget(page)
        self._navigation.currentRowChanged.connect(self._change_page)
        self._navigation.setCurrentRow(0)
        layout.addWidget(sidebar)
        layout.addWidget(self._pages, 1)
        self.setCentralWidget(shell)

    def _page(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget(objectName="content")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(36, 32, 36, 28)
        layout.setSpacing(12)
        layout.addWidget(QLabel(title, objectName="title"))
        layout.addWidget(QLabel(subtitle, objectName="subtitle", wordWrap=True))
        layout.addSpacing(12)
        return page, layout

    def _card(self, title: str, description: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame(objectName="card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        layout.addWidget(QLabel(title, objectName="section"))
        layout.addWidget(QLabel(description, objectName="hint", wordWrap=True))
        return card, layout

    def _hotkey_page(self) -> QWidget:
        page, layout = self._page("全局热键", "设置快捷键，在任意界面快速开始截图。")
        card, content = self._card("截图快捷键", "按下组合键后点击应用；如有冲突，将保留原快捷键。")
        row = QHBoxLayout()
        self._shortcut = QKeySequenceEdit(QKeySequence(self.saved_hotkey()))
        self._shortcut.setMaximumSequenceLength(1)
        self._shortcut.setClearButtonEnabled(True)
        self._shortcut.setAccessibleName("截图热键")
        button = QPushButton("应用热键", objectName="primary")
        button.clicked.connect(lambda: self.hotkey_requested.emit(self._shortcut.keySequence()))
        row.addWidget(self._shortcut, 1)
        row.addWidget(button)
        content.addLayout(row)
        self._hotkey_status = QLabel(wordWrap=True)
        self._hotkey_feedback = QLabel(wordWrap=True, objectName="hint")
        content.addWidget(self._hotkey_status)
        content.addWidget(self._hotkey_feedback)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def _history_page(self) -> QWidget:
        page, layout = self._page("截图历史", "查看成功复制、保存或贴图的截图。")
        self._history_list = QListWidget(objectName="history")
        self._history_list.setIconSize(QSize(100, 64))
        self._history_list.currentItemChanged.connect(self._show_history_preview)
        self._history_items = {}
        self._preview = QLabel("选择一条记录查看预览", alignment=Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumHeight(150)
        self._preview.setWordWrap(True)
        layout.addWidget(self._history_list, 1)
        layout.addWidget(self._preview, 1)
        row = QHBoxLayout()
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh_history)
        copy = QPushButton("复制图片")
        copy.clicked.connect(self._copy_history)
        delete = QPushButton("删除记录")
        delete.clicked.connect(self._delete_history)
        row.addWidget(refresh)
        row.addWidget(copy)
        row.addWidget(delete)
        row.addStretch()
        layout.addLayout(row)
        return page

    def _ocr_page(self) -> QWidget:
        page, layout = self._page("OCR 和翻译", "配置文字识别和翻译的默认行为。")
        card, content = self._card("文字识别", "使用本地 PP-OCRv6 Small 识别中英文，无需上传截图。")
        content.addWidget(QLabel("识别引擎：RapidOCR · ONNX Runtime"))
        layout.addWidget(card)
        card, content = self._card("翻译", "翻译时会将识别文字发送给 DeepSeek；可在识别结果中更改语言。")
        self._language = QComboBox()
        for name, value in LANGUAGES:
            self._language.addItem(name, value)
        index = self._language.findData(self.settings.value("translation/language", "Simplified Chinese"))
        self._language.setCurrentIndex(max(index, 0))
        self._language.currentIndexChanged.connect(
            lambda: self.settings.setValue("translation/language", self._language.currentData())
        )
        content.addWidget(QLabel("默认目标语言"))
        content.addWidget(self._language)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def _model_page(self) -> QWidget:
        page, layout = self._page("AI 模型", "管理翻译使用的模型和访问凭据。")
        card, content = self._card("DeepSeek", "当前翻译使用 DeepSeek，API Key 保存在 Windows 凭据管理器。")
        content.addWidget(QLabel(f"模型：{DEEPSEEK_MODEL}"))
        self._key = QLineEdit(echoMode=QLineEdit.EchoMode.Password)
        self._key.setAccessibleName("DeepSeek API Key")
        self._key.setPlaceholderText("输入 API Key 以保存或替换")
        content.addWidget(self._key)
        row = QHBoxLayout()
        save = QPushButton("保存 Key", objectName="primary")
        save.clicked.connect(self._save_key)
        remove = QPushButton("移除 Key")
        remove.clicked.connect(self._remove_key)
        row.addWidget(save)
        row.addWidget(remove)
        row.addStretch()
        content.addLayout(row)
        self._key_status = QLabel(wordWrap=True, objectName="hint")
        content.addWidget(self._key_status)
        layout.addWidget(card)
        layout.addStretch()
        self._update_key_status()
        return page

    def _about_page(self) -> QWidget:
        page, layout = self._page("关于", "了解 Easy to Shot。")
        card, content = self._card("Easy to Shot", "截图、标注、文字识别与录屏，一处完成。")
        content.addWidget(QLabel("版本 0.1.0"))
        content.addWidget(QLabel("Windows 桌面截图工具"))
        layout.addWidget(card)
        layout.addStretch()
        return page

    def _change_page(self, index: int) -> None:
        self._pages.setCurrentIndex(index)
        if index == 1:
            self.refresh_history()
        elif index == 3:
            self._update_key_status()

    def refresh_history(self) -> None:
        self._history_list.clear()
        self._history_items = {}
        for entry in self.history.store.list_recent(limit=200):
            path = self.history.store.image_path(entry)
            try:
                stamp = datetime.fromisoformat(entry.created_at_utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                stamp = entry.created_at_utc
            item = QListWidgetItem(QIcon(str(path)), f"{stamp}   ·   {entry.width_px} × {entry.height_px}   ·   {entry.source}")
            item.setData(Qt.ItemDataRole.UserRole, entry.history_item_id)
            self._history_items[entry.history_item_id] = entry
            self._history_list.addItem(item)
        self._preview.setText("选择一条记录查看预览" if self._history_items else "暂无截图历史")

    def _selected_history(self):
        item = self._history_list.currentItem()
        return self._history_items.get(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _show_history_preview(self, *_args) -> None:
        item = self._selected_history()
        if item is None:
            self._preview.clear()
            return
        pixmap = QPixmap(str(self.history.store.image_path(item)))
        if pixmap.isNull():
            self._preview.setText("图片文件不可用")
        else:
            self._preview.setPixmap(pixmap.scaled(500, 220, Qt.AspectRatioMode.KeepAspectRatio,
                                                   Qt.TransformationMode.SmoothTransformation))

    def _copy_history(self) -> None:
        item = self._selected_history()
        if item:
            image = QPixmap(str(self.history.store.image_path(item)))
            if image.isNull():
                QMessageBox.warning(self, "截图历史", "图片文件不可用。")
            else:
                QApplication.clipboard().setPixmap(image)

    def _delete_history(self) -> None:
        item = self._selected_history()
        if item and QMessageBox.question(self, "删除记录", "确定删除这条截图历史吗？") == QMessageBox.StandardButton.Yes:
            if self.history.delete(item.history_item_id) != HistoryStatus.DELETED:
                QMessageBox.warning(self, "截图历史", "删除失败，请重试。")
            self.refresh_history()

    def _update_key_status(self) -> None:
        try:
            configured = bool(get_deepseek_key())
            self._key_status.setText("已配置 API Key。" if configured else "尚未配置 API Key。")
        except CredentialError as error:
            self._key_status.setText(str(error))

    def _save_key(self) -> None:
        try:
            save_deepseek_key(self._key.text())
        except (CredentialError, ValueError) as error:
            self._key_status.setText(str(error))
        else:
            self._key.clear()
            self._update_key_status()

    def _remove_key(self) -> None:
        try:
            delete_deepseek_key()
        except CredentialError as error:
            self._key_status.setText(str(error))
        else:
            self._key.clear()
            self._update_key_status()

    def saved_hotkey(self) -> str:
        return str(self.settings.value("hotkey/capture", DEFAULT_HOTKEY))

    def activate(self) -> None:
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def focus_hotkey_settings(self) -> None:
        self._navigation.setCurrentRow(0)
        self._shortcut.setFocus()

    def show_hotkey_state(self, state: HotkeyState) -> None:
        self._hotkey_status.setText(f"当前热键：{state.active}" if state.active else "当前未注册截图热键")
        self._hotkey_feedback.setText(_HOTKEY_MESSAGES.get(state.error, ""))
        if state.active and state.error is None:
            self.settings.setValue("hotkey/capture", state.active)


