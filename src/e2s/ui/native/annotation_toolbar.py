from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QToolButton, QVBoxLayout, QWidget

from e2s.annotation.elements import ERASER_TOOLS, HIGHLIGHT_TOOLS, Tool
from e2s.ui.native.annotation_controls import (
    CAPTURE_CONTROLS_STYLE,
    PanelPosition,
    describe_control,
)
from e2s.ui.native.toolbar_icons import toolbar_icon
from e2s.storage.shortcuts import load_shortcuts, shortcut_settings


@dataclass(frozen=True, slots=True)
class Command:
    label: str
    keys: tuple[str, ...]


_TOOL_COMMANDS = {
    Tool.MOVE: Command("移动", ("M", "Ctrl+E")),
    Tool.SELECT: Command("选择", ("V",)),
    Tool.RECTANGLE: Command("矩形", ("1",)),
    Tool.ELLIPSE: Command("椭圆", ("Shift+1",)),
    Tool.ARROW: Command("箭头", ("2",)),
    Tool.PEN: Command("画笔", ("3", "P")),
    Tool.TEXT: Command("文字", ("5", "T")),
    Tool.WATERMARK: Command("水印", ("9",)),
    Tool.RECT_HIGHLIGHT: Command("高亮", ("4", "H")),
    Tool.ERASER: Command("橡皮擦", ("8", "E")),
}
_ACTION_COMMANDS = {
    "undo": Command("撤销", ("Ctrl+Z",)),
    "redo": Command("重做", ("Ctrl+Y",)),
    "ocr": Command("识别文字", ("Ctrl+O",)),
    "barcode": Command("扫描二维码", ("Ctrl+Q",)),
    "record": Command("录像", ("Ctrl+R",)),
    "pin": Command("固定到屏幕", ("Ctrl+F",)),
    "scroll": Command("滚动截图", ("L",)),
    "save": Command("保存为文件", ("Ctrl+S",)),
    "cancel": Command("取消", ("Esc",)),
    "copy": Command("复制到剪贴板", ("Ctrl+C", "Enter")),
}
_GROUPS = (
    (Tool.MOVE, Tool.SELECT),
    (Tool.RECTANGLE, Tool.ELLIPSE, Tool.ARROW, Tool.PEN, Tool.TEXT, Tool.WATERMARK,
     Tool.RECT_HIGHLIGHT, Tool.ERASER),
    ("undo", "redo"),
    ("ocr", "barcode", "record", "pin", "scroll", "save"),
    ("cancel", "copy"),
)
_RECORDING_GROUPS = (
    (Tool.SELECT, Tool.RECTANGLE, Tool.ELLIPSE, Tool.ARROW, Tool.PEN, Tool.TEXT,
     Tool.RECT_HIGHLIGHT, Tool.ERASER),
    ("undo", "redo"),
    ("cancel",),
)
_FAMILIES = (HIGHLIGHT_TOOLS, ERASER_TOOLS)
_PRIMARY = {tool: group[0] for group in _FAMILIES for tool in group}

_BUTTON_SIZE = 38
_MARGINS = 7
_BUTTON_GAP = 4
_SEPARATOR_WIDTH = 8


def describe_button(button: QToolButton, command: Command) -> None:
    hint = f"{command.label}（{' / '.join(command.keys)}）" if command.keys else command.label
    describe_control(button, hint)
    button.setAccessibleName(command.label)
    button.setAccessibleDescription(hint)


