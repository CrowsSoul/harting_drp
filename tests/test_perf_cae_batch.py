# -*- coding: utf-8 -*-
import copy
import json
import os
import tempfile
import unittest

from nxdrp.checkers.performance import cae_batch
from nxdrp.journals import build_perf_geometry as geometry_journal


class PerfCaeBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.batch = cae_batch.generate_batch(count=3, seed=7123)

    def test_lhs_generation_is_deterministic(self):
        again = cae_batch.generate_batch(count=3, seed=7123)
        first_cases = [{k: v for k, v in case.items() if k != "created_at"} for case in self.batch["cases"]]
        second_cases = [{k: v for k, v in case.items() if k != "created_at"} for case in again["cases"]]
        self.assertEqual(first_cases, second_cases)
        self.assertFalse(self.batch["solver_run_performed"])

    def test_perf01_is_steady_solid_joule_with_five_exact_outputs(self):
        case = next(item for item in self.batch["cases"] if item["check_item_id"] == "PERF-01")
        self.assertEqual(case["solver_setup"], {
            "analysis_type": "thermal_with_joule",
            "analysis_mode": "steady",
            "physics_domain": "solid",
            "joule_heating": True,
        })
        self.assertEqual(case["required_outputs"], {
            "maximum_temperature_c": "degC",
            "delta_t_c": "degC",
            "total_resistance_ohm": "ohm",
            "joule_power_w": "W",
            "voltage_drop_v": "V",
        })
        self.assertEqual(set(case["expected_values"]), set(case["required_outputs"]))
        self.assertIsNot(case["expected_values"], case["required_outputs"])
        self.assertEqual(case["boundary_conditions"]["electrical_outlet"]["voltage_v"], 0.0)
        self.assertEqual(case["boundary_conditions"]["electrical_inlet"]["current_a"], case["formula_inputs"]["current_a"])
        actions = cae_batch._action_templates()["PERF-01"]
        self.assertEqual(actions["analysis_type"], "thermal_with_joule")
        self.assertEqual(actions["physics_domain"], "solid")
        self.assertNotIn("Coupled Thermal-Flow", json.dumps(actions))

    def test_perf02_models_one_contact_and_scales_formula_explicitly(self):
        case = next(item for item in self.batch["cases"] if item["check_item_id"] == "PERF-02")
        geometry = case["geometry_request"]
        conditions = case["contact_conditions"]
        self.assertEqual(case["formula_inputs"]["contacts"], 1.0)
        self.assertEqual(conditions["modeled_contact_count"], 1)
        self.assertEqual(conditions["contact_count"], 1)
        self.assertGreater(conditions["rule_contact_count"], 1)
        self.assertEqual(geometry["normal_overlap_mm"], case["formula_inputs"]["overlap_mm"])
        self.assertEqual(geometry["insertion_stroke_mm"], 0.5 * geometry["length_mm"])
        self.assertNotEqual(geometry["insertion_stroke_mm"], geometry["normal_overlap_mm"])
        self.assertEqual(geometry["target_slope_deg"], conditions["lead_angle_deg"])
        factor = conditions["rule_contact_count"]
        for name in ("insertion_force_n", "withdrawal_force_n"):
            self.assertAlmostEqual(case["expected_rule_values"][name], case["expected_values"][name] * factor, places=10)
        self.assertEqual(
            case["expected_rule_values"]["maximum_normal_contact_force_n"],
            case["expected_values"]["maximum_normal_contact_force_n"],
        )
        self.assertEqual(case["formula_scaling"]["output_factors"]["maximum_normal_contact_force_n"], 1.0)
        self.assertEqual(case["solver_setup"]["solution_card"], "SOL 401")
        self.assertEqual(conditions["load_steps"], ["establish_contact", "insert", "withdraw"])
        self.assertEqual([step["action"] for step in case["load_steps"]], ["establish_contact", "insert", "withdraw"])
        self.assertAlmostEqual(
            case["load_steps"][0]["displacement_mm"] + case["load_steps"][1]["displacement_mm"],
            -geometry["insertion_stroke_mm"],
        )
        self.assertEqual(case["load_steps"][2]["displacement_mm"], geometry["insertion_stroke_mm"])
        self.assertEqual(case["constraints"]["driven_displacement"]["direction"], "-X")
        self.assertTrue(conditions["large_displacement"])

    def test_geometry_request_uses_axes_overlap_and_stroke_not_plate_gap(self):
        case = next(item for item in self.batch["cases"] if item["check_item_id"] == "PERF-02")
        request = cae_batch.build_geometry_request(case, "contact.prt")
        self.assertEqual(request["axis_convention"], {
            "length": "X", "width": "Y", "thickness_and_normal_overlap": "Z",
        })
        self.assertNotIn("plate_gap_mm", request)
        self.assertNotIn("interference_mm", request)
        self.assertEqual(request["target_slope_deg"], request["lead_angle_deg"])

    def test_geometry_request_rejects_invalid_dimensions_angle_and_stroke(self):
        original = next(item for item in self.batch["cases"] if item["check_item_id"] == "PERF-02")
        for field, value in (
            ("length_mm", 0), ("width_mm", -1), ("thickness_mm", float("nan")),
            ("normal_overlap_mm", 0), ("insertion_stroke_mm", -2),
            ("insertion_stroke_mm", 0.0001),
            ("lead_angle_deg", 0), ("lead_angle_deg", 90), ("lead_angle_deg", None),
        ):
            with self.subTest(field=field, value=value):
                case = copy.deepcopy(original)
                case["geometry_request"][field] = value
                case["contact_conditions"].pop(field, None)
                with self.assertRaises(ValueError):
                    cae_batch.build_geometry_request(case, "bad.prt")

    def test_target_starts_without_penetration_and_travel_matches_overlap(self):
        request = {
            "length_mm": 10.0,
            "width_mm": 2.0,
            "thickness_mm": 0.4,
            "normal_overlap_mm": 0.2,
            "insertion_stroke_mm": 5.0,
            "lead_angle_deg": 30.0,
        }
        definition = geometry_journal._target_definition(request)
        self.assertEqual(definition["x0"], request["length_mm"])
        self.assertGreater(definition["z0"], request["thickness_mm"])
        self.assertTrue(all(point[0] >= request["length_mm"] for point in definition["points_xz"]))
        self.assertAlmostEqual(
            definition["contact_travel_mm"] + definition["deflection_travel_mm"],
            request["insertion_stroke_mm"],
        )

    def test_journal_role_proposals_use_corrected_cylinder_and_sloped_target(self):
        def face(face_id, body_id, body_name, centroid, normal):
            return {
                "face_id": face_id, "body_id": body_id, "body_name": body_name,
                "centroid_mm": centroid, "normal": normal, "area_mm2": 1.0,
            }

        cylinder_records = {"CONDUCTOR": [
            face("F1", "B1", "CONDUCTOR", [0.0, 0.0, 0.0], [-1.0, 0.0, 0.0]),
            face("F2", "B1", "CONDUCTOR", [10.0, 0.0, 0.0], [1.0, 0.0, 0.0]),
            face("F3", "B1", "CONDUCTOR", [5.0, 1.0, 0.0], None),
        ]}
        roles = geometry_journal._proposed_roles("cylinder", {"length_mm": 10.0}, cylinder_records)
        self.assertEqual(roles["electrical_inlet"]["face_ids"], ["F1"])
        self.assertEqual(roles["electrical_outlet"]["face_ids"], ["F2"])
        self.assertEqual(roles["convection"]["face_ids"], ["F3"])

        contact_records = {
            "CONTACT_SPRING": [
                face("F11", "B11", "CONTACT_SPRING", [0.0, 1.0, 0.2], [-1.0, 0.0, 0.0]),
                face("F12", "B11", "CONTACT_SPRING", [10.0, 1.0, 0.2], [1.0, 0.0, 0.0]),
                face("F13", "B11", "CONTACT_SPRING", [5.0, 1.0, 0.4], [0.0, 0.0, 1.0]),
            ],
            "CONTACT_TARGET": [
                face("F21", "B21", "CONTACT_TARGET", [8.0, 1.0, 0.3], [0.5, 0.0, -0.8660254]),
                face("F22", "B21", "CONTACT_TARGET", [17.5, 1.0, 0.3], [1.0, 0.0, 0.0]),
            ],
        }
        request = {
            "length_mm": 10.0,
            "thickness_mm": 0.4,
            "normal_overlap_mm": 0.2,
            "insertion_stroke_mm": 5.0,
            "lead_angle_deg": 30.0,
        }
        roles = geometry_journal._proposed_roles("cantilever_contact_pair", request, contact_records)
        self.assertEqual(roles["fixed_root"]["face_ids"], ["F11"])
        self.assertEqual(roles["driven_face"]["face_ids"], ["F22"])
        self.assertEqual(roles["contact_source"]["face_ids"], ["F13"])
        self.assertEqual(roles["contact_target"]["face_ids"], ["F21"])

    def test_run_state_controls_exported_and_solved_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch_path = os.path.join(tmp, "batch.json")
            workspace = os.path.join(tmp, "workspace")
            cae_batch._json_write(batch_path, cae_batch.generate_batch(3, items=("PERF-01",)))
            index = cae_batch.materialize_batch(batch_path, workspace)
            entry = index["cases"][0]
            for name in ("source.prt", "case.fem", "case.sim", "solver_result.json"):
                with open(os.path.join(entry["directory"], name), "w", encoding="utf-8") as fh:
                    fh.write("{}")
            state_path = os.path.join(entry["directory"], "run_state.json")
            legacy = cae_batch.refresh_workspace_status(workspace)["cases"][0]
            self.assertFalse(legacy["solved"])
            self.assertEqual(legacy["status"], "simcenter_container_ready")
            cae_batch._json_write(state_path, {"stages": {
                "geometry": {"status": "done"}, "fem": {"status": "done"},
                "sim": {"status": "done"}, "export": {"status": "done"},
                "solve": {"status": "running"},
            }})
            refreshed = cae_batch.refresh_workspace_status(workspace)["cases"][0]
            self.assertTrue(refreshed["exported"])
            self.assertFalse(refreshed["solved"])
            self.assertEqual(refreshed["status"], "solver_exported")
            cae_batch._json_write(state_path, {"stages": {
                "geometry": {"status": "done"}, "export": {"status": "done"},
                "solve": {"status": "succeeded"},
            }})
            refreshed = cae_batch.refresh_workspace_status(workspace)["cases"][0]
            self.assertTrue(refreshed["solved"])
            self.assertEqual(refreshed["status"], "solver_exported")

    def test_certification_uses_item_specific_mesh_limits(self):
        records = []
        for item in ("PERF-01", "PERF-02"):
            case = next(value for value in self.batch["cases"] if value["check_item_id"] == item)
            records.append({
                "case_id": case["case_id"], "check_item_id": item,
                "license_mode": "commercial", "certification_eligible": True,
                "smoke": False, "outputs": case["expected_values"] and {
                    name: {"value": value, "unit": case["expected_units"][name]}
                    for name, value in case["expected_values"].items()
                },
                "quality": {
                    "mesh_sensitivity_relative_change_pct": 2.5,
                    "energy_balance_relative_error": 0.01,
                    "penetration_max_mm": 0.005,
                },
            })
        with tempfile.TemporaryDirectory() as tmp:
            batch_path = os.path.join(tmp, "batch.json")
            records_path = os.path.join(tmp, "records.json")
            cae_batch._json_write(batch_path, self.batch)
            cae_batch._json_write(records_path, {"accepted": records, "rejected": []})
            report = cae_batch.certification_report(batch_path, records_path, min_samples_per_item=1)
        self.assertTrue(any("PERF-01" in blocker and "2.50%" in blocker for blocker in report["blockers"]))
        self.assertFalse(any("PERF-02" in blocker and "网格敏感性" in blocker for blocker in report["blockers"]))
        checks = {item["check_item_id"]: item for item in report["checks"]}
        self.assertEqual(checks["PERF-01"]["max_mesh_sensitivity_pct"], 2.0)
        self.assertEqual(checks["PERF-02"]["max_mesh_sensitivity_pct"], 3.0)

        records[0]["quality"]["energy_balance_relative_error"] = 0.03
        records[1]["quality"]["penetration_max_mm"] = 0.02
        with tempfile.TemporaryDirectory() as tmp:
            batch_path = os.path.join(tmp, "batch.json")
            records_path = os.path.join(tmp, "records.json")
            cae_batch._json_write(batch_path, self.batch)
            cae_batch._json_write(records_path, {"accepted": records, "rejected": []})
            quality_report = cae_batch.certification_report(batch_path, records_path, min_samples_per_item=1)
        self.assertTrue(any("energy_balance_relative_error" in item for item in quality_report["blockers"]))
        self.assertTrue(any("penetration_max_mm" in item for item in quality_report["blockers"]))


if __name__ == "__main__":
    unittest.main()
