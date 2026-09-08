#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建 Ubuntu 22.04 amd64 的离线可安装 Debian 包。

运行：
    ./.venv/bin/python packaging/build_deb.py

包内自带 GUI、云端自动标注、人工修框、提示词优化、视频切片和数据集
导出的 Python 依赖，不包含硬件相关的 PyTorch/CUDA、本地大模型和训练环境。
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.metadata as metadata
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import sysconfig
import tempfile
import textwrap

from packaging.requirements import Requirement


PACKAGE = "best-yolo"
VERSION = "1.3.0-1"
ARCH = "amd64"
MAINTAINER = "LIANGFENG1007 <292772460+LIANGFENG1007@users.noreply.github.com>"
ROOT = Path(__file__).resolve().parents[1]
SITE_PACKAGES = Path(sysconfig.get_paths()["purelib"]).resolve()

RUNTIME_DISTS = (
    "PySide6-Essentials",
    "Pillow",
    "openai",
    "PyYAML",
    "opencv-python",
    "numpy",
)

ROOT_FILES = (
    "autolabel_qwen.py",
    "build_dataset.py",
    "palette.py",
)

GUI_FILES = (
    "app.py",
    "appmeta.py",
    "boxedit.py",
    "core.py",
    "promptai.py",
    "rangebar.py",
    "runner.py",
    "shortcut_settings.py",
    "theme.py",
    "theme_settings.py",
    "update_check.py",
    "video.py",
    "widgets.py",
)

SYSTEM_DEPENDS = (
    "python3 (>= 3.10)",
    "python3 (<< 3.11)",
    "libc6 (>= 2.35)",
    "libstdc++6",
    "libgcc-s1",
    "libglib2.0-0",
    "libgl1",
    "libegl1",
    "libopengl0",
    "libfontconfig1",
    "libfreetype6",
    "libdbus-1-3",
    "libx11-6",
    "libx11-xcb1",
    "libxext6",
    "libxkbcommon0",
    "libxkbcommon-x11-0",
    "libxcb1",
    "libxcb-cursor0",
    "libxcb-icccm4",
    "libxcb-image0",
    "libxcb-keysyms1",
    "libxcb-randr0",
    "libxcb-render0",
    "libxcb-render-util0",
    "libxcb-shape0",
    "libxcb-shm0",
    "libxcb-sync1",
    "libxcb-util1",
    "libxcb-xfixes0",
    "libxcb-xkb1",
    "libxau6",
    "libxdmcp6",
    "libwayland-client0",
    "libwayland-cursor0",
    "libwayland-egl1",
    "libgtk-3-0",
    "libffi8",
    "libpng16-16",
    "libbrotli1",
    "libpcre3",
    "libexpat1",
    "libuuid1",
    "libbsd0",
    "libsystemd0",
    "liblzma5",
    "liblz4-1",
    "libcap2",
    "libgcrypt20",
    "libgpg-error0",
    "zlib1g",
    "fonts-noto-cjk",
    "hicolor-icon-theme",
    "desktop-file-utils",
    "xdg-utils",
)


def run(cmd, **kwargs):
    print("+", " ".join(str(x) for x in cmd), flush=True)
    return subprocess.run(cmd, check=True, text=True, **kwargs)


def check_build_host():
    if platform.machine() not in ("x86_64", "AMD64"):
        raise SystemExit("只能在 x86_64 主机上构建 amd64 包")
    if sys.version_info[:2] != (3, 10):
        raise SystemExit("必须使用项目的 Python 3.10 虚拟环境构建")
    os_release = Path("/etc/os-release").read_text(encoding="utf-8")
    if 'VERSION_ID="22.04"' not in os_release:
        raise SystemExit("这个构建脚本只面向 Ubuntu 22.04")
    if not shutil.which("dpkg-deb"):
        raise SystemExit("缺少 dpkg-deb，请先安装 dpkg-dev")
    for name in RUNTIME_DISTS:
        try:
            metadata.distribution(name)
        except metadata.PackageNotFoundError:
            raise SystemExit(f"当前构建环境缺少 {name}")


