#!/usr/bin/env python3
"""检查运行环境，并按用户授权保存可选的本地写作偏好。"""

import argparse
import json
import os
import platform
import shutil
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
API_KEY_ENV = "DKNOWC_API_KEY"
PROFILE_PATH = SKILL_ROOT / "config" / "user_profile.json"
ENV_STATE_PATH = SKILL_ROOT / "config" / "environment_state.json"
SCRIPTS_DIR = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


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
    python_docx_available = _module_available("docx")
    requests_available = _module_available("requests")
    config_status = check_api_key_config()
    kb_count = _count_kb_materials()
    pref_count = _count_writing_preferences()
    blocking_issues = []
    if not python3_available:
        blocking_issues.append("python3_missing")
    if not python_docx_available:
        blocking_issues.append("python_docx_missing")
    if not requests_available:
        blocking_issues.append("requests_missing")
    dependency_issues = [
        issue for issue in blocking_issues
        if issue in {"python3_missing", "python_docx_missing", "requests_missing"}
    ]
    # API Key 只在任务需要深知搜索时才是前置条件，不作为基础写作的阻断项。
    # 不涉及搜索的简单通知、改写润色、只生成 Word 等任务可直接使用。
    search_blocking_issues = []
    if not config_status["api_key_configured"]:
        search_blocking_issues.append("api_key_missing")
    return {
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "python3_available": python3_available,
        "python_docx": python_docx_available,
        "requests": requests_available,
        "api_key_configured": config_status["api_key_configured"],
        "api_key_env": API_KEY_ENV,
        "api_key_source": config_status["api_key_source"],
        "api_key_hint": config_status["api_key_hint"],
        "config_issue": None if config_status["api_key_configured"] else "api_key_missing",
        "search_ready": config_status["api_key_configured"] and requests_available,
        "search_blocking_issues": search_blocking_issues,
        "search_note": None if config_status["api_key_configured"] else f"环境变量 {API_KEY_ENV} 中未配置有效 API Key；仅当任务需要深知搜索（查政策依据、数据支撑、案例参考）时才需要配置，不涉及搜索的写作任务可直接使用。",
        # guide_message：需要搜索但 Key 未配置时给用户的引导话术（S1 三段式：价值 / 开通方式 / 退路+样例钩子）。
        # Agent 在搜索方案确认后向用户转述本话术（可结合任务补充上下文），要素不得删改。
        "guide_message": None if config_status["api_key_configured"] else (
            "这份材料需要引用政策原文和权威数据，凭印象写政策名和数字，审稿时最容易被挑出来。"
            "开通权威检索后，每条政策、数据都带原文出处、可点开核验。\n"
            "开通是免费的：自带 300 次权威检索额度，完成实名认证还能再领 100 元体验金。"
            "只需手机号收一次验证码——两步、约 10 秒，不用去网站，剩下的我来办；手机号仅用于本次验证，不会有营销骚扰。\n"
            "也可以先不开通：我基于你手头的材料先写，政策依据的位置先标注'待补'。"
            "想先看看开通后生成的核验报告长什么样，我可以发你一份示例看看。"
        ),
        "font_note": "Word 文档会写入公文常用字体名称；打开端如缺少对应字体，Word/WPS 可能自动替换，需以本机打开后的显示为准。",
        "blocking_issues": blocking_issues,
        "ready": not blocking_issues,
        "search_ready_note": None if config_status["api_key_configured"] else "仅需要搜索的任务需先完成 MaaS 注册获取 API Key 并写入环境变量；无需搜索的任务可先直接写作。",
        "local_memory": {
            "knowledge_base_materials": kb_count,
            "knowledge_base_dir": "knowledge-base/",
            "writing_preferences_count": pref_count,
            "preferences_path": "config/writing_preferences.json",
            "note": "个人素材库与写作偏好仅保存在本机，不随公开包分发；大于 0 时写作任务应先检索素材库并应用偏好。",
        },
        "dependency_install_prompt_needed": bool(dependency_issues) and not state.get("dependency_install_declined"),
        "install_hint": "经用户同意后，可执行 python3 -m pip install python-docx requests" if dependency_issues else None,
        # env_message：组件缺失时给用户的统一话术——不暴露组件名（python-docx/requests 对用户无意义）；
        # 就绪时不输出任何环境话题。多 Python 环境下检测口径以 python_executable 为准。
        "env_message": (
            "检测到本机写作环境需要补装两个小组件（约 10 秒，只装一次），我现在装好可以吗？"
            if dependency_issues else None
        ),
        "maas_platform_url": "https://platform.dknowc.cn/auth/#/login",
        "environment_state": {
            "dependency_install_declined": bool(state.get("dependency_install_declined")),
        },
    }


