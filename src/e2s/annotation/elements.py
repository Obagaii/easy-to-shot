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


type Element = Stroke | Text
