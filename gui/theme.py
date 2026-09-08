# -*- coding: utf-8 -*-
"""深色主题。颜色集中在这里,改配色只动这一个文件。

关于 QSS 的两个坑(踩过):
- Qt 的 rgba() 里 alpha 是 0~255 整数或百分比,写 0.12 会被截成 0 = 完全透明。
- 纯 CSS 的"用 border 拼三角形/对勾"在 Qt 里不成立(subcontrol 有自己的尺寸提示),
  所以对勾和下拉箭头都用 Pillow 画成 PNG 再 url() 引用。
"""
import os
import re

C = {
    "bg":        "#1E1F22",   # 窗口底
    "bg_side":   "#191A1C",   # 侧边栏(比底更深,拉开层次)
    "card":      "#2A2C30",   # 卡片/输入框
    "card_hi":   "#32353A",   # 悬停
    "border":    "#3A3D42",
    "text":      "#E8E8EA",
    "text_dim":  "#9A9CA1",   # 次要说明文字
    "text_faint": "#6E7075",  # 占位符
    "accent":    "#4A9EFF",   # 强调蓝
    "accent_hi": "#63AEFF",
    "accent_lo": "#2B5F9E",
    "ok":        "#3FB950",
    "warn":      "#D29922",
    "err":       "#F85149",
}

# 等宽字体:日志窗用。列几个常见的,取系统里有的第一个。
MONO = '"JetBrains Mono","Noto Sans Mono","DejaVu Sans Mono","Consolas",monospace'
# UI 字体:优先中文字体,避免中文回退成方框
UI_FONT = '"Microsoft YaHei UI","Noto Sans CJK SC","Source Han Sans SC","WenQuanYi Zen Hei","Segoe UI","Ubuntu",sans-serif'


def apply_palette(app):
    """用 QPalette 设窗口底色 + 各种系统色。
    比在 QSS 里写 QWidget{background} 安全:不会把卡片里的容器一起刷黑,
    也能让 QFileDialog / QMessageBox 这些系统对话框跟着变深色。"""
    from PySide6.QtGui import QPalette, QColor
    from PySide6.QtCore import Qt
    p = QPalette()
    win, base, text = QColor(C["bg"]), QColor("#16171A"), QColor(C["text"])
    p.setColor(QPalette.Window, win)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, base)
    p.setColor(QPalette.AlternateBase, QColor(C["card"]))
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, QColor(C["card_hi"]))
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.ToolTipBase, QColor(C["card"]))
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Highlight, QColor(C["accent"]))
    p.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    p.setColor(QPalette.Link, QColor(C["accent"]))
    p.setColor(QPalette.PlaceholderText, QColor(C["text_faint"]))
    for g in (QPalette.Disabled,):
        p.setColor(g, QPalette.Text, QColor(C["text_faint"]))
        p.setColor(g, QPalette.ButtonText, QColor(C["text_faint"]))
        p.setColor(g, QPalette.WindowText, QColor(C["text_faint"]))
    app.setPalette(p)


def _asset_dir():
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_assets")
    os.makedirs(d, exist_ok=True)
    return d


def _qss_url(path):
    """QSS 的 url() 只认正斜杠。"""
    return path.replace("\\", "/")


