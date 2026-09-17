#!/usr/bin/env python3
"""把写作流程的结构化正文/素材 JSON 转成可信搜索同款溯源报告。"""

from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
# 工作区根：dsh 场景通过环境变量 DKNWOC_WS_ROOT 指向会话工作区，未设置时回退到 skill 目录（SkillHub 兼容）
import os as _os
_ws = _os.environ.get("DKNWOC_WS_ROOT")
if not _ws:
    # dsh 会话隔离：每会话独立产物目录 <工作区>/dknowc-output/<DSH_SESSION_ID前8位>/，
    # 多会话共用同一工作区时互不混杂；非 dsh 环境回退为工作区本身。
    _sid = _os.environ.get("DSH_SESSION_ID", "")
    _ws = str(Path(_os.getcwd()) / "dknowc-output" / (_sid[:8] if _sid else "_default"))
WS_ROOT = Path(_ws).resolve()
INPUT_DIR = WS_ROOT / "official-docs" / "input"
OUTPUT_DIR = WS_ROOT / "official-docs" / "output"
SEARCH_RESULTS_DIR = WS_ROOT / "official-docs" / "search-results"


def load_renderer():
    path = Path(__file__).with_name("render_trace_html.py")
    spec = importlib.util.spec_from_file_location("dknowc_trace_renderer", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载可信溯源报告模板: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolve_input(value: str) -> Path:
    raw = Path(value).expanduser()
    path = raw.resolve() if raw.is_absolute() else (INPUT_DIR / raw.name).resolve()
    if path.suffix.lower() != ".json":
        raise ValueError("输入文件必须是 JSON")
    try:
        path.relative_to(INPUT_DIR.resolve())
    except ValueError as exc:
        raise ValueError(f"输入文件必须位于 official-docs/input/: {value}") from exc
    if not path.exists():
        raise FileNotFoundError(f"输入文件不存在: {path}")
    return path


def safe_output(value: str, title: str) -> Path:
    if value:
        raw = Path(value).expanduser()
        path = raw.resolve() if raw.is_absolute() else (OUTPUT_DIR / raw.name).resolve()
    else:
        safe_title = "".join("_" if char in '\\/:*?"<>| ' else char for char in title).strip("_")
        path = (OUTPUT_DIR / f"{safe_title[:80] or '溯源核验报告'}_溯源核验报告.html").resolve()
    if path.suffix.lower() not in {".html", ".htm"}:
        path = path.with_suffix(".html")
    try:
        path.relative_to(OUTPUT_DIR.resolve())
    except ValueError as exc:
        raise ValueError("输出文件必须位于 official-docs/output/") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def first_value(item: dict, *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, "", [], {}):
            return str(value)
    return ""


def normalize_title(value: str) -> str:
    """仅用于兼容旧结果的标题兜底匹配；新流程优先使用素材中的 source_url。"""
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"[《》〈〉「」『』\[\]【】()（）]", "", text)
    text = re.sub(r"\s+", "", text)
    return text


def load_source_index() -> dict:
    """从本地搜索结果按文章标题建立原文 URL 索引，补齐上游整理时遗漏的字段。

    同时从同响应的 policyFiles 区提取发文字号（writtenText）并入索引——
    文号与检索文章分开展示在同一响应里，本地标题匹配即可拿到，无需接口改动；
    新闻/解读类不在 policyFiles 中（本就无文号），匹配不上则不显示。
    """
    index = {}
    if not SEARCH_RESULTS_DIR.exists():
        return index
    for path in SEARCH_RESULTS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        # 兼容两种落盘格式：--clean 白名单（顶层 articles）与接口原始响应（content.data）
        articles = data.get("articles") if isinstance(data.get("articles"), list) else None
        policy_files = []
        if articles is None:
            content = data.get("content", {})
            payload = content.get("data", {}) if isinstance(content, dict) else {}
            if isinstance(payload, dict):
                articles = payload.get("检索文章", []) if isinstance(payload.get("检索文章"), list) else []
                if isinstance(payload.get("policyFiles"), list):
                    policy_files = payload["policyFiles"]
        elif isinstance(data.get("policyFiles"), list):
            policy_files = data["policyFiles"]
        doc_numbers = {}
        for pf in policy_files:
            if not isinstance(pf, dict):
                continue
            doc_no = first_value(pf, "writtenText", "发文字号")
            title = first_value(pf, "title", "标题")
            if doc_no and title:
                doc_numbers.setdefault(normalize_title(title), doc_no)
        for article in articles:
            if not isinstance(article, dict):
                continue
            title = first_value(article, "文章标题", "title", "标题")
            if not title:
                continue
            source_url = first_value(article, "源网址", "原文链接", "sourceUrl", "source_url", "url")
            policy_url = first_value(article, "知识专库原文", "policyUrl", "policy_url")
            if source_url or policy_url:
                record = {"source_url": source_url, "policy_url": policy_url}
                index.setdefault(title, record)
                index.setdefault(normalize_title(title), record)
        for key, record in list(index.items()):
            if "doc_number" not in record:
                no = doc_numbers.get(key)
                if no:
                    record["doc_number"] = no
    return index


