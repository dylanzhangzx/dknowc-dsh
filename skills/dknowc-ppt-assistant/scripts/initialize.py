#!/usr/bin/env python3
"""深知可信PPT初始化与环境检查。

Public 版统一只从环境变量 DKNOWC_API_KEY 读取 API Key。

职责划分：
- 本脚本只报告环境状态，不自行决定是否阻断任务。
- `ready` 只表示基础运行环境（python3、requests）就绪。
- `search_ready` 表示可调用深知可信检索（API Key 已配置且 requests 可用）。
- `pptx_ready` 表示可直接执行 SVG→PPTX 编译导出（python-pptx + XlsxWriter 可用）。
  依赖缺失时可用 `uv run --with python-pptx --with XlsxWriter python3 ...` 隔离提供，
  此时素材检索与 SVG 创作不受影响。
"""

import argparse
import json
import os
import platform
import shutil

from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
API_KEY_ENV = "DKNOWC_API_KEY"
ENV_STATE_PATH = SKILL_ROOT / "config" / "environment_state.json"

PLACEHOLDER_KEYS = {
    "",
    "your_api_key_here",
    "你的深知可信搜索 API Key",
    "你的深知搜索 API Key",
}


def _module_available(module_name):
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


def _looks_like_key(value: str) -> bool:
    value = (value or "").strip()
    return value not in PLACEHOLDER_KEYS


def _in_dsh() -> bool:
    """dsh 环境标志：dsh 的 bash 工具会注入 DSH_SHELL=1。

    dsh 场景下，脚本子进程无法隐式继承 DKNOWC_API_KEY（dsh 安全机制会清理
    名字含 KEY 的环境变量），但 dsh 插件会通过 shell-env 显式通道把该 Key
    注入为 DSH_DKNOWC_API_KEY。检索子能力走 MCP 转接，无 Key 时仅暂停
    检索，不阻断纯生成任务。
    """
    return os.environ.get("DSH_SHELL") == "1"


def check_api_key_config():
    if _in_dsh():
        api_key = os.environ.get("DSH_DKNOWC_API_KEY", "").strip()
        if _looks_like_key(api_key):
            return {
                "api_key_configured": True,
                "api_key_env": API_KEY_ENV,
                "api_key_source": "environment",
                "api_key_hint": None,
            }
        return {
            "api_key_configured": False,
            "api_key_env": API_KEY_ENV,
            "api_key_source": None,
            "api_key_hint": f"未检测到可用的 {API_KEY_ENV}（dsh 主进程环境变量未配置或为空）。仅检索任务受影响，不涉及检索的生成任务可继续。",
        }

    api_key = os.environ.get(API_KEY_ENV, "").strip()
    if _looks_like_key(api_key):
        return {
            "api_key_configured": True,
            "api_key_env": API_KEY_ENV,
            "api_key_source": "environment",
            "api_key_hint": None,
        }
    return {
        "api_key_configured": False,
        "api_key_env": API_KEY_ENV,
        "api_key_source": None,
        "api_key_hint": f"本 Skill 的素材检索需要通过环境变量 {API_KEY_ENV} 连接深知可信智能服务。当前未检测到可用 Key，请先注册或登录深知可信智能 MaaS 账号获取 API Key，再注入该环境变量。",
    }


def load_environment_state():
    if not ENV_STATE_PATH.exists():
        return {}
    try:
        with ENV_STATE_PATH.open("r", encoding="utf-8") as state_file:
            state = json.load(state_file)
        return state if isinstance(state, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_environment_state(state):
    ENV_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ENV_STATE_PATH.open("w", encoding="utf-8") as state_file:
        json.dump(state, state_file, ensure_ascii=False, indent=2)


def check_environment():
    state = load_environment_state()
    python3_available = shutil.which("python3") is not None
    requests_available = _module_available("requests")
    python_pptx_available = _module_available("pptx")
    xlsxwriter_available = _module_available("XlsxWriter")
    config_status = check_api_key_config()

    blocking_issues = []
    if not python3_available:
        blocking_issues.append("python3_missing")
    if not requests_available:
        blocking_issues.append("requests_missing")

    pptx_blocking_issues = []
    if not python_pptx_available:
        pptx_blocking_issues.append("python_pptx_missing")
    if not xlsxwriter_available:
        pptx_blocking_issues.append("xlsxwriter_missing")

    search_blocking_issues = []
    if not config_status["api_key_configured"]:
        search_blocking_issues.append("api_key_missing")

    return {
        "python": platform.python_version(),
        "python3_available": python3_available,
        "requests": requests_available,
        "python_pptx": python_pptx_available,
        "xlsxwriter": xlsxwriter_available,
        "api_key_configured": config_status["api_key_configured"],
        "api_key_env": API_KEY_ENV,
        "api_key_source": config_status["api_key_source"],
        "api_key_hint": config_status["api_key_hint"],
        "search_ready": config_status["api_key_configured"] and requests_available,
        "search_blocking_issues": search_blocking_issues,
        # PPT 编译依赖缺失不阻断其他环节：可用 uv run --with 隔离提供。
        "pptx_ready": python3_available and python_pptx_available and xlsxwriter_available,
        "pptx_blocking_issues": pptx_blocking_issues,
        "pptx_hint": (
            "SVG 编译导出可用 `uv run --with python-pptx --with XlsxWriter python3 ...` 隔离提供依赖；"
            if pptx_blocking_issues else None
        ),
        "blocking_issues": blocking_issues,
        "ready": not blocking_issues,
        "maas_platform_url": "https://platform.dknowc.cn/",
        "environment_state": {
            "dependency_install_declined": bool(state.get("dependency_install_declined")),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="深知可信PPT初始化与环境检查")
    parser.add_argument("--decline-dependency-install", action="store_true", help="记录用户已拒绝依赖安装提示，后续不再反复询问")
    parser.add_argument("--reset-environment-prompts", action="store_true", help="清除依赖安装提示的拒绝记录")
    args = parser.parse_args()

    state = load_environment_state()
    if args.reset_environment_prompts:
        state.pop("dependency_install_declined", None)
    if args.decline_dependency_install:
        state["dependency_install_declined"] = True
    if args.reset_environment_prompts or args.decline_dependency_install:
        save_environment_state(state)

    result = check_environment()
    result["environment_state_path"] = "config/environment_state.json"
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
