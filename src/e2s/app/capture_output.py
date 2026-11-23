from pathlib import Path

from PySide6.QtGui import QImage

from e2s.capture.session import OutputSnapshot
from e2s.output.files import OutputFileService, SaveResult
from e2s.output.ports import ClipboardWriteError, TaskResult
from e2s.output.service import OutputService
from e2s.output.service import OutputSnapshot as ServiceSnapshot
from e2s.platform.windows.clipboard import ClipboardError, copy_image_to_clipboard


class QtClipboardWriter:
    def write_image(self, snapshot: ServiceSnapshot) -> None:
        image = QImage(
            snapshot.pixels,
            snapshot.width_px,
            snapshot.height_px,
            snapshot.width_px * 4,
            QImage.Format.Format_RGBA8888,
        )
        try:
            copy_image_to_clipboard(image.copy())
        except ClipboardError as error:
            raise ClipboardWriteError(str(error)) from error


def _to_service_snapshot(snapshot: OutputSnapshot) -> ServiceSnapshot:
    return ServiceSnapshot(
        operation_id=str(snapshot.operation_id),
        session_id=str(snapshot.session_id),
        revision=snapshot.result_revision,
        width_px=snapshot.width_px,
        height_px=snapshot.height_px,
        pixels=snapshot.rgba_pixels,
    )


def copy_snapshot(snapshot: OutputSnapshot) -> TaskResult:
    """Use the Windows clipboard on the GUI thread."""
    return OutputService(QtClipboardWriter()).copy_image_to_clipboard(
        _to_service_snapshot(snapshot)
    )


def save_snapshot(
    snapshot: OutputSnapshot, target: Path, *, is_overwrite_confirmed: bool
) -> SaveResult:
    """Encode a submitted snapshot and publish the PNG from a worker thread."""
    return OutputFileService(target.parent).save_as(
        _to_service_snapshot(snapshot), target, is_overwrite_confirmed=is_overwrite_confirmed
    )
