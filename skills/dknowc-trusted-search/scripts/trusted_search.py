#!/usr/bin/env python3
"""深知可信搜索可信搜索调用脚本（V2 接口，1.6.0 起）。

调用可信搜索 V2 接口 open-api/maas/dependable/v2/search，返回权威材料召回结果。
V2 与 V1 的关键差异（2026-10-23 切换，对齐公文写作 3.9.0 的实测结论）：
- searchType 必填且**每次调用只传一个值**（policy/govSite/affair/qa/private）；
  混传多个类型会共用结果名额、稀释政策文件与文号覆盖——需要两类来源时并行
  调用两路再经 merge_search_results.py 合并，禁止在一请求里混传。
- 参数定档（受控实测选定）：segmentCount=4、MaterialLength=18000、
  filterPara=true、queryTopArea=false、simplified=false。
- 成功判定：ret==0（或缺省）且 content.code==200；业务错误是 HTTP 200 +
  content.code=500 + 中文 msg（结构化返回，按业务错误处理，不当网络失败重试）。
- 已知接口问题（平台侧待确认，应用侧不绕）：policyFiles.writtenText 偶发为空
  （文号匹配拿不到就不显示）；文章级发文字号主要在 searchType=policy 时才有返回
  （govSite 基本没有、深度搜索完全不带）；段落"匹配等级"（S/I/P）不稳定，只作参考。
"""

import argparse
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_ENDPOINT = "https://open.dknowc.cn/open-api/maas/dependable/v2/search"
SKILL_ROOT = Path(__file__).resolve().parent.parent
# 工作区根：dsh 场景通过环境变量 DKNWOC_WS_ROOT 指向会话工作区，未设置时回退到 cwd
import os as _os
_ws = _os.environ.get("DKNWOC_WS_ROOT")
if not _ws:
    # dsh 会话隔离：每会话独立产物目录 <工作区>/dknowc-output/<DSH_SESSION_ID前8位>/，
    # 多会话共用同一工作区时互不混杂；非 dsh 环境回退为工作区本身。
    _sid = _os.environ.get("DSH_SESSION_ID", "")
    _ws = str(Path(_os.getcwd()) / "dknowc-output" / (_sid[:8] if _sid else "_default"))
WS_ROOT = Path(_ws).resolve()
SEARCH_RESULTS_DIR = WS_ROOT / "official-docs" / "search-results"

# V2 参数定档（1.6.0；对齐公文写作 3.9.0 三组受控实测：4/18000 双主题相关率最高、边际新增质量最好）
DEFAULT_SEARCH_TYPE = "policy"       # 政策依据主路；办事/流程类补 govSite 路（各自单值，禁止混传）
SEARCH_TYPES = ("policy", "govSite", "affair", "qa", "private")
DEFAULT_SEGMENT_COUNT = 4
DEFAULT_MATERIAL_LENGTH = 18000

# 余额/额度用尽的判定：HTTP 状态与业务错误消息双路径。
# 命中后返回 quota_exhausted=true，Agent 必须停止重试并引导用户到 MaaS 处理，不得反复调用。
# 错误码语义按接口文档区分：401=密钥校验失败（可能失效，需重新获取）；403=接口无权限（密钥类型不符）；
# 402=余额类。429 接口文案为"繁忙/限流/余额不足"三义混合、无法归因——现阶段全部按额度用尽处理
# （2026-09-10 起），待后端把服务端问题与余额拆分为不同错误码后再调整回区分逻辑。
MAAS_PLATFORM_URL = "https://platform.dknowc.cn/auth/#/login"
QUOTA_EXHAUSTED_HTTP_CODES = {402, 429}
QUOTA_EXHAUSTED_KEYWORDS = (
    "余额不足", "额度不足", "额度已用完", "额度已用尽", "体验额度已用完",
    "余额已不足", "欠费", "quota", "insufficient", "balance", "exceeded",
)


def detect_quota_exhausted(status_code=None, errmsg=None):
    """判断本次接口失败是否由余额/额度用尽引起。"""
    if status_code in QUOTA_EXHAUSTED_HTTP_CODES:
        return True
    if errmsg:
        lowered = str(errmsg).lower()
        if any(kw in lowered for kw in QUOTA_EXHAUSTED_KEYWORDS):
            return True
    return False


