# 故障排查

## 一键诊断

Windows：从开始菜单启动软件；启动错误记录在 `%LOCALAPPDATA%\BestYolo\logs\start.log`。也可以运行：

```powershell
& "C:\Program Files\Best yolo\BestYolo.exe" --diagnose
```

Ubuntu：

```bash
best-yolo --diagnose
best-yolo --show-log
```

## Windows SmartScreen 提示未知发布者

当前安装程序没有商业代码签名证书。先把安装程序的 `Get-FileHash` 结果与 Release 中同名 `.sha256` 文件对比；一致后选择“更多信息”和“仍要运行”。不要从第三方网盘下载安装包。

## Windows 安装后无法启动

确认系统是 64 位 Windows 10 1809+ 或 Windows 11，并查看 `%LOCALAPPDATA%\BestYolo\logs\start.log`。安装器内置 Python、Qt、OpenCV 和微软 VC++ 运行库，不需要另装 Python。

## 检测更新显示“没有网络”

更新检查访问 GitHub。如果当前网络无法访问 GitHub，软件仍可正常使用自动标注、人工修框和数据集导出。开启可用的网络连接后，再点击左上角蓝色“检测更新”。

## 无法启动或提示 Permission denied

确认安装版本不是早期的 `1.0.0-1`：

```bash
dpkg-query -W -f='${Version}\n' best-yolo
sudo apt install ./best-yolo_最新版本_amd64.deb
```

## Qt xcb 插件错误

使用 `apt install` 安装 `.deb`，不要只用 `dpkg -i`。也可修复依赖：

```bash
sudo apt --fix-broken install
```

## 模型列表获取失败

专属接入点可能不实现 `/models`，但仍能调用视觉模型。可以直接在可搜索下拉框中输入模型 ID。401 表示 Key 错误，403 表示权限不足，404 通常表示接入点不提供模型枚举。

## 框挤在角落或占满整图

把“高级选项 → 坐标口径”恢复为“自动判定”，再运行少量预览。不要在不确定时强制选择像素、0–1000 或 0–1。

## 429 限流

降低并发数或设置较小 QPS，例如并发 4、每秒 2 次。保持“跳过已标好的图”开启，重跑时只处理失败项；合法的空标签负样本也会被跳过。

## Issue 中可以附什么

可以附诊断输出和经过检查的日志片段。请先删除 API 接入点、用户名和本地路径；绝对不要上传 `.gui_state.json`。
