"""Character-related logic: cards, references, prompts, and voice inheritance."""
from __future__ import annotations

import base64
import binascii
import re
import shutil
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat, UnidentifiedImageError

from scripts.face_crop import preprocess_reference_image
from scripts.run_workflow import StoryScene

from backend.project_models import (
    atomic_write_json,
    default_character_meta,
    default_voice_config,
    ensure_project_dirs,
    load_json,
    normalize_character_meta,
    project_dir,
    project_relative_file_exists,
    workspace_url,
    WORKSPACE,
)


# ─── Voice auto-assignment ────────────────────────────────────────────────────
# Profiles are selected based on DEFAULT_VOICE_PROVIDER in .env:
#   - "cosyvoice" → OmniVoice presets (voice_id = preset name on remote GPU)
#   - "edge"      → Edge TTS neural voices (fallback)

import os as _os

_VOICE_PROVIDER = (_os.environ.get("DEFAULT_VOICE_PROVIDER") or "edge").strip().lower()

# OmniVoice presets (matches remote API /health → voice_designs)
_OMNIVOICE_PROFILES = {
    "male_protagonist": {"voice_id": "male_protagonist", "voice_rate": 1.0, "voice_pitch": 0.0, "voice_volume": 1.0},
    "male_cold": {"voice_id": "male_cold", "voice_rate": 1.0, "voice_pitch": 0.0, "voice_volume": 1.0},
    "male_villain": {"voice_id": "male_villain", "voice_rate": 1.0, "voice_pitch": 0.0, "voice_volume": 1.0},
    "male_bully": {"voice_id": "male_bully", "voice_rate": 1.0, "voice_pitch": 0.0, "voice_volume": 1.0},
    "male_young": {"voice_id": "male_young", "voice_rate": 1.0, "voice_pitch": 0.0, "voice_volume": 1.0},
    "male_narrator": {"voice_id": "narrator", "voice_rate": 1.0, "voice_pitch": 0.0, "voice_volume": 1.0},
    # Female voices
    "female_protagonist": {"voice_id": "female_protagonist", "voice_rate": 1.0, "voice_pitch": 0.0, "voice_volume": 1.0},
    "female_cold": {"voice_id": "male_cold", "voice_rate": 1.0, "voice_pitch": 0.0, "voice_volume": 1.0},
    "female_gentle": {"voice_id": "female_protagonist", "voice_rate": 0.92, "voice_pitch": 0.0, "voice_volume": 0.9},
}

# Edge TTS fallback profiles
_EDGE_TTS_PROFILES = {
    "male_protagonist": {"voice_id": "zh-CN-YunxiNeural", "voice_rate": 0.95, "voice_pitch": -2.0, "voice_volume": 1.0},
    "male_cold": {"voice_id": "zh-CN-YunxiNeural", "voice_rate": 0.85, "voice_pitch": -3.0, "voice_volume": 0.95},
    "male_villain": {"voice_id": "zh-CN-YunyangNeural", "voice_rate": 0.88, "voice_pitch": -1.0, "voice_volume": 1.0},
    "male_bully": {"voice_id": "zh-CN-YunjianNeural", "voice_rate": 1.1, "voice_pitch": 2.0, "voice_volume": 1.1},
    "male_young": {"voice_id": "zh-CN-YunxiaNeural", "voice_rate": 1.0, "voice_pitch": 0.0, "voice_volume": 1.0},
    "male_narrator": {"voice_id": "zh-CN-YunyangNeural", "voice_rate": 0.92, "voice_pitch": 0.0, "voice_volume": 1.0},
    "female_protagonist": {"voice_id": "zh-CN-XiaoxiaoNeural", "voice_rate": 0.95, "voice_pitch": 0.0, "voice_volume": 1.0},
    "female_cold": {"voice_id": "zh-CN-XiaoyiNeural", "voice_rate": 0.9, "voice_pitch": -1.0, "voice_volume": 0.95},
    "female_gentle": {"voice_id": "zh-CN-XiaoxiaoNeural", "voice_rate": 0.9, "voice_pitch": 1.0, "voice_volume": 0.9},
}

VOICE_PROFILES = _OMNIVOICE_PROFILES if _VOICE_PROVIDER == "cosyvoice" else _EDGE_TTS_PROFILES

