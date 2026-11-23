import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from e2s.app import controller as controller_module
from e2s.app.controller import AppController
from e2s.ui.native.tray import Tray, create_app_icon
from e2s.ui.native.workbench import Workbench


@pytest.fixture
def desktop(app: QApplication, monkeypatch: pytest.MonkeyPatch):
    if app.platformName() == "offscreen":
        pytest.skip("Requires a real Qt desktop")
    screen = app.primaryScreen()
    monkeypatch.setattr(controller_module, "screen_at_cursor", lambda _app: screen)
    icon = create_app_icon()
    workbench = Workbench(icon)
    tray = Tray(icon)
    controller = AppController(app, workbench, tray)
    try:
        yield controller, workbench, tray, screen
    finally:
        controller.close()


def wait_for_overlay(controller: AppController):
    for _ in range(100):
        if controller._overlay is not None:
            return controller._overlay
        QTest.qWait(10)
    pytest.fail("The capture overlay did not open")


def test_capture_hides_maximized_workbench_and_cancel_restores_it(
    desktop, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, workbench, _, screen = desktop
    workbench.showMaximized()
    expected = screen.grabWindow(0).size()
    capture = controller_module.capture_frame
    frames = []

    def record_frame(target):
        assert target == screen
        assert not workbench.isVisible()
        assert controller._overlay is None
        frame = capture(target)
        assert (frame.width_px, frame.height_px) == (expected.width(), expected.height())
        frames.append(frame)
        return frame

    monkeypatch.setattr(controller_module, "capture_frame", record_frame)
    workbench.capture_requested.emit()
    controller.start_capture()
    overlay = wait_for_overlay(controller)
    assert overlay.size() == screen.geometry().size()
    assert overlay.mapToGlobal(QPoint(0, 0)) == screen.geometry().topLeft()
    controller.start_capture()
    assert controller._overlay is overlay
    assert len(frames) == 1

    QTest.keyClick(overlay, Qt.Key.Key_Escape)
    assert controller._overlay is None
    assert workbench.isVisible()
    assert workbench.isMaximized()


def test_display_change_cancels_capture_started_from_tray(desktop) -> None:
    controller, workbench, tray, _ = desktop
    tray.capture_requested.emit()
    overlay = wait_for_overlay(controller)

    controller._displays.changed.emit()
    assert controller._overlay is None
    assert not overlay.isVisible()
    assert not workbench.isVisible()
