#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render sanitized product screenshots for the public README."""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("BEST_YOLO_API_ONLY", "1")
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/images"
OUT.mkdir(parents=True, exist_ok=True)


def make_demo(data_root):
    from PIL import Image, ImageDraw, ImageFont

    images = data_root / "demo-images"
    labels = data_root / "projects" / "Demo" / "out" / "labels"
    images.mkdir(parents=True)
    labels.mkdir(parents=True)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 24)
    except Exception:
        font = ImageFont.load_default()

    for i in range(8):
        im = Image.new("RGB", (960, 640), (38, 42, 48))
        d = ImageDraw.Draw(im)
        d.rectangle((0, 410, 960, 640), fill=(91, 76, 63))
        d.rectangle((0, 0, 960, 74), fill=(26, 29, 34))
        d.text((28, 22), f"DEMO FRAME {i + 1:02d}", font=font,
               fill=(225, 229, 235))

        # bottle
        bx = 125 + i * 12
        d.rounded_rectangle((bx, 205, bx + 120, 490), radius=26,
                            fill=(65, 147, 220), outline=(158, 211, 255), width=5)
        d.rectangle((bx + 36, 160, bx + 84, 220), fill=(50, 116, 178))
        # helmet
        hx = 410 - i * 7
        d.pieslice((hx, 230, hx + 240, 470), 180, 360,
                   fill=(238, 180, 46), outline=(255, 222, 126), width=5)
        d.rectangle((hx + 15, 345, hx + 225, 430), fill=(238, 180, 46))
        # parcel
        px = 690
        d.rounded_rectangle((px, 265 + i * 3, px + 190, 475 + i * 3), radius=8,
                            fill=(178, 119, 72), outline=(235, 186, 135), width=5)
        d.line((px + 95, 270 + i * 3, px + 95, 470 + i * 3),
               fill=(98, 69, 48), width=8)
        im.save(images / f"demo_{i + 1:02d}.jpg", quality=91)

        boxes = [
            (0, (bx + 60) / 960, 325 / 640, 120 / 960, 330 / 640),
            (1, (hx + 120) / 960, 350 / 640, 240 / 960, 240 / 640),
            (2, (px + 95) / 960, (370 + i * 3) / 640, 190 / 960, 210 / 640),
        ]
        body = "\n".join(
            f"{cid} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}"
            for cid, xc, yc, w, h in boxes)
        (labels / f"demo_{i + 1:02d}.txt").write_text(body + "\n")
    return images


def optimize_png(path):
    from PIL import Image
    with Image.open(path) as im:
        im.save(path, optimize=True)


def make_banner():
    from PIL import Image, ImageDraw, ImageFont
    canvas = Image.new("RGB", (1600, 640), (24, 26, 29))
    shot = Image.open(OUT / "annotation.png").convert("RGB")
    shot.thumbnail((1020, 574), Image.Resampling.LANCZOS)
    canvas.paste(shot, (550, 33))
    icon = Image.open(OUT / "logo.png").convert("RGBA")
    icon.thumbnail((118, 118), Image.Resampling.LANCZOS)
    canvas.paste(icon, (74, 74), icon)
    try:
        bold = ImageFont.truetype(
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 66)
        regular = ImageFont.truetype(
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 28)
        small = ImageFont.truetype(
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 22)
    except Exception:
        bold = regular = small = ImageFont.load_default()
    d = ImageDraw.Draw(canvas)
    d.text((74, 225), "Best yolo", font=bold, fill=(239, 241, 244))
    d.text((77, 320), "Qwen-VL 辅助的 YOLO 标注工作台", font=regular,
           fill=(145, 184, 230))
    lines = ("自动标注  ·  人工精修", "提示词优化  ·  视频抽帧",
             "Windows 10/11  ·  Ubuntu 22.04")
    for n, text in enumerate(lines):
        d.text((78, 395 + n * 42), text, font=small, fill=(174, 178, 185))
    canvas.save(OUT / "banner.png", optimize=True)


