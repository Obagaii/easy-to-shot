import base64
import json

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QEnterEvent, QPainter, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)
from qfluentwidgets import PushButton

from e2s.storage.history import HistoryItem, HistoryStore


def load_history_screen(store: HistoryStore, item: HistoryItem) -> QPixmap:
    image = QPixmap()
    try:
        metadata = json.loads(store.session_path(item).read_bytes())
        if metadata["version"] == 2:
            data = store.read_session_asset(item.history_item_id, metadata["image"])
        elif metadata["version"] == 1:
            data = base64.b64decode(metadata["image"], validate=True)
        else:
            return image
        image.loadFromData(data, "PNG")
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return image


class HistoryThumbnail(QAbstractButton):
    def __init__(self, image: QPixmap, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image = image
        self._hovered = False
        self.setObjectName("historyThumbnail")
        self.setAccessibleName("预览截图")
        self.setToolTip("点击预览图片" if not image.isNull() else "图片不可用")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(160, 100)
        self.setEnabled(not image.isNull())

    def enterEvent(self, event: QEnterEvent) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.fillRect(self.rect(), QColor("#edf1f7"))
            if self._image.isNull():
                painter.setPen(QColor("#718096"))
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "图片不可用")
                return
            size = self._image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            rect = QRectF((self.width() - size.width()) / 2, (self.height() - size.height()) / 2,
                          size.width(), size.height())
            painter.drawPixmap(rect, self._image, QRectF(self._image.rect()))
            if self._hovered:
                painter.fillRect(self.rect(), QColor(0, 0, 0, 120))
                painter.setPen(Qt.GlobalColor.white)
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "点击预览")


class _ImageView(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image = QPixmap()
        self.setMinimumSize(1, 1)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: #20242b; border-radius: 8px; color: white;")

    def set_image(self, image: QPixmap) -> None:
        self._image = image
        self._update_image()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_image()

    def _update_image(self) -> None:
        if self._image.isNull():
            self.setText("图片不可用")
            return
        available = self.contentsRect().size() - QSize(24, 24)
        if available.width() > 0 and available.height() > 0:
            self.setPixmap(self._image.scaled(available, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))


class HistoryPreview(QDialog):
    def __init__(self, result: QPixmap, screen: QPixmap, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("historyPreview")
        self.setWindowTitle("图片预览")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(960, 700)
        self.setMinimumSize(480, 360)
        self._result = result
        self._screen = screen
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self._result_button = PushButton("截图区域")
        self._screen_button = PushButton("整图")
        for button in (self._result_button, self._screen_button):
            button.setCheckable(True)
            button.setStyleSheet("QPushButton:checked { background: #1677ff; color: white; }")
            header.addWidget(button)
        group = QButtonGroup(self)
        group.addButton(self._result_button)
        group.addButton(self._screen_button)
        self._result_button.setChecked(True)
        self._screen_button.setEnabled(not screen.isNull())
        if screen.isNull():
            self._screen_button.setToolTip("此记录没有保存完整屏幕图片")
        header.addStretch()
        close = PushButton("关闭")
        close.clicked.connect(self.close)
        header.addWidget(close)
        layout.addLayout(header)
        self._view = _ImageView(self)
        layout.addWidget(self._view, 1)
        self._result_button.clicked.connect(lambda: self._view.set_image(self._result))
        self._screen_button.clicked.connect(lambda: self._view.set_image(self._screen))
        self._view.set_image(result)
