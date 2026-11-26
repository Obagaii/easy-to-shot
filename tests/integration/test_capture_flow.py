import os
from pathlib import Path
from time import sleep

import pytest
import zxingcpp
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QImage, QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QWidget,
)

from e2s.annotation.elements import Stroke, Tool
from e2s.app import capture_output
from e2s.app import controller as controller_module
from e2s.app.controller import AppController
from e2s.capture.geometry import SelectionDrag, SelectionRect
from e2s.capture.ocr import OcrLine
from e2s.capture.service import CaptureFrame
from e2s.capture.session import OutputSnapshot
from e2s.platform.windows.clipboard import ClipboardError
from e2s.platform.windows.uia_selection import HitPhase, SelectorHit
from e2s.storage.history import HistoryService, HistoryStore
from e2s.ui.native import qr_results
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


def move_pointer(
    widget: QWidget, position: QPoint, buttons: Qt.MouseButton = Qt.MouseButton.NoButton
) -> None:
    QApplication.sendEvent(widget, QMouseEvent(
        QEvent.Type.MouseMove, QPointF(position), QPointF(widget.mapToGlobal(position)),
        Qt.MouseButton.NoButton, buttons, Qt.KeyboardModifier.NoModifier,
    ))


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
    outputs = []
    controller.snapshot_ready.connect(results.append)
    controller.output_succeeded.connect(lambda *event: outputs.append(event))
    tray.capture_requested.emit()
    overlay = wait_for_overlay(controller)

    screen.geometryChanged.emit(screen.geometry())
    assert controller._overlay is None
    assert not overlay.isVisible()
    assert not workbench.isVisible()
    assert not results
    assert not outputs


def test_smart_selection_uses_native_child_in_topmost_window(desktop) -> None:
    controller, _, tray, screen = desktop
    origin = screen.geometry().topLeft() + QPoint(80, 80)
    flags = (
        Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
    )
    behind = QWidget(None, flags)
    foreground = QWidget(None, flags)
    child = QPushButton("Native option", foreground)
    behind.setGeometry(QRect(origin, QSize(320, 260)))
    foreground.setGeometry(QRect(origin, QSize(250, 200)))
    child.setGeometry(30, 40, 100, 80)
    child.winId()
    original_cursor = QCursor.pos()
    try:
        behind.show()
        foreground.show()
        foreground.raise_()
        position = child.mapToGlobal(child.rect().center())
        QCursor.setPos(position)
        tray.capture_requested.emit()
        overlay = wait_for_overlay(controller)
        QCursor.setPos(position + QPoint(1, 0))
        smart = overlay._smart_selection

        def preview_matches_child() -> bool:
            return (
                len(smart._path) >= 2
                and overlay._selection_on_screen(smart._path[0]).width() == pytest.approx(100, abs=2)
                and overlay._selection_on_screen(smart._path[-1]).width() == pytest.approx(250, abs=2)
            )

        wait_for(preview_matches_child, "accessibility child and foreground window path")
        assert overlay._displayed_selection() == smart._path[0]
    finally:
        foreground.close()
        behind.close()
        QCursor.setPos(original_cursor)


