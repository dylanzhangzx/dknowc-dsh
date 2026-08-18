#!/usr/bin/env python3
"""
DKAG 素材召回接口脚本
用于根据查询关键词召回相关公文素材

使用深知可信搜索接口：/dependable/search/
"""

import argparse
import html
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

import requests

# ========== DKAG 搜索限制配置 ==========
# 本 skill 专门处理公文写作场景

# 查询关键词长度限制
MAX_QUERY_LENGTH = 500          # 最大查询字符数
MIN_QUERY_LENGTH = 2            # 最小查询字符数

# 错误提示
QUERY_TOO_LONG_ERROR = f"错误：查询关键词过长，超过限制（最大 {MAX_QUERY_LENGTH} 字符）"
QUERY_TOO_SHORT_ERROR = f"错误：查询关键词过短，最少需要 {MIN_QUERY_LENGTH} 个字符"
# ==========================================

# API Key 与搜索结果路径
SKILL_ROOT = Path(__file__).resolve().parent.parent
# 工作区根：dsh 场景通过环境变量 DKNWOC_WS_ROOT 指向会话工作区，未设置时回退到 skill 目录（SkillHub 兼容）
import os as _os
WS_ROOT = Path(_os.environ.get("DKNWOC_WS_ROOT") or _os.getcwd()).resolve()

API_KEY_ENV = "DKNOWC_API_KEY"
DEFAULT_BASE_URL = "https://open.dknowc.cn/dependable/search/"
SEARCH_RESULTS_DIR = WS_ROOT / "official-docs" / "search-results"
CONFIG_HELP_URL = "https://platform.dknowc.cn/"
FIXED_SEGMENT_COUNT = 2
FIXED_SIMPLIFIED = False
DEFAULT_MATERIAL_LENGTH = 12000
VALID_SEARCH_TYPES = {"policy", "affair", "govSite", "qa", "private"}
VALID_SEARCH_CHANNELS = {"govSearch", "webSearch", "wxSearch"}


def normalize_time_filter(time: Optional[str]) -> Optional[str]:
    """
    接口的 eff_time 对横杠式时间范围较敏感。
    公文写作场景默认不强制按年份范围过滤，遇到 2023-2025 这类范围时直接忽略，
    避免服务端返回 500 影响素材召回。
    """
    if not time:
        return None
    value = time.strip()
    if not value:
        return None
    if re.search(r'\d{4}\s*[-~—–至到]\s*\d{4}', value):
        return None
    return value


def is_relative_to(path: Path, parent: Path) -> bool:
    """兼容旧 Python 版本的 Path.is_relative_to。"""
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_output_json(output_path: str) -> Path:
    """只允许将搜索结果写入 skill 的搜索结果目录。"""
    raw_path = Path(output_path).expanduser()
    if raw_path.is_absolute():
        resolved = raw_path.resolve()
    elif raw_path.parent == Path("."):
        resolved = (SEARCH_RESULTS_DIR / raw_path.name).resolve()
    else:
        resolved = (WS_ROOT / raw_path).resolve()

    if resolved.suffix.lower() != ".json":
        resolved = resolved.with_suffix(".json")
    if not is_relative_to(resolved, SEARCH_RESULTS_DIR.resolve()):
        raise ValueError(f"输出文件必须位于搜索结果目录内: {SEARCH_RESULTS_DIR}")
    return resolved


def parse_list_values(values: Optional[list[str]]) -> list[str]:
    """解析命令行传入的多值参数，兼容重复传参和逗号分隔。"""
    parsed: list[str] = []
    for value in values or []:
        for item in str(value).split(","):
            item = item.strip()
            if item and item not in parsed:
                parsed.append(item)
    return parsed


def validate_choices(values: list[str], valid_values: set[str], field_name: str) -> list[str]:
    """校验接口枚举参数，避免拼写错误导致检索范围失控。"""
    invalid = [value for value in values if value not in valid_values]
    if invalid:
        valid_text = ", ".join(sorted(valid_values))
        raise ValueError(f"{field_name} 包含无效值: {', '.join(invalid)}；可选值: {valid_text}")
    return values


