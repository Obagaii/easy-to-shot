from PySide6.QtGui import QColor, QImage

from e2s.annotation.document import AnnotationDocument
from e2s.annotation.elements import Stroke, Tool
from e2s.annotation.renderer import hit_test, render_annotations


def image_with_color(width: int, height: int, color: str) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGBA8888)
    image.fill(QColor(color))
    return image


def test_history_can_reproduce_layer_order_and_discards_redo_after_new_edit() -> None:
    source = image_with_color(70, 60, "#ffffff")
    document = AnnotationDocument(source)
    rectangle = Stroke(Tool.RECTANGLE, ((5, 5), (35, 35)), "#ff0000", 2, True)
    top_rectangle = Stroke(Tool.RECTANGLE, ((10, 10), (30, 30)), "#0000ff", 3, True)
    document.add(rectangle)
    index = document.add(top_rectangle)
    assert hit_test(document.elements, (20, 20), 0) == index
    original = render_annotations(document.source, document.elements)

    document.replace(index, top_rectangle.translated(30, 5))
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
    document.replace(index, top_rectangle)
    assert document.can_redo
    document.delete(index)
    assert not document.can_redo
    assert source.pixelColor(20, 20) == QColor("#ffffff")
