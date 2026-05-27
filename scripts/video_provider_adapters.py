from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from video_providers import VideoProviderSpec


class VideoProviderError(RuntimeError):
    """Base error for remote video provider failures."""


class VideoProviderConfigError(VideoProviderError):
    """Raised when a provider is selected but not configured."""


@dataclass(frozen=True)
class VideoRenderRequest:
    scene: int
    title: str
    prompt: str
    negative_prompt: str
    keyframe_path: Path
    out_path: Path
    run_dir: Path
    duration: float
    width: int
    height: int
    fps: int
    camera: str = ""
    emotion: str = ""
    dialogue: str = ""
    characters: tuple[str, ...] = ()
    temporal_spec: dict[str, Any] | None = None
    consistency_spec: dict[str, Any] | None = None


def _env(prefix: str, name: str, default: str = "") -> str:
    return os.environ.get(f"{prefix}_{name}", default).strip()


def _env_any(prefix: str, names: tuple[str, ...], default: str = "") -> str:
    for name in names:
        value = _env(prefix, name)
        if value:
            return value
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def _env_float(prefix: str, name: str, default: float) -> float:
    raw = _env(prefix, name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _provider_prefix(spec: VideoProviderSpec) -> str:
    return spec.id.upper().replace("-", "_")


def _join_url(base_url: str, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _root_base_url(base_url: str) -> str:
    return base_url.rstrip("/").removesuffix("/v1").removesuffix("/v2")


def _json_request(url: str, payload: dict[str, Any] | None, headers: dict[str, str], timeout: float) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=data, headers=headers, method="GET" if payload is None else "POST")
    with urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise VideoProviderError(f"Provider response must be a JSON object: {url}")
    return parsed


def _multipart_request(url: str, fields: dict[str, str], files: dict[str, Path], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    boundary = f"----comicdrama-{uuid.uuid4().hex}"
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")
    for name, path in files.items():
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'.encode("utf-8")
        )
        body.extend(f"Content-Type: {mime}\r\n\r\n".encode("utf-8"))
        body.extend(path.read_bytes())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    req_headers = dict(headers)
    req_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = Request(url, data=bytes(body), headers=req_headers, method="POST")
    with urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    parsed = json.loads(raw) if raw.strip() else {}
    if not isinstance(parsed, dict):
        raise VideoProviderError(f"Provider response must be a JSON object: {url}")
    return parsed


def _extract_task_id(payload: dict[str, Any]) -> str:
    for key in ("task_id", "taskId", "id", "job_id", "jobId", "request_id", "requestId"):
        value = payload.get(key)
        if value:
            return str(value)
    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_task_id(data)
    result = payload.get("result")
    if isinstance(result, dict):
        return _extract_task_id(result)
    response = payload.get("response")
    if isinstance(response, dict):
        return _extract_task_id(response)
    return ""


def _extract_video_url(payload: dict[str, Any]) -> str:
    for key in ("video_url", "videoUrl", "output_url", "outputUrl", "url"):
        value = payload.get(key)
        if value:
            return str(value)
    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_video_url(data)
    result = payload.get("result")
    if isinstance(result, dict):
        return _extract_video_url(result)
    response = payload.get("response")
    if isinstance(response, dict):
        return _extract_video_url(response)
    content = payload.get("content")
    if isinstance(content, dict):
        return _extract_video_url(content)
    output = payload.get("output")
    if isinstance(output, dict):
        return _extract_video_url(output)
    if isinstance(output, list) and output:
        first = output[0]
        if isinstance(first, dict):
            return _extract_video_url(first)
        if isinstance(first, str):
            return first
    return ""


def _extract_video_base64(payload: dict[str, Any]) -> str:
    for key in ("video_base64", "videoBase64", "base64", "video"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_video_base64(data)
    output = payload.get("output")
    if isinstance(output, dict):
        return _extract_video_base64(output)
    return ""


def _status(payload: dict[str, Any]) -> str:
    for key in ("status", "state", "task_status", "taskStatus"):
        value = payload.get(key)
        if value:
            return str(value).strip().lower()
    data = payload.get("data")
    if isinstance(data, dict):
        return _status(data)
    output = payload.get("output")
    if isinstance(output, dict):
        for key in ("task_status", "status"):
            value = output.get(key)
            if value:
                return str(value).strip().lower()
    return ""


def _first_frame_url(request: VideoRenderRequest, prefix: str, headers: dict[str, str]) -> str:
    existing = _env(prefix, "REFERENCE_IMAGE_URL")
    if existing:
        return existing

    upload_url = _env(prefix, "IMAGE_UPLOAD_URL")
    if not upload_url:
        return ""

    mode = (_env(prefix, "IMAGE_UPLOAD_MODE", "json") or "json").lower()
    if mode == "multipart":
        field = _env(prefix, "IMAGE_UPLOAD_FIELD", "file")
        response = _multipart_request(upload_url, {}, {field: request.keyframe_path}, headers, timeout=120)
    else:
        image_b64 = base64.b64encode(request.keyframe_path.read_bytes()).decode("ascii")
        payload = {
            "image_base64": image_b64,
            "filename": request.keyframe_path.name,
            "scene": request.scene,
        }
        safe_payload = dict(payload)
        safe_payload["image_base64"] = f"<base64:{len(image_b64)} chars>"
        _write_debug(request.run_dir, request.scene, "image_upload_payload", safe_payload)
        response = _json_request(upload_url, payload, headers, timeout=120)

    _write_debug(request.run_dir, request.scene, "image_upload_response", response)
    url = _extract_video_url(response)
    if not url:
        for key in ("image_url", "imageUrl", "file_url", "fileUrl"):
            value = response.get(key)
            if value:
                url = str(value)
                break
    if not url:
        raise VideoProviderError("Image upload succeeded but did not return a URL.")
    return url


def _aspect_ratio(width: int, height: int) -> str:
    return "9:16" if int(height) >= int(width) else "16:9"


def _openai_size(width: int, height: int, model: str) -> str:
    portrait = int(height) >= int(width)
    pro = "pro" in model.lower()
    if pro and max(width, height) >= 1792:
        return "1080x1920" if portrait else "1920x1080"
    return "720x1280" if portrait else "1280x720"


def _detect_route(prefix: str, spec: VideoProviderSpec, model: str) -> str:
    explicit = _env(prefix, "ROUTE")
    if explicit:
        return explicit.strip().lower()
    name = f"{spec.id} {model}".lower()
    if spec.id == "sora" or "sora-2" in name or "openai" in name:
        return "openai_official"
    if "seedance" in name or "doubao" in name or spec.id in {"doubao", "seedance"}:
        return "volc"
    if "kling" in name:
        return "kling"
    return "unified"


def _decode_base64_video(raw: str, out_path: Path) -> None:
    payload = raw
    if raw.startswith("data:") and "," in raw:
        payload = raw.split(",", 1)[1]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(base64.b64decode(payload))


def _download_video(url: str, out_path: Path, headers: dict[str, str], timeout: float) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urlopen(Request(url), timeout=timeout) as response:
            out_path.write_bytes(response.read())
            return
    except HTTPError as exc:
        if exc.code not in {401, 403}:
            raise
    with urlopen(Request(url, headers=headers), timeout=timeout) as response:
        out_path.write_bytes(response.read())


def _write_debug(run_dir: Path, scene: int, name: str, payload: object) -> None:
    debug_dir = run_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / f"scene_{scene:02}_remote_video_{name}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _send_structured_spec(prefix: str) -> bool:
    raw = os.environ.get(f"{prefix}_SEND_STRUCTURED_SPEC", os.environ.get("VIDEO_SEND_STRUCTURED_SPEC", "0"))
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _structured_spec_mode(prefix: str, route: str) -> str:
    raw = os.environ.get(f"{prefix}_STRUCTURED_SPEC_MODE", os.environ.get("VIDEO_STRUCTURED_SPEC_MODE", "auto"))
    mode = raw.strip().lower()
    if mode in {"none", "off", "0", "false", "no"}:
        return "none"
    if mode in {"fields", "prompt", "both"}:
        return mode
    if route == "unified":
        return "fields"
    return "prompt"


def _structured_metadata(request: VideoRenderRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if isinstance(request.temporal_spec, dict) and request.temporal_spec:
        payload["temporal_spec"] = request.temporal_spec
    if isinstance(request.consistency_spec, dict) and request.consistency_spec:
        payload["consistency_spec"] = request.consistency_spec
    return payload


def _scene_context_payload(request: VideoRenderRequest) -> dict[str, Any]:
    return {
        "scene": request.scene,
        "title": request.title,
        "camera": request.camera,
        "emotion": request.emotion,
        "dialogue": request.dialogue,
        "characters": list(request.characters or ()),
    }


def _structured_json_text(payload: dict[str, Any], limit: int) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(raw) <= limit:
        return raw
    return raw[: max(0, limit - 32)] + "...<truncated>"


def _prompt_with_structured_spec(prompt: str, request: VideoRenderRequest, prefix: str, route: str) -> str:
    mode = _structured_spec_mode(prefix, route)
    if mode not in {"prompt", "both"}:
        return prompt
    metadata = _structured_metadata(request)
    if not metadata:
        return prompt
    limit = int(_env_float(prefix, "STRUCTURED_SPEC_PROMPT_LIMIT", float(os.environ.get("VIDEO_STRUCTURED_SPEC_PROMPT_LIMIT", "6000") or 6000)))
    block = _structured_json_text(metadata, max(1000, limit))
    return (
        f"{prompt}\n\n"
        "Structured continuity contract for this video generation. Follow it as production constraints, not narration:\n"
        f"{block}"
    )


def _attach_structured_fields(body: dict[str, Any], request: VideoRenderRequest, prefix: str, route: str) -> None:
    mode = _structured_spec_mode(prefix, route)
    if mode not in {"fields", "both"}:
        return
    metadata = _structured_metadata(request)
    if not metadata:
        return
    metadata_field = _env(prefix, "METADATA_FIELD", "metadata")
    temporal_field = _env(prefix, "TEMPORAL_SPEC_FIELD", "temporal_spec")
    consistency_field = _env(prefix, "CONSISTENCY_SPEC_FIELD", "consistency_spec")
    if metadata_field:
        body[metadata_field] = metadata
    if temporal_field and isinstance(request.temporal_spec, dict):
        body[temporal_field] = request.temporal_spec
    if consistency_field and isinstance(request.consistency_spec, dict):
        body[consistency_field] = request.consistency_spec


def _transcode_to_mp4(
    source_path: Path,
    out_path: Path,
    *,
    ffmpeg: str | None,
    run_guarded: Callable[..., Any] | None,
    duration: float,
    timeout_s: int,
) -> None:
    if ffmpeg is None or run_guarded is None:
        source_path.replace(out_path)
        return
    run_guarded(
        [
            ffmpeg,
            "-y",
            "-i",
            str(source_path),
            "-t",
            f"{float(duration):.3f}",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            str(out_path),
        ],
        cwd=out_path.parent,
        timeout=timeout_s,
        stage="ffmpeg_transcode_remote_video",
    )


def _poll_task(
    *,
    request: VideoRenderRequest,
    spec: VideoProviderSpec,
    task_id: str,
    poll_url: str,
    headers: dict[str, str],
    poll_interval: float,
    timeout_s: int,
) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    result: dict[str, Any] = {}
    while time.time() < deadline:
        try:
            result = _json_request(poll_url, None, headers, timeout=60)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise VideoProviderError(f"{spec.label} poll failed for task {task_id}: {exc}") from exc
        _write_debug(request.run_dir, request.scene, f"{spec.id}_poll_response", result)
        status = _status(result)
        if status in {"completed", "complete", "success", "succeeded", "done", "succeed"}:
            return result
        if status in {"failed", "failure", "error", "cancelled", "canceled", "expired"}:
            raise VideoProviderError(f"{spec.label} task {task_id} failed: {json.dumps(result, ensure_ascii=False)}")
        if _extract_video_url(result) or _extract_video_base64(result):
            return result
        time.sleep(poll_interval)
    raise VideoProviderError(f"{spec.label} task {task_id} timed out after {timeout_s}s.")


def _finish_video_result(
    request: VideoRenderRequest,
    spec: VideoProviderSpec,
    result: dict[str, Any],
    headers: dict[str, str],
    *,
    ffmpeg: str | None,
    run_guarded: Callable[..., Any] | None,
    timeout_s: int,
) -> Path:
    source_path = request.out_path
    video_b64 = _extract_video_base64(result)
    video_url = _extract_video_url(result)
    if video_b64:
        _decode_base64_video(video_b64, source_path)
    elif video_url:
        suffix = Path(urlparse(video_url).path).suffix.lower()
        download_path = request.out_path if suffix in {"", ".mp4"} else request.out_path.with_name(f"{request.out_path.stem}_source{suffix}")
        _download_video(video_url, download_path, headers, timeout=max(120, timeout_s))
        source_path = download_path
    else:
        raise VideoProviderError(f"{spec.label} response did not include video_url or video_base64.")

    if source_path.suffix.lower() != ".mp4" or source_path != request.out_path:
        _transcode_to_mp4(
            source_path,
            request.out_path,
            ffmpeg=ffmpeg,
            run_guarded=run_guarded,
            duration=request.duration,
            timeout_s=timeout_s,
        )

    _write_debug(
        request.run_dir,
        request.scene,
        f"{spec.id}_downloaded_asset",
        {"provider": asdict(spec), "output_path": str(request.out_path)},
    )
    return request.out_path


def _render_openai_official(
    request: VideoRenderRequest,
    spec: VideoProviderSpec,
    prefix: str,
    api_key: str,
    model: str,
    base_url: str,
    headers: dict[str, str],
    *,
    timeout_s: int,
    ffmpeg: str | None,
    run_guarded: Callable[..., Any] | None,
    submit_url: str = "",
    poll_url_template: str = "",
    content_url_template: str = "",
) -> Path:
    endpoint = submit_url or _join_url(base_url, _env(prefix, "SUBMIT_PATH", "videos"))
    prompt_text = _prompt_with_structured_spec(request.prompt, request, prefix, "openai_official")
    fields = {
        "model": model,
        "prompt": prompt_text,
        "size": _env(prefix, "SIZE", _openai_size(request.width, request.height, model)),
        "seconds": str(int(round(float(request.duration)))),
    }
    upload_field = _env(prefix, "REFERENCE_FIELD", "input_reference")
    response = _multipart_request(endpoint, fields, {upload_field: request.keyframe_path}, {"Authorization": f"Bearer {api_key}"}, timeout=120)
    _write_debug(request.run_dir, request.scene, f"{spec.id}_submit_response", response)

    task_id = _extract_task_id(response)
    if not task_id:
        return _finish_video_result(request, spec, response, headers, ffmpeg=ffmpeg, run_guarded=run_guarded, timeout_s=timeout_s)

    poll_url = poll_url_template or _join_url(base_url, _env(prefix, "POLL_PATH", f"videos/{task_id}").replace("{task_id}", task_id))
    result = _poll_task(
        request=request,
        spec=spec,
        task_id=task_id,
        poll_url=poll_url,
        headers=headers,
        poll_interval=max(1.0, _env_float(prefix, "POLL_INTERVAL_SECONDS", 5.0)),
        timeout_s=timeout_s,
    )
    if not (_extract_video_url(result) or _extract_video_base64(result)):
        content_url = content_url_template or _join_url(base_url, _env(prefix, "CONTENT_PATH", f"videos/{task_id}/content").replace("{task_id}", task_id))
        result = {"video_url": content_url, "status": "completed"}
    return _finish_video_result(request, spec, result, headers, ffmpeg=ffmpeg, run_guarded=run_guarded, timeout_s=timeout_s)


def _render_unified(
    request: VideoRenderRequest,
    spec: VideoProviderSpec,
    prefix: str,
    model: str,
    base_url: str,
    headers: dict[str, str],
    *,
    timeout_s: int,
    ffmpeg: str | None,
    run_guarded: Callable[..., Any] | None,
    submit_url: str = "",
    poll_url_template: str = "",
) -> Path:
    first_frame_url = _first_frame_url(request, prefix, headers)
    if not first_frame_url and _env(prefix, "REQUIRE_IMAGE_URL", "1").lower() not in {"0", "false", "no"}:
        raise VideoProviderConfigError(
            f"{prefix}_IMAGE_UPLOAD_URL or {prefix}_REFERENCE_IMAGE_URL is required for unified video providers."
        )

    root = _root_base_url(base_url)
    submit_path = _env(prefix, "SUBMIT_PATH", "/v1/videos/generations")
    poll_path = _env(prefix, "POLL_PATH", "/v1/tasks/{task_id}")
    prompt_text = _prompt_with_structured_spec(request.prompt, request, prefix, "unified")
    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt_text,
        "duration": float(request.duration),
        "aspect_ratio": _aspect_ratio(request.width, request.height),
        "resolution": _env(prefix, "RESOLUTION", "720p"),
        "audio": _env(prefix, "AUDIO", "false").lower() in {"1", "true", "yes", "on"},
        "camerafixed": _env(prefix, "CAMERA_FIXED", "false").lower() in {"1", "true", "yes", "on"},
    }
    if first_frame_url:
        body["image"] = first_frame_url
        body["image_with_roles"] = [{"url": first_frame_url, "role": "first_frame"}]
    _attach_structured_fields(body, request, prefix, "unified")
    _write_debug(request.run_dir, request.scene, f"{spec.id}_submit_payload", body)

    response = _json_request(submit_url or _join_url(root, submit_path), body, headers, timeout=120)
    _write_debug(request.run_dir, request.scene, f"{spec.id}_submit_response", response)
    task_id = _extract_task_id(response)
    if not task_id:
        return _finish_video_result(request, spec, response, headers, ffmpeg=ffmpeg, run_guarded=run_guarded, timeout_s=timeout_s)

    result = _poll_task(
        request=request,
        spec=spec,
        task_id=task_id,
        poll_url=poll_url_template or _join_url(root, poll_path.replace("{task_id}", task_id)),
        headers=headers,
        poll_interval=max(1.0, _env_float(prefix, "POLL_INTERVAL_SECONDS", 5.0)),
        timeout_s=timeout_s,
    )
    return _finish_video_result(request, spec, result, headers, ffmpeg=ffmpeg, run_guarded=run_guarded, timeout_s=timeout_s)


def _render_volc(
    request: VideoRenderRequest,
    spec: VideoProviderSpec,
    prefix: str,
    model: str,
    base_url: str,
    headers: dict[str, str],
    *,
    timeout_s: int,
    ffmpeg: str | None,
    run_guarded: Callable[..., Any] | None,
    submit_url: str = "",
    poll_url_template: str = "",
) -> Path:
    first_frame_url = _first_frame_url(request, prefix, headers)
    if not first_frame_url:
        raise VideoProviderConfigError(f"{prefix}_IMAGE_UPLOAD_URL or {prefix}_REFERENCE_IMAGE_URL is required for Volc/Seedance.")

    text = _prompt_with_structured_spec(request.prompt, request, prefix, "volc")
    text += f" --rs {_env(prefix, 'RESOLUTION', '720p')}"
    text += f" --rt {_aspect_ratio(request.width, request.height)}"
    text += f" --dur {int(round(float(request.duration)))}"
    text += f" --cf {_env(prefix, 'CAMERA_FIXED', 'false').lower() in {'1', 'true', 'yes', 'on'}}"
    body = {
        "model": model,
        "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": first_frame_url}, "role": "first_frame"},
        ],
    }
    _write_debug(request.run_dir, request.scene, f"{spec.id}_submit_payload", body)

    root = _root_base_url(base_url)
    response = _json_request(
        submit_url or _join_url(root, _env(prefix, "SUBMIT_PATH", "/volc/v1/contents/generations/tasks")),
        body,
        headers,
        timeout=120,
    )
    _write_debug(request.run_dir, request.scene, f"{spec.id}_submit_response", response)
    task_id = _extract_task_id(response)
    if not task_id:
        return _finish_video_result(request, spec, response, headers, ffmpeg=ffmpeg, run_guarded=run_guarded, timeout_s=timeout_s)

    poll_path = _env(prefix, "POLL_PATH", "/volc/v1/contents/generations/tasks/{task_id}")
    result = _poll_task(
        request=request,
        spec=spec,
        task_id=task_id,
        poll_url=poll_url_template or _join_url(root, poll_path.replace("{task_id}", task_id)),
        headers=headers,
        poll_interval=max(1.0, _env_float(prefix, "POLL_INTERVAL_SECONDS", 5.0)),
        timeout_s=timeout_s,
    )
    return _finish_video_result(request, spec, result, headers, ffmpeg=ffmpeg, run_guarded=run_guarded, timeout_s=timeout_s)


