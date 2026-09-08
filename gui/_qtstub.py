# -*- coding: utf-8 -*-
"""测试专用:一个极简的假 PySide6,让 app.py 能在没装 Qt 的环境里被导入和调用。

只为验证「逻辑」是否正确(参数拼装、配置往返、类别表读写、日志/进度处理),
不验证「外观」。真机上跑的是真 Qt。用法见 gui/test_gui.py。
"""
import sys
import types


class _Sig:
    def __init__(self, owner=None):
        self._subs = []
        self._owner = owner

    def connect(self, fn):
        self._subs.append(fn)

    def disconnect(self, *a):
        self._subs = []

    def emit(self, *a):
        # 真 Qt 里 blockSignals(True) 会拦住信号,测试必须还原这个语义,
        # 否则会漏掉「初始化期间误触发」这类真实 bug
        if self._owner is not None and getattr(self._owner, "_blocked", False):
            return
        for f in list(self._subs):
            # 真 PySide6 会按槽函数的参数个数截断多余参数,这里照做
            try:
                f(*a)
            except TypeError as e:
                if "positional argument" not in str(e):
                    raise
                f()


class _SigDescriptor:
    """模拟 PySide6 的 Signal:声明在类上,但每个实例各有一份订阅者。

    以前直接返回一个 _Sig(),类属性会被所有实例共享 —— 建第二个窗口时
    信号会串台(A 窗口的 emit 触发 B 窗口的槽)。真 Qt 不是这样的。
    """

    def __init__(self, name):
        self._name = name

    def __get__(self, obj, cls=None):
        if obj is None:
            return self
        store = obj.__dict__.setdefault("_sig_store", {})
        if self._name not in store:
            store[self._name] = _Sig(obj)
        return store[self._name]


_sig_counter = [0]


def Signal(*a, **k):
    _sig_counter[0] += 1
    return _SigDescriptor(f"sig{_sig_counter[0]}")


class _Flag(str):
    """枚举值。是 str 的子类,所以能比较、能当字典键,还支持 a | b。

    真 Qt 的 flags 是位掩码,代码里会写 flags() & ~Qt.ItemIsEditable
    (去掉某个位),所以这里也得支持 ~ 和 &。
    """
    def __or__(self, o):
        return _Flag(f"{self}|{o}")
    __ror__ = __or__

    def __invert__(self):
        return _Flag(f"~{self}")

    def __and__(self, o):
        return _Flag(f"{self}&{o}")
    __rand__ = __and__


class _Enum:
    """任意属性都返回一个唯一可比较的哨兵值(支持 | 组合)。"""
    def __init__(self, name="E"):
        self._n = name
        self._c = {}

    def __getattr__(self, k):
        if k.startswith("_"):
            raise AttributeError(k)
        return self._c.setdefault(k, _Flag(f"<{self._n}.{k}>"))


class _ListItem:
    """QListWidgetItem:测试要能读回文字和颜色(未标注的图要显示成灰色)。"""

    def __init__(self, text=""):
        self._t = text
        self._fg = None
        self._tip = ""

    def text(self):
        return self._t

    def setText(self, t=""):
        self._t = str(t)

    def setForeground(self, c):
        self._fg = c

    def foreground(self):
        return self._fg

    def setToolTip(self, t):
        self._tip = t

    def toolTip(self):
        return self._tip

    # 缩略图会往 item 上挂路径(UserRole)和图标
    def setData(self, role, v):
        self._data = getattr(self, "_data", {})
        self._data[role] = v

    def data(self, role):
        return getattr(self, "_data", {}).get(role)

    def setIcon(self, ic):
        self._icon = ic

    def icon(self):
        return getattr(self, "_icon", None)

    def setTextAlignment(self, a):
        self._align = a

    # 勾选框:AI 补充提示词页靠它做批量选择
    def flags(self):
        return getattr(self, "_flags", _Flag("<flags>"))

    def setFlags(self, f):
        self._flags = f

    def setCheckState(self, st):
        self._check = st

    def checkState(self):
        return getattr(self, "_check", None)


