---
name: so101-next-cube
description: >
  Loop head for SO-101 tasks over SEVERAL coloured cubes ('sort the cubes red, green,
  blue, yellow', 'put all the cubes in the box', 'put the blue then the red cube in the
  box'). Each pass picks the next colour of the order not yet verified in the box and
  locates that cube, or exits finished when all are done. Use when the task handles more
  than one cube. Coordinator contract: declare_subgraph(skill='so101-next-cube',
  inputs={}, outputs={'target_obb': 'OrientedBoundingBox', 'color': 'str'},
  exit_success_values=['found', 'finished'], on_error='not_found'), no stage. Routes:
  found->pick, finished->done, not_found->itself; pick failed and every place exit go
  back to it. See read_skill_example('so101-locating-container', 'coordinator_loop').
license: Apache-2.0
compatibility: requires gap>=0.1
metadata: {category: perception, tags: [so101, loop, sorting, perception, dino, vlm, sam3]}
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
    found: The next cube was localized; target_obb and color are bound. Route to so101-picking-cube.
    finished: Every colour in the order is verified in the box (or out of attempts). The loop is done — route to done (success), NOT abort.
    not_found: Perception raised for this pass. Lives only in on_error. Route back to this same loop head (it retries, then gives up on that colour).
  produces_outputs:
    target_obb: OrientedBoundingBox
    color: str
  canonical_scripts:
    - choose_color: scripts/choose_color.py
    - route_choice: scripts/route_choice.py
    - perceive_dino_vlm: scripts/perceive_dino_vlm.py
  prompts:
    vlm_pairwise: prompts/vlm_pairwise.md
  examples:
    - title: The complete loop-head subgraph (copy it, set the colour order)
      path: examples/canonical_subgraph.json
  hard_rules:
    - >
      Emit exactly the builder code in the body (section "Builder code"). Change ONLY the colors literal on the choose node to the task's order (comma-separated from red, green, blue, yellow).
    - >
      route is a type="router" node reached by add_edge("choose", "route") and left ONLY through add_conditional_edges("route", {"pick": "observe", "finished": "finished"}) - no router_field, no plain edges out of route.
    - >
      add_exit("found") and add_exit("finished") create the noop nodes: never add_node them; add their edges to END yourself. set_on_error("not_found"). No inputs. Outputs: target_obb=Ref("obb.obb"), color=Ref("choose.color").
    - >
      Top level: next found -> grasp, finished -> done, not_found -> next. grasp failed -> next. place verified / missed / blocked -> next. Never route a loop exit to abort.
  streaming: false
---

# so101-next-cube

The loop head for multi-cube tasks. Each pass handles one colour. The loop ends
when every colour has been verified in the box by `so101-placing-in-container`,
or after 3 attempts per colour.

## Builder code (copy exactly)

This is the subgraph as `gap.builder` code. `Subgraph`, `Ref`, `START` and `END` come from `gap.builder`.

```python
sg = Subgraph(name="next_sg", skill="so101-next-cube")
sg.add_node("choose", type="script", script="scripts/choose_color.py",
            inputs={"colors": "red,green,blue,yellow"})        # the task's colour order
sg.add_node("route", type="router", script="scripts/route_choice.py",
            inputs={"finished": Ref("choose.finished")})
sg.add_node("observe", type="tool", tool="robot.get_observation")
sg.add_node("perceive", type="script", script="scripts/perceive_dino_vlm.py",
            inputs={"cameras": Ref("observe.cameras"),
                    "object_name": Ref("choose.object_name"),
                    "object_description": Ref("choose.object_description"),
                    "use_multiview": False})
sg.add_node("obb", type="tool", tool="geometry.filter_and_compute_obb",
            inputs={"points": Ref("perceive.cloud"), "eps": 0.008, "min_samples": 5})
sg.add_exit("found")            # creates noop "found"
sg.add_exit("finished")         # creates noop "finished"
sg.set_on_error("not_found")
sg.add_edge(START, "choose")
sg.add_edge("choose", "route")
sg.add_conditional_edges("route", {"pick": "observe", "finished": "finished"})
for a, b in [("observe", "perceive"), ("perceive", "obb"), ("obb", "found"),
             ("found", END), ("finished", END)]:
    sg.add_edge(a, b)
sg.set_outputs(target_obb=Ref("obb.obb"), color=Ref("choose.color"))
```

## Node flow

```text
choose → route ─pick→ observe → perceive → obb → found
           └─finished→ finished
```

1. **`choose`**: `type: script`, `script: "scripts/choose_color.py"`, with
   `inputs: {colors: "red,green,blue,yellow"}`. Put the task's order here.
2. **`route`**: `type: router`, `script: "scripts/route_choice.py"`, with
   `inputs: {finished: {"$ref": "choose.finished"}}`. Its conditional edge,
   `{router_field: null, mapping: {pick: observe, finished: finished}}`, sends
   a pass to perception or ends the loop.
3. **`observe`**: `type: tool`, `tool: "robot.get_observation"`.
4. **`perceive`**: `type: script`, `script: "scripts/perceive_dino_vlm.py"`,
   with these inputs:
   - `cameras: {"$ref": "observe.cameras"}`
   - `object_name: {"$ref": "choose.object_name"}`
   - `object_description: {"$ref": "choose.object_description"}`
   - `use_multiview: false`
5. **`obb`**: `type: tool`, `tool: "geometry.filter_and_compute_obb"`, with
   `inputs: {points: {"$ref": "perceive.cloud"}, eps: 0.008, min_samples: 5}`.
6. **`found`** and **`finished`**: `type: noop` exits, each with an edge to
   `END`.

## Loop wiring at the top level

```text
so101-locating-container ─found→ next(<this>) ─found→ grasp(so101-picking-cube) ─grasped→ place(so101-placing-in-container)
                                   │  ▲  ▲                 │ failed                       │ verified / missed / blocked
                          finished │  │  └─────────────────┴──────────────────────────────┘
                                   ▼  └── not_found (retry)
                                 done
```

Pass `color: {"$ref": ...}` into `so101-placing-in-container`, and give it the same
`colors` order. It uses them to put each colour in its own quadrant and to mark
the colour done once it's verified.
