import ctypes
import sys

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

from e2s.platform.windows.hotkeys import GlobalHotkey, HotkeyError, HotkeyState


@pytest.mark.parametrize(
    ("shortcut", "error"),
    [
        ("F8", HotkeyError.INVALID),
        ("Ctrl+A, Ctrl+B", HotkeyError.INVALID),
        ("Ctrl+F12", HotkeyError.RESERVED),
        ("Meta+S", HotkeyError.RESERVED),
        ("Alt+Tab", HotkeyError.RESERVED),
    ],
)
def test_invalid_or_reserved_shortcut_is_rejected(
    app: QApplication, shortcut: str, error: HotkeyError
) -> None:
    hotkey = GlobalHotkey(app, lambda: None)
    try:
        assert hotkey.replace(QKeySequence(shortcut)) == HotkeyState(None, error)
    finally:
        hotkey.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Win32 hotkey registration")
def test_native_hotkey_replacement_preserves_existing_registration_on_conflict(
    app: QApplication,
) -> None:
    user32 = ctypes.windll.user32
    activations = []
    hotkey = GlobalHotkey(app, lambda: activations.append(True))
    blocker_id = 0x4533
    assert user32.RegisterHotKey(None, blocker_id, 0x0006, 0x87)  # Ctrl+Shift+F24
    try:
        assert hotkey.replace(QKeySequence("Ctrl+Shift+F24")) == HotkeyState(
            None, HotkeyError.CONFLICT
        )
        assert hotkey.replace(QKeySequence("Ctrl+Shift+F23")) == HotkeyState("Ctrl+Shift+F23")
        assert hotkey.replace(QKeySequence("Ctrl+Shift+F24")) == HotkeyState(
            "Ctrl+Shift+F23", HotkeyError.CONFLICT
        )
        thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        assert user32.PostThreadMessageW(thread_id, 0x0312, hotkey._registration_id, 0)
        loop = QEventLoop()
        QTimer.singleShot(30, loop.quit)
        loop.exec()
        assert activations == [True]

        assert hotkey.replace(QKeySequence("Ctrl+Shift+F22")) == HotkeyState("Ctrl+Shift+F22")
        assert user32.RegisterHotKey(None, blocker_id + 1, 0x0006, 0x86)  # Previous shortcut
        assert user32.UnregisterHotKey(None, blocker_id + 1)
    finally:
        user32.UnregisterHotKey(None, blocker_id)
        hotkey.close()
