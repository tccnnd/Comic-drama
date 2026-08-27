from __future__ import annotations

import math
import random
import re
import wave
from pathlib import Path

from backend.config_utils import coerce_bool as _coerce_bool
from backend.config_utils import coerce_float as _coerce_float
from backend.config_utils import coerce_int as _coerce_int
from scripts.bgm_matcher import select_bgm_for_scene
from scripts.rw_config import (
    AUDIO_ASSET_EXTENSIONS,
    AUDIO_ASSETS,
    DEFAULT_AUDIO_MANIFEST,
    DEFAULT_SUBPROCESS_TIMEOUTS,
    DEFAULT_SUBTITLE_STYLE,
)
from scripts.rw_ffmpeg import get_ffmpeg_exe, run_guarded
from scripts.rw_models import StoryScene
from scripts.rw_styles import (
    default_audio_style,
    normalize_audio_manifest,
    normalize_audio_style,
    normalize_subtitle_style,
)
from scripts.rw_utils import clamp, ensure_parent, media_duration, wav_duration, write_text
from scripts.rw_voice import split_dialogue_lines, split_dialogue_speaker
from scripts.subtitle_style import build_ass_document


def _subtitle_rolls(pacing: str, emotion: str) -> tuple[int, int]:
    pacing = str(pacing or "").strip().lower()
    emotion = str(emotion or "").strip().lower()
    if pacing == "fast" or emotion == "anger":
        return 40, 120
    if pacing == "slow" or emotion in {"sadness", "calm"}:
        return 120, 350
    return 80, 200


def write_scene_subtitles(
    scene_id: str,
    dialogue_segments: list[tuple[str, str]],
    durations: list[float],
    path: Path,
    subtitle_style: dict | None = None,
    ass_path: Path | None = None,
    emotion_tone: str = "",
    pacing: str = "",
    default_speaker: str = "",
) -> None:
    style = normalize_subtitle_style(subtitle_style)
    pre_roll_ms, post_roll_ms = _subtitle_rolls(pacing, emotion_tone)
    pre_roll = pre_roll_ms / 1000.0
    post_roll = post_roll_ms / 1000.0
    min_duration = 0.80
    total_duration = max(0.0, sum(max(0.0, float(duration)) for duration in durations))
    scene_end_cap = total_duration - 0.05 if total_duration > 0.05 else total_duration
    cursor = 0.0
    segments: list[tuple[float, float, str, str]] = []
    for (speaker, spoken_text), duration in zip(dialogue_segments, durations):
        effective_speaker = speaker or default_speaker
        text = format_subtitle_text(effective_speaker, spoken_text, style)
        if not text:
            cursor += duration
            continue
        audio_start = cursor
        audio_end = cursor + duration
        segments.append((audio_start, audio_end, effective_speaker, text))
        cursor += duration
    entries: list[tuple[float, float, str]] = []
    ass_entries: list[tuple[float, float, str, str, str]] = []
    for index, (audio_start, audio_end, effective_speaker, text) in enumerate(segments):
        sub_start = max(0.0, audio_start - pre_roll)
        raw_end = audio_end + post_roll
        if index + 1 < len(segments):
            next_audio_start = segments[index + 1][0]
            next_start = max(0.0, next_audio_start - pre_roll)
            sub_end = min(raw_end, next_start - 0.02)
        else:
            sub_end = raw_end
        sub_end = min(sub_end, scene_end_cap)
        if sub_end <= sub_start:
            sub_end = min(scene_end_cap, sub_start + max(0.25, audio_end - audio_start))
        if sub_end - sub_start < min_duration and sub_end < scene_end_cap:
            sub_end = min(scene_end_cap, sub_start + min_duration)
        entries.append((sub_start, sub_end, text))
        ass_entries.append((sub_start, sub_end, text, effective_speaker, emotion_tone))
    write_srt_entries(entries, path)
    if ass_path is not None:
        write_ass_entries(ass_entries, ass_path, style)


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


def write_ass_entries(entries: list[tuple], path: Path, subtitle_style: dict | None = None) -> None:
    style = normalize_subtitle_style(subtitle_style)
    write_text(path, build_ass_document(entries, style))


def ffmpeg_escape_filter_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(":", "\\:")


