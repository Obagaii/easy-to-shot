import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from e2s.app import capture_output
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
    controller, workbench, tray, screen = desktop
    results = []
    controller.snapshot_ready.connect(results.append)
    tray.capture_requested.emit()
    overlay = wait_for_overlay(controller)

    screen.geometryChanged.emit(screen.geometry())
    assert controller._overlay is None
    assert not overlay.isVisible()
    assert not workbench.isVisible()
    assert not results


def test_copy_submits_frozen_pixels_and_restores_workbench(desktop, monkeypatch) -> None:
    controller, workbench, _, _ = desktop
    copied = []
    monkeypatch.setattr(capture_output, "copy_image_to_clipboard", copied.append)
    results = []
    controller.snapshot_ready.connect(lambda snapshot: results.append(snapshot))
    workbench.showMaximized()
    workbench.capture_requested.emit()
    overlay = wait_for_overlay(controller)
    assert overlay._canvas is None
    assert not results
    assert overlay.isVisible()

    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(200, 180))
    QTest.mouseMove(overlay, QPoint(40, 30))
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(40, 30))
    canvas = overlay._canvas
    assert canvas._toolbar.isVisible()
    assert not results
    QTest.keyClick(canvas, Qt.Key.Key_Right)
    frame = overlay._frame.image
    QTest.keyClick(canvas, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)

    assert len(results) == 1
    snapshot = results[0]
    selection = snapshot.selection
    assert selection.left == int(40 / overlay.width() * frame.width()) + 1
    assert selection.top == int(30 / overlay.height() * frame.height())
    expected = frame.copy(
        selection.left, selection.top, selection.width_px, selection.height_px
    ).convertToFormat(snapshot.to_image().format())
    assert snapshot.to_image() == expected
    assert copied == [expected]
    assert controller._overlay is None
    assert workbench.isVisible()
    assert workbench.isMaximized()


def test_edge_handle_can_resize_and_move_a_selection_without_changing_its_size(desktop) -> None:
    controller, _, tray, _ = desktop
    tray.capture_requested.emit()
    overlay = wait_for_overlay(controller)
    edge = QPoint(overlay.width() - 1, overlay.height() - 1)

    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(40, 30))
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=edge)
    full_edge = overlay._session.selection
    assert (full_edge.right, full_edge.bottom) == (overlay._frame.width_px, overlay._frame.height_px)

    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=edge)
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=edge - QPoint(40, 30))
    resized = overlay._session.selection
    assert (resized.left, resized.top) == (full_edge.left, full_edge.top)
    assert resized.right < full_edge.right
    assert resized.bottom < full_edge.bottom

    center = overlay.rect().center()
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=center)
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=center + QPoint(6, 8))
    moved = overlay._session.selection
    assert moved.left > resized.left
    assert moved.top > resized.top
    assert (moved.width_px, moved.height_px) == (resized.width_px, resized.height_px)


@pytest.mark.parametrize(
    ("position", "edge", "cursor_shape"),
    [
        (QPoint(260, 120), "top", Qt.CursorShape.SizeVerCursor),
        (QPoint(360, 220), "right", Qt.CursorShape.SizeHorCursor),
        (QPoint(260, 320), "bottom", Qt.CursorShape.SizeVerCursor),
        (QPoint(160, 220), "left", Qt.CursorShape.SizeHorCursor),
    ],
)
def test_side_handle_resizes_only_its_edge(desktop, position, edge, cursor_shape) -> None:
    controller, _, tray, _ = desktop
    tray.capture_requested.emit()
    overlay = wait_for_overlay(controller)

    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(160, 120))
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(360, 320))
    initial = overlay._session.selection

    mouse_move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(position),
        QPointF(overlay.mapToGlobal(position)),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas = overlay._canvas
    QApplication.sendEvent(canvas, mouse_move)
    assert canvas.cursor().shape() == cursor_shape
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=position)
    assert canvas._toolbar.isHidden()
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=position + QPoint(23, 31))
    assert canvas._toolbar.isVisible()
    resized = overlay._session.selection

    assert getattr(resized, edge) > getattr(initial, edge)
    for fixed_edge in {"left", "top", "right", "bottom"} - {edge}:
        assert getattr(resized, fixed_edge) == getattr(initial, fixed_edge)


def test_toolbar_restores_at_new_position_after_dragging_the_selection(desktop) -> None:
    controller, _, tray, _ = desktop
    tray.capture_requested.emit()
    overlay = wait_for_overlay(controller)
    window = overlay.windowHandle()
    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=QPoint(130, 230))
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=QPoint(650, 395))
    canvas = overlay._canvas
    toolbar = canvas._toolbar
    assert toolbar.isVisible()
    old_position = toolbar.pos()
    original = overlay._session.selection

    start = QPoint(375, 295)
    end = start + QPoint(25, 40)
    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=start)
    assert toolbar.isHidden()
    QTest.mouseMove(window, end)
    assert toolbar.isHidden()
    assert overlay._preview_selection != original
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=end)

    assert toolbar.isVisible()
    assert toolbar.pos() != old_position
    moved = overlay._session.selection
    assert moved.left > original.left
    assert moved.top > original.top
    assert moved.width_px == original.width_px
    assert moved.height_px == original.height_px
