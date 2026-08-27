"""Lightweight LLM dispatch hub.

Single entry point for all LLM calls in the project. Unifies configuration
(reading from llm_settings.json with env-var fallback), retry logic, usage
tracking, and task-level model routing.

Usage:
    from backend.llm_hub import llm_client

    content = llm_client.chat(
        system_prompt="You are a helpful assistant.",
        user_prompt="Hello",
        task="default",
    )
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
LLM_SETTINGS_FILE = ROOT / "workspace" / "llm_settings.json"
LLM_USAGE_FILE = ROOT / "workspace" / "llm_usage.jsonl"
LLM_DEBUG_DIR = ROOT / "outputs" / "llm_debug"

# Task definitions: key → (label, description) for UI display
TASK_DEFINITIONS: list[dict[str, str]] = [
    {"key": "language_model", "label": "语言模型", "desc": "文本改写、剧本拆解、导演解读等语言类任务的独立配置。"},
    {"key": "character_image", "label": "角色图生成", "desc": "角色设定图、参考图生成的独立模型或兼容接口配置。"},
    {"key": "storyboard", "label": "剧本拆解（故事→分镜）", "desc": "从故事大纲生成分镜场景"},
    {"key": "script_storyboard", "label": "剧本拆解（剧本→分镜）", "desc": "从完整剧本生成分镜场景"},
    {"key": "director_classify", "label": "导演解读（场景分类）", "desc": "对每个场景进行导演级分类与情绪标注"},
]

LANGUAGE_MODEL_TASKS = {"default", "storyboard", "script_storyboard", "director_classify"}

# Task keys that can have dedicated model overrides
KNOWN_TASKS = {t["key"] for t in TASK_DEFINITIONS}

# Retryable HTTP status codes
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

DEFAULT_TIMEOUT = 300
MAX_RETRIES = 3


def _load_env_file() -> None:
    """Load .env file into os.environ if not already loaded."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        pass


# Public aliases for backward compatibility with app.py
def load_llm_settings() -> dict[str, Any]:
    """Load LLM settings from JSON file, falling back to env vars."""
    return _load_settings()


def save_llm_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Persist LLM settings to JSON file."""
    return _save_settings(settings)


def _load_settings() -> dict[str, Any]:
    """Load LLM settings from JSON file, falling back to env vars."""
    _load_env_file()

    defaults: dict[str, Any] = {
        "api_key": os.environ.get("LLM_API_KEY", ""),
        "base_url": os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1"),
        "model": os.environ.get("LLM_MODEL", "deepseek-chat"),
        "json_mode": os.environ.get("LLM_JSON_MODE", "true").strip().lower()
        in ("1", "true", "yes", "on"),
        "task_overrides": {},
    }

    if LLM_SETTINGS_FILE.exists():
        try:
            data = json.loads(LLM_SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in ("api_key", "base_url", "model"):
                    if isinstance(data.get(key), str):
                        defaults[key] = data[key]
                if isinstance(data.get("json_mode"), bool):
                    defaults["json_mode"] = data["json_mode"]
                if isinstance(data.get("task_overrides"), dict):
                    defaults["task_overrides"] = data["task_overrides"]
                # Migrate old task_models format to task_overrides
                if isinstance(data.get("task_models"), dict) and not defaults["task_overrides"]:
                    for task_key, model_name in data["task_models"].items():
                        if isinstance(model_name, str) and model_name.strip():
                            defaults["task_overrides"][task_key] = {"model": model_name.strip()}
        except Exception:
            pass

    return defaults


def _save_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Persist LLM settings to JSON file."""
    # Normalize task_overrides: each task can have api_key/base_url/model subset
    raw_overrides = settings.get("task_overrides") or {}
    clean_overrides: dict[str, dict[str, str]] = {}
    if isinstance(raw_overrides, dict):
        for task_key, override in raw_overrides.items():
            if not isinstance(override, dict):
                continue
            clean: dict[str, str] = {}
            for field in ("api_key", "base_url", "model"):
                val = override.get(field)
                if isinstance(val, str) and val.strip():
                    if field == "base_url":
                        clean[field] = val.strip().rstrip("/")
                    else:
                        clean[field] = val.strip()
            if clean:
                clean_overrides[task_key] = clean

    normalized: dict[str, Any] = {
        "api_key": str(settings.get("api_key") or "").strip(),
        "base_url": str(settings.get("base_url") or "").strip().rstrip("/"),
        "model": str(settings.get("model") or "").strip(),
        "json_mode": bool(settings.get("json_mode", True)),
        "task_overrides": clean_overrides,
    }
    LLM_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    LLM_SETTINGS_FILE.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return normalized


def _append_usage(record: dict[str, Any]) -> None:
    """Append a usage record to the JSONL log file."""
    try:
        LLM_USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LLM_USAGE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass  # Usage logging is best-effort


