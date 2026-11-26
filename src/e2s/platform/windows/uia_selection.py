from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum, auto
from functools import partial
from queue import Queue
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from e2s.capture.geometry import SelectionRect
from e2s.platform.windows.window_capture import VisibleWindow, visible_windows

try:
    import comtypes
    from comtypes.client import CreateObject, GetModule
except ImportError:
    comtypes = None

_FOREGROUND_SECONDS = 0.168
_REFINEMENT_SECONDS = 1.5
_REFINEMENT_CALL_SECONDS = 0.5
_PROGRESS_SECONDS = 0.032
_MAX_STEPS = 80
_TYPE_CACHE_LOCK = Lock()
_TIMEOUT_CODES = {0x80131505, 0x800705B4}

type _Point = tuple[int, int]
type _Rectangles = tuple[SelectionRect, ...]


class HitPhase(IntEnum):
    INITIAL = 0
    REFINEMENT = auto()
    FINISHED = auto()


class HitStop(IntEnum):
    COMPLETE = 0
    BUDGET_EXHAUSTED = auto()
    DECODING_PENDING = auto()
    PROVIDER_TIMEOUT = auto()
    PROVIDER_FAILURE = auto()
    CANCELLED = auto()
    TRAVERSAL_LIMIT = auto()


@dataclass(frozen=True, slots=True)
class SelectorHit:
    epoch: int
    request_id: int
    phase: HitPhase
    reason: HitStop
    ok: bool
    rects: _Rectangles

    @property
    def can_refine(self) -> bool:
        return self.ok and self.reason in (
            HitStop.BUDGET_EXHAUSTED, HitStop.DECODING_PENDING, HitStop.PROVIDER_TIMEOUT,
        )


@dataclass(frozen=True, slots=True)
class _Job:
    epoch: int
    request_id: int
    point: _Point
    window: VisibleWindow
    cancellation: Event | None = None

    def cancelled(self) -> bool:
        return self.cancellation is not None and self.cancellation.is_set()


@dataclass(slots=True)
class _ChildBatch:
    array: Any
    count: int
    next_index: int = 0
    decoded: list["_Node"] = field(default_factory=list)


@dataclass(slots=True)
class _Node:
    bounds: SelectionRect
    element: Any = None
    structural: bool = False
    order: int = 0
    children: tuple["_Node", ...] | None = None
    batch: _ChildBatch | None = None
    error: HitStop | None = None


class _UiaProvider:
    """Acquire one layer of the UI Automation Control View at a time."""

    def __init__(self) -> None:
        with _TYPE_CACHE_LOCK:
            api = GetModule("UIAutomationCore.dll")
        self.automation = CreateObject(api.CUIAutomation8, interface=api.IUIAutomation2)
        self.request = self.automation.CreateCacheRequest()
        self.request.TreeScope = api.TreeScope_Element | api.TreeScope_Children
        self.request.TreeFilter = self.automation.ControlViewCondition
        self.request.AddProperty(api.UIA_BoundingRectanglePropertyId)
        self.request.AddProperty(api.UIA_IsOffscreenPropertyId)
        self.request.AddProperty(api.UIA_ControlTypePropertyId)
        self._structural_types = (api.UIA_PaneControlTypeId, api.UIA_GroupControlTypeId)

    def expand(self, node: _Node, window: VisibleWindow, deadline: float, job: _Job) -> HitStop:
        if node.children is not None:
            return HitStop.COMPLETE
        if node.error is not None:
            return node.error
        if monotonic() >= deadline:
            return HitStop.BUDGET_EXHAUSTED
        try:
            if node.batch is None:
                remaining = deadline - monotonic()
                if job.cancellation is not None:
                    remaining = min(remaining, _REFINEMENT_CALL_SECONDS)
                time_ms = max(1, int(remaining * 1000))
                self.automation.ConnectionTimeout = time_ms
                self.automation.TransactionTimeout = time_ms
                if node.element is None:
                    cached = self.automation.ElementFromHandleBuildCache(
                        window.window_id, self.request,
                    )
                else:
                    cached = node.element.BuildUpdatedCache(self.request)
                children = cached.GetCachedChildren()
                if not children:
                    node.children = ()
                    return HitStop.COMPLETE
                node.batch = _ChildBatch(children, children.Length)

            batch = node.batch
            while batch.next_index < batch.count:
                if job.cancelled():
                    return HitStop.CANCELLED
                if monotonic() >= deadline:
                    return HitStop.DECODING_PENDING
                index = batch.next_index
                batch.next_index += 1
                candidate = self._read_child(batch.array, index, window.bounds)
                if candidate is not None:
                    batch.decoded.append(candidate)
            node.children = tuple(batch.decoded)
            node.batch = None
            return HitStop.COMPLETE
        except comtypes.COMError as error:
            if error.hresult & 0xFFFFFFFF in _TIMEOUT_CODES:
                return HitStop.PROVIDER_TIMEOUT
            node.error = HitStop.PROVIDER_FAILURE
            return node.error

    def _read_child(self, array, index: int, window: SelectionRect) -> _Node | None:
        try:
            element = array.GetElement(index)
            if not element or element.CachedIsOffscreen:
                return None
            rect = element.CachedBoundingRectangle
            bounds = SelectionRect(
                max(window.left, rect.left), max(window.top, rect.top),
                min(window.right, rect.right), min(window.bottom, rect.bottom),
            )
            if bounds.width_px < 2 or bounds.height_px < 2:
                return None
        except comtypes.COMError:
            return None
        try:
            structural = element.CachedControlType in self._structural_types
        except comtypes.COMError:
            structural = False
        return _Node(bounds, element, structural, index)


