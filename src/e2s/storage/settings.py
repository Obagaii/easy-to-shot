"""Settings validation and atomic persistence."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

DEFAULT_HOTKEY = "Ctrl+Shift+F8"
DEFAULT_HISTORY_LIMIT = 200
MIN_HISTORY_LIMIT = 1
MAX_HISTORY_LIMIT = 1000
SETTINGS_FILENAME = "settings.json"

_MODIFIER_KEYS = frozenset({"ctrl", "shift", "alt"})
_NAMED_KEYS = frozenset(
    {
        "space",
        "enter",
        "esc",
        "tab",
        "backspace",
        "delete",
        "insert",
        "home",
        "end",
        "pageup",
        "pagedown",
        "up",
        "down",
        "left",
        "right",
        "printscreen",
        "pause",
    }
)
_RESERVED_HOTKEYS = frozenset(
    {"alt+tab", "alt+shift+tab", "alt+esc", "alt+f4", "ctrl+esc", "ctrl+alt+delete"}
)


class SettingsStatus(StrEnum):
    """读取或写入设置后的稳定状态值。"""

    OK = "ok"
    MISSING = "missing"
    CORRUPT = "corrupt"
    INVALID = "invalid"
    WRITE_FAILED = "write_failed"


@dataclass(frozen=True)
class AppSettings:
    """设置草稿与已保存设置的统一结构，不可变以避免后台任务改写。"""

    hotkey: str = DEFAULT_HOTKEY
    output_directory: str = ""
    history_enabled: bool = True
    history_limit: int = DEFAULT_HISTORY_LIMIT


@dataclass(frozen=True)
class ValidationIssue:
    """单个字段的校验失败，error_code 供界面与桥接复用。"""

    field: str
    error_code: str
    message: str


@dataclass(frozen=True)
class LoadResult:
    """读取结果：设置值、状态与损坏诊断副本路径。"""

    settings: AppSettings
    status: SettingsStatus
    diagnostic_path: str = ""


def default_output_directory() -> str:
    """返回默认输出目录；空设置表示尚未指定，由调用方按需创建。"""
    return str(Path.home() / "Pictures" / "EasyToShot")


def _is_allowed_main_key(key: str) -> bool:
    if key.startswith("f") and key[1:].isdigit():
        return 1 <= int(key[1:]) <= 12
    if len(key) == 1 and (key.isalpha() or key.isdigit()):
        return True
    return key in _NAMED_KEYS


def _parse_hotkey(value: str) -> tuple[frozenset[str], str] | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parts = [part.strip().lower() for part in value.split("+")]
    if len(parts) < 2 or any(not part for part in parts):
        return None
    *modifier_parts, main_key = parts
    if not all(part in _MODIFIER_KEYS for part in modifier_parts):
        return None
    if len(set(modifier_parts)) != len(modifier_parts):
        return None
    if main_key in _MODIFIER_KEYS or not _is_allowed_main_key(main_key):
        return None
    normalized_main_key = "delete" if main_key == "del" else main_key
    return frozenset(modifier_parts), normalized_main_key


def _normalize_hotkey(modifiers: frozenset[str], main_key: str) -> str:
    ordered = [name for name in ("ctrl", "alt", "shift") if name in modifiers]
    return "+".join([*ordered, main_key])


def _is_directory_writable(directory: Path) -> bool:
    """用一次真实的临时文件写入探测可写性，避免 Windows ACL 下 os.access 误判。"""
    try:
        descriptor, name = tempfile.mkstemp(prefix=".e2s-check-", dir=directory)
    except OSError:
        return False
    os.close(descriptor)
    try:
        Path(name).unlink()
    except OSError:
        pass
    return True


def _hotkey_error_code(value: str) -> str | None:
    parsed = _parse_hotkey(value)
    if parsed is None:
        return "hotkey_invalid"
    modifiers, main_key = parsed
    if _normalize_hotkey(modifiers, main_key) in _RESERVED_HOTKEYS:
        return "hotkey_reserved"
    return None


def validate_settings(settings: AppSettings) -> tuple[ValidationIssue, ...]:
    """逐字段校验设置草稿，返回全部问题而不是在第一项中断。"""
    issues: list[ValidationIssue] = []

    hotkey_error = _hotkey_error_code(settings.hotkey)
    if hotkey_error:
        issues.append(ValidationIssue("hotkey", hotkey_error, "热键组合无效或已被系统保留。"))

    if not isinstance(settings.output_directory, str):
        issues.append(
            ValidationIssue("output_directory", "output_directory_invalid", "输出目录格式不正确。")
        )
    elif settings.output_directory:
        directory = Path(settings.output_directory)
        if not directory.is_dir():
            issues.append(
                ValidationIssue("output_directory", "output_directory_not_found", "输出目录不存在。")
            )
        elif not _is_directory_writable(directory):
            issues.append(
                ValidationIssue(
                    "output_directory", "output_directory_not_writable", "输出目录不可写。"
                )
            )

    if not isinstance(settings.history_enabled, bool):
        issues.append(
            ValidationIssue("history_enabled", "history_enabled_invalid", "历史开关必须是布尔值。")
        )

    limit = settings.history_limit
    if isinstance(limit, bool) or not isinstance(limit, int):
        issues.append(ValidationIssue("history_limit", "history_limit_invalid", "历史上限须为整数。"))
    elif not MIN_HISTORY_LIMIT <= limit <= MAX_HISTORY_LIMIT:
        issues.append(ValidationIssue("history_limit", "history_limit_out_of_range", "历史上限超范围。"))

    return tuple(issues)


def _settings_from_payload(payload: dict[str, Any]) -> AppSettings:
    hotkey = payload.get("hotkey", DEFAULT_HOTKEY)
    output_directory = payload.get("output_directory", "")
    history_enabled = payload.get("history_enabled", True)
    history_limit = payload.get("history_limit", DEFAULT_HISTORY_LIMIT)
    if not isinstance(hotkey, str) or not isinstance(output_directory, str):
        raise ValueError("设置字段类型不正确。")
    if not isinstance(history_enabled, bool):
        raise ValueError("设置字段类型不正确。")
    if isinstance(history_limit, bool) or not isinstance(history_limit, int):
        raise ValueError("设置字段类型不正确。")
    return AppSettings(
        hotkey=hotkey,
        output_directory=output_directory,
        history_enabled=history_enabled,
        history_limit=history_limit,
    )


def _to_payload(settings: AppSettings) -> dict[str, Any]:
    return {
        "hotkey": settings.hotkey,
        "output_directory": settings.output_directory,
        "history_enabled": settings.history_enabled,
        "history_limit": settings.history_limit,
    }


class SettingsStore:
    """读写 settings.json；写入使用同目录临时文件与 os.replace 原子发布。"""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._path = self._root / SETTINGS_FILENAME

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> LoadResult:
        if not self._path.exists():
            return LoadResult(AppSettings(), SettingsStatus.MISSING)
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return self._handle_corrupt()
        if not isinstance(payload, dict):
            return self._handle_corrupt()
        try:
            settings = _settings_from_payload(payload)
        except ValueError:
            return self._handle_corrupt()
        if validate_settings(settings):
            return LoadResult(AppSettings(), SettingsStatus.INVALID)
        return LoadResult(settings, SettingsStatus.OK)

    def save(self, settings: AppSettings) -> SettingsStatus:
        if validate_settings(settings):
            return SettingsStatus.INVALID
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError:
            return SettingsStatus.WRITE_FAILED
        content = json.dumps(_to_payload(settings), ensure_ascii=False, indent=2) + "\n"
        temp_path: Path | None = None
        try:
            descriptor, name = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=self._root)
            temp_path = Path(name)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self._path)
            return SettingsStatus.OK
        except OSError:
            return SettingsStatus.WRITE_FAILED
        finally:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def _handle_corrupt(self) -> LoadResult:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        diagnostic = self._root / f"settings.corrupt.{stamp}.json"
        try:
            shutil.copyfile(self._path, diagnostic)
            diagnostic_path = str(diagnostic)
        except OSError:
            diagnostic_path = ""
        return LoadResult(AppSettings(), SettingsStatus.CORRUPT, diagnostic_path)


class HotkeyStatus(StrEnum):
    """热键注册结果，错误取值与 A 的 HotkeyError 对齐。"""

    ACTIVE = "active"
    INVALID = "invalid"
    RESERVED = "reserved"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class HotkeyState:
    """实际生效的热键及其注册状态。"""

    active_hotkey: str | None
    status: HotkeyStatus
    error_code: str = ""


class HotkeyRegistrar(Protocol):
    """由 A 的平台适配层实现；设置服务不持有窗口对象、不调用 Qt API。"""

    def register(self, hotkey: str) -> HotkeyState:
        """注册新热键并返回实际状态。"""

    def restore(self, hotkey: str) -> HotkeyState:
        """写入失败时恢复原热键并返回实际状态。"""


class StaticHotkeyRegistrar:
    """平台层未接入前的本地模拟实现，用于服务独立运行与验证。"""

    def register(self, hotkey: str) -> HotkeyState:
        return HotkeyState(hotkey, HotkeyStatus.ACTIVE)

    def restore(self, hotkey: str) -> HotkeyState:
        return HotkeyState(hotkey, HotkeyStatus.ACTIVE)


class ApplyStatus(StrEnum):
    """设置应用结果；任一失败均回退到原设置。"""

    APPLIED = "applied"
    INVALID_DRAFT = "invalid_draft"
    HOTKEY_REJECTED = "hotkey_rejected"
    WRITE_FAILED = "write_failed"
    ROLLBACK_FAILED = "rollback_failed"


@dataclass(frozen=True)
class ApplyResult:
    """最终生效的设置、状态、实际热键与错误码。"""

    settings: AppSettings
    status: ApplyStatus
    active_hotkey: str | None
    error_code: str = ""


class SettingsService:
    """组合设置存储与热键注册，保证失败时原设置与实际热键一致。"""

    def __init__(
        self, store: SettingsStore, registrar: HotkeyRegistrar | None = None
    ) -> None:
        self._store = store
        self._registrar: HotkeyRegistrar = registrar or StaticHotkeyRegistrar()

    def load(self) -> LoadResult:
        return self._store.load()

    def apply(self, draft: AppSettings) -> ApplyResult:
        current = self._store.load().settings
        issues = validate_settings(draft)
        if issues:
            return ApplyResult(
                current, ApplyStatus.INVALID_DRAFT, current.hotkey, issues[0].error_code
            )

        registered: HotkeyState | None = None
        if draft.hotkey != current.hotkey:
            registered = self._registrar.register(draft.hotkey)
            if registered.status is not HotkeyStatus.ACTIVE:
                return ApplyResult(
                    current,
                    ApplyStatus.HOTKEY_REJECTED,
                    registered.active_hotkey,
                    registered.error_code or registered.status.value,
                )

        saved = self._store.save(draft)
        if saved is not SettingsStatus.OK:
            active = registered.active_hotkey if registered else current.hotkey
            if registered is not None:
                rollback = self._registrar.restore(current.hotkey)
                active = rollback.active_hotkey
                if rollback.status is not HotkeyStatus.ACTIVE:
                    return ApplyResult(
                        current,
                        ApplyStatus.ROLLBACK_FAILED,
                        active,
                        rollback.error_code or rollback.status.value,
                    )
            return ApplyResult(current, ApplyStatus.WRITE_FAILED, active, saved.value)

        return ApplyResult(
            draft,
            ApplyStatus.APPLIED,
            registered.active_hotkey if registered else current.hotkey,
        )


