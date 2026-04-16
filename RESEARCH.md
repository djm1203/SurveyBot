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

**Research question:** Can an automated submission bot evade Qualtrics's fingerprinting and behavioral biometric systems well enough to produce responses that are indistinguishable from real human responses?

---

## 2. Threat Model & Motivation

### Why Qualtrics surveys are a target

Academic surveys frequently inform real decisions — course offerings, program funding, student satisfaction scores. Qualtrics is the dominant platform. If the platform's bot detection can be defeated, the integrity of survey-based research is at risk.

### What Qualtrics defends against

Qualtrics embeds multiple fraud detection layers in every survey:

- **Q_DuplicateRespondent** (replaced RelevantID in June 2025) — browser fingerprint hash stored in localStorage; detects repeat submissions from the same device
- **reCAPTCHA v3** (Q_RecaptchaScore) — Google's risk scorer based on browsing history, cookies, and behavioral signals; sessions without history score 0.1–0.3
- **LegacyTextAnalytics** — per-field keystroke event collection: `keystrokeCount`, `pasteCount`, `totalTime`, average inter-key interval
- **CustomJS behavioral biometrics** — survey-embedded script that evaluates: honeypot field fill, average typing speed < 120ms threshold, mouse path efficiency > 0.99 (near-perfect straight-line), mouse velocity standard deviation < 0.02 (suspiciously uniform)

A naive bot is trivially caught: identical fingerprint across runs, no mouse movement, instant form completion, paste-filled text fields, same email address.

### Our approach

Rather than attacking Qualtrics directly, we build a bot that **genuinely looks like a human** at every layer the detection system can observe. The philosophy is defense-by-imitation, not evasion-by-obfuscation.

---

## 3. System Architecture

The bot is organized into three independent layers, each responsible for a distinct deception concern.

```
main.py  (orchestrator — runs N independent submissions)
│
├── LAYER 1 — Stealth Browser
│    ├── stealth.py       Browser launch, context isolation, storage_state restore
│    ├── fingerprint.py   Per-run browser identity (UA, screen, locale, timezone)
│    └── warm_profile.py  Pre-warms browser profile with realistic browsing history
│
├── LAYER 2 — Survey Navigation
│    ├── bot.py           DOM analysis, question type dispatch, page flow
│    ├── answers.py       Answer generation (names, email, choices, slider)
│    └── branching.py     Completion detection, conditional question handling
│
└── LAYER 3 — Human Simulation
     ├── human_sim.py     Keystroke profile replay, reading pauses, scroll simulation
     └── mouse.py         WindMouse physics engine — gravity + wind + overshoot
```

### File responsibilities at a glance

| File | Lines | Responsibility |
|------|-------|----------------|
| `main.py` | ~307 | Orchestrates N runs; CLI prompt; inter-run gaps; warmed profile lookup |
| `stealth.py` | ~249 | Browser launch with anti-detection; context isolation; storage_state restore |
| `fingerprint.py` | ~163 | Consistent per-run browser identity generation |
| `warm_profile.py` | ~120 | One-time browser pre-warming for reCAPTCHA v3 score improvement |
| `bot.py` | ~530 | Question type detection and dispatch; page navigation; honeypot check |
| `answers.py` | ~260 | Pure Python answer generation; field classification; free-text pool |
| `branching.py` | ~146 | Survey completion detection; new-question handling |
| `human_sim.py` | ~320 | Keystroke replay; flight-time offset; scroll simulation; behavioral pacing |
| `mouse.py` | ~220 | WindMouse physics engine (gravity + wind + overshoot + correction) |
| `config.py` | ~47 | All tunable timing and URL constants |
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

A canvas hash probe runs immediately after context creation and is logged at DEBUG level:

```
[stealth] Canvas hash tail: pggMjosAAAAASUVORK5CYII=
```

Comparing this tail across runs confirms Camoufox noise injection is rotating the canvas hash. Identical tails across runs would mean Q_DuplicateRespondent could link them via canvas fingerprint.