class _Pixmap:
    """假 QPixmap:只需要"有没有加载成功"和宽高。

    框编辑的坐标换算全靠宽高,所以这个必须是真数字,不能用万能兜底对象。
    测试里通过 _Pixmap.FAKE 注册"某路径 -> (w,h)"。
    """
    FAKE = {}

    def __init__(self, path=None, *a):
        self._p = path or ""
        if self._p in self.FAKE:
            self._w, self._h = self.FAKE[self._p]
            return
        # 没登记过的路径:如果磁盘上真有这个图,就读真实尺寸。
        # 程序运行中生成的图(比如缩略图缓存)没法预先登记,
        # 不读的话它们会被当成"加载失败",相关代码路径就测不到。
        self._w, self._h = 0, 0
        try:
            import os
            if self._p and os.path.isfile(self._p):
                from PIL import Image
                with Image.open(self._p) as im:
                    self._w, self._h = im.size
        except Exception:
            pass

    def isNull(self):
        return self._w <= 0 or self._h <= 0

    def width(self):
        return self._w

    def height(self):
        return self._h

    def rect(self):
        return (0, 0, self._w, self._h)

    def scaled(self, *a, **k):
        return self

    def fill(self, *a):
        pass


class _MouseEv:
    """假鼠标事件。pos 用图片坐标之外的控件坐标。"""

    def __init__(self, x, y, button="left", mods=0):
        self._x, self._y = float(x), float(y)
        self._b = button
        self._m = mods

    def position(self):
        return _Pt(self._x, self._y)

    def button(self):
        # 必须和 _Enum("Qt") 生成的值一致,否则 == Qt.LeftButton 永远为假
        return _Flag("<Qt.LeftButton>") if self._b == "left" \
            else _Flag("<Qt.RightButton>")

    def modifiers(self):
        return self._m

    def key(self):
        return None


class _Pt:
    def __init__(self, x, y):
        self._x, self._y = x, y

    def x(self):
        return self._x

    def y(self):
        return self._y


class _WheelEv:
    """假的滚轮事件"""
    def type(self): return "<QEvent.Wheel>"
    def ignore(self): self._ignored = True


