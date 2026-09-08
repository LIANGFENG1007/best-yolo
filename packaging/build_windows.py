#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 Windows x64 上构建独立运行的 Best yolo 安装程序。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import textwrap

from packaging.requirements import Requirement


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DISTS = (
    "PySide6-Essentials",
    "Pillow",
    "openai",
    "PyYAML",
    "opencv-python",
    "numpy",
)
EXCLUDES = (
    "accelerate",
    "matplotlib",
    "pandas",
    "PyQt5",
    "PyQt6",
    "qwen_vl_utils",
    "scipy",
    "tkinter",
    "torch",
    "torchvision",
    "transformers",
    "ultralytics",
)


def run(cmd, **kwargs):
    print("+", subprocess.list2cmdline([str(x) for x in cmd]), flush=True)
    return subprocess.run([str(x) for x in cmd], check=True, **kwargs)


def parse_version(value):
    value = (value or "").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError("Windows 发布版本必须是 X.Y.Z，例如 1.0.0")
    parts = tuple(int(x) for x in value.split("."))
    if any(x > 65535 for x in parts):
        raise ValueError("Windows 版本号的每一段不能超过 65535")
    return value, parts + (0,)


def check_host():
    if os.name != "nt":
        raise SystemExit("Windows 安装包必须在 Windows 上构建")
    if platform.machine().lower() not in ("amd64", "x86_64"):
        raise SystemExit("Windows 安装包必须在 x64 构建机上生成")
    if sys.version_info[:2] != (3, 10):
        raise SystemExit("Windows 安装包固定使用 Python 3.10 构建")
    for name in RUNTIME_DISTS:
        try:
            metadata.distribution(name)
        except metadata.PackageNotFoundError:
            raise SystemExit(f"构建环境缺少 {name}")


def find_iscc():
    configured = (os.environ.get("ISCC_PATH") or "").strip()
    candidates = [
        Path(configured) if configured else None,
        Path(shutil.which("ISCC.exe") or "") if shutil.which("ISCC.exe") else None,
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) /
        "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) /
        "Inno Setup 6" / "ISCC.exe",
    ]
    for path in candidates:
        if path and path.is_file():
            return path.resolve()
    raise SystemExit("找不到 Inno Setup 6 的 ISCC.exe")


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
    return [found[key] for key in sorted(found)]


def write_version_file(path, version, parts):
    a, b, c, d = parts
    body = f'''\
        VSVersionInfo(
          ffi=FixedFileInfo(
            filevers=({a}, {b}, {c}, {d}),
            prodvers=({a}, {b}, {c}, {d}),
            mask=0x3f,
            flags=0x0,
            OS=0x40004,
            fileType=0x1,
            subtype=0x0,
            date=(0, 0)),
          kids=[
            StringFileInfo([StringTable('080404B0', [
              StringStruct('CompanyName', 'LIANGFENG1007'),
              StringStruct('FileDescription', 'Best yolo 桌面标注工具'),
              StringStruct('FileVersion', '{version}'),
              StringStruct('InternalName', 'BestYolo'),
              StringStruct('LegalCopyright', 'Copyright (C) 2026 LIANGFENG1007'),
              StringStruct('OriginalFilename', 'BestYolo.exe'),
              StringStruct('ProductName', 'Best yolo'),
              StringStruct('ProductVersion', '{version}')
            ])]),
            VarFileInfo([VarStruct('Translation', [2052, 1200])])
          ])
    '''
    path.write_text(textwrap.dedent(body), encoding="utf-8")


def make_icon(path):
    from PIL import Image
    with Image.open(ROOT / "gui" / "icon.png") as source:
        image = source.convert("RGBA")
        image.save(path, format="ICO",
                   sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                          (64, 64), (128, 128), (256, 256)])


