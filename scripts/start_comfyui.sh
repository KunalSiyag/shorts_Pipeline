#!/usr/bin/env bash
# Start ComfyUI in low-VRAM mode (RTX 3050 4GB)
set -euo pipefail
COMFY_DIR="${COMFY_DIR:-$HOME/ComfyUI}"
cd "$COMFY_DIR"
source venv/bin/activate
echo "Starting ComfyUI at http://127.0.0.1:8188 (low VRAM mode)..."
echo "Tip: use http://127.0.0.1:8188 in the browser (not localhost) to avoid 403 errors."
exec python main.py --lowvram --preview-method auto --listen 127.0.0.1 --port 8188 --enable-cors-header "*"