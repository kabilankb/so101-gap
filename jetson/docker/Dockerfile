# Slim runtime for the GaP services. The Python environments are NOT baked in:
# jetson/install.sh builds them on the host (uv venvs + per-bundle venvs + model
# caches) and docker-compose.yml mounts them at the same paths. The image only
# supplies what those venvs need from the OS: GL/EGL/GLFW loaders for MuJoCo
# (offscreen EGL + the --gui viewer), X11 client libs, curl, git.
# CUDA comes from the pip wheels (torch/jax) + the Jetson driver libs that the
# nvidia container runtime mounts in.
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash ca-certificates curl git libgomp1 \
      libegl1 libgl1 libgles2 libglx0 libopengl0 libglfw3 \
      libx11-6 libxext6 libxrandr2 libxinerama1 libxcursor1 libxi6 libxxf86vm1 \
      libsm6 libice6 \
    && rm -rf /var/lib/apt/lists/*
# NVIDIA EGL vendor entry for glvnd (the runtime mounts the library itself)
RUN mkdir -p /usr/share/glvnd/egl_vendor.d && \
    printf '{"file_format_version":"1.0.0","ICD":{"library_path":"libEGL_nvidia.so.0"}}\n' \
      > /usr/share/glvnd/egl_vendor.d/10_nvidia.json
ENV MUJOCO_GL=egl
