#!/usr/bin/env python3
"""阻止客户信息、API Key 和本地生成物进入 SkillHub 公开包。"""

import re
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
LOCAL_BLOCKLIST_PATH = SKILL_ROOT / "config" / "release_blocklist.txt"
SKIP_PARTS = {".git"}
SKIP_FILES = {"CHANGE_log.md", "release_blocklist.txt"}
BANNED_FILES = {"_meta.json", "config.ini", "config.ini.example", "environment_state.json", "user_profile.json", "writing_preferences.json"}
BANNED_DIRS = {"knowledge-base"}
BANNED_ARTIFACT_NAMES = {".gitignore", ".gitkeep", ".DS_Store"}
BANNED_ARTIFACT_SUFFIXES = {".pyc", ".pyo"}
ALLOWED_API_KEY_VALUES = {"", "your_api_key_here", "你的深知搜索 API Key"}
API_KEY_PATTERN = re.compile(r"(?im)^\s*api_key\s*=\s*([^\s#;]+)\s*$")
SECRET_TOKEN_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")


def load_local_blocklist():
    if not LOCAL_BLOCKLIST_PATH.exists():
        return []
    terms = []
    for line in LOCAL_BLOCKLIST_PATH.read_text(encoding="utf-8").splitlines():
        clean = line.strip()
        if clean and not clean.startswith("#"):
            terms.append(clean)
    return terms


def should_flag_api_key_value(value):
    clean = value.strip().strip('"').strip("'")
    if clean in ALLOWED_API_KEY_VALUES:
        return False
    # 代码变量、函数调用和对象属性不是明文 Key；真实配置值通常是单个 token。
    if any(mark in clean for mark in ("(", ")", "[", "]", "{", "}", ".", ",")):
        return False
    return True


def main():
    banned_terms = load_local_blocklist()
    findings = []
    for path in SKILL_ROOT.rglob("*"):
        if path.name in BANNED_ARTIFACT_NAMES or path.suffix in BANNED_ARTIFACT_SUFFIXES:
            findings.append(f"{path.relative_to(SKILL_ROOT)}: 公开包不得包含本地产物或平台不允许的文件")
            continue
        if any(part == "__pycache__" for part in path.parts):
            findings.append(f"{path.relative_to(SKILL_ROOT)}: 公开包不得包含 __pycache__")
            continue
        # 个人素材库与写作偏好是本机私有状态，绝不进入公开包。
        if any(part in BANNED_DIRS for part in path.relative_to(SKILL_ROOT).parts):
            findings.append(f"{path.relative_to(SKILL_ROOT)}: 公开包不得包含个人素材库等本机私有数据")
            continue
        if path.is_file() and path.name in BANNED_FILES:
            findings.append(f"{path.relative_to(SKILL_ROOT)}: 公开包不得包含真实配置文件或本机私有状态")
            continue
        if not path.is_file() or path.name in SKIP_FILES or any(part in SKIP_PARTS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            for term in banned_terms:
                if term in line:
                    findings.append(f"{path.relative_to(SKILL_ROOT)}:{line_number}: {term}")
            for match in API_KEY_PATTERN.finditer(line):
                if should_flag_api_key_value(match.group(1)):
                    findings.append(f"{path.relative_to(SKILL_ROOT)}:{line_number}: 发现非占位符 api_key")
            if SECRET_TOKEN_PATTERN.search(line):
                findings.append(f"{path.relative_to(SKILL_ROOT)}:{line_number}: 发现疑似 API Key")

    if findings:
        print("发布检查失败：发现客户强相关内容")
        print("\n".join(findings))
        raise SystemExit(1)
    print("发布检查通过：未发现已登记的客户强相关内容")


if __name__ == "__main__":
    main()
