import pytest

from app.services.sync.hlc import (
    HlcClock,
    HlcTimestamp,
    hlc_cmp,
    new_hlc_value,
)


def _clock(device_id, wall=None):
    return HlcClock(device_id, wall)


class _FixedWall:
    def __init__(self, millis):
        self._millis = millis

    def __call__(self):
        return self._millis


def test_format_roundtrip():
    ts = HlcTimestamp(1234567890123, 42, "a" * 36)
    restored = HlcTimestamp.from_string(ts.to_string())
    assert restored == ts


def test_string_sort_matches_total_order():
    a = HlcTimestamp(10, 0, "b" * 36)
    b = HlcTimestamp(10, 1, "a" * 36)
    assert a < b
    assert a.to_string() < b.to_string()


def test_clock_bumps_counter_on_same_wall():
    clock = _clock("d" * 36, _FixedWall(5000))
    first = HlcTimestamp.from_string(clock.now())
    second = HlcTimestamp.from_string(clock.now())
    assert first.ms == second.ms == 5000
    assert second.counter == first.counter + 1


def test_clock_monotonic_with_advancing_wall():
    wall = _FixedWall(1000)
    clock = _clock("d" * 36, wall)
    t1 = HlcTimestamp.from_string(clock.now())
    wall._millis = 2000
    t2 = HlcTimestamp.from_string(clock.now())
    assert t2 > t1
    assert t2.counter == 0


def test_clock_receive_newer_jumps_and_bumps():
    clock = _clock("d" * 36, _FixedWall(1000))
    received = HlcTimestamp(3000, 5, "e" * 36)
    out = HlcTimestamp.from_string(clock.now(received))
    assert out.ms == 3000
    assert out.counter == 6


def test_total_order_across_devices():
    a = HlcTimestamp(100, 0, "a" * 36)
    b = HlcTimestamp(100, 0, "b" * 36)
    assert a < b
    assert hlc_cmp(a.to_string(), b.to_string()) == -1
    assert hlc_cmp(b.to_string(), a.to_string()) == 1
    assert hlc_cmp(a.to_string(), a.to_string()) == 0


def test_new_hlc_value_is_sortable():
    v = new_hlc_value()
    ts = HlcTimestamp.from_string(v)
    assert ts.counter == 0
    assert len(v) == 64


def test_clock_rejects_wrong_device_length():
    with pytest.raises(ValueError):
        HlcClock("short")
