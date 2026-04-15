"""
fingerprint.py — Browser fingerprint generation.

Each call to generate_fingerprint() produces a new, internally consistent
fingerprint dict for one bot run. stealth.py consumes this dict directly.

Uses BrowserForge (bundled with camoufox) when available.
Falls back to a hand-crafted pool of realistic values if not.
"""

import logging
import random

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Static data pools (used by the manual fallback)
# ---------------------------------------------------------------------------

# (os_name, navigator.platform, selection_weight)
_OS_POOL = [
    ("windows", "Win32",        0.72),
    ("macos",   "MacIntel",     0.19),
    ("linux",   "Linux x86_64", 0.09),
]

# Common desktop screen resolutions — capped at 1440×900 so the browser
# window fits on a normal laptop screen and large-viewport slider issues
# don't surface.
_RESOLUTIONS = [
    (1366, 768),
    (1440, 900),
    (1280, 800),
    (1536, 864),
    (1600, 900),
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

    # BrowserForge fingerprint object — attribute access may vary by version
    try:
        w = fp.screen.width
        h = fp.screen.height
    except AttributeError:
        w, h = random.choice(_RESOLUTIONS)

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

    w, h = random.choice(_RESOLUTIONS)
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
