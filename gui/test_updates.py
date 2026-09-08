#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import sys
import unittest


os.environ["BEST_YOLO_DISABLE_UPDATE_CHECK"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import _qtstub
QtWidgets, _, _ = _qtstub.install()

import app
from appmeta import APP_VERSION
import update_check


class _Response:
    def __init__(self, payload=b"{}", status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit=-1):
        return self.payload if limit < 0 else self.payload[:limit]


class _Opener:
    def __init__(self, response=None, error=None):
        self.response = response or _Response()
        self.error = error
        self.requests = []

    def open(self, request, timeout=0):
        self.requests.append((request, timeout))
        if self.error:
            raise self.error
        return self.response


def _payload(tag="v1.4.0", body="## 新增功能\n\n- 自动更新提示"):
    return {
        "tag_name": tag,
        "name": f"Best yolo {tag}",
        "body": body,
        "published_at": "2026-09-08T08:00:00Z",
        "draft": False,
        "prerelease": False,
    }


class UpdateLogicTests(unittest.TestCase):
    def test_semantic_version_comparison(self):
        self.assertTrue(update_check.is_newer("v1.1.0", "1.0.9"))
        self.assertTrue(update_check.is_newer("v2.0.0", "1.99.99"))
        self.assertFalse(update_check.is_newer("v1.1.0", "1.1.0"))
        self.assertFalse(update_check.is_newer("v1.0.9", "1.1.0"))
        self.assertFalse(update_check.is_newer("not-a-version", "1.1.0"))

    def test_release_payload_is_validated(self):
        release = update_check.parse_release(_payload(), "1.1.0")
        self.assertTrue(release["update_available"])
        self.assertEqual(release["version"], "1.4.0")
        self.assertEqual(
            release["url"],
            "https://github.com/LIANGFENG1007/best-yolo/releases/tag/v1.4.0")
        self.assertIn("自动更新提示", release["body"])
        bad = _payload()
        bad["prerelease"] = True
        with self.assertRaises(ValueError):
            update_check.parse_release(bad, "1.1.0")

    def test_network_failure_is_quiet_and_friendly(self):
        release, error = update_check.check_for_update(
            loader=lambda timeout: (_ for _ in ()).throw(OSError("offline")))
        self.assertEqual(release, {})
        self.assertEqual(error, update_check.NO_NETWORK_MESSAGE)

    def test_release_page_probe(self):
        url = "https://github.com/LIANGFENG1007/best-yolo/releases/tag/v1.2.0"
        ok, error = update_check.probe_release_page(
            url, opener=_Opener(_Response(status=200)))
        self.assertTrue(ok)
        self.assertEqual(error, "")
        ok, error = update_check.probe_release_page(
            url, opener=_Opener(error=OSError("offline")))
        self.assertFalse(ok)
        self.assertEqual(error, update_check.NO_NETWORK_MESSAGE)
        self.assertFalse(update_check.probe_release_page("https://example.com/")[0])

    def test_latest_json_request_has_versioned_user_agent(self):
        raw = json.dumps(_payload()).encode("utf-8")
        opener = _Opener(_Response(raw))
        got = update_check._load_latest_json(timeout=3, opener=opener)
        self.assertEqual(got["tag_name"], "v1.4.0")
        request, timeout = opener.requests[0]
        self.assertEqual(timeout, 3.0)
        self.assertIn(APP_VERSION, request.get_header("User-agent"))


class UpdateUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        QtWidgets.QMessageBox.CALLS.clear()
        self.window = app.MainWindow()

    def test_button_switches_between_blue_and_red_state(self):
        self.assertEqual(self.window.btn_update.text(), "检测更新")
        self.assertEqual(self.window.btn_update.objectName(), "UpdateCheckBtn")
        release = update_check.parse_release(_payload("v1.4.0"), APP_VERSION)
        self.window._update_check_seq = 1
        self.window._on_update_ready(1, release, "", False)
        self.assertEqual(self.window.btn_update.text(), "发现更新")
        self.assertEqual(self.window.btn_update.objectName(), "UpdateAvailableBtn")

        called = []
        self.window._show_update_dialog = lambda: called.append(True)
        self.window.btn_update.click()
        self.assertEqual(called, [True])

        current = update_check.parse_release(_payload(f"v{APP_VERSION}"), APP_VERSION)
        self.window._update_check_seq = 2
        self.window._on_update_ready(2, current, "", False)
        self.assertEqual(self.window.btn_update.text(), "检测更新")
        self.assertEqual(self.window.btn_update.objectName(), "UpdateCheckBtn")

    def test_automatic_failure_is_silent_manual_failure_is_visible(self):
        self.window._update_check_seq = 1
        self.window._on_update_ready(1, {}, update_check.NO_NETWORK_MESSAGE, False)
        self.assertEqual(QtWidgets.QMessageBox.CALLS, [])
        self.window._update_check_seq = 2
        self.window._on_update_ready(2, {}, update_check.NO_NETWORK_MESSAGE, True)
        self.assertEqual(QtWidgets.QMessageBox.CALLS[-1][1], "没有网络")

    def test_timeout_resets_manual_check_and_ignores_late_result(self):
        self.window._update_checking = True
        self.window._update_manual_wait = True
        self.window._update_check_seq = 9
        self.window._set_update_button(checking=True)
        self.window._update_check_timeout(9)
        self.assertFalse(self.window._update_checking)
        self.assertEqual(self.window.btn_update.text(), "检测更新")
        self.assertEqual(QtWidgets.QMessageBox.CALLS[-1][1], "没有网络")

        release = update_check.parse_release(_payload("v9.0.0"), APP_VERSION)
        self.window._on_update_ready(9, release, "", False)
        self.assertEqual(self.window.btn_update.text(), "检测更新")

    def test_release_link_failure_reports_no_network(self):
        self.window._update_link_seq = 7
        self.window._update_dialog = QtWidgets.QDialog()
        self.window._update_go_button = QtWidgets.QPushButton()
        self.window._on_update_page_ready(
            7, False, update_check.NO_NETWORK_MESSAGE)
        self.assertEqual(self.window._update_go_button.text(), "前往 GitHub 发布页")
        self.assertEqual(QtWidgets.QMessageBox.CALLS[-1][1], "没有网络")


if __name__ == "__main__":
    unittest.main(verbosity=2)
