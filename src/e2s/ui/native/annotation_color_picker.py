from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSignalBlocker,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QHideEvent,
    QIntValidator,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from e2s.ui.native.toolbar_icons import toolbar_icon

_PICKER_WIDTH = 258
_GAP = 6
_HUES = ("#ff0000", "#ffff00", "#00ff00", "#00ffff", "#0000ff", "#ff00ff", "#ff0000")
_FORMATS = {"HEX": ("HEX",), "RGB": ("红", "绿", "蓝"), "HSB": ("色相", "饱和度", "亮度")}


class SaturationField(QWidget):
    changed = Signal(float, float)
    finished = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedHeight(160)
        self.setAccessibleName("饱和度和亮度")
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._values = (0.0, 0.0, 1.0)

    def set_hsv(self, hue: float, saturation: float, brightness: float) -> None:
        self._values = hue, saturation, brightness
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        hue, saturation, brightness = self._values
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            clip = QPainterPath()
            clip.addRoundedRect(rect, 6, 6)
            painter.setClipPath(clip)
            color = QLinearGradient(rect.topLeft(), rect.topRight())
            color.setColorAt(0, QColor("#ffffff"))
            color.setColorAt(1, QColor.fromHsvF(hue, 1, 1))
            painter.fillRect(rect, color)
            shade = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            shade.setColorAt(0, QColor(0, 0, 0, 0))
            shade.setColorAt(1, QColor("#000000"))
            painter.fillRect(rect, shade)
            painter.setClipping(False)
            cursor = QPointF(
                max(6, min(rect.right() - 5, rect.left() + rect.width() * saturation)),
                max(6, min(rect.bottom() - 5, rect.top() + rect.height() * (1 - brightness))),
            )
            painter.setBrush(QColor.fromHsvF(hue, saturation, brightness))
            painter.setPen(QPen(QColor("#474747"), 3))
            painter.drawEllipse(cursor, 5, 5)
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.drawEllipse(cursor, 5, 5)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._update_from_pointer(event.position())
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._update_from_pointer(event.position())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._update_from_pointer(event.position())
            self.finished.emit()
            event.accept()

    def _update_from_pointer(self, point: QPointF) -> None:
        saturation = max(0.0, min(1.0, (point.x() - 1) / max(1, self.width() - 2)))
        brightness = 1 - max(0.0, min(1.0, (point.y() - 1) / max(1, self.height() - 2)))
        self.changed.emit(saturation, brightness)