### 4.3 Per-Run Context Isolation + Warmed Profile Restore

Each submission gets a **fresh browser context** (`browser.new_context()`), not a new browser process.

```python
context = browser.new_context(
    viewport={"width": w, "height": h},
    locale="en-US",
    timezone_id="America/Chicago",
    storage_state="profiles/warmed_profile_20260415_150227.json",  # optional
)
page = context.new_page()
```

**Why this matters for Q_DuplicateRespondent:**  
Q_DuplicateRespondent identifies repeat respondents through a combination of localStorage tokens, cookies, and canvas fingerprint. A new context has no prior cookies, no storage, and Camoufox injects fresh canvas noise — so each run appears as a completely new device.

**Why `storage_state` matters for reCAPTCHA v3:**  
reCAPTCHA v3 scores a session based on Google cookie presence, browsing history, and behavioral signals. A zero-history fresh context scores 0.1–0.3 regardless of how human the behavior looks. Loading a pre-warmed profile restores Google cookies and site visit history, pushing scores into the 0.7–0.9 range typical of real users.

**`warm_profile.py`** — run once before a bot session to create the profile:

```
Camoufox launches → visits Google → YouTube → Wikipedia → AP News → BBC
  Human scroll + mouse events on each site
  Saves context.storage_state() → profiles/warmed_profile_TIMESTAMP.json
```

`main.py` picks the most recently saved profile automatically (`profiles/warmed_profile_*.json` sorted by name descending).

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

> **BrowserForge API note:** BrowserForge ≥1.0 changed the `browser` parameter from a list of tuples to a plain string. Using `browser=[("firefox", "*")]` raises `AttributeError: 'tuple' object has no attribute 'name'`. The correct call is `browser="firefox"`.

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

**Name/email consistency:** The first name generated for Q1 is cached (`self._first_name`) and reused when building the Q3 email address. This produces realistic address patterns like `kimberly.johnson21@gmail.com` rather than mismatched names.

**Multiple-choice filtering:** `select_choice()` applies two filter layers:
- **Forbidden** (`"other"`, `"please specify"`, `"write in"`) — these trigger mandatory text fields the bot cannot fill
- **Exclusive** (`"prefer not to say"`, `"n/a"`) — selected with 20% probability for realism

**Slider distribution:** Values are Gaussian-distributed around the midpoint (std = range/4), avoiding the bot-giveaway of always picking 5 or always picking 10.

**Free-text pool:** Generic fields draw from a 30-entry pool of realistic academic comments to produce varied, human-sounding responses rather than a repeated static string.

### 5.3 Email Address Strategy

Three modes configurable at runtime via CLI:

| Mode | Behavior | Use case |
|------|----------|----------|
| `natural` | `{firstname}.{lastname}{suffix}@{domain}` | Production runs — realistic addresses indistinguishable from real users |
| `prefix` | `surveybot{10000–99999}@{domain}` | Testing — easy to grep in Qualtrics export for bot identification |
| `fixed` | Always returns `BOT_EMAIL` from config | Controlled testing; easy to filter |

**Natural mode** generates email addresses that match the first/last name already used for Q1/Q2, e.g. `donna.perez55@yahoo.com`. The suffix is a random 2-digit number and the domain is drawn from a pool of 10 common providers (gmail, yahoo, outlook, hotmail, msn, aol, live, me, icloud, protonmail).

Natural mode addresses cannot be identified by a single export grep, unlike prefix mode. 90,000 suffix combinations × 10 domains = 900,000 unique addresses before theoretical collision.

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
_wait_for_page_ready()         # unconditionally waits for LoadingPage overlay to clear

# On initial page load
page.wait_for_selector("#NextButton, div.QuestionOuter", timeout=15_000)
```

`_wait_for_page_ready()` is called at the top of every page loop iteration, not just after a Next click. This prevents the bot from interacting with a stale DOM during the transition window, which was causing silent click failures on slow connections.

### 5.6 Honeypot Detection

The survey's CustomJS injects a hidden `#honey_trap` input. Any content in this field at submission time is a guaranteed bot flag. The bot checks it explicitly after answering all questions on a page:

