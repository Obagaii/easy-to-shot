from time import sleep

import pytest
import zxingcpp
from PIL import Image
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QWidget,
)

from e2s.annotation.elements import Tool
from e2s.app import capture_output
from e2s.app import controller as controller_module
from e2s.app.controller import AppController
from e2s.capture.geometry import SelectionDrag, SelectionRect
from e2s.capture.service import CaptureFrame
from e2s.platform.windows.clipboard import ClipboardError
from e2s.storage.history import HistoryService, HistoryStore
from e2s.ui.native import overlay as overlay_module
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
    child = QWidget(foreground)
    behind.setGeometry(QRect(origin, QSize(320, 260)))
    foreground.setGeometry(QRect(origin, QSize(250, 200)))
    child.setGeometry(30, 40, 100, 80)
    child.winId()
    try:
        behind.show()
        foreground.show()
        foreground.raise_()
        tray.capture_requested.emit()
        overlay = wait_for_overlay(controller)
        position = overlay.mapFromGlobal(child.mapToGlobal(child.rect().center()))
        QTest.mouseMove(overlay.windowHandle(), position)
        child_bounds, window_bounds = overlay._hover_path

        assert overlay._displayed_selection() == child_bounds
        assert overlay._selection_on_screen(child_bounds).width() == pytest.approx(100, abs=2)
        assert overlay._selection_on_screen(window_bounds).width() == pytest.approx(250, abs=2)
    finally:
        foreground.close()
        behind.close()


def test_smart_selection_follows_pointer_and_commits_the_hovered_area(
    desktop, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, _, tray, screen = desktop
    child = SelectionRect(18, 18, 70, 70)
    parent = SelectionRect(5, 5, 100, 115)
    other = SelectionRect(110, 10, 180, 90)

    class WindowSelectionStub:
        def __init__(self, _overlay_id: int) -> None:
            pass

        def hit_path(self, x_px: int, _y_px: int) -> tuple[SelectionRect, ...]:
            return (child, parent) if x_px < parent.right else (other,)

    monkeypatch.setattr(overlay_module, "WindowSelection", WindowSelectionStub)
    tray.capture_requested.emit()
    overlay = wait_for_overlay(controller)
    scale_x = overlay._frame.width_px / screen.geometry().width()
    scale_y = overlay._frame.height_px / screen.geometry().height()
    first_point = QPoint(round(45 / scale_x), round(45 / scale_y))
    second_point = QPoint(round(145 / scale_x), round(45 / scale_y))
    window = overlay.windowHandle()
    QTest.mouseMove(window, first_point)
    assert overlay._displayed_selection() == child
    assert overlay._session.selection is None
    assert overlay._canvas is None

    wheel = QWheelEvent(
        QPointF(first_point), QPointF(overlay.mapToGlobal(first_point)),
        QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False,
    )
    QApplication.sendEvent(overlay, wheel)
    assert overlay._displayed_selection() == parent

    QTest.mouseMove(window, second_point)
    assert overlay._displayed_selection() == other
    assert overlay._session.selection is None
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=second_point)
    assert overlay._session.selection == other
    assert overlay._canvas._toolbar.isVisible()

    QTest.mouseMove(window, first_point)
    assert overlay._displayed_selection() == other


def test_drag_from_smart_preview_creates_manual_selection(desktop, monkeypatch) -> None:
    controller, _, tray, _ = desktop

    class WindowSelectionStub:
        def __init__(self, _overlay_id: int) -> None:
            pass

        def hit_path(self, _x_px: int, _y_px: int) -> tuple[SelectionRect, ...]:
            return (SelectionRect(0, 0, 500, 400),)

    monkeypatch.setattr(overlay_module, "WindowSelection", WindowSelectionStub)
    tray.capture_requested.emit()
    overlay = wait_for_overlay(controller)
    window = overlay.windowHandle()
    start, finish = QPoint(20, 30), QPoint(140, 150)
    expected = SelectionDrag(overlay._source_position(QPointF(start))).update(
        overlay._source_position(QPointF(finish)), overlay._frame.width_px, overlay._frame.height_px
    )

    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=start)
    assert overlay._displayed_selection() == SelectionRect(0, 0, 500, 400)
    QTest.mouseMove(window, start + QPoint(1, 1))
    assert overlay._displayed_selection() == SelectionRect(0, 0, 500, 400)
    QTest.mouseMove(window, finish)
    assert overlay._displayed_selection() == expected
    assert overlay._session.selection is None
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=finish)
    assert overlay._session.selection == expected
    assert overlay._canvas._toolbar.isVisible()


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
