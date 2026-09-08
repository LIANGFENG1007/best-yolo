# -*- coding: utf-8 -*-
"""可搜索、可持久化的快捷键设置窗口。"""
from PySide6.QtCore import Qt, QStringListModel
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QCompleter, QDialog, QDoubleSpinBox,
    QFrame, QHBoxLayout, QHeaderView, QKeySequenceEdit, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSizePolicy, QSpinBox, QSplitter,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from theme import C


def _spec(sid, section, name, description, scope="global", defaults=(),
          repeat=False, target="page"):
    return {
        "id": sid,
        "section": section,
        "name": name,
        "description": description,
        "scope": scope,
        "defaults": tuple(defaults),
        "repeat": bool(repeat),
        "target": target,
    }


# 所有可以从界面直接触发的命令都集中在这里。顺序就是设置窗口中的顺序。
SHORTCUT_DEFINITIONS = (
    # 全局与导航
    _spec("settings.shortcuts", "全局与导航", "打开快捷键设置",
          "打开当前窗口。", defaults=("Ctrl+Alt+K",)),
    _spec("settings.theme", "全局与导航", "打开界面配色",
          "打开主题预设和自定义调色窗口。", defaults=("Ctrl+Alt+T",)),
    _spec("global.check_updates", "全局与导航", "检测软件更新",
          "检测 GitHub 上的最新稳定版本。", defaults=("Ctrl+Alt+U",)),
    _spec("nav.home", "全局与导航", "打开首页", "切换到首页。",
          defaults=("Alt+1",)),
    _spec("nav.mark", "全局与导航", "打开人工标注", "切换到人工标注页。",
          defaults=("Alt+2",)),
    _spec("nav.prompt", "全局与导航", "打开 AI 补充提示词",
          "切换到提示词分析页。", defaults=("Alt+3",)),
    _spec("nav.dataset", "全局与导航", "打开导出数据集",
          "切换到数据集导出页。", defaults=("Alt+4",)),
    _spec("nav.video", "全局与导航", "打开视频切片", "切换到视频切片页。",
          defaults=("Alt+5",)),
    _spec("global.open_output", "全局与导航", "打开输出目录",
          "打开当前项目的标签输出目录。", defaults=("Ctrl+Alt+O",)),
    _spec("global.open_preview", "全局与导航", "打开预览图目录",
          "打开当前项目的带框预览目录。", defaults=("Ctrl+Alt+P",)),
    _spec("ui.zoom_in", "全局与导航", "放大界面", "增大界面显示比例。",
          defaults=("Ctrl++", "Ctrl+="), repeat=True),
    _spec("ui.zoom_out", "全局与导航", "缩小界面", "减小界面显示比例。",
          defaults=("Ctrl+-",), repeat=True),
    _spec("ui.zoom_reset", "全局与导航", "界面恢复 100%",
          "将界面显示比例恢复为 100%。", defaults=("Ctrl+0",)),

    # 首页与自动标注
    _spec("home.new_project", "首页与自动标注", "新建项目", "新建一套标注项目。",
          "home", ("Ctrl+N",)),
    _spec("home.rename_project", "首页与自动标注", "重命名项目",
          "修改当前项目名称。", "home"),
    _spec("home.delete_project", "首页与自动标注", "删除项目",
          "删除当前项目及其项目内产物。", "home"),
    _spec("home.choose_images", "首页与自动标注", "选择图片文件夹",
          "打开图片目录选择窗口。", "home"),
    _spec("home.choose_output", "首页与自动标注", "选择输出目录",
          "打开标签输出目录选择窗口。", "home"),
    _spec("home.toggle_backup", "首页与自动标注", "切换运行前备份",
          "开启或关闭旧结果备份。", "home"),
    _spec("home.classes_all", "首页与自动标注", "类别全部选中",
          "勾选类别表中的所有类别。", "home"),
    _spec("home.classes_none", "首页与自动标注", "类别全部取消",
          "取消类别表中的所有类别。", "home"),
    _spec("home.add_class", "首页与自动标注", "添加类别",
          "在类别表末尾增加一行。", "home"),
    _spec("home.import_classes", "首页与自动标注", "导入类别表",
          "从 classes.txt 或 data.yaml 导入类别。", "home"),
    _spec("home.set_api_key", "首页与自动标注", "设置 API Key",
          "打开 API Key 设置窗口。", "home"),
    _spec("home.fetch_models", "首页与自动标注", "获取可用模型",
          "从当前接入点拉取模型列表。", "home"),
    _spec("home.toggle_advanced", "首页与自动标注", "展开或收起高级选项",
          "切换高级参数区域。", "home"),
    _spec("home.toggle_skip_done", "首页与自动标注", "切换跳过已标图片",
          "开启或关闭跳过已有标签。", "home"),
    _spec("home.preview", "首页与自动标注", "运行预览标注",
          "按预览张数开始自动标注。", "home", ("Ctrl+Return",)),
    _spec("home.label_all", "首页与自动标注", "运行全部标注",
          "对当前图片目录运行全量标注。", "home", ("Ctrl+Shift+Return",)),
    _spec("home.stop", "首页与自动标注", "停止标注任务",
          "停止正在运行的标注任务。", "home", ("Esc",)),
    _spec("home.clear_log", "首页与自动标注", "清空标注日志",
          "清空首页日志窗口。", "home"),
    _spec("home.copy_log", "首页与自动标注", "复制标注日志",
          "复制首页中的全部日志。", "home"),

    # 人工标注
    _spec("mark.refresh", "人工标注", "刷新图片与标签",
          "重新读取当前图片和标签。", "mark"),
    _spec("mark.previous", "人工标注", "上一张图片", "切换到上一张图片。",
          "mark", ("A", "PgUp"), repeat=True),
    _spec("mark.next", "人工标注", "下一张图片", "切换到下一张图片。",
          "mark", ("D", "PgDown"), repeat=True),
    _spec("mark.save", "人工标注", "保存全部修改",
          "保存所有待写入的 YOLO 标签。", "mark", ("Ctrl+S",)),
    _spec("mark.undo", "人工标注", "撤销框修改", "撤销最近一次框操作。",
          "mark", ("Ctrl+Z",), repeat=True),
    _spec("mark.redo", "人工标注", "重做框修改", "恢复最近撤销的框操作。",
          "mark", ("Ctrl+Shift+Z", "Ctrl+Y"), repeat=True),
    _spec("mark.delete", "人工标注", "删除选中的框",
          "删除画布中当前选中的框。", "mark", ("Del", "Backspace"),
          target="canvas"),
    _spec("mark.clear", "人工标注", "清空本张所有框",
          "清空当前图片上的全部框。", "mark", ("Shift+Del",)),
    _spec("mark.confirm", "人工标注", "确认新画的框",
          "确认当前待落下的新框。", "mark", ("Return", "Enter"),
          target="canvas"),
    _spec("mark.cancel", "人工标注", "取消新框或取消选择",
          "取消待确认框；没有待确认框时取消选中。", "mark", ("Esc",),
          target="canvas"),
    _spec("mark.toggle_lock", "人工标注", "切换图片锁定",
          "锁定或解锁当前图片。", "mark", ("L",)),
    _spec("mark.toggle_autosave", "人工标注", "切换自动保存",
          "开启或关闭定时自动保存。", "mark"),
    _spec("mark.reset_view", "人工标注", "画布缩放复位",
          "让当前图片重新适合画布。", "mark", ("0",), target="canvas"),
    _spec("mark.nudge_left", "人工标注", "选中框左移 1 像素",
          "将选中的框向左微调。", "mark", ("Left",), True, "canvas"),
    _spec("mark.nudge_right", "人工标注", "选中框右移 1 像素",
          "将选中的框向右微调。", "mark", ("Right",), True, "canvas"),
    _spec("mark.nudge_up", "人工标注", "选中框上移 / 上一张",
          "有选中框时向上微调，否则切换到上一张。", "mark", ("Up",),
          True, "canvas"),
    _spec("mark.nudge_down", "人工标注", "选中框下移 / 下一张",
          "有选中框时向下微调，否则切换到下一张。", "mark", ("Down",),
          True, "canvas"),
    _spec("mark.nudge_left_fast", "人工标注", "选中框左移 10 像素",
          "将选中的框向左快速微调。", "mark", ("Shift+Left",), True, "canvas"),
    _spec("mark.nudge_right_fast", "人工标注", "选中框右移 10 像素",
          "将选中的框向右快速微调。", "mark", ("Shift+Right",), True, "canvas"),
    _spec("mark.nudge_up_fast", "人工标注", "选中框上移 10 像素",
          "将选中的框向上快速微调。", "mark", ("Shift+Up",), True, "canvas"),
    _spec("mark.nudge_down_fast", "人工标注", "选中框下移 10 像素",
          "将选中的框向下快速微调。", "mark", ("Shift+Down",), True, "canvas"),

    # AI 补充提示词
    _spec("prompt.images_all", "AI 补充提示词", "图片全部选中",
          "勾选提示词页中的全部图片。", "prompt"),
    _spec("prompt.images_none", "AI 补充提示词", "图片全部取消",
          "取消提示词页中的全部图片。", "prompt"),
    _spec("prompt.images_invert", "AI 补充提示词", "反选图片",
          "反转当前图片勾选状态。", "prompt"),
    _spec("prompt.images_changed", "AI 补充提示词", "只选人工改过的图片",
          "只勾选相对 AI 基线发生修改的图片。", "prompt"),
    _spec("prompt.refresh", "AI 补充提示词", "刷新图片列表",
          "重新读取图片、标签和基线。", "prompt"),
    _spec("prompt.classes_all", "AI 补充提示词", "分析类别全部选中",
          "勾选全部启用类别。", "prompt"),
    _spec("prompt.classes_none", "AI 补充提示词", "分析类别全部取消",
          "取消全部分析类别。", "prompt"),
    _spec("prompt.fetch_models", "AI 补充提示词", "载入提示词模型列表",
          "读取首页缓存的模型列表。", "prompt"),
    _spec("prompt.start", "AI 补充提示词", "开始提示词分析",
          "提交选中的图片进行分析。", "prompt", ("Ctrl+Return",)),
    _spec("prompt.stop", "AI 补充提示词", "停止提示词分析",
          "请求停止当前分析。", "prompt", ("Esc",)),
    _spec("prompt.apply", "AI 补充提示词", "应用勾选的建议",
          "将选中的建议写入类别描述。", "prompt", ("Ctrl+S",)),
    _spec("prompt.findings", "AI 补充提示词", "查看模型原话",
          "打开逐图观察结论。", "prompt"),

    # 导出数据集
    _spec("dataset.choose_output", "导出数据集", "选择数据集输出目录",
          "打开数据集目录选择窗口。", "dataset"),
    _spec("dataset.generate", "导出数据集", "生成数据集",
          "切分 train/val 并生成配置。", "dataset", ("Ctrl+Return",)),
    _spec("dataset.open", "导出数据集", "打开数据集目录",
          "在文件管理器中打开数据集。", "dataset"),

    # 视频切片
    _spec("video.choose_file", "视频切片", "选择视频文件",
          "打开视频文件选择窗口。", "video"),
    _spec("video.choose_output", "视频切片", "选择切片输出目录",
          "打开切片图片目录选择窗口。", "video"),
    _spec("video.play", "视频切片", "播放或暂停区间",
          "播放或暂停当前选择区间。", "video", ("Space",)),
    _spec("video.set_start", "视频切片", "播放头设为开始",
          "把播放头位置设为区间起点。", "video", ("I",)),
    _spec("video.set_end", "视频切片", "播放头设为结束",
          "把播放头位置设为区间终点。", "video", ("O",)),
    _spec("video.full_range", "视频切片", "选择整个视频",
          "将抽帧区间恢复为整段视频。", "video", ("Home",)),
    _spec("video.extract", "视频切片", "开始视频切片",
          "按当前区间和间隔开始抽帧。", "video", ("Ctrl+Return",)),
    _spec("video.stop", "视频切片", "停止视频切片",
          "请求停止正在进行的抽帧。", "video", ("Esc",)),
    _spec("video.open_output", "视频切片", "打开切片文件夹",
          "在文件管理器中打开切片目录。", "video"),
    _spec("video.use_frames", "视频切片", "用切片图片去标注",
          "把当前项目图片目录指向切片目录。", "video"),
    _spec("video.refresh", "视频切片", "刷新切片缩略图",
          "重新读取切片输出目录。", "video"),
)


