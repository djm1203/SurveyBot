"""
main.py — SurveyBot entry point.

WHAT THIS DOES
--------------
Runs the complete bot pipeline N times.  At startup it prompts for the
survey URL, run count, and email mode — all values default to config.py
so teammates can just press Enter to accept them.

Each run is fully independent:
  1. Generate a fresh browser fingerprint  (fingerprint.py)
  2. Launch an anti-detect browser         (stealth.py)
  3. Load a random human keystroke profile (human_sim.py)
  4. Navigate and fill the survey          (bot.py)
  5. Close the browser cleanly
  6. Wait a randomised gap before the next run

LAYER SUMMARY
-------------
  Layer 1 — Stealth Browser   : stealth.py + fingerprint.py
  Layer 2 — Survey Navigation : bot.py + answers.py + branching.py
  Layer 3 — Human Simulation  : human_sim.py + mouse.py

USAGE
-----
    python main.py

You will be prompted for configuration before anything launches.
Press Enter on any prompt to accept the default shown in brackets.

LOGGING
-------
All modules log to the console at INFO level by default.
Change LOG_LEVEL below to DEBUG for verbose output during development.
"""

import logging
import random
import sys
import time

import human_sim
import mouse
from bot import SurveyBot
from config import BOT_EMAIL, BOT_EMAIL_MODE, BOT_EMAIL_PREFIX, RUN_COUNT, SURVEY_URL, TIMING
from fingerprint import generate_fingerprint
from stealth import launch_browser

# ---------------------------------------------------------------------------
# Logging setup
# All modules use logging.getLogger(__name__), so configuring the root
# logger here propagates to every module automatically.
# ---------------------------------------------------------------------------
LOG_LEVEL = logging.INFO   # Change to logging.DEBUG for verbose output

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Inter-run delay
# Waiting between runs avoids triggering rate-limiting or submission-burst
# detection on the survey platform.
# ---------------------------------------------------------------------------
_INTER_RUN_MIN_S = 5    # minimum seconds between runs
_INTER_RUN_MAX_S = 15   # maximum seconds between runs


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# CLI prompt
# ---------------------------------------------------------------------------

def prompt_config() -> dict:
    """
    Interactively ask the user for runtime configuration.

    Every field has a default pulled from config.py — pressing Enter
    accepts it without typing anything.  Returns a dict with the
    final values to use for this session.
    """
    width = 60
    print("\n" + "═" * width)
    print("  SurveyBot".center(width))
    print("  Baylor Capstone — Red Team Survey Automation".center(width))
    print("═" * width + "\n")
    print("  Press Enter to accept the default shown in [brackets].\n")

    # ── Survey URL ───────────────────────────────────────────────────────
    url_input = input(f"  Survey URL\n  [{SURVEY_URL}]\n  > ").strip()
    url = url_input or SURVEY_URL

    # ── Run count ────────────────────────────────────────────────────────
    while True:
        count_input = input(f"\n  Number of submissions [{RUN_COUNT}]: ").strip()
        if not count_input:
            count = RUN_COUNT
            break
        if count_input.isdigit() and int(count_input) > 0:
            count = int(count_input)
            break
        print("  Please enter a positive integer.")

    # ── Email mode ───────────────────────────────────────────────────────
    print(f"\n  Email mode:")
    print(f"    prefix — random suffix each run  e.g. {BOT_EMAIL_PREFIX}4821@gmail.com")
    print(f"    fixed  — same address every run  e.g. {BOT_EMAIL}")
    while True:
        mode_input = input(f"\n  Email mode [{BOT_EMAIL_MODE}]: ").strip().lower()
        if not mode_input:
            email_mode = BOT_EMAIL_MODE
            break
        if mode_input in ("prefix", "fixed"):
            email_mode = mode_input
            break
        print("  Please type 'prefix' or 'fixed'.")

    # ── Confirmation ─────────────────────────────────────────────────────
    print("\n" + "─" * width)
    print(f"  URL        : {url}")
    print(f"  Runs       : {count}")
    print(f"  Email mode : {email_mode}")
    print("─" * width)

    confirm = input("\n  Start? [Y/n]: ").strip().lower()
    if confirm == "n":
        print("\n  Aborted.\n")
        sys.exit(0)

    print()
    return {"url": url, "count": count, "email_mode": email_mode}


