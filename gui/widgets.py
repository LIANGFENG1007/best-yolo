# -*- coding: utf-8 -*-
"""可复用的小控件。"""
import os
from PySide6.QtCore import (Qt, Signal, QSize, QObject, QEvent,
                            QStringListModel, QRect, QPoint)
from PySide6.QtGui import QPixmap, QPainter, QColor, QIcon, QPen
from PySide6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout,
                               QPushButton, QLineEdit, QFileDialog, QFrame,
                               QSizePolicy, QScrollArea, QDialog, QCheckBox,
                               QComboBox, QCompleter, QLayout,
                               QListWidget, QListWidgetItem, QAbstractItemView)

from theme import C


class NoWheelFilter(QObject):
    """吃掉下拉框/数字框上的滚轮事件。

    为什么需要:这些控件默认会响应滚轮改值。页面本身要滚动,鼠标滑过它们时
    很容易把「模型」「并发数」「预览张数」悄悄改掉,而且没有任何提示 ——
    上次就是这么把「坐标口径」误设成强制 0~1,导致一整批标签全废。

    只在控件没有键盘焦点时拦截:用户主动点进去后仍然可以用滚轮微调。
    """

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Wheel and not obj.hasFocus():
            # 输入框没有焦点时不应改值，但如果它位于页面滚动区内，
            # 滚轮仍应继续滚动页面。直接转动最近的 QScrollArea，避免
            # 把事件交回输入控件后又触发数字/下拉选项变化。
            parent = obj.parentWidget()
            seen = set()
            for _level in range(64):
                if parent is None or id(parent) in seen:
                    break
                seen.add(id(parent))
                if isinstance(parent, QScrollArea):
                    delta = 0
                    try:
                        delta = ev.pixelDelta().y() or ev.angleDelta().y()
                    except (AttributeError, TypeError):
                        pass
                    if delta:
                        bar = parent.verticalScrollBar()
                        bar.setValue(bar.value() - delta)
                    ev.accept()
                    return True
                parent = parent.parentWidget()
            ev.ignore()
            return True          # 没有页面滚动区时只拦下控件滚轮
        return False


_no_wheel = NoWheelFilter()      # 单例:所有控件共用一个过滤器


def no_wheel(w):
    """给控件装上"忽略滚轮"。返回控件本身,方便链式写法。"""
    # 没有焦点时不接收滚轮(双保险:焦点策略 + 事件过滤)
    w.setFocusPolicy(Qt.StrongFocus)
    w.installEventFilter(_no_wheel)
    return w


