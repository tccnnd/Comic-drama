from __future__ import annotations

from dataclasses import dataclass
import json
import re
import warnings
from pathlib import Path
from typing import Any


def _clean_prompt(text: str) -> str:
    raw = " ".join(str(text or "").split())
    return raw.strip(" ,\uFF0C;\uFF1B")


def _normalized_name(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).lower()


def find_project_root(start_path: str | Path) -> Path | None:
    path = Path(start_path).resolve()
    candidates = [path, *path.parents]
    for candidate in candidates:
        if (candidate / "project.json").exists():
            return candidate
    return None


@dataclass
class CompiledPrompt:
    positive: str
    character_count: int
    token_estimate: int = 0


class PromptCompiler:
    """
    Three-layer prompt compiler.
    Layer 1: scene core.
    Layer 2: character anchors from immutable features.
    Layer 3: project style guide.
    """

    def __init__(self, project_path: str | Path):
        self._root = Path(project_path)
        self._project = self._load_json(self._root / "project.json")
        self._style_guide = _clean_prompt(self._project.get("style_guide") or "")
        self._char_profiles = self._load_characters()

    def _load_json(self, path: Path) -> dict[str, Any]:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}

    def _load_characters(self) -> dict[str, dict[str, Any]]:
        profiles: dict[str, dict[str, Any]] = {}
        char_dir = self._root / "characters"
        if not char_dir.exists():
            return profiles
        for path in sorted(char_dir.glob("*.json")):
            try:
                profile = self._load_json(path)
            except Exception:
                continue
            name = _clean_prompt(profile.get("name") or path.stem)
            if not name:
                continue
            profiles[_normalized_name(name)] = profile
        return profiles

    def _estimate_tokens(self, positive: str) -> int:
        zh_chars = sum(1 for char in positive if "\u4e00" <= char <= "\u9fff")
        en_words = len(
            [
                word
                for word in positive.split()
                if not any("\u4e00" <= char <= "\u9fff" for char in word)
            ]
        )
        return int(zh_chars * 1.5) + en_words

    def compile(self, scene_visual: str, characters: list[str], speaker: str | None = None) -> CompiledPrompt:
        parts: list[str] = []

        core = _clean_prompt(scene_visual)
        if core:
            parts.append(core)

        anchors: list[str] = []
        seen: set[str] = set()
        speaker_key = _normalized_name(speaker)
        for name in characters or []:
            char_name = _clean_prompt(name)
            if not char_name:
                continue
            key = _normalized_name(char_name)
            if key in seen:
                continue
            seen.add(key)
            profile = self._char_profiles.get(key, {})
            immutable = _clean_prompt(profile.get("immutable_features") or "")
            if not immutable:
                fallback_parts = [
                    _clean_prompt(profile.get("appearance_core") or ""),
                    _clean_prompt(profile.get("clothing_style") or ""),
                ]
                immutable = _clean_prompt(", ".join(part for part in fallback_parts if part))
            if immutable:
                weight = 0.9 if key and key == speaker_key else 0.75
                anchors.append(f"({immutable}:{weight:g})")
        if anchors:
            parts.append(", ".join(anchors))

        if self._style_guide:
            parts.append(self._style_guide)

        positive = ", ".join(part for part in parts if part)
        token_estimate = self._estimate_tokens(positive)
        if token_estimate > 140:
            warnings.warn(
                f"Prompt token estimate {token_estimate}; near SDXL multi-chunk limits, consider shortening scene text",
                RuntimeWarning,
                stacklevel=2,
            )

        return CompiledPrompt(
            positive=positive,
            character_count=len(anchors),
            token_estimate=token_estimate,
        )
