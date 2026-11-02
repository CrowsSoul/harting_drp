# -*- coding: utf-8 -*-
"""语义指令 Web 接口：解析 -> 确认 -> 后台执行 -> 结果回读。"""

import os
import time
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError as exc:  # pragma: no cover - 取决于本机环境
    raise unittest.SkipTest(
        "平台 测试需要第三方依赖（fastapi/httpx）："
        "python -m pip install -r nxdrp/checkers/platform_web/requirements.txt"
    ) from exc

from nxdrp.checkers.platform_web.backend._server import create_app  # noqa: E402
from nxdrp.checkers.platform_web.backend._service import MODULE  # noqa: E402


class AssistantApiTests(unittest.TestCase):
    def setUp(self):
        (MODULE / "runtime").mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix="assistant-api-", dir=MODULE / "runtime")
        self.env = patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""})
        self.env.start()
        self.app = create_app(Path(self.tmp.name))
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env.stop()
        self.tmp.cleanup()

    def make_plan(self, instruction: str) -> dict:
        response = self.client.post("/api/assistant/plans", json={"instruction": instruction})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def wait(self, run_id: str, timeout: float = 20.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            run = self.client.get(f"/api/assistant/runs/{run_id}").json()
            if run["state"] in {"completed", "failed", "cancelled"}:
                return run
            time.sleep(0.03)
        self.fail("执行未在超时内结束")

    def test_health_and_capabilities(self):
        health = self.client.get("/api/assistant/health").json()
        self.assertEqual(health["status"], "ok")
        self.assertIn("llm", health)
        capabilities = self.client.get("/api/assistant/capabilities").json()
        self.assertIn("board_a", {m["ref"] for m in capabilities["models"]})
        self.assertEqual(len(capabilities["checks"]), 44)
        self.assertIn("current_temp", {s["scenario"] for s in capabilities["scenarios"]})
        self.assertTrue(capabilities["examples"])

    def test_plan_does_not_execute(self):
        plan = self.make_plan("board_a 跑 DFM-31")
        self.assertEqual(plan["state"], "pending")
        self.assertEqual(plan["spec"]["model"]["ref"], "board_a")
        self.assertTrue(plan["preview"]["requires_confirmation"])
        self.assertEqual(self.client.get("/api/assistant/runs").json(), [])

    def test_confirm_runs_and_result_is_readable(self):
        plan = self.make_plan("board_a 跑 DFM-31")
        response = self.client.post(
            f"/api/assistant/plans/{plan['plan_id']}/confirm", json={"accept": True}
        )
        self.assertEqual(response.status_code, 202, response.text)
        run = self.wait(response.json()["run_id"])
        self.assertEqual(run["state"], "completed", run.get("error"))
        self.assertEqual(run["result"]["checks"]["executed"], 1)
        self.assertTrue(run["result"]["summary"]["text"])
        download = self.client.get(f"/api/assistant/runs/{run['run_id']}/download")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.json()["checks"]["finding_count"],
                         run["result"]["checks"]["finding_count"])

    def test_edit_spec_before_confirm(self):
        plan = self.make_plan("跑一遍全部检查")
        self.assertIn("model", plan["missing"])
        blocked = self.client.post(
            f"/api/assistant/plans/{plan['plan_id']}/confirm", json={"accept": True}
        )
        self.assertEqual(blocked.status_code, 422)
        edited = dict(plan["spec"])
        edited["model"] = {"ref": "bosses", "kind": "sample"}
        edited["checks"] = {"only": ["DFM-13"]}
        response = self.client.post(
            f"/api/assistant/plans/{plan['plan_id']}/confirm",
            json={"accept": True, "spec": edited},
        )
        self.assertEqual(response.status_code, 202, response.text)
        run = self.wait(response.json()["run_id"])
        self.assertEqual(run["state"], "completed", run.get("error"))
        self.assertEqual(run["spec"]["model"]["ref"], "bosses")

    def test_reject_does_not_create_run(self):
        plan = self.make_plan("board_a 跑 DFM-31")
        response = self.client.post(
            f"/api/assistant/plans/{plan['plan_id']}/confirm", json={"accept": False}
        )
        self.assertEqual(response.json()["state"], "rejected")
        self.assertEqual(self.client.get("/api/assistant/runs").json(), [])
        again = self.client.post(
            f"/api/assistant/plans/{plan['plan_id']}/confirm", json={"accept": True}
        )
        self.assertEqual(again.status_code, 422)

    def test_invalid_inputs(self):
        self.assertEqual(
            self.client.post("/api/assistant/plans", json={"instruction": ""}).status_code, 422
        )
        self.assertEqual(self.client.get("/api/assistant/plans/nope").status_code, 404)
        self.assertEqual(self.client.get("/api/assistant/runs/nope").status_code, 404)

    def test_demo_page(self):
        response = self.client.get("/api/assistant/demo")
        self.assertEqual(response.status_code, 200)
        self.assertIn("语义指令", response.text)
        self.assertIn('/?page=assistant', response.text)

    def test_auto_runs_without_confirmation_and_builds_review_and_pdf(self):
        response = self.client.post(
            "/api/assistant/auto",
            json={"instruction": "board_a 跑 DFM-31"},
        )
        self.assertEqual(response.status_code, 202, response.text)
        body = response.json()
        self.assertEqual(body["plan"]["state"], "confirmed")
        run = self.wait(body["run"]["run_id"])
        self.assertEqual(run["state"], "completed", run.get("error"))
        self.assertIn("verdict", run["result"]["review"])
        self.assertTrue(run["result"]["summary"]["text"])
        report = self.client.get(f"/api/assistant/runs/{run['run_id']}/report.pdf")
        self.assertEqual(report.status_code, 200, report.text)
        self.assertTrue(report.content.startswith(b"%PDF-"))

    def test_auto_rejects_incomplete_task(self):
        response = self.client.post("/api/assistant/auto", json={"instruction": "跑一遍全部检查"})
        self.assertEqual(response.status_code, 422)
        self.assertIn("model", response.text)

    def test_settings_saved_masked_and_cleared(self):
        initial = self.client.get("/api/assistant/settings").json()
        self.assertFalse(initial["configured"])
        response = self.client.put(
            "/api/assistant/settings",
            json={"api_key": "sk-test-1234567890", "model": "deepseek-chat",
                  "base_url": "https://api.deepseek.com"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()
        self.assertTrue(saved["configured"])
        self.assertTrue(saved["masked"].endswith("7890"))
        self.assertNotIn("sk-test-1234567890", response.text)
        # 落盘文件不能有明文
        settings_file = self.app.state.assistant.settings.path
        self.assertNotIn("sk-test-1234567890", settings_file.read_text(encoding="utf-8"))
        # 清除后回到未配置
        cleared = self.client.put("/api/assistant/settings", json={"clear_key": True}).json()
        self.assertFalse(cleared["configured"])

    def test_invalid_settings_rejected(self):
        response = self.client.put(
            "/api/assistant/settings", json={"api_key": "bad key with spaces"}
        )
        self.assertEqual(response.status_code, 422)
        response = self.client.put(
            "/api/assistant/settings", json={"base_url": "not-a-url"}
        )
        self.assertEqual(response.status_code, 422)

    def test_probe_without_key_is_offline(self):
        probe = self.client.post("/api/assistant/llm/probe", json={}).json()
        self.assertFalse(probe["reachable"])

    def test_static_js_is_served_as_javascript(self):
        """白屏回归：Windows 注册表把 .js 标成 text/plain 时，模块脚本会被浏览器拒绝。"""
        assets = sorted((MODULE / "frontend/dist/assets").glob("index-*.js"))
        self.assertTrue(assets, "前端构建产物缺失")
        response = self.client.get(f"/assets/{assets[0].name}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("javascript", response.headers.get("content-type", ""))

    def test_cli_style_sync_execution(self):
        service = self.app.state.assistant
        plan = service.plan("board_a 跑 DFM-31", offline=True)
        run = service.confirm_sync(plan["plan_id"])
        self.assertEqual(run["state"], "completed", run.get("error"))
        self.assertEqual(service.get_plan(plan["plan_id"])["state"], "confirmed")
        self.assertEqual(run["result"]["checks"]["executed"], 1)


if __name__ == "__main__":
    unittest.main()
