from dataclasses import dataclass
from time import monotonic

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from e2s.capture.geometry import SelectionRect
from e2s.platform.windows.uia_selection import (
    HitPhase,
    HitStop,
    SelectorHit,
    WindowsSelector,
)

_REFINE_DELAY_MS = 80

type _Point = tuple[int, int]


@dataclass(frozen=True, slots=True)
class _Query:
    number: int
    point: _Point
    window_only: bool


class SmartSelection(QObject):
    """Manage hover, press and refinement results for one frozen frame."""

    changed = Signal()
    failed = Signal()

    def __init__(
        self, client: WindowsSelector, window_id: int, monitor: SelectionRect, parent: QObject
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._monitor = monitor
        self._screen = SelectionRect(0, 0, monitor.width_px, monitor.height_px)
        self._point: _Point | None = None
        self._changed_at = 0.0
        self._path: tuple[SelectionRect, ...] = ()
        self._index = 0
        self._level_chosen = False
        self._window_only = False
        self._paused = False
        self._ready = False
        self._number = 0
        self._in_flight: _Query | None = None
        self._refinement: _Query | None = None
        self._refinement_started = False
        self._sent_target: tuple[_Point, bool] | None = None
        self._timer = QTimer(self, singleShot=True)
        self._timer.timeout.connect(self._refine)
        self._client.refreshed.connect(self._on_refreshed)
        self._client.hit_received.connect(self._on_hit)
        self._epoch = self._client.refresh(window_id, monitor)

    @property
    def selection(self) -> SelectionRect | None:
        return self._path[self._index] if self._path else None

    @property
    def has_levels(self) -> bool:
        return not self._window_only and len(self._path) > 1

    @property
    def window_only(self) -> bool:
        return self._window_only

    def move(self, point: _Point) -> None:
        if self._paused or self._point == point:
            return
        self._point = point
        self._changed_at = monotonic()
        self._cancel_refinement()
        if self.selection is not None and not _contains_point(self.selection, point):
            self._set_path(tuple(rect for rect in self._path if _contains_point(rect, point)))
        self._request_latest()

    def step(self, delta: int) -> bool:
        if self._paused or not self.has_levels:
            return False
        self._level_chosen = True
        self._index = max(0, min(len(self._path) - 1, self._index + delta))
        self.changed.emit()
        return True

    def toggle_target(self) -> bool:
        if self._paused:
            return False
        self._window_only = not self._window_only
        self._level_chosen = False
        self._index = len(self._path) - 1 if self._window_only and self._path else 0
        self._changed_at = monotonic()
        self._cancel_refinement()
        self._request_latest()
        self.changed.emit()
        return True

    def pause(self) -> None:
        self._paused = True
        self._cancel_refinement()

    def resume(self) -> None:
        self._paused = False
        self._point = None
        self._sent_target = None

    def clear(self) -> None:
        self._point = None
        self._sent_target = None
        self._cancel_refinement()
        self._set_path(())

    def stop(self) -> None:
        if self._epoch:
            self.pause()
            self._epoch = 0
            self._client.release()

    def _set_path(self, path: tuple[SelectionRect, ...], *, refinement: bool = False) -> None:
        if path == self._path:
            return
        chosen = self.selection if refinement and self._level_chosen else None
        self._path = path
        self._level_chosen = chosen is not None and chosen in path
        if self._window_only and path:
            self._index = len(path) - 1
        elif self._level_chosen:
            self._index = path.index(chosen)
        else:
            self._index = 0
        self.changed.emit()

    def _request_latest(self) -> None:
        if not self._ready or self._paused or self._point is None or self._in_flight:
            return
        target = (self._point, self._window_only)
        if self._sent_target == target:
            return
        self._sent_target = target
        self._number += 1
        self._in_flight = _Query(self._number, *target)
        self._client.query(
            self._epoch, self._number, *self._global_point(self._point),
            window_only=self._window_only,
        )

    def _global_point(self, point: _Point) -> _Point:
        return point[0] + self._monitor.left, point[1] + self._monitor.top

    def _cancel_refinement(self) -> None:
        self._timer.stop()
        if self._refinement_started:
            self._client.invalidate_refinement()
        self._refinement = None
        self._refinement_started = False

    @Slot()
    def _refine(self) -> None:
        if self._refinement is not None:
            query = self._refinement
            self._refinement_started = True
            self._client.refine(self._epoch, query.number, *self._global_point(query.point))

    @Slot(int, bool)
    def _on_refreshed(self, epoch: int, ok: bool) -> None:
        if epoch == self._epoch:
            if ok:
                self._ready = True
                self._request_latest()
            else:
                self._fail()

    @Slot()
    def _fail(self) -> None:
        if self._epoch:
            self.stop()
            self.failed.emit()

    @Slot(object)
    def _on_hit(self, result: SelectorHit) -> None:
        if result.epoch != self._epoch:
            return
        if result.phase is HitPhase.INITIAL:
            query = self._in_flight
            if query is None or result.request_id != query.number:
                return
            self._in_flight = None
            self._accept_initial(query, result)
            self._request_latest()
        elif self._refinement is not None and result.request_id == self._refinement.number:
            self._accept_refinement(result)

    def _accept_initial(self, query: _Query, result: SelectorHit) -> None:
        if self._paused or self._point is None or query.window_only != self._window_only:
            return
        path = self._local_path(result.rects)
        if path:
            self._set_path(path)
        elif self._point == query.point:
            self._set_path((self._screen,))
        if self._point == query.point and not query.window_only and result.can_refine:
            self._refinement = query
            elapsed_ms = round((monotonic() - self._changed_at) * 1000)
            self._timer.start(max(0, _REFINE_DELAY_MS - elapsed_ms))

    def _accept_refinement(self, result: SelectorHit) -> None:
        if result.phase is HitPhase.FINISHED:
            self._refinement_started = False
        if not result.ok or result.reason == HitStop.CANCELLED:
            return
        refined = self._local_path(result.rects)
        previous_size = len(self._path)
        if previous_size and len(refined) > previous_size and refined[-previous_size:] == self._path:
            self._set_path(refined, refinement=True)

    def _local_path(self, rects: tuple[SelectionRect, ...]) -> tuple[SelectionRect, ...]:
        if self._point is None:
            return ()
        path = []
        monitor = self._monitor
        for rect in rects:
            local = SelectionRect(
                max(0, rect.left - monitor.left), max(0, rect.top - monitor.top),
                min(self._screen.right, rect.right - monitor.left),
                min(self._screen.bottom, rect.bottom - monitor.top),
            )
            if (
                local.fits(self._screen.width_px, self._screen.height_px)
                and _contains_point(local, self._point)
                and local not in path
            ):
                path.append(local)
        return tuple(path)


def _contains_point(rect: SelectionRect, point: _Point) -> bool:
    x, y = point
    return rect.left <= x < rect.right and rect.top <= y < rect.bottom
