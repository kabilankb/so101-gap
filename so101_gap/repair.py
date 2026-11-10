"""Deterministic repair of LLM-generated SO-101 graphs.

A local 30B model reliably picks the right skills and fills each subgraph
correctly from the skill's canonical builder code, but sometimes slips on the
top-level wiring. Each slip below is fixed only in the way the SO-101 skill
contracts (registry/skills/*/SKILL.md) prescribe, and every change is reported:

  R0  A declared subgraph that the top-level routes use but that has no top-level
      node gets one (node name == subgraph name, as in the coordinator examples).
  R1  The so101-locating-container subgraph must exist and run first
      (START → container; found → the previous first step; not_found → abort).
      If the model left it out or never connected it, the skill's canonical
      subgraph is inserted / rewired.
  R2  In a single-cube graph (no so101-next-cube loop) so101-placing-in-container
      takes its colour as a literal. If the model declared a `color` input that
      nothing produces, the input is dropped and the colour named in the task
      is written in.
  R3  Top-level nodes unreachable from START (and their subgraphs) are removed.
  R5  Several place steps in one graph share ONE colour order (the order the
      graph handles the colours), so each cube gets its own quadrant; verify
      labels are normalised to "<colour> cube".
  R4  Conditional edges leaving a subgraph node route on its exit, so their
      router_field must be "exit" (GaP's validator accepts null, the runtime
      then fails with "cannot read field ''").

After repairing, the caller re-validates with GaP's own validator.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

REGISTRY = Path(__file__).resolve().parent.parent / "registry" / "skills"
COLOURS = ("red", "green", "blue", "yellow")


def _skill_of(w: dict, node: str) -> str | None:
    nd = w["nodes"].get(node, {})
    if nd.get("type") != "subgraph":
        return None
    return w["subgraphs"].get(nd.get("ref"), {}).get("skill")


def _targets(w: dict, node: str) -> set[str]:
    out = {d for s, d in w["edges"] if s == node}
    ce = w["conditional_edges"].get(node)
    if ce:
        out |= set(ce["mapping"].values())
    return out


def _start_target(w: dict) -> str | None:
    return next((d for s, d in w["edges"] if s == "START"), None)


def _reachable(w: dict) -> set[str]:
    seen, todo = set(), [_start_target(w)]
    while todo:
        n = todo.pop()
        if n is None or n in seen or n == "END":
            continue
        seen.add(n)
        todo.extend(_targets(w, n))
    return seen


def _ensure_abort(w: dict) -> None:
    if "abort" not in w["nodes"]:
        w["nodes"]["abort"] = {"type": "end", "status": "failure", "recovery": [
            {"tool": "robot.set_gripper", "inputs": {"fraction": 0.45}},
            {"tool": "robot.go_home", "inputs": {}}]}


def _copy_skill_scripts(skill: str, wf_dir: Path) -> None:
    for f in (REGISTRY / skill / "scripts").glob("*.py"):
        dst = wf_dir / "scripts" / f.name
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)


def _replace_ref(obj, ref: str, value):
    if isinstance(obj, dict):
        if obj == {"$ref": ref}:
            return value
        return {k: _replace_ref(v, ref, value) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_replace_ref(v, ref, value) for v in obj]
    return obj


def repair(wf_dir: str | Path, instruction: str = "") -> list[str]:
    """Repair ``<wf_dir>/workflow.json`` in place; return what was changed."""
    wf_dir = Path(wf_dir)
    path = wf_dir / "workflow.json"
    w = json.loads(path.read_text())
    w.setdefault("edges", [])
    w.setdefault("conditional_edges", {})
    notes: list[str] = []

    # R0: routed-to / routed-from subgraphs need top-level nodes
    named = set(w["conditional_edges"]) | {d for ce in w["conditional_edges"].values()
                                           for d in ce.get("mapping", {}).values()}
    for n in sorted(named):
        if n not in w["nodes"] and n in w["subgraphs"]:
            w["nodes"][n] = {"type": "subgraph", "ref": n}
            notes.append(f"R0: added the missing top-level node for subgraph {n!r}")
    for n in ("done", "abort"):
        if n in named and n not in w["nodes"]:
            _ensure_abort(w) if n == "abort" else w["nodes"].setdefault(
                "done", {"type": "end", "status": "success"})

    # R1: the container subgraph exists and runs first
    containers = [n for n in w["nodes"] if _skill_of(w, n) == "so101-locating-container"]
    # a container that only hands over to another container is redundant (an earlier repair
    # inserted one before the model's own was wired up): start at the model's
    first0 = _start_target(w)
    if first0 in containers:
        nxt = w["conditional_edges"].get(first0, {}).get("mapping", {}).get("found")
        if nxt in containers and nxt != first0:
            w["edges"] = [e for e in w["edges"] if e[0] != "START"] + [["START", nxt]]
            w["conditional_edges"].pop(first0, None)
            ref = w["nodes"].pop(first0).get("ref")
            if ref and not any(o.get("ref") == ref for o in w["nodes"].values()):
                w["subgraphs"].pop(ref, None)
            containers.remove(first0)
            notes.append(f"R1: removed the redundant container step {first0!r}; START -> {nxt!r}")
    first = _start_target(w)
    if not containers:
        sg = json.loads((REGISTRY / "so101-locating-container" / "examples" /
                         "canonical_subgraph.json").read_text())
        name = "container_sg"
        while name in w["subgraphs"] or name in w["nodes"]:
            name += "_"
        w["subgraphs"][name] = sg
        w["nodes"][name] = {"type": "subgraph", "ref": name}
        _copy_skill_scripts("so101-locating-container", wf_dir)
        containers = [name]
        notes.append(f"R1: inserted the canonical so101-locating-container subgraph as {name!r}")
    box = containers[0]
    if first != box:
        _ensure_abort(w)
        w["edges"] = [e for e in w["edges"] if e[0] != "START"] + [["START", box]]
        if first is not None and first != box:
            w["conditional_edges"][box] = {"router_field": "exit",
                                           "mapping": {"found": first, "not_found": "abort"}}
        notes.append(f"R1: START -> {box!r} (found -> {first!r}, not_found -> 'abort')")

    # R2: single-cube place with an unbound colour input
    has_loop = any(_skill_of(w, n) == "so101-next-cube" for n in w["nodes"])
    if not has_loop:
        colour = next((c for c in COLOURS if re.search(rf"\b{c}\b", instruction.lower())), None)
        for n in list(w["nodes"]):
            if _skill_of(w, n) != "so101-placing-in-container":
                continue
            ref = w["nodes"][n]["ref"]
            sg = w["subgraphs"][ref]
            call_inputs = w["nodes"][n].get("inputs", {})
            if "color" in sg.get("inputs", {}) and "color" not in call_inputs and colour:
                del sg["inputs"]["color"]
                sg["nodes"] = _replace_ref(sg["nodes"], "in.color", colour)
                notes.append(f"R2: {ref!r} colour input was unbound; set to the task's colour {colour!r}")

    # R3: drop unreachable top-level nodes and their subgraphs
    live = _reachable(w)
    for n in [n for n in w["nodes"] if n not in live]:
        nd = w["nodes"].pop(n)
        w["conditional_edges"].pop(n, None)
        w["edges"] = [e for e in w["edges"] if n not in e]
        ref = nd.get("ref")
        if ref and not any(o.get("ref") == ref for o in w["nodes"].values()):
            w["subgraphs"].pop(ref, None)
        notes.append(f"R3: removed unreachable node {n!r}")

    # R4: subgraph nodes route on their exit
    for n, ce in w["conditional_edges"].items():
        if w["nodes"].get(n, {}).get("type") == "subgraph" and ce.get("router_field") != "exit":
            ce["router_field"] = "exit"
            notes.append(f"R4: {n!r} conditional edges now route on router_field 'exit'")

    # R5: one shared colour order across place steps; clean verify labels
    order, places = [], []
    node = _start_target(w)
    seen = set()
    while node and node not in seen:                      # walk the main (success) path
        seen.add(node)
        sk = _skill_of(w, node)
        if sk == "so101-placing-in-container":
            sg = w["subgraphs"][w["nodes"][node]["ref"]]
            put = next((nd for nd in sg["nodes"].values()
                        if str(nd.get("script", "")).endswith("so101_place.py")), None)
            if put and isinstance(put.get("inputs", {}).get("color"), str):
                order.append(put["inputs"]["color"])
                places.append(sg)
        ce = w["conditional_edges"].get(node, {}).get("mapping", {})
        node = next((ce[k] for k in ("found", "grasped", "verified") if k in ce), None)
    if len(places) > 1:
        want = ",".join(dict.fromkeys(order))
        for sg in places:
            for nd in sg["nodes"].values():
                ins = nd.get("inputs") or {}
                if str(nd.get("script", "")).endswith("so101_place.py") and ins.get("colors") != want:
                    ins["colors"] = want
                    notes.append(f"R5: place colour order set to {want!r}")
    for sg in w["subgraphs"].values():
        for nd in sg.get("nodes", {}).values():
            ins = nd.get("inputs") or {}
            is_verify = str(nd.get("script", "")).endswith("verify_in_container.py")
            if is_verify and isinstance(ins.get("color"), str):
                label = f"{ins['color']} cube"
                if ins.get("object_name") not in (None, label):
                    ins["object_name"] = label
                    notes.append(f"R5: verify label set to {label!r}")

    if notes:
        path.write_text(json.dumps(w, indent=2) + "\n")
    return notes
