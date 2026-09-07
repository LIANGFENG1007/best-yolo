#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI 的纯逻辑层 —— 不依赖 Qt,可单独测试。

界面(app.py)只负责画和转发;所有"会算错"的东西都放这里:
配置读写、命令行参数拼装、参数校验、进度解析、标签统计。
"""
import os
import re
import sys
import json
import glob
import time
import shutil

# 项目根目录(gui/ 的上一级)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 源码运行时仍把数据放在项目目录。系统安装包通过环境变量把用户数据
# 放到 ~/.local/share/best-yolo，避免普通用户向只读的 /opt 写文件。
_DATA_ENV = (os.environ.get("BEST_YOLO_DATA_DIR") or "").strip()
DATA_ROOT = (os.path.abspath(os.path.expanduser(_DATA_ENV))
             if _DATA_ENV else ROOT)
CONFIG_PATH = os.path.join(DATA_ROOT, "config.json")

# 常用模型:(值, 显示名)。顺序 = 推荐顺序。
# 显示名就是模型 id 本身,不加"最准/便宜"这类点评 —— 免得和接入点上
# 拉到的真实列表看起来是两种东西。
# 这是"兜底 + 常用"列表:没联网获取时用它,获取成功后这些仍会置顶显示。
API_MODELS = [
    ("qwen3-vl-plus",  "qwen3-vl-plus"),
    ("qwen3-vl-flash", "qwen3-vl-flash"),
    ("qwen-vl-max",    "qwen-vl-max"),
    ("qwen-vl-plus",   "qwen-vl-plus"),
]
# 常用模型的名字集合,用于在获取到的长列表里标出"常用"
COMMON_API_MODELS = [m for m, _ in API_MODELS]
LOCAL_MODELS = [
    ("Qwen/Qwen2.5-VL-3B-Instruct", "Qwen/Qwen2.5-VL-3B-Instruct"),
    ("Qwen/Qwen2.5-VL-7B-Instruct", "Qwen/Qwen2.5-VL-7B-Instruct"),
]

# 官方百炼的通用地址。用专属接入点的人在界面里改成自己的。
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# 首次启动的默认类别表,直接沿用 run.sh 里已经调好的 16 类
DEFAULT_CLASSES = [
    ("CA001", "眼镜或墨镜(有两片镜片和两条镜腿的眼镜框)", True),
    ("CA002", "透明胶带卷或封箱胶带卷(圆环形,中间是空心圆孔)", True),
    ("CA003", "遥控器(长条形塑料遥控器,表面有很多按键)", True),
    ("CA004", "卷尺(带金属圆形刻度盘的皮尺,或蓝色塑料外壳的自动卷尺)", True),
    ("CB001", "瓶装或袋装调味料(酱油/醋/番茄酱/盐等调料包装)", True),
    ("CB002", "筒装或碗装方便面(圆桶形纸质泡面桶,如康师傅/统一桶面)", True),
    ("CB003", "面包或吐司(松软的烘焙面包,常有透明塑料袋包装)", True),
    ("CB004", "薯片(圆筒形纸筒薯片如乐事Lays纸筒,或鼓起的袋装薯片膨化食品袋)", True),
    ("CC001", "罐装饮料(金属易拉罐,如可乐/啤酒/凉茶/绿茶罐)", True),
    ("CC002", "袋装饮料(软塑料袋装的饮料,如袋装豆奶/果汁袋)", True),
    ("CC003", "350ml小瓶装饮用水(较矮小的透明矿泉水瓶,瓶里是无色透明的水)", True),
    ("CC004", "550ml大瓶装饮用水(较高大的透明矿泉水瓶,明显比350ml高一截,瓶里是无色透明的水)", True),
    ("CD001", "石榴(红色或黄红色球形水果,顶端有花萼状凸起)", True),
    ("CD002", "柿子(橙红色扁圆形水果,表皮光滑)", True),
    ("CD003", "冬枣或青枣(小颗青绿色或青褐色的枣子)", True),
    ("CD004", "柚子(大个黄绿色球形或梨形柚子,明显比其它水果大)", True),
]
DEFAULT_NEGATIVE = ("香蕉、瓶装茶饮料或冰红茶(带彩色标签、液体是深褐色的塑料瓶,"
                    "不是饮用水)、桌上的紫色或蓝色垫布、地面和地砖、人的鞋子和裤腿、纸箱和包装盒")


def default_config():
    return {
        "images": "",
        "out": os.path.join(ROOT, "out"),
        "dataset": os.path.join(ROOT, "dataset"),
        # classes: [{"name","desc","on"}, ...] 顺序 = 类别 id
        "classes": [{"name": n, "desc": d, "on": o} for n, d, o in DEFAULT_CLASSES],
        "negative": DEFAULT_NEGATIVE,
        "backend": "api",
        "model": "qwen3-vl-plus",
        "max_pixels": 2000000,
        # 并发别默认给太大:视觉模型的 QPS 配额通常很小,
        # 50 并发几乎必然被限流(429)导致大批图片失败。
        "workers": 8,
        "qps": 0,              # 0=按并发自动估算;限流多就手填 2
        "retries": 5,          # 被限流时重试几次
        "skip_done": True,     # 重跑时跳过已标好的图,不重复花钱
        "preview_limit": 20,
        "coord_scale": 0,      # 0=自动判定
        "tiles": "",           # ""=不切片, 如 "2x2"
        "overlap": 0.15,
        "upscale": 2.0,
        "base_url": DEFAULT_BASE_URL,
        "api_key": "",         # 必填:不内置任何 key(这套东西会分发出去)
        "backup_old": True,
        "val_ratio": 0.2,
        "seed": 0,
        # 上次从接入点拉到的模型列表(缓存下来,下次打开不用重新联网也有列表)
        "model_cache": [],
        "autosave": False,     # 改框时自动保存
        "autosave_min": 1,     # 自动保存间隔(分钟)
    }


# ---------------- 项目 ----------------
# 一个项目 = 一套独立的配置(图片目录/类别表/输出目录…)。
# 存在 projects/<名字>/config.json,互不干扰;换项目就是换一份配置。
PROJECTS_DIR = os.path.join(DATA_ROOT, "projects")
STATE_PATH = os.path.join(DATA_ROOT, ".gui_state.json")
BAD_NAME = r'[\\/:*?"<>|]'


def project_dir(name):
    return os.path.join(PROJECTS_DIR, name)


def project_config_path(name):
    return os.path.join(project_dir(name), "config.json")


def check_project_name(name):
    """返回错误说明,合法则返回 ""。"""
    n = (name or "").strip()
    if not n:
        return "项目名不能为空"
    if len(n) > 60:
        return "项目名太长(最多 60 字)"
    if re.search(BAD_NAME, n):
        return '项目名不能包含 \\ / : * ? " < > |'
    if n in (".", ".."):
        return "项目名不合法"
    return ""


def list_projects():
    """已有项目,按最近使用排前面。返回 [{"name","images","n_labels","used"}]。"""
    out = []
    try:
        names = sorted(os.listdir(PROJECTS_DIR))
    except Exception:
        return out
    for n in names:
        if n.startswith("."):
            continue          # .trash_* 是删除残骸,不算项目
        cp = project_config_path(n)
        if not os.path.isfile(cp):
            continue
        info = {"name": n, "images": "", "n_labels": 0, "used": 0.0}
        try:
            with open(cp, encoding="utf-8") as f:
                c = json.load(f)
            info["images"] = c.get("images", "") or ""
            out_dir = c.get("out", "") or ""
            if out_dir:
                info["n_labels"] = len(glob.glob(
                    os.path.join(out_dir, "labels", "*.txt")))
        except Exception:
            pass          # 配置坏了也要能列出来,好让用户删掉它
        try:
            info["used"] = os.path.getmtime(cp)
        except Exception:
            pass
        out.append(info)
    out.sort(key=lambda d: -d["used"])
    return out


# 换项目时【保留】的字段:模型与性能那一块,以及导出参数。
# 这些是"你的账号/机器"属性,跟具体数据集无关,每建一个项目重填一遍纯属折磨。
CARRY_KEYS = (
    "backend", "model", "max_pixels", "workers", "qps", "retries",
    "skip_done", "preview_limit", "coord_scale", "tiles", "overlap",
    "upscale", "backup_old", "val_ratio", "seed", "autosave",
    "autosave_min",
)


def blank_project_config(carry_from=None, proj_dir=""):
    """一个新项目的初始配置:内容全空,只继承模型与性能设置。

    一个项目对应一套内容 —— 图片目录、类别表、负样本都从零开始,
    不能从别的项目带过来,否则会把上一个项目的类别表误当成这个项目的。
    """
    cfg = default_config()
    if carry_from:
        for k in CARRY_KEYS:
            if k in carry_from:
                cfg[k] = carry_from[k]
    cfg["images"] = ""          # 必须自己选
    cfg["classes"] = []         # 类别表清空
    cfg["negative"] = ""        # 负样本描述清空
    # 输出目录自动放在项目文件夹里,不用用户操心,也不会几个项目互相覆盖
    cfg["out"] = os.path.join(proj_dir, "out") if proj_dir else ""
    cfg["dataset"] = os.path.join(proj_dir, "dataset") if proj_dir else ""
    return cfg


def create_project(name, carry_from=None):
    """新建项目。返回该项目的配置路径;名字已存在会抛 ValueError。"""
    err = check_project_name(name)
    if err:
        raise ValueError(err)
    name = name.strip()
    d = project_dir(name)
    if os.path.exists(d):
        raise ValueError(f"项目「{name}」已经存在了")
    os.makedirs(d, exist_ok=True)
    cfg = blank_project_config(carry_from, d)
    save_project_config(cfg, project_config_path(name))
    return project_config_path(name)


def delete_project(name):
    """删除项目目录(含它的标签和数据集)。返回删掉的路径。

    先把目录改名挪走再删:rmtree 可能因为文件被占用/权限问题半途失败,
    那样项目目录还在,列表里就仍然看得到这个"已删除"的项目。
    改名是原子操作,一旦成功它就绝不会再出现在列表里 —— 即使后面
    清理残骸失败,也只是留下一个 .trash_ 开头的垃圾目录。
    """
    err = check_project_name(name)
    if err:
        raise ValueError(err)
    d = project_dir(name.strip())
    if not os.path.isdir(d):
        raise ValueError(f"项目「{name}」不存在")
    trash = os.path.join(PROJECTS_DIR,
                         f".trash_{name.strip()}_{int(time.time())}")
    try:
        os.rename(d, trash)
    except Exception:
        # 连改名都做不到(目录被占用),那就老实报错,别假装删掉了
        shutil.rmtree(d)
        return d
    shutil.rmtree(trash, ignore_errors=True)   # 删不干净也没关系,已经不在列表里
    return d


def purge_trash():
    """顺手清理上次没删干净的残骸。失败就算了,不影响使用。"""
    try:
        for n in os.listdir(PROJECTS_DIR):
            if n.startswith(".trash_"):
                shutil.rmtree(os.path.join(PROJECTS_DIR, n), ignore_errors=True)
    except Exception:
        pass


def rename_project(old, new):
    err = check_project_name(new)
    if err:
        raise ValueError(err)
    src, dst = project_dir(old), project_dir(new.strip())
    if not os.path.isdir(src):
        raise ValueError(f"项目「{old}」不存在")
    if os.path.exists(dst):
        raise ValueError(f"项目「{new}」已经存在了")
    os.rename(src, dst)
    return dst


# 这些是"账号/机器"属性,不属于任何项目,存在全局 state 里。
# 以前它们只存在项目配置里,于是:还没建项目就填 key -> 没地方存;
# 把项目删了 -> key 跟着消失。这就是"key 时不时丢"的原因。
GLOBAL_KEYS = ("api_key", "base_url", "model_cache")


def load_globals():
    """读全局设置(API Key、接入点、模型缓存)。"""
    s = load_state()
    g = s.get("globals")
    return g if isinstance(g, dict) else {}


def save_globals(cfg, allow_clear=()):
    """把配置里的账号级字段存到全局,和项目无关。

    空值默认【不覆盖】已存的值。原因:同时开着两个窗口,或者关窗时交上来
    一份旧的界面状态,都可能拿一个空 key 把存好的 key 抹掉 —— 这就是
    "输好的 key 下次打开没了"的另一半原因。
    只有用户主动点「清除」时才传 allow_clear,明确允许清空。
    """
    g = load_globals()
    for k in GLOBAL_KEYS:
        if k not in cfg:
            continue
        v = cfg[k]
        if not v and k not in allow_clear and g.get(k):
            continue          # 空值不许覆盖已经存好的
        g[k] = v
    save_state(globals=g)


def load_state():
    """记住上次打开的是哪个项目。"""
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except Exception:
        return {}


def save_state(**kw):
    s = load_state()
    s.update(kw)
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_PATH)
        os.chmod(STATE_PATH, 0o600)     # 内含 API Key，不能让其他本机用户读取
    except Exception:
        pass          # 记不住也不该影响使用


def project_label_count(name):
    """项目已标了多少张(用于列表上显示进度)。"""
    try:
        with open(project_config_path(name), encoding="utf-8") as f:
            c = json.load(f)
        return len(glob.glob(os.path.join(c.get("out", ""), "labels", "*.txt")))
    except Exception:
        return 0


def load_config(path=None):
    """读配置;缺字段用默认值补齐(以后加新字段不会让旧配置崩)。
    path=None 时用模块级 CONFIG_PATH —— 在调用时才取值,便于测试重定向。"""
    path = path or CONFIG_PATH
    cfg = default_config()
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            for k, v in saved.items():
                if k in cfg:
                    cfg[k] = v
    except FileNotFoundError:
        pass
    except Exception:
        pass          # 配置坏了就当默认,不要让软件打不开
    # 注意 fill_default=False:新项目的类别表是【故意空着】的,
    # 不能自动填回 16 个默认类 —— 那样用户会以为项目没清空。
    cfg["classes"] = _normalize_classes(cfg.get("classes"), fill_default=False)
    return cfg


def parse_classes_file(path):
    """读 classes.txt / data.yaml,返回类别名列表(顺序 = 类别 id)。

    两种格式都认:
      - classes.txt:一行一个名字,行号就是 id(YOLO 生态通用)
      - data.yaml:取 names 字段,支持 {0: a, 1: b} 和 [a, b] 两种写法

    读不出来就抛 ValueError,让界面能说清原因。
    """
    if not path or not os.path.isfile(path):
        raise ValueError("文件不存在")
    try:
        with open(path, encoding="utf-8-sig") as f:
            text = f.read()
    except Exception as e:
        raise ValueError(f"读不了这个文件:{e}")

    if os.path.splitext(path)[1].lower() in (".yaml", ".yml"):
        try:
            import yaml
            data = yaml.safe_load(text) or {}
        except Exception as e:
            raise ValueError(f"YAML 解析失败:{e}")
        names = data.get("names") if isinstance(data, dict) else None
        if isinstance(names, dict):
            # 键是 id,要按数字排序而不是字符串排序(10 不能排在 2 前面)
            try:
                items = sorted(names.items(), key=lambda kv: int(kv[0]))
            except (TypeError, ValueError):
                items = sorted(names.items(), key=lambda kv: str(kv[0]))
            out = [str(v).strip() for _, v in items]
        elif isinstance(names, list):
            out = [str(v).strip() for v in names]
        else:
            raise ValueError("这个 data.yaml 里没有 names 字段")
    else:
        # 逗号分隔的一行也认(有人习惯那么写)
        lines = [ln.strip() for ln in text.splitlines()]
        lines = [ln for ln in lines if ln and not ln.startswith("#")]
        if len(lines) == 1 and "," in lines[0]:
            out = [c.strip() for c in lines[0].split(",")]
        else:
            out = lines
    out = [n for n in out if n]
    if not out:
        raise ValueError("这个文件里没有类别名")
    return out


def _normalize_classes(raw, fill_default=True):
    out = []
    for it in (raw or []):
        if isinstance(it, dict) and str(it.get("name", "")).strip():
            out.append({"name": str(it["name"]).strip(),
                        "desc": str(it.get("desc", "") or "").strip(),
                        "on": bool(it.get("on", True))})
    if out or not fill_default:
        return out
    return [{"name": n, "desc": d, "on": o} for n, d, o in DEFAULT_CLASSES]


def save_config(cfg, path=None):
    path = path or CONFIG_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)     # 原子替换,写坏了不会毁掉原配置


def project_config_only(cfg):
    """移除账号级字段，避免 API Key 在每个项目配置中重复落盘。"""
    return {k: v for k, v in dict(cfg or {}).items() if k not in GLOBAL_KEYS}


def save_project_config(cfg, path):
    save_config(project_config_only(cfg), path)


# ---------------- API Key 与模型列表 ----------------
def builtin_api_key():
    """以前会从 autolabel_qwen.py 里读内置的默认 key 当兜底。

    现在不内置任何 key —— 这套东西要分发给别人,代码里写死自己的 key
    等于把账单交出去。保留这个函数只为兼容调用点,永远返回空。
    """
    return ""


def mask_key(key):
    """把 key 显示成 sk-abcd****wxyz 的样子。
    只为了"别人瞄一眼看不到",不是加密 —— 配置文件里仍是明文,
    所以 config.json 已加进 .gitignore,不要把它发给别人。"""
    k = (key or "").strip()
    if not k:
        return ""
    if len(k) <= 12:
        return k[:2] + "*" * max(1, len(k) - 2)
    return f"{k[:6]}{'*' * 8}{k[-4:]}"


def looks_like_key(key):
    """粗略判断像不像一个 key(只挡明显的手滑,不做严格校验)。"""
    k = (key or "").strip()
    return len(k) >= 16 and " " not in k and "\n" not in k


def fetch_models(base_url, api_key, timeout=20):
    """联网拉取接入点支持的模型列表(OpenAI 兼容的 GET /v1/models)。

    返回 (models, error):
      models: ["qwen3-vl-plus", ...] 按名字排序,失败时为 []
      error:  失败原因(中文),成功时为 ""

    注意:这个函数会联网,必须放在后台线程里调用,否则界面会卡住。
    """
    base = (base_url or "").strip() or DEFAULT_BASE_URL
    key = (api_key or "").strip()
    if not key:
        return [], "还没填 API Key"
    try:
        import httpx
        from openai import OpenAI
    except Exception as e:
        return [], f"缺少依赖: {e}"
    try:
        # trust_env=False:和标注脚本一致,绝不走系统代理
        # (系统里的 ALL_PROXY=socks://... 会让 httpx 直接建不起来)
        client = OpenAI(api_key=key, base_url=base,
                        http_client=httpx.Client(trust_env=False, timeout=float(timeout)))
        got = client.models.list()
        names = []
        for m in got:
            mid = getattr(m, "id", None) or (m.get("id") if isinstance(m, dict) else None)
            if mid:
                names.append(str(mid))
        if not names:
            return [], "接入点返回了空列表"
        return sorted(set(names)), ""
    except Exception as e:
        return [], _friendly_api_error(e)


def _friendly_api_error(e):
    """把 SDK 的异常翻译成一句能照着做的中文。"""
    s = str(e)
    low = s.lower()
    if "401" in s or "invalid_api_key" in low or "unauthorized" in low:
        return "API Key 不对(401),检查有没有复制错或多了空格"
    if "403" in s or "forbidden" in low:
        return "没有权限(403),这个 Key 可能没开通该接入点"
    if "404" in s or "not found" in low:
        # 百炼的专属接入点(ws-xxx.maas.aliyuncs.com)常常只开 /chat/completions,
        # 不实现 /v1/models。这不是地址写错,别误导用户去改地址。
        return ("这个接入点不支持列出模型(404)。专属接入点通常只开放对话接口 —— "
                "直接从下面的常用模型里选就行,或手动打字填模型名")
    if "timeout" in low or "timed out" in low:
        return "连接超时,检查网络"
    if "proxy" in low:
        return f"代理配置有问题:{s[:120]}"
    if "connect" in low or "resolve" in low or "name or service" in low:
        return "连不上接入点,检查网络或地址是否正确"
    return s[:160]


def merge_model_list(fetched, current=None):
    """把拉到的模型排成好用的顺序:常用的(且接入点确实支持的)在前,其余按名字排。
    返回 [(值, 显示名, 是否常用)]。"""
    fetched = list(fetched or [])
    fset = set(fetched)
    out, seen = [], set()
    label = {m: t for m, t in API_MODELS}
    # 1) 常用且接入点支持的,置顶
    for m in COMMON_API_MODELS:
        if m in fset:
            out.append((m, label.get(m, m), True))
            seen.add(m)
    # 2) 其余按名字排;视觉模型(带 vl)排在前面,标注用得上的是它们
    rest = sorted(m for m in fetched if m not in seen)
    for m in [x for x in rest if "vl" in x.lower()] + \
             [x for x in rest if "vl" not in x.lower()]:
        out.append((m, m, False))
        seen.add(m)
    # 3) 当前选中的模型即使不在列表里也要保留,否则会被悄悄换掉。
    #    显示名仍然只是模型 id(不加说明),"列表里没有"这件事放到 tooltip 里讲。
    if current and current not in seen:
        out.insert(0, (current, current, False))
    return out


# ---------------- 参数校验 ----------------
def validate(cfg):
    """返回错误信息列表;空列表 = 可以跑。"""
    errs = []
    imgs = cfg.get("images") or ""
    if not imgs:
        errs.append("没选图片文件夹")
    elif not os.path.isdir(imgs):
        errs.append(f"图片文件夹不存在:{imgs}")
    elif not count_images(imgs):
        errs.append(f"文件夹里没有图片(支持 jpg/png/bmp/webp):{imgs}")

    classes = cfg.get("classes") or []
    if not classes:
        errs.append("类别表是空的")
    names = [c["name"] for c in classes]
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        errs.append("类别名重复:" + "、".join(sorted(dup)))
    for c in classes:
        # 这两个字符是 --desc 的分隔符,混进描述会让参数解析错位
        if "|" in c["desc"]:
            errs.append(f"{c['name']} 的描述里不能有 | 符号(它是分隔符)")
        if "=" in c["name"] or "|" in c["name"] or "," in c["name"]:
            errs.append(f"类别名 {c['name']!r} 不能含 = | , 这些字符")
    if not [c for c in classes if c["on"]]:
        errs.append("一个类别都没勾选,至少勾一个")
    if not cfg.get("out"):
        errs.append("没设输出目录")
    return errs


def count_images(folder):
    exts = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
    try:
        return len([f for f in os.listdir(folder) if f.lower().endswith(exts)])
    except Exception:
        return 0


# ---------------- 命令行参数拼装 ----------------
def build_desc(classes):
    """只给勾选且有描述的类拼 --desc。"""
    parts = [f"{c['name']}={c['desc']}" for c in classes if c["on"] and c["desc"]]
    return "|".join(parts)


def build_only(classes):
    """全勾选 -> 返回 ""(不传 --only);部分勾选 -> 逗号串。"""
    on = [c["name"] for c in classes if c["on"]]
    return "" if len(on) == len(classes) else ",".join(on)


def build_label_args(cfg, limit=0, locks_file=""):
    """拼 autolabel_qwen.py 的参数(不含 python 和脚本名)。

    locks_file:上锁清单。传了的话脚本会跳过这些图,而且不占 --limit 名额。
    """
    classes = cfg["classes"]
    args = [
        "--images", cfg["images"],
        "--out", cfg["out"],
        "--classes", ",".join(c["name"] for c in classes),
        "--backend", cfg["backend"],
        "--model", cfg["model"],
        "--max-pixels", str(int(cfg["max_pixels"])),
        "--workers", str(int(cfg["workers"])),
        "--retries", str(int(cfg.get("retries", 5))),
    ]
    if float(cfg.get("qps", 0) or 0) > 0:
        args += ["--qps", str(float(cfg["qps"]))]
    if cfg.get("skip_done"):
        args += ["--skip-done"]
    desc = build_desc(classes)
    if desc:
        args += ["--desc", desc]
    only = build_only(classes)
    if only:
        args += ["--only", only]
    if (cfg.get("negative") or "").strip():
        args += ["--negative", cfg["negative"].strip()]
    # coord_scale: 0=自动判定(不传参数), -1=强制像素, >0=强制该除数
    cs = float(cfg.get("coord_scale") or 0)
    if cs == -1:
        args += ["--coord-scale", "pixel"]
    elif cs > 0:
        args += ["--coord-scale", str(cs)]
    if (cfg.get("tiles") or "").strip():
        args += ["--tiles", cfg["tiles"].strip(),
                 "--overlap", str(float(cfg["overlap"])),
                 "--upscale", str(float(cfg["upscale"]))]
    if limit and int(limit) > 0:
        args += ["--limit", str(int(limit))]
    # 上锁保护:手动改好的图不参与重跑
    if locks_file and os.path.exists(locks_file):
        args += ["--locks", locks_file]
    return args


def build_dataset_args(cfg):
    return [
        "--images", cfg["images"],
        "--labels", os.path.join(cfg["out"], "labels"),
        "--out", cfg["dataset"],
        "--classes", ",".join(c["name"] for c in cfg["classes"]),
        "--ext", "auto",
        "--val-ratio", str(float(cfg.get("val_ratio", 0.2))),
        "--seed", str(int(cfg.get("seed", 0))),
    ]


def script_path(name):
    return os.path.join(ROOT, name)


def child_env(cfg):
    """给子进程的环境变量。
    - PYTHONUNBUFFERED:让日志实时吐出来,否则 GUI 日志窗要等程序结束才有内容
    - 清掉代理:百炼接入点是国内地址,而且 socks:// 写法会让 httpx 直接报错
    """
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
              "HTTPS_PROXY", "https_proxy", "FTP_PROXY", "ftp_proxy"):
        env.pop(k, None)
    if (cfg.get("base_url") or "").strip():
        env["QWEN_BASE_URL"] = cfg["base_url"].strip()
    if (cfg.get("api_key") or "").strip():
        env["DASHSCOPE_API_KEY"] = cfg["api_key"].strip()
    return env


# ---------------- 日志/进度解析 ----------------
# 匹配 "[3/20] xxx.png -> 5 个框" 和 "[3/20] xxx.png 失败: ..."
_PROG = re.compile(r"^\[(\d+)/(\d+)\]\s+(.+?)(?:\s*->\s*(\d+)\s*个框|\s*失败[::]\s*(.*))?$")


def parse_progress(line):
    """解析一行进度。返回 dict(done,total,name,boxes,error) 或 None。"""
    m = _PROG.match((line or "").strip())
    if not m:
        return None
    done, total, name, boxes, err = m.groups()
    return {"done": int(done), "total": int(total), "name": name,
            "boxes": int(boxes) if boxes else 0,
            "error": err if err is not None else None}


def parse_total(line):
    """从 "共 109 张图, 后端=api, ..." 里取总数。"""
    m = re.match(r"^共\s+(\d+)\s+张图", (line or "").strip())
    return int(m.group(1)) if m else None


# ---------------- 结果统计(直接读标签文件,不依赖日志) ----------------
def read_label_stats(out_dir, classes):
    """统计 out/labels 里各类别框数。返回 dict:
      per_class: [{"id","name","desc","count","on"}]
      total_boxes / n_files / n_empty / warn(坐标异常提示)
    """
    labels_dir = os.path.join(out_dir, "labels")
    counts, n_files, n_empty = {}, 0, 0
    n_box = degen = 0
    for f in sorted(glob.glob(os.path.join(labels_dir, "*.txt"))):
        n_files += 1
        try:
            with open(f, encoding="utf-8") as fh:
                body = fh.read().strip()
        except Exception:
            continue
        if not body:
            n_empty += 1
            continue
        for ln in body.splitlines():
            parts = ln.split()
            if not parts:
                continue
            try:
                cid = int(parts[0])
            except ValueError:
                continue
            counts[cid] = counts.get(cid, 0) + 1
            # 顺手查坐标是否退化(口径设错的典型症状:框被 clamp 成满幅)
            if len(parts) == 5:
                n_box += 1
                try:
                    bw, bh = float(parts[3]), float(parts[4])
                    if bw >= 0.999 and bh >= 0.999:
                        degen += 1
                except ValueError:
                    pass
    per_class = []
    for i, c in enumerate(classes):
        per_class.append({"id": i, "name": c["name"], "desc": c["desc"],
                          "on": c["on"], "count": counts.get(i, 0)})
    warn = ""
    if n_box and degen / n_box > 0.3:
        warn = (f"{degen}/{n_box} 个框退化成了满幅,画出来看不见 —— "
                "坐标口径设错了。把「高级选项 → 坐标口径」改回「自动判定」后重标。")
    return {"per_class": per_class, "total_boxes": sum(counts.values()),
            "n_files": n_files, "n_empty": n_empty, "warn": warn}


def list_vis_images(out_dir):
    d = os.path.join(out_dir, "vis")
    exts = (".jpg", ".jpeg", ".png")
    try:
        return sorted(os.path.join(d, f) for f in os.listdir(d)
                      if f.lower().endswith(exts))
    except Exception:
        return []


IMG_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")


def list_source_images(images_dir):
    """列出待标注目录里的所有图片(递归子目录)。

    这是"纯手动标注"的入口:不跑 AI 也能把整个文件夹的图都摆出来逐张画框。
    """
    if not images_dir or not os.path.isdir(images_dir):
        return []
    out = []
    for p in glob.glob(os.path.join(images_dir, "**", "*"), recursive=True):
        if os.path.splitext(p)[1].lower() in IMG_EXTS and os.path.isfile(p):
            out.append(p)
    return sorted(out)


def list_editable_images(images_dir, out_dir):
    """标注页要显示的图片清单 = 原图目录里的所有图。

    返回 [(显示名, 原图路径, 标签路径, 已有框数)]。
    没跑过 AI 的图也会列出来(框数 0),这样可以纯手动标。
    """
    rows = []
    for p in list_source_images(images_dir):
        lb = label_path_for(out_dir, p)
        n = len(read_boxes(lb)) if os.path.exists(lb) else -1
        rows.append((os.path.basename(p), p, lb, n))
    return rows


# ---------------- 人工修改框(读写 YOLO 标签) ----------------
def label_path_for(out_dir, img_path):
    """由图片路径推出对应的标签文件路径(同名 .txt)。"""
    stem = os.path.splitext(os.path.basename(img_path))[0]
    return os.path.join(out_dir, "labels", stem + ".txt")


def source_image_for(img_path, images_dir):
    """给一张 vis 预览图,找回原始图片(画框要画在干净的原图上)。

    vis 图是标注脚本画好框的产物,不能拿它当底图再画一遍 —— 那样会
    出现两层框。所以按文件名去原图目录里找。
    """
    stem = os.path.splitext(os.path.basename(img_path))[0]
    if images_dir and os.path.isdir(images_dir):
        for ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp",
                    ".PNG", ".JPG", ".JPEG"):
            p = os.path.join(images_dir, stem + ext)
            if os.path.exists(p):
                return p
        # 有些流程会把图放在子目录里
        for p in glob.glob(os.path.join(images_dir, "**", stem + ".*"),
                           recursive=True):
            if os.path.splitext(p)[1].lower() in (".png", ".jpg", ".jpeg",
                                                  ".bmp", ".webp"):
                return p
    return None


def read_boxes(label_file):
    """读 YOLO 标签 -> [{"cid","xc","yc","w","h"}](都是 0~1 归一化)。
    读不到或格式坏的行直接跳过,不让界面崩。"""
    out = []
    try:
        with open(label_file, encoding="utf-8") as f:
            for ln in f:
                p = ln.split()
                if len(p) < 5:
                    continue
                try:
                    cid = int(float(p[0]))
                    xc, yc, w, h = (float(v) for v in p[1:5])
                except ValueError:
                    continue
                out.append({"cid": cid, "xc": xc, "yc": yc, "w": w, "h": h})
    except Exception:
        pass
    return out


def write_boxes(label_file, boxes):
    """把框写回 YOLO 标签文件(原子替换,写坏了不会毁掉原文件)。
    坐标会被夹到 0~1 并保证宽高 > 0,避免写出训练时报错的标签。"""
    os.makedirs(os.path.dirname(label_file), exist_ok=True)
    lines = []
    for b in boxes:
        xc, yc = _clamp01(b["xc"]), _clamp01(b["yc"])
        w, h = _clamp01(b["w"]), _clamp01(b["h"])
        if w <= 1e-6 or h <= 1e-6:
            continue                      # 拖成一条线的框直接丢掉
        # 保证框不越界:中心 ± 半宽 都要落在 [0,1]
        w = min(w, 2 * xc, 2 * (1 - xc))
        h = min(h, 2 * yc, 2 * (1 - yc))
        if w <= 1e-6 or h <= 1e-6:
            continue
        lines.append(f"{int(b['cid'])} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}")
    tmp = label_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))
    os.replace(tmp, label_file)
    return len(lines)


def _clamp01(v):
    return 0.0 if v < 0 else (1.0 if v > 1 else float(v))


def boxes_to_pixels(boxes, w, h):
    """归一化框 -> 像素矩形 [(cid, x1,y1,x2,y2), ...],给界面画图用。"""
    out = []
    for b in boxes:
        bw, bh = b["w"] * w, b["h"] * h
        x1, y1 = b["xc"] * w - bw / 2, b["yc"] * h - bh / 2
        out.append((b["cid"], x1, y1, x1 + bw, y1 + bh))
    return out


def pixels_to_box(cid, x1, y1, x2, y2, w, h):
    """像素矩形 -> 归一化框。会自动把反向拖出来的坐标摆正。"""
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return {"cid": int(cid),
            "xc": _clamp01(((x1 + x2) / 2) / max(1, w)),
            "yc": _clamp01(((y1 + y2) / 2) / max(1, h)),
            "w": _clamp01(abs(x2 - x1) / max(1, w)),
            "h": _clamp01(abs(y2 - y1) / max(1, h))}


def has_results(out_dir):
    return bool(glob.glob(os.path.join(out_dir, "labels", "*.txt")))


def backup_dir(path):
    """把已存在的目录改名成 <名>_旧_月日_时分,返回新名;不存在则返回 None。"""
    if not os.path.isdir(path):
        return None
    import datetime
    stamp = datetime.datetime.now().strftime("%m%d_%H%M")
    dst = f"{path}_旧_{stamp}"
    n = 1
    while os.path.exists(dst):
        n += 1
        dst = f"{path}_旧_{stamp}_{n}"
    os.rename(path, dst)
    return dst


def fmt_px(n):
    """2000000 -> '200万'"""
    n = int(n)
    return f"{n / 10000:.0f}万" if n >= 10000 else str(n)


# ================== AI 补充提示词:基线快照 + 改动史 ==================
# 核心问题是"跟哪一版比"。自动标注跑完的那一刻,把 labels/ 整份复制成
# 快照(baseline)。之后你手动改、保存多少次都只动当前标签,快照不动 ——
# 所以存 1 次和存 100 次,对比结果完全一样。下次重跑自动标注才刷新快照。

def baseline_dir(proj_dir):
    return os.path.join(proj_dir, "prompt_ai", "baseline")


def history_path(proj_dir):
    return os.path.join(proj_dir, "prompt_ai", "history.json")


def snapshot_baseline(proj_dir, out_dir):
    """把当前 labels/ 存成基线快照。返回存了几个文件。

    在"自动标注刚跑完"时调用 —— 那一刻磁盘上的标签就是纯 AI 的结果。
    """
    src = os.path.join(out_dir or "", "labels")
    dst = baseline_dir(proj_dir)
    if not os.path.isdir(src):
        return 0
    import shutil
    try:
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        os.makedirs(dst, exist_ok=True)
    except Exception:
        return 0
    n = 0
    for p in glob.glob(os.path.join(src, "*.txt")):
        try:
            shutil.copy2(p, os.path.join(dst, os.path.basename(p)))
            n += 1
        except Exception:
            pass
    # 记下快照时间和当时的类别表:模型要知道"那一版用的是什么提示词"
    try:
        cfg = load_config(project_config_path(os.path.basename(proj_dir))) \
            if os.path.isdir(proj_dir) else {}
    except Exception:
        cfg = {}
    meta = {
        "at": _now_str(),
        "n_files": n,
        "classes": cfg.get("classes") or [],
        "negative": cfg.get("negative") or "",
    }
    try:
        os.makedirs(os.path.dirname(baseline_meta_path(proj_dir)), exist_ok=True)
        with open(baseline_meta_path(proj_dir), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return n


def baseline_meta_path(proj_dir):
    return os.path.join(proj_dir, "prompt_ai", "baseline.json")


def baseline_meta(proj_dir):
    try:
        with open(baseline_meta_path(proj_dir), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def has_baseline(proj_dir):
    d = baseline_dir(proj_dir)
    return os.path.isdir(d) and bool(glob.glob(os.path.join(d, "*.txt")))


def baseline_label_for(proj_dir, img_path):
    """这张图在基线快照里的标签路径(可能不存在)。"""
    stem = os.path.splitext(os.path.basename(img_path))[0]
    return os.path.join(baseline_dir(proj_dir), stem + ".txt")


def _now_str():
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_history(proj_dir):
    """读改动史:[{at, class, old, new, reason, accepted}, ...]

    这是"记忆"。下一轮会把它一起发给模型,它才知道哪些描述你已经调过、
    不要来回改,也能看出哪些建议你拒绝过。
    """
    try:
        with open(history_path(proj_dir), encoding="utf-8") as f:
            h = json.load(f)
        return h if isinstance(h, list) else []
    except Exception:
        return []


def append_history(proj_dir, entries):
    """往改动史里追加几条。entries 是 dict 列表。"""
    if not entries:
        return
    h = load_history(proj_dir)
    at = _now_str()
    for e in entries:
        e = dict(e)
        e.setdefault("at", at)
        h.append(e)
    # 只留最近 200 条:再多对模型也没帮助,还会把 prompt 撑爆
    h = h[-200:]
    try:
        os.makedirs(os.path.dirname(history_path(proj_dir)), exist_ok=True)
        tmp = history_path(proj_dir) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(h, f, ensure_ascii=False, indent=2)
        os.replace(tmp, history_path(proj_dir))
    except Exception:
        pass


def diff_boxes(base_boxes, cur_boxes, iou_thr=0.5):
    """对比两份框,返回改动摘要。

    做法:按类别 + IoU 配对。配上的看框有没有明显移动,配不上的就是
    "AI 多标了"(base 里有、现在没了)或"漏标了"(现在有、base 里没有)。
    iou_thr 0.5 是常规阈值:低于它基本可以认为不是同一个框。
    """
    def to_xyxy(b):
        return (b["xc"] - b["w"] / 2, b["yc"] - b["h"] / 2,
                b["xc"] + b["w"] / 2, b["yc"] + b["h"] / 2)

    def iou(a, b):
        ax1, ay1, ax2, ay2 = to_xyxy(a)
        bx1, by1, bx2, by2 = to_xyxy(b)
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
        inter = iw * ih
        ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
        return inter / ua if ua > 0 else 0.0

    base = list(base_boxes or [])
    cur = list(cur_boxes or [])
    used_cur = set()
    matched, moved, relabeled = [], [], []
    for bi, b in enumerate(base):
        best, best_i = 0.0, -1
        for ci, c in enumerate(cur):
            if ci in used_cur:
                continue
            v = iou(b, c)
            if v > best:
                best, best_i = v, ci
        if best_i >= 0 and best >= iou_thr:
            used_cur.add(best_i)
            c = cur[best_i]
            if c["cid"] != b["cid"]:
                relabeled.append((b, c))
            elif best < 0.85:
                moved.append((b, c))       # 同类但框调整过
            else:
                matched.append((b, c))
    # 配不上的留给下面统一算(不在这里处理,避免重复判断)
    # base 里配不上任何当前框的 -> 你把它删了(AI 标错或多标)
    deleted = [b for b in base
               if not any(iou(b, cur[ci]) >= iou_thr for ci in used_cur)]
    added = [c for ci, c in enumerate(cur) if ci not in used_cur]
    return {
        "n_base": len(base), "n_cur": len(cur),
        "kept": len(matched), "moved": moved,
        "relabeled": relabeled, "deleted": deleted, "added": added,
    }


# ================== 上锁:保护改好的标签不被自动标注覆盖 ==================
# 规则:手动改过的图默认上锁,AI 标的默认不上锁。上了锁的图在"预览标注"和
# "标注全部"时都会被跳过(预览张数也不算它),避免辛苦改好的框被重跑冲掉。

def locks_path(proj_dir):
    return os.path.join(proj_dir, "locks.json")


def load_locks(proj_dir):
    """返回上锁的图片名集合(只存文件名,换目录也不失效)。"""
    try:
        with open(locks_path(proj_dir), encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, list):
            return set(str(x) for x in d)
        if isinstance(d, dict):
            return set(str(x) for x in d.get("locked") or [])
    except Exception:
        pass
    return set()


def save_locks(proj_dir, names):
    try:
        os.makedirs(proj_dir, exist_ok=True)
        tmp = locks_path(proj_dir) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"locked": sorted(names)}, f,
                      ensure_ascii=False, indent=2)
        os.replace(tmp, locks_path(proj_dir))
        return True
    except Exception:
        return False


def lock_key(path):
    """上锁用的键:图片文件名(不含目录)。"""
    return os.path.basename(path or "")


def restore_locked_labels(backup_out, out_dir, locked):
    """备份 out/ 之后,把上锁的标签从备份里复制回来。

    backup_dir() 是把整个 out/ 改名,上锁的标签会跟着被搬走 ——
    虽然文件没丢,但界面上看就是"我改好的框不见了"。所以要复制回来。
    返回复制了几个。
    """
    if not (backup_out and locked and os.path.isdir(backup_out)):
        return 0
    src = os.path.join(backup_out, "labels")
    dst = os.path.join(out_dir, "labels")
    if not os.path.isdir(src):
        return 0
    import shutil
    os.makedirs(dst, exist_ok=True)
    n = 0
    for name in locked:
        stem = os.path.splitext(name)[0] + ".txt"
        sp = os.path.join(src, stem)
        if os.path.exists(sp):
            try:
                shutil.copy2(sp, os.path.join(dst, stem))
                n += 1
            except Exception:
                pass
    # vis 预览图也一起搬,否则标注页看不到那张图的预览
    vs, vd = os.path.join(backup_out, "vis"), os.path.join(out_dir, "vis")
    if os.path.isdir(vs):
        os.makedirs(vd, exist_ok=True)
        for name in locked:
            stem = os.path.splitext(name)[0]
            for ext in (".jpg", ".png", ".jpeg"):
                sp = os.path.join(vs, stem + ext)
                if os.path.exists(sp):
                    try:
                        shutil.copy2(sp, os.path.join(vd, stem + ext))
                    except Exception:
                        pass
                    break
    return n
