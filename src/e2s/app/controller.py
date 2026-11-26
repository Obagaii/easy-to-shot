from dataclasses import dataclass, replace
from datetime import datetime
from functools import partial
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from PIL import Image
from PySide6.QtCore import (
    QObject,
    QPoint,
    QRect,
    QSize,
    QStandardPaths,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QImage, QKeySequence, QScreen
from PySide6.QtWidgets import QApplication, QMessageBox

from e2s.app.capture_output import copy_snapshot, save_snapshot, to_service_snapshot
from e2s.capture.geometry import SelectionRect, move_selection
from e2s.capture.ocr import OcrError, OcrLine, ScreenshotRecognizer
from e2s.capture.qr import CodeDetection, scan_codes
from e2s.capture.service import CaptureError, capture_frame
from e2s.capture.session import CaptureSession, CaptureSource, OutputSnapshot
from e2s.output.files import SaveResult, build_filename
from e2s.output.ports import TaskResult, TaskState
from e2s.platform.windows.displays import (
    DisplayWatcher,
    screen_at_cursor,
)
from e2s.platform.windows.file_dialogs import choose_image_save_path
from e2s.platform.windows.hotkeys import GlobalHotkey
from e2s.platform.windows.uia_selection import WindowsSelector
from e2s.platform.windows.window_capture import scroll_window_below
from e2s.ui.native.live_capture import grab_region
from e2s.ui.native.overlay import CaptureOverlay
from e2s.ui.native.pinned_image import PinnedImage
from e2s.ui.native.recognition_results import RecognitionResults
from e2s.ui.native.region_recording import RegionRecording
from e2s.ui.native.scrolling_capture import ScrollingCapture
from e2s.ui.native.tray import Tray
from e2s.ui.native.workbench import Workbench
from e2s.ui.native.shortcut_dialog import ShortcutDialog

_OutputWindow = CaptureOverlay | PinnedImage | ScrollingCapture
type _OcrKey = tuple[SelectionRect, bytes]
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
    _scan_finished = Signal(object, object, str)
    _ocr_finished = Signal(object, object, str)

    def __init__(self, app: QApplication, workbench: Workbench, tray: Tray) -> None:
        super().__init__()
        self._app = app
        self._workbench = workbench
        self._tray = tray
        self._hotkey = GlobalHotkey(app, self.start_capture)
        self._selector = WindowsSelector(self)
        self._capture_screen: QScreen | None = None
        self._capture_source = CaptureSource.HOTKEY
        self._overlay: CaptureOverlay | None = None
        self._previous_window: WindowState | None = None
        self._live_panel: RegionRecording | ScrollingCapture | None = None
        self._activate_after_capture = False
        self._is_closing = False
        self._pinned_images: set[PinnedImage] = set()
        self._pending_save: tuple[OutputSnapshot, _OutputWindow] | None = None
        self._recognizer = ScreenshotRecognizer()
        self._ocr_request: tuple[CaptureOverlay, _OcrKey] | None = None
        self._ocr_cache: dict[_OcrKey, tuple[OcrLine, ...]] = {}
        self._save_pool = QThreadPool(self)
        self._save_finished.connect(self._on_save_finished, Qt.ConnectionType.QueuedConnection)
        self._scan_finished.connect(self._on_scan_finished, Qt.ConnectionType.QueuedConnection)
        self._ocr_finished.connect(self._on_ocr_finished, Qt.ConnectionType.QueuedConnection)
        self.output_succeeded.connect(
            lambda snapshot, result, source: self._workbench.history.record_success(
                snapshot, result, source, limit=200
            )
        )

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
        self._workbench.history.repair_on_startup(limit=200)
        self._replace_hotkey(QKeySequence(self._workbench.saved_hotkey()))
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
        self._selector.close()
        self._save_pool.waitForDone()

    @Slot()
    def quit(self) -> None:
        self.close()
        self._app.quit()

    @Slot()
    def start_capture(self, source: CaptureSource = CaptureSource.HOTKEY) -> None:
        if isinstance(QApplication.activeModalWidget(), ShortcutDialog):
            return
        if self._is_closing:
            return
        if self._capture_screen is not None:
            if self._live_panel is not None:
                self._live_panel.activateWindow()
            elif self._overlay is not None:
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

        self._overlay = CaptureOverlay(CaptureSession(frame, self._capture_source), self._selector)
        self._overlay.cancelled.connect(self._finish_capture)
        self._overlay.copy_requested.connect(self._copy_snapshot)
        self._overlay.save_requested.connect(self._save_snapshot)
        self._overlay.pin_requested.connect(self._pin_snapshot)
        self._overlay.action_requested.connect(self._run_capture_action)
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
        self._show_pin(snapshot, overlay, screen, overlay.selection_origin(snapshot.selection))

    def _show_pin(
        self, snapshot: OutputSnapshot, overlay: CaptureOverlay, screen: QScreen, origin: QPoint
    ) -> bool:
        try:
            pin = PinnedImage(snapshot.to_image())
        except (MemoryError, ValueError):
            overlay.set_output_feedback("无法创建贴图，请缩小选区后重试。")
            return False

        self._pinned_images.add(pin)
        pin.closed.connect(lambda: self._pinned_images.discard(pin))
        pin.copy_requested.connect(
            lambda: self._copy_output(replace(snapshot, operation_id=uuid4()), pin)
        )
        pin.save_requested.connect(
            lambda: self._save_output(replace(snapshot, operation_id=uuid4()), pin)
        )
        pin.show_at(screen, origin)
        result = TaskResult(str(snapshot.operation_id), TaskState.SUCCEEDED)
        self._complete_output(snapshot, result, "pin", overlay)
        return True

    @Slot(str, object)
    def _run_capture_action(self, name: str, snapshot: OutputSnapshot) -> None:
        overlay, screen = self._overlay, self._capture_screen
        if overlay is None or screen is None:
            return
        if name == "barcode":
            overlay.set_output_feedback("正在扫描二维码…", is_pending=True)
            self._save_pool.start(lambda: self._scan_snapshot(overlay, snapshot))
        elif name == "ocr":
            self._start_ocr(snapshot, overlay)
        elif name in ("scroll", "record"):
            self._start_live_capture(name, snapshot, overlay, screen)

    def _start_ocr(self, snapshot: OutputSnapshot, overlay: CaptureOverlay) -> None:
        key = (snapshot.selection, sha256(snapshot.rgba_pixels).digest())
        cached = self._ocr_cache.get(key)
        if cached is not None:
            self._show_ocr_results(overlay, snapshot, cached)
            return
        if self._ocr_request is not None:
            overlay.set_output_feedback("上一项文字识别仍在运行，请稍后重试。")
            return
        self._ocr_request = overlay, key
        overlay.set_output_feedback("正在本地识别文字…", is_pending=True)
        self._save_pool.start(lambda: self._recognize_snapshot(snapshot))

    def _recognize_snapshot(self, snapshot: OutputSnapshot) -> None:
        try:
            lines = self._recognizer.recognize(snapshot)
        except OcrError as error:
            self._ocr_finished.emit(snapshot, (), str(error))
        else:
            self._ocr_finished.emit(snapshot, lines, "")

    @Slot(object, object, str)
    def _on_ocr_finished(
        self, snapshot: OutputSnapshot, lines: tuple[OcrLine, ...], message: str
    ) -> None:
        request, self._ocr_request = self._ocr_request, None
        if request is None:
            return
        overlay, key = request
        if self._overlay is not overlay:
            return
        if message:
            overlay.set_output_feedback(message)
            return
        self._ocr_cache[key] = lines
        self._show_ocr_results(overlay, snapshot, lines)

    @staticmethod
    def _show_ocr_results(
        overlay: CaptureOverlay, snapshot: OutputSnapshot, lines: tuple[OcrLine, ...]
    ) -> None:
        overlay.set_output_feedback("" if lines else "选区内未识别到文字。")
        if lines:
            dialog = RecognitionResults(lines, partial(overlay.cover_text, snapshot, lines), overlay)
            dialog.finished.connect(overlay.reactivate)
            dialog.open()

    def _scan_snapshot(self, overlay: CaptureOverlay, snapshot: OutputSnapshot) -> None:
        try:
            detections = scan_codes(snapshot)
        except (MemoryError, RuntimeError, ValueError):
            self._scan_finished.emit(overlay, (), "扫描二维码失败，请重试。")
        else:
            message = "" if detections else "选区内未识别到二维码或条码。"
            self._scan_finished.emit(overlay, detections, message)

    @Slot(object, object, str)
    def _on_scan_finished(
        self, overlay: CaptureOverlay, detections: tuple[CodeDetection, ...], message: str
    ) -> None:
        if self._overlay is overlay:
            overlay.set_output_feedback(message)
            overlay.show_code_results(detections)

    def _start_live_capture(
        self, name: str, snapshot: OutputSnapshot, overlay: CaptureOverlay, screen: QScreen
    ) -> None:
        selection = snapshot.selection

        def grab() -> QImage:
            return grab_region(screen, selection)

        if name == "scroll":
            if min(selection.width_px, selection.height_px) < 24:
                overlay.set_output_feedback("滚动截图区域至少需要 24 × 24 像素。")
                return
            window_id = int(overlay.winId())
            source_width, source_height = overlay.capture_size_px()

            def shifted_selection(offset: QPoint) -> SelectionRect:
                dpi = screen.devicePixelRatio()
                return move_selection(
                    selection, round(offset.x() * dpi), round(offset.y() * dpi),
                    source_width, source_height,
                )

            panel = ScrollingCapture(
                lambda offset: grab_region(screen, shifted_selection(offset)),
                lambda horizontal, offset: scroll_window_below(
                    window_id, shifted_selection(offset), horizontal=horizontal
                ),
            )
            panel.captured.connect(
                lambda action, image: self._finish_scroll(
                    action, snapshot, overlay, screen, panel, image
                )
            )
        else:
            if min(selection.width_px, selection.height_px) < 16:
                overlay.set_output_feedback("录屏区域至少需要 16 × 16 像素。")
                return
            movies = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MoviesLocation)
            directory = (Path(movies) if movies else Path.home()) / "EasyToShot"
            default_name = directory / build_filename(datetime.now())
            try:
                panel = RegionRecording(
                    grab, default_name, QSize(selection.width_px, selection.height_px),
                    capture_overlay=overlay,
                )
            except OSError:
                overlay.set_output_feedback("无法创建录屏临时文件。")
                return
            panel.completed.connect(lambda path: self._tray.notify(f"录屏已保存到 {path}"))

        self._live_panel = panel
        panel.finished.connect(lambda _result: self._close_live_panel(panel))
        panel.failed.connect(lambda message: self._live_failed(panel, message))
        region = overlay.selection_geometry(selection)
        if isinstance(panel, RegionRecording):
            toolbar = overlay._canvas._toolbar
            anchor = QRect(toolbar.mapToGlobal(QPoint(0, 0)), toolbar.size())
            panel.recording_started.connect(overlay.hide)
            presented = panel.present(screen, region, anchor)
        else:
            presented = panel.present(screen, region)
        if not presented:
            self._live_failed(panel, "没有可放置控制窗口的区域，请缩小截图选区。")
            return
        if not isinstance(panel, RegionRecording):
            overlay.hide()
        QTimer.singleShot(_CAPTURE_SETTLE_MS, panel, panel.start)

    def _finish_scroll(
        self, action: str, snapshot: OutputSnapshot, overlay: CaptureOverlay, screen: QScreen,
        panel: ScrollingCapture, image: Image.Image,
    ) -> None:
        if self._live_panel is not panel or self._overlay is not overlay:
            return
        try:
            result = replace(
                snapshot, selection=SelectionRect(0, 0, image.width, image.height),
                rgba_pixels=image.tobytes(),
            )
        except MemoryError:
            panel.set_output_feedback("内存不足，无法生成长截图。")
            return
        if action == "copy":
            self._copy_output(result, panel)
        elif action == "save":
            self._save_output(result, panel)
        elif action == "pin" and not self._show_pin(result, overlay, screen, panel.selection_origin):
            panel.set_output_feedback("无法打开长截图贴图。")

    def _live_failed(self, panel: RegionRecording | ScrollingCapture, message: str) -> None:
        panel.reject()
        if self._overlay is not None:
            self._overlay.set_output_feedback(message)

    def _close_live_panel(self, panel: RegionRecording | ScrollingCapture) -> None:
        if self._live_panel is panel:
            self._live_panel = None
            if self._overlay is not None and self._capture_screen is not None:
                if panel.result() == panel.DialogCode.Accepted:
                    self._finish_capture()
                elif not self._overlay.isVisible():
                    self._overlay.show_on_screen(self._capture_screen)
        panel.deleteLater()


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
            self._set_output_feedback(window, "正在保存上一张截图，请稍后重试。", is_pending=False)
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
        default_directory = self._pictures_directory()
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

    @staticmethod
    def _pictures_directory() -> Path:
        pictures = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        return Path(pictures) if pictures else Path.home()

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
            if result.path is not None and not self._is_closing:
                self._tray.notify(f"截图已保存到 {result.path}")
        else:
            message = _SAVE_ERRORS.get(result.error_code, "无法保存截图，请重试。")
            self._set_output_feedback(window, message, is_pending=False)

    def _has_output_window(self, window: _OutputWindow) -> bool:
        return not self._is_closing and (
            window is self._overlay or window is self._live_panel or window in self._pinned_images
        )

    def _set_output_feedback(
        self, window: _OutputWindow, message: str, *, is_pending: bool | None = None
    ) -> None:
        if self._has_output_window(window):
            if isinstance(window, (CaptureOverlay, ScrollingCapture)):
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
        if isinstance(window, (CaptureOverlay, ScrollingCapture)):
            if self._overlay is window or self._live_panel is window:
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
        self._ocr_cache.clear()
        if self._live_panel is not None:
            panel, self._live_panel = self._live_panel, None
            if panel.isVisible():
                panel.reject()
        if self._overlay is not None:
            self._overlay.release_smart_selection()
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
