# -*- coding: utf-8 -*-
"""执行器：Mock 模型上的检查、两种物理仿真、评测、NX 参数驱动（假平台）。"""

import tempfile
import unittest
from pathlib import Path

from nxdrp.assistant import context
from nxdrp.assistant.executor import ExecutionError, Executor
from nxdrp.assistant.spec import TaskSpec, TaskSpecError


def run_spec(data: dict, **kwargs) -> dict:
    return Executor(root=context.repo_root(), **kwargs).execute(TaskSpec.from_dict(data))


def check_spec(**overrides) -> dict:
    data = {
        "spec_version": "1.0",
        "intent": "check",
        "model": {"ref": "board_a", "kind": "sample"},
        "checks": {"only": ["DFM-31"]},
    }
    data.update(overrides)
    return data


class ExecutorCheckTests(unittest.TestCase):
    def test_dfm31_on_mock_model(self):
        payload = run_spec(check_spec())
        self.assertEqual(payload["state"], "completed")
        self.assertEqual(payload["checks"]["executed"], 1)
        self.assertEqual(payload["checks"]["total"], 1)
        self.assertGreaterEqual(payload["checks"]["finding_count"], 1)
        self.assertEqual(payload["model"]["model_id"], "board_a")
        self.assertTrue(payload["checks"]["basis"][0]["source_standard"])
        self.assertIn("board_a", payload["summary"]["text"])

    def test_all_checks_scope(self):
        payload = run_spec(check_spec(checks={"only": []}))
        self.assertGreater(payload["checks"]["total"], 20)
        self.assertIn("DFM-31", {r["check_item_id"] for r in payload["checks"]["results"]})

    def test_check_without_model_is_rejected(self):
        with self.assertRaises(TaskSpecError) as caught:
            run_spec({"intent": "check", "model": {"ref": ""}})
        self.assertIn("model.ref", str(caught.exception))

    def test_unknown_model_is_rejected(self):
        with self.assertRaises(ExecutionError) as caught:
            run_spec(check_spec(model={"ref": "not_a_model", "kind": "sample"}))
        self.assertEqual(caught.exception.stage, "resolve")


class ExecutorSimulationTests(unittest.TestCase):
    def test_current_temp_uses_overridden_current(self):
        payload = run_spec(
            {
                "intent": "pipeline",
                "model": {"ref": "board_a", "kind": "sample"},
                "checks": {"only": ["PERF-01"]},
                "simulation": {"scenario": "current_temp", "conditions": {"current_a": 20}},
            }
        )
        simulation = payload["simulation"]
        self.assertEqual(simulation["scenario"], "current_temp")
        self.assertGreater(simulation["outputs"]["delta_t_c"], 140.0)
        self.assertTrue(simulation["outputs"]["alarm"])
        # 检查器必须用同一份工况，不能仍然是 16 A。
        perf = [f for f in payload["checks"]["findings"] if f["check_item_id"] == "PERF-01"]
        self.assertTrue(perf)
        self.assertIn("20.0 A", perf[0]["message"])

    def test_geometry_only_prediction_without_model(self):
        payload = run_spec(
            {
                "intent": "predict",
                "model": {"ref": ""},
                "simulation": {
                    "scenario": "current_temp",
                    "conditions": {"area_mm2": 3.5, "length_mm": 12, "material": "Cu", "current_a": 25},
                },
            }
        )
        self.assertIsNone(payload["model"])
        self.assertGreater(payload["simulation"]["outputs"]["delta_t_c"], 0)
        self.assertIn("未指定", payload["summary"]["text"])

    def test_insertion_force_on_model(self):
        payload = run_spec(
            {
                "intent": "predict",
                "model": {"ref": "contact_spring", "kind": "sample"},
                "simulation": {"scenario": "insertion_force", "conditions": {}},
            }
        )
        out = payload["simulation"]["outputs"]
        self.assertAlmostEqual(out["insertion_force_n"], 75.70, places=1)
        self.assertTrue(out["alarm"])

    def test_insertion_force_geometry_only(self):
        payload = run_spec(
            {
                "intent": "predict",
                "model": {"ref": ""},
                "simulation": {
                    "scenario": "insertion_force",
                    "conditions": {
                        "length_mm": 8,
                        "width_mm": 2,
                        "thickness_mm": 0.5,
                        "material": "CuSn6",
                    },
                },
            }
        )
        self.assertGreater(payload["simulation"]["outputs"]["insertion_force_n"], 0)

    def test_out_of_range_condition_is_explained(self):
        with self.assertRaises(ExecutionError) as caught:
            run_spec(
                {
                    "intent": "predict",
                    "model": {"ref": ""},
                    "simulation": {
                        "scenario": "current_temp",
                        "conditions": {"area_mm2": 0.1, "length_mm": 12, "material": "Cu"},
                    },
                }
            )
        self.assertEqual(caught.exception.stage, "simulate")
        self.assertIn("超出适用范围", str(caught.exception))