class Obj:
    """万能 Qt 控件替身:任何方法都可调用,任何属性都存在。"""
    _sigs = ("clicked", "textChanged", "currentIndexChanged", "valueChanged",
             "stateChanged", "currentRowChanged", "readyReadStandardOutput",
             "finished", "errorOccurred", "toggled", "triggered",
             "itemChanged", "cellChanged", "currentChanged")

    def __init__(self, *a, **k):
        # 真 Qt 里 QHBoxLayout(parent) 会把后续 addWidget 的控件 reparent 到 parent,
        # 所以 parent.findChild() 找得到。这里记住这个 parent 来还原该语义。
        self._layout_parent = a[0] if (a and isinstance(a[0], Obj)) else None
        self._t = ""
        self._items = []      # (text, data)
        self._idx = -1
        self._val = 0
        self._checked = False
        self._rows = 0
        self._cols = 0
        self._cells = {}
        self._widgets = {}
        self._vis = True
        self._enabled = True
        self._children = []
        self._cur_row = -1
        self._blocked = False
        self._objname = ""
        for s in self._sigs:
            setattr(self, s, _Sig(self))
        if a and isinstance(a[0], str):
            self._t = a[0]

    def __getattr__(self, k):
        if k.startswith("_"):
            raise AttributeError(k)
        return _Noop(k)

    # 文本
    def setText(self, t=""): self._t = str(t)
    def text(self): return self._t

    # 提示气泡:测试要能读回内容(比如"这条改动过大"的警告)
    def setToolTip(self, t=""): self._tip = str(t)
    def toolTip(self): return getattr(self, "_tip", "")

    # 有些控件会调 super().resizeEvent(e) / super().keyPressEvent(e),
    # 假 Qt 得提供这些空实现,否则 AttributeError
    def resizeEvent(self, e=None): pass
    def keyPressEvent(self, e=None): pass
    def paintEvent(self, e=None): pass
    def showEvent(self, e=None): pass

    def setWindowTitle(self, t=""): self._wtitle = str(t)
    def windowTitle(self): return getattr(self, "_wtitle", "")

    # objectName 决定 QSS 样式(#Primary/#Danger/#RowDel),测试要能读回来
    def setObjectName(self, n=""): self._objname = str(n)
    def objectName(self): return getattr(self, "_objname", "")

    def click(self):
        """模拟点击:真 Qt 的 QPushButton.click() 会发 clicked 信号。"""
        self.clicked.emit(False)
    def setPlainText(self, t=""): self._t = str(t)
    def toPlainText(self): return self._t
    def appendPlainText(self, t=""): self._t += str(t) + "\n"
    def appendHtml(self, t=""): self._t += str(t) + "\n"
    def clear(self):
        self._t = ""
        self._items = []
        self._idx = -1

    # 下拉框
    def addItem(self, text, data=None):
        self._items.append((text, data))
        if self._idx < 0:
            self._idx = 0
    def count(self): return len(self._items)
    def findData(self, d):
        for i, (_, dd) in enumerate(self._items):
            if dd == d:
                return i
        return -1
    def setCurrentIndex(self, i):
        self._idx = i
        # 真 Qt:切换选中项会同步更新可编辑框里的文字
        if 0 <= i < len(self._items):
            self._t = self._items[i][0]
        self.currentIndexChanged.emit(i)
    def currentIndex(self): return self._idx
    def currentData(self):
        return self._items[self._idx][1] if 0 <= self._idx < len(self._items) else None
    def currentText(self):
        # 真 Qt:可编辑下拉框返回输入框里的文字(可能是用户手打的,
        # 未必等于当前选中项)。测试要能模拟"手打"就必须以 _t 为准。
        if self._t:
            return self._t
        return self._items[self._idx][0] if 0 <= self._idx < len(self._items) else ""
    def setItemData(self, i, v, role=None): self._idata = getattr(self,'_idata',{}); self._idata[(i,role)]=v
    def itemText(self, i):
        return self._items[i][0] if 0 <= i < len(self._items) else ""
    def lineEdit(self):
        self._le = getattr(self, "_le", None) or Obj()
        return self._le
    def setEditable(self, b): pass
    def itemData(self, i):
        return self._items[i][1] if 0 <= i < len(self._items) else None

    # 数值
    def setValue(self, v):
        self._val = v
        self.valueChanged.emit(v)
    def value(self): return self._val
    def setRange(self, a, b): self._lo, self._hi = a, b

    # 勾选
    def setChecked(self, b):
        self._checked = bool(b)
        self.stateChanged.emit(2 if b else 0)
        self.toggled.emit(bool(b))
    def isChecked(self): return self._checked

    # 表格
    def setRowCount(self, n):
        if n == 0:
            self._cells, self._widgets = {}, {}
        self._rows = n
    def rowCount(self): return self._rows

    # 列宽/行高:缩放逻辑要能验证,所以真的存下来
    def setColumnWidth(self, c, w):
        self._colw = getattr(self, "_colw", {})
        self._colw[c] = w

    def columnWidth(self, c):
        return getattr(self, "_colw", {}).get(c, 100)

    def setDefaultSectionSize(self, n): self._secsz = n
    def defaultSectionSize(self): return getattr(self, "_secsz", 30)

    def viewport(self):
        # ThumbStrip 用 viewport 的尺寸来算格子大小,得给个真实数字
        if not hasattr(self, "_vp"):
            self._vp = Obj()
            self._vp.resize(400, 300)
        return self._vp

    def setSpacing(self, n): self._spacing = n
    def spacing(self): return getattr(self, "_spacing", 0)
    def setIconSize(self, s): self._iconsz = s
    def iconSize(self): return getattr(self, "_iconsz", None)
    def setGridSize(self, s): self._gridsz = s
    def gridSize(self): return getattr(self, "_gridsz", None)

    def verticalHeader(self):
        # 必须每次返回【同一个】对象,否则设进去的行高下次读不到
        if not hasattr(self, "_vhdr"):
            self._vhdr = Obj()
        return self._vhdr

    def horizontalHeader(self):
        if not hasattr(self, "_hhdr"):
            self._hhdr = Obj()
        return self._hhdr

    def setHorizontalHeaderLabels(self, labels):
        self._hdr = list(labels)

    def horizontalHeaderItem(self, i):
        h = getattr(self, "_hdr", [])
        return _ListItem(h[i]) if 0 <= i < len(h) else None
    def setColumnCount(self, n): self._cols = n
    def columnCount(self): return self._cols
    def insertRow(self, r): self._rows += 1
    def removeRow(self, r):
        self._rows -= 1
        nc, nw = {}, {}
        for (rr, cc), v in self._cells.items():
            nc[(rr - 1 if rr > r else rr, cc)] = v if rr != r else None
        self._cells = {k: v for k, v in nc.items() if v is not None}
        for (rr, cc), v in self._widgets.items():
            if rr != r:
                nw[(rr - 1 if rr > r else rr, cc)] = v
        self._widgets = nw
    def setItem(self, r, c, it): self._cells[(r, c)] = it
    def item(self, r, c): return self._cells.get((r, c))
    def setCellWidget(self, r, c, w):
        self._widgets[(r, c)] = w
        if isinstance(w, Obj): self._children.append(w)
    def cellWidget(self, r, c): return self._widgets.get((r, c))
    def selectedIndexes(self): return getattr(self, "_sel", [])
    def horizontalHeader(self): return self
    def viewport(self):
        # ThumbStrip 用 viewport 的尺寸来算格子大小,得给个真实数字
        if not hasattr(self, "_vp"):
            self._vp = Obj()
            self._vp.resize(400, 300)
        return self._vp

    def setSpacing(self, n): self._spacing = n
    def spacing(self): return getattr(self, "_spacing", 0)
    def setIconSize(self, s): self._iconsz = s
    def iconSize(self): return getattr(self, "_iconsz", None)
    def setGridSize(self, s): self._gridsz = s
    def gridSize(self): return getattr(self, "_gridsz", None)

    def verticalHeader(self): return self

    # 列表
    def addItem_list(self, t): self._items.append((t, None))
    def setCurrentRow(self, r):
        self._cur_row = r
        self.currentRowChanged.emit(r)
    def currentRow(self): return self._cur_row

    # 可见/启用
    def setVisible(self, b): self._vis = bool(b)
    def isVisible(self): return self._vis
    def setEnabled(self, b): self._enabled = bool(b)
    def isEnabled(self): return self._enabled

    # 布局/容器
    def addWidget(self, w=None, *a, **k):
        self._children.append(w)
        # 模拟 reparent:加到某个 layout 上的控件,也算那个 layout 宿主的子控件
        if self._layout_parent is not None and isinstance(w, Obj):
            self._layout_parent._children.append(w)
    def addLayout(self, l=None, *a, **k):
        self._children.append(l)
        if isinstance(l, Obj):
            # 宿主沿 layout 链往下传:QGridLayout() 这种建时没给 parent 的,
            # 被 addLayout 挂上来之后,它的 addWidget 也要归到同一个宿主。
            # 不这么做,findChildren 会漏掉网格里的控件。
            if l._layout_parent is None:
                l._layout_parent = self._layout_parent
            if self._layout_parent is not None:
                self._layout_parent._children.append(l)
    def setCentralWidget(self, w):
        # 真 Qt 里这一步会让 w 成为窗口的子控件,findChildren 才找得到整棵树
        if isinstance(w, Obj):
            self._children.append(w)
        self._central = w
    def setWidget(self, w):
        if isinstance(w, Obj):
            self._children.append(w)
        return w
    def setCellWidget_track(self, w):
        if isinstance(w, Obj):
            self._children.append(w)
    def addStretch(self, *a): pass
    def findChildren(self, typ=None, name=None):
        out, seen = [], set()
        def walk(o):
            for c in getattr(o, "_children", []):
                if not isinstance(c, Obj) or id(c) in seen: continue
                seen.add(id(c))
                if typ is None or isinstance(c, typ): out.append(c)
                walk(c)
        walk(self)
        return out

    def findChild(self, typ=None, name=None):
        """按类型递归找子控件(真 Qt 的 findChild 也是递归的)。"""
        for c in self._children:
            if not isinstance(c, Obj):
                continue
            if typ is None or isinstance(c, typ):
                return c
        for c in self._children:                 # 再往下一层找
            if isinstance(c, Obj):
                got = c.findChild(typ, name)
                if got is not None:
                    return got
        return None
    def widget(self, i=0): return None
    def button(self, i): return self._btns.setdefault(i, Obj()) if hasattr(self, "_btns") else Obj()
    def font(self): return Obj()
    def size(self): return Obj()
    def installEventFilter(self, f):
        self._filters = getattr(self, "_filters", [])
        self._filters.append(f)
    def hasFocus(self): return getattr(self, "_focus", False)
    def setFocusPolicy(self, p): self._fp = p
    def wheel(self):
        """测试用:模拟一次滚轮。返回 True=被过滤器吃掉(值不会变)"""
        ev = _WheelEv()
        for f in getattr(self, "_filters", []):
            if f.eventFilter(self, ev): return True
        return False

    def resize(self, w, h):
        """测试用:给控件一个真实尺寸,否则 width()/height() 是 0,
        画布的缩放/命中判定全都算不出来。"""
        self._w_px, self._h_px = int(w), int(h)

    def width(self):
        return getattr(self, "_w_px", 0)

    def height(self):
        return getattr(self, "_h_px", 0)

    def size(self):
        return _Noop(0, w=self.width(), h=self.height())

    def rect(self):
        return _Noop(0, w=self.width(), h=self.height())

    def blockSignals(self, b):
        old = self._blocked
        self._blocked = bool(b)
        return old
    def showMessage(self, *a, **k): pass


