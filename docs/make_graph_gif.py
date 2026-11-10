"""Make an animated "graph executing" GIF from one so101-gap run.

    python docs/make_graph_gif.py outputs/so101_sort_<time>_seed<N> docs/media/graph_run.gif

Left: the episode's front-camera video. Right: the GaP workflow (rendered by
``gap.viz.render``) with the node that is currently executing highlighted.
Bottom: a caption built from the node's recorded outputs in the GaP trace
(chosen colour, grasp point, gripper reading, placement slot, VLM result).

Needs the graph-as-policy runtime (``gap.viz``), Pillow and imageio. The
video is mapped onto the motion nodes (home / pick / put) in proportion to
their durations in the trace; perception and routing nodes hold the frame.
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import imageio.v2 as iio
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HL = "#ff6a00"
MOTION = {"box_sg.home", "grasp_sg.pick", "place_sg.put"}
TOP_OF = {"box_sg": "box", "next_sg": "next", "grasp_sg": "grasp", "place_sg": "place"}


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


class GraphRenderer:
    """Renders the workflow once per highlighted node (cached)."""

    def __init__(self, workflow: dict, height: int):
        import gap.viz.render as R
        from matplotlib.patches import FancyBboxPatch

        self.R, self.wf, self.height, self.cache = R, workflow, height, {}
        orig = R._draw_node

        def draw_node(ax, cx, cy, name, node):
            orig(ax, cx, cy, name, node)
            if node.get("_hl"):
                w, h = R.NODE_W + 0.12, R.NODE_H + 0.12
                ax.add_patch(FancyBboxPatch((cx - w / 2, cy - h / 2), w, h,
                                            boxstyle="round,pad=0.02,rounding_size=0.14",
                                            linewidth=4.0, edgecolor=HL, facecolor="none", zorder=7))

        R._draw_node = draw_node

    def __call__(self, key: str) -> Image.Image:
        if key not in self.cache:
            wf = copy.deepcopy(self.wf)
            sg, _, node = key.partition(".")
            nodes = wf["subgraphs"][sg]["nodes"] if node else wf["nodes"]
            nodes[node or sg]["_hl"] = True
            with tempfile.TemporaryDirectory() as d:
                out = Path(d) / "g.png"
                self.R.render(wf, out, legend=False, also_png=False)
                im = Image.open(out).convert("RGB")
            w = round(im.width * self.height / im.height)
            self.cache[key] = im.resize((w, self.height), Image.LANCZOS)
        return self.cache[key]


def _iter_output(trace: Path, node: str, i: int) -> dict:
    p = trace / "node_data" / node / "iters" / f"{i:03d}" / "output.json"
    if not p.is_file() and i == 0:
        p = trace / "node_data" / node / "output.json"
    return json.loads(p.read_text()) if p.is_file() else {}


def build_steps(trace: Path) -> list[dict]:
    """Ordered executed nodes, with routers (not traced) inserted by structure."""
    events = json.loads((trace / "dag_trace.json").read_text())["events"]
    start, steps, visits = {}, [], {}
    for e in events:
        n = e["node_name"]
        if e["event_type"] == "node_started":
            start[n] = e["timestamp"]
        elif e["event_type"] == "node_finished" and n in start:
            i = visits.get(n, 0)
            visits[n] = i + 1
            steps.append({"key": n, "dur": e["timestamp"] - start.pop(n), "iter": i})
    out, colour = [], ""
    for k, s in enumerate(steps):
        key, i = s["key"], s["iter"]
        o = _iter_output(trace, key, i)
        if key == "box_sg.perceive":
            s["caption"] = "box · DINO proposals → VLM tournament → SAM3 → 'green box'"
        elif key.endswith(".obb"):
            s["caption"] = f"{TOP_OF[key.split('.')[0]]} · depth → 3D oriented bounding box"
        elif key == "next_sg.choose":
            colour = o.get("color", "")
            s["caption"] = ("next · all colours verified → finished" if o.get("finished")
                            else f"next · next colour in order: {colour.upper()}")
        elif key == "next_sg.perceive":
            s["caption"] = f"next · perceive '{colour} cube' (DINO → VLM tournament → SAM3)"
        elif key == "grasp_sg.pick":
            x, y, z = o.get("grasp_xyz", (0, 0, 0))
            s["caption"] = (f"grasp · top-down pick at ({x:.2f}, {y:.2f}) m"
                            f" — gripper {o.get('closed_fraction', 0):.2f} = holding")
        elif key == "place_sg.put":
            s["caption"] = f"place · {colour} cube → its quadrant of the box"
        elif key == "box_sg.home":
            s["caption"] = "box · arm home (clear view)"
        else:
            s["caption"] = key.replace("_sg.", " · ")
        out.append(s)
        nxt = steps[k + 1]["key"] if k + 1 < len(steps) else None
        if key == "next_sg.choose":
            finished = bool(o.get("finished"))
            out.append({"key": "next_sg.route", "dur": 0, "caption":
                        f"next · route → {'finished' if finished else 'pick'}"})
            if finished:
                out.append({"key": "done", "dur": 0, "caption": "done ✓ — every colour verified in the box"})
        if key == "place_sg.put":
            ok = nxt == "next_sg.choose"
            out.append({"key": "place_sg.verify", "dur": 0,
                        "caption": f"place · VLM: is the {colour} cube in the box? → {'YES' if ok else '…'}"})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--height", type=int, default=380)
    ap.add_argument("--fps", type=int, default=8)
    args = ap.parse_args()

    trace = args.run_dir / "trace"
    wf = json.loads((args.run_dir / "graph" / "workflow.json").read_text())
    video = [np.asarray(f) for f in iio.mimread(args.run_dir / "run_video.mp4", memtest=False)]
    steps = build_steps(trace)

    # map video frames onto motion nodes, proportional to their durations
    mdur = sum(s["dur"] for s in steps if s["key"] in MOTION) or 1.0
    cursor, n = 0, len(video)
    for s in steps:
        if s["key"] in MOTION:
            k = max(1, round(n * s["dur"] / mdur))
            s["frames"] = list(range(cursor, min(n, cursor + k)))
            cursor = min(n - 1, cursor + k)
        else:
            s["frames"] = [min(cursor, n - 1)]

    graph = GraphRenderer(wf, args.height)
    font, cap_h = _font(17), 38
    frames = []
    for s in steps:
        g = graph(s["key"])
        idx = s["frames"]
        # motion: ~1 GIF frame per 6 video frames; others: hold ~0.6 s
        picks = idx[::6] if len(idx) > 1 else idx * max(1, round(args.fps * 0.6))
        for fi in picks:
            v = Image.fromarray(video[fi]).convert("RGB")
            v = v.resize((round(v.width * args.height / v.height), args.height), Image.LANCZOS)
            canvas = Image.new("RGB", (v.width + g.width + 8, args.height + cap_h), "white")
            canvas.paste(v, (0, 0))
            canvas.paste(g, (v.width + 8, 0))
            d = ImageDraw.Draw(canvas)
            d.rectangle([0, args.height, canvas.width, args.height + cap_h], fill="#1f2328")
            d.text((12, args.height + 9), s["caption"], fill="white", font=font)
            frames.append(canvas)
    frames += [frames[-1]] * (args.fps * 2)  # hold the ending
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("ffmpeg"):
        # palettegen/paletteuse: far better colours than PIL quantize, and
        # rectangle diffs keep the (mostly static) graph half cheap
        with tempfile.TemporaryDirectory() as d:
            for i, f in enumerate(frames):
                f.save(f"{d}/{i:05d}.png")
            subprocess.run(
                ["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(args.fps), "-i", f"{d}/%05d.png",
                 "-vf", "split[a][b];[a]palettegen=max_colors=200:stats_mode=full[p];"
                        "[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
                 str(args.out)], check=True)
    else:
        pal = [f.quantize(colors=200, method=Image.MEDIANCUT) for f in frames]
        pal[0].save(args.out, save_all=True, append_images=pal[1:], duration=int(1000 / args.fps), loop=0)
    print(f"wrote {args.out}: {len(frames)} frames, {args.out.stat().st_size / 1e6:.1f} MB")

if __name__ == "__main__":
    main()