DEFINITION_BY_ID = {d["id"]: d for d in SHORTCUT_DEFINITIONS}


def _using_qt_stub():
    try:
        import PySide6
        return getattr(PySide6, "__version__", "") == "0-stub"
    except Exception:
        return False


def canonical_sequence(text):
    """把任意可识别的按键文字转成 Qt 可跨平台保存的格式。"""
    text = str(text or "").strip()
    if not text:
        return ""
    if _using_qt_stub():
        return text
    seq = QKeySequence.fromString(text, QKeySequence.PortableText)
    if seq.isEmpty():
        seq = QKeySequence(text)
    return seq.toString(QKeySequence.PortableText).strip()


def normalize_sequences(values):
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return []
    out = []
    for value in values[:2]:
        seq = canonical_sequence(value)
        if seq and seq not in out:
            out.append(seq)
    return out


def default_bindings():
    return {d["id"]: normalize_sequences(d["defaults"])
            for d in SHORTCUT_DEFINITIONS}


def merged_bindings(saved):
    """补上新增功能的默认值，同时保留用户主动清空的项目。"""
    out = default_bindings()
    if not isinstance(saved, dict):
        return out
    for sid, values in saved.items():
        if sid in DEFINITION_BY_ID:
            out[sid] = normalize_sequences(values)
    return out


