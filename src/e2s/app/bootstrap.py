import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication, QMessageBox

from e2s.app.controller import AppController
from e2s.app.single_instance import SingleInstance, SingleInstanceError
from e2s.ui.native.tray import Tray, create_app_icon
from e2s.ui.native.workbench import Workbench


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("EasyToShot")
    app.setApplicationDisplayName("Easy to Shot")
    app.setQuitOnLastWindowClosed(False)

    instance = None
    try:
        data_location = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation
        )
        if not data_location:
            raise SingleInstanceError("无法定位当前用户的应用数据目录。")
        instance = SingleInstance(Path(data_location))
        if not instance.start():
            return 0

        icon = create_app_icon()
        app.setWindowIcon(icon)
        workbench = Workbench(icon)
        tray = Tray(icon)
        if not tray.isSystemTrayAvailable():
            QMessageBox.critical(None, "Easy to Shot", "无法使用系统托盘。")
            return 1
        controller = AppController(app, workbench, tray)
        instance.activation_requested.connect(controller.show_workbench)
        controller.start()
        try:
            return app.exec()
        finally:
            controller.close()
    except (OSError, SingleInstanceError) as error:
        QMessageBox.critical(None, "Easy to Shot", str(error))
        return 1
    finally:
        if instance is not None:
            instance.close()
