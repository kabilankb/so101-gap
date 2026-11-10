#!/usr/bin/env bash
# Run the colour-sorting graph on the Jetson (sim + GaP + perception + VLM all local).
#   jetson/run_demo.sh --seed 0
#   jetson/run_demo.sh --seed 3 --order yellow,blue,green,red
#   jetson/run_demo.sh --seeds 0,1,2      # several episodes in a row
#   jetson/run_demo.sh --seed 0 --gui     # live MuJoCo viewer on the Jetson desktop
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export GAP_SKILLS_PATH="${GAP_SKILLS_PATH:-$(dirname "$ROOT")/open-robot-skills}"
export MUJOCO_GL=egl PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
# --gui: borrow the logged-in desktop session's display (also works from SSH)
if [ -z "${DISPLAY:-}" ]; then
  shell=$(pgrep -u "$(id -u)" -x gnome-shell | head -1 || true)
  if [ -n "$shell" ]; then
    eval "$(tr '\0' '\n' < /proc/$shell/environ | grep -E '^(DISPLAY|XAUTHORITY)=' | sed 's/^/export /')"
  fi
fi
# wait for the VLM (jetson/run_vlm.sh or the compose `vlm` service); first load takes ~1-2 min
for i in $(seq 1 180); do curl -sf http://127.0.0.1:8080/health >/dev/null && break
  [ "$i" = 1 ] && echo "waiting for the VLM on :8080 ..."; sleep 10; done
curl -sf http://127.0.0.1:8080/health >/dev/null || { echo "VLM not running: jetson/run_vlm.sh"; exit 1; }
cd "$ROOT"
if [ "${1:-}" = --seeds ]; then
  seeds="$2"; shift 2
  rc=0
  for s in ${seeds//,/ }; do .venv/bin/so101-gap-run --seed "$s" "$@" || rc=1; done
  exit $rc
fi
exec .venv/bin/so101-gap-run "$@"
