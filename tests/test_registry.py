"""The SO-101 skill registry is internally consistent and its builder snippets are valid.

The LLM codegen copies each SKILL.md's "Builder code" block verbatim, so those
snippets must assemble into workflows that GaP's own validator accepts — both a
single-cube graph and the so101-next-cube loop. Needs the full graph-as-policy
runtime (gap.builder + gap.runtime) and an open-robot-skills checkout next to
this package; skipped otherwise.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
REG = ROOT / "registry" / "skills"
ORS = ROOT.parent / "open-robot-skills"
SKILLS = sorted(p.name for p in REG.iterdir() if (p / "SKILL.md").is_file())


def _frontmatter(name: str) -> dict:
    text = (REG / name / "SKILL.md").read_text()
    return yaml.safe_load(text.split("\n---\n", 1)[0].removeprefix("---\n"))


def _builder_code(name: str) -> str:
    body = (REG / name / "SKILL.md").read_text().split("\n---\n", 1)[1]
    m = re.search(r"## Builder code \(copy exactly\).*?```python\n(.*?)```", body, re.S)
    assert m, f"{name}: no builder code block"
    return m.group(1)


@pytest.mark.parametrize("name", SKILLS)
def test_skill_contract(name):
    fm = _frontmatter(name)
    assert fm["name"] == name and "Use when" in fm["description"]
    gapx = fm["gap"]
    for entry in gapx.get("canonical_scripts", []):
        (path,) = entry.values()
        assert (REG / name / path).is_file(), path
    for ex in gapx.get("examples", []):
        path = REG / name / ex["path"]
        if path.suffix == ".json":
            json.loads(path.read_text())
        else:  # coordinator WorkflowSpec examples are Python: they must build
            pytest.importorskip("gap.builder")
            ns: dict = {}
            exec(path.read_text(), ns)  # noqa: S102 - our own example
            assert ns["spec"].to_dict()["subgraphs"]
    for exit_name in gapx["exit_conditions"]:
        assert re.fullmatch(r"[a-z_]+", exit_name)


def _assemble(tmp: Path, loop: bool) -> Path:
    pytest.importorskip("gap.builder")
    from gap.builder import END, START, Ref, Subgraph, Workflow

    ns = {"Subgraph": Subgraph, "Ref": Ref, "START": START, "END": END}
    sgs = {}
    middle = "so101-next-cube" if loop else "so101-locating-cube"
    order = ["so101-locating-container", middle, "so101-picking-cube", "so101-placing-in-container"]
    for name in order:
        code = _builder_code(name)
        if loop and name == "so101-placing-in-container":
            code = code.replace('sg.add_input("container_obb", type_name="OrientedBoundingBox")',
                                'sg.add_input("container_obb", type_name="OrientedBoundingBox")\n'
                                'sg.add_input("color", type_name="str")')
            code = code.replace('"color": "red", "colors": "red"',
                                '"color": Ref("in.color"), "colors": "red,green,blue,yellow"')
            code = code.replace('inputs={"color": "red"}', 'inputs={"color": Ref("in.color")}')
        local = dict(ns)
        exec(code, local)  # noqa: S102 - our own SKILL.md snippets
        sgs[name] = local["sg"]

    wf = Workflow(name="registry_check")
    for sg in sgs.values():
        wf.add_subgraph(sg)
    names = {"so101-locating-container": "box", "so101-locating-cube": "target", "so101-next-cube": "next",
             "so101-picking-cube": "grasp", "so101-placing-in-container": "place"}
    for name, sg in sgs.items():
        wf.add_node(names[name], type="subgraph", ref=sg.name)
    wf.add_node("done", type="end", status="success")
    wf.add_node("abort", type="end", status="failure")
    wf.add_edge(START, "box")
    if loop:
        routes = {"box": {"found": "next", "not_found": "abort"},
                  "next": {"found": "grasp", "finished": "done", "not_found": "next"},
                  "grasp": {"grasped": "place", "failed": "next"},
                  "place": {"verified": "next", "missed": "next", "blocked": "next"}}
    else:
        routes = {"box": {"found": "target", "not_found": "abort"},
                  "target": {"found": "grasp", "not_found": "abort"},
                  "grasp": {"grasped": "place", "failed": "abort"},
                  "place": {"verified": "done", "missed": "abort", "blocked": "abort"}}
    for src, mapping in routes.items():
        wf.add_conditional_edges(src, mapping, router_field="exit")

    out = tmp / ("loop" if loop else "single")
    (out / "scripts").mkdir(parents=True)
    for d in REG.iterdir():  # materialize canonical scripts the graph references
        for f in (d / "scripts").glob("*.py"):
            shutil.copy2(f, out / "scripts" / f.name)
    wf.save(out / "workflow.json")
    return out


@pytest.mark.parametrize("loop", [False, True])
def test_builder_snippets_validate(tmp_path, loop):
    if not ORS.is_dir():
        pytest.skip("open-robot-skills checkout not found")
    out = _assemble(tmp_path, loop)
    gap_bin = Path(sys.executable).with_name("gap")
    res = subprocess.run([str(gap_bin), "run", str(out), "--validate-only",
                          "--skills", str(ROOT / "registry"), "--skills", str(ORS)],
                         capture_output=True, text=True)
    report = res.stdout + res.stderr
    assert "OK: 0 errors" in report, report[-2000:]
