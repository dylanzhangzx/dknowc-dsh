#!/usr/bin/env python3
"""核验记录指纹（1.0.1）：把“核验结论”绑定到当时的答案与证据。

verify_claims.py 落盘时写入 record（answer_digest / evidence_digest / verdict）；
render_trace_html.py 渲染时按**当前**答案与证据重新计算并比对——

- 答案被改过（数字、措辞、角标映射变化）→ digest 不匹配；
- 补查/换材料后旧报告复用 → 证据集合（文章Id + 原文链接）不匹配。

任一不匹配即“核验记录已失效”，报告按硬错误判「核验未通过」，
必须重跑 verify_claims 后重新渲染，不得沿用旧绿标。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable

_CITE_RE = re.compile(r"\[(\d+)\]")


def canonical_answer(answer: str) -> str:
    """答案规范化：角标按首次出现重排为 1..N，其余原样。

    两侧（verify_claims 收到的原始答案 / render 收到的答案）各自规范化后比较，
    避免仅因角标重排产生假失效。
    """
    text = (answer or "").replace("\r\n", "\n")
    mapping: dict[str, str] = {}

    def _sub(match: re.Match) -> str:
        key = match.group(1)
        if key not in mapping:
            mapping[key] = str(len(mapping) + 1)
        return f"[{mapping[key]}]"

    return _CITE_RE.sub(_sub, text)


def answer_digest(answer: str) -> str:
    return hashlib.sha256(canonical_answer(answer).encode("utf-8")).hexdigest()


def evidence_digest(items: Iterable[dict]) -> str:
    """证据指纹：文章标识 + 原文链接的有序集合。

    两侧字段对齐：材料画像用 id（= 文章Id）+ url；渲染侧用 article_id + url。
    只用身份字段，不用角标编号（渲染会重排）与摘录文本（裁剪策略可能不同）。
    """
    pairs = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        article = str(item.get("article_id") or item.get("id") or "").strip()
        url = str(item.get("url") or "").strip().rstrip("/")
        if url == "接口未返回":
            url = ""
        if not article and not url:
            continue
        pairs.add((article, url))
    raw = json.dumps(sorted(pairs), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def stale_reason(record: Any, answer: str, items: Iterable[dict]) -> str:
    """返回失效原因；不为空即核验记录已失效。"""
    if not isinstance(record, dict) or not record:
        return "缺少核验记录指纹（record），无法确认核验对应当前答案与证据"
    if record.get("answer_digest") and record.get("answer_digest") != answer_digest(answer):
        return "核验记录与当前答案不一致（答案在核验后被修改过），需重新核验"
    if record.get("evidence_digest") and record.get("evidence_digest") != evidence_digest(items):
        return "核验记录与当前证据不一致（材料在核验后发生补查/变更），需重新核验"
    if not record.get("answer_digest") or not record.get("evidence_digest"):
        return "核验记录指纹不完整，无法确认核验对应当前答案与证据"
    return ""