def dependency_closure(roots):
    queue = list(roots)
    found = {}
    while queue:
        requested = queue.pop(0)
        key = requested.casefold().replace("_", "-")
        if key in found:
            continue
        dist = metadata.distribution(requested)
        real_name = dist.metadata.get("Name") or requested
        real_key = real_name.casefold().replace("_", "-")
        if real_key in found:
            continue
        found[real_key] = dist
        for raw in dist.requires or ():
            req = Requirement(raw)
            if req.marker and not req.marker.evaluate():
                continue
            queue.append(req.name)
    return [found[k] for k in sorted(found)]


def copy_distribution(dist, vendor):
    copied = 0
    for entry in dist.files or ():
        src = Path(dist.locate_file(entry))
        try:
            rel = src.resolve().relative_to(SITE_PACKAGES)
        except (ValueError, FileNotFoundError):
            continue                  # 跳过 .venv/bin 下的命令行工具
        if "__pycache__" in rel.parts or src.suffix in (".pyc", ".pyo"):
            continue
        if rel.name in {"INSTALLER", "REQUESTED", "RECORD", "direct_url.json"}:
            continue                  # pip 安装上下文元数据，不属于运行时或许可证
        if not src.is_file():
            continue
        dst = vendor / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1
    if not copied:
        raise RuntimeError(f"{dist.metadata['Name']} 没有复制到任何文件")
    return copied


def copy_app(stage):
    app_dir = stage / "opt/best-yolo/app"
    gui_dir = app_dir / "gui"
    assets = gui_dir / "_assets"
    assets.mkdir(parents=True, exist_ok=True)
    for name in ROOT_FILES:
        shutil.copy2(ROOT / name, app_dir / name)
    for name in GUI_FILES:
        shutil.copy2(ROOT / "gui" / name, gui_dir / name)
    for name in ("check.png", "arrow.png", "up.png", "down.png"):
        shutil.copy2(ROOT / "gui/_assets" / name, assets / name)
    shutil.copy2(ROOT / "gui/icon.png", gui_dir / "icon.png")
    return app_dir


