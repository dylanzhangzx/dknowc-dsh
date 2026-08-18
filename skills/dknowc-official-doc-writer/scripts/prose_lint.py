#!/usr/bin/env python3
"""深知公文写作 - 中文正式文稿语言质检脚本。

扫描 .txt / .md / .docx 草稿，提示 AI 味、旁白、口语、占位符和格式风险。
只报风险，不自动改写正文。本脚本是可选质检能力，不参与主写作流程。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree


class Finding:
    """一条质检发现。"""

    __slots__ = ("path", "line", "severity", "label", "match", "advice")

    def __init__(self, path: str, line: int, severity: str, label: str, match: str, advice: str):
        self.path = path
        self.line = line
        self.severity = severity
        self.label = label
        self.match = match
        self.advice = advice

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "line": self.line,
            "severity": self.severity,
            "label": self.label,
            "match": self.match,
            "advice": self.advice,
        }


SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}

# (severity, label, pattern, advice)
PATTERNS = [
    # --- 思考泄露与起草过程（硬边界，high）---
    ("high", "thought-leak", r"作为(?:一个)?\s*AI|我是(?:一个)?\s*AI|由\s*AI\s*(?:起草|生成|辅助生成)", "删除模型身份或生成过程表述，改为正文判断。"),
    ("high", "thought-leak", r"我的(?:思路|推理|分析)|(?:思考|推理)过程(?:如下|是|：|:)|内部推理", "删除思考过程或内部推理表述。"),
    ("high", "thought-leak", r"我将根据|接下来我会|按你的要求|这版文章|这段文字|根据用户要求(?:修改|改写|调整)", "删除外部修改过程表述，改为定稿正文。"),
    ("medium", "thought-leak", r"本(?:文|稿|报告|方案|材料|说明)[^。\n]{0,8}(?:是|为)?\s*AI\s*(?:辅助)?生成", "删除 AI 生成声明，正式正文不出现该表述。"),

    # --- 旁白句（写作说明混入正文）---
    ("high", "side-commentary", r"本方案重点说明|本文将从|本节主要(?:介绍|说明)", "删除写作说明，改成正文判断。"),
    ("medium", "side-commentary", r"以下(?:直接)?列出|相关情况如下|需要指出的是|值得注意的是", "删除提示语，直接进入事项。"),
    ("medium", "side-commentary", r"根据有关资料显示|有关方面认为|业内专家指出", "避免模糊背书，补充明确来源或改为材料已给事实。"),
    ("medium", "side-commentary", r"为了便于理解|简单来说|通俗地说|可以理解为|综上所述[，,]", "正式文稿中删除解释腔或过渡套话。"),

    # --- 二元包装句（成簇判断，单次可保留）---
    ("medium", "paired-summary", r"不是[^。；;\n]{0,80}而是", "检查是否为虚假对比；必要否定对比可保留。"),
    ("medium", "paired-summary", r"不仅[^。；;\n]{0,80}(?:还|更是)", "检查是否拆成具体事实；成簇出现时提示。"),
    ("medium", "paired-summary", r"不但[^。；;\n]{0,80}而且", "检查是否拆成具体事实；成簇出现时提示。"),
    ("medium", "paired-summary", r"既[^。；;\n]{0,80}又", "改为具体并列事项，避免套话。"),
    ("medium", "paired-summary", r"一方面[^。；;\n]{0,100}另一方面", "检查是否为真实并列；否则按业务自然分段。"),

    # --- 未完成占位符 ---
    ("medium", "placeholder", r"\[[^\]\n]{0,30}(?:具体|待|填写|补充|确认|项目名称|单位名称|金额|日期)[^\]\n]{0,30}\]", "交付正文不应保留方括号占位；缺项改为正文外提示。"),
    ("medium", "placeholder", r"(?<![A-Za-z一-鿿])X{2,}(?:万元|亿元|项|%|％|卡|套|人|次|个|年|月|日|张|台)", "交付正文不应保留 X/XXXX 类占位。"),
    ("medium", "placeholder", r"Y{4}年M{1,2}月D{1,2}日", "交付正文不应保留 YYYY年MM月DD日 类占位。"),
    ("medium", "placeholder", r"[（(][^）)\n]{0,30}(?:待(?:确认|补充|填写|签发)|签发日期|会议时间|成文日期)[^）)\n]{0,30}[）)]", "交付正文不应保留括号占位。"),
    ("medium", "placeholder", r"〔(?:签发日期|会议时间|待补充)〕", "交付正文不应保留未完成占位。"),

    # --- 口语化与弱判断 ---
    ("medium", "casual", r"这个钱花得值|用不完|AI味|老板关心|马上要|搞清楚", "改为正式表达，且不升级强度（见 anti_ai_patterns.md）。"),

    # --- 空泛套话（low，需有实质支撑）---
    ("low", "empty-filler", r"全面赋能|提供有力支撑|奠定坚实基础|未来可期|高度重视|充分发挥|不断提升|持续推进", "确认是否有具体对象、机制或结果支撑；无则改为具体工作。"),
    ("low", "template-phrase", r"形成一批|重点任务包括|保障措施包括|总体看|再上新台阶", "避免总括句承接长清单或口号式收尾。"),

    # --- 高频抽象词 ---
    ("low", "abstract-term", r"赋能|闭环|底座|抓手|矩阵", "抽象词需落到具体对象、机制或验收标准；同一词过多时替换。"),

    # --- 格式噪点 ---
    ("medium", "format", r"[一-鿿][,;:!?][一-鿿]", "中文正文中改用全角标点。"),
    ("low", "format", r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", "确认正式中文材料中是否应取消千位分隔符。"),
    ("low", "format", r"\*\*[^*\n]{1,80}\*\*|^\s*#{1,6}\s+|^\s*---\s*$", "正式公文正文不要用 Markdown 加粗/标题/横线。"),
    ("low", "format", r"[\U0001F300-\U0001FAFF]", "正式公文正文避免使用 Emoji。"),
]

# 术语过度集中阈值
REPEAT_TERMS = {
    "赋能": 3, "闭环": 4, "抓手": 3, "底座": 6, "矩阵": 3,
    "生态": 4, "口径": 4, "边界": 4,
}


def read_docx(path: Path) -> str:
    """提取 .docx 中的正文文本。"""
    pieces = []
    xml_names = (
        "word/document.xml",
        "word/header1.xml", "word/header2.xml", "word/header3.xml",
        "word/footer1.xml", "word/footer2.xml", "word/footer3.xml",
    )
    try:
        with zipfile.ZipFile(path) as zf:
            for name in xml_names:
                if name not in zf.namelist():
                    continue
                root = ElementTree.fromstring(zf.read(name))
                for elem in root.iter():
                    tag = elem.tag.rsplit("}", 1)[-1]
                    if tag == "t" and elem.text:
                        pieces.append(elem.text)
                    elif tag in {"p", "br"}:
                        pieces.append("\n")
    except (zipfile.BadZipFile, ElementTree.ParseError, OSError):
        return ""
    return "".join(pieces)


def read_text(arg: str) -> tuple[str, str]:
    """读取 .txt / .md / .docx / stdin。"""
    if arg == "-":
        return "<stdin>", sys.stdin.read()
    path = Path(arg)
    if path.suffix.lower() == ".docx":
        return str(path), read_docx(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SystemExit(f"无法读取文件 {path}: {exc}")
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return str(path), raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return str(path), raw.decode("gb18030", errors="replace")


def scan_file(path: str, text: str, include_format: bool, include_structure: bool) -> list[Finding]:
    findings = []
    lines = text.splitlines() or [text]
    seen_pairs = set()

    for idx, line in enumerate(lines, start=1):
        for severity, label, pattern, advice in PATTERNS:
            if label == "format" and not include_format:
                continue
            for match in re.finditer(pattern, line):
                key = (label, match.group(0), idx)
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                findings.append(Finding(path, idx, severity, label, match.group(0), advice))

    if include_structure:
        findings.extend(repeat_term_findings(path, text))
        findings.extend(duplicate_paragraph_findings(path, lines))
    return findings


def repeat_term_findings(path: str, text: str) -> list[Finding]:
    findings = []
    for term, threshold in REPEAT_TERMS.items():
        count = text.count(term)
        if count >= threshold:
            findings.append(Finding(
                path, 1, "low", "term-overuse", term,
                f"`{term}` 出现 {count} 次；建议将部分表述替换为更具体的事项、主体或办理要素。",
            ))
    return findings


def duplicate_paragraph_findings(path: str, lines: list[str]) -> list[Finding]:
    """相邻段落事项重叠检测。"""
    findings = []
    prev_text = ""
    prev_line = 0
    for idx, line in enumerate(lines, start=1):
        text = re.sub(r"\s+", "", line)
        if len(text) < 60:
            prev_text = ""
            continue
        if prev_text and text and _similarity(prev_text, text) >= 0.42:
            findings.append(Finding(
                path, idx, "medium", "adjacent-duplicate",
                text[:40] + "...",
                f"与第 {prev_line} 行段落事项重叠较高；检查是否为胶水式重复连接。",
            ))
        prev_text = text
        prev_line = idx
    return findings


def _similarity(a: str, b: str) -> float:
    a_set, b_set = set(a), set(b)
    if not a_set or not b_set:
        return 0.0
    return len(a_set & b_set) / len(a_set | b_set)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="深知公文写作草稿语言质检")
    parser.add_argument("files", nargs="+", help="要扫描的 .txt/.md/.docx 文件，或 '-' 表示 stdin")
    parser.add_argument("--encoding", help="纯文本文件编码（可选）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 结果")
    parser.add_argument("--format", action="store_true", help="同时检查标点、数字、Markdown、Emoji 格式风险")
    parser.add_argument("--structure", action="store_true", help="同时检查相邻段落重复与术语过度集中")
    parser.add_argument("--strict", action="store_true", help="存在中高等级发现时返回退出码 1")
    args = parser.parse_args(argv)

    all_findings = []
    had_error = False
    for arg in args.files:
        try:
            path, text = read_text(arg)
        except SystemExit as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            had_error = True
            continue
        all_findings.extend(scan_file(path, text, args.format, args.structure))

    if args.json:
        print(json.dumps([f.as_dict() for f in all_findings], ensure_ascii=False, indent=2))
    elif all_findings:
        for f in all_findings:
            print(f"{f.path}:{f.line}: {f.severity}: {f.label}: {f.match}")
            print(f"  {f.advice}")
    elif not had_error:
        print("未发现明显语言风险。")

    if args.strict and not had_error:
        high_medium = [f for f in all_findings if SEVERITY_RANK[f.severity] >= 2]
        return 1 if high_medium else 0
    return 1 if had_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
