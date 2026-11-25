from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QObject, QSize, QTimer, QUrl, Signal
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import (
    QAudioDevice,
    QAudioInput,
    QMediaCaptureSession,
    QMediaFormat,
    QMediaRecorder,
    QVideoFrame,
    QVideoFrameInput,
)


class RecordingSession(QObject):
    """Keep Qt Multimedia, frame timing and encoding on the GUI thread."""

    ready = Signal(object)
    failed = Signal(str)
    elapsed_changed = Signal(int)

    def __init__(
        self, grab: Callable[[], QImage], size: QSize, path: Path, parent: QObject
    ) -> None:
        super().__init__(parent)
        self._grab = grab
        self._path = path
        self._size = QSize(size.width() // 2 * 2, size.height() // 2 * 2)
        self._elapsed_before_pause = 0
        self._clock = QElapsedTimer()
        self._is_finalizing = False
        self._can_write = True
        self._timer = QTimer(self, interval=33)
        self._timer.timeout.connect(self._send_frame)
        self._session = QMediaCaptureSession(self)
        self._recorder = QMediaRecorder(self)
        self._input = QVideoFrameInput(self)
        self._input.readyToSendVideoFrame.connect(self._allow_write)
        self._audio_input = None
        self._session.setRecorder(self._recorder)
        self._session.setVideoFrameInput(self._input)
        self._recorder.setOutputLocation(QUrl.fromLocalFile(str(path)))
        self._recorder.setVideoResolution(self._size)
        self._recorder.setVideoFrameRate(30)
        self._recorder.setQuality(QMediaRecorder.Quality.NormalQuality)
        self._recorder.errorOccurred.connect(self._on_error)
        self._recorder.recorderStateChanged.connect(self._on_state)

    def start(
        self, audio: QAudioDevice | None, *, fps: int = 30, quality: int = 3
    ) -> None:
        self._timer.setInterval(round(1000 / fps))
        self._recorder.setVideoFrameRate(fps)
        self._recorder.setQuality(QMediaRecorder.Quality(quality))
        media_format = QMediaFormat(QMediaFormat.FileFormat.MPEG4)
        media_format.setVideoCodec(QMediaFormat.VideoCodec.H264)
        if audio is not None:
            self._audio_input = QAudioInput(audio, self)
            self._session.setAudioInput(self._audio_input)
            media_format.setAudioCodec(QMediaFormat.AudioCodec.AAC)
        self._recorder.setMediaFormat(media_format)
        self._clock.start()
        self._recorder.record()
        if self._recorder.recorderState() == QMediaRecorder.RecorderState.RecordingState:
            self._timer.start()
            self._send_frame()

    def set_paused(self, paused: bool) -> None:
        if paused:
            self._timer.stop()
            self._elapsed_before_pause += self._clock.elapsed()
            self._recorder.pause()
        else:
            self._clock.restart()
            self._recorder.record()
            self._timer.start()

    def finish(self) -> None:
        self._timer.stop()
        self._is_finalizing = True
        self._recorder.stop()

    def abort(self) -> None:
        self._is_finalizing = False
        self._timer.stop()
        self._recorder.stop()

    def _allow_write(self) -> None:
        self._can_write = True

    def _send_frame(self) -> None:
        elapsed = self._elapsed_before_pause + self._clock.elapsed()
        interval = self._timer.interval()
        self.elapsed_changed.emit(elapsed)
        if not self._can_write:
            return
        image = self._grab()
        if image.isNull():
            self.abort()
            self.failed.emit("录屏区域已失效。")
            return
        if image.size() != self._size:
            image = image.copy(0, 0, self._size.width(), self._size.height())
        frame = QVideoFrame(image.convertToFormat(QImage.Format.Format_RGB32))
        frame.setStartTime(elapsed * 1000)
        frame.setEndTime((elapsed + interval) * 1000)
        self._can_write = False
        if not self._input.sendVideoFrame(frame):
            self._can_write = True

    def _on_state(self, state: QMediaRecorder.RecorderState) -> None:
        if state != QMediaRecorder.RecorderState.StoppedState or not self._is_finalizing:
            return
        self._is_finalizing = False
        try:
            if self._path.stat().st_size > 0:
                self.ready.emit(self._path)
                return
        except OSError:
            pass
        self.failed.emit("没有生成可保存的视频。")

    def _on_error(self, _error: QMediaRecorder.Error, _message: str) -> None:
        self._is_finalizing = False
        self._timer.stop()
        self.failed.emit("无法编码录屏，请检查录制设备和视频编码器。")
