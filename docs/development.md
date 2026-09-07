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
./.venv/bin/python packaging/build_deb.py --version 1.1.0-1
```

构建器使用白名单复制源码，递归计算锁定依赖，规范化权限和时间戳，生成 SHA256 与中文安装说明。输出在 `dist/`，不会进入 Git；标签发布工作流会把它上传到 GitHub Releases。
