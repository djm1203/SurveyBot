"""
answers.py — Pure Python answer selection logic. No browser dependency.

bot.py calls these functions at runtime, passing whatever it finds in the DOM.
This module only deals with *what* to answer, never *how* to interact with the page.
"""

import random
import re

from config import BOT_EMAIL, BOT_EMAIL_MODE, BOT_EMAIL_PREFIX

# ---------------------------------------------------------------------------
# Data pools
# ---------------------------------------------------------------------------

FIRST_NAMES = [
    "James", "John", "Robert", "Michael", "William", "David", "Richard",
    "Joseph", "Thomas", "Charles", "Christopher", "Daniel", "Matthew",
    "Anthony", "Mark", "Donald", "Steven", "Paul", "Andrew", "Joshua",
    "Mary", "Patricia", "Jennifer", "Linda", "Barbara", "Elizabeth",
    "Susan", "Jessica", "Sarah", "Karen", "Lisa", "Nancy", "Betty",
    "Margaret", "Sandra", "Ashley", "Dorothy", "Kimberly", "Emily",
    "Donna", "Michelle", "Carol", "Amanda", "Melissa", "Deborah",
    "Stephanie", "Rebecca", "Sharon", "Laura", "Cynthia",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
    "Carter", "Roberts",
]

EMAIL_DOMAINS = [
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com",
    "protonmail.com", "live.com",
]

# Patterns that indicate a "cannot answer / prefer not to say" type option.
# Matching is case-insensitive substring.
_EXCLUSIVE_PATTERNS = [
    "cannot answer",
    "prefer not",
    "decline to",
    "none of the above",
    "not applicable",
    "n/a",
]

# Patterns that indicate an option which triggers a mandatory open text field.
# These should never be selected by the bot.
_FORBIDDEN_PATTERNS = [
    "other",
    "please specify",
    "write in",
]


# ---------------------------------------------------------------------------
# Text field helpers
# ---------------------------------------------------------------------------

def random_first_name() -> str:
    return random.choice(FIRST_NAMES)


def random_last_name() -> str:
    return random.choice(LAST_NAMES)


def random_email(first: str | None = None, last: str | None = None) -> str:
    """
    Generate an email address according to BOT_EMAIL_MODE in config.py.

    "fixed"  → always returns BOT_EMAIL exactly.
    "prefix" → returns BOT_EMAIL_PREFIX + random numeric suffix @ random domain,
               e.g. surveybot4821@gmail.com. Easy for your team to grep in
               Qualtrics data while still varying per submission.

    first/last are accepted for API compatibility but only used if mode is
    neither "fixed" nor "prefix" (future extension).
    """
    if BOT_EMAIL_MODE == "fixed":
        return BOT_EMAIL

    if BOT_EMAIL_MODE == "prefix":
        domain = random.choice(EMAIL_DOMAINS)
        suffix = random.randint(1000, 9999)
        return f"{BOT_EMAIL_PREFIX}{suffix}@{domain}"

    # Fallback: derive from name hints (realistic random address)
    first = first or random_first_name()
    last = last or random_last_name()
    domain = random.choice(EMAIL_DOMAINS)
    styles = [
        f"{first.lower()}.{last.lower()}",
        f"{first.lower()}{last.lower()}",
        f"{first[0].lower()}{last.lower()}",
        f"{first.lower()}.{last.lower()}{random.randint(1, 99)}",
        f"{first.lower()}{random.randint(10, 999)}",
    ]
    local = re.sub(r"[^a-z0-9._+-]", "", random.choice(styles))
    return f"{local}@{domain}"


def classify_text_field(label: str) -> str:
    """
    Heuristic: inspect the question label and return the semantic type.
    Returns one of: 'first_name', 'last_name', 'email', 'generic'.
    """
    label_lower = label.lower()
    if "email" in label_lower:
        return "email"
    if "first" in label_lower and "name" in label_lower:
        return "first_name"
    if "last" in label_lower and "name" in label_lower:
        return "last_name"
    # "full name" or bare "name" — treat as first name
    if "name" in label_lower:
        return "first_name"
    return "generic"


def answer_text_field(
    field_type: str,
    first_name: str | None = None,
    last_name: str | None = None,
) -> str:
    """
    Return the string to type into a text field.

    Parameters
    ----------
    field_type : str
        One of the values returned by classify_text_field().
    first_name : str, optional
        Already-generated first name so the email can match.
    last_name : str, optional
        Already-generated last name so the email can match.
    """
    if field_type == "first_name":
        return first_name or random_first_name()
    if field_type == "last_name":
        return last_name or random_last_name()
    if field_type == "email":
        return random_email(first_name, last_name)
    # generic — return a short random word-like string
    return random_first_name()


# ---------------------------------------------------------------------------
# Multiple choice / checkbox helpers
# ---------------------------------------------------------------------------

def _matches_any(text: str, patterns: list[str]) -> bool:
    t = text.lower()
    return any(p in t for p in patterns)


def select_choice(
    options: list[str],
    forbidden_patterns: list[str] | None = None,
    exclusive_patterns: list[str] | None = None,
    exclusive_prob: float = 0.2,
) -> str | None:
    """
    Choose one option from a list, applying exclusion rules.

    Parameters
    ----------
    options : list[str]
        All visible option labels for the question.
    forbidden_patterns : list[str], optional
        Substrings that mark options the bot must never select (e.g. "other").
        Defaults to the module-level _FORBIDDEN_PATTERNS list.
    exclusive_patterns : list[str], optional
        Substrings that mark "cannot answer" style options.
        Defaults to the module-level _EXCLUSIVE_PATTERNS list.
    exclusive_prob : float
        Probability (0–1) of selecting an exclusive option when one exists.
        Default 0.2 (20%).

    Returns
    -------
    str | None
        The label of the chosen option, or None if no selectable options remain.
    """
    if forbidden_patterns is None:
        forbidden_patterns = _FORBIDDEN_PATTERNS
    if exclusive_patterns is None:
        exclusive_patterns = _EXCLUSIVE_PATTERNS

    # Split options into buckets
    forbidden = [o for o in options if _matches_any(o, forbidden_patterns)]
    exclusive = [o for o in options if o not in forbidden and _matches_any(o, exclusive_patterns)]
    normal = [o for o in options if o not in forbidden and o not in exclusive]

    # Decide whether to pick an exclusive option
    if exclusive and random.random() < exclusive_prob:
        return random.choice(exclusive)

    if normal:
        return random.choice(normal)

    # Fall back to exclusive if no normal options remain
    if exclusive:
        return random.choice(exclusive)

    return None  # every option was forbidden — caller must handle


# ---------------------------------------------------------------------------
# Slider helper
# ---------------------------------------------------------------------------

def random_slider_value(min_val: int = 0, max_val: int = 10) -> int:
    """
    Return a random integer in [min_val, max_val] inclusive.
    Biased slightly toward the middle to look more human (avoids always
    picking extremes like 0 or 10).
    """
    if min_val == max_val:
        return min_val

    # Gaussian centered at midpoint, clipped to range
    mid = (min_val + max_val) / 2
    std = (max_val - min_val) / 4  # ~95% of values fall within range
    value = round(random.gauss(mid, std))
    return max(min_val, min(max_val, value))
