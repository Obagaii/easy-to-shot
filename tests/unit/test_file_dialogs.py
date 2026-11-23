from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog

from e2s.platform.windows.file_dialogs import choose_image_save_path, choose_output_directory


def test_save_dialog_returns_only_the_native_confirmed_path(monkeypatch: pytest.MonkeyPatch) -> None:
    path = Path("C:/Screenshots/截图.png")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(path), ""))
    assert choose_image_save_path(None, Path("C:/Screenshots/E2S.png")) == path

    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: ("", ""))
    assert choose_image_save_path(None, path) is None


def test_directory_dialog_reports_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_: "")
    assert choose_output_directory(None, Path("C:/Screenshots")) is None