class AnnotationToolbar(QFrame):
    tool_changed = Signal(object)
    action_requested = Signal(str)

    def __init__(self, parent: QWidget, *, recording: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("annotationToolbar")
        self.setProperty("toolbarSurface", True)
        self.setAccessibleName("录像标注工具栏" if recording else "截图工具栏")
        self._groups = _RECORDING_GROUPS if recording else _GROUPS
        self._recording = recording
        self._shortcut_settings = shortcut_settings()
        self.setStyleSheet(CAPTURE_CONTROLS_STYLE)
        self._rows = QVBoxLayout(self)
        self._rows.setContentsMargins(_MARGINS, 5, _MARGINS, 5)
        self._rows.setSpacing(2)

        self._drag_handle = QToolButton(self)
        self._drag_handle.setIcon(toolbar_icon("drag_handle"))
        self._drag_handle.setIconSize(QSize(18, 22))
        self._drag_handle.setFixedSize(17, _BUTTON_SIZE)
        describe_control(self._drag_handle, "拖动工具栏")
        self.position = PanelPosition(self, self._drag_handle)
        self._main_buttons: list[QWidget] = [self._drag_handle]
        self._buttons: dict[Tool, QToolButton] = {}
        self._action_buttons: dict[str, QToolButton] = {}
        self._variants = {group[0]: group[0] for group in _FAMILIES}
        for index, group in enumerate(self._groups):
            if index:
                self._main_buttons.append(self._separator())
            for item in group:
                self._main_buttons.append(self._button(item))
        if not recording:
            self._action_buttons["copy"].setObjectName("copyAnnotation")
        self._available_width = 0
        self.set_tool(Tool.SELECT if recording else Tool.MOVE)
        self.set_history(False, False)

    @property
    def preferred_width(self) -> int:
        buttons = len(self._buttons) + len(self._action_buttons)
        return (
            2 * _MARGINS + self._drag_handle.width() + buttons * _BUTTON_SIZE
            + (len(self._groups) - 1) * _SEPARATOR_WIDTH
            + (len(self._main_buttons) - 1) * _BUTTON_GAP
        )

    def shortcuts(self) -> list[tuple[tuple[str, ...], Callable[[], None]]]:
        tools = [
            (self._keys(f"tool/{tool.value}", command), lambda tool=tool: self.activate_tool(tool))
            for tool, command in _TOOL_COMMANDS.items() if tool in self._buttons
        ]
        actions = [
            (self._keys(f"action/{name}", command), self._action_buttons[name].click)
            for name, command in _ACTION_COMMANDS.items() if name in self._action_buttons
        ]
        return [*tools, *actions]

    def _keys(self, name: str, command: Command) -> tuple[str, ...]:
        return command.keys if self._recording else load_shortcuts(
            self._shortcut_settings, name, command.keys
        )

    def activate_tool(self, tool: Tool) -> None:
        self.tool_changed.emit(self._variants.get(tool, tool))

    def set_tool(self, tool: Tool) -> None:
        primary = _PRIMARY.get(tool, tool)
        if primary in self._variants:
            self._variants[primary] = tool
            self._buttons[primary].setIcon(toolbar_icon(tool.value, primary=True))
        for group, button in self._buttons.items():
            button.setChecked(group is primary)

    def set_history(self, can_undo: bool, can_redo: bool) -> None:
        self._action_buttons["undo"].setEnabled(can_undo)
        self._action_buttons["redo"].setEnabled(can_redo)

    def fit_to_width(self, width: int) -> None:
        if width == self._available_width:
            return
        self._available_width = width
        while self._rows.count():
            row = self._rows.takeAt(0).layout()
            while row.count():
                row.takeAt(0)
            row.deleteLater()
        inner_width = max(24, width - 2 * _MARGINS)
        buttons = len(self._buttons) + len(self._action_buttons)
        size = max(26, _BUTTON_SIZE - max(0, self.preferred_width - width + buttons - 1) // buttons)
        row = self._add_row()
        span = 0
        for widget in self._main_buttons:
            if isinstance(widget, QToolButton) and widget is not self._drag_handle:
                widget.setFixedSize(size, size)
                widget.setIconSize(QSize(size - 10, size - 10))
            advance = widget.width() + (_BUTTON_GAP if row.count() else 0)
            if span + advance > inner_width and row.count():
                row = self._add_row()
                span = 0
                advance = widget.width()
            row.addWidget(widget, alignment=Qt.AlignmentFlag.AlignVCenter)
            span += advance
        self._rows.invalidate()
        self.resize(self.sizeHint())
        self._rows.activate()

    def _add_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(_BUTTON_GAP)
        row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._rows.addLayout(row)
        return row

    def _separator(self) -> QFrame:
        holder = QFrame(self)
        holder.setFixedSize(_SEPARATOR_WIDTH, 24)
        line = QFrame(holder)
        line.setObjectName("toolbarDivider")
        line.setGeometry(_SEPARATOR_WIDTH // 2, 5, 1, 14)
        return holder

    def _button(self, item: Tool | str) -> QToolButton:
        button = QToolButton(self)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if isinstance(item, Tool):
            button.setProperty("toolButton", True)
            button.setIcon(toolbar_icon(item.value, primary=True))
            button.setCheckable(True)
            button.clicked.connect(lambda: self.activate_tool(item))
            command = _TOOL_COMMANDS[item]
            describe_button(button, Command(command.label, self._keys(f"tool/{item.value}", command)))
            self._buttons[item] = button
        else:
            button.setIcon(toolbar_icon(item))
            button.clicked.connect(lambda: self.action_requested.emit(item))
            command = _ACTION_COMMANDS[item]
            command = Command(command.label, self._keys(f"action/{item}", command))
            if self._recording and item == "cancel":
                command = Command("返回桌面操作", command.keys)
            describe_button(button, command)
            self._action_buttons[item] = button
        return button
