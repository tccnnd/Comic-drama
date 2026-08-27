from __future__ import annotations

import json
import random
import shutil
import time
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFilter

from scripts.rw_models import StoryScene
from backend.config_utils import env_bool, env_float, env_optional_value, env_value
from scripts.rw_config import OUTPUTS, WORKFLOWS
from scripts.rw_ffmpeg import get_ffmpeg_exe, render_timeout, run_guarded
from scripts.rw_utils import load_json, replace_placeholders, unresolved_placeholders, write_debug_json
from scripts.rw_image import create_keyframe
from scripts.rw_prompts import (
    ANIME_NEGATIVE_PROMPT_EXTRA,
    anime_video_prompt,
    anime_visual_prompt,
    build_scene_video_prompts,
    clean_comfyui_visual_prompt,
    infer_character_appearance_hint,
    scene_consistency_spec,
    temporal_spec_prompt_lines,
)
from scripts.rw_planning import build_scene_temporal_spec
from scripts.comfyui_patcher import patch_workflow
from scripts.comfyui_ssh_tunnel import ensure_comfyui_tunnel
from scripts.prompt_compiler import PromptCompiler, find_project_root
from video_providers import normalize_video_provider as resolve_video_provider_name


COMFYUI_STYLE_PRESETS = {
    "anime_fallback": {
        "positive_suffix": "anime style, cel shading, manga style, flat color, 2d illustration, clean lineart, expressive anime character acting",
        "negative_suffix": "photorealistic, realistic skin, dslr, photograph, live action, 3d render, cgi, skin pores",
    },
    "anime_v5": {
        "positive_suffix": "",
        "negative_suffix": "",
    },
}


def comfyui_style_preset() -> dict[str, str]:
    preset_name = env_value("COMFYUI_STYLE_PRESET", default="").strip().lower()
    preset = COMFYUI_STYLE_PRESETS.get(preset_name)
    return preset if preset is not None else {"positive_suffix": "", "negative_suffix": ""}


def append_prompt_suffix(text: str, suffix: str) -> str:
    clean_text = str(text or "").strip()
    clean_suffix = str(suffix or "").strip()
    if clean_text and clean_suffix:
        return f"{clean_text}, {clean_suffix}"
    return clean_text or clean_suffix


def inject_comfyui_workflow(
    template: object,
    *,
    checkpoint_name: str,
    lora_name: str,
    style_preset: dict[str, str] | None = None,
) -> dict:
    if not isinstance(template, dict):
        raise ValueError("ComfyUI workflow template must be a JSON object.")
    checkpoint_name = str(checkpoint_name or "").strip()
    if not checkpoint_name:
        raise ValueError("COMFYUI_CHECKPOINT_NAME / COMFYUI_VIDEO_CHECKPOINT_NAME is required for ComfyUI rendering.")

    graph = deepcopy(template)
    checkpoint_node_id: str | None = None
    lora_node_id: str | None = None

    for node_id, node in graph.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        class_type = node.get("class_type")
        if class_type == "CheckpointLoaderSimple":
            checkpoint_node_id = str(node_id)
            inputs["ckpt_name"] = checkpoint_name
        elif class_type == "UNETLoader":
            checkpoint_node_id = str(node_id)
            inputs["unet_name"] = checkpoint_name
        elif class_type == "LoraLoader":
            lora_node_id = str(node_id)

    if checkpoint_node_id is None:
        raise ValueError("ComfyUI workflow is missing CheckpointLoaderSimple or UNETLoader.")

    if lora_node_id and not str(lora_name or "").strip():
        for node in graph.values():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs")
            if not isinstance(inputs, dict):
                continue
            for input_name, input_value in list(inputs.items()):
                if (
                    isinstance(input_value, list)
                    and len(input_value) == 2
                    and str(input_value[0]) == lora_node_id
                ):
                    inputs[input_name] = [checkpoint_node_id, input_value[1]]
        del graph[lora_node_id]
    elif lora_node_id:
        lora_node = graph.get(lora_node_id)
        if isinstance(lora_node, dict) and isinstance(lora_node.get("inputs"), dict):
            lora_node["inputs"]["lora_name"] = str(lora_name or "").strip()

    preset = style_preset or {}
    positive_suffix = str(preset.get("positive_suffix") or "").strip()
    negative_suffix = str(preset.get("negative_suffix") or "").strip()
    if positive_suffix or negative_suffix:
        for node in graph.values():
            if not isinstance(node, dict) or node.get("class_type") != "CLIPTextEncode":
                continue
            inputs = node.get("inputs")
            if not isinstance(inputs, dict):
                continue
            text = inputs.get("text")
            if not isinstance(text, str):
                continue
            if "__NEGATIVE__" in text:
                inputs["text"] = append_prompt_suffix(text, negative_suffix)
            else:
                inputs["text"] = append_prompt_suffix(text, positive_suffix)

    return graph


