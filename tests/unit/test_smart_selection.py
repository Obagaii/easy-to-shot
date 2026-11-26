from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from e2s.capture.geometry import SelectionRect
from e2s.platform.windows.uia_selection import (
    HitPhase,
    HitStop,
    SelectorHit,
    _Job,
    _Node,
    _walk,
)
from e2s.platform.windows.window_capture import VisibleWindow
from e2s.ui.native.smart_selection import SmartSelection


class SelectorStub(QObject):
    refreshed = Signal(int, bool)
    hit_received = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.queries = []
        self.refinements = []
        self.invalidations = 0

    def refresh(self, _window_id, _monitor) -> int:
        return 1

    def query(self, epoch, number, x, y, *, window_only) -> None:
        self.queries.append((epoch, number, x, y, window_only))

    def refine(self, epoch, number, x, y) -> None:
        self.refinements.append((epoch, number, x, y))

    def invalidate_refinement(self) -> None:
        self.invalidations += 1


def test_paths_are_clipped_and_stale_results_are_ignored(app: QApplication) -> None:
    selector = SelectorStub()
    monitor = SelectionRect(-200, 25, 0, 125)
    left = SelectionRect(-200, 25, -100, 110)
    right = SelectionRect(-100, 25, 10, 110)
    smart = SmartSelection(selector, 1, monitor, selector)

    smart.move((20, 20))
    selector.refreshed.emit(1, True)
    assert selector.queries == [(1, 1, -180, 45, False)]
    smart.move((140, 30))
    selector.hit_received.emit(SelectorHit(1, 1, HitPhase.INITIAL, 0, True, (left,)))
    assert smart.selection is None
    assert selector.queries[-1] == (1, 2, -60, 55, False)

    selector.hit_received.emit(SelectorHit(1, 2, HitPhase.INITIAL, 1, True, (right,)))
    assert smart.selection == SelectionRect(100, 0, 200, 85)
    QTest.qWait(115)
    assert selector.refinements == [(1, 2, -60, 55)]

    child = SelectionRect(-80, 35, -32, 71)
    selector.hit_received.emit(SelectorHit(1, 2, HitPhase.REFINEMENT, 1, True, (child, right)))
    assert smart.selection == SelectionRect(120, 10, 168, 46)
    smart.pause()
    assert selector.invalidations == 1
    selector.hit_received.emit(SelectorHit(1, 2, HitPhase.FINISHED, 0, True, (right,)))
    assert smart.selection == SelectionRect(120, 10, 168, 46)


def test_redundant_structural_panes_do_not_hide_controls_and_tree_is_reused() -> None:
    frame = SelectionRect(0, 0, 300, 180)
    button = SelectionRect(25, 25, 80, 58)
    content = _Node(frame, "page", order=0)
    wrapper = _Node(frame, "outer-pane", structural=True, order=1)
    redundant_leaf = _Node(frame, "inner-group", structural=True)
    root = _Node(frame, "window")
    layers = {
        "window": (content, wrapper),
        "outer-pane": (redundant_leaf,),
        "inner-group": (),
        "page": (_Node(button, "button"),),
        "button": (),
    }
    loads = []

    class Provider:
        def expand(self, node, _window, _deadline, _job):
            if node.children is None:
                loads.append(node.element)
                node.children = layers[node.element]
            return HitStop.COMPLETE

    job = _Job(1, 1, (42, 38), VisibleWindow(5, frame))
    provider = Provider()
    for _ in range(2):
        path, stop = _walk(provider, root, job, lambda _: None)
        assert stop is HitStop.COMPLETE
        assert path == (button, frame)
    assert loads == ["window", "outer-pane", "inner-group", "page", "button"]
