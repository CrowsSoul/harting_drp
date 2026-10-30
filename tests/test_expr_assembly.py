# -*- coding: utf-8 -*-
"""装配 7 项（DFM-01~07）规则模型 v2：新旧等价与表达式语义。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nxdrp.checkers.assembly.test_assembly import (
    _NxStub,
    fastener_row,
    hole_rows,
    model_with_gap,
)
from nxdrp.contracts import ModelBundle, RuleBook
from nxdrp.pipeline import run
from nxdrp.registry import discover

MODELS = REPO_ROOT / "mockdata" / "models"
ASSEMBLY = tuple(f"DFM-{i:02d}" for i in range(1, 8))
REGISTRY = discover()
RULEBOOK = RuleBook.load(str(REPO_ROOT / "rules" / "dfm_default.json"))


def run_items(model, only=None, rulebook=None, nx=None):
    return run(model, rulebook or RULEBOOK, REGISTRY, only=list(only or ASSEMBLY), nx=nx)


def legacy_rulebook() -> RuleBook:
    book = RuleBook.load(str(REPO_ROOT / "rules" / "dfm_default.json"))
    for rule in book.rules:
        if rule.check_item_id in ASSEMBLY:
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


def synthetic_models():
    def aligned(offset, diameter_b=4.0):
        return model_with_gap(1.0, {"holes": hole_rows(offset=offset, diameter_b=diameter_b)})

    def slot(offset, angle_axis=(0, 0, 1)):
        return model_with_gap(1.0, {
            "holes": [hole_rows()[0]],
            "slots": [{"feature_id": "S", "mate_id": "M1", "part_id": "B",
                       "center": [5 + offset, 5, 0], "axis": list(angle_axis),
                       "width_mm": 5, "face_ids": ["B-S1"]}],
        })

    def fastener(**updates):
        return model_with_gap(1.0, {"fasteners": [fastener_row(**updates)]})

    return [
        ("interference", model_with_gap(-1.0)),
        ("contact", model_with_gap(0.0)),
        ("interference_annotated", model_with_gap(1.0, {
            "interferences": [{"part_ids": ["A", "B"], "volume_mm3": 0.5,
                               "face_ids": ["A-F1", "B-F1"]}]})),
        ("clearance_0.1", model_with_gap(0.1)),
        ("clearance_0.3", model_with_gap(0.3)),
        ("clearance_0.301", model_with_gap(0.301)),
        ("hole_offset", aligned(0.2)),
        ("hole_good", aligned(0.0)),
        ("hole_diameter", aligned(0.0, diameter_b=4.2)),
        ("slot_offset", slot(0.3)),
        ("slot_good", slot(0.0)),
        ("tool_diameter", fastener(available_tool_diameter_mm=9.9)),
        ("tool_height", fastener(available_tool_height_mm=39.9)),
        ("tool_inaccessible", fastener(accessible=False)),
        ("tool_good", fastener()),
        ("radial", fastener(radial_clearance_mm=0.49)),
        ("axial", fastener(axial_clearance_mm=0.49)),
        ("both_clearance", fastener(radial_clearance_mm=0.2, axial_clearance_mm=0.2)),
        ("steel_short", fastener(engagement_length_mm=3.9)),
        ("steel_ok", fastener(engagement_length_mm=4.0)),
        ("plastic_short", fastener(material="plastic", engagement_length_mm=5.9)),
        ("plastic_ok", fastener(material="plastic", engagement_length_mm=6.0)),
    ]


class EquivalenceTests(unittest.TestCase):
    def test_new_and_legacy_paths_agree(self):
        legacy = legacy_rulebook()
        cases = [(p.stem, ModelBundle.load(str(p))) for p in sorted(MODELS.glob("*.model.json"))]
        cases += synthetic_models()
        for name, model in cases:
            with self.subTest(model=name):
                assert_equal(self, verdicts(run_items(model, rulebook=legacy)),
                             verdicts(run_items(model)), name)


class ExpressionSemanticsTests(unittest.TestCase):
    def test_dfm02_precise_vs_coarse_severity(self):
        coarse = run_items(model_with_gap(0.1), ["DFM-02"]).findings
        self.assertEqual(coarse[0].severity, "P3")          # 无 NX：包围盒粗筛
        precise = run_items(model_with_gap(0.1), ["DFM-02"], nx=_NxStub(0.2)).findings
        self.assertEqual(precise[0].severity, "P2")         # 精确测距
        self.assertEqual(precise[0].extra["method"], "nx_minimum_distance")

    def test_dfm01_units_and_threshold(self):
        found = run_items(model_with_gap(-1.0), ["DFM-01"]).findings
        self.assertEqual(found[0].unit, "mm^3")
        self.assertEqual(found[0].severity, "P1")
        self.assertGreater(found[0].measured_value, found[0].threshold_value)

    def test_dfm05_accessible_flag(self):
        found = run_items(
            model_with_gap(1.0, {"fasteners": [fastener_row(accessible=False)]}),
            ["DFM-05"],
        ).findings
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].measured_value, 10.0)     # 可用直径
        self.assertEqual(found[0].threshold_value, 10.0)    # 要求直径

    def test_dfm06_reports_both_directions(self):
        found = run_items(
            model_with_gap(1.0, {"fasteners": [fastener_row(
                radial_clearance_mm=0.2, axial_clearance_mm=0.2)]}),
            ["DFM-06"],
        ).findings
        self.assertEqual(len(found), 2)
        self.assertEqual({f.extra["clearance_direction"] for f in found}, {"radial", "axial"})

    def test_dfm07_material_branch(self):
        steel = run_items(
            model_with_gap(1.0, {"fasteners": [fastener_row(engagement_length_mm=3.9)]}),
            ["DFM-07"],
        ).findings
        self.assertAlmostEqual(steel[0].threshold_value, 1.0)
        plastic = run_items(
            model_with_gap(1.0, {"fasteners": [fastener_row(
                material="plastic", engagement_length_mm=5.9)]}),
            ["DFM-07"],
        ).findings
        self.assertAlmostEqual(plastic[0].threshold_value, 1.5)


if __name__ == "__main__":
    unittest.main()
