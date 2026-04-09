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

import branching
from answers import (
    answer_text_field,
    classify_text_field,
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
        self.page.wait_for_load_state("domcontentloaded")

        page_num = 1
        while not branching.is_survey_complete(self.page):
            logger.info(f"[bot] ── Page {page_num} ──────────────────")
            self.fill_page()
            branching.handle_new_visible_questions(self.page, self)
            self._reading_pause()
            self.next_page()
            page_num += 1

            if page_num > 50:
                logger.error("[bot] Safety limit: 50 pages exceeded — aborting")
                break

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
                    self.page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
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
                    self.page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
                    logger.info(f"[bot] Next via role button '{name}'")
                    return
            except Exception:
                continue

        logger.error("[bot] Could not find Next/Submit button")

    def is_complete(self) -> bool:
        return branching.is_survey_complete(self.page)

    # ------------------------------------------------------------------
    # Question dispatcher
    # ------------------------------------------------------------------

    def _dispatch_question(self, container) -> None:
        """Inspect container children and call the right handler."""
        if self._has_visible(container, "input[type='text']"):
            self.handle_text_input(container)
        elif self._has_visible(container, "textarea"):
            self.handle_textarea(container)
        elif (self._has_visible(container, "input[type='radio']")
              or self._has_visible(container, ".radio, .RadioSelect, .ChoiceStructure")):
            self.handle_radio(container)
        elif self._has_visible(container, "input[type='checkbox']"):
            self.handle_checkbox(container)
        elif (self._has_visible(container, "input[type='range']")
              or self._has_visible(container, ".slider, .DragSlider, .QSlider, [role='slider']")):
            self.handle_slider(container)
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
        self._type_text(el, text)
        logger.info(f"[bot] Text ({field_type}): {text}")

    def handle_textarea(self, container) -> None:
        from answers import random_first_name
        text = (
            f"I think it is a great program. "
            f"{random_first_name()} agrees as well."
        )
        el = container.locator("textarea").first
        el.click()
        self._type_text(el, text)
        logger.info(f"[bot] Textarea: '{text[:40]}...'")

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
                        self._human_click(label_el)
                        self._short_pause()
                        break
                except Exception:
                    continue

        logger.info(f"[bot] Checkbox: {chosen}")

    def handle_slider(self, container) -> None:
        # ── Strategy 1: native <input type="range"> ──────────────────
        range_inputs = container.locator("input[type='range']")
        if range_inputs.count() > 0:
            el = range_inputs.first
            min_val = int(el.get_attribute("min") or 0)
            max_val = int(el.get_attribute("max") or 10)
            value = random_slider_value(min_val, max_val)
            el.evaluate(
                "(el, val) => {"
                "  el.value = val;"
                "  el.dispatchEvent(new Event('input',  {bubbles: true}));"
                "  el.dispatchEvent(new Event('change', {bubbles: true}));"
                "}",
                value,
            )
            logger.info(f"[bot] Slider (range input): {value} [{min_val}–{max_val}]")
            return

        # ── Strategy 2: Qualtrics custom slider — click on track ─────
        track_selectors = [
            ".slider-track", ".QSlider", ".DragSlider",
            "[role='slider']", ".slider", "div.sliderTrack",
        ]
        for sel in track_selectors:
            try:
                loc = container.locator(sel)
                if loc.count() == 0 or not loc.first.is_visible(timeout=400):
                    continue
                box = loc.first.bounding_box()
                if not box:
                    continue
                frac = max(0.05, min(0.95, random.gauss(0.5, 0.15)))
                x = box["x"] + box["width"] * frac
                y = box["y"] + box["height"] / 2
                self.page.mouse.click(x, y)
                logger.info(f"[bot] Slider (click at {frac:.2f} of track)")
                return
            except Exception:
                continue

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
        for sel in (".QuestionText", ".question-text", "label", "legend", "h2", "h3", "p"):
            try:
                el = container.locator(sel).first
                if el.is_visible(timeout=300):
                    return el.inner_text().strip()
            except Exception:
                continue
        return ""

    def _choice_labels(self, container) -> list[str]:
        labels = []
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
                locator.type(text, delay=delay)
            except Exception:
                locator.fill(text)

    def _human_click(self, locator) -> None:
        try:
            import human_sim
            human_sim.human_click(locator)
        except (ImportError, NotImplementedError, AttributeError):
            self._short_pause()
            locator.click()

    def _short_pause(self) -> None:
        ms = max(100, int(random.gauss(400, 100)))
        self.page.wait_for_timeout(ms)

    def _reading_pause(self) -> None:
        """Pause before hitting Next — scales with number of questions."""
        try:
            import human_sim
            human_sim.reading_pause(self.page)
        except (ImportError, NotImplementedError, AttributeError):
            n = len(self._find_question_containers())
            base_ms = max(1_000, n * 1_500)
            ms = max(500, int(random.gauss(base_ms, base_ms * 0.2)))
            self.page.wait_for_timeout(ms)
