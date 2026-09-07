# -*- coding: utf-8 -*-
"""用 QProcess 跑标注/建数据集脚本,把输出实时喂给界面。

为什么用 QProcess 而不是 subprocess+线程:
QProcess 的信号本来就在 Qt 主线程派发,不用自己做线程转发,也不会卡界面。
"""
import os
import sys
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

import core


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
        p.setProgram(sys.executable)      # 用当前解释器 = venv 里的 python
        # -u = 不缓冲输出。管道模式下 Python 默认按块缓冲,
        # 日志会攒一大坨才冒出来,看着像卡死(重试等待时尤其明显)。
        p.setArguments(["-u", script] + list(args))
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
            self.line.emit("✗ 启动失败:无法运行 " + sys.executable)
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