def pyinstaller_base(dist_dir, work_dir, spec_dir, icon, version_file):
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--noupx", "--log-level=WARN",
        f"--distpath={dist_dir}", f"--workpath={work_dir}",
        f"--specpath={spec_dir}", f"--paths={ROOT}", f"--paths={ROOT / 'gui'}",
        f"--icon={icon}", f"--version-file={version_file}",
    ]
    for name in EXCLUDES:
        cmd.append(f"--exclude-module={name}")
    return cmd


def build_frozen_apps(build_root, icon, version_file):
    dist_dir = build_root / "frozen"
    spec_dir = build_root / "spec"
    spec_dir.mkdir(parents=True, exist_ok=True)

    main_cmd = pyinstaller_base(
        dist_dir, build_root / "work-main", spec_dir, icon, version_file)
    main_cmd += [
        "--name=BestYolo", "--onedir", "--windowed", "--optimize=1",
        "--hidden-import=cv2",
        "--hidden-import=httpx",
        "--hidden-import=numpy",
        "--hidden-import=openai",
        "--hidden-import=PIL.Image",
        "--hidden-import=palette",
        "--hidden-import=yaml",
        "--collect-data=certifi",
        f"--add-data={ROOT / 'gui' / '_assets'}{os.pathsep}_assets",
        str(ROOT / "packaging" / "windows_entry.py"),
    ]
    run(main_cmd)

    worker_cmd = pyinstaller_base(
        dist_dir, build_root / "work-worker", spec_dir, icon, version_file)
    worker_cmd += [
        "--name=BestYoloWorker", "--onefile", "--console", "--optimize=1",
        "--hidden-import=autolabel_qwen",
        "--hidden-import=build_dataset",
        "--hidden-import=certifi",
        "--hidden-import=httpx",
        "--hidden-import=openai",
        "--hidden-import=palette",
        "--hidden-import=PIL.Image",
        "--hidden-import=yaml",
        "--collect-data=certifi",
        str(ROOT / "packaging" / "windows_worker.py"),
    ]
    run(worker_cmd)

    app_dir = dist_dir / "BestYolo"
    worker = dist_dir / "BestYoloWorker.exe"
    if not (app_dir / "BestYolo.exe").is_file() or not worker.is_file():
        raise RuntimeError("PyInstaller 没有生成预期的 Windows 程序")
    shutil.copy2(worker, app_dir / worker.name)
    return app_dir


def copy_licenses(app_dir):
    target = app_dir / "licenses"
    target.mkdir(parents=True, exist_ok=True)
    summary = ["Best yolo bundled third-party components", ""]
    for dist in dependency_closure(RUNTIME_DISTS):
        name = dist.metadata.get("Name") or "unknown"
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
        copied = 0
        for entry in dist.files or ():
            lower_parts = [part.lower() for part in entry.parts]
            filename = entry.name.lower()
            if not (any(part in ("license", "licenses") for part in lower_parts) or
                    filename.startswith(("license", "copying", "notice"))):
                continue
            source = Path(dist.locate_file(entry))
            if not source.is_file():
                continue
            relative = Path(*entry.parts[-2:]) if len(entry.parts) > 1 else Path(entry.name)
            destination = target / safe / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied += 1
        license_text = (dist.metadata.get("License-Expression") or
                        dist.metadata.get("License") or "see bundled metadata")
        summary.append(f"- {name} {dist.version}: {license_text} ({copied} license files)")

    python_candidates = [
        Path(sys.base_prefix) / "LICENSE.txt",
        Path(sys.executable).resolve().parent / "LICENSE.txt",
        Path(sys.base_prefix).parent / "LICENSE.txt",
    ]
    for source in python_candidates:
        if source.is_file():
            python_dir = target / "Python-3.10"
            python_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, python_dir / "LICENSE.txt")
            break
    (target / "THIRD_PARTY_LICENSES.txt").write_text(
        "\n".join(summary) + "\n", encoding="utf-8")


