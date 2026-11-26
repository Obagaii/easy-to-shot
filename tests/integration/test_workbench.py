from pathlib import Path

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

from e2s.app.controller import AppController
from e2s.output.ports import TaskResult, TaskState
from e2s.output.service import OutputSnapshot
from e2s.platform.windows.hotkeys import HotkeyError, HotkeyState
from e2s.ui.native.tray import Tray, create_app_icon
from e2s.ui.native.workbench import Workbench


def test_successful_output_appears_in_history_and_can_be_copied(
    app: QApplication, tmp_path: Path
) -> None:
    icon = create_app_icon()
    workbench = Workbench(icon, tmp_path)
    controller = AppController(app, workbench, Tray(icon))
    try:
        snapshot = OutputSnapshot("op", "session", 1, 1, 1, bytes([255, 0, 0, 255]))
        controller.output_succeeded.emit(snapshot, TaskResult("op", TaskState.SUCCEEDED), "copy")
        workbench.refresh_history()
        assert workbench._history_list.count() == 1
        workbench._history_list.setCurrentRow(0)
        workbench._copy_history()
        assert app.clipboard().image().pixelColor(0, 0).red() == 255
    finally:
        controller.close()


def test_hotkey_persists_only_after_success_and_language_is_saved(
    app: QApplication, tmp_path: Path
) -> None:
    window = Workbench(create_app_icon(), tmp_path)
    window.show_hotkey_state(HotkeyState("Ctrl+Shift+F9"))
    window.show_hotkey_state(HotkeyState("Ctrl+Shift+F9", HotkeyError.CONFLICT))
    window._language.setCurrentIndex(window._language.findData("English"))
    window.settings.sync()
    restored = Workbench(create_app_icon(), tmp_path)
    assert restored.saved_hotkey() == "Ctrl+Shift+F9"
    assert restored._language.currentData() == "English"
    window.close()
    restored.close()
