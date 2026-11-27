from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from e2s.annotation.elements import Point
from e2s.capture.session import OutputSnapshot
from e2s.capture.ocr_models import model_paths, model_ready

if TYPE_CHECKING:
    from rapidocr import RapidOCR


@dataclass(frozen=True, slots=True)
class OcrLine:
    text: str
    corners: tuple[Point, ...]


class OcrError(RuntimeError):
    pass


class ScreenshotRecognizer:
    """Run the bundled OCR pipeline on a worker, with one request at a time."""

    def __init__(self) -> None:
        self._engine: RapidOCR | None = None
        self._model = "small"
        self._model_root: Path | None = None

    def set_model(self, root: Path, model: str) -> None:
        if (root, model) != (self._model_root, self._model):
            self._model_root, self._model = root, model
            self._engine = None

    def recognize(self, snapshot: OutputSnapshot) -> tuple[OcrLine, ...]:
        try:
            if self._engine is None:
                self._engine = self._load_engine()
            image = Image.frombytes(
                "RGBA", (snapshot.width_px, snapshot.height_px), snapshot.rgba_pixels
            ).convert("RGB")
            result = self._engine(image)
            if result.boxes is None or not result.txts:
                return ()
            lines = []
            for text, box in zip(result.txts, result.boxes, strict=True):
                text = " ".join(text.split())
                corners = tuple((float(x), float(y)) for x, y in box)
                if text and len(corners) == 4 and all(
                    isfinite(value) for corner in corners for value in corner
                ):
                    lines.append(OcrLine(text, corners))
        except Exception as error:
            # RapidOCR and its ONNX backend use different exception types.
            raise OcrError("文字识别失败，请检查 OCR 组件后重试。") from error
        return tuple(lines)

    def _load_engine(self) -> "RapidOCR":
        import rapidocr

        root = self._model_root or Path(rapidocr.__file__).parent
        if not model_ready(root, self._model):
            raise FileNotFoundError("Selected OCR models are missing")
        detector, recognizer = model_paths(root, self._model)
        return rapidocr.RapidOCR(params={
            "Global.log_level": "warning",
            "Global.use_cls": False,
            "Det.model_path": str(detector),
            "Rec.model_path": str(recognizer),
            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        })
