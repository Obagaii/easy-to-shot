import ctypes
from ctypes import wintypes

from e2s.capture.geometry import SelectionRect

_DWMWA_EXTENDED_FRAME_BOUNDS = 9
_DWMWA_CLOAKED = 14
_GWL_EXSTYLE = -20
_WS_EX_TRANSPARENT = 0x20
_WS_EX_LAYERED = 0x80000
_CWP_SKIPINVISIBLE = 0x1
_CWP_SKIPTRANSPARENT = 0x4


def exclude_capture_window(window_id: int) -> bool:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    set_affinity = user32.SetWindowDisplayAffinity
    set_affinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    set_affinity.restype = wintypes.BOOL
    return bool(set_affinity(window_id, 0x11))


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("monitor", wintypes.RECT),
        ("work", wintypes.RECT),
        ("flags", wintypes.DWORD),
    ]


class WindowSelection:
    """Hit-test visible windows on the capture monitor in source pixels."""

    def __init__(self, overlay_id: int) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32 = user32
        self._dwm_attribute = ctypes.WinDLL("dwmapi").DwmGetWindowAttribute
        self._dwm_attribute.argtypes = [
            wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
        ]
        self._dwm_attribute.restype = ctypes.c_long

        user32.GetShellWindow.restype = wintypes.HWND
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        user32.ChildWindowFromPointEx.argtypes = [wintypes.HWND, wintypes.POINT, wintypes.UINT]
        user32.ChildWindowFromPointEx.restype = wintypes.HWND

        self._monitor = _monitor_bounds(user32, overlay_id)
        self._windows: list[tuple[int, SelectionRect]] = []
        if self._monitor is not None:
            self._snapshot_windows(overlay_id, self._monitor)

    def _snapshot_windows(self, overlay_id: int, monitor: wintypes.RECT) -> None:
        desktop_id = self._user32.GetShellWindow()
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self._user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]

        @callback_type
        def collect(window_id: int, _data: int) -> bool:
            if window_id not in (overlay_id, desktop_id):
                bounds = self._visible_bounds(window_id, monitor)
                if bounds is not None:
                    self._windows.append((window_id, bounds))
            return True

        self._user32.EnumWindows(collect, 0)

    def _visible_bounds(self, window_id: int, monitor: wintypes.RECT) -> SelectionRect | None:
        user32 = self._user32
        if not user32.IsWindowVisible(window_id) or user32.IsIconic(window_id):
            return None
        style = user32.GetWindowLongW(window_id, _GWL_EXSTYLE)
        click_through = _WS_EX_LAYERED | _WS_EX_TRANSPARENT
        if style & click_through == click_through:
            return None
        bounds = wintypes.RECT()
        if (
            self._dwm_attribute(
                window_id, _DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(bounds), ctypes.sizeof(bounds)
            ) != 0
            or bounds.left >= bounds.right or bounds.top >= bounds.bottom
        ) and not user32.GetWindowRect(window_id, ctypes.byref(bounds)):
            return None
        clipped = _clip_bounds(bounds, monitor)
        if clipped is None:
            return None
        cloaked = wintypes.DWORD()
        if self._dwm_attribute(
            window_id, _DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
        ) == 0 and cloaked.value:
            return None
        return clipped

    def hit_path(self, x_px: int, y_px: int) -> tuple[SelectionRect, ...]:
        """Return the deepest native child first, followed by its enclosing windows."""
        monitor = self._monitor
        if monitor is None:
            return ()
        width, height = monitor.right - monitor.left, monitor.bottom - monitor.top
        if not (0 <= x_px < width and 0 <= y_px < height):
            return ()
        x, y = monitor.left + x_px, monitor.top + y_px
        for window_id, bounds in self._windows:
            if bounds.left <= x < bounds.right and bounds.top <= y < bounds.bottom:
                path = self._child_path(window_id, bounds, x, y)
                return tuple(
                    SelectionRect(
                        rect.left - monitor.left, rect.top - monitor.top,
                        rect.right - monitor.left, rect.bottom - monitor.top,
                    )
                    for rect in reversed(path)
                )
        return (SelectionRect(0, 0, width, height),)

    def _child_path(
        self, window_id: int, bounds: SelectionRect, x: int, y: int
    ) -> list[SelectionRect]:
        user32 = self._user32
        path = [bounds]
        parent = wintypes.RECT(bounds.left, bounds.top, bounds.right, bounds.bottom)
        while True:
            point = wintypes.POINT(x, y)
            if not user32.ScreenToClient(window_id, ctypes.byref(point)):
                break
            child = user32.ChildWindowFromPointEx(
                window_id, point, _CWP_SKIPINVISIBLE | _CWP_SKIPTRANSPARENT
            )
            if not child or child == window_id:
                break
            child_bounds = wintypes.RECT()
            if not user32.GetWindowRect(child, ctypes.byref(child_bounds)):
                break
            clipped = _clip_bounds(child_bounds, parent)
            if clipped is None or not (
                clipped.left <= x < clipped.right and clipped.top <= y < clipped.bottom
            ):
                break
            if clipped != path[-1]:
                path.append(clipped)
                parent = wintypes.RECT(clipped.left, clipped.top, clipped.right, clipped.bottom)
            window_id = child
        return path


