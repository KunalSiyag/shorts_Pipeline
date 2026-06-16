"""
Image Generation Agent

Pluggable backends for cheapest possible image creation while supporting
consistency (reference images, style prompts).

Current implementations:
- mock: Fast, zero-cost, produces usable vertical placeholder images with overlaid text.
  Perfect for end-to-end pipeline testing and prompt iteration.

Future / swappable:
- comfyui (local ComfyUI HTTP API)
- api_generic (fal, Runware, Together, Replicate, custom endpoint)
- imagine (prototype using this Grok session's image tools — manual for now)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from PIL import Image, ImageDraw, ImageFont


class ImageAgent:
    def __init__(self, config_path: str | Path = "config.yaml"):
        self.config_path = Path(config_path)
        self.cfg = self._load_config()
        self.backend = self.cfg.get("image_generation", {}).get("backend", "mock")
        self.aspect = self.cfg.get("image_generation", {}).get("aspect_ratio", "9:16")
        # For 9:16 vertical shorts
        self.width = self.cfg.get("image_generation", {}).get("width", 1080)
        self.height = self.cfg.get("image_generation", {}).get("height", 1920)
        self.paths = self.cfg.get("paths", {})

    def _load_config(self) -> dict:
        p = self.config_path
        if not p.exists():
            p = p.parent / "config.example.yaml"
        if p.exists():
            with open(p) as f:
                return yaml.safe_load(f) or {}
        return {}

    def generate_scene_image(
        self,
        scene_id: int,
        prompt: str,
        output_path: str | Path,
        reference_image: Optional[str | Path] = None,
        style_description: str = "",
    ) -> Path:
        """
        Generate (or mock) one scene image.

        reference_image: path to a previously generated base/character image for consistency (used by real backends).
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if self.backend == "mock":
            return self._mock_generate(prompt, output_path, scene_id, style_description)
        elif self.backend == "comfyui":
            return self._comfyui_generate(prompt, output_path, reference_image, style_description)
        elif self.backend in ("api_generic", "imagine"):
            return self._api_generate(prompt, output_path, reference_image, style_description)
        else:
            # Safe default
            return self._mock_generate(prompt, output_path, scene_id, style_description)

    def _mock_generate(
        self, prompt: str, output_path: Path, scene_id: int, style: str
    ) -> Path:
        """
        Create a clean vertical placeholder image with the prompt text overlaid.
        Looks decent enough to validate the full video pipeline.
        """
        img = Image.new("RGB", (self.width, self.height), color=(18, 18, 28))
        draw = ImageDraw.Draw(img)

        # Gradient-like dark cinematic background effect via rectangles
        for i in range(0, self.height, 40):
            alpha = int(20 + (i / self.height) * 35)
            color = (25 + alpha // 3, 25 + alpha // 4, 40 + alpha // 2)
            draw.rectangle([0, i, self.width, i + 40], fill=color)

        # Try to use a decent font; fall back gracefully
        try:
            title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 52)
            body_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
        except Exception:
            title_font = ImageFont.load_default()
            body_font = ImageFont.load_default()

        # Header
        draw.text(
            (self.width // 2, 120),
            f"SCENE {scene_id}",
            fill=(180, 200, 255),
            font=title_font,
            anchor="mm",
        )

        # Main prompt text (word-wrapped)
        margin = 80
        max_width = self.width - 2 * margin
        lines = []
        words = (prompt + "\n\n[Style: " + (style or "cinematic vertical") + "]").split()
        current = ""
        for w in words:
            test = current + " " + w if current else w
            bbox = draw.textbbox((0, 0), test, font=body_font)
            if bbox[2] - bbox[0] <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = w
        if current:
            lines.append(current)

        y = 280
        for line in lines[:18]:  # safety
            draw.text(
                (margin, y),
                line,
                fill=(230, 230, 245),
                font=body_font,
            )
            y += 42

        # Subtle bottom label
        draw.text(
            (self.width // 2, self.height - 90),
            "MOCK — replace with real image gen for production",
            fill=(120, 120, 140),
            font=body_font,
            anchor="mm",
        )

        img.save(output_path, "PNG", optimize=True)
        return output_path

    def _comfyui_generate(self, prompt: str, output_path: Path, reference: Optional[Path], style: str) -> Path:
        # Placeholder — user will implement the actual ComfyUI workflow call
        # (queue prompt, poll history, download image)
        raise NotImplementedError(
            "ComfyUI backend not implemented yet. "
            "Run with backend: mock for now, or implement the HTTP workflow execution here. "
            "See ComfyUI docs for /prompt and /history endpoints."
        )

    def _api_generate(self, prompt: str, output_path: Path, reference: Optional[Path], style: str) -> Path:
        # Generic cheap API caller (Runware, fal, etc.). Implement per provider.
        raise NotImplementedError(
            "API backend not implemented. Use 'mock' or add your cheapest provider SDK call here."
        )

    def generate_all_scenes(
        self,
        script_scenes: list,
        style: str,
        images_dir: Path,
        reference_first: bool = True,
    ) -> list[Path]:
        """
        Convenience: generate images for all scenes.
        If reference_first, the first generated image can be passed as reference to later ones (real backends).
        """
        images_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        reference: Optional[Path] = None

        for i, scene in enumerate(script_scenes):
            out = images_dir / f"scene_{scene.id:02d}.png"
            full_prompt = f"{scene.image_prompt}. {style}".strip()
            img_path = self.generate_scene_image(
                scene.id, full_prompt, out, reference_image=reference, style_description=style
            )
            paths.append(img_path)
            if reference_first and reference is None:
                reference = img_path  # subsequent scenes can use this as visual anchor
        return paths
