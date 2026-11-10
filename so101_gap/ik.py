"""MuJoCo damped-least-squares IK backend for the 5-DOF SO-101.

Implements the surface GaP's ``Connector`` expects from an IK backend
(``solve_ik``, ``plan_linear``, ``trajectory_needs_joint_reverse``) — the
role cuRobo/PyRoKi play for Franka/YAM, neither of which ships an SO-101.

Poses are world-frame poses of the ``gripperframe`` site (the TCP between the
fingertips). Site axes: +x = approach (out of the fingers), +z = jaw closing
axis. A 5-DOF arm cannot reach every 6-D pose; position and the approach axis
are weighted hard, rotation about the approach (jaw yaw) softer.
"""

from __future__ import annotations

import logging

import mujoco
import numpy as np
from gap_core.types import make_pose, pose_to_matrix

logger = logging.getLogger(__name__)

ARM = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")
TCP_SITE = "gripperframe"

# Site orientation for a straight-down grasp with the jaws closing along world X.
R_DOWN = np.array([[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]])


def down_rotation(yaw: float) -> np.ndarray:
    c, s = np.cos(yaw), np.sin(yaw)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]]) @ R_DOWN


class So101MujocoIK:
    trajectory_needs_joint_reverse = False

    def __init__(self, model: mujoco.MjModel, home: np.ndarray | None = None) -> None:
        self.model = model
        self.data = mujoco.MjData(model)  # scratch: never touches the live sim
        self.site = model.site(TCP_SITE).id
        self.qadr = np.array([model.joint(n).qposadr[0] for n in ARM])
        self.dadr = np.array([model.joint(n).dofadr[0] for n in ARM])
        self.lo = model.jnt_range[[model.joint(n).id for n in ARM], 0]
        self.hi = model.jnt_range[[model.joint(n).id for n in ARM], 1]
        self.home = np.zeros(5) if home is None else np.asarray(home, float)

    # --- kinematics -------------------------------------------------------
    def fk(self, q: np.ndarray) -> np.ndarray:
        self.data.qpos[self.qadr] = q
        mujoco.mj_kinematics(self.model, self.data)
        mujoco.mj_comPos(self.model, self.data)  # mj_jacSite needs cdof/subtree com
        T = np.eye(4)
        T[:3, :3] = self.data.site_xmat[self.site].reshape(3, 3)
        T[:3, 3] = self.data.site_xpos[self.site]
        return T

    def _solve(self, T_target: np.ndarray, seed: np.ndarray, iters: int = 300,
               w_yaw: float = 0.15, w_app: float = 0.3) -> tuple[np.ndarray, float, float]:
        q = np.clip(np.asarray(seed, float).copy(), self.lo, self.hi)
        jp = np.zeros((3, self.model.nv))
        jr = np.zeros((3, self.model.nv))
        p_t, R_t = T_target[:3, 3], T_target[:3, :3]
        for _ in range(iters):
            T = self.fk(q)
            p, R = T[:3, 3], T[:3, :3]
            e_p = p_t - p
            # approach axis (site x) hard, jaw axis (site z) soft
            e_a = np.cross(R[:, 0], R_t[:, 0])
            e_y = np.cross(R[:, 2], R_t[:, 2])
            e = np.concatenate([e_p, w_app * e_a, w_yaw * e_y])
            if np.linalg.norm(e_p) < 5e-4 and (w_app < 0.3 or np.linalg.norm(e_a) < 0.01):
                break
            mujoco.mj_jacSite(self.model, self.data, jp, jr, self.site)
            Jp, Jr = jp[:, self.dadr], jr[:, self.dadr]
            J = np.vstack([Jp, w_app * Jr, w_yaw * Jr])
            dq = J.T @ np.linalg.solve(J @ J.T + 1e-4 * np.eye(9), e)
            q = np.clip(q + np.clip(dq, -0.2, 0.2), self.lo, self.hi)
        T = self.fk(q)
        pos_err = float(np.linalg.norm(p_t - T[:3, 3]))
        ang_err = float(np.arccos(np.clip(T[:3, 0] @ R_t[:, 0], -1, 1)))
        return q, pos_err, ang_err

    @staticmethod
    def _tilted(T: np.ndarray, tilt: float) -> np.ndarray:
        """Rotate the target about its own jaw axis (site z): the fingers keep the
        same contact faces, only the approach leans."""
        c, s = np.cos(tilt), np.sin(tilt)
        T2 = T.copy()
        T2[:3, :3] = T[:3, :3] @ np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])
        return T2

    TILTS = tuple(np.deg2rad(t) for t in (0, 15, -15, 30, -30, 40, -40))

    def solve(self, T_target: np.ndarray, seed=None, pos_tol=0.004, ang_tol=0.08, tilts=None,
              relax: float = 0.0):
        seeds = [s for s in (seed, self.home) if s is not None]
        rng = np.random.default_rng(0)
        seeds += [rng.uniform(self.lo, self.hi) * 0.7 for _ in range(8)]
        # Position-only solutions escape the clamped-joint local minima that the
        # orientation terms create; use them as extra seeds.
        pos_only = []
        for s in seeds:
            q, pe, ae = self._solve(T_target, s, iters=150, w_yaw=0.0, w_app=0.0)
            if pe < pos_tol:
                pos_only.append((ae, q))
        pos_only.sort(key=lambda t: t[0])
        seeds = seeds[:2] + [q for _, q in pos_only[:4]] + seeds[2:]
        best = None
        for tilt in (self.TILTS if tilts is None else tilts):
            T = self._tilted(T_target, tilt)
            for s in seeds:
                q, pe, ae = self._solve(T, s)
                if best is None or pe + 0.02 * ae < best[1]:
                    best = (q, pe + 0.02 * ae, pe, ae)
                if pe < pos_tol and ae < ang_tol:
                    return q
        if relax:
            # position exact, approach as close to the request as the arm allows
            cands = []
            for _, s in pos_only[:4]:
                q, pe, ae = self._solve(T_target, s, iters=150, w_yaw=0.0, w_app=0.05)
                if pe < pos_tol:
                    cands.append((ae, q))
            cands += [(ae, q) for ae, q in pos_only]
            if cands:
                ae, q = min(cands, key=lambda t: t[0])
                if ae < relax:
                    logger.info("SO-101 IK: relaxed approach (%.0f deg off)", np.rad2deg(ae))
                    return q
        logger.warning("SO-101 IK failed: pos_err=%.4f ang_err=%.3f", best[2], best[3])
        return None

    # --- GaP IK-backend surface ------------------------------------------
    def solve_ik(self, pose, arm_id=0, seed_joints=None, tcp_offset=None):
        seed = None if seed_joints is None else np.asarray(seed_joints[:5])
        q = self.solve(pose_to_matrix(pose), seed=seed)
        return None if q is None else [float(v) for v in q]

    def plan_linear(self, start_world_pose, end_world_pose, *, arm_id=0, tcp_offset=None,
                    seed_joints=None, step_m: float = 0.004, **_):
        """Straight TCP line (~0.12 m/s at 30 Hz), IK per waypoint seeded by the
        previous one. One approach tilt is used for the whole line; tilts are
        tried in order until the line is continuous."""
        from scipy.spatial.transform import Rotation, Slerp
        T0, T1 = pose_to_matrix(start_world_pose), pose_to_matrix(end_world_pose)
        q0 = np.asarray(seed_joints[:5], float) if seed_joints is not None else self.home
        n = max(2, int(np.ceil(np.linalg.norm(T1[:3, 3] - T0[:3, 3]) / step_m)) + 1)
        R_start = self.fk(q0)[:3, :3]  # start from the actual current orientation
        for tilt in self.TILTS:
            T1t = self._tilted(T1, tilt)
            if self.solve(T1t, seed=q0, tilts=(0.0,)) is None:
                continue
            slerp = Slerp([0, 1], Rotation.from_matrix([R_start, T1t[:3, :3]]))
            q, wps, ok = q0.copy(), [], True
            for t in np.linspace(0, 1, n)[1:]:
                T = np.eye(4)
                T[:3, 3] = (1 - t) * T0[:3, 3] + t * T1[:3, 3]
                T[:3, :3] = slerp(t).as_matrix()
                q_new, pe, ae = self._solve(T, q, iters=80)
                if pe > 0.006 or np.max(np.abs(q_new - q)) > 0.3:
                    ok = False
                    break
                q = q_new
                wps.append({"positions": [float(v) for v in q]})
            if ok:
                if tilt:
                    logger.info("plan_linear: using approach tilt %.0f deg", np.rad2deg(tilt))
                return {"waypoints": wps}
        # Free-space fallback: joint-space interpolation to the IK goal
        # (smooth, collision-unaware — the graph only uses it for transfers
        # at hover height; descents/lifts are short vertical lines above).
        q_goal = self.solve(T1, seed=q0, relax=(1.2 if T1[2, 3] > 0.05 else 0.8) if T1[2, 3] > 0.03 else 0.0)
        if q_goal is None:
            logger.warning("plan_linear: target unreachable")
            return None
        steps = max(2, int(np.ceil(np.max(np.abs(q_goal - q0)) / 0.025)))
        s = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, steps + 1)[1:])  # ease in/out
        logger.info("plan_linear: no straight line; joint-space move (%d steps)", steps)
        return {"waypoints": [{"positions": [float(v) for v in q0 + a * (q_goal - q0)]} for a in s]}

    def pose_of(self, q) -> dict:
        T = self.fk(np.asarray(q, float))
        from scipy.spatial.transform import Rotation
        x, y, z, w = Rotation.from_matrix(T[:3, :3]).as_quat()
        return make_pose(T[:3, 3], (w, x, y, z))
