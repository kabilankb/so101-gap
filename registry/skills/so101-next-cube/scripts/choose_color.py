"""Loop head: pick the next colour to handle, in the requested order.

``colors`` is a comma-separated order such as ``"red,green,blue,yellow"``. A
colour is skipped once ``verify_in_container`` (so101-placing-in-container) has
confirmed it in the box, or after ``max_attempts`` tries. ``finished`` is true
when every colour is done or given up, or the pass budget is spent.

The per-run state lives in a small JSON file keyed by the run's trace dir, so
the loop head and the verifier agree without passing state through the graph.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from typing import TypedDict

from gap import NodeContext

logger = logging.getLogger(__name__)
ALL = ("red", "green", "blue", "yellow")


class Output(TypedDict):
    color: str
    object_name: str
    object_description: str
    finished: bool


def _state_path(ctx) -> str:
    trace = getattr(ctx, "_trace", None)
    out_dir = getattr(trace, "_output_dir", None) if trace is not None else None
    tag = hashlib.sha1(str(out_dir or os.getpid()).encode()).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), f".so101_sort_{tag}.json")


def run(ctx: NodeContext, colors: str = "red,green,blue,yellow", max_attempts: int = 3,
        max_passes: int = 16) -> Output:
    order = [c.strip() for c in colors.split(",") if c.strip()]
    path = _state_path(ctx)
    try:
        with open(path) as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {"done": [], "attempts": {}, "current": None, "passes": 0, "log": []}
    st["passes"] += 1
    todo = [c for c in order if c not in st["done"] and st["attempts"].get(c, 0) < max_attempts]
    finished = not todo or st["passes"] > max_passes
    color = "" if finished else todo[0]
    if color:
        st["attempts"][color] = st["attempts"].get(color, 0) + 1
    st["current"] = color
    with open(path, "w") as f:
        json.dump(st, f)
    logger.info("[sort] pass %d: done=%s next=%s", st["passes"], st["done"], color or "-")
    others = ", ".join(c for c in ALL if c != color)
    return {
        "color": color,
        "object_name": f"{color} cube",
        "object_description": (f"a small solid {color} wooden cube (3 cm) lying on the table, outside the "
                               f"box. Not the large open green box/tray, and not a {others} cube."),
        "finished": finished,
    }
