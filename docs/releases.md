# 版本目录

这里集中列出 Best yolo 的公开版本、主要变化和各平台安装包。一般用户应选择最上方的最新稳定版。

## [v1.3.0](https://github.com/LIANGFENG1007/best-yolo/releases/tag/v1.3.0) - 2026-09-08

新增完整的界面配色系统与 8 套一键主题。

[查看本版本的完整发布说明](release-notes/v1.3.0.md)

### 新增功能

- 左下角新增彩色调色盘按钮，可随时打开界面配色设置。
- 提供经典黑、经典白、流金黑、玫瑰红、极光蓝、翡翠绿、冰川青和暮光紫 8 套一键主题。
- 支持分别设置界面底色、侧边栏、面板、输入区域、主要文字、次要文字和按钮强调色。
- 自定义调色包含圆形 HSV 全色调色盘、亮度滑条、十六进制输入和分类推荐色。
- 配色立即生效并自动保存；“打开界面配色”可在快捷键设置中修改，默认 `Ctrl+Alt+T`。

### 修复内容

- 浅色主题会完整适配输入框、表格、日志、滚动条和状态栏，不残留固定深色区域。
- 自定义按钮色会自动选择高对比度文字。
- 成功、警告、错误、删除、停止和更新提醒保留功能语义，并根据背景生成合适的颜色。
- 切换主题时同步更新已经显示的状态文字与表格颜色。

### Windows 10 / 11 x64

- [下载安装程序](https://github.com/LIANGFENG1007/best-yolo/releases/download/v1.3.0/BestYolo-Setup-1.3.0-win64.exe)
- [SHA256 校验文件](https://github.com/LIANGFENG1007/best-yolo/releases/download/v1.3.0/BestYolo-Setup-1.3.0-win64.exe.sha256)
- [中文安装说明](https://github.com/LIANGFENG1007/best-yolo/releases/download/v1.3.0/INSTALL-Windows10-zh-CN.txt)

### Ubuntu 22.04 amd64

- [下载 Debian 安装包](https://github.com/LIANGFENG1007/best-yolo/releases/download/v1.3.0/best-yolo_1.3.0-1_amd64.deb)
- [SHA256 校验文件](https://github.com/LIANGFENG1007/best-yolo/releases/download/v1.3.0/best-yolo_1.3.0-1_amd64.deb.sha256)
- [中文安装说明](https://github.com/LIANGFENG1007/best-yolo/releases/download/v1.3.0/INSTALL-Ubuntu22.04-zh-CN.txt)

## [v1.1.0](https://github.com/LIANGFENG1007/best-yolo/releases/tag/v1.1.0) - 2026-09-08

新增启动更新检查与左上角更新提醒。

[查看本版本的完整发布说明](release-notes/v1.1.0.md)

### 新增功能

- 启动后后台静默检查 GitHub 最新稳定版，不阻塞主界面。
- 没有新版本时显示蓝色“检测更新”，发现新版本时显示红色“发现更新”。
- 更新弹窗显示版本号和完整更新内容，并可前往对应 GitHub Release。
- 支持手动重新检测版本。
- 可在快捷键设置中修改“检测软件更新”，默认按键为 `Ctrl+Alt+U`。

### 修复内容

- 断网或 GitHub 不可达时不再影响启动，也不会自动弹出错误。
- 点击发布页前会检测连通性，无网络时明确提示。
- 修复部分功能弹窗可能无法打开的潜在问题。

### Windows 10 / 11 x64

- [下载安装程序](https://github.com/LIANGFENG1007/best-yolo/releases/download/v1.1.0/BestYolo-Setup-1.1.0-win64.exe)
- [SHA256 校验文件](https://github.com/LIANGFENG1007/best-yolo/releases/download/v1.1.0/BestYolo-Setup-1.1.0-win64.exe.sha256)
- [中文安装说明](https://github.com/LIANGFENG1007/best-yolo/releases/download/v1.1.0/INSTALL-Windows10-zh-CN.txt)

### Ubuntu 22.04 amd64

- [下载 Debian 安装包](https://github.com/LIANGFENG1007/best-yolo/releases/download/v1.1.0/best-yolo_1.1.0-1_amd64.deb)
- [SHA256 校验文件](https://github.com/LIANGFENG1007/best-yolo/releases/download/v1.1.0/best-yolo_1.1.0-1_amd64.deb.sha256)
- [中文安装说明](https://github.com/LIANGFENG1007/best-yolo/releases/download/v1.1.0/INSTALL-Ubuntu22.04-zh-CN.txt)

## [v1.0.0](https://github.com/LIANGFENG1007/best-yolo/releases/tag/v1.0.0) - 2026-09-08

首个公开稳定版本。

[查看本版本的完整发布说明](release-notes/v1.0.0.md)

### 新增功能

- Qwen-VL 云端批量自动标注，支持预览、并发、QPS、重试、切片检测和跳过已完成图片。
- 在原图上新建、移动、缩放、改类和删除 YOLO 框，支持撤销、重做、自动保存与图片锁定。
- AI 对比原始标注和人工修订结果，生成可以逐条确认的提示词补充建议。
- 视频时间区间预览与批量抽帧。
- 稳定切分 train/val，并导出 `data.yaml` 与 `classes.txt`。
- 77 个功能命令的可搜索、自定义快捷键设置。
- Windows 10/11 x64 与 Ubuntu 22.04 amd64 安装包。

### 修复内容

- 修复 AI 补充提示词页面右侧无法滚动、底部内容被遮挡的问题。
- 修复模型输入框不能按部分名称筛选下拉列表的问题。
- 修复 Debian 安装后普通用户无权读取程序文件的问题。
- 修复 API Key 被重复写入项目配置以及可能被空值覆盖的问题。
- 修复空标签负样本会被重复调用 API 的问题。
- 修复非零类别在提示词分析中可能映射错误的问题。
- 修复 Windows 冻结版无法启动后台标注脚本和中文类别导出编码的问题。

### Windows 10 / 11 x64

- [下载安装程序](https://github.com/LIANGFENG1007/best-yolo/releases/download/v1.0.0/BestYolo-Setup-1.0.0-win64.exe)
- [SHA256 校验文件](https://github.com/LIANGFENG1007/best-yolo/releases/download/v1.0.0/BestYolo-Setup-1.0.0-win64.exe.sha256)
- [中文安装说明](https://github.com/LIANGFENG1007/best-yolo/releases/download/v1.0.0/INSTALL-Windows10-zh-CN.txt)

### Ubuntu 22.04 amd64

- [下载 Debian 安装包](https://github.com/LIANGFENG1007/best-yolo/releases/download/v1.0.0/best-yolo_1.0.0-4_amd64.deb)
- [SHA256 校验文件](https://github.com/LIANGFENG1007/best-yolo/releases/download/v1.0.0/best-yolo_1.0.0-4_amd64.deb.sha256)
- [中文安装说明](https://github.com/LIANGFENG1007/best-yolo/releases/download/v1.0.0/INSTALL-Ubuntu22.04-zh-CN.txt)

完整源代码也可以从对应 Release 页面底部下载。安装前建议用同名 `.sha256` 文件核对安装包。
