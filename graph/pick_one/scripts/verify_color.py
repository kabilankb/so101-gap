"""Router: unprivileged VLM check that this colour's cube is now in the box.

``verified`` marks the colour done for the loop head; ``missed`` leaves it to
be retried (up to the attempt budget). If the VLM is unreachable the colour
is NOT marked done (fail safe) and the loop head's budgets still terminate.
"""

from __future__ import annotations

import logging
import os
import sys

import numpy as np
from gap import NodeContext

sys.path.insert(0, os.path.dirname(__file__))
import sort_state  # noqa: E402

logger = logging.getLogger(__name__)


def run(ctx: NodeContext, color: str) -> dict:
    obs = ctx.tool("robot.get_observation")
    cams = obs.get("cameras") or []
    rgb = np.asarray(cams[0]["rgb"]) if cams else None
    ok = False
    if rgb is not None:
        try:
            resp = ctx.tool(
                "vlm.query_yes_no",
                prompt=(f"Look at the open green box on the table. Is the {color} cube "
                        f"inside the green box? Answer YES only if the {color} cube is "
                        f"resting inside the box, not on the table."),
                image=rgb,
            )
            ok = bool(resp.get("answer"))
            logger.info("[verify] %s in box? %s (%r)", color, ok, str(resp.get("text"))[:120])
        except Exception as exc:  # noqa: BLE001
            logger.warning("[verify] VLM unavailable: %s", exc)
    st = sort_state.load(ctx)
    if ok and color not in st["done"]:
        st["done"].append(color)
    st["log"].append({"color": color, "verified": ok})
    sort_state.save(ctx, st)
    return {"route": "verified" if ok else "missed"}
