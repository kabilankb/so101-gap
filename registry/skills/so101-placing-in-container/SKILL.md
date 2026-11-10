---
name: so101-placing-in-container
description: >
  Puts the cube held by the LeRobot SO-101 into the open green box (container_obb),
  sends the arm home and asks the VLM whether the cube is now inside; with a colour
  order each colour gets its own quadrant. Use when an SO-101 task places a picked cube
  into the box, after so101-picking-cube. Coordinator contract:
  declare_subgraph(skill='so101-placing-in-container', inputs={'container_obb':
  'OrientedBoundingBox'} (plus 'color': 'str' inside a so101-next-cube loop),
  outputs={}, exit_success_values=['verified', 'missed'], on_error='blocked',
  stage='place'). Single cube: verified->done, missed/blocked->abort. Loop: all three
  exits -> so101-next-cube.
license: Apache-2.0
compatibility: requires gap>=0.1
metadata: {category: placing, tags: [so101, placing, container, vlm, verification]}
gap:
  requires: {}
  allowed_tools:
    - robot.get_ee_pose
    - robot.go_to_pose_cartesian
    - robot.go_home
    - robot.get_observation
    - vlm.query_yes_no
  required_inputs:
    container_obb: OrientedBoundingBox
  exit_conditions:
    verified: The VLM confirmed the cube is inside the box. Single cube → done; loop → back to so101-next-cube.
    missed: The VLM says the cube is not in the box. Single cube → abort; loop → back to so101-next-cube (it retries that colour).
    blocked: Motion raised during the place. Lives only in on_error. Single cube → abort; loop → back to so101-next-cube.
  canonical_scripts:
    - so101_place: scripts/so101_place.py
    - verify_in_container: scripts/verify_in_container.py
  examples:
    - title: Single-cube subgraph (red cube, literal colour)
      path: examples/canonical_subgraph.json
    - title: Loop subgraph (colour from so101-next-cube)
      path: examples/loop_subgraph.json
  hard_rules:
    - >
      Emit exactly the builder code in the body (section "Builder code"). verify is a plain type="script" node (NOT a router) whose output field "verdict" is the exit: sg.set_exit_router(router_field="verdict", success_values=["verified", "missed"]).
    - >
      Do NOT call add_exit, do NOT add noop nodes named verified or missed, do NOT add conditional edges: edges are exactly START -> put -> verify -> END. set_on_error("blocked").
    - >
      Do NOT write your own place or verify script. Do not add a target_obb input - only container_obb (and color inside a loop).
  streaming: false
---

# so101-placing-in-container

Places the held cube in the green box, then verifies the placement with the VLM.

## Builder code (copy exactly)

This is the subgraph as `gap.builder` code. `Subgraph`, `Ref`, `START` and `END` come from `gap.builder`.

```python
# single cube (literal colour):
sg = Subgraph(name="place_sg", skill="so101-placing-in-container")
sg.add_input("container_obb", type_name="OrientedBoundingBox")
sg.add_node("put", type="script", script="scripts/so101_place.py",
            inputs={"container_obb": Ref("in.container_obb"), "color": "red", "colors": "red"})
sg.add_node("verify", type="script", script="scripts/verify_in_container.py",
            inputs={"color": "red"})
sg.add_edge(START, "put")
sg.add_edge("put", "verify")
sg.add_edge("verify", END)
sg.set_exit_router(router_field="verdict", success_values=["verified", "missed"])
sg.set_on_error("blocked")

# inside a so101-next-cube loop (colour from the loop head) the differences are:
#   sg.add_input("color", type_name="str")
#   put inputs:    {"container_obb": Ref("in.container_obb"), "color": Ref("in.color"),
#                   "colors": "red,green,blue,yellow"}   # same order literal as the loop head
#   verify inputs: {"color": Ref("in.color")}
```

## Node flow (2 nodes)

```text
START → put → verify → END        exit = verify's "verdict" field: "verified" | "missed"
```

1. **`put`**: `type: script`, `script: "scripts/so101_place.py"`. It moves over
   the colour's quadrant at a safe height, descends into the box, opens the jaw
   to 45%, retracts, and goes home.
2. **`verify`**: `type: script`, `script: "scripts/verify_in_container.py"`. The
   VLM answers "is the `<colour>` cube inside the green box?" and the script
   returns `{"verdict": "verified" | "missed"}`. When `color` is set it also
   records the result for the `so101-next-cube` loop head.

```json
"edges": [["START", "put"], ["put", "verify"], ["verify", "END"]],
"conditional_edges": {},
"exit": {"router_field": "verdict", "success_values": ["verified", "missed"]},
"on_error": "blocked"
```

## Routing at the top level

| Task | `verified` | `missed` | `blocked` |
|---|---|---|---|
| Single cube | `done` | `abort` | `abort` |
| `so101-next-cube` loop | loop head | loop head | loop head |
