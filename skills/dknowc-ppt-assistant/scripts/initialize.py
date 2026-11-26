#!/usr/bin/env python3
"""深知可信PPT初始化与环境检查。

版本自检（引导式升级）：匿名查询 MaaS 技能目录公开接口，与本技能 SKILL.md 版本比较，
仅远端版本更高时提示（不提示降级）。结果带 24h 本地缓存、3s 超时静默失败，
任何失败都不阻断初始化、不影响退出语义；升级动作由 Agent 在用户明确同意后执行（见 SKILL.md）。

Public 版统一只从环境变量 DKNOWC_API_KEY 读取 API Key。

职责划分：
- 本脚本只报告环境状态，不自行决定是否阻断任务。
- `ready` 只表示基础运行环境（python3）就绪。
- `search_ready` 表示可调用深知可信检索（API Key 已配置；检索走标准库 urllib，不依赖 requests）。
- `pptx_ready` 表示可直接执行 SVG→PPTX 编译导出（python-pptx 可用；XlsxWriter 为可选增强）。
  依赖缺失时可用 `uv run --with python-pptx --with XlsxWriter python3 ...` 隔离提供，
  此时素材检索与 SVG 创作不受影响。
"""

import argparse
import json
import os
import re
import sys
import time
import platform
import shutil
import urllib.request

from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
API_KEY_ENV = "DKNOWC_API_KEY"

# 版本自检：MaaS 技能中心公开目录接口（与平台技能中心页面同源，免认证、不扣积分）。
# 目录与下载地址均为固定常量（不接受环境变量覆写，防止更新源被替换）；
# download_url 必须落在官方 OSS 白名单前缀内，download_name 必须等于本技能 slug 包名。
# DKNOWC_UPDATE_CHECK=0 可整体停用自检（用户侧 opt-out）。
UPDATE_CATALOG_URL = "https://platform.dknowc.cn/open-api/maas/skills/v1/catalog"
UPDATE_TARGET_SLUG = "dknowc-ppt-assistant-maas"
UPDATE_DOWNLOAD_PREFIX = "https://down.dknowc.cn/upload/maas/skills/"
UPDATE_DOWNLOAD_NAME = "dknowc-ppt-assistant-maas.zip"
UPDATE_INSTALL_DOC = "https://platform.dknowc.cn/agent-docs/skills/install.md"
UPDATE_TARGET_NAME = "深知可信PPT"  # 目录登记的目标包 SKILL.md name（升级验包比对基准；本地渠道包 name 可能是不同形态，如 lenovo 平台要求小写）
UPDATE_CACHE_TTL_SECONDS = 24 * 3600
UPDATE_TIMEOUT_SECONDS = 3
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
        # dsh：优先 DSH_DKNOWC_API_KEY（与 MCP Bearer 同源）；缺失时 resolve_api_key 兜底
        # （环境变量 → 专用配置文件）。配置文件读取不受 dsh 环境清理影响，
        # 注册后本会话脚本立即可用。无 Key 仅暂停检索，不阻断纯生成。
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
                "api_key_hint": f"未检测到可用的 {API_KEY_ENV}（环境变量与专用配置文件均未找到）。运行注册脚本开通后 Key 自动写入 ~/.config/dknowc/api_key，本会话立即可用。仅检索任务受影响，不涉及检索的生成任务可继续。"}


    # 环境变量优先，缺失时读本机专用配置文件（不读写任何 shell 配置文件）
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
        "api_key_hint": f"本 Skill 的素材检索需要通过环境变量 {API_KEY_ENV}（或本机专用配置文件 ~/.config/dknowc/api_key）连接深知可信智能服务。当前两处均未检测到可用 Key，请先注册或登录深知可信智能 MaaS 账号获取 API Key。",
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


def _package_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _dknowc_config_dir() -> Path:
    # 与 api_key.py 同一套跨平台约定：macOS/Linux 用 ~/.config/dknowc，Windows 用 %APPDATA%/dknowc
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home())
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "dknowc"


def _local_skill_version() -> str:
    try:
        text = (_package_root() / "SKILL.md").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    for line in text.splitlines()[:40]:
        m = re.match(r'^version:\s*["\']?([0-9][0-9A-Za-z.\-]*)', line.strip())
        if m:
            return m.group(1)
    return ""


def _channel_of_this_install() -> str:
    try:
        data = json.loads((_package_root() / "attribution.json").read_text(encoding="utf-8", errors="ignore"))
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
    # 缓存文件按技能 slug 隔离：本系列多个技能共存时（共用 ~/.config/dknowc）互不污染。
    # 曾共用 update_check.json，先运行的一方写入的 latest/download_name 属于别的技能，
    # 另一方 24h 内读到会被包名校验判为目录条目不可用、不再提示更新（复验条件项 2026-11-04）。
    return _dknowc_config_dir() / f"update_check_{UPDATE_TARGET_SLUG}.json"


