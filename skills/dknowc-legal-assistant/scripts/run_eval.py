#!/usr/bin/env python3
"""深知法律助手 · 30 题法条检索评测。

每部法只解析一次（001 → 003 → 002/005 → 选本），再对每个条号做切分与校验。
指标：法名命中 / 条号命中 / 关键词命中 / 版本标记命中。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
import legal_search as ls  # type: ignore
import legal_client as c  # type: ignore

ROOT = Path(__file__).resolve().parent.parent


def norm(text: str) -> str:
    return ls.norm_title(text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", default=str(ROOT / "eval" / "questions.jsonl"))
    parser.add_argument("--limit-laws", type=int, default=0, help="只跑前 N 部法（0=全部）")
    parser.add_argument("--output", default=str(ROOT / "eval" / "results_latest.json"))
    args = parser.parse_args()

    questions = [json.loads(line) for line in Path(args.questions).read_text(encoding="utf-8").splitlines() if line.strip()]
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for q in questions:
        groups.setdefault(q["law"], []).append(q)
    laws = list(groups.keys())
    if args.limit_laws:
        laws = laws[: args.limit_laws]

    rows: List[Dict[str, Any]] = []
    for law in laws:
        started = time.time()
        try:
            resolved = ls.resolve_law(law, article=str(groups[law][0]["article"]))
        except Exception as exc:  # noqa: BLE001
            for q in groups[law]:
                rows.append({
                    "id": q["id"], "law": law, "article": q["article"],
                    "law_ok": False, "article_found": False, "keyword_ok": False,
                    "marker_ok": False, "error": str(exc), "selected": "", "source": "",
                    "latency_s": round(time.time() - started, 1),
                })
            print(f"[FAIL] {law}: {exc}", flush=True)
            continue

        selected_title = str(resolved.selected.candidate.get("title") or "")
        selected_source = str(resolved.selected.candidate.get("sourceUrl") or "")
        core = law.replace("中华人民共和国", "")
        law_ok = (norm(core) in norm(selected_title)) or (norm(law) in norm(selected_title)) or (norm(selected_title) in norm(law))
        for q in groups[law]:
            article_text = ls.extract_article(resolved.selected.text, q["article"])
            article_found = bool(article_text)
            keyword_ok = bool(article_text and q["keyword"] in article_text)
            rows.append({
                "id": q["id"], "law": law, "article": q["article"],
                "law_ok": law_ok, "article_found": article_found, "keyword_ok": keyword_ok,
                "marker_ok": bool(resolved.selected.marker_hit),
                "status_fallback": bool(resolved.status_fallback),
                "selected": selected_title, "source": selected_source,
                "status": str(resolved.selected.candidate.get("validityStatus") or ""),
                "latest_version": resolved.marker,
                "latency_s": round(time.time() - started, 1),
                "error": "",
            })
        print(f"[OK] {law} | {selected_title[:36]} | marker={resolved.selected.marker_hit} | {len(groups[law])} 题", flush=True)

    total = len(rows)
    law_n = sum(1 for r in rows if r["law_ok"])
    art_n = sum(1 for r in rows if r["article_found"])
    kw_n = sum(1 for r in rows if r["keyword_ok"])
    mk_n = sum(1 for r in rows if r["marker_ok"])
    fb_n = sum(1 for r in rows if r.get("status_fallback"))
    print("\n=== 明细 ===")
    print(f"{'id':<5}{'法名':<8}{'条号':<6}{'关键词':<8}{'版本标记':<8}{'法律'}")
    for r in rows:
        print(f"{r['id']:<5}{'✓' if r['law_ok'] else '✗':<8}{'✓' if r['article_found'] else '✗':<6}"
              f"{'✓' if r['keyword_ok'] else '✗':<8}{'✓' if r['marker_ok'] else '✗':<8}{r['law'][:28]}")
    print("\n=== 汇总 ===")
    print(f"题目数 {total}｜法名命中 {law_n}/{total} ({law_n/total:.0%})｜条号命中 {art_n}/{total} ({art_n/total:.0%})"
          f"｜关键词命中 {kw_n}/{total} ({kw_n/total:.0%})｜版本标记命中 {mk_n}/{total} ({mk_n/total:.0%})"
          f"｜失效回退 {fb_n}/{total}")

    out = {
        "total": total,
        "law_ok": law_n,
        "article_found": art_n,
        "keyword_ok": kw_n,
        "marker_ok": mk_n,
        "rows": rows,
    }
    Path(args.output).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"结果已写入：{args.output}")


if __name__ == "__main__":
    main()
