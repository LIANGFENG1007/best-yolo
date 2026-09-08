#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Best yolo —— 图形界面入口。

    python gui/app.py

三个页面:
  首页    配图片/类别/模型 -> 预览 N 张或标全部 -> 实时日志
  标注    看 AI 标的框,可拖动/缩放/新建/删除,保存后直接写回 YOLO 标签
  数据集  切 train/val + data.yaml
"""
import os
import re
import sys
import threading

# 让 import core/theme/widgets/runner 生效(不管从哪个目录启动)
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from PySide6.QtCore import Qt, QTimer, QUrl, Signal, QSize
from PySide6.QtGui import (QDesktopServices, QTextCursor, QFont, QShortcut,
                           QKeySequence, QColor, QImage, QPixmap, QIcon)
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QLabel, QPushButton, QLineEdit,
                               QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit,
                               QTextBrowser, QDialog,
                               QTableWidget, QTableWidgetItem, QHeaderView,
                               QStackedWidget, QButtonGroup, QCheckBox, QSplitter,
                               QProgressBar, QMessageBox, QListWidget, QFrame,
                               QAbstractItemView, QSizePolicy, QGridLayout,
                               QListWidgetItem, QCheckBox, QInputDialog,
                               QFileDialog)

import core
from appmeta import APP_VERSION
from theme import stylesheet, apply_palette, C
from widgets import (Card, PathPicker, FieldRow, ImageView, color_dot,
                     ThumbStrip, ImageDialog,
                     app_icon, scroll_area, no_wheel, KeyField,
                     SearchableCombo, FlowLayout)
import video as vid
import promptai
import shortcut_settings as hotkeys
import update_check
from rangebar import RangeBar, VideoView

# 一次最多抽这么多张。间隔手滑填成 0.02 秒能抽出几万张,
# 磁盘和后面的标注量都受不了,必须有个硬上限。
MAX_FRAMES = 3000
from boxedit import BoxCanvas
from runner import ScriptRunner

PALETTE = None      # 延迟从 autolabel_qwen 读,保证颜色和画框完全一致

# AI 补充提示词页默认用的模型:看图能力够、价格适中
PAI_DEFAULT_MODEL = "qwen3-vl-plus"
API_ONLY_INSTALL = os.environ.get("BEST_YOLO_API_ONLY", "").strip().lower() \
    in ("1", "true", "yes")


def palette():
    global PALETTE
    if PALETTE is None:
        try:
            sys.path.insert(0, core.ROOT)
            from palette import PALETTE as P
            PALETTE = P
        except Exception:
            PALETTE = [(74, 158, 255)]
    return PALETTE


class MainWindow(QMainWindow):
    # 后台线程拉完模型后用它把结果送回主线程。
    # 【不能用 QTimer.singleShot】—— 它会在调用它的那个线程上建 timer,
    # 而工作线程没有事件循环,回调永远不会执行(界面就一直卡在"获取中…")。
    # 信号槽跨线程时 Qt 会自动排队到接收者所在线程,这才是正确做法。
    models_ready = Signal(list, str)
    update_ready = Signal(int, dict, str, bool)
    update_page_ready = Signal(int, bool, str)
    # 页码。侧栏顺序 = 页面顺序,改顺序只改这里和上面的 addWidget
    PAGE_HOME, PAGE_MARK, PAGE_PROMPT, PAGE_DATASET, PAGE_VIDEO = range(5)

    # AI 补充提示词:后台线程 -> 界面(Qt 规定只能在主线程改控件)
    pai_progress = Signal(int, int)
    pai_done = Signal(dict, str)
    pai_thumb = Signal(int, int, str)   # (代号, 行号, 缩略图路径)

    def __init__(self):
        super().__init__()
        # 任何操作都必须先有项目。None = 还没选,界面处于"只能新建/选项目"状态。
        core.purge_trash()           # 清掉上次没删干净的残骸
        self._proj = core.load_state().get("project") or None
        if self._proj and not os.path.isfile(core.project_config_path(self._proj)):
            self._proj = None        # 项目被删了就当没选
        if self._proj is None:
            # 只剩一个项目时直接进去,省一次点击;多个就让用户自己选
            ps = core.list_projects()
            if len(ps) == 1:
                self._proj = ps[0]["name"]
        self.cfg = self._load_cfg()
        self._dirty = False           # 当前图片的框有未保存的修改
        self._cur_row = 0             # 当前看的是第几张
        self._cur_label = ""          # 当前图对应的标签文件
        # 待保存的改动:{标签文件路径: 框列表}。
        # 切换图片时把当前改动挪进来,「全部保存」再一次性落盘 ——
        # 这样翻看多张、改多张之后不用逐张点保存。
        self._pending = {}
        # 界面缩放:默认 1.0 = 原始比例。上次手动调过就沿用那个
        try:
            _z = float(core.load_state().get("zoom") or 1.0)
        except (TypeError, ValueError):
            _z = 1.0
        self._ui_k = _z if 0.5 <= _z <= 2.0 else 1.0
        self._closing = False      # 关窗中:回调要立刻收手,别碰控件
        self._locks = set()        # 上锁的图片名(不参与重跑)
        self._pai_rows = []        # AI 补充提示词页的图片行
        self._pai_stop = False
        self._pai_result = None
        self._pai_neg = ""
        self._pai_thumb_seq = 0    # 缩略图后台任务的代号(换页就作废)
        self._zoom_box = None      # 右上角的缩放控件(第一次建页时创建)
        self._zoom_placed = False
        self._base_pt = 9.5        # 基准字号(main() 里会按系统字体校准)
        self._vis_labels = []      # 列表里每张图对应的标签文件
        self._vis_counts = []      # 磁盘上的框数(-1=没标签文件)
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._autosave_tick)
        self._fetching = False        # 是否正在联网拉模型列表
        self._fetch_seq = 0           # 请求序号,用来忽略过期的响应
        self._update_checking = False
        self._update_check_seq = 0
        self._update_handled_seq = 0
        self._update_manual_wait = False
        self._latest_release = {}
        self._update_link_seq = 0
        self._update_link_checking = False
        self._update_dialog = None
        self._update_go_button = None
        self.models_ready.connect(self._on_models)
        self.update_ready.connect(self._on_update_ready)
        self.update_page_ready.connect(self._on_update_page_ready)
        self.pai_progress.connect(self._on_pai_progress)
        self.pai_done.connect(self._on_pai_done)
        self.pai_thumb.connect(self._on_pai_thumb)
        self.runner = ScriptRunner(self)
        self.runner.line.connect(self.on_log)
        self.runner.progress.connect(self.on_progress)
        self.runner.finished.connect(self.on_finished)
        self._task = None          # "preview" / "all" / "dataset"

        self.setWindowTitle("Best yolo")
        self.setWindowIcon(app_icon())
        # 最小尺寸必须 >= 内容真正需要的宽度,否则各栏会互相挤压重合。
        # 三栏最小 150+300+200 + 分隔条 + 侧栏 184 + 边距 ≈ 900
        # 高度下限 700:视频切片页要求一屏放完(不许滚轮),右侧三张设置卡
        # 加起来约 470px,再要给缩略图留出能看的地方,600 高是塞不下的。
        self.setMinimumSize(900, 700)
        self.resize(*self._startup_size())

        root = QWidget()
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_sidebar())

        # 页码用常量,不要在代码里散落 0/1/2/3 —— 调顺序时最容易漏改
        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_label_page())      # PAGE_HOME
        self.pages.addWidget(self._build_result_page())     # PAGE_MARK
        self.pages.addWidget(self._build_promptai_page())   # PAGE_PROMPT
        self.pages.addWidget(self._build_dataset_page())    # PAGE_DATASET
        self.pages.addWidget(self._build_video_page())      # PAGE_VIDEO
        lay.addWidget(self.pages, 1)

        # 统一给所有下拉框/数字框装上"忽略滚轮"。
        # 放在建完界面之后一次性扫,比每个控件手写一遍可靠 —— 以后新加控件也自动覆盖。
        self._disable_wheel_on_inputs()
        self._setup_shortcuts()

        self.status = self.statusBar()
        self.status.setObjectName("StatusBar")
        self.status.showMessage("就绪")

        self._refresh_projects()
        self._load_to_ui()
        self._refresh_img_count()
        if os.environ.get("BEST_YOLO_DISABLE_UPDATE_CHECK", "").strip().lower() \
                not in ("1", "true", "yes"):
            QTimer.singleShot(350, lambda: self._check_updates(manual=False))

    # ---------------- 侧边栏 ----------------
    def _build_sidebar(self):
        bar = QWidget()
        bar.setObjectName("Sidebar")
        bar.setFixedWidth(184)
        self.side = bar        # 缩放时要改它的宽度
        lay = QVBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 12)
        lay.setSpacing(0)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(18, 16, 10, 0)
        brand_row.setSpacing(6)
        brand = QLabel("Best yolo")
        brand.setObjectName("Brand")
        self.btn_update = QPushButton("检测更新")
        self.btn_update.setObjectName("UpdateCheckBtn")
        self.btn_update.setToolTip(f"检测 Best yolo 新版本（当前 v{APP_VERSION}）")
        self.btn_update.setCursor(Qt.PointingHandCursor)
        self.btn_update.clicked.connect(self._on_update_button)
        brand_row.addWidget(brand, 1)
        brand_row.addWidget(self.btn_update, 0, Qt.AlignRight | Qt.AlignVCenter)
        sub = QLabel("图片 → YOLO 数据集")
        sub.setObjectName("BrandSub")
        lay.addLayout(brand_row)
        lay.addWidget(sub)

        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        for i, (txt, tip) in enumerate([
                ("首页", "配置并运行自动标注"),
                ("标注", "查看并手动拖动修改 AI 标出的框"),
                ("AI 补充提示词", "让大模型对比你的修订,反推提示词该怎么写"),
                ("导出数据集", "切分 train/val 并生成 data.yaml"),
                ("视频切片", "把视频按间隔抽成图片,用来做标注素材")]):
            b = QPushButton(txt)
            b.setObjectName("NavBtn")
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _, k=i: self._go(k))
            self.nav.addButton(b, i)
            lay.addWidget(b)
        self.nav.button(0).setChecked(True)

        lay.addStretch(1)
        for txt, fn in [("打开输出目录", lambda: self._open(self.cfg["out"])),
                        ("打开预览图目录", lambda: self._open(
                            os.path.join(self.cfg["out"], "vis")))]:
            b = QPushButton(txt)
            b.setObjectName("LinkBtn")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(fn)
            lay.addWidget(b)
        return bar

    # ---------------- 更新检查 ----------------
    def _set_update_button(self, available=False, checking=False):
        if checking:
            text, name = "检测中…", "UpdateCheckBtn"
            tip = "正在连接 GitHub 检测新版本"
        elif available:
            text, name = "发现更新", "UpdateAvailableBtn"
            version = self._latest_release.get("version") or "新版本"
            tip = f"发现 Best yolo v{version}，点击查看更新内容"
        else:
            text, name = "检测更新", "UpdateCheckBtn"
            tip = f"检测 Best yolo 新版本（当前 v{APP_VERSION}）"
        if hasattr(self, "_shortcut_bindings"):
            tip += f"\n快捷键：{self._shortcut_text('global.check_updates')}"
        self.btn_update.setText(text)
        self.btn_update.setObjectName(name)
        self.btn_update.setToolTip(tip)
        try:
            style = self.btn_update.style()
            style.unpolish(self.btn_update)
            style.polish(self.btn_update)
            self.btn_update.update()
        except Exception:
            pass

    def _check_updates(self, manual=False):
        """后台检测 GitHub latest release；自动检查失败时完全静默。"""
        if self._update_checking:
            self._update_manual_wait = self._update_manual_wait or bool(manual)
            if manual:
                self._set_update_button(checking=True)
            return
        self._update_checking = True
        self._update_check_seq += 1
        seq = self._update_check_seq
        if manual:
            self._set_update_button(checking=True)

        QTimer.singleShot(7000, lambda s=seq: self._update_check_timeout(s))

        def work():
            release, error = update_check.check_for_update(APP_VERSION, timeout=5.0)
            try:
                self.update_ready.emit(seq, release, error, bool(manual))
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _update_check_timeout(self, seq):
        if (self._closing or seq != self._update_check_seq or
                seq <= self._update_handled_seq):
            return
        self._on_update_ready(seq, {}, update_check.NO_NETWORK_MESSAGE, False)

    def _on_update_ready(self, seq, release, error, manual=False):
        if (self._closing or seq != self._update_check_seq or
                seq <= self._update_handled_seq):
            return
        self._update_handled_seq = seq
        self._update_checking = False
        show_feedback = bool(manual or self._update_manual_wait)
        self._update_manual_wait = False
        if error:
            self._set_update_button(False)
            if show_feedback:
                QMessageBox.information(self, "没有网络", update_check.NO_NETWORK_MESSAGE)
            return
        self._latest_release = dict(release or {})
        available = bool(self._latest_release.get("update_available"))
        self._set_update_button(available)
        if available and show_feedback:
            self._show_update_dialog()
        elif show_feedback:
            version = self._latest_release.get("version") or APP_VERSION
            QMessageBox.information(
                self, "已经是最新版",
                f"当前版本是 v{APP_VERSION}，GitHub 最新稳定版是 v{version}。")

    def _on_update_button(self):
        if self._latest_release.get("update_available"):
            self._show_update_dialog()
        else:
            self._check_updates(manual=True)

    def _show_update_dialog(self):
        release = self._latest_release
        if not release.get("update_available"):
            self._check_updates(manual=True)
            return
        dlg = QDialog(self)
        dlg.setObjectName("UpdateDialog")
        dlg.setWindowTitle(f"发现 Best yolo v{release.get('version', '')}")
        dlg.resize(700, 540)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        title = QLabel(f"发现新版本 v{release.get('version', '')}")
        title.setObjectName("UpdateDialogTitle")
        layout.addWidget(title)
        current = QLabel(f"当前版本 v{APP_VERSION} · 以下是新版本更新内容")
        current.setObjectName("UpdateDialogVersion")
        layout.addWidget(current)

        notes = QTextBrowser()
        notes.setObjectName("UpdateNotes")
        notes.setOpenExternalLinks(False)
        notes.setMarkdown(release.get("body") or "## 更新内容\n\n这个版本没有提供更新说明。")
        layout.addWidget(notes, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        later = QPushButton("稍后")
        later.clicked.connect(dlg.reject)
        go = QPushButton("前往 GitHub 发布页")
        go.setObjectName("Primary")
        go.clicked.connect(
            lambda: self._probe_and_open_release(dlg, go, release.get("url", "")))
        buttons.addWidget(later)
        buttons.addWidget(go)
        layout.addLayout(buttons)

        self._update_dialog = dlg
        self._update_go_button = go
        dlg.exec()
        self._update_link_seq += 1       # 关闭弹窗后作废仍在路上的网络结果
        self._update_link_checking = False
        self._update_dialog = None
        self._update_go_button = None

    def _probe_and_open_release(self, dlg, button, url):
        if self._update_link_checking:
            return
        self._update_link_checking = True
        self._update_link_seq += 1
        seq = self._update_link_seq
        button.setEnabled(False)
        button.setText("正在连接…")

        def work():
            ok, error = update_check.probe_release_page(url, timeout=5.0)
            try:
                self.update_page_ready.emit(seq, ok, error)
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _on_update_page_ready(self, seq, ok, error):
        if self._closing or seq != self._update_link_seq:
            return
        self._update_link_checking = False
        button = self._update_go_button
        dlg = self._update_dialog
        if button is not None:
            button.setEnabled(True)
            button.setText("前往 GitHub 发布页")
        if not ok:
            QMessageBox.information(
                dlg or self, "没有网络", error or update_check.NO_NETWORK_MESSAGE)
            return
        url = self._latest_release.get("url") or ""
        opened = bool(url) and QDesktopServices.openUrl(QUrl(url))
        if not opened:
            QMessageBox.information(
                dlg or self, "没有网络", update_check.NO_NETWORK_MESSAGE)
            return
        if dlg is not None:
            dlg.accept()

    def _go(self, idx):
        self.pages.setCurrentIndex(idx)
        self.nav.button(idx).setChecked(True)
        if idx == self.PAGE_PROMPT:
            self._pai_reload()     # 进 AI 补充提示词页就刷新图片和基线状态
        # 离开视频页就停掉播放:定时器继续解码看不见的画面纯属白耗 CPU,
        # 而且和关窗销毁控件叠在一起时容易踩到段错误
        if idx != self.PAGE_VIDEO:
            self._stop_vid_play()
        # 缩放控件是同一份,跟着切到当前页的标题行右边
        pg = self.pages.widget(idx)
        slot = getattr(pg, "_zoom_slot", None)
        if slot is not None and getattr(self, "_zoom_box", None) is not None:
            slot.addWidget(self._zoom_box, 0, Qt.AlignRight | Qt.AlignVCenter)
        if idx == 1:
            self.refresh_results()

    # ---------------- 页面骨架(占位,下面分块补) ----------------
    def _page_shell(self, title, subtitle):
        page = QWidget()
        page.setAutoFillBackground(True)   # 用调色板的窗口底色填充
        lay = QVBoxLayout(page)
        lay.setContentsMargins(26, 22, 26, 18)
        lay.setSpacing(14)
        t = QLabel(title)
        t.setObjectName("PageTitle")
        s = QLabel(subtitle)
        s.setObjectName("PageSub")
        # 标题行右边放缩放按钮。只在第一次调用时建控件,之后的页面复用
        # 同一组按钮(缩放是全局的,每页放一份没意义)。
        trow = QHBoxLayout()
        trow.setContentsMargins(0, 0, 0, 0)
        trow.addWidget(t, 1)
        if getattr(self, "_zoom_box", None) is None:
            self.btn_shortcuts = QPushButton("快捷键")
            self.btn_shortcuts.setObjectName("ShortcutSettingsBtn")
            self.btn_shortcuts.setToolTip("打开快捷键设置")
            self.btn_shortcuts.setCursor(Qt.PointingHandCursor)
            self.btn_shortcuts.clicked.connect(self._show_shortcut_settings)
            self.btn_zoom_out = QPushButton("−")
            self.btn_zoom_out.setObjectName("ZoomBtn")
            self.btn_zoom_out.setToolTip("界面缩小一档(Ctrl+-)")
            self.btn_zoom_out.setCursor(Qt.PointingHandCursor)
            self.btn_zoom_out.clicked.connect(lambda: self._zoom(-1))
            self.lb_zoom = QLabel("100%")
            self.lb_zoom.setObjectName("ZoomLabel")
            self.lb_zoom.setAlignment(Qt.AlignCenter)
            self.lb_zoom.setToolTip("当前界面缩放。双击回到 100%")
            self.btn_zoom_in = QPushButton("+")
            self.btn_zoom_in.setObjectName("ZoomBtn")
            self.btn_zoom_in.setToolTip("界面放大一档(Ctrl++)")
            self.btn_zoom_in.setCursor(Qt.PointingHandCursor)
            self.btn_zoom_in.clicked.connect(lambda: self._zoom(1))
            self._zoom_box = QWidget()
            zl = QHBoxLayout(self._zoom_box)
            zl.setContentsMargins(0, 0, 0, 0)
            zl.setSpacing(4)
            zl.addWidget(self.btn_shortcuts)
            zl.addSpacing(4)
            zl.addWidget(self.btn_zoom_out)
            zl.addWidget(self.lb_zoom)
            zl.addWidget(self.btn_zoom_in)
        # 同一个控件不能同时放进两个布局,所以只挂在第一个页面的标题行上,
        # 其余页面靠切页时把它移过去(_go 里做)。
        if not getattr(self, "_zoom_placed", False):
            trow.addWidget(self._zoom_box, 0, Qt.AlignRight | Qt.AlignVCenter)
            self._zoom_placed = True
        lay.addLayout(trow)
        lay.addWidget(s)
        page._zoom_slot = trow          # 切页时把缩放控件移到当前页
        return page, lay

    # ================= 页面1:首页 =================
    def _build_label_page(self):
        page, lay = self._page_shell(
            "首页", "配好类别和描述,先跑预览确认框对不对,再标全部")

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        # ---- 左:配置 ----
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(12)

        # ---- 项目:一套配置一个项目,互不干扰 ----
        c0 = Card("项目", "每个项目有自己的图片目录、类别表和输出目录。切换项目会自动保存当前项目。")
        prow = QHBoxLayout()
        prow.setSpacing(7)
        self.cb_proj = QComboBox()
        self.cb_proj.setMinimumWidth(190)
        self.cb_proj.setToolTip("切到别的项目;上面的配置会跟着换")
        self.cb_proj.currentIndexChanged.connect(self._on_proj_switch)
        b_new = QPushButton("新建项目")
        b_new.setObjectName("Primary")
        b_new.clicked.connect(self._new_project)
        b_ren = QPushButton("重命名")
        b_ren.clicked.connect(self._rename_project)
        b_del = QPushButton("删除项目")
        b_del.setObjectName("Danger")
        b_del.clicked.connect(self._del_project)
        prow.addWidget(self.cb_proj, 1)
        prow.addWidget(b_new)
        prow.addWidget(b_ren)
        prow.addWidget(b_del)
        c0.body.addLayout(prow)
        self.lb_proj = QLabel("")
        self.lb_proj.setObjectName("Hint")
        self.lb_proj.setWordWrap(True)
        c0.body.addWidget(self.lb_proj)
        ll.addWidget(c0)

        c1 = Card("图片与输出")
        self.p_images = PathPicker("待标注图片文件夹")
        self.p_images.changed.connect(lambda _: self._refresh_img_count())
        self.p_out = PathPicker("标签和预览图的输出目录", status=False)
        c1.body.addWidget(FieldRow("图片文件夹", self.p_images))
        c1.body.addWidget(FieldRow("输出目录", self.p_out,
                                   hint="默认即可,无需更改"))
        self.cb_backup = QCheckBox("开跑前把上次的结果改名备份(避免新旧标签混在一起)")
        self.cb_backup.setChecked(True)
        c1.body.addWidget(FieldRow("", self.cb_backup))
        ll.addWidget(c1)

        c2 = Card("类别表", "勾选=本次要检测。取消勾选的类仍占用类别 id,不会影响已有标签的 id。",
                  grow=True)
        self.tbl = QTableWidget(0, 4)
        self.tbl.setHorizontalHeaderLabels(
            ["检测", "类别名", "描述(给模型看,越具体越准)", "删除"])
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.Fixed)
        self.tbl.setColumnWidth(0, 48)
        self.tbl.setColumnWidth(1, 108)     # 留够宽度,编辑时中文类别名不至于挤成一团
        self.tbl.setColumnWidth(3, 58)      # 每行右边的「删除」
        # 32px:要同时装得下 24px 高的单元格编辑框和 22px 的删除按钮,
        # 行太矮会把编辑时的汉字上下裁掉
        self.tbl.verticalHeader().setDefaultSectionSize(32)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        # 16 类时这张表是主角,给它最多的空间,并让它随窗口一起长高
        self.tbl.setMinimumHeight(260)
        self.tbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        c2.body.addWidget(self.tbl, 1)

        row = QHBoxLayout()
        row.setSpacing(7)
        # 注意:clicked 会带一个 bool 参数,必须用 lambda 挡掉,
        # 否则 _add_class_row 会把 False 当成类别名建出一行 "False"
        self._cls_btns = []
        # 删除不在这里了 —— 每行右边有个红叉,点哪行删哪行,比"先选再删"直接
        for txt, fn in [("全选", lambda: self._check_all(True)),
                        ("全不选", lambda: self._check_all(False)),
                        ("加一行", lambda: self._add_class_row()),
                        ("导入 classes", lambda: self._import_classes())]:
            b = QPushButton(txt)
            b.clicked.connect(fn)
            row.addWidget(b)
            self._cls_btns.append(b)
        row.addStretch(1)
        self.lb_cls_stat = QLabel("")
        self.lb_cls_stat.setObjectName("Hint")
        row.addWidget(self.lb_cls_stat)
        c2.body.addLayout(row)
        ll.addWidget(c2, 1)

        c3 = Card("不要标注的东西",
                  "画面里存在但不属于任何类别的干扰物。写进来能明显减少误标,比反复改描述有效。")
        self.ed_neg = QPlainTextEdit()
        self.ed_neg.setPlaceholderText("用顿号分隔,如:香蕉、瓶装茶饮料、桌布、鞋子")
        self.ed_neg.setFixedHeight(58)
        c3.body.addWidget(self.ed_neg)
        ll.addWidget(c3, 0)

        c4 = Card("模型与性能")
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(9)
        self.cb_backend = QComboBox()
        self.cb_backend.addItem("云端 API(不占本机显卡)", "api")
        if not API_ONLY_INSTALL:
            self.cb_backend.addItem("本地 GPU(离线免费,需 NVIDIA 显卡)", "local")
        self.cb_backend.currentIndexChanged.connect(self._on_backend_change)
        self.cb_model = SearchableCombo()
        self.btn_fetch = QPushButton("获取可用模型")
        self.btn_fetch.setCursor(Qt.PointingHandCursor)
        self.btn_fetch.setToolTip("联网向接入点查询这个 Key 能用哪些模型")
        self.btn_fetch.clicked.connect(self.fetch_models)
        self.lb_fetch = QLabel("")
        self.lb_fetch.setObjectName("Hint")
        self.lb_fetch.setWordWrap(True)
        self.key_field = KeyField()
        self.key_field.changed.connect(self._on_key_changed)
        self.sp_workers = QSpinBox()
        self.sp_workers.setRange(1, 200)
        self.sp_workers.setToolTip(
            "并发请求数。视觉模型的配额通常很小,给太大会被限流(429)。\n"
            "报限流就调小,或把下面的限速填成 2")
        self.sp_qps = QSpinBox()
        self.sp_qps.setRange(0, 100)
        self.sp_qps.setSpecialValueText("自动")
        self.sp_qps.setSuffix(" 次/秒")
        self.sp_qps.setToolTip(
            "每秒最多发几个请求。0=按并发数自动估算。\n"
            "老是被限流就填小一点(比如 2),比调并发更管用")
        self.ck_skip = QCheckBox("跳过已标好的图")
        self.ck_skip.setToolTip(
            "重跑时只补没标上的图,不重复调用 API(省钱)。\n"
            "想全部重标就取消勾选")
        self.cb_px = QComboBox()
        for v, t in [(2000000, "200万 · 推荐"), (1003520, "100万 · 省钱"),
                     (4000000, "400万 · 更清楚,更贵")]:
            self.cb_px.addItem(t, v)
        self.sp_limit = QSpinBox()
        self.sp_limit.setRange(1, 9999)
        self.sp_limit.setToolTip("预览只标前 N 张,用来先确认框准不准。\n"
                                 "填 1 就只标 1 张,最省钱")
        self.sp_limit.setSuffix(" 张")
        self.sp_limit.setAccelerated(True)     # 按住上下键可加速
        # 数字框默认没有加减按钮(样式里隐藏了),这里补一对,方便不用键盘也能改
        self.sp_limit.setButtonSymbols(QSpinBox.UpDownArrows)

        def _cell(lbl, w):
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(3)
            t = QLabel(lbl)
            t.setStyleSheet(f"color:{C['text_dim']}; background:transparent;")
            bl.addWidget(t)
            bl.addWidget(w)
            return box

        # 模型行:下拉(可搜索) + 获取按钮
        mrow = QWidget()
        mr = QHBoxLayout(mrow)
        mr.setContentsMargins(0, 0, 0, 0)
        mr.setSpacing(8)
        mr.addWidget(self.cb_model, 1)
        mr.addWidget(self.btn_fetch)

        g.addWidget(_cell("后端", self.cb_backend), 0, 0, 1, 2)
        self.cell_key = _cell("API Key", self.key_field)
        g.addWidget(self.cell_key, 1, 0, 1, 2)
        g.addWidget(_cell("模型", mrow), 2, 0, 1, 2)
        g.addWidget(self.lb_fetch, 3, 0, 1, 2)
        g.addWidget(_cell("并发数", self.sp_workers), 4, 0)
        g.addWidget(_cell("处理分辨率", self.cb_px), 4, 1)
        g.addWidget(_cell("限速", self.sp_qps), 5, 0)
        g.addWidget(_cell("预览张数", self.sp_limit), 5, 1)
        g.addWidget(self.ck_skip, 6, 0, 1, 2)
        c4.body.addLayout(g)

        self.btn_adv = QPushButton("高级选项 ▾")
        self.btn_adv.setObjectName("LinkBtn")
        self.btn_adv.setCursor(Qt.PointingHandCursor)
        self.btn_adv.clicked.connect(self._toggle_adv)
        c4.body.addWidget(self.btn_adv, 0, Qt.AlignLeft)

        self.adv = QWidget()
        av = QVBoxLayout(self.adv)
        av.setContentsMargins(0, 4, 0, 0)
        av.setSpacing(8)
        self.cb_coord = QComboBox()
        self.cb_coord.addItem("自动判定(推荐,几乎不用改)", 0)
        self.cb_coord.addItem("强制像素坐标", -1)
        self.cb_coord.addItem("强制 0~1000 归一化", 1000)
        self.cb_coord.addItem("强制 0~1 比例", 1)
        self.cb_coord.currentIndexChanged.connect(self._warn_coord)
        self.cb_tiles = QComboBox()
        self.cb_tiles.addItem("不切片(默认)", "")
        self.cb_tiles.addItem("2x2(小目标,API 调用×4)", "2x2")
        self.cb_tiles.addItem("3x3(极小目标,API 调用×9)", "3x3")
        self.ed_base = QLineEdit()
        self.ed_base.setPlaceholderText("留空用官方百炼地址")
        # 换了接入点,原来的模型列表就不作数了
        self.ed_base.editingFinished.connect(self._on_base_changed)
        self.lb_coord_warn = QLabel("")
        self.lb_coord_warn.setObjectName("Hint")
        self.lb_coord_warn.setWordWrap(True)
        av.addWidget(FieldRow("坐标口径", self.cb_coord,
                              "别动它。自动判定对绝大多数情况都是对的;"
                              "选错会让所有框挤到角落或整体偏移", label_w=84))
        av.addWidget(self.lb_coord_warn)
        av.addWidget(FieldRow("切片检测", self.cb_tiles,
                              "目标太小、模型漏检时用;会成倍增加费用", label_w=84))
        av.addWidget(FieldRow("接入点", self.ed_base,
                              "改了接入点要重新点「获取可用模型」", label_w=84))
        self.adv.setVisible(False)
        c4.body.addWidget(self.adv)
        ll.addWidget(c4, 0)
        # 没有 addStretch:让类别表吃掉多余空间(它是这一页的主角)。
        # 整列外面套滚动区,窗口再小也能滚到底,不会有控件被切掉。
        split.addWidget(scroll_area(left))

        # ---- 右:运行 + 日志 ----
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(12)

        c5 = Card("运行")
        brow = QHBoxLayout()
        brow.setSpacing(9)
        self.btn_preview = QPushButton("先标 20 张预览")
        self.btn_preview.setObjectName("Primary")
        self.btn_preview.setCursor(Qt.PointingHandCursor)
        self.btn_preview.clicked.connect(lambda: self.run_label(preview=True))
        self.btn_all = QPushButton("标注全部")
        self.btn_all.setCursor(Qt.PointingHandCursor)
        self.btn_all.clicked.connect(lambda: self.run_label(preview=False))
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setObjectName("Danger")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.runner.stop)
        brow.addWidget(self.btn_preview)
        brow.addWidget(self.btn_all)
        brow.addWidget(self.btn_stop)
        brow.addStretch(1)
        c5.body.addLayout(brow)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        c5.body.addWidget(self.bar)
        self.lb_prog = QLabel("尚未运行")
        self.lb_prog.setObjectName("Hint")
        c5.body.addWidget(self.lb_prog)
        rl.addWidget(c5)

        c6 = Card("日志", grow=True)
        self.log = QPlainTextEdit()
        self.log.setObjectName("Log")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(4000)   # 防止长时间跑把内存吃满
        self.log.setLineWrapMode(QPlainTextEdit.NoWrap)
        c6.body.addWidget(self.log, 1)
        lrow = QHBoxLayout()
        b_clr = QPushButton("清空")
        b_clr.clicked.connect(self.log.clear)
        b_cp = QPushButton("复制全部")
        b_cp.clicked.connect(lambda: QApplication.clipboard().setText(
            self.log.toPlainText()))
        lrow.addWidget(b_clr)
        lrow.addWidget(b_cp)
        lrow.addStretch(1)
        c6.body.addLayout(lrow)
        rl.addWidget(c6, 1)

        split.addWidget(right)
        split.setSizes([620, 500])
        lay.addWidget(split, 1)
        return page

    # ================= 页面2:标注(查看 + 人工修改框) =================
    def _build_result_page(self):
        page, lay = self._page_shell(
            "标注", "拖动框改位置,拖角改大小。空白处拖出新框后按回车确定"
                    "(Esc 取消)。滚轮缩放,上下键翻图")

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(9)
        hrow = QHBoxLayout()
        self.lb_vis = QLabel("预览图")
        self.lb_vis.setObjectName("CardTitle")
        b_ref = QPushButton("刷新")
        b_ref.clicked.connect(self.refresh_results)
        hrow.addWidget(self.lb_vis)
        hrow.addStretch(1)
        hrow.addWidget(b_ref)
        ll.addLayout(hrow)
        self.lst_vis = QListWidget()
        self.lst_vis.currentRowChanged.connect(self._show_vis)
        self.lst_vis.setMinimumWidth(150)
        ll.addWidget(self.lst_vis, 1)
        nav = QHBoxLayout()
        self.btn_prev = QPushButton("← 上一张")
        self.btn_prev.setToolTip("A / PgUp / ↑(没选中框时)")
        self.btn_prev.clicked.connect(lambda: self._step_vis(-1))
        self.btn_next = QPushButton("下一张 →")
        self.btn_next.setToolTip("D / PgDn / ↓(没选中框时)")
        self.btn_next.clicked.connect(lambda: self._step_vis(1))
        nav.addWidget(self.btn_prev)
        nav.addWidget(self.btn_next)
        ll.addLayout(nav)
        split.addWidget(left)

        mid = QWidget()
        mid.setMinimumWidth(300)      # 工具条会换行,所以这里可以给得更小
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(8)

        # 编辑工具条。用会换行的布局:窗口缩小时它自己折行,
        # 不会把中间面板的最小宽度顶大、去挤压左右两栏(那就是重合的原因)
        tbw = QWidget()
        tb = FlowLayout(tbw, spacing=7)
        self.cb_newcls = SearchableCombo()
        self.cb_newcls.setToolTip("拉新框时用哪个类别;选中某个框时改这里就是改它的类别")
        self.cb_newcls.setMinimumWidth(140)
        self.cb_newcls.setMaximumWidth(210)
        self.cb_newcls.currentIndexChanged.connect(self._on_newcls)
        self.btn_del = QPushButton("删除框")
        self.btn_del.setObjectName("Danger")
        self.btn_del.setToolTip("删掉选中的框(快捷键 Delete)")
        self.btn_del.clicked.connect(lambda: self.canvas.delete_selected())
        self.btn_undo = QPushButton("撤销")
        self.btn_undo.setToolTip("Ctrl+Z")
        self.btn_undo.clicked.connect(lambda: self.canvas.undo())
        self.btn_clear = QPushButton("本张清空")
        self.btn_clear.setObjectName("Danger")
        self.btn_clear.setToolTip("删掉这张图的所有框(可以 Ctrl+Z 撤销)")
        self.btn_clear.clicked.connect(self._clear_this)
        self.btn_save = QPushButton("全部保存")
        self.btn_save.setObjectName("Primary")
        self.btn_save.setToolTip("Ctrl+S:把所有改过的图片一次性写回 out/labels/*.txt")
        self.btn_save.clicked.connect(self.save_boxes)
        # 自动保存
        self.ck_auto = QCheckBox("自动保存")
        self.ck_auto.setToolTip("每隔一段时间自动把改动写回标签文件")
        self.ck_auto.toggled.connect(self._on_autosave_toggle)
        self.sp_auto = QSpinBox()
        self.sp_auto.setRange(1, 120)
        self.sp_auto.setSuffix(" 分钟")
        self.sp_auto.setToolTip("自动保存的间隔")
        self.sp_auto.setButtonSymbols(QSpinBox.UpDownArrows)
        self.sp_auto.valueChanged.connect(self._on_autosave_interval)
        # 上锁:保护改好的标签不被重跑覆盖。手动改过的会自动上锁,
        # 这里可以手动勾/取消。
        self.ck_lock = QCheckBox("🔒 上锁")
        self.ck_lock.setToolTip(
            "上锁的图在「预览标注」和「标注全部」时都会跳过,\n"
            "预览张数也不算它 —— 改好的框不会被重跑冲掉。\n"
            "你手动改过的图会自动上锁。")
        self.ck_lock.toggled.connect(self._on_lock_toggle)
        # 滚轮缩放的倍数显示 + 复位
        self.lb_zoomlv = QLabel("100%")
        self.lb_zoomlv.setObjectName("Hint")
        self.lb_zoomlv.setToolTip("滚轮缩放倍数。中键拖动可以挪图")
        self.btn_zoomfit = QPushButton("复位")
        self.btn_zoomfit.setToolTip("回到整张刚好放下(快捷键 0)")
        self.lb_zoomlv.setToolTip(
            "滚轮缩放 50%~1200%。中键拖动挪图,按 0 复位")
        # 用 lambda 延迟取 self.canvas —— 画布是在工具条之后才创建的,
        # 这里直接写 self.canvas.reset_zoom 会 AttributeError
        self.btn_zoomfit.clicked.connect(lambda: self.canvas.reset_zoom())
        for wg in (QLabel("类别"), self.cb_newcls, self.btn_del, self.btn_undo,
                   self.btn_clear, self.btn_save, self.ck_auto, self.sp_auto,
                   self.ck_lock, self.lb_zoomlv, self.btn_zoomfit):
            tb.addWidget(wg)
        ml.addWidget(tbw)

        self.canvas = BoxCanvas()
        # 主窗口统一管理画布按键，快捷键设置里修改后才能真正替换旧按键。
        self.canvas.set_external_shortcuts(True)
        self.canvas.changed.connect(self._on_boxes_changed)
        self.canvas.selection_changed.connect(self._on_box_selected)
        self.canvas.zoom_changed.connect(self._on_canvas_zoom)
        # 画布里按上下键翻图(没选中框时)
        self.canvas.step_image.connect(self._step_vis)
        self.canvas.pending_changed.connect(self._on_pending)
        ml.addWidget(self.canvas, 1)

        self.lb_imginfo = QLabel("")
        self.lb_imginfo.setObjectName("Hint")
        self.lb_imginfo.setAlignment(Qt.AlignCenter)
        self.lb_imginfo.setWordWrap(True)
        ml.addWidget(self.lb_imginfo)
        split.addWidget(mid)

        right = QWidget()
        right.setMinimumWidth(200)     # 保证"框数"那列不会被挤掉
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(12)
        c = Card("各类别框数", "颜色和预览图里的框一致", grow=True)
        self.tbl_stat = QTableWidget(0, 3)
        self.tbl_stat.setHorizontalHeaderLabels(["id", "类别", "框数"])
        h2 = self.tbl_stat.horizontalHeader()
        h2.setSectionResizeMode(0, QHeaderView.Fixed)
        h2.setSectionResizeMode(1, QHeaderView.Stretch)
        h2.setSectionResizeMode(2, QHeaderView.Fixed)
        # 窄栏里 id/框数 两列必须紧凑,否则会把中间"类别"列挤到和数字重叠
        self.tbl_stat.setColumnWidth(0, 28)
        self.tbl_stat.setColumnWidth(2, 52)
        self.tbl_stat.verticalHeader().setVisible(False)
        self.tbl_stat.verticalHeader().setDefaultSectionSize(27)
        self.tbl_stat.setEditTriggers(QAbstractItemView.NoEditTriggers)
        c.body.addWidget(self.tbl_stat, 1)
        self.lb_sum = QLabel("")
        self.lb_sum.setObjectName("Hint")
        self.lb_sum.setWordWrap(True)
        c.body.addWidget(self.lb_sum)
        rl.addWidget(c, 1)
        split.addWidget(right)

        # 三栏:文件列表窄、图片区最宽(看框是主要任务)、统计表中等
        split.setSizes([225, 560, 260])
        # 每栏都能独立收窄;真放不下时由 QSplitter 出滚动而不是重叠
        split.setStretchFactor(1, 1)      # 拉窗口时把多出来的宽度给图片区
        lay.addWidget(split, 1)
        return page

    # ================= 页面3:数据集 =================
    def _build_dataset_page(self):
        page, lay = self._page_shell(
            "导出数据集",
            "把图片和标签配对、切成 train/val,并生成 YOLO 需要的 data.yaml")

        c = Card("切分设置")
        self.p_ds = PathPicker("数据集输出目录", status=False)
        self.sp_val = QDoubleSpinBox()
        self.sp_val.setRange(0.05, 0.5)
        self.sp_val.setSingleStep(0.05)
        self.sp_val.setDecimals(2)
        self.sp_val.setToolTip("验证集占比,常用 0.2")
        self.sp_seed = QSpinBox()
        self.sp_seed.setRange(0, 99999)
        self.sp_seed.setToolTip("随机种子。同一个种子切出来的结果一样,方便复现")
        c.body.addWidget(FieldRow("输出目录", self.p_ds))
        c.body.addWidget(FieldRow("验证集占比", self.sp_val))
        c.body.addWidget(FieldRow(
            "随机种子", self.sp_seed,
            hint="相同的随机种子生成的验证集划分一致,方便复现切分"))
        row = QHBoxLayout()
        self.btn_ds = QPushButton("生成数据集")
        self.btn_ds.setObjectName("Primary")
        self.btn_ds.setCursor(Qt.PointingHandCursor)
        self.btn_ds.clicked.connect(self.run_dataset)
        b_open = QPushButton("打开数据集目录")
        b_open.clicked.connect(lambda: self._open(self.p_ds.text()))
        row.addWidget(self.btn_ds)
        row.addWidget(b_open)
        row.addStretch(1)
        c.body.addLayout(row)
        lay.addWidget(c)

        c2 = Card("日志", grow=True)
        self.log_ds = QPlainTextEdit()
        self.log_ds.setObjectName("Log")
        self.log_ds.setReadOnly(True)
        self.log_ds.setMaximumBlockCount(2000)
        c2.body.addWidget(self.log_ds, 1)
        lay.addWidget(c2, 1)
        return page

    # ================= 页面5:AI 补充提示词 =================
    def _build_promptai_page(self):
        page, lay = self._page_shell(
            "AI 补充提示词",
            "选上你手动改过的图,让大模型对比 AI 原来标的和你改成的,反推提示词该怎么写")

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        # ---- 左:图片列表(缩略图 + 勾选)----
        left = QWidget()
        llay = QVBoxLayout(left)
        llay.setContentsMargins(0, 0, 0, 0)
        llay.setSpacing(10)
        cimg = Card("图片", "缩略图上是你当前标的框。勾选要提交分析的图,双击放大看",
                    grow=True)
        self.lst_pai = QListWidget()
        self.lst_pai.setIconSize(QSize(96, 96))   # 要看清框,给大一点
        self.lst_pai.setSpacing(2)
        self.lst_pai.itemClicked.connect(self._pai_click)
        self.lst_pai.itemDoubleClicked.connect(self._pai_open)
        cimg.body.addWidget(self.lst_pai, 1)

        # 批量选择:改过的图最常用,单独给个按钮
        brow = FlowLayout()
        for txt, fn, tip in [
                ("全选", lambda: self._pai_check_all(True), "选中列表里所有图"),
                ("全不选", lambda: self._pai_check_all(False), ""),
                ("反选", self._pai_invert, ""),
                ("只选我改过的", self._pai_check_changed,
                 "和 AI 原始版对比,只勾选框有变化的图"),
                ("刷新列表", self._pai_reload, "重新读一遍图片和标签")]:
            b = QPushButton(txt)
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(fn)
            brow.addWidget(b)
        cimg.body.addLayout(brow)
        self.lb_pai_sel = QLabel("已选 0 张")
        self.lb_pai_sel.setObjectName("Hint")
        cimg.body.addWidget(self.lb_pai_sel)
        llay.addWidget(cimg, 1)
        split.addWidget(left)

        # 右侧卡片的总高度会超过小屏幕可用区域。放进独立滚动区后，
        # 模型、类别、开始和建议区都能用滚轮访问，左侧图片列表仍单独滚动。
        right = self._build_promptai_right()
        self.pai_right_scroll = scroll_area(right, min_w=360)
        self.pai_right_scroll.setObjectName("PromptRightScroll")
        self.pai_right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        split.addWidget(self.pai_right_scroll)
        left.setMinimumWidth(280)
        split.setSizes([420, 660])
        lay.addWidget(split, 1)
        return page

    def _build_promptai_right(self):
        """右侧:基线状态 + 模型选择 + 开始 + 建议对照表。"""
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)
        # QScrollArea 依据内容控件的最小高度决定是否显示纵向滚动条。
        # 不设这个约束时，Qt 会继续压缩整列，底部卡片仍可能被裁掉。
        rl.setSizeConstraint(QVBoxLayout.SetMinimumSize)

        c1 = Card("对比基线")
        self.lb_pai_base = QLabel("")
        self.lb_pai_base.setObjectName("Hint")
        self.lb_pai_base.setWordWrap(True)
        c1.body.addWidget(self.lb_pai_base)
        rl.addWidget(c1)

        c2 = Card("模型")
        # 和首页共用同一种可搜索下拉框：点击箭头看完整列表，输入任意片段
        # 会弹出包含匹配结果，同时仍允许输入列表外的自定义模型 id。
        self.cb_pai_model = SearchableCombo()
        self._fill_pai_models(PAI_DEFAULT_MODEL)
        self.cb_pai_model.setToolTip(
            f"分析要看图,必须用视觉模型(名字里带 vl 的)。\n"
            f"默认 {PAI_DEFAULT_MODEL};可点箭头下拉选择,也可输入部分名称搜索")
        b_fetch = QPushButton("拉取列表")
        b_fetch.setToolTip("从接入点读取可用模型(用首页填的 API Key)")
        b_fetch.clicked.connect(self._pai_fetch_models)
        mrow = QHBoxLayout()
        mrow.addWidget(self.cb_pai_model, 1)
        mrow.addWidget(b_fetch)
        c2.body.addLayout(mrow)
        self.sp_pai_workers = QDoubleSpinBox()
        self.sp_pai_workers.setDecimals(0)
        self.sp_pai_workers.setRange(1, 16)
        self.sp_pai_workers.setValue(4)
        self.sp_pai_workers.setToolTip("同时分析几张图。视觉模型配额小,别给太大")
        c2.body.addWidget(FieldRow("并发", self.sp_pai_workers, label_w=52))
        rl.addWidget(c2)

        # 要分析哪些类别 —— 有时只想调其中一两类的描述,
        # 没必要让模型把所有类都动一遍
        c25 = Card("这次分析哪些类别", "默认全选。不勾的类别,描述不会被改动")
        self.lst_pai_cls = QListWidget()
        self.lst_pai_cls.setMaximumHeight(140)
        crow = FlowLayout()
        for txt, fn in [("全选", lambda: self._pai_cls_all(True)),
                        ("全不选", lambda: self._pai_cls_all(False))]:
            b = QPushButton(txt)
            b.clicked.connect(fn)
            crow.addWidget(b)
        c25.body.addWidget(self.lst_pai_cls)
        c25.body.addLayout(crow)
        rl.addWidget(c25)

        c3 = Card("开始")
        self.btn_pai_go = QPushButton("开始分析")
        self.btn_pai_go.setObjectName("Primary")
        self.btn_pai_go.setCursor(Qt.PointingHandCursor)
        self.btn_pai_go.clicked.connect(self._pai_run)
        c3.body.addWidget(self.btn_pai_go)
        self.pb_pai = QProgressBar()
        self.pb_pai.setVisible(False)
        c3.body.addWidget(self.pb_pai)
        self.btn_pai_stop = QPushButton("停止")
        self.btn_pai_stop.setObjectName("Danger")
        self.btn_pai_stop.setEnabled(False)
        self.btn_pai_stop.clicked.connect(
            lambda: setattr(self, "_pai_stop", True))
        c3.body.addWidget(self.btn_pai_stop)
        self.lb_pai_stat = QLabel("")
        self.lb_pai_stat.setObjectName("Hint")
        self.lb_pai_stat.setWordWrap(True)
        c3.body.addWidget(self.lb_pai_stat)
        rl.addWidget(c3)

        # 建议对照表:模型给完先在这里看,勾了才写进类别表
        c4 = Card("建议", "勾选要采纳的,再点下面的「应用」。不勾的不会动", grow=True)
        self.tbl_pai = QTableWidget(0, 4)
        self.tbl_pai.setHorizontalHeaderLabels(["采纳", "类别", "现在的描述", "建议改成"])
        self.tbl_pai.verticalHeader().setVisible(False)
        self.tbl_pai.setColumnWidth(0, 44)
        self.tbl_pai.setColumnWidth(1, 88)
        self.tbl_pai.horizontalHeader().setStretchLastSection(True)
        self.tbl_pai.setWordWrap(True)
        c4.body.addWidget(self.tbl_pai, 1)
        self.lb_pai_neg = QLabel("")
        self.lb_pai_neg.setObjectName("Hint")
        self.lb_pai_neg.setWordWrap(True)
        c4.body.addWidget(self.lb_pai_neg)
        arow = QHBoxLayout()
        self.btn_pai_apply = QPushButton("应用勾选的建议")
        self.btn_pai_apply.setObjectName("Primary")
        self.btn_pai_apply.setEnabled(False)
        self.btn_pai_apply.clicked.connect(self._pai_apply)
        b_detail = QPushButton("看模型原话")
        b_detail.setToolTip("显示每张图的观察结论,便于判断建议靠不靠谱")
        b_detail.clicked.connect(self._pai_show_findings)
        arow.addWidget(self.btn_pai_apply, 1)
        arow.addWidget(b_detail)
        c4.body.addLayout(arow)
        rl.addWidget(c4, 1)
        return right

    # ---------------- AI 补充提示词:列表 ----------------
    def _pai_reload(self):
        """铺图片列表:名字 + 缩略图 + 勾选框,并标出哪些改过。"""
        out = self.p_out.text() or self.cfg.get("out", "")
        imgs = self.p_images.text() or self.cfg.get("images", "")
        rows = core.list_editable_images(imgs, out)
        pd = core.project_dir(self._proj) if self._proj else ""
        has_base = bool(pd) and core.has_baseline(pd)
        names = [c["name"] for c in self._classes_from_table()]
        # 画好框的图缓存在项目里,不污染你的图片目录
        cache = os.path.join(pd, "prompt_ai", "boxed") if pd else None

        self.lst_pai.clear()
        self._pai_rows = []
        for name, img, lb, n in rows:
            cur = core.read_boxes(lb) if os.path.exists(lb) else []
            base = None
            changed = False
            if has_base:
                bp = core.baseline_label_for(pd, img)
                if os.path.exists(bp):
                    base = core.read_boxes(bp)
                    d = core.diff_boxes(base, cur)
                    changed = bool(d["moved"] or d["relabeled"]
                                   or d["deleted"] or d["added"])
            tag = "  ● 改过" if changed else ""
            it = QListWidgetItem(f"{name}{tag}")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            it.setData(Qt.UserRole, img)
            it.setToolTip(f"{name}\n框数:{len(cur)}\n双击放大查看")
            if changed:
                it.setForeground(QColor(C["ok"]))
            self.lst_pai.addItem(it)
            # 缩略图【不在这里画】。一张 4K 图渲染要 80ms,100 张就是 8 秒
            # 界面卡死。先把列表铺出来,缩略图交给后台线程慢慢补。
            self._pai_rows.append({"name": name, "img": img, "label": lb,
                                   "cur": cur, "base": base,
                                   "changed": changed, "show": img})
        # 基线状态说明
        if not self._proj:
            self.lb_pai_base.setText("还没有项目。先在首页新建一个项目。")
        elif not has_base:
            self.lb_pai_base.setStyleSheet(
                f"color:{C['warn']}; background:transparent;")
            self.lb_pai_base.setText(
                "还没有 AI 原始版可对比 —— 这是个全新项目。\n"
                "分析时会直接看你的手动标注,给出第一版提示词。\n"
                "(跑一次自动标注后,这里就会记下 AI 原始版)")
        else:
            m = core.baseline_meta(pd)
            n_ch = sum(1 for r in self._pai_rows if r["changed"])
            self.lb_pai_base.setStyleSheet(
                f"color:{C['text_dim']}; background:transparent;")
            self.lb_pai_base.setText(
                f"AI 原始版:{m.get('at','?')}({m.get('n_files',0)} 张)\n"
                f"其中 {n_ch} 张你改过。\n"
                "手动保存多少次都不影响这一版,对比结果稳定。")
        self._pai_fill_classes()
        self._pai_update_sel()
        self._pai_start_thumbs(cache)

    def _pai_start_thumbs(self, cache):
        """后台把缩略图一张张画出来,画好一张就发信号更新一行。

        为什么要后台:一张 4K 图渲染 80ms,100 张 8 秒 —— 全在主线程做
        就是"一点就卡"。现在点进来列表立刻出来,图慢慢补上。
        """
        self._pai_thumb_seq += 1        # 换代号:老线程的结果直接丢掉
        seq = self._pai_thumb_seq
        rows = list(self._pai_rows)
        if not rows:
            return
        names = [c["name"] for c in self._classes_from_table()]
        cols = palette()
        import threading

        def work():
            for i, r in enumerate(rows):
                if seq != self._pai_thumb_seq or self._closing:
                    return          # 已经换页/换项目了,别再往界面上写
                try:
                    p = promptai.render_thumb(
                        r["img"], r["cur"], cols, size=192, cache_dir=cache)
                except Exception:
                    continue
                self.pai_thumb.emit(seq, i, p)

        threading.Thread(target=work, daemon=True).start()

    def _on_pai_thumb(self, seq, i, path):
        """后台画好了一张缩略图:贴到对应那一行。"""
        if seq != self._pai_thumb_seq or self._closing:
            return                  # 过期结果(用户已经切走了/正在关窗)
        if not (0 <= i < self.lst_pai.count()) or i >= len(self._pai_rows):
            return
        try:
            row_data = self._pai_rows[i]
        except IndexError:
            return          # 测试替身会跨线程直调信号，列表可能刚好被刷新
        it = self.lst_pai.item(i)
        if it is None:
            return          # 列表刚好在这一瞬被清空了(连着切页会遇到)
        pm = QPixmap(path)
        if pm.isNull():
            return
        it.setIcon(QIcon(pm))
        row_data["show"] = path

    def _pai_fill_classes(self):
        """铺"这次分析哪些类别"。默认全勾上;保留上次的勾选状态。"""
        was = {}
        for i in range(self.lst_pai_cls.count()):
            it = self.lst_pai_cls.item(i)
            was[it.text()] = it.checkState() == Qt.Checked
        self.lst_pai_cls.clear()
        for c in self._classes_from_table():
            if not c.get("on", True):
                continue          # 类别表里关掉的类,这里也不用出现
            nm = c["name"]
            it = QListWidgetItem(nm)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if was.get(nm, True) else Qt.Unchecked)
            it.setToolTip((c.get("desc") or "还没有描述") + "\n勾上才会分析这一类")
            self.lst_pai_cls.addItem(it)

    def _pai_cls_all(self, on):
        st = Qt.Checked if on else Qt.Unchecked
        for i in range(self.lst_pai_cls.count()):
            self.lst_pai_cls.item(i).setCheckState(st)

    def _pai_classes_picked(self):
        """勾选要分析的类别名。"""
        return [self.lst_pai_cls.item(i).text()
                for i in range(self.lst_pai_cls.count())
                if self.lst_pai_cls.item(i).checkState() == Qt.Checked]

    def _pai_update_sel(self):
        n = sum(1 for i in range(self.lst_pai.count())
                if self.lst_pai.item(i).checkState() == Qt.Checked)
        self.lb_pai_sel.setText(f"已选 {n} 张")
        return n

    def _pai_check_all(self, on):
        st = Qt.Checked if on else Qt.Unchecked
        for i in range(self.lst_pai.count()):
            self.lst_pai.item(i).setCheckState(st)
        self._pai_update_sel()

    def _pai_invert(self):
        for i in range(self.lst_pai.count()):
            it = self.lst_pai.item(i)
            it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked
                             else Qt.Checked)
        self._pai_update_sel()

    def _pai_check_changed(self):
        """只勾选和 AI 原始版有差异的图 —— 最常用的批量操作。"""
        rows = getattr(self, "_pai_rows", [])
        n = 0
        for i in range(self.lst_pai.count()):
            ch = rows[i]["changed"] if i < len(rows) else False
            self.lst_pai.item(i).setCheckState(
                Qt.Checked if ch else Qt.Unchecked)
            n += 1 if ch else 0
        self._pai_update_sel()
        if not n:
            self.status.showMessage(
                "没有检测到改过的图(全新项目就自己勾选要分析的)", 4000)

    def _pai_click(self, it):
        """点一行:只更新"已选几张",不放大。

        放大改成双击 —— 单击就弹窗的话,勾选/取消勾选时都会被窗口打断,
        批量选十几张会被弹十几次。
        """
        self._pai_update_sel()

    def _pai_open(self, it):
        """双击才放大看图。

        列表里的缩略图只有 192px(为了不卡),放大看糊,所以这里按需渲染
        一张清晰的带框图。只渲染点开的这一张,不影响速度。
        """
        p = it.data(Qt.UserRole) if it else ""
        if not (p and os.path.isfile(p)):
            return
        rows = getattr(self, "_pai_rows", [])
        pd = core.project_dir(self._proj) if self._proj else ""
        cache = os.path.join(pd, "prompt_ai", "boxed") if pd else None
        names = [c["name"] for c in self._classes_from_table()]
        # 放大看的是【带框的图】,不是原图 —— 你要确认的是框标得对不对
        paths, idx = [], 0
        for k, r in enumerate(rows):
            if r["img"] == p:
                idx = k
                try:
                    paths.append(promptai.render_boxed(
                        r["img"], r["cur"], names, palette(), cache_dir=cache))
                    continue
                except Exception:
                    pass
            paths.append(r.get("show") or r["img"])
        ImageDialog(paths, idx, self).exec()

    # ---------------- AI 补充提示词:跑分析 ----------------
    def _fill_pai_models(self, cur=None):
        """按首页的模型缓存重建可搜索下拉列表。"""
        cached = list(self.cfg.get("model_cache") or [])
        items = (core.merge_model_list(cached, current=cur) if cached
                 else [(v, t, True) for v, t in core.API_MODELS])
        self.cb_pai_model.load(items, current=cur or PAI_DEFAULT_MODEL)

    def _pai_fetch_models(self):
        """填模型列表。复用首页拉到的缓存(同一个 Key 和接入点)。"""
        cur = self.cb_pai_model.selected()
        cached = self.cfg.get("model_cache") or []
        if not cached:
            self.status.showMessage(
                "还没有模型列表,先去首页点「拉取模型」", 5000)
            return
        self._fill_pai_models(cur)
        self.status.showMessage(f"载入了 {len(cached)} 个模型", 4000)

    def _pai_selected(self):
        """勾选的样本,格式给 promptai.analyze 用。"""
        rows = getattr(self, "_pai_rows", [])
        out = []
        for i in range(self.lst_pai.count()):
            if self.lst_pai.item(i).checkState() != Qt.Checked:
                continue
            if i < len(rows):
                r = rows[i]
                out.append({"name": r["name"], "img": r["img"],
                            "base": r["base"], "cur": r["cur"]})
        return out

    def _pai_run(self):
        if not self._proj:
            QMessageBox.information(self, "先建项目", "所有操作都属于某个项目。")
            return
        samples = self._pai_selected()
        if not samples:
            QMessageBox.information(
                self, "先选图",
                "在左边勾选要提交分析的图片。\n"
                "改过的图可以用「只选我改过的」一键勾上。")
            return
        model = self.cb_pai_model.selected()
        if not model:
            QMessageBox.information(
                self, "选个模型", "分析要看图,填一个视觉模型(名字里带 vl)。")
            return
        if "vl" not in model.lower():
            if QMessageBox.question(
                    self, "这个模型能看图吗?",
                    f"「{model}」看起来不是视觉模型。\n\n"
                    "分析必须看图片,纯文本模型会失败。要继续吗?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No) != QMessageBox.Yes:
                return
        key = (self.cfg.get("api_key") or "").strip()
        if not key:
            QMessageBox.warning(self, "缺 API Key", "先去首页填 API Key。")
            return
        # 只把勾选的类别发给模型 —— 没勾的它看不到,自然不会被改
        picked = self._pai_classes_picked()
        if not picked:
            QMessageBox.information(
                self, "选个类别",
                "「这次分析哪些类别」里一个都没勾。\n至少勾一个才有东西可分析。")
            return
        # 用量提前说清楚:一张图一次调用
        n = len(samples)
        if QMessageBox.question(
                self, "确认提交",
                f"会把 {n} 张图发给「{model}」分析,\n"
                f"大约 {n} 次图片调用 + 1 次汇总调用。\n"
                f"这次只分析 {len(picked)} 个类别:"
                f"{'、'.join(picked[:6])}"
                f"{' 等' if len(picked) > 6 else ''}\n\n继续吗?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes) != QMessageBox.Yes:
            return

        self._pai_stop = False
        self.btn_pai_go.setEnabled(False)
        self.btn_pai_stop.setEnabled(True)
        self.pb_pai.setVisible(True)
        self.pb_pai.setRange(0, 100)
        self.pb_pai.setValue(0)
        self.lb_pai_stat.setStyleSheet(
            f"color:{C['text_dim']}; background:transparent;")
        self.lb_pai_stat.setText(f"正在分析 {n} 张图…")

        self._pai_picked = set(picked)
        classes = [c for c in self._classes_from_table()
                   if c["name"] in self._pai_picked]
        all_names = [c["name"] for c in self._classes_from_table()]
        neg = self.ed_neg.toPlainText().strip()
        hist = core.load_history(core.project_dir(self._proj))
        workers = int(self.sp_pai_workers.value())
        base_url = self.cfg.get("base_url", "")

        # 联网必须放后台线程,否则界面卡死
        import threading

        def work():
            data, err = promptai.analyze(
                samples, classes, neg, hist, base_url, key, model,
                workers=workers,
                on_progress=lambda i, t, _: self.pai_progress.emit(i, t),
                should_stop=lambda: self._pai_stop,
                all_names=all_names)
            self.pai_done.emit(data or {}, err or "")

        threading.Thread(target=work, daemon=True).start()

    def _on_pai_progress(self, i, total):
        self.pb_pai.setValue(int(i * 100 / max(1, total)))
        self.lb_pai_stat.setText(f"正在分析… {i}/{total} 张")

    def _on_pai_done(self, data, err):
        self.btn_pai_go.setEnabled(True)
        self.btn_pai_stop.setEnabled(False)
        self.pb_pai.setVisible(False)
        if err:
            self.lb_pai_stat.setStyleSheet(
                f"color:{C['err']}; background:transparent;")
            self.lb_pai_stat.setText(err)
            return
        self._pai_result = data
        self._pai_fill_table(data)
        self.lb_pai_stat.setStyleSheet(
            f"color:{C['ok']}; background:transparent;")
        self.lb_pai_stat.setText(data.get("summary") or "分析完成,看下面的建议")

    def _pai_fill_table(self, data):
        """把建议铺成对照表。只有勾选并点「应用」才会写进类别表。"""
        items = [c for c in (data.get("classes") or [])
                 if isinstance(c, dict)]
        # 双保险:模型偶尔会顺手改没让它看的类别,这里再过滤一次
        picked = getattr(self, "_pai_picked", None)
        if picked:
            items = [c for c in items if (c.get("name") or "").strip() in picked]
        cur_desc = {c["name"]: (c.get("desc") or "")
                    for c in self._classes_from_table()}
        self.tbl_pai.setRowCount(0)
        n_change = 0
        n_warn = 0
        for c in items:
            nm = (c.get("name") or "").strip()
            new = (c.get("desc") or "").strip()
            old = cur_desc.get(nm, "")
            act = (c.get("action") or "").lower()
            # keep 或者内容没变的不占位置 —— 表里只放真正要改的
            if act == "keep" or not new or new == old:
                continue
            r = self.tbl_pai.rowCount()
            self.tbl_pai.insertRow(r)
            # 检查模型有没有"整个重写"而不是在原文上修订
            warn = promptai.rewrite_warning(old, new)
            ck = QCheckBox()
            # 改动过大的默认【不勾】—— 让你先看一眼再决定,
            # 而不是一点应用就把原来写好的描述冲掉
            ck.setChecked(not warn)
            ck.setToolTip(warn or (c.get("reason") or ""))
            w = QWidget()
            wl = QHBoxLayout(w)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.addWidget(ck, 0, Qt.AlignCenter)
            self.tbl_pai.setCellWidget(r, 0, w)
            tip = []
            if c.get("changed"):
                tip.append(f"改了哪里:{c['changed']}")
            if c.get("reason"):
                tip.append(f"依据:{c['reason']}")
            if warn:
                tip.append(f"⚠ {warn}")
            for col, txt in ((1, nm + (" ⚠" if warn else "")),
                             (2, old or "(空)"), (3, new)):
                it = QTableWidgetItem(txt)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if tip:
                    it.setToolTip("\n".join(tip))
                if warn:
                    it.setForeground(QColor(C["warn"]))
                self.tbl_pai.setItem(r, col, it)
            n_change += 1
            if warn:
                n_warn += 1
        self.tbl_pai.resizeRowsToContents()

        # 负样本单独显示:它是一整段,不适合塞进表格
        neg_new = (data.get("negative") or "").strip()
        neg_old = self.ed_neg.toPlainText().strip()
        # 要求是"在原文后面追加",模型有时还是会整段重写。
        # 原文没被包含就自己接上去,不让它把你写的东西冲掉。
        if neg_new and neg_old and neg_old not in neg_new:
            extra = neg_new
            for sep in (";", ";", "、", ","):
                extra = extra.replace(sep, ";")
            add = [x.strip() for x in extra.split(";")
                   if x.strip() and x.strip() not in neg_old]
            neg_new = neg_old + ("" if not add else ";" + ";".join(add))
        self._pai_neg = neg_new if (neg_new and neg_new != neg_old) else ""
        if self._pai_neg:
            self.lb_pai_neg.setStyleSheet(
                f"color:{C['warn']}; background:transparent;")
            self.lb_pai_neg.setText(
                f"「不要标注的东西」也建议改成:{self._pai_neg}\n"
                f"理由:{data.get('negative_reason','')}\n"
                "(点「应用」时一起写入)")
        else:
            self.lb_pai_neg.setStyleSheet(
                f"color:{C['text_faint']}; background:transparent;")
            self.lb_pai_neg.setText("「不要标注的东西」没有改动建议")
        self.btn_pai_apply.setEnabled(bool(n_change) or bool(self._pai_neg))
        if n_warn:
            self.status.showMessage(
                f"有 {n_warn} 条改动幅度过大(标了 ⚠),已默认不勾选,"
                "请对比原文后再决定", 8000)
        if not n_change and not self._pai_neg:
            self.lb_pai_neg.setText(
                "模型认为现在的描述已经够用,没有要改的。")

    def _pai_apply(self):
        """把勾上的建议写进类别表,并记进改动史(下一轮的记忆)。"""
        classes = self._classes_from_table()
        by_name = {c["name"]: c for c in classes}
        entries = []
        n = 0
        for r in range(self.tbl_pai.rowCount()):
            w = self.tbl_pai.cellWidget(r, 0)
            ck = w.findChild(QCheckBox) if w else None
            nm = self.tbl_pai.item(r, 1).text()
            old = self.tbl_pai.item(r, 2).text()
            new = self.tbl_pai.item(r, 3).text()
            accepted = bool(ck and ck.isChecked())
            # 拒绝的也要记 —— 下一轮模型才知道不要再提这条
            entries.append({"class": nm, "old": "" if old == "(空)" else old,
                            "new": new, "accepted": accepted,
                            "reason": (self.tbl_pai.item(r, 3).toolTip() or "")
                            .replace("理由:", "")})
            if accepted and nm in by_name:
                by_name[nm]["desc"] = new
                n += 1
        neg_applied = False
        if getattr(self, "_pai_neg", ""):
            self.ed_neg.setPlainText(self._pai_neg)
            entries.append({"class": "(不要标注的东西)", "old": "",
                            "new": self._pai_neg, "accepted": True,
                            "reason": "整段替换"})
            neg_applied = True
        if not n and not neg_applied:
            self.status.showMessage("一条都没勾,什么都没改", 3000)
            return
        self._fill_class_table(classes)
        self._save_cfg()
        core.append_history(core.project_dir(self._proj), entries)
        self.btn_pai_apply.setEnabled(False)
        self.lb_pai_stat.setStyleSheet(
            f"color:{C['ok']}; background:transparent;")
        self.lb_pai_stat.setText(
            f"已写入 {n} 条描述"
            + ("(含不要标注的东西)" if neg_applied else "")
            + "。下次跑自动标注就会用新提示词。")
        self.status.showMessage(
            f"已应用 {n} 条建议,并记入调整历史", 5000)

    def _pai_show_findings(self):
        """看模型对每张图的原话,判断建议靠不靠谱。"""
        data = getattr(self, "_pai_result", None)
        if not data:
            QMessageBox.information(self, "还没有结果", "先点「开始分析」。")
            return
        txt = "\n\n".join(data.get("_findings") or []) or "(没有观察结论)"
        errs = data.get("_errors") or []
        if errs:
            txt += "\n\n分析失败的图:\n" + "\n".join(errs[:10])
        dlg = QDialog(self)
        dlg.setWindowTitle("模型的观察结论")
        dlg.resize(760, 560)
        dl = QVBoxLayout(dlg)
        box = QPlainTextEdit(txt)
        box.setReadOnly(True)
        dl.addWidget(box, 1)
        b = QPushButton("关闭")
        b.clicked.connect(dlg.accept)
        dl.addWidget(b)
        dlg.exec()

    def _space_pressed(self):
        """空格只在视频切片页有意义,在别的页按了不该有反应。"""
        if self.pages.currentIndex() == self.PAGE_VIDEO:
            self._toggle_vid_play()

    # ---------------- 视频切片:逻辑 ----------------
    def _load_video(self):
        """选了视频文件之后:读信息、铺开区间条、显示第一帧。"""
        path = self.p_video.text().strip()
        self._stop_vid_play()
        if self._vid_reader is not None:
            self._vid_reader.close()
            self._vid_reader = None
        if not path:
            return
        if not vid.is_video(path):
            self.lb_vinfo.setText(
                f"这个后缀不像视频({os.path.splitext(path)[1]})。"
                f"支持:{'、'.join(e.lstrip('.') for e in vid.VIDEO_EXTS)}")
            self.lb_vinfo.setStyleSheet(f"color:{C['warn']}; background:transparent;")
            return
        info = vid.probe(path)
        self._vid_info = info
        if not info["ok"]:
            self.lb_vinfo.setText(f"读不了这个视频:{info['err']}")
            self.lb_vinfo.setStyleSheet(f"color:{C['err']}; background:transparent;")
            self.vid_bar.set_duration(0)
            return
        self.lb_vinfo.setStyleSheet(f"color:{C['text_faint']}; background:transparent;")
        self.lb_vinfo.setText(
            f"{info['w']}×{info['h']} · {info['fps']:.2f} fps · "
            f"时长 {vid.fmt_time(info['duration'])}"
            + (f" · 约 {info['frames']} 帧" if info["frames"] else ""))
        self._vid_reader = vid.FrameReader(path)
        self.vid_bar.set_duration(info["duration"])
        # 输出目录没填就默认放到项目里的 frames/,省得用户自己想
        if not self.p_frames.text().strip():
            base = (core.project_dir(self._proj) if self._proj
                    else os.path.dirname(path))
            self.p_frames.setText(os.path.join(base, "frames"))
        self._show_vid_frame(0.0)
        self._update_vid_est()

    def _show_vid_frame(self, sec):
        """把某一时刻的画面显示到预览区。"""
        if getattr(self, "_closing", False):
            return          # 正在关窗,控件可能已经没了
        if self._vid_reader is None or not self._vid_reader.ok():
            return
        frame = self._vid_reader.at(sec)
        if frame is None:
            return
        try:
            import numpy as np
            # 下面这行按"3 通道 + 内存连续"去读 frame 的原始内存。
            # 灰度视频给的是单通道,按 3*w 的行距读会越界 —— 那是直接段错误,
            # try/except 都拦不住。所以先把形状和连续性摆平。
            if frame.ndim == 2:                     # 灰度 -> 补成 3 通道
                frame = np.repeat(frame[:, :, None], 3, axis=2)
            elif frame.shape[2] == 4:               # BGRA -> 丢掉 alpha
                frame = frame[:, :, :3]
            elif frame.shape[2] != 3:
                return
            if not frame.flags["C_CONTIGUOUS"]:
                frame = np.ascontiguousarray(frame)
            h, w = frame.shape[:2]
            if w <= 0 or h <= 0:
                return
            # OpenCV 给的是 BGR,用 Format_BGR888 直接认,不用再转一次
            img = QImage(frame.data, w, h, 3 * w, QImage.Format_BGR888)
            # copy():frame 是临时的 numpy 数组,QImage 只是借用它的内存,
            # 不复制的话下一帧覆盖过来会花屏甚至崩
            self.vid_prev.set_frame(QPixmap.fromImage(img.copy()))
        except Exception:
            pass

    def _on_vid_range(self, a, b):
        self._update_vid_est()

    def _on_vid_head_moving(self, sec):
        """拖动播放头时连续出画面(剪辑软件那种跟手的感觉)。

        不能在这里直接解码。鼠标一秒能发上百个 move 事件,而 4K 视频解一帧
        要几十毫秒 —— 事件会排成长队,每一个都去解一个【已经过时】的位置,
        画面就越拖越落后。
        所以这里只记下"最想看哪个时间点"(极便宜),真正的解码交给一个短
        定时器:它每次只解最新的那个位置,中间积压的全部丢掉。
        """
        self._vid_want = sec
        if not self._scrub_timer.isActive():
            # 第一帧立刻出,手感才跟得上;之后由定时器按节奏续
            self._scrub_decode()
            self._scrub_timer.start(40)

    def _scrub_decode(self):
        """解码并显示"最新想看的那一帧"。没有新位置就把定时器停掉。"""
        want = getattr(self, "_vid_want", None)
        if want is None:
            self._scrub_timer.stop()
            return
        self._vid_want = None
        self._show_vid_frame(want)

    def _on_vid_head(self, sec):
        # 松手:停掉限流,把最后位置精确补一帧,
        # 保证你停在哪里看到的就是哪一帧
        self._scrub_timer.stop()
        self._vid_want = None
        self._show_vid_frame(sec)

    def _set_vid_edge(self, which):
        a, b = self.vid_bar.range()
        h = self.vid_bar.head()
        self.vid_bar.set_range(h, b) if which == "a" else self.vid_bar.set_range(a, h)

    def _toggle_vid_play(self):
        if self._vid_timer.isActive():
            self._stop_vid_play()
        else:
            if self._vid_reader is None or not self._vid_reader.ok():
                return
            a, b = self.vid_bar.range()
            if not (a <= self.vid_bar.head() < b):
                self.vid_bar.set_head(a)
            self.vid_play.setText("⏸ 暂停")
            fps = self._vid_info.get("fps") or 25.0
            # 预览不必按原始帧率解码,12fps 足够看清动作,也不会把界面拖死
            self._vid_step = 1.0 / min(fps, 12.0)
            self._vid_timer.start(int(1000 / min(fps, 12.0)))

    def _stop_vid_play(self):
        self._vid_timer.stop()
        self.vid_play.setText("▶ 播放区间")

    def _vid_tick(self):
        a, b = self.vid_bar.range()
        t = self.vid_bar.head() + getattr(self, "_vid_step", 0.08)
        if t >= b:
            t = a          # 在区间里循环,方便反复确认这段对不对
        self.vid_bar.set_head(t)
        self._show_vid_frame(t)

    def _update_vid_est(self):
        """预告会抽多少张。间隔填太小会抽爆,必须提前告诉用户。"""
        if not self._vid_info.get("ok"):
            self.lb_vest.setText("")
            return
        a, b = self.vid_bar.range()
        ivl = self.sp_ivl.value()
        times = vid.plan_times(a, b, ivl, self._vid_info["duration"])
        n = len(times)
        self.vid_bar.set_marks(times if n <= 400 else times[::max(1, n // 400)])
        txt = (f"区间 {vid.fmt_time(a)} ~ {vid.fmt_time(b)}"
               f"(共 {vid.fmt_time(max(0, b - a))}),每 {ivl:g} 秒一张 "
               f"→ 预计 {n} 张")
        if n > MAX_FRAMES:
            txt += f";超过上限 {MAX_FRAMES} 张,只会抽前 {MAX_FRAMES} 张"
            self.lb_vest.setStyleSheet(f"color:{C['warn']}; background:transparent;")
        elif n > 800:
            txt += ";数量不少,标注量会很大,可以把间隔调大些"
            self.lb_vest.setStyleSheet(f"color:{C['warn']}; background:transparent;")
        else:
            self.lb_vest.setStyleSheet(f"color:{C['text_faint']}; background:transparent;")
        self.lb_vest.setText(txt)

    def _run_extract(self):
        """开始抽帧。在主线程里做,但每张都刷新界面,不会假死。"""
        if not self._vid_info.get("ok"):
            QMessageBox.information(self, "先选视频", "先选一个能打开的视频文件。")
            return
        out = self.p_frames.text().strip()
        if not out:
            QMessageBox.information(self, "选个输出目录", "先指定图片放到哪个文件夹。")
            return
        prefix = self.ed_vprefix.text().strip() or "image_"
        if re.search(r'[\\/:*?"<>|]', prefix):
            QMessageBox.warning(self, "文件名不合法",
                                '前缀不能包含 \\ / : * ? " < > |')
            return
        a, b = self.vid_bar.range()
        n_plan = len(vid.plan_times(a, b, self.sp_ivl.value(),
                                    self._vid_info["duration"]))
        if n_plan > 800:
            if QMessageBox.question(
                    self, "确认张数",
                    f"这次会抽出约 {min(n_plan, MAX_FRAMES)} 张图。\n\n"
                    "张数太多的话后面标注工作量会很大,\n"
                    "要不要先把抽帧间隔调大一点?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes) != QMessageBox.Yes:
                return
        self._stop_vid_play()
        self._vid_stop = False
        self.btn_vgo.setEnabled(False)
        self.btn_vstop.setEnabled(True)
        self.pb_vid.setVisible(True)
        self.pb_vid.setRange(0, 100)
        self.pb_vid.setValue(0)

        def on_prog(i, total, path):
            # processEvents 会让【关窗事件】在抽帧循环中间被处理:窗口一销毁,
            # 这个回调再去碰 pb_vid / lb_vstat 就是访问已释放的控件 —— 段错误。
            # 所以先看 _closing,是关窗就立刻让循环退出。
            if getattr(self, "_closing", False):
                return False
            self.pb_vid.setValue(int(i * 100 / max(1, total)))
            self.lb_vstat.setText(f"正在切分… {i}/{total}  {os.path.basename(path)}")
            QApplication.processEvents()      # 让界面能响应"停止"
            return not self._vid_stop and not getattr(self, "_closing", False)

        n, err = vid.extract(
            self.p_video.text().strip(), out,
            interval=self.sp_ivl.value(), start=a, end=b,
            prefix=prefix, digits=3,
            fmt=self.cb_vfmt.currentData(),
            resume=self.ck_vresume.isChecked(),
            on_progress=on_prog, should_stop=lambda: self._vid_stop,
            limit=MAX_FRAMES)

        if getattr(self, "_closing", False):
            return            # 窗口已经在关了,别再动任何控件
        self.btn_vgo.setEnabled(True)
        self.btn_vstop.setEnabled(False)
        self.pb_vid.setVisible(False)
        if err and n == 0:
            self.lb_vstat.setStyleSheet(f"color:{C['err']}; background:transparent;")
            self.lb_vstat.setText(f"切分失败:{err}")
            return
        self.lb_vstat.setStyleSheet(f"color:{C['ok']}; background:transparent;")
        tail = "(已停止)" if err == "已停止" else ""
        self.lb_vstat.setText(f"切好了 {n} 张,放在 {out}{tail}")
        self._reload_thumbs()          # 切完立刻把图铺到下半边
        self.status.showMessage(f"视频切片完成:{n} 张图 -> {out}", 8000)

    def _reload_thumbs(self):
        """重新铺一遍切好的图。"""
        out = self.p_frames.text().strip()
        shown, total = self.thumbs.load_dir(out)
        if not total:
            self.lb_thumbs.setText("这个文件夹里还没有图")
        elif shown < total:
            self.lb_thumbs.setText(
                f"共 {total} 张,只显示前 {shown} 张(太多了会卡);"
                "其余请点「打开切分文件夹」")
        else:
            self.lb_thumbs.setText(f"共 {total} 张")

    def _open_thumb(self, path):
        """点缩略图:弹窗放大看,左右键能翻页。"""
        paths = self.thumbs.paths()
        try:
            i = paths.index(path)
        except ValueError:
            i = 0
        ImageDialog(paths, i, self).exec()

    def _use_frames(self):
        """把项目的图片文件夹指向刚切出来的目录,少一步手选。"""
        out = self.p_frames.text().strip()
        if not out or not os.path.isdir(out):
            QMessageBox.information(self, "还没有图", "先切分出图片再用。")
            return
        if not self._require_project():
            return
        self.p_images.setText(out)
        self._save_cfg()
        self._refresh_img_count()
        self.refresh_results()
        n = core.count_images(out)
        self.status.showMessage(f"当前项目的图片文件夹已指向 {out}({n} 张)", 6000)
        self._go(self.PAGE_HOME)

    # ================= 页面4:视频切片 =================
    def _build_video_page(self):
        page, lay = self._page_shell(
            "视频切片", "把视频按时间间隔抽成图片。拖两端选区间,可以先播一遍看看")

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        # ---- 左:预览 + 区间条 ----
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)
        cprev = Card("预览", grow=True)
        self.vid_prev = VideoView()
        cprev.body.addWidget(self.vid_prev, 1)

        self.vid_bar = RangeBar()
        self.vid_bar.range_changed.connect(self._on_vid_range)
        self.vid_bar.head_moved.connect(self._on_vid_head_moving)
        self.vid_bar.head_released.connect(self._on_vid_head)
        cprev.body.addWidget(self.vid_bar)

        prow = QHBoxLayout()
        prow.setSpacing(7)
        self.vid_play = QPushButton("▶ 播放区间")
        self.vid_play.setToolTip("在选定区间里循环播放(空格键也可以)")
        self.vid_play.clicked.connect(self._toggle_vid_play)
        b_a = QPushButton("[ 设为开始")
        b_a.setToolTip("把播放头的位置设成区间开始")
        b_a.clicked.connect(lambda: self._set_vid_edge("a"))
        b_b = QPushButton("设为结束 ]")
        b_b.setToolTip("把播放头的位置设成区间结束")
        b_b.clicked.connect(lambda: self._set_vid_edge("b"))
        b_all = QPushButton("整段")
        b_all.setToolTip("区间恢复成整个视频")
        b_all.clicked.connect(lambda: self.vid_bar.set_range(
            0, self.vid_bar.duration()))
        for b in (self.vid_play, b_a, b_b, b_all):
            prow.addWidget(b)
        prow.addStretch(1)
        cprev.body.addLayout(prow)
        ll.addWidget(cprev, 1)
        split.addWidget(left)

        # ---- 右:设置在上,切好的图在下 ----
        # 这一页刻意【不用滚动区】:所有东西必须一屏看完。
        # 三张设置卡按内容占自然高度,剩下的全给缩略图 ——
        # 窗口变小时是缩略图变小,而不是让你滚轮找按钮。
        right = QWidget()
        rcol = QVBoxLayout(right)
        rcol.setContentsMargins(0, 0, 0, 0)
        rcol.setSpacing(10)
        rtop = QWidget()
        rl = QVBoxLayout(rtop)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)

        c1 = Card("视频与输出")
        self.p_video = PathPicker(
            "视频文件路径", pick_dir=False, status=False,
            file_filter="视频 (*.mp4 *.mov *.avi *.mkv *.flv *.wmv *.webm"
                        " *.m4v *.mpg *.mpeg *.ts *.3gp);;所有文件 (*)")
        self.p_video.changed.connect(lambda _: self._load_video())
        self.p_frames = PathPicker("图片输出文件夹", status=False)
        self.p_frames.changed.connect(lambda _: self._reload_thumbs())
        c1.body.addWidget(FieldRow("视频", self.p_video, label_w=76))
        c1.body.addWidget(FieldRow("输出到", self.p_frames, label_w=76))
        self.lb_vinfo = QLabel("")
        self.lb_vinfo.setObjectName("Hint")
        self.lb_vinfo.setWordWrap(True)
        c1.body.addWidget(self.lb_vinfo)

        c2 = Card("抽帧设置")
        self.sp_ivl = QDoubleSpinBox()
        self.sp_ivl.setRange(0.02, 600.0)
        self.sp_ivl.setDecimals(2)
        self.sp_ivl.setSingleStep(0.5)
        self.sp_ivl.setValue(1.0)
        self.sp_ivl.setSuffix(" 秒")
        self.sp_ivl.setToolTip("每隔多久抽一张。标注素材通常 0.5~2 秒")
        self.sp_ivl.valueChanged.connect(self._update_vid_est)
        self.cb_vfmt = QComboBox()
        for v, t in [("jpg", "jpg(小,推荐)"), ("png", "png(无损,大)")]:
            self.cb_vfmt.addItem(t, v)
        self.ed_vprefix = QLineEdit("image_")
        self.ed_vprefix.setToolTip("文件名前缀,配合序号 -> image_001.jpg")
        self.ck_vresume = QCheckBox("接着已有编号往后排")
        self.ck_vresume.setChecked(True)
        self.ck_vresume.setToolTip(
            "输出文件夹里已经有 image_007 时,这次从 008 开始,不覆盖旧的。\n"
            "取消勾选则每次都从 001 开始(会覆盖同名文件)")
        c2.body.addWidget(FieldRow("抽帧间隔", self.sp_ivl, label_w=76))
        c2.body.addWidget(FieldRow("图片格式", self.cb_vfmt, label_w=76))
        c2.body.addWidget(FieldRow("文件名", self.ed_vprefix, label_w=76))
        c2.body.addWidget(FieldRow("", self.ck_vresume, label_w=76))
        self.lb_vest = QLabel("")
        self.lb_vest.setObjectName("Hint")
        self.lb_vest.setWordWrap(True)
        c2.body.addWidget(self.lb_vest)

        c3 = Card("开始")
        self.btn_vgo = QPushButton("确定,开始切分")
        self.btn_vgo.setObjectName("Primary")
        self.btn_vgo.setCursor(Qt.PointingHandCursor)
        self.btn_vgo.clicked.connect(self._run_extract)
        self.btn_vstop = QPushButton("停止")
        self.btn_vstop.setObjectName("Danger")
        self.btn_vstop.setEnabled(False)
        self.btn_vstop.clicked.connect(lambda: setattr(self, "_vid_stop", True))
        self.btn_vopen = QPushButton("打开切分文件夹")
        self.btn_vopen.clicked.connect(lambda: self._open(self.p_frames.text()))
        self.btn_vuse = QPushButton("用这批图去标注")
        self.btn_vuse.setToolTip("把当前项目的「图片文件夹」指向这个输出目录")
        self.btn_vuse.clicked.connect(self._use_frames)
        c3.body.addWidget(self.btn_vgo)
        # 三个次要按钮挤一行,省出一整行高度给缩略图 ——
        # 这一页不许滚动,竖向空间得省着用
        vrow = QHBoxLayout()
        vrow.setSpacing(6)
        vrow.addWidget(self.btn_vstop)
        vrow.addWidget(self.btn_vopen)
        vrow.addWidget(self.btn_vuse)
        c3.body.addLayout(vrow)
        self.pb_vid = QProgressBar()
        self.pb_vid.setVisible(False)
        c3.body.addWidget(self.pb_vid)
        self.lb_vstat = QLabel("")
        self.lb_vstat.setObjectName("Hint")
        self.lb_vstat.setWordWrap(True)
        c3.body.addWidget(self.lb_vstat)

        # 顺序:视频与输出 -> 开始 -> 抽帧设置。
        # 「开始」放第二块:排在选文件之后符合"先选再动手"的直觉,
        # 又不用滚过一堆参数才看到按钮。参数大多只设一次,放最后。
        rl.addWidget(c1)
        rl.addWidget(c3)
        rl.addWidget(c2)
        # Minimum:这几张卡按内容要多少给多少,绝不被压缩 ——
        # 被压缩就会出现"输入框比文字还矮、文字变虚线"的问题
        rtop.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        rcol.addWidget(rtop, 0)          # 0 = 只占内容需要的高度

        # 下半:切好的图。点一下放大看
        cthumb = Card("切好的图", "点一下放大查看;左右键翻页", grow=True)
        self.thumbs = ThumbStrip()
        self.thumbs.opened.connect(self._open_thumb)
        cthumb.body.addWidget(self.thumbs, 1)
        trow = QHBoxLayout()
        self.lb_thumbs = QLabel("还没有图")
        self.lb_thumbs.setObjectName("Hint")
        b_reload = QPushButton("刷新")
        b_reload.setToolTip("重新读一遍输出文件夹")
        b_reload.clicked.connect(self._reload_thumbs)
        trow.addWidget(self.lb_thumbs, 1)
        trow.addWidget(b_reload)
        cthumb.body.addLayout(trow)
        # 缩略图区是"可让位"的那一方:窗口不够高时它先缩,
        # 而不是把上面的输入框压扁(压扁了文字会被裁成一排虚线)。
        cthumb.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
        self.thumbs.setMinimumHeight(70)
        rcol.addWidget(cthumb, 1)        # 1 = 把剩下的竖向空间全吃掉

        split.addWidget(right)
        left.setMinimumWidth(300)
        right.setMinimumWidth(300)
        split.setSizes([560, 520])       # 右边宽一点,缩略图才铺得开
        lay.addWidget(split, 1)

        # 播放用的定时器:按帧率间隔往前推播放头
        self._vid_timer = QTimer(self)
        self._vid_timer.timeout.connect(self._vid_tick)
        # 拖动播放头时的解码限流:只解"最新想看的那一帧",丢掉积压
        self._scrub_timer = QTimer(self)
        self._scrub_timer.timeout.connect(self._scrub_decode)
        self._vid_want = None
        self._vid_info = {}
        self._vid_reader = None
        self._vid_stop = False
        return page

    # ================= 配置 <-> 界面 =================
    def _apply_cfg(self, cfg):
        """把一份配置整体套进界面(切项目时用)。"""
        self.cfg = cfg
        self._load_to_ui()

    def _load_to_ui(self):
        # 锁是按项目存的。启动和切项目都会走这里,在这一处读就不会漏
        self._locks = (core.load_locks(core.project_dir(self._proj))
                       if self._proj else set())
        c = self.cfg
        self.p_images.setText(c["images"])
        self.p_out.setText(c["out"])
        self.p_ds.setText(c["dataset"])
        self.cb_backup.setChecked(bool(c.get("backup_old", True)))
        self.ed_neg.setPlainText(c.get("negative", ""))
        # 先静默设后端,避免 currentIndexChanged 在模型还没填时就触发
        self.cb_backend.blockSignals(True)
        i = self.cb_backend.findData(c.get("backend", "api"))
        self.cb_backend.setCurrentIndex(max(0, i))
        self.cb_backend.blockSignals(False)
        self._fill_models(c.get("model"))
        self._fill_pai_models(self.cb_pai_model.selected() or PAI_DEFAULT_MODEL)
        self.sp_workers.setValue(int(c.get("workers", 8)))
        self.sp_qps.setValue(int(c.get("qps", 0) or 0))
        self.ck_skip.setChecked(bool(c.get("skip_done", True)))
        j = self.cb_px.findData(int(c.get("max_pixels", 2000000)))
        if j < 0:
            self.cb_px.addItem(core.fmt_px(c["max_pixels"]), int(c["max_pixels"]))
            j = self.cb_px.count() - 1
        self.cb_px.setCurrentIndex(j)
        self.sp_limit.setValue(int(c.get("preview_limit", 20)))
        self.sp_auto.setValue(int(c.get("autosave_min", 1) or 1))
        self.ck_auto.setChecked(bool(c.get("autosave", False)))
        self.sp_auto.setEnabled(self.ck_auto.isChecked())
        k = self.cb_coord.findData(int(float(c.get("coord_scale", 0))))
        self.cb_coord.setCurrentIndex(max(0, k))
        t = self.cb_tiles.findData(c.get("tiles", ""))
        self.cb_tiles.setCurrentIndex(max(0, t))
        self.ed_base.setText(c.get("base_url", ""))
        self.key_field.set_key(c.get("api_key", ""))
        self.sp_val.setValue(float(c.get("val_ratio", 0.2)))
        self.sp_seed.setValue(int(c.get("seed", 0)))
        self._fill_class_table(c["classes"])
        self._on_backend_change()
        self._sync_preview_btn()
        self.sp_limit.valueChanged.connect(self._sync_preview_btn)

    def _fill_models(self, cur=None):
        """按当前后端重建模型下拉。cur 在新列表里就选它,否则选第一个。
        云端:优先用上次拉到的完整列表(缓存在 config 里),没有就用常用列表。"""
        if self.cb_backend.currentData() == "api":
            cached = list(self.cfg.get("model_cache") or [])
            items = (core.merge_model_list(cached, current=cur) if cached
                     else [(v, t, True) for v, t in core.API_MODELS])
        else:
            items = [(v, t, False) for v, t in core.LOCAL_MODELS]
        self.cb_model.load(items, current=cur)

    def _on_backend_change(self, *_):
        # 换后端要换模型列表(本地和云端的模型名完全不同);
        # 当前模型若在新列表里就保留,否则退回该后端的首选模型。
        self._fill_models(self.cb_model.selected())
        is_api = self.cb_backend.currentData() == "api"
        # 并发/切片/接入点只对 API 有意义
        self.sp_workers.setEnabled(is_api)
        self.sp_qps.setEnabled(is_api)
        self.ck_skip.setEnabled(is_api)
        self.cb_tiles.setEnabled(is_api)
        self.ed_base.setEnabled(is_api)
        self.cell_key.setVisible(is_api)
        self.btn_fetch.setVisible(is_api)
        self.lb_fetch.setVisible(is_api)

    def _sync_preview_btn(self, *_):
        self.btn_preview.setText(f"先标 {self.sp_limit.value()} 张预览")

    def _collect_from_ui(self):
        c = dict(self.cfg)
        c["images"] = self.p_images.text()
        c["out"] = self.p_out.text()
        c["dataset"] = self.p_ds.text()
        c["backup_old"] = self.cb_backup.isChecked()
        c["negative"] = self.ed_neg.toPlainText().strip()
        c["backend"] = self.cb_backend.currentData()
        c["model"] = self.cb_model.selected()
        c["workers"] = self.sp_workers.value()
        c["qps"] = self.sp_qps.value()
        c["skip_done"] = self.ck_skip.isChecked()
        c["max_pixels"] = self.cb_px.currentData()
        c["preview_limit"] = self.sp_limit.value()
        c["autosave"] = self.ck_auto.isChecked()
        c["autosave_min"] = self.sp_auto.value()
        c["coord_scale"] = self.cb_coord.currentData()
        c["tiles"] = self.cb_tiles.currentData()
        c["base_url"] = self.ed_base.text().strip()
        c["api_key"] = self.key_field.key()
        c["val_ratio"] = self.sp_val.value()
        c["seed"] = self.sp_seed.value()
        c["classes"] = self._classes_from_table()
        return c

    # ---------------- 类别表 ----------------
    def _fill_class_table(self, classes):
        self.tbl.setRowCount(0)
        for c in classes:
            self._add_class_row(c["name"], c["desc"], c["on"])
        self._update_cls_stat()

    def _add_class_row(self, name="", desc="", on=True):
        r = self.tbl.rowCount()
        self.tbl.insertRow(r)
        chk = QCheckBox()
        chk.setChecked(bool(on))
        # stateChanged 会传一个 int,_update_cls_stat 不收参数,必须用 lambda 挡掉
        chk.stateChanged.connect(lambda _: self._update_cls_stat())
        box = QWidget()
        bl = QHBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(chk, 0, Qt.AlignCenter)
        self.tbl.setCellWidget(r, 0, box)
        it_name = QTableWidgetItem(str(name))
        it_name.setIcon(color_dot(palette()[r % len(palette())]))
        self.tbl.setItem(r, 1, it_name)
        self.tbl.setItem(r, 2, QTableWidgetItem(str(desc)))
        # 行尾的删除按钮:只有"删除"二字,红色
        x = QPushButton("删除")
        x.setObjectName("RowDel")
        x.setCursor(Qt.PointingHandCursor)
        x.setFixedHeight(24)
        x.setToolTip("删掉这个类别")
        # 不能把 r 捕获进闭包 —— 删过一行之后后面的行号就全变了,
        # 那样点第 5 行的叉可能删掉第 3 行。改成运行时按按钮反查当前行。
        x.clicked.connect(lambda _=False, b=x: self._del_class_row(b))
        self.tbl.setCellWidget(r, 3, x)
        self._update_cls_stat()

    def _import_classes(self):
        """从 classes.txt / data.yaml 导入类别表。

        类别顺序就是 id,所以导入是"整表替换"而不是追加 —— 追加会让
        id 对不上那份文件,标签就全错了。已有内容会先问一句。
        """
        if not self._require_project():
            return
        start = self.p_out.text() or self.p_images.text() or core.ROOT
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 classes.txt 或 data.yaml", start,
            "类别文件 (classes.txt *.txt *.yaml *.yml);;所有文件 (*)")
        if not path:
            return
        try:
            names = core.parse_classes_file(path)
        except Exception as e:
            QMessageBox.warning(self, "导入失败", str(e))
            return
        old = self._classes_from_table()
        if old:
            r = QMessageBox.question(
                self, "覆盖现有类别表",
                f"读到 {len(names)} 个类别:\n"
                f"  {'、'.join(names[:6])}{' …' if len(names) > 6 else ''}\n\n"
                f"当前表里有 {len(old)} 个类别,导入会整表替换。\n"
                "(类别顺序就是 id,不能只追加,否则和这份文件对不上)",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if r != QMessageBox.Yes:
                return
        # 描述尽量保留:同名类别沿用原来写好的描述,省得重填
        desc_of = {c["name"]: c["desc"] for c in old}
        on_of = {c["name"]: c["on"] for c in old}
        self._fill_class_table([{"name": n,
                                 "desc": desc_of.get(n, ""),
                                 "on": on_of.get(n, True)} for n in names])
        kept = sum(1 for n in names if desc_of.get(n))
        msg = f"已导入 {len(names)} 个类别"
        if kept:
            msg += f",其中 {kept} 个沿用了原来的描述"
        n_empty = sum(1 for n in names if not desc_of.get(n))
        if n_empty:
            msg += f";还有 {n_empty} 个没有描述,记得补上再跑"
        self.status.showMessage(msg, 8000)
        self._save_cfg()

    def _row_of_button(self, btn):
        """按钮在第几行(实时查,不受删行后行号变化影响)。"""
        for r in range(self.tbl.rowCount()):
            if self.tbl.cellWidget(r, 3) is btn:
                return r
        return -1

    def _del_class_row(self, btn=None):
        r = self._row_of_button(btn) if btn is not None else -1
        if r < 0:
            return
        it = self.tbl.item(r, 1)
        name = (it.text().strip() if it else "") or f"第 {r + 1} 行"
        # 删类别会让后面所有类别的 id 前移,已有标签会对不上,必须提醒。
        # 最后一行没有"后面的类别",不会影响已有标签,所以不用啰嗦。
        is_last = (r == self.tbl.rowCount() - 1)
        if not is_last:
            if QMessageBox.warning(
                    self, "确认删除",
                    f"要删掉类别「{name}」吗?\n\n"
                    f"注意:它后面还有 {self.tbl.rowCount() - r - 1} 个类别,"
                    "删掉会让它们的 id 全部前移,\n"
                    "之前标好的标签会对不上类别,建议删完重新标注。",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No) != QMessageBox.Yes:
                return
        self.tbl.removeRow(r)
        self._recolor_rows()
        self._update_cls_stat()
        self.status.showMessage(f"已删掉类别「{name}」", 3000)

    def _recolor_rows(self):
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r, 1)
            if it:
                it.setIcon(color_dot(palette()[r % len(palette())]))

    def _check_all(self, on):
        for r in range(self.tbl.rowCount()):
            w = self.tbl.cellWidget(r, 0)
            if w:
                cb = w.findChild(QCheckBox)
                if cb:
                    cb.setChecked(on)
        self._update_cls_stat()

    def _classes_from_table(self):
        out = []
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r, 1)
            name = (it.text().strip() if it else "")
            if not name:
                continue
            d = self.tbl.item(r, 2)
            w = self.tbl.cellWidget(r, 0)
            cb = w.findChild(QCheckBox) if w else None
            out.append({"name": name,
                        "desc": (d.text().strip() if d else ""),
                        "on": bool(cb.isChecked()) if cb else True})
        return out

    def _update_cls_stat(self, *_):
        cs = self._classes_from_table()
        on = sum(1 for c in cs if c["on"])
        nod = sum(1 for c in cs if c["on"] and not c["desc"])
        txt = f"共 {len(cs)} 类,本次检测 {on} 类"
        if nod:
            txt += f" · {nod} 个勾选的类没写描述(模型很可能找不到)"
        self.lb_cls_stat.setText(txt)
        self.lb_cls_stat.setStyleSheet(
            f"color:{C['warn'] if nod else C['text_dim']}; background:transparent;")

    def _on_base_changed(self):
        """换了接入点:旧的模型缓存作废,提示重新获取。"""
        if self.cfg.get("model_cache"):
            self.cfg["model_cache"] = []
            self._fill_models(self.cb_model.selected())
            self.lb_fetch.setText("接入点变了,模型列表已清空 —— 请重新点「获取可用模型」。")
            self.lb_fetch.setStyleSheet(f"color:{C['warn']}; background:transparent;")

    def _on_key_changed(self, key):
        """Key 变了:立刻存盘(下次打开就不用再输),并顺手刷新模型列表。

        这是唯一允许把 key 清空的入口 —— 用户确实点了「清除」。
        其它地方存盘时空 key 一律不覆盖已存的,免得被旧界面状态抹掉。
        """
        self.cfg["api_key"] = key
        self._save_cfg(allow_clear=("api_key",))
        if key:
            self.lb_fetch.setText("Key 已保存。正在获取可用模型…")
            self.lb_fetch.setStyleSheet(f"color:{C['text_dim']}; background:transparent;")
            self.fetch_models()
        else:
            self.lb_fetch.setText("已清除 Key。没有 Key 无法调用 API,请重新设置。")
            self.lb_fetch.setStyleSheet(f"color:{C['warn']}; background:transparent;")

    def fetch_models(self):
        """联网拉模型列表。必须放后台线程 —— 在主线程里做网络请求会让界面假死。"""
        if getattr(self, "_fetching", False):
            return
        key = self.key_field.key() or core.builtin_api_key()
        base = self.ed_base.text().strip() or core.DEFAULT_BASE_URL
        if not key:
            self.lb_fetch.setText("先设置 API Key 再获取模型。")
            self.lb_fetch.setStyleSheet(f"color:{C['warn']}; background:transparent;")
            return
        self._fetching = True
        self._fetch_seq = getattr(self, "_fetch_seq", 0) + 1
        seq = self._fetch_seq
        self.btn_fetch.setEnabled(False)
        self.btn_fetch.setText("获取中…")
        self.lb_fetch.setText("正在向接入点查询可用模型…")
        self.lb_fetch.setStyleSheet(f"color:{C['text_dim']}; background:transparent;")

        # 兜底:万一请求卡死(DNS 不响应等),25 秒后强制解锁按钮,
        # 否则用户会像刚才那样一直盯着"获取中…"。
        def _guard():
            if self._fetching and seq == self._fetch_seq:
                self._on_models([], "超过 25 秒没有响应,可能是网络或接入点地址问题")
        QTimer.singleShot(25000, _guard)      # 在主线程调用,这里用 singleShot 是安全的

        def work():
            # 这里在后台线程,绝对不能碰任何控件 —— 只能把结果 emit 出去,
            # 由主线程的槽去更新界面。
            try:
                names, err = core.fetch_models(base, key)
            except Exception as e:                  # 兜底:线程里抛异常会被吞掉
                names, err = [], f"内部错误:{e}"
            self.models_ready.emit(names, err)

        threading.Thread(target=work, daemon=True).start()

    def _on_models(self, names, err):
        # 超时兜底已经处理过这次请求时,忽略迟到的结果(避免覆盖掉超时提示)
        if getattr(self, "_handled_seq", None) == self._fetch_seq and self._fetch_seq:
            return
        self._handled_seq = self._fetch_seq
        self._fetching = False
        self.btn_fetch.setEnabled(True)
        self.btn_fetch.setText("获取可用模型")
        if err:
            # 拉不到就退回常用列表 —— 不能让用户对着空下拉框发愁
            if self.cb_model.count() == 0:
                self._fill_models(self.cfg.get("model"))
            self.lb_fetch.setText(f"{err}")
            self.lb_fetch.setStyleSheet(f"color:{C['warn']}; background:transparent;")
            return
        self.cfg["model_cache"] = names
        cur = self.cb_model.selected()
        self._fill_models(cur)
        self._fill_pai_models(self.cb_pai_model.selected() or PAI_DEFAULT_MODEL)
        n_vl = sum(1 for m in names if "vl" in m.lower())
        self.lb_fetch.setText(
            f"接入点共 {len(names)} 个模型,其中 {n_vl} 个视觉模型(带 vl)。"
            "常用的已加粗置顶;可直接在框里打字搜索。")
        self.lb_fetch.setStyleSheet(f"color:{C['ok']}; background:transparent;")
        self._save_cfg()

    def _setup_shortcuts(self):
        """读取全局设置并把每个功能注册成可替换的 QShortcut。"""
        saved = core.load_state().get("shortcuts")
        self._shortcut_bindings = hotkeys.merged_bindings(saved)
        self._shortcut_specs = hotkeys.DEFINITION_BY_ID
        self._shortcut_handlers_map = self._shortcut_handlers()
        self._shortcut_objects = []
        self._rebuild_shortcuts()

        app = QApplication.instance()
        if app is not None:
            # 焦点在输入框时临时停用 A/D/Space/Delete 这类无修饰按键，
            # 否则设置了快捷键后会连正常打字也被截走。
            self._shortcut_focus_slot = self._on_shortcut_focus_changed
            app.focusChanged.connect(self._shortcut_focus_slot)
            self._shortcut_focus_connected = True
        self.pages.currentChanged.connect(
            lambda _index: self._update_shortcut_focus())

    def _shortcut_handlers(self):
        """功能 id -> 实际界面动作。所有可配置命令只在这里接线。"""
        return {
            # 全局与导航
            "settings.shortcuts": self._show_shortcut_settings,
            "global.check_updates": self._on_update_button,
            "nav.home": lambda: self._go(self.PAGE_HOME),
            "nav.mark": lambda: self._go(self.PAGE_MARK),
            "nav.prompt": lambda: self._go(self.PAGE_PROMPT),
            "nav.dataset": lambda: self._go(self.PAGE_DATASET),
            "nav.video": lambda: self._go(self.PAGE_VIDEO),
            "global.open_output": lambda: self._open(
                self.p_out.text() or self.cfg.get("out", "")),
            "global.open_preview": lambda: self._open(os.path.join(
                self.p_out.text() or self.cfg.get("out", ""), "vis")),
            "ui.zoom_in": lambda: self._zoom(1),
            "ui.zoom_out": lambda: self._zoom(-1),
            "ui.zoom_reset": self._zoom_reset,

            # 首页与自动标注
            "home.new_project": self._new_project,
            "home.rename_project": self._rename_project,
            "home.delete_project": self._del_project,
            "home.choose_images": self.p_images._browse,
            "home.choose_output": self.p_out._browse,
            "home.toggle_backup": self.cb_backup.toggle,
            "home.classes_all": lambda: self._check_all(True),
            "home.classes_none": lambda: self._check_all(False),
            "home.add_class": self._add_class_row,
            "home.import_classes": self._import_classes,
            "home.set_api_key": self.key_field._edit,
            "home.fetch_models": self.fetch_models,
            "home.toggle_advanced": self._toggle_adv,
            "home.toggle_skip_done": self.ck_skip.toggle,
            "home.preview": lambda: self.run_label(preview=True),
            "home.label_all": lambda: self.run_label(preview=False),
            "home.stop": self.runner.stop,
            "home.clear_log": self.log.clear,
            "home.copy_log": lambda: QApplication.clipboard().setText(
                self.log.toPlainText()),

            # 人工标注
            "mark.refresh": self.refresh_results,
            "mark.previous": lambda: self._step_vis(-1),
            "mark.next": lambda: self._step_vis(1),
            "mark.save": self.save_boxes,
            "mark.undo": self.canvas.undo,
            "mark.redo": self.canvas.redo,
            "mark.delete": self.canvas.delete_selected,
            "mark.clear": self._clear_this,
            "mark.confirm": self.canvas.confirm_pending,
            "mark.cancel": self.canvas.cancel_or_deselect,
            "mark.toggle_lock": self.ck_lock.toggle,
            "mark.toggle_autosave": self.ck_auto.toggle,
            "mark.reset_view": self.canvas.reset_zoom,
            "mark.nudge_left": lambda: self._nudge_or_step(-1, 0),
            "mark.nudge_right": lambda: self._nudge_or_step(1, 0),
            "mark.nudge_up": lambda: self._nudge_or_step(0, -1, -1),
            "mark.nudge_down": lambda: self._nudge_or_step(0, 1, 1),
            "mark.nudge_left_fast": lambda: self._nudge_or_step(-10, 0),
            "mark.nudge_right_fast": lambda: self._nudge_or_step(10, 0),
            "mark.nudge_up_fast": lambda: self._nudge_or_step(0, -10),
            "mark.nudge_down_fast": lambda: self._nudge_or_step(0, 10),

            # AI 补充提示词
            "prompt.images_all": lambda: self._pai_check_all(True),
            "prompt.images_none": lambda: self._pai_check_all(False),
            "prompt.images_invert": self._pai_invert,
            "prompt.images_changed": self._pai_check_changed,
            "prompt.refresh": self._pai_reload,
            "prompt.classes_all": lambda: self._pai_cls_all(True),
            "prompt.classes_none": lambda: self._pai_cls_all(False),
            "prompt.fetch_models": self._pai_fetch_models,
            "prompt.start": self._pai_run,
            "prompt.stop": lambda: setattr(self, "_pai_stop", True),
            "prompt.apply": self._pai_apply,
            "prompt.findings": self._pai_show_findings,

            # 导出数据集
            "dataset.choose_output": self.p_ds._browse,
            "dataset.generate": self.run_dataset,
            "dataset.open": lambda: self._open(self.p_ds.text()),

            # 视频切片
            "video.choose_file": self.p_video._browse,
            "video.choose_output": self.p_frames._browse,
            "video.play": self._toggle_vid_play,
            "video.set_start": lambda: self._set_vid_edge("a"),
            "video.set_end": lambda: self._set_vid_edge("b"),
            "video.full_range": lambda: self.vid_bar.set_range(
                0, self.vid_bar.duration()),
            "video.extract": self._run_extract,
            "video.stop": lambda: setattr(self, "_vid_stop", True),
            "video.open_output": lambda: self._open(self.p_frames.text()),
            "video.use_frames": self._use_frames,
            "video.refresh": self._reload_thumbs,
        }

    def _shortcut_page(self, scope):
        return {
            "home": self.PAGE_HOME,
            "mark": self.PAGE_MARK,
            "prompt": self.PAGE_PROMPT,
            "dataset": self.PAGE_DATASET,
            "video": self.PAGE_VIDEO,
        }.get(scope)

    def _shortcut_parent(self, spec):
        """页面命令只在对应页生效；画布命令只在画布有焦点时生效。"""
        if spec.get("target") == "canvas":
            return self.canvas, Qt.WidgetShortcut
        # 页面命令也挂在主窗口上，再由 _update_shortcut_focus 按当前页启停。
        # 这样焦点落在侧栏或状态栏时快捷键仍可用，同时不同页面可以复用按键。
        return self, Qt.WindowShortcut

    def _rebuild_shortcuts(self):
        for shortcut, _spec, _seq in getattr(self, "_shortcut_objects", []):
            shortcut.setEnabled(False)
            shortcut.setParent(None)
            shortcut.deleteLater()
        self._shortcut_objects = []

        for spec in hotkeys.SHORTCUT_DEFINITIONS:
            handler = self._shortcut_handlers_map.get(spec["id"])
            if handler is None:
                continue
            parent, context = self._shortcut_parent(spec)
            for seq in self._shortcut_bindings.get(spec["id"], []):
                seq = hotkeys.canonical_sequence(seq)
                if not seq:
                    continue
                shortcut = QShortcut(QKeySequence(seq), parent)
                shortcut.setContext(context)
                shortcut.setAutoRepeat(bool(spec.get("repeat")))
                shortcut.activated.connect(
                    lambda sid=spec["id"]: self._trigger_shortcut(sid))
                self._shortcut_objects.append((shortcut, spec, seq))
        self._update_shortcut_focus()
        self._update_shortcut_tooltips()

    def _trigger_shortcut(self, sid):
        spec = self._shortcut_specs.get(sid)
        if spec is None:
            return
        page = self._shortcut_page(spec.get("scope"))
        if page is not None and self.pages.currentIndex() != page:
            return
        handler = self._shortcut_handlers_map.get(sid)
        if handler is not None:
            handler()

    def _update_shortcut_focus(self):
        """文本框有焦点时，不让无修饰快捷键吞掉正常输入。"""
        if getattr(self, "_closing", False):
            return
        app = QApplication.instance()
        focus = app.focusWidget() if app is not None else None
        typing = hotkeys.is_text_input(focus)
        try:
            current = self.pages.currentIndex()
        except RuntimeError:
            return                  # Qt 正在销毁窗口，页面对象已经释放
        for shortcut, spec, seq in getattr(self, "_shortcut_objects", []):
            page = self._shortcut_page(spec.get("scope"))
            active_page = page is None or page == current
            typing_conflict = typing and hotkeys.is_unmodified_sequence(seq)
            try:
                shortcut.setEnabled(active_page and not typing_conflict)
            except RuntimeError:
                return

    def _on_shortcut_focus_changed(self, _old=None, _new=None):
        self._update_shortcut_focus()

    def _show_shortcut_settings(self):
        dlg = hotkeys.ShortcutSettingsDialog(self._shortcut_bindings, self)
        if dlg.exec() != QDialog.Accepted:
            return
        self._shortcut_bindings = dlg.bindings()
        core.save_state(shortcuts=self._shortcut_bindings)
        self._rebuild_shortcuts()
        self.status.showMessage("快捷键已保存并立即生效", 4000)

    def _nudge_or_step(self, dx, dy, step_image=0):
        """上下键沿用原交互：选中框时微调，没选框时翻图。"""
        if self.canvas.selected() >= 0:
            self.canvas.nudge_selected(dx, dy)
        elif step_image:
            self._step_vis(step_image)

    def _shortcut_text(self, sid):
        return hotkeys.binding_label(
            self._shortcut_bindings.get(sid, []), empty="未设置")

    def _update_shortcut_tooltips(self):
        def tip(widget, sid, text):
            if widget is not None:
                widget.setToolTip(f"{text}\n快捷键：{self._shortcut_text(sid)}")

        tip(getattr(self, "btn_shortcuts", None), "settings.shortcuts",
            "打开快捷键设置")
        if getattr(self, "btn_update", None) is not None:
            self._set_update_button(
                bool(self._latest_release.get("update_available")),
                checking=self._update_checking and self.btn_update.text() == "检测中…")
        tip(getattr(self, "btn_zoom_out", None), "ui.zoom_out", "界面缩小一档")
        tip(getattr(self, "btn_zoom_in", None), "ui.zoom_in", "界面放大一档")
        tip(getattr(self, "btn_prev", None), "mark.previous", "上一张图片")
        tip(getattr(self, "btn_next", None), "mark.next", "下一张图片")
        tip(getattr(self, "btn_undo", None), "mark.undo", "撤销框修改")
        tip(getattr(self, "btn_del", None), "mark.delete", "删除选中的框")
        tip(getattr(self, "btn_save", None), "mark.save", "保存所有改过的图片")
        tip(getattr(self, "btn_zoomfit", None), "mark.reset_view", "画布缩放复位")
        tip(getattr(self, "btn_preview", None), "home.preview", "运行预览标注")
        tip(getattr(self, "btn_all", None), "home.label_all", "运行全部标注")
        tip(getattr(self, "btn_stop", None), "home.stop", "停止标注任务")
        tip(getattr(self, "btn_pai_go", None), "prompt.start", "开始提示词分析")
        tip(getattr(self, "btn_pai_stop", None), "prompt.stop", "停止提示词分析")
        tip(getattr(self, "btn_pai_apply", None), "prompt.apply", "应用勾选的建议")
        tip(getattr(self, "btn_ds", None), "dataset.generate", "生成数据集")
        tip(getattr(self, "vid_play", None), "video.play", "播放或暂停选择区间")
        tip(getattr(self, "btn_vgo", None), "video.extract", "开始视频切片")
        tip(getattr(self, "btn_vstop", None), "video.stop", "停止视频切片")

    def _disable_wheel_on_inputs(self):
        """让所有 QComboBox / QSpinBox / QDoubleSpinBox 不再响应滚轮改值。
        滚页面时鼠标扫过这些控件会悄悄改掉设置,是个很容易踩的坑。"""
        n = 0
        for cls in (QComboBox, QSpinBox, QDoubleSpinBox):
            for w in self.findChildren(cls):
                no_wheel(w)
                n += 1
        return n

    def _warn_coord(self, *_):
        """非自动的坐标口径极容易把整批标签毁掉(框全挤到角落),必须显眼提示。"""
        v = self.cb_coord.currentData()
        if v == 0:
            self.lb_coord_warn.setText("")
            return
        self.lb_coord_warn.setText(
            "⚠ 已强制坐标口径。除非你确认自动判定错了,否则请改回「自动判定」—— "
            "设错会导致所有框位置错误(比如全部缩到右下角一个点)。")
        self.lb_coord_warn.setStyleSheet(
            f"color:{C['warn']}; background:transparent;")

    def _toggle_adv(self, *_):
        show = not self.adv.isVisible()
        self.adv.setVisible(show)
        self.btn_adv.setText("高级选项 ▴" if show else "高级选项 ▾")

    def _refresh_img_count(self, *_):
        p = self.p_images.text()
        if not p:
            self.p_images.set_status("未选择", "dim")
        elif not os.path.isdir(p):
            self.p_images.set_status("路径无效", "err")
        else:
            n = core.count_images(p)
            self.p_images.set_status(f"{n} 张图", "ok" if n else "err")

    # ================= 运行 =================
    def run_label(self, preview):
        if not self._require_project():
            return
        if self.runner.is_running():
            self.status.showMessage("已有任务在跑", 3000)
            return
        cfg = self._collect_from_ui()
        errs = core.validate(cfg)
        if errs:
            QMessageBox.warning(self, "配置有问题", "\n".join("· " + e for e in errs))
            return
        self.cfg = cfg
        self._save_cfg()

        n_img = core.count_images(cfg["images"])
        # 上锁的图不参与,张数要先扣掉 —— 否则提示"预览 20 张"而实际
        # 只标了几张新的(名额被上锁的图占了)
        n_lock = 0
        if self._locks:
            names = {os.path.basename(p)
                     for p in core.list_source_images(cfg["images"])}
            n_lock = len(names & self._locks)
            n_img = max(0, n_img - n_lock)
        limit = cfg["preview_limit"] if preview else 0
        n_run = min(limit, n_img) if limit else n_img
        if n_img == 0 and n_lock:
            QMessageBox.information(
                self, "都上锁了",
                f"{n_lock} 张图全都上锁了,没有要标的。\n\n"
                "想重新标某张,去标注页把它的锁取消掉。")
            return

        if not preview:
            tiles = cfg.get("tiles") or ""
            mult = 1
            if tiles:
                gx, gy = tiles.lower().split("x")
                mult = int(gx) * int(gy)
            msg = (f"要对 {n_run} 张图跑全量标注。\n\n"
                   f"后端:{'云端 API' if cfg['backend']=='api' else '本地 GPU'}\n"
                   f"模型:{cfg['model']}\n")
            if cfg["backend"] == "api":
                msg += f"预计 API 调用:约 {n_run*mult} 次(会产生费用)\n"
            msg += "\n建议先跑预览确认框和类别都对,再跑全量。要继续吗?"
            if QMessageBox.question(self, "确认标注全部", msg,
                                    QMessageBox.Yes | QMessageBox.No,
                                    QMessageBox.No) != QMessageBox.Yes:
                return

        # 先切任务、清日志,再做备份 —— 否则 clear() 会把备份提示冲掉
        self._task = "preview" if preview else "all"
        self.log.clear()

        # 备份旧结果:上一次的标签留着会和新的混在一起
        if cfg.get("backup_old") and core.has_results(cfg["out"]):
            try:
                dst = core.backup_dir(cfg["out"])
                if dst:
                    self.on_log(f"↳ 上次结果已备份到 {os.path.basename(dst)}/")
                    # 备份是把整个 out/ 改名,上锁的标签会跟着被搬走。
                    # 复制回来,否则界面上看就是"我改好的框不见了"。
                    if self._locks:
                        nb = core.restore_locked_labels(
                            dst, cfg["out"], self._locks)
                        if nb:
                            self.on_log(f"↳ 已保住 {nb} 张上锁的标签")
            except Exception as e:
                self.on_log(f"⚠ 备份失败(继续跑): {e}")

        os.makedirs(os.path.join(cfg["out"], "labels"), exist_ok=True)
        os.makedirs(os.path.join(cfg["out"], "vis"), exist_ok=True)

        # 上锁清单交给脚本:这些图跳过,而且不占预览张数的名额
        lf = ""
        if self._proj and self._locks:
            lf = core.locks_path(core.project_dir(self._proj))
        args = core.build_label_args(cfg, limit=limit, locks_file=lf)
        self.on_log(f"$ python autolabel_qwen.py {_shorten(args)}")
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.lb_prog.setText(
            f"准备处理 {n_run} 张…"
            + (f"({n_lock} 张已上锁,跳过)" if n_lock else ""))
        self._set_running(True)
        self.runner.start(core.script_path("autolabel_qwen.py"), args,
                          core.child_env(cfg), core.ROOT)

    def run_dataset(self):
        if not self._require_project():
            return
        if self.runner.is_running():
            self.status.showMessage("已有任务在跑", 3000)
            return
        cfg = self._collect_from_ui()
        errs = core.validate(cfg)
        if errs:
            QMessageBox.warning(self, "配置有问题", "\n".join("· " + e for e in errs))
            return
        if not core.has_results(cfg["out"]):
            QMessageBox.warning(self, "还没有标签",
                                f"{cfg['out']}/labels 里没有标签文件。\n先去「标注」页跑一次。")
            return
        self.cfg = cfg
        self._save_cfg()
        self._task = "dataset"
        self.log_ds.clear()
        # dataset 是复制累积的,不清会混入上一次的类别体系
        if os.path.isdir(os.path.join(cfg["dataset"], "images")):
            r = QMessageBox.question(
                self, "已存在数据集",
                f"{cfg['dataset']} 里已经有数据集了。\n\n"
                "它是累积复制的,直接生成会把旧类别的标签混进来。\n"
                "要先把旧的改名备份吗?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Yes)
            if r == QMessageBox.Cancel:
                return
            if r == QMessageBox.Yes:
                try:
                    dst = core.backup_dir(cfg["dataset"])
                    if dst:
                        self._ds_log(f"↳ 旧数据集已备份到 {os.path.basename(dst)}/")
                except Exception as e:
                    self._ds_log(f"⚠ 备份失败: {e}")

        args = core.build_dataset_args(cfg)
        self._ds_log(f"$ python build_dataset.py {_shorten(args)}")
        self._set_running(True)
        self.runner.start(core.script_path("build_dataset.py"), args,
                          core.child_env(cfg), core.ROOT)

    def _set_running(self, on):
        self.btn_preview.setEnabled(not on)
        self.btn_all.setEnabled(not on)
        self.btn_ds.setEnabled(not on)
        self.btn_stop.setEnabled(on and self._task != "dataset")
        self.status.showMessage("运行中…" if on else "就绪")

    def on_log(self, ln):
        box = self.log_ds if self._task == "dataset" else self.log
        # 关键行上色:错误红、完成绿、警告黄
        s = ln.rstrip()
        low = s.lower()
        color = None
        if s.startswith("✗") or "失败" in s or "error" in low or "traceback" in low:
            color = C["err"]
        elif s.startswith("完成") or s.startswith("数据集就绪") or s.startswith("✓"):
            color = C["ok"]
        elif s.startswith("⚠") or s.startswith("↳") or "warn" in low:
            color = C["warn"]
        if color:
            box.appendHtml(f'<span style="color:{color}">{_esc(s)}</span>')
        else:
            box.appendPlainText(s)
        box.moveCursor(QTextCursor.End)

    def _ds_log(self, s):
        self.log_ds.appendPlainText(s)
        self.log_ds.moveCursor(QTextCursor.End)

    def on_progress(self, done, total):
        if total > 0:
            self.bar.setRange(0, total)
            self.bar.setValue(done)
            self.lb_prog.setText(f"{done} / {total} 张")

    def on_finished(self, code):
        was = self._task
        self._task = None
        self._set_running(False)
        if code == -1:
            self.on_log("■ 已停止")
            self.status.showMessage("已停止", 5000)
        elif code == 0:
            self.status.showMessage("完成", 5000)
            if was in ("preview", "all"):
                # 这一刻磁盘上的标签就是纯 AI 的结果,存成基线快照。
                # 之后你手动改、保存多少次都不动它 —— 「AI 补充提示词」
                # 永远拿这一版做对比,不会因为存了多次而搞混。
                self._snapshot_baseline()
                self.refresh_results()
                QTimer.singleShot(300, lambda: self._go(self.PAGE_MARK))
        else:
            self.on_log(f"✗ 进程退出码 {code}")
            self.status.showMessage(f"失败(退出码 {code})", 8000)

    def _snapshot_baseline(self):
        """自动标注跑完:把 labels/ 存成"AI 原始版"快照。"""
        if not self._proj:
            return
        try:
            pd = core.project_dir(self._proj)
            out = self.p_out.text() or self.cfg["out"]
            n = core.snapshot_baseline(pd, out)
            if n:
                self.on_log(f"· 已记录 AI 原始版({n} 张),"
                            f"之后的手工修改都会和这一版对比")
        except Exception as e:
            self.on_log(f"· 记录 AI 原始版失败:{e}(不影响标注)")

    # ================= 结果页 =================
    def refresh_results(self, *_):
        """刷新标注页。列表 = 待标注目录里的【所有图片】,
        没跑过 AI 的也列出来 —— 那样就能纯手动标。"""
        out = self.p_out.text() or self.cfg["out"]
        imgs_dir = self.p_images.text() or self.cfg["images"]
        rows = core.list_editable_images(imgs_dir, out)
        if not rows:
            # 原图目录空/不存在时,退回只看已标注的(至少别是一片空白)
            rows = [(os.path.basename(f), f, core.label_path_for(out, f),
                     len(core.read_boxes(core.label_path_for(out, f))))
                    for f in core.list_vis_images(out)]
        cur = self.lst_vis.currentRow()
        self.lst_vis.blockSignals(True)
        self.lst_vis.clear()
        n_done = 0
        for name, p, lb, n in rows:
            it = QListWidgetItem(name)
            if n >= 0:
                n_done += 1
            self.lst_vis.addItem(it)
        self.lst_vis.blockSignals(False)
        files = [r[1] for r in rows]
        self._vis_files = files
        self._vis_labels = [r[2] for r in rows]     # 每张图对应的标签文件
        self._vis_counts = [r[3] for r in rows]     # 磁盘上的框数(-1 = 没标签文件)
        self.lb_vis.setText(f"图片 ({len(files)},已标 {n_done})")
        self._mark_lock_in_list()     # 上锁的加个 🔒
        self._recolor_vis()

        # 工具条的类别下拉:和类别表保持一致
        classes = self._classes_from_table()
        keep = self.cb_newcls.currentData()
        self.cb_newcls.load(
            [(i, f"{i}  {c['name']}", False) for i, c in enumerate(classes)],
            current=keep if keep is not None else 0,
            colors=[palette()[i % len(palette())] for i in range(len(classes))])

        if files:
            row = min(max(cur, 0), len(files) - 1)
            self._cur_row = row
            self.lst_vis.setCurrentRow(row)
            self._show_vis(row)        # 首次进来 currentRow 没变时不会触发信号
        else:
            self.canvas.load("", [], palette(), [])
            self.lb_imginfo.setText("")
            self._dirty = False
            self._update_save_state()

        self._refresh_stats_only()

    def _recolor_vis(self):
        """给图片列表上色,三种状态一眼可分:

          灰  = 还没有任何框(没标签文件,或标签文件是空的)
          黄  = 改过但还没保存(在待保存表里,或就是当前正在改的这张)
          白  = 已保存,磁盘上有框

        注意"改了没保存"要优先判断:一张已保存的图被改动之后,
        它当然还在磁盘上有框,但此刻更重要的信息是"你还没存"。
        """
        labels = getattr(self, "_vis_labels", [])
        counts = getattr(self, "_vis_counts", [])
        for i in range(self.lst_vis.count()):
            it = self.lst_vis.item(i)
            if it is None:
                continue
            lb = labels[i] if i < len(labels) else ""
            n_disk = counts[i] if i < len(counts) else -1
            # 这张图是不是有未保存的改动
            if lb and lb in self._pending:
                n_now = len(self._pending[lb])
                dirty = True
            elif lb and self._dirty and lb == self._cur_label:
                n_now = len(self.canvas.boxes())
                dirty = True
            else:
                n_now = n_disk
                dirty = False
            if dirty:
                it.setForeground(QColor(C["warn"]))
                it.setToolTip(f"{n_now} 个框 · 改过还没保存")
            elif n_now <= 0:
                it.setForeground(QColor(C["text_faint"]))
                it.setToolTip("还没有框" if n_now == 0 else "还没标注")
            else:
                it.setForeground(QColor(C["text"]))
                it.setToolTip(f"{n_now} 个框 · 已保存")

    def _refresh_stats_only(self):
        """只重算右侧统计(保存框之后要立刻反映新数字)。"""
        out = self.p_out.text() or self.cfg["out"]
        classes = self._classes_from_table()
        st = core.read_label_stats(out, classes)
        self.tbl_stat.setRowCount(0)
        zero = []
        for pc in st["per_class"]:
            r = self.tbl_stat.rowCount()
            self.tbl_stat.insertRow(r)
            self.tbl_stat.setItem(r, 0, QTableWidgetItem(str(pc["id"])))
            it = QTableWidgetItem(pc["name"])
            rgb = palette()[pc["id"] % len(palette())]
            it.setIcon(color_dot(rgb))
            # 类别名用它自己的框颜色,和图上的框对应得更直接
            it.setForeground(QColor(*rgb))
            if pc["desc"]:
                it.setToolTip(pc["desc"])
            self.tbl_stat.setItem(r, 1, it)
            cnt = QTableWidgetItem(str(pc["count"]))
            cnt.setTextAlignment(Qt.AlignCenter)
            if pc["on"] and pc["count"] == 0:
                cnt.setForeground(QColor(C["warn"]))
                zero.append(pc["name"])
            self.tbl_stat.setItem(r, 2, cnt)
        parts = [f"{st['n_files']} 张已标注,共 {st['total_boxes']} 个框"]
        if st["n_empty"]:
            parts.append(f"{st['n_empty']} 张没有任何框")
        if zero:
            parts.append("这些勾选的类一个都没标到,建议改描述:" + "、".join(zero))
        # 坐标口径错这种"标签有内容但全废"的情况最要紧,放最前面并标红
        if st.get("warn"):
            parts.insert(0, "⚠ " + st["warn"])
        self.lb_sum.setText(" · ".join(parts))
        bad = bool(st.get("warn"))
        self.lb_sum.setStyleSheet(
            f"color:{C['err'] if bad else (C['warn'] if zero else C['text_dim'])};"
            " background:transparent;")

    def _show_vis(self, row):
        """切换图片:载入【原图】+ 可编辑的框。

        注意底图必须用原图,不能用 out/vis 里那张已经画好框的预览图 ——
        否则会出现两层框(画上去的 + 我们再画的)。
        """
        fs = getattr(self, "_vis_files", [])
        if not fs or row < 0 or row >= len(fs):
            return
        # 有画好还没按回车的框,先把它落下 —— 你画它是有意的,
        # 不该因为翻页就白画一次
        if self.canvas.has_pending():
            self.canvas.confirm_pending()
        # 切图不弹窗打断:先把当前改动收进待保存表,想走时再统一处理
        self._stash_current()
        vis = fs[row]
        out = self.p_out.text() or self.cfg["out"]
        # 列表里存的已经是原图路径;但如果退回了"只看已标注"模式,
        # 里面是 out/vis 的图,那还得找回原图,否则会画出两层框。
        if os.path.normpath(vis).startswith(
                os.path.normpath(os.path.join(out, "vis"))):
            src = core.source_image_for(
                vis, self.p_images.text() or self.cfg["images"])
        else:
            src = vis
        base = src or vis
        self._cur_row = row
        self._cur_label = core.label_path_for(out, vis)
        # 这张图之前改过还没存?用改过的版本,别拿磁盘上的旧内容盖掉
        boxes = self._pending.get(self._cur_label)
        if boxes is None:
            boxes = core.read_boxes(self._cur_label)
        classes = self._classes_from_table()
        names = [c["name"] for c in classes]
        self.canvas.load(base, boxes, palette(), names)
        self._dirty = False
        self._sync_lock_ui()          # 工具条上的锁跟着这张图
        self._update_save_state()
        from PIL import Image
        try:
            w, h = Image.open(base).size
            dim = f"  {w}×{h}"
        except Exception:
            dim = ""
        warn = "" if src else "  ·  ⚠ 没找到原图,显示的是带框预览图(会有两层框)"
        self.lb_imginfo.setText(
            f"{os.path.basename(vis)}{dim}  ·  {len(boxes)} 个框  ·  "
            f"第 {row+1}/{len(fs)} 张{warn}")

    # ---------------- 框编辑 ----------------
    def _on_newcls(self, *_):
        """工具条里的类别下拉:选中了某个框就改它的类别,否则只影响新框。"""
        cid = self.cb_newcls.currentData()
        if cid is None:
            return
        self.canvas.set_new_class(cid)
        if self.canvas.selected() >= 0:
            self.canvas.set_selected_class(cid)

    def _on_pending(self, has):
        """画好待确认时给一句提示 —— 不然不知道还要按回车。"""
        if has:
            self.status.showMessage("按回车确定这个框,按 Esc 取消", 6000)
        else:
            self.status.clearMessage()

    def _on_canvas_zoom(self, z):
        """画布缩放变了:更新工具条上的倍数。"""
        self.lb_zoomlv.setText(f"{int(round(z * 100))}%")

    def _on_box_selected(self, i):
        self.btn_del.setEnabled(i >= 0)
        if i >= 0:
            b = self.canvas.boxes()[i]
            j = self.cb_newcls.findData(b["cid"])
            if j >= 0:
                self.cb_newcls.blockSignals(True)
                self.cb_newcls.setCurrentIndex(j)
                self.cb_newcls.blockSignals(False)

    def _on_boxes_changed(self):
        self._dirty = True
        # 手动动过框就自动上锁 —— 你花时间改的东西,默认不该被重跑覆盖。
        # 想让它重新参与自动标注,把工具条上的锁取消掉即可。
        self._auto_lock_current()
        self._update_save_state()
        self._recolor_vis()          # 这张图立刻变黄:改了还没存
        n = len(self.canvas.boxes())
        txt = self.lb_imginfo.text()
        # 只更新"N 个框"那一段,其余信息保留
        self.lb_imginfo.setText(
            re.sub(r"·\s*\d+ 个框", f"·  {n} 个框", txt) if "个框" in txt else txt)

    # ---------------- 上锁 ----------------
    def _cur_img(self):
        """当前正在看的图片路径(没有就返回 "")。"""
        i = self.lst_vis.currentRow()
        files = getattr(self, "_vis_files", [])
        return files[i] if 0 <= i < len(files) else ""

    def _auto_lock_current(self):
        """手动改过 -> 自动上锁。已经锁着就什么都不做。"""
        p = self._cur_img()
        if not p or not self._proj:
            return
        k = core.lock_key(p)
        if k in self._locks:
            return
        self._locks.add(k)
        core.save_locks(core.project_dir(self._proj), self._locks)
        # 同步工具条上的勾(别触发 toggled 又存一次)
        self.ck_lock.blockSignals(True)
        self.ck_lock.setChecked(True)
        self.ck_lock.blockSignals(False)
        self._mark_lock_in_list()
        self.status.showMessage(
            f"{os.path.basename(p)} 已自动上锁,重跑标注不会覆盖它", 4000)

    def _on_lock_toggle(self, on):
        """工具条上手动勾/取消锁。"""
        p = self._cur_img()
        if not p or not self._proj:
            return
        k = core.lock_key(p)
        if on:
            self._locks.add(k)
        else:
            self._locks.discard(k)
        core.save_locks(core.project_dir(self._proj), self._locks)
        self._mark_lock_in_list()
        self.status.showMessage(
            f"{os.path.basename(p)} " + ("已上锁,重跑不会动它" if on
                                         else "已解锁,重跑会重新标它"), 4000)

    def _sync_lock_ui(self):
        """切换图片时更新工具条上的锁状态。"""
        p = self._cur_img()
        self.ck_lock.blockSignals(True)
        self.ck_lock.setChecked(bool(p) and core.lock_key(p) in self._locks)
        self.ck_lock.setEnabled(bool(p))
        self.ck_lock.blockSignals(False)

    def _mark_lock_in_list(self):
        """上锁的图在名字右边加个锁图案,一眼就能看出哪些受保护。"""
        files = getattr(self, "_vis_files", [])
        for i in range(min(self.lst_vis.count(), len(files))):
            it = self.lst_vis.item(i)
            base = os.path.basename(files[i])
            locked = core.lock_key(files[i]) in self._locks
            it.setText(f"{base}  🔒" if locked else base)
            it.setToolTip(("已上锁:重跑标注会跳过这张\n" if locked else "")
                          + base)

    # ---------------- 项目 ----------------
    def _cfg_path(self):
        """当前项目的配置文件路径。没选项目时返回 ""(不存盘)。"""
        return core.project_config_path(self._proj) if self._proj else ""

    def _load_cfg(self):
        """读配置:项目内容 + 全局的账号设置(Key/接入点/模型缓存)。"""
        cfg = (core.load_config(self._cfg_path()) if self._proj
               else core.blank_project_config())
        g = core.load_globals()
        for k in core.GLOBAL_KEYS:
            if g.get(k):
                cfg[k] = g[k]        # 全局的优先:它才是最新填的那份
        return cfg

    def _save_cfg(self, allow_clear=()):
        """存配置。

        分两半存:
          - API Key / 接入点 / 模型缓存 -> 全局(和项目无关)
          - 其余(图片目录、类别表…)     -> 当前项目

        Key 必须存全局。以前全部塞进项目配置里,结果"还没建项目就填 key"
        没地方存、"删掉项目"连 key 一起删掉 —— 那就是 key 时不时丢的原因。
        """
        cfg = self._collect_from_ui()
        core.save_globals(cfg, allow_clear=allow_clear)   # 这一步不需要项目
        p = self._cfg_path()
        if p:
            core.save_project_config(cfg, p)

    def _refresh_projects(self):
        """重填项目下拉。没有项目时只有一条占位提示。"""
        self.cb_proj.blockSignals(True)
        self.cb_proj.clear()
        ps = core.list_projects()
        if not ps:
            self.cb_proj.addItem("(还没有项目)", None)
        for p in ps:
            n = p["name"]
            # 下拉里只显示项目名。已标多少张不写在这里 ——
            # 那是会变的进度,挂在名字后面会让人以为它是名字的一部分。
            self.cb_proj.addItem(n, n)
        i = self.cb_proj.findData(self._proj)
        self.cb_proj.setCurrentIndex(max(0, i))
        self.cb_proj.blockSignals(False)
        self._update_proj_hint()
        self._update_gate()

    def _update_proj_hint(self):
        if self._proj:
            n = len(self._classes_from_table())
            miss = []
            if not self.p_images.text().strip():
                miss.append("选图片文件夹")
            if not n:
                miss.append("填类别表")
            tail = ("  还需要:" + "、".join(miss)) if miss else ""
            self.lb_proj.setText(
                f"当前项目:{self._proj}({n} 个类别)" + tail)
        else:
            self.lb_proj.setText(
                "先新建一个项目再开始 —— 每个项目有自己的图片目录和类别表,互不干扰。")

    def _require_project(self):
        """需要项目才能做的操作,先挡一道。"""
        if self._proj:
            return True
        QMessageBox.information(
            self, "先建个项目",
            "所有操作都属于某个项目。\n\n"
            "点「新建项目」起个名字,然后选图片文件夹、填类别表就能开始。")
        return False

    def _update_gate(self):
        """没有选中项目时,把会改动内容的操作全禁掉。

        一个项目对应一套内容。没项目就编辑,那些改动无处存放,
        跑出来的标签也不知道算谁的 —— 所以直接不让点,比事后报错清楚。
        """
        on = bool(self._proj)
        for wg in (self.p_images, self.p_out, self.p_ds, self.tbl,
                   self.ed_neg, self.cb_backup, self.btn_preview,
                   self.btn_all, self.btn_ds):
            try:
                wg.setEnabled(on)
            except Exception:
                pass
        for b in getattr(self, "_cls_btns", []):
            b.setEnabled(on)
        # 标注页也一样:没项目就没有图可标
        for wg in (self.canvas, self.lst_vis, self.btn_save, self.btn_del,
                   self.btn_undo, self.btn_clear, self.cb_newcls,
                   self.ck_auto, self.btn_prev, self.btn_next):
            try:
                wg.setEnabled(on)
            except Exception:
                pass

    def _on_proj_switch(self, _i=0):
        """切项目:先保存当前的,再把另一份配置整套读进界面。"""
        want = self.cb_proj.currentData()
        if want == self._proj or want is None:
            return
        if not self._confirm_discard():          # 有没保存的框先问一句
            self._refresh_projects()             # 用户取消 -> 下拉拨回去
            return
        try:
            self._save_cfg()                     # 存住当前项目
        except Exception:
            pass
        self._switch_to(want)
        self.status.showMessage(f"已切到项目「{want}」", 3000)

    def _new_project(self):
        name, ok = QInputDialog.getText(self, "新建项目", "项目名:")
        if not ok:
            return
        err = core.check_project_name(name)
        if err:
            QMessageBox.warning(self, "名字不合法", err)
            return
        if not self._confirm_discard():      # 当前项目有没保存的框,先问
            return
        try:
            self._save_cfg()                 # 存住当前项目再走
        except Exception:
            pass
        # 内容全部清空,只把"模型与性能"那一块带过去(接入点/密钥/并发这些
        # 是账号和机器属性,跟数据集无关,每次重填没意义)
        try:
            core.create_project(name, carry_from=self._collect_from_ui())
        except Exception as e:
            QMessageBox.warning(self, "建不了", str(e))
            return
        self._switch_to(name.strip())
        self.status.showMessage(
            f"项目「{self._proj}」建好了。类别表和图片目录是空的,选一下就能开始", 7000)

    def _switch_to(self, name):
        """真正切到某个项目:读它的配置、重置标注页状态。"""
        self._proj = name
        core.save_state(project=name)
        self.cfg = self._load_cfg()      # 含全局的 Key/接入点
        self._apply_cfg(self.cfg)
        self._refresh_projects()
        self._pending.clear()
        self._dirty = False
        self.canvas.load("", [], [], [])     # 清掉画布上一个项目的图和框
        self._cur_label = ""
        self._cur_row = 0
        self._update_save_state()
        self.refresh_results()

    def _rename_project(self):
        if not self._proj:
            QMessageBox.information(self, "改不了", "还没有项目,先新建一个。")
            return
        name, ok = QInputDialog.getText(self, "重命名项目", "新名字:", text=self._proj)
        if not ok or name.strip() == self._proj:
            return
        try:
            self._save_cfg()
            core.rename_project(self._proj, name)
        except Exception as e:
            QMessageBox.warning(self, "改不了", str(e))
            return
        old, self._proj = self._proj, name.strip()
        core.save_state(project=self._proj)
        # 输出目录跟着项目目录走,重命名后要修正,否则还指向旧路径
        c = self._collect_from_ui()
        for k in ("out", "dataset"):
            if core.project_dir(old) in c.get(k, ""):
                c[k] = c[k].replace(core.project_dir(old), core.project_dir(self._proj))
        self.cfg = c
        self._apply_cfg(c)
        self._save_cfg()
        self._refresh_projects()
        self.refresh_results()
        self.status.showMessage(f"已改名为「{self._proj}」", 3000)

    def _del_project(self):
        name = self.cb_proj.currentData()
        if not name:
            QMessageBox.information(self, "删不了", "还没有项目可删。")
            return
        n_lb = core.project_label_count(name)
        r = QMessageBox.question(
            self, "删除项目",
            f"要删掉项目「{name}」吗?\n\n"
            f"会一起删掉它的配置"
            + (f"、{n_lb} 个标签文件和导出的数据集" if n_lb else "和输出目录") + "。\n"
            "你的原始图片不受影响。这个操作不能撤销。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        try:
            core.delete_project(name)
        except Exception as e:
            QMessageBox.warning(self, "删不了", str(e))
            return
        if self._proj == name:
            # 删的是当前项目:还有别的就切过去,没有就回到"未选择"状态
            left = core.list_projects()
            self._switch_to(left[0]["name"] if left else None)
        else:
            self._refresh_projects()
        self.status.showMessage(f"项目「{name}」已删除", 4000)

    def _clear_this(self):
        """清空当前这张图的所有框。误点了可以 Ctrl+Z 撤销,所以不弹窗确认。"""
        n = len(self.canvas.boxes())
        if not n:
            self.status.showMessage("这张图本来就没有框", 2500)
            return
        self.canvas.clear_boxes()
        self.status.showMessage(f"已清空 {n} 个框(Ctrl+Z 可撤销,保存后才会写入文件)", 5000)

    def _stash_current(self):
        """把当前图片的改动记进待保存表(还没落盘)。"""
        if self._dirty and self._cur_label:
            self._pending[self._cur_label] = self.canvas.boxes()
            self._dirty = False
            self._recolor_vis()      # 改动挪进待保存表了,颜色保持黄色

    def _n_pending(self):
        return len(self._pending) + (1 if self._dirty else 0)

    def _update_save_state(self):
        n = self._n_pending()
        self.btn_save.setEnabled(n > 0)
        self.btn_undo.setEnabled(self.canvas.can_undo())
        self.btn_save.setText(f"全部保存 ({n})" if n else "全部保存")

    def save_boxes(self):
        """把所有改过的图片一次性写回 YOLO 标签文件。"""
        self._stash_current()
        if not self._pending:
            self.status.showMessage("没有需要保存的改动", 2500)
            return
        n_files = n_box = 0
        failed = []
        labels = getattr(self, "_vis_labels", [])
        for lb, boxes in list(self._pending.items()):
            try:
                n = core.write_boxes(lb, boxes)
                n_box += n
                n_files += 1
                self._pending.pop(lb, None)
                # 磁盘上的框数变了,缓存跟着更新,列表颜色才能转成白色
                if lb in labels:
                    self._vis_counts[labels.index(lb)] = n
            except Exception as e:
                failed.append(f"{os.path.basename(lb)}: {e}")
        self._update_save_state()
        self._recolor_vis()          # 存完:黄 -> 白(没有框的仍是灰)
        if failed:
            QMessageBox.warning(
                self, "部分保存失败",
                "这些文件写不进去:\n" + "\n".join(failed[:6]))
        self.status.showMessage(
            f"已保存 {n_files} 张图的 {n_box} 个框" if n_files else "保存失败", 4000)
        self._refresh_stats_only()

    # ---------------- 自动保存 ----------------
    def _on_autosave_toggle(self, on):
        self.sp_auto.setEnabled(on)
        if on:
            self._auto_timer.start(max(1, self.sp_auto.value()) * 60_000)
            self.status.showMessage(
                f"自动保存已开启,每 {self.sp_auto.value()} 分钟一次", 3000)
        else:
            self._auto_timer.stop()
            self.status.showMessage("自动保存已关闭", 2500)
        try:
            self._save_cfg()
        except Exception:
            pass

    def _on_autosave_interval(self, v):
        if self.ck_auto.isChecked():
            self._auto_timer.start(max(1, v) * 60_000)   # 改间隔后重新计时

    def _autosave_tick(self):
        """定时器到点:有改动才写,没改动不打扰。"""
        if self._n_pending() == 0:
            return
        self.save_boxes()

    def _confirm_discard(self):
        """有未保存的修改时先问一句。返回 True = 可以继续切换。

        注意:切换图片时不算"要丢弃" —— 改动会先进待保存表,
        只有关窗口/换目录这种真要走人的时候才问。
        """
        if self._n_pending() == 0:
            return True
        n = self._n_pending()
        r = QMessageBox.question(
            self, "还没保存",
            f"有 {n} 张图片的框改了但没保存。\n\n"
            "「保存」全部写回标签文件,「丢弃」放弃这些修改。",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save)
        if r == QMessageBox.Save:
            self.save_boxes()
            return True
        if r == QMessageBox.Discard:
            self._pending.clear()
            self._dirty = False
            self._update_save_state()
            self._recolor_vis()      # 放弃改动:黄色退回原来的颜色
            return True
        return False

    def _count_boxes_for(self, vis_path):
        base = os.path.splitext(os.path.basename(vis_path))[0]
        lb = os.path.join(self.p_out.text() or self.cfg["out"], "labels", base + ".txt")
        try:
            with open(lb, encoding="utf-8") as f:
                return len([l for l in f.read().splitlines() if l.strip()])
        except Exception:
            return 0

    def _step_vis(self, d):
        n = self.lst_vis.count()
        if n:
            self.lst_vis.setCurrentRow((self.lst_vis.currentRow() + d) % n)

    # ================= 杂项 =================
    def _open(self, path):
        if path and os.path.isdir(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            self.status.showMessage(f"目录还不存在:{path}", 4000)

    # 界面缩放的档位。1.0 = 原始比例(默认),用右上角的 - / + 手动切。
    # 之所以不再跟着窗口尺寸自动变:全屏时自动放大到 1.6 倍,输入框里的
    # 长路径反而会被挤得看不全，所以缩放应由用户决定。
    # 缩放该由你决定,而不是软件猜。
    ZOOM_STEPS = (0.9, 1.0, 1.1, 1.25, 1.4, 1.6)

    def _startup_size(self):
        """启动窗口大小:按屏幕可用区域的八成开,再夹在合理范围里。

        不写死一个大尺寸 —— 1600x1000 在 1366x768 的笔记本上会超出屏幕,
        标题栏被顶到看不见。按屏幕比例算才两边都合适。
        上限 1800x1150:再大就只是留白变多,信息密度并没有提高。
        """
        w, h = 1480, 950          # 拿不到屏幕信息时的默认值(比原来的 1180x780 大)
        try:
            app = QApplication.instance()
            scr = app.primaryScreen() if app else None
            if scr is not None:
                g = scr.availableGeometry()
                if g.width() > 0 and g.height() > 0:
                    w = int(g.width() * 0.8)
                    h = int(g.height() * 0.8)
        except Exception:
            pass
        w = max(900, min(w, 1800))
        h = max(700, min(h, 1150))
        return w, h

    def _zoom_reset(self):
        """回到 100%(原始比例)。"""
        if abs(self._ui_k - 1.0) < 0.01:
            return
        self._ui_k = 1.0
        self._apply_scale()
        self.lb_zoom.setText("100%")
        self.status.showMessage("界面缩放回到 100%", 2500)
        core.save_state(zoom=1.0)

    def _zoom(self, d):
        """手动调界面缩放。d=+1 放大一档,-1 缩小一档。"""
        steps = list(self.ZOOM_STEPS)
        # 找当前档位,再往前/后走一格
        cur = min(range(len(steps)), key=lambda i: abs(steps[i] - self._ui_k))
        i = max(0, min(len(steps) - 1, cur + d))
        if steps[i] == self._ui_k:
            self.status.showMessage(
                "已经是最大了" if d > 0 else "已经是最小了", 2500)
            return
        self._ui_k = steps[i]
        self._apply_scale()
        self.lb_zoom.setText(f"{int(self._ui_k * 100)}%")
        self.status.showMessage(f"界面缩放 {int(self._ui_k * 100)}%", 2500)
        core.save_state(zoom=self._ui_k)      # 记住,下次打开还是这个大小

    def _apply_scale(self):
        app = QApplication.instance()
        if app is None:
            return
        k = self._ui_k
        # 关键:QSS 的 padding/min-height 和 app.font() 的字号都要按同一个 k 走。
        # 只放大字号不放大内边距,字就会顶到框边被裁成"一截一截的横线";
        # 反过来只放大框、字不变,就是之前"面板大了字显小"的问题。
        app.setStyleSheet(stylesheet(k))
        f = app.font()
        f.setPointSizeF(max(9.5, self._base_pt * k))
        app.setFont(f)

        # QSS 管不到用代码写死的尺寸,这些得手动跟着放大,
        # 否则字变大了、格子没变大,文字就会被挤或被截断。
        def sz(v):
            return int(round(v * k))

        try:
            self.side.setFixedWidth(sz(184))
            self.tbl.setColumnWidth(0, sz(48))
            self.tbl.setColumnWidth(1, sz(108))
            self.tbl.setColumnWidth(3, sz(58))
            self.tbl.verticalHeader().setDefaultSectionSize(sz(32))
            self.tbl_stat.setColumnWidth(0, sz(28))
            self.tbl_stat.setColumnWidth(2, sz(52))
            self.tbl_stat.verticalHeader().setDefaultSectionSize(sz(27))
            self.ed_neg.setFixedHeight(sz(58))
            self.lst_vis.setMinimumWidth(sz(150))
            self.cb_newcls.setMinimumWidth(sz(140))
            self.cb_proj.setMinimumWidth(sz(190))
            for r in range(self.tbl.rowCount()):
                b = self.tbl.cellWidget(r, 3)
                if b is not None:
                    b.setFixedHeight(sz(24))
            for pk in (self.p_images, self.p_out, self.p_ds,
                       getattr(self, "p_video", None),
                       getattr(self, "p_frames", None)):
                if pk is not None:
                    pk.set_scale(k)
            for row in self.findChildren(FieldRow):
                row.set_scale(k)
        except Exception:
            pass          # 缩放只是观感,再怎么也不该让界面崩

    def closeEvent(self, e):
        # 手改的框还没保存就关窗口 = 白干,必须先问
        if not self._confirm_discard():
            e.ignore()
            return
        if self.runner.is_running():
            if QMessageBox.question(
                    self, "任务还在跑",
                    "标注任务正在运行,关闭窗口会中断它。确定要关吗?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No) != QMessageBox.Yes:
                e.ignore()
                return
            self.runner.stop()
        try:
            self._save_cfg()
        except Exception:
            pass
        # 关窗前把还在跑的东西全停掉,再放手让 Qt 销毁控件。
        # 不停的话:定时器还会 timeout -> 往已经析构的控件上画 -> 段错误
        # (退出码 139,而且日志里看不到任何 Python 报错)。
        self._closing = True
        self._update_check_seq += 1
        self._update_link_seq += 1
        try:
            app = QApplication.instance()
            if app is not None and getattr(
                    self, "_shortcut_focus_connected", False):
                app.focusChanged.disconnect(self._shortcut_focus_slot)
                self._shortcut_focus_connected = False
            self._vid_stop = True          # 让抽帧循环下一次回调就退出
            self._pai_stop = True
            self._pai_thumb_seq += 1        # 作废缩略图后台任务
            self._vid_timer.stop()
            self._scrub_timer.stop()
            self._auto_timer.stop()
            if self._vid_reader is not None:
                self._vid_reader.close()   # 释放 cv2.VideoCapture
                self._vid_reader = None
        except Exception:
            pass
        e.accept()


def _esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _shorten(args):
    """把参数拼成一行给日志看;超长的描述截断,避免糊满屏幕。"""
    out = []
    for a in args:
        a = str(a)
        if len(a) > 60:
            a = a[:57] + "…"
        out.append(f'"{a}"' if " " in a or "|" in a else a)
    return " ".join(out)


def main():
    # 高分屏下不缩放会发虚
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    app = QApplication(sys.argv)
    app.setApplicationName("Best yolo")
    app.setApplicationVersion(APP_VERSION)
    app.setDesktopFileName("best-yolo")
    # Fusion 是跨发行版表现最一致的风格;系统主题(如 Adwaita)会覆盖掉不少 QSS
    app.setStyle("Fusion")
    apply_palette(app)
    app.setStyleSheet(stylesheet())
    f = app.font()
    base_pt = max(9.5, f.pointSizeF())
    f.setPointSizeF(base_pt)
    app.setFont(f)
    w = MainWindow()
    w._base_pt = base_pt          # 缩放时以系统字号为基准往上乘
    if abs(w._ui_k - 1.0) > 0.01:
        w._apply_scale()          # 上次手动调过缩放,启动就套上
    w.lb_zoom.setText(f"{int(w._ui_k * 100)}%")
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