def comfyui_base_url() -> str:
    tunnel_url = ensure_comfyui_tunnel()
    if tunnel_url:
        return tunnel_url.rstrip("/")
    return env_value("COMFYUI_BASE_URL", "COMFYUI_URL", default="http://127.0.0.1:8188").rstrip("/")


def comfyui_auth_headers() -> dict[str, str]:
    raw = env_value("COMFYUI_AUTH_HEADER", default="").strip()
    if raw and ":" in raw:
        key, value = raw.split(":", 1)
        return {key.strip(): value.strip()}
    api_key = env_value("COMFYUI_API_KEY", default="").strip()
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def comfyui_workflow_path() -> Path:
    raw = env_value("COMFYUI_WORKFLOW_PATH", default=str(WORKFLOWS / "comfyui_keyframe_template.json"))
    return Path(raw)


def comfyui_video_workflow_path() -> Path:
    raw = env_value("COMFYUI_VIDEO_WORKFLOW_PATH", "VIDEO_WORKFLOW_PATH", default=str(WORKFLOWS / "comfyui_video_template.json"))
    return Path(raw)


def comfyui_input_dir() -> Path | None:
    raw = env_value("COMFYUI_INPUT_DIR", default="").strip()
    return Path(raw) if raw else None


def comfyui_reference_mode() -> str:
    return env_value("COMFYUI_REFERENCE_MODE", default="auto").strip().lower() or "auto"


def comfyui_is_local() -> bool:
    parsed = urlparse(comfyui_base_url())
    return parsed.hostname in {"127.0.0.1", "localhost", "::1", None}


def default_comfyui_reference_image_path() -> Path:
    return OUTPUTS / "comfyui_default_reference.png"


def ensure_default_comfyui_reference_image() -> Path:
    path = default_comfyui_reference_image_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    size = (512, 768)
    base = Image.new("RGBA", size, (28, 24, 32, 255))
    draw = ImageDraw.Draw(base, "RGBA")

    for y in range(size[1]):
        blend = y / max(1, size[1] - 1)
        r = int(28 + 38 * blend)
        g = int(24 + 20 * blend)
        b = int(32 + 24 * blend)
        draw.line((0, y, size[0], y), fill=(r, g, b, 255))

    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow, "RGBA")
    glow_draw.ellipse((44, 64, 468, 724), fill=(92, 124, 160, 60))
    glow_draw.ellipse((108, 116, 404, 660), fill=(38, 48, 70, 110))
    glow = glow.filter(ImageFilter.GaussianBlur(44))
    base = Image.alpha_composite(base, glow)
    draw = ImageDraw.Draw(base, "RGBA")

    draw.ellipse((158, 146, 354, 366), fill=(202, 176, 158, 255))
    draw.polygon([(158, 166), (182, 122), (234, 94), (286, 92), (334, 120), (356, 168), (350, 206), (322, 182), (288, 170), (228, 170), (190, 182)], fill=(16, 16, 20, 255))
    draw.polygon([(168, 204), (178, 294), (170, 388), (184, 456), (214, 510), (236, 548), (144, 534), (126, 398), (134, 282)], fill=(16, 16, 20, 240))
    draw.polygon([(344, 204), (334, 294), (342, 388), (328, 456), (298, 510), (276, 548), (368, 534), (386, 398), (378, 282)], fill=(16, 16, 20, 240))
    draw.polygon([(174, 136), (202, 108), (230, 96), (258, 92), (290, 98), (318, 118), (300, 134), (270, 126), (236, 124), (198, 132)], fill=(10, 10, 14, 255))
    draw.polygon([(140, 154), (154, 214), (138, 266), (126, 230), (122, 182)], fill=(10, 10, 14, 220))
    draw.polygon([(374, 154), (360, 214), (376, 266), (388, 230), (392, 182)], fill=(10, 10, 14, 220))

    draw.arc((194, 210, 242, 238), start=180, end=360, fill=(50, 38, 30, 255), width=4)
    draw.arc((268, 210, 316, 238), start=180, end=360, fill=(50, 38, 30, 255), width=4)
    draw.line((238, 258, 246, 298), fill=(116, 84, 76, 180), width=3)
    draw.line((218, 318, 286, 318), fill=(88, 52, 60, 190), width=4)
    draw.line((182, 224, 206, 220), fill=(48, 34, 32, 180), width=4)
    draw.line((306, 220, 330, 224), fill=(48, 34, 32, 180), width=4)
    draw.line((196, 286, 184, 302), fill=(122, 86, 82, 140), width=2)
    draw.line((304, 286, 316, 302), fill=(122, 86, 82, 140), width=2)
    draw.ellipse((166, 252, 182, 262), fill=(120, 74, 76, 68))
    draw.ellipse((330, 252, 346, 262), fill=(120, 74, 76, 68))

    robe = [(94, 620), (160, 444), (206, 384), (256, 404), (306, 384), (354, 444), (418, 620), (392, 748), (120, 748)]
    draw.polygon(robe, fill=(92, 96, 104, 255))
    collar = [(194, 394), (256, 452), (318, 394), (344, 426), (256, 506), (168, 426)]
    draw.polygon(collar, fill=(176, 172, 160, 255))
    draw.polygon([(206, 458), (256, 540), (304, 458), (332, 468), (286, 572), (226, 572), (180, 468)], fill=(64, 68, 76, 255))

    for x in range(4):
        draw.line((126 + x * 24, 560, 378 - x * 20, 726), fill=(46, 50, 58, 120), width=3)

    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow, "RGBA")
    shadow_draw.ellipse((104, 130, 410, 420), fill=(0, 0, 0, 42))
    shadow_draw.ellipse((140, 410, 372, 754), fill=(0, 0, 0, 64))
    shadow = shadow.filter(ImageFilter.GaussianBlur(28))
    base = Image.alpha_composite(base, shadow)

    draw = ImageDraw.Draw(base, "RGBA")
    draw.ellipse((204, 226, 228, 246), fill=(30, 24, 28, 255))
    draw.ellipse((284, 226, 308, 246), fill=(30, 24, 28, 255))
    draw.line((226, 250, 246, 258), fill=(108, 76, 68, 180), width=2)
    draw.line((282, 250, 302, 258), fill=(108, 76, 68, 180), width=2)
    base.convert("RGB").save(path, quality=95)
    return path


