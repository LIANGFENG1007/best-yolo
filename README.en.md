<div align="center">
  <img src="docs/images/logo.png" width="104" alt="Best yolo logo">
  <h1>Best yolo</h1>
  <p><strong>A desktop workflow from images or video to a reviewed YOLO dataset.</strong></p>

  [![CI](https://github.com/LIANGFENG1007/best-yolo/actions/workflows/ci.yml/badge.svg)](https://github.com/LIANGFENG1007/best-yolo/actions/workflows/ci.yml)
  [![Release](https://img.shields.io/github/v/release/LIANGFENG1007/best-yolo)](https://github.com/LIANGFENG1007/best-yolo/releases/latest)
  ![Windows 10+](https://img.shields.io/badge/Windows-10%2F11-0078D4?logo=windows&logoColor=white)
  ![Ubuntu 22.04](https://img.shields.io/badge/Ubuntu-22.04-E95420?logo=ubuntu&logoColor=white)

  [Download](https://github.com/LIANGFENG1007/best-yolo/releases/latest) ·
  [Version archive](docs/releases.md) ·
  [中文](README.md)
</div>

![Best yolo overview](docs/images/banner.png)

Best yolo combines Qwen-VL assisted auto-labeling, manual bounding-box correction, prompt refinement from human edits, video frame extraction, and YOLO dataset export in one PySide6 desktop app.

## Highlights

- Preview a small batch before paying for a full API run.
- Rate limiting, retries, tiled detection, coordinate validation, and failed-image recovery.
- Edit normalized YOLO boxes directly on the original image with undo/redo and image locks.
- Compare the AI baseline with human corrections and selectively apply prompt suggestions.
- Extract a selected video interval and export deterministic train/validation splits.
- Configure 78 commands through a searchable shortcut editor.
- Check for new stable releases in the background and review release notes before opening GitHub.

## Windows 10 / 11 x64

Download `BestYolo-Setup-*-win64.exe` from [Releases](https://github.com/LIANGFENG1007/best-yolo/releases/latest) and run the installer. You can select the installation directory. Python, Qt, OpenCV, the Microsoft Visual C++ runtime, and all other runtime dependencies are included. Windows 10 version 1809 or newer is required.

The installer is currently unsigned, so Microsoft SmartScreen may show an unknown-publisher warning. Verify the download against the accompanying `.sha256` file before running it.

## Ubuntu 22.04 amd64

Download the `.deb` from [Releases](https://github.com/LIANGFENG1007/best-yolo/releases/latest), then run:

```bash
sudo apt install ./best-yolo_*_amd64.deb
```

Launch **Best yolo** from the application menu. The release bundles its Python runtime dependencies. Access to Ubuntu repositories may be required to install missing system GUI libraries.

Both public installers are the cloud API edition. GPU-specific PyTorch, CUDA, local model weights, and training dependencies remain optional source installations. See [development](docs/development.md), [privacy](docs/privacy.md), and [troubleshooting](docs/troubleshooting.md).

## License status

No open-source license has been granted yet. The source is visible for inspection and personal evaluation; redistribution and modification rights are reserved until a license is selected.
