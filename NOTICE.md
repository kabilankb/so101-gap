# Notice

so101-gap is licensed under the Apache License 2.0 (see `LICENSE`). It builds on
the following third-party work, which is **not vendored** unless noted. The
installer fetches it at pinned revisions.

| Component | Use | License |
|---|---|---|
| [graph-as-policy](https://github.com/graph-robots/graph-as-policy) (`53e8049`) | Graph runtime, connector and `RobotIO` interfaces, skill registry | Apache-2.0 |
| `graph/color_sort/scripts/perceive_dino_vlm.py` | **Vendored** copy of open-robot-skills' canonical `perceiving-objects` script | Apache-2.0 |
| [lerobot/so101-tabletop-mujoco](https://huggingface.co/lerobot/so101-tabletop-mujoco) (`43a427cc`) | MuJoCo scene, EnvHub env, MuJoCo Menagerie SO-101 model | Apache-2.0 |
| [MuJoCo](https://github.com/google-deepmind/mujoco) | Physics + rendering | Apache-2.0 |
| [NVIDIA Nemotron-3-Nano-Omni](https://huggingface.co/ggml-org/NVIDIA-Nemotron-3-Nano-Omni-30B-A3B-GGUF) via [llama.cpp](https://github.com/ggml-org/llama.cpp) | Local VLM | NVIDIA Open Model License (model); MIT (llama.cpp) |
| [SAM3](https://huggingface.co/facebook/sam3), [Grounding DINO](https://huggingface.co/IDEA-Research/grounding-dino-base) | Segmentation / detection weights (downloaded) | See the model cards (SAM3 is gated) |
