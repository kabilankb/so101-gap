"""Loop head: pick the next colour to sort, in the requested order.

A colour is skipped once the VLM has verified it in the box, or after
``max_attempts`` failed tries (so one stubborn cube cannot stall the rest).
``finished`` becomes true when every colour is done or given up, or when the
total pass budget is spent.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import TypedDict

from gap import NodeContext

sys.path.insert(0, os.path.dirname(__file__))
import sort_state  # noqa: E402

logger = logging.getLogger(__name__)


class Output(TypedDict):
    color: str
    object_name: str
    object_description: str
    finished: bool


def run(ctx: NodeContext, colors: str, max_attempts: int = 3, max_passes: int = 16) -> Output:
    colors = [c.strip() for c in colors.split(",") if c.strip()]
    st = sort_state.load(ctx)
    st["passes"] += 1
    todo = [c for c in colors if c not in st["done"] and st["attempts"].get(c, 0) < max_attempts]
    finished = not todo or st["passes"] > max_passes
    color = "" if finished else todo[0]
    if not finished:
        st["attempts"][color] = st["attempts"].get(color, 0) + 1
    st["current"] = color
    sort_state.save(ctx, st)
    logger.info("[sort] pass %d: done=%s next=%s attempt=%s", st["passes"], st["done"],
                color or "-", st["attempts"].get(color, 0) if color else "-")
    others = ", ".join(c for c in ("red", "green", "blue", "yellow") if c != color)
    return {
        "color": color,
        "object_name": f"{color} cube",
        "object_description": (
            f"a small solid {color} wooden cube (3 cm) lying on the table, outside the box. "
            f"Not the large open green box/tray, and not a {others} cube."
        ),
        "finished": finished,
    }
