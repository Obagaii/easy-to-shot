from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from urllib.request import Request, urlopen

from PySide6.QtCore import QObject, QThreadPool, Signal


@dataclass(frozen=True, slots=True)
class ModelFile:
    name: str
    url: str
    digest: str


_BASE = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv6"
_HASHES = {
    "tiny": ("f42c0fbd294d95eac1a550e131b277dac97462c8025fa4b6c3cec1b7894bd3d5",
             "e16e242de5937ad92609223f19bc2aff3727ee40b095f996907c24749bad251b"),
    "small": ("090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f",
              "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884"),
    "medium": ("92078b7355007ccfffcd4c8cd441a3afd4538904d06881b29a155e1e679907c2",
               "eef444829dbbe18d7fea59a3f6eb75647518d2b3a9568d27c92e42940204894b"),
}
MODEL_LABELS = {
    "tiny": "小 · PP-OCRv6 Tiny",
    "small": "中 · PP-OCRv6 Small",
    "medium": "大 · PP-OCRv6 Medium",
}


def model_files(model: str) -> tuple[ModelFile, ...]:
    hashes = _HASHES[model]
    return tuple(
        ModelFile(f"PP-OCRv6_{kind}_{model}.onnx",
                  f"{_BASE}/{kind}/PP-OCRv6_{kind}_{model}.onnx", digest)
        for kind, digest in zip(("det", "rec"), hashes, strict=True)
    )


def model_paths(root: Path, model: str) -> tuple[Path, ...]:
    if model == "small":
        import rapidocr
        bundled = Path(rapidocr.__file__).parent / "models"
        paths = tuple(bundled / item.name for item in model_files(model))
        if all(path.is_file() for path in paths):
            return paths
    return tuple(root / "ocr_models" / item.name for item in model_files(model))


def model_ready(root: Path, model: str) -> bool:
    return all(path.is_file() and path.stat().st_size > 0 for path in model_paths(root, model))


def download_model(root: Path, model: str, progress) -> None:
    directory = root / "ocr_models"
    directory.mkdir(parents=True, exist_ok=True)
    files = model_files(model)
    for index, item in enumerate(files, 1):
        destination = directory / item.name
        temporary = directory / (item.name + ".part")
        try:
            digest = sha256()
            request = Request(item.url, headers={"User-Agent": "E2S/0.2"})
            with urlopen(request, timeout=60) as response, temporary.open("wb") as output:
                total = int(response.headers.get("Content-Length") or 0)
                received = 0
                while chunk := response.read(1024 * 256):
                    output.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    progress(index, len(files), received, total)
            if digest.hexdigest() != item.digest:
                raise ValueError("模型文件校验失败")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)


class ModelDownloader(QObject):
    progress = Signal(int, int, int, int)
    finished = Signal(str, str)

    def start(self, root: Path, model: str) -> None:
        def run() -> None:
            try:
                download_model(root, model, self.progress.emit)
            except (OSError, ValueError) as error:
                self.finished.emit(model, str(error))
            else:
                self.finished.emit(model, "")
        QThreadPool.globalInstance().start(run)