# ---------------------------------------------------------------------------
# Per-run pipeline
# ---------------------------------------------------------------------------

def run_once(run_number: int, total_runs: int, url: str, email_mode: str) -> bool:
    """
    Execute a single end-to-end survey submission.

    Returns True if the run completed successfully, False on error.

    Parameters
    ----------
    run_number  : 1-based index of this run (for logging)
    total_runs  : Total number of runs planned (for logging)
    url         : Survey URL to navigate to
    email_mode  : "prefix" or "fixed" — overrides config.BOT_EMAIL_MODE
    """
    logger.info(f"{'='*55}")
    logger.info(f"  RUN {run_number} of {total_runs}")
    logger.info(f"{'='*55}")

    # ── Step 1: generate a unique fingerprint for this run ───────────────
    # A new fingerprint = a new "person" from the perspective of RelevantID
    # and browser fingerprint databases.
    fingerprint = generate_fingerprint()
    logger.info(
        f"[main] Fingerprint: {fingerprint.get('platform')} | "
        f"{fingerprint['viewport']['width']}×{fingerprint['viewport']['height']} | "
        f"{fingerprint.get('locale')}"
    )

    # ── Step 2: pick a human keystroke profile for this run ──────────────
    # Randomly selects one of the recorded JSON profiles from keystrokes/.
    # All typing this run will mimic that person's rhythm.
    profile_name = human_sim.select_profile()
    logger.info(f"[main] Keystroke profile: {profile_name or 'fallback defaults'}")

    # ── Step 3: reset mouse tracking position ────────────────────────────
    # Pretend the cursor starts near the center of the viewport so the
    # first Bezier move has a plausible start point.
    vp = fingerprint["viewport"]
    mouse.reset_position(
        x=vp["width"]  / 2 + random.gauss(0, 20),
        y=vp["height"] / 2 + random.gauss(0, 20),
    )

    # ── Step 4: launch browser ───────────────────────────────────────────
    # BrowserSession is a context manager — browser is guaranteed to close
    # even if the bot raises an exception.
    with launch_browser(fingerprint) as session:
        logger.info(f"[main] Browser mode: {session.mode}")

        # ── Step 5: run the bot ──────────────────────────────────────────
        # Pass TIMING from config so bot.py can use page_load_timeout_ms
        # without importing config directly (keeps bot.py portable).
        bot = SurveyBot(
            page=session.page,
            config={
                "survey_url": url,
                "TIMING": TIMING,
                # email_mode is passed through so answers.py can respect it
                # at runtime without re-importing config each run
                "email_mode": email_mode,
            },
        )
        try:
            bot.run()
            logger.info(f"[main] Run {run_number} completed successfully")
            return True
        except Exception as exc:
            logger.error(f"[main] Run {run_number} failed: {exc}", exc_info=True)
            return False


def main() -> None:
    """
    Entry point — prompt for config, then run the bot N times.
    """
    # Collect URL, run count, and email mode from the user before anything launches
    cfg = prompt_config()

    # Apply the chosen email mode globally so answers.py picks it up.
    # We patch the config module directly so the import in answers.py
    # sees the updated value without needing a restart.
    import config as _cfg_module
    _cfg_module.BOT_EMAIL_MODE = cfg["email_mode"]

    logger.info("SurveyBot starting")
    logger.info(f"Target URL  : {cfg['url']}")
    logger.info(f"Planned runs: {cfg['count']}")
    logger.info(f"Email mode  : {cfg['email_mode']}")

    successes = 0
    failures  = 0

    for i in range(1, cfg["count"] + 1):
        ok = run_once(
            run_number=i,
            total_runs=cfg["count"],
            url=cfg["url"],
            email_mode=cfg["email_mode"],
        )
        if ok:
            successes += 1
        else:
            failures += 1

        # Wait between runs — skip the delay after the final run
        if i < cfg["count"]:
            gap = random.uniform(_INTER_RUN_MIN_S, _INTER_RUN_MAX_S)
            logger.info(f"[main] Waiting {gap:.1f}s before next run…")
            time.sleep(gap)

    # ── Final summary ─────────────────────────────────────────────────────
    logger.info(f"{'='*55}")
    logger.info(f"  DONE — {successes} succeeded, {failures} failed")
    logger.info(f"{'='*55}")


# ---------------------------------------------------------------------------
# Entry guard
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    main()