# Keywords to detect character personality for voice assignment
_PERSONALITY_KEYWORDS = {
    "male_cold": ["冷酷", "冷漠", "冰冷", "寡言", "沉默", "教主", "魔教", "天魔", "重生"],
    "male_villain": ["阴险", "奸诈", "背叛", "叛徒", "护法", "阴暗"],
    "male_bully": ["嚣张", "霸道", "欺负", "跋扈", "粗暴", "师兄", "保护费"],
    "male_young": ["少年", "年轻", "废柴", "杂役", "跟班", "小弟"],
    "female_protagonist": ["女主", "坚强", "温柔", "美丽"],
    "female_cold": ["冷艳", "高冷", "女王"],
}


def auto_assign_voice(character: dict[str, Any]) -> dict[str, Any]:
    """Auto-assign voice settings based on character traits if not already set."""
    if character.get("voice_id"):
        return character  # Already has explicit voice

    name = str(character.get("name") or "").strip()
    description = str(character.get("description") or character.get("summary") or "").strip()
    gender = str(character.get("meta", {}).get("gender") or character.get("gender") or "").strip()
    personality = str(character.get("personality") or "").strip()
    combined_text = f"{name} {description} {personality}".lower()

    # Determine gender
    is_female = any(kw in combined_text for kw in ["女", "female", "她", "姐", "妹"])
    if gender in ("女", "female", "Female", "F"):
        is_female = True

    # Match personality keywords
    best_profile = "male_protagonist" if not is_female else "female_protagonist"
    for profile_key, keywords in _PERSONALITY_KEYWORDS.items():
        if any(kw in combined_text for kw in keywords):
            if is_female and profile_key.startswith("female"):
                best_profile = profile_key
                break
            elif not is_female and profile_key.startswith("male"):
                best_profile = profile_key
                break

    # Apply voice settings
    voice_settings = VOICE_PROFILES.get(best_profile, VOICE_PROFILES["male_protagonist"])
    for key, value in voice_settings.items():
        if character.get(key) in (None, "", 0, 0.0):
            character[key] = value

    return character


def character_dir(project_id: str) -> Path:
    return project_dir(project_id) / "characters"


def character_card_path(project_id: str, character: dict[str, Any] | str) -> Path:
    if isinstance(character, dict):
        char_id = str(character.get("char_id") or "").strip()
        if not char_id:
            char_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(character.get("name") or "character")).strip("_") or "character"
    else:
        char_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(character or "character")).strip("_") or "character"
    return character_dir(project_id) / f"{char_id}.json"


def _normalized_name(value: object) -> str:
    return str(value or "").strip().lower()