def display_sequence(text):
    text = canonical_sequence(text)
    if not text or _using_qt_stub():
        return text
    return QKeySequence(text).toString(QKeySequence.NativeText) or text


def binding_label(values, empty="未设置"):
    labels = [display_sequence(v) for v in normalize_sequences(values)]
    return "  /  ".join(labels) if labels else empty


def is_unmodified_sequence(text):
    """没有 Ctrl/Alt/Meta 的按键会和文本输入冲突，需要在输入框中停用。"""
    low = canonical_sequence(text).casefold()
    return not any(mod in low for mod in ("ctrl+", "alt+", "meta+", "cmd+"))


def _scopes_overlap(a, b):
    return a == "global" or b == "global" or a == b


def find_conflicts(bindings):
    """返回 [(按键, 功能 id 1, 功能 id 2)]；不同页面允许复用。"""
    used = {}
    conflicts = []
    for spec in SHORTCUT_DEFINITIONS:
        sid = spec["id"]
        for seq in normalize_sequences(bindings.get(sid, [])):
            key = seq.casefold()
            for other_id in used.get(key, []):
                other = DEFINITION_BY_ID[other_id]
                if _scopes_overlap(spec["scope"], other["scope"]):
                    conflicts.append((seq, other_id, sid))
            used.setdefault(key, []).append(sid)
    return conflicts