def make_assets():
    """用 Pillow 生成 QSS 需要的小图:对勾、下拉箭头。
    Qt 的 url() 不支持 data: URI,只能给真实文件路径;
    而 border 拼三角形/对勾在 Qt 里画不出来,所以这里生成 PNG。
    返回 {名字: 路径};Pillow 不可用时返回 {}(界面退回原生画法,不影响功能)。"""
    # Debian 安装版位于只读 /opt。构建包时这些资源已经生成，启动时直接
    # 复用，不能再尝试覆盖它们。
    if os.environ.get("BEST_YOLO_READONLY_INSTALL", "").strip() in (
            "1", "true", "yes"):
        d = _asset_dir()
        ready = {name: _qss_url(os.path.join(d, name + ".png"))
                 for name in ("check", "arrow", "up", "down")}
        if all(os.path.isfile(path) for path in ready.values()):
            return ready
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return {}
    d = _asset_dir()
    out = {}
    S = 4        # 超采样,边缘不锯齿

    def _save(name, size, draw_fn):
        p = os.path.join(d, name)
        im = Image.new("RGBA", (size * S, size * S), (0, 0, 0, 0))
        draw_fn(ImageDraw.Draw(im), size * S)
        im.resize((size, size), Image.LANCZOS).save(p)
        out[name.split(".")[0]] = _qss_url(p)

    def check(dr, n):
        u = n / 16.0
        dr.line([(3.2 * u, 8.6 * u), (6.6 * u, 12 * u), (12.8 * u, 4.6 * u)],
                fill=(255, 255, 255, 255), width=max(1, int(2.1 * u)), joint="curve")

    def arrow(dr, n):
        u = n / 16.0
        dr.polygon([(2.6 * u, 6 * u), (13.4 * u, 6 * u), (8 * u, 11.4 * u)],
                   fill=(154, 156, 161, 255))

    # 数字框的加减箭头。画在 16x16 画布上再让 Qt 缩到 9px,
    # 三角形要画得饱满一些,缩小后才看得清。
    def up(dr, n):
        u = n / 16.0
        dr.polygon([(3.5 * u, 10.5 * u), (12.5 * u, 10.5 * u), (8 * u, 5 * u)],
                   fill=(210, 212, 216, 255))

    def down(dr, n):
        u = n / 16.0
        dr.polygon([(3.5 * u, 5.5 * u), (12.5 * u, 5.5 * u), (8 * u, 11 * u)],
                   fill=(210, 212, 216, 255))

    try:
        _save("check.png", 16, check)
        _save("arrow.png", 16, arrow)
        _save("up.png", 16, up)
        _save("down.png", 16, down)
    except Exception:
        return {}
    return out


def scale_qss(qss, k):
    """把样式表里的 px 尺寸按 k 倍放大,用于窗口变大时同步放大字号和间距。

    为什么用正则整体缩放,而不是把每处都写成变量:样式表里有 80 多处 px,
    逐个参数化既啰嗦又容易漏。这里统一处理,并且保留两个例外:
      - 1px 一律不动:边框和分隔线放大后会变成粗黑框,很丑
      - border-radius 只放大到 1.5 倍:圆角跟着放大会变成"胶囊"
    """
    if abs(k - 1.0) < 0.01:
        return qss

    def bump(v, kk):
        if v <= 1:
            return f"{v}px"            # 边框保持 1px,放大会变成粗黑框
        return f"{max(2, round(v * kk))}px"

    out = []
    in_comment = False
    for line in qss.splitlines():
        # 注释里的 px 不能改。注释里常写"padding: 7px 9px"这类说明文字,
        # 改了不影响样式,但会让注释和实际值不一致,排查问题时更误导人。
        stripped = line.strip()
        was_in = in_comment
        if "/*" in line and "*/" not in line:
            in_comment = True
        elif "*/" in line:
            in_comment = False
        if was_in or stripped.startswith("/*"):
            out.append(line)
            continue
        kk = min(k, 1.5) if "border-radius" in line else k
        out.append(re.sub(r"(\d+)px",
                          lambda m: bump(int(m.group(1)), kk), line))
    return "\n".join(out)


