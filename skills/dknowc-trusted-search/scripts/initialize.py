#!/usr/bin/env python3
"""深知可信搜索 SkillHub / WorkBuddy public 版初始化检查。

API Key 读取：优先进程环境变量 DKNOWC_API_KEY，缺失时从 ~/.zshrc 兜底解析
（宿主进程早于 key 写入启动、或宿主安全更新后不再加载 zshrc 导出变量时不误报缺失）。
注册脚本 register_key.mjs 注册成功后会自动把 Key 写入 ~/.zshrc 标记块，本检查直读该文件，
无需重启宿主。不读取、不写入本地 config.ini 中的 Key。
"""

import json
import os
import shutil
import sys
from pathlib import Path


API_KEY_ENV = "DKNOWC_API_KEY"
MAAS_PLATFORM_URL = "https://platform.dknowc.cn/auth/#/login"
PLACEHOLDER_KEYS = {"", "your_api_key_here", "你的深知可信搜索 API Key", "你的深知搜索 API Key"}

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _looks_like_key(value: str) -> bool:
    value = (value or "").strip()
    return value not in PLACEHOLDER_KEYS and value.startswith("sk-")


def _in_dsh() -> bool:
    """dsh 环境标志：dsh 的 bash 工具会注入 DSH_SHELL=1。"""
    return os.environ.get("DSH_SHELL") == "1"


def check_api_key_config():
    if _in_dsh():
        # dsh 场景：优先插件经 shell-env 注入的 DSH_DKNOWC_API_KEY（与 MCP Bearer 同源）；
        # 缺失时 ~/.zshrc 兜底（注册成功自动持久化后、dsh 重启前的窗口期不误报缺失）。
        api_key = os.environ.get("DSH_DKNOWC_API_KEY", "").strip()
        source = "environment"
        if not _looks_like_key(api_key):
            try:
                from api_key import resolve_api_key
                api_key2, source2 = resolve_api_key()
                if _looks_like_key(api_key2):
                    api_key, source = api_key2, source2
            except ImportError:
                pass
        if _looks_like_key(api_key):
            note = None
            if source == "zshrc":
                note = ("dsh 场景：Key 已持久化在 ~/.zshrc。当前 dsh 主进程环境变量尚未加载该 Key——"
                        "本会话的 MCP Bearer 认证在启动时已冻结，请经 scripts/mcp_direct.py 直调完成当前任务"
                        "（脚本会自动从 ~/.zshrc 解析 Key）；重启 dsh 或新开会话后自动恢复正常 MCP 转接。")
            return {
                "api_key_configured": True,
                "api_key_env": API_KEY_ENV,
                "api_key_source": source,
                "api_key_hint": None,
                "search_ready": True,
                "search_note": note,
            }
        return {
            "api_key_configured": False,
            "api_key_env": API_KEY_ENV,
            "api_key_source": None,
            "api_key_hint": f"未检测到可用的 {API_KEY_ENV}（dsh 主进程环境变量与 ~/.zshrc 中均未找到）。需要先将有效的 API Key 配置到启动 dsh 的环境变量 {API_KEY_ENV}（如 ~/.zshrc），再重启 dsh 或新建会话。",
            "search_ready": False,
            "search_note": f"当前缺少 {API_KEY_ENV}，暂时不能查询政策法规、办事流程、标准依据和可信溯源内容。",
        }

    # 环境变量优先，缺失时从 ~/.zshrc 兜底解析
    api_key = ""
    source = ""
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
            "api_key_source": source or "environment",
            "api_key_hint": None,
            "search_ready": True,
            "search_note": None,
        }

    return {
        "api_key_configured": False,
        "api_key_env": API_KEY_ENV,
        "api_key_source": None,
        "api_key_hint": f"本 Skill 需要通过 {API_KEY_ENV} 连接深知可信智能服务以获取可信内容。当前未检测到可用 Key，请先注册或登录深知智能 MaaS 账号并获取 API Key。",
        "search_ready": False,
        "search_note": f"当前缺少 {API_KEY_ENV}，暂时不能查询政策法规、办事流程、标准依据和可信溯源内容。",
    }


def main():
    status = check_api_key_config()
    blocking_issues = []
    if not status["api_key_configured"]:
        blocking_issues.append("api_key_missing")

    # node 运行时只影响注册链路（register_key.mjs），检索本身用 python3 即可，不作为阻断项。
    node_available = shutil.which("node") is not None

    print(json.dumps({
        **status,
        "python_executable": sys.executable,
        "node_available": node_available,
        "blocking_issues": blocking_issues,
        "ready": not blocking_issues,
        # guide_message：需要检索但 Key 未配置时给用户的引导话术（S1 三段式：价值 / 开通方式 / 退路+样例钩子）。
        # Agent 在检索方向确认后向用户转述本话术（可结合任务补充上下文），要素不得删改。
        "guide_message": None if status["api_key_configured"] else (
            "这个问题涉及政策口径和具体数字——普通搜索结果来源杂、无法核验，凭印象答政策名和数字，口径错了会影响你的判断和决策。"
            "开通权威检索后，每条政策、数据都带原文出处、可点开核验，还会附一份可点击的溯源报告。\n"
            "开通是免费的：自带 300 次权威检索额度，完成实名认证还能再领 100 元体验金。"
            "只需手机号收一次验证码——两步、约 10 秒，不用去网站，剩下的我来办；手机号仅用于本次验证，不会有营销骚扰。\n"
            "也可以先不开通：我先基于已有知识给你一版初步回答，涉及政策口径、数字的地方逐条标注\"依据待核验\"，"
            "并说明未联网检索、口径可能过期。想先看看开通后检索结果和溯源报告长什么样，我可以发你示例看看。"
        ),
        # env_message：注册所需运行环境缺失时给用户的统一话术——不暴露组件名（node 对用户无意义）；
        # 就绪时不输出任何环境话题。完整场景话术见 reference/onboarding_scripts.md S6。
        "env_message": (
            "检测到本机开通检索还差一个小程序环境（约 1 分钟，只装一次），我现在装好可以吗？"
            if not node_available else None
        ),
        "maas_platform_url": MAAS_PLATFORM_URL,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
