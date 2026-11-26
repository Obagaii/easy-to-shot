from dataclasses import FrozenInstanceError

import pytest

from e2s.output.mock import MockClipboardWriter
from e2s.output.ports import TaskState
from e2s.output.service import OutputService
from samples import build_snapshot


def test_copy_returns_failure_and_preserves_snapshot_for_retry() -> None:
    writer = MockClipboardWriter()
    service = OutputService(writer)
    snapshot = build_snapshot("op-copy", width_px=9, height_px=5)
    writer.fail_next_write = True

    failed = service.copy_image_to_clipboard(snapshot)
    assert failed.state is TaskState.FAILED
    assert failed.error_code == "clipboard_write_failed"
    assert not writer.written

    retried = service.copy_image_to_clipboard(snapshot)
    assert retried.state is TaskState.SUCCEEDED
    assert retried.operation_id == failed.operation_id == snapshot.operation_id
    assert writer.written == [snapshot]


def test_output_snapshot_rejects_invalid_dimensions_and_is_immutable() -> None:
    snapshot = build_snapshot("op-copy")
    with pytest.raises(FrozenInstanceError):
        snapshot.width_px = 4
    with pytest.raises(ValueError):
        build_snapshot("invalid", width_px=0)