def write_install_guide(path, version, installer_name, digest):
    path.write_text(textwrap.dedent(f'''\
        Best yolo {version} Windows 安装说明
        ====================================

        适用系统：Windows 10 1809 或更高版本，Windows 11，64 位 x64

        1. 下载 {installer_name}。
        2. 可在 PowerShell 中核对 SHA256：

           (Get-FileHash .\\{installer_name} -Algorithm SHA256).Hash

           正确值：{digest.upper()}

        3. 双击安装程序，按向导选择安装目录。默认目录是：

           C:\\Program Files\\Best yolo

        4. 安装完成后，从开始菜单或桌面快捷方式启动 Best yolo。
        5. 首次使用时新建项目，并填写使用者自己的 API Key。

        安装包已经包含 Python、PySide6、OpenAI SDK、Pillow、OpenCV、NumPy、
        PyYAML 和 Microsoft Visual C++ 运行库，目标电脑无需预装开发环境。

        用户项目和 API 配置保存在：
           %LOCALAPPDATA%\\BestYolo

        卸载软件不会删除用户项目和 API 配置。

        当前安装程序未使用商业代码签名证书。Windows SmartScreen 可能显示
        “Windows 已保护你的电脑”；请先核对上面的 SHA256，再选择“更多信息”
        和“仍要运行”。
    '''), encoding="utf-8-sig")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True, help="版本号，例如 1.0.0")
    parser.add_argument("--output-dir", default=str(ROOT / "dist"))
    parser.add_argument("--vc-redist", required=True,
                        help="微软官方 VC_redist.x64.exe 的路径")
    parser.add_argument("--inno-chinese", required=True,
                        help="Inno Setup 官方 ChineseSimplified.isl 的路径")
    args = parser.parse_args()
    version, parts = parse_version(args.version)
    check_host()
    iscc = find_iscc()
    vc_redist = Path(args.vc_redist).resolve()
    if not vc_redist.is_file():
        raise SystemExit(f"找不到 VC++ 运行库安装程序: {vc_redist}")
    inno_chinese = Path(args.inno_chinese).resolve()
    if not inno_chinese.is_file():
        raise SystemExit(f"找不到 Inno Setup 简体中文语言文件: {inno_chinese}")

    build_root = ROOT / "build" / "windows"
    if build_root.exists():
        shutil.rmtree(build_root)
    build_root.mkdir(parents=True)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    icon = build_root / "best-yolo.ico"
    version_file = build_root / "version-info.txt"
    make_icon(icon)
    write_version_file(version_file, version, parts)
    app_dir = build_frozen_apps(build_root, icon, version_file)
    copy_licenses(app_dir)

    env = dict(os.environ)
    env.update({
        "BEST_YOLO_VERSION": version,
        "BEST_YOLO_SOURCE_DIR": str(app_dir),
        "BEST_YOLO_OUTPUT_DIR": str(output_dir),
        "BEST_YOLO_SETUP_ICON": str(icon),
        "BEST_YOLO_VC_REDIST": str(vc_redist),
        "BEST_YOLO_INNO_CHINESE": str(inno_chinese),
    })
    run([iscc, ROOT / "packaging" / "windows" / "installer.iss"], env=env)

    installer = output_dir / f"BestYolo-Setup-{version}-win64.exe"
    if not installer.is_file():
        raise RuntimeError(f"Inno Setup 没有生成 {installer.name}")
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    checksum = installer.with_name(installer.name + ".sha256")
    checksum.write_text(f"{digest}  {installer.name}\n", encoding="ascii")
    guide = output_dir / "INSTALL-Windows10-zh-CN.txt"
    write_install_guide(guide, version, installer.name, digest)
    print(f"Built: {installer}")
    print(f"Size: {installer.stat().st_size / 1024 / 1024:.1f} MiB")
    print(f"SHA256: {digest}")
    print(f"Guide: {guide}")


if __name__ == "__main__":
    main()
