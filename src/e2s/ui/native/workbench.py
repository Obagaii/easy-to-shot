from pathlib import Path

from PySide6.QtCore import QSettings, QSize, QStandardPaths, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QKeySequenceEdit, QLabel,
    QDialog, QLineEdit, QMainWindow, QMessageBox,
    QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from qfluentwidgets import (
    CardWidget, ComboBox, FluentIcon, LineEdit, NavigationInterface,
    PrimaryPushButton, PushButton,
)

from e2s import __version__
from e2s.capture.translation import DEEPSEEK_MODEL
from e2s.platform.windows.credentials import (
    CredentialError, delete_deepseek_key, get_deepseek_key, save_deepseek_key,
)
from e2s.platform.windows.hotkeys import DEFAULT_HOTKEY, HotkeyError, HotkeyState
from e2s.storage.history import HistoryService, HistoryStore
from e2s.storage.quick_capture import QuickCaptureBinding, load_quick_capture, save_quick_capture
from e2s.storage.shortcuts import canonical_shortcut, load_shortcuts, save_shortcuts
from e2s.ui.native.annotation_toolbar import _ACTION_COMMANDS, _TOOL_COMMANDS
from e2s.ui.native.history_page import HistoryPage
from e2s.ui.native.shortcut_dialog import ShortcutDialog
from e2s.ui.native.quick_capture_dialog import QuickCaptureDialog, binding_label

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
QKeySequenceEdit, QListWidget#history { background: white; border: 1px solid #ccd7e6; border-radius: 6px; padding: 7px; }
QListWidget#history::item { padding: 10px; border-bottom: 1px solid #edf1f5; }
QListWidget#history::item:selected { background: #e4efff; color: #203859; }
"""


class ShortcutCard(CardWidget):
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#a6b4c7"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 6, 6)


class Workbench(QMainWindow):
    capture_requested = Signal()
    hotkey_requested = Signal(QKeySequence)
    history_edit_requested = Signal(object)
    quick_capture_changed = Signal(object)

    def __init__(self, icon: QIcon, data_root: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("𝘌2𝘚")
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
        capture = PrimaryPushButton("＋  新建截图")
        capture.clicked.connect(self.capture_requested.emit)
        side.addWidget(capture)
        side.addSpacing(18)
        self._navigation = NavigationInterface(showMenuButton=False, collapsible=False)
        self._navigation.setExpandWidth(176)
        self._navigation.expand(False)
        entries = (
            ("hotkey", FluentIcon.SETTING, "全局热键"),
            ("quick", FluentIcon.SPEED_HIGH, "快速截图"),
            ("history", FluentIcon.HISTORY, "截图历史"),
            ("ocr", FluentIcon.LANGUAGE, "OCR 和翻译"),
            ("model", FluentIcon.ROBOT, "AI 模型"),
            ("about", FluentIcon.INFO, "关于"),
        )
        for index, (route, icon, label) in enumerate(entries):
            self._navigation.addItem(
                route, icon, label, onClick=lambda _checked=False, i=index: self._change_page(i)
            )
        side.addWidget(self._navigation, 1)
        self._pages = QStackedWidget()
        for page in (self._hotkey_page(), self._quick_capture_page(), self._history_page(), self._ocr_page(),
                     self._model_page(), self._about_page()):
            self._pages.addWidget(page)

        self._navigation.setCurrentItem("hotkey")
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
        card = CardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        layout.addWidget(QLabel(title, objectName="section"))
        layout.addWidget(QLabel(description, objectName="hint", wordWrap=True))
        return card, layout

    def _hotkey_page(self) -> QWidget:
        page, layout = self._page("快捷键", "配置全局截图热键和截图窗口内的工具快捷键。")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget(objectName="content")
        rows = QVBoxLayout(body)
        rows.setContentsMargins(0, 0, 8, 0)
        rows.setSpacing(10)
        self._shortcut_buttons = {}
        self._shortcut_definitions = {
            **{f"tool/{tool.value}": command for tool, command in _TOOL_COMMANDS.items()},
            **{f"action/{name}": command for name, command in _ACTION_COMMANDS.items()},
        }
        rows.addWidget(QLabel("全局快捷键", objectName="section"))
        rows.addWidget(QLabel("在任何应用中启动截图", objectName="hint"))
        rows.addWidget(self._shortcut_row("capture", "截图"))
        self._hotkey_status = QLabel(wordWrap=True, objectName="hint")
        self._hotkey_feedback = QLabel(wordWrap=True, objectName="hint")
        rows.addWidget(self._hotkey_status)
        rows.addWidget(self._hotkey_feedback)
        rows.addSpacing(16)
        rows.addWidget(QLabel("截图窗口快捷键", objectName="section"))
        rows.addWidget(QLabel("框选完成后使用；同一功能可设置多个按键。", objectName="hint"))
        for key, command in self._shortcut_definitions.items():
            rows.addWidget(self._shortcut_row(key, command.label))
        rows.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        self._refresh_shortcut_buttons()
        return page

    def _shortcut_row(self, key: str, label: str) -> QWidget:
        card = ShortcutCard()
        row = QHBoxLayout(card)
        row.setContentsMargins(18, 10, 18, 10)
        row.addWidget(QLabel(label), 1)
        button = PushButton()
        button.setAccessibleName(f"配置{label}快捷键")
        button.clicked.connect(lambda: self._edit_shortcuts(key, label))
        row.addWidget(button)
        self._shortcut_buttons[key] = button
        return card

    def _refresh_shortcut_buttons(self) -> None:
        self._shortcut_buttons["capture"].setText(self.saved_hotkey())
        for key, command in self._shortcut_definitions.items():
            values = load_shortcuts(self.settings, key, command.keys)
            self._shortcut_buttons[key].setText("  /  ".join(values) if values else "未设置")

    def _edit_shortcuts(self, key: str, label: str) -> None:
        is_global = key == "capture"
        values = (self.saved_hotkey(),) if is_global else load_shortcuts(
            self.settings, key, self._shortcut_definitions[key].keys
        )
        dialog = ShortcutDialog(
            label, values, lambda keys: self._apply_shortcuts(key, keys), self, single=is_global
        )
        dialog.exec()
        self._refresh_shortcut_buttons()

    def _apply_shortcuts(self, key: str, values: tuple[str, ...]) -> str:
        if key == "capture":
            if len(values) != 1:
                return "全局截图需要设置一个快捷键。"
            requested = canonical_shortcut(values[0])
            for other, command in self._shortcut_definitions.items():
                if requested in load_shortcuts(self.settings, other, command.keys):
                    return f"该快捷键已用于截图窗口的“{command.label}”。"
            self._last_hotkey_error = ""
            self.hotkey_requested.emit(QKeySequence(values[0]))
            return self._last_hotkey_error

        normalized = [canonical_shortcut(value) for value in values]
        if any(not value for value in normalized):
            return "请输入有效的快捷键。"
        aliases = lambda value: "Enter" if value in ("Return", "Num+Enter") else value
        comparable = [aliases(value) for value in normalized]
        if aliases(canonical_shortcut(self.saved_hotkey())) in comparable:
            return "该快捷键已用于全局截图。"
        if len(set(comparable)) != len(comparable):
            return "存在重复的快捷键。"
        reserved = {"Del", "Alt+C", "[", "]", "Tab", "Up", "Down", "Left", "Right",
                    "Shift+Up", "Shift+Down", "Shift+Left", "Shift+Right"}
        if any(value in reserved or ("Esc" in value and key != "action/cancel") for value in normalized):
            return "该按键用于截图窗口的其他操作，请选择其他按键。"
        for other, command in self._shortcut_definitions.items():
            if other == key:
                continue
            existing = load_shortcuts(self.settings, other, command.keys)
            if set(comparable) & {aliases(canonical_shortcut(value)) for value in existing}:
                return f"该快捷键已用于“{command.label}”。"
        save_shortcuts(self.settings, key, tuple(normalized))
        if self.settings.status() != QSettings.Status.NoError:
            return "保存失败，请检查应用数据目录的写入权限。"
        return ""

    def _quick_capture_page(self) -> QWidget:
        page, layout = self._page("快速截图", "配置激活按键和鼠标拖动的快捷操作。")
        layout.addWidget(QLabel("快速截图", objectName="section"))
        layout.addWidget(QLabel("按住激活按键并拖动鼠标，松开后执行操作。", objectName="hint"))
        card = ShortcutCard()
        row = QHBoxLayout(card)
        row.setContentsMargins(18, 10, 18, 10)
        row.addWidget(QLabel("截图复制到剪贴板"), 1)
        self._quick_button = PushButton()
        self._quick_button.setAccessibleName("配置截图复制到剪贴板快捷键")
        self._quick_button.clicked.connect(self._edit_quick_capture)
        row.addWidget(self._quick_button)
        layout.addWidget(card)
        self._quick_status = QLabel(wordWrap=True, objectName="hint")
        layout.addWidget(self._quick_status)
        layout.addStretch()
        self._refresh_quick_capture()
        return page

    def _refresh_quick_capture(self) -> None:
        self._quick_button.setText(binding_label(load_quick_capture(self.settings)))

    def _edit_quick_capture(self) -> None:
        dialog = QuickCaptureDialog(load_quick_capture(self.settings), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        binding = dialog.binding()
        save_quick_capture(self.settings, binding)
        if self.settings.status() != QSettings.Status.NoError:
            self._quick_status.setText("保存失败，请检查应用数据目录的写入权限。")
            return
        self._refresh_quick_capture()
        self.quick_capture_changed.emit(binding)

    def _history_page(self) -> QWidget:
        page, layout = self._page("截图历史", "查看和管理已完成的截图。")
        self._history_page_widget = HistoryPage(self.history, page)
        self._history_page_widget.edit_requested.connect(self.history_edit_requested.emit)
        layout.addWidget(self._history_page_widget, 1)
        return page

    def _ocr_page(self) -> QWidget:
        page, layout = self._page("OCR 和翻译", "配置文字识别和翻译的默认行为。")
        card, content = self._card("文字识别", "使用本地 PP-OCRv6 Small 识别中英文，无需上传截图。")
        content.addWidget(QLabel("识别引擎：RapidOCR · ONNX Runtime"))
        layout.addWidget(card)
        card, content = self._card("翻译", "翻译时会将识别文字发送给所选翻译服务；可在截图中更改语言和模型。")
        self._language = ComboBox()
        for name, value in LANGUAGES:
            self._language.addItem(name, userData=value)
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
        card, content = self._card("DeepSeek", "使用 DeepSeek 翻译时，API Key 保存在 Windows 凭据管理器。")
        content.addWidget(QLabel(f"模型：{DEEPSEEK_MODEL}"))
        self._key = LineEdit()
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        self._key.setAccessibleName("DeepSeek API Key")
        self._key.setPlaceholderText("输入 API Key 以保存或替换")
        content.addWidget(self._key)
        row = QHBoxLayout()
        save = PrimaryPushButton("保存 Key")
        save.clicked.connect(self._save_key)
        remove = PushButton("移除 Key")
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
        page, layout = self._page("关于", "了解 E2S。")
        card = CardWidget()
        content = QVBoxLayout(card)
        content.setContentsMargins(28, 28, 28, 28)
        content.setSpacing(18)

        heading = QHBoxLayout()
        heading.setSpacing(18)
        icon = QLabel()
        icon.setObjectName("aboutIcon")
        icon.setPixmap(self.windowIcon().pixmap(72, 72))
        icon.setFixedSize(72, 72)
        heading.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        identity = QVBoxLayout()
        identity.setSpacing(5)
        identity.addWidget(QLabel("E2S", objectName="section"))
        identity.addWidget(QLabel("Easy to Shot", objectName="hint"))
        version = QLabel(f"版本 {__version__}")
        version.setObjectName("aboutVersion")
        identity.addWidget(version)
        heading.addLayout(identity)
        heading.addStretch()
        content.addLayout(heading)

        description = QLabel("轻松捕捉，记录灵感。", wordWrap=True)
        content.addWidget(description)
        details = QLabel("截图、标注、文字识别、翻译与录屏，让每一次捕捉更简单。", wordWrap=True)
        details.setObjectName("hint")
        content.addWidget(details)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def _change_page(self, index: int) -> None:
        self._pages.setCurrentIndex(index)
        self._navigation.setCurrentItem(("hotkey", "quick", "history", "ocr", "model", "about")[index])
        if index == 2:
            self.refresh_history()
        elif index == 4:
            self._update_key_status()

    def refresh_history(self) -> None:
        self._history_page_widget.refresh()

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
        self._change_page(0)
        self._shortcut_buttons["capture"].setFocus()

    def show_hotkey_state(self, state: HotkeyState) -> None:
        self._hotkey_status.setText(f"当前热键：{state.active}" if state.active else "当前未注册截图热键")
        self._last_hotkey_error = _HOTKEY_MESSAGES.get(state.error, "")
        self._hotkey_feedback.setText(self._last_hotkey_error)
        self._refresh_shortcut_buttons()
        if state.active and state.error is None:
            self.settings.setValue("hotkey/capture", state.active)