def _read_usage() -> list[dict[str, Any]]:
    """Read all usage records."""
    if not LLM_USAGE_FILE.exists():
        return []
    records = []
    try:
        for line in LLM_USAGE_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    except Exception:
        pass
    return records


def get_usage_summary() -> dict[str, Any]:
    """Return aggregated usage statistics."""
    records = _read_usage()
    if not records:
        return {
            "total_calls": 0,
            "total_tokens": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "by_task": {},
            "by_model": {},
            "recent": [],
        }

    total_tokens = 0
    total_prompt = 0
    total_completion = 0
    by_task: dict[str, dict[str, int]] = {}
    by_model: dict[str, dict[str, int]] = {}

    for r in records:
        tokens = r.get("total_tokens", 0)
        prompt = r.get("prompt_tokens", 0)
        completion = r.get("completion_tokens", 0)
        total_tokens += tokens
        total_prompt += prompt
        total_completion += completion

        task = r.get("task", "default")
        if task not in by_task:
            by_task[task] = {"calls": 0, "tokens": 0}
        by_task[task]["calls"] += 1
        by_task[task]["tokens"] += tokens

        model = r.get("model", "unknown")
        if model not in by_model:
            by_model[model] = {"calls": 0, "tokens": 0}
        by_model[model]["calls"] += 1
        by_model[model]["tokens"] += tokens

    return {
        "total_calls": len(records),
        "total_tokens": total_tokens,
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "by_task": by_task,
        "by_model": by_model,
        "recent": records[-20:],
    }


