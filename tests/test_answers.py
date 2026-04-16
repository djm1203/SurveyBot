"""
tests/test_answers.py — Unit tests for answers.py

All tests are pure Python — no browser, no Playwright, no network.
Run with:  pytest tests/
"""

import re
import pytest
from answers import (
    FIRST_NAMES,
    LAST_NAMES,
    EMAIL_DOMAINS,
    random_first_name,
    random_last_name,
    random_email,
    classify_text_field,
    answer_text_field,
    select_choice,
    random_slider_value,
)


# ---------------------------------------------------------------------------
# random_first_name / random_last_name
# ---------------------------------------------------------------------------

def test_random_first_name_in_pool():
    assert random_first_name() in FIRST_NAMES


def test_random_last_name_in_pool():
    assert random_last_name() in LAST_NAMES


def test_names_are_non_empty_strings():
    assert isinstance(random_first_name(), str) and len(random_first_name()) > 0
    assert isinstance(random_last_name(), str) and len(random_last_name()) > 0


# ---------------------------------------------------------------------------
# random_email
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"^[a-z0-9._+-]+@[a-z0-9.-]+\.[a-z]{2,}$")


def test_email_valid_format():
    for _ in range(20):
        assert EMAIL_RE.match(random_email()), f"Invalid: {random_email()}"


def test_email_uses_known_domain():
    for _ in range(20):
        domain = random_email().split("@")[1]
        assert domain in EMAIL_DOMAINS


def test_email_prefix_mode():
    # Explicitly test "prefix" mode — local part starts with BOT_EMAIL_PREFIX.
    # Must patch answers.BOT_EMAIL_MODE (the already-imported name), not
    # config.BOT_EMAIL_MODE, because answers.py binds the value at import time.
    import answers as _ans
    original = _ans.BOT_EMAIL_MODE
    try:
        _ans.BOT_EMAIL_MODE = "prefix"
        email = random_email(first="Alice", last="Smith")
        local = email.split("@")[0]
        assert local.startswith(_ans.BOT_EMAIL_PREFIX)
    finally:
        _ans.BOT_EMAIL_MODE = original


def test_email_without_hints_still_valid():
    email = random_email()
    assert EMAIL_RE.match(email)


# ---------------------------------------------------------------------------
# classify_text_field
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,expected", [
    ("What is your first name?", "first_name"),
    ("First Name", "first_name"),
    ("What is your last name?", "last_name"),
    ("Last Name", "last_name"),
    ("What is your email?", "email"),
    ("Email address", "email"),
    ("Your email:", "email"),
    ("Enter your name", "first_name"),    # bare "name" → first_name
    ("Describe your experience", "generic"),
    ("Additional comments", "generic"),
])
def test_classify_text_field(label, expected):
    assert classify_text_field(label) == expected


# ---------------------------------------------------------------------------
# answer_text_field
# ---------------------------------------------------------------------------

def test_answer_first_name_in_pool():
    assert answer_text_field("first_name") in FIRST_NAMES


def test_answer_last_name_in_pool():
    assert answer_text_field("last_name") in LAST_NAMES


def test_answer_email_valid():
    assert EMAIL_RE.match(answer_text_field("email"))


def test_answer_email_prefix_mode_uses_bot_prefix():
    # Explicitly test "prefix" mode — patch answers module, not config module.
    import answers as _ans
    original = _ans.BOT_EMAIL_MODE
    try:
        _ans.BOT_EMAIL_MODE = "prefix"
        email = answer_text_field("email", first_name="Carol", last_name="King")
        local = email.split("@")[0]
        assert local.startswith(_ans.BOT_EMAIL_PREFIX)
    finally:
        _ans.BOT_EMAIL_MODE = original


def test_answer_generic_returns_string():
    result = answer_text_field("generic")
    assert isinstance(result, str) and len(result) > 0


def test_answer_uses_provided_first_name():
    result = answer_text_field("first_name", first_name="Zara")
    assert result == "Zara"


def test_answer_uses_provided_last_name():
    result = answer_text_field("last_name", last_name="Okonkwo")
    assert result == "Okonkwo"


# ---------------------------------------------------------------------------
# select_choice
# ---------------------------------------------------------------------------

MAJORS = ["CS-General", "CS-Cyber", "CS-SWE", "DS"]
OPTIONS_WITH_OTHER = ["CS-General", "CS-Cyber", "CS-SWE", "DS", "Other"]
OPTIONS_WITH_EXCLUSIVE = ["CS-General", "CS-Cyber", "I cannot answer"]
OPTIONS_ALL_FORBIDDEN = ["Other", "Please specify"]
OPTIONS_ALL_EXCLUSIVE = ["I cannot answer", "Prefer not to say"]


def test_select_choice_returns_from_list():
    for _ in range(30):
        result = select_choice(MAJORS)
        assert result in MAJORS


def test_select_choice_never_picks_other():
    for _ in range(50):
        result = select_choice(OPTIONS_WITH_OTHER)
        assert result != "Other"


def test_select_choice_never_picks_forbidden_custom():
    options = ["Option A", "Option B", "Write-in answer"]
    for _ in range(30):
        result = select_choice(options, forbidden_patterns=["write-in"])
        assert result in ("Option A", "Option B")


def test_select_choice_all_forbidden_returns_none():
    result = select_choice(OPTIONS_ALL_FORBIDDEN)
    assert result is None


def test_select_choice_exclusive_prob_zero_never_picks_exclusive():
    for _ in range(50):
        result = select_choice(OPTIONS_WITH_EXCLUSIVE, exclusive_prob=0.0)
        assert result != "I cannot answer"


def test_select_choice_exclusive_prob_one_always_picks_exclusive():
    for _ in range(20):
        result = select_choice(OPTIONS_WITH_EXCLUSIVE, exclusive_prob=1.0)
        assert result == "I cannot answer"


def test_select_choice_all_exclusive_fallback():
    # When prob=0 but only exclusive options remain (no normal), should still pick one
    result = select_choice(OPTIONS_ALL_EXCLUSIVE, exclusive_prob=0.0)
    assert result in OPTIONS_ALL_EXCLUSIVE


def test_select_choice_single_option():
    assert select_choice(["CS-General"]) == "CS-General"


def test_select_choice_empty_list_returns_none():
    assert select_choice([]) is None


# ---------------------------------------------------------------------------
# random_slider_value
# ---------------------------------------------------------------------------

def test_slider_in_range():
    for _ in range(100):
        val = random_slider_value(0, 10)
        assert 0 <= val <= 10


def test_slider_custom_range():
    for _ in range(100):
        val = random_slider_value(1, 5)
        assert 1 <= val <= 5


def test_slider_returns_int():
    assert isinstance(random_slider_value(), int)


def test_slider_min_equals_max():
    assert random_slider_value(7, 7) == 7


def test_slider_covers_range():
    # Run enough times that we expect both ends of a small range to appear
    values = {random_slider_value(0, 2) for _ in range(200)}
    assert values == {0, 1, 2}
