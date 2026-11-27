from dataclasses import dataclass
import unicodedata

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QMouseEvent, QPainter, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from e2s.ui.native.ocr_layout import TextRow


@dataclass(frozen=True, slots=True)
class _Glyph:
    text: str
    rect: QRectF
    font: QFont
    color: QColor
    start: int
    end: int


def _units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _clusters(text: str) -> list[str]:
    clusters: list[str] = []
    for char in text:
        if unicodedata.combining(char) and clusters:
            clusters[-1] += char
        else:
            clusters.append(char)
    return clusters


class OcrTextLayer(QPlainTextEdit):
    def __init__(self, rows: list[TextRow], parent) -> None:
        super().__init__(parent)
        self._rows = rows
        self._glyphs: list[_Glyph] = []
        self._anchor: int | None = None
        self.textChanged.connect(self._rebuild)
        self.selectionChanged.connect(self.viewport().update)

    def setReadOnly(self, read_only: bool) -> None:
        super().setReadOnly(read_only)
        self.viewport().update()

    def _rebuild(self) -> None:
        text = self.toPlainText()
        parts = text.split("\n")
        self._glyphs = []
        if not self._rows or not text:
            self.viewport().update()
            return
        if len(parts) == len(self._rows):
            offset = 0
            for row, part in zip(self._rows, parts, strict=True):
                self._layout_row(row, part, offset)
                offset += _units(part) + 1
        else:
            self._layout_flow(text)
        self.viewport().update()

    def _layout_flow(self, text: str) -> None:
        clusters = _clusters(text)
        index = 0
        offset = 0
        for row in self._rows:
            if index >= len(clusters):
                break
            font = QFont("Microsoft YaHei UI")
            font.setPixelSize(row.font_px)
            metrics = QFontMetricsF(font)
            capacity = row.bounds.height() if row.vertical else row.bounds.width()
            end, used = index, 0.0
            while end < len(clusters):
                char = clusters[end]
                if char == "\n":
                    break
                advance = metrics.height() if row.vertical else metrics.horizontalAdvance(char)
                if used + advance > capacity and end > index:
                    break
                used += advance
                end += 1
            part = "".join(clusters[index:end])
            self._layout_row(row, part, offset)
            offset += _units(part)
            index = end
            if index < len(clusters) and clusters[index] == "\n":
                index += 1
                offset += 1
        if index < len(clusters):
            row = self._rows[-1]
            part = "".join(clusters[index:])
            self._layout_row(row, part, offset, overflow=True)

    def _layout_row(self, row: TextRow, text: str, offset: int,
                    overflow: bool = False) -> None:
        clusters = _clusters(text)
        if not clusters:
            return
        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(row.font_px)
        metrics = QFontMetricsF(font)
        if row.vertical:
            cell_height = row.bounds.height() / len(clusters)
            if not overflow:
                font.setPixelSize(max(1, min(row.font_px, round(cell_height * 0.92))))
            cell_height = min(cell_height, QFontMetricsF(font).height() * 1.4)
            for index, char in enumerate(clusters):
                rect = QRectF(row.bounds.left(), row.bounds.top() + index * cell_height,
                              row.bounds.width(), cell_height)
                end = offset + _units(char)
                self._glyphs.append(_Glyph(char, rect, font, row.foreground, offset, end))
                offset = end
        else:
            total = sum(metrics.horizontalAdvance(char) for char in clusters)
            if total > row.bounds.width() and not overflow:
                font.setPixelSize(max(1, round(row.font_px * row.bounds.width() / total)))
                metrics = QFontMetricsF(font)
            x = row.bounds.left()
            y = row.bounds.top() + (row.bounds.height() if overflow else 0)
            for char in clusters:
                advance = metrics.horizontalAdvance(char)
                if overflow and x + advance > self.viewport().width():
                    x = row.bounds.left()
                    y += metrics.height()
                rect = QRectF(x, y, advance, max(row.bounds.height(), metrics.height()))
                end = offset + _units(char)
                self._glyphs.append(_Glyph(char, rect, font, row.foreground, offset, end))
                offset = end
                x += advance

    def paintEvent(self, event) -> None:
        if not self.isReadOnly():
            super().paintEvent(event)
            return
        cursor = self.textCursor()
        begin, end = cursor.selectionStart(), cursor.selectionEnd()
        with QPainter(self.viewport()) as painter:
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            for glyph in self._glyphs:
                selected = glyph.start < end and glyph.end > begin
                if selected:
                    painter.fillRect(glyph.rect, QColor("#1677ff"))
                painter.setFont(glyph.font)
                painter.setPen(QColor("white") if selected else glyph.color)
                painter.drawText(glyph.rect, Qt.AlignmentFlag.AlignCenter, glyph.text)

    def _position_at(self, point: QPointF) -> int:
        if not self._glyphs:
            return 0
        def distance(glyph: _Glyph) -> float:
            rect = glyph.rect
            dx = max(rect.left() - point.x(), 0, point.x() - rect.right())
            dy = max(rect.top() - point.y(), 0, point.y() - rect.bottom())
            return dx * dx + dy * dy
        glyph = min(self._glyphs, key=distance)
        row = next((row for row in self._rows if row.foreground == glyph.color
                    and row.bounds.contains(glyph.rect.center())), None)
        after = point.y() > glyph.rect.center().y() if row and row.vertical else (
            point.x() > glyph.rect.center().x())
        return glyph.end if after else glyph.start

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self.isReadOnly() or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self.setFocus()
        self._anchor = self._position_at(event.position())
        cursor = self.textCursor()
        cursor.setPosition(self._anchor)
        self.setTextCursor(cursor)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._anchor is None or not self.isReadOnly():
            super().mouseMoveEvent(event)
            return
        cursor = self.textCursor()
        cursor.setPosition(self._anchor)
        cursor.setPosition(self._position_at(event.position()), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._anchor is not None and self.isReadOnly():
            self._anchor = None
            event.accept()
            return
        super().mouseReleaseEvent(event)