def _clip_bounds(bounds: wintypes.RECT, limit: wintypes.RECT) -> SelectionRect | None:
    rect = SelectionRect(
        max(bounds.left, limit.left), max(bounds.top, limit.top),
        min(bounds.right, limit.right), min(bounds.bottom, limit.bottom),
    )
    if rect.width_px < 2 or rect.height_px < 2:
        return None
    return rect


def _monitor_bounds(user32: ctypes.WinDLL, anchor_id: int) -> wintypes.RECT | None:
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo)]
    info = _MonitorInfo()
    info.size = ctypes.sizeof(info)
    monitor = user32.MonitorFromWindow(anchor_id, 2)
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    return info.monitor


def scroll_window_below(
    anchor_id: int, selection: SelectionRect, *, horizontal: bool
) -> bool:
    """Post one wheel step to the window under the capture center."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetTopWindow.argtypes = [wintypes.HWND]
    user32.GetTopWindow.restype = wintypes.HWND
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowEnabled.argtypes = [wintypes.HWND]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.ChildWindowFromPointEx.argtypes = [wintypes.HWND, wintypes.POINT, wintypes.UINT]
    user32.ChildWindowFromPointEx.restype = wintypes.HWND
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

    monitor = _monitor_bounds(user32, anchor_id)
    if monitor is None:
        return False
    point = wintypes.POINT(
        monitor.left + (selection.left + selection.right) // 2,
        monitor.top + (selection.top + selection.bottom) // 2,
    )
    own_process = ctypes.WinDLL("kernel32").GetCurrentProcessId()
    process = wintypes.DWORD()
    rect = wintypes.RECT()
    target = user32.GetTopWindow(None)
    while target:
        user32.GetWindowThreadProcessId(target, ctypes.byref(process))
        if (
            process.value != own_process and user32.IsWindowVisible(target)
            and user32.IsWindowEnabled(target) and user32.GetWindowRect(target, ctypes.byref(rect))
            and rect.left <= point.x < rect.right and rect.top <= point.y < rect.bottom
        ):
            break
        target = user32.GetWindow(target, 2)
    if not target:
        return False

    while True:
        client = wintypes.POINT(point.x, point.y)
        if not user32.ScreenToClient(target, ctypes.byref(client)):
            return False
        child = user32.ChildWindowFromPointEx(target, client, 0x0007)
        if child in (None, target):
            break
        target = child
    packed_point = (point.x & 0xffff) | ((point.y & 0xffff) << 16)
    delta = 120 if horizontal else -120
    return bool(user32.PostMessageW(
        target, 0x020E if horizontal else 0x020A, (delta & 0xffff) << 16, packed_point
    ))
