# -*- coding: utf-8 -*-
import hashlib
import json
import os
import tempfile
import unittest
from unittest import mock

from nxdrp.checkers.performance import cae_batch
from nxdrp.checkers.performance.cae_bindings import confirm_bindings, load_binding_templates
from nxdrp.checkers.performance.cae_orchestrator import build_setup_manifest


class PerfCaeIngestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.batch = cae_batch.generate_batch(3, seed=818, items=("PERF-01",))
        self.case = self.batch["cases"][0]
        self.batch_path = os.path.join(self.temp.name, "batch.json")
        cae_batch._json_write(self.batch_path, self.batch)

    def result(self, case=None, license_mode="commercial"):
        case = case or self.case
        return {
            "schema_version": "1.0.0",
            "case_id": case["case_id"],
            "check_item_id": case["check_item_id"],
            "solver": {"product": "NX Thermal", "version": "2606", "license_mode": license_mode},
            "model_identity": {
                "model_id": "standalone-model", "content_digest": "c" * 64, "input_digest": "d" * 64,
            },
            "convergence_status": "converged",
            "outputs": {
                name: {"value": value, "unit": case["expected_units"][name]}
                for name, value in case["expected_values"].items()
            },
            "quality": {"mesh_sensitivity_relative_change_pct": 1.0},
        }

    def ingest(self, payload, name="result.json", **kwargs):
        path = os.path.join(self.temp.name, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cae_batch._json_write(path, payload)
        return cae_batch.ingest_results(self.batch_path, path, **kwargs)

    def test_standalone_identity_is_accepted_with_warning_but_not_certification_eligible(self):
        records = self.ingest(self.result())
        self.assertEqual(records["rejected_count"], 0, records["rejected"])
        record = records["accepted"][0]
        self.assertEqual(record["solver"]["model_id"], "standalone-model")
        self.assertFalse(record["identity_verified"])
        self.assertFalse(record["certification_eligible"])
        self.assertTrue(record["warnings"])
        self.assertFalse(records["certification_eligible"])

    def test_every_required_output_is_mandatory(self):
        for name in self.case["expected_units"]:
            with self.subTest(output=name):
                payload = self.result()
                del payload["outputs"][name]
                records = self.ingest(payload, f"missing-{name}.json")
                self.assertEqual(records["accepted_count"], 0)
                self.assertIn(name, records["rejected"][0]["reason"])

    def test_wrong_units_nonfinite_values_and_unknown_case_are_rejected(self):
        wrong_unit = self.result()
        wrong_unit["outputs"]["voltage_drop_v"]["unit"] = "mV"
        records = self.ingest(wrong_unit, "wrong-unit.json")
        self.assertEqual(records["accepted_count"], 0)
        self.assertIn("单位", records["rejected"][0]["reason"])

        for value in (float("nan"), float("inf"), True, "1.0"):
            with self.subTest(value=value):
                payload = self.result()
                payload["outputs"]["delta_t_c"]["value"] = value
                records = self.ingest(payload, f"finite-{type(value).__name__}-{value}.json")
                self.assertEqual(records["accepted_count"], 0)

        unknown = self.result()
        unknown["case_id"] = "NOT-IN-BATCH"
        records = self.ingest(unknown, "unknown.json")
        self.assertEqual(records["accepted_count"], 0)
        self.assertIn("不在当前 batch", records["rejected"][0]["reason"])

    def test_smoke_and_evaluation_have_distinct_source_and_no_certification_eligibility(self):
        unverified = self.result(license_mode="unverified")
        self.assertEqual(self.ingest(unverified, "unverified.json")["accepted_count"], 0)
        smoke = self.ingest(unverified, "smoke.json", allow_unverified_for_smoke=True)
        self.assertEqual(smoke["accepted_count"], 1)
        self.assertEqual(smoke["accepted"][0]["source"], "cae_smoke")
        self.assertEqual(smoke["accepted"][0]["solver"]["source"], "cae_smoke")
        self.assertTrue(smoke["contains_smoke_results"])
        self.assertFalse(smoke["accepted"][0]["certification_eligible"])

        evaluation = self.ingest(self.result(license_mode="evaluation"), "evaluation.json")
        self.assertEqual(evaluation["accepted_count"], 1)
        self.assertEqual(evaluation["accepted"][0]["source"], "cae_smoke")
        self.assertFalse(evaluation["accepted"][0]["certification_eligible"])
        self.assertTrue(any("evaluation" in warning for warning in evaluation["accepted"][0]["warnings"]))

    def confirm_workspace(self):
        workspace = os.path.join(self.temp.name, "trusted-workspace")
        index = cae_batch.materialize_batch(self.batch_path, workspace)
        entry = index["cases"][0]
        with open(entry["bindings_path"], "r", encoding="utf-8") as fh:
            binding = json.load(fh)
        roles = load_binding_templates()["items"]["PERF-01"]["required_face_roles"]
        response = {
            "ok": True, "case_id": binding["case_id"], "model_id": binding["case_id"],
            "part_path": binding["source_geometry"]["source_part"], "part_digest": "e" * 64,
            "body_tags": [21], "body_roles": {"conductor": "B21"},
            "face_roles": {
                role: {"face_ids": [f"F{index + 1}"], "body_ids": ["B21"], "faces": []}
                for index, role in enumerate(roles)
            },
        }
        confirm_bindings(binding, "test-reviewer", response, "2026-11-01T00:00:00+00:00")
        cae_batch._json_write(entry["bindings_path"], binding)
        return workspace, binding

    def native_artifact(self, name="native-result.op2", content=b"native solver output"):
        path = os.path.join(self.temp.name, name)
        with open(path, "wb") as fh:
            fh.write(content)
        return path, hashlib.sha256(content).hexdigest()

    def trusted_result(self, binding):
        payload = self.result()
        payload["batch_id"] = self.batch["batch_id"]
        payload["binding_digest"] = binding["binding_digest"]
        payload["model_identity"] = {
            "model_id": binding["source_geometry"]["model_id"],
            "content_digest": binding["source_geometry"]["model_digest"],
            "input_digest": cae_batch._payload_digest(self.case),
        }
        native_path, native_digest = self.native_artifact()
        payload["run"] = {
            "native_result_path": native_path,
            "native_result_digest": native_digest,
        }
        payload["residual"] = 1.0e-8
        return payload

    def released_material(self):
        return mock.patch.object(
            cae_batch, "load_material_library", return_value={"status": "released"},
        )

    def test_trusted_workspace_verifies_model_and_binding_identities(self):
        workspace, binding = self.confirm_workspace()
        records = self.ingest(self.trusted_result(binding), "trusted.json", workspace=workspace)
        self.assertEqual(records["rejected_count"], 0, records["rejected"])
        self.assertTrue(records["accepted"][0]["identity_verified"])
        # The shipped material library is provisional, so it must not certify.
        self.assertFalse(records["accepted"][0]["certification_eligible"])
        self.assertTrue(any("材料库" in warning for warning in records["accepted"][0]["warnings"]))

        with self.released_material():
            eligible = self.ingest(
                self.trusted_result(binding), "trusted-released.json", workspace=workspace,
            )
        self.assertTrue(eligible["accepted"][0]["certification_eligible"])

        wrong_model = self.trusted_result(binding)
        wrong_model["model_identity"]["model_id"] = "payload-self-assertion"
        rejected = self.ingest(wrong_model, "wrong-model.json", workspace=workspace)
        self.assertEqual(rejected["accepted_count"], 0)
        self.assertIn("model_id", rejected["rejected"][0]["reason"])

        wrong_binding = self.trusted_result(binding)
        wrong_binding["binding_digest"] = "f" * 64
        rejected = self.ingest(wrong_binding, "wrong-binding.json", workspace=workspace)
        self.assertEqual(rejected["accepted_count"], 0)
        self.assertIn("binding_digest", rejected["rejected"][0]["reason"])

    def test_trusted_result_without_native_artifact_is_rejected(self):
        workspace, binding = self.confirm_workspace()
        payload = self.trusted_result(binding)
        del payload["run"]
        records = self.ingest(payload, "no-native.json", workspace=workspace)
        self.assertEqual(records["accepted_count"], 0)
        self.assertIn("原生", records["rejected"][0]["reason"])

    def test_trusted_result_from_foreign_batch_is_rejected(self):
        workspace, binding = self.confirm_workspace()
        payload = self.trusted_result(binding)
        payload["batch_id"] = "OTHER-BATCH"
        records = self.ingest(payload, "foreign-batch.json", workspace=workspace)
        self.assertEqual(records["accepted_count"], 0)
        self.assertIn("batch_id", records["rejected"][0]["reason"])

    def test_trusted_setup_manifest_can_validate_without_workspace(self):
        workspace, binding = self.confirm_workspace()
        manifest = build_setup_manifest(
            os.path.join(workspace, binding["case_id"]),
            "NX 2606.3002",
            batch_id=self.batch["batch_id"],
        )
        payload = self.trusted_result(binding)
        payload["setup_digest"] = manifest["setup_digest"]
        records = self.ingest(payload, "setup-manifest.json", setup_manifest=manifest)
        self.assertEqual(records["rejected_count"], 0, records["rejected"])
        self.assertFalse(records["accepted"][0]["certification_eligible"])

        released_payload = self.trusted_result(binding)
        released_payload["setup_digest"] = manifest["setup_digest"]
        with self.released_material():
            eligible = self.ingest(
                released_payload, "setup-released.json", setup_manifest=manifest,
            )
        self.assertTrue(eligible["accepted"][0]["certification_eligible"])

        payload["setup_digest"] = "a" * 64
        rejected = self.ingest(payload, "setup-mismatch.json", setup_manifest=manifest)
        self.assertEqual(rejected["accepted_count"], 0)

    def test_tampered_embedded_setup_manifest_digest_is_rejected(self):
        workspace, binding = self.confirm_workspace()
        manifest = build_setup_manifest(
            os.path.join(workspace, binding["case_id"]),
            "NX 2606.3002",
            batch_id=self.batch["batch_id"],
        )
        manifest["mesh"] = {"element_size_mm": 999.0}
        payload = self.trusted_result(binding)
        payload["setup_digest"] = manifest["setup_digest"]
        records = self.ingest(payload, "tampered-manifest.json", setup_manifest=manifest)
        self.assertEqual(records["accepted_count"], 0)
        self.assertIn("setup_digest", records["rejected"][0]["reason"])

    def test_certification_report_rejects_ghost_samples(self):
        records = self.ingest(self.result(license_mode="evaluation"), "ghost-base.json")
        records["accepted"].append(dict(records["accepted"][0], case_id="GHOST-CASE"))
        records["accepted_count"] = len(records["accepted"])
        records_path = os.path.join(self.temp.name, "ghost-records.json")
        cae_batch._json_write(records_path, records)
        report = cae_batch.certification_report(
            self.batch_path, records_path, min_samples_per_item=1,
        )
        self.assertEqual(report["status"], "not_ready")
        self.assertTrue(any("不属于当前 batch" in blocker for blocker in report["blockers"]))

    def test_duplicate_case_results_are_not_silently_overwritten(self):
        results = os.path.join(self.temp.name, "duplicates")
        os.makedirs(results)
        cae_batch._json_write(os.path.join(results, "a.json"), self.result())
        cae_batch._json_write(os.path.join(results, "b.json"), self.result())
        records = cae_batch.ingest_results(self.batch_path, results)
        self.assertEqual(records["accepted_count"], 1)
        self.assertEqual(records["rejected_count"], 1)
        self.assertIn("重复 case_id", records["rejected"][0]["reason"])

    def test_smoke_record_blocks_certification_even_with_other_checks_present(self):
        records = self.ingest(self.result(license_mode="evaluation"), "cert-smoke.json")
        records_path = os.path.join(self.temp.name, "records.json")
        cae_batch._json_write(records_path, records)
        report = cae_batch.certification_report(self.batch_path, records_path, min_samples_per_item=1)
        self.assertEqual(report["status"], "not_ready")
        self.assertTrue(any("smoke/evaluation" in blocker for blocker in report["blockers"]))
        self.assertFalse(report["requirements"]["evaluation_and_smoke_eligible"])


if __name__ == "__main__":
    unittest.main()
