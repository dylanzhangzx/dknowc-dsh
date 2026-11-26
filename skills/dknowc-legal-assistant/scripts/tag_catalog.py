#!/usr/bin/env python3
"""政策分类标签目录：路径解析与校验（2026-11-05，业务方提供清单）。

目录来源：钉钉表格《政策分类标签清单》→ reference/policy_tags.json，裁剪版 250 条（全量 1,633 条保留在内部工作区，不随公开包分发）。
每条含：标签类型、一级/二级/三级分类、ICS code、最终标签名、标签ID、标签编码、创建状态。

用途：
1) 解析：传短名（如「金融监管行业」）自动补成接口要求的完整路径
   （`政策/行业标签/金融监管行业`）；
2) 校验：把可信搜索接口 V2 返回的 `文件标签` 逐个对照目录，找出目录里没有的路径；
3) 与 legal_search.py 集成：`--policy-labels` 自动解析短名，检索结果自动校验标签。

只读本地目录，不发起网络请求。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

CATALOG_PATH = Path(__file__).resolve().parent.parent / "reference" / "policy_tags.json"


class Catalog:
    def __init__(self, entries: Iterable[Dict[str, Any]]):
        self.entries = [e for e in entries if e.get("最终标签名")]
        self.by_path: Dict[str, Dict[str, Any]] = {e["最终标签名"]: e for e in self.entries}
        self.by_leaf: Dict[str, List[str]] = defaultdict(list)
        self.by_type: Dict[str, List[str]] = defaultdict(list)
        # 本地目录只收法律/主题/行业三类（ICS 与本 skill 无关，未收）。
        # 用前两段作为"已覆盖前缀"，目录外但类型未覆盖的标签不当作错误。
        self.covered_prefixes = {"/".join(p.split("/")[:2]) for p in self.by_path}
        for e in self.entries:
            path = e["最终标签名"]
            self.by_leaf[path.rsplit("/", 1)[-1]].append(path)
            self.by_type[e.get("标签类型") or ""].append(path)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Catalog":
        p = Path(path) if path else CATALOG_PATH
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls(data)

    # ---------- 解析 ----------
    def resolve(self, name: str) -> List[str]:
        """把用户写法解析成目录里的完整路径。

        支持三种写法：完整路径、路径后缀（如「行业标签/金融监管行业」）、叶子名。
        返回按路径排序去重后的候选；空列表表示目录里没有。
        """
        name = (name or "").strip().strip("／").replace("／", "/")
        if not name:
            return []
        if name in self.by_path:
            return [name]
        suffix = "/" + name
        hits = [p for p in self.by_path if p.endswith(suffix)]
        if hits:
            return sorted(set(hits))
        leaf_hits = sorted(set(self.by_leaf.get(name, [])))
        if leaf_hits:
            return leaf_hits
        # 父级路径（如「法律」「政策/行业标签」）本身可能不在明细里，但它是目录中
        # 一批路径的公共前缀；接口支持前缀匹配，按前缀原样返回。
        prefix = name + "/"
        if any(p.startswith(prefix) for p in self.by_path):
            return [name]
        return []

    def resolve_unique(self, name: str) -> Optional[str]:
        hits = self.resolve(name)
        return hits[0] if len(hits) == 1 else None

    # ---------- 校验 ----------
    def is_valid(self, path: str) -> bool:
        return (path or "").strip() in self.by_path

    def type_of(self, path: str) -> str:
        e = self.by_path.get((path or "").strip())
        return (e or {}).get("标签类型", "")

    def unknown_in_articles(self, articles: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
        """检查检索返回的文章标签，列出目录中不存在的路径及出处。"""
        bad: List[Dict[str, str]] = []
        for a in articles or []:
            title = str(a.get("文章标题") or "")[:40]
            for tag in a.get("文件标签") or []:
                tag = str(tag or "").strip()
                if not tag or tag in self.by_path:
                    continue
                prefix = "/".join(tag.split("/")[:2])
                if prefix not in self.covered_prefixes:
                    continue  # 本地目录未收录该类（如 ICS），不算目录外
                bad.append({"文章": title, "文件标签": tag})
        return bad


def resolve_many(labels: Iterable[str], catalog: Optional[Catalog] = None) -> List[str]:
    """把一组标签写法解析成完整路径；解析不到或歧义的保留原值（交给接口判定）。"""
    cat = catalog or Catalog.load()
    out: List[str] = []
    for raw in labels:
        raw = (raw or "").strip()
        if not raw:
            continue
        path = cat.resolve_unique(raw)
        if path is None and not cat.resolve(raw):
            print(f"标签目录：未找到「{raw}」，按原值传给接口", file=sys.stderr)
        elif path is None:
            print(f"标签目录：「{raw}」命中多个路径，按原值传给接口（{'; '.join(cat.resolve(raw)[:4])}）",
                  file=sys.stderr)
        out.append(path or raw)
    return out


def describe(entries: Iterable[Dict[str, Any]]) -> str:
    from collections import Counter
    c = Counter(e.get("标签类型") or "" for e in entries)
    return "｜".join(f"{k} {v}" for k, v in sorted(c.items()))


def main() -> None:
    ap = argparse.ArgumentParser(description="政策分类标签目录：解析短名 / 校验接口返回标签")
    ap.add_argument("--resolve", help="按完整路径、路径后缀或叶子名解析完整路径")
    ap.add_argument("--check", help="校验 legal_search.py 输出 JSON 里所有 文件标签")
    ap.add_argument("--type", help="列出某一标签类型下的全部路径（如 【DT】行业标签）")
    ap.add_argument("--catalog", help="目录 JSON 路径（默认 skill 内 reference/policy_tags.json）")
    args = ap.parse_args()
    cat = Catalog.load(Path(args.catalog) if args.catalog else None)

    if args.resolve:
        hits = cat.resolve(args.resolve)
        if not hits:
            print("未找到")
            raise SystemExit(1)
        for h in hits:
            print(h)
        return

    if args.type:
        for p in sorted(cat.by_type.get(args.type, [])):
            print(p)
        return

    if args.check:
        data = json.loads(Path(args.check).read_text(encoding="utf-8"))
        arts = ((data.get("content") or {}).get("data") or {}).get("检索文章") or []
        bad = cat.unknown_in_articles(arts)
        total = sum(len(a.get("文件标签") or []) for a in arts)
        print(f"文章 {len(arts)} 篇，标签 {total} 个，目录外 {len(bad)} 个")
        for b in bad:
            print(f"  ✗ {b['文件标签']}  ← {b['文章']}")
        return

    print(f"目录条目：{len(cat.entries)}（{describe(cat.entries)}）")


if __name__ == "__main__":
    main()
