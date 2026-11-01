# -*- coding: utf-8 -*-
"""PERF 求解证据的身份、单位、授权和 smoke 门禁。"""

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nxdrp.checkers.performance.solver_evidence import (
    SolverEvidenceError,
    load_solver_evidence,
)


OUTPUTS = {
    "maximum_temperature_c": {"value": 80.0, "unit": "degC"},
    "delta_t_c": {"value": 55.0, "unit": "degC"},
    "total_resistance_ohm": {"value": 0.001, "unit": "ohm"},
    "joule_power_w": {"value": 0.256, "unit": "W"},
    "voltage_drop_v": {"value": 0.016, "unit": "V"},
}


def result_payload():
    return {
        "schema_version": "1.0.0",
        "batch_id": "B1",
        "case_id": "C1",
        "check_item_id": "PERF-01",
        "setup_digest": "s" * 64,
        "binding_digest": "b" * 64,
        "capability_id": "NX2606-PERF01",
        "solver": {"product": "Simcenter 3D", "version": "2606", "license_mode": "commercial"},
        "model_identity": {"model_id": "M1", "content_digest": "model-digest", "input_digest": "input"},
        "run": {"native_result_path": "result.op2", "native_result_digest": "n" * 64},
        "convergence_status": "converged",
        "residual": 1e-8,
        "outputs": copy.deepcopy(OUTPUTS),
        "quality": {},
    }


class SolverEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = os.path.join(self.temp.name, "result.json")

    def write(self, payload):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def test_valid_identity_and_required_outputs(self):
        self.write(result_payload())
        evidence = load_solver_evidence(
            self.path,
            expected_item="PERF-01",
            expected_case_id="C1",
            expected_batch_id="B1",
            expected_model_id="M1",
            expected_digest="model-digest",
            expected_setup_digest="s" * 64,
            expected_binding_digest="b" * 64,
            expected_capability_id="NX2606-PERF01",
            expected_native_result_digest="n" * 64,
            required_outputs={name: value["unit"] for name, value in OUTPUTS.items()},
            require_authorized=True,
        )
        self.assertTrue(evidence.certification_eligible)
        self.assertEqual(evidence.value("voltage_drop_v", "V"), 0.016)

    def test_every_trusted_identity_is_checked(self):
        cases = (
            ("expected_case_id", "OTHER"),
            ("expected_batch_id", "OTHER"),
            ("expected_model_id", "OTHER"),
            ("expected_digest", "OTHER"),
            ("expected_input_digest", "OTHER"),
            ("expected_setup_digest", "x" * 64),
            ("expected_binding_digest", "x" * 64),
            ("expected_capability_id", "OTHER"),
            ("expected_native_result_digest", "x" * 64),
        )
        for key, value in cases:
            with self.subTest(key=key):
                self.write(result_payload())
                with self.assertRaises(SolverEvidenceError):
                    load_solver_evidence(self.path, **{key: value})

    def test_missing_output_and_wrong_unit_fail(self):
        payload = result_payload()
        del payload["outputs"]["voltage_drop_v"]
        self.write(payload)
        with self.assertRaisesRegex(SolverEvidenceError, "voltage_drop_v"):
            load_solver_evidence(self.path, required_outputs={"voltage_drop_v": "V"})
        payload = result_payload()
        payload["outputs"]["delta_t_c"]["unit"] = "K"
        self.write(payload)
        with self.assertRaises(SolverEvidenceError):
            load_solver_evidence(self.path, required_outputs={"delta_t_c": "degC"})

    def test_non_finite_residual_and_output_fail(self):
        payload = result_payload()
        payload["residual"] = float("nan")
        self.write(payload)
        with self.assertRaises(SolverEvidenceError):
            load_solver_evidence(self.path)
        payload = result_payload()
        payload["outputs"]["joule_power_w"]["value"] = float("inf")
        self.write(payload)
        with self.assertRaises(SolverEvidenceError):
            load_solver_evidence(self.path)

    def test_native_evidence_requires_artifact_residual_and_matching_digest(self):
        payload = result_payload()
        with self.assertRaises(SolverEvidenceError):
            self.write(payload)
            load_solver_evidence(self.path, require_native_evidence=True)
        native = os.path.join(self.temp.name, "native.op2")
        with open(native, "wb") as fh:
            fh.write(b"native solver result")
        digest = hashlib.sha256(b"native solver result").hexdigest()
        payload["run"] = {"native_result_path": native, "native_result_digest": digest}
        self.write(payload)
        evidence = load_solver_evidence(self.path, require_native_evidence=True)
        self.assertEqual(evidence.native_result_digest, digest)
        with open(native, "wb") as fh:
            fh.write(b"changed")
        with self.assertRaises(SolverEvidenceError):
            load_solver_evidence(self.path, require_native_evidence=True)

    def test_evaluation_and_smoke_are_not_production_evidence(self):
        payload = result_payload()
        payload["solver"]["license_mode"] = "evaluation"
        self.write(payload)
        evidence = load_solver_evidence(self.path)
        self.assertFalse(evidence.certification_eligible)
        with self.assertRaises(SolverEvidenceError):
            load_solver_evidence(self.path, require_authorized=True)

        payload["solver"]["license_mode"] = "unverified"
        self.write(payload)
        evidence = load_solver_evidence(self.path)
        self.assertEqual(evidence.evidence_source, "cae_smoke")
        self.assertFalse(evidence.certification_eligible)

    def test_rapid_same_path_rewrite_never_uses_stale_evidence(self):
        payload = result_payload()
        self.write(payload)
        first = load_solver_evidence(self.path)
        self.assertEqual(first.license_mode, "commercial")
        payload["solver"]["license_mode"] = "unverified"  # same length as commercial
        self.write(payload)
        second = load_solver_evidence(self.path)
        self.assertEqual(second.license_mode, "unverified")
        self.assertEqual(second.evidence_source, "cae_smoke")

    def test_fake_product_and_invalid_source_fail(self):
        payload = result_payload()
        payload["solver"]["product"] = "Python formula only"
        self.write(payload)
        with self.assertRaises(SolverEvidenceError):
            load_solver_evidence(self.path)
        payload = result_payload()
        payload["evidence_source"] = "trusted_by_me"
        self.write(payload)
        with self.assertRaises(SolverEvidenceError):
            load_solver_evidence(self.path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