def _contains(bounds: SelectionRect, point: _Point) -> bool:
    x, y = point
    return bounds.left <= x < bounds.right and bounds.top <= y < bounds.bottom


def _hit_child(node: _Node, point: _Point, before: int | None = None) -> _Node | None:
    return next((
        child for child in reversed(node.children or ())
        if (before is None or child.order < before) and _contains(child.bounds, point)
    ), None)


def _find_alternative(path: list[_Node], point: _Point) -> bool:
    # Equal-size layout panes may overlap the actual content without owning its hit.
    while len(path) > 1:
        leaf, parent = path[-1], path[-2]
        if not leaf.structural or leaf.bounds != parent.bounds:
            return False
        sibling = _hit_child(parent, point, before=leaf.order)
        if sibling is not None:
            path[-1] = sibling
            return True
        path.pop()
    return False


def _rectangles(path: list[_Node]) -> _Rectangles:
    return tuple(dict.fromkeys(node.bounds for node in reversed(path)))


def _walk(
    provider: _UiaProvider, root: _Node, job: _Job,
    publish: Callable[[_Rectangles], None],
) -> tuple[_Rectangles, HitStop]:
    refining = job.cancellation is not None
    started = monotonic()
    deadline = started + (_REFINEMENT_SECONDS if refining else _FOREGROUND_SECONDS)
    next_update = started + _PROGRESS_SECONDS
    previous = ()
    path = [root]
    for _ in range(_MAX_STEPS):
        if job.cancelled():
            return _rectangles(path), HitStop.CANCELLED
        result = provider.expand(path[-1], job.window, deadline, job)
        if result is not HitStop.COMPLETE:
            return _rectangles(path), result
        hit = _hit_child(path[-1], job.point)
        if hit is not None:
            path.append(hit)
        elif not _find_alternative(path, job.point):
            return _rectangles(path), HitStop.COMPLETE
        now = monotonic()
        if refining and now >= next_update:
            rects = _rectangles(path)
            if rects != previous and not job.cancelled():
                publish(rects)
                previous = rects
            next_update = now + _PROGRESS_SECONDS
    return _rectangles(path), HitStop.TRAVERSAL_LIMIT


class _Command(IntEnum):
    CLEAR = auto()
    STOP = auto()


