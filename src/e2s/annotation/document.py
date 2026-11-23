from dataclasses import dataclass

from PySide6.QtGui import QImage

from e2s.annotation.elements import Element


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
        self._past: list[Edit] = []
        self._future: list[Edit] = []
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
        index = len(self._elements)
        self._record(Edit(index, None, element))
        return index

    def replace(self, index: int, element: Element) -> None:
        previous = self._elements[index]
        if previous != element:
            self._record(Edit(index, previous, element))

    def delete(self, index: int) -> None:
        self._record(Edit(index, self._elements[index], None))

    def undo(self) -> None:
        if self._past:
            edit = self._past.pop()
            edit.apply(self._elements, reverse=True)
            self._future.append(edit)
            self._revision += 1

    def redo(self) -> None:
        if self._future:
            edit = self._future.pop()
            edit.apply(self._elements)
            self._past.append(edit)
            self._revision += 1

    def _record(self, edit: Edit) -> None:
        edit.apply(self._elements)
        self._past.append(edit)
        self._future.clear()
        self._revision += 1