def test_smart_selection_follows_accessible_controls_without_native_handles(desktop) -> None:
    controller, _, tray, screen = desktop
    origin = screen.geometry().topLeft() + QPoint(180, 180)
    flags = (
        Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
    )
    window = QWidget(None, flags)
    window.setGeometry(QRect(origin, QSize(315, 165)))
    left = QPushButton("Left option", window)
    left.setGeometry(24, 28, 110, 42)
    right = QPushButton("Right option", window)
    right.setGeometry(156, 72, 134, 50)
    assert not left.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
    assert not right.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
    original_cursor = QCursor.pos()
    try:
        window.show()
        window.raise_()
        QCursor.setPos(left.mapToGlobal(left.rect().center()))
        tray.capture_requested.emit()
        overlay = wait_for_overlay(controller)
        # Move the actual desktop pointer while the capture overlay is foreground.
        QCursor.setPos(left.mapToGlobal(left.rect().center() + QPoint(1, 0)))

        def preview_matches(button: QPushButton) -> bool:
            rect = overlay._displayed_selection()
            if rect is None or overlay._session.selection is not None:
                return False
            expected = overlay.mapFromGlobal(button.mapToGlobal(QPoint()))
            local = overlay._selection_on_screen(rect).toAlignedRect()
            return (
                (local.topLeft() - expected).manhattanLength() <= 4
                and abs(local.width() - button.width()) <= 2
                and abs(local.height() - button.height()) <= 2
            )

        wait_for(lambda: preview_matches(left), "left accessibility preview")
        QCursor.setPos(right.mapToGlobal(right.rect().center()))
        wait_for(lambda: preview_matches(right), "right accessibility preview")
        selected = overlay._displayed_selection()
        QTest.mouseClick(
            overlay, Qt.MouseButton.LeftButton,
            pos=overlay.mapFromGlobal(right.mapToGlobal(right.rect().center())),
        )
        assert overlay._session.selection == selected
        assert overlay._canvas._toolbar.isVisible()
    finally:
        window.close()
        QCursor.setPos(original_cursor)


def stub_selector(controller, monkeypatch, path_at) -> None:
    selector = controller._selector
    monitor = None
    monkeypatch.setattr(type(selector), "available", property(lambda _: True))

    def refresh(_window_id, physical_monitor):
        nonlocal monitor
        monitor = physical_monitor
        QTimer.singleShot(0, lambda: selector.refreshed.emit(1, True))
        return 1

    def query(epoch, number, x, y, *, window_only):
        left, top = monitor.left, monitor.top
        path = path_at(x - left, y - top)
        if window_only:
            path = path[-1:]
        physical = tuple(
            SelectionRect(rect.left + left, rect.top + top, rect.right + left, rect.bottom + top)
            for rect in path
        )
        result = SelectorHit(epoch, number, HitPhase.INITIAL, 0, True, physical)
        QTimer.singleShot(0, lambda: selector.hit_received.emit(result))

    monkeypatch.setattr(selector, "refresh", refresh)
    monkeypatch.setattr(selector, "query", query)


