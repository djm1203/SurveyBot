"""
warm_profile.py — Pre-warm a browser profile for reCAPTCHA v3 evasion.

WHY THIS EXISTS
---------------
reCAPTCHA v3 assigns low scores (0.1–0.3) to fresh browser contexts that
have zero cookies, zero browsing history, and no Google session state.  Its
ML model treats a clean-slate context as a strong bot signal regardless of
how good the mouse movement or keystroke timing looks.

A "warmed" profile has:
  • Google NID / CONSENT cookies (from visiting google.com)
  • Referral and navigation history spread across multiple domains
  • Realistic cache headers and service-worker entries

When the bot loads this saved state at run time, reCAPTCHA v3 sees a session
that looks like it belongs to an established user → scores rise to 0.6–0.9.

USAGE
-----
Run once before your first bot run (or re-run weekly to refresh cookies):

    python warm_profile.py

The script saves a file to  profiles/warmed_profile_YYYYMMDD_HHMMSS.json
main.py picks it up automatically on the next bot run.

The browser window opens so you can observe the warming sequence.  Do not
interact with it — just let it finish and close automatically.
"""

import logging
import random
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output directory
# ---------------------------------------------------------------------------
_PROFILES_DIR = Path(__file__).parent / "profiles"

# ---------------------------------------------------------------------------
# Warm-up visit sequence
#
# Each entry is a tuple of:
#   (url, min_dwell_s, max_dwell_s, description)
#
# The sites are chosen to:
#   • Get Google NID / CONSENT cookies without requiring a login
#   • Build up realistic referral chains across unrelated domains
#   • Simulate a normal mid-day browsing session
# ---------------------------------------------------------------------------
_VISIT_SEQUENCE = [
    # Google homepage — establishes NID, CONSENT, 1P_JAR cookies
    ("https://www.google.com",           5, 10, "Google homepage"),
    # Simple Google search (no login required, sets search-session cookies)
    ("https://www.google.com/search?q=weather+forecast+today", 6, 12, "Google search"),
    # Wikipedia — trusted referral, no tracking
    ("https://en.wikipedia.org/wiki/Main_Page",                 8, 18, "Wikipedia"),
    # News site — common in mid-day browsing patterns
    ("https://apnews.com",                                       7, 15, "AP News"),
    # Return to Google — reinforces the session cookie
    ("https://www.google.com",                                   4,  8, "Google (return)"),
    # YouTube — sets more Google cookies (PREF, VISITOR_INFO1_LIVE, etc.)
    ("https://www.youtube.com",                                  6, 14, "YouTube"),
    # One more general-interest site to pad history
    ("https://www.bbc.com",                                      5, 12, "BBC"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _human_scroll(page, n: int = 3) -> None:
    """Fire n realistic scroll events on the current page."""
    for _ in range(n):
        delta = random.randint(80, 350) * (1 if random.random() < 0.8 else -1)
        try:
            page.mouse.wheel(0, delta)
        except Exception:
            pass
        time.sleep(random.uniform(0.3, 0.9))


def _human_move(page) -> None:
    """Move the mouse to a few random positions to generate telemetry."""
    for _ in range(random.randint(3, 7)):
        x = random.randint(100, 1100)
        y = random.randint(80,  650)
        try:
            page.mouse.move(x, y)
        except Exception:
            pass
        time.sleep(random.uniform(0.05, 0.2))


# ---------------------------------------------------------------------------
# Core warm-up loop
# ---------------------------------------------------------------------------

def warm(headless: bool = False) -> str:
    """
    Launch the browser, visit the warm-up sequence, and save the profile.

    Parameters
    ----------
    headless : bool
        False (default) — visible browser so you can verify the sequence.
        True — run headless (useful in CI / scheduled warming).

    Returns
    -------
    str
        Absolute path to the saved profile JSON.
    """
    _PROFILES_DIR.mkdir(exist_ok=True)

    # Try Camoufox first; fall back to plain Playwright Firefox
    try:
        return _warm_with_camoufox(headless)
    except Exception as exc:
        logger.warning(f"[warm] Camoufox unavailable ({exc}), falling back to Playwright")
        return _warm_with_playwright(headless)


def _run_sequence(page) -> None:
    """Visit every site in _VISIT_SEQUENCE with human-like behaviour."""
    for url, min_s, max_s, label in _VISIT_SEQUENCE:
        logger.info(f"[warm] Visiting: {label} — {url}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        except Exception as exc:
            logger.warning(f"[warm] Navigation warning for {label}: {exc}")

        # Simulate reading: scroll + random mouse movement
        _human_scroll(page, n=random.randint(2, 5))
        _human_move(page)

        dwell = random.uniform(min_s, max_s)
        logger.info(f"[warm] Dwelling {dwell:.1f}s on {label}")
        time.sleep(dwell)


def _save_state(context, label: str) -> str:
    """Save context storage state and return the file path."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _PROFILES_DIR / f"warmed_profile_{ts}.json"
    context.storage_state(path=str(path))
    logger.info(f"[warm] Profile saved → {path}")
    return str(path)


def _warm_with_camoufox(headless: bool) -> str:
    from camoufox.sync_api import Camoufox  # noqa: PLC0415

    logger.info("[warm] Launching Camoufox for profile warming")
    with Camoufox(headless=headless, os="windows", locale="en-US") as browser:
        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="America/Chicago",
        )
        page = context.new_page()
        _run_sequence(page)
        return _save_state(context, "camoufox")


def _warm_with_playwright(headless: bool) -> str:
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    logger.info("[warm] Launching Playwright Firefox for profile warming")
    with sync_playwright() as pw:
        browser = pw.firefox.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="America/Chicago",
        )
        page = context.new_page()
        _run_sequence(page)
        path = _save_state(context, "playwright")
        browser.close()
        return path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Pre-warm a browser profile for reCAPTCHA v3 evasion."
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless mode (default: visible browser)",
    )
    args = parser.parse_args()

    width = 60
    print("\n" + "═" * width)
    print("  SurveyBot — Profile Warmer".center(width))
    print("═" * width)
    print(
        "\n  This script visits several websites to build up browser\n"
        "  history and Google cookies.  Do not interact with the\n"
        "  browser window — let it run to completion.\n"
    )

    try:
        saved = warm(headless=args.headless)
        print(f"\n  Profile saved to:\n  {saved}\n")
        print("  Run  python main.py  to use it.\n")
    except KeyboardInterrupt:
        print("\n  Interrupted — no profile saved.\n")
        sys.exit(1)
    except Exception as exc:
        logger.error(f"Profile warming failed: {exc}", exc_info=True)
        sys.exit(1)
