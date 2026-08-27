from __future__ import annotations

import re
from pathlib import Path

try:
    import pyttsx3
except ImportError:  # pragma: no cover - optional runtime dependency
    pyttsx3 = None

from backend.config_utils import env_value
from scripts import tts_engines
from scripts.rw_config import DEFAULT_SUBPROCESS_TIMEOUTS, DEFAULT_VOICE_PRESETS, ROOT
from scripts.rw_ffmpeg import concat_timeout, run_guarded
from scripts.rw_models import StoryScene
from scripts.rw_styles import normalize_audio_style, normalize_subtitle_style
from scripts.rw_utils import (
    ensure_parent,
    load_json,
    media_duration,
    wav_duration,
    write_silent_wav,
    write_text,
)


def voice_presets_path() -> Path:
    return Path(env_value("VOICE_PRESETS_PATH", default=str(ROOT / "voice_presets.json")))


def load_voice_presets() -> dict:
    path = voice_presets_path()
    if path.exists():
        try:
            data = load_json(path)
            if isinstance(data, dict):
                return data
        except Exception as exc:
            print(f"[tts] Failed to load voice presets from {path}: {exc}")
    return DEFAULT_VOICE_PRESETS


def split_dialogue_speaker(text: str) -> tuple[str, str]:
    match = re.match(r"^\s*([^：:\n]{1,16})[：:]\s*(.+)$", text.strip(), re.S)
    if not match:
        return "", text.strip()
    return match.group(1).strip(), match.group(2).strip()


def split_dialogue_lines(text: str) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    last_speaker = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        speaker, spoken = split_dialogue_speaker(line)
        if speaker:
            lines.append((speaker, spoken))
            last_speaker = speaker
        elif last_speaker and not line.startswith(("旁白", "解说")):
            lines.append((last_speaker, line))
        else:
            lines.append(("", line))
    return lines


def infer_voice_profile(speaker: str, characters: list[str]) -> str:
    speaker = speaker.strip()
    if not speaker or speaker in {"旁白", "解说"}:
        return "narrator"
    if speaker in {"主持人", "主播", "记者"}:
        return "host"
    if speaker in {"反派", "对手", "老板"} or any(
        token in speaker for token in {"虎", "护法", "魔", "敌", "贼", "恶", "妖"}
    ):
        return "antagonist"
    if any(
        token in speaker
        for token in {"姐", "妹", "她", "女", "娘", "妃", "姬", "嫣", "雪", "月", "晚"}
    ):
        return "female_lead"
    return "male_lead"


def resolve_voice_name(scene: StoryScene) -> tuple[str, str, str]:
    presets = load_voice_presets()
    voice_map = presets.get("voice_map", {})
    if not isinstance(voice_map, dict):
        voice_map = {}
    default_voice = str(presets.get("default", "zh-CN-XiaoxiaoNeural"))

    explicit_voice = (scene.voice_id or "").strip()
    if explicit_voice:
        dialogue_speaker, _ = split_dialogue_speaker(scene.dialogue)
        speaker = (scene.speaker or dialogue_speaker or "旁白").strip()
        profile = (scene.voice_profile or infer_voice_profile(speaker, scene.characters)).strip()
        return speaker, profile, explicit_voice

    dialogue_speaker, _ = split_dialogue_speaker(scene.dialogue)
    speaker = (scene.speaker or dialogue_speaker or "旁白").strip()
    profile = (scene.voice_profile or infer_voice_profile(speaker, scene.characters)).strip()

    for key in (speaker, profile, dialogue_speaker):
        if not key:
            continue
        mapped = voice_map.get(key)
        if mapped:
            return speaker, profile, str(mapped)

    return speaker, profile, default_voice


def resolve_voice_engine(scene: StoryScene, provider: str) -> str:
    engine = tts_engines.normalize_engine_name(scene.voice_engine)
    if engine in {"auto", ""}:
        return tts_engines.normalize_engine_name(provider)
    return engine


def local_tts_engine(
    preferred_voice: str = "", rate_scale: float = 1.0, volume_scale: float = 1.0
) -> pyttsx3.Engine:
    return tts_engines.local_tts_engine(
        preferred_voice, rate_scale=rate_scale, volume_scale=volume_scale
    )


def synthesize_local_tts(
    text: str,
    out_path: Path,
    preferred_voice: str = "",
    rate_scale: float = 1.0,
    volume_scale: float = 1.0,
) -> None:
    tts_engines.synthesize_local_tts(
        text,
        out_path,
        preferred_voice=preferred_voice,
        rate_scale=rate_scale,
        volume_scale=volume_scale,
    )


