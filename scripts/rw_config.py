from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STORY = ROOT / "inputs" / "sample_story.txt"
OUTPUTS = ROOT / "outputs"
WORKFLOWS = ROOT / "workflows"
AUDIO_ASSETS = ROOT / "assets" / "audio"
AUDIO_ASSET_EXTENSIONS = (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg")
DEFAULT_PALETTE = [
    ("0x182033", "0x4ea3ff"),
    ("0x211a2e", "0xb879ff"),
    ("0x2a2420", "0xffb347"),
    ("0x14291f", "0x43d18d"),
    ("0x2b1d25", "0xff5d8f"),
    ("0x1d2430", "0xffd166"),
    ("0x102824", "0x2dd4bf"),
    ("0x271a1a", "0xff6b6b"),
]

DEFAULT_SUBTITLE_STYLE = {
    "font_name": "Microsoft YaHei",
    "font_size": 34,
    "margin_v": 120,
    "outline": 2,
    "shadow": 0,
    "alignment": 2,
    "show_speaker": True,
    "burn_in": True,
}

DEFAULT_AUDIO_STYLE = {
    "master_lufs": -16.0,
    "true_peak": -1.5,
    "loudness_range": 11.0,
    "limiter_level": 0.98,
    "bgm_path": "",
    "bgm_gain_db": -18.0,
    "duck_threshold": 0.08,
    "duck_ratio": 8.0,
    "duck_attack_ms": 20,
    "duck_release_ms": 250,
}
DEFAULT_AUDIO_MANIFEST = {
    "bgm_style": "",
    "bgm_file": "",
    "bgm_gain_db": "",
    "sfx_trigger": {"file": "", "timestamp_ms": 0, "volume": 0.65},
    "sfx_triggers": [],
}
DEFAULT_CROP_BOX = {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}
MIN_CROP_BOX_SIZE = 0.05

EPISODE_PHASES = ("opening", "setup", "reversal", "finale")
DEFAULT_EPISODE_PACING = {
    "preset": "classic_four_act",
    "auto_assign": True,
    "phase_order": list(EPISODE_PHASES),
}

DEFAULT_SUBPROCESS_TIMEOUTS = {
    "ffprobe": 15,
    "tts": 90,
    "ffmpeg_audio": 60,
    "ffmpeg_render": 180,
    "ffmpeg_concat": 300,
    "comfyui": 180,
}

DEFAULT_VOICE_PRESETS = {
    "default": "zh-CN-XiaoxiaoNeural",
    "voice_map": {
        "narrator": "zh-CN-YunxiNeural",
        "female_lead": "zh-CN-XiaoxiaoNeural",
        "male_lead": "zh-CN-YunxiNeural",
        "antagonist": "zh-CN-YunjianNeural",
        "host": "zh-CN-YunyangNeural",
        "child": "zh-CN-XiaobeiNeural",
    },
}

SCRIPT_HEADING_RE = re.compile(
    r"^\s*(?:第\s*)?(?P<index>\d{1,3})\s*(?:场|幕|节|scene)\s*[:：.\-、]?\s*(?P<title>.*)$",
    re.IGNORECASE,
)
SCRIPT_SCENE_MARKERS = ("场景", "镜头", "Scene", "scene", "第", "#")
SCRIPT_CAMERA_RULES = [
    (("慢推", "推进", "推近", "拉近", "zoom in", "push in", "dolly in"), "slow_push_in"),
    (("慢拉", "拉远", "拉开", "zoom out", "pull out", "dolly out"), "slow_zoom_out"),
    (("左移", "向左", "pan left", "左摇"), "pan_left"),
    (("右移", "向右", "pan right", "右摇"), "pan_right"),
    (("俯拍", "俯视", "tilt down", "下压"), "tilt_down"),
    (("仰拍", "仰视", "tilt up", "上仰"), "tilt_up"),
    (("特写", "近景", "close-up", "close up", "reveal"), "dramatic_reveal"),
]
SCRIPT_EMOTION_RULES = [
    (("开心", "高兴", "兴奋", "惊喜", "笑", "雀跃"), "happy"),
    (("愤怒", "生气", "怒", "火大", "暴怒", "愤慨"), "angry"),
    (("难过", "悲伤", "哭", "落泪", "委屈", "心酸"), "sad"),
    (("震惊", "错愕", "愣住", "吃惊", "惊讶"), "shocked"),
    (("紧张", "压迫", "焦灼", "忐忑", "慌张"), "tense"),
    (("平静", "冷静", "镇定", "沉稳"), "calm"),
]
SCRIPT_ROLE_IGNORE = {
    "旁白",
    "解说",
    "播音",
    "字幕",
    "画外音",
    "AI漫剧剧本",
    "剧本",
    "标题",
    "类型",
    "作者",
    "编剧",
    "提示",
    "提示词",
    "画面",
    "氛围",
    "场景",
    "镜头",
    "音效",
    "说明",
    "备注",
    "简介",
    "梗概",
    "对白",
}

# The original implementation stays in place as a fallback reference, but the
# definitions below take precedence at runtime and give the web MVP a steadier
# pasted-script parser plus richer preview metadata.
SCRIPT_SCENE_MARKERS = ("场景", "镜头", "Scene", "scene", "第", "#")
SCRIPT_ROLE_IGNORE = {"旁白", "解说", "播音", "字幕", "画外音"}
SCRIPT_DIALOGUE_SEPARATORS = (":", "：", "—", "–", "-", "－")
SCRIPT_HEADING_RE = re.compile(
    r"^\s*(?:(?:第\s*(?P<index>[\d一二三四五六七八九十百]{1,6})\s*(?:场|幕|节|镜头))|(?:scene\s*(?P<scene_index>\d{1,3}))|(?:场景\s*\d{1,3})|(?:镜头\s*\d{1,3})|(?:#{1,3}\s*.+))",
    re.IGNORECASE,
)
SCRIPT_SPEAKER_TOKEN_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9·•_]{1,16}$")
SCRIPT_HEADING_FALLBACK_RE = re.compile(
    r"^\s*(?:(?:\u7b2c\s*)?(?P<number>[0-9\u96f6\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u4e24]{1,6})\s*(?:\u573a|\u5e55|\u8282|\u955c\u5934|\u955c)|(?P<label>\u573a\u666f|\u955c\u5934|\u5206\u955c|scene)\s*(?P<label_number>[0-9\u96f6\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u4e24]{0,6})|(?P<hash>#{1,3}\s*.+))\s*(?P<trailing>.*)$",
    re.IGNORECASE,
)
