---
name: so101-picking-cube
description: >
  Top-down pick of one 3 cm cube with the 5-DOF LeRobot SO-101 gripper from its
  target_obb: partial jaw opening, transit, descend, close, lift, and an unprivileged
  gripper-reading check that the cube is held. Use when an SO-101 task must pick up a
  cube located by so101-locating-cube or so101-next-cube; follow it with so101-placing-
  in-container. Coordinator contract: declare_subgraph(skill='so101-picking-cube',
  inputs={'target_obb': 'OrientedBoundingBox'}, outputs={},
  exit_success_values=['grasped'], on_error='failed', stage='grasp'). failed routes to
  abort (single cube) or back to so101-next-cube (loop).
license: Apache-2.0
compatibility: requires gap>=0.1
metadata: {category: grasping, tags: [so101, grasping, top-down, ik]}
gap:
  requires: {}
  allowed_tools:
    - robot.get_ee_pose
    - robot.go_to_pose_cartesian
    - robot.close_gripper
    - robot.get_gripper
  required_inputs:
    target_obb: OrientedBoundingBox
  exit_conditions:
    grasped: The cube is held in the gripper after the lift. Route to so101-placing-in-container.
    failed: The gripper closed on nothing, the cube slipped, or IK/motion failed (a raise). Lives only in on_error. In a single-cube task route to abort; inside a so101-next-cube loop route back to the loop head.
  canonical_scripts:
    - so101_pick: scripts/so101_pick.py
  examples:
    - title: The complete subgraph (copy it)
      path: examples/canonical_subgraph.json
  references:
    - title: Why the SO-101 grasps the way it does
      path: references/so101_grasping.md
  hard_rules:
    - >
      Emit exactly the builder code in the body (section "Builder code"): ONE script node pick (scripts/so101_pick.py). Do NOT add open/close/move tool nodes and do NOT write your own pick script.
    - >
      sg.add_exit("grasped") creates the noop node itself: never also call add_node("grasped"). Add add_edge("grasped", END) yourself. set_on_error("failed"). No outputs.
  streaming: false
---

# so101-picking-cube

Picks one cube top-down with the SO-101. The SO-101 is a 5-DOF arm with a
hinged jaw, so the generic Franka grasping skills don't apply. Use this skill's
canonical script as-is.

## Builder code (copy exactly)

This is the subgraph as `gap.builder` code. `Subgraph`, `Ref`, `START` and `END` come from `gap.builder`.

```python
sg = Subgraph(name="pick_sg", skill="so101-picking-cube")
sg.add_input("target_obb", type_name="OrientedBoundingBox")
sg.add_node("pick", type="script", script="scripts/so101_pick.py",
            inputs={"target_obb": Ref("in.target_obb")})
sg.add_exit("grasped")          # creates noop "grasped" - never add_node("grasped")
sg.set_on_error("failed")
sg.add_edge(START, "pick")
sg.add_edge("pick", "grasped")
sg.add_edge("grasped", END)
```

## Node flow (2 nodes)

```text
pick → grasped
```

- **`pick`**: `type: script`, `script: "scripts/so101_pick.py"`, with
  `inputs: {target_obb: {"$ref": "in.target_obb"}}`.
- **`grasped`**: `type: noop`, with an edge to `END`.

Subgraph contract:

```json
"inputs": {"target_obb": "OrientedBoundingBox"},
"outputs": {},
"exit": {"router_field": null, "success_values": ["grasped"]},
"on_error": "failed"
```

## What the script does

1. Opens the jaw to 45%.
2. Rises to 10 cm and moves over the cube.
3. Hovers 3 cm above it, then descends to the cube's centre height.
4. Closes the jaw. If the gripper reading is 0.06 or less it closed on
   nothing, so the script raises.
5. Lifts 5.5 cm. If the reading drops to 0.06 or less the cube slipped, so the
   script raises.

Either raise routes the subgraph to `failed`.
