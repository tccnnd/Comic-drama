from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

DEFAULT_EXTENSIONS = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".txt",
    ".yaml",
    ".yml",
}

SKIP_DIRS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "_external",
    "build",
    "dist",
    "node_modules",
    "outputs",
    "tools",
    "workspace",
}

QUESTION_RUN_RE = re.compile(r"\?{4,}")

def chars(*codepoints: int) -> str:
    return "".join(chr(codepoint) for codepoint in codepoints)


# Common fragments produced when UTF-8 Chinese text is decoded as GBK/GB18030.
# These are built from code points so the checker does not flag its own source.
MOJIBAKE_SEQUENCES = (
    chars(0x9366, 0x70D8),
    chars(0x9365, 0x5267, 0x5896),
    chars(0x7459, 0x6395, 0x58CA),
    chars(0x690B, 0x5EA2, 0x7278),
    chars(0x701B, 0x6940, 0x7BB7),
    chars(0x7035, 0x714E),
    chars(0x9352, 0x55DB),
    chars(0x9353, 0x0444, 0x6E70),
    chars(0x95CA, 0x62BD),
    chars(0x7EF1, 0x72B3, 0x6F57),
    chars(0x93BB, 0x612C, 0x5F47),
    chars(0x59DD, 0xFF45, 0x6E6A),
    chars(0x9241),
    chars(0x8133),
)

# Rare-looking single characters that are strong mojibake signals in this repo.
MOJIBAKE_CHARS = frozenset(
    map(
        chr,
        (
            0x9356,  # 鍖
            0x9366,  # 鍦
            0x9422,  # 鐢
            0x7035,  # 瀵
            0x95CA,  # 闊
            0x9353,  # 鍓
            0x93C6,  # 鏆
            0x93BB,  # 鎻
            0x95BF,  # 閿
            0x95B8,  # 閸
            0x941F,  # 鐟
            0x9239,  # 鈹
            0x20AC,  # €
            0x9241,  # garbled check mark
            0x8133,  # garbled close mark
        ),
    )
)


def iter_text_files(root: Path, extensions: set[str]) -> list[Path]:
    files: list[Path] = []
    for current, dirs, names in os.walk(root):
        dirs[:] = [
            name
            for name in dirs
            if name not in SKIP_DIRS
            and not name.startswith("tmp_pytest")
            and not (name == "tmp" and Path(current) == root)
        ]
        current_path = Path(current)
        for name in names:
            path = current_path / name
            if path.suffix.lower() in extensions:
                files.append(path)
    return files


def text_issues(path: Path) -> list[tuple[int, str]]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return [(0, "file is not valid UTF-8")]
    issues: list[tuple[int, str]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        has_private_use = any(0xE000 <= ord(char) <= 0xF8FF for char in line)
        has_sequence = any(marker in line for marker in MOJIBAKE_SEQUENCES)
        suspicious_char_count = sum(1 for char in line if char in MOJIBAKE_CHARS)
        has_question_run = bool(QUESTION_RUN_RE.search(line))
        if "text.count" in line and "damaged_marks" in line:
            continue
        if has_private_use or has_sequence or suspicious_char_count >= 2 or has_question_run:
            snippet = line.strip()[:160].encode("unicode_escape").decode("ascii")
            issues.append((line_no, snippet))
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Check source text for mojibake and invalid UTF-8.")
    parser.add_argument("paths", nargs="*", help="Files or directories to scan. Defaults to repository root.")
    args = parser.parse_args()

    targets = [ROOT / value for value in args.paths] if args.paths else [ROOT]
    files: list[Path] = []
    for target in targets:
        if target.is_file():
            files.append(target)
        elif target.is_dir():
            files.extend(iter_text_files(target, DEFAULT_EXTENSIONS))

    failures: list[str] = []
    for path in sorted(set(files)):
        for line_no, snippet in text_issues(path):
            rel = path.relative_to(ROOT)
            if line_no:
                failures.append(f"{rel}:{line_no}: {snippet}")
            else:
                failures.append(f"{rel}: {snippet}")

    if failures:
        print("Text hygiene check failed:")
        print("\n".join(failures))
        return 1
    print("Text hygiene check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