class LlmClient:
    """Unified LLM client with config management, retry, and usage tracking."""

    def __init__(self) -> None:
        self._settings: dict[str, Any] | None = None
        self._settings_mtime: float = 0.0

    @property
    def settings(self) -> dict[str, Any]:
        """Return settings, hot-reloading if the JSON file changed on disk."""
        try:
            mtime = LLM_SETTINGS_FILE.stat().st_mtime if LLM_SETTINGS_FILE.exists() else 0.0
        except Exception:
            mtime = 0.0
        if self._settings is None or mtime != self._settings_mtime:
            self._settings = _load_settings()
            self._settings_mtime = mtime
        return self._settings

    def reload(self) -> None:
        """Force reload settings from disk."""
        self._settings = None
        self._settings  # trigger load

    def _resolve_task_config(self, task: str) -> dict[str, str]:
        """Resolve full config (api_key, base_url, model) for a given task.

        Task overrides take precedence over defaults. Only non-empty override
        fields replace the default value.
        """
        cfg = self.settings
        resolved = {
            "api_key": str(cfg.get("api_key") or "").strip(),
            "base_url": str(cfg.get("base_url") or "").strip().rstrip("/"),
            "model": str(cfg.get("model") or "").strip(),
        }
        overrides = cfg.get("task_overrides") or {}

        ordered_overrides: list[dict[str, Any]] = []
        if isinstance(overrides, dict):
            if task in LANGUAGE_MODEL_TASKS and isinstance(overrides.get("language_model"), dict):
                ordered_overrides.append(overrides["language_model"])
            task_override = overrides.get(task, {})
            if isinstance(task_override, dict):
                ordered_overrides.append(task_override)

        for override in ordered_overrides:
            for field in ("api_key", "base_url", "model"):
                val = override.get(field)
                if isinstance(val, str) and val.strip():
                    if field == "base_url":
                        resolved[field] = val.strip().rstrip("/")
                    else:
                        resolved[field] = val.strip()
        return resolved

    def _resolve_model(self, task: str) -> str:
        """Resolve model for a given task (backward compat)."""
        return self._resolve_task_config(task)["model"]

    def _build_request(
        self, payload: dict[str, Any], use_json_mode: bool
    ) -> dict[str, Any]:
        """Build request payload with optional JSON mode."""
        request_payload = {**payload}
        if use_json_mode:
            request_payload["response_format"] = {"type": "json_object"}
        return request_payload

    def _do_request(
        self, base_url: str, api_key: str, payload: dict[str, Any], timeout: int
    ) -> str:
        """Send a single HTTP request to the LLM API."""
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{base_url}/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")

    def _request_with_retry(
        self, base_url: str, api_key: str, payload: dict[str, Any], timeout: int, use_json_mode: bool
    ) -> str:
        """Send request with exponential backoff retry on retryable errors."""
        request_payload = self._build_request(payload, use_json_mode)

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                return self._do_request(base_url, api_key, request_payload, timeout)
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                # If JSON mode causes 400/422, retry without it
                if use_json_mode and exc.code in {400, 422} and attempt == 0:
                    try:
                        return self._do_request(base_url, api_key, payload, timeout)
                    except HTTPError as retry_exc:
                        retry_detail = retry_exc.read().decode("utf-8", errors="replace")
                        raise RuntimeError(f"LLM HTTP {retry_exc.code}: {retry_detail}") from retry_exc
                    except URLError as retry_exc:
                        raise RuntimeError(f"LLM request failed: {retry_exc}") from retry_exc

                if exc.code in _RETRYABLE_STATUS and attempt < MAX_RETRIES - 1:
                    wait = 2 ** attempt  # 1s, 2s, 4s
                    time.sleep(wait)
                    last_error = RuntimeError(f"LLM HTTP {exc.code}: {detail}")
                    continue
                raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
            except URLError as exc:
                if attempt < MAX_RETRIES - 1:
                    wait = 2 ** attempt
                    time.sleep(wait)
                    last_error = RuntimeError(f"LLM request failed: {exc}")
                    continue
                raise RuntimeError(f"LLM request failed: {exc}") from exc

        raise last_error or RuntimeError("LLM request failed after retries")

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        task: str = "default",
        model: str = "",
        temperature: float = 0.2,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> str:
        """Send a chat completion request and return the content string.

        Args:
            system_prompt: System message content.
            user_prompt: User message content.
            task: Task key for model routing and usage tracking.
            model: Override model; if empty, uses task_models or default.
            temperature: Sampling temperature.
            timeout: Request timeout in seconds.

        Returns:
            The assistant's response content string.

        Raises:
            RuntimeError: If configuration is missing or the request fails.
        """
        cfg = self.settings
        task_cfg = self._resolve_task_config(task)
        api_key = task_cfg["api_key"]
        base_url = task_cfg["base_url"]
        use_json_mode = bool(cfg.get("json_mode", True))

        resolved_model = (model.strip() if model else task_cfg["model"]).strip()

        if not api_key or not base_url or not resolved_model:
            raise RuntimeError(
                "Missing LLM_API_KEY, LLM_BASE_URL, or LLM_MODEL. "
                "Configure via the settings UI or .env file."
            )

        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }

        start_ts = time.time()
        ok = False
        usage_info: dict[str, Any] = {}
        content = ""
        error_msg = ""

        try:
            body = self._request_with_retry(base_url, api_key, payload, timeout, use_json_mode)
            response_json = json.loads(body)
            content = response_json["choices"][0]["message"]["content"]
            usage_info = response_json.get("usage", {})
            ok = True
            return content
        except Exception as exc:
            error_msg = str(exc)
            raise
        finally:
            duration_ms = int((time.time() - start_ts) * 1000)
            _append_usage({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(start_ts)),
                "task": task,
                "model": resolved_model,
                "prompt_tokens": usage_info.get("prompt_tokens", 0),
                "completion_tokens": usage_info.get("completion_tokens", 0),
                "total_tokens": usage_info.get("total_tokens", 0),
                "duration_ms": duration_ms,
                "ok": ok,
                "error": error_msg if not ok else "",
            })

    def chat_raw(
        self,
        payload: dict[str, Any],
        *,
        task: str = "default",
        timeout: int = DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        """Send a pre-built payload and return the full response dict.

        For advanced use cases where the caller needs full control over the
        request payload (e.g. custom messages, tools, etc).
        """
        cfg = self.settings
        task_cfg = self._resolve_task_config(task)
        api_key = task_cfg["api_key"]
        base_url = task_cfg["base_url"]
        use_json_mode = bool(cfg.get("json_mode", True))

        resolved_model = payload.get("model", "").strip()
        if not resolved_model:
            resolved_model = task_cfg["model"]
            payload = {**payload, "model": resolved_model}

        if not api_key or not base_url or not resolved_model:
            raise RuntimeError(
                "Missing LLM_API_KEY, LLM_BASE_URL, or LLM_MODEL. "
                "Configure via the settings UI or .env file."
            )

        start_ts = time.time()
        ok = False
        usage_info: dict[str, Any] = {}
        error_msg = ""

        try:
            body = self._request_with_retry(base_url, api_key, payload, timeout, use_json_mode)
            response_json = json.loads(body)
            usage_info = response_json.get("usage", {})
            ok = True
            return response_json
        except Exception as exc:
            error_msg = str(exc)
            raise
        finally:
            duration_ms = int((time.time() - start_ts) * 1000)
            _append_usage({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(start_ts)),
                "task": task,
                "model": resolved_model,
                "prompt_tokens": usage_info.get("prompt_tokens", 0),
                "completion_tokens": usage_info.get("completion_tokens", 0),
                "total_tokens": usage_info.get("total_tokens", 0),
                "duration_ms": duration_ms,
                "ok": ok,
                "error": error_msg if not ok else "",
            })


# Singleton instance
llm_client = LlmClient()
