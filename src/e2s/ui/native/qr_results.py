from collections.abc import Callable

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QEnterEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import PlainTextEdit, PushButton

from e2s.capture.qr import CodeDetection
from e2s.ui.native.toolbar_icons import toolbar_icon


def _copy_text(text: str) -> None:
    QApplication.clipboard().setText(text)


class CodeMarker(QToolButton):
    def __init__(self, owner: QWidget, detection: CodeDetection, show_result: Callable[[], None]) -> None:
        super().__init__(owner)
        self.detection = detection
        self._show_result = show_result
        self.setObjectName("codeMarker")
        self.setFixedSize(24, 24)
        self.setIcon(toolbar_icon("barcode_marker"))
        self.setAccessibleName("二维码识别结果")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            QToolButton { background: #1677ff; border: 2px solid white; border-radius: 12px; }
            QToolButton:hover, QToolButton:focus { background: #4096ff; }
        """)
        self.clicked.connect(lambda: show_result())

    def enterEvent(self, event: QEnterEvent) -> None:
        self._show_result()
        super().enterEvent(event)


class QrResults:
    """Manage recognition markers and a shared result popover for one capture."""

    def __init__(self, owner: QWidget) -> None:
        self._owner = owner
        self._markers: list[CodeMarker] = []
        self._popover: QFrame | None = None
        self._active: CodeMarker | None = None
        self._timer = QTimer(owner, interval=250)
        self._timer.timeout.connect(self._hide_when_pointer_leaves)

    def show(self, detections: tuple[CodeDetection, ...], target: QRectF) -> None:
        self.clear()
        for code in detections:
            marker = CodeMarker(self._owner, code, lambda code=code: self._show_code(code))
            point = QPoint(round(target.left() + target.width() * code.center[0]),
                           round(target.top() + target.height() * code.center[1]))
            marker.move(point - QPoint(12, 12))
            self._markers.append(marker)
            marker.show()
            marker.raise_()
        if len(detections) == 1:
            self._show_code(detections[0])

    def clear(self) -> None:
        self._timer.stop()
        self._active = None
        for marker in self._markers:
            marker.hide()
            marker.deleteLater()
        self._markers.clear()
        if self._popover is not None:
            self._popover.hide()
            self._popover.deleteLater()
            self._popover = None

    def _show_code(self, detection: CodeDetection) -> None:
        marker = next(marker for marker in self._markers if marker.detection == detection)
        if marker is self._active and self._popover is not None and self._popover.isVisible():
            return
        if self._popover is not None:
            self._popover.hide()
            self._popover.deleteLater()
        self._active = marker
        popover = QFrame(self._owner)
        self._popover = popover
        popover.setObjectName("codeResult")
        popover.setStyleSheet("""
            QFrame#codeResult { background: #fff; border: 1px solid #d9d9d9; border-radius: 8px; }
            QPlainTextEdit { background: transparent; border: 0; color: #262626; }
            QPushButton { padding: 5px 10px; border: 1px solid #d9d9d9; border-radius: 4px; }
            QPushButton:hover { color: #1677ff; border-color: #1677ff; }
        """)
        popover.setFixedWidth(max(1, min(344, self._owner.width() - 12)))
        layout = QVBoxLayout(popover)
        text = PlainTextEdit(popover)
        text.setPlainText(detection.text)
        text.setReadOnly(True)
        text.setAccessibleName("识别结果")
        text.setFixedHeight(min(160, max(46, len(detection.text) // 3)))
        layout.addWidget(text)
        status = QLabel(popover)
        status.hide()
        layout.addWidget(status)
        actions = QHBoxLayout()
        layout.addLayout(actions)
        actions.addStretch()
        copy = PushButton("复制文本", popover)
        copy.clicked.connect(lambda: _copy_text(detection.text))
        actions.addWidget(copy)
        url = QUrl(detection.text.strip(), QUrl.ParsingMode.StrictMode)
        if url.isValid() and url.scheme() in ("http", "https") and url.host():
            opening = PushButton("打开链接", popover)

            def open_link() -> None:
                if not QDesktopServices.openUrl(url):
                    status.setText("无法打开识别到的链接。")
                    status.show()
                    popover.adjustSize()

            opening.clicked.connect(open_link)
            actions.addWidget(opening)
        popover.adjustSize()
        x = marker.geometry().right() + 5
        if x + popover.width() > self._owner.width():
            x = marker.x() - popover.width() - 5
        y = marker.geometry().center().y() - popover.height() // 2
        popover.move(max(0, x), max(0, min(y, self._owner.height() - popover.height())))
        popover.show()
        popover.raise_()
        self._timer.start()

    def _hide_when_pointer_leaves(self) -> None:
        if self._popover is not None and self._active is not None:
            if self._popover.underMouse() or self._active.underMouse() or self._popover.isAncestorOf(
                QApplication.focusWidget()
            ):
                return
            self._popover.hide()
            self._timer.stop()
