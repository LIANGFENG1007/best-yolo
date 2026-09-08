<div align="center">
  <img src="docs/images/logo.png" width="104" alt="Best yolo logo">
  <h1>Best yolo</h1>
  <p><strong>从图片或视频到 YOLO 数据集的一站式桌面标注工作台</strong></p>
  <p>Qwen-VL 自动打框 · 人工精修 · AI 反推提示词 · 视频抽帧 · 数据集导出</p>

  [![CI](https://github.com/LIANGFENG1007/best-yolo/actions/workflows/ci.yml/badge.svg)](https://github.com/LIANGFENG1007/best-yolo/actions/workflows/ci.yml)
  [![Release](https://img.shields.io/github/v/release/LIANGFENG1007/best-yolo?display_name=tag&sort=semver)](https://github.com/LIANGFENG1007/best-yolo/releases/latest)
  ![Windows 10+](https://img.shields.io/badge/Windows-10%2F11-0078D4?logo=windows&logoColor=white)
  ![Ubuntu 22.04](https://img.shields.io/badge/Ubuntu-22.04-E95420?logo=ubuntu&logoColor=white)
  ![Architecture](https://img.shields.io/badge/architecture-x64-4A9EFF)
  ![Python](https://img.shields.io/badge/Python-3.10-3776AB?logo=python&logoColor=white)

  [下载最新版](https://github.com/LIANGFENG1007/best-yolo/releases/latest) ·
  [版本目录](docs/releases.md) ·
  [安装文档](docs/installation.md) ·
  [English](README.en.md)
</div>

![Best yolo overview](docs/images/banner.png)

## 它解决什么问题

视觉模型能快速产生第一版检测框，但真正可训练的数据集还需要检查漏标、误标、类别串标、坐标偏移和负样本。Best yolo 把这条流程放进一个桌面应用：先用兼容 OpenAI 接口的 Qwen-VL 模型批量标注，再直接在原图上修框，最后导出标准 YOLO 数据集。

## 核心能力

| 板块 | 能力 |
|---|---|
| 自动标注 | 预览小批量后再跑全量；支持并发、QPS、重试、切片检测和坐标口径检查 |
| 人工标注 | 新建、移动、缩放、改类、删除框；撤销/重做、自动保存、图片锁定和缩放平移 |
| AI 补充提示词 | 对比“AI 原始版”和人工修订版，逐图分析后生成可选择采纳的类别描述建议 |
| 视频切片 | 可视化选择时间区间，按时间间隔抽帧，支持续编序号和缩略图检查 |
| 数据集导出 | 配对图片与标签，稳定切分 train/val，生成 `data.yaml` 和 `classes.txt` |
| 快捷键 | 79 个命令可配置，按页面分组，支持主/备用按键、包含搜索和冲突检查 |
| 更新检查 | 每个新版本首次发现时自动提示一次；按钮和备用链接可直接交给系统默认浏览器打开 |
| 界面配色 | 8 套一键主题；可分别调整界面、侧栏、面板、输入区、文字和按钮颜色 |

<table>
  <tr>
    <td width="50%"><img src="docs/images/annotation.png" alt="人工标注"></td>
    <td width="50%"><img src="docs/images/prompt.png" alt="AI 补充提示词"></td>
  </tr>
  <tr>
    <td align="center">在原图上精修 YOLO 框</td>
    <td align="center">从人工修订反推提示词</td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/images/shortcuts.png" alt="快捷键设置"></td>
    <td width="50%"><img src="docs/images/video.png" alt="视频切片"></td>
  </tr>
  <tr>
    <td align="center">按功能板块管理快捷键</td>
    <td align="center">选区间并批量抽帧</td>
  </tr>
</table>

## 个性化配色

点击左下角的彩色调色盘即可打开配色设置。内置经典黑、经典白、流金黑、玫瑰红、极光蓝、翡翠绿、冰川青和暮光紫 8 套一键主题；自定义模式提供圆形全色调色盘、亮度滑条、十六进制颜色值和推荐色。主要文字、次要文字与按钮强调色可以分别设置，成功、警告、删除、停止和更新提示等语义颜色会按背景自动调整可读性。配色保存后立即生效，并在下次启动时自动恢复。

![Best yolo 界面配色设置](docs/images/themes.png)

<table>
  <tr>
    <td width="50%"><img src="docs/images/theme-classic-white.png" alt="经典白主题"></td>
    <td width="50%"><img src="docs/images/theme-black-gold.png" alt="流金黑主题"></td>
  </tr>
  <tr>
    <td align="center">经典白</td>
    <td align="center">流金黑</td>
  </tr>
</table>

## 下载安装

所有安装包都在 [Releases](https://github.com/LIANGFENG1007/best-yolo/releases/latest)。发布版是云端 API 版，使用者填写自己的 API Key；安装包不包含任何账号凭据、项目图片或标签。

### Windows 10 / 11 x64

下载 `BestYolo-Setup-*-win64.exe` 后双击安装。安装向导允许选择安装目录，默认是 `C:\Program Files\Best yolo`，也可以创建桌面快捷方式。

安装包内置 Python、PySide6、OpenAI SDK、Pillow、OpenCV、NumPy、PyYAML 和微软 VC++ 运行库，全新的 64 位 Windows 10 1809+ 或 Windows 11 无需预装开发环境。当前安装程序没有商业代码签名证书；若 SmartScreen 提示未知发布者，请先用同名 `.sha256` 文件核对下载完整性。详细步骤见 [安装文档](docs/installation.md)。

### Ubuntu 22.04 x86_64

下载最新的 `amd64.deb`，然后在下载目录运行：

```bash
sudo apt install ./best-yolo_*_amd64.deb
```

安装完成后在应用菜单搜索 **Best yolo**，或运行：

```bash
best-yolo
```

Ubuntu 安装包内置 Python 运行依赖；首次安装缺少系统图形库时，`apt` 会从 Ubuntu 软件源补齐。

## 工作流程

```mermaid
flowchart LR
    A[图片目录] --> B[预览标注]
    V[视频] --> F[区间抽帧]
    F --> A
    B --> C{检查结果}
    C -->|调整描述| B
    C -->|人工修框| D[锁定正确标签]
    D --> P[AI 分析修订]
    P --> B
    D --> E[导出 YOLO 数据集]
```

## 数据与隐私

- Release 不包含任何 API Key、项目图片、标签或个人路径。
- API Key 只保存在当前用户目录：Windows 为 `%LOCALAPPDATA%\BestYolo`，Ubuntu 为 `~/.local/share/best-yolo`。
- 只有用户主动开始云端标注或提示词分析时，选中的图片才会发送到所配置的 API 接入点。
- 卸载软件不会删除用户项目；完整说明见 [隐私与数据](docs/privacy.md)。

## 从源码运行

```bash
git clone git@github.com:LIANGFENG1007/best-yolo.git
cd best-yolo
./scripts/bootstrap.sh
./scripts/run-dev.sh
```

本地 Qwen-VL 后端和 YOLO 训练是可选组件，分别参见 [开发文档](docs/development.md)。

## 系统诊断

```bash
best-yolo --diagnose
best-yolo --show-log
```

常见问题见 [故障排查](docs/troubleshooting.md)。提交问题前请删除日志中的接入点和文件路径，不要上传 `.gui_state.json`。

## 项目状态

当前 Release 提供 Windows 10/11 x64 安装程序和 Ubuntu 22.04 amd64 安装包。PyTorch、CUDA、本地模型权重和训练环境与显卡及驱动强绑定，因此不塞进通用安装包；源码仍保留这些可选入口。

## 许可证

当前仓库尚未附加开源许可证。源码公开用于查看和个人评估；这不自动授予复制、修改或重新分发源码的权利。Release 二进制可供下载安装。正式开源授权将在后续版本中单独确定。
