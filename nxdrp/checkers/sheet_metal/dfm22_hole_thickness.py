# -*- coding: utf-8 -*-
"""DFM-22 孔径与料厚比（粗筛）。

取同轴孔组的最小直径，与 min_hole_diameter_ratio × t 比较。
料厚为规则值或 2V/A / 包围盒推断值。
"""

from __future__ import annotations

from typing import Iterable

from nxdrp.checkers.base import CheckContext
from nxdrp.contracts import Finding
from nxdrp.expr import ExprMissingSymbol

from ._sheet_metal_dfm_common import (
    SheetMetalChecker,
    emit_finding,
    positive_number,
    thickness_text,
)


class HoleDiameterThicknessChecker(SheetMetalChecker):
    check_item_id = "DFM-22"
    name = "孔径与料厚比"
    requires = ("faces", "normals", "axes", "cylindrical_faces", "face_radius")
    default_params = {
        "min_hole_diameter_ratio": 1.0,
        "sheet_thickness_mm": None,
    }

    def applies(self, model, params):
        feats = self.features(model, params)
        if not any(self.thickness(feats, hole.part_id) for hole in feats.holes):
            return False, "未识别到孔候选（粗筛）"
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        if ctx.rule.has_expression:
            return self._check_expression(ctx)
        return self._check_legacy(ctx)

    # ---------------- 规则模型 v2：孔径/t 下限判定在 R-DFM-22 的 expression 里 ----------------
    def _check_expression(self, ctx: CheckContext) -> list[Finding]:
        feats = self.features(ctx.model, ctx.params)
        findings = []
        for hole in feats.holes:
            thickness = self.thickness(feats, hole.part_id)
            if thickness is None:
                continue
            diameter = 2.0 * hole.r_min
            try:
                verdicts = ctx.evaluate(
                    {"diameter": diameter, "thickness": thickness.value}
                )
            except ExprMissingSymbol:
                continue
            faces = "、".join(hole.face_ids)
            for verdict in verdicts:
                limit = float(verdict.threshold)
                findings.append(
                    emit_finding(
                        ctx,
                        severity=verdict.severity,
                        part_id=hole.part_id,
                        face_ids=hole.face_ids,
                        message=(
                            f"【粗筛】零件 {hole.part_id} 孔组（面 {faces}）最小孔径 "
                            f"Ø{float(verdict.measured):.3f} mm < {limit / thickness.value:.2f}×t={limit:.3f} mm"
                            f"（{thickness_text(thickness)}）"
                        ),
                        measured=verdict.measured,
                        threshold=verdict.threshold,
                        unit=verdict.unit or "mm",
                        suggestion=(
                            f"将最小孔径增大到至少 {limit:.2f} mm（当前 Ø{diameter:.2f}），"
                            f"或改用激光切割/更薄板材。"
                        ),
                        thickness=thickness,
                        feature_kind="hole",
                        feature_confidence=hole.confidence,
                        location=hole.center,
                    )
                )
        return findings

    # ---------------- 旧路径：规则没有 expression 时照旧跑（兼容期保留） ----------------
    def _check_legacy(self, ctx: CheckContext) -> Iterable[Finding]:
        ratio = positive_number(ctx.param("min_hole_diameter_ratio")) or 1.0
        feats = self.features(ctx.model, ctx.params)
        findings = []
        for hole in feats.holes:
            thickness = self.thickness(feats, hole.part_id)
            if thickness is None:
                continue
            diameter = 2.0 * hole.r_min
            limit = ratio * thickness.value
            if diameter >= limit - 1e-9:
                continue
            faces = "、".join(hole.face_ids)
            findings.append(
                emit_finding(
                    ctx,
                    part_id=hole.part_id,
                    face_ids=hole.face_ids,
                    message=(
                        f"【粗筛】零件 {hole.part_id} 孔组（面 {faces}）最小孔径 "
                        f"Ø{diameter:.3f} mm < {ratio:.2f}×t={limit:.3f} mm"
                        f"（{thickness_text(thickness)}）"
                    ),
                    measured=diameter,
                    threshold=limit,
                    suggestion=(
                        f"将最小孔径增大到至少 {limit:.2f} mm（当前 Ø{diameter:.2f}），"
                        f"或改用激光切割/更薄板材。"
                    ),
                    thickness=thickness,
                    feature_kind="hole",
                    feature_confidence=hole.confidence,
                    location=hole.center,
                )
            )
        return findings


CHECKERS = [HoleDiameterThicknessChecker()]