def write_text(path, body, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    path.chmod(mode)


def write_launcher(stage):
    write_text(stage / "usr/bin/best-yolo", r'''
        #!/bin/sh
        set -u
        umask 077

        APP_DIR="${BEST_YOLO_APP_DIR:-/opt/best-yolo}"
        DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/best-yolo"
        STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/best-yolo"
        CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/best-yolo"
        LOG_FILE="$STATE_DIR/start.log"

        mkdir -p "$DATA_DIR" "$STATE_DIR" "$CACHE_DIR"
        if [ -f "$LOG_FILE" ] && [ "$(stat -c %s "$LOG_FILE" 2>/dev/null || echo 0)" -gt 5242880 ]; then
            mv -f "$LOG_FILE" "$LOG_FILE.old"
        fi

        export BEST_YOLO_DATA_DIR="$DATA_DIR"
        export BEST_YOLO_API_ONLY=1
        export BEST_YOLO_READONLY_INSTALL=1
        export PYTHONPATH="$APP_DIR/vendor:$APP_DIR/app:$APP_DIR/app/gui"
        export PYTHONNOUSERSITE=1
        export PYTHONDONTWRITEBYTECODE=1
        export PYTHONUTF8=1
        export QT_ENABLE_HIGHDPI_SCALING=1
        export QT_PLUGIN_PATH="$APP_DIR/vendor/PySide6/Qt/plugins"
        export QT_QPA_PLATFORM_PLUGIN_PATH="$APP_DIR/vendor/PySide6/Qt/plugins/platforms"
        unset PYTHONHOME

        if [ "${1:-}" = "--show-log" ]; then
            if command -v xdg-open >/dev/null 2>&1; then
                xdg-open "$LOG_FILE"
            else
                printf '%s\n' "$LOG_FILE"
            fi
            exit 0
        fi

        if [ "${1:-}" = "--diagnose" ]; then
            printf 'Best yolo runtime: %s\n' "$APP_DIR"
            printf 'User data: %s\n' "$DATA_DIR"
            printf 'Log: %s\n' "$LOG_FILE"
            /usr/bin/python3 -c 'import sys, PySide6, PIL, openai, cv2, yaml, numpy; from appmeta import APP_VERSION; from PySide6.QtWidgets import QApplication, QWidget; q=QApplication.instance() or QApplication([]); w=QWidget(); print("Best yolo", APP_VERSION); print(sys.version); print("Qt platform", q.platformName()); print("PySide6", PySide6.__version__); print("Pillow", PIL.__version__); print("OpenAI", openai.__version__); print("OpenCV", cv2.__version__); print("NumPy", numpy.__version__)'
            exit $?
        fi

        printf '\n=============== %s 启动 ===============\n' "$(date '+%F %T')" >>"$LOG_FILE"
        /usr/bin/python3 "$APP_DIR/app/gui/app.py" "$@" >>"$LOG_FILE" 2>&1
        code=$?
        if [ "$code" -ne 0 ]; then
            msg="Best yolo 启动失败（退出码 $code）。日志：$LOG_FILE"
            if command -v zenity >/dev/null 2>&1; then
                zenity --error --title="Best yolo" --width=480 --text="$msg" 2>/dev/null &
            elif command -v notify-send >/dev/null 2>&1; then
                notify-send "Best yolo" "$msg" 2>/dev/null || true
            fi
        fi
        exit "$code"
    ''', 0o755)


def write_desktop_files(stage):
    write_text(stage / "usr/share/applications/best-yolo.desktop", '''
        [Desktop Entry]
        Type=Application
        Version=1.0
        Name=Best yolo
        Name[zh_CN]=Best yolo
        Comment=Auto-label images with Qwen-VL and export YOLO datasets
        Comment[zh_CN]=使用千问视觉模型自动标注图片并导出 YOLO 数据集
        TryExec=/usr/bin/best-yolo
        Exec=/usr/bin/best-yolo
        Icon=best-yolo
        Terminal=false
        Categories=Graphics;
        Keywords=yolo;label;annotation;dataset;qwen;标注;数据集;
        StartupNotify=true
    ''')
    icon = stage / "usr/share/icons/hicolor/256x256/apps/best-yolo.png"
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "gui/icon.png", icon)
    write_text(stage / "usr/share/metainfo/best-yolo.metainfo.xml", '''
        <?xml version="1.0" encoding="UTF-8"?>
        <component type="desktop-application">
          <id>io.github.LIANGFENG1007.BestYolo</id>
          <name>Best yolo</name>
          <summary>Qwen-VL assisted YOLO dataset annotation</summary>
          <metadata_license>CC0-1.0</metadata_license>
          <project_license>LicenseRef-proprietary</project_license>
          <description>
            <p>Desktop workflow for cloud image auto-labeling, manual box correction,
            prompt refinement, video frame extraction and YOLO dataset export.</p>
          </description>
          <launchable type="desktop-id">best-yolo.desktop</launchable>
          <provides><binary>best-yolo</binary></provides>
          <categories><category>Graphics</category></categories>
          <content_rating type="oars-1.1" />
        </component>
    ''')


