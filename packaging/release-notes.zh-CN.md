# Best yolo 首个公开版本

Best yolo 是一款面向 YOLO 数据集制作的桌面工具，支持 Qwen-VL 自动标注、人工精修、AI 补充提示词、视频抽帧和数据集导出。

## 安装

本页面提供适用于 **Ubuntu 22.04 x86_64 / amd64** 的安装包。下载 `.deb` 和同名 `.sha256` 文件后运行：

```bash
sha256sum -c best-yolo_*.deb.sha256
sudo apt install ./best-yolo_*_amd64.deb
```

安装完成后，在应用菜单搜索 **Best yolo**，或在终端运行 `best-yolo`。

## 下载文件

- `best-yolo_1.0.0-3_amd64.deb`：主安装包。
- `best-yolo_1.0.0-3_amd64.deb.sha256`：安装包完整性校验文件。
- `安装说明-Ubuntu22.04.txt`：离线查看的中文安装说明。

发布版使用用户自行配置的兼容 OpenAI 接口，不包含 API Key、项目图片、标签或个人路径。更多信息请查看仓库首页和安装文档。
