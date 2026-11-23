from collections.abc import Callable

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QActionGroup, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QSpinBox, QToolButton, QWidget

_COLORS = {
    "#e53935": "红色",
    "#fb8c00": "橙色",
    "#fdd835": "黄色",
    "#43a047": "绿色",
    "#1e88e5": "蓝色",
    "#8e24aa": "紫色",
    "#ffffff": "白色",
    "#15191f": "黑色",
}


class ColorControl(QToolButton):
    color_changed = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("annotationColor")
        self.setAccessibleName("颜色")
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setIconSize(QSize(14, 14))
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self)
        menu.setObjectName("annotationPalette")
        group = QActionGroup(menu)
        self._actions = {}
        self._color = ""
        for color, label in _COLORS.items():
            action = menu.addAction(_swatch(color), label)
            action.setCheckable(True)
            group.addAction(action)
            action.triggered.connect(lambda _checked, value=color: self.set_color(value))
            self._actions[color] = action
        self.setMenu(menu)
        self.set_color(next(iter(_COLORS)))

    @property
    def color(self) -> str:
        return self._color

    def set_color(self, color: str) -> None:
        if color == self._color or color not in self._actions:
            return
        self._color = color
        action = self._actions[color]
        action.setChecked(True)
        self.setIcon(action.icon())
        self.setText(f"{action.text()}  ▾")
        self.color_changed.emit()


class SizeControl(QFrame):
    value_changed = Signal(int)

    def __init__(self, name: str, minimum: int, maximum: int, value: int, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("annotationSize")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 1, 2, 1)
        layout.setSpacing(2)
        label = QLabel(name, self)
        layout.addWidget(label)

        self._spin = QSpinBox(self)
        self._spin.setObjectName("annotationSizeValue")
        self._spin.setAccessibleName(name)
        self._spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self._spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spin.setRange(minimum, maximum)
        self._spin.setValue(value)
        self._spin.setSuffix(" px")
        self._spin.setFixedWidth(56)
        label.setBuddy(self._spin)
        layout.addWidget(self._spin)

        self._decrease = self._add_step_button("−", f"减小{name}", self._spin.stepDown)
        self._increase = self._add_step_button("+", f"增大{name}", self._spin.stepUp)
        layout.addWidget(self._decrease)
        layout.addWidget(self._increase)
        self._spin.valueChanged.connect(self._value_changed)
        self._value_changed(value)

    @property
    def value(self) -> int:
        return self._spin.value()

    def set_value(self, value: int) -> None:
        self._spin.setValue(value)

    def _add_step_button(self, text: str, label: str, step: Callable[[], None]) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("annotationStep")
        button.setText(text)
        button.setAccessibleName(label)
        button.setToolTip(label)
        button.setFixedSize(24, 24)
        button.setAutoRepeat(True)
        button.clicked.connect(step)
        return button

    def _value_changed(self, value: int) -> None:
        self._decrease.setEnabled(value > self._spin.minimum())
        self._increase.setEnabled(value < self._spin.maximum())
        self.value_changed.emit(value)


def _swatch(color: str) -> QIcon:
    pixmap = QPixmap(28, 28)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    with QPainter(pixmap) as painter:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#253953"), 1))
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(QRectF(1, 1, 12, 12), 4, 4)
    return QIcon(pixmap)
