from random import Random

import pytest
from PIL import Image

from e2s.capture.scrolling import ScrollResult, ScrollStitcher


@pytest.mark.parametrize("horizontal", [False, True])
def test_scroll_appends_only_pixels_after_the_overlap(horizontal) -> None:
    random = Random(23)
    colors = [random.randrange(256) for _ in range(140)]
    source = Image.new("RGB", (100, 140))
    source.putdata([(color, color, color) for color in colors for _ in range(source.width)])
    stitcher = ScrollStitcher(horizontal=horizontal)

    def view(image):
        return image.transpose(Image.Transpose.TRANSPOSE) if horizontal else image

    first = view(source.crop((0, 0, 100, 85)))
    second = view(source.crop((0, 31, 100, 116)))
    third = view(source.crop((0, 55, 100, 140)))
    unrelated = Image.new("RGB", first.size, "white")
    assert stitcher.add(first) is ScrollResult.ADDED
    assert stitcher.add(first.copy()) is ScrollResult.UNCHANGED
    assert stitcher.add(unrelated) is ScrollResult.NO_OVERLAP
    assert stitcher.add(second) is ScrollResult.ADDED
    assert stitcher.add(third) is ScrollResult.ADDED
    assert stitcher.frames == 3
    assert stitcher.image().size == view(source).size
    assert stitcher.image().tobytes() == view(source).tobytes()


@pytest.mark.parametrize("horizontal", [False, True])
def test_reverse_scroll_adds_only_content_outside_the_already_captured_range(horizontal) -> None:
    colors = Random(77).choices(range(256), k=150)
    source = Image.new("RGB", (30, 150))
    source.putdata([(value, value, value) for value in colors for _ in range(source.width)])
    stitcher = ScrollStitcher(horizontal=horizontal)

    def view(start: int, end: int) -> Image.Image:
        frame = source.crop((0, start, source.width, end))
        return frame.transpose(Image.Transpose.TRANSPOSE) if horizontal else frame

    assert stitcher.add(view(30, 115)) is ScrollResult.ADDED
    assert stitcher.add(view(55, 140)) is ScrollResult.ADDED
    assert stitcher.add(view(35, 120)) is ScrollResult.UNCHANGED
    assert stitcher.add(view(0, 85)) is ScrollResult.ADDED
    assert stitcher.is_prepend
    assert stitcher.added_part.tobytes() == view(0, 30).tobytes()
    assert stitcher.image().tobytes() == view(0, 140).tobytes()
