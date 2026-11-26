from collections.abc import Callable
from random import Random
from time import monotonic, sleep

import pytest
from PIL import Image
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qfluentwidgets import SpinBox

from e2s.ui.native.scrolling_capture import ScrollingCapture


def _wait_for(app, ready: Callable[[], bool]) -> None:
    deadline = monotonic() + 2
    while not ready() and monotonic() < deadline:
        app.processEvents()
        sleep(0.008)
    assert ready()


def _page(horizontal: bool) -> Image.Image:
    colors = Random(12).choices(range(256), k=330)
    source = Image.new("RGBA", (120, 330))
    source.putdata([(value, value, value, 255) for value in colors for _ in range(source.width)])
    return source.transpose(Image.Transpose.TRANSPOSE) if horizontal else source


@pytest.mark.parametrize("horizontal", [False, True])
def test_scroll_updates_the_thumbnail_and_exports_the_trimmed_full_image(app, horizontal) -> None:
    screen = app.primaryScreen()
    center = screen.availableGeometry().center()
    region = QRect(center.x() - 130, center.y() - 130, 260, 260)
    source = _page(horizontal)
    offset = 0

    def grab(_delta: QPoint) -> QImage:
        box = (offset, 0, offset + 200, 120) if horizontal else (0, offset, 120, offset + 200)
        frame = source.crop(box)
        return QImage(
            frame.tobytes(), frame.width, frame.height, frame.width * 4,
            QImage.Format.Format_RGBA8888,
        ).copy()

    panel = ScrollingCapture(grab, lambda _horizontal, _delta: True)
    try:
        assert panel.present(screen, region)
        if horizontal:
            panel._sideways.click()
        else:
            panel.start()
        thumbnail = panel._thumbnail
        _wait_for(app, thumbnail.isVisible)
        assert thumbnail.isVisible()
        assert thumbnail.source_extent == 200
        original = thumbnail.viewport().grab().toImage()
        assert QColor(original.pixel(20, 20)).red() != 245

        offset = 70
        _wait_for(app, lambda: thumbnail.source_extent == 270)
        assert thumbnail.source_extent == 270
        assert thumbnail.viewport().grab().toImage() != original
        assert thumbnail._bar.maximum() > 0
        assert thumbnail._bar.value() == thumbnail._bar.maximum()
        assert not thumbnail.geometry().intersects(region)
        if horizontal:
            assert thumbnail.geometry().bottom() < region.top()
        else:
            assert thumbnail.geometry().left() > region.right()

        original_region = panel._region.topLeft()
        panel._nudge(1, 1)
        assert panel._region.topLeft() - original_region == (
            QPoint(1, 0) if horizontal else QPoint(0, 1)
        )
        assert thumbnail.source_extent == 270

        thumbnail._bar.setValue(0)
        first = QPoint(1, 40) if horizontal else QPoint(40, 1)
        moved = QPoint(22, 40) if horizontal else QPoint(40, 22)
        QTest.mousePress(thumbnail.viewport(), Qt.MouseButton.LeftButton, pos=first)
        QTest.mouseMove(thumbnail.viewport(), moved)
        QTest.mouseRelease(thumbnail.viewport(), Qt.MouseButton.LeftButton, pos=moved)
        head, tail = thumbnail.trim
        assert head > 0
        assert tail == 270

        exported = []
        panel.captured.connect(lambda name, image: exported.append((name, image)))
        panel._results[-1].click()
        _wait_for(app, lambda: bool(exported))
        assert exported[0][0] == "copy"
        bounds = (head, 0, tail, 120) if horizontal else (0, head, 120, tail)
        assert exported[0][1].tobytes() == source.crop(bounds).tobytes()
    finally:
        panel.reject()
        panel.deleteLater()
        app.processEvents()

def test_scroll_toolbar_drag_and_interval_control(app) -> None:
    screen = app.primaryScreen()
    area = screen.availableGeometry()
    region = QRect(area.center() - QPoint(100, 100), area.center() + QPoint(100, 100))
    panel = ScrollingCapture(lambda _offset: QImage(), lambda _horizontal, _delta: True)
    try:
        assert panel.present(screen, region)
        assert isinstance(panel._interval, SpinBox)
        interval = panel._interval
        assert interval.upButton.isHidden() and interval.downButton.isHidden()
        interval.setFocus()
        interval.lineEdit().selectAll()
        QTest.keyClicks(interval.lineEdit(), "300")
        QTest.keyClick(interval.lineEdit(), Qt.Key.Key_Return)
        assert panel._auto_timer.interval() == 300
        local_pos = QPointF(interval.rect().center())
        wheel = QWheelEvent(
            local_pos, QPointF(interval.mapToGlobal(local_pos.toPoint())), QPoint(), QPoint(0, 120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(interval, wheel)
        assert panel._auto_timer.interval() == 325
        panel.move(area.topLeft() + QPoint(30, 30))
        handle = panel._drag_handle
        local = QPointF(handle.rect().center())
        start = QPointF(handle.mapToGlobal(local.toPoint()))
        original = panel.pos()
        for kind, position, button, buttons in (
            (QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
            (QEvent.Type.MouseMove, start + QPointF(40, 30), Qt.MouseButton.NoButton,
             Qt.MouseButton.LeftButton),
            (QEvent.Type.MouseButtonRelease, start + QPointF(40, 30), Qt.MouseButton.LeftButton,
             Qt.MouseButton.NoButton),
        ):
            event = QMouseEvent(kind, local, position, button, buttons, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(handle, event)
        assert panel.pos() == original + QPoint(40, 30)
        panel._position_controls()
        assert panel.pos() == original + QPoint(40, 30)
    finally:
        panel.reject()
        panel.deleteLater()
        app.processEvents()
