import base64
import json
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage

from e2s.annotation.elements import ImagePatch, Stroke, StrokeStyle, Text, Tool
from e2s.app.capture_output import to_service_snapshot
from e2s.capture.geometry import SelectionRect
from e2s.capture.history_session import deserialize_session, serialize_session
from e2s.capture.service import CaptureFrame
from e2s.capture.session import CaptureSession, CaptureSource
from e2s.output.ports import TaskResult, TaskState
from e2s.storage.history import HistoryService, HistoryStatus, HistoryStore


def test_history_restores_full_frame_selection_annotations_and_undo(app, tmp_path: Path) -> None:
    image = QImage(160, 100, QImage.Format.Format_RGBA8888)
    image.fill(QColor("white"))
    image.setPixelColor(3, 4, QColor("blue"))
    session = CaptureSession(CaptureFrame("display", QRect(-160, 0, 160, 100), image), CaptureSource.TRAY)
    selection = SelectionRect(20, 20, 140, 80)
    session.set_selection(selection)
    document = session.begin_annotation()
    document.add(Stroke(Tool.RECTANGLE, ((30, 30), (80, 70)), "#ff0000", 3,
                        style=StrokeStyle(fill_color="#00ff00")))
    document.add(Text((35, 45), "Hello", "#000000", 16))
    patch = QImage(5, 5, QImage.Format.Format_RGBA8888)
    patch.fill(Qt.GlobalColor.yellow)
    document.add(ImagePatch((100, 40), patch))
    document.undo()
    original = session.create_snapshot()
    service_snapshot = to_service_snapshot(original)
    service_snapshot = replace(service_snapshot, history_data=serialize_session(session))
    history = HistoryService(HistoryStore(tmp_path))
    result = history.record_success(service_snapshot, TaskResult("op", TaskState.SUCCEEDED), "copy")
    assert result.status is HistoryStatus.RECORDED
    item = result.item
    payload_path = history.store.session_path(item)
    metadata = json.loads(payload_path.read_bytes())
    assert metadata["image"] == "screen.png"
    screen_path = history.store.session_asset_path(item.history_item_id, "screen.png")
    assert screen_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert QImage(str(screen_path)).pixelColor(3, 4) == QColor("blue")
    restored = deserialize_session(
        payload_path.read_bytes(),
        asset_loader=lambda name: history.store.read_session_asset(item.history_item_id, name),
    )
    assert restored.frame.geometry_dip == session.frame.geometry_dip
    assert restored.frame.image.pixelColor(3, 4) == QColor("blue")
    assert restored.selection == selection
    assert restored.create_snapshot().rgba_pixels == original.rgba_pixels
    assert restored.begin_annotation().can_undo
    assert restored.begin_annotation().can_redo
    restored.begin_annotation().redo()
    restored_patch = restored.begin_annotation().elements[-1].image
    assert restored_patch.size() == patch.size()
    assert restored_patch.pixelColor(2, 2) == patch.pixelColor(2, 2)
    assert history.delete(item.history_item_id) is HistoryStatus.DELETED
    assert not payload_path.exists()
    assert not screen_path.parent.exists()


def test_legacy_embedded_screen_remains_readable(app) -> None:
    image = QImage(10, 10, QImage.Format.Format_RGBA8888)
    image.fill(QColor("blue"))
    session = CaptureSession(CaptureFrame("old", QRect(0, 0, 10, 10), image), CaptureSource.TRAY)
    session.set_selection(SelectionRect(0, 0, 10, 10))
    payload = serialize_session(session)
    data = json.loads(payload.metadata)
    data["version"] = 1
    data["image"] = base64.b64encode(dict(payload.assets)["screen.png"]).decode("ascii")
    restored = deserialize_session(json.dumps(data).encode())
    assert restored.frame.image.pixelColor(0, 0) == QColor("blue")


def test_history_keeps_result_and_cleans_assets_when_screen_write_fails(
    app, tmp_path: Path, monkeypatch
) -> None:
    image = QImage(10, 10, QImage.Format.Format_RGBA8888)
    image.fill(QColor("white"))
    session = CaptureSession(CaptureFrame("display", QRect(0, 0, 10, 10), image), CaptureSource.TRAY)
    session.set_selection(SelectionRect(0, 0, 10, 10))
    snapshot = replace(to_service_snapshot(session.create_snapshot()), history_data=serialize_session(session))
    store = HistoryStore(tmp_path)
    original_write = store._write_image
    monkeypatch.setattr(store, "_write_image", lambda name, data: (
        False if name.endswith("screen.png") else original_write(name, data)
    ))
    result = HistoryService(store).record_success(
        snapshot, TaskResult(snapshot.operation_id, TaskState.SUCCEEDED), "copy"
    )
    assert result.status is HistoryStatus.RECORDED
    assert store.image_path(result.item).is_file()
    assert not store.session_path(result.item).exists()
    assert not store.session_asset_path(result.item.history_item_id, "screen.png").parent.exists()
