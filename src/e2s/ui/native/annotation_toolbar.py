from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QHBoxLayout,

    QToolButton,
    QVBoxLayout,
)

from e2s.annotation.elements import MAX_STROKE_WIDTH_PX, Tool
from e2s.ui.native.annotation_controls import ColorControl, SizeControl

_TOOLS = {
    Tool.SELECT: "选择",
    Tool.RECTANGLE: "矩形",
    Tool.ELLIPSE: "椭圆",
    Tool.LINE: "直线",
    Tool.ARROW: "箭头",
    Tool.PEN: "画笔",
}

_FILL_TOOLS = (Tool.RECTANGLE, Tool.ELLIPSE)


class AnnotationToolbar(QFrame):
    tool_changed = Signal(object)
    undo_requested = Signal()
    redo_requested = Signal()
    delete_requested = Signal()
    copy_requested = Signal()
    save_requested = Signal()

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setObjectName("annotationToolbar")
        self.setStyleSheet(
            """
            QFrame#annotationToolbar {
                background: #f4f6f9; border: 1px solid #9aa8b7; border-radius: 8px;
            }
            QToolButton {
                color: #182534; background: transparent;
                border: 1px solid transparent; border-radius: 4px; padding: 4px 6px;
            }
            QToolButton:hover { background: #e4ecf6; }
            QToolButton:checked, QToolButton#copyAnnotation:enabled { background: #cee2fc; }
            QToolButton:focus { border-color: #547db0; }
            QToolButton:disabled { color: #697787; }
            QToolButton#annotationColor, QFrame#annotationSize {
                background: #ffffff; border: 1px solid #cfdae7; border-radius: 6px;
            }
            QToolButton#annotationColor:hover { background: #e4ecf6; }
            QToolButton#annotationColor:focus { border-color: #547db0; }
            QToolButton#annotationColor::menu-indicator { image: none; width: 0; }
            QMenu#annotationPalette {
                color: #182534; background: #ffffff; border: 1px solid #cfdae7; padding: 4px;
            }
            QMenu#annotationPalette::item { padding: 5px 10px 5px 26px; }
            QMenu#annotationPalette::item:selected { background: #e4ecf6; }
            QFrame#annotationSize QLabel { color: #43566f; background: transparent; }
            QSpinBox#annotationSizeValue {
                color: #182534; background: #f4f6f9;
                border: 1px solid transparent; border-radius: 4px; padding: 1px 0;
            }
            QSpinBox#annotationSizeValue:focus { border-color: #547db0; }
            QToolButton#annotationStep { padding: 0; font-weight: bold; }
            QToolButton#annotationDelete:enabled { color: #a8313e; }
            QToolButton#annotationDelete:enabled:hover { background: #fde9eb; }
            QCheckBox { color: #182534; background: transparent; }
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 5, 7, 5)
        layout.setSpacing(3)
        tools = QHBoxLayout()
        options = QHBoxLayout()
        tools.setSpacing(3)
        options.setSpacing(5)
        layout.addLayout(tools)
        layout.addLayout(options)
        self._tools = QButtonGroup(self)
        self._buttons = {}
        for tool, label in _TOOLS.items():
            button = self._add_button(tools, label)
            button.setCheckable(True)
            self._tools.addButton(button)
            button.clicked.connect(lambda checked, tool=tool: self.tool_changed.emit(tool))
            self._buttons[tool] = button
        tools.addStretch(1)
        self._undo = self._add_button(tools, "撤销", self.undo_requested, "Ctrl+Z")
        self._redo = self._add_button(tools, "重做", self.redo_requested, "Ctrl+Shift+Z")
        self._delete = self._add_button(tools, "删除", self.delete_requested, "Delete")
        self._delete.setObjectName("annotationDelete")
        self._delete.setEnabled(False)

        self._color = ColorControl(self)
        options.addWidget(self._color)

        self._width = SizeControl("笔宽", 1, MAX_STROKE_WIDTH_PX, 4, self)
        options.addWidget(self._width)
        self._fill = QCheckBox("填充", self)
        options.addWidget(self._fill)
        options.addStretch(1)
        self._copy = self._add_button(options, "复制", self.copy_requested, "Ctrl+C")
        self._copy.setObjectName("copyAnnotation")
        self._save = self._add_button(options, "另存", self.save_requested, "Ctrl+S")
        self.set_tool(Tool.SELECT)
        self.set_history(False, False)

    @property
    def color(self) -> str:
        return self._color.color

    @property
    def width_px(self) -> int:
        return self._width.value

    @property
    def is_filled(self) -> bool:
        return self._fill.isChecked()

    def set_tool(self, tool: Tool) -> None:
        self._buttons[tool].setChecked(True)
        is_stroke = tool in (Tool.RECTANGLE, Tool.ELLIPSE, Tool.LINE, Tool.ARROW, Tool.PEN)
        self._color.setVisible(is_stroke)
        self._width.setVisible(is_stroke)
        self._fill.setVisible(tool in _FILL_TOOLS)

    def set_element_selected(self, is_selected: bool) -> None:
        self._delete.setEnabled(is_selected)

    def set_history(self, can_undo: bool, can_redo: bool) -> None:
        self._undo.setEnabled(can_undo)
        self._redo.setEnabled(can_redo)

    def _add_button(self, layout: QHBoxLayout, text: str, signal=None, shortcut="") -> QToolButton:
        button = QToolButton(self)
        button.setText(text)
        if shortcut:
            button.setToolTip(f"{text}（{shortcut}）")
        if signal is not None:
            button.clicked.connect(signal)
        layout.addWidget(button)
        return button
