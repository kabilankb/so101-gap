"""Build a GaP ``Connector`` for the SO-101 MuJoCo tabletop."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from gap.connector.core import Connector
from gap.connector.robot_io_env import ArmLayout, RobotIOEnv

from .ik import ARM, So101MujocoIK
from .io import So101TabletopIO

# env.py HOME (degrees) for the 5 arm joints, in radians.
HOME_RAD = tuple(np.deg2rad([0.0, -60.0, 60.0, 35.0, 0.0]).tolist())


@dataclass
class So101Config:
    arm_dof: int = 5
    num_arms: int = 1
    action_mode: str = "absolute_joints"
    control_freq: float = 30.0
    home_joints: tuple = HOME_RAD
    tcp_offset: tuple = (0.0, 0.0, 0.0)  # IK already targets the TCP site
    tcp_rotation_z: float | None = None
    arm_bases: list | None = None
    robot_urdf_path: str | None = None
    default_cameras: list = field(default_factory=lambda: ["front"])
    is_real: bool = False


class So101Connector(Connector):
    """Connector + a sim-only ``sim.check_success`` and eval helpers."""

    def __init__(self, io: So101TabletopIO, ik: So101MujocoIK, config: So101Config):
        lo, hi = io.world.lo[5], io.world.hi[5]
        layout = ArmLayout(
            joint_names=ARM,
            gripper_joint_names=("gripper",),
            gripper_fraction=lambda q: float(np.clip((q[0] - lo) / (hi - lo), 0.0, 1.0)),
            gripper_target=lambda f: np.array([lo + f * (hi - lo)]),
        )
        env = RobotIOEnv(io, (layout,), fk=lambda arm_id, q: ik.fk(np.asarray(q)))
        super().__init__(env, config, camera_names=list(config.default_cameras), ik=ik)
        self.io = io

    def _register_extra_tools(self, reg) -> None:
        reg.register_callable(
            "robot.set_gripper", self.set_gripper_settle,
            summary="Set the gripper open fraction (0 closed .. 1 fully open) and settle.",
            tags=("sim_step",),
        )
        reg.register_callable(
            "sim.check_success", self.check_success,
            summary="Privileged sim check: are all four cubes in the box?",
        )

    def set_gripper_settle(self, fraction: float, settle_steps: int = 30) -> dict:
        """Partial opening: the SO-101's hinged jaw sweeps ~100 deg when fully
        open, which drags through the table and neighbouring cubes."""
        self.set_gripper(float(fraction))
        self._settle(int(settle_steps))
        return {"position": self.get_gripper_fraction()}

    def check_success(self) -> dict:
        states = self.io.cube_states()
        return {"success": all(s["in_box"] for s in states.values()), "cubes": states}


def make_connector(seed: int = 0, gui: bool = False) -> So101Connector:
    io = So101TabletopIO(seed=seed, gui=gui)
    ik = So101MujocoIK(io.model, home=np.array(HOME_RAD))
    return So101Connector(io, ik, So101Config())
