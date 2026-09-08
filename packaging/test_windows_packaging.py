#!/usr/bin/env python3
from pathlib import Path
import os
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "gui"))
sys.path.insert(0, str(ROOT / "packaging"))

import build_windows
import autolabel_qwen
import runner


class WindowsPackagingTests(unittest.TestCase):
    def test_version_validation(self):
        self.assertEqual(build_windows.parse_version("1.2.3"),
                         ("1.2.3", (1, 2, 3, 0)))
        for value in ("v1.2.3", "1.2", "1.2.3-beta", "1.2.70000"):
            with self.assertRaises(ValueError):
                build_windows.parse_version(value)

    def test_frozen_worker_command(self):
        program, args = runner.process_command(
            r"C:\bundle\autolabel_qwen.py", ["--limit", "3"],
            frozen=True, platform_name="nt",
            executable=r"C:\Program Files\Best yolo\BestYolo.exe",
            worker_exe=r"C:\Program Files\Best yolo\BestYoloWorker.exe")
        self.assertEqual(program,
                         r"C:\Program Files\Best yolo\BestYoloWorker.exe")
        self.assertEqual(args, ["label", "--limit", "3"])

    def test_source_command_still_uses_python(self):
        program, args = runner.process_command(
            "/repo/autolabel_qwen.py", ["--limit", "2"],
            frozen=False, platform_name=os.name,
            executable=sys.executable)
        self.assertEqual(program, sys.executable)
        self.assertEqual(args, ["-u", "/repo/autolabel_qwen.py", "--limit", "2"])

    def test_installer_keeps_directory_page(self):
        script = (ROOT / "packaging" / "windows" / "installer.iss").read_text(
            encoding="utf-8")
        self.assertIn("DisableDirPage=no", script)
        self.assertIn("MinVersion=10.0.17763", script)
        self.assertIn("VC_redist.x64.exe", script)
        self.assertIn("BEST_YOLO_INNO_CHINESE", script)
        self.assertNotIn("[UninstallDelete]", script)

    def test_cloud_resize_has_no_local_model_dependency(self):
        self.assertEqual(
            autolabel_qwen.smart_dims(1920, 1080, 3136, 2_000_000, 32),
            (1856, 1056))
        self.assertEqual(
            autolabel_qwen.smart_dims(40, 20, 3136, 2_000_000, 32),
            (96, 64))
        with self.assertRaises(ValueError):
            autolabel_qwen.smart_dims(1000, 4, 3136, 2_000_000, 32)


if __name__ == "__main__":
    unittest.main()
