from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

from e2s.platform.windows.hotkeys import DEFAULT_HOTKEY, GlobalHotkey
from e2s.ui.native.tray import Tray
from e2s.ui.native.workbench import Workbench


class AppController(QObject):
    capture_requested = Signal()

    def __init__(self, app: QApplication, workbench: Workbench, tray: Tray) -> None:
        super().__init__()
        self._app = app
        self._workbench = workbench
        self._tray = tray
        self._hotkey = GlobalHotkey(app, self.capture_requested.emit)
        tray.workbench_requested.connect(self.show_workbench)
        tray.settings_requested.connect(workbench.show_hotkey_settings)
        tray.quit_requested.connect(self.quit)
        workbench.hotkey_requested.connect(self._replace_hotkey)

    def start(self) -> None:
        self._replace_hotkey(QKeySequence(DEFAULT_HOTKEY))
        self._tray.show()
        self.show_workbench()

    @Slot()
    def show_workbench(self) -> None:
        self._workbench.activate()

    def close(self) -> None:
        self._tray.hide()
        self._workbench.close()
        self._hotkey.close()

    @Slot()
    def quit(self) -> None:
        self.close()
        self._app.quit()

    @Slot(QKeySequence)
    def _replace_hotkey(self, sequence: QKeySequence) -> None:
        self._workbench.show_hotkey_state(self._hotkey.replace(sequence))
