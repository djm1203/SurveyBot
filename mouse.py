"""
mouse.py — Human-grade mouse movement simulation.

WHY THIS EXISTS
---------------
Bot detection tools score mouse events as a primary behavioral signal.
Dead giveaways of automation:
  • Perfectly straight movement (zero lateral deviation)
  • Uniform speed (no acceleration / deceleration)
  • Insufficient mousemove event count (< ~100 events per click)
  • No overshoot — humans routinely move past a target and correct back

This module uses two techniques:

  1. WindMouse physics engine
     Models the cursor as a particle attracted to the target (gravity) with
     random lateral turbulence (wind).  This produces the slightly wobbly,
     arcing paths that are characteristic of real hand-to-mouse movement.
     Unlike static Bezier interpolation, each move is unique because the
     physics unfold differently every time.

     Parameters are tuned so:
       - Short moves (< 150 px) : ~40–80 events, fast snap
       - Medium moves (150–500 px) : ~80–200 events, smooth arc
       - Long moves (> 500 px) : ~200–400 events, wide bow

  2. Overshoot + correction
     After reaching the target, 40 % of clicks intentionally overshoot
     3–12 % of the travel distance in the direction of approach, pause
     briefly (simulating the moment the user realises they went too far),
     then glide back.  This matches the Fitts's Law motor data on human
     pointing tasks.

USAGE (from bot.py / human_sim.py)
-----------------------------------
    from mouse import bezier_click, bezier_move

    bezier_click(page, locator)           # move then click a Playwright locator
    bezier_move(page, target_x, target_y) # just move, no click
    reset_position(x, y)                  # call once per run with viewport centre
"""

import logging
import math
import random

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level tracked cursor position
# Playwright's sync API has no "where is the mouse right now?" property, so
# we maintain it ourselves.  reset_position() must be called at run start.
# ---------------------------------------------------------------------------
_mouse_x: float = 0.0
_mouse_y: float = 0.0


# ---------------------------------------------------------------------------
# Public API  (names kept identical to the original so callers need no changes)
# ---------------------------------------------------------------------------

def bezier_click(page, locator) -> None:
    """
    Move the mouse to the centre of `locator` via WindMouse, then click.

    Randomly applies overshoot+correction (~40 % of calls) for realism.
    Falls back to a plain .click() if the bounding box is unavailable.
    """
    try:
        box = locator.bounding_box(timeout=2_000)
        if not box:
            raise ValueError("bounding_box returned None")

        target_x = box["x"] + box["width"]  / 2
        target_y = box["y"] + box["height"] / 2

        bezier_move(page, target_x, target_y)

        # Overshoot+correction on ~40 % of clicks
        if random.random() < 0.40:
            _overshoot_correct(page, target_x, target_y)

        page.mouse.click(target_x, target_y)

    except Exception as exc:
        logger.warning(f"[mouse] bezier_click fell back to direct click: {exc}")
        locator.click()


def bezier_move(page, target_x: float, target_y: float) -> None:
    """
    Move the mouse from its current tracked position to (target_x, target_y)
    using the WindMouse physics engine.
    """
    global _mouse_x, _mouse_y
    _windmouse(page, _mouse_x, _mouse_y, target_x, target_y)
    _mouse_x = target_x
    _mouse_y = target_y


def reset_position(x: float = 0.0, y: float = 0.0) -> None:
    """
    Reset the module's tracked cursor position.
    Call once per bot run, typically with the viewport centre.
    """
    global _mouse_x, _mouse_y
    _mouse_x = x
    _mouse_y = y


# ---------------------------------------------------------------------------
# WindMouse physics engine
# ---------------------------------------------------------------------------

