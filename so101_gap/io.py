"""RobotIO driver for the HF EnvHub scene ``lerobot/so101-tabletop-mujoco``.

GaP's ``RobotIO`` boundary: the driver only measures joints + cameras and
applies one whole-robot joint-position target per control period. All
kinematics/planning live in GaP (``So101MujocoIK``) — same as a real arm.

Joint vector (radians, MuJoCo qpos order):
    shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import mujoco
import mujoco.viewer  # --gui (passive GLFW viewer)
import numpy as np
from gap.robot_io import CameraSample, JointPositionCommand, RobotSample

# HF snapshot of lerobot/so101-tabletop-mujoco (env.py + MJCF + meshes); jetson/install.sh
# downloads it next to this package.
SCENE_REPO = Path(os.environ.get(
    "SO101_SCENE", Path(__file__).resolve().parent.parent.parent / "so101-tabletop-mujoco"))


def load_env_module():
    if str(SCENE_REPO) not in sys.path:
        sys.path.insert(0, str(SCENE_REPO))
    import env as so101_env  # the EnvHub env.py from the HF repo

    return so101_env


# MuJoCo cameras look down -Z with +Y up; GaP back-projects in OpenCV
# convention (+Z forward, +Y down).
_MJ_TO_CV = np.diag([1.0, -1.0, -1.0])


class So101TabletopIO:
    """Owns one ``SO101Env`` world; exposes it through GaP's RobotIO protocol.

    GaP runs graph nodes on worker threads, but an EGL context can only be
    current on one thread. All MuJoCo stepping and rendering therefore runs on
    a single simulator-owner thread; the public methods marshal onto it.
    """

    def __init__(self, *args, **kwargs) -> None:
        from concurrent.futures import ThreadPoolExecutor

        self._owner = ThreadPoolExecutor(max_workers=1, thread_name_prefix="so101-sim")
        self._owner.submit(self._init, *args, **kwargs).result()

    def _on_owner(self, fn, *args):
        return self._owner.submit(fn, *args).result()

    def _init(
        self,
        seed: int = 0,
        cameras: tuple[str, ...] = ("front",),
        height: int = 480,
        width: int = 640,
        video_every: int = 2,
        video_size: tuple[int, int] = (360, 480),
        gui: bool = False,
    ) -> None:
        E = load_env_module()
        self.E = E
        self.env = E.SO101Env(**{**E.DEFAULTS, "observation_height": height,
                                 "observation_width": width})
        self.env.reset(seed=seed)
        self.world = self.env._world
        self.model, self.data = self.world.model, self.world.data
        self._joint_names = tuple(E.JOINTS)
        self._cams = tuple(cameras)
        self._renderer = mujoco.Renderer(self.model, height, width)
        self._h, self._w = height, width
        self._seq = 0
        self._t = 0.0
        self._dt = 1.0 / self.env.fps
        # video of the front camera, recorded during motion
        self.video_every = video_every
        self._vid_renderer = mujoco.Renderer(self.model, *video_size)
        self.frames: list[np.ndarray] = []
        self._record()
        # Live interactive MuJoCo viewer (GLFW window on $DISPLAY), synced every
        # control step from this owner thread. Offscreen renderers stay on EGL.
        self.viewer = None
        if gui:

            self.viewer = mujoco.viewer.launch_passive(
                self.model, self.data, show_left_ui=False, show_right_ui=False)
            self.viewer.cam.lookat[:] = (0.22, 0.03, 0.05)
            self.viewer.cam.distance, self.viewer.cam.azimuth, self.viewer.cam.elevation = 0.75, 200, -30
            self.viewer.sync()

    # --- RobotIO protocol -------------------------------------------------
    @property
    def joint_names(self) -> tuple[str, ...]:
        return self._joint_names

    @property
    def control_period_s(self) -> float:
        return self._dt

    def observe(self) -> RobotSample:
        return self._on_owner(self._observe)

    def exchange(self, command: JointPositionCommand) -> RobotSample:
        return self._on_owner(self._exchange, command)

    def _observe(self) -> RobotSample:
        mujoco.mj_forward(self.model, self.data)
        return self._sample(with_cameras=True)

    def _exchange(self, command: JointPositionCommand) -> RobotSample:
        q = np.asarray(command.positions, dtype=np.float64)
        lo, hi = self.world.lo, self.world.hi
        self.data.ctrl[self.world.actuators] = np.clip(q, lo, hi)
        mujoco.mj_step(self.model, self.data, nstep=self.world.substeps)
        self._seq += 1
        self._t += self._dt
        if self._seq % self.video_every == 0:
            self._record()
        if self.viewer is not None and self.viewer.is_running():
            self.viewer.sync()
        return self._sample(with_cameras=False)

    # --- helpers ----------------------------------------------------------
    def _sample(self, with_cameras: bool) -> RobotSample:
        adr = self.world.qadr
        dofadr = [self.model.joint(n).dofadr[0] for n in self._joint_names]
        cams = {name: self._camera(name) for name in self._cams} if with_cameras else {}
        return RobotSample(
            sequence=self._seq,
            timestamp_s=self._t,
            joint_positions=self.data.qpos[adr].astype(np.float64).copy(),
            joint_velocities=self.data.qvel[dofadr].astype(np.float64).copy(),
            cameras=cams,
        )

    def _camera(self, name: str) -> CameraSample:
        cid = self.model.camera(name).id
        r = self._renderer
        r.update_scene(self.data, camera=cid)
        rgb = r.render().copy()
        r.enable_depth_rendering()
        r.update_scene(self.data, camera=cid)
        depth = r.render().astype(np.float32).copy()
        r.disable_depth_rendering()
        fy = 0.5 * self._h / np.tan(np.deg2rad(self.model.cam_fovy[cid]) / 2)
        K = np.array([[fy, 0, self._w / 2], [0, fy, self._h / 2], [0, 0, 1]], dtype=np.float64)
        T = np.eye(4)
        T[:3, :3] = self.data.cam_xmat[cid].reshape(3, 3) @ _MJ_TO_CV
        T[:3, 3] = self.data.cam_xpos[cid]
        return CameraSample(rgb=rgb, depth_m=depth, intrinsics=K, pose=T, timestamp_s=self._t)

    def _record(self) -> None:
        self._vid_renderer.update_scene(self.data, camera="front")
        self.frames.append(self._vid_renderer.render().copy())

    # --- privileged evaluation only (never used by the graph) -------------
    def cube_states(self) -> dict[str, dict]:
        return self._on_owner(self._cube_states)

    def _cube_states(self) -> dict[str, dict]:
        m, d = self.model, self.data
        box = m.body(self.E.BOX_BODY).id
        c, R = d.xpos[box], d.xmat[box].reshape(3, 3)
        out = {}
        for name in self.E.CUBE_BODIES:
            p = d.xpos[m.body(name).id]
            loc = (p - c) @ R
            inside = bool(np.all(np.abs(loc[:2]) < self.E.BOX_INNER_HALF)
                          and loc[2] < self.E.IN_BOX_MAX_HEIGHT)
            out[name.removesuffix("_cube")] = {"pos": p.round(3).tolist(), "in_box": inside}
        return out

    def close(self) -> None:
        def _close():
            if self.viewer is not None:
                self.viewer.close()
            self._renderer.close()
            self._vid_renderer.close()
            self.env.close()
        self._on_owner(_close)
        self._owner.shutdown()
