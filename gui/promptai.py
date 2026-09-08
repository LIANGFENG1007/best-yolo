# -*- coding: utf-8 -*-
"""AI 补充提示词:让大模型看"AI 原来标的"和"你改成的",反推提示词该怎么写。

两个阶段:
  1) 每张图单独问一次(可并发):这张图上你改了什么、说明提示词哪里没写清。
     发的是一张【对照图】—— 同一张原图上画两种框:红=AI 原来的,绿=你现在的。
     这样模型不用靠坐标数字想象位置,直接看图就知道"框歪了/多框了/漏框了"。
  2) 把所有单图结论 + 改动史汇总,问一次:给出每个类别的新描述。
     分两步是因为视觉模型一次看几十张图会顾此失彼,而且没法并发。

全新项目(没有基线)走另一条路:直接看你的手标结果,给第一版描述。
"""
import os
import json
import base64
import io

# 画框的颜色:红=AI 原始,绿=人工修订后。和界面里的框色无关,
# 这两种颜色对比强,模型描述起来也不容易混。
C_AI = (255, 64, 64)
C_HUMAN = (64, 220, 96)


def _load_font(px, bold=False):
    """加载系统中文字体，兼容 Ubuntu 和 Windows。"""
    from PIL import ImageFont
    windir = os.environ.get("WINDIR", r"C:\Windows")
    win_names = (["msyhbd.ttc", "simhei.ttf", "msyh.ttc"] if bold else
                 ["msyh.ttc", "msyhbd.ttc", "simhei.ttf"])
    candidates = [os.path.join(windir, "Fonts", name) for name in win_names]
    candidates += [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            return ImageFont.truetype(path, int(px), index=0)
        except Exception:
            continue
    return ImageFont.load_default()


def _load_rgb(path, max_side=1280):
    """读图并限制长边。太大既慢又贵,1280 对判断框准不准足够了。"""
    from PIL import Image
    im = Image.open(path).convert("RGB")
    if max(im.size) > max_side:
        r = max_side / max(im.size)
        im = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))),
                       Image.LANCZOS)
    return im


def compose_diff_image(img_path, base_boxes, cur_boxes, names, max_side=1280):
    """在原图上画两套框:红=AI 原始,绿=人工修订。返回 PIL Image。

    只画框不画填充,否则会盖住物体本身 —— 模型就看不出框对不对了。
    """
    from PIL import ImageDraw
    im = _load_rgb(img_path, max_side)
    d = ImageDraw.Draw(im)
    W, H = im.size
    f = _load_font(14)

    taken = []          # 已占用的标签区域,避免两个标签叠在一起谁都看不清

    def place(x, y, bw, bh):
        """给标签找个不和已有标签重叠的位置,重叠就往下挪一行。"""
        for _ in range(6):
            box = (x, y, x + bw, y + bh)
            if not any(box[0] < t[2] and t[0] < box[2] and
                       box[1] < t[3] and t[1] < box[3] for t in taken):
                taken.append(box)
                return x, y
            y += bh + 2
        taken.append((x, y, x + bw, y + bh))
        return x, y

    def draw(boxes, color, tag):
        for b in boxes or []:
            x1 = (b["xc"] - b["w"] / 2) * W
            y1 = (b["yc"] - b["h"] / 2) * H
            x2 = (b["xc"] + b["w"] / 2) * W
            y2 = (b["yc"] + b["h"] / 2) * H
            d.rectangle([x1, y1, x2, y2], outline=color, width=3)
            nm = names[b["cid"]] if 0 <= b["cid"] < len(names) else str(b["cid"])
            txt = f"{tag}{nm}"
            tw = d.textbbox((0, 0), txt, font=f)
            bw, bh = tw[2] - tw[0] + 6, tw[3] - tw[1] + 4
            lx, ly = place(x1, max(0, y1 - bh), bw, bh)
            d.rectangle([lx, ly, lx + bw, ly + bh], fill=color)
            d.text((lx + 3, ly + 1), txt, font=f, fill=(0, 0, 0))

    # 先画人工(绿)再画 AI(红):AI 那版是"标错的",压在上面更容易被注意到
    draw(cur_boxes, C_HUMAN, "人工:")
    draw(base_boxes, C_AI, "AI:")
    return im


