import os
import subprocess
import sys
from pathlib import Path
from time import monotonic

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from e2s.app.controller import AppController
from e2s.app.single_instance import SingleInstance
from e2s.ui.native.tray import Tray, create_app_icon
from e2s.ui.native.workbench import Workbench


def test_closing_workbench_leaves_tray_available(app: QApplication) -> None:
    icon = create_app_icon()
    workbench = Workbench(icon)
    tray = Tray(icon)
    controller = AppController(app, workbench, tray)

    tray.show()
    controller.show_workbench()
    workbench.close()
    assert not workbench.isVisible()
    assert tray.isVisible()

    tray.workbench_requested.emit()
    assert workbench.isVisible()
    workbench.close()
    tray.hide()


def test_secondary_process_activates_primary(app: QApplication, tmp_path: Path) -> None:
    instance = SingleInstance(tmp_path)
    assert instance.start()
    activations = []
    instance.activation_requested.connect(lambda: activations.append(True))
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; from sys import argv; "
            "from PySide6.QtCore import QCoreApplication; "
            "from e2s.app.single_instance import SingleInstance; "
            "app = QCoreApplication([]); "
            "instance = SingleInstance(Path(argv[1])); "
            "raise SystemExit(2 if instance.start() else 0)",
            str(tmp_path),
        ],
        env=env,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = monotonic() + 5
        while child.poll() is None and monotonic() < deadline:
            QTest.qWait(10)
        _, stderr = child.communicate(timeout=1)
        assert child.returncode == 0, stderr.decode(errors="replace")
        assert activations == [True]
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)
        instance.close()

    replacement = SingleInstance(tmp_path)
    try:
        assert replacement.start()
    finally:
        replacement.close()
