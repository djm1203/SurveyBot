SURVEY_URL = "https://baylor.qualtrics.com/jfe/form/SV_6GagF9EpumzN06W"

# How many times to submit the survey per run
RUN_COUNT = 1

# Email strategy for the bot:
#   "fixed"  — always use BOT_EMAIL exactly (easy to filter, useful for testing)
#   "prefix" — use BOT_EMAIL_PREFIX + random suffix (harder to block en masse)
BOT_EMAIL_MODE = "prefix"
BOT_EMAIL = "surveybot.test@gmail.com"       # used when mode = "fixed"
BOT_EMAIL_PREFIX = "surveybot"               # used when mode = "prefix"

# Human simulation timing constants (seconds)
TIMING = {
    # Delay between individual answer selections
    "min_action_delay": 0.15,
    "max_action_delay": 0.5,
    # Gaussian params for click delay (mean, std)
    "click_mean": 0.3,
    "click_std": 0.1,
    # Reading pause per question on a page (scales with question count)
    "read_per_question_mean": 0.6,
    "read_per_question_std": 0.2,
    # Delay range before hitting Next button
    "next_button_min": 0.4,
    "next_button_max": 1.0,
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
