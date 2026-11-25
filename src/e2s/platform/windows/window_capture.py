import ctypes
from ctypes import wintypes

from e2s.capture.geometry import SelectionRect


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


def scroll_window_below(
    anchor_id: int, selection: SelectionRect, *, horizontal: bool
) -> bool:
    """Post one wheel step to the window under the capture center."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo)]
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

    info = _MonitorInfo()
    info.size = ctypes.sizeof(info)
    monitor = user32.MonitorFromWindow(anchor_id, 2)
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return False
    point = wintypes.POINT(
        info.monitor.left + (selection.left + selection.right) // 2,
        info.monitor.top + (selection.top + selection.bottom) // 2,
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
