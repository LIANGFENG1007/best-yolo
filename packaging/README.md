# Ubuntu 22.04 amd64 Debian package

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
