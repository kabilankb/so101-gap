"""Per-episode sorting progress, shared by the loop's script nodes.

Stored in a small JSON file keyed by the run's trace directory (unique per
trial), so the loop head, the pick and the verify nodes agree on which colours
are done and how many attempts each has had. Nothing here is privileged: a
colour is marked done only when the VLM confirms it is in the box.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile


def _path(ctx) -> str:
    trace = getattr(ctx, "_trace", None)
    out_dir = getattr(trace, "_output_dir", None) if trace is not None else None
    tag = hashlib.sha1(str(out_dir or os.getpid()).encode()).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), f".so101_sort_{tag}.json")


def load(ctx) -> dict:
    try:
        with open(_path(ctx)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"done": [], "attempts": {}, "current": None, "passes": 0, "log": []}


def save(ctx, state: dict) -> None:
    with open(_path(ctx), "w") as f:
        json.dump(state, f)
