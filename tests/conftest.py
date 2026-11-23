import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app