def burn_subtitles_to_video(
    ffmpeg: str,
    video_path: Path,
    subtitles_path: Path,
    out_path: Path,
    subtitle_style: dict | None = None,
    timeout_s: int | None = None,
) -> Path:
    style = normalize_subtitle_style(subtitle_style)
    fonts_dir = Path("C:/Windows/Fonts")
    force_style = ",".join(
        [
            f"FontName={style['font_name']}",
            f"FontSize={style['font_size']}",
            f"Outline={style['outline']}",
            f"Shadow={style['shadow']}",
            f"Alignment={style['alignment']}",
            f"MarginV={style['margin_v']}",
        ]
    )
    subtitle_filter = (
        f"subtitles='{ffmpeg_escape_filter_path(subtitles_path)}'"
        f":fontsdir='{ffmpeg_escape_filter_path(fonts_dir)}'"
        f":force_style='{force_style}'"
    )
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        "-vf",
        subtitle_filter,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        str(out_path),
    ]
    run_guarded(
        cmd,
        cwd=out_path.parent,
        timeout=timeout_s or DEFAULT_SUBPROCESS_TIMEOUTS["ffmpeg_render"],
        stage="ffmpeg_burn_subtitles",
    )
    return out_path


def db_to_linear(value_db: float) -> float:
    return 10 ** (float(value_db) / 20.0)


def normalize_audio_track(
    ffmpeg: str, input_path: Path, out_path: Path, audio_style: dict | None = None
) -> Path:
    style = normalize_audio_style(audio_style)
    audio_filter = ",".join(
        [
            f"loudnorm=I={style['master_lufs']}:TP={style['true_peak']}:LRA={style['loudness_range']}:linear=true:print_format=summary",
            f"alimiter=limit={style['limiter_level']}",
        ]
    )
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(input_path),
        "-af",
        audio_filter,
        "-c:a",
        "pcm_s16le",
        str(out_path),
    ]
    run_guarded(
        cmd,
        cwd=out_path.parent,
        timeout=DEFAULT_SUBPROCESS_TIMEOUTS["ffmpeg_audio"],
        stage="ffmpeg_normalize_audio",
    )
    return out_path


def resolve_path(base_dir: Path | None, raw_path: str) -> Path | None:
    value = str(raw_path or "").strip()
    if not value:
        return None
    candidate = Path(value)
    if candidate.is_absolute() or base_dir is None:
        return candidate
    return (base_dir / candidate).resolve()


def mix_voice_with_bgm(
    ffmpeg: str,
    voice_path: Path,
    out_path: Path,
    duration: float,
    audio_style: dict | None = None,
    project_root: Path | None = None,
) -> Path:
    style = normalize_audio_style(audio_style)
    bgm_path = resolve_path(project_root, style.get("bgm_path", ""))
    if bgm_path is None or not bgm_path.exists():
        return voice_path

    bgm_gain = db_to_linear(style["bgm_gain_db"])
    fade_duration = min(1.0, max(0.12, float(duration) / 5.0))
    fade_out_start = max(0.0, float(duration) - fade_duration)
    filter_complex = ";".join(
        [
            (
                f"[1:a]volume={bgm_gain:.6f},"
                f"afade=t=in:st=0:d={fade_duration:.3f},"
                f"afade=t=out:st={fade_out_start:.3f}:d={fade_duration:.3f},"
                "aformat=sample_rates=48000:channel_layouts=stereo[bgm]"
            ),
            f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo[voice]",
            (
                f"[bgm][voice]sidechaincompress=threshold={style['duck_threshold']}:ratio={style['duck_ratio']}"
                f":attack={style['duck_attack_ms']}:release={style['duck_release_ms']}:makeup=1[ducked]"
            ),
            "[voice][ducked]amix=inputs=2:duration=first:normalize=0[mixed]",
            (
                f"[mixed]loudnorm=I={style['master_lufs']}:TP={style['true_peak']}:LRA={style['loudness_range']}:linear=true:print_format=summary"
                f",alimiter=limit={style['limiter_level']}[final]"
            ),
        ]
    )
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(voice_path),
        "-stream_loop",
        "-1",
        "-i",
        str(bgm_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[final]",
        "-t",
        f"{max(0.25, float(duration)):.3f}",
        "-c:a",
        "pcm_s16le",
        str(out_path),
    ]
    run_guarded(
        cmd,
        cwd=out_path.parent,
        timeout=max(60, min(180, int(max(0.25, float(duration)) * 4 + 20))),
        stage="ffmpeg_mix_voice_bgm",
    )
    return out_path