def img_to_data_url(im, fmt="JPEG", quality=88):
    buf = io.BytesIO()
    im.save(buf, format=fmt, quality=quality)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    mime = "image/jpeg" if fmt.upper() in ("JPEG", "JPG") else "image/png"
    return f"data:{mime};base64,{b64}"


# ---------------- 提示词 ----------------
PER_IMAGE_DIFF = (
    "这是一张目标检测的标注对照图。同一张图上画了两套框:\n"
    "  · 红框(标注 AI:)= 模型自动标注的结果\n"
    "  · 绿框(标注 人工:)= 人工检查并修订后的结果\n\n"
    "当前使用的类别定义:\n{classes}\n"
    "{negative}\n"
    "系统统计出的差异:{diff}\n\n"
    "请判断:人工为什么这样改?说明现在的类别描述哪里不够清楚,"
    "导致模型标错、多标或漏标。\n"
    "只回答观察到的问题,每条一行,不超过 4 条,不要重复统计数字,"
    "不要提修改建议(下一步再统一给)。"
)

FIRST_TIME = (
    "这是一张目标检测的人工标注图,绿框是人工标出的目标,框上的文字是类别名。\n"
    "当前类别只有名字、没有描述:\n{classes}\n\n"
    "请观察每一类实际长什么样(颜色、形状、材质、大小、常见摆放方式),"
    "以便后续写出能让视觉模型准确找到它们的描述。\n"
    "每类一行,不超过 6 条。只描述看到的事实。"
)

AGGREGATE = (
    "你在帮一个目标检测标注流程【修订】现有提示词。\n\n"
    "【现有的类别描述】(这是你要修订的原文,不是参考资料)\n{classes}\n\n"
    "【现有『不要标注』的说明】\n{negative}\n\n"
    "【历史调整记录】(说明哪些描述已经改过,不要来回改;"
    "accepted=false 表示用户拒绝过这个建议,不要再提)\n{history}\n\n"
    "【多张图的观察结论】\n{findings}\n\n"
    "最重要的要求:你是在【原有描述的基础上修改】,不是重写。\n"
    "  · 原描述里已有的正确信息必须保留,原有的措辞和用词习惯要沿用;\n"
    "  · 只针对观察到的问题做增补或修正 —— 通常是加一个限定条件、"
    "补一种容易漏的形态、或去掉一个导致误标的说法;\n"
    "  · 不要因为觉得自己写得更好就换一套说法;\n"
    "  · 如果某类的原描述已经够用,action 填 keep,desc 照抄原文。\n\n"
    "其它要求:\n"
    "1) 描述要具体、可判断(颜色/形状/材质/尺寸/是否含破损变形),"
    "不要写『清晰可见』这种没法执行的话;\n"
    "2) 如果观察到反复多标某类东西,把它追加到 negative 里"
    "(保留原有内容,用分号接上,不要整段重写);\n"
    "3) 每条都要给出简短理由,并在 changed 里说明"
    "『在原描述上具体动了哪一处』;\n"
    "4) 描述用中文,控制在 60 字以内。\n\n"
    "严格只输出 JSON,格式:\n"
    '{{"classes": [{{"name": "类别名", "action": "keep|update", '
    '"desc": "修订后的完整描述(在原文基础上改)", '
    '"changed": "在原描述上动了哪一处", "reason": "依据哪个观察"}}], '
    '"negative": "不要标注的东西(在原文后面追加,保留原有内容)", '
    '"negative_reason": "理由", "summary": "一句话总结这次调整"}}'
)


def _classes_text(classes):
    out = []
    for c in classes or []:
        if not c.get("on", True):
            continue
        nm = (c.get("name") or "").strip()
        ds = (c.get("desc") or "").strip()
        out.append(f"  - {nm}: {ds}" if ds else f"  - {nm}: (还没有描述)")
    return "\n".join(out) or "  (类别表是空的)"


