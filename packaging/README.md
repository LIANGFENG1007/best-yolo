# 发布安装包

## Ubuntu 22.04 amd64

Build on Ubuntu 22.04 x86_64 with the project virtual environment:

```bash
./.venv/bin/python packaging/build_deb.py
```

The result is written to `dist/best-yolo_<version>_amd64.deb`.

Install on Ubuntu 22.04:

```bash
sudo apt install ./best-yolo_*_amd64.deb
```

Run from the application menu or with `best-yolo`. Use
`best-yolo --diagnose` to verify the bundled runtime.

The package is deliberately API-only. PyTorch, CUDA, local model weights and the
YOLO training stack are hardware-specific and are not suitable for a portable
Ubuntu package. User data is stored below `~/.local/share/best-yolo` and remains
after package removal.

## Windows 10 / 11 x64

Build on 64-bit Windows with Python 3.10, PyInstaller 6 and Inno Setup 6:

```powershell
python -m pip install -r packaging/requirements-deb.lock -r packaging/requirements-windows-build.lock
python packaging/build_windows.py --version 1.0.0 --vc-redist C:\path\to\VC_redist.x64.exe --inno-chinese C:\path\to\ChineseSimplified.isl
```

The result is `dist/BestYolo-Setup-<version>-win64.exe`. The installer always
shows the destination-directory page and bundles the Microsoft Visual C++ x64
runtime for clean Windows installations. User data remains under
`%LOCALAPPDATA%\BestYolo` after uninstall.
