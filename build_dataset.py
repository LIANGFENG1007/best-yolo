#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 图片 + YOLO 标签 切分成 train/val,并生成 data.yaml。"""
import os
import glob
import random
import shutil
import argparse
import yaml


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True, help="原始图片文件夹")
    ap.add_argument("--labels", required=True, help="autolabel 生成的 labels 目录")
    ap.add_argument("--out", default="dataset", help="输出数据集目录")
    ap.add_argument("--classes", required=True, help="类别,逗号分隔(顺序=类别id)")
    ap.add_argument("--ext", default=".jpg", help="图片后缀")
    ap.add_argument("--val-ratio", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    classes = [c.strip() for c in args.classes.split(",") if c.strip()]
    random.seed(args.seed)

    if args.ext and args.ext.lower() != "auto":
        imgs = glob.glob(os.path.join(args.images, "*" + args.ext))
    else:
        exts = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
        imgs = [f for f in glob.glob(os.path.join(args.images, "*"))
                if f.lower().endswith(exts)]

    pairs = []
    for img in imgs:
        base = os.path.splitext(os.path.basename(img))[0]
        lbl = os.path.join(args.labels, base + ".txt")
        if os.path.exists(lbl):
            pairs.append((img, lbl))

    if not pairs:
        raise SystemExit("没找到任何 图片+标签 配对,检查 --images / --labels / --ext")

    random.shuffle(pairs)
    n_val = int(len(pairs) * args.val_ratio)
    split = {"val": pairs[:n_val], "train": pairs[n_val:]}

    for part, items in split.items():
        os.makedirs(os.path.join(args.out, "images", part), exist_ok=True)
        os.makedirs(os.path.join(args.out, "labels", part), exist_ok=True)
        for img, lbl in items:
            shutil.copy(img, os.path.join(args.out, "images", part, os.path.basename(img)))
            shutil.copy(lbl, os.path.join(args.out, "labels", part, os.path.basename(lbl)))

    data = {
        "path": os.path.abspath(args.out),
        "train": "images/train",
        "val": "images/val",
        "names": {i: c for i, c in enumerate(classes)},
    }
    with open(os.path.join(args.out, "data.yaml"), "w") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    # classes.txt:一行一个类别名,行号 = 类别 id。
    # 这是 YOLO 生态的通用约定(labelImg / X-AnyLabeling / darknet 都认它),
    # 有它才能用那些工具直接打开这批标签继续改。
    cls_txt = os.path.join(args.out, "classes.txt")
    with open(cls_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(classes) + "\n")

    print(f"数据集就绪: {args.out}  (train={len(split['train'])}, val={len(split['val'])})")
    print(f"已写出 data.yaml 和 classes.txt({len(classes)} 个类别)")


if __name__ == "__main__":
    main()
