"""
提取动漫角色语音样本用于 OmniVoice 克隆。

使用方法：
1. 手动下载 JOJO 星尘斗士的片段（B站/YouTube）到 voice_sources/ 目录
2. 运行此脚本，自动分离人声并裁剪为适合克隆的片段

依赖：
  pip install demucs pydub

或者手动准备：
  - 找到角色独白片段（5-15秒，无BGM最佳）
  - 保存为 WAV 格式到 voice_samples/ 目录
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES_DIR = ROOT / "voice_sources"
SAMPLES_DIR = ROOT / "voice_samples"
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
SOURCES_DIR.mkdir(parents=True, exist_ok=True)

# JOJO 星尘斗士角色配置
JOJO_CHARACTERS = {
    "jotaro": {
        "name": "空条承太郎",
        "cv": "小野大辅",
        "traits": "低沉冷酷，寡言少语，偶尔爆发",
        "sample_lines": [
            "やれやれだぜ。",
            "てめーは俺を怒らせた。",
            "オラオラオラオラ！",
        ],
    },
    "dio": {
        "name": "DIO",
        "cv": "子安武人",
        "traits": "霸气邪魅，高傲自信，戏剧性强",
        "sample_lines": [
            "無駄無駄無駄無駄！",
            "このDIOだ！",
            "ザ・ワールド！時よ止まれ！",
        ],
    },
    "kakyoin": {
        "name": "花京院典明",
        "cv": "平川大辅",
        "traits": "温和理性，偶尔热血",
        "sample_lines": [
            "レロレロレロレロ。",
            "エメラルドスプラッシュ！",
        ],
    },
    "polnareff": {
        "name": "波鲁纳雷夫",
        "cv": "小松史法",
        "traits": "热情冲动，话多，情绪丰富",
        "sample_lines": [
            "ブラボー！おお、ブラボー！",
            "シルバーチャリオッツ！",
        ],
    },
    "joseph": {
        "name": "约瑟夫·乔斯达",
        "cv": "石冢运升",
        "traits": "老练幽默，中年男声，偶尔搞笑",
        "sample_lines": [
            "OH MY GOD!",
            "HOLY SHIT!",
            "次にお前は…と言う！",
        ],
    },
}


def check_ffmpeg() -> str:
    """Check if ffmpeg is available."""
    for name in ("ffmpeg", "ffmpeg.exe"):
        try:
            subprocess.run([name, "-version"], capture_output=True, check=True)
            return name
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    print("ERROR: ffmpeg not found. Please install ffmpeg.")
    sys.exit(1)


def extract_audio_from_video(video_path: Path, output_path: Path, ffmpeg: str) -> Path:
    """Extract audio track from video file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le", "-ar", "24000", "-ac", "1",
        str(output_path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return output_path


def trim_audio(input_path: Path, output_path: Path, start: float, duration: float, ffmpeg: str) -> Path:
    """Trim audio to specific segment."""
    cmd = [
        ffmpeg, "-y", "-i", str(input_path),
        "-ss", str(start), "-t", str(duration),
        "-acodec", "pcm_s16le", "-ar", "24000", "-ac", "1",
        str(output_path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return output_path


def separate_vocals(input_path: Path, output_dir: Path) -> Path | None:
    """Use demucs to separate vocals from background music."""
    try:
        cmd = [
            sys.executable, "-m", "demucs",
            "--two-stems", "vocals",
            "-o", str(output_dir),
            str(input_path),
        ]
        subprocess.run(cmd, capture_output=True, check=True, timeout=300)
        # Demucs outputs to output_dir/htdemucs/filename/vocals.wav
        stem = input_path.stem
        vocals_path = output_dir / "htdemucs" / stem / "vocals.wav"
        if vocals_path.exists():
            return vocals_path
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  Demucs separation failed: {e}")
        print("  Tip: pip install demucs")
    return None


def process_source_files(ffmpeg: str, use_demucs: bool = False):
    """Process all video/audio files in voice_sources/ directory."""
    source_files = list(SOURCES_DIR.glob("*.*"))
    video_exts = {".mp4", ".mkv", ".webm", ".flv", ".avi", ".mov"}
    audio_exts = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}

    if not source_files:
        print(f"\n没有找到源文件。请将 JOJO 动漫片段放入：")
        print(f"  {SOURCES_DIR}")
        print(f"\n建议命名格式：")
        print(f"  jotaro_01.mp4  (承太郎片段1)")
        print(f"  dio_01.mp4     (DIO片段1)")
        print(f"  kakyoin_01.mp4 (花京院片段1)")
        return

    for source in sorted(source_files):
        if source.suffix.lower() not in video_exts | audio_exts:
            continue

        # Detect character from filename
        char_key = source.stem.split("_")[0].lower()
        char_info = JOJO_CHARACTERS.get(char_key, {"name": char_key, "cv": "unknown"})
        print(f"\n处理: {source.name} → {char_info['name']} ({char_info.get('cv', '')})")

        # Extract audio if video
        if source.suffix.lower() in video_exts:
            raw_audio = SAMPLES_DIR / f"{source.stem}_raw.wav"
            extract_audio_from_video(source, raw_audio, ffmpeg)
        else:
            raw_audio = source

        # Vocal separation (optional)
        if use_demucs:
            print("  分离人声...")
            vocals = separate_vocals(raw_audio, SAMPLES_DIR / "demucs_output")
            if vocals:
                final_audio = vocals
                print(f"  ✓ 人声分离完成")
            else:
                final_audio = raw_audio
                print(f"  ✗ 跳过人声分离，使用原始音频")
        else:
            final_audio = raw_audio

        # Copy/convert to final sample
        sample_out = SAMPLES_DIR / f"{char_key}_{source.stem}.wav"
        if final_audio != sample_out:
            cmd = [
                ffmpeg, "-y", "-i", str(final_audio),
                "-acodec", "pcm_s16le", "-ar", "24000", "-ac", "1",
                str(sample_out),
            ]
            subprocess.run(cmd, capture_output=True, check=True)

        size_kb = sample_out.stat().st_size / 1024
        print(f"  ✓ 保存: {sample_out.name} ({size_kb:.0f}KB)")


def generate_config():
    """Generate voice_samples/config.json for the project to use."""
    config = {}
    for wav in sorted(SAMPLES_DIR.glob("*.wav")):
        if wav.stem.endswith("_raw"):
            continue
        char_key = wav.stem.split("_")[0].lower()
        char_info = JOJO_CHARACTERS.get(char_key, {"name": char_key, "cv": "unknown", "traits": ""})
        if char_key not in config:
            config[char_key] = {
                "name": char_info["name"],
                "cv": char_info.get("cv", ""),
                "traits": char_info.get("traits", ""),
                "samples": [],
            }
        config[char_key]["samples"].append({
            "path": str(wav.relative_to(ROOT)),
            "filename": wav.name,
            "size_kb": round(wav.stat().st_size / 1024, 1),
        })

    config_path = SAMPLES_DIR / "config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n配置已生成: {config_path}")
    print(f"\n角色样本汇总:")
    for key, info in config.items():
        print(f"  {info['name']} ({info['cv']}): {len(info['samples'])} 个样本")


def print_guide():
    """Print usage guide."""
    print("=" * 60)
    print("JOJO 星尘斗士 语音克隆样本提取工具")
    print("=" * 60)
    print(f"""
目标角色:
""")
    for key, info in JOJO_CHARACTERS.items():
        print(f"  {key:<12} {info['name']} (CV: {info['cv']})")
        print(f"             特征: {info['traits']}")
        print()

    print(f"""
获取音频的方法:

  方法1: B站下载（推荐）
  ─────────────────────
  1. 在B站搜索 "JOJO 星尘斗士 承太郎 名场面" 等关键词
  2. 找到角色独白/对话片段（尽量无BGM或BGM很轻的）
  3. 用 yt-dlp 下载:
     yt-dlp -x --audio-format wav "https://www.bilibili.com/video/BVxxxxxx"
  4. 将下载的文件重命名后放入 voice_sources/ 目录:
     jotaro_01.wav, dio_01.wav, kakyoin_01.wav ...

  方法2: 从完整剧集中截取
  ─────────────────────────
  1. 找到 JOJO 星尘斗士的视频文件
  2. 用 ffmpeg 截取角色独白片段（5-15秒）:
     ffmpeg -i episode.mp4 -ss 12:34 -t 10 -vn jotaro_01.wav
  3. 放入 voice_sources/ 目录

  方法3: 101soundboards.com
  ─────────────────────────
  访问以下页面可以找到角色语音片段:
  - https://www.101soundboards.com/boards/83927 (星尘斗士音板)
  - 右键音频按钮 → 另存为

  推荐片段时长: 5-15秒
  推荐格式: WAV (24kHz, 单声道)
  关键要求: 尽量只有角色人声，无BGM/音效

文件命名规则:
  {{角色key}}_{{编号}}.{{格式}}
  例: jotaro_01.mp4, dio_battle_cry.wav

准备好后运行:
  python scripts/extract_voice_samples.py --process
  python scripts/extract_voice_samples.py --process --demucs  (带人声分离)
""")


def main():
    parser = argparse.ArgumentParser(description="JOJO 星尘斗士语音样本提取")
    parser.add_argument("--process", action="store_true", help="处理 voice_sources/ 中的文件")
    parser.add_argument("--demucs", action="store_true", help="使用 demucs 分离人声（需要 pip install demucs）")
    parser.add_argument("--config", action="store_true", help="生成样本配置文件")
    parser.add_argument("--guide", action="store_true", help="显示使用指南")
    args = parser.parse_args()

    if args.guide or (not args.process and not args.config):
        print_guide()
        return

    ffmpeg = check_ffmpeg()

    if args.process:
        process_source_files(ffmpeg, use_demucs=args.demucs)

    generate_config()


if __name__ == "__main__":
    main()
