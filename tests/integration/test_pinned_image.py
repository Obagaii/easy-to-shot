from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest

from e2s.ui.native.pinned_image import PinnedImage

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

        local = QPointF(8, 8)
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
