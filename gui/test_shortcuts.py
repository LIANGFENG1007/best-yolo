#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快捷键设置的真实 Qt 测试。运行时使用离屏平台，不打开可见窗口。"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shutil
import sys
import tempfile
import unittest

os.environ["BEST_YOLO_DISABLE_UPDATE_CHECK"] = "1"

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import app as A
import core
import shortcut_settings as S


class ShortcutSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qal_shortcuts_")
        core.PROJECTS_DIR = A.core.PROJECTS_DIR = os.path.join(self.tmp, "projects")
        core.STATE_PATH = A.core.STATE_PATH = os.path.join(self.tmp, "state.json")
        core.CONFIG_PATH = A.core.CONFIG_PATH = os.path.join(self.tmp, "config.json")
        os.makedirs(core.PROJECTS_DIR)
        core.create_project("test")
        core.save_state(project="test")

    def tearDown(self):
        for widget in QApplication.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QApplication.processEvents()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_registry_defaults_and_scoped_conflicts(self):
        defaults = S.default_bindings()
        self.assertEqual(len(S.SHORTCUT_DEFINITIONS), 79)
        self.assertEqual(len({d["section"] for d in S.SHORTCUT_DEFINITIONS}), 6)
        self.assertEqual(defaults["mark.save"], ["Ctrl+S"])
        self.assertEqual(defaults["settings.theme"], ["Ctrl+Alt+T"])
        self.assertEqual(S.find_conflicts(defaults), [])

        # 不同页面不会同时生效，因此可以共用同一个按键。
        reused = {**defaults, "home.preview": ["F8"], "video.extract": ["F8"]}
        self.assertEqual(S.find_conflicts(reused), [])

        # 全局命令和任意页面重名都会抢按键，必须阻止保存。
        bad = {**defaults, "nav.home": ["Ctrl+S"]}
        conflicts = S.find_conflicts(bad)
        self.assertTrue(any(pair[1:] == ("nav.home", "mark.save")
                            for pair in conflicts))

    def test_contains_search_and_editor_validation(self):
        dlg = S.ShortcutSettingsDialog(S.default_bindings())
        dlg.show()
        QApplication.processEvents()
        self.assertEqual(dlg.tree.topLevelItemCount(), 6)
        self.assertEqual(dlg._completer.filterMode(), Qt.MatchContains)
        self.assertTrue(any("保存全部修改" in text and "Ctrl+S" in text
                            for text in dlg._search_model.stringList()))

        dlg.search.setText("提示词")
        QApplication.processEvents()
        found = dlg.visible_action_ids()
        self.assertIn("prompt.start", found)
        self.assertIn("nav.prompt", found)
        self.assertLess(len(found), len(S.SHORTCUT_DEFINITIONS))

        dlg.search.setText("保存")
        QApplication.processEvents()
        found = dlg.visible_action_ids()
        self.assertIn("mark.save", found)
        self.assertIn("mark.toggle_autosave", found)

        dlg._working["nav.home"] = ["Ctrl+S"]
        dlg._validate()
        self.assertFalse(dlg.btn_save.isEnabled())
        self.assertIn("冲突", dlg.lb_conflict.text())

    def test_main_window_registration_trigger_and_persistence(self):
        win = A.MainWindow()
        win.show()
        QApplication.processEvents()

        layout = win._zoom_box.layout()
        self.assertLess(layout.indexOf(win.btn_shortcuts),
                        layout.indexOf(win.btn_zoom_out))
        self.assertEqual(set(win._shortcut_handlers_map),
                         set(S.DEFINITION_BY_ID))
        expected = sum(len(v) for v in S.default_bindings().values())
        self.assertEqual(len(win._shortcut_objects), expected)

        def enabled(sid):
            return [shortcut.isEnabled()
                    for shortcut, spec, _seq in win._shortcut_objects
                    if spec["id"] == sid]

        win.pages.setCurrentIndex(win.PAGE_HOME)
        QApplication.processEvents()
        self.assertTrue(all(enabled("home.preview")))
        self.assertFalse(any(enabled("dataset.generate")))
        win.pages.setCurrentIndex(win.PAGE_DATASET)
        QApplication.processEvents()
        self.assertFalse(any(enabled("home.preview")))
        self.assertTrue(all(enabled("dataset.generate")))

        # 改完立即重建后，真实按键事件应执行新绑定。
        win._shortcut_bindings["nav.video"] = ["Ctrl+Alt+V"]
        win._rebuild_shortcuts()
        win.pages.setCurrentIndex(win.PAGE_HOME)
        win.activateWindow()
        win.setFocus()
        QApplication.processEvents()
        QTest.keyClick(win, Qt.Key_V, Qt.ControlModifier | Qt.AltModifier)
        QApplication.processEvents()
        self.assertEqual(win.pages.currentIndex(), win.PAGE_VIDEO)

        core.save_state(shortcuts=win._shortcut_bindings)
        reopened = A.MainWindow()
        self.assertEqual(reopened._shortcut_bindings["nav.video"],
                         ["Ctrl+Alt+V"])

        # 真实 Qt 不会像测试替身那样吞掉不存在的方法；项目切换必须无异常。
        core.create_project("second")
        reopened._switch_to("second")
        self.assertEqual(reopened._proj, "second")


if __name__ == "__main__":
    unittest.main(verbosity=2)
