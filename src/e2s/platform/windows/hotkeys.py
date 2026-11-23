import ctypes
import sys
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCore import QAbstractNativeEventFilter, QByteArray, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

_MOD_ALT = 0x0001
_MOD_CONTROL = 0x0002
_MOD_SHIFT = 0x0004
_MOD_NOREPEAT = 0x4000
_WM_HOTKEY = 0x0312
_ERROR_HOTKEY_ALREADY_REGISTERED = 1409
_HOTKEY_IDS = (0x4531, 0x4532)

_MODIFIERS = {
    Qt.KeyboardModifier.AltModifier: _MOD_ALT,
    Qt.KeyboardModifier.ControlModifier: _MOD_CONTROL,
    Qt.KeyboardModifier.ShiftModifier: _MOD_SHIFT,
}
_VIRTUAL_KEYS = {
    Qt.Key.Key_Backspace: 0x08,
    Qt.Key.Key_Tab: 0x09,
    Qt.Key.Key_Backtab: 0x09,
    Qt.Key.Key_Return: 0x0D,
    Qt.Key.Key_Escape: 0x1B,
    Qt.Key.Key_Space: 0x20,
    Qt.Key.Key_PageUp: 0x21,
    Qt.Key.Key_PageDown: 0x22,
    Qt.Key.Key_End: 0x23,
    Qt.Key.Key_Home: 0x24,
    Qt.Key.Key_Left: 0x25,
    Qt.Key.Key_Up: 0x26,
    Qt.Key.Key_Right: 0x27,
    Qt.Key.Key_Down: 0x28,
    Qt.Key.Key_Print: 0x2C,
    Qt.Key.Key_Insert: 0x2D,
    Qt.Key.Key_Delete: 0x2E,
}
_KEYPAD_KEYS = {
    Qt.Key.Key_Asterisk: 0x6A,
    Qt.Key.Key_Plus: 0x6B,
    Qt.Key.Key_Minus: 0x6D,
    Qt.Key.Key_Period: 0x6E,
    Qt.Key.Key_Comma: 0x6E,
    Qt.Key.Key_Slash: 0x6F,
}
_RESERVED = {
    (_MOD_ALT, 0x09),  # Alt+Tab
    (_MOD_ALT | _MOD_SHIFT, 0x09),
    (_MOD_ALT, 0x1B),  # Alt+Esc
    (_MOD_ALT | _MOD_SHIFT, 0x1B),
    (_MOD_ALT, 0x73),  # Alt+F4
    (_MOD_CONTROL, 0x1B),  # Ctrl+Esc
    (_MOD_CONTROL | _MOD_SHIFT, 0x1B),
    (_MOD_CONTROL | _MOD_ALT, 0x2E),  # Ctrl+Alt+Del
}


class HotkeyError(StrEnum):
    INVALID = "invalid"
    RESERVED = "reserved"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class HotkeyState:
    active: str | None
    error: HotkeyError | None = None


DEFAULT_HOTKEY = "Ctrl+Shift+F8"


def _decode(
    sequence: QKeySequence, scan_key: Callable[[str], int] | None
) -> tuple[int, int] | HotkeyError:
    if sequence.count() != 1:
        return HotkeyError.INVALID

    combination = sequence[0]
    qt_modifiers = combination.keyboardModifiers()
    if qt_modifiers & Qt.KeyboardModifier.MetaModifier:
        return HotkeyError.RESERVED
    supported = (
        Qt.KeyboardModifier.AltModifier
        | Qt.KeyboardModifier.ControlModifier
        | Qt.KeyboardModifier.ShiftModifier
    )
    keypad = Qt.KeyboardModifier.KeypadModifier
    if not qt_modifiers & supported or qt_modifiers & ~(supported | keypad):
        return HotkeyError.INVALID

    modifiers = sum(code for flag, code in _MODIFIERS.items() if qt_modifiers & flag)
    key = combination.key()
    if qt_modifiers & keypad:
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            virtual_key = 0x60 + int(key - Qt.Key.Key_0)
        else:
            virtual_key = _KEYPAD_KEYS.get(key, 0)
    elif Qt.Key.Key_A <= key <= Qt.Key.Key_Z or Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        virtual_key = int(key)
    elif Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
        virtual_key = 0x70 + int(key - Qt.Key.Key_F1)
    else:
        virtual_key = _VIRTUAL_KEYS.get(key, 0)

    if (
        not virtual_key and not qt_modifiers & keypad
        and scan_key is not None and 0x21 <= key <= 0xFFFF
    ):
        # Punctuation uses layout-specific VKs and may require Shift to type.
        encoded = scan_key(chr(key))
        shift_state = encoded >> 8
        if 0 <= shift_state <= 7:
            virtual_key = encoded & 0xFF
            modifiers |= (
                (_MOD_SHIFT if shift_state & 1 else 0)
                | (_MOD_CONTROL if shift_state & 2 else 0)
                | (_MOD_ALT if shift_state & 4 else 0)
            )
    if not virtual_key:
        return HotkeyError.INVALID
    if virtual_key == 0x7B or (modifiers, virtual_key) in _RESERVED:  # F12
        return HotkeyError.RESERVED
    return modifiers, virtual_key


