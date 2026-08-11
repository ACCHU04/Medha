from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

WallMillis = Callable[[], int]

DEVICE_ID_LENGTH = 36  # str(uuid4())
_MS_WIDTH = 20
_COUNTER_WIDTH = 6
_HLC_LENGTH = _MS_WIDTH + 1 + _COUNTER_WIDTH + 1 + DEVICE_ID_LENGTH


@dataclass(frozen=True)
class HlcTimestamp:
    """Hybrid Logical Clock value with a total order (ms, counter, device_id)."""

    ms: int
    counter: int
    device_id: str

    @classmethod
    def from_string(cls, value: str) -> HlcTimestamp:
        ms_str, counter_str, device_id = value.split(":")
        return cls(int(ms_str), int(counter_str), device_id)

    def to_string(self) -> str:
        return (
            f"{self.ms:0{_MS_WIDTH}d}:"
            f"{self.counter:0{_COUNTER_WIDTH}d}:{self.device_id}"
        )

    @property
    def sortable(self) -> str:
        return self.to_string()

    def __lt__(self, other: HlcTimestamp) -> bool:
        return (self.ms, self.counter, self.device_id) < (
            other.ms,
            other.counter,
            other.device_id,
        )

    def __le__(self, other: HlcTimestamp) -> bool:
        return (self.ms, self.counter, self.device_id) <= (
            other.ms,
            other.counter,
            other.device_id,
        )


def new_hlc_value() -> str:
    """Fresh standalone HLC (no causal history) — used for legacy backfill/seed."""
    ms = int(time.time() * 1000)
    return HlcTimestamp(ms, 0, "0" * DEVICE_ID_LENGTH).to_string()


class HlcClock:
    """HLC clock per the original algorithm (Kulkarni et al., 2014)."""

    def __init__(
        self,
        device_id: str,
        wall_millis: WallMillis | None = None,
    ) -> None:
        if len(device_id) != DEVICE_ID_LENGTH:
            raise ValueError(
                f"device_id must be {DEVICE_ID_LENGTH} chars, got {len(device_id)}"
            )
        self._device_id = device_id
        self._wall = wall_millis or (lambda: int(time.time() * 1000))
        self._last: HlcTimestamp | None = None

    @property
    def device_id(self) -> str:
        return self._device_id

    @property
    def last(self) -> HlcTimestamp | None:
        return self._last

    def now(self, received: HlcTimestamp | None = None) -> str:
        wall_ms = self._wall()
        last = self._last
        last_ms = last.ms if last is not None else None

        if received is None:
            if last is None:
                now_ms, counter = wall_ms, 0
            else:
                now_ms = max(wall_ms, last_ms or 0)
                counter = 0 if now_ms > last_ms else last.counter + 1
        else:
            if last is None:
                now_ms = max(wall_ms, received.ms)
                counter = 0 if now_ms > received.ms else received.counter + 1
            else:
                now_ms = max(wall_ms, last_ms, received.ms)
                if now_ms == last_ms == received.ms:
                    counter = max(last.counter, received.counter) + 1
                elif now_ms == last_ms:
                    counter = last.counter + 1
                elif now_ms == received.ms:
                    counter = received.counter + 1
                else:
                    counter = 0

        ts = HlcTimestamp(now_ms, counter, self._device_id)
        self._last = ts
        return ts.to_string()


def hlc_cmp(a: str, b: str) -> int:
    """Compare two canonical HLC strings. Returns -1/0/1 in total order."""
    left = HlcTimestamp.from_string(a)
    right = HlcTimestamp.from_string(b)
    return (left > right) - (left < right)
