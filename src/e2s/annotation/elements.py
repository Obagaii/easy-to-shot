from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Self


MAX_STROKE_WIDTH_PX = 32

type Point = tuple[float, float]


class Tool(StrEnum):
    SELECT = "select"
    RECTANGLE = "rectangle"
    ELLIPSE = "ellipse"
    LINE = "line"
    ARROW = "arrow"
    PEN = "pen"


@dataclass(frozen=True, slots=True)
class Stroke:
    tool: Tool
    points: tuple[Point, ...]
    color: str
    width_px: int
    is_filled: bool = False

    def translated(self, dx: float, dy: float) -> Self:
        return replace(self, points=tuple((x + dx, y + dy) for x, y in self.points))


type Element = Stroke
