# 开发与构建

## 云端 API 开发环境

```bash
./scripts/bootstrap.sh
./scripts/run-dev.sh
```

开发数据默认写入 `.dev-data/`，不会进入 Git。

## 测试

```bash
./.venv/bin/python -B gui/test_gui.py
QT_QPA_PLATFORM=offscreen ./.venv/bin/python -B gui/test_shortcuts.py
QT_QPA_PLATFORM=offscreen ./.venv/bin/python -B gui/test_video_layout.py
```

## 本地 GPU 后端

先根据 NVIDIA 驱动安装匹配的 PyTorch，再运行：

```bash
./.venv/bin/pip install -r requirements-local.txt
```

本地模型权重不会进入仓库或 Release。

## YOLO 训练助手

```bash
./.venv/bin/pip install -r requirements-train.txt
```

## 构建 Ubuntu `.deb`

构建机必须是 Ubuntu 22.04 amd64、Python 3.10：

```bash
./.venv/bin/python packaging/build_deb.py --version 1.3.2-1
```

构建器使用白名单复制源码，递归计算锁定依赖，规范化权限和时间戳，生成 SHA256 与中文安装说明。输出在 `dist/`，不会进入 Git；标签发布工作流会把它上传到 GitHub Releases。

## 构建 Windows 安装程序

Windows 构建固定使用 Windows Server 2022 x64、Python 3.10、PyInstaller 与 Inno Setup 6。GitHub Release 工作流会执行完整构建；本机复现时先安装两个锁文件中的依赖，并准备微软官方 `VC_redist.x64.exe`：

```powershell
python -m pip install -r packaging/requirements-deb.lock -r packaging/requirements-windows-build.lock
python packaging/build_windows.py --version 1.0.0 --vc-redist C:\path\to\VC_redist.x64.exe --inno-chinese C:\path\to\ChineseSimplified.isl
```

Windows 构建包含无控制台 GUI 和独立后台任务程序。CI 会把安装器装进自定义临时目录，运行真实 Qt 界面与中文类别导出，再卸载并确认用户数据仍在。

## 发布新版本

1. 在 `CHANGELOG.md` 中按“新增功能 / 修复内容”记录版本变化。
2. 在 `docs/releases.md` 顶部加入该版本及各平台下载地址。
3. 从 `docs/release-notes/TEMPLATE.md` 新建 `docs/release-notes/vX.Y.Z.md`。
4. 推送 `vX.Y.Z` 标签。工作流会分别构建 Windows 和 Ubuntu；两边全部通过后才更新 Release。

缺少对应版本发布说明时，工作流会拒绝发布，避免下载页出现旧版本文案。