def _diff_text(d, names):
    """把 diff_boxes 的结果说成人话,给模型当线索。"""
    if not d:
        return "无"

    def nm(b):
        return names[b["cid"]] if 0 <= b["cid"] < len(names) else str(b["cid"])

    bits = []
    if d.get("kept"):
        bits.append(f"{d['kept']} 个框人工确认无误")
    if d.get("moved"):
        bits.append("调整了框位置/大小:" +
                    "、".join(sorted({nm(b) for b, _ in d["moved"]})))
    if d.get("relabeled"):
        bits.append("改了类别:" + "、".join(
            f"{nm(b)}->{nm(c)}" for b, c in d["relabeled"][:6]))
    if d.get("deleted"):
        bits.append("删掉了 AI 标的:" +
                    "、".join(sorted({nm(b) for b in d["deleted"]})))
    if d.get("added"):
        bits.append("补标了 AI 漏掉的:" +
                    "、".join(sorted({nm(b) for b in d["added"]})))
    return ";".join(bits) if bits else "两版一致"


# ---------------- 调模型 ----------------
def _client(base_url, api_key, timeout=120):
    import httpx
    from openai import OpenAI
    # trust_env=False:和标注脚本一致,绝不走系统代理
    # (系统里的 ALL_PROXY=socks://... 会让 httpx 直接建不起来)
    return OpenAI(api_key=(api_key or "").strip(),
                  base_url=(base_url or "").strip(),
                  http_client=httpx.Client(trust_env=False, timeout=float(timeout)))


def _ask(client, model, text, data_url=None, timeout=120):
    """问一次模型。有图就带图。返回回答文本,失败抛异常。"""
    content = [{"type": "text", "text": text}]
    if data_url:
        content.insert(0, {"type": "image_url",
                           "image_url": {"url": data_url}})
    r = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        temperature=0.2,          # 要稳定可复现,不要发挥
    )
    return (r.choices[0].message.content or "").strip()


def _parse_json(text):
    """从回答里抠出 JSON。模型常会包一层 ```json ``` 或前后加话。"""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("```")[1] if "```" in t[3:] else t[3:]
        if t.lower().startswith("json"):
            t = t[4:]
    t = t.strip()
    # 找第一个 { 到最后一个 }
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        t = t[i:j + 1]
    return json.loads(t)


def analyze(samples, classes, negative, history, base_url, api_key, model,
            workers=4, on_progress=None, should_stop=None, max_side=1280,
            all_names=None):
    """主流程。samples = [{"img","base","cur","name"}...]

    base/cur 是框列表(base 为 None 表示全新项目,没有对比基线)。
    返回 (结果 dict, 错误信息)。结果里有 classes/negative/summary。
    """
    # classes 可以只是本轮勾选的子集，但框里的 cid 永远对应完整类别表。
    # 绘图和差异描述必须用完整名字，否则勾选非第 0 类时会显示成数字或错类。
    names = list(all_names or
                 [(c.get("name") or "") for c in (classes or [])])
    cls_txt = _classes_text(classes)
    neg = (negative or "").strip()
    if not samples:
        return None, "没有选中任何图片"
    try:
        client = _client(base_url, api_key)
    except Exception as e:
        return None, f"连不上模型接口:{e}"

    # ---- 阶段1:逐图观察(并发)----
    findings = []
    errs = []
    total = len(samples)
    done = [0]

    def one(s):
        if should_stop and should_stop():
            return None
        try:
            base_boxes = s.get("base")
            cur = s.get("cur") or []
            if base_boxes is None:
                # 全新项目:只有人工标注,让模型描述看到了什么
                im = compose_diff_image(s["img"], [], cur, names, max_side)
                q = FIRST_TIME.format(classes=cls_txt)
            else:
                im = compose_diff_image(s["img"], base_boxes, cur, names, max_side)
                import core
                d = core.diff_boxes(base_boxes, cur)
                # 选中就一定发 —— 用户说"我只会选我改过的",不替他判断。
                # 就算系统算不出差异(比如只是微调了一两像素),
                # 也照样让模型看图,它可能看出统计看不出的东西。
                q = PER_IMAGE_DIFF.format(
                    classes=cls_txt,
                    negative=(f"当前不要标注:{neg}" if neg else ""),
                    diff=_diff_text(d, names))
            ans = _ask(client, model, q, img_to_data_url(im))
            return f"[{s.get('name') or os.path.basename(s['img'])}]\n{ans}"
        except Exception as e:
            errs.append(f"{s.get('name','?')}: {e}")
            return None
        finally:
            done[0] += 1
            if on_progress:
                on_progress(done[0], total, "")

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as ex:
        for r in ex.map(one, samples):
            if r:
                findings.append(r)

    if should_stop and should_stop():
        return None, "已停止"
    if not findings:
        if errs:
            return None, "所有图片都分析失败:\n" + "\n".join(errs[:5])
        return None, "模型没有给出任何观察结论,可以换个模型再试"

    # ---- 阶段2:汇总成提示词 ----
    hist_txt = "(还没有历史记录)"
    if history:
        hist_txt = "\n".join(
            f"  - {h.get('at','')} {h.get('class','')}: "
            f"{h.get('old','') or '(空)'} -> {h.get('new','')} "
            f"[accepted={str(bool(h.get('accepted'))).lower()}] "
            f"{h.get('reason','')}"
            for h in history[-40:])
    q = AGGREGATE.format(classes=cls_txt, negative=neg or "(没有)",
                         history=hist_txt, findings="\n\n".join(findings))
    try:
        ans = _ask(client, model, q)
        data = _parse_json(ans)
    except Exception as e:
        return None, f"汇总失败:{e}"
    if not isinstance(data, dict):
        return None, "模型返回的不是预期格式"
    data["_findings"] = findings
    data["_errors"] = errs
    return data, ""


