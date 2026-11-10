"""Place the held cube in its colour's slot inside the box, then clear the view.

The box (9 cm inside) is split into a 2x2 grid; each colour gets its own
quadrant, in the order of ``colors`` — so the cubes end up sorted by colour,
not stacked. After releasing, the arm returns home so the front camera sees
the box unobstructed for the verification step.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import TypedDict

from gap import NodeContext
from gap_core.types import OrientedBoundingBox

sys.path.insert(0, os.path.dirname(__file__))
import so101_motion as M  # noqa: E402

logger = logging.getLogger(__name__)
SLOTS = [(-1, -1), (-1, 1), (1, -1), (1, 1)]  # (dx, dy) sign per slot
SLOT_OFFSET = 0.021  # m from the box centre


class Output(TypedDict):
    place_xyz: list[float]


def run(ctx: NodeContext, container_obb: OrientedBoundingBox, color: str,
        colors: str) -> Output:
    colors = [s.strip() for s in colors.split(",") if s.strip()]
    c = container_obb["center"]
    i = colors.index(color) if color in colors else 0
    sx, sy = SLOTS[i % 4]
    x, y = float(c["x"]) + sx * SLOT_OFFSET, float(c["y"]) + sy * SLOT_OFFSET
    cur = M.ee_xyz(ctx)
    yaw = M.tangential_yaw(x, y, 0.0)
    logger.info("[place] %s -> slot %d at (%.3f, %.3f)", color, i, x, y)
    M.transit(ctx, x, y, yaw, z=max(0.085, float(cur[2])))
    M.move(ctx, x, y, 0.038, yaw)
    ctx.tool("robot.set_gripper", fraction=0.45, settle_steps=30)
    M.move(ctx, x, y, 0.09, yaw)
    ctx.tool("robot.go_home")
    return {"place_xyz": [x, y, 0.038]}
