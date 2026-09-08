# 安装与升级

## 支持范围

- Windows 10 1809 或更高版本、Windows 11，64 位 x64
- Ubuntu 22.04 LTS
- x86_64 / amd64 架构
- X11 或 Wayland 桌面会话
- 云端视觉模型使用者自己的 API Key 和兼容 OpenAI 的接入点

## Windows 安装

下载 Release 中版本号最高的三个 Windows 文件：

- `BestYolo-Setup-版本-win64.exe`
- `BestYolo-Setup-版本-win64.exe.sha256`
- `INSTALL-Windows10-zh-CN.txt`

在 PowerShell 中核对安装程序：

```powershell
(Get-FileHash .\BestYolo-Setup-*-win64.exe -Algorithm SHA256).Hash
Get-Content .\BestYolo-Setup-*-win64.exe.sha256
```

两个哈希值应完全相同。双击 `.exe` 后按向导安装，安装位置页面会始终显示；默认目录是 `C:\Program Files\Best yolo`，可以改到其他位置。安装过程需要管理员权限，因为安装包会补齐微软 VC++ 运行库。

安装包已包含 Python 3.10、PySide6、OpenAI SDK、Pillow、OpenCV、NumPy 和 PyYAML，全新系统无需另外安装 Python。软件运行云端标注时仍需要网络。

当前安装程序没有商业代码签名证书，SmartScreen 可能显示“Windows 已保护你的电脑”。确认 SHA256 正确后，可选择“更多信息”与“仍要运行”。

Windows 用户数据保存在 `%LOCALAPPDATA%\BestYolo`。从 Windows“已安装的应用”卸载软件不会删除项目和 API 配置。

## Ubuntu 安装

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

## Ubuntu 升级

下载新版本后再次执行：

```bash
sudo apt install ./best-yolo_新版本_amd64.deb
```

升级不会覆盖 `~/.local/share/best-yolo` 下的项目。

## Ubuntu 卸载

```bash
sudo apt remove best-yolo
```

用户数据会保留。确认不再需要后，可自行删除：

```bash
rm -r ~/.local/share/best-yolo ~/.local/state/best-yolo
```