def normalize_material_length(material_length: Optional[int]) -> int:
    """限制单次检索返回材料体量，避免过长上下文影响写作。"""
    if material_length is None:
        return DEFAULT_MATERIAL_LENGTH
    if material_length <= 0:
        raise ValueError("MaterialLength 必须为正整数")
    return material_length


def extract_knowledge_base_url(api_response: dict) -> str:
    """
    从深知搜索返回中提取知识专库链接。

    新接口中 knowledgeBase 位于 content.knowledgeBase，不在 content.data 内。
    为兼容不同 Agent 的读取习惯，脚本会在输出阶段把该链接冗余写入多个稳定字段。
    """
    content = api_response.get("content", {})
    if not isinstance(content, dict):
        return ""
    candidates = [
        content.get("knowledgeBase", ""),
        api_response.get("knowledgeBase", ""),
    ]
    data = content.get("data", {})
    if isinstance(data, dict):
        candidates.append(data.get("knowledgeBase", ""))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def attach_knowledge_base_aliases(result: dict, knowledge_base_url: str) -> dict:
    """把知识专库链接写入多个稳定位置，降低 Agent 找不到链接的概率。"""
    if not knowledge_base_url:
        return result

    result["knowledgeBase"] = knowledge_base_url
    result["knowledgeBasePath"] = "content.knowledgeBase"
    result["knowledgeBase_note"] = "知识专库链接来自深知搜索接口返回的 content.knowledgeBase；脚本已冗余复制到顶层 knowledgeBase。"

    search_meta = result.get("search_meta")
    if isinstance(search_meta, dict):
        search_meta["knowledgeBase"] = knowledge_base_url

    content = result.get("content")
    if isinstance(content, dict):
        content["knowledgeBase"] = knowledge_base_url
        data = content.get("data")
        if isinstance(data, dict):
            data["knowledgeBase"] = knowledge_base_url
            data["knowledgeBase_note"] = "兼容字段：原始链接位于 content.knowledgeBase。"

    return result


def load_config(config_path: Optional[Path] = None) -> dict:
    """
    从统一环境变量加载 API Key。搜索接口地址固定为 DEFAULT_BASE_URL。
    """
    if config_path is not None:
        raise ValueError(f"当前版本不再读取 config.ini，请通过环境变量 {API_KEY_ENV} 配置 API Key。")

    api_key = os.environ.get(API_KEY_ENV, "").strip()
    if not api_key or api_key in {"your_api_key_here", "你的深知搜索 API Key"}:
        raise ValueError(
            f"API Key 为空，请通过环境变量 {API_KEY_ENV} 配置有效 API Key。"
        )
    
    return {
        "api_key": api_key,
        "api_key_source": "environment",
    }


