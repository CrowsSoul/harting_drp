# -*- coding: utf-8 -*-
"""注塑 11 项（DFM-08~18）规则模型 v2：新旧等价与表达式语义。"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nxdrp.checkers.injection.tests.test_injection import make_face, make_model, wall_pair
from nxdrp.contracts import Edge, ModelBundle, RuleBook
from nxdrp.pipeline import run
from nxdrp.registry import discover

MODELS = REPO_ROOT / "mockdata" / "models"
INJECTION = tuple(f"DFM-{i:02d}" for i in range(8, 19))
REGISTRY = discover()
RULEBOOK = RuleBook.load(str(REPO_ROOT / "rules" / "dfm_default.json"))

#: 已知口径修正：DFM-11 旧路径把比例量误标成 mm，v2 改标"比值"
KNOWN_UNIT_FIXES = {("DFM-11", "mm", "比值")}


def run_items(model, only=None, rulebook=None):
    return run(model, rulebook or RULEBOOK, REGISTRY, only=list(only or INJECTION))


def legacy_rulebook() -> RuleBook:
    book = RuleBook.load(str(REPO_ROOT / "rules" / "dfm_default.json"))
    for rule in book.rules:
        if rule.check_item_id in INJECTION:
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
        if (a[0], a[4], b[4]) not in KNOWN_UNIT_FIXES:
            case.assertEqual(a[4], b[4], label)
        case.assertEqual(a[5:], b[5:], label)
        for x, y in ((a[2], b[2]), (a[3], b[3])):
            if x is None or y is None:
                case.assertEqual(x, y, label)
            else:
                case.assertAlmostEqual(x, y, delta=0.011, msg=label)


# ---------------- 合成模型（覆盖注塑 11 项） ----------------
def wall_meta(values, nominal=2.0):
    return {
        "wall_samples": [
            {"part_id": "P01", "thickness_mm": v, "area_mm2": 100.0,
             "face_ids": [f"F{i + 1}"], "location": [float(i), 0.0, 0.0]}
            for i, v in enumerate(values)
        ]
    }


def variation_meta(thickness_b):
    return {"wall_samples": [
        {"part_id": "P01", "thickness_mm": 2.0, "face_ids": ["F1"], "adjacent_face_ids": ["F2"]},
        {"part_id": "P01", "thickness_mm": thickness_b, "face_ids": ["F2"]},
    ]}


def rib_meta(root, height):
    return {"ribs": [{"part_id": "P01", "root_thickness_mm": root, "height_mm": height,
                      "face_ids": ["F1"], "location": [5.0, 5.0, 2.0],
                      "origin": "upstream_feature"}]}


def boss_meta(**over):
    base = {"part_id": "P01", "outer_radius_mm": 2.0, "wall_thickness_mm": 1.0,
            "top_thickness_mm": 1.0, "root_fillet_radius_mm": 0.5,
            "side_wall_clearance_mm": 2.0, "face_ids": ["F1"],
            "location": [5.0, 5.0, 5.0], "origin": "upstream_feature"}
    base.update(over)
    return {"bosses": [base]}


def corner_meta(kind, radius):
    return {"corners": [{"part_id": "P01", "kind": kind, "radius_mm": radius,
                         "nominal_wall_mm": 2.0, "face_ids": ["F1"],
                         "location": [5.0, 5.0, 5.0], "origin": "upstream_feature"}]}


def undercut_meta(**over):
    base = {"part_id": "P01", "depth_mm": 1.0, "direction": [1.0, 0.0, 0.0],
            "face_ids": ["F1"], "location": [5.0, 5.0, 2.0]}
    base.update(over)
    return {"undercuts": [base]}


def draft_model(angle):
    rad = math.radians(angle)
    return make_model([make_face("F1", normal=(math.cos(rad), 0.0, math.sin(rad)))])


def sharp_model(dihedral):
    normal_angle = math.radians(180.0 - dihedral)
    a = make_face("F1", normal=(0.0, 0.0, 1.0), cog=(5.0, 5.0, 5.0))
    b = make_face("F2", normal=(math.sin(normal_angle), 0.0, math.cos(normal_angle)),
                  cog=(10.0, 5.0, 5.0))
    edge = Edge(edge_id="E1", part_id="P01", face_ids=["F1", "F2"], curve_type="line", length=5.0)
    return make_model([a, b], [edge], [["F1", "F2"]])


def synthetic_models():
    return [
        ("min_wall_below", make_model(wall_pair(0.5), material="PA66")),
        ("min_wall_at", make_model(wall_pair(0.8), material="PA66")),
        ("uniform_wall", make_model(meta=wall_meta([2.0, 2.0, 2.8]))),
        ("variation", make_model(meta=variation_meta(3.0))),
        ("rib_both", make_model(meta=rib_meta(1.4, 8.0))),
        ("rib_height", make_model(meta=rib_meta(1.0, 5.1))),
        ("mold_wall", make_model(meta={"ribs": [
            {"part_id": "P01", "root_thickness_mm": 2.0, "location": [0.0, 5.0, 2.0]},
            {"part_id": "P01", "root_thickness_mm": 2.0, "location": [4.0, 5.0, 2.0]}]})),
        ("draft_shallow", draft_model(0.4)),
        ("draft_edge", draft_model(0.5)),
        ("undercut", make_model(meta=undercut_meta())),
        ("undercut_no_depth", make_model(meta=undercut_meta(depth_mm=None))),
        ("boss_wall", make_model(meta=boss_meta(wall_thickness_mm=0.5))),
        ("fillet_inner", make_model(meta=corner_meta("inner", 0.4))),
        ("fillet_outer", make_model(meta=corner_meta("outer", 0.8))),
        ("multi_pull", make_model(meta={"undercuts": [
            {"part_id": "P01", "direction": [1, 0, 0], "face_ids": ["F1"], "location": [0.0, 5.0, 5.0]},
            {"part_id": "P01", "direction": [0, 1, 0], "face_ids": ["F1"], "location": [1.0, 5.0, 5.0]}]})),
        ("sharp", sharp_model(30.0)),
        ("sharp_edge", sharp_model(60.0)),
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
    def test_dfm08_critical_ratio_upgrades_severity(self):
        # 规则默认 severity=P1，用 P3 的规则库才能看出 case 级的 P1 升级
        book = RuleBook.load(str(REPO_ROOT / "rules" / "dfm_default.json"))
        book.get("DFM-08").severity = "P3"
        low = run_items(make_model(wall_pair(0.5), material="PA66"), ["DFM-08"], book).findings
        self.assertEqual(low[0].severity, "P1")          # 0.5 < 0.8 × 0.75
        near = run_items(make_model(wall_pair(0.7), material="PA66"), ["DFM-08"], book).findings
        self.assertEqual(near[0].severity, "P3")

    def test_dfm08_material_table_from_params(self):
        found = run_items(make_model(wall_pair(1.2), material="PC"), ["DFM-08"]).findings
        self.assertEqual(found[0].threshold_value, 1.5)
        skipped = run_items(make_model(wall_pair(1.2), material="UNKNOWN"), ["DFM-08"]).findings
        self.assertEqual(skipped, [])                    # 材料不在表内 → 跳过不猜

    def test_dfm14_missing_depth_reports_without_measured(self):
        found = run_items(make_model(meta=undercut_meta(depth_mm=None)), ["DFM-14"]).findings
        self.assertEqual(len(found), 1)
        self.assertIsNone(found[0].measured_value)
        self.assertEqual(found[0].threshold_value, 0.0)   # 规则默认 min_undercut_depth_mm=0

    def test_dfm16_outer_ratio_uses_if_branch(self):
        found = run_items(make_model(meta=corner_meta("outer", 0.8)), ["DFM-16"]).findings
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(found[0].threshold_value, 1.0)   # 0.5 × 2.0
        inner = run_items(make_model(meta=corner_meta("inner", 0.4)), ["DFM-16"]).findings
        self.assertAlmostEqual(inner[0].threshold_value, 0.5)   # 0.25 × 2.0

    def test_dfm11_unit_is_ratio_not_mm(self):
        found = run_items(make_model(meta=rib_meta(1.4, 8.0)), ["DFM-11"]).findings
        self.assertEqual(found[0].unit, "比值")            # 旧路径误标 mm，见 KNOWN_UNIT_FIXES

    def test_dfm09_percent_unit(self):
        found = run_items(make_model(meta=wall_meta([2.0, 2.0, 2.8])), ["DFM-09"]).findings
        self.assertEqual(found[0].unit, "%")
        self.assertAlmostEqual(found[0].measured_value, 33.33, places=2)

    def test_dfm17_threshold_is_one_direction(self):
        found = run_items(make_model(meta={"undercuts": [
            {"part_id": "P01", "direction": [1, 0, 0], "face_ids": ["F1"], "location": [0.0, 5.0, 5.0]},
            {"part_id": "P01", "direction": [0, 1, 0], "face_ids": ["F1"], "location": [1.0, 5.0, 5.0]}]}),
            ["DFM-17"]).findings
        self.assertEqual(found[0].unit, "方向")
        self.assertEqual(found[0].threshold_value, 1.0)
        self.assertEqual(found[0].measured_value, 2.0)


if __name__ == "__main__":
    unittest.main()
