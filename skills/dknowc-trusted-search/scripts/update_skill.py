#!/usr/bin/env python3
"""深知可信搜索 引导式升级执行器（「版本自检与引导升级」的代码化四步）。

由 Agent 在用户明确同意升级后调用（见 SKILL.md「版本自检与引导升级」）：

  python3 scripts/update_skill.py           # 预览：版本对比＋下载地址＋影响说明，不做任何改动
  python3 scripts/update_skill.py --yes     # 执行：下载官方包 → 验包 → 备份 → 就地替换 → 验证

安全约束：
- 目录地址、下载白名单前缀、包名均为 initialize.py 固定常量（不接受任何参数传入的
  自定义 URL）；版本来源、下载地址、包名任一不符即拒绝；
- 验包：单一顶层目录、无绝对路径与 .. 逃逸、无软链接、zip CRC 完整、包内 SKILL.md
  的 name 与本技能一致且 version 等于目录登记版本；
- 整目录备份成功后才开始替换；替换过程异常自动从备份回滚；
- 只写本技能安装目录与系统临时目录，不读写任何 shell 配置文件；
  ~/.config/dknowc（API Key、自检缓存）在技能目录之外，不受影响。

退出码：0＝成功（预览或升级完成）；2＝无可用更新或当前渠道不支持自升级；
3＝下载或验包失败（未做任何改动）；4＝替换失败（已从备份回滚）；1＝其他错误。
"""

import argparse
import json
import re
import shutil
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from initialize import (  # noqa: E402
    UPDATE_DOWNLOAD_NAME,
    UPDATE_DOWNLOAD_PREFIX,
    UPDATE_INSTALL_DOC,
    UPDATE_TARGET_NAME,
    _parse_version,
    check_update,
    set_declined_version,
)

