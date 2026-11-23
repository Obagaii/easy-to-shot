import pytest
from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from e2s.annotation.document import AnnotationDocument
from e2s.annotation.elements import Text, Tool
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


def test_drag_add_move_delete_and_undo_with_source_pixel_coordinates(canvas) -> None:
    widget, document, scale = canvas
    toolbar = widget._toolbar
    QTest.mouseClick(toolbar._buttons[Tool.LINE], Qt.MouseButton.LeftButton)
    drag(widget, QPoint(55, 80), QPoint(295, 80))
    created = document.elements[0]
    assert created.points[0] == pytest.approx((25 * scale, 30 * scale))
    assert created.points[1] == pytest.approx((265 * scale, 30 * scale))
    assert created.width_px == 4

    QTest.mouseClick(toolbar._buttons[Tool.SELECT], Qt.MouseButton.LeftButton)
    drag(widget, QPoint(75, 83), QPoint(85, 103))
    assert document.revision == 2
    assert document.elements[0].points[0] == pytest.approx((35 * scale, 50 * scale))
    QTest.keyClick(widget, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert document.elements == (created,)
    QTest.keyClick(
        widget, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    )
    assert document.elements != (created,)
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=QPoint(85, 100))
    QTest.keyClick(widget, Qt.Key.Key_Delete)
    assert not document.elements


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


def test_arrow_resize_changes_only_the_dragged_endpoint(canvas) -> None:
    widget, document, scale = canvas
    QTest.mouseClick(widget._toolbar._buttons[Tool.ARROW], Qt.MouseButton.LeftButton)
    drag(widget, QPoint(80, 95), QPoint(180, 95))
    original = document.elements[0]
    QTest.mouseClick(widget._toolbar._buttons[Tool.SELECT], Qt.MouseButton.LeftButton)
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=QPoint(130, 95))
    drag(widget, QPoint(180, 95), QPoint(230, 160))

    resized = document.elements[0]
    assert resized.points[0] == original.points[0]
    assert resized.points[1] == pytest.approx((200 * scale, 110 * scale))
    assert resized.width_px == original.width_px


def test_ime_multiline_text_can_be_reedited_cancelled_and_undone(canvas) -> None:
    widget, document, scale = canvas
    QTest.mouseClick(widget._toolbar._buttons[Tool.TEXT], Qt.MouseButton.LeftButton)
    position = QPoint(85, 85)
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=position)
    editor = widget._editor
    QApplication.sendEvent(editor, QInputMethodEvent("ni", []))
    assert editor.has_preedit
    QTest.keyClick(editor, Qt.Key.Key_Escape)
    assert widget._editor is editor
    QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert widget._editor is editor
    assert not document.elements

    commit = QInputMethodEvent()
    commit.setCommitString("你好")
    QApplication.sendEvent(editor, commit)
    QTest.keyClick(editor, Qt.Key.Key_Return)
    commit.setCommitString("世界")
    QApplication.sendEvent(editor, commit)
    QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert widget._editor is None
    original = document.elements[0]
    assert isinstance(original, Text)
    assert original.origin == pytest.approx((55 * scale, 35 * scale))
    assert original.value == "你好\n世界"
    assert document.revision == 1

    QTest.mouseDClick(widget, Qt.MouseButton.LeftButton, pos=position + QPoint(6, 8))
    widget._editor.setPlainText("取消这次修改")
    QTest.keyClick(widget._editor, Qt.Key.Key_Escape)
    assert widget._editor is None
    assert document.elements == (original,)
    assert document.revision == 1

    QTest.mouseDClick(widget, Qt.MouseButton.LeftButton, pos=position + QPoint(6, 8))
    widget._editor.setPlainText("再次编辑")
    widget._toolbar._font_size.set_value(38)
    widget._toolbar._color.set_color("#1e88e5")
    QTest.keyClick(widget._editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert document.revision == 2
    assert document.elements[0].value == "再次编辑"
    assert document.elements[0].font_size_px == 38
    assert document.elements[0].color == "#1e88e5"
    QTest.keyClick(widget, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert document.elements == (original,)
