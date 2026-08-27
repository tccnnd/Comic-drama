from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont

from scripts.rw_models import StoryScene
from scripts.rw_styles import normalize_crop_box
from scripts.rw_utils import clamp


def font_candidates() -> list[Path]:
    return [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/msyhbd.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/simsun.ttc"),
    ]


def pick_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = font_candidates()
    if bold:
        candidates = [p for p in candidates if "bd" in p.name.lower()] + [
            p for p in candidates if "bd" not in p.name.lower()
        ]
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    normalized = value.replace("0x", "#")
    return ImageColor.getrgb(normalized)


def blend_color(value: str, factor: float) -> tuple[int, int, int]:
    r, g, b = hex_to_rgb(value)
    target = (12, 16, 26)
    return (
        int(r * (1 - factor) + target[0] * factor),
        int(g * (1 - factor) + target[1] * factor),
        int(b * (1 - factor) + target[2] * factor),
    )


def wrap_for_pixels(text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    if not text:
        return [""]
    lines: list[str] = []
    current = ""
    for ch in text:
        trial = current + ch
        if font.getlength(trial) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines


def draw_paragraph(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    font,
    fill,
    spacing: int = 14,
) -> None:
    x0, y0, x1, y1 = box
    y = y0
    line_height = None
    for paragraph in text.splitlines():
        wrapped = wrap_for_pixels(paragraph, font, x1 - x0)
        for line in wrapped:
            bbox = draw.textbbox((x0, y), line, font=font)
            line_height = bbox[3] - bbox[1]
            if y + line_height > y1:
                draw.text((x0, max(y0, y1 - line_height)), "…", font=font, fill=fill)
                return
            draw.text((x0, y), line, font=font, fill=fill)
            y = bbox[3] + spacing
        y += spacing // 2


def apply_crop_box(
    image: Image.Image, crop_box: object, target_size: tuple[int, int] = (1080, 1920)
) -> Image.Image:
    width, height = image.size
    if width <= 0 or height <= 0:
        return image.resize(target_size, Image.Resampling.LANCZOS)
    box = normalize_crop_box(crop_box)
    x0 = int(round(box["x"] * width))
    y0 = int(round(box["y"] * height))
    crop_w = max(1, int(round(box["width"] * width)))
    crop_h = max(1, int(round(box["height"] * height)))
    x0 = int(clamp(x0, 0, max(0, width - crop_w)))
    y0 = int(clamp(y0, 0, max(0, height - crop_h)))
    x1 = min(width, x0 + crop_w)
    y1 = min(height, y0 + crop_h)
    return image.crop((x0, y0, x1, y1)).resize(target_size, Image.Resampling.LANCZOS)


def split_text_chunks(text: str, parts: int = 2) -> list[str]:
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return [""] * max(1, parts)
    if parts <= 1:
        return [cleaned]

    targets = max(1, math.ceil(len(cleaned) / parts))
    chunks: list[str] = []
    start = 0
    for index in range(parts - 1):
        end = min(len(cleaned), start + targets)
        while end < len(cleaned) and cleaned[end] not in "。！？!?，,；;":
            end += 1
        piece = cleaned[start:end].strip()
        if not piece:
            piece = cleaned[start : min(len(cleaned), start + targets)].strip()
            end = min(len(cleaned), start + targets)
        chunks.append(piece)
        start = end
    chunks.append(cleaned[start:].strip())
    return [chunk for chunk in chunks if chunk] or [cleaned]


def focal_crop(image: Image.Image, zoom: float, center_x: float, center_y: float) -> Image.Image:
    width, height = image.size
    zoom = max(1.0, zoom)
    crop_w = int(width / zoom)
    crop_h = int(height / zoom)
    x0 = int(clamp(center_x * width - crop_w / 2, 0, max(0, width - crop_w)))
    y0 = int(clamp(center_y * height - crop_h / 2, 0, max(0, height - crop_h)))
    return image.crop((x0, y0, x0 + crop_w, y0 + crop_h)).resize(
        (width, height), Image.Resampling.LANCZOS
    )


def emotion_stamp(emotion: str) -> str:
    value = emotion.strip()
    if not value:
        return ""
    for keyword, stamp in (
        ("震撼", "轰"),
        ("压迫", "压"),
        ("反转", "!!"),
        ("决绝", "啪"),
        ("悬疑", "?"),
        ("愤怒", "怒"),
        ("悲伤", "痛"),
    ):
        if keyword in value:
            return stamp
    return value[:2]


def create_keyframe(scene: StoryScene, run_dir: Path) -> Path:
    scene_id = f"{scene.scene:02}"
    out = run_dir / f"scene_{scene_id}_keyframe.png"
    size = (1080, 1920)
    base = Image.new("RGBA", size, hex_to_rgb(scene.bg_color) + (255,))
    draw = ImageDraw.Draw(base, "RGBA")

    top_rgb = blend_color(scene.bg_color, 0.12)
    bottom_rgb = blend_color(scene.bg_color, 0.62)
    for y in range(size[1]):
        t = y / max(1, size[1] - 1)
        rgb = (
            int(top_rgb[0] * (1 - t) + bottom_rgb[0] * t),
            int(top_rgb[1] * (1 - t) + bottom_rgb[1] * t),
            int(top_rgb[2] * (1 - t) + bottom_rgb[2] * t),
        )
        draw.line((0, y, size[0], y), fill=rgb + (255,))

    rng = random.Random(scene.scene * 17)
    accent = hex_to_rgb(scene.accent_color)

    rain = Image.new("RGBA", size, (0, 0, 0, 0))
    rain_draw = ImageDraw.Draw(rain, "RGBA")
    for _ in range(140):
        x = rng.randint(-80, size[0] + 80)
        y = rng.randint(0, size[1])
        length = rng.randint(40, 180)
        alpha = rng.randint(14, 38)
        rain_draw.line((x, y, x + 18, y + length), fill=accent + (alpha,), width=rng.randint(1, 2))
    rain = rain.filter(ImageFilter.GaussianBlur(0.5))
    base = Image.alpha_composite(base, rain)

    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow, "RGBA")
    glow_draw.ellipse((-140, 140, 980, 980), fill=accent + (68,))
    glow_draw.ellipse((250, 1120, 1220, 1860), fill=(255, 255, 255, 16))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    base = Image.alpha_composite(base, glow)
    draw = ImageDraw.Draw(base, "RGBA")

    horizon_y = 1210
    draw.rectangle((0, horizon_y, size[0], size[1]), fill=(0, 0, 0, 42))
    draw.polygon(
        [(0, 1180), (260, 1020), (420, 1110), (720, 980), (1080, 1120), (1080, 1920), (0, 1920)],
        fill=(8, 10, 18, 122),
    )

    silhouette = [
        (200, 1460),
        (250, 1170),
        (320, 1080),
        (390, 1160),
        (420, 1480),
        (360, 1600),
        (240, 1600),
    ]
    draw.polygon(silhouette, fill=(8, 8, 12, 210))
    draw.ellipse((318, 1032, 430, 1148), fill=(18, 18, 24, 220))
    draw.polygon(
        [(630, 1540), (690, 1220), (760, 1120), (840, 1200), (862, 1510), (792, 1640), (650, 1640)],
        fill=(12, 12, 18, 200),
    )
    draw.ellipse((742, 1068, 870, 1184), fill=(24, 24, 30, 220))

    title_font = pick_font(64, bold=True)
    subtitle_font = pick_font(34, bold=True)
    meta_font = pick_font(24, bold=True)
    body_font = pick_font(40, bold=True)

    title_box = (60, 70, 430, 216)
    draw.rounded_rectangle(
        title_box, radius=24, fill=(6, 8, 14, 190), outline=accent + (180,), width=3
    )
    draw.text((92, 98), scene.title, font=title_font, fill=(255, 255, 255, 255))
    draw.text((92, 166), scene.camera, font=meta_font, fill=accent + (255,))

    bottom_box = (74, 1602, 1006, 1838)
    draw.rounded_rectangle(
        bottom_box, radius=30, fill=(8, 10, 16, 202), outline=accent + (160,), width=3
    )
    draw.text((108, 1640), scene.emotion, font=subtitle_font, fill=accent + (255,))
    draw_paragraph(
        draw, scene.dialogue, (108, 1698, 962, 1810), body_font, (245, 245, 245, 255), spacing=10
    )

    for idx, character in enumerate(scene.characters[:3]):
        chip_x = 600 + idx * 150
        draw.rounded_rectangle(
            (chip_x, 96, chip_x + 128, 146),
            radius=18,
            fill=accent + (34,),
            outline=accent + (160,),
            width=2,
        )
        draw.text((chip_x + 16, 105), character[:6], font=meta_font, fill=(250, 250, 250, 240))

    for _ in range(28):
        x = rng.randint(0, size[0])
        y = rng.randint(0, size[1])
        length = rng.randint(20, 80)
        draw.line(
            (x, y, x + rng.randint(-16, 16), y + length),
            fill=(255, 255, 255, rng.randint(18, 42)),
            width=1,
        )

    base = base.filter(ImageFilter.GaussianBlur(0.2))
    base.convert("RGB").save(out, quality=95)
    return out


