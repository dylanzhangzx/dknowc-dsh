#!/usr/bin/env python3
"""来源展示口径：政策材料显示发文机构，非政策也不显示数据源网站名。

本包链路为可信搜索 V2 + 深度搜索 V3。展示层一律不出现“数据源”网站名：
政策只显示接口返回的发文机构，缺失显示“发文机构待补”；非政策显示发文机构，
缺失显示“公开网站”。不从标题推导发文机构。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple


def clean_issuer(value: Any) -> str:
    """清理接口返回的发文机构：去掉所有 ## 分隔标记与多余空白。

    V2 的「发布或实施机构」是多机构顿号串，每个机构后都带 ##（如
    `广东省人力资源和社会保障厅##、中国人民银行广东省分行##`），只去首尾会
    在展示层漏出 `##`，因此整串清除。
    """
    text = str(value or "")
    text = re.sub(r"#+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def source_identity(item: Dict[str, Any], vo: Optional[Dict[str, Any]] = None) -> Tuple[str, str, str, bool]:
    """返回 (展示用机构/来源, 数据源, 原始发文机构, 是否政策)。"""
    vo = vo if isinstance(vo, dict) else {}
    unit = item.get("unit")
    if isinstance(unit, list):
        unit_parts = [clean_issuer(x) for x in unit if isinstance(x, str)]
        unit_text = "、".join(x for x in unit_parts if x)
    else:
        unit_text = clean_issuer(unit)
    issuer = clean_issuer("" if not isinstance(item.get("发布或实施机构"), str) else item.get("发布或实施机构"))
    if not issuer:
        issuer = clean_issuer("" if not isinstance(item.get("发布机关"), str) else item.get("发布机关"))
    if not issuer:
        issuer = clean_issuer(unit_text)
    # 不再使用 sourceElement：历史 JSON 里它常是“中国经济网/中国政府网”这类站点名，
    # 不是发文机构。缺机构字段时按政策/非政策显示“发文机构待补/公开网站”，不从标题推导。
    # 个别脏数据把门户网站写进“发布或实施机构”，不得当发文机构使用。
    if any(marker in issuer for marker in ("网站", "门户", "信息常见问答")):
        issuer = ""
    data_source = ""
    for value in (item.get("数据源"), item.get("来源"), vo.get("typeName"), vo.get("sourceName")):
        if isinstance(value, str) and value.strip():
            data_source = value.strip()
            break
    article_type = ""
    for value in (item.get("文章类型"), item.get("articleType")):
        if isinstance(value, str) and value.strip():
            article_type = value.strip()
            break
    is_policy = article_type.strip().lower() == "policy" or article_type.strip() == "政策"
    # 展示层一律不出现“数据源”网站名（项目口径）。
    # 只使用接口返回的发文机构，不从标题推导。
    agency = issuer or ("发文机构待补" if is_policy else "公开网站")
    return agency, data_source, issuer, is_policy
