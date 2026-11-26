#!/usr/bin/env python3
"""深知法律助手 public 版初始化检查。

API Key 读取：优先进程环境变量 DKNOWC_API_KEY，缺失时从本机专用配置文件
~/.config/dknowc/api_key 读取（不读取、不改写任何 shell 配置文件）
（宿主进程早于 key 写入启动、或宿主安全更新后不再加载 shell 导出变量时不误报缺失）。
注册脚本 register_key.mjs 注册成功后自动把 Key 写入专用配置文件（不写入、不改写任何 shell 配置文件），
本检查直读该文件，无需重启宿主。不读取、不写入本地 config.ini 中的 Key。
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


API_KEY_ENV = "DKNOWC_API_KEY"
MAAS_PLATFORM_URL = "https://platform.dknowc.cn/auth/#/login"
PLACEHOLDER_KEYS = {"", "your_api_key_here", "你的深知法律助手 API Key", "你的深知可信搜索 API Key", "你的深知搜索 API Key"}

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _looks_like_key(value: str) -> bool:
    value = (value or "").strip()
    return value not in PLACEHOLDER_KEYS and value.startswith("sk-")


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
    key_mode = None
    try:
        from api_key import resolve_api_key, key_file_mode
        api_key, source = resolve_api_key()
        key_mode = key_file_mode()
    except ImportError:
        api_key = os.environ.get(API_KEY_ENV, "").strip()
        source = "environment" if api_key else ""
    permission_warning = None
    if source != "environment" and key_mode is not None and (key_mode & 0o077):
        permission_warning = (
            f"Key 文件权限过宽（{oct(key_mode)}）；建议执行 chmod 600 "
            f"{api_key_file_path_display()}，避免同机其他用户读取。"
        )
    base = {
        "api_key_env": API_KEY_ENV,
        "api_key_source": source or None,
        "key_file_mode": oct(key_mode) if key_mode is not None else None,
        "key_file_permission_warning": permission_warning,
        "key_validated": False,
        "key_validation_error": None,
        "key_validation_note": "默认做一次轻量检索校验；--no-verify-key 可跳过。Key 失效时按开通引导重新获取。",
    }
    if _looks_like_key(api_key):
        return {
            **base,
            "api_key_configured": True,
            "api_key_hint": None,
            "search_ready": True,
            "search_note": None,
        }

    return {
        **base,
        "api_key_configured": False,
        "api_key_source": None,
        "api_key_hint": f"本 Skill 需要通过 {API_KEY_ENV} 连接深知可信智能服务以获取可信内容。当前未检测到可用 Key，请先注册或登录深知智能 MaaS 账号并获取 API Key。",
        "search_ready": False,
        "search_note": f"当前缺少 {API_KEY_ENV}，暂时不能查询法律法规、司法解释、政策依据和可信溯源内容。",
    }


def api_key_file_path_display() -> str:
    try:
        from api_key import api_key_file_path
        return str(api_key_file_path())
    except Exception:
        return "~/.config/dknowc/api_key"


def _node_status() -> dict:
    node = shutil.which("node")
    if not node:
        return {"node_available": False, "node_version": None, "node_ok": False}
    try:
        out = subprocess.check_output([node, "--version"], text=True, timeout=5).strip()
        major = int(out.lstrip("v").split(".")[0])
        return {"node_available": True, "node_version": out, "node_ok": major >= 18}
    except Exception:
        return {"node_available": True, "node_version": None, "node_ok": False}


def _verify_key() -> tuple:
    try:
        from legal_client import filter_policies
        # 初始化校验必须“轻量”：最多等 8 秒，避免网络黑洞把每次会话启动拖到 60 秒。
        filter_policies("中华人民共和国劳动合同法", limit=1, timeout=8)
        return True, None, None
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        if status in (401, 403):
            return False, f"Key 校验失败（HTTP {status}）", status
        return False, f"Key 校验请求未完成：{str(exc)[:160]}", status


def main():
    status = check_api_key_config()
    blocking_issues = []
    if not status["api_key_configured"]:
        blocking_issues.append("api_key_missing")

    # 默认做一次轻量联网校验；--no-verify-key 可跳过（离线/快速检查时用）。
    if status["api_key_configured"] and "--no-verify-key" not in sys.argv[1:]:
        validated, error, status_code = _verify_key()
        status["key_validated"] = validated
        status["key_validation_error"] = error
        if not validated:
            if status_code in (401, 403):
                status["search_ready"] = False
                blocking_issues.append("api_key_invalid")
            else:
                status["search_note"] = f"{error}；首次检索可能失败，联网后请重新运行 initialize.py。"

    # node 运行时只影响注册链路（register_key.mjs），检索本身用 python3 即可，不作为阻断项。
    node_status = _node_status()
    register_script_present = (Path(__file__).resolve().parent / "register_key.mjs").is_file()

    print(json.dumps({
        **status,
        "python_executable": sys.executable,
        "node_available": node_status["node_available"],
        "node_version": node_status["node_version"],
        "node_ok": node_status["node_ok"],
        "register_script_present": register_script_present,
        "registration_ready": node_status["node_ok"] and register_script_present,
        "blocking_issues": blocking_issues,
        "ready": not blocking_issues,
        # guide_message：需要检索但 Key 未配置/未通过校验时给用户的引导话术（S1 三段式：价值 / 开通方式 / 退路+样例钩子）。
        # Agent 在检索方向确认后向用户转述本话术（可结合任务补充上下文），要素不得删改。
        "guide_message": None if status["api_key_configured"] and "api_key_invalid" not in blocking_issues else (
            "这个问题涉及法律条文和具体规则——普通搜索结果来源杂、无法核验，凭印象答法条和条号，错了会直接影响判断和决策。"
            "开通权威检索后，每条法律、条文都带原文出处、可点开核验，还会附一份可点击的溯源报告。\n"
            "开通是免费的：注册即赠送 10 万积分，完成实名认证再送 10 万积分。"
            "只需手机号收一次验证码——约 10 秒，不用自己填注册表，剩下的我来办；手机号仅用于本次验证，不会有营销骚扰。\n"
            "也可以先不开通：我先基于已有知识给你一版初步回答，涉及政策口径、数字的地方逐条标注\"依据待核验\"，"
            "并说明未联网检索、口径可能过期。想先看看开通后检索结果和溯源报告长什么样，我可以发你示例看看。"
        ),
        # env_message：注册所需运行环境缺失时给用户的统一话术——不暴露组件名（node 对用户无意义）；
        # 就绪时不输出任何环境话题。完整场景话术见 reference/onboarding_scripts.md S6。
        "env_message": (
            "检测到本机开通检索还差一个小程序环境（约 1 分钟，只装一次），我现在装好可以吗？"
            if not node_status["node_ok"] or not register_script_present else None
        ),
        "maas_platform_url": MAAS_PLATFORM_URL,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
