"""
Video Assembly Agent

Produces final vertical shorts with:
- smooth_i2v: AI-generated motion clips (fal Wan — recommended)
- ffmpeg_kenburns / draw_reveal: static image effects (legacy / free fallback)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml

from utils.ffmpeg_utils import (
    check_ffmpeg,
    create_kenburns_clip,
    create_reveal_clip,
    create_srt_for_scenes,
    concat_clips,
    mix_music,
    burn_simple_captions,
    get_audio_duration,
    mux_motion_video_with_audio,
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
        self.motion_mode = self.video_cfg.get("motion_mode", "smooth_i2v")
        self.i2v_cfg = self.video_cfg.get("fal_i2v", {})

    def _load_config(self) -> dict:
        p = self.config_path
        if not p.exists():
            p = p.parent / "config.example.yaml"
        if p.exists():
            with open(p) as f:
                return yaml.safe_load(f) or {}
        return {}

    def _uses_smooth_i2v(self) -> bool:
        return self.motion_mode in ("smooth_i2v", "api_i2v")

    def assemble(
        self,
        script,
        image_paths: list[Path],
        output_video: str | Path,
        voice: str = "en-US-AriaNeural",
        add_music: bool = True,
    ) -> Path:
        if not check_ffmpeg():
            raise RuntimeError("ffmpeg / ffprobe not found on PATH. Install ffmpeg to use video assembly.")

        output_video = Path(output_video)
        finals_dir = Path(self.paths.get("finals_dir", "outputs/finals"))
        clips_dir = Path(self.paths.get("clips_dir", "outputs/clips"))
        audio_dir = Path(self.paths.get("audio_dir", "outputs/audio"))
        temp_dir = Path(self.paths.get("temp_dir", "outputs/temp"))

        for d in (finals_dir, clips_dir, audio_dir, temp_dir):
            d.mkdir(parents=True, exist_ok=True)

        scene_audios: list[Path] = []
        scene_durations: list[float] = []

        print(f"[video] Generating TTS for {len(script.scenes)} scenes...")
        for scene in script.scenes:
            aud_path = audio_dir / f"scene_{scene.id:02d}.mp3"
            generate_tts(scene.narration, aud_path, voice=voice)
            dur = get_audio_duration(aud_path)
            scene_durations.append(max(2.0, dur))
            scene_audios.append(aud_path)

        use_i2v = self._uses_smooth_i2v() or self.motion_mode == "hybrid"
        allow_fallback = self.video_cfg.get("i2v_fallback", False)

        if self._uses_smooth_i2v():
            print(f"[video] Generating smooth AI motion clips (fal Wan I2V)...")
        elif use_i2v:
            print(f"[video] Creating motion clips (mode={self.motion_mode})...")
        else:
            print(f"[video] Creating clips (mode={self.motion_mode})...")

        clip_paths: list[Path] = []
        raw_i2v_dir = temp_dir / "i2v_raw"
        raw_i2v_dir.mkdir(parents=True, exist_ok=True)
        res = self.video_cfg.get("output_resolution", [1080, 1920])

        for i, (scene, img, aud) in enumerate(zip(script.scenes, image_paths, scene_audios)):
            clip = clips_dir / f"clip_{scene.id:02d}.mp4"
            direction = scene.notes.lower() if "zoom" in (scene.notes or "").lower() else "random"

            scene_uses_i2v = use_i2v and (
                self._uses_smooth_i2v()
                or self.motion_mode == "api_i2v"
                or (self.motion_mode == "hybrid" and "i2v" in (scene.notes or "").lower())
            )

            if scene_uses_i2v:
                from utils.i2v import build_motion_prompt, generate_i2v

                motion_prompt = build_motion_prompt(scene)
                raw_i2v = raw_i2v_dir / f"scene_{scene.id:02d}_raw.mp4"
                try:
                    generate_i2v(
                        image_path=Path(img),
                        prompt=motion_prompt,
                        output_path=raw_i2v,
                        cfg={**self.i2v_cfg, "provider": "fal"},
                    )
                    mux_motion_video_with_audio(
                        raw_i2v, aud, clip,
                        width=res[0], height=res[1],
                        fps=self.video_cfg.get("target_fps", 30),
                        smooth=True,
                    )
                    print(f"  Scene {scene.id}: smooth AI video ✓")
                except Exception as e:
                    if not allow_fallback:
                        raise RuntimeError(
                            f"Smooth video failed for scene {scene.id}: {e}\n"
                            "Set FAL_KEY or enable i2v_fallback in config to use static images."
                        ) from e
                    print(f"  Scene {scene.id}: I2V failed ({e}), falling back to static motion")
                    scene_uses_i2v = False

            if not scene_uses_i2v:
                if self.motion_mode == "draw_reveal":
                    reveal_dir = "top_to_bottom" if i % 2 else "left_to_right"
                    create_reveal_clip(
                        image_path=img, audio_path=aud, output_path=clip,
                        duration=scene_durations[i], width=res[0], height=res[1],
                        fps=self.video_cfg.get("target_fps", 30), direction=reveal_dir,
                    )
                else:
                    create_kenburns_clip(
                        image_path=img, audio_path=aud, output_path=clip,
                        duration=scene_durations[i], width=res[0], height=res[1],
                        zoom_speed=self.ken_cfg.get("zoom_speed", 0.035),
                        direction=direction, fps=self.video_cfg.get("target_fps", 30),
                    )
            clip_paths.append(clip)

        raw_concat = temp_dir / f"{output_video.stem}_concat.mp4"
        concat_clips(clip_paths, raw_concat, scene_durations=scene_durations)

        srt_path = temp_dir / f"{output_video.stem}.srt"
        create_srt_for_scenes(script.scenes, scene_durations, srt_path)

        captioned = temp_dir / f"{output_video.stem}_captioned.mp4"
        cap_cfg = self.captions_cfg or {}
        style_choice = cap_cfg.get("style", "clean_outline")
        if style_choice == "box":
            custom_style = (
                "FontName=DejaVuSans-Bold,Fontsize=42,PrimaryColour=&H00FFFFFF,"
                "OutlineColour=&H00000000,BorderStyle=3,Outline=2,Shadow=1,"
                "Alignment=2,MarginV=90"
            )
        else:
            fontsize = cap_cfg.get("fontsize", 32)
            margin_v = cap_cfg.get("margin_v", 200)
            margin_lr = cap_cfg.get("margin_lr", 70)
            custom_style = (
                f"FontName=DejaVuSans-Bold,Fontsize={fontsize},PrimaryColour=&H00FFFFFF,"
                "OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=0,"
                f"Alignment=2,MarginV={margin_v},MarginL={margin_lr},MarginR={margin_lr}"
            )
        burn_simple_captions(raw_concat, srt_path, captioned, style=custom_style)

        final = output_video
        music_dir = Path(self.video_cfg.get("music_dir", "music"))
        music_file: Optional[Path] = None
        if add_music and music_dir.exists():
            candidates = sorted(music_dir.glob("*.mp3")) + sorted(music_dir.glob("*.wav"))
            if candidates:
                music_file = candidates[0]

        mix_music(
            video_path=captioned,
            music_path=music_file,
            output_path=final,
            music_volume=self.video_cfg.get("music_volume", 0.15),
        )

        print(f"[video] Done → {final}")
        return final