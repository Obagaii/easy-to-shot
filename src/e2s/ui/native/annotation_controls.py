from collections.abc import Iterable

from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QIcon, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QSlider,
    QSpinBox,
    QToolButton,
    QWidget,
)

from e2s.ui.native.toolbar_icons import toolbar_icon

STROKE_COLORS = {
    "#1f1f1f": "黑色", "#f5222d": "红色", "#52c41a": "绿色",
    "#1677ff": "蓝色", "#faad14": "橙色",
}
FILL_COLORS = {
    "": "透明", "#6bff7875": "红色", "#6bb7eb8f": "绿色",
    "#6b69baff": "蓝色", "#6bffd666": "黄色",
}
CAPTURE_CONTROLS_STYLE = """
    QFrame[toolbarSurface="true"] {
        background: #ffffff; border: 1px solid #8ebaff; border-radius: 10px;
    }
    QToolButton {
        color: #1f1f1f; background: transparent; border: 1px solid transparent;
        border-radius: 6px; padding: 0;
    }
    QToolButton:hover { background: #f0f5ff; }
    QToolButton[toolButton="true"]:checked { background: #1677ff; color: #ffffff; }
    QToolButton:focus { border-color: #91caff; }
    QToolButton::menu-indicator { image: none; width: 0; }
    QToolButton[optionButton="true"] { border-color: #d9d9d9; }
    QToolButton[optionButton="true"]:checked {
        color: #1677ff; background: #ffffff; border-color: #1677ff;
    }
    QToolButton[segment="first"] { border-top-right-radius: 0; border-bottom-right-radius: 0; }
    QToolButton[segment="middle"] { border-radius: 0; }
    QToolButton[segment="last"] { border-top-left-radius: 0; border-bottom-left-radius: 0; }
    QToolButton#colorSwatch:checked, QToolButton#customSwatch { border-color: #d9d9d9; }
    QToolButton:disabled { color: #bfbfbf; }
    QLabel#styleLabel { color: #1f1f1f; font-size: 14px; font-family: "Microsoft YaHei UI"; }
    QScrollArea { background: transparent; border: none; }
    QScrollArea QWidget#styleSections { background: #ffffff; }
    QScrollBar:vertical { width: 5px; background: transparent; margin: 0; }
    QScrollBar::handle:vertical { background: #d2e4fd; min-height: 20px; border-radius: 2px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
    QSlider::groove:horizontal { background: #e8e8e8; height: 4px; border-radius: 2px; }
    QSlider::sub-page:horizontal { background: #91caff; border-radius: 2px; }
    QSlider::handle:horizontal {
        background: #ffffff; border: 2px solid #91caff; width: 12px;
        border-radius: 7px; margin: -5px 0;
    }
    QSpinBox, QLineEdit, QComboBox#colorFormat {
        color: #1f1f1f; background: #ffffff; border: 1px solid #d9d9d9;
        border-radius: 6px; padding: 3px 6px;
    }
    QSpinBox:focus, QLineEdit:focus, QComboBox#colorFormat:focus { border-color: #1677ff; }
    QLineEdit#colorComponent { padding: 2px; }
    QComboBox#colorFormat { padding: 2px 4px; }
    QComboBox#colorFormat::drop-down { border: 0; width: 15px; }
    QComboBox#colorFormat::down-arrow { image: none; }
    QComboBox#colorFormat QAbstractItemView {
        color: #1f1f1f; background: #ffffff; border: 1px solid #d9d9d9;
        selection-color: #1f1f1f; selection-background-color: #e6f4ff;
    }
    QMenu { background: #ffffff; border: 1px solid #e3e3e3; padding: 4px; }
    QMenu::item { color: #1f1f1f; padding: 4px 12px; }
    QMenu::item:selected { background: #e6f4ff; }
    QFrame#toolbarDivider { background: #d9d9d9; }
"""


def describe_control(button: QToolButton, label: str) -> None:
    button.setProperty("alt", label)
    button.setToolTip(label)
    button.setAccessibleName(label)
    button.setCursor(Qt.CursorShape.PointingHandCursor)