```python
honeypot = self.page.locator("#honey_trap")
if honeypot.count() > 0:
    val = honeypot.input_value()
    if val:
        logger.error(f"[bot] HONEYPOT FILLED — value: '{val}' — this run will be flagged")
```

The check runs before clicking Next so the log captures the exact value that was filled, making it easy to trace which interaction polluted the field.

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

**Flight-time offset — detection threshold bypass:**  
The recorded profiles have raw mean flight times of 91–96ms. The Qualtrics CustomJS flags any submission where `avg_speed < 120ms` as a bot signal. Rather than re-recording at a slower pace, a global `_FLIGHT_OFFSET_MS = 50.0` is added to every sampled interval at playback time:

```python
_FLIGHT_OFFSET_MS: float = 50.0   # shifts 91–96ms profiles to 141–146ms effective

def _sample_flight_ms() -> float:
    raw = random.gauss(mean, std) + _FLIGHT_OFFSET_MS
    return max(60.0, min(600.0, raw))
```

This shifts the effective average to 141–146ms — safely above the 120ms threshold — while preserving the natural variance pattern of each individual profile. The effective rate is logged explicitly:

```
[human_sim] Loaded profile 'person_04.json' — mean flight: 92ms (effective: 142ms after +50ms offset), mean dwell: 115ms
```

**Fall-back warning:**  
If `_type_text()` is forced to use `.fill()` (e.g. when `press_sequentially` raises), a WARNING is emitted:

```
[bot] _type_text fell back to .fill() — LegacyTextAnalytics will record keystrokeCount=0 / pasteCount=1
```

This makes paste-detection failures visible in the log immediately.

### 6.2 WindMouse Physics Engine (`mouse.py`)

Real human mouse movement follows physics: there is momentum, slight overshoots, and a correction phase. Straight-line or uniform-velocity movement is a known bot signal; Bezier curves improve on this but still lack authentic physics. The system was rewritten to use the **WindMouse algorithm**:

```
Parameters:
  gravity  = 9.0   — pull toward the target (increases with distance)
  wind     = 3.0   — random lateral turbulence
  max_step = 12.0  — velocity cap to prevent teleportation

Each iteration:
  dist    = sqrt((tx-x)² + (ty-y)²)
  wdist   = min(dist, sqrt(3×max_step)) × wind × random.gauss(0,1)
  vx     += (gravity × (tx-x)/dist) + (wdist × random.gauss(0,1))
  vy     += (gravity × (ty-y)/dist) + (wdist × random.gauss(0,1))
  speed   = sqrt(vx² + vy²)
  if speed > max_step: vx, vy = vx/speed×max_step, vy/speed×max_step
  x, y   += vx, vy + micro-jitter(Gauss 0, 0.4)
  page.mouse.move(x, y)
  wait(Uniform[1ms, 6ms])
```

This produces trajectories with realistic curvature, acceleration, and deceleration — matching the physical motor control pattern described in Fitts's Law studies.

**Overshoot + correction pattern:**  
After reaching the target, the engine simulates a slight overshoot (5–12% of travel distance past the target) and a 60–160ms correction back. This matches the motor-correction behavior seen in human mouse tracking data and defeats path-efficiency detectors (`efficiency > 0.99` flag).

**Velocity standard deviation:**  
The random wind term and micro-jitter ensure velocity varies significantly across the path. This defeats velocity uniformity detectors (`velocity_stddev < 0.02` flag).

**Page-close resilience:**  
The inner loop wraps each `page.mouse.move()` call in a try/except. When Qualtrics closes the page mid-interaction (e.g. after submission), the mouse thread exits immediately instead of blocking for 30+ seconds.

Public API is unchanged from the previous Bezier implementation: `bezier_click`, `bezier_move`, `reset_position`.

### 6.3 Page Scroll Simulation (`human_sim.py`)

Every page load triggers a `simulate_page_scroll()` call before any answers are filled. This generates scroll events that reCAPTCHA v3 and behavioral biometrics expect to see from a reading user:

