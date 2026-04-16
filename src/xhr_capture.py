"""
src/xhr_capture.py — Qualtrics XHR capture: request body + response scores.

WHY THIS EXISTS
---------------
Qualtrics bot-score data lives in two places:

  1. REQUEST body (POST payload) — the CustomJS biometric block writes
     fields like bot_score, typing_avg_speed_ms, mouse_path_efficiency
     into Embedded Data and they travel to the server as ED[field]=value
     form parameters on every /next POST.

  2. RESPONSE body — the server echoes back SM fields (Q_RecaptchaScore,
     Q_TotalDuration, Q_DuplicateRespondent) in the JSON response.

We intercept both via page.on("request") + page.on("response") so we get
the complete picture without relying on DevTools manually.

USAGE
-----
Call attach_capture() BEFORE page.goto() so it catches the /start response
(which has the initial reCAPTCHA score) as well as every /next response.

    results = attach_capture(page, run_label="run01")
    bot.run()
    log_run_verdict(results, run_number=1)

The results dict is mutated in place as responses arrive — it is safe to
read it after bot.run() returns.

OUTPUT
------
Each run writes a JSON file to  logs/xhr_<run_label>_<timestamp>.json
containing the captured request/response data for offline inspection.
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output directory
# ---------------------------------------------------------------------------
CAPTURE_DIR = Path(__file__).parent.parent / "logs"

# ---------------------------------------------------------------------------
# Fields to extract from the Qualtrics response JSON
#
# ED  — Embedded Data written by the CustomJS biometric block
# SM  — Survey Metadata returned by the Qualtrics engine at the top level
# ---------------------------------------------------------------------------
_ED_KEYS = [
    "bot_score",
    "typing_avg_speed_ms",
    "typing_consistency_score",
    "mouse_path_efficiency",
    "mouse_velocity_avg",
    "mouse_velocity_stddev",
    "is_mobile",
]

_SM_KEYS = [
    "Q_RecaptchaScore",
    "Q_RecaptchaStatus",
    "Q_TotalDuration",
    "Q_DuplicateRespondent",
    "Q_RelevantIDFraudScore",
    "Q_RelevantIDLastStartDate",
]

# ---------------------------------------------------------------------------
# Static asset extensions to skip
# ---------------------------------------------------------------------------
_SKIP_EXTENSIONS = (".js", ".css", ".png", ".jpg", ".jpeg", ".gif",
                    ".ico", ".woff", ".woff2", ".svg", ".ttf")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def attach_capture(page, run_label: str) -> dict:
    """
    Register a response listener on the Playwright page.

    Returns a results dict that is populated in place as responses arrive.
    Read it after bot.run() completes to get the extracted detection scores.

    Must be called BEFORE page.goto() to capture the /start response.

    Parameters
    ----------
    page       : Playwright Page object
    run_label  : Short string used in the log filename (e.g. "run01")
    """
    CAPTURE_DIR.mkdir(exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = CAPTURE_DIR / f"xhr_{run_label}_{ts}.json"

    captured: list[dict] = []

    # Mutable results dict — populated by the callback as responses arrive
    results: dict = {
        "bot_score":               None,
        "Q_RecaptchaScore":        None,
        "Q_RecaptchaStatus":       None,
        "Q_TotalDuration":         None,
        "Q_DuplicateRespondent":   None,
        "Q_RelevantIDFraudScore":  None,
        "typing_avg_speed_ms":     None,
        "typing_consistency_score": None,
        "mouse_path_efficiency":   None,
        "mouse_velocity_avg":      None,
        "mouse_velocity_stddev":   None,
        "pasteCount_total":        None,
        "is_eos":                  False,
        "passed":                  None,   # True = human, False = bot, None = unknown
    }

    def _on_request(request) -> None:
        """
        Intercept POST request bodies on Qualtrics /next endpoints.

        The CustomJS biometric block encodes scores as ED[field]=value in
        the URL-encoded POST body.  These values are never echoed back in the
        response JSON — the response interceptor alone will always miss them.
        """
        url = request.url
        if "qualtrics.com" not in url:
            return
        if request.method != "POST":
            return
        # Only /next requests carry ED fields; /start is GET/HTML
        if "/next" not in url:
            return

        try:
            post_data = request.post_data
            if not post_data:
                return

            params = parse_qs(post_data)

            # ED fields arrive as ED[field_name]=value
            ed_extracted: dict = {}
            for key, val_list in params.items():
                if key.startswith("ED[") and key.endswith("]"):
                    field = key[3:-1]   # strip "ED[" prefix and "]" suffix
                    ed_extracted[field] = val_list[0]

            if not ed_extracted:
                return

            logger.debug(
                f"[xhr_capture] Request ED fields: {list(ed_extracted.keys())}"
            )

            # Update results for every known ED key
            for field in _ED_KEYS:
                if field in ed_extracted:
                    results[field] = ed_extracted[field]

            # bot_score drives the pass/fail verdict
            if "bot_score" in ed_extracted:
                results["bot_score"] = ed_extracted["bot_score"]
                results["passed"] = (ed_extracted["bot_score"] == "Low (Human)")

            # Log the request-extracted data to the captured list as well
            entry: dict = {
                "ts":     time.time(),
                "url":    url,
                "source": "request",
                "ed":     ed_extracted,
            }
            captured.append(entry)
            try:
                log_path.write_text(json.dumps(captured, indent=2), encoding="utf-8")
            except Exception as exc:
                logger.debug(f"[xhr_capture] Failed to write log: {exc}")

        except Exception as exc:
            logger.debug(f"[xhr_capture] Request capture error: {exc}")

    def _on_response(response) -> None:
        url = response.url

        # Filter: only Qualtrics, only POST, skip static assets
        if "qualtrics.com" not in url:
            return
        if response.request.method != "POST":
            return
        if any(url.lower().endswith(ext) for ext in _SKIP_EXTENSIONS):
            return
        # The recaptcha score endpoint has a different structure — handled
        # via the SM.Q_RecaptchaScore field in the main /next response
        if "getRecaptchaV3Score" in url:
            return

        try:
            body_text = response.text()
        except Exception as exc:
            logger.debug(f"[xhr_capture] Could not read body for {url}: {exc}")
            return

        entry: dict = {
            "ts":        time.time(),
            "url":       url,
            "status":    response.status,
            "source":    "response",
            "parsed_ok": False,
        }

        # Parse-first: read the full body without truncating so the SM/ED
        # fields at the end of large Qualtrics responses aren't cut off.
        # Store only a small preview in the disk log to keep file sizes sane.
        try:
            data = json.loads(body_text)
            entry["parsed_ok"] = True
            entry["body_preview"] = body_text[:300]

            # ── Embedded Data (CustomJS biometrics) ──────────────────────
            # NOTE: ED fields are usually absent from responses — they travel
            # in the request body.  Keep this block as a fallback in case the
            # survey config echoes them back.
            ed = data.get("ED") or {}
            for key in _ED_KEYS:
                val = _deep_get(ed, key)
                if val is not None:
                    entry[key] = val
                    results[key] = val

            # ── Survey Metadata ───────────────────────────────────────────
            sm = data.get("SM") or {}
            for key in _SM_KEYS:
                val = _deep_get(sm, key)
                if val is not None:
                    entry[f"SM_{key}"] = val
                    if results.get(key) is None:
                        results[key] = val

            # ── EOS (end-of-survey) flag ──────────────────────────────────
            if data.get("IsEOS"):
                results["is_eos"] = True
                entry["is_eos"] = True
                # Q_TotalDuration is authoritative on the EOS response
                duration = sm.get("Q_TotalDuration")
                if duration is not None:
                    results["Q_TotalDuration"] = duration

            # ── LegacyTextAnalytics — paste detection ─────────────────────
            lta = (data.get("LegacyTextAnalytics")
                   or sm.get("LegacyTextAnalyticsDelta")
                   or {})
            if lta:
                paste_total = sum(
                    v.get("pasteCount", 0)
                    for v in lta.values()
                    if isinstance(v, dict)
                )
                entry["pasteCount_total"] = paste_total
                results["pasteCount_total"] = paste_total

            # ── Pass/fail verdict ─────────────────────────────────────────
            if results["bot_score"] is not None:
                results["passed"] = (results["bot_score"] == "Low (Human)")

        except (json.JSONDecodeError, ValueError):
            # Not a JSON response (HTML error page, etc.)
            entry["body_preview"] = body_text[:400]

        captured.append(entry)

        # Write to disk immediately so a crash mid-run doesn't lose data
        try:
            log_path.write_text(json.dumps(captured, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug(f"[xhr_capture] Failed to write log: {exc}")

        logger.debug(
            f"[xhr_capture] {response.request.method} {url[-60:]} "
            f"→ {response.status} | parsed={entry['parsed_ok']}"
        )

    page.on("request",  _on_request)
    page.on("response", _on_response)
    logger.info(f"[xhr_capture] Active — logging to {log_path.name}")
    return results


def log_run_verdict(results: dict, run_number: int) -> None:
    """
    Log a clean per-run verdict summary extracted from XHR payloads.

    Call after bot.run() completes.
    """
    passed    = results.get("passed")
    score     = results.get("bot_score")         or "N/A"
    recaptcha = results.get("Q_RecaptchaScore")  or "N/A"
    duration  = results.get("Q_TotalDuration")   or "N/A"
    duplicate = results.get("Q_DuplicateRespondent") or "N/A"
    typing    = results.get("typing_avg_speed_ms")   or "N/A"
    mouse_eff = results.get("mouse_path_efficiency") or "N/A"
    mouse_std = results.get("mouse_velocity_stddev") or "N/A"
    paste     = results.get("pasteCount_total")      or "N/A"

    if passed is True:
        status = "PASS (human)"
    elif passed is False:
        status = "FAIL (bot)"
    else:
        status = "UNKNOWN — bot_score not found in payload"

    sep = "─" * 52
    logger.info(f"[xhr_capture] {sep}")
    logger.info(f"[xhr_capture]  Run {run_number:>2} XHR Verdict: {status}")
    logger.info(f"[xhr_capture] {sep}")
    logger.info(f"[xhr_capture]   bot_score              : {score}")
    logger.info(f"[xhr_capture]   Q_RecaptchaScore       : {recaptcha}")
    logger.info(f"[xhr_capture]   Q_TotalDuration        : {duration}s")
    logger.info(f"[xhr_capture]   Q_DuplicateRespondent  : {duplicate}")
    logger.info(f"[xhr_capture]   typing_avg_speed_ms    : {typing}")
    logger.info(f"[xhr_capture]   mouse_path_efficiency  : {mouse_eff}")
    logger.info(f"[xhr_capture]   mouse_velocity_stddev  : {mouse_std}")
    logger.info(f"[xhr_capture]   pasteCount_total       : {paste}")
    logger.info(f"[xhr_capture] {sep}")

    if passed is False:
        logger.error(f"[xhr_capture]  BOT DETECTED on run {run_number} — score: {score}")
    elif passed is True:
        logger.info(f"[xhr_capture]  Passed as human on run {run_number}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deep_get(d: dict, key: str):
    """
    Look up a key in a dict, also checking one level of nested dicts.
    Qualtrics sometimes nests ED fields under sub-keys.
    """
    if not isinstance(d, dict):
        return None
    if key in d:
        return d[key]
    for v in d.values():
        if isinstance(v, dict) and key in v:
            return v[key]
    return None
