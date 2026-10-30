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
MIGRATED = ("DFM-27", "DFM-28", "DFM-33")
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


def _round(value):
    return None if value is None else round(value, 2)


def verdicts(result):
    """Findings 的结构化投影：只比对判定口径，忽略文案。

    measured/threshold 统一对齐到 2 位小数——v2 规则把 rounding=2 写进规则库，
    展示精度从旧路径的 4 位变 2 位，这是规则声明的可审计变更，不是判定漂移。
    """
    return sorted(
        (f.check_item_id, f.severity, _round(f.measured_value), _round(f.threshold_value),
         f.unit, tuple(f.part_refs), tuple(f.evidence.face_ids))
        for f in result.findings
    )


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
                self.assertEqual(verdicts(old), verdicts(new), name)


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


if __name__ == "__main__":
    unittest.main()
