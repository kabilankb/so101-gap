"""so101_gap.repair fixes the wiring slips a local LLM made on a real generation.

The fixture is Nemotron-3-Nano-Omni's unrepaired output for "pick the blue cube
and put it in the green box": the subgraphs are right, but the green-box subgraph
is missing and the top-level edges route on router_field=None.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from so101_gap.repair import repair

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "generated_pick_blue_llm.json"
ORS = ROOT.parent / "open-robot-skills"


@pytest.fixture
def wf_dir(tmp_path):
    d = tmp_path / "task_00"
    (d / "scripts").mkdir(parents=True)
    shutil.copy(FIXTURE, d / "workflow.json")
    for skill in ("so101-locating-cube", "so101-picking-cube", "so101-placing-in-container"):
        for f in (ROOT / "registry" / "skills" / skill / "scripts").glob("*.py"):
            shutil.copy2(f, d / "scripts" / f.name)
    return d


def test_repair_rules(wf_dir):
    notes = repair(wf_dir, "pick the blue cube and put it in the green box")
    assert any(n.startswith("R1: inserted") for n in notes)
    assert any(n.startswith("R4") for n in notes)
    w = json.loads((wf_dir / "workflow.json").read_text())
    skill_of = {n: w["subgraphs"][nd["ref"]]["skill"] for n, nd in w["nodes"].items()
                if nd.get("type") == "subgraph"}
    box = next(n for n, sk in skill_of.items() if sk == "so101-locating-container")
    assert ["START", box] in w["edges"]
    assert w["conditional_edges"][box]["mapping"]["found"] == "locate_blue_cube"
    assert all(ce["router_field"] == "exit" for ce in w["conditional_edges"].values())
    assert repair(wf_dir, "pick the blue cube and put it in the green box") == []   # idempotent


def test_repaired_graph_validates(wf_dir):
    pytest.importorskip("gap.runtime")
    if not ORS.is_dir():
        pytest.skip("open-robot-skills checkout not found")
    repair(wf_dir, "pick the blue cube and put it in the green box")
    gap_bin = Path(sys.executable).with_name("gap")
    res = subprocess.run([str(gap_bin), "run", str(wf_dir), "--validate-only",
                          "--skills", str(ROOT / "registry"), "--skills", str(ORS)],
                         capture_output=True, text=True)
    assert "OK: 0 errors" in res.stdout + res.stderr, (res.stdout + res.stderr)[-1500:]
