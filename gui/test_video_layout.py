#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频切片页在不同界面缩放比例下的真实 Qt 布局回归测试。"""
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

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QFrame, QScrollArea

import app as A
import core
import theme


class VideoLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="best_yolo_video_layout_")
        core.PROJECTS_DIR = A.core.PROJECTS_DIR = os.path.join(self.tmp, "projects")
        core.STATE_PATH = A.core.STATE_PATH = os.path.join(self.tmp, "state.json")
        core.CONFIG_PATH = A.core.CONFIG_PATH = os.path.join(self.tmp, "config.json")
        os.makedirs(core.PROJECTS_DIR)
        core.create_project("test")
        core.save_state(project="test", zoom=1.0)
        theme.apply_theme(theme.preset_colors(theme.DEFAULT_THEME_ID))
        theme.apply_palette(self.qt)
        self.qt.setStyleSheet(theme.stylesheet())
        self.window = A.MainWindow()
        self.window.resize(900, 700)
        self.window.show()
        self.window._go(self.window.PAGE_VIDEO)
        self.qt.processEvents()

    def tearDown(self):
        for widget in QApplication.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QApplication.processEvents()
        theme.apply_theme(theme.preset_colors(theme.DEFAULT_THEME_ID))
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cards(self):
        return sorted(
            [card for card in self.window.video_settings_content.findChildren(QFrame)
             if card.objectName() == "Card"],
            key=lambda card: card.geometry().y())

    def test_form_cards_keep_gaps_and_bottom_is_reachable_at_every_scale(self):
        for scale in self.window.ZOOM_STEPS:
            self.window._ui_k = scale
            self.window._apply_scale()
            self.window.resize(900, 700)
            self.window._go(self.window.PAGE_VIDEO)
            self.qt.processEvents()

            scroll = self.window.video_settings_scroll
            content = self.window.video_settings_content
            self.assertIsInstance(scroll, QScrollArea)
            cards = self._cards()
            self.assertEqual(len(cards), 4, scale)

            # 每张卡都必须在上一张结束之后，间距不能为负。
            for previous, current in zip(cards, cards[1:]):
                self.assertGreaterEqual(
                    current.geometry().y(),
                    previous.geometry().y() + previous.geometry().height(),
                    f"scale={scale}: cards overlap")

            # 三张设置卡不能低于自身内容的最小高度；最后一张允许缩小，
            # 不足的内容由滚动区承担。
            for card in cards[:3]:
                self.assertGreaterEqual(
                    card.height(), card.minimumSizeHint().height(),
                    f"scale={scale}: form card compressed")
            bottom = cards[-1].geometry().y() + cards[-1].height()
            self.assertLessEqual(bottom, content.height(), scale)

            # 滚到最底部后，最后一张卡必须落在可视区域内。
            scroll.verticalScrollBar().setValue(
                scroll.verticalScrollBar().maximum())
            self.qt.processEvents()
            last_top = cards[-1].mapTo(scroll.viewport(), cards[-1].rect().topLeft()).y()
            last_bottom = last_top + cards[-1].height()
            self.assertGreaterEqual(last_bottom, 0, scale)
            self.assertLessEqual(last_top, scroll.viewport().height(), scale)

            # 高缩放时次要按钮允许换行；无论是否换行，按钮都不能越出开始卡。
            start = cards[1]
            for button in (self.window.btn_vstop, self.window.btn_vopen,
                           self.window.btn_vuse):
                top_left = button.mapTo(start, button.rect().topLeft())
                bottom_right = button.mapTo(start, button.rect().bottomRight())
                self.assertGreaterEqual(top_left.x(), 0, scale)
                self.assertGreaterEqual(top_left.y(), 0, scale)
                self.assertLessEqual(bottom_right.x(), start.width(), scale)
                self.assertLessEqual(bottom_right.y(), start.height(), scale)

            # 右侧内容不应因为按钮一行过长而被迫横向裁切；极窄窗口下
            # 若 Qt 必须保留横向滚动条，也要保证它是可用的而非隐藏内容。
            self.assertGreaterEqual(scroll.horizontalScrollBar().maximum(), 0)

    def test_mouse_wheel_scrolls_the_video_settings_column(self):
        self.window._ui_k = 0.9
        self.window._apply_scale()
        self.window.resize(900, 700)
        self.window._go(self.window.PAGE_VIDEO)
        self.qt.processEvents()
        scroll = self.window.video_settings_scroll
        before = scroll.verticalScrollBar().value()
        point = scroll.viewport().rect().center()
        event = QWheelEvent(
            QPointF(point), QPointF(point), QPoint(0, 0), QPoint(0, -240),
            Qt.NoButton, Qt.NoModifier, Qt.ScrollPhase.ScrollUpdate, False)
        QApplication.sendEvent(scroll.viewport(), event)
        self.qt.processEvents()
        self.assertGreater(scroll.verticalScrollBar().value(), before)

    def test_wheel_over_an_unfocused_input_scrolls_without_changing_its_value(self):
        self.window._ui_k = 0.9
        self.window._apply_scale()
        self.window.resize(900, 700)
        self.window._go(self.window.PAGE_VIDEO)
        self.qt.processEvents()
        scroll = self.window.video_settings_scroll
        spin = self.window.sp_ivl
        spin.clearFocus()
        before_value = spin.value()
        before_scroll = scroll.verticalScrollBar().value()
        point = spin.rect().center()
        event = QWheelEvent(
            QPointF(point), QPointF(point), QPoint(0, 0), QPoint(0, -240),
            Qt.NoButton, Qt.NoModifier, Qt.ScrollPhase.ScrollUpdate, False)
        QApplication.sendEvent(spin, event)
        self.qt.processEvents()
        self.assertEqual(spin.value(), before_value)
        self.assertGreater(scroll.verticalScrollBar().value(), before_scroll)


if __name__ == "__main__":
    unittest.main(verbosity=2)
