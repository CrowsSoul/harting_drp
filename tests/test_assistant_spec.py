# -*- coding: utf-8 -*-
"""TaskSpec 契约：合法任务单能过，越界字段必须报错。"""

import unittest

from nxdrp.assistant import spec


def valid(**overrides):
    data = {
        "spec_version": "1.0",
        "intent": "check",
        "instruction": "board_a 跑 DFM-31",
        "model": {"ref": "board_a", "kind": "sample"},
        "checks": {"only": ["DFM-31"]},
    }
    data.update(overrides)
    return data


class TaskSpecTests(unittest.TestCase):
    def test_valid_spec_roundtrip(self):
        task = spec.validate_spec(valid())
        self.assertEqual(task.model.ref, "board_a")
        self.assertEqual(task.effective_only(), ["DFM-31"])
        self.assertEqual(spec.validate_spec(task.to_dict()).to_dict(), task.to_dict())

    def test_unknown_field_rejected(self):
        with self.assertRaises(spec.TaskSpecError) as caught:
            spec.validate_spec(valid(rule_version="2"))
        self.assertIn("rule_version", str(caught.exception))

    def test_unknown_check_item_rejected(self):
        with self.assertRaises(spec.TaskSpecError):
            spec.validate_spec(valid(checks={"only": ["DFM-99"]}))

    def test_only_and_skip_conflict(self):
        with self.assertRaises(spec.TaskSpecError) as caught:
            spec.validate_spec(valid(checks={"only": ["DFM-31"], "skip": ["DFM-31"]}))
        self.assertIn("不能同时在", str(caught.exception))

    def test_non_finite_condition_rejected(self):
        with self.assertRaises(spec.TaskSpecError):
            spec.validate_spec(
                valid(
                    intent="predict",
                    simulation={"scenario": "current_temp", "conditions": {"current_a": float("nan")}},
                )
            )

    def test_unknown_condition_key_rejected(self):
        with self.assertRaises(spec.TaskSpecError) as caught:
            spec.validate_spec(
                valid(
                    intent="predict",
                    simulation={"scenario": "current_temp", "conditions": {"voltage_v": 24}},
                )
            )
        self.assertIn("voltage_v", str(caught.exception))

    def test_rule_override_types(self):
        task = spec.validate_spec(
            valid(checks={"only": ["PERF-01"], "rule_overrides": {"PERF-01": {"current_a": 20}}})
        )
        self.assertEqual(task.checks.rule_overrides["PERF-01"]["current_a"], 20)
        with self.assertRaises(spec.TaskSpecError):
            spec.validate_spec(
                valid(checks={"only": ["PERF-01"], "rule_overrides": {"PERF-01": {"current_a": {"x": 1}}}})
            )

    def test_model_required_for_checks(self):
        with self.assertRaises(spec.TaskSpecError) as caught:
            spec.validate_spec({"intent": "check", "model": {"ref": ""}})
        self.assertIn("model.ref", str(caught.exception))

    def test_geometry_only_prediction_needs_no_model(self):
        task = spec.validate_spec(
            {
                "intent": "predict",
                "model": {"ref": ""},
                "simulation": {
                    "scenario": "current_temp",
                    "conditions": {"area_mm2": 3.5, "length_mm": 12, "material": "Cu", "current_a": 25},
                },
            }
        )
        self.assertEqual(task.model.ref, "")
        self.assertEqual(task.simulation.scenario, "current_temp")

    def test_pipeline_requires_scenario_check_in_scope(self):
        with self.assertRaises(spec.TaskSpecError) as caught:
            spec.validate_spec(
                valid(
                    intent="pipeline",
                    checks={"only": ["DFM-31"]},
                    simulation={"scenario": "current_temp", "conditions": {"current_a": 20}},
                )
            )
        self.assertIn("PERF-01", str(caught.exception))

    def test_nx_parameters_requires_an_expression(self):
        with self.assertRaises(spec.TaskSpecError):
            spec.validate_spec(
                valid(intent="simulate", simulation={"scenario": "nx_parameters", "nx_parameters": {}})
            )

    def test_simcenter_operation_validated(self):
        with self.assertRaises(spec.TaskSpecError):
            spec.validate_spec(
                valid(
                    intent="simulate",
                    model={"ref": "p" * 32, "kind": "upload"},
                    simulation={"scenario": "simcenter", "conditions": {"operation": "run"}},
                )
            )

    def test_condition_merges_into_rule_params(self):
        task = spec.validate_spec(
            valid(
                intent="pipeline",
                checks={"only": ["PERF-01"]},
                simulation={"scenario": "current_temp", "conditions": {"current_a": 22}},
            )
        )
        merged = task.apply_rule_params("PERF-01", {"current_a": 16.0, "max_rise_c": 45.0})
        self.assertEqual(merged["current_a"], 22.0)
        self.assertEqual(merged["max_rise_c"], 45.0)

    def test_zero_ambient_allowed_but_zero_current_rejected(self):
        task = spec.validate_spec(
            valid(
                intent="predict",
                simulation={"scenario": "current_temp", "conditions": {"ambient_temp_c": 0}},
            )
        )
        self.assertEqual(task.simulation.conditions["ambient_temp_c"], 0)
        with self.assertRaises(spec.TaskSpecError):
            spec.validate_spec(
                valid(
                    intent="predict",
                    simulation={"scenario": "current_temp", "conditions": {"current_a": 0}},
                )
            )

    def test_json_schema_shape(self):
        schema = spec.json_schema()
        self.assertEqual(schema["type"], "object")
        self.assertIn("intent", schema["properties"])
        self.assertIn("model", schema["required"])
        self.assertEqual(set(schema["properties"]["intent"]["enum"]), set(spec.INTENTS))


if __name__ == "__main__":
    unittest.main()
