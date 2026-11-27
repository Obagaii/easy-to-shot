from PySide6.QtCore import QSettings, QRect
from PySide6.QtGui import QColor, QImage

from e2s.capture.service import CaptureFrame
from e2s.platform.windows.global_mouse import GlobalMouseCapture
from e2s.storage.quick_capture import QuickCaptureBinding, load_quick_capture, save_quick_capture
from e2s.ui.native.quick_capture import native_selection


def test_quick_capture_binding_defaults_and_persistence(tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    assert load_quick_capture(settings) == QuickCaptureBinding()
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

        def GetAsyncKeyState(self, key):
            return -32768 if key == 0x5B else 0

        def keybd_event(self, *args):
            self.masked.append(args)

        def CallNextHookEx(self, *_args):
            return 0

    mouse = GlobalMouseCapture(QuickCaptureBinding(), lambda: True)
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
        assert load_quick_capture(window.settings) == changes[-1] == selected_binding
    finally:
        window.close()
