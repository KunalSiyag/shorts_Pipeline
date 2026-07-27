"""Programmatic whiteboard & stick-figure explainer images (no AI needed)."""
from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _fonts():
    try:
        title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 44)
        body = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
        small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 26)
    except OSError:
        title = body = small = ImageFont.load_default()
    return title, body, small


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for w in words:
        test = f"{current} {w}".strip()
        if draw.textlength(test, font=font) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = w
    if current:
        lines.append(current)
    return lines[:6]


def _stick_figure(draw: ImageDraw.ImageDraw, cx: int, cy: int, pose: int, scale: float = 1.0) -> None:
    s = scale
    color = (30, 30, 40)
    w = max(3, int(4 * s))
    # head
    r = int(28 * s)
    draw.ellipse([cx - r, cy - int(120 * s) - r, cx + r, cy - int(120 * s) + r], outline=color, width=w)
    body_top = cy - int(92 * s)
    body_bot = cy + int(30 * s)
    draw.line([cx, body_top, cx, body_bot], fill=color, width=w)
    # legs
    draw.line([cx, body_bot, cx - int(35 * s), cy + int(100 * s)], fill=color, width=w)
    draw.line([cx, body_bot, cx + int(35 * s), cy + int(100 * s)], fill=color, width=w)
    if pose == 0:  # pointing right
        draw.line([cx, body_top + int(20 * s), cx + int(70 * s), cy - int(10 * s)], fill=color, width=w)
        draw.line([cx + int(20 * s), body_top + int(35 * s), cx - int(55 * s), cy + int(5 * s)], fill=color, width=w)
    elif pose == 1:  # explaining arms up
        draw.line([cx, body_top + int(15 * s), cx - int(60 * s), cy - int(50 * s)], fill=color, width=w)
        draw.line([cx, body_top + int(15 * s), cx + int(60 * s), cy - int(50 * s)], fill=color, width=w)
    elif pose == 2:  # thinking
        draw.line([cx, body_top + int(20 * s), cx + int(50 * s), cy - int(30 * s)], fill=color, width=w)
        draw.line([cx + int(20 * s), body_top + int(30 * s), cx - int(45 * s), body_top + int(50 * s)], fill=color, width=w)
    else:  # board gesture
        draw.line([cx, body_top + int(20 * s), cx - int(65 * s), cy - int(20 * s)], fill=color, width=w)
        draw.line([cx, body_top + int(20 * s), cx + int(40 * s), cy - int(40 * s)], fill=color, width=w)


def _whiteboard_frame(draw: ImageDraw.ImageDraw, w: int, h: int) -> None:
    margin = 50
    draw.rectangle([margin, margin, w - margin, h - margin], outline=(200, 200, 210), width=3)
    draw.rectangle([margin + 8, margin + 8, w - margin - 8, h - margin - 8], fill=(252, 252, 250))


def draw_stick_figure_scene(
    scene_id: int,
    narration: str,
    subtitle: str = "",
    width: int = 1080,
    height: int = 1920,
) -> Image.Image:
    img = Image.new("RGB", (width, height), (248, 248, 252))
    draw = ImageDraw.Draw(img)
    title_f, body_f, _ = _fonts()

    draw.text((width // 2, 90), f"Scene {scene_id}", fill=(100, 110, 140), font=title_f, anchor="mm")

    pose = scene_id % 4
    _stick_figure(draw, int(width * 0.38), int(height * 0.42), pose, scale=1.4)

    # Speech bubble
    bx, by = int(width * 0.52), int(height * 0.22)
    bw, bh = int(width * 0.38), int(height * 0.22)
    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=20, fill=(255, 255, 255), outline=(60, 60, 70), width=3)
    lines = _wrap(draw, narration, body_f, bw - 40)
    y = by + 24
    for line in lines[:4]:
        draw.text((bx + 20, y), line, fill=(25, 25, 35), font=body_f)
        y += 38

    # Key idea bullets (unique per scene)
    bullet_y = int(height * 0.62)
    draw.text((80, bullet_y - 50), "Key points:", fill=(50, 50, 60), font=title_f)
    bullets = _wrap(draw, subtitle or narration, body_f, width - 160)[:3]
    for i, b in enumerate(bullets):
        draw.ellipse([80, bullet_y + i * 48 - 4, 100, bullet_y + i * 48 + 16], fill=(80, 130, 220))
        draw.text((115, bullet_y + i * 48), b, fill=(30, 30, 40), font=body_f)

    return img


def draw_whiteboard_scene(
    scene_id: int,
    narration: str,
    concept: str = "",
    width: int = 1080,
    height: int = 1920,
) -> Image.Image:
    img = Image.new("RGB", (width, height), (235, 235, 240))
    draw = ImageDraw.Draw(img)
    title_f, body_f, small_f = _fonts()
    _whiteboard_frame(draw, width, height)

    # Progressive "drawn" content — more elements appear in later scenes
    progress = min(scene_id, 6)
    draw.text((width // 2, 130), f"Step {scene_id}", fill=(40, 40, 50), font=title_f, anchor="mm")

    # Simulated marker strokes (underline + diagram boxes)
    y = 220
    lines = _wrap(draw, narration, body_f, width - 140)
    for i, line in enumerate(lines[:3]):
        draw.text((70, y), line, fill=(20, 20, 30), font=body_f)
        lw = draw.textlength(line, font=body_f)
        if i < progress:
            draw.line([70, y + 36, 70 + lw, y + 36], fill=(220, 60, 60), width=3)
        y += 70

    # Diagram area — unique doodles per scene
    dy = int(height * 0.55)
    colors = [(70, 130, 210), (220, 90, 70), (90, 170, 90), (180, 100, 200)]
    c = colors[scene_id % len(colors)]
    if progress >= 2:
        draw.rectangle([70, dy, width - 70, dy + 280], outline=c, width=4)
        concept_lines = _wrap(draw, concept or narration, small_f, width - 200)[:4]
        ty = dy + 30
        for cl in concept_lines:
            draw.text((100, ty), f"• {cl}", fill=(30, 30, 40), font=small_f)
            ty += 42
    if progress >= 4:
        # Arrow / flow doodle
        ax = width // 2
        draw.line([ax - 120, dy + 320, ax + 120, dy + 320], fill=c, width=5)
        draw.polygon([(ax + 120, dy + 320), (ax + 90, dy + 305), (ax + 90, dy + 335)], fill=c)

    # Hand-with-marker hint (corner)
    if progress >= 1:
        hx, hy = width - 130, height - 200
        draw.ellipse([hx, hy, hx + 40, hy + 40], fill=(255, 220, 180), outline=(80, 60, 50), width=2)
        draw.line([hx + 20, hy + 35, hx - 30, hy + 80], fill=(220, 60, 60), width=6)

    return img


def save_explainer_image(
    style: str,
    scene_id: int,
    narration: str,
    image_prompt: str,
    output_path: Path,
    width: int = 1080,
    height: int = 1920,
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if style == "stick_figure":
        img = draw_stick_figure_scene(scene_id, narration, subtitle=image_prompt, width=width, height=height)
    else:
        img = draw_whiteboard_scene(scene_id, narration, concept=image_prompt, width=width, height=height)
    img.save(output_path, "PNG", optimize=True)
    return output_path