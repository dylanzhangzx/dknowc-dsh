#!/usr/bin/env python3
"""深知可信咨询 SkillHub public 版初始化检查。

API Key 解析：优先进程环境变量 DKNOWC_API_KEY，缺失时从 ~/.zshrc 兜底解析——
宿主应用（WorkBuddy 等）的会话进程可能读不到用户 shell 环境变量（启动早于
key 写入，或宿主不再加载 ~/.zshrc 导出值），盘上已有 key 时不应误报缺失。
不读取、不写入本地 config.ini 中的 Key。
"""

import json
import os


API_KEY_ENV = "DKNOWC_API_KEY"
PLACEHOLDER_KEYS = {"", "your_api_key_here", "你的深知可信统一接口 API Key", "你的深知可信咨询 API Key"}


def _looks_like_key(value: str) -> bool:
    value = (value or "").strip()
    return value not in PLACEHOLDER_KEYS


def _in_dsh() -> bool:
    """dsh 环境标志：dsh 的 bash 工具会注入 DSH_SHELL=1。"""
    return os.environ.get("DSH_SHELL") == "1"


def check_api_key_config():
    if _in_dsh():
        # dsh 场景：优先插件经 shell-env 注入的 DSH_DKNOWC_API_KEY（与 MCP Bearer 同源）；
        # 缺失时本地环境变量 / ~/.zshrc 兜底（注册成功自动持久化后、dsh 重启前的窗口期）。
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
            note = "dsh 场景：接口经深知可信工作台 MCP 转接（credible_chat），API Key 由 dsh 主进程环境变量 DKNOWC_API_KEY 提供（经 shell-env 显式注入为 DSH_DKNOWC_API_KEY）。"
            if source == "zshrc":
                note = ("dsh 场景：Key 已持久化在 ~/.zshrc（api_key_source=zshrc）。当前 dsh 主进程环境变量尚未加载该 Key——"
                        "本会话的 MCP Bearer 认证在启动时已冻结，请经 scripts/mcp_direct.py 直调完成当前任务"
                        "（脚本会自动从 ~/.zshrc 解析 Key）；重启 dsh 或新开会话后自动恢复正常 MCP 转接。")
            return {
                "api_key_configured": True,
                "api_key_env": f"{API_KEY_ENV} (DSH_DKNOWC_API_KEY)" if source == "environment" else API_KEY_ENV,
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
            "search_note": f"当前未检测到可用的 {API_KEY_ENV}，暂时无法获取深知可信内容。",
        }

    # 环境变量优先，缺失时从 ~/.zshrc 兜底解析（与深知公文写作 api_key.py 同源）
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
            "search_ready": True,
            "search_note": None,
        }

    return {
        "api_key_configured": False,
        "api_key_env": API_KEY_ENV,
        "api_key_source": None,
            "api_key_hint": f"本 Skill 需要通过环境变量 {API_KEY_ENV} 调用深知可信统一接口获取可信内容，当前环境变量与 ~/.zshrc 中均未找到有效 Key。请先注册或登录深知可信智能 MaaS 账号获取 API Key，再注入该环境变量。",
        "search_ready": False,
        "search_note": f"当前未检测到可用的 {API_KEY_ENV}，暂时无法获取深知可信内容。",
    }


def main():
    status = check_api_key_config()
    blocking_issues = []
    if not status["api_key_configured"]:
        blocking_issues.append("api_key_missing")

    # guide_message：需要可信咨询但 Key 未配置时给用户的引导话术（S1 三段式：价值 / 权益+开通方式 / 退路+样例钩子）。
    # Agent 优先原样转述本话术；完整话术库见 reference/onboarding_scripts.md。
    guide_message = None
    if not status["api_key_configured"]:
        guide_message = (
            "这个问题涉及具体的办事条件和金额口径，凭记忆回答容易过时或者记错地区差异，"
            "答错了会影响办事和决策。开通可信咨询后，答案基于权威文件库原文，"
            "条件、金额、办理路径都带出处、可点开核验。\n"
            "开通是免费的：自带 300 次可信咨询额度，完成实名认证还能再领 100 元体验金。"
            "只需手机号收一次验证码——两步、约 10 秒，不用去网站，剩下的我来办；"
            "手机号仅用于本次验证，不会有营销骚扰。\n"
            "也可以先不开通：我按已有知识先答，并明确标注“未联网核验、口径可能过期”。"
            "想先看看开通后生成的核验报告长什么样，我可以发你一份示例看看。"
        )

    print(json.dumps({
        **status,
        "blocking_issues": blocking_issues,
        "ready": not blocking_issues,
        "guide_message": guide_message,
        "maas_platform_url": "https://platform.dknowc.cn/auth/#/login",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
