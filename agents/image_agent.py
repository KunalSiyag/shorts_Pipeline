"""
Image Generation Agent

Pluggable backends for cheapest possible image creation while supporting
consistency (reference images, style prompts).

Current implementations:
- mock: Fast, zero-cost placeholder images (pipeline testing only).
- pollinations: Free cloud API, no API key. Good default for real images.
- comfyui: Local open-source (Flux/SDXL) via ComfyUI HTTP API.
- fal / runware: Cheap paid APIs (~$0.003–0.01 per image).
"""
from __future__ import annotations

import random
import time
import urllib.parse
from pathlib import Path
from typing import Any, Optional

import requests
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
        elif self.backend == "fal":
            return self._fal_generate(prompt, output_path, reference_image, style_description)
        elif self.backend == "runware":
            return self._runware_generate(prompt, output_path, reference_image, style_description)
        elif self.backend == "explainer":
            return self._explainer_generate(prompt, output_path, scene_id, style_description)
        elif self.backend == "pollinations":
            return self._pollinations_generate(prompt, output_path, reference_image, style_description)
        elif self.backend == "grok":
            return self._grok_generate(prompt, output_path, reference_image, style_description)
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
        """
        Generate image using local ComfyUI (https://github.com/comfyanonymous/ComfyUI).

        ComfyUI is NOT "just a connector". It is a complete local Stable Diffusion / Flux interface.
        It loads open-source models directly on your GPU (no cloud, no per-image cost).

        Our code just sends the prompt + settings via its REST API and downloads the result.

        Recommended open-source models for images:
        - Flux.1-schnell or Flux.1-dev (best quality right now)
        - SDXL, SD 3, or Lightning models for speed on lower VRAM
        """
        comfy_cfg: dict[str, Any] = self.cfg.get("image_generation", {}).get("comfyui", {})
        base_url = str(comfy_cfg.get("base_url", "http://127.0.0.1:8188")).rstrip("/")
        gen_width = int(comfy_cfg.get("width", self.width))
        gen_height = int(comfy_cfg.get("height", self.height))

        checkpoint = comfy_cfg.get("checkpoint", "flux1-schnell.safetensors")  # Change to your actual model file
        steps = int(comfy_cfg.get("steps", 4))  # Flux schnell is very fast
        cfg_scale = float(comfy_cfg.get("cfg", 1.0))
        sampler_name = comfy_cfg.get("sampler_name", "euler")
        scheduler = comfy_cfg.get("scheduler", "simple")
        negative_prompt = comfy_cfg.get(
            "negative_prompt",
            "blurry, low quality, text, watermark, deformed"
        )
        denoise_strength = float(comfy_cfg.get("denoise", 0.65 if reference else 1.0))

        full_prompt = f"{prompt}, {style}".strip() if style else prompt

        try:
            workflow = self._build_comfyui_workflow(
                prompt=full_prompt,
                negative_prompt=negative_prompt,
                width=gen_width,
                height=gen_height,
                steps=steps,
                cfg=cfg_scale,
                sampler_name=sampler_name,
                scheduler=scheduler,
                seed=random.randint(0, 2**32 - 1),
                checkpoint=checkpoint,
                reference_image=reference,
                denoise=denoise_strength,
                base_url=base_url,
            )

            # Queue the workflow
            queue_resp = requests.post(f"{base_url}/prompt", json={"prompt": workflow}, timeout=30)
            queue_resp.raise_for_status()
            prompt_id = queue_resp.json()["prompt_id"]

            # Poll until done
            outputs: dict[str, Any] = {}
            for _ in range(300):  # max ~5 minutes
                time.sleep(1)
                history_resp = requests.get(f"{base_url}/history/{prompt_id}", timeout=10)
                history = history_resp.json()
                if prompt_id in history:
                    outputs = history[prompt_id].get("outputs", {})
                    if outputs:
                        break

            if not outputs:
                raise RuntimeError("ComfyUI timed out waiting for image generation.")

            # Find saved image (usually from SaveImage node)
            image_info: dict[str, Any] | None = None
            for node_output in outputs.values():
                if "images" in node_output and node_output["images"]:
                    image_info = node_output["images"][0]
                    break

            if not image_info:
                raise RuntimeError("No image was produced by ComfyUI workflow. "
                                   "Ensure your workflow ends with a SaveImage node.")

            # Download the image
            view_params = {
                "filename": image_info["filename"],
                "subfolder": image_info.get("subfolder", ""),
                "type": image_info.get("type", "output"),
            }
            img_resp = requests.get(f"{base_url}/view", params=view_params, timeout=60)
            img_resp.raise_for_status()

            output_path.write_bytes(img_resp.content)
            return output_path

        except requests.RequestException as e:
            raise RuntimeError(
                f"Failed to communicate with ComfyUI at {base_url}. "
                f"Is ComfyUI running? Error: {e}"
            ) from e
        except Exception as e:
            if isinstance(e, RuntimeError):
                raise
            raise RuntimeError(f"ComfyUI generation failed: {e}") from e

    def _build_comfyui_workflow(
        self,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        steps: int,
        cfg: float,
        sampler_name: str,
        scheduler: str,
        seed: int,
        checkpoint: str,
        reference_image: Optional[Path],
        denoise: float,
        base_url: str,
    ) -> dict[str, Any]:
        """Build ComfyUI workflow. Special handling for Flux models."""
        workflow: dict[str, Any] = {}
        is_flux = "flux" in checkpoint.lower()

        if is_flux:
            # Flux workflow optimized for low VRAM (GGUF recommended for 4GB)
            # Assumes you have installed ComfyUI-GGUF custom node for .gguf files
            # Place .gguf in models/unet/
            # clip_l.safetensors and t5xxl_fp8 in models/clip/
            # ae.safetensors in models/vae/
            if ".gguf" in checkpoint.lower():
                workflow["4"] = {
                    "inputs": {"unet_name": checkpoint, "weight_dtype": "default"},
                    "class_type": "UnetLoaderGGUF",  # From ComfyUI-GGUF
                }
            else:
                workflow["4"] = {
                    "inputs": {"unet_name": checkpoint, "weight_dtype": "fp8_e4m3fn"},
                    "class_type": "UNETLoader",
                }

            workflow["5"] = {
                "inputs": {
                    "clip_name1": "clip_l.safetensors",
                    "clip_name2": "t5xxl_fp8_e4m3fn.safetensors",
                    "type": "flux"
                },
                "class_type": "DualCLIPLoader",
            }
            workflow["6"] = {
                "inputs": {"text": prompt, "clip": ["5", 0]},
                "class_type": "CLIPTextEncode",
            }
            workflow["7"] = {
                "inputs": {"text": negative_prompt or "", "clip": ["5", 0]},
                "class_type": "CLIPTextEncode",
            }
            workflow["8"] = {
                "inputs": {"vae_name": "ae.safetensors"},
                "class_type": "VAELoader",
            }

            if reference_image and reference_image.exists():
                try:
                    uploaded_name = self._upload_image(base_url, reference_image)
                    workflow["9"] = {"inputs": {"image": uploaded_name}, "class_type": "LoadImage"}
                    workflow["10"] = {"inputs": {"pixels": ["9", 0], "vae": ["8", 0]}, "class_type": "VAEEncode"}
                    latent_node = ["10", 0]
                    denoise_val = denoise
                except Exception:
                    workflow["11"] = {"inputs": {"width": width, "height": height, "batch_size": 1}, "class_type": "EmptyLatentImage"}
                    latent_node = ["11", 0]
                    denoise_val = 1.0
            else:
                workflow["11"] = {"inputs": {"width": width, "height": height, "batch_size": 1}, "class_type": "EmptyLatentImage"}
                latent_node = ["11", 0]
                denoise_val = 1.0

            workflow["3"] = {
                "inputs": {
                    "seed": seed,
                    "steps": steps,
                    "cfg": cfg,
                    "sampler_name": sampler_name,
                    "scheduler": scheduler,
                    "denoise": denoise_val,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": latent_node,
                },
                "class_type": "KSampler",
            }
            workflow["12"] = {"inputs": {"samples": ["3", 0], "vae": ["8", 0]}, "class_type": "VAEDecode"}
            workflow["13"] = {
                "inputs": {"filename_prefix": f"shorts_flux_{int(time.time())}", "images": ["12", 0]},
                "class_type": "SaveImage",
            }
        else:
            # Standard SD workflow (for SDXL, SD1.5 etc.)
            workflow["4"] = {
                "inputs": {"ckpt_name": checkpoint},
                "class_type": "CheckpointLoaderSimple",
            }
            workflow["5"] = {
                "inputs": {"text": prompt, "clip": ["4", 1]},
                "class_type": "CLIPTextEncode",
            }
            workflow["6"] = {
                "inputs": {"text": negative_prompt, "clip": ["4", 1]},
                "class_type": "CLIPTextEncode",
            }

            if reference_image and reference_image.exists():
                try:
                    uploaded_name = self._upload_image(base_url, reference_image)
                    workflow["10"] = {"inputs": {"image": uploaded_name}, "class_type": "LoadImage"}
                    workflow["11"] = {"inputs": {"pixels": ["10", 0], "vae": ["4", 2]}, "class_type": "VAEEncode"}
                    latent_node = ["11", 0]
                    denoise_val = denoise
                except:
                    latent_node = ["7", 0]
                    denoise_val = 1.0
            else:
                workflow["7"] = {
                    "inputs": {"width": width, "height": height, "batch_size": 1},
                    "class_type": "EmptyLatentImage",
                }
                latent_node = ["7", 0]
                denoise_val = 1.0

            workflow["3"] = {
                "inputs": {
                    "seed": seed,
                    "steps": steps,
                    "cfg": cfg,
                    "sampler_name": sampler_name,
                    "scheduler": scheduler,
                    "denoise": denoise_val,
                    "model": ["4", 0],
                    "positive": ["5", 0],
                    "negative": ["6", 0],
                    "latent_image": latent_node,
                },
                "class_type": "KSampler",
            }
            workflow["8"] = {
                "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
                "class_type": "VAEDecode",
            }
            workflow["9"] = {
                "inputs": {
                    "filename_prefix": f"shorts_scene_{int(time.time())}",
                    "images": ["8", 0],
                },
                "class_type": "SaveImage",
            }

        return workflow

    def _upload_image(self, base_url: str, image_path: Path) -> str:
        """Upload an image to ComfyUI so it can be used by LoadImage node."""
        with open(image_path, "rb") as f:
            files = {"image": (image_path.name, f, "image/png")}
            data = {"overwrite": "true", "type": "input"}
            resp = requests.post(f"{base_url}/upload/image", files=files, data=data, timeout=30)
            resp.raise_for_status()
            result = resp.json()
            # ComfyUI returns the name it stored it under
            return result.get("name", image_path.name)

    def _explainer_generate(
        self, prompt: str, output_path: Path, scene_id: int, style: str
    ) -> Path:
        """Draw whiteboard or stick-figure explainer frames (unique per scene)."""
        from utils.explainer_draw import save_explainer_image

        explainer_cfg = self.cfg.get("image_generation", {}).get("explainer", {})
        draw_style = explainer_cfg.get("style", "whiteboard")
        narration = prompt.split(".")[0] if prompt else "Explain this concept"
        save_explainer_image(
            style=draw_style,
            scene_id=scene_id,
            narration=narration[:200],
            image_prompt=prompt,
            output_path=output_path,
            width=self.width,
            height=self.height,
        )
        return output_path

    def _pollinations_generate(
        self, prompt: str, output_path: Path, reference: Optional[Path], style: str
    ) -> Path:
        """Free image generation via Pollinations.ai (no API key required).

        Best zero-cost option when ComfyUI is not set up. Quality is decent for shorts.
        Rate limits apply — add small delays between scenes.
        """
        poll_cfg: dict[str, Any] = self.cfg.get("image_generation", {}).get("pollinations", {})
        base_url = poll_cfg.get("base_url", "https://image.pollinations.ai/prompt")
        model = poll_cfg.get("model", "flux")
        enhance = poll_cfg.get("enhance", True)
        seed = poll_cfg.get("seed") or random.randint(0, 2**31 - 1)

        full_prompt = f"{prompt}. {style}. vertical 9:16 cinematic".strip() if style else prompt
        # Pollinations works best with shorter prompts
        if len(full_prompt) > 500:
            full_prompt = full_prompt[:497] + "..."

        params = {
            "width": self.width,
            "height": self.height,
            "nologo": "true",
            "enhance": str(enhance).lower(),
            "model": model,
            "seed": seed,
        }
        url = f"{base_url}/{urllib.parse.quote(full_prompt)}?{urllib.parse.urlencode(params)}"

        last_err: Optional[Exception] = None
        for attempt in range(4):
            try:
                resp = requests.get(url, timeout=120)
                if resp.status_code == 429:
                    time.sleep(5 * (attempt + 1))
                    continue
                resp.raise_for_status()
                if len(resp.content) < 1000:
                    raise RuntimeError("Pollinations returned an empty or invalid image.")
                output_path.write_bytes(resp.content)
                return output_path
            except requests.RequestException as e:
                last_err = e
                time.sleep(3 * (attempt + 1))
        raise RuntimeError(
            f"Pollinations generation failed after retries: {last_err}. "
            "Free tier has rate limits — wait a few minutes, or use fal (~$0.006/image) / comfyui (local)."
        ) from last_err

    def _fal_generate(self, prompt: str, output_path: Path, reference: Optional[Path], style: str) -> Path:
        """Generate using fal.ai (cheap high-quality Flux etc.). Requires FAL_KEY env or config."""
        import fal_client
        import os

        full_prompt = f"{prompt}. {style}".strip() if style else prompt
        model = self.cfg.get("image_generation", {}).get("fal", {}).get("model", "fal-ai/flux/schnell")

        try:
            # fal_client uses env FAL_KEY by default
            result = fal_client.subscribe(
                model,
                arguments={
                    "prompt": full_prompt,
                    "image_size": {"width": self.width, "height": self.height},  # or "portrait_9_16" etc.
                    "num_inference_steps": 4,
                    "guidance_scale": 3.5,
                    # For img2img if reference:
                    # "image_url": ... if reference
                },
            )
            image_url = result["images"][0]["url"]
            img_resp = requests.get(image_url, timeout=60)
            img_resp.raise_for_status()
            output_path.write_bytes(img_resp.content)
            return output_path
        except Exception as e:
            raise RuntimeError(f"fal.ai generation failed: {e}. Set FAL_KEY env var or in UI.") from e

    def _runware_generate(self, prompt: str, output_path: Path, reference: Optional[Path], style: str) -> Path:
        """Generate using Runware (one of the cheapest APIs). Requires RUNWARE_API_KEY."""
        import asyncio
        from runware import Runware, IImageInference

        full_prompt = f"{prompt}. {style}".strip() if style else prompt
        model = self.cfg.get("image_generation", {}).get("runware", {}).get("model", "runware:101@1")

        async def _run():
            runware = Runware()
            await runware.connect()
            request = IImageInference(
                positivePrompt=full_prompt,
                model=model,
                width=self.width,
                height=self.height,
                numberResults=1,
            )
            images = await runware.imageInference(requestImage=request)
            if images:
                img_url = images[0].imageURL
                img_resp = requests.get(img_url, timeout=60)
                img_resp.raise_for_status()
                output_path.write_bytes(img_resp.content)
                return output_path
            raise RuntimeError("No image returned from Runware")

        try:
            return asyncio.run(_run())
        except Exception as e:
            raise RuntimeError(f"Runware generation failed: {e}. Set RUNWARE_API_KEY.") from e

    def _grok_generate(self, prompt: str, output_path: Path, reference: Optional[Path], style: str) -> Path:
        """Grok image generation.

        You only have in-app Grok access (no xAI API key).
        This backend is only useful *inside this chat*.

        When you select "grok" in the UI here, I will generate the images for you
        using Grok Imagine (the tool available in this session).

        For running the pipeline on your own machine later:
        → Do NOT use the "grok" image backend.
        → Use "comfyui" (best) or "fal"/"runware" (cheap cloud).
        """
        full_prompt = f"{prompt}. {style}".strip() if style else prompt

        raise RuntimeError(
            "You are inside a Grok session.\n"
            "When using the Streamlit UI and you choose 'grok' for images, "
            "tell me and I will generate the actual images here using Grok Imagine.\n\n"
            "For normal use on your PC, install ComfyUI and use the 'comfyui' backend (completely free)."
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
        reference_first: bool = False,
    ) -> list[Path]:
        """
        Generate images for all scenes. reference_first=False by default so each scene looks distinct.
        """
        img_cfg = self.cfg.get("image_generation", {})
        if img_cfg.get("reference_scenes") is True:
            reference_first = True

        images_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        reference: Optional[Path] = None

        for i, scene in enumerate(script_scenes):
            out = images_dir / f"scene_{scene.id:02d}.png"
            full_prompt = f"{scene.image_prompt}. {style}".strip()
            # Explainer backend uses narration from scene object when available
            if self.backend == "explainer":
                narration = getattr(scene, "narration", full_prompt)
                img_path = self.generate_scene_image(
                    scene.id, narration, out,
                    reference_image=None,
                    style_description=scene.image_prompt,
                )
            else:
                img_path = self.generate_scene_image(
                    scene.id, full_prompt, out,
                    reference_image=reference if reference_first else None,
                    style_description=style,
                )
            paths.append(img_path)
            if self.backend == "pollinations" and i < len(script_scenes) - 1:
                time.sleep(2)
            if reference_first and reference is None:
                reference = img_path
        return paths
