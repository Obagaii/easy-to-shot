import pytest
from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QInputMethodEvent, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolButton, QWidget

from e2s.annotation.document import AnnotationDocument
from e2s.annotation.elements import Stroke, StrokeStyle, Text, Tool
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
    QTest.mouseClick(toolbar._buttons[Tool.ARROW], Qt.MouseButton.LeftButton)
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
        widget, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier
    )
    assert document.elements != (created,)
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=QPoint(85, 100))
    QTest.keyClick(widget, Qt.Key.Key_Delete)
    assert not document.elements


def test_select_element_resize_from_corner_and_delete(canvas) -> None:
    widget, document, scale = canvas
    toolbar = widget._toolbar
    QTest.mouseClick(toolbar._buttons[Tool.RECTANGLE], Qt.MouseButton.LeftButton)
    widget._styles._controls["color"]._presets["#1677ff"].click()
    QTest.keyClick(widget, Qt.Key.Key_BracketRight)
    drag(widget, QPoint(80, 95), QPoint(195, 150))
    original = document.elements[0]
    assert original.color == "#1677ff"
    assert original.width_px == 5

    QTest.mouseClick(toolbar._buttons[Tool.SELECT], Qt.MouseButton.LeftButton)
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=QPoint(135, 95))
    drag(widget, QPoint(195, 150), QPoint(235, 185))
    resized = document.elements[0]
    assert document.revision == 2
    assert resized.points[0] == original.points[0]
    assert resized.points[1] == pytest.approx((205 * scale, 135 * scale))

    QTest.keyClick(widget, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert document.elements == (original,)
    QTest.keyClick(
        widget, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier
    )
    assert document.elements == (resized,)
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=QPoint(135, 95))
    drag(widget, QPoint(155, 125), QPoint(177, 134))
    moved = document.elements[0]
    assert moved.points[0] == pytest.approx((72 * scale, 54 * scale))
    QTest.keyClick(widget, Qt.Key.Key_Delete)
    assert not document.elements
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
    widget._styles._controls["font_size_px"]._buttons[42].click()
    widget._styles._controls["color"].set_color("#1677ff")
    QTest.keyClick(widget._editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert document.revision == 2
    assert document.elements[0].value == "再次编辑"
    assert document.elements[0].font_size_px == 42
    assert document.elements[0].color == "#1677ff"
    QTest.keyClick(widget, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert document.elements == (original,)


def test_toolbar_exposes_only_requested_tools_and_shortcuts(canvas) -> None:
    widget, _, _ = canvas
    toolbar = widget._toolbar
    assert tuple(toolbar._buttons) == (
        Tool.MOVE, Tool.SELECT, Tool.RECTANGLE, Tool.ELLIPSE, Tool.ARROW, Tool.PEN,
        Tool.TEXT, Tool.WATERMARK, Tool.RECT_HIGHLIGHT, Tool.ERASER,
    )
    assert tuple(toolbar._action_buttons) == (
        "undo", "redo", "ocr", "barcode", "record", "pin", "scroll", "save", "cancel", "copy"
    )
    for button in (*toolbar._buttons.values(), *toolbar._action_buttons.values()):
        assert button.accessibleName() in button.property("alt")
        assert button.toolTip() == button.accessibleDescription()
        assert not button.icon().pixmap(20, 20).isNull()

    for name, tool in (("V", Tool.SELECT), ("Shift+1", Tool.ELLIPSE), ("2", Tool.ARROW),
                       ("4", Tool.RECT_HIGHLIGHT), ("8", Tool.ERASER), ("9", Tool.WATERMARK)):
        key = QKeySequence(name)[0]
        QTest.keyClick(widget, key.key(), key.keyboardModifiers())
        assert widget._tool is tool

    requested = []
    widget.pin_requested.connect(lambda: requested.append("pin"))
    widget.output_requested.connect(requested.append)
    control = Qt.KeyboardModifier.ControlModifier
    QTest.keyClick(widget, Qt.Key.Key_F, control)
    QTest.keyClick(widget, Qt.Key.Key_Q, control)
    QTest.keyClick(widget, Qt.Key.Key_O, control)
    QTest.keyClick(widget, Qt.Key.Key_R, control)
    QTest.keyClick(widget, Qt.Key.Key_L)
    assert requested == ["pin", "barcode", "ocr", "record", "scroll"]


def test_settings_follow_tool_and_element_eraser_undo_restores_selection(canvas) -> None:
    widget, document, _ = canvas
    toolbar = widget._toolbar
    toolbar._buttons[Tool.RECTANGLE].click()
    assert widget._styles._roles[:2] == ("color", "fill_color")
    drag(widget, QPoint(70, 80), QPoint(110, 105))
    toolbar._buttons[Tool.ELLIPSE].click()
    assert Tool.ELLIPSE is widget._tool
    assert "corner_radius_px" not in widget._styles._roles
    drag(widget, QPoint(150, 120), QPoint(200, 150))
    original = document.elements
    assert [element.tool for element in original] == [Tool.RECTANGLE, Tool.ELLIPSE]

    toolbar._buttons[Tool.ERASER].click()
    assert widget._styles._roles == ("eraser_mode",)
    drag(widget, QPoint(60, 65), QPoint(220, 155))
    assert not document.elements
    QTest.keyClick(widget, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert document.elements == original
    QTest.keyClick(widget, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert not document.elements
    widget._styles._controls["eraser_mode"]._buttons["brush_eraser"].click()
    assert widget._styles._roles == ("eraser_mode", "brush_width")


def test_toolbar_keeps_every_button_inside_the_window_after_resize(canvas) -> None:
    widget, _, _ = canvas
    toolbar = widget._toolbar
    toolbar._buttons[Tool.RECTANGLE].click()
    for width in (630, 340, 760):
        widget.resize(width, widget.height())
        QApplication.processEvents()
        assert toolbar.width() <= width - 8
        assert widget.rect().contains(widget._styles.geometry())
        assert not toolbar.geometry().intersects(widget._styles.geometry())
        for button in toolbar._main_buttons:
            assert toolbar.rect().contains(button.geometry())


def test_watermark_updates_preview_and_commits_once_when_typing_finishes(canvas) -> None:
    widget, document, _ = canvas
    toolbar = widget._toolbar
    toolbar._buttons[Tool.WATERMARK].click()
    assert widget._styles._sections["family"].isHidden()
    assert widget._styles._sections["watermark_font_size"].isVisible()
    field = widget._styles._controls["watermark_text"]
    field.setFocus()
    QTest.keyClicks(field, "Private Team")
    assert field.text() == "Private Team"
    assert not document.elements
    assert widget._preview_image() != document.source
    QTest.keyClick(field, Qt.Key.Key_Return)
    assert len(document.elements) == 1
    assert document.elements[0].watermark.value == "Private Team"
    assert document.revision == 1

    widget.setFocus()
    QTest.keyClick(widget, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert widget._preview_image() == document.source


def test_sidebar_is_independent_and_follows_tool_and_crop_drag(canvas) -> None:
    widget, _, _ = canvas
    widget.parentWidget().resize(1400, 940)
    widget.resize(widget.parentWidget().size())
    toolbar, sidebar = widget._toolbar, widget._styles
    assert toolbar.isVisible()
    assert sidebar.isHidden()
    toolbar._buttons[Tool.RECTANGLE].click()
    QApplication.processEvents()

    assert sidebar.parentWidget() is widget
    assert sidebar.geometry().left() > toolbar.geometry().right()
    assert sidebar._scroll.verticalScrollBar().maximum() == 0
    assert tuple(sidebar._roles) == (
        "color", "fill_color", "width_px", "line_style", "line_effect",
        "corner_radius_px", "opacity", "layers",
    )

    widget.preview_selection(QRectF(80, 70, 360, 210))
    assert toolbar.isHidden()
    assert sidebar.isHidden()
    widget.preview_selection(None)
    assert toolbar.isVisible()
    assert sidebar.isVisible()

    toolbar._buttons[Tool.ARROW].click()
    assert {"arrow_type", "arrow_outline", "start_head", "shaft", "end_head"} <= set(sidebar._roles)
    toolbar._buttons[Tool.ELLIPSE].click()
    assert sidebar._sections["corner_radius_px"].isHidden()
    toolbar._buttons[Tool.MOVE].click()
    assert sidebar.isHidden()


def test_sidebar_opacity_and_layer_changes_update_rendering_and_undo(canvas) -> None:
    widget, document, scale = canvas
    first = Stroke(Tool.RECTANGLE, ((30, 30), (150, 130)), "#ff0000", 4,
                   style=StrokeStyle(fill_color="#ff0000"))
    second = Stroke(Tool.RECTANGLE, ((85, 65), (190, 155)), "#0000ff", 4,
                    style=StrokeStyle(fill_color="#0000ff"))
    document.add_many((first, second))
    widget._toolbar._buttons[Tool.SELECT].click()
    point = QPoint(30 + round(50 / scale), 50 + round(60 / scale))
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=point)
    layer_buttons = widget._styles._controls["layers"].findChildren(QToolButton)
    next(button for button in layer_buttons if button.accessibleName() == "置于顶层").click()
    assert document.elements == (second, first)
    assert widget._preview_image().pixelColor(100, 100) == QColor("#ff0000")

    opacity = widget._styles._controls["opacity"]
    opacity.setValue(50)
    assert document.elements[1].opacity == 50
    pixel = widget._preview_image().pixelColor(100, 100)
    assert pixel.red() == pytest.approx(128, abs=1)
    assert pixel.blue() == pytest.approx(127, abs=1)
    QTest.keyClick(widget, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert document.elements == (second, first)
    QTest.keyClick(widget, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert document.elements == (first, second)


def test_sidebar_alignment_and_opacity_are_single_multi_element_edits(canvas) -> None:
    widget, document, _ = canvas
    first = Stroke(Tool.RECTANGLE, ((25, 25), (65, 60)), "#ff0000", 4)
    second = Stroke(Tool.ELLIPSE, ((90, 70), (150, 130)), "#0000ff", 4)
    document.add_many((first, second))
    widget._toolbar._buttons[Tool.SELECT].click()
    drag(widget, QPoint(34, 53), QPoint(200, 194))
    assert widget._multi_selection == {0, 1}

    horizontal = widget._styles._controls["horizontal"].findChildren(QToolButton)
    next(button for button in horizontal if button.accessibleName() == "左对齐").click()
    assert document.elements[0] == first
    assert document.elements[1].points[0][0] == pytest.approx(first.points[0][0])
    assert document.revision == 2

    widget._styles._controls["opacity"].setValue(40)
    assert [element.opacity for element in document.elements] == [40, 40]
    assert document.revision == 3
    QTest.keyClick(widget, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert [element.opacity for element in document.elements] == [100, 100]
    QTest.keyClick(widget, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert document.elements == (first, second)
