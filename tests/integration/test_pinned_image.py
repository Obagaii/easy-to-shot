import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest

from e2s.capture.geometry import ResizeHandle
from e2s.ui.native.pinned_image import PinnedImage
from e2s.ui.native.resize_handles import resize_cursor

_LEFT = Qt.MouseButton.LeftButton
_NO_BUTTON = Qt.MouseButton.NoButton
_NO_MODIFIER = Qt.KeyboardModifier.NoModifier


def test_pin_windows_can_move_zoom_and_close_independently(app) -> None:
    screen = app.primaryScreen()
    origin = screen.availableGeometry().topLeft() + QPoint(60, 60)
    image = QImage(96, 48, QImage.Format.Format_RGBA8888)
    image.fill(QColor("#4b9fc7"))
    first = PinnedImage(image)
    second = PinnedImage(image)
    try:
        first.show_at(screen, origin)
        second.show_at(screen, origin + QPoint(200, 100))
        assert first.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        assert first.isVisible() and second.isVisible()
        second_geometry = second.geometry()
        size = first.size()

        local = QPointF(first.rect().center())
        initial = QPointF(first.mapToGlobal(local.toPoint()))
        moved = initial + QPointF(30, 20)
        for event_type, global_pos, button, buttons in (
            (QEvent.Type.MouseButtonPress, initial, _LEFT, _LEFT),
            (QEvent.Type.MouseMove, moved, _NO_BUTTON, _LEFT),
            (QEvent.Type.MouseButtonRelease, moved, _LEFT, _NO_BUTTON),
        ):
            event = QMouseEvent(event_type, local, global_pos, button, buttons, _NO_MODIFIER)
            app.sendEvent(first, event)
        assert first.pos() == origin + QPoint(30, 20)

        zoomed_sizes = []
        for delta in (120, -120):
            global_pos = QPointF(first.mapToGlobal(local.toPoint()))
            wheel = QWheelEvent(
                local, global_pos, QPoint(), QPoint(0, delta), _NO_BUTTON,
                _NO_MODIFIER, Qt.ScrollPhase.NoScrollPhase, False,
            )
            app.sendEvent(first, wheel)
            assert abs(first.width() - 2 * first.height()) <= 1
            zoomed_sizes.append(first.size())
        assert zoomed_sizes[0].width() > size.width()
        assert zoomed_sizes[1] == size
        assert second.geometry() == second_geometry

        closed = []
        first.closed.connect(lambda: closed.append(True))
        first.activateWindow()
        QTest.keyClick(first, Qt.Key.Key_Escape)
        assert closed == [True]
        assert not first.isVisible()
        assert second.isVisible()
    finally:
        if first.isVisible():
            first.close()
        second.close()

    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert app.primaryScreen() is screen


def test_pin_returns_from_missing_negative_origin_screen(app) -> None:
    image = QImage(300, 150, QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.blue)
    pin = PinnedImage(image)
    remaining = QRect(0, 0, 120, 110)
    removed = QRect(-450, -120, 450, 400)
    try:
        pin.setGeometry(-390, -60, 300, 150)
        pin.restore_visibility([remaining, removed])
        assert pin.pos() == QPoint(-390, -60)

        pin.restore_visibility([remaining])
        assert remaining.contains(pin.geometry())
        assert pin.width() == 120
        assert pin.height() == 60
    finally:
        pin.close()


@pytest.mark.parametrize("handle", tuple(ResizeHandle))
def test_pin_handle_resizes_with_opposite_anchor(app, handle: ResizeHandle) -> None:
    screen = app.primaryScreen()
    origin = screen.availableGeometry().topLeft() + QPoint(140, 140)
    image = QImage(180, 90, QImage.Format.Format_RGBA8888)
    image.fill(QColor("#3b7ba4"))
    pin = PinnedImage(image)
    horizontal, vertical = handle.value
    try:
        pin.show_at(screen, origin)
        before = pin.geometry()
        margin = 4
        local = QPointF(
            (before.width() / 2) + horizontal * (before.width() / 2 - margin),
            (before.height() / 2) + vertical * (before.height() / 2 - margin),
        )
        start = pin.mapToGlobal(local)
        stop = start + QPointF(horizontal * 36, vertical * 20)

        hover = QMouseEvent(QEvent.Type.MouseMove, local, start, _NO_BUTTON, _NO_BUTTON, _NO_MODIFIER)
        app.sendEvent(pin, hover)
        assert pin.cursor().shape() == resize_cursor(handle)

        press = QMouseEvent(QEvent.Type.MouseButtonPress, local, start, _LEFT, _LEFT, _NO_MODIFIER)
        app.sendEvent(pin, press)
        for kind, button, buttons in (
            (QEvent.Type.MouseMove, _NO_BUTTON, _LEFT),
            (QEvent.Type.MouseButtonRelease, _LEFT, _NO_BUTTON),
        ):
            event = QMouseEvent(kind, pin.mapFromGlobal(stop), stop, button, buttons, _NO_MODIFIER)
            app.sendEvent(pin, event)

        after = pin.geometry()
        assert after.width() > before.width()
        assert after.height() > before.height()
        assert abs(after.width() - 2 * after.height()) <= 1
        anchor_x = (1 - horizontal) / 2
        anchor_y = (1 - vertical) / 2
        anchor_before = QPointF(
            before.x() + anchor_x * before.width(), before.y() + anchor_y * before.height()
        )
        anchor_after = QPointF(
            after.x() + anchor_x * after.width(), after.y() + anchor_y * after.height()
        )
        assert abs(anchor_after.x() - anchor_before.x()) <= 0.5
        assert abs(anchor_after.y() - anchor_before.y()) <= 0.5
    finally:
        pin.close()