class FakeWorkbench:
    def __init__(self, folder: Path, available: bool = True):
        self.folder_path = Path(folder)
        self.available = available
        self.submitted = None

    def settings(self):
        return {"batch_found": self.available, "root": "X:/NX"}

    def submit(self, action, model_id=None, source_job_id=None, parameters=None, open_after=False):
        self.submitted = {
            "action": action,
            "model_id": model_id,
            "source_job_id": source_job_id,
            "parameters": parameters,
        }
        return {"id": "b" * 32, "state": "queued"}

    def detail(self, key):
        return {"id": key, "state": "completed", "result": {"changed": self.submitted["parameters"]}}

    def folder(self, key):
        return self.folder_path


class FakePlatform:
    def __init__(self, folder: Path, available: bool = True):
        self.nx_workbench = FakeWorkbench(folder, available)
        self.registered = []

    def register_model(self, filename, data):
        self.registered.append(filename)
        return {"id": "c" * 32}


class ExecutorNxTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(prefix="assistant-nx-")
        self.tmp = Path(self.tmpdir.name)
        self.platform = FakePlatform(self.tmp)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_nx_parameter_drive_payload(self):
        payload = run_spec(
            {
                "intent": "simulate",
                "model": {"ref": "mockdata/parts/thin_wall.prt", "kind": "path"},
                "simulation": {"scenario": "nx_parameters", "nx_parameters": {"width": 2.5}},
            },
            platform=self.platform,
        )
        self.assertEqual(payload["simulation"]["scenario"], "nx_parameters")
        self.assertEqual(payload["simulation"]["changed"], {"width": 2.5})
        submitted = self.platform.nx_workbench.submitted
        self.assertEqual(submitted["action"], "apply")
        self.assertEqual(submitted["parameters"], {"width": 2.5})
        self.assertEqual(self.platform.registered, ["thin_wall.prt"])

    def test_nx_missing_installation_is_explained(self):
        platform = FakePlatform(self.tmp, available=False)
        with self.assertRaises(ExecutionError) as caught:
            run_spec(
                {
                    "intent": "simulate",
                    "model": {"ref": "mockdata/parts/thin_wall.prt", "kind": "path"},
                    "simulation": {"scenario": "nx_parameters", "nx_parameters": {"width": 2.5}},
                },
                platform=platform,
            )
        self.assertIn("NX", str(caught.exception))

    def test_nx_requires_platform_context(self):
        with self.assertRaises(ExecutionError) as caught:
            run_spec(
                {
                    "intent": "simulate",
                    "model": {"ref": "mockdata/parts/thin_wall.prt", "kind": "path"},
                    "simulation": {"scenario": "nx_parameters", "nx_parameters": {"width": 2.5}},
                }
            )
        self.assertIn("平台服务", str(caught.exception))


class ExecutorEvaluationTests(unittest.TestCase):
    def test_labels_scoring(self):
        payload = run_spec(
            check_spec(
                checks={"only": ["DFM-31"]},
                evaluation={"labels": "mockdata/labels/board_a.labels.json", "radius_mm": 2.0},
            )
        )
        evaluation = payload["evaluation"]
        self.assertGreater(evaluation["label_count"], 0)
        self.assertGreater(evaluation["predicted"], 0)
        self.assertIsNotNone(evaluation["precision"])
        self.assertIn("macro-F1", payload["summary"]["text"])

    def test_missing_labels_file_is_reported(self):
        with self.assertRaises(ExecutionError) as caught:
            run_spec(
                check_spec(evaluation={"labels": "mockdata/labels/nope.labels.json", "radius_mm": 2.0})
            )
        self.assertEqual(caught.exception.stage, "evaluate")


if __name__ == "__main__":
    unittest.main()
