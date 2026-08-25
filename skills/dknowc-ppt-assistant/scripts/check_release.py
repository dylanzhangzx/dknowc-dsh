#!/usr/bin/env python3
"""深知可信PPT发布前检查。

阻止 API Key、真实配置和本地生成物进入 SkillHub 公开包。
针对本 Skill 的抽取结构适配：允许第三方声明文件（THIRD_PARTY_NOTICES.md、
LICENSE*.txt、NOTICE.md）与编译器数据文件；projects/ 与 official-docs/
工作区内只允许 .gitkeep 占位。
"""

import re
from pathlib import Path


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


SKILL_ROOT = Path(__file__).resolve().parent.parent
SKIP_PARTS = {".git", "__pycache__"}
WORKSPACE_DIR_NAMES = {"official-docs", "projects"}
ALLOWED_WORKSPACE_FILES = {".gitkeep"}
SKIP_FILES = {"CHANGE_log.md", "release_blocklist.txt", "THIRD_PARTY_NOTICES.md"}
BANNED_FILES = {
    "config.ini",
    "config.ini.example",
    "_meta.json",
    "environment_state.json",
}
# 第三方许可文件随包分发（MIT 合规要求），不视为违禁。
ALLOWED_LICENSE_NAMES = {"THIRD_PARTY_NOTICES.md", "NOTICE.md"}
ALLOWED_LICENSE_PREFIXES = ("LICENSE-",)
ALLOWED_DATA_SUFFIXES = {".json", ".xml", ".txt"}
BANNED_ARTIFACT_NAMES = {".DS_Store"}
BANNED_ARTIFACT_SUFFIXES = {".pyc", ".pyo"}
ALLOWED_API_KEY_VALUES = {
    "",
    "your_api_key_here",
    "你的深知可信搜索 API Key",
    "你的深知搜索 API Key",
}
API_KEY_PATTERN = re.compile(r"(?im)^\s*api_key[^\S\r\n]*=[^\S\r\n]*([^\s#;]+)[^\S\r\n]*$")
SECRET_TOKEN_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")


def should_flag_api_key_value(value):
    clean = value.strip().strip('"').strip("'")
    if clean in ALLOWED_API_KEY_VALUES:
        return False
    if any(mark in clean for mark in ("(", ")", "[", "]", "{", "}", ".", ",")):
        return False
    return True


def _is_allowed_license_file(path: Path) -> bool:
    if path.name in ALLOWED_LICENSE_NAMES:
        return True
    return any(path.name.startswith(p) for p in ALLOWED_LICENSE_PREFIXES)


def main():
    findings = []
    for path in SKILL_ROOT.rglob("*"):
        rel = path.relative_to(SKILL_ROOT)
        parts = rel.parts
        if path.name in BANNED_ARTIFACT_NAMES or path.suffix in BANNED_ARTIFACT_SUFFIXES:
            findings.append(f"{rel}: 公开包不得包含本地产物")
            continue
        if any(part in SKIP_PARTS for part in parts):
            continue
        if path.is_file() and path.name in BANNED_FILES:
            findings.append(f"{rel}: 公开包不得包含真实配置文件")
            continue
        # 工作区目录只允许 .gitkeep（第三方许可文件除外）
        if path.is_file() and WORKSPACE_DIR_NAMES.intersection(parts):
            if path.name not in ALLOWED_WORKSPACE_FILES and not _is_allowed_license_file(path):
                findings.append(f"{rel}: 工作区目录内只允许 .gitkeep 占位，公开包不得包含工作区产物")
                continue
        if not path.is_file() or path.name in SKIP_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            # 二进制数据文件（json/xml/txt 之外的图片等）跳过文本扫描
            if path.suffix.lower() not in ALLOWED_DATA_SUFFIXES:
                continue
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            for match in API_KEY_PATTERN.finditer(line):
                if should_flag_api_key_value(match.group(1)):
                    findings.append(f"{rel}:{line_number}: 发现非占位符 api_key")
            if SECRET_TOKEN_PATTERN.search(line):
                findings.append(f"{rel}:{line_number}: 发现疑似 API Key")

    if findings:
        print("发布检查失败：发现不应进入 SkillHub 公开包的内容")
        print("\n".join(findings))
        raise SystemExit(1)
    print("发布检查通过：未发现真实配置、API Key 或本地生成物")


if __name__ == "__main__":
    main()
