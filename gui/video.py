# -*- coding: utf-8 -*-
"""视频抽帧:把一段视频按时间间隔切成图片。

只用 OpenCV(项目里已经有,ultralytics 依赖它),不引入新的依赖。

设计要点:
- 读视频信息用 CAP_PROP_*,但【不信任】它给的帧数:很多手机录的 mp4
  帧数字段是错的甚至是 0,所以时长优先按 帧数/fps 算,算不出来再退回
  遍历。界面上宁可显示"未知"也不能显示一个错的时长。
- 抽帧按【时间】而不是按帧号步进:间隔 0.5 秒这种要求和帧率无关,
  按帧号算会在变帧率(VFR)视频上越走越偏。
- 每抽一张都回调一次,界面才能显示进度、也才能中途取消。
"""
import os
import glob

VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".webm",
              ".m4v", ".mpg", ".mpeg", ".ts", ".3gp")


def is_video(path):
    return os.path.splitext(path or "")[1].lower() in VIDEO_EXTS


def probe(path):
    """读视频基本信息。返回 dict,失败时 ok=False。

    duration 单位秒。拿不到就是 0.0,调用方要能接受"未知时长"。
    """
    info = {"ok": False, "fps": 0.0, "frames": 0, "w": 0, "h": 0,
            "duration": 0.0, "err": ""}
    if not path or not os.path.isfile(path):
        info["err"] = "文件不存在"
        return info
    try:
        import cv2
    except Exception as e:
        info["err"] = f"缺少 OpenCV:{e}"
        return info
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        cap.release()
        info["err"] = "打不开这个视频(格式不支持或文件损坏)"
        return info
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        info["w"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        info["h"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        # fps 离谱(有些文件写成 0 或 1000)就当未知
        if not (0.1 < fps < 1000):
            fps = 0.0
        info["fps"] = fps
        info["frames"] = max(0, n)
        if fps and n > 0:
            info["duration"] = n / fps
        else:
            # 兜底:跳到最后读时间戳。比遍历整个视频快得多。
            cap.set(cv2.CAP_PROP_POS_AVI_RATIO, 1.0)
            ms = float(cap.get(cv2.CAP_PROP_POS_MSEC) or 0)
            info["duration"] = max(0.0, ms / 1000.0)
        info["ok"] = info["w"] > 0 and info["h"] > 0
        if not info["ok"]:
            info["err"] = "读不到画面尺寸"
    finally:
        cap.release()
    return info


def fmt_time(sec):
    """秒 -> mm:ss.s,超过一小时显示 h:mm:ss.s。"""
    try:
        sec = max(0.0, float(sec))
    except (TypeError, ValueError):
        return "0:00.0"
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:04.1f}" if h else f"{m}:{s:04.1f}"


def grab_frame(path, sec):
    """取某个时间点的一帧,返回 BGR ndarray;失败返回 None。

    给预览用。每次都重开一次 VideoCapture 太慢,所以外面用 FrameReader。
    """
    r = FrameReader(path)
    try:
        return r.at(sec)
    finally:
        r.close()


class FrameReader:
    """按时间点取帧,复用同一个 VideoCapture(拖进度条时才不卡)。"""

    def __init__(self, path):
        self.path = path
        self.cap = None
        try:
            import cv2
            self._cv2 = cv2
            cap = cv2.VideoCapture(path)
            self.cap = cap if cap.isOpened() else None
            if self.cap is None:
                cap.release()
        except Exception:
            self._cv2 = None

    def ok(self):
        return self.cap is not None

    def at(self, sec):
        if self.cap is None:
            return None
        cv2 = self._cv2
        try:
            self.cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(sec)) * 1000.0)
            ok, frame = self.cap.read()
            return frame if ok else None
        except Exception:
            return None

    def close(self):
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None


def plan_times(start, end, interval, duration=0.0, limit=0):
    """算出要抽哪些时间点。返回秒的列表。

    区间左闭右闭:end 那一帧也要,否则用户框到视频末尾会少一张。
    limit>0 时最多这么多张(界面上防止手滑填 0.01 秒抽出几万张)。
    """
    try:
        interval = float(interval)
    except (TypeError, ValueError):
        interval = 0.0
    if interval <= 0:
        return []
    start = max(0.0, float(start or 0))
    end = float(end or 0)
    if duration > 0:
        end = min(end, duration)
    if end <= start:
        return []
    out = []
    t = start
    # 用乘法而不是累加,避免浮点误差累积(0.1 加 100 次会偏)
    i = 0
    while True:
        t = start + i * interval
        if t > end + 1e-6:
            break
        out.append(round(t, 4))
        i += 1
        if limit and len(out) >= limit:
            break
    return out


def next_index(out_dir, prefix="image_"):
    """已有 image_007.jpg 时返回 8,方便多段视频往同一个文件夹里续抽。"""
    mx = 0
    for p in glob.glob(os.path.join(out_dir, f"{prefix}*")):
        stem = os.path.splitext(os.path.basename(p))[0]
        tail = stem[len(prefix):]
        if tail.isdigit():
            mx = max(mx, int(tail))
    return mx + 1


def extract(path, out_dir, interval, start=0.0, end=None, prefix="image_",
            digits=3, fmt="jpg", quality=95, resume=True,
            on_progress=None, should_stop=None, limit=0):
    """抽帧存图。返回 (成功张数, 错误信息或"")。

    on_progress(i, total, saved_path) 每存一张调一次,返回 False 可中止。
    should_stop() 返回 True 也中止(给界面的"停止"按钮用)。
    """
    info = probe(path)
    if not info["ok"]:
        return 0, info["err"] or "读不了这个视频"
    if end is None or float(end) <= 0:
        end = info["duration"]
    times = plan_times(start, end, interval, info["duration"], limit)
    if not times:
        return 0, "这个区间和间隔算不出任何一帧,检查开始/结束时间和间隔"
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception as e:
        return 0, f"建不了输出目录:{e}"

    try:
        import cv2
    except Exception as e:
        return 0, f"缺少 OpenCV:{e}"

    idx = next_index(out_dir, prefix) if resume else 1
    ext = (fmt or "jpg").lower().lstrip(".")
    params = []
    if ext in ("jpg", "jpeg"):
        params = [cv2.IMWRITE_JPEG_QUALITY, int(quality)]
    elif ext == "png":
        params = [cv2.IMWRITE_PNG_COMPRESSION, 3]

    reader = FrameReader(path)
    if not reader.ok():
        return 0, "打不开这个视频"
    n_ok = 0
    try:
        for i, t in enumerate(times):
            if should_stop and should_stop():
                return n_ok, "已停止"
            frame = reader.at(t)
            if frame is None:
                continue          # 个别时间点读不到就跳过,不要整批失败
            name = f"{prefix}{idx:0{digits}d}.{ext}"
            dst = os.path.join(out_dir, name)
            try:
                # 用 imencode 再手写文件:cv2.imwrite 遇到中文路径会静默失败
                ok, buf = cv2.imencode("." + ext, frame, params)
                if not ok:
                    continue
                with open(dst, "wb") as f:
                    f.write(buf.tobytes())
            except Exception:
                continue
            n_ok += 1
            idx += 1
            if on_progress and on_progress(i + 1, len(times), dst) is False:
                return n_ok, "已停止"
    finally:
        reader.close()
    return n_ok, ""
