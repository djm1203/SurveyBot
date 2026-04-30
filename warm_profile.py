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
# CORE sites are always visited — they establish Google NID, CONSENT, and
# YouTube VISITOR_INFO cookies which are what reCAPTCHA v3 actually checks.
#
# FILLER sites are sampled randomly each run (3 of 8) so each saved profile
# has a different browsing history.  This matters for two reasons:
#   1. Cookie staleness — profiles generated days apart have different NID
#      values, so the bot isn't cloning the same session across runs.
#   2. Cross-submission correlation — different cookie histories reduce the
#      chance that reCAPTCHA links multiple profiles to the same source.
# ---------------------------------------------------------------------------
_CORE_SITES = [
    # Google homepage — establishes NID, CONSENT, 1P_JAR cookies
    ("https://www.google.com",                                    5, 10, "Google homepage"),
    # Google search — sets search-session cookies
    ("https://www.google.com/search?q=baylor+university",         6, 12, "Google search"),
    # Return visit — reinforces the session cookie
    ("https://www.google.com",                                    4,  8, "Google (return)"),
    # YouTube — sets PREF, VISITOR_INFO1_LIVE, and more Google cookies
    ("https://www.youtube.com",                                   6, 14, "YouTube"),
]

_FILLER_POOL = [
    ("https://en.wikipedia.org/wiki/Main_Page",  8, 18, "Wikipedia"),
    ("https://apnews.com",                        7, 15, "AP News"),
    ("https://www.bbc.com",                       5, 12, "BBC"),
    ("https://stackoverflow.com",                 5, 11, "Stack Overflow"),
    ("https://github.com",                        4, 10, "GitHub"),
    ("https://www.reddit.com",                    5, 12, "Reddit"),
    ("https://www.weather.gov",                   4,  9, "Weather.gov"),
    ("https://www.espn.com",                      4, 10, "ESPN"),
]

# Build sequence fresh each run — 3 random fillers appended after core sites
_VISIT_SEQUENCE = _CORE_SITES + random.sample(_FILLER_POOL, k=3)


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


def _human_move(page, w: int = 1366, h: int = 768) -> None:
    """Move the mouse to a few random positions to generate telemetry."""
    for _ in range(random.randint(4, 9)):
        x = random.randint(80, max(100, w - 100))
        y = random.randint(60, max(80,  h - 80))
        try:
            page.mouse.move(x, y)
        except Exception:
            pass
        time.sleep(random.uniform(0.05, 0.25))


def _human_click_link(page, w: int = 1366, h: int = 768) -> None:
    """
    Click a visible anchor link on the current page, wait briefly, then
    navigate back.  This generates the back-forward navigation history that
    reCAPTCHA v3 values as evidence of a real browsing session.
    Skips if no safe link is found.
    """
    try:
        # Collect visible links that stay on the same domain (no external jumps)
        links = page.locator("a[href]").all()
        current_host = page.url.split("/")[2] if "//" in page.url else ""
        candidates = []
        for link in links[:30]:   # scan first 30 only — fast
            try:
                if not link.is_visible(timeout=200):
                    continue
                href = link.get_attribute("href") or ""
                # Only follow relative links or same-host links
                if href.startswith("/") or current_host in href:
                    box = link.bounding_box()
                    if box and 40 < box["x"] < w - 40 and 40 < box["y"] < h - 40:
                        candidates.append(link)
            except Exception:
                continue

        if not candidates:
            return

        target = random.choice(candidates[:10])
        target.click(timeout=3_000)
        time.sleep(random.uniform(2.5, 5.0))
        _human_scroll(page, n=random.randint(1, 3))
        _human_move(page, w, h)
        page.go_back(timeout=5_000, wait_until="domcontentloaded")
        time.sleep(random.uniform(1.0, 2.5))
    except Exception:
        pass   # navigation failures are non-fatal during warming


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


def _run_sequence(page, w: int = 1366, h: int = 768) -> None:
    """Visit every site in _VISIT_SEQUENCE with human-like behaviour."""
    for url, min_s, max_s, label in _VISIT_SEQUENCE:
        logger.info(f"[warm] Visiting: {label} — {url}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        except Exception as exc:
            logger.warning(f"[warm] Navigation warning for {label}: {exc}")

        # Simulate reading: scroll + mouse movement + occasional link click
        _human_scroll(page, n=random.randint(2, 5))
        _human_move(page, w, h)

        # 60% chance of clicking a link and coming back — builds navigation history
        if random.random() < 0.60:
            _human_click_link(page, w, h)

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
    from src.fingerprint import _pick_resolution  # noqa: PLC0415

    w, h = _pick_resolution()
    logger.info(f"[warm] Launching Camoufox for profile warming ({w}×{h})")
    with Camoufox(
        headless=headless,
        os="windows",
        locale="en-US",
        window=(w, h),
    ) as browser:
        context = browser.new_context(
            viewport={"width": w, "height": h},
            locale="en-US",
            timezone_id="America/Chicago",
        )
        page = context.new_page()
        _run_sequence(page, w, h)
        return _save_state(context, "camoufox")


def _warm_with_playwright(headless: bool) -> str:
    from playwright.sync_api import sync_playwright  # noqa: PLC0415
    from src.fingerprint import _pick_resolution  # noqa: PLC0415

    w, h = _pick_resolution()
    logger.info(f"[warm] Launching Playwright Firefox for profile warming ({w}×{h})")
    with sync_playwright() as pw:
        browser = pw.firefox.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": w, "height": h},
            locale="en-US",
            timezone_id="America/Chicago",
        )
        page = context.new_page()
        _run_sequence(page, w, h)
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
