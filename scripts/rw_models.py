from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scripts.rw_config import DEFAULT_CROP_BOX


# ---------------------------------------------------------------------------
# Grouped view dataclasses (read-only snapshots of related StoryScene fields)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VoiceConfig:
    """Read-only view of voice/TTS fields on StoryScene."""

    speaker: str
    profile: str
    engine: str
    id: str
    reference_audio_path: str
    reference_text: str
    emotion: str
    rate: float
    pitch: float
    volume: float


@dataclass(frozen=True)
class AudioConfig:
    """Read-only view of audio/SFX/subtitle fields on StoryScene."""

    rhythm_preset: str
    sfx_type: str
    manifest: dict[str, object]
    subtitle_preset: str


@dataclass(frozen=True)
class CameraConfig:
    """Read-only view of camera motion fields on StoryScene."""

    movement: str
    intensity: float
    speed: float


@dataclass(frozen=True)
class EpisodePacing:
    """Read-only view of episode pacing fields on StoryScene."""

    rhythm: str
    phase: str
    phase_index: int
    phase_total: int


@dataclass(frozen=True)
class CharacterReferenceConfig:
    """Read-only view of character reference fields on StoryScene."""

    descriptions: str
    references: list[dict]
    primary_image_path: str
    primary_image_abs_path: str
    primary_meta: dict[str, Any] | None
    consistency_meta: dict[str, Any] | None


@dataclass(frozen=True)
class DirectorConfig:
    """Read-only view of director interpretation fields on StoryScene."""

    emotion_tone: str
    scene_intent: str
    pacing: str
    subject_focus: str
    meta: dict[str, Any] | None


@dataclass(frozen=True)
class ProductionConfig:
    """Read-only view of production bible / prompt compilation fields."""

    bible: dict[str, Any]
    temporal_spec: dict[str, Any]
    character_prompt: str
    negative_prompt: str


@dataclass(frozen=True)
class ValidationState:
    """Read-only view of validation state fields on StoryScene."""

    failed: bool
    error_message: str
    raw_llm_output: dict[str, Any]


# ---------------------------------------------------------------------------
# StoryScene — 50 fields organized into logical groups via section comments
# and accessible as grouped views via read-only properties.
# ---------------------------------------------------------------------------


