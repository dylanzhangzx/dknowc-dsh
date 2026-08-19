#!/usr/bin/env python3
"""深知公文写作 - 本地个人记忆管理：个人素材库与写作偏好。

两类本地状态均只保存在本机、不随公开包分发、不上传：
- 个人素材库 knowledge-base/：用户确认保存的长期材料，按用途分类并打场景标签。
- 写作偏好 config/writing_preferences.json：用户沉淀的内容、排版、表达习惯。

用法示例：
  python3 scripts/local_memory.py kb save <文件> --category policy --tags 通知,请示 --note 说明
  python3 scripts/local_memory.py kb list [--category policy] [--tag 通知]
  python3 scripts/local_memory.py kb search 关键词 [--category policy]
  python3 scripts/local_memory.py kb remove kb-001
  python3 scripts/local_memory.py pref save --type format --scope 通知 --rule "标题不使用问句"
  python3 scripts/local_memory.py pref list [--type format] [--scope 通知]
  python3 scripts/local_memory.py pref remove wp-001
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from datetime import date
from pathlib import Path
from xml.etree import ElementTree


SKILL_ROOT = Path(__file__).resolve().parent.parent
# dsh 场景：个人素材库与写作偏好属于跨会话持久数据，锚定用户主目录固定位置
# （~/.dknowc-writer/），跨工作区共享、插件升级不丢失；可经 DKNWOC_HOME_DIR 覆盖。
import os as _os
DATA_ROOT = Path(_os.environ.get("DKNWOC_HOME_DIR") or str(Path.home() / ".dknowc-writer")).resolve()
KB_ROOT = DATA_ROOT / "knowledge-base"
INDEX_PATH = KB_ROOT / "_index.json"
PREF_PATH = DATA_ROOT / "config" / "writing_preferences.json"

KB_CATEGORIES = {
    "unit-profile": "单位资料",
    "policy": "政策文件",
    "data": "数据资料",
    "past-docs": "历史文稿",
    "business-rules": "业务口径",
    "misc": "其他",
}
PREF_TYPES = {
    "content": "内容习惯",
    "format": "排版习惯",
    "phrasing": "表达习惯",
}
STORABLE_SUFFIXES = {".txt", ".md", ".json", ".csv", ".docx"}
TEXT_SEARCH_SUFFIXES = {".txt", ".md", ".json", ".csv", ".docx"}
MAX_STORE_BYTES = 20 * 1024 * 1024


def load_kb_index() -> dict:
    if not INDEX_PATH.exists():
        return {"version": 1, "items": []}
    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "items": []}
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return {"version": 1, "items": []}
    return data


def save_kb_index(data: dict) -> None:
    KB_ROOT.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_prefs() -> dict:
    empty = {key: [] for key in PREF_TYPES}
    if not PREF_PATH.exists():
        return empty
    try:
        data = json.loads(PREF_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(data, dict):
        return empty
    return {
        key: data.get(key) if isinstance(data.get(key), list) else []
        for key in PREF_TYPES
    }


def save_prefs(data: dict) -> None:
    PREF_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREF_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def next_id(prefix: str, items: list) -> str:
    max_no = 0
    for item in items:
        no = str(item.get("id", "")).rsplit("-", 1)[-1]
        if no.isdigit():
            max_no = max(max_no, int(no))
    return f"{prefix}-{max_no + 1:03d}"


def read_docx_text(path: Path) -> str:
    pieces = []
    try:
        with zipfile.ZipFile(path) as zf:
            if "word/document.xml" not in zf.namelist():
                return ""
            root = ElementTree.fromstring(zf.read("word/document.xml"))
            for elem in root.iter():
                tag = elem.tag.rsplit("}", 1)[-1]
                if tag == "t" and elem.text:
                    pieces.append(elem.text)
                elif tag in {"p", "br"}:
                    pieces.append("\n")
    except (zipfile.BadZipFile, ElementTree.ParseError, OSError):
        return ""
    return "".join(pieces)


def searchable_text(path: Path) -> str:
    if path.suffix.lower() not in TEXT_SEARCH_SUFFIXES:
        return ""
    if path.suffix.lower() == ".docx":
        return read_docx_text(path)
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def unique_dest(category_dir: Path, filename: str) -> Path:
    dest = category_dir / filename
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    for i in range(1, 1000):
        candidate = category_dir / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
    raise SystemExit("ERROR: 无法生成唯一文件名")


def emit(result: dict) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_kb_save(args) -> dict:
    src = Path(args.file).expanduser()
    if not src.is_file():
        raise SystemExit(f"ERROR: 文件不存在: {src}")
    if src.suffix.lower() not in STORABLE_SUFFIXES:
        raise SystemExit(f"ERROR: 暂不支持保存 {src.suffix} 文件，支持: {', '.join(sorted(STORABLE_SUFFIXES))}")
    if src.stat().st_size > MAX_STORE_BYTES:
        raise SystemExit("ERROR: 文件超过 20MB，不宜存入素材库")
    category = args.category
    if category not in KB_CATEGORIES:
        raise SystemExit(f"ERROR: 分类必须是 {', '.join(KB_CATEGORIES)} 之一")

    tags = [t.strip() for t in (args.tags or "").replace("，", ",").split(",") if t.strip()]
    category_dir = KB_ROOT / category
    category_dir.mkdir(parents=True, exist_ok=True)
    dest = unique_dest(category_dir, Path(src.name).name)
    shutil.copy2(src, dest)

    index = load_kb_index()
    item = {
        "id": next_id("kb", index["items"]),
        "title": args.title or Path(src).stem,
        "category": category,
        "category_label": KB_CATEGORIES[category],
        "tags": tags,
        "note": args.note or "",
        "file": str(dest.relative_to(DATA_ROOT)),
        "size": dest.stat().st_size,
        "added": date.today().isoformat(),
    }
    index["items"].append(item)
    save_kb_index(index)
    return {"saved": True, "material": item}


def cmd_kb_list(args) -> dict:
    items = load_kb_index()["items"]
    if args.category:
        items = [i for i in items if i.get("category") == args.category]
    if args.tag:
        tag = args.tag.strip()
        items = [i for i in items if tag in (i.get("tags") or [])]
    return {"count": len(items), "materials": items}


def cmd_kb_search(args) -> dict:
    keyword = args.keyword.strip()
    if not keyword:
        raise SystemExit("ERROR: 关键词不能为空")
    items = load_kb_index()["items"]
    if args.category:
        items = [i for i in items if i.get("category") == args.category]
    lowered = keyword.lower()
    results = []
    for item in items:
        matched_in = []
        if lowered in str(item.get("title", "")).lower():
            matched_in.append("标题")
        if any(lowered in str(t).lower() for t in item.get("tags") or []):
            matched_in.append("标签")
        if lowered in str(item.get("note", "")).lower():
            matched_in.append("备注")
        path = DATA_ROOT / str(item.get("file", ""))
        if path.is_file() and lowered in searchable_text(path).lower():
            matched_in.append("正文")
        if matched_in:
            results.append({**item, "matched_in": matched_in})
    return {"count": len(results), "materials": results}


def cmd_kb_remove(args) -> dict:
    index = load_kb_index()
    target = None
    for item in index["items"]:
        if item.get("id") == args.id:
            target = item
            break
    if target is None:
        raise SystemExit(f"ERROR: 素材不存在: {args.id}")
    path = (DATA_ROOT / str(target.get("file", ""))).resolve()
    try:
        path.relative_to(KB_ROOT.resolve())
    except ValueError:
        path = None  # 索引指向异常路径时只删索引，不动文件
    if path and path.is_file():
        path.unlink()
    index["items"] = [i for i in index["items"] if i.get("id") != args.id]
    save_kb_index(index)
    return {"removed": True, "id": args.id}


def cmd_pref_save(args) -> dict:
    if args.type not in PREF_TYPES:
        raise SystemExit(f"ERROR: 偏好类型必须是 {', '.join(PREF_TYPES)} 之一")
    rule = args.rule.strip()
    if not rule:
        raise SystemExit("ERROR: 偏好内容不能为空")
    scope = args.scope or "通用"
    prefs = load_prefs()
    for existing in prefs[args.type]:
        if existing.get("rule") == rule and existing.get("scope") == scope:
            return {"saved": False, "reason": "已有相同偏好", "preference": existing}
    item = {
        "id": next_id("wp", prefs[args.type]),
        "type": args.type,
        "type_label": PREF_TYPES[args.type],
        "scope": scope,
        "rule": rule,
        "source": args.source or "用户确认保存",
        "created": date.today().isoformat(),
    }
    prefs[args.type].append(item)
    save_prefs(prefs)
    return {"saved": True, "preference": item}


def cmd_pref_list(args) -> dict:
    prefs = load_prefs()
    out = []
    for ptype, items in prefs.items():
        if args.type and ptype != args.type:
            continue
        for item in items:
            if args.scope and item.get("scope") != args.scope:
                continue
            out.append(item)
    return {"count": len(out), "preferences": out}


def cmd_pref_remove(args) -> dict:
    prefs = load_prefs()
    for ptype, items in prefs.items():
        for item in items:
            if item.get("id") == args.id:
                prefs[ptype] = [i for i in items if i.get("id") != args.id]
                save_prefs(prefs)
                return {"removed": True, "id": args.id}
    raise SystemExit(f"ERROR: 偏好不存在: {args.id}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="深知公文写作本地个人记忆管理（素材库与写作偏好）")
    commands = parser.add_subparsers(dest="group", required=True)

    kb = commands.add_parser("kb", help="个人素材库管理")
    kb_commands = kb.add_subparsers(dest="action", required=True)

    kb_save = kb_commands.add_parser("save", help="保存材料到素材库（经用户确认后执行）")
    kb_save.add_argument("file", help="要保存的材料文件路径")
    kb_save.add_argument("--category", required=True,
                         help=f"用途分类: {'/'.join(KB_CATEGORIES)}")
    kb_save.add_argument("--tags", help="场景标签，逗号分隔，如: 通知,请示")
    kb_save.add_argument("--note", help="备注说明")
    kb_save.add_argument("--title", help="素材标题，默认取文件名")
    kb_save.set_defaults(func=cmd_kb_save)

    kb_list = kb_commands.add_parser("list", help="列出素材库条目")
    kb_list.add_argument("--category", help="按用途分类过滤")
    kb_list.add_argument("--tag", help="按场景标签过滤")
    kb_list.set_defaults(func=cmd_kb_list)

    kb_search = kb_commands.add_parser("search", help="按关键词检索素材（标题/标签/备注/正文）")
    kb_search.add_argument("keyword", help="检索关键词")
    kb_search.add_argument("--category", help="按用途分类过滤")
    kb_search.set_defaults(func=cmd_kb_search)

    kb_remove = kb_commands.add_parser("remove", help="删除素材条目及文件（必须先经用户确认）")
    kb_remove.add_argument("id", help="素材 ID，如 kb-001")
    kb_remove.set_defaults(func=cmd_kb_remove)

    pref = commands.add_parser("pref", help="写作偏好管理")
    pref_commands = pref.add_subparsers(dest="action", required=True)

    pref_save = pref_commands.add_parser("save", help="保存写作偏好（经用户确认后执行）")
    pref_save.add_argument("--type", required=True, help=f"偏好类型: {'/'.join(PREF_TYPES)}")
    pref_save.add_argument("--scope", help="适用范围：通用或具体文种，默认通用")
    pref_save.add_argument("--rule", required=True, help="偏好内容描述")
    pref_save.add_argument("--source", help="来源说明，如：2026-08-19 用户修改反馈")
    pref_save.set_defaults(func=cmd_pref_save)

    pref_list = pref_commands.add_parser("list", help="列出写作偏好")
    pref_list.add_argument("--type", help="按类型过滤: content/format/phrasing")
    pref_list.add_argument("--scope", help="按适用范围过滤")
    pref_list.set_defaults(func=cmd_pref_list)

    pref_remove = pref_commands.add_parser("remove", help="删除写作偏好（必须先经用户确认）")
    pref_remove.add_argument("id", help="偏好 ID，如 wp-001")
    pref_remove.set_defaults(func=cmd_pref_remove)

    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    result = args.func(args)
    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
