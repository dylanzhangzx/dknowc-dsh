#!/usr/bin/env python3
"""检查运行环境，并按用户授权保存可选的本地写作偏好。

版本自检（引导式升级）：匿名查询 MaaS 技能目录公开接口，与本技能 SKILL.md 版本比较，
仅远端版本更高时提示（不提示降级）。结果带 24h 本地缓存、3s 超时静默失败，
任何失败都不阻断初始化、不影响退出语义；升级动作由 Agent 在用户明确同意后执行（见 SKILL.md）。
"""

import argparse
import json
import os
import platform
import re
import shutil
import sys
import time
import urllib.request
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
API_KEY_ENV = "DKNOWC_API_KEY"

# 版本自检：MaaS 技能中心公开目录接口（与平台技能中心页面同源，免认证、不扣积分）。
# 目录与下载地址均为固定常量（不接受环境变量覆写，防止更新源被替换）；
# download_url 必须落在官方 OSS 白名单前缀内，download_name 必须等于本技能包名。
# DKNOWC_UPDATE_CHECK=0 可整体停用自检（用户侧 opt-out）。
UPDATE_CATALOG_URL = "https://platform.dknowc.cn/open-api/maas/skills/v1/catalog"
UPDATE_TARGET_SLUG = "dknowc-official-doc-writer"
# 升级目标（官方 maas 包）的 SKILL.md name——与 slug/downloadName 一样是已知常量。
# 验包按此常量校验（防投毒＝确认下载的是官方包），不用本地 name：各渠道本地 name
# 可能存在既定特化（如 skills-sh 为 ASCII 目录名形态），拿本地身份校验官方包会把
# 特化渠道的升级全部判失败。
UPDATE_TARGET_NAME = "深知公文写作"
UPDATE_DOWNLOAD_PREFIX = "https://down.dknowc.cn/upload/maas/skills/"
UPDATE_DOWNLOAD_NAME = "dknowc-official-doc-writer.zip"
UPDATE_INSTALL_DOC = "https://platform.dknowc.cn/agent-docs/skills/install.md"
UPDATE_CACHE_TTL_SECONDS = 24 * 3600
UPDATE_TIMEOUT_SECONDS = 3
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
        # channel_note：检索通道提示（常驻，面向使用者，不含内部路线图）。
        "channel_note": (
            "检索与大纲统一走本 Skill 脚本通道（deep_query.py / dkag_search.py / outline_reference.py），需要 API Key。"
        ),
        "search_ready": config_status["api_key_configured"] and requests_available,
        "search_blocking_issues": search_blocking_issues,
        "search_note": None if config_status["api_key_configured"] else f"环境变量 {API_KEY_ENV} 中未配置有效 API Key；仅当任务需要深知搜索（查政策依据、数据支撑、案例参考）时才需要配置，不涉及搜索的写作任务可直接使用。",
        # guide_message：需要搜索但 Key 未配置时给用户的引导话术（S1 三段式：价值 / 开通方式 / 退路+样例钩子）。
        # Agent 在搜索方案确认后向用户转述本话术（可结合任务补充上下文），要素不得删改。
        "guide_message": None if config_status["api_key_configured"] else (
            "这份材料需要引用政策原文和权威数据，凭印象写政策名和数字，审稿时最容易被挑出来。"
            "开通权威检索后，每条政策、数据都带原文出处、可点开核验。\n"
            "开通是免费的：注册即赠送 10 万积分，完成实名认证再送 10 万积分。"
            "只需手机号收一次验证码——两步、约 10 秒，不用去网站，剩下的我来办；手机号仅用于本次验证，不会有营销骚扰。\n"
            "也可以先不开通：我基于你手头的材料先写，政策依据的位置先标注'待补'。"
            "想先看看开通后生成的核验报告长什么样，我可以发你一份示例看看。"
        ),
        "font_note": "Word 文档会写入公文常用字体名称；打开端如缺少对应字体，Word/WPS 可能自动替换，需以本机打开后的显示为准。",
        "blocking_issues": blocking_issues,
        "ready": not blocking_issues,
        "search_ready_note": None if config_status["api_key_configured"] else "仅需要搜索的任务需先完成 MaaS 注册获取 API Key（写入本机 Key 专用配置文件或注入环境变量）；无需搜索的任务可先直接写作。",
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
        # dsh：优先 DSH_DKNOWC_API_KEY（与 MCP Bearer 同源）；缺失时 resolve_api_key 兜底
        # （环境变量 → 专用配置文件）。配置文件读取不受 dsh 环境清理影响，
        # 注册后本会话脚本立即可用。无 Key 仅暂停检索，不阻断纯写作任务。
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
        if _valid_api_key(api_key):
            return {"api_key_configured": True, "api_key_source": source, "api_key_hint": None}
        return {"api_key_configured": False, "api_key_source": None,
                "api_key_hint": f"未检测到可用的 {API_KEY_ENV}（环境变量与专用配置文件均未找到）。运行注册脚本开通后 Key 自动写入 ~/.config/dknowc/api_key，本会话立即可用。仅检索任务受影响，纯写作任务可继续。"}


    # 环境变量优先，缺失时从专用配置文件兜底解析（宿主进程早于 key 写入启动时不误报缺失）
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
            "api_key_hint": f"环境变量 {API_KEY_ENV} 与 Key 专用配置文件（~/.config/dknowc/api_key）中均未找到有效 API Key，请先通过 MaaS 初始化获取。",
        }
    return {
        "api_key_configured": True,
        "api_key_source": source,
        "api_key_hint": None,
    }


