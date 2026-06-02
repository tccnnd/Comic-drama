"""Shared fixtures for the Comic Drama test suite."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure project root is on sys.path so imports work
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def tmp_workspace(tmp_path):
    """Create a temporary workspace directory and patch WORKSPACE to point to it."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with patch("backend.project_models.WORKSPACE", workspace):
        yield workspace


@pytest.fixture()
def sample_project(tmp_workspace):
    """Create a sample project with scenes and characters inside the temp workspace."""
    project_id = "test_project_001"
    project_root = tmp_workspace / project_id
    project_root.mkdir()
    (project_root / "scenes").mkdir()
    (project_root / "characters").mkdir()
    (project_root / "output").mkdir()

    # Create scene directories
    for i in range(1, 4):
        scene_dir = project_root / "scenes" / f"scene_{i:03d}"
        scene_dir.mkdir()

    project_data = {
        "project_id": project_id,
        "title": "测试漫剧",
        "style_id": "anime_standard",
        "characters": [
            {
                "char_id": "c_001",
                "name": "林晚",
                "meta": {"age": "22", "role": "女主"},
                "appearance_core": "黑色长发，清秀面容",
                "clothing_style": "白色连衣裙",
                "negative_constraints": "",
                "description": "温柔但坚强的女主角",
                "voice_profile": "female_lead",
                "voice_engine": "edge",
                "voice_id": "zh-CN-XiaoxiaoNeural",
                "reference_audio_path": "",
                "reference_text": "",
                "emotion": "",
                "reference_image_path": "",
                "reference_image_url": "",
                "reference_meta": {},
            },
            {
                "char_id": "c_002",
                "name": "陆远",
                "meta": {"age": "28", "role": "男主"},
                "appearance_core": "短发，英俊",
                "clothing_style": "黑色西装",
                "negative_constraints": "",
                "description": "冷酷的总裁",
                "voice_profile": "male_lead",
                "voice_engine": "edge",
                "voice_id": "zh-CN-YunxiNeural",
                "reference_audio_path": "",
                "reference_text": "",
                "emotion": "",
                "reference_image_path": "",
                "reference_image_url": "",
                "reference_meta": {},
            },
        ],
        "scenes": [
            {
                "scene_id": "scene_001",
                "order": 1,
                "title": "初次相遇",
                "visual_prompt": "办公室走廊，两人擦肩而过",
                "dialogue": "林晚：你好，我是新来的实习生。",
                "speaker": "林晚",
                "camera_movement": "slow_push_in",
                "emotion": "neutral",
                "duration_seconds": 4.0,
                "characters": ["林晚", "陆远"],
                "voice_engine": "edge",
                "voice_id": "",
                "voice_rate": 1.0,
                "voice_pitch": 0.0,
                "voice_volume": 1.0,
                "camera_speed": 1.0,
                "sfx_type": "auto",
                "audio_manifest": {
                    "bgm_style": "",
                    "bgm_file": "",
                    "bgm_gain_db": "",
                    "sfx_trigger": {"file": "", "timestamp_ms": 0, "volume": 0.65},
                    "sfx_triggers": [],
                },
                "assets": {
                    "status": "pending",
                    "versions": {"image": 0, "audio": 0, "video": 0},
                    "image_path": "",
                    "image_url": "",
                    "audio_path": "",
                    "audio_url": "",
                    "video_path": "",
                    "video_url": "",
                },
                "history": [],
            },
            {
                "scene_id": "scene_002",
                "order": 2,
                "title": "冲突升级",
                "visual_prompt": "会议室，紧张对峙",
                "dialogue": "陆远：这个方案不行，重做。",
                "speaker": "陆远",
                "camera_movement": "dramatic_push",
                "emotion": "anger",
                "duration_seconds": 5.0,
                "characters": ["林晚", "陆远"],
                "voice_engine": "edge",
                "voice_id": "",
                "voice_rate": 1.0,
                "voice_pitch": 0.0,
                "voice_volume": 1.0,
                "camera_speed": 1.35,
                "sfx_type": "hit",
                "audio_manifest": {
                    "bgm_style": "",
                    "bgm_file": "",
                    "bgm_gain_db": "",
                    "sfx_trigger": {"file": "hit", "timestamp_ms": 1200, "volume": 0.65},
                    "sfx_triggers": [],
                },
                "assets": {
                    "status": "pending",
                    "versions": {"image": 0, "audio": 0, "video": 0},
                    "image_path": "",
                    "image_url": "",
                    "audio_path": "",
                    "audio_url": "",
                    "video_path": "",
                    "video_url": "",
                },
                "history": [],
            },
            {
                "scene_id": "scene_003",
                "order": 3,
                "title": "和解",
                "visual_prompt": "公园长椅，夕阳",
                "dialogue": "林晚：谢谢你今天帮了我。",
                "speaker": "林晚",
                "camera_movement": "melancholy_pan",
                "emotion": "calm",
                "duration_seconds": 6.0,
                "characters": ["林晚"],
                "voice_engine": "edge",
                "voice_id": "",
                "voice_rate": 1.0,
                "voice_pitch": 0.0,
                "voice_volume": 1.0,
                "camera_speed": 0.7,
                "sfx_type": "auto",
                "audio_manifest": {
                    "bgm_style": "",
                    "bgm_file": "",
                    "bgm_gain_db": "",
                    "sfx_trigger": {"file": "", "timestamp_ms": 0, "volume": 0.65},
                    "sfx_triggers": [],
                },
                "assets": {
                    "status": "pending",
                    "versions": {"image": 0, "audio": 0, "video": 0},
                    "image_path": "",
                    "image_url": "",
                    "audio_path": "",
                    "audio_url": "",
                    "video_path": "",
                    "video_url": "",
                },
                "history": [],
            },
        ],
    }

    project_file = project_root / "project.json"
    project_file.write_text(json.dumps(project_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "project_id": project_id,
        "project_root": project_root,
        "project_data": project_data,
        "workspace": tmp_workspace,
    }