class GlobalHotkey(QAbstractNativeEventFilter):
    def __init__(self, app: QApplication, on_trigger: Callable[[], None]) -> None:
        super().__init__()
        self._app = app
        self._on_trigger = on_trigger
        self._registration_id: int | None = None
        self._binding: tuple[int, int] | None = None
        self._state = HotkeyState(None)
        self._registered_ids: set[int] = set()
        self._user32 = None
        self._is_closed = False
        if sys.platform == "win32":
            self._user32 = ctypes.WinDLL("user32", use_last_error=True)
            self._user32.RegisterHotKey.argtypes = (
                wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT
            )
            self._user32.RegisterHotKey.restype = wintypes.BOOL
            self._user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
            self._user32.UnregisterHotKey.restype = wintypes.BOOL
            self._user32.VkKeyScanW.argtypes = (wintypes.WCHAR,)
            self._user32.VkKeyScanW.restype = ctypes.c_short
            app.installNativeEventFilter(self)

    @property
    def state(self) -> HotkeyState:
        return self._state

    def replace(self, sequence: QKeySequence) -> HotkeyState:
        """Register one shortcut on the GUI thread and retain the old one on failure."""
        scan_key = self._user32.VkKeyScanW if self._user32 is not None else None
        decoded = _decode(sequence, scan_key)
        if isinstance(decoded, HotkeyError):
            return self._set_error(decoded)
        if self._user32 is None or self._is_closed:
            return self._set_error(HotkeyError.UNAVAILABLE)

        shortcut = sequence.toString(QKeySequence.SequenceFormat.PortableText)
        if decoded == self._binding:
            self._state = HotkeyState(shortcut)
            return self._state

        replacement_id = next(
            (value for value in _HOTKEY_IDS if value not in self._registered_ids), None
        )
        if replacement_id is None:
            return self._set_error(HotkeyError.UNAVAILABLE)
        modifiers, virtual_key = decoded
        if not self._user32.RegisterHotKey(
            None, replacement_id, modifiers | _MOD_NOREPEAT, virtual_key
        ):
            error = (
                HotkeyError.CONFLICT
                if ctypes.get_last_error() == _ERROR_HOTKEY_ALREADY_REGISTERED
                else HotkeyError.UNAVAILABLE
            )
            return self._set_error(error)
        self._registered_ids.add(replacement_id)

        if self._registration_id is not None and not self._unregister(self._registration_id):
            self._unregister(replacement_id)
            return self._set_error(HotkeyError.UNAVAILABLE)
        self._registration_id = replacement_id
        self._binding = decoded
        self._state = HotkeyState(shortcut)
        return self._state

    def close(self) -> None:
        if self._is_closed:
            return
        self._is_closed = True
        if self._user32 is not None:
            self._app.removeNativeEventFilter(self)
            for registration_id in tuple(self._registered_ids):
                self._unregister(registration_id)
        self._registration_id = None
        self._binding = None
        self._state = HotkeyState(None)

    def nativeEventFilter(self, event_type: QByteArray, message: int) -> tuple[bool, int]:
        windows_events = (b'windows_dispatcher_MSG', b'windows_generic_MSG')
        if event_type in windows_events and self._registration_id is not None:
            native_message = wintypes.MSG.from_address(int(message))
            if (
                native_message.message == _WM_HOTKEY
                and native_message.wParam == self._registration_id
            ):
                self._on_trigger()
                return True, 0
        return False, 0

    def _set_error(self, error: HotkeyError) -> HotkeyState:
        self._state = HotkeyState(self._state.active, error)
        return self._state

    def _unregister(self, registration_id: int) -> bool:
        if self._user32.UnregisterHotKey(None, registration_id):
            self._registered_ids.discard(registration_id)
            return True
        return False