def render_boxed(img_path, boxes, names, colors, max_side=1400, cache_dir=None):
    """把当前标签画到图上,返回图片路径(用于列表缩略图和放大查看)。

    为什么不能直接用 out/vis/ 里的图:那是自动标注当时画的,里面是
    【AI 原来的框】。你手动改过之后它就过期了 —— 而你要确认的恰恰是
    "我改成的框对不对"。所以这里按当前标签重新画。

    画好的图缓存到 cache_dir,文件名带标签的修改时间:标签一改缓存就失效,
    不会给你看旧图。
    """
    from PIL import ImageDraw
    if not (img_path and os.path.isfile(img_path)):
        return img_path
    if not boxes:
        return img_path          # 没有框就用原图,省一次画图
    if cache_dir:
        try:
            os.makedirs(cache_dir, exist_ok=True)
            stem = os.path.splitext(os.path.basename(img_path))[0]
            # 用"框的内容"算个短签名:框一变文件名就变,缓存自动失效
            sig = _box_sig(boxes)
            dst = os.path.join(cache_dir, f"{stem}_{sig}.jpg")
            if os.path.exists(dst):
                return dst
        except Exception:
            dst = None
    else:
        dst = None

    try:
        im = _load_rgb(img_path, max_side)
    except Exception:
        return img_path
    d = ImageDraw.Draw(im)
    W, H = im.size
    # 线宽跟着图的大小走,小图上 3px 就够粗,大图上要更粗才看得见
    lw = max(2, int(min(W, H) / 300))
    f = _load_font(max(13, int(min(W, H) / 45)))
    for b in boxes:
        cid = b["cid"]
        col = tuple(colors[cid % len(colors)]) if colors else (255, 64, 64)
        x1 = (b["xc"] - b["w"] / 2) * W
        y1 = (b["yc"] - b["h"] / 2) * H
        x2 = (b["xc"] + b["w"] / 2) * W
        y2 = (b["yc"] + b["h"] / 2) * H
        d.rectangle([x1, y1, x2, y2], outline=col, width=lw)
        nm = names[cid] if 0 <= cid < len(names) else str(cid)
        tb = d.textbbox((0, 0), nm, font=f)
        bw, bh = tb[2] - tb[0] + 8, tb[3] - tb[1] + 5
        ty = y1 - bh if y1 - bh >= 0 else y1       # 贴不下就画在框内
        d.rectangle([x1, ty, x1 + bw, ty + bh], fill=col)
        d.text((x1 + 4, ty + 1), nm, font=f, fill=(255, 255, 255))
    if dst:
        try:
            im.save(dst, quality=88)
            return dst
        except Exception:
            pass
    return img_path