class GradientSlider(QSlider):
    def __init__(self, name: str, maximum: int, parent: QWidget, *, alpha: bool = False) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setAccessibleName(name)
        self.setToolTip(name)
        self.setRange(0, maximum)
        self.setFixedHeight(16)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._alpha = alpha
        self._color = QColor("#ffffff")

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        track = QRectF(6, 3, self.width() - 12, self.height() - 6)
        if track.width() <= 0:
            return
        fraction = self.value() / self.maximum()
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            clip = QPainterPath()
            clip.addRoundedRect(track, track.height() / 2, track.height() / 2)
            painter.setClipPath(clip)
            gradient = QLinearGradient(track.topLeft(), track.topRight())
            if self._alpha:
                for row in range(2):
                    for col in range(0, round(track.width()) + 5, 5):
                        shade = "#d9d9d9" if (row + col // 5) % 2 else "#ffffff"
                        painter.fillRect(QRectF(track.x() + col, track.y() + row * 5, 5, 5), shade)
                end = self._color.toRgb()
                start = QColor(end)
                start.setAlpha(0)
                end.setAlpha(255)
                gradient.setColorAt(0, start)
                gradient.setColorAt(1, end)
                knob = QColor(end)
                knob.setAlpha(self.value())
            else:
                for index, color in enumerate(_HUES):
                    gradient.setColorAt(index / (len(_HUES) - 1), QColor(color))
                knob = QColor.fromHsv(self.value(), 255, 255)
            painter.fillRect(track, gradient)
            painter.setClipping(False)
            painter.setBrush(knob)
            painter.setPen(QPen(QColor("#1677ff" if self.hasFocus() else "#777777"), 2.5))
            center = QPointF(track.left() + fraction * track.width(), track.center().y())
            painter.drawEllipse(center, 5.5, 5.5)
            painter.setPen(QPen(QColor("#ffffff"), 1.5))
            painter.drawEllipse(center, 5.5, 5.5)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setSliderDown(True)
            self._update_from_pointer(event.position().x())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.isSliderDown():
            self._update_from_pointer(event.position().x())
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            self._update_from_pointer(event.position().x())
            self.setSliderDown(False)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def _update_from_pointer(self, x: float) -> None:
        fraction = max(0.0, min(1.0, (x - 6) / max(1, self.width() - 12)))
        self.setValue(round(fraction * self.maximum()))


class ColorFormatCombo(QComboBox):
    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        center = QPointF(self.width() - 11, self.height() / 2)
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor("#595959"), 1.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(center + QPointF(-3, -1), center + QPointF(0, 2))
            painter.drawLine(center + QPointF(0, 2), center + QPointF(3, -1))


class AnnotationColorPicker(QFrame):
    """A shared color editor anchored to a swatch inside the capture widget."""

    color_previewed = Signal(QColor)
    color_committed = Signal(QColor)
    sample_requested = Signal()
    closed = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("annotationColorPicker")
        self.setProperty("toolbarSurface", True)
        self.setAccessibleName("自由颜色")
        self.setFixedWidth(_PICKER_WIDTH)
        self.setMouseTracking(True)
        self._anchor: QWidget | None = None
        self._sidebar: QWidget | None = None
        self._sticky = False
        self._color = QColor("#ffffff")
        self._committed = QColor(self._color)
        self._hue = 0.0
        self._dismiss_timer = QTimer(self, singleShot=True, interval=220)
        self._dismiss_timer.timeout.connect(self._dismiss_if_pointer_left)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(9)
        self._saturation = SaturationField(self)
        self._saturation.changed.connect(self._change_saturation)
        self._saturation.finished.connect(self._commit)
        layout.addWidget(self._saturation)

        tracks = QVBoxLayout()
        tracks.setSpacing(2)
        self._hue_slider = GradientSlider("色相", 359, self)
        self._alpha_slider = GradientSlider("透明度", 255, self, alpha=True)
        for track in (self._hue_slider, self._alpha_slider):
            tracks.addWidget(track)
            track.valueChanged.connect(lambda _value, track=track: self._update_sliders(track))
            track.sliderReleased.connect(self._commit)
        self._sample = QToolButton(self)
        self._sample.setProperty("optionButton", True)
        self._sample.setIcon(toolbar_icon("eyedropper"))
        self._sample.setAccessibleName("从画布取色")
        self._sample.setToolTip("从画布取色")
        self._sample.setFixedSize(34, 34)
        self._sample.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sample.clicked.connect(self.sample_requested)
        track_row = QHBoxLayout()
        track_row.setSpacing(8)
        track_row.addLayout(tracks, 1)
        track_row.addWidget(self._sample)
        layout.addLayout(track_row)

        self._format = ColorFormatCombo(self)
        self._format.setAccessibleName("颜色格式")
        self._format.setObjectName("colorFormat")
        self._format.setFixedSize(63, 28)
        self._format.setCursor(Qt.CursorShape.PointingHandCursor)
        self._format.addItems(_FORMATS)
        self._format.currentTextChanged.connect(self._sync_fields)
        self._alpha_value = QSpinBox(self)
        self._alpha_value.setAccessibleName("颜色透明度百分比")
        self._alpha_value.setRange(0, 100)
        self._alpha_value.setSuffix("%")
        self._alpha_value.setFixedSize(51, 28)
        self._alpha_value.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self._alpha_value.setKeyboardTracking(False)
        self._alpha_value.valueChanged.connect(self._change_percent)
        self._fields: dict[str, list[QLineEdit]] = {}
        self._field_stack = QStackedWidget(self)
        self._field_stack.setFixedHeight(28)
        for mode, labels in _FORMATS.items():
            row_widget = QWidget(self._field_stack)
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(3)
            self._fields[mode] = []
            for index, label in enumerate(labels):
                field = QLineEdit(row_widget)
                field.setObjectName("colorComponent")
                field.setAccessibleName(label)
                field.setToolTip(label)
                field.setAlignment(Qt.AlignmentFlag.AlignCenter)
                field.setMinimumWidth(0)
                maximum = 255 if mode == "RGB" else (359 if index == 0 else 100)
                if mode == "HEX":
                    field.setMaxLength(7)
                else:
                    field.setValidator(QIntValidator(0, maximum, field))
                    field.setMaxLength(3)
                field.editingFinished.connect(self._apply_fields)
                self._fields[mode].append(field)
                row.addWidget(field)
            self._field_stack.addWidget(row_widget)
        input_row = QHBoxLayout()
        input_row.setSpacing(5)
        input_row.addWidget(self._format)
        input_row.addWidget(self._field_stack, 1)
        input_row.addWidget(self._alpha_value)
        layout.addLayout(input_row)
        self.hide()

    @property
    def anchor(self) -> QWidget | None:
        return self._anchor

    def open_at(self, anchor: QWidget, sidebar: QWidget, value: str, *, sticky: bool) -> None:
        if self._anchor is anchor and self.isVisible():
            self._sticky |= sticky
            return
        self.hide()
        self._anchor, self._sidebar = anchor, sidebar
        self._sticky = sticky
        self._format.hidePopup()
        self._committed = QColor(value) if value else QColor()
        color = self._committed if self._committed.isValid() else QColor("#ffffff")
        self._hue = max(0.0, color.hsvHueF())
        self._set_color(color)
        self.adjustSize()
        self.reposition()
        QApplication.instance().installEventFilter(self)
        self.show()
        self.raise_()

    def reposition(self) -> None:
        if self._anchor is None or self._sidebar is None:
            return
        parent = self.parentWidget()
        margin = parent.rect().adjusted(_GAP, _GAP, -_GAP, -_GAP)
        source = QRect(parent.mapFromGlobal(self._anchor.mapToGlobal(QPoint())), self._anchor.size())
        side = self._sidebar.geometry()
        left = side.left() - self.width() - _GAP
        right = side.right() + 1 + _GAP
        y = source.top()
        if left >= margin.left() and side.center().x() >= parent.rect().center().x():
            x = left
        elif right + self.width() <= margin.right() + 1:
            x = right
        elif left >= margin.left():
            x = left
        else:
            x = source.right() + 1 - self.width()
            y = source.bottom() + 1 + _GAP
            if y + self.height() > margin.bottom() + 1:
                y = source.top() - self.height() - _GAP
        self.move(
            max(margin.left(), min(x, margin.right() + 1 - self.width())),
            max(margin.top(), min(y, margin.bottom() + 1 - self.height())),
        )
        self.raise_()

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        self._dismiss_timer.stop()
        QApplication.instance().removeEventFilter(self)
        if self._anchor is not None:
            self._anchor, self._sidebar = None, None
            self._format.hidePopup()
            self.closed.emit()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if self._anchor is None or not self.isVisible():
            return False
        kind = event.type()
        if kind in (QEvent.Type.Enter, QEvent.Type.Leave) and watched in (self, self._anchor):
            if kind == QEvent.Type.Enter:
                self._dismiss_timer.stop()
            elif not self._sticky:
                self._dismiss_timer.start()
        elif kind == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            dropdown = self._format.view()
            position = event.globalPosition().toPoint()
            inside_picker = self.rect().contains(self.mapFromGlobal(position))
            inside_anchor = self._anchor.rect().contains(self._anchor.mapFromGlobal(position))
            inside_options = dropdown.isVisible() and dropdown.rect().contains(
                dropdown.mapFromGlobal(position)
            )
            if inside_picker or inside_options:
                self._sticky = True
            elif not inside_anchor:
                focus = QApplication.focusWidget()
                if focus is not None and self.isAncestorOf(focus):
                    focus.clearFocus()
                self.hide()
        elif kind in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            if event.key() == Qt.Key.Key_Escape and not self._format.view().isVisible():
                if kind == QEvent.Type.KeyPress:
                    if self._committed.isValid():
                        self._set_color(self._committed)
                    self.hide()
                event.accept()
                return True
            focus = QApplication.focusWidget()
            if kind == QEvent.Type.ShortcutOverride and focus is not None and self.isAncestorOf(focus):
                event.accept()
                return True
        return False

    def _dismiss_if_pointer_left(self) -> None:
        if self._anchor is not None and not self._sticky:
            point = QCursor.pos()
            if not (
                self.rect().contains(self.mapFromGlobal(point))
                or self._anchor.rect().contains(self._anchor.mapFromGlobal(point))
            ):
                self.hide()

    def _sync_fields(self) -> None:
        mode = self._format.currentText()
        self._field_stack.setCurrentIndex(self._format.currentIndex())
        if mode == "HEX":
            values = (self._color.name().upper(),)
        elif mode == "RGB":
            values = self._color.getRgb()[:3]
        else:
            values = (self._hue_slider.value(), round(self._color.hsvSaturationF() * 100),
                      round(self._color.valueF() * 100))
        for field, value in zip(self._fields[mode], values, strict=True):
            text = str(value)
            if field.text() != text:
                field.setText(text)
        with QSignalBlocker(self._alpha_value):
            self._alpha_value.setValue(round(self._color.alphaF() * 100))

    def _apply_fields(self) -> None:
        mode = self._format.currentText()
        fields = self._fields[mode]
        color = QColor()
        if mode == "HEX":
            text = fields[0].text().strip().removeprefix("#")
            if len(text) in (3, 6):
                color = QColor(f"#{text}")
        elif all(field.hasAcceptableInput() for field in fields):
            first, second, third = (int(field.text()) for field in fields)
            color = QColor.fromRgb(first, second, third) if mode == "RGB" else QColor.fromHsvF(
                first / 360, second / 100, third / 100
            )
        if color.isValid():
            color.setAlpha(self._color.alpha())
            self._set_color(color)
            self._commit()
        else:
            self._sync_fields()

    def _change_percent(self, value: int) -> None:
        color = QColor(self._color)
        color.setAlpha(round(value * 255 / 100))
        self._set_color(color)
        self._commit()

    def _change_saturation(self, saturation: float, brightness: float) -> None:
        self._set_color(QColor.fromHsvF(self._hue, saturation, brightness, self._color.alphaF()))
        self.color_previewed.emit(self._color)

    def _update_sliders(self, source: QSlider) -> None:
        color = QColor.fromHsvF(
            self._hue_slider.value() / 360, self._color.hsvSaturationF(), self._color.valueF(),
            self._alpha_slider.value() / 255,
        )
        self._set_color(color)
        if source.isSliderDown():
            self.color_previewed.emit(self._color)
        else:
            self._commit()

    def _set_color(self, color: QColor) -> None:
        self._color = color
        hue, saturation, brightness, _alpha = color.getHsvF()
        if hue >= 0:
            self._hue = hue
        self._saturation.set_hsv(self._hue, saturation, brightness)
        with QSignalBlocker(self._hue_slider), QSignalBlocker(self._alpha_slider):
            self._hue_slider.setValue(min(359, round(self._hue * 360)))
            self._alpha_slider.setValue(color.alpha())
        self._alpha_slider.set_color(color)
        self._sample.setStyleSheet(
            f"QToolButton {{ background-color: {color.name()}; }}"
            f"QToolButton:hover {{ border-color: #1677ff; background-color: {color.lighter(135).name()}; }}"
        )
        icon = "eyedropper_light" if color.lightness() < 120 else "eyedropper"
        self._sample.setIcon(toolbar_icon(icon))
        self._sync_fields()

    def _commit(self) -> None:
        if self._color.toRgb() != self._committed.toRgb():
            self._committed = QColor(self._color)
            self.color_committed.emit(self._color)
