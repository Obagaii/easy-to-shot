from contextlib import ExitStack
from pathlib import Path
from threading import Lock
from time import monotonic
from wave import open as open_wave


class SystemAudioRecording:
    """Save the default Windows output loopback as PCM, sharing the video's pause boundaries."""

    def __init__(self, path: Path) -> None:
        import pyaudiowpatch as audio

        self._audio = audio
        self._engine = audio.PyAudio()
        self._lock = Lock()
        self._segment_started: float | None = None
        self._segment_start_frame = 0
        self._frames_written = 0
        self.failed = False
        with ExitStack() as resources:
            resources.callback(self._engine.terminate)
            device = self._engine.get_default_wasapi_loopback()
            self._rate = int(device["defaultSampleRate"])
            channels = int(device["maxInputChannels"])
            self._frame_bytes = channels * 2
            self._wave = resources.enter_context(open_wave(str(path), "wb"))
            self._wave.setparams((channels, 2, self._rate, 0, "NONE", "not compressed"))
            resources.callback(self._finish_wave)
            self._stream = self._engine.open(
                format=audio.paInt16, channels=channels, rate=self._rate,
                input=True, input_device_index=int(device["index"]),
                frames_per_buffer=1024, stream_callback=self._write, start=False,
            )
            resources.callback(self._stream.close)
            self._resources = resources.pop_all()

    def start(self) -> None:
        self.set_paused(False)
        self._stream.start_stream()

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            if paused:
                if self._segment_started is not None:
                    self._segment_start_frame += round(
                        (monotonic() - self._segment_started) * self._rate
                    )
                self._segment_started = None
            elif self._segment_started is None:
                self._segment_started = monotonic()

    def _write(self, pcm: bytes, frames: int, timing: dict, _status: int) -> tuple[None, int]:
        with self._lock:
            started = self._segment_started
            if started is None or self.failed:
                return None, self._audio.paContinue
            latency = timing["current_time"] - timing["input_buffer_adc_time"]
            # Loopback providers can skip packets during silence. Keep PCM on the video timeline.
            onset = self._segment_start_frame + round(
                (monotonic() - started - max(0, latency)) * self._rate
            )
            if timing["input_buffer_adc_time"] <= 0:
                onset = self._segment_start_frame + round(
                    (monotonic() - started) * self._rate
                ) - frames
            start = max(self._segment_start_frame, self._frames_written)
            try:
                if onset > start + frames * 2:
                    self._pad_to(onset)
                elif start > onset and (self._frames_written <= self._segment_start_frame):
                    pcm = pcm[(start - onset) * self._frame_bytes:]
                self._pad_to(start)
                self._wave.writeframesraw(pcm)
                self._frames_written += len(pcm) // self._frame_bytes
            except OSError:
                self.failed = True
        return None, self._audio.paContinue

    def _pad_to(self, frame: int) -> None:
        while self._frames_written < frame:
            count = min(self._rate, frame - self._frames_written)
            self._wave.writeframesraw(bytes(count * self._frame_bytes))
            self._frames_written += count

    def _finish_wave(self) -> None:
        if not self.failed:
            self._pad_to(max(1, self._segment_start_frame))

    def close(self) -> None:
        self.set_paused(True)
        self._resources.close()
