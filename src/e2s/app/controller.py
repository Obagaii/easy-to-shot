from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, QStandardPaths, QThreadPool, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QKeySequence, QScreen
from PySide6.QtWidgets import QApplication, QMessageBox

from e2s.app.capture_output import copy_snapshot, save_snapshot, to_service_snapshot
from e2s.capture.service import CaptureError, capture_frame
from e2s.capture.session import CaptureSession, CaptureSource, OutputSnapshot
from e2s.output.files import SaveResult, build_filename
from e2s.output.ports import TaskResult, TaskState
from e2s.platform.windows.displays import DisplayWatcher, screen_at_cursor
from e2s.platform.windows.file_dialogs import choose_image_save_path
from e2s.platform.windows.hotkeys import DEFAULT_HOTKEY, GlobalHotkey
from e2s.ui.native.overlay import CaptureOverlay
from e2s.ui.native.pinned_image import PinnedImage
from e2s.ui.native.tray import Tray
from e2s.ui.native.workbench import Workbench

_OutputWindow = CaptureOverlay | PinnedImage
_CAPTURE_SETTLE_MS = 100
_SAVE_ERRORS = {
    "overwrite_not_confirmed": "目标文件已存在，请重新选择文件或确认覆盖。",
    "directory_not_writable": "无法写入所选目录，请选择其他目录。",
    "encode_failed": "无法生成 PNG，请重试。",
}


@dataclass(frozen=True, slots=True)
class WindowState:
    flags: Qt.WindowState
    was_active: bool


