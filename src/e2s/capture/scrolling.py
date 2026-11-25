from collections import deque
from enum import Enum

from PIL import Image, ImageChops, ImageFilter, ImageStat

_MAX_PIXELS = 75_000_000
_SAMPLE_COLUMNS = 48


class ScrollResult(Enum):
    ADDED = "added"
    UNCHANGED = "unchanged"
    NO_OVERLAP = "no_overlap"
    FULL = "full"


class ScrollStitcher:
    """Assemble overlapping views as the source scrolls along a single axis."""

    def __init__(self, *, horizontal: bool = False) -> None:
        self.horizontal = horizontal
        self._last: Image.Image | None = None
        self._parts: deque[Image.Image] = deque()
        self._start = 0
        self._end = 0
        self._position = 0
        self.added_part: Image.Image | None = None
        self.is_prepend = False

    @property
    def frames(self) -> int:
        return len(self._parts)

    @property
    def size(self) -> tuple[int, int]:
        if self._last is None:
            return 0, 0
        size = self._last.width, self._end - self._start
        return size[::-1] if self.horizontal else size

    def add(self, source: Image.Image) -> ScrollResult:
        view = source.transpose(Image.Transpose.TRANSPOSE) if self.horizontal else source
        width, height = view.size
        self.added_part = None
        if self._last is None:
            self._parts.append(view)
            self._last = view
            self._end = height
            self.added_part = source
            return ScrollResult.ADDED
        if view.size != self._last.size:
            return ScrollResult.NO_OVERLAP
        if ImageChops.difference(view, self._last).getbbox(alpha_only=False) is None:
            return ScrollResult.UNCHANGED
        shift = _scroll_shift(self._last, view)
        if shift is None:
            return ScrollResult.NO_OVERLAP
        position = self._position + shift
        end = position + height
        start_added = max(0, self._start - position)
        end_added = max(0, end - self._end)
        if (self._end - self._start + start_added + end_added) * width > _MAX_PIXELS:
            return ScrollResult.FULL
        self._position = position
        self._last = view
        if start_added:
            part = view.crop((0, 0, width, start_added))
            self._parts.appendleft(part)
            self._start = position
        elif end_added:
            part = view.crop((0, height - end_added, width, height))
            self._parts.append(part)
            self._end = end
        else:
            return ScrollResult.UNCHANGED
        self.is_prepend = start_added > 0
        self.added_part = part.transpose(Image.Transpose.TRANSPOSE) if self.horizontal else part
        return ScrollResult.ADDED

    def image(self) -> Image.Image:
        if self._last is None:
            raise ValueError("There are no captured views")
        combined = Image.new(self._last.mode, (self._last.width, self._end - self._start))
        offset = 0
        for part in self._parts:
            combined.paste(part, (0, offset))
            offset += part.height
        return combined.transpose(Image.Transpose.TRANSPOSE) if self.horizontal else combined


def _scroll_shift(previous: Image.Image, current: Image.Image) -> int | None:
    width, height = current.size
    if height < 24:
        return None
    inset = min(width // 8, 32)
    samples = min(_SAMPLE_COLUMNS, width - 2 * inset)
    old, new = [
        view.crop((inset, 0, width - inset, height)).convert("L").resize(
            (samples, height), Image.Resampling.BOX
        )
        for view in (previous, current)
    ]
    result = _match_direction(old, new)
    if result is not None:
        return result
    # At fractional display scaling a scroll may land between physical rows.
    blur = ImageFilter.GaussianBlur(0.9)
    old, new = old.filter(blur), new.filter(blur)
    stationary = ImageStat.Stat(ImageChops.difference(old, new)).mean[0]
    if stationary < 3:
        return None
    return _match_direction(old, new, maximum_error=min(8, stationary * 0.55))


def _match_direction(old: Image.Image, new: Image.Image, maximum_error: float = 12) -> int | None:
    forward = _match_shift(old, new, maximum_error)
    backward = _match_shift(new, old, maximum_error)
    if forward is not None and (backward is None or forward <= backward):
        return forward[1]
    return -backward[1] if backward is not None else None


def _match_shift(
    old: Image.Image, new: Image.Image, maximum_error: float
) -> tuple[float, int] | None:
    samples, height = old.size
    old_bytes, new_bytes = old.tobytes(), new.tobytes()
    trim = max(1, min(24, height // 12))
    best: tuple[float, int] | None = None
    for shift in range(1, height - max(20, height // 5)):
        stop = height - shift - trim
        if stop <= trim:
            break
        positions = range(trim, stop, max(1, (stop - trim) // 8))
        differences = []
        for y in positions:
            a = (y + shift) * samples
            b = y * samples
            differences.append(sum(
                abs(x - y) for x, y in zip(old_bytes[a:a + samples], new_bytes[b:b + samples])
            ))
        score = sum(differences) / (len(differences) * samples)
        candidate = (score, shift)
        if best is None or candidate < best:
            best = candidate
    if best is None or best[0] > maximum_error + 2:
        return None
    shift = best[1]
    stop = height - shift - trim
    diff = ImageChops.difference(
        old.crop((0, trim + shift, samples, stop + shift)),
        new.crop((0, trim, samples, stop)),
    )
    score = ImageStat.Stat(diff).mean[0]
    return (score, shift) if score <= maximum_error else None