def audio_manifest_dict(scene: StoryScene) -> dict[str, object]:
    return scene.audio_manifest if isinstance(scene.audio_manifest, dict) else {}


def resolve_audio_asset(kind: str, value: object, project_root: Path | None = None) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidate = resolve_path(project_root, raw)
    if candidate and candidate.exists():
        return candidate

    asset_dir = AUDIO_ASSETS / kind
    raw_path = Path(raw)
    names = [raw_path.name]
    if raw_path.suffix:
        names.append(raw)
    else:
        names.extend(f"{raw}{suffix}" for suffix in AUDIO_ASSET_EXTENSIONS)
    for name in dict.fromkeys(names):
        candidate = asset_dir / name
        if candidate.exists():
            return candidate
    return None


def normalize_sfx_kind(value: object) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "slap": "hit",
        "punch": "hit",
        "impact": "hit",
        "knock": "hit",
        "table": "boom",
        "desk": "boom",
        "slam": "boom",
        "explosion": "boom",
        "thunder": "thunder",
        "lightning": "thunder",
        "drop": "drop",
        "fall": "drop",
        "pen": "drop",
        "whoosh": "whoosh",
        "spark": "spark",
        "hit": "hit",
        "boom": "boom",
    }
    return aliases.get(raw, raw)


def scene_audio_style(
    scene: StoryScene, audio_style: dict | None = None, project_root: Path | None = None
) -> dict:
    style = normalize_audio_style(audio_style)
    manifest = audio_manifest_dict(scene)
    bgm_root = AUDIO_ASSETS / "bgm"
    selection = select_bgm_for_scene(scene, manifest, bgm_root=bgm_root, project_root=project_root)
    if selection.path is not None:
        style["bgm_path"] = str(selection.path)
        if selection.style:
            style["bgm_style"] = selection.style
        if selection.source:
            style["bgm_source"] = selection.source
    elif manifest.get("bgm_file") or manifest.get("bgm_path") or manifest.get("bgm_style"):
        bgm_value = (
            manifest.get("bgm_file") or manifest.get("bgm_path") or manifest.get("bgm_style")
        )
        bgm_path = resolve_audio_asset("bgm", bgm_value, project_root=project_root)
        if bgm_path is not None:
            style["bgm_path"] = str(bgm_path)
    if manifest.get("bgm_gain_db") not in (None, ""):
        style["bgm_gain_db"] = _coerce_float(
            manifest.get("bgm_gain_db"), style["bgm_gain_db"], -60.0, 0.0
        )
    return style


def srt_timestamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def format_subtitle_text(speaker: str, text: str, subtitle_style: dict | None = None) -> str:
    style = normalize_subtitle_style(subtitle_style)
    speaker = speaker.strip()
    text = text.strip()
    if not text:
        return ""
    if speaker and style.get("show_speaker", True):
        return f"{speaker}：{text}"
    return text


def write_srt_entries(entries: list[tuple[float, float, str]], path: Path) -> None:
    chunks: list[str] = []
    index = 1
    for start, end, text in entries:
        if not text.strip():
            continue
        chunks.append(
            f"{index}\n" f"{srt_timestamp(start)} --> {srt_timestamp(end)}\n" f"{text.strip()}\n"
        )
        index += 1
    write_text(path, "\n".join(chunks))


def write_srt(scenes: list[StoryScene], path: Path) -> None:
    cursor = 0.0
    entries: list[tuple[float, float, str]] = []
    for scene in scenes:
        start = cursor
        end = cursor + scene.duration
        entries.append((start, end, scene.dialogue))
        cursor = end
    write_srt_entries(entries, path)


def write_srt_from_durations(scenes: list[StoryScene], durations: list[float], path: Path) -> None:
    cursor = 0.0
    entries: list[tuple[float, float, str]] = []
    for scene, duration in zip(scenes, durations):
        start = cursor
        end = cursor + duration
        entries.append((start, end, scene.dialogue))
        cursor = end
    write_srt_entries(entries, path)