class _Noop(int):
    """未实现的方法:调用后返回自己,支持链式,不报错。
    继承 int(值0)是为了让 size().width()-8 这类算术不炸 —— 真 Qt 返回的是数字。

    带 w/h 时可以当 QSize/QRect 用:size().width() 会返回真实宽度,
    框编辑的坐标换算需要这个。"""
    def __new__(cls, name="noop", w=None, h=None):
        o = super().__new__(cls, 0)
        o._name = name
        o._w, o._h = w, h
        return o

    def __call__(self, *a, **k):
        return self

    def width(self):
        return _Noop("w") if self._w is None else self._w

    def height(self):
        return _Noop("h") if self._h is None else self._h

    def __getattr__(self, k):
        if k.startswith("_"):
            raise AttributeError(k)
        return _Noop(k)

    def __bool__(self):
        return False


class ListObj(Obj):
    # QListWidget 的枚举常量(IconMode/Adjust/Static 等),
    # ThumbStrip 会用到。用 _Flag 占位就够了。
    IconMode = _Flag("<IconMode>")
    ListMode = _Flag("<ListMode>")
    Adjust = _Flag("<Adjust>")
    Fixed = _Flag("<Fixed>")
    Static = _Flag("<Static>")
    Free = _Flag("<Free>")

    def addItem(self, t):
        # 真 Qt 的 addItem 既收字符串也收 QListWidgetItem。
        # 存成 (显示文字, item对象),测试才能检查颜色/提示。
        if isinstance(t, _ListItem):
            self._items.append((t.text(), t))
        else:
            self._items.append((t, None))

    def item(self, i):
        return self._items[i][1] if 0 <= i < len(self._items) else None

    def count(self): return len(self._items)