def comfyui_upload_image(source: Path, *, subfolder: str = "comicdrama_refs") -> dict[str, str]:
    boundary = f"----comicdrama{random.randint(100000000, 999999999)}"
    filename = source.name
    content_type = "image/png"
    if source.suffix.lower() in {".jpg", ".jpeg"}:
        content_type = "image/jpeg"
    elif source.suffix.lower() == ".webp":
        content_type = "image/webp"
    image_bytes = source.read_bytes()

    def form_field(name: str, value: str) -> bytes:
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode("utf-8")

    body = bytearray()
    body.extend(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
    )
    body.extend(image_bytes)
    body.extend(b"\r\n")
    body.extend(form_field("type", "input"))
    body.extend(form_field("subfolder", subfolder))
    body.extend(form_field("overwrite", "true"))
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

    request = Request(
        f"{comfyui_base_url()}/upload/image",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", **comfyui_auth_headers()},
        method="POST",
    )
    try:
        with urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ComfyUI image upload failed with HTTP {exc.code}: {body_text}") from exc

    name = str(payload.get("name") or filename)
    remote_subfolder = str(payload.get("subfolder") or subfolder).strip("/")
    load_name = f"{remote_subfolder}/{name}" if remote_subfolder else name
    return {"source": str(source), "load_image": load_name, "absolute": load_name}


def prepare_comfyui_reference_image(scene: StoryScene) -> dict[str, str]:
    raw_path = (scene.primary_reference_image_abs_path or scene.primary_reference_image_path or "").strip()
    placeholder = False
    if not raw_path:
        source = ensure_default_comfyui_reference_image()
        placeholder = True
    else:
        source = Path(raw_path)
        if not source.is_file():
            source = ensure_default_comfyui_reference_image()
            placeholder = True

    absolute = str(source.resolve())
    mode = comfyui_reference_mode()
    if mode == "upload" or (mode == "auto" and not comfyui_is_local()):
        uploaded = comfyui_upload_image(source)
        uploaded["placeholder"] = placeholder
        return uploaded
    if mode == "absolute":
        return {"source": raw_path or "__generated_default_reference__", "load_image": absolute, "absolute": absolute, "placeholder": placeholder}

    input_dir = comfyui_input_dir()
    if not input_dir:
        if mode == "auto" and not comfyui_is_local():
            uploaded = comfyui_upload_image(source)
            uploaded["placeholder"] = placeholder
            return uploaded
        return {"source": raw_path or "__generated_default_reference__", "load_image": absolute, "absolute": absolute, "placeholder": placeholder}

    target_dir = input_dir / "comicdrama_refs"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_name = f"scene_{scene.scene:02}_{source.stem}{source.suffix.lower() or '.png'}"
    target = target_dir / target_name
    shutil.copy2(source, target)
    load_name = f"comicdrama_refs/{target.name}"
    return {"source": raw_path or "__generated_default_reference__", "load_image": load_name, "absolute": str(target.resolve()), "placeholder": placeholder}