```python
def simulate_page_scroll(page) -> None:
    n_scrolls = random.randint(2, 6)
    for _ in range(n_scrolls):
        direction = 1 if random.random() < 0.78 else -1   # mostly down
        delta = random.randint(60, 300) * direction
        page.mouse.move(random.randint(200, 900), random.randint(150, 500))
        page.mouse.wheel(0, delta)
        page.wait_for_timeout(max(80, int(random.gauss(380, 100))))
```

The 78% downward bias matches natural reading scroll behavior. Random mouse repositioning before each wheel event adds realistic context.

### 6.4 Behavioral Pacing

All timing constants are Gaussian-distributed rather than uniform — uniform distributions are statistically distinguishable from human timing.

| Pause type | When | Duration |
|------------|------|----------|
| Reading pause | Before clicking Next | `Gauss(3.0 × n_q, 0.9 × n_q)` seconds |
| Pre-click pause | Before each button/label click | `Gauss(600ms, 150ms)` |
| Inter-action pause | Between individual answer interactions | Uniform `[500ms, 2000ms]` |
| Inter-run gap | Between full submissions | Uniform `[30s, 90s]` |

Reading pauses scale with the number of visible questions, mirroring how humans take longer to read pages with more content. The 30–90s inter-run gap spreads submissions across time to avoid burst-detection signals in Qualtrics's server-side logs.

**Q_TotalDuration monitoring:**  
`main.py` tracks wall-clock time per run and logs the result. A warning fires if completion takes less than 30 seconds:

```
[main] Estimated Q_TotalDuration: 38.2s
```

---

## 7. Detection Vectors & Mitigations

| Detection Vector | Risk Without Mitigation | Mitigation Applied | Layer |
|-----------------|------------------------|-------------------|-------|
| `navigator.webdriver` flag | Immediate detection | Camoufox C++ patch | 1 |
| Canvas fingerprint consistency | Q_DuplicateRespondent links runs | Camoufox noise injection (verified via hash probe) | 1 |
| WebGL renderer string | Hardware ID fingerprinting | Camoufox spoofing | 1 |
| User agent / platform mismatch | Inconsistency flag | Paired fingerprint generation | 1 |
| Screen resolution implausibility | Automated heuristics | Curated real-device resolution pool | 1 |
| Stale Firefox version | Anomaly detection | Version pool kept current (128–138) | 1 |
| Q_DuplicateRespondent token | Same-device detection | Per-run browser context isolation | 1 |
| reCAPTCHA v3 cold context (0.1–0.3) | Low trust score flags submission | Warmed profile with Google cookies + browsing history | 1 |
| Recognizable bot email pattern | Single grep identifies all runs | Natural name-based email mode; 900K combinations | 2 |
| Same email address every run | Trivial duplicate filter | All three modes vary per run | 2 |
| Honeypot field filled | CRITICAL bot flag in CustomJS | Explicit check + ERROR log before Next click | 2 |
| Paste-filled text fields | LegacyTextAnalytics pasteCount=1 | `press_sequentially` keystroke-by-keystroke; fill() triggers warning | 3 |
| Typing avg_speed < 120ms | CustomJS biometric threshold | `_FLIGHT_OFFSET_MS = 50ms` shifts effective average to 141–146ms | 3 |
| Zero scroll events | reCAPTCHA v3 passive signal | `simulate_page_scroll()` on every page load | 3 |
| Straight-line mouse movement | Path efficiency > 0.99 flag | WindMouse gravity + wind turbulence | 3 |
| Uniform mouse velocity | Velocity stddev < 0.02 flag | WindMouse random wind term + micro-jitter | 3 |
| No overshoot on mouse movement | Inhuman precision | WindMouse overshoot + correction pattern | 3 |
| Instant form completion | Q_TotalDuration outlier | Gaussian-distributed pacing; 30s minimum monitored | 3 |
| Submission burst pattern | Server-side rate signal | 30–90s randomized inter-run gap | 3 |
| Keyboard-only slider interaction | Missing mousedown event | Bounding-box `mouse.click()` on slider track | 2 |

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
| `pathlib` | Cross-platform file paths for keystroke profiles and warmed profiles |
| `re` | Email address sanitization in `answers.py` |
| `time` | Inter-run sleep (stdlib fallback for pre-click pause) |
| `math` | WindMouse distance and velocity calculations |