def _count_kb_materials():
    index_path = SKILL_ROOT / "knowledge-base" / "_index.json"
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return len(data["items"])
    return 0


def _count_writing_preferences():
    pref_path = SKILL_ROOT / "config" / "writing_preferences.json"
    try:
        data = json.loads(pref_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(data, dict):
        return 0
    return sum(len(v) for v in data.values() if isinstance(v, list))


def _module_available(module_name):
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


def _in_dsh() -> bool:
    """dsh 环境标志：dsh 的 bash 工具会注入 DSH_SHELL=1。"""
    return os.environ.get("DSH_SHELL") == "1"


def check_api_key_config():
    if _in_dsh():
        # dsh 场景：优先插件经 shell-env 注入的 DSH_DKNOWC_API_KEY（与 MCP Bearer 同源）；
        # 缺失时 ~/.zshrc 兜底（注册成功自动持久化后、dsh 重启前的窗口期不误报缺失）。
        # 无 Key 仅暂停搜索，不阻断纯写作。
        api_key = os.environ.get("DSH_DKNOWC_API_KEY", "").strip()
        source = "environment"
        if not _valid_api_key(api_key):
            try:
                from api_key import resolve_api_key as _rk
                api_key2, source2 = _rk()
                if _valid_api_key(api_key2):
                    api_key, source = api_key2, source2
            except ImportError:
                pass
        if not _valid_api_key(api_key):
            return {"api_key_configured": False, "api_key_source": None,
                "api_key_hint": f"未检测到可用的 {API_KEY_ENV}（dsh 主进程环境变量与 ~/.zshrc 中均未找到）。需要先将有效的 API Key 配置到启动 dsh 的环境变量 {API_KEY_ENV}（如 ~/.zshrc），再重启 dsh 或新建会话。仅搜索任务受影响，不涉及搜索的写作任务可继续。"}
        return {"api_key_configured": True, "api_key_source": source, "api_key_hint": None}

    # 环境变量优先，缺失时从 ~/.zshrc 兜底解析（宿主进程早于 key 写入启动时不误报缺失）
    try:
        from api_key import resolve_api_key
        api_key, source = resolve_api_key()
    except ImportError:
        api_key = os.environ.get(API_KEY_ENV, "").strip()
        source = "environment" if api_key else ""
    if not _valid_api_key(api_key):
        return {
            "api_key_configured": False,
            "api_key_source": None,
            "api_key_hint": f"环境变量 {API_KEY_ENV} 与 ~/.zshrc 中均未找到有效 API Key，请先通过 MaaS 初始化获取。",
        }
    return {
        "api_key_configured": True,
        "api_key_source": source,
        "api_key_hint": None,
    }


def _valid_api_key(value):
    return bool(value) and value not in {"your_api_key_here", "你的深知搜索 API Key"}


def main():
    parser = argparse.ArgumentParser(description="深知写作助手初始化与环境检查")
    parser.add_argument("--organization", help="常用发文机关；不填写则使用 XX单位")
    parser.add_argument("--doc-prefix", help="常用发文字号前缀；不填写则使用 XX")
    parser.add_argument("--region", help="常用搜索地域；不填写则按任务询问")
    parser.add_argument("--print-unit", help="常用印发单位")
    parser.add_argument("--save", action="store_true", help="经用户授权后，将所填设置仅保存到本机")
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

    if args.save:
        profile = {
            "organization": args.organization or "",
            "doc_prefix": args.doc_prefix or "",
            "region": args.region or "",
            "print_unit": args.print_unit or "",
        }
        PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with PROFILE_PATH.open("w", encoding="utf-8") as profile_file:
            json.dump(profile, profile_file, ensure_ascii=False, indent=2)

    result = check_environment()
    result["profile_saved"] = args.save
    result["profile_path"] = "config/user_profile.json" if args.save else None
    result["environment_state_path"] = "config/environment_state.json"
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
