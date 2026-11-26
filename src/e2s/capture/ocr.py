from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from e2s.capture.session import OutputSnapshot

if TYPE_CHECKING:
    from rapidocr import RapidOCR


class OcrError(RuntimeError):
    pass


class ScreenshotRecognizer:
    """Run the bundled OCR pipeline on a worker, with one request at a time."""

    def __init__(self) -> None:
        self._engine: RapidOCR | None = None

    def recognize(self, snapshot: OutputSnapshot) -> str:
        try:
            if self._engine is None:
                self._engine = self._load_engine()
            image = Image.frombytes(
                "RGBA", (snapshot.width_px, snapshot.height_px), snapshot.rgba_pixels
            ).convert("RGB")
            result = self._engine(image)
        except Exception as error:
            # RapidOCR and its ONNX backend use different exception types.
            raise OcrError("文字识别失败，请检查 OCR 组件后重试。") from error
        return "\n".join(line.strip() for line in (result.txts or ()) if line.strip())

    @staticmethod
    def _load_engine() -> "RapidOCR":
        import rapidocr

        models = Path(rapidocr.__file__).parent / "models"
        detector = models / "PP-OCRv6_det_small.onnx"
        recognizer = models / "PP-OCRv6_rec_small.onnx"
        if not detector.is_file() or not recognizer.is_file():
            raise FileNotFoundError("Bundled PP-OCRv6 Small models are missing")
        return rapidocr.RapidOCR(params={
            "Global.log_level": "warning",
            "Global.use_cls": False,
            "Det.model_path": str(detector),
            "Rec.model_path": str(recognizer),
            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        })
