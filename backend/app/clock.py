"""Demo clock.

Every timestamp in the product comes from here rather than from `datetime.now()`.
The clock keeps a virtual "business time" (naive, Moscow local) that runs faster
than wall time, so a follow-up rule written as "+15 minutes" can be demonstrated
in a few seconds without faking the rule itself.

    virtual_now = anchor_virtual + (real_now - anchor_real) * speed

Speed 1 is real time; 60 means one real second is one demo minute.
"""
from __future__ import annotations

import datetime as dt
import threading

ALLOWED_SPEEDS = (1, 10, 60, 100, 600)


class DemoClock:
    def __init__(self, speed: int = 60) -> None:
        self._lock = threading.RLock()
        self._speed = speed
        self._anchor_real = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        self._anchor_virtual = self._default_start()

    @staticmethod
    def _default_start() -> dt.datetime:
        """Start the demo on a plausible business morning (09:40 Moscow, today)."""
        today = dt.datetime.now().date()
        return dt.datetime.combine(today, dt.time(9, 40))

    # --- reading -----------------------------------------------------------

    @property
    def speed(self) -> int:
        with self._lock:
            return self._speed

    def now(self) -> dt.datetime:
        with self._lock:
            real_elapsed = (
                dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - self._anchor_real
            ).total_seconds()
            return self._anchor_virtual + dt.timedelta(seconds=real_elapsed * self._speed)

    def state(self) -> dict:
        return {
            "now": self.now().isoformat(timespec="seconds"),
            "speed": self.speed,
            "allowed_speeds": list(ALLOWED_SPEEDS),
        }

    # --- writing -----------------------------------------------------------

    def _reanchor(self, virtual: dt.datetime) -> None:
        self._anchor_virtual = virtual
        self._anchor_real = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

    def set_speed(self, speed: int) -> None:
        with self._lock:
            current = self.now()
            self._speed = max(1, int(speed))
            self._reanchor(current)

    def set_now(self, virtual: dt.datetime) -> None:
        with self._lock:
            self._reanchor(virtual)

    def jump(self, minutes: int) -> None:
        with self._lock:
            self._reanchor(self.now() + dt.timedelta(minutes=minutes))

    def restore(self, anchor_virtual: dt.datetime, anchor_real: dt.datetime, speed: int) -> None:
        with self._lock:
            self._anchor_virtual = anchor_virtual
            self._anchor_real = anchor_real
            self._speed = speed

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "anchor_virtual": self._anchor_virtual.isoformat(),
                "anchor_real": self._anchor_real.isoformat(),
                "speed": self._speed,
            }


clock = DemoClock()


def now() -> dt.datetime:
    return clock.now()


# --- business-hours helpers -------------------------------------------------


def parse_hhmm(value: str, fallback: tuple[int, int] = (0, 0)) -> dt.time:
    try:
        hh, mm = value.split(":")
        return dt.time(int(hh), int(mm))
    except (ValueError, AttributeError):
        return dt.time(*fallback)


def in_windows(moment: dt.datetime, windows: list[str]) -> bool:
    """`windows` looks like ["12:30-14:30", "17:00-20:00"]."""
    if not windows:
        return True
    t = moment.time()
    for window in windows:
        try:
            start_s, end_s = window.split("-")
        except ValueError:
            continue
        start, end = parse_hhmm(start_s), parse_hhmm(end_s)
        if start <= t <= end:
            return True
    return False


def next_window_start(moment: dt.datetime, windows: list[str]) -> dt.datetime:
    """Earliest moment at/after `moment` that falls inside one of the windows."""
    if not windows:
        return moment
    candidates: list[dt.datetime] = []
    for day_offset in range(0, 3):
        day = (moment + dt.timedelta(days=day_offset)).date()
        for window in windows:
            try:
                start_s, _ = window.split("-")
            except ValueError:
                continue
            candidate = dt.datetime.combine(day, parse_hhmm(start_s))
            if candidate >= moment:
                candidates.append(candidate)
    return min(candidates) if candidates else moment


def shift_into_windows(moment: dt.datetime, windows: list[str]) -> dt.datetime:
    return moment if in_windows(moment, windows) else next_window_start(moment, windows)
