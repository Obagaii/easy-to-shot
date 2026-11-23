import pytest
from PySide6.QtGui import QColor, QImage

from e2s.annotation.document import AnnotationDocument
from e2s.annotation.elements import Stroke, Text, Tool
from e2s.annotation.renderer import hit_test, render_annotations
from e2s.annotation.resize import ElementResize, resize_bounds
from e2s.capture.geometry import ResizeHandle


def image_with_color(width: int, height: int, color: str) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGBA8888)
    image.fill(QColor(color))
    return image


def test_history_can_reproduce_layer_order_and_discards_redo_after_new_edit() -> None:
    source = image_with_color(70, 60, "#ffffff")
    document = AnnotationDocument(source)
    rectangle = Stroke(Tool.RECTANGLE, ((5, 5), (35, 35)), "#ff0000", 2, True)
    ellipse = Stroke(Tool.ELLIPSE, ((10, 10), (30, 30)), "#0000ff", 3, True)
    document.add(rectangle)
    index = document.add(ellipse)
    assert hit_test(document.elements, (20, 20), 0) == index
    original = render_annotations(document.source, document.elements)

    document.replace(index, ellipse.translated(30, 5))
    moved = render_annotations(document.source, document.elements)
    assert moved.pixelColor(20, 20) == QColor("#ff0000")
    document.delete(0)
    document.undo()
    assert render_annotations(document.source, document.elements) == moved
    document.undo()
    assert render_annotations(document.source, document.elements) == original
    document.redo()
    assert render_annotations(document.source, document.elements) == moved
    document.undo()
    document.replace(index, ellipse)
    assert document.can_redo
    document.delete(index)
    assert not document.can_redo
    assert source.pixelColor(20, 20) == QColor("#ffffff")


@pytest.mark.parametrize("tool", [Tool.RECTANGLE, Tool.ELLIPSE])
def test_outlines_hit_the_stroke_and_filled_shapes_hit_the_center(tool: Tool) -> None:
    outline = Stroke(tool, ((30, 30), (10, 10)), "#ff0000", 4)
    filled = Stroke(tool, outline.points, outline.color, outline.width_px, True)
    assert hit_test((outline,), (20, 10), 0) == 0
    assert hit_test((outline,), (20, 20), 0) is None
    assert hit_test((filled,), (20, 20), 0) == 0


def test_lines_arrow_wings_and_freehand_use_source_pixel_width() -> None:
    source = image_with_color(90, 90, "#ffffff")
    line = Stroke(Tool.LINE, ((10, 20), (50, 20)), "#ff0000", 4)
    arrow = Stroke(Tool.ARROW, ((10, 40), (50, 40)), "#ff0000", 4)
    pen = Stroke(Tool.PEN, ((10, 50), (20, 60), (50, 60)), "#ff0000", 4)
    dot = Stroke(Tool.PEN, ((60, 70),), "#0000ff", 4)
    merged = render_annotations(source, (line, arrow, pen, dot))

    red = QColor("#ff0000")
    white = QColor("#ffffff")
    assert merged.pixelColor(25, 18) == red
    assert merged.pixelColor(25, 21) == red
    assert merged.pixelColor(25, 22) == white
    assert merged.pixelColor(39, 45) == red
    assert merged.pixelColor(25, 59) == red
    assert merged.pixelColor(40, 70) == white
    assert merged.pixelColor(60, 70) == QColor("#0000ff")
    assert hit_test((arrow,), (39, 45), 0) == 0
    assert hit_test((pen,), (15, 55), 0) == 0
    assert hit_test((dot,), (60, 70), 0) == 0


@pytest.mark.parametrize(
    ("element", "expected"),
    [
        (
            Stroke(Tool.ELLIPSE, ((10, 20), (30, 30)), "#ff0000", 3),
            Stroke(Tool.ELLIPSE, ((10, 20), (50, 40)), "#ff0000", 3),
        ),
        (
            Stroke(Tool.PEN, ((10, 20), (15, 30), (30, 25)), "#ff0000", 3),
            Stroke(Tool.PEN, ((10, 20), (20, 40), (50, 30)), "#ff0000", 3),
        ),
    ],
)
def test_box_resize_keeps_the_opposite_corner_and_source_pixel_style(element, expected) -> None:
    gesture = ElementResize(element, ResizeHandle.BOTTOM_RIGHT, resize_bounds(element))
    assert gesture.update(20, 10) == expected


def test_proportional_resize_enlarges_multiline_text_from_its_anchor(app) -> None:
    element = Text((10, 20), "你好\n世界", "#123456", 24)
    bounds = resize_bounds(element)
    gesture = ElementResize(element, ResizeHandle.BOTTOM_RIGHT, bounds)
    resized = gesture.update(bounds.width() / 2, bounds.height() / 2)
    assert resized.font_size_px == 36
    assert resized.value == element.value
    assert resized.color == element.color
    assert resized.origin[1] == pytest.approx(element.origin[1])


def test_multiline_text_renders_in_each_line_and_restores_when_undone(app) -> None:
    source = image_with_color(120, 100, "#ffffff")
    document = AnnotationDocument(source)
    text = Text((5, 5), "你好\n世界", "#123456", 20)
    index = document.add(text)
    rendered = render_annotations(source, document.elements)
    assert rendered.copy(0, 5, 90, 22) != source.copy(0, 5, 90, 22)
    assert rendered.copy(0, 28, 90, 23) != source.copy(0, 28, 90, 23)
    document.replace(index, Text(text.origin, "新文字", text.color, 20))
    assert render_annotations(source, document.elements) != rendered
    document.undo()
    assert render_annotations(source, document.elements) == rendered
