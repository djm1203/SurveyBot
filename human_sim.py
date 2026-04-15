"""
human_sim.py — Human behavioral simulation engine.

WHY THIS EXISTS
---------------
Modern bot detection doesn't just look at your browser fingerprint — it
watches HOW you interact: how fast you type, whether you pause to "read",
how long you hold each key.  A bot that types 200 characters in 0.4 seconds
with perfectly uniform spacing is trivially flagged.

This module has two jobs:
  1. KEYSTROKE REPLAY  — load a real human's recorded timing profile from
     keystrokes/person_XX.json (recorded by recorder.py) and replay those
     timings when typing.  Each character's inter-key delay is sampled from
     a Gaussian distribution fitted to that person's actual keypress data.

  2. BEHAVIORAL PACING — inject human-like pauses around clicks and page
     transitions using Gaussian-distributed delays drawn from the constants
     in config.py.

PROFILE LOADING
---------------
Call select_profile() once at the start of each bot run.  This picks a
random JSON file from keystrokes/ and stores its statistics module-wide.
All subsequent typing calls pull from that profile automatically.

If no profiles exist (no one has run recorder.py yet), the module falls
back to configurable default timing values.

PUBLIC FUNCTIONS (called by bot.py)
------------------------------------
    select_profile()                  → load a random profile for this run
    type_with_profile(page, locator, text) → type with that person's timing
    human_click(locator)              → click with a Gaussian pre-click pause
    reading_pause(page, n_questions)  → simulate reading before hitting Next
"""

import json
import logging
import random
from pathlib import Path

from config import TIMING

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level active profile
# Set once per run by select_profile().  None = use fallback defaults.
# ---------------------------------------------------------------------------
_active_profile: dict | None = None

# Directory where recorder.py saves JSON profiles
_KEYSTROKES_DIR = Path(__file__).parent / "keystrokes"

# Fallback timing (ms) when no profile is loaded.
# _FALLBACK_FLIGHT_STD must stay above 100 ms — behavioral biometric detectors
# flag inter-keystroke σ < 100 ms as a strong bot signal.
_FALLBACK_DWELL_MEAN  = 80
_FALLBACK_DWELL_STD   = 25
_FALLBACK_FLIGHT_MEAN = 130
_FALLBACK_FLIGHT_STD  = 100


# ---------------------------------------------------------------------------
# Profile management
# ---------------------------------------------------------------------------

def select_profile() -> str | None:
    """
    Pick a random keystroke JSON profile from keystrokes/ and store it
    as the active profile for this run.

    Returns the filename of the chosen profile, or None if no profiles exist.
    Call this once at the start of each SurveyBot run.
    """
    global _active_profile

    profiles = list(_KEYSTROKES_DIR.glob("person_*.json"))
    if not profiles:
        logger.warning(
            "[human_sim] No keystroke profiles found in keystrokes/ — "
            "falling back to default timing.  Run recorder.py to create profiles."
        )
        _active_profile = None
        return None

    chosen_path = random.choice(profiles)
    try:
        with open(chosen_path, encoding="utf-8") as f:
            data = json.load(f)
        _active_profile = data["profile"]
        logger.info(
            f"[human_sim] Loaded profile '{chosen_path.name}' — "
            f"mean flight: {_active_profile['mean_flight']:.0f}ms, "
            f"mean dwell: {_active_profile['mean_dwell']:.0f}ms"
        )
        return chosen_path.name
    except Exception as exc:
        logger.error(f"[human_sim] Failed to load profile {chosen_path.name}: {exc}")
        _active_profile = None
        return None


def get_active_profile_name() -> str:
    """Return a human-readable description of the currently loaded profile."""
    if _active_profile is None:
        return "fallback defaults"
    return (
        f"profile (dwell={_active_profile['mean_dwell']:.0f}ms, "
        f"flight={_active_profile['mean_flight']:.0f}ms)"
    )


# ---------------------------------------------------------------------------
# Typing
# ---------------------------------------------------------------------------

def type_with_profile(page, locator, text: str) -> None:
    """
    Type `text` into a focused element using the active profile's timing.

    Each character gets an independently sampled inter-keystroke delay
    (flight time) drawn from Gauss(mean_flight, std_flight).  This produces
    the natural rhythm variation that separates human typing from bots.

    Falls back to random uniform timing if no profile is loaded.

    Parameters
    ----------
    page    : Playwright Page — used for keyboard API and wait calls
    locator : Playwright Locator — the input element to type into
    text    : The string to type
    """
    locator.click()  # Focus the element before typing

    for char in text:
        flight_ms = _sample_flight_ms()

        # page.keyboard.type fires: keydown → keypress → input → keyup
        # This is exactly what a real browser sees from a physical keypress.
        # We do NOT use locator.fill() because that skips keyboard events
        # entirely and is a strong bot signal.
        page.keyboard.type(char)

        # Inter-keystroke pause (flight time = gap between keys)
        if flight_ms > 0:
            page.wait_for_timeout(int(flight_ms))


