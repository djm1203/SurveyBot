# SurveyBot

A Python browser automation bot built for a red team vs. blue team capstone exercise at Baylor University. The objective is to bypass bot detection software protecting a Qualtrics survey — demonstrating the attack/defense cycle in survey integrity research.

## Architecture

The bot operates in three layers:

| Layer | Files | Purpose |
| --- | --- | --- |
| **Stealth Browser** | `stealth.py`, `fingerprint.py`, `warm_profile.py` | Launches Camoufox (anti-detect Firefox) with realistic fingerprints; restores a pre-warmed browser profile for reCAPTCHA v3 scoring; isolates each run to a fresh context to defeat Q_DuplicateRespondent |
| **Survey Navigation** | `bot.py`, `answers.py`, `branching.py` | Playwright automation that navigates Qualtrics page-by-page, selects answers, checks the honeypot field, and handles conditional branching |
| **Human Simulation** | `human_sim.py`, `mouse.py`, `recorder.py` | WindMouse physics engine for realistic mouse paths, keystroke profile replay with flight-time offset to clear biometric thresholds, scroll simulation, and Gaussian-distributed pacing |

## Detection Vectors Addressed

1. `navigator.webdriver` flag — Camoufox patches at C++ engine level
2. Canvas / WebGL fingerprint consistency — Camoufox noise injection, verified per run via hash probe
3. Q_DuplicateRespondent repeat-device detection — isolated browser context per run
4. reCAPTCHA v3 cold-context low score (0.1–0.3) — pre-warmed profile with Google cookies + browsing history
5. Honeypot hidden field — explicit check before every Next click; ERROR log if filled
6. LegacyTextAnalytics paste detection — keystroke-by-keystroke typing via `press_sequentially`; fallback to `.fill()` triggers a warning log
7. Typing avg-speed < 120ms biometric threshold — `_FLIGHT_OFFSET_MS = 50ms` shifts recorded profiles from 91–96ms to 141–146ms effective average
8. Mouse path efficiency > 0.99 (near-straight-line) — WindMouse gravity + wind turbulence produces curved, realistic trajectories
9. Mouse velocity stddev < 0.02 (uniform robotic movement) — WindMouse random wind term + micro-jitter
10. No overshoot on mouse movement — overshoot + correction phase after every move
11. Zero scroll events — `simulate_page_scroll()` called on every page load
12. Completion speed anomaly (Q_TotalDuration) — Gaussian-randomized delays; 30s minimum monitored
13. Submission burst pattern — 30–90s randomized inter-run gap
14. Recognizable bot email pattern — natural name-based email mode (`donna.perez55@yahoo.com`)
15. Browser fingerprint field inconsistency — BrowserForge generates internally-consistent UA / platform / locale / timezone tuples

## Setup

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m camoufox fetch   # downloads the patched Firefox binary
```

## Keystroke Recording (run once per teammate)

Each team member records their personal typing profile before using the bot:

```bash
python recorder.py
```

Follow the prompts — type the sample paragraph naturally. The script saves your profile to `keystrokes/person_XX.json`. The bot randomly selects one profile per run to replay realistic keystroke rhythms.

## Profile Warming (run before each bot session)

Warm a browser profile so reCAPTCHA v3 sees a session with real Google cookies and browsing history:

```bash
python warm_profile.py
```

This visits Google, YouTube, Wikipedia, AP News, and BBC with human scroll and mouse events, then saves the browser state to `profiles/warmed_profile_TIMESTAMP.json`. The bot picks the most recently saved profile automatically. Re-run every few days to keep cookies fresh.

## Running the Bot

```bash
python main.py
```

You will be prompted for the survey URL, number of runs, and email mode (`natural` / `prefix` / `fixed`). Press Enter to accept the defaults from `config.py`.

## Project Structure

```text
SurveyBot/
├── main.py              # entry point — CLI prompt, N-run orchestrator, inter-run gaps
├── bot.py               # core Playwright navigation; honeypot check; question dispatch
├── stealth.py           # Camoufox launch; context isolation; storage_state restore
├── fingerprint.py       # BrowserForge fingerprint generation
├── warm_profile.py      # one-time browser pre-warming for reCAPTCHA v3
├── human_sim.py         # keystroke replay; flight-time offset; scroll simulation
├── mouse.py             # WindMouse physics engine (gravity + wind + overshoot)
├── answers.py           # answer generation — names, emails, choices, free-text pool
├── branching.py         # Qualtrics completion detection; conditional question handling
├── recorder.py          # keystroke timing profiler for teammates
├── config.py            # URL, run count, email mode, timing constants
├── keystrokes/          # recorded JSON profiles (gitignored)
├── profiles/            # warmed browser profiles (gitignored)
└── tests/
    └── test_answers.py  # pytest unit tests for answers.py
```
