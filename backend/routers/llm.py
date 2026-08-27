from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from backend.llm_hub import (
    LLM_SETTINGS_FILE,
    TASK_DEFINITIONS,
)
from backend.llm_hub import get_usage_summary as _get_llm_usage_summary
from backend.llm_hub import llm_client as _llm_client
from backend.llm_hub import load_llm_settings, save_llm_settings

router = APIRouter(tags=["llm"])


def llm_settings_config_path() -> str:
    return str(LLM_SETTINGS_FILE)


# ─── Common LLM endpoint presets ─────────────────────────────────────────────
LLM_PRESETS: list[dict[str, str]] = [
    {"label": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    {"label": "OpenAI", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    {
        "label": "通义千问 (DashScope)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
    {
        "label": "Moonshot (Kimi)",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
    },
    {
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
    },
    {"label": "自定义", "base_url": "", "model": ""},
]


class LlmSettingsRequest(BaseModel):
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    json_mode: bool = True
    task_overrides: dict[str, dict[str, str]] | None = None


def is_masked_api_key(value: str) -> bool:
    text = str(value or "").strip()
    return bool(text) and text.startswith(("•", "*"))


def merge_llm_settings_payload(payload: LlmSettingsRequest) -> dict[str, Any]:
    stored = load_llm_settings()
    api_key = payload.api_key.strip()
    if is_masked_api_key(api_key):
        api_key = str(stored.get("api_key") or "")

    stored_overrides = (
        stored.get("task_overrides") if isinstance(stored.get("task_overrides"), dict) else {}
    )
    merged_overrides: dict[str, dict[str, str]] = {}
    for task_key, override in (payload.task_overrides or {}).items():
        if not isinstance(override, dict):
            continue
        clean: dict[str, str] = {}
        for field in ("base_url", "model"):
            value = override.get(field)
            if isinstance(value, str) and value.strip():
                clean[field] = value.strip()
        override_key = str(override.get("api_key") or "").strip()
        if is_masked_api_key(override_key):
            stored_key = (
                stored_overrides.get(task_key, {}).get("api_key")
                if isinstance(stored_overrides.get(task_key), dict)
                else ""
            )
            if stored_key:
                clean["api_key"] = str(stored_key)
        elif "api_key" in override:
            if override_key:
                clean["api_key"] = override_key
        else:
            stored_key = (
                stored_overrides.get(task_key, {}).get("api_key")
                if isinstance(stored_overrides.get(task_key), dict)
                else ""
            )
            if stored_key:
                clean["api_key"] = str(stored_key)
        if clean:
            merged_overrides[str(task_key)] = clean

    return {
        "api_key": api_key,
        "base_url": payload.base_url.strip().rstrip("/"),
        "model": payload.model.strip(),
        "json_mode": payload.json_mode,
        "task_overrides": merged_overrides,
    }


@router.get("/api/llm-settings")
def llm_settings_endpoint() -> dict:
    """Return current LLM configuration and available presets."""
    settings = load_llm_settings()
    # Mask the API key for security: show only last 4 characters
    api_key = str(settings.get("api_key") or "")
    masked_key = f"••••••••{api_key[-4:]}" if len(api_key) > 4 else ("••••" if api_key else "")

    # Mask API keys in task_overrides
    raw_overrides = settings.get("task_overrides") or {}
    masked_overrides: dict[str, dict[str, Any]] = {}
    for task_key, override in raw_overrides.items():
        if not isinstance(override, dict):
            continue
        masked_entry: dict[str, Any] = {}
        for field in ("api_key", "base_url", "model"):
            if field in override:
                if field == "api_key":
                    ov_key = str(override.get("api_key") or "")
                    masked_entry["api_key_masked"] = (
                        f"••••••••{ov_key[-4:]}" if len(ov_key) > 4 else ("••••" if ov_key else "")
                    )
                    masked_entry["api_key_set"] = bool(ov_key)
                else:
                    masked_entry[field] = override[field]
        masked_overrides[task_key] = masked_entry

    return {
        "settings": {
            "api_key_masked": masked_key,
            "api_key_set": bool(api_key),
            "base_url": settings.get("base_url", ""),
            "model": settings.get("model", ""),
            "json_mode": settings.get("json_mode", True),
            "task_overrides": masked_overrides,
        },
        "presets": LLM_PRESETS,
        "task_definitions": TASK_DEFINITIONS,
        "config_path": llm_settings_config_path(),
    }


@router.put("/api/llm-settings")
def save_llm_settings_endpoint(payload: LlmSettingsRequest) -> dict:
    """Save LLM configuration to the JSON config file."""
    data = merge_llm_settings_payload(payload)
    saved = save_llm_settings(data)

    # Force the LLM client to pick up the new config
    _llm_client.reload()

    # Return masked key
    api_key = str(saved.get("api_key") or "")
    masked_key = f"••••••••{api_key[-4:]}" if len(api_key) > 4 else ("••••" if api_key else "")

    # Mask API keys in task_overrides
    raw_overrides = saved.get("task_overrides") or {}
    masked_overrides: dict[str, dict[str, Any]] = {}
    for task_key, override in raw_overrides.items():
        if not isinstance(override, dict):
            continue
        masked_entry: dict[str, Any] = {}
        for field in ("api_key", "base_url", "model"):
            if field in override:
                if field == "api_key":
                    ov_key = str(override.get("api_key") or "")
                    masked_entry["api_key_masked"] = (
                        f"••••••••{ov_key[-4:]}" if len(ov_key) > 4 else ("••••" if ov_key else "")
                    )
                    masked_entry["api_key_set"] = bool(ov_key)
                else:
                    masked_entry[field] = override[field]
        masked_overrides[task_key] = masked_entry

    return {
        "settings": {
            "api_key_masked": masked_key,
            "api_key_set": bool(api_key),
            "base_url": saved.get("base_url", ""),
            "model": saved.get("model", ""),
            "json_mode": saved.get("json_mode", True),
            "task_overrides": masked_overrides,
        },
        "task_definitions": TASK_DEFINITIONS,
        "config_path": llm_settings_config_path(),
    }


@router.post("/api/llm-test")
def test_llm_connection(payload: LlmSettingsRequest) -> dict:
    """Test LLM connection with the provided settings."""
    api_key = payload.api_key.strip()
    base_url = payload.base_url.strip().rstrip("/")
    model = payload.model.strip()

    # If api_key is blank or looks like a mask, load the stored key.
    if not api_key or is_masked_api_key(api_key):
        stored = load_llm_settings()
        api_key = str(stored.get("api_key") or "")
        if not api_key:
            return {"ok": False, "error": "未找到已保存的 API Key，请输入完整的 Key"}

    if not base_url or not model:
        return {"ok": False, "error": "Base URL 和 Model 不能为空"}

    try:
        import urllib.request

        url = f"{base_url}/chat/completions"
        body = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 5,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_body = json.loads(resp.read().decode("utf-8"))
            resp_model = resp_body.get("model", "")
            return {"ok": True, "model": resp_model or model}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/api/llm-usage")
def llm_usage_endpoint() -> dict:
    """Return aggregated LLM usage statistics."""
    return _get_llm_usage_summary()
