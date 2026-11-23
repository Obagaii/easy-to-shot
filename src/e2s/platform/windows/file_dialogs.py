from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QWidget


def choose_image_save_path(parent: QWidget | None, suggested_path: Path) -> Path | None:
    """Open the system save dialog on the GUI thread and return its accepted path."""
    path, _ = QFileDialog.getSaveFileName(
        parent, "另存截图", str(suggested_path), "PNG 图像 (*.png)"
    )
    return Path(path) if path else None


def choose_output_directory(parent: QWidget | None, initial_directory: Path) -> Path | None:
    """Open the system folder picker on the GUI thread and return its accepted directory."""
    path = QFileDialog.getExistingDirectory(parent, "选择输出目录", str(initial_directory))
    return Path(path) if path else None
