"""Unprivileged VLM check that the placed cube is inside the container.

Asks the VLM, on the front-camera frame (the arm is home, out of the view),
whether ``object_name`` (default ``"<color> cube"``) rests inside the open
green box. Returns ``{"verdict": "verified"}`` on YES, else ``"missed"``. The
subgraph's exit reads that field (``set_exit_router(router_field="verdict")``).
A VLM error is treated as ``missed`` (fail safe).

When ``color`` is set, a verified colour is also recorded in the per-run
sorting state that the ``so101-next-cube`` loop head reads, so a looped graph
moves on to the next colour.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from typing import TypedDict

import numpy as np
from gap import NodeContext

logger = logging.getLogger(__name__)


class Output(TypedDict):
    verdict: str


def _state_path(ctx) -> str:
    trace = getattr(ctx, "_trace", None)
    out_dir = getattr(trace, "_output_dir", None) if trace is not None else None
    tag = hashlib.sha1(str(out_dir or os.getpid()).encode()).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), f".so101_sort_{tag}.json")


def _mark_done(ctx, color: str, ok: bool) -> None:
    path = _state_path(ctx)
    try:
        with open(path) as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {"done": [], "attempts": {}, "current": None, "passes": 0, "log": []}
    if ok and color not in st["done"]:
        st["done"].append(color)
    st["log"].append({"color": color, "verified": ok})
    with open(path, "w") as f:
        json.dump(st, f)


def run(ctx: NodeContext, color: str = "", object_name: str = "") -> Output:
    name = object_name or (f"{color} cube" if color else "cube")
    obs = ctx.tool("robot.get_observation")
    cams = obs.get("cameras") or []
    ok = False
    if cams:
        try:
            resp = ctx.tool(
                "vlm.query_yes_no",
                prompt=(f"Look at the open green box on the table. Is the {name} inside the green box? "
                        f"Answer YES only if the {name} is resting inside the box, not on the table."),
                image=np.asarray(cams[0]["rgb"]),
            )
            ok = bool(resp.get("answer"))
            logger.info("[verify] %s in box? %s (%r)", name, ok, str(resp.get("text"))[:120])
        except Exception as exc:  # noqa: BLE001  (VLM down -> fail safe)
            logger.warning("[verify] VLM unavailable: %s", exc)
    if color:
        _mark_done(ctx, color, ok)
    return {"verdict": "verified" if ok else "missed"}