def user_message_for_error(status_code=None, quota_exhausted=False):
    """按错误类型返回给用户的固定话术（Agent 必须原样转述，不得改写后发挥）。"""
    if quota_exhausted:
        return (f"检索调不动，很可能是积分用完了：到 {MAAS_PLATFORM_URL} 看一下积分，"
                "完成实名认证可以再领 10 万积分。")
    if status_code == 401:
        return "访问密钥校验没通过（密钥可能已失效），我重新获取一下密钥；还不行的话需要重新验证手机号。"
    if status_code == 403:
        return (f"当前密钥没有检索权限（可能类型不符或已变更）。到 {MAAS_PLATFORM_URL} 查看密钥权限，"
                "或重新验证手机号获取新密钥。")
    if status_code == 500:
        return "检索服务暂时异常，我稍后再试；持续异常的话先基于已有检索结果整理回答，关键依据标注'依据待核验'。"
    return "检索暂时没连上（网络波动），稍等我再试一次；持续失败的话先基于已有检索结果整理回答，关键依据标注'依据待核验'。"


def _fail_request(stage: str, reason: str, status_code=None, errmsg=None):
    """请求失败时输出结构化错误（含 user_message 固定话术）并退出。"""
    quota = detect_quota_exhausted(status_code, errmsg)
    retry_forbidden = quota or status_code == 403
    print(f"错误：{reason}", file=sys.stderr)
    print(json.dumps({
        "status": "error",
        "stage": stage,
        "status_code": status_code,
        "quota_exhausted": quota,
        "retry_forbidden": retry_forbidden,
        "user_message": user_message_for_error(status_code, quota),
        "maas_platform_url": MAAS_PLATFORM_URL,
    }, ensure_ascii=False))
    sys.exit(1)



def resolve_output_json(output_path: str) -> Path:
    """把搜索结果 JSON 落到 official-docs/search-results/，阻断路径遍历。"""
    raw_path = Path(output_path).expanduser()
    if raw_path.is_absolute():
        resolved = raw_path.resolve()
    elif raw_path.parent == Path("."):
        resolved = (SEARCH_RESULTS_DIR / raw_path.name).resolve()
    else:
        resolved = raw_path.resolve()

    if resolved.suffix.lower() != ".json":
        resolved = resolved.with_suffix(".json")
    try:
        resolved.relative_to(SEARCH_RESULTS_DIR.resolve())
    except ValueError:
        raise ValueError(f"输出文件必须位于 official-docs/search-results/ 内: {output_path}")
    return resolved


def _pick(*values: Optional[str]) -> str:
    for value in values:
        if value:
            return value.strip()
    return ""


