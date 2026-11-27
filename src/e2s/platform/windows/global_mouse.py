import ctypes
import sys
from ctypes import wintypes
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from e2s.storage.quick_capture import QuickCaptureBinding


class _MouseInfo(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("extraInfo", ctypes.c_size_t)]


class GlobalMouseCapture(QObject):
    drag_event = Signal(str, int, int)

    def __init__(self, binding: QuickCaptureBinding, available: Callable[[], bool]) -> None:
        super().__init__()
        self.binding = binding
        self._available = available
        self._active = False
        self._button = None
        self._hook = None
        self._user32 = None
        self._callback = None
        if sys.platform != "win32":
            return
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        self._callback = callback_type(self._handle)
        self._user32.SetWindowsHookExW.argtypes = (ctypes.c_int, callback_type, wintypes.HINSTANCE, wintypes.DWORD)
        self._user32.SetWindowsHookExW.restype = wintypes.HANDLE
        self._user32.CallNextHookEx.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        self._user32.CallNextHookEx.restype = ctypes.c_ssize_t
        self._user32.UnhookWindowsHookEx.argtypes = (wintypes.HANDLE,)
        self._user32.keybd_event.argtypes = (wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t)
        self._user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        self._user32.GetAsyncKeyState.restype = ctypes.c_short
        self._hook = self._user32.SetWindowsHookExW(14, self._callback, None, 0)

    @property
    def available(self) -> bool:
        return bool(self._hook)

    def close(self) -> None:
        if self._hook:
            self._user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def _modifiers(self) -> frozenset[str]:
        down = lambda key: bool(self._user32.GetAsyncKeyState(key) & 0x8000)
        return frozenset(name for name, keys in (
            ("win", (0x5B, 0x5C)), ("alt", (0x12,)), ("ctrl", (0x11,)),
            ("shift", (0x10,)),
        ) if any(down(key) for key in keys))

    def _handle(self, code: int, message: int, data: int) -> int:
        if code >= 0:
            info = ctypes.cast(data, ctypes.POINTER(_MouseInfo)).contents
            if not info.flags & 1:
                buttons = {0x201: ("left", True), 0x202: ("left", False),
                           0x204: ("right", True), 0x205: ("right", False),
                           0x207: ("middle", True), 0x208: ("middle", False),
                           0x20B: ("side", True), 0x20C: ("side", False)}
                event = buttons.get(message)
                if event and event[0] == "side":
                    event = (f"side{info.mouseData >> 16}", event[1])
                if self._active:
                    if event and not event[1] and event[0] == self._button:
                        self._active = False
                        self.drag_event.emit("finish", info.pt.x, info.pt.y)
                        return 1
                    if message == 0x200:
                        self.drag_event.emit("move", info.pt.x, info.pt.y)
                elif event and event[1] and self.binding.enabled and self.binding.modifiers:
                    button = "side" if event[0].startswith("side") else event[0]
                    if button == self.binding.button and self._modifiers() == self.binding.modifiers and self._available():
                        if self.binding.modifiers & {"win", "alt"}:
                            self._user32.keybd_event(0xE8, 0, 0, 0)
                            self._user32.keybd_event(0xE8, 0, 2, 0)
                        self._active = True
                        self._button = event[0]
                        self.drag_event.emit("begin", info.pt.x, info.pt.y)
                        return 1
        return self._user32.CallNextHookEx(self._hook, code, message, data)