def _render_kling(
    request: VideoRenderRequest,
    spec: VideoProviderSpec,
    prefix: str,
    model: str,
    base_url: str,
    headers: dict[str, str],
    *,
    timeout_s: int,
    ffmpeg: str | None,
    run_guarded: Callable[..., Any] | None,
    submit_url: str = "",
    poll_url_template: str = "",
) -> Path:
    first_frame_url = _first_frame_url(request, prefix, headers)
    root = _root_base_url(base_url)
    endpoint_type = "image2video" if first_frame_url else "text2video"
    prompt_text = _prompt_with_structured_spec(request.prompt, request, prefix, "kling")
    body: dict[str, Any] = {
        "model_name": model,
        "prompt": prompt_text,
        "aspect_ratio": _aspect_ratio(request.width, request.height),
        "duration": str(max(5, min(10, int(round(float(request.duration)))))),
        "mode": _env(prefix, "MODE", "std"),
    }
    if first_frame_url:
        body["image_url"] = first_frame_url
    _write_debug(request.run_dir, request.scene, f"{spec.id}_submit_payload", body)

    submit_path = _env(prefix, "SUBMIT_PATH", f"/kling/v1/videos/{endpoint_type}")
    response = _json_request(submit_url or _join_url(root, submit_path), body, headers, timeout=120)
    _write_debug(request.run_dir, request.scene, f"{spec.id}_submit_response", response)
    task_id = _extract_task_id(response)
    if not task_id:
        return _finish_video_result(request, spec, response, headers, ffmpeg=ffmpeg, run_guarded=run_guarded, timeout_s=timeout_s)

    poll_path = _env(prefix, "POLL_PATH", f"/kling/v1/videos/{endpoint_type}/{{task_id}}")
    result = _poll_task(
        request=request,
        spec=spec,
        task_id=task_id,
        poll_url=poll_url_template or _join_url(root, poll_path.replace("{task_id}", task_id)),
        headers=headers,
        poll_interval=max(1.0, _env_float(prefix, "POLL_INTERVAL_SECONDS", 5.0)),
        timeout_s=timeout_s,
    )
    return _finish_video_result(request, spec, result, headers, ffmpeg=ffmpeg, run_guarded=run_guarded, timeout_s=timeout_s)


