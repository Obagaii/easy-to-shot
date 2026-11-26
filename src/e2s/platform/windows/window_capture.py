import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from e2s.capture.geometry import SelectionRect

_DESKTOP_CLASSES = {"Progman", "WorkerW"}
_DWMWA_EXTENDED_FRAME_BOUNDS = 9
_DWMWA_CLOAKED = 14
_GWL_EXSTYLE = -20
_CLICK_THROUGH_LAYERED = 0x80000 | 0x20


@dataclass(frozen=True, slots=True)
class VisibleWindow:
    window_id: int
    bounds: SelectionRect


def visible_windows(
    overlay_id: int, monitor: SelectionRect,
) -> tuple[VisibleWindow, ...]:
    """Snapshot visible top-level windows on this monitor in desktop Z order."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    dwm = ctypes.WinDLL("dwmapi").DwmGetWindowAttribute
    dwm.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    dwm.restype = ctypes.c_long
    user32.GetShellWindow.restype = wintypes.HWND
    user32.GetDesktopWindow.restype = wintypes.HWND
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    excluded = {overlay_id, user32.GetShellWindow(), user32.GetDesktopWindow()}
    windows = []
    class_name = ctypes.create_unicode_buffer(128)

    @callback_type
    def collect(window_id: int, _data: int) -> bool:
        if (
            window_id in excluded or not user32.IsWindowVisible(window_id)
            or user32.IsIconic(window_id)
        ):
            return True
        window_style = user32.GetWindowLongW(window_id, _GWL_EXSTYLE)
        if window_style & _CLICK_THROUGH_LAYERED == _CLICK_THROUGH_LAYERED:
            return True
        length = user32.GetClassNameW(window_id, class_name, len(class_name))
        if length and class_name.value in _DESKTOP_CLASSES:
            return True
        bounds = wintypes.RECT()
        if (
            dwm(
                window_id, _DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(bounds), ctypes.sizeof(bounds),
            ) != 0
            or bounds.left >= bounds.right or bounds.top >= bounds.bottom
        ) and not user32.GetWindowRect(window_id, ctypes.byref(bounds)):
            return True
        rect = SelectionRect(
            max(bounds.left, monitor.left), max(bounds.top, monitor.top),
            min(bounds.right, monitor.right), min(bounds.bottom, monitor.bottom),
        )
        if min(rect.width_px, rect.height_px) < 2:
            return True
        cloaked = wintypes.DWORD()
        status = dwm(window_id, _DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        if status or not cloaked.value:
            windows.append(VisibleWindow(window_id, rect))
        return True

    user32.EnumWindows(collect, 0)
    return tuple(windows)


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


def monitor_pixel_bounds(window_id: int) -> SelectionRect | None:
    """Return the physical desktop bounds of the monitor containing a window."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    rect = _monitor_bounds(user32, window_id)
    if rect is None:
        return None
    return SelectionRect(rect.left, rect.top, rect.right, rect.bottom)


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
