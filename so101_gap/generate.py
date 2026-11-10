"""so101-gap-generate: write an SO-101 graph from a sentence with a local LLM.

    so101-gap-generate "pick the blue cube and put it in the green box"
    so101-gap-generate "sort the cubes into the box in the order yellow, red, green, blue"

Runs Graph-as-Policy's multi-agent codegen (coordinator → per-subgraph agents →
validate/fix) against an OpenAI-compatible server, by default Nemotron-3-Nano-Omni
on llama.cpp at http://127.0.0.1:8080/v1 (the compose ``vlm`` service). The LLM
only sees this package's SO-101 skill registry (``registry/skills``) plus the
vision tool bundles from open-robot-skills, never the Franka/LIBERO skills.

Three adjustments make a 30B-A3B local model work with GaP's codegen:
  * thinking mode is switched ON per request (``chat_template_kwargs``); the
    server keeps it off for the fast in-graph VLM calls
  * the skill catalog is restricted (``only=``) so every choice is an SO-101 skill
  * the checkpoint agent is off: checkpoints need simulator ground truth that this
    connector deliberately doesn't expose

The result is a normal workflow folder: validate it, then run it with
``so101-gap-run --graph <dir>`` or ``GRAPH=<dir> docker compose run --rm so101``.
"""

from __future__ import annotations

import argparse
import functools
import os
import re
import shutil
import sys
import time
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = PKG_ROOT / "registry"
SO101_SKILLS = ["so101-locating-container", "so101-locating-cube", "so101-next-cube",
                "so101-picking-cube", "so101-placing-in-container"]
TOOL_BUNDLES = ["vlm", "sam3", "grounding-dino", "geometry"]


def _restrict_catalog(only: list[str]) -> None:
    import gap.skills as gs

    orig = gs.load_registry_set
    if getattr(orig, "_so101_only", False):
        return

    @functools.wraps(orig)
    def load(registry_set, **kw):
        kw["only"] = only
        return orig(registry_set, **kw)

    load._so101_only = True
    gs.load_registry_set = load


def _enable_thinking(budget_tokens: int | None) -> None:
    import gap.agent.llm as L

    orig = L._openai_request_body
    if getattr(orig, "_so101_thinking", False):
        return

    def body(config, system, messages, tools=None):
        b = orig(config, system, messages, tools=tools)
        b["chat_template_kwargs"] = {"enable_thinking": True}
        if budget_tokens:
            b["max_tokens"] = budget_tokens
        return b

    body._so101_thinking = True
    L._openai_request_body = body


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("instruction",
                    help='task in plain English, e.g. "pick the red cube and put it in the box"')
    ap.add_argument("--out", type=Path, default=None,
                    help="output dir (default: graph/generated/<slug>); the workflow lands in <out>/task_00")
    ap.add_argument("--llm-url", default=os.environ.get("SO101_LLM_URL", "http://127.0.0.1:8080/v1"))
    ap.add_argument("--model", default=os.environ.get("SO101_LLM_MODEL", "my_model"))
    ap.add_argument("--skills", default=os.environ.get("GAP_SKILLS_PATH",
                                                       str(PKG_ROOT.parent / "open-robot-skills")),
                    help="open-robot-skills checkout (for the vision tool bundles)")
    ap.add_argument("--no-thinking", action="store_true", help="leave the model's thinking mode off")
    ap.add_argument("--max-tokens", type=int, default=16384)
    args = ap.parse_args(argv)

    slug = re.sub(r"[^a-z0-9]+", "_", args.instruction.lower()).strip("_")[:48] or "task"
    out = args.out or PKG_ROOT / "graph" / "generated" / slug
    if out.exists():
        shutil.rmtree(out)

    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _restrict_catalog(SO101_SKILLS + TOOL_BUNDLES)
    if not args.no_thinking:
        _enable_thinking(args.max_tokens)

    import gap.agent
    from gap.agent.config import PipelineConfig

    cfg = PipelineConfig()
    cfg.llm.provider = "openrouter"            # = any OpenAI-compatible endpoint
    cfg.llm.endpoint = args.llm_url
    cfg.llm.model = args.model
    cfg.llm.api_key = "local"
    cfg.llm.max_tokens = args.max_tokens
    cfg.composition.checkpoint_agent = False
    cfg.skills = [REGISTRY, Path(args.skills)]

    print(f"[so101-gap-generate] {args.instruction!r}\n  llm={args.llm_url} ({args.model}) -> {out}",
          flush=True)
    t0 = time.time()
    error = None
    try:
        gap.agent.generate_sync(args.instruction, out_dir=out, config=cfg)
    except Exception as exc:  # noqa: BLE001 - a near-valid graph may still be on disk
        error = exc
    wf_dir = out / "task_00"
    if not (wf_dir / "workflow.json").is_file():
        print(f"[so101-gap-generate] FAILED after {time.time() - t0:.0f}s: {error}", file=sys.stderr)
        return 1

    from .repair import repair

    notes = repair(wf_dir, args.instruction)
    for n in notes:
        print(f"  repair {n}")
    ok, report = _validate(wf_dir, args.skills)
    status = "OK" if ok else "INVALID"
    print(f"[so101-gap-generate] {status} in {time.time() - t0:.0f}s"
          f"{' (codegen error: ' + str(error)[:160] + ')' if error and not ok else ''}: {wf_dir}")
    if not ok:
        print(report[-1500:], file=sys.stderr)
        return 1
    import json as _json

    from gap.viz.text import to_text

    print(to_text(_json.loads((wf_dir / "workflow.json").read_text())))
    rel = os.path.relpath(wf_dir, PKG_ROOT)
    print(f"  run:  GRAPH={rel} docker compose run --rm so101\n"
          f"   or:  .venv/bin/so101-gap-run --graph {rel} --gui")
    return 0


def _validate(wf_dir: Path, skills: str) -> tuple[bool, str]:
    """GaP's own validator, against the SO-101 registry + the tool bundles."""
    import subprocess

    gap_bin = Path(sys.executable).with_name("gap")
    res = subprocess.run([str(gap_bin), "run", str(wf_dir), "--validate-only",
                          "--skills", str(REGISTRY), "--skills", skills],
                         capture_output=True, text=True)
    report = res.stdout + res.stderr
    return "OK: 0 errors" in report, report

if __name__ == "__main__":
    sys.exit(main())