def test_smart_selection_follows_pointer_and_commits_the_hovered_area(
    desktop, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, _, tray, screen = desktop
    child = SelectionRect(18, 18, 70, 70)
    parent = SelectionRect(5, 5, 100, 115)
    other = SelectionRect(110, 10, 180, 90)

    stub_selector(
        controller, monkeypatch, lambda x, _y: (child, parent) if x < parent.right else (other,)
    )
    tray.capture_requested.emit()
    overlay = wait_for_overlay(controller)
    scale_x = overlay._frame.width_px / screen.geometry().width()
    scale_y = overlay._frame.height_px / screen.geometry().height()
    first_point = QPoint(round(45 / scale_x), round(45 / scale_y))
    second_point = QPoint(round(145 / scale_x), round(45 / scale_y))
    move_pointer(overlay, first_point)
    wait_for(lambda: overlay._displayed_selection() == child, "initial child preview")
    assert overlay._session.selection is None
    assert overlay._canvas is None

    animation = overlay._smart_preview_animation
    animation.setCurrentTime(animation.duration())
    child_rect = overlay._selection_on_screen(child)
    parent_rect = overlay._selection_on_screen(parent)
    assert overlay._painted_selection() == (child, child_rect)

    wheel = QWheelEvent(
        QPointF(first_point), QPointF(overlay.mapToGlobal(first_point)),
        QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False,
    )
    QApplication.sendEvent(overlay, wheel)
    assert overlay._displayed_selection() == parent
    animation.pause()
    animation.setCurrentTime(animation.duration() // 2)
    preview, intermediate = overlay._painted_selection()
    assert preview == parent
    assert parent_rect.left() < intermediate.left() < child_rect.left()
    assert child_rect.width() < intermediate.width() < parent_rect.width()

    QTest.keyClick(overlay, Qt.Key.Key_Tab)
    assert overlay._smart_selection.window_only
    assert overlay._displayed_selection() == parent
    QTest.keyClick(overlay, Qt.Key.Key_Tab)
    wait_for(lambda: overlay._displayed_selection() == child, "child preview after Tab")
    assert animation.startValue() == intermediate
    animation.setCurrentTime(animation.duration())

    move_pointer(overlay, second_point)
    assert overlay._displayed_selection() is None
    assert overlay._painted_selection() == (child, child_rect)
    wait_for(lambda: overlay._displayed_selection() == other, "next window preview")
    assert animation.startValue() == child_rect
    assert overlay._session.selection is None

    animation.setCurrentTime(animation.duration() // 2)
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=second_point)
    assert overlay._painted_selection() == (other, overlay._selection_on_screen(other))
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=second_point)
    assert overlay._session.selection == other
    assert overlay._canvas._toolbar.isVisible()

    move_pointer(overlay, first_point)
    assert overlay._displayed_selection() == other


def test_drag_from_smart_preview_creates_manual_selection(desktop, monkeypatch) -> None:
    controller, _, tray, _ = desktop

    stub_selector(controller, monkeypatch, lambda _x, _y: (SelectionRect(0, 0, 500, 400),))
    tray.capture_requested.emit()
    overlay = wait_for_overlay(controller)
    start, finish = QPoint(20, 30), QPoint(140, 150)
    expected = SelectionDrag(overlay._source_position(QPointF(start))).update(
        overlay._source_position(QPointF(finish)), overlay._frame.width_px, overlay._frame.height_px
    )

    move_pointer(overlay, start)
    wait_for(lambda: overlay._displayed_selection() is not None, "smart selection preview")
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=start)
    assert overlay._displayed_selection() == SelectionRect(0, 0, 500, 400)
    move_pointer(overlay, start + QPoint(1, 1), Qt.MouseButton.LeftButton)
    assert overlay._displayed_selection() == SelectionRect(0, 0, 500, 400)
    move_pointer(overlay, finish, Qt.MouseButton.LeftButton)
    assert overlay._displayed_selection() == expected
    assert overlay._painted_selection() == (expected, overlay._selection_on_screen(expected))
    assert overlay._session.selection is None
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=finish)
    assert overlay._session.selection == expected
    assert overlay._canvas._toolbar.isVisible()


def test_recording_opens_for_current_capture_selection(desktop, monkeypatch, tmp_path) -> None:
    controller, _, tray, _ = desktop
    monkeypatch.setattr(
        controller_module.QStandardPaths, "writableLocation", lambda _location: str(tmp_path)
    )
    tray.capture_requested.emit()
    overlay = wait_for_overlay(controller)
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(80, 70))
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(340, 250))
    selection = overlay._session.selection
    QTest.mouseClick(overlay._canvas._toolbar._action_buttons["record"], Qt.MouseButton.LeftButton)
    panel = controller._live_panel

    assert panel._region == overlay.selection_geometry(selection)
    assert panel._directory == tmp_path / "EasyToShot"
    assert overlay.isVisible()
    assert overlay.isEnabled()
    assert panel.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert panel._drag_handle.isVisible()
    panel.reject()
    assert overlay.isVisible()
    assert overlay.isEnabled()
    assert overlay._displayed_selection() == selection

    QTest.mouseClick(overlay._canvas._toolbar._action_buttons["record"], Qt.MouseButton.LeftButton)
    panel = controller._live_panel
    panel._record.click()
    assert not overlay.isVisible()
    panel.reject()
    assert overlay.isVisible()
    assert overlay.isEnabled()



def test_recording_toolbar_dismisses_on_capture_click_and_escape_still_works(
    desktop, monkeypatch, tmp_path
) -> None:
    controller, _, tray, _ = desktop
    monkeypatch.setattr(
        controller_module.QStandardPaths, "writableLocation", lambda _location: str(tmp_path)
    )
    tray.capture_requested.emit()
    overlay = wait_for_overlay(controller)
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(80, 70))
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(340, 250))
    toolbar = overlay._canvas._toolbar
    QTest.mouseClick(toolbar._action_buttons["record"], Qt.MouseButton.LeftButton)
    assert controller._live_panel is not None
    assert overlay.isEnabled()

    QTest.mouseClick(toolbar._buttons[Tool.RECTANGLE], Qt.MouseButton.LeftButton)
    assert controller._live_panel is None
    assert overlay._canvas._tool is Tool.RECTANGLE
    assert overlay.isEnabled()

    QTest.mouseClick(toolbar._action_buttons["record"], Qt.MouseButton.LeftButton)
    assert controller._live_panel is not None
    QTest.mouseClick(overlay._canvas, Qt.MouseButton.LeftButton, pos=QPoint(160, 140))
    assert controller._live_panel is None
    assert overlay.isEnabled()
    QTest.keyClick(overlay._canvas, Qt.Key.Key_Escape)
    assert controller._overlay is None

