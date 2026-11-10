"""SO-101 IK on the real Menagerie model (CPU only). Needs the HF scene checkout
(SO101_SCENE or ../so101-tabletop-mujoco) and graph-as-policy-core."""

import os
import sys
from pathlib import Path

import numpy as np
import pytest

mujoco = pytest.importorskip("mujoco")
pytest.importorskip("gap_core")

SCENE = Path(os.environ.get("SO101_SCENE", Path(__file__).resolve().parents[2] / "so101-tabletop-mujoco"))
if not (SCENE / "env.py").is_file():
    pytest.skip(f"scene checkout not found at {SCENE}", allow_module_level=True)
sys.path.insert(0, str(SCENE))
import env as so101_env  # noqa: E402

from so101_gap.ik import So101MujocoIK, down_rotation  # noqa: E402

HOME = np.deg2rad([0.0, -60.0, 60.0, 35.0, 0.0])


@pytest.fixture(scope="module")
def ik():
    model = so101_env.build_model(SCENE / "so101_tabletop.xml", SCENE)
    return So101MujocoIK(model, home=HOME)


def _target(x, y, z, yaw):
    T = np.eye(4)
    T[:3, :3] = down_rotation(yaw)
    T[:3, 3] = (x, y, z)
    return T


@pytest.mark.parametrize("xy", [(0.20, -0.02), (0.27, -0.14), (0.25, 0.04), (0.32, 0.0)])
def test_top_down_grasp_reachable_on_table(ik, xy):
    x, y = xy
    yaw = np.arctan2(y, x) + np.pi / 2  # jaws tangential
    q = ik.solve(_target(x, y, 0.016, yaw))
    assert q is not None
    T = ik.fk(q)
    assert np.linalg.norm(T[:3, 3] - (x, y, 0.016)) < 0.005
    assert T[2, 0] < -0.9  # approach axis points down


def test_relaxed_transit_pose(ik):
    # 10 cm above a far cube with the jaws 40 deg off tangential: needs the relaxed mode
    T = _target(0.268, -0.139, 0.10, np.deg2rad(102))
    assert ik.solve(T, relax=1.2) is not None


def test_plan_linear_vertical_descent(ik):
    from gap_core.types import matrix_to_pose

    q0 = ik.solve(_target(0.22, 0.0, 0.05, np.pi / 2))
    traj = ik.plan_linear(matrix_to_pose(ik.fk(q0)), matrix_to_pose(_target(0.22, 0.0, 0.016, np.pi / 2)),
                          seed_joints=list(q0))
    assert traj is not None and len(traj["waypoints"]) >= 5