def test_pin_handle_stops_at_screen_edge_without_moving_anchor(app) -> None:
    screen = app.primaryScreen()
    area = screen.availableGeometry()
    image = QImage(180, 90, QImage.Format.Format_RGBA8888)
    image.fill(QColor("#3b7ba4"))
    pin = PinnedImage(image)
    try:
        pin.show_at(screen, QPoint(area.right() - 206, area.top() + 140))
        before = pin.geometry()
        local = QPointF(before.width() - 4, before.height() / 2)
        start = pin.mapToGlobal(local)
        stop = QPointF(area.right() + 400, start.y())
        press = QMouseEvent(QEvent.Type.MouseButtonPress, local, start, _LEFT, _LEFT, _NO_MODIFIER)
        app.sendEvent(pin, press)
        move = QMouseEvent(
            QEvent.Type.MouseMove, pin.mapFromGlobal(stop), stop, _NO_BUTTON, _LEFT, _NO_MODIFIER
        )
        app.sendEvent(pin, move)
        release = QMouseEvent(
            QEvent.Type.MouseButtonRelease, pin.mapFromGlobal(stop), stop, _LEFT, _NO_BUTTON,
            _NO_MODIFIER,
        )
        app.sendEvent(pin, release)
        assert area.contains(pin.geometry())
        assert pin.geometry().left() == before.left()
        assert pin.geometry().right() == area.right()
        assert abs(pin.geometry().center().y() - before.center().y()) <= 1
    finally:
        pin.close()


def test_pin_renders_capture_frame_and_all_grips_without_hover(app) -> None:
    image = QImage(124, 84, QImage.Format.Format_RGBA8888)
    image.fill(QColor("#3b7ba4"))
    pin = PinnedImage(image)
    try:
        pin.resize(image.size())
        preview = QImage(pin.size(), QImage.Format.Format_RGBA8888)
        pin.render(preview)
        cyan = QColor("#58dcfa")
        assert preview.pixelColor(26, 1) == cyan
        for x, y in ((4, 4), (62, 4), (120, 4), (120, 42),
                     (120, 80), (62, 80), (4, 80), (4, 42)):
            assert preview.pixelColor(x, y) == cyan
        assert preview.pixelColor(13, 4) == preview.pixelColor(4, 13) == cyan
        assert preview.pixelColor(10, 10) == image.pixelColor(10, 10)
        assert preview.pixelColor(62, 42) == image.pixelColor(62, 42)
    finally:
        pin.close()


def test_pin_actions_appear_on_click_and_close_only_that_pin(app):
    image = QImage(180, 100, QImage.Format.Format_RGBA8888)
    image.fill(QColor("blue"))
    pin = PinnedImage(image)
    other = PinnedImage(image)
    try:
        screen = app.primaryScreen()
        pin.show_at(screen, screen.availableGeometry().topLeft() + QPoint(100, 100))
        other.show_at(screen, screen.availableGeometry().topLeft() + QPoint(350, 100))
        assert pin._edit_button.isHidden() and pin._close_button.isHidden()
        requested = []
        pin.edit_requested.connect(lambda: requested.append(True))
        QTest.mouseClick(pin, _LEFT, pos=QPoint(90, 55))
        assert pin._edit_button.isVisible() and pin._close_button.isVisible()
        assert pin._close_button.x() == pin.width() - 42
        assert pin._edit_button.x() == pin.width() - 78
        pin.resize(220, 100)
        assert pin._close_button.x() == pin.width() - 42
        assert pin._edit_button.x() == pin.width() - 78
        QTest.mouseClick(pin._edit_button, _LEFT)
        assert requested == [True]
        QTest.mouseClick(pin._close_button, _LEFT)
        assert not pin.isVisible() and other.isVisible()
    finally:
        if pin.isVisible():
            pin.close()
        other.close()