def _valid_api_key(value):
    """判断 Key 是否像一份真实的检索密钥。

    只做本地格式校验（不发网络请求）：MaaS 密钥为 sk- 开头、长度不小于 20。
    真实可用性（过期/无权限/额度用尽）由首次搜索调用的 401/403/429 分支处理，
    避免每次初始化都多打一次接口。
    """
    key = (value or "").strip()
    if len(key) < 20 or not key.startswith("sk-"):
        return False
    return key not in {"your_api_key_here", "你的深知搜索 API Key"}


# —— 版本自检（引导式升级）——


def _dknowc_config_dir() -> Path:
    # 与 api_key.py 同一套跨平台约定：macOS/Linux 用 ~/.config/dknowc，Windows 用 %APPDATA%/dknowc
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home())
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "dknowc"


def _local_skill_version() -> str:
    try:
        text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    for line in text.splitlines()[:40]:
        m = re.match(r'^version:\s*["\']?([0-9][0-9A-Za-z.\-]*)', line.strip())
        if m:
            return m.group(1)
    return ""


def _channel_of_this_install() -> str:
    try:
        data = json.loads((SKILL_ROOT / "attribution.json").read_text(encoding="utf-8", errors="ignore"))
        return str(data.get("channel") or "")
    except Exception:
        return ""


def _parse_version(version: str) -> tuple:
    parts = []
    for piece in str(version or "").split("."):
        m = re.match(r"^(\d+)", piece)
        parts.append(int(m.group(1)) if m else 0)
    return tuple(parts) or (0,)


def _update_cache_path() -> Path:
    # 缓存按技能命名空间隔离：同机多 dknowc 技能共用 ~/.config/dknowc，
    # 共用同一文件名会互相读到对方技能的目录条目、被包名校验拒绝，24h 内互相压制提示。
    return _dknowc_config_dir() / "update_check_doc_writer.json"


