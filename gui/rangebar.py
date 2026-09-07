# -*- coding: utf-8 -*-
"""剪辑软件那样的区间条:左右两个手柄拖选区间,中间一个播放头。

为什么自己画而不用两个 QSlider:两个滑块叠在一起没法表达"区间",
而且拖动时互相穿越很难处理。自己画能顺手做到:
- 拖到对面会自动交换,不会出现"结束在开始之前"这种非法状态
- 点空白处直接把播放头挪过去(剪辑软件的习惯)
- 区间外的部分压暗,一眼看出选了哪段
"""
from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont
from PySide6.QtWidgets import QWidget, QSizePolicy

from theme import C

H_W = 9          # 手柄宽度(像素)
BAR_H = 34       # 区间条本体高度
RULER_H = 14     # 下面刻度区高度


class VideoView(QWidget):
    """视频预览区:每次重绘都按当前控件尺寸缩放画面,保持比例并居中。

    为什么不用 QLabel + setPixmap:QLabel 的缩放是一次性的,窗口放大后
    画面停在旧尺寸,四周留一大片黑边。

    高度策略:自己不索要高度(sizePolicy 用 Ignored),布局给多少用多少。
    这一页要求"一屏放完",预览必须肯让位 —— 如果它按 16:9 索要高度,
    窗口一矮就会把区间条和按钮顶出可视范围,只能靠滚轮找。
    画面比例靠 paintEvent 里的 KeepAspectRatio 保证,不靠占地面积。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pm = None
        self._ar = 16 / 9.0          # 画面宽高比,拿到视频后更新
        self._hint = "选一个视频文件开始"
        # 最小高度给小一点:这一页要求一屏放完,预览必须肯让位,
        # 否则窗口一矮它就把区间条和按钮顶出可视范围。
        self.setMinimumHeight(120)
        # Expanding/Ignored:高度完全由布局分配,自己不提要求。
        # 之前用 Preferred + heightForWidth 会按 16:9 索要高度,窗口矮的时候
        # 就把下面的东西挤出去 —— 那正是"缩小后要滚轮"的原因之一。
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)

    def hasHeightForWidth(self):
        # 不再按比例索要高度,改成"给多少用多少",画面在 paintEvent 里居中
        return False

    def set_aspect(self, w, h):
        if w > 0 and h > 0:
            self._ar = w / float(h)
            self.updateGeometry()

    def set_frame(self, pm):
        self._pm = pm
        if pm is not None and not pm.isNull():
            self.set_aspect(pm.width(), pm.height())
        self.update()

    def set_hint(self, text):
        self._hint = text
        self._pm = None
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#101114"))
        if self._pm is None or self._pm.isNull():
            p.setPen(QColor(C["text_faint"]))
            p.drawText(self.rect(), Qt.AlignCenter, self._hint)
            p.end()
            return
        # 每次重绘都按当前控件尺寸缩放 —— 窗口怎么变都填得满
        pm = self._pm.scaled(self.size(), Qt.KeepAspectRatio,
                             Qt.SmoothTransformation)
        x = (self.width() - pm.width()) // 2
        y = (self.height() - pm.height()) // 2
        p.drawPixmap(x, y, pm)
        p.end()


class RangeBar(QWidget):
    """区间选择条。所有对外的值都是秒。"""

    range_changed = Signal(float, float)     # 开始, 结束
    head_moved = Signal(float)               # 播放头(拖动中会连续发)
    head_released = Signal(float)            # 松手(用来触发一次预览刷新)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dur = 0.0
        self._a = 0.0            # 区间开始
        self._b = 0.0            # 区间结束
        self._head = 0.0         # 播放头
        self._drag = None        # "a"/"b"/"head"/None
        self._marks = []         # 抽帧点(秒),画成小竖线
        self.setMinimumHeight(BAR_H + RULER_H + 6)
        self.setMinimumWidth(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    # ---------------- 对外接口 ----------------
    def set_duration(self, sec):
        self._dur = max(0.0, float(sec or 0))
        self._a, self._b = 0.0, self._dur
        self._head = 0.0
        self.update()

    def duration(self):
        return self._dur

    def range(self):
        return (min(self._a, self._b), max(self._a, self._b))

    def set_range(self, a, b):
        self._a = self._clamp(a)
        self._b = self._clamp(b)
        self.update()
        self.range_changed.emit(*self.range())

    def head(self):
        return self._head

    def set_head(self, sec, notify=False):
        self._head = self._clamp(sec)
        self.update()
        if notify:
            self.head_moved.emit(self._head)

    def set_marks(self, times):
        """把抽帧的时间点画在条上,能直观看出"抽得密不密"。"""
        self._marks = list(times or [])
        self.update()

    # ---------------- 坐标换算 ----------------
    def _clamp(self, v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = 0.0
        return max(0.0, min(v, self._dur))

    def _x_of(self, sec):
        if self._dur <= 0:
            return float(H_W)
        usable = max(1, self.width() - 2 * H_W)
        return H_W + usable * (self._clamp(sec) / self._dur)

    def _sec_of(self, x):
        if self._dur <= 0:
            return 0.0
        usable = max(1, self.width() - 2 * H_W)
        return self._clamp((x - H_W) / usable * self._dur)

    # ---------------- 交互 ----------------
    def mousePressEvent(self, e):
        if self._dur <= 0 or e.button() != Qt.LeftButton:
            return
        x = e.position().x()
        # 手柄的命中范围放宽到 ±10px,不然很难点中
        da, db = abs(x - self._x_of(self._a)), abs(x - self._x_of(self._b))
        if min(da, db) <= 10:
            self._drag = "a" if da <= db else "b"
        else:
            # 点在区间条上 = 挪播放头(剪辑软件都是这个习惯)
            self._drag = "head"
            self.set_head(self._sec_of(x), notify=True)
        self.update()

    def mouseMoveEvent(self, e):
        x = e.position().x()
        if self._drag is None:
            if self._dur > 0 and min(abs(x - self._x_of(self._a)),
                                     abs(x - self._x_of(self._b))) <= 10:
                self.setCursor(Qt.SizeHorCursor)     # 提示这里能拖
            else:
                self.setCursor(Qt.PointingHandCursor)
            return
        v = self._sec_of(x)
        if self._drag == "a":
            self._a = v
            self.range_changed.emit(*self.range())
        elif self._drag == "b":
            self._b = v
            self.range_changed.emit(*self.range())
        else:
            self._head = v
            self.head_moved.emit(self._head)
        self.update()

    def mouseReleaseEvent(self, e):
        if self._drag in ("a", "b"):
            # 拖过头了就交换,保证 a<=b。不这么做会出现"结束在开始之前"
            if self._a > self._b:
                self._a, self._b = self._b, self._a
                self._drag = "b" if self._drag == "a" else "a"
            # 播放头拽回区间内,不然预览的画面在区间外很迷惑
            a, b = self.range()
            if not (a <= self._head <= b):
                self._head = a
                self.head_moved.emit(self._head)
            self.range_changed.emit(*self.range())
        if self._drag == "head":
            self.head_released.emit(self._head)
        self._drag = None
        self.update()

    def keyPressEvent(self, e):
        """左右键微调播放头:1 帧级别的精细定位比鼠标准。"""
        step = 1.0 if e.modifiers() & Qt.ShiftModifier else 0.1
        if e.key() == Qt.Key_Left:
            self.set_head(self._head - step, notify=True)
            self.head_released.emit(self._head)
        elif e.key() == Qt.Key_Right:
            self.set_head(self._head + step, notify=True)
            self.head_released.emit(self._head)
        else:
            super().keyPressEvent(e)

    # ---------------- 绘制 ----------------
    def paintEvent(self, e):
        from video import fmt_time
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        top, h = 2, BAR_H
        # 底槽
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#101114")))
        p.drawRoundedRect(QRectF(H_W, top, max(1, self.width() - 2 * H_W), h), 4, 4)
        if self._dur <= 0:
            p.setPen(QColor(C["text_faint"]))
            p.drawText(self.rect(), Qt.AlignCenter, "先选一个视频")
            p.end()
            return
        xa, xb = self._x_of(self._a), self._x_of(self._b)
        if xa > xb:
            xa, xb = xb, xa
        # 选中区间:蓝色半透明填充
        sel = QColor(C["accent"])
        sel.setAlpha(56)
        p.setBrush(QBrush(sel))
        p.drawRect(QRectF(xa, top, xb - xa, h))
        # 抽帧点
        if self._marks:
            p.setPen(QPen(QColor(255, 255, 255, 90), 1))
            for t in self._marks:
                x = self._x_of(t)
                p.drawLine(QPointF(x, top + h - 9), QPointF(x, top + h - 2))
        # 两个手柄
        for x in (xa, xb):
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(C["accent"])))
            p.drawRoundedRect(QRectF(x - H_W / 2, top - 2, H_W, h + 4), 3, 3)
            p.setPen(QPen(QColor(255, 255, 255, 200), 1))
            for off in (-2, 2):
                p.drawLine(QPointF(x + off, top + h / 2 - 5),
                           QPointF(x + off, top + h / 2 + 5))
        # 播放头:白色细线 + 上面一个小三角
        xh = self._x_of(self._head)
        p.setPen(QPen(QColor("#FFFFFF"), 2))
        p.drawLine(QPointF(xh, top), QPointF(xh, top + h))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#FFFFFF")))
        # PySide6 的 drawPolygon 只接受【一个】点序列,分开传多个点会
        # TypeError,而 paintEvent 里抛异常会让 Qt 直接段错误(139)。
        p.drawPolygon([QPointF(xh - 4, top), QPointF(xh + 4, top),
                       QPointF(xh, top + 5)])
        # 刻度文字:开始 / 播放头 / 结束
        f = QFont()
        f.setPointSize(8)
        p.setFont(f)
        p.setPen(QColor(C["text_dim"]))
        a, b = self.range()
        ry = top + h + 1
        p.drawText(QRectF(H_W, ry, 90, RULER_H),
                   Qt.AlignLeft | Qt.AlignVCenter, fmt_time(a))
        p.drawText(QRectF(self.width() - H_W - 90, ry, 90, RULER_H),
                   Qt.AlignRight | Qt.AlignVCenter, fmt_time(b))
        p.setPen(QColor(C["text"]))
        p.drawText(QRectF(0, ry, self.width(), RULER_H),
                   Qt.AlignHCenter | Qt.AlignVCenter, fmt_time(self._head))
        p.end()
