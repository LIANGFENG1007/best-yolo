#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主题引擎和真实 Qt 配色窗口回归测试。"""
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

from PySide6.QtWidgets import QApplication

import app as A
import core
import theme
import theme_settings as T


class ThemeLogicTests(unittest.TestCase):
    def tearDown(self):
        theme.apply_theme(theme.preset_colors(theme.DEFAULT_THEME_ID))

    def test_eight_named_presets_are_complete_and_readable(self):
        self.assertEqual(len(theme.THEME_PRESETS), 8)
        self.assertEqual(
            [item["name"] for item in theme.THEME_PRESETS],
            ["经典黑", "经典白", "流金黑", "玫瑰红", "极光蓝", "翡翠绿",
             "冰川青", "暮光紫"])
        for preset in theme.THEME_PRESETS:
            self.assertEqual(set(preset["colors"]),
                             set(theme.EDITABLE_COLOR_KEYS))
            colors = theme.resolve_theme(preset["colors"])
            self.assertGreaterEqual(
                theme.contrast_ratio(colors["text"], colors["bg"]), 4.5,
                preset["name"])
            self.assertGreaterEqual(
                theme.contrast_ratio(colors["accent_text"], colors["accent"]),
                4.5, preset["name"])
            for key in ("ok", "warn", "err"):
                self.assertGreaterEqual(
                    theme.contrast_ratio(colors[key], colors["card"]), 3.0,
                    f"{preset['name']} {key}")
                self.assertGreaterEqual(
                    theme.contrast_ratio(colors[key + "_text"], colors[key]),
                    4.5, f"{preset['name']} {key} text")

    def test_theme_state_round_trip_and_invalid_values(self):
        colors = theme.preset_colors("black_gold")
        saved = theme.theme_state("black_gold", colors)
        preset_id, loaded = theme.load_theme_state(saved)
        self.assertEqual(preset_id, "black_gold")
        self.assertEqual(loaded, colors)

        colors["text"] = "#123456"
        saved = theme.theme_state("black_gold", colors)
        self.assertEqual(saved["preset"], "custom")
        preset_id, loaded = theme.load_theme_state(saved)
        self.assertEqual(preset_id, "custom")
        self.assertEqual(loaded["text"], "#123456")

        preset_id, loaded = theme.load_theme_state(
            {"preset": "missing", "colors": {"accent": "not-a-color"}})
        self.assertEqual(preset_id, theme.DEFAULT_THEME_ID)
        self.assertEqual(loaded["accent"], "#4A9EFF")

    def test_semantic_button_colors_adapt_to_custom_background(self):
        light = theme.resolve_theme({
            **theme.preset_colors("classic_light"), "accent": "#FFF59D"})
        self.assertEqual(light["accent_text"], "#101114")
        self.assertGreaterEqual(
            theme.contrast_ratio(light["err"], light["card"]), 3.15)
        self.assertGreaterEqual(
            theme.contrast_ratio(light["err_text"], light["err"]), 4.5)


class ThemeQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="best_yolo_theme_")
        core.PROJECTS_DIR = A.core.PROJECTS_DIR = os.path.join(self.tmp, "projects")
        core.STATE_PATH = A.core.STATE_PATH = os.path.join(self.tmp, "state.json")
        core.CONFIG_PATH = A.core.CONFIG_PATH = os.path.join(self.tmp, "config.json")
        os.makedirs(core.PROJECTS_DIR)
        core.create_project("test")
        core.save_state(project="test")
        theme.apply_theme(theme.preset_colors(theme.DEFAULT_THEME_ID))
        theme.apply_palette(self.qt)
        self.qt.setStyleSheet(theme.stylesheet())

    def tearDown(self):
        for widget in QApplication.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QApplication.processEvents()
        theme.apply_theme(theme.preset_colors(theme.DEFAULT_THEME_ID))
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dialog_has_presets_wheel_recommendations_and_custom_state(self):
        dialog = T.ThemeSettingsDialog()
        dialog.show()
        QApplication.processEvents()
        self.assertEqual(len(dialog._preset_buttons), 8)
        self.assertEqual(len(dialog._field_buttons), 7)
        self.assertEqual(len(dialog._recommend_buttons), 12)

        dialog.selectPreset("classic_light")
        preset_id, colors = dialog.selectedTheme()
        self.assertEqual(preset_id, "classic_light")
        self.assertEqual(colors["bg"], "#F3F5F7")
        self.assertTrue(dialog._preset_buttons["classic_light"].isChecked())

        dialog.selectField("text")
        dialog._set_current_color("#123456")
        preset_id, colors = dialog.selectedTheme()
        self.assertEqual(preset_id, "custom")
        self.assertEqual(colors["text"], "#123456")
        self.assertEqual(dialog.hex_edit.text(), "#123456")
        self.assertEqual(dialog.badge.text(), "自定义")

        dialog.wheel.resize(232, 232)
        dialog.wheel.setColor("#00FF00")
        self.assertEqual(dialog.wheel.color(), "#00FF00")
        dialog.wheel.setValue(0.5, emit=False)
        self.assertEqual(dialog.wheel.color(), "#008000")
        image = dialog.wheel._wheel_image()
        self.assertFalse(image.isNull())
        self.assertGreater(image.pixelColor(214, 116).red(), 100)

    def test_main_window_button_apply_and_persistence(self):
        window = A.MainWindow()
        window.show()
        QApplication.processEvents()
        self.assertEqual(window.btn_theme.objectName(), "ThemeSettingsButton")
        self.assertEqual(window.btn_theme.accessibleName(), "界面配色")
        self.assertFalse(window.btn_theme.icon().isNull())
        self.assertIn("Ctrl+Alt+T", window.btn_theme.toolTip())

        custom = theme.preset_colors("classic_light")
        custom["accent"] = "#E05275"
        window._apply_theme_choice("custom", custom)
        self.assertEqual(theme.C["bg"], "#F3F5F7")
        self.assertEqual(theme.C["accent"], "#E05275")
        saved = core.load_state()["theme"]
        self.assertEqual(saved["preset"], "custom")
        self.assertEqual(saved["colors"]["accent"], "#E05275")

        reopened = A.MainWindow()
        self.assertEqual(reopened._theme_id, "custom")
        self.assertEqual(reopened._theme_colors["accent"], "#E05275")


if __name__ == "__main__":
    unittest.main(verbosity=2)