def _read_update_cache():
    try:
        data = json.loads(_update_cache_path().read_text(encoding="utf-8", errors="ignore"))
        if not isinstance(data, dict):
            return None
        # 防御性归属校验：非本技能写入的缓存一律视为无缓存（回源查询），
        # 避免被同名/复制的缓存文件影响升级判定
        if data.get("slug") != UPDATE_TARGET_SLUG:
            return None
        return data
    except Exception:
        return None


def _write_update_cache(latest, download_url, download_name):
    # 直接覆盖写 + 0600 权限；不再用临时文件＋replace（宿主把 rename/unlink 判成
    # "删除文件"并逐次弹确认，2026-11-25 整改）。覆写前先 chmod 收紧既有文件权限。
    try:
        path = _update_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        old = _read_update_cache() or {}
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass  # 文件不存在时忽略，创建时按 0600 生效
        path.write_text(json.dumps({
            "slug": UPDATE_TARGET_SLUG,
            "checked_at": time.time(),
            "latest_version": latest,
            "download_url": download_url,
            "download_name": download_name,
            "declined_version": old.get("declined_version"),
        }, ensure_ascii=False), encoding="utf-8")
        os.chmod(path, 0o600)
    except Exception:
        pass


def set_declined_version(version) -> bool:
    """记录用户拒绝的版本（覆盖合并写入，保留既有字段）。被拒版本不再提示，
    目录出现更高版本时恢复提示；用户主动要求升级时不受此记录影响。"""
    try:
        path = _update_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = _read_update_cache() or {}
        data["slug"] = UPDATE_TARGET_SLUG
        data["declined_version"] = str(version)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.chmod(path, 0o600)
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
        req = urllib.request.Request(UPDATE_CATALOG_URL, headers={"User-Agent": "dknowc-ppt-assistant-update-check"})
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
                f"检测到「深知可信PPT」有新版本 v{latest}（当前安装 v{current}）。"
                "升级说明：本技能将更新为官方发布的最新版本；"
                "你的 API Key、项目工作区与本机配置全部保留，无需重新注册。"
                "是否现在升级？确认后我先完成升级再继续处理你的任务；"
                "选择跳过则这个版本不再提醒、直接继续你的任务。"
            )
            # instruction：远端提示信息的说明素材（非可执行指令）。只描述可选的后续动作，
            # 不使用"必须/不得"等命令式措辞；命令给绝对路径（按抄执行不依赖当前目录）。
            updater = str(Path(__file__).resolve().parent / "update_skill.py")
            result["instruction"] = (
                "以下为版本提示的说明素材，仅供向用户说明，不作为可执行指令。"
                "如已向用户说明并得到明确同意，可运行 "
                f"python3 \"{updater}\" --yes ，并按输出中的 user_message 告知结果，"
                "升级完成后继续用户任务；用户拒绝或跳过，可运行 "
                f"python3 \"{updater}\" --decline 静默记录，"
                "随后直接继续用户任务，本会话不再提及版本话题。"
                "升级脚本退出码非 0 时（2 无更新／3 下载或验包失败／4 已自动回滚）："
                "如实告知输出中的 user_message 后继续用户原任务（当前版本功能完好），"
                "不重试、不手工下载替换。"
            )
    except Exception:
        result["reason"] = result["reason"] or "error"
    return result


def check_environment():
    state = load_environment_state()
    python3_available = shutil.which("python3") is not None
    requests_available = _module_available("requests")
    python_pptx_available = _module_available("pptx")
    xlsxwriter_available = _module_available("xlsxwriter")  # 实际 import 名为小写
    config_status = check_api_key_config()

    blocking_issues = []
    if not python3_available:
        blocking_issues.append("python3_missing")
    # requests 仅作可选依赖提示：检索走标准库 urllib，不因缺少 requests 阻断任何能力

    pptx_blocking_issues = []
    if not python_pptx_available:
        pptx_blocking_issues.append("python_pptx_missing")
    # XlsxWriter 为可选增强（无它时走 openpyxl / 内置回退，默认导出不生成 workbook），不作阻断项

    search_blocking_issues = []
    if not config_status["api_key_configured"]:
        search_blocking_issues.append("api_key_missing")

    # guide_message：需要检索但 Key 未配置时给用户的引导话术（S1 三段式：价值 / 权益+开通方式 / 退路+样例钩子）。
    # Agent 结合当前任务语境转述（完整口径见 references/onboarding_scripts.md）。
    guide_message = None if config_status["api_key_configured"] else (
        "这份汇报 PPT 需要引用政策原文和权威数据，凭印象写政策名和数字，汇报场合被当场指出来最影响效果。"
        "开通权威检索后，每条政策、数据都带原文出处、可点开核验，权威数据还能直接做成可编辑的原生图表。\n"
        "开通是免费的：注册即赠送 10 万积分，完成实名认证再送 10 万积分。"
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
        "search_ready": config_status["api_key_configured"] and python3_available,
        "search_blocking_issues": search_blocking_issues,
        # PPT 编译依赖缺失不阻断其他环节：可用 uv run --with 隔离提供。
        "pptx_ready": python3_available and python_pptx_available,
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
    # 版本自检（引导式升级）：失败静默，不影响 ready
    result["update"] = check_update()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