class _Worker:
    def __init__(self, publish: Callable[[SelectorHit], None]) -> None:
        self._publish = publish
        self.queue: Queue[_Job | _Command] = Queue()
        self._thread = Thread(target=self._run, name="smart-selection-uia", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self.queue.put(_Command.STOP)
        self._thread.join(timeout=_REFINEMENT_CALL_SECONDS + 0.1)

    def _run(self) -> None:
        provider = None
        initialized = False
        try:
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            initialized = True
            provider = _UiaProvider()
        except (comtypes.COMError, OSError, AttributeError, ImportError):
            pass
        try:
            self._serve(provider)
        finally:
            provider = None
            if initialized:
                comtypes.CoUninitialize()

    def _serve(self, provider: _UiaProvider | None) -> None:
        epoch = 0
        roots: dict[VisibleWindow, _Node] = {}
        while True:
            job = self.queue.get()
            if job is _Command.STOP:
                return
            if job is _Command.CLEAR:
                roots.clear()
                continue
            if job.epoch != epoch:
                epoch = job.epoch
                roots.clear()
            phase = HitPhase.FINISHED if job.cancellation is not None else HitPhase.INITIAL
            rects = (job.window.bounds,)
            stop = HitStop.CANCELLED if job.cancelled() else HitStop.PROVIDER_FAILURE
            if provider is not None and not job.cancelled():
                root = roots.get(job.window)
                if root is None:
                    root = roots[job.window] = _Node(job.window.bounds)
                rects, stop = _walk(
                    provider, root, job,
                    partial(self._send, job, HitPhase.REFINEMENT, HitStop.DECODING_PENDING),
                )
            self._send(job, phase, stop, rects)

    def _send(self, job: _Job, phase: HitPhase, stop: HitStop, rects: _Rectangles) -> None:
        self._publish(SelectorHit(job.epoch, job.request_id, phase, stop, True, rects))


class WindowsSelector(QObject):
    """Provide a frozen window snapshot and two independent UI Automation workers."""

    refreshed = Signal(int, bool)
    hit_received = Signal(object)

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._epoch = 0
        self._windows: tuple[VisibleWindow, ...] = ()
        self._foreground: _Worker | None = None
        self._refinement: _Worker | None = None
        self._cancellation: Event | None = None
        self._closed = False

    @property
    def available(self) -> bool:
        return not self._closed

    def refresh(self, window_id: int, monitor: SelectionRect) -> int:
        self.release()
        self._epoch += 1
        epoch = self._epoch
        self._windows = visible_windows(window_id, monitor)
        QTimer.singleShot(0, lambda: self.refreshed.emit(epoch, True))
        return epoch

    def query(self, epoch: int, number: int, x: int, y: int, *, window_only: bool) -> None:
        window = self._find_window(epoch, (x, y))
        if window is None or window_only or comtypes is None:
            rects = (window.bounds,) if window is not None else ()
            hit = SelectorHit(epoch, number, HitPhase.INITIAL, HitStop.COMPLETE, True, rects)
            QTimer.singleShot(0, lambda: self._publish(hit))
            return
        if self._foreground is None:
            self._foreground = _Worker(self._publish)
        self._foreground.queue.put(_Job(epoch, number, (x, y), window))

    def refine(self, epoch: int, number: int, x: int, y: int) -> None:
        window = self._find_window(epoch, (x, y))
        if window is None or comtypes is None:
            return
        self.invalidate_refinement()
        self._cancellation = Event()
        if self._refinement is None:
            self._refinement = _Worker(self._publish)
        self._refinement.queue.put(_Job(epoch, number, (x, y), window, self._cancellation))

    def invalidate_refinement(self) -> None:
        if self._cancellation is not None:
            self._cancellation.set()
            self._cancellation = None

    def release(self) -> None:
        self._windows = ()
        self.invalidate_refinement()
        for worker in (self._foreground, self._refinement):
            if worker is not None:
                worker.queue.put(_Command.CLEAR)

    def close(self) -> None:
        self._closed = True
        self.release()
        for worker in (self._foreground, self._refinement):
            if worker is not None:
                worker.close()

    def _find_window(self, epoch: int, point: _Point) -> VisibleWindow | None:
        if not self._closed and self._epoch == epoch:
            return next((window for window in self._windows if _contains(window.bounds, point)), None)
        return None

    def _publish(self, hit: SelectorHit) -> None:
        if not self._closed and self._epoch == hit.epoch:
            self.hit_received.emit(hit)
