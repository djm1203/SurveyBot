# SurveyBot

A Python browser automation bot built for a red team vs. blue team capstone exercise at Baylor University. The objective is to bypass bot detection software protecting a Qualtrics survey — demonstrating the attack/defense cycle in survey integrity research.

## Architecture

The bot operates in three layers:

| Layer | Files | Purpose |
|-------|-------|---------|
| **Stealth Browser** | `stealth.py`, `fingerprint.py` | Launches Camoufox (anti-detect Firefox) with realistic fingerprints; isolates each run to a fresh browser context to defeat RelevantID |
| **Survey Navigation** | `bot.py`, `answers.py`, `branching.py` | Playwright automation that navigates Qualtrics page-by-page, selects answers, and handles conditional branching |
| **Human Simulation** | `human_sim.py`, `mouse.py`, `recorder.py` | Randomized delays, Bezier-curve mouse movement, and per-teammate keystroke timing profiles to defeat behavioral analysis |

## Detection Vectors Addressed

1. `navigator.webdriver` flag — Camoufox patches at engine level
2. Browser fingerprint inconsistency — BrowserForge generates believable profiles
3. Completion speed anomalies — Gaussian-randomized delays in `human_sim.py`
4. Keystroke timing uniformity — recorded human profiles replayed via `recorder.py`
5. Straight-line mouse movement — Bezier curves in `mouse.py`
6. Window focus loss events — headful browser kept in focus
7. RelevantID duplicate detection — isolated browser context per run
8. Honeypot hidden fields — all interactions gated on `is_visible()` checks
9. reCAPTCHA v3 scoring — Camoufox + realistic behavioral timing
10. Missing JS keyboard events — Playwright keyboard API (not `.fill()`)

## Setup

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m camoufox fetch   # downloads the patched Firefox binary
```

## Keystroke Recording (run once per teammate)

Each team member should record their personal typing profile before the bot is used:

```bash
python recorder.py
```

Follow the prompts — you will be asked to type a short paragraph naturally. The script saves your timing profile to `keystrokes/person_XX.json`. The bot randomly selects one profile per run to replay realistic keystroke rhythms.

## Running the Bot

```bash
python main.py
```

Set `RUN_COUNT` in `config.py` to control how many survey submissions to make.

## Project Structure

```
SurveyBot/
├── main.py              # entry point
├── bot.py               # core Playwright navigation class
├── stealth.py           # Camoufox browser launch
├── fingerprint.py       # BrowserForge fingerprint generation
├── human_sim.py         # timing delays and reading pauses
├── mouse.py             # Bezier curve mouse movement
├── answers.py           # answer selection logic (pure Python)
├── branching.py         # Qualtrics conditional page logic
├── recorder.py          # keystroke timing profiler for teammates
├── config.py            # constants, URL, timing params, sample text
├── keystrokes/          # recorded JSON profiles (gitignored)
└── tests/
    └── test_answers.py  # pytest unit tests for answers.py
```
