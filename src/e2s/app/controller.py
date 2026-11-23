from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QKeySequence, QScreen
from PySide6.QtWidgets import QApplication

from e2s.capture.service import CaptureError, capture_frame
from e2s.capture.session import CaptureSession, CaptureSource, OutputSnapshot
from e2s.platform.windows.displays import DisplayWatcher, screen_at_cursor
from e2s.platform.windows.hotkeys import DEFAULT_HOTKEY, GlobalHotkey
from e2s.ui.native.overlay import CaptureOverlay
from e2s.ui.native.tray import Tray
from e2s.ui.native.workbench import Workbench

_CAPTURE_SETTLE_MS = 100


@dataclass(frozen=True, slots=True)
class WindowState:
    flags: Qt.WindowState
    was_active: bool


class AppController(QObject):
    snapshot_ready = Signal(object)

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

        self._capture_timer = QTimer(self)
        self._capture_timer.setSingleShot(True)
        self._capture_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._capture_timer.timeout.connect(self._show_frozen_frame)
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
        self._tray.dismiss_menu()
        self._tray.hide()
        self._workbench.close()
        self._hotkey.close()

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
        self._overlay.snapshot_confirmed.connect(self._submit_snapshot)
        self._overlay.show_on_screen(self._capture_screen)

    @Slot(object)
    def _submit_snapshot(self, snapshot: OutputSnapshot) -> None:
        self._finish_capture()
        self.snapshot_ready.emit(snapshot)

    @Slot()
    def _on_displays_changed(self) -> None:
        if self._capture_screen is not None:
            self._finish_capture()
            self._tray.notify("屏幕配置已变化，请重新截图。")

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
