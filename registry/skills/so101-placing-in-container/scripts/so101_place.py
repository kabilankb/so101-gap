"""Place the held cube into the open container with the LeRobot SO-101.

The container's 9 cm interior is a 2x2 grid of slots. With ``color`` and
``colors`` set (e.g. ``"blue"`` and ``"red,green,blue,yellow"``) each colour gets
its own quadrant, in the order of ``colors``, so cubes end up sorted and never
stacked. Without them the cube goes to the centre.

Motion: rise to transit height → move over the slot → descend into the box →
open to ~45 % (a wider swing of the hinged jaw hits the box walls) → retract →
go home, so the front camera sees the box unobstructed for verification.

Self-contained on purpose: canonical scripts are copied per subgraph into
generated workflows, so they cannot import sibling helper modules.
"""

from __future__ import annotations

import logging
from typing import TypedDict

import numpy as np
from gap import NodeContext
from gap_core.types import OrientedBoundingBox
from scipy.spatial.transform import Rotation

logger = logging.getLogger(__name__)

SLOTS = [(-1, -1), (-1, 1), (1, -1), (1, 1)]   # (dx, dy) sign per slot
SLOT_OFFSET = 0.021                            # m from the container centre
RELEASE_Z = 0.038                              # m, TCP height at release (cube bottom ~2 cm)
TRANSIT_Z = 0.085
_R_DOWN = np.array([[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]])


class Output(TypedDict):
    place_xyz: list[float]


def _move(ctx: NodeContext, x: float, y: float, z: float, yaw: float) -> None:
    c, s = np.cos(yaw), np.sin(yaw)
    qx, qy, qz, qw = Rotation.from_matrix(np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]]) @ _R_DOWN).as_quat()
    ctx.tool("robot.go_to_pose_cartesian", pose={
        "position": {"x": float(x), "y": float(y), "z": float(z)},
        "rotation": {"w": float(qw), "x": float(qx), "y": float(qy), "z": float(qz)}})


def run(ctx: NodeContext, container_obb: OrientedBoundingBox, color: str = "",
        colors: str = "") -> Output:
    order = [c.strip() for c in colors.split(",") if c.strip()]
    c = container_obb["center"]
    x, y = float(c["x"]), float(c["y"])
    if color and color in order:
        sx, sy = SLOTS[order.index(color) % 4]
        x, y = x + sx * SLOT_OFFSET, y + sy * SLOT_OFFSET
    yaw = float(np.arctan2(y, x) + np.pi / 2)                 # jaws tangential
    logger.info("[place] %s -> (%.3f, %.3f)", color or "cube", x, y)
    p = ctx.tool("robot.get_ee_pose")["pose"]["position"]
    z = max(TRANSIT_Z, float(p["z"]))
    if p["z"] < z - 0.01:
        _move(ctx, p["x"], p["y"], z, yaw)
    _move(ctx, x, y, z, yaw)
    _move(ctx, x, y, RELEASE_Z, yaw)
    ctx.tool("robot.set_gripper", fraction=0.45, settle_steps=30)
    _move(ctx, x, y, 0.09, yaw)
    ctx.tool("robot.go_home")
    return {"place_xyz": [x, y, RELEASE_Z]}
