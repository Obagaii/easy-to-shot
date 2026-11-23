from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Self


MIN_FONT_SIZE_PX = 8
MAX_FONT_SIZE_PX = 256
MAX_STROKE_WIDTH_PX = 32

type Point = tuple[float, float]


class Tool(StrEnum):
    SELECT = "select"
    RECTANGLE = "rectangle"
    ELLIPSE = "ellipse"
    LINE = "line"
    ARROW = "arrow"
    PEN = "pen"
    TEXT = "text"
    MOSAIC = "mosaic"


@dataclass(frozen=True, slots=True)
class Stroke:
    tool: Tool
    points: tuple[Point, ...]
    color: str
    width_px: int
    is_filled: bool = False

    def translated(self, dx: float, dy: float) -> Self:
        return replace(self, points=tuple((x + dx, y + dy) for x, y in self.points))


@dataclass(frozen=True, slots=True)
class Text:
    origin: Point
    value: str
    color: str
    font_size_px: int

    def translated(self, dx: float, dy: float) -> Self:
        x, y = self.origin
        return replace(self, origin=(x + dx, y + dy))


@dataclass(frozen=True, slots=True)
class Mosaic:
    start: Point
    end: Point
    block_size_px: int

    def translated(self, dx: float, dy: float) -> Self:
        x1, y1 = self.start
        x2, y2 = self.end
        return replace(self, start=(x1 + dx, y1 + dy), end=(x2 + dx, y2 + dy))


type Element = Stroke | Text | Mosaic