class AppController(QObject):
    snapshot_ready = Signal(object)
    output_succeeded = Signal(object, object, str)
    _save_finished = Signal(object)

    def __init__(self, app: QApplication, workbench: Workbench, tray: Tray) -> None:
        super().__init__()
        self._app = app
        self._workbench = workbench
        self._tray = tray
        self._hotkey = GlobalHotkey(app, self.start_capture)
        self._capture_screen: QScreen | None = None
        self._capture_source = CaptureSource.HOTKEY
        self._overlay: CaptureOverlay | None = None
        self._previous_window: WindowState | None = None
        self._activate_after_capture = False
        self._is_closing = False
        self._pinned_images: set[PinnedImage] = set()
        self._pending_save: tuple[OutputSnapshot, _OutputWindow] | None = None
        self._save_pool = QThreadPool(self)
        self._save_finished.connect(self._on_save_finished, Qt.ConnectionType.QueuedConnection)

        self._capture_timer = QTimer(self)
        self._capture_timer.setSingleShot(True)
        self._capture_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._capture_timer.timeout.connect(self._show_frozen_frame)
        self._pin_recovery_timer = QTimer(self)
        self._pin_recovery_timer.setSingleShot(True)
        self._pin_recovery_timer.timeout.connect(self._restore_pins)
        self._displays = DisplayWatcher(app, self)
        self._displays.changed.connect(self._on_displays_changed)
        tray.workbench_requested.connect(self.show_workbench)
        tray.capture_requested.connect(lambda: self.start_capture(CaptureSource.TRAY))
        tray.settings_requested.connect(self._show_hotkey_settings)
        tray.quit_requested.connect(self.quit)
        workbench.capture_requested.connect(lambda: self.start_capture(CaptureSource.WORKBENCH))
        workbench.hotkey_requested.connect(self._replace_hotkey)

    def start(self) -> None:
        self._replace_hotkey(QKeySequence(DEFAULT_HOTKEY))
        self._tray.show()
        self.show_workbench()

    @Slot()
    def show_workbench(self) -> None:
        if self._is_closing:
            return
        if self._capture_screen is not None:
            self._activate_after_capture = True
            return
        self._workbench.activate()

    def close(self) -> None:
        if self._is_closing:
            return
        self._is_closing = True
        self._finish_capture()
        self._pin_recovery_timer.stop()
        for pin in tuple(self._pinned_images):
            pin.close()
        self._tray.dismiss_menu()
        self._tray.hide()
        self._workbench.close()
        self._hotkey.close()
        self._save_pool.waitForDone()

    @Slot()
    def quit(self) -> None:
        self.close()
        self._app.quit()

    @Slot()
    def start_capture(self, source: CaptureSource = CaptureSource.HOTKEY) -> None:
        if self._is_closing:
            return
        if self._capture_screen is not None:
            if self._overlay is not None:
                self._overlay.reactivate()
            return

        self._tray.dismiss_menu()
        screen = screen_at_cursor(self._app)
        if screen is None:
            self._tray.notify("未找到鼠标所在的屏幕，请重试。")
            return
        self._capture_screen = screen
        self._capture_source = source

        if source == CaptureSource.WORKBENCH and self._workbench.isVisible():
            self._previous_window = WindowState(
                self._workbench.windowState(), self._workbench.isActiveWindow()
            )
            self._workbench.hide()
        # Let Qt dismiss the triggering UI and Windows compose the updated desktop.
        self._capture_timer.start(_CAPTURE_SETTLE_MS)

    @Slot()
    def _show_frozen_frame(self) -> None:
        if self._capture_screen is None:
            return
        try:
            frame = capture_frame(self._capture_screen)
        except CaptureError as error:
            self._finish_capture()
            self._tray.notify(str(error))
            return

        self._overlay = CaptureOverlay(CaptureSession(frame, self._capture_source))
        self._overlay.cancelled.connect(self._finish_capture)
        self._overlay.copy_requested.connect(self._copy_snapshot)
        self._overlay.save_requested.connect(self._save_snapshot)
        self._overlay.pin_requested.connect(self._pin_snapshot)
        self._overlay.show_on_screen(self._capture_screen)

    @Slot(object)
    def _copy_snapshot(self, snapshot: OutputSnapshot) -> None:
        if self._overlay is not None:
            self._copy_output(snapshot, self._overlay)

    @Slot(object)
    def _save_snapshot(self, snapshot: OutputSnapshot) -> None:
        if self._overlay is not None:
            self._save_output(snapshot, self._overlay)

    @Slot(object)
    def _pin_snapshot(self, snapshot: OutputSnapshot) -> None:
        overlay, screen = self._overlay, self._capture_screen
        if overlay is None or screen is None:
            return
        try:
            pin = PinnedImage(snapshot.to_image())
        except (MemoryError, ValueError):
            overlay.set_output_feedback("无法创建贴图，请缩小选区后重试。")
            return

        self._pinned_images.add(pin)
        pin.closed.connect(lambda: self._pinned_images.discard(pin))
        pin.copy_requested.connect(
            lambda: self._copy_output(replace(snapshot, operation_id=uuid4()), pin)
        )
        pin.save_requested.connect(
            lambda: self._save_output(replace(snapshot, operation_id=uuid4()), pin)
        )
        pin.show_at(screen, overlay.selection_origin(snapshot.selection))
        result = TaskResult(str(snapshot.operation_id), TaskState.SUCCEEDED)
        self._complete_output(snapshot, result, "pin", overlay)

    def _copy_output(self, snapshot: OutputSnapshot, window: _OutputWindow) -> None:
        if not self._has_output_window(window):
            return
        try:
            result = copy_snapshot(snapshot)
        except MemoryError:
            result = TaskResult(str(snapshot.operation_id), TaskState.FAILED)
        if result.state is TaskState.SUCCEEDED:
            self._complete_output(snapshot, result, "copy", window)
        else:
            self._set_output_feedback(window, "无法复制截图，请重试。")

    def _save_output(self, snapshot: OutputSnapshot, window: _OutputWindow) -> None:
        if not self._has_output_window(window):
            return
        if self._pending_save is not None:
            self._set_output_feedback(window, "正在保存上一张截图，请稍后重试。")
            return

        self._pending_save = (snapshot, window)
        is_submitted = False
        try:
            self._set_output_feedback(window, "", is_pending=True)
            target, is_overwrite_confirmed = self._choose_save_target(window)
            if target is None or not self._has_output_window(window):
                return
            self._set_output_feedback(window, "正在保存截图…", is_pending=True)
            self._save_pool.start(
                lambda: self._write_snapshot(snapshot, target, is_overwrite_confirmed)
            )
            is_submitted = True
        finally:
            if not is_submitted:
                self._pending_save = None
                self._set_output_feedback(window, "", is_pending=False)

    def _choose_save_target(self, window: _OutputWindow) -> tuple[Path | None, bool]:
        pictures = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        default_directory = Path(pictures) if pictures else Path.home()
        output_directory = default_directory / "EasyToShot"
        if not output_directory.is_dir():
            output_directory = default_directory
        suggested = output_directory / build_filename(datetime.now())
        target = choose_image_save_path(window, suggested, confirm_overwrite=False)
        if target is None or not self._has_output_window(window):
            return None, False
        if target.suffix.lower() != ".png":
            target = target.with_name(f"{target.name}.png")
        if not target.exists():
            return target, False
        answer = QMessageBox.question(
            window, "覆盖截图", f"已存在同名文件，是否覆盖？\n{target}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            return target, True
        return None, False

    def _write_snapshot(
        self, snapshot: OutputSnapshot, target: Path, is_overwrite_confirmed: bool
    ) -> None:
        try:
            result = save_snapshot(snapshot, target, is_overwrite_confirmed=is_overwrite_confirmed)
        except MemoryError:
            result = SaveResult(
                str(snapshot.operation_id), TaskState.FAILED, error_code="encode_failed"
            )
        self._save_finished.emit(result)

    @Slot(object)
    def _on_save_finished(self, result: SaveResult) -> None:
        if self._pending_save is None:
            return
        (snapshot, window), self._pending_save = self._pending_save, None
        if result.state is TaskState.SUCCEEDED:
            self._set_output_feedback(window, "", is_pending=False)
            self._complete_output(snapshot, result, "save", window)
        else:
            message = _SAVE_ERRORS.get(result.error_code, "无法保存截图，请重试。")
            self._set_output_feedback(window, message, is_pending=False)

    def _has_output_window(self, window: _OutputWindow) -> bool:
        return not self._is_closing and (window is self._overlay or window in self._pinned_images)

    def _set_output_feedback(
        self, window: _OutputWindow, message: str, *, is_pending: bool | None = None
    ) -> None:
        if self._has_output_window(window):
            if isinstance(window, CaptureOverlay):
                window.set_output_feedback(message, is_pending=bool(is_pending))
                return
            if is_pending is not None:
                window.set_save_pending(is_pending)
        if message and not is_pending and not self._is_closing:
            self._tray.notify(message)

    def _complete_output(
        self,
        snapshot: OutputSnapshot,
        result: TaskResult | SaveResult,
        source: str,
        window: _OutputWindow,
    ) -> None:
        if isinstance(window, CaptureOverlay):
            if self._overlay is window:
                self._finish_capture()
            self.snapshot_ready.emit(snapshot)
        # History can subscribe with HistoryService.record_success on a worker queue.
        self.output_succeeded.emit(to_service_snapshot(snapshot), result, source)

    @Slot()
    def _restore_pins(self) -> None:
        areas = [screen.availableGeometry() for screen in self._app.screens()]
        for pin in self._pinned_images:
            pin.restore_visibility(areas)

    @Slot()
    def _on_displays_changed(self) -> None:
        if self._capture_screen is not None:
            self._finish_capture()
            self._tray.notify("屏幕配置已变化，请重新截图。")
        if self._pinned_images and not self._is_closing:
            # Qt may reposition windows after screenRemoved; verify the final geometry.
            self._pin_recovery_timer.start(0)

    @Slot()
    def _finish_capture(self) -> None:
        self._capture_timer.stop()
        self._capture_screen = None
        if self._overlay is not None:
            self._overlay.hide()
            self._overlay.deleteLater()
            self._overlay = None

        previous, self._previous_window = self._previous_window, None
        reactivate, self._activate_after_capture = self._activate_after_capture, False
        if self._is_closing:
            return
        if previous is not None:
            self._workbench.setWindowState(previous.flags)
            self._workbench.show()
            if previous.was_active and not self._workbench.isMinimized():
                self._workbench.activate()
        if reactivate:
            self.show_workbench()

    @Slot()
    def _show_hotkey_settings(self) -> None:
        self.show_workbench()
        self._workbench.focus_hotkey_settings()

    @Slot(QKeySequence)
    def _replace_hotkey(self, sequence: QKeySequence) -> None:
        self._workbench.show_hotkey_state(self._hotkey.replace(sequence))
