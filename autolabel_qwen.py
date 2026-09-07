#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qwen-VL 全自动打标 -> YOLO 标签(支持 Qwen2.5-VL 与 Qwen3-VL)

后端:
  --backend local  本地 Qwen2.5-VL(免费/离线,需要 NVIDIA GPU)
  --backend api    云端(OpenAI 兼容接口):需 export DASHSCOPE_API_KEY;
                   专属接入点用 export QWEN_BASE_URL=...;支持并发。

分辨率:
  --max-pixels     模型处理图片的像素上限(如 2000000=200万)。检测在边长 480~2560 内最稳。
                   会按 smart_resize 缩放,坐标也按缩放后尺寸归一化(已修正对齐)。
  Qwen3-VL 的 patch 因子是 32、Qwen2.5-VL 是 28,脚本按模型名自动选择。

高速(仅 API):
  --workers N      并行请求数,越大越快;报限流(RateLimit)就调小。

输出:
  <out>/labels/*.txt  YOLO 格式标签(已归一化: 类别id xc yc w h)
  <out>/vis/*.jpg     画好框的可视化图(第一次务必先看它确认框对齐!)
"""
import os
import re
import io
import json
import glob
import base64
import argparse
import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image, ImageDraw


# ---------------- 限流与重试 ----------------
RETRY_LOG = True        # 是否打印重试过程(GUI 里能看到进度,不至于像卡住)
LIMITER = None          # 全局令牌桶,由 main() 按 --qps 装上


def is_rate_limit(e):
    """是不是被限流。百炼返回 429 + limit_requests。"""
    s = str(e)
    return ("429" in s or "rate limit" in s.lower()
            or "limit_requests" in s or "Throttling" in s)


def is_retryable(e):
    """值得重试的错误:限流、5xx、超时、连接中断。

    4xx(除 429)不重试 —— 参数错/key 错重试多少次都一样,只是浪费时间。
    """
    if is_rate_limit(e):
        return True
    s = str(e).lower()
    for k in ("500", "502", "503", "504", "timeout", "timed out",
              "connection", "temporarily", "internal error", "remote end"):
        if k in s:
            return True
    return False


class RateLimiter:
    """令牌桶:把整个进程的请求速率压在 qps 以内。

    只靠调小 --workers 控制不住速率 —— 20 个线程各自跑得多快取决于响应
    时间。这里在真正发请求前统一取令牌,才能稳定不触发 429。
    """

    def __init__(self, qps):
        self.interval = 1.0 / max(qps, 0.01)
        self._lock = threading.Lock()
        self._next = 0.0

    def acquire(self):
        with self._lock:
            now = time.monotonic()
            wait = self._next - now
            if wait <= 0:
                self._next = now + self.interval
                wait = 0
            else:
                self._next += self.interval
        if wait > 0:
            time.sleep(wait)

PROMPT_TMPL = (
    "请在图中检测以下目标类别:{classes}。\n"
    "以 JSON 数组输出,每个元素格式为 "
    '{{"bbox_2d": [x1, y1, x2, y2], "label": "类别名"}}。'
    "坐标必须是【整数像素值】(不是 0~1 的比例):x1,y1 为左上角,x2,y2 为右下角,"
    "最小 0,最大为图像的宽/高。label 必须严格是上面列出的类别名之一(如 CA001),"
    "不要输出中文描述作为 label。\n"
    "重要要求:\n"
    "1) 图中通常有多个物体,**每一个都要单独输出一条**,同一类出现多次就输出多条;\n"
    "2) 框要紧贴物体轮廓,只框物体本身,不要把周围的桌布/地面框进来;\n"
    "3) 物体互相遮挡时,框可见部分;\n"
    "4) 只框上面列出的类别,{negative}其它东西一律不要框;\n"
    "5) 不确定是哪一类的物体,宁可不输出,也不要猜一个类别名;\n"
    "6) 图中没有任何目标就输出空数组 []。\n"
    "只输出 JSON,不要输出任何其它文字。"
)


def factor_for(model_id):
    """Qwen3-VL patch 因子 32;Qwen2.5-VL 及旧款 28。"""
    m = (model_id or "").lower()
    return 32 if ("qwen3-vl" in m or "qwen3.6" in m or "qwen3.7" in m or "qwen3.8" in m) else 28


def smart_dims(w, h, min_pixels, max_pixels, factor):
    from qwen_vl_utils import smart_resize
    hb, wb = smart_resize(h, w, factor=factor, min_pixels=min_pixels, max_pixels=max_pixels)
    return wb, hb


def parse_boxes(text):
    """从模型输出里稳健地抽出 [(label, [x1,y1,x2,y2]), ...]。"""
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    s, e = text.find("["), text.rfind("]")
    if s == -1 or e == -1:
        return []
    try:
        data = json.loads(text[s:e + 1])
    except Exception:
        return []
    out = []
    for d in data:
        if not isinstance(d, dict):
            continue
        bb = d.get("bbox_2d") or d.get("bbox") or d.get("box")
        label = d.get("label") or d.get("category") or d.get("name")
        if bb and label and len(bb) == 4:
            try:
                out.append((str(label), [float(v) for v in bb]))
            except Exception:
                continue
    return out


def resolve_label(raw_label, classes, name2id, desc_map=None):
    """把模型返回的 label 归一化成我们的类别名。
    classes = 本次【实际要检测】的类别列表(--only 之后的),不是全部类别。
    - 只检测一个类:任何返回都归到这个类(最稳,避免模型回填描述/别名导致丢框)。
    - 多类:① 精确匹配类别名(大小写/空格无关) ② 类别名子串匹配
           ③ 【编号类别名专用】用 desc_map 反查:模型回了中文描述(如"眼镜")时,
              去各类的描述里找关键词命中 —— 因为 "CA001" 和 "眼镜" 没有公共字符,
              光靠 ①② 会全部丢框。
      都不中返回 None(宁可丢,也不要错标成别的类)。
    """
    if len(classes) == 1:
        return classes[0]
    raw = (raw_label or "").strip()
    if raw in name2id and raw in classes:
        return raw
    rl = raw.lower().replace(" ", "").replace("_", "")
    # ① 规范化后精确匹配
    for c in classes:
        if c.lower().replace(" ", "").replace("_", "") == rl:
            return c
    if not rl:
        return None
    # ② 类别名子串匹配(如模型回 "class CA001" 或 "ca001-眼镜")
    for c in classes:
        cl = c.lower().replace(" ", "").replace("_", "")
        if cl and (cl in rl or rl in cl):
            return c
    # ③ 用描述反查(模型回中文描述时的救命路径)
    if desc_map:
        best, best_len = None, 0
        for c in classes:
            d = (desc_map.get(c) or "")
            if not d:
                continue
            # 描述里括号前的主名(如 "眼镜或墨镜")拆成候选词
            head = re.split(r"[((]", d)[0]
            for kw in re.split(r"[或/、,,]", head):
                kw = kw.strip()
                # 单字词太容易误命中(如"水"),要求 >=2 字
                if len(kw) >= 2 and kw in raw and len(kw) > best_len:
                    best, best_len = c, len(kw)
        if best:
            return best
    return None


def parse_desc(desc_str, classes, active=None):
    """解析 --desc,返回 {类别名: 描述}。支持两种写法(| 分隔):
      ① 按类别名(推荐,顺序无关): '006=靶心里的红色十字|003=军用帐篷'
      ② 按顺序:                  '描述1|描述2|...'
    写法②的对齐规则:条数=全部类别数 -> 对齐 classes;条数=实际检测类别数 -> 对齐 active。
    """
    if not desc_str:
        return {}
    parts = [d.strip() for d in desc_str.split("|")]
    nonempty = [p for p in parts if p]
    # 只要每一条都是 "已知类别名=描述" 的形式,就按写法① 解析
    keyed = bool(nonempty) and all(
        "=" in p and p.split("=", 1)[0].strip() in classes for p in nonempty)
    out = {}
    if keyed:
        for p in nonempty:
            k, v = p.split("=", 1)
            out[k.strip()] = v.strip()
        return out
    target = list(classes)
    if active and len(parts) == len(active) and len(active) != len(classes):
        target = list(active)
    for i, c in enumerate(target):
        if i < len(parts) and parts[i]:
            out[c] = parts[i]
    return out


def to_yolo(label_id, bb, div_w, div_h):
    x1, y1, x2, y2 = bb
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    xc = ((x1 + x2) / 2) / div_w
    yc = ((y1 + y2) / 2) / div_h
    w = (x2 - x1) / div_w
    h = (y2 - y1) / div_h
    xc, yc = min(max(xc, 0.0), 1.0), min(max(yc, 0.0), 1.0)
    w, h = min(max(w, 0.0), 1.0), min(max(h, 0.0), 1.0)
    if w <= 0 or h <= 0:
        return None
    return f"{label_id} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}"


# 每个类别一个高对比度颜色(按类别 id 循环取用)。16 类要 16 色,否则颜色撞车看不出区别。
PALETTE = [
    (255, 59, 48),    # 红
    (52, 199, 89),    # 绿
    (0, 122, 255),    # 蓝
    (255, 204, 0),    # 黄
    (175, 82, 222),   # 紫
    (255, 149, 0),    # 橙
    (90, 200, 250),   # 天蓝
    (255, 45, 146),   # 品红
    (0, 199, 190),    # 青
    (162, 132, 94),   # 棕
    (142, 250, 0),    # 黄绿
    (255, 255, 255),  # 白
    (88, 86, 214),    # 靛
    (255, 112, 82),   # 珊瑚
    (0, 105, 60),     # 深绿
    (120, 0, 60),     # 酒红
]


def _load_font(px):
    """尽量加载一个 px 大小的字体;优先中文字体(含中英文,不乱码);都失败退回默认。"""
    # (路径, index):.ttc 是字体集合,需指定 index
    candidates = [
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0),  # 中英文都支持,首选
        ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0), # 仅英文,兜底
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
    ]
    from PIL import ImageFont
    for path, idx in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, px, index=idx)
            except Exception:
                continue
    return ImageFont.load_default()


def draw_vis_wh(img_path, boxes, div_w, div_h, out_path, name2id=None, font_px=None):
    im = Image.open(img_path).convert("RGB")
    W, H = im.size
    d = ImageDraw.Draw(im)
    sx, sy = W / div_w, H / div_h
    # 字号随图片大小自适应,至少 18px;线宽也随之加粗
    fpx = font_px or max(18, int(H * 0.035))
    font = _load_font(fpx)
    line_w = max(2, int(H * 0.005))
    for label, bb in boxes:
        cid = (name2id or {}).get(label, 0)
        color = PALETTE[cid % len(PALETTE)]
        # 底块太亮(如白/黄)时用黑字,否则白字,保证文字始终看得清
        txt_fill = (0, 0, 0) if (0.299 * color[0] + 0.587 * color[1]
                                 + 0.114 * color[2]) > 160 else (255, 255, 255)
        x1, y1, x2, y2 = bb
        x1, y1, x2, y2 = x1 * sx, y1 * sy, x2 * sx, y2 * sy
        d.rectangle([x1, y1, x2, y2], outline=color, width=line_w)
        # 文字加同色底块,放大且清晰
        try:
            tb = d.textbbox((0, 0), label, font=font)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
        except Exception:
            tw, th = len(label) * fpx // 2, fpx
        ty = max(0, y1 - th - 6)
        d.rectangle([x1, ty, x1 + tw + 8, ty + th + 6], fill=color)
        d.text((x1 + 4, ty + 2), label, fill=txt_fill, font=font)
    im.save(out_path)


# ---------------- 本地后端 ----------------
class LocalQwen:
    def __init__(self, model_id, min_pixels, max_pixels):
        from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor
        self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            model_id, torch_dtype="auto", device_map="auto")
        self.processor = AutoProcessor.from_pretrained(
            model_id, min_pixels=min_pixels, max_pixels=max_pixels)
        self.min_pixels, self.max_pixels = min_pixels, max_pixels
        self.factor = factor_for(model_id)

    def ref_dims(self, w, h):
        return smart_dims(w, h, self.min_pixels, self.max_pixels, self.factor)

    def infer(self, img_path, prompt):
        from qwen_vl_utils import process_vision_info
        messages = [{"role": "user", "content": [
            {"type": "image", "image": f"file://{os.path.abspath(img_path)}"},
            {"type": "text", "text": prompt}]}]
        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = self.processor(text=[text], images=image_inputs,
                                videos=video_inputs, padding=True,
                                return_tensors="pt").to(self.model.device)
        gen = self.model.generate(**inputs, max_new_tokens=2048)
        trimmed = gen[:, inputs.input_ids.shape[1]:]
        return self.processor.batch_decode(
            trimmed, skip_special_tokens=True,
            clean_up_tokenization_spaces=False)[0]


# ---------------- API 后端(OpenAI 兼容,支持百炼专属接入点) ----------------
# 不内置任何 API Key —— 这份代码会分发给别人,写死自己的 key 等于把账单
# 交给陌生人。Key 只从环境变量 DASHSCOPE_API_KEY 来(界面会自动传进来)。
DEFAULT_API_KEY = ""
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class ApiQwen:
    def __init__(self, model_id, min_pixels, max_pixels,
                 retries=5, backoff=2.0):
        from openai import OpenAI
        key = os.environ.get("DASHSCOPE_API_KEY") or DEFAULT_API_KEY
        base = os.environ.get("QWEN_BASE_URL") or DEFAULT_BASE_URL
        if not key:
            raise SystemExit(
                "没有 API Key。\n"
                "  界面里:首页「接入点与模型」-> 密钥 -> 设置\n"
                "  命令行:export DASHSCOPE_API_KEY=YOUR_API_KEY")
        # 百炼接入点是阿里云国内地址,不需要(也不该)走代理。
        # 而且系统里常见 ALL_PROXY=socks://... 这种写法会让 httpx 直接报
        # "Unknown scheme for proxy URL"(httpx 只认 socks5://,不认 socks://),
        # 连客户端都建不起来。所以默认造一个【不读环境变量代理】的 http_client。
        # 确实要走代理时:export QWEN_USE_PROXY=1 (此时需 pip install "httpx[socks]")
        kwargs = {}
        if os.environ.get("QWEN_USE_PROXY", "").strip() not in ("1", "true", "yes"):
            try:
                import httpx
                kwargs["http_client"] = httpx.Client(trust_env=False, timeout=120.0)
            except Exception:
                pass
        self.client = OpenAI(api_key=key, base_url=base, **kwargs)
        self.model_id = model_id
        self.retries, self.backoff = retries, backoff
        self.min_pixels, self.max_pixels = min_pixels, max_pixels
        self.factor = factor_for(model_id)

    def ref_dims(self, w, h):
        return smart_dims(w, h, self.min_pixels, self.max_pixels, self.factor)

    def infer(self, img_path, prompt, pil_img=None, upscale=1.0):
        # 可传 img_path 或直接传 pil_img(切片模式用)。upscale>1 时把(切片)图放大再发,小目标更清楚。
        im = pil_img if pil_img is not None else Image.open(img_path).convert("RGB")
        if upscale and upscale != 1.0:
            im = im.resize((int(im.width * upscale), int(im.height * upscale)))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=95)
        b64 = base64.b64encode(buf.getvalue()).decode()
        # 限流(429)必须重试,否则并发一高就整批失败、图片白白丢掉
        last = None
        for attempt in range(self.retries + 1):
            if LIMITER is not None:
                LIMITER.acquire()
            try:
                resp = self.client.chat.completions.create(
                    model=self.model_id,
                    max_tokens=2048,
                    messages=[{"role": "user", "content": [
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        {"type": "text", "text": prompt}]}],
                )
                return resp.choices[0].message.content
            except Exception as e:
                last = e
                if attempt >= self.retries or not is_retryable(e):
                    raise
                # 指数退避 + 随机抖动:20 个线程同时被限流,不能又同时重试
                wait = min(self.backoff * (2 ** attempt), 60.0)
                wait *= 0.7 + 0.6 * random.random()
                if RETRY_LOG:
                    kind = "限流" if is_rate_limit(e) else "临时错误"
                    print(f"    {os.path.basename(img_path or '切片')} {kind},"
                          f"{wait:.1f}s 后第 {attempt + 1} 次重试", flush=True)
                time.sleep(wait)
        raise last


def guess_scale(boxes, w, h, forced=None):
    """自动判定模型返回的坐标空间。返回 (div_w, div_h) 作为归一化除数。

    关键约束:【像素坐标不可能超出图像尺寸】。所以先看坐标能不能被图像尺寸容纳,
    能容纳就是像素;容纳不下才可能是 0~1000 那种归一化。

    以前的写法是"<=1000 就当 0~1000",对小图是错的:
    比如 731x503 的图,模型返回像素 462 —— 因为 462<=1000 被当成归一化,
    结果所有框都缩到原来的 73%,系统性偏移。这个 bug 已修。

    - forced: --coord-scale 强制指定(1=0~1比例, 1000=0~1000归一化)
    """
    if forced == "pixel":
        return float(w), float(h)
    if forced:
        return float(forced), float(forced)
    vals = []
    for _, bb in boxes:
        vals += [abs(v) for v in bb]
    mx = max(vals) if vals else 0
    if mx <= 1.5:
        return 1.0, 1.0          # 0~1 比例
    # 5% 容差:模型看到的是 smart_resize 对齐后的尺寸(会比原图略大几十像素)
    if mx <= max(w, h) * 1.05:
        return float(w), float(h)          # 像素坐标(最常见)
    if mx <= 1050:
        return 1000.0, 1000.0              # 超出图像尺寸,那就是 0~1000 归一化
    return float(w), float(h)


def _iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / ua if ua > 0 else 0.0


def _dedup(boxes_px, iou_th=0.5):
    """boxes_px: [(label,[x1,y1,x2,y2]) 像素]。重叠去重,保留先出现的。"""
    kept = []
    for lb, bb in boxes_px:
        if all(_iou(bb, kb[1]) < iou_th or kb[0] != lb for kb in kept):
            kept.append((lb, bb))
    return kept


def parse_grid(grid):
    """严格解析 2x2 这类切片网格，拒绝表达式和异常大的调用倍数。"""
    m = re.fullmatch(r"([1-9]\d*)x([1-9]\d*)", (grid or "").strip().lower())
    if not m:
        raise ValueError("切片格式必须是 2x2 或 3x3 这样的整数网格")
    gx, gy = int(m.group(1)), int(m.group(2))
    if gx > 10 or gy > 10:
        raise ValueError("切片网格最大为 10x10")
    return gx, gy


def detect_tiled(engine, p, prompt, grid, overlap, upscale):
    """切片检测:把图切成 grid(如 '2x2')块、每块放大 upscale 倍分别检测,
    坐标映射回原图像素,再去重。返回像素坐标的 [(raw_label,[x1,y1,x2,y2]), ...]。"""
    im = Image.open(p).convert("RGB")
    W, H = im.size
    gx, gy = parse_grid(grid)
    tw, th = W // gx, H // gy
    ox, oy = int(tw * overlap), int(th * overlap)
    all_px = []
    for j in range(gy):
        for i in range(gx):
            x1 = max(0, i * tw - ox); y1 = max(0, j * th - oy)
            x2 = min(W, (i + 1) * tw + ox); y2 = min(H, (j + 1) * th + oy)
            tile = im.crop((x1, y1, x2, y2))
            raw = engine.infer(None, prompt, pil_img=tile, upscale=upscale)
            boxes = parse_boxes(raw)
            if not boxes:
                continue
            tW = int(tile.width * upscale); tH = int(tile.height * upscale)
            dw, dh = guess_scale(boxes, tW, tH)   # 判定该切片返回的坐标空间
            for lb, bb in boxes:
                bx1, by1, bx2, by2 = bb
                # 归一化到切片(去掉放大),再加切片左上角偏移 -> 原图像素
                px1 = x1 + bx1 / dw * tile.width
                py1 = y1 + by1 / dh * tile.height
                px2 = x1 + bx2 / dw * tile.width
                py2 = y1 + by2 / dh * tile.height
                all_px.append((lb, [px1, py1, px2, py2]))
    return _dedup(all_px), (W, H)


def process_one(engine, p, prompt, name2id, coord_scale, out_dir, is_api,
                tiles=None, overlap=0.15, upscale=2.0, active=None, desc_map=None,
                dropped=None):
    # active = 本次实际检测的类别(--only);name2id 仍是全部类别->全局 id 的映射
    classes = list(active) if active else list(name2id.keys())
    w, h = Image.open(p).size
    if tiles and is_api:
        # 切片模式:结果已是原图像素坐标
        boxes_px, _ = detect_tiled(engine, p, prompt, tiles, overlap, upscale)
        div_w, div_h = w, h
        boxes = boxes_px
    else:
        raw = engine.infer(p, prompt)
        boxes = parse_boxes(raw)
        if is_api:
            div_w, div_h = guess_scale(boxes, w, h, forced=coord_scale)
        else:
            if coord_scale == "pixel":
                div_w, div_h = float(w), float(h)
            elif coord_scale:
                div_w, div_h = float(coord_scale), float(coord_scale)
            else:
                div_w, div_h = engine.ref_dims(w, h)
    lines = []
    clean_boxes = []
    for raw_label, bb in boxes:
        label = resolve_label(raw_label, classes, name2id, desc_map=desc_map)
        if label is None:
            # 记下来:模型回了但没能对上类别名的 label(排查用)
            if dropped is not None:
                dropped.append(str(raw_label))
            continue
        line = to_yolo(name2id[label], bb, div_w, div_h)
        if line:
            lines.append(line)
            clean_boxes.append((label, bb))
    base = os.path.splitext(os.path.basename(p))[0]
    with open(os.path.join(out_dir, "labels", base + ".txt"), "w") as f:
        f.write("\n".join(lines))
    draw_vis_wh(p, clean_boxes, div_w, div_h, os.path.join(out_dir, "vis", base + ".jpg"), name2id=name2id)
    return len(lines)


def _check_coords(out_dir):
    """扫一遍标签,判断坐标是否明显不合理。返回警告文字,正常则返回 ""。

    典型病症:坐标口径判定错(或 --coord-scale 设错)会让框退化成
    "1.0 1.0 1.0 1.0"(挤到右下角)或占满整图 —— 标签非空但完全没用。
    这种错误光看标签文件不明显,必须主动检查。
    """
    n = degen = full = tiny = 0
    for f in glob.glob(os.path.join(out_dir, "labels", "*.txt")):
        try:
            with open(f) as fh:
                for ln in fh:
                    p = ln.split()
                    if len(p) != 5:
                        continue
                    n += 1
                    xc, yc, bw, bh = (float(v) for v in p[1:])
                    if bw >= 0.999 and bh >= 0.999:
                        degen += 1          # 退化:宽高被 clamp 到满值
                    elif bw * bh >= 0.9:
                        full += 1           # 几乎占满整图
                    elif bw * bh <= 0.00002:
                        tiny += 1           # 小到不可能是真目标
        except Exception:
            continue
    if not n:
        return ""
    msgs = []
    if degen / n > 0.3:
        msgs.append(
            f"⚠ 严重:{degen}/{n} 个框退化成了满幅(宽高都=1.0),画出来就是一个贴边的大框或看不见。\n"
            "   原因几乎一定是坐标口径设错了 —— 检查 --coord-scale,\n"
            "   界面里请把「高级选项 → 坐标口径」改回「自动判定」。")
    if full / n > 0.3:
        msgs.append(f"⚠ {full}/{n} 个框几乎占满整张图,可能是坐标口径不对或模型没找准目标。")
    if tiny / n > 0.3:
        msgs.append(f"⚠ {tiny}/{n} 个框小到几乎不可见,可能坐标口径被当成了像素/归一化的反面。")
    return "\n".join(msgs)


def collect_images(folder, ext):
    if ext and ext.lower() != "auto":
        return sorted(glob.glob(os.path.join(folder, "*" + ext)))
    exts = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
    files = [f for f in glob.glob(os.path.join(folder, "*")) if f.lower().endswith(exts)]
    return sorted(files)


def load_lock_names(path):
    """读上锁清单,返回文件名集合。读不到就当没有锁(不该因此中断标注)。"""
    if not path or not os.path.exists(path):
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, list):
            return set(str(x) for x in d)
        if isinstance(d, dict):
            return set(str(x) for x in d.get("locked") or [])
    except Exception as e:
        print(f"警告:上锁清单读不了({e}),这次不做上锁保护")
    return set()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True, help="待标注图片文件夹")
    ap.add_argument("--out", default="out", help="输出目录")
    ap.add_argument("--classes", required=True,
                    help="类别,逗号分隔,如 apple,person,box(顺序=类别id)")
    ap.add_argument("--desc", default="",
                    help="给模型的详细描述。两种写法(可混用 | 分隔):"
                         "①按类别名: '006=靶心里的红色十字|003=军用帐篷'(推荐,顺序无关);"
                         "②按顺序: 描述1|描述2 (顺序与 --classes 对应)。留空则直接用类别名")
    ap.add_argument("--only", default="",
                    help="只检测这些类别(逗号分隔,如 006);其余类别只占类别id位置、不发给模型。"
                         "标签里的类别id仍按 --classes 的完整顺序")
    ap.add_argument("--negative", default="",
                    help="画面里存在但【不要标注】的东西(顿号或逗号分隔),写进提示词让模型主动排除,"
                         "如 '香蕉、瓶装茶饮料、桌布'。压误标最有效的一招")
    ap.add_argument("--backend", choices=["local", "api"], default="local")
    ap.add_argument("--model", default=None,
                    help="local 默认 Qwen/Qwen2.5-VL-3B-Instruct;api 可填 qwen3-vl-plus 等")
    ap.add_argument("--ext", default="auto", help="图片后缀,auto=常见图片全收(默认)")
    ap.add_argument("--limit", type=int, default=0, help=">0 时只处理前 N 张(预览用)")
    ap.add_argument("--min-pixels", type=int, default=256 * 28 * 28)
    ap.add_argument("--max-pixels", type=int, default=1280 * 28 * 28,
                    help="模型处理像素上限,如 2000000=200万")
    ap.add_argument("--workers", type=int, default=1,
                    help="仅 API:并行请求数,越大越快;报限流就调小")
    ap.add_argument("--skip-done", action="store_true",
                    help="跳过已有非空标签的图(补跑限流失败的图时用)")
    ap.add_argument("--locks", default="",
                    help="上锁清单 json(界面里手动改好的图)。"
                         "这些图一律跳过,且不占 --limit 的名额")
    ap.add_argument("--qps", type=float, default=0,
                    help="每秒最多发几个请求(0=按 workers 自动估算)。"
                         "限流(429)多就调小,比如 2")
    ap.add_argument("--retries", type=int, default=5,
                    help="被限流/临时报错时的重试次数,0=不重试")
    ap.add_argument("--retry-backoff", type=float, default=2.0,
                    help="重试等待的基数秒,按 2 的幂次递增(2→4→8…)")
    ap.add_argument("--coord-scale", default="0",
                    help="坐标口径兜底。0=自动判定(推荐);pixel=强制按图像像素;"
                         "1000=强制 0~1000 归一化;1=强制 0~1 比例。"
                         "设错会让所有框位置错误,一般不要动")
    ap.add_argument("--tiles", default="",
                    help="切片检测(治远景小目标),如 2x2 / 3x3;留空=不切片。仅 API 有效")
    ap.add_argument("--overlap", type=float, default=0.15, help="切片重叠比例,默认0.15")
    ap.add_argument("--upscale", type=float, default=2.0, help="每块放大倍数,默认2.0,小目标更清楚")
    args = ap.parse_args()

    if args.backend == "local" and os.environ.get(
            "BEST_YOLO_API_ONLY", "").strip().lower() in ("1", "true", "yes"):
        raise SystemExit(
            "这个 Debian 安装包是云端 API 版，不包含与显卡绑定的本地模型环境。")

    classes = [c.strip() for c in args.classes.split(",") if c.strip()]
    name2id = {c: i for i, c in enumerate(classes)}

    # --only:本次实际要检测的类别子集(类别id 仍按 classes 的完整顺序算)
    if args.only:
        only = [c.strip() for c in args.only.split(",") if c.strip()]
        bad = [c for c in only if c not in name2id]
        if bad:
            raise SystemExit(f"--only 里的类别不在 --classes 中: {','.join(bad)}\n"
                             f"可选: {','.join(classes)}")
        active = [c for c in classes if c in only]
    else:
        active = list(classes)

    # --desc:给模型看的"详细描述"(可选)。
    #   写法① 按类别名(推荐): "006=靶心圆形区域内的红色十字|003=军用帐篷" —— 顺序无关
    #   写法② 按顺序:          "描述1|描述2|..." —— 与 --classes 顺序对应
    # 描述让模型更懂要找什么,但仍要求它用简洁类别名回填 label。
    desc_map = parse_desc(args.desc, classes, active)
    if any(desc_map.get(c) for c in active):
        # 一类一行,比一长串分号更清楚(16类时尤其重要)
        class_text = "\n" + "\n".join(
            f'  - {c}: {desc_map.get(c) or c}' for c in active)
    else:
        class_text = "、".join(active)
    neg = (args.negative or "").strip()
    neg_text = f"下列东西即使出现也不要框:{neg};" if neg else ""
    prompt = PROMPT_TMPL.format(classes=class_text, negative=neg_text)

    os.makedirs(os.path.join(args.out, "labels"), exist_ok=True)
    os.makedirs(os.path.join(args.out, "vis"), exist_ok=True)

    if args.backend == "local":
        model_id = args.model or "Qwen/Qwen2.5-VL-3B-Instruct"
        engine = LocalQwen(model_id, args.min_pixels, args.max_pixels)
    else:
        model_id = args.model or "qwen-vl-max"
        engine = ApiQwen(model_id, args.min_pixels, args.max_pixels,
                         retries=max(0, args.retries),
                         backoff=max(0.2, args.retry_backoff))

    imgs = collect_images(args.images, args.ext)
    # 上锁的图在这里就剔掉 —— 必须在 --limit 之前,否则"预览 20 张"里
    # 会被上锁的图占掉名额,实际只标了几张新的。
    locked = load_lock_names(args.locks)
    if locked:
        before = len(imgs)
        imgs = [p for p in imgs if os.path.basename(p) not in locked]
        n_lock = before - len(imgs)
        if n_lock:
            print(f"上锁保护:跳过 {n_lock} 张手动改好的图(不会被覆盖)")
    if args.limit > 0:
        imgs = imgs[:args.limit]
    # coord_scale: None=自动判定, "pixel"=强制按图像宽高, 数字=强制该除数
    cs_raw = str(args.coord_scale or "0").strip().lower()
    if cs_raw in ("pixel", "px"):
        coord_scale = "pixel"
    else:
        try:
            coord_scale = float(cs_raw) or None
        except ValueError:
            raise SystemExit(f"--coord-scale 只能是 0 / pixel / 1000 / 1,收到 {args.coord_scale!r}")
    workers = args.workers if args.backend == "api" else 1
    # 装上全局限流器。不指定 --qps 时按并发数估一个保守值:
    # 视觉模型单次要几秒,workers 个线程稳态速率约 workers/3,再打个折。
    global LIMITER
    if args.backend == "api":
        qps = args.qps if args.qps > 0 else max(1.0, workers / 3.0)
        LIMITER = RateLimiter(qps)
    else:
        qps = 0
    print(f"共 {len(imgs)} 张图, 后端={args.backend}, 模型={model_id}, "
          f"max_pixels={args.max_pixels}, workers={workers}"
          + (f", 限速={qps:.1f}/秒, 重试={args.retries} 次" if args.backend == "api" else ""))
    print("类别表(id=类别名): " + ", ".join(f"{name2id[c]}={c}" for c in classes))
    if len(active) != len(classes):
        print("本次只检测: " + ", ".join(f"{c}(id={name2id[c]})" for c in active)
              + "  —— 其余类别只占位,不发给模型、不会出现在标签里")
    print("发给模型的目标描述: " + class_text)
    if not imgs:
        raise SystemExit(f"没在 {args.images} 找到图片,检查路径或 --ext")

    # 补跑模式:已经有标签的图直接跳过,只打没标上的那些,不重复花钱
    if args.skip_done:
        keep = []
        for p in imgs:
            lb = os.path.join(args.out, "labels",
                              os.path.splitext(os.path.basename(p))[0] + ".txt")
            # 空标签文件是成功处理的负样本，不是失败；失败时根本不会建文件。
            if os.path.exists(lb):
                continue
            keep.append(p)
        n_skip = len(imgs) - len(keep)
        if n_skip:
            print(f"--skip-done: 跳过已有标签的 {n_skip} 张,只跑剩下 {len(keep)} 张")
        imgs = keep
        if not imgs:
            print("所有图都已有标签,没什么要补的。")
            return

    total = 0
    is_api = (args.backend == "api")
    tiles = args.tiles or None
    dropped = []          # 模型回了但对不上类别名的 label(排查用)
    per_class = {}        # 各类别标了多少框
    from functools import partial
    do_one = partial(process_one, engine, prompt=prompt, name2id=name2id,
                     coord_scale=coord_scale, out_dir=args.out, is_api=is_api,
                     tiles=tiles, overlap=args.overlap, upscale=args.upscale,
                     active=active, desc_map=desc_map, dropped=dropped)
    if tiles:
        try:
            gx, gy = parse_grid(tiles)
        except ValueError as e:
            raise SystemExit(str(e))
        print(f"切片模式: {tiles}, overlap={args.overlap}, upscale={args.upscale} "
              f"(每张约 {gx * gy} 次 API 调用)")
    failed = []           # [(路径, 错误)] 全部重试完还是失败的
    def run_batch(paths, tag=""):
        """跑一批图,返回 (框数合计, 失败列表)。"""
        got, bad = 0, []
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(do_one, p): p for p in paths}
                done = 0
                for fut in as_completed(futs):
                    p = futs[fut]
                    done += 1
                    try:
                        n = fut.result()
                        got += n
                        print(f"[{tag}{done}/{len(paths)}] {os.path.basename(p)} -> {n} 个框",
                              flush=True)
                    except Exception as ex2:
                        bad.append((p, ex2))
                        print(f"[{tag}{done}/{len(paths)}] {os.path.basename(p)} 失败: {ex2}",
                              flush=True)
        else:
            for i, p in enumerate(paths, 1):
                try:
                    n = do_one(p)
                    got += n
                    print(f"[{tag}{i}/{len(paths)}] {os.path.basename(p)} -> {n} 个框",
                          flush=True)
                except Exception as ex2:
                    bad.append((p, ex2))
                    print(f"[{tag}{i}/{len(paths)}] {os.path.basename(p)} 失败: {ex2}",
                          flush=True)
        return got, bad

    n_box, failed = run_batch(imgs)
    total += n_box

    # 整批扫完后,被限流打掉的那些再单线程慢速重跑一遍。
    # 这时并发压力已经没了,通常能全部补上,不用你手动重跑整个目录。
    rl_failed = [(p, e) for p, e in failed if is_rate_limit(e)]
    if rl_failed and args.retries > 0:
        print(f"\n有 {len(rl_failed)} 张因限流失败,降速重跑这些图(单线程)…")
        saved_workers, workers = workers, 1
        saved_limiter = LIMITER
        LIMITER = RateLimiter(max(0.5, (args.qps or 3.0) / 3.0))
        n_box, still_bad = run_batch([p for p, _ in rl_failed], tag="补跑 ")
        total += n_box
        workers = saved_workers
        LIMITER = saved_limiter
        failed = [(p, e) for p, e in failed if not is_rate_limit(e)] + still_bad

    ok_n = len(imgs) - len(failed)
    print(f"完成! {ok_n}/{len(imgs)} 张成功,共 {total} 个框。"
          f"请先打开 {args.out}/vis 检查框准不准,再继续训练。")

    # 失败清单必须醒目:之前 14 张挂了也只是混在滚动日志里,很容易以为跑完了
    if failed:
        rl = sum(1 for _, e in failed if is_rate_limit(e))
        print(f"\n⚠ {len(failed)} 张没标上(这些图没有标签文件):")
        for p, e in failed[:10]:
            print(f"  - {os.path.basename(p)}: {str(e)[:100]}")
        if len(failed) > 10:
            print(f"  … 另有 {len(failed) - 10} 张")
        if rl:
            print(f"\n  其中 {rl} 张是被限流(429)。降低并发或限速再跑一次即可补上:")
            print(f"    --workers {max(1, workers // 2)} --qps 2")
            print(f"    --skip-done   # 跳过已标好的,只补这 {len(failed)} 张,不重复花钱")

    # 坐标健康检查:框全贴边/占满全图 = 坐标口径判定错了(比如误设了 --coord-scale)。
    # 这种情况标签看着"有内容"但完全没用,必须当场喊出来,不能让用户自己去看图发现。
    _sane = _check_coords(args.out)
    if _sane:
        print("\n" + _sane)

    # 各类别标了多少 —— 一眼看出哪类没标到 / 哪类被过度标注
    id2name = {i: c for c, i in name2id.items()}
    counts = {}
    for f in glob.glob(os.path.join(args.out, "labels", "*.txt")):
        with open(f) as fh:
            for ln in fh:
                p0 = ln.split()
                if p0:
                    counts[int(p0[0])] = counts.get(int(p0[0]), 0) + 1
    empty = sum(1 for f in glob.glob(os.path.join(args.out, "labels", "*.txt"))
                if os.path.getsize(f) == 0)
    print("\n各类别框数:")
    for c in active:
        i = name2id[c]
        d = (desc_map.get(c) or "")[:22]
        n = counts.get(i, 0)
        flag = "   <-- 一个都没标到,检查描述" if n == 0 else ""
        print(f"  id={i:<3} {c}  {n:>5} 个   {d}{flag}")
    if empty:
        print(f"  (另有 {empty} 张图没有任何标签 = 空文件,若不该为空说明描述没匹配上)")
    if dropped:
        from collections import Counter
        print(f"\n⚠ 有 {len(dropped)} 个框因为 label 对不上类别名被丢弃,出现最多的:")
        for k, v in Counter(dropped).most_common(8):
            print(f"    {v:>4}x  {k!r}")
        print("  -> 若这些其实是你要的类,把它的说法写进对应类别的 --desc 描述里")


if __name__ == "__main__":
    main()
