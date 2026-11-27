from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter

from e2s.capture.ocr import OcrLine
from e2s.ui.native.ocr_layout import prepare_text_rows


def test_rows_preserve_individual_geometry_colors_and_scaled_font_sizes(app) -> None:
    image = QImage(300, 120, QImage.Format.Format_RGB32)
    image.fill(QColor('white'))
    with QPainter(image) as painter:
        painter.fillRect(QRect(0, 60, 300, 60), QColor('#202020'))
        painter.fillRect(QRect(15, 18, 45, 8), QColor('#bb2222'))
        painter.fillRect(QRect(25, 78, 45, 8), QColor('#eeeeee'))
    lines = (
        OcrLine('hello', ((10, 12), (100, 12), (100, 30), (10, 30))),
        OcrLine('world', ((20, 70), (120, 70), (120, 92), (20, 92))),
    )
    rows = prepare_text_rows(image, lines, 0.5, 0.5)
    assert rows[0].bounds.left() == 5
    assert rows[1].bounds.top() == 35
    assert rows[0].foreground.red() > rows[0].foreground.green() * 2
    assert rows[1].foreground.lightness() > 200
    assert rows[0].font_px < rows[1].font_px <= 10


def test_oversized_ocr_box_does_not_inflate_font(app) -> None:
    image = QImage(300, 200, QImage.Format.Format_RGB32)
    image.fill(QColor('white'))
    lines = tuple(OcrLine('text', ((5, y), (100, y), (100, y + h), (5, y + h)))
                  for y, h in ((5, 15), (30, 16), (60, 100)))
    rows = prepare_text_rows(image, lines, 1, 1)
    assert rows[2].font_px <= rows[1].font_px * 2 + 1


def test_text_layer_places_horizontal_and_vertical_glyphs_at_ocr_positions(app) -> None:
    from e2s.ui.native.ocr_text_layer import OcrTextLayer

    image = QImage(300, 220, QImage.Format.Format_RGB32)
    image.fill(QColor('white'))
    lines = (
        OcrLine('horizontal', ((30, 25), (170, 25), (170, 48), (30, 48))),
        OcrLine('縦書き文字', ((220, 60), (242, 60), (242, 190), (220, 190))),
    )
    rows = prepare_text_rows(image, lines, 1, 1)
    editor = OcrTextLayer(rows, None)
    editor.resize(300, 220)
    editor.setReadOnly(True)
    editor.setPlainText('horizontal\n縦書き文字')
    glyphs = editor._glyphs
    assert glyphs[0].rect.left() == 30
    vertical = glyphs[len('horizontal'):]
    assert rows[1].vertical and rows[1].font_px >= 15
    assert all(glyph.rect.left() == 220 for glyph in vertical)
    assert vertical[-1].rect.top() > vertical[0].rect.top() + 50
    editor.selectAll()
    assert editor.textCursor().selectedText().replace('\u2029', '\n') == editor.toPlainText()
    editor.show()
    app.processEvents()
    rendered = QImage(300, 220, QImage.Format.Format_ARGB32)
    rendered.fill(QColor("white"))
    editor.viewport().render(rendered)
    assert any(rendered.pixelColor(x, y).lightness() < 200
               for x in range(220, 243) for y in range(60, 190))
    editor.close()


def test_streamed_translation_flows_through_original_line_positions(app) -> None:
    from e2s.ui.native.ocr_text_layer import OcrTextLayer

    image = QImage(240, 120, QImage.Format.Format_RGB32)
    image.fill(QColor('white'))
    lines = tuple(OcrLine('original text', ((25, y), (170, y), (170, y + 20), (25, y + 20)))
                  for y in (10, 60))
    editor = OcrTextLayer(prepare_text_rows(image, lines, 1, 1), None)
    editor.resize(240, 120)
    editor.setReadOnly(True)
    editor.setPlainText('A translation that is long enough to cover both original rows')
    assert any(glyph.rect.top() == 60 for glyph in editor._glyphs)
    assert editor._glyphs[0].rect.left() == 25