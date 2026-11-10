"""so101-gap-run: run the colour-sorting graph on the SO-101 MuJoCo tabletop.

    so101-gap-run --seed 0 --order red,green,blue,yellow

Everything is local: the MuJoCo sim, GaP, Grounding DINO + SAM3 (skill
bundles) and the VLM (an OpenAI-compatible server, by default llama.cpp
serving Nemotron-3-Nano-Omni on :8080 of the same machine).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
GRAPH = PKG_ROOT / "graph" / "color_sort"
COLORS = ("red", "green", "blue", "yellow")


def _graph_with_order(order: str, dst: Path) -> Path:
    shutil.copytree(GRAPH, dst)
    wf_path = dst / "workflow.json"
    wf = json.loads(wf_path.read_text())
    for node in ("next", "place"):
        wf["nodes"][node]["inputs"]["colors"] = order
    wf_path.write_text(json.dumps(wf, indent=2) + "\n")
    return dst


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=0, help="scene randomization seed")
    ap.add_argument("--order", default="red,green,blue,yellow",
                    help="colour order (comma-separated subset/permutation of red,green,blue,yellow)")
    ap.add_argument("--out", default=str(PKG_ROOT / "outputs"), help="output root")
    ap.add_argument("--skills",
                    default=os.environ.get("GAP_SKILLS_PATH", str(PKG_ROOT.parent / "open-robot-skills")),
                    help="open-robot-skills checkout")
    ap.add_argument("--vlm-url", default=os.environ.get("GAP_VLM_BASE_URL", "http://127.0.0.1:8080/v1"))
    ap.add_argument("--vlm-model", default=os.environ.get("GAP_VLM_MODEL", "my_model"))
    ap.add_argument("--gui", action="store_true",
                    help="open the live MuJoCo viewer window (needs a desktop session / $DISPLAY)")
    args = ap.parse_args(argv)

    order = ",".join(c.strip() for c in args.order.split(",") if c.strip())
    bad = [c for c in order.split(",") if c not in COLORS]
    if bad or not order:
        ap.error(f"unknown colours {bad}; choose from {COLORS}")

    os.environ.setdefault("MUJOCO_GL", "egl")
    os.environ.update({
        "GAP_VLM_PROVIDER": "openrouter",  # = any OpenAI-compatible endpoint
        "GAP_VLM_BASE_URL": args.vlm_url,
        "GAP_VLM_MODEL": args.vlm_model,
        "GAP_VLM_API_KEY": os.environ.get("GAP_VLM_API_KEY", "local"),
    })
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "so101_gap.ik", "OpenGL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    import gap
    import imageio.v2 as iio

    from .connector import make_connector

    run_dir = Path(args.out) / time.strftime(f"so101_sort_%Y%m%d_%H%M%S_seed{args.seed}")
    run_dir.mkdir(parents=True)
    graph = _graph_with_order(order, run_dir / "graph")
    print(f"[so101-gap] seed={args.seed} order={order} vlm={args.vlm_url} -> {run_dir}", flush=True)

    conn = make_connector(seed=args.seed, gui=args.gui)
    t0 = time.time()
    try:
        result = gap.execute(graph, conn, skills=args.skills, trace_dir=run_dir / "trace",
                             checkpoints="off")
    finally:
        cubes = conn.io.cube_states()
        frames = conn.io.frames
        conn.close()
    wall = time.time() - t0

    iio.mimsave(run_dir / "run_video.mp4", frames, fps=15, macro_block_size=1)
    wanted = order.split(",")
    sorted_ok = [c for c in wanted if cubes[c]["in_box"]]
    report = {
        "seed": args.seed, "order": wanted, "graph_exit": result.exit_status,
        "graph_success": result.success, "error": None if result.error is None else str(result.error),
        "cubes_in_box": sorted_ok, "all_sorted": len(sorted_ok) == len(wanted),
        "cubes": cubes, "wall_s": round(wall, 1), "sim_s": round(len(frames) * 2 / 30, 1),
        "video": str(run_dir / "run_video.mp4"), "trace": str(run_dir / "trace"),
    }
    (run_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("graph_exit", "cubes_in_box", "all_sorted", "wall_s")}))
    print(f"[so101-gap] {'SUCCESS' if report['all_sorted'] else 'INCOMPLETE'}: "
          f"{len(sorted_ok)}/{len(wanted)} cubes in the box; video {report['video']}")
    return 0 if report["all_sorted"] else 1


if __name__ == "__main__":
    sys.exit(main())