def is_text_input(widget):
    """判断焦点是否在会输入文字/数字的控件中。"""
    return isinstance(widget, (QLineEdit, QPlainTextEdit, QComboBox,
                               QSpinBox, QDoubleSpinBox, QKeySequenceEdit))


class ShortcutSettingsDialog(QDialog):
    """按板块浏览、包含式搜索并编辑主/备用快捷键。"""

    SCOPE_NAMES = {
        "global": "整个应用",
        "home": "首页",
        "mark": "人工标注页",
        "prompt": "AI 补充提示词页",
        "dataset": "导出数据集页",
        "video": "视频切片页",
    }

    def __init__(self, bindings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("快捷键设置")
        self.setMinimumSize(760, 520)
        self.resize(980, 680)
        self._working = merged_bindings(bindings)
        self._current_id = None
        self._items = {}
        self._groups = {}
        self._conflicts = []

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        title = QLabel("快捷键设置")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setObjectName("ShortcutSearch")
        self.search.setPlaceholderText("搜索功能、板块、说明或按键，例如：保存、提示词、Ctrl+S")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.lb_count = QLabel("")
        self.lb_count.setObjectName("Hint")
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.lb_count)
        root.addLayout(search_row)

        # 和首页模型搜索一样，输入任意片段就弹出匹配建议；下方树也同步过滤。
        self._search_model = QStringListModel([], self)
        self._completer = QCompleter(self)
        self._completer.setModel(self._search_model)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchContains)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self.search.setCompleter(self._completer)
        self._refresh_search_suggestions()

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)

        self.tree = QTreeWidget()
        self.tree.setObjectName("ShortcutTree")
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["功能", "快捷键"])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.currentItemChanged.connect(self._select_item)
        self.tree.itemDoubleClicked.connect(
            lambda item, _col: self.key_primary.setFocus()
            if item and item.data(0, Qt.UserRole) else None)
        split.addWidget(self.tree)

        editor = QFrame()
        editor.setObjectName("ShortcutEditor")
        editor.setMinimumWidth(310)
        editor.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        el = QVBoxLayout(editor)
        el.setContentsMargins(18, 16, 18, 16)
        el.setSpacing(10)
        self.lb_name = QLabel("选择一个功能")
        self.lb_name.setObjectName("CardTitle")
        self.lb_name.setWordWrap(True)
        self.lb_scope = QLabel("")
        self.lb_scope.setObjectName("ShortcutScope")
        self.lb_desc = QLabel("")
        self.lb_desc.setObjectName("Hint")
        self.lb_desc.setWordWrap(True)
        el.addWidget(self.lb_name)
        el.addWidget(self.lb_scope)
        el.addWidget(self.lb_desc)

        el.addSpacing(8)
        el.addWidget(QLabel("主快捷键"))
        self.key_primary = self._key_editor()
        el.addWidget(self.key_primary)
        el.addWidget(QLabel("备用快捷键"))
        self.key_alternate = self._key_editor()
        el.addWidget(self.key_alternate)

        erow = QHBoxLayout()
        self.btn_clear = QPushButton("清空本项")
        self.btn_default = QPushButton("恢复本项默认")
        self.btn_clear.clicked.connect(self._clear_current)
        self.btn_default.clicked.connect(self._restore_current)
        erow.addWidget(self.btn_clear)
        erow.addWidget(self.btn_default)
        el.addLayout(erow)
        self.lb_conflict = QLabel("")
        self.lb_conflict.setObjectName("ShortcutConflict")
        self.lb_conflict.setWordWrap(True)
        el.addWidget(self.lb_conflict)
        el.addStretch(1)
        split.addWidget(editor)
        split.setSizes([590, 350])

        buttons = QHBoxLayout()
        restore_all = QPushButton("全部恢复默认")
        restore_all.clicked.connect(self._restore_all)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        self.btn_save = QPushButton("保存快捷键")
        self.btn_save.setObjectName("Primary")
        self.btn_save.clicked.connect(self._accept_if_valid)
        buttons.addWidget(restore_all)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.btn_save)
        root.addLayout(buttons)

        self._fill_tree()
        self._validate()
        self.search.setFocus()

    def _key_editor(self):
        editor = QKeySequenceEdit()
        editor.setMaximumSequenceLength(1)
        editor.setClearButtonEnabled(True)
        line = editor.findChild(QLineEdit)
        if line is not None:
            line.setPlaceholderText("点击后按下快捷键")
        editor.keySequenceChanged.connect(self._keys_changed)
        return editor

    def _fill_tree(self):
        first = None
        for spec in SHORTCUT_DEFINITIONS:
            section = spec["section"]
            group = self._groups.get(section)
            if group is None:
                group = QTreeWidgetItem(self.tree, [section, ""])
                group.setFlags(group.flags() & ~Qt.ItemIsSelectable)
                group.setExpanded(True)
                self._groups[section] = group
            item = QTreeWidgetItem(group, [spec["name"], ""])
            item.setData(0, Qt.UserRole, spec["id"])
            item.setToolTip(0, spec["description"])
            self._items[spec["id"]] = item
            if first is None:
                first = item
        self._refresh_labels()
        if first is not None:
            self.tree.setCurrentItem(first)
        self._filter(self.search.text())

    def _refresh_labels(self):
        for sid, item in self._items.items():
            item.setText(1, binding_label(self._working.get(sid, [])))

    def _refresh_search_suggestions(self):
        """候选里同时放功能名和按键，Ctrl+S 这类片段也能弹出结果。"""
        self._search_model.setStringList([
            f"{spec['section']} · {spec['name']} · "
            f"{binding_label(self._working.get(spec['id'], []))}"
            for spec in SHORTCUT_DEFINITIONS
        ])

    def _select_item(self, current, _previous=None):
        sid = current.data(0, Qt.UserRole) if current is not None else None
        if not sid or sid not in DEFINITION_BY_ID:
            return
        self._current_id = sid
        spec = DEFINITION_BY_ID[sid]
        self.lb_name.setText(spec["name"])
        self.lb_scope.setText("生效范围：" + self.SCOPE_NAMES.get(
            spec["scope"], spec["scope"]))
        self.lb_desc.setText(spec["description"])
        values = self._working.get(sid, [])
        for editor, value in zip(
                (self.key_primary, self.key_alternate),
                (values + ["", ""])[:2]):
            editor.blockSignals(True)
            editor.setKeySequence(QKeySequence(value))
            editor.blockSignals(False)
        self.btn_clear.setEnabled(bool(values))
        self.btn_default.setEnabled(
            values != normalize_sequences(spec["defaults"]))

    def _keys_changed(self, *_):
        if not self._current_id:
            return
        values = []
        for editor in (self.key_primary, self.key_alternate):
            seq = canonical_sequence(editor.keySequence().toString(
                QKeySequence.PortableText))
            if seq and seq not in values:
                values.append(seq)
        self._working[self._current_id] = values
        self._refresh_labels()
        self._refresh_search_suggestions()
        self._validate()
        self._filter(self.search.text())
        spec = DEFINITION_BY_ID[self._current_id]
        self.btn_clear.setEnabled(bool(values))
        self.btn_default.setEnabled(
            values != normalize_sequences(spec["defaults"]))

    def _clear_current(self):
        if not self._current_id:
            return
        self._working[self._current_id] = []
        self._reload_current()

    def _restore_current(self):
        if not self._current_id:
            return
        spec = DEFINITION_BY_ID[self._current_id]
        self._working[self._current_id] = normalize_sequences(spec["defaults"])
        self._reload_current()

    def _restore_all(self):
        self._working = default_bindings()
        self._refresh_labels()
        self._refresh_search_suggestions()
        self._reload_current()
        self._filter(self.search.text())

    def _reload_current(self):
        item = self._items.get(self._current_id)
        if item is not None:
            self._select_item(item)
        self._refresh_labels()
        self._refresh_search_suggestions()
        self._validate()

    def _validate(self):
        self._conflicts = find_conflicts(self._working)
        if self._conflicts:
            seq, left, right = self._conflicts[0]
            a, b = DEFINITION_BY_ID[left], DEFINITION_BY_ID[right]
            more = len(self._conflicts) - 1
            self.lb_conflict.setText(
                f"冲突：{display_sequence(seq)} 同时用于“{a['name']}”和"
                f"“{b['name']}”" + (f"，另有 {more} 处冲突" if more else ""))
            self.lb_conflict.setStyleSheet(
                f"color:{C['err']}; background:transparent;")
            self.btn_save.setEnabled(False)
        else:
            self.lb_conflict.setText("没有快捷键冲突")
            self.lb_conflict.setStyleSheet(
                f"color:{C['ok']}; background:transparent;")
            self.btn_save.setEnabled(True)

    def _filter(self, text):
        needle = (text or "").strip().casefold()
        visible = []
        for section, group in self._groups.items():
            n_group = 0
            for i in range(group.childCount()):
                item = group.child(i)
                sid = item.data(0, Qt.UserRole)
                spec = DEFINITION_BY_ID[sid]
                keys = " ".join(self._working.get(sid, []))
                hay = " ".join((section, spec["name"], spec["description"],
                                keys, binding_label(self._working.get(sid, []), "")))
                show = not needle or needle in hay.casefold()
                item.setHidden(not show)
                if show:
                    visible.append(sid)
                    n_group += 1
            group.setHidden(n_group == 0)
            if needle and n_group:
                group.setExpanded(True)
        self.lb_count.setText(f"显示 {len(visible)} / {len(SHORTCUT_DEFINITIONS)}")
        cur = self.tree.currentItem()
        if visible and (cur is None or cur.isHidden() or
                        not cur.data(0, Qt.UserRole)):
            self.tree.setCurrentItem(self._items[visible[0]])
        return visible

    def visible_action_ids(self):
        return [sid for sid, item in self._items.items() if not item.isHidden()]

    def _accept_if_valid(self):
        self._validate()
        if not self._conflicts:
            self.accept()

    def bindings(self):
        return {sid: list(values) for sid, values in self._working.items()}
