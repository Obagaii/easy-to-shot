import pytest
from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from e2s.annotation.document import AnnotationDocument
from e2s.annotation.elements import Tool
from e2s.ui.native.canvas import AnnotationCanvas


@pytest.fixture(params=[1.0, 1.5])
def canvas(app, request):
    image = QImage(int(390 * request.param), int(240 * request.param), QImage.Format.Format_RGBA8888)
    image.fill(QColor("#ffffff"))
    document = AnnotationDocument(image)
    window = QWidget()
    window.resize(650, 470)
    canvas = AnnotationCanvas(document, QRectF(30, 50, 390, 240), window)
    canvas.setGeometry(window.rect())
    window.show()
    canvas.setFocus()
    app.processEvents()
    yield canvas, document, request.param
    window.close()


def drag(widget, start, end) -> None:
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(widget, (start + end) / 2)
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=end)


def test_select_element_resize_from_corner_and_delete_from_toolbar(canvas) -> None:
    widget, document, scale = canvas
    toolbar = widget._toolbar
    QTest.mouseClick(toolbar._buttons[Tool.RECTANGLE], Qt.MouseButton.LeftButton)
    toolbar._color.menu().actions()[4].trigger()
    QTest.mouseClick(toolbar._width._increase, Qt.MouseButton.LeftButton)
    assert toolbar.color == "#1e88e5"
    assert toolbar.width_px == 5
    drag(widget, QPoint(80, 95), QPoint(195, 150))
    original = document.elements[0]
    assert original.color == "#1e88e5"
    assert original.width_px == 5

    QTest.mouseClick(toolbar._buttons[Tool.SELECT], Qt.MouseButton.LeftButton)
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=QPoint(135, 95))
    assert toolbar._delete.isEnabled()
    drag(widget, QPoint(195, 150), QPoint(235, 185))
    resized = document.elements[0]
    assert document.revision == 2
    assert resized.points[0] == original.points[0]
    assert resized.points[1] == pytest.approx((205 * scale, 135 * scale))

    QTest.keyClick(widget, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert document.elements == (original,)
    QTest.keyClick(
        widget, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    )
    assert document.elements == (resized,)
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=QPoint(135, 95))
    drag(widget, QPoint(155, 125), QPoint(177, 134))
    moved = document.elements[0]
    assert moved.points[0] == pytest.approx((72 * scale, 54 * scale))
    QTest.mouseClick(toolbar._delete, Qt.MouseButton.LeftButton)
    assert not document.elements
    assert not toolbar._delete.isEnabled()
    QTest.keyClick(widget, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert document.elements == (moved,)
