from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4

from PySide6.QtGui import QImage

from e2s.annotation.document import AnnotationDocument
from e2s.annotation.elements import ImagePatch
from e2s.annotation.renderer import render_annotations
from e2s.capture.geometry import SelectionRect
from e2s.capture.history_payload import HistoryPayload
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
    history_data: HistoryPayload | None = None

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
        self._annotation: AnnotationDocument | None = None

    @property
    def selection(self) -> SelectionRect | None:
        return self._selection

    def set_selection(self, selection: SelectionRect | None) -> None:
        if selection is not None and not selection.fits(self.frame.width_px, self.frame.height_px):
            raise ValueError("Selection must fit inside the captured pixels")
        if self._selection == selection:
            return
        if self._annotation is not None:
            if selection is None:
                self._revision += self._annotation.revision
                self._annotation = None
            else:
                self._annotation.set_source(
                    self._copy_selection(selection), (selection.left, selection.top)
                )
        self._selection = selection
        self._revision += 1

    def begin_annotation(self) -> AnnotationDocument:
        selection = self._selection
        if selection is None:
            raise CaptureError("请先框选有效的截图区域。")
        if self._annotation is None:
            self._annotation = AnnotationDocument(
                self._copy_selection(selection), (selection.left, selection.top)
            )
        return self._annotation

    def create_snapshot(self, *, include_text_covers: bool = True) -> OutputSnapshot:
        """Capture the current crop, optionally exposing the source text underneath OCR covers."""
        selection = self._selection
        if selection is None:
            raise CaptureError("请先框选有效的截图区域。")
        document = self.begin_annotation()
        elements = document.elements
        if not include_text_covers:
            elements = tuple(element for element in elements if not isinstance(element, ImagePatch))
        image = render_annotations(document.source, elements, document.origin_px)
        # RGBA8888 uses exactly four bytes per pixel with no row padding.
        if image.isNull():
            raise CaptureError("无法生成截图，请缩小选区后重试。")
        return OutputSnapshot(
            uuid4(),
            self._session_id,
            self._revision + document.revision,
            self._source,
            self.frame.screen_id,
            selection,
            bytes(image.constBits()),
        )

    def _copy_selection(self, selection: SelectionRect) -> QImage:
        crop = self.frame.image.copy(
            selection.left, selection.top, selection.width_px, selection.height_px
        )
        if crop.isNull():
            raise CaptureError("无法生成截图，请缩小选区后重试。")
        return crop
