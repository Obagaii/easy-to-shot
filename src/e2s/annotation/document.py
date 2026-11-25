from dataclasses import dataclass

from PySide6.QtGui import QImage

from e2s.annotation.elements import MASK_TOOLS, Element, Tool


@dataclass(frozen=True, slots=True)
class Edit:
    index: int
    before: Element | None
    after: Element | None

    def apply(self, elements: list[Element], *, reverse: bool = False) -> None:
        before, after = (self.after, self.before) if reverse else (self.before, self.after)
        if after is None:
            del elements[self.index]
        elif before is None:
            elements.insert(self.index, after)
        else:
            elements[self.index] = after


class AnnotationDocument:
    """Own a frozen crop and edit its ordered elements on the GUI thread."""

    def __init__(self, source: QImage, origin_px: tuple[int, int] = (0, 0)) -> None:
        self.set_source(source, origin_px)
        self._elements: list[Element] = []
        self._past: list[tuple[Edit, ...]] = []
        self._future: list[tuple[Edit, ...]] = []
        self._revision = 0

    @property
    def source(self) -> QImage:
        """Return a copy-on-write view of the selected source pixels."""
        return QImage(self._source)

    @property
    def origin_px(self) -> tuple[int, int]:
        return self._origin_px

    def set_source(self, source: QImage, origin_px: tuple[int, int]) -> None:
        """Replace the crop without moving the elements in the frozen frame."""
        self._source = QImage(source)
        self._origin_px = origin_px

    @property
    def elements(self) -> tuple[Element, ...]:
        return tuple(self._elements)

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def can_undo(self) -> bool:
        return bool(self._past)

    @property
    def can_redo(self) -> bool:
        return bool(self._future)

    def add(self, element: Element) -> int:
        return self.add_many((element,))[0]

    def add_many(self, elements: tuple[Element, ...]) -> tuple[int, ...]:
        edits = tuple(Edit(index, None, element)
                      for index, element in enumerate(elements, start=len(self._elements)))
        if edits:
            self._record(*edits)
        return tuple(edit.index for edit in edits)

    def replace(self, index: int, element: Element) -> None:
        self.replace_many({index: element})

    def replace_many(self, replacements: dict[int, Element]) -> None:
        edits = tuple(
            Edit(index, self._elements[index], element)
            for index, element in replacements.items() if self._elements[index] != element
        )
        if edits:
            self._record(*edits)

    def delete(self, index: int) -> None:
        self.delete_many({index})

    def delete_many(self, indexes: set[int]) -> None:
        if indexes:
            self._record(*(Edit(i, self._elements[i], None) for i in sorted(indexes, reverse=True)))

    def move_layers(self, indexes: set[int], action: str) -> set[int]:
        occupied = [
            index for index, element in enumerate(self._elements)
            if element.tool not in (*MASK_TOOLS, Tool.WATERMARK)
        ]
        order = occupied.copy()
        if action in ("top", "bottom"):
            order.sort(key=lambda index: (index in indexes) == (action == "top"))
        else:
            direction = 1 if action == "raise" else -1
            positions = range(len(order) - 2, -1, -1) if direction > 0 else range(1, len(order))
            for i in positions:
                other = i + direction
                if order[i] in indexes and order[other] not in indexes:
                    order[i], order[other] = order[other], order[i]
        self.replace_many({i: self._elements[old] for i, old in zip(occupied, order, strict=True)})
        return {i for i, old in zip(occupied, order, strict=True) if old in indexes}

    def undo(self) -> None:
        if self._past:
            edits = self._past.pop()
            for edit in reversed(edits):
                edit.apply(self._elements, reverse=True)
            self._future.append(edits)
            self._revision += 1

    def redo(self) -> None:
        if self._future:
            edits = self._future.pop()
            for edit in edits:
                edit.apply(self._elements)
            self._past.append(edits)
            self._revision += 1

    def _record(self, *edits: Edit) -> None:
        for edit in edits:
            edit.apply(self._elements)
        self._past.append(edits)
        self._future.clear()
        self._revision += 1
