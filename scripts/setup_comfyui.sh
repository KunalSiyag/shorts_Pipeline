#!/usr/bin/env bash
# ComfyUI setup for RTX 3050 4GB VRAM — Flux Schnell GGUF
set -euo pipefail

COMFY_DIR="${COMFY_DIR:-$HOME/ComfyUI}"
PYTHON="${PYTHON:-python3}"

echo "=== ComfyUI setup → $COMFY_DIR ==="

if [ ! -d "$COMFY_DIR/.git" ]; then
  git clone https://github.com/comfyanonymous/ComfyUI "$COMFY_DIR"
fi

cd "$COMFY_DIR"
if [ ! -d venv ]; then
  $PYTHON -m venv venv
fi
source venv/bin/activate
pip install -U pip wheel
pip install -r requirements.txt
pip install huggingface_hub

# GGUF support (required for 4GB VRAM Flux)
mkdir -p custom_nodes
if [ ! -d custom_nodes/ComfyUI-GGUF ]; then
  git clone https://github.com/city96/ComfyUI-GGUF custom_nodes/ComfyUI-GGUF
fi
pip install gguf

mkdir -p models/unet models/clip models/vae

download() {
  local url="$1" dest="$2"
  if [ -f "$dest" ]; then
    echo "  skip (exists): $dest"
    return
  fi
  echo "  downloading: $dest"
  hf download "${@:3}" --local-dir "$(dirname "$dest")" 2>/dev/null || \
    wget -q --show-progress -O "$dest" "$url" || \
    curl -L -o "$dest" "$url"
}

echo "=== Downloading Flux Schnell GGUF Q4 (~5GB) ==="
if [ ! -f models/unet/flux1-schnell-Q4_0.gguf ]; then
  hf download city96/FLUX.1-schnell-gguf flux1-schnell-Q4_0.gguf --local-dir models/unet || true
fi

echo "=== Downloading CLIP + VAE (~1.5GB) ==="
hf download comfyanonymous/flux_text_encoders clip_l.safetensors --local-dir models/clip || true
hf download comfyanonymous/flux_text_encoders t5xxl_fp8_e4m3fn.safetensors --local-dir models/clip || true
hf download camenduru/FLUX.1-dev-ungated ae.safetensors --local-dir models/vae || true

cat <<'EOF'

=== Setup complete ===

Start ComfyUI (low VRAM mode):
  cd ~/ComfyUI && source venv/bin/activate
  python main.py --lowvram --preview-method auto

Then in shorts_Pipeline config.yaml set:
  image_generation:
    backend: comfyui

If you get OOM errors, switch checkpoint to flux1-schnell-Q3_K_S.gguf (smaller).
EOF