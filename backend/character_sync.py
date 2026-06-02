"""Character data synchronization between project.characters and AssetStore.

Problem: Character visual data (gender, appearance, visual_prompt) lives in AssetStore
but project.characters (used by rendering pipeline) has empty fields.

Solution: AssetStore is the authority for visual attributes. This module syncs
AssetStore data INTO project.characters on project load and after asset updates.

Data flow:
  AssetStore (visual authority) ──sync──> project.characters (rendering uses this)
  project.characters (voice/ref authority) ──sync──> AssetStore (display uses this)
"""
from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

logger = logging.getLogger(__name__)


def _normalized_key(value: object) -> str:
    return str(value or "").strip().lower()


def sync_characters_from_assets(project: dict[str, Any], project_id: str) -> bool:
    """Sync visual attributes from AssetStore into project.characters.

    Returns True if any data was updated.
    """
    try:
        from backend.assets import load_asset_store
    except ImportError:
        return False

    try:
        store = load_asset_store(project_id)
    except Exception:
        return False

    if not store.characters:
        return False

    # Build lookup from asset store
    asset_map: dict[str, Any] = {}
    for asset in store.characters:
        key = _normalized_key(asset.name)
        if key:
            asset_map[key] = asset

    characters = project.get("characters", [])
    if not characters:
        return False

    updated = False
    for character in characters:
        if not isinstance(character, dict):
            continue
        key = _normalized_key(character.get("name"))
        asset = asset_map.get(key)
        if asset is None:
            continue

        # Sync visual fields: AssetStore -> project.characters
        # Only overwrite if project field is empty
        visual_syncs = [
            ("appearance_core", asset.appearance),
            ("description", asset.description),
        ]
        for field, asset_value in visual_syncs:
            if not str(character.get(field) or "").strip() and str(asset_value or "").strip():
                character[field] = str(asset_value).strip()
                updated = True

        # Sync meta (gender, age)
        meta = character.get("meta")
        if not isinstance(meta, dict):
            meta = {}
            character["meta"] = meta

        if not str(meta.get("gender") or "").strip() and str(asset.gender or "").strip():
            meta["gender"] = str(asset.gender).strip()
            updated = True
        if not str(meta.get("age_group") or "").strip() and str(asset.age or "").strip():
            meta["age_group"] = str(asset.age).strip()
            updated = True
        if not str(meta.get("age") or "").strip() and str(asset.age or "").strip():
            meta["age"] = str(asset.age).strip()
            updated = True

        # Sync clothing_style from visual_prompt if empty
        if not str(character.get("clothing_style") or "").strip() and str(asset.visual_prompt or "").strip():
            character["clothing_style"] = str(asset.visual_prompt).strip()
            updated = True

        # Sync personality
        if not str(character.get("personality") or "").strip() and str(asset.personality or "").strip():
            character["personality"] = str(asset.personality).strip()
            updated = True

    if updated:
        logger.info("[character-sync] Synced visual data from AssetStore for project %s", project_id)

    return updated


def sync_assets_from_characters(project: dict[str, Any], project_id: str) -> bool:
    """Sync voice/reference data from project.characters into AssetStore.

    Returns True if any data was updated.
    """
    try:
        from backend.assets import load_asset_store, save_asset_store
    except ImportError:
        return False

    try:
        store = load_asset_store(project_id)
    except Exception:
        return False

    if not store.characters:
        return False

    characters = project.get("characters", [])
    if not characters:
        return False

    # Build lookup from project characters
    char_map: dict[str, dict[str, Any]] = {}
    for character in characters:
        if not isinstance(character, dict):
            continue
        key = _normalized_key(character.get("name"))
        if key:
            char_map[key] = character

    updated = False
    for asset in store.characters:
        key = _normalized_key(asset.name)
        character = char_map.get(key)
        if character is None:
            continue

        # Sync voice_id from project character
        char_voice = str(character.get("voice_id") or "").strip()
        if char_voice and not asset.voice_id:
            asset.voice_id = char_voice
            updated = True

    if updated:
        save_asset_store(project_id, store)
        logger.info("[character-sync] Synced voice data from project.characters for %s", project_id)

    return updated


def ensure_characters_synced(project: dict[str, Any], project_id: str) -> dict[str, Any]:
    """Ensure project.characters has complete data from all sources.

    Call this before rendering or prompt compilation.
    """
    sync_characters_from_assets(project, project_id)
    return project
