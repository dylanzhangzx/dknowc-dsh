#!/usr/bin/env python3
"""深知可信PPT 的通用输入入口（1.7.0）：统一入口 + 本产品字段透传。

在内核 `build_report_input.py`（兄弟 skill dk-trace-report，merged 适配器）之上补充本产品的字段语义：
- 复用其「检索文章 → materials」映射与 `--policy-files` 文号回填；
- 透传 merge 产物的 `search_meta`（含 calls 补搜增量）——统一入口只保留
  材料/答案/自检等核心字段，过程条「该路新增 N 篇 · 补充 K 段」依赖 search_meta.calls；
- 旧式顶层 `检索记录` 归一到 search_meta.calls（label 取 purpose/query 标签）；
- 顶层 `verification_checks` 透传为渲染器的 `verificationChecks`（需人工复核事项）。

输出仍是标准通用 JSON，渲染器不需要任何本产品定制。用法与内核入口一致：
    python3 build_trace_input.py merged.json --run "$RUN" --output input.json \
        --answer-file answer.txt --question "用户问题" \
        --self-check-file selfcheck.json --stage outline --policy-files
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# dsh：内核抽离到插件内兄弟 skill「溯源核验报告生成器」（dk-trace-report），
# 此处注入其 scripts 目录到 sys.path；母版同目录形态下目录不存在、行为不变。
import sys as _sys
from pathlib import Path as _Path
_KERNEL_DIR = _Path(__file__).resolve().parent.parent.parent / "dk-trace-report" / "scripts"
if _KERNEL_DIR.is_dir():
    _sys.path.insert(0, str(_KERNEL_DIR))

import build_report_input as base
from run_paths import RunPathError, SKILL_ROOT, is_within, resolve_input_path, resolve_run_dir


def carry_runtime_meta(payload: Dict[str, Any], source: Dict[str, Any]) -> None:
    """把检索/合并产物里的过程元数据透传到通用 JSON（渲染器按 search_meta.calls 展示补搜增量）。"""
    meta = source.get("search_meta") if isinstance(source.get("search_meta"), dict) else None
    legacy = source.get("检索记录") if isinstance(source.get("检索记录"), list) else None
    calls: List[Dict[str, Any]] = []
    if meta and isinstance(meta.get("calls"), list):
        calls = [c for c in meta["calls"] if isinstance(c, dict)]
    elif legacy:
        for entry in legacy:
            if not isinstance(entry, dict):
                continue
            label = base.first_str(entry.get("purpose"), entry.get("query"),
                                   entry.get("通道"), entry.get("label"))
            calls.append({
                "label": label,
                "new_articles": entry.get("new_articles", entry.get("新增文章")),
                "added_paragraphs": entry.get("added_paragraphs", entry.get("补充段落")),
            })
    merged: Dict[str, Any] = dict(meta or {})
    if calls:
        merged["calls"] = calls
    if merged:
        payload["search_meta"] = merged
    checks = source.get("verification_checks") or source.get("verificationChecks")
    if isinstance(checks, list) and checks:
        payload["verificationChecks"] = [str(x) for x in checks if str(x).strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="深知可信PPT：检索/merge 产物 → 通用 JSON")
    parser.add_argument("source_json", help="检索/merge 产物（content.data.检索文章 或顶层 检索文章）")
    parser.add_argument("--run", help="本次运行的独立目录（相对路径基准；必须在 Skill 目录之外）")
    parser.add_argument("--output", help="输出通用 JSON 文件名；相对名落 --run 目录（默认 input.json）")
    parser.add_argument("--answer-file", help="最终答案文件（.txt/.md，关键结论带 [n] 角标）")
    parser.add_argument("--answer", help="最终答案文本（文件优先）")
    parser.add_argument("--question", help="用户原始问题")
    parser.add_argument("--question-file", help="用户原始问题全文文件")
    parser.add_argument("--self-check-file", help="答案自检结果 JSON（键集由 config 的 selfcheck.labels 决定）")
    parser.add_argument("--verify-file", help="域内核验记录 JSON（原样嵌入）")
    parser.add_argument("--title", help="报告标题；缺省取输入 JSON 的 title 或问题")
    parser.add_argument("--stage", choices=["outline", "final"], help="双版阶段标识（提纲版/成稿版）")
    parser.add_argument("--policy-files", action="store_true",
                        help="用 policyFiles 的 writtenText 回填空缺发文字号")
    args = parser.parse_args()

    try:
        run_dir = resolve_run_dir(args.run) if args.run else None
    except RunPathError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    try:
        source_path = resolve_input_path(args.source_json, run_dir, {".json"})
        source = base.load_json_file(source_path)
    except (RunPathError, json.JSONDecodeError, OSError) as exc:
        print(f"错误：输入无法读取（{exc}）", file=sys.stderr)
        return 2

    articles = base.find_merged_articles(source)
    if not articles:
        print("错误：未在输入中找到「检索文章」（content.data.检索文章 或顶层 检索文章）。", file=sys.stderr)
        return 2
    materials = [base.map_merged_article(a) for a in articles]
    if args.policy_files:
        filled = base.apply_policy_files(materials, source)
        if filled:
            print(f"policyFiles 文号回填：{filled} 条")
    for idx, material in enumerate(materials):
        if not base.first_str(material.get("编号")):
            material["编号"] = str(idx + 1)

    source_meta = source if isinstance(source, dict) else {}
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
        answer = base.first_str(source_meta.get("answer"), source_meta.get("答案"))

    question = ""
    if args.question_file:
        try:
            question = resolve_input_path(args.question_file, run_dir, {".txt", ".md"}).read_text(encoding="utf-8").strip()
        except (RunPathError, OSError) as exc:
            print(f"错误：问题文件无法读取（{exc}）", file=sys.stderr)
            return 2
    else:
        question = base.first_str(args.question, source_meta.get("question"), source_meta.get("问题"))

    self_check: Any = None
    if args.self_check_file:
        try:
            self_check = base.load_json_file(resolve_input_path(args.self_check_file, run_dir, {".json"}))
        except (RunPathError, json.JSONDecodeError, OSError) as exc:
            print(f"错误：自检文件无法读取（{exc}）", file=sys.stderr)
            return 2
    else:
        self_check = (source_meta.get("selfCheck") or source_meta.get("self_check")
                     or source_meta.get("agentCheck") or source_meta.get("agent_check"))

    verify_record: Any = None
    if args.verify_file:
        try:
            verify_record = base.load_json_file(resolve_input_path(args.verify_file, run_dir, {".json"}))
        except (RunPathError, json.JSONDecodeError, OSError) as exc:
            print(f"错误：核验记录无法读取（{exc}）", file=sys.stderr)
            return 2

    payload: Dict[str, Any] = {
        "title": base.first_str(args.title, source_meta.get("title")) or question,
        "question": question,
        "answer": answer,
        "materials": materials,
    }
    if args.stage:
        payload["stage"] = args.stage
    if isinstance(self_check, dict) and self_check:
        payload["selfCheck"] = self_check
    if isinstance(verify_record, dict) and verify_record:
        payload["verifyRecord"] = verify_record
    carry_runtime_meta(payload, source_meta)

    raw_output = Path(args.output or "input.json").expanduser()
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
    print(f"  材料 {len(materials)} 条 · 答案 {len(answer)} 字"
          f" · 自检 {'有' if payload.get('selfCheck') else '无'}"
          f" · 补搜记录 {len((payload.get('search_meta') or {}).get('calls') or [])} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