def _list_arg(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [value.strip()]


def _validate_eff_time(value: str) -> str:
    value = value.strip()
    pattern = r"^\d{4}年(\d{2}月(\d{2}日)?)?$"
    if re.fullmatch(pattern, value):
        return value
    print(
        "错误：eff_time 只能传一个查询所属的生效日期，格式为 YYYY年、YYYY年MM月或 YYYY年MM月DD日；"
        "不要传 2024-2025年、2024至2025年、2024 2025 这类时间范围。",
        file=sys.stderr,
    )
    sys.exit(2)


def _validate_service_area(value: str) -> str:
    value = value.strip()
    multi_area_markers = [",", "，", "、", ";", "；", "/", "|", " 和 ", " 与 ", "及"]
    if any(marker in value for marker in multi_area_markers) or re.search(r"\s+", value):
        print(
            "错误：service_area 只能传一个规范地域名，例如 重庆、重庆两江新区、中国；"
            "不要传 重庆,两江新区、重庆 两江新区、北京和上海 这类多个地域。复杂任务请拆成多次搜索。",
            file=sys.stderr,
        )
        sys.exit(2)
    return value


def _validate_search_type(value: str) -> str:
    """V2：searchType 单值必填。混传（逗号/顿号/空格分隔多个）直接报错——混传会共用
    结果名额、稀释政策文件与文号覆盖（公文写作 3.9.0 实测结论），需要两类来源时
    并行调用两路再 merge。"""
    value = (value or "").strip()
    if not value:
        return DEFAULT_SEARCH_TYPE
    multi_markers = [",", "，", "、", ";", "；", " ", "\t", "/", "|"]
    if any(marker in value for marker in multi_markers):
        print(
            "错误：searchType 每次调用只传一个值（policy / govSite / affair / qa / private）。"
            "混传多个类型会共用结果名额、稀释政策文件与文号覆盖——需要两类来源时请并行调用"
            "两路（各传一个 searchType）再经 merge_search_results.py 合并。",
            file=sys.stderr,
        )
        sys.exit(2)
    if value not in SEARCH_TYPES:
        print(f"错误：searchType 只能是 {' / '.join(SEARCH_TYPES)} 之一，收到：{value}", file=sys.stderr)
        sys.exit(2)
    return value


def _build_payload(args: argparse.Namespace) -> Dict[str, Any]:
    # V2 请求体（1.6.0）：searchType 必填单值；eff_time/service_area 恒为数组的 V1 兼容形态；
    # item / knowBase 不传（1.5.2 口径延续：办事清单能力接口侧不可用、专库外链属已移除老能力）。
    payload: Dict[str, Any] = {
        "query": args.query,
        # 联网搜索模式：searchChannel 单值传 webSearch，
        # 返回真实互联网内容（网页正文段落+源网址，可溯源到原段）；dataAuthority 随联网路自动开——
        # 返回文章级 数据权威性 标注（实测联网结果为"非权威"），供渲染层打"非官方来源"徽标。
        "dataAuthority": bool(args.data_authority or args.search_channel == "webSearch"),
        "eff_time": _list_arg(_validate_eff_time(args.eff_time)) if args.eff_time else [""],
        "service_area": _list_arg(_validate_service_area(args.service_area)) if args.service_area else [""],
        "searchType": [args.search_type],
        "policy": False if args.no_policy else True,
        "return_full_content": args.return_full_content,
        # simplified 固定 False：simplified=true 返回精简集（材料更少且无存档快照 screenShotPath），
        # false 返回完整集（含快照字段，供核验报告原文失效时兜底回看）。
        "simplified": bool(args.simplified),
        "segmentCount": args.segment_count,
        "MaterialLength": args.material_length,
        "filterPara": not args.no_filter_para,
        "queryTopArea": args.query_top_area,
    }
    if args.search_channel:
        # 单值（与 searchType 同理）：govSearch/webSearch/wxSearch 一次只传一个
        payload["searchChannel"] = [args.search_channel]
    return payload


def _post(url: str, api_key: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("api-key", api_key)
    req.add_header("Content-Type", "application/json")
    # 来源声明（X-Dknowc-Attribution，仅统计用、不参与鉴权）：
    # 读包根 attribution.json + SKILL.md 的 version；读取失败不加头、不阻断请求。
    try:
        from attribution import build_attribution_header, ATTRIBUTION_HEADER
        _attr = build_attribution_header()
        if _attr:
            req.add_header(ATTRIBUTION_HEADER, _attr)
    except Exception:
        pass

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace").replace("\x00", "")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        _fail_request("http", f"HTTP {e.code} {detail or e.reason}", status_code=e.code, errmsg=detail)
    except urllib.error.URLError as e:
        _fail_request("network", f"网络请求失败 - {e.reason}")
    except socket.timeout:
        _fail_request("timeout", "可信搜索接口请求超时")

    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}
    if isinstance(body, dict):
        return body
    return {"data": body}


def _content(body: Dict[str, Any]) -> Dict[str, Any]:
    content = body.get("content")
    if isinstance(content, dict):
        return content
    return body


def _data(body: Dict[str, Any]) -> Dict[str, Any]:
    content = _content(body)
    data = content.get("data")
    if isinstance(data, dict):
        return data
    return {}


def _articles(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    articles = data.get("检索文章")
    if isinstance(articles, list):
        return [item for item in articles if isinstance(item, dict)]
    return []


def _short(text: Any, limit: int) -> str:
    if text is None:
        return ""
    value = " ".join(str(text).split())
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "..."


def _print_list(title: str, items: Any, fields: Iterable[str], max_items: int) -> None:
    if not isinstance(items, list) or not items:
        return
    print(f"\n{title}")
    for idx, item in enumerate(items[:max_items], start=1):
        if not isinstance(item, dict):
            continue
        print(f"{idx}. {item.get('title') or item.get('标题') or item.get('name') or '未命名'}")
        for field in fields:
            value = item.get(field)
            if value:
                if isinstance(value, list):
                    value = "; ".join(str(v) for v in value)
                print(f"   {field}: {_short(value, 220)}")


def _bail_if_biz_error(body: Dict[str, Any]) -> None:
    """业务码校验（V2，1.6.0）：成功 = ret∈{None,0} 且 content.code∈{None,200}。

    业务错误是 HTTP 200 + content.code=500 + 中文 msg（结构化返回，不当网络失败重试）；
    401 为扁平 {code,msg}（由 _fail_request 的 HTTP 分支处理）。错误输出携带 tid 便于平台排查。
    1.4.0 修复保持：`--json-only` 落盘前与摘要输出前都必须校验——错误响应不得当正常结果落盘。
    """
    content = _content(body)
    code = content.get("code")
    msg = content.get("msg")
    ret = body.get("ret")
    biz_ok = (ret in (None, 0, "0")) and (code in (None, 200, "200"))
    if not biz_ok:
        quota = detect_quota_exhausted(None, msg)
        print(f"错误：可信搜索接口返回 ret={ret} code={code} {msg or ''}".strip())
        print(json.dumps({
            "status": "error",
            "stage": "biz",
            "biz_code": code,
            "ret": ret,
            "tid": body.get("tid"),
            "quota_exhausted": quota,
            "retry_forbidden": quota,
            "user_message": user_message_for_error(None if code != 500 else 500, quota),
            "maas_platform_url": MAAS_PLATFORM_URL,
        }, ensure_ascii=False))
        sys.exit(1)


def _print_summary(body: Dict[str, Any], max_articles: int, max_paragraphs: int, paragraph_chars: int,
                   search_type: str) -> None:
    _bail_if_biz_error(body)

    data = _data(body)
    if not data:
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return

    print(f"可信搜索结果（searchType={search_type}｜tid={body.get('tid') or '未返回'}）")
    for key in ("用户问题", "咨询日期", "办理地域"):
        value = data.get(key)
        if value:
            print(f"{key}：{value}")

    articles = _articles(data)
    total_articles = len(articles)
    display_count = min(max_articles, total_articles)

    if total_articles:
        print(f"\n召回材料：共 {total_articles} 条，聊天窗口展示前 {display_count} 条材料")
    else:
        print("\n召回材料：0 条")

    for idx, article in enumerate(articles[:max_articles], start=1):
        title = article.get('文章标题') or '未命名材料'
        source = article.get('数据源') or article.get('发布或实施机构') or ''
        date = article.get('发布日期') or '接口未返回'
        url = article.get('源网址') or '接口未返回'

        paragraph_text = ''
        paragraphs = article.get("段落")
        if isinstance(paragraphs, list) and paragraphs:
            first = next((p for p in paragraphs if isinstance(p, dict)), {})
            paragraph_text = first.get("内容") or first.get("标题") or ''
        full = article.get("全文")
        if not paragraph_text and full:
            paragraph_text = str(full)

        print(f"\n{idx}. {title}")
        meta = []
        if source:
            meta.append(f"来源：{source}")
        meta.append(f"发布日期：{date}")
        print("｜".join(meta))
        print(f"相关段落：{_short(paragraph_text, paragraph_chars) or '接口未返回'}")
        print(f"原文：{url}")


def main() -> None:
    parser = argparse.ArgumentParser(description="深知可信搜索调用脚本（V2 接口，1.6.0 起）")
    parser.add_argument("query", help="用户搜索问题")
    parser.add_argument("--endpoint", help="覆盖可信搜索接口地址（默认 V2：open-api/maas/dependable/v2/search）")
    parser.add_argument("--service-area", help="办理地域，只传一个中文地域名")
    parser.add_argument("--eff-time", help="生效时间，只传一个日期值，如 2026年、2026年07月")
    parser.add_argument("--search-type", default=DEFAULT_SEARCH_TYPE,
                        help=f"检索材料类型，单值必填：{'/'.join(SEARCH_TYPES)}；默认 {DEFAULT_SEARCH_TYPE}。"
                             "混传报错——需要两类来源时并行调用两路再合并")
    parser.add_argument("--policy", action="store_true", help="返回规范性文件清单（默认开启）")
    parser.add_argument("--no-policy", action="store_true", help="不返回规范性文件清单")
    parser.add_argument("--return-full-content", action="store_true", help="返回资料全文")
    parser.add_argument("--segment-count", type=int, default=DEFAULT_SEGMENT_COUNT,
                        help=f"每篇材料最多返回段落数（默认 {DEFAULT_SEGMENT_COUNT}，1.6.0 实测定档）")
    parser.add_argument("--material-length", type=int, default=DEFAULT_MATERIAL_LENGTH,
                        help=f"每段材料长度上限（默认 {DEFAULT_MATERIAL_LENGTH}，与 segmentCount 配套定档）")
    parser.add_argument("--search-channel", default="",
                        choices=["webSearch", "govSearch", "wxSearch"],
                        help="动态搜索渠道（单值）：webSearch=自动联网搜索模式（返回互联网网页正文段落+源网址，"
                             "可溯源到原段；dataAuthority 自动开启）；govSearch=政府站定向；wxSearch=微信生态。"
                             "默认不传=只查深知库内")
    parser.add_argument("--data-authority", action="store_true",
                        help="请求返回文章级 数据权威性 标注（联网路自动开启，无需显式传）")
    parser.add_argument("--no-filter-para", action="store_true",
                        help="关闭段落过滤 filterPara（默认开启，剔除低匹配段落）")
    parser.add_argument("--query-top-area", action="store_true",
                        help="开启 queryTopArea（由接口带出上级地域材料）；默认关闭，上级材料走单独构路")
    parser.add_argument("--simplified", action="store_true",
                        help="精炼输出（剔除部分材料；将丢失存档快照 screenShotPath 与部分候选材料，不建议在需要生成核验报告时使用）")
    parser.add_argument("--max-articles", type=int, default=3, help="摘要最多展示材料数")
    parser.add_argument("--max-paragraphs", type=int, default=1, help="每篇材料最多展示段落数")
    parser.add_argument("--paragraph-chars", type=int, default=1200, help="每段最多展示字符数")
    parser.add_argument("--show-payload", action="store_true", help="打印请求参数")
    parser.add_argument("--dry-run", action="store_true", help="只打印请求参数，不发起请求")
    parser.add_argument("--json-only", action="store_true", help="仅输出原始 JSON")
    parser.add_argument("--output", "-o", help="搜索结果 JSON 文件名，写入 official-docs/search-results/（配合 --json-only 使用）")
    parser.add_argument("--timeout", type=int, default=60, help="请求超时秒数")
    args = parser.parse_args()

    args.search_type = _validate_search_type(args.search_type)
    endpoint = _pick(
        args.endpoint,
        os.environ.get("DKNOWC_TRUSTED_SEARCH_ENDPOINT"),
        os.environ.get("DKNOWC_KNOW_SEARCH_ENDPOINT"),
        DEFAULT_ENDPOINT,
    )
    api_key = _pick(
        os.environ.get("DKNOWC_API_KEY"),
    )
    if not api_key:
        # 宿主进程读不到 shell 环境变量时，从专用配置文件兜底解析已持久化的 Key
        try:
            from api_key import resolve_api_key
            api_key, _source = resolve_api_key()
        except ImportError:
            pass

    if not api_key:
        print("错误：缺少 api_key，请配置环境变量 DKNOWC_API_KEY。", file=sys.stderr)
        sys.exit(2)

    payload = _build_payload(args)
    if args.show_payload:
        print("=== 可信搜索请求参数（V2） ===")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print()
    if args.dry_run:
        return

    body = _post(endpoint, api_key, payload, args.timeout)
    if args.json_only:
        _bail_if_biz_error(body)  # 落盘前校验：错误响应不落盘、不报"已保存"（1.4.0 修复）
        # 检索通道打标（1.5.0）：每篇检索文章注入 检索通道="深知可信搜索"，供 merge →
        # 渲染按接口通道拆分计数与来源声明；1.6.0 起同时记录本路 searchType（V2 单值）
        _content = body.get("content") if isinstance(body.get("content"), dict) else {}
        _data = _content.get("data") if isinstance(_content.get("data"), dict) else {}
        _channel_tag = "深知可信搜索·联网" if args.search_channel == "webSearch" else "深知可信搜索"
        for _a in (_data.get("检索文章") or []):
            if isinstance(_a, dict):
                if not _a.get("检索通道"):
                    _a["检索通道"] = _channel_tag
                if not _a.get("检索类型"):
                    _a["检索类型"] = args.search_type
                # 联网路统一补 非官方来源 标记（dataAuthority 缺失/未开时兜底；渲染层按此+数据权威性双口径打徽标）
                if args.search_channel == "webSearch":
                    _a["非官方来源"] = True
        raw_json = json.dumps(body, ensure_ascii=False, indent=2)
        if args.output:
            output_path = resolve_output_json(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(raw_json, encoding="utf-8")
            # 绝对路径输出（2026-09-28 修复）：只打相对路径时 Agent 会到工作区 cwd 下找、
            # 找不到就全盘 find（实测触发宿主 ~/.ssh 读取询问）——落盘位置在 skill 目录，直接给绝对路径
            print(f"已保存搜索结果 JSON（位于 skill 工作区，绝对路径）：{output_path}")
        else:
            print(raw_json)
        return
    _print_summary(body, args.max_articles, args.max_paragraphs, args.paragraph_chars, args.search_type)


if __name__ == "__main__":
    main()
