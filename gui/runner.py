# -*- coding: utf-8 -*-
"""用 QProcess 跑标注/建数据集脚本,把输出实时喂给界面。

为什么用 QProcess 而不是 subprocess+线程:
QProcess 的信号本来就在 Qt 主线程派发,不用自己做线程转发,也不会卡界面。
"""
import os
import ntpath
import sys
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

import core


def process_command(script, args, *, frozen=None, platform_name=None,
                    executable=None, worker_exe=None):
    """返回 QProcess 要运行的程序与参数。

    Windows GUI 冻结版没有 python.exe，也不能把 BestYolo.exe 当 Python
    解释器使用，所以标注和导出交给安装目录里的控制台 worker。
    可选参数只给跨平台测试使用。
    """
    is_frozen = getattr(sys, "frozen", False) if frozen is None else bool(frozen)
    platform_name = os.name if platform_name is None else platform_name
    executable = sys.executable if executable is None else executable
    args = list(args)
    if is_frozen and platform_name == "nt":
        path_module = ntpath
        mode = {
            "autolabel_qwen.py": "label",
            "build_dataset.py": "dataset",
        }.get(path_module.basename(script))
        if not mode:
            raise ValueError(f"未知的后台任务: {path_module.basename(script)}")
        worker = (worker_exe or os.environ.get("BEST_YOLO_WORKER_EXE") or
                  path_module.join(path_module.dirname(executable),
                                   "BestYoloWorker.exe"))
        return worker, [mode] + args
    return executable, ["-u", script] + args


class ScriptRunner(QObject):
    line = Signal(str)            # 一行输出(已去掉换行)
    progress = Signal(int, int)   # done, total
    finished = Signal(int)        # exit code(被用户停止时为 -1)
    started = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc = None
        self._buf = ""
        self._stopping = False

    def is_running(self):
        return self.proc is not None and self.proc.state() != QProcess.NotRunning

    def start(self, script, args, env, workdir):
        if self.is_running():
            self.line.emit("⚠ 已有任务在跑,先停止它")
            return False
        self._buf = ""
        self._stopping = False
        p = QProcess(self)
        try:
            program, proc_args = process_command(script, args)
        except Exception as e:
            self.line.emit(f"✗ 启动失败: {e}")
            self.finished.emit(1)
            return False
        p.setProgram(program)
        # -u = 不缓冲输出。管道模式下 Python 默认按块缓冲,
        # 日志会攒一大坨才冒出来,看着像卡死(重试等待时尤其明显)。
        p.setArguments(proc_args)
        p.setWorkingDirectory(workdir)
        p.setProcessChannelMode(QProcess.MergedChannels)  # stderr 也收进来
        qe = QProcessEnvironment()
        for k, v in env.items():
            qe.insert(k, str(v))
        p.setProcessEnvironment(qe)
        p.readyReadStandardOutput.connect(self._on_out)
        p.finished.connect(self._on_done)
        p.errorOccurred.connect(self._on_err)
        self.proc = p
        p.start()
        if not p.waitForStarted(5000):
            self.line.emit("✗ 启动失败:无法运行 " + program)
            self.proc = None
            self.finished.emit(1)
            return False
        self.started.emit()
        return True

    def _on_out(self):
        if self.proc is None:
            return
        raw = bytes(self.proc.readAllStandardOutput())
        self._buf += raw.decode("utf-8", errors="replace")
        # 进度条那种 \r 刷新也当成断行,避免整段堆在一行
        self._buf = self._buf.replace("\r\n", "\n").replace("\r", "\n")
        while "\n" in self._buf:
            ln, self._buf = self._buf.split("\n", 1)
            self._emit_line(ln)

    def _emit_line(self, ln):
        self.line.emit(ln)
        pr = core.parse_progress(ln)
        if pr:
            self.progress.emit(pr["done"], pr["total"])

    def _on_err(self, err):
        if self._stopping:
            return
        self.line.emit(f"✗ 进程错误: {err}")

    def _on_done(self, code, status):
        if self._buf.strip():
            self._emit_line(self._buf)
            self._buf = ""
        self.proc = None
        self.finished.emit(-1 if self._stopping else int(code))

    def stop(self):
        if not self.is_running():
            return
        self._stopping = True
        self.line.emit("… 正在停止")
        # 先抓到本地引用:terminate/waitForFinished 期间 finished 信号可能已经
        # 触发 _on_done 把 self.proc 置成 None,直接再用 self.proc 会 AttributeError
        p = self.proc
        p.terminate()
        if p.state() != QProcess.NotRunning and not p.waitForFinished(3000):
            p.kill()                  # 3 秒还没退就强杀
            p.waitForFinished(1000)
