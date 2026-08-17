#!/usr/bin/env python3
"""深知可信咨询 SkillHub public 版初始化检查。

Public 版统一只从环境变量 DKNOWC_API_KEY 读取 API Key，不读取、不写入本地 config.ini 中的 Key。
"""

import json
import os


API_KEY_ENV = "DKNOWC_API_KEY"
PLACEHOLDER_KEYS = {"", "your_api_key_here", "你的深知可信统一接口 API Key", "你的深知可信咨询 API Key"}


def _looks_like_key(value: str) -> bool:
    value = (value or "").strip()
    return value not in PLACEHOLDER_KEYS


def _in_dsh() -> bool:
    """dsh 环境标志：dsh 的 bash 工具会注入 DSH_SHELL=1。

    dsh 场景下，脚本子进程无法隐式继承 DKNOWC_API_KEY（dsh 安全机制会清理
    名字含 KEY 的环境变量），但 dsh 插件会通过 shell-env 显式通道把该 Key
    注入为 DSH_DKNOWC_API_KEY。因此检查 DSH_DKNOWC_API_KEY 即可真实判断
    "dsh 主进程环境变量是否已配置 DKNOWC_API_KEY"。
    """
    return os.environ.get("DSH_SHELL") == "1"


def check_api_key_config():
    if _in_dsh():
        # dsh 场景：读取插件注入的 DSH_DKNOWC_API_KEY（来源为 dsh 主进程的 DKNOWC_API_KEY）
        api_key = os.environ.get("DSH_DKNOWC_API_KEY", "").strip()
        if _looks_like_key(api_key):
            return {
                "api_key_configured": True,
                "api_key_env": "DKNOWC_API_KEY (DSH_DKNOWC_API_KEY)",
                "api_key_source": "environment",
                "api_key_hint": None,
                "search_ready": True,
                "search_note": "dsh 场景：接口经深知可信工作台 MCP 转接（credible_chat），API Key 由 dsh 主进程环境变量 DKNOWC_API_KEY 提供（经 shell-env 显式注入为 DSH_DKNOWC_API_KEY）。",
            }
        return {
            "api_key_configured": False,
            "api_key_env": API_KEY_ENV,
            "api_key_source": None,
            "api_key_hint": f"未检测到可用的 {API_KEY_ENV}（dsh 主进程环境变量未配置或为空）。需要先将有效的 API Key 配置到启动 dsh 的环境变量 {API_KEY_ENV}（如 ~/.zshrc），再重启 dsh 或新建会话。",
            "search_ready": False,
            "search_note": f"当前缺少 {API_KEY_ENV}，暂时无法获取深知可信内容。",
        }

    api_key = os.environ.get(API_KEY_ENV, "").strip()
    if _looks_like_key(api_key):
        return {
            "api_key_configured": True,
            "api_key_env": API_KEY_ENV,
            "api_key_source": "environment",
            "api_key_hint": None,
            "search_ready": True,
            "search_note": None,
        }

    return {
        "api_key_configured": False,
        "api_key_env": API_KEY_ENV,
        "api_key_source": None,
            "api_key_hint": f"本 Skill 需要通过环境变量 {API_KEY_ENV} 调用深知可信统一接口获取可信内容，当前还未配置。请先注册或登录深知可信智能 MaaS 账号获取 API Key，再注入该环境变量。",
        "search_ready": False,
        "search_note": f"当前未检测到可用的 {API_KEY_ENV}，暂时无法获取深知可信内容。",
    }


def main():
    status = check_api_key_config()
    blocking_issues = []
    if not status["api_key_configured"]:
        blocking_issues.append("api_key_missing")

    print(json.dumps({
        **status,
        "blocking_issues": blocking_issues,
        "ready": not blocking_issues,
        "maas_platform_url": "https://platform.dknowc.cn/",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