def synthesize_windows_sapi_tts(
    text: str,
    out_path: Path,
    preferred_voice: str = "",
    rate_scale: float = 1.0,
    volume_scale: float = 1.0,
) -> None:
    tts_engines.synthesize_windows_sapi_tts(
        text,
        out_path,
        preferred_voice=preferred_voice,
        rate_scale=rate_scale,
        volume_scale=volume_scale,
    )


def format_edge_rate(rate: float) -> str:
    return tts_engines.format_edge_rate(rate)


def format_edge_volume(volume: float) -> str:
    return tts_engines.format_edge_volume(volume)


def format_edge_pitch(pitch: float) -> str:
    return tts_engines.format_edge_pitch(pitch)


def synthesize_edge_tts(
    text: str,
    out_path: Path,
    voice: str,
    rate: float = 1.0,
    volume: float = 1.0,
    pitch: float = 0.0,
) -> None:
    tts_engines.synthesize_edge_tts(text, out_path, voice, rate=rate, volume=volume, pitch=pitch)


def convert_audio_to_wav(ffmpeg: str, input_path: Path, out_path: Path) -> Path:
    result = run_guarded(
        [ffmpeg, "-y", "-i", str(input_path), str(out_path)],
        cwd=out_path.parent,
        timeout=DEFAULT_SUBPROCESS_TIMEOUTS["ffmpeg_audio"],
        stage="ffmpeg_audio",
    )
    return out_path


def concat_audio_segments(ffmpeg: str, segments: list[Path], out_path: Path, run_dir: Path) -> Path:
    concat_file = run_dir / f"{out_path.stem}_audio_concat.txt"
    write_text(concat_file, "\n".join(f"file '{segment.name}'" for segment in segments))
    result = run_guarded(
        [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(out_path),
        ],
        cwd=run_dir,
        timeout=concat_timeout(len(segments)),
        stage="ffmpeg_concat_audio",
    )
    return out_path


def synthesize_voice_fragment(
    ffmpeg: str,
    text: str,
    voice: str,
    provider: str,
    out_wav: Path,
    segment_prefix: str,
    voice_id: str = "",
    reference_audio_path: str = "",
    reference_text: str = "",
    emotion: str = "",
    rate_scale: float = 1.0,
    volume_scale: float = 1.0,
    pitch_shift: float = 0.0,
) -> float:
    if not text.strip():
        write_silent_wav(out_wav, 0.4)
        return wav_duration(out_wav)

    for candidate in tts_engines.engine_chain(provider):
        try:
            if candidate == "edge":
                mp3_path = out_wav.with_suffix(".mp3")
                edge_voice = env_value("TTS_EDGE_VOICE", default=voice)
                synthesize_edge_tts(
                    text,
                    mp3_path,
                    edge_voice,
                    rate=rate_scale,
                    volume=volume_scale,
                    pitch=pitch_shift,
                )
                convert_audio_to_wav(ffmpeg, mp3_path, out_wav)
                if mp3_path.exists():
                    mp3_path.unlink()
                return wav_duration(out_wav)
            if candidate == "local":
                synthesize_local_tts(
                    text,
                    out_wav,
                    preferred_voice=voice,
                    rate_scale=rate_scale,
                    volume_scale=volume_scale,
                )
                return wav_duration(out_wav)
            if candidate == "silent":
                write_silent_wav(out_wav, max(0.4, min(2.0, len(text) / 10)))
                return wav_duration(out_wav)
            if tts_engines.is_external_engine(candidate):
                tts_engines.synthesize_external_tts(
                    candidate,
                    text,
                    out_wav,
                    voice,
                    voice_id=voice_id,
                    reference_audio_path=reference_audio_path,
                    reference_text=reference_text,
                    emotion=emotion,
                    rate=rate_scale,
                    pitch=pitch_shift,
                    volume=volume_scale,
                )
                return wav_duration(out_wav)
        except Exception as exc:
            print(f"[tts] {candidate} unavailable for {segment_prefix}, trying next backend: {exc}")

    write_silent_wav(out_wav, max(0.4, min(2.0, len(text) / 10)))
    return wav_duration(out_wav)


def resolve_dialogue_voice(
    scene: StoryScene, speaker: str, spoken_text: str
) -> tuple[str, str, str]:
    segment_scene = StoryScene(
        scene=scene.scene,
        duration=scene.duration,
        title=scene.title,
        visual=scene.visual,
        dialogue=spoken_text,
        camera=scene.camera,
        emotion=scene.emotion,
        characters=scene.characters,
        bg_color=scene.bg_color,
        accent_color=scene.accent_color,
        speaker=speaker,
        voice_profile=infer_voice_profile(speaker, scene.characters),
    )
    return resolve_voice_name(segment_scene)


