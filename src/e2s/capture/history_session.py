"""Serialize capture state as JSON metadata and separate PNG assets."""

import base64
import json
from collections.abc import Callable
from dataclasses import asdict
from hashlib import sha256

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRect
from PySide6.QtGui import QImage

from e2s.annotation.document import Edit
from e2s.annotation.elements import (
    ImagePatch, Stroke, StrokeStyle, Text, TextStyle, Tool, WatermarkStyle,
)
from e2s.capture.geometry import SelectionRect
from e2s.capture.history_payload import HistoryPayload
from e2s.capture.service import CaptureFrame
from e2s.capture.session import CaptureSession, CaptureSource


def _encode_image(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not image.save(buffer, "PNG"):
        raise ValueError("Unable to encode history image")
    buffer.close()
    return bytes(data)


def _decode_image(data: bytes) -> QImage:
    image = QImage.fromData(data, "PNG")
    if image.isNull():
        raise ValueError("Invalid history image")
    return image


def _element_to_data(element, assets: dict[str, bytes]):
    if element is None:
        return None
    if isinstance(element, ImagePatch):
        image = _encode_image(element.image)
        name = f"patch-{sha256(image).hexdigest()}.png"
        assets[name] = image
        return {"type": "patch", "origin": element.origin, "image": name}
    return {"type": "stroke" if isinstance(element, Stroke) else "text", "data": asdict(element)}


def _element_from_data(value, load_image: Callable[[str], QImage]):
    if value is None:
        return None
    kind = value["type"]
    if kind == "patch":
        return ImagePatch(tuple(value["origin"]), load_image(value["image"]))
    data = value["data"]
    data["tool"] = Tool(data["tool"])
    if kind == "stroke":
        data["points"] = tuple(tuple(point) for point in data["points"])
        data["pressures"] = tuple(data["pressures"])
        data["control"] = tuple(data["control"]) if data["control"] is not None else None
        data["style"] = StrokeStyle(**data["style"])
        return Stroke(**data)
    if kind == "text":
        data["origin"] = tuple(data["origin"])
        data["style"] = TextStyle(**data["style"])
        data["watermark"] = WatermarkStyle(**data["watermark"])
        return Text(**data)
    raise ValueError("Unknown history element")


def serialize_session(session: CaptureSession, output_override: QImage | None = None) -> HistoryPayload:
    selection = session.selection
    if selection is None:
        raise ValueError("Missing selection")
    document = session.begin_annotation()
    assets = {"screen.png": _encode_image(session.frame.image)}

    def edit_data(edit):
        return {"index": edit.index, "before": _element_to_data(edit.before, assets),
                "after": _element_to_data(edit.after, assets)}

    elements = list(document.elements)
    past = list(document._past)
    if output_override is not None:
        patch = ImagePatch((selection.left, selection.top), output_override)
        past.append((Edit(len(elements), None, patch),))
        elements.append(patch)
    rect = session.frame.geometry_dip
    data = {
        "version": 2,
        "screen_id": session.frame.screen_id,
        "geometry": [rect.x(), rect.y(), rect.width(), rect.height()],
        "image": "screen.png",
        "selection": [selection.left, selection.top, selection.right, selection.bottom],
        "elements": [_element_to_data(element, assets) for element in elements],
        "past": [[edit_data(edit) for edit in group] for group in past],
        "future": [] if output_override is not None else [
            [edit_data(edit) for edit in group] for group in document._future
        ],
        "revision": document.revision,
    }
    metadata = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return HistoryPayload(metadata, tuple(assets.items()))


def deserialize_session(
    payload: bytes, geometry: QRect | None = None,
    asset_loader: Callable[[str], bytes] | None = None,
) -> CaptureSession:
    data = json.loads(payload)
    version = data["version"]
    if version not in (1, 2):
        raise ValueError("Unsupported history version")

    def load_image(name: str) -> QImage:
        if version == 1:
            return _decode_image(base64.b64decode(name, validate=True))
        if asset_loader is None:
            raise ValueError("Missing history image loader")
        return _decode_image(asset_loader(name))

    image = load_image(data["image"])
    rect = geometry or QRect(*data["geometry"])
    if rect.isEmpty():
        raise ValueError("Invalid screen geometry")
    session = CaptureSession(CaptureFrame(data["screen_id"], rect, image), CaptureSource.WORKBENCH)
    session.set_selection(SelectionRect(*data["selection"]))
    document = session.begin_annotation()
    document._elements = [_element_from_data(item, load_image) for item in data["elements"]]

    def edit_from_data(edit):
        return Edit(edit["index"], _element_from_data(edit["before"], load_image),
                    _element_from_data(edit["after"], load_image))

    document._past = [tuple(edit_from_data(edit) for edit in group) for group in data["past"]]
    document._future = [tuple(edit_from_data(edit) for edit in group) for group in data["future"]]
    document._revision = data["revision"]
    return session
