# -*- coding: utf-8 -*-
"""可拖动的框编辑画布。

用来人工修正 AI 标注:拖动整个框、拖 8 个角/边改大小、拉新框、删框、改类别。
所有坐标对外都是 0~1 归一化(和 YOLO 标签一致),内部才转成屏幕像素。

设计要点:
- 底图必须是【原图】而不是 vis 预览图,否则会看到两层框。
- 图片按比例缩放居中显示,所有命中判定都在"图片坐标系"里做,
  避免缩放后点不准。
- 每次修改都记进撤销栈,误拖了能 Ctrl+Z 回去。
"""
from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen, QBrush, QFont
from PySide6.QtWidgets import QWidget, QSizePolicy

# 8 个缩放手柄的位置代号
HANDLES = ("tl", "t", "tr", "r", "br", "b", "bl", "l")
HANDLE_PX = 8          # 手柄命中范围(屏幕像素)
MIN_BOX_PX = 6         # 小于这个尺寸的框不接受(防手抖点出一个点)


class BoxCanvas(QWidget):
    """显示图片 + 可编辑的框。"""

    changed = Signal()              # 框有任何改动(用于标记未保存)
    selection_changed = Signal(int)  # 当前选中的框序号,-1 表示没选
    zoom_changed = Signal(float)     # 滚轮缩放倍数变了
    step_image = Signal(int)         # 请求翻图:-1 上一张 / +1 下一张
    pending_changed = Signal(bool)   # 有/没有待确认的新框

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pm = None             # 原图 QPixmap
        self._boxes = []            # [{"cid","xc","yc","w","h"}] 归一化
        self._colors = []           # [(r,g,b)] 按 cid 取色
        self._names = []            # 类别名,画标签用
        self._sel = -1
        self._undo = []
        self._redo = []
        # 交互状态
        self._mode = None           # None/"move"/"resize"/"new"
        self._handle = None
        self._drag_from = None      # 拖动起点(图片坐标)
        self._orig = None           # 拖动前的框(用于计算增量)
        self._new_rect = None       # 正在拉的新框(图片坐标)
        self._snap = None           # 本次操作前的框快照(判断是否真改了)
        self._new_cid = 0           # 拉新框时用的类别
        self.setMouseTracking(True)
        self._cross = None        # 鼠标位置,用来画十字辅助线
        self._zoom = 1.0          # 滚轮缩放系数(1.0 = 整张刚好放下)
        self._pan = (0.0, 0.0)    # 平移量,配合缩放用
        self._pending = None      # 画好待确认的框(回车确定/Esc 取消)
        self._pending_snap = None
        # 主窗口启用可配置快捷键后，由 QShortcut 接管键盘操作；独立使用画布
        # 或逻辑测试时仍保留下面的内置默认按键。
        self._external_shortcuts = False
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(320, 260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.CrossCursor)

    # ---------------- 对外接口 ----------------
    def load(self, img_path, boxes, colors, names):
        """换一张图。boxes 是归一化框列表(会被复制,不改调用方的数据)。"""
        pm = QPixmap(img_path)
        self._pm = None if pm.isNull() else pm
        self._boxes = [dict(b) for b in (boxes or [])]
        self._colors = colors or [(74, 158, 255)]
        self._names = names or []
        self._sel = -1
        self._undo, self._redo = [], []
        self._mode = None
        self._snap = None
        self._pending = None      # 换图时丢掉待确认的框(它属于上一张图)
        self._pending_snap = None
        # 换图归位:上一张放大到 8 倍,下一张不该还停在那个视角
        self._zoom = 1.0
        self._pan = (0.0, 0.0)
        self.update()
        self.selection_changed.emit(-1)
        self.zoom_changed.emit(self._zoom)
        return self._pm is not None

    def boxes(self):
        return [dict(b) for b in self._boxes]

    def set_new_class(self, cid):
        """设置"拉新框时用哪个类别"。"""
        self._new_cid = int(cid)

    def selected(self):
        return self._sel

    def set_selected_class(self, cid):
        if 0 <= self._sel < len(self._boxes):
            self._push_undo()
            self._boxes[self._sel]["cid"] = int(cid)
            self.update()
            self.changed.emit()

    def delete_selected(self):
        if 0 <= self._sel < len(self._boxes):
            self._push_undo()
            self._boxes.pop(self._sel)
            self._sel = -1
            self.update()
            self.changed.emit()
            self.selection_changed.emit(-1)

    def clear_boxes(self):
        if self._boxes:
            self._push_undo()
            self._boxes = []
            self._sel = -1
            self.update()
            self.changed.emit()
            self.selection_changed.emit(-1)

    def undo(self):
        if self._undo:
            self._redo.append([dict(b) for b in self._boxes])
            self._boxes = self._undo.pop()
            self._sel = min(self._sel, len(self._boxes) - 1)
            self.update()
            self.changed.emit()
            self.selection_changed.emit(self._sel)

    def redo(self):
        if self._redo:
            self._undo.append([dict(b) for b in self._boxes])
            self._boxes = self._redo.pop()
            self._sel = min(self._sel, len(self._boxes) - 1)
            self.update()
            self.changed.emit()
            self.selection_changed.emit(self._sel)

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def _push_undo(self):
        self._undo.append([dict(b) for b in self._boxes])
        if len(self._undo) > 100:
            self._undo.pop(0)
        self._redo.clear()

    def _same(self, a, b):
        """两份框列表是否一样(用来判断这次操作到底改了没)。"""
        if len(a) != len(b):
            return False
        for p, q in zip(a, b):
            if p["cid"] != q["cid"]:
                return False
            for k in ("xc", "yc", "w", "h"):
                if abs(p[k] - q[k]) > 1e-9:
                    return False
        return True

    def _commit(self, snap):
        """真的改了才记进撤销栈。

        以前是鼠标一按下就无条件 _push_undo(),于是"点一下选中某个框"
        也会压一层【当前状态】进去。撤销时回到的就是这个没变化的状态,
        看起来就是"撤销按了没反应"。必须按两次才退回上一步 —— 这就是
        你遇到的问题。现在只有内容真的变了才记。
        """
        if snap is None or self._same(snap, self._boxes):
            return False
        self._undo.append(snap)
        if len(self._undo) > 100:
            self._undo.pop(0)
        self._redo.clear()
        return True

    # ---------------- 坐标换算 ----------------
    def _base_fit(self):
        """不考虑缩放时的显示区域 (ox, oy, scale) —— 也就是"整张刚好放进控件"。"""
        if self._pm is None:
            return 0.0, 0.0, 1.0
        cw, ch = max(1, self.width() - 8), max(1, self.height() - 8)
        iw, ih = self._pm.width(), self._pm.height()
        s = min(cw / iw, ch / ih)
        s = min(s, 4.0)              # 小图别放太大,免得糊成一片
        dw, dh = iw * s, ih * s
        return (self.width() - dw) / 2, (self.height() - dh) / 2, s

    def _fit(self):
        """图片当前的显示区域 (ox, oy, scale),已经算上滚轮缩放和平移。

        所有坐标换算(命中判定、画框、十字线)都走这里,所以只要这一个函数
        支持缩放,别的地方不用改。
        """
        ox, oy, s = self._base_fit()
        if self._pm is None or abs(self._zoom - 1.0) < 1e-6:
            return ox, oy, s
        # 以控件中心为基准放大,再加上平移量
        z = self._zoom
        iw, ih = self._pm.width() * s, self._pm.height() * s
        cx, cy = self.width() / 2, self.height() / 2
        nx = cx - (cx - ox) * z + self._pan[0]
        ny = cy - (cy - oy) * z + self._pan[1]
        return nx, ny, s * z

    def _to_img(self, pos):
        """控件坐标 -> 图片像素坐标。"""
        ox, oy, s = self._fit()
        return (pos.x() - ox) / s, (pos.y() - oy) / s

    def _to_screen(self, x, y):
        ox, oy, s = self._fit()
        return ox + x * s, oy + y * s

    def _box_rect_img(self, b):
        """归一化框 -> 图片像素矩形 (x1,y1,x2,y2)。"""
        iw, ih = self._pm.width(), self._pm.height()
        bw, bh = b["w"] * iw, b["h"] * ih
        x1, y1 = b["xc"] * iw - bw / 2, b["yc"] * ih - bh / 2
        return x1, y1, x1 + bw, y1 + bh

    def _set_box_from_img(self, i, x1, y1, x2, y2):
        iw, ih = self._pm.width(), self._pm.height()
        if x2 < x1:
            x1, x2 = x2, x1
        if y2 < y1:
            y1, y2 = y2, y1
        # 夹在图片范围内
        x1, x2 = max(0, min(x1, iw)), max(0, min(x2, iw))
        y1, y2 = max(0, min(y1, ih)), max(0, min(y2, ih))
        b = self._boxes[i]
        b["xc"] = ((x1 + x2) / 2) / iw
        b["yc"] = ((y1 + y2) / 2) / ih
        b["w"] = abs(x2 - x1) / iw
        b["h"] = abs(y2 - y1) / ih

    def _color(self, cid):
        if not self._colors:
            return QColor(74, 158, 255)
        return QColor(*self._colors[int(cid) % len(self._colors)])

    def _label(self, cid):
        if 0 <= int(cid) < len(self._names):
            return self._names[int(cid)]
        return str(cid)

    # ---------------- 命中判定 ----------------
    def _hit(self, pos):
        """返回 (框序号, 手柄名或None)。优先命中选中框的手柄,再命中框体。"""
        if self._pm is None:
            return -1, None
        _, _, s = self._fit()
        tol = HANDLE_PX / max(s, 1e-6)      # 换算到图片坐标的容差
        mx, my = self._to_img(pos)
        # 先看当前选中框的手柄(手柄在框边上,必须优先)
        order = ([self._sel] if 0 <= self._sel < len(self._boxes) else []) + \
                [i for i in range(len(self._boxes)) if i != self._sel]
        for i in order:
            x1, y1, x2, y2 = self._box_rect_img(self._boxes[i])
            if i == self._sel:
                h = self._hit_handle(mx, my, x1, y1, x2, y2, tol)
                if h:
                    return i, h
        # 再看框体(小框优先,避免大框把小框盖住选不中)
        cands = []
        for i in order:
            x1, y1, x2, y2 = self._box_rect_img(self._boxes[i])
            if x1 - tol <= mx <= x2 + tol and y1 - tol <= my <= y2 + tol:
                cands.append((abs(x2 - x1) * abs(y2 - y1), i))
        if cands:
            cands.sort()
            return cands[0][1], None
        return -1, None

    @staticmethod
    def _hit_handle(mx, my, x1, y1, x2, y2, tol):
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        pts = {"tl": (x1, y1), "t": (cx, y1), "tr": (x2, y1), "r": (x2, cy),
               "br": (x2, y2), "b": (cx, y2), "bl": (x1, y2), "l": (x1, cy)}
        for name, (px, py) in pts.items():
            if abs(mx - px) <= tol and abs(my - py) <= tol:
                return name
        return None

    _CURSORS = {"tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor,
                "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
                "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
                "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor}

    # ---------------- 鼠标交互 ----------------
    def mousePressEvent(self, e):
        if self._pm is None:
            return
        # 放大之后要能挪:中键拖动平移(左键还是画框,不能占用)
        if e.button() == Qt.MiddleButton:
            self._mode = "pan"
            self._pan_from = e.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() != Qt.LeftButton:
            return
        i, h = self._hit(e.position())
        mx, my = self._to_img(e.position())
        if i >= 0:
            if self._sel != i:
                self._sel = i
                self.selection_changed.emit(i)
            # 先拍个快照,松手时若真的动过才记进撤销栈。
            # 不能在这里直接 push —— 只是点一下选中的话什么都没改。
            self._snap = [dict(b) for b in self._boxes]
            self._orig = dict(self._boxes[i])
            self._drag_from = (mx, my)
            self._mode = "resize" if h else "move"
            self._handle = h
        else:
            # 空白处按下 = 拉一个新框。
            # 上一个框还等着确认就先把它落下 —— 连着画几个框时不必每个都按回车,
            # 否则画第二个的时候第一个就悄悄丢了。
            if self._pending:
                self.confirm_pending()
            self._sel = -1
            self.selection_changed.emit(-1)
            self._mode = "new"
            self._snap = [dict(b) for b in self._boxes]
            self._drag_from = (mx, my)
            self._new_rect = (mx, my, mx, my)
        self.update()

    def mouseMoveEvent(self, e):
        if self._pm is None:
            return
        # 记住鼠标位置,画十字辅助线用。拖框时也要更新,
        # 这样拉框的同时也能看准对齐位置。
        self._cross = e.position()
        if self._mode == "pan":
            # 中键拖动:跟手挪图
            d = e.position() - self._pan_from
            self._pan = (self._pan[0] + d.x(), self._pan[1] + d.y())
            self._pan_from = e.position()
            self._clamp_pan()
            self.update()
            return
        self.update()
        if self._mode is None:
            # 只是悬停:更新鼠标形状,让用户知道能拖
            i, h = self._hit(e.position())
            if h:
                self.setCursor(self._CURSORS.get(h, Qt.ArrowCursor))
            elif i >= 0:
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.CrossCursor)
            return
        mx, my = self._to_img(e.position())
        if self._mode == "new":
            x0, y0 = self._drag_from
            self._new_rect = (x0, y0, mx, my)
        elif self._mode == "move":
            dx, dy = mx - self._drag_from[0], my - self._drag_from[1]
            iw, ih = self._pm.width(), self._pm.height()
            x1, y1, x2, y2 = self._box_rect_img(self._orig)
            w, h = x2 - x1, y2 - y1
            # 整体平移,并且不许拖出图外
            nx1 = max(0, min(x1 + dx, iw - w))
            ny1 = max(0, min(y1 + dy, ih - h))
            self._set_box_from_img(self._sel, nx1, ny1, nx1 + w, ny1 + h)
        elif self._mode == "resize":
            x1, y1, x2, y2 = self._box_rect_img(self._orig)
            hd = self._handle
            if "l" in hd:
                x1 = mx
            if "r" in hd:
                x2 = mx
            if "t" in hd:
                y1 = my
            if "b" in hd:
                y2 = my
            self._set_box_from_img(self._sel, x1, y1, x2, y2)
        self.update()

    def mouseReleaseEvent(self, e):
        if self._pm is None or self._mode is None:
            return
        if self._mode == "pan":
            self._mode = None
            self.setCursor(Qt.CrossCursor)
            return
        _, _, s = self._fit()
        if self._mode == "new" and self._new_rect:
            x1, y1, x2, y2 = self._new_rect
            # 太小的当成误点,不建框
            if abs(x2 - x1) * s >= MIN_BOX_PX and abs(y2 - y1) * s >= MIN_BOX_PX:
                # 松手不直接落框,先变成"待确认" —— 按回车才真正建框。
                # 好处是画歪了可以直接按 Esc 取消,不用建完再撤销。
                self._pending = (x1, y1, x2, y2)
                self._pending_snap = self._snap
                self.pending_changed.emit(True)
            self._new_rect = None
        elif self._mode in ("move", "resize"):
            b = self._boxes[self._sel] if 0 <= self._sel < len(self._boxes) else None
            if b and (b["w"] * self._pm.width() * s < MIN_BOX_PX or
                      b["h"] * self._pm.height() * s < MIN_BOX_PX):
                # 缩得太小 = 用户其实想删,但别擅自删,还原就好。
                # 注意:直接还原快照,不能走 undo() —— 那会把这次没生效的
                # 操作塞进重做栈,用户没点过重做却发现重做可用了。
                if self._snap is not None:
                    self._boxes = [dict(x) for x in self._snap]
            elif self._commit(self._snap):
                self.changed.emit()
        self._mode = None
        self._handle = None
        self._orig = None
        self._snap = None
        self.update()

    def confirm_pending(self):
        """把待确认的框正式建出来。返回是否真的建了。"""
        if not self._pending or self._pm is None:
            return False
        x1, y1, x2, y2 = self._pending
        iw, ih = self._pm.width(), self._pm.height()
        import core
        self._boxes.append(
            core.pixels_to_box(self._new_cid, x1, y1, x2, y2, iw, ih))
        self._commit(self._pending_snap)
        self._pending = None
        self._pending_snap = None
        # 确认完【不要选中】它:选中状态下方向键的含义是"微调这个框",
        # 那按完回车就没法用上下键翻图了 —— 而"画完直接翻下一张"
        # 恰恰是最常走的路径。想微调就点一下那个框。
        self._sel = -1
        self.pending_changed.emit(False)
        self.selection_changed.emit(-1)
        self.changed.emit()
        self.update()
        return True

    def cancel_pending(self):
        """丢掉待确认的框(画歪了直接按 Esc,不用建完再撤销)。"""
        if not self._pending:
            return False
        self._pending = None
        self._pending_snap = None
        self.pending_changed.emit(False)
        self.update()
        return True

    def has_pending(self):
        return self._pending is not None

    def set_external_shortcuts(self, on=True):
        self._external_shortcuts = bool(on)

    def cancel_or_deselect(self):
        """取消待确认框；没有待确认框时取消当前选择。"""
        if self.cancel_pending():
            return True
        if self._sel >= 0:
            self._sel = -1
            self.selection_changed.emit(-1)
            self.update()
            return True
        return False

    def nudge_selected(self, dx, dy):
        """按图片像素微调选中的框，供可配置快捷键调用。"""
        if self._pm is None or not (0 <= self._sel < len(self._boxes)):
            return False
        self._push_undo()
        x1, y1, x2, y2 = self._box_rect_img(self._boxes[self._sel])
        self._set_box_from_img(self._sel, x1 + dx, y1 + dy, x2 + dx, y2 + dy)
        self.update()
        self.changed.emit()
        return True

    def keyPressEvent(self, e):
        if self._external_shortcuts:
            # 主程序中的按键由 QShortcut 统一分发。这里继续处理会导致一次按键
            # 执行两遍，而且用户改掉快捷键后旧按键仍会残留。
            super().keyPressEvent(e)
            return
        k = e.key()
        # 回车:确认刚画的框。放在最前面 —— 有待确认的框时,
        # 回车的含义只有这一个
        if k in (Qt.Key_Return, Qt.Key_Enter):
            if self.confirm_pending():
                return
            super().keyPressEvent(e)
            return
        if k in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_selected()
        elif k == Qt.Key_Escape:
            self.cancel_or_deselect()
        elif k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down) and \
                0 <= self._sel < len(self._boxes):
            # 选中了框:方向键微调 1px(按住 Shift 走 10px),比鼠标更精细
            step = 10 if e.modifiers() & Qt.ShiftModifier else 1
            dx = (-step if k == Qt.Key_Left else step if k == Qt.Key_Right else 0)
            dy = (-step if k == Qt.Key_Up else step if k == Qt.Key_Down else 0)
            self.nudge_selected(dx, dy)
        elif k in (Qt.Key_Up, Qt.Key_Down):
            # 没选框:上下键翻图。方向键在这两种情况下含义不同 ——
            # 选中框时是微调(精细活离不开它),没选时才是翻页。
            # 想翻页又不想取消选中,用 A/D 或 PgUp/PgDn。
            self.step_image.emit(-1 if k == Qt.Key_Up else 1)
        else:
            super().keyPressEvent(e)

    # ---------------- 绘制 ----------------
    # 下限 0.5:比整张更小,方便看清框在整图里的相对位置
    ZOOM_MIN, ZOOM_MAX = 0.5, 12.0

    def wheelEvent(self, e):
        """滚轮缩放。关键是"光标底下那个点不能动" —— 否则放大几次就找不到
        刚才在看的地方了。

        做法:记下光标对应的图片坐标,改完缩放系数后调整平移量,
        让同一个图片坐标仍然落在光标下面。
        """
        if self._pm is None:
            return
        dy = e.angleDelta().y()
        if not dy:
            return
        pos = e.position()
        # 缩放前:光标底下是图片上的哪个点
        bx, by = self._to_img(pos)
        step = 1.15 if dy > 0 else 1 / 1.15
        z = max(self.ZOOM_MIN, min(self.ZOOM_MAX, self._zoom * step))
        # 反复乘 1.15 再除回来会留下 1.0000000000000002 这种尾巴。
        # 贴近这几个关键刻度就吸附过去 —— 否则"缩回 1 倍"永远差一点,
        # 平移量也归不了位;1.0 是"整张刚好放下",最值得吸附。
        for anchor in (self.ZOOM_MIN, 1.0, self.ZOOM_MAX):
            if abs(z - anchor) < 0.02:
                z = anchor
                break
        if abs(z - self._zoom) < 1e-9:
            return
        self._zoom = z
        # 缩放后:让那个点重新回到光标位置
        ox, oy, s = self._fit()
        sx, sy = ox + bx * s, oy + by * s
        self._pan = (self._pan[0] + pos.x() - sx,
                     self._pan[1] + pos.y() - sy)
        self._clamp_pan()       # 1 倍及以下会在这里归位,免得图偏在一边
        self._cross = pos
        self.update()
        self.zoom_changed.emit(self._zoom)
        e.accept()

    def _clamp_pan(self):
        """限制平移范围:别把图拖出视野外面找不回来。"""
        if self._pm is None:
            return
        if self._zoom <= 1.0 + 1e-6:
            # 1 倍及以下:整张图本来就看得见,平移没有意义,居中就好
            self._pan = (0.0, 0.0)
            return
        ox, oy, s = self._fit()
        iw, ih = self._pm.width() * s, self._pm.height() * s
        dx = dy = 0.0
        # 图比控件大时,至少要盖住控件;图比控件小时,不许移出控件
        if iw >= self.width():
            if ox > 0:
                dx = -ox
            elif ox + iw < self.width():
                dx = self.width() - (ox + iw)
        if ih >= self.height():
            if oy > 0:
                dy = -oy
            elif oy + ih < self.height():
                dy = self.height() - (oy + ih)
        if dx or dy:
            self._pan = (self._pan[0] + dx, self._pan[1] + dy)

    def reset_zoom(self):
        self._zoom = 1.0
        self._pan = (0.0, 0.0)
        self.update()
        self.zoom_changed.emit(self._zoom)

    def zoom(self):
        return self._zoom

    def leaveEvent(self, e):
        # 鼠标移出画布就擦掉十字线,否则会留一条线在那里
        self._cross = None
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#141518"))
        if self._pm is None:
            p.setPen(QColor(124, 126, 132))
            p.drawText(self.rect(), Qt.AlignCenter, "选一张图开始修改框")
            p.end()
            return
        ox, oy, s = self._fit()
        p.drawPixmap(QRectF(ox, oy, self._pm.width() * s,
                            self._pm.height() * s), self._pm,
                     QRectF(self._pm.rect()))
        f = QFont()
        f.setPointSize(9)
        f.setBold(True)
        p.setFont(f)
        for i, b in enumerate(self._boxes):
            x1, y1, x2, y2 = self._box_rect_img(b)
            sx1, sy1 = self._to_screen(x1, y1)
            sx2, sy2 = self._to_screen(x2, y2)
            col = self._color(b["cid"])
            sel = (i == self._sel)
            p.setPen(QPen(col, 3 if sel else 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(sx1, sy1, sx2 - sx1, sy2 - sy1))
            # 选中的框加一层半透明填充,一眼看出选了哪个
            if sel:
                fill = QColor(col)
                fill.setAlpha(48)
                p.setBrush(QBrush(fill))
                p.setPen(Qt.NoPen)
                p.drawRect(QRectF(sx1, sy1, sx2 - sx1, sy2 - sy1))
            # 类别标签
            txt = self._label(b["cid"])
            fm = p.fontMetrics()
            tw, th = fm.horizontalAdvance(txt) + 8, fm.height() + 2
            ty = sy1 - th if sy1 - th > oy else sy1
            p.setBrush(QBrush(col))
            p.setPen(Qt.NoPen)
            p.drawRect(QRectF(sx1, ty, tw, th))
            p.setPen(QColor(255, 255, 255))
            p.drawText(QRectF(sx1 + 4, ty, tw, th), Qt.AlignVCenter, txt)
            if sel:
                self._draw_handles(p, sx1, sy1, sx2, sy2, col)
        # 十字辅助虚线:方便把框对齐到物体边缘。
        # 画在最上层,但用半透明,不至于盖住画面细节。
        if self._cross is not None:
            cx, cy = self._cross.x(), self._cross.y()
            iw, ih = self._pm.width() * s, self._pm.height() * s
            # 只在图片范围内画,画到边框外面没有意义
            if ox <= cx <= ox + iw and oy <= cy <= oy + ih:
                pen = QPen(QColor(255, 255, 255, 150), 1, Qt.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawLine(QPointF(ox, cy), QPointF(ox + iw, cy))
                p.drawLine(QPointF(cx, oy), QPointF(cx, oy + ih))

        # 正在拉的新框:虚线
        if self._mode == "new" and self._new_rect:
            x1, y1, x2, y2 = self._new_rect
            sx1, sy1 = self._to_screen(x1, y1)
            sx2, sy2 = self._to_screen(x2, y2)
            pen = QPen(QColor(255, 255, 255), 2, Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(sx1, sy1, sx2 - sx1, sy2 - sy1))

        # 画好待确认的框:用即将成为的类别色 + 一行提示,
        # 和已建好的框区分开,不然分不清哪个还没落定
        if self._pending:
            x1, y1, x2, y2 = self._pending
            sx1, sy1 = self._to_screen(x1, y1)
            sx2, sy2 = self._to_screen(x2, y2)
            col = self._color(self._new_cid)
            fill = QColor(col)
            fill.setAlpha(40)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(fill))
            p.drawRect(QRectF(sx1, sy1, sx2 - sx1, sy2 - sy1))
            p.setPen(QPen(col, 2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(sx1, sy1, sx2 - sx1, sy2 - sy1))
            tip = f"{self._label(self._new_cid)} · 回车确定 / Esc 取消"
            fm = p.fontMetrics()
            tw, th = fm.horizontalAdvance(tip) + 10, fm.height() + 4
            ty = sy1 - th if sy1 - th > oy else sy2
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(col))
            p.drawRect(QRectF(sx1, ty, tw, th))
            p.setPen(QColor(255, 255, 255))
            p.drawText(QRectF(sx1 + 5, ty, tw, th), Qt.AlignVCenter, tip)
        p.end()

    @staticmethod
    def _draw_handles(p, x1, y1, x2, y2, col):
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        pts = [(x1, y1), (cx, y1), (x2, y1), (x2, cy),
               (x2, y2), (cx, y2), (x1, y2), (x1, cy)]
        p.setBrush(QBrush(QColor(255, 255, 255)))
        p.setPen(QPen(col, 2))
        for px, py in pts:
            p.drawRect(QRectF(px - 4, py - 4, 8, 8))
