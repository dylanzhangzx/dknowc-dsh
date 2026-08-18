#!/usr/bin/env python3
"""阻止 API Key、真实配置和本地生成物进入 SkillHub 公开包。"""

import re
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
SKIP_PARTS = {".git"}
BANNED_DIRS = {"outputs"}
SKIP_FILES = {"CHANGE_log.md"}
BANNED_FILES = {"config.ini", "_meta.json", "config.ini.example", "register.mjs"}
BANNED_ARTIFACT_NAMES = {".DS_Store"}
BANNED_ARTIFACT_SUFFIXES = {".pyc", ".pyo"}
BANNED_TERMS = (
    "广东省政务服务和数据管理" + "局",
    "广东省政数" + "局",
    "粤政" + "数",
    "粤政" + "易",
)
ALLOWED_API_KEY_VALUES = {"", "your_api_key_here", "你的深知可信统一接口 API Key"}
API_KEY_PATTERN = re.compile(r"(?im)^\s*api_key[^\S\r\n]*=[^\S\r\n]*([^\s#;]+)[^\S\r\n]*$")
SECRET_TOKEN_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")


def main():
    findings = []
    for path in SKILL_ROOT.rglob("*"):
        if path.name in BANNED_ARTIFACT_NAMES or path.suffix in BANNED_ARTIFACT_SUFFIXES:
            findings.append(f"{path.relative_to(SKILL_ROOT)}: 公开包不得包含本地产物或平台不允许的文件")
            continue
        if any(part in BANNED_DIRS for part in path.relative_to(SKILL_ROOT).parts):
            findings.append(f"{path.relative_to(SKILL_ROOT)}: 公开包不得包含本地生成输出目录")
            continue
        if any(part == "__pycache__" for part in path.parts):
            findings.append(f"{path.relative_to(SKILL_ROOT)}: 公开包不得包含 __pycache__")
            continue
        if path.is_file() and path.name in BANNED_FILES:
            findings.append(f"{path.relative_to(SKILL_ROOT)}: 公开包不得包含真实配置文件")
            continue
        if not path.is_file() or path.name in SKIP_FILES or any(part in SKIP_PARTS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            for term in BANNED_TERMS:
                if term in line:
                    findings.append(f"{path.relative_to(SKILL_ROOT)}:{line_number}: {term}")
        if path.suffix != ".py":
            for match in API_KEY_PATTERN.finditer(text):
                if match.group(1) not in ALLOWED_API_KEY_VALUES:
                    findings.append(f"{path.relative_to(SKILL_ROOT)}: 发现非占位符 api_key")
        if SECRET_TOKEN_PATTERN.search(text):
            findings.append(f"{path.relative_to(SKILL_ROOT)}: 发现疑似 API Key")

    if findings:
        print("发布检查失败：发现不应进入 SkillHub 公开包的内容")
        print("\n".join(findings))
        raise SystemExit(1)
    print("发布检查通过：未发现真实配置、API Key 或本地生成物")


if __name__ == "__main__":
    main()
