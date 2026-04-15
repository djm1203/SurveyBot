# SurveyBot — Architecture, Implementation & Research Documentation

**Baylor University | Senior Capstone | Cybersecurity Red Team Track**  
**Team:** Derek Martinez et al.  
**Target System:** Qualtrics Survey Platform (SV_6GagF9EpumzN06W)

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Threat Model & Motivation](#2-threat-model--motivation)
3. [System Architecture](#3-system-architecture)
4. [Layer 1 — Stealth Browser](#4-layer-1--stealth-browser)
5. [Layer 2 — Survey Navigation](#5-layer-2--survey-navigation)
6. [Layer 3 — Human Simulation](#6-layer-3--human-simulation)
7. [Detection Vectors & Mitigations](#7-detection-vectors--mitigations)
8. [Dependencies & Packages](#8-dependencies--packages)
9. [Key Design Decisions & Tradeoffs](#9-key-design-decisions--tradeoffs)
10. [Qualtrics-Specific Findings](#10-qualtrics-specific-findings)
11. [Configuration & Tunability](#11-configuration--tunability)
12. [Known Limitations](#12-known-limitations)
13. [Running the Bot](#13-running-the-bot)

---

## 1. Project Overview

SurveyBot is a browser automation tool built to demonstrate that a Qualtrics survey used in an academic study is **vulnerable to automated ballot-stuffing** — and to measure how detectable that automation is against the platform's native defenses.

The bot submits a 5-question Qualtrics form repeatedly, each time appearing as a unique human user. It is not a general-purpose scraper; every design decision is oriented around **evading behavioral and fingerprint-based bot detection** while correctly filling out a realistic survey response.

**Survey questions targeted:**
1. First name (text input)
2. Last name (text input)
3. Email address (text input)
4. Major (radio button — multiple CS track options)
5. Excitement level (custom drag slider, 0–10)

**Research question:** Can an automated submission bot evade Qualtrics's RelevantID and browser fingerprinting systems well enough to produce responses that are indistinguishable from real human responses?

---

## 2. Threat Model & Motivation

### Why Qualtrics surveys are a target

Academic surveys frequently inform real decisions — course offerings, program funding, student satisfaction scores. Qualtrics is the dominant platform. If the platform's bot detection can be defeated, the integrity of survey-based research is at risk.

### What Qualtrics defends against

Qualtrics uses **RelevantID**, a third-party fraud detection system embedded in every survey. RelevantID collects:

- Browser fingerprint (canvas hash, WebGL renderer, fonts, screen metrics)
- Behavioral signals (time-on-page, mouse movement patterns, keystroke timing)
- Duplicate detection (cookie/localStorage fingerprint per submission)
- IP reputation

A naive bot is trivially caught: identical fingerprint across runs, no mouse movement, instant form completion, same email address.

### Our approach

Rather than attacking Qualtrics directly, we build a bot that **genuinely looks like a human** at every layer the detection system can observe. The philosophy is defense-by-imitation, not evasion-by-obfuscation.

---

## 3. System Architecture

The bot is organized into three independent layers, each responsible for a distinct deception concern.

```
main.py  (orchestrator — runs N independent submissions)
│
├── LAYER 1 — Stealth Browser
│    ├── stealth.py       Browser launch, context isolation, fallback chain
│    └── fingerprint.py   Per-run browser identity (UA, screen, locale, timezone)
│
├── LAYER 2 — Survey Navigation
│    ├── bot.py           DOM analysis, question type dispatch, page flow
│    ├── answers.py       Answer generation (names, email, choices, slider)
│    └── branching.py     Completion detection, conditional question handling
│
└── LAYER 3 — Human Simulation
     ├── human_sim.py     Keystroke profile replay, reading pauses, click timing
     └── mouse.py         Bezier-curve mouse movement
```

### File responsibilities at a glance

| File | Lines | Responsibility |
|------|-------|----------------|
| `main.py` | ~267 | Orchestrates N runs; CLI prompt; inter-run gaps |
| `stealth.py` | ~181 | Browser launch with anti-detection; context isolation |
| `fingerprint.py` | ~163 | Consistent per-run browser identity generation |
| `bot.py` | ~520 | Question type detection and dispatch; page navigation |
| `answers.py` | ~235 | Pure Python answer generation; field classification |
| `branching.py` | ~146 | Survey completion detection; new-question handling |
| `human_sim.py` | ~260 | Keystroke replay; behavioral pacing |
| `mouse.py` | ~168 | Cubic Bezier mouse movement |
| `config.py` | ~40 | All tunable timing and URL constants |
| `recorder.py` | — | Captures real human typing profiles for replay |

---

## 4. Layer 1 — Stealth Browser

### 4.1 Browser Selection — Graceful Degradation

Three-tier fallback so the bot works even when optional packages are missing:

```
1st choice:  Camoufox (patched Firefox)              ← primary
2nd choice:  Playwright Firefox + playwright-stealth  ← JS-level patches
3rd choice:  Plain Playwright Firefox                 ← last resort
```

**Why Firefox over Chrome?**  
Chromium-based automation is heavily targeted by detection libraries (FingerprintJS, BotD, Cloudflare). Firefox has a lower automation signal baseline, and Camoufox patches it at the C++ level — something no JS shim can fully replicate for Chrome.

### 4.2 Camoufox

Camoufox is a Playwright-compatible fork of Firefox that removes automation artifacts at the browser engine level:

- `navigator.webdriver` is `undefined` (not `true`)
- Canvas and WebGL fingerprints are noise-injected to look like real hardware
- AudioContext fingerprint is spoofed
- Font enumeration is realistic for the target OS
- No headless-mode timing quirks

Key parameters used in `stealth.py`:

```python
Camoufox(
    headless=False,
    os="windows",           # Drives BrowserForge fingerprint selection
    locale="en-US",
    window=(1366, 768),     # Sets actual OS window size — prevents oversized windows
)
```

> **Discovery:** `window=(w, h)` is required to match the window to the viewport fingerprint. Without it, Camoufox uses BrowserForge's randomly selected monitor size (often 1920×1080+), making the bot visually obvious and potentially causing layout-dependent slider interactions to fail.

### 4.3 Per-Run Context Isolation

Each submission gets a **fresh browser context** (`browser.new_context()`), not a new browser process.

```python
context = browser.new_context(
    viewport={"width": w, "height": h},
    locale="en-US",
    timezone_id="America/Chicago",
)
page = context.new_page()
```

**Why this matters for RelevantID:**  
RelevantID identifies repeat respondents through a combination of localStorage tokens, cookies, and canvas fingerprint. A new context has no prior cookies, no storage, and Camoufox injects fresh canvas noise — so each run appears as a completely new device from RelevantID's perspective.

### 4.4 Browser Fingerprint Generation (`fingerprint.py`)

Every run generates a distinct, internally-consistent "person" identity:

| Field | Source | Example |
|-------|--------|---------|
| User agent | BrowserForge → manual fallback | `Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Gecko/20100101 Firefox/134.0` |
| Viewport / screen | Curated pool of real laptop resolutions | 1366×768, 1440×900, 1280×800 |
| Locale + timezone | Paired tuples (never inconsistent) | `en-US` + `America/Chicago` |
| Navigator platform | Matched to OS choice | `Win32`, `MacIntel`, `Linux x86_64` |
| Firefox version | Pool of current stable/ESR versions | 128–138 |

**OS distribution** is weighted to match real-world browser share:
- Windows: 72%
- macOS: 19%
- Linux: 9%

**Why consistency matters:** Fingerprinting systems correlate fields. A Windows user agent paired with a Mac platform string, or a US locale with a European timezone, are immediate red flags. The paired-tuple design ensures all fields agree.

---

## 5. Layer 2 — Survey Navigation

### 5.1 Question Type Dispatcher (`bot.py`)

The bot detects question types from the DOM rather than hard-coding the survey structure. This makes it portable to any Qualtrics survey.

Detection is evaluated in priority order (order matters — see §10 for why):

```
input[type='text']                    → handle_text_input
textarea                              → handle_textarea
[role='slider'] / .QQSL-* / .QSlider → handle_slider    ← checked BEFORE radio
input[type='radio'] / .ChoiceStructure→ handle_radio
input[type='checkbox']                → handle_checkbox
select                                → handle_dropdown
```

### 5.2 Field Classification & Answer Generation (`answers.py`)

Text fields are classified by their question label before an answer is generated:

```python
def classify_text_field(label: str) -> str:
    if "email" in label:      return "email"
    if "first" in label:      return "first_name"
    if "last" in label:       return "last_name"
    if "name" in label:       return "first_name"   # bare "name" field
    return "generic"
```

**Name/email consistency:** The first name generated for Q1 is cached (`self._first_name`) and reused when building the Q3 email address. This produces realistic address patterns like `kimberly.johnson21339@gmail.com` rather than mismatched names.

**Multiple-choice filtering:** `select_choice()` applies two filter layers:
- **Forbidden** (`"other"`, `"please specify"`, `"write in"`) — these trigger mandatory text fields the bot cannot fill
- **Exclusive** (`"prefer not to say"`, `"n/a"`) — selected with 20% probability for realism

**Slider distribution:** Values are Gaussian-distributed around the midpoint (std = range/4), avoiding the bot-giveaway of always picking 5 or always picking 10.

### 5.3 Email Address Strategy

Two modes configurable at runtime:

| Mode | Behavior | Use case |
|------|----------|----------|
| `prefix` | `surveybot{10000-99999}@{domain}` | Easy to grep in Qualtrics export; varies per run |
| `fixed` | Always returns `BOT_EMAIL` from config | Controlled testing; easy to filter |

90,000 suffix combinations × 7 domains = 630,000 unique addresses before theoretical collision.

### 5.4 Survey Completion Detection (`branching.py`)

Three independent signals checked in order:

1. **URL pattern** — `SE=` or `SurveyRetire` in URL (Qualtrics's native end-of-survey redirect)
2. **Body text scan** — checks for phrases like `"thank you"`, `"your response has been recorded"`, `"end of survey"`
3. **No navigation buttons** — both `#NextButton` and `#submitButton` absent after page settles, confirmed by URL match

**Why three signals?** Qualtrics offers custom end-of-survey redirects, embedded survey modes, and white-label deployments — each may use a different completion signal. Multiple fallbacks ensure the bot stops cleanly regardless of survey configuration.

### 5.5 Page Transition Handling

Qualtrics is a JavaScript SPA. Page transitions are not real navigations — the DOM mutates in place while a `#SkinContent.LoadingPage` overlay is shown. The bot handles this in two places:

```python
# After clicking Next
page.wait_for_load_state("load")
_wait_for_qualtrics_transition()   # waits for LoadingPage overlay to appear and vanish

# On initial page load
page.wait_for_selector("#NextButton, div.QuestionOuter", timeout=15_000)
```

Without the explicit selector wait on initial load, the main loop spins 6–10 times in under 2 seconds before Qualtrics finishes rendering — burning time and generating anomalous behavior patterns.

---

## 6. Layer 3 — Human Simulation

### 6.1 Keystroke Dynamics Replay (`human_sim.py` + `recorder.py`)

The most sophisticated behavioral layer in the system.

**Phase 1 — Recording:**  
Team members run `recorder.py` and type a standard sample paragraph. Every keypress is timestamped. The system extracts per-person statistics:

```json
{
  "profile": {
    "mean_flight": 91.4,
    "std_flight": 42.1,
    "mean_dwell": 117.2,
    "std_dwell": 38.6,
    "n_keystrokes": 847
  }
}
```

- **Flight time**: milliseconds between releasing key N and pressing key N+1
- **Dwell time**: milliseconds a key is held down

**Phase 2 — Playback:**  
Each bot run randomly selects one profile from `keystrokes/`. Every character typed samples a delay from `Gauss(mean_flight, std_flight)` — reproducing the natural variation of that person's typing rhythm.

```python
for char in text:
    flight_ms = random.gauss(profile["mean_flight"], profile["std_flight"])
    page.keyboard.type(char)
    page.wait_for_timeout(max(20, min(600, flight_ms)))
```

**Why this matters:** Bot detection systems that analyze keystroke dynamics look for uniform inter-key spacing and abnormally consistent timing. Real humans accelerate on familiar bigrams (e.g., `th`, `er`) and slow on uncommon ones. Replaying a real person's profile reproduces these micro-patterns.

### 6.2 Bezier-Curve Mouse Movement (`mouse.py`)

Real human mouse paths are curved, with slight overshoots and hand tremor. Straight-line movement between elements is a known bot signal.

**Implementation:**

```
P0 ─────────── P1
 \              \
  \    curve     \
   P2 ──────────── P3 (target)
```

Four control points define a cubic Bezier curve:
- P0: current tracked position
- P1/P2: randomly offset perpendicular to the straight-line path (the "bow")
- P3: target element center

30–50 intermediate points are traced along the curve, each with ±0.4px Gaussian noise simulating hand tremor. Total move duration: 200–600ms (randomized per move).

The module tracks cursor position independently since Playwright's sync API does not expose current mouse coordinates.

### 6.3 Behavioral Pacing

All timing constants are Gaussian-distributed rather than uniform — uniform distributions are statistically distinguishable from human timing.

| Pause type | When | Duration |
|------------|------|----------|
| Reading pause | Before clicking Next | `Gauss(0.6 × n_questions, 0.2 × n_questions)` seconds |
| Pre-click pause | Before each button/label click | `Gauss(300ms, 100ms)` |
| Inter-action pause | Between individual answer interactions | Uniform `[150ms, 500ms]` |
| Inter-run gap | Between full submissions | Uniform `[3s, 8s]` |

Reading pauses scale with the number of visible questions, mirroring how humans take longer to read pages with more content. Pages with zero visible questions (loading screens, consent pages) are detected and skipped immediately.

---

## 7. Detection Vectors & Mitigations

| Detection Vector | Risk Without Mitigation | Mitigation Applied | Layer |
|-----------------|------------------------|-------------------|-------|
| `navigator.webdriver` flag | Immediate detection | Camoufox C++ patch | 1 |
| Canvas fingerprint | Duplicate detection across runs | Camoufox noise injection | 1 |
| WebGL renderer string | Hardware ID fingerprinting | Camoufox spoofing | 1 |
| User agent / platform mismatch | Inconsistency flag | Paired fingerprint generation | 1 |
| Screen resolution implausibility | Automated heuristics | Curated real-device resolution pool | 1 |
| Stale Firefox version | Anomaly detection | Version pool kept current (128–138) | 1 |
| RelevantID duplicate token | Same-device detection | Per-run browser context isolation | 1 |
| Same email address | Trivial duplicate filter | 630K-combination prefix+suffix mode | 2 |
| Bot-typed form fields | Uniform timing detection | Keystroke profile replay | 3 |
| Straight-line mouse movement | Movement linearity detection | Bezier-curve mouse paths | 3 |
| Instant form completion | Time-on-page analysis | Gaussian-distributed pacing delays | 3 |
| Keyboard-only slider interaction | Missing mouse event | Mouse click on slider track | 2 |
| IP-based rate limiting | Submission burst flagging | Inter-run delays; single IP limitation | — |

---

## 8. Dependencies & Packages

### Runtime Dependencies

| Package | Version | Role |
|---------|---------|------|
| `camoufox` | latest | Patched Firefox browser with anti-detection at engine level |
| `playwright` | ≥1.38 | Browser automation API (sync) |
| `playwright-stealth` | latest | JS-level stealth patches (fallback mode only) |
| `browserforge` | bundled with camoufox | Statistical browser fingerprint generation |

### Standard Library (no install needed)

| Module | Used for |
|--------|----------|
| `random` | All stochastic sampling — timing, choices, fingerprints |
| `json` | Loading keystroke profiles from `keystrokes/` |
| `logging` | Structured per-module logs |
| `pathlib` | Cross-platform file paths for keystroke profiles |
| `re` | Email address sanitization in `answers.py` |
| `time` | Inter-run sleep (stdlib fallback for pre-click pause) |

### Dev / Recording

| Tool | Purpose |
|------|---------|
| `recorder.py` | Keystroke timing capture (run once per team member) |
| `keyboard` or `pynput` | Keypress event listening during recording |

---

## 9. Key Design Decisions & Tradeoffs

### Architecture: Sync Playwright over async

**Decision:** Use `playwright.sync_api` throughout.  
**Rationale:** The bot runs one page at a time in a sequential flow. Async adds complexity (event loops, coroutines) with no benefit for a single-threaded, single-page use case. Camoufox's sync API is also more mature.

### Layer separation

**Decision:** `bot.py` has zero knowledge of stealth or fingerprinting. `stealth.py` has zero knowledge of survey content.  
**Rationale:** Each layer can be tested and debugged independently. `bot.py` can be pointed at any Playwright page. `stealth.py` can wrap any bot.

### Graceful degradation (Camoufox → Playwright+stealth → Playwright)

**Decision:** Three fallback levels rather than hard-requiring Camoufox.  
**Rationale:** Camoufox requires a separate install; teammates may run the bot without it. The fallback chain ensures the bot always runs, with lower stealth guarantees noted in the log.

### Per-run context isolation vs. per-run browser restart

**Decision:** New context per run, not new browser process.  
**Rationale:** A new browser process takes 10–30 seconds and leaves OS-level artifacts (process IDs, crash reports). A new context takes <1 second and fully resets the web-visible state that RelevantID observes.

### Dispatch order: slider before radio

**Decision:** Slider detection runs before radio detection in `_dispatch_question`.  
**Rationale:** Qualtrics renders its custom slider inside a container that also contains `.ChoiceStructure` elements. If radio is checked first, the slider container is misidentified as a radio question and the slider is never answered — causing silent validation failure.

### Mouse click (not keyboard) for slider interaction

**Decision:** Use `page.mouse.click(x, y)` on the slider track; never keyboard arrow keys.  
**Rationale:** Discovered through testing — Qualtrics's custom drag slider marks a question as "answered" in its internal response engine only when a `mousedown`+`mouseup` event fires on the track. Keyboard focus + arrow keys move the visual handle but leave the question flagged as unanswered, causing the page to fail validation on Next and loop.

### `check(force=True)` for radio and checkbox inputs

**Decision:** Call `.check(force=True)` on the hidden `<input>` after clicking the visible label.  
**Rationale:** Qualtrics hides the real `<input type="radio">` element and renders a styled `<span>`. Playwright refuses to interact with hidden elements by default. `force=True` bypasses the visibility check; the label click handles the UI JS while `check(force=True)` ensures the input's `.checked` property is set for Playwright's own state tracking.

### Config-driven timing

**Decision:** All timing constants live in `config.py`, none are hardcoded.  
**Rationale:** Speed vs. stealth is a tunable tradeoff. Fast runs (~20s each) are useful for testing; slower runs with higher variance look more human for production use.

---

## 10. Qualtrics-Specific Findings

These were discovered by inspecting live DOM during development — they are not documented by Qualtrics and required empirical testing to diagnose.

### Finding 1: Hidden radio inputs
Qualtrics renders radio buttons as styled `<span>` elements; the real `<input type="radio">` is set to `visibility: hidden`. Standard Playwright click on the label triggers Qualtrics's UI JavaScript but does not set the input's `.checked` property. `check(force=True)` is required as a belt-and-suspenders.

### Finding 2: Slider requires mouse event
The Qualtrics drag slider (`[role='slider']`) responds to keyboard arrow keys for visual positioning, but the `onChange` handler that writes the response to Qualtrics's internal model only fires on mouse events. A bot that uses keyboard interaction passes visual inspection but produces an unanswered question in Qualtrics's validation layer.

### Finding 3: LoadingPage overlay timing
Between pages, Qualtrics briefly adds `class="LoadingPage"` to `#SkinContent`. This overlay can disappear in under 100ms on fast connections — faster than `wait_for_load_state("domcontentloaded")` resolves. Without waiting for this overlay, the bot may query the old DOM during the transition and either mis-detect completion or attempt to fill already-submitted fields.

### Finding 4: SPA initial render delay
After `page.goto()`, `wait_for_load_state("domcontentloaded")` resolves while the page is still a blank white screen. Qualtrics's SPA JavaScript then fetches the survey definition and renders it — this can take 1–4 seconds on a normal connection. Without an explicit `wait_for_selector("#NextButton, div.QuestionOuter")`, the main loop spins 6–10 empty iterations.

### Finding 5: `.ChoiceStructure` inside slider containers
Qualtrics wraps its slider inside a `div.QuestionOuter` that also contains `.ChoiceStructure` child elements (used for label rendering). Any radio detection heuristic that checks for `.ChoiceStructure` inside a question container will false-match the slider question. The slider check must run before the radio check.

---

## 11. Configuration & Tunability

All runtime-tunable values live in `config.py`:

```python
SURVEY_URL = "https://baylor.qualtrics.com/jfe/form/SV_6GagF9EpumzN06W"
RUN_COUNT  = 1
BOT_EMAIL_MODE   = "prefix"   # "prefix" | "fixed"
BOT_EMAIL        = "surveybot.test@gmail.com"
BOT_EMAIL_PREFIX = "surveybot"

TIMING = {
    "min_action_delay":       0.15,   # s — between answer interactions
    "max_action_delay":       0.50,
    "click_mean":             0.30,   # s — Gaussian pre-click pause
    "click_std":              0.10,
    "read_per_question_mean": 0.60,   # s per question — reading pause scale
    "read_per_question_std":  0.20,
    "next_button_min":        0.40,   # s — pause before hitting Next
    "next_button_max":        1.00,
    "page_load_timeout_ms":   15_000, # ms — max wait for page load
}
```

**Speed vs. stealth tuning:**  
Cutting `read_per_question_mean` from 1.5 → 0.6 reduced a 5-question page pause from ~7.5s to ~3s. Current settings produce a run time of ~25–40 seconds per submission — fast enough for a 20-run test session while remaining within plausible human page-reading speed.

---

## 12. Known Limitations

### IP-based detection (unmitigated)
All submissions come from the same IP address. A Qualtrics administrator can trivially filter by IP in the response data. Mitigation would require a rotating proxy pool, which was out of scope for this capstone.

### Single-machine only
The bot requires a local Firefox install and runs headfully (non-headless). It cannot be deployed serverlessly or distributed across machines without additional infrastructure.

### Keystroke profiles are thin
Only 2 real human profiles have been recorded (`person_01.json`, `person_04.json`). A statistical analysis across many runs would reveal that timing patterns cluster around two distributions. Minimum recommended: 5–8 distinct profiles.

### No CAPTCHA handling
If Qualtrics enables CAPTCHA challenges (not present in the test survey), the bot has no mechanism to solve them. Camoufox's clean fingerprint reduces the likelihood of CAPTCHA triggers, but does not eliminate them.

### Qualtrics survey-specific DOM assumptions
The question dispatcher is heuristic — it relies on Qualtrics's standard DOM structure. Custom survey themes or Qualtrics updates that change class names could break detection. The selector lists in `bot.py` would need updating.

---

## 13. Running the Bot

```bash
# Install dependencies
pip install camoufox playwright playwright-stealth
playwright install firefox

# Record a keystroke profile (run once per team member)
python recorder.py
# Follow prompts — output saved to keystrokes/person_XX.json

# Run the bot
python main.py
# Prompts for: survey URL, number of runs, email mode
```

**Recommended test procedure:**
1. Set `RUN_COUNT = 3` for a quick smoke test
2. Check Qualtrics response data to verify submissions appear
3. Note whether RelevantID flags any responses
4. Increase `RUN_COUNT` for volume testing

**Log interpretation:**
```
[fingerprint] Manual: ...     ← BrowserForge not installed; using fallback pool
[stealth] Launched Camoufox  ← Primary browser active
[bot] ── Page 1 ──            ← Bot entered main loop
[bot] 0 question container(s) ← SPA still rendering; bot is waiting
[bot] 5 question container(s) ← Survey form loaded
[bot] Radio: CS - General     ← Major selected
[bot] Slider (click at 0.54)  ← Excitement level set
[branching] Complete — phrase ← "thank you" found; run ended
```
