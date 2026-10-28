# -*- coding: utf-8 -*-
"""跨模块联调：Web 平台调用 报告插件，真实生成 PDF 并提供下载。

这是把 平台（陈卉妍）与 报告（赵文哲）接起来以后最容易出问题的一环：
平台 按 ``generate_report(result=..., model=..., rulebook=..., output_path=...)``
调用，报告 原生接口是 ``generate_report(run, output_root, model=..., rules=...)``。
本用例走真实 provider（不做 mock），确认两边参数能对上、文件真的生成。

依赖 fastapi/httpx（平台）与 reportlab/Pillow（报告）；缺任意一项时跳过。
"""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

MODULES_ROOT = Path(__file__).resolve().parents[1]

try:
    from fastapi.testclient import TestClient

    from nxdrp.checkers.platform_web.backend._server import create_app
except ModuleNotFoundError as exc:  # pragma: no cover - 取决于本机环境
    raise unittest.SkipTest(f"缺少 平台 依赖：{exc}；见 platform_web/requirements.txt") from exc

from nxdrp.checkers.report.service import capabilities as report_capabilities


@unittest.skipUnless(report_capabilities().get("pdf"), "缺少 报告 的 PDF 依赖 reportlab/Pillow")
class M7ToM8ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="platform-report-")
        self.directory = Path(self.tmp.name)
        self.app = create_app(self.directory)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.book = self.client.get("/api/rulebooks").json()[0]

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.tmp.cleanup()

    def _wait(self, key, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            task = self.client.get(f"/api/tasks/{key}").json()
            if task["state"] in {"completed", "failed"}:
                return task
            time.sleep(0.05)
        self.fail("任务未在超时时间内完成")

    def test_platform_generates_pdf_through_real_report(self):
        upload = self.client.post(
            "/api/models",
            files={
                "file": (
                    "board_a.model.json",
                    (MODULES_ROOT / "mockdata/models/board_a.model.json").read_bytes(),
                    "application/json",
                )
            },
        )
        self.assertEqual(upload.status_code, 201, upload.text)
        submit = self.client.post(
            "/api/tasks", json={"model_id": upload.json()["id"], "rulebook_id": self.book["id"], "only": []}
        )
        self.assertEqual(submit.status_code, 202, submit.text)
        key = submit.json()["id"]
        self.assertEqual(self._wait(key)["state"], "completed")
        self.assertGreater(len(self.client.get(f"/api/tasks/{key}/result").json()["findings"]), 0)

        with patch.dict(os.environ, {"NXDRP_REPORT_PROVIDER": "nxdrp.checkers.report:generate_report"}):
            response = self.client.post(f"/api/tasks/{key}/reports/pdf")
            self.assertEqual(response.status_code, 200, response.text)
            download = self.client.get(response.json()["download_url"])
        self.assertEqual(download.status_code, 200)
        self.assertTrue(download.content.startswith(b"%PDF"), "下载内容不是有效 PDF")
        self.assertGreater(len(download.content), 10_000)


if __name__ == "__main__":
    unittest.main()