### Dev / Recording

| Tool | Purpose |
|------|---------|
| `recorder.py` | Keystroke timing capture (run once per team member) |
| `warm_profile.py` | Pre-warm browser with Google/YouTube/Wikipedia history (run before bot sessions) |
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
**Rationale:** A new browser process takes 10–30 seconds and leaves OS-level artifacts (process IDs, crash reports). A new context takes <1 second and fully resets the web-visible state that Q_DuplicateRespondent observes.

### WindMouse physics over Bezier curves

**Decision:** Replaced cubic Bezier mouse paths with the WindMouse gravity + wind algorithm, plus an overshoot-and-correct phase.  
**Rationale:** Analysis of the survey's embedded CustomJS revealed two explicit thresholds: path efficiency > 0.99 (near-straight-line) and velocity stddev < 0.02 (robotic uniformity). Bezier curves are smooth but have predictable curvature and no velocity variation. WindMouse uses stochastic wind turbulence and gravity pull that produces trajectories matching real mouse tracking data at the statistical level — efficiency < 0.95 and meaningful velocity variance across every move.

### Warmed browser profile for reCAPTCHA v3

**Decision:** Run `warm_profile.py` once before a bot session; load the saved profile via `storage_state` for each run.  
**Rationale:** reCAPTCHA v3 is a passive scorer — it evaluates the entire session history, not just behavior on the target page. A fresh context with no Google cookies always scores 0.1–0.3, below the passing threshold for many survey configurations, regardless of how realistic the bot's behavior is. A pre-warmed profile carries real cookies and browsing history, pushing scores to 0.7–0.9.

### Flight-time offset rather than re-recording profiles

**Decision:** Apply `_FLIGHT_OFFSET_MS = 50ms` globally at playback time rather than asking teammates to retype slower profiles.  
**Rationale:** The CustomJS threshold is `avg_speed < 120ms`. Recorded profiles cluster at 91–96ms — all below the threshold. Re-recording introduces human error (people unconsciously type at their natural pace) and re-profiles would need periodic updating. The offset cleanly shifts the distribution without distorting its shape: the person-specific variance, bigram acceleration patterns, and dwell-time characteristics are all preserved.

### Dispatch order: slider before radio

**Decision:** Slider detection runs before radio detection in `_dispatch_question`.  
**Rationale:** Qualtrics renders its custom slider inside a container that also contains `.ChoiceStructure` elements. If radio is checked first, the slider container is misidentified as a radio question and the slider is never answered — causing silent validation failure.

### Mouse click (not keyboard) for slider interaction

**Decision:** Use `page.mouse.click(x, y)` on the slider track; never keyboard arrow keys.  
**Rationale:** Qualtrics's custom drag slider marks a question as "answered" only when a `mousedown`+`mouseup` event fires on the track. Keyboard focus + arrow keys move the visual handle but leave the question flagged as unanswered, causing the page to fail validation on Next.

### `_human_click()` only for radio and checkbox (no `check(force=True)`)

**Decision:** Radio and checkbox interactions use only `_human_click()` on the visible label; `check(force=True)` on the hidden input was removed.  
**Rationale:** The CustomJS biometrics log pointer events. `check(force=True)` fires a synthetic programmatic event that does not carry pointer coordinates — detectable as a non-human interaction. `_human_click()` drives the WindMouse engine to the element and fires a real pointer event, which Qualtrics's event listeners receive as authentic.

### Config-driven timing

**Decision:** All timing constants live in `config.py`, none are hardcoded.  
**Rationale:** Speed vs. stealth is a tunable tradeoff. Faster timing is useful for debugging; production timing (current defaults) produces 30–45s runs that clear Q_TotalDuration thresholds.

