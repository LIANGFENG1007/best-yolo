#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在自动标注得到的数据集上训练 YOLO。"""
import argparse
from ultralytics import YOLO


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="dataset/data.yaml")
    ap.add_argument("--model", default="yolov8n.pt",
                    help="想更准可换 yolov8s/m.pt 或 yolo11n.pt")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640)
    args = ap.parse_args()

    YOLO(args.model).train(data=args.data, epochs=args.epochs, imgsz=args.imgsz)
    print("训练完成!权重在 runs/detect/train/weights/best.pt")


if __name__ == "__main__":
    main()