def test_copy_submits_frozen_pixels_and_restores_workbench(desktop, monkeypatch) -> None:
    controller, workbench, _, _ = desktop
    copied = []
    monkeypatch.setattr(capture_output, "copy_image_to_clipboard", copied.append)
    results = []
    outputs = []
    controller.snapshot_ready.connect(results.append)
    controller.output_succeeded.connect(lambda *event: outputs.append(event))
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
    assert len(outputs) == 1
    submitted, result, source = outputs[0]
    assert source == "copy"
    assert submitted.operation_id == result.operation_id == str(snapshot.operation_id)
    assert submitted.pixels == snapshot.rgba_pixels
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


def test_resizing_with_a_drawing_tool_keeps_marks_at_the_same_screen_pixels(desktop) -> None:
    controller, _, tray, _ = desktop
    tray.capture_requested.emit()
    overlay = wait_for_overlay(controller)
    window = overlay.windowHandle()
    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=QPoint(150, 110))
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=QPoint(520, 355))
    canvas = overlay._canvas
    QTest.mouseClick(canvas._toolbar._buttons[Tool.ARROW], Qt.MouseButton.LeftButton)
    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=QPoint(220, 170))
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=QPoint(355, 170))
    assert len(canvas._document.elements) == 1
    element = canvas._document.elements[0]
    old = overlay._session.selection

    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=QPoint(150, 232))
    assert canvas._toolbar.isHidden()
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=QPoint(185, 232))
    assert canvas._toolbar.isVisible()
    resized = overlay._session.selection
    assert resized.left > old.left
    assert resized.right == old.right
    assert (resized.top, resized.bottom) == (old.top, old.bottom)
    assert canvas._document.elements == (element,)
    snapshot = overlay._session.create_snapshot()
    x = round(element.points[0][0] + 20 - resized.left)
    y = round(element.points[0][1] - resized.top)
    assert snapshot.to_image().pixelColor(x, y) == QColor(element.color)
    assert canvas._preview_image() == snapshot.to_image()

    QTest.keyClick(canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert not canvas._document.elements
    assert overlay._session.selection == resized
    QTest.keyClick(
        canvas, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier
    )
    assert canvas._document.elements == (element,)

    QTest.mouseClick(canvas._toolbar._buttons[Tool.SELECT], Qt.MouseButton.LeftButton)
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=QPoint(280, 170))
    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=QPoint(355, 170))
    assert canvas._toolbar.isVisible()
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=QPoint(405, 215))
    resized_line = canvas._document.elements[0]
    assert resized_line.points[0] == element.points[0]
    assert resized_line.points[-1][0] > element.points[-1][0]
    assert resized_line.points[-1][1] > element.points[-1][1]
    assert overlay._session.selection == resized


