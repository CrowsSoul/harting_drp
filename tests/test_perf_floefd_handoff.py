# -*- coding: utf-8 -*-
"""Offline deterministic FloEFD handoff tests; no proprietary solver is used."""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from nxdrp.checkers.performance.cae_bindings import (  # noqa: E402
    binding_digest,
    create_binding_draft,
)
from nxdrp.checkers.performance.floefd_handoff import (  # noqa: E402
    FloEFDHandoffError,
    build_floefd_handoff,
    main,
)


def confirmed_fixture():
    case = {
        "case_id": "PERF01-HANDOFF-001",
        "solver_case_id": "PERF-01-ET-STEADY-001",
        "check_item_id": "PERF-01",
        "material": "Cu",
        "formula_inputs": {
            "current_a": 16.0,
            "ambient_temp_c": 25.0,
            "h_w_m2k": 15.0,
            "emissivity": 0.25,
        },
    }
    binding = create_binding_draft(case)
    binding["source_geometry"].update({
        "source_part": "C:/confirmed/terminal.prt",
        "model_digest": "confirmed-model-digest",
        "body_tags": [101],
        "status": "confirmed",
    })
    role_faces = {
        "electrical_inlet": ["F_IN"],
        "electrical_outlet": ["F_GROUND"],
        "convection": ["F_CONV_1", "F_CONV_2"],
        "radiation": ["F_RAD"],
    }
    for role, face_ids in role_faces.items():
        binding["face_roles"][role].update({
            "face_ids": face_ids,
            "body_ids": ["B_TERMINAL"],
            "status": "confirmed",
        })
    for query in binding["result_queries"].values():
        query["status"] = "confirmed"
    binding["status"] = "confirmed"
    binding["confirmation"] = {
        "reviewer": "offline-test-reviewer",
        "confirmed_at": "2026-11-01T00:00:00+00:00",
        "geometry_digest": "confirmed-model-digest",
    }
    binding["binding_digest"] = binding_digest(binding)
    return case, binding


class TestFloEFDHandoff(unittest.TestCase):
    def test_content_and_determinism(self):
        case, binding = confirmed_fixture()
        identity = {
            "model_id": "terminal-001",
            "content_digest": "confirmed-model-digest",
            "nx_version": "NX 2606.3002",
        }
        first = build_floefd_handoff(case, binding, identity)
        second = build_floefd_handoff(case, binding, identity)
        self.assertEqual(first, second)
        self.assertEqual(len(first["handoff_id"]), 64)
        self.assertEqual(first["status"], "ready_for_engineer")
        self.assertFalse(first["solver_run_performed"])
        self.assertFalse(first["automation_supported"])
        self.assertEqual(first["result_contract"], "contracts/schema/perf_solver_result.schema.json")
        self.assertEqual(first["binding_digest"], binding["binding_digest"])
        self.assertEqual(first["model_identity"]["model_id"], "terminal-001")
        self.assertEqual(first["source_geometry"]["body_tags"], [101])
        self.assertEqual(first["face_roles"]["electrical_inlet"]["face_ids"], ["F_IN"])

        self.assertEqual(first["electrical"]["current_a"], 16.0)
        self.assertEqual(first["electrical"]["ground_potential_v"], 0.0)
        self.assertEqual(first["electrical"]["ground_face_ids"], ["F_GROUND"])
        self.assertEqual(first["convection"]["heat_transfer_coefficient_w_m2k"], 15.0)
        self.assertEqual(first["radiation"]["emissivity"], 0.25)
        self.assertEqual(first["material"]["material"], "Cu")
        resistivity = first["temperature_dependent_resistivity"]
        self.assertTrue(resistivity["temperature_dependent"])
        self.assertGreater(resistivity["electrical_resistivity_ohm_m"], 0)
        self.assertGreater(resistivity["temperature_coefficient_1_k"], 0)
        self.assertIn("temperature_c", resistivity["expression"])

        self.assertEqual(len(first["mesh"]["local_refinement"]), 3)
        self.assertTrue(first["mesh"]["medium_and_fine_study_required"])
        self.assertEqual(len(first["goals"]), 5)
        self.assertEqual(len(first["probes"]), 3)
        output_names = [item["output_key"] for item in first["required_outputs"]]
        self.assertEqual(output_names, [
            "maximum_temperature_c",
            "delta_t_c",
            "total_resistance_ohm",
            "joule_power_w",
            "voltage_drop_v",
        ])
        self.assertTrue(all(item["native_key"] is None for item in first["required_outputs"]))
        self.assertEqual(first["quality_requirements"]["mesh_sensitivity_relative_change_pct_max"], 2.0)
        self.assertEqual(first["quality_requirements"]["energy_balance_relative_error_max"], 0.02)
        self.assertEqual(first["capability"]["status"], "unverified")
        self.assertFalse(first["capability"]["verified"])

    def test_schema_contains_all_emitted_top_level_keys(self):
        case, binding = confirmed_fixture()
        handoff = build_floefd_handoff(case, binding)
        with open(
            os.path.join(ROOT, "contracts", "schema", "perf_floefd_handoff.schema.json"),
            "r",
            encoding="utf-8",
        ) as fh:
            schema = json.load(fh)
        self.assertEqual(set(handoff), set(schema["properties"]))
        self.assertTrue(set(schema["required"]).issubset(handoff))

    def test_rejects_perf02(self):
        case, binding = confirmed_fixture()
        case["check_item_id"] = "PERF-02"
        with self.assertRaises(FloEFDHandoffError) as ctx:
            build_floefd_handoff(case, binding)
        self.assertEqual(ctx.exception.code, "unsupported_item")
        self.assertIn("SOL401", ctx.exception.action)

    def test_rejects_unconfirmed_binding(self):
        case, binding = confirmed_fixture()
        binding["status"] = "pending"
        binding["binding_digest"] = binding_digest(binding)
        with self.assertRaises(FloEFDHandoffError) as ctx:
            build_floefd_handoff(case, binding)
        self.assertEqual(ctx.exception.code, "binding_not_confirmed")
        self.assertEqual(ctx.exception.as_dict()["status"], "not_done")

    def test_rejects_tampered_digest(self):
        case, binding = confirmed_fixture()
        binding["load_values"]["current_a"] = 20.0
        with self.assertRaises(FloEFDHandoffError) as ctx:
            build_floefd_handoff(case, binding)
        self.assertEqual(ctx.exception.code, "binding_digest_mismatch")

    def test_rejects_unknown_release_without_fallback(self):
        case, binding = confirmed_fixture()
        with self.assertRaises(FloEFDHandoffError) as ctx:
            build_floefd_handoff(case, binding, release="NX 2606")
        self.assertEqual(ctx.exception.code, "capability_not_available")

    def test_cli_writes_handoff_without_running_a_solver(self):
        case, binding = confirmed_fixture()
        with tempfile.TemporaryDirectory() as root:
            case_path = os.path.join(root, "case.json")
            binding_path = os.path.join(root, "binding.json")
            out_path = os.path.join(root, "handoff.json")
            for path, payload in ((case_path, case), (binding_path, binding)):
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh)
            result = main(["--case", case_path, "--binding", binding_path, "--out", out_path])
            self.assertEqual(result, 0)
            with open(out_path, "r", encoding="utf-8") as fh:
                written = json.load(fh)
            self.assertEqual(written, build_floefd_handoff(case, binding))
            self.assertFalse(written["solver_run_performed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