def main():
    data_root = Path(tempfile.gettempdir()) / "best-yolo-public-demo"
    shutil.rmtree(data_root, ignore_errors=True)
    data_root.mkdir(parents=True)
    os.environ["BEST_YOLO_DATA_DIR"] = str(data_root)
    sys.path.insert(0, str(ROOT / "gui"))

    from PySide6.QtWidgets import QApplication
    import app as gui_app
    import core
    import theme

    images = make_demo(data_root)
    project = core.project_dir("Demo")
    cfg = core.blank_project_config(proj_dir=project)
    cfg.update({
        "images": str(images),
        "out": str(Path(project) / "out"),
        "dataset": str(Path(project) / "dataset"),
        "classes": [
            {"name": "bottle", "desc": "蓝色透明饮料瓶，含瓶盖和完整瓶身", "on": True},
            {"name": "helmet", "desc": "黄色安全帽，半圆硬壳并带帽檐", "on": True},
            {"name": "parcel", "desc": "棕色纸箱包裹，矩形且有封箱胶带", "on": True},
        ],
        "negative": "桌面、背景文字、物体阴影",
        "model": "qwen3-vl-plus",
        "workers": 4,
        "qps": 2,
        "preview_limit": 4,
        "seed": 7,
    })
    core.save_project_config(cfg, core.project_config_path("Demo"))
    core.save_state(project="Demo", zoom=0.9,
                    globals={"api_key": "", "base_url": core.DEFAULT_BASE_URL,
                             "model_cache": ["qwen3-vl-plus", "qwen3-vl-flash",
                                             "qwen-vl-max", "qwen-vl-plus"]})
    core.snapshot_baseline(project, cfg["out"])
    # Make one visible human correction after the AI baseline snapshot.
    p = Path(cfg["out"]) / "labels/demo_02.txt"
    lines = p.read_text().splitlines()
    first = lines[0].split()
    first[1] = f"{float(first[1]) + 0.025:.6f}"
    lines[0] = " ".join(first)
    p.write_text("\n".join(lines) + "\n")
    core.save_locks(project, {"demo_02.jpg"})

    qt = QApplication([])
    qt.setStyle("Fusion")
    theme.apply_palette(qt)
    qt.setStyleSheet(theme.stylesheet(0.9))
    win = gui_app.MainWindow()
    win._ui_k = 0.9
    win._apply_scale()
    win.resize(1440, 900)
    win.show()
    qt.processEvents()

    win._go(win.PAGE_HOME)
    qt.processEvents()
    win.grab().save(str(OUT / "overview.png"))

    win._go(win.PAGE_MARK)
    win.lst_vis.setCurrentRow(1)
    qt.processEvents()
    win.grab().save(str(OUT / "annotation.png"))

    win._go(win.PAGE_PROMPT)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        qt.processEvents()
        if win._pai_rows and all(row.get("show") != row.get("img")
                                 for row in win._pai_rows):
            break
        time.sleep(0.02)
    win._pai_check_changed()
    qt.processEvents()
    win.grab().save(str(OUT / "prompt.png"))

    dialog = gui_app.hotkeys.ShortcutSettingsDialog(win._shortcut_bindings, win)
    dialog.resize(980, 680)
    dialog.search.setText("保存")
    dialog.show()
    qt.processEvents()
    dialog.grab().save(str(OUT / "shortcuts.png"))
    dialog.close()

    import cv2
    video_path = data_root / "demo.avi"
    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"MJPG"),
                             4.0, (960, 640))
    for path in sorted(images.glob("*.jpg")):
        writer.write(cv2.imread(str(path)))
    writer.release()
    win._go(win.PAGE_VIDEO)
    win.p_video.setText(str(video_path))
    win.sp_ivl.setValue(0.5)
    qt.processEvents()
    win.grab().save(str(OUT / "video.png"))

    win.close()
    qt.processEvents()
    shutil.copy2(ROOT / "gui/icon.png", OUT / "logo.png")
    for name in ("overview.png", "annotation.png", "prompt.png",
                 "shortcuts.png", "video.png", "logo.png"):
        optimize_png(OUT / name)
    make_banner()
    shutil.rmtree(data_root, ignore_errors=True)
    print("Rendered README assets in", OUT)


if __name__ == "__main__":
    main()
