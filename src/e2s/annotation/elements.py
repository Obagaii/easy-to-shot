from dataclasses import dataclass, replace
from enum import StrEnum
from typing import ClassVar, Self

from PySide6.QtGui import QImage

MIN_FONT_SIZE_PX = 8
MAX_FONT_SIZE_PX = 256
MAX_STROKE_WIDTH_PX = 72

type Point = tuple[float, float]


class Tool(StrEnum):
    MOVE = "move"
    SELECT = "select"
    RECTANGLE = "rectangle"
    ELLIPSE = "ellipse"
    ARROW = "arrow"
    PEN = "pen"
    HIGHLIGHT = "highlight"
    RECT_HIGHLIGHT = "rect_highlight"
    WATERMARK = "watermark"
    ERASER = "eraser"
    RECT_ERASER = "rect_eraser"
    BRUSH_ERASER = "brush_eraser"
    TEXT = "text"
    IMAGE_PATCH = "image_patch"


SHAPE_TOOLS = (Tool.RECTANGLE, Tool.ELLIPSE)
HIGHLIGHT_TOOLS = (Tool.RECT_HIGHLIGHT, Tool.HIGHLIGHT)
ERASER_TOOLS = (Tool.ERASER, Tool.RECT_ERASER, Tool.BRUSH_ERASER)
MASK_TOOLS = (Tool.RECT_ERASER, Tool.BRUSH_ERASER)


@dataclass(frozen=True, slots=True)
class StrokeStyle:
    fill_color: str = ""
    corner_radius_px: int = 0
    line_style: str = "solid"
    line_effect: str = "precise"
    arrow_type: str = "straight"
    arrow_ratio: int = 35
    arrow_outline: str = ""
    arrow_outline_width: int = 0
    start_head: str = "none"
    end_head: str = "triangle"
    shaft: str = "solid"
    brush_mode: str = "regular"
    highlight_border: int = 0
    highlight_outline: str = "#fadb14"


@dataclass(frozen=True, slots=True)
class TextStyle:
    family: str = ""
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikethrough: bool = False
    alignment: str = "left"
    outline: str = ""
    outline_width: int = 2
    background: str = ""
    corner_radius_px: int = 0


@dataclass(frozen=True, slots=True)
class WatermarkStyle:
    value: str = ""
    angle: int = 30
    gap_px: int = 56
    opacity: int = 16


@dataclass(frozen=True, slots=True)
class Stroke:
    tool: Tool
    points: tuple[Point, ...]
    color: str
    width_px: int
    is_filled: bool = False
    style: StrokeStyle = StrokeStyle()
    pressures: tuple[float, ...] = ()
    control: Point | None = None
    opacity: int = 100

    def translated(self, dx: float, dy: float) -> Self:
        control = None if self.control is None else (self.control[0] + dx, self.control[1] + dy)
        return replace(self, points=tuple((x + dx, y + dy) for x, y in self.points), control=control)


@dataclass(frozen=True, slots=True)
class Text:
    origin: Point
    value: str
    color: str
    font_size_px: int
    tool: Tool = Tool.TEXT
    style: TextStyle = TextStyle()
    watermark: WatermarkStyle = WatermarkStyle()
    opacity: int = 100

    def translated(self, dx: float, dy: float) -> Self:
        x, y = self.origin
        return replace(self, origin=(x + dx, y + dy))


@dataclass(frozen=True, slots=True)
class ImagePatch:
    """An undoable, frame-relative raster overlay with transparent areas."""

    origin: Point
    image: QImage
    tool: ClassVar[Tool] = Tool.IMAGE_PATCH


type Element = Stroke | Text
type Annotation = Element | ImagePatch
