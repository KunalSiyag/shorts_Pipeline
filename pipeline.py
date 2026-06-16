#!/usr/bin/env python3
"""
Main orchestrator for the cheap automatic shorts pipeline.

Usage examples:
    python pipeline.py --topic "5 insane facts about the universe that will blow your mind"
    python pipeline.py --topic "..." --config myconfig.yaml --output outputs/my_short.mp4

This runs the three stages:
1. Scripting Agent (Ollama or cheap LLM)
2. Image Agent (starts with fast mock; swap to real cheap backend later)
3. Video Agent (ffmpeg Ken Burns + TTS + captions + music — the zero-extra-cost motion solution)

Designed to be extremely low marginal cost while still producing watchable, high-retention vertical shorts.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Make local imports work when running from root
sys.path.insert(0, str(Path(__file__).parent))

from agents import ScriptAgent, ImageAgent, VideoAgent
from agents.script_agent import VideoScript


def main():
    parser = argparse.ArgumentParser(description="Generate a cheap vertical short video from a topic.")
    parser.add_argument("--topic", "-t", type=str, default=None,
                        help="The core idea or title for the short (e.g. 'Top 5 black hole facts')")
    parser.add_argument("--script-json", type=str, default=None,
                        help="Path to a pre-generated VideoScript JSON (bypasses LLM for testing or manual scripts)")
    parser.add_argument("--config", "-c", type=str, default="config.yaml",
                        help="Path to config.yaml (falls back to config.example.yaml)")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Final output video path (default: outputs/finals/<sanitized topic>.mp4)")
    parser.add_argument("--voice", type=str, default="en-US-AriaNeural",
                        help="edge-tts voice (en-US-AriaNeural, en-US-GuyNeural, etc.)")
    parser.add_argument("--no-music", action="store_true", help="Disable background music")
    parser.add_argument("--skip-images", action="store_true", help="Assume images already exist (for debugging assembly)")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Config {config_path} not found — using config.example.yaml as fallback.")
        config_path = Path("config.example.yaml")

    if args.script_json:
        print(f"\n=== Using pre-generated script: {args.script_json} ===\n")
        with open(args.script_json) as f:
            script_data = __import__("json").load(f)
        script = VideoScript.model_validate(script_data)  # type: ignore
        print(f"  Title: {script.title}")
        print(f"  Scenes: {len(script.scenes)}")
        script_path = Path(args.script_json)
    else:
        if not args.topic:
            parser.error("--topic is required unless --script-json is provided")
        print(f"\n=== Generating short for topic: {args.topic} ===\n")

        # === 1. SCRIPTING ===
        print("[1/3] Running scripting agent...")
        script_agent = ScriptAgent(config_path)
        script = script_agent.generate(args.topic)
        print(f"  Title: {script.title}")
        print(f"  Scenes: {len(script.scenes)}")
        print(f"  Style: {script.overall_style[:80]}...")

        # Save script for inspection / iteration
        scripts_dir = Path("outputs/scripts")
        scripts_dir.mkdir(parents=True, exist_ok=True)
        script_path = scripts_dir / f"{_slug(args.topic)}.json"
        script_agent.save_script(script, script_path)
        print(f"  Saved script → {script_path}")

    # === 2. IMAGES ===
    print("\n[2/3] Running image agent (mock by default for zero cost)...")
    image_agent = ImageAgent(config_path)
    topic_for_slug = args.topic or script.title
    images_dir = Path(image_agent.paths.get("images_dir", "outputs/images")) / _slug(topic_for_slug)
    images_dir.mkdir(parents=True, exist_ok=True)

    if args.skip_images:
        # Try to load existing
        image_paths = sorted(images_dir.glob("scene_*.png"))
        if not image_paths:
            raise FileNotFoundError("No existing images found and --skip-images was used.")
        print(f"  Using {len(image_paths)} pre-existing images from {images_dir}")
    else:
        image_paths = image_agent.generate_all_scenes(
            script.scenes,
            style=script.overall_style,
            images_dir=images_dir,
            reference_first=True,
        )
        print(f"  Generated {len(image_paths)} scene images → {images_dir}")

    # === 3. VIDEO ASSEMBLY ===
    print("\n[3/3] Running video assembly (ffmpeg Ken Burns + TTS + captions)...")
    video_agent = VideoAgent(config_path)

    if args.output:
        final_path = Path(args.output)
    else:
        finals_dir = Path(video_agent.paths.get("finals_dir", "outputs/finals"))
        finals_dir.mkdir(parents=True, exist_ok=True)
        slug = _slug(args.topic or script.title)
        final_path = finals_dir / f"{slug}.mp4"

    final = video_agent.assemble(
        script=script,
        image_paths=image_paths,
        output_video=final_path,
        voice=args.voice,
        add_music=not args.no_music,
    )

    print("\n" + "=" * 50)
    print(f"SUCCESS! Final short saved to:\n  {final.resolve()}")
    print("=" * 50)
    print("\nNext steps for cheaper/better results:")
    print("  • Inspect the video and the saved JSON script.")
    print("  • Tune prompts/script_system.txt for your niche.")
    print("  • Switch image_generation.backend in config to a real cheap API or local ComfyUI.")
    print("  • Add better music selection or word-level captions later.")
    print("  • Batch multiple topics with a small wrapper script.")


def _slug(text: str) -> str:
    import re
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return s[:60] or "short"


if __name__ == "__main__":
    main()