---

## 10. Qualtrics-Specific Findings

These were discovered by inspecting live DOM and captured XHR payloads during development — they are not documented by Qualtrics and required empirical testing to diagnose.

### Finding 1: Hidden radio inputs
Qualtrics renders radio buttons as styled `<span>` elements; the real `<input type="radio">` is set to `visibility: hidden`. Standard Playwright click on the label triggers Qualtrics's UI JavaScript. `check(force=True)` on the hidden input fires a programmatic event that the biometric CustomJS can distinguish from a pointer event — removed in favor of label-only clicking.

### Finding 2: Slider requires mouse event
The Qualtrics drag slider (`[role='slider']`) responds to keyboard arrow keys for visual positioning, but the `onChange` handler that writes the response to Qualtrics's internal model only fires on mouse events. A bot that uses keyboard interaction passes visual inspection but produces an unanswered question in Qualtrics's validation layer.

### Finding 3: LoadingPage overlay timing
Between pages, Qualtrics briefly adds `class="LoadingPage"` to `#SkinContent`. This overlay can disappear in under 100ms on fast connections. `_wait_for_page_ready()` is called unconditionally at the top of every page loop iteration, not just after a Next click, to handle the race condition.

### Finding 4: SPA initial render delay
After `page.goto()`, `wait_for_load_state("domcontentloaded")` resolves while the page is still a blank white screen. Qualtrics's SPA JavaScript then fetches the survey definition and renders it — this can take 1–4 seconds. Without an explicit `wait_for_selector("#NextButton, div.QuestionOuter")`, the main loop spins empty iterations.

### Finding 5: `.ChoiceStructure` inside slider containers
Qualtrics wraps its slider inside a `div.QuestionOuter` that also contains `.ChoiceStructure` child elements (used for label rendering). Any radio detection heuristic that checks for `.ChoiceStructure` inside a question container will false-match the slider question. The slider check must run before the radio check.

### Finding 6: Q_DuplicateRespondent replaced RelevantID (June 2025)
Qualtrics deprecated the RelevantID third-party integration in June 2025 and replaced it with Q_DuplicateRespondent, a first-party implementation. Q_DuplicateRespondent uses the same combination of canvas fingerprint, localStorage tokens, and cookie state that RelevantID used, but is now managed entirely within the Qualtrics platform. Per-run context isolation and Camoufox canvas noise injection defeat it through the same mechanism.

### Finding 7: CustomJS behavioral biometrics (from XHR payload analysis)
The survey embeds a CustomJS block on QID2 that evaluates four signals at submission time:
- **Honeypot field** (`#honey_trap`) — any value = CRITICAL flag
- **Average typing speed** — `avg_speed < 120ms` = bot flag
- **Mouse path efficiency** — `efficiency > 0.99` (path length / straight-line distance) = bot flag
- **Mouse velocity stddev** — `stddev < 0.02` = bot flag (uniform robotic movement)

These thresholds were extracted from the survey's embedded JavaScript and drove the decisions to add `_FLIGHT_OFFSET_MS`, switch to WindMouse, and add the honeypot check.

