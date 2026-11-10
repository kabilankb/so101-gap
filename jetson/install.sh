#!/usr/bin/env bash
# Install the SO-101 Graph-as-Policy demo on a Jetson (tested: AGX Orin 64 GB, L4T R39, CUDA 13).
#
#   ./jetson/install.sh            # from the so101-gap checkout
#
# Lays out, next to this package:
#   graph-as-policy/        GaP engine (pinned commit, no submodules: the LIBERO/robosuite/cuRobo
#                           sim stack is not used by this demo)
#   open-robot-skills/      skill + tool bundles (pinned commit)
#   so101-tabletop-mujoco/  the LeRobot EnvHub scene (pinned HF revision)
# and creates .venv (Python 3.11) plus per-bundle venvs for grounding-dino, sam3, vlm, geometry.
# Needs a Hugging Face token with access to facebook/sam3 (~/.cache/huggingface/token or HF_TOKEN).
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh

GAP_REV=53e8049      # graph-robots/graph-as-policy
SKILLS_REV=752dfbd   # graph-robots/open-robot-skills
SCENE_REV=43a427cc783cd2c09445cf341bea6bb5bd9c22d1  # lerobot/so101-tabletop-mujoco

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PARENT="$(dirname "$ROOT")"
cd "$PARENT"

clone() {  # clone <url> <dir> <rev>
  if [ ! -d "$2/.git" ]; then git clone --filter=blob:none "$1" "$2"; fi
  git -C "$2" fetch -q origin && git -C "$2" checkout -q "$3"
}
clone https://github.com/graph-robots/graph-as-policy.git graph-as-policy "$GAP_REV"
clone https://github.com/graph-robots/open-robot-skills.git open-robot-skills "$SKILLS_REV"
uvx --from huggingface_hub hf download lerobot/so101-tabletop-mujoco \
  --revision "$SCENE_REV" --local-dir so101-tabletop-mujoco >/dev/null

cd "$ROOT"
[ -d .venv ] || uv venv -p 3.11 .venv
uv pip install -p .venv -q -e ../graph-as-policy/gap-core
uv pip install -p .venv -q --no-deps -e ../graph-as-policy -e ../open-robot-skills
uv pip install -p .venv -q -e .

# aarch64 patch: the geometry bundle locks open3d 0.19, which ships no aarch64 wheel.
# 0.18.0 is the last release with one (and needs NumPy 1.x). Pin it on aarch64 only.
GEO=../open-robot-skills/tools/geometry
if [ "$(uname -m)" = aarch64 ] && ! grep -q "open3d==0.18.0" "$GEO/pyproject.toml"; then
  python3 - "$GEO/pyproject.toml" <<'EOF'
import sys
p = sys.argv[1]; s = open(p).read()
s = s.replace('  "open3d>=0.18",\n',
    '  "open3d>=0.18; platform_machine != \'aarch64\'",\n'
    '  "open3d==0.18.0; platform_machine == \'aarch64\'",  # last release with aarch64 wheels\n'
    '  "numpy<2; platform_machine == \'aarch64\'",  # open3d 0.18 is built against NumPy 1.x\n')
open(p, "w").write(s)
EOF
  (cd "$GEO" && uv lock)
fi

# Per-bundle venvs (torch from PyPI: aarch64 CUDA wheels run on Orin with L4T R39)
export GAP_SKILLS_PATH="$PARENT/open-robot-skills"
.venv/bin/gap skills install --workflow graph/color_sort
.venv/bin/gap skills check --download   # prefetch Grounding DINO + SAM3 weights
.venv/bin/gap run graph/color_sort --validate-only

echo "installed. docker compose up -d vlm viz && docker compose run --rm so101   (or jetson/run_vlm.sh + jetson/run_demo.sh)"
