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


def test_navigation_and_tray_hotkey_entry_select_the_right_page(
    app: QApplication, tmp_path: Path
) -> None:
    window = Workbench(create_app_icon(), tmp_path)
    for index, route in enumerate(("hotkey", "history", "ocr", "model", "about")):
        window._navigation.panel.widget(route).click()
        assert window._pages.currentIndex() == index
    window.focus_hotkey_settings()
    assert window._pages.currentIndex() == 0
    window.close()


def test_configured_shortcuts_apply_to_canvas_and_detect_conflicts(
    app: QApplication, tmp_path: Path, monkeypatch
) -> None:
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QWidget
    from e2s.annotation.document import AnnotationDocument
    from e2s.annotation.elements import Tool
    from e2s.storage.shortcuts import shortcut_settings
    from e2s.ui.native import annotation_toolbar
    from e2s.ui.native.canvas import AnnotationCanvas

    window = Workbench(create_app_icon(), tmp_path)
    assert window._apply_shortcuts("tool/arrow", ("Ctrl+K", "6")) == ""
    assert "箭头" in window._apply_shortcuts("tool/pen", ("Ctrl+K",))
    assert window._apply_shortcuts("tool/pen", ("Delete",))
    assert window._apply_shortcuts("tool/pen", ("Esc",))
    monkeypatch.setattr(annotation_toolbar, "shortcut_settings", lambda: shortcut_settings(tmp_path))
    image = QImage(120, 80, QImage.Format.Format_RGBA8888)
    image.fill(QColor("white"))
    parent = QWidget()
    canvas = AnnotationCanvas(AnnotationDocument(image), QRectF(0, 0, 120, 80), parent)
    canvas.setGeometry(0, 0, 120, 80)
    parent.show()
    canvas.setFocus()
    app.processEvents()
    QTest.keyClick(canvas, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
    assert canvas._tool == Tool.ARROW
    assert "Ctrl+K / 6" in canvas._toolbar._buttons[Tool.ARROW].toolTip()
    QTest.keyClick(canvas, Qt.Key.Key_V)
    QTest.keyClick(canvas, Qt.Key.Key_2)
    assert canvas._tool == Tool.SELECT
    QTest.keyClick(canvas, Qt.Key.Key_6)
    assert canvas._tool == Tool.ARROW
    parent.close()
    window.close()


def test_shortcut_dialog_saves_multiple_bindings_and_allows_removing_them(
    app: QApplication, tmp_path: Path
) -> None:
    from PySide6.QtWidgets import QDialog
    from e2s.storage.shortcuts import load_shortcuts
    from e2s.ui.native.shortcut_dialog import ShortcutDialog

    window = Workbench(create_app_icon(), tmp_path)
    dialog = ShortcutDialog(
        "箭头", ("2",), lambda keys: window._apply_shortcuts("tool/arrow", keys), window
    )
    dialog._add_entry("Ctrl+K")
    dialog._confirm()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert load_shortcuts(window.settings, "tool/arrow", ()) == ("2", "Ctrl+K")
    dialog = ShortcutDialog(
        "箭头", ("2", "Ctrl+K"),
        lambda keys: window._apply_shortcuts("tool/arrow", keys), window,
    )
    while dialog._rows:
        dialog._remove_entry(dialog._rows[0], dialog._buttons[0])
    dialog._confirm()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert load_shortcuts(window.settings, "tool/arrow", ("2",)) == ()
    window.close()


def test_shortcut_recorder_captures_keys_and_preserves_cancel(app: QApplication) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QWidget
    from e2s.ui.native.shortcut_dialog import ShortcutDialog

    saved = []
    parent = QWidget()
    dialog = ShortcutDialog("箭头", ("2",), lambda values: saved.append(values) or "", parent)
    dialog.show()
    app.processEvents()
    dialog._buttons[0].click()
    assert dialog._rows[0].ring.aniGroup.state().name == "Running"
    assert dialog._rows[0].ring.width() == 24
    assert not dialog._confirm_button.isEnabled()
    assert not dialog._add.isEnabled()
    QTest.keyClick(dialog, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
    assert dialog._buttons[0].text() == "Ctrl+K"
    assert dialog._rows[0].ring.aniGroup.state().name == "Stopped"
    assert dialog._rows[0].action.isEnabled()
    dialog._rows[0].action.click()
    assert dialog._confirm_button.isEnabled()
    dialog._add.click()
    QTest.keyClick(dialog, Qt.Key.Key_F6)
    dialog._rows[1].action.click()
    dialog._confirm_button.click()
    assert saved == [("Ctrl+K", "F6")]
    second = ShortcutDialog("箭头", ("2",), lambda values: saved.append(values) or "", parent)
    second.show()
    second._buttons[0].click()
    QTest.keyClick(second, Qt.Key.Key_F7)
    second.reject()
    assert saved == [("Ctrl+K", "F6")]
    parent.close()
