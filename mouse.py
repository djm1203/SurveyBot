"""
mouse.py — Bezier-curve mouse movement.

WHY THIS EXISTS
---------------
Bot detection tools (and some reCAPTCHA v3 scoring models) watch how the
mouse moves, not just where it ends up.  The dead giveaway of automation is
perfectly straight-line movement: a real human's hand trembles slightly,
overshoots, and follows a natural arc.  This module replaces Playwright's
direct .click() with a curved path of intermediate mouse positions.

HOW IT WORKS
------------
A cubic Bezier curve is defined by four control points:
  P0 → current mouse position (start)
  P1 → random point biased toward the start  (pulls the curve away early)
  P2 → random point biased toward the target (pulls it back in late)
  P3 → target element center (end)

We sample ~30-50 points along that curve, move the mouse to each one with a
small delay, then let Playwright fire the actual click event.

USAGE (from bot.py / human_sim.py)
-----------------------------------
    from mouse import bezier_click, bezier_move

    bezier_click(page, locator)          # move then click a Playwright locator
    bezier_move(page, target_x, target_y) # just move, no click
"""

import logging
import random

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level mouse state
# We track the logical cursor position ourselves because Playwright's sync
# API does not expose a "current mouse position" property.
# ---------------------------------------------------------------------------
_mouse_x: float = 0.0
_mouse_y: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def bezier_click(page, locator) -> None:
    """
    Move the mouse to a locator's center along a Bezier curve, then click.

    Falls back to a plain .click() if the element's bounding box cannot be
    determined (e.g. the element is not yet visible).

    Parameters
    ----------
    page    : Playwright Page object
    locator : Playwright Locator pointing to the element to click
    """
    try:
        box = locator.bounding_box(timeout=2_000)
        if not box:
            raise ValueError("bounding_box returned None")

        # Target: center of the element
        target_x = box["x"] + box["width"]  / 2
        target_y = box["y"] + box["height"] / 2

        bezier_move(page, target_x, target_y)
        page.mouse.click(target_x, target_y)

    except Exception as exc:
        # Graceful degradation — the survey still gets answered, just less stealthily
        logger.warning(f"[mouse] bezier_click fell back to direct click: {exc}")
        locator.click()


def bezier_move(page, target_x: float, target_y: float) -> None:
    """
    Move the mouse from its current tracked position to (target_x, target_y)
    along a cubic Bezier curve.

    Parameters
    ----------
    page     : Playwright Page object
    target_x : Destination x coordinate (pixels)
    target_y : Destination y coordinate (pixels)
    """
    global _mouse_x, _mouse_y

    start_x, start_y = _mouse_x, _mouse_y
    end_x,   end_y   = target_x, target_y

    # ── Build control points ────────────────────────────────────────────────
    # P1 and P2 are offset perpendicular to the straight-line path so the
    # curve bows naturally rather than just wobbling along the straight line.
    dx = end_x - start_x
    dy = end_y - start_y

    # Random lateral offset — scales with move distance so long moves curve more
    distance = max(1.0, (dx**2 + dy**2) ** 0.5)
    jitter   = distance * random.uniform(0.1, 0.3)

    # Perpendicular unit vector  (-dy/d, dx/d)
    perp_x = -dy / distance * jitter * random.choice([-1, 1])
    perp_y =  dx / distance * jitter * random.choice([-1, 1])

    p0 = (start_x, start_y)
    p1 = (start_x + dx * 0.3 + perp_x, start_y + dy * 0.3 + perp_y)
    p2 = (start_x + dx * 0.7 + perp_x, start_y + dy * 0.7 + perp_y)
    p3 = (end_x,   end_y)

    # ── Trace the curve ──────────────────────────────────────────────────────
    steps         = random.randint(30, 50)
    total_ms      = random.uniform(200, 600)   # total move duration
    step_delay_ms = int(total_ms / steps)

    for i in range(1, steps + 1):
        t = i / steps
        x, y = _cubic_bezier(t, p0, p1, p2, p3)

        # Tiny random noise on each step — simulates hand tremor
        x += random.gauss(0, 0.4)
        y += random.gauss(0, 0.4)

        page.mouse.move(x, y)
        if step_delay_ms > 0:
            page.wait_for_timeout(step_delay_ms)

    # Update tracked position
    _mouse_x = end_x
    _mouse_y = end_y


def reset_position(x: float = 0.0, y: float = 0.0) -> None:
    """
    Reset the module's tracked mouse position.
    Call this at the start of each bot run so the first move starts from a
    known location (e.g. center of the viewport) rather than (0, 0).
    """
    global _mouse_x, _mouse_y
    _mouse_x = x
    _mouse_y = y


# ---------------------------------------------------------------------------
# Internal: cubic Bezier math
# ---------------------------------------------------------------------------

def _cubic_bezier(
    t: float,
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
) -> tuple[float, float]:
    """
    Evaluate a cubic Bezier curve at parameter t ∈ [0, 1].

    The standard formula:
        B(t) = (1-t)³·P0 + 3(1-t)²t·P1 + 3(1-t)t²·P2 + t³·P3
    """
    u = 1 - t
    x = u**3*p0[0] + 3*u**2*t*p1[0] + 3*u*t**2*p2[0] + t**3*p3[0]
    y = u**3*p0[1] + 3*u**2*t*p1[1] + 3*u*t**2*p2[1] + t**3*p3[1]
    return x, y
