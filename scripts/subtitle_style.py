"""
ASS subtitle style helpers.

The workflow still writes normal SRT files for portability.  This module only
builds richer ASS output: per-speaker colors plus light emotion emphasis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ASS color format is &HAABBGGRR&.  Alpha 00 means fully opaque.
SPEAKER_PALETTE = [
    "&H0066D1FF&",  # warm yellow
    "&H00FFA34E&",  # blue
    "&H008DD143&",  # green
    "&H008F5DFF&",  # pink
    "&H00FFD166&",  # cyan-gold
    "&H00A020E8&",  # purple
    "&H0040C0FF&",  # orange
    "&H00B5E61D&",  # lime
]

DEFAULT_COLOR = "&H00FFFFFF&"
OUTLINE_COLOR = "&H00101010&"
BACK_COLOR = "&H7F000000&"

EMOTION_EMPHASIS: dict[str, tuple[int, int]] = {
    "anger": (1, 0),
    "fear": (1, 0),
    "surprise": (1, 0),
    "sadness": (0, 1),
}


@dataclass(frozen=True)
class AssDialogueEntry:
    start: float
    end: float
    text: str
    speaker: str = ""
    emotion_tone: str = ""


@dataclass(frozen=True)
class AssStyle:
    name: str
    color: str
    bold: int = 0
    italic: int = 0


def normalize_ass_entries(entries: list[tuple]) -> list[AssDialogueEntry]:
    """Accept legacy (start, end, text) tuples and enriched 5-tuples."""
    normalized: list[AssDialogueEntry] = []
    for item in entries:
        if len(item) < 3:
            continue
        start, end, text = item[:3]
        speaker = item[3] if len(item) >= 4 else ""
        emotion_tone = item[4] if len(item) >= 5 else ""
        normalized.append(
            AssDialogueEntry(
                start=float(start),
                end=float(end),
                text=str(text or ""),
                speaker=str(speaker or "").strip(),
                emotion_tone=str(emotion_tone or "").strip().lower(),
            )
        )
    return normalized


def build_ass_document(
    entries: list[tuple],
    subtitle_style: dict[str, Any],
    *,
    play_res_x: int = 1080,
    play_res_y: int = 1920,
) -> str:
    normalized_entries = normalize_ass_entries(entries)
    speaker_colors = _speaker_colors(normalized_entries)
    styles = _styles_for_entries(normalized_entries, speaker_colors)

    chunks = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {play_res_x}",
        f"PlayResY: {play_res_y}",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
    ]
    for style in styles.values():
        chunks.append(_style_line(style, subtitle_style))
    chunks.extend(
        [
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
    )

    for entry in normalized_entries:
        if not entry.text.strip():
            continue
        style_name = _style_name_for_entry(entry, speaker_colors)
        chunks.append(
            f"Dialogue: 0,{ass_timestamp(entry.start)},{ass_timestamp(entry.end)},"
            f"{style_name},{_safe_ass_field(entry.speaker)},0,0,0,,{ass_escape_text(entry.text.strip())}"
        )
    return "\n".join(chunks)


def ass_timestamp(seconds: float) -> str:
    centiseconds = int(round(max(0.0, float(seconds)) * 100))
    hours, rem = divmod(centiseconds, 360000)
    minutes, rem = divmod(rem, 6000)
    secs, centiseconds = divmod(rem, 100)
    return f"{hours}:{minutes:02}:{secs:02}.{centiseconds:02}"


def ass_escape_text(text: str) -> str:
    value = str(text or "")
    return (
        value.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\r", "")
        .replace("\n", r"\N")
    )


def _speaker_colors(entries: list[AssDialogueEntry]) -> dict[str, str]:
    colors: dict[str, str] = {}
    for entry in entries:
        speaker = entry.speaker.strip()
        if not speaker or speaker in colors:
            continue
        colors[speaker] = SPEAKER_PALETTE[len(colors) % len(SPEAKER_PALETTE)]
    return colors


def _styles_for_entries(entries: list[AssDialogueEntry], speaker_colors: dict[str, str]) -> dict[str, AssStyle]:
    styles: dict[str, AssStyle] = {
        "ComicDrama": AssStyle("ComicDrama", DEFAULT_COLOR, bold=0, italic=0)
    }
    for entry in entries:
        style_name = _style_name_for_entry(entry, speaker_colors)
        if style_name in styles:
            continue
        color = speaker_colors.get(entry.speaker, DEFAULT_COLOR)
        bold, italic = EMOTION_EMPHASIS.get(entry.emotion_tone, (0, 0))
        styles[style_name] = AssStyle(style_name, color, bold=bold, italic=italic)
    return styles


def _style_name_for_entry(entry: AssDialogueEntry, speaker_colors: dict[str, str]) -> str:
    if entry.speaker:
        speaker_index = list(speaker_colors).index(entry.speaker) + 1 if entry.speaker in speaker_colors else 0
        base = f"Speaker{speaker_index:02d}" if speaker_index else "ComicDrama"
    else:
        base = "ComicDrama"
    if entry.emotion_tone in EMOTION_EMPHASIS:
        return f"{base}_{entry.emotion_tone}"
    return base


def _style_line(style: AssStyle, subtitle_style: dict[str, Any]) -> str:
    font_name = _safe_ass_field(str(subtitle_style.get("font_name") or "Microsoft YaHei"))
    font_size = int(subtitle_style.get("font_size") or 34)
    outline = int(subtitle_style.get("outline") or 2)
    shadow = int(subtitle_style.get("shadow") or 0)
    alignment = int(subtitle_style.get("alignment") or 2)
    margin_v = int(subtitle_style.get("margin_v") or 120)
    return (
        f"Style: {style.name},{font_name},{font_size},{style.color},&H000000FF,"
        f"{OUTLINE_COLOR},{BACK_COLOR},{style.bold},{style.italic},0,0,100,100,0,0,1,"
        f"{outline},{shadow},{alignment},48,48,{margin_v},1"
    )


def _safe_ass_field(value: str) -> str:
    return str(value or "").replace(",", "").replace("\n", " ").replace("\r", " ").strip()