def _build_consistency_meta(scene: StoryScene, reference_info: dict[str, str], ip_adapter_weight: float) -> dict[str, Any]:
    primary_meta = scene.primary_reference_meta if isinstance(scene.primary_reference_meta, dict) else {}
    warnings = [str(item) for item in (primary_meta.get("warnings") or []) if str(item).strip()]
    placeholder = bool(reference_info.get("placeholder"))
    if placeholder:
        warnings.append("使用占位参考图，IPAdapter 权重已降级")

    load_image = str(reference_info.get("load_image") or "").strip() or None
    source_value = str(reference_info.get("source") or reference_info.get("absolute") or "").strip()
    reference_path = source_value if source_value and Path(source_value).exists() else None
    absolute = bool(load_image and Path(load_image).is_absolute())

    return {
        "reference_path": reference_path,
        "load_image": load_image,
        "absolute": absolute,
        "placeholder": placeholder,
        "crop_method": primary_meta.get("crop_method"),
        "ip_adapter_weight": ip_adapter_weight,
        "warnings": warnings,
        "errors": [],
        "injected_at": time.time(),
    }


def _initial_consistency_meta(scene: StoryScene) -> dict[str, Any]:
    primary_meta = scene.primary_reference_meta if isinstance(scene.primary_reference_meta, dict) else {}
    warnings = [str(item) for item in (primary_meta.get("warnings") or []) if str(item).strip()]
    reference_path = None
    raw_abs = str(scene.primary_reference_image_abs_path or "").strip()
    raw_rel = str(scene.primary_reference_image_path or "").strip()
    if raw_abs and Path(raw_abs).is_file():
        reference_path = str(Path(raw_abs).resolve())
    elif raw_rel and Path(raw_rel).is_file():
        reference_path = str(Path(raw_rel).resolve())

    return {
        "reference_path": reference_path,
        "load_image": None,
        "absolute": False,
        "placeholder": True,
        "crop_method": primary_meta.get("crop_method"),
        "ip_adapter_weight": None,
        "warnings": warnings,
        "errors": [],
        "injected_at": time.time(),
    }


