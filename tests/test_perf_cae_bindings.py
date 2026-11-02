# -*- coding: utf-8 -*-
import copy
import os
import tempfile
import unittest

from nxdrp.checkers.performance.cae_batch import generate_batch
from nxdrp.checkers.performance.cae_bindings import (
    apply_geometry_response,
    binding_digest,
    confirm_bindings,
    create_binding_draft,
    load_binding_templates,
    validate_bindings,
)


class PerfCaeBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def draft(self, item="PERF-02"):
        case = generate_batch(3, seed=99, items=(item,))["cases"][0]
        binding = create_binding_draft(case)
        part = os.path.join(self.temp.name, f"{item}.prt")
        binding["source_geometry"]["source_part"] = part
        binding["binding_digest"] = binding_digest(binding)
        return binding, part

    def response(self, binding, part, digest="a" * 64):
        item = binding["check_item_id"]
        roles = load_binding_templates()["items"][item]["required_face_roles"]
        tags = [11, 12] if item == "PERF-02" else [11]
        face_roles = {}
        for index, role in enumerate(roles, 1):
            body_id = "B12" if role == "contact_target" else "B11"
            face_roles[role] = {
                "face_ids": [f"F{100 + index}"],
                "body_ids": [body_id],
                "faces": [{
                    "face_id": f"F{100 + index}", "tag": 100 + index,
                    "body_id": body_id, "area_mm2": 1.25,
                    "centroid_mm": [0.0, 0.0, 0.0], "normal": [1.0, 0.0, 0.0],
                }],
            }
        return {
            "ok": True, "case_id": binding["case_id"], "model_id": binding["case_id"],
            "part_path": part, "part_digest": digest, "body_tags": tags,
            "body_roles": {"contact_spring": "B11"} if item == "PERF-02" else {"conductor": "B11"},
            "face_roles": face_roles,
        }

    def test_geometry_response_only_proposes_tags(self):
        binding, part = self.draft()
        apply_geometry_response(binding, self.response(binding, part))
        self.assertEqual(binding["status"], "proposed")
        self.assertEqual(binding["source_geometry"]["status"], "proposed")
        self.assertTrue(all(role["status"] == "proposed" for role in binding["face_roles"].values()))
        self.assertTrue(all(query["status"] == "pending" for query in binding["result_queries"].values()))
        self.assertEqual(binding["contact_pairs"][0]["status"], "proposed")
        self.assertFalse(validate_bindings(binding)["valid"])
        self.assertEqual(binding["binding_digest"], binding_digest(binding))

    def test_geometry_response_requires_matching_case_source_and_current_digest(self):
        binding, part = self.draft()
        response = self.response(binding, part)
        for field, value in (("case_id", "OTHER"), ("part_path", os.path.join(self.temp.name, "other.prt"))):
            with self.subTest(field=field):
                changed = copy.deepcopy(response)
                changed[field] = value
                with self.assertRaises(ValueError):
                    apply_geometry_response(binding, changed)
        binding["load_values"]["insertion_stroke_mm"] += 1.0
        with self.assertRaises(ValueError):
            apply_geometry_response(binding, response)

    def test_confirm_requires_reviewer_and_validates_all_setup_data(self):
        binding, part = self.draft()
        with self.assertRaises(ValueError):
            confirm_bindings(binding, "", self.response(binding, part))
        confirm_bindings(binding, "reviewer@example.com", self.response(binding, part), "2026-11-01T00:00:00+00:00")
        validation = validate_bindings(binding, strict=True)
        self.assertTrue(validation["valid"], validation["errors"])
        self.assertEqual(binding["confirmation"]["reviewer"], "reviewer@example.com")
        self.assertEqual(binding["confirmation"]["geometry_digest"], "a" * 64)
        self.assertTrue(all(query["status"] == "confirmed" for query in binding["result_queries"].values()))
        self.assertEqual(binding["binding_digest"], binding_digest(binding))

    def test_invalid_material_override_is_rejected_even_with_valid_digest(self):
        binding, part = self.draft("PERF-01")
        confirm_bindings(binding, "reviewer", self.response(binding, part))
        binding["material"]["electrical_resistivity_ohm_m"] = -1.0
        binding["binding_digest"] = binding_digest(binding)
        validation = validate_bindings(binding, strict=True)
        self.assertFalse(validation["valid"])
        self.assertTrue(any("electrical_resistivity_ohm_m" in error for error in validation["errors"]))

    def test_incomplete_result_query_cannot_be_confirmed_and_rolls_back(self):
        binding, part = self.draft("PERF-01")
        binding["result_queries"]["voltage_drop_v"]["unit"] = "mV"
        binding["binding_digest"] = binding_digest(binding)
        before = copy.deepcopy(binding)
        with self.assertRaises(ValueError):
            confirm_bindings(binding, "reviewer", self.response(binding, part))
        self.assertEqual(binding, before)

    def test_missing_face_role_cannot_be_applied(self):
        binding, part = self.draft()
        response = self.response(binding, part)
        del response["face_roles"]["contact_target"]
        with self.assertRaises(ValueError):
            apply_geometry_response(binding, response)

    def test_tampering_invalidates_digest(self):
        binding, part = self.draft()
        confirm_bindings(binding, "reviewer", self.response(binding, part))
        binding["load_values"]["normal_overlap_mm"] = 99.0
        validation = validate_bindings(binding)
        self.assertFalse(validation["valid"])
        self.assertTrue(any("binding_digest" in error for error in validation["errors"]))
        with self.assertRaises(ValueError):
            confirm_bindings(binding, "reviewer", self.response(binding, part))

    def test_new_geometry_digest_invalidates_previous_confirmation(self):
        binding, part = self.draft()
        response = self.response(binding, part)
        confirm_bindings(binding, "reviewer", response)
        changed = self.response(binding, part, "b" * 64)
        apply_geometry_response(binding, changed)
        self.assertEqual(binding["source_geometry"]["model_digest"], "b" * 64)
        self.assertNotIn("confirmation", binding)
        self.assertEqual(binding["status"], "proposed")
        self.assertFalse(validate_bindings(binding)["valid"])

    def test_generated_solver_loads_and_result_queries_are_complete(self):
        thermal, _ = self.draft("PERF-01")
        self.assertEqual(thermal["solver"]["analysis_type"], "thermal_with_joule")
        self.assertEqual(thermal["solver"]["analysis_mode"], "steady")
        self.assertEqual(thermal["solver"]["physics_domain"], "solid")
        self.assertEqual(thermal["load_values"]["outlet_voltage_v"], 0.0)
        self.assertEqual(thermal["result_queries"]["voltage_drop_v"]["unit"], "V")

        structural, _ = self.draft("PERF-02")
        pair = structural["contact_pairs"][0]
        self.assertEqual(pair["normal_overlap_mm"], structural["load_values"]["normal_overlap_mm"])
        self.assertEqual(pair["insertion_stroke_mm"], structural["load_values"]["insertion_stroke_mm"])
        self.assertNotEqual(pair["normal_overlap_mm"], pair["insertion_stroke_mm"])
        self.assertEqual(structural["solver"]["solution_type"], "SOL 401 Multi-Step Nonlinear")
        self.assertTrue(pair["large_displacement"])
        expected_queries = set(load_binding_templates()["items"]["PERF-02"]["required_result_queries"])
        self.assertEqual(set(structural["result_queries"]), expected_queries)


if __name__ == "__main__":
    unittest.main()
