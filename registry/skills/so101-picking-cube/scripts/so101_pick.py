"""Top-down pick of one perceived cube with the 5-DOF LeRobot SO-101.

From the perceived OBB (front-camera depth) it takes the centre XY, the top
height and the cube's face yaw, and closes the jaws across the face pair
nearest to *tangential* to the arm's reach (the orientation a 5-DOF arm can
hold over the widest height range).

Motion: open the jaw to ~45 % (fully open, the hinged jaw sweeps ~100 deg
through the table and neighbouring cubes) → rise to transit height → move over
the cube → hover → descend to cube-centre height → close → lift.

Success is unprivileged: the closed gripper must stop on the cube (open
fraction above ``min_closed``) and still hold it after the lift. A miss raises
``GraspFailed``, which routes the subgraph to its ``on_error`` exit (``failed``).

Self-contained on purpose: canonical scripts are copied per subgraph into
generated workflows, so they cannot import sibling helper modules.
"""

from __future__ import annotations

import logging
from typing import TypedDict

import numpy as np
from gap import NodeContext
from gap_core.errors import GraspFailed
from gap_core.types import OrientedBoundingBox
from scipy.spatial.transform import Rotation

logger = logging.getLogger(__name__)

CUBE = 0.03          # m, cube edge
TRANSIT_Z = 0.10     # m, TCP height for moves across the table
# gripperframe site orientation for a straight-down approach, jaws closing along world X
_R_DOWN = np.array([[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]])


class Output(TypedDict):
    grasp_xyz: list[float]
    closed_fraction: float


def _down_pose(x: float, y: float, z: float, yaw: float) -> dict:
    c, s = np.cos(yaw), np.sin(yaw)
    qx, qy, qz, qw = Rotation.from_matrix(np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]]) @ _R_DOWN).as_quat()
    return {"position": {"x": float(x), "y": float(y), "z": float(z)},
            "rotation": {"w": float(qw), "x": float(qx), "y": float(qy), "z": float(qz)}}


def _move(ctx: NodeContext, x: float, y: float, z: float, yaw: float) -> None:
    ctx.tool("robot.go_to_pose_cartesian", pose=_down_pose(x, y, z, yaw))


def _cube_from_obb(obb: OrientedBoundingBox) -> tuple[float, float, float, float]:
    c, e, q = obb["center"], obb["extent"], obb["orientation"]
    R = Rotation.from_quat([q["x"], q["y"], q["z"], q["w"]]).as_matrix()
    top = c["z"] + float(np.abs(R[2, :]) @ np.array([e["x"], e["y"], e["z"]]))
    zc = max(top - CUBE / 2, CUBE / 2 - 0.003)
    axis = R[:, int(np.argmin(np.abs(R[2, :])))]          # most horizontal OBB axis = a face normal
    return float(c["x"]), float(c["y"]), zc, float(np.arctan2(axis[1], axis[0]))


def _tangential_yaw(x: float, y: float, face_yaw: float) -> float:
    target = np.arctan2(y, x) + np.pi / 2
    cands = [face_yaw + k * np.pi / 2 for k in range(4)]
    return float(min(cands, key=lambda a: abs(np.angle(np.exp(1j * (a - target))))))


def run(ctx: NodeContext, target_obb: OrientedBoundingBox, min_closed: float = 0.06,
        open_fraction: float = 0.45) -> Output:
    x, y, zc, face_yaw = _cube_from_obb(target_obb)
    yaw = _tangential_yaw(x, y, face_yaw)
    logger.info("[pick] cube at (%.3f, %.3f, %.3f) jaw yaw %.0f deg", x, y, zc, np.rad2deg(yaw))
    ctx.tool("robot.set_gripper", fraction=open_fraction, settle_steps=25)
    p = ctx.tool("robot.get_ee_pose")["pose"]["position"]
    if p["z"] < TRANSIT_Z - 0.01:
        _move(ctx, p["x"], p["y"], TRANSIT_Z, yaw)
    _move(ctx, x, y, TRANSIT_Z, yaw)
    _move(ctx, x, y, zc + 0.03, yaw)
    _move(ctx, x, y, zc + 0.001, yaw)
    closed = float(ctx.tool("robot.close_gripper", settle_steps=45)["position"])
    if closed < min_closed:
        ctx.tool("robot.set_gripper", fraction=open_fraction, settle_steps=15)
        _move(ctx, x, y, TRANSIT_Z, yaw)
        raise GraspFailed(f"gripper closed on nothing (open fraction {closed:.3f})")
    _move(ctx, x, y, zc + 0.055, yaw)
    held = float(ctx.tool("robot.get_gripper")["position"])
    if held < min_closed:
        ctx.tool("robot.set_gripper", fraction=open_fraction, settle_steps=15)
        raise GraspFailed(f"cube slipped during the lift (open fraction {held:.3f})")
    logger.info("[pick] holding (gripper %.3f)", held)
    return {"grasp_xyz": [x, y, zc], "closed_fraction": closed}
