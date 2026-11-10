"""Write graph/color_sort/workflow.json (the GaP v3 graph for SO-101 colour sorting).

    START -> box --found--> next --pick--> grasp --grasped--> place --verified/missed--+
                               |  ^           |failed                                    |
                     finished  |  +-----------+------------------------------------------+
                               v
                             done
"""

import json
from pathlib import Path

OBB = "OrientedBoundingBox"
ORDER = "red,green,blue,yellow"  # default colour order (run.py --order rewrites it)
BOX_DESC = ("the large open green box / tray with low walls that the cubes are sorted into. "
            "Not a small cube.")


def perceive(name_ref, desc_ref):
    return {
        "type": "script", "script": "scripts/perceive_dino_vlm.py",
        "inputs": {"cameras": {"$ref": "observe.cameras"}, "object_name": name_ref,
                   "object_description": desc_ref, "use_multiview": False},
    }


wf = {
    "version": 3,
    "meta": {
        "name": "so101_color_sort",
        "description": (
            "SO-101 (lerobot/so101-tabletop-mujoco): pick the coloured cubes one at a time in the "
            "requested colour order and place each in its own quadrant of the green box. "
            "Perception: Grounding DINO + VLM tournament + SAM3 on the front RGB-D camera. "
            "Each placement is verified by the VLM; misses are retried with fresh perception."
        ),
    },
    "nodes": {
        "box": {"type": "subgraph", "ref": "box_sg"},
        "next": {"type": "subgraph", "ref": "next_sg", "inputs": {"colors": ORDER}},
        "grasp": {"type": "subgraph", "ref": "grasp_sg"},
        "place": {"type": "subgraph", "ref": "place_sg", "inputs": {"colors": ORDER}},
        "done": {"type": "end", "status": "success"},
        "abort": {"type": "end", "status": "failure", "recovery": [
            {"tool": "robot.open_gripper", "inputs": {}},
            {"tool": "robot.go_home", "inputs": {}}]},
    },
    "edges": [["START", "box"]],
    "conditional_edges": {
        "box": {"router_field": "exit", "mapping": {"found": "next", "not_found": "abort"}},
        "next": {"router_field": "exit",
                 "mapping": {"found": "grasp", "finished": "done", "not_found": "next"}},
        "grasp": {"router_field": "exit", "mapping": {"grasped": "place", "failed": "next"}},
        "place": {"router_field": "exit",
                  "mapping": {"verified": "next", "missed": "next", "blocked": "next"}},
    },
    "subgraphs": {
        # 1. the box: perceived once (it does not move)
        "box_sg": {
            "skill": "perceiving-objects",
            "inputs": {},
            "outputs": {"container_obb": {"$ref": "obb.obb"}},
            "nodes": {
                "home": {"type": "tool", "tool": "robot.go_home"},
                "observe": {"type": "tool", "tool": "robot.get_observation"},
                "perceive": perceive("green box", BOX_DESC),
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
        # 2. loop head: next colour in order -> perceive that cube
        "next_sg": {
            "skill": "perceiving-objects",
            "inputs": {"colors": "str"},
            "outputs": {"target_obb": {"$ref": "obb.obb"}, "color": {"$ref": "choose.color"}},
            "nodes": {
                "choose": {"type": "script", "script": "scripts/choose_color.py",
                           "inputs": {"colors": {"$ref": "in.colors"}}},
                "route": {"type": "router", "script": "scripts/route_choice.py",
                          "inputs": {"finished": {"$ref": "choose.finished"}}},
                "observe": {"type": "tool", "tool": "robot.get_observation"},
                "perceive": perceive({"$ref": "choose.object_name"},
                                     {"$ref": "choose.object_description"}),
                "obb": {"type": "tool", "tool": "geometry.filter_and_compute_obb",
                        "inputs": {"points": {"$ref": "perceive.cloud"}, "eps": 0.008,
                                   "min_samples": 5}},
                "found": {"type": "noop"},
                "finished": {"type": "noop"},
            },
            "edges": [["START", "choose"], ["choose", "route"], ["observe", "perceive"],
                      ["perceive", "obb"], ["obb", "found"], ["found", "END"],
                      ["finished", "END"]],
            "conditional_edges": {
                "route": {"router_field": None,
                          "mapping": {"pick": "observe", "finished": "finished"}}},
            "exit": {"router_field": None, "success_values": ["found", "finished"]},
            "on_error": "not_found",
        },
        # 3. pick it
        "grasp_sg": {
            "skill": "generic",
            "inputs": {"target_obb": OBB},
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
        # 4. place it in its colour's quadrant, then VLM-verify
        "place_sg": {
            "skill": "generic",
            "inputs": {"container_obb": OBB, "color": "str", "colors": "str"},
            "outputs": {"place_xyz": {"$ref": "put.place_xyz"}},
            "nodes": {
                "put": {"type": "script", "script": "scripts/so101_place.py",
                        "inputs": {"container_obb": {"$ref": "in.container_obb"},
                                   "color": {"$ref": "in.color"},
                                   "colors": {"$ref": "in.colors"}}},
                "verify": {"type": "router", "script": "scripts/verify_color.py",
                           "inputs": {"color": {"$ref": "in.color"}}},
                "verified": {"type": "noop"},
                "missed": {"type": "noop"},
            },
            "edges": [["START", "put"], ["put", "verify"], ["verified", "END"],
                      ["missed", "END"]],
            "conditional_edges": {
                "verify": {"router_field": None,
                           "mapping": {"verified": "verified", "missed": "missed"}}},
            "exit": {"router_field": None, "success_values": ["verified", "missed"]},
            "on_error": "blocked",
        },
    },
}

if __name__ == "__main__":
    out = Path(__file__).parent / "color_sort" / "workflow.json"
    out.write_text(json.dumps(wf, indent=2) + "\n")
    print("wrote", out)