def parse_srt_timestamp(value: str) -> float:
    match = re.match(r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})$", value.strip())
    if not match:
        return 0.0
    hours, minutes, seconds, millis = map(int, match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def parse_srt_entries(path: Path) -> list[tuple[float, float, str]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    entries: list[tuple[float, float, str]] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [line.strip("\r") for line in block.splitlines() if line.strip("\r")]
        if len(lines) < 2:
            continue
        time_line = lines[1] if "-->" in lines[1] else lines[0]
        body_lines = lines[2:] if "-->" in lines[1] else lines[1:]
        match = re.match(r"(.+?)\s*-->\s*(.+)", time_line)
        if not match:
            continue
        start = parse_srt_timestamp(match.group(1))
        end = parse_srt_timestamp(match.group(2))
        text_body = "\n".join(body_lines).strip()
        if text_body:
            entries.append((start, end, text_body))
    return entries


def offset_srt_entries(
    entries: list[tuple[float, float, str]], offset: float
) -> list[tuple[float, float, str]]:
    return [(start + offset, end + offset, text) for start, end, text in entries]


def _scene_field(scene: StoryScene | dict | None, field: str, default: object = "") -> object:
    if scene is None:
        return default
    if isinstance(scene, dict):
        return scene.get(field, default)
    return getattr(scene, field, default)


def _scene_subtitle_emotion(scene: StoryScene | dict | None) -> str:
    tone = str(_scene_field(scene, "emotion_tone", "") or "").strip()
    if tone:
        return tone
    meta = _scene_field(scene, "director_meta", None)
    if isinstance(meta, dict):
        return str(meta.get("emotion_tone") or "").strip()
    return ""


def _scene_dialogue_segments(scene: StoryScene | dict | None) -> list[tuple[str, str]]:
    dialogue = str(_scene_field(scene, "dialogue", "") or "")
    segments = split_dialogue_lines(dialogue)
    if segments:
        return segments
    speaker = str(_scene_field(scene, "speaker", "") or "").strip()
    return [(speaker, dialogue.strip())] if dialogue.strip() else []


def stitch_scene_subtitles(
    scene_files: list[Path],
    durations: list[float],
    path: Path,
    fallback_scenes: list[StoryScene] | None = None,
    ass_path: Path | None = None,
    subtitle_style: dict | None = None,
) -> None:
    cursor = 0.0
    entries: list[tuple[float, float, str]] = []
    ass_entries: list[tuple[float, float, str, str, str]] = []
    for index, scene_file in enumerate(scene_files):
        scene = (
            fallback_scenes[index]
            if fallback_scenes is not None and index < len(fallback_scenes)
            else None
        )
        local_entries = parse_srt_entries(scene_file)
        if not local_entries and scene is not None:
            local_entries = [
                (0.0, durations[index], str(_scene_field(scene, "dialogue", "") or "").strip())
            ]
        offset_entries = offset_srt_entries(local_entries, cursor)
        entries.extend(offset_entries)
        scene_segments = _scene_dialogue_segments(scene)
        emotion_tone = _scene_subtitle_emotion(scene)
        scene_speaker = str(_scene_field(scene, "speaker", "") or "").strip()
        for local_index, (start, end, text) in enumerate(offset_entries):
            speaker = scene_speaker
            if local_index < len(scene_segments) and scene_segments[local_index][0]:
                speaker = scene_segments[local_index][0]
            ass_entries.append((start, end, text, speaker, emotion_tone))
        cursor += durations[index] if index < len(durations) else 0.0
    write_srt_entries(entries, path)
    if ass_path is not None:
        write_ass_entries(ass_entries if ass_entries else entries, ass_path, subtitle_style)


def write_tone_sfx(path: Path, kind: str, duration: float = 0.32, sample_rate: int = 44100) -> Path:
    ensure_parent(path)
    kind = (kind or "whoosh").strip().lower()
    duration = max(0.08, min(0.8, float(duration)))
    frame_count = int(sample_rate * duration)
    rng = random.Random(f"{path.name}:{kind}")
    frames = bytearray()
    for frame in range(frame_count):
        t = frame / sample_rate
        p = frame / max(1, frame_count - 1)
        if kind in {"hit", "slap"}:
            freq = 120 + 70 * (1 - p)
            envelope = math.exp(-9.0 * p)
            sample = math.sin(2 * math.pi * freq * t) * envelope
            sample += (rng.random() * 2 - 1) * 0.16 * math.exp(-15.0 * p)
        elif kind == "boom":
            freq = 72 + 50 * (1 - p)
            envelope = math.exp(-5.5 * p)
            sample = math.sin(2 * math.pi * freq * t) * envelope
            sample += (rng.random() * 2 - 1) * 0.11 * math.exp(-10.0 * p)
        elif kind == "thunder":
            rumble = math.sin(2 * math.pi * (52 + 18 * math.sin(9 * t)) * t)
            crack = (rng.random() * 2 - 1) * math.exp(-18.0 * p)
            envelope = math.exp(-2.8 * p)
            sample = rumble * envelope * 0.45 + crack * 0.2
        elif kind == "drop":
            ping = math.sin(2 * math.pi * 1250 * t) * math.exp(-20.0 * p)
            thud = math.sin(2 * math.pi * 180 * t) * math.exp(-14.0 * p)
            sample = ping * 0.28 + thud * 0.22
        elif kind == "spark":
            freq = 900 + 800 * p
            envelope = math.sin(math.pi * p) * 0.32
            sample = math.sin(2 * math.pi * freq * t) * envelope
        else:
            freq = 260 + 620 * p
            envelope = math.sin(math.pi * p) * 0.28
            sample = math.sin(2 * math.pi * freq * t) * envelope
            sample += (rng.random() * 2 - 1) * 0.035 * envelope
        value = int(clamp(sample, -1.0, 1.0) * 32767)
        frames.extend(value.to_bytes(2, "little", signed=True))
        frames.extend(value.to_bytes(2, "little", signed=True))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(frames))
    return path


def sfx_kind_for_scene(scene: StoryScene) -> str:
    explicit = normalize_sfx_kind(scene.sfx_type or "auto")
    if explicit in {"none", "off", "silent"}:
        return "none"
    if explicit in {"whoosh", "hit", "spark", "boom", "thunder", "drop"}:
        return explicit
    text = f"{scene.camera} {scene.emotion}".lower()
    if "dramatic" in text or "reveal" in text or "shocked" in text or "angry" in text:
        return "hit"
    if "happy" in text or "calm" in text:
        return "spark"
    return "whoosh"


def _beat_sfx_triggers(
    scene: StoryScene,
    beat_specs: list[dict[str, object]],
    duration: float,
    run_dir: Path,
) -> list[dict[str, object]]:
    if not beat_specs:
        return []

    emotion_tone = str(getattr(scene, "emotion_tone", "") or scene.emotion or "").strip().lower()
    intense_scene = emotion_tone in {"anger", "fear", "tension", "surprise"}
    triggers: list[dict[str, object]] = []
    boundary_cursor = 0.0
    boundary_floor = 0.35
    boundary_ceiling = max(0.4, float(duration) - 0.18)
    min_gap_ms = 800

    for index, beat in enumerate(beat_specs[:-1], start=1):
        boundary_cursor += float(beat.get("duration") or 0.0)
        if boundary_cursor <= boundary_floor or boundary_cursor >= boundary_ceiling:
            continue

        beat_label = str(beat.get("beat_type") or beat.get("label") or "").strip().upper()
        if beat_label == "REVERSAL":
            kind = "hit"
            gain_db = -18.0
            sfx_duration = 0.30
            offset_ms = -30
        elif beat_label == "FINALE":
            kind = "whoosh"
            gain_db = -20.0
            sfx_duration = 0.30
            offset_ms = -50
        elif beat_label == "OPENING":
            kind = "whoosh"
            gain_db = -24.0
            sfx_duration = 0.22
            offset_ms = -40
        else:
            kind = "hit" if intense_scene else "whoosh"
            gain_db = -20.0 if kind == "hit" else -24.0
            sfx_duration = 0.28 if kind == "hit" else 0.24
            offset_ms = -30

        if intense_scene and beat_label != "REVERSAL":
            gain_db -= 3.0

        delay_ms = max(0, int(boundary_cursor * 1000) + offset_ms)
        if triggers:
            prev_delay = int(triggers[-1].get("delay_ms") or 0)
            prev_gain = float(triggers[-1].get("gain_db") or -120.0)
            if delay_ms - prev_delay < min_gap_ms:
                if gain_db <= prev_gain:
                    continue
                triggers.pop()

        sfx_path = write_tone_sfx(
            run_dir / f"scene_{scene.scene:02}_sfx_beatcut_{index}.wav",
            kind,
            sfx_duration,
        )
        triggers.append(
            {
                "path": sfx_path,
                "delay_ms": delay_ms,
                "volume": db_to_linear(gain_db),
                "gain_db": gain_db,
            }
        )

    return triggers


def scene_sfx_triggers(
    scene: StoryScene, run_dir: Path, duration: float, project_root: Path | None = None
) -> list[dict[str, object]]:
    from scripts.run_workflow import build_scene_beats

    manifest = audio_manifest_dict(scene)
    raw_triggers: list[object] = []
    if isinstance(manifest.get("sfx_triggers"), list):
        raw_triggers.extend(manifest["sfx_triggers"])
    if isinstance(manifest.get("sfx_trigger"), dict):
        raw_triggers.append(manifest["sfx_trigger"])

    triggers: list[dict[str, object]] = []
    for item in raw_triggers:
        if not isinstance(item, dict):
            continue
        file_value = item.get("file") or item.get("path") or item.get("style") or item.get("name")
        sfx_path = resolve_audio_asset("sfx", file_value, project_root=project_root)
        generated_kind = normalize_sfx_kind(file_value)
        if sfx_path is None and generated_kind in {
            "whoosh",
            "hit",
            "spark",
            "boom",
            "thunder",
            "drop",
        }:
            sfx_path = write_tone_sfx(
                run_dir / f"scene_{scene.scene:02}_sfx_{generated_kind}_{len(triggers) + 1}.wav",
                generated_kind,
                0.42 if generated_kind in {"boom", "thunder"} else 0.28,
            )
        if sfx_path is None:
            continue
        timestamp_ms = _coerce_int(item.get("timestamp_ms"), 0, 0, int(max(0.0, duration) * 1000))
        volume = _coerce_float(item.get("volume"), 0.65, 0.0, 2.0)
        triggers.append(
            {"path": sfx_path, "delay_ms": timestamp_ms, "volume": volume, "source": "manifest"}
        )

    spoken_text = split_dialogue_speaker(scene.dialogue)[1]
    beat_specs = build_scene_beats(scene, duration, spoken_text)
    for trigger in _beat_sfx_triggers(scene, beat_specs, duration, run_dir):
        trigger["source"] = "auto_beat"
        triggers.append(trigger)

    beat_kind = sfx_kind_for_scene(scene)
    if beat_kind != "none":
        start_sfx = write_tone_sfx(
            run_dir / f"scene_{scene.scene:02}_sfx_start.wav", "whoosh", 0.26
        )
        beat_sfx = write_tone_sfx(run_dir / f"scene_{scene.scene:02}_sfx_beat.wav", beat_kind, 0.34)
        beat_delay_ms = int(
            max(400, min(float(duration) * 1000 - 360, float(duration) * 1000 * 0.66))
        )
        triggers.append({"path": start_sfx, "delay_ms": 0, "volume": 0.22, "source": "auto_scene"})
        triggers.append(
            {"path": beat_sfx, "delay_ms": beat_delay_ms, "volume": 0.18, "source": "auto_scene"}
        )

    ranked_sources = {"manifest": 0, "auto_beat": 1, "auto_scene": 2}
    triggers.sort(
        key=lambda item: (
            int(item.get("delay_ms") or 0),
            ranked_sources.get(str(item.get("source") or ""), 99),
            -float(item.get("volume") or 0.0),
        )
    )

    deduped: list[dict[str, object]] = []
    for trigger in triggers:
        if not deduped:
            deduped.append(trigger)
            continue
        current_delay = int(trigger.get("delay_ms") or 0)
        prev_delay = int(deduped[-1].get("delay_ms") or 0)
        if current_delay - prev_delay < 100:
            current_rank = ranked_sources.get(str(trigger.get("source") or ""), 99)
            prev_rank = ranked_sources.get(str(deduped[-1].get("source") or ""), 99)
            current_volume = float(trigger.get("volume") or 0.0)
            prev_volume = float(deduped[-1].get("volume") or 0.0)
            if current_rank < prev_rank or (
                current_rank == prev_rank and current_volume > prev_volume
            ):
                deduped[-1] = trigger
            continue
        deduped.append(trigger)

    return deduped[:12]


def scene_should_screen_shake(scene: StoryScene) -> bool:
    tokens = f"{scene.sfx_type} {scene.camera} {scene.emotion}".lower()
    manifest = audio_manifest_dict(scene)
    for key in ("sfx_trigger", "sfx_triggers"):
        value = manifest.get(key)
        if isinstance(value, dict):
            tokens += " " + " ".join(str(item or "") for item in value.values()).lower()
        elif isinstance(value, list):
            tokens += " " + " ".join(
                " ".join(str(item_value or "") for item_value in item.values()).lower()
                for item in value
                if isinstance(item, dict)
            )
    return any(
        token in tokens
        for token in (
            "hit",
            "impact",
            "slap",
            "punch",
            "thunder",
            "boom",
            "explosion",
            "击",
            "打",
            "雷",
            "巴掌",
            "轰",
            "拍",
            "巨响",
        )
    )


def mix_scene_sfx(
    ffmpeg: str,
    voice_path: Path,
    scene: StoryScene,
    run_dir: Path,
    duration: float,
    project_root: Path | None = None,
) -> Path:
    if not voice_path.exists():
        return voice_path
    scene_id = f"{scene.scene:02}"
    triggers = scene_sfx_triggers(scene, run_dir, duration, project_root=project_root)
    if not triggers:
        return voice_path
    out_path = run_dir / f"scene_{scene_id}_voice_sfx.wav"
    filter_parts = ["[0:a]aformat=sample_rates=48000:channel_layouts=stereo[voice]"]
    mix_inputs = ["[voice]"]
    for index, trigger in enumerate(triggers, start=1):
        delay_ms = int(trigger.get("delay_ms") or 0)
        gain_db = trigger.get("gain_db")
        if gain_db not in (None, ""):
            volume = db_to_linear(_coerce_float(gain_db, 0.0, -60.0, 12.0))
        else:
            volume = float(trigger.get("volume") or 0.65)
        filter_parts.append(
            f"[{index}:a]volume={volume:.4f},adelay={delay_ms}|{delay_ms},aformat=sample_rates=48000:channel_layouts=stereo[s{index}]"
        )
        mix_inputs.append(f"[s{index}]")
    filter_parts.append(
        "".join(mix_inputs)
        + f"amix=inputs={len(mix_inputs)}:duration=first:normalize=0,alimiter=limit=0.96[mixed]"
    )
    filter_complex = ";".join(filter_parts)
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(voice_path),
    ]
    for trigger in triggers:
        cmd.extend(["-i", str(trigger["path"])])
    cmd.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            "[mixed]",
            "-c:a",
            "pcm_s16le",
            str(out_path),
        ]
    )
    try:
        run_guarded(
            cmd,
            cwd=run_dir,
            timeout=DEFAULT_SUBPROCESS_TIMEOUTS["ffmpeg_audio"],
            stage="ffmpeg_mix_sfx",
        )
    except Exception as exc:
        print(f"[audio] SFX mix failed for scene {scene_id}: {exc}")
        return voice_path
    return out_path


def apply_scene_grade(ffmpeg: str, input_path: Path, out_path: Path, scene: StoryScene) -> Path:
    strength = clamp(float(scene.camera_intensity or 1.0), 0.7, 1.8)
    contrast = 1.03 + 0.03 * strength
    saturation = 1.05 + 0.05 * strength
    brightness = 0.004 * (strength - 1.0)
    sharpness = 0.55 + 0.18 * strength
    vignette = max(8.0, 14.0 - 2.0 * strength)
    filter_chain = ",".join(
        [
            "scale=1080:1920:flags=lanczos",
            f"eq=contrast={contrast:.3f}:brightness={brightness:.3f}:saturation={saturation:.3f}:gamma=1.00",
            f"unsharp=5:5:{sharpness:.3f}:5:5:0.000",
            f"vignette=PI/{vignette:.3f}",
            "format=yuv420p",
        ]
    )
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(input_path),
        "-vf",
        filter_chain,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-c:a",
        "copy",
        str(out_path),
    ]
    run_guarded(
        cmd,
        cwd=out_path.parent,
        timeout=DEFAULT_SUBPROCESS_TIMEOUTS["ffmpeg_render"],
        stage="ffmpeg_apply_grade",
    )
    return out_path