def submit_comfyui_prompt(workflow: dict, prompt_id: str, client_id: str) -> dict:
    payload = {
        "prompt": workflow,
        "client_id": client_id,
        "prompt_id": prompt_id,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    url = f"{comfyui_base_url()}/prompt"
    request = Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    for k, v in comfyui_auth_headers().items():
        request.add_header(k, v)
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ComfyUI /prompt failed with HTTP {exc.code}: {body}") from exc


def poll_comfyui_history(prompt_id: str, timeout_s: int = 300) -> dict:
    deadline = time.time() + timeout_s
    url = f"{comfyui_base_url()}/history/{prompt_id}"
    while time.time() < deadline:
        try:
            req = Request(url)
            for k, v in comfyui_auth_headers().items():
                req.add_header(k, v)
            with urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if prompt_id in payload:
                return payload[prompt_id]
        except Exception:
            pass
        time.sleep(2)
    raise TimeoutError(f"Timed out waiting for ComfyUI prompt {prompt_id}")


def download_comfyui_image(image_info: dict, out_path: Path) -> None:
    from urllib.parse import urlencode

    query = {
        "filename": image_info["filename"],
        "subfolder": image_info.get("subfolder", ""),
        "type": image_info.get("type", "output"),
    }
    url = f"{comfyui_base_url()}/view?{urlencode(query)}"
    req = Request(url)
    for k, v in comfyui_auth_headers().items():
        req.add_header(k, v)
    with urlopen(req, timeout=60) as response:
        out_path.write_bytes(response.read())


def download_comfyui_asset(asset_info: dict, out_path: Path) -> None:
    from urllib.parse import urlencode

    query = {
        "filename": asset_info["filename"],
        "subfolder": asset_info.get("subfolder", ""),
        "type": asset_info.get("type", "output"),
    }
    url = f"{comfyui_base_url()}/view?{urlencode(query)}"
    req = Request(url)
    for k, v in comfyui_auth_headers().items():
        req.add_header(k, v)
    with urlopen(req, timeout=60) as response:
        out_path.write_bytes(response.read())


def render_scene_video_comfyui(scene: StoryScene, keyframe_path: Path, duration: float, out_path: Path, run_dir: Path) -> Path:
    workflow_path = comfyui_video_workflow_path()
    if not workflow_path.exists():
        raise FileNotFoundError(f"ComfyUI video workflow template not found: {workflow_path}")

    run_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = run_dir / "debug"
    prompt_text, negative_text = build_scene_video_prompts(scene, duration, run_dir)
    temporal_spec = scene.temporal_spec or build_scene_temporal_spec(
        scene,
        duration,
        width=int(env_float("VIDEO_WIDTH", default=1080)),
        height=int(env_float("VIDEO_HEIGHT", default=1920)),
        fps=int(env_float("VIDEO_FPS", default=24)),
    )
    consistency_spec = scene_consistency_spec(scene)

    workflow = load_json(workflow_path)
    prompt_id = f"comicdrama-video-{scene.scene:02}-{int(time.time() * 1000)}"
    client_id = f"client-{random.randint(100000, 999999)}"
    keyframe_info = comfyui_upload_image(keyframe_path)
    replacements = {
        "__PROMPT__": prompt_text,
        "__NEGATIVE__": negative_text,
        "__SEED__": scene.scene * 20011 + 97,
        "__WIDTH__": int(env_float("VIDEO_WIDTH", default=1080)),
        "__HEIGHT__": int(env_float("VIDEO_HEIGHT", default=1920)),
        "__STEPS__": int(env_float("VIDEO_STEPS", default=18)),
        "__CFG__": env_float("VIDEO_CFG", default=6.5),
        "__DURATION__": float(duration),
        "__DURATION_SECONDS__": float(duration),
        "__FPS__": int(env_float("VIDEO_FPS", default=24)),
        "__PRIMARY_REFERENCE_IMAGE__": keyframe_info["load_image"],
        "__REFERENCE_IMAGE__": keyframe_info["load_image"],
        "__KEYFRAME_IMAGE__": keyframe_info["load_image"],
        "__SCENE_TITLE__": scene.title,
        "__SCENE_DIALOGUE__": scene.dialogue,
        "__SCENE_CAMERA__": scene.camera,
        "__SCENE_EMOTION__": scene.emotion,
        "__CHARACTER_DESCRIPTIONS__": scene.character_descriptions,
        "__VIDEO_CHECKPOINT_NAME__": comfyui_checkpoint_name(),
        "__VIDEO_LORA_NAME__": comfyui_lora_name(),
        "__VIDEO_LORA_STRENGTH_MODEL__": env_float("COMFYUI_VIDEO_LORA_STRENGTH_MODEL", default=0.7),
        "__VIDEO_LORA_STRENGTH_CLIP__": env_float("COMFYUI_VIDEO_LORA_STRENGTH_CLIP", default=0.7),
        "__VIDEO_IP_ADAPTER_WEIGHT__": env_float("COMFYUI_VIDEO_IP_ADAPTER_WEIGHT", default=0.65),
    }
    injected = replace_placeholders(workflow, replacements)
    if not isinstance(injected, dict):
        raise ValueError("ComfyUI video workflow template must resolve to a JSON object.")
    unresolved = unresolved_placeholders(injected)
    if unresolved:
        write_debug_json(debug_dir / f"scene_{scene.scene:02}_video_unresolved.json", unresolved)
        raise ValueError(f"ComfyUI video workflow has unresolved placeholders: {', '.join(unresolved[:5])}")

    write_debug_json(
        debug_dir / f"scene_{scene.scene:02}_video_request_meta.json",
        {
            "scene": scene.scene,
            "title": scene.title,
            "base_url": comfyui_base_url(),
            "workflow_path": str(workflow_path),
            "prompt_id": prompt_id,
            "client_id": client_id,
            "keyframe_info": keyframe_info,
            "duration": duration,
            "prompt_text": prompt_text,
            "temporal_spec": temporal_spec,
            "consistency_spec": consistency_spec,
        },
    )
    write_debug_json(debug_dir / f"scene_{scene.scene:02}_video_filled_workflow.json", injected)

    try:
        submit_response = submit_comfyui_prompt(injected, prompt_id, client_id)
        write_debug_json(debug_dir / f"scene_{scene.scene:02}_video_submit_response.json", submit_response)
        prompt_id = str(submit_response.get("prompt_id", prompt_id))
        history = poll_comfyui_history(prompt_id, timeout_s=max(300, int(max(30.0, duration) * 60)))
        write_debug_json(debug_dir / f"scene_{scene.scene:02}_video_history.json", history)
        status = history.get("status", {})
        status_str = str(status.get("status_str") or "").lower()
        completed = status.get("completed")
        if completed is False or status_str in {"error", "failed", "failure"}:
            raise RuntimeError(f"ComfyUI video workflow failed: {json.dumps(status, ensure_ascii=False)}")
    except Exception as exc:
        raise RuntimeError(f"ComfyUI video generation failed: {exc}") from exc

    outputs = history.get("outputs", {})
    for node_id, node_output in outputs.items():
        for field in ("videos", "gifs"):
            items = node_output.get(field) or []
            if not items:
                continue
            asset_info = items[0]
            filename = str(asset_info.get("filename") or "")
            suffix = Path(filename).suffix.lower() or ".mp4"
            download_path = out_path if suffix == out_path.suffix.lower() else out_path.with_name(f"{out_path.stem}_source{suffix}")
            download_comfyui_asset(asset_info, download_path)
            if download_path != out_path:
                ffmpeg = get_ffmpeg_exe()
                run_guarded(
                    [
                        ffmpeg,
                        "-y",
                        "-i",
                        str(download_path),
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
                    cwd=run_dir,
                    timeout=render_timeout(duration) + 300,
                    stage="ffmpeg_transcode_comfyui_video",
                )
            write_debug_json(
                debug_dir / f"scene_{scene.scene:02}_video_downloaded_asset.json",
                {"node_id": node_id, "field": field, "asset": asset_info, "output_path": str(out_path)},
            )
            return out_path

    raise RuntimeError(f"ComfyUI video workflow completed but returned no video media. Debug: {debug_dir}")


def render_keyframe_comfyui(scene: StoryScene, run_dir: Path) -> Path:
    workflow_path = comfyui_workflow_path()
    if not workflow_path.exists():
        raise FileNotFoundError(f"ComfyUI workflow template not found: {workflow_path}")
    run_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = run_dir / "debug"

    # Quality prefix for better keyframe generation
    quality_prefix = "masterpiece, best quality, full color, vibrant colors, digital painting, colored, highly detailed"

    prompt_parts = [quality_prefix, clean_comfyui_visual_prompt(scene.visual)]
    prompt_parts.append(infer_character_appearance_hint(scene))
    if scene.character_prompt_compilation:
        prompt_parts.append(scene.character_prompt_compilation)
    if scene.character_descriptions:
        prompt_parts.append(scene.character_descriptions)
    # Add composition tags
    prompt_parts.append("cinematic composition, dramatic lighting")
    prompt_text = anime_visual_prompt(
        ", ".join(part for part in prompt_parts if part),
        title=scene.title,
        characters=scene.characters,
        camera=scene.camera,
        emotion=scene.emotion,
    )
    project_root = find_project_root(run_dir)
    if project_root is not None:
        compiler = PromptCompiler(project_root)
        prompt_source_parts = [clean_comfyui_visual_prompt(scene.visual)]
        if scene.character_prompt_compilation:
            prompt_source_parts.append(str(scene.character_prompt_compilation).strip())
        if scene.character_descriptions:
            prompt_source_parts.append(scene.character_descriptions)
        compiled = compiler.compile(
            ", ".join(part for part in prompt_source_parts if part),
            list(scene.characters or []),
            speaker=scene.speaker,
        )
        # Prepend quality tags to compiled output
        compiled_with_quality = ", ".join(
            part for part in [quality_prefix, compiled.positive, "cinematic composition, dramatic lighting"] if str(part).strip()
        )
        prompt_text = anime_visual_prompt(
            compiled_with_quality,
            title=scene.title,
            characters=scene.characters,
            camera=scene.camera,
            emotion=scene.emotion,
        )
    references_json = json.dumps(scene.character_references or [], ensure_ascii=False)
    scene.consistency_meta = _initial_consistency_meta(scene)
    try:
        reference_info = prepare_comfyui_reference_image(scene)
    except Exception as exc:
        scene.consistency_meta.setdefault("errors", []).append(str(exc))
        raise
    workflow = load_json(workflow_path)
    prompt_id = f"comicdrama-{scene.scene:02}-{int(time.time() * 1000)}"
    client_id = f"client-{random.randint(100000, 999999)}"
    ip_adapter_weight = env_float("COMFYUI_IP_ADAPTER_WEIGHT", default=0.65)
    if reference_info.get("placeholder"):
        ip_adapter_weight = min(ip_adapter_weight, env_float("COMFYUI_PLACEHOLDER_IP_ADAPTER_WEIGHT", default=0.0))
    checkpoint_name = comfyui_checkpoint_name()
    lora_name = comfyui_lora_name()
    style_preset = comfyui_style_preset()
    replacements = {
        "__PROMPT__": prompt_text,
        "__NEGATIVE__": ", ".join(
            part
            for part in [
                "worst quality, low quality, normal quality",
                ANIME_NEGATIVE_PROMPT_EXTRA,
                "bad anatomy, bad hands, extra fingers, fewer fingers, extra limbs, deformed, disfigured, watermark, text, signature",
                scene.negative_prompt_compilation,
            ]
            if part
        ),
        "__SEED__": scene.scene * 10007,
        "__WIDTH__": int(env_float("COMFYUI_WIDTH", default=1080)),
        "__HEIGHT__": int(env_float("COMFYUI_HEIGHT", default=1920)),
        "__STEPS__": int(env_float("COMFYUI_STEPS", default=20)),
        "__CFG__": env_float("COMFYUI_CFG", default=7.0),
        "__TITLE__": scene.title,
        "__VISUAL__": prompt_text,
        "__DIALOGUE__": scene.dialogue,
        "__CHARACTER_DESCRIPTIONS__": scene.character_descriptions,
        "__REFERENCE_IMAGE_PATHS_JSON__": references_json,
        "__PRIMARY_REFERENCE_IMAGE__": reference_info["load_image"],
        "__PRIMARY_REFERENCE_IMAGE_ABS__": reference_info["absolute"],
        "__PRIMARY_REFERENCE_SOURCE__": reference_info["source"],
        "__IP_ADAPTER_IMAGE__": reference_info["load_image"],
        "__FACEID_IMAGE__": reference_info["load_image"],
        "__FACEID_LORA_STRENGTH__": env_float("COMFYUI_FACEID_LORA_STRENGTH", default=0.6),
        "__IP_ADAPTER_WEIGHT__": ip_adapter_weight,
        "__FACEID_WEIGHT__": env_float("COMFYUI_FACEID_WEIGHT", default=2.0),
        "__LORA_NAME__": lora_name,
        "__LORA_STRENGTH_MODEL__": env_float("COMFYUI_LORA_STRENGTH_MODEL", default=0.8),
        "__LORA_STRENGTH_CLIP__": env_float("COMFYUI_LORA_STRENGTH_CLIP", default=0.8),
        "__CHARACTER_COUNT__": len(scene.character_references or []),
    }
    scene.consistency_meta = _build_consistency_meta(scene, reference_info, ip_adapter_weight)
    workflow = patch_workflow(
        workflow,
        positive_prompt="__PROMPT__\n__CHARACTER_DESCRIPTIONS__",
        negative_prompt="blurry, noisy, messy, lowres, jpeg, artifacts, ill, distorted, malformed, watermark, __NEGATIVE__",
        reference_image_filename="__PRIMARY_REFERENCE_IMAGE__",
        ipadapter_weight=ip_adapter_weight,
    )
    injected = inject_comfyui_workflow(
        workflow,
        checkpoint_name=checkpoint_name,
        lora_name=lora_name,
        style_preset=style_preset,
    )
    filled = replace_placeholders(injected, replacements)
    if not isinstance(filled, dict):
        raise ValueError("ComfyUI workflow template must resolve to a JSON object.")
    unresolved = unresolved_placeholders(filled)
    if unresolved:
        write_debug_json(debug_dir / f"scene_{scene.scene:02}_comfyui_unresolved.json", unresolved)
        raise ValueError(f"ComfyUI workflow has unresolved placeholders: {', '.join(unresolved[:5])}")

    write_debug_json(
        debug_dir / f"scene_{scene.scene:02}_comfyui_request_meta.json",
        {
            "scene": scene.scene,
            "title": scene.title,
            "base_url": comfyui_base_url(),
            "workflow_path": str(workflow_path),
            "prompt_id": prompt_id,
            "client_id": client_id,
            "reference_info": reference_info,
            "ip_adapter_weight": ip_adapter_weight,
            "checkpoint_name": checkpoint_name,
            "lora_name": lora_name,
            "style_preset": env_value("COMFYUI_STYLE_PRESET", default=""),
            "prompt_text": prompt_text,
        },
    )
    write_debug_json(debug_dir / f"scene_{scene.scene:02}_filled_workflow.json", filled)

    try:
        submit_response = submit_comfyui_prompt(filled, prompt_id, client_id)
        write_debug_json(debug_dir / f"scene_{scene.scene:02}_submit_response.json", submit_response)
        prompt_id = str(submit_response.get("prompt_id", prompt_id))
        history = poll_comfyui_history(prompt_id)
        write_debug_json(debug_dir / f"scene_{scene.scene:02}_history.json", history)
        status = history.get("status", {})
        status_str = str(status.get("status_str") or "").lower()
        completed = status.get("completed")
        if completed is False or status_str in {"error", "failed", "failure"}:
            raise RuntimeError(f"ComfyUI workflow failed: {json.dumps(status, ensure_ascii=False)}")
    except Exception as exc:
        if isinstance(scene.consistency_meta, dict):
            errors = scene.consistency_meta.setdefault("errors", [])
            if str(exc) not in errors:
                errors.append(str(exc))
        raise

    outputs = history.get("outputs", {})
    save_image_node_ids = [
        node_id
        for node_id, node in filled.items()
        if isinstance(node, dict) and node.get("class_type") == "SaveImage"
    ]
    ordered_node_ids = save_image_node_ids + [node_id for node_id in outputs.keys() if node_id not in save_image_node_ids]
    for node_id in ordered_node_ids:
        node_output = outputs.get(node_id, {})
        images = node_output.get("images") or []
        if images:
            out = run_dir / f"scene_{scene.scene:02}_keyframe.png"
            download_comfyui_image(images[0], out)
            write_debug_json(
                debug_dir / f"scene_{scene.scene:02}_downloaded_image.json",
                {"node_id": node_id, "image": images[0], "output_path": str(out)},
            )
            return out
    raise RuntimeError(f"ComfyUI workflow completed but returned no images. Debug: {debug_dir}")


def generate_keyframe(scene: StoryScene, run_dir: Path, provider: str) -> Path:
    provider = (provider or "auto").strip().lower()
    if provider == "local":
        return create_keyframe(scene, run_dir)
    if provider == "comfyui":
        return render_keyframe_comfyui(scene, run_dir)
    if provider == "cloud":
        return _generate_keyframe_cloud(scene, run_dir)
    # Auto mode: try ComfyUI -> cloud -> local
    try:
        return render_keyframe_comfyui(scene, run_dir)
    except Exception as exc:
        if isinstance(scene.consistency_meta, dict):
            errors = scene.consistency_meta.setdefault("errors", [])
            if str(exc) not in errors:
                errors.append(str(exc))
        if env_bool("COMFYUI_STRICT", "KEYFRAME_STRICT", default=False):
            raise
        print(f"[keyframe] ComfyUI unavailable, trying cloud provider: {exc}")
        # Try cloud text-to-image
        try:
            return _generate_keyframe_cloud(scene, run_dir)
        except Exception as cloud_exc:
            print(f"[keyframe] Cloud provider also failed: {cloud_exc}")
            if isinstance(scene.consistency_meta, dict):
                scene.consistency_meta.setdefault("fallback_used", "local_keyframe")
            print("[keyframe] Falling back to local renderer")
            return create_keyframe(scene, run_dir)


def _generate_keyframe_cloud(scene: StoryScene, run_dir: Path) -> Path:
    """Generate keyframe via cloud text-to-image API."""
    from backend.keyframe_providers import generate_keyframe_dashscope, build_keyframe_prompt

    # Build character info for prompt
    characters: list[dict] = []
    for ref in (scene.character_references or []) if hasattr(scene, "character_references") else []:
        if isinstance(ref, dict):
            characters.append(ref)

    # Build prompt
    positive, negative = build_keyframe_prompt(
        scene.visual,
        characters,
        style_suffix=scene.character_prompt_compilation or "",
    )

    scene_id = f"{scene.scene:02}"
    output_path = run_dir / f"scene_{scene_id}_keyframe.png"
    width = int(env_float("COMFYUI_WIDTH", default=832))
    height = int(env_float("COMFYUI_HEIGHT", default=1216))

    result = generate_keyframe_dashscope(
        prompt=positive,
        negative_prompt=negative,
        width=width,
        height=height,
        output_path=output_path,
    )
    if result and result.exists():
        return result
    raise RuntimeError("Cloud keyframe generation failed or returned no image")


def normalize_video_provider(provider: str | None = None) -> str:
    return resolve_video_provider_name(provider)


def comfyui_checkpoint_name() -> str:
    return env_value("COMFYUI_CHECKPOINT_NAME", "COMFYUI_VIDEO_CHECKPOINT_NAME", default="")


def comfyui_lora_name() -> str:
    return env_optional_value("COMFYUI_LORA_NAME", default=env_optional_value("COMFYUI_VIDEO_LORA_NAME", default=""))
