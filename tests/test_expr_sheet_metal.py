# -*- coding: utf-8 -*-
"""钣金 8 项（DFM-19~26）规则模型 v2：新旧等价与表达式语义。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nxdrp.contracts import ModelBundle, RuleBook
from nxdrp.pipeline import run
from nxdrp.registry import discover

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "bent_sheet.model.json"
MODELS = REPO_ROOT / "mockdata" / "models"
SHEET = tuple(f"DFM-{i}" for i in range(19, 27))
REGISTRY = discover()
RULEBOOK = RuleBook.load(str(REPO_ROOT / "rules" / "dfm_default.json"))


def run_items(model, only=None, rulebook=None):
    return run(model, rulebook or RULEBOOK, REGISTRY, only=list(only or SHEET))


def legacy_rulebook() -> RuleBook:
    book = RuleBook.load(str(REPO_ROOT / "rules" / "dfm_default.json"))
    for rule in book.rules:
        if rule.check_item_id in SHEET:
            rule.expression = {}
            rule.exceptions = []
            rule.unit = ""
            rule.rounding = None
    return book


def verdicts(result):
    rows = [
        (f.check_item_id, f.severity, f.measured_value, f.threshold_value,
         f.unit, tuple(f.part_refs), tuple(f.evidence.face_ids))
        for f in result.findings
    ]
    return sorted(rows, key=lambda r: (r[0], r[1], r[4], r[5], r[6], round(r[2] or 0, 1)))


def assert_equal(case: unittest.TestCase, old, new, label: str):
    case.assertEqual(len(old), len(new), label)
    for a, b in zip(old, new):
        case.assertEqual(a[:2], b[:2], label)
        case.assertEqual(a[4:], b[4:], label)
        for x, y in ((a[2], b[2]), (a[3], b[3])):
            if x is None or y is None:
                case.assertEqual(x, y, label)
            else:
                case.assertAlmostEqual(x, y, delta=0.011, msg=label)


class EquivalenceTests(unittest.TestCase):
    def test_new_and_legacy_paths_agree(self):
        legacy = legacy_rulebook()
        cases = [("bent_sheet", ModelBundle.load(str(FIXTURE)))]
        cases += [(p.stem, ModelBundle.load(str(p))) for p in sorted(MODELS.glob("*.model.json"))]
        for name, model in cases:
            with self.subTest(model=name):
                assert_equal(self, verdicts(run_items(model, rulebook=legacy)),
                             verdicts(run_items(model)), name)


class ExpressionSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bent = run_items(ModelBundle.load(str(FIXTURE)))

    def findings(self, item):
        return [f for f in self.bent.findings if f.check_item_id == item]

    def test_all_sheet_rules_use_mm(self):
        for item in ("DFM-19", "DFM-20", "DFM-21", "DFM-22", "DFM-24", "DFM-25"):
            for finding in self.findings(item):
                self.assertEqual(finding.unit, "mm", item)

    def test_dfm19_threshold_is_ratio_times_thickness(self):
        found = self.findings("DFM-19")
        self.assertEqual(len(found), 1)
        # t=2.0、ratio=0.5 → 阈值 1.0，measured 为内半径
        self.assertAlmostEqual(found[0].threshold_value, 1.0)
        self.assertAlmostEqual(found[0].measured_value, 0.6)

    def test_dfm24_and_25_threshold_include_bend_radius(self):
        # 3t + R：bent_sheet 的 t=2.0、R≈0.6 → 6.6
        for item in ("DFM-24", "DFM-25"):
            found = self.findings(item)
            self.assertEqual(len(found), 1, item)
            self.assertAlmostEqual(found[0].threshold_value, 6.6, places=2)

    def test_dfm26_high_case(self):
        model = ModelBundle.load(str(MODELS / "bosses.model.json"))
        found = run_items(model, ["DFM-26"]).findings
        self.assertEqual(len(found), 1)
        self.assertGreater(found[0].measured_value, found[0].threshold_value)  # 高于上限

    def test_dfm26_low_case_uses_min_ratio(self):
        book = RuleBook.load(str(REPO_ROOT / "rules" / "dfm_default.json"))
        rule = book.get("DFM-26")
        rule.params["min_boss_height_ratio"] = 5.0
        rule.params["max_boss_height_ratio"] = 10.0
        model = ModelBundle.load(str(MODELS / "bosses.model.json"))
        found = run_items(model, ["DFM-26"], book).findings
        self.assertTrue(found)
        for finding in found:
            self.assertLess(finding.measured_value, finding.threshold_value)   # 全部低于下限
            self.assertAlmostEqual(finding.threshold_value, 5.0 * 4.786, places=2)


if __name__ == "__main__":
    unittest.main()
