from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4

from PySide6.QtGui import QImage

from e2s.capture.geometry import SelectionRect
from e2s.capture.service import CaptureError, CaptureFrame


class CaptureSource(StrEnum):
    WORKBENCH = "workbench"
    TRAY = "tray"
    HOTKEY = "hotkey"


@dataclass(frozen=True, slots=True)
class OutputSnapshot:
    """Independent, tightly packed RGBA8888 pixels and metadata for one output operation."""

    operation_id: UUID
    session_id: UUID
    result_revision: int
    source: CaptureSource
    screen_id: str
    selection: SelectionRect
    rgba_pixels: bytes

    @property
    def width_px(self) -> int:
        return self.selection.width_px

    @property
    def height_px(self) -> int:
        return self.selection.height_px

    def to_image(self) -> QImage:
        """Return an owned QImage that callers can modify without changing the snapshot."""
        return QImage(
            self.rgba_pixels,
            self.width_px,
            self.height_px,
            self.width_px * 4,
            QImage.Format.Format_RGBA8888,
        ).copy()


class CaptureSession:
    def __init__(self, frame: CaptureFrame, source: CaptureSource) -> None:
        self.frame = frame
        self._source = source
        self._session_id = uuid4()
        self._revision = 0
        self._selection: SelectionRect | None = None

    @property
    def selection(self) -> SelectionRect | None:
        return self._selection

    def set_selection(self, selection: SelectionRect | None) -> None:
        if selection is not None and not selection.fits(self.frame.width_px, self.frame.height_px):
            raise ValueError("Selection must fit inside the captured pixels")
        if self._selection != selection:
            self._selection = selection
            self._revision += 1

    def create_snapshot(self) -> OutputSnapshot:
        selection = self._selection
        if selection is None:
            raise CaptureError("请先框选有效的截图区域。")
        crop = self.frame.image.copy(
            selection.left, selection.top, selection.width_px, selection.height_px
        )
        image = crop.convertToFormat(QImage.Format.Format_RGBA8888)
        # RGBA8888 uses exactly four bytes per pixel with no row padding.
        if image.isNull():
            raise CaptureError("无法生成截图，请缩小选区后重试。")
        return OutputSnapshot(
            uuid4(),
            self._session_id,
            self._revision,
            self._source,
            self.frame.screen_id,
            selection,
            bytes(image.constBits()),
        )
