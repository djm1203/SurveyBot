"""
recorder.py — Standalone keystroke timing profiler.

Each teammate runs this once. The resulting JSON profile is loaded by the
bot at runtime to replay realistic inter-key timings that match a real human.

Usage:
    python recorder.py
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev

from pynput import keyboard

from config import SAMPLE_TEXT

KEYSTROKES_DIR = Path(__file__).parent / "keystrokes"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _participant_path(number: str) -> Path:
    padded = number.zfill(2)
    return KEYSTROKES_DIR / f"person_{padded}.json"


def _prompt_participant_number() -> Path:
    """Ask for a participant number; handle already-taken files."""
    while True:
        raw = input("Enter your participant number (e.g. 1, 2, 3 ...): ").strip()
        if not raw.isdigit():
            print("  Please enter a number.")
            continue

        path = _participant_path(raw)
        if path.exists():
            ans = input(
                f"  {path.name} already exists. Overwrite? [y/N] "
            ).strip().lower()
            if ans == "y":
                return path
            # else loop — ask for a different number
        else:
            return path


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

class KeystrokeRecorder:
    """Listens to keyboard events and computes dwell + flight times."""

    def __init__(self) -> None:
        self._press_times: dict[str, float] = {}   # key -> keydown time (ms)
        self._last_release_time: float | None = None
        self._events: list[dict] = []              # raw events in order
        self._done = False

    # -- pynput callbacks ---------------------------------------------------

    def on_press(self, key: keyboard.Key | keyboard.KeyCode) -> bool | None:
        if self._done:
            return False  # stop listener

        # Escape or Enter stops recording
        if key == keyboard.Key.esc or key == keyboard.Key.enter:
            self._done = True
            return False

        key_name = _key_name(key)
        now = _now_ms()
        self._press_times[key_name] = now
        return None  # keep listening

    def on_release(self, key: keyboard.Key | keyboard.KeyCode) -> bool | None:
        if self._done:
            return False

        key_name = _key_name(key)
        now = _now_ms()

        press_time = self._press_times.pop(key_name, None)
        dwell_ms = (now - press_time) if press_time is not None else 0.0

        flight_ms = (
            (press_time - self._last_release_time)
            if (press_time is not None and self._last_release_time is not None)
            else 0.0
        )
        # flight can technically be negative if keys overlap; clamp to 0
        flight_ms = max(flight_ms, 0.0)

        self._last_release_time = now

        self._events.append({
            "key": key_name,
            "dwell_ms": round(dwell_ms, 2),
            "flight_ms": round(flight_ms, 2),
        })

        # Live counter so the user knows recording is active
        count = len(self._events)
        print(f"\r  Keystrokes recorded: {count}   ", end="", flush=True)

        return None

    # -- Result assembly ----------------------------------------------------

    def keystrokes(self) -> list[dict]:
        return self._events

    def profile(self) -> dict:
        dwells = [e["dwell_ms"] for e in self._events if e["dwell_ms"] > 0]
        flights = [e["flight_ms"] for e in self._events if e["flight_ms"] > 0]

        def _safe_mean(lst: list[float]) -> float:
            return round(mean(lst), 2) if lst else 0.0

        def _safe_std(lst: list[float]) -> float:
            return round(stdev(lst), 2) if len(lst) >= 2 else 0.0

        return {
            "mean_dwell": _safe_mean(dwells),
            "std_dwell": _safe_std(dwells),
            "mean_flight": _safe_mean(flights),
            "std_flight": _safe_std(flights),
            "total_keystrokes": len(self._events),
        }


def _key_name(key: keyboard.Key | keyboard.KeyCode) -> str:
    if isinstance(key, keyboard.KeyCode):
        return key.char if key.char else f"<keycode:{key.vk}>"
    return key.name  # e.g. "space", "enter", "backspace"


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _print_sample_text() -> None:
    width = 70
    border = "─" * width
    print(f"\n┌{border}┐")
    print(f"│{'  SAMPLE TEXT — type this exactly':^{width}}│")
    print(f"├{border}┤")
    # Word-wrap at width-4 so it fits inside the box
    words = SAMPLE_TEXT.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        if len(candidate) <= width - 4:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    for line in lines:
        print(f"│  {line:<{width - 2}}│")
    print(f"└{border}┘\n")


def _countdown(seconds: int = 3) -> None:
    print("Starting in:", end="", flush=True)
    for i in range(seconds, 0, -1):
        print(f" {i}", end="", flush=True)
        time.sleep(1)
    print(" GO!\n")


def _print_summary(profile: dict, participant: str) -> None:
    print("\n" + "=" * 50)
    print(f"  Keystroke profile saved for {participant}")
    print("=" * 50)
    print(f"  Total keystrokes  : {profile['total_keystrokes']}")
    print(f"  Mean dwell time   : {profile['mean_dwell']:.1f} ms")
    print(f"  Std  dwell time   : {profile['std_dwell']:.1f} ms")
    print(f"  Mean flight time  : {profile['mean_flight']:.1f} ms")
    print(f"  Std  flight time  : {profile['std_flight']:.1f} ms")
    print("=" * 50 + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("\n=== SurveyBot Keystroke Recorder ===\n")

    # Ensure keystrokes/ exists
    KEYSTROKES_DIR.mkdir(parents=True, exist_ok=True)

    out_path = _prompt_participant_number()
    participant_id = out_path.stem  # e.g. "person_01"

    _print_sample_text()

    print("Type the text above as naturally as possible.")
    print("Press Enter or Escape when finished (typing is captured silently).\n")

    _countdown(3)

    recorder = KeystrokeRecorder()
    with keyboard.Listener(
        on_press=recorder.on_press,
        on_release=recorder.on_release,
    ) as listener:
        listener.join()

    keystrokes = recorder.keystrokes()
    if not keystrokes:
        print("No keystrokes recorded — exiting without saving.")
        sys.exit(0)

    profile = recorder.profile()

    payload = {
        "participant": participant_id,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "keystrokes": keystrokes,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"\nSaved to {out_path}")
    _print_summary(profile, participant_id)


if __name__ == "__main__":
    main()
