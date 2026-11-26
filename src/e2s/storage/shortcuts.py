import json
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths
from PySide6.QtGui import QKeySequence


def shortcut_settings(root: Path | None = None) -> QSettings:
    if root is None:
        root = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
    return QSettings(str(root / "workbench.ini"), QSettings.Format.IniFormat)


def load_shortcuts(settings: QSettings, key: str, defaults: tuple[str, ...]) -> tuple[str, ...]:
    raw = settings.value(f"shortcuts/{key}")
    if raw is None:
        return defaults
    try:
        values = json.loads(str(raw))
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            return defaults
        return tuple(values)
    except (TypeError, ValueError):
        return defaults


def save_shortcuts(settings: QSettings, key: str, values: tuple[str, ...]) -> None:
    settings.setValue(f"shortcuts/{key}", json.dumps(values, ensure_ascii=False))
    settings.sync()


def canonical_shortcut(value: str) -> str:
    sequence = QKeySequence(value, QKeySequence.SequenceFormat.PortableText)
    return sequence.toString(QKeySequence.SequenceFormat.PortableText)
