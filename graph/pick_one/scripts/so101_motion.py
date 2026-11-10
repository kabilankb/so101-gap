"""Shared SO-101 top-down motion helpers for the pick/place scripts.

Only ``robot.*`` tools are used, so the same scripts drive a real SO-101.
TCP = the ``gripperframe`` site between the fingertips; site +x is the
approach direction and +z the jaw-closing axis.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation

# Site orientation for a straight-down approach with the jaws closing along world X.
R_DOWN = np.array([[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]])
TRANSIT_Z = 0.10  # m, TCP height for moves across the table


def down_pose(x: float, y: float, z: float, yaw: float) -> dict:
    c, s = np.cos(yaw), np.sin(yaw)
    R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]]) @ R_DOWN
    qx, qy, qz, qw = Rotation.from_matrix(R).as_quat()
    return {"position": {"x": float(x), "y": float(y), "z": float(z)},
            "rotation": {"w": float(qw), "x": float(qx), "y": float(qy), "z": float(qz)}}


def tangential_yaw(x: float, y: float, face_yaw: float) -> float:
    """Jaw yaw on one of the cube's face directions, closest to tangential —
    the jaw orientation a 5-DOF arm can hold over the widest height range."""
    target = np.arctan2(y, x) + np.pi / 2
    cands = [face_yaw + k * np.pi / 2 for k in range(4)]
    return float(min(cands, key=lambda a: abs(np.angle(np.exp(1j * (a - target))))))


def ee_xyz(ctx) -> np.ndarray:
    p = ctx.tool("robot.get_ee_pose")["pose"]["position"]
    return np.array([p["x"], p["y"], p["z"]])


def move(ctx, x, y, z, yaw) -> None:
    ctx.tool("robot.go_to_pose_cartesian", pose=down_pose(x, y, z, yaw))


def transit(ctx, x, y, yaw, z=TRANSIT_Z) -> None:
    """Rise to transit height, cross over, ready to descend at (x, y)."""
    cur = ee_xyz(ctx)
    if cur[2] < z - 0.01:
        move(ctx, cur[0], cur[1], z, yaw)
    move(ctx, x, y, z, yaw)


def gripper(ctx) -> float:
    return float(ctx.tool("robot.get_gripper")["position"])
