#!/usr/bin/env python3
"""深知法律助手 · 法律检索脚本。

两种模式：
1) 法条模式（--law + --article）：001 定位法律 → 003 版本 → 002/005 取全文 → 本地切条。
2) 语义模式（仅 --query）：012 可信搜索（法律标签/关闭时效过滤）召回候选材料。

输出为可信搜索同构 JSON（content.data.检索文章），可直接交给 render_trace_html.py 生成
溯源核验报告。

设计口径（2026-10-30 与用户确认）：
- 仅覆盖中国大陆法律；港澳/新加坡不在范围。
- validityStatus=EXPIRED_OR_REPEALED 视为失效并排除；OTHER 暂按现行有效（数据仍在治理）。
- OTHER 不等于文本是现行版：同一部法存在多个镜像副本，必须用 003 的最新修正日期做正文标记校验，
  选出真正的现行合并本。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import legal_client as client
try:
    import tag_catalog
except Exception:  # 目录缺失时不影响检索
    tag_catalog = None  # type: ignore

SKILL_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = SKILL_ROOT / "official-docs" / "search-results"

CN_DIGITS = "零一二三四五六七八九"
MIN_ARTICLE_CHARS = 10

HEAD_RE = re.compile(r"第[零一二三四五六七八九十百千〇]+条(?:之[一二三四五六七八九十]+)?")
CHAPTER_RE = re.compile(r"第[零一二三四五六七八九十百千〇]+(?:分)?[章节编]")
BAD_TITLE_WORDS = (
    "通知", "报告", "意见", "批复", "答复", "解读", "宣传提纲", "学习", "检查",
    "修正案", "修改决定", "决定", "解释", "办法", "指引", "公告", "问答", "案例", "判决", "裁定",
    "草案", "审议", "说明", "贯彻", "宣传", "讲话", "培训", "征文", "执行部分", "情况汇报",
    "实施条例",
)


# ---------- 文本工具 ----------

def normalize_width(text: str) -> str:
    out = []
    for ch in text or "":
        code = ord(ch)
        if 0xFF10 <= code <= 0xFF19:  # 全角数字
            out.append(chr(code - 0xFF10 + ord("0")))
        elif code == 0x3000:
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def int_to_cn(n: int) -> str:
    if n <= 0:
        return str(n)
    if n < 10:
        return CN_DIGITS[n]
    if n == 10:
        return "十"
    if 10 < n < 20:
        return "十" + CN_DIGITS[n % 10]
    digits = str(n)
    length = len(digits)
    units = ["", "十", "百", "千"]
    res = ""
    zero = False
    for i, ch in enumerate(digits):
        d = int(ch)
        pos = length - i - 1
        if d == 0:
            zero = True
            continue
        if zero and res:
            res += "零"
        zero = False
        res += CN_DIGITS[d] + units[pos]
    return res


def normalize_article(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    m = re.search(r"(\d+)", raw)
    if m and "条" not in raw:
        return "第" + int_to_cn(int(m.group(1))) + "条"
    m = re.search(r"第([零一二三四五六七八九十百千〇\d]+)条", raw)
    if m:
        body = m.group(1)
        if body.isdigit():
            body = int_to_cn(int(body))
        return "第" + body + "条"
    return raw


def parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    text = normalize_width(str(value)).strip()
    for fmt in ("%Y-%m-%d", "%Y年%m月%d日", "%Y/%m/%d", "%Y-%m", "%Y年%m月"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    m = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def format_date(value: Optional[date]) -> str:
    return value.strftime("%Y-%m-%d") if value else ""


def marker_variants(value: Optional[date]) -> List[str]:
    if not value:
        return []
    return [
        f"{value.year}年{value.month}月{value.day}日",
        f"{value.year}年{value.month:02d}月{value.day:02d}日",
        f"{value.year}-{value.month:02d}-{value.day:02d}",
        value.strftime("%Y.%m.%d"),
    ]


def norm_title(text: str) -> str:
    return re.sub(r"[\s《》()（）\[\]【】·—\-]", "", text or "")


def title_score(title: str, law: str) -> int:
    t = norm_title(title)
    if not t:
        return 0
    bases = [law]
    if law.startswith("中华人民共和国"):
        bases.append(law[len("中华人民共和国"):])
    best = 0
    for base in bases:
        l = norm_title(base)
        if not l:
            continue
        if t == l:
            best = max(best, 10)
        elif t.startswith(l):
            best = max(best, 8)
        elif l in t:
            best = max(best, 5)
    return best


def bad_title_extra(title: str, law: str) -> bool:
    extra = norm_title(title).replace(norm_title(law), "")
    if not extra:
        return False
    return any(word in extra for word in BAD_TITLE_WORDS)


def host_of(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        host = ""
    return host


def snippet(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit]


# ---------- 选本 ----------

@dataclass
class CopyEval:
    candidate: Dict[str, Any]
    score: float
    title_score: int
    bad_extra: bool
    expired: bool = False
    content: Dict[str, Any] = field(default_factory=dict)
    text: str = ""
    marker_hit: bool = False
    article_hit: bool = False
    written: Optional[date] = None
    reason: str = ""


@dataclass
class Resolved:
    law: str
    selected: CopyEval
    versions: List[Dict[str, Any]]
    latest_version_date: Optional[date]
    marker: str
    evaluated: List[CopyEval]
    article: str = ""
    status_fallback: bool = False


def _rank_candidates(law: str, candidates: Iterable[Dict[str, Any]], latest: Optional[date]) -> List[CopyEval]:
    scored: List[CopyEval] = []
    for c in candidates:
        status = str(c.get("validityStatus") or "")
        ts = title_score(str(c.get("title") or ""), law)
        if ts == 0:
            continue
        # 派生文件直接剔除（2026-11-05，对比实验 Q1 实测）：查《劳动合同法》时其实施条例、
        # 修改决定等副本因标题前缀匹配进入候选池，只减分挡不住"日期+20/条号命中"翻盘——
        # 实测失效回退时选中实施条例副本，切出的是条例条文。派生词出现在"标题减去法名"
        # 的剩余部分时整条剔除（用户查的就是派生法时，剩余部分不含该词，不受影响）。
        extra = norm_title(str(c.get("title") or "")).replace(norm_title(law), "")
        if any(w in extra for w in ("实施条例", "实施细则", "实施办法", "细则", "修改决定", "修正案", "草案", "征求意见稿")):
            continue
        bad = bad_title_extra(str(c.get("title") or ""), law)
        written = parse_date(c.get("writtenDate"))
        length = int(c.get("contentLength") or 0)
        score = ts * 10 + min(length / 10000.0, 5.0)
        if bad:
            score -= 15
        if status == "EXPIRED_OR_REPEALED":
            score -= 8
        if latest and written == latest:
            score += 20
        reason = f"标题匹配{ts}/10"
        if latest and written == latest:
            reason += f"；成文日期=最新修正日{format_date(latest)}"
        if bad:
            reason += "；标题含通知/草案等非正式文本词，降权"
        if status == "EXPIRED_OR_REPEALED":
            reason += "；库内状态=EXPIRED_OR_REPEALED"
        scored.append(CopyEval(
            candidate=c, score=score, title_score=ts, bad_extra=bad,
            expired=(status == "EXPIRED_OR_REPEALED"), written=written, reason=reason,
        ))
    scored.sort(key=lambda x: (-x.score, -int(x.candidate.get("contentLength") or 0)))
    return scored


def gather_candidates(law: str) -> List[Dict[str, Any]]:
    """001 的标题匹配对长标题（司法解释）偏严：全名可能只命中旧版。

    这里按全名 → 去掉“关于”前缀 → 去掉“审理”前缀 → 去掉“中华人民共和国”前缀
    逐步放宽，再去重合并。
    """
    variants: List[str] = [law]
    if "关于" in law:
        tail = law.split("关于", 1)[1]
        variants.append(tail)
        variants.append(re.sub(r"^审理", "", tail))
    if law.startswith("中华人民共和国"):
        variants.append(law[len("中华人民共和国"):])
    seen: Dict[str, Dict[str, Any]] = {}
    for variant in variants:
        if not variant.strip():
            continue
        try:
            items = client.filter_policies(variant.strip(), limit=30)
        except client.LegalApiError:
            continue
        for item in items:
            fid = str(item.get("encryptedFileId") or "")
            if fid and fid not in seen:
                seen[fid] = item
    return list(seen.values())


def _evaluate(ranked: List[CopyEval], latest: Optional[date], article: str, max_copies: int,
              cache: Dict[str, Tuple[Dict[str, Any], str]]) -> List[CopyEval]:
    out: List[CopyEval] = []
    for idx, item in enumerate(ranked):
        if len(out) >= max_copies:
            break
        fid = str(item.candidate.get("encryptedFileId") or "")
        if not fid:
            continue
        if fid not in cache:
            try:
                cache[fid] = client.get_full_text(fid)
            except client.LegalApiError:
                continue
        content, text = cache[fid]
        if not text:
            continue
        item.content = content
        item.text = text
        if latest:
            probes = marker_variants(latest)
            item.marker_hit = any(p in normalize_width(text) for p in probes)
        if article:
            item.article_hit = bool(extract_article(text, article))
        item.score += 30 if item.marker_hit else 0
        if article:
            item.score += 45 if item.article_hit else -20
        if item.marker_hit:
            item.reason += f"；正文含最新修正日标记{format_date(latest)}"
        elif latest:
            item.reason += "；正文未命中最新修正日标记"
        if article:
            item.reason += "；含目标条号" if item.article_hit else "；未含目标条号"
        out.append(item)
        # 按需下载（2026-11-05）：拿到一份「非失效 + 含最新修正日标记 +（如指定）含目标条号」
        # 的副本就停，不再把前 4 份全部下下来比对。正常一部法只花 1 次 002+005，
        # 只有遇到残篇/旧版/串档副本时才继续下下一份兜底。
        if article and not item.article_hit:
            continue
        if not item.expired:
            break
        # 选中副本是失效状态：只有在后面已经没有"像样的非失效候选"时才停。
        # 「像样」= 标题匹配度 ≥8；版本链噪音里常混进修改决定、实施规定等低分同名项，
        # 为它们多下全文没有意义（2026-11-05 社会保险法实测：后面 3 份全是低分杂项）。
        if not any((not later.expired) and later.title_score >= 8 for later in ranked[idx + 1:]):
            break
    return out


def _pick(evaluated: List[CopyEval], article: str) -> Tuple[CopyEval, bool]:
    """按“不失效优先、含目标条号优先、版本标记优先”选本。

    返回 (selected, status_fallback)。status_fallback=True 表示库里没有可用的
    OTHER/有效副本，只能回退到 EXPIRED_OR_REPEALED 的全文，报告中必须如实提示。
    """
    def key(item: CopyEval) -> Tuple:
        return (
            1 if item.article_hit else 0,
            1 if item.marker_hit else 0,
            item.score,
            item.written or date.min,
            len(item.text),
        )

    # 正文是否含最新修正日标记，比文件级 validityStatus 更接近“文本是否现行”。
    # 优先级：含目标条号 > 含最新修正日标记 > 非失效 > 分数。
    # 若最终选中的是失效副本（标记命中但状态存疑），status_fallback=True，报告必须提示复核。
    def key2(item: CopyEval) -> Tuple:
        # 条号命中优先只对标题精确同名的副本生效（2026-11-05，对比实验 Q1 实测）：
        # 实施条例等派生法与本体法条号大量重合（条例也有第36/40/47条），非精确同名副本
        # 的 article_hit 会被跨文件同条号欺骗，不得作为选本依据。
        article_hit_trusted = item.article_hit and item.title_score >= 10
        return (
            1 if article_hit_trusted else 0,
            1 if item.marker_hit else 0,
            0 if item.expired else 1,
            item.score,
            item.written or date.min,
            len(item.text),
        )

    hits = [e for e in evaluated if e.article_hit] if article else list(evaluated)
    pool = hits or evaluated
    if not pool:
        raise client.LegalApiError("resolve", "候选正文均下载失败")
    selected = max(pool, key=key2)
    return selected, bool(selected.expired)



def _pick_version_by_date(versions: List[Dict[str, Any]], ref_date: date) -> Optional[Dict[str, Any]]:
    """按基准日挑适用版本（2026-11-05）。

    003 历次版本返回每个版本的 inferredApplicableFrom/To 适用区间，直接按区间命中；
    这样"2015 版第 26 条（24%/36%）"这类旧法条文不用靠 Agent 试查询词，也不会被
    最新版同名条号顶掉。
    """
    for item in versions or []:
        # 版本链里的"关于修改…的决定"是修正案本身，不是整合后的法律文本，跳过
        if "关于修改" in str(item.get("title") or "") or str(item.get("title") or "").endswith("决定"):
            continue
        start = parse_date(item.get("inferredApplicableFrom") or item.get("statedEffectiveDate")
                           or item.get("statedWrittenDate"))
        end = parse_date(item.get("inferredApplicableTo"))
        if start and start <= ref_date and (end is None or ref_date <= end):
            return item
    return None

def resolve_law(law: str, max_copies: int = 6, article: str = "",
                reference_date: Optional[date] = None) -> Resolved:
    candidates = gather_candidates(law)
    if not candidates:
        raise client.LegalApiError("resolve", f"001 未找到标题包含「{law}」的政策/法律文件")

    # 种子优先用标题最完整、日期最新的副本，查版本链拿最新修正日期
    seed_rank = _rank_candidates(law, candidates, None)
    if not seed_rank:
        raise client.LegalApiError("resolve", f"「{law}」的候选均被标题规则排除")
    # 种子要挑“标题最完整 + 成文日期最新”的副本：同一部法的多个镜像里，旧版可能更长，
    # 只按长度会拿到旧版，进而把 003 的最新修正日期也带错。
    seed_eval = max(
        seed_rank,
        key=lambda e: (e.title_score, e.written or date.min, int(e.candidate.get("contentLength") or 0)),
    )
    seed = seed_eval.candidate
    versions: List[Dict[str, Any]] = []
    latest: Optional[date] = None
    try:
        versions = client.query_versions(str(seed.get("encryptedFileId") or "")).get("versions") or []
        # 003 的版本链会串到相邻文件：查《食品安全法》返回《食品安全法实施条例》的版本，
        # 查《劳动合同法实施条例》返回《劳动合同法》的版本。只保留标题确实是本法（或本法
        # 的修正/修订版）的版本，避免用错误的最新修正日期做正文标记。
        law_key = norm_title(law)
        core_key = norm_title(
            law.replace("最高人民法院", "").replace("最高人民检察院", "").replace("中华人民共和国", "")
        )
        kept = []
        for item in versions:
            vt = norm_title(item.get("title") or "")
            if not vt:
                kept.append(item)
                continue
            if vt == law_key or vt.startswith(law_key + "（") or vt.startswith(law_key + "("):
                kept.append(item)
                continue
            # 栏目/版本后缀（2026-11-05，T8 实测）：版本条目标题 = 法名 +【执法职责、执法依据、
            # 执法程序】之类括注，norm_title 剥掉【】后既不等于法名也不带"（"前缀，会被当成
            # 串档版本丢掉——实测《行政处罚法》2021 版条目因此被滤掉，latest 落到 1996 制定日。
            # 在原始标题上判：以法名开头、剩余部分是括注（【（〔[ 开头）即视为本法版本。
            # "实施条例"等实体性后缀不以括注开头，仍被排除，串档保护不受影响。
            raw_t = str(item.get("title") or "").strip()
            raw_law = law.strip()
            if raw_law and raw_t.startswith(raw_law):
                extra = raw_t[len(raw_law):].strip()
                if extra and extra[0] in "【（(〔[":
                    kept.append(item)
                    continue
            # 修正/修订/修改决定：标题里嵌了本法名称，但整串不等于法名。
            # 例如“最高人民法院关于修改《关于审理民间借贷案件适用法律若干问题的规定》的决定”。
            if core_key and core_key in vt and any(w in vt for w in ("修正", "修订", "修改")):
                if "实施条例" not in vt:
                    kept.append(item)
        versions = kept
        dates = [parse_date(v.get("statedWrittenDate")) for v in versions]
        dates = [d for d in dates if d]
        latest = max(dates) if dates else None
    except client.LegalApiError:
        versions = []
        latest = None

    # 基准日选版本（2026-11-05）：查旧法/跨期问题时按 003 的适用区间取当时文本。
    if reference_date:
        chosen = _pick_version_by_date(versions, reference_date)
        vid = str((chosen or {}).get("encryptedVersionId") or "")
        if chosen and vid:
            try:
                content = client.get_content("", version_id=vid)
                url = str(((content.get("contentFile") or {}).get("downloadUrl") or "")).strip()
                text = client.download_text(url) if url else ""
            except client.LegalApiError:
                text = ""
            if text.strip():
                vdate = parse_date(chosen.get("statedWrittenDate")) or parse_date(chosen.get("inferredApplicableFrom"))
                cand = {
                    "encryptedFileId": vid,
                    "title": str(chosen.get("title") or law),
                    "documentNumber": str(chosen.get("documentNumber") or ""),
                    "writtenDate": format_date(vdate) if vdate else "",
                    "validityStatus": "",
                    "sourceUrl": str((content.get("sourceUrl") or "") or ""),
                }
                item = CopyEval(
                    candidate=cand, score=100.0, title_score=10, bad_extra=False, text=text,
                    written=vdate,
                    reason=(f"按基准日 {format_date(reference_date)} 选用 "
                            f"{format_date(vdate) if vdate else '历史'} 版"
                            f"（适用 {chosen.get('inferredApplicableFrom') or '?'}"
                            f"～{chosen.get('inferredApplicableTo') or '今'}）"),
                )
                if article:
                    item.article_hit = bool(extract_article(text, article))
                return Resolved(
                    law=law, selected=item, versions=versions,
                    latest_version_date=vdate,
                    marker=format_date(vdate) if vdate else "",
                    evaluated=[item], article=normalize_article(article) if article else "",
                    status_fallback=False,
                )

    ranked = _rank_candidates(law, candidates, latest)
    cache: Dict[str, Tuple[Dict[str, Any], str]] = {}
    evaluated = _evaluate(ranked, latest, article, max_copies, cache)
    if not evaluated:
        raise client.LegalApiError("resolve", f"「{law}」的候选正文均下载失败")

    selected, status_fallback = _pick(evaluated, article)
    return Resolved(
        law=law,
        selected=selected,
        versions=versions,
        latest_version_date=latest,
        marker=format_date(latest),
        evaluated=evaluated,
        article=normalize_article(article) if article else "",
        status_fallback=status_fallback,
    )


# ---------- 条文切分 ----------

_SENTENCE_BREAK = "。；！？"
_CHAPTER_TITLE_MAX = 40
# 结构标题只可能出现在文件开头、句末标点之后、或换行之后（允许标点与标题之间夹空格）。
# 书名号右半边 `》` 不算句首：“《劳动合同法》第三章”是引用他法章节，不是结构标题。
_HEADING_LEAD = "。；！？\n\r”）』」】"


def _at_sentence_start(text: str, start: int) -> bool:
    if start == 0:
        return True
    prev = text[start - 1]
    if prev in _HEADING_LEAD:
        return True
    if prev.isspace():
        j = start - 1
        newline = False
        while j >= 0 and text[j].isspace():
            if text[j] in "\n\r":
                newline = True
            j -= 1
        # 独立成行就是结构标题；同一行内的空格（如“第三章 第四十六条”）不算。
        if newline:
            return True
        return j < 0 or text[j] in _HEADING_LEAD
    return False


def _heading_positions(text: str) -> List[re.Match]:
    """条标题只认句首位置：文件开头、句末标点后、换行后。

    条内引用（“依照本法第四十六条”“劳动合同法第四十七条”“第三章 第四十六条”）
    前面是汉字、逗号或章标题，不是句首，一律排除。这比“前一个字符不是汉字”更严，
    能覆盖“章引用 + 条引用”的组合（2026-11-13 复审阻断）。
    """
    return [match for match in HEAD_RE.finditer(text) if _at_sentence_start(text, match.start())]


def _sentence_window(text: str, start: int) -> str:
    """取本句内、标题之前的文本（从上一个句末标点或换行开始）。"""
    for i in range(start - 1, -1, -1):
        if text[i] in _SENTENCE_BREAK or text[i] in "\n\r":
            return text[i + 1:start]
    return text[:start]


def _is_structural_chapter(text: str, start: int) -> bool:
    """判断“第X章/节/编”是结构标题还是条内引用。

    结构标题：文件开头、句末标点/换行之后；跟在文件标题后（“……劳动合同法第一章
    总则”）；或跟在分编/章/节标题后（“第二分编所有权第四章一般规定”）。
    条内引用：“依照本法第三章”“根据本条例第二章”——前面是「依照/根据/本法/本条例」。
    """
    if _at_sentence_start(text, start):
        return True
    prev = text[start - 1]
    if not re.match(r"[一-鿿]", prev):
        return False
    # 只看标题前的一小段：章标题很短，前后相邻的都是结构标题；拉整句会把正文里的
    # “包括”“除外”等词误当引用信号（民法典目录整段无句号时尤其明显）。
    window = text[max(0, start - 24):start]
    # 书名号 = 引用其他法律（“参见《劳动合同法》第三章”），不是本文件的结构标题。
    if "《" in window:
        return False
    if re.search(r"(本法|该法|本条例|本办法|本规定|本章|本节|本编)", window):
        return False
    if re.search(
        r"(依照|根据|按照|依据|参照|适用|违反|符合|具有|属于|包括|详见|参见|另见|载于)",
        window,
    ):
        return False
    if CHAPTER_RE.search(window) or re.search(r"(附则|附录|附件)$", window):
        return True
    # 文件标题直接接章标题：“……劳动合同法第一章总则”，前文必有法/条例/规定/办法等文种词。
    return bool(re.search(r"[法条例规定办法细则典]", window))


def _chapter_positions(text: str) -> List[int]:
    """只认结构章/节/编标题，排除条内引用。"""
    return [match.start() for match in CHAPTER_RE.finditer(text)
            if _is_structural_chapter(text, match.start())]


def _structural_headings(text: str) -> List[re.Match]:
    """条标题位置：常规标题 + 每个结构章标题后的第一条。

    行内引用（“劳动合同法第四十七条”“依照本法第四十六条”）仍然排除；章标题后的
    第一条是结构标题，必须保留，否则切条会越到下一章。只补每个章的第一条，避免把
    条内引用再当成条标题。
    """
    kept = _heading_positions(text)
    kept_starts = {match.start() for match in kept}
    chapters = _chapter_positions(text)
    all_heads = list(HEAD_RE.finditer(text))
    out = list(kept)
    added: set = set()
    for pos in chapters:
        nxt = next((m for m in all_heads if m.start() > pos), None)
        if nxt is None or nxt.start() in kept_starts or nxt.start() in added:
            continue
        gap = text[pos:nxt.start()]
        if len(gap) <= _CHAPTER_TITLE_MAX and not re.search(r"[。；！？\n\r]", gap):
            out.append(nxt)
            added.add(nxt.start())
    # “附则/附录/附件”不是第X章，但同样是结构标题；其后的第一条按结构条标题处理。
    for match in all_heads:
        if match.start() in kept_starts or match.start() in added:
            continue
        window = _sentence_window(text, match.start())
        if re.search(r"(附则|附录|附件)$", window) and len(window) <= 10:
            out.append(match)
            added.add(match.start())
    # 文件标题与第一条同行连写（“《中华人民共和国民法典》第一条 …”“中华人民共和国民法典
    # 第一条 …”）：只对本文件的第一条放行。若它前面已经切出过结构条标题，说明这是正文里
    # 引用他法（“劳动合同法第一条规定的义务”），不能当标题（2026-11-13 复审 4 建议）。
    for match in all_heads:
        if match.group() != "第一条" or match.start() in kept_starts or match.start() in added:
            continue
        # 前面已经有过结构条标题，说明本文件的条序已经开始，这个“第一条”是正文引用。
        if any(pos < match.start() for pos in kept_starts):
            continue
        window = _sentence_window(text, match.start())[-40:]
        if len(window) > 40 or re.search(r"(本法|该法|本条例|本办法|本规定|依照|根据|按照|依据|参照|适用|详见|参见)", window):
            continue
        if re.search(r"(法|典|条例|规定|办法|细则|章程|》)$", window):
            out.append(match)
            added.add(match.start())
    out.sort(key=lambda match: match.start())
    return out


def extract_article(text: str, article: str) -> Optional[str]:
    target = normalize_article(article)
    if not target:
        return None
    norm = normalize_width(text)
    matches = _structural_headings(norm)
    chapters = _chapter_positions(norm)
    for i, match in enumerate(matches):
        if match.group() != target:
            continue
        next_article = matches[i + 1].start() if i + 1 < len(matches) else len(norm)
        # 章标题也是边界：目标条是章末最后一条时，不能把下一章标题和下一条带进来。
        next_chapter = next((pos for pos in chapters if pos > match.start()), len(norm))
        end = min(next_article, next_chapter)
        segment = norm[match.start():end].strip()
        # 最短条文的现实长度：劳动合同法第三十六条只有 28 字（"用人单位与劳动者
        # 协商一致，可以解除劳动合同。"）。原先 30 字的门槛会把这类短文当成没切到，
        # 进而触发"回退前 N 条"，Agent 误以为副本残缺（2026-11-05 Q1 实测）。
        if len(segment) >= MIN_ARTICLE_CHARS:
            return segment
    return None


def split_articles(text: str) -> List[Tuple[str, str]]:
    norm = normalize_width(text)
    matches = _structural_headings(norm)
    chapters = _chapter_positions(norm)
    out: List[Tuple[str, str]] = []
    for i, match in enumerate(matches):
        next_article = matches[i + 1].start() if i + 1 < len(matches) else len(norm)
        next_chapter = next((pos for pos in chapters if pos > match.start()), len(norm))
        end = min(next_article, next_chapter)
        body = norm[match.start():end].strip()
        if len(body) >= MIN_ARTICLE_CHARS:
            out.append((match.group(), body))
    return out


def pick_by_keywords(text: str, keywords: List[str], top_n: int = 3) -> List[Tuple[str, str]]:
    kws = [k for k in keywords if k]
    if not kws:
        return split_articles(text)[:top_n]
    scored = []
    for heading, body in split_articles(text):
        score = sum(1 for k in kws if k in body)
        if score:
            scored.append((score, heading, body))
    scored.sort(key=lambda x: (-x[0], len(x[1])))
    return [(h, b) for _s, h, b in scored[:top_n]]


# ---------- 输出构造 ----------

def build_statute_article(resolved: Resolved, segments: List[Tuple[str, str]]) -> Dict[str, Any]:
    sel = resolved.selected
    cand = sel.candidate
    source_url = str(cand.get("sourceUrl") or "")
    return {
        "文章Id": str(cand.get("encryptedFileId") or ""),
        "文章类型": "policy",
        "文章标题": resolved.law,
        "原始标题": str(cand.get("title") or ""),
        # 只透传接口给的发文机关，不给默认值（2026-11-13 统一口径：不猜机构）。
        "发布或实施机构": str(cand.get("issuingAuthority") or ""),
        "数据源": host_of(source_url) or "深知法律法规库",
        "源网址": source_url,
        "发布日期": format_date(parse_date(cand.get("writtenDate")) or resolved.latest_version_date),
        "发文字号": str(cand.get("documentNumber") or ""),
        "生效日期": str(cand.get("effectiveDate") or ""),
        "文件标签": cand.get("policyTopicTags") or [],
        "版本状态": str(cand.get("validityStatus") or ""),
        "版本标记": resolved.marker,
        "版本标记命中": bool(sel.marker_hit),
        "版本状态存疑": bool(resolved.status_fallback),
        "版本状态说明": (
            f"正文含最新修正日 {resolved.marker}" if sel.marker_hit and resolved.marker
            else "原文取自库内全文"
        ),
        "历次版本数": len(resolved.versions),
        "选本依据": sel.reason + ("；无更好副本，采用库内全文" if resolved.status_fallback else ""),
        # 交付物不做版本状态评价（2026-11-05 定稿）：数据层返回什么就按生效状态使用，
        # 版本相关的数据问题走独立的数据问题报告，不体现在 skill 输出里。
        "核验": (
            f"原文含最新修正日 {resolved.marker}" if resolved.marker
            else "原文取自库内全文"
        ),
        "检索通道": "深知可信搜索",
        "检索类型": "legal-statute",
        "段落": [
            {
                "id": idx,
                "标题": heading,
                "内容": body,
                "匹配等级": "原文",
            }
            for idx, (heading, body) in enumerate(segments, start=1)
        ],
    }


def build_semantic_articles(body: Dict[str, Any], channel_label: str = "深知可信搜索") -> List[Dict[str, Any]]:
    data = (body.get("content") or {}).get("data") or {}
    articles = [x for x in (data.get("检索文章") or []) if isinstance(x, dict)]
    for article in articles:
        article.setdefault("检索通道", channel_label)
        # 与深知可信搜索 1.7.2 对齐：webSearch 路统一补 非官方来源=true，
        # 即使接口把法院/政府网站标为“权威”，也不是深知库内材料。
        if channel_label.endswith("联网"):
            article.setdefault("非官方来源", True)
        article.setdefault("检索类型", "legal-semantic")
        # 012 的段落字段已是原文原段；统一匹配等级文案，避免渲染层把它当低置信段落
        for para in article.get("段落") or []:
            if isinstance(para, dict) and not para.get("匹配等级"):
                para["匹配等级"] = "原文"
    return articles


OLD_INTERP_PATTERN = re.compile(r"解释[（(](二|三|四)[）)]")


def find_old_interpretations(articles: List[Dict[str, Any]]) -> List[str]:
    """返回材料标题里确认属于 2006/2010/2013 年旧解释的条目。

    2020 年《解释（一）》整合替代的是旧解释（二/三/四）。2025 年新颁的
    《解释（二）》（法释〔2025〕12号，2025-09-01 施行）是现行文本，不能误判为旧解释。
    这里只做暴露，不改结果；数据层问题另行记录。
    """
    hits: List[str] = []
    for article in articles:
        title = str(article.get("文章标题") or article.get("标题") or "")
        if not OLD_INTERP_PATTERN.search(title):
            continue
        doc_no = str(article.get("发文字号") or "")
        date_text = str(article.get("生效日期") or article.get("发布日期") or "")
        # 2021 年以后颁行/生效的，是现行解释（含 2025 年新解释二），不提示
        if re.search(r"〔(2021|2022|2023|2024|2025|2026)〕", doc_no):
            continue
        if date_text and date_text >= "2021-01-01":
            continue
        # 只有确认是旧解释年份，或日期早于 2021，才提示；元数据缺失时不猜
        if re.search(r"〔(2006|2010|2013)〕", doc_no) or (date_text and date_text < "2021-01-01"):
            hits.append(title)
    return hits


def output_body(query: str, ref: str, articles: List[Dict[str, Any]], legal_meta: Dict[str, Any]) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "tid": legal_meta.get("tid") or "",
        "ret": 0,
        "content": {
            "code": 200,
            "msg": "success",
            "data": {
                "用户问题": query,
                "咨询日期": ref,
                "办理地域": "中国",
                "文章数量": len(articles),
                "检索文章": articles,
            },
        },
        "_legal": legal_meta,
    }
    return body


def resolve_output_path(name: str, run: str | None = None) -> Path:
    """结果 JSON 写入会话 run 目录（--run / DKNOWC_RUN_DIR），拒绝写入 Skill 安装目录。"""
    from path_guard import safe_write_path
    try:
        return safe_write_path(name, run)
    except ValueError as exc:
        raise client.LegalApiError("output", str(exc)) from None


# ---------- 主流程 ----------

def run(args: argparse.Namespace) -> Dict[str, Any]:
    query = (args.query or "").strip()
    law = (args.law or "").strip()
    ref_date = (args.reference_date or date.today().isoformat()).strip()

    article_specs: List[str] = []
    if getattr(args, "articles", ""):
        article_specs = [s for s in re.split(r"[,，\s]+", args.articles) if s.strip()]
    elif args.article:
        article_specs = [args.article]

    if law:
        first_article = article_specs[0] if article_specs else ""
        # 只有显式传 --reference-date 才走"按基准日选版本"，默认仍用最新版选本逻辑
        _ref = parse_date(args.reference_date) if args.reference_date else None
        resolved = resolve_law(law, max_copies=args.max_copies, article=first_article,
                               reference_date=_ref)
        segments: List[Tuple[str, str]] = []
        missing: List[str] = []
        fulltext_fallback = False
        seen: set = set()
        for spec in article_specs:
            key = normalize_article(spec)
            if not key or key in seen:
                continue
            seen.add(key)
            text = extract_article(resolved.selected.text, spec)
            if text:
                segments.append((key, text))
            else:
                missing.append(key)
        if missing and article_specs:
            # 选中副本可能残缺（2026-11-05 Q1 实测：某镜像全文只切出第一~三条）。先在
            # 其余已下载候选里找，找得到就换本重切；都不要退回"正文前 N 条"——那会让
            # Agent 把第一~三条当成目标条文，白烧一轮调用。
            for alt in sorted(resolved.evaluated, key=lambda e: (e.marker_hit, e.score, len(e.text)),
                              reverse=True):
                if alt is resolved.selected:
                    continue
                alt_texts = [(normalize_article(s), extract_article(alt.text, s)) for s in article_specs]
                hits = [(k, t) for k, t in alt_texts if t]
                if len(hits) <= len(segments):
                    continue
                resolved.selected = alt
                segments = hits
                missing = [k for k, t in alt_texts if not t]
                if not missing:
                    break
        if not segments and article_specs:
            raise client.LegalApiError(
                "extract",
                f"「{law}」已下载的副本里都切不出 {'、'.join(missing or article_specs)}："
                f"换法律名/条号重试，或改用语义模式（--query）取原文"
            )
        if not segments and args.keywords:
            keywords = [k.strip() for k in re.split(r"[,，\s]+", args.keywords) if k.strip()]
            segments = pick_by_keywords(resolved.selected.text, keywords, top_n=args.top_n)
        if not segments:
            # 没指定条号/关键词时，返回正文前 3 条，避免整部法全文塞进报告
            segments = split_articles(resolved.selected.text)[: max(1, args.top_n)]
        if not segments:
            # 政策文件常见“一、二、（一）”结构，没有“第X条”可切。此时不要把
            # “没有条标题”误报成“没有全文”：把库内全文作为一个材料返回，由
            # Agent 按章节/段落引用。仍保留原来的 extract 错误只在全文为空时抛出。
            full_text = (resolved.selected.text or "").strip()
            if full_text:
                segments = [("正文", full_text)]
                fulltext_fallback = True
        if not segments:
            raise client.LegalApiError("extract", f"未能从「{law}」正文中切出目标条文")

        article = build_statute_article(resolved, segments)
        if fulltext_fallback:
            article["检索类型"] = "legal-policy-fulltext"
            article["未切条"] = True
        if missing:
            article["未切出条号"] = missing
        meta = {
            "mode": "statute_fulltext" if fulltext_fallback else "statute",
            "law": law,
            "article": normalize_article(args.article) if args.article else "",
            "articles": [normalize_article(s) for s in article_specs],
            "missing_articles": missing,
            "latest_version_date": resolved.marker,
            "versions_count": len(resolved.versions),
            "selected_file_id": str(resolved.selected.candidate.get("encryptedFileId") or ""),
            "selected_source": str(resolved.selected.candidate.get("sourceUrl") or ""),
            "selected_status": str(resolved.selected.candidate.get("validityStatus") or ""),
            "marker_hit": bool(resolved.selected.marker_hit),
            "status_fallback": bool(resolved.status_fallback),
            "evaluated_copies": [
                {
                    "file_id": str(e.candidate.get("encryptedFileId") or ""),
                    "title": str(e.candidate.get("title") or ""),
                    "status": str(e.candidate.get("validityStatus") or ""),
                    "score": round(e.score, 2),
                    "marker_hit": e.marker_hit,
                    "article_hit": e.article_hit,
                    "reason": e.reason,
                }
                for e in resolved.evaluated
            ],
        }
        return output_body(query or law, ref_date, [article], meta)

    if not query:
        raise client.LegalApiError("input", "必须提供 --query，或提供 --law 走法条模式")

    labels = [x.strip() for x in re.split(r"[,，]", getattr(args, "policy_labels", "") or "") if x.strip()]
    # 标签目录（2026-11-05）：允许传短名/叶子名，自动解析成接口要求的完整路径
    if labels and tag_catalog:
        try:
            labels = tag_catalog.resolve_many(labels)
        except Exception:
            pass
    search_channel = (getattr(args, "search_channel", "") or "").strip()
    # 阶段二（webSearch）是独立外部检索，不与库内标签混用；传了也强制清空，
    # 避免外部网页被 policyLabels 按库内标签过滤成 0 条。
    if search_channel and labels:
        print(f"阶段二联网检索不使用 policyLabels，已忽略：{labels}", file=sys.stderr)
        labels = []
    body = client.semantic_search(
        query,
        limit_articles=args.limit_articles,
        policy_labels=labels or None,
        search_channel=search_channel or None,
    )
    if body.get("_legal_label_zero"):
        print(f"检索结果：带标签 {labels} 返回 0 条（按契约不作静默降级；如需无标签结果请另发一次检索）",
              file=sys.stderr)
    articles = build_semantic_articles(
        body,
        channel_label="深知联网" if search_channel == "webSearch" else "深知可信搜索",
    )
    # 校验返回的文件标签是否都在目录里（目录外标签说明数据侧有一致性问题）
    tag_unknown = []
    if tag_catalog:
        try:
            tag_unknown = tag_catalog.Catalog.load().unknown_in_articles(articles)
            if tag_unknown:
                print(f"标签校验：{len(tag_unknown)} 个返回标签不在目录中，例如 "
                      f"{tag_unknown[0]['文件标签']}", file=sys.stderr)
        except Exception:
            pass
    data = (body.get("content") or {}).get("data") or {}
    meta = {
        "mode": "semantic",
        "query": query,
        "policy_labels": labels,
        "search_channel": search_channel or None,
        "tid": body.get("tid") or "",
        "article_count": len(articles),
        "note": "语义模式用于确定法律/候选材料；拿到法律名与条号后应再用 --law/--article 取精确原文",
        "semantic_params": data.get("用户问题"),
        "tag_unknown": tag_unknown,
        "label_zero": bool(body.get("_legal_label_zero")),
    }
    return output_body(query, ref_date, articles, meta)


def main() -> None:
    parser = argparse.ArgumentParser(description="深知法律助手 · 法律检索（001/003/002/005 + 012）")
    parser.add_argument("--query", help="用户问题（语义模式必填）")
    parser.add_argument("--law", help="法律名称，如“中华人民共和国劳动合同法”")
    parser.add_argument("--article", help="单个条号，如 47 或 第四十七条")
    parser.add_argument("--articles", help="多个条号，逗号分隔，如 38,39,40,47；一次解析、一次下载、切出多条；与 --article 同时传时以本参数为准")
    parser.add_argument("--keywords", help="未指定条号时，用关键词挑选相关条文")
    parser.add_argument("--top-n", type=int, default=3, help="未指定条号时最多返回的条文数（默认 3）")
    parser.add_argument("--limit-articles", type=int, default=10, help="语义模式最多返回材料数（默认 10）")
    parser.add_argument("--policy-labels", default="", help="可信搜索接口 V2 标签过滤（policyLabels），逗号分隔完整路径。查法律本体可传「法律/法律标签/法律」过滤新闻稿/问答页噪音；司法解释、批复不在该标签族内，查解释类文件时不要传")
    parser.add_argument("--search-channel", default="", help="V2 检索通道（阶段二）：库内无果/支撑不足时传 webSearch，走深知联网检索；返回材料由报告标「非官方来源」")
    parser.add_argument("--max-copies", type=int, default=4, help="选本下载副本的上限（默认 4）；命中合格副本即提前停止，正常只下 1-2 份")
    parser.add_argument("--reference-date", default="", help="按该日期选取当时有效的版本（YYYY-MM-DD）；跨期/旧法问题必传，不传取最新版")
    parser.add_argument("--output", "-o", help="结果 JSON 文件名（落到 --run 目录）")
    parser.add_argument("--run", help="会话 run 目录（也可用环境变量 DKNOWC_RUN_DIR）；写 --output 时必填")
    parser.add_argument("--json-only", action="store_true", help="仅输出 JSON")
    parser.add_argument("--timeout", type=int, default=90, help="单次请求超时秒数（默认 90）")
    args = parser.parse_args()

    # 先解析并检查落盘目标，再发请求：避免先花时间检索、后因路径/覆盖被拒。
    out_path = None
    if args.output:
        try:
            out_path = resolve_output_path(args.output, args.run)
        except client.LegalApiError as exc:
            print(json.dumps({
                "status": "error", "stage": exc.stage, "message": str(exc),
            }, ensure_ascii=False, indent=2), file=sys.stderr)
            sys.exit(1)
        if out_path.exists():
            print(json.dumps({
                "status": "error", "stage": "output",
                "message": f"输出文件已存在，拒绝覆盖：{out_path}\n"
                           "重复/并行运行请换一个 --run 目录，或换一个 --output 文件名。",
            }, ensure_ascii=False, indent=2), file=sys.stderr)
            sys.exit(1)

    try:
        body = run(args)
    except client.LegalApiError as exc:
        print(json.dumps({
            "status": "error",
            "stage": exc.stage,
            "message": str(exc),
            "status_code": exc.status_code,
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)

    old_interps = find_old_interpretations(
        ((body.get("content") or {}).get("data") or {}).get("检索文章") or []
    )
    if old_interps:
        body.setdefault("_legal", {})["old_interpretation"] = old_interps
        print(
            "警告：返回材料包含 2006/2010/2013 年的旧司法解释（解释二/三/四），"
            "已被 2020 年《解释（一）》整合替代，不得直接作为现行依据。"
            "注意：2025 年新颁《解释（二）》（法释〔2025〕12号）是现行文本，不在旧解释之列。"
            f"命中：{'；'.join(old_interps[:3])}",
            file=sys.stderr,
        )

    raw = json.dumps(body, ensure_ascii=False, indent=2)
    if args.output and out_path is not None:
        path = out_path
        path.write_text(raw, encoding="utf-8")
        print(f"已保存法律检索 JSON：{path}")
        if not args.json_only:
            data = (body.get("content") or {}).get("data") or {}
            print(f"模式：{(body.get('_legal') or {}).get('mode')}｜材料：{data.get('文章数量')} 条")
            for idx, article in enumerate(data.get("检索文章") or [], start=1):
                print(f"{idx}. {article.get('文章标题')}｜{article.get('数据源')}｜{article.get('发布日期')}")
                for para in (article.get("段落") or [])[:1]:
                    print("   " + snippet(str(para.get("内容") or ""), 160))
        return
    print(raw)


if __name__ == "__main__":
    main()
