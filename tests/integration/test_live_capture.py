import sys
from types import SimpleNamespace

import numpy as np
from PySide6.QtGui import QColor

from e2s.capture.geometry import SelectionRect
from e2s.ui.native import live_capture


def test_live_capture_uses_matching_display_reuses_frame_and_releases(monkeypatch):
    pixels = np.zeros((4, 5, 3), dtype=np.uint8)
    pixels[1, 1] = (255, 0, 0)
    pixels[2, 2] = (0, 255, 0)
    calls = []
    camera = SimpleNamespace(
        grab=lambda **kwargs: calls.append(kwargs) or pixels,
        release=lambda: calls.append("released"),
    )
    factory = SimpleNamespace(outputs=[
        [SimpleNamespace(devicename="other")],
        [SimpleNamespace(devicename="DISPLAY2")],
    ])
    dxcam = SimpleNamespace(
        DXFactory=lambda: factory,
        create=lambda **kwargs: calls.append(kwargs) or camera,
    )
    monkeypatch.setitem(sys.modules, "dxcam", dxcam)
    screen = SimpleNamespace(name=lambda: "display2")
    live_capture.release_live_capture()
    try:
        first = live_capture.grab_region(screen, SelectionRect(1, 1, 3, 3))
        second = live_capture.grab_region(screen, SelectionRect(2, 2, 4, 4))
        assert first.pixelColor(0, 0) == QColor("red")
        assert second.pixelColor(0, 0) == QColor("lime")
        assert calls == [
            {"device_idx": 1, "output_idx": 0, "output_color": "RGB"},
            {"new_frame_only": False},
            {"new_frame_only": False},
        ]
    finally:
        live_capture.release_live_capture()
    assert calls[-1] == "released"
