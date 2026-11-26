import logging
from collections.abc import Callable
from enum import Enum, auto
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

from imageio_ffmpeg import get_ffmpeg_exe
from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QProcess,
    QRect,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QDesktopServices, QImage, QKeySequence, QMouseEvent, QScreen, QShortcut
from PySide6.QtMultimedia import QAudioDevice, QMediaDevices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import ComboBox

from e2s.capture.recording import RecordingSession
from e2s.capture.recording_export import RecordingFormat, export_arguments
from e2s.platform.windows.recording_audio import SystemAudioRecording
from e2s.platform.windows.window_capture import exclude_capture_window
from e2s.ui.native.annotation_controls import CAPTURE_CONTROLS_STYLE, describe_control
from e2s.ui.native.annotation_toolbar import Command, describe_button
from e2s.ui.native.live_capture import LiveSelectionOutline
from e2s.ui.native.recording_annotation import RecordingAnnotation
from e2s.ui.native.toolbar_icons import toolbar_icon

_LOG = logging.getLogger(__name__)


def _cleanup_recording(directory: TemporaryDirectory, attempts: int = 6) -> None:
    directory.cleanup()
    if not Path(directory.name).exists():
        return
    if attempts > 1:
        QTimer.singleShot(
            100, QApplication.instance(), lambda: _cleanup_recording(directory, attempts - 1)
        )
    else:
        _LOG.warning("Could not remove temporary recording files")


class Stage(Enum):
    READY = auto()
    RECORDING = auto()
    PAUSED = auto()
    FINALIZING = auto()
    REVIEW = auto()
    SAVED = auto()


