from collections.abc import Callable
from enum import Enum, auto
from pathlib import Path
from shutil import copyfile, which
from tempfile import NamedTemporaryFile, TemporaryDirectory

from PySide6.QtCore import (
    QMimeData,
    QPoint,
    QProcess,
    QRect,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QDesktopServices, QImage, QKeySequence, QScreen, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from e2s.capture.recording import RecordingSession
from e2s.platform.windows.window_capture import exclude_capture_window
from e2s.ui.native.annotation_toolbar import Command, describe_button
from e2s.ui.native.live_capture import LiveSelectionOutline
from e2s.ui.native.toolbar_icons import toolbar_icon


class Stage(Enum):
    READY = auto()
    COUNTDOWN = auto()
    RECORDING = auto()
    PAUSED = auto()
    FINALIZING = auto()
    REVIEW = auto()


class RegionRecording(QDialog):
    failed = Signal(str)
    completed = Signal(object)

    def __init__(self, grab: Callable[[], QImage], destination: Path, size: QSize) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("录像")
        self._destination = destination
        self._stage = Stage.READY
        self._closed = False
        self._working = TemporaryDirectory(prefix="e2s-recording-")
        self._video_path = Path(self._working.name) / "capture.mp4"
        self._elapsed = 0
        self._seconds_left = 0
        self._delay = 0
        self._fps = 30
        self._quality = 3
        self._ffmpeg = which("ffmpeg")
        self._export_process: QProcess | None = None
        self._export_target: Path | None = None
        self._export_temp: Path | None = None
        self._copy_after_export = False
        self._outline = LiveSelectionOutline("#ff4d4f")
        self._region = QRect()
        self._screen: QScreen | None = None
        self._countdown = QTimer(self, interval=1000)
        self._countdown.timeout.connect(self._count_down)
        self._session = RecordingSession(grab, size, self._video_path, self)
        self._session.elapsed_changed.connect(self._show_elapsed)
        self._session.ready.connect(self._enter_review)
        self._session.failed.connect(self.failed)
        self._audio_device = None
        self._player = QMediaPlayer(self)
        self._speaker = QAudioOutput(self)
        self._player.setAudioOutput(self._speaker)

        self.setStyleSheet("""
            QDialog { background: #ffffff; }
            QLabel, QToolButton { color: #262626; }
            QToolButton { border: 0; border-radius: 6px; padding: 3px; }
            QToolButton:hover { background: #e6f4ff; }
            QToolButton::menu-indicator { image: none; width: 0; }
        """)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._video = QVideoWidget(self)
        self._video.setFixedSize(400, 225)
        self._video.hide()
        self._layout.addWidget(self._video)
        self._player.setVideoOutput(self._video)
        self._timeline = QSlider(Qt.Orientation.Horizontal, self)
        self._timeline.setAccessibleName("录像播放位置")
        self._timeline.sliderMoved.connect(self._player.setPosition)
        self._player.positionChanged.connect(self._timeline.setValue)
        self._player.durationChanged.connect(self._duration_changed)
        self._layout.addWidget(self._timeline)
        self._trim_fields = QWidget(self)
        fields = QHBoxLayout(self._trim_fields)
        fields.setContentsMargins(0, 0, 0, 0)
        self._trim_start = self._trim_time("起点（秒）", fields)
        self._trim_end = self._trim_time("终点（秒）", fields)
        self._trim_fields.hide()
        self._layout.addWidget(self._trim_fields)
        self._controls = QHBoxLayout()
        self._layout.addLayout(self._controls)
        self._record = self._button("record_start", "开始录像", ("Ctrl+S",), self._toggle_recording)
        self._pause = self._button("record_pause", "暂停 / 继续", ("Space",), self._toggle_pause)
        self._clock = QLabel("00:00", self)
        self._clock.setMinimumWidth(52)
        self._clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._controls.addWidget(self._clock)
        self._audio = self._button("microphone", "录制音频设备", (), None)
        self._audio.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self._audio)
        menu.aboutToShow.connect(self._list_audio)
        self._audio.setMenu(menu)
        self._options = self._button("record_settings", "录像设置", (), self._show_options)
        self._folder = self._button("record_folder", "打开录像文件夹", (), self._open_directory)
        self._play = self._button("record_start", "播放 / 暂停预览", (), self._toggle_preview)
        self._trim = self._button("record_trim", "裁剪录像", (), self._toggle_trim)
        self._trim.setEnabled(self._ffmpeg is not None)
        if self._ffmpeg is None:
            self._trim.setToolTip("裁剪录像需要 FFmpeg")
        self._save = self._button("save", "保存录像", ("Ctrl+E",), self._save_video)
        self._copy = self._button("copy", "复制录像文件", ("Ctrl+C",), self._copy_video)
        self._button("cancel", "关闭录像", ("Esc",), self.reject)
        self._update_controls()

    def _button(self, icon: str, name: str, keys: tuple[str, ...], action) -> QToolButton:
        button = QToolButton(self)
        button.setIcon(toolbar_icon(icon))
        button.setIconSize(QSize(22, 22))
        button.setFixedSize(32, 32)
        if keys:
            describe_button(button, Command(name, keys))
            for key in keys:
                shortcut = QShortcut(QKeySequence(key), self)
                shortcut.setAutoRepeat(False)
                shortcut.activated.connect(lambda button=button: button.click() if button.isVisible() else None)
        else:
            button.setToolTip(name)
            button.setAccessibleName(name)
        if action is not None:
            button.clicked.connect(action)
        self._controls.addWidget(button)
        return button

    def present(self, screen: QScreen, region: QRect) -> bool:
        self._screen, self._region = screen, region
        self.winId()
        self.windowHandle().setScreen(screen)
        self.adjustSize()
        if exclude_capture_window(int(self.winId())) or self._place_outside_region():
            self.show()
            self._place_outside_region()
            self._outline.show_around(screen, region)
            return True
        return False

    def _place_outside_region(self) -> bool:
        if self._screen is None:
            return False
        area = self._screen.availableGeometry().adjusted(8, 8, -8, -8)
        width, height = self.width() + 16, self.height() + 42
        region = self._region
        x = max(area.left(), min(region.right() - width, area.right() - width))
        y = max(area.top(), min(region.top(), area.bottom() - height))
        for point in (QPoint(x, region.bottom() + 6), QPoint(x, region.top() - height - 6),
                      QPoint(region.right() + 6, y), QPoint(region.left() - width - 6, y)):
            box = QRect(point, QSize(width, height))
            if area.contains(box) and not box.intersects(region):
                self.move(point + QPoint(8, 34))
                return True
        self.move(area.topLeft() + QPoint(0, 32))
        return False

    def start(self) -> None:
        self.activateWindow()
        self._record.setFocus()

    def _toggle_recording(self) -> None:
        if self._stage is Stage.READY:
            if self._delay:
                self._stage = Stage.COUNTDOWN
                self._seconds_left = self._delay
                self._clock.setText(str(self._seconds_left))
                self._countdown.start()
            else:
                self._begin_recording()
        elif self._stage is Stage.COUNTDOWN:
            self._countdown.stop()
            self._stage = Stage.READY
            self._clock.setText("00:00")
        elif self._stage in (Stage.RECORDING, Stage.PAUSED):
            self._stage = Stage.FINALIZING
            self._session.finish()
        self._update_controls()

    def _count_down(self) -> None:
        self._seconds_left -= 1
        if self._seconds_left > 0:
            self._clock.setText(str(self._seconds_left))
            return
        self._countdown.stop()
        self._begin_recording()

    def _begin_recording(self) -> None:
        self._stage = Stage.RECORDING
        self._update_controls()
        self._session.start(self._audio_device, fps=self._fps, quality=self._quality)

    def _toggle_pause(self) -> None:
        if self._stage in (Stage.RECORDING, Stage.PAUSED):
            paused = self._stage is Stage.RECORDING
            self._stage = Stage.PAUSED if paused else Stage.RECORDING
            self._session.set_paused(paused)
            self._update_controls()

    def _show_elapsed(self, milliseconds: int) -> None:
        if milliseconds // 1000 != self._elapsed:
            self._elapsed = milliseconds // 1000
            self._clock.setText(f"{self._elapsed // 60:02d}:{self._elapsed % 60:02d}")

    def _list_audio(self) -> None:
        menu = self._audio.menu()
        menu.clear()
        menu.addAction("静音", lambda: self._select_audio(None))
        for device in QMediaDevices.audioInputs():
            action = menu.addAction(device.description(), lambda device=device: self._select_audio(device))
            action.setCheckable(True)
            action.setChecked(device == self._audio_device)

    def _select_audio(self, device) -> None:
        self._audio_device = device
        self._audio.setIcon(toolbar_icon("microphone" if device is None else "microphone_on"))
        self._audio.setToolTip("录制音频设备" if device is None else device.description())

    def _show_options(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("录像设置")
        layout = QFormLayout(dialog)
        options = []
        for label, low, high, initial in (
            ("开始延迟（秒）", 0, 10, self._delay),
            ("帧率", 10, 60, self._fps),
            ("画质", 0, 4, self._quality),
        ):
            field = QSpinBox(dialog)
            field.setRange(low, high)
            field.setValue(initial)
            layout.addRow(label, field)
            options.append(field)
        apply = QToolButton(dialog)
        apply.setText("应用")
        apply.clicked.connect(dialog.accept)
        layout.addRow(apply)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._delay, self._fps, self._quality = (field.value() for field in options)

    def _open_directory(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._destination.parent)))

    def _enter_review(self, path: Path) -> None:
        self._stage = Stage.REVIEW
        self._outline.hide()
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._video.show()
        self._update_controls()
        self.adjustSize()
        self._place_outside_region()

    def _toggle_preview(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _update_controls(self) -> None:
        selecting = self._stage is Stage.READY
        recording = self._stage in (Stage.RECORDING, Stage.PAUSED)
        review = self._stage is Stage.REVIEW
        is_exporting = self._export_process is not None
        self._audio.setEnabled(selecting)
        self._options.setEnabled(selecting)
        self._pause.setVisible(recording)
        self._timeline.setVisible(review)
        self._trim.setVisible(review)
        self._trim.setEnabled(self._ffmpeg is not None and not is_exporting and self._player.duration() > 0)
        self._copy.setVisible(review)
        self._copy.setEnabled(not is_exporting)
        self._save.setEnabled(not is_exporting)
        self._record.setVisible(not review)
        self._record.setEnabled(self._stage is not Stage.FINALIZING)
        self._record.setIcon(toolbar_icon("record_start" if selecting else "record_stop"))
        label = "开始录像" if selecting else "取消倒计时" if self._stage is Stage.COUNTDOWN else "结束录像"
        describe_button(self._record, Command(label, ("Ctrl+S",)))
        self._pause.setIcon(toolbar_icon("record_start" if self._stage is Stage.PAUSED else "record_pause"))
        self._save.setVisible(review)
        self._play.setVisible(review)

    def _trim_time(self, label: str, fields: QHBoxLayout) -> QDoubleSpinBox:
        field = QDoubleSpinBox(self._trim_fields)
        field.setDecimals(2)
        field.setAccessibleName(label)
        fields.addWidget(QLabel(label, self._trim_fields))
        fields.addWidget(field)
        return field

    def _duration_changed(self, duration: int) -> None:
        self._timeline.setRange(0, duration)
        self._trim_start.setRange(0, duration / 1000)
        self._trim_end.setRange(0, duration / 1000)
        self._trim_end.setValue(duration / 1000)
        self._update_controls()

    def _toggle_trim(self) -> None:
        self._player.pause()
        self._trim_fields.setVisible(self._trim_fields.isHidden())
        self.adjustSize()

    def _save_video(self) -> None:
        if self._stage is not Stage.REVIEW or self._export_process is not None:
            return
        self._player.pause()
        dialog = QFileDialog(self, "保存录像", str(self._destination), "MP4 视频 (*.mp4)")
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setDefaultSuffix("mp4")
        if not dialog.exec():
            return
        path = Path(dialog.selectedFiles()[0])
        if path.suffix.lower() != ".mp4":
            path = path.with_suffix(".mp4")
            if path.exists() and QMessageBox.question(
                self, "覆盖录像", f"已存在同名文件，是否覆盖？\n{path}"
            ) != QMessageBox.StandardButton.Yes:
                return
        self._export(path)

    def _copy_video(self) -> None:
        if self._stage is not Stage.REVIEW or self._export_process is not None:
            return
        self._player.pause()
        directory = self._destination.parent / "EasyToShot"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                dir=directory, prefix=f"{self._destination.stem}_", suffix=".mp4", delete=False
            ) as handle:
                path = Path(handle.name)
        except OSError:
            self._show_export_error("无法创建要复制的录像文件。")
            return
        self._export(path, copy=True)

    def _export(self, path: Path, *, copy: bool = False) -> None:
        self._export_target = path
        self._copy_after_export = copy
        start, end = self._trim_start.value(), self._trim_end.value()
        if not self._trim_fields.isHidden() and end <= start:
            self._finish_export(False, "录像终点必须晚于起点。")
            return
        try:
            with NamedTemporaryFile(dir=path.parent, prefix=".e2s-", suffix=".mp4", delete=False) as handle:
                self._export_temp = Path(handle.name)
            if self._trim_fields.isHidden():
                copyfile(self._video_path, self._export_temp)
                self._finish_export(True)
                return
        except OSError:
            self._finish_export(False)
            return
        process = QProcess(self)
        self._export_process = process
        process.finished.connect(lambda code, _status: self._finish_export(code == 0))
        process.errorOccurred.connect(self._export_failed)
        self._update_controls()
        process.start(self._ffmpeg, [
            "-nostdin", "-loglevel", "error", "-y", "-ss", str(start),
            "-i", str(self._video_path), "-t", str(end - start),
            "-map", "0:v:0", "-map", "0:a?", "-vf", f"fps={self._fps}",
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac", "-movflags", "+faststart", str(self._export_temp),
        ])

    def _export_failed(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._finish_export(False, "无法启动 FFmpeg 裁剪录像。")

    def _finish_export(self, succeeded: bool, message: str = "") -> None:
        process, self._export_process = self._export_process, None
        if process is not None:
            process.deleteLater()
        path, self._export_target = self._export_target, None
        temporary, self._export_temp = self._export_temp, None
        if path is None:
            return
        try:
            if succeeded:
                if temporary is None or not temporary.stat().st_size:
                    raise OSError("Empty video")
                temporary.replace(path)
        except OSError:
            succeeded = False
        finally:
            self._clean_path(temporary)
        if not succeeded:
            if self._copy_after_export:
                self._clean_path(path)
            if not self._closed:
                self._show_export_error(message or "无法生成录像文件，请重试。")
        elif self._copy_after_export:
            data = QMimeData()
            data.setUrls([QUrl.fromLocalFile(str(path))])
            QApplication.clipboard().setMimeData(data)
        if succeeded:
            self.completed.emit(path)
            self.accept()
        elif not self._closed:
            self._update_controls()

    def _show_export_error(self, message: str) -> None:
        QMessageBox.warning(self, "导出录像", message)

    @staticmethod
    def _clean_path(path: Path | None) -> None:
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def done(self, result: int) -> None:
        if not self._closed:
            self._closed = True
            self._countdown.stop()
            self._session.abort()
            self._outline.close()
            if self._export_process is not None:
                self._export_process.kill()
                self._export_process.waitForFinished(500)
                if self._export_process is not None:
                    self._finish_export(False)
            self._player.stop()
            self._player.setSource(QUrl())
            try:
                self._working.cleanup()
            except OSError:
                pass
        super().done(result)
