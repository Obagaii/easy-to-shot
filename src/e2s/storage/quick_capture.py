from dataclasses import dataclass

from PySide6.QtCore import QSettings


@dataclass(frozen=True, slots=True)
class QuickCaptureBinding:
    button: str = "left"
    modifiers: frozenset[str] = frozenset({"win"})
    enabled: bool = True


def load_quick_capture(settings: QSettings, action: str = "copy") -> QuickCaptureBinding:
    prefix = "quick_capture" if action == "copy" else f"quick_capture/{action}"
    default_button = {"copy": "left", "ocr": "right", "translate": "middle"}.get(action, "left")
    button = str(settings.value(f"{prefix}/button", default_button))
    if button not in {"left", "right", "middle", "side"}:
        button = default_button
    default_modifier = None if action in {"record", "barcode"} else ("ctrl" if action == "pin" else "win")
    modifiers = frozenset(
        key for key in ("win", "alt", "ctrl")
        if settings.value(f"{prefix}/{key}", key == default_modifier, type=bool)
    )
    return QuickCaptureBinding(
        button, modifiers, settings.value(f"{prefix}/enabled", action not in {"record", "barcode"}, type=bool)
    )


def save_quick_capture(
    settings: QSettings, binding: QuickCaptureBinding, action: str = "copy"
) -> None:
    prefix = "quick_capture" if action == "copy" else f"quick_capture/{action}"
    settings.setValue(f"{prefix}/button", binding.button)
    settings.setValue(f"{prefix}/enabled", binding.enabled)
    for key in ("win", "alt", "ctrl"):
        settings.setValue(f"{prefix}/{key}", key in binding.modifiers)
    settings.sync()
