# Why the SO-101 grasps the way it does

The LeRobot SO-101 is a **5-DOF** arm (shoulder pan, shoulder lift, elbow flex,
wrist flex, wrist roll) with a **hinged** jaw. Three consequences shape the
canonical `so101_pick.py`:

- **A straight-down grasp is fully determined.** With the approach locked
  vertical, the jaw yaw is no longer free. The script closes the jaws across
  the cube faces nearest *tangential* to the arm's reach, because that is the
  orientation the arm can hold over the widest range of heights. For far poses
  the IK leans the approach 15–40° about the jaw axis, so the fingers still
  land on the same faces.
- **Partial opening (45%).** Fully open, the moving jaw swings about 100°
  through the table and neighbouring cubes. The arm motors are torque-limited
  (about 3 N·m), so that contact shoves the whole arm several centimetres.
- **Grasp at cube-centre height.** A lower grasp wedges the cube against the
  palm with the jaw fully closed. The gripper then reads like a miss even
  though the cube is held.

Grasp success comes from the gripper's open fraction alone. A 3 cm cube held
reads about 0.15, and an empty close reads under 0.06.
