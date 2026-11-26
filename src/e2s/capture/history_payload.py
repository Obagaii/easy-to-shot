from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HistoryPayload:
    metadata: bytes
    assets: tuple[tuple[str, bytes], ...]
