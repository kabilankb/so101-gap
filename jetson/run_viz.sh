#!/usr/bin/env bash
# GaP trace viewer for this package's runs (graph, per-node I/O, VLM prompts/answers, frames).
#   jetson/run_viz.sh            # serves http://127.0.0.1:9432 on the Jetson
# From a laptop:  ssh -N -L 9432:127.0.0.1:9432 atlas@<jetson>  then open http://localhost:9432
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p outputs
exec .venv/bin/gap viz --root outputs --port "${PORT:-9432}" --host 127.0.0.1 --no-browser \
  --services "$(dirname "$ROOT")/open-robot-skills"
