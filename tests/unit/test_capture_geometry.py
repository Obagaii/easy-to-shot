import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage

from e2s.capture.geometry import ResizeHandle, ScreenCoordinates, SelectionDrag, SelectionRect
from e2s.capture.service import CaptureFrame
from e2s.capture.session import CaptureSession, CaptureSource


@pytest.mark.parametrize(
    ("origin", "position"),
    [
        ((3.25, 6.5), (23.5, 16.75)),
        ((3.25, 16.75), (23.5, 6.5)),
        ((23.5, 6.5), (3.25, 16.75)),
        ((23.5, 16.75), (3.25, 6.5)),
    ],
)
def test_selection_normalizes_four_drag_directions(origin, position) -> None:
    assert SelectionDrag(origin).update(position, 30, 30) == SelectionRect(3, 6, 24, 17)


@pytest.mark.parametrize(
    ("handle", "position", "expected"),
    [
        (ResizeHandle.TOP_LEFT, (-20, -30), SelectionRect(0, 0, 80, 100)),
        (ResizeHandle.TOP_RIGHT, (500, -30), SelectionRect(20, 0, 200, 100)),
        (ResizeHandle.BOTTOM_LEFT, (-20, 300), SelectionRect(0, 30, 80, 160)),
        (ResizeHandle.BOTTOM_RIGHT, (500, 300), SelectionRect(20, 30, 200, 160)),
    ],
)
def test_corner_resize_preserves_opposite_corner_and_clamps_to_screen(
    handle, position, expected
) -> None:
    selection = SelectionRect(20, 30, 80, 100)
    drag = SelectionDrag((0, 0), selection, handle)
    assert drag.update(position, 200, 160) == expected


@pytest.mark.parametrize(
    ("handle", "position", "expected"),
    [
        (ResizeHandle.TOP, (50, -200), SelectionRect(20, 0, 80, 100)),
        (ResizeHandle.TOP, (-50, 200), SelectionRect(20, 98, 80, 100)),
        (ResizeHandle.RIGHT, (500, 50), SelectionRect(20, 30, 200, 100)),
        (ResizeHandle.RIGHT, (-500, -50), SelectionRect(20, 30, 22, 100)),
        (ResizeHandle.BOTTOM, (-50, 300), SelectionRect(20, 30, 80, 160)),
        (ResizeHandle.BOTTOM, (50, -300), SelectionRect(20, 30, 80, 32)),
        (ResizeHandle.LEFT, (-500, -50), SelectionRect(0, 30, 80, 100)),
        (ResizeHandle.LEFT, (500, 50), SelectionRect(78, 30, 80, 100)),
    ],
)
def test_side_resize_moves_only_its_edge_and_respects_limits(handle, position, expected) -> None:
    selection = SelectionRect(20, 30, 80, 100)
    assert SelectionDrag((0, 0), selection, handle).update(position, 200, 160) == expected


def test_resize_cannot_cross_opposite_corner_and_tiny_drag_can_be_reselected() -> None:
    selection = SelectionRect(5, 5, 17, 17)
    assert SelectionDrag((5, 5), selection, ResizeHandle.TOP_LEFT).update(
        (30, 30), 30, 30
    ) == SelectionRect(15, 15, 17, 17)
    drag = SelectionDrag((2.25, 2.25))
    assert drag.update((3.75, 3.75), 30, 30) is None
    assert drag.update((5.25, 5.25), 30, 30) == SelectionRect(2, 2, 6, 6)


def test_move_preserves_pixel_dimensions_at_fractional_dpi_and_screen_edge() -> None:
    drag = SelectionDrag((30.2, 40.3), SelectionRect(20, 30, 80, 100))
    assert drag.update((31.6, 42.2), 200, 160) == SelectionRect(21, 32, 81, 102)
    assert drag.update((500, -100), 200, 160) == SelectionRect(140, 0, 200, 70)


def test_mixed_dpi_negative_origin_uses_captured_size_and_preserves_edge_pixels() -> None:
    main = ScreenCoordinates(0, 0, 1920, 1080, 1920, 1080)
    left = ScreenCoordinates(-2560, -180, 1707, 960, 2560, 1440)
    assert main.to_source(1919, 1079) == (1919, 1079)
    assert left.to_source(-2560, -180) == (0, 0)

    right_dip = -2560 + 1707
    bottom_dip = -180 + 960
    drag = SelectionDrag(left.to_source(right_dip, bottom_dip))
    selection = drag.update(left.to_source(right_dip - 3, bottom_dip - 3), 2560, 1440)
    assert selection == SelectionRect(2555, 1435, 2560, 1440)
    assert left.to_local_dip(selection.right, selection.bottom) == (1707, 960)

    image = QImage(2560, 1440, QImage.Format.Format_RGB32)
    image.fill(QColor("#234567"))
    image.setPixelColor(2559, 1439, QColor("#fa2d1c"))
    session = CaptureSession(
        CaptureFrame("left", QRect(-2560, -180, 1707, 960), image), CaptureSource.TRAY
    )
    session.set_selection(selection)
    snapshot = session.create_snapshot()
    assert len(snapshot.rgba_pixels) == 5 * 5 * 4
    assert snapshot.to_image().pixelColor(4, 4) == QColor("#fa2d1c")
    assert snapshot.to_image().pixelColor(0, 0) == QColor("#234567")


def test_snapshot_owns_pixels_and_revisions_track_committed_selection() -> None:
    image = QImage(10, 10, QImage.Format.Format_RGB32)
    image.fill(QColor("#abcdef"))
    session = CaptureSession(
        CaptureFrame("test", QRect(0, 0, 10, 10), image), CaptureSource.HOTKEY
    )
    selection = SelectionRect(1, 2, 4, 7)
    session.set_selection(selection)
    snapshot = session.create_snapshot()
    session.set_selection(selection)
    repeated = session.create_snapshot()
    session.set_selection(SelectionRect(3, 4, 8, 7))
    changed = session.create_snapshot()

    assert snapshot.session_id == repeated.session_id == changed.session_id
    assert snapshot.operation_id != repeated.operation_id
    assert snapshot.result_revision == repeated.result_revision < changed.result_revision
    assert (snapshot.width_px, snapshot.height_px) == (3, 5)
    snapshot.to_image().fill(QColor("#000000"))
    assert snapshot.to_image().pixelColor(0, 0) == QColor("#abcdef")
