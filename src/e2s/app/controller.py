from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QApplication

from e2s.ui.native.tray import Tray
from e2s.ui.native.workbench import Workbench


class AppController(QObject):
    def __init__(self, app: QApplication, workbench: Workbench, tray: Tray) -> None:
        super().__init__(app)
        self._app = app
        self._workbench = workbench
        self._tray = tray
        tray.workbench_requested.connect(self.show_workbench)
        tray.quit_requested.connect(self.quit)

    @Slot()
    def show_workbench(self) -> None:
        self._workbench.activate()

    @Slot()
    def quit(self) -> None:
        self._tray.hide()
        self._workbench.close()
        self._app.quit()
