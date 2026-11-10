"""Static checks on the colour-sort workflow (no GaP runtime, no GPU)."""

import json
import py_compile
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRAPH = ROOT / "graph" / "color_sort"


def _wf() -> dict:
    return json.loads((GRAPH / "workflow.json").read_text())


def test_builder_matches_committed_workflow(tmp_path, monkeypatch):
    """graph/build_workflow.py is the source of truth for workflow.json."""
    committed = _wf()
    ns = runpy.run_path(str(ROOT / "graph" / "build_workflow.py"), run_name="not_main")
    assert ns["wf"] == committed


def test_topology():
    wf = _wf()
    assert wf["version"] == 3
    assert set(wf["subgraphs"]) == {"box_sg", "next_sg", "grasp_sg", "place_sg"}
    ce = wf["conditional_edges"]
    assert ce["next"]["mapping"]["finished"] == "done"
    # every failure path loops back to the loop head, never aborts mid-episode
    assert ce["grasp"]["mapping"]["failed"] == "next"
    assert set(ce["place"]["mapping"].values()) == {"next"}


def test_scripts_exist_and_compile():
    wf = _wf()
    for sg in wf["subgraphs"].values():
        for node in sg["nodes"].values():
            if "script" in node:
                path = GRAPH / node["script"]
                assert path.is_file(), path
                py_compile.compile(str(path), doraise=True)


def test_colour_order_bound_at_both_call_sites():
    nodes = _wf()["nodes"]
    assert nodes["next"]["inputs"]["colors"] == nodes["place"]["inputs"]["colors"]
    assert set(nodes["next"]["inputs"]["colors"].split(",")) == {"red", "green", "blue", "yellow"}


def test_pick_one_template_matches_builder():
    ns = runpy.run_path(str(ROOT / "graph" / "build_pick_one.py"), run_name="not_main")
    committed = json.loads((ROOT / "graph" / "pick_one" / "workflow.json").read_text())
    assert ns["build"]("red") == committed
    for name in ns["SCRIPTS"]:
        assert (ROOT / "graph" / "pick_one" / "scripts" / name).read_text() == \
               (GRAPH / "scripts" / name).read_text()