@dataclass
class StoryScene:
    # --- Core scene data (required) ---
    scene: int
    duration: float
    title: str
    visual: str
    dialogue: str
    camera: str
    emotion: str
    characters: list[str]
    bg_color: str
    accent_color: str

    # --- Voice/TTS ---
    speaker: str = ""
    voice_profile: str = ""
    voice_engine: str = ""
    voice_id: str = ""
    reference_audio_path: str = ""
    reference_text: str = ""
    voice_emotion: str = ""
    voice_rate: float = 1.0
    voice_pitch: float = 0.0
    voice_volume: float = 1.0

    # --- Audio / SFX / Subtitle ---
    rhythm_preset: str = "balanced"
    sfx_type: str = "auto"
    audio_manifest: dict[str, object] = field(default_factory=dict)
    subtitle_preset: str = "standard"

    # --- Camera motion ---
    camera_intensity: float = 1.0
    camera_speed: float = 1.0

    # --- Episode pacing ---
    episode_rhythm: str = "classic_four_act"
    episode_phase: str = "setup"
    episode_phase_index: int = 1
    episode_phase_total: int = 4

    # --- Visual framing ---
    crop_box: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_CROP_BOX))

    # --- Character references ---
    character_descriptions: str = ""
    character_references: list[dict] = field(default_factory=list)
    primary_reference_image_path: str = ""
    primary_reference_image_abs_path: str = ""
    primary_reference_meta: dict[str, Any] | None = None
    consistency_meta: dict[str, Any] | None = None

    # --- Director interpretation ---
    camera_movement: str = ""
    emotion_tone: str = ""
    scene_intent: str = ""
    pacing: str = ""
    subject_focus: str = ""
    director_meta: dict[str, Any] | None = None

    # --- Production ---
    production_bible: dict[str, Any] = field(default_factory=dict)
    temporal_spec: dict[str, Any] = field(default_factory=dict)
    character_prompt_compilation: str = ""
    negative_prompt_compilation: str = ""

    # --- Validation state ---
    validation_failed: bool = False
    error_message: str = ""
    raw_llm_output: dict[str, Any] = field(default_factory=dict)

    # --- Grouped read-only views ---

    @property
    def voice_config(self) -> VoiceConfig:
        """Snapshot of voice/TTS fields. Mutations to the returned object do not
        affect the underlying scene — update the flat fields directly."""
        return VoiceConfig(
            speaker=self.speaker,
            profile=self.voice_profile,
            engine=self.voice_engine,
            id=self.voice_id,
            reference_audio_path=self.reference_audio_path,
            reference_text=self.reference_text,
            emotion=self.voice_emotion,
            rate=self.voice_rate,
            pitch=self.voice_pitch,
            volume=self.voice_volume,
        )

    @property
    def audio_config(self) -> AudioConfig:
        """Snapshot of audio/SFX/subtitle fields."""
        return AudioConfig(
            rhythm_preset=self.rhythm_preset,
            sfx_type=self.sfx_type,
            manifest=self.audio_manifest,
            subtitle_preset=self.subtitle_preset,
        )

    @property
    def camera_config(self) -> CameraConfig:
        """Snapshot of camera motion fields."""
        return CameraConfig(
            movement=self.camera_movement,
            intensity=self.camera_intensity,
            speed=self.camera_speed,
        )

    @property
    def episode_pacing(self) -> EpisodePacing:
        """Snapshot of episode pacing fields."""
        return EpisodePacing(
            rhythm=self.episode_rhythm,
            phase=self.episode_phase,
            phase_index=self.episode_phase_index,
            phase_total=self.episode_phase_total,
        )

    @property
    def character_reference_config(self) -> CharacterReferenceConfig:
        """Snapshot of character reference fields."""
        return CharacterReferenceConfig(
            descriptions=self.character_descriptions,
            references=self.character_references,
            primary_image_path=self.primary_reference_image_path,
            primary_image_abs_path=self.primary_reference_image_abs_path,
            primary_meta=self.primary_reference_meta,
            consistency_meta=self.consistency_meta,
        )

    @property
    def director_config(self) -> DirectorConfig:
        """Snapshot of director interpretation fields."""
        return DirectorConfig(
            emotion_tone=self.emotion_tone,
            scene_intent=self.scene_intent,
            pacing=self.pacing,
            subject_focus=self.subject_focus,
            meta=self.director_meta,
        )

    @property
    def production_config(self) -> ProductionConfig:
        """Snapshot of production bible / prompt compilation fields."""
        return ProductionConfig(
            bible=self.production_bible,
            temporal_spec=self.temporal_spec,
            character_prompt=self.character_prompt_compilation,
            negative_prompt=self.negative_prompt_compilation,
        )

    @property
    def validation_state(self) -> ValidationState:
        """Snapshot of validation state fields."""
        return ValidationState(
            failed=self.validation_failed,
            error_message=self.error_message,
            raw_llm_output=self.raw_llm_output,
        )

    def __post_init__(self) -> None:
        """Validate cross-field consistency after construction."""
        if self.scene < 1:
            raise ValueError(f"Scene number must be >= 1, got {self.scene}")
        if self.duration < 0:
            raise ValueError(f"Duration must be non-negative, got {self.duration}")
        if not 0.0 <= self.voice_rate:
            raise ValueError(f"voice_rate must be >= 0.0, got {self.voice_rate}")
        if self.voice_intensity_out_of_range():
            raise ValueError(
                f"voice_volume must be >= 0.0, got {self.voice_volume}"
            )
        if self.episode_phase_total < 1:
            raise ValueError(
                f"episode_phase_total must be >= 1, got {self.episode_phase_total}"
            )
        if not 1 <= self.episode_phase_index <= self.episode_phase_total:
            raise ValueError(
                f"episode_phase_index {self.episode_phase_index} out of range "
                f"[1, {self.episode_phase_total}]"
            )

    def voice_intensity_out_of_range(self) -> bool:
        """Check voice_volume is non-negative."""
        return self.voice_volume < 0.0


class SceneValidationError(ValueError):
    def __init__(self, reason: str, raw: dict[str, Any], field: str | None = None):
        super().__init__(reason)
        self.reason = reason
        self.raw = raw
        self.field = field

    def to_error_message(self) -> str:
        if self.field:
            return f"[{self.field}] {self.reason}"
        return self.reason
