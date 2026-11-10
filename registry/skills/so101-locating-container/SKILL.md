---
name: so101-locating-container
description: >
  Locates the open green box (the container cubes go into) on the LeRobot SO-101 MuJoCo
  tabletop and returns its 3D box as container_obb (arm home, then DINO + VLM tournament
  + SAM3 + depth on the front camera). Use when an SO-101 task puts cubes into the green
  box: it is ALWAYS the first subgraph, run once. Coordinator contract:
  declare_subgraph(skill='so101-locating-container', inputs={},
  outputs={'container_obb': 'OrientedBoundingBox'}, exit_success_values=['found'],
  on_error='not_found'), no stage. Whole-workflow WorkflowSpec examples to copy:
  read_skill_example('so101-locating-container', 'coordinator_single_cube') for one
  named cube, 'coordinator_loop' for several cubes / an order / all cubes.
license: Apache-2.0
compatibility: requires gap>=0.1
metadata: {category: perception, tags: [so101, perception, container, dino, vlm, sam3]}
gap:
  requires: {}
  allowed_tools:
    - robot.go_home
    - robot.get_observation
    - grounding-dino.detect
    - vlm.query
    - vlm.query_yes_no
    - sam3.segment_box
    - sam3.segment_text
    - geometry.mask_to_world_points
    - geometry.filter_and_compute_obb
  exit_conditions:
    found: The green box was localized; container_obb is bound. Route to the cube-locating or loop-head subgraph.
    not_found: Perception raised (box not detected). Lives only in on_error. Route to abort.
  produces_outputs:
    container_obb: OrientedBoundingBox
  canonical_scripts:
    - perceive_dino_vlm: scripts/perceive_dino_vlm.py
  prompts:
    vlm_pairwise: prompts/vlm_pairwise.md
  examples:
    - title: The complete subgraph (copy it)
      path: examples/canonical_subgraph.json
    - title: Coordinator WorkflowSpec for one named cube
      path: examples/coordinator_single_cube
    - title: Coordinator WorkflowSpec for several cubes / an order (loop)
      path: examples/coordinator_loop
  hard_rules:
    - >
      Emit exactly the builder code in the body (section "Builder code"). The only literals are the green-box object_name / object_description.
    - >
      sg.add_exit("found") creates the noop node itself: never also call add_node("found"). It does NOT add the edge, so add_edge("found", END) yourself.
    - >
      set_on_error("not_found") is a symbol, never a node. No inputs (add no add_input). Output: set_outputs(container_obb=Ref("obb.obb")).
  streaming: false
---

# so101-locating-container

Finds the open green box on the SO-101 tabletop and returns its oriented
bounding box (`container_obb`) for the placing skill.

## Builder code (copy exactly)

This is the subgraph as `gap.builder` code. `Subgraph`, `Ref`, `START` and `END` come from `gap.builder`.

```python
sg = Subgraph(name="container_sg", skill="so101-locating-container")
sg.add_node("home", type="tool", tool="robot.go_home")
sg.add_node("observe", type="tool", tool="robot.get_observation")
sg.add_node("perceive", type="script", script="scripts/perceive_dino_vlm.py",
            inputs={"cameras": Ref("observe.cameras"), "object_name": "green box",
                    "object_description": "the large open green box / tray with low walls that the "
                                          "cubes are sorted into. Not a small cube.",
                    "use_multiview": False})
sg.add_node("obb", type="tool", tool="geometry.filter_and_compute_obb",
            inputs={"points": Ref("perceive.cloud")})
sg.add_exit("found")            # creates the noop node "found" - never add_node("found")
sg.set_on_error("not_found")    # failure exit symbol - never a node
for a, b in [(START, "home"), ("home", "observe"), ("observe", "perceive"),
             ("perceive", "obb"), ("obb", "found"), ("found", END)]:
    sg.add_edge(a, b)
sg.set_outputs(container_obb=Ref("obb.obb"))
```

## Node flow (5 nodes)

```text
home → observe → perceive → obb → found
```

1. **`home`**: `type: tool`, `tool: "robot.go_home"`. Moves the arm out of the
   camera view.
2. **`observe`**: `type: tool`, `tool: "robot.get_observation"`. Returns the
   front RGB-D camera.
3. **`perceive`**: `type: script`, `script: "scripts/perceive_dino_vlm.py"`,
   with these inputs:
   - `cameras: {"$ref": "observe.cameras"}`
   - `object_name: "green box"`
   - `object_description: "the large open green box / tray with low walls that the cubes are sorted into. Not a small cube."`
   - `use_multiview: false`
4. **`obb`**: `type: tool`, `tool: "geometry.filter_and_compute_obb"`, with
   `inputs: {points: {"$ref": "perceive.cloud"}}`.
5. **`found`**: `type: noop`, with an edge to `END`.

Outputs: `container_obb: {"$ref": "obb.obb"}`. Exit: `success_values: ["found"]`,
`on_error: "not_found"`.

## Where it sits in a graph

```text
START → <this> ─found→ so101-locating-cube | so101-next-cube → so101-picking-cube → so101-placing-in-container
          └─not_found→ abort
```