class RegionRecording(QDialog):
    recording_started = Signal()
    failed = Signal(str)
    completed = Signal(object)

    def __init__(
        self, grab: Callable[[], QImage], destination: Path, size: QSize,
        *, capture_overlay: QWidget | None = None,
    ) -> None:
        super().__init__(
            None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._drag_anchor: QPoint | None = None
        self._excluded_from_capture = False
        self.setWindowTitle("区域录像")
        self._capture_overlay = capture_overlay
        self._grab = grab
        self._size = QSize(size)
        self._destination = destination
        self._directory = destination.parent
        self._stage = Stage.READY
        self._closed = False
        self._starting = False
        self._working = TemporaryDirectory(prefix="e2s-recording-", ignore_cleanup_errors=True)
        self._video_path = Path(self._working.name) / "capture.mp4"
        self._system_audio_path = Path(self._working.name) / "system.wav"
        self._system_audio: SystemAudioRecording | None = None
        self._has_system_audio = False
        self._has_microphone = False
        self._audio_device: QAudioDevice | None = None
        self._annotation: RecordingAnnotation | None = None
        self._export_process: QProcess | None = None
        self._export_target: Path | None = None
        self._export_temp: Path | None = None
        self._outline = LiveSelectionOutline("#ff4d4f")
        self._region = QRect()
        self._screen: QScreen | None = None
        self._session = RecordingSession(self._capture_frame, size, self._video_path, self)
        self._session.elapsed_changed.connect(self._show_elapsed)
        self._session.ready.connect(self._enter_review)
        self._session.failed.connect(self.failed)

        self.setStyleSheet(CAPTURE_CONTROLS_STYLE + """
            QToolButton[recordingToggle="true"]:checked { background: #bae0ff; }
            QLabel { color: #262626; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        surface = QFrame(self)
        surface.setProperty("toolbarSurface", True)
        layout.addWidget(surface)
        surface_layout = QVBoxLayout(surface)
        surface_layout.setContentsMargins(7, 5, 7, 5)
        surface_layout.setSpacing(2)
        self._controls = QHBoxLayout()
        self._controls.setSpacing(4)
        surface_layout.addLayout(self._controls)
        self._drag_handle = QToolButton(self)
        self._drag_handle.setIcon(toolbar_icon("drag_handle"))
        self._drag_handle.setIconSize(QSize(18, 22))
        self._drag_handle.setFixedSize(17, 38)
        describe_control(self._drag_handle, "拖动录像工具栏")
        self._drag_handle.setCursor(Qt.CursorShape.SizeAllCursor)
        self._drag_handle.installEventFilter(self)
        self._controls.addWidget(self._drag_handle)
        self._record = self._button("record_start", "开始录像", ("Ctrl+S",), self._toggle_recording)
        self._pause = self._button("record_pause", "暂停 / 继续", ("Space",), self._toggle_pause)
        self._clock = QLabel("00:00", self)
        self._clock.setMinimumWidth(50)
        self._clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._controls.addWidget(self._clock)
        self._format = ComboBox(self)
        self._format.setMinimumWidth(90)
        self._format.addItems([output_format.name for output_format in RecordingFormat])
        self._format.setAccessibleName("录像保存格式")
        self._format.currentIndexChanged.connect(self._update_controls)
        self._controls.addWidget(self._format)
        self._mic = self._button("microphone", "录制麦克风")
        self._mic.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self._mic)
        menu.aboutToShow.connect(self._list_audio)
        self._mic.setMenu(menu)
        self._speaker = self._button("speaker", "录制系统声音")
        self._speaker.setCheckable(True)
        self._speaker.setProperty("recordingToggle", True)
        self._annotate = self._button("pen", "录像标注", ("Ctrl+D",), self._toggle_annotation)
        self._annotate.setCheckable(True)
        self._annotate.setProperty("recordingToggle", True)
        self._save = self._button("save", "保存录像", ("Ctrl+E",), self._save_video)
        self._button("record_folder", "打开录像文件夹", (), self._open_directory)
        self._button("cancel", "关闭录像", ("Esc",), self.reject)
        self._status = QLabel(self)
        self._status.setWordWrap(True)
        self._status.setMaximumWidth(440)
        self._status.hide()
        surface_layout.addWidget(self._status)
        self._update_controls()
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            self._stage is Stage.READY
            and self._capture_overlay is not None
            and isinstance(watched, QWidget)
            and watched.window() is self._capture_overlay
            and event.type() == QEvent.Type.MouseButtonPress
        ):
            self.reject()
            return False
        if watched is self._drag_handle and isinstance(event, QMouseEvent):
            if (event.type() == QEvent.Type.MouseButtonPress
                    and event.button() == Qt.MouseButton.LeftButton):
                self._drag_anchor = event.globalPosition().toPoint() - self.pos()
                self._drag_handle.grabMouse()
                return True
            if self._drag_anchor is not None and event.type() == QEvent.Type.MouseMove:
                point = event.globalPosition().toPoint() - self._drag_anchor
                screen = QApplication.screenAt(event.globalPosition().toPoint()) or self._screen
                if screen is not None:
                    area = screen.availableGeometry()
                    point.setX(max(area.left(), min(point.x(), area.right() + 1 - self.width())))
                    point.setY(max(area.top(), min(point.y(), area.bottom() + 1 - self.height())))
                if self._excluded_from_capture or not QRect(point, self.size()).intersects(self._region):
                    self.move(point)
                return True
            if self._drag_anchor is not None and event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_anchor = None
                self._drag_handle.releaseMouse()
                return True
        if (
            self._stage in (Stage.RECORDING, Stage.PAUSED)
            and event.type() == QEvent.Type.Show
            and isinstance(watched, QWidget)
            and watched.isWindow()
        ):
            parent = watched.parentWidget()
            while parent is not None:
                if parent in (self, self._annotation):
                    exclude_capture_window(int(watched.winId()))
                    break
                parent = parent.parentWidget()
        return super().eventFilter(watched, event)

    @property
    def _output_format(self) -> RecordingFormat:
        return RecordingFormat(self._format.currentText().lower())

    def _button(
        self, icon: str, name: str, keys: tuple[str, ...] = (),
        action: Callable[[], None] | None = None,
    ) -> QToolButton:
        button = QToolButton(self)
        button.setIcon(toolbar_icon(icon))
        button.setIconSize(QSize(22, 22))
        button.setFixedSize(38, 38)
        if keys:
            describe_button(button, Command(name, keys))
            for key in keys:
                self._bind_shortcut(key, self, button)
        else:
            button.setToolTip(name)
            button.setAccessibleName(name)
        if action is not None:
            button.clicked.connect(action)
        self._controls.addWidget(button)
        return button

    @staticmethod
    def _bind_shortcut(key: str, window: QWidget, button: QToolButton) -> None:
        def trigger() -> None:
            if button.isVisible() and not (
                key == "Space" and isinstance(QApplication.focusWidget(), QPlainTextEdit)
            ):
                button.click()

        shortcut = QShortcut(QKeySequence(key), window)
        shortcut.setAutoRepeat(False)
        shortcut.activated.connect(trigger)

    def present(self, screen: QScreen, region: QRect, anchor: QRect | None = None) -> bool:
        self._screen, self._region = screen, region
        self.winId()
        self.windowHandle().setScreen(screen)
        self.adjustSize()
        self._place_outside_region()
        if anchor is not None:
            area = screen.availableGeometry()
            x = max(area.left(), min(anchor.left(), area.right() + 1 - self.width()))
            y = anchor.bottom() + 5
            if y + self.height() > area.bottom() + 1:
                y = anchor.top() - self.height() - 5
            self.move(x, max(area.top(), y))
        self.show()
        self._excluded_from_capture = exclude_capture_window(int(self.winId()))
        if not self._excluded_from_capture:
            outside_region = not QRect(self.pos(), self.size()).intersects(region)
            if not outside_region:
                self._place_outside_region()
            if not outside_region:
                self.hide()
                return False
        return True

    def _place_outside_region(self) -> bool:
        if self._screen is None:
            return False
        area = self._screen.availableGeometry().adjusted(8, 8, -8, -8)
        width, height = self.width(), self.height()
        region = self._region
        x = max(area.left(), min(region.left(), area.right() - width))
        y = max(area.top(), min(region.top(), area.bottom() - height))
        for point in (
            QPoint(x, region.top() - height - 6), QPoint(x, region.bottom() + 6),
            QPoint(region.right() + 6, y), QPoint(region.left() - width - 6, y),
        ):
            box = QRect(point, QSize(width, height))
            if area.contains(box) and not box.intersects(region):
                if self._excluded_from_capture or not QRect(point, self.size()).intersects(self._region):
                    self.move(point)
                return True
        self.move(area.topLeft())
        return False

    def start(self) -> None:
        self.activateWindow()
        self._record.setFocus()

    def _toggle_recording(self) -> None:
        if self._stage is Stage.READY:
            self._begin_recording()
        elif self._stage in (Stage.RECORDING, Stage.PAUSED):
            self._stage = Stage.FINALIZING
            if self._annotation is not None:
                self._annotation.hide()
            self._finish_system_audio()
            self._update_controls()
            self._session.finish()

    def _begin_recording(self) -> None:
        self._show_status("")
        audio = self._audio_device if self._output_format.supports_audio else None
        if self._output_format.supports_audio and self._speaker.isChecked():
            try:
                self._system_audio = SystemAudioRecording(self._system_audio_path)
                self._system_audio.start()
            except (ImportError, OSError, LookupError, ValueError):
                self._finish_system_audio()
                self._show_status("无法录制系统声音，请检查 Windows 的默认播放设备。")
                return
        self._has_microphone = audio is not None
        self._stage = Stage.RECORDING
        self._starting = True
        self._update_controls()
        self.recording_started.emit()
        if self._screen is not None:
            self._outline.show_around(self._screen, self._region)
        QTimer.singleShot(100, self, lambda: self._start_session(audio))

    def _start_session(self, audio: QAudioDevice | None) -> None:
        if not self._closed and self._stage in (Stage.RECORDING, Stage.PAUSED):
            self._session.start(audio)
            self._starting = False
            self._update_controls()

    def _finish_system_audio(self) -> None:
        audio, self._system_audio = self._system_audio, None
        if audio is None:
            return
        try:
            audio.close()
            self._has_system_audio = not audio.failed
        except OSError:
            self._has_system_audio = False
        if not self._has_system_audio and not self._closed:
            self._show_status("系统声音录制失败，仍可保存画面及已录制的麦克风音频。")

    def _toggle_pause(self) -> None:
        if self._stage not in (Stage.RECORDING, Stage.PAUSED):
            return
        paused = self._stage is Stage.RECORDING
        self._stage = Stage.PAUSED if paused else Stage.RECORDING
        self._session.set_paused(paused)
        if self._system_audio is not None:
            self._system_audio.set_paused(paused)
        self._update_controls()

    def _toggle_annotation(self) -> None:
        editing = self._annotate.isChecked()
        if editing and self._annotation is None and self._screen is not None:
            try:
                self._annotation = RecordingAnnotation(
                    self._screen, self._region, self._size, self._grab
                )
                self._annotation.editing_cancelled.connect(self._annotate.click)
                for key, button in (
                    ("Ctrl+D", self._annotate), ("Ctrl+S", self._record), ("Space", self._pause)
                ):
                    self._bind_shortcut(key, self._annotation, button)
            except MemoryError:
                self._annotate.setChecked(False)
                self._show_status("无法分配录像标注画布。")
                return
        if self._annotation is not None and not self._annotation.set_editing(editing):
            self._annotate.setChecked(False)
            self._show_status("当前系统无法将标注工具栏排除在录像之外。")
        self.raise_()

    def _capture_frame(self) -> QImage:
        frame = self._grab()
        return self._annotation.capture_frame(frame) if self._annotation is not None else frame

    def _show_elapsed(self, milliseconds: int) -> None:
        minutes, seconds = divmod(milliseconds // 1000, 60)
        text = f"{minutes:02d}:{seconds:02d}"
        if self._clock.text() != text:
            self._clock.setText(text)

    def _list_audio(self) -> None:
        menu = self._mic.menu()
        menu.clear()
        devices: list[tuple[str, QAudioDevice | None]] = [("关闭麦克风", None)]
        devices.extend((device.description(), device) for device in QMediaDevices.audioInputs())
        for name, device in devices:
            action = menu.addAction(name, lambda device=device: self._select_audio(device))
            action.setCheckable(True)
            action.setChecked(device == self._audio_device)

    def _select_audio(self, device: QAudioDevice | None) -> None:
        self._audio_device = device
        icon = "microphone" if device is None else "microphone_on"
        self._mic.setIcon(toolbar_icon(icon))
        self._update_controls()

    def _open_directory(self) -> None:
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            self._show_status("无法创建录像文件夹。")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._directory))):
            self._show_status("无法打开录像文件夹。")

    def _enter_review(self, _path: Path) -> None:
        self._stage = Stage.REVIEW
        self._outline.hide()
        self._update_controls()
        self._save.setFocus()

    def _update_controls(self) -> None:
        ready = self._stage is Stage.READY
        recording = self._stage in (Stage.RECORDING, Stage.PAUSED)
        review = self._stage is Stage.REVIEW
        audio_enabled = ready and self._output_format.supports_audio
        for button in (self._mic, self._speaker, self._format):
            button.setVisible(ready)
        self._mic.setEnabled(audio_enabled)
        self._speaker.setEnabled(audio_enabled)
        mic_label = self._audio_device.description() if self._audio_device else "录制麦克风"
        self._mic.setToolTip(mic_label if audio_enabled else "仅 MP4 支持麦克风录音")
        self._speaker.setToolTip("录制系统声音" if audio_enabled else "仅 MP4 支持系统录音")
        self._record.setEnabled(not self._starting)
        self._pause.setEnabled(not self._starting)
        self._pause.setVisible(recording)
        self._annotate.setVisible(recording)
        self._record.setVisible(ready or recording)
        self._record.setIcon(toolbar_icon("record_start" if ready else "record_stop"))
        label = "开始录像" if ready else "结束录像"
        describe_button(self._record, Command(label, ("Ctrl+S",)))
        self._pause.setIcon(toolbar_icon(
            "record_start" if self._stage is Stage.PAUSED else "record_pause"
        ))
        self._save.setVisible(review)
        self._save.setEnabled(self._export_process is None)
        self.adjustSize()

    def _save_video(self) -> None:
        if self._stage is not Stage.REVIEW or self._export_process is not None:
            return
        output_format = self._output_format
        default_path = self._destination.with_suffix(f".{output_format.value}")
        try:
            default_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            default_path = Path.home() / default_path.name
        dialog = QFileDialog(self, "保存录像", str(default_path), output_format.name_filter)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setDefaultSuffix(output_format.value)
        if not dialog.exec():
            return
        path = Path(dialog.selectedFiles()[0])
        if path.suffix.lower() != f".{output_format.value}":
            path = path.with_suffix(f".{output_format.value}")
            if path.exists() and QMessageBox.question(
                self, "覆盖录像", f"已存在同名文件，是否覆盖？\n{path}"
            ) != QMessageBox.StandardButton.Yes:
                return
        self._export(path)

    def _export(self, path: Path) -> None:
        try:
            executable = get_ffmpeg_exe()
            with NamedTemporaryFile(
                dir=path.parent, prefix=".e2s-", suffix=path.suffix, delete=False
            ) as handle:
                self._export_temp = Path(handle.name)
        except (OSError, RuntimeError):
            self._show_status("无法启动录像导出，请检查编码器和目标文件夹。")
            return
        self._export_target = path
        process = QProcess(self)
        self._export_process = process
        process.finished.connect(self._export_finished)
        process.errorOccurred.connect(self._export_failed)
        self._show_status("正在保存录像…")
        self._update_controls()
        process.start(executable, export_arguments(
            self._video_path, self._export_temp, self._output_format,
            system_audio=self._system_audio_path if self._has_system_audio else None,
            has_microphone=self._has_microphone,
        ))

    def _export_finished(self, code: int, status: QProcess.ExitStatus) -> None:
        self._finish_export(code == 0 and status == QProcess.ExitStatus.NormalExit)

    def _export_failed(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._finish_export(False)

    def _finish_export(self, succeeded: bool) -> None:
        process, self._export_process = self._export_process, None
        if process is not None:
            if not succeeded and not self._closed:
                details = bytes(process.readAllStandardError()).decode("utf-8", errors="replace")
                _LOG.warning("Recording export failed: %s", details.strip() or process.errorString())
            process.deleteLater()
        path, self._export_target = self._export_target, None
        temporary, self._export_temp = self._export_temp, None
        if path is None or temporary is None:
            return
        try:
            succeeded = succeeded and not self._closed and temporary.stat().st_size > 0
            if succeeded:
                temporary.replace(path)
        except OSError:
            succeeded = False
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                _LOG.warning("Could not remove temporary recording export")
        if self._closed:
            return
        if succeeded:
            self._directory = path.parent
            self._stage = Stage.SAVED
            self._show_status(f"已保存 {path.name}")
            self.completed.emit(path)
        else:
            self._show_status("无法保存录像，请检查目标文件夹后重试。")
        self._update_controls()

    def _show_status(self, message: str) -> None:
        self._status.setText(message)
        self._status.setVisible(bool(message))
        self.adjustSize()

    def done(self, result: int) -> None:
        if not self._closed:
            self._closed = True
            QApplication.instance().removeEventFilter(self)
            self._session.abort()
            self._finish_system_audio()
            self._outline.close()
            if self._annotation is not None:
                self._annotation.close()
                self._annotation.deleteLater()
                self._annotation = None
            if self._export_process is not None:
                self._export_process.kill()
                self._export_process.waitForFinished(500)
                if self._export_process is not None:
                    self._finish_export(False)
            # The Qt encoder can retain its file handle briefly after stop().
            _cleanup_recording(self._working)
        super().done(QDialog.DialogCode.Accepted if self._stage is Stage.SAVED else result)
