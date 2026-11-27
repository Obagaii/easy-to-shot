from dataclasses import dataclass

from PySide6.QtCore import QSettings


@dataclass(frozen=True, slots=True)
class QuickCaptureBinding:
    button: str = "left"
    modifiers: frozenset[str] = frozenset({"win"})
    enabled: bool = True


def load_quick_capture(settings: QSettings) -> QuickCaptureBinding:
    button = str(settings.value("quick_capture/button", "left"))
    if button not in {"left", "right", "middle", "side"}:
        button = "left"
    modifiers = frozenset(
        key for key in ("win", "alt", "ctrl")
        if settings.value(f"quick_capture/{key}", key == "win", type=bool)
    )
    return QuickCaptureBinding(
        button, modifiers, settings.value("quick_capture/enabled", True, type=bool)
    )


def save_quick_capture(settings: QSettings, binding: QuickCaptureBinding) -> None:
    settings.setValue("quick_capture/button", binding.button)
    settings.setValue("quick_capture/enabled", binding.enabled)
    for key in ("win", "alt", "ctrl"):
        settings.setValue(f"quick_capture/{key}", key in binding.modifiers)
    settings.sync()