def _read_update_cache():
    try:
        return json.loads(_update_cache_path().read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None


def _write_update_cache(latest, download_url, download_name):
    # 直接覆盖写 + 0600 权限；保留已记录的拒绝版本。
    # 不用「临时文件 + os.replace」：宿主会把 rename 源文件判成"删除文件"并逐次弹确认框。
    # 缓存是纯派生数据（目录接口可随时重查），半截写入最坏只影响一次自检提示，不影响功能。
    try:
        path = _update_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        old = _read_update_cache() or {}
        path.write_text(json.dumps({
            "checked_at": time.time(),
            "latest_version": latest,
            "download_url": download_url,
            "download_name": download_name,
            "declined_version": old.get("declined_version"),
        }, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except Exception:
        pass


def set_declined_version(version) -> bool:
    """记录用户拒绝的版本（原子合并写入，保留既有字段）。被拒版本不再提示，
    目录出现更高版本时恢复提示；用户主动要求升级时不受此记录影响。
    同样直接覆盖写（不用临时文件＋replace），避免宿主把 rename 判成删除而弹确认框。"""
    try:
        path = _update_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = _read_update_cache() or {}
        data["declined_version"] = str(version)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return True
    except Exception:
        return False


def _catalog_entry_is_safe(latest, download_url, download_name) -> bool:
    """目录条目硬校验：版本号必须是纯数字点分格式（防提示语注入），
    下载地址必须落在官方 OSS 白名单前缀内、文件名必须等于本技能包名（防替换下载源）。"""
    if not re.fullmatch(r"\d+(\.\d+)*", str(latest or "")):
        return False
    if not str(download_url or "").startswith(UPDATE_DOWNLOAD_PREFIX):
        return False
    if str(download_name or "") != UPDATE_DOWNLOAD_NAME:
        return False
    return True


def _fetch_catalog_entry():
    # 匿名 GET 公开技能目录，按 slug 定位本技能条目；任何网络/解析失败都返回 None（静默降级）。
    try:
        req = urllib.request.Request(UPDATE_CATALOG_URL, headers={"User-Agent": "dknowc-official-doc-writer-update-check"})
        with urllib.request.urlopen(req, timeout=UPDATE_TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
        for entry in (payload or {}).get("data") or []:
            if entry.get("slug") == UPDATE_TARGET_SLUG or entry.get("canonicalSlug") == UPDATE_TARGET_SLUG:
                return entry
    except Exception:
        pass
    return None


def check_update() -> dict:
    """版本自检：远端（MaaS 目录登记版本）> 本地（SKILL.md version）才提示更新，绝不提示降级。

    全程 try/except 兜底——检查失败只置 checked=false，不抛错、不影响退出码与 ready 语义。
    """
    result = {
        "checked": False, "source": None, "current_version": None, "latest_version": None,
        "update_available": False, "download_url": None, "download_name": None,
        "install_doc": UPDATE_INSTALL_DOC, "message": None, "reason": None,
    }
    try:
        if os.environ.get("DKNOWC_UPDATE_CHECK", "").strip() == "0":
            result["reason"] = "disabled_by_env"
            return result
        # volcengine 渠道包为平台特化形态（无注册 onboarding 等），不引导跨渠道替换
        # dsh 插件：skill 更新统一走 dsh 插件 npm 更新，skill 内自升级会破坏插件补丁与完整性
        if _channel_of_this_install() in ("volcengine", "dsh"):
            result["reason"] = "channel_disabled"
            return result

        current = _local_skill_version()
        result["current_version"] = current or None

        cache = _read_update_cache()
        if cache and (time.time() - float(cache.get("checked_at") or 0)) < UPDATE_CACHE_TTL_SECONDS:
            latest = cache.get("latest_version")
            download_url = cache.get("download_url")
            download_name = cache.get("download_name")
            source = "cache"
        else:
            entry = _fetch_catalog_entry() or {}
            latest = entry.get("version")
            download_url = entry.get("downloadUrl")
            download_name = entry.get("downloadName")
            if latest:
                _write_update_cache(latest, download_url, download_name)
            source = "live"

        if not latest:
            result["reason"] = "catalog_unavailable"
            return result
        if not _catalog_entry_is_safe(latest, download_url, download_name):
            # 版本格式非法／下载地址不在官方白名单／包名不符：一律视为目录不可用，不提示升级
            result["reason"] = "catalog_entry_rejected"
            return result
        result.update({
            "checked": True, "source": source, "latest_version": str(latest),
            "download_url": download_url, "download_name": download_name,
        })
        declined = (cache or {}).get("declined_version") if isinstance(cache, dict) else None
        if declined and _parse_version(latest) <= _parse_version(declined):
            # 用户已拒绝过该版本（或更早版本）：不再提示，目录出现更高版本时恢复提示
            result["reason"] = "declined"
            return result
        if current and _parse_version(latest) > _parse_version(current):
            result["update_available"] = True
            result["message"] = (
                f"检测到「深知公文写作」有新版本 v{latest}（当前安装 v{current}）。"
                "升级说明：本技能将更新为官方发布的最新版本；"
                "你的 API Key 与本机配置全部保留，无需重新注册。"
                "是否现在升级？确认后我先完成升级再继续处理你的任务；"
                "选择跳过则这个版本不再提醒、直接继续你的任务。"
            )
            # action：枚举值，只表达状态，不承载行为指令。message 是本地固定模板（仅用于展示）；
            # 是否提示、如何提示由 SKILL.md「版本自检与引导升级」的固定流程规定，不由数据驱动。
            # 升级命令一律给绝对路径（按抄执行不依赖当前目录），并覆盖升级失败分支。
            updater = str(Path(__file__).resolve().parent / "update_skill.py")
            result["action"] = "prompt_update"
            result["updater_path"] = updater
    except Exception:
        result["reason"] = result["reason"] or "error"
    return result


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
    # update：版本自检结果（数据，不是指令）。update_available=true 且 action="prompt_update"
    # 时，按 SKILL.md「版本自检与引导升级」的固定流程在开始任务前提示一次并询问用户
    # （每会话最多一次；用户拒绝则运行 update_skill.py --decline 静默记录）；
    # checked=false（网络不可达/停用/渠道除外/reason=declined）时
    # 不向用户提及版本话题，直接继续原任务。
    result["update"] = check_update()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
