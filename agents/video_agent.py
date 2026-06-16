"""
Video Assembly Agent

Takes:
- A VideoScript
- List of scene images (same order)
- Generated audio (or generates it)

Produces a final vertical short using the cheapest possible high-retention techniques:
- Ken Burns motion on images (ffmpeg)
- Per-scene or full audio
- Simple but effective captions
- Optional royalty-free music bed
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

# Ensure we can import sibling utils when running as script or -c
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml

from utils.ffmpeg_utils import (
    check_ffmpeg,
    create_kenburns_clip,
    create_srt_for_scenes,
    concat_clips,
    mix_music,
    burn_simple_captions,
    get_audio_duration,
)
from utils.tts import generate_tts


class VideoAgent:
    def __init__(self, config_path: str | Path = "config.yaml"):
        self.config_path = Path(config_path)
        self.cfg = self._load_config()
        self.paths = self.cfg.get("paths", {})
        self.video_cfg = self.cfg.get("video_assembly", {})
        self.ken_cfg = self.video_cfg.get("kenburns", {})
        self.captions_cfg = self.video_cfg.get("captions", {})
        self.motion_mode = self.video_cfg.get("motion_mode", "ffmpeg_kenburns")

    def _load_config(self) -> dict:
        p = self.config_path
        if not p.exists():
            p = p.parent / "config.example.yaml"
        if p.exists():
            with open(p) as f:
                return yaml.safe_load(f) or {}
        return {}

    def assemble(
        self,
        script,                      # VideoScript instance
        image_paths: list[Path],
        output_video: str | Path,
        voice: str = "en-US-AriaNeural",
        add_music: bool = True,
    ) -> Path:
        """
        Full assembly pipeline for one short.
        """
        if not check_ffmpeg():
            raise RuntimeError("ffmpeg / ffprobe not found on PATH. Install ffmpeg to use video assembly.")

        output_video = Path(output_video)
        finals_dir = Path(self.paths.get("finals_dir", "outputs/finals"))
        clips_dir = Path(self.paths.get("clips_dir", "outputs/clips"))
        audio_dir = Path(self.paths.get("audio_dir", "outputs/audio"))
        temp_dir = Path(self.paths.get("temp_dir", "outputs/temp"))

        for d in (finals_dir, clips_dir, audio_dir, temp_dir):
            d.mkdir(parents=True, exist_ok=True)

        # 1. Generate per-scene audio (or could do one big audio + timestamps)
        scene_audios: list[Path] = []
        scene_durations: list[float] = []

        print(f"[video] Generating TTS for {len(script.scenes)} scenes...")
        for scene in script.scenes:
            aud_path = audio_dir / f"scene_{scene.id:02d}.mp3"
            generate_tts(scene.narration, aud_path, voice=voice)
            dur = get_audio_duration(aud_path)
            # respect the script hint but use real audio length (more accurate)
            scene_durations.append(max(2.0, dur))
            scene_audios.append(aud_path)

        # 2. Create motion clips per scene
        print("[video] Creating Ken Burns clips...")
        clip_paths: list[Path] = []
        for i, (scene, img, aud) in enumerate(zip(script.scenes, image_paths, scene_audios)):
            clip = clips_dir / f"clip_{scene.id:02d}.mp4"
            dur = scene_durations[i]
            direction = scene.notes.lower() if "zoom" in (scene.notes or "").lower() else "random"

            create_kenburns_clip(
                image_path=img,
                audio_path=aud,
                output_path=clip,
                duration=dur,
                width=self.video_cfg.get("output_resolution", [1080, 1920])[0],
                height=self.video_cfg.get("output_resolution", [1080, 1920])[1],
                zoom_speed=self.ken_cfg.get("zoom_speed", 0.035),
                direction=direction,
                fps=self.video_cfg.get("target_fps", 30),
            )
            clip_paths.append(clip)

        # 3. Concat raw clips
        raw_concat = temp_dir / f"{output_video.stem}_concat.mp4"
        concat_clips(clip_paths, raw_concat)

        # 4. Create captions
        srt_path = temp_dir / f"{output_video.stem}.srt"
        create_srt_for_scenes(script.scenes, scene_durations, srt_path)

        # 5. Burn captions
        captioned = temp_dir / f"{output_video.stem}_captioned.mp4"
        burn_simple_captions(raw_concat, srt_path, captioned)

        # 6. Mix music if available
        final = output_video
        music_dir = Path(self.video_cfg.get("music_dir", "music"))
        music_file: Optional[Path] = None
        if add_music and music_dir.exists():
            candidates = sorted(music_dir.glob("*.mp3")) + sorted(music_dir.glob("*.wav"))
            if candidates:
                music_file = candidates[0]  # simple: take first one. Later: smarter selection or loop

        mix_music(
            video_path=captioned,
            music_path=music_file,
            output_path=final,
            music_volume=self.video_cfg.get("music_volume", 0.15),
        )

        print(f"[video] Done → {final}")
        return final