def clean_dkag_response(api_response: dict) -> dict:
    """
    清洗 DKAG API 返回的数据

    清洗逻辑：
    1. 处理 HTML 转义字符（如 &nbsp; 等）
    2. 移除网页干扰词（如 "首页 > 打印"）
    3. 统一换行符并合并多余换行
    4. 合并多余的空格和制表符
    5. 为每个段落分配唯一 ID

    Args:
        api_response: DKAG API 原始返回的 JSON

    Returns:
        清洗后的结果字典
    """
    try:
        # 按照新接口路径定位文章列表
        # 新接口格式：content -> data -> 检索文章
        inner_content = api_response.get("content", {})
        
        # 兼容新接口的嵌套结构
        if "data" in inner_content:
            real_data = inner_content.get("data", {})
        else:
            real_data = inner_content
            
        articles = real_data.get("检索文章", [])
        
        # 提取 knowledgeBase 链接。新接口中该字段在 content.knowledgeBase，不在 content.data 内。
        knowledge_base_url = extract_knowledge_base_url(api_response)

        if not articles:
            return {
                "cleaned": True,
                "articles": [],
                "message": "未检索到相关参考文章",
                "knowledgeBase": knowledge_base_url
            }

        cleaned_articles = []
        global_id_counter = 1

        for art in articles:
            cleaned_art = {
                "文章标题": art.get("文章标题", "无标题"),
                "发布日期": art.get("发布日期", ""),
                "数据源": art.get("数据源", "未知来源"),
                "段落": []
            }
            for key in ("源网址", "sourceUrl", "source_url", "原文链接", "原文地址", "文章链接", "url", "URL"):
                if art.get(key):
                    cleaned_art["源网址"] = str(art[key]).strip()
                    break
            if art.get("办理地域"):
                cleaned_art["办理地域"] = str(art["办理地域"]).strip()
            if art.get("发布日期可信度"):
                cleaned_art["发布日期可信度"] = str(art["发布日期可信度"]).strip()
            # 保留接口返回的原文地址，供可信溯源报告展示“查看原文”。
            for key in ("sourceUrl", "source_url", "原文链接", "原文地址", "文章链接", "url", "URL"):
                if art.get(key):
                    cleaned_art["原文链接"] = str(art[key]).strip()
                    break
            for key in ("policyUrl", "policy_url", "知识专库原文"):
                if art.get(key):
                    cleaned_art["知识专库原文"] = str(art[key]).strip()
                    break

            # 遍历段落并清洗
            paragraphs = art.get("段落", [])
            for p in paragraphs:
                # 提取标题和内容
                p_title = p.get("标题", "").strip()
                p_content = p.get("内容", "").strip()

                # 合并标题和内容
                full_text = f"{p_title}\n{p_content}" if p_title else p_content

                # --- 清洗逻辑 ---
                # 1. 处理 HTML 转义字符 (如 &nbsp; 等)
                content = html.unescape(full_text)

                # 2. 移除特定的网页干扰词
                content = re.sub(r'首页\s*>\s*.*?\s*打印\s*\]', '', content, flags=re.DOTALL)
                content = re.sub(r'点击\s*\d+.*?次', '', content)
                content = re.sub(r'分享\s*到.*?$', '', content, flags=re.MULTILINE)

                # 3. 统一换行符并合并多余换行
                content = content.replace('\r', '\n')
                content = re.sub(r'\n+', '\n', content)

                # 4. 合并多余的空格和制表符
                content = re.sub(r'[ \t]+', ' ', content)
                content = content.strip()

                if content:
                    # 分配全局唯一的自增 ID
                    cleaned_art["段落"].append({
                        "id": global_id_counter,
                        "标题": p_title,
                        "内容": content
                    })
                    global_id_counter += 1

            # 只有当文章清洗后仍有有效段落时才添加
            if cleaned_art["段落"]:
                cleaned_articles.append(cleaned_art)

        # 如果没有有效结果
        if not cleaned_articles:
            return {
                "cleaned": True,
                "articles": [],
                "message": "素材内容经过清洗后为空"
            }

        # 提取规范性文件清单（policyFiles）
        policy_files = real_data.get("policyFiles", [])

        # 返回清洗后结果
        return {
            "cleaned": True,
            "articles": cleaned_articles,
            "total_articles": len(cleaned_articles),
            "total_paragraphs": global_id_counter - 1,
            "knowledgeBase": knowledge_base_url,
            "knowledgeBasePath": "content.knowledgeBase",
            "knowledgeBase_note": "知识专库链接来自深知搜索接口返回的 content.knowledgeBase；脚本已冗余复制到顶层 knowledgeBase。",
            "policyFiles": policy_files
        }

    except Exception as e:
        # 返回报错信息方便排查
        return {
            "cleaned": False,
            "error": True,
            "message": f"数据清洗报错: {type(e).__name__} - {str(e)}"
        }


