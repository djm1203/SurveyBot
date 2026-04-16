SURVEY_URL = "https://baylor.qualtrics.com/jfe/form/SV_6GagF9EpumzN06W"

# How many times to submit the survey per run
RUN_COUNT = 1

# Email strategy for the bot:
#   "fixed"  — always use BOT_EMAIL exactly (easy to filter, useful for testing)
#   "prefix" — use BOT_EMAIL_PREFIX + random suffix (harder to block en masse)
BOT_EMAIL_MODE = "natural"               # generates realistic name-based addresses
BOT_EMAIL = "surveybot.test@gmail.com"   # used when mode = "fixed"
BOT_EMAIL_PREFIX = "surveybot"           # used when mode = "prefix" (testing only)
# "prefix" mode always produces surveybot##### addresses — a single grep in the
# Qualtrics export identifies every bot run regardless of behavioral scores.
# Use "natural" for real runs; switch to "prefix" only during local testing.

# Human simulation timing constants (seconds)
# These values produce a realistic 3–6 minute survey completion time.
# Lower values were flagged by behavioral biometric detection (completion
# time and inter-action variance are both scored signals).
TIMING = {
    # Delay between individual answer selections (e.g. checkbox to next radio)
    "min_action_delay": 0.5,
    "max_action_delay": 2.0,
    # Gaussian params for pre-click pause (hand-movement + decision time)
    "click_mean": 0.6,
    "click_std": 0.15,
    # Reading pause per question on a page (scales linearly with question count)
    # 3 s/question × 3 questions = ~9 s reading time before answering
    "read_per_question_mean": 3.0,
    "read_per_question_std": 0.9,
    # Extra pause before hitting Next after all questions are answered
    "next_button_min": 1.2,
    "next_button_max": 3.0,
    # Page load wait (max)
    "page_load_timeout_ms": 15_000,
}

# Sample text teammates type during keystroke recording session
SAMPLE_TEXT = (
    "The quick brown fox jumps over the lazy dog near the "
    "river bank. Every morning the birds sing outside the window and the sun "
    "rises slowly over the hills. People walk their dogs along the path while "
    "children play in the park nearby. The weather has been warm and pleasant "
    "this week, making it a good time to go outside and enjoy the fresh air. "
    "Most days start slowly but pick up pace as the morning moves along."
)
