from pathlib import Path
from unittest.mock import patch

from PIL import Image

from e2s.output.files import OutputFileService
from e2s.output.ports import TaskState
from samples import build_snapshot


def test_save_as_writes_snapshot_and_requires_overwrite_confirmation(tmp_path: Path) -> None:
    snapshot = build_snapshot("op-save", width_px=9, height_px=5)
    service = OutputFileService(tmp_path)
    target = tmp_path / "capture.png"
    target.write_bytes(b"original")

    cancelled = service.save_as(snapshot, target)
    assert cancelled.state is TaskState.CANCELLED
    assert cancelled.error_code == "overwrite_not_confirmed"
    assert target.read_bytes() == b"original"

    result = service.save_as(snapshot, target, is_overwrite_confirmed=True)
    assert result.state is TaskState.SUCCEEDED
    assert result.path == target
    with Image.open(target) as image:
        assert image.size == (9, 5)
        assert image.tobytes() == snapshot.pixels
    assert not list(tmp_path.glob("*.tmp"))


def test_save_as_does_not_replace_file_created_during_encoding(tmp_path: Path) -> None:
    snapshot = build_snapshot("op-save")
    service = OutputFileService(tmp_path)
    target = tmp_path / "concurrent.png"
    encode = service._encode_payload

    def encode_after_create(snapshot):
        target.write_bytes(b"created by another operation")
        return encode(snapshot)

    with patch.object(service, "_encode_payload", side_effect=encode_after_create):
        result = service.save_as(snapshot, target)
    assert result.state is TaskState.CANCELLED
    assert result.error_code == "overwrite_not_confirmed"
    assert target.read_bytes() == b"created by another operation"


def test_save_failure_preserves_existing_file_and_allows_retry(tmp_path: Path) -> None:
    snapshot = build_snapshot("op-save")
    service = OutputFileService(tmp_path)
    target = tmp_path / "capture.png"
    target.write_bytes(b"original")

    with patch.object(OutputFileService, "_write_temp", side_effect=OSError("disk full")):
        failed = service.save_as(snapshot, target, is_overwrite_confirmed=True)
    assert failed.state is TaskState.FAILED
    assert failed.error_code == "write_failed"
    assert target.read_bytes() == b"original"
    assert not list(tmp_path.glob("*.tmp"))

    retried = service.save_as(snapshot, target, is_overwrite_confirmed=True)
    assert retried.state is TaskState.SUCCEEDED
    assert retried.operation_id == failed.operation_id
    with Image.open(target) as image:
        assert image.tobytes() == snapshot.pixels


def test_save_as_missing_directory_reports_failure(tmp_path: Path) -> None:
    result = OutputFileService(tmp_path).save_as(
        build_snapshot("op-save"), tmp_path / "missing" / "capture.png"
    )
    assert result.state is TaskState.FAILED
    assert result.error_code == "directory_not_writable"
    assert result.path is None