MAX_PACKAGE_BYTES = 20 * 1024 * 1024  # 压缩包下载上限防护（当前约 0.5MB）
MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024  # 解压后总量上限（防压缩炸弹，正常包 <2MB）
DOWNLOAD_TIMEOUT_SECONDS = 60
USER_DATA_DIRS = ("official-docs",)  # 技能目录内的用户工作区，升级时保留


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """禁止下载跟随重定向：官方 OSS 地址必须直连命中，任何 30x 视为异常。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _emit(payload: dict, code: int):
    payload["exit_code"] = code
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.exit(code)


def _skill_md_meta_from_zip(zf: zipfile.ZipFile):
    """读包内 SKILL.md frontmatter 的 name 与 version。"""
    name_member = next((n for n in zf.namelist() if n.count("/") == 1 and n.endswith("/SKILL.md")), None)
    if not name_member:
        return None, None
    head = zf.read(name_member).decode("utf-8", errors="ignore")[:2000]
    m_name = re.search(r'^name:\s*["\']?([^"\'\n]+)', head, re.M)
    m_ver = re.search(r'^version:\s*["\']?([0-9][0-9A-Za-z.\-]*)', head, re.M)
    return (m_name.group(1).strip() if m_name else None, m_ver.group(1) if m_ver else None)


def _validate_package(zip_path: Path, expect_version: str, expect_name: str):
    """验包：结构安全 + 解压总量上限 + zip 完整性 + 包内 SKILL.md 与官方目标包身份一致（UPDATE_TARGET_NAME）。返回错误列表（空＝通过）。"""
    errors = []
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = [n for n in zf.namelist() if n.strip()]
            tops = {n.split("/")[0] for n in names}
            if len(tops) != 1 or not next(iter(tops), ""):
                errors.append(f"顶层目录数异常：{len(tops)}")
            total_uncompressed = 0
            for n in names:
                parts = Path(n).parts
                # POSIX 绝对路径／.. 逃逸／反斜杠／Windows 盘符（C:）与含冒号组件一律拒绝
                if n.startswith("/") or ".." in parts or "\\" in n or any(":" in p for p in parts):
                    errors.append(f"路径逃逸：{n}")
                info = zf.getinfo(n)
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    errors.append(f"包含软链接：{n}")
                total_uncompressed += info.file_size
            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                errors.append(f"解压后总量超上限：{total_uncompressed} > {MAX_UNCOMPRESSED_BYTES}")
            bad = zf.testzip()
            if bad is not None:
                errors.append(f"zip 完整性校验失败：{bad}")
            pkg_name, pkg_version = _skill_md_meta_from_zip(zf)
            if pkg_name != expect_name:
                errors.append(f"包内 SKILL.md name 不一致：{pkg_name}")
            if pkg_version != expect_version:
                errors.append(f"包内 SKILL.md version 不等于登记版本：{pkg_version} != {expect_version}")
    except zipfile.BadZipFile:
        errors.append("不是有效的 zip 文件")
    return errors


def _download(url: str, dest: Path, allowed_prefix: str):
    """流式下载到 dest：禁止重定向（最终地址必须仍落在白名单前缀内）＋压缩包大小上限。"""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "dknowc-trusted-search-update"})
    with opener.open(req, timeout=DOWNLOAD_TIMEOUT_SECONDS) as resp, open(dest, "wb") as f:
        final_url = resp.geturl() or url
        if not final_url.startswith(allowed_prefix):
            raise ValueError(f"下载最终地址越界：{final_url[:80]}")
        total = 0
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_PACKAGE_BYTES:
                raise ValueError(f"下载超出大小上限（{MAX_PACKAGE_BYTES} 字节）")
            f.write(chunk)


def _backup_install(install_dir: Path, old_version: str) -> Path:
    """整目录备份为安装目录旁的 zip（可恢复）。备份失败抛异常，调用方不得继续替换。"""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup = install_dir.parent / f"{install_dir.name}_backup_v{old_version}_{stamp}.zip"
    shutil.make_archive(str(backup.with_suffix("")), "zip", install_dir.parent, install_dir.name)
    return backup


def _restore_install(backup: Path, install_dir: Path):
    """从备份回滚（替换阶段异常时调用）。"""
    for child in install_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)
    with zipfile.ZipFile(backup) as zf:
        top = next(iter({n.split("/")[0] for n in zf.namelist() if n.strip()}), None)
        for n in zf.namelist():
            if n.endswith("/"):
                continue
            rel = Path(n).relative_to(top)
            dest = install_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(n))


def _replace_in_place(zip_path: Path, install_dir: Path, staging: Path):
    """就地替换：用户数据暂存→清空→写入新包（剥顶层）→恢复用户数据。"""
    for sub in USER_DATA_DIRS:
        src = install_dir / sub
        if src.exists():
            shutil.move(str(src), str(staging / sub))
    for child in install_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    with zipfile.ZipFile(zip_path) as zf:
        top = next(iter({n.split("/")[0] for n in zf.namelist() if n.strip()}))
        for n in zf.namelist():
            if n.endswith("/"):
                continue
            rel = Path(n).relative_to(top)
            dest = install_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(n))
    for sub in USER_DATA_DIRS:
        if (staging / sub).exists():
            shutil.move(str(staging / sub), str(install_dir / sub))


def main():
    parser = argparse.ArgumentParser(description="深知可信搜索 引导式升级（须先经用户明确同意才使用 --yes）")
    parser.add_argument("--yes", action="store_true", help="确认执行升级（默认仅预览，不做任何改动）")
    parser.add_argument("--decline", action="store_true", help="记录用户拒绝本次版本（静默；被拒版本不再提示，出现更高版本时恢复提示）")
    parser.add_argument("--force", action="store_true", help="用户主动要求升级时与 --yes 同用：无视拒绝记录执行（仍走全部下载与验包校验）")
    args = parser.parse_args()

    install_dir = Path(__file__).resolve().parent.parent
    local_meta = (install_dir / "SKILL.md").read_text(encoding="utf-8", errors="ignore")[:2000]
    m_ver = re.search(r'^version:\s*["\']?([0-9][0-9A-Za-z.\-]*)', local_meta, re.M)
    local_version = m_ver.group(1) if m_ver else ""

    update = check_update()

    if args.decline:
        # 用户拒绝了本次版本提示：静默记录被拒版本（对用户无感，无需转述）。
        latest_known = update.get("latest_version") if update.get("checked") else None
        recorded = bool(latest_known) and set_declined_version(latest_known)
        _emit({"ok": recorded, "declined_version": latest_known, "user_message": None},
              0 if recorded else 2)

    # --force：用户主动要求升级时无视"拒绝记录"（reason=declined）继续执行，
    # 但仍须远端登记版本高于本地——同版本重装与降级（含目录版本回退）一律拒绝；
    # 其余无更新场景（检查失败／停用）force 不生效，仍退出 2。
    remote_higher = _parse_version(update.get("latest_version") or "0") > _parse_version(local_version or "0")
    forced = args.force and update.get("reason") == "declined" and remote_higher
    if not update.get("update_available") and not forced:
        _emit({
            "ok": False,
            "reason": update.get("reason") or "no_update",
            "current_version": update.get("current_version") or local_version,
            "latest_version": update.get("latest_version"),
            "user_message": "当前已是最新版本，无需升级。" if update.get("checked") else "暂时无法确认是否有新版本（版本目录不可达或当前渠道不支持自升级），已跳过，不影响使用。",
        }, 2)

    latest = update["latest_version"]
    base = {
        "ok": True,
        "current_version": local_version,
        "latest_version": latest,
        "download_url": update["download_url"],
        "download_name": update["download_name"],
        "install_doc": UPDATE_INSTALL_DOC,
    }

    if not args.yes:
        _emit({
            **base,
            "mode": "preview",
            "user_message": (
                f"新版本 v{latest}（当前 v{local_version}）已就绪：本技能将更新为官方发布的最新版本，"
                "你的 API Key 与本机配置全部保留，无需重新注册；升级过程不影响你的任务。"
            ),
        }, 0)

    # ── 执行升级：下载 → 验包 → 备份 → 替换 → 验证 ──
    with tempfile.TemporaryDirectory(prefix="dknowc_upgrade_") as td:
        td = Path(td)
        pkg = td / UPDATE_DOWNLOAD_NAME
        try:
            _download(update["download_url"], pkg, UPDATE_DOWNLOAD_PREFIX)
        except Exception as exc:
            _emit({**base, "ok": False, "stage": "download", "error": str(exc)[:200],
                   "user_message": "升级包下载失败，未做任何改动，可稍后重试；如持续失败请联系服务方。"}, 3)

        errors = _validate_package(pkg, latest, UPDATE_TARGET_NAME)
        if errors:
            _emit({**base, "ok": False, "stage": "verify", "errors": errors,
                   "user_message": "升级包校验未通过（结构或版本异常），已中止，未做任何改动；请反馈给服务方。"}, 3)

        staging = td / "staging"
        staging.mkdir()
        backup = None
        try:
            backup = _backup_install(install_dir, local_version or "unknown")
            _replace_in_place(pkg, install_dir, staging)
        except Exception as exc:
            if backup is None:
                # 备份阶段失败：安装目录尚未做任何改动
                _emit({**base, "ok": False, "stage": "backup", "error": str(exc)[:200], "rollback": "not_needed",
                       "user_message": "升级前备份失败，未做任何改动；请检查磁盘空间后重试。"}, 4)
            try:
                _restore_install(backup, install_dir)
                for sub in USER_DATA_DIRS:
                    if (staging / sub).exists() and not (install_dir / sub).exists():
                        shutil.move(str(staging / sub), str(install_dir / sub))
                _emit({**base, "ok": False, "stage": "replace", "error": str(exc)[:200], "rollback": "success",
                       "user_message": "升级过程中出现异常，已自动回滚到原版本，使用不受影响；请反馈给服务方。"}, 4)
            except Exception as rollback_exc:
                _emit({**base, "ok": False, "stage": "replace", "error": str(exc)[:200], "rollback": "failed",
                       "rollback_error": str(rollback_exc)[:200],
                       "backup_path": str(backup),
                       "user_message": "升级失败且回滚未完全成功，请把备份文件提供给服务方恢复。"}, 4)

        new_meta = (install_dir / "SKILL.md").read_text(encoding="utf-8", errors="ignore")[:2000]
        m_new = re.search(r'^version:\s*["\']?([0-9][0-9A-Za-z.\-]*)', new_meta, re.M)
        new_version = m_new.group(1) if m_new else ""
        preserved = {sub: (install_dir / sub).exists() for sub in USER_DATA_DIRS}
        if new_version != latest:
            # 不应发生（验包已比对），兜底触发回滚
            _restore_install(backup, install_dir)
            _emit({**base, "ok": False, "stage": "verify_after_replace", "error": f"替换后版本异常：{new_version}",
                   "rollback": "success",
                   "user_message": "升级后校验未通过，已自动回滚到原版本，使用不受影响。"}, 4)

        _emit({
            **base,
            "mode": "upgrade",
            "ok": True,
            "backup_path": str(backup),
            "user_data_preserved": preserved,
            "new_version": new_version,
            "user_message": (
                f"深知可信搜索已从 v{local_version} 升级到 v{new_version}。"
                "你的 API Key 与本机配置全部保留，无需重新注册。"
                f"如需回退，原版本备份已保存在：{backup}"
            ),
        }, 0)


if __name__ == "__main__":
    main()
