"""
Cheap & high-quality TTS using edge-tts (Microsoft Edge voices).
Free, unlimited, good natural quality, runs locally (no API key).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import edge_tts


DEFAULT_VOICE = "en-US-AriaNeural"  # Pleasant, versatile female voice. Alternatives: en-US-GuyNeural, en-GB-SoniaNeural, etc.


async def _generate_async(text: str, voice: str, output_path: Path) -> None:
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(output_path))


def generate_tts(
    text: str,
    output_path: str | Path,
    voice: str = DEFAULT_VOICE,
) -> Path:
    """
    Generate speech from text. Returns path to the saved .mp3.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # edge-tts is async; run it conveniently
    try:
        asyncio.run(_generate_async(text, voice, output_path))
    except RuntimeError:
        # If already in an event loop (rare in CLI), create a new one
        loop = asyncio.new_event_loop()
        loop.run_until_complete(_generate_async(text, voice, output_path))
        loop.close()

    if not output_path.exists() or output_path.stat().st_size < 100:
        raise RuntimeError(f"TTS generation failed for output: {output_path}")

    return output_path


def estimate_speech_duration_sec(text: str, wpm: float = 150.0) -> float:
    """
    Rough estimate. Real duration comes from the actual audio file.
    """
    words = len(text.split())
    minutes = words / wpm
    return max(1.5, minutes * 60.0 + 0.4)  # small buffer for natural pacing
