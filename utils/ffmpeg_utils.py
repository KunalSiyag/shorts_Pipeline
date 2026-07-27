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


def _wrap_caption_text(text: str, max_chars_per_line: int = 24, max_lines: int = 2) -> str:
    """Wrap text into at most max_lines, keeping each line <= max_chars_per_line.
    Prefers splitting at spaces. Produces clean, short lines so subtitles
    don't dominate the vertical frame.
    """
    words = text.split()
    if not words:
        return ""
    lines = []
    current = ""
    for word in words:
        if len(current) + 1 + len(word) <= max_chars_per_line:
            current = (current + " " + word).strip()
        else:
            if current:
                lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    # If text was extremely long, truncate last line gracefully
    result = "\n".join(lines[:max_lines])
    if len(result.replace("\n", " ")) < len(text) and len(lines) >= max_lines:
        # Truncate last line if needed (rare for well-written scripts)
        last = lines[-1]
        if len(last) > max_chars_per_line - 3:
            last = last[:max_chars_per_line-3] + "..."
        lines[-1] = last
        result = "\n".join(lines[:max_lines])
    return result


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
        # Smart wrap: aim for max ~38 chars per line, max 2 lines for clean shorts captions
        text = _wrap_caption_text(text, max_chars_per_line=24, max_lines=2)

        lines.append(str(i))
        lines.append(f"{fmt(start)} --> {fmt(end)}")
        lines.append(text)
        lines.append("")

    output_srt.write_text("\n".join(lines), encoding="utf-8")
    return output_srt


def concat_clips(
    clip_paths: list[Path],
    output_path: Path,
    with_transitions: bool = True,
    scene_durations: Optional[list[float]] = None,
) -> Path:
    """
    Concatenate scene clips.
    If with_transitions=True, uses xfade (fadeblack) for smooth transitions between scenes.
    Falls back to stream-copy concat if xfade fails (e.g. mismatched codecs).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if len(clip_paths) == 1:
        shutil.copy2(clip_paths[0], output_path)
        return output_path

    def _concat_copy() -> Path:
        concat_list = output_path.parent / "concat_list.txt"
        with open(concat_list, "w") as f:
            for p in clip_paths:
                f.write(f"file '{p.resolve()}'\n")
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ]
        _run(cmd)
        concat_list.unlink(missing_ok=True)
        return output_path

    if not with_transitions:
        return _concat_copy()

    durations = scene_durations or [get_audio_duration(p) for p in clip_paths]
    if len(durations) != len(clip_paths):
        durations = [4.0] * len(clip_paths)

    n = len(clip_paths)
    fade_dur = 0.4
    inputs: list[str] = []
    for p in clip_paths:
        inputs += ["-i", str(p)]

    filter_parts: list[str] = []
    prev = "[0:v]"
    cumulative = durations[0]
    for i in range(n - 1):
        offset = max(0.5, cumulative - fade_dur)
        out = f"[x{i}]"
        filter_parts.append(
            f"{prev}[{i + 1}:v]xfade=transition=fadeblack:duration={fade_dur}:offset={offset:.3f}{out}"
        )
        prev = out
        cumulative += durations[i + 1] - fade_dur

    fc = ";".join(filter_parts)
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", fc,
        "-map", prev,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]
    try:
        _run(cmd)
        return output_path
    except subprocess.CalledProcessError:
        return _concat_copy()


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


def create_reveal_clip(
    image_path: str | Path,
    audio_path: str | Path,
    output_path: str | Path,
    duration: Optional[float] = None,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    direction: str = "left_to_right",
) -> Path:
    """Animate a still as if being drawn/revealed (whiteboard wipe effect)."""
    image_path = Path(image_path)
    audio_path = Path(audio_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if duration is None:
        duration = get_audio_duration(audio_path)

    reveal_end = max(0.8, duration * 0.72)
    if direction == "top_to_bottom":
        wipe_expr = f"if(lt(Y,H*T/{reveal_end:.3f}),B,A)"
    else:
        wipe_expr = f"if(lt(X,W*T/{reveal_end:.3f}),B,A)"

    fc = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:white,format=rgba[fg];"
        f"color=c=white:s={width}x{height}:d={duration:.3f},fps={fps},format=rgba[bg];"
        f"[bg][fg]blend=all_expr='{wipe_expr}':shortest=1,format=yuv420p[v]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(image_path),
        "-i", str(audio_path),
        "-filter_complex", fc,
        "-map", "[v]", "-map", "1:a",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "160k",
        "-shortest", "-movflags", "+faststart",
        str(output_path),
    ]
    _run(cmd)
    return output_path


def mux_motion_video_with_audio(
    video_path: str | Path,
    audio_path: str | Path,
    output_path: str | Path,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    smooth: bool = True,
) -> Path:
    """Fit a silent AI motion clip to narration length, then mux audio.

    Uses time-stretch (not jerky looping) when the clip is shorter than the voiceover.
    """
    video_path = Path(video_path)
    audio_path = Path(audio_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    target_dur = get_audio_duration(audio_path)
    src_dur = max(0.5, get_audio_duration(video_path))

    scale_pad = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
    )

    if src_dur < target_dur * 0.95:
        # Slow-mo stretch to fill narration (smoother than looping)
        pts_factor = target_dur / src_dur
        vf = f"{scale_pad},setpts={pts_factor:.4f}*PTS,fps={fps},format=yuv420p"
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-vf", vf,
            "-t", str(target_dur),
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "160k",
            "-shortest", "-movflags", "+faststart",
            str(output_path),
        ]
    else:
        vf = f"{scale_pad},fps={fps},format=yuv420p"
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-vf", vf,
            "-t", str(target_dur),
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "160k",
            "-shortest", "-movflags", "+faststart",
            str(output_path),
        ]
    _run(cmd)
    return output_path


def burn_simple_captions(
    video_with_audio: str | Path,
    srt_path: str | Path,
    output_path: str | Path,
    style: str | None = None,
) -> Path:
    """
    Burn the .srt onto the video using subtitles filter.
    Uses a clean transparent style by default (no big box).
    You can pass a custom ASS style string via the style param.
    """
    video_with_audio = Path(video_with_audio)
    srt_path = Path(srt_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Escape path for filter (single quotes around filename)
    srt_escaped = str(srt_path).replace("'", "'\\''")

    if style is None:
        style = (
            "FontName=DejaVuSans-Bold,"
            "FontSize=32,"
            "PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,"
            "BorderStyle=1,"
            "Outline=3,Bold=1,"
            "Shadow=0,Alignment=2,"
            "MarginV=200,MarginL=70,MarginR=70"
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
