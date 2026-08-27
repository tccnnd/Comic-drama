#!/usr/bin/env python3
"""outputs/ 保留策略清理工具（T2.1）。

用法:
  python scripts/cleanup_outputs.py            # dry-run：仅列出将清理项与释放空间
  python scripts/cleanup_outputs.py --apply    # 实际执行清理
  python scripts/cleanup_outputs.py --keep-runs 3   # 保留最近 3 个 run_*（默认 2）
  python scripts/cleanup_outputs.py --dry-run --json  # 输出 JSON 摘要

保留策略:
  1. gateB_check/ 等验收产物目录（--keep-dirs 白名单，默认 gateB_check）永不删除。
  2. outputs/run_* 目录：按 mtime 保留最近 N 个（--keep-runs，默认 2），其余删除。
  3. outputs/ 顶层历史测试文件（png/zip/safetensors/mp4/webm 等）列入清理。
  4. 未知目录与未匹配文件（如正在使用的临时目录）保持原样，仅提示。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"

# 验收产物白名单：这些目录永不删除
KEEP_DIRS_DEFAULT = ("gateB_check",)

# 顶层历史测试产物的扩展名（非 run_* 产物）
CLEANABLE_EXT = {
    ".png",
    ".jpg",
    ".jpeg",
    ".zip",
    ".safetensors",
    ".mp4",
    ".webm",
    ".mov",
    ".gif",
    ".wav",
    ".mp3",
    ".log",
    ".json",
    ".txt",
}


def _dir_mtime(p: Path) -> float:
    return p.stat().st_mtime


def plan_cleanup(keep_runs: int, keep_dirs: tuple[str, ...]) -> tuple[list[Path], int]:
    """返回 (待清理路径列表, 预计释放字节)。不执行任何删除。"""
    if not OUTPUTS.is_dir():
        return [], 0
    cleanable: list[Path] = []
    freed = 0

    # run_* 目录：按 mtime 排序，保留最近 N 个
    runs = sorted(
        [p for p in OUTPUTS.iterdir() if p.is_dir() and p.name.startswith("run_")],
        key=_dir_mtime,
        reverse=True,
    )
    for p in runs[keep_runs:]:
        size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        cleanable.append(p)
        freed += size

    # 非 run_*、非白名单的历史测试/冒烟目录：全部列入清理
    for p in OUTPUTS.iterdir():
        if p.is_dir() and p.name not in keep_dirs and not p.name.startswith("run_"):
            size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            cleanable.append(p)
            freed += size

    # 顶层历史测试文件
    for p in OUTPUTS.iterdir():
        if p.is_file() and p.suffix.lower() in CLEANABLE_EXT:
            cleanable.append(p)
            freed += p.stat().st_size

    return cleanable, freed


def main() -> int:
    ap = argparse.ArgumentParser(description="outputs/ 保留策略清理（dry-run 默认）")
    ap.add_argument("--apply", action="store_true", help="实际执行删除；缺省为 dry-run")
    ap.add_argument("--keep-runs", type=int, default=2, help="保留最近 N 个 run_* 目录（默认 2）")
    ap.add_argument(
        "--keep-dirs",
        default=",".join(KEEP_DIRS_DEFAULT),
        help="永不删除的目录白名单（逗号分隔，默认 gateB_check）",
    )
    ap.add_argument("--json", action="store_true", help="输出 JSON 摘要")
    args = ap.parse_args()

    keep_dirs = tuple(d.strip() for d in args.keep_dirs.split(",") if d.strip())
    cleanable, freed = plan_cleanup(args.keep_runs, keep_dirs)

    size_mb = freed / 1024 / 1024
    if args.json:
        print(
            json.dumps(
                {
                    "mode": "apply" if args.apply else "dry-run",
                    "items": len(cleanable),
                    "freed_mb": round(size_mb, 1),
                    "paths": [str(p.relative_to(ROOT)) for p in cleanable],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(
            f"[{'APPLY' if args.apply else 'DRY-RUN'}] 可清理 {len(cleanable)} 项，"
            f"预计释放 {size_mb:.1f} MB"
        )
        for p in cleanable:
            rel = p.relative_to(ROOT)
            print(f"  - {rel}")

    if args.apply:
        for p in cleanable:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
        print(f"[APPLY] 已删除 {len(cleanable)} 项")
    return 0


if __name__ == "__main__":
    sys.exit(main())