def render_remote_video_provider(
    request: VideoRenderRequest,
    spec: VideoProviderSpec,
    *,
    ffmpeg: str | None = None,
    run_guarded: Callable[..., Any] | None = None,
    timeout_s: int = 900,
) -> Path:
    prefix = _provider_prefix(spec)
    api_key = _env_any(prefix, ("API_KEY", "OPENAI_API_KEY"))
    model = _env_any(prefix, ("MODEL", "OPENAI_VIDEO_MODEL"), default="sora-2" if spec.id == "sora" else "")
    base_url = _env_any(
        prefix,
        ("BASE_URL", "OPENAI_BASE_URL"),
        default="https://api.openai.com/v1" if spec.id == "sora" else "",
    ).rstrip("/")
    submit_url = _env_any(prefix, ("SUBMIT_URL", "OPENAI_SUBMIT_PATH"))
    poll_url = _env_any(prefix, ("POLL_URL", "OPENAI_POLL_PATH"))
    content_url = _env_any(prefix, ("CONTENT_URL", "OPENAI_CONTENT_PATH"))
    provider_timeout = int(_env_float(prefix, "TIMEOUT_SECONDS", float(timeout_s)))

    if not api_key:
        raise VideoProviderConfigError(f"{prefix}_API_KEY is required for video provider '{spec.id}'.")
    if not model:
        raise VideoProviderConfigError(f"{prefix}_MODEL is required for video provider '{spec.id}'.")
    if not base_url and not _env(prefix, "SUBMIT_URL"):
        raise VideoProviderConfigError(
            f"{prefix}_BASE_URL is required for video provider '{spec.id}'."
        )

    route = _detect_route(prefix, spec, model)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    _write_debug(
        request.run_dir,
        request.scene,
        f"{spec.id}_route",
        {
            "provider": spec.id,
            "route": route,
            "model": model,
            "base_url": base_url,
            "duration": request.duration,
            "size": [request.width, request.height],
            "fps": request.fps,
            "structured_spec_available": bool(_structured_metadata(request)),
            "structured_spec_mode": _structured_spec_mode(prefix, route),
            "structured_spec_sent": _structured_spec_mode(prefix, route) in {"fields", "both"} and route == "unified",
        },
    )
    metadata = _structured_metadata(request)
    if metadata:
        _write_debug(request.run_dir, request.scene, f"{spec.id}_structured_spec", metadata)

    render_kwargs = {
        "timeout_s": max(timeout_s, provider_timeout),
        "ffmpeg": ffmpeg,
        "run_guarded": run_guarded,
    }
    try:
        if route == "openai_official":
            return _render_openai_official(
                request,
                spec,
                prefix,
                api_key,
                model,
                base_url,
                headers,
                submit_url=submit_url,
                poll_url_template=poll_url,
                content_url_template=content_url,
                **render_kwargs,
            )
        if route == "volc":
            return _render_volc(
                request,
                spec,
                prefix,
                model,
                base_url,
                headers,
                submit_url=submit_url,
                poll_url_template=poll_url,
                **render_kwargs,
            )
        if route == "kling":
            return _render_kling(
                request,
                spec,
                prefix,
                model,
                base_url,
                headers,
                submit_url=submit_url,
                poll_url_template=poll_url,
                **render_kwargs,
            )
        return _render_unified(
            request,
            spec,
            prefix,
            model,
            base_url,
            headers,
            submit_url=submit_url,
            poll_url_template=poll_url,
            **render_kwargs,
        )
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise VideoProviderError(f"{spec.label} {route} request failed: {exc}") from exc
