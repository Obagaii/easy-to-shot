from dataclasses import dataclass, replace
from datetime import datetime
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
from PySide6.QtGui import QGuiApplication, QImage, QKeySequence, QPainter, QScreen
from PySide6.QtWidgets import QApplication

from e2s.app.capture_output import copy_snapshot, save_snapshot, to_service_snapshot
from e2s.capture.geometry import SelectionRect, move_selection
from e2s.capture.history_session import deserialize_session, serialize_session
from e2s.capture.ocr import OcrError, OcrLine, ScreenshotRecognizer
from e2s.capture.qr import CodeDetection, scan_codes
from e2s.capture.service import CaptureError, CaptureFrame, capture_frame
from e2s.capture.session import CaptureSession, CaptureSource, OutputSnapshot
from e2s.output.files import SaveResult, build_filename
from e2s.output.ports import TaskResult, TaskState
from e2s.platform.windows.displays import (
    DisplayWatcher,
    screen_at_cursor,
)
from e2s.platform.windows.file_dialogs import choose_image_save_path
from e2s.platform.windows.hotkeys import GlobalHotkey
from e2s.platform.windows.global_mouse import GlobalMouseCapture
from e2s.storage.quick_capture import load_quick_capture
from e2s.platform.windows.uia_selection import WindowsSelector
from e2s.platform.windows.window_capture import scroll_window_below
from e2s.ui.native.dialogs import confirm_action, show_warning
from e2s.ui.native.live_capture import grab_region, release_live_capture
from e2s.ui.native.overlay import CaptureOverlay
from e2s.ui.native.pinned_image import PinnedImage
from e2s.ui.native.quick_capture import QuickCaptureOverlay, screen_for_native_point
from e2s.ui.native.quick_capture_dialog import QuickCaptureDialog
from e2s.ui.native.region_recording import RegionRecording
from e2s.ui.native.scrolling_capture import ScrollingCapture
from e2s.ui.native.toolbar_icons import toolbar_icon
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
        self._quick_overlay = None
        self._quick_frame = None
        self._quick_screen = None
        self._quick_mouse = GlobalMouseCapture(
            {action: load_quick_capture(workbench.settings, action) for action in ("copy", "ocr", "translate", "pin")},
            lambda: not self._is_closing and self._capture_screen is None
            and self._quick_overlay is None and not self._has_settings_dialog(),
        )
        self._quick_mouse.drag_event.connect(self._on_quick_drag, Qt.ConnectionType.QueuedConnection)
        if not self._quick_mouse.available:
            workbench._quick_status.setText("无法启用全局鼠标监听，请重新启动应用。")
        self._selector = WindowsSelector(self)
        self._capture_screen: QScreen | None = None
        self._capture_source = CaptureSource.HOTKEY
        self._overlay: CaptureOverlay | None = None
        self._previous_window: WindowState | None = None
        self._live_panel: RegionRecording | ScrollingCapture | None = None
        self._activate_after_capture = False
        self._is_closing = False
        self._pinned_images: set[PinnedImage] = set()
        self._pin_snapshots: dict[PinnedImage, OutputSnapshot] = {}
        self._editing_pin: PinnedImage | None = None
        self._pending_save: tuple[OutputSnapshot, _OutputWindow] | None = None
        self._recognizer = ScreenshotRecognizer()
        self._ocr_request: tuple[CaptureOverlay, _OcrKey, bool] | None = None
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
        workbench.history_edit_requested.connect(self._edit_history)
        workbench.hotkey_requested.connect(self._replace_hotkey)
        workbench.quick_capture_changed.connect(self._set_quick_binding)

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
        self._quick_mouse.close()
        self._close_quick_capture()
        self._selector.close()
        self._save_pool.waitForDone()

    @Slot()
    def quit(self) -> None:
        self.close()
        self._app.quit()

    def _has_settings_dialog(self) -> bool:
        return any(
            dialog.isVisible()
            for dialog_type in (ShortcutDialog, QuickCaptureDialog)
            for dialog in self._workbench.findChildren(dialog_type)
        ) or QApplication.activeModalWidget() is not None

    @Slot()
    def start_capture(self, source: CaptureSource = CaptureSource.HOTKEY) -> None:
        if self._quick_overlay is not None:
            return
        if self._has_settings_dialog():
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

    @Slot(object)
    def _set_quick_binding(self, binding) -> None:
        self._quick_mouse.bindings = binding

    @Slot(str, int, int, str)
    def _on_quick_drag(self, phase: str, x: int, y: int, action: str = "copy") -> None:
        if self._is_closing:
            return
        if phase == "begin":
            if self._capture_screen is not None or self._quick_overlay is not None:
                return
            screen, bounds = screen_for_native_point(self._app, x, y)
            if screen is None or bounds is None:
                self._tray.notify("未找到鼠标所在的屏幕，请重试。")
                return
            try:
                self._quick_frame = capture_frame(screen)
            except CaptureError as error:
                self._tray.notify(str(error))
                return
            self._quick_screen = screen
            self._quick_overlay = QuickCaptureOverlay(screen, self._quick_frame, bounds, (x, y))
            self._quick_overlay.show()
        elif self._quick_overlay is not None:
            self._quick_overlay.update_end(x, y)
            if phase == "finish":
                selection = self._quick_overlay.selection()
                frame, screen = self._quick_frame, self._quick_screen
                self._close_quick_capture()
                if selection is None or frame is None:
                    return
                try:
                    session = CaptureSession(frame, CaptureSource.HOTKEY)
                    session.set_selection(selection)
                    if action in {"ocr", "translate"}:
                        if screen is None:
                            return
                        self._capture_screen = screen
                        self._capture_source = CaptureSource.HOTKEY
                        self._open_session(session)
                        self._start_ocr(session.create_snapshot(), self._overlay, auto_translate=action == "translate")
                        return
                    snapshot = replace(session.create_snapshot(), history_data=serialize_session(session))
                    if action == "pin":
                        if screen is None:
                            return
                        geometry = frame.geometry_dip
                        origin = geometry.topLeft() + QPoint(
                            round(selection.left * geometry.width() / frame.width_px),
                            round(selection.top * geometry.height() / frame.height_px),
                        )
                        self._show_pin(snapshot, None, screen, origin)
                        return
                    result = copy_snapshot(snapshot)
                    if result.state is TaskState.SUCCEEDED:
                        self.snapshot_ready.emit(snapshot)
                        self.output_succeeded.emit(to_service_snapshot(snapshot), result, "copy")
                    else:
                        self._tray.notify("无法复制截图，请重试。")
                except (CaptureError, MemoryError, ValueError):
                    self._tray.notify("无法生成截图，请重试。")

    def _close_quick_capture(self) -> None:
        if self._quick_overlay is not None:
            self._quick_overlay.close()
            self._quick_overlay.deleteLater()
            self._quick_overlay = None
        self._quick_frame = None
        self._quick_screen = None

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

        self._open_session(CaptureSession(frame, self._capture_source))

    def _open_session(self, session: CaptureSession) -> None:
        self._overlay = CaptureOverlay(session, self._selector)
        self._overlay.cancelled.connect(self._finish_capture)
        if self._editing_pin is None:
            self._overlay.copy_requested.connect(self._copy_snapshot)
        else:
            self._overlay.copy_requested.connect(self._apply_pin_edit)
        self._overlay.save_requested.connect(self._save_snapshot)
        self._overlay.pin_requested.connect(self._pin_snapshot)
        self._overlay.action_requested.connect(self._run_capture_action)
        self._overlay.show_on_screen(self._capture_screen)
        if self._editing_pin is not None and self._overlay._canvas is not None:
            button = self._overlay._canvas._toolbar._action_buttons["copy"]
            button.setIcon(toolbar_icon("accept"))
            button.setToolTip("完成编辑（Enter）")
            button.setAccessibleName("完成编辑")

    @Slot(object)
    def _edit_history(self, item) -> None:
        if self._capture_screen is not None or self._is_closing:
            return
        screen = next((screen for screen in self._app.screens()
                       if screen.name() == item["screen_id"]), None)
        screen = screen or screen_at_cursor(self._app) or self._app.primaryScreen()
        try:
            if screen is None:
                raise ValueError("No available screen")
            session = deserialize_session(
                item["payload"], screen.geometry(),
                lambda name: self._workbench.history.store.read_session_asset(
                    item["history_item_id"], name
                ),
            )
        except (ValueError, KeyError, TypeError, OSError):
            show_warning(self._workbench, "截图历史", "无法恢复这条截图的编辑数据。")
            return
        self._capture_screen = screen
        self._capture_source = CaptureSource.WORKBENCH
        self._previous_window = WindowState(
            self._workbench.windowState(), self._workbench.isActiveWindow()
        )
        self._workbench.hide()
        self._open_session(session)

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
        self, snapshot: OutputSnapshot, overlay: CaptureOverlay | None, screen: QScreen, origin: QPoint
    ) -> bool:
        try:
            pin = PinnedImage(snapshot.to_image())
        except (MemoryError, ValueError):
            if overlay is not None:
                overlay.set_output_feedback("无法创建贴图，请缩小选区后重试。")
            else:
                self._tray.notify("无法创建贴图，请缩小选区后重试。")
            return False

        self._pinned_images.add(pin)
        self._pin_snapshots[pin] = snapshot
        pin.closed.connect(lambda: self._forget_pin(pin))
        pin.edit_requested.connect(lambda: self._edit_pin(pin))
        pin.copy_requested.connect(
            lambda: self._copy_output(replace(self._pin_snapshots[pin], operation_id=uuid4()), pin)
        )
        pin.save_requested.connect(
            lambda: self._save_output(replace(self._pin_snapshots[pin], operation_id=uuid4()), pin)
        )
        pin.show_at(screen, origin)
        result = TaskResult(str(snapshot.operation_id), TaskState.SUCCEEDED)
        if overlay is None:
            self.snapshot_ready.emit(snapshot)
        self._complete_output(snapshot, result, "pin", overlay or pin)
        return True

    def _forget_pin(self, pin: PinnedImage) -> None:
        self._pinned_images.discard(pin)
        self._pin_snapshots.pop(pin, None)
        if self._editing_pin is pin:
            self._editing_pin = None

    def _edit_pin(self, pin: PinnedImage) -> None:
        if self._is_closing or self._capture_screen is not None or self._quick_overlay is not None:
            self._tray.notify("请先完成当前截图，再编辑贴图。")
            return
        screen = QGuiApplication.screenAt(pin.geometry().center())
        if screen is None or not screen.geometry().contains(pin.geometry()):
            self._tray.notify("请将贴图完整移入一个屏幕后再编辑。")
            return
        pin.hide()
        try:
            frame = capture_frame(screen)
            geometry = frame.geometry_dip
            rect = pin.geometry().translated(-geometry.x(), -geometry.y())
            left = round(rect.left() * frame.width_px / geometry.width())
            top = round(rect.top() * frame.height_px / geometry.height())
            right = round((rect.right() + 1) * frame.width_px / geometry.width())
            bottom = round((rect.bottom() + 1) * frame.height_px / geometry.height())
            selection = SelectionRect(left, top, right, bottom)
            if not selection.fits(frame.width_px, frame.height_px):
                raise ValueError("Invalid pin selection")
            image = frame.image
            with QPainter(image) as painter:
                painter.drawImage(QRect(left, top, right - left, bottom - top), pin._image)
            session = CaptureSession(CaptureFrame(frame.screen_id, geometry, image), CaptureSource.HOTKEY)
            session.set_selection(selection)
            self._editing_pin = pin
            self._capture_screen = screen
            self._capture_source = CaptureSource.HOTKEY
            self._open_session(session)
        except (CaptureError, MemoryError, ValueError):
            self._finish_capture()
            if pin in self._pinned_images:
                pin.show()
            self._tray.notify("无法打开贴图编辑，请重试。")

    @Slot(object)
    def _apply_pin_edit(self, snapshot: OutputSnapshot) -> None:
        pin = self._editing_pin
        if pin is None or pin not in self._pinned_images:
            return
        try:
            pin.set_image(snapshot.to_image())
        except (MemoryError, ValueError):
            if self._overlay is not None:
                self._overlay.set_output_feedback("无法更新贴图，请重试。")
            return
        self._pin_snapshots[pin] = snapshot
        self._finish_capture()

    @Slot(str, object)
    def _run_capture_action(self, name: str, snapshot: OutputSnapshot) -> None:
        overlay, screen = self._overlay, self._capture_screen
        if overlay is None or screen is None:
            return
        if name == "barcode":
            overlay.set_output_feedback("正在扫描二维码…", is_pending=True)
            self._save_pool.start(lambda: self._scan_snapshot(overlay, snapshot))
        elif name in ("ocr", "translate_text"):
            self._start_ocr(snapshot, overlay, auto_translate=name == "translate_text")
        elif name in ("scroll", "record"):
            self._start_live_capture(name, snapshot, overlay, screen)

    def _start_ocr(
        self, snapshot: OutputSnapshot, overlay: CaptureOverlay, *, auto_translate: bool = False
    ) -> None:
        key = (snapshot.selection, sha256(snapshot.rgba_pixels).digest())
        cached = self._ocr_cache.get(key)
        if cached is not None:
            self._show_ocr_results(overlay, snapshot, cached, auto_translate=auto_translate)
            return
        if self._ocr_request is not None:
            overlay.set_output_feedback("上一项文字识别仍在运行，请稍后重试。")
            return
        self._ocr_request = overlay, key, auto_translate
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
        overlay, key, auto_translate = request
        if self._overlay is not overlay:
            return
        if message:
            overlay.set_output_feedback(message)
            return
        self._ocr_cache[key] = lines
        self._show_ocr_results(overlay, snapshot, lines, auto_translate=auto_translate)

    def _show_ocr_results(
        self, overlay: CaptureOverlay, snapshot: OutputSnapshot, lines: tuple[OcrLine, ...],
        *, auto_translate: bool = False
    ) -> None:
        overlay.set_output_feedback("" if lines else "选区内未识别到文字。")
        if lines:
            language = self._workbench.settings.value("translation/language", "Simplified Chinese")
            overlay.show_ocr_results(snapshot, lines, str(language), auto_translate=auto_translate)

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
            release_live_capture()
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
        if confirm_action(window, "覆盖截图", f"已存在同名文件，是否覆盖？\n{target}"):
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
        self._close_quick_capture()
        if self._capture_screen is not None:
            self._finish_capture()
            self._tray.notify("屏幕配置已变化，请重新截图。")
        if self._pinned_images and not self._is_closing:
            # Qt may reposition windows after screenRemoved; verify the final geometry.
            self._pin_recovery_timer.start(0)

    @Slot()
    def _finish_capture(self) -> None:
        self._capture_timer.stop()
        release_live_capture()
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

        pin, self._editing_pin = self._editing_pin, None
        if pin is not None and pin in self._pinned_images and not self._is_closing:
            pin.show()
            pin.raise_()

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
