"""
branching.py — Qualtrics conditional logic and completion detection.

Responsibilities:
  - Detect when the survey is complete
  - After each page fill, find question containers that became visible
    due to Qualtrics display logic and hand them back to the bot

NOTE: This module intentionally does NOT import bot.py to avoid a
circular import. It receives the bot instance as a parameter instead.
"""

import logging

logger = logging.getLogger(__name__)

# Mirrored from bot.py — kept here to avoid circular imports
_QUESTION_SELECTORS = [
    "div.QuestionOuter",
    "div.question-container",
    "[data-qid]",
    ".question-block",
]

_COMPLETION_PHRASES = [
    "thank you",
    "your response has been recorded",
    "survey is now complete",
    "you have completed",
    "end of survey",
    "submission complete",
    "response recorded",
    "your survey has been submitted",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_survey_complete(page) -> bool:
    """
    Return True if the survey appears to be finished.

    Checks (in order):
    1. URL contains Qualtrics end-of-survey parameters
    2. Page body contains a known completion phrase
    3. Neither a Next button nor a Submit button exists on the page
    """
    url = page.url

    # Qualtrics appends ?SE= or redirects to a SurveyRetire page when done
    if "SE=" in url or "SurveyRetire" in url:
        logger.info("[branching] Complete — URL pattern matched")
        return True

    # Scan visible text for completion phrases
    try:
        body = page.locator("body").inner_text(timeout=3_000).lower()
        for phrase in _COMPLETION_PHRASES:
            if phrase in body:
                logger.info(f"[branching] Complete — phrase: '{phrase}'")
                return True
    except Exception:
        pass

    # No navigation buttons left → survey likely ended
    has_next   = _element_visible(page, "#NextButton")
    has_submit = _element_visible(page, "#submitButton")
    if not has_next and not has_submit:
        # Guard against false positives on slow loads
        try:
            page.wait_for_load_state("domcontentloaded", timeout=3_000)
        except Exception:
            pass
        # Re-check after load settles — if still no buttons, we're done
        if not _element_visible(page, "#NextButton") and \
           not _element_visible(page, "#submitButton"):
            logger.info("[branching] Complete — no navigation buttons present")
            return True

    return False


def handle_new_visible_questions(page, bot) -> None:
    """
    After fill_page(), scan for question containers that became visible
    due to Qualtrics display logic.  Re-run the bot dispatcher on any
    that appear unanswered.

    Parameters
    ----------
    page : Playwright Page
    bot  : SurveyBot instance — used to call _dispatch_question()
    """
    for selector in _QUESTION_SELECTORS:
        try:
            containers = page.locator(selector).all()
            if not containers:
                continue

            for container in containers:
                try:
                    if container.is_visible(timeout=300) and not _is_answered(container):
                        logger.info("[branching] Newly visible question — dispatching")
                        bot._dispatch_question(container)
                except Exception as exc:
                    logger.debug(f"[branching] Container check error: {exc}")
            return  # Found a selector that worked — done
        except Exception:
            continue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _element_visible(page, selector: str) -> bool:
    try:
        loc = page.locator(selector)
        return loc.count() > 0 and loc.first.is_visible(timeout=500)
    except Exception:
        return False


def _is_answered(container) -> bool:
    """
    Heuristic: return True if the container already has user input.
    Not exhaustive — primarily catches radio/checkbox and text fields.
    """
    try:
        if container.locator("input:checked").count() > 0:
            return True
        for sel in ("input[type='text']", "textarea"):
            for inp in container.locator(sel).all():
                try:
                    if inp.input_value():
                        return True
                except Exception:
                    pass
    except Exception:
        pass
    return False
