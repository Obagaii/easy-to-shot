from dataclasses import dataclass
from enum import Enum
from math import ceil, floor

_MIN_SELECTION_PX = 2


@dataclass(frozen=True, slots=True)
class SelectionRect:
    """A half-open [left, right) × [top, bottom) rectangle in source pixels."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width_px(self) -> int:
        return self.right - self.left

    @property
    def height_px(self) -> int:
        return self.bottom - self.top

    def fits(self, width_px: int, height_px: int) -> bool:
        return (
            0 <= self.left < self.right <= width_px
            and 0 <= self.top < self.bottom <= height_px
            and self.width_px >= _MIN_SELECTION_PX
            and self.height_px >= _MIN_SELECTION_PX
        )


@dataclass(frozen=True, slots=True)
class ScreenCoordinates:
    origin_x_dip: int
    origin_y_dip: int
    width_dip: int
    height_dip: int
    width_px: int
    height_px: int

    def to_source(self, x_dip: float, y_dip: float) -> tuple[float, float]:
        """Convert Qt desktop coordinates to continuous, screen-local source coordinates."""
        x_px = (x_dip - self.origin_x_dip) / self.width_dip * self.width_px
        y_px = (y_dip - self.origin_y_dip) / self.height_dip * self.height_px
        return x_px, y_px

    def to_local_dip(self, x_px: int, y_px: int) -> tuple[float, float]:
        return (
            x_px / self.width_px * self.width_dip,
            y_px / self.height_px * self.height_dip,
        )


class Corner(Enum):
    TOP_LEFT = (True, True)
    TOP_RIGHT = (False, True)
    BOTTOM_LEFT = (True, False)
    BOTTOM_RIGHT = (False, False)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def move_selection(
    selection: SelectionRect, dx_px: int, dy_px: int, width_px: int, height_px: int
) -> SelectionRect:
    left = max(0, min(width_px - selection.width_px, selection.left + dx_px))
    top = max(0, min(height_px - selection.height_px, selection.top + dy_px))
    return SelectionRect(left, top, left + selection.width_px, top + selection.height_px)


@dataclass(frozen=True, slots=True)
class SelectionDrag:
    origin: tuple[float, float]
    selection: SelectionRect | None = None
    corner: Corner | None = None

    def update(
        self, position: tuple[float, float], width_px: int, height_px: int
    ) -> SelectionRect | None:
        x_px, y_px = position
        origin_x, origin_y = self.origin
        if self.selection is None:
            left, right = sorted(
                (_clamp(origin_x, 0, width_px), _clamp(x_px, 0, width_px))
            )
            top, bottom = sorted(
                (_clamp(origin_y, 0, height_px), _clamp(y_px, 0, height_px))
            )
            if right - left < _MIN_SELECTION_PX or bottom - top < _MIN_SELECTION_PX:
                return None
        elif self.corner is None:
            # Quantize the displacement as one unit so a move preserves the pixel size.
            return move_selection(
                self.selection, round(x_px - origin_x), round(y_px - origin_y), width_px, height_px
            )
        else:
            left, top, right, bottom = self._resized_edges(
                x_px - origin_x, y_px - origin_y, width_px, height_px
            )
        return SelectionRect(floor(left), floor(top), ceil(right), ceil(bottom))

    def _resized_edges(
        self, dx_px: float, dy_px: float, width_px: int, height_px: int
    ) -> tuple[float, float, float, float]:
        selection = self.selection
        moves_left, moves_top = self.corner.value
        left, top = selection.left, selection.top
        right, bottom = selection.right, selection.bottom
        if moves_left:
            left = _clamp(left + dx_px, 0, right - _MIN_SELECTION_PX)
        else:
            right = _clamp(right + dx_px, left + _MIN_SELECTION_PX, width_px)
        if moves_top:
            top = _clamp(top + dy_px, 0, bottom - _MIN_SELECTION_PX)
        else:
            bottom = _clamp(bottom + dy_px, top + _MIN_SELECTION_PX, height_px)
        return left, top, right, bottom