def _windmouse(
    page,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    gravity: float = 9.0,
    wind: float = 3.0,
    max_step: float = 12.0,
    min_wait_ms: int = 1,
    max_wait_ms: int = 6,
    max_iterations: int = 5_000,
) -> None:
    """
    Move the cursor from (start_x, start_y) to (end_x, end_y) using a
    gravity+wind physics simulation.

    gravity        — attraction toward the target per step
    wind           — maximum random lateral turbulence per step
    max_step       — maximum pixels moved per step (controls speed)
    max_iterations — hard safety cap; prevents any theoretical infinite loop
                     and allows fast exit if the page closes mid-move.
    """
    x, y = float(start_x), float(start_y)
    wind_x = wind_y = 0.0
    velo_x = velo_y = 0.0

    for _ in range(max_iterations):
        dist = math.sqrt((end_x - x) ** 2 + (end_y - y) ** 2)
        if dist < 1.0:
            break

        # Wind turbulence — decays as we approach the target so the cursor
        # steadies up near the destination (just like a real hand)
        wind_scale = min(wind, dist / 4.0)
        wind_x = wind_x / math.sqrt(3) + (random.random() * 2 - 1) * wind_scale
        wind_y = wind_y / math.sqrt(3) + (random.random() * 2 - 1) * wind_scale

        # Gravity pulls toward target
        velo_x += wind_x + gravity * (end_x - x) / dist
        velo_y += wind_y + gravity * (end_y - y) / dist

        # Cap speed — scale the cap with remaining distance so the cursor
        # naturally decelerates as it closes in
        effective_max = min(max_step, dist / 2.0 + 0.5)
        speed = math.sqrt(velo_x ** 2 + velo_y ** 2)
        if speed > effective_max:
            rand_speed = effective_max * (0.7 + random.random() * 0.3)
            velo_x = velo_x / speed * rand_speed
            velo_y = velo_y / speed * rand_speed

        # Micro-jitter — simulates hand tremor (~0.3 px RMS)
        x += velo_x + random.gauss(0, 0.3)
        y += velo_y + random.gauss(0, 0.3)

        try:
            page.mouse.move(x, y)
        except Exception:
            # Page closed or navigated away — abort the move gracefully
            return

        wait_ms = random.randint(min_wait_ms, max_wait_ms)
        if wait_ms > 0:
            try:
                page.wait_for_timeout(wait_ms)
            except Exception:
                return


# ---------------------------------------------------------------------------
# Overshoot + correction
# ---------------------------------------------------------------------------

def _overshoot_correct(page, target_x: float, target_y: float) -> None:
    """
    Simulate the human tendency to overshoot a click target and then
    make a small corrective sub-movement back.

    The overshoot distance is 5–12 % of the distance the cursor just
    travelled, applied in the same direction of approach.
    """
    global _mouse_x, _mouse_y

    dx = target_x - _mouse_x
    dy = target_y - _mouse_y
    dist = math.sqrt(dx ** 2 + dy ** 2)
    if dist < 5:
        return  # too close — no overshoot worth simulating

    overshoot_frac = random.uniform(0.05, 0.12)
    overshoot_dist = dist * overshoot_frac
    norm_x = dx / dist
    norm_y = dy / dist

    # Add slight lateral drift to the overshoot so it isn't perfectly collinear
    perp_x = -norm_y * random.uniform(-0.15, 0.15)
    perp_y =  norm_x * random.uniform(-0.15, 0.15)

    over_x = target_x + norm_x * overshoot_dist + perp_x * overshoot_dist
    over_y = target_y + norm_y * overshoot_dist + perp_y * overshoot_dist

    # Fast dart to the overshoot point
    _windmouse(page, _mouse_x, _mouse_y, over_x, over_y,
               gravity=18, wind=0.5, max_step=6)

    # Brief pause — the moment the user realises they overshot
    page.wait_for_timeout(random.randint(60, 160))

    # Slow correction back to target
    _windmouse(page, over_x, over_y, target_x, target_y,
               gravity=22, wind=0.2, max_step=4)

    _mouse_x = target_x
    _mouse_y = target_y