class ButtonGroup(Obj):
    def __init__(self, *a, **k):
        super().__init__()
        self._btns = {}
    def addButton(self, b, i): self._btns[i] = b
    def button(self, i): return self._btns.get(i, Obj())
    def setExclusive(self, b): pass


class Stack(Obj):
    def __init__(self, *a, **k):
        super().__init__()
        self._pages = []
        self._cur = 0
    def addWidget(self, w=None, *a, **k):
        self._pages.append(w)
        if isinstance(w, Obj): self._children.append(w)   # 页面也是子控件
        return len(self._pages) - 1
    def setCurrentIndex(self, i):
        self._cur = i
        self.currentChanged.emit(i)
    def currentIndex(self): return self._cur


class MsgBox(Obj):
    """QMessageBox:测试里用 MsgBox.ANSWER 控制返回值,并记录所有弹窗。"""
    Yes, No, Cancel, Ok = (_Flag("<Yes>"), _Flag("<No>"),
                           _Flag("<Cancel>"), _Flag("<Ok>"))
    # 保存/丢弃:未保存的框修改要用到
    Save, Discard = _Flag("<Save>"), _Flag("<Discard>")
    ANSWER = Yes
    CALLS = []

    @classmethod
    def question(cls, parent, title, text, *a, **k):
        cls.CALLS.append(("question", title, text))
        return cls.ANSWER

    @classmethod
    def warning(cls, parent, title, text, *a, **k):
        cls.CALLS.append(("warning", title, text))
        # 传了按钮参数 = 在问"要不要",按 ANSWER 回答;
        # 没传 = 纯提示框,回 Ok。
        return cls.ANSWER if a else cls.Ok

    @classmethod
    def information(cls, parent, title, text, *a, **k):
        cls.CALLS.append(("information", title, text))
        return cls.Ok

    @classmethod
    def critical(cls, parent, title, text, *a, **k):
        cls.CALLS.append(("critical", title, text))
        return cls.Ok