# 快照兜底开关：默认启用。接口 screenShotPath 曾存在路径缺 /A/ 层级的拼接 bug
# （2026-09-16 反馈后端修复中）；本开关内的 verify_snapshots 会在展示前完成
# "补 /A/ 修订 + 逐条可达实测 + 不可达弃用"，保证报告中出现的快照全部验证可打开。
SNAPSHOT_ENABLED = True


# 软 404 关键词：政府站常以 HTTP 200 返回"页面不存在"错误页，状态码识别不了，
# 需读页面标题嗅探。关键词取自实测样例，且仅匹配 <title>（政策正文不会出现在标题里），
# 误杀风险极低。
SOFT_404_KEYWORDS = ("页面不存在", "页面未找到", "您访问的页面", "已删除", "已下线", "无法找到", "not found", "404")


def check_link_alive(url: str, timeout: int = 8) -> bool:
    """检测原文链接是否仍然可达。失效判据（客观信号，与请求方无关）：
    ① HTTP 404/410；② 软 404——HTTP 200 但页面标题为典型失效页。
    连接失败、超时、403、5xx 等一律视为"无法确认"按有效处理——政府站
    常对脚本请求反爬，凭这些判死会误杀可用链接。
    """
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(
                url, method=method,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status in (404, 410):
                    return False
                if method == "GET":
                    chunk = resp.read(4096).decode("utf-8", errors="replace")
                    title = re.search(r"<title>(.*?)</title>", chunk, re.I | re.S)
                    text = title.group(1) if title else chunk[:200]
                    lowered = text.lower()
                    return not any(k in text or k in lowered for k in SOFT_404_KEYWORDS)
        except urllib.error.HTTPError as e:
            if method == "GET":
                return e.code not in (404, 410)
        except Exception:
            if method == "GET":
                return True
    return True


def normalize_snapshot_url(url: str) -> str:
    """快照路径容错：接口部分返回值缺 /A/ 层级（实测 60 条中 5 条，补全后即可访问），
    统一规范化为 https://attach.dknowc.cn/snapshot/A/<2位>/<2位>/<哈希>.jpg。"""
    u = (url or "").strip()
    if u.startswith("https://attach.dknowc.cn/snapshot/") and "/snapshot/A/" not in u:
        return u.replace("/snapshot/", "/snapshot/A/", 1)
    return u


def mark_dead_links(articles: list[dict]) -> int:
    """并发检测全部材料的原文链接，404/410 的标记 链接失效=True。返回失效数。"""
    targets = [(i, a["源网址"]) for i, a in enumerate(articles) if (a.get("源网址") or "").strip()]
    if not targets:
        return 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        alive = dict(zip((i for i, _ in targets), pool.map(check_link_alive, (u for _, u in targets))))
    dead = 0
    for i, _ in targets:
        if not alive.get(i, True):
            articles[i]["链接失效"] = True
            dead += 1
    return dead


def verify_snapshots(articles: list[dict]) -> int:
    """快照展示前的路径校验（纯本地检查，不发网络请求）：
    组装阶段已由 normalize_snapshot_url 补全 /A/ 层级；此处校验修订后的路径
    是否符合合法格式（https://attach.dknowc.cn/snapshot/A/…），不合法则弃用。

    不做网络可达检测：attach 前置雷池 WAF 的拦截与请求方 IP 风控相关
    （检测机高频请求会被拦而普通用户正常），可达性实测会误杀好快照；
    快照文件本身的存在性由可信搜索侧的数据质量保障。
    """
    dropped = 0
    for a in articles:
        u = (a.get("快照链接") or "").strip()
        if not u:
            continue
        if u.startswith("https://attach.dknowc.cn/snapshot/A/"):
            continue
        a["快照链接"] = ""
        dropped += 1
    return dropped


def to_trace_payload(data: dict) -> tuple[dict, str, str]:
    title = first_value(data, "title", "标题") or "可信溯源报告"
    answer = first_value(data, "document_content", "documentContent", "正文", "body", "answer", "content_markdown")
    if isinstance(data.get("document_content"), list):
        answer = "\n\n".join(first_value(item, "text", "content") for item in data["document_content"] if isinstance(item, dict))
    materials = data.get("materials") or data.get("素材使用情况") or []
    # 未引用召回材料：接口召回但正文未采用，同样进入材料面板（排在已引用材料之后）
    recalled = data.get("recalled_materials") or data.get("未引用素材") or []
    articles = []
    source_index = load_source_index()
    for used, group in ((True, materials), (False, recalled)):
        for index, item in enumerate(group, 1):
            if not isinstance(item, dict):
                continue
            material_name = first_value(item, "material_name", "材料名称", "title", "文章标题") or f"来源材料{index}"
            # 新结果必须直接携带 source_url；标题匹配仅兼容历史 JSON。
            matched = source_index.get(material_name) or source_index.get(normalize_title(material_name), {})
            source_url = first_value(item, "source_url", "sourceUrl", "源网址", "原文链接", "url") or matched.get("source_url", "")
            policy_url = first_value(item, "policyUrl", "policy_url", "knowledgeBase", "知识专库链接") or matched.get("policy_url", "")
            doc_number = first_value(item, "doc_number", "文号") or matched.get("doc_number", "")
            articles.append({
                "文章标题": material_name,
                "文号": doc_number,
                "来源": first_value(item, "source", "来源", "publisher"),
                "发布日期": first_value(item, "date", "发布日期", "time"),
                # 接口原始结构透传：发布日期可信度 + 段落（含段落标题，用于"原文位置"标题链）
                "发布日期可信度": first_value(item, "发布日期可信度", "可信度", "confidence"),
                "段落": item.get("段落") if isinstance(item.get("段落"), list) else [],
                "相关段落": first_value(item, "excerpt", "摘录", "支撑内容", "support"),
                "正文对应": first_value(item, "section", "正文对应"),
                "源网址": source_url,
                "知识专库原文": policy_url,
                # 快照链接（接口 screenShotPath）：原文 404 时的存档兜底，渲染层择一展示。
                # 接口刚上线数据不稳（实测部分快照 404/NoSuchKey），默认关闭，--enable-snapshot 打开。
                "快照链接": normalize_snapshot_url(first_value(item, "snapshot_url", "快照链接", "screenShotPath", "screenshot_path")) if SNAPSHOT_ENABLED else "",
                "policyUrl": first_value(item, "policyUrl", "policy_url"),
                "类型": first_value(item, "type", "素材类型") or "材料",
                "核验": first_value(item, "verification", "核验", "核验说明"),
                # 所属搜索条件（多路检索时按来源分组筛选）与引用状态
                "搜索条件": first_value(item, "search_key", "搜索条件"),
                "已引用": used,
            })
    # 知识专库链接区已随 3.6.0 未引用召回全量展示移除：召回内容都在报告材料面板中，
    # JSON 中残留的 knowledge_bases 字段被忽略（兼容旧 JSON，不报错）。
    content = {"data": {"检索文章": articles}}
    payload = {"answer": answer, "question": title, "content": content}
    # 成稿自检结果（5 项）由生成流程写入溯源 JSON；未写入时渲染器如实显示"未记录"
    self_check = data.get("self_check") or data.get("selfCheck")
    if isinstance(self_check, dict):
        payload["selfCheck"] = self_check
        content["selfCheck"] = self_check
    # 生成流程写入的核验说明清单，用于报告底部核验方法说明
    verify_checks = data.get("verification_checks") or data.get("verificationChecks")
    if isinstance(verify_checks, list) and verify_checks:
        payload["verificationChecks"] = [str(x) for x in verify_checks]
        content["verificationChecks"] = [str(x) for x in verify_checks]
    return payload, title, answer


def main() -> None:
    parser = argparse.ArgumentParser(description="生成深知可信搜索同款可信溯源报告 HTML")
    parser.add_argument("input", help="结构化可信溯源 JSON，必须位于 official-docs/input")
    parser.add_argument("--output", "-o", help="输出 HTML 文件名，默认写入 official-docs/output")
    parser.add_argument("--skip-link-check", action="store_true",
                        help="跳过原文链接活性检测（默认检测：404/410 标记失效）")
    parser.add_argument("--disable-snapshot", action="store_true",
                        help="关闭快照兜底展示（默认启用：原文 404 时以验证过的存档快照替换）")
    args = parser.parse_args()
    if args.disable_snapshot:
        global SNAPSHOT_ENABLED
        SNAPSHOT_ENABLED = False
    input_path = resolve_input(args.input)
    data = json.loads(input_path.read_text(encoding="utf-8"))
    payload, title, answer = to_trace_payload(data)
    articles = payload.get("content", {}).get("data", {}).get("检索文章", [])
    if not args.skip_link_check:
        dead = mark_dead_links(articles)
        if dead:
            print(f"链接检测：{dead} 条原文链接已失效（404/410），将改用存档快照或如实标注")
    if SNAPSHOT_ENABLED:
        dropped = verify_snapshots(articles)
        total = sum(1 for a in articles if (a.get("快照链接") or "").strip())
        print(f"快照校验：{total} 条路径合法放行 / 弃用 {dropped} 条非法路径（已自动补全 /A/，不做网络检测）")
    # 生成前校验：有素材但正文无角标 = 无法建立核验对应，拒绝生成，要求先修 JSON
    materials_count = len(data.get("materials") or [])
    if materials_count and not re.search(r"\[\d+\]", answer):
        print(f"错误：materials 共 {materials_count} 条，但正文 document_content 没有任何 [n] 角标，无法生成核验对应。", file=sys.stderr)
        print("请修正溯源 JSON：在正文关键结论后标注 [1]、[2] 等角标并与 materials 一一对应，然后重新运行本脚本。", file=sys.stderr)
        raise SystemExit(1)
    output_path = safe_output(args.output, title)
    renderer = load_renderer()
    rendered = renderer.render_html(payload, title, answer_override=answer, question_override=title)
    output_path.write_text(rendered, encoding="utf-8")
    print(f"溯源核验报告 HTML 已生成: {output_path}")


if __name__ == "__main__":
    main()
