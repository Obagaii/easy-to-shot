from enum import StrEnum
from pathlib import Path


class RecordingFormat(StrEnum):
    MP4 = "mp4"
    GIF = "gif"
    WEBP = "webp"

    @property
    def name_filter(self) -> str:
        return f"{self.name} (*.{self.value})"

    @property
    def supports_audio(self) -> bool:
        return self is RecordingFormat.MP4


def export_arguments(
    source: Path, target: Path, output_format: RecordingFormat,
    *, system_audio: Path | None = None, has_microphone: bool = False,
) -> list[str]:
    """Build a streaming FFmpeg export without the recording controls or editor surfaces."""
    args = ["-nostdin", "-loglevel", "error", "-y", "-i", str(source)]
    if output_format is RecordingFormat.GIF:
        args += [
            "-filter_complex_threads", "1", "-filter_complex",
            (
                "[0:v]fps=15,split[frames][colors];"
                "[colors]palettegen=stats_mode=single[palette];"
                "[frames][palette]paletteuse=new=1:dither=bayer[video]"
            ),
            "-map", "[video]", "-an", "-loop", "0",
        ]
    elif output_format is RecordingFormat.WEBP:
        args += [
            "-map", "0:v:0", "-an", "-vf", "fps=15", "-c:v", "libwebp_anim",
            "-quality", "82", "-loop", "0",
        ]
    elif system_audio is not None:
        args += ["-i", str(system_audio), "-map", "0:v:0", "-c:v", "copy"]
        if has_microphone:
            args += [
                "-filter_complex",
                "[0:a][1:a]amix=inputs=2:duration=longest:dropout_transition=0,apad[audio]",
                "-map", "[audio]",
            ]
        else:
            args += ["-map", "1:a:0", "-af", "apad"]
        args += ["-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart"]
    else:
        args += ["-map", "0", "-c", "copy", "-movflags", "+faststart"]
    return [*args, str(target)]
