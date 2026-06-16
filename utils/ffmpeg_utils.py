"""
FFmpeg utilities for the cheapest possible high-quality short video assembly.

Core technique (zero extra AI cost):
- Take a still image
- Apply slow cinematic Ken Burns motion (zoom + pan) using zoompan filter
- Sync with voiceover audio clip for the scene
- Add basic timed captions
- Concat everything losslessly where possible
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=check)


def check_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def get_audio_duration(path: str | Path) -> float:
    """Return duration in seconds using ffprobe."""
    path = Path(path)
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        out = subprocess.check_output(cmd, text=True).strip()
        return float(out)
    except Exception:
        return 4.0  # safe fallback


def create_kenburns_clip(
    image_path: str | Path,
    audio_path: str | Path,
    output_path: str | Path,
    duration: Optional[float] = None,
    width: int = 1080,
    height: int = 1920,
    zoom_speed: float = 0.035,
    direction: str = "random",
    fps: int = 30,
) -> Path:
    """
    Create one scene video clip from a still image + its audio using Ken Burns effect.

    direction: "in" (slow zoom in), "out" (zoom out), "left", "right", or "random".
    """
    image_path = Path(image_path)
    audio_path = Path(audio_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if duration is None:
        duration = get_audio_duration(audio_path)

    # Build zoompan expression
    # We want very slow, cinematic movement.
    # zoompan works on the input before scaling in many cases; we scale first for safety.
    import random
    if direction == "random":
        direction = random.choice(["in", "out", "left", "right", "in"])

    # Base scale + pad to exact target resolution (letterbox / pillar if needed, but we design prompts for 9:16)
    scale_pad = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
    )

    # zoompan: z starts near 1.0 and slowly increases or decreases.
    # d = duration * fps  (number of frames)
    frames = int(duration * fps) + 2

    if direction == "in":
        z_expr = f"min(1.0+{zoom_speed}*on/{frames},1.18)"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
    elif direction == "out":
        z_expr = f"max(1.18-{zoom_speed}*on/{frames},1.0)"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
    elif direction == "left":
        z_expr = "1.06"
        x_expr = f"iw*0.1 + (iw*0.15)*on/{frames}"
        y_expr = "ih/2-(ih/zoom/2)"
    elif direction == "right":
        z_expr = "1.06"
        x_expr = f"iw*0.25 - (iw*0.15)*on/{frames}"
        y_expr = "ih/2-(ih/zoom/2)"
    else:
        z_expr = "1.0"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"

    vf = (
        f"{scale_pad},"
        f"zoompan=z='{z_expr}':d={frames}:x='{x_expr}':y='{y_expr}':s={width}x{height}:fps={fps},"
        f"format=yuv420p"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(image_path),
        "-i", str(audio_path),
        "-vf", vf,
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "160k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ]

    _run(cmd)
    return output_path


def create_srt_for_scenes(
    scenes: list,
    scene_durations: list[float],
    output_srt: str | Path,
) -> Path:
    """
    Very simple .srt with one caption block per scene.
    For better results later: word-level timing + highlight.
    """
    output_srt = Path(output_srt)
    output_srt.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    t = 0.0
    for i, (scene, dur) in enumerate(zip(scenes, scene_durations), 1):
        start = t
        end = t + dur
        t = end

        def fmt(sec: float) -> str:
            h = int(sec // 3600)
            m = int((sec % 3600) // 60)
            s = int(sec % 60)
            ms = int((sec - int(sec)) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        text = scene.narration.replace("\n", " ").strip()
        # Split into two lines if long
        if len(text) > 70:
            mid = len(text) // 2
            # try to split near a space
            space = text.find(" ", mid - 10, mid + 15)
            if space > 0:
                text = text[:space] + "\n" + text[space + 1 :]
            else:
                text = text[:mid] + "\n" + text[mid:]

        lines.append(str(i))
        lines.append(f"{fmt(start)} --> {fmt(end)}")
        lines.append(text)
        lines.append("")

    output_srt.write_text("\n".join(lines), encoding="utf-8")
    return output_srt


def concat_clips(clip_paths: list[Path], output_path: Path, with_transitions: bool = True) -> Path:
    """
    Concatenate scene clips into final video.
    Uses stream copy when possible (fast, no re-encode).
    For simple crossfade transitions we would need to re-encode or use complex filter.
    Start with pure concat for maximum cheapness + quality.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if len(clip_paths) == 1:
        shutil.copy2(clip_paths[0], output_path)
        return output_path

    # Write concat list
    concat_list = output_path.parent / "concat_list.txt"
    with open(concat_list, "w") as f:
        for p in clip_paths:
            f.write(f"file '{p.resolve()}'\n")

    # Fast concat (assumes all clips same codec / resolution / framerate)
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    _run(cmd)
    concat_list.unlink(missing_ok=True)
    return output_path


def mix_music(
    video_path: str | Path,
    music_path: Optional[str | Path],
    output_path: str | Path,
    music_volume: float = 0.12,
    duck_level: float = 0.35,  # not fully implemented in simple version
) -> Path:
    """
    Simple music bed under the video.
    For real ducking you would use sidechain or a more complex filtergraph.
    """
    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not music_path or not Path(music_path).exists():
        # No music — just copy
        shutil.copy2(video_path, output_path)
        return output_path

    music_path = Path(music_path)

    # Loop music if needed + lower volume
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-stream_loop", "-1",
        "-i", str(music_path),
        "-filter_complex",
        f"[1:a]volume={music_volume},aloop=loop=-1:size=2e9[bg];[0:a][bg]amix=inputs=2:duration=first[aout]",
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "160k",
        "-shortest",
        str(output_path),
    ]
    _run(cmd)
    return output_path


def burn_simple_captions(
    video_with_audio: str | Path,
    srt_path: str | Path,
    output_path: str | Path,
) -> Path:
    """
    Burn the .srt onto the video using subtitles filter.
    Styling is basic; tune force_style for your look.
    """
    video_with_audio = Path(video_with_audio)
    srt_path = Path(srt_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Escape path for filter (single quotes around filename)
    srt_escaped = str(srt_path).replace("'", "'\\''")

    style = (
        "FontName=DejaVuSans-Bold,Fontsize=42,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BorderStyle=3,Outline=2.5,Shadow=1.5,"
        "Alignment=2,MarginV=90"
    )

    vf = f"subtitles='{srt_escaped}':force_style='{style}'"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_with_audio),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "17",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    _run(cmd)
    return output_path
