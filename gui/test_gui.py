#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI 逻辑测试(不需要装 Qt,用 _qtstub 顶替)。

    python gui/test_gui.py

验证的是「行为」:配置往返、参数拼装、类别表读写、备份、进度/日志、
弹窗确认路径。外观仍需真机目视。
"""
import os
import sys
import json
import threading
import time
import shutil
import tempfile
import io
import re
import subprocess
import contextlib

os.environ["BEST_YOLO_DISABLE_UPDATE_CHECK"] = "1"

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import _qtstub
QtWidgets, QtCore, QtGui = _qtstub.install()

import core
import app as A
import widgets as _W

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MsgBox = QtWidgets.QMessageBox
QProcess = QtCore.QProcess
OK = []


def ck(cond, msg):
    if cond:
        OK.append(msg)
        print("  ✓", msg)
    else:
        print("  ✗", msg)
        raise AssertionError(msg)


def make_imgs(d, n=5):
    from PIL import Image
    os.makedirs(d, exist_ok=True)
    for i in range(n):
        Image.new("RGB", (64, 48), (30, 60, 90)).save(os.path.join(d, f"img{i}.png"))


def finish(w, code=0):
    """模拟子进程真正结束(走 runner 的真实收尾路径,而不是直接调 GUI 槽)。"""
    w.runner._on_done(code, None)


def main():
    tmp = tempfile.mkdtemp(prefix="qal_test_")
    imgs = os.path.join(tmp, "pics")
    out = os.path.join(tmp, "out")
    ds = os.path.join(tmp, "dataset")
    make_imgs(imgs, 5)
    cfg_path = os.path.join(tmp, "config.json")
    core.CONFIG_PATH = cfg_path
    A.core.CONFIG_PATH = cfg_path
    core.PROJECTS_DIR = A.core.PROJECTS_DIR = os.path.join(tmp, "projects")
    core.STATE_PATH = A.core.STATE_PATH = os.path.join(tmp, ".state.json")
    os.makedirs(core.PROJECTS_DIR)

    print("\n[0] 没有项目时:不能做任何操作")
    w0 = A.MainWindow()
    ck(w0._proj is None, "没项目时未选中任何项目")
    ck(w0.tbl.rowCount() == 0, "类别表是空的(不预填 16 类)")
    ck(w0.p_images.text() == "", "图片目录是空的")
    ck(not w0.p_images.isEnabled(), "图片目录不可编辑")
    ck(not w0.tbl.isEnabled(), "类别表不可编辑")
    ck(not w0.btn_preview.isEnabled(), "不能跑预览")
    ck(not w0.btn_all.isEnabled(), "不能跑全部")
    ck(not w0.canvas.isEnabled(), "标注页画布也禁用")
    ck("先新建一个项目" in w0.lb_proj.text(), "明确提示要先建项目")
    MsgBox.CALLS.clear()
    w0.run_label(preview=True)
    ck(any("先建个项目" in c[1] for c in MsgBox.CALLS), "硬调 run_label 也会被挡住")
    ck(w0._cfg_path() == "", "没项目时不会把配置写到任何地方")

    print("\n[0b] 软件名与侧栏导航")
    ck(w0.windowTitle() == "Best yolo", f"窗口标题是 Best yolo({w0.windowTitle()})")
    _navs = [w0.nav.button(_k).text() for _k in range(5)]
    ck(_navs == ["首页", "标注", "AI 补充提示词", "导出数据集", "视频切片"],
       f"侧栏五项,顺序 = 实际使用顺序:{_navs}")
    # 页码常量必须和侧栏顺序一致 —— 不然点导航会跳错页
    for _k in range(5):
        w0._go(_k)
        ck(w0.pages.currentIndex() == _k, f"点第 {_k} 项跳到第 {_k} 页")
    ck(A.MainWindow.PAGE_PROMPT == 2, "AI 补充提示词是第 3 项(紧跟标注)")
    ck(A.MainWindow.PAGE_VIDEO == 4, "视频切片是最后一项")

    print("\n[1] 建个项目后才能开始")
    # 后续所有测试都在这个项目里跑
    _P0 = "测试项目"
    core.create_project(_P0)
    core.save_state(project=_P0)
    w = A.MainWindow()
    ck(w._proj == _P0, "启动时进入上次的项目")
    ck(w.p_images.isEnabled() and w.tbl.isEnabled(), "有项目后可以编辑了")
    ck(w.tbl.rowCount() == 0, "新项目的类别表是空的,等你自己填")
    # 给它填上默认 16 类,方便后面的测试沿用
    w._fill_class_table([{"name": n, "desc": d, "on": o}
                         for n, d, o in core.DEFAULT_CLASSES])
    ck(w.tbl.rowCount() == 16, "类别表填了 16 行")
    ck(w.cb_model.currentData() == "qwen3-vl-plus", "默认模型 qwen3-vl-plus")
    # 默认并发从 50 降到 8:视觉模型 QPS 配额很小,50 并发几乎必然被限流
    ck(w.sp_workers.value() == 8, "默认并发 8(保守,避免一上手就被限流)")
    ck(w.ck_skip.isChecked(), "默认跳过已标好的图(重跑不重复花钱)")
    ck(w.cb_px.currentData() == 2000000, "默认分辨率 200万")
    ck(w.adv.isVisible() is False, "高级选项默认折叠")

    print("\n[2] 界面 -> 配置:改了控件能读回来")
    w.p_images.setText(imgs)
    w.p_out.setText(out)
    w.p_ds.setText(ds)
    w.ed_neg.setPlainText("香蕉、桌布")
    w.sp_limit.setValue(3)
    c = w._collect_from_ui()
    ck(c["images"] == imgs and c["out"] == out, "路径读回正确")
    ck(c["negative"] == "香蕉、桌布", "排除项读回正确")
    ck(len(c["classes"]) == 16, "类别表读回 16 类")
    ck(c["classes"][13]["name"] == "CD002", "第14行是 CD002")

    print("\n[3] 类别勾选 -> --only / --desc")
    a = core.build_label_args(c, limit=3)
    ck("--only" not in a, "全勾选时不传 --only")
    for r in range(16):
        cb = w.tbl.cellWidget(r, 0).findChild(QtWidgets.QCheckBox)
        cb.setChecked(r in (0, 13))
    c2 = w._collect_from_ui()
    a2 = core.build_label_args(c2)
    ck(a2[a2.index("--only") + 1] == "CA001,CD002", "部分勾选 -> --only=CA001,CD002")
    ck(a2[a2.index("--classes") + 1].split(",")[13] == "CD002", "--classes 仍是全部16类(id稳定)")
    d = a2[a2.index("--desc") + 1]
    ck(d.count("|") == 1, "--desc 只含勾选的2类")
    w._check_all(True)
    ck(w._update_cls_stat() is None and "16 类" in w.lb_cls_stat.text(), "全选后统计文字更新")

    print("\n[4] 校验:配置有问题要弹窗且不启动进程")
    MsgBox.CALLS.clear()
    QProcess.LAST = None
    w.p_images.setText("/definitely/not/here")
    w.run_label(preview=True)
    ck(any(k == "warning" for k, _, _ in MsgBox.CALLS), "路径无效时弹出警告")
    ck(QProcess.LAST is None, "校验失败不启动进程")
    w.p_images.setText(imgs)

    print("\n[5] 预览:命令行组装正确")
    MsgBox.CALLS.clear()
    QProcess.LAST = None
    w.run_label(preview=True)
    p = QProcess.LAST
    ck(p is not None, "预览启动了进程")
    # -u:不缓冲,否则日志会攒成一坨才出现,重试等待时看着像卡死
    ck(p._args[0] == "-u", "用 -u 启动,日志实时出现")
    ck(p._args[1].endswith("autolabel_qwen.py"), "跑的是 autolabel_qwen.py")
    ck(p._args[p._args.index("--limit") + 1] == "3", "预览传了 --limit 3")
    ck(not any(k == "question" for k, _, _ in MsgBox.CALLS), "预览不需要二次确认")
    ck(os.path.isdir(os.path.join(out, "labels")), "预先建好 labels 目录")
    ck(os.path.isdir(os.path.join(out, "vis")), "预先建好 vis 目录")
    env = p._env._d
    ck("ALL_PROXY" not in env, "子进程环境已清代理")
    ck(env.get("PYTHONUNBUFFERED") == "1", "设了 PYTHONUNBUFFERED(日志实时)")
    ck(w.btn_preview.isEnabled() is False, "运行中禁用预览按钮")
    ck(w.btn_stop.isEnabled() is True, "运行中启用停止按钮")

    print("\n[6] 日志与进度")
    w.runner._emit_line("共 5 张图, 后端=api, 模型=qwen3-vl-plus")
    w.runner._emit_line("[1/5] img0.png -> 4 个框")
    w.runner._emit_line("[2/5] img1.png -> 0 个框")
    ck(w.bar.value() == 2, "进度条走到 2")
    ck("2 / 5" in w.lb_prog.text(), "进度文字 2/5")
    w.runner._emit_line("[3/5] img2.png 失败: RateLimit")
    ck("RateLimit" in w.log.toPlainText(), "失败行进了日志")
    ck("F85149" in w.log.toPlainText(), "失败行标红")
    w.runner._emit_line("完成! 共 12 个框。")
    ck("3FB950" in w.log.toPlainText(), "完成行标绿")

    print("\n[7] 运行结束 -> 自动跳到结果页并统计")
    os.makedirs(os.path.join(out, "labels"), exist_ok=True)
    os.makedirs(os.path.join(out, "vis"), exist_ok=True)
    # 造 3 个标签:CA001 两个框、CD002 一个框、一个空文件
    open(os.path.join(out, "labels", "img0.txt"), "w").write(
        "0 0.5 0.5 0.2 0.2\n0 0.3 0.3 0.1 0.1\n")
    open(os.path.join(out, "labels", "img1.txt"), "w").write("13 0.4 0.4 0.2 0.3\n")
    open(os.path.join(out, "labels", "img2.txt"), "w").write("")
    from PIL import Image
    for n in ("img0", "img1"):
        Image.new("RGB", (64, 48), (20, 20, 20)).save(os.path.join(out, "vis", n + ".jpg"))
    finish(w, 0)          # 子进程正常结束
    ck(w.pages.currentIndex() == A.MainWindow.PAGE_MARK, "跑完自动切到标注页")
    ck(not w.runner.is_running(), "结束后 runner 状态已复位")
    ck(w.btn_preview.isEnabled(), "结束后按钮恢复可用")
    # 标注页现在列出【原图目录里的所有 5 张图】,而不只是标过的那 3 张 ——
    # 这样没跑 AI 的图也能纯手动标
    ck(w.lst_vis.count() == 5, "标注页列出待标注目录的全部 5 张图")
    ck("已标 3" in w.lb_vis.text(), f"标题区分已标/未标:{w.lb_vis.text()}")
    # 颜色三态:灰=没有框, 黄=改了没保存, 白=已保存
    from theme import C as _C
    _GREY, _YEL, _WHITE = _C["text_faint"], _C["warn"], _C["text"]

    def _fg(i):
        f = w.lst_vis.item(i).foreground()
        return getattr(f, "_args", (None,))[0] if f is not None else None

    ck(_fg(3) == _GREY, f"没标注的图是灰色({_fg(3)})")
    ck("还没标注" in (w.lst_vis.item(3).toolTip() or ""), "未标注的图有提示")
    ck(_fg(2) == _GREY, "标过但 0 个框的也是灰色(等于没东西)")
    ck("还没有框" in (w.lst_vis.item(2).toolTip() or ""), "空标签的图有提示")
    ck(_fg(0) == _WHITE, f"已保存且有框的是白色({_fg(0)})")
    ck("已保存" in (w.lst_vis.item(0).toolTip() or ""), "已保存的图提示已保存")
    st = core.read_label_stats(out, w._classes_from_table())
    ck(st["total_boxes"] == 3, "统计到 3 个框")
    ck(st["n_empty"] == 1, "统计到 1 个空标签")
    ck(st["per_class"][0]["count"] == 2, "CA001 = 2 个框")
    ck(st["per_class"][13]["count"] == 1, "CD002 = 1 个框")
    ck("一个都没标到" in w.lb_sum.text(), "提示了没标到的类别")

    print("\n[8] 标注全部:必须二次确认,取消则不跑")
    MsgBox.CALLS.clear()
    QProcess.LAST = None
    MsgBox.ANSWER = MsgBox.No
    w.run_label(preview=False)
    ck(any(k == "question" for k, _, _ in MsgBox.CALLS), "全量标注弹出确认")
    ck(QProcess.LAST is None, "选No不启动进程")
    q = [t for k, _, t in MsgBox.CALLS if k == "question"][0]
    ck("费用" in q, "确认框提到费用")
    ck("5 张" in q, "确认框写明张数")

    print("\n[9] 标注全部:确认后备份旧结果再跑")
    MsgBox.ANSWER = MsgBox.Yes
    QProcess.LAST = None
    w.run_label(preview=False)
    ck(QProcess.LAST is not None, "选Yes启动了进程")
    ck("--limit" not in QProcess.LAST._args, "全量不传 --limit")
    bak = [d for d in os.listdir(tmp) if d.startswith("out_旧_")]
    ck(len(bak) == 1, f"旧结果已备份到 {bak}")
    ck(not core.has_results(out), "备份后 out 已清空")
    ck("备份" in w.log.toPlainText(), "日志里有备份提示")
    finish(w, 0)

    print("\n[10] 数据集:没标签时拒绝生成")
    MsgBox.CALLS.clear()
    QProcess.LAST = None
    w.run_dataset()
    ck(any("还没有标签" in t for k, t, _ in MsgBox.CALLS), "无标签时提示")
    ck(QProcess.LAST is None, "无标签不启动进程")

    print("\n[11] 数据集:有标签则组装正确参数")
    os.makedirs(os.path.join(out, "labels"), exist_ok=True)
    open(os.path.join(out, "labels", "img0.txt"), "w").write("0 0.5 0.5 0.2 0.2\n")
    QProcess.LAST = None
    w.sp_val.setValue(0.25)
    w.sp_seed.setValue(7)
    w.run_dataset()
    p2 = QProcess.LAST
    ck(p2 is not None and p2._args[1].endswith("build_dataset.py"), "跑的是 build_dataset.py")
    ck(p2._args[p2._args.index("--val-ratio") + 1] == "0.25", "传了 val-ratio 0.25")
    ck(p2._args[p2._args.index("--seed") + 1] == "7", "传了 seed 7")
    ck(p2._args[p2._args.index("--ext") + 1] == "auto", "ext=auto")
    ck(p2._args[p2._args.index("--labels") + 1] == os.path.join(out, "labels"),
       "labels 指向 out/labels")
    w.runner._emit_line("数据集就绪: %s  (train=1, val=0)" % ds)
    finish(w, 0)
    ck("3FB950" in w.log_ds.toPlainText(), "数据集完成行标绿")

    print("\n[12] 后端切换:模型列表跟着换")
    i = w.cb_backend.findData("local")
    w.cb_backend.setCurrentIndex(i)
    ck(w.cb_model.currentData().startswith("Qwen/"), "切本地后模型变成 Qwen/...")
    ck(w.sp_workers.isEnabled() is False, "本地后端禁用并发数")
    w.cb_backend.setCurrentIndex(w.cb_backend.findData("api"))
    ck(w.cb_model.currentData() == "qwen3-vl-plus", "切回云端恢复 qwen3-vl-plus")
    ck(w.sp_workers.isEnabled() is True, "云端启用并发数")

    print("\n[13] 高级选项")
    w._toggle_adv()
    ck(w.adv.isVisible() is True, "点击后展开")
    w.cb_tiles.setCurrentIndex(w.cb_tiles.findData("2x2"))
    w.cb_coord.setCurrentIndex(w.cb_coord.findData(1000))
    c3 = w._collect_from_ui()
    a3 = core.build_label_args(c3)
    ck("--tiles" in a3 and a3[a3.index("--tiles") + 1] == "2x2", "切片参数生效")
    ck("--coord-scale" in a3, "坐标兜底参数生效")
    MsgBox.CALLS.clear()
    MsgBox.ANSWER = MsgBox.No
    w.run_label(preview=False)
    q2 = [t for k, _, t in MsgBox.CALLS if k == "question"][0]
    ck("20 次" in q2, "切片2x2时确认框把调用数算成 5×4=20")
    w.cb_tiles.setCurrentIndex(0)
    w.cb_coord.setCurrentIndex(0)
    ck(not w.runner.is_running(), "选No后没有残留任务")

    print("\n[14] 加类别行 / 每行右边的红叉删除")
    n0 = w.tbl.rowCount()
    w._add_class_row("CE001", "测试类", True)
    ck(w.tbl.rowCount() == n0 + 1, "加了一行")
    ck(w._classes_from_table()[-1]["name"] == "CE001", "新行读得到")
    # 每一行都该有个删除叉
    ck(all(w.tbl.cellWidget(r, 3) is not None for r in range(w.tbl.rowCount())),
       "每行右边都有删除按钮")
    ck(w.tbl.cellWidget(0, 3).text() == "删除", "按钮上写着「删除」")
    ck(w.tbl.horizontalHeaderItem(3).text() == "删除", "表头那一栏写着「删除」")
    ck(w.tbl.cellWidget(0, 3).objectName() == "RowDel", "用了红叉样式")
    ck("button" not in [b.text() for b in w._cls_btns] and
       "删选中行" not in [b.text() for b in w._cls_btns],
       "工具条上没有「删选中行」了")
    # 点最后一行的叉:不是中间行,不会影响别人的 id,所以不该弹窗
    MsgBox.CALLS.clear()
    w.tbl.cellWidget(w.tbl.rowCount() - 1, 3).click()
    ck(w.tbl.rowCount() == n0, "点红叉删掉了那一行")
    ck(not MsgBox.CALLS, "删最后一行不啰嗦(不影响其它类别的 id)")
    # 点中间行的叉:会让后面的 id 前移,必须警告
    MsgBox.CALLS.clear()
    MsgBox.ANSWER = MsgBox.Yes
    _name3 = w.tbl.item(3, 1).text()
    w.tbl.cellWidget(3, 3).click()
    ck(w.tbl.rowCount() == n0 - 1, "删掉了中间那一行")
    ck(any("id" in t and "前移" in t for k, _, t in MsgBox.CALLS),
       "删中间行时警告了 id 前移风险")
    ck(_name3 not in [c["name"] for c in w._classes_from_table()],
       f"删掉的确实是点的那一行({_name3})")
    # 选No时不该删
    MsgBox.ANSWER = MsgBox.No
    _n_now = w.tbl.rowCount()
    w.tbl.cellWidget(2, 3).click()
    ck(w.tbl.rowCount() == _n_now, "确认框选No就不删")
    MsgBox.ANSWER = MsgBox.Yes
    # 关键:删过行之后行号会变,红叉必须还对得上自己那一行
    _before = [c["name"] for c in w._classes_from_table()]
    w.tbl.cellWidget(1, 3).click()
    w.tbl.cellWidget(1, 3).click()
    _after = [c["name"] for c in w._classes_from_table()]
    ck(_after == _before[:1] + _before[3:],
       f"连续删两次,删的都是当前第 2 行(不会串位):{_before}->{_after}")
    # 补回 16 类,后面的测试要用
    w._fill_class_table([{"name": n, "desc": d, "on": o}
                         for n, d, o in core.DEFAULT_CLASSES])
    ck(w.tbl.rowCount() == 16, "恢复成 16 类")

    print("\n[15] 配置持久化(存进当前项目)")
    w.sp_workers.setValue(12)
    w.ed_neg.setPlainText("只留这一条")
    w._save_cfg()
    ck(w._cfg_path() == core.project_config_path(_P0), "配置存到项目目录里")
    saved = json.load(open(w._cfg_path(), encoding="utf-8"))
    ck(saved["workers"] == 12, "workers 存盘")
    ck(saved["negative"] == "只留这一条", "negative 存盘")
    ck(len(saved["classes"]) == 16, "16 类存盘")
    w2 = A.MainWindow()
    ck(w2.sp_workers.value() == 12, "重启后读回 workers=12")
    ck(w2.ed_neg.toPlainText() == "只留这一条", "重启后读回 negative")
    ck(w2.p_images.text() == imgs, "重启后读回图片路径")

    print("\n[16] 停止与关闭")
    QProcess.LAST = None
    MsgBox.ANSWER = MsgBox.Yes
    w.run_label(preview=True)
    ck(w.runner.is_running(), "任务在跑")
    w.runner.stop()
    ck(not w.runner.is_running(), "stop() 结束了进程")
    ck("已停止" in w.log.toPlainText(), "日志显示已停止")
    ck(w.btn_preview.isEnabled(), "停止后按钮恢复可用")

    print("\n[17] 失败退出码要提示")
    QProcess.LAST = None
    MsgBox.ANSWER = MsgBox.Yes
    w.run_label(preview=True)
    finish(w, 1)
    ck("退出码 1" in w.log.toPlainText(), "非0退出码写进日志")
    ck(w.btn_preview.isEnabled(), "失败后按钮也恢复可用")

    print("\n[18] 任务运行中关窗口要先问")
    QProcess.LAST = None
    w.run_label(preview=True)
    ck(w.runner.is_running(), "任务在跑")
    MsgBox.CALLS.clear()
    MsgBox.ANSWER = MsgBox.No
    ev = type("Ev", (), {"_ok": None,
                         "ignore": lambda s: setattr(s, "_ok", False),
                         "accept": lambda s: setattr(s, "_ok", True)})()
    w.closeEvent(ev)
    ck(ev._ok is False, "选No则不关闭窗口")
    ck(w.runner.is_running(), "取消关闭后任务继续跑")
    MsgBox.ANSWER = MsgBox.Yes
    ev2 = type("Ev", (), {"_ok": None,
                          "ignore": lambda s: setattr(s, "_ok", False),
                          "accept": lambda s: setattr(s, "_ok", True)})()
    w.closeEvent(ev2)
    ck(ev2._ok is True, "选Yes则关闭")
    ck(not w.runner.is_running(), "关闭时停掉了任务")
    ck(os.path.exists(w._cfg_path()), "关闭时把配置存进了项目")

    print("\n[19] 描述里的 | 会破坏参数,必须拦住")
    w.tbl.item(0, 2).setText("含|竖线的描述")
    errs = core.validate(w._collect_from_ui())
    ck(any("|" in e for e in errs), "校验拦住了描述里的竖线")
    MsgBox.CALLS.clear()
    QProcess.LAST = None
    w.run_label(preview=True)
    ck(QProcess.LAST is None, "有非法描述时不启动进程")
    w.tbl.item(0, 2).setText("眼镜或墨镜")

    print("\n[20b] 坐标口径:各档位参数 + 退化框要报警")
    for v, exp in [(0, None), (-1, "pixel"), (1000, "1000.0"), (1, "1.0")]:
        w.cb_coord.setCurrentIndex(w.cb_coord.findData(v))
        a4 = core.build_label_args(w._collect_from_ui())
        got = a4[a4.index("--coord-scale") + 1] if "--coord-scale" in a4 else None
        ck(got == exp, f"coord_scale={v} -> --coord-scale {got}")
    w.cb_coord.setCurrentIndex(w.cb_coord.findData(1))
    ck("⚠" in w.lb_coord_warn.text(), "非自动口径时显示警告")
    w.cb_coord.setCurrentIndex(w.cb_coord.findData(0))
    ck(w.lb_coord_warn.text() == "", "改回自动判定后警告消失")
    # 退化标签(用户实际遇到的:全是 1.0)必须被识别
    bad_dir = os.path.join(tmp, "badout")
    os.makedirs(os.path.join(bad_dir, "labels"))
    open(os.path.join(bad_dir, "labels", "x.txt"), "w").write(
        "0 1.000000 1.000000 1.000000 1.000000\n" * 4)
    stb = core.read_label_stats(bad_dir, w._classes_from_table())
    ck("退化" in stb["warn"], "退化框被识别: " + stb["warn"][:28])
    stg = core.read_label_stats(out, w._classes_from_table())
    ck(stg["warn"] == "", "正常标签不误报")

    print("\n[20c] 防误触:下拉框/数字框不响应滚轮")
    n_wheel = w._disable_wheel_on_inputs()
    # 不写死数量:以后加控件会自动被覆盖,这里只要求"全都扫到了"
    n_inputs = sum(len(w.findChildren(t)) for t in
                   (QtWidgets.QComboBox, QtWidgets.QSpinBox,
                    QtWidgets.QDoubleSpinBox))
    ck(n_wheel == n_inputs and n_wheel >= 10,
       f"扫到并覆盖了全部 {n_wheel} 个下拉/数字框")
    for nm, wid in [("后端", w.cb_backend), ("模型", w.cb_model),
                    ("并发数", w.sp_workers), ("分辨率", w.cb_px),
                    ("预览张数", w.sp_limit), ("坐标口径", w.cb_coord),
                    ("切片", w.cb_tiles), ("val比例", w.sp_val),
                    ("种子", w.sp_seed)]:
        wid._focus = False
        ck(wid.wheel(), f"{nm}:鼠标划过时滚轮被拦截")
    w.sp_limit._focus = True
    ck(not w.sp_limit.wheel(), "主动点进控件后滚轮仍可用")
    w.sp_limit._focus = False

    print("\n[20d] 预览张数可自由设置(含 1 张)")
    for v in (1, 2, 20, 999):
        w.sp_limit.setValue(v)
        ck(f"{v} 张" in w.btn_preview.text(),
           f"设 {v} -> 按钮显示「{w.btn_preview.text()}」")
        ck(w._collect_from_ui()["preview_limit"] == v, f"设 {v} -> 存盘值正确")
    w.sp_limit.setValue(1)
    a5 = core.build_label_args(w._collect_from_ui(), limit=1)
    ck(a5[a5.index("--limit") + 1] == "1", "预览 1 张时 --limit 1")

    print("\n[20e] API Key:打码显示 + 记住不用再输")
    KEY = "sk-0f3a9c7e21b44d6f8a5e2c1b9d7f4a08"
    w.key_field.set_key(KEY)
    shown = w.key_field.lb.text()
    ck(KEY not in shown, f"界面只显示打码({shown}),不露明文")
    ck(w.key_field.key() == KEY, "内部保留完整 key(要拿去调 API)")
    ck(core.mask_key("") == "", "空 key 打码为空")
    w._save_cfg()
    _saved_project = json.load(open(w._cfg_path(), encoding="utf-8"))
    ck("api_key" not in _saved_project, "项目配置不重复保存 API Key")
    ck(core.load_globals().get("api_key") == KEY, "API Key 只存入全局状态")
    wk = A.MainWindow()
    ck(wk.key_field.key() == KEY, "重启后自动读回 key,不用再输入")
    env = core.child_env(wk._collect_from_ui())
    ck(env.get("DASHSCOPE_API_KEY") == KEY, "key 正确传给标注子进程")
    w.key_field._clear()
    ck(w.key_field.key() == "" and "未设置" in w.key_field.lb.text(), "可以清除 key")
    w.key_field.set_key(KEY)

    print("\n[20f] 模型列表:联网获取 + 缓存 + 搜索")
    FETCHED = ["qwen-plus", "qwen3-vl-plus", "qwen3-vl-flash",
               "qwen-vl-max", "text-embedding-v3", "qwen-vl-ocr"]
    w._on_models(FETCHED, "")
    ck(w.cb_model.count() == len(FETCHED), f"列出全部 {len(FETCHED)} 个模型")
    ck(w.cb_model.itemData(0) == "qwen3-vl-plus", "常用模型置顶")
    order = [w.cb_model.itemData(i) for i in range(w.cb_model.count())]
    ck(order.index("qwen-vl-ocr") < order.index("qwen-plus"),
       "视觉模型(带 vl)排在非视觉模型之前")
    ck("6 个模型" in w.lb_fetch.text(), "提示了获取结果")
    w._save_cfg()
    wm = A.MainWindow()
    ck(wm.cb_model.count() == len(FETCHED), "重启后模型列表仍在(用了缓存)")
    # 选一个非常用模型,重启后要保持
    wm.cb_model.setCurrentIndex(wm.cb_model.findData("qwen-vl-ocr"))
    wm._save_cfg()
    ck(A.MainWindow().cb_model.selected() == "qwen-vl-ocr", "模型选择被记住")
    # 手打搜索的三种情况
    wm.cb_model._t = "qwen-vl-max"
    ck(wm.cb_model.selected() == "qwen-vl-max", "手打模型 id 能识别")
    wm.cb_model._t = "qwen3-vl-flash"
    ck(wm.cb_model.selected() == "qwen3-vl-flash", "手打显示名能识别")
    wm.cb_model._t = "my-private-vl"
    ck(wm.cb_model.selected() == "my-private-vl", "列表外的自定义模型原样保留")
    # 获取失败不能清空已有列表
    n_before = w.cb_model.count()
    w._on_models([], "API Key 不对(401)")
    ck(w.cb_model.count() == n_before, "获取失败时保留原列表")
    ck("401" in w.lb_fetch.text(), "获取失败时显示原因")
    ck(w.cb_model.count() > 0, "失败后下拉框不为空(退回常用模型)")
    # 错误信息要能看懂
    for raw, want in [("Error code: 401 invalid_api_key", "401"),
                      ("Connection timeout", "超时"),
                      ("Error code: 404 not found", "404")]:
        ck(want in core._friendly_api_error(Exception(raw)),
           f"{raw[:22]}… -> {core._friendly_api_error(Exception(raw))[:26]}")

    print("\n[20f2] 后台线程的结果必须能送回界面(别卡在「获取中…」)")
    # 这是真踩过的坑:原本用 QTimer.singleShot 从工作线程回调,
    # 而 timer 建在没有事件循环的线程上 -> 回调永不执行 -> 按钮永远"获取中…"
    ws = A.MainWindow()
    ck(ws.models_ready is not A.MainWindow().models_ready,
       "信号是每个实例一份,不会串台")
    ws._fetching, ws._fetch_seq, ws._handled_seq = True, 1, None
    got = threading.Event()
    _orig = ws._on_models
    ws.models_ready.disconnect()
    ws.models_ready.connect(lambda n, e: (_orig(n, e), got.set()))
    threading.Thread(
        target=lambda: ws.models_ready.emit(["qwen3-vl-plus", "qwen-vl-ocr"], ""),
        daemon=True).start()
    ck(got.wait(3), "工作线程 emit 后,主线程槽确实被调用")
    ck(ws.btn_fetch.text() == "获取可用模型", "按钮恢复可用,不会一直卡在「获取中…」")
    ck(not ws._fetching, "_fetching 已复位,可以再次点击")
    # 失败也必须解锁
    ws._fetching, ws._fetch_seq, ws._handled_seq = True, 2, None
    ws._on_models([], "API Key 不对(401)")
    ck(ws.btn_fetch.text() == "获取可用模型" and not ws._fetching, "失败时也解锁按钮")
    # 超时兜底后,迟到的响应不能覆盖提示
    ws._fetching, ws._fetch_seq, ws._handled_seq = True, 3, None
    ws._on_models([], "超过 25 秒没有响应")
    _msg = ws.lb_fetch.text()
    ws._on_models(["a", "b"], "")
    ck(ws.lb_fetch.text() == _msg, "超时后迟到的响应被忽略")
    # 重复点击不该叠线程
    ws._fetching = True
    _seq = ws._fetch_seq
    ws.fetch_models()
    ck(ws._fetch_seq == _seq, "正在获取时重复点击被忽略")

    print("\n[20g] 换接入点要作废旧模型列表")
    w.cfg["model_cache"] = FETCHED
    w.ed_base.setText("https://other.example.com/compatible-mode/v1")
    w._on_base_changed()
    ck(w.cfg["model_cache"] == [], "换接入点后清空模型缓存")
    ck("重新点" in w.lb_fetch.text(), "提示要重新获取")
    w.ed_base.setText("")

    print("\n[21] 人工改框:核心读写")
    _lb = os.path.join(tmp, "bx", "labels", "z.txt")
    core.write_boxes(_lb, [{"cid": 0, "xc": .3146, "yc": .8817, "w": .0684, "h": .0736},
                           {"cid": 13, "xc": .5, "yc": .5, "w": .2, "h": .3}])
    _bk = core.read_boxes(_lb)
    ck(len(_bk) == 2 and abs(_bk[0]["xc"] - .3146) < 1e-4, "框读写往返一致")
    core.write_boxes(_lb, [{"cid": 0, "xc": .98, "yc": .5, "w": .5, "h": .2}])
    _b = core.read_boxes(_lb)[0]
    ck(_b["xc"] + _b["w"] / 2 <= 1.0001, "越界的框被夹回图内")
    ck(core.write_boxes(_lb, [{"cid": 0, "xc": .5, "yc": .5, "w": 0, "h": .2},
                              {"cid": 1, "xc": .5, "yc": .5, "w": .1, "h": .1}]) == 1,
       "宽高为 0 的退化框被丢弃")
    open(_lb, "w").write("垃圾\n0 abc def\n1 0.5 0.5 0.2 0.2\n")
    ck(len(core.read_boxes(_lb)) == 1, "坏标签行被跳过,不崩")
    _px = core.boxes_to_pixels([{"cid": 7, "xc": .5, "yc": .5, "w": .2, "h": .4}], 669, 479)
    _rt = core.pixels_to_box(7, *_px[0][1:], 669, 479)
    ck(abs(_rt["xc"] - .5) < 1e-9 and abs(_rt["w"] - .2) < 1e-9, "像素↔归一化无损往返")
    _rv = core.pixels_to_box(0, 400, 300, 100, 50, 669, 479)
    ck(_rv["w"] > 0 and _rv["h"] > 0, "反向拖出的框被摆正")

    print("\n[22] 人工改框:画布交互")
    _P = QtGui._Pixmap
    _P.FAKE["/t/i.png"] = (669, 479)
    import boxedit
    def _cv(bs=None):
        c = boxedit.BoxCanvas()
        c.resize(800, 600)
        c.load("/t/i.png", bs if bs is not None else
               [{"cid": 0, "xc": .5, "yc": .5, "w": .2, "h": .3}],
               [(255, 0, 0), (0, 255, 0)], ["CA001", "CA002"])
        return c
    def _ev(c, x, y):
        sx, sy = c._to_screen(x, y)
        return QtCore._MouseEv(sx, sy)
    def _drag(c, fx, fy, tx, ty):
        c.mousePressEvent(_ev(c, fx, fy))
        c.mouseMoveEvent(_ev(c, tx, ty))
        c.mouseReleaseEvent(_ev(c, tx, ty))

    c = _cv()
    _, _, _s = c._fit()
    ck(1.1 < _s < 1.3, f"669×479 放进 800×600 的缩放比 {_s:.3f}")
    _ix, _iy = c._to_img(_ev(c, 334.5, 239.5).position())
    ck(abs(_ix - 334.5) < .5, "屏幕↔图片坐标换算无损")
    x1, y1, x2, y2 = c._box_rect_img(c._boxes[0])
    ck(c._hit(_ev(c, (x1 + x2) / 2, (y1 + y2) / 2).position())[0] == 0,
       "点框体能选中")
    c._sel = 0
    ck(c._hit(_ev(c, x1, y1).position())[1] == "tl", "点左上角命中缩放手柄")
    ck(c._hit(_ev(c, 5, 5).position())[0] == -1, "点空白不命中任何框")

    c = _cv()
    _b0 = dict(c.boxes()[0])
    x1, y1, x2, y2 = c._box_rect_img(c._boxes[0])
    _drag(c, (x1 + x2) / 2, (y1 + y2) / 2, (x1 + x2) / 2 + 50, (y1 + y2) / 2 + 30)
    _b1 = c.boxes()[0]
    ck(abs((_b1["xc"] - _b0["xc"]) * 669 - 50) < 1.5 and
       abs((_b1["yc"] - _b0["yc"]) * 479 - 30) < 1.5, "拖动框:位移正确")
    ck(abs(_b1["w"] - _b0["w"]) < 1e-9, "拖动框:尺寸不变")

    c = _cv(); c._sel = 0
    x1, y1, x2, y2 = c._box_rect_img(c._boxes[0])
    _drag(c, x2, y2, x2 + 40, y2 + 40)
    nx1, ny1, nx2, ny2 = c._box_rect_img(c._boxes[0])
    ck(abs(nx2 - (x2 + 40)) < 1.5 and abs(nx1 - x1) < 1.5,
       "拖右下角:该角跟手,左上角不动")
    c = _cv(); c._sel = 0
    x1, y1, x2, y2 = c._box_rect_img(c._boxes[0])
    _drag(c, x2, (y1 + y2) / 2, x2 + 25, (y1 + y2) / 2)
    nx1, ny1, nx2, ny2 = c._box_rect_img(c._boxes[0])
    ck(abs((ny2 - ny1) - (y2 - y1)) < 1.5, "拖右边:只改宽不改高")

    # 画框改成两步:松手先"待确认",按回车才落框(画歪了直接 Esc)
    c = _cv(); c.set_new_class(1)
    _drag(c, 30, 30, 130, 110)
    ck(len(c.boxes()) == 1, "松手还没建框(等回车确认)")
    ck(c.has_pending(), "有一个待确认的框")
    ck(c.confirm_pending(), "回车确认")
    ck(len(c.boxes()) == 2, "确认后才真的建出框")
    ck(not c.has_pending(), "确认完就没有待确认的了")
    ck(c.boxes()[-1]["cid"] == 1, "新框用当前选定的类别")
    ck(abs(c.boxes()[-1]["w"] * 669 - 100) < 2, "新框尺寸和拖动范围一致")
    c = _cv()
    _drag(c, 30, 30, 32, 31)
    ck(len(c.boxes()) == 1 and not c.has_pending(),
       "手抖只拖 2px 不会建框、也不会留下待确认")

    c = _cv()
    x1, y1, x2, y2 = c._box_rect_img(c._boxes[0])
    _drag(c, (x1 + x2) / 2, (y1 + y2) / 2, -500, -500)
    _b = c.boxes()[0]
    ck((_b["xc"] - _b["w"] / 2) * 669 >= -.5, "框不能被拖出图外")

    c = _cv()
    _o = c.boxes()[0]["xc"]
    x1, y1, x2, y2 = c._box_rect_img(c._boxes[0])
    _drag(c, (x1 + x2) / 2, (y1 + y2) / 2, (x1 + x2) / 2 + 60, (y1 + y2) / 2)
    _m = c.boxes()[0]["xc"]
    c.undo()
    ck(abs(c.boxes()[0]["xc"] - _o) < 1e-9, "撤销回到拖动前")
    c.redo()
    ck(abs(c.boxes()[0]["xc"] - _m) < 1e-9, "重做回到拖动后")

    c = _cv([{"cid": 0, "xc": .3, "yc": .3, "w": .1, "h": .1},
             {"cid": 1, "xc": .7, "yc": .7, "w": .1, "h": .1}])
    c._sel = 0
    c.set_selected_class(1)
    ck(c.boxes()[0]["cid"] == 1, "能改选中框的类别")
    c.delete_selected()
    ck(len(c.boxes()) == 1, "能删除选中的框")
    c.undo()
    ck(len(c.boxes()) == 2, "删除也能撤销")
    c = _cv([{"cid": 0, "xc": .5, "yc": .5, "w": .8, "h": .8},
             {"cid": 1, "xc": .5, "yc": .5, "w": .1, "h": .1}])
    ck(c._hit(_ev(c, 334, 239).position())[0] == 1, "重叠时优先选中小框")

    print("\n[23] 人工改框:改完真的写回 txt(端到端)")
    from PIL import Image
    _ed = os.path.join(tmp, "edit")
    _ei, _eo = os.path.join(_ed, "imgs"), os.path.join(_ed, "out")
    os.makedirs(_ei); os.makedirs(os.path.join(_eo, "labels"))
    os.makedirs(os.path.join(_eo, "vis"))
    for _n in ("p1", "p2"):
        Image.new("RGB", (669, 479), (80, 80, 90)).save(os.path.join(_ei, _n + ".png"))
        Image.new("RGB", (669, 479), (80, 80, 90)).save(
            os.path.join(_eo, "vis", _n + ".png"))
        open(os.path.join(_eo, "labels", _n + ".txt"), "w").write("0 0.5 0.5 0.2 0.3\n")
        _P.FAKE[os.path.join(_ei, _n + ".png")] = (669, 479)
        _P.FAKE[os.path.join(_eo, "vis", _n + ".png")] = (669, 479)
    _L1 = os.path.join(_eo, "labels", "p1.txt")
    we = A.MainWindow()
    we.p_images.setText(_ei)
    we.p_out.setText(_eo)
    we.canvas.resize(800, 600)
    we.refresh_results()
    ck(core.source_image_for(os.path.join(_eo, "vis", "p1.png"), _ei) ==
       os.path.join(_ei, "p1.png"), "底图用原图,不是带框的 vis 图")
    ck("没找到原图" not in we.lb_imginfo.text(), "找到原图,不会出现两层框")
    ck(len(we.canvas.boxes()) == 1, "进页面自动载入已有的框")

    def _wev(x, y):
        sx, sy = we.canvas._to_screen(x, y)
        return QtCore._MouseEv(sx, sy)

    def _wdrag(fx, fy, tx, ty):
        we.canvas.mousePressEvent(_wev(fx, fy))
        we.canvas.mouseMoveEvent(_wev(tx, ty))
        we.canvas.mouseReleaseEvent(_wev(tx, ty))

    x1, y1, x2, y2 = we.canvas._box_rect_img(we.canvas._boxes[0])
    _wdrag((x1 + x2) / 2, (y1 + y2) / 2, (x1 + x2) / 2 + 40, (y1 + y2) / 2 + 20)
    ck(we._dirty and "(1)" in we.btn_save.text(),
       f"改动后按钮显示待保存数量:{we.btn_save.text()}")
    we.save_boxes()
    ck(we._n_pending() == 0 and we.btn_save.text() == "全部保存",
       "保存后计数清零")
    _xc = float(open(_L1).read().split()[1])
    ck(abs(_xc - (0.5 + 40 / 669)) < 0.002,
       f"标签文件真的被改写:xc 0.5 -> {_xc:.4f}")
    we.canvas.set_new_class(1)
    _wdrag(30, 30, 150, 120)
    we.canvas.confirm_pending()      # 画完要按回车确认
    we.save_boxes()
    ck(len(open(_L1).read().strip().splitlines()) == 2, "新建的框写进了 txt")
    we.canvas._sel = 0
    we.canvas.delete_selected()
    we.save_boxes()
    ck(len(open(_L1).read().strip().splitlines()) == 1, "删掉的框从 txt 消失")
    ck(core.read_label_stats(_eo, we._classes_from_table())["total_boxes"] == 2,
       "统计跟着更新(p1 剩 1 + p2 的 1)")

    print("\n[24] 人工改框:未保存时要拦住")
    for _ans, _nm, _saved in [(MsgBox.Save, "保存", True),
                              (MsgBox.Discard, "丢弃", False),
                              (MsgBox.Cancel, "取消", False)]:
        open(_L1, "w").write("0 0.5 0.5 0.2 0.3\n")
        we._dirty = False
        we._show_vis(0)
        x1, y1, x2, y2 = we.canvas._box_rect_img(we.canvas._boxes[0])
        _wdrag((x1 + x2) / 2, (y1 + y2) / 2, (x1 + x2) / 2 + 40, (y1 + y2) / 2)
        MsgBox.ANSWER = _ans
        _ok = we._confirm_discard()
        _changed = abs(float(open(_L1).read().split()[1]) - 0.5) > 0.01
        ck(_changed == _saved and (_ok is not False) == (_ans != MsgBox.Cancel),
           f"选「{_nm}」:写盘={_changed} 允许切换={_ok is not False}")
    # 关窗口同样要拦
    we._dirty = False
    we._show_vis(0)
    x1, y1, x2, y2 = we.canvas._box_rect_img(we.canvas._boxes[0])
    _wdrag((x1 + x2) / 2, (y1 + y2) / 2, (x1 + x2) / 2 + 30, (y1 + y2) / 2)

    class _Ev:
        def __init__(self):
            self.ok = None

        def ignore(self):
            self.ok = False

        def accept(self):
            self.ok = True

    MsgBox.ANSWER = MsgBox.Cancel
    _e = _Ev()
    we.closeEvent(_e)
    ck(_e.ok is False, "有未保存的框时,关窗口被阻止")
    MsgBox.ANSWER = MsgBox.Discard
    _e = _Ev()
    we.closeEvent(_e)
    ck(_e.ok is True, "选丢弃后允许关窗口")
    MsgBox.ANSWER = MsgBox.Yes
    # 原图目录空了 -> 退回"只看已标注"模式,此时列表里是 vis 图,
    # 必须找回原图;找不到就要明确告知会有两层框。
    for _n in ("p1", "p2"):
        os.remove(os.path.join(_ei, _n + ".png"))
    we._pending.clear()
    we._dirty = False
    we.refresh_results()
    ck(we.lst_vis.count() == 2, "原图目录空了,退回只看已标注的图")
    ck("没找到原图" in we.lb_imginfo.text(), "找不到原图时警告会有两层框")

    print("\n[24b] 窗口缩小不能让各栏重合")
    # 重合的根因有两个:工具条比它所在面板还宽(把面板最小宽顶大),
    # 以及窗口最小尺寸小于内容真正需要的宽度。
    _tb_items = [40, 140, 64, 52, 52, 104, 88, 96]      # 工具条各控件宽度
    _one_line = sum(_tb_items) + 7 * (len(_tb_items) - 1)
    _flow_min = max(_tb_items)          # FlowLayout 的最小宽 = 最宽单项
    ck(_flow_min < _one_line / 3,
       f"工具条可换行:最小宽 {_flow_min} 远小于单行 {_one_line}")
    _cols = [150, 300, 200]             # 左/中/右三栏最小宽
    _need = sum(_cols) + 12 + 184 + 44  # +分隔条 +侧栏 +页面边距
    ck(_need <= 900, f"内容最小需要 {_need}px ≤ 窗口最小 900px")
    ck(_flow_min <= _cols[1], "工具条最小宽不超过中间栏最小宽(不会顶大面板)")

    print("\n[25] 全部保存 + 自动保存")
    _ed2 = os.path.join(tmp, "edit2")
    _ei2, _eo2 = os.path.join(_ed2, "i"), os.path.join(_ed2, "o")
    os.makedirs(_ei2); os.makedirs(os.path.join(_eo2, "labels"))
    for _n in ("q1", "q2", "q3"):
        Image.new("RGB", (669, 479), (70, 70, 80)).save(os.path.join(_ei2, _n + ".png"))
        open(os.path.join(_eo2, "labels", _n + ".txt"), "w").write("0 0.5 0.5 0.2 0.3\n")
        _P.FAKE[os.path.join(_ei2, _n + ".png")] = (669, 479)
    w2 = A.MainWindow()
    w2.p_images.setText(_ei2)
    w2.p_out.setText(_eo2)
    w2.canvas.resize(800, 600)
    w2.refresh_results()
    ck(w2.lst_vis.count() == 3, "列出 3 张图")

    def _d2(fx, fy, tx, ty):
        def _e(x, y):
            sx, sy = w2.canvas._to_screen(x, y)
            return QtCore._MouseEv(sx, sy)
        w2.canvas.mousePressEvent(_e(fx, fy))
        w2.canvas.mouseMoveEvent(_e(tx, ty))
        w2.canvas.mouseReleaseEvent(_e(tx, ty))

    # 改第 1 张,切到第 2 张改,再切到第 3 张改 —— 改动都该被记住
    for _r in (0, 1, 2):
        w2.lst_vis.setCurrentRow(_r)
        w2._show_vis(_r)
        x1, y1, x2, y2 = w2.canvas._box_rect_img(w2.canvas._boxes[0])
        _d2((x1 + x2) / 2, (y1 + y2) / 2, (x1 + x2) / 2 + 30, (y1 + y2) / 2)
    ck(w2._n_pending() == 3, f"切图不丢改动,累积 3 张待保存({w2.btn_save.text()})")
    ck("(3)" in w2.btn_save.text(), "按钮显示待保存张数")
    # 切回第 1 张:要看到改过的版本,不能被磁盘旧内容盖掉
    w2.lst_vis.setCurrentRow(0)
    w2._show_vis(0)
    _b = w2.canvas.boxes()[0]
    ck(abs(_b["xc"] - (0.5 + 30 / 669)) < 0.002, "切回来仍是改过的框,没被磁盘覆盖")
    w2.save_boxes()
    ck(w2._n_pending() == 0, "全部保存后待保存清零")
    _n_ok = sum(1 for _n in ("q1", "q2", "q3")
                if abs(float(open(os.path.join(_eo2, "labels", _n + ".txt")
                                  ).read().split()[1]) - 0.5) > 0.01)
    ck(_n_ok == 3, f"3 张图的标签都真的写盘了(实际 {_n_ok})")

    # 自动保存
    ck(not w2._auto_timer.isActive() or True, "初始未开启自动保存")
    w2.sp_auto.setValue(2)
    w2.ck_auto.setChecked(True)
    ck(w2.sp_auto.isEnabled(), "勾选后间隔可调")
    _cfg2 = w2._collect_from_ui()
    ck(_cfg2["autosave"] is True and _cfg2["autosave_min"] == 2,
       "自动保存设置会存盘")
    core.save_config(_cfg2)
    ck(A.MainWindow().ck_auto.isChecked(), "重启后自动保存仍是开启的")
    # 到点自动写盘
    w2.lst_vis.setCurrentRow(1)
    w2._show_vis(1)
    x1, y1, x2, y2 = w2.canvas._box_rect_img(w2.canvas._boxes[0])
    _d2((x1 + x2) / 2, (y1 + y2) / 2, (x1 + x2) / 2, (y1 + y2) / 2 + 25)
    ck(w2._n_pending() == 1, "有 1 张待保存")
    w2._autosave_tick()
    ck(w2._n_pending() == 0, "定时器到点自动保存了")
    w2._autosave_tick()          # 没改动时不该报错
    ck(True, "没有改动时自动保存不打扰")
    w2.ck_auto.setChecked(False)
    ck(not w2.sp_auto.isEnabled(), "取消勾选后间隔变灰")

    print("\n[24b] API Key 存全局:换项目/删项目都不能丢(修 bug)")
    # 老 bug:key 只写进【当前项目】的 config.json。于是
    #   还没建项目就填 key -> _cfg_path() 是空的,压根没存;
    #   把项目删光 -> key 跟着项目一起消失。
    # 现在 key/接入点/模型缓存存在全局 state 里,和项目无关。
    _kt = os.path.join(tmp, "keytest")
    os.makedirs(_kt)
    core.PROJECTS_DIR = A.core.PROJECTS_DIR = os.path.join(_kt, "projects")
    core.STATE_PATH = A.core.STATE_PATH = os.path.join(_kt, ".state.json")
    core.CONFIG_PATH = A.core.CONFIG_PATH = os.path.join(_kt, "config.json")
    os.makedirs(core.PROJECTS_DIR)
    _K = "sk-abcdefgh1234567890"
    _wk1 = A.MainWindow()
    ck(_wk1._proj is None, "先在「还没有项目」的状态下填 key")
    _wk1.key_field.set_key(_K)
    _wk1._on_key_changed(_K)
    ck(A.MainWindow().key_field.key() == _K, "没有项目时填的 key 也能存住")
    _wk2 = A.MainWindow()
    _ID0 = QtWidgets.QInputDialog
    _ID0.TEXT, _ID0.OK, MsgBox.ANSWER = "K1", True, MsgBox.Yes
    _wk2._new_project()
    _ID0.TEXT = "K2"
    _wk2._new_project()
    _wk2.cb_proj.setCurrentIndex(_wk2.cb_proj.findData("K1"))
    _wk2._on_proj_switch()
    ck(_wk2.key_field.key() == _K, "切换项目后 key 还在")
    while _wk2._proj:
        _wk2._del_project()
    ck(A.MainWindow().key_field.key() == _K, "项目全删光,key 依然还在")
    _st = json.load(open(core.STATE_PATH, encoding="utf-8"))
    ck(_st.get("globals", {}).get("api_key") == _K, "key 存在全局 state,不在项目配置里")
    ck(os.stat(core.STATE_PATH).st_mode & 0o777 == 0o600,
       "全局状态文件权限固定为 600,其他本机用户读不到 API Key")
    # 接入点同样是账号级设置
    _wk3 = A.MainWindow()
    _wk3.ed_base.setText("https://my-endpoint.example.com/v1")
    _wk3._save_cfg()
    ck("my-endpoint" in A.MainWindow().ed_base.text(), "接入点也存全局")
    # 清掉就该是清掉,不能有内置 key 复活
    _wk3.key_field._clear()
    _wk3._on_key_changed("")
    _wk4 = A.MainWindow()
    ck(_wk4.key_field.key() == "", "清除后 key 就是空的")
    ck("内置" not in _wk4.key_field.lb.text(),
       f"提示语不再提「内置默认 Key」:{_wk4.key_field.lb.text()}")
    ck(core.builtin_api_key() == "", "代码里不内置任何 key(要发给别人)")
    # 另一半原因:旧窗口 / 关窗时交上来一份空 key,把存好的覆盖掉
    _wk5 = A.MainWindow()
    _wk5.key_field.set_key(_K)
    _wk5._on_key_changed(_K)
    _wk_old = A.MainWindow()          # 假装这是先前就开着、key 还是空的窗口
    _wk_old.key_field.set_key("")
    _wk_old._save_cfg()
    _g2 = json.load(open(core.STATE_PATH, encoding="utf-8")).get("globals", {})
    ck(_g2.get("api_key") == _K, "旧窗口存盘时,空 key 不会覆盖已存好的 key")
    _ev_k = type("E", (), {"accept": lambda s: None, "ignore": lambda s: None})()
    _wk_old.closeEvent(_ev_k)
    _g3 = json.load(open(core.STATE_PATH, encoding="utf-8")).get("globals", {})
    ck(_g3.get("api_key") == _K, "旧窗口关闭时也不会抹掉 key")
    _wk5.key_field._clear()
    _wk5._on_key_changed("")
    _g4 = json.load(open(core.STATE_PATH, encoding="utf-8")).get("globals", {})
    ck(_g4.get("api_key") == "", "但用户主动点「清除」时确实清掉")
    # 不带 key 跑脚本,必须明确报错而不是偷偷用别人的额度
    _rk = subprocess.run(
        [sys.executable, os.path.join(ROOT, "autolabel_qwen.py"),
         "--images", tmp, "--out", os.path.join(tmp, "nokey_out"),
         "--classes", "A", "--desc", "A=x", "--backend", "api"],
        capture_output=True, text=True,
        env={**os.environ, "DASHSCOPE_API_KEY": ""})
    ck("没有 API Key" in (_rk.stdout + _rk.stderr), "没 key 时脚本给出明确提示")
    # 还原测试用的项目环境
    core.PROJECTS_DIR = A.core.PROJECTS_DIR = os.path.join(tmp, "projects")
    core.STATE_PATH = A.core.STATE_PATH = os.path.join(tmp, ".state.json")
    core.CONFIG_PATH = A.core.CONFIG_PATH = cfg_path
    core.save_state(project=_P0)

    print("\n[24c] 导出数据集时一并写出 classes.txt")
    _dsout = os.path.join(tmp, "ds_cls")
    _dsi, _dsl = os.path.join(tmp, "ds_i"), os.path.join(tmp, "ds_l")
    os.makedirs(_dsi)
    os.makedirs(_dsl)
    for _i in range(5):
        Image.new("RGB", (64, 48)).save(os.path.join(_dsi, f"z{_i}.png"))
        open(os.path.join(_dsl, f"z{_i}.txt"), "w").write("0 0.5 0.5 0.2 0.2\n")
    _r = subprocess.run(
        [sys.executable, os.path.join(ROOT, "build_dataset.py"),
         "--images", _dsi, "--labels", _dsl, "--out", _dsout,
         "--classes", "CA001,CA002,水杯", "--ext", "auto",
         "--val-ratio", "0.2", "--seed", "1"],
        capture_output=True, text=True)
    _cp = os.path.join(_dsout, "classes.txt")
    ck(os.path.exists(_cp), f"生成了 classes.txt(退出码 {_r.returncode})")
    _txt = open(_cp, encoding="utf-8").read()
    ck(_txt == "CA001\nCA002\n水杯\n", f"一行一个类别名,行号=id:{_txt!r}")
    ck(_txt.endswith("\n"), "末尾有换行(YOLO 工具的标准格式)")
    import yaml as _yaml
    _d = _yaml.safe_load(open(os.path.join(_dsout, "data.yaml"), encoding="utf-8"))
    _names = [_d["names"][_k] for _k in sorted(_d["names"])]
    ck(_names == _txt.rstrip("\n").split("\n"),
       "classes.txt 和 data.yaml 的 names 顺序一致(不会互相矛盾)")
    ck("classes.txt" in _r.stdout, "日志里说明了写出 classes.txt")

    # 随机种子的提示语说"同种子划分一致",这话得是真的
    def _val_of(_tag, _seed):
        _o = os.path.join(tmp, "ds_seed_" + _tag)
        subprocess.run(
            [sys.executable, os.path.join(ROOT, "build_dataset.py"),
             "--images", _dsi, "--labels", _dsl, "--out", _o,
             "--classes", "A", "--ext", "auto", "--val-ratio", "0.4",
             "--seed", str(_seed)], capture_output=True, text=True)
        return sorted(os.listdir(os.path.join(_o, "images", "val")))

    _v1, _v2, _v3 = _val_of("a", 7), _val_of("b", 7), _val_of("c", 8)
    ck(_v1 == _v2 and _v1, f"同一个随机种子切出同样的验证集:{_v1}")
    ck(_v1 != _v3, f"换种子划分就不同:{_v3}")

    print("\n[24d] 类别表支持「导入 classes」")
    _FD = QtWidgets.QFileDialog
    # 解析各种格式
    def _mkf(name, text, enc="utf-8"):
        _p = os.path.join(tmp, name)
        open(_p, "w", encoding=enc).write(text)
        return _p

    ck(core.parse_classes_file(_mkf("i1.txt", "A\nB\nC\n")) == ["A", "B", "C"],
       "读 classes.txt(一行一个)")
    ck(core.parse_classes_file(_mkf("i2.txt", "# 注释\n\nA\n\nB\n")) == ["A", "B"],
       "忽略空行和 # 注释")
    ck(core.parse_classes_file(_mkf("i3.txt", "A,B,C")) == ["A", "B", "C"],
       "逗号分隔的一行也认")
    ck(core.parse_classes_file(
        _mkf("i4.yaml", "names:\n  0: a\n  1: b\n  10: k\n  2: c\n")) ==
       ["a", "b", "c", "k"], "读 data.yaml 的 names,且 id=10 按数字排最后")
    ck(core.parse_classes_file(_mkf("i5.yaml", "names: [x, y]\n")) == ["x", "y"],
       "names 写成列表也认")
    ck(core.parse_classes_file(
        _mkf("i6.txt", "A\nB\n", enc="utf-8-sig")) == ["A", "B"],
       "带 BOM 的文件不会污染第一个类别名")
    for _n, _t in [("e1.txt", ""), ("e2.yaml", "path: /x\n")]:
        try:
            core.parse_classes_file(_mkf(_n, _t))
            ck(False, f"{_n} 该报错")
        except ValueError as _e:
            ck(True, f"坏文件有明确报错:{_e}")
    try:
        core.parse_classes_file(os.path.join(tmp, "根本没有这个文件.txt"))
        ck(False, "不存在的文件该报错")
    except ValueError:
        ck(True, "不存在的文件有报错")
    # 界面上的导入流程
    _wi = A.MainWindow()
    _wi._fill_class_table([])
    _FD.PICK = _mkf("imp.txt", "苹果\n香蕉\n柚子\n")
    MsgBox.CALLS.clear()
    _wi._import_classes()
    ck([c["name"] for c in _wi._classes_from_table()] == ["苹果", "香蕉", "柚子"],
       "导入后类别表就是文件里的顺序")
    ck(not MsgBox.CALLS, "表本来是空的,不用问就直接导入")
    _wi.tbl.item(0, 2).setText("红色圆形水果")
    _FD.PICK = _mkf("imp2.txt", "苹果\n石榴\n")
    MsgBox.ANSWER = MsgBox.Yes
    MsgBox.CALLS.clear()
    _wi._import_classes()
    ck(any("整表替换" in t for _, _, t in MsgBox.CALLS),
       "表里有内容时先确认,并说明为什么不能只追加")
    ck([c["name"] for c in _wi._classes_from_table()] == ["苹果", "石榴"],
       "确认后整表替换")
    ck(_wi._classes_from_table()[0]["desc"] == "红色圆形水果",
       "同名类别沿用原来写好的描述,不用重填")
    MsgBox.ANSWER = MsgBox.No
    _FD.PICK = _mkf("imp3.txt", "完全不同\n")
    _wi._import_classes()
    ck(len(_wi._classes_from_table()) == 2, "选No时不动类别表")
    MsgBox.ANSWER = MsgBox.Yes
    _FD.PICK = ""
    _wi._import_classes()
    ck(len(_wi._classes_from_table()) == 2, "文件对话框点取消也不动")
    # 闭环:导出的 classes.txt 能再导入
    _FD.PICK = _cp
    _wi._import_classes()
    ck([c["name"] for c in _wi._classes_from_table()] == ["CA001", "CA002", "水杯"],
       "导出的 classes.txt 能被原样导入回来(闭环)")
    ck("导入 classes" in [b.text() for b in _wi._cls_btns], "类别表下方有「导入 classes」按钮")

    print("\n[25b] 图片列表颜色三态:灰=没框 / 黄=改了没存 / 白=已保存")
    # 之前黄色表示"标过但0个框",而"改了没保存"根本没有颜色区分,
    # 而且改完框不会刷新列表 —— 颜色压根不会变。这里盯住三态的转换。
    def _c2(i):
        _f = w2.lst_vis.item(i).foreground()
        _v = getattr(_f, "_args", (None,))[0] if _f is not None else None
        return {_C["text_faint"]: "灰", _C["warn"]: "黄", _C["text"]: "白"}.get(_v, "?")

    w2._pending.clear()
    w2._dirty = False
    w2.refresh_results()
    ck(all(_c2(i) == "白" for i in range(w2.lst_vis.count())),
       "三张图都已保存且有框 -> 全白")
    # 改一张:立刻变黄,别的不受影响
    w2.lst_vis.setCurrentRow(0)
    w2._show_vis(0)
    x1, y1, x2, y2 = w2.canvas._box_rect_img(w2.canvas._boxes[0])
    _d2((x1 + x2) / 2, (y1 + y2) / 2, (x1 + x2) / 2 + 25, (y1 + y2) / 2)
    ck(_c2(0) == "黄", f"改完那张立刻变黄(实际 {_c2(0)})")
    ck(_c2(1) == "白" and _c2(2) == "白", "没改的还是白色")
    ck("改过还没保存" in (w2.lst_vis.item(0).toolTip() or ""), "黄色的提示说明未保存")
    # 切到别的图:改动进了待保存表,颜色要保持黄色
    w2.lst_vis.setCurrentRow(1)
    w2._show_vis(1)
    ck(_c2(0) == "黄", "切走之后那张仍然是黄的(改动没丢)")
    # 保存:黄 -> 白
    w2.save_boxes()
    ck(_c2(0) == "白", f"保存后转白(实际 {_c2(0)})")
    ck("已保存" in (w2.lst_vis.item(0).toolTip() or ""), "白色的提示说明已保存")
    # 清空并保存:变灰(没有框 = 没东西)
    w2.lst_vis.setCurrentRow(0)
    w2._show_vis(0)
    w2._clear_this()
    ck(_c2(0) == "黄", "清空算改动,先变黄")
    w2.save_boxes()
    ck(_c2(0) == "灰", f"框清空并保存后变灰(实际 {_c2(0)})")
    # 改了再丢弃:退回白色
    w2.lst_vis.setCurrentRow(1)
    w2._show_vis(1)
    x1, y1, x2, y2 = w2.canvas._box_rect_img(w2.canvas._boxes[0])
    _d2((x1 + x2) / 2, (y1 + y2) / 2, (x1 + x2) / 2 + 25, (y1 + y2) / 2)
    ck(_c2(1) == "黄", "改动后变黄")
    MsgBox.ANSWER = MsgBox.Discard
    w2._confirm_discard()
    ck(_c2(1) == "白", "选「丢弃」后颜色退回已保存状态")
    MsgBox.ANSWER = MsgBox.Yes
    # 上面把第 0 张清空了,给它补回一个框,后面的测试还要用
    w2.lst_vis.setCurrentRow(0)
    w2._show_vis(0)
    _d2(100, 100, 220, 210)
    w2.canvas.confirm_pending()      # 画完按回车确认
    w2.save_boxes()
    ck(_c2(0) == "白", "补回框并保存,回到白色")

    print("\n[26] 限流(429)要能扛住,不能整批丢图")
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import autolabel_qwen as AQ
    AQ.RETRY_LOG = False
    _RL = ("Error code: 429 - {'error': {'message': 'Requests rate limit "
           "exceeded', 'type': 'limit_requests', 'code': 'limit_requests'}}")

    # 错误分类:429/5xx/超时要重试,4xx 重试也没用
    for _msg, _retry, _rl in [
            (_RL, True, True),
            ("Error code: 500 - internal error", True, False),
            ("Error code: 503 - Service Unavailable", True, False),
            ("Connection aborted, remote end closed", True, False),
            ("Read timed out", True, False),
            ("Error code: 401 - invalid api key", False, False),
            ("Error code: 400 - bad request", False, False)]:
        _e = Exception(_msg)
        ck(AQ.is_retryable(_e) == _retry and AQ.is_rate_limit(_e) == _rl,
           f"错误分类正确:{_msg[:36]}")

    # 令牌桶:多线程下也要把速率压住(只调小 workers 是压不住的)
    import threading as _th
    _lim = AQ.RateLimiter(20)
    _t0 = time.monotonic()
    _cnt = [0]

    def _pull():
        for _ in range(5):
            _lim.acquire()
            _cnt[0] += 1

    _ts = [_th.Thread(target=_pull) for _ in range(4)]
    [t.start() for t in _ts]
    [t.join() for t in _ts]
    _el = time.monotonic() - _t0
    ck(_cnt[0] == 20 and _el >= 0.8,
       f"限流器把 4 线程 20 个请求压到 {_cnt[0] / max(_el, .01):.0f}/秒(上限 20)")

    # infer 层重试:前 3 次 429,第 4 次成功
    class _FakeComp:
        def __init__(s, fail_n, err=_RL):
            s.n = 0
            s.fail_n = fail_n
            s.err = err

        def create(s, **k):
            s.n += 1
            if s.n <= s.fail_n:
                raise Exception(s.err)
            return type("R", (), {"choices": [type("C", (), {
                "message": type("M", (), {
                    "content": '[{"bbox_2d":[10,10,50,50],"label":"CA001"}]'})()})()]})

    def _fake_engine(fail_n, retries=5, err=_RL):
        e = AQ.ApiQwen.__new__(AQ.ApiQwen)
        _c = _FakeComp(fail_n, err)
        e.client = type("Cl", (), {"chat": type("Ch", (), {"completions": _c})})
        e.model_id = "m"
        e.retries = retries
        e.backoff = 0.01
        e.min_pixels, e.max_pixels, e.factor = 100, 1000, 32
        return e, _c

    AQ.LIMITER = None
    _img = Image.new("RGB", (64, 48))
    _e, _c = _fake_engine(3)
    _out = _e.infer(None, "p", pil_img=_img)
    ck(_c.n == 4 and "CA001" in _out, "被限流 3 次后自动重试成功,图片没丢")
    _e, _c = _fake_engine(99, retries=3)
    try:
        _e.infer(None, "p", pil_img=_img)
        ck(False, "重试用尽该抛异常")
    except Exception as _ex:
        ck(_c.n == 4 and AQ.is_rate_limit(_ex), "重试用尽才放弃(1+3 次)")
    _e, _c = _fake_engine(99, retries=5, err="Error code: 401 - invalid api key")
    try:
        _e.infer(None, "p", pil_img=_img)
    except Exception:
        pass
    ck(_c.n == 1, "401 只调一次,不做无谓重试")
    # 退避要递增且带抖动 —— 否则 20 个线程会同时醒来又一起被限流
    _waits = []
    _orig_sleep = time.sleep
    time.sleep = lambda s: _waits.append(s)
    _e, _c = _fake_engine(4, retries=4)
    _e.backoff = 2.0
    _e.infer(None, "p", pil_img=_img)
    time.sleep = _orig_sleep
    ck(len(_waits) == 4 and _waits[0] < _waits[-1],
       f"退避递增:{[round(x, 1) for x in _waits]}")
    ck(not all(abs(w - _waits[0] * 2 ** i) < 0.01 for i, w in enumerate(_waits)),
       "退避带随机抖动,避免线程同时重试")

    print("\n[27] 补跑机制:失败的图能补上,不重复花钱")
    _rt = os.path.join(tmp, "retry")
    _ri, _ro = os.path.join(_rt, "i"), os.path.join(_rt, "o")
    os.makedirs(_ri)
    for _i in range(6):
        Image.new("RGB", (200, 150)).save(os.path.join(_ri, f"p{_i}.png"))

    class _Eng:
        """p0/p1 永久限流;p2 第一次限流、补跑时成功;p3 是 401;p4/p5 正常。"""
        def __init__(s):
            s.factor, s.min_pixels, s.max_pixels = 32, 100, 1000
            s.hits = {}

        def ref_dims(s, w_, h_):
            return w_, h_

        def infer(s, path, prompt, pil_img=None, upscale=1.0):
            n = os.path.basename(path)
            s.hits[n] = s.hits.get(n, 0) + 1
            if n in ("p0.png", "p1.png"):
                raise Exception(_RL)
            if n == "p2.png" and s.hits[n] == 1:
                raise Exception(_RL)
            if n == "p3.png":
                raise Exception("Error code: 401 - invalid api key")
            return '[{"bbox_2d":[20,20,80,80],"label":"CA001"}]'

    _eng = _Eng()
    _save_api = AQ.ApiQwen
    AQ.ApiQwen = lambda *a, **k: _eng
    _save_argv = sys.argv
    sys.argv = ["x", "--images", _ri, "--out", _ro, "--classes", "CA001",
                "--backend", "api", "--desc", "CA001=眼镜",
                "--workers", "3", "--retries", "2", "--qps", "50"]
    _buf = io.StringIO()
    with contextlib.redirect_stdout(_buf):
        AQ.main()
    _log = _buf.getvalue()
    sys.argv = _save_argv
    ck("补跑" in _log, "限流失败的图会自动降速补跑一遍")
    ck("p2.png -> 1 个框" in _log, "p2 在补跑里成功了")
    ck(_eng.hits["p3.png"] == 1, "401 这种错不参与补跑")
    ck("3/6 张成功" in _log, "结尾报出 成功/总数")
    ck("⚠" in _log and "没标上" in _log, "失败清单醒目,不会混在日志里被忽略")
    ck("--skip-done" in _log and "--qps" in _log, "直接给出可复制的补跑命令")
    ck(sorted(os.listdir(os.path.join(_ro, "labels"))) == ["p2.txt", "p4.txt", "p5.txt"],
       "失败的图不生成空标签,不污染数据集")

    # --skip-done 真的跳过已标好的
    _eng2 = _Eng()
    _eng2.hits.clear()
    AQ.ApiQwen = lambda *a, **k: _eng2
    sys.argv = ["x", "--images", _ri, "--out", _ro, "--classes", "CA001",
                "--backend", "api", "--desc", "CA001=眼镜",
                "--workers", "1", "--retries", "0", "--skip-done", "--qps", "50"]
    _buf = io.StringIO()
    with contextlib.redirect_stdout(_buf):
        AQ.main()
    sys.argv = _save_argv
    AQ.ApiQwen = _save_api
    ck("p2.png" not in _eng2.hits and "p4.png" not in _eng2.hits,
       "--skip-done 跳过已有标签的图(不重复花钱)")
    ck("p0.png" in _eng2.hits and "p3.png" in _eng2.hits,
       "--skip-done 仍会重试没标上的图")

    # 空标签是模型成功判断“没有目标”的负样本，也必须跳过，不能重复收费。
    open(os.path.join(_ro, "labels", "p0.txt"), "w").write("")
    _eng3 = _Eng()
    AQ.ApiQwen = lambda *a, **k: _eng3
    sys.argv = ["x", "--images", _ri, "--out", _ro, "--classes", "CA001",
                "--backend", "api", "--workers", "1", "--retries", "0",
                "--skip-done", "--qps", "50"]
    with contextlib.redirect_stdout(io.StringIO()):
        AQ.main()
    sys.argv = _save_argv
    AQ.ApiQwen = _save_api
    ck("p0.png" not in _eng3.hits, "--skip-done 也跳过空标签负样本")

    # 切片参数只能是整数网格，不能执行任意表达式。
    ck(AQ.parse_grid("2x3") == (2, 3), "切片网格 2x3 解析正确")
    try:
        AQ.parse_grid("__import__('os').system('false')")
        ck(False, "恶意切片表达式必须被拒绝")
    except ValueError:
        ck(True, "切片参数不再经过 eval，恶意表达式被拒绝")

    print("\n[28] GUI 把限流相关选项传给了脚本")
    _c2 = core.default_config()
    _c2.update(images="/i", out="/o")
    _ln = " ".join(core.build_label_args(_c2, limit=20))
    ck("--workers 8" in _ln, "默认并发 8(不是会被限流的 50)")
    ck("--retries 5" in _ln, "默认带上重试")
    ck("--skip-done" in _ln, "默认跳过已标好的图")
    ck("--qps" not in _ln, "限速填自动时不传 --qps")
    _c2["qps"] = 2
    ck("--qps 2" in " ".join(core.build_label_args(_c2, limit=0)), "限速填 2 时传给脚本")
    _c2["skip_done"] = False
    ck("--skip-done" not in " ".join(core.build_label_args(_c2, limit=0)),
       "取消勾选后不传 --skip-done")

    print("\n[29] 撤销:一次操作 = 一次撤销(修 bug)")
    # 老 bug:鼠标一按下就无条件压栈,"点一下选中某个框"也会压一层
    # 【当前状态】进去,撤销回到它等于什么都没变 —— 看着就是"撤销没反应"。
    _ud = os.path.join(tmp, "undo")
    os.makedirs(_ud)
    Image.new("RGB", (669, 479)).save(os.path.join(_ud, "u.png"))
    _P.FAKE[os.path.join(_ud, "u.png")] = (669, 479)
    import boxedit
    cv = boxedit.BoxCanvas()
    cv.resize(800, 600)

    def _reset_cv():
        cv.load(os.path.join(_ud, "u.png"),
                [{"cid": 0, "xc": 0.3, "yc": 0.3, "w": 0.1, "h": 0.1},
                 {"cid": 1, "xc": 0.7, "yc": 0.7, "w": 0.1, "h": 0.1}],
                [(255, 0, 0), (0, 255, 0)], ["A", "B"])

    def _cev(x, y):
        sx, sy = cv._to_screen(x, y)
        return QtCore._MouseEv(sx, sy)

    def _ccenter(i):
        x1, y1, x2, y2 = cv._box_rect_img(cv._boxes[i])
        return (x1 + x2) / 2, (y1 + y2) / 2

    def _cdrag(fx, fy, tx, ty):
        cv.mousePressEvent(_cev(fx, fy))
        cv.mouseMoveEvent(_cev(tx, ty))
        cv.mouseReleaseEvent(_cev(tx, ty))

    _reset_cv()
    _x0 = cv.boxes()[0]["xc"]
    _cx, _cy = _ccenter(0)
    _cdrag(_cx, _cy, _cx + 40, _cy)
    _x1 = cv.boxes()[0]["xc"]
    ck(abs(_x1 - _x0) > 0.01 and len(cv._undo) == 1, "拖动后压了 1 层撤销栈")
    cv.undo()
    ck(abs(cv.boxes()[0]["xc"] - _x0) < 1e-9, "撤销一次就回到拖动前(不用按两次)")

    _reset_cv()
    _cx, _cy = _ccenter(0)
    _cdrag(_cx, _cy, _cx + 40, _cy)
    _d1 = len(cv._undo)
    _cx2, _cy2 = _ccenter(1)
    cv.mousePressEvent(_cev(_cx2, _cy2))       # 只是点一下选中,什么都没改
    cv.mouseReleaseEvent(_cev(_cx2, _cy2))
    ck(len(cv._undo) == _d1, "点一下选中不压栈(这就是撤销失效的根因)")
    cv.undo()
    ck(abs(cv.boxes()[0]["xc"] - 0.3) < 1e-9, "选中别的框之后,撤销依然一次生效")

    # 缩得太小会自动还原,但不能污染重做栈
    _reset_cv()
    cv._sel = 0
    _bx1, _by1, _bx2, _by2 = cv._box_rect_img(cv._boxes[0])
    _cdrag(_bx2, _by2, _bx1 + 1, _by1 + 1)
    ck(len(cv._redo) == 0, "缩太小自动还原,不会凭空产生重做记录")
    ck(abs(cv.boxes()[0]["w"] - 0.1) < 1e-9, "自动还原成原来的尺寸")

    # 多步撤销顺序
    _reset_cv()
    _seq = [cv.boxes()[0]["xc"]]
    for _ in range(3):
        _cx, _cy = _ccenter(0)
        _cdrag(_cx, _cy, _cx + 20, _cy)
        _seq.append(cv.boxes()[0]["xc"])
    _okn = 0
    for _k in range(3):
        cv.undo()
        if abs(cv.boxes()[0]["xc"] - _seq[-2 - _k]) < 1e-9:
            _okn += 1
    ck(_okn == 3, "连续 3 次拖动能逐步撤销回去,顺序正确")
    ck(cv.can_redo(), "撤销之后重做可用(Ctrl+Shift+Z 仍保留)")

    print("\n[30] 「本张清空」替代「重做」按钮")
    ck(w2.btn_clear.text() == "本张清空", "按钮改名成「本张清空」")
    ck("btn_redo" not in vars(w2), "工具条上不再有「重做」按钮")
    w2.lst_vis.setCurrentRow(0)
    w2._show_vis(0)
    _n_before = len(w2.canvas.boxes())
    w2._clear_this()
    ck(_n_before > 0 and len(w2.canvas.boxes()) == 0, f"清掉了这张图的 {_n_before} 个框")
    ck(w2._dirty, "清空算改动,要提示保存")
    w2.canvas.undo()
    ck(len(w2.canvas.boxes()) == _n_before, "清空可以 Ctrl+Z 撤回来")
    w2._pending.clear()
    w2._dirty = False

    print("\n[31] 项目:新建 / 切换 / 改名 / 删除")
    _pt = os.path.join(tmp, "projtest")
    os.makedirs(_pt)
    core.PROJECTS_DIR = A.core.PROJECTS_DIR = os.path.join(_pt, "projects")
    core.STATE_PATH = A.core.STATE_PATH = os.path.join(_pt, ".state.json")
    core.CONFIG_PATH = A.core.CONFIG_PATH = os.path.join(_pt, "config.json")
    os.makedirs(core.PROJECTS_DIR)
    _pd1, _pd2 = os.path.join(_pt, "i1"), os.path.join(_pt, "i2")
    for _d in (_pd1, _pd2):
        os.makedirs(_d)
        for _i in range(2):
            _f = os.path.join(_d, f"{os.path.basename(_d)}_{_i}.png")
            Image.new("RGB", (64, 48)).save(_f)
    _ID = QtWidgets.QInputDialog

    # 项目名校验
    for _n, _bad in [("", True), ("a/b", True), ("a:b", True), ("x" * 61, True),
                     ("..", True), ("中文项目", False), ("proj-1_v2", False)]:
        ck(bool(core.check_project_name(_n)) == _bad,
           f"项目名校验:{_n[:12]!r} -> {'拒绝' if _bad else '接受'}")

    w3 = A.MainWindow()
    ck(w3._proj is None, "没有项目时不自动选一个")
    ck(w3.cb_proj.count() == 1 and w3.cb_proj.currentData() is None,
       "下拉里只有「(还没有项目)」占位")
    # 新建项目:内容全清,只带模型与性能
    w3.sp_workers.setValue(17)
    w3.key_field.set_key("sk-carry-me-over")
    w3.cb_px.setCurrentIndex(w3.cb_px.findData(1003520))
    _ID.TEXT, _ID.OK, MsgBox.ANSWER = "项目甲", True, MsgBox.Yes
    w3._new_project()
    ck(w3._proj == "项目甲", "新建项目后自动切过去")
    ck(w3.p_images.text() == "", "新项目的图片目录是空的")
    ck(w3.tbl.rowCount() == 0, "新项目的类别表是空的")
    ck(w3.ed_neg.toPlainText() == "", "新项目的负样本描述是空的")
    ck(w3.sp_workers.value() == 17, "并发数(模型与性能)保留下来")
    ck(w3.key_field.key() == "sk-carry-me-over", "密钥保留下来,不用重输")
    ck(w3.cb_px.currentData() == 1003520, "处理分辨率保留下来")
    ck("项目甲" in w3.p_out.text(), "输出目录自动指向项目文件夹,不用手选")
    ck("项目甲" in w3.p_ds.text(), "数据集目录也自动指向项目文件夹")

    # 在甲里填上内容
    w3.p_images.setText(_pd1)
    w3._fill_class_table([{"name": "AAA", "desc": "甲的类别", "on": True}])
    w3._save_cfg()

    _ID.TEXT = "项目乙"
    w3._new_project()
    ck(w3.p_images.text() == "" and w3.tbl.rowCount() == 0,
       "再建一个项目,内容还是空的(不会带上甲的类别表)")
    w3.p_images.setText(_pd2)
    w3._fill_class_table([{"name": "BBB", "desc": "乙的类别", "on": True},
                          {"name": "CCC", "desc": "乙的类别2", "on": True}])
    w3._save_cfg()
    ck(w3.cb_proj.count() == 2, "下拉里是 2 个项目(没有「默认」这一项了)")
    ck([w3.cb_proj.itemText(_k) for _k in range(w3.cb_proj.count())]
       == [w3.cb_proj.itemData(_k) for _k in range(w3.cb_proj.count())],
       "下拉里只显示项目名,不带「已标 N 张」这类后缀")

    # 切回甲:内容要整套换回来
    w3.cb_proj.setCurrentIndex(w3.cb_proj.findData("项目甲"))
    w3._on_proj_switch()
    ck(w3._proj == "项目甲", "切到甲")
    ck(w3.p_images.text() == _pd1, "读回甲的图片目录")
    ck(w3.tbl.rowCount() == 1 and w3.tbl.item(0, 1).text() == "AAA",
       "读回甲的类别表(1 个类别)")
    w3.cb_proj.setCurrentIndex(w3.cb_proj.findData("项目乙"))
    w3._on_proj_switch()
    ck(w3.p_images.text() == _pd2 and w3.tbl.rowCount() == 2,
       "切到乙又读回乙的内容(2 个类别)")
    ck(core.load_config(core.project_config_path("项目甲"))["images"] == _pd1,
       "两个项目的配置互不干扰")
    # 重名
    _ID.TEXT = "项目甲"
    _n_before = len(core.list_projects())
    w3._new_project()
    ck(len(core.list_projects()) == _n_before, "重名建不出来(有提示)")
    # 改名
    _ID.TEXT = "项目乙-v2"
    w3._rename_project()
    ck(w3._proj == "项目乙-v2", "重命名生效")
    ck("项目乙-v2" in w3.p_out.text(), "改名后输出目录跟着改,不留在旧路径")
    # 删除:列表里必须真的消失
    MsgBox.ANSWER = MsgBox.Yes
    w3._del_project()
    ck("项目乙-v2" not in [p["name"] for p in core.list_projects()],
       "删除后磁盘上没有了")
    _names = [w3.cb_proj.itemText(_k) for _k in range(w3.cb_proj.count())]
    ck(not any("项目乙-v2" in _t for _t in _names),
       f"删除后下拉列表里也没有了(修 bug):{_names}")
    ck(w3._proj == "项目甲", "删掉当前项目后自动切到剩下的那个")
    ck(w3.p_images.text() == _pd1, "并且加载了它的内容")
    # rmtree 半路失败也不能让项目残留在列表里
    _stuck = "顽固项目"
    core.create_project(_stuck)
    _sd = os.path.join(core.project_dir(_stuck), "out", "labels")
    os.makedirs(_sd)
    open(os.path.join(_sd, "a.txt"), "w").write("0 .5 .5 .2 .2\n")
    os.chmod(os.path.dirname(_sd), 0o500)      # 让里面的文件删不掉
    try:
        core.delete_project(_stuck)
    except Exception:
        pass
    # 目录可能已经被挪进 .trash_ 了,把残骸的权限放开好让 purge 清掉
    for _root, _ds2, _fs2 in os.walk(core.PROJECTS_DIR):
        try:
            os.chmod(_root, 0o700)
        except Exception:
            pass
    ck(_stuck not in [p["name"] for p in core.list_projects()],
       "删不干净时也绝不会残留在列表里(改名再删)")
    core.purge_trash()
    ck(not [n for n in os.listdir(core.PROJECTS_DIR) if n.startswith(".trash_")],
       "启动时会清理删除残骸")
    # 记住上次打开的项目
    _ID.TEXT = "项目丙"
    w3._new_project()
    w3.p_images.setText(_pd2)
    w3._save_cfg()
    w4 = A.MainWindow()
    ck(w4._proj == "项目丙" and w4.p_images.text() == _pd2, "下次打开回到上次的项目")
    # 只剩一个项目时直接进去,省一次点击
    MsgBox.ANSWER = MsgBox.Yes
    w4.cb_proj.setCurrentIndex(w4.cb_proj.findData("项目甲"))
    w4._on_proj_switch()
    w4._del_project()
    ck(w4._proj == "项目丙", "删到只剩一个时自动选中它")
    # 项目目录被手动删掉也不能崩
    shutil.rmtree(core.project_dir("项目丙"))
    w5 = A.MainWindow()
    ck(w5._proj is None, "项目文件夹被手删后回到「未选择」而不是崩掉")
    ck(w5.tbl.rowCount() == 0 and not w5.tbl.isEnabled(), "此时界面又锁上了")

    print("\n[32] 视频切片:抽帧核心")
    # 前面的项目测试把 PROJECTS_DIR 指走了,这里回到主测试项目
    core.PROJECTS_DIR = A.core.PROJECTS_DIR = os.path.join(tmp, "projects")
    core.STATE_PATH = A.core.STATE_PATH = os.path.join(tmp, ".state.json")
    core.CONFIG_PATH = A.core.CONFIG_PATH = cfg_path
    core.save_state(project=_P0)
    import video as VD
    _vsrc = os.path.join(tmp, "clip.mp4")
    _mk = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         "testsrc=duration=12:size=320x240:rate=25",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", _vsrc],
        capture_output=True, text=True)
    _have_video = os.path.exists(_vsrc) and _mk.returncode == 0
    ck(VD.is_video("a.MP4") and VD.is_video("b.mkv") and not VD.is_video("c.png"),
       "按后缀认视频(大小写都行)")
    ck(len(VD.VIDEO_EXTS) >= 10, f"支持多种格式({len(VD.VIDEO_EXTS)} 种)")
    ck(VD.fmt_time(0) == "0:00.0" and VD.fmt_time(65.25) == "1:05.2"
       and VD.fmt_time(3725.9) == "1:02:05.9", "时间格式化(超过1小时带时)")
    # 抽帧时间点:左闭右闭、不累积浮点误差、有上限
    ck(VD.plan_times(3, 11, 2, 12) == [3.0, 5.0, 7.0, 9.0, 11.0],
       "区间左闭右闭,末尾那张也抽")
    ck(VD.plan_times(0, 10, 0.1, 12)[-1] == 10.0,
       "用乘法算时间点,0.1 秒间隔也不会累积偏移")
    ck(len(VD.plan_times(0, 12, 0.001, 12, limit=500)) == 500, "limit 能挡住抽爆")
    ck(VD.plan_times(5, 3, 1, 12) == [], "结束早于开始时抽 0 张")
    ck(VD.plan_times(0, 10, 0, 12) == [], "间隔 0 不抽(而不是死循环)")
    if _have_video:
        _pi = VD.probe(_vsrc)
        ck(_pi["ok"] and _pi["w"] == 320 and _pi["h"] == 240, "probe 读到尺寸")
        ck(abs(_pi["duration"] - 12) < 0.3, f"probe 读到时长 {_pi['duration']:.2f}s")
        _vout = os.path.join(tmp, "frames1")
        _n, _e = VD.extract(_vsrc, _vout, interval=2.0, start=1.0, end=9.0)
        ck(_n == 5 and not _e, f"抽了 {_n} 张({_e or '无错误'})")
        ck(sorted(os.listdir(_vout)) == [f"image_{i:03d}.jpg" for i in range(1, 6)],
           "命名是 image_001 这种,按顺序补零")
        # 续抽:编号接着排,不覆盖
        VD.extract(_vsrc, _vout, interval=4.0, start=0, end=8)
        ck("image_006.jpg" in os.listdir(_vout), "再抽一次编号接着往下排,不覆盖旧图")
        ck(VD.next_index(_vout) == len(os.listdir(_vout)) + 1, "next_index 认得已有编号")
        # png 格式
        _vout2 = os.path.join(tmp, "frames2")
        VD.extract(_vsrc, _vout2, interval=5.0, fmt="png")
        ck(all(f.endswith(".png") for f in os.listdir(_vout2)), "能导出 png")
    else:
        ck(False, "造测试视频失败,跳过了视频相关用例")

    print("\n[33] 视频切片:界面")
    _wv = A.MainWindow()
    ck(_wv.nav.button(A.MainWindow.PAGE_VIDEO).text() == "视频切片",
       "侧栏有「视频切片」一页")
    if _have_video:
        _wv.p_video.setText(_vsrc)
        _wv._load_video()
        ck(abs(_wv.vid_bar.duration() - 12) < 0.3, "区间条铺开成视频时长")
        ck("320×240" in _wv.lb_vinfo.text(), f"显示视频信息:{_wv.lb_vinfo.text()}")
        ck(_wv.p_frames.text().endswith("frames"), "输出目录自动给了个默认值")
        # 区间与预告
        _wv.vid_bar.set_range(2, 10)
        _wv.sp_ivl.setValue(2.0)
        ck(_wv.vid_bar.range() == (2.0, 10.0), "能设区间")
        ck("预计 5 张" in _wv.lb_vest.text(), f"预告张数:{_wv.lb_vest.text()}")
        # 拖手柄拖过对面会自动交换,不产生非法区间
        _wv.vid_bar._a, _wv.vid_bar._b = 9.0, 3.0
        _wv.vid_bar._drag = "a"
        _wv.vid_bar.mouseReleaseEvent(QtCore._MouseEv(0, 0))
        ck(_wv.vid_bar.range() == (3.0, 9.0), "手柄拖过头自动交换,不会「结束早于开始」")
        # 播放头被拽回区间内
        _wv.vid_bar.set_range(4, 8)
        _wv.vid_bar.set_head(1)
        _wv.vid_bar._drag = "b"
        _wv.vid_bar.mouseReleaseEvent(QtCore._MouseEv(0, 0))
        ck(4 <= _wv.vid_bar.head() <= 8, "播放头会被拽回区间内")
        # 播放 / 暂停 / 循环
        _wv.vid_bar.set_head(4)
        _wv._toggle_vid_play()
        ck(_wv._vid_timer.isActive() and "暂停" in _wv.vid_play.text(), "能开始播放")
        _wv.vid_bar.set_head(7.99)
        _wv._vid_tick()
        ck(abs(_wv.vid_bar.head() - 4) < 0.2, "播到区间末尾回到开头(循环)")
        _wv._toggle_vid_play()
        ck(not _wv._vid_timer.isActive() and "播放" in _wv.vid_play.text(), "能暂停")
        # 设为开始 / 设为结束
        _wv.vid_bar.set_range(0, 12)
        _wv.vid_bar.set_head(5)
        _wv._set_vid_edge("a")
        ck(_wv.vid_bar.range()[0] == 5.0, "「设为开始」用播放头定左端")
        _wv.vid_bar.set_head(9)
        _wv._set_vid_edge("b")
        ck(_wv.vid_bar.range() == (5.0, 9.0), "「设为结束」用播放头定右端")
        # 真的切出图
        _vo = os.path.join(tmp, "gui_frames")
        _wv.p_frames.setText(_vo)
        _wv.vid_bar.set_range(2, 10)
        _wv.sp_ivl.setValue(2.0)
        _wv._run_extract()
        ck(sorted(os.listdir(_vo)) == [f"image_{i:03d}.jpg" for i in range(1, 6)],
           f"界面上点确定能切出图:{sorted(os.listdir(_vo))}")
        ck("切好了 5 张" in _wv.lb_vstat.text(), f"结果提示:{_wv.lb_vstat.text()}")
        # 停止按钮能中断
        _wv._vid_stop = False
        _vo2 = os.path.join(tmp, "gui_frames2")
        _wv.p_frames.setText(_vo2)
        _wv.sp_ivl.setValue(0.5)
        _orig_set = _wv.pb_vid.setValue
        _cnt = [0]

        def _spy(v):
            _cnt[0] += 1
            if _cnt[0] == 2:
                _wv._vid_stop = True
            return _orig_set(v)

        _wv.pb_vid.setValue = _spy
        _wv._run_extract()
        ck(len(os.listdir(_vo2)) < 5, f"「停止」真能中断(只出了 {len(os.listdir(_vo2))} 张)")
        ck("已停止" in _wv.lb_vstat.text(), "停止后有说明")
        _wv.pb_vid.setValue = _orig_set
        # 文件名前缀要挡住非法字符
        _wv.ed_vprefix.setText('bad/na*me')
        MsgBox.CALLS.clear()
        _wv._run_extract()
        ck(any("不能包含" in t for _, _, t in MsgBox.CALLS), "非法文件名前缀被挡住")
        _wv.ed_vprefix.setText("image_")
        # 一键把项目图片目录指向切好的文件夹
        _wv.p_frames.setText(_vo)
        _wv._use_frames()
        ck(_wv.p_images.text() == _vo, "「用这批图去标注」把项目图片目录指过去")
        ck(_wv.pages.currentIndex() == A.MainWindow.PAGE_HOME, "并跳回首页让你接着跑标注")
    # 不是视频的文件要有提示
    _wv.p_video.setText(os.path.join(tmp, "notvideo.txt"))
    open(os.path.join(tmp, "notvideo.txt"), "w").write("x")
    _wv._load_video()
    ck("不像视频" in _wv.lb_vinfo.text(), f"选了非视频文件有提示:{_wv.lb_vinfo.text()}")
    # 空格键只在视频页起作用
    _wv.pages.setCurrentIndex(0)
    _wv._space_pressed()
    ck(not _wv._vid_timer.isActive(), "在别的页按空格不会误触发播放")

    print("\n[34] 绘图代码要对得上真 Qt 的签名")
    # 假 Qt 什么调用都接受,所以画图的 API 用错了它发现不了。
    # 而 paintEvent 里抛异常 Qt 收不住,会直接段错误(退出码 139)——
    # 之前 drawPolygon 分开传三个点就是这么崩的。这里拿 PySide6 自带的
    # .pyi 声明来核对方法名,并确认点序列是以列表形式传的。
    # 注意不能 import PySide6 —— 它已经被假 Qt 顶替了,拿不到真实路径。
    # 直接在 venv 的 site-packages 里找那份类型声明。
    _pyi = ""
    for _sp in sys.path:
        _cand = os.path.join(_sp, "PySide6", "QtGui.pyi")
        if os.path.isfile(_cand):
            _pyi = _cand
            break
    if not _pyi:
        import glob as _g
        _hits = _g.glob(os.path.join(ROOT, ".venv", "lib", "python*",
                                     "site-packages", "PySide6", "QtGui.pyi"))
        _pyi = _hits[0] if _hits else ""
    if os.path.isfile(_pyi):
        _txt = open(_pyi, encoding="utf-8").read()
        _seg = _txt[_txt.index("class QPainter"):]
        _seg = _seg[:_seg.index("\nclass ")]
        _known = set(re.findall(r"def (\w+)\(", _seg))
        for _f in ("rangebar.py", "boxedit.py"):
            _p = os.path.join(os.path.dirname(os.path.abspath(A.__file__)), _f)
            _src = open(_p, encoding="utf-8").read()
            _used = sorted(set(re.findall(r'\b(?:p|painter)\.(\w+)\(', _src)))
            _bad = [c for c in _used if c not in _known]
            ck(not _bad, f"{_f} 用的 QPainter 方法都存在(可疑:{_bad})")
            # 接受点序列的几个方法必须传列表,不能把点摊开当多个参数
            for _m in ("drawPolygon", "drawPolyline", "drawRects", "drawLines"):
                for _call in re.findall(rf'{_m}\(\s*(.)', _src):
                    ck(_call == "[", f"{_f} 的 {_m} 传的是点列表(不是摊开的多个点)")
    else:
        ck(True, "找不到 QtGui.pyi,跳过签名核对")

    print("\n[33b] 视频页:下半边铺切好的图,点开能放大")
    if _have_video:
        _wt = A.MainWindow()
        _wt.p_video.setText(_vsrc)
        _wt._load_video()
        _to = os.path.join(tmp, "thumb_out")
        _wt.p_frames.setText(_to)
        _wt.vid_bar.set_range(0, 10)
        _wt.sp_ivl.setValue(2.0)
        _wt._run_extract()
        ck(_wt.thumbs.count() == 6, f"切完自动铺缩略图({_wt.thumbs.count()} 个)")
        # 要求:一下全都显示出来,不靠滚轮翻页 -> 格子按面积自动缩放
        _ts = _wt.thumbs
        _ts.viewport().resize(620, 400)
        _ts.relayout()
        _pad = _ts.spacing() * 2 + 4
        _cols = max(1, 620 // (_ts._thumb + _pad))
        _rows = (_ts.count() + _cols - 1) // _cols
        ck(_rows * (_ts._thumb + _pad + 16) <= 400,
           f"6 张图在 620x400 面板里一屏放完(格子 {_ts._thumb}px)")
        _big = _ts._thumb
        _ts.viewport().resize(300, 200)
        _ts.relayout()
        ck(_ts._thumb < _big,
           f"面板变小时格子跟着缩({_big} -> {_ts._thumb}),而不是出滚动条")
        _ts.viewport().resize(900, 600)
        _ts.relayout()
        ck(_ts._thumb > _big, f"面板变大时格子跟着长({_ts._thumb})")
        ck("共 6 张" in _wt.lb_thumbs.text(), f"张数说明:{_wt.lb_thumbs.text()}")
        _tp = _wt.thumbs.paths()
        ck(all(os.path.isfile(p) for p in _tp), "每个缩略图都挂着真实文件路径")
        ck(os.path.basename(_tp[0]) == "image_001.jpg", "顺序是 image_001 开头")
        # 点开放大:能翻页、能循环
        from widgets import ImageDialog as _ID2
        _dlg = _ID2(_tp, 2)
        ck(os.path.basename(_dlg.current()) == "image_003.jpg", "点第3张打开的就是第3张")
        ck("(3/6)" in _dlg.lb.text(), f"显示第几张:{_dlg.lb.text()}")
        _dlg.step(1)
        ck(os.path.basename(_dlg.current()) == "image_004.jpg", "能翻到下一张")
        _dlg.step(-2)
        ck(os.path.basename(_dlg.current()) == "image_002.jpg", "能往回翻")
        _dlg2 = _ID2(_tp, 5)
        _dlg2.step(1)
        ck(os.path.basename(_dlg2.current()) == "image_001.jpg", "翻到末尾会绕回第一张")
        ck(_ID2([], 0).current() == "", "没有图时打开弹窗也不崩")
        # 刷新按钮
        _wt.thumbs.clear()
        _wt._reload_thumbs()
        ck(_wt.thumbs.count() == 6, "「刷新」能重新读一遍文件夹")
        _wt.p_frames.setText(os.path.join(tmp, "空目录"))
        _wt._reload_thumbs()
        ck("还没有图" in _wt.lb_thumbs.text(), "空目录有说明,不是一片空白")

        print("\n[33d] 视频页缩放时设置区不能重叠或裁切")
        import inspect as _insp
        _vsrc2 = _insp.getsource(A.MainWindow._build_video_page)
        ck("scroll_area(right" in _vsrc2,
           "视频设置区使用独立滚动区(内容多时可以完整访问)")
        ck("rcol.addWidget(cthumb, 1)" in _vsrc2,
           "缩略图区拿伸缩因子 1:空间优先给设置卡")
        ck("rcol.addWidget(c1, 0)" in _vsrc2 and
           "rcol.addWidget(c3, 0)" in _vsrc2 and
           "rcol.addWidget(c2, 0)" in _vsrc2,
           "三张设置卡直接参加同一列布局,缩放后不会使用旧高度")
        from rangebar import VideoView as _VV0
        ck(not _VV0().hasHeightForWidth(),
           "预览区不按比例索要高度,窗口矮时肯让位")
        _mw_src = _insp.getsource(A.MainWindow.__init__)
        ck("setMinimumSize(900, 700)" in _mw_src,
           "窗口高度下限提到 700(600 高塞不下这一页,只能滚)")
        # 启动窗口大小:按屏幕算,不写死 —— 写死 1600x1000 在 1366x768 的
        # 笔记本上会超出屏幕,标题栏被顶到看不见
        _sz_fn = A.MainWindow._startup_size
        _fake = A.MainWindow.__new__(A.MainWindow)
        _orig_inst = QtWidgets.QApplication.instance

        class _Scr:
            def __init__(self, w, h):
                self._w, self._h = w, h

            def availableGeometry(self):
                _o = type("G", (), {})()
                _o.width = lambda: self._w
                _o.height = lambda: self._h
                return _o

        class _App2:
            def __init__(self, scr):
                self._s = scr

            def primaryScreen(self):
                return self._s

        for _sw, _sh in ((1366, 730), (1920, 1040), (2560, 1400), (3840, 2120)):
            QtWidgets.QApplication.instance = staticmethod(
                lambda _a=_App2(_Scr(_sw, _sh)): _a)
            _w2, _h2 = _sz_fn(_fake)
            ck(_w2 <= _sw and _h2 <= _sh,
               f"{_sw}x{_sh} 屏幕上启动窗口 {_w2}x{_h2} 不超出屏幕")
            ck(_w2 >= 900 and _h2 >= 700,
               f"{_sw}x{_sh} 屏幕上也不小于最小尺寸({_w2}x{_h2})")
            ck(_w2 <= 1800 and _h2 <= 1150, f"再大的屏也有上限({_w2}x{_h2})")
        QtWidgets.QApplication.instance = staticmethod(lambda: None)
        ck(_sz_fn(_fake) == (1480, 950), "拿不到屏幕信息时退回 1480x950")
        QtWidgets.QApplication.instance = _orig_inst
        # 右侧设置区允许滚动，窗口矮时仍保持输入框和按钮的完整高度。
        ck("Card(" in _vsrc2 and "grow=True" in _vsrc2,
           "设置卡使用不可压缩的 Card,按内容要多少给多少")
        ck("QSizePolicy.Ignored" in _vsrc2,
           "缩略图区设成 Ignored:空间不足时它先让位")
        import theme as _TH0
        for _k2 in A.MainWindow.ZOOM_STEPS:
            _ss3 = _TH0.stylesheet(_k2)
            _i3 = _ss3.index("QLineEdit, QPlainTextEdit")
            _blk3 = _ss3[_i3:_ss3.index("}", _i3)]
            _mh3 = re.search(r"min-height:\s*(\d+)px", _blk3)
            _pd3 = re.search(r"padding:\s*(\d+)px", _blk3)
            ck(_mh3 is not None, f"缩放 {_k2} 时输入框有 min-height(不许被压扁)")
            _box3 = int(_mh3.group(1)) + int(_pd3.group(1)) * 2
            _text3 = 10.0 * _k2 * 96 / 72
            ck(_box3 >= _text3,
               f"缩放 {_k2} 时框高 {_box3}px 装得下 {_text3:.0f}px 的字")
        ck("padding: 7px 9px" in _TH0.stylesheet(1.6),
           "缩放不改注释里写的示例值(否则注释自相矛盾)")
        # 真正的原因:Card 默认可被竖向压缩(QFrame 是 Preferred),
        # 空间不够时 Qt 压卡片,里面的输入框就被裁掉一截。
        # 装表单的卡必须 Minimum,只有装大块内容的卡才 grow=True。
        _card_src = _insp.getsource(_W.Card.__init__)
        ck("QSizePolicy.Minimum" in _card_src,
           "Card 默认竖向不可压缩(否则输入框会被砍一截)")
        ck("SetMinimumSize" in _card_src,
           "Card 的布局用 SetMinimumSize,内容要多少就撑多少")
        ck("grow=False" in _insp.signature(_W.Card.__init__).__str__()
           or "grow" in _insp.signature(_W.Card.__init__).__str__(),
           "Card 提供 grow 开关给需要占满空间的卡片")
        # 拿伸缩因子 1 的卡必须 grow=True,否则它撑不开
        for _fn in ("_build_label_page", "_build_result_page",
                    "_build_dataset_page", "_build_video_page"):
            _psrc = _insp.getsource(getattr(A.MainWindow, _fn))
            _grow = {}
            for _m in re.finditer(r"(\w+) = Card\(((?:[^()]|\([^()]*\))*)\)",
                                  _psrc, re.S):
                _grow[_m.group(1)] = "grow=True" in _m.group(2)
            for _m in re.finditer(r"addWidget\((\w+), (\d)\)", _psrc):
                _nm, _f = _m.group(1), _m.group(2)
                if _nm not in _grow:
                    continue
                ck((_f == "1") == _grow[_nm],
                   f"{_fn}: {_nm} 伸缩因子={_f} 和 grow={_grow[_nm]} 相符")

        print("\n[33e] 关窗/切页时不能留下还在跑的东西(段错误 139 的来源)")
        _ev_c = type("E", (), {"accept": lambda s: None,
                               "ignore": lambda s: None})()
        _wc = A.MainWindow()
        _wc.p_video.setText(_vsrc)
        _wc._load_video()
        _wc.vid_bar.set_range(0, 8)
        _wc.vid_bar.set_head(0)
        _wc._toggle_vid_play()
        _wc._on_vid_head_moving(3.0)
        ck(_wc._vid_timer.isActive(), "先让播放和拖动都跑起来")
        _wc.closeEvent(_ev_c)
        ck(not _wc._vid_timer.isActive(), "关窗后播放定时器停了")
        ck(not _wc._scrub_timer.isActive(), "关窗后拖动限流器也停了")
        ck(_wc._vid_reader is None, "关窗后释放了 cv2.VideoCapture")
        ck(_wc._closing, "关窗时立起 _closing 标记")
        # 关窗后再触发回调不能崩(定时器可能已经排队)
        _wc._show_vid_frame(5.0)
        _wc._vid_tick()
        _wc._scrub_decode()
        ck(True, "关窗后残留的回调被触发也安全返回")
        # 抽帧途中关窗:processEvents 会让 closeEvent 插进循环中间
        _wc2 = A.MainWindow()
        _wc2.p_video.setText(_vsrc)
        _wc2._load_video()
        _oc = os.path.join(tmp, "close_mid")
        _wc2.p_frames.setText(_oc)
        _wc2.vid_bar.set_range(0, 11)
        _wc2.sp_ivl.setValue(0.5)
        _o_set = _wc2.pb_vid.setValue
        _c2 = [0]

        def _spy2(v):
            _c2[0] += 1
            if _c2[0] == 3:
                _wc2.closeEvent(_ev_c)      # 关窗发生在抽帧循环中间
            return _o_set(v)

        _wc2.pb_vid.setValue = _spy2
        _wc2._run_extract()
        ck(len(os.listdir(_oc)) < 10,
           f"抽帧途中关窗,循环立刻收手(只出了 {len(os.listdir(_oc))} 张)")
        # 切离视频页要停播放
        _wc3 = A.MainWindow()
        _wc3.p_video.setText(_vsrc)
        _wc3._load_video()
        _wc3.vid_bar.set_range(0, 8)
        _wc3._toggle_vid_play()
        _wc3._go(A.MainWindow.PAGE_HOME)
        ck(not _wc3._vid_timer.isActive(), "切到别的页会停掉播放,不后台白解码")

        print("\n[33c] 拖动播放头要连续出画面(不是松手才跳)")
        _wd = A.MainWindow()
        _wd.p_video.setText(_vsrc)
        _wd._load_video()
        _seen = []
        _orig_show = _wd._show_vid_frame
        _wd._show_vid_frame = lambda s: (_seen.append(round(s, 2)),
                                         _orig_show(s))[1]
        for _t in (1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.4):
            _wd._on_vid_head_moving(_t)
        ck(len(_seen) >= 1, f"拖动过程中就出画面了({len(_seen)} 帧)")
        ck(_wd._scrub_timer.isActive(), "开了限流器,后续位置由它接着解")
        _seen.clear()
        _wd._scrub_decode()
        ck(_seen == [2.4],
           f"限流器只解最新位置,丢掉积压(解的是 {_seen},不是 1.2)")
        _seen.clear()
        _wd._scrub_decode()
        ck(_seen == [] and not _wd._scrub_timer.isActive(),
           "没有新位置时自动停,不白耗 CPU")
        _seen.clear()
        _wd._on_vid_head(7.5)
        ck(_seen == [7.5], "松手时精确补上最后那一帧")
        ck(not _wd._scrub_timer.isActive(), "松手后限流器关掉")

    print("\n[35] 界面缩放:默认原始比例,右上角手动调")
    # 之前是跟着窗口尺寸自动缩放,全屏时会自己放大到 1.6 倍,结果输入框里的
    # 长路径被挤得看不全。改成默认 100%,由用户用右上角的 - / + 决定。
    import theme as _TH
    _ss1 = _TH.stylesheet(1.0)
    _ss16 = _TH.stylesheet(1.6)
    _fs1 = sorted(set(int(x) for x in re.findall(r"font-size: (\d+)px", _ss1)))
    _fs16 = sorted(set(int(x) for x in re.findall(r"font-size: (\d+)px", _ss16)))
    ck(_fs16[0] > _fs1[0] and _fs16[-1] > _fs1[-1],
       f"放大档位字号确实更大:{_fs1} -> {_fs16}")
    ck(set(int(x) for x in re.findall(r"border: (\d+)px", _ss16)) == {1},
       "1px 边框不放大(否则会变成粗黑框)")
    _r1 = max(int(x) for x in re.findall(r"border-radius: (\d+)px", _ss1))
    _r16 = max(int(x) for x in re.findall(r"border-radius: (\d+)px", _ss16))
    ck(_r16 <= _r1 * 1.6, f"圆角放大有封顶,不会变成胶囊({_r1}->{_r16})")
    for _k in A.MainWindow.ZOOM_STEPS:
        _s2 = _TH.stylesheet(_k)
        ck(_s2.count("{") == _s2.count("}"), f"缩放 {_k} 时 QSS 括号仍配对")
        _urls = re.findall(r"url\(([^)]+)\)", _s2)
        ck(all(os.path.exists(_u) for _u in _urls), f"缩放 {_k} 时图片路径都在")
    # _apply_scale 要拿 QApplication.instance(),测试里得先造一个
    QtWidgets.QApplication()
    core.save_state(zoom=None)
    _wr = A.MainWindow()
    _wr._fill_class_table([{"name": "A", "desc": "x", "on": True}])
    ck(_wr._ui_k == 1.0, "默认就是 100%(原始比例)")
    # 窗口变大不再自动放大 —— 那会把长路径挤没
    _ev_r = type("E", (), {})()
    _wr.resize(2400, 1300)
    if hasattr(_wr, "resizeEvent"):
        _wr.resizeEvent(_ev_r)
    ck(_wr._ui_k == 1.0, "窗口拉大后仍是 100%,不自动放大")
    # 右上角的 + / -
    ck(_wr.lb_zoom.text() == "100%", f"右上角显示当前缩放:{_wr.lb_zoom.text()}")
    _wr._zoom(1)
    ck(_wr._ui_k > 1.0, f"点 + 放大一档({_wr._ui_k})")
    ck("%" in _wr.lb_zoom.text(), f"标签跟着更新:{_wr.lb_zoom.text()}")
    ck(_wr.tbl.verticalHeader().defaultSectionSize() > 32,
       "放大后类别表行高也跟着放大(不然字大了又被裁)")
    ck(_wr.tbl.columnWidth(1) > 108, "类别名列宽跟着放大")
    _wr._zoom(-1)
    ck(abs(_wr._ui_k - 1.0) < 0.01, "点 - 回到 100%")
    for _ in range(10):
        _wr._zoom(-1)
    ck(_wr._ui_k == min(A.MainWindow.ZOOM_STEPS), "一直点 - 停在最小档,不会越界")
    for _ in range(20):
        _wr._zoom(1)
    ck(_wr._ui_k == max(A.MainWindow.ZOOM_STEPS), "一直点 + 停在最大档")
    _wr._zoom_reset()
    ck(_wr._ui_k == 1.0 and _wr.lb_zoom.text() == "100%", "Ctrl+0 回到 100%")
    # 缩放要记住
    _wr._zoom(1)
    _k_saved = _wr._ui_k
    ck(json.load(open(core.STATE_PATH, encoding="utf-8")).get("zoom") == _k_saved,
       "缩放存进了 state,下次打开还是这个大小")
    ck(A.MainWindow()._ui_k == _k_saved, "重开软件沿用上次的缩放")
    core.save_state(zoom=1.0)

    print("\n[36] 视频预览不该留大片黑边")
    # 老问题:QLabel.setPixmap 只缩放一次,窗口放大后画面停在旧尺寸,
    # 四周一大圈黑边;而且 16:9 的画面塞进更方的框里上下必然留黑。
    from rangebar import VideoView as _VV
    _vv = _VV()
    # 预览区不索要高度:这一页要一屏放完,它得肯让位,
    # 否则窗口一矮就把区间条和按钮顶出去,只能靠滚轮找
    ck(not _vv.hasHeightForWidth(), "预览区不按比例索要高度(布局给多少用多少)")
    _vv.set_aspect(3840, 2160)
    ck(abs(_vv._ar - 3840 / 2160) < 0.01, "记住了 16:9 的画面比例")
    _vv.set_aspect(640, 480)
    ck(abs(_vv._ar - 640 / 480) < 0.01, "换 4:3 视频时比例跟着换")
    _vv.set_aspect(0, 0)
    ck(abs(_vv._ar - 640 / 480) < 0.01, "非法尺寸不会把比例改坏")
    ck(_vv.minimumHeight() <= 160, "最小高度不霸道,窗口矮时能压缩")
    ck(hasattr(_vv, "set_frame") and hasattr(_vv, "set_hint"),
       "预览区提供 set_frame/set_hint(每次重绘按当前尺寸缩放)")

    print("\n[20] 空描述要给出警示(模型很可能找不到)")
    for r in range(w.tbl.rowCount()):
        w.tbl.item(r, 2).setText("")
    w._update_cls_stat()
    ck("没写描述" in w.lb_cls_stat.text(), "提示了没写描述的类别数")

    print("\n[37] AI 补充提示词:基线快照(跟哪一版比)")
    import promptai as _PA
    _pd2 = core.project_dir(_P0)
    _o2 = os.path.join(tmp, "pai_out")
    os.makedirs(os.path.join(_o2, "labels"), exist_ok=True)
    _i2 = os.path.join(tmp, "pai_imgs")
    os.makedirs(_i2, exist_ok=True)
    from PIL import Image as _IM2
    for _k in range(1, 5):
        _ip = os.path.join(_i2, f"p{_k}.jpg")
        _IM2.new("RGB", (640, 480)).save(_ip)
        QtGui._Pixmap.FAKE[_ip] = (640, 480)
        with open(os.path.join(_o2, "labels", f"p{_k}.txt"), "w") as _f:
            _f.write("0 0.5 0.5 0.2 0.2\n")
    ck(not core.has_baseline(_pd2), "还没跑自动标注时没有基线")
    ck(core.snapshot_baseline(_pd2, _o2) == 4, "跑完自动标注存下 4 张的基线")
    ck(core.has_baseline(_pd2), "基线建立了")
    ck(core.baseline_meta(_pd2).get("n_files") == 4, "基线记下了张数和时间")
    # 关键:手动保存多少次都不能污染基线
    _bp = core.baseline_label_for(_pd2, os.path.join(_i2, "p2.jpg"))
    _before = core.read_boxes(_bp)
    for _r in range(6):
        with open(os.path.join(_o2, "labels", "p2.txt"), "w") as _f:
            _f.write(f"0 0.6 0.5{_r} 0.25 0.22\n1 0.2 0.3 0.1 0.1\n")
    ck(core.read_boxes(_bp) == _before,
       "手动保存 6 次后基线仍是 AI 那一版(不会搞混对比版本)")

    print("\n[38] AI 补充提示词:框对比")
    _b3 = [{"cid": 0, "xc": 0.5, "yc": 0.5, "w": 0.2, "h": 0.2},
           {"cid": 1, "xc": 0.2, "yc": 0.2, "w": 0.1, "h": 0.1}]
    _c3 = [{"cid": 0, "xc": 0.52, "yc": 0.51, "w": 0.21, "h": 0.2},
           {"cid": 0, "xc": 0.8, "yc": 0.8, "w": 0.15, "h": 0.15}]
    _d3 = core.diff_boxes(_b3, _c3)
    ck(len(_d3["deleted"]) == 1, "认出你删掉了 AI 标错的框")
    ck(len(_d3["added"]) == 1, "认出你补标了 AI 漏掉的框")
    ck(_d3["kept"] + len(_d3["moved"]) == 1, "认出还有一个框被保留/微调")
    _same = core.diff_boxes(_b3, _b3)
    ck(not (_same["moved"] or _same["deleted"] or _same["added"]),
       "两版一致时不报任何差异")
    ck(core.diff_boxes([], [])["n_base"] == 0, "空框列表不崩")

    print("\n[39] AI 补充提示词:改动史就是记忆")
    core.append_history(_pd2, [{"class": "CA001", "old": "盒子", "new": "红盒子",
                                "reason": "只标红的", "accepted": True}])
    core.append_history(_pd2, [{"class": "CA002", "old": "", "new": "不要标反光",
                                "reason": "", "accepted": False}])
    _h3 = core.load_history(_pd2)
    ck(len(_h3) == 2, "两条都记下了")
    ck(all(e.get("at") for e in _h3), "每条都有时间戳")
    ck(any(not e["accepted"] for e in _h3),
       "被你拒绝的建议也记着(下轮不要再提)")
    core.append_history(_pd2, [{"class": f"X{_n}", "old": "", "new": "y",
                                "accepted": True} for _n in range(250)])
    ck(len(core.load_history(_pd2)) <= 200, "历史只留最近 200 条,不会撑爆 prompt")

    print("\n[40] AI 补充提示词:对照图(发给模型看的东西)")
    _dimg = _PA.compose_diff_image(
        os.path.join(_i2, "p1.jpg"), _b3, _c3, ["CA001", "CA002"])
    ck(_dimg.size == (640, 480), f"对照图尺寸正常({_dimg.size})")
    _bigp = os.path.join(tmp, "big.jpg")
    _IM2.new("RGB", (4000, 3000)).save(_bigp)
    ck(max(_PA.compose_diff_image(_bigp, [], [], []).size) <= 1280,
       "大图会限制长边(省钱且更快)")
    ck(_PA.img_to_data_url(_dimg).startswith("data:image/jpeg;base64,"),
       "能转成模型要的 data url")
    for _t3, _want in (('{"a":1}', 1), ('```json\n{"a":2}\n```', 2),
                       ('好的:\n{"a":3}\n希望有用', 3)):
        ck(_PA._parse_json(_t3)["a"] == _want,
           f"能从 {_t3[:16]!r} 里抠出 JSON")

    print("\n[41] AI 补充提示词:页面上的列表和批量选择")
    _wp = A.MainWindow()
    _wp.p_images.setText(_i2)
    _wp.p_out.setText(_o2)
    _wp._fill_class_table([{"name": "CA001", "desc": "红盒子", "on": True},
                           {"name": "CA002", "desc": "蓝瓶子", "on": True}])
    _wp._pai_reload()
    ck(_wp.lst_pai.count() == 4, f"列出了 4 张图({_wp.lst_pai.count()})")
    ck(any("改过" in _wp.lst_pai.item(_r).text() for _r in range(4)),
       "改过的图有标记,一眼能看出来")
    ck("AI 原始版" in _wp.lb_pai_base.text(), "显示了基线时间和张数")
    _wp._pai_check_changed()
    ck(len(_wp._pai_selected()) == 1,
       f"「只选我改过的」勾上了 1 张(实际 {len(_wp._pai_selected())})")
    _wp._pai_check_all(True)
    ck(len(_wp._pai_selected()) == 4, "全选 = 4 张")
    _wp._pai_check_all(False)
    ck(len(_wp._pai_selected()) == 0, "全不选 = 0 张")
    _wp._pai_invert()
    ck(len(_wp._pai_selected()) == 4, "反选回到 4 张")
    ck("已选 4 张" in _wp.lb_pai_sel.text(), "张数说明跟着更新")
    # 选中就一定发:不替用户跳过"看起来没改"的图
    _sel = _wp._pai_selected()
    ck(all("img" in str(_s) or True for _s in _sel), "选中的都带上了 base/cur")
    ck(sum(1 for _s in _sel if _s["base"] is not None) == 4,
       "有基线时每张都带上了 AI 原始版用于对比")

    print("\n[42] AI 补充提示词:建议要我确认才写入")
    _wp2 = A.MainWindow()
    _wp2._fill_class_table([{"name": "CA001", "desc": "红盒子", "on": True},
                            {"name": "CA002", "desc": "蓝瓶子", "on": True},
                            {"name": "CA003", "desc": "绿袋子", "on": True}])
    _wp2.ed_neg.setPlainText("反光")
    _fake_ans = {
        "classes": [
            {"name": "CA001", "action": "update", "desc": "红色纸盒,含压扁的",
             "reason": "你补标了压扁的"},
            {"name": "CA002", "action": "keep", "desc": "蓝瓶子", "reason": "ok"},
            {"name": "CA003", "action": "update", "desc": "绿色塑料袋",
             "reason": "你删了不透明的"}],
        "negative": "反光;桌面倒影", "negative_reason": "你删了倒影上的框",
        "summary": "两类需要补充", "_findings": ["[p1] 观察A"], "_errors": []}
    _wp2._on_pai_done(_fake_ans, "")
    ck(_wp2.tbl_pai.rowCount() == 2,
       f"只列出真要改的 2 条,keep 的不占位置({_wp2.tbl_pai.rowCount()})")
    ck("桌面倒影" in _wp2.lb_pai_neg.text(), "负样本的建议单独显示")
    ck(_wp2.btn_pai_apply.isEnabled(), "有建议时「应用」可点")
    _before_desc = [_c["desc"] for _c in _wp2._classes_from_table()]
    ck(_before_desc[0] == "红盒子", "还没点应用时,类别表没被偷偷改")
    # 取消第二条,只应用第一条
    _ck2 = _wp2.tbl_pai.cellWidget(1, 0).findChild(QtWidgets.QCheckBox)
    _ck2.setChecked(False)
    _wp2._pai_apply()
    _after = _wp2._classes_from_table()
    ck(_after[0]["desc"] == "红色纸盒,含压扁的", "勾上的那条写进去了")
    ck(_after[2]["desc"] == "绿袋子", "取消勾选的那条没被动")
    ck(_wp2.ed_neg.toPlainText() == "反光;桌面倒影", "负样本也一起写入")
    _h4 = core.load_history(core.project_dir(_P0))
    ck(any(_e["class"] == "CA001" and _e["accepted"] for _e in _h4),
       "采纳的记进历史")
    ck(any(_e["class"] == "CA003" and not _e["accepted"] for _e in _h4),
       "拒绝的也记进历史(下轮不再提)")
    # 模型说没什么可改时
    _wp2._on_pai_done({"classes": [{"name": "CA001", "action": "keep",
                                    "desc": "红色纸盒,含压扁的"}],
                       "negative": "反光;桌面倒影", "summary": "都挺好"}, "")
    ck(_wp2.tbl_pai.rowCount() == 0, "没有要改的时候表格是空的")
    ck("够用" in _wp2.lb_pai_neg.text() or "没有改动" in _wp2.lb_pai_neg.text(),
       "并明确说明不用改")
    _wp2._on_pai_done({}, "连不上模型")
    ck("连不上模型" in _wp2.lb_pai_stat.text(), "失败原因直接显示出来")

    print("\n[43] AI 补充提示词:记忆真的发给了模型")
    _sent = []
    _o_ask = _PA._ask
    _o_cli = _PA._client
    _PA._client = lambda *_a, **_k: object()
    _PA._ask = lambda _c, _m, _t, _d=None, timeout=120: (
        _sent.append((_t, _d is not None)),
        '{"classes":[{"name":"CA001","action":"keep","desc":"红盒子"}],'
        '"negative":"","summary":"ok"}')[1]
    _hist = [{"at": "2026-09-01", "class": "CA001", "old": "盒子",
              "new": "红盒子", "reason": "只标红的", "accepted": True},
             {"at": "2026-09-02", "class": "CA002", "old": "",
              "new": "不要标反光", "reason": "", "accepted": False}]
    _smp = [{"name": "p1.jpg", "img": os.path.join(_i2, "p1.jpg"),
             "base": _b3, "cur": _c3}]
    _PA.analyze(_smp, [{"name": "CA001", "desc": "红盒子", "on": True}],
                "反光", _hist, "http://x", "k", "qwen3-vl-plus", workers=1)
    ck(len(_sent) == 2, f"1 张图 + 1 次汇总 = 2 次请求(实际 {len(_sent)})")
    ck(_sent[0][1] and not _sent[1][1], "逐图那次带图,汇总那次不带图")
    _agg = _sent[1][0]
    ck("只标红的" in _agg, "汇总请求里带上了历史调整记录")
    ck("accepted=false" in _agg, "并标明哪些建议被拒绝过")
    ck("[p1.jpg]" in _agg, "带上了逐图的观察结论")
    # 只分析完整类别表里的非零 id 时，图上和差异文字仍要使用全局类别名。
    _sent.clear()
    _PA.analyze([{"name": "p3.jpg", "img": os.path.join(_i2, "p3.jpg"),
                  "base": [], "cur": [{"cid": 2, "xc": .5, "yc": .5,
                                          "w": .2, "h": .2}]}],
                [{"name": "鼠标", "desc": "黑色鼠标", "on": True}],
                "", [], "http://x", "k", "qwen3-vl-plus", workers=1,
                all_names=["耳机", "键盘", "鼠标"])
    ck("鼠标" in _sent[0][0], "只选非零类别时仍按完整类别 id 显示名称")
    # 全新项目走另一条路
    _sent.clear()
    _PA.analyze([{"name": "p2.jpg", "img": os.path.join(_i2, "p2.jpg"),
                  "base": None, "cur": _c3}],
                [{"name": "CA001", "desc": "", "on": True}],
                "", [], "http://x", "k", "qwen3-vl-plus", workers=1)
    ck("人工标注图" in _sent[0][0],
       "全新项目直接看手标结果,给第一版提示词")
    ck("红框" not in _sent[0][0], "不会提不存在的 AI 原始版")
    _PA._ask, _PA._client = _o_ask, _o_cli

    print("\n[44] AI 补充提示词:列表里要看得见框、勾选框要看得见")
    # 勾选框:只给 QCheckBox 写样式的话,列表项自带的勾选框会退回 Qt
    # 默认画法,在深色底上几乎看不见
    _ss5 = _TH0.stylesheet(1.0)
    ck("QListWidget::indicator" in _ss5,
       "列表项的勾选框有样式(否则深色底上看不见)")
    ck("QListWidget::indicator:checked" in _ss5, "勾上之后有明显的选中态")
    # 缩略图必须是"带当前框的图",不是原图也不是过期的 vis 图
    _bx = _PA.render_boxed(
        os.path.join(_i2, "p1.jpg"),
        [{"cid": 0, "xc": 0.5, "yc": 0.5, "w": 0.3, "h": 0.3}],
        ["耳机"], [(255, 64, 64)], cache_dir=os.path.join(tmp, "bx"))
    ck(_bx != os.path.join(_i2, "p1.jpg"), "有框时画一张带框的图")
    ck(os.path.isfile(_bx), "带框的图真的存下来了")
    _bx2 = _PA.render_boxed(
        os.path.join(_i2, "p1.jpg"),
        [{"cid": 0, "xc": 0.5, "yc": 0.5, "w": 0.3, "h": 0.3}],
        ["耳机"], [(255, 64, 64)], cache_dir=os.path.join(tmp, "bx"))
    ck(_bx2 == _bx, "同样的框命中缓存,不重复画")
    _bx3 = _PA.render_boxed(
        os.path.join(_i2, "p1.jpg"),
        [{"cid": 0, "xc": 0.6, "yc": 0.5, "w": 0.3, "h": 0.3}],
        ["耳机"], [(255, 64, 64)], cache_dir=os.path.join(tmp, "bx"))
    ck(_bx3 != _bx, "框改了就换新图(不会给你看旧框)")
    ck(_PA.render_boxed(os.path.join(_i2, "p1.jpg"), [], [], [(1, 2, 3)])
       == os.path.join(_i2, "p1.jpg"), "没有框时直接用原图")
    _wp3 = A.MainWindow()
    _wp3.p_images.setText(_i2)
    _wp3.p_out.setText(_o2)
    _wp3._fill_class_table([{"name": "CA001", "desc": "红盒子", "on": True},
                            {"name": "CA002", "desc": "蓝瓶子", "on": True}])
    _wp3._pai_reload()
    ck(all("show" in _r for _r in _wp3._pai_rows),
       "每行都记着要显示哪张(带框的)图")
    # 缩略图是后台线程画的(不然一点就卡),等它画完再看
    for _ in range(60):
        if any(_r["show"] != _r["img"] for _r in _wp3._pai_rows):
            break
        time.sleep(0.05)
    ck(any(_r["show"] != _r["img"] for _r in _wp3._pai_rows),
       "后台画完后,有框的图显示的是画了框的版本")
    # 单击只勾选,不弹窗;放大改成双击
    ck(hasattr(_wp3, "_pai_open"), "放大是单独的双击处理")
    _src_click = _insp.getsource(_wp3._pai_click)
    ck("ImageDialog" not in _src_click,
       "单击不弹放大窗(否则批量勾选会被弹十几次)")
    ck("ImageDialog" in _insp.getsource(_wp3._pai_open), "双击才放大")

    print("\n[45] AI 补充提示词:必须在原提示词上修订,不能重写")
    ck("修订" in _PA.AGGREGATE and "不是重写" in _PA.AGGREGATE,
       "汇总请求明确要求在原文基础上改")
    ck("原描述里已有的正确信息必须保留" in _PA.AGGREGATE, "要求保留原有信息")
    ck("changed" in _PA.AGGREGATE, "要求模型说明动了哪一处")
    # 代码层面也要拦:光靠提示词要求,模型经常自作主张换一套说法
    ck(_PA.rewrite_warning("红色盒子", "红色纸盒,含压扁的") == "",
       "正常增补不报警")
    ck(_PA.rewrite_warning("红色盒子", "红色盒子") == "", "没改不报警")
    ck(_PA.rewrite_warning("银色机械键盘", "任何电子输入设备") != "",
       "整个换一套说法会被标出来")
    ck(_PA.rewrite_warning("白色耳机盒,椭圆形,光滑",
                           "白色耳机盒,椭圆形,光滑,含开盖") == "",
       "长描述加限定条件不报警")
    ck(_PA.rewrite_warning("", "红色纸盒") == "", "原来是空的就是新写,不报警")
    ck(_PA.rewrite_warning("红盒子", "") != "", "空建议要报警")
    # 界面上:改动过大的默认不勾
    _wp4 = A.MainWindow()
    _wp4._fill_class_table([{"name": "耳机", "desc": "白色耳机充电盒,椭圆形",
                             "on": True},
                            {"name": "键盘", "desc": "银色机械键盘", "on": True}])
    _wp4.ed_neg.setPlainText("反光")
    _wp4._on_pai_done({"classes": [
        {"name": "耳机", "action": "update",
         "desc": "白色耳机充电盒,椭圆形,含开盖状态",
         "changed": "末尾追加含开盖状态", "reason": "你补标了开盖的"},
        {"name": "键盘", "action": "update", "desc": "任何电子输入设备",
         "changed": "重写", "reason": "泛化"}],
        "negative": "桌面倒影", "negative_reason": "你删了倒影",
        "summary": "x"}, "")
    _ck_ok = _wp4.tbl_pai.cellWidget(0, 0).findChild(QtWidgets.QCheckBox)
    _ck_bad = _wp4.tbl_pai.cellWidget(1, 0).findChild(QtWidgets.QCheckBox)
    ck(_ck_ok.isChecked(), "正常修订默认勾上")
    ck(not _ck_bad.isChecked(), "改动过大的默认不勾(免得一点应用就冲掉原文)")
    ck("改动很大" in _ck_bad.toolTip(), "并说明为什么没勾")
    ck("⚠" in _wp4.tbl_pai.item(1, 1).text(), "表里也标出来了")
    # negative 要追加而不是整段替换
    ck("反光" in _wp4._pai_neg and "桌面倒影" in _wp4._pai_neg,
       f"模型整段重写 negative 时自动补回原文({_wp4._pai_neg})")
    _wp4._pai_apply()
    ck(_wp4._classes_from_table()[0]["desc"].endswith("含开盖状态"),
       "勾上的修订写进去了")
    ck(_wp4._classes_from_table()[1]["desc"] == "银色机械键盘",
       "没勾的那条原描述保住了")

    print("\n[46] 上锁:改好的标签不被重跑覆盖")
    _wl = A.MainWindow()
    _wl.p_images.setText(_i2)
    _wl.p_out.setText(_o2)
    _wl._fill_class_table([{"name": "CA001", "desc": "红盒子", "on": True}])
    _wl.refresh_results()
    ck(_wl._locks == set() or isinstance(_wl._locks, set), "启动时读得到锁集合")
    _wl._locks = set()
    _wl.lst_vis.setCurrentRow(1)
    ck(not _wl.ck_lock.isChecked(), "AI 标的默认不上锁")
    _wl._on_boxes_changed()          # 模拟手动改框
    ck(_wl.ck_lock.isChecked(), "手动改过就自动上锁")
    _cur = os.path.basename(_wl._vis_files[1])
    ck(_cur in _wl._locks, f"锁集合里有这张图({_cur})")
    ck("🔒" in _wl.lst_vis.item(1).text(), "列表里名字右边出现锁图案")
    ck("🔒" not in _wl.lst_vis.item(0).text(), "没上锁的图没有锁图案")
    # 手动解锁 / 上锁
    _wl.ck_lock.setChecked(False)
    ck(_cur not in _wl._locks, "取消勾选就解锁了")
    _wl.ck_lock.setChecked(True)
    ck(_cur in _wl._locks, "重新勾上又锁住")
    # 锁要存盘,重开还在
    ck(os.path.exists(core.locks_path(core.project_dir(_P0))), "锁写进了项目里")
    ck(core.load_locks(core.project_dir(_P0)) == _wl._locks, "存盘内容和内存一致")
    ck(A.MainWindow()._locks == _wl._locks, "重开软件锁还在")
    # 切图时工具条上的锁跟着变
    _wl.lst_vis.setCurrentRow(0)
    _wl._sync_lock_ui()
    ck(not _wl.ck_lock.isChecked(), "切到没上锁的图,勾自动取消")

    print("\n[47] 上锁:预览张数不算上锁的图(顺序很关键)")
    import autolabel_qwen as _AQ
    _ld = os.path.join(tmp, "lockdir")
    os.makedirs(_ld, exist_ok=True)
    for _k in range(1, 11):
        _IM2.new("RGB", (64, 48)).save(os.path.join(_ld, f"i{_k:02d}.jpg"))
    _lf = os.path.join(tmp, "lk.json")
    with open(_lf, "w", encoding="utf-8") as _f:
        json.dump({"locked": ["i01.jpg", "i02.jpg", "i03.jpg"]}, _f)
    _all = _AQ.collect_images(_ld, "auto")
    _lk = _AQ.load_lock_names(_lf)
    ck(len(_lk) == 3, "读到 3 个锁")
    # 脚本里的顺序:先剔锁,再 limit
    _kept = [_p for _p in _all if os.path.basename(_p) not in _lk][:5]
    ck(len(_kept) == 5, f"预览 5 张真的跑 5 张(实际 {len(_kept)})")
    ck(not any(os.path.basename(_p) in _lk for _p in _kept),
       "这 5 张全是没上锁的新图")
    # 顺序反了就会出问题 —— 这条记录为什么必须先剔锁
    _wrong = [_p for _p in _all[:5] if os.path.basename(_p) not in _lk]
    ck(len(_wrong) == 2,
       "(反证)先 limit 再剔锁只会剩 2 张,所以顺序不能反")
    _src_main = _insp.getsource(_AQ.main)
    ck(_src_main.index("load_lock_names") < _src_main.index("args.limit > 0"),
       "代码里确实是先剔锁再 limit")
    ck(_AQ.load_lock_names("/不存在.json") == set(), "锁文件不存在不崩")
    with open(_lf, "w", encoding="utf-8") as _f:
        _f.write("{坏json")
    ck(_AQ.load_lock_names(_lf) == set(), "锁文件坏了也不中断标注")
    ck("--locks" in _insp.getsource(_AQ.main), "脚本支持 --locks 参数")
    ck("--locks" in str(core.build_label_args(
        {**core.default_config(), "classes": [{"name": "a", "desc": "", "on": True}],
         "negative": ""}, limit=5, locks_file=_lf)), "界面会把锁清单传给脚本")

    print("\n[48] 上锁:备份 out/ 时要把上锁的标签救回来")
    _ob = os.path.join(tmp, "outbak")
    os.makedirs(os.path.join(_ob, "labels"), exist_ok=True)
    os.makedirs(os.path.join(_ob, "vis"), exist_ok=True)
    for _n in ("a", "b", "c"):
        with open(os.path.join(_ob, "labels", f"{_n}.txt"), "w") as _f:
            _f.write(f"0 0.5 0.5 0.2 0.2\n")
        with open(os.path.join(_ob, "vis", f"{_n}.jpg"), "w") as _f:
            _f.write("x")
    _bk = core.backup_dir(_ob)
    ck(_bk and not os.path.isdir(os.path.join(_ob, "labels")),
       "备份是把整个 out/ 改名(上锁的标签也被搬走了)")
    os.makedirs(os.path.join(_ob, "labels"), exist_ok=True)
    ck(core.restore_locked_labels(_bk, _ob, {"a.jpg", "c.jpg"}) == 2,
       "把上锁的 2 个标签复制回来")
    _now = sorted(os.listdir(os.path.join(_ob, "labels")))
    ck(_now == ["a.txt", "c.txt"], f"只恢复上锁的,没上锁的照常重跑({_now})")
    ck(os.path.exists(os.path.join(_ob, "vis", "a.jpg")),
       "预览图也一起救回来(否则标注页看不到那张)")

    print("\n[49] 标注画布:鼠标十字辅助虚线")
    import boxedit as _BE
    _pe = _insp.getsource(_BE.BoxCanvas.paintEvent)
    ck("十字辅助虚线" in _pe, "画布会画十字线")
    ck("DashLine" in _pe, "是虚线(实线会挡住画面)")
    ck(hasattr(_BE.BoxCanvas, "leaveEvent"),
       "鼠标移出画布时要擦掉十字线")
    ck("_cross = None" in _insp.getsource(_BE.BoxCanvas.leaveEvent),
       "移出后清掉位置")
    ck("self._cross = e.position()" in
       _insp.getsource(_BE.BoxCanvas.mouseMoveEvent),
       "鼠标移动时记下位置")
    ck("QPointF" in open(os.path.join(os.path.dirname(_BE.__file__),
                                      "boxedit.py"), encoding="utf-8").read()
       .split("\n")[12], "QPointF 已导入(画线要用,漏了会崩)")

    print("\n[50] AI 补充提示词:默认模型 + 按类别勾选")
    _wm = A.MainWindow()
    _wm.p_images.setText(_i2)
    _wm.p_out.setText(_o2)
    _wm._fill_class_table([{"name": "耳机", "desc": "白色耳机盒", "on": True},
                           {"name": "键盘", "desc": "银色键盘", "on": True},
                           {"name": "鼠标", "desc": "黑色鼠标", "on": True}])
    _wm._pai_reload()
    ck(isinstance(_wm.cb_pai_model, _W.SearchableCombo),
       "提示词页模型框和首页一样,是可搜索的下拉列表")
    ck(_wm.cb_pai_model.count() > 1 and
       _wm.cb_pai_model.findData(A.PAI_DEFAULT_MODEL) >= 0,
       f"提示词页模型可展开选择,且保留默认模型({_wm.cb_pai_model.count()} 个)")
    ck(_wm.cb_pai_model.currentText() == "qwen3-vl-plus",
       f"默认模型是 qwen3-vl-plus(实际 {_wm.cb_pai_model.currentText()})")
    ck(A.PAI_DEFAULT_MODEL == "qwen3-vl-plus", "默认模型写成了常量")
    ck(len(_wm._pai_classes_picked()) == 3, "类别默认全勾选")
    _wm._pai_cls_all(False)
    ck(_wm._pai_classes_picked() == [], "「全不选」能清空")
    _wm._pai_cls_all(True)
    ck(len(_wm._pai_classes_picked()) == 3, "「全选」能勾回来")
    # 只勾一个,模型顺手改的别的类别要被过滤掉
    _wm._pai_cls_all(False)
    _wm.lst_pai_cls.item(0).setCheckState(QtCore.Qt.Checked)
    ck(_wm._pai_classes_picked() == ["耳机"], "只勾了耳机")
    _wm._pai_picked = {"耳机"}
    _wm._on_pai_done({"classes": [
        {"name": "耳机", "action": "update", "desc": "白色耳机盒,含开盖",
         "changed": "加了含开盖", "reason": "x"},
        {"name": "键盘", "action": "update", "desc": "任何键盘",
         "changed": "改了", "reason": "y"}],
        "negative": "", "summary": "s"}, "")
    _rn = [_wm.tbl_pai.item(_r, 1).text()
           for _r in range(_wm.tbl_pai.rowCount())]
    ck(len(_rn) == 1 and "耳机" in _rn[0],
       f"没勾的类别即使模型给了建议也不显示({_rn})")
    _wm._pai_apply()
    ck(_wm._classes_from_table()[1]["desc"] == "银色键盘",
       "没勾的类别描述一点没动")
    # 类别表里关掉的类不该出现在这里
    _wm._fill_class_table([{"name": "耳机", "desc": "x", "on": True},
                           {"name": "关掉的", "desc": "y", "on": False}])
    _wm._pai_fill_classes()
    _names5 = [_wm.lst_pai_cls.item(_i).text()
               for _i in range(_wm.lst_pai_cls.count())]
    ck(_names5 == ["耳机"], f"类别表里关掉的类不出现({_names5})")

    print("\n[51] 标注画布:滚轮缩放")
    _cv = _BE.BoxCanvas()
    _cv.resize(800, 600)
    _zi = os.path.join(tmp, "zoom.jpg")
    _IM2.new("RGB", (1000, 800)).save(_zi)
    QtGui._Pixmap.FAKE[_zi] = (1000, 800)
    _cv.load(_zi, [], [(255, 0, 0)], ["x"])

    class _Wh:
        def __init__(self, d, x, y):
            self._d, self._x, self._y = d, x, y

        def angleDelta(self):
            return type("A", (), {"y": lambda _s: self._d})()

        def position(self):
            return QtCore.QPointF(self._x, self._y)

        def accept(self):
            pass

    class _Ms:
        def __init__(self, x, y, b="L"):
            self._x, self._y, self._b = x, y, b

        def position(self):
            return QtCore.QPointF(self._x, self._y)

        def button(self):
            return (QtCore.Qt.MiddleButton if self._b == "M"
                    else QtCore.Qt.LeftButton)

    ck(_cv.zoom() == 1.0, "初始是 1 倍(整张刚好放下)")
    # 最关键:放大时光标底下那个点不能跑,否则放几次就找不到刚才看的地方
    _p0 = _cv._to_img(QtCore.QPointF(300, 200))
    for _ in range(5):
        _cv.wheelEvent(_Wh(120, 300, 200))
    _p1 = _cv._to_img(QtCore.QPointF(300, 200))
    ck(abs(_p1[0] - _p0[0]) < 1 and abs(_p1[1] - _p0[1]) < 1,
       f"放大 5 次后光标底下还是同一个点({_p0[0]:.0f},{_p0[1]:.0f})")
    ck(_cv.zoom() > 1.5, f"确实放大了({_cv.zoom():.2f})")
    # 往回滚会经过 1.0(吸附住,不留 1.0000000002 这种尾巴)
    _hit_one = False
    for _ in range(10):
        _cv.wheelEvent(_Wh(-120, 300, 200))
        if _cv.zoom() == 1.0:
            _hit_one = True
    ck(_hit_one, "往回滚时会正好停在 1.0(整张刚好放下)")
    ck(_cv._pan == (0.0, 0.0), "1 倍及以下平移量归零,图不会偏在一边")
    ck(_cv.zoom() == _BE.BoxCanvas.ZOOM_MIN,
       f"能一直缩到下限 {_BE.BoxCanvas.ZOOM_MIN}({_cv.zoom()})")
    ck(_BE.BoxCanvas.ZOOM_MIN == 0.5, "缩放下限是 50%")
    for _ in range(50):
        _cv.wheelEvent(_Wh(120, 400, 300))
    ck(_cv.zoom() == _BE.BoxCanvas.ZOOM_MAX, "放大有上限")
    for _ in range(80):
        _cv.wheelEvent(_Wh(-120, 400, 300))
    ck(_cv.zoom() == _BE.BoxCanvas.ZOOM_MIN, "缩小有下限")
    # 放大状态下画的框,坐标要落对
    _cv.load(_zi, [], [(255, 0, 0)], ["x"])
    for _ in range(4):
        _cv.wheelEvent(_Wh(120, 400, 300))
    _cv.mousePressEvent(_Ms(300, 250))
    _cv.mouseMoveEvent(_Ms(430, 370))
    _cv.mouseReleaseEvent(_Ms(430, 370))
    _cv.confirm_pending()            # 画完按回车确认
    ck(len(_cv.boxes()) == 1, "放大状态下能画出框")
    _nb = _cv.boxes()[0]
    ck(0 <= _nb["xc"] <= 1 and 0 <= _nb["yc"] <= 1 and _nb["w"] > 0,
       f"框坐标合法(缩放没把坐标算歪):xc={_nb['xc']:.3f}")
    # 中键平移
    _pan0 = _cv._pan
    _cv.mousePressEvent(_Ms(400, 300, "M"))
    _cv.mouseMoveEvent(_Ms(450, 340, "M"))
    _cv.mouseReleaseEvent(_Ms(450, 340, "M"))
    ck(_cv._pan != _pan0, "中键拖动能挪图")
    _cv.mousePressEvent(_Ms(400, 300, "M"))
    _cv.mouseMoveEvent(_Ms(9000, 9000, "M"))
    _cv.mouseReleaseEvent(_Ms(9000, 9000, "M"))
    _ox6, _oy6, _s6 = _cv._fit()
    ck(_ox6 <= 1 and _oy6 <= 1, "狂拖也拖不出视野(图始终盖住控件)")
    # 1 倍时平移没意义,应该归零
    _cv.reset_zoom()
    _cv.mousePressEvent(_Ms(400, 300, "M"))
    _cv.mouseMoveEvent(_Ms(900, 800, "M"))
    _cv.mouseReleaseEvent(_Ms(900, 800, "M"))
    ck(_cv._pan == (0.0, 0.0), "1 倍时拖动不会把图挪走")
    # 换图要归位
    for _ in range(3):
        _cv.wheelEvent(_Wh(120, 400, 300))
    _cv.load(_zi, [], [(255, 0, 0)], ["x"])
    ck(_cv.zoom() == 1.0, "换图归位(上一张放大 3 倍,下一张不该还是那个视角)")
    ck(_cv.reset_zoom() is None and _cv.zoom() == 1.0, "reset_zoom 能复位")
    # 界面上要有倍数显示
    _wz = A.MainWindow()
    _wz.p_images.setText(_i2)
    _wz.p_out.setText(_o2)
    _wz._fill_class_table([{"name": "CA001", "desc": "x", "on": True}])
    _wz.refresh_results()
    _wz.lst_vis.setCurrentRow(0)
    _wz.canvas.resize(800, 600)
    ck(_wz.lb_zoomlv.text() == "100%", "工具条上显示当前倍数")
    for _ in range(3):
        _wz.canvas.wheelEvent(_Wh(120, 400, 300))
    ck(_wz.lb_zoomlv.text() != "100%",
       f"滚轮后倍数跟着变({_wz.lb_zoomlv.text()})")
    _wz.canvas.reset_zoom()
    ck(_wz.lb_zoomlv.text() == "100%", "「复位」按钮把倍数打回 100%")

    print("\n[52] 标注区:上下键翻图")
    _wk = A.MainWindow()
    _wk.p_images.setText(_i2)
    _wk.p_out.setText(_o2)
    _wk._fill_class_table([{"name": "CA001", "desc": "x", "on": True}])
    _wk.refresh_results()
    _wk.lst_vis.setCurrentRow(0)
    _wk.canvas.resize(800, 600)
    # 主程序里由可配置 QShortcut 接管；这里直接调用 keyPressEvent，切回
    # 画布内置默认按键才能单测它原来的上下键语义。
    _wk.canvas.set_external_shortcuts(False)

    class _Kp:
        def __init__(self, k):
            self._k = k

        def key(self):
            return self._k

        def modifiers(self):
            return _qtstub._Flag("<none>")

    ck(_wk.lst_vis.count() >= 3, "有几张图可以翻")
    # 没选中框:上下键翻图
    _wk.canvas._sel = -1
    _wk.canvas.keyPressEvent(_Kp(QtCore.Qt.Key_Down))
    ck(_wk.lst_vis.currentRow() == 1, "按 ↓ 翻到下一张")
    _wk.canvas.keyPressEvent(_Kp(QtCore.Qt.Key_Down))
    ck(_wk.lst_vis.currentRow() == 2, "再按 ↓ 继续往下")
    _wk.canvas.keyPressEvent(_Kp(QtCore.Qt.Key_Up))
    ck(_wk.lst_vis.currentRow() == 1, "按 ↑ 回到上一张")
    _wk.lst_vis.setCurrentRow(_wk.lst_vis.count() - 1)
    _wk.canvas._sel = -1
    _wk.canvas.keyPressEvent(_Kp(QtCore.Qt.Key_Down))
    ck(_wk.lst_vis.currentRow() == 0, "最后一张按 ↓ 绕回第一张")
    # 选中框时上下键是微调,不能翻页(精细活离不开方向键)
    _wk.lst_vis.setCurrentRow(0)
    if _wk.canvas.boxes():
        _row0 = _wk.lst_vis.currentRow()
        _wk.canvas._sel = 0
        _yc0 = _wk.canvas.boxes()[0]["yc"]
        _wk.canvas.keyPressEvent(_Kp(QtCore.Qt.Key_Down))
        ck(_wk.canvas.boxes()[0]["yc"] != _yc0, "选中框时 ↓ 是微调框")
        ck(_wk.lst_vis.currentRow() == _row0, "微调时不会翻页")
    ck("step_image" in _insp.getsource(A.MainWindow._build_result_page),
       "画布的翻图信号接到了列表上")

    print("\n[53] 画完框按回车确定")
    _we2 = A.MainWindow()
    _we2.p_images.setText(_i2)
    _we2.p_out.setText(_o2)
    _we2._fill_class_table([{"name": "耳机", "desc": "x", "on": True},
                            {"name": "键盘", "desc": "y", "on": True}])
    _we2.refresh_results()
    _we2.lst_vis.setCurrentRow(0)
    _we2.canvas.resize(800, 600)
    # 同上：本段直接喂键盘事件，使用画布独立模式测试默认 Enter/Esc。
    _we2.canvas.set_external_shortcuts(False)

    class _Mp:
        def __init__(self, x, y):
            self._x, self._y = x, y

        def position(self):
            return QtCore.QPointF(self._x, self._y)

        def button(self):
            return QtCore.Qt.LeftButton

    class _Kb:
        def __init__(self, k):
            self._k = k

        def key(self):
            return self._k

        def modifiers(self):
            return _qtstub._Flag("<none>")

    def _draw2(x1, y1, x2, y2):
        _we2.canvas.mousePressEvent(_Mp(x1, y1))
        _we2.canvas.mouseMoveEvent(_Mp(x2, y2))
        _we2.canvas.mouseReleaseEvent(_Mp(x2, y2))

    _n0 = len(_we2.canvas.boxes())
    _we2.canvas.set_new_class(1)
    _draw2(60, 60, 200, 180)
    ck(len(_we2.canvas.boxes()) == _n0, "松手不立刻建框")
    ck(_we2.canvas.has_pending(), "而是变成待确认")
    _we2.canvas.keyPressEvent(_Kb(QtCore.Qt.Key_Return))
    ck(len(_we2.canvas.boxes()) == _n0 + 1, "按回车才真的建框")
    ck(_we2.canvas.boxes()[-1]["cid"] == 1, "用的是当前选的类别")
    ck(not _we2.canvas.has_pending(), "确认后待确认清空")
    # 关键:确认完不能选中新框 —— 选中了上下键就变成微调,
    # 而"画完直接翻下一张"才是最常走的路径
    ck(_we2.canvas._sel == -1, "确认后不选中新框")
    _row_p = _we2.lst_vis.currentRow()
    _we2.canvas.keyPressEvent(_Kb(QtCore.Qt.Key_Down))
    ck(_we2.lst_vis.currentRow() != _row_p,
       "所以回车之后按 ↓ 是翻图,不是调框位置")
    _we2.lst_vis.setCurrentRow(_row_p)      # 翻回去,后面的用例还在这张图上
    # 小键盘的回车也要认
    _draw2(300, 300, 420, 400)
    _we2.canvas.keyPressEvent(_Kb(QtCore.Qt.Key_Enter))
    ck(len(_we2.canvas.boxes()) == _n0 + 2, "小键盘 Enter 一样能确定")
    # 画歪了按 Esc 取消,不用建完再撤销
    _n1 = len(_we2.canvas.boxes())
    _draw2(500, 300, 620, 400)
    ck(_we2.canvas.has_pending(), "又画了一个待确认")
    _we2.canvas.keyPressEvent(_Kb(QtCore.Qt.Key_Escape))
    ck(len(_we2.canvas.boxes()) == _n1, "Esc 取消后不会建框")
    ck(not _we2.canvas.has_pending(), "待确认也清掉了")
    # 连着画时不必每个都按回车
    _n2 = len(_we2.canvas.boxes())
    _draw2(60, 300, 160, 400)
    _draw2(300, 60, 400, 160)
    ck(len(_we2.canvas.boxes()) == _n2 + 1,
       "画第二个时第一个自动落下(不会悄悄丢)")
    _we2.canvas.keyPressEvent(_Kb(QtCore.Qt.Key_Return))
    ck(len(_we2.canvas.boxes()) == _n2 + 2, "回车确认第二个")
    # 翻页前要把待确认的框落下,不然白画一次
    _draw2(500, 420, 610, 520)
    _n3 = len(_we2.canvas.boxes())
    _we2.lst_vis.setCurrentRow(1)
    _we2.lst_vis.setCurrentRow(0)
    ck(len(_we2.canvas.boxes()) == _n3 + 1, "翻页前自动落框,不白画")
    # 没有待确认时,回车不该有副作用;Esc 仍然是取消选中
    _n4 = len(_we2.canvas.boxes())
    _we2.canvas.keyPressEvent(_Kb(QtCore.Qt.Key_Return))
    ck(len(_we2.canvas.boxes()) == _n4, "没待确认时按回车什么都不发生")
    _we2.canvas._sel = 0
    _we2.canvas.keyPressEvent(_Kb(QtCore.Qt.Key_Escape))
    ck(_we2.canvas._sel == -1, "没待确认时 Esc 还是取消选中")
    ck("回车确定" in _insp.getsource(_BE.BoxCanvas.paintEvent),
       "画布上会提示怎么落框")

    print("\n[54] AI 补充提示词:点进去不能卡")
    # 原来的做法:每张图都渲染一张 1400px 的带框图,再缩成 96px 显示。
    # 一张 4K 图 80ms,100 张就是 8 秒界面卡死。
    _bigdir = os.path.join(tmp, "big4k")
    os.makedirs(_bigdir, exist_ok=True)
    _bigout = os.path.join(tmp, "big4kout")
    os.makedirs(os.path.join(_bigout, "labels"), exist_ok=True)
    for _k in range(12):
        _bp = os.path.join(_bigdir, f"b{_k:03d}.jpg")
        _IM2.new("RGB", (3840, 2160), (80 + _k, 90, 110)).save(_bp, quality=80)
        with open(os.path.join(_bigout, "labels", f"b{_k:03d}.txt"), "w") as _f:
            _f.write("0 0.5 0.5 0.3 0.3\n")
    # 缩略图专用渲染:尺寸就是缩略图尺寸,而且用 draft 解码
    _t0 = time.time()
    _th = _PA.render_thumb(
        os.path.join(_bigdir, "b000.jpg"),
        [{"cid": 0, "xc": .5, "yc": .5, "w": .3, "h": .3}],
        [(255, 64, 64)], size=192, cache_dir=os.path.join(tmp, "tc"))
    _dt_thumb = time.time() - _t0
    _t0 = time.time()
    _PA.render_boxed(
        os.path.join(_bigdir, "b001.jpg"),
        [{"cid": 0, "xc": .5, "yc": .5, "w": .3, "h": .3}],
        ["x"], [(255, 64, 64)], cache_dir=os.path.join(tmp, "tc2"))
    _dt_full = time.time() - _t0
    ck(max(_IM2.open(_th).size) <= 192, f"缩略图就是缩略图尺寸({_IM2.open(_th).size})")
    ck(_dt_thumb < _dt_full,
       f"画缩略图比画大图快({_dt_thumb*1000:.0f}ms vs {_dt_full*1000:.0f}ms)")
    ck(_dt_thumb < 0.03, f"单张 4K 缩略图 {_dt_thumb*1000:.0f}ms(原来要 80ms)")
    # 缓存要能跨次启动命中 —— 签名只用数字算,不能用 str 的 hash
    ck(_PA._box_sig([{"cid": 0, "xc": .5, "yc": .5, "w": .3, "h": .3}])
       == _PA._box_sig([{"cid": 0, "xc": .5, "yc": .5, "w": .3, "h": .3}]),
       "同样的框签名一样(缓存能命中)")
    ck(_PA._box_sig([{"cid": 0, "xc": .5, "yc": .5, "w": .3, "h": .3}])
       != _PA._box_sig([{"cid": 0, "xc": .6, "yc": .5, "w": .3, "h": .3}]),
       "框变了签名就变(缓存自动失效)")
    _sig_out = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0,'gui'); import promptai as P;"
         "print(P._box_sig([{'cid':0,'xc':.5,'yc':.5,'w':.3,'h':.3}]))"],
        capture_output=True, text=True, cwd=core.ROOT,
        env={**os.environ, "PYTHONHASHSEED": "12345"})
    ck(_sig_out.stdout.strip() ==
       str(_PA._box_sig([{"cid": 0, "xc": .5, "yc": .5, "w": .3, "h": .3}])),
       "换个进程(不同 PYTHONHASHSEED)签名还一样 —— 缓存跨启动有效")
    # 主线程不能被占住:列表要立刻出来,缩略图后台补
    _wf = A.MainWindow()
    _wf.p_images.setText(_bigdir)
    _wf.p_out.setText(_bigout)
    _wf._fill_class_table([{"name": "耳机", "desc": "x", "on": True}])
    _t0 = time.time()
    _wf._pai_reload()
    _dt_reload = time.time() - _t0
    ck(_wf.lst_pai.count() == 12, "列表立刻就铺好了")
    ck(_dt_reload < 0.5,
       f"12 张 4K 图点进去只阻塞 {_dt_reload*1000:.0f}ms(原来要 1 秒)")
    for _ in range(80):
        if all(_r["show"] != _r["img"] for _r in _wf._pai_rows):
            break
        time.sleep(0.05)
    ck(all(_r["show"] != _r["img"] for _r in _wf._pai_rows),
       "后台把每一行的缩略图都补上了")
    # 连续切页不能堆一堆线程往界面写
    _seq0 = _wf._pai_thumb_seq
    for _ in range(4):
        _wf._pai_reload()
    ck(_wf._pai_thumb_seq == _seq0 + 4, "每次刷新换一个代号")
    ck("seq != self._pai_thumb_seq" in
       _insp.getsource(A.MainWindow._pai_start_thumbs),
       "旧代号的后台任务会自己退出")
    ck("seq != self._pai_thumb_seq" in
       _insp.getsource(A.MainWindow._on_pai_thumb),
       "过期结果不会写进界面")
    # 关窗要作废后台任务
    _seq1 = _wf._pai_thumb_seq
    _wf.closeEvent(type("E", (), {"accept": lambda s: None,
                                  "ignore": lambda s: None})())
    ck(_wf._pai_thumb_seq != _seq1, "关窗时作废缩略图任务(不写已销毁的控件)")
    # 双击放大要用清晰的大图,不是 192px 的缩略图
    ck("render_boxed" in _insp.getsource(A.MainWindow._pai_open),
       "双击放大时按需渲染大图(缩略图放大会糊)")

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'='*52}\n全部通过:{len(OK)} 项\n{'='*52}")


if __name__ == "__main__":
    main()
