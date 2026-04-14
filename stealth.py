"""
stealth.py — Anti-detection browser launch.

Tries Camoufox (patched Firefox) first.
Falls back to standard Playwright Firefox + playwright-stealth if Camoufox
is not installed or fails to launch.

Usage:
    session = launch_browser(fingerprint)
    page    = session.page
    ...
    session.close()
"""

import logging
import random

logger = logging.getLogger(__name__)

_VIEWPORTS = [
    {"width": 1280, "height": 800},
    {"width": 1366, "height": 768},
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
]


class BrowserSession:
    """
    Wraps either a Camoufox or Playwright browser.
    Callers get a uniform interface regardless of which backend launched.

    Always call .close() when done, or use as a context manager:
        with launch_browser(fp) as session:
            page = session.page
    """

    def __init__(self) -> None:
        self._camoufox_cm = None   # Camoufox context manager (for __exit__)
        self._playwright = None    # sync_playwright instance (fallback mode)
        self._browser = None       # Playwright Browser object
        self._context = None       # Playwright BrowserContext (fallback mode)
        self.page = None
        self.mode: str = "unknown"

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "BrowserSession":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Launch
    # ------------------------------------------------------------------

    def launch(self, fingerprint: dict) -> "BrowserSession":
        try:
            self._launch_camoufox(fingerprint)
        except Exception as exc:
            # If Camoufox partially initialised before throwing, its internal
            # asyncio loop may still be running.  Call __exit__ to tear it
            # down cleanly before we attempt the Playwright fallback —
            # otherwise Playwright refuses to start ("inside asyncio loop").
            if self._camoufox_cm is not None:
                try:
                    self._camoufox_cm.__exit__(None, None, None)
                except Exception:
                    pass
                self._camoufox_cm = None

            logger.warning(
                f"[stealth] Camoufox unavailable ({exc}), "
                "falling back to Playwright + playwright-stealth"
            )
            self._launch_playwright_fallback(fingerprint)
        return self

    def _launch_camoufox(self, fingerprint: dict) -> None:
        from camoufox.sync_api import Camoufox  # noqa: PLC0415

        # Do NOT pass screen= as a plain dict — Camoufox forwards it to
        # BrowserForge's generator which expects a typed constraint object,
        # not a dict, and raises AttributeError: 'dict' has no 'is_set'.
        # Omitting it lets Camoufox pick a realistic screen size automatically
        # based on the os= parameter.
        self._camoufox_cm = Camoufox(
            headless=False,
            os=_platform_to_camoufox_os(fingerprint.get("platform", "Win32")),
            locale=fingerprint.get("locale", "en-US"),
        )
        browser = self._camoufox_cm.__enter__()
        self._browser = browser

        # Isolated context per run — defeats RelevantID duplicate detection.
        # We still honour the viewport from our fingerprint so the page layout
        # matches the screen size Camoufox reported.
        viewport = fingerprint.get("viewport", random.choice(_VIEWPORTS))
        context = browser.new_context(
            viewport={"width": viewport["width"], "height": viewport["height"]},
            locale=fingerprint.get("locale", "en-US"),
            timezone_id=fingerprint.get("timezone", "America/Chicago"),
        )
        self.page = context.new_page()
        self._context = context
        self.mode = "camoufox"
        logger.info("[stealth] Launched Camoufox browser")

    def _launch_playwright_fallback(self, fingerprint: dict) -> None:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415

        viewport = fingerprint.get("viewport", random.choice(_VIEWPORTS))
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.firefox.launch(headless=False)
        self._context = self._browser.new_context(
            viewport=viewport,
            user_agent=fingerprint.get("user_agent", ""),
            locale=fingerprint.get("locale", "en-US"),
            timezone_id=fingerprint.get("timezone", "America/Chicago"),
        )
        self.page = self._context.new_page()

        try:
            from playwright_stealth import stealth_sync  # noqa: PLC0415
            stealth_sync(self.page)
            self.mode = "playwright+stealth"
            logger.info("[stealth] Launched Playwright Firefox + playwright-stealth")
        except ImportError:
            self.mode = "playwright"
            logger.warning(
                "[stealth] playwright-stealth not installed — "
                "no extra patches applied"
            )

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    def close(self) -> None:
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._camoufox_cm is not None:
                self._camoufox_cm.__exit__(None, None, None)
            else:
                if self._browser:
                    self._browser.close()
                if self._playwright:
                    self._playwright.stop()
        except Exception as exc:
            logger.error(f"[stealth] Error during browser close: {exc}")


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def launch_browser(fingerprint: dict) -> BrowserSession:
    """Create, launch, and return a BrowserSession. Access the page via .page."""
    return BrowserSession().launch(fingerprint)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _platform_to_camoufox_os(platform: str) -> str:
    p = platform.lower()
    if "win" in p:
        return "windows"
    if "mac" in p or "darwin" in p:
        return "macos"
    return "linux"