class PanelPosition(QObject):
    """Keep a draggable panel within its capture canvas."""

    moved = Signal()

    def __init__(self, panel: QWidget, handle: QToolButton) -> None:
        super().__init__(panel)
        self._panel = panel
        self._handle = handle
        self._drag_anchor: QPoint | None = None
        self._manual_position: QPoint | None = None
        handle.setCursor(Qt.CursorShape.SizeAllCursor)
        handle.installEventFilter(self)

    def place(self, anchor: QPoint, bounds: QRect | None = None) -> None:
        if bounds is None or self._manual_position is not None:
            bounds = self._panel.parentWidget().rect()
        point = self._manual_position if self._manual_position is not None else anchor
        self._panel.move(
            max(bounds.x(), min(point.x(), bounds.right() + 1 - self._panel.width())),
            max(bounds.y(), min(point.y(), bounds.bottom() + 1 - self._panel.height())),
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._handle and isinstance(event, QMouseEvent):
            kind = event.type()
            if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_anchor = self._panel.mapFromGlobal(event.globalPosition().toPoint())
                self._handle.grabMouse()
                return True
            if self._drag_anchor is not None:
                if kind == QEvent.Type.MouseMove:
                    pointer = event.globalPosition().toPoint()
                    self._manual_position = self._panel.parentWidget().mapFromGlobal(pointer)
                    self._manual_position -= self._drag_anchor
                    self.place(self._manual_position)
                    self.moved.emit()
                    return True
                if kind == QEvent.Type.MouseButtonRelease:
                    self._drag_anchor = None
                    self._handle.releaseMouse()
                    return True
        return super().eventFilter(watched, event)


class ColorControl(QFrame):
    color_changed = Signal(str)
    custom_requested = Signal(bool)

    def __init__(self, name: str, parent: QWidget, *, optional: bool = False) -> None:
        super().__init__(parent)
        self.setAccessibleName(name)
        self._color = ""
        self._presets: dict[str, QToolButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        for color, label in (FILL_COLORS if optional else STROKE_COLORS).items():
            button = QToolButton(self)
            button.setObjectName("colorSwatch")
            button.setCheckable(True)
            button.setFixedSize(29, 29)
            button.setIconSize(QSize(21, 21))
            button.setIcon(_swatch(color, show_alpha=False))
            describe_control(button, f"{name} · {label}")
            button.clicked.connect(lambda _checked=False, color=color: self._choose_preset(color))
            self._group.addButton(button)
            self._presets[color] = button
            layout.addWidget(button)
        divider = QFrame(self)
        divider.setObjectName("toolbarDivider")
        divider.setFixedSize(1, 18)
        layout.addSpacing(4)
        layout.addWidget(divider, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addSpacing(4)
        self._custom = QToolButton(self)
        self._custom.setObjectName("customSwatch")
        self._custom.setFixedSize(32, 32)
        self._custom.setIconSize(QSize(23, 23))
        describe_control(self._custom, f"自定义{name}与透明度")
        self._hover_timer = QTimer(self, singleShot=True, interval=180)
        self._custom.clicked.connect(self._open_custom)
        self._hover_timer.timeout.connect(lambda: self.custom_requested.emit(False))
        self._custom.installEventFilter(self)
        layout.addWidget(self._custom)
        self.set_color("")

    def set_color(self, color: str) -> None:
        changed = color != self._color
        self._color = color
        self.preview_color(color)
        for value, button in self._presets.items():
            matches = color == value
            if color and value and QColor(value).alpha() == 255:
                matches = QColor(color).name() == value
            button.setChecked(matches)
        if changed:
            self.color_changed.emit(color)

    def _choose_preset(self, color: str) -> None:
        if color and color in STROKE_COLORS and self._color:
            chosen = QColor(color)
            chosen.setAlpha(QColor(self._color).alpha())
            color = color_name(chosen)
        self.set_color(color)

    @property
    def custom_button(self) -> QToolButton:
        return self._custom

    @property
    def color(self) -> str:
        return self._color

    def preview_color(self, value: str) -> None:
        self._custom.setIcon(_swatch(value))

    def set_qcolor(self, color: QColor) -> None:
        self.set_color(color_name(color))

    def _open_custom(self) -> None:
        self._hover_timer.stop()
        self.custom_requested.emit(True)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._custom and event.type() == QEvent.Type.Enter:
            self._hover_timer.start()
        elif watched is self._custom and event.type() in (QEvent.Type.Leave, QEvent.Type.Hide):
            self._hover_timer.stop()
        return super().eventFilter(watched, event)


class SizeControl(QSpinBox):
    def __init__(
        self, name: str, minimum: int, maximum: int, suffix: str, parent: QWidget
    ) -> None:
        super().__init__(parent)
        self.setAccessibleName(name)
        self.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setRange(minimum, maximum)
        self.setSuffix(suffix)
        self.setFixedSize(94, 34)
        self.setToolTip(f"{name}（滚轮调整）")
        self.setKeyboardTracking(False)

    def set_value(self, value: int) -> None:
        self.setValue(value)

    def step(self, increase: bool) -> None:
        self.stepBy(1 if increase else -1)


class ModeControl(QFrame):
    value_changed = Signal(object)

    def __init__(
        self, name: str, choices: dict[str | int, tuple[str, str]], parent: QWidget,
        *, exclusive: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setAccessibleName(name)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._group = QButtonGroup(self)
        self._group.setExclusive(exclusive)
        self._buttons: dict[str | int, QToolButton] = {}
        for index, (value, (label, icon)) in enumerate(choices.items()):
            button = QToolButton(self)
            button.setFixedSize(39, 38)
            button.setIconSize(QSize(21, 21))
            button.setIcon(toolbar_icon(icon))
            button.setProperty("optionButton", True)
            if len(choices) > 1:
                segment = "first" if index == 0 else "last" if index == len(choices) - 1 else "middle"
                button.setProperty("segment", segment)
            describe_control(button, label)
            button.setCheckable(True)
            self._buttons[value] = button
            self._group.addButton(button)
            layout.addWidget(button)
            button.clicked.connect(lambda _checked=False, value=value: self.value_changed.emit(value))

    def set_value(self, value: str | int) -> None:
        button = self._buttons.get(value)
        if button is not None:
            button.setChecked(True)

    def set_checked_values(self, values: Iterable[str]) -> None:
        checked = set(values)
        for value, button in self._buttons.items():
            button.setChecked(value in checked)


class NumericPresets(ModeControl):
    def __init__(
        self, name: str, choices: dict[int, tuple[str, str]], minimum: int, maximum: int,
        parent: QWidget,
    ) -> None:
        super().__init__(name, choices, parent)
        self._value = minimum
        self._minimum = minimum
        self._maximum = maximum

    def set_value(self, value: int) -> None:
        self._value = value
        nearest = min(self._buttons, key=lambda choice: abs(choice - value))
        super().set_value(nearest)

    def step(self, increase: bool) -> None:
        value = max(self._minimum, min(self._maximum, self._value + (1 if increase else -1)))
        self.value_changed.emit(value)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta:
            self.step(delta > 0)
            event.accept()
        else:
            super().wheelEvent(event)


class OpacityControl(QSlider):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(0, 100)
        self.setTracking(False)
        self.setFixedHeight(34)
        self.setAccessibleName("透明度")

    def set_value(self, value: int) -> None:
        self.setValue(value)
        self.setToolTip(f"{value}%")


def color_name(color: QColor) -> str:
    return color.name(QColor.NameFormat.HexRgb if color.alpha() == 255 else QColor.NameFormat.HexArgb)


def _swatch(value: str, *, show_alpha: bool = True) -> QIcon:
    pixmap = QPixmap(48, 48)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    with QPainter(pixmap) as painter:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(1, 1, 22, 22)
        painter.setPen(Qt.PenStyle.NoPen)
        color = QColor(value) if value else QColor(Qt.GlobalColor.transparent)
        if not color.alpha() or (show_alpha and color.alpha() < 255):
            for row in range(4):
                for col in range(4):
                    shade = "#ffffff" if (row + col) % 2 else "#eeeeee"
                    painter.fillRect(QRectF(2 + col * 5, 2 + row * 5, 5, 5), QColor(shade))
        painter.setBrush(color)
        painter.drawRoundedRect(rect, 3, 3)
    return QIcon(pixmap)