def test_annotated_preview_copy_and_saved_png_match_after_output_retries(
    desktop, monkeypatch, tmp_path
) -> None:
    controller, workbench, _, _ = desktop

    def synthetic_frame(screen):
        geometry = screen.geometry()
        image = QImage(geometry.size() * screen.devicePixelRatio(), QImage.Format.Format_RGBA8888)
        image.fill(QColor("#ffffff"))
        return CaptureFrame("test", geometry, image)

    monkeypatch.setattr(controller_module, "capture_frame", synthetic_frame)
    attempted_copies = []

    def reject_clipboard(image):
        attempted_copies.append(bytes(image.constBits()))
        raise ClipboardError("clipboard is temporarily unavailable")

    monkeypatch.setattr(capture_output, "copy_image_to_clipboard", reject_clipboard)
    target = tmp_path / "annotated.png"
    paths = iter((None, target))
    monkeypatch.setattr(
        controller_module, "choose_image_save_path", lambda *_args, **_kwargs: next(paths)
    )
    exported = []
    controller.snapshot_ready.connect(exported.append)
    workbench.show()
    workbench.capture_requested.emit()
    overlay = wait_for_overlay(controller)
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(40, 60))
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(360, 260))
    canvas = overlay._canvas
    QTest.mouseClick(canvas._toolbar._buttons[Tool.RECTANGLE], Qt.MouseButton.LeftButton)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(60, 85))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(240, 190))
    QTest.mouseClick(canvas._toolbar._buttons[Tool.RECT_HIGHLIGHT], Qt.MouseButton.LeftButton)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(85, 80))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(260, 160))
    preview = canvas._preview_image()
    assert preview != canvas._document.source

    QTest.keyClick(canvas, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert controller._overlay is overlay
    assert not exported
    assert attempted_copies == [bytes(preview.constBits())]

    QTest.keyClick(canvas, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert controller._overlay is overlay
    assert not target.exists()
    assert canvas._preview_image() == preview
    QTest.keyClick(canvas, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    for _ in range(100):
        if exported:
            break
        QApplication.processEvents()
        sleep(0.01)

    assert len(exported) == 1
    assert controller._overlay is None
    assert workbench.isVisible()
    assert exported[0].to_image() == preview
    with Image.open(target) as image:
        assert image.size == (preview.width(), preview.height())
        assert image.tobytes() == exported[0].rgba_pixels


def test_pin_keeps_composite_for_copy_save_and_history_after_zoom(
    desktop, monkeypatch, tmp_path
) -> None:
    controller, workbench, _, screen = desktop
    frame = QImage(320, 200, QImage.Format.Format_RGBA8888)
    frame.fill(QColor("#216581"))
    monkeypatch.setattr(
        controller_module, "capture_frame", lambda target: CaptureFrame(
            target.name(), target.geometry(), frame
        )
    )
    copied = []
    monkeypatch.setattr(capture_output, "copy_image_to_clipboard", copied.append)
    target = tmp_path / "pinned.png"
    targets = iter((None, target))
    dialog_windows = []

    def choose_target(window, *_args, **_kwargs):
        dialog_windows.append(window)
        return next(targets)

    monkeypatch.setattr(controller_module, "choose_image_save_path", choose_target)
    store = HistoryStore(tmp_path / "storage")
    history = HistoryService(store)
    outputs = []
    controller.output_succeeded.connect(lambda *event: outputs.append(event))
    controller.output_succeeded.connect(history.record_success)

    workbench.show()
    workbench.capture_requested.emit()
    overlay = wait_for_overlay(controller)
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(40, 50))
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(310, 250))
    canvas = overlay._canvas
    QTest.mouseClick(canvas._toolbar._buttons[Tool.RECTANGLE], Qt.MouseButton.LeftButton)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(90, 100))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(210, 170))
    preview = canvas._preview_image()
    assert preview != canvas._document.source
    assert not outputs

    QTest.mouseClick(canvas._toolbar._action_buttons["pin"], Qt.MouseButton.LeftButton)
    assert controller._overlay is None
    assert workbench.isVisible()
    assert len(controller._pinned_images) == 1
    pin, = controller._pinned_images
    assert pin.isVisible()
    assert len(outputs) == 1
    snapshot, result, source = outputs[0]
    assert source == "pin"
    assert snapshot.operation_id == result.operation_id
    assert snapshot.pixels == bytes(preview.constBits())
    assert (snapshot.width_px, snapshot.height_px) == (preview.width(), preview.height())

    initial_size = pin.size()
    local = QPointF(8, 8)
    wheel = QWheelEvent(
        local, QPointF(pin.mapToGlobal(local.toPoint())), QPoint(), QPoint(0, 240),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(pin, wheel)
    assert pin.width() > initial_size.width()
    assert pin.width() != snapshot.width_px

    QTest.keyClick(pin, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert copied == [preview]
    assert pin.isVisible()
    assert [event[2] for event in outputs] == ["pin", "copy"]

    QTest.keyClick(pin, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert pin.isVisible()
    assert len(outputs) == 2
    assert not target.exists()
    QTest.keyClick(pin, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    for _ in range(100):
        if len(outputs) == 3:
            break
        QTest.qWait(10)
    assert dialog_windows == [pin, pin]
    assert [event[2] for event in outputs] == ["pin", "copy", "save"]
    assert len({output.operation_id for output, _, _ in outputs}) == 3
    for output, output_result, _ in outputs:
        assert output.operation_id == output_result.operation_id
        assert output.session_id == snapshot.session_id
        assert output.revision == snapshot.revision
        assert output.pixels == snapshot.pixels

    with Image.open(target) as saved:
        assert saved.size == (snapshot.width_px, snapshot.height_px)
        assert saved.convert("RGBA").tobytes() == snapshot.pixels
    saved_items = store.list_recent()
    assert len(saved_items) == 1
    assert saved_items[0].source == "pin"
    with Image.open(store.image_path(saved_items[0])) as recorded:
        assert recorded.convert("RGBA").tobytes() == snapshot.pixels

    pin.move(screen.geometry().bottomRight() + QPoint(100, 100))
    controller._displays.changed.emit()
    QTest.qWait(10)
    assert screen.availableGeometry().contains(pin.geometry())
    assert pin.isVisible()

    controller.close()
    assert not pin.isVisible()
    assert not controller._pinned_images


def test_pin_allocation_failure_keeps_capture_open_for_retry(desktop, monkeypatch) -> None:
    controller, workbench, _, _ = desktop
    workbench.capture_requested.emit()
    overlay = wait_for_overlay(controller)
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(30, 40))
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(190, 140))
    canvas = overlay._canvas
    outputs = []
    controller.output_succeeded.connect(lambda *event: outputs.append(event))

    def reject_pin(_image):
        raise MemoryError

    with monkeypatch.context() as patch:
        patch.setattr(controller_module, "PinnedImage", reject_pin)
        QTest.keyClick(canvas, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
        assert controller._overlay is overlay
        assert not controller._pinned_images
        assert not outputs

    QTest.keyClick(canvas, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert controller._overlay is None
    assert len(controller._pinned_images) == 1
    assert [event[2] for event in outputs] == ["pin"]


def test_scroll_tool_opens_inline_and_copies_the_stitched_pixels(desktop, monkeypatch) -> None:
    controller, workbench, _, _ = desktop
    clipboard = []
    monkeypatch.setattr(capture_output, "copy_image_to_clipboard", clipboard.append)
    workbench.show()
    workbench.capture_requested.emit()
    overlay = wait_for_overlay(controller)
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(40, 50))
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(320, 265))
    selected = overlay._session.selection
    sample = QImage(selected.width_px, selected.height_px, QImage.Format.Format_RGBA8888)
    sample.fill(QColor("#2b63bc"))
    monkeypatch.setattr(controller_module, "grab_region", lambda _screen, _selection: sample)

    QTest.keyClick(overlay._canvas, Qt.Key.Key_L)
    panel = controller._live_panel
    assert panel is not None
    assert not overlay.isVisible()
    for _ in range(100):
        QApplication.processEvents()
        if panel._ready:
            break
        sleep(0.01)
    assert panel._thumbnail.isVisible()

    panel._results[-1].click()
    for _ in range(100):
        QApplication.processEvents()
        if clipboard:
            break
        sleep(0.01)
    assert controller._live_panel is None and controller._overlay is None
    assert workbench.isVisible()
    assert clipboard == [sample]


def test_scan_codes_place_markers_and_copy_the_selected_result(desktop, monkeypatch) -> None:
    controller, workbench, _, screen = desktop
    payload = "Easy to Shot QR"
    code = zxingcpp.create_barcode(payload, zxingcpp.BarcodeFormat.QRCode)
    sample = Image.fromarray(zxingcpp.write_barcode_to_image(code, 4)).convert("RGBA")
    dpr = screen.devicePixelRatio()
    geometry = screen.geometry()
    image = Image.new("RGBA", (round(geometry.width() * dpr), round(geometry.height() * dpr)), "white")
    image.paste(sample, (round(80 * dpr), round(85 * dpr)))
    frozen = QImage(image.tobytes(), *image.size, QImage.Format.Format_RGBA8888).copy()
    monkeypatch.setattr(
        controller_module, "capture_frame", lambda _screen: CaptureFrame("qr", geometry, frozen)
    )

    workbench.capture_requested.emit()
    overlay = wait_for_overlay(controller)
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(40, 50))
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(320, 265))
    QTest.keyClick(overlay._canvas, Qt.Key.Key_Q, Qt.KeyboardModifier.ControlModifier)
    for _ in range(100):
        markers = overlay.findChildren(QToolButton, "codeMarker")
        if markers:
            break
        QTest.qWait(10)
    (marker,) = markers
    center = marker.geometry().center()
    assert center.x() == pytest.approx(80 + sample.width / (2 * dpr), abs=3)
    assert center.y() == pytest.approx(85 + sample.height / (2 * dpr), abs=3)
    marker.click()
    popup = overlay._qr_results._popover
    assert popup.findChild(QPlainTextEdit).toPlainText() == payload
    copied = []
    monkeypatch.setattr(qr_results, "_copy_text", copied.append)
    popup.findChild(QPushButton).click()
    assert copied == [payload]


