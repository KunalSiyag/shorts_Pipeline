"""Image-to-video backends — smooth AI motion clips."""
from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path
from typing import Any

import requests


def _image_to_data_uri(image_path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(image_path))
    mime = mime or "image/png"
    data = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _ensure_fal_key() -> None:
    if not os.environ.get("FAL_KEY"):
        raise RuntimeError(
            "Smooth AI video requires a fal.ai API key.\n"
            "1. Sign up at https://fal.ai\n"
            "2. Create an API key\n"
            "3. Paste it in the Streamlit sidebar under 'fal API key'\n"
            "   or run: export FAL_KEY='your-key'\n"
            "Cost: ~$0.05–0.15 per scene clip (480p–720p)."
        )


def build_motion_prompt(scene: Any) -> str:
    """Combine motion + visual hints for fluid I2V generation."""
    parts = []
    if getattr(scene, "motion_prompt", None):
        parts.append(scene.motion_prompt)
    if getattr(scene, "image_prompt", None):
        parts.append(f"Visual context: {scene.image_prompt[:200]}")
    if getattr(scene, "narration", None):
        parts.append(f"Mood matches narration: {scene.narration[:120]}")
    base = ". ".join(parts) if parts else "smooth cinematic camera motion, natural movement, atmospheric"
    return (
        f"{base}. Fluid realistic motion, no sudden cuts, subtle environmental movement, "
        "professional vertical short video."
    )


def generate_fal_i2v(
    image_path: Path,
    prompt: str,
    output_path: Path,
    *,
    model: str = "fal-ai/wan/v2.2-5b/image-to-video",
    resolution: str = "480p",
    aspect_ratio: str = "9:16",
    num_frames: int = 81,
    fps: int = 16,
    use_interpolation: bool = True,
) -> Path:
    """Generate a smooth motion clip from a still image via fal.ai Wan I2V."""
    import fal_client

    _ensure_fal_key()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    image_url = _image_to_data_uri(image_path)
    args: dict[str, Any] = {
        "image_url": image_url,
        "prompt": prompt,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
        "num_frames": num_frames,
        "frames_per_second": fps,
        "enable_prompt_expansion": False,
        "acceleration": "regular",
        "video_quality": "high",
        "video_write_mode": "balanced",
    }
    if use_interpolation and "turbo" not in model and "5b" in model:
        args["interpolator_model"] = "film"
        args["num_interpolated_frames"] = 1
        args["adjust_fps_for_interpolation"] = True

    result = fal_client.subscribe(model, arguments=args)

    video_info: dict[str, Any] = result.get("video") or {}
    video_url = video_info.get("url")
    if not video_url:
        raise RuntimeError(f"fal I2V returned no video URL. Response: {result}")

    resp = requests.get(video_url, timeout=300)
    resp.raise_for_status()
    output_path.write_bytes(resp.content)
    return output_path


def generate_i2v(
    image_path: Path,
    prompt: str,
    output_path: Path,
    cfg: dict[str, Any] | None = None,
) -> Path:
    """Generate smooth video clip using configured I2V provider (default: fal)."""
    cfg = cfg or {}
    provider = cfg.get("provider", "fal")
    if provider == "fal":
        return generate_fal_i2v(
            image_path=image_path,
            prompt=prompt,
            output_path=output_path,
            model=cfg.get("model", "fal-ai/wan/v2.2-5b/image-to-video"),
            resolution=cfg.get("resolution", "480p"),
            aspect_ratio=cfg.get("aspect_ratio", "9:16"),
            num_frames=int(cfg.get("num_frames", 81)),
            fps=int(cfg.get("fps", 16)),
            use_interpolation=cfg.get("use_interpolation", True),
        )
    raise RuntimeError(f"Unknown I2V provider: {provider}. Use provider: fal in config.")