def write_docs(stage, dists):
    doc = stage / "usr/share/doc/best-yolo"
    doc.mkdir(parents=True, exist_ok=True)
    write_text(doc / "README.Debian", '''
        Best yolo for Ubuntu 22.04
        =========================

        This package is the cloud API edition. It includes the desktop interface,
        image auto-labeling, manual correction, prompt refinement, video extraction
        and dataset export. Hardware-specific PyTorch/CUDA and local model weights
        are intentionally not bundled.

        User projects and API credentials are stored under:
          ~/.local/share/best-yolo

        Logs are stored under:
          ~/.local/state/best-yolo/start.log

        Diagnostics:
          best-yolo --diagnose
          best-yolo --show-log

        Removing the Debian package does not delete user projects or credentials.
    ''')
    third_party = [
        "Bundled Python distributions (their license files remain in vendor/*.dist-info):",
        "",
    ]
    for dist in sorted(dists, key=lambda d: (d.metadata.get("Name") or "").casefold()):
        third_party.append(
            f"- {dist.metadata.get('Name')} {dist.version}: "
            f"{dist.metadata.get('License-Expression') or dist.metadata.get('License') or 'see metadata'}")
    write_text(doc / "THIRD_PARTY_LICENSES.txt", "\n".join(third_party) + "\n")
    write_text(doc / "copyright", '''
        Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
        Upstream-Name: Best yolo
        Source: local project

        Files: opt/best-yolo/app/*
        Copyright: 2026 LIANGFENG1007
        License: Proprietary

        Files: opt/best-yolo/vendor/*
        Copyright: respective upstream authors
        License: See THIRD_PARTY_LICENSES.txt and the bundled distribution metadata.
    ''')
    changelog = (
        f"best-yolo ({VERSION}) jammy; urgency=medium\n\n"
        "  * Initial Ubuntu 22.04 amd64 cloud API package.\n\n"
        f" -- {MAINTAINER}  Sun, 07 Sep 2026 22:00:00 +0800\n"
    ).encode("utf-8")
    with (doc / "changelog.Debian.gz").open("wb") as raw:
        with gzip.GzipFile(filename="changelog.Debian", mode="wb",
                           fileobj=raw, mtime=0) as gz:
            gz.write(changelog)


def installed_size_kib(stage):
    return sum(p.stat().st_size for p in stage.rglob("*") if p.is_file()) // 1024


def write_debian_metadata(stage):
    debian = stage / "DEBIAN"
    debian.mkdir(parents=True, exist_ok=True)
    control = f'''
        Package: {PACKAGE}
        Version: {VERSION}
        Section: graphics
        Priority: optional
        Architecture: {ARCH}
        Maintainer: {MAINTAINER}
        Installed-Size: {installed_size_kib(stage)}
        Depends: {", ".join(SYSTEM_DEPENDS)}
        Recommends: zenity
        Description: Qwen-VL assisted YOLO dataset annotation desktop app
         Best yolo provides cloud image auto-labeling, manual bounding-box correction,
         prompt refinement, video frame extraction and YOLO dataset export.
         Python runtime dependencies are bundled for offline installation on Ubuntu 22.04.
    '''
    write_text(debian / "control", control)
    write_text(debian / "postinst", r'''
        #!/bin/sh
        set -e
        if [ -d /opt/best-yolo ]; then
            chown -R root:root /opt/best-yolo
            chmod -R a+rX,go-w /opt/best-yolo
        fi
        if command -v update-desktop-database >/dev/null 2>&1; then
            update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
        fi
        if command -v gtk-update-icon-cache >/dev/null 2>&1; then
            gtk-update-icon-cache -q /usr/share/icons/hicolor >/dev/null 2>&1 || true
        fi
        exit 0
    ''', 0o755)
    write_text(debian / "postrm", r'''
        #!/bin/sh
        set -e
        if command -v update-desktop-database >/dev/null 2>&1; then
            update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
        fi
        if command -v gtk-update-icon-cache >/dev/null 2>&1; then
            gtk-update-icon-cache -q /usr/share/icons/hicolor >/dev/null 2>&1 || true
        fi
        exit 0
    ''', 0o755)

    lines = []
    for path in sorted(p for p in stage.rglob("*")
                       if p.is_file() and "DEBIAN" not in p.parts):
        digest = hashlib.md5(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(stage)}")
    write_text(debian / "md5sums", "\n".join(lines) + "\n")


def normalize_mtimes(stage, epoch):
    for path in stage.rglob("*"):
        if not path.is_symlink():
            os.utime(path, (epoch, epoch))
    os.utime(stage, (epoch, epoch))


def normalize_permissions(stage):
    """Debian 安装内容必须能被普通用户读取，目录必须能被穿越。"""
    for path in stage.rglob("*"):
        if path.is_symlink():
            continue
        if path.is_dir():
            path.chmod(0o755)
            continue
        old_mode = stat.S_IMODE(path.stat().st_mode)
        path.chmod(0o755 if old_mode & 0o111 else 0o644)
    stage.chmod(0o755)


