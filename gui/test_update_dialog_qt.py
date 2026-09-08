#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""更新弹窗的真实 Qt 布局测试。"""
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["BEST_YOLO_DISABLE_UPDATE_CHECK"] = "1"

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog

import app as A
import core
import update_check
from appmeta import APP_VERSION


class UpdateDialogQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="best_yolo_update_qt_")
        core.PROJECTS_DIR = A.core.PROJECTS_DIR = os.path.join(self.tmp, "projects")
        core.STATE_PATH = A.core.STATE_PATH = os.path.join(self.tmp, "state.json")
        core.CONFIG_PATH = A.core.CONFIG_PATH = os.path.join(self.tmp, "config.json")
        os.makedirs(core.PROJECTS_DIR)
        self.window = A.MainWindow()
        self.window.show()
        QApplication.processEvents()

    def tearDown(self):
        for widget in QApplication.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QApplication.processEvents()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_manual_link_and_buttons_fit_real_dialog(self):
        payload = {
            "tag_name": "v9.8.7",
            "name": "Best yolo v9.8.7",
            "body": "## 新增功能\n\n- 示例更新内容\n\n## 修复内容\n\n- 示例修复内容",
            "published_at": "2026-09-08T08:00:00Z",
            "draft": False,
            "prerelease": False,
        }
        release = update_check.parse_release(payload, APP_VERSION)
        self.window._latest_release = release
        captured = {}

        def inspect_and_close():
            dialogs = [widget for widget in QApplication.topLevelWidgets()
                       if isinstance(widget, QDialog) and
                       widget.objectName() == "UpdateDialog"]
            captured["count"] = len(dialogs)
            if dialogs:
                dialog = dialogs[0]
                QApplication.processEvents()
                captured["dialog"] = dialog
                captured["link_width"] = dialog.release_url_label.width()
                captured["text_width"] = dialog.release_url_label.fontMetrics().horizontalAdvance(
                    release["url"])
                captured["overlap"] = dialog.release_url_label.geometry().intersects(
                    dialog.copy_release_button.geometry())
                screenshot = os.environ.get(
                    "BEST_YOLO_UPDATE_SCREENSHOT",
                    os.path.join(self.tmp, "update-dialog.png"))
                dialog.grab().save(screenshot)
            for dialog in dialogs:
                dialog.reject()

        QTimer.singleShot(40, inspect_and_close)
        returned = self.window._show_update_dialog()
        self.assertEqual(captured.get("count"), 1)
        dialog = captured["dialog"]
        self.assertIs(returned, dialog)
        self.assertIn("无法自动跳转", dialog.release_fallback_label.text())
        self.assertIn(release["url"], dialog.release_url_label.text())
        self.assertEqual(dialog.copy_release_button.text(), "复制链接")
        self.assertEqual(dialog.open_release_button.text(), "前往 GitHub 发布页")
        self.assertGreaterEqual(captured["link_width"], captured["text_width"])
        self.assertFalse(captured["overlap"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
