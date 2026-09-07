# 安装与升级

## 支持范围

- Ubuntu 22.04 LTS
- x86_64 / amd64
- X11 或 Wayland 桌面会话
- 云端视觉模型使用者自己的 API Key 和兼容 OpenAI 的接入点

## 安装

下载 Release 中版本号最高的 `.deb` 和同名 `.sha256` 文件：

```bash
sha256sum -c best-yolo_*.deb.sha256
sudo apt install ./best-yolo_*_amd64.deb
```

使用 `apt install` 可以自动补齐 Ubuntu 图形库。只运行 `dpkg -i` 可能留下未满足的依赖。

## 首次启动

1. 在应用菜单打开 **Best yolo**。
2. 新建项目。
3. 选择图片目录并导入或填写类别表。
4. 在首页设置自己的 API Key 和接入点。
5. 先运行少量预览，确认类别和坐标后再运行全部。

## 升级

下载新版本后再次执行：

```bash
sudo apt install ./best-yolo_新版本_amd64.deb
```

升级不会覆盖 `~/.local/share/best-yolo` 下的项目。

## 卸载

```bash
sudo apt remove best-yolo
```

用户数据会保留。确认不再需要后，可自行删除：

```bash
rm -r ~/.local/share/best-yolo ~/.local/state/best-yolo
```
