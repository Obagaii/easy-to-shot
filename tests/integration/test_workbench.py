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
        page = workbench._history_page_widget
        assert len(page._entries) == 1
        page._copy(page._entries[0])
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
    for index, route in enumerate(("hotkey", "quick", "history", "ocr", "model", "about")):
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


def test_about_page_displays_application_icon_and_version(app: QApplication, tmp_path: Path) -> None:
    from PySide6.QtWidgets import QLabel

    from e2s import __version__

    icon = create_app_icon()
    window = Workbench(icon, tmp_path)
    try:
        window._navigation.panel.widget("about").click()
        version = window.findChild(QLabel, "aboutVersion")
        about_icon = window.findChild(QLabel, "aboutIcon")
        assert version.text() == f"版本 {__version__}"
        assert about_icon.pixmap() is not None
        assert not about_icon.pixmap().isNull()
        assert all(not icon.pixmap(size, size).isNull() for size in (16, 32, 256))
    finally:
        window.close()


def test_history_filters_selection_pagination_and_clear(app: QApplication, tmp_path: Path, monkeypatch) -> None:
    from datetime import datetime, timezone

    from PySide6.QtWidgets import QMessageBox
    from e2s.output.ports import TaskResult, TaskState
    from e2s.output.service import OutputSnapshot

    window = Workbench(create_app_icon(), tmp_path)
    page = window._history_page_widget
    try:
        for index in range(10):
            snapshot = OutputSnapshot(str(index), str(index), 1, 2, 2, bytes([255, 0, 0, 255] * 4))
            window.history.record_success(snapshot, TaskResult(str(index), TaskState.SUCCEEDED),
                                          "copy" if index < 6 else "save")
        page.refresh()
        assert len(page._entries) == 10
        assert page._next.isEnabled()
        page._select_all()
        page._move_page(1)
        assert len(page._selected) == 10
        assert all(checkbox.isChecked() for checkbox in page._cards.values())
        page._source.setCurrentIndex(page._source.findData("save"))
        assert len(page._entries) == 4
        page._date_filter.setChecked(True)
        page._end.setDate(page._end.date().addDays(-1))
        assert not page._entries
        page._date_filter.setChecked(False)
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
        page._delete_selected()
        assert window.history.store.count() == 0
        page._clear()
        assert window.history.store.count() == 0
    finally:
        window.close()


def test_history_thumbnail_opens_preview_and_switches_screen(app: QApplication, tmp_path: Path) -> None:
    from dataclasses import replace

    from PySide6.QtCore import QPointF, QRect, Qt
    from PySide6.QtGui import QColor, QEnterEvent, QImage
    from PySide6.QtTest import QTest

    from e2s.app.capture_output import to_service_snapshot
    from e2s.capture.geometry import SelectionRect
    from e2s.capture.history_session import serialize_session
    from e2s.capture.service import CaptureFrame
    from e2s.capture.session import CaptureSession, CaptureSource
    from e2s.output.ports import TaskResult, TaskState
    from e2s.ui.native.history_preview import HistoryPreview, HistoryThumbnail

    window = Workbench(create_app_icon(), tmp_path)
    image = QImage(120, 80, QImage.Format.Format_RGBA8888)
    image.fill(QColor("white"))
    image.setPixelColor(2, 2, QColor("red"))
    session = CaptureSession(CaptureFrame("display", QRect(0, 0, 120, 80), image), CaptureSource.TRAY)
    session.set_selection(SelectionRect(20, 20, 100, 60))
    snapshot = replace(to_service_snapshot(session.create_snapshot()), history_data=serialize_session(session))
    window.history.record_success(snapshot, TaskResult(snapshot.operation_id, TaskState.SUCCEEDED), "copy")
    window.refresh_history()
    page = window._history_page_widget
    window._change_page(2)
    window.show()
    app.processEvents()
    try:
        thumbnail = next(widget for widget in page.findChildren(HistoryThumbnail) if widget.isVisible())
        point = QPointF(thumbnail.rect().center())
        app.sendEvent(thumbnail, QEnterEvent(point, point, QPointF(thumbnail.mapToGlobal(point.toPoint()))))
        assert thumbnail._hovered
        QTest.mouseClick(thumbnail, Qt.MouseButton.LeftButton)
        app.processEvents()
        preview = window.findChild(HistoryPreview, "historyPreview")
        assert preview is not None and preview.isVisible()
        assert preview._view._image.size() == session.create_snapshot().to_image().size()
        preview._screen_button.click()
        assert preview._view._image.size() == image.size()
        assert preview._view._image.toImage().pixelColor(2, 2) == QColor("red")
        preview._result_button.click()
        assert preview._view._image.size() == session.create_snapshot().to_image().size()
        preview.close()

        legacy = OutputSnapshot("old", "old", 1, 1, 1, bytes([255, 0, 0, 255]))
        window.history.record_success(legacy, TaskResult("old", TaskState.SUCCEEDED), "save")
        page.refresh()
        entry = next(item for item in page._entries if item.session_id == "old")
        page._preview(entry)
        preview = next(dialog for dialog in window.findChildren(HistoryPreview) if dialog.isVisible())
        assert not preview._screen_button.isEnabled()
        assert preview._screen_button.toolTip()
        preview.close()
    finally:
        window.close()

