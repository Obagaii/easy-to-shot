from hashlib import sha256
from io import BytesIO

import pytest

from e2s.capture import ocr_models
from e2s.capture.ocr import ScreenshotRecognizer


def test_model_download_verifies_hash_and_removes_incomplete_files(tmp_path, monkeypatch):
    payload = b"model data"
    files = tuple(ocr_models.ModelFile(f"{name}.onnx", f"https://example.com/{name}",
                                      sha256(payload).hexdigest()) for name in ("det", "rec"))
    monkeypatch.setattr(ocr_models, "model_files", lambda model: files)

    class Response(BytesIO):
        headers = {"Content-Length": str(len(payload))}

    monkeypatch.setattr(ocr_models, "urlopen", lambda *_args, **_kwargs: Response(payload))
    progress = []
    ocr_models.download_model(tmp_path, "tiny", lambda *args: progress.append(args))
    assert ocr_models.model_ready(tmp_path, "tiny")
    assert len(progress) == 2
    monkeypatch.setattr(ocr_models, "urlopen", lambda *_args, **_kwargs: Response(b"corrupt"))
    with pytest.raises(ValueError, match="校验失败"):
        ocr_models.download_model(tmp_path, "tiny", lambda *_: None)
    assert not list((tmp_path / "ocr_models").glob("*.part"))
    assert (tmp_path / "ocr_models" / "det.onnx").read_bytes() == payload


def test_recognizer_switches_to_selected_model_files(tmp_path, monkeypatch):
    import rapidocr

    for item in ocr_models.model_files("tiny"):
        path = tmp_path / "ocr_models" / item.name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"model")
    calls = []
    monkeypatch.setattr(rapidocr, "RapidOCR", lambda **kwargs: calls.append(kwargs) or object())
    recognizer = ScreenshotRecognizer()
    recognizer.set_model(tmp_path, "tiny")
    recognizer._load_engine()
    assert calls[0]["params"]["Det.model_path"].endswith("PP-OCRv6_det_tiny.onnx")
    assert calls[0]["params"]["Rec.model_path"].endswith("PP-OCRv6_rec_tiny.onnx")