def compose_comic_frame(
    source_image: Image.Image,
    scene: StoryScene,
    beat: dict[str, object],
    run_dir: Path,
    scene_id: str,
    beat_index: int,
    beat_total: int,
) -> Path:
    size = source_image.size
    frame = focal_crop(
        source_image,
        float(beat["zoom"]),
        float(beat["center_x"]),
        float(beat["center_y"]),
    ).convert("RGBA")
    accent = hex_to_rgb(scene.accent_color)

    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay, "RGBA")
    overlay_draw.rectangle((0, 0, size[0], 132), fill=(6, 8, 14, 72))
    overlay_draw.rectangle((0, size[1] - 250, size[0], size[1]), fill=(6, 8, 14, 140))
    overlay_draw.rectangle((0, size[1] - 266, size[0], size[1] - 256), fill=accent + (180,))
    overlay_draw.rounded_rectangle(
        (52, 44, 360, 140), radius=22, fill=(10, 12, 20, 168), outline=accent + (160,), width=2
    )
    overlay_draw.rounded_rectangle(
        (size[0] - 264, 44, size[0] - 52, 140),
        radius=22,
        fill=accent + (34,),
        outline=accent + (160,),
        width=2,
    )
    overlay_draw.rounded_rectangle(
        (64, size[1] - 206, size[0] - 64, size[1] - 72),
        radius=26,
        fill=(8, 10, 16, 190),
        outline=(255, 255, 255, 54),
        width=2,
    )
    frame = Image.alpha_composite(frame, overlay)
    draw = ImageDraw.Draw(frame, "RGBA")

    display_index = max(1, int(beat_index))
    title_font = pick_font(32, bold=True)
    meta_font = pick_font(22, bold=True)
    body_font = pick_font(36, bold=True)

    draw.text((78, 66), scene.title, font=title_font, fill=(255, 255, 255, 255))
    draw.text((78, 104), str(beat["label"])[:18], font=meta_font, fill=accent + (255,))
    draw.text(
        (size[0] - 236, 66),
        f"{display_index}/{beat_total}",
        font=meta_font,
        fill=(250, 250, 250, 220),
    )
    draw.text(
        (size[0] - 236, 104), str(beat["caption"])[:10], font=meta_font, fill=(250, 250, 250, 180)
    )

    subtitle = str(beat["bubble"]) or scene.dialogue
    draw_paragraph(
        draw,
        subtitle,
        (92, size[1] - 184, size[0] - 92, size[1] - 88),
        body_font,
        (245, 245, 245, 255),
        spacing=8,
    )

    footer = f"{scene.camera}  |  {scene.emotion}"
    footer_bbox = draw.textbbox((0, 0), footer, font=meta_font)
    draw.text(
        ((size[0] - (footer_bbox[2] - footer_bbox[0])) / 2, size[1] - 54),
        footer,
        font=meta_font,
        fill=(240, 240, 240, 180),
    )

    out = run_dir / f"scene_{scene_id}_beat_{display_index}.png"
    frame.convert("RGB").save(out, quality=95)
    return out