def dkag_search(
    query: str,
    area: Optional[str] = None,
    time: Optional[str] = None,
    purpose: Optional[str] = None,
    api_key: Optional[str] = None,
    config_path: Optional[Path] = None,
    clean: bool = False,
    policy: bool = False,
    full: bool = False,
    search_types: Optional[list[str]] = None,
    search_channels: Optional[list[str]] = None,
    material_length: Optional[int] = DEFAULT_MATERIAL_LENGTH,
) -> dict:
    """
    调用深知可信搜索接口召回素材

    API 文档：
    - 请求路径: https://open.dknowc.cn/dependable/search/
    - 请求方式: POST
    - Content-Type: application/json
    - 认证方式: api-key 请求头

    Args:
        query: 搜索关键词（必填，支持完整句子）
        area: 用户所属地域（可选，默认"中国"），如"广东省"、"北京市"
        time: 生效日期（可选），如"2026年"、"2025年08月"、"2025年08月15日"。
              不建议传"2023-2025"这类范围，脚本会自动忽略。
        purpose: 搜索方案中的搜索目的，用于素材来源说明中的知识专库链接显示名。
        api_key: API 密钥（可选，如不传则从 DKNOWC_API_KEY 读取）
        clean: 是否对返回结果进行数据清洗（默认 False）
        policy: 是否返回规范性文件清单policyFiles（默认 False）
        full: 是否返回文章全文（return_full_content，默认 False）
        search_types: 指定搜索素材类型，如 policy、affair、govSite、qa、private
        search_channels: 指定动态搜索渠道，如 govSearch、webSearch、wxSearch
        material_length: 控制返回素材总长度，默认 12000
        本 skill 固定使用 segmentCount=2，每篇材料最多返回 2 个相关段落。

    Returns:
        搜索结果字典
    """
    # 验证查询关键词
    if len(query) > MAX_QUERY_LENGTH:
        return {
            "error": True,
            "message": QUERY_TOO_LONG_ERROR,
            "query_length": len(query),
            "max_length": MAX_QUERY_LENGTH
        }

    if len(query) < MIN_QUERY_LENGTH:
        return {
            "error": True,
            "message": QUERY_TOO_SHORT_ERROR,
            "query_length": len(query),
            "min_length": MIN_QUERY_LENGTH
        }

    # 获取 API Key。搜索接口地址固定为 DEFAULT_BASE_URL。
    if not api_key:
        config = load_config(config_path)
        api_key = config["api_key"]

    normalized_time = normalize_time_filter(time)
    try:
        normalized_search_types = validate_choices(
            parse_list_values(search_types),
            VALID_SEARCH_TYPES,
            "searchType"
        )
        normalized_search_channels = validate_choices(
            parse_list_values(search_channels),
            VALID_SEARCH_CHANNELS,
            "searchChannel"
        )
        normalized_material_length = normalize_material_length(material_length)
    except ValueError as e:
        return {
            "error": True,
            "message": str(e)
        }

    # 构建请求体（新接口格式）
    payload = {
        "query": query,
        "eff_time": [normalized_time] if normalized_time else [""],
        "service_area": [area] if area else [""],
        "knowBase": True,
        "policy": policy,
        "return_full_content": full,
        "segmentCount": FIXED_SEGMENT_COUNT,
        "simplified": FIXED_SIMPLIFIED,
        "MaterialLength": normalized_material_length
    }

    if normalized_search_types:
        payload["searchType"] = normalized_search_types
    if normalized_search_channels:
        payload["searchChannel"] = normalized_search_channels

    # 构建请求头
    headers = {
        "Content-Type": "application/json",
        "api-key": api_key
    }

    search_meta = {
        "query": query,
        "purpose": (purpose or "").strip(),
        "area": area or "",
        "time": normalized_time or "",
        "requested_time": time or "",
        "time_ignored": bool(time and not normalized_time),
        "policy": policy,
        "full": full,
        "clean": clean,
        "segmentCount": FIXED_SEGMENT_COUNT,
        "simplified": FIXED_SIMPLIFIED,
        "MaterialLength": normalized_material_length,
        "searchType": normalized_search_types,
        "searchChannel": normalized_search_channels
    }

    # 发送请求
    try:
        response = requests.post(DEFAULT_BASE_URL, data=json.dumps(payload), headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        # 新接口返回结构：content.检索文章
        # 需要转换成旧接口的格式以保持兼容
        if "content" in result and "检索文章" in result.get("content", {}):
            # 包装成旧格式
            result = {
                "content": {
                    "data": result["content"]
                }
            }

        if result.get("ret") not in (None, 0, "0") or result.get("errcode") not in (None, 0, "0"):
            return {
                "error": True,
                "message": "深知搜索接口返回异常",
                "ret": result.get("ret"),
                "errcode": result.get("errcode"),
                "errmsg": result.get("errmsg"),
                "bizStatus": result.get("bizStatus"),
                "search_meta": search_meta
            }

        knowledge_base_url = extract_knowledge_base_url(result)

        # 如果需要清洗数据
        if clean:
            cleaned_result = clean_dkag_response(result)
            cleaned_result["search_meta"] = search_meta
            attach_knowledge_base_aliases(cleaned_result, knowledge_base_url or cleaned_result.get("knowledgeBase", ""))
            return cleaned_result
        result["search_meta"] = search_meta
        attach_knowledge_base_aliases(result, knowledge_base_url)
        return result
    except requests.exceptions.RequestException as e:
        return {
            "error": True,
            "message": "请求失败：网络连接、代理或接口返回异常，请检查运行环境和 API Key",
            "error_type": type(e).__name__,
            "payload": payload,
            "status_code": getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None,
            "search_meta": search_meta
        }


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description="DKAG 素材召回接口（V2新接口）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s "在北京申请就业见习单位认定需要哪些材料"
  %(prog)s "留学人才来粤服务政策" --area 广东省
  %(prog)s "北京社保政策" --area 北京市 --json
        """
    )
    parser.add_argument("query", help="搜索关键词（支持完整句子）")
    parser.add_argument("--area", help="用户所属地域（默认: 中国），如: 广东省、北京市")
    parser.add_argument("--time", help="生效日期范围，如: 2026年、2025年08月、2025年08月15日")
    parser.add_argument("--purpose", help="搜索方案中的搜索目的，用于知识专库链接外显文字（内部字段，不向用户展示）")
    parser.add_argument("--api-key", help=f"API 密钥（可选，默认从环境变量 {API_KEY_ENV} 读取）")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    parser.add_argument("--clean", action="store_true", help="对返回结果进行数据清洗（去除HTML转义、网页干扰词等）")
    parser.add_argument("--policy", action="store_true", help="返回规范性文件清单（policyFiles）")
    parser.add_argument("--full", action="store_true", help="返回文章全文（return_full_content）")
    parser.add_argument(
        "--search-type",
        action="append",
        help="指定搜索素材类型，可重复传入或用逗号分隔：policy, affair, govSite, qa, private"
    )
    parser.add_argument(
        "--search-channel",
        action="append",
        help="指定动态搜索渠道，可重复传入或用逗号分隔：govSearch, webSearch, wxSearch"
    )
    parser.add_argument(
        "--material-length",
        type=int,
        default=DEFAULT_MATERIAL_LENGTH,
        help=f"控制返回素材总长度（默认: {DEFAULT_MATERIAL_LENGTH}）"
    )
    parser.add_argument("--output", "-o", help="输出 JSON 文件路径（可选，默认输出到标准输出）")

    args = parser.parse_args()

    # 调用搜索。配置缺失、API Key 缺失等启动阶段异常也输出为结构化 JSON，便于 Agent 稳定转述配置引导。
    try:
        result = dkag_search(
            query=args.query,
            area=args.area,
            time=args.time,
            purpose=args.purpose,
            api_key=args.api_key,
            clean=args.clean,
            policy=args.policy,
            full=args.full,
            search_types=args.search_type,
            search_channels=args.search_channel,
            material_length=args.material_length
        )
    except Exception as exc:
        result = {
            "error": True,
            "message": str(exc),
            "config_help_url": CONFIG_HELP_URL,
            "hint": f"请先配置环境变量 {API_KEY_ENV}，完成后再重新执行搜索。"
        }

    # 输出结果
    output_json = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output_path = resolve_output_json(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_json, encoding="utf-8")
        print(f"✓ 搜索结果已保存: {output_path}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