def check_permissions(stage):
    bad = []
    for path in (stage, *stage.rglob("*")):
        if path.is_symlink():
            continue
        mode = stat.S_IMODE(path.stat().st_mode)
        if path.is_dir() and mode & 0o005 != 0o005:
            bad.append((path, mode))
        elif path.is_file() and mode & 0o004 != 0o004:
            bad.append((path, mode))
    if bad:
        sample = ", ".join(f"{p}:{m:o}" for p, m in bad[:8])
        raise RuntimeError(f"安装内容存在普通用户不可读路径：{sample}")


def main():
    global VERSION
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(ROOT / "dist"))
    parser.add_argument("--version", default=VERSION,
                        help="Debian version, for example 1.3.0-1")
    parser.add_argument("--keep-stage", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9][A-Za-z0-9.+:~\-]*", args.version):
        raise SystemExit(f"非法 Debian 版本号：{args.version!r}")
    VERSION = args.version
    check_build_host()

    stage = Path(tempfile.mkdtemp(prefix="best-yolo-deb-"))
    print("Staging:", stage)
    try:
        copy_app(stage)
        vendor = stage / "opt/best-yolo/vendor"
        vendor.mkdir(parents=True, exist_ok=True)
        dists = dependency_closure(RUNTIME_DISTS)
        print(f"Vendoring {len(dists)} distributions:")
        total_files = 0
        for dist in dists:
            n = copy_distribution(dist, vendor)
            total_files += n
            print(f"  {dist.metadata['Name']} {dist.version}: {n} files")
        print(f"Vendored files: {total_files}")

        write_launcher(stage)
        write_desktop_files(stage)
        write_docs(stage, dists)
        write_debian_metadata(stage)
        normalize_permissions(stage)
        check_permissions(stage)
        normalize_mtimes(stage, 1_788_796_800)  # 2026-09-07 00:00:00 UTC

        output_dir = Path(args.output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"{PACKAGE}_{VERSION}_{ARCH}.deb"
        if output.exists():
            output.unlink()
        env = dict(os.environ)
        env["SOURCE_DATE_EPOCH"] = "1788796800"
        run(["dpkg-deb", "--root-owner-group", "-Zxz", "-z6",
             "--build", str(stage), str(output)], env=env)
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        checksum = output.with_name(output.name + ".sha256")
        checksum.write_text(f"{digest}  {output.name}\n", encoding="ascii")
        install_note = output_dir / "INSTALL-Ubuntu22.04-zh-CN.txt"
        install_note.write_text(textwrap.dedent(f'''\
            Best yolo {VERSION} 安装说明
            ================================

            适用系统：Ubuntu 22.04 LTS，x86_64 / amd64

            1. 把 {output.name} 放到目标电脑。
            2. 在文件所在目录打开终端，执行：

               sudo apt install ./{output.name}

               请使用 apt install，不要只用 dpkg -i；apt 会自动补齐 Ubuntu
               系统图形库。全新系统缺少依赖时需要能访问 Ubuntu 软件源。

            3. 安装完成后，在应用菜单搜索“Best yolo”，或运行：

               best-yolo

            4. 首次使用时新建项目，并填写使用者自己的 API Key。

            诊断运行环境：
               best-yolo --diagnose

            打开启动日志：
               best-yolo --show-log

            用户项目和 API 配置保存在：
               ~/.local/share/best-yolo

            日志保存在：
               ~/.local/state/best-yolo/start.log

            卸载软件：
               sudo apt remove best-yolo

            卸载不会删除用户项目和 API 配置。这个安装包是云端 API 版，
            不包含与显卡驱动绑定的 PyTorch、CUDA、本地模型和 YOLO 训练环境。

            SHA256：
               {digest}
        '''), encoding="utf-8")
        print(f"\nBuilt: {output}")
        print(f"Size: {output.stat().st_size / 1024 / 1024:.1f} MiB")
        print(f"SHA256: {digest}")
        print(f"Checksum: {checksum}")
        print(f"Install guide: {install_note}")
    finally:
        if args.keep_stage:
            print("Kept staging directory:", stage)
        else:
            shutil.rmtree(stage, ignore_errors=True)


if __name__ == "__main__":
    main()
