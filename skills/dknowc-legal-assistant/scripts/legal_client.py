#!/usr/bin/env python3
"""深知法律助手 · 接口客户端。

覆盖法律场景需要的 MaaS 接口：
- 001 政策条件筛选  /policy-data/v1/policies/filter
- 002 政策正文查询  /policy-data/v1/policy-contents/get
- 003 政策历次版本  /policy-data/v1/policy-versions/query
- 005 正文下载      /policy-data/v1/policy-contents/download
- 012 可信搜索 V2   /open-api/maas/dependable/v2/search

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
from urllib.parse import urlparse

BASE = "https://open.dknowc.cn/open-api/maas"
SEARCH_ENDPOINT = BASE + "/dependable/v2/search"
POLICY_FILTER = BASE + "/policy-data/v1/policies/filter"
POLICY_CONTENT = BASE + "/policy-data/v1/policy-contents/get"
POLICY_VERSIONS = BASE + "/policy-data/v1/policy-versions/query"
POLICY_DOWNLOAD = BASE + "/policy-data/v1/policy-contents/download"


class LegalApiError(RuntimeError):
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
    raise LegalApiError("auth", "缺少 DKNOWC_API_KEY；请配置环境变量或 ~/.config/dknowc/api_key", None)


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
        raise LegalApiError("http", f"HTTP {exc.code}: {detail}", exc.code, detail)
    except urllib.error.URLError as exc:
        raise LegalApiError("network", f"网络错误: {exc.reason}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise LegalApiError("parse", f"返回非 JSON: {raw[:200]}")


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
        raise LegalApiError("policy-filter", body.get("message") or f"ret={body.get('ret')} code={body.get('code')}", None, body)
    content = body.get("content") or {}
    return [x for x in (content.get("policies") or []) if isinstance(x, dict)]


def query_versions(file_id: str) -> Dict[str, Any]:
    body = _post(POLICY_VERSIONS, {"encryptedFileId": file_id, "searchType": "policy"})
    if body.get("ret") != 1 or (body.get("code") or 0) != 200:
        raise LegalApiError("policy-versions", body.get("message") or f"ret={body.get('ret')} code={body.get('code')}", None, body)
    return body.get("content") or {}


def get_content(file_id: str, version_id: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"encryptedFileId": file_id, "searchType": "policy"}
    if version_id:
        payload = {"encryptedVersionId": version_id, "searchType": "policy"}
    body = _post(POLICY_CONTENT, payload)
    if body.get("ret") != 1 or (body.get("code") or 0) != 200:
        raise LegalApiError("policy-content", body.get("message") or f"ret={body.get('ret')} code={body.get('code')}", None, body)
    return body.get("content") or {}


ALLOWED_DOWNLOAD_HOSTS = {"open.dknowc.cn", "attach.dknowc.cn"}


def _validate_download_url(download_url: str) -> str:
    """下载地址只允许 https + 深知域名，避免把 api-key 发往接口返回的任意主机。"""
    parsed = urlparse((download_url or "").strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise LegalApiError("download", "下载地址不在允许的域名内，已拒绝发送 api-key")
    return download_url


def download_text(download_url: str, timeout: int = 90, key: Optional[str] = None) -> str:
    download_url = _validate_download_url(download_url)
    api_key = key or resolve_key()
    req = urllib.request.Request(download_url, headers=_headers(api_key))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:300]
        raise LegalApiError("download", f"下载失败 HTTP {exc.code}: {detail}", exc.code)
    except urllib.error.URLError as exc:
        raise LegalApiError("download", f"下载失败: {exc.reason}")


def get_full_text(file_id: str) -> Tuple[Dict[str, Any], str]:
    content = get_content(file_id)
    url = ((content.get("contentFile") or {}).get("downloadUrl") or "").strip()
    if not url:
        return content, ""
    return content, download_text(url)


def semantic_search(
    query: str,
    limit_articles: int = 10,
    segment_count: int = 6,
    material_length: int = 25000,
    service_area: Optional[str] = None,
    policy_labels: Optional[List[str]] = None,
    search_channel: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "query": query,
        "searchType": ["policy"],
        "validityFilter": False,
        "searchGranularity": "PROVISION",
        "segmentCount": segment_count,
        "MaterialLength": material_length,
        "filterPara": True,
        # 数据权威性（2026-11-05 实测可用）：返回"权威/非权威"，渲染层据此打来源徽标，
        # 与 existing 的"非官方来源"口径并用。字段很小，默认打开。
        "dataAuthority": True,
    }
    if service_area:
        payload["service_area"] = [service_area]
    # 标签过滤（2026-11-05）：传父标签"法律/法律标签/法律"可滤掉语义召回里的新闻稿/问答页
    # （实测 T1 的中国法院网新闻稿、政府问答页都不带该标签）。注意司法解释/批复不在
    # 该标签族内——查解释类文件时不要传，否则目标文件会被漏掉。
    if policy_labels:
        payload["policyLabels"] = policy_labels
    # 联网检索（2026-11-10，阶段二）：库内无果/支撑不足时，先用深知自己的
    # webSearch 通道补公开网页原文；外部材料由接口/渲染层标“非官方来源”。
    if search_channel:
        payload["searchChannel"] = [search_channel]
    body = _post(SEARCH_ENDPOINT, payload)
    content = body.get("content") or {}
    if (content.get("code") or 0) != 200:
        raise LegalApiError("semantic-search", content.get("msg") or f"code={content.get('code')}", None, body)
    data = content.get("data") or {}
    articles = [x for x in (data.get("检索文章") or []) if isinstance(x, dict)]
    # 带标签检索 0 条时不再静默降级重查（2026-11-06）：按接口契约，标签是调用方
    # 明确指定的范围限定；静默去掉标签会把"标签过滤没命中"伪装成"检索成功"，
    # 掩盖接口问题。这里只标注结果为空，由调用方决定是否另发一次不带标签的检索，
    # 并把两次结果分别记录、在报告中如实展示。
    if policy_labels and not articles:
        body["_legal_label_zero"] = True
    if limit_articles and len(articles) > limit_articles:
        data["检索文章"] = articles[:limit_articles]
    return body
