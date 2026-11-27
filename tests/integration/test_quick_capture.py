from PySide6.QtCore import QPoint, QSettings, QRect
from PySide6.QtGui import QColor, QImage

from e2s.capture.service import CaptureFrame
from e2s.platform.windows.global_mouse import GlobalMouseCapture
from e2s.storage.quick_capture import QuickCaptureBinding, load_quick_capture, save_quick_capture
from e2s.ui.native.quick_capture import native_selection


def test_quick_capture_binding_defaults_and_persistence(tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    assert load_quick_capture(settings) == QuickCaptureBinding()
    assert load_quick_capture(settings, "pin") == QuickCaptureBinding("left", frozenset({"ctrl"}))
    binding = QuickCaptureBinding("side", frozenset({"ctrl", "alt"}), False)
    save_quick_capture(settings, binding)
    assert load_quick_capture(settings) == binding


def test_native_drag_converts_and_clamps_physical_pixels():
    result = native_selection((2200, 900), (1800, 200), (1920, 0, 3840, 1080), 1920, 1080)
    assert (result.left, result.top, result.right, result.bottom) == (0, 200, 280, 900)
    assert native_selection((10, 10), (10, 10), (0, 0, 100, 100), 100, 100) is None


def test_quick_capture_copies_and_records_selection(app, tmp_path, monkeypatch):
    from e2s.app import controller as controller_module
    from e2s.app.controller import AppController
    from e2s.output.ports import TaskResult, TaskState
    from e2s.ui.native.tray import Tray, create_app_icon
    from e2s.ui.native.workbench import Workbench

    icon = create_app_icon()
    window = Workbench(icon, tmp_path)
    controller = AppController(app, window, Tray(icon))
    image = QImage(100, 80, QImage.Format.Format_RGBA8888)
    image.fill(QColor("red"))
    frame = CaptureFrame("display", QRect(0, 0, 100, 80), image)
    monkeypatch.setattr(controller_module, "screen_for_native_point", lambda *_: (app.primaryScreen(), (0, 0, 100, 80)))
    monkeypatch.setattr(controller_module, "capture_frame", lambda *_: frame)
    copied = []
    monkeypatch.setattr(controller_module, "copy_snapshot", lambda snapshot: copied.append(snapshot) or TaskResult(str(snapshot.operation_id), TaskState.SUCCEEDED))
    try:
        controller._on_quick_drag("begin", 10, 20)
        controller._on_quick_drag("move", 60, 70)
        controller._on_quick_drag("finish", 60, 70)
        assert len(copied) == 1
        assert (copied[0].width_px, copied[0].height_px) == (50, 50)
        assert window.history.store.count() == 1
    finally:
        controller.close()


def test_global_mouse_matches_and_consumes_a_drag(app):
    import ctypes
    from e2s.platform.windows.global_mouse import _MouseInfo

    class User32:
        def __init__(self):
            self.masked = []
            self.key = 0x5B

        def GetAsyncKeyState(self, key):
            return -32768 if key == self.key else 0

        def keybd_event(self, *args):
            self.masked.append(args)

        def CallNextHookEx(self, *_args):
            return 0

    mouse = GlobalMouseCapture({"copy": QuickCaptureBinding(), "ocr": QuickCaptureBinding("right"),
                                "translate": QuickCaptureBinding("middle"),
                                "pin": QuickCaptureBinding("left", frozenset({"ctrl"}))}, lambda: True)
    mouse.close()
    mouse._user32 = User32()
    events = []
    mouse.drag_event.connect(lambda *event: events.append(event))
    info = _MouseInfo()
    info.pt.x, info.pt.y = 10, 20
    address = ctypes.addressof(info)
    assert mouse._handle(0, 0x201, address) == 1
    info.pt.x, info.pt.y = 30, 40
    assert mouse._handle(0, 0x200, address) == 0
    assert mouse._handle(0, 0x202, address) == 1
    assert [event[0] for event in events] == ["begin", "move", "finish"]
    assert len(mouse._user32.masked) == 2
    assert mouse._handle(0, 0x204, address) == 1
    assert mouse._handle(0, 0x205, address) == 1
    assert events[-1] == ("finish", 30, 40, "ocr")
    assert mouse._handle(0, 0x207, address) == 1
    assert mouse._handle(0, 0x208, address) == 1
    assert events[-1] == ("finish", 30, 40, "translate")
    mouse._user32.key = 0x11
    assert mouse._handle(0, 0x201, address) == 1
    assert mouse._handle(0, 0x202, address) == 1
    assert events[-1] == ("finish", 30, 40, "pin")
    mouse._user32.key = 0x5B
    mouse.bindings["ocr"] = QuickCaptureBinding()
    assert mouse._handle(0, 0x201, address) == 0


def test_quick_capture_dialog_selects_binding_and_cancel_preserves_settings(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from e2s.ui.native.quick_capture_dialog import QuickCaptureDialog
    from e2s.ui.native.tray import create_app_icon
    from e2s.ui.native.workbench import Workbench

    window = Workbench(create_app_icon(), tmp_path)
    changes = []
    window.quick_capture_changed.connect(changes.append)
    try:
        assert window._quick_button.text() == "Win + 左键拖动"
        dialog = QuickCaptureDialog(load_quick_capture(window.settings), window)
        dialog._keys["win"].setChecked(False)
        assert not dialog.binding().enabled
        dialog._keys["ctrl"].setChecked(True)
        dialog._keys["alt"].setChecked(True)
        dialog._button.setCurrentIndex(dialog._button.findData("right"))
        dialog._confirm()
        from PySide6.QtTest import QTest
        for _ in range(100):
            if dialog.result() == QDialog.DialogCode.Accepted:
                break
            QTest.qWait(10)
        assert dialog.result() == QDialog.DialogCode.Accepted
        monkeypatch.setattr(QuickCaptureDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
        window._edit_quick_capture()
        assert window._quick_button.text() == "Win + 左键拖动"
        monkeypatch.setattr(QuickCaptureDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
        selected_binding = dialog.binding()
        monkeypatch.setattr(QuickCaptureDialog, "binding", lambda self: selected_binding)
        window._edit_quick_capture()
        assert window._quick_button.text() == "Alt + Ctrl + 右键拖动"
        assert load_quick_capture(window.settings) == changes[-1]["copy"] == selected_binding
    finally:
        window.close()


def test_quick_ocr_opens_capture_session_with_selected_area(app, tmp_path, monkeypatch):
    from e2s.app import controller as controller_module
    from e2s.app.controller import AppController
    from e2s.ui.native.tray import Tray, create_app_icon
    from e2s.ui.native.workbench import Workbench

    icon = create_app_icon()
    window = Workbench(icon, tmp_path)
    controller = AppController(app, window, Tray(icon))
    image = QImage(100, 80, QImage.Format.Format_RGBA8888)
    image.fill(QColor("white"))
    frame = CaptureFrame("display", QRect(0, 0, 100, 80), image)
    screen = app.primaryScreen()
    monkeypatch.setattr(controller_module, "screen_for_native_point", lambda *_: (screen, (0, 0, 100, 80)))
    monkeypatch.setattr(controller_module, "capture_frame", lambda *_: frame)
    received = []
    overlay = object()
    monkeypatch.setattr(controller, "_open_session", lambda session: setattr(controller, "_overlay", overlay))
    monkeypatch.setattr(controller, "_start_ocr", lambda snapshot, target, auto_translate=False: received.append((snapshot, target, auto_translate)))
    try:
        assert load_quick_capture(window.settings, "ocr") == QuickCaptureBinding("right")
        assert window._quick_buttons["ocr"].text() == "Win + 右键拖动"
        controller._on_quick_drag("begin", 10, 20, "ocr")
        controller._on_quick_drag("finish", 60, 70, "ocr")
        assert len(received) == 1
        assert (received[0][0].width_px, received[0][0].height_px) == (50, 50)
        assert received[0][1] is overlay
        assert received[0][2] is False
        assert load_quick_capture(window.settings, "translate") == QuickCaptureBinding("middle")
        assert window._quick_buttons["translate"].text() == "Win + 中键拖动"
        controller._capture_screen = None
        controller._on_quick_drag("begin", 10, 20, "translate")
        controller._on_quick_drag("finish", 60, 70, "translate")
        assert len(received) == 2
        assert (received[1][0].width_px, received[1][0].height_px) == (50, 50)
        assert received[1][1:] == (overlay, True)
    finally:
        controller._overlay = None
        controller.close()


def test_quick_pin_shows_selected_area_and_records_history(app, tmp_path, monkeypatch):
    from e2s.app import controller as controller_module
    from e2s.app.controller import AppController
    from e2s.ui.native.pinned_image import PinnedImage
    from e2s.ui.native.tray import Tray, create_app_icon
    from e2s.ui.native.workbench import Workbench

    icon = create_app_icon()
    window = Workbench(icon, tmp_path)
    controller = AppController(app, window, Tray(icon))
    image = QImage(200, 160, QImage.Format.Format_RGBA8888)
    image.fill(QColor("red"))
    frame = CaptureFrame("display", QRect(-100, 50, 100, 80), image)
    screen = app.primaryScreen()
    monkeypatch.setattr(controller_module, "screen_for_native_point", lambda *_: (screen, (0, 0, 200, 160)))
    monkeypatch.setattr(controller_module, "capture_frame", lambda *_: frame)
    shown = []
    monkeypatch.setattr(PinnedImage, "show_at", lambda pin, target, origin: shown.append((pin, target, origin)))
    try:
        assert window._quick_buttons["pin"].text() == "Ctrl + 左键拖动"
        controller._on_quick_drag("begin", 20, 40, "pin")
        controller._on_quick_drag("finish", 120, 140, "pin")
        assert len(shown) == 1
        pin, target, origin = shown[0]
        assert target is screen
        assert origin == QPoint(-90, 70)
        assert (pin._image.width(), pin._image.height()) == (100, 100)
        assert window.history.store.count() == 1
    finally:
        controller.close()


def test_pin_edit_applies_changes_and_cancel_restores_original(app, tmp_path, monkeypatch):
    from dataclasses import replace
    from e2s.app import controller as controller_module
    from e2s.app.controller import AppController
    from e2s.ui.native.tray import Tray, create_app_icon
    from e2s.ui.native.workbench import Workbench

    icon = create_app_icon()
    window = Workbench(icon, tmp_path)
    controller = AppController(app, window, Tray(icon))
    screen = app.primaryScreen()
    geometry = screen.geometry()
    image = QImage(geometry.size(), QImage.Format.Format_RGBA8888)
    image.fill(QColor("white"))
    frame = CaptureFrame(screen.name(), geometry, image)
    monkeypatch.setattr(controller_module, "capture_frame", lambda *_: frame)
    monkeypatch.setattr(controller_module, "screen_for_native_point", lambda *_: (
        screen, (0, 0, image.width(), image.height())
    ))
    try:
        controller._on_quick_drag("begin", 40, 40, "pin")
        controller._on_quick_drag("finish", 140, 120, "pin")
        pin, = controller._pinned_images
        assert pin.isVisible()
        pin.edit_requested.emit()
        assert not pin.isVisible()
        overlay = controller._overlay
        assert overlay is not None and overlay._canvas is not None
        assert overlay._canvas._toolbar._action_buttons["copy"].accessibleName() == "完成编辑"
        snapshot = overlay._session.create_snapshot()
        updated = QImage(snapshot.width_px, snapshot.height_px, QImage.Format.Format_RGBA8888)
        updated.fill(QColor("red"))
        overlay.copy_requested.emit(replace(snapshot, rgba_pixels=bytes(updated.constBits())))
        assert controller._overlay is None and pin.isVisible()
        assert pin._image.pixelColor(0, 0) == QColor("red")
        assert controller._pin_snapshots[pin].to_image().pixelColor(0, 0) == QColor("red")
        pin.edit_requested.emit()
        controller._finish_capture()
        assert pin.isVisible() and pin._image.pixelColor(0, 0) == QColor("red")
    finally:
        controller.close()