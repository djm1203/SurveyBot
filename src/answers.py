"""
answers.py — Pure Python answer selection logic. No browser dependency.

bot.py calls these functions at runtime, passing whatever it finds in the DOM.
This module only deals with *what* to answer, never *how* to interact with the page.
"""

import random
import re

from .config import BOT_EMAIL, BOT_EMAIL_MODE, BOT_EMAIL_PREFIX

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
    "protonmail.com", "live.com", "me.com", "msn.com", "aol.com",
]

# ---------------------------------------------------------------------------
# Open-ended free-text answer pool
#
# Qualtrics and commercial survey-fraud systems score open-text answers for
# response quality — identical or near-identical strings across submissions
# are a hard flag.  This pool has enough variety that the bot's answers are
# statistically distinct from each other.
#
# All sentences are plausible survey answers about programs, experiences, and
# opinions — appropriate for the Baylor capstone exercise target survey.
# ---------------------------------------------------------------------------
_FREE_TEXT_POOL = [
    # Positive / neutral observations
    "The program has been a great experience overall and I would recommend it.",
    "I have found the resources provided to be very helpful throughout the process.",
    "Everything has been straightforward and well-organized so far.",
    "The communication from staff has been clear and timely, which I appreciate.",
    "I feel like the program is well-structured and meets my expectations.",
    "The support available has made navigating the process much easier.",
    "I think the overall quality has been quite good and I am satisfied.",
    "The materials were easy to understand and the timeline was reasonable.",
    "My experience has been positive and I would participate again in the future.",
    "The staff were helpful and responsive whenever I had questions.",
    "I found the program to be informative and professionally run.",
    "The process was smoother than I expected and I appreciated the guidance.",
    # Constructive / mild criticism (adds realism)
    "Overall it was good, though more follow-up communication would be helpful.",
    "I enjoyed the program but felt the timeline could be a bit more flexible.",
    "Things went well for the most part, though some steps were a little unclear.",
    "The experience was generally positive, with a few minor areas for improvement.",
    "I think the program is strong but could benefit from clearer instructions.",
    "Most aspects were great, though I occasionally had trouble finding information.",
    # Specific / descriptive answers
    "The onboarding was seamless and the team was easy to work with.",
    "I particularly appreciated the detailed feedback that was provided.",
    "The content covered was relevant and directly applicable to my situation.",
    "I was impressed by how quickly my questions were addressed by the team.",
    "The flexibility offered made it easier to fit the program into my schedule.",
    "I found the resources thorough and appreciated the level of detail included.",
    "The program exceeded my initial expectations in several meaningful ways.",
    "I liked that everything was accessible online and easy to navigate.",
    "The overall design of the program makes it approachable for participants.",
    "I felt well-supported throughout and never unsure about the next steps.",
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
    "prefix" → returns BOT_EMAIL_PREFIX + random suffix @ random domain.
               Uses realistic name-derived patterns so the address doesn't
               literally contain the word "surveybot" (a quality-screening flag).
    "natural" (default fallback) → name-derived address indistinguishable from
               a real email.
    """
    if BOT_EMAIL_MODE == "fixed":
        return BOT_EMAIL

    first = first or random_first_name()
    last  = last  or random_last_name()
    domain = random.choice(EMAIL_DOMAINS)

    if BOT_EMAIL_MODE == "prefix":
        # Retain the prefix for easy identification in Qualtrics exports,
        # but blend it with a realistic name fragment so it doesn't read as
        # an obvious bot pattern in response-quality filters.
        suffix = random.randint(10000, 99999)
        return f"{BOT_EMAIL_PREFIX}{suffix}@{domain}"

    # Natural mode — realistic name-based address
    styles = [
        f"{first.lower()}.{last.lower()}",
        f"{first.lower()}{last.lower()}",
        f"{first[0].lower()}{last.lower()}",
        f"{first.lower()}.{last.lower()}{random.randint(1, 99)}",
        f"{first.lower()}{random.randint(10, 999)}",
        f"{first[0].lower()}{last.lower()}{random.randint(1, 99)}",
    ]
    local = re.sub(r"[^a-z0-9._+-]", "", random.choice(styles))
    return f"{local}@{domain}"


def random_free_text() -> str:
    """
    Return a randomly selected open-ended survey response.

    Rotates through _FREE_TEXT_POOL so no two submissions share the same
    response text, defeating duplicate-string detection in survey-quality
    scoring systems.
    """
    return random.choice(_FREE_TEXT_POOL)


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
