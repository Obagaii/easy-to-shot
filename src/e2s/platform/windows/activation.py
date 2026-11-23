import ctypes
import sys


def allow_foreground_activation(process_id: int) -> None:
    """Pass the launching process's foreground permission on to the primary instance."""
    if sys.platform == "win32":
        ctypes.windll.user32.AllowSetForegroundWindow(ctypes.c_ulong(process_id))
