#!/usr/bin/env python3
"""统一入口（1.0.1）：把业务 Skill 的检索/装配产物映射为通用 JSON。

设计原则（上游单源化）：
- 渲染器只认通用 JSON（materials + answer + question + selfCheck + verifyRecord）；
- 一切输入形态差异在**这里**的 adapter 层消化：
  * adapter=merged（默认）：检索接口/merge 脚本产物（`content.data.检索文章` 或顶层 `检索文章`）
    → materials；可选 `--policy-files` 用 policyFiles 的 writtenText 回填发文字号。
  * adapter=assembly：装配形态的溯源 JSON（materials/recalled_materials/document_content）
    → materials（字段映射见 SKILL.md「统一入口」表）。
- 接口调整时只改本脚本，渲染器不动（上游单源约定）。

用法：
    python3 build_report_input.py merged.json --adapter merged \
        --answer-file answer.txt --question-file question.txt \
        --self-check-file selfcheck.json --verify-file verify.json \
        --output input.json

    python3 build_report_input.py 公文装配.json --adapter assembly \
        --answer-file answer.txt --output input.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

from run_paths import (RunPathError, SKILL_ROOT, is_within, resolve_input_path,
                       resolve_run_dir)


def first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value not in (None, "", [], {}) and not isinstance(value, (dict, list)):
            return str(value).strip()
    return ""


def _norm_title(value: str) -> str:
    """标题归一：去掉空白与常见标点，用于 policyFiles 匹配。"""
    return re.sub(r"[\s　，。、；：:,.·《》“”\"'（）()【】\[\]—\-/]+", "",
                  str(value or "").lower())


def _paragraph_join(item: Dict[str, Any]) -> str:
    """段落数组 → 摘录文本（与渲染器 paragraph_text 同口径）。"""
    paragraphs = item.get("段落") or item.get("paragraphs") or item.get("content")
    chunks: List[str] = []
    if isinstance(paragraphs, list):
        for para in paragraphs:
            if isinstance(para, dict):
                chunk = first_str(para.get("内容"), para.get("text"), para.get("content"),
                                  para.get("summary"), para.get("标题"), para.get("title"))
            else:
                chunk = str(para)
            if chunk.strip():
                chunks.append(chunk.strip())
    if chunks:
        return "\n".join(chunks)
    return first_str(item.get("原文"), item.get("摘录"), item.get("excerpt"), item.get("support"),
                     item.get("摘要"), item.get("snippet"))


def _is_unofficial(item: Dict[str, Any]) -> bool:
    if item.get("非官方来源") is True:
        return True
    kind = str(item.get("来源性质") or item.get("source_kind") or "").strip().lower()
    if kind in ("unofficial", "非官方", "非官方来源"):
        return True
    if str(item.get("数据权威性") or item.get("authority") or "").strip() in ("非权威", "non-authoritative"):
        return True
    return False


def find_merged_articles(payload: Any) -> List[Dict[str, Any]]:
    """检索接口/merge 产物 → 文章数组。兼容 content.data.检索文章 与顶层 检索文章。"""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    content = payload.get("content")
    if isinstance(content, dict):
        data = content.get("data")
        if isinstance(data, dict) and isinstance(data.get("检索文章"), list):
            return [x for x in data["检索文章"] if isinstance(x, dict)]
    if isinstance(payload.get("检索文章"), list):
        return [x for x in payload["检索文章"] if isinstance(x, dict)]
    return []


def map_merged_article(item: Dict[str, Any]) -> Dict[str, Any]:
    """单篇文章（接口形态）→ 通用材料。只改包装，不改内容。"""
    number = item.get("编号") or item.get("index") or item.get("idx") or item.get("角标")
    doc_number = first_str(item.get("文号"), item.get("发文字号"), item.get("writtenText"),
                           item.get("doc_number"))
    material: Dict[str, Any] = {
        "标题": first_str(item.get("文章标题"), item.get("material_name"), item.get("标题"),
                          item.get("title"), item.get("name")),
        "源网址": first_str(item.get("源网址"), item.get("sourceUrl"), item.get("原文链接"),
                            item.get("url")),
        "快照链接": first_str(item.get("快照链接"), item.get("screenShotPath"), item.get("snapshot")),
        "发布机构": first_str(item.get("发布或实施机构"), item.get("发布机构"), item.get("发布机关"),
                              item.get("issuer")),
        "发布日期": first_str(item.get("发布日期"), item.get("date"), item.get("发布时间")),
        "发文字号": doc_number,
        "可信度": first_str(item.get("发布日期可信度"), item.get("可信度"), item.get("confidence")),
        "检索分组": first_str(item.get("搜索条件"), item.get("检索分组"), item.get("search_key")),
        "检索通道": first_str(item.get("检索通道"), item.get("channel")),
        "类型": first_str(item.get("文章类型"), item.get("类型"), item.get("type"), item.get("素材类型")),
        "核验": first_str(item.get("核验"), item.get("核验说明"), item.get("verification")),
    }
    if number not in (None, "", []):
        material["编号"] = number
    paragraphs = item.get("段落") or item.get("paragraphs")
    if isinstance(paragraphs, list) and paragraphs:
        material["段落"] = paragraphs
    else:
        # 无段落数组时用摘录文本兜底；有段落时不再重复存全文（渲染器从段落读取）
        material["原文"] = _paragraph_join(item)
    if "可引用" in item:
        material["可引用"] = item.get("可引用")
    if "待核验" in item:
        material["待核验"] = item.get("待核验")
    if _is_unofficial(item):
        material["来源性质"] = "unofficial"
    return {k: v for k, v in material.items() if v not in (None, "")}


def map_assembly_material(item: Dict[str, Any], used: bool = True) -> Dict[str, Any]:
    """装配 JSON 的单条材料 → 通用材料（字段映射见 SKILL.md「统一入口」表）。"""
    material: Dict[str, Any] = {
        "标题": first_str(item.get("material_name"), item.get("材料名称"), item.get("标题"),
                          item.get("title")),
        "源网址": first_str(item.get("source_url"), item.get("源网址"), item.get("url")),
        "快照链接": first_str(item.get("snapshot_url"), item.get("快照链接"), item.get("snapshot")),
        "发布机构": first_str(item.get("source"), item.get("发布机构"), item.get("issuer")),
        "发布日期": first_str(item.get("date"), item.get("发布日期")),
        "发文字号": first_str(item.get("doc_number"), item.get("文号"), item.get("发文字号")),
        "检索分组": first_str(item.get("search_key"), item.get("检索分组")),
        "类型": first_str(item.get("type"), item.get("类型")),
        "核验": first_str(item.get("verification"), item.get("核验")),
        "章节": first_str(item.get("section")),
    }
    paragraphs = item.get("段落") or item.get("paragraphs")
    if isinstance(paragraphs, list) and paragraphs:
        material["段落"] = paragraphs
    else:
        material["原文"] = _paragraph_join(item)
    if not used:
        material["已引用"] = False
    if item.get("编号") not in (None, "", []):
        material["编号"] = item.get("编号")
    return {k: v for k, v in material.items() if v not in (None, "")}


def apply_policy_files(materials: List[Dict[str, Any]], payload: Any) -> int:
    """policyFiles → 发文字号回填：按标题归一匹配，只填空缺，不覆盖已有文号。"""
    content = payload.get("content") if isinstance(payload, dict) else None
    data = content.get("data") if isinstance(content, dict) else None
    policy_files = data.get("policyFiles") if isinstance(data, dict) else None
    if not isinstance(policy_files, list):
        return 0
    doc_map: Dict[str, str] = {}
    for pf in policy_files:
        if not isinstance(pf, dict):
            continue
        title = _norm_title(first_str(pf.get("title"), pf.get("标题"), pf.get("文章标题")))
        written = first_str(pf.get("writtenText"), pf.get("发文字号"), pf.get("文号"))
        if title and written:
            doc_map[title] = written
    filled = 0
    for material in materials:
        if material.get("发文字号"):
            continue
        written = doc_map.get(_norm_title(str(material.get("标题") or "")))
        if written:
            material["发文字号"] = written
            filled += 1
    return filled


def load_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="统一入口：业务产物 → 通用 JSON（渲染器唯一输入）")
    parser.add_argument("source_json", help="业务 Skill 的产物 JSON（merge 结果或公文装配 JSON）")
    parser.add_argument("--adapter", choices=("merged", "assembly"), default="merged",
                        help="输入适配器：merged=检索文章形态；assembly=公文装配 JSON（默认 merged）")
    parser.add_argument("--run", help="本次运行的独立目录（输入/输出相对路径基准；必须在 Skill 目录之外）")
    parser.add_argument("--output", help="输出通用 JSON 文件名；相对名落在 --run 目录（默认 input.json）")
    parser.add_argument("--answer-file", help="最终答案文件（.txt/.md，关键结论带 [n] 角标）")
    parser.add_argument("--answer", help="最终答案文本（与 --answer-file 二选一，文件优先）")
    parser.add_argument("--question", help="用户原始问题（完整原文）")
    parser.add_argument("--question-file", help="用户原始问题全文文件（多行问题必须用本参数）")
    parser.add_argument("--self-check-file", help="答案自检结果 JSON（键集由业务配置决定）")
    parser.add_argument("--verify-file", help="域内核验记录 JSON（verdict/record/issues），原样嵌入输出")
    parser.add_argument("--title", help="报告标题；缺省取输入 JSON 的 title 或问题")
    parser.add_argument("--stage", help="双版阶段标识（outline/final），原样写入输出 properties")
    parser.add_argument("--policy-files", action="store_true",
                        help="merged 适配器：用 policyFiles 的 writtenText 回填空缺发文字号")
    args = parser.parse_args()

    try:
        run_dir = resolve_run_dir(args.run) if args.run else None
    except RunPathError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    try:
        source_path = resolve_input_path(args.source_json, run_dir, {".json"})
        source = load_json_file(source_path)
    except (RunPathError, json.JSONDecodeError, OSError) as exc:
        print(f"错误：输入无法读取（{exc}）", file=sys.stderr)
        return 2

    source_meta: Dict[str, Any] = source if isinstance(source, dict) else {}
    materials: List[Dict[str, Any]] = []

    if args.adapter == "merged":
        articles = find_merged_articles(source)
        if not articles:
            print("错误：未在输入中找到「检索文章」（content.data.检索文章 或顶层 检索文章）。\n"
                  "请确认传入的是检索/merge 产物；已是通用 JSON 时无需本脚本，可直接给渲染器。",
                  file=sys.stderr)
            return 2
        materials = [map_merged_article(a) for a in articles]
        if args.policy_files:
            filled = apply_policy_files(materials, source)
            if filled:
                print(f"policyFiles 文号回填：{filled} 条")
    else:
        raw = source_meta.get("materials") if isinstance(source_meta.get("materials"), list) else []
        recalled = source_meta.get("recalled_materials") if isinstance(source_meta.get("recalled_materials"), list) else []
        materials = ([map_assembly_material(x, used=True) for x in raw if isinstance(x, dict)]
                     + [map_assembly_material(x, used=False) for x in recalled if isinstance(x, dict)])
        if not materials:
            print("错误：装配 JSON 中没有 materials / recalled_materials。", file=sys.stderr)
            return 2

    # 编号缺省补齐（与渲染器口径一致：按数组顺序 1-based）
    for idx, material in enumerate(materials):
        if not first_str(material.get("编号")):
            material["编号"] = str(idx + 1)

    # 答案：文件 > 命令行 > 输入 JSON 自带
    answer = ""
    if args.answer_file:
        try:
            answer = resolve_input_path(args.answer_file, run_dir, {".txt", ".md"}).read_text(encoding="utf-8")
        except (RunPathError, OSError) as exc:
            print(f"错误：答案文件无法读取（{exc}）", file=sys.stderr)
            return 2
    elif args.answer:
        answer = args.answer
    else:
        answer = first_str(source_meta.get("answer"), source_meta.get("答案"),
                           source_meta.get("document_content"))

    question = ""
    if args.question_file:
        try:
            question = resolve_input_path(args.question_file, run_dir, {".txt", ".md"}).read_text(encoding="utf-8").strip()
        except (RunPathError, OSError) as exc:
            print(f"错误：问题文件无法读取（{exc}）", file=sys.stderr)
            return 2
    else:
        question = first_str(args.question, source_meta.get("question"), source_meta.get("问题"))

    self_check: Any = None
    if args.self_check_file:
        try:
            self_check = load_json_file(resolve_input_path(args.self_check_file, run_dir, {".json"}))
        except (RunPathError, json.JSONDecodeError, OSError) as exc:
            print(f"错误：自检文件无法读取（{exc}）", file=sys.stderr)
            return 2
    else:
        self_check = source_meta.get("selfCheck") or source_meta.get("self_check")

    verify_record: Any = None
    if args.verify_file:
        try:
            verify_record = load_json_file(resolve_input_path(args.verify_file, run_dir, {".json"}))
        except (RunPathError, json.JSONDecodeError, OSError) as exc:
            print(f"错误：核验记录无法读取（{exc}）", file=sys.stderr)
            return 2

    payload: Dict[str, Any] = {
        "title": first_str(args.title, source_meta.get("title")) or question,
        "question": question,
        "answer": answer,
        "materials": materials,
    }
    if isinstance(self_check, dict) and self_check:
        payload["selfCheck"] = self_check
    if isinstance(verify_record, dict) and verify_record:
        payload["verifyRecord"] = verify_record
    if args.stage:
        payload["stage"] = args.stage

    # 中间产物允许覆盖同名（每次重新生成 input.json），不做 _v2 另存
    output_name = args.output or "input.json"
    raw_output = Path(output_name).expanduser()
    if raw_output.is_absolute():
        output = raw_output.resolve()
    elif run_dir is not None:
        output = (run_dir / raw_output).resolve()
    else:
        print("错误：相对 --output 必须同时用 --run 指定运行目录", file=sys.stderr)
        return 2
    if output.suffix.lower() != ".json":
        output = output.with_suffix(".json")
    if output == SKILL_ROOT or is_within(output, SKILL_ROOT):
        print(f"错误：产物不能写入 Skill 安装目录：{output}", file=sys.stderr)
        return 2

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已生成通用 JSON：{output}")
    print(f"  材料 {len(materials)} 条 · 答案 {len(answer)} 字 · 自检 {'有' if payload.get('selfCheck') else '无'}"
          f" · 核验记录 {'有' if payload.get('verifyRecord') else '无'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