### Finding 8: TargetClosedError on page close mid-interaction
When Qualtrics closes the current page (e.g. after the final submission), any in-flight `page.mouse.move()` or `page.keyboard.press()` raises `playwright._impl._errors.TargetClosedError`. This blocks for 30+ seconds per call (Playwright's default timeout) before raising. Fixed by: (a) wrapping mouse movement in try/except to exit immediately on TargetClosedError, (b) catching TargetClosedError in the main `bot.run()` loop and treating it as successful completion.

---

## 11. Configuration & Tunability

All runtime-tunable values live in `config.py`:

```python
SURVEY_URL = "https://baylor.qualtrics.com/jfe/form/SV_6GagF9EpumzN06W"
RUN_COUNT  = 1

BOT_EMAIL_MODE   = "natural"            # "natural" | "prefix" | "fixed"
BOT_EMAIL        = "surveybot.test@gmail.com"
BOT_EMAIL_PREFIX = "surveybot"          # used when mode = "prefix" (testing only)

TIMING = {
    "min_action_delay":          0.5,   # s — between answer interactions
    "max_action_delay":          2.0,
    "click_mean":                0.6,   # s — Gaussian pre-click pause
    "click_std":                 0.15,
    "read_per_question_mean":    3.0,   # s per question — reading pause scale
    "read_per_question_std":     0.9,
    "next_button_min":           1.2,   # s — pause before hitting Next
    "next_button_max":           3.0,
    "page_load_timeout_ms":   15_000,   # ms — max wait for page load
}
```

**Speed vs. stealth tuning:**  
Current settings produce a run time of 30–45 seconds per submission — within plausible human reading speed for a 5-question survey. Values below the `read_per_question_mean = 1.0` / `min_action_delay = 0.15` range were flagged by Q_TotalDuration analysis in prior test runs.

**Email mode override:**  
The CLI `prompt_config()` in `main.py` accepts all three modes at runtime. The default shown in brackets comes from `config.py`, but any mode can be selected per session without editing files. `main.py` patches `answers.BOT_EMAIL_MODE` directly (not `config.BOT_EMAIL_MODE`) since `answers.py` imports the value at load time.

---

## 12. Known Limitations

### IP-based detection (unmitigated)
All submissions come from the same IP address. A Qualtrics administrator can trivially filter by IP in the response data. Mitigation would require a rotating proxy pool, which was out of scope for this capstone.

### Single-machine only
The bot requires a local Firefox install and runs headfully (non-headless). It cannot be deployed serverlessly or distributed across machines without additional infrastructure.

### Keystroke profiles are thin
Three real human profiles have been recorded (`person_02.json`, `person_03.json`, `person_04.json`). A statistical analysis across many runs would reveal that timing patterns cluster around three distributions. Minimum recommended: 5–8 distinct profiles.

### Warmed profile staleness
The warmed profile captures a snapshot of browser state at one point in time. Google cookies expire; reCAPTCHA v3 may devalue old profiles over time. The profile should be regenerated every few days for sustained operation.

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
python -m camoufox fetch

# Record keystroke profiles (run once per team member)
python recorder.py
# Follow prompts — output saved to keystrokes/person_XX.json

# Pre-warm a browser profile for reCAPTCHA v3 (run once before a bot session)
python warm_profile.py
# Visits Google → YouTube → Wikipedia → AP News → BBC
# Saves to profiles/warmed_profile_TIMESTAMP.json

# Run the bot
python main.py
# Prompts for: survey URL, number of runs, email mode
```

**Recommended test procedure:**
1. Run `warm_profile.py` to create a fresh profile
2. Set `RUN_COUNT = 3` in `config.py` for a quick smoke test
3. Check Qualtrics response data to verify submissions appear
4. Note whether Q_DuplicateRespondent or CustomJS flags any responses
5. Increase `RUN_COUNT` for volume testing

**Log interpretation:**
```
[main] Warmed profile: warmed_profile_20260415_150227.json   ← profile loaded
[stealth] Canvas hash tail: pggMjosAAAAASUVORK5CYII=          ← per-run unique hash
[stealth] Launched Camoufox browser                          ← primary browser active
[human_sim] Loaded profile 'person_04.json' — mean flight: 92ms (effective: 142ms after +50ms offset)
[bot] ── Page 1 ──                                           ← bot entered main loop
[bot] Honeypot present and empty — OK                        ← honeypot check passed
[bot] 5 question container(s) found                          ← survey form loaded
[bot] Textarea (first_name): 'Donna'                         ← name typed keystroke-by-keystroke
[bot] Radio: CS - Cyber                                      ← major selected via WindMouse click
[bot] Slider (click at 0.60 via [role='slider'])             ← excitement level set
[branching] Complete — phrase: 'thank you'                   ← completion detected
[main] Estimated Q_TotalDuration: 44.4s                      ← above 30s threshold — OK
```
