# -*- coding: utf-8 -*-
"""DFM-19 最小弯曲半径（粗筛）。

识别与两个互不平行平面相邻的圆柱面作为折弯候选，读取其内半径 R，
与 min_bend_radius_ratio × t 比较。弯曲线取圆柱轴线，不是真实切线。
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


class BendRadiusChecker(SheetMetalChecker):
    check_item_id = "DFM-19"
    name = "最小弯曲半径"
    requires = ("faces", "normals", "axes", "cylindrical_faces", "face_radius")
    default_params = {
        "min_bend_radius_ratio": 0.5,
        "sheet_thickness_mm": None,
    }

    def applies(self, model, params):
        feats = self.features(model, params)
        if not any(self.thickness(feats, bend.part_id) for bend in feats.bends):
            return False, "未识别到折弯候选圆柱面（粗筛）"
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        if ctx.rule.has_expression:
            return self._check_expression(ctx)
        return self._check_legacy(ctx)

    # ---------------- 规则模型 v2：R/t 下限判定在 R-DFM-19 的 expression 里 ----------------
    def _check_expression(self, ctx: CheckContext) -> list[Finding]:
        feats = self.features(ctx.model, ctx.params)
        findings = []
        for bend in feats.bends:
            thickness = self.thickness(feats, bend.part_id)
            if thickness is None:
                continue
            try:
                verdicts = ctx.evaluate(
                    {"radius": bend.radius, "thickness": thickness.value}
                )
            except ExprMissingSymbol:
                continue
            for verdict in verdicts:
                limit = float(verdict.threshold)
                findings.append(
                    emit_finding(
                        ctx,
                        severity=verdict.severity,
                        part_id=bend.part_id,
                        face_ids=[bend.face.face_id],
                        message=(
                            f"【粗筛】零件 {bend.part_id} 折弯面 {bend.face.face_id} "
                            f"内 R={bend.radius:.3f} mm，R/t={bend.radius / thickness.value:.2f} "
                            f"< 下限 {limit / thickness.value:.2f}（{thickness_text(thickness)}）"
                        ),
                        measured=verdict.measured,
                        threshold=verdict.threshold,
                        unit=verdict.unit or "mm",
                        suggestion=(
                            f"将折弯内圆角半径增大到至少 {limit:.2f} mm"
                            f"（{limit / thickness.value:.2f}×t），或改用更薄的板材。"
                        ),
                        thickness=thickness,
                        feature_kind="bend",
                        feature_confidence=bend.confidence,
                        location=bend.point,
                    )
                )
        return findings

    # ---------------- 旧路径：规则没有 expression 时照旧跑（兼容期保留） ----------------
    def _check_legacy(self, ctx: CheckContext) -> Iterable[Finding]:
        ratio = positive_number(ctx.param("min_bend_radius_ratio")) or 0.5
        feats = self.features(ctx.model, ctx.params)
        findings = []
        for bend in feats.bends:
            thickness = self.thickness(feats, bend.part_id)
            if thickness is None:
                continue
            limit = ratio * thickness.value
            if bend.radius >= limit - 1e-9:
                continue
            findings.append(
                emit_finding(
                    ctx,
                    part_id=bend.part_id,
                    face_ids=[bend.face.face_id],
                    message=(
                        f"【粗筛】零件 {bend.part_id} 折弯面 {bend.face.face_id} "
                        f"内 R={bend.radius:.3f} mm，R/t={bend.radius / thickness.value:.2f} "
                        f"< 下限 {ratio:.2f}（{thickness_text(thickness)}）"
                    ),
                    measured=bend.radius,
                    threshold=limit,
                    suggestion=(
                        f"将折弯内圆角半径增大到至少 {limit:.2f} mm（{ratio:.2f}×t），"
                        f"或改用更薄的板材。"
                    ),
                    thickness=thickness,
                    feature_kind="bend",
                    feature_confidence=bend.confidence,
                    location=bend.point,
                )
            )
        return findings


CHECKERS = [BendRadiusChecker()]
