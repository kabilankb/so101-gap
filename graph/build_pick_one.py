"""Template: the smallest useful graph. Pick ONE named cube and put it in the box.

    python graph/build_pick_one.py --color red        # writes graph/pick_one/
    ./jetson/run_demo.sh --graph graph/pick_one --gui
    GRAPH=graph/pick_one docker compose run --rm so101

    START → box ─found─→ target ─found─→ grasp ─grasped─→ place ─verified─→ done ✓
              └─────────────┴──────────────┴────────────────┴──(anything else)─→ abort ✗

Copy this file to start your own graph. A graph is a dict with:
  nodes             top-level nodes (here: one per subgraph + the done/abort ends)
  edges             unconditional edges ([["START", "box"]])
  conditional_edges how each subgraph's exit label routes to the next node
  subgraphs         each one: a skill, typed inputs/outputs, nodes (tool | script | router | noop),
                    edges, conditional_edges, exit labels, and an on_error label
Outputs flow between subgraphs by name (box_sg's container_obb → place_sg's container_obb).
Node scripts live in scripts/ and call robot/vision tools through ctx.tool(...).
"""

import argparse
import json
import shutil
from pathlib import Path

HERE = Path(__file__).parent
SCRIPTS = ["perceive_dino_vlm.py", "so101_motion.py", "so101_pick.py", "so101_place.py",
           "verify_color.py", "sort_state.py"]
OBB = "OrientedBoundingBox"


def perceive(name, description):
    return {"type": "script", "script": "scripts/perceive_dino_vlm.py",
            "inputs": {"cameras": {"$ref": "observe.cameras"}, "object_name": name,
                       "object_description": description, "use_multiview": False}}


def build(color: str) -> dict:
    return {
        "version": 3,
        "meta": {"name": f"so101_pick_one_{color}",
                 "description": f"SO-101: pick the {color} cube and put it in the green box (template)."},
        "nodes": {
            "box": {"type": "subgraph", "ref": "box_sg"},
            "target": {"type": "subgraph", "ref": "target_sg"},
            "grasp": {"type": "subgraph", "ref": "grasp_sg"},
            "place": {"type": "subgraph", "ref": "place_sg",
                      "inputs": {"color": color, "colors": color}},
            "done": {"type": "end", "status": "success"},
            "abort": {"type": "end", "status": "failure", "recovery": [
                {"tool": "robot.set_gripper", "inputs": {"fraction": 0.45}},
                {"tool": "robot.go_home", "inputs": {}}]},
        },
        "edges": [["START", "box"]],
        "conditional_edges": {
            "box": {"router_field": "exit", "mapping": {"found": "target", "not_found": "abort"}},
            "target": {"router_field": "exit", "mapping": {"found": "grasp", "not_found": "abort"}},
            "grasp": {"router_field": "exit", "mapping": {"grasped": "place", "failed": "abort"}},
            "place": {"router_field": "exit",
                      "mapping": {"verified": "done", "missed": "abort", "blocked": "abort"}},
        },
        "subgraphs": {
            "box_sg": {
                "skill": "perceiving-objects", "inputs": {},
                "outputs": {"container_obb": {"$ref": "obb.obb"}},
                "nodes": {
                    "home": {"type": "tool", "tool": "robot.go_home"},
                    "observe": {"type": "tool", "tool": "robot.get_observation"},
                    "perceive": perceive("green box", "the large open green box / tray with low walls. "
                                                      "Not a small cube."),
                    "obb": {"type": "tool", "tool": "geometry.filter_and_compute_obb",
                            "inputs": {"points": {"$ref": "perceive.cloud"}}},
                    "found": {"type": "noop"},
                },
                "edges": [["START", "home"], ["home", "observe"], ["observe", "perceive"],
                          ["perceive", "obb"], ["obb", "found"], ["found", "END"]],
                "conditional_edges": {},
                "exit": {"router_field": None, "success_values": ["found"]},
                "on_error": "not_found",
            },
            "target_sg": {
                "skill": "perceiving-objects", "inputs": {},
                "outputs": {"target_obb": {"$ref": "obb.obb"}},
                "nodes": {
                    "observe": {"type": "tool", "tool": "robot.get_observation"},
                    "perceive": perceive(f"{color} cube", f"a small solid {color} wooden cube (3 cm) on the "
                                                          f"table. Not the large green box."),
                    "obb": {"type": "tool", "tool": "geometry.filter_and_compute_obb",
                            "inputs": {"points": {"$ref": "perceive.cloud"}, "eps": 0.008,
                                       "min_samples": 5}},
                    "found": {"type": "noop"},
                },
                "edges": [["START", "observe"], ["observe", "perceive"], ["perceive", "obb"],
                          ["obb", "found"], ["found", "END"]],
                "conditional_edges": {},
                "exit": {"router_field": None, "success_values": ["found"]},
                "on_error": "not_found",
            },
            "grasp_sg": {
                "skill": "generic", "inputs": {"target_obb": OBB},
                "outputs": {"grasp_xyz": {"$ref": "pick.grasp_xyz"}},
                "nodes": {
                    "pick": {"type": "script", "script": "scripts/so101_pick.py",
                             "inputs": {"target_obb": {"$ref": "in.target_obb"}}},
                    "grasped": {"type": "noop"},
                },
                "edges": [["START", "pick"], ["pick", "grasped"], ["grasped", "END"]],
                "conditional_edges": {},
                "exit": {"router_field": None, "success_values": ["grasped"]},
                "on_error": "failed",
            },
            "place_sg": {
                "skill": "generic",
                "inputs": {"container_obb": OBB, "color": "str", "colors": "str"},
                "outputs": {"place_xyz": {"$ref": "put.place_xyz"}},
                "nodes": {
                    "put": {"type": "script", "script": "scripts/so101_place.py",
                            "inputs": {"container_obb": {"$ref": "in.container_obb"},
                                       "color": {"$ref": "in.color"}, "colors": {"$ref": "in.colors"}}},
                    "verify": {"type": "router", "script": "scripts/verify_color.py",
                               "inputs": {"color": {"$ref": "in.color"}}},
                    "verified": {"type": "noop"},
                    "missed": {"type": "noop"},
                },
                "edges": [["START", "put"], ["put", "verify"], ["verified", "END"], ["missed", "END"]],
                "conditional_edges": {"verify": {"router_field": None,
                                                 "mapping": {"verified": "verified", "missed": "missed"}}},
                "exit": {"router_field": None, "success_values": ["verified", "missed"]},
                "on_error": "blocked",
            },
        },
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--color", default="red", choices=["red", "green", "blue", "yellow"])
    ap.add_argument("--out", type=Path, default=HERE / "pick_one")
    args = ap.parse_args()
    (args.out / "scripts").mkdir(parents=True, exist_ok=True)
    for name in SCRIPTS:  # graphs are self-contained: copy the node scripts they use
        shutil.copy2(HERE / "color_sort" / "scripts" / name, args.out / "scripts" / name)
    (args.out / "workflow.json").write_text(json.dumps(build(args.color), indent=2) + "\n")
    print("wrote", args.out)