def stylesheet(scale=1.0):
    a = make_assets()
    # 图生成失败就不写这两条规则,Qt 会退回原生画法(有对勾/箭头,只是样式不统一)
    # 对勾图也要给列表项的勾选框用上,否则勾上了看不出来
    check_rule = (f"QCheckBox::indicator:checked, "
                  f"QListWidget::indicator:checked "
                  f"{{ image: url({a['check']}); }}"
                  if "check" in a else "")
    arrow_rule = (f"QComboBox::down-arrow {{ image: url({a['arrow']}); "
                  f"width: 10px; height: 10px; margin-right: 8px; }}"
                  if "arrow" in a else "")
    spin_rules = ""
    if "up" in a and "down" in a:
        spin_rules = (
            f"QSpinBox::up-arrow, QDoubleSpinBox::up-arrow "
            f"{{ image: url({a['up']}); width: 9px; height: 9px; }}\n"
            f"QSpinBox::down-arrow, QDoubleSpinBox::down-arrow "
            f"{{ image: url({a['down']}); width: 9px; height: 9px; }}")
    _qss = f"""
/* QWidget 会匹配所有子类。这里不设 background —— 让普通容器保持透明,
   露出父级颜色(卡片里的行才不会被刷成窗口底色)。
   窗口底色改由 QPalette 设置(见 app.py 的 apply_palette),
   那是唯一不会波及子控件的做法。 */
QWidget {{
    color: {C['text']};
    font-family: {UI_FONT};
    font-size: 13px;
}}

/* ---------- 侧边栏 ---------- */
#Sidebar {{
    background: {C['bg_side']};
    border-right: 1px solid {C['border']};
}}
#Brand {{
    color: {C['text']};
    font-size: 15px;
    font-weight: 600;
    padding: 0;
    background: transparent;
}}
#UpdateCheckBtn, #UpdateAvailableBtn {{
    border-radius: 4px;
    padding: 3px 6px;
    font-size: 10px;
    font-weight: 600;
    min-width: 50px;
}}
#UpdateCheckBtn {{
    color: {C['accent_hi']};
    background: rgba(74,158,255,22);
    border: 1px solid {C['accent_lo']};
}}
#UpdateCheckBtn:hover {{
    color: #FFFFFF;
    background: {C['accent_lo']};
    border-color: {C['accent']};
}}
#UpdateAvailableBtn {{
    color: #FFFFFF;
    background: {C['err']};
    border: 1px solid {C['err']};
}}
#UpdateAvailableBtn:hover {{ background: #FF675F; border-color: #FF675F; }}
#UpdateAvailableBtn:pressed {{ background: #C9352E; border-color: #C9352E; }}
#BrandSub {{
    color: {C['text_faint']};
    font-size: 11px;
    padding: 0 18px 14px 18px;
    background: transparent;
}}
#NavBtn {{
    background: transparent;
    border: none;
    border-left: 3px solid transparent;
    color: {C['text_dim']};
    text-align: left;
    padding: 11px 18px;
    font-size: 13px;
}}
#NavBtn:hover {{
    background: {C['card']};
    color: {C['text']};
}}
#NavBtn:checked {{
    background: {C['card']};
    border-left: 3px solid {C['accent']};
    color: {C['text']};
    font-weight: 600;
}}

/* ---------- 卡片 ---------- */
#Card {{
    background: {C['card']};
    border: 1px solid {C['border']};
    border-radius: 8px;
}}
#CardTitle {{
    font-size: 13px;
    font-weight: 600;
    color: {C['text']};
    background: transparent;
}}
#Hint {{
    color: {C['text_dim']};
    font-size: 11px;
    background: transparent;
}}
#PageTitle {{
    font-size: 19px;
    font-weight: 600;
    background: transparent;
}}
#PageSub {{
    color: {C['text_dim']};
    font-size: 12px;
    background: transparent;
}}
#UpdateDialogTitle {{
    color: {C['text']};
    font-size: 20px;
    font-weight: 600;
    background: transparent;
}}
#UpdateDialogVersion {{
    color: {C['text_dim']};
    font-size: 12px;
    background: transparent;
}}
#UpdateNotes {{
    background: {C['bg']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 10px;
}}

/* ---------- 输入控件 ---------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox,
QKeySequenceEdit {{
    background: {C['bg']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 7px 9px;
    color: {C['text']};
    selection-background-color: {C['accent_lo']};
    /* 高度下限:窗口太矮时 Qt 会把控件压扁,压到比文字还矮就只能看见
       文字中间一条,看起来像一排虚线。给个下限,宁可挤别处也不能压这里。 */
    min-height: 17px;
}}
/* 给加减按钮留出右边距,数字不会被按钮压住 */
QSpinBox, QDoubleSpinBox {{ padding-right: 24px; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QKeySequenceEdit:focus {{
    border: 1px solid {C['accent']};
}}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled,
QDoubleSpinBox:disabled, QKeySequenceEdit:disabled {{
    color: {C['text_faint']};
    background: {C['card']};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
{arrow_rule}
QComboBox QAbstractItemView {{
    background: {C['card']};
    border: 1px solid {C['border']};
    selection-background-color: {C['accent_lo']};
    outline: none;
    padding: 4px;
}}
/* 数字框的加减按钮:必须保留且看得见。
   滚轮已被禁用(防误触),如果再把按钮藏了,就只剩键盘输入一条路了。 */
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background: {C['card_hi']};
    border: none;
    border-left: 1px solid {C['border']};
    width: 20px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border; subcontrol-position: top right;
    border-top-right-radius: 5px;
    border-bottom: 1px solid {C['border']};
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right;
    border-bottom-right-radius: 5px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: #4A4E55;
}}
{spin_rules}

/* ---------- 按钮 ---------- */
QPushButton {{
    background: {C['card_hi']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 8px 16px;
    color: {C['text']};
}}
QPushButton:hover {{ background: #3C4046; border-color: #4A4E55; }}
QPushButton:pressed {{ background: #2E3136; }}
QPushButton:disabled {{ background: {C['card']}; color: {C['text_faint']}; }}

#Primary {{
    background: {C['accent']};
    border: none;
    color: #FFFFFF;
    font-weight: 600;
    padding: 10px 22px;
}}
#Primary:hover {{ background: {C['accent_hi']}; }}
#Primary:pressed {{ background: {C['accent_lo']}; }}
#Primary:disabled {{ background: #2F3237; color: {C['text_faint']}; }}

#Danger {{ background: transparent; border: 1px solid {C['err']}; color: {C['err']}; }}
/* Qt 的 rgba alpha 是 0~255 整数,不能写 0.12(会被截成 0=全透明,等于没有悬停反馈) */
#Danger:hover {{ background: rgba(248,81,73,32); }}
#Danger:pressed {{ background: rgba(248,81,73,56); }}
#Danger:disabled {{ border-color: {C['border']}; color: {C['text_faint']}; }}

/* 类别表每行右边的「✕ 删除」:平时是暗红的,悬停才变亮红填充,
   免得 16 行一起亮着抢注意力 */
#RowDel {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 0 6px;
    color: #A85450;
    font-size: 12px;
}}
#RowDel:hover {{
    background: {C['err']}; color: #FFFFFF; border-color: {C['err']};
}}
#RowDel:pressed {{ background: #C9352E; color: #FFFFFF; }}
#RowDel:disabled {{ color: {C['border']}; background: transparent; }}

/* 右上角的界面缩放 - / + */
#ZoomBtn {{
    background: {C['card']}; border: 1px solid {C['border']};
    border-radius: 5px; color: {C['text']};
    min-width: 26px; max-width: 26px; padding: 2px 0;
    font-size: 15px;
}}
#ZoomBtn:hover {{ background: {C['card_hi']}; border-color: {C['accent']}; }}
#ZoomBtn:pressed {{ background: {C['accent_lo']}; }}
#ZoomLabel {{
    color: {C['text_dim']}; background: transparent;
    min-width: 42px; font-size: 12px;
}}

#ShortcutSettingsBtn {{
    background: {C['card']}; border: 1px solid {C['border']};
    border-radius: 5px; color: {C['text_dim']};
    padding: 4px 10px; font-size: 12px;
}}
#ShortcutSettingsBtn:hover {{
    background: {C['card_hi']}; color: {C['text']}; border-color: {C['accent']};
}}
#ShortcutSettingsBtn:pressed {{ background: {C['accent_lo']}; }}

#LinkBtn {{
    background: transparent; border: none;
    color: {C['accent']}; padding: 4px 6px; text-align: left;
}}
#LinkBtn:hover {{ color: {C['accent_hi']}; text-decoration: underline; }}

/* ---------- 表格 ---------- */
QTableWidget, QTableView, QTreeWidget {{
    background: {C['bg']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    gridline-color: {C['border']};
    selection-background-color: {C['accent_lo']};
}}
QTableWidget::item {{ padding: 5px 6px; border: none; }}
QTableWidget::item:selected {{ color: {C['text']}; }}
QTreeWidget::item {{ padding: 5px 7px; }}
QTreeWidget::item:selected {{ color: {C['text']}; }}

#ShortcutEditor {{
    background: {C['card']}; border: 1px solid {C['border']}; border-radius: 7px;
}}
#ShortcutScope {{ color: {C['accent']}; background: transparent; font-size: 11px; }}

/* 单元格里弹出的编辑框。
   它是个 QLineEdit,会继承上面输入控件的 padding: 7px 9px —— 在只有
   30 来 px 高的单元格里,上下各吃掉 7px 后留给文字的高度不够一个汉字,
   字形被裁掉上下两截,看起来就"又小又像乱码"。这里单独压扁内边距,
   并显式给足字号和行高。 */
QTableWidget QLineEdit, QTableView QLineEdit {{
    padding: 0px 5px;
    margin: 0px;
    border: 1px solid {C['accent']};
    border-radius: 3px;
    background: {C['bg']};
    color: {C['text']};
    font-family: {UI_FONT};
    font-size: 13px;
    min-height: 22px;
}}
QHeaderView::section {{
    background: {C['card']};
    color: {C['text_dim']};
    border: none;
    border-bottom: 1px solid {C['border']};
    border-right: 1px solid {C['border']};
    padding: 7px 6px;
    font-weight: 600;
    font-size: 12px;
}}
QTableCornerButton::section {{ background: {C['card']}; border: none; }}

/* ---------- 复选框 ---------- */
QCheckBox {{ spacing: 7px; background: transparent; }}
/* 列表项自带的勾选框也要一起管:只写 QCheckBox 的话,
   QListWidget 里的勾选框会退回 Qt 默认画法 —— 在深色底上几乎看不见 */
QCheckBox::indicator, QListWidget::indicator, QTreeWidget::indicator {{
    width: 15px; height: 15px;
    border: 1px solid #6B7280;
    border-radius: 4px;
    background: {C['bg']};
}}
QCheckBox::indicator:hover, QListWidget::indicator:hover {{
    border-color: {C['accent']};
}}
QCheckBox::indicator:checked, QListWidget::indicator:checked,
QTreeWidget::indicator:checked {{
    background: {C['accent']};
    border-color: {C['accent']};
}}
/* 对勾图standard由 make_assets() 用 Pillow 生成(Qt 画不出 CSS 那种 border 对勾) */
{check_rule}

/* ---------- 日志 ---------- */
#Log {{
    background: #16171A;
    border: 1px solid {C['border']};
    border-radius: 6px;
    font-family: {MONO};
    font-size: 12px;
    color: #C8CACE;
    padding: 8px;
}}

/* ---------- 进度条 ---------- */
/* height 在 QSS 里只对 subcontrol 生效,widget 上必须用 min/max-height */
QProgressBar {{
    background: {C['bg']};
    border: 1px solid {C['border']};
    border-radius: 4px;
    min-height: 8px;
    max-height: 8px;
}}
QProgressBar::chunk {{ background: {C['accent']}; border-radius: 3px; }}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: #45484E; border-radius: 5px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: #55585F; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background: #45484E; border-radius: 5px; min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{ background: #55585F; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- 其它 ---------- */
QSplitter::handle {{ background: {C['border']}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QToolTip {{
    background: {C['card']}; color: {C['text']};
    border: 1px solid {C['border']}; padding: 5px 7px; border-radius: 4px;
}}
/* 打码后的 API Key:等宽字体,一眼看出是凭据 */
#KeyMask {{
    background: transparent;
    font-family: {MONO};
    font-size: 12px;
}}
#StatusBar {{ background: {C['bg_side']}; color: {C['text_dim']}; }}
#Chip {{
    background: {C['bg']}; border: 1px solid {C['border']};
    border-radius: 10px; padding: 2px 9px; color: {C['text_dim']}; font-size: 11px;
}}
"""
    return scale_qss(_qss, scale)