# ---------------------------------------------------------------------------
# Click timing
# ---------------------------------------------------------------------------

def human_click(locator) -> None:
    """
    Click a Playwright locator with a human-like pre-click pause.

    The pause simulates the brief moment between deciding to click and
    actually clicking — real users don't click instantaneously.

    Uses mouse.py's bezier_click if available for curved mouse movement.
    Falls back to a simple .click() preceded by a Gaussian delay.

    Parameters
    ----------
    locator : Playwright Locator — the element to click
    """
    # Short pause before the click (decision time + hand movement)
    pre_click_ms = max(
        50,
        int(random.gauss(
            TIMING["click_mean"] * 1000,
            TIMING["click_std"]  * 1000,
        ))
    )

    # We can't call page.wait_for_timeout without the page reference here,
    # so we use the locator's page property if available
    try:
        locator.page.wait_for_timeout(pre_click_ms)
    except AttributeError:
        # Some Playwright versions don't expose .page on a locator directly
        import time
        time.sleep(pre_click_ms / 1000)

    # Attempt Bezier curve movement for more natural mouse path
    try:
        from mouse import bezier_click
        bezier_click(locator.page, locator)
    except Exception:
        locator.click()


# ---------------------------------------------------------------------------
# Reading / thinking pauses
# ---------------------------------------------------------------------------

def reading_pause(page, n_questions: int = 1) -> None:
    """
    Pause to simulate a human reading the page before clicking Next.

    The pause scales with the number of questions on the page — a page with
    5 questions takes longer to "read" than a page with 1.  A small random
    Gaussian jitter is added so the timing is never perfectly predictable.

    Parameters
    ----------
    page        : Playwright Page — used for wait calls
    n_questions : Number of visible questions on the current page.
                  Defaults to 1 if caller doesn't know the count.
    """
    mean_ms = (
        TIMING["read_per_question_mean"]
        * n_questions
        * 1000
    )
    std_ms = (
        TIMING["read_per_question_std"]
        * n_questions
        * 1000
    )
    pause_ms = max(500, int(random.gauss(mean_ms, std_ms)))
    logger.debug(f"[human_sim] Reading pause: {pause_ms}ms ({n_questions} question(s))")
    page.wait_for_timeout(pause_ms)


def short_action_pause(page) -> None:
    """
    Small pause between individual answer interactions (e.g. between
    selecting one checkbox and moving to the next question).

    Drawn uniformly from [min_action_delay, max_action_delay] in config.py.
    """
    ms = random.uniform(
        TIMING["min_action_delay"] * 1000,
        TIMING["max_action_delay"] * 1000,
    )
    page.wait_for_timeout(int(ms))


def simulate_page_scroll(page) -> None:
    """
    Fire realistic scroll events to simulate a user reading the page.

    Real users scroll to see the full question set before answering.
    Systems that collect scroll telemetry (DataDome, reCAPTCHA v3) treat
    zero scroll events as a bot signal.

    Behaviour:
      • 2–6 wheel events per call
      • 78 % scroll down, 22 % scroll up (natural reading pattern)
      • Delta drawn from Uniform(60, 300) px — matches typical trackpad/scroll wheel
      • Gaussian delay between events centred at 380 ms
      • Mouse position randomised across the viewport width on each event
    """
    n_scrolls = random.randint(2, 6)
    for _ in range(n_scrolls):
        direction = 1 if random.random() < 0.78 else -1
        delta = random.randint(60, 300) * direction
        # page.mouse.wheel takes (delta_x, delta_y) — move cursor slightly
        # each time so the page doesn't snap the scroll anchor
        try:
            x = random.randint(200, 900)
            y = random.randint(150, 500)
            page.mouse.move(x, y)
            page.mouse.wheel(0, delta)
        except Exception:
            pass
        page.wait_for_timeout(max(80, int(random.gauss(380, 100))))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sample_flight_ms() -> float:
    """
    Sample an inter-keystroke delay (flight time) from the active profile.

    Flight time = time between releasing one key and pressing the next.
    Uses the profile's Gaussian parameters if a profile is loaded,
    otherwise uses hardcoded fallback values.

    Returns a non-negative float in milliseconds.
    """
    if _active_profile:
        mean = _active_profile["mean_flight"]
        std  = _active_profile["std_flight"]
    else:
        mean = _FALLBACK_FLIGHT_MEAN
        std  = _FALLBACK_FLIGHT_STD

    # Clamp to a sensible range — never negative, never so long it looks frozen
    return max(20.0, min(600.0, random.gauss(mean, std)))
