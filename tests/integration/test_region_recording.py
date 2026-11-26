from pathlib import Path
from subprocess import run
from wave import open as open_wave

import pytest
from imageio_ffmpeg import get_ffmpeg_exe
from PIL import Image
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qfluentwidgets import ComboBox

from e2s.annotation.elements import Tool
from e2s.capture.recording_export import RecordingFormat
from e2s.ui.native import region_recording
from e2s.ui.native.region_recording import RegionRecording, Stage


def wait_until(condition) -> None:
    for _ in range(250):
        if condition():
            return
        QTest.qWait(20)
    pytest.fail("Recording did not reach the expected state")


@pytest.mark.parametrize("output_format", list(RecordingFormat))
def test_recording_exports_animated_file_with_live_annotations(
    app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    output_format: RecordingFormat,
) -> None:
    screen = app.primaryScreen()
    if app.platformName() != "windows" or screen is None:
        pytest.skip("Requires the Windows recording overlay")

    raw = QImage(128, 96, QImage.Format.Format_RGB32)
    raw.fill(QColor("#d0e0f0"))
    region = QRect(screen.geometry().topLeft() + QPoint(80, 80), QSize(128, 96))
    panel = RegionRecording(lambda: QImage(raw), tmp_path / "capture", raw.size())
    failures = []
    saved = []
    directories = []
    panel.failed.connect(failures.append)
    panel.completed.connect(saved.append)
    monkeypatch.setattr(
        region_recording.QDesktopServices, "openUrl",
        lambda url: directories.append(Path(url.toLocalFile())) or True,
    )
    try:
        assert panel.present(screen, region)
        assert isinstance(panel._format, ComboBox)
        panel._format.setCurrentText(output_format.name)
        assert panel._mic.isEnabled() == output_format.supports_audio
        assert panel._speaker.isEnabled() == output_format.supports_audio
        panel._record.click()
        QTest.qWait(250)
        assert panel._stage is Stage.RECORDING
        panel._annotate.click()
        assert panel._annotate.isChecked()
        annotation = panel._annotation
        canvas = annotation._canvas
        assert "copy" not in canvas._toolbar._action_buttons
        canvas._toolbar.activate_tool(Tool.PEN)
        local = region.topLeft() - screen.geometry().topLeft()
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=local + QPoint(16, 30))
        QTest.mouseMove(canvas, local + QPoint(100, 30))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=local + QPoint(100, 30))
        line_color = panel._capture_frame().pixelColor(54, 30)
        assert line_color != raw.pixelColor(54, 30)
        panel._annotate.click()
        assert annotation.windowFlags() & Qt.WindowType.WindowTransparentForInput
        assert panel._capture_frame().pixelColor(54, 30) != raw.pixelColor(54, 30)
        panel._pause.click()
        assert panel._stage is Stage.PAUSED
        QTest.qWait(100)
        panel._pause.click()
        QTest.qWait(400)
        panel._record.click()
        wait_until(lambda: panel._stage is Stage.REVIEW or failures)
        assert not failures

        if output_format.supports_audio:
            with open_wave(str(panel._system_audio_path), "wb") as audio:
                audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                audio.writeframes(b"\0\0" * 16000)
            panel._has_system_audio = True
        output = tmp_path / "saved" / f"recording.{output_format.value}"
        output.parent.mkdir()
        panel._export(output)
        wait_until(lambda: panel._export_process is None)
        assert saved == [output], panel._status.text()
        panel._open_directory()
        assert directories == [output.parent]
        assert not list(output.parent.glob(".e2s-*"))
        if output_format.supports_audio:
            decoded = run(
                [get_ffmpeg_exe(), "-v", "error", "-i", str(output),
                 "-map", "0:a:0", "-f", "null", "-"],
                capture_output=True, check=False,
            )
            assert decoded.returncode == 0, decoded.stderr
            decoded = run(
                [get_ffmpeg_exe(), "-v", "error", "-sseof", "-0.2", "-i", str(output),
                 "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                capture_output=True, check=True,
            )
            assert decoded.stdout
            image = Image.frombytes("RGB", (128, 96), decoded.stdout)
        else:
            with Image.open(output) as animation:
                assert animation.is_animated
                animation.seek(animation.n_frames - 1)
                image = animation.convert("RGB")
        assert image.getpixel((54, 30)) == pytest.approx(line_color.getRgb()[:3], abs=16)
        assert image.getpixel((6, 6)) == pytest.approx(raw.pixelColor(6, 6).getRgb()[:3], abs=16)
    finally:
        panel.reject()


def test_recording_toolbar_can_be_dragged_from_its_handle(app: QApplication, tmp_path: Path) -> None:
    screen = app.primaryScreen()
    image = QImage(80, 80, QImage.Format.Format_RGB32)
    panel = RegionRecording(lambda: QImage(image), tmp_path / "capture", image.size())
    region = QRect(screen.availableGeometry().topLeft() + QPoint(500, 300), QSize(80, 80))
    try:
        assert panel.present(screen, region)
        panel.move(screen.availableGeometry().topLeft() + QPoint(100, 100))
        handle = panel._drag_handle
        local = QPointF(handle.rect().center())
        start = QPointF(handle.mapToGlobal(local.toPoint()))
        original = panel.pos()
        for kind, position, button, buttons in (
            (QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
            (QEvent.Type.MouseMove, start + QPointF(40, 30), Qt.MouseButton.NoButton,
             Qt.MouseButton.LeftButton),
            (QEvent.Type.MouseButtonRelease, start + QPointF(40, 30), Qt.MouseButton.LeftButton,
             Qt.MouseButton.NoButton),
        ):
            event = QMouseEvent(kind, local, position, button, buttons, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(handle, event)
        assert panel.pos() == original + QPoint(40, 30)
    finally:
        panel.reject()