def render_voice_track(
    ffmpeg: str,
    scene: StoryScene,
    run_dir: Path,
    provider: str,
    write_subtitles: bool = True,
    subtitle_style: dict | None = None,
    audio_style: dict | None = None,
) -> tuple[Path, float]:
    from scripts.rw_audio import normalize_audio_track, write_scene_subtitles

    style = normalize_subtitle_style(subtitle_style)
    audio_settings = normalize_audio_style(audio_style)
    scene_id = f"{scene.scene:02}"
    text = scene.dialogue.strip()
    raw_wav = run_dir / f"scene_{scene_id}_voice_raw.wav"
    voice_wav = run_dir / f"scene_{scene_id}_voice.wav"
    subtitle_path = run_dir / f"scene_{scene_id}_dialogue.srt"
    subtitle_ass_path = run_dir / f"scene_{scene_id}_dialogue.ass"
    effective_provider = resolve_voice_engine(scene, provider)

    if not text:
        write_silent_wav(raw_wav, scene.duration)
        if write_subtitles:
            subtitle_path.write_text("", encoding="utf-8")
            subtitle_ass_path.write_text("", encoding="utf-8")
        normalize_audio_track(ffmpeg, raw_wav, voice_wav, audio_settings)
        return voice_wav, wav_duration(voice_wav)

    dialogue_segments = split_dialogue_lines(text)
    if not dialogue_segments:
        write_silent_wav(raw_wav, scene.duration)
        if write_subtitles:
            subtitle_path.write_text("", encoding="utf-8")
            subtitle_ass_path.write_text("", encoding="utf-8")
        normalize_audio_track(ffmpeg, raw_wav, voice_wav, audio_settings)
        return voice_wav, wav_duration(voice_wav)

    if effective_provider == "silent":
        write_silent_wav(raw_wav, scene.duration)
        if write_subtitles:
            if len(dialogue_segments) == 1:
                fallback_durations = [scene.duration]
            else:
                per_segment = scene.duration / max(1, len(dialogue_segments))
                fallback_durations = [per_segment for _ in dialogue_segments]
            write_scene_subtitles(
                scene_id,
                dialogue_segments,
                fallback_durations,
                subtitle_path,
                style,
                ass_path=subtitle_ass_path,
                emotion_tone=scene.emotion_tone,
                pacing=scene.pacing,
                default_speaker=scene.speaker,
            )
        normalize_audio_track(ffmpeg, raw_wav, voice_wav, audio_settings)
        return voice_wav, wav_duration(voice_wav)

    segment_paths: list[Path] = []
    segment_durations: list[float] = []
    single_segment = len(dialogue_segments) == 1
    for index, (speaker, spoken_text) in enumerate(dialogue_segments, start=1):
        segment_speaker = speaker or scene.speaker or "旁白"
        _, _, voice_name = resolve_dialogue_voice(scene, segment_speaker, spoken_text)
        segment_wav = (
            raw_wav if single_segment else run_dir / f"scene_{scene_id}_voice_{index:02}.wav"
        )
        try:
            duration = synthesize_voice_fragment(
                ffmpeg,
                spoken_text,
                voice_name,
                effective_provider,
                segment_wav,
                f"scene_{scene_id}_{index:02}",
                voice_id=scene.voice_id,
                reference_audio_path=scene.reference_audio_path,
                reference_text=scene.reference_text or spoken_text,
                emotion=scene.voice_emotion or scene.emotion,
                rate_scale=float(scene.voice_rate or 1.0),
                volume_scale=float(scene.voice_volume or 1.0),
                pitch_shift=float(scene.voice_pitch or 0.0),
            )
        except Exception as exc:
            print(f"[tts] Segment synthesis failed for scene {scene_id} line {index}: {exc}")
            write_silent_wav(segment_wav, max(0.4, scene.duration / max(1, len(dialogue_segments))))
            duration = wav_duration(segment_wav)
        segment_durations.append(duration)
        segment_paths.append(segment_wav)

    if not segment_paths:
        write_silent_wav(raw_wav, scene.duration)
        if write_subtitles:
            subtitle_path.write_text("", encoding="utf-8")
            subtitle_ass_path.write_text("", encoding="utf-8")
        normalize_audio_track(ffmpeg, raw_wav, voice_wav, audio_settings)
        return voice_wav, wav_duration(voice_wav)

    if not single_segment:
        concat_audio_segments(ffmpeg, segment_paths, raw_wav, run_dir)
    if write_subtitles:
        write_scene_subtitles(
            scene_id,
            dialogue_segments,
            segment_durations,
            subtitle_path,
            style,
            ass_path=subtitle_ass_path,
            emotion_tone=scene.emotion_tone,
            pacing=scene.pacing,
            default_speaker=scene.speaker,
        )
    normalize_audio_track(ffmpeg, raw_wav, voice_wav, audio_settings)
    return voice_wav, wav_duration(voice_wav)
