#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows 安装版的标注与数据集后台任务入口。"""
from __future__ import annotations

from pathlib import Path
import json
import os
import sys


def _source_paths():
    if getattr(sys, "frozen", False):
        return
    root = Path(__file__).resolve().parents[1]
    gui = root / "gui"
    for path in (str(gui), str(root)):
        if path not in sys.path:
            sys.path.insert(0, path)


def _utf8_streams():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            pass


def main():
    _source_paths()
    _utf8_streams()
    os.environ.setdefault("BEST_YOLO_API_ONLY", "1")
    if len(sys.argv) < 2:
        raise SystemExit("用法: BestYoloWorker.exe label|dataset [参数]")
    mode, rest = sys.argv[1], sys.argv[2:]
    if mode == "self-test":
        import openai
        import PIL
        import yaml
        print(json.dumps({
            "ok": True,
            "python": sys.version,
            "Pillow": PIL.__version__,
            "OpenAI": openai.__version__,
            "PyYAML": yaml.__version__,
        }, ensure_ascii=False))
        return 0
    if mode == "label":
        import autolabel_qwen
        sys.argv = ["autolabel_qwen.py"] + rest
        autolabel_qwen.main()
        return 0
    if mode == "dataset":
        import build_dataset
        sys.argv = ["build_dataset.py"] + rest
        build_dataset.main()
        return 0
    raise SystemExit(f"未知后台任务: {mode}")


if __name__ == "__main__":
    raise SystemExit(main())
