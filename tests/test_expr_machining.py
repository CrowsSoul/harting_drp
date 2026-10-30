# -*- coding: utf-8 -*-
"""DFM-27/28/33 规则模型 v2 迁移：边界语义、豁免子句与新旧双路径等价。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nxdrp.contracts import BBox, Face, ModelBundle, Part, RuleBook
from nxdrp.pipeline import run
from nxdrp.registry import discover

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "machining_syn.model.json"
MODELS = REPO_ROOT / "mockdata" / "models"
#: 机加工 12 项全部走规则模型 v2（W1 迁移 3 项 + W2 迁移 9 项）
MIGRATED = tuple(f"DFM-{i}" for i in range(27, 39))
REGISTRY = discover()
RULEBOOK = RuleBook.load(str(REPO_ROOT / "rules" / "dfm_default.json"))


def run_items(model, only=None, rulebook=None):
    return run(model, rulebook or RULEBOOK, REGISTRY, only=list(only or MIGRATED))


def legacy_rulebook() -> RuleBook:
    """把三条迁移规则的 expression 抹掉，得到旧判定路径的规则库。"""
    book = RuleBook.load(str(REPO_ROOT / "rules" / "dfm_default.json"))
    for rule in book.rules:
        if rule.check_item_id in MIGRATED:
            rule.expression = {}
            rule.exceptions = []
            rule.unit = ""
            rule.rounding = None      # 旧路径：机加模块默认 4 位小数
    return book


def verdicts(result):
    """Findings 的结构化投影：只比对判定口径，忽略文案。

    measured/threshold 保留原始值；比较时允许 0.011 的显示舍入差——
    v2 规则把 rounding 写进规则库，展示精度与舍入方式（四舍五入）可能与旧路径
    （Python round，4 位）不同，这是规则声明的可审计变更，不是判定漂移。
    """
    rows = [
        (f.check_item_id, f.severity, f.measured_value, f.threshold_value,
         f.unit, tuple(f.part_refs), tuple(f.evidence.face_ids))
        for f in result.findings
    ]
    return sorted(rows, key=lambda r: (r[0], r[1], r[4], r[5], r[6], round(r[2] or 0, 1)))


def assert_verdicts_equal(case: unittest.TestCase, old, new, label: str):
    case.assertEqual(len(old), len(new), label)
    for a, b in zip(old, new):
        case.assertEqual(a[:2], b[:2], label)          # check_item_id / severity
        case.assertEqual(a[4:], b[4:], label)          # unit / part_refs / face_ids
        for x, y in ((a[2], b[2]), (a[3], b[3])):
            if x is None or y is None:
                case.assertEqual(x, y, label)
            else:
                case.assertAlmostEqual(x, y, delta=0.011, msg=label)


# ---------------- 微型模型 ----------------
def plane(fid, pid, normal, point, area, bbox):
    return Face(face_id=fid, part_id=pid, solid_face_type="planar", uf_face_type=16,
                normal=normal, point=point, area=area, bbox=bbox)


def cyl(fid, pid, radius, axis, point, bbox, area=100.0):
    return Face(face_id=fid, part_id=pid, solid_face_type="cylindrical", uf_face_type=17,
                axis=axis, point=point, radius_diameter=radius, is_radius=True,
                area=area, bbox=bbox)


def torus(fid, pid, radius, axis, point, bbox, area=10.0):
    return Face(face_id=fid, part_id=pid, solid_face_type="toroidal", uf_face_type=20,
                axis=axis, point=point, radius_diameter=radius, is_radius=True,
                area=area, bbox=bbox)


def micro(parts, faces, adjacency=(), meta=None):
    return ModelBundle(
        model_id="micro", parts=list(parts), faces=list(faces),
        adjacency=[tuple(a) for a in adjacency], meta=dict(meta or {}),
    )


def block_part(pid="P1", bbox=BBox(0, 0, 0, 20, 20, 20)):
    return Part(part_id=pid, bbox=bbox, body_type="solid")


def deep_hole_model(depth):
    faces = [
        plane("B", "P1", (0, 0, -1), (10, 10, 0), 400.0, BBox(0, 0, 0, 20, 20, 0)),
        plane("T", "P1", (0, 0, 1), (10, 10, 20), 400.0, BBox(0, 0, 20, 20, 20, 20)),
        cyl("H", "P1", 2.0, (0, 0, -1), (10, 10, 20 - depth / 2),
            BBox(8, 8, 20 - depth, 12, 12, 20)),
    ]
    return micro([block_part()], faces, [("H", "T"), ("H", "B")])


def slot_model(width, depth):
    x0, x1, z_bottom, z_top = 10, 10 + width, 20 - depth, 20
    cx = (x0 + x1) / 2.0
    faces = [
        plane("W1", "P1", (1, 0, 0), (x0, 25, (z_bottom + z_top) / 2),
              (z_top - z_bottom) * 30.0, BBox(x0, 10, z_bottom, x0, 40, z_top)),
        plane("W2", "P1", (-1, 0, 0), (x1, 25, (z_bottom + z_top) / 2),
              (z_top - z_bottom) * 30.0, BBox(x1, 10, z_bottom, x1, 40, z_top)),
        plane("SB", "P1", (0, 0, 1), (cx, 25, z_bottom), width * 30.0,
              BBox(x0, 10, z_bottom, x1, 40, z_bottom)),
    ]
    return micro([block_part()], faces, [("W1", "SB"), ("W2", "SB")])


def sharp_edge_model(meta=None):
    faces = [
        plane("T", "P1", (0, 0, 1), (10, 10, 10), 400.0, BBox(0, 0, 10, 20, 20, 10)),
        plane("S", "P1", (1, 0, 0), (20, 10, 5), 100.0, BBox(20, 0, 0, 20, 20, 10)),
    ]
    return micro([block_part(bbox=BBox(0, 0, 0, 20, 20, 10))], faces, [("T", "S")], meta)


def fillet_model(radius):
    faces = [
        plane("T", "P1", (0, 0, 1), (10, 10, 10), 400.0, BBox(0, 0, 10, 20, 20, 10)),
        torus("FT", "P1", radius, (1, 0, 0), (10, 20, 9.5),
              BBox(0, 19.5, 9, 20, 20, 10)),
    ]
    return micro([block_part(bbox=BBox(0, 0, 0, 20, 20, 10))], faces)


# ---------------- 等价性：新旧双路径同模型同结果 ----------------
class EquivalenceTests(unittest.TestCase):
    def test_new_and_legacy_paths_agree(self):
        legacy = legacy_rulebook()
        cases = [
            ("machining_syn", ModelBundle.load(str(FIXTURE))),
            ("deep_slot", ModelBundle.load(str(MODELS / "deep_slot.model.json"))),
            ("plate_holes", ModelBundle.load(str(MODELS / "plate_holes.model.json"))),
            ("thin_wall", ModelBundle.load(str(MODELS / "thin_wall.model.json"))),
            ("demo_asm", ModelBundle.load(str(MODELS / "demo_asm.model.json"))),
            ("board_a", ModelBundle.load(str(MODELS / "board_a.model.json"))),
            ("deep_hole_4.01", deep_hole_model(16.04)),
            ("deep_hole_10.01", deep_hole_model(40.04)),
            ("slot_3.01", slot_model(4.0, 12.04)),
            ("sharp_edge", sharp_edge_model()),
            ("fillet_0.49", fillet_model(0.49)),
        ]
        for name, model in cases:
            with self.subTest(model=name):
                new = run_items(model)
                old = run_items(model, rulebook=legacy)
                assert_verdicts_equal(self, verdicts(old), verdicts(new), name)


# ---------------- DFM-27 ----------------
class Dfm27ExpressionTests(unittest.TestCase):
    def test_boundaries_and_severity(self):
        # 4.01 → P2；10.01 → P1；阈值取对应档
        self.assertEqual(len(run_items(deep_hole_model(16.04), ["DFM-27"]).findings), 1)
        self.assertEqual(len(run_items(deep_hole_model(16.0), ["DFM-27"]).findings), 0)
        deep = run_items(deep_hole_model(40.04), ["DFM-27"]).findings[0]
        self.assertEqual(deep.severity, "P1")
        self.assertEqual(deep.threshold_value, 10.0)
        normal = run_items(deep_hole_model(16.04), ["DFM-27"]).findings[0]
        self.assertEqual(normal.severity, "P2")
        self.assertEqual(normal.threshold_value, 4.0)
        self.assertEqual(normal.measured_value, 4.01)
        self.assertEqual(normal.unit, "比值")

    def test_params_override_still_drives_expression(self):
        book = RuleBook.load(str(REPO_ROOT / "rules" / "dfm_default.json"))
        rule = book.get("DFM-27")
        rule.params["deep_hole_ratio"] = 2.0
        result = run_items(deep_hole_model(8.04), ["DFM-27"], rulebook=book)  # 4.02 > 2
        self.assertEqual(len(result.findings), 1)


# ---------------- DFM-28 ----------------
class Dfm28ExpressionTests(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(len(run_items(slot_model(4.0, 12.04), ["DFM-28"]).findings), 1)
        self.assertEqual(len(run_items(slot_model(4.0, 12.0), ["DFM-28"]).findings), 0)
        self.assertEqual(len(run_items(slot_model(4.0, 4.0), ["DFM-28"]).findings), 0)


# ---------------- DFM-33 ----------------
class Dfm33ExpressionTests(unittest.TestCase):
    def test_small_fillet_boundary(self):
        self.assertEqual(len(run_items(fillet_model(0.49), ["DFM-33"]).findings), 1)
        self.assertEqual(len(run_items(fillet_model(0.5), ["DFM-33"]).findings), 0)

    def test_sharp_edge_reports_by_default(self):
        result = run_items(sharp_edge_model(), ["DFM-33"])
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(result.findings[0].extra["feature_kind"], "sharp_edge")
        self.assertEqual(result.findings[0].measured_value, 0.0)
        self.assertEqual(result.findings[0].threshold_value, 0.5)

    def test_sharp_edge_exemption_via_model_meta(self):
        model = sharp_edge_model(meta={"sharp_edge_exempt_parts": ["P1"]})
        self.assertEqual(len(run_items(model, ["DFM-33"]).findings), 0)

    def test_exemption_does_not_silence_fillet_case(self):
        # 豁免只作用于锐边 case：圆角 meas 里没有 exempt_edge，缺数据不豁免
        model = fillet_model(0.3)
        model.meta["sharp_edge_exempt_parts"] = ["P1"]
        self.assertEqual(len(run_items(model, ["DFM-33"]).findings), 1)


# ---------------- W2：其余 9 项的表达式语义 ----------------
class W2ExpressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = ModelBundle.load(str(FIXTURE))

    def run_fixture(self, item, rulebook=None):
        return run_items(self.fixture, [item], rulebook=rulebook)

    def test_dfm29_boolean_case_without_threshold(self):
        findings = self.run_fixture("DFM-29").findings
        self.assertEqual(len(findings), 2)
        for finding in findings:
            self.assertIsNone(finding.threshold_value)   # 布尔型 case：无阈值
            self.assertIsNotNone(finding.measured_value)
            self.assertEqual(finding.unit, "mm")

    def test_dfm30_boolean_case_without_threshold(self):
        model = ModelBundle.load(str(MODELS / "demo_asm.model.json"))
        findings = run_items(model, ["DFM-30"]).findings
        self.assertEqual(len(findings), 3)
        for finding in findings:
            self.assertIsNone(finding.threshold_value)
            self.assertTrue(finding.extra["blockers"])

    def test_dfm31_tolerance_override_drives_expression(self):
        # nearest() + 容差都来自规则参数：放宽容差后两条非标孔都变合规
        book = RuleBook.load(str(REPO_ROOT / "rules" / "dfm_default.json"))
        rule = book.get("DFM-31")
        self.assertEqual(len(self.run_fixture("DFM-31", rulebook=book).findings), 2)
        rule.params["tolerance_mm"] = 0.25
        self.assertEqual(len(self.run_fixture("DFM-31", rulebook=book).findings), 0)

    def test_dfm34_size_case_uses_mm_unit(self):
        findings = self.run_fixture("DFM-34").findings
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].unit, "mm")           # 角度合格 → 命中尺寸 case
        self.assertAlmostEqual(findings[0].threshold_value, 0.5)

    def test_dfm36_threshold_is_nearest_standard_angle(self):
        findings = self.run_fixture("DFM-36").findings
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].unit, "deg")
        self.assertAlmostEqual(findings[0].threshold_value, 30.0)  # 20° 最近标准角

    def test_dfm37_and_38_units(self):
        self.assertEqual(self.run_fixture("DFM-37").findings[0].unit, "mm")
        self.assertEqual(self.run_fixture("DFM-38").findings[0].unit, "deg")


if __name__ == "__main__":
    unittest.main()
