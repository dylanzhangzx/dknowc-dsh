#!/usr/bin/env python3
"""深知税务助手 dsh 版初始化检查。

API Key 读取：优先进程环境变量 DKNOWC_API_KEY，缺失时从本机专用配置文件
~/.config/dknowc/api_key（或 DKNOWC_CONFIG_DIR 指定路径）读取
（不读取、不改写任何 shell 配置文件；宿主进程早于 key 写入启动、或宿主安全更新后
不再加载 shell 导出变量时不误报缺失）。注册脚本 register_key.mjs 注册成功后自动把
Key 写入专用配置文件，本检查直读该文件，无需重启宿主。

Key 校验口径：格式检查（非占位符 + sk- 前缀 + 长度）后，默认再做一次
轻量真实检索校验（policies/filter，limit=1，8 秒超时）：
- 401/403 → ready=false，blocking_issues=["api_key_invalid"]；
- 网络超时/5xx → 降级放行，key_validated=false，提示首次检索可能失败；
- --no-verify-key 可跳过真实校验（离线/快速检查）。
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


API_KEY_ENV = "DKNOWC_API_KEY"
MAAS_PLATFORM_URL = "https://platform.dknowc.cn/auth/#/login"
PLACEHOLDER_KEYS = {"", "your_api_key_here", "你的深知税务助手 API Key", "你的深知可信搜索 API Key", "你的深知搜索 API Key"}
# register_key.mjs 使用全局 fetch，要求 Node 18+；低版本会在注册链路才失败，这里提前暴露
MIN_NODE_MAJOR = 18

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _looks_like_key(value: str) -> bool:
    value = (value or "").strip()
    return value not in PLACEHOLDER_KEYS and value.startswith("sk-") and len(value) >= 20


def _node_runtime() -> dict:
    """node 可用性检查（2026-11-06 审核修复：查版本不只查存在）。"""
    if shutil.which("node") is None:
        return {"node_available": False, "node_version": None}
    try:
        out = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=5)
        m = re.search(r"v(\d+)", out.stdout or "")
        major = int(m.group(1)) if m else None
    except (OSError, subprocess.SubprocessError):
        major = None
    return {
        "node_available": major is None or major >= MIN_NODE_MAJOR,
        "node_version": f"v{major}" if major is not None else "unknown",
        "node_version_ok": major is not None and major >= MIN_NODE_MAJOR,
    }


def _in_dsh() -> bool:
    """dsh 环境标志：dsh 的 bash 工具会注入 DSH_SHELL=1。"""
    return os.environ.get("DSH_SHELL") == "1"


def check_api_key_config():
    if _in_dsh():
        # dsh：优先 DSH_DKNOWC_API_KEY（与 MCP Bearer 同源）；缺失时 resolve_api_key 兜底
        # （环境变量 → 专用配置文件）。配置文件读取不受 dsh 环境清理影响，
        # 注册后本会话脚本立即可用。无 Key 仅暂停检索，不阻断纯生成/计算类任务。
        api_key = os.environ.get("DSH_DKNOWC_API_KEY", "").strip()
        source = "environment"
        if not _looks_like_key(api_key):
            try:
                from api_key import resolve_api_key as _rk
                api_key2, source2 = _rk()
                if _looks_like_key(api_key2):
                    api_key, source = api_key2, source2
            except ImportError:
                pass
        if _looks_like_key(api_key):
            return {"api_key_configured": True, "api_key_source": source, "api_key_hint": None}
        return {"api_key_configured": False, "api_key_source": None,
                "api_key_hint": f"未检测到可用的 {API_KEY_ENV}（环境变量与专用配置文件均未找到）。运行注册脚本开通后 Key 自动写入 ~/.config/dknowc/api_key，本会话立即可用。"}


    # 环境变量优先，缺失时从专用配置文件读取（不涉及 shell 配置文件）
    api_key = ""
    source = ""
    try:
        from api_key import resolve_api_key
        api_key, source = resolve_api_key()
    except ImportError:
        api_key = os.environ.get(API_KEY_ENV, "").strip()
        source = "environment" if api_key else ""
    base = {
        "key_validated": False,
        "key_validation_error": None,
        "key_validation_ms": None,
        "key_validation_note": "默认做一次轻量检索校验；--no-verify-key 可跳过。Key 失效时按开通引导重新获取。",
    }
    if _looks_like_key(api_key):
        return {
            **base,
            "api_key_configured": True,
            "api_key_check": "format + 轻量真实检索校验（policies/filter，limit=1，8 秒超时）",
            "api_key_env": API_KEY_ENV,
            "api_key_source": source or "environment",
            "api_key_hint": None,
            "search_ready": True,
            "search_note": None,
        }

    return {
        **base,
        "api_key_configured": False,
        "api_key_check": "format-only（未配置 Key，未发起真实校验）",
        "api_key_env": API_KEY_ENV,
        "api_key_source": None,
        "api_key_hint": f"本 Skill 需要通过 {API_KEY_ENV} 连接深知可信智能服务以获取可信内容。当前未检测到可用 Key，请先注册或登录深知智能 MaaS 账号并获取 API Key。",
        "search_ready": False,
        "search_note": f"当前缺少 {API_KEY_ENV}，暂时不能查询税收政策、优惠条件、申报期限和可信溯源内容。",
    }


def _verify_key() -> tuple:
    """轻量真实校验：最多等 8 秒，避免网络黑洞把会话启动拖到 60 秒。"""
    try:
        from tax_client import filter_policies
        filter_policies("中华人民共和国个人所得税法", limit=1, timeout=8)
        return True, None, None
    except Exception as exc:  # noqa: BLE001
        status = getattr(exc, "status_code", None)
        body = getattr(exc, "body", None)
        code = body.get("code") if isinstance(body, dict) else None
        if status in (401, 403) or code in (401, 403):
            return False, f"Key 校验失败（鉴权 {status or code}）", status or code
        return False, f"Key 校验请求未完成：{str(exc)[:160]}", status


def apply_key_validation(status: dict, blocking_issues: list) -> tuple:
    """执行轻量校验并落到状态：401/403 阻断；网络/5xx 降级放行。"""
    if not status.get("api_key_configured") or "--no-verify-key" in sys.argv[1:]:
        return status, blocking_issues
    started = time.perf_counter()
    validated, error, status_code = _verify_key()
    status["key_validation_ms"] = int((time.perf_counter() - started) * 1000)
    status["key_validated"] = validated
    status["key_validation_error"] = error
    if not validated:
        if status_code in (401, 403):
            status["search_ready"] = False
            status["search_note"] = "当前 Key 未通过校验，已停止检索；请按开通引导重新获取。"
            blocking_issues.append("api_key_invalid")
        else:
            status["search_note"] = (
                f"{error}；已降级放行，首次检索可能失败，联网后请重新运行 initialize.py。"
            )
    return status, blocking_issues


def main():
    status = check_api_key_config()
    blocking_issues = []
    if not status["api_key_configured"]:
        blocking_issues.append("api_key_missing")

    # 默认做一次轻量联网校验；--no-verify-key 可跳过（离线/快速检查时用）。
    status, blocking_issues = apply_key_validation(status, blocking_issues)

    # node 运行时只影响注册链路（register_key.mjs，需 18+），检索本身用 python3 即可，不作为阻断项。
    node = _node_runtime()
    # 注册脚本存在性检查（2026-11-06 发布收口要求）：打包缺文件时提前暴露，而不是等用户开通才失败。
    register_script = Path(__file__).resolve().parent / "register_key.mjs"
    register_script_available = register_script.is_file()

    print(json.dumps({
        **status,
        "python_executable": sys.executable,
        "node_available": node["node_available"],
        "node_version": node["node_version"],
        "node_version_ok": node.get("node_version_ok", False),
        "register_script_available": register_script_available,
        "register_ready": bool(node["node_available"] and register_script_available),
        "blocking_issues": blocking_issues,
        "ready": not blocking_issues,
        # guide_message：需要检索但 Key 未配置时给用户的引导话术（S1 三段式：价值 / 开通方式 / 退路+样例钩子）。
        # Agent 在检索方向确认后向用户转述本话术（可结合任务补充上下文），要素不得删改。
        "guide_message": None if (
            status["api_key_configured"] and "api_key_invalid" not in blocking_issues
        ) else (
            "这个问题涉及税收政策和具体标准——税率、扣除标准、优惠条件按年度调整，凭印象答容易拿旧口径当现行政策，直接影响申报和缴税。"
            "开通权威检索后，每条结论都带政策原文出处、文号与日期，可点开核验，还会附一份可点击的溯源报告。\n"
            "开通是免费的：注册即赠送 10 万积分，完成实名认证再送 10 万积分。"
            "我会用你的手机号为你注册一个检索账号，并在本机保存一份访问凭证（只存本机，不上传、不外传）；"
            "你只需收一次注册验证码并告诉我——约 10 秒，不用自己填注册表。手机号仅用于本次注册验证，不会有营销骚扰。\n"
            "也可以先不开通：我先基于已有知识给你一版初步回答，涉及税率、扣除标准、优惠期限的地方逐条标注\"依据待核验\"，"
            "并说明未联网检索、口径可能过期。想先看看开通后检索结果和溯源报告长什么样，我可以发你示例看看。"
        ),
        # env_message：注册所需运行环境缺失时给用户的统一话术——不暴露组件名（node 对用户无意义）；
        # 就绪时不输出任何环境话题。完整场景话术见 reference/onboarding_scripts.md S6。
        "env_message": (
            "检测到本机开通检索还差一个小程序环境（约 1 分钟，只装一次），我现在装好可以吗？"
            if not node["node_available"] else None
        ),
        "maas_platform_url": MAAS_PLATFORM_URL,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