def normalize_character_card(character: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(character)
    merged["char_id"] = str(merged.get("char_id") or "").strip()
    merged["name"] = str(merged.get("name") or "").strip()
    merged["meta"] = normalize_character_meta(merged.get("meta"))
    merged["appearance_core"] = str(merged.get("appearance_core") or "").strip()
    merged["clothing_style"] = str(merged.get("clothing_style") or "").strip()
    merged["negative_constraints"] = str(merged.get("negative_constraints") or "").strip()
    merged["immutable_features"] = str(merged.get("immutable_features") or "").strip()
    merged["description"] = str(merged.get("description") or "").strip()
    merged["summary"] = str(merged.get("summary") or "").strip()
    merged["voice_profile"] = str(merged.get("voice_profile") or "").strip()
    merged["voice_engine"] = str(merged.get("voice_engine") or "").strip()
    merged["voice_id"] = str(merged.get("voice_id") or "").strip()
    merged["reference_audio_path"] = str(merged.get("reference_audio_path") or "").strip()
    merged["reference_audio_url"] = str(merged.get("reference_audio_url") or "").strip()
    merged["reference_text"] = str(merged.get("reference_text") or "").strip()
    merged["emotion"] = str(merged.get("emotion") or "").strip()
    merged["suggested_voice_engine"] = str(merged.get("suggested_voice_engine") or _VOICE_PROVIDER or "edge").strip() or "edge"
    merged["reference_image_path"] = str(merged.get("reference_image_path") or "").strip()
    merged["reference_image_url"] = str(merged.get("reference_image_url") or "").strip()
    merged["primary_reference_image_path"] = str(merged.get("primary_reference_image_path") or "").strip()
    merged["primary_reference_image_url"] = str(merged.get("primary_reference_image_url") or "").strip()
    merged["reference_original_path"] = str(merged.get("reference_original_path") or "").strip()
    merged["reference_original_url"] = str(merged.get("reference_original_url") or "").strip()
    merged["reference_meta"] = deepcopy(merged.get("reference_meta") if isinstance(merged.get("reference_meta"), dict) else {})
    return merged


def load_character_card_files(project_id: str) -> dict[str, dict[str, Any]]:
    cards: dict[str, dict[str, Any]] = {}
    base = character_dir(project_id)
    if not base.exists():
        return cards
    for path in sorted(base.glob("*.json")):
        try:
            payload = load_json(path)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        payload = normalize_character_card(payload)
        char_id = payload.get("char_id") or path.stem
        name = payload.get("name") or ""
        if char_id:
            cards[str(char_id)] = payload
        if name:
            cards[_normalized_name(name)] = payload
    return cards


def sync_character_card_files(project: dict[str, Any]) -> None:
    project_id = str(project.get("project_id") or "")
    if not project_id:
        return
    ensure_project_dirs(project_id)
    for character in project.get("characters", []):
        if not isinstance(character, dict):
            continue
        normalized = normalize_character_card(character)
        path = character_card_path(project_id, normalized)
        atomic_write_json(path, normalized)


def hydrate_character_cards(project: dict[str, Any]) -> dict[str, Any]:
    project_id = str(project.get("project_id") or "")
    if not project_id:
        return project
    cards = load_character_card_files(project_id)
    if not cards:
        return project
    for character in project.get("characters", []):
        if not isinstance(character, dict):
            continue
        card = cards.get(str(character.get("char_id") or "")) or cards.get(_normalized_name(character.get("name")))
        if not isinstance(card, dict):
            continue
        for key in (
            "meta",
            "appearance_core",
            "clothing_style",
            "negative_constraints",
            "description",
            "summary",
            "voice_profile",
            "voice_engine",
            "voice_id",
            "reference_audio_path",
            "reference_audio_url",
            "reference_text",
            "emotion",
            "voice_rate",
            "voice_pitch",
            "voice_volume",
            "suggested_voice_engine",
            "reference_image_path",
            "reference_image_url",
            "reference_original_path",
            "reference_original_url",
            "reference_meta",
        ):
            value = card.get(key)
            if value not in (None, ""):
                character[key] = deepcopy(value)
    return project


def _role_lookup(roles: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for role in roles or []:
        if not isinstance(role, dict):
            continue
        name = str(role.get("name") or "").strip()
        if not name:
            continue
        lookup[_normalized_name(name)] = role
    return lookup


_PLACEHOLDER_CHARACTER_NAMES = {
    "主角",
    "主人公",
    "角色",
    "人物",
    "旁白",
    "解说",
    "男主",
    "女主",
    "反派",
}
_PLACEHOLDER_CHARACTER_NAMES_NORMALIZED = {str(item).strip().lower() for item in _PLACEHOLDER_CHARACTER_NAMES}


def _is_placeholder_character(name: str, role_map: dict[str, dict[str, Any]]) -> bool:
    normalized = _normalized_name(name)
    return normalized in _PLACEHOLDER_CHARACTER_NAMES_NORMALIZED and normalized not in role_map


def build_initial_characters(scenes: list[StoryScene], roles: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    role_map = _role_lookup(roles)
    index = 1
    for scene in scenes:
        for character in scene.characters:
            name = character.strip()
            if not name or name in seen:
                continue
            if _is_placeholder_character(name, role_map):
                continue
            role = role_map.get(_normalized_name(name), {})
            voice_rate = role.get("voice_rate") if role.get("voice_rate") not in (None, "") else scene.voice_rate
            voice_pitch = role.get("voice_pitch") if role.get("voice_pitch") not in (None, "") else scene.voice_pitch
            voice_volume = role.get("voice_volume") if role.get("voice_volume") not in (None, "") else scene.voice_volume
            seen[name] = {
                "char_id": f"c_{index:03d}",
                "name": name,
                **default_voice_config(),
                "meta": normalize_character_meta(role.get("meta") if isinstance(role.get("meta"), dict) else {}),
                "appearance_core": str(role.get("appearance_core") or ""),
                "clothing_style": str(role.get("clothing_style") or ""),
                "negative_constraints": str(role.get("negative_constraints") or ""),
                "immutable_features": str(role.get("immutable_features") or ""),
                "voice_profile": str(role.get("voice_profile") or scene.voice_profile or ""),
                "voice_engine": str(role.get("suggested_voice_engine") or scene.voice_engine or _VOICE_PROVIDER or ""),
                "voice_id": str(role.get("voice_id") or scene.voice_id or ""),
                "reference_audio_path": str(role.get("reference_audio_path") or scene.reference_audio_path or ""),
                "reference_audio_url": "",
                "reference_text": str(role.get("reference_text") or scene.reference_text or ""),
                "emotion": str(role.get("emotion") or scene.emotion or ""),
                "voice_rate": float(voice_rate if voice_rate not in (None, "") else 1.0),
                "voice_pitch": float(voice_pitch if voice_pitch not in (None, "") else 0.0),
                "voice_volume": float(voice_volume if voice_volume not in (None, "") else 1.0),
                "description": str(role.get("summary") or ""),
                "first_scene": int(role.get("first_scene") or scene.scene),
                "importance": float(role.get("importance") or 0),
                "summary": str(role.get("summary") or ""),
                "suggested_voice_engine": str(role.get("suggested_voice_engine") or _VOICE_PROVIDER or "edge"),
                "reference_image_path": "",
                "reference_image_url": "",
                "primary_reference_image_path": "",
                "primary_reference_image_url": "",
                "reference_original_path": "",
                "reference_original_url": "",
                "reference_meta": {},
            }
            index += 1
    # Auto-assign voice settings based on character traits
    return [auto_assign_voice(char) for char in seen.values()]


def remove_placeholder_scene_characters(scenes: list[StoryScene], roles: list[dict[str, Any]] | None = None) -> list[StoryScene]:
    role_map = _role_lookup(roles)
    if not role_map:
        return scenes
    for scene in scenes:
        scene.characters = [name for name in scene.characters if not _is_placeholder_character(name, role_map)]
        if scene.speaker and _is_placeholder_character(scene.speaker, role_map):
            scene.speaker = ""
    return scenes


def merge_character_configs(
    existing: list[dict[str, Any]],
    scenes: list[StoryScene],
    roles: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    fresh = build_initial_characters(scenes, roles=roles)
    if not fresh:
        return deepcopy(existing)

    existing_map: dict[str, dict[str, Any]] = {}
    for character in existing:
        key = _normalized_name(character.get("name"))
        if key and key not in existing_map:
            existing_map[key] = character

    merged: list[dict[str, Any]] = []
    preserved_keys = {
        "char_id",
        "meta",
        "appearance_core",
        "clothing_style",
        "negative_constraints",
        "description",
        "reference_image_path",
        "reference_image_url",
        "reference_original_path",
        "reference_original_url",
        "reference_meta",
        "voice_id",
        "reference_audio_path",
        "reference_audio_url",
        "reference_text",
        "voice_rate",
        "voice_pitch",
        "voice_volume",
    }
    for character in fresh:
        key = _normalized_name(character.get("name"))
        merged_character = deepcopy(character)
        source = existing_map.get(key)
        if source:
            for field in preserved_keys:
                value = source.get(field)
                if value not in (None, ""):
                    merged_character[field] = deepcopy(value)
        merged.append(merged_character)
    return merged


def _normalized_key(value: object) -> str:
    return str(value or "").strip().lower()


def _voice_source_for_scene(project: dict[str, Any], scene: dict[str, Any]) -> dict[str, Any] | None:
    names = [
        scene.get("speaker"),
        *list(scene.get("characters") or []),
    ]
    characters = project.get("characters", [])
    character_map = {
        _normalized_key(character.get("name")): character
        for character in characters
        if _normalized_key(character.get("name"))
    }
    for name in names:
        match = character_map.get(_normalized_key(name))
        if match:
            return match
    return None


def scene_character_refs(project: dict[str, Any], scene: dict[str, Any]) -> list[dict[str, Any]]:
    project_id = str(project.get("project_id") or "")
    character_map = {
        _normalized_key(character.get("name")): character
        for character in project.get("characters", [])
        if _normalized_key(character.get("name"))
    }

    # Load asset store to enrich character data with visual descriptions
    asset_char_map: dict[str, Any] = {}
    try:
        from backend.assets import load_asset_store, AssetType
        asset_store = load_asset_store(project_id)
        for asset in asset_store.characters:
            asset_key = _normalized_key(asset.name)
            if asset_key:
                asset_char_map[asset_key] = asset
    except Exception:
        pass

    ordered_names: list[object] = []
    speaker = scene.get("speaker")
    if speaker:
        ordered_names.append(speaker)
    ordered_names.extend(list(scene.get("characters") or []))

    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, name in enumerate(ordered_names):
        key = _normalized_key(name)
        if not key or key in seen:
            continue
        character = character_map.get(key)
        if not character:
            continue
        seen.add(key)
        relative_path = str(character.get("reference_image_path") or "").strip()
        abs_path = ""
        url = str(character.get("reference_image_url") or "").strip()
        if relative_path:
            candidate = project_dir(project_id) / relative_path
            if candidate.is_file():
                abs_path = str(candidate.resolve())
                url = workspace_url(project_id, relative_path)

        # Get base values from project characters
        appearance_core = str(character.get("appearance_core") or "").strip()
        clothing_style = str(character.get("clothing_style") or "").strip()
        description = str(character.get("description") or "").strip()
        negative_constraints = str(character.get("negative_constraints") or "").strip()
        meta = deepcopy(character.get("meta") if isinstance(character.get("meta"), dict) else default_character_meta())

        # Enrich from asset store if project character data is sparse
        asset = asset_char_map.get(key)
        if asset is not None:
            if not appearance_core and asset.appearance:
                appearance_core = str(asset.appearance).strip()
            if not clothing_style and asset.visual_prompt:
                # Use visual_prompt as clothing/appearance fallback
                clothing_style = str(asset.visual_prompt).strip()
            if not description and asset.description:
                description = str(asset.description).strip()
            # Enrich meta with gender/age from asset
            if not meta.get("gender") and asset.gender:
                meta["gender"] = str(asset.gender).strip()
            if not meta.get("age_group") and asset.age:
                meta["age_group"] = str(asset.age).strip()
            if not meta.get("age") and asset.age:
                meta["age"] = str(asset.age).strip()

        refs.append(
            {
                "name": str(character.get("name") or name),
                "char_id": str(character.get("char_id") or ""),
                "description": description,
                "summary": str(character.get("summary") or ""),
                "meta": meta,
                "appearance_core": appearance_core,
                "clothing_style": clothing_style,
                "negative_constraints": negative_constraints,
                "reference_meta": deepcopy(character.get("reference_meta") if isinstance(character.get("reference_meta"), dict) else {}),
                "reference_image_path": relative_path,
                "reference_image_abs_path": abs_path,
                "reference_image_url": url,
                "role": "primary" if not refs else "supporting",
            }
        )
    return refs


def _character_prompt_feature_lines(ref: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Build SDXL-friendly English keyword tags for a character reference.

    Returns (positive_tags, negative_tags) as lists of comma-separated English keywords
    focusing on visual attributes that Stable Diffusion models understand well.
    """
    name = str(ref.get("name") or "").strip()
    meta = ref.get("meta") if isinstance(ref.get("meta"), dict) else {}
    positive: list[str] = []
    negative: list[str] = []

    age = str(meta.get("age") or "").strip()
    gender = str(meta.get("gender") or "").strip()
    appearance = str(ref.get("appearance_core") or "").strip()
    clothing = str(ref.get("clothing_style") or "").strip()
    description = str(ref.get("description") or ref.get("summary") or "").strip()
    negative_constraints = str(ref.get("negative_constraints") or "").strip()

    # Identity anchor: gender + age hint
    identity_parts: list[str] = []
    if gender:
        identity_parts.append(gender)
    if age:
        identity_parts.append(f"{age} years old")
    if identity_parts:
        positive.append(", ".join(identity_parts))

    # Appearance anchor: hair, face, eyes, body type (most important for consistency)
    if appearance:
        positive.append(appearance)

    # Clothing anchor
    if clothing:
        positive.append(clothing)

    # Supplementary description (only visual keywords, skip narrative text)
    if description and not appearance:
        positive.append(description)

    # Negative constraints
    if negative_constraints:
        negative.append(negative_constraints)
    # Standard consistency negatives
    negative.append("inconsistent character design, wrong hair color, wrong eye color, wrong clothing")

    return positive, negative


def compile_character_prompt(scene: dict[str, Any], refs: list[dict[str, Any]]) -> tuple[str, str]:
    """Compile character visual anchors into SDXL-compatible English prompt segments.

    Returns (positive_prompt, negative_prompt) as comma-separated English tags
    suitable for direct injection into Stable Diffusion prompts.
    """
    positive_lines: list[str] = []
    negative_lines: list[str] = []
    seen: set[str] = set()
    char_count = 0

    for ref in refs[:4]:
        key = str(ref.get("char_id") or ref.get("name") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        char_count += 1
        positive, negative = _character_prompt_feature_lines(ref)
        positive_lines.extend(positive)
        negative_lines.extend(negative)

    # Add character count hint for SD composition
    if char_count == 1:
        positive_lines.insert(0, "1girl" if any(
            kw in " ".join(positive_lines).lower()
            for kw in ("female", "girl", "woman", "she")
        ) else "1boy" if any(
            kw in " ".join(positive_lines).lower()
            for kw in ("male", "boy", "man", "he")
        ) else "1person")
    elif char_count == 2:
        positive_lines.insert(0, "2people")
    elif char_count > 2:
        positive_lines.insert(0, f"{char_count}people, multiple characters")

    return ", ".join(line for line in positive_lines if line), ", ".join(line for line in negative_lines if line)


def scene_with_character_context(project: dict[str, Any], scene: dict[str, Any]) -> dict[str, Any]:
    from backend.scene_graph import _scene_graph_payload, build_production_bible, scene_production_bible

    merged = scene_with_inherited_voice(project, scene)
    refs = scene_character_refs(project, merged)
    descriptions = [
        f"{ref['name']}：{ref['description']}"
        for ref in refs
        if str(ref.get("description") or "").strip()
    ]
    primary = next((ref for ref in refs if ref.get("reference_image_abs_path") or ref.get("reference_image_path")), refs[0] if refs else None)
    merged["character_references"] = refs
    merged["character_descriptions"] = "；".join(descriptions)
    positive_prompt, negative_prompt = compile_character_prompt(merged, refs)
    merged["character_prompt_compilation"] = positive_prompt
    merged["negative_prompt_compilation"] = negative_prompt
    merged["visual_prompt_compiled"] = "；".join(
        part for part in [str(merged.get("visual_prompt") or "").strip(), positive_prompt] if part
    )
    if primary:
        merged["primary_reference_image_path"] = str(primary.get("reference_image_path") or "")
        merged["primary_reference_image_abs_path"] = str(primary.get("reference_image_abs_path") or "")
        primary_meta = primary.get("reference_meta") if isinstance(primary.get("reference_meta"), dict) else {}
        merged["primary_reference_meta"] = {
            "crop_method": primary_meta.get("crop_method"),
            "output_size": deepcopy(primary_meta.get("output_size")) if isinstance(primary_meta.get("output_size"), list) else primary_meta.get("output_size"),
            "warnings": list(primary_meta.get("warnings") or []),
        }
    merged["production_bible"] = scene_production_bible(project, merged, refs)
    scene_order = int(merged.get("order") or 1)
    scene_graph = _scene_graph_payload(merged, scene_order, project_id=str(project.get("project_id") or ""))
    merged["temporal_spec"] = {
        "version": 1,
        "kind": "scene_temporal_video_spec",
        "scene": scene_order,
        "title": str(merged.get("title") or "").strip(),
        "duration_seconds": float(merged.get("duration_seconds") or 0.0),
        "camera_track": deepcopy(scene_graph.get("camera_track") or {}),
        "shots": deepcopy(scene_graph.get("shots") or []),
        "continuity_rules": {
            "generate_continuous_video": True,
            "avoid_static_pan_only_motion": True,
            "preserve_character_environment_contact": True,
            "preserve_lighting_direction": True,
            "preserve_scene_geometry": True,
        },
    }
    return merged


def scene_with_inherited_voice(project: dict[str, Any], scene: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(scene)
    source = _voice_source_for_scene(project, scene)
    if not source:
        return merged
    for key in {
        "voice_profile",
        "voice_engine",
        "voice_id",
        "reference_audio_path",
        "reference_text",
        "emotion",
        "voice_rate",
        "voice_pitch",
        "voice_volume",
    }:
        if merged.get(key) in (None, "") and source.get(key) not in (None, ""):
            merged[key] = deepcopy(source[key])
    return merged


def validate_reference_image(path: Path) -> None:
    try:
        with Image.open(path) as image:
            width, height = image.size
            if width < 128 or height < 128:
                raise ValueError("Reference image is too small. Use an image at least 128x128.")
            thumb = image.convert("RGB")
            thumb.thumbnail((96, 96))
            pixels = list(thumb.getdata())
            color_bins = {(r // 32, g // 32, b // 32) for r, g, b in pixels}
            channel_ranges = [max(channel) - min(channel) for channel in zip(*pixels)]
            max_stddev = max(ImageStat.Stat(thumb).stddev)
    except UnidentifiedImageError as exc:
        raise ValueError("Uploaded file is not a readable image.") from exc

    if len(color_bins) < 8 or max(channel_ranges) < 24 or max_stddev < 10:
        raise ValueError("Reference image has too little visual detail. Upload a real character image, not a flat placeholder.")


def write_data_url_image(project_id: str, filename: str, data_url: str) -> Path:
    if "," not in data_url:
        raise ValueError("Invalid data URL")
    header, encoded = data_url.split(",", 1)
    if "base64" not in header:
        raise ValueError("Only base64 data URLs are supported")
    try:
        raw = base64.b64decode(encoded)
    except binascii.Error as exc:
        raise ValueError("Invalid base64 payload") from exc
    suffix = Path(filename or "upload.png").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".png"
    out = project_dir(project_id) / "characters" / f"upload_{uuid.uuid4().hex[:8]}{suffix}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)
    try:
        validate_reference_image(out)
    except ValueError:
        out.unlink(missing_ok=True)
        raise
    return out


def update_character_reference_image(project_id: str, char_index: int, source_path: Path) -> dict[str, Any]:
    """Update a character's reference image. Requires project_lock externally or uses it internally."""
    from backend.project_models import project_lock
    from backend.scene_renderer import _invalidate_character_scenes

    validate_reference_image(source_path)
    with project_lock(project_id):
        from backend.project_runtime import load_project, _save_project_with_project_event
        project = load_project(project_id)
        characters = project.get("characters", [])
        if char_index < 1 or char_index > len(characters):
            raise KeyError(f"Character {char_index} not found")
        character = characters[char_index - 1]
        directory = project_dir(project_id) / "characters" / character["char_id"]
        directory.mkdir(parents=True, exist_ok=True)
        original = directory / "reference_original.png"
        processed = directory / "reference_processed.png"
        if processed.exists():
            processed.unlink()
        if source_path.resolve() != original.resolve():
            shutil.copy2(source_path, original)
        else:
            original = source_path
        result = preprocess_reference_image(original, processed)
        original_relative = str(original.relative_to(project_dir(project_id))).replace("\\", "/")
        character["reference_original_path"] = original_relative
        character["reference_original_url"] = workspace_url(project_id, original_relative)
        if result.get("ok"):
            relative = str(processed.relative_to(project_dir(project_id))).replace("\\", "/")
            character["reference_image_path"] = relative
            character["reference_image_url"] = workspace_url(project_id, relative)
            character["reference_meta"] = {
                "crop_method": result.get("crop_method") or "center_fallback",
                "face_box": result.get("face_box"),
                "crop_box": result.get("crop_box"),
                "output_size": result.get("output_size") or [512, 512],
                "warnings": list(result.get("warnings") or []),
            }
        else:
            character["reference_image_path"] = ""
            character["reference_image_url"] = ""
            character["reference_meta"] = {
                "crop_method": "failed",
                "face_box": None,
                "crop_box": None,
                "output_size": result.get("output_size") or [0, 0],
                "warnings": list(result.get("warnings") or []),
            }
        _invalidate_character_scenes(project, character, ["characters"])
        return _save_project_with_project_event(project)
