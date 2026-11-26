from e2s.output.service import OutputSnapshot

CHANNELS = 4


def make_pixels(width_px: int, height_px: int, seed: int = 0) -> bytes:
    """Generate deterministic RGBA pixels with distinct boundary values."""

    base = bytes((channel + seed) % 256 for channel in range(CHANNELS))
    data = bytearray(base * (width_px * height_px))
    if data:
        data[0] = (data[0] + 17) % 256
        data[-1] = (data[-1] + 31) % 256
    return bytes(data)


def build_snapshot(
    operation_id: str,
    *,
    width_px: int = 2,
    height_px: int = 2,
    seed: int = 0,
    session_id: str = "s-001",
    revision: int = 1,
) -> OutputSnapshot:
    """Create an output snapshot from deterministic synthetic pixels."""

    return OutputSnapshot(
        operation_id=operation_id,
        session_id=session_id,
        revision=revision,
        width_px=width_px,
        height_px=height_px,
        pixels=make_pixels(width_px, height_px, seed),
        parameters={"format": "png", "channels": CHANNELS},
    )
