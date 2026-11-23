import pytest
from PySide6.QtCore import QMimeData
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QApplication

from e2s.platform.windows.clipboard import (
    ClipboardError,
    copy_image_to_clipboard,
    copy_text_to_clipboard,
)


class ClipboardStub:
    def __init__(self) -> None:
        self.data: QMimeData | None = None
        self.is_available = True

    def setMimeData(self, data: QMimeData) -> None:
        self.data = data

    def ownsClipboard(self) -> bool:
        return self.is_available


def test_clipboard_adapter_supplies_native_image_and_text_formats(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    clipboard = ClipboardStub()
    monkeypatch.setattr(QGuiApplication, "clipboard", lambda *_: clipboard)
    image = QImage(3, 5, QImage.Format.Format_RGBA8888)
    image.fill(0x12345678)
    copy_image_to_clipboard(image)
    assert clipboard.data.imageData() == image

    copy_text_to_clipboard("截图")
    assert clipboard.data.text() == "截图"

    clipboard.is_available = False
    with pytest.raises(ClipboardError, match="无法写入"):
        copy_text_to_clipboard("截图")
