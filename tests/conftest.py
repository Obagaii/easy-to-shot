from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from e2s.storage.shortcuts import shortcut_settings
from e2s.ui.native import annotation_toolbar, workbench


@pytest.fixture(scope="session")
def app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


@pytest.fixture(autouse=True)
def isolate_user_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(annotation_toolbar, "shortcut_settings", lambda: shortcut_settings(tmp_path))
    monkeypatch.setattr(workbench, "get_deepseek_key", lambda: None)
