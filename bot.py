"""
bot.py — Core Playwright survey navigation.

SurveyBot is a generic Qualtrics navigator.  It auto-detects question types
from the DOM and delegates answer generation to answers.py.
It deliberately knows nothing about stealth or fingerprinting — main.py
wires those together.

Usage (from main.py):
    bot = SurveyBot(page, {"survey_url": SURVEY_URL})
    bot.run()
"""

import logging
import random

try:
    # Playwright ≥ 1.20 exposes TargetClosedError directly
    from playwright._impl._errors import TargetClosedError as _TargetClosedError
except ImportError:
    # Fallback: treat any Exception as potentially a closed-page error
    _TargetClosedError = Exception  # type: ignore[assignment,misc]

import branching
from answers import (
    answer_text_field,
    classify_text_field,
    random_free_text,
    random_slider_value,
    select_choice,
)

logger = logging.getLogger(__name__)

# Qualtrics question container selectors — tried in order, first match wins
_QUESTION_SELECTORS = [
    "div.QuestionOuter",
    "div.question-container",
    "[data-qid]",
    ".question-block",
]

# Next / Submit button selectors — tried in order
_NEXT_SELECTORS = [
    "#NextButton",
    "#submitButton",
    "button[aria-label='Next']",
    "button[aria-label='Submit']",
    "button[type='submit']",
]


# ---------------------------------------------------------------------------
# Bot class
# ---------------------------------------------------------------------------

