from PySide6.QtCore import QMimeData, QThread
from PySide6.QtGui import QGuiApplication, QImage


class ClipboardError(RuntimeError):
    pass


def copy_image_to_clipboard(image: QImage) -> None:
    """Write a non-null image to the system clipboard on the Qt GUI thread."""
    if image.isNull():
        raise ClipboardError("没有可复制的图像。")
    data = QMimeData()
    data.setImageData(image)
    _write_clipboard(data)


def copy_text_to_clipboard(text: str) -> None:
    """Write text to the system clipboard on the Qt GUI thread."""
    data = QMimeData()
    data.setText(text)
    _write_clipboard(data)


def _write_clipboard(data: QMimeData) -> None:
    app = QGuiApplication.instance()
    if not isinstance(app, QGuiApplication) or app.thread() != QThread.currentThread():
        raise ClipboardError("剪贴板写入必须在界面线程执行。")
    clipboard = app.clipboard()
    clipboard.setMimeData(data)
    if not clipboard.ownsClipboard():
        raise ClipboardError("无法写入系统剪贴板，请重试。")