class FlowLayout(QLayout):
    """会自动换行的横向布局。

    工具条按钮多了以后,固定一行会把面板的最小宽度顶得很大,窗口一缩就
    和左右两栏挤在一起(重合)。让它在放不下时换行,面板就能真正变窄。
    """

    def __init__(self, parent=None, spacing=7):
        super().__init__(parent)
        self._items = []
        self._space = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, it):
        self._items.append(it)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), test_only=True)

    def setGeometry(self, r):
        super().setGeometry(r)
        self._do(r, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        # 最小宽 = 最宽的那个控件,而不是所有控件之和 —— 这才是能换行的关键
        w = h = 0
        for it in self._items:
            s = it.minimumSize()
            w = max(w, s.width())
            h = max(h, s.height())
        m = self.contentsMargins()
        return QSize(w + m.left() + m.right(), h + m.top() + m.bottom())

    def _do(self, rect, test_only):
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        right = rect.right() - m.right()
        line_h = 0
        for it in self._items:
            s = it.sizeHint()
            if x > rect.x() + m.left() and x + s.width() > right:
                x = rect.x() + m.left()       # 换行
                y += line_h + self._space
                line_h = 0
            if not test_only:
                it.setGeometry(QRect(QPoint(x, y), s))
            x += s.width() + self._space
            line_h = max(line_h, s.height())
        return y + line_h - rect.y() + m.bottom()


class KeyField(QWidget):
    """API Key 输入:平时只显示一颗按钮 + 打码后的 key,不占一长条。

    点「设置」弹小窗输入 -> 确定后收起,只显示 sk-0f3a****4a08。
    这样界面清爽,也不会把 key 明晃晃摊在屏幕上。
    """
    changed = Signal(str)          # 参数是新的完整 key

    def __init__(self, parent=None):
        super().__init__(parent)
        self._key = ""
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.lb = QLabel("")
        self.lb.setObjectName("KeyMask")
        self.btn = QPushButton("设置 API Key")
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.clicked.connect(self._edit)
        self.btn_clear = QPushButton("清除")
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.clicked.connect(self._clear)
        lay.addWidget(self.btn)
        lay.addWidget(self.lb, 1)
        lay.addWidget(self.btn_clear)
        self._sync()

    def set_key(self, k):
        self._key = (k or "").strip()
        self._sync()

    def key(self):
        return self._key

    def _sync(self):
        import core
        if self._key:
            self.lb.setText(core.mask_key(self._key))
            self.lb.setStyleSheet(f"color:{C['ok']}; background:transparent;")
            self.btn.setText("更换")
            self.btn_clear.setVisible(True)
        else:
            self.lb.setText("未设置 —— 点右边「设置」填入你的 API Key")
            self.lb.setStyleSheet(f"color:{C['text_faint']}; background:transparent;")
            self.btn.setText("设置 API Key")
            self.btn_clear.setVisible(False)

    def _edit(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("设置 API Key")
        dlg.setMinimumWidth(460)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(10)
        tip = QLabel("粘贴你的 API Key。保存后界面上只会显示打码后的样子,\n"
                     "下次打开软件不用再输入。")
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        v.addWidget(tip)
        ed = QLineEdit(self._key)
        ed.setEchoMode(QLineEdit.Password)     # 输入时就不显示明文
        ed.setPlaceholderText("sk-...")
        ed.setClearButtonEnabled(True)
        v.addWidget(ed)
        # 让用户能自己确认粘对了没有
        cb = QCheckBox("显示明文")
        cb.toggled.connect(
            lambda on: ed.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        v.addWidget(cb)
        warn = QLabel("")
        warn.setObjectName("Hint")
        warn.setWordWrap(True)
        v.addWidget(warn)
        row = QHBoxLayout()
        ok = QPushButton("确定")
        ok.setObjectName("Primary")
        cancel = QPushButton("取消")
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        v.addLayout(row)
        cancel.clicked.connect(dlg.reject)

        def _accept():
            import core
            k = ed.text().strip()
            if k and not core.looks_like_key(k):
                warn.setText("⚠ 这看起来不像一个 Key(太短或含空格)。确认无误可再点一次确定。")
                warn.setStyleSheet(f"color:{C['warn']}; background:transparent;")
                # 记一个标记:再点一次就放行,不硬拦
                if getattr(dlg, "_warned", False):
                    dlg.accept()
                dlg._warned = True
                return
            dlg.accept()
        ok.clicked.connect(_accept)
        ed.returnPressed.connect(_accept)
        ed.setFocus()
        if dlg.exec() == QDialog.Accepted:
            self.set_key(ed.text().strip())
            self.changed.emit(self._key)

    def _clear(self):
        self.set_key("")
        self.changed.emit("")


class SearchableCombo(QComboBox):
    """带搜索的下拉框:点开后可以直接打字过滤。

    模型多起来(接入点常有几十个)时,纯下拉根本找不着,所以套一个
    QCompleter 做包含式匹配。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)   # 打字不会往列表里塞新项
        self.setMaxVisibleItems(18)
        self._comp = QCompleter(self)
        self._comp.setCaseSensitivity(Qt.CaseInsensitive)
        self._comp.setFilterMode(Qt.MatchContains)  # 输入片段即可匹配,不必从头
        self._comp.setCompletionMode(QCompleter.PopupCompletion)
        self.setCompleter(self._comp)
        self.lineEdit().setPlaceholderText("点这里可直接打字搜索模型")

    def load(self, items, current=None, colors=None):
        """items: [(值, 显示名, 是否常用)]
        colors: 可选,[(r,g,b)] 逐项上色(类别下拉用它对应框的颜色)"""
        self.blockSignals(True)
        self.clear()
        for idx, (v, text, common) in enumerate(items):
            self.addItem(text, v)
            i = self.count() - 1
            if common:
                f = self.font()
                f.setBold(True)
                self.setItemData(i, f, Qt.FontRole)     # 常用模型加粗
                self.setItemData(i, "常用模型", Qt.ToolTipRole)
            if colors and idx < len(colors):
                self.setItemData(i, QColor(*colors[idx]), Qt.ForegroundRole)
        # 搜索用的候选表要跟着更新
        model = QStringListModel([t for _, t, _ in items], self)
        self._comp.setModel(model)
        i = self.findData(current) if current else -1
        self.setCurrentIndex(i if i >= 0 else 0)
        self.blockSignals(False)

    def selected(self):
        """返回当前选中的模型值(真正的模型 id,不是显示名)。

        可编辑下拉框有三种情况都要处理:
          1) 正常从列表里选 -> currentData() 就是模型 id
          2) 手打了列表里的显示名 -> 反查 id(显示名现在就是 id,
             但自定义模型或将来加后缀时这条仍然必要)
          3) 手打了模型 id 本身 -> 直接就是它
        """
        typed = self.currentText().strip()
        if not typed:
            return self.currentData() or ""
        for i in range(self.count()):
            if self.itemText(i) == typed:      # 情况1&2:从列表选的,或打了显示名
                return self.itemData(i)
        # 情况3:打的是模型 id(在列表里或自定义的),原样返回
        return typed


class Card(QFrame):
    """带标题的卡片容器。body 用 addWidget/addLayout 往里塞。"""

    def __init__(self, title=None, hint=None, parent=None, grow=False):
        """grow=True 用于"里面装大块内容、需要占满剩余空间"的卡片
        (预览、缩略图、日志、图片列表)。默认 False = 按内容占高度且不被压缩。
        """
        super().__init__(parent)
        self.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(10)
        # 装表单的卡片竖向不许被压缩。QFrame 默认是 Preferred,意思是
        # "可以被压小",竖向空间不够时 Qt 就把卡片压到最小,里面的输入框
        # 跟着被裁掉一截(只看得见文字中间一条,像一排虚线)。
        # 光给 QLineEdit 写 QSS 的 min-height 不管用 —— QSS 不参与布局协商,
        # 必须在这一层就拒绝压缩。
        if not grow:
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
            outer.setSizeConstraint(QVBoxLayout.SetMinimumSize)
        if title:
            t = QLabel(title)
            t.setObjectName("CardTitle")
            outer.addWidget(t)
        if hint:
            h = QLabel(hint)
            h.setObjectName("Hint")
            h.setWordWrap(True)
            outer.addWidget(h)
        self.body = QVBoxLayout()
        self.body.setSpacing(9)
        self.body.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(self.body)


class PathPicker(QWidget):
    """路径输入 + 浏览按钮 + 右侧状态文字(如"109 张图")。"""
    changed = Signal(str)

    def __init__(self, placeholder="", pick_dir=True, status=True,
                 file_filter="", parent=None):
        super().__init__(parent)
        self._pick_dir = pick_dir
        self._filter = file_filter      # 选文件时的格式过滤
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.textChanged.connect(self._on_text)
        btn = QPushButton("浏览…")
        self._btn = btn
        self._btn_w = 76
        btn.setFixedWidth(76)
        btn.clicked.connect(self._browse)
        lay.addWidget(self.edit, 1)
        lay.addWidget(btn)
        self.status = None
        if status:
            self.status = QLabel("")
            self.status.setObjectName("Chip")
            self._status_w = 74
            self.status.setMinimumWidth(74)
            self.status.setAlignment(Qt.AlignCenter)
            lay.addWidget(self.status)

    def set_scale(self, k):
        """窗口放大时按同比例放大按钮宽度,免得字变大后被挤成两行。"""
        self._btn.setFixedWidth(int(round(self._btn_w * k)))
        if self.status is not None:
            self.status.setMinimumWidth(int(round(self._status_w * k)))

    def _on_text(self, t):
        self.changed.emit(t)

    def _browse(self):
        cur = self.edit.text().strip() or os.path.expanduser("~")
        start = cur if os.path.isdir(cur) else os.path.dirname(cur) or os.path.expanduser("~")
        if self._pick_dir:
            p = QFileDialog.getExistingDirectory(self, "选择文件夹", start)
        else:
            p, _ = QFileDialog.getOpenFileName(
                self, "选择文件", start, self._filter or "")
        if p:
            self.edit.setText(p)

    def text(self):
        return self.edit.text().strip()

    def setText(self, t):
        self.edit.setText(t or "")

    def set_status(self, txt, kind="dim"):
        if self.status is None:
            return
        color = {"ok": C["ok"], "err": C["err"], "dim": C["text_dim"]}.get(kind, C["text_dim"])
        self.status.setText(txt)
        self.status.setStyleSheet(f"#Chip {{ color: {color}; }}")


class FieldRow(QWidget):
    """左标签 + 右控件 的一行。标签宽度统一,视觉对齐。"""

    def __init__(self, label, widget, hint=None, label_w=96, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        lb = QLabel(label)
        self._lb = lb
        self._lb_w = label_w
        lb.setFixedWidth(label_w)
        lb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lb.setStyleSheet(f"color:{C['text_dim']}; background:transparent;")
        row.addWidget(lb)
        row.addWidget(widget, 1)
        lay.addLayout(row)
        self._hint = None
        if hint:
            h = QLabel(hint)
            h.setObjectName("Hint")
            h.setWordWrap(True)
            h.setContentsMargins(label_w + 10, 0, 0, 0)
            lay.addWidget(h)
            self._hint = h

    def set_scale(self, k):
        """标签列跟着放大,不然字变大后"待标注图片文件夹"这种会被截断。"""
        w = int(round(self._lb_w * k))
        self._lb.setFixedWidth(w)
        if self._hint is not None:
            self._hint.setContentsMargins(w + int(round(10 * k)), 0, 0, 0)


class ImageView(QLabel):
    """自适应缩放显示图片,保持比例、居中,不放大超过原图。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pm = None
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(240, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet(
            f"background:#141518; border:1px solid {C['border']}; border-radius:6px;"
            f"color:{C['text_faint']};")
        self.setText("选一张图预览")

    def load(self, path):
        pm = QPixmap(path)
        if pm.isNull():
            self._pm = None
            self.setText("图片打不开")
            return False
        self._pm = pm
        self._render()
        return True

    def clear_image(self, msg="选一张图预览"):
        self._pm = None
        super().clear()
        self.setText(msg)

    def _render(self):
        if self._pm is None:
            return
        avail = self.size()
        w = max(1, avail.width() - 8)
        h = max(1, avail.height() - 8)
        # 不放大:图比框小就原样显示
        if self._pm.width() <= w and self._pm.height() <= h:
            self.setPixmap(self._pm)
        else:
            self.setPixmap(self._pm.scaled(w, h, Qt.KeepAspectRatio,
                                           Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._render()


def color_dot(rgb, size=11):
    """生成一个圆形色块图标,用在类别表里标注该类的框颜色。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(*rgb))
    p.setPen(QPen(QColor(0, 0, 0, 90), 1))
    p.drawEllipse(0, 0, size - 1, size - 1)
    p.end()
    return QIcon(pm)


def app_icon():
    """内置画一个应用图标:深色圆角底 + 蓝色检测框 + 十字准星。
    这样不依赖任何图片文件,打包/复制都不会丢图标。"""
    size = 256
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    # 底
    p.setBrush(QColor("#22252A"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(8, 8, size - 16, size - 16, 52, 52)
    # 检测框
    pen = QPen(QColor(C["accent"]), 13)
    pen.setJoinStyle(Qt.MiterJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRect(66, 66, 124, 124)
    # 四角加重(像目标框的角标)
    pen2 = QPen(QColor("#8FC4FF"), 13)
    pen2.setCapStyle(Qt.FlatCap)
    p.setPen(pen2)
    for (x, y, dx, dy) in ((66, 66, 1, 1), (190, 66, -1, 1),
                           (66, 190, 1, -1), (190, 190, -1, -1)):
        p.drawLine(x, y, x + 34 * dx, y)
        p.drawLine(x, y, x, y + 34 * dy)
    # 中心准星
    p.setPen(QPen(QColor("#FFFFFF"), 9))
    p.drawLine(128, 108, 128, 148)
    p.drawLine(108, 128, 148, 128)
    p.end()
    return QIcon(pm)


def scroll_area(inner, min_w=430):
    """把一个 widget 包进无边框滚动区(窗口小的时候内容不会被挤没,而是可以滚)。"""
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    sa.setWidget(inner)
    sa.setMinimumWidth(min_w)          # 再窄就横向滚动,不要把控件压变形
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    sa.setStyleSheet("QScrollArea{background:transparent;} "
                     "QScrollArea>QWidget>QWidget{background:transparent;}")
    return sa


class ThumbStrip(QListWidget):
    """缩略图网格:显示切出来的图,点一下放大看。

    用 QListWidget 的 IconMode 而不是自己排版:它自带换行、滚动、选中和
    键盘导航,窗口变化时也会自动重排,省很多事。
    """
    opened = Signal(str)          # 要求放大看某张图

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListWidget.IconMode)
        self.setResizeMode(QListWidget.Adjust)      # 窗口变化时重排
        self.setMovement(QListWidget.Static)
        self.setSpacing(6)
        self.setUniformItemSizes(True)
        self.setWordWrap(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        # 不要滚动条:要求是"一下全都显示出来",所以改成自动缩小格子来塞满
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._thumb = 128
        self._auto_fit = True        # 按可用面积自动决定缩略图大小
        self._pms = []               # 原图 pixmap,重排时按新尺寸重新缩
        self._apply_sizes()
        # 单击就放大 —— 需求是"点击可以放大查看"
        self.itemClicked.connect(self._emit_open)
        self.itemActivated.connect(self._emit_open)

    def _emit_open(self, it):
        if it is not None:
            self.opened.emit(it.data(Qt.UserRole) or "")

    def _apply_sizes(self):
        self.setIconSize(QSize(self._thumb, self._thumb))
        # 格子比图标大一圈,留出文件名那行
        self.setGridSize(QSize(self._thumb + 16, self._thumb + 30))

    def set_thumb_size(self, px):
        self._thumb = max(64, int(px))
        self._apply_sizes()

    def load_dir(self, folder, exts=(".jpg", ".jpeg", ".png", ".bmp", ".webp"),
                 limit=400):
        """把文件夹里的图铺上去,返回 (显示张数, 总张数)。

        limit:上千张时全部读进来会明显卡顿,只铺前面一批,
        剩下的让用户点「打开切分文件夹」去看。
        """
        self.clear()
        self._pms = []
        if not folder or not os.path.isdir(folder):
            return (0, 0)
        try:
            files = sorted(f for f in os.listdir(folder)
                           if os.path.splitext(f)[1].lower() in exts)
        except OSError:
            return (0, 0)
        for name in files[:limit]:
            p = os.path.join(folder, name)
            it = QListWidgetItem(name)
            it.setData(Qt.UserRole, p)
            it.setToolTip(f"{name}\n点一下放大查看")
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignBottom)
            pm = QPixmap(p)
            self._pms.append(None if pm.isNull() else pm)
            self.addItem(it)
        self.relayout()
        return (min(len(files), limit), len(files))

    def relayout(self):
        """按当前可用面积算出格子大小,让所有图刚好铺满、不用滚动。

        思路:格子越小,一行能放的越多、需要的行数越少。从大到小试,
        找到第一个"总行数装得下"的尺寸。没有滚动条,所以宁可格子小一点,
        也不能让后面的图跑到看不见的地方。
        """
        n = self.count()
        if not n or not self._auto_fit:
            return
        vw = max(60, self.viewport().width())
        vh = max(60, self.viewport().height())
        pad = self.spacing() * 2 + 4
        # 缩到 64px 以下就看不出画面内容了,那时才允许滚动 ——
        # "一下全部显示"的前提是还看得清,否则一屏糊点没有意义。
        MIN_USEFUL = 64
        best = None
        for t in range(220, MIN_USEFUL - 1, -4):
            cell_w, cell_h = t + pad, t + pad + 16      # +16 给文件名那行
            cols = max(1, vw // cell_w)
            rows = (n + cols - 1) // cols
            if rows * cell_h <= vh:
                best = t
                break
        if best is None:
            best = MIN_USEFUL
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        else:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        if best != self._thumb:
            self._thumb = best
            self._apply_sizes()
            self._rescale_icons()

    def _rescale_icons(self):
        """格子尺寸变了,图标要按新尺寸重新缩一遍,否则会模糊或留白。"""
        for i in range(self.count()):
            pm = self._pms[i] if i < len(self._pms) else None
            if pm is None:
                continue
            self.item(i).setIcon(QIcon(pm.scaled(
                self._thumb, self._thumb,
                Qt.KeepAspectRatio, Qt.SmoothTransformation)))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.relayout()          # 面板大小一变就重新算格子

    def paths(self):
        return [self.item(i).data(Qt.UserRole) for i in range(self.count())]


class ImageDialog(QDialog):
    """放大看图。左右键翻页,Esc 关闭。"""

    def __init__(self, paths, index=0, parent=None):
        super().__init__(parent)
        self._paths = [p for p in (paths or []) if p]
        self._i = max(0, min(index, len(self._paths) - 1)) if self._paths else 0
        self.setWindowTitle("查看图片")
        self.resize(900, 680)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        self.view = ImageView()
        lay.addWidget(self.view, 1)
        row = QHBoxLayout()
        self.lb = QLabel("")
        self.lb.setObjectName("Hint")
        b_prev = QPushButton("← 上一张")
        b_prev.clicked.connect(lambda: self.step(-1))
        b_next = QPushButton("下一张 →")
        b_next.clicked.connect(lambda: self.step(1))
        b_close = QPushButton("关闭")
        b_close.clicked.connect(self.accept)
        row.addWidget(self.lb, 1)
        row.addWidget(b_prev)
        row.addWidget(b_next)
        row.addWidget(b_close)
        lay.addLayout(row)
        self._render_cur()

    def _render_cur(self):
        if not self._paths:
            self.lb.setText("没有图片")
            return
        p = self._paths[self._i]
        self.view.load(p)
        self.lb.setText(
            f"{os.path.basename(p)}   ({self._i + 1}/{len(self._paths)})")

    def step(self, d):
        if not self._paths:
            return
        self._i = (self._i + d) % len(self._paths)
        self._render_cur()

    def current(self):
        return self._paths[self._i] if self._paths else ""

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Left, Qt.Key_Up):
            self.step(-1)
        elif e.key() in (Qt.Key_Right, Qt.Key_Down, Qt.Key_Space):
            self.step(1)
        else:
            super().keyPressEvent(e)
