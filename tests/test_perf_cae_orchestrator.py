# -*- coding: utf-8 -*-
"""CAE 编排的离线门禁、阶段顺序、恢复及导出契约测试。"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nxdrp.checkers.performance import cae_orchestrator as orch
from nxdrp.checkers.performance.cae_bindings import binding_digest


OUTPUT_UNITS = {
    "maximum_temperature_c": "degC",
    "delta_t_c": "degC",
    "total_resistance_ohm": "ohm",
    "joule_power_w": "W",
    "voltage_drop_v": "V",
}


def capability(status="verified"):
    return {
        "capability_id": "TEST-NX-PERF01",
        "status": status,
        "solution_mode": "thermal_with_joule",
        "solver": "TEST SOLVER",
        "analysis": "Steady Electrothermal",
        "solution_type": "TEST JOULE",
        "native_result_keys": {name: name for name in OUTPUT_UNITS},
    }


class FakeExecutor:
    def __init__(self, root, omit_output=""):
        self.root = root
        self.omit_output = omit_output
        self.calls = []

    def execute(self, journal, request_path, response_path, timeout_s):
        self.calls.append((journal, timeout_s))
        with open(request_path, "r", encoding="utf-8") as fh:
            request = json.load(fh)
        manifest = request["setup_manifest"]
        response = {"ok": True, "case_id": manifest["case_id"], "state": "not_done"}
        if journal == "create_simcenter_case":
            response["state"] = "container_created"
        elif journal == "setup_simcenter_case":
            response["state"] = "solver_ready"
        elif journal == "solve_simcenter_case":
            native = os.path.join(self.root, "native_result.json")
            with open(native, "w", encoding="utf-8") as fh:
                json.dump({"native": True}, fh)
            response.update({
                "state": "solved",
                "native_result_path": native,
                "native_result_digest": orch.file_digest(native),
            })
        elif journal == "export_simcenter_results":
            result = os.path.join(self.root, "solver_result.json")
            units = dict(manifest["required_output_units"])
            if self.omit_output:
                units.pop(self.omit_output, None)
            payload = {
                "schema_version": "1.0.0",
                "batch_id": manifest["batch_id"],
                "case_id": manifest["case_id"],
                "check_item_id": manifest["check_item_id"],
                "setup_digest": manifest["setup_digest"],
                "binding_digest": manifest["binding"]["digest"],
                "solver": {"product": "Simcenter 3D", "version": "TEST", "license_mode": "commercial"},
                "model_identity": manifest["model_identity"],
                "run": {
                    "native_result_path": os.path.join(self.root, "native_result.json"),
                    "native_result_digest": orch.file_digest(os.path.join(self.root, "native_result.json")),
                },
                "convergence_status": "converged",
                "residual": 1e-8,
                "outputs": {name: {"value": 1.0, "unit": unit} for name, unit in units.items()},
            }
            with open(result, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            response.update({"state": "exported", "solver_result_path": result})
        with open(response_path, "w", encoding="utf-8") as fh:
            json.dump(response, fh)
        return response


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name
        self.case = {
            "case_id": "PERF01-TEST-0001",
            "check_item_id": "PERF-01",
            "required_output_units": dict(OUTPUT_UNITS),
            "boundary_conditions": {"current_a": 16.0},
            "mesh": {"element_size_mm": 0.5},
        }
        self.binding = {
            "case_id": self.case["case_id"],
            "check_item_id": "PERF-01",
            "material": {"material": "Cu"},
            "source_geometry": {
                "source_part": os.path.join(self.root, "source.prt"),
                "model_digest": "confirmed-model-digest",
                "body_tags": [1],
                "status": "confirmed",
            },
            "face_roles": {},
            "load_values": {"current_a": 16.0},
            "contact_pairs": [],
            "result_queries": {},
        }
        self.binding["binding_digest"] = binding_digest(self.binding)
        self.write("case.json", self.case)
        self.write("bindings.json", self.binding)

    def write(self, name, payload):
        with open(os.path.join(self.root, name), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def prepare(self, status="verified"):
        return self.prepare_in(self.root, status=status, batch_id="BATCH-TEST")

    def prepare_in(self, case_dir, *, status="verified", batch_id=""):
        with mock.patch.object(orch, "capability_for", return_value=capability(status)), \
             mock.patch.object(orch, "validate_bindings", return_value={"valid": True, "errors": []}):
            return orch.prepare_case(case_dir, "TEST NX", batch_id=batch_id)

    def test_prepare_records_solution_creation_and_versions_artifacts(self):
        self.prepare()
        with open(os.path.join(self.root, "setup_manifest.json"), "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        self.assertIn(manifest["setup_id"], manifest["artifacts"]["fem"])
        self.assertIn(manifest["setup_id"], manifest["artifacts"]["sim"])
        self.assertIn(manifest["setup_id"], manifest["artifacts"]["solver_result"])
        self.assertTrue(orch.build_journal_request(manifest, "setup")["create_solution"])
        self.assertFalse(orch.build_journal_request(manifest, "solve")["create_solution"])

    def test_prepare_infers_batch_id_from_parent_index(self):
        workspace = os.path.join(self.root, "workspace")
        case_dir = os.path.join(workspace, self.case["case_id"])
        os.makedirs(case_dir)
        for name, payload in (("case.json", self.case), ("bindings.json", self.binding)):
            with open(os.path.join(case_dir, name), "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
        with open(os.path.join(workspace, "index.json"), "w", encoding="utf-8") as fh:
            json.dump({
                "batch_id": "BATCH-FROM-INDEX",
                "cases": [{"case_id": self.case["case_id"], "directory": case_dir}],
            }, fh)
        state = self.prepare_in(case_dir)
        self.assertEqual(state["batch_id"], "BATCH-FROM-INDEX")

    def test_reprepare_after_changed_binding_uses_new_artifact_generation(self):
        self.prepare()
        with open(os.path.join(self.root, "setup_manifest.json"), "r", encoding="utf-8") as fh:
            first = json.load(fh)
        changed = dict(self.binding)
        changed["load_values"] = {"current_a": 32.0}
        changed["binding_digest"] = binding_digest(changed)
        self.write("bindings.json", changed)
        self.prepare()
        with open(os.path.join(self.root, "setup_manifest.json"), "r", encoding="utf-8") as fh:
            second = json.load(fh)
        self.assertNotEqual(first["setup_id"], second["setup_id"])
        self.assertNotEqual(first["artifacts"]["fem"], second["artifacts"]["fem"])
        self.assertFalse(os.path.exists(first["artifacts"]["fem"]))

    def test_offline_never_calls_executor(self):
        self.prepare()
        executor = mock.Mock()
        state = orch.run_stage(self.root, "setup", online=False, executor=executor)
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["stages"]["setup"]["error"].split("：")[0], "OFFLINE_EXECUTION_DISABLED")
        executor.execute.assert_not_called()

    def test_unverified_capability_blocks_online_execution(self):
        self.prepare("unverified")
        executor = mock.Mock()
        state = orch.run_stage(self.root, "setup", online=True, executor=executor)
        self.assertEqual(state["status"], "not_done")
        self.assertIn("CAPABILITY_UNVERIFIED", state["stages"]["setup"]["error"])
        executor.execute.assert_not_called()

    def test_stages_cannot_be_skipped(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, "前序阶段"):
            orch.run_stage(self.root, "solve", online=True, executor=FakeExecutor(self.root))

    def test_complete_fake_pipeline_and_resume(self):
        self.prepare()
        executor = FakeExecutor(self.root)
        state = orch.run_stage(self.root, "setup", online=True, executor=executor)
        self.assertEqual(state["stages"]["setup"]["status"], "succeeded")
        state = orch.run_stage(self.root, "solve", online=True, executor=executor)
        self.assertTrue(state["solver_run_performed"])
        state = orch.run_stage(self.root, "export", online=True, executor=executor)
        self.assertEqual(state["status"], "succeeded")
        attempts = state["stages"]["export"]["attempt"]
        calls = len(executor.calls)
        again = orch.run_stage(self.root, "export", online=True, executor=executor)
        self.assertEqual(again["stages"]["export"]["attempt"], attempts)
        self.assertEqual(len(executor.calls), calls)

    def test_incomplete_export_fails_closed(self):
        self.prepare()
        executor = FakeExecutor(self.root, omit_output="voltage_drop_v")
        orch.run_stage(self.root, "setup", online=True, executor=executor)
        orch.run_stage(self.root, "solve", online=True, executor=executor)
        state = orch.run_stage(self.root, "export", online=True, executor=executor)
        self.assertEqual(state["status"], "failed")
        self.assertIn("voltage_drop_v", state["stages"]["export"]["error"])

    def test_changed_binding_invalidates_downstream(self):
        self.prepare()
        changed = dict(self.binding)
        changed["load_values"] = {"current_a": 99.0}
        self.write("bindings.json", changed)
        with self.assertRaisesRegex(ValueError, "binding 已变化"):
            orch.run_stage(self.root, "setup", online=True, executor=FakeExecutor(self.root))

    def test_failed_rerun_invalidates_downstream_success(self):
        self.prepare()
        executor = FakeExecutor(self.root)
        orch.run_stage(self.root, "setup", online=True, executor=executor)
        orch.run_stage(self.root, "solve", online=True, executor=executor)
        state = orch.run_stage(self.root, "export", online=True, executor=executor)
        self.assertEqual(state["stages"]["export"]["status"], "succeeded")

        # Force the solve stage to re-run by changing its recorded input.
        response_path = os.path.join(self.root, "setup_response.json")
        with open(response_path, "r", encoding="utf-8") as fh:
            setup_response = json.load(fh)
        setup_response["rerun_marker"] = "changed"
        with open(response_path, "w", encoding="utf-8") as fh:
            json.dump(setup_response, fh)
        failing = mock.Mock()
        failing.execute.side_effect = RuntimeError("native failure")
        state = orch.run_stage(self.root, "solve", online=True, executor=failing)
        self.assertEqual(state["stages"]["solve"]["status"], "failed")
        self.assertEqual(state["stages"]["export"]["status"], "pending")
        self.assertEqual(state["stages"]["export"]["artifacts"], {})
        self.assertFalse(state["solver_run_performed"])

    def test_changed_setup_invalidates_downstream(self):
        self.prepare()
        path = os.path.join(self.root, "setup_manifest.json")
        with open(path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        manifest["setup_digest"] = "changed"
        self.write("setup_manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "重新 prepare"):
            orch.run_stage(self.root, "setup", online=True, executor=FakeExecutor(self.root))


if __name__ == "__main__":
    unittest.main(verbosity=2)
