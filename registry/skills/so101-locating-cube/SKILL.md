---
name: so101-locating-cube
description: >
  Locates ONE named coloured cube (red, green, blue or yellow, 3 cm) on the LeRobot
  SO-101 tabletop and returns its 3D box as target_obb (DINO + VLM tournament + SAM3 +
  depth). Use when an SO-101 task names a single cube to pick; for several cubes or an
  order use so101-next-cube instead. Runs after so101-locating-container, feeds
  so101-picking-cube. Coordinator contract: declare_subgraph(skill='so101-locating-
  cube', inputs={}, outputs={'target_obb': 'OrientedBoundingBox'},
  exit_success_values=['found'], on_error='not_found'), no stage.
license: Apache-2.0
compatibility: requires gap>=0.1
metadata: {category: perception, tags: [so101, perception, cube, dino, vlm, sam3]}
gap:
  requires: {}
  allowed_tools:
    - robot.get_observation
    - grounding-dino.detect
    - vlm.query
    - vlm.query_yes_no
    - sam3.segment_box
    - sam3.segment_text
    - geometry.mask_to_world_points
    - geometry.filter_and_compute_obb
  exit_conditions:
    found: The cube was localized; target_obb is bound. Route to so101-picking-cube.
    not_found: Perception raised (cube not detected). Lives only in on_error. Route to abort.
  produces_outputs:
    target_obb: OrientedBoundingBox
  canonical_scripts:
    - perceive_dino_vlm: scripts/perceive_dino_vlm.py
  prompts:
    vlm_pairwise: prompts/vlm_pairwise.md
  examples:
    - title: The complete subgraph for the red cube (copy it, change the colour)
      path: examples/canonical_subgraph.json
  hard_rules:
    - >
      Emit exactly the builder code in the body (section "Builder code"), changing ONLY the colour words: object_name "<colour> cube" and the description, which must name the OTHER three colours as excluded.
    - >
      sg.add_exit("found") creates the noop node itself: never also call add_node("found"). It does NOT add the edge, so add_edge("found", END) yourself.
    - >
      No inputs (add no add_input). Output: set_outputs(target_obb=Ref("obb.obb")). set_on_error("not_found").
  streaming: false
---

# so101-locating-cube

Finds one named cube and returns its oriented bounding box (`target_obb`) for
`so101-picking-cube`.

## Builder code (copy exactly)

This is the subgraph as `gap.builder` code. `Subgraph`, `Ref`, `START` and `END` come from `gap.builder`.

```python
sg = Subgraph(name="cube_sg", skill="so101-locating-cube")
sg.add_node("observe", type="tool", tool="robot.get_observation")
sg.add_node("perceive", type="script", script="scripts/perceive_dino_vlm.py",
            inputs={"cameras": Ref("observe.cameras"), "object_name": "red cube",
                    "object_description": "a small solid red wooden cube (3 cm) lying on the table, "
                                          "outside the box. Not the large open green box/tray, and "
                                          "not a green, blue, yellow cube.",
                    "use_multiview": False})
sg.add_node("obb", type="tool", tool="geometry.filter_and_compute_obb",
            inputs={"points": Ref("perceive.cloud"), "eps": 0.008, "min_samples": 5})
sg.add_exit("found")            # creates the noop node "found" - never add_node("found")
sg.set_on_error("not_found")
for a, b in [(START, "observe"), ("observe", "perceive"), ("perceive", "obb"),
             ("obb", "found"), ("found", END)]:
    sg.add_edge(a, b)
sg.set_outputs(target_obb=Ref("obb.obb"))
```

## Node flow (4 nodes)

```text
observe → perceive → obb → found
```

1. **`observe`**: `type: tool`, `tool: "robot.get_observation"`.
2. **`perceive`**: `type: script`, `script: "scripts/perceive_dino_vlm.py"`,
   with these inputs:
   - `cameras: {"$ref": "observe.cameras"}`
   - `object_name: "<colour> cube"`
   - `object_description`: the colour text from the hard rules, which names the
     other three colours as excluded.
   - `use_multiview: false`
3. **`obb`**: `type: tool`, `tool: "geometry.filter_and_compute_obb"`, with
   `inputs: {points: {"$ref": "perceive.cloud"}, eps: 0.008, min_samples: 5}`.
4. **`found`**: `type: noop`, with an edge to `END`.

The colours are red, green, blue and yellow. The green **cube** is easy to
confuse with the green **box**, so the description must always exclude the box.

## Where it sits in a graph

```text
so101-locating-container ─found→ <this> ─found→ so101-picking-cube ─grasped→ so101-placing-in-container
                                    └─not_found→ abort
```
