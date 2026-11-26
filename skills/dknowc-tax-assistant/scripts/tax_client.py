#!/usr/bin/env python3
"""深知税务助手 · 接口客户端。

覆盖税务场景需要的 MaaS 接口（对外一律用产品名，不用内部代号）：
- 可信搜索接口 V2   /dependable/v2/search          主路：条款级语义召回
- 政策条件筛选      /policy-data/v1/policies/filter
- 政策正文          /policy-data/v1/policy-contents/get
- 历次版本          /policy-data/v1/policy-versions/query
- 全文下载          /policy-data/v1/policy-contents/download

统一鉴权：请求头 api-key。Key 解析优先 DKNOWC_API_KEY，其次 ~/.config/dknowc/api_key。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE = "https://open.dknowc.cn/open-api/maas"
SEARCH_ENDPOINT = BASE + "/dependable/v2/search"
POLICY_FILTER = BASE + "/policy-data/v1/policies/filter"
POLICY_CONTENT = BASE + "/policy-data/v1/policy-contents/get"
POLICY_VERSIONS = BASE + "/policy-data/v1/policy-versions/query"
POLICY_DOWNLOAD = BASE + "/policy-data/v1/policy-contents/download"


class TaxApiError(RuntimeError):
    def __init__(self, stage: str, message: str, status_code: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.stage = stage
        self.status_code = status_code
        self.body = body


def resolve_key() -> str:
    key = os.environ.get("DKNOWC_API_KEY", "").strip()
    if key:
        return key
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from api_key import resolve_api_key  # type: ignore
        key, _source = resolve_api_key()
        if key:
            return key
    except Exception:
        pass
    raise TaxApiError("auth", "缺少 DKNOWC_API_KEY；请配置环境变量或 ~/.config/dknowc/api_key", None)


def _headers(api_key: str) -> Dict[str, str]:
    headers = {"api-key": api_key, "Content-Type": "application/json"}
    try:
        from attribution import build_attribution_header, ATTRIBUTION_HEADER  # type: ignore
        attr = build_attribution_header()
        if attr:
            headers[ATTRIBUTION_HEADER] = attr
    except Exception:
        pass
    return headers


def _post(url: str, payload: Dict[str, Any], timeout: int = 60, key: Optional[str] = None) -> Dict[str, Any]:
    api_key = key or resolve_key()
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_headers(api_key))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:500]
        raise TaxApiError("http", f"HTTP {exc.code}: {detail}", exc.code, detail)
    except urllib.error.URLError as exc:
        raise TaxApiError("network", f"网络错误: {exc.reason}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise TaxApiError("parse", f"返回非 JSON: {raw[:200]}")


def filter_policies(
    title: str,
    limit: int = 20,
    filters: Optional[Dict[str, Any]] = None,
    timeout: int = 60,
) -> List[Dict[str, Any]]:
    payload: Dict[str, Any] = {
        "filters": {"title": title},
        "searchType": ["policy"],
        "limit": limit,
    }
    if filters:
        payload["filters"].update(filters)
    body = _post(POLICY_FILTER, payload, timeout=timeout)
    if body.get("ret") != 1 or (body.get("code") or 0) != 200:
        raise TaxApiError("policy-filter", body.get("message") or f"ret={body.get('ret')} code={body.get('code')}", None, body)
    content = body.get("content") or {}
    return [x for x in (content.get("policies") or []) if isinstance(x, dict)]


def query_versions(file_id: str) -> Dict[str, Any]:
    body = _post(POLICY_VERSIONS, {"encryptedFileId": file_id, "searchType": "policy"})
    if body.get("ret") != 1 or (body.get("code") or 0) != 200:
        raise TaxApiError("policy-versions", body.get("message") or f"ret={body.get('ret')} code={body.get('code')}", None, body)
    return body.get("content") or {}


def get_content(file_id: str, version_id: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"encryptedFileId": file_id, "searchType": "policy"}
    if version_id:
        payload = {"encryptedVersionId": version_id, "searchType": "policy"}
    body = _post(POLICY_CONTENT, payload)
    if body.get("ret") != 1 or (body.get("code") or 0) != 200:
        raise TaxApiError("policy-content", body.get("message") or f"ret={body.get('ret')} code={body.get('code')}", None, body)
    return body.get("content") or {}


def _validate_download_url(download_url: str) -> None:
    """下载地址白名单校验（2026-11-06 复审收紧：exact-host 口径，与深知系列产品现行口径一致）。

    download_text 会携带 api-key 请求头请求该地址；URL 来自接口返回的
    contentFile.downloadUrl。仅允许：https + 精确主机名（open.dknowc.cn /
    attach.dknowc.cn）+ 默认 443 端口 + 无 userinfo。任意子域通配、非 443 端口、
    带 username/password 的 URL 一律拒绝。
    """
    from urllib.parse import urlparse
    allowed_hosts = {"open.dknowc.cn", "attach.dknowc.cn"}
    parsed = urlparse(download_url or "")
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        raise TaxApiError("download", f"下载地址校验失败：仅允许 https（实际 {parsed.scheme or '无'}），拒绝携带 api-key 请求")
    if host not in allowed_hosts:
        raise TaxApiError("download", f"下载地址校验失败：非白名单主机（{host}，仅允许 {'/'.join(sorted(allowed_hosts))}），拒绝携带 api-key 请求")
    if parsed.port not in (None, 443):
        raise TaxApiError("download", f"下载地址校验失败：非 443 端口（{parsed.port}），拒绝携带 api-key 请求")
    if parsed.username or parsed.password:
        raise TaxApiError("download", f"下载地址校验失败：URL 含 userinfo，拒绝携带 api-key 请求")


def download_text(download_url: str, timeout: int = 90, key: Optional[str] = None) -> str:
    _validate_download_url(download_url)
    api_key = key or resolve_key()
    req = urllib.request.Request(download_url, headers=_headers(api_key))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:300]
        raise TaxApiError("download", f"下载失败 HTTP {exc.code}: {detail}", exc.code)
    except urllib.error.URLError as exc:
        raise TaxApiError("download", f"下载失败: {exc.reason}")


def get_full_text(file_id: str) -> Tuple[Dict[str, Any], str]:
    content = get_content(file_id)
    url = ((content.get("contentFile") or {}).get("downloadUrl") or "").strip()
    if not url:
        return content, ""
    return content, download_text(url)


def semantic_search(
    query: str,
    limit_articles: int = 10,
    segment_count: int = 8,
    material_length: int = 25000,
    service_area: Optional[str] = None,
    policy_labels: Optional[List[str]] = None,
    search_channel: Optional[str] = None,
) -> Dict[str, Any]:
    """可信搜索接口 V2：税务检索主路。

    参数口径见 reference/retrieval-v2.md：
    - PROVISION 条款级召回；filterPara/dataAuthority 默认开；
    - validityFilter 默认 false（true 时召回经常为 0，不用于常规对比）；
    - policyLabels 必须传完整路径（族+类型+目录名），多个标签按且（AND）召回。
    """
    payload: Dict[str, Any] = {
        "query": query,
        "searchType": ["policy"],
        "validityFilter": False,
        "searchGranularity": "PROVISION",
        "segmentCount": segment_count,
        "MaterialLength": material_length,
        "filterPara": True,
        # 数据权威性：返回"权威/非权威"，渲染层据此打来源徽标；字段很小，默认打开。
        "dataAuthority": True,
    }
    if service_area:
        payload["service_area"] = [service_area]
    # 标签过滤（2026-11-05/06 实测）：只传叶子名不生效，必须完整路径；
    # 税务族 = 政策/主题标签/财政、金融、审计/税务；
    # 社保是另一个族 = 政策/主题标签/劳动、人事、监察/社会保障，不要与税务标签混用。
    if policy_labels:
        payload["policyLabels"] = policy_labels
    # 联网检索模式（2026-11-10，对齐可信搜索 1.7.2 阶段二）：searchChannel 单值传
    # webSearch/govSearch/wxSearch，返回互联网正文段落+源网址；dataAuthority 已默认开，
    # 联网结果为"非权威"，调用方需补 非官方来源 标记供渲染层打徽标。
    if search_channel:
        payload["searchChannel"] = [search_channel]
    body = _post(SEARCH_ENDPOINT, payload)
    content = body.get("content") or {}
    if (content.get("code") or 0) != 200:
        raise TaxApiError("semantic-search", content.get("msg") or f"code={content.get('code')}", None, body)
    data = content.get("data") or {}
    articles = [x for x in (data.get("检索文章") or []) if isinstance(x, dict)]
    # 带标签检索 0 条时不静默降级重查：标签是调用方明确指定的范围限定，静默去掉
    # 标签会把"标签过滤没命中"伪装成"检索成功"。这里只标注结果为空（label_zero），
    # 由调用方决定是否另发一次不带标签的独立检索，两次结果分别落盘、分别展示。
    if policy_labels and not articles:
        body["_tax_label_zero"] = True
    if limit_articles and len(articles) > limit_articles:
        data["检索文章"] = articles[:limit_articles]
    return body
