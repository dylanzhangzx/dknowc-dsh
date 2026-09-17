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
import sys
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
    """dsh 环境标志：dsh 的 bash 工具会注入 DSH_SHELL=1。"""
    return os.environ.get("DSH_SHELL") == "1"


def check_api_key_config():
    if _in_dsh():
        # dsh 场景：优先插件经 shell-env 注入的 DSH_DKNOWC_API_KEY（与 MCP Bearer 同源）；
        # 缺失时 ~/.zshrc 兜底。无 Key 仅暂停检索，不阻断纯生成（材料/免检索模式）。
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
            return {"api_key_configured": True, "api_key_env": API_KEY_ENV, "api_key_source": source, "api_key_hint": None}
        return {"api_key_configured": False, "api_key_env": API_KEY_ENV, "api_key_source": None,
                "api_key_hint": f"未检测到可用的 {API_KEY_ENV}（dsh 主进程环境变量与 ~/.zshrc 中均未找到）。需要先将有效的 API Key 配置到启动 dsh 的环境变量 {API_KEY_ENV}（如 ~/.zshrc），再重启 dsh 或新建会话。仅检索任务受影响，不涉及检索的生成任务可继续。"}

    # 环境变量优先，缺失时从 ~/.zshrc 兜底解析（宿主进程早于 key 写入启动、
    # 或宿主不再加载 ~/.zshrc 导出变量时不误报缺失，与公文写作同源方案）
    try:
        from api_key import resolve_api_key
        api_key, source = resolve_api_key()
    except ImportError:
        api_key = os.environ.get(API_KEY_ENV, "").strip()
        source = "environment" if api_key else ""
    if _looks_like_key(api_key):
        return {
            "api_key_configured": True,
            "api_key_env": API_KEY_ENV,
            "api_key_source": source,
            "api_key_hint": None,
        }
    return {
        "api_key_configured": False,
        "api_key_env": API_KEY_ENV,
        "api_key_source": None,
        "api_key_hint": f"本 Skill 的素材检索需要通过环境变量 {API_KEY_ENV}（或 ~/.zshrc 持久化）连接深知可信智能服务。当前两处均未检测到可用 Key，请先注册或登录深知可信智能 MaaS 账号获取 API Key。",
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

    # guide_message：需要检索但 Key 未配置时给用户的引导话术（S1 三段式：价值 / 权益+开通方式 / 退路+样例钩子）。
    # Agent 结合当前任务语境转述（完整口径见 references/onboarding_scripts.md）。
    guide_message = None if config_status["api_key_configured"] else (
        "这份汇报 PPT 需要引用政策原文和权威数据，凭印象写政策名和数字，汇报场合被当场指出来最影响效果。"
        "开通权威检索后，每条政策、数据都带原文出处、可点开核验，权威数据还能直接做成可编辑的原生图表。\n"
        "开通是免费的：自带 300 次权威检索额度，完成实名认证还能再领 100 元体验金。"
        "只需手机号收一次验证码——两步、约 10 秒，不用去网站，剩下的我来办；手机号仅用于本次验证，不会有营销骚扰。\n"
        "也可以先不开通：我基于你手头的材料先把 PPT 做出来，政策和数据的位置先标注「数据待核验」。"
        "想先看看开通后自动生成的核验报告长什么样，我可以发你一份示例看看。"
    )
    # env_message：依赖缺失时给用户的统一话术——用「小组件」等通俗说法（requests/python-pptx 等组件名
    # 对用户无理解价值）；就绪时不输出环境话题。多 Python 环境下检测口径以 python_executable 为准。
    missing_basic = [k for k, ok in (("小组件", requests_available),) if not ok]
    missing_compile = 2 - int(python_pptx_available) - int(xlsxwriter_available)
    if blocking_issues or pptx_blocking_issues:
        total = len(missing_basic) + missing_compile
        env_message = (
            f"检测到本机制作环境需要补装 {'一个' if total == 1 else str(total)} 个小组件"
            "（约 10 秒，只装一次），我现在装好可以吗？"
            "（基础小组件影响检索，编译小组件影响最后的 PPT 导出，缺失时我会自动用隔离环境补齐）"
        )
    else:
        env_message = None

    return {
        "python": platform.python_version(),
        "python_executable": sys.executable,
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
        "guide_message": guide_message,
        "env_message": env_message,
        "maas_platform_url": "https://platform.dknowc.cn/auth/#/login",
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
