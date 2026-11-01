# -*- coding: utf-8 -*-
"""Pure offline tests for the fail-closed Simcenter journal helpers."""

import copy
import os
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from nxdrp.journals import create_simcenter_case as create
from nxdrp.journals import export_simcenter_results as export
from nxdrp.journals import setup_simcenter_case as setup
from nxdrp.journals import solve_simcenter_case as solve


UNITS = {
    "maximum_temperature_c": "C",
    "delta_t_c": "C",
    "total_resistance_ohm": "ohm",
    "joule_power_w": "W",
    "voltage_drop_v": "V",
    "insertion_force_n": "N",
    "withdrawal_force_n": "N",
    "maximum_normal_contact_force_n": "N",
    "maximum_penetration_mm": "mm",
    "maximum_equivalent_stress_mpa": "MPa",
}


def fake_nxopen():
    return types.SimpleNamespace(
        Session=types.SimpleNamespace(GetSession=lambda: types.SimpleNamespace())
    )


class SimcenterJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = self.temp.name

    def tearDown(self):
        self.temp.cleanup()

    def manifest(self, item="PERF-01"):
        case = {"case_id": item + "-CASE", "check_item_id": item}
        if item == "PERF-02":
            case["load_steps"] = [
                {"step": 1, "action": "establish_contact"},
                {"step": 2, "action": "insert"},
                {"step": 3, "action": "withdraw"},
            ]
        setup_payload = {
            "case_id": case["case_id"],
            "check_item_id": item,
            "out_dir": self.root,
        }
        material = {"material": "verified-material"}
        if item == "PERF-01":
            material.update({
                "density_kg_m3": 8900.0,
                "thermal_conductivity_w_mk": 100.0,
                "specific_heat_j_kgk": 400.0,
                "electrical_resistivity_ohm_m": 1.0e-8,
                "temperature_coefficient_1_k": 0.003,
                "emissivity": 0.2,
            })
            loads = {
                "current_a": 16.0,
                "outlet_voltage_v": 0.0,
                "ambient_temperature_c": 25.0,
                "convection_h_w_m2k": 15.0,
                "radiation_emissivity": 0.2,
            }
            roles = ("electrical_inlet", "electrical_outlet", "convection", "radiation")
            contacts = []
        else:
            material.update({
                "density_kg_m3": 8900.0,
                "elastic_modulus_gpa": 120.0,
                "poisson_ratio": 0.3,
                "yield_strength_mpa": 400.0,
            })
            loads = {"normal_overlap_mm": 0.2, "insertion_stroke_mm": 0.5}
            roles = ("fixed_root", "driven_face", "contact_source", "contact_target")
            contacts = [{
                "source_face_ids": ["source"],
                "target_face_ids": ["target"],
                "method": "penalty",
                "friction_coefficient": 0.2,
                "penalty_stiffness": 1000.0,
                "search_distance_mm": 0.1,
                "normal_overlap_mm": 0.2,
                "insertion_stroke_mm": 0.5,
                "large_displacement": True,
                "status": "confirmed",
            }]
        queries = {}
        for name in create.REQUIRED_RESULT_KEYS[item]:
            query = {"status": "confirmed", "native_key": "native." + name}
            if name in UNITS:
                query["unit"] = UNITS[name]
            queries[name] = query
        binding = {
            "case_id": case["case_id"],
            "check_item_id": item,
            "status": "ready_for_simcenter",
            "source_geometry": {
                "source_part": os.path.join(self.root, "source.prt"),
                "model_digest": "model-content-digest",
                "body_tags": [101],
                "status": "confirmed",
            },
            "material": material,
            "load_values": loads,
            "face_roles": {
                role: {"status": "confirmed", "face_ids": [role + "-face"], "body_ids": ["body"]}
                for role in roles
            },
            "contact_pairs": contacts,
            "result_queries": queries,
        }
        capability = {
            "check_item_id": item,
            "verified": True,
            "capabilities": {create.SUPPORTED_CAPABILITY[item]: True},
            "solver": "verified-native-solver",
            "analysis_type": "verified-analysis",
            "solution_type": "verified-solution-type",
            "solution_title": "verified-solution-title",
            "fem_template": "verified.fem",
            "sim_template": "verified.sim",
            "presentation": "verified-presentation",
        }
        for payload, field in (
            (case, "case_digest"),
            (setup_payload, "setup_digest"),
            (binding, "binding_digest"),
            (capability, "capability_digest"),
        ):
            payload[field] = create.payload_digest(payload, field)
        return {
            "case": case,
            "setup": setup_payload,
            "binding": binding,
            "capability": capability,
        }

    def identity(self, manifest):
        return {
            "case_id": manifest["case"]["case_id"],
            "check_item_id": manifest["case"]["check_item_id"],
            "case_digest": manifest["case"]["case_digest"],
            "setup_digest": manifest["setup"]["setup_digest"],
            "binding_digest": manifest["binding"]["binding_digest"],
            "capability_digest": create.payload_digest(
                manifest["capability"], "capability_digest"
            ),
        }

    def container_response(self, manifest):
        fem = os.path.join(self.root, "case.fem")
        sim = os.path.join(self.root, "case.sim")
        for path, content in ((fem, b"fem"), (sim, b"sim")):
            with open(path, "wb") as handle:
                handle.write(content)
        return {
            "ok": True,
            "state": "container_created",
            **self.identity(manifest),
            "fem_path": fem,
            "fem_sha256": create.file_digest(fem),
            "sim_path": sim,
            "sim_sha256": create.file_digest(sim),
        }

    def committed_builders(self, item="PERF-01"):
        names = setup.PERF01_BUILDERS if item == "PERF-01" else setup.PERF02_BUILDERS
        registry = {}
        for name in names:
            def commit(context, payload, builder_name=name):
                result = {"committed": True, "native_handle": builder_name + "-handle"}
                if builder_name.endswith("output_requests"):
                    result["output_requests_set"] = True
                return result
            registry[name] = commit
        return registry

    def setup_response(self, manifest):
        request = {
            "setup_manifest": manifest,
            "container_response": self.container_response(manifest),
            "online_execution": True,
        }
        response = setup.run(
            request,
            nxopen=fake_nxopen(),
            builder_registry=self.committed_builders(manifest["case"]["check_item_id"]),
        )
        self.assertTrue(response["ok"], response)
        return response

    def native_files(self):
        paths = {}
        for name in ("native_deck", "native_result", "native_log"):
            path = os.path.join(self.root, name + ".native")
            with open(path, "wb") as handle:
                handle.write((name + " bytes").encode("ascii"))
            paths[name] = path
        return paths

    def run_metadata(self, manifest, paths):
        model_identity = {
            "model_id": "native-model",
            "content_digest": "model-content-digest",
            "input_digest": "native-input-digest",
        }
        return {
            "run_id": "native-run-001",
            "native_api": "verified.NXOpen.NativeSolve",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:01:00Z",
            "input_digest": "native-input-digest",
            "solution_title": manifest["capability"]["solution_title"],
            "solver": {
                "product": manifest["capability"]["solver"],
                "version": "2606",
                "license_mode": "authorized",
            },
            "model_identity": model_identity,
            "case_file": paths["native_deck"],
            "result_file": paths["native_result"],
            **self.identity(manifest),
        }

    def solved_response(self, manifest, steps=None):
        paths = self.native_files()
        metadata = self.run_metadata(manifest, paths)
        if steps is None:
            steps = (
                [{"step": 1, "status": "converged"}]
                if manifest["case"]["check_item_id"] == "PERF-01"
                else [
                    {"step": 1, "status": "converged"},
                    {"step": 2, "status": "converged"},
                    {"step": 3, "status": "converged"},
                ]
            )
        native_result = {
            "completed": True,
            "convergence_status": "converged",
            "native_deck_path": paths["native_deck"],
            "native_result_path": paths["native_result"],
            "native_log_path": paths["native_log"],
            "run_metadata": metadata,
            "step_statuses": steps,
        }
        setup_response = self.setup_response(manifest)
        response = solve.run(
            {
                "setup_manifest": manifest,
                "setup_response": setup_response,
                "online_execution": True,
            },
            nxopen=fake_nxopen(),
            solver_registry={"simcenter_solve": lambda context, payload: native_result},
        )
        self.assertTrue(response["ok"], response)
        return response

    def extraction(self, manifest, solved):
        item = manifest["case"]["check_item_id"]
        values = {}
        for index, name in enumerate(create.NUMERIC_OUTPUTS[item], 1):
            values["native." + name] = {
                "value": float(index),
                "unit": manifest["binding"]["result_queries"][name]["unit"],
            }
        values["native.convergence_status"] = "converged"
        values["native.residual"] = 1.0e-6
        quality = (
            {"mesh_sensitivity_relative_change_pct": 1.0, "energy_balance_relative_error": 0.01}
            if item == "PERF-01"
            else {"mesh_sensitivity_relative_change_pct": 1.0, "penetration_max_mm": 0.001}
        )
        return {
            "native_api": "verified.NXOpen.NativeResultExtraction",
            "run_metadata": solved["run_metadata"],
            "model_identity": solved["run_metadata"]["model_identity"],
            "native_result_path": solved["native_result"]["path"],
            "native_result_sha256": solved["native_result"]["sha256"],
            "step_statuses": solved["step_statuses"],
            "values": values,
            "quality": quality,
        }

    def test_unverified_capability_fails_before_nx(self):
        manifest = self.manifest()
        manifest["capability"]["verified"] = False
        manifest["capability"]["capability_digest"] = create.payload_digest(
            manifest["capability"], "capability_digest"
        )
        response = create.run({"setup_manifest": manifest, "online_execution": False})
        self.assertFalse(response["ok"])
        self.assertEqual(response["state"], "not_done")
        self.assertEqual(response["error_code"], "CAPABILITY_UNVERIFIED")

    def test_unsupported_capability_fails_closed(self):
        manifest = self.manifest()
        manifest["capability"]["capabilities"]["thermal_with_joule"] = False
        manifest["capability"]["capability_digest"] = create.payload_digest(
            manifest["capability"], "capability_digest"
        )
        response = create.run({"setup_manifest": manifest})
        self.assertEqual(response["error_code"], "CAPABILITY_UNVERIFIED")

    def test_digest_tampering_and_online_gates(self):
        manifest = self.manifest()
        manifest["binding"]["load_values"]["current_a"] = 99.0
        response = create.run({"setup_manifest": manifest})
        self.assertEqual(response["error_code"], "DIGEST_MISMATCH")

        manifest = self.manifest()
        response = create.run({"setup_manifest": manifest, "online_execution": False})
        self.assertEqual(response["error_code"], "ONLINE_EXECUTION_REQUIRED")
        response = solve.run({
            "setup_manifest": manifest,
            "setup_response": {
                "ok": True,
                "state": "solver_ready",
                "output_requests_set": True,
                "builders": {"material": {"committed": True}},
                **self.identity(manifest),
            },
            "online_execution": False,
        })
        self.assertEqual(response["error_code"], "ONLINE_EXECUTION_REQUIRED")

    def test_orchestrator_setup_envelope_and_digest_aliases(self):
        nested = self.manifest()
        case = copy.deepcopy(nested["case"])
        case.pop("case_digest")
        capability = copy.deepcopy(nested["capability"])
        capability.pop("capabilities")
        capability.pop("capability_digest")
        capability.update({
            "status": "verified",
            "mode": "thermal_with_joule",
            "supported_modes": ["thermal_with_joule"],
            "solver_name": capability.pop("solver"),
            "analysis_name": capability.pop("analysis_type"),
            "solution_name": capability.pop("solution_title"),
            "template_names": {
                "fem": capability.pop("fem_template"),
                "sim": capability.pop("sim_template"),
            },
            "native_result_mapping": {
                name: "native." + name for name in create.REQUIRED_RESULT_KEYS["PERF-01"]
            },
        })
        manifest = copy.deepcopy(nested["setup"])
        manifest.pop("setup_digest")
        manifest.update({
            "schema_version": "1.0.0",
            "setup_id": "verified-setup",
            "status": "ready",
            "solver_run_performed": False,
            "case": case,
            "model_identity": {
                "model_id": "native-model",
                "content_digest": "model-content-digest",
                "input_digest": create.payload_digest(case),
            },
            "binding": {
                "path": "",
                "digest": nested["binding"]["binding_digest"],
                "payload": nested["binding"],
            },
            "capability": capability,
            "required_output_units": {
                name: UNITS[name] for name in create.NUMERIC_OUTPUTS["PERF-01"]
            },
            "result_mapping": capability["native_result_mapping"],
            "artifacts": {"working_directory": self.root},
        })
        manifest["setup_digest"] = create.payload_digest(manifest, "setup_digest")
        response = create.run({"setup_manifest": manifest, "online_execution": False})
        self.assertEqual(response["error_code"], "ONLINE_EXECUTION_REQUIRED")

    def test_source_part_digest_is_verified_before_container_creation(self):
        manifest = self.manifest()
        source = manifest["binding"]["source_geometry"]["source_part"]
        with open(source, "wb") as handle:
            handle.write(b"confirmed source bytes")
        digest = create.file_digest(source)
        manifest["binding"]["source_geometry"]["model_digest"] = digest
        manifest["binding"]["binding_digest"] = create.payload_digest(
            manifest["binding"], "binding_digest"
        )
        response = create.run(
            {"setup_manifest": manifest, "online_execution": True},
            nxopen=fake_nxopen(),
        )
        self.assertNotEqual(response.get("error_code"), "DIGEST_MISMATCH")

        with open(source, "wb") as handle:
            handle.write(b"tampered source bytes")
        response = create.run(
            {"setup_manifest": manifest, "online_execution": True},
            nxopen=fake_nxopen(),
        )
        self.assertEqual(response.get("error_code"), "DIGEST_MISMATCH")

    def test_setup_requires_confirmed_binding_and_verified_builders(self):
        manifest = self.manifest()
        manifest["binding"]["status"] = "pending"
        manifest["binding"]["binding_digest"] = create.payload_digest(
            manifest["binding"], "binding_digest"
        )
        response = setup.run({"setup_manifest": manifest})
        self.assertEqual(response["error_code"], "BINDING_NOT_CONFIRMED")

        manifest = self.manifest()
        response = setup.run(
            {
                "setup_manifest": manifest,
                "container_response": self.container_response(manifest),
                "online_execution": True,
            },
            nxopen=fake_nxopen(),
        )
        self.assertEqual(response["error_code"], "NX_API_UNSUPPORTED")
        self.assertNotEqual(response.get("state"), "solver_ready")

    def test_setup_does_not_claim_ready_without_output_requests(self):
        manifest = self.manifest()
        registry = self.committed_builders()
        registry["perf01_output_requests"] = lambda context, payload: {"committed": True}
        response = setup.run(
            {
                "setup_manifest": manifest,
                "container_response": self.container_response(manifest),
                "online_execution": True,
            },
            nxopen=fake_nxopen(),
            builder_registry=registry,
        )
        self.assertEqual(response["error_code"], "OUTPUT_REQUESTS_NOT_SET")
        self.assertEqual(response["state"], "not_done")

    def test_both_setup_branches_commit_with_synthetic_builders(self):
        for item in ("PERF-01", "PERF-02"):
            with self.subTest(item=item):
                manifest = self.manifest(item)
                response = self.setup_response(manifest)
                self.assertEqual(response["state"], "solver_ready")
                expected = setup.PERF01_BUILDERS if item == "PERF-01" else setup.PERF02_BUILDERS
                self.assertEqual(set(response["builders"]), set(expected))

    def test_perf02_solve_requires_three_converged_steps(self):
        manifest = self.manifest("PERF-02")
        with self.assertRaises(AssertionError) as caught:
            self.solved_response(
                manifest,
                steps=[
                    {"step": 1, "status": "converged"},
                    {"step": 2, "status": "converged"},
                ],
            )
        self.assertIn("SOLVE_NOT_CONVERGED", str(caught.exception))

    def test_native_export_requires_all_values_and_rejects_unknown_keys(self):
        manifest = self.manifest()
        solved = self.solved_response(manifest)
        extraction = self.extraction(manifest, solved)
        incomplete = copy.deepcopy(extraction)
        del incomplete["values"]["native.voltage_drop_v"]
        response = export.run({
            "setup_manifest": manifest,
            "solved_response": solved,
            "native_extraction": incomplete,
            "out_path": os.path.join(self.root, "incomplete.json"),
        })
        self.assertEqual(response["error_code"], "OUTPUT_INCOMPLETE")

        unknown = copy.deepcopy(extraction)
        unknown["values"]["native.unmapped"] = 1.0
        response = export.run({
            "setup_manifest": manifest,
            "solved_response": solved,
            "native_extraction": unknown,
            "out_path": os.path.join(self.root, "unknown.json"),
        })
        self.assertEqual(response["error_code"], "UNKNOWN_RESULT_KEY")

    def test_native_export_succeeds_for_all_perf01_values(self):
        manifest = self.manifest()
        solved = self.solved_response(manifest)
        out_path = os.path.join(self.root, "solver-result.json")
        response = export.run({
            "setup_manifest": manifest,
            "solved_response": solved,
            "native_extraction": self.extraction(manifest, solved),
            "out_path": out_path,
        })
        self.assertTrue(response["ok"], response)
        self.assertEqual(set(response["output_keys"]), set(create.NUMERIC_OUTPUTS["PERF-01"]))
        self.assertTrue(os.path.isfile(out_path))
        self.assertEqual(response["result_sha256"], create.file_digest(out_path))

    def test_native_export_succeeds_for_all_perf02_values(self):
        manifest = self.manifest("PERF-02")
        solved = self.solved_response(manifest)
        out_path = os.path.join(self.root, "structural-solver-result.json")
        response = export.run({
            "setup_manifest": manifest,
            "solved_response": solved,
            "native_extraction": self.extraction(manifest, solved),
            "out_path": out_path,
        })
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["state"], "exported")
        self.assertEqual(set(response["output_keys"]), set(create.NUMERIC_OUTPUTS["PERF-02"]))
        self.assertEqual(len(solved["step_statuses"]), 3)

    def test_journal_sources_have_no_legacy_protocol_or_formula_fallback(self):
        for module in (create, setup, solve, export):
            with open(module.__file__, "r", encoding="utf-8") as handle:
                source = handle.read()
            if module is create:
                self.assertIn("NXDRP_NX_REQUEST", source)
                self.assertIn("NXDRP_NX_RESPONSE", source)
            else:
                self.assertIn("journal_main(run)", source)
            self.assertNotIn("NXDRP_CAE_REQUEST", source)
            self.assertNotIn("NXDRP_CAE_RESPONSE", source)
            self.assertNotIn("Nonlinear Statics", source)
            self.assertNotIn("Coupled Thermal-Flow", source)
            self.assertNotIn("predict_raw", source)
            self.assertNotIn("predict_insertion", source)
            self.assertNotIn("nxdrp.checkers.performance", source)


if __name__ == "__main__":
    unittest.main()