class InputDialog(Obj):
    """QInputDialog:测试里用 TEXT/OK 控制用户输入了什么、点没点确定。"""
    TEXT = ""
    OK = True
    CALLS = []

    @classmethod
    def getText(cls, parent, title, label, *a, **k):
        cls.CALLS.append((title, label, k.get("text", "")))
        return cls.TEXT, cls.OK


class App(Obj):
    _inst = None
    def __init__(self, *a, **k):
        super().__init__()
        App._inst = self
    @staticmethod
    def clipboard(): return Obj()
    @staticmethod
    def processEvents(*a, **k): pass
    @staticmethod
    def instance(): return App._inst
    def font(self): return getattr(self, "_font", Obj())
    def setFont(self, f): self._font = f
    def setStyleSheet(self, s): self._ss = s
    def exec(self): return 0


def install():
    """把假 PySide6 塞进 sys.modules。必须在 import app 之前调用。"""
    QtCore = types.ModuleType("PySide6.QtCore")
    QtGui = types.ModuleType("PySide6.QtGui")
    QtWidgets = types.ModuleType("PySide6.QtWidgets")
    PySide6 = types.ModuleType("PySide6")
    PySide6.__version__ = "0-stub"

    class _AnyAttrMeta0(type):
        def __getattr__(cls, k):
            if k.startswith("__"):
                raise AttributeError(k)
            return _Flag(f"<{cls.__name__}.{k}>")

    QtCore.Qt = _Enum("Qt")
    QtCore.QEvent = _Enum("QEvent")
    QtCore.Signal = Signal
    QtCore.QObject = Obj
    QtCore.QUrl = _AnyAttrMeta0("QUrl", (Obj,), {})
    QtCore.QSize = Obj
    class _Timer(Obj):
        """QTimer:记住 start/stop 状态,让"是否正在播放"这类逻辑可测。
        singleShot 立即执行,测试才能看到效果。"""
        singleShot = staticmethod(lambda ms, fn: fn())

        def __init__(self, *a, **k):
            super().__init__()
            self._active = False

        def start(self, *a):
            self._active = True

        def stop(self):
            self._active = False

        def isActive(self):
            return self._active

    QtCore.QTimer = _Timer

    class QProcess(Obj):
        NotRunning, Running = "<NotRunning>", "<Running>"
        MergedChannels = "<Merged>"
        LAST = None
        def __init__(self, *a, **k):
            super().__init__()
            self._state = QProcess.NotRunning
            self._prog, self._args, self._wd, self._env = None, [], None, {}
            QProcess.LAST = self
        def setProgram(self, p): self._prog = p
        def setArguments(self, a): self._args = list(a)
        def setWorkingDirectory(self, d): self._wd = d
        def setProcessChannelMode(self, m): pass
        def processEnvironment(self): return Obj()
        def setProcessEnvironment(self, e): self._env = e
        def start(self): self._state = QProcess.Running
        def waitForStarted(self, ms=0): return True
        def waitForFinished(self, ms=0):
            self._exit()
            return True
        def state(self): return self._state
        def _exit(self, code=0):
            """真 Qt 里进程结束会发 finished 信号,测试必须还原,
            否则 runner 的收尾逻辑(按钮复位/日志)永远不会跑。"""
            if self._state != QProcess.NotRunning:
                self._state = QProcess.NotRunning
                self.finished.emit(code, "<Crash>")
        def terminate(self): self._exit(0)
        def kill(self): self._exit(0)
        def readAllStandardOutput(self): return getattr(self, "_out", b"")
    QtCore.QProcess = QProcess

    class QPE(Obj):
        def __init__(self, *a, **k):
            super().__init__()
            self._d = {}
        def insert(self, k, v): self._d[k] = v
        def keys(self): return list(self._d)
        def value(self, k, d=None): return self._d.get(k, d)
    QtCore.QProcessEnvironment = QPE

    # 这些类既当实例用(QPainter(pm)),又当枚举容器用(QPainter.Antialiasing),
    # 所以给它们一个「任意类属性都存在」的元类。
    class _AnyAttrMeta(type):
        def __getattr__(cls, k):
            if k.startswith("__"):
                raise AttributeError(k)
            return _Flag(f"<{cls.__name__}.{k}>")

    for n in ("QPainter", "QIcon", "QPen", "QFont", "QImage", "QBrush"):
        setattr(QtGui, n, _AnyAttrMeta(n, (Obj,), {}))

    class _Color(Obj):
        """QColor:把构造参数留着,测试才能验证到底设了什么颜色。"""
        def __init__(self, *a, **k):
            super().__init__()
            self._args = a

        def name(self):
            return self._args[0] if (self._args and
                                     isinstance(self._args[0], str)) else ""

    QtGui.QColor = _Color
    QtGui.QTextCursor = _Enum("QTextCursor")
    QtGui.QDesktopServices = type("QDS", (Obj,), {
        "openUrl": staticmethod(lambda u: True)})

    widget_names = ("QWidget", "QMainWindow", "QVBoxLayout", "QHBoxLayout",
                    "QGridLayout", "QLabel", "QPushButton", "QLineEdit",
                    "QComboBox", "QSpinBox", "QDoubleSpinBox", "QPlainTextEdit",
                    "QTextEdit", "QTextBrowser", "QTableWidget", "QSplitter", "QCheckBox",
                    "QProgressBar", "QFrame", "QScrollArea", "QStatusBar",
                    "QTreeWidget", "QKeySequenceEdit", "QSlider")
    for n in widget_names:
        setattr(QtWidgets, n, _AnyAttrMeta(n, (Obj,), {}))
    QtWidgets.QListWidget = ListObj
    QtWidgets.QButtonGroup = ButtonGroup
    QtWidgets.QStackedWidget = Stack
    QtWidgets.QMessageBox = MsgBox
    QtWidgets.QInputDialog = InputDialog
    QtWidgets.QApplication = App
    QtWidgets.QHeaderView = _Enum("QHeaderView")
    QtWidgets.QSizePolicy = _Enum("QSizePolicy")
    QtWidgets.QAbstractItemView = _Enum("QAbstractItemView")
    class _FileDialog(Obj):
        """QFileDialog:测试里用 PICK 指定"用户选了哪个文件/文件夹"。
        PICK="" 等于用户点了取消。"""
        PICK = ""

        @staticmethod
        def getExistingDirectory(*a, **k):
            return _FileDialog.PICK

        @staticmethod
        def getOpenFileName(*a, **k):
            return (_FileDialog.PICK, "")

    QtWidgets.QFileDialog = _FileDialog
    QtGui.QPalette = _AnyAttrMeta("QPalette", (Obj,), {})
    # --- KeyField / SearchableCombo 需要的 ---
    QtWidgets.QDialog = _AnyAttrMeta("QDialog", (Obj,), {
        "exec": lambda self: MsgBox.ANSWER,
        "Accepted": "<Accepted>",
        "reject": lambda self: None, "accept": lambda self: None})
    QtWidgets.QCompleter = _AnyAttrMeta("QCompleter", (Obj,), {})
    QtWidgets.QLayout = _AnyAttrMeta("QLayout", (Obj,), {})
    QtWidgets.QListWidgetItem = _ListItem
    QtWidgets.QTreeWidgetItem = _ListItem
    QtCore.QRect = _AnyAttrMeta("QRect", (Obj,), {})
    QtCore.QRectF = _AnyAttrMeta("QRectF", (Obj,), {})
    class _PointF:
        """真的存 x/y —— 缩放/命中判定全靠这两个数,不能用万能兜底对象。"""

        def __init__(self, x=0.0, y=0.0):
            self._x, self._y = float(x), float(y)

        def x(self):
            return self._x

        def y(self):
            return self._y

        def __sub__(self, o):
            return _PointF(self._x - o.x(), self._y - o.y())

        def __add__(self, o):
            return _PointF(self._x + o.x(), self._y + o.y())

        def __repr__(self):
            return f"QPointF({self._x:.1f}, {self._y:.1f})"

    QtCore.QPointF = _PointF
    QtCore.QPoint = _PointF
    QtCore.QPoint = _AnyAttrMeta("QPoint", (Obj,), {})

    # --- 框编辑画布需要的 ---
    QtGui.QShortcut = _AnyAttrMeta("QShortcut", (Obj,), {})
    QtGui.QKeySequence = _AnyAttrMeta("QKeySequence", (Obj,), {})
    QtGui.QBrush = _AnyAttrMeta("QBrush", (Obj,), {})
    QtGui.QPixmap = _Pixmap

    QtCore.QStringListModel = _AnyAttrMeta("QStringListModel", (Obj,), {})


    # QTableWidgetItem 要能存文本/图标/tooltip
    class TWI(Obj):
        def __init__(self, t=""):
            super().__init__()
            self._t = str(t)
            self._tip = ""
        def setIcon(self, i): self._icon = i
        def setToolTip(self, t): self._tip = str(t)
        def toolTip(self): return self._tip
        def setTextAlignment(self, a): pass
        def setForeground(self, c): self._fg = c
    QtWidgets.QTableWidgetItem = TWI

    PySide6.QtCore, PySide6.QtGui, PySide6.QtWidgets = QtCore, QtGui, QtWidgets
    for m, n in ((PySide6, "PySide6"), (QtCore, "PySide6.QtCore"),
                 (QtGui, "PySide6.QtGui"), (QtWidgets, "PySide6.QtWidgets")):
        sys.modules[n] = m
    QtGui._Pixmap = _Pixmap
    QtCore._MouseEv = _MouseEv
    return QtWidgets, QtCore, QtGui
