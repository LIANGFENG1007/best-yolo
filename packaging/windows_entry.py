#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Best yolo Windows GUI 冻结入口。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import traceback


APP_DIR_NAME = "BestYolo"


def _source_paths():
    if getattr(sys, "frozen", False):
        return
    root = Path(__file__).resolve().parents[1]
    gui = root / "gui"
    for path in (str(gui), str(root)):
        if path not in sys.path:
            sys.path.insert(0, path)


def configure_environment():
    base = (os.environ.get("LOCALAPPDATA") or
            os.environ.get("APPDATA") or
            str(Path.home()))
    data_dir = Path(base) / APP_DIR_NAME
    os.environ.setdefault("BEST_YOLO_DATA_DIR", str(data_dir))
    os.environ.setdefault("BEST_YOLO_API_ONLY", "1")
    os.environ.setdefault("BEST_YOLO_READONLY_INSTALL", "1")
    os.environ.setdefault("PYTHONUTF8", "1")
    if getattr(sys, "frozen", False):
        worker = Path(sys.executable).with_name("BestYoloWorker.exe")
        os.environ.setdefault("BEST_YOLO_WORKER_EXE", str(worker))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def _diagnostics():
    import cv2
    import numpy
    import openai
    import PIL
    import PySide6
    import yaml

    worker = Path(os.environ.get("BEST_YOLO_WORKER_EXE", ""))
    return {
        "python": sys.version,
        "executable": sys.executable,
        "data_dir": os.environ["BEST_YOLO_DATA_DIR"],
        "worker": str(worker),
        "worker_exists": worker.is_file(),
        "PySide6": PySide6.__version__,
        "Pillow": PIL.__version__,
        "OpenAI": openai.__version__,
        "OpenCV": cv2.__version__,
        "NumPy": numpy.__version__,
        "PyYAML": yaml.__version__,
    }


def _write_json(path, data):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                      encoding="utf-8")


def _smoke_test(output):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    import app as gui_app

    qt_app = QApplication.instance() or QApplication([])
    qt_app.setApplicationName("Best yolo")
    qt_app.setStyle("Fusion")
    gui_app.apply_palette(qt_app)
    qt_app.setStyleSheet(gui_app.stylesheet())
    window = gui_app.MainWindow()
    qt_app.processEvents()
    result = _diagnostics()
    result.update({
        "pages": window.pages.count(),
        "window_title": window.windowTitle(),
        "smoke_ok": window.pages.count() == 5 and window.windowTitle() == "Best yolo",
    })
    _write_json(output, result)
    window.close()
    qt_app.processEvents()
    return 0 if result["smoke_ok"] and result["worker_exists"] else 1


def _show_path(path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch(exist_ok=True)
    os.startfile(str(target))


def _message_box(title, text):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(text), str(title), 0x10)
    except Exception:
        pass


def main():
    _source_paths()
    data_dir = configure_environment()
    args = sys.argv[1:]
    if args[:1] == ["--smoke-test"]:
        if len(args) != 2:
            raise SystemExit("--smoke-test 需要输出 JSON 路径")
        return _smoke_test(args[1])
    if args[:1] == ["--diagnose-output"]:
        if len(args) != 2:
            raise SystemExit("--diagnose-output 需要输出 JSON 路径")
        _write_json(args[1], _diagnostics())
        return 0
    if args[:1] == ["--diagnose"]:
        output = data_dir / "diagnostics.json"
        _write_json(output, _diagnostics())
        _show_path(output)
        return 0
    if args[:1] == ["--show-log"]:
        _show_path(data_dir / "logs" / "start.log")
        return 0

    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "start.log"
    with log_path.open("a", encoding="utf-8", buffering=1) as log:
        sys.stdout = log
        sys.stderr = log
        import app as gui_app
        gui_app.main()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:
        data = configure_environment()
        log_dir = data / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "start.log").open("a", encoding="utf-8") as log:
            log.write("\nWindows launcher fatal error\n")
            traceback.print_exc(file=log)
        if "--smoke-test" not in sys.argv and "--diagnose-output" not in sys.argv:
            _message_box("Best yolo", "程序启动失败，请查看：\n" + str(log_dir / "start.log"))
        raise
