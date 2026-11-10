"""Top-down pick of one perceived cube with the SO-101.

From the perceived OBB (front-camera depth): centre XY, top height, and the
cube's face yaw. The jaws close on the face pair nearest to tangential.
The jaw opens only ~45%: fully open, the SO-101's hinged jaw sweeps ~100 deg
through the table and neighbouring cubes. The TCP goes to the cube's centre height.
Grasp success is unprivileged: the closed gripper must stop on the cube
(open fraction above ``min_closed``) and still hold it after the lift.
A miss raises, which routes the subgraph to ``failed`` and the loop retries
with fresh perception.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import TypedDict

import numpy as np
from gap import NodeContext
from gap_core.errors import ToolError
from gap_core.types import OrientedBoundingBox
from scipy.spatial.transform import Rotation

sys.path.insert(0, os.path.dirname(__file__))
import so101_motion as M  # noqa: E402

logger = logging.getLogger(__name__)
CUBE = 0.03


class Output(TypedDict):
    grasp_xyz: list[float]
    closed_fraction: float


def _cube_from_obb(obb: OrientedBoundingBox) -> tuple[float, float, float, float]:
    c, e, q = obb["center"], obb["extent"], obb["orientation"]
    R = Rotation.from_quat([q["x"], q["y"], q["z"], q["w"]]).as_matrix()
    # top of the visible points -> cube centre one half-edge below
    top = c["z"] + float(np.abs(R[2, :]) @ np.array([e["x"], e["y"], e["z"]]))
    zc = max(top - CUBE / 2, CUBE / 2 - 0.003)
    # face yaw: the OBB axis that is most horizontal
    axis = R[:, int(np.argmin(np.abs(R[2, :])))]
    face_yaw = float(np.arctan2(axis[1], axis[0]))
    return float(c["x"]), float(c["y"]), zc, face_yaw


def run(ctx: NodeContext, target_obb: OrientedBoundingBox, min_closed: float = 0.06,
        grasp_depth: float = -0.001, open_fraction: float = 0.45) -> Output:
    x, y, zc, face_yaw = _cube_from_obb(target_obb)
    yaw = M.tangential_yaw(x, y, face_yaw)
    logger.info("[pick] cube at (%.3f, %.3f, %.3f) jaw yaw %.0f deg", x, y, zc, np.rad2deg(yaw))
    ctx.tool("robot.set_gripper", fraction=open_fraction, settle_steps=25)
    M.transit(ctx, x, y, yaw)
    M.move(ctx, x, y, zc + 0.03, yaw)
    M.move(ctx, x, y, zc - grasp_depth, yaw)
    closed = float(ctx.tool("robot.close_gripper", settle_steps=45)["position"])
    if closed < min_closed:
        ctx.tool("robot.set_gripper", fraction=open_fraction, settle_steps=15)
        M.move(ctx, x, y, M.TRANSIT_Z, yaw)
        raise ToolError("so101.pick", f"gripper closed on nothing (fraction {closed:.3f})")
    M.move(ctx, x, y, zc + 0.055, yaw)
    held = M.gripper(ctx)
    if held < min_closed:
        ctx.tool("robot.set_gripper", fraction=open_fraction, settle_steps=15)
        raise ToolError("so101.pick", f"cube slipped during lift (fraction {held:.3f})")
    logger.info("[pick] holding (gripper %.3f)", held)
    return {"grasp_xyz": [x, y, zc], "closed_fraction": closed}