def test_screen_ocr_displays_selectable_text_and_editable_original(desktop, monkeypatch) -> None:
    controller, workbench, _, screen = desktop
    geometry, dpr = screen.geometry(), screen.devicePixelRatio()
    pixels = round(geometry.width() * dpr), round(geometry.height() * dpr)
    image = Image.new("RGBA", pixels, "white")
    font = ImageFont.truetype(str(Path(os.environ["WINDIR"]) / "Fonts" / "msyh.ttc"), 42)
    drawing = ImageDraw.Draw(image)
    drawing.text((75, 70), "截图文字识别", font=font, fill="black")
    drawing.text((75, 133), "Easy to Shot", font=font, fill="black")
    frozen = QImage(image.tobytes(), *image.size, QImage.Format.Format_RGBA8888).copy()
    monkeypatch.setattr(
        controller_module, "capture_frame", lambda _: CaptureFrame("ocr", geometry, frozen)
    )
    workbench.capture_requested.emit()
    overlay = wait_for_overlay(controller)
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(420, 230))
    QTest.keyClick(overlay._canvas, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
    wait_for(lambda: overlay._ocr_workspace is not None, "OCR completion")
    workspace = overlay._ocr_workspace
    assert "截图文字识别" in workspace._editor.toPlainText()
    assert "Easy to Shot" in workspace._editor.toPlainText()
    assert workspace._editor.isReadOnly()
    workspace._editor.selectAll()
    workspace._editor.copy()
    assert QApplication.clipboard().text() == workspace._editor.toPlainText()
    workspace._show_original.click()
    assert workspace._editor.isHidden()
    assert workspace._original.pos() == workspace._region.topLeft()
    workspace._show_original.click()
    workspace._edit.click()
    workspace._editor.setPlainText("Edited text")
    workspace._edit.click()
    assert workspace._editor.toPlainText() == "Edited text"
    rendered = workspace.output_image()
    assert rendered.size() == workspace._snapshot.to_image().size()
    assert rendered != workspace._snapshot.to_image()
    snapshots = []
    overlay._request_output(snapshots.append)
    assert snapshots[0].rgba_pixels == bytes(rendered.constBits())
    workspace.close()
    assert overlay._ocr_workspace is None
    assert overlay._canvas.isVisible()

def test_ocr_reuses_selection_content_only_within_the_same_capture(
    desktop, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, workbench, _, screen = desktop
    geometry = screen.geometry()
    image = QImage(geometry.size(), QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.white)
    monkeypatch.setattr(
        controller_module, "capture_frame", lambda _: CaptureFrame("ocr", geometry, image)
    )
    first_area = SelectionRect(10, 10, 270, 170)
    blank_area = SelectionRect(260, 170, 400, 255)
    calls = []
    lines = (OcrLine("Sample", ((8, 8), (72, 8), (72, 26), (8, 26))),)

    def recognize(snapshot: OutputSnapshot) -> tuple[OcrLine, ...]:
        calls.append(snapshot.selection)
        return () if snapshot.selection == blank_area else lines

    monkeypatch.setattr(controller._recognizer, "recognize", recognize)

    def request_ocr(overlay, expected: str) -> None:
        QTest.keyClick(overlay._canvas, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
        wait_for(lambda: controller._ocr_request is None, "OCR completion")
        workspace = overlay._ocr_workspace
        if expected:
            assert workspace is not None
            assert workspace._editor.toPlainText() == expected
            workspace.close()
        else:
            assert workspace is None
            assert "未识别到文字" in overlay._canvas._feedback.text()
    workbench.capture_requested.emit()
    overlay = wait_for_overlay(controller)
    overlay._set_selection(first_area)
    request_ocr(overlay, "Sample")
    overlay._set_selection(blank_area)
    request_ocr(overlay, "")
    request_ocr(overlay, "")
    overlay._set_selection(first_area)
    request_ocr(overlay, "Sample")
    assert calls == [first_area, blank_area]

    document = overlay._session.begin_annotation()
    document.add(Stroke(Tool.RECTANGLE, ((35, 35), (60, 60)), "#1677ff", 2, True))
    request_ocr(overlay, "Sample")
    QTest.keyClick(overlay._canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    request_ocr(overlay, "Sample")
    assert calls == [first_area, blank_area, first_area]

    overlay.close()
    workbench.capture_requested.emit()
    overlay = wait_for_overlay(controller)
    overlay._set_selection(first_area)
    request_ocr(overlay, "Sample")
    assert calls == [first_area, blank_area, first_area, first_area]


def test_translation_toolbar_recognizes_then_translates_with_cached_results(
    desktop, monkeypatch: pytest.MonkeyPatch
) -> None:
    from e2s.capture.stream_translation import StreamingTranslator

    controller, workbench, _, screen = desktop
    geometry = screen.geometry()
    image = QImage(geometry.size(), QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.white)
    monkeypatch.setattr(
        controller_module, "capture_frame", lambda _: CaptureFrame("translate", geometry, image)
    )
    calls = []
    translations = []
    lines = (OcrLine("Hello", ((8, 8), (72, 8), (72, 26), (8, 26))),)
    monkeypatch.setattr(controller._recognizer, "recognize", lambda snapshot: calls.append(snapshot) or lines)
    monkeypatch.setattr(
        StreamingTranslator, "translate",
        lambda self, text, language, model, key: translations.append((text, language, model)),
    )
    workbench.capture_requested.emit()
    overlay = wait_for_overlay(controller)
    overlay._set_selection(SelectionRect(10, 10, 270, 170))
    workbench._language.setCurrentIndex(workbench._language.findData("English"))
    overlay._canvas._toolbar._action_buttons["translate_text"].click()
    wait_for(lambda: overlay._ocr_workspace is not None, "automatic translation")
    assert len(calls) == 1
    assert translations == [("Hello", "English", "free")]
    assert not overlay._ocr_workspace._translate.isEnabled()
    overlay._ocr_workspace.close()
    overlay._canvas._toolbar._action_buttons["translate_text"].click()
    assert len(calls) == 1
    assert len(translations) == 2
    overlay._ocr_workspace.close()
    workbench._language.setCurrentIndex(workbench._language.findData("Japanese"))
    overlay._canvas._toolbar._action_buttons["ocr"].click()
    assert len(translations) == 2
    assert overlay._ocr_workspace._editor.toPlainText() == "Hello"
    assert overlay._ocr_workspace._language.currentData() == "Japanese"


def wait_for(check, description: str) -> None:
    for _ in range(1500):
        QApplication.processEvents()
        if check():
            return
        sleep(0.01)
    pytest.fail(f"Timed out waiting for {description}.")
