"""
BGM matching helpers.

The matcher is intentionally asset-library friendly:
- explicit scene audio_manifest values win
- otherwise, director classification fields infer a style
- files can be organized by directory, filename tokens, or _meta.json tags
- no matching asset means "no BGM", not a render failure
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


AUDIO_EXTENSIONS = (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg")

BGM_STYLE_PRIORITY: dict[str, list[str]] = {
    "anger": ["anger", "tension", "action", "neutral"],
    "fear": ["fear", "tension", "action", "neutral"],
    "surprise": ["surprise", "tension", "neutral"],
    "tension": ["tension", "action", "fear", "neutral"],
    "sadness": ["sadness", "calm", "neutral"],
    "joy": ["joy", "upbeat", "calm", "neutral"],
    "calm": ["calm", "neutral"],
    "neutral": ["neutral", "calm"],
}

SCENE_INTENT_PRIORITY: dict[str, list[str]] = {
    "action": ["action", "tension", "anger", "neutral"],
    "reaction": ["tension", "sadness", "neutral"],
    "dialogue": ["calm", "neutral"],
    "establishing": ["calm", "neutral"],
    "transition": ["neutral", "calm"],
}

PACING_PRIORITY: dict[str, list[str]] = {
    "fast": ["tension", "action", "neutral"],
    "slow": ["sadness", "calm", "neutral"],
    "medium": ["neutral", "calm"],
}


@dataclass(frozen=True)
class BgmSelection:
    path: Path | None
    style: str = ""
    source: str = "none"  # explicit_file | explicit_style | auto | none
    reason: str = ""


def select_bgm_for_scene(
    scene: Any,
    manifest: dict[str, Any] | None,
    *,
    bgm_root: Path,
    project_root: Path | None = None,
) -> BgmSelection:
    manifest = manifest if isinstance(manifest, dict) else {}

    explicit_file = str(manifest.get("bgm_file") or manifest.get("bgm_path") or "").strip()
    if explicit_file:
        path = _resolve_path(explicit_file, bgm_root=bgm_root, project_root=project_root)
        if path is not None:
            return BgmSelection(path=path, style=_style_for_path(path, bgm_root), source="explicit_file")
        return BgmSelection(path=None, source="none", reason=f"explicit BGM not found: {explicit_file}")

    explicit_style = _normalize_label(manifest.get("bgm_style"))
    if explicit_style:
        path = _resolve_path(explicit_style, bgm_root=bgm_root, project_root=project_root)
        if path is not None:
            return BgmSelection(path=path, style=explicit_style, source="explicit_style")
        path = _pick_for_styles([explicit_style, "neutral", "calm"], scene, bgm_root)
        if path is not None:
            return BgmSelection(path=path, style=explicit_style, source="explicit_style")
        return BgmSelection(path=None, style=explicit_style, source="none", reason=f"no BGM asset for style: {explicit_style}")

    styles = infer_bgm_styles(scene)
    path = _pick_for_styles(styles, scene, bgm_root)
    if path is None:
        return BgmSelection(path=None, source="none", reason="no matching BGM assets")
    return BgmSelection(path=path, style=_first_known_style(styles), source="auto")


def infer_bgm_styles(scene: Any) -> list[str]:
    emotion = _normalize_label(_field(scene, "emotion_tone"))
    if not emotion:
        meta = _field(scene, "director_meta")
        if isinstance(meta, dict):
            emotion = _normalize_label(meta.get("emotion_tone"))
    if not emotion:
        emotion = _emotion_from_scene_text(_field(scene, "emotion"))

    intent = _normalize_label(_field(scene, "scene_intent"))
    pacing = _normalize_label(_field(scene, "pacing"))

    styles: list[str] = []
    styles.extend(BGM_STYLE_PRIORITY.get(emotion, []))
    styles.extend(SCENE_INTENT_PRIORITY.get(intent, []))
    styles.extend(PACING_PRIORITY.get(pacing, []))
    styles.extend(["neutral", "calm"])
    return _dedupe(styles)


def bgm_asset_count(bgm_root: Path) -> int:
    if not bgm_root.exists():
        return 0
    return len(_all_audio_files(bgm_root))


def _pick_for_styles(styles: list[str], scene: Any, bgm_root: Path) -> Path | None:
    if not bgm_root.exists():
        return None
    catalog = _build_catalog(bgm_root)
    for style in styles:
        candidates = catalog.get(style, [])
        if candidates:
            return _stable_pick(candidates, _scene_seed(scene, style))
    candidates = catalog.get("neutral", []) or catalog.get("__all__", [])
    if candidates:
        return _stable_pick(candidates, _scene_seed(scene, "fallback"))
    return None


def _build_catalog(bgm_root: Path) -> dict[str, list[Path]]:
    catalog: dict[str, list[Path]] = {"__all__": []}
    meta = _load_meta(bgm_root)
    for path in _all_audio_files(bgm_root):
        catalog["__all__"].append(path)
        labels = set(_labels_for_path(path, bgm_root))
        labels.update(_labels_from_meta(path, bgm_root, meta))
        if not labels:
            labels.add("neutral")
        for label in labels:
            catalog.setdefault(label, []).append(path)
    for key in list(catalog):
        catalog[key] = sorted(dict.fromkeys(catalog[key]), key=lambda item: str(item).lower())
    return catalog


def _all_audio_files(bgm_root: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in bgm_root.rglob("*")
            if path.is_file()
            and path.suffix.lower() in AUDIO_EXTENSIONS
            and not any(part.startswith(".") for part in path.relative_to(bgm_root).parts)
        ),
        key=lambda item: str(item).lower(),
    )


def _labels_for_path(path: Path, bgm_root: Path) -> list[str]:
    try:
        relative = path.relative_to(bgm_root)
    except ValueError:
        return []
    labels: list[str] = []
    if len(relative.parts) > 1:
        labels.append(_normalize_label(relative.parts[0]))
    stem_tokens = path.stem.replace("-", "_").split("_")
    labels.extend(_normalize_label(token) for token in stem_tokens)
    return [label for label in labels if label]


def _labels_from_meta(path: Path, bgm_root: Path, meta: dict[str, Any]) -> list[str]:
    if not meta:
        return []
    try:
        relative = path.relative_to(bgm_root).as_posix()
    except ValueError:
        relative = path.name
    files = meta.get("files") if isinstance(meta.get("files"), dict) else meta
    entry = None
    if isinstance(files, dict):
        entry = files.get(relative) or files.get(path.name) or files.get(path.stem)
    if not isinstance(entry, dict):
        return []
    tags = entry.get("tags") or entry.get("styles") or entry.get("emotion")
    if isinstance(tags, str):
        tags = [tags]
    if not isinstance(tags, list):
        return []
    return [_normalize_label(item) for item in tags if _normalize_label(item)]


def _load_meta(bgm_root: Path) -> dict[str, Any]:
    path = bgm_root / "_meta.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _resolve_path(raw: str, *, bgm_root: Path, project_root: Path | None) -> Path | None:
    value = str(raw or "").strip()
    if not value:
        return None
    candidate = Path(value)
    candidates: list[Path] = []
    if candidate.is_absolute():
        candidates.append(candidate)
    elif project_root is not None:
        candidates.append((project_root / candidate).resolve())
    candidates.append((bgm_root / candidate).resolve())
    if not candidate.suffix:
        expanded: list[Path] = []
        for item in candidates:
            expanded.append(item)
            expanded.extend(item.with_suffix(suffix) for suffix in AUDIO_EXTENSIONS)
        candidates = expanded
    for item in candidates:
        if item.exists() and item.is_file():
            return item
    if candidate.suffix:
        stem = candidate.stem
    else:
        stem = candidate.name
    for item in _all_audio_files(bgm_root):
        if item.name == candidate.name or item.stem == stem:
            return item
    return None


def _stable_pick(candidates: list[Path], seed: str) -> Path:
    if len(candidates) == 1:
        return candidates[0]
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    return candidates[int(digest[:8], 16) % len(candidates)]


def _scene_seed(scene: Any, style: str) -> str:
    parts = [
        str(_field(scene, "scene", "")),
        str(_field(scene, "title", "")),
        str(_field(scene, "speaker", "")),
        style,
    ]
    return "|".join(parts)


def _field(scene: Any, name: str, default: Any = "") -> Any:
    if scene is None:
        return default
    if isinstance(scene, dict):
        return scene.get(name, default)
    return getattr(scene, name, default)


def _normalize_label(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _emotion_from_scene_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if any(token in text for token in ("怒", "气", "爆", "震", "紧张", "恐惧")):
        return "tension"
    if any(token in text for token in ("悲", "伤", "失落", "难过", "哭")):
        return "sadness"
    if any(token in text for token in ("喜", "乐", "开心", "轻松", "甜")):
        return "joy"
    if any(token in text for token in ("静", "平静", "日常", "对话", "回忆")):
        return "calm"
    return _normalize_label(text)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _first_known_style(styles: list[str]) -> str:
    for style in styles:
        if style in BGM_STYLE_PRIORITY or style in SCENE_INTENT_PRIORITY or style in PACING_PRIORITY:
            return style
    return styles[0] if styles else ""


def _style_for_path(path: Path, bgm_root: Path) -> str:
    try:
        relative = path.relative_to(bgm_root)
    except ValueError:
        return ""
    if len(relative.parts) > 1:
        return _normalize_label(relative.parts[0])
    return ""


def _emotion_from_scene_text(value: Any) -> str:  # override the earlier display-mangled copy
    text = str(value or "").strip()
    if not text:
        return ""
    if any(token in text for token in ("\u6012", "\u6c14", "\u7206", "\u9707", "\u7d27\u5f20", "\u6050\u60e7")):
        return "tension"
    if any(token in text for token in ("\u60b2", "\u4f24", "\u5931\u843d", "\u96be\u8fc7", "\u54ed")):
        return "sadness"
    if any(token in text for token in ("\u559c", "\u4e50", "\u5f00\u5fc3", "\u8f7b\u677e", "\u751c")):
        return "joy"
    if any(token in text for token in ("\u9759", "\u5e73\u9759", "\u65e5\u5e38", "\u5bf9\u8bdd", "\u56de\u5fc6")):
        return "calm"
    return _normalize_label(text)
