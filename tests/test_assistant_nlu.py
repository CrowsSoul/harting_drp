# -*- coding: utf-8 -*-
"""离线语义解析：20 条典型指令的准确率，以及「不猜」的边界行为。"""

import unittest

from nxdrp.assistant import cases, context, nlu


class NluTests(unittest.TestCase):
    def setUp(self):
        self.models = context.available_models()

    def test_twenty_cases_accuracy(self):
        report = cases.run(models=self.models)
        self.assertEqual(report["total"], 20)
        self.assertGreaterEqual(
            report["accuracy"], 0.9, msg=f"离线解析准确率不足：{report['failures']}"
        )

    def test_missing_model_is_not_guessed(self):
        parsed = nlu.parse("跑一遍全部检查", self.models)
        self.assertEqual(parsed["spec"]["model"]["ref"], "")
        self.assertIn("model", parsed["missing"])
        self.assertLessEqual(parsed["confidence"], 0.45)

    def test_geometry_only_does_not_require_model(self):
        parsed = nlu.parse("给截面积 4 mm²、长度 10 mm、材料 Cu，算 20 A 温升", self.models)
        self.assertEqual(parsed["spec"]["model"]["ref"], "")
        self.assertNotIn("model", parsed["missing"])
        self.assertEqual(parsed["spec"]["simulation"]["conditions"]["material"], "Cu")

    def test_label_path_is_not_a_model(self):
        parsed = nlu.parse(
            "对照标注集 mockdata/labels/board_a.labels.json 评测 board_a 的 DFM-31", self.models
        )
        self.assertEqual(parsed["spec"]["model"]["ref"], "board_a")
        self.assertEqual(
            parsed["spec"]["evaluation"]["labels"], "mockdata/labels/board_a.labels.json"
        )
        self.assertEqual(parsed["spec"]["intent"], "evaluate")

    def test_skip_clause_removed_from_scope(self):
        parsed = nlu.parse("board_a 全部检查，跳过 DFM-08", self.models)
        self.assertEqual(parsed["spec"]["checks"]["only"], [])
        self.assertEqual(parsed["spec"]["checks"]["skip"], ["DFM-08"])

    def test_nx_expression_parsing(self):
        parsed = nlu.parse("把 bosses 的表达式 width 改成 2.5，再跑 DFM-08", self.models)
        self.assertEqual(parsed["spec"]["simulation"]["scenario"], "nx_parameters")
        self.assertEqual(parsed["spec"]["simulation"]["nx_parameters"], {"width": 2.5})

    def test_condition_flows_into_rule_overrides(self):
        parsed = nlu.parse("把 board_a 的电流改成 20 A，只看温升", self.models)
        overrides = parsed["spec"]["checks"]["rule_overrides"]
        self.assertEqual(overrides["PERF-01"]["current_a"], 20)

    def test_sample_filename_is_treated_as_sample(self):
        parsed = nlu.parse("board_a.model.json 跑 DFM-31", self.models)
        self.assertEqual(parsed["spec"]["model"]["ref"], "board_a")
        self.assertEqual(parsed["spec"]["model"]["kind"], "sample")

    def test_long_model_name_wins(self):
        parsed = nlu.parse("demo_asm 跑 DFM-01", self.models)
        self.assertEqual(parsed["spec"]["model"]["ref"], "demo_asm")


if __name__ == "__main__":
    unittest.main()
