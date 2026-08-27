#!/usr/bin/env python3
"""pre-commit 敏感信息扫描（T2.3）。

检测高置信 secret 模式（AWS 密钥、私钥、GitHub token、OpenAI key、
JWT 等）在即将提交的文本文件中出现。命中则返回非零，阻止提交。

排除：.venv/ node_modules/ _external/ outputs/ data/ *.lock 二进制等。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 高置信模式（避免误报：不含宽松的 password = xxx）
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("AWS secret", re.compile(r"(?i)\baws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}")),
    ("private key", re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b")),
    ("OpenAI key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("generic API key", re.compile(r"(?i)\bapi[_-]?key\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{24,}['\"]?")),
]

_EXCLUDE_DIRS = {
    ".venv",
    "node_modules",
    "_external",
    "outputs",
    "data",
    "workspace",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".workbuddy",
    ".tmp",
    ".kiro",
    "tools",
    ".vscode",
    ".idea",
    ".github",
}
_EXCLUDE_SUFFIXES = {
    ".lock",
    ".pyc",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".mp4",
    ".webm",
    ".wav",
    ".mp3",
    ".zip",
    ".safetensors",
    ".bin",
    ".ttf",
    ".woff2",
}
_EXCLUDE_NAMES = {
    "package-lock.json",
    "coverage.xml",
    ".health_probe_*.tmp",
    ".env",
    ".env.example",
}


def _iter_target_files() -> list[Path]:
    files = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        parts = rel.parts
        if any(part in _EXCLUDE_DIRS for part in parts):
            continue
        if p.suffix.lower() in _EXCLUDE_SUFFIXES:
            continue
        if p.name in _EXCLUDE_NAMES:
            continue
        files.append(p)
    return files


def main() -> int:
    findings: list[str] = []
    for path in _iter_target_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name, pattern in _PATTERNS:
            for m in pattern.finditer(text):
                line_no = text.count("\n", 0, m.start()) + 1
                findings.append(f"{path.relative_to(ROOT)}:{line_no}: {name}")

    if findings:
        print("[secret-scan] 检测到潜在敏感信息，已阻止提交：")
        for f in findings[:20]:
            print(f"  {f}")
        if len(findings) > 20:
            print(f"  ... 以及另外 {len(findings) - 20} 处")
        return 1
    print("[secret-scan] OK：未检测到敏感信息")
    return 0


if __name__ == "__main__":
    sys.exit(main())