def rewrite_warning(old, new):
    """判断模型是不是把描述【整个重写】了,而不是在原文上修订。

    只靠提示词要求"基于原文修改"是不够的 —— 模型经常自作主张换一套说法。
    这里做个粗判:原描述里的关键片段还在不在。返回 "" 表示看起来是修订,
    否则返回给用户看的提醒。

    判据是字符重合率(中文没有空格,按词切不可靠)。原描述越长,
    要求保留的比例越低 —— 长描述本来就有更多改写空间。
    """
    o = (old or "").strip()
    n = (new or "").strip()
    if not o:
        return ""                    # 原来是空的,那本来就是新写
    if not n:
        return "建议的描述是空的"
    so, sn = set(o), set(n)
    keep = len(so & sn) / max(1, len(so))
    thr = 0.65 if len(o) <= 20 else 0.5
    if keep < thr:
        return (f"这条改动很大,原描述的内容基本没保留"
                f"(只沿用了 {keep * 100:.0f}%)。"
                f"确认前请对比一下原文。")
    return ""


def render_thumb(img_path, boxes, colors, size=192, cache_dir=None):
    """画一张【缩略图尺寸】的带框图。专门给列表用。

    和 render_boxed 的区别:那个渲染到 1400px(为了双击放大时清晰),
    列表里只显示 96px,渲染 1400px 纯属浪费 —— 一张 4K 图要 81ms,
    100 张就是 8 秒的界面卡死。

    这里两个提速点:
      1) size 直接就是缩略图尺寸,不做无用的大图;
      2) im.draft():JPEG 可以在【解码阶段】就按 1/2、1/4、1/8 出图,
         根本不用把 4K 全部解出来再缩。这一条是大头,快 40 倍。
    """
    from PIL import Image, ImageDraw
    if not (img_path and os.path.isfile(img_path)):
        return img_path
    dst = None
    if cache_dir:
        try:
            os.makedirs(cache_dir, exist_ok=True)
            stem = os.path.splitext(os.path.basename(img_path))[0]
            sig = _box_sig(boxes)
            dst = os.path.join(cache_dir, f"{stem}_t{size}_{sig}.jpg")
            if os.path.exists(dst):
                return dst
        except Exception:
            dst = None
    try:
        im = Image.open(img_path)
        # 关键:让 JPEG 解码器直接吐小图(png 没有这个能力,会被忽略)
        try:
            im.draft("RGB", (size, size))
        except Exception:
            pass
        im = im.convert("RGB")
        im.thumbnail((size, size), Image.BILINEAR)   # 缩略图用双线性够了
        if boxes:
            d = ImageDraw.Draw(im)
            W, H = im.size
            lw = 2 if size <= 220 else 3
            for b in boxes:
                col = (tuple(colors[b["cid"] % len(colors)])
                       if colors else (255, 64, 64))
                x1 = (b["xc"] - b["w"] / 2) * W
                y1 = (b["yc"] - b["h"] / 2) * H
                x2 = (b["xc"] + b["w"] / 2) * W
                y2 = (b["yc"] + b["h"] / 2) * H
                d.rectangle([x1, y1, x2, y2], outline=col, width=lw)
            # 缩略图这么小,类别名写上去也看不清,干脆不写 —— 双击放大能看
        if dst:
            im.save(dst, quality=85)
            return dst
    except Exception:
        pass
    return img_path


def _box_sig(boxes):
    """框内容的短签名。框一变签名就变,缓存自动失效。

    只用数字算 hash:Python 对 str/bytes 的 hash 每次启动都不同
    (PYTHONHASHSEED),那样缓存跨次启动就永远命中不了。
    """
    return abs(hash(tuple(
        (b["cid"], round(b["xc"], 4), round(b["yc"], 4),
         round(b["w"], 4), round(b["h"], 4)) for b in (boxes or [])
    ))) % 10 ** 8
