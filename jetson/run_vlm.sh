#!/usr/bin/env bash
# Local VLM for the demo: NVIDIA Nemotron-3-Nano-Omni (30B-A3B, Q4_K_M + vision mmproj) on llama.cpp,
# OpenAI-compatible on :8080 (model alias my_model). ~26 GB of Orin memory once loaded.
#   jetson/run_vlm.sh          start (detached; first run downloads ~24 GB)
#   jetson/run_vlm.sh stop
set -euo pipefail
NAME=nemotron-omni
CACHE="${LLAMA_CACHE:-$HOME/workspace/llama-cache}"
if [ "${1:-}" = stop ]; then sudo docker rm -f "$NAME"; exit 0; fi
if curl -sf http://127.0.0.1:8080/health >/dev/null; then echo "VLM already up on :8080"; exit 0; fi
mkdir -p "$CACHE"
sudo docker rm -f "$NAME" 2>/dev/null || true
sudo docker run -d --name "$NAME" --pull missing --runtime=nvidia --network host \
  -v "$CACHE":/root/.cache/huggingface \
  ghcr.io/nvidia-ai-iot/llama_cpp:latest-jetson-orin \
  llama-server -hf ggml-org/NVIDIA-Nemotron-3-Nano-Omni-30B-A3B-GGUF:Q4_K_M \
  --ctx-size 32768 --port 8080 --host 0.0.0.0 --alias my_model --n-gpu-layers 999 \
  --jinja --chat-template-kwargs '{"enable_thinking":false}'
echo -n "waiting for the VLM"
until curl -sf http://127.0.0.1:8080/health >/dev/null; do echo -n .; sleep 10; done; echo " up"