class SurveyBot:
    def __init__(self, page, config: dict) -> None:
        """
        Parameters
        ----------
        page   : playwright.sync_api.Page
        config : dict — must contain "survey_url" (or "SURVEY_URL")
        """
        self.page = page
        self.config = config
        # Persist generated name across questions so email matches
        self._first_name: str | None = None
        self._last_name:  str | None = None

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Navigate to the survey and fill every page until complete."""
        url = self.config.get("survey_url") or self.config.get("SURVEY_URL", "")
        logger.info(f"[bot] Navigating to {url}")
        self.page.goto(url)
        self.page.wait_for_load_state("load")
        # Qualtrics is a JS SPA — wait for the first interactive element to
        # render before entering the main loop.  Without this, the loop spins
        # many times in ~2 s while the page is still blank.
        try:
            self.page.wait_for_selector(
                "#NextButton, div.QuestionOuter, [data-qid]",
                timeout=15_000,
            )
        except Exception:
            pass  # Handled by is_survey_complete / next_page fallbacks

        page_num = 1
        try:
            while not branching.is_survey_complete(self.page):
                logger.info(f"[bot] ── Page {page_num} ──────────────────")
                self._wait_for_page_ready()
                self._initial_page_scroll()
                self.fill_page()
                branching.handle_new_visible_questions(self.page, self)
                self._reading_pause()
                self.next_page()
                page_num += 1

                if page_num > 50:
                    logger.error("[bot] Safety limit: 50 pages exceeded — aborting")
                    break
        except _TargetClosedError:
            # The page or browser was closed externally (survey platform detected the
            # bot, Camoufox crashed, or the user closed the window).  Exit cleanly
            # rather than hanging on subsequent Playwright calls that would each wait
            # for internal timeouts before raising.
            logger.warning("[bot] Page/browser closed mid-run — aborting cleanly")
            return

        logger.info("[bot] Survey complete")

    # ------------------------------------------------------------------
    # Page-level methods
    # ------------------------------------------------------------------

    def fill_page(self) -> None:
        """Detect and fill all visible questions on the current page."""
        containers = self._find_question_containers()
        logger.info(f"[bot] {len(containers)} question container(s) found")

        for container in containers:
            if not container.is_visible():
                continue
            try:
                self._dispatch_question(container)
            except Exception as exc:
                logger.error(f"[bot] Question handler error: {exc}")

    def next_page(self) -> None:
        """Click Next or Submit, then wait for navigation to settle."""
        timeout_ms = self.config.get("TIMING", {}).get("page_load_timeout_ms", 15_000)

        for selector in _NEXT_SELECTORS:
            try:
                loc = self.page.locator(selector)
                if loc.is_visible(timeout=1_000):
                    self._human_click(loc)
                    self.page.wait_for_load_state("load", timeout=timeout_ms)
                    self._wait_for_qualtrics_transition()
                    logger.info(f"[bot] Next via selector: {selector}")
                    return
            except Exception:
                continue

        # Role-based fallback
        for name in ("Next", "Submit"):
            try:
                btn = self.page.get_by_role("button", name=name)
                if btn.is_visible(timeout=500):
                    self._human_click(btn)
                    self.page.wait_for_load_state("load", timeout=timeout_ms)
                    self._wait_for_qualtrics_transition()
                    logger.info(f"[bot] Next via role button '{name}'")
                    return
            except Exception:
                continue

        logger.error("[bot] Could not find Next/Submit button")

    def is_complete(self) -> bool:
        return branching.is_survey_complete(self.page)

    def _wait_for_qualtrics_transition(self) -> None:
        """
        After clicking Next/Submit, Qualtrics sets class="LoadingPage" on
        #SkinContent while it transitions to the next page or thank-you screen.
        Waiting for that overlay to disappear ensures we don't try to fill
        the old form DOM that's still present during the animation.
        """
        try:
            overlay = self.page.locator("#SkinContent.LoadingPage")
            # Wait up to 3 s for the overlay to appear (it's fast)
            overlay.wait_for(state="visible", timeout=3_000)
            # Then wait up to 20 s for it to disappear (page fully loaded)
            overlay.wait_for(state="hidden", timeout=20_000)
            logger.debug("[bot] Qualtrics transition complete")
        except Exception:
            # Overlay didn't appear or already gone — nothing to wait for
            pass

    # ------------------------------------------------------------------
    # Question dispatcher
    # ------------------------------------------------------------------

    def _dispatch_question(self, container) -> None:
        """Inspect container children and call the right handler."""
        if self._has_visible(container, "input[type='text']"):
            self.handle_text_input(container)
        elif self._has_visible(container, "textarea"):
            self.handle_textarea(container)
        # Slider check must come BEFORE radio: Qualtrics slider containers
        # often contain .ChoiceStructure divs that would trigger a false
        # radio match if we checked radio first.
        elif (self._has_visible(container, "input[type='range']")
              or self._has_visible(container, "[role='slider']")
              or self._has_visible(container,
                  ".slider, .DragSlider, .QSlider, "
                  ".QQSL-sliderLine, .QQSL-sliderHandle, .QL-slider")):
            self.handle_slider(container)
        elif (self._has_visible(container, "input[type='radio']")
              or self._has_visible(container, ".radio, .RadioSelect, .ChoiceStructure")):
            self.handle_radio(container)
        elif self._has_visible(container, "input[type='checkbox']"):
            self.handle_checkbox(container)
        elif self._has_visible(container, "select"):
            self.handle_dropdown(container)
        else:
            logger.warning("[bot] Unknown question type — skipping container")

    # ------------------------------------------------------------------
    # Question handlers
    # ------------------------------------------------------------------

    def handle_text_input(self, container) -> None:
        label = self._question_label(container)
        field_type = classify_text_field(label)
        text = answer_text_field(
            field_type,
            first_name=self._first_name,
            last_name=self._last_name,
        )

        # Cache so email can stay consistent with the typed name
        if field_type == "first_name":
            self._first_name = text
        elif field_type == "last_name":
            self._last_name = text

        inputs = container.locator("input[type='text']")
        if inputs.count() == 0:
            inputs = container.locator("input")
        el = inputs.first
        el.click()
        el.fill("")  # Clear any content from a previous loop attempt
        self._type_text(el, text)
        logger.info(f"[bot] Text ({field_type}): {text}")

    def handle_textarea(self, container) -> None:
        label = self._question_label(container)
        field_type = classify_text_field(label)

        if field_type in ("first_name", "last_name", "email"):
            # Short-answer question that Qualtrics rendered as a <textarea>
            text = answer_text_field(
                field_type,
                first_name=self._first_name,
                last_name=self._last_name,
            )
            if field_type == "first_name":
                self._first_name = text
            elif field_type == "last_name":
                self._last_name = text
        else:
            # Genuine open-ended text area — draw from the diverse free-text
            # pool so no two submissions share the same response string.
            text = random_free_text()

        el = container.locator("textarea").first
        el.click()
        el.fill("")  # Clear any content from a previous loop attempt
        self._type_text(el, text)
        logger.info(f"[bot] Textarea ({field_type}): '{text[:40]}'")

    def handle_radio(self, container) -> None:
        options = self._choice_labels(container)
        if not options:
            logger.warning("[bot] Radio: no visible options found")
            return

        chosen = select_choice(options)
        if chosen is None:
            logger.warning("[bot] Radio: select_choice returned None — skipping")
            return

        for label_el in container.locator("label").all():
            try:
                if (label_el.is_visible(timeout=300)
                        and label_el.inner_text().strip() == chosen):
                    # Click the label via bezier_click so pointer events fire
                    # naturally — avoids the synthetic-interaction signal that
                    # check(force=True) produces by bypassing pointer events.
                    self._human_click(label_el)
                    logger.info(f"[bot] Radio: {chosen}")
                    return
            except Exception:
                continue

        logger.warning(f"[bot] Radio: could not find label for '{chosen}'")

    def handle_checkbox(self, container) -> None:
        options = self._choice_labels(container)
        if not options:
            return

        n = random.randint(1, min(3, len(options)))
        chosen = random.sample(options, n)

        for choice in chosen:
            for label_el in container.locator("label").all():
                try:
                    if (label_el.is_visible(timeout=300)
                            and label_el.inner_text().strip() == choice):
                        # Human click fires the full pointer-event sequence;
                        # no check(force=True) which would skip those events.
                        self._human_click(label_el)
                        self._short_pause()
                        break
                except Exception:
                    continue

        logger.info(f"[bot] Checkbox: {chosen}")

    def handle_slider(self, container) -> None:
        # Brief wait for Qualtrics JS to finish rendering a slider that just
        # appeared via display-logic branching.  Without this, the slider track
        # may have zero bounding-box dimensions or the role='slider' element may
        # not yet be in the DOM.
        self.page.wait_for_timeout(random.randint(300, 600))

        # ── Strategy 1: native <input type="range"> ──────────────────
        # Click a position on the track proportional to the chosen value so
        # the browser fires real pointer and change events — not DOM injection,
        # which skips the pointer-event sequence detectors look for.
        range_inputs = container.locator("input[type='range']")
        if range_inputs.count() > 0:
            el = range_inputs.first
            min_val = int(el.get_attribute("min") or 0)
            max_val = int(el.get_attribute("max") or 10)
            value = random_slider_value(min_val, max_val)
            try:
                el.scroll_into_view_if_needed()
                box = el.bounding_box()
                if box and box["width"] > 0:
                    frac = (value - min_val) / max(1, max_val - min_val)
                    frac = max(0.05, min(0.95, frac))
                    x = box["x"] + box["width"] * frac
                    y = box["y"] + box["height"] / 2
                    try:
                        from mouse import bezier_move
                        bezier_move(self.page, x, y)
                    except Exception:
                        self.page.mouse.move(x, y)
                    self.page.wait_for_timeout(60)
                    self.page.mouse.click(x, y)
                    logger.info(
                        f"[bot] Slider (range click at {frac:.2f}): "
                        f"{value} [{min_val}–{max_val}]"
                    )
                    return
            except Exception:
                pass
            # Fallback only if bounding_box unavailable
            el.evaluate(
                "(el, val) => {"
                "  el.value = val;"
                "  el.dispatchEvent(new Event('input',  {bubbles: true}));"
                "  el.dispatchEvent(new Event('change', {bubbles: true}));"
                "}",
                value,
            )
            logger.info(f"[bot] Slider (range fallback inject): {value} [{min_val}–{max_val}]")
            return

        # ── Strategy 2: Qualtrics custom slider — mouse click on track ─
        # Qualtrics requires a real mouse interaction (click or drag) to mark
        # the slider question as "answered" in its response engine.
        # Keyboard-only events after focus() move the handle visually but do
        # NOT trigger Qualtrics's internal response-tracking JS.
        #
        # We scroll the container into view first (large-viewport safety),
        # then click at a random position along the slider line/handle.
        try:
            container.scroll_into_view_if_needed()
            self.page.wait_for_timeout(200)
        except Exception:
            pass

        click_selectors = [
            "[role='slider']",
            ".QQSL-sliderLine", ".QQSL-sliderTrack", ".QQSL-sliderHandle",
            ".slider-track", ".slider", ".DragSlider", ".QSlider",
        ]
        for sel in click_selectors:
            try:
                loc = container.locator(sel)
                if loc.count() == 0 or not loc.first.is_visible(timeout=400):
                    continue
                loc.first.scroll_into_view_if_needed()
                box = loc.first.bounding_box()
                if not box:
                    continue
                frac = max(0.15, min(0.85, random.gauss(0.5, 0.15)))
                x = box["x"] + box["width"] * frac
                y = box["y"] + box["height"] / 2
                try:
                    from mouse import bezier_move
                    bezier_move(self.page, x, y)
                except Exception:
                    self.page.mouse.move(x, y)
                self.page.wait_for_timeout(80)
                self.page.mouse.click(x, y)
                logger.info(f"[bot] Slider (click at {frac:.2f} via {sel})")
                return
            except Exception:
                continue

        # ── Strategy 3: click in the lower portion of the question container ─
        # Last-resort: click in the bottom 30% of the container where the
        # slider track lives regardless of the specific selector.
        try:
            container.scroll_into_view_if_needed()
            box = container.bounding_box()
            if box:
                frac = max(0.15, min(0.85, random.gauss(0.5, 0.15)))
                x = box["x"] + box["width"] * frac
                y = box["y"] + box["height"] * 0.75
                try:
                    from mouse import bezier_move
                    bezier_move(self.page, x, y)
                except Exception:
                    self.page.mouse.move(x, y)
                self.page.wait_for_timeout(80)
                self.page.mouse.click(x, y)
                logger.info(f"[bot] Slider (container fallback click at {frac:.2f})")
                return
        except Exception:
            pass

        logger.warning("[bot] Slider: no usable slider element found")

    def handle_dropdown(self, container) -> None:
        sel_el = container.locator("select").first
        raw_options = sel_el.locator("option").all_text_contents()
        options = [
            o.strip() for o in raw_options
            if o.strip() and "select" not in o.lower()
        ]
        if not options:
            return

        chosen = select_choice(options)
        if chosen:
            sel_el.select_option(label=chosen)
            logger.info(f"[bot] Dropdown: {chosen}")

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _find_question_containers(self) -> list:
        for selector in _QUESTION_SELECTORS:
            try:
                loc = self.page.locator(selector)
                if loc.count() > 0:
                    return loc.all()
            except Exception:
                continue
        return []

    def _has_visible(self, container, selector: str) -> bool:
        try:
            loc = container.locator(selector)
            return loc.count() > 0 and loc.first.is_visible(timeout=300)
        except Exception:
            return False

    def _question_label(self, container) -> str:
        for sel in (".QuestionText", ".question-text", "legend", "h2", "h3", "p"):
            try:
                el = container.locator(sel).first
                if el.is_visible(timeout=300):
                    return el.inner_text().strip()
            except Exception:
                continue
        return ""

    def _choice_labels(self, container) -> list[str]:
        # Prefer labels with a 'for' attribute — these are always tied to
        # an input element and are never question-text labels.
        labels = []
        for el in container.locator("label[for]").all():
            try:
                if el.is_visible(timeout=300):
                    text = el.inner_text().strip()
                    if text:
                        labels.append(text)
            except Exception:
                continue

        if labels:
            return labels

        # Fallback: all visible labels (less precise — may include question text)
        for el in container.locator("label").all():
            try:
                if el.is_visible(timeout=300):
                    text = el.inner_text().strip()
                    if text:
                        labels.append(text)
            except Exception:
                continue
        return labels

    def _type_text(self, locator, text: str) -> None:
        """Type text with human-like delays. Falls back if human_sim not ready."""
        try:
            import human_sim
            human_sim.type_with_profile(self.page, locator, text)
        except (ImportError, NotImplementedError, AttributeError):
            delay = random.uniform(80, 180)
            try:
                locator.press_sequentially(text, delay=delay)
            except Exception:
                locator.fill(text)

    def _human_click(self, locator) -> None:
        try:
            import human_sim
            human_sim.human_click(locator)
        except (ImportError, NotImplementedError, AttributeError):
            self._short_pause()
            locator.click()

    def _wait_for_page_ready(self) -> None:
        """
        Block until the Qualtrics LoadingPage overlay is gone and at least one
        interactive element is present.

        This guard is necessary because _wait_for_qualtrics_transition() in
        next_page() only waits for the overlay if it arrives within a 3-second
        window.  When the server is slow the overlay appears later, causing
        fill_page() to attempt clicks while pointer events are still blocked.
        Calling this at the top of each page loop makes the guard unconditional.
        """
        try:
            overlay = self.page.locator("#SkinContent.LoadingPage")
            # wait_for with state="visible" returns immediately if already visible,
            # or raises TimeoutError after 2 s if it never appears — either way
            # we then wait for hidden.
            try:
                overlay.wait_for(state="visible", timeout=2_000)
            except Exception:
                pass  # Overlay never appeared — page is already ready
            overlay.wait_for(state="hidden", timeout=20_000)
        except Exception:
            pass
        # Ensure at least one interactive element is rendered before proceeding
        try:
            self.page.wait_for_selector(
                "#NextButton, #submitButton, div.QuestionOuter, [data-qid]",
                timeout=8_000,
            )
        except Exception:
            pass

    def _initial_page_scroll(self) -> None:
        """Scroll the page to simulate a user reading before answering."""
        try:
            import human_sim
            human_sim.simulate_page_scroll(self.page)
        except Exception:
            pass

    def _short_pause(self) -> None:
        ms = max(100, int(random.gauss(400, 100)))
        self.page.wait_for_timeout(ms)

    def _reading_pause(self) -> None:
        """Pause before hitting Next — scales with number of questions.
        Skipped entirely when the page has no visible questions (consent /
        loading pages) so we don't waste seconds on empty pages."""
        try:
            containers = self._find_question_containers()
            n = sum(1 for c in containers if c.is_visible())
        except Exception:
            n = 1

        if n == 0:
            # No containers yet — Qualtrics SPA may still be rendering.
            # Wait for content rather than spinning immediately back to the loop.
            try:
                self.page.wait_for_selector(
                    "#NextButton, #submitButton, div.QuestionOuter",
                    timeout=5_000,
                )
            except Exception:
                self.page.wait_for_timeout(500)
            return

        try:
            import human_sim
            human_sim.reading_pause(self.page, n_questions=n)
        except (ImportError, NotImplementedError, AttributeError):
            base_ms = max(500, n * 1_000)
            ms = max(300, int(random.gauss(base_ms, base_ms * 0.2)))
            self.page.wait_for_timeout(ms)
