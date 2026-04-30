"""
fingerprint.py — Browser fingerprint generation.

Each call to generate_fingerprint() produces a new, internally consistent
fingerprint dict for one bot run. stealth.py consumes this dict directly.

Uses BrowserForge (bundled with camoufox) when available.
Falls back to a hand-crafted pool of realistic values if not.
"""

import ctypes
import logging
import random

logger = logging.getLogger(__name__)


def _get_screen_bounds() -> tuple[int, int]:
    """
    Return (usable_width, usable_height) of the primary monitor.

    Subtracts 80px from height to leave room for the Windows taskbar and
    browser chrome (address bar + tabs) so the browser window never overflows
    the screen and the Next/Submit button stays reachable.

    Falls back to 1366×768 on non-Windows or if ctypes fails.
    """
    try:
        u32 = ctypes.windll.user32
        # SM_CXSCREEN=0, SM_CYSCREEN=1 — primary monitor logical pixel dimensions
        w = u32.GetSystemMetrics(0)
        h = u32.GetSystemMetrics(1) - 80
        if w > 800 and h > 500:   # sanity check
            return w, h
    except Exception:
        pass
    return 1366, 688   # conservative fallback

# ---------------------------------------------------------------------------
# Static data pools (used by the manual fallback)
# ---------------------------------------------------------------------------

# (os_name, navigator.platform, selection_weight)
_OS_POOL = [
    ("windows", "Win32",        0.72),
    ("macos",   "MacIntel",     0.19),
    ("linux",   "Linux x86_64", 0.09),
]

# Common desktop screen resolutions in ascending order.
# _pick_resolution() filters this list to only those that fit the actual screen.
_RESOLUTIONS = [
    (1280, 720),
    (1280, 800),
    (1366, 768),
    (1440, 900),
    (1536, 864),
    (1600, 900),
    (1920, 1080),
]

# (locale, IANA timezone)  — US-heavy to match Baylor's likely user base
_LOCALES = [
    ("en-US", "America/Chicago"),
    ("en-US", "America/New_York"),
    ("en-US", "America/Denver"),
    ("en-US", "America/Los_Angeles"),
    ("en-US", "America/Phoenix"),
]

# Firefox ESR + stable release range — keep plausible
_FF_VERSIONS = list(range(128, 139))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _pick_resolution() -> tuple[int, int]:
    """
    Choose a random resolution from the pool that fits the actual screen.

    Filters _RESOLUTIONS to those <= usable screen bounds, then picks
    randomly from the survivors.  If nothing fits (tiny screen / ctypes
    failure), falls back to the smallest entry in the pool.
    """
    max_w, max_h = _get_screen_bounds()
    fitting = [(w, h) for w, h in _RESOLUTIONS if w <= max_w and h <= max_h]
    if not fitting:
        fitting = [_RESOLUTIONS[0]]
    chosen = random.choice(fitting)
    logger.debug(
        f"[fingerprint] Screen bounds {max_w}×{max_h} → "
        f"picked resolution {chosen[0]}×{chosen[1]}"
    )
    return chosen


def generate_fingerprint() -> dict:
    """
    Generate a consistent, believable browser fingerprint for one bot run.

    Returns a dict with keys:
        user_agent, viewport, screen, locale, timezone, platform

    stealth.py passes this dict directly to Camoufox / Playwright new_context().
    """
    try:
        return _from_browserforge()
    except Exception as exc:
        logger.warning(
            f"[fingerprint] BrowserForge unavailable ({exc}), "
            "using manual fingerprint generation"
        )
        return _manual()


# ---------------------------------------------------------------------------
# BrowserForge path
# ---------------------------------------------------------------------------

def _from_browserforge() -> dict:
    from browserforge.fingerprints import FingerprintGenerator  # noqa: PLC0415

    # BrowserForge ≥ 1.0 accepts plain strings, not ("name", "version") tuples.
    # Pass "firefox" directly; omit device/locale as they vary by version.
    gen = FingerprintGenerator(
        browser="firefox",
        os=["windows", "macos"],
    )
    fp = gen.generate()

    # BrowserForge may return any screen size including 1920×1080 or larger.
    # Always override with a resolution that fits the actual screen — this
    # keeps the Camoufox window on screen and the Next button reachable.
    w, h = _pick_resolution()

    try:
        ua = fp.navigator.userAgent
    except AttributeError:
        ua = _build_ua("windows", random.choice(_FF_VERSIONS))

    try:
        platform = fp.navigator.platform
    except AttributeError:
        platform = "Win32"

    locale, timezone = random.choice(_LOCALES)

    return {
        "user_agent": ua,
        "viewport":   {"width": w, "height": h},
        "screen":     {"width": w, "height": h},
        "locale":     locale,
        "timezone":   timezone,
        "platform":   platform,
    }


# ---------------------------------------------------------------------------
# Manual fallback path
# ---------------------------------------------------------------------------

def _manual() -> dict:
    os_name, platform, _ = random.choices(
        [(o, p, w) for o, p, w in _OS_POOL],
        weights=[w for _, _, w in _OS_POOL],
    )[0]

    w, h = _pick_resolution()
    locale, timezone = random.choice(_LOCALES)
    ff_ver = random.choice(_FF_VERSIONS)
    ua = _build_ua(os_name, ff_ver)

    logger.debug(
        f"[fingerprint] Manual: {os_name} | {w}x{h} | "
        f"FF{ff_ver} | {locale} | {timezone}"
    )

    return {
        "user_agent": ua,
        "viewport":   {"width": w, "height": h},
        "screen":     {"width": w, "height": h},
        "locale":     locale,
        "timezone":   timezone,
        "platform":   platform,
    }


def _build_ua(os_name: str, ff_ver: int) -> str:
    if os_name == "windows":
        return (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:{ff_ver}.0) "
            f"Gecko/20100101 Firefox/{ff_ver}.0"
        )
    if os_name == "macos":
        return (
            f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:{ff_ver}.0) "
            f"Gecko/20100101 Firefox/{ff_ver}.0"
        )
    return (
        f"Mozilla/5.0 (X11; Linux x86_64; rv:{ff_ver}.0) "
        f"Gecko/20100101 Firefox/{ff_ver}.0"
    